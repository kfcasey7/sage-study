#!/bin/sh
# Sage Study installer for macOS and Linux (on a Mac, double-click Install.command). Safe to run again: running it again
# repairs the app.
#
# Everything goes in one folder of its own: a private copy of uv, the Python it provides, and the app. Your PATH, any
# Python you already have, and any uv you already have stay untouched. Your study data is kept elsewhere and never touched.
#
#   --data-dir FOLDER   keep study data in this folder instead of the default
#   --no-launch         don't open the app afterwards
#
# It also works without downloading the project first:  curl -fsSL <raw URL of this file> | sh
# SAGE_INSTALL_ROOT relocates the install folder and SAGE_INSTALL_NONINTERACTIVE=1 skips prompts (used by the tests).
set -eu

UV_VERSION="0.13.6"
PYTHON_VERSION="3.13"
APP_NAME="Sage Study"
GITHUB_REPO="kfcasey7/sage-study"

DATA_DIR=""
LAUNCH=1
while [ $# -gt 0 ]; do
    case "$1" in
        --data-dir) DATA_DIR="$2"; shift 2 ;;
        --no-launch) LAUNCH=0; shift ;;
        *) echo "Unknown option: $1"; exit 2 ;;
    esac
done

if [ "$(uname -s)" = "Darwin" ]; then
    DEFAULT_ROOT="$HOME/Library/Application Support/SageStudy-App"
else
    DEFAULT_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/sage-study-app"
fi
ROOT="${SAGE_INSTALL_ROOT:-$DEFAULT_ROOT}"
BIN="$ROOT/bin"
UV="$BIN/uv"
ENV_BIN="$ROOT/tools/sage-study/bin"

say() { printf '%s\n' "$1"; }
step() { printf '\n==> %s\n' "$1"; }
fail() {
    printf '\nThe install did not finish: %s\n' "$1"
    say "Your study data wasn't touched. Check your internet connection and run this again."
    say "If it keeps failing, see the Troubleshooting section of README.md."
    exit 1
}

download() {  # url destination
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$1" -o "$2"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$2" "$1"
    else
        fail "this computer has neither curl nor wget, and one of them is needed to download the app."
    fi
}

# Run from a pipe, without the project next to this script: fetch the newest release first.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || pwd)
if [ -f "$SCRIPT_DIR/constraints.txt" ] && [ -f "$SCRIPT_DIR/backend/sage/__init__.py" ]; then
    SOURCE="$SCRIPT_DIR"
    WORK=""
else
    WORK=$(mktemp -d)
    trap 'rm -rf "$WORK"' EXIT
    step "Downloading the newest release of $APP_NAME"
    LATEST=$(curl -fsSLI -o /dev/null -w '%{url_effective}' "https://github.com/$GITHUB_REPO/releases/latest" 2>/dev/null | sed -n 's#.*/tag/\(v[0-9.]*\)$#\1#p' || true)
    if [ -n "$LATEST" ]; then
        ARCHIVE="https://github.com/$GITHUB_REPO/archive/refs/tags/$LATEST.tar.gz"
    else
        ARCHIVE="https://github.com/$GITHUB_REPO/archive/refs/heads/main.tar.gz"
    fi
    download "$ARCHIVE" "$WORK/source.tar.gz" || fail "the download failed."
    tar -xzf "$WORK/source.tar.gz" -C "$WORK" || fail "the download was damaged."
    SOURCE=$(find "$WORK" -mindepth 1 -maxdepth 1 -type d | head -n 1)
fi

say "Installing $APP_NAME. This takes a few minutes the first time, and needs an internet connection."

step "Closing the app if it's open"
if pgrep -f "$ROOT/tools" >/dev/null 2>&1; then
    if [ "${SAGE_INSTALL_NONINTERACTIVE:-}" != "1" ] && [ -t 0 ]; then
        say "$APP_NAME is open. Please close its window, then press Enter here."
        read -r _ || true
    fi
    pkill -f "$ROOT/tools" 2>/dev/null || true
    sleep 1
fi

step "Getting uv (it provides Python and the app's other parts)"
if [ -x "$UV" ]; then
    say "   Already have uv."
else
    mkdir -p "$BIN"
    download "https://astral.sh/uv/$UV_VERSION/install.sh" "$ROOT/uv-install.sh" || fail "uv couldn't be downloaded."
    # UV_UNMANAGED_INSTALL: exactly this folder, with no PATH changes and no receipt left elsewhere.
    UV_UNMANAGED_INSTALL="$BIN" sh "$ROOT/uv-install.sh" || fail "uv couldn't be installed."
    rm -f "$ROOT/uv-install.sh"
    [ -x "$UV" ] || fail "uv didn't install."
fi

# Everything uv touches stays inside the install folder, which is what makes uninstalling clean.
export UV_TOOL_DIR="$ROOT/tools"
export UV_TOOL_BIN_DIR="$BIN"
export UV_PYTHON_INSTALL_DIR="$ROOT/python"
export UV_PYTHON_BIN_DIR="$BIN"
export UV_CACHE_DIR="$ROOT/cache"
export UV_PYTHON_PREFERENCE="only-managed"
export UV_NO_MODIFY_PATH=1

step "Installing $APP_NAME"
"$UV" tool install --quiet --force --reinstall --python "$PYTHON_VERSION" --constraints "$SOURCE/constraints.txt" "$SOURCE" \
    || fail "uv couldn't install the app."
"$UV" cache clean --quiet || true
[ -x "$ENV_BIN/python" ] || fail "the app's environment is missing after installing."

step "Creating the shortcuts"
{
    printf '{"installed_by": "installer", "data_dir": "%s"}\n' "$(printf '%s' "$DATA_DIR" | sed 's/\\/\\\\/g; s/"/\\"/g')"
} > "$ROOT/sage-install.json"
cp "$SOURCE/uninstall.sh" "$ROOT/uninstall.sh"
cp "$SOURCE/installer/update.sh" "$ROOT/update.sh"
chmod +x "$ROOT/uninstall.sh" "$ROOT/update.sh"
if [ -n "$DATA_DIR" ]; then
    "$ENV_BIN/python" -m sage.shortcuts create --data-dir "$DATA_DIR" || fail "the shortcuts couldn't be created."
else
    "$ENV_BIN/python" -m sage.shortcuts create || fail "the shortcuts couldn't be created."
fi

step "Checking Claude Code"
if [ -n "$DATA_DIR" ]; then
    "$ENV_BIN/sage-study" --data-dir "$DATA_DIR" --check || true
else
    "$ENV_BIN/sage-study" --check || true
fi

if [ "$(uname -s)" = "Linux" ]; then
    say ""
    say "On Linux, $APP_NAME opens in your default browser unless a desktop window library is available. It works the same either way."
fi

printf '\nAll done! Open %s from your Desktop or your applications menu.\n' "$APP_NAME"
if [ "$LAUNCH" = "1" ]; then
    if [ -n "$DATA_DIR" ]; then
        nohup "$ENV_BIN/sage-study-gui" --data-dir "$DATA_DIR" >/dev/null 2>&1 &
    else
        nohup "$ENV_BIN/sage-study-gui" >/dev/null 2>&1 &
    fi
fi
