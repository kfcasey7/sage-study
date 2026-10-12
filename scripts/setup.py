"""One-shot setup: virtual environment, Python dependencies, frontend build, icons, desktop shortcut.

    python scripts/setup.py                 # everything
    python scripts/setup.py --no-shortcut   # skip the shortcut
    python scripts/setup.py --skip-frontend # reuse an existing frontend/dist build

Run via setup.ps1 (Windows) or setup.sh (macOS/Linux), which find a suitable Python first.
"""
from __future__ import annotations

import argparse
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

    print("\nSetup complete. Launch Sage Study from the desktop shortcut, then add your API key in Settings.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        print(f"\nSetup failed while running: {' '.join(map(str, e.cmd))}")
        sys.exit(1)
