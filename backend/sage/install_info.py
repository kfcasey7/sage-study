"""How this copy of the app was installed, which decides how it updates.

  installer  the one-step installers: <root>/tools/sage-study is this environment, <root>/sage-install.json the marker
  packaged   a PyInstaller build from a GitHub Release
  source     `uv tool install`, or a developer's checkout"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

MARKER = "sage-install.json"


def load() -> dict[str, Any]:
    if getattr(sys, "frozen", False):
        return {"kind": "packaged"}
    try:
        root = Path(sys.prefix).parents[1]
        info = json.loads((root / MARKER).read_text(encoding="utf-8"))
        return {**info, "kind": "installer", "root": str(root)}
    except (IndexError, OSError, ValueError):
        return {"kind": "source"}
