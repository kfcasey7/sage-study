"""The YouTube Data API key, kept in the operating system's credential store (Windows Credential
Manager / macOS Keychain / Secret Service) via keyring. It never goes to the frontend; settings only
report whether a key is set and its last four characters."""
from __future__ import annotations

import logging

from . import config
from .errors import AppError

log = logging.getLogger(__name__)


def _keyring():
    import keyring

    return keyring


def get_youtube_key() -> str | None:
    try:
        return _keyring().get_password(config.KEYRING_SERVICE, config.KEYRING_YOUTUBE) or None
    except Exception as e:  # noqa: BLE001 - no usable keyring backend: behave as if no key is set
        log.warning("keyring unavailable: %s", e)
        return None


def set_youtube_key(key: str) -> None:
    try:
        _keyring().set_password(config.KEYRING_SERVICE, config.KEYRING_YOUTUBE, key)
    except Exception as e:  # noqa: BLE001
        raise AppError("server_error", "Couldn't save the key in your system's credential store.", detail=repr(e)) from e


def delete_youtube_key() -> None:
    try:
        _keyring().delete_password(config.KEYRING_SERVICE, config.KEYRING_YOUTUBE)
    except Exception:  # noqa: BLE001 - already gone
        pass


def youtube_key_status() -> dict:
    key = get_youtube_key()
    return {"set": bool(key), "last4": key[-4:] if key else None}
