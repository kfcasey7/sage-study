"""Material Breakdown: merging on append keeps subtopic ids (and so mastery) stable; Study Set quizzes,
subtopic study guides, and migrated sets."""
from __future__ import annotations

import itertools

from sage.services.breakdown import merge_subtopics

from .conftest import wait_for
from .test_api import correct_answer, next_q


def sub(id, name, status="active", created=1, updated=1, **kw):
    return {"id": id, "name": name, "summary": kw.get("summary", f"{name} summary"), "key_concepts": kw.get("key_concepts", ["k"]),
            "formulas": [], "difficulty": 3, "source_ids": [], "status": status, "created_version": created, "updated_version": updated}


def ret(ref, name, change="unchanged", **kw):
    return {"ref": ref, "change": change, "name": name, "summary": kw.get("summary", f"{name} summary"),
            "key_concepts": kw.get("key_concepts", ["k"]), "formulas": [], "difficulty": 3, "source_ids": []}


def ids():
    counter = itertools.count(1)
    return lambda: f"new{next(counter)}"


def test_merge_keeps_ids_and_marks_new():
    existing = [sub("a", "Carnot cycle"), sub("b", "Entropy")]
    rows, removed = merge_subtopics(existing, [ret("a", "Carnot cycle"), ret("", "Otto cycle", "new"), ret("b", "Entropy")], 2, ids())
    assert [(r["id"], r["position"]) for r in rows] == [("a", 0), ("new1", 1), ("b", 2)]
    assert rows[1]["created_version"] == rows[1]["updated_version"] == 2
    assert rows[0]["updated_version"] == 1 and rows[2]["updated_version"] == 1  # unchanged
    assert removed == []


def test_merge_rename_by_ref_and_name_fallback():
    existing = [sub("a", "Carnot cycle"), sub("b", "Entropy")]
    rows, removed = merge_subtopics(existing, [ret("a", "The Carnot cycle", "updated"), ret("bogus", "entropy")], 3, ids())
    assert [r["id"] for r in rows] == ["a", "b"]
    assert rows[0]["name"] == "The Carnot cycle" and rows[0]["updated_version"] == 3
    assert rows[1]["updated_version"] == 1  # matched by name; same content


def test_merge_updated_only_when_content_really_changes():
    existing = [sub("a", "Carnot cycle")]
    rows, _ = merge_subtopics(existing, [ret("a", "Carnot cycle", "updated")], 2, ids())  # says updated, isn't
    assert rows[0]["updated_version"] == 1
    rows, _ = merge_subtopics(existing, [ret("a", "Carnot cycle", "unchanged", summary="Reworded")], 2, ids())
    assert rows[0]["updated_version"] == 1  # Claude says unchanged: a reword isn't a change
    rows, _ = merge_subtopics(existing, [ret("a", "Carnot cycle", "updated", key_concepts=["k", "regenerator"])], 2, ids())
    assert rows[0]["updated_version"] == 2


def test_merge_removes_and_revives():
    existing = [sub("a", "Carnot cycle"), sub("b", "Entropy"), sub("c", "Old topic", status="removed")]
    rows, removed = merge_subtopics(existing, [ret("a", "Carnot cycle"), ret("c", "Old topic")], 4, ids())
    assert removed == ["b"]
    assert [r["id"] for r in rows] == ["a", "c"]
    assert rows[1]["status"] == "active" and rows[1]["updated_version"] == 4


def test_merge_never_matches_one_subtopic_twice():
    existing = [sub("a", "Carnot cycle")]
    rows, _ = merge_subtopics(existing, [ret("a", "Carnot cycle"), ret("a", "Carnot cycle II")], 2, ids())
    assert [r["id"] for r in rows] == ["a", "new1"]


# --- Study Set flows -------------------------------------------------------------------------------

def make_set(client, prompt="Heat engines"):
    src = client.post("/api/sources/files", files={"file": ("notes.txt", b"Carnot and Otto cycles. " * 40, "text/plain")},
                      data={"draft_id": "d"}).json()
    s = client.post("/api/sets", json={"prompt": prompt, "subject": "Thermo", "source_ids": [src["id"]]}).json()
    return wait_ready(client, s["id"])


