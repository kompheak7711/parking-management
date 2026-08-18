#!/bin/sh
set -eu

repo="${PROPERTY_RENTAL_REPO:-/Users/sokompheak/Development/property-rental-management}"
skip_remote="${PROPERTY_RENTAL_SELECTION_SKIP_REMOTE:-false}"
cd "$repo"

preflight="$(scripts/openclaw-supervisor-preflight.sh)"
[ "$(printf '%s' "$preflight" | jq -r '.state_issue')" = authorized_candidate_selection_required ] || exit 0
[ -z "$(git status --porcelain=v1)" ] || {
  echo "Structured candidate selection requires a clean worktree" >&2
  exit 73
}
candidate="$(printf '%s' "$preflight" | jq -c '.queue_candidate')"
printf '%s' "$candidate" | jq -e '
  type == "object"
  and .status == "approved_ready"
  and .protected_operation != true
  and (.phase | type == "string" and length > 0)
  and (.task | type == "string" and length > 0)
' >/dev/null

temporary="$(mktemp)"
jq \
  --argjson candidate "$candidate" \
  --arg timestamp "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" '
    .next_candidate = $candidate
    | .next_action = ("Implement the approved bounded candidate: " + $candidate.task)
    | .owner_action = "none"
    | .idle_reason = null
    | .timestamp = $timestamp
  ' ops/STATE.json >"$temporary"
mv "$temporary" ops/STATE.json

git add -- ops/STATE.json ops/AUTONOMOUS_QUEUE.json
git diff --cached --quiet && exit 0
git commit -m "ops: select structured authorized successor"
git push

[ "$skip_remote" = true ] && exit 0
"$repo/scripts/openclaw-wait-for-ci.sh" "$(git rev-parse HEAD)"
