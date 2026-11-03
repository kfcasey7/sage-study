"""Settings > Diagnostics. Every field is listed explicitly: nothing from `claude auth status` other than the
fields below (it also returns the account's email and organization), no log text, no study content."""
from __future__ import annotations

import platform
import sqlite3
import sys
from pathlib import Path

from fastapi import APIRouter

from .. import config, install_info, llm_client, runtime

router = APIRouter(prefix="/api", tags=["diagnostics"])


def _anonymized(path: str | None) -> str:
    """Home folders usually contain the person's name."""
    if not path:
        return "(none)"
    try:
        home = str(Path.home())
    except RuntimeError:
        return path
    return "~" + path[len(home):] if path.lower().startswith(home.lower()) else path


def _schema_version() -> int | str:
    try:
        conn = sqlite3.connect(config.DB_PATH)
        try:
            return conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return "unreadable"


@router.get("/diagnostics")
async def diagnostics() -> dict:
    cli = await llm_client.cli_status(refresh=True)
    items = [
        ("App version", config.VERSION),
        ("Install type", install_info.load()["kind"]),
        ("Window", runtime.window_mode + (f" ({runtime.fallback_reason})" if runtime.fallback_reason else "")),
        ("Operating system", f"{platform.system()} {platform.release()} ({platform.version()}), {platform.machine()}"),
        ("Python version", sys.version.split()[0]),
        ("Claude Code installed", "yes" if cli["installed"] else "no"),
        ("Claude Code version", cli["version"] or "(unknown)"),
        ("Claude Code location", _anonymized(cli["path"])),
        ("Logged in to Claude Code", "yes" if cli["logged_in"] else "no"),
        ("Sign-in type", cli["auth_method"] or "(unknown)"),
        ("Plan type", cli["subscription"] or "(unknown)"),
        ("Data folder", _anonymized(str(config.DATA_DIR))),
        ("Database version", str(_schema_version())),
    ]
    report = "\n".join([f"{config.APP_NAME} diagnostic report", *(f"{label}: {value}" for label, value in items)])
    return {"items": [{"label": label, "value": value} for label, value in items], "report": report, "data_dir": str(config.DATA_DIR)}
