#!/bin/sh
set -eu

repo=/Users/sokompheak/Development/property-rental-management
state_dir=/Users/sokompheak/.openclaw/state/property-rental-supervisor-dispatch
last_file="$state_dir/last-successful-fingerprint"
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

openclaw agent \
  --agent property-rental-supervisor \
  --message-file "$repo/ops/OPENCLAW_SUPERVISOR_PROMPT.md" \
  --thinking medium \
  --timeout 1800 \
  --json

printf '%s\n' "$fingerprint" >"$last_file"
