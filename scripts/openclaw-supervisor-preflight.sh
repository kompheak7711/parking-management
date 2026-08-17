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
state_commit="$(jq -r '.commit // ""' ops/STATE.json)"
head_sha="$(git rev-parse HEAD)"
worktree_status="$(git status --porcelain=v1)"
worktree_fingerprint="$(printf '%s' "$worktree_status" | shasum -a 256 | awk '{print $1}')"
upstream_sha="$(git rev-parse '@{upstream}' 2>/dev/null || true)"

actionable=false
normalized=false
state_issue=""

# Durable state must not silently stall because a model omitted a redundant field.
# Derive only actions already covered by explicit approved state; never infer approval.
if [ "$blocker_count" -eq 0 ]; then
  case "$status" in
    verified_for_review|complete_uncommitted|complete_unpublished)
      if [ -n "$state_commit" ] && [ "$state_commit" != "$head_sha" ] \
        && [ "$head_sha" = "$upstream_sha" ] && [ -z "$worktree_status" ] \
        && git merge-base --is-ancestor "$state_commit" "$head_sha" 2>/dev/null; then
        next_action="Reconcile compact state with published HEAD $head_sha: record status published, branch, published commit, nonempty exact next_action, explicit next-candidate approval status, idle reason, and owner action; do not implement the next candidate."
        normalized=true
        state_issue="published_compact_state_reconciliation_required"
      fi
      ;;
  esac
  if [ "$normalized" = false ] && [ "$status" = approved_ready ] && [ -z "$next_action" ] \
    && [ "$candidate_status" = approved_ready ] && [ -n "$candidate_task" ]; then
    next_action="Implement the approved bounded candidate: $candidate_task"
    normalized=true
    state_issue="missing_next_action_derived_from_approved_candidate"
  fi
  if [ "$normalized" = false ]; then
    case "$status:$approval_status" in
      complete_uncommitted:approved_ready|complete_unpublished:approved_ready)
        next_action="Independently verify and publish the completed bounded tranche under standing authorization, then dispatch the next approved candidate."
        normalized=true
        state_issue="completed_tranche_publication_action_enforced"
        ;;
    esac
  fi
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
