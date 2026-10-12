"""Deterministic grading for objective question types (no API call)."""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

from .presentation import correct_answer_text


def verdict_for(score: float) -> str:
    if score >= 99.5:
        return "correct"
    if score <= 0.5:
        return "incorrect"
    return "partial"


def _result(score: float, feedback: str, q: dict[str, Any], details: dict | None = None) -> dict[str, Any]:
    score = round(max(0.0, min(100.0, score)), 1)
    return {
        "score": score,
        "verdict": verdict_for(score),
        "feedback": feedback,
        "model_answer": correct_answer_text(q),
        "misconception": "",
        "details": details or {},
        "graded_by": "local",
    }


def skipped_result(q: dict[str, Any]) -> dict[str, Any]:
    r = _result(0, "Skipped. This counts as a miss for mastery tracking.", q)
    r["verdict"] = "incorrect"
    return r


# --- Fill-in-the-blank normalisation ---------------------------------------------

_WS = re.compile(r"\s+")
_NUM = re.compile(r"^[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?$")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").strip().lower()
    t = t.strip("$").strip()
    t = _WS.sub(" ", t)
    t = t.rstrip(".;,")
    for article in ("the ", "a ", "an "):
        if t.startswith(article):
            t = t[len(article):]
            break
    return t.strip()


def _as_number(text: str) -> float | None:
    t = normalize(text).replace(",", "").replace(" ", "")
    return float(t) if _NUM.match(t) else None


def blank_matches(given: str, accepted: list[str]) -> bool:
    g = normalize(given)
    if not g:
        return False
    g_num = _as_number(given)
    for a in accepted:
        if g == normalize(a):
            return True
        a_num = _as_number(a)
        if g_num is not None and a_num is not None and math.isclose(g_num, a_num, rel_tol=1e-6, abs_tol=1e-9):
            return True
    return False


# --- Grading -----------------------------------------------------------------------

def lcs_length(a: list[int], b: list[int]) -> int:
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            dp[i + 1][j + 1] = dp[i][j] + 1 if x == y else max(dp[i][j + 1], dp[i + 1][j])
    return dp[-1][-1]


def grade_local(q: dict[str, Any], display: dict[str, Any], response: dict[str, Any]) -> dict[str, Any] | None:
    """Returns a grade dict, or None when the answer needs Claude (fill-in-the-blank answers
    that don't exactly match an accepted answer)."""
    t = q["type"]

    if t == "multiple_choice":
        ok = response.get("choice") == q["correct_index"]
        return _result(100 if ok else 0, "", q)

    if t == "true_false":
        ok = response.get("value") is q["correct"]
        return _result(100 if ok else 0, "", q)

    if t == "select_all":
        chosen = set(response.get("choices") or [])
        correct = set(q["correct_indices"])
        hits = len(chosen & correct)
        wrong = len(chosen - correct)
        score = max(0.0, (hits - wrong) / len(correct)) * 100
        missed = len(correct - chosen)
        if score == 100:
            fb = "Correct: you selected every right option and nothing else."
        else:
            fb = f"You selected {hits} of {len(correct)} correct options"
            fb += f" and {wrong} incorrect option{'s' if wrong != 1 else ''}." if wrong else "."
            if missed:
                fb += f" {missed} correct option{'s were' if missed != 1 else ' was'} missed."
        return _result(score, fb, q, {"hits": hits, "wrong": wrong, "missed": missed})

    if t == "matching":
        matches = response.get("matches") or []
        right = display["right"]
        n = len(q["pairs"])
        correct_count = 0
        for i, pair in enumerate(q["pairs"]):
            m = matches[i] if i < len(matches) else None
            if m is not None and 0 <= m < len(right) and right[m] == pair["right"]:
                correct_count += 1
        fb = "All pairs matched correctly." if correct_count == n else f"{correct_count} of {n} pairs matched correctly."
        return _result(100 * correct_count / n, fb, q, {"correct_pairs": correct_count, "total": n})

    if t == "ordering":
        order = list(response.get("order") or [])
        n = len(q["items"])
        target = list(range(n))
        if order == target:
            return _result(100, "Correct order.", q)
        # Credit = longest run of items already in the right relative order.
        in_place = lcs_length(order, target)
        score = 100 * in_place / n if len(order) == n else 0
        fb = f"{in_place} of {n} steps are in the correct relative order."
        return _result(min(score, 90), fb, q, {"in_order": in_place, "total": n})

    if t == "fill_blank":
        given = list(response.get("blanks") or [])
        n = len(q["blanks"])
        given += [""] * (n - len(given))
        results = [blank_matches(g, b["accepted_answers"]) for g, b in zip(given, q["blanks"])]
        if all(results):
            return _result(100, "Correct.", q)
        unresolved = [i for i, (ok, g) in enumerate(zip(results, given)) if not ok and g.strip()]
        if unresolved:
            return None  # a non-matching answer might still be an acceptable equivalent
        return _result(100 * sum(results) / n, f"{sum(results)} of {n} blanks correct.", q)

    return None
