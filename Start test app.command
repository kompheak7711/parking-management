#!/bin/sh
# Double-click in Finder to start the test app (scripts/local/start-test-app.sh).
cd "$(dirname -- "$0")" || exit 1
sh scripts/local/start-test-app.sh
status=$?
printf '\nThe test app has stopped. You can close this window.\n'
exit "$status"
