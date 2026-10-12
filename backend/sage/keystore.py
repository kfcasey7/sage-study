"""API key storage in the OS credential store (keyring), with ANTHROPIC_API_KEY as a fallback.
The key never leaves the backend: callers outside this module only ever see `key_status()`."""
from __future__ import annotations

import logging
import os

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from . import config

log = logging.getLogger(__name__)


def _from_keyring() -> str | None:
    try:
        return keyring.get_password(config.KEYRING_SERVICE, config.KEYRING_USER) or None
    except KeyringError as e:  # no backend available (e.g. headless Linux without a secret service)
        log.warning("keyring unavailable: %s", e)
        return None


def get_api_key() -> tuple[str | None, str]:
    """Returns (key, source) where source is 'keyring', 'env', or 'none'."""
    key = _from_keyring()
    if key:
        return key, "keyring"
    env = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env:
        return env, "env"
    return None, "none"


def set_api_key(key: str) -> None:
    keyring.set_password(config.KEYRING_SERVICE, config.KEYRING_USER, key.strip())


def delete_api_key() -> None:
    try:
        keyring.delete_password(config.KEYRING_SERVICE, config.KEYRING_USER)
    except PasswordDeleteError:
        pass


def key_status() -> dict:
    key, source = get_api_key()
    return {
        "key_set": key is not None,
        "source": source,
        "last4": key[-4:] if key else None,
    }