def wait_ready(client, set_id):
    return wait_for(lambda: (lambda v: v if v["breakdown"]["status"] == "ready" else None)(client.get(f"/api/sets/{set_id}").json()))


def take_quiz(client, sid):
    while True:
        r = next_q(client, sid)
        if r["state"] == "done":
            break
        q = r["question"]
        client.post(f"/api/questions/{q['id']}/answer", json={"response": correct_answer(q["id"]), "confidence": "high", "skipped": False})
    return client.post(f"/api/sessions/{sid}/finish").json()


def test_set_breakdown_quiz_mastery_and_append(client, fake_claude):
    view = make_set(client)
    assert view["title"] == "Test Set"
    assert view["breakdown"]["overview"] and view["breakdown"]["map_mermaid"].startswith("flowchart")
    alpha, beta = view["subtopics"]
    assert alpha["name"] == "Alpha" and alpha["source_ids"] == [view["sources"][0]["id"]]
    assert not alpha["is_new"] and alpha["mastery"] is None  # nothing to compare with on a first breakdown
    assert view["sources"][0]["label"] == "S1" and view["sources"][0]["in_breakdown"]
    prompt = next(c for c in fake_claude.calls if c["purpose"] == "breakdown")["req"].prompt
    assert "[S1] notes.txt" in prompt and "- S1: notes.txt" in prompt

    # Quiz on one subtopic, options chosen at quiz time
    s = client.post(f"/api/sets/{view['id']}/quiz", json={"subtopic_ids": [alpha["id"]], "types": ["multiple_choice"],
                                                          "difficulty": 2, "count": 2}).json()
    assert s["study_set_id"] == view["id"] and [t["name"] for t in s["subtopics"]] == ["Alpha"]
    res = take_quiz(client, s["id"])
    assert res["mastery"]["overall"]["score"] == 100
    view = client.get(f"/api/sets/{view['id']}").json()
    assert view["subtopics"][0]["mastery"]["score"] == 100 and view["subtopics"][0]["mastery"]["n"] == 2
    assert view["subtopics"][1]["mastery"] is None
    assert view["quizzes"][0]["id"] == s["id"] and view["quizzes"][0]["status"] == "completed"

    # Append a prompt: existing subtopics keep their ids and mastery; the new one is marked
    r = client.post(f"/api/sets/{view['id']}/append", json={"prompt": "Also cover the Rankine cycle"})
    assert r.status_code == 200, r.text
    view2 = wait_ready(client, view["id"])
    assert [x["id"] for x in view2["subtopics"][:2]] == [alpha["id"], beta["id"]]
    added = view2["subtopics"][2]
    assert added["is_new"] and not view2["subtopics"][0]["is_new"]
    assert view2["subtopics"][0]["mastery"]["score"] == 100
    assert [p["text"] for p in view2["prompts"]] == ["Heat engines", "Also cover the Rankine cycle"]
    merge_prompt = [c for c in fake_claude.calls if c["purpose"] == "breakdown"][-1]["req"].prompt
    assert f'ref="{alpha["id"]}"' in merge_prompt and 'newest="true"' in merge_prompt

    # Nothing new to merge
    assert client.post(f"/api/sets/{view['id']}/append", json={"prompt": ""}).status_code == 400


def test_append_new_source_marks_it(client, fake_claude):
    view = make_set(client)
    up = client.post("/api/sources/files", files={"file": ("ch7.txt", b"Rankine cycle. " * 40, "text/plain")},
                     data={"set_id": view["id"]}).json()
    v = client.get(f"/api/sets/{view['id']}").json()
    assert v["sources_changed"] and not next(x for x in v["sources"] if x["id"] == up["id"])["in_breakdown"]
    client.post(f"/api/sets/{view['id']}/append", json={"prompt": ""})
    v = wait_ready(client, view["id"])
    assert not v["sources_changed"]
    prompt = [c for c in fake_claude.calls if c["purpose"] == "breakdown"][-1]["req"].prompt
    assert "- S2: ch7.txt (text, new)" in prompt


