"""Session persistence helpers and the per-session Claude call context."""
from __future__ import annotations

from collections import OrderedDict
from typing import Any

from .. import config, db, ingest
from ..claude_client import CallContext
from ..errors import AppError
from ..prompts.system import material_preamble


def get_session(session_id: str) -> dict[str, Any]:
    row = db.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
    if not row:
        raise AppError("not_found", "That study session no longer exists.")
    row["config"] = db.loads(row.pop("config_json"), {})
    row["error"] = db.loads(row.pop("error_json"), None)
    return row


def update_session(session_id: str, **fields: Any) -> None:
    if "config" in fields:
        fields["config_json"] = db.dumps(fields.pop("config"))
    if "error" in fields:
        err = fields.pop("error")
        fields["error_json"] = db.dumps(err) if err is not None else None
    db.update("sessions", "id", session_id, fields)


def get_subtopics(session_id: str) -> list[dict[str, Any]]:
    return db.query("SELECT id, name, description, position FROM subtopics WHERE session_id = ? ORDER BY position", (session_id,))


def get_uploads(session_id: str) -> list[dict[str, Any]]:
    return db.query(
        "SELECT u.* FROM uploads u JOIN session_documents d ON d.upload_id = u.id "
        "WHERE d.session_id = ? ORDER BY d.position",
        (session_id,),
    )


def load_question(question_id: str) -> dict[str, Any]:
    row = db.query_one("SELECT * FROM questions WHERE id = ?", (question_id,))
    if not row:
        raise AppError("not_found", "Question not found.")
    row["payload"] = db.loads(row.pop("payload_json"))
    row["display"] = db.loads(row.pop("display_json"))
    return row


def load_answer(question_id: str) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM answers WHERE question_id = ?", (question_id,))
    if row:
        row["response"] = db.loads(row.pop("response_json"), {})
        row["details"] = db.loads(row.pop("details_json"), {})
        row["skipped"] = bool(row["skipped"])
    return row


def progress(session_id: str) -> dict[str, int]:
    s = db.query_one(
        "SELECT "
        " (SELECT COUNT(*) FROM questions WHERE session_id = ? AND status = 'served') AS served,"
        " (SELECT COUNT(*) FROM answers WHERE session_id = ?) AS answered,"
        " (SELECT COUNT(*) FROM answers WHERE session_id = ? AND grade_status = 'pending') AS grading,"
        " (SELECT COUNT(DISTINCT slot) FROM questions WHERE session_id = ? AND status != 'discarded') AS generated",
        (session_id, session_id, session_id, session_id),
    )
    return dict(s)  # type: ignore[arg-type]


# Base64-encoding large PDFs on every call is wasteful; keep a few sessions' blocks in memory.
_prefix_cache: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
_PREFIX_CACHE_SIZE = 4


def call_context(session: dict[str, Any]) -> CallContext:
    sid = session["id"]
    blocks = _prefix_cache.get(sid)
    if blocks is None:
        uploads = get_uploads(sid)
        blocks = ingest.content_blocks(uploads)
        preamble = material_preamble(session["material"], session["subject"], bool(uploads))
        # The breakpoint goes on the last block shared by every call in the session.
        blocks.append({"type": "text", "text": preamble, "cache_control": {"type": "ephemeral", "ttl": "1h"}})
        _prefix_cache[sid] = blocks
        while len(_prefix_cache) > _PREFIX_CACHE_SIZE:
            _prefix_cache.popitem(last=False)
    else:
        _prefix_cache.move_to_end(sid)
    cfg = session["config"]
    return CallContext(
        session_id=sid,
        model=cfg.get("model", config.DEFAULT_MODEL),
        effort=cfg.get("effort", config.DEFAULT_EFFORT),
        fallback=cfg.get("fallback", True),
        prefix_blocks=blocks,
    )


def forget_context(session_id: str) -> None:
    _prefix_cache.pop(session_id, None)
