"""One-shot setup: virtual environment, Python dependencies, frontend build, icons, desktop shortcut,
and a check that the Claude Code CLI is installed and logged in (all AI calls go through it).

    python scripts/setup.py                 # everything
    python scripts/setup.py --no-shortcut   # skip the shortcut
    python scripts/setup.py --skip-frontend # reuse an existing frontend/dist build

Run via setup.ps1 (Windows) or setup.sh (macOS/Linux), which find a suitable Python first.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
FRONTEND = ROOT / "frontend"


def step(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def run(cmd: list[str], cwd: Path = ROOT) -> None:
    print("   $", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def find_claude() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    exe = "claude.exe" if sys.platform == "win32" else "claude"
    for c in (Path.home() / ".local" / "bin" / exe, Path.home() / ".claude" / "local" / exe,
              Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd", Path("/usr/local/bin/claude"),
              Path("/opt/homebrew/bin/claude")):
        if c.is_file():
            return str(c)
    return None


LOGIN_HELP = """
   To finish setting up Claude Code:
     1. Open a terminal and run:  claude
     2. Log in with your Claude Pro account (type /login if it doesn't prompt you).
     3. Quit Claude Code (/exit). Sage Study will then work, with no API key needed.
"""


def check_claude_code() -> bool:
    """Report whether the Claude Code CLI is installed and logged in. Never fails setup."""
    cli = find_claude()
    if not cli:
        print("   Claude Code was NOT found on your PATH.")
        print("   Install it from https://claude.com/claude-code (or: npm install -g @anthropic-ai/claude-code)")
        print(LOGIN_HELP)
        return False
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("ANTHROPIC_")}
    try:
        version = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=30, env=env).stdout.strip()
        out = subprocess.run([cli, "auth", "status", "--json"], capture_output=True, text=True, timeout=30, env=env).stdout
        info = json.loads(out) if out.strip().startswith("{") else {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"   Found {cli}, but couldn't check its login status ({e}).")
        print(LOGIN_HELP)
        return False
    print(f"   Found Claude Code {version} at {cli}")
    if not info.get("loggedIn"):
        print("   Claude Code is installed but NOT logged in.")
        print(LOGIN_HELP)
        return False
    plan = info.get("subscriptionType") or "unknown"
    print(f"   Logged in via {info.get('authMethod')} ({plan} plan). Ready.")
    if info.get("authMethod") not in ("claude.ai", "oauth", "subscription"):
        print("   Note: this login isn't a Claude subscription. Run `claude auth login` to use your Pro account.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-shortcut", action="store_true")
    parser.add_argument("--skip-frontend", action="store_true")
    args = parser.parse_args()

    if sys.version_info < (3, 11):
        print(f"Python 3.11+ is required (this is {sys.version.split()[0]}).")
        return 1

    step("Creating virtual environment (.venv)")
    if not venv_python().exists():
        venv.EnvBuilder(with_pip=True).create(VENV)
    else:
        print("   already exists")
    py = str(venv_python())

    step("Installing Python dependencies")
    run([py, "-m", "pip", "install", "--upgrade", "pip", "--quiet"])
    run([py, "-m", "pip", "install", "-r", "requirements.txt", "--quiet"])

    step("Generating app icons")
    run([py, "scripts/make_icons.py"])

    if not args.skip_frontend:
        step("Building the frontend")
        npm = shutil.which("npm") or shutil.which("npm.cmd")
        if not npm:
            print("   Node.js (npm) wasn't found. Install the LTS version from https://nodejs.org and run setup again.")
            return 1
        run([npm, "ci" if (FRONTEND / "package-lock.json").exists() else "install", "--no-fund", "--no-audit"], cwd=FRONTEND)
        run([npm, "run", "build"], cwd=FRONTEND)

    if not args.no_shortcut:
        step("Creating the desktop shortcut")
        run([py, "scripts/create_shortcut.py"])

    step("Checking Claude Code (used for all AI features)")
    ready = check_claude_code()

    print("\nSetup complete. Launch Sage Study from the desktop shortcut.")
    if not ready:
        print("AI features will work once Claude Code is installed and logged in (see above).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        print(f"\nSetup failed while running: {' '.join(map(str, e.cmd))}")
        sys.exit(1)
