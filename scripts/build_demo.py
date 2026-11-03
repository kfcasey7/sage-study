"""Generate the bundled demo Study Set (backend/sage/demo) from samples/thermo-first-law.pdf, using the real
Claude Code CLI on your own plan. Only needed when the demo's content should change.

    python scripts/build_demo.py

Runs a private copy of the backend on a temporary data folder, so your own study data isn't involved.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "sage" / "demo"
SAMPLE = ROOT / "samples" / "thermo-first-law.pdf"
H = {"x-sage-client": "1"}
OBJECTIVE = ["multiple_choice", "select_all", "true_false", "matching", "ordering"]
TITLE = "Sample: The First Law of Thermodynamics"
TABLES = {  # table: column naming the row's owner
    "study_sets": "id", "set_prompts": "set_id", "sources": "set_id", "set_subtopics": "set_id", "guides": "set_id",
    "playlists": "set_id", "sessions": "study_set_id",
}


class Api:
    def __init__(self, base: str):
        self.base = base

    def call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else (b"" if method != "GET" else None)
        headers = {**H, "content-type": "application/json"} if body is not None else H
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path} -> {e.code}: {e.read().decode()[:600]}") from None

    def upload(self, path: Path, draft: str):
        boundary = uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="draft_id"\r\n\r\n{draft}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                "Content-Type: application/pdf\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(self.base + "/api/sources/files", data=body, method="POST",
                                     headers={**H, "content-type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())


def wait(label: str, fn, timeout: float = 900, every: float = 3):
    t0 = time.time()
    while time.time() - t0 < timeout:
        out = fn()
        if out:
            print(f"  {label}: done in {time.time() - t0:.0f}s", flush=True)
            return out
        time.sleep(every)
    raise SystemExit(f"timed out waiting for {label}")


def answer_for(db_path: Path, qid: str, right: bool) -> dict:
    conn = sqlite3.connect(db_path)
    payload, display = conn.execute("SELECT payload_json, display_json FROM questions WHERE id = ?", (qid,)).fetchone()
    conn.close()
    p, d = json.loads(payload), json.loads(display)
    t = p["type"]
    if t == "multiple_choice":
        return {"choice": p["correct_index"] if right else (p["correct_index"] + 1) % len(p["options"])}
    if t == "select_all":
        return {"choices": p["correct_indices"] if right else [i for i in range(len(p["options"])) if i not in p["correct_indices"]][:1]}
    if t == "true_false":
        return {"value": p["correct"] if right else not p["correct"]}
    if t == "matching":
        order = [d["right"].index(pair["right"]) for pair in p["pairs"]]
        return {"matches": order if right else order[1:] + order[:1]}
    order = list(range(len(p["items"])))
    return {"order": order if right else list(reversed(order))}


def take_quiz(api: Api, db_path: Path, set_id: str, subtopic_ids: list[str], count: int, wrong_on: set[int]) -> str:
    q = api.call("POST", f"/api/sets/{set_id}/quiz", {"subtopic_ids": subtopic_ids, "types": OBJECTIVE, "difficulty": 3, "adaptive": False,
                                                      "count": count, "languages": ["Python"]})
    sid = q["id"]
    for i in range(count):
        n = wait(f"question {i + 1}", lambda: (lambda r: r if r["state"] != "pending" else None)(api.call("GET", f"/api/sessions/{sid}/next")), every=2)
        assert n["state"] == "question", n
        qid = n["question"]["id"]
        api.call("POST", f"/api/questions/{qid}/answer",
                 {"response": answer_for(db_path, qid, i not in wrong_on), "confidence": "medium", "skipped": False})
    return sid


def rows(conn: sqlite3.Connection, sql: str, params: tuple | list = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params)]


def export(db_path: Path, data_dir: Path, set_id: str, ready_session: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    tables: dict[str, list[dict]] = {t: rows(conn, f"SELECT * FROM {t} WHERE {col} = ?", (set_id,)) for t, col in TABLES.items()}
    sessions = [s["id"] for s in tables["sessions"]]
    marks = ",".join("?" * len(sessions))
    tables["session_documents"] = rows(conn, f"SELECT * FROM session_documents WHERE session_id IN ({marks})", sessions)
    tables["subtopics"] = rows(conn, f"SELECT * FROM subtopics WHERE session_id IN ({marks})", sessions)
    tables["questions"] = rows(conn, f"SELECT * FROM questions WHERE session_id IN ({marks}) AND status != 'discarded'", sessions)
    tables["answers"] = rows(conn, f"SELECT * FROM answers WHERE session_id IN ({marks}) AND session_id != ?", [*sessions, ready_session])
    playlists = [p["id"] for p in tables["playlists"]]
    tables["playlist_items"] = rows(conn, f"SELECT * FROM playlist_items WHERE playlist_id IN ({','.join('?' * len(playlists))})", playlists)
    upload_ids = [s["upload_id"] for s in tables["sources"]]
    tables["uploads"] = rows(conn, f"SELECT * FROM uploads WHERE id IN ({','.join('?' * len(upload_ids))})", upload_ids)
    conn.close()

    # The second quiz goes back to untaken: its questions wait in the pool and it starts at question one.
    for s in tables["sessions"]:
        if s["id"] == ready_session:
            s.update(status="ready", completed_at=None, score=None)
    for q in tables["questions"]:
        if q["session_id"] == ready_session:
            q.update(status="pool", position=None)

    OUT.mkdir(parents=True, exist_ok=True)
    files = {}
    for u in tables["uploads"]:
        assert u["kind"] == "text", "the demo's source must have extractable text"
        name = f"source-{u['id']}.txt"
        shutil.copyfile(data_dir / u["path"], OUT / name)
        files[u["id"]] = name
    (OUT / "demo_set.json").write_text(json.dumps({"set_id": set_id, "files": files, "tables": tables}, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    data_dir = Path(tempfile.mkdtemp(prefix="sage-demo-"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "SAGE_DATA_DIR": str(data_dir), "SAGE_PORT": str(port), "PYTHONPATH": str(ROOT / "backend")}
    server = subprocess.Popen([sys.executable, "-m", "sage.dev"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    api = Api(f"http://127.0.0.1:{port}")
    db_path = data_dir / "sage.db"
    try:
        def up():
            try:
                return api.call("GET", "/api/_ping")
            except OSError:
                return None
        wait("server", up, timeout=30, every=0.5)

        draft = uuid.uuid4().hex
        pdf = api.upload(SAMPLE, draft)
        s = api.call("POST", "/api/sets", {"subject": "Thermodynamics", "title": TITLE,
                                           "prompt": "The first law of thermodynamics: internal energy, heat and work, and enthalpy.",
                                           "source_ids": [pdf["id"]]})
        set_id = s["id"]
        v = wait("breakdown", lambda: (lambda x: x if x["breakdown"]["status"] in ("ready", "failed") else None)(api.call("GET", f"/api/sets/{set_id}")))
        assert v["breakdown"]["status"] == "ready", v["breakdown"]["error"]
        api.call("PATCH", f"/api/sets/{set_id}", {"title": TITLE})
        ids = [x["id"] for x in v["subtopics"]]
        print(f"  {len(ids)} subtopics: {[x['name'] for x in v['subtopics']]}")

        g = api.call("POST", f"/api/sets/{set_id}/guides", {"subtopic_ids": ids[:2]})
        g = wait("study guide", lambda: (lambda x: x if x["status"] != "generating" else None)(api.call("GET", f"/api/guides/{g['id']}")))
        assert g["status"] == "ready", g

        p = api.call("POST", f"/api/sets/{set_id}/playlists", {"subtopic_ids": ids[:2]})
        p = wait("playlist", lambda: (lambda x: x if x["status"] != "generating" else None)(api.call("GET", f"/api/playlists/{p['id']}")))
        assert p["status"] == "ready", p

        finished = take_quiz(api, db_path, set_id, ids, 5, wrong_on={1, 3})
        wait("first quiz graded", lambda: api.call("POST", f"/api/sessions/{finished}/finish"))
        ready = take_quiz(api, db_path, set_id, ids, 5, wrong_on=set())
    finally:
        server.terminate()
        server.wait(timeout=20)
    export(db_path, data_dir, set_id, ready)
    shutil.rmtree(data_dir, ignore_errors=True)
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
