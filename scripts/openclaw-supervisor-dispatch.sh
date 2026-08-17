#!/bin/sh
set -eu

repo="${PROPERTY_RENTAL_REPO:-/Users/sokompheak/Development/property-rental-management}"
state_dir="${PROPERTY_RENTAL_DISPATCH_STATE_DIR:-/Users/sokompheak/.openclaw/state/property-rental-supervisor-dispatch}"
openclaw_bin="${PROPERTY_RENTAL_OPENCLAW_BIN:-openclaw}"
max_cycles="${PROPERTY_RENTAL_MAX_IMMEDIATE_CYCLES:-6}"
last_file="$state_dir/last-attempted-fingerprint"
usage_file="$state_dir/model-usage.jsonl"
lock_dir="$state_dir/lock"

preflight="$($repo/scripts/openclaw-supervisor-preflight.sh)"
actionable="$(printf '%s' "$preflight" | jq -r '.actionable')"
[ "$actionable" = true ] || exit 0

mkdir -p "$state_dir"
if ! mkdir "$lock_dir" 2>/dev/null; then
  exit 0
fi
result_file="$(mktemp)"
trap 'rm -f "$result_file"; rmdir "$lock_dir" 2>/dev/null || true' EXIT HUP INT TERM
cycle=0
cumulative_tokens=0

while [ "$cycle" -lt "$max_cycles" ]; do
  preflight="$($repo/scripts/openclaw-supervisor-preflight.sh)"
  actionable="$(printf '%s' "$preflight" | jq -r '.actionable')"
  [ "$actionable" = true ] || exit 0

  fingerprint="$(printf '%s' "$preflight" | shasum -a 256 | awk '{print $1}')"
  if [ -f "$last_file" ] && [ "$(cat "$last_file")" = "$fingerprint" ]; then
    exit 0
  fi

  printf '%s\n' "$fingerprint" >"$last_file"
  : >"$result_file"

  if ! "$openclaw_bin" agent \
    --agent property-rental-supervisor \
    --session-id "property-rental-$fingerprint" \
    --message-file "$repo/ops/OPENCLAW_SUPERVISOR_PROMPT.md" \
    --thinking low \
    --timeout 1800 \
    --json >"$result_file"; then
    echo "Supervisor model cycle failed; identical state will not be retried automatically." >&2
    exit 70
  fi

  tokens="$(jq -r '.. | objects | select(has("usage")) | .usage.total? // empty' "$result_file" | sort -nr | head -1)"
  tokens="${tokens:-0}"
  cumulative_tokens=$((cumulative_tokens + tokens))
  jq -cn \
    --arg timestamp "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
    --arg fingerprint "$fingerprint" \
    --argjson cycle "$((cycle + 1))" \
    --argjson tokens "$tokens" \
    --argjson cumulative_tokens "$cumulative_tokens" \
    '{timestamp: $timestamp, fingerprint: $fingerprint, immediate_cycle: $cycle, total_tokens: $tokens, cumulative_tokens: $cumulative_tokens}' \
    >>"$usage_file"

  if [ "$tokens" -gt 100000 ]; then
    echo "Supervisor model cycle exceeded the 100000-token tranche ceiling ($tokens); further identical runs are suppressed." >&2
    exit 78
  fi

  postflight="$($repo/scripts/openclaw-supervisor-preflight.sh)"
  if [ "$(printf '%s' "$postflight" | jq -r '.actionable')" = true ] && [ "$postflight" = "$preflight" ]; then
    echo "Supervisor completed without advancing compact state; further identical runs are suppressed pending review." >&2
    exit 79
  fi

  cycle=$((cycle + 1))
done

# A bounded chain prevents a mistaken state transition from creating an unbounded
# model loop. If more approved work remains, the ordinary scheduler resumes it.
exit 0
