"""Skipping questions to the end of the quiz, and changing question options mid-session."""
from __future__ import annotations

from sage import db

from .test_api import correct_answer, create, next_q


def answer(client, q, response=None, **extra):
    r = client.post(f"/api/questions/{q['id']}/answer", json={"response": response or correct_answer(q["id"]), **extra})
    assert r.status_code == 200, r.text
    return r.json()


def defer(client, q):
    return client.post(f"/api/questions/{q['id']}/defer")


def test_skipped_question_comes_back_at_the_end(client, fake_claude):
    s = create(client, types=["multiple_choice"], count=4)
    sid = s["id"]
    first = next_q(client, sid)["question"]
    r = defer(client, first)
    assert r.status_code == 200 and r.json()["skipped_waiting"] == 1
    assert client.get(f"/api/sessions/{sid}").json()["progress"]["skipped_waiting"] == 1

    seen = []
    for _ in range(3):
        q = next_q(client, sid)["question"]
        assert q["id"] != first["id"] and not q["was_skipped"]
        seen.append(q)
        answer(client, q)
    back = next_q(client, sid)["question"]
    assert back["id"] == first["id"] and back["was_skipped"]
    assert [q["position"] for q in seen] + [back["position"]] == [0, 1, 2, 3]
    answer(client, back)
    assert next_q(client, sid)["state"] == "done"
    res = client.post(f"/api/sessions/{sid}/finish").json()
    assert res["mastery"]["overall"]["n"] == 4 and res["mastery"]["overall"]["score"] == 100


def test_skipping_twice_keeps_order(client, fake_claude):
    s = create(client, types=["true_false"], count=3)
    sid = s["id"]
    a = next_q(client, sid)["question"]
    defer(client, a)
    b = next_q(client, sid)["question"]
    defer(client, b)
    c = next_q(client, sid)["question"]
    answer(client, c)
    assert next_q(client, sid)["question"]["id"] == a["id"]
    defer(client, a)  # skip again: goes behind b
    assert next_q(client, sid)["question"]["id"] == b["id"]


def test_last_question_cannot_be_skipped(client, fake_claude):
    s = create(client, types=["true_false"], count=1)
    q = next_q(client, s["id"])["question"]
    r = defer(client, q)
    assert r.status_code == 409 and "last question" in r.json()["error"]["message"]


def test_cannot_skip_an_answered_question(client, fake_claude):
    s = create(client, types=["true_false"], count=2)
    q = next_q(client, s["id"])["question"]
    answer(client, q)
    assert defer(client, q).status_code == 409


def test_i_dont_know_counts_as_a_miss_not_a_skip(client, fake_claude):
    s = create(client, types=["true_false"], count=2)
    q = next_q(client, s["id"])["question"]
    a = answer(client, q, response={}, skipped=True)
    assert a["verdict"] == "incorrect" and a["skipped"]
    assert client.get(f"/api/sessions/{s['id']}").json()["progress"]["skipped_waiting"] == 0


def test_changing_options_only_affects_upcoming_and_skipped_questions(client, fake_claude):
    s = create(client, types=["multiple_choice"], count=6)
    sid = s["id"]
    q1 = next_q(client, sid)["question"]
    answer(client, q1)
    q2 = next_q(client, sid)["question"]
    defer(client, q2)
    q3 = next_q(client, sid)["question"]  # on screen while options change

    r = client.put(f"/api/sessions/{sid}/options", json={
        "types": ["true_false"], "difficulty": 2, "adaptive": False, "count": 5, "language": "Python", "feedback_mode": "end",
    })
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["config"]["types"] == ["true_false"] and view["config"]["count"] == 5 and view["config"]["feedback_mode"] == "end"

    # The answered question and the one on screen are untouched.
    assert db.query_one("SELECT status, type FROM questions WHERE id = ?", (q1["id"],)) == {"status": "served", "type": "multiple_choice"}
    assert next_q(client, sid)["question"]["id"] == q3["id"]
    answer(client, q3)
    # The skipped multiple-choice question no longer fits, so it was discarded and rewritten.
    assert db.query_one("SELECT status FROM questions WHERE id = ?", (q2["id"],))["status"] == "discarded"

    rest = []
    while (r := next_q(client, sid))["state"] == "question":
        q = r["question"]
        rest.append(q)
        answer(client, q)
    assert [q["type"] for q in rest] == ["true_false"] * 3  # 5 total: q1, q3, then three more
    assert all(q["difficulty"] == 2 for q in rest)
    q2_slot = db.query_one("SELECT slot FROM questions WHERE id = ?", (q2["id"],))["slot"]
    assert db.query_one("SELECT slot FROM questions WHERE id = ?", (rest[-1]["id"],))["slot"] == q2_slot  # rewritten skip comes last
    res = client.post(f"/api/sessions/{sid}/finish").json()
    assert res["mastery"]["overall"]["n"] == 5


