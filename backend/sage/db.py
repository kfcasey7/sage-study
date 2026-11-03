"""SQLite storage. One short-lived connection per operation keeps this safe across
uvicorn's event loop and the worker threads FastAPI uses for sync endpoints."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS uploads (
    id          TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    kind        TEXT NOT NULL,          -- pdf | image | text
    source_type TEXT NOT NULL,          -- original extension kind: pdf, docx, pptx, text, image
    media_type  TEXT NOT NULL,
    size        INTEGER NOT NULL,
    path        TEXT NOT NULL,          -- file sent to Claude (original, resized image, or extracted .txt)
    char_count  INTEGER,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id                 TEXT PRIMARY KEY,
    created_at         TEXT NOT NULL,
    completed_at       TEXT,
    subject            TEXT NOT NULL DEFAULT '',
    title              TEXT NOT NULL DEFAULT '',
    material           TEXT NOT NULL DEFAULT '',
    config_json        TEXT NOT NULL,
    status             TEXT NOT NULL,   -- analyzing | generating | ready | completed | failed
    error_json         TEXT,
    parent_session_id  TEXT,
    current_difficulty INTEGER NOT NULL,
    score              REAL
);
CREATE TABLE IF NOT EXISTS session_documents (
    session_id TEXT NOT NULL,
    upload_id  TEXT NOT NULL,
    position   INTEGER NOT NULL,
    PRIMARY KEY (session_id, upload_id)
);
CREATE TABLE IF NOT EXISTS subtopics (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT NOT NULL,
    position    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS questions (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    position     INTEGER,               -- set when served to the user
    slot         INTEGER NOT NULL,      -- planned slot index (adaptive candidates share a slot)
    subtopic_id  TEXT NOT NULL,
    type         TEXT NOT NULL,
    difficulty   INTEGER NOT NULL,
    payload_json TEXT NOT NULL,         -- full question incl. answer key (never sent to UI before answering)
    display_json TEXT NOT NULL,         -- public view (shuffled options etc.)
    status       TEXT NOT NULL,         -- pool | served | deferred (skipped, comes back at the end) | discarded
    deferred_count INTEGER NOT NULL DEFAULT 0,  -- times the student skipped it
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS answers (
    question_id   TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL,
    response_json TEXT NOT NULL,
    confidence    TEXT,                 -- low | medium | high | NULL
    skipped       INTEGER NOT NULL DEFAULT 0,
    answered_at   TEXT NOT NULL,
    grade_status  TEXT NOT NULL,        -- pending | done | error
    score         REAL,
    verdict       TEXT,                 -- correct | partial | incorrect
    feedback      TEXT,
    model_answer  TEXT,
    misconception TEXT,
    details_json  TEXT,
    graded_by     TEXT,                 -- local | claude
    grade_error   TEXT
);
CREATE TABLE IF NOT EXISTS study_guides (
    session_id   TEXT PRIMARY KEY,
    status       TEXT NOT NULL,         -- generating | ready | failed
    content_json TEXT,
    error_json   TEXT,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_calls (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT,
    purpose      TEXT NOT NULL,          -- topic_map | generate | grade | study_guide | diagram_repair | chat
    model        TEXT NOT NULL,          -- CLI alias (haiku, sonnet, opus)
    duration_ms  INTEGER NOT NULL,
    ok           INTEGER NOT NULL,       -- 1 = usable result, 0 = failed attempt
    error_code   TEXT,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS question_chats (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id  TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    role         TEXT NOT NULL,          -- user | assistant
    content      TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS question_reports (
    question_id  TEXT PRIMARY KEY,       -- one report per question (reporting again replaces it)
    session_id   TEXT NOT NULL,
    reason       TEXT NOT NULL,          -- see config.REPORT_REASONS
    note         TEXT NOT NULL DEFAULT '',
    answered     INTEGER NOT NULL,       -- 1 = reported after answering (kept, not scored); 0 = replaced
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS study_sets (
    id                    TEXT PRIMARY KEY,
    title                 TEXT NOT NULL DEFAULT '',
    subject               TEXT NOT NULL DEFAULT '',
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    breakdown_status      TEXT NOT NULL,      -- none | legacy (migrated, subtopics only) | generating | ready | failed
    breakdown_json        TEXT,               -- {overview, map_mermaid, map_repaired, coverage_notes, generated_at}
    breakdown_error_json  TEXT,
    breakdown_version     INTEGER NOT NULL DEFAULT 0,   -- bumped by every (re)generation
    breakdown_sources_key TEXT                -- ready source ids the breakdown was built from
);
CREATE TABLE IF NOT EXISTS set_prompts (
    id         TEXT PRIMARY KEY,
    set_id     TEXT NOT NULL,
    text       TEXT NOT NULL,
    version    INTEGER NOT NULL,              -- breakdown version it was added for
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    id          TEXT PRIMARY KEY,
    set_id      TEXT,                         -- NULL while still on the setup screen
    draft_id    TEXT,                         -- setup-screen group, for de-duplication before the set exists
    kind        TEXT NOT NULL,                -- file | link
    source_type TEXT NOT NULL,                -- pdf docx pptx text image | web web_pdf youtube gdoc gslides gsheet
    url         TEXT,
    title       TEXT NOT NULL DEFAULT '',
    upload_id   TEXT,                         -- processed content (uploads row)
    dedupe_key  TEXT NOT NULL,
    status      TEXT NOT NULL,                -- processing | ready | failed
    error_json  TEXT,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS set_subtopics (
    id                TEXT PRIMARY KEY,
    set_id            TEXT NOT NULL,
    name              TEXT NOT NULL,
    summary           TEXT NOT NULL DEFAULT '',
    key_concepts_json TEXT NOT NULL DEFAULT '[]',
    formulas_json     TEXT NOT NULL DEFAULT '[]',
    difficulty        INTEGER,
    source_ids_json   TEXT NOT NULL DEFAULT '[]',
    position          INTEGER NOT NULL,
    status            TEXT NOT NULL,          -- active | removed (kept so old quiz results keep their names)
    created_version   INTEGER NOT NULL,
    updated_version   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS guides (
    id                TEXT PRIMARY KEY,
    set_id            TEXT,
    session_id        TEXT,                   -- weak-areas guides belong to a finished quiz
    kind              TEXT NOT NULL,          -- weak_areas | subtopics
    subtopic_ids_json TEXT NOT NULL DEFAULT '[]',
    status            TEXT NOT NULL,          -- generating | ready | failed
    content_json      TEXT,
    error_json        TEXT,
    created_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS playlists (
    id                TEXT PRIMARY KEY,
    set_id            TEXT NOT NULL,
    subtopic_ids_json TEXT NOT NULL,
    status            TEXT NOT NULL,          -- generating | ready | failed
    error_json        TEXT,
    spares_json       TEXT NOT NULL DEFAULT '{}',  -- {set_subtopic_id: [ranked, verified-later candidates]}
    created_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS playlist_items (
    id              TEXT PRIMARY KEY,
    playlist_id     TEXT NOT NULL,
    set_subtopic_id TEXT NOT NULL,
    video_id        TEXT NOT NULL,
    title           TEXT NOT NULL,
    channel         TEXT NOT NULL DEFAULT '',
    duration_s      INTEGER,
    thumbnail       TEXT NOT NULL DEFAULT '',
    reason          TEXT NOT NULL DEFAULT '',
    watched         INTEGER NOT NULL DEFAULT 0,
    position        INTEGER NOT NULL,
    status          TEXT NOT NULL,            -- active | replaced
    created_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS question_videos (
    question_id   TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL,
    videos_json   TEXT NOT NULL,
    before_answer INTEGER NOT NULL,           -- 1 = looked up before answering ("used help")
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS yt_cache (
    key        TEXT PRIMARY KEY,              -- search:<query> | video:<id>
    json       TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oembed_cache (
    video_id   TEXT PRIMARY KEY,
    ok         INTEGER NOT NULL,
    json       TEXT,
    checked_at TEXT NOT NULL
);
DROP TABLE IF EXISTS api_calls;          -- token/cost tracking from the API-key era
CREATE INDEX IF NOT EXISTS idx_questions_session ON questions(session_id, status);
CREATE INDEX IF NOT EXISTS idx_answers_session ON answers(session_id);
CREATE INDEX IF NOT EXISTS idx_ai_calls_session ON ai_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_question_chats_question ON question_chats(question_id, id);
CREATE INDEX IF NOT EXISTS idx_sources_set ON sources(set_id, position);
CREATE INDEX IF NOT EXISTS idx_set_subtopics_set ON set_subtopics(set_id, position);
CREATE INDEX IF NOT EXISTS idx_guides_set ON guides(set_id);
CREATE INDEX IF NOT EXISTS idx_guides_session ON guides(session_id);
CREATE INDEX IF NOT EXISTS idx_playlist_items ON playlist_items(playlist_id, position);
"""

