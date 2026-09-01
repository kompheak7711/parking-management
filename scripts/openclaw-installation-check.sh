#!/bin/sh
set -eu

repo="${PROPERTY_RENTAL_REPO:-$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)}"
openclaw="${PROPERTY_RENTAL_OPENCLAW_BIN:-/Users/sokompheak/.openclaw/bin/openclaw}"
supervisor_id="${PROPERTY_RENTAL_SUPERVISOR_ID:-658ffdaf-1ac1-45a6-a842-f5f7d7a226eb}"
expected_enabled="${PROPERTY_RENTAL_EXPECT_SCHEDULER_ENABLED:-any}"
authoritative_prompt="$repo/ops/OPENCLAW_SUPERVISOR_PROMPT.md"

[ -x "$openclaw" ]
[ -f "$authoritative_prompt" ]

jobs="$($openclaw cron list --json)"
schedule_count="$(printf '%s' "$jobs" | jq '[.jobs[] | select(.name == "property-rental-24x7-supervisor")] | length')"
[ "$schedule_count" = 1 ] || {
  echo "Expected exactly one Property Rental supervisor schedule" >&2
  exit 67
}
configured_count="$(printf '%s' "$jobs" | jq --arg id "$supervisor_id" '[.jobs[] | select(.id == $id and .name == "property-rental-24x7-supervisor")] | length')"
[ "$configured_count" = 1 ] || {
  echo "The unique Property Rental supervisor schedule has an unexpected identity" >&2
  exit 67
}

job="$($openclaw cron get "$supervisor_id")"
enabled="$(printf '%s' "$job" | jq -r '.enabled')"
case "$expected_enabled" in
  any) ;;
  true) [ "$enabled" = true ] || { echo "Supervisor schedule is not enabled" >&2; exit 67; } ;;
  false) [ "$enabled" = false ] || { echo "Supervisor schedule is not disabled" >&2; exit 67; } ;;
  *) echo "Unsupported expected scheduler state" >&2; exit 64 ;;
esac

printf '%s' "$job" | jq -e \
  --arg id "$supervisor_id" \
  --rawfile prompt "$authoritative_prompt" '
    .id == $id
    and .declarationKey == "property-rental-24x7-v1"
    and .name == "property-rental-24x7-supervisor"
    and .agentId == "property-manager"
    and .sessionTarget == "isolated"
    and .schedule.kind == "every"
    and .schedule.everyMs == 1800000
    and .payload.kind == "agentTurn"
    and .payload.message == $prompt
    and .payload.model == "openai/gpt-5.6-sol"
    and .payload.thinking == "xhigh"
    and .payload.timeoutSeconds == 1800
    and .payload.lightContext == false
  ' >/dev/null || {
  echo "Installed schedule does not match the authoritative continuous supervisor policy" >&2
  exit 67
}

echo "Exactly one 30-minute native supervisor schedule matches the authoritative repository prompt"
