#!/bin/sh
set -eu

repo="${PROPERTY_RENTAL_REPO:-/Users/sokompheak/Development/property-rental-management}"
cd "$repo"

status="$(jq -r '.status // "unknown"' ops/STATE.json)"
status_known=false
case "$status" in
  approved_ready|active|in_progress|verified_for_review|complete_unpublished|complete_uncommitted|published|failed|not_verified|discrepancy|repair_required|verified_unpublished|implemented_awaiting_supervisor_review)
    status_known=true
    ;;
esac
recorded_next_action="$(jq -r '.next_action // ""' ops/STATE.json)"
next_action="$recorded_next_action"
candidate_task="$(jq -r '.next_candidate.task // ""' ops/STATE.json)"
candidate_phase="$(jq -r '.next_candidate.phase // ""' ops/STATE.json)"
candidate_status="$(jq -r '.next_candidate.status // "unknown"' ops/STATE.json)"
candidate_is_object="$(jq -r '.next_candidate | type == "object"' ops/STATE.json)"
approval_status="$(jq -r '.approval.status // "unknown"' ops/STATE.json)"
implementation_started="$(jq -r '.approval.implementation_started == true' ops/STATE.json)"
implementation_completed="$(jq -r '.approval.implementation_completed == true' ops/STATE.json)"
publication_completed="$(jq -r '.approval.publication_completed == true' ops/STATE.json)"
blocker_count="$(jq -r '(.blockers // []) | length' ops/STATE.json)"
repair_attempts="$(jq -r '(.repair.attempts // 0) | if type == "number" and floor == . and . >= 0 then . else 0 end' ops/STATE.json)"
repair_max_attempts="$(jq -r '(.repair.max_attempts // 2) | if type == "number" and floor == . and . >= 1 and . <= 2 then . else 2 end' ops/STATE.json)"
repair_scope_preserved="$(jq -r '.repair.scope_preserved // false' ops/STATE.json)"
repair_failure="$(jq -r '.repair.failure // ""' ops/STATE.json)"
repair_protected="$(jq -r '[.repair.requires_owner_decision, .repair.suspected_secret, .repair.scope_expansion, .repair.protected_operation] | any(. == true)' ops/STATE.json)"
active_cycle="$(jq -r '.active_cycle // .task // "unknown"' ops/STATE.json)"
state_commit="$(jq -r '.commit // ""' ops/STATE.json)"
head_sha="$(git rev-parse HEAD)"
worktree_status="$(git status --porcelain=v1)"
worktree_fingerprint="$(printf '%s' "$worktree_status" | shasum -a 256 | awk '{print $1}')"
upstream_sha="$(git rev-parse '@{upstream}' 2>/dev/null || true)"
durable_v1_authorization=false
if grep -Fq 'Remaining v1 application tranches are authorized when bounded by canonical documents' ops/QUEUE.md; then
  durable_v1_authorization=true
fi
candidate_is_concrete=false
if [ "$candidate_is_object" = true ] && [ -n "$candidate_phase" ] \
  && [ "$candidate_phase" != unselected ] && [ -n "$candidate_task" ]; then
  candidate_is_concrete=true
fi
roadmap_current_id="$(jq -r '.roadmap.current_id // ""' ops/STATE.json)"
if [ -z "$roadmap_current_id" ] && [ "$(jq -r '.phase // ""' ops/STATE.json)" = "Phase 2P" ]; then
  roadmap_current_id="V1-011"
