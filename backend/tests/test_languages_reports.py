"""Several code languages per session, and reporting poorly made questions."""
from __future__ import annotations

from collections import Counter

from sage import db
from sage.services import sessions as S

from .test_api import correct_answer, create, next_q


def answer(client, q, response=None):
    r = client.post(f"/api/questions/{q['id']}/answer", json={"response": response or correct_answer(q["id"])})
    assert r.status_code == 200, r.text
    return r.json()


def play_all(client, sid):
    served = []
    while (r := next_q(client, sid))["state"] == "question":
        served.append(r["question"])
        answer(client, r["question"])
    return served


# --- Languages -------------------------------------------------------------------------------

def test_code_questions_spread_across_picked_languages(client, fake_claude):
    s = create(client, types=["code"], count=6, languages=["SQL", "Assembly", "JSON"])
    assert s["config"]["languages"] == ["SQL", "Assembly", "JSON"]
    served = play_all(client, s["id"])
    assert Counter(q["language"] for q in served) == {"SQL": 2, "Assembly": 2, "JSON": 2}
    prompt = "\n".join(c["req"].prompt for c in fake_claude.calls if c["purpose"] == "generate")
    assert 'language "SQL"' in prompt and "Language notes" in prompt and "x86-64" in prompt


def test_unknown_language_rejected(client, fake_claude):
    r = client.post("/api/sessions", json={"material": "x", "types": ["code"], "count": 2, "languages": ["COBOL"]})
    assert r.status_code == 400 and "COBOL" in r.json()["error"]["message"]


def test_old_single_language_sessions_still_load(client, fake_claude):
    s = create(client, types=["code"], count=2, language="Java")
    cfg = S.get_session(s["id"])["config"]
    cfg["language"] = cfg.pop("languages")[0]  # what a session saved before this change looks like
    db.execute("UPDATE sessions SET config_json = ? WHERE id = ?", (db.dumps(cfg), s["id"]))
    assert client.get(f"/api/sessions/{s['id']}").json()["config"]["languages"] == ["Java"]


def test_changing_languages_rewrites_upcoming_code_questions(client, fake_claude):
    s = create(client, types=["code"], count=4, languages=["Python"])
    sid = s["id"]
    first = next_q(client, sid)["question"]
    answer(client, first)
    client.put(f"/api/sessions/{sid}/options", json={
        "types": ["code"], "difficulty": 3, "adaptive": False, "count": 4, "languages": ["C", "XML"], "feedback_mode": "immediate",
    })
    rest = play_all(client, sid)
    assert first["language"] == "Python"
    assert len(rest) == 3 and {q["language"] for q in rest} <= {"C", "XML"} and len({q["language"] for q in rest}) == 2


# --- Reports -----------------------------------------------------------------------------------

def report(client, q, reason="wrong_answer", note=""):
    return client.post(f"/api/questions/{q['id']}/report", json={"reason": reason, "note": note})


def test_reporting_the_question_on_screen_replaces_it_at_the_end(client, fake_claude):
    s = create(client, types=["multiple_choice"], count=3)
    sid = s["id"]
    bad = next_q(client, sid)["question"]
    r = report(client, bad, "unclear", "Two options are both right")
    assert r.status_code == 200 and r.json()["replaced"]
    assert db.query_one("SELECT status FROM questions WHERE id = ?", (bad["id"],))["status"] == "discarded"

    served = play_all(client, sid)
    assert len(served) == 3 and bad["id"] not in {q["id"] for q in served}
    assert [q["position"] for q in served] == [0, 1, 2]
    # Later questions were written knowing about the report.
    prompts = [c["req"].prompt for c in fake_claude.calls if c["purpose"] == "generate"]
    assert any("<reported_questions>" in p and "Unclear or ambiguous" in p and "Two options are both right" in p for p in prompts)
    res = client.post(f"/api/sessions/{sid}/finish").json()
    assert res["mastery"]["overall"]["n"] == 3 and res["reported"] == []


def test_reporting_an_answered_question_leaves_it_out_of_the_score(client, fake_claude):
    s = create(client, types=["true_false"], count=2)
    sid = s["id"]
    q1 = next_q(client, sid)["question"]
    answer(client, q1, {"value": not S.load_question(q1["id"])["payload"]["correct"]})  # wrong
    q2 = next_q(client, sid)["question"]
    answer(client, q2)  # right
    res = client.post(f"/api/sessions/{sid}/finish").json()
    assert res["mastery"]["overall"]["score"] == 50

    r = report(client, q1, "wrong_answer")
    assert r.status_code == 200 and r.json()["excluded"]
    res = client.get(f"/api/sessions/{sid}/results").json()
    assert res["mastery"]["overall"]["n"] == 1 and res["mastery"]["overall"]["score"] == 100
    assert res["reported"] == [q1["id"]] and res["missed"] == []
    item = next(i for i in res["questions"] if i["id"] == q1["id"])
    assert item["reported"] and item["report_reason"] == "The answer key is wrong"
    assert next(h for h in client.get("/api/history").json() if h["id"] == sid)["score"] == 100


def test_report_validation(client, fake_claude):
    s = create(client, types=["true_false"], count=2)
    q = next_q(client, s["id"])["question"]
    assert report(client, q, "bogus").status_code == 400
    assert client.post("/api/questions/nope/report", json={"reason": "other"}).status_code == 404
    pool = db.query_one("SELECT id FROM questions WHERE session_id = ? AND status = 'pool'", (s["id"],))
    if pool:  # not shown yet
        assert report(client, {"id": pool["id"]}).status_code == 409


def test_reporting_the_last_question_still_gives_a_replacement(client, fake_claude):
    s = create(client, types=["true_false"], count=1)
    q = next_q(client, s["id"])["question"]
    assert report(client, q).json()["replaced"]
    served = play_all(client, s["id"])
    assert len(served) == 1 and served[0]["id"] != q["id"]
