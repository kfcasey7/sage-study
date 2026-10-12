"""Answer submission and grading dispatch (local deterministic vs Claude rubric grading)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .. import config, db
from ..claude_client import structured_call
from ..errors import AppError
from ..prompts.grade import grading_instruction
from ..schemas.guide import GRADE_SCHEMA, GradeOut
from ..schemas.questions import AnswerSubmission
from . import generation
from . import sessions as S
from .grading_local import grade_local, skipped_result
from .presentation import correct_answer_text, user_answer_text

log = logging.getLogger(__name__)

_grading: dict[str, asyncio.Task] = {}


def _grade_fields(res: dict[str, Any]) -> dict[str, Any]:
    return {
        "grade_status": "done",
        "score": res["score"],
        "verdict": res["verdict"],
        "feedback": res["feedback"],
        "model_answer": res["model_answer"],
        "misconception": res.get("misconception", ""),
        "details_json": db.dumps(res.get("details", {})),
        "graded_by": res["graded_by"],
        "grade_error": None,
    }


async def grade_with_claude(question_id: str) -> None:
    q = S.load_question(question_id)
    ans = S.load_answer(question_id)
    if ans is None:
        raise AppError("not_found", "No answer to grade.")
    session = S.get_session(q["session_id"])
    answer_text = user_answer_text(q["payload"], q["display"], ans["response"], ans["skipped"])
    try:
        grade: GradeOut = await structured_call(
            S.call_context(session),
            purpose="grade",
            instruction=grading_instruction(q["payload"], answer_text),
            schema=GRADE_SCHEMA,
            validate=GradeOut.model_validate,
            max_tokens=16000,
        )
    except AppError as e:
        db.update("answers", "question_id", question_id, {"grade_status": "error", "grade_error": db.dumps(e.to_dict())})
        raise
    model_answer = grade.model_answer.strip() or correct_answer_text(q["payload"])
    if q["type"] == "math" and q["payload"].get("final_answer") and "Final answer" not in model_answer:
        model_answer += f"\n\n**Final answer:** ${q['payload']['final_answer']}$"
    db.update("answers", "question_id", question_id, _grade_fields({
        "score": float(grade.score),
        "verdict": grade.verdict,
        "feedback": grade.feedback,
        "model_answer": model_answer,
        "misconception": grade.misconception,
        "details": {"criteria": [c.model_dump() for c in grade.criteria_results]},
        "graded_by": "claude",
    }))


def schedule_grade(question_id: str) -> asyncio.Task:
    task = _grading.get(question_id)
    if task and not task.done():
        return task
    db.update("answers", "question_id", question_id, {"grade_status": "pending", "grade_error": None})

    async def run() -> None:
        try:
            await grade_with_claude(question_id)
        finally:
            # Adaptive sessions wait on the grade to pick the next difficulty.
            q = db.query_one("SELECT session_id FROM questions WHERE id = ?", (question_id,))
            if q:
                generation._kick(q["session_id"])

    task = asyncio.get_running_loop().create_task(run())
    _grading[question_id] = task
    return task


async def submit_answer(question_id: str, sub: AnswerSubmission) -> dict[str, Any]:
    q = S.load_question(question_id)
    if q["status"] != "served":
        raise AppError("conflict", "This question isn't active.")
    if S.load_answer(question_id):
        raise AppError("conflict", "This question was already answered.")
    session = S.get_session(q["session_id"])
    if session["status"] == "completed":
        raise AppError("conflict", "This session is already finished.")

    if sub.skipped:
        res = skipped_result(q["payload"])
    elif config.GRADING_MODE[q["type"]] in ("local", "hybrid"):
        res = grade_local(q["payload"], q["display"], sub.response)
    else:
        res = None

    row = {
        "question_id": question_id,
        "session_id": q["session_id"],
        "response_json": db.dumps(sub.response),
        "confidence": None if sub.skipped else sub.confidence,
        "skipped": int(sub.skipped),
        "answered_at": db.now(),
        "grade_status": "pending",
    }
    if res:
        row.update(_grade_fields(res))
        row["details_json"] = db.dumps(res.get("details", {}))
    db.insert("answers", row)

    cfg = session["config"]
    if res is None:
        task = schedule_grade(question_id)
        if cfg["feedback_mode"] == "immediate" or cfg["adaptive"]:
            try:
                await asyncio.shield(task)
            except AppError:
                pass  # stored on the answer row; the UI offers a retry
    generation._kick(q["session_id"])
    return answer_view(question_id, reveal=cfg["feedback_mode"] == "immediate")


async def regrade(question_id: str) -> dict[str, Any]:
    ans = S.load_answer(question_id)
    if ans is None:
        raise AppError("not_found", "No answer to grade.")
    if ans["grade_status"] != "done":
        try:
            await asyncio.shield(schedule_grade(question_id))
        except AppError:
            pass
    q = S.load_question(question_id)
    session = S.get_session(q["session_id"])
    return answer_view(question_id, reveal=session["config"]["feedback_mode"] == "immediate" or session["status"] == "completed")


def answer_view(question_id: str, reveal: bool) -> dict[str, Any]:
    q = S.load_question(question_id)
    ans = S.load_answer(question_id)
    assert ans is not None
    view: dict[str, Any] = {
        "question_id": question_id,
        "grade_status": ans["grade_status"],
        "grade_error": db.loads(ans["grade_error"], None),
        "revealed": reveal,
    }
    if reveal and ans["grade_status"] == "done":
        view.update({
            "score": ans["score"],
            "verdict": ans["verdict"],
            "skipped": ans["skipped"],
            "feedback": ans["feedback"],
            "correct_answer": ans["model_answer"] or correct_answer_text(q["payload"]),
            "explanation": q["payload"].get("explanation", ""),
            "your_answer": user_answer_text(q["payload"], q["display"], ans["response"], ans["skipped"]),
            "misconception": ans["misconception"],
            "criteria": (ans["details"] or {}).get("criteria", []),
            "answer_key": answer_key(q["payload"], q["display"]),
        })
    return view


def answer_key(payload: dict[str, Any], display: dict[str, Any]) -> dict[str, Any]:
    """Structured key so the UI can highlight right/wrong choices in objective inputs."""
    t = payload["type"]
    if t == "multiple_choice":
        return {"correct_ids": [payload["correct_index"]]}
    if t == "select_all":
        return {"correct_ids": sorted(payload["correct_indices"])}
    if t == "true_false":
        return {"correct": payload["correct"]}
    if t == "matching":
        right = display["right"]
        return {"matches": [right.index(p["right"]) for p in payload["pairs"]]}
    if t == "ordering":
        return {"order": list(range(len(payload["items"])))}
    if t == "fill_blank":
        return {"blanks": [b["accepted_answers"][0] for b in payload["blanks"]]}
    return {}


async def wait_for_grades(session_id: str) -> None:
    pending = db.query("SELECT question_id FROM answers WHERE session_id = ? AND grade_status != 'done'", (session_id,))
    tasks = [schedule_grade(r["question_id"]) for r in pending]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
