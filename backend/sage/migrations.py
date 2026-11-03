"""Versioned data migrations (PRAGMA user_version), plus the helpers that attach quiz sessions to
Study Sets. The helpers take an open connection so the migration runs in one transaction; the app uses
the same functions for sessions created through the older /api/sessions endpoint.

v1: Study Sets. Every session without a set gets one (a retest joins its parent's set), with the
session's documents as file sources, its prompt as the first prompt, and its subtopics as the set's
subtopics. Weak-areas study guides move from `study_guides` to `guides`.

v2: upload paths become relative to the data folder, so the folder can be moved or renamed."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LATEST = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id() -> str:
    return uuid.uuid4().hex[:16]


def file_sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return None


def upload_dedupe_key(upload: dict[str, Any] | sqlite3.Row) -> str:
    sha = upload["sha256"]
    return f"sha256:{sha}" if sha else f"upload:{upload['id']}"


def _norm(name: str) -> str:
    return " ".join(name.lower().split())


def link_subtopics(conn: sqlite3.Connection, session_id: str, set_id: str, version: int | None = None) -> None:
    """Point each of the session's subtopics without a link at the set subtopic with the same name,
    adding set subtopics for names the set doesn't have yet."""
    if version is None:
        version = conn.execute("SELECT breakdown_version FROM study_sets WHERE id = ?", (set_id,)).fetchone()[0]
    existing: dict[str, str] = {}
    for r in conn.execute("SELECT id, name FROM set_subtopics WHERE set_id = ? ORDER BY status = 'active' DESC, position",
                          (set_id,)):
        existing.setdefault(_norm(r["name"]), r["id"])  # prefer an active subtopic over a removed one
    pos = conn.execute("SELECT COALESCE(MAX(position), -1) FROM set_subtopics WHERE set_id = ?", (set_id,)).fetchone()[0]
    for sub in conn.execute(
            "SELECT id, name, description FROM subtopics WHERE session_id = ? AND set_subtopic_id IS NULL ORDER BY position",
            (session_id,)).fetchall():
        key = _norm(sub["name"])
        target = existing.get(key)
        if target is None:
            pos += 1
            target = _id()
            conn.execute(
                "INSERT INTO set_subtopics (id, set_id, name, summary, position, status, created_version, updated_version) "
                "VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
                (target, set_id, sub["name"], sub["description"] or "", pos, version, version))
            existing[key] = target
        conn.execute("UPDATE subtopics SET set_subtopic_id = ? WHERE id = ?", (target, sub["id"]))


def add_file_sources(conn: sqlite3.Connection, set_id: str, upload_ids: list[str]) -> None:
    """Attach already-processed uploads to a set as file sources, skipping duplicates."""
    keys = {r[0] for r in conn.execute("SELECT dedupe_key FROM sources WHERE set_id = ?", (set_id,))}
    pos = conn.execute("SELECT COALESCE(MAX(position), -1) FROM sources WHERE set_id = ?", (set_id,)).fetchone()[0]
    for uid in upload_ids:
        u = conn.execute("SELECT * FROM uploads WHERE id = ?", (uid,)).fetchone()
        if u is None:
            continue
        key = upload_dedupe_key(u)
        if key in keys or conn.execute(
                "SELECT 1 FROM sources WHERE set_id = ? AND upload_id = ?", (set_id, uid)).fetchone():
            continue
        pos += 1
        keys.add(key)
        conn.execute(
            "INSERT INTO sources (id, set_id, kind, source_type, title, upload_id, dedupe_key, status, position, created_at) "
            "VALUES (?, ?, 'file', ?, ?, ?, ?, 'ready', ?, ?)",
            (_id(), set_id, u["source_type"], u["filename"], uid, key, pos, u["created_at"]))