fi
queue_candidate='null'
roadmap_total=0
roadmap_completed=0
roadmap_current_status="unknown"
if [ -f ops/V1_ROADMAP.json ]; then
  roadmap_total="$(jq -r '.total_tranches // 0' ops/V1_ROADMAP.json)"
  roadmap_completed="$(jq -r '[.tranches[] | select(.status == "complete")] | length' ops/V1_ROADMAP.json)"
  roadmap_current_status="$(jq -r --arg current "$roadmap_current_id" '.tranches[]? | select(.id == $current) | .status' ops/V1_ROADMAP.json)"
  queue_candidate="$(jq -c --arg current "$roadmap_current_id" '
    . as $root
    | ((.tranches | map(select(.id == $current)) | .[0].order) // -1) as $order
    | [.tranches[]?
        | select(.order == ($order + 1) and .status == "approved_ready" and .authorization == "durable_v1")
        | select([.dependencies[]? as $dependency
            | $root.tranches[]
            | select(.id == $dependency)
            | (.status == "complete" or .id == $current)] | all)]
    | if length == 1 then .[0] else null end
  ' ops/V1_ROADMAP.json)"
fi
queue_candidate_available="$(printf '%s' "$queue_candidate" | jq -r 'type == "object" and (.protected_operation != true)')"

actionable=false
normalized=false
state_issue=""

# Durable state must not silently stall because a model omitted a redundant field.
# Derive only actions already covered by explicit approved state; never infer approval.
if [ "$blocker_count" -eq 0 ]; then
  if [ "$implementation_completed" = true ] && [ "$publication_completed" = false ]; then
    if [ -n "$state_commit" ] && [ "$state_commit" != "$head_sha" ] \
      && [ "$head_sha" = "$upstream_sha" ] && [ -z "$worktree_status" ] \
      && git merge-base --is-ancestor "$state_commit" "$head_sha" 2>/dev/null; then
      next_action="Reconcile compact state with published HEAD $head_sha: record status published, branch, published commit, nonempty exact next_action, explicit next-candidate approval status, idle reason, and owner action; do not implement the next candidate."
      normalized=true
      state_issue="published_compact_state_reconciliation_required"
    fi
  else
    case "$status" in
      verified_for_review|verified_unpublished|complete_uncommitted|complete_unpublished|implemented_awaiting_supervisor_review)
      if [ -n "$state_commit" ] && [ "$state_commit" != "$head_sha" ] \
        && [ "$head_sha" = "$upstream_sha" ] && [ -z "$worktree_status" ] \
        && git merge-base --is-ancestor "$state_commit" "$head_sha" 2>/dev/null; then
        next_action="Reconcile compact state with published HEAD $head_sha: record status published, branch, published commit, nonempty exact next_action, explicit next-candidate approval status, idle reason, and owner action; do not implement the next candidate."
        normalized=true
        state_issue="published_compact_state_reconciliation_required"
      fi
      ;;
    esac
  fi
  if [ "$normalized" = false ] && [ "$approval_status" = approved_ready ] \
    && [ "$implementation_completed" = true ] && [ "$publication_completed" = false ]; then
    next_action="Independently verify and publish the completed bounded tranche under standing authorization, then dispatch the next approved candidate."
    normalized=true
    state_issue="completed_tranche_publication_action_enforced"
  fi
  if [ "$normalized" = false ] && [ "$status" = implemented_awaiting_supervisor_review ] \
    && [ "$approval_status" = approved_ready ]; then
    next_action="Independently verify and publish the completed bounded tranche under standing authorization; record it as complete_uncommitted before publication and do not wait for redundant Owner permission."
    normalized=true
    state_issue="completed_status_alias_publication_enforced"
  fi
  if [ "$normalized" = false ] && [ "$status" = approved_ready ] && [ -z "$next_action" ] \
    && [ "$candidate_status" = approved_ready ] && [ -n "$candidate_task" ]; then
    next_action="Implement the approved bounded candidate: $candidate_task"
    normalized=true
    state_issue="missing_next_action_derived_from_approved_candidate"
  fi
  if [ "$normalized" = false ] && [ "$status" = published ] \
    && [ "$candidate_status" = approved_ready ] && [ -n "$candidate_task" ]; then
    next_action="Implement the approved bounded candidate: $candidate_task"
    normalized=true
    state_issue="published_next_candidate_dispatch_required"
  fi
  if [ "$normalized" = false ] && [ "$status" = published ] \
    && [ "$durable_v1_authorization" = true ] && [ "$candidate_is_concrete" = false ]; then
    if [ "$queue_candidate_available" = true ]; then
      next_action="Materialize the exact structured approved successor from ops/V1_ROADMAP.json without a model, then dispatch it immediately."
      normalized=true
      state_issue="authorized_candidate_selection_required"
    else
      next_action="No unique safe structured successor exists for the published phase. Record an explicit bounded candidate or protected Owner-decision reason."
      normalized=true
      state_issue="handoff_missing"
    fi
  fi
  if [ "$normalized" = false ]; then
    case "$status:$approval_status" in
      verified_unpublished:approved_ready|complete_uncommitted:approved_ready|complete_unpublished:approved_ready)
        next_action="Independently verify and publish the completed bounded tranche under standing authorization, then dispatch the next approved candidate."
        normalized=true
        state_issue="completed_tranche_publication_action_enforced"
        ;;
    esac
  fi
  if [ "$normalized" = false ]; then
    case "$status" in
      failed|not_verified|discrepancy|repair_required)
        case "$approval_status" in
          approved_ready|approved_active|approved_complete)
            if [ "$repair_scope_preserved" = true ] && [ "$repair_protected" = false ] \
              && [ -n "$repair_failure" ] && [ "$repair_attempts" -lt "$repair_max_attempts" ]; then
              next_action="Perform bounded automatic repair attempt $((repair_attempts + 1)) of $repair_max_attempts for the already-approved tranche: $repair_failure. Preserve the original scope, add deterministic regression coverage, and re-run every applicable publication gate."
              normalized=true
              state_issue="bounded_automatic_repair_authorized"
            fi
            ;;
        esac
        ;;
    esac
  fi
  if [ "$normalized" = false ] && [ "$status_known" = false ]; then
    case "$approval_status" in
      approved_ready|approved_active|approved_complete)
        if [ "$durable_v1_authorization" = true ] && [ "$repair_protected" = false ]; then
          next_action="Perform a bounded compact-state contract repair for unrecognized status '$status': reconcile approval lifecycle, current roadmap item, Git/worktree evidence, and exact next action without changing application scope or publishing unverified work."
          normalized=true
          state_issue="state_contract_repair_authorized"
        else
          next_action="Unrecognized compact-state status '$status' cannot be safely normalized under current authorization."
          normalized=true
          state_issue="state_contract_violation"
        fi
        ;;
      *)
        next_action="Unrecognized compact-state status '$status' cannot be safely normalized under current authorization."
        normalized=true
        state_issue="state_contract_violation"
        ;;
    esac
  fi
