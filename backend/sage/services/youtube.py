"""Finding YouTube videos for subtopics (playlists) and for quiz questions ("Find video").

Every video shown comes from a real search, and every one is checked with YouTube's oEmbed endpoint
before it is shown. Claude never writes a URL or video ID:

  * With a YouTube Data API key (Settings; kept in the OS credential store): Claude writes search
    queries, the app runs search.list and videos.list (cached in SQLite to save quota), and Claude
    ranks the returned candidates by id. Picks whose id isn't a candidate are rejected.
  * Without a key: one Claude Code CLI call that may use only WebSearch (restricted to youtube.com)
    reports candidates; the app keeps only video ids that appear in the captured search results.

Spare candidates are kept per subtopic so "Replace this video" and "Find more" usually need no
new search."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

from .. import config, db, secrets
from ..errors import AppError
from ..llm_client import CallContext, search_call, structured_call
from ..prompts.videos import (SEARCH_SYSTEM_PROMPT, queries_instruction, rank_instruction,
                              search_instruction)
from ..schemas.questions import STR, arr, obj
from . import linkfetch
from . import sets_core as C

log = logging.getLogger(__name__)
API = "https://www.googleapis.com/youtube/v3"
_tasks: dict[str, asyncio.Task] = {}

# Replaced in tests with a client on an httpx.MockTransport.
def http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=config.LINK_TIMEOUT, follow_redirects=True,
                             headers={"User-Agent": config.BROWSER_USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})


# --- Parsing helpers ------------------------------------------------------------------------------

_ISO = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")
_VIDEO_IN_TEXT = re.compile(r"(?:youtube\.com/watch\?(?:[^\s\"'<>]*?&)?v=|youtu\.be/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})")


def parse_iso_duration(value: str | None) -> int | None:
    """'PT1H2M3S' -> 3723 seconds."""
    m = _ISO.match(value or "")
    if not m or not any(m.groups()):
        return None
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def video_ids_in(texts: list[str]) -> set[str]:
    """Every YouTube video id that appears as a link in search-result text."""
    return {m.group(1) for t in texts for m in _VIDEO_IN_TEXT.finditer(t)}


def thumbnail(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def playlist_url(video_ids: list[str]) -> str | None:
    """A temporary YouTube playlist of these videos (tested: watch_videos redirects to a TL... list)."""
    ids = list(dict.fromkeys(video_ids))[:50]
    return f"https://www.youtube.com/watch_videos?video_ids={','.join(ids)}" if ids else None


# --- Caches ------------------------------------------------------------------------------------------

def _fresh(ts: str, max_age: timedelta) -> bool:
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(ts) < max_age
    except ValueError:
        return False


def _cache_get(key: str) -> Any:
    row = db.query_one("SELECT json, fetched_at FROM yt_cache WHERE key = ?", (key,))
    if row and _fresh(row["fetched_at"], timedelta(days=config.YOUTUBE_CACHE_DAYS)):
        return json.loads(row["json"])
    return None


def _cache_put(key: str, value: Any) -> None:
    db.execute("INSERT INTO yt_cache (key, json, fetched_at) VALUES (?, ?, ?) "
               "ON CONFLICT(key) DO UPDATE SET json = excluded.json, fetched_at = excluded.fetched_at",
               (key, db.dumps(value), db.now()))


# --- YouTube Data API v3 -------------------------------------------------------------------------------

def _api_error(r: httpx.Response) -> AppError:
    try:
        err = r.json().get("error", {})
    except ValueError:
        err = {}
    reasons = {e.get("reason") for e in err.get("errors", [])}
    if reasons & {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}:
        return AppError("youtube_quota", "Your YouTube API key has used today's quota (it resets at midnight Pacific "
                        "time). Remove the key in Settings to search without it until then.")
    if r.status_code in (400, 403) and (reasons & {"keyInvalid", "badRequest", "accessNotConfigured", "forbidden"}
                                        or "API key" in str(err.get("message", ""))):
        return AppError("youtube_key_invalid", "YouTube rejected the API key. Check it in Settings, and make sure "
                        "\"YouTube Data API v3\" is enabled for its Google Cloud project.", detail=str(err.get("message", ""))[:300])
    return AppError("network", f"YouTube search failed (HTTP {r.status_code}).", detail=str(err.get("message", ""))[:300])


async def api_search(client: httpx.AsyncClient, key: str, query: str) -> list[dict[str, Any]]:
    cache_key = f"search:{' '.join(query.lower().split())}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        r = await client.get(f"{API}/search", params={
            "part": "snippet", "type": "video", "q": query, "maxResults": config.YOUTUBE_RESULTS_PER_QUERY,
            "videoEmbeddable": "true", "safeSearch": "moderate", "relevanceLanguage": "en", "key": key})
    except httpx.HTTPError as e:
        raise AppError("network", "Couldn't reach YouTube. Check your internet connection.", detail=repr(e)) from None
    if r.status_code != 200:
        raise _api_error(r)
    out = []
    for item in r.json().get("items", []):
        vid = (item.get("id") or {}).get("videoId")
        sn = item.get("snippet") or {}
        if vid and linkfetch._YT_ID.match(vid):
            out.append({"video_id": vid, "title": sn.get("title", ""), "channel": sn.get("channelTitle", ""),
                        "description": sn.get("description", ""), "published": sn.get("publishedAt", "")})
    _cache_put(cache_key, out)
    return out


async def api_details(client: httpx.AsyncClient, key: str, ids: list[str]) -> dict[str, dict[str, Any]]:
    """Duration, channel, and view count per video id (videos.list, 1 quota unit per 50 ids)."""
    out: dict[str, dict[str, Any]] = {}
    missing = []
    for vid in dict.fromkeys(ids):
        cached = _cache_get(f"video:{vid}")
        if cached is not None:
            out[vid] = cached
        else:
            missing.append(vid)
    for i in range(0, len(missing), 50):
        batch = missing[i:i + 50]
        try:
            r = await client.get(f"{API}/videos", params={"part": "contentDetails,snippet,statistics",
                                                          "id": ",".join(batch), "key": key})
        except httpx.HTTPError as e:
            raise AppError("network", "Couldn't reach YouTube. Check your internet connection.", detail=repr(e)) from None
        if r.status_code != 200:
            raise _api_error(r)
        for item in r.json().get("items", []):
            sn, cd, stats = item.get("snippet") or {}, item.get("contentDetails") or {}, item.get("statistics") or {}
            info = {"title": sn.get("title", ""), "channel": sn.get("channelTitle", ""),
                    "duration_s": parse_iso_duration(cd.get("duration")),
                    "views": int(stats["viewCount"]) if str(stats.get("viewCount", "")).isdigit() else None}
            out[item["id"]] = info
            _cache_put(f"video:{item['id']}", info)
    return out


async def test_key(key: str) -> dict[str, Any]:
    """A 1-unit request to check a key works."""
    async with http_client() as client:
        try:
            r = await client.get(f"{API}/videos", params={"part": "id", "id": "jNQXAC9IVRw", "key": key})
        except httpx.HTTPError as e:
            raise AppError("network", "Couldn't reach YouTube. Check your internet connection.", detail=repr(e)) from None
    if r.status_code != 200:
        raise _api_error(r)
    return {"ok": True}


# --- oEmbed verification ----------------------------------------------------------------------------

async def verify(client: httpx.AsyncClient, video_id: str) -> dict[str, Any] | None:
    """oEmbed data if the video exists and is public, else None (cached for a day)."""
    row = db.query_one("SELECT ok, json, checked_at FROM oembed_cache WHERE video_id = ?", (video_id,))
    if row and _fresh(row["checked_at"], timedelta(hours=config.OEMBED_CACHE_HOURS)):
        return json.loads(row["json"]) if row["ok"] else None
    try:
        r = await client.get("https://www.youtube.com/oembed", params={"url": watch_url(video_id), "format": "json"})
    except httpx.HTTPError:
        return None  # unverifiable right now: don't show it
    ok = r.status_code == 200
    data = None
    if ok:
        try:
            data = r.json()
        except ValueError:
            ok = False
    db.execute("INSERT INTO oembed_cache (video_id, ok, json, checked_at) VALUES (?, ?, ?, ?) "
               "ON CONFLICT(video_id) DO UPDATE SET ok = excluded.ok, json = excluded.json, checked_at = excluded.checked_at",
               (video_id, int(ok), db.dumps(data) if ok else None, db.now()))
    return data if ok else None


async def watch_page_duration(client: httpx.AsyncClient, video_id: str) -> int | None:
    """Best-effort length without an API key, from the watch page's lengthSeconds."""
    cached = _cache_get(f"length:{video_id}")
    if cached is not None:
        return cached or None
    try:
        r = await client.get(watch_url(video_id))
        m = re.search(r'"lengthSeconds":"(\d+)"', r.text) if r.status_code == 200 else None
    except httpx.HTTPError:
        return None
    value = int(m.group(1)) if m else 0
    _cache_put(f"length:{video_id}", value)
    return value or None


