#!/bin/sh
set -eu

repo="${PROPERTY_RENTAL_REPO:-$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)}"
cd "$repo"

if ! expected_branch="$(jq -er 'if (.branch | type) == "string" and (.branch | length) > 0 then .branch else error("invalid branch") end' ops/STATE.json)"; then
  echo "Compact state has no valid authorized branch" >&2
  exit 73
fi
current_branch="$(git branch --show-current)"
[ -n "$current_branch" ] && [ -n "$expected_branch" ] && [ "$current_branch" = "$expected_branch" ] || {
  echo "Deterministic reconciliation is not on the compact-state authorized branch" >&2
  exit 73
}

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

# Publication state is downstream of candidate CI. The resumable dispatcher
# proves that gate before mutation; standalone use retains the same proof.
if [ "${PROPERTY_RENTAL_RECONCILE_MUTATE_ONLY:-false}" != true ]; then
  "$repo/scripts/openclaw-wait-for-ci.sh" "$head"
fi

next_action="Select the exact structured approved successor from ops/V1_ROADMAP.json without a model; do not reimplement the published candidate."
temporary="$(mktemp)"
jq \
  --arg head "$head" \
  --arg branch "$(git branch --show-current)" \
  --arg timestamp "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
  --arg next_action "$next_action" '
    .status = "published"
    | .approval.publication_completed = true
    | .branch = $branch
    | .commit = $head
    | .timestamp = $timestamp
    | .next_action = $next_action
    | .idle_reason = "published candidate awaits deterministic successor selection"
    | .owner_action = "none"
  ' ops/STATE.json >"$temporary"
mv "$temporary" ops/STATE.json

now_temporary="$(mktemp)"
awk '
  /<!-- AUTOMATION_STATUS_BEGIN -->/ {skip=1; next}
  /<!-- AUTOMATION_STATUS_END -->/ {skip=0; next}
  !skip {print}
' ops/NOW.md >"$now_temporary"
printf '%s\n' \
  '<!-- AUTOMATION_STATUS_BEGIN -->' \
  "- Automation publication state: published on $(git branch --show-current) at $head." \
  "- Automation exact next action: $next_action" \
  '<!-- AUTOMATION_STATUS_END -->' >>"$now_temporary"
mv "$now_temporary" ops/NOW.md

git add -- ops/NOW.md ops/STATE.json
[ "${PROPERTY_RENTAL_RECONCILE_MUTATE_ONLY:-false}" = true ] && exit 0
git diff --cached --quiet && exit 0
git commit -m "ops: reconcile published automation state"
git push

"$repo/scripts/openclaw-wait-for-ci.sh" "$(git rev-parse HEAD)"