def adopt_session(conn: sqlite3.Connection, session_id: str) -> str:
    """Attach a session that has no Study Set: a retest joins its parent's set, anything else gets a
    new set built from the session. Returns the set id."""
    s = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if s["study_set_id"]:
        return s["study_set_id"]
    set_id = None
    if s["parent_session_id"]:
        parent = conn.execute("SELECT study_set_id FROM sessions WHERE id = ?", (s["parent_session_id"],)).fetchone()
        set_id = parent["study_set_id"] if parent else None
    if set_id is None:
        set_id = _id()
        conn.execute(
            "INSERT INTO study_sets (id, title, subject, created_at, updated_at, breakdown_status, breakdown_version) "
            "VALUES (?, ?, ?, ?, ?, 'legacy', 0)",
            (set_id, s["title"] or s["subject"] or "Study set", s["subject"] or "", s["created_at"],
             s["completed_at"] or s["created_at"]))
        if (s["material"] or "").strip():
            conn.execute("INSERT INTO set_prompts (id, set_id, text, version, created_at) VALUES (?, ?, ?, 0, ?)",
                         (_id(), set_id, s["material"].strip(), s["created_at"]))
    uploads = [r[0] for r in conn.execute(
        "SELECT upload_id FROM session_documents WHERE session_id = ? ORDER BY position", (session_id,))]
    add_file_sources(conn, set_id, uploads)
    conn.execute("UPDATE sessions SET study_set_id = ? WHERE id = ?", (set_id, session_id))
    link_subtopics(conn, session_id, set_id)
    conn.execute("UPDATE study_sets SET updated_at = MAX(updated_at, ?) WHERE id = ?",
                 (s["completed_at"] or s["created_at"], set_id))
    return set_id


def _backfill_sha256(conn: sqlite3.Connection) -> None:
    for u in conn.execute("SELECT id, path, source_type FROM uploads WHERE sha256 IS NULL").fetchall():
        stored = Path(u["path"])
        original = stored.parent / "document.pdf"
        # Only PDFs keep the original bytes; other types keep extracted text, which can't match a new upload.
        if u["source_type"] == "pdf" and original.exists():
            sha = file_sha256(original)
            if sha:
                conn.execute("UPDATE uploads SET sha256 = ? WHERE id = ?", (sha, u["id"]))


def _move_study_guides(conn: sqlite3.Connection) -> None:
    for g in conn.execute("SELECT * FROM study_guides").fetchall():
        if conn.execute("SELECT 1 FROM guides WHERE session_id = ? AND kind = 'weak_areas'", (g["session_id"],)).fetchone():
            continue
        s = conn.execute("SELECT study_set_id FROM sessions WHERE id = ?", (g["session_id"],)).fetchone()
        content = json.loads(g["content_json"]) if g["content_json"] else {"sections": []}
        ids = [sec["subtopic_id"] for sec in content.get("sections", [])]
        conn.execute(
            "INSERT INTO guides (id, set_id, session_id, kind, subtopic_ids_json, status, content_json, error_json, created_at) "
            "VALUES (?, ?, ?, 'weak_areas', ?, ?, ?, ?, ?)",
            (_id(), s["study_set_id"] if s else None, g["session_id"], json.dumps(ids), g["status"], g["content_json"],
             g["error_json"], g["created_at"]))


def _v1(conn: sqlite3.Connection) -> None:
    _backfill_sha256(conn)
    for s in conn.execute("SELECT id FROM sessions WHERE study_set_id IS NULL ORDER BY created_at, id").fetchall():
        adopt_session(conn, s["id"])
    _move_study_guides(conn)


_UPLOAD_TAIL = re.compile(r"(?:^|[\\/])(uploads[\\/][^\\/]+[\\/][^\\/]+)$")


def _v2(conn: sqlite3.Connection) -> None:
    for u in conn.execute("SELECT id, path FROM uploads").fetchall():
        m = _UPLOAD_TAIL.search(u["path"])
        if m:  # anything else stays as it was: it still resolves, and nothing is ever discarded
            conn.execute("UPDATE uploads SET path = ? WHERE id = ?", (m.group(1).replace("\\", "/"), u["id"]))


def run(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= LATEST:
        return
    if not conn.in_transaction:
        conn.execute("BEGIN")
    if version < 1:
        _v1(conn)
    if version < 2:
        _v2(conn)
    conn.execute(f"PRAGMA user_version = {LATEST}")
