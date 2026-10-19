"""Instruction for a Study Set's Material Breakdown, first build and merge-on-append."""
from __future__ import annotations

from typing import Any

from .study_guide import MERMAID_RULES


def _prompts_block(prompts: list[dict[str, Any]], new_version: int) -> str:
    if not prompts:
        return "<prompt_history>(No prompt was given: cover the main ideas of the sources.)</prompt_history>"
    lines = []
    for i, p in enumerate(prompts, 1):
        newest = ' newest="true"' if p["version"] == new_version else ""
        lines.append(f'<prompt n="{i}"{newest}>\n{p["text"].strip()}\n</prompt>')
    return "<prompt_history>\n" + "\n".join(lines) + "\n</prompt_history>"


def _sources_block(sources: list[dict[str, Any]]) -> str:
    ready = [s for s in sources if s["status"] == "ready"]
    failed = [s for s in sources if s["status"] == "failed"]
    lines = [f'- {s["label"]}: {s["title"]} ({s["source_type"]}{", new" if s.get("new") else ""})' for s in ready]
    out = "<sources>\n" + ("\n".join(lines) or "(none)") + "\n</sources>"
    if failed:
        out += ("\n<unreadable_sources>These were added but couldn't be read, so they are NOT in the material:\n"
                + "\n".join(f'- {s["title"]}' for s in failed) + "\n</unreadable_sources>")
    return out


def _existing_block(existing: list[dict[str, Any]]) -> str:
    rows = "\n".join(f'<subtopic ref="{s["id"]}" name="{s["name"]}">{s["summary"]}</subtopic>' for s in existing)
    return f"<current_subtopics>\n{rows}\n</current_subtopics>"


def breakdown_instruction(prompts: list[dict[str, Any]], sources: list[dict[str, Any]], existing: list[dict[str, Any]],
                          new_version: int) -> str:
    merging = bool(existing)
    merge_rules = f"""
This Study Set already has a breakdown, and the student's quiz results are attached to its subtopics, so \
keep it stable:
{_existing_block(existing)}
- Keep every current subtopic that is still covered, with its `ref` copied exactly. You may improve its \
summary, concepts, and formulas; set `change` to "updated" only if the new material or prompt changes \
what it covers, otherwise "unchanged". Keep the same name unless it is clearly wrong.
- Add subtopics for material or requests that the current ones don't cover, with `ref` "" and `change` "new". \
The newest prompt and sources marked "new" are usually why this update was requested.
- Drop a current subtopic only if a prompt explicitly asks to remove or stop covering it.
- Keep current subtopics in their existing order and put new ones where they fit in the material.""" if merging else """
- Set every `ref` to "" and every `change` to "new"."""
    return f"""\
<task>Write the Material Breakdown for this Study Set: a map of what the material covers that the student \
uses to choose what to study, quiz, and watch.</task>

{_prompts_block(prompts, new_version)}

{_sources_block(sources)}

The documents above are labelled with the same [S#] tags. Return:
- `title`: a short title for the set (at most 8 words), e.g. "Thermodynamics: First Law and Enthalpy".
- `overview`: 2-4 sentences of Markdown on what the material covers and how the parts fit together.
- `subtopics`: 3 to 12 subtopics that together cover what the prompts ask for (fewer for short material). \
Each must be narrow enough that a weak quiz score on it points to a specific thing to study, e.g. \
"Entropy change of ideal gases" rather than "Entropy". For each:
  - `name` (at most 6 words), `summary` (1-2 sentences of Markdown).
  - `key_concepts`: 3-8 key terms or ideas, each a few words.
  - `formulas`: the key formulas as KaTeX-compatible LaTeX WITHOUT $ delimiters, each with a one-line \
description that defines its symbols. Use an empty list when the subtopic has no formulas.
  - `difficulty`: 1 (intro/recall) to 5 (expert synthesis), for a student meeting it for the first time.
  - `sources`: the [S#] labels (e.g. "S2") of the sources it comes from. Use an empty list only for \
content that comes from a prompt rather than any source.
- `map_mermaid`: a `flowchart LR` or `flowchart TD` showing how the subtopics relate (prerequisites, \
"part of", "used in"). Use one node per subtopic, labelled with its exact name, and a few labelled edges.
- `coverage_notes`: things a prompt asks about that the sources don't cover, or cover only briefly, each \
one sentence naming the request. If the prompts ask for something the sources lack, still include a \
subtopic for it when it is standard course content, and say in its summary that it comes from general \
knowledge. Use an empty list when everything requested is covered.
{merge_rules}

If a prompt is narrower than the sources (e.g. "only chapter 3"), break down only that part.

{MERMAID_RULES}
"""
