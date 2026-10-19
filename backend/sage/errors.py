"""Application errors with stable codes the frontend maps to friendly messages."""
from __future__ import annotations

from typing import Any

STATUS_FOR_CODE = {
    "cli_missing": 503,
    "not_logged_in": 401,
    "usage_limit": 429,
    "cli_error": 502,
    "not_found": 404,
    "overloaded": 503,
    "server_error": 502,
    "network": 503,
    "timeout": 504,
    "refusal": 422,
    "truncated": 502,
    "invalid_output": 502,
    "unsupported_file": 415,
    "file_too_large": 413,
    "missing_file": 410,
    "bad_request": 400,
    "conflict": 409,
    "no_videos": 404,
    "youtube_quota": 429,
    "youtube_key_invalid": 400,
}


class AppError(Exception):
    def __init__(self, code: str, message: str, *, retry_after: float | None = None, detail: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.detail = detail

    @property
    def status(self) -> int:
        return STATUS_FOR_CODE.get(self.code, 500)

    @property
    def retryable(self) -> bool:
        return self.code in {"usage_limit", "overloaded", "server_error", "network", "timeout", "truncated",
                             "invalid_output", "cli_error", "not_logged_in", "cli_missing", "no_videos"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retry_after": self.retry_after,
            "retryable": self.retryable,
            "detail": self.detail,
        }
