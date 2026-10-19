"""Study Set sources: uploaded files and pasted links.

A source belongs to a set, or (while you're still on the setup screen) to a draft. Identical files
(same bytes) and identical links (same normalized URL, same YouTube video, same Google file) are
added only once per set or draft. Links are read in the background; a link that can't be read is
marked "Couldn't read" with the reason and never blocks the rest of the set."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import config, db, ingest
from ..errors import AppError
from . import linkfetch

log = logging.getLogger(__name__)
_tasks: dict[str, asyncio.Task] = {}
_fetch_slots: asyncio.Semaphore | None = None


def _sem() -> asyncio.Semaphore:
    global _fetch_slots
    if _fetch_slots is None:
        _fetch_slots = asyncio.Semaphore(3)
    return _fetch_slots


def view(row: dict[str, Any], label: str | None = None) -> dict[str, Any]:
    upload = db.query_one("SELECT kind, char_count, size FROM uploads WHERE id = ?", (row["upload_id"],)) if row.get("upload_id") else None
    return {
        "id": row["id"], "kind": row["kind"], "source_type": row["source_type"], "url": row["url"],
        "title": row["title"], "status": row["status"], "error": db.loads(row["error_json"], None),
        "label": label, "content_kind": upload["kind"] if upload else None,
        "char_count": upload["char_count"] if upload else None, "size": upload["size"] if upload else None,
        "created_at": row["created_at"],
    }


def _get(source_id: str) -> dict[str, Any]:
    row = db.query_one("SELECT * FROM sources WHERE id = ?", (source_id,))
    if not row:
        raise AppError("not_found", "That source no longer exists.")
    return row


def _scope(set_id: str | None, draft_id: str | None) -> tuple[str, list[Any]]:
    if set_id:
        return "set_id = ?", [set_id]
    if draft_id:
        return "set_id IS NULL AND draft_id = ?", [draft_id]
    raise AppError("bad_request", "A source must belong to a study set or a draft.")


def _existing(set_id: str | None, draft_id: str | None, key: str) -> dict[str, Any] | None:
    where, params = _scope(set_id, draft_id)
    return db.query_one(f"SELECT * FROM sources WHERE {where} AND dedupe_key = ?", [*params, key])


def _next_position(set_id: str | None, draft_id: str | None) -> int:
    where, params = _scope(set_id, draft_id)
    return (db.query_one(f"SELECT COALESCE(MAX(position), -1) AS p FROM sources WHERE {where}", params) or {"p": -1})["p"] + 1


def set_sources(set_id: str) -> list[dict[str, Any]]:
    return db.query("SELECT * FROM sources WHERE set_id = ? ORDER BY position", (set_id,))


def labels(set_id: str) -> dict[str, str]:
    """S1, S2, ... by position, over every source in the set (stable as long as none are removed)."""
    return {r["id"]: f"S{i}" for i, r in enumerate(set_sources(set_id), 1)}


def set_views(set_id: str) -> list[dict[str, Any]]:
    lab = labels(set_id)
    return [view(r, lab[r["id"]]) for r in set_sources(set_id)]


# --- Files ------------------------------------------------------------------------------------

def add_file(filename: str, data: bytes, *, set_id: str | None = None, draft_id: str | None = None) -> dict[str, Any]:
    key = f"sha256:{hashlib.sha256(data).hexdigest()}"
    dup = _existing(set_id, draft_id, key)
    if dup:
        return {**view(dup), "duplicate": True}
    up = ingest.save_upload(filename, data)  # raises AppError for unsupported/empty/too-large files
    row = {
        "id": db.new_id(), "set_id": set_id, "draft_id": draft_id, "kind": "file", "source_type": up["source_type"],
        "url": None, "title": up["filename"], "upload_id": up["id"], "dedupe_key": key, "status": "ready",
        "error_json": None, "position": _next_position(set_id, draft_id), "created_at": db.now(),
    }
    db.insert("sources", row)
    return {**view(row), "duplicate": False}


# --- Links ------------------------------------------------------------------------------------

def add_links(urls: list[str], *, set_id: str | None = None, draft_id: str | None = None) -> list[dict[str, Any]]:
    urls = [u for u in (u.strip() for u in urls) if u]
    if not urls:
        raise AppError("bad_request", "Paste at least one link.")
    if len(urls) > config.MAX_LINKS_PER_REQUEST:
        raise AppError("bad_request", f"Add at most {config.MAX_LINKS_PER_REQUEST} links at a time.")
    out = []
    for raw in urls:
        try:
            url = linkfetch.clean_url(raw)
        except linkfetch.LinkError as e:
            out.append({"id": None, "url": raw, "status": "failed", "error": {"code": "bad_link", "message": str(e)},
                        "duplicate": False, "kind": "link", "title": raw})
            continue
        key = linkfetch.dedupe_key(url)
        dup = _existing(set_id, draft_id, key)
        if dup:
            out.append({**view(dup), "duplicate": True})
            continue
        vid = linkfetch.youtube_id(url)
        g = linkfetch.google_file(url)
        stype = "youtube" if vid else (g[0] if g and g[0] != "gdrive" else "web")
        row = {
            "id": db.new_id(), "set_id": set_id, "draft_id": draft_id, "kind": "link", "source_type": stype,
            "url": url, "title": url, "upload_id": None, "dedupe_key": key, "status": "processing",
            "error_json": None, "position": _next_position(set_id, draft_id), "created_at": db.now(),
        }
        db.insert("sources", row)
        _start(row["id"])
        out.append({**view(row), "duplicate": False})
    return out


def _start(source_id: str) -> None:
    task = _tasks.get(source_id)
    if task and not task.done():
        return
    try:
        _tasks[source_id] = asyncio.get_running_loop().create_task(process_link(source_id))
    except RuntimeError:  # no running loop (sync callers); processed on the next view
        pass


async def process_link(source_id: str) -> None:
    row = _get(source_id)
    try:
        async with _sem():
            fetched = await linkfetch.fetch_link(row["url"])
        if fetched.file_bytes is not None:
            up = await asyncio.to_thread(ingest.save_upload, fetched.filename or "document", fetched.file_bytes)
            upload_id = up["id"]
        else:
            up = await asyncio.to_thread(ingest.save_text_upload, fetched.title, fetched.text or "", "text")
            upload_id = up["id"]
        if not db.query_one("SELECT 1 FROM sources WHERE id = ?", (source_id,)):
            ingest.delete_upload(upload_id)  # removed while it was being read
            return
        db.update("sources", "id", source_id, {"status": "ready", "upload_id": upload_id, "error_json": None,
                                               "title": fetched.title[:300], "source_type": fetched.source_type})
    except linkfetch.LinkError as e:
        db.update("sources", "id", source_id, {"status": "failed", "error_json": db.dumps(
            {"code": "link_unreadable", "message": str(e), "retryable": False})})
    except AppError as e:  # e.g. a linked PDF that is password-protected
        db.update("sources", "id", source_id, {"status": "failed", "error_json": db.dumps(e.to_dict())})
    except Exception as e:  # noqa: BLE001
        log.exception("reading link %s failed", row["url"])
        db.update("sources", "id", source_id, {"status": "failed", "error_json": db.dumps(
            {"code": "link_unreadable", "message": "Something went wrong reading this link.", "detail": repr(e),
             "retryable": True})})
    finally:
        _tasks.pop(source_id, None)


def resume_processing(rows: list[dict[str, Any]]) -> None:
    """Restart reading links left 'processing' by an app restart."""
    for r in rows:
        if r["status"] == "processing" and not (_tasks.get(r["id"]) and not _tasks[r["id"]].done()):
            _start(r["id"])


async def wait_for_set(set_id: str, timeout: float = 180) -> None:
    """Wait until no source in the set is still being read."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        rows = [r for r in set_sources(set_id) if r["status"] == "processing"]
        if not rows:
            return
        resume_processing(rows)
        if asyncio.get_running_loop().time() > deadline:
            for r in rows:
                db.update("sources", "id", r["id"], {"status": "failed", "error_json": db.dumps(
                    {"code": "link_unreadable", "message": "Reading this link took too long.", "retryable": True})})
            return
        await asyncio.sleep(0.25)


