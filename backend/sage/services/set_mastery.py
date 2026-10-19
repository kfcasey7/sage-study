"""Mastery per Study Set subtopic, across every quiz taken on the set. Each quiz keeps its own
snapshot of subtopics; `subtopics.set_subtopic_id` links them to the set's, so results stay attached
as the breakdown changes. Reported questions don't count, as in quiz results."""
from __future__ import annotations

from typing import Any

from .. import db
from . import results
from . import sets_core as C
from .mastery import compute_mastery


def set_items(set_id: str) -> list[dict[str, Any]]:
    """Scored answers from all of the set's quizzes, keyed by set subtopic id, oldest first."""
    links = {r["id"]: r["set_subtopic_id"] for r in db.query(
        "SELECT t.id, t.set_subtopic_id FROM subtopics t JOIN sessions s ON s.id = t.session_id WHERE s.study_set_id = ?",
        (set_id,))}
    items = []
    for s in db.query("SELECT id, created_at FROM sessions WHERE study_set_id = ? ORDER BY created_at", (set_id,)):
        for it in results.scored(results.answered_items(s["id"])):
            target = links.get(it["subtopic_id"])
            if target:
                items.append({**it, "session_id": s["id"], "session_subtopic_id": it["subtopic_id"], "subtopic_id": target})
    return items


def set_mastery(set_id: str) -> dict[str, dict[str, Any]]:
    """{set_subtopic_id: {score, n, correct, ..., weak, weak_reasons}} for subtopics with graded answers."""
    items = set_items(set_id)
    if not items:
        return {}
    m = compute_mastery(items, C.subtopics(set_id, include_removed=True))
    return {row["id"]: row for row in m["subtopics"] if row["n"]}


def misses_for(set_id: str, subtopic_id: str, limit: int = 4) -> list[dict[str, Any]]:
    """Most recent missed (or confidently wrong) answers on a set subtopic."""
    misses = [i for i in set_items(set_id) if i["subtopic_id"] == subtopic_id
              and (i["verdict"] != "correct" or i["confidently_wrong"])]
    return misses[-limit:][::-1]
