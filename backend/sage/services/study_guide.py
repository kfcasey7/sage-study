"""Study guide generation: one structured call per weak subtopic, run in parallel."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .. import db
from ..llm_client import structured_call
from ..errors import AppError
from ..prompts.study_guide import diagram_repair_instruction, section_instruction
from ..schemas.guide import DIAGRAM_REPAIR_SCHEMA, STUDY_SECTION_SCHEMA, DiagramRepair, StudySection
from . import sessions as S
from .results import results

log = logging.getLogger(__name__)
_tasks: dict[str, asyncio.Task] = {}
MAX_MISSES_PER_SECTION = 8


def _load(session_id: str) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM study_guides WHERE session_id = ?", (session_id,))
    if row:
        row["content"] = db.loads(row.pop("content_json"), {"sections": []})
        row["error"] = db.loads(row.pop("error_json"), None)
    return row


def _save(session_id: str, **fields: Any) -> None:
    if "content" in fields:
        fields["content_json"] = db.dumps(fields.pop("content"))
    if "error" in fields:
        err = fields.pop("error")
        fields["error_json"] = db.dumps(err) if err else None
    db.update("study_guides", "session_id", session_id, fields)


def _update_section(session_id: str, subtopic_id: str, **changes: Any) -> None:
    # Runs on the event loop thread with no awaits between read and write, so concurrent
    # section tasks can't interleave here.
    guide = _load(session_id)
    assert guide is not None
    for sec in guide["content"]["sections"]:
        if sec["subtopic_id"] == subtopic_id:
            sec.update(changes)
    _save(session_id, content=guide["content"])


def get_guide(session_id: str) -> dict[str, Any] | None:
    guide = _load(session_id)
    if guide and guide["status"] == "generating" and not (_tasks.get(session_id) and not _tasks[session_id].done()):
        # App restarted mid-generation: mark unfinished sections failed so they can be retried.
        for sec in guide["content"]["sections"]:
            if sec["status"] == "pending":
                sec["status"] = "failed"
                sec["error"] = {"code": "interrupted", "message": "Generation was interrupted. Retry this section.", "retryable": True}
        _finalize(session_id, guide["content"])
        guide = _load(session_id)
    return guide


def _finalize(session_id: str, content: dict[str, Any]) -> None:
    ready = any(s["status"] == "ready" for s in content["sections"])
    pending = any(s["status"] == "pending" for s in content["sections"])
    status = "generating" if pending else ("ready" if ready else "failed")
    _save(session_id, content=content, status=status)


def start(session_id: str, force: bool = False) -> dict[str, Any]:
    session = S.get_session(session_id)
    if session["status"] != "completed":
        raise AppError("conflict", "Finish the session before generating a study guide.")
    existing = get_guide(session_id)
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
    if existing:
        _save(session_id, status="generating", content=content, error=None)
    else:
        db.insert("study_guides", {"session_id": session_id, "status": "generating",
                                   "content_json": db.dumps(content), "created_at": db.now()})
    _tasks[session_id] = asyncio.get_running_loop().create_task(_build(session_id, [s["id"] for s in weak]))
    return _load(session_id)  # type: ignore[return-value]


def _misses_for(res: dict[str, Any], subtopic_id: str) -> list[dict[str, Any]]:
    misses = [q for q in res["missed"] if q["subtopic_id"] == subtopic_id]
    # Confidently-wrong answers first: those misconceptions matter most.
    misses.sort(key=lambda q: (not q["confidently_wrong"], q["score"] or 0))
    return misses[:MAX_MISSES_PER_SECTION]


async def _build_section(session_id: str, subtopic_id: str) -> None:
    session = S.get_session(session_id)
    res = results(session_id)
    sub = next(s for s in res["mastery"]["subtopics"] if s["id"] == subtopic_id)
    try:
        section: StudySection = await structured_call(
            S.call_context(session),
            purpose="study_guide",
            instruction=section_instruction(sub, sub["score"], sub["weak_reasons"], _misses_for(res, subtopic_id)),
            schema=STUDY_SECTION_SCHEMA,
            validate=StudySection.model_validate,
            focus=f'{sub["name"]} {sub.get("description", "")} ' + " ".join(m["prompt"] for m in _misses_for(res, subtopic_id)),
        )
        _update_section(session_id, subtopic_id, status="ready", section=section.model_dump(), error=None)
    except AppError as e:
        _update_section(session_id, subtopic_id, status="failed", error=e.to_dict())
    except Exception as e:  # noqa: BLE001
        log.exception("study guide section failed")
        _update_section(session_id, subtopic_id, status="failed",
                        error=AppError("server_error", "This section failed to generate.", detail=repr(e)).to_dict())


async def _build(session_id: str, subtopic_ids: list[str]) -> None:
    await asyncio.gather(*(_build_section(session_id, sid) for sid in subtopic_ids))
    guide = _load(session_id)
    if guide:
        _finalize(session_id, guide["content"])


def retry_section(session_id: str, subtopic_id: str) -> dict[str, Any]:
    guide = get_guide(session_id)
    if not guide:
        raise AppError("not_found", "No study guide for this session yet.")
    if not any(s["subtopic_id"] == subtopic_id for s in guide["content"]["sections"]):
        raise AppError("not_found", "That section isn't part of this study guide.")
    _update_section(session_id, subtopic_id, status="pending", error=None)
    _save(session_id, status="generating")

    async def run() -> None:
        await _build_section(session_id, subtopic_id)
        g = _load(session_id)
        if g:
            _finalize(session_id, g["content"])

    _tasks[session_id] = asyncio.get_running_loop().create_task(run())
    return _load(session_id)  # type: ignore[return-value]


async def repair_diagram(session_id: str, subtopic_id: str, error: str) -> dict[str, Any]:
    guide = get_guide(session_id)
    if not guide:
        raise AppError("not_found", "No study guide for this session yet.")
    sec = next((s for s in guide["content"]["sections"] if s["subtopic_id"] == subtopic_id), None)
    if not sec or not sec.get("section"):
        raise AppError("not_found", "That section isn't available.")
    diagram = sec["section"]["diagram"]
    if diagram.get("repaired"):
        raise AppError("conflict", "This diagram was already repaired once.")
    fixed: DiagramRepair = await structured_call(
        S.call_context(S.get_session(session_id)),
        purpose="diagram_repair",
        instruction=diagram_repair_instruction(diagram["mermaid"], error),
        schema=DIAGRAM_REPAIR_SCHEMA,
        validate=DiagramRepair.model_validate,
        focus=sec["name"],
    )
    section = sec["section"]
    section["diagram"] = {**diagram, "mermaid": fixed.mermaid, "repaired": True}
    _update_section(session_id, subtopic_id, section=section)
    return section
