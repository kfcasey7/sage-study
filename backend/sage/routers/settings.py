from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from .. import config, db, install_info, llm_client, runtime
from ..errors import AppError

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    model_fast: str | None = None
    model_smart: str | None = None
    feedback_mode: Literal["immediate", "end"] | None = None
    theme: Literal["light", "dark"] | None = None
    quiz_prefs: dict | None = None
    setup_complete: bool | None = None
    update_check: bool | None = None


def first_run() -> bool:
    """The wizard shows once, and never for someone who has already been using the app."""
    return not db.get_settings()["setup_complete"] and db.query_one("SELECT 1 FROM study_sets LIMIT 1") is None


def _payload() -> dict:
    return {
        "settings": db.get_settings(),
        "options": {
            "models": config.MODELS,
            "difficulty_levels": config.DIFFICULTY_LEVELS,
            "question_types": config.QUESTION_TYPES,
            "code_languages": config.CODE_LANGUAGES,
            "report_reasons": config.REPORT_REASONS,
            "question_counts": config.QUESTION_COUNTS,
            "max_questions": config.MAX_QUESTIONS,
            "max_file_mb": config.MAX_FILE_MB,
            "extensions": sorted(config.SUPPORTED_EXTENSIONS),
        },
        "app": {
            "name": config.APP_NAME, "version": config.VERSION, "data_dir": str(config.DATA_DIR),
            "repo_url": config.REPO_URL, "install_docs_url": config.CLAUDE_CODE_DOCS_URL,
            "install_kind": install_info.load()["kind"], "first_run": first_run(),
            "window_mode": runtime.window_mode, "fallback_reason": runtime.fallback_reason,
            "heartbeat_seconds": config.BROWSER_HEARTBEAT_SECONDS,
        },
    }


@router.get("")
def get_settings() -> dict:
    return _payload()


@router.put("")
def update_settings(body: SettingsUpdate) -> dict:
    values = body.model_dump(exclude_none=True)
    for key in ("model_fast", "model_smart"):
        if key in values and values[key] not in config.MODEL_IDS:
            raise AppError("bad_request", f"Unknown model '{values[key]}'.")
    db.set_settings(values)
    return _payload()


@router.get("/cli-status")
async def cli_status(refresh: bool = False) -> dict:
    """Is the Claude Code CLI installed and logged in?"""
    return await llm_client.cli_status(refresh=refresh)
