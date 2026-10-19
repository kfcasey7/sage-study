"""Schema for the Material Breakdown of a Study Set."""
from __future__ import annotations

from typing import Callable, Literal

from pydantic import field_validator

from .. import config
from .guide import Formula, Strict
from .questions import DIFFICULTY, STR, arr, obj

BREAKDOWN_SCHEMA = obj({
    "title": STR,
    "overview": STR,
    "subtopics": arr(obj({
        "ref": STR,
        "change": {"type": "string", "enum": ["unchanged", "updated", "new"]},
        "name": STR,
        "summary": STR,
        "key_concepts": arr(STR),
        "formulas": arr(obj({"latex": STR, "description": STR})),
        "difficulty": DIFFICULTY,
        "sources": arr(STR),
    })),
    "map_mermaid": STR,
    "coverage_notes": arr(STR),
})


class BreakdownSubtopic(Strict):
    ref: str
    change: Literal["unchanged", "updated", "new"]
    name: str
    summary: str
    key_concepts: list[str]
    formulas: list[Formula]
    difficulty: int
    sources: list[str]

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("every subtopic needs a name")
        return v[:120]

    @field_validator("difficulty")
    @classmethod
    def _difficulty(cls, v: int) -> int:
        if not 1 <= v <= 5:
            raise ValueError("difficulty must be 1-5")
        return v


class Breakdown(Strict):
    title: str
    overview: str
    subtopics: list[BreakdownSubtopic]
    map_mermaid: str
    coverage_notes: list[str]

    @field_validator("subtopics")
    @classmethod
    def _count(cls, v: list[BreakdownSubtopic]) -> list[BreakdownSubtopic]:
        lo, hi = config.BREAKDOWN_MIN_SUBTOPICS, config.BREAKDOWN_MAX_SUBTOPICS
        if not lo <= len(v) <= hi:
            raise ValueError(f"produce between {lo} and {hi} subtopics")
        names = [s.name.lower() for s in v]
        if len(set(names)) != len(names):
            raise ValueError("subtopic names must be unique")
        return v


def make_validator(source_labels: set[str]) -> Callable[[dict], Breakdown]:
    """Validate a breakdown; source citations are normalised ("s2", "[S2]" -> "S2") and any that don't
    name a real source are dropped rather than failing the whole call."""
    def validate(data: dict) -> Breakdown:
        b = Breakdown.model_validate(data)
        if not b.overview.strip():
            raise ValueError("overview is empty")
        for s in b.subtopics:
            cleaned = []
            for ref in s.sources:
                label = ref.strip().strip("[]").upper()
                if label in source_labels and label not in cleaned:
                    cleaned.append(label)
            s.sources = cleaned
            s.key_concepts = [c.strip() for c in s.key_concepts if c.strip()][:12]
        b.coverage_notes = [n.strip() for n in b.coverage_notes if n.strip()]
        return b

    return validate
