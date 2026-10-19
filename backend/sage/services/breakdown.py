"""Material Breakdown: one Claude call that maps a Study Set's sources and prompts into an overview,
subtopics (summary, key concepts, formulas, difficulty, sources), a relationship map, and coverage notes.

Appending (a new prompt and/or sources) regenerates it in merge mode: Claude sees the current
subtopics with their ids and keeps the ones still covered, and `merge_subtopics` matches what comes
back to the stored rows. Subtopic ids stay stable, so quiz mastery stays attached; subtopics that are
dropped are marked removed rather than deleted, so old results keep their names."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .. import db
from ..errors import AppError
from ..llm_client import structured_call
from ..prompts.breakdown import breakdown_instruction
from ..prompts.study_guide import diagram_repair_instruction
from ..schemas.breakdown import BREAKDOWN_SCHEMA, Breakdown, make_validator
from ..schemas.guide import DIAGRAM_REPAIR_SCHEMA, DiagramRepair
from . import sets_core as C
from . import sources as Src

log = logging.getLogger(__name__)
_tasks: dict[str, asyncio.Task] = {}

CONTENT_FIELDS = ("name", "summary", "key_concepts", "formulas", "difficulty", "source_ids")


def _norm(name: str) -> str:
    return " ".join(name.lower().split())


def merge_subtopics(existing: list[dict[str, Any]], returned: list[dict[str, Any]], version: int,
                    new_id=db.new_id) -> tuple[list[dict[str, Any]], list[str]]:
    """Match a regenerated breakdown's subtopics to the stored ones.

    existing: stored subtopics (active and removed) with id, status, created_version, updated_version and
              the CONTENT_FIELDS.
    returned: Claude's subtopics with `ref`, `change` and the CONTENT_FIELDS, in display order.
    Returns (rows to store, in order, each with id/position/status/versions; ids that are now removed).

    A returned subtopic matches the stored one whose id equals its ref, else one with the same name
    (Claude sometimes drops the ref); otherwise it is new. A match keeps its id; its updated_version
    becomes `version` only when Claude says it changed and its content really differs. A removed
    subtopic that comes back is reactivated and counts as updated."""
    by_id = {e["id"]: e for e in existing}
    by_name: dict[str, dict[str, Any]] = {}
    for e in sorted(existing, key=lambda e: e["status"] != "active"):
        by_name.setdefault(_norm(e["name"]), e)
    used: set[str] = set()
    rows: list[dict[str, Any]] = []
    for pos, r in enumerate(returned):
        match = by_id.get(r.get("ref") or "")
        if match is None or match["id"] in used:
            match = by_name.get(_norm(r["name"]))
            if match is not None and match["id"] in used:
                match = None
        content = {k: r[k] for k in CONTENT_FIELDS}
        if match is None:
            rows.append({"id": new_id(), **content, "position": pos, "status": "active",
                         "created_version": version, "updated_version": version})
            continue
        used.add(match["id"])
        differs = any(match.get(k) != content[k] for k in ("name", "summary", "key_concepts", "formulas"))
        revived = match["status"] != "active"
        changed = revived or (differs and r.get("change") != "unchanged")
        rows.append({"id": match["id"], **content, "position": pos, "status": "active",
                     "created_version": match["created_version"],
                     "updated_version": version if changed else match["updated_version"]})
    removed = [e["id"] for e in existing if e["id"] not in used and e["status"] == "active"]
    return rows, removed


def _store(set_id: str, rows: list[dict[str, Any]], removed: list[str]) -> None:
    with db.connect() as conn:
        for r in rows:
            fields = {
                "name": r["name"], "summary": r["summary"], "key_concepts_json": db.dumps(r["key_concepts"]),
                "formulas_json": db.dumps(r["formulas"]), "difficulty": r["difficulty"],
                "source_ids_json": db.dumps(r["source_ids"]), "position": r["position"], "status": "active",
                "created_version": r["created_version"], "updated_version": r["updated_version"],
            }
            if conn.execute("SELECT 1 FROM set_subtopics WHERE id = ?", (r["id"],)).fetchone():
                conn.execute(f"UPDATE set_subtopics SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                             [*fields.values(), r["id"]])
            else:
                conn.execute(f"INSERT INTO set_subtopics (id, set_id, {', '.join(fields)}) VALUES (?, ?, {', '.join('?' for _ in fields)})",
                             [r["id"], set_id, *fields.values()])
        base = len(rows)
        for i, sid in enumerate(removed):
            conn.execute("UPDATE set_subtopics SET status = 'removed', position = ? WHERE id = ?", (base + i, sid))


def running(set_id: str) -> bool:
    t = _tasks.get(set_id)
    return bool(t and not t.done())


def start(set_id: str, new_source_ids: list[str] | None = None) -> None:
    """(Re)generate the breakdown in the background."""
    st = C.get_set(set_id)
    if running(set_id):
        return
    C.update_set(set_id, breakdown_status="generating", breakdown_error=None)
    _tasks[set_id] = asyncio.get_running_loop().create_task(_run(set_id, st["breakdown_status"], set(new_source_ids or [])))


def check_interrupted(st: dict[str, Any]) -> dict[str, Any]:
    """App restarted mid-generation: mark it failed so it can be retried."""
    if st["breakdown_status"] == "generating" and not running(st["id"]):
        err = {"code": "interrupted", "message": "Building the breakdown was interrupted. Try again.", "retryable": True}
        C.update_set(st["id"], breakdown_status="failed", breakdown_error=err)
        st = C.get_set(st["id"])
    return st


async def _run(set_id: str, previous_status: str, new_source_ids: set[str]) -> None:
    try:
        await Src.wait_for_set(set_id)
        st = C.get_set(set_id)
        version = st["breakdown_version"] + 1
        labels = Src.labels(set_id)
        source_views = [{**Src.view(s, labels[s["id"]]), "new": s["id"] in new_source_ids} for s in Src.set_sources(set_id)]
        all_subs = C.subtopics(set_id, include_removed=True)
        # Migrated sets send their old subtopics too, so the quiz results attached to them carry over.
        existing_active = [s for s in all_subs if s["status"] == "active"]
        ctx = C.set_context(st)
        prompts = C.prompts(set_id)
        breakdown: Breakdown = await structured_call(
            ctx,
            purpose="breakdown",
            instruction=breakdown_instruction(prompts, source_views, existing_active, version),
            schema=BREAKDOWN_SCHEMA,
            validate=make_validator(set(labels.values())),
            focus=" ".join(p["text"] for p in prompts) + " " + " ".join(s["name"] for s in existing_active),
        )
        label_to_id = {v: k for k, v in labels.items()}
        returned = [{
            "ref": s.ref.strip(), "change": s.change, "name": s.name, "summary": s.summary.strip(),
            "key_concepts": s.key_concepts, "formulas": [f.model_dump() for f in s.formulas],
            "difficulty": s.difficulty, "source_ids": [label_to_id[x] for x in s.sources if x in label_to_id],
        } for s in breakdown.subtopics]
        rows, removed = merge_subtopics(all_subs, returned, version)
        _store(set_id, rows, removed)
        marks = previous_status == "ready" or (previous_status == "failed" and bool(st["breakdown"]))
        failed_titles = [s["title"] for s in source_views if s["status"] == "failed"]
        fields: dict[str, Any] = {
            "breakdown_status": "ready", "breakdown_error": None, "breakdown_version": version,
            "breakdown_sources_key": C.sources_key(set_id),
            "breakdown": {
                "overview": breakdown.overview.strip(), "map_mermaid": breakdown.map_mermaid.strip(), "map_repaired": False,
                "coverage_notes": breakdown.coverage_notes, "generated_at": db.now(),
                # Badges only make sense when there was a full breakdown to compare with.
                "marks_changes": marks, "unreadable_sources": failed_titles,
                "removed": [s["name"] for s in all_subs if s["id"] in removed],
            },
        }
        if not st["title"].strip():
            fields["title"] = breakdown.title.strip()[:120] or "Study set"
        C.update_set(set_id, **fields)
    except AppError as e:
        log.warning("breakdown for %s failed: %s", set_id, e.code)
        C.update_set(set_id, breakdown_status="failed", breakdown_error=e.to_dict())
    except Exception as e:  # noqa: BLE001
        log.exception("breakdown for %s crashed", set_id)
        C.update_set(set_id, breakdown_status="failed",
                     breakdown_error=AppError("server_error", "Building the breakdown failed unexpectedly.", detail=repr(e)).to_dict())
    finally:
        _tasks.pop(set_id, None)


async def repair_map(set_id: str, error: str) -> dict[str, Any]:
    st = C.get_set(set_id)
    bd = st["breakdown"]
    if not bd or not bd.get("map_mermaid"):
        raise AppError("not_found", "This breakdown has no map.")
    if bd.get("map_repaired"):
        raise AppError("conflict", "The map was already repaired once.")
    fixed: DiagramRepair = await structured_call(
        C.set_context(st), purpose="diagram_repair", instruction=diagram_repair_instruction(bd["map_mermaid"], error),
        schema=DIAGRAM_REPAIR_SCHEMA, validate=DiagramRepair.model_validate, doc_budget=4000,
    )
    bd = {**bd, "map_mermaid": fixed.mermaid, "map_repaired": True}
    C.update_set(set_id, breakdown=bd)
    return bd