_init_lock = threading.Lock()
_initialized_path: str | None = None


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def _add_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    if column not in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a database was first created, then run versioned data migrations."""
    from . import migrations

    _add_column(conn, "questions", "deferred_count", "INTEGER NOT NULL DEFAULT 0")
    _add_column(conn, "sessions", "study_set_id", "TEXT")
    _add_column(conn, "subtopics", "set_subtopic_id", "TEXT")
    _add_column(conn, "uploads", "sha256", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_set ON sessions(study_set_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_subtopics_set ON subtopics(set_subtopic_id)")
    migrations.run(conn)


def _backup_before_migration() -> None:
    """Copy the database aside before a migration touches it (once per schema version), and refuse to open
    a database written by a newer version of the app rather than risk damaging it."""
    from . import migrations
    from .errors import AppError

    if not config.DB_PATH.exists():
        return
    conn = sqlite3.connect(config.DB_PATH)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > migrations.LATEST:
            raise AppError("server_error", f"Your study data was saved by a newer version of {config.APP_NAME}. "
                                           "Please update the app. Your data hasn't been changed.")
        has_sessions = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sessions'").fetchone() is not None
        if version >= migrations.LATEST or not has_sessions:
            return
        backup = config.DB_PATH.with_name(f"{config.DB_PATH.name}.bak-v{migrations.LATEST}")
        if backup.exists():
            return
        dst = sqlite3.connect(backup)
        try:
            conn.backup(dst)  # consistent copy, including pages still in the WAL file
            good = dst.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            dst.close()
        if not good:
            backup.unlink(missing_ok=True)
            raise AppError("server_error", "Couldn't make a safe backup of your study data, so the update wasn't applied.")
    finally:
        conn.close()


def init_db() -> None:
    global _initialized_path
    with _init_lock:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        _backup_before_migration()
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            _migrate(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        _initialized_path = str(config.DB_PATH)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    if _initialized_path != str(config.DB_PATH):
        init_db()
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def query_one(sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple | list = ()) -> int:
    with connect() as conn:
        cur = conn.execute(sql, params)
        return cur.rowcount


def insert(table: str, row: dict[str, Any]) -> None:
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(row.values()))


def update(table: str, key_col: str, key: Any, fields: dict[str, Any]) -> None:
    sets = ", ".join(f"{c} = ?" for c in fields)
    execute(f"UPDATE {table} SET {sets} WHERE {key_col} = ?", [*fields.values(), key])


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def loads(text: str | None, default: Any = None) -> Any:
    if text is None:
        return default
    return json.loads(text)


# --- Settings ----------------------------------------------------------------

def get_settings() -> dict[str, Any]:
    stored = {r["key"]: json.loads(r["value"]) for r in query("SELECT key, value FROM settings")}
    # Only known keys: older versions stored API-era settings (model IDs, effort, fallback).
    return {k: stored.get(k, default) for k, default in config.DEFAULT_SETTINGS.items()}


def set_settings(values: dict[str, Any]) -> dict[str, Any]:
    with connect() as conn:
        for k, v in values.items():
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (k, json.dumps(v)),
            )
    return get_settings()
