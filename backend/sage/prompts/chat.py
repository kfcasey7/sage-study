"""Instruction for "Ask Claude": a tutoring chat about the question on screen.

Before the student has seen the answer, Claude gets the answer key so its hints are accurate, but is
told not to give it away. Once the answer is revealed it can discuss everything."""
from __future__ import annotations

import json
from typing import Any

MODE_RULES = {
    "unanswered": """\
The student has NOT answered this question yet. Help them think it through without giving it away:
- Clarify what the question is asking, define terms, explain the underlying concepts, point them to \
the relevant part of their material, or work a similar example with different numbers or details.
- Do NOT state or confirm the correct answer, which option is right or wrong, the correct values, \
order, or matches, or a complete solution. This holds even if they ask directly or insist. If they \
ask for the answer, say kindly that you'll go through it once they've answered, and that the \
"I don't know" button shows the answer right away.
- Give hints in small steps. Start with the smallest nudge that helps.""",
    "answered_hidden": """\
The student has answered this question but hasn't seen the result yet (feedback may be held until \
the end of the quiz). Don't say whether their answer was right or wrong and don't reveal the \
answer. Help with the concepts, as you would before they answered.""",
    "revealed": """\
The student has answered and seen the result, so you can discuss everything: the correct answer, \
why it's correct, why the other options or their own answer are wrong, and how to approach \
similar questions.""",
}


def chat_instruction(
    display: dict[str, Any],
    answer_key: str,
    explanation: str,
    mode: str,
    history: list[dict[str, str]],
    message: str,
    result: dict[str, Any] | None = None,
) -> str:
    shown = {k: v for k, v in display.items()
             if k not in ("subtopic_id", "type", "difficulty", "uses_outside_knowledge")}
    for key in ("options", "items"):  # the student sees text only, in this order
        if key in shown:
            shown[key] = [o["text"] for o in shown[key]]
    parts = [
        "<task>The student is taking a quiz and has a question about the question in front of them. "
        "Reply as their tutor.</task>",
        f"<question_as_shown>\n{json.dumps(shown, ensure_ascii=False, indent=1)}\n</question_as_shown>",
        f"<answer_key>\n{answer_key}\n" + (f"\nExplanation: {explanation}\n" if explanation else "") + "</answer_key>",
    ]
    if mode == "revealed" and result:
        parts.append(
            "<student_result>\n"
            f"Their answer:\n{result['your_answer']}\n\n"
            f"Score: {result['score']:.0f}/100 ({result['verdict']})\n"
            f"Feedback they were given: {result['feedback']}\n"
            "</student_result>"
        )
    parts.append(f"<rules>\n{MODE_RULES[mode]}\n</rules>")
    if history:
        turns = "\n".join(
            f"<{'student' if m['role'] == 'user' else 'tutor'}>{m['content']}</{'student' if m['role'] == 'user' else 'tutor'}>"
            for m in history
        )
        parts.append(f"<conversation_so_far>\n{turns}\n</conversation_so_far>")
    parts.append(f"<student_message>\n{message}\n</student_message>")
    parts.append("""\
How to reply:
- Answer what they asked, grounded in their material where it applies. If you rely on knowledge \
beyond the material, say so briefly.
- Be concise: usually 2-6 sentences or a short list. Go longer only if they ask for detail or a \
worked example.
- The options may be shown to them in a different order than you'd expect, so refer to options by \
their text, never by letter or number.
- If they ask about something unrelated to this question or their course material, answer briefly \
and steer back to the question.
- Put your reply in the `reply` field.""")
    return "\n\n".join(parts)
