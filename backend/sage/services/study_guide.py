"""Study guides: one structured call per subtopic, run in parallel.

Two kinds, same section format and graphics:
  * weak_areas: after a quiz, for the subtopics the student did poorly on (one per quiz);
  * subtopics: from a Study Set's Material Breakdown, for the subtopics the student picked, using their
    quiz history on each subtopic when they have one."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .. import db
from ..errors import AppError
from ..llm_client import CallContext, structured_call
from ..prompts.study_guide import diagram_repair_instruction, section_instruction
from ..schemas.guide import DIAGRAM_REPAIR_SCHEMA, STUDY_SECTION_SCHEMA, DiagramRepair, StudySection
from . import sessions as S
from . import sets_core as C
from .results import results
from .set_mastery import misses_for, set_mastery

log = logging.getLogger(__name__)
_tasks: dict[str, asyncio.Task] = {}
MAX_MISSES_PER_SECTION = 8


def _load(guide_id: str) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM guides WHERE id = ?", (guide_id,))
    if row:
        row["content"] = db.loads(row.pop("content_json"), {"sections": []})
        row["error"] = db.loads(row.pop("error_json"), None)
        row["subtopic_ids"] = db.loads(row.pop("subtopic_ids_json"), [])
    return row


def _save(guide_id: str, **fields: Any) -> None:
    if "content" in fields:
        fields["content_json"] = db.dumps(fields.pop("content"))
    if "error" in fields:
        err = fields.pop("error")
        fields["error_json"] = db.dumps(err) if err else None
    db.update("guides", "id", guide_id, fields)


def _update_section(guide_id: str, subtopic_id: str, **changes: Any) -> None:
    # Runs on the event loop thread with no awaits between read and write, so concurrent
    # section tasks can't interleave here.
    guide = _load(guide_id)
    assert guide is not None
    for sec in guide["content"]["sections"]:
        if sec["subtopic_id"] == subtopic_id:
            sec.update(changes)
    _save(guide_id, content=guide["content"])


def _running(guide_id: str) -> bool:
    t = _tasks.get(guide_id)
    return bool(t and not t.done())


def get_guide(guide_id: str) -> dict[str, Any] | None:
    guide = _load(guide_id)
    if guide and guide["status"] == "generating" and not _running(guide_id):
        # App restarted mid-generation: mark unfinished sections failed so they can be retried.
        for sec in guide["content"]["sections"]:
            if sec["status"] == "pending":
                sec["status"] = "failed"
                sec["error"] = {"code": "interrupted", "message": "Generation was interrupted. Retry this section.", "retryable": True}
        _finalize(guide_id, guide["content"])
        guide = _load(guide_id)
    return guide


def require(guide_id: str) -> dict[str, Any]:
    guide = get_guide(guide_id)
    if not guide:
        raise AppError("not_found", "That study guide no longer exists.")
    return guide


def session_guide_id(session_id: str) -> str | None:
    row = db.query_one("SELECT id FROM guides WHERE session_id = ? AND kind = 'weak_areas'", (session_id,))
    return row["id"] if row else None


def get_session_guide(session_id: str) -> dict[str, Any] | None:
    gid = session_guide_id(session_id)
    return get_guide(gid) if gid else None


def _finalize(guide_id: str, content: dict[str, Any]) -> None:
    ready = any(s["status"] == "ready" for s in content["sections"])
    pending = any(s["status"] == "pending" for s in content["sections"])
    status = "generating" if pending else ("ready" if ready else "failed")
    _save(guide_id, content=content, status=status)


def _launch(guide_id: str, subtopic_ids: list[str]) -> None:
    async def run() -> None:
        await asyncio.gather(*(_build_section(guide_id, sid) for sid in subtopic_ids))
        g = _load(guide_id)
        if g:
            _finalize(guide_id, g["content"])

    _tasks[guide_id] = asyncio.get_running_loop().create_task(run())


# --- Starting ----------------------------------------------------------------------------------

def start(session_id: str, force: bool = False) -> dict[str, Any]:
    """Weak-areas guide for a finished quiz (one per quiz; `force` rebuilds it)."""
    session = S.get_session(session_id)
    if session["status"] != "completed":
        raise AppError("conflict", "Finish the session before generating a study guide.")
    existing = get_session_guide(session_id)
    if existing and not force and existing["status"] in ("generating", "ready"):
        return existing

    res = results(session_id)
    weak = [s for s in res["mastery"]["subtopics"] if s["weak"]]
    if not weak:
        raise AppError("bad_request", "No weak areas to cover. Every subtopic is at 70% or above with no confidently wrong answers.")
    content = {
        "generated_at": db.now(),
        "overall_score": res["mastery"]["overall"]["score"],
        "sections": [
            {"subtopic_id": s["id"], "name": s["name"], "score": s["score"], "weak_reasons": s["weak_reasons"],
             "status": "pending", "section": None, "error": None}
            for s in weak
        ],
    }
    ids = [s["id"] for s in weak]
    if existing:
        guide_id = existing["id"]
        _save(guide_id, status="generating", content=content, error=None, subtopic_ids_json=db.dumps(ids))
    else:
        guide_id = db.new_id()
        db.insert("guides", {"id": guide_id, "set_id": session.get("study_set_id"), "session_id": session_id,
                             "kind": "weak_areas", "subtopic_ids_json": db.dumps(ids), "status": "generating",
                             "content_json": db.dumps(content), "created_at": db.now()})
    _launch(guide_id, ids)
    return _load(guide_id)  # type: ignore[return-value]


def start_for_subtopics(set_id: str, subtopic_ids: list[str]) -> dict[str, Any]:
    """Study guide for chosen subtopics of a Study Set's breakdown."""
    C.get_set(set_id)
    subs = {s["id"]: s for s in C.subtopics(set_id)}
    chosen = [sid for sid in dict.fromkeys(subtopic_ids) if sid in subs]
    if not chosen:
        raise AppError("bad_request", "Pick at least one subtopic.")
    mastery = set_mastery(set_id)
    scores = [mastery[s]["score"] for s in chosen if s in mastery and mastery[s]["score"] is not None]
    content = {
        "generated_at": db.now(),
        "overall_score": round(sum(scores) / len(scores), 1) if scores else None,
        "sections": [
            {"subtopic_id": sid, "name": subs[sid]["name"], "score": (mastery.get(sid) or {}).get("score"),
             "weak_reasons": (mastery.get(sid) or {}).get("weak_reasons", []), "status": "pending", "section": None, "error": None}
            for sid in chosen
        ],
    }
    guide_id = db.new_id()
    db.insert("guides", {"id": guide_id, "set_id": set_id, "session_id": None, "kind": "subtopics",
                         "subtopic_ids_json": db.dumps(chosen), "status": "generating",
                         "content_json": db.dumps(content), "created_at": db.now()})
    C.update_set(set_id)
    _launch(guide_id, chosen)
    return _load(guide_id)  # type: ignore[return-value]


