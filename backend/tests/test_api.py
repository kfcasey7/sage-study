"""End-to-end API flow against a fake Claude."""
from __future__ import annotations

import anthropic
import httpx2 as httpx
import pytest

from sage import db, desktop
from sage.services import sessions as S

from .conftest import FakeMessage, FakeText, wait_for
from .samples import sample


def upload_text(client, name="notes.txt", text="Heat engines convert heat into work. " * 20):
    r = client.post("/api/uploads", files={"file": (name, text.encode(), "text/plain")})
    assert r.status_code == 200, r.text
    return r.json()


def create(client, **over):
    body = {"material": "Chapter 1", "subject": "Thermo", "upload_ids": [], "types": ["multiple_choice"],
            "difficulty": 3, "adaptive": False, "count": 5, "language": "Python", **over}
    r = client.post("/api/sessions", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def next_q(client, sid, timeout=10.0):
    def poll():
        r = client.get(f"/api/sessions/{sid}/next").json()
        return r if r["state"] in ("question", "done", "error") else None
    return wait_for(poll, timeout)


def correct_answer(question_id: str) -> dict:
    q = S.load_question(question_id)
    p, d = q["payload"], q["display"]
    t = p["type"]
    if t == "multiple_choice":
        return {"choice": p["correct_index"]}
    if t == "select_all":
        return {"choices": p["correct_indices"]}
    if t == "true_false":
        return {"value": p["correct"]}
    if t == "matching":
        return {"matches": [d["right"].index(pair["right"]) for pair in p["pairs"]]}
    if t == "ordering":
        return {"order": list(range(len(p["items"])))}
    if t == "fill_blank":
        return {"blanks": [b["accepted_answers"][0] for b in p["blanks"]]}
    return {"text": "An answer"}


def wrong_answer(question_id: str) -> dict:
    q = S.load_question(question_id)
    p = q["payload"]
    if p["type"] == "multiple_choice":
        return {"choice": (p["correct_index"] + 1) % len(p["options"])}
    if p["type"] == "true_false":
        return {"value": not p["correct"]}
    return {"text": "wrong"}


def test_guard_rejects_missing_header_and_foreign_host(fake_claude):
    from fastapi.testclient import TestClient
    from sage.app import create_app

    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        assert c.put("/api/settings", json={"theme": "dark"}).status_code == 403
        assert c.get("/api/settings").status_code == 200
    with TestClient(app, base_url="http://evil.example:8765", headers={"x-sage-client": "1"}) as c:
        assert c.get("/api/settings").status_code == 403


def test_settings_never_expose_key(client):
    body = client.get("/api/settings").json()
    assert body["key"] == {"key_set": True, "source": "env", "last4": "3456"}
    assert "sk-ant-test-key-123456" not in str(body)
    r = client.put("/api/settings", json={"model": "claude-haiku-5-5", "feedback_mode": "end", "theme": "dark"})
    assert r.json()["settings"]["model"] == "claude-haiku-5-5"
    assert client.put("/api/settings", json={"model": "gpt-4"}).status_code == 400


def test_full_non_adaptive_flow(client, fake_claude):
    up = upload_text(client)
    s = create(client, upload_ids=[up["id"]], types=["multiple_choice", "true_false", "ordering", "matching", "select_all"], count=7)
    sid = s["id"]
    seen_types = set()
    for i in range(7):
        r = next_q(client, sid)
        assert r["state"] == "question", r
        q = r["question"]
        assert q["position"] == i and q["total"] == 7
        assert "correct_index" not in q and "rubric" not in q
        seen_types.add(q["type"])
        a = client.post(f"/api/questions/{q['id']}/answer", json={"response": correct_answer(q["id"]), "confidence": "high"}).json()
        assert a["grade_status"] == "done" and a["verdict"] == "correct" and a["revealed"]
    assert next_q(client, sid)["state"] == "done"
    assert seen_types == {"multiple_choice", "true_false", "ordering", "matching", "select_all"}

    res = client.post(f"/api/sessions/{sid}/finish").json()
    assert res["session"]["status"] == "completed"
    assert res["mastery"]["overall"]["score"] == 100
    assert res["missed"] == []
    # topic map + 2 generation batches (5 + 2); objective answers never call Claude
    assert fake_claude.purposes() == ["topic_map", "generate", "generate"]
    assert res["cost"]["total"]["calls"] == 3 and res["cost"]["total"]["cost"] > 0
    assert res["cost"]["total"]["cache_read"] > 0

    # Every call shares the same cached prefix: system + documents + preamble with a 1h breakpoint.
    prefixes = [c["params"]["messages"][0]["content"][:-1] for c in fake_claude.calls]
    assert all(p == prefixes[0] for p in prefixes)
    assert prefixes[0][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert prefixes[0][0]["source"]["type"] == "text"
    assert {c["params"]["output_config"]["effort"] for c in fake_claude.calls} == {"medium"}
    assert fake_claude.calls[0]["params"]["fallbacks"] == "default"

    assert client.post(f"/api/sessions/{sid}/study-guide").status_code == 400  # nothing weak


def test_claude_graded_answers_and_study_guide(client, fake_claude, tmp_path, monkeypatch):
    s = create(client, types=["short_response", "multiple_choice"], count=4)
    sid = s["id"]
    for _ in range(4):
        q = next_q(client, sid)["question"]
        if q["type"] == "short_response":
            a = client.post(f"/api/questions/{q['id']}/answer", json={"response": {"text": "Some words"}, "confidence": "medium"}).json()
            assert a["verdict"] == "partial" and a["score"] == 40 and "Partly right" in a["feedback"]
        else:
            client.post(f"/api/questions/{q['id']}/answer", json={"response": wrong_answer(q["id"]), "confidence": "high"})
    res = client.post(f"/api/sessions/{sid}/finish").json()
    assert res["mastery"]["overall"]["score"] == 20
    assert len(res["missed"]) == 4
    assert any(m["confidently_wrong"] for m in res["missed"])
    weak = res["mastery"]["weak_subtopic_ids"]
    assert weak

    g = client.post(f"/api/sessions/{sid}/study-guide").json()
    assert g["status"] in ("generating", "ready")
    guide = wait_for(lambda: (lambda r: r if r["status"] == "ready" else None)(client.get(f"/api/sessions/{sid}/study-guide").json()))
    assert len(guide["content"]["sections"]) == len(weak)
    assert all(sec["status"] == "ready" for sec in guide["content"]["sections"])
    guide_calls = [c for c in fake_claude.calls if c["purpose"] == "study_guide"]
    guide_prompts = [c["params"]["messages"][0]["content"][-1]["text"] for c in guide_calls]
    assert any("Student's answer: Some words" in p and "Confuses A and B." in p for p in guide_prompts)

    sub_id = guide["content"]["sections"][0]["subtopic_id"]
    fixed = client.post(f"/api/sessions/{sid}/study-guide/repair-diagram", json={"subtopic_id": sub_id, "error": "Parse error"}).json()
    assert fixed["diagram"]["mermaid"].endswith("A-->C") and fixed["diagram"]["repaired"]
    assert client.post(f"/api/sessions/{sid}/study-guide/repair-diagram", json={"subtopic_id": sub_id, "error": "x"}).status_code == 409

    target = tmp_path / "guide.md"
    monkeypatch.setattr(desktop, "choose_save_path", lambda name, ft: target)
    out = client.post(f"/api/sessions/{sid}/study-guide/export/markdown").json()
    assert out["path"] == str(target)
    md = target.read_text(encoding="utf-8")
    assert "# Study Guide: Test Session" in md and "```mermaid" in md and "<details>" in md and "$$" in md

    rt = client.post(f"/api/sessions/{sid}/retest").json()
    assert rt["status"] == "generating" and rt["title"].startswith("Retest:")
    assert {st["name"] for st in rt["subtopics"]} == {r["name"] for r in res["mastery"]["subtopics"] if r["weak"]}
    before = fake_claude.purposes().count("topic_map")
    assert next_q(client, rt["id"])["state"] == "question"
    assert fake_claude.purposes().count("topic_map") == before  # retests reuse subtopics

    hist = client.get("/api/history").json()
    assert {h["id"] for h in hist} == {sid, rt["id"]}
    assert client.get("/api/subjects").json() == ["Thermo"]
    trend = client.get("/api/trends", params={"subject": "Thermo"}).json()
    assert trend["sessions"][0]["session_id"] == sid


def test_end_mode_hides_feedback_until_results(client, fake_claude):
    client.put("/api/settings", json={"feedback_mode": "end"})
    s = create(client, types=["short_response"], count=2)
    for _ in range(2):
        q = next_q(client, s["id"])["question"]
        a = client.post(f"/api/questions/{q['id']}/answer", json={"response": {"text": "x"}}).json()
        assert not a["revealed"] and "feedback" not in a
    res = client.post(f"/api/sessions/{s['id']}/finish").json()
    assert res["ungraded"] == []
    assert all(q["verdict"] == "partial" for q in res["questions"])


def test_adaptive_moves_difficulty_and_prefetches_candidates(client, fake_claude):
    s = create(client, types=["multiple_choice"], count=4, adaptive=True, difficulty=3)
    sid = s["id"]
    q1 = next_q(client, sid)["question"]
    assert q1["difficulty"] == 3
    # While q1 is on screen, the worker prefetches candidates for slot 1 at 2, 3, and 4.
    wait_for(lambda: len(db.query("SELECT 1 FROM questions WHERE session_id = ? AND slot = 1", (sid,))) == 3)
    client.post(f"/api/questions/{q1['id']}/answer", json={"response": correct_answer(q1["id"])})
    q2 = next_q(client, sid)["question"]
    assert q2["difficulty"] == 4
    discarded = db.query("SELECT difficulty FROM questions WHERE session_id = ? AND slot = 1 AND status = 'discarded'", (sid,))
    assert sorted(r["difficulty"] for r in discarded) == [2, 3]
    client.post(f"/api/questions/{q2['id']}/answer", json={"skipped": True, "response": {}})
    q3 = next_q(client, sid)["question"]
    assert q3["difficulty"] == 3
    gen_calls = [c for c in fake_claude.calls if c["purpose"] == "generate"]
    assert len(gen_calls) >= 3


def test_validation_retry_then_success(client, fake_claude):
    def bad(params):
        return {"questions": [sample("multiple_choice", slot=i, subtopic_id="x", correct_index=9) for i in range(5)]}
    fake_claude.queue("generate", bad)
    s = create(client, count=5)
    q = next_q(client, s["id"])
    assert q["state"] == "question"
    gen = [c for c in fake_claude.calls if c["purpose"] == "generate"]
    assert len(gen) == 2
    assert "rejected by the validator" in gen[1]["params"]["messages"][0]["content"][-1]["text"]


def test_auth_error_surfaces_and_retry_recovers(client, fake_claude):
    def boom(params):
        raise anthropic.AuthenticationError("bad key", response=httpx.Response(401, request=httpx.Request("POST", "https://x")), body=None)
    fake_claude.queue("topic_map", boom)
    s = create(client)
    r = next_q(client, s["id"])
    assert r["state"] == "error" and r["error"]["code"] == "invalid_key"
    assert "rejected" in r["error"]["message"]
    client.post(f"/api/sessions/{s['id']}/retry")
    assert next_q(client, s["id"])["state"] == "question"


def test_rate_limit_and_refusal_mapping(client, fake_claude):
    def limited(params):
        raise anthropic.RateLimitError("slow down", response=httpx.Response(429, headers={"retry-after": "30"}, request=httpx.Request("POST", "https://x")), body=None)
    fake_claude.queue("topic_map", limited)
    r = next_q(client, create(client)["id"])
    assert r["error"]["code"] == "rate_limited" and r["error"]["retry_after"] == 30 and r["error"]["retryable"]

    fake_claude.queue("topic_map", lambda p: FakeMessage(content=[FakeText("")], stop_reason="refusal"))
    r = next_q(client, create(client)["id"])
    assert r["error"]["code"] == "refusal"


def test_missing_key(client, monkeypatch):
    from sage import keystore
    monkeypatch.setattr(keystore, "get_api_key", lambda: (None, "none"))
    r = next_q(client, create(client)["id"])
    assert r["error"]["code"] == "missing_key"


def test_grading_error_can_be_retried(client, fake_claude):
    def boom(params):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
    s = create(client, types=["short_response"], count=1)
    q = next_q(client, s["id"])["question"]
    fake_claude.queue("grade", boom)
    a = client.post(f"/api/questions/{q['id']}/answer", json={"response": {"text": "x"}}).json()
    assert a["grade_status"] == "error" and a["grade_error"]["code"] == "network"
    a = client.post(f"/api/questions/{q['id']}/regrade").json()
    assert a["grade_status"] == "done" and a["verdict"] == "partial"


def test_answer_conflicts(client, fake_claude):
    s = create(client, count=1)
    q = next_q(client, s["id"])["question"]
    assert client.post(f"/api/questions/{q['id']}/answer", json={"response": {"choice": 0}}).status_code == 200
    assert client.post(f"/api/questions/{q['id']}/answer", json={"response": {"choice": 0}}).status_code == 409


def test_create_session_validation(client):
    assert client.post("/api/sessions", json={"types": []}).status_code == 400
    assert client.post("/api/sessions", json={"types": ["multiple_choice"], "material": ""}).status_code == 400
    assert client.post("/api/sessions", json={"types": ["multiple_choice"], "material": "x", "count": 500}).status_code == 400
    assert client.post("/api/sessions", json={"types": ["multiple_choice"], "material": "x", "upload_ids": ["nope"]}).status_code == 410


def test_delete_session_removes_files(client, fake_claude):
    up = upload_text(client)
    s = create(client, upload_ids=[up["id"]])
    next_q(client, s["id"])
    path = db.query_one("SELECT path FROM uploads WHERE id = ?", (up["id"],))["path"]
    assert client.delete(f"/api/sessions/{s['id']}").json() == {"ok": True}
    import os
    assert not os.path.exists(path)
    assert client.get(f"/api/sessions/{s['id']}").status_code == 404
