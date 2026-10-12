"""Live end-to-end check against a running Sage Study backend and the real Claude API.

    python scripts/e2e_live.py --url http://127.0.0.1:PORT [--quick]

It uploads samples/thermo-first-law.pdf, runs a session with every question type, answers some
correctly (using the stored answer key / rubric model answer) and some badly, finishes, generates the
study guide, and checks prompt caching, cost tracking, Markdown export, retest, and adaptive mode.
This spends real API credit (roughly $0.25-0.60 on Sonnet 5.5).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from sage import config  # noqa: E402

H = {"x-sage-client": "1"}
BAD_TEXT = "I am not sure. Maybe it has something to do with pressure?"


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, body: dict | None = None, timeout: float = 300):
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


def payload_of(qid: str) -> dict:
    con = sqlite3.connect(config.DB_PATH)
    try:
        row = con.execute("SELECT payload_json, display_json FROM questions WHERE id = ?", (qid,)).fetchone()
        return {"payload": json.loads(row[0]), "display": json.loads(row[1])}
    finally:
        con.close()


def good_answer(q: dict) -> dict:
    p, d = q["payload"], q["display"]
    t = p["type"]
    if t == "multiple_choice":
        return {"choice": p["correct_index"]}
    if t == "select_all":
        return {"choices": p["correct_indices"]}
    if t == "true_false":
        return {"value": p["correct"]}
    if t == "matching":
        return {"matches": [d["right"].index(x["right"]) for x in p["pairs"]]}
    if t == "ordering":
        return {"order": list(range(len(p["items"])))}
    if t == "fill_blank":
        return {"blanks": [b["accepted_answers"][0] for b in p["blanks"]]}
    model = p["rubric"]["model_answer"]
    if t == "math":
        return {"work": model, "final": p["final_answer"]}
    if t == "code":
        return {"code": model.replace("```python", "").replace("```", "").strip()}
    if t == "error_analysis":
        return {"text": model, "code": model}
    return {"text": model}


def bad_answer(q: dict) -> dict:
    p = q["payload"]
    t = p["type"]
    if t == "multiple_choice":
        return {"choice": (p["correct_index"] + 1) % len(p["options"])}
    if t == "true_false":
        return {"value": not p["correct"]}
    if t == "select_all":
        return {"choices": [i for i in range(len(p["options"])) if i not in p["correct_indices"]][:1]}
    if t == "ordering":
        return {"order": list(reversed(range(len(p["items"]))))}
    if t == "matching":
        return {"matches": [None] * len(p["pairs"])}
    if t == "fill_blank":
        return {"blanks": ["banana"] * len(p["blanks"])}
    if t == "math":
        return {"work": "W = P V", "final": "42"}
    if t == "code":
        return {"code": "def f(*args):\n    return None\n"}
    if t == "error_analysis":
        return {"text": "The code looks fine to me.", "code": p.get("flawed_work", "")}
    return {"text": BAD_TEXT}


def next_question(api: Api, sid: str, timeout: float = 240) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = api.call("GET", f"/api/sessions/{sid}/next")
        if r["state"] in ("question", "done"):
            return r
        if r["state"] == "error":
            raise RuntimeError(f"session error: {r['error']}")
        time.sleep(1.5)
    raise RuntimeError("timed out waiting for a question")


def check(cond: bool, msg: str, failures: list[str]) -> None:
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--quick", action="store_true", help="skip the adaptive mini-session")
    args = ap.parse_args()
    api = Api(args.url)
    failures: list[str] = []
    t_start = time.time()

    settings = api.call("GET", "/api/settings")
    check(settings["key"]["key_set"], f"API key configured (source: {settings['key']['source']})", failures)
    if not settings["key"]["key_set"]:
        return 1
    print(f"Model: {settings['settings']['model']}, effort: {settings['settings']['effort']}")
    api.call("PUT", "/api/settings", {"feedback_mode": "immediate"})

    print("\n== Upload + session with all 13 question types")
    up = api.upload(ROOT / "samples" / "thermo-first-law.pdf")
    check(up["kind"] == "pdf", "PDF uploaded as native document", failures)
    types = [t["id"] for t in settings["options"]["question_types"]]
    s = api.call("POST", "/api/sessions", {
        "material": "Chapter 2: the first law, work in ideal-gas processes, enthalpy, and heat engine efficiency.",
        "subject": "Thermodynamics (E2E)", "upload_ids": [up["id"]], "types": types, "difficulty": 3,
        "adaptive": False, "count": 13, "language": "Python",
    })
    sid = s["id"]
    first = next_question(api, sid)
    session = api.call("GET", f"/api/sessions/{sid}")
    print(f"  Topic map: '{session['title']}' -> {[x['name'] for x in session['subtopics']]}")
    check(2 <= len(session["subtopics"]) <= 12, "topic map produced subtopics", failures)

    seen: dict[str, dict] = {}
    r = first
    i = 0
    while r["state"] == "question":
        q = r["question"]
        stored = payload_of(q["id"])
        good = i % 2 == 0
        answer = good_answer(stored) if good else bad_answer(stored)
        conf = "high" if not good and i % 4 == 1 else "medium"
        t0 = time.time()
        a = api.call("POST", f"/api/questions/{q['id']}/answer", {"response": answer, "confidence": conf, "skipped": False})
        dt = time.time() - t0
        seen[q["type"]] = {"good": good, "score": a.get("score"), "verdict": a.get("verdict"), "status": a["grade_status"],
                           "outside": q["uses_outside_knowledge"], "secs": round(dt, 1)}
        print(f"  Q{q['position'] + 1:>2} {q['type']:<17} d{q['difficulty']} {'good' if good else 'bad '} -> "
              f"{a['grade_status']} {a.get('verdict')} {a.get('score')}  ({dt:.1f}s){'  [outside knowledge]' if q['uses_outside_knowledge'] else ''}")
        i += 1
        r = next_question(api, sid)

    check(set(seen) == set(types), f"served every question type ({len(seen)}/13)", failures)
    check(all(v["status"] == "done" for v in seen.values()), "every answer graded", failures)
    goods = [v["score"] for v in seen.values() if v["good"] and v["score"] is not None]
    bads = [v["score"] for v in seen.values() if not v["good"] and v["score"] is not None]
    check(min(goods) >= 70 if goods else False, f"answer-key/model answers scored well (min {min(goods) if goods else None})", failures)
    check(max(bads) <= 50 if bads else False, f"bad answers scored low (max {max(bads) if bads else None})", failures)

    print("\n== Finish + results")
    res = api.call("POST", f"/api/sessions/{sid}/finish")
    m = res["mastery"]
    print(f"  Overall {m['overall']['score']}%, weak: {[x['name'] for x in m['subtopics'] if x['weak']]}")
    check(res["session"]["status"] == "completed", "session completed", failures)
    check(res["ungraded"] == [], "no ungraded answers", failures)
    cost = res["cost"]["total"]
    print(f"  Calls {cost['calls']}, input {cost['input']}, cache write {cost['cache_write']}, cache read {cost['cache_read']}, "
          f"output {cost['output']}, cost ${cost['cost']:.4f}")
    check(cost["cache_read"] > 0, "prompt cache hits on the shared document prefix", failures)
    check(cost["cost"] > 0, "cost tracked", failures)

    print("\n== Study guide")
    t0 = time.time()
    g = api.call("POST", f"/api/sessions/{sid}/study-guide")
    while g["status"] == "generating" and time.time() - t0 < 400:
        time.sleep(3)
        g = api.call("GET", f"/api/sessions/{sid}/study-guide")
    print(f"  Status {g['status']} after {time.time() - t0:.0f}s")
    sections = g["content"]["sections"]
    for sec in sections:
        body = sec["section"] or {}
        print(f"  - {sec['name']}: {sec['status']}; formulas={len(body.get('key_formulas', []))}, "
              f"diagram={body.get('diagram', {}).get('include')}, chart={body.get('chart', {}).get('include')}, "
              f"mistakes={len(body.get('common_mistakes', []))}, practice={len(body.get('practice_questions', []))}"
              + (f", error={sec['error']['code']}" if sec.get("error") else ""))
    check(g["status"] == "ready" and all(x["status"] == "ready" for x in sections), "all study-guide sections generated", failures)
    md = api.call("GET", f"/api/sessions/{sid}/study-guide/export/markdown")
    out = ROOT / "samples" / "e2e-study-guide.md"
    out.write_text(md["markdown"], encoding="utf-8")
    check("## " in md["markdown"] and "$$" in md["markdown"], f"Markdown export ({len(md['markdown'])} chars) -> {out.name}", failures)

    print("\n== Retest weak areas")
    rt = api.call("POST", f"/api/sessions/{sid}/retest")
    weak_names = {x["name"] for x in m["subtopics"] if x["weak"]}
    check({x["name"] for x in rt["subtopics"]} == weak_names, "retest limited to weak subtopics", failures)
    q1 = next_question(api, rt["id"])
    check(q1["state"] == "question" and q1["question"]["subtopic_name"] in weak_names, "retest serves a weak-area question", failures)
    api.call("DELETE", f"/api/sessions/{rt['id']}")

    if not args.quick:
        print("\n== Adaptive mini-session (3 multiple-choice questions)")
        a = api.call("POST", "/api/sessions", {
            "material": "", "subject": "Thermodynamics (E2E)", "upload_ids": [up["id"]], "types": ["multiple_choice"],
            "difficulty": 3, "adaptive": True, "count": 3,
        })
        diffs = []
        r = next_question(api, a["id"])
        k = 0
        while r["state"] == "question":
            q = r["question"]
            diffs.append(q["difficulty"])
            stored = payload_of(q["id"])
            api.call("POST", f"/api/questions/{q['id']}/answer", {"response": good_answer(stored) if k == 0 else bad_answer(stored), "confidence": None, "skipped": False})
            k += 1
            r = next_question(api, a["id"])
        print(f"  Difficulties served: {diffs}")
        check(diffs == [3, 4, 3], "adaptive difficulty: up after correct, down after miss", failures)
        api.call("POST", f"/api/sessions/{a['id']}/finish")

    print(f"\nDone in {time.time() - t_start:.0f}s. Session id: {sid}")
    print("FAILURES:\n- " + "\n- ".join(failures) if failures else "ALL CHECKS PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
