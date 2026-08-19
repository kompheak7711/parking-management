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
    .roadmap.current_id = $candidate.id
    | .roadmap.total = 60
    | .next_candidate = ($candidate + {roadmap_id:$candidate.id})
    | .phase = $candidate.phase
    | .tranche = $candidate.task
    | .task = ("Implement the approved bounded candidate: " + $candidate.task)
    | .status = "active"
    | .active_cycle = (
        ($candidate.id | ascii_downcase)
        + "-"
        + ($candidate.task
            | ascii_downcase
            | gsub("[^a-z0-9]+"; "-")
            | gsub("(^-|-$)"; ""))
      )
    | .risk_class = ($candidate.risk_class // "high")
    | .approval = {
        status: "approved_ready",
        basis: "structured durable-v1 successor selection",
        implementation_started: true,
        implementation_completed: false,
        publication_completed: false
      }
    | .authorities = ($candidate.authorities // [])
    | .touched_areas = ($candidate.include // [])
    | .tests = []
    | .relevant_docs = ($candidate.authorities // [])
    | .next_action = ("Implement the approved bounded candidate: " + $candidate.task)
    | .owner_action = "none"
    | .idle_reason = null
    | .blockers = []
    | .repair = {
        tranche_id: $candidate.id,
        failure: null,
        scope_preserved: true,
        attempts: 0,
        max_attempts: 2,
        requires_owner_decision: false,
        suspected_secret: false,
        scope_expansion: false,
        protected_operation: false,
        last_outcome: null
      }
    | .timestamp = $timestamp
  ' ops/STATE.json >"$temporary"
mv "$temporary" ops/STATE.json

current_id="$(printf '%s' "$preflight" | jq -r '.roadmap.current_id')"
roadmap_temporary="$(mktemp)"
jq --arg current "$current_id" '
  .tranches |= map(if .id == $current then .status = "complete" | .authorization = "complete" else . end)
' ops/V1_ROADMAP.json >"$roadmap_temporary"
mv "$roadmap_temporary" ops/V1_ROADMAP.json

git add -- ops/STATE.json ops/V1_ROADMAP.json
git diff --cached --quiet && exit 0
git commit -m "ops: select structured authorized successor"
git push

[ "$skip_remote" = true ] && exit 0
"$repo/scripts/openclaw-wait-for-ci.sh" "$(git rev-parse HEAD)"
