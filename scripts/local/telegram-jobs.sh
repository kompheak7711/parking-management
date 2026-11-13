#!/bin/sh
# Runs the Telegram bot jobs every 10 seconds on the Mac mini test run (owner ask 07/11/2026;
# "reply is too slow" with once a minute; prm-telegram-pull.timer and prm-telegram-send.timer run
# every 10 seconds on the office server too). Since DL-219 the relay answers every message at once
# and the pull job collects the messages every 150 seconds; each run still sends what the relay
# needs (only when it changed) and the new messages. Started by start-test-app.sh when
# "Set up Telegram test.command" has run; it stops with the test app.
# Each run is logged to .local/telegram.log; nothing secret is printed.
set -eu
. "$(dirname -- "$0")/common.sh"

TG="$PRM_LOCAL/telegram"
PRM_TELEGRAM_EVERY=10
[ -s "$TG/operations.json" ] && [ -s "$TG/jobs.env" ] || prm_fail "Run Set up Telegram test.command first."
IFS= read -r APP_DATABASE_URL < "$PRM_SECRETS/runtime_database_url"
# ABA QR payments (DL-180) are recorded with the money login, as Receive payment does.
IFS= read -r APP_FINANCIAL_DATABASE_URL < "$PRM_SECRETS/financial_database_url"
APP_HR_FILES_DIRECTORY="$PRM_LOCAL/hr-files"
export APP_DATABASE_URL APP_FINANCIAL_DATABASE_URL APP_HR_FILES_DIRECTORY
. "$TG/jobs.env"
cd "$PRM_ROOT/backend"
while :; do
  started=$(date +%s)
  uv run --quiet property-rental-telegram-pull --config "$TG/operations.json" \
    --property-id "$PRM_PROPERTY_ID" --actor-id "$PRM_TELEGRAM_ACTOR_ID" \
    "--service-actor-id=$PRM_TELEGRAM_SERVICE_ACTOR_ID" || true
  uv run --quiet property-rental-telegram-send --config "$TG/operations.json" \
    --property-id "$PRM_PROPERTY_ID" --actor-id "$PRM_TELEGRAM_ACTOR_ID" || true
  # Every 10 seconds, counted from the start of this run.
  rest=$((PRM_TELEGRAM_EVERY - $(date +%s) + started))
  [ "$rest" -gt 0 ] && sleep "$rest"
done
