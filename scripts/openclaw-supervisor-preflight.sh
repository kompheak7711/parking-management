#!/bin/sh
set -eu

repo="${PROPERTY_RENTAL_REPO:-/Users/sokompheak/Development/property-rental-management}"
cd "$repo"

status="$(jq -r '.status // "unknown"' ops/STATE.json)"
recorded_next_action="$(jq -r '.next_action // ""' ops/STATE.json)"
next_action="$recorded_next_action"
candidate_task="$(jq -r '.next_candidate.task // ""' ops/STATE.json)"
candidate_status="$(jq -r '.next_candidate.status // "unknown"' ops/STATE.json)"
approval_status="$(jq -r '.approval.status // "unknown"' ops/STATE.json)"
blocker_count="$(jq -r '(.blockers // []) | length' ops/STATE.json)"
head_sha="$(git rev-parse HEAD)"
worktree_fingerprint="$(git status --porcelain=v1 | shasum -a 256 | awk '{print $1}')"

actionable=false
normalized=false
state_issue=""

# Durable state must not silently stall because a model omitted a redundant field.
# Derive only actions already covered by explicit approved state; never infer approval.
if [ "$blocker_count" -eq 0 ]; then
  if [ "$status" = approved_ready ] && [ -z "$next_action" ] \
    && [ "$candidate_status" = approved_ready ] && [ -n "$candidate_task" ]; then
    next_action="Implement the approved bounded candidate: $candidate_task"
    normalized=true
    state_issue="missing_next_action_derived_from_approved_candidate"
  fi
  case "$status:$approval_status" in
    complete_uncommitted:approved_ready|complete_unpublished:approved_ready)
      next_action="Independently verify and publish the completed bounded tranche under standing authorization, then dispatch the next approved candidate."
      normalized=true
      state_issue="completed_tranche_publication_action_enforced"
      ;;
  esac
fi

if [ "$blocker_count" -eq 0 ] && [ -n "$next_action" ]; then
  case "$status" in
    approved_ready|active|in_progress|verified_for_review|complete_unpublished|complete_uncommitted)
      actionable=true
      ;;
  esac
fi

jq -cn \
  --arg head "$head_sha" \
  --arg status "$status" \
  --arg next_action "$next_action" \
  --arg recorded_next_action "$recorded_next_action" \
  --arg state_issue "$state_issue" \
  --arg worktree "$worktree_fingerprint" \
  --argjson blockers "$blocker_count" \
  --argjson normalized "$normalized" \
  --argjson actionable "$actionable" \
  '{head: $head, status: $status, next_action: $next_action, recorded_next_action: $recorded_next_action, state_issue: $state_issue, normalized: $normalized, blockers: $blockers, worktree: $worktree, actionable: $actionable}'
