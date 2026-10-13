"""Session creation, topic mapping, the background question-generation worker, and the question queue.

The plan (`config.slots`) has one entry per question the student will answer: {subtopic_id, type}, or
None for a slot removed when the question count was lowered. New slots are served in order; questions
the student skips go to the end (`config.deferred_slots`, in skip order) and come back after every new
slot has been served.

Non-adaptive sessions: a small first batch (FIRST_BATCH) so the student can start quickly, then batches
of BATCH_SIZE generated in the background, keeping POOL_AHEAD unanswered questions ready. Adaptive
sessions: while a question is on screen (or being graded), the worker prefetches one candidate for the
next slot at every difficulty the answer could lead to, in a single call; the matching candidate is
served and the rest discarded. The adaptive level (`sessions.current_difficulty`) moves when an answer
is graded, so skipping a question doesn't change it.

Question options (types, difficulty, adaptive, count, language) can be changed mid-session. Answered
questions and the one on screen are kept; upcoming and skipped questions that no longer fit are
discarded and rewritten for their slot."""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from pydantic import ValidationError

from .. import config, db
from ..errors import AppError
from ..llm_client import structured_call
from ..prompts.generate import generation_instruction
from ..prompts.topic_map import TOPIC_MAP_INSTRUCTION
from ..schemas.guide import TOPIC_MAP_SCHEMA, TopicMap
from ..schemas.questions import generation_schema, parse_question
from . import sessions as S
from .mastery import candidate_difficulties, plan_slots
from .presentation import build_display

log = logging.getLogger(__name__)

_workers: dict[str, asyncio.Task] = {}
MAX_STALLED_ROUNDS = 2
CODE_TYPES = {"code", "error_analysis"}


# --- Validation shared by creation and option changes ----------------------------------

def _clean_options(types: list[str], difficulty: int, count: int, language: str) -> list[str]:
    types = [t for t in config.QUESTION_TYPE_IDS if t in set(types)]
    if not types:
        raise AppError("bad_request", "Pick at least one question type.")
    if not 1 <= difficulty <= 5:
        raise AppError("bad_request", "Difficulty must be between 1 and 5.")
    if not 1 <= count <= config.MAX_QUESTIONS:
        raise AppError("bad_request", f"Choose between 1 and {config.MAX_QUESTIONS} questions.")
    if language and language not in config.CODE_LANGUAGES:
        raise AppError("bad_request", f"Unsupported code language '{language}'.")
    return types


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
    types = _clean_options(types, difficulty, count, language)
    if not material.strip() and not upload_ids:
        raise AppError("bad_request", "Describe what to cover or upload at least one document.")
    for uid in upload_ids:
        if not db.query_one("SELECT 1 FROM uploads WHERE id = ?", (uid,)):
            raise AppError("missing_file", "One of the uploaded files is no longer available. Remove it and upload it again.")

    session_id = db.new_id()
    doc_chars = sum(
        (db.query_one("SELECT char_count FROM uploads WHERE id = ?", (uid,)) or {}).get("char_count") or 0
        for uid in upload_ids
    )
    cfg = {
        "types": types,
        "difficulty": difficulty,
        "adaptive": adaptive,
        "count": count,
        "language": language or "Python",
        "feedback_mode": settings["feedback_mode"],
        "model_fast": settings["model_fast"],
        "model_smart": settings["model_smart"],
        # Longer than one call can hold: each call gets the most relevant excerpts (shown in the UI).
        "docs_truncated": doc_chars > config.DOC_CHAR_BUDGET,
        "doc_chars": doc_chars,
        "slots": None,
        "deferred_slots": [],
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
        focus=session["material"],
    )
    _store_subtopics(session["id"], [s.model_dump() for s in topic_map.subtopics])
    S.update_session(session["id"], title=topic_map.title.strip(), status="generating")


# --- Queue state -------------------------------------------------------------------------

def _questions(session_id: str) -> list[dict[str, Any]]:
    """Live (not discarded) questions with the fields the queue logic needs."""
    rows = db.query(
        "SELECT id, slot, type, difficulty, status, position, payload_json, deferred_count FROM questions "
        "WHERE session_id = ? AND status != 'discarded' ORDER BY slot, created_at",
        (session_id,),
    )
    for r in rows:
        r["language"] = (db.loads(r.pop("payload_json")) or {}).get("language", "")
    return rows


