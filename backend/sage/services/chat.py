"""'Ask Claude': a per-question tutoring chat. Messages are stored per question, so reopening the
chat (or the app) shows the conversation so far."""
from __future__ import annotations

from typing import Any

from .. import config, db
from ..errors import AppError
from ..llm_client import structured_call
from ..prompts.chat import chat_instruction
from ..schemas.guide import CHAT_SCHEMA, ChatOut
from . import sessions as S
from .grading import answer_view
from .presentation import correct_answer_text


def _mode(question_id: str, session: dict[str, Any]) -> str:
    ans = S.load_answer(question_id)
    if ans is None:
        return "unanswered"
    revealed = session["config"]["feedback_mode"] == "immediate" or session["status"] == "completed"
    return "revealed" if revealed and ans["grade_status"] == "done" else "answered_hidden"


def _messages(question_id: str) -> list[dict[str, Any]]:
    return db.query("SELECT id, role, content, created_at FROM question_chats WHERE question_id = ? ORDER BY id", (question_id,))


def _load(question_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    q = S.load_question(question_id)
    if q["status"] not in ("served", "deferred"):
        raise AppError("not_found", "This question isn't part of the quiz anymore.")
    return q, S.get_session(q["session_id"])


def chat_view(question_id: str) -> dict[str, Any]:
    q, session = _load(question_id)
    return {"question_id": question_id, "mode": _mode(question_id, session), "messages": _messages(question_id)}


async def ask(question_id: str, message: str) -> dict[str, Any]:
    text = message.strip()
    if not text:
        raise AppError("bad_request", "Type a question first.")
    if len(text) > config.CHAT_MESSAGE_MAX_CHARS:
        raise AppError("bad_request", f"That message is too long. Keep it under {config.CHAT_MESSAGE_MAX_CHARS:,} characters.")
    q, session = _load(question_id)
    mode = _mode(question_id, session)
    history = [{"role": m["role"], "content": m["content"]} for m in _messages(question_id)][-config.CHAT_HISTORY_MESSAGES:]
    result = answer_view(question_id, reveal=True) if mode == "revealed" else None
    out: ChatOut = await structured_call(
        S.call_context(session),
        purpose="chat",
        instruction=chat_instruction(
            q["display"], correct_answer_text(q["payload"]), q["payload"].get("explanation", ""), mode, history, text, result,
        ),
        schema=CHAT_SCHEMA,
        validate=ChatOut.model_validate,
        focus=f'{q["display"].get("subtopic_name", "")} {q["payload"]["prompt"]} {text}',
        doc_budget=config.CHAT_DOC_CHAR_BUDGET,
    )
    # Save the exchange only once Claude has replied, so a failed request leaves no orphan message.
    with db.connect() as conn:
        for role, content in (("user", text), ("assistant", out.reply)):
            conn.execute(
                "INSERT INTO question_chats (question_id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (question_id, q["session_id"], role, content, db.now()),
            )
    return {"question_id": question_id, "mode": mode, "messages": _messages(question_id)}
