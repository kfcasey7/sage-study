from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from .. import claude_client, config, db, keystore
from ..errors import AppError

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    model: str | None = None
    effort: Literal["low", "medium", "high"] | None = None
    feedback_mode: Literal["immediate", "end"] | None = None
    theme: Literal["light", "dark"] | None = None
    fallback_enabled: bool | None = None


class KeyIn(BaseModel):
    api_key: str


def _payload() -> dict:
    return {
        "settings": db.get_settings(),
        "key": keystore.key_status(),
        "options": {
            "models": config.MODELS,
            "efforts": config.EFFORT_LEVELS,
            "difficulty_levels": config.DIFFICULTY_LEVELS,
            "question_types": config.QUESTION_TYPES,
            "code_languages": config.CODE_LANGUAGES,
            "question_counts": config.QUESTION_COUNTS,
            "max_questions": config.MAX_QUESTIONS,
            "max_file_mb": config.MAX_FILE_MB,
            "extensions": sorted(config.SUPPORTED_EXTENSIONS),
            "pricing": config.PRICING,
        },
        "app": {"name": config.APP_NAME, "version": config.VERSION, "data_dir": str(config.DATA_DIR)},
    }


@router.get("")
def get_settings() -> dict:
    return _payload()


@router.put("")
def update_settings(body: SettingsUpdate) -> dict:
    values = body.model_dump(exclude_none=True)
    if "model" in values and values["model"] not in {m["id"] for m in config.MODELS}:
        raise AppError("bad_request", "Unknown model.")
    db.set_settings(values)
    return _payload()


@router.put("/api-key")
async def set_key(body: KeyIn) -> dict:
    key = body.api_key.strip()
    if not key.startswith("sk-ant-") or len(key) < 20:
        raise AppError("invalid_key", "That doesn't look like an Anthropic API key. Keys start with 'sk-ant-'.")
    previous, source = keystore.get_api_key()
    keystore.set_api_key(key)
    try:
        await claude_client.check_key(db.get_settings()["model"])
    except AppError as e:
        if e.code in ("invalid_key", "permission_denied"):
            # Don't keep a key we know is bad; restore whatever was stored before.
            if previous and source == "keyring":
                keystore.set_api_key(previous)
            else:
                keystore.delete_api_key()
            raise
        # Network trouble etc.: keep the key, but tell the user it wasn't verified.
        return {**_payload(), "warning": f"Key saved, but it couldn't be verified: {e.message}"}
    return _payload()


@router.delete("/api-key")
def delete_key() -> dict:
    keystore.delete_api_key()
    return _payload()


@router.post("/test-key")
async def test_key() -> dict:
    await claude_client.check_key(db.get_settings()["model"])
    return {"ok": True, "key": keystore.key_status()}