# --- Claude calls ----------------------------------------------------------------------------------

QUERIES_SCHEMA = obj({"targets": arr(obj({"key": STR, "queries": arr(STR)}))})
SEARCH_SCHEMA = obj({"targets": arr(obj({"key": STR, "videos": arr(obj({"url": STR, "title": STR, "reason": STR}))}))})
RANK_SCHEMA = obj({"targets": arr(obj({"key": STR, "picks": arr(obj({"video_id": STR, "reason": STR}))}))})


def _context(settings: dict[str, Any] | None = None) -> CallContext:
    s = settings or db.get_settings()
    return CallContext(session_id=None, model_fast=s.get("model_fast", config.DEFAULT_MODEL_FAST),
                       model_smart=s.get("model_smart", config.DEFAULT_MODEL_SMART))


def validate_queries(keys: set[str]) -> Callable[[dict], dict[str, list[str]]]:
    def validate(data: dict) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for t in data.get("targets", []):
            if t.get("key") in keys:
                qs = [" ".join(q.split())[:100] for q in t.get("queries", []) if q.strip()]
                out[t["key"]] = list(dict.fromkeys(qs))[:3]
        missing = keys - {k for k, v in out.items() if v}
        if missing:
            raise ValueError(f"write queries for every target; missing: {sorted(missing)}")
        return out
    return validate


