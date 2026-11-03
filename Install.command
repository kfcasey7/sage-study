#!/bin/sh
# Double-click to install Sage Study on a Mac.
cd "$(dirname "$0")" || exit 1
sh ./install.sh "$@"
status=$?
printf '\nYou can close this window.\n'
exit $status