def test_skipped_question_rewritten_when_it_comes_back(client, fake_claude):
    s = create(client, types=["multiple_choice", "true_false"], count=3)
    sid = s["id"]
    first = next_q(client, sid)["question"]
    defer(client, first)
    other = "true_false" if first["type"] == "multiple_choice" else "multiple_choice"
    client.put(f"/api/sessions/{sid}/options", json={
        "types": [other], "difficulty": 3, "adaptive": False, "count": 3, "language": "Python", "feedback_mode": "immediate",
    })
    served = []
    while (r := next_q(client, sid))["state"] == "question":
        served.append(r["question"])
        answer(client, r["question"])
    assert len(served) == 3
    assert all(q["type"] == other for q in served if q["id"] != first["id"])
    assert first["id"] not in {q["id"] for q in served}  # replaced, not reused


def test_skipped_question_kept_when_options_still_fit(client, fake_claude):
    s = create(client, types=["true_false"], count=3)
    sid = s["id"]
    first = next_q(client, sid)["question"]
    defer(client, first)
    client.put(f"/api/sessions/{sid}/options", json={
        "types": ["true_false", "multiple_choice"], "difficulty": 3, "adaptive": False, "count": 3,
        "language": "Python", "feedback_mode": "end",
    })
    ids = []
    while (r := next_q(client, sid))["state"] == "question":
        ids.append(r["question"]["id"])
        answer(client, r["question"])
    assert ids[-1] == first["id"]


def test_raising_the_count_adds_questions(client, fake_claude):
    s = create(client, types=["true_false"], count=2)
    sid = s["id"]
    answer(client, next_q(client, sid)["question"])
    client.put(f"/api/sessions/{sid}/options", json={
        "types": ["true_false"], "difficulty": 3, "adaptive": False, "count": 4, "language": "Python", "feedback_mode": "immediate",
    })
    n = 1
    while (r := next_q(client, sid))["state"] == "question":
        assert r["question"]["total"] == 4
        answer(client, r["question"])
        n += 1
    assert n == 4


def test_options_validation(client, fake_claude):
    s = create(client, types=["true_false"], count=3)
    sid = s["id"]
    answer(client, next_q(client, sid)["question"])
    next_q(client, sid)  # second question on screen
    base = {"types": ["true_false"], "difficulty": 3, "adaptive": False, "language": "Python", "feedback_mode": "immediate"}
    r = client.put(f"/api/sessions/{sid}/options", json={**base, "count": 1})
    assert r.status_code == 400 and "can't be lower than 2" in r.json()["error"]["message"]
    assert client.put(f"/api/sessions/{sid}/options", json={**base, "count": 2, "types": []}).status_code == 400
    assert client.put(f"/api/sessions/{sid}/options", json={**base, "count": 2, "difficulty": 9}).status_code == 400
    client.post(f"/api/sessions/{sid}/finish")
    assert client.put(f"/api/sessions/{sid}/options", json={**base, "count": 3}).status_code == 409


def test_adaptive_level_ignores_skips(client, fake_claude):
    s = create(client, types=["multiple_choice"], count=4, adaptive=True, difficulty=3)
    sid = s["id"]
    q1 = next_q(client, sid)["question"]
    defer(client, q1)
    q2 = next_q(client, sid)["question"]
    assert q2["difficulty"] == 3  # skipping didn't move the level
    answer(client, q2)            # correct -> up
    assert next_q(client, sid)["question"]["difficulty"] == 4


def test_session_view_exposes_settings_for_the_options_dialog(client, fake_claude):
    s = create(client, types=["code", "true_false"], count=3, language="C++", material="Pointers and references")
    v = client.get(f"/api/sessions/{s['id']}").json()
    assert v["material"] == "Pointers and references" and v["editable"]
    assert v["config"]["types"] == ["true_false", "code"] and v["config"]["languages"] == ["C++"]
    assert "slots" not in v["config"] and "deferred_slots" not in v["config"]
    assert {"answered", "skipped_waiting"} <= set(v["progress"])


def test_rewritten_skip_still_counts_and_is_marked(client, fake_claude):
    s = create(client, types=["multiple_choice", "true_false"], count=3)
    sid = s["id"]
    first = next_q(client, sid)["question"]
    defer(client, first)
    other = "true_false" if first["type"] == "multiple_choice" else "multiple_choice"
    client.put(f"/api/sessions/{sid}/options", json={
        "types": [other], "difficulty": 3, "adaptive": False, "count": 3, "language": "Python", "feedback_mode": "immediate",
    })
    assert client.get(f"/api/sessions/{sid}").json()["progress"]["skipped_waiting"] == 1
    last = None
    while (r := next_q(client, sid))["state"] == "question":
        last = r["question"]
        answer(client, last)
    assert last["was_skipped"] and last["type"] == other and last["id"] != first["id"]
