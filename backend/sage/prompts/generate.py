"""Instruction for generating quiz questions. Edit TYPE_GUIDANCE to change how each question
type is written."""
from __future__ import annotations

import json

from .. import config

DIFFICULTY_GUIDANCE = {
    1: "Intro: recall of definitions, terms, and basic facts stated directly in the material.",
    2: "Review: explain or connect ideas covered in the material; single-step application.",
    3: "Exam-level: the kind of problem a fair exam would ask; apply concepts in familiar settings, 2-3 steps.",
    4: "Challenging: multi-step problems, edge cases, common traps, and subtle distinctions between related ideas.",
    5: "Expert: synthesis across subtopics, unfamiliar situations, and rigorous justification.",
}

TYPE_GUIDANCE = {
    "multiple_choice": (
        "Four options, exactly one correct (`correct_index`, 0-based). Distractors must be plausible and "
        "reflect real misconceptions. Do not use 'all of the above' or 'none of the above', because the "
        "app shuffles options."
    ),
    "select_all": (
        "Four to six options; `correct_indices` lists every correct option (at least one, not all). "
        "Say 'Select all that apply' in the prompt. No 'all/none of the above' options."
    ),
    "true_false": (
        "A single precise statement in `prompt` that is unambiguously true or false according to the "
        "material. Set `correct`. Avoid trick wording and double negatives."
    ),
    "fill_blank": (
        "Write the sentence in `prompt` with each blank marked exactly as {{blank}} (one to three blanks). "
        "`blanks` has one entry per blank, in order. `accepted_answers` lists every reasonable form "
        "(synonyms, abbreviations, singular/plural, numeric forms such as 0.5 and 1/2)."
    ),
    "matching": (
        "Four to six `pairs` of `left` (terms) and `right` (definitions or values). Each right side must "
        "match exactly one left side. Add zero to two `distractors`: right-side entries that match nothing. "
        "The prompt should say what is being matched."
    ),
    "ordering": (
        "Four to seven `items` listed in the CORRECT order (the app shuffles them). Use a real process, "
        "sequence, or derivation from the material where the order is unambiguous. The prompt should say "
        "what is being ordered."
    ),
    "short_response": (
        "Answerable in 1-3 sentences. Rubric: 2-3 criteria; model answer of 1-3 sentences."
    ),
    "long_response": (
        "An essay-style question needing 2-4 paragraphs: explain, compare, justify, or evaluate. "
        "Rubric: 3-5 criteria covering the key points, reasoning quality, and accuracy."
    ),
    "free_response": (
        "An open question that can be answered in several valid ways (a paragraph or so). Rubric: "
        "criteria that reward correct reasoning whatever approach the student takes."
    ),
    "math": (
        "A calculation or derivation. The student shows step-by-step work in LaTeX plus a separate final "
        "answer. Give all values and units needed. `final_answer` is the final result in LaTeX without "
        "$ delimiters (include units). Rubric criteria should cover setup, method, execution, and final answer. "
        "The rubric's model answer shows a complete worked solution."
    ),
    "code": (
        "Ask the student to write a function or short snippet in {language}. State the exact signature, "
        "inputs, outputs, and any constraints. `language` = \"{language}\". `starter_code` contains the "
        "signature and a comment where the body goes (or an empty string). Rubric criteria cover correctness "
        "on normal inputs, edge cases, and clarity/style. Model answer = complete working code."
    ),
    "error_analysis": (
        "Show flawed work in `flawed_work` containing one or two realistic, specific mistakes. Use either "
        "{language} code (set `language` = \"{language}\") or a worked math/engineering solution (set "
        "`language` = \"\" and write the work in Markdown/LaTeX). The prompt asks the student to find the "
        "mistake, explain why it is wrong, and give the corrected work. Do not hint at where the error is. "
        "Model answer names each error, explains it, and shows the fix."
    ),
    "applied_scenario": (
        "Put a short, concrete, realistic engineering or real-world situation in `scenario` (with numbers "
        "where useful), then ask in `prompt` how a concept from the material applies: analyze, decide, design, "
        "or estimate. Rubric rewards correct use of the concept, justified assumptions, and a clear conclusion."
    ),
}


def generation_instruction(
    requests: list[dict],
    subtopics: list[dict],
    language: str,
    previous_prompts: list[str],
) -> str:
    """requests: [{request, subtopic_id, type, difficulty}] - one question per request."""
    lang = language or "Python"
    types_used = sorted({r["type"] for r in requests}, key=config.QUESTION_TYPE_IDS.index)
    levels_used = sorted({r["difficulty"] for r in requests})

    sub_lines = "\n".join(f'- id "{s["id"]}": {s["name"]}: {s["description"]}' for s in subtopics)
    req_lines = "\n".join(
        f'- slot {r["request"]}: type "{r["type"]}", subtopic_id "{r["subtopic_id"]}", difficulty {r["difficulty"]}'
        for r in requests
    )
    type_lines = "\n".join(
        f"- {t}: {TYPE_GUIDANCE[t].replace('{language}', lang)}" for t in types_used
    )
    level_lines = "\n".join(f"- {d}: {DIFFICULTY_GUIDANCE[d]}" for d in levels_used)

    avoid = ""
    if previous_prompts:
        shown = [p[:160].replace("\n", " ") for p in previous_prompts[-30:]]
        avoid = (
            "\n<already_asked>\nThe student has already seen these questions. Do not repeat or "
            "closely paraphrase them; test different facts or skills:\n"
            + "\n".join(f"- {json.dumps(p, ensure_ascii=False)}" for p in shown)
            + "\n</already_asked>\n"
        )

    return f"""\
<task>Write {len(requests)} quiz question{'s' if len(requests) != 1 else ''}, one for each slot below.</task>

<subtopics>
{sub_lines}
</subtopics>

<slots>
{req_lines}
</slots>

<difficulty_levels>
{level_lines}
</difficulty_levels>

<question_types>
{type_lines}
</question_types>
{avoid}
Rules:
- Return exactly one question per slot, copying `slot`, `type`, `subtopic_id`, and `difficulty` from the slot.
- Test the named subtopic at the named difficulty, using the material.
- Set `uses_outside_knowledge` to true only if answering correctly requires information that is not in the material.
- `explanation` (shown after answering) says in 1-3 sentences why the correct answer is right.
- Every question must be self-contained: include any values, definitions, or context the student needs.
- Make sure each question has one defensible correct answer (or, for open types, a rubric that a grader \
can apply consistently). Double-check calculations in answer keys.
"""
