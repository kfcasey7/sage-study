"""Builds the public (answer-free) view of a question and human-readable answer summaries."""
from __future__ import annotations

import random
from typing import Any

from .. import config


def _rng(seed: str) -> random.Random:
    return random.Random(seed)


def build_display(question_id: str, q: dict[str, Any], subtopic_name: str) -> dict[str, Any]:
    """Public view sent to the UI. Options are shuffled deterministically per question;
    each shuffled option keeps its original index as ``id`` so grading never depends on order."""
    rng = _rng(question_id)
    t = q["type"]
    view: dict[str, Any] = {
        "type": t,
        "type_label": config.TYPE_LABELS[t],
        "subtopic_id": q["subtopic_id"],
        "subtopic_name": subtopic_name,
        "difficulty": q["difficulty"],
        "difficulty_label": config.DIFFICULTY_LEVELS[q["difficulty"]]["label"],
        "prompt": q["prompt"],
        "uses_outside_knowledge": q["uses_outside_knowledge"],
        "source_hint": q.get("source_hint", ""),
    }
    if t in ("multiple_choice", "select_all"):
        opts = [{"id": i, "text": o} for i, o in enumerate(q["options"])]
        rng.shuffle(opts)
        view["options"] = opts
    elif t == "fill_blank":
        view["blank_count"] = len(q["blanks"])
    elif t == "matching":
        view["left"] = [p["left"] for p in q["pairs"]]
        right = [p["right"] for p in q["pairs"]] + list(q.get("distractors", []))
        rng.shuffle(right)
        view["right"] = right
    elif t == "ordering":
        items = [{"id": i, "text": s} for i, s in enumerate(q["items"])]
        # Re-shuffle until the order differs from the answer (lists of >=3 always can).
        for _ in range(10):
            rng.shuffle(items)
            if [it["id"] for it in items] != list(range(len(items))):
                break
        view["items"] = items
    elif t == "code":
        view["language"] = q["language"]
        view["starter_code"] = q["starter_code"]
    elif t == "error_analysis":
        view["language"] = q["language"]
        view["flawed_work"] = q["flawed_work"]
    elif t == "applied_scenario":
        view["scenario"] = q["scenario"]
    return view


def _fence(text: str, language: str = "") -> str:
    lang = language.lower().replace("++", "pp").replace("c#", "csharp") if language else ""
    return f"```{lang}\n{text.rstrip()}\n```"


def correct_answer_text(q: dict[str, Any]) -> str:
    """Markdown summary of the answer key."""
    t = q["type"]
    if t == "multiple_choice":
        return q["options"][q["correct_index"]]
    if t == "select_all":
        return "\n".join(f"- {q['options'][i]}" for i in sorted(q["correct_indices"]))
    if t == "true_false":
        return "True" if q["correct"] else "False"
    if t == "fill_blank":
        return "\n".join(
            f"{n}. {b['accepted_answers'][0]}" for n, b in enumerate(q["blanks"], 1)
        )
    if t == "matching":
        return "\n".join(f"- {p['left']} → {p['right']}" for p in q["pairs"])
    if t == "ordering":
        return "\n".join(f"{n}. {s}" for n, s in enumerate(q["items"], 1))
    if t == "math":
        return f"{q['rubric']['model_answer']}\n\n**Final answer:** ${q['final_answer']}$"
    if t in ("code", "error_analysis") and q.get("language"):
        answer = q["rubric"]["model_answer"]
        return answer if "```" in answer else _fence(answer, q["language"])
    return q["rubric"]["model_answer"]


def user_answer_text(q: dict[str, Any], display: dict[str, Any], response: dict[str, Any], skipped: bool) -> str:
    if skipped:
        return "_Skipped / I don't know_"
    t = q["type"]
    try:
        if t == "multiple_choice":
            c = response.get("choice")
            return q["options"][c] if c is not None else "_No answer_"
        if t == "select_all":
            chosen = response.get("choices") or []
            return "\n".join(f"- {q['options'][i]}" for i in sorted(chosen)) or "_None selected_"
        if t == "true_false":
            v = response.get("value")
            return "_No answer_" if v is None else ("True" if v else "False")
        if t == "fill_blank":
            blanks = response.get("blanks") or []
            return "\n".join(f"{n}. {b or '_(blank)_'}" for n, b in enumerate(blanks, 1)) or "_No answer_"
        if t == "matching":
            matches = response.get("matches") or []
            lines = []
            for i, left in enumerate(display["left"]):
                m = matches[i] if i < len(matches) else None
                lines.append(f"- {left} → {display['right'][m] if m is not None else '_(none)_'}")
            return "\n".join(lines)
        if t == "ordering":
            order = response.get("order") or []
            return "\n".join(f"{n}. {q['items'][i]}" for n, i in enumerate(order, 1)) or "_No answer_"
        if t == "math":
            work = (response.get("work") or "").strip()
            final = (response.get("final") or "").strip()
            parts = []
            if work:
                parts.append(work)
            parts.append(f"**Final answer:** ${final}$" if final else "**Final answer:** _(none)_")
            return "\n\n".join(parts)
        if t in ("code", "error_analysis"):
            parts = []
            if response.get("text", "").strip():
                parts.append(response["text"].strip())
            if response.get("code", "").strip():
                parts.append(_fence(response["code"], q.get("language", "")))
            return "\n\n".join(parts) or "_No answer_"
        return (response.get("text") or "").strip() or "_No answer_"
    except (IndexError, KeyError, TypeError):
        return "_Unreadable answer_"
