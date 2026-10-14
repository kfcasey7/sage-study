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
DROP TABLE IF EXISTS api_calls;          -- token/cost tracking from the API-key era
CREATE INDEX IF NOT EXISTS idx_questions_session ON questions(session_id, status);
CREATE INDEX IF NOT EXISTS idx_answers_session ON answers(session_id);
CREATE INDEX IF NOT EXISTS idx_ai_calls_session ON ai_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_question_chats_question ON question_chats(question_id, id);
"""

_init_lock = threading.Lock()
_initialized_path: str | None = None


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a database was first created."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(questions)")}
    if "deferred_count" not in cols:
        conn.execute("ALTER TABLE questions ADD COLUMN deferred_count INTEGER NOT NULL DEFAULT 0")


def init_db() -> None:
    global _initialized_path
    with _init_lock:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(config.DB_PATH)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            _migrate(conn)
            conn.commit()
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
