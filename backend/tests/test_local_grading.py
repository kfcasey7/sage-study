import pytest

from sage.services.grading_local import blank_matches, grade_local, lcs_length, normalize, skipped_result, verdict_for
from sage.services.presentation import build_display, correct_answer_text, user_answer_text

from .samples import sample


def display_for(q):
    return build_display("qid-test", q, "Subtopic")


def grade(q, response):
    return grade_local(q, display_for(q), response)


def test_multiple_choice():
    q = sample("multiple_choice")
    assert grade(q, {"choice": 2})["verdict"] == "correct"
    r = grade(q, {"choice": 0})
    assert (r["score"], r["verdict"]) == (0, "incorrect")
    assert grade(q, {})["verdict"] == "incorrect"
    assert r["model_answer"] == "C"


def test_true_false_requires_exact_bool():
    q = sample("true_false", correct=False)
    assert grade(q, {"value": False})["score"] == 100
    assert grade(q, {"value": True})["score"] == 0
    assert grade(q, {"value": 0})["score"] == 0  # falsy but not False
    assert grade(q, {})["score"] == 0


@pytest.mark.parametrize("choices,score,verdict", [
    ([0, 3], 100, "correct"),
    ([0], 50, "partial"),
    ([0, 3, 1], 50, "partial"),     # one wrong pick cancels one right pick
    ([0, 1], 0, "incorrect"),
    ([1, 2], 0, "incorrect"),       # floored at zero
    ([], 0, "incorrect"),
    ([0, 1, 2, 3], 0, "incorrect"),  # selecting everything earns nothing
])
def test_select_all_partial_credit(choices, score, verdict):
    r = grade(sample("select_all"), {"choices": choices})
    assert (r["score"], r["verdict"]) == (score, verdict)


def test_matching_uses_displayed_right_column():
    q = sample("matching")
    d = display_for(q)
    idx = {text: i for i, text in enumerate(d["right"])}
    perfect = [idx["Water"], idx["Salt"], idx["Carbon dioxide"]]
    assert grade_local(q, d, {"matches": perfect})["score"] == 100
    two = [idx["Water"], idx["Salt"], idx["Ammonia"]]
    r = grade_local(q, d, {"matches": two})
    assert r["verdict"] == "partial" and r["score"] == pytest.approx(66.7)
    assert grade_local(q, d, {"matches": [None, None, None]})["score"] == 0
    assert grade_local(q, d, {"matches": [99, -1]})["score"] == 0


def test_ordering():
    q = sample("ordering")
    assert grade(q, {"order": [0, 1, 2, 3]})["verdict"] == "correct"
    one_off = grade(q, {"order": [1, 0, 2, 3]})
    assert one_off["verdict"] == "partial" and one_off["score"] == 75
    reversed_ = grade(q, {"order": [3, 2, 1, 0]})
    assert reversed_["score"] == 25
    assert grade(q, {"order": [0, 1]})["score"] == 0  # incomplete answer


def test_ordering_partial_is_capped_below_full_credit():
    q = sample("ordering", items=[str(i) for i in range(12)])
    order = list(range(12))
    order[10], order[11] = order[11], order[10]
    r = grade(q, {"order": order})
    assert r["verdict"] == "partial" and r["score"] <= 90


def test_ordering_display_is_shuffled_but_complete():
    q = sample("ordering")
    d = display_for(q)
    ids = [it["id"] for it in d["items"]]
    assert sorted(ids) == [0, 1, 2, 3] and ids != [0, 1, 2, 3]


def test_fill_blank_exact_and_numeric():
    q = sample("fill_blank")
    assert grade(q, {"blanks": ["100", "Atmospheric"]})["verdict"] == "correct"
    assert grade(q, {"blanks": ["100.0", " standard. "]})["verdict"] == "correct"
    assert grade(q, {"blanks": ["1e2", "the standard"]})["verdict"] == "correct"


def test_fill_blank_defers_to_claude_on_unmatched_answers():
    q = sample("fill_blank")
    assert grade(q, {"blanks": ["100", "sea-level"]}) is None


def test_fill_blank_empty_answers_graded_locally():
    q = sample("fill_blank")
    r = grade(q, {"blanks": ["100", ""]})
    assert r["score"] == 50 and r["verdict"] == "partial"
    assert grade(q, {"blanks": []})["score"] == 0


@pytest.mark.parametrize("type_id", ["short_response", "math", "code", "error_analysis", "applied_scenario"])
def test_open_types_need_claude(type_id):
    assert grade(sample(type_id), {"text": "anything"}) is None


def test_skipped_counts_as_miss():
    r = skipped_result(sample("multiple_choice"))
    assert (r["score"], r["verdict"]) == (0, "incorrect")


def test_helpers():
    assert normalize("  The  Mitochondria. ") == "mitochondria"
    assert blank_matches("1,000", ["1000"])
    assert not blank_matches("", ["x"])
    assert lcs_length([1, 0, 2, 3], [0, 1, 2, 3]) == 3
    assert verdict_for(100) == "correct" and verdict_for(0) == "incorrect" and verdict_for(40) == "partial"


def test_mc_display_hides_answer_and_keeps_original_ids():
    q = sample("multiple_choice")
    d = display_for(q)
    assert "correct_index" not in d and "explanation" not in d
    assert sorted(o["id"] for o in d["options"]) == [0, 1, 2, 3]
    assert {o["text"] for o in d["options"]} == set(q["options"])


@pytest.mark.parametrize("type_id", ["short_response", "math", "code", "error_analysis", "applied_scenario", "fill_blank"])
def test_display_never_leaks_answer_keys(type_id):
    d = display_for(sample(type_id))
    for key in ("rubric", "final_answer", "blanks", "explanation", "correct", "correct_index", "correct_indices", "pairs"):
        assert key not in d


def test_answer_texts():
    q = sample("ordering")
    assert correct_answer_text(q).startswith("1. First")
    assert user_answer_text(q, display_for(q), {"order": [1, 0, 2, 3]}, False).startswith("1. Second")
    assert "Skipped" in user_answer_text(q, display_for(q), {}, True)
    m = sample("math")
    assert "Final answer" in user_answer_text(m, display_for(m), {"work": "w", "final": "2"}, False)
    c = sample("code")
    assert "```python" in user_answer_text(c, display_for(c), {"code": "print(1)"}, False)
    assert user_answer_text(sample("multiple_choice"), {}, {"choice": 99}, False) == "_Unreadable answer_"
