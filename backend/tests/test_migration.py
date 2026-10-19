"""The v1 migration: quiz sessions from before Study Sets get sets, nothing is lost, and it runs once."""
from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from sage import config, db

OLD_SCHEMA = """
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE uploads (id TEXT PRIMARY KEY, filename TEXT NOT NULL, kind TEXT NOT NULL, source_type TEXT NOT NULL,
    media_type TEXT NOT NULL, size INTEGER NOT NULL, path TEXT NOT NULL, char_count INTEGER, created_at TEXT NOT NULL);
CREATE TABLE sessions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, completed_at TEXT, subject TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '', material TEXT NOT NULL DEFAULT '', config_json TEXT NOT NULL, status TEXT NOT NULL,
    error_json TEXT, parent_session_id TEXT, current_difficulty INTEGER NOT NULL, score REAL);
CREATE TABLE session_documents (session_id TEXT NOT NULL, upload_id TEXT NOT NULL, position INTEGER NOT NULL,
    PRIMARY KEY (session_id, upload_id));
CREATE TABLE subtopics (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL,
    position INTEGER NOT NULL);
CREATE TABLE questions (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, position INTEGER, slot INTEGER NOT NULL,
    subtopic_id TEXT NOT NULL, type TEXT NOT NULL, difficulty INTEGER NOT NULL, payload_json TEXT NOT NULL,
    display_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE study_guides (session_id TEXT PRIMARY KEY, status TEXT NOT NULL, content_json TEXT, error_json TEXT,
    created_at TEXT NOT NULL);
"""


@pytest.fixture
def old_db(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(db, "_initialized_path", None)
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    folder = tmp_path / "uploads" / "u1"
    folder.mkdir(parents=True)
    pdf = b"%PDF-1.4 fake original bytes"
    (folder / "document.pdf").write_bytes(pdf)
    (folder / "extracted.txt").write_text("[Page 1]\nCarnot cycle", encoding="utf-8")
    cfg = json.dumps({"types": ["multiple_choice"], "difficulty": 3, "adaptive": False, "count": 5, "language": "Python",
                      "feedback_mode": "immediate", "slots": []})
    rows = [
        ("u1", "lecture.pdf", "text", "pdf", "text/plain", len(pdf), str(folder / "extracted.txt"), 20, "2026-01-01T00:00:00+00:00"),
    ]
    conn.executemany("INSERT INTO uploads VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.executemany("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("A", "2026-01-01T10:00:00+00:00", "2026-01-01T11:00:00+00:00", "Thermo", "Heat Engines", "Chapter 4", cfg,
         "completed", None, None, 3, 62.0),
        ("B", "2026-01-02T10:00:00+00:00", None, "Thermo", "Retest: Heat Engines", "Chapter 4", cfg, "ready", None, "A", 3, None),
        ("C", "2026-01-03T10:00:00+00:00", None, "", "Prompt only", "", cfg, "ready", None, None, 3, None),
    ])
    conn.executemany("INSERT INTO session_documents VALUES (?,?,?)", [("A", "u1", 0), ("B", "u1", 0)])
    conn.executemany("INSERT INTO subtopics VALUES (?,?,?,?,?)", [
        ("a1", "A", "Carnot cycle", "Ideal engine", 0), ("a2", "A", "Entropy", "S", 1),
        ("b1", "B", "carnot  cycle", "Ideal engine", 0), ("b2", "B", "Otto cycle", "Engines", 1),
        ("c1", "C", "Kinematics", "Motion", 0),
    ])
    conn.execute("INSERT INTO questions VALUES ('q1','A',1,0,'a1','multiple_choice',3,'{}','{}','served','2026-01-01')")
    content = {"generated_at": "x", "overall_score": 62, "sections": [{"subtopic_id": "a2", "name": "Entropy", "status": "ready"}]}
    conn.execute("INSERT INTO study_guides VALUES ('A','ready',?,NULL,'2026-01-01T12:00:00+00:00')", (json.dumps(content),))
    conn.commit()
    conn.close()
    return path, hashlib.sha256(pdf).hexdigest()


