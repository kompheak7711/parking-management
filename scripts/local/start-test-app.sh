#!/bin/sh
# Starts the whole test app on the Mac mini in one window (owner ask 29/10/2026: "make a single
# Start test app"): Docker and the database, any new migrations, the screens and the API. It runs
# the same scripts as README "Local run on the Mac mini" steps 3, 7 and 8, so nothing about the
# secrets or the key changes. Double-click "Start test app.command" in the repository folder, or:
#
#   sh scripts/local/start-test-app.sh
#
# sudo asks for your Mac password once (for the API). Control-C, or closing the window, stops the
# screens and the API; the database keeps running in Docker, as before.
set -eu
. "$(dirname -- "$0")/common.sh"
cd "$PRM_ROOT"

command -v docker >/dev/null 2>&1 || prm_fail "Docker is not installed. Install Docker Desktop first."
if ! docker info >/dev/null 2>&1; then
  printf 'Opening Docker Desktop. Please wait...\n'
  open -a Docker 2>/dev/null || prm_fail "Docker Desktop did not open. Open it, then try again."
  tries=0
  until docker info >/dev/null 2>&1; do
    tries=$((tries + 1))
    [ "$tries" -le 90 ] || prm_fail "Docker Desktop did not start in 3 minutes. Open it, then try again."
    sleep 2
  done
fi

printf '1 of 4: starting the database...\n'
sh scripts/local/database.sh start
printf '2 of 4: applying any new database changes...\n'
sh scripts/local/migrate.sh

origin=$(prm_origin)
mkdir -p "$PRM_LOCAL"
log="$PRM_LOCAL/screens.log"
printf '3 of 4: starting the screens (log: .local/screens.log)...\n'
(cd frontend && exec npm run dev:local) > "$log" 2>&1 &
screens=$!
stop_screens() {
  kill "$screens" 2>/dev/null || true
}
trap stop_screens EXIT INT TERM HUP

# Open the browser once the screen server answers (about 30 seconds at most).
(
  tries=0
  until curl --silent --output /dev/null --cacert "$PRM_HTTPS/local-ca.pem" "$origin" 2>/dev/null; do
    tries=$((tries + 1))
    [ "$tries" -le 30 ] || exit 0
    sleep 1
  done
  open "$origin"
) &

printf '4 of 4: starting the API. Type your Mac password if asked.\n'
printf 'The app opens at %s. Keep this window open while you test.\n' "$origin"
printf 'To stop the app, press Control-C here or close this window.\n'
# Not exec: the trap must stop the screens when the API stops.
sh scripts/local/start-api.sh
