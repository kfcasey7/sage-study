"""Live end-to-end check of Study Sets against a running Sage Study backend, using the real Claude Code
CLI on your Claude subscription (it counts toward your plan's usage limits).

    python scripts/e2e_sets.py --url http://127.0.0.1:8765

Creates a Study Set from samples/thermo-first-law.pdf plus a web link, waits for the Material Breakdown,
appends a prompt and another link (merged breakdown), generates a study guide for two subtopics, builds a
video playlist, takes a 3-question quiz using "Find video" once before answering, and checks that
everything is attached to the set in History.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
H = {"x-sage-client": "1"}


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, body: dict | None = None, timeout: float = 900):
        data = json.dumps(body).encode() if body is not None else (b"" if method != "GET" else None)
        headers = {**H, "content-type": "application/json"} if body is not None else H
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path} -> {e.code}: {e.read().decode()[:600]}") from None

    def upload(self, path: Path, **fields: str):
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                     f"Content-Type: application/pdf\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(self.base + "/api/sources/files", data=b"".join(parts), method="POST",
                                     headers={**H, "content-type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())

    get = lambda self, p: self.call("GET", p)  # noqa: E731
    post = lambda self, p, b=None: self.call("POST", p, b if b is not None else {})  # noqa: E731


def wait(label: str, fn, timeout: float = 900, every: float = 4):
    t0 = time.time()
    while time.time() - t0 < timeout:
        out = fn()
        if out:
            print(f"  {label}: done in {time.time() - t0:.0f}s")
            return out
        time.sleep(every)
    raise SystemExit(f"timed out waiting for {label}")


def step(msg: str) -> None:
    print(f"\n== {msg}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--link", default="https://en.wikipedia.org/wiki/First_law_of_thermodynamics")
    ap.add_argument("--append-link", default="https://en.wikipedia.org/wiki/Second_law_of_thermodynamics")
    args = ap.parse_args()
    api = Api(args.url)
    draft = uuid.uuid4().hex

    step("Sources: the sample PDF and a web link")
    pdf = api.upload(ROOT / "samples" / "thermo-first-law.pdf", draft_id=draft)
    link = api.call("POST", "/api/sources/links", {"urls": [args.link], "draft_id": draft})[0]
    rows = wait("link read", lambda: (lambda r: r if all(x["status"] != "processing" for x in r) else None)(
        api.get(f"/api/sources?ids={pdf['id']},{link['id']}")), timeout=120, every=1)
    for r in rows:
        print(f"  {r['status']:>6}  {r['source_type']:<8} {r['title'][:60]}  ({r['char_count']} chars)")
    assert all(r["status"] == "ready" for r in rows), rows

    step("Create the Study Set and wait for the Material Breakdown")
    s = api.post("/api/sets", {"subject": "Thermodynamics", "title": "",
                               "prompt": "First law of thermodynamics: internal energy, heat and work, and enthalpy.",
                               "source_ids": [pdf["id"], link["id"]]})
    set_id = s["id"]
    v = wait("breakdown", lambda: (lambda x: x if x["breakdown"]["status"] in ("ready", "failed") else None)(api.get(f"/api/sets/{set_id}")))
    assert v["breakdown"]["status"] == "ready", v["breakdown"]["error"]
    print(f"  title: {v['title']}")
    print(f"  overview: {v['breakdown']['overview'][:200]}")
    for sub in v["subtopics"]:
        print(f"  - {sub['name']} (difficulty {sub['difficulty']}, {len(sub['key_concepts'])} concepts, "
              f"{len(sub['formulas'])} formulas, sources {[x['label'] for x in v['sources'] if x['id'] in sub['source_ids']]})")
    print(f"  coverage notes: {v['breakdown']['coverage_notes']}")
    print(f"  map: {v['breakdown']['map_mermaid'][:120]!r}")
    first_ids = [x["id"] for x in v["subtopics"]]

    step("Append a prompt and another link; merge the breakdown")
    added = api.call("POST", "/api/sources/links", {"urls": [args.append_link], "set_id": set_id})[0]
    wait("appended link read", lambda: api.get(f"/api/sources?ids={added['id']}")[0]["status"] != "processing", timeout=120, every=1)
    api.post(f"/api/sets/{set_id}/append", {"prompt": "Also cover entropy and the second law of thermodynamics."})
    v2 = wait("merged breakdown", lambda: (lambda x: x if x["breakdown"]["status"] in ("ready", "failed") else None)(api.get(f"/api/sets/{set_id}")))
    assert v2["breakdown"]["status"] == "ready", v2["breakdown"]["error"]
    kept = [x for x in v2["subtopics"] if x["id"] in first_ids]
    new = [x["name"] for x in v2["subtopics"] if x["is_new"]]
    print(f"  {len(kept)}/{len(first_ids)} earlier subtopics kept their ids; new: {new}; "
          f"updated: {[x['name'] for x in v2['subtopics'] if x['is_updated']]}; removed: {v2['breakdown']['removed']}")
    print(f"  prompts: {[p['text'][:40] for p in v2['prompts']]}")
    assert new or any(x["is_updated"] for x in v2["subtopics"]), "the append changed nothing"
    assert len(kept) >= len(first_ids) - 1

    changed = [x["id"] for x in v2["subtopics"] if x["is_new"] or x["is_updated"]]
    pick = [v2["subtopics"][0]["id"], changed[0] if changed[0] != v2["subtopics"][0]["id"] else v2["subtopics"][1]["id"]]

    step("Study guide for two subtopics")
    g = api.post(f"/api/sets/{set_id}/guides", {"subtopic_ids": pick})
    g = wait("study guide", lambda: (lambda x: x if x["status"] != "generating" else None)(api.get(f"/api/guides/{g['id']}")))
    for sec in g["content"]["sections"]:
        sect = sec.get("section") or {}
        print(f"  {sec['status']:>6}  {sec['name']}: {len(sect.get('key_formulas', []))} formulas, "
              f"diagram={bool(sect.get('diagram', {}).get('include'))}, chart={bool(sect.get('chart', {}).get('include'))}")
    assert g["status"] == "ready"

    step("Video playlist for the same subtopics")
    p = api.post(f"/api/sets/{set_id}/playlists", {"subtopic_ids": pick})
    p = wait("playlist", lambda: (lambda x: x if x["status"] != "generating" else None)(api.get(f"/api/playlists/{p['id']}")))
    print(f"  status {p['status']} via {p['mode']}; YouTube playlist link: {p['youtube_playlist_url']}")
    for grp in p["groups"]:
        print(f"  {grp['name']}:")
        for vid in grp["videos"]:
            print(f"    - {vid['title'][:70]} | {vid['channel']} | {vid['duration_s']}s | {vid['url']}")
            print(f"      why: {vid['reason']}")
    assert p["status"] == "ready" and all(grp["videos"] for grp in p["groups"])

    step("3-question quiz, using Find video once before answering")
    q = api.post(f"/api/sets/{set_id}/quiz", {"subtopic_ids": pick, "types": ["multiple_choice", "true_false", "short_response"],
                                               "difficulty": 3, "adaptive": False, "count": 3, "languages": ["Python"]})
    sid = q["id"]
    used_on = None
    for i in range(3):
        n = wait(f"question {i + 1}", lambda: (lambda r: r if r["state"] != "pending" else None)(api.get(f"/api/sessions/{sid}/next")), every=2)
        assert n["state"] == "question", n
        qq = n["question"]
        print(f"  Q{i + 1} [{qq['type']}] {qq['prompt'][:100]}")
        if i == 0:
            vids = api.post(f"/api/questions/{qq['id']}/videos")
            used_on = qq["id"]
            print(f"    Find video -> {[x['title'][:50] for x in vids['videos']]} (used before answering: {vids['used_before_answer']})")
        if qq["type"] == "multiple_choice":
            resp = {"choice": qq["options"][0]["id"]}
        elif qq["type"] == "true_false":
            resp = {"value": True}
        else:
            resp = {"text": "The change in internal energy equals heat added to the system minus the work done by the system."}
        a = api.post(f"/api/questions/{qq['id']}/answer", {"response": resp, "confidence": "medium", "skipped": False})
        print(f"    answered: {a.get('grade_status')} {a.get('verdict') or ''}")
    res = api.post(f"/api/sessions/{sid}/finish")
    helped = {x["id"]: x["used_video_help"] for x in res["questions"]}
    print(f"  score {res['mastery']['overall']['score']}%; used help: {helped}")
    assert helped[used_on] and sum(helped.values()) == 1

    step("Everything is saved on the set and in History")
    row = next(x for x in api.get("/api/sets") if x["id"] == set_id)
    print(f"  History row: {row['title']} | sources {row['sources']} | subtopics {row['subtopics']} | quizzes {row['quizzes']} "
          f"| guides {row['guides']} | playlists {row['playlists']} | last score {row['last_score']}")
    v3 = api.get(f"/api/sets/{set_id}")
    m = {x["name"]: x["mastery"]["score"] for x in v3["subtopics"] if x["mastery"]}
    print(f"  mastery on the breakdown: {m}")
    assert row["quizzes"] == 1 and row["guides"] == 1 and row["playlists"] == 1 and row["sources"] == 3 and m
    print(f"\nAll checks passed. Open it in the app: #/sets/{set_id}")


if __name__ == "__main__":
    main()
