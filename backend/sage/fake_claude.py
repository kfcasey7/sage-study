"""A fake Claude that returns schema-valid canned responses. Used by the test suite, and by
`SAGE_FAKE_CLAUDE=1 python -m sage.dev` to click through the UI without an API key or cost."""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

SLOT_RE = re.compile(r'slot (\d+): type "(\w+)", subtopic_id "(\w+)", difficulty (\d)')

RUBRIC = {
    "criteria": [
        {"criterion": "States the key idea", "points": 2},
        {"criterion": "Supports it with a correct example", "points": 2},
    ],
    "model_answer": "A model answer.",
}


def _base(type_id: str) -> dict:
    return {
        "type": type_id, "slot": 0, "subtopic_id": "s1", "difficulty": 3,
        "prompt": f"Prompt for {type_id}", "uses_outside_knowledge": False,
        "source_hint": "Section 1", "explanation": "Because of reasons.",
    }


SAMPLES: dict[str, dict] = {
    "multiple_choice": {**_base("multiple_choice"), "options": ["A", "B", "C", "D"], "correct_index": 2},
    "select_all": {**_base("select_all"), "options": ["A", "B", "C", "D"], "correct_indices": [0, 3]},
    "true_false": {**_base("true_false"), "correct": True},
    "fill_blank": {
        **_base("fill_blank"),
        "prompt": "Water boils at {{blank}} degrees Celsius at {{blank}} pressure.",
        "blanks": [{"accepted_answers": ["100"]}, {"accepted_answers": ["atmospheric", "standard"]}],
    },
    "matching": {
        **_base("matching"),
        "pairs": [{"left": "H2O", "right": "Water"}, {"left": "NaCl", "right": "Salt"}, {"left": "CO2", "right": "Carbon dioxide"}],
        "distractors": ["Ammonia"],
    },
    "ordering": {**_base("ordering"), "items": ["First", "Second", "Third", "Fourth"]},
    "short_response": {**_base("short_response"), "rubric": RUBRIC},
    "long_response": {**_base("long_response"), "rubric": RUBRIC},
    "free_response": {**_base("free_response"), "rubric": RUBRIC},
    "math": {**_base("math"), "final_answer": "x = 2", "rubric": RUBRIC},
    "code": {**_base("code"), "language": "Python", "starter_code": "def f(x):\n    pass\n", "rubric": RUBRIC},
    "error_analysis": {**_base("error_analysis"), "language": "Python", "flawed_work": "def add(a, b):\n    return a - b\n", "rubric": RUBRIC},
    "applied_scenario": {**_base("applied_scenario"), "scenario": "A bridge engineer...", "rubric": RUBRIC},
}

# Richer prompts for demo mode, so every input renders realistically.
DEMO_OVERRIDES: dict[str, dict] = {
    "multiple_choice": {"prompt": "For an ideal gas undergoing an **isothermal** process, which quantity is zero?",
                        "options": ["Work done $W$", "Heat transfer $Q$", "Change in internal energy $\\Delta U$", "Change in entropy $\\Delta S$"]},
    "select_all": {"prompt": "Which of the following are **state functions**? Select all that apply.",
                   "options": ["Internal energy $U$", "Heat $Q$", "Work $W$", "Enthalpy $H$"]},
    "true_false": {"prompt": "The first law of thermodynamics states that $\\Delta U = Q - W$ for a closed system (with $W$ done *by* the system)."},
    "matching": {"prompt": "Match each process to the quantity held constant.",
                 "pairs": [{"left": "Isothermal", "right": "Temperature"}, {"left": "Isobaric", "right": "Pressure"}, {"left": "Isochoric", "right": "Volume"}],
                 "distractors": ["Entropy"]},
    "ordering": {"prompt": "Order the strokes of an ideal Otto cycle, starting from intake.",
                 "items": ["Intake", "Adiabatic compression", "Constant-volume heat addition", "Adiabatic expansion (power)"]},
    "math": {"prompt": "A gas expands isothermally at $T = 300\\,\\text{K}$ from $V_1 = 1\\,\\text{L}$ to $V_2 = 2\\,\\text{L}$ ($n = 1$ mol). Find the work done by the gas.",
             "final_answer": "W \\approx 1729\\,\\text{J}"},
    "code": {"prompt": "Write a function `celsius_to_kelvin(c)` that returns the temperature in kelvin, raising `ValueError` below absolute zero.",
             "starter_code": "def celsius_to_kelvin(c):\n    # your code here\n    pass\n"},
    "error_analysis": {"prompt": "This function should add two numbers. Find and fix the bug."},
    "applied_scenario": {"prompt": "Estimate the heat the radiator must reject, and justify your assumptions.",
                         "scenario": "A car engine produces **60 kW** of shaft power at **30 %** thermal efficiency."},
    "short_response": {"prompt": "In one or two sentences, explain why heat is a *path* function."},
    "long_response": {"prompt": "Compare the Carnot and Otto cycles. Discuss efficiency limits and practical constraints."},
    "free_response": {"prompt": "Explain, in your own words, what entropy measures."},
}


