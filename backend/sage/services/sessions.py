"""Session persistence helpers and the per-session Claude call context."""
from __future__ import annotations

from collections import OrderedDict
from typing import Any

from .. import config, db, ingest
from ..errors import AppError
from ..llm_client import CallContext
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
    out = dict(s)  # type: ignore[arg-type]
    # Skipped questions waiting at the end, including ones being rewritten after an options change.
    cfg = db.loads((db.query_one("SELECT config_json FROM sessions WHERE id = ?", (session_id,)) or {}).get("config_json"), {}) or {}
    served = {r["slot"] for r in db.query("SELECT slot FROM questions WHERE session_id = ? AND status = 'served'", (session_id,))}
    plan = cfg.get("slots") or []
    out["skipped_waiting"] = len([x for x in cfg.get("deferred_slots", []) if x not in served and x < len(plan) and plan[x]])
    return out


# Reading extracted text from disk for every call is cheap, but keep a few sessions' material loaded.
_material_cache: OrderedDict[str, ingest.Material] = OrderedDict()
_MATERIAL_CACHE_SIZE = 4


def call_context(session: dict[str, Any]) -> CallContext:
    sid = session["id"]
    material = _material_cache.get(sid)
    if material is None:
        material = ingest.load_material(get_uploads(sid))
        _material_cache[sid] = material
        while len(_material_cache) > _MATERIAL_CACHE_SIZE:
            _material_cache.popitem(last=False)
    else:
        _material_cache.move_to_end(sid)
    cfg = session["config"]
    has_docs = bool(material.texts or material.files)
    return CallContext(
        session_id=sid,
        model_fast=cfg.get("model_fast", config.DEFAULT_MODEL_FAST),
        model_smart=cfg.get("model_smart", config.DEFAULT_MODEL_SMART),
        material=material,
        preamble=material_preamble(session["material"], session["subject"], has_docs),
    )


def forget_context(session_id: str) -> None:
    _material_cache.pop(session_id, None)
