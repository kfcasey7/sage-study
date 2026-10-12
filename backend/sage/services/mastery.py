"""Mastery calculation: per-subtopic and per-type scores, weak-area detection, adaptive steps,
question-slot planning, and cross-session trends."""
from __future__ import annotations

import random
from collections import defaultdict
from typing import Any, Iterable

from .. import config


def is_confidently_wrong(item: dict[str, Any]) -> bool:
    return (
        not item.get("skipped")
        and item.get("confidence") == "high"
        and (item.get("score") or 0) < config.CONFIDENTLY_WRONG_SCORE
    )


def _bucket() -> dict[str, Any]:
    return {"n": 0, "total": 0.0, "correct": 0, "partial": 0, "incorrect": 0, "skipped": 0, "confidently_wrong": 0}


def _add(bucket: dict[str, Any], item: dict[str, Any]) -> None:
    bucket["n"] += 1
    bucket["total"] += item.get("score") or 0.0
    if item.get("skipped"):
        bucket["skipped"] += 1
        bucket["incorrect"] += 1
    else:
        bucket[item.get("verdict") or "incorrect"] += 1
    if is_confidently_wrong(item):
        bucket["confidently_wrong"] += 1


def _finish(bucket: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in bucket.items() if k != "total"}
    out["score"] = round(bucket["total"] / bucket["n"], 1) if bucket["n"] else None
    return out


def compute_mastery(items: Iterable[dict[str, Any]], subtopics: list[dict[str, Any]]) -> dict[str, Any]:
    """items: graded answers with keys subtopic_id, type, score (0-100), verdict, confidence, skipped.
    Ungraded items (score None and not skipped) are ignored."""
    items = [i for i in items if i.get("skipped") or i.get("score") is not None]
    overall = _bucket()
    by_sub: dict[str, dict] = defaultdict(_bucket)
    by_type: dict[str, dict] = defaultdict(_bucket)
    for it in items:
        _add(overall, it)
        _add(by_sub[it["subtopic_id"]], it)
        _add(by_type[it["type"]], it)

    subtopic_rows = []
    for s in subtopics:
        b = _finish(by_sub[s["id"]]) if s["id"] in by_sub else _finish(_bucket())
        weak_reasons = []
        if b["score"] is not None and b["score"] < config.WEAK_THRESHOLD:
            weak_reasons.append("low_score")
        if b["confidently_wrong"]:
            weak_reasons.append("confidently_wrong")
        subtopic_rows.append({
            "id": s["id"], "name": s["name"], "description": s.get("description", ""),
            **b, "weak": bool(weak_reasons), "weak_reasons": weak_reasons,
        })

    type_rows = [
        {"type": t, "label": config.TYPE_LABELS.get(t, t), **_finish(b)}
        for t, b in sorted(by_type.items(), key=lambda kv: config.QUESTION_TYPE_IDS.index(kv[0]) if kv[0] in config.QUESTION_TYPE_IDS else 99)
    ]
    return {
        "overall": _finish(overall),
        "subtopics": subtopic_rows,
        "types": type_rows,
        "weak_subtopic_ids": [r["id"] for r in subtopic_rows if r["weak"]],
    }


def next_difficulty(current: int, verdict: str | None, skipped: bool = False) -> int:
    """Adaptive rule: up one after a correct answer, down one after a miss, unchanged after partial."""
    if skipped or verdict == "incorrect":
        step = -1
    elif verdict == "correct":
        step = 1
    else:
        step = 0
    return max(1, min(5, current + step))


def candidate_difficulties(current: int) -> list[int]:
    """Distinct difficulties the next adaptive question could need."""
    return sorted({next_difficulty(current, v) for v in ("correct", "partial", "incorrect")})


def plan_slots(count: int, subtopic_ids: list[str], types: list[str], seed: str) -> list[dict[str, str]]:
    """Spread `count` questions across subtopics and types as evenly as possible.

    Subtopics and types each cycle through a freshly shuffled order every round, so each one
    appears floor(count/n) or ceil(count/n) times and the subtopic/type pairings vary."""
    rng = random.Random(seed)

    def cycle(values: list[str], n: int) -> list[str]:
        out: list[str] = []
        while len(out) < n:
            block = list(values)
            rng.shuffle(block)
            out.extend(block)
        return out[:n]

    subs = cycle(subtopic_ids, count)
    kinds = cycle(types, count)
    return [{"subtopic_id": s, "type": t} for s, t in zip(subs, kinds)]


def subtopic_trends(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """sessions: chronological [{session_id, created_at, score, subtopics: [{name, score}]}].
    Returns one series per subtopic name (case-insensitive) across sessions."""
    series: dict[str, dict[str, Any]] = {}
    for s in sessions:
        for sub in s["subtopics"]:
            if sub.get("score") is None:
                continue
            key = sub["name"].strip().lower()
            entry = series.setdefault(key, {"name": sub["name"], "points": []})
            entry["points"].append({"session_id": s["session_id"], "date": s["created_at"], "score": sub["score"]})
    out = list(series.values())
    for e in out:
        pts = e["points"]
        e["latest"] = pts[-1]["score"]
        e["change"] = round(pts[-1]["score"] - pts[0]["score"], 1) if len(pts) > 1 else None
    return sorted(out, key=lambda e: e["name"].lower())
