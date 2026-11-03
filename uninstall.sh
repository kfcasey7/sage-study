#!/bin/sh
# Removes Sage Study: the app, its environment, and its shortcuts. Asks before deleting your study data.
#
#   --delete-data / --keep-data   answer the question up front
#
# SAGE_INSTALL_ROOT relocates the install folder (used by the tests).
set -eu

APP_NAME="Sage Study"
CHOICE=""
for arg in "$@"; do
    case "$arg" in
        --delete-data) CHOICE="delete" ;;
        --keep-data) CHOICE="keep" ;;
        *) echo "Unknown option: $arg"; exit 2 ;;
    esac
done

if [ "$(uname -s)" = "Darwin" ]; then
    DEFAULT_ROOT="$HOME/Library/Application Support/SageStudy-App"
else
    DEFAULT_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/sage-study-app"
fi
ROOT="${SAGE_INSTALL_ROOT:-$DEFAULT_ROOT}"
PYTHON="$ROOT/tools/sage-study/bin/python"

if [ ! -d "$ROOT" ]; then
    echo "$APP_NAME isn't installed here, so there's nothing to remove."
    exit 0
fi

echo "Removing $APP_NAME..."
pkill -f "$ROOT/tools" 2>/dev/null || true
sleep 1

# The data folder: the one chosen at install time, otherwise wherever the app says its default is.
CUSTOM_DATA=""
DATA_DIR=""
if [ -x "$PYTHON" ]; then
    CUSTOM_DATA=$("$PYTHON" -c "import json,sys; print(json.load(open(sys.argv[1], encoding='utf-8')).get('data_dir') or '')" "$ROOT/sage-install.json" 2>/dev/null || true)
    DATA_DIR="$CUSTOM_DATA"
    [ -n "$DATA_DIR" ] || DATA_DIR=$("$PYTHON" -m sage.cli --print-data-dir | tail -n 1)
    "$PYTHON" -m sage.shortcuts remove >/dev/null
fi

if [ -z "$CHOICE" ] && [ -n "$DATA_DIR" ] && [ -d "$DATA_DIR" ]; then
    echo ""
    echo "Your study data (quizzes, study guides, uploaded files) is in:"
    echo "   $DATA_DIR"
    printf 'Delete it too? This can'"'"'t be undone. Type yes to delete, or press Enter to keep it: '
    read -r answer || answer=""
    [ "$answer" = "yes" ] && CHOICE="delete" || CHOICE="keep"
fi

# Only the default data folder owns the saved YouTube key.
if [ "$CHOICE" = "delete" ] && [ -z "$CUSTOM_DATA" ] && [ -x "$PYTHON" ]; then
    "$PYTHON" -m sage.cli --forget-youtube-key >/dev/null 2>&1 || true
fi

cd "$HOME"
rm -rf "$ROOT"

if [ "$CHOICE" = "delete" ] && [ -n "$DATA_DIR" ]; then
    rm -rf "$DATA_DIR"
    echo "Removed $APP_NAME and your study data."
else
    echo "Removed $APP_NAME."
    if [ -n "$DATA_DIR" ] && [ -d "$DATA_DIR" ]; then
        echo "Your study data is still in: $DATA_DIR"
    fi
fi
