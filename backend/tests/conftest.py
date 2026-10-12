"""Test fixtures: isolated data dir, a fake API key, and a fake Claude that returns schema-valid
responses (so the full session flow runs without network access or cost)."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from sage import claude_client, config, db, keystore
from sage.services import sessions as S

from .samples import sample

SLOT_RE = re.compile(r'slot (\d+): type "(\w+)", subtopic_id "(\w+)", difficulty (\d)')


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    db.init_db()
    S._prefix_cache.clear()
    yield tmp_path


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setattr(keystore, "get_api_key", lambda: ("sk-ant-test-key-123456", "env"))


@dataclass
class FakeUsage:
    input_tokens: int = 50
    output_tokens: int = 400
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation: Any = None


@dataclass
class FakeText:
    text: str
    type: str = "text"


@dataclass
class FakeMessage:
    content: list
    model: str = "claude-sonnet-5-5"
    stop_reason: str = "end_turn"
    usage: FakeUsage = field(default_factory=FakeUsage)


def purpose_of(params: dict) -> str:
    props = params["output_config"]["format"]["schema"]["properties"]
    if "questions" in props:
        return "generate"
    if "subtopics" in props:
        return "topic_map"
    if "verdict" in props:
        return "grade"
    if "worked_example" in props:
        return "study_guide"
    if "mermaid" in props:
        return "repair"
    raise AssertionError(f"unknown schema {list(props)}")


def instruction_of(params: dict) -> str:
    return params["messages"][0]["content"][-1]["text"]


def default_response(purpose: str, params: dict) -> dict:
    if purpose == "topic_map":
        return {"title": "Test Session", "summary": "About tests.", "subtopics": [
            {"name": "Alpha", "description": "First"}, {"name": "Beta", "description": "Second"},
        ]}
    if purpose == "generate":
        qs = []
        for slot, type_id, sub, diff in SLOT_RE.findall(instruction_of(params)):
            qs.append(sample(type_id, slot=int(slot), subtopic_id=sub, difficulty=int(diff),
                             prompt=f"Q slot {slot} {type_id} d{diff}" + (" {{blank}} {{blank}}" if type_id == "fill_blank" else "")))
        return {"questions": qs}
    if purpose == "grade":
        return {"score": 40, "verdict": "partial", "feedback": "Partly right.", "model_answer": "Model.",
                "misconception": "Confuses A and B.", "criteria_results": [{"criterion": "c", "awarded": 1, "max": 2, "comment": "ok"}]}
    if purpose == "study_guide":
        return {
            "title": "Section", "explanation": "Explained.",
            "key_formulas": [{"latex": "a^2+b^2=c^2", "description": "Pythagoras"}],
            "diagram": {"include": True, "kind": "flowchart", "mermaid": "flowchart TD\nA-->B", "caption": "Flow"},
            "chart": {"include": False, "chart_type": "line", "title": "", "x_label": "", "y_label": "", "series": [], "caption": ""},
            "worked_example": {"problem": "P", "steps": ["one", "two"], "answer": "A"},
            "common_mistakes": [{"mistake": "M", "why": "W", "fix": "F", "from_your_answers": True}],
            "practice_questions": [{"question": "q1", "answer": "a1"}, {"question": "q2", "answer": "a2"}],
        }
    if purpose == "repair":
        return {"mermaid": "flowchart TD\nA-->C"}
    raise AssertionError(purpose)


class FakeClaude:
    def __init__(self):
        self.calls: list[dict] = []
        self.overrides: dict[str, list[Callable[[dict], Any]]] = {}

    def queue(self, purpose: str, fn: Callable[[dict], Any]) -> None:
        """Queue a one-shot response (a dict to return, or raise an exception) for the next call."""
        self.overrides.setdefault(purpose, []).append(fn)

    async def send(self, params: dict) -> FakeMessage:
        purpose = purpose_of(params)
        self.calls.append({"purpose": purpose, "params": params})
        queued = self.overrides.get(purpose)
        result = queued.pop(0)(params) if queued else default_response(purpose, params)
        if isinstance(result, FakeMessage):
            return result
        reads = 1000 if len(self.calls) > 1 else 0
        usage = FakeUsage(cache_read_input_tokens=reads, cache_creation_input_tokens=0 if reads else 1000)
        return FakeMessage(content=[FakeText(json.dumps(result))], usage=usage, model=params["model"])

    def purposes(self) -> list[str]:
        return [c["purpose"] for c in self.calls]


@pytest.fixture
def fake_claude(monkeypatch, api_key):
    fake = FakeClaude()
    monkeypatch.setattr(claude_client, "_send", fake.send)
    return fake


@pytest.fixture
def client(fake_claude):
    from sage.app import create_app

    with TestClient(create_app(), base_url="http://127.0.0.1:8765", headers={"x-sage-client": "1"}) as c:
        yield c


def wait_for(fn: Callable[[], Any], timeout: float = 10.0, interval: float = 0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(interval)
    raise AssertionError("timed out waiting for condition")