fi

if [ "$blocker_count" -eq 0 ] && [ -n "$next_action" ]; then
  if [ "$state_issue" = completed_tranche_publication_action_enforced ] \
    || [ "$state_issue" = state_contract_repair_authorized ]; then
    actionable=true
  fi
  case "$status" in
    approved_ready|active|in_progress|verified_for_review|verified_unpublished|complete_unpublished|complete_uncommitted|implemented_awaiting_supervisor_review)
      actionable=true
      ;;
    failed|not_verified|discrepancy|repair_required)
      if [ "$state_issue" = bounded_automatic_repair_authorized ]; then
        actionable=true
      fi
      ;;
    published)
      if [ "$state_issue" = published_next_candidate_dispatch_required ] \
        || [ "$state_issue" = authorized_candidate_selection_required ]; then
        actionable=true
      fi
      ;;
  esac
fi

jq -cn \
  --arg head "$head_sha" \
  --arg status "$status" \
  --arg next_action "$next_action" \
  --arg recorded_next_action "$recorded_next_action" \
  --arg state_issue "$state_issue" \
  --arg active_cycle "$active_cycle" \
  --arg repair_failure "$repair_failure" \
  --arg worktree "$worktree_fingerprint" \
  --argjson blockers "$blocker_count" \
  --argjson repair_attempts "$repair_attempts" \
  --argjson repair_max_attempts "$repair_max_attempts" \
  --argjson durable_v1_authorization "$durable_v1_authorization" \
  --argjson candidate_is_concrete "$candidate_is_concrete" \
  --argjson status_known "$status_known" \
  --argjson implementation_started "$implementation_started" \
  --argjson implementation_completed "$implementation_completed" \
  --argjson publication_completed "$publication_completed" \
  --argjson queue_candidate "$queue_candidate" \
  --arg roadmap_current_id "$roadmap_current_id" \
  --argjson roadmap_total "$roadmap_total" \
  --argjson roadmap_completed "$roadmap_completed" \
  --arg roadmap_current_status "$roadmap_current_status" \
  --argjson normalized "$normalized" \
  --argjson actionable "$actionable" \
  '{head: $head, status: $status, active_cycle: $active_cycle, next_action: $next_action, recorded_next_action: $recorded_next_action, state_issue: $state_issue, repair_failure: $repair_failure, normalized: $normalized, blockers: $blockers, repair_attempts: $repair_attempts, repair_max_attempts: $repair_max_attempts, durable_v1_authorization: $durable_v1_authorization, candidate_is_concrete: $candidate_is_concrete, status_known: $status_known, implementation_started: $implementation_started, implementation_completed: $implementation_completed, publication_completed: $publication_completed, queue_candidate: $queue_candidate, roadmap:{current_id:$roadmap_current_id,current_status:$roadmap_current_status,total:$roadmap_total,completed:$roadmap_completed}, worktree: $worktree, actionable: $actionable}'