def validate_search(keys: set[str]) -> Callable[[dict, list[str]], dict[str, list[dict[str, str]]]]:
    """Keep only videos whose id appears in the captured WebSearch results."""
    def validate(data: dict, search_results: list[str]) -> dict[str, list[dict[str, str]]]:
        seen = video_ids_in(search_results)
        out: dict[str, list[dict[str, str]]] = {k: [] for k in keys}
        dropped = 0
        for t in data.get("targets", []):
            if t.get("key") not in keys:
                continue
            for v in t.get("videos", []):
                vid = linkfetch.youtube_id(v.get("url", ""))
                if not vid or vid not in seen:
                    dropped += 1
                    continue
                if all(x["video_id"] != vid for x in out[t["key"]]):
                    out[t["key"]].append({"video_id": vid, "title": v.get("title", ""), "reason": v.get("reason", "").strip()})
        if dropped:
            log.warning("dropped %d video(s) not found in the search results", dropped)
        return out
    return validate


def validate_rank(candidates: dict[str, list[dict[str, Any]]]) -> Callable[[dict], dict[str, list[dict[str, str]]]]:
    def validate(data: dict) -> dict[str, list[dict[str, str]]]:
        out: dict[str, list[dict[str, str]]] = {k: [] for k in candidates}
        bad = []
        for t in data.get("targets", []):
            key = t.get("key")
            if key not in candidates:
                continue
            allowed = {c["video_id"] for c in candidates[key]}
            for p in t.get("picks", []):
                vid = p.get("video_id", "").strip()
                if vid not in allowed:
                    bad.append(vid)
                elif all(x["video_id"] != vid for x in out[key]):
                    out[key].append({"video_id": vid, "reason": p.get("reason", "").strip()})
        if bad:
            raise ValueError(f"these video_ids are not in the candidate lists: {bad[:10]}. Use only listed ids.")
        return out
    return validate


# --- Finding videos -------------------------------------------------------------------------------------

