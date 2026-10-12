"""Valid example questions for every type (as Claude would return them), shared by tests."""
from __future__ import annotations

import copy

RUBRIC = {
    "criteria": [
        {"criterion": "States the key idea", "points": 2},
        {"criterion": "Supports it with a correct example", "points": 2},
    ],
    "model_answer": "A model answer.",
}


def _base(type_id: str, slot: int = 0, subtopic_id: str = "s1", difficulty: int = 3) -> dict:
    return {
        "type": type_id,
        "slot": slot,
        "subtopic_id": subtopic_id,
        "difficulty": difficulty,
        "prompt": f"Prompt for {type_id}",
        "uses_outside_knowledge": False,
        "source_hint": "Section 1",
        "explanation": "Because of reasons.",
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


def sample(type_id: str, **overrides) -> dict:
    q = copy.deepcopy(SAMPLES[type_id])
    q.update(overrides)
    return q
