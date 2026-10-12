from collections import Counter

import pytest

from sage.services.mastery import (
    candidate_difficulties, compute_mastery, is_confidently_wrong, next_difficulty, plan_slots, subtopic_trends,
)

SUBS = [{"id": "a", "name": "Alpha"}, {"id": "b", "name": "Beta"}, {"id": "c", "name": "Gamma"}]


def item(sub, score, verdict=None, type_="multiple_choice", confidence=None, skipped=False):
    if verdict is None:
        verdict = "correct" if score >= 99.5 else "incorrect" if score <= 0.5 else "partial"
    return {"subtopic_id": sub, "type": type_, "score": score, "verdict": verdict, "confidence": confidence, "skipped": skipped}


def test_overall_and_per_subtopic_scores():
    m = compute_mastery([item("a", 100), item("a", 50), item("b", 100), item("b", 100)], SUBS)
    assert m["overall"]["score"] == 87.5
    rows = {r["id"]: r for r in m["subtopics"]}
    assert rows["a"]["score"] == 75 and rows["a"]["partial"] == 1
    assert rows["b"]["score"] == 100
    assert rows["c"]["score"] is None and rows["c"]["n"] == 0 and not rows["c"]["weak"]


def test_weak_below_threshold():
    m = compute_mastery([item("a", 60), item("a", 70), item("b", 70)], SUBS)
    rows = {r["id"]: r for r in m["subtopics"]}
    assert rows["a"]["weak"] and rows["a"]["weak_reasons"] == ["low_score"]
    assert not rows["b"]["weak"]  # exactly 70 is not below the threshold
    assert m["weak_subtopic_ids"] == ["a"]


def test_confidently_wrong_flags_otherwise_strong_subtopic():
    items = [item("a", 100)] * 4 + [item("a", 0, confidence="high")]
    m = compute_mastery(items, SUBS)
    row = m["subtopics"][0]
    assert row["score"] == 80
    assert row["weak"] and row["weak_reasons"] == ["confidently_wrong"]
    assert row["confidently_wrong"] == 1


def test_confidently_wrong_definition():
    assert is_confidently_wrong(item("a", 40, confidence="high"))
    assert not is_confidently_wrong(item("a", 40, confidence="medium"))
    assert not is_confidently_wrong(item("a", 60, confidence="high"))
    assert not is_confidently_wrong(item("a", 0, confidence="high", skipped=True))


def test_skips_count_as_misses_and_ungraded_are_ignored():
    pending = {"subtopic_id": "a", "type": "short_response", "score": None, "verdict": None, "confidence": None, "skipped": False}
    m = compute_mastery([item("a", 100), item("a", 0, skipped=True), pending], SUBS)
    row = m["subtopics"][0]
    assert row["n"] == 2 and row["score"] == 50 and row["skipped"] == 1 and row["incorrect"] == 1


def test_per_type_rows_in_canonical_order():
    m = compute_mastery([item("a", 100, type_="code"), item("a", 0, type_="multiple_choice")], SUBS)
    assert [t["type"] for t in m["types"]] == ["multiple_choice", "code"]
    assert m["types"][1]["label"] == "Code"


@pytest.mark.parametrize("current,verdict,skipped,expected", [
    (3, "correct", False, 4), (3, "incorrect", False, 2), (3, "partial", False, 3),
    (5, "correct", False, 5), (1, "incorrect", False, 1), (3, None, True, 2),
])
def test_next_difficulty(current, verdict, skipped, expected):
    assert next_difficulty(current, verdict, skipped) == expected


def test_candidate_difficulties():
    assert candidate_difficulties(3) == [2, 3, 4]
    assert candidate_difficulties(1) == [1, 2]
    assert candidate_difficulties(5) == [4, 5]


@pytest.mark.parametrize("count,n_subs,n_types", [(10, 3, 4), (5, 4, 1), (20, 5, 13), (7, 1, 3), (15, 6, 6)])
def test_plan_slots_is_balanced(count, n_subs, n_types):
    subs = [f"s{i}" for i in range(n_subs)]
    types = [f"t{i}" for i in range(n_types)]
    slots = plan_slots(count, subs, types, seed="x")
    assert len(slots) == count
    for key, pool in (("subtopic_id", subs), ("type", types)):
        counts = Counter(s[key] for s in slots)
        expected = [counts.get(p, 0) for p in pool]
        assert max(expected) - min(expected) <= 1


def test_plan_slots_deterministic_per_seed():
    assert plan_slots(10, ["a", "b"], ["x", "y", "z"], "seed") == plan_slots(10, ["a", "b"], ["x", "y", "z"], "seed")


def test_plan_slots_varies_pairings_when_counts_align():
    slots = plan_slots(12, ["a", "b"], ["x", "y"], seed="s")
    assert len({(s["subtopic_id"], s["type"]) for s in slots}) > 2


def test_trends_match_names_case_insensitively():
    sessions = [
        {"session_id": "1", "created_at": "2026-01-01", "score": 50, "subtopics": [{"name": "Entropy", "score": 40}, {"name": "Work", "score": None}]},
        {"session_id": "2", "created_at": "2026-01-05", "score": 80, "subtopics": [{"name": "entropy ", "score": 85}]},
    ]
    t = subtopic_trends(sessions)
    assert len(t) == 1
    assert t[0]["name"] == "Entropy" and [p["score"] for p in t[0]["points"]] == [40, 85]
    assert t[0]["change"] == 45 and t[0]["latest"] == 85