def sample(type_id: str, **overrides) -> dict:
    q = copy.deepcopy(SAMPLES[type_id])
    q.update(overrides)
    return q


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


def default_response(purpose: str, params: dict, demo: bool = False) -> dict:
    if purpose == "topic_map":
        return {"title": "Test Session", "summary": "About tests.", "subtopics": [
            {"name": "Alpha", "description": "First"}, {"name": "Beta", "description": "Second"},
        ]}
    if purpose == "generate":
        qs = []
        for slot, type_id, sub, diff in SLOT_RE.findall(instruction_of(params)):
            prompt = f"Q slot {slot} {type_id} d{diff}" + (" {{blank}} {{blank}}" if type_id == "fill_blank" else "")
            q = sample(type_id, slot=int(slot), subtopic_id=sub, difficulty=int(diff), prompt=prompt)
            if demo and type_id in DEMO_OVERRIDES:
                q.update(DEMO_OVERRIDES[type_id])
            qs.append(q)
        return {"questions": qs}
    if purpose == "grade":
        return {"score": 40, "verdict": "partial", "feedback": "Partly right.", "model_answer": "Model.",
                "misconception": "Confuses A and B.", "criteria_results": [{"criterion": "c", "awarded": 1, "max": 2, "comment": "ok"}]}
    if purpose == "study_guide":
        return {
            "title": "Section", "explanation": "Explained.",
            "key_formulas": [{"latex": "a^2+b^2=c^2", "description": "Pythagoras"}],
            "diagram": {"include": True, "kind": "flowchart", "mermaid": "flowchart TD\nA-->B", "caption": "Flow"},
            "chart": {"include": True, "chart_type": "line", "title": "y = x²", "x_label": "x", "y_label": "y",
                      "series": [{"name": "y", "points": [{"label": "", "x": x, "y": x * x} for x in range(-5, 6)]}], "caption": "A parabola"},
            "worked_example": {"problem": "P", "steps": ["one", "two"], "answer": "A"},
            "common_mistakes": [{"mistake": "M", "why": "W", "fix": "F", "from_your_answers": True}],
            "practice_questions": [{"question": "q1", "answer": "a1"}, {"question": "q2", "answer": "a2"}],
        }
    if purpose == "repair":
        return {"mermaid": "flowchart TD\nA-->C"}
    raise AssertionError(purpose)


class FakeClaude:
    def __init__(self, demo: bool = False):
        self.demo = demo
        self.calls: list[dict] = []
        self.overrides: dict[str, list[Callable[[dict], Any]]] = {}

    def queue(self, purpose: str, fn: Callable[[dict], Any]) -> None:
        """Queue a one-shot response (a dict to return, or raise an exception) for the next call."""
        self.overrides.setdefault(purpose, []).append(fn)

    async def send(self, params: dict) -> FakeMessage:
        purpose = purpose_of(params)
        self.calls.append({"purpose": purpose, "params": params})
        queued = self.overrides.get(purpose)
        result = queued.pop(0)(params) if queued else default_response(purpose, params, self.demo)
        if isinstance(result, FakeMessage):
            return result
        if self.demo:
            import asyncio
            await asyncio.sleep(1.5)  # make loading states visible
        reads = 1000 if len(self.calls) > 1 else 0
        usage = FakeUsage(cache_read_input_tokens=reads, cache_creation_input_tokens=0 if reads else 1000)
        return FakeMessage(content=[FakeText(json.dumps(result))], usage=usage, model=params["model"])

    def purposes(self) -> list[str]:
        return [c["purpose"] for c in self.calls]


def install_demo() -> FakeClaude:
    """Patch the client so every call is answered by the fake (dev demo mode)."""
    from . import claude_client, keystore

    fake = FakeClaude(demo=True)
    claude_client._send = fake.send  # type: ignore[assignment]
    keystore.get_api_key = lambda: ("sk-ant-demo-mode-0000", "env")  # type: ignore[assignment]
    return fake
