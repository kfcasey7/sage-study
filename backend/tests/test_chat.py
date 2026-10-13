"""'Ask Claude' chat about the question on screen."""
from __future__ import annotations

from sage import db
from sage.errors import AppError

from .test_api import correct_answer, create, next_q


def ask(client, q, message):
    return client.post(f"/api/questions/{q['id']}/chat", json={"message": message})


def test_chat_before_answering_is_a_tutor_that_keeps_the_answer_back(client, fake_claude):
    s = create(client, types=["multiple_choice"], count=2)
    q = next_q(client, s["id"])["question"]
    assert client.get(f"/api/questions/{q['id']}/chat").json() == {"question_id": q["id"], "mode": "unanswered", "messages": []}

    r = ask(client, q, "What does this term mean?")
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["mode"] == "unanswered"
    assert [(m["role"], m["content"]) for m in view["messages"]] == [("user", "What does this term mean?"), ("assistant", "Here's a hint.")]

    prompt = fake_claude.calls[-1]["req"].prompt
    assert "has NOT answered" in prompt and "Do NOT state or confirm the correct answer" in prompt
    assert "<answer_key>" in prompt and "<student_result>" not in prompt
    assert fake_claude.calls[-1]["req"].model == "sonnet"
    assert db.query_one("SELECT purpose FROM ai_calls ORDER BY id DESC LIMIT 1")["purpose"] == "chat"


def test_chat_sends_earlier_turns(client, fake_claude):
    s = create(client, types=["true_false"], count=2)
    q = next_q(client, s["id"])["question"]
    ask(client, q, "first question")
    fake_claude.queue("chat", lambda req: {"reply": "second reply"})
    view = ask(client, q, "follow-up").json()
    assert len(view["messages"]) == 4 and view["messages"][-1]["content"] == "second reply"
    prompt = fake_claude.calls[-1]["req"].prompt
    assert "<student>first question</student>" in prompt and "<tutor>Here's a hint.</tutor>" in prompt
    assert "<student_message>\nfollow-up\n</student_message>" in prompt


def test_chat_after_answer_is_revealed_discusses_the_result(client, fake_claude):
    s = create(client, types=["multiple_choice"], count=2)
    q = next_q(client, s["id"])["question"]
    client.post(f"/api/questions/{q['id']}/answer", json={"response": correct_answer(q["id"])})
    view = ask(client, q, "Why is that right?").json()
    assert view["mode"] == "revealed"
    prompt = fake_claude.calls[-1]["req"].prompt
    assert "<student_result>" in prompt and "Score: 100/100 (correct)" in prompt and "discuss everything" in prompt


def test_chat_keeps_answer_hidden_when_feedback_is_at_the_end(client, fake_claude):
    s = create(client, types=["true_false"], count=2)
    client.put(f"/api/sessions/{s['id']}/options", json={
        "types": ["true_false"], "difficulty": 3, "adaptive": False, "count": 2, "language": "Python", "feedback_mode": "end",
    })
    q = next_q(client, s["id"])["question"]
    client.post(f"/api/questions/{q['id']}/answer", json={"response": correct_answer(q["id"])})
    assert client.get(f"/api/questions/{q['id']}/chat").json()["mode"] == "answered_hidden"
    ask(client, q, "Was I right?")
    prompt = fake_claude.calls[-1]["req"].prompt
    assert "hasn't seen the result" in prompt and "<student_result>" not in prompt


def test_failed_reply_saves_nothing(client, fake_claude):
    s = create(client, types=["true_false"], count=2)
    q = next_q(client, s["id"])["question"]

    def boom(req):
        raise AppError("usage_limit", "Claude usage limit reached.")
    fake_claude.queue("chat", boom)
    r = ask(client, q, "hello?")
    assert r.status_code == 429 and r.json()["error"]["code"] == "usage_limit"
    assert client.get(f"/api/questions/{q['id']}/chat").json()["messages"] == []


def test_chat_validation_and_cleanup(client, fake_claude):
    s = create(client, types=["true_false"], count=2)
    q = next_q(client, s["id"])["question"]
    assert ask(client, q, "   ").status_code == 400
    assert ask(client, q, "x" * 5000).status_code == 400
    assert client.post("/api/questions/nope/chat", json={"message": "hi"}).status_code == 404
    ask(client, q, "hi")
    client.delete(f"/api/sessions/{s['id']}")
    assert db.query("SELECT * FROM question_chats") == []