def queue_state(session: dict[str, Any], rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cfg = session["config"]
    rows = _questions(session["id"]) if rows is None else rows
    plan = cfg.get("slots") or []
    active = [i for i, s in enumerate(plan) if s]
    served = {r["slot"] for r in rows if r["status"] == "served"}
    deferred = [s for s in cfg.get("deferred_slots", []) if s not in served and s < len(plan) and plan[s]]
    deferred_set = set(deferred)
    new = [i for i in active if i not in served and i not in deferred_set]
    has_question = {r["slot"] for r in rows if r["status"] in ("pool", "deferred")}
    return {"rows": rows, "plan": plan, "served": served, "new": new, "deferred": deferred, "has_question": has_question}


def _awaiting_answer(session_id: str) -> bool:
    """True while a question is on screen or an answer is still being graded."""
    row = db.query_one(
        "SELECT "
        " (SELECT COUNT(*) FROM questions q WHERE q.session_id = ? AND q.status = 'served' "
        "   AND q.id NOT IN (SELECT question_id FROM answers WHERE session_id = ?)) AS current,"
        " (SELECT COUNT(*) FROM answers WHERE session_id = ? AND grade_status = 'pending') AS grading",
        (session_id, session_id, session_id),
    )
    return bool(row and (row["current"] or row["grading"]))


def _request(plan: list, slot: int, difficulty: int) -> dict[str, Any]:
    return {"slot": slot, **plan[slot], "difficulty": difficulty}


def needed_requests(session: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = session["config"]
    if not cfg.get("slots") or session["status"] in ("analyzing", "completed"):
        return []
    q = queue_state(session)
    plan, rows = q["plan"], q["rows"]

    if not cfg["adaptive"]:
        upcoming = q["new"] + q["deferred"]
        missing = [i for i in upcoming if i not in q["has_question"]]
        ready = len(upcoming) - len(missing)
        if missing and ready < config.POOL_AHEAD:
            size = config.FIRST_BATCH if not rows else config.BATCH_SIZE
            return [_request(plan, i, cfg["difficulty"]) for i in missing[:size]]
        return []

    level = session["current_difficulty"]
    if q["new"]:
        k = q["new"][0]
        diffs = candidate_difficulties(level) if _awaiting_answer(session["id"]) else [level]
        have = {r["difficulty"] for r in rows if r["slot"] == k and r["status"] == "pool"}
        return [_request(plan, k, d) for d in diffs if d not in have]
    # Only skipped questions remain: rewrite any that were discarded after an options change.
    missing = [i for i in q["deferred"] if i not in q["has_question"]]
    return [_request(plan, missing[0], level)] if missing else []


# --- Generation --------------------------------------------------------------------------

def _still_wanted(cfg: dict[str, Any], req: dict[str, Any]) -> bool:
    """Generated questions are stored only if the plan didn't change while Claude was writing them."""
    plan = cfg.get("slots") or []
    slot = req["slot"]
    if slot >= len(plan) or not plan[slot] or plan[slot]["type"] != req["type"]:
        return False
    return cfg["adaptive"] or req["difficulty"] == cfg["difficulty"]


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

    wanted_subs = {r["subtopic_id"] for r in requests}
    focus = " ".join(f'{s["name"]} {s["description"]}' for s in subtopics if s["id"] in wanted_subs)
    good, problems = await structured_call(
        S.call_context(session),
        purpose="generate",
        instruction=instruction,
        schema=generation_schema(sorted({r["type"] for r in requests})),
        validate=validate,
        focus=focus,
    )
    if problems:
        log.warning("generation partially invalid for %s: %s", session["id"], problems)

    cfg_now = S.get_session(session["id"])["config"]
    stored = 0
    for request_no, q in good.items():
        req = by_request[request_no]
        if not _still_wanted(cfg_now, req):
            stored += 1  # not a failure: the options changed mid-call
            continue
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


def _kick(session_id: str) -> None:
    try:
        ensure_worker(session_id)
    except RuntimeError:  # no running loop (sync test contexts)
        pass


# --- Serving ------------------------------------------------------------------------------

def question_view(row: dict[str, Any], total: int) -> dict[str, Any]:
    display = db.loads(row["display_json"]) if "display_json" in row else row["display"]
    return {"id": row["id"], "position": row["position"], "total": total,
            "was_skipped": bool(row.get("deferred_count")), **display}


def _serve(session_id: str, question: dict[str, Any]) -> dict[str, Any]:
    position = db.query_one(
        "SELECT COUNT(*) AS n FROM questions WHERE session_id = ? AND status = 'served'", (session_id,))["n"]
    db.update("questions", "id", question["id"], {"status": "served", "position": position})
    # Other candidates for the same slot (adaptive prefetch) are no longer needed.
    db.execute("UPDATE questions SET status = 'discarded' WHERE session_id = ? AND slot = ? AND status = 'pool'",
               (session_id, question["slot"]))
    question["position"] = position
    return question


def next_question(session_id: str) -> dict[str, Any]:
    session = S.get_session(session_id)
    cfg = session["config"]
    total = cfg["count"]
    if session["status"] == "completed":
        return {"state": "done"}

    current = db.query_one(
        "SELECT * FROM questions WHERE session_id = ? AND status = 'served' "
        "AND id NOT IN (SELECT question_id FROM answers WHERE session_id = ?) ORDER BY position LIMIT 1",
        (session_id, session_id),
    )
    if current:
        return {"state": "question", "question": question_view(current, total)}
    if not cfg.get("slots"):
        return _pending(session_id)

    q = queue_state(session)
    if not q["new"] and not q["deferred"]:
        return {"state": "done"}

    chosen = None
    if q["new"]:
        k = q["new"][0]
        if cfg["adaptive"]:
            if db.query_one("SELECT 1 FROM answers WHERE session_id = ? AND grade_status = 'pending'", (session_id,)):
                return {"state": "pending", "message": "Grading your answer…"}
            chosen = db.query_one(
                "SELECT * FROM questions WHERE session_id = ? AND slot = ? AND difficulty = ? AND status = 'pool' LIMIT 1",
                (session_id, k, session["current_difficulty"]),
            )
        else:
            chosen = db.query_one("SELECT * FROM questions WHERE session_id = ? AND slot = ? AND status = 'pool' LIMIT 1",
                                  (session_id, k))
    else:
        # Every new question has been served: bring skipped ones back, oldest skip first.
        for slot in q["deferred"]:
            chosen = db.query_one(
                "SELECT * FROM questions WHERE session_id = ? AND slot = ? AND status IN ('deferred', 'pool') "
                "ORDER BY status = 'deferred' DESC, created_at LIMIT 1",
                (session_id, slot),
            )
            if chosen:
                cfg["deferred_slots"] = [s for s in cfg.get("deferred_slots", []) if s != slot]
                S.update_session(session_id, config=cfg)
                if not chosen["deferred_count"]:  # a rewrite of a skipped question: still show it as skipped earlier
                    chosen["deferred_count"] = 1
                    db.update("questions", "id", chosen["id"], {"deferred_count": 1})
                break

    if chosen:
        _serve(session_id, chosen)
        S.update_session(session_id, status="ready")
        _kick(session_id)
        return {"state": "question", "question": question_view(chosen, total)}
    return _pending(session_id)


def _pending(session_id: str) -> dict[str, Any]:
    _kick(session_id)
    session = S.get_session(session_id)
    if session["error"]:
        return {"state": "error", "error": session["error"]}
    message = "Reading your material and mapping subtopics…" if session["status"] == "analyzing" else "Writing your next questions…"
    return {"state": "pending", "message": message}


def defer_question(question_id: str) -> dict[str, Any]:
    """'Skip for now': put the on-screen question at the end of the quiz."""
    row = db.query_one("SELECT * FROM questions WHERE id = ?", (question_id,))
    if not row:
        raise AppError("not_found", "Question not found.")
    if row["status"] != "served" or db.query_one("SELECT 1 FROM answers WHERE question_id = ?", (question_id,)):
        raise AppError("conflict", "Only the question on screen can be skipped.")
    session = S.get_session(row["session_id"])
    if session["status"] == "completed":
        raise AppError("conflict", "This session is already finished.")
    cfg = session["config"]
    answered = db.query_one("SELECT COUNT(*) AS n FROM answers WHERE session_id = ?", (session["id"],))["n"]
    if cfg["count"] - answered <= 1:
        raise AppError("conflict", "This is the last question, so there's nothing to skip ahead to. Answer it or choose \"I don't know\".")
    db.update("questions", "id", question_id,
              {"status": "deferred", "position": None, "deferred_count": (row["deferred_count"] or 0) + 1})
    cfg["deferred_slots"] = [s for s in cfg.get("deferred_slots", []) if s != row["slot"]] + [row["slot"]]
    S.update_session(session["id"], config=cfg)
    _kick(session["id"])
    return {"ok": True, "skipped_waiting": len(cfg["deferred_slots"])}


# --- Changing question options mid-session -------------------------------------------------

def _fits(row: dict[str, Any], cfg: dict[str, Any], reset_level: bool) -> bool:
    """Does an upcoming (pool) or skipped (deferred) question still match the session's options?"""
    if row["type"] not in cfg["types"]:
        return False
    if row["type"] in CODE_TYPES and row.get("language") and row["language"] != cfg["language"]:
        return False
    if not cfg["adaptive"]:
        return row["difficulty"] == cfg["difficulty"]
    # Adaptive: prefetched candidates are tied to the old level; skipped questions keep theirs unless
    # the level was reset.
    return not (reset_level and (row["status"] == "pool" or row["difficulty"] != cfg["difficulty"]))


def update_options(session_id: str, *, types: list[str], difficulty: int, adaptive: bool, count: int,
                   language: str, feedback_mode: str) -> dict[str, Any]:
    session = S.get_session(session_id)
    if session["status"] == "completed":
        raise AppError("conflict", "This session is finished, so its options can't be changed. Start a retest instead.")
    types = _clean_options(types, difficulty, count, language)
    if feedback_mode not in ("immediate", "end"):
        raise AppError("bad_request", "Unknown feedback mode.")
    cfg = session["config"]
    answered = db.query_one("SELECT COUNT(*) AS n FROM answers WHERE session_id = ?", (session_id,))["n"]
    on_screen = 1 if _awaiting_on_screen(session_id) else 0
    if count < answered + on_screen:
        raise AppError("bad_request", f"You've already answered {answered} question{'s' if answered != 1 else ''}"
                       f"{' and one is on screen' if on_screen else ''}, so the total can't be lower than {answered + on_screen}.")

    reset_level = adaptive != cfg["adaptive"] or difficulty != cfg["difficulty"]
    cfg.update(types=types, difficulty=difficulty, adaptive=adaptive, count=count, language=language or "Python",
               feedback_mode=feedback_mode)
    if reset_level and adaptive:
        S.update_session(session_id, current_difficulty=difficulty)

    if cfg.get("slots"):
        _replan(session_id, cfg, reset_level)
    S.update_session(session_id, config=cfg, error=None)
    _kick(session_id)
    return S.get_session(session_id)


def _awaiting_on_screen(session_id: str) -> bool:
    return bool(db.query_one(
        "SELECT 1 FROM questions WHERE session_id = ? AND status = 'served' "
        "AND id NOT IN (SELECT question_id FROM answers WHERE session_id = ?)", (session_id, session_id)))


def _replan(session_id: str, cfg: dict[str, Any], reset_level: bool) -> None:
    """Fit the slot plan to new options without touching answered or on-screen questions."""
    plan: list = cfg["slots"]
    rows = _questions(session_id)
    served = {r["slot"] for r in rows if r["status"] == "served"}

    # 1. Drop upcoming/skipped questions that no longer fit.
    keep_slots: set[int] = set()
    for r in rows:
        if r["status"] in ("pool", "deferred"):
            if _fits(r, cfg, reset_level):
                keep_slots.add(r["slot"])
            else:
                db.update("questions", "id", r["id"], {"status": "discarded"})

    # 2. Slots without a usable question keep their subtopic but take a type from the new set.
    rng = random.Random(f"{session_id}-{len(plan)}-{','.join(cfg['types'])}")
    cycle: list[str] = []
    for i, entry in enumerate(plan):
        if not entry or i in served or i in keep_slots or entry["type"] in cfg["types"]:
            continue
        if not cycle:
            cycle = list(cfg["types"])
            rng.shuffle(cycle)
        plan[i] = {**entry, "type": cycle.pop()}

    # 3. Match the number of slots to the new count.
    active = [i for i, s in enumerate(plan) if s]
    deferred = [s for s in cfg.get("deferred_slots", []) if s in active and s not in served]
    if cfg["count"] > len(active):
        subs = [s["id"] for s in S.get_subtopics(session_id)]
        plan.extend(plan_slots(cfg["count"] - len(active), subs, cfg["types"], seed=f"{session_id}-{len(plan)}"))
    elif cfg["count"] < len(active):
        unserved_new = [i for i in active if i not in served and i not in deferred]
        # Remove empty upcoming slots first, then ones with a question ready, then skipped ones (newest skip first).
        order = ([i for i in reversed(unserved_new) if i not in keep_slots]
                 + [i for i in reversed(unserved_new) if i in keep_slots]
                 + list(reversed(deferred)))
        for i in order[: len(active) - cfg["count"]]:
            plan[i] = None
            db.execute("UPDATE questions SET status = 'discarded' WHERE session_id = ? AND slot = ? AND status IN ('pool', 'deferred')",
                       (session_id, i))
    cfg["slots"] = plan
    cfg["deferred_slots"] = [s for s in cfg.get("deferred_slots", []) if s < len(plan) and plan[s] and s not in served]