def test_subtopic_study_guide_uses_quiz_history(client, fake_claude):
    view = make_set(client)
    alpha, beta = view["subtopics"]
    s = client.post(f"/api/sets/{view['id']}/quiz", json={"subtopic_ids": [alpha["id"]], "types": ["multiple_choice"], "count": 1}).json()
    take_quiz(client, s["id"])
    g = client.post(f"/api/sets/{view['id']}/guides", json={"subtopic_ids": [alpha["id"], beta["id"]]}).json()
    assert g["kind"] == "subtopics" and g["meta"]["title"] == "Test Set"
    guide = wait_for(lambda: (lambda r: r if r["status"] == "ready" else None)(client.get(f"/api/guides/{g['id']}").json()))
    assert [x["name"] for x in guide["content"]["sections"]] == ["Alpha", "Beta"]
    prompts = [c["req"].prompt for c in fake_claude.calls if c["purpose"] == "study_guide"]
    assert any("Quiz score on this subtopic so far: 100%" in p for p in prompts)
    assert any("hasn't been quizzed on this subtopic yet" in p for p in prompts)
    assert client.get(f"/api/sets/{view['id']}").json()["guides"][0]["id"] == g["id"]
    # Same section format: diagram repair and retry work by guide id
    fixed = client.post(f"/api/guides/{g['id']}/repair-diagram", json={"subtopic_id": alpha["id"], "error": "Parse error"}).json()
    assert fixed["diagram"]["repaired"]
    assert client.post(f"/api/guides/{g['id']}/sections/{beta['id']}/retry").json()["status"] == "generating"


def test_guide_and_quiz_need_subtopics(client, fake_claude):
    view = make_set(client)
    assert client.post(f"/api/sets/{view['id']}/guides", json={"subtopic_ids": ["nope"]}).status_code == 400
    assert client.post(f"/api/sets/{view['id']}/quiz", json={"subtopic_ids": [], "types": ["multiple_choice"]}).status_code == 400


def test_breakdown_failure_keeps_set_and_can_retry(client, fake_claude):
    from sage.errors import AppError

    def fail(_req):
        raise AppError("usage_limit", "Claude usage limit reached.")
    fake_claude.queue("breakdown", fail)
    s = client.post("/api/sets", json={"prompt": "Statics"}).json()
    v = wait_for(lambda: (lambda v: v if v["breakdown"]["status"] == "failed" else None)(client.get(f"/api/sets/{s['id']}").json()))
    assert v["breakdown"]["error"]["code"] == "usage_limit"
    client.post(f"/api/sets/{s['id']}/breakdown")
    assert len(wait_ready(client, s["id"])["subtopics"]) == 2


def test_old_endpoint_sessions_get_a_set_and_can_build_a_breakdown(client, fake_claude):
    s = client.post("/api/sessions", json={"material": "Chapter 1", "subject": "Thermo", "types": ["multiple_choice"], "count": 2}).json()
    take_quiz(client, s["id"])
    set_id = client.get(f"/api/sessions/{s['id']}").json()["study_set_id"]
    v = client.get(f"/api/sets/{set_id}").json()
    assert v["breakdown"]["status"] == "legacy"
    before = [x["id"] for x in v["subtopics"]]
    assert len(before) == 2 and v["subtopics"][0]["mastery"]["n"] >= 1
    client.post(f"/api/sets/{set_id}/breakdown")
    v = wait_ready(client, set_id)
    assert [x["id"] for x in v["subtopics"]] == before  # quiz results stay attached
    assert not any(x["is_new"] or x["is_updated"] for x in v["subtopics"])  # first full breakdown: no badges
    # A retest joins the same set
    r = client.post(f"/api/sessions/{s['id']}/retest")
    if r.status_code == 200:
        assert r.json()["study_set_id"] == set_id
