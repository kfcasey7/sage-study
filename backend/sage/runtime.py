"""Runtime state shared between the launcher and the API (only known once the app has started)."""
from __future__ import annotations

import secrets
import time


port: int = 0
auth_required: bool = True                # False only under `python -m sage.dev`
token: str = secrets.token_urlsafe(32)    # new every launch; see app.py
window_mode: str = "window"               # window | browser
fallback_reason: str | None = None        # why the native window couldn't start
last_heartbeat: float = time.monotonic()  # browser mode: when the tab last checked in
stop_requested: bool = False


def server_url() -> str:
    return f"http://127.0.0.1:{port}"


def launch_url() -> str:
    """Opening this signs the window or browser in to this launch (see app.py)."""
    return f"{server_url()}/launch?token={token}"


def cookie_name() -> str:
    # Browsers share cookies across ports on one host, so the port keeps two running copies apart.
    return f"sage_session_{port}"
