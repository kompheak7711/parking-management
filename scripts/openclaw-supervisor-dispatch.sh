#!/bin/sh
set -eu

repo=/Users/sokompheak/Development/property-rental-management
state_dir=/Users/sokompheak/.openclaw/state/property-rental-supervisor-dispatch
last_file="$state_dir/last-attempted-fingerprint"
usage_file="$state_dir/model-usage.jsonl"
lock_dir="$state_dir/lock"

preflight="$($repo/scripts/openclaw-supervisor-preflight.sh)"
actionable="$(printf '%s' "$preflight" | jq -r '.actionable')"
[ "$actionable" = true ] || exit 0

fingerprint="$(printf '%s' "$preflight" | shasum -a 256 | awk '{print $1}')"
mkdir -p "$state_dir"
if ! mkdir "$lock_dir" 2>/dev/null; then
  exit 0
fi
trap 'rmdir "$lock_dir" 2>/dev/null || true' EXIT HUP INT TERM

if [ -f "$last_file" ] && [ "$(cat "$last_file")" = "$fingerprint" ]; then
  exit 0
fi

printf '%s\n' "$fingerprint" >"$last_file"
result_file="$(mktemp)"
trap 'rm -f "$result_file"; rmdir "$lock_dir" 2>/dev/null || true' EXIT HUP INT TERM

if ! openclaw agent \
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
jq -cn --arg timestamp "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" --arg fingerprint "$fingerprint" --argjson tokens "$tokens" \
  '{timestamp: $timestamp, fingerprint: $fingerprint, total_tokens: $tokens}' >>"$usage_file"

if [ "$tokens" -gt 100000 ]; then
  echo "Supervisor model cycle exceeded the 100000-token tranche ceiling ($tokens); further identical runs are suppressed." >&2
  exit 78
fi

postflight="$($repo/scripts/openclaw-supervisor-preflight.sh)"
if [ "$(printf '%s' "$postflight" | jq -r '.actionable')" = true ] && [ "$postflight" = "$preflight" ]; then
  echo "Supervisor completed without advancing compact state; further identical runs are suppressed pending review." >&2
  exit 79
fi
