#!/bin/sh
# Double-click to remove Sage Study from a Mac.
cd "$(dirname "$0")" || exit 1
sh ./uninstall.sh "$@"
status=$?
printf '\nYou can close this window.\n'
exit $status
