"""Instructions for study-guide sections and Mermaid diagram repair."""
from __future__ import annotations

MERMAID_RULES = """\
Mermaid rules (the diagram is rendered by Mermaid 11 and must parse):
- Start with one of: `flowchart TD`, `flowchart LR`, `sequenceDiagram`, `stateDiagram-v2`, `classDiagram`, \
`timeline`, or `mindmap` (use flowchart for concept maps).
- Node IDs are plain alphanumeric words (A, B, step1). Put every label in double quotes: A["Heat added (Q)"].
- No LaTeX, no $ signs, no HTML tags, no Markdown inside the diagram. Use plain Unicode for symbols (Δ, θ, ≤, ², →).
- Edge labels use the -->|"label"| form. Keep it to about 4-14 nodes.
- Do not wrap the diagram in ``` fences."""


def _misses_block(misses: list[dict]) -> str:
    return "\n\n".join(
        f"""<missed_question n="{i}" type="{m['type']}" score="{m['score']}" confidence="{m.get('confidence') or 'not given'}">
Question: {m['prompt']}
Student's answer: {m['your_answer']}
Correct answer: {m['correct_answer']}
Grader feedback: {m.get('feedback') or ''}
Misconception: {m.get('misconception') or ''}
</missed_question>"""
        for i, m in enumerate(misses, 1)
    )


def section_instruction(subtopic: dict, score: float | None, weak_reasons: list[str], misses: list[dict],
                        mode: str = "weak") -> str:
    """mode "weak": after a quiz, for a subtopic the student did poorly on. mode "topic": from the Material
    Breakdown, for any subtopic the student picked, with their quiz history on it if they have one."""
    if mode == "weak":
        reasons = []
        if "low_score" in weak_reasons:
            reasons.append("scored below 70%")
        if "confidently_wrong" in weak_reasons:
            reasons.append("answered incorrectly while marking high confidence")
        task = "Write one section of a personalized study guide for the subtopic below."
        performance = (f"<performance>Score: {'n/a' if score is None else f'{score:.0f}%'}. Flagged because the student "
                       f"{' and '.join(reasons) or 'struggled here'}.</performance>")
        misses_text = _misses_block(misses) or "(No individual misses recorded; the subtopic was flagged as weak overall.)"
        address = " Address the specific misunderstandings shown above."
    else:
        task = "Write one section of a study guide for the subtopic below, which the student chose to study."
        if score is None:
            performance = "<performance>The student hasn't been quizzed on this subtopic yet: teach it from the start.</performance>"
        else:
            performance = f"<performance>Quiz score on this subtopic so far: {score:.0f}%.</performance>"
        misses_text = _misses_block(misses)
        address = " Address the misunderstandings shown in the missed questions above." if misses else ""
    return f"""\
<task>{task}</task>

<subtopic name="{subtopic['name']}">{subtopic.get('description', '')}</subtopic>
{performance}

{misses_text}

Write the section for this student, based on the material:
- `title`: the subtopic name, or a clearer version of it.
- `explanation`: a plain-language explanation of the concept (2-5 short paragraphs of Markdown). Build \
intuition first, then precision.{address}
- `key_formulas`: the important formulas for this subtopic as KaTeX-compatible LaTeX WITHOUT $ delimiters, \
each with a one-line description that defines its symbols. Use an empty list if the subtopic has no formulas.
- At least one graphic:
  - `diagram`: set include=true with a Mermaid diagram (flowchart, concept map, sequence, or state machine) \
when structure, process, or relationships would help.
  - `chart`: set include=true when a quantitative relationship is easier to see as a plot. Give 8-40 \
points per series computed accurately from the relevant formula with realistic values. `label` is used for \
bar-chart category names (use "" otherwise). Set include=false and leave the fields empty when not used.
- `worked_example`: a representative problem with clear numbered steps (Markdown/LaTeX in each step) and \
the final answer.
- `common_mistakes`: 2-4 mistakes. Mistakes the student actually made (in the missed questions above, if \
any) come first, with from_your_answers=true; describe what they did, why it is wrong, and how to avoid it. \
Other mistakes students commonly make here have from_your_answers=false.
- `practice_questions`: 2-3 new questions (not repeats of the missed ones) with complete answers.

{MERMAID_RULES}
"""


def diagram_repair_instruction(mermaid: str, error: str) -> str:
    return f"""\
<task>This Mermaid diagram from a study guide failed to render. Return a corrected version.</task>

<diagram>
{mermaid}
</diagram>

<parser_error>
{error[:1500]}
</parser_error>

Keep the same content and meaning, and fix the syntax. If a construct is fragile, simplify it to a \
plain `flowchart TD`.

{MERMAID_RULES}
"""
