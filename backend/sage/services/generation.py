"""Session creation, topic mapping, and the background question-generation worker.

Non-adaptive sessions: questions are generated in batches of BATCH_SIZE, kept about one batch ahead
of the student. Adaptive sessions: while the student answers question k, the worker prefetches one
candidate for slot k+1 at every difficulty the answer could lead to, in a single call. The matching
candidate is served and the rest are discarded."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic import ValidationError

from .. import config, db
from ..claude_client import structured_call
from ..errors import AppError
from ..prompts.generate import generation_instruction
from ..prompts.topic_map import TOPIC_MAP_INSTRUCTION
from ..schemas.guide import TOPIC_MAP_SCHEMA, TopicMap
from ..schemas.questions import generation_schema, parse_question
from . import sessions as S
from .mastery import candidate_difficulties, next_difficulty, plan_slots
from .presentation import build_display

log = logging.getLogger(__name__)

_workers: dict[str, asyncio.Task] = {}
MAX_STALLED_ROUNDS = 2


# --- Creation -------------------------------------------------------------------------

def create_session(
    *,
    material: str,
    subject: str,
    upload_ids: list[str],
    types: list[str],
    difficulty: int,
    adaptive: bool,
    count: int,
    language: str,
    settings: dict[str, Any],
    subtopics: list[dict[str, str]] | None = None,
    parent_session_id: str | None = None,
) -> str:
    types = [t for t in config.QUESTION_TYPE_IDS if t in set(types)]
    if not types:
        raise AppError("bad_request", "Pick at least one question type.")
    if not 1 <= difficulty <= 5:
        raise AppError("bad_request", "Difficulty must be between 1 and 5.")
    if not 1 <= count <= config.MAX_QUESTIONS:
        raise AppError("bad_request", f"Choose between 1 and {config.MAX_QUESTIONS} questions.")
    if not material.strip() and not upload_ids:
        raise AppError("bad_request", "Describe what to cover or upload at least one document.")
    if language and language not in config.CODE_LANGUAGES:
        raise AppError("bad_request", f"Unsupported code language '{language}'.")
    for uid in upload_ids:
        if not db.query_one("SELECT 1 FROM uploads WHERE id = ?", (uid,)):
            raise AppError("missing_file", "One of the uploaded files is no longer available. Remove it and upload it again.")

    session_id = db.new_id()
    cfg = {
        "types": types,
        "difficulty": difficulty,
        "adaptive": adaptive,
        "count": count,
        "language": language or "Python",
        "feedback_mode": settings["feedback_mode"],
        "model": settings["model"],
        "effort": settings["effort"],
        "fallback": settings["fallback_enabled"],
        "slots": None,
    }
    db.insert("sessions", {
        "id": session_id,
        "created_at": db.now(),
        "subject": subject.strip(),
        "title": "",
        "material": material.strip(),
        "config_json": db.dumps(cfg),
        "status": "analyzing",
        "parent_session_id": parent_session_id,
        "current_difficulty": difficulty,
    })
    for pos, uid in enumerate(upload_ids):
        db.insert("session_documents", {"session_id": session_id, "upload_id": uid, "position": pos})
    if subtopics:
        _store_subtopics(session_id, subtopics)
        S.update_session(session_id, status="generating")
    return session_id


def _store_subtopics(session_id: str, subtopics: list[dict[str, str]]) -> None:
    rows = []
    for pos, s in enumerate(subtopics):
        row = {"id": db.new_id(), "session_id": session_id, "name": s["name"].strip(),
               "description": s.get("description", "").strip(), "position": pos}
        db.insert("subtopics", row)
        rows.append(row)
    session = S.get_session(session_id)
    cfg = session["config"]
    cfg["slots"] = plan_slots(cfg["count"], [r["id"] for r in rows], cfg["types"], seed=session_id)
    S.update_session(session_id, config=cfg)


async def analyze(session: dict[str, Any]) -> None:
    ctx = S.call_context(session)
    topic_map: TopicMap = await structured_call(
        ctx,
        purpose="topic_map",
        instruction=TOPIC_MAP_INSTRUCTION,
        schema=TOPIC_MAP_SCHEMA,
        validate=TopicMap.model_validate,
        max_tokens=16000,
    )
    _store_subtopics(session["id"], [s.model_dump() for s in topic_map.subtopics])
    S.update_session(session["id"], title=topic_map.title.strip(), status="generating")


# --- Worker ----------------------------------------------------------------------------

def _questions(session_id: str) -> list[dict[str, Any]]:
    return db.query(
        "SELECT id, slot, difficulty, status, position FROM questions "
        "WHERE session_id = ? AND status != 'discarded' ORDER BY slot, created_at",
        (session_id,),
    )


def needed_requests(session: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = session["config"]
    slots = cfg.get("slots")
    if not slots or session["status"] in ("analyzing", "completed"):
        return []
    rows = _questions(session["id"])
    count = cfg["count"]

    if not cfg["adaptive"]:
        generated = {r["slot"] for r in rows}
        answered = db.query_one("SELECT COUNT(*) AS n FROM answers WHERE session_id = ?", (session["id"],))["n"]
        missing = [i for i in range(count) if i not in generated]
        if missing and len(generated) - answered < config.BATCH_SIZE:
            return [{"slot": i, **slots[i], "difficulty": cfg["difficulty"]} for i in missing[: config.BATCH_SIZE]]
        return []

    served = sorted((r for r in rows if r["status"] == "served"), key=lambda r: r["slot"])
    k = len(served)
    if k >= count:
        return []
    if k == 0:
        diffs = [session["current_difficulty"]]
    else:
        last = served[-1]
        ans = S.load_answer(last["id"])
        if ans and ans["grade_status"] == "done":
            diffs = [next_difficulty(last["difficulty"], ans["verdict"], ans["skipped"])]
        else:
            diffs = candidate_difficulties(last["difficulty"])
    have = {r["difficulty"] for r in rows if r["slot"] == k and r["status"] == "pool"}
    return [{"slot": k, **slots[k], "difficulty": d} for d in diffs if d not in have]


async def generate(session: dict[str, Any], wanted: list[dict[str, Any]]) -> int:
    """Generate questions for `wanted` requests; returns how many were stored."""
    subtopics = S.get_subtopics(session["id"])
    names = {s["id"]: s["name"] for s in subtopics}
    previous = [
        db.loads(r["payload_json"])["prompt"]
        for r in db.query("SELECT payload_json FROM questions WHERE session_id = ? AND status != 'discarded'", (session["id"],))
    ]
    requests = [{"request": i, **w} for i, w in enumerate(wanted)]
    by_request = {r["request"]: r for r in requests}
    instruction = generation_instruction(requests, subtopics, session["config"]["language"], previous)

    def validate(data: dict[str, Any]) -> tuple[dict[int, dict], list[str]]:
        good: dict[int, dict] = {}
        problems: list[str] = []
        for raw in data.get("questions", []):
            try:
                q = parse_question(raw)
            except ValidationError as e:
                problems.append(f"slot {raw.get('slot')}: {e.errors()[0].get('msg', e)}")
                continue
            req = by_request.get(q.slot)
            if req is None or q.type != req["type"] or q.slot in good:
                problems.append(f"slot {q.slot}: expected type {req['type'] if req else '?'}, got {q.type}")
                continue
            good[q.slot] = q.model_dump()
        if not good:
            raise ValueError("; ".join(problems) or "no questions were returned")
        return good, problems

    good, problems = await structured_call(
        S.call_context(session),
        purpose="generate",
        instruction=instruction,
        schema=generation_schema(),
        validate=validate,
        max_tokens=32000,
    )
    if problems:
        log.warning("generation partially invalid for %s: %s", session["id"], problems)

    stored = 0
    for request_no, q in good.items():
        req = by_request[request_no]
        # The answer key is trusted, but the slot metadata comes from our plan, not the model.
        q.update(slot=req["slot"], subtopic_id=req["subtopic_id"], difficulty=req["difficulty"])
        qid = db.new_id()
        db.insert("questions", {
            "id": qid,
            "session_id": session["id"],
            "position": None,
            "slot": req["slot"],
            "subtopic_id": req["subtopic_id"],
            "type": q["type"],
            "difficulty": req["difficulty"],
            "payload_json": db.dumps(q),
            "display_json": db.dumps(build_display(qid, q, names.get(req["subtopic_id"], ""))),
            "status": "pool",
            "created_at": db.now(),
        })
        stored += 1
    return stored


async def _run_worker(session_id: str) -> None:
    try:
        session = S.get_session(session_id)
        if session["status"] == "analyzing":
            await analyze(session)
        stalled = 0
        while True:
            session = S.get_session(session_id)
            wanted = needed_requests(session)
            if not wanted:
                break
            stored = await generate(session, wanted)
            stalled = 0 if stored else stalled + 1
            if stalled >= MAX_STALLED_ROUNDS:
                raise AppError("invalid_output", "Claude couldn't produce valid questions for this material.")
            if session["status"] == "generating":
                S.update_session(session_id, status="ready")
    except AppError as e:
        log.warning("worker for %s stopped: %s (%s)", session_id, e.code, e.detail or e.message)
        S.update_session(session_id, error=e.to_dict())
    except Exception as e:  # noqa: BLE001 - surface anything unexpected to the UI
        log.exception("worker for %s crashed", session_id)
        S.update_session(session_id, error=AppError("server_error", "Question generation failed unexpectedly.", detail=repr(e)).to_dict())


def ensure_worker(session_id: str) -> None:
    task = _workers.get(session_id)
    if task and not task.done():
        return
    session = S.get_session(session_id)
    if session["error"] or session["status"] == "completed":
        return
    _workers[session_id] = asyncio.get_running_loop().create_task(_run_worker(session_id))


def retry(session_id: str) -> None:
    S.update_session(session_id, error=None)
    ensure_worker(session_id)


def stop_worker(session_id: str) -> None:
    task = _workers.pop(session_id, None)
    if task and not task.done():
        task.cancel()


def worker_running(session_id: str) -> bool:
    task = _workers.get(session_id)
    return bool(task and not task.done())


# --- Serving ----------------------------------------------------------------------------

def question_view(row: dict[str, Any], total: int) -> dict[str, Any]:
    display = db.loads(row["display_json"]) if "display_json" in row else row["display"]
    return {"id": row["id"], "position": row["position"], "total": total, **display}


def next_question(session_id: str) -> dict[str, Any]:
    session = S.get_session(session_id)
    cfg = session["config"]
    total = cfg["count"]
    if session["status"] == "completed":
        return {"state": "done"}

    served = db.query(
        "SELECT q.* FROM questions q WHERE q.session_id = ? AND q.status = 'served' ORDER BY q.position",
        (session_id,),
    )
    answered = {r["question_id"] for r in db.query("SELECT question_id FROM answers WHERE session_id = ?", (session_id,))}
    current = [q for q in served if q["id"] not in answered]
    if current:
        return {"state": "question", "question": question_view(current[0], total)}
    k = len(served)
    if k >= total:
        return {"state": "done"}

    candidate = None
    if cfg["adaptive"]:
        target = session["current_difficulty"]
        if k > 0:
            last = served[-1]
            ans = S.load_answer(last["id"])
            if ans is None or ans["grade_status"] == "pending":
                return {"state": "pending", "message": "Grading your answer…"}
            if ans["grade_status"] == "error":
                target = last["difficulty"]
            else:
                target = next_difficulty(last["difficulty"], ans["verdict"], ans["skipped"])
        candidate = db.query_one(
            "SELECT * FROM questions WHERE session_id = ? AND slot = ? AND difficulty = ? AND status = 'pool' LIMIT 1",
            (session_id, k, target),
        )
    else:
        candidate = db.query_one(
            "SELECT * FROM questions WHERE session_id = ? AND slot = ? AND status = 'pool' LIMIT 1",
            (session_id, k),
        )

    if candidate:
        db.update("questions", "id", candidate["id"], {"status": "served", "position": k})
        db.execute(
            "UPDATE questions SET status = 'discarded' WHERE session_id = ? AND slot = ? AND status = 'pool'",
            (session_id, k),
        )
        S.update_session(session_id, current_difficulty=candidate["difficulty"], status="ready")
        candidate["position"] = k
        _kick(session_id)
        return {"state": "question", "question": question_view(candidate, total)}

    _kick(session_id)
    session = S.get_session(session_id)
    if session["error"]:
        return {"state": "error", "error": session["error"]}
    message = "Reading your material and mapping subtopics…" if session["status"] == "analyzing" else "Writing your next questions…"
    return {"state": "pending", "message": message}


def _kick(session_id: str) -> None:
    try:
        ensure_worker(session_id)
    except RuntimeError:  # no running loop (sync test contexts)
        pass
