#!/bin/sh
# Started by the app when you click "Update and restart": update.sh TAG APP_PID [DATA_DIR]. Waits for the app to close, then
# installs the release's own installer over this copy. Your study data is kept in its separate folder. Details go to update.log.
set -u

TAG="$1"
APP_PID="${2:-}"
DATA_DIR="${3:-}"
GITHUB_REPO="kfcasey7/sage-study"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec >"$ROOT/update.log" 2>&1

case "$TAG" in
    v[0-9]*.[0-9]*.[0-9]*) ;;
    *) echo "Unexpected version '$TAG'"; exit 1 ;;
esac

if [ -n "$APP_PID" ]; then
    n=0
    while kill -0 "$APP_PID" 2>/dev/null && [ "$n" -lt 60 ]; do sleep 1; n=$((n + 1)); done
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export SAGE_INSTALL_NONINTERACTIVE=1 SAGE_INSTALL_ROOT="$ROOT"

if curl -fsSL "https://github.com/$GITHUB_REPO/archive/refs/tags/$TAG.tar.gz" -o "$WORK/release.tar.gz" \
    && tar -xzf "$WORK/release.tar.gz" -C "$WORK"; then
    SOURCE=$(find "$WORK" -mindepth 1 -maxdepth 1 -type d | head -n 1)
    if [ -n "$DATA_DIR" ]; then
        sh "$SOURCE/install.sh" --data-dir "$DATA_DIR" && exit 0
    else
        sh "$SOURCE/install.sh" && exit 0
    fi
fi

echo "Update failed; starting the installed version again."
if [ -n "$DATA_DIR" ]; then
    nohup "$ROOT/tools/sage-study/bin/sage-study-gui" --data-dir "$DATA_DIR" >/dev/null 2>&1 &
else
    nohup "$ROOT/tools/sage-study/bin/sage-study-gui" >/dev/null 2>&1 &
fi
exit 1
