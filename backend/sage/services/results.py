"""Finishing a session and assembling the results dashboard data."""
from __future__ import annotations

from typing import Any

from .. import config, db
from . import generation, grading
from . import sessions as S
from .mastery import compute_mastery, is_confidently_wrong, subtopic_trends
from .presentation import correct_answer_text, user_answer_text


def answered_items(session_id: str) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT q.id, q.position, q.type, q.subtopic_id, q.difficulty, q.payload_json, q.display_json, "
        "a.response_json, a.confidence, a.skipped, a.grade_status, a.score, a.verdict, a.feedback, "
        "a.model_answer, a.misconception, a.details_json, a.grade_error, a.graded_by "
        "FROM questions q JOIN answers a ON a.question_id = q.id "
        "WHERE q.session_id = ? ORDER BY q.position",
        (session_id,),
    )
    items = []
    for r in rows:
        payload = db.loads(r["payload_json"])
        display = db.loads(r["display_json"])
        response = db.loads(r["response_json"], {})
        item = {
            "id": r["id"],
            "position": r["position"],
            "type": r["type"],
            "type_label": config.TYPE_LABELS[r["type"]],
            "subtopic_id": r["subtopic_id"],
            "subtopic_name": display.get("subtopic_name", ""),
            "difficulty": r["difficulty"],
            "prompt": payload["prompt"],
            "display": display,
            "uses_outside_knowledge": payload["uses_outside_knowledge"],
            "confidence": r["confidence"],
            "skipped": bool(r["skipped"]),
            "grade_status": r["grade_status"],
            "grade_error": db.loads(r["grade_error"], None),
            "score": r["score"],
            "verdict": r["verdict"],
            "feedback": r["feedback"] or "",
            "misconception": r["misconception"] or "",
            "explanation": payload.get("explanation", ""),
            "your_answer": user_answer_text(payload, display, response, bool(r["skipped"])),
            "correct_answer": r["model_answer"] or correct_answer_text(payload),
            "criteria": (db.loads(r["details_json"], {}) or {}).get("criteria", []),
            "graded_by": r["graded_by"],
        }
        item["confidently_wrong"] = is_confidently_wrong(item)
        items.append(item)
    return items


def _seconds_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    from datetime import datetime

    return max(0.0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())


def ai_summary(session_id: str) -> dict[str, Any]:
    """AI calls made and time spent waiting on Claude, overall and per step."""
    rows = db.query(
        "SELECT purpose, COUNT(*) AS calls, SUM(1 - ok) AS failed, SUM(duration_ms) / 1000.0 AS seconds "
        "FROM ai_calls WHERE session_id = ? GROUP BY purpose ORDER BY MIN(id)",
        (session_id,),
    )
    for r in rows:
        r["seconds"] = round(r["seconds"] or 0, 1)
    total = {
        "calls": sum(r["calls"] for r in rows),
        "failed": sum(r["failed"] or 0 for r in rows),
        "seconds": round(sum(r["seconds"] for r in rows), 1),
    }
    return {"total": total, "by_purpose": rows}


async def finish(session_id: str) -> dict[str, Any]:
    session = S.get_session(session_id)
    if session["status"] != "completed":
        generation.stop_worker(session_id)
        await grading.wait_for_grades(session_id)
        # Drop prefetched or served-but-unanswered questions.
        db.execute(
            "UPDATE questions SET status = 'discarded' WHERE session_id = ? AND id NOT IN "
            "(SELECT question_id FROM answers WHERE session_id = ?)",
            (session_id, session_id),
        )
        mastery = compute_mastery(answered_items(session_id), S.get_subtopics(session_id))
        S.update_session(session_id, status="completed", completed_at=db.now(), score=mastery["overall"]["score"], error=None)
    return results(session_id)


def results(session_id: str) -> dict[str, Any]:
    session = S.get_session(session_id)
    items = answered_items(session_id)
    subtopics = S.get_subtopics(session_id)
    mastery = compute_mastery(items, subtopics)
    guide = db.query_one("SELECT status FROM study_guides WHERE session_id = ?", (session_id,))
    return {
        "session": {
            "id": session["id"],
            "title": session["title"],
            "subject": session["subject"],
            "created_at": session["created_at"],
            "completed_at": session["completed_at"],
            "status": session["status"],
            "config": {k: v for k, v in session["config"].items() if k != "slots"},
            "docs_truncated": session["config"].get("docs_truncated", False),
            "parent_session_id": session["parent_session_id"],
        },
        "mastery": mastery,
        "questions": items,
        "missed": [i for i in items if i["verdict"] != "correct" or i["confidently_wrong"]],
        "ungraded": [i["id"] for i in items if i["grade_status"] != "done"],
        "ai": ai_summary(session_id),
        "session_seconds": _seconds_between(session["created_at"], session["completed_at"]),
        "study_guide_status": guide["status"] if guide else None,
    }


def history() -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT s.id, s.created_at, s.completed_at, s.subject, s.title, s.status, s.score, s.parent_session_id, "
        "s.config_json, (SELECT COUNT(*) FROM answers a WHERE a.session_id = s.id) AS answered, "
        "(SELECT COUNT(*) FROM ai_calls c WHERE c.session_id = s.id) AS ai_calls, "
        "(SELECT SUM(duration_ms) FROM ai_calls c WHERE c.session_id = s.id) / 1000.0 AS ai_seconds, "
        "(SELECT status FROM study_guides g WHERE g.session_id = s.id) AS guide_status "
        "FROM sessions s ORDER BY s.created_at DESC"
    )
    out = []
    for r in rows:
        cfg = db.loads(r.pop("config_json"), {})
        r["count"] = cfg.get("count")
        r["adaptive"] = cfg.get("adaptive")
        r["ai_seconds"] = round(r["ai_seconds"] or 0, 1)
        r["session_seconds"] = _seconds_between(r["created_at"], r["completed_at"])
        out.append(r)
    return out


def subjects() -> list[str]:
    return [r["subject"] for r in db.query(
        "SELECT subject, MAX(created_at) AS last FROM sessions WHERE subject != '' GROUP BY subject ORDER BY last DESC"
    )]


def trends(subject: str) -> dict[str, Any]:
    sessions = db.query(
        "SELECT id, created_at, score, title FROM sessions WHERE subject = ? AND status = 'completed' ORDER BY created_at",
        (subject,),
    )
    data = []
    for s in sessions:
        m = compute_mastery(answered_items(s["id"]), S.get_subtopics(s["id"]))
        data.append({
            "session_id": s["id"], "created_at": s["created_at"], "score": s["score"], "title": s["title"],
            "subtopics": [{"name": r["name"], "score": r["score"]} for r in m["subtopics"]],
        })
    return {
        "subject": subject,
        "sessions": [{k: d[k] for k in ("session_id", "created_at", "score", "title")} for d in data],
        "subtopics": subtopic_trends(data),
    }