# --- Building sections ---------------------------------------------------------------------------

def _misses_for(res: dict[str, Any], subtopic_id: str) -> list[dict[str, Any]]:
    misses = [q for q in res["missed"] if q["subtopic_id"] == subtopic_id]
    # Confidently-wrong answers first: those misconceptions matter most.
    misses.sort(key=lambda q: (not q["confidently_wrong"], q["score"] or 0))
    return misses[:MAX_MISSES_PER_SECTION]


def _section_request(guide: dict[str, Any], subtopic_id: str) -> tuple[CallContext, str, str]:
    """(context, instruction, focus) for one section."""
    if guide["kind"] == "weak_areas":
        session = S.get_session(guide["session_id"])
        res = results(guide["session_id"])
        sub = next(s for s in res["mastery"]["subtopics"] if s["id"] == subtopic_id)
        misses = _misses_for(res, subtopic_id)
        return (S.call_context(session), section_instruction(sub, sub["score"], sub["weak_reasons"], misses),
                f'{sub["name"]} {sub.get("description", "")} ' + " ".join(m["prompt"] for m in misses))
    st = C.get_set(guide["set_id"])
    sub = next((s for s in C.subtopics(guide["set_id"], include_removed=True) if s["id"] == subtopic_id), None)
    if sub is None:
        raise AppError("not_found", "That subtopic is no longer part of this study set.")
    m = set_mastery(guide["set_id"]).get(subtopic_id) or {}
    misses = misses_for(guide["set_id"], subtopic_id)
    concepts = ", ".join(sub["key_concepts"])
    described = {"name": sub["name"], "description": sub["summary"] + (f" Key concepts: {concepts}." if concepts else "")}
    return (C.set_context(st), section_instruction(described, m.get("score"), m.get("weak_reasons", []), misses, mode="topic"),
            f'{sub["name"]} {sub["summary"]} {concepts} ' + " ".join(x["prompt"] for x in misses))


