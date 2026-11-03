"""Print the CHANGELOG section for a tag, with the download instructions every release page needs.

    python scripts/release_notes.py v1.0.0
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FOOTER = """
---

**Which download?** Windows: `SageStudy-Setup-*.exe`. Mac with Apple silicon (M1 or newer): `*-macos-arm64.zip`. Older Intel Mac: `*-macos-intel.zip`. Linux: `*-linux-x64.tar.gz`.

These builds aren't code-signed, so Windows and macOS show a warning the first time. [INSTALL.md](https://github.com/kfcasey7/sage-study/blob/main/INSTALL.md) explains exactly what you'll see and how to get past it.

You also need your own Claude Code and a Claude plan that includes it. Sage Study is unofficial and isn't affiliated with or endorsed by Anthropic.
"""


def section(tag: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    version = tag.lstrip("v")
    m = re.search(rf"^## \[?{re.escape(version)}\]?.*?\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m:
        raise SystemExit(f"CHANGELOG.md has no section for {version}")
    return m.group(1).strip()


if __name__ == "__main__":
    print(section(sys.argv[1]) + "\n" + FOOTER)
