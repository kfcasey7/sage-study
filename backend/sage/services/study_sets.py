"""Study Sets: a title, prompts, sources, the current Material Breakdown, and every quiz, study guide,
and playlist made from it."""
from __future__ import annotations

from typing import Any

from .. import db, migrations
from ..errors import AppError
from . import breakdown, generation, study_guide
from . import sessions as S
from . import sets_core as C
from . import sources as Src
from .set_mastery import set_mastery


def create(*, subject: str, title: str, prompt: str, source_ids: list[str]) -> str:
    if not prompt.strip() and not source_ids:
        raise AppError("bad_request", "Describe what to cover or add at least one file or link.")
    set_id = db.new_id()
    now = db.now()
    db.insert("study_sets", {"id": set_id, "title": title.strip()[:120], "subject": subject.strip()[:80], "created_at": now,
                             "updated_at": now, "breakdown_status": "none", "breakdown_version": 0})
    if prompt.strip():
        db.insert("set_prompts", {"id": db.new_id(), "set_id": set_id, "text": prompt.strip(), "version": 1, "created_at": now})
    Src.attach(set_id, source_ids)
    breakdown.start(set_id)
    return set_id


def adopt_session(session_id: str) -> str:
    """Put a session created outside a set (the older /api/sessions endpoint) into its own set."""
    with db.connect() as conn:
        return migrations.adopt_session(conn, session_id)


def _require_breakdown(st: dict[str, Any]) -> None:
    if not C.subtopics(st["id"]):
        if st["breakdown_status"] == "generating":
            raise AppError("conflict", "The breakdown is still being built. Try again in a moment.")
        raise AppError("conflict", "This study set has no subtopics yet. Build the breakdown first.")


def _chosen(set_id: str, subtopic_ids: list[str]) -> list[dict[str, Any]]:
    wanted = set(subtopic_ids)
    chosen = [s for s in C.subtopics(set_id) if s["id"] in wanted]
    if not chosen:
        raise AppError("bad_request", "Pick at least one subtopic.")
    return chosen


# --- Views -----------------------------------------------------------------------------------------

def _quizzes(set_id: str) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT s.id, s.title, s.status, s.score, s.created_at, s.completed_at, s.parent_session_id, s.config_json, "
        "(SELECT COUNT(*) FROM answers a WHERE a.session_id = s.id) AS answered "
        "FROM sessions s WHERE s.study_set_id = ? ORDER BY s.created_at DESC", (set_id,))
    out = []
    for r in rows:
        cfg = db.loads(r.pop("config_json"), {}) or {}
        subs = db.query("SELECT name FROM subtopics WHERE session_id = ? ORDER BY position", (r["id"],))
        out.append({**r, "count": cfg.get("count"), "adaptive": cfg.get("adaptive"), "subtopics": [s["name"] for s in subs]})
    return out


def view(set_id: str) -> dict[str, Any]:
    from . import youtube

    st = breakdown.check_interrupted(C.get_set(set_id))
    Src.resume_processing(Src.set_sources(set_id))
    version = st["breakdown_version"]
    bd = st["breakdown"] or {}
    marks = bool(bd.get("marks_changes"))
    mastery = set_mastery(set_id)
    subtopics = []
    for s in C.subtopics(set_id):
        m = mastery.get(s["id"])
        subtopics.append({
            **s,
            "mastery": {k: m[k] for k in ("score", "n", "correct", "partial", "incorrect", "weak")} if m else None,
            "is_new": marks and s["created_version"] == version,
            "is_updated": marks and s["updated_version"] == version and s["created_version"] != version,
        })
    sources = Src.set_views(set_id)
    key = C.sources_key(set_id)
    in_breakdown = set((st["breakdown_sources_key"] or "").split(",")) - {""}
    for src in sources:
        src["in_breakdown"] = src["id"] in in_breakdown
    built = st["breakdown_status"] == "ready" or (st["breakdown_status"] == "failed" and st["breakdown"])
    return {
        "id": st["id"], "title": st["title"], "subject": st["subject"], "created_at": st["created_at"],
        "updated_at": st["updated_at"],
        "breakdown": {
            "status": st["breakdown_status"], "error": st["breakdown_error"], "version": version,
            "overview": bd.get("overview"), "map_mermaid": bd.get("map_mermaid"), "map_repaired": bd.get("map_repaired", False),
            "coverage_notes": bd.get("coverage_notes", []), "generated_at": bd.get("generated_at"),
            "unreadable_sources": bd.get("unreadable_sources", []), "removed": bd.get("removed", []),
            "running": breakdown.running(set_id),
        },
        # Sources added, removed, or read since the breakdown was built.
        "sources_changed": bool(built and key != (st["breakdown_sources_key"] or "")),
        "subtopics": subtopics,
        "sources": sources,
        "prompts": C.prompts(set_id),
        "quizzes": _quizzes(set_id),
        "guides": study_guide.set_guides(set_id),
        "playlists": youtube.set_playlists(set_id),
    }


