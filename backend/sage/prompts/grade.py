"""Instruction for grading open-ended answers against the rubric generated with the question."""
from __future__ import annotations

import json

TYPE_GRADING_NOTES = {
    "math": (
        "Check the reasoning, not just the final answer. Award method credit for a correct setup and "
        "approach even when there is an arithmetic slip. Accept mathematically equivalent forms of the "
        "final answer (unsimplified vs simplified, fraction vs decimal within sensible rounding, equivalent "
        "units, rearranged expressions). A correct final answer with no supporting work earns at most "
        "partial credit unless the question only asked for a result."
    ),
    "code": (
        "Trace the code mentally on typical inputs and on edge cases (empty input, zero, negative numbers, "
        "boundaries, large inputs). Correctness matters most, then edge cases, then clarity and style. "
        "Don't deduct for trivial syntax slips that don't change the logic, but say what they are. If the "
        "code would not run or gives wrong results, say which input breaks it."
    ),
    "error_analysis": (
        "Full credit requires finding each planted error, explaining why it is wrong, and giving a correct "
        "fix. Give partial credit for finding an error without a correct fix or explanation."
    ),
    "fill_blank": (
        "The student's blanks did not exactly match the accepted answers. Decide for each blank whether the "
        "answer is an acceptable equivalent (synonym, spelling variant, equivalent number or units) or wrong. "
        "Score = percentage of blanks that are acceptable."
    ),
    "applied_scenario": (
        "Reward correct application of the concept to the scenario, reasonable stated assumptions, and a "
        "clear conclusion. Different valid approaches can earn full credit."
    ),
}


def grading_instruction(question: dict, student_answer: str) -> str:
    q = {k: v for k, v in question.items() if k not in ("slot", "subtopic_id", "explanation")}
    notes = TYPE_GRADING_NOTES.get(question["type"], "")
    return f"""\
<task>Grade the student's answer to this question.</task>

<question>
{json.dumps(q, ensure_ascii=False, indent=1)}
</question>

<student_answer>
{student_answer}
</student_answer>

How to grade:
- Apply the rubric's criteria. For each criterion, report points awarded (0 to its max) with a short comment.
- `score` is 0-100: the share of rubric points earned, adjusted for overall correctness.
- `verdict`: "correct" for 85-100, "partial" for 40-84, "incorrect" for 0-39. Blank, irrelevant, \
or "I don't know" answers score 0.
- `feedback`: 2-5 specific sentences. Say what was right, what was missing or wrong, and how to fix it. \
Quote or refer to the student's own words or steps.
- `model_answer`: a complete exemplary answer (improve on the rubric's model answer if needed).
- `misconception`: one sentence naming the underlying misunderstanding behind the mistake, or "" if \
the answer is correct or the error is only a slip.
{('- ' + notes) if notes else ''}
"""
