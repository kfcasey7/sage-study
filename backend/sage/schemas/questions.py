"""Question schemas.

Two views of the same data:
  * JSON Schema (``generation_schema``) sent to Claude via structured outputs. Hand-written so it
    stays within the supported subset: every object has ``additionalProperties: false`` and lists
    all properties as required; no numeric/length constraints.
  * Pydantic models used to validate what comes back, including the constraints JSON Schema can't
    express here (difficulty 1-5, answer indices in range, enough options, ...).
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

BLANK_TOKEN = "{{blank}}"
BLANK_RE = re.compile(r"\{\{\s*blank\s*\}\}")


# --- JSON Schema helpers ---------------------------------------------------------

def obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def arr(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


STR = {"type": "string"}
INT = {"type": "integer"}
BOOL = {"type": "boolean"}
DIFFICULTY = {"type": "integer", "enum": [1, 2, 3, 4, 5]}

RUBRIC_SCHEMA = obj({
    "criteria": arr(obj({"criterion": STR, "points": INT})),
    "model_answer": STR,
})


def _base_props(type_id: str) -> dict[str, Any]:
    return {
        "type": {"type": "string", "const": type_id},
        "slot": INT,
        "subtopic_id": STR,
        "difficulty": DIFFICULTY,
        "prompt": STR,
        "uses_outside_knowledge": BOOL,
        "source_hint": STR,
        "explanation": STR,
    }


TYPE_EXTRA_PROPS: dict[str, dict[str, Any]] = {
    "multiple_choice": {"options": arr(STR), "correct_index": INT},
    "select_all": {"options": arr(STR), "correct_indices": arr(INT)},
    "true_false": {"correct": BOOL},
    "fill_blank": {"blanks": arr(obj({"accepted_answers": arr(STR)}))},
    "matching": {"pairs": arr(obj({"left": STR, "right": STR})), "distractors": arr(STR)},
    "ordering": {"items": arr(STR)},
    "short_response": {"rubric": RUBRIC_SCHEMA},
    "long_response": {"rubric": RUBRIC_SCHEMA},
    "free_response": {"rubric": RUBRIC_SCHEMA},
    "math": {"final_answer": STR, "rubric": RUBRIC_SCHEMA},
    "code": {"language": STR, "starter_code": STR, "rubric": RUBRIC_SCHEMA},
    "error_analysis": {"language": STR, "flawed_work": STR, "rubric": RUBRIC_SCHEMA},
    "applied_scenario": {"scenario": STR, "rubric": RUBRIC_SCHEMA},
}


def question_json_schema(type_id: str) -> dict[str, Any]:
    return obj({**_base_props(type_id), **TYPE_EXTRA_PROPS[type_id]})


def generation_schema(types: list[str] | None = None) -> dict[str, Any]:
    """Schema for a batch of questions, limited to the requested types (all 13 by default)."""
    wanted = [t for t in TYPE_EXTRA_PROPS if types is None or t in types]
    item = question_json_schema(wanted[0]) if len(wanted) == 1 else {"anyOf": [question_json_schema(t) for t in wanted]}
    return obj({"questions": arr(item)})


# --- Pydantic models -------------------------------------------------------------

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Criterion(Strict):
    criterion: str
    points: int

    @field_validator("points")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("criterion points must be positive")
        return v


class Rubric(Strict):
    criteria: list[Criterion]
    model_answer: str

    @field_validator("criteria")
    @classmethod
    def _non_empty(cls, v: list[Criterion]) -> list[Criterion]:
        if not v:
            raise ValueError("rubric needs at least one criterion")
        return v

    @field_validator("model_answer")
    @classmethod
    def _has_answer(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("rubric model_answer is empty")
        return v


class QuestionBase(Strict):
    slot: int
    subtopic_id: str
    difficulty: int
    prompt: str
    uses_outside_knowledge: bool
    source_hint: str
    explanation: str

    @field_validator("difficulty")
    @classmethod
    def _difficulty(cls, v: int) -> int:
        if not 1 <= v <= 5:
            raise ValueError("difficulty must be 1-5")
        return v

    @field_validator("prompt")
    @classmethod
    def _prompt(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("prompt is empty")
        return v


def _check_options(options: list[str], minimum: int = 2) -> list[str]:
    if len(options) < minimum:
        raise ValueError(f"need at least {minimum} options")
    if any(not o.strip() for o in options):
        raise ValueError("options must not be blank")
    if len({o.strip().lower() for o in options}) != len(options):
        raise ValueError("options must be distinct")
    return options


class MultipleChoice(QuestionBase):
    type: Literal["multiple_choice"]
    options: list[str]
    correct_index: int

    @model_validator(mode="after")
    def _check(self):
        _check_options(self.options, 3)
        if not 0 <= self.correct_index < len(self.options):
            raise ValueError("correct_index out of range")
        return self


class SelectAll(QuestionBase):
    type: Literal["select_all"]
    options: list[str]
    correct_indices: list[int]

    @model_validator(mode="after")
    def _check(self):
        _check_options(self.options, 3)
        if not self.correct_indices:
            raise ValueError("select_all needs at least one correct option")
        if len(set(self.correct_indices)) != len(self.correct_indices):
            raise ValueError("duplicate correct_indices")
        if any(not 0 <= i < len(self.options) for i in self.correct_indices):
            raise ValueError("correct_indices out of range")
        return self


class TrueFalse(QuestionBase):
    type: Literal["true_false"]
    correct: bool


class Blank(Strict):
    accepted_answers: list[str]

    @field_validator("accepted_answers")
    @classmethod
    def _non_empty(cls, v: list[str]) -> list[str]:
        v = [a for a in v if a.strip()]
        if not v:
            raise ValueError("each blank needs at least one accepted answer")
        return v


class FillBlank(QuestionBase):
    type: Literal["fill_blank"]
    blanks: list[Blank]

    @model_validator(mode="after")
    def _check(self):
        n = len(BLANK_RE.findall(self.prompt))
        if n == 0:
            raise ValueError(f"fill_blank prompt must contain {BLANK_TOKEN}")
        if n != len(self.blanks):
            raise ValueError(f"prompt has {n} blanks but {len(self.blanks)} answers were given")
        return self


class Pair(Strict):
    left: str
    right: str


class Matching(QuestionBase):
    type: Literal["matching"]
    pairs: list[Pair]
    distractors: list[str]

    @model_validator(mode="after")
    def _check(self):
        if len(self.pairs) < 3:
            raise ValueError("matching needs at least 3 pairs")
        _check_options([p.left for p in self.pairs], 3)
        _check_options([p.right for p in self.pairs] + self.distractors, 3)
        return self


class Ordering(QuestionBase):
    type: Literal["ordering"]
    items: list[str]

    @model_validator(mode="after")
    def _check(self):
        _check_options(self.items, 3)
        return self


class RubricQuestion(QuestionBase):
    rubric: Rubric


class ShortResponse(RubricQuestion):
    type: Literal["short_response"]


class LongResponse(RubricQuestion):
    type: Literal["long_response"]


class FreeResponse(RubricQuestion):
    type: Literal["free_response"]


class MathQuestion(RubricQuestion):
    type: Literal["math"]
    final_answer: str


class CodeQuestion(RubricQuestion):
    type: Literal["code"]
    language: str
    starter_code: str


class ErrorAnalysis(RubricQuestion):
    type: Literal["error_analysis"]
    language: str
    flawed_work: str

    @field_validator("flawed_work")
    @classmethod
    def _has_work(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("error_analysis needs flawed_work")
        return v


class AppliedScenario(RubricQuestion):
    type: Literal["applied_scenario"]
    scenario: str


Question = Annotated[
    Union[
        MultipleChoice, SelectAll, TrueFalse, FillBlank, Matching, Ordering,
        ShortResponse, LongResponse, FreeResponse, MathQuestion, CodeQuestion,
        ErrorAnalysis, AppliedScenario,
    ],
    Field(discriminator="type"),
]
QuestionAdapter: TypeAdapter[Any] = TypeAdapter(Question)


def parse_question(data: dict[str, Any]):
    return QuestionAdapter.validate_python(data)


# --- Answer payloads from the UI -------------------------------------------------

class AnswerSubmission(BaseModel):
    response: dict[str, Any] = Field(default_factory=dict)
    confidence: Literal["low", "medium", "high"] | None = None
    skipped: bool = False