def get_many(ids: list[str]) -> list[dict[str, Any]]:
    rows = [r for r in (db.query_one("SELECT * FROM sources WHERE id = ?", (i,)) for i in ids) if r]
    resume_processing(rows)
    return [view(r) for r in rows]


def retry(source_id: str) -> dict[str, Any]:
    row = _get(source_id)
    if row["kind"] != "link" or row["status"] != "failed":
        raise AppError("conflict", "Only links that couldn't be read can be retried.")
    db.update("sources", "id", source_id, {"status": "processing", "error_json": None})
    _start(source_id)
    return view(_get(source_id))


# --- Attaching & removing ----------------------------------------------------------------------

def attach(set_id: str, source_ids: list[str]) -> list[str]:
    """Move setup-screen (or another draft's) sources into a set, dropping ones the set already has.
    Returns the ids actually attached."""
    attached = []
    pos = _next_position(set_id, None)
    for sid in source_ids:
        row = db.query_one("SELECT * FROM sources WHERE id = ?", (sid,))
        if not row:
            continue
        if row["set_id"] == set_id:
            attached.append(sid)
            continue
        if row["set_id"] is not None:
            raise AppError("conflict", "That source belongs to another study set.")
        if _existing(set_id, None, row["dedupe_key"]):
            remove(sid)
            continue
        db.update("sources", "id", sid, {"set_id": set_id, "draft_id": None, "position": pos})
        pos += 1
        attached.append(sid)
    return attached


def remove(source_id: str) -> None:
    row = db.query_one("SELECT * FROM sources WHERE id = ?", (source_id,))
    if not row:
        return
    task = _tasks.pop(source_id, None)
    if task and not task.done():
        task.cancel()
    db.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    if row["upload_id"]:
        ingest.delete_upload(row["upload_id"])  # kept if a quiz still uses it


def cleanup_unattached() -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=config.UNATTACHED_SOURCE_DAYS)).isoformat(timespec="seconds")
    for r in db.query("SELECT id FROM sources WHERE set_id IS NULL AND created_at < ?", (cutoff,)):
        remove(r["id"])
