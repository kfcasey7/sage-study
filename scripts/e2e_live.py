"""Live end-to-end check against a running Sage Study backend, using the real Claude Code CLI on
your Claude subscription (no API key, no API billing; it does count toward your plan's usage limits).

    python scripts/e2e_live.py --url http://127.0.0.1:PORT

Uploads samples/thermo-first-law.pdf, runs a 3-question session (multiple choice, short response,
math), answers one correctly from the answer key, one with the rubric's model answer, and one badly,
then checks grading, finishes, generates the study guide, and exports it to Markdown.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from sage import config  # noqa: E402

H = {"x-sage-client": "1"}


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, body: dict | None = None, timeout: float = 600):
        data = json.dumps(body).encode() if body is not None else (b"" if method != "GET" else None)
        headers = {**H, "content-type": "application/json"} if body is not None else H
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path} -> {e.code}: {e.read().decode()[:500]}") from None

    def upload(self, path: Path) -> dict:
        boundary = "----sage-e2e"
        payload = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            "Content-Type: application/pdf\r\n\r\n"
        ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(self.base + "/api/uploads", data=payload, method="POST",
                                     headers={**H, "content-type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())


def stored(qid: str) -> dict:
    con = sqlite3.connect(config.DB_PATH)
    try:
        row = con.execute("SELECT payload_json, display_json FROM questions WHERE id = ?", (qid,)).fetchone()
        return {"payload": json.loads(row[0]), "display": json.loads(row[1])}
    finally:
        con.close()


def answer_for(q: dict) -> tuple[dict, str]:
    p = q["payload"]
    t = p["type"]
    if t == "multiple_choice":
        return {"choice": p["correct_index"]}, "good"
    if t == "short_response":
        return {"text": p["rubric"]["model_answer"]}, "good"
    if t == "math":
        return {"work": "W = P V", "final": "42"}, "bad"
    raise AssertionError(t)


def next_question(api: Api, sid: str, timeout: float = 600) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = api.call("GET", f"/api/sessions/{sid}/next")
        if r["state"] in ("question", "done"):
            return r
        if r["state"] == "error":
            raise RuntimeError(f"session error: {r['error']}")
        time.sleep(2)
    raise RuntimeError("timed out waiting for a question")


def check(cond: bool, msg: str, failures: list[str]) -> None:
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    args = ap.parse_args()
    api = Api(args.url)
    failures: list[str] = []
    t_start = time.time()

    st = api.call("GET", "/api/settings/cli-status?refresh=true")
    check(st["ready"], f"Claude Code ready ({st.get('version')}, {st.get('subscription')} plan via {st.get('auth_method')})", failures)
    if not st["ready"]:
        print("  ", st.get("message"))
        return 1
    settings = api.call("PUT", "/api/settings", {"feedback_mode": "immediate"})
    print(f"Models: questions={settings['settings']['model_fast']}, grading/guide={settings['settings']['model_smart']}")

    print("\n== Upload + 3-question session (multiple choice, short response, math)")
    up = api.upload(ROOT / "samples" / "thermo-first-law.pdf")
    check(up["kind"] == "text" and (up["char_count"] or 0) > 1000, f"PDF text extracted ({up['char_count']} chars)", failures)
    s = api.call("POST", "/api/sessions", {
        "material": "Chapter 2: the first law, work in ideal-gas processes, and heat engine efficiency.",
        "subject": "Thermodynamics (E2E)", "upload_ids": [up["id"]],
        "types": ["multiple_choice", "short_response", "math"], "difficulty": 3, "adaptive": False, "count": 3,
    })
    sid = s["id"]
    t0 = time.time()
    r = next_question(api, sid)
    print(f"  First question ready after {time.time() - t0:.0f}s")
    session = api.call("GET", f"/api/sessions/{sid}")
    print(f"  Topic map: '{session['title']}' -> {[x['name'] for x in session['subtopics']]}")
    check(len(session["subtopics"]) >= 2, "topic map produced subtopics", failures)

    graded: dict[str, dict] = {}
    while r["state"] == "question":
        q = r["question"]
        answer, kind = answer_for(stored(q["id"]))
        t0 = time.time()
        a = api.call("POST", f"/api/questions/{q['id']}/answer", {"response": answer, "confidence": "high", "skipped": False})
        graded[q["type"]] = {**a, "kind": kind}
        print(f"  Q{q['position'] + 1} {q['type']:<16} {kind} answer -> {a['grade_status']} {a.get('verdict')} {a.get('score')} "
              f"({time.time() - t0:.0f}s)")
        print(f"      prompt: {q['prompt'][:110].replace(chr(10), ' ')}")
        if a.get("feedback"):
            print(f"      feedback: {a['feedback'][:160].replace(chr(10), ' ')}")
        r = next_question(api, sid)

    check(set(graded) == {"multiple_choice", "short_response", "math"}, "served all three question types", failures)
    check(all(g["grade_status"] == "done" for g in graded.values()), "every answer graded", failures)
    if "short_response" in graded:
        check((graded["short_response"].get("score") or 0) >= 70, "model answer to the short response graded well (Claude)", failures)
    if "math" in graded:
        check((graded["math"].get("score") or 100) <= 50, "wrong math answer graded low (Claude)", failures)

    print("\n== Finish + results")
    res = api.call("POST", f"/api/sessions/{sid}/finish")
    m = res["mastery"]
    print(f"  Overall {m['overall']['score']}%, weak: {[x['name'] for x in m['subtopics'] if x['weak']]}")
    check(res["session"]["status"] == "completed" and res["ungraded"] == [], "session completed and fully graded", failures)
    ai = res["ai"]
    print(f"  AI calls: {ai['total']['calls']} ({ai['total']['failed']} retried/failed), AI time {ai['total']['seconds']}s, "
          f"session {res['session_seconds']:.0f}s")
    for p in ai["by_purpose"]:
        print(f"    {p['purpose']:<14} {p['calls']} call(s), {p['seconds']}s")
    con = sqlite3.connect(config.DB_PATH)
    models = dict(con.execute("SELECT purpose, GROUP_CONCAT(DISTINCT model) FROM ai_calls WHERE session_id = ? GROUP BY purpose", (sid,)).fetchall())
    con.close()
    print(f"  Models used: {models}")
    check(models.get("generate") == settings["settings"]["model_fast"], "questions written with the fast model", failures)
    check(models.get("grade") == settings["settings"]["model_smart"], "written/math answers graded with the smart model", failures)

    print("\n== Study guide")
    if not any(x["weak"] for x in m["subtopics"]):
        print("  (no weak areas; skipping)")
    else:
        t0 = time.time()
        g = api.call("POST", f"/api/sessions/{sid}/study-guide")
        while g["status"] == "generating" and time.time() - t0 < 900:
            time.sleep(4)
            g = api.call("GET", f"/api/sessions/{sid}/study-guide")
        print(f"  Status {g['status']} after {time.time() - t0:.0f}s")
        for sec in g["content"]["sections"]:
            body = sec["section"] or {}
            print(f"  - {sec['name']}: {sec['status']}; formulas={len(body.get('key_formulas', []))}, "
                  f"diagram={body.get('diagram', {}).get('include')}, chart={body.get('chart', {}).get('include')}, "
                  f"mistakes={len(body.get('common_mistakes', []))}, practice={len(body.get('practice_questions', []))}"
                  + (f", error={sec['error']['code']}: {sec['error']['message']}" if sec.get("error") else ""))
        check(g["status"] == "ready" and all(x["status"] == "ready" for x in g["content"]["sections"]), "study guide generated", failures)
        md = api.call("GET", f"/api/sessions/{sid}/study-guide/export/markdown")
        out = ROOT / "samples" / "e2e-study-guide.md"
        out.write_text(md["markdown"], encoding="utf-8")
        check("## " in md["markdown"], f"Markdown export ({len(md['markdown'])} chars) -> samples/{out.name}", failures)

    leftovers = list(config.LLM_TMP_DIR.glob("*")) if config.LLM_TMP_DIR.exists() else []
    check(not [p for p in leftovers if p.name != "status"], "no CLI work folders left behind", failures)

    print(f"\nDone in {time.time() - t_start:.0f}s. Session id: {sid}")
    print("FAILURES:\n- " + "\n- ".join(failures) if failures else "ALL CHECKS PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