async def _build_section(guide_id: str, subtopic_id: str) -> None:
    try:
        guide = _load(guide_id)
        assert guide is not None
        ctx, instruction, focus = _section_request(guide, subtopic_id)
        section: StudySection = await structured_call(
            ctx, purpose="study_guide", instruction=instruction, schema=STUDY_SECTION_SCHEMA,
            validate=StudySection.model_validate, focus=focus,
        )
        _update_section(guide_id, subtopic_id, status="ready", section=section.model_dump(), error=None)
    except AppError as e:
        _update_section(guide_id, subtopic_id, status="failed", error=e.to_dict())
    except Exception as e:  # noqa: BLE001
        log.exception("study guide section failed")
        _update_section(guide_id, subtopic_id, status="failed",
                        error=AppError("server_error", "This section failed to generate.", detail=repr(e)).to_dict())


def retry_section(guide_id: str, subtopic_id: str) -> dict[str, Any]:
    guide = require(guide_id)
    if not any(s["subtopic_id"] == subtopic_id for s in guide["content"]["sections"]):
        raise AppError("not_found", "That section isn't part of this study guide.")
    _update_section(guide_id, subtopic_id, status="pending", error=None)
    _save(guide_id, status="generating")
    _launch(guide_id, [subtopic_id])
    return _load(guide_id)  # type: ignore[return-value]


async def repair_diagram(guide_id: str, subtopic_id: str, error: str) -> dict[str, Any]:
    guide = require(guide_id)
    sec = next((s for s in guide["content"]["sections"] if s["subtopic_id"] == subtopic_id), None)
    if not sec or not sec.get("section"):
        raise AppError("not_found", "That section isn't available.")
    diagram = sec["section"]["diagram"]
    if diagram.get("repaired"):
        raise AppError("conflict", "This diagram was already repaired once.")
    ctx = S.call_context(S.get_session(guide["session_id"])) if guide["kind"] == "weak_areas" else C.set_context(C.get_set(guide["set_id"]))
    fixed: DiagramRepair = await structured_call(
        ctx,
        purpose="diagram_repair",
        instruction=diagram_repair_instruction(diagram["mermaid"], error),
        schema=DIAGRAM_REPAIR_SCHEMA,
        validate=DiagramRepair.model_validate,
        focus=sec["name"],
    )
    section = sec["section"]
    section["diagram"] = {**diagram, "mermaid": fixed.mermaid, "repaired": True}
    _update_section(guide_id, subtopic_id, section=section)
    return section


# --- Views -----------------------------------------------------------------------------------------

def meta(guide: dict[str, Any]) -> dict[str, Any]:
    """Title and context for the guide page and exports."""
    if guide["kind"] == "weak_areas":
        s = S.get_session(guide["session_id"])
        return {"title": s["title"] or "Study session", "subject": s["subject"], "date": s["created_at"],
                "set_id": guide["set_id"], "session_id": guide["session_id"], "kind": "weak_areas"}
    st = C.get_set(guide["set_id"])
    return {"title": st["title"] or "Study set", "subject": st["subject"], "date": guide["created_at"],
            "set_id": guide["set_id"], "session_id": None, "kind": "subtopics"}


def guide_view(guide: dict[str, Any]) -> dict[str, Any]:
    return {"id": guide["id"], "status": guide["status"], "content": guide["content"], "kind": guide["kind"],
            "created_at": guide["created_at"], "meta": meta(guide)}


def set_guides(set_id: str) -> list[dict[str, Any]]:
    out = []
    for r in db.query("SELECT id FROM guides WHERE set_id = ? ORDER BY created_at DESC", (set_id,)):
        g = get_guide(r["id"])
        if g:
            secs = g["content"].get("sections", [])
            out.append({"id": g["id"], "kind": g["kind"], "status": g["status"], "created_at": g["created_at"],
                        "session_id": g["session_id"], "subtopics": [s["name"] for s in secs]})
    return out