def list_sets() -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT t.id, t.title, t.subject, t.created_at, t.updated_at, t.breakdown_status, "
        "(SELECT COUNT(*) FROM sources s WHERE s.set_id = t.id) AS sources, "
        "(SELECT COUNT(*) FROM set_subtopics st WHERE st.set_id = t.id AND st.status = 'active') AS subtopics, "
        "(SELECT COUNT(*) FROM sessions q WHERE q.study_set_id = t.id) AS quizzes, "
        "(SELECT COUNT(*) FROM sessions q WHERE q.study_set_id = t.id AND q.status = 'completed') AS completed, "
        "(SELECT COUNT(*) FROM sessions q WHERE q.study_set_id = t.id AND q.status != 'completed') AS in_progress, "
        "(SELECT q.score FROM sessions q WHERE q.study_set_id = t.id AND q.status = 'completed' "
        "  ORDER BY q.completed_at DESC LIMIT 1) AS last_score, "
        "(SELECT COUNT(*) FROM guides g WHERE g.set_id = t.id) AS guides, "
        "(SELECT COUNT(*) FROM playlists p WHERE p.set_id = t.id) AS playlists, "
        "MAX(t.updated_at, COALESCE((SELECT MAX(COALESCE(q.completed_at, q.created_at)) FROM sessions q "
        "  WHERE q.study_set_id = t.id), '')) AS last_activity "
        "FROM study_sets t ORDER BY last_activity DESC")
    return rows


# --- Changes -----------------------------------------------------------------------------------------

def rebuild(set_id: str) -> dict[str, Any]:
    st = C.get_set(set_id)
    if breakdown.running(set_id):
        raise AppError("conflict", "The breakdown is already being built.")
    if not C.prompts(set_id) and not any(s["status"] != "failed" for s in Src.set_sources(set_id)):
        raise AppError("bad_request", "Add a prompt or at least one readable source first.")
    previous = set((st["breakdown_sources_key"] or "").split(",")) - {""}
    breakdown.start(set_id, [s["id"] for s in Src.set_sources(set_id) if s["id"] not in previous] if previous else [])
    return view(set_id)


def append(set_id: str, prompt: str) -> dict[str, Any]:
    """Add a prompt (optional) and regenerate the breakdown, merging in sources added since the last one."""
    st = C.get_set(set_id)
    if breakdown.running(set_id):
        raise AppError("conflict", "The breakdown is already being updated.")
    changed = C.sources_key(set_id) != (st["breakdown_sources_key"] or "") or any(
        s["status"] == "processing" for s in Src.set_sources(set_id))
    if not prompt.strip() and not changed:
        raise AppError("bad_request", "Add a prompt or a new file or link to update the breakdown.")
    if prompt.strip():
        db.insert("set_prompts", {"id": db.new_id(), "set_id": set_id, "text": prompt.strip()[:4000],
                                  "version": st["breakdown_version"] + 1, "created_at": db.now()})
    return rebuild(set_id)


def rename(set_id: str, title: str | None, subject: str | None) -> dict[str, Any]:
    C.get_set(set_id)
    fields: dict[str, Any] = {}
    if title is not None:
        if not title.strip():
            raise AppError("bad_request", "The title can't be empty.")
        fields["title"] = title.strip()[:120]
    if subject is not None:
        fields["subject"] = subject.strip()[:80]
    if fields:
        C.update_set(set_id, **fields)
        if "subject" in fields:  # trends are grouped by subject
            db.execute("UPDATE sessions SET subject = ? WHERE study_set_id = ?", (fields["subject"], set_id))
    return view(set_id)


def delete(set_id: str) -> None:
    C.get_set(set_id)
    for s in db.query("SELECT id FROM sessions WHERE study_set_id = ?", (set_id,)):
        S.delete_session(s["id"])
    for p in db.query("SELECT id FROM playlists WHERE set_id = ?", (set_id,)):
        db.execute("DELETE FROM playlist_items WHERE playlist_id = ?", (p["id"],))
    with db.connect() as conn:
        conn.execute("DELETE FROM playlists WHERE set_id = ?", (set_id,))
        conn.execute("DELETE FROM guides WHERE set_id = ?", (set_id,))
        conn.execute("DELETE FROM set_prompts WHERE set_id = ?", (set_id,))
        conn.execute("DELETE FROM set_subtopics WHERE set_id = ?", (set_id,))
    for src in Src.set_sources(set_id):
        Src.remove(src["id"])
    db.execute("DELETE FROM study_sets WHERE id = ?", (set_id,))


# --- Actions ------------------------------------------------------------------------------------------

def start_quiz(set_id: str, *, subtopic_ids: list[str], types: list[str], difficulty: int, adaptive: bool, count: int,
               languages: list[str], settings: dict[str, Any]) -> str:
    st = C.get_set(set_id)
    _require_breakdown(st)
    chosen = _chosen(set_id, subtopic_ids)
    upload_ids = [u["id"] for _, u in C.ready_uploads(set_id)]
    subtopics = []
    for s in chosen:
        concepts = ", ".join(s["key_concepts"])
        subtopics.append({"name": s["name"], "set_subtopic_id": s["id"],
                          "description": s["summary"] + (f" Key concepts: {concepts}." if concepts else "")})
    session_id = generation.create_session(
        material=C.coverage_text(set_id) or f"Cover: {', '.join(s['name'] for s in chosen)}.",
        subject=st["subject"], upload_ids=upload_ids, types=types, difficulty=difficulty, adaptive=adaptive,
        count=count, languages=languages, settings=settings, subtopics=subtopics, study_set_id=set_id,
    )
    S.update_session(session_id, title=(st["title"] or "Study set")[:120])
    C.update_set(set_id)
    generation.ensure_worker(session_id)
    return session_id


def start_guide(set_id: str, subtopic_ids: list[str]) -> dict[str, Any]:
    st = C.get_set(set_id)
    _require_breakdown(st)
    return study_guide.guide_view(study_guide.start_for_subtopics(set_id, [s["id"] for s in _chosen(set_id, subtopic_ids)]))
