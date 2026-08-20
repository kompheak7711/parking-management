#!/bin/sh
set -eu

repo="${PROPERTY_RENTAL_REPO:-$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)}"
installed_workspace="${PROPERTY_RENTAL_OPENCLAW_WORKSPACE:-/Users/sokompheak/.openclaw/workspaces/property-rental-supervisor}"
installed_wrapper="$installed_workspace/bin/hermes-property-rental"
state_db="${PROPERTY_RENTAL_OPENCLAW_DB:-/Users/sokompheak/.openclaw/state/openclaw.sqlite}"
supervisor_id="${PROPERTY_RENTAL_SUPERVISOR_ID:-658ffdaf-1ac1-45a6-a842-f5f7d7a226eb}"
expected_enabled="${PROPERTY_RENTAL_EXPECT_SCHEDULER_ENABLED:-any}"

[ -x "$repo/scripts/openclaw-supervisor-dispatch.sh" ]
[ -x "$repo/scripts/hermes-property-rental" ]
[ -x "$installed_wrapper" ]

schedule_count="$(sqlite3 "$state_db" \
  "SELECT count(*) FROM cron_jobs WHERE name='property-rental-24x7-supervisor';")"
[ "$schedule_count" = 1 ] || {
  echo "Expected exactly one Property Rental supervisor schedule" >&2
  exit 67
}
configured_count="$(sqlite3 "$state_db" \
  "SELECT count(*) FROM cron_jobs WHERE job_id='$supervisor_id' AND name='property-rental-24x7-supervisor';")"
[ "$configured_count" = 1 ] || {
  echo "The unique Property Rental supervisor schedule has an unexpected identity" >&2
  exit 67
}
schedule="$(sqlite3 -separator '|' "$state_db" \
  "SELECT enabled,schedule_kind,every_ms,payload_kind,payload_message FROM cron_jobs WHERE job_id='$supervisor_id' AND name='property-rental-24x7-supervisor';")"
enabled="$(printf '%s' "$schedule" | cut -d'|' -f1)"
schedule_kind="$(printf '%s' "$schedule" | cut -d'|' -f2)"
every_ms="$(printf '%s' "$schedule" | cut -d'|' -f3)"
payload_kind="$(printf '%s' "$schedule" | cut -d'|' -f4)"
payload_message="$(printf '%s' "$schedule" | cut -d'|' -f5-)"
[ "$schedule_kind" = every ] && [ "$every_ms" = 1800000 ] && [ "$payload_kind" = command ] || {
  echo "Supervisor schedule kind, interval, or payload kind is invalid" >&2
  exit 67
}
case "$expected_enabled" in
  any) ;;
  true) [ "$enabled" = 1 ] || { echo "Supervisor schedule is not enabled" >&2; exit 67; } ;;
  false) [ "$enabled" = 0 ] || { echo "Supervisor schedule is not disabled" >&2; exit 67; } ;;
  *) echo "Unsupported expected scheduler state" >&2; exit 64 ;;
esac
printf '%s' "$payload_message" | jq -e \
  --arg dispatcher "$repo/scripts/openclaw-supervisor-dispatch.sh" \
  --arg repo "$repo" '
    .kind == "command"
    and .argv == [$dispatcher]
    and .cwd == $repo
    and .noOutputTimeoutSeconds == 10860
    and .outputMaxBytes == 20000
    and (keys | sort) == (["argv","cwd","kind","noOutputTimeoutSeconds","outputMaxBytes"] | sort)
  ' >/dev/null || {
  echo "Installed schedule payload is not the exact repository dispatcher contract" >&2
  exit 67
}
cmp -s "$repo/scripts/hermes-property-rental" "$installed_wrapper" || {
  echo "Installed Hermes wrapper differs from the repository-owned wrapper" >&2
  exit 67
}

echo "Exactly one 30-minute schedule and the installed Hermes wrapper match repository-owned behavior"
