from __future__ import annotations

import webbrowser
from urllib.parse import urlparse

from fastapi import APIRouter
from pydantic import BaseModel

from .. import secrets
from ..errors import AppError
from ..services import youtube

router = APIRouter(prefix="/api", tags=["videos"])


@router.get("/playlists/{playlist_id}")
def get_playlist(playlist_id: str) -> dict:
    return youtube.playlist_view(playlist_id)


@router.delete("/playlists/{playlist_id}")
def delete_playlist(playlist_id: str) -> dict:
    youtube.delete_playlist(playlist_id)
    return {"ok": True}


class WatchedIn(BaseModel):
    watched: bool


@router.put("/playlist-items/{item_id}")
def set_watched(item_id: str, body: WatchedIn) -> dict:
    return youtube.set_watched(item_id, body.watched)


@router.post("/playlist-items/{item_id}/replace")
async def replace(item_id: str) -> dict:
    return await youtube.replace_item(item_id)


class MoreIn(BaseModel):
    subtopic_id: str


@router.post("/playlists/{playlist_id}/more")
async def more(playlist_id: str, body: MoreIn) -> dict:
    return await youtube.more_for_subtopic(playlist_id, body.subtopic_id)


@router.get("/questions/{question_id}/videos")
def get_question_videos(question_id: str) -> dict:
    return youtube.question_videos(question_id) or {"videos": [], "used_before_answer": False}


@router.post("/questions/{question_id}/videos")
async def find_question_videos(question_id: str) -> dict:
    """'Find video': 1-3 videos on the concept behind this question. Opening it before answering is
    recorded as 'used help' (shown on the results screen; the grade is unchanged)."""
    return await youtube.find_for_question(question_id)


# --- YouTube API key ------------------------------------------------------------------------------------

class KeyIn(BaseModel):
    key: str


@router.get("/settings/youtube-key")
def key_status() -> dict:
    return {**secrets.youtube_key_status(), "mode": youtube.mode()}


@router.put("/settings/youtube-key")
async def save_key(body: KeyIn) -> dict:
    key = body.key.strip()
    if len(key) < 20 or " " in key:
        raise AppError("bad_request", "That doesn't look like a YouTube API key (they're about 39 characters, starting with \"AIza\").")
    await youtube.test_key(key)
    secrets.set_youtube_key(key)
    return {**secrets.youtube_key_status(), "mode": youtube.mode()}


@router.delete("/settings/youtube-key")
def delete_key() -> dict:
    secrets.delete_youtube_key()
    return {**secrets.youtube_key_status(), "mode": youtube.mode()}


@router.post("/settings/youtube-key/test")
async def test_saved_key() -> dict:
    key = secrets.get_youtube_key()
    if not key:
        raise AppError("bad_request", "No YouTube API key is saved.")
    return await youtube.test_key(key)


# --- Opening videos in the default browser ------------------------------------------------------------------

class UrlIn(BaseModel):
    url: str


YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtube-nocookie.com"}


@router.post("/open-url")
def open_url(body: UrlIn) -> dict:
    """Open a YouTube link, or a link you added as a source, in the default browser."""
    from .. import db

    p = urlparse(body.url)
    youtube = p.scheme == "https" and (p.hostname or "").lower() in YOUTUBE_HOSTS
    own_source = p.scheme in ("http", "https") and db.query_one("SELECT 1 FROM sources WHERE url = ?", (body.url,)) is not None
    if not (youtube or own_source):
        raise AppError("bad_request", "Only YouTube links and links you added as sources can be opened from here.")
    return {"ok": bool(webbrowser.open(body.url))}
