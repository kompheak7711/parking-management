#!/bin/sh
set -eu

source_repo="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT HUP INT TERM

make_repo() {
  name="$1"
  repo="$test_root/$name/repo"
  mkdir -p "$repo/ops" "$repo/scripts"
  cp "$source_repo/scripts/openclaw-supervisor-preflight.sh" "$repo/scripts/"
  cp "$source_repo/scripts/openclaw-select-next-candidate.sh" "$repo/scripts/"
  cp "$source_repo/scripts/openclaw-reconcile-published-state.sh" "$repo/scripts/"
  cp "$source_repo/scripts/openclaw-wait-for-ci.sh" "$repo/scripts/"
  cp "$source_repo/scripts/openclaw-task-packet.sh" "$repo/scripts/"
  cp "$source_repo/scripts/openclaw_automation.py" "$repo/scripts/"
  chmod +x "$repo/scripts/"*.sh
  printf '%s\n' '# state' >"$repo/ops/NOW.md"
  printf '%s\n' 'Remaining v1 application tranches are authorized when bounded by canonical documents 001-010.' >"$repo/ops/QUEUE.md"
  jq -cn '{
    "status":"approved_ready","phase":"Identity","active_cycle":"v1-018","risk_class":"high",
    "roadmap":{"current_id":"V1-018","total":2},"blockers":[],"next_action":"Implement exact candidate",
    "approval":{"status":"approved_ready","implementation_started":false,"implementation_completed":false,"publication_completed":false},
    "next_candidate":{"id":"V1-018","roadmap_id":"V1-018","phase":"Identity","task":"Exact candidate","status":"approved_ready","risk_class":"high"},
    "repair":{"tranche_id":"V1-018","failure":null,"scope_preserved":true,"attempts":0,"max_attempts":2,"requires_owner_decision":false,"suspected_secret":false,"scope_expansion":false,"protected_operation":false}
  }' >"$repo/ops/STATE.json"
  jq -cn '{"schema_version":1,"total_tranches":2,"tranches":[
    {"id":"V1-017","order":17,"status":"complete"},
    {"id":"V1-018","order":18,"phase":"Identity","task":"Exact candidate","dependencies":["V1-017"],"authorities":["API-079"],"include":["bounded API"],"exclude":["policy invention"],"status":"approved_ready","authorization":"durable_v1","risk_class":"high","protected_operation":false}
  ]}' >"$repo/ops/V1_ROADMAP.json"
  git -C "$repo" init -q
  git -C "$repo" config user.name test
  git -C "$repo" config user.email test@example.invalid
  git -C "$repo" add .
  git -C "$repo" commit -qm baseline
}

make_repo missing-action
repo="$test_root/missing-action/repo"
jq 'del(.next_action)' "$repo/ops/STATE.json" >"$repo/ops/state.tmp"
mv "$repo/ops/state.tmp" "$repo/ops/STATE.json"
result="$(PROPERTY_RENTAL_REPO="$repo" "$repo/scripts/openclaw-supervisor-preflight.sh")"
printf '%s' "$result" | jq -e '.actionable and .state_issue == "missing_next_action_derived_from_approved_candidate"' >/dev/null

make_repo completion-alias
repo="$test_root/completion-alias/repo"
jq '.status="verified_unpublished" | .approval.implementation_completed=true | .next_action="wait"' "$repo/ops/STATE.json" >"$repo/ops/state.tmp"
mv "$repo/ops/state.tmp" "$repo/ops/STATE.json"
result="$(PROPERTY_RENTAL_REPO="$repo" "$repo/scripts/openclaw-supervisor-preflight.sh")"
printf '%s' "$result" | jq -e '.actionable and .state_issue == "completed_tranche_publication_action_enforced" and (.next_action | contains("standing authorization"))' >/dev/null

make_repo unknown-status
repo="$test_root/unknown-status/repo"
jq '.status="future_worker_label" | .approval.status="approved_ready"' "$repo/ops/STATE.json" >"$repo/ops/state.tmp"
mv "$repo/ops/state.tmp" "$repo/ops/STATE.json"
result="$(PROPERTY_RENTAL_REPO="$repo" "$repo/scripts/openclaw-supervisor-preflight.sh")"
printf '%s' "$result" | jq -e '.actionable and (.status_known | not) and .state_issue == "state_contract_repair_authorized"' >/dev/null

make_repo bounded-repair
repo="$test_root/bounded-repair/repo"
jq '.status="not_verified" | .approval.status="approved_active" | .repair.failure="backend CI failed"' "$repo/ops/STATE.json" >"$repo/ops/state.tmp"
mv "$repo/ops/state.tmp" "$repo/ops/STATE.json"
result="$(PROPERTY_RENTAL_REPO="$repo" "$repo/scripts/openclaw-supervisor-preflight.sh")"
printf '%s' "$result" | jq -e '.actionable and .state_issue == "bounded_automatic_repair_authorized" and .repair_max_attempts == 2' >/dev/null
jq '.repair.attempts=2' "$repo/ops/STATE.json" >"$repo/ops/state.tmp"
mv "$repo/ops/state.tmp" "$repo/ops/STATE.json"
result="$(PROPERTY_RENTAL_REPO="$repo" "$repo/scripts/openclaw-supervisor-preflight.sh")"
printf '%s' "$result" | jq -e '.actionable | not' >/dev/null
jq '.repair.attempts=0 | .repair.requires_owner_decision=true' "$repo/ops/STATE.json" >"$repo/ops/state.tmp"
mv "$repo/ops/state.tmp" "$repo/ops/STATE.json"
result="$(PROPERTY_RENTAL_REPO="$repo" "$repo/scripts/openclaw-supervisor-preflight.sh")"
printf '%s' "$result" | jq -e '.actionable | not' >/dev/null

make_repo published-next
repo="$test_root/published-next/repo"
jq '.status="published" | .approval.publication_completed=true | .roadmap.current_id="V1-017"' "$repo/ops/STATE.json" >"$repo/ops/state.tmp"
mv "$repo/ops/state.tmp" "$repo/ops/STATE.json"
result="$(PROPERTY_RENTAL_REPO="$repo" "$repo/scripts/openclaw-supervisor-preflight.sh")"
printf '%s' "$result" | jq -e '.actionable and .state_issue == "published_next_candidate_dispatch_required"' >/dev/null

make_repo missing-handoff
repo="$test_root/missing-handoff/repo"
jq '.status="published" | .approval.publication_completed=true | .roadmap.current_id="V1-018" | .next_candidate=null | .next_action=""' "$repo/ops/STATE.json" >"$repo/ops/state.tmp"
mv "$repo/ops/state.tmp" "$repo/ops/STATE.json"
jq '.tranches=[.tranches[] | select(.id == "V1-018")] | .tranches[0].status="complete"' "$repo/ops/V1_ROADMAP.json" >"$repo/ops/roadmap.tmp"
mv "$repo/ops/roadmap.tmp" "$repo/ops/V1_ROADMAP.json"
result="$(PROPERTY_RENTAL_REPO="$repo" "$repo/scripts/openclaw-supervisor-preflight.sh")"
printf '%s' "$result" | jq -e '(.actionable | not) and .state_issue == "handoff_missing"' >/dev/null

echo "OpenClaw compact-state routing tests passed"
