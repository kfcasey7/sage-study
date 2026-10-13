"""Schemas for the topic map, Claude grading, and study guide sections."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from .questions import BOOL, INT, STR, arr, obj

NUM = {"type": "number"}

# --- Topic map ---------------------------------------------------------------

TOPIC_MAP_SCHEMA = obj({
    "title": STR,
    "summary": STR,
    "subtopics": arr(obj({"name": STR, "description": STR})),
})


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubtopicOut(Strict):
    name: str
    description: str


class TopicMap(Strict):
    title: str
    summary: str
    subtopics: list[SubtopicOut]

    @field_validator("subtopics")
    @classmethod
    def _count(cls, v: list[SubtopicOut]) -> list[SubtopicOut]:
        if not 2 <= len(v) <= 12:
            raise ValueError("produce between 2 and 12 subtopics")
        names = [s.name.strip().lower() for s in v]
        if len(set(names)) != len(names):
            raise ValueError("subtopic names must be unique")
        return v


# --- Grading -------------------------------------------------------------------

GRADE_SCHEMA = obj({
    "score": INT,
    "verdict": {"type": "string", "enum": ["correct", "partial", "incorrect"]},
    "feedback": STR,
    "model_answer": STR,
    "misconception": STR,
    "criteria_results": arr(obj({"criterion": STR, "awarded": INT, "max": INT, "comment": STR})),
})


class CriterionResult(Strict):
    criterion: str
    awarded: int
    max: int
    comment: str


class GradeOut(Strict):
    score: int
    verdict: Literal["correct", "partial", "incorrect"]
    feedback: str
    model_answer: str
    misconception: str
    criteria_results: list[CriterionResult]

    @field_validator("score")
    @classmethod
    def _range(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("score must be 0-100")
        return v

    @model_validator(mode="after")
    def _consistent(self):
        # Keep the verdict and score from contradicting each other.
        if self.verdict == "correct" and self.score < 70:
            raise ValueError("verdict 'correct' requires score >= 70")
        if self.verdict == "incorrect" and self.score > 50:
            raise ValueError("verdict 'incorrect' requires score <= 50")
        return self


# --- Study guide ---------------------------------------------------------------

STUDY_SECTION_SCHEMA = obj({
    "title": STR,
    "explanation": STR,
    "key_formulas": arr(obj({"latex": STR, "description": STR})),
    "diagram": obj({
        "include": BOOL,
        "kind": {"type": "string", "enum": ["flowchart", "concept_map", "sequence", "state", "class", "timeline", "other"]},
        "mermaid": STR,
        "caption": STR,
    }),
    "chart": obj({
        "include": BOOL,
        "chart_type": {"type": "string", "enum": ["line", "bar", "scatter", "area"]},
        "title": STR,
        "x_label": STR,
        "y_label": STR,
        "series": arr(obj({"name": STR, "points": arr(obj({"label": STR, "x": NUM, "y": NUM}))})),
        "caption": STR,
    }),
    "worked_example": obj({"problem": STR, "steps": arr(STR), "answer": STR}),
    "common_mistakes": arr(obj({"mistake": STR, "why": STR, "fix": STR, "from_your_answers": BOOL})),
    "practice_questions": arr(obj({"question": STR, "answer": STR})),
})


class Formula(Strict):
    latex: str
    description: str


class Diagram(Strict):
    include: bool
    kind: str
    mermaid: str
    caption: str


class Point(Strict):
    label: str
    x: float
    y: float


class Series(Strict):
    name: str
    points: list[Point]


class Chart(Strict):
    include: bool
    chart_type: Literal["line", "bar", "scatter", "area"]
    title: str
    x_label: str
    y_label: str
    series: list[Series]
    caption: str


class WorkedExample(Strict):
    problem: str
    steps: list[str]
    answer: str


class Mistake(Strict):
    mistake: str
    why: str
    fix: str
    from_your_answers: bool


class Practice(Strict):
    question: str
    answer: str


class StudySection(Strict):
    title: str
    explanation: str
    key_formulas: list[Formula]
    diagram: Diagram
    chart: Chart
    worked_example: WorkedExample
    common_mistakes: list[Mistake]
    practice_questions: list[Practice]

    @model_validator(mode="after")
    def _check(self):
        has_diagram = self.diagram.include and self.diagram.mermaid.strip()
        has_chart = self.chart.include and any(s.points for s in self.chart.series)
        if not (has_diagram or has_chart):
            raise ValueError("include at least one graphic: a Mermaid diagram or a chart with data")
        if not 2 <= len(self.practice_questions) <= 4:
            raise ValueError("include 2-3 practice questions")
        if not self.common_mistakes:
            raise ValueError("include at least one common mistake")
        if not self.worked_example.steps:
            raise ValueError("worked example needs steps")
        return self


DIAGRAM_REPAIR_SCHEMA = obj({"mermaid": STR})


class DiagramRepair(Strict):
    mermaid: str


# --- "Ask Claude" chat ------------------------------------------------------------

CHAT_SCHEMA = obj({"reply": STR})


class ChatOut(Strict):
    reply: str

    @field_validator("reply")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("reply must not be empty")
        return v.strip()
