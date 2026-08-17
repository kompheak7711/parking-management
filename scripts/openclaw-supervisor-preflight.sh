#!/bin/sh
set -eu

repo="${PROPERTY_RENTAL_REPO:-/Users/sokompheak/Development/property-rental-management}"
cd "$repo"

status="$(jq -r '.status // "unknown"' ops/STATE.json)"
next_action="$(jq -r '.next_action // ""' ops/STATE.json)"
blocker_count="$(jq -r '(.blockers // []) | length' ops/STATE.json)"
head_sha="$(git rev-parse HEAD)"
worktree_fingerprint="$(git status --porcelain=v1 | shasum -a 256 | awk '{print $1}')"

actionable=false
if [ "$blocker_count" -eq 0 ] && [ -n "$next_action" ]; then
  case "$status" in
    approved_ready|active|in_progress|verified_for_review|complete_unpublished)
      actionable=true
      ;;
  esac
fi

jq -cn \
  --arg head "$head_sha" \
  --arg status "$status" \
  --arg next_action "$next_action" \
  --arg worktree "$worktree_fingerprint" \
  --argjson blockers "$blocker_count" \
  --argjson actionable "$actionable" \
  '{head: $head, status: $status, next_action: $next_action, blockers: $blockers, worktree: $worktree, actionable: $actionable}'