async def _candidates_api(client: httpx.AsyncClient, key: str, targets: list[dict[str, Any]], subject: str,
                          exclude: set[str], ctx: CallContext) -> dict[str, list[dict[str, Any]]]:
    queries = await structured_call(ctx, purpose="video_queries", instruction=queries_instruction(targets, subject),
                                    schema=QUERIES_SCHEMA, validate=validate_queries({t["key"] for t in targets}))
    found: dict[str, list[dict[str, Any]]] = {}
    for t in targets:
        merged: dict[str, dict[str, Any]] = {}
        for q in queries[t["key"]][:config.QUERIES_PER_TARGET + 1]:
            for c in await api_search(client, key, q):
                if c["video_id"] not in exclude:
                    merged.setdefault(c["video_id"], c)
        found[t["key"]] = list(merged.values())
    details = await api_details(client, key, [c["video_id"] for cs in found.values() for c in cs])
    for cs in found.values():
        for c in cs:
            c.update({k: v for k, v in details.get(c["video_id"], {}).items() if v not in (None, "")})
    return found


async def _rank(targets: list[dict[str, Any]], candidates: dict[str, list[dict[str, Any]]], picks: int,
                ctx: CallContext) -> dict[str, list[dict[str, Any]]]:
    if not any(candidates.values()):
        return {k: [] for k in candidates}
    ranked = await structured_call(
        ctx, purpose="video_rank", instruction=rank_instruction(targets, candidates, picks), schema=RANK_SCHEMA,
        validate=validate_rank(candidates))
    out = {}
    for key, rows in ranked.items():
        by_id = {c["video_id"]: c for c in candidates[key]}
        out[key] = [{**by_id[r["video_id"]], "reason": r["reason"]} for r in rows]
    return out


