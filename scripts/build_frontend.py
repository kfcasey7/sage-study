"""Build the React UI into backend/sage/web, the prebuilt copy that ships with the app so end users never need
Node. Run this and commit the result whenever the frontend changes.

    python scripts/build_frontend.py           # npm ci + build, then record what it was built from
    python scripts/build_frontend.py --check   # fail if the frontend changed since the last build (for CI)
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
STAMP = ROOT / "backend" / "sage" / "web" / ".source-hash"
INPUTS = ["src", "public", "index.html", "package-lock.json", "package.json", "tsconfig.json", "vite.config.ts"]


def source_hash() -> str:
    h = hashlib.sha256()
    for name in INPUTS:
        path = FRONTEND / name
        for f in sorted(path.rglob("*")) if path.is_dir() else [path]:
            if f.is_file():
                h.update(f.relative_to(FRONTEND).as_posix().encode())
                h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        built = STAMP.read_text().strip() if STAMP.exists() else ""
        if built != source_hash():
            print("backend/sage/web is out of date: run `python scripts/build_frontend.py` and commit the result.")
            return 1
        print("backend/sage/web matches the frontend source.")
        return 0
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        print("npm wasn't found. Building the UI needs Node.js (only developers need this).")
        return 1
    subprocess.run([npm, "ci", "--no-fund", "--no-audit"], cwd=FRONTEND, check=True)
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)
    STAMP.write_text(source_hash() + "\n")
    print(f"Built {STAMP.parent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
