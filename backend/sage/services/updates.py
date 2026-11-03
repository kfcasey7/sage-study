"""Looks for a newer release on GitHub when the user asks or on launch (it can be turned off in Settings).
Nothing is sent except the request itself, nothing updates without a click, and the app has no telemetry."""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any

import httpx

from .. import config, desktop, install_info
from ..errors import AppError

log = logging.getLogger(__name__)

TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
RELEASE_PAGE = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+/releases/")
API_URL = f"https://api.github.com/repos/{config.GITHUB_REPO}/releases/latest"
NOTES_MAX_CHARS = 20_000

_cache: tuple[float, dict[str, Any]] | None = None


def _version(tag: str) -> tuple[int, int, int] | None:
    m = TAG.match(tag)
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def _current() -> tuple[int, int, int]:
    return _version(f"v{config.VERSION}") or (0, 0, 0)


def http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=10, headers={"Accept": "application/vnd.github+json", "User-Agent": config.LINK_USER_AGENT})


def manual_command(tag: str) -> str:
    return f"uv tool install --force git+{config.REPO_URL}@{tag}"


async def check(force: bool = False) -> dict[str, Any]:
    """{"status": "current" | "available" | "unknown", ...}. A failed check only means no banner."""
    global _cache
    if _cache and not force and time.time() - _cache[0] < config.UPDATE_CACHE_HOURS * 3600:
        return _cache[1]
    kind = install_info.load()["kind"]
    result: dict[str, Any] = {"status": "unknown", "current": config.VERSION, "latest": None, "notes": "", "url": f"{config.REPO_URL}/releases",
                              "install_kind": kind, "can_self_update": kind == "installer", "command": None}
    try:
        async with http_client() as client:
            r = await client.get(API_URL)
        if r.status_code == 200:
            data = r.json()
            latest = _version(str(data.get("tag_name") or ""))
            if latest:
                result.update(status="available" if latest > _current() else "current", latest=data["tag_name"],
                              notes=str(data.get("body") or "")[:NOTES_MAX_CHARS])
                if RELEASE_PAGE.match(str(data.get("html_url") or "")):
                    result["url"] = data["html_url"]
                if kind == "source":
                    result["command"] = manual_command(data["tag_name"])
        elif r.status_code == 404:
            result["status"] = "current"  # no release has been published yet
    except (httpx.HTTPError, ValueError) as e:
        log.info("update check failed: %s", e)
    if result["status"] != "unknown":
        _cache = (time.time(), result)
    return result


def _spawn_updater(info: dict[str, Any], tag: str) -> None:
    """Hand over to a script outside this environment: it waits for the app to close, installs the release's
    own installer over this one (keeping the data folder), and starts the app again."""
    root = Path(info["root"])
    data_dir = os.environ.get("SAGE_DATA_DIR") or ""
    pid = str(os.getpid())
    if sys.platform == "win32":
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(root / "update.ps1"), "-Tag", tag, "-WaitPid", pid]
        if data_dir:
            args += ["-DataDir", data_dir]
        # A hidden console: PowerShell quits without running the script under DETACHED_PROCESS. Leaving the launcher's
        # job keeps Windows from ending the updater along with the app.
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            subprocess.Popen(args, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, close_fds=True, cwd=root)
        except OSError:  # the job doesn't allow leaving, so there's nothing to leave
            subprocess.Popen(args, creationflags=flags, close_fds=True, cwd=root)
    else:
        subprocess.Popen(["/bin/sh", str(root / "update.sh"), tag, pid, data_dir], start_new_session=True, close_fds=True, cwd=root,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def apply() -> dict[str, Any]:
    """The tag comes from GitHub's answer, re-checked here, never from the request."""
    state = await check()
    if state["status"] != "available" or not _version(state["latest"] or ""):
        raise AppError("conflict", "There's no newer version to install right now.")
    info = install_info.load()
    if info["kind"] == "installer":
        _spawn_updater(info, state["latest"])
        desktop.request_quit()
        return {"action": "updating"}
    if info["kind"] == "packaged":
        webbrowser.open(state["url"])
        return {"action": "opened_download_page", "url": state["url"]}
    return {"action": "manual", "command": state["command"], "url": state["url"]}
