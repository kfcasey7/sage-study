#!/usr/bin/env bash
# Sage Study setup for macOS / Linux. Usage: ./setup.sh [--no-shortcut] [--skip-frontend]
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for candidate in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$candidate"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "Python 3.11 or newer was not found. Install it (https://www.python.org/downloads/) and run setup again." >&2
  exit 1
fi

# Linux: pywebview needs a GUI backend (GTK via PyGObject, or Qt). See README if the window doesn't open.
exec "$PY" scripts/setup.py "$@"
