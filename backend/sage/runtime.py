"""Runtime state shared between the launcher and the API (the port is only known at startup)."""
from __future__ import annotations

from . import config

port: int = config.PREFERRED_PORT


def server_url() -> str:
    return f"http://127.0.0.1:{port}"