def test_sessions_get_study_sets(old_db):
    path, sha = old_db
    db.init_db()
    sets = db.query("SELECT * FROM study_sets ORDER BY created_at")
    assert [s["title"] for s in sets] == ["Heat Engines", "Prompt only"]  # the retest joined its parent's set
    assert all(s["breakdown_status"] == "legacy" for s in sets)
    a_set, c_set = sets[0]["id"], sets[1]["id"]
    assert {r["id"]: r["study_set_id"] for r in db.query("SELECT id, study_set_id FROM sessions")} == {"A": a_set, "B": a_set, "C": c_set}

    # Prompts and sources
    assert [p["text"] for p in db.query("SELECT text FROM set_prompts WHERE set_id = ?", (a_set,))] == ["Chapter 4"]
    assert db.query("SELECT * FROM set_prompts WHERE set_id = ?", (c_set,)) == []
    srcs = db.query("SELECT * FROM sources WHERE set_id = ?", (a_set,))
    assert len(srcs) == 1 and srcs[0]["upload_id"] == "u1" and srcs[0]["kind"] == "file" and srcs[0]["status"] == "ready"
    assert srcs[0]["dedupe_key"] == f"sha256:{sha}"  # hashed from the stored original PDF
    assert db.query_one("SELECT sha256 FROM uploads WHERE id = 'u1'")["sha256"] == sha

    # Subtopics: the retest's "carnot  cycle" matches the parent's; "Otto cycle" is added to the set.
    names = [s["name"] for s in db.query("SELECT name FROM set_subtopics WHERE set_id = ? ORDER BY position", (a_set,))]
    assert names == ["Carnot cycle", "Entropy", "Otto cycle"]
    links = {r["id"]: r["set_subtopic_id"] for r in db.query("SELECT id, set_subtopic_id FROM subtopics")}
    assert all(links.values())
    assert links["a1"] == links["b1"] != links["a2"]

    # Guides moved, old columns added, questions untouched.
    g = db.query("SELECT * FROM guides")
    assert len(g) == 1 and g[0]["session_id"] == "A" and g[0]["set_id"] == a_set and g[0]["kind"] == "weak_areas"
    assert json.loads(g[0]["subtopic_ids_json"]) == ["a2"]
    assert db.query_one("SELECT deferred_count FROM questions WHERE id = 'q1'")["deferred_count"] == 0
    assert db.query_one("PRAGMA user_version")["user_version"] == 1

    # A backup was made before migrating.
    backup = path.with_name(path.name + ".bak-v1")
    assert backup.exists()
    b = sqlite3.connect(backup)
    assert b.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 3
    assert "study_set_id" not in {r[1] for r in b.execute("PRAGMA table_info(sessions)")}
    b.close()


def test_migration_runs_once(old_db, monkeypatch):
    db.init_db()
    before = db.query("SELECT id FROM study_sets ORDER BY id")
    monkeypatch.setattr(db, "_initialized_path", None)
    db.init_db()
    assert db.query("SELECT id FROM study_sets ORDER BY id") == before
    assert db.query_one("SELECT COUNT(*) AS n FROM sources")["n"] == 1
    assert db.query_one("SELECT COUNT(*) AS n FROM guides")["n"] == 1


def test_migrated_sessions_still_open(old_db, client):
    r = client.get("/api/sessions/A/results")
    assert r.status_code == 200, r.text
    assert r.json()["session"]["study_set_id"]
    assert client.get("/api/sessions/A/study-guide").json()["status"] == "ready"
    sets = client.get("/api/sets").json()
    assert {s["title"]: s["quizzes"] for s in sets} == {"Heat Engines": 2, "Prompt only": 1}
    view = client.get(f"/api/sets/{sets[0]['id'] if sets[0]['title'] == 'Heat Engines' else sets[1]['id']}").json()
    assert view["breakdown"]["status"] == "legacy" and [s["name"] for s in view["subtopics"]] == ["Carnot cycle", "Entropy", "Otto cycle"]
    assert len(view["quizzes"]) == 2 and len(view["guides"]) == 1
