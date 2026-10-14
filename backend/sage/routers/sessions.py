from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, Field

from .. import config, db, ingest
from ..errors import AppError
from ..schemas.questions import AnswerSubmission
from ..services import chat, generation, grading, results
from ..services import sessions as S

router = APIRouter(prefix="/api", tags=["sessions"])


# --- Uploads -------------------------------------------------------------------------------

@router.post("/uploads")
async def upload(file: UploadFile = File(...)) -> dict:
    data = await file.read(config.MAX_FILE_MB * 1024 * 1024 + 1)
    return ingest.save_upload(file.filename or "upload", data)


@router.delete("/uploads/{upload_id}")
def delete_upload(upload_id: str) -> dict:
    ingest.delete_upload(upload_id)
    return {"ok": True}


# --- Sessions --------------------------------------------------------------------------------

class SessionIn(BaseModel):
    material: str = ""
    subject: str = ""
    upload_ids: list[str] = Field(default_factory=list)
    types: list[str]
    difficulty: int = 3
    adaptive: bool = False
    count: int = 10
    languages: list[str] = Field(default_factory=list)
    language: str | None = None  # older clients: a single code language


def session_view(session_id: str) -> dict[str, Any]:
    s = S.get_session(session_id)
    cfg = {k: v for k, v in s["config"].items() if k not in ("slots", "deferred_slots")}
    return {
        "id": s["id"],
        "title": s["title"],
        "subject": s["subject"],
        "material": s["material"],
        "status": s["status"],
        "error": s["error"],
        "created_at": s["created_at"],
        "config": cfg,
        "current_difficulty": s["current_difficulty"],
        "subtopics": S.get_subtopics(session_id),
        "documents": [ingest.public_upload(u) for u in S.get_uploads(session_id)],
        "progress": S.progress(session_id),
        "generating": generation.worker_running(session_id),
        "editable": s["status"] != "completed",
    }


@router.post("/sessions")
async def create_session(body: SessionIn) -> dict:
    session_id = generation.create_session(
        material=body.material,
        subject=body.subject,
        upload_ids=body.upload_ids,
        types=body.types,
        difficulty=body.difficulty,
        adaptive=body.adaptive,
        count=body.count,
        languages=body.languages or [body.language or "Python"],
        settings=db.get_settings(),
    )
    generation.ensure_worker(session_id)
    return session_view(session_id)


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    return session_view(session_id)


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict:
    S.get_session(session_id)
    generation.stop_worker(session_id)
    upload_ids = [r["upload_id"] for r in db.query("SELECT upload_id FROM session_documents WHERE session_id = ?", (session_id,))]
    with db.connect() as conn:
        conn.execute("DELETE FROM answers WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM questions WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM subtopics WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM study_guides WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM session_documents WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM ai_calls WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM question_chats WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM question_reports WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    for uid in upload_ids:
        ingest.delete_upload(uid)  # only removes files no other session uses
    S.forget_context(session_id)
    return {"ok": True}


@router.post("/sessions/{session_id}/retry")
async def retry(session_id: str) -> dict:
    S.forget_context(session_id)
    generation.retry(session_id)
    return session_view(session_id)


@router.get("/sessions/{session_id}/next")
async def next_question(session_id: str) -> dict:
    out = generation.next_question(session_id)
    out["progress"] = S.progress(session_id)
    return out


class OptionsIn(BaseModel):
    types: list[str]
    difficulty: int
    adaptive: bool
    count: int
    languages: list[str] = Field(default_factory=list)
    language: str | None = None  # older clients: a single code language
    feedback_mode: str = "immediate"


@router.put("/sessions/{session_id}/options")
async def update_options(session_id: str, body: OptionsIn) -> dict:
    """Change question options mid-session; only questions not yet answered or on screen are affected."""
    opts = body.model_dump()
    legacy = opts.pop("language")
    opts["languages"] = opts["languages"] or [legacy or "Python"]
    generation.update_options(session_id, **opts)
    return session_view(session_id)


@router.post("/questions/{question_id}/defer")
async def defer(question_id: str) -> dict:
    """'Skip for now': move the on-screen question to the end of the quiz."""
    return generation.defer_question(question_id)


class ChatIn(BaseModel):
    message: str


@router.get("/questions/{question_id}/chat")
def get_chat(question_id: str) -> dict:
    return chat.chat_view(question_id)


@router.post("/questions/{question_id}/chat")
async def ask_claude(question_id: str, body: ChatIn) -> dict:
    """'Ask Claude' about this question. Before the answer is revealed, Claude helps without giving it away."""
    return await chat.ask(question_id, body.message)


class ReportIn(BaseModel):
    reason: str
    note: str = ""


@router.post("/questions/{question_id}/report")
async def report(question_id: str, body: ReportIn) -> dict:
    """Report a poorly made question. Unanswered: replaced by a new question at the end.
    Answered: kept but left out of the score."""
    return generation.report_question(question_id, body.reason, body.note)


@router.post("/questions/{question_id}/answer")
async def answer(question_id: str, body: AnswerSubmission) -> dict:
    return await grading.submit_answer(question_id, body)


@router.post("/questions/{question_id}/regrade")
async def regrade(question_id: str) -> dict:
    return await grading.regrade(question_id)


@router.get("/questions/{question_id}/answer")
def get_answer(question_id: str) -> dict:
    q = S.load_question(question_id)
    if not S.load_answer(question_id):
        raise AppError("not_found", "Not answered yet.")
    s = S.get_session(q["session_id"])
    return grading.answer_view(question_id, reveal=s["config"]["feedback_mode"] == "immediate" or s["status"] == "completed")


@router.post("/sessions/{session_id}/finish")
async def finish(session_id: str) -> dict:
    return await results.finish(session_id)


@router.get("/sessions/{session_id}/results")
def get_results(session_id: str) -> dict:
    return results.results(session_id)


class RetestIn(BaseModel):
    count: int | None = None


@router.post("/sessions/{session_id}/retest")
async def retest(session_id: str, body: RetestIn | None = None) -> dict:
    res = results.results(session_id)
    if res["session"]["status"] != "completed":
        raise AppError("conflict", "Finish the session before starting a retest.")
    weak = [s for s in res["mastery"]["subtopics"] if s["weak"]]
    if not weak:
        raise AppError("bad_request", "There are no weak areas to retest.")
    parent = S.get_session(session_id)
    cfg = parent["config"]
    upload_ids = [u["id"] for u in S.get_uploads(session_id)]
    count = (body.count if body and body.count else None) or cfg["count"]
    new_id = generation.create_session(
        material=parent["material"],
        subject=parent["subject"],
        upload_ids=upload_ids,
        types=cfg["types"],
        difficulty=cfg["difficulty"],
        adaptive=cfg["adaptive"],
        count=count,
        languages=cfg["languages"],
        settings={**db.get_settings(), "model_fast": cfg.get("model_fast", config.DEFAULT_MODEL_FAST),
                  "model_smart": cfg.get("model_smart", config.DEFAULT_MODEL_SMART)},
        subtopics=[{"name": s["name"], "description": s["description"]} for s in weak],
        parent_session_id=session_id,
    )
    title = parent["title"] or "Study session"
    S.update_session(new_id, title=f"Retest: {title}"[:120])
    generation.ensure_worker(new_id)
    return session_view(new_id)


# --- History ---------------------------------------------------------------------------------

@router.get("/history")
def history() -> list[dict]:
    return results.history()


@router.get("/subjects")
def subjects() -> list[str]:
    return results.subjects()


@router.get("/trends")
def trends(subject: str) -> dict:
    return results.trends(subject)
