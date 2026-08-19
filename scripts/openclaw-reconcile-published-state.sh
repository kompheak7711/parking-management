#!/bin/sh
set -eu

repo="${PROPERTY_RENTAL_REPO:-/Users/sokompheak/Development/property-rental-management}"
skip_remote="${PROPERTY_RENTAL_RECONCILE_SKIP_REMOTE:-false}"
cd "$repo"

preflight="$(scripts/openclaw-supervisor-preflight.sh)"
[ "$(printf '%s' "$preflight" | jq -r '.state_issue')" = published_compact_state_reconciliation_required ] || exit 0
[ -z "$(git status --porcelain=v1)" ] || {
  echo "Deterministic reconciliation requires a clean worktree" >&2
  exit 73
}
head="$(git rev-parse HEAD)"
upstream="$(git rev-parse '@{upstream}')"
[ "$head" = "$upstream" ] || {
  echo "Deterministic reconciliation requires synchronized HEAD" >&2
  exit 73
}

# Publication state is downstream of candidate CI. Do not mutate compact state or
# create a reconciliation commit until GitHub Actions has accepted the candidate HEAD.
"$repo/scripts/openclaw-wait-for-ci.sh" "$head"

next_action="$(jq -r '
  if .next_candidate.status == "approved_ready" and (.next_candidate.task // "") != ""
  then "Implement the approved bounded candidate: " + .next_candidate.task
  elif (.next_action // "") != "" then .next_action
  else "No actionable next candidate is recorded."
  end
' ops/STATE.json)"
temporary="$(mktemp)"
jq \
  --arg head "$head" \
  --arg branch "$(git branch --show-current)" \
  --arg timestamp "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
  --arg next_action "$next_action" '
    .status = "published"
    | .branch = $branch
    | .commit = $head
    | .timestamp = $timestamp
    | .next_action = $next_action
    | .idle_reason = (if .next_candidate.status == "approved_ready" then null else (.idle_reason // "waiting for an explicitly approved candidate") end)
    | .owner_action = (if .next_candidate.status == "approved_ready" then "none" else (.owner_action // "Owner decision required") end)
  ' ops/STATE.json >"$temporary"
mv "$temporary" ops/STATE.json

git add -- ops/STATE.json
git diff --cached --quiet && exit 0
git commit -m "ops: reconcile published automation state"
git push

[ "$skip_remote" = true ] && exit 0
"$repo/scripts/openclaw-wait-for-ci.sh" "$(git rev-parse HEAD)"
