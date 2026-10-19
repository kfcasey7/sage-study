"""Instructions for finding YouTube videos. Claude writes search queries and chooses among real search
results; it never writes a video URL or ID of its own."""
from __future__ import annotations

from typing import Any

SEARCH_SYSTEM_PROMPT = """\
You help a student find YouTube videos that explain what they are studying. You can only search the \
web with the WebSearch tool; you cannot open pages. Only report videos whose URLs appear in your search \
results, copied exactly. Never write a YouTube URL or video ID from memory. Your response is parsed by \
software against a JSON schema: reply with only the JSON object.
"""

PREFERENCES = """\
Prefer, in order:
- videos that explain this specific concept (not a whole course, a different topic, or a passing mention);
- clear educational channels (universities, well-known educators, textbook or exam-prep channels);
- a length of about 4-25 minutes; avoid Shorts (under 90 seconds) and lectures over an hour unless \
nothing else covers it;
- English, unless the topic names another language.
Avoid clickbait, compilations, reaction videos, and videos that only sell a course."""


def _targets_block(targets: list[dict[str, Any]]) -> str:
    return "\n".join(f'<target key="{t["key"]}" title="{t["title"]}">{t.get("description", "")}</target>' for t in targets)


def queries_instruction(targets: list[dict[str, Any]], subject: str) -> str:
    return f"""\
<task>Write YouTube search queries that will find videos explaining each target below.</task>
{f'<subject>{subject}</subject>' if subject else ''}
{_targets_block(targets)}

For each target, return 2 queries (3 if it is broad), each 3-8 words, the way a student would search YouTube \
(e.g. "first law of thermodynamics explained", "isothermal process work derivation"). Use standard \
terminology from the subject, not the wording of a quiz question, and never include an answer to a question.
"""


def search_instruction(targets: list[dict[str, Any]], subject: str, per_target: int, exclude: list[str]) -> str:
    skip = f"\nDo not report these videos (already chosen): {', '.join(exclude)}." if exclude else ""
    return f"""\
<task>Find YouTube videos that explain each target below.</task>
{f'<subject>{subject}</subject>' if subject else ''}
{_targets_block(targets)}

For each target, run 1-2 WebSearch searches with allowed_domains set to ["youtube.com"], using queries a \
student would type into YouTube (standard terminology, 3-8 words; never include an answer to a question). \
Then report up to {per_target} candidate videos per target, best first. Each must be a youtube.com/watch \
or youtu.be URL copied exactly from your search results, with its title from the results and one short \
sentence (at most 20 words) on why it fits the target.{skip}

{PREFERENCES}
"""


def rank_instruction(targets: list[dict[str, Any]], candidates: dict[str, list[dict[str, Any]]], picks: int) -> str:
    blocks = []
    for t in targets:
        rows = []
        for c in candidates.get(t["key"], []):
            mins = f'{c["duration_s"] // 60}:{c["duration_s"] % 60:02d}' if c.get("duration_s") else "unknown"
            views = f'{c["views"]:,}' if c.get("views") else "unknown"
            desc = (c.get("description") or "").replace("\n", " ")[:200]
            rows.append(f'- video_id={c["video_id"]} | "{c["title"]}" | channel: {c.get("channel") or "?"} | '
                        f'length: {mins} | views: {views} | {desc}')
        blocks.append(f'<target key="{t["key"]}" title="{t["title"]}">\n{t.get("description", "")}\n'
                      f'<candidates>\n{chr(10).join(rows) or "(none)"}\n</candidates>\n</target>')
    return f"""\
<task>Choose the best YouTube videos for each target from its candidates.</task>

{chr(10).join(blocks)}

For each target, return up to {picks + 3} of its candidates, best first (the first {picks} are shown to \
the student; the rest are kept as replacements). Skip candidates that don't fit at all; return an empty \
list if none do. For each, give the video_id exactly as listed and a `reason`: one sentence (at most 20 \
words) on why it is relevant to this target, written to the student.

{PREFERENCES}
"""