async def _candidates_websearch(targets: list[dict[str, Any]], subject: str, exclude: set[str], per_target: int,
                                ctx: CallContext) -> dict[str, list[dict[str, Any]]]:
    """Without an API key: WebSearch-only CLI calls, a few targets per call, run concurrently."""
    groups = [targets[i:i + 4] for i in range(0, len(targets), 4)]

    async def one(group: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        return await search_call(
            ctx, purpose="video_search", instruction=search_instruction(group, subject, per_target, sorted(exclude)[:30]),
            schema=SEARCH_SCHEMA, validate=validate_search({t["key"] for t in group}), system=SEARCH_SYSTEM_PROMPT)

    merged: dict[str, list[dict[str, Any]]] = {}
    for part in await asyncio.gather(*(one(g) for g in groups)):
        for key, vids in part.items():
            merged[key] = [v for v in vids if v["video_id"] not in exclude]
    return merged


async def _finish(client: httpx.AsyncClient, ranked: list[dict[str, Any]], want: int,
                  with_api: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Verify ranked candidates with oEmbed in order until `want` pass. Returns (shown, spares)."""
    shown: list[dict[str, Any]] = []
    i = 0
    while i < len(ranked) and len(shown) < want:
        batch = ranked[i:i + want - len(shown)]
        i += len(batch)
        metas = await asyncio.gather(*(verify(client, c["video_id"]) for c in batch))
        for c, meta in zip(batch, metas):
            if meta is None:
                continue
            # oEmbed is YouTube's own title and channel; web-search titles can be stale or carry " - YouTube".
            title = (c.get("title") if with_api else None) or meta.get("title") or c.get("title", "")
            channel = (c.get("channel") if with_api else None) or meta.get("author_name") or c.get("channel", "")
            c = {**c, "title": re.sub(r"\s+-\s+YouTube$", "", title), "channel": channel, "thumbnail": thumbnail(c["video_id"])}
            if c.get("duration_s") is None and not with_api:
                c["duration_s"] = await watch_page_duration(client, c["video_id"])
            shown.append(c)
    return shown, ranked[i:]


async def find_videos(targets: list[dict[str, Any]], *, subject: str = "", per_target: int = config.VIDEOS_PER_SUBTOPIC,
                      exclude: set[str] | None = None,
                      settings: dict[str, Any] | None = None) -> dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """{target key: (verified videos to show, ranked spares not yet verified)}."""
    exclude = exclude or set()
    ctx = _context(settings)
    key = secrets.get_youtube_key()
    async with http_client() as client:
        if key:
            candidates = await _candidates_api(client, key, targets, subject, exclude, ctx)
            ranked = await _rank(targets, candidates, per_target, ctx)
        else:
            ranked = await _candidates_websearch(targets, subject, exclude, per_target + 3, ctx)
        out = {}
        taken = set(exclude)  # a video is shown under one target only
        for t in targets:
            pool = [c for c in ranked.get(t["key"], []) if c["video_id"] not in taken]
            shown, spares = await _finish(client, pool, per_target, bool(key))
            taken |= {v["video_id"] for v in shown}
            out[t["key"]] = (shown, spares)
    return out


async def next_verified(spares: list[dict[str, Any]], exclude: set[str], want: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Take verified videos from a spares list (no new search)."""
    pool = [s for s in spares if s["video_id"] not in exclude]
    async with http_client() as client:
        return await _finish(client, pool, want, bool(secrets.get_youtube_key()))


def mode() -> str:
    return "api" if secrets.get_youtube_key() else "websearch"


# --- Playlists ----------------------------------------------------------------------------------------

def _items(playlist_id: str) -> list[dict[str, Any]]:
    return db.query("SELECT * FROM playlist_items WHERE playlist_id = ? AND status = 'active' ORDER BY position", (playlist_id,))


def _insert_items(playlist_id: str, subtopic_id: str, videos: list[dict[str, Any]], start_pos: int) -> None:
    for i, v in enumerate(videos):
        db.insert("playlist_items", {
            "id": db.new_id(), "playlist_id": playlist_id, "set_subtopic_id": subtopic_id, "video_id": v["video_id"],
            "title": v.get("title", "")[:300], "channel": v.get("channel", "")[:200], "duration_s": v.get("duration_s"),
            "thumbnail": v.get("thumbnail") or thumbnail(v["video_id"]), "reason": v.get("reason", "")[:400],
            "watched": 0, "position": start_pos + i, "status": "active", "created_at": db.now(),
        })


def _get_playlist(playlist_id: str) -> dict[str, Any]:
    row = db.query_one("SELECT * FROM playlists WHERE id = ?", (playlist_id,))
    if not row:
        raise AppError("not_found", "That playlist no longer exists.")
    row["subtopic_ids"] = db.loads(row.pop("subtopic_ids_json"), [])
    row["spares"] = db.loads(row.pop("spares_json"), {})
    row["error"] = db.loads(row.pop("error_json"), None)
    return row


def _targets(set_id: str, subtopic_ids: list[str]) -> list[dict[str, Any]]:
    subs = {s["id"]: s for s in C.subtopics(set_id, include_removed=True)}
    return [{"key": sid, "title": subs[sid]["name"],
             "description": subs[sid]["summary"] + (f" Key concepts: {', '.join(subs[sid]['key_concepts'])}." if subs[sid]["key_concepts"] else "")}
            for sid in subtopic_ids if sid in subs]


def start_playlist(set_id: str, subtopic_ids: list[str]) -> dict[str, Any]:
    C.get_set(set_id)
    active = {s["id"] for s in C.subtopics(set_id)}
    chosen = [s for s in dict.fromkeys(subtopic_ids) if s in active]
    if not chosen:
        raise AppError("bad_request", "Pick at least one subtopic.")
    pid = db.new_id()
    db.insert("playlists", {"id": pid, "set_id": set_id, "subtopic_ids_json": db.dumps(chosen), "status": "generating",
                            "spares_json": "{}", "created_at": db.now()})
    C.update_set(set_id)
    _tasks[pid] = asyncio.get_running_loop().create_task(_build(pid, set_id, chosen))
    return playlist_view(pid)


async def _build(pid: str, set_id: str, subtopic_ids: list[str]) -> None:
    try:
        st = C.get_set(set_id)
        found = await find_videos(_targets(set_id, subtopic_ids), subject=st["subject"], per_target=config.VIDEOS_PER_SUBTOPIC)
        spares = {}
        pos = 0
        shown_ids = {v["video_id"] for shown, _ in found.values() for v in shown}
        for sid in subtopic_ids:
            shown, rest = found.get(sid, ([], []))
            _insert_items(pid, sid, shown, pos)
            pos += len(shown) + 10
            spares[sid] = [r for r in rest if r["video_id"] not in shown_ids]
        status = "ready" if any(found.get(s, ([], []))[0] for s in subtopic_ids) else "failed"
        err = None if status == "ready" else {"code": "no_videos", "message": "No suitable videos were found. Try again, "
                                              "or add a YouTube API key in Settings for better search results.", "retryable": True}
        db.update("playlists", "id", pid, {"status": status, "spares_json": db.dumps(spares), "error_json": db.dumps(err) if err else None})
    except AppError as e:
        db.update("playlists", "id", pid, {"status": "failed", "error_json": db.dumps(e.to_dict())})
    except Exception as e:  # noqa: BLE001
        log.exception("playlist %s failed", pid)
        db.update("playlists", "id", pid, {"status": "failed", "error_json": db.dumps(
            AppError("server_error", "Building the playlist failed unexpectedly.", detail=repr(e)).to_dict())})
    finally:
        _tasks.pop(pid, None)


def _running(pid: str) -> bool:
    t = _tasks.get(pid)
    return bool(t and not t.done())


def playlist_view(pid: str) -> dict[str, Any]:
    p = _get_playlist(pid)
    if p["status"] == "generating" and not _running(pid):
        err = {"code": "interrupted", "message": "Building the playlist was interrupted. Try again.", "retryable": True}
        db.update("playlists", "id", pid, {"status": "failed", "error_json": db.dumps(err)})
        p = _get_playlist(pid)
    st = C.get_set(p["set_id"])
    subs = {s["id"]: s for s in C.subtopics(p["set_id"], include_removed=True)}
    items = _items(pid)
    groups = []
    for sid in p["subtopic_ids"]:
        vids = [{"id": i["id"], "video_id": i["video_id"], "title": i["title"], "channel": i["channel"],
                 "duration_s": i["duration_s"], "thumbnail": i["thumbnail"], "reason": i["reason"],
                 "watched": bool(i["watched"]), "url": watch_url(i["video_id"])} for i in items if i["set_subtopic_id"] == sid]
        groups.append({"subtopic_id": sid, "name": subs[sid]["name"] if sid in subs else "Removed subtopic",
                       "videos": vids, "spares_left": len(p["spares"].get(sid, []))})
    all_ids = [i["video_id"] for i in items]
    return {"id": pid, "set_id": p["set_id"], "set_title": st["title"], "status": p["status"], "error": p["error"],
            "created_at": p["created_at"], "groups": groups, "youtube_playlist_url": playlist_url(all_ids),
            "busy": _running(pid), "mode": mode()}


def set_playlists(set_id: str) -> list[dict[str, Any]]:
    out = []
    for p in db.query("SELECT id, status, created_at, subtopic_ids_json FROM playlists WHERE set_id = ? ORDER BY created_at DESC", (set_id,)):
        counts = db.query_one("SELECT COUNT(*) AS n, SUM(watched) AS w FROM playlist_items WHERE playlist_id = ? AND status = 'active'", (p["id"],))
        subs = {s["id"]: s["name"] for s in C.subtopics(set_id, include_removed=True)}
        out.append({"id": p["id"], "status": p["status"] if p["status"] != "generating" or _running(p["id"]) else "failed",
                    "created_at": p["created_at"], "videos": counts["n"] or 0, "watched": counts["w"] or 0,
                    "subtopics": [subs.get(s, "") for s in db.loads(p["subtopic_ids_json"], [])]})
    return out


def set_watched(item_id: str, watched: bool) -> dict[str, Any]:
    if not db.query_one("SELECT 1 FROM playlist_items WHERE id = ?", (item_id,)):
        raise AppError("not_found", "That video is no longer in the playlist.")
    db.update("playlist_items", "id", item_id, {"watched": int(watched)})
    return {"ok": True, "watched": watched}


async def _more_for(pid: str, sid: str, want: int) -> list[dict[str, Any]]:
    """Up to `want` new verified videos for a subtopic: spares first, then a fresh search."""
    p = _get_playlist(pid)
    used = {r["video_id"] for r in db.query("SELECT video_id FROM playlist_items WHERE playlist_id = ?", (pid,))}
    spares = p["spares"].get(sid, [])
    got, rest = await next_verified(spares, used, want)
    if len(got) < want:
        st = C.get_set(p["set_id"])
        found = await find_videos(_targets(p["set_id"], [sid]), subject=st["subject"], per_target=want - len(got),
                                  exclude=used | {g["video_id"] for g in got})
        new, new_rest = found.get(sid, ([], []))
        got += new
        rest = rest + new_rest
    p = _get_playlist(pid)
    p["spares"][sid] = [r for r in rest if r["video_id"] not in {g["video_id"] for g in got}]
    db.update("playlists", "id", pid, {"spares_json": db.dumps(p["spares"])})
    return got


async def replace_item(item_id: str) -> dict[str, Any]:
    item = db.query_one("SELECT * FROM playlist_items WHERE id = ?", (item_id,))
    if not item or item["status"] != "active":
        raise AppError("not_found", "That video is no longer in the playlist.")
    got = await _more_for(item["playlist_id"], item["set_subtopic_id"], 1)
    if not got:
        raise AppError("no_videos", "No other suitable video was found for this subtopic.")
    db.update("playlist_items", "id", item_id, {"status": "replaced"})
    _insert_items(item["playlist_id"], item["set_subtopic_id"], got, item["position"])
    return playlist_view(item["playlist_id"])


async def more_for_subtopic(pid: str, sid: str) -> dict[str, Any]:
    p = _get_playlist(pid)
    if sid not in p["subtopic_ids"]:
        raise AppError("not_found", "That subtopic isn't part of this playlist.")
    got = await _more_for(pid, sid, config.VIDEOS_PER_SUBTOPIC)
    if not got:
        raise AppError("no_videos", "No more suitable videos were found for this subtopic.")
    last = db.query_one("SELECT COALESCE(MAX(position), 0) AS p FROM playlist_items WHERE playlist_id = ? AND set_subtopic_id = ?",
                        (pid, sid))["p"]
    _insert_items(pid, sid, got, last + 1)
    return playlist_view(pid)


def delete_playlist(pid: str) -> None:
    _get_playlist(pid)
    db.execute("DELETE FROM playlist_items WHERE playlist_id = ?", (pid,))
    db.execute("DELETE FROM playlists WHERE id = ?", (pid,))


# --- "Find video" during a quiz ---------------------------------------------------------------------------

def _video_out(v: dict[str, Any]) -> dict[str, Any]:
    return {"video_id": v["video_id"], "title": v.get("title", ""), "channel": v.get("channel", ""),
            "duration_s": v.get("duration_s"), "thumbnail": v.get("thumbnail") or thumbnail(v["video_id"]),
            "reason": v.get("reason", ""), "url": watch_url(v["video_id"])}


def question_videos(question_id: str) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM question_videos WHERE question_id = ?", (question_id,))
    if not row:
        return None
    return {"videos": db.loads(row["videos_json"], []), "used_before_answer": bool(row["before_answer"])}


async def find_for_question(question_id: str) -> dict[str, Any]:
    from . import sessions as S

    existing = question_videos(question_id)
    if existing is not None and existing["videos"]:
        return existing
    q = S.load_question(question_id)
    session = S.get_session(q["session_id"])
    answered = S.load_answer(question_id) is not None
    sub = db.query_one("SELECT name, description FROM subtopics WHERE id = ?", (q["subtopic_id"],)) or {"name": "", "description": ""}
    # The question as the student sees it (never the answer key), plus its subtopic.
    prompt = re.sub(r"\s+", " ", q["display"].get("prompt", ""))[:600]
    target = {"key": "q", "title": sub["name"] or "this question",
              "description": f"{sub['description']} The student is working on this question: {prompt}"}
    found = await find_videos([target], subject=session["subject"], per_target=config.VIDEOS_PER_QUESTION)
    shown, _ = found.get("q", ([], []))
    videos = [_video_out(v) for v in shown]
    if not videos:
        raise AppError("no_videos", "No suitable videos were found for this question. Try again in a moment.")
    db.execute("INSERT INTO question_videos (question_id, session_id, videos_json, before_answer, created_at) "
               "VALUES (?, ?, ?, ?, ?) ON CONFLICT(question_id) DO UPDATE SET videos_json = excluded.videos_json",
               (question_id, q["session_id"], db.dumps(videos), int(not answered), db.now()))
    return {"videos": videos, "used_before_answer": not answered}
