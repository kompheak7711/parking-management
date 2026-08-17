#!/bin/sh
set -eu

source_repo="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT HUP INT TERM

make_repo() {
  scenario="$1"
  risk="$2"
  task="${3:-test}"
  repo="$test_root/$scenario/repo"
  state_dir="$test_root/$scenario/state"
  mkdir -p "$repo/scripts" "$repo/ops" "$state_dir"
  cp "$source_repo/scripts/openclaw-supervisor-dispatch.sh" "$repo/scripts/"
  cp "$source_repo/scripts/openclaw-supervisor-preflight.sh" "$repo/scripts/"
  cp "$source_repo/scripts/openclaw-task-packet.sh" "$repo/scripts/"
  cp "$source_repo/ops/OPENCLAW_SUPERVISOR_PROMPT.md" "$repo/ops/"
  jq -cn \
    --arg risk "$risk" \
    --arg task "$task" \
    '{status:"approved_ready",next_action:$task,blockers:[],next_candidate:{phase:"test",task:$task,status:"approved_ready",risk_class:$risk}}' \
    >"$repo/ops/STATE.json"
  printf '%s\n' '# Test' >"$repo/ops/NOW.md"
  printf '%s\n' '# Test' >"$repo/ops/QUEUE.md"
  git -C "$repo" init -q
  git -C "$repo" add .
  git -C "$repo" -c user.name=test -c user.email=test@example.invalid commit -qm test
}

fake_openclaw="$test_root/openclaw"
cp "$source_repo/scripts/test-fixtures/fake-openclaw.sh" "$fake_openclaw"
chmod +x "$fake_openclaw"

run_case() {
  scenario="$1"
  risk="$2"
  expected="$3"
  task="${4:-test}"
  make_repo "$scenario" "$risk" "$task"
  repo="$test_root/$scenario/repo"
  state_dir="$test_root/$scenario/state"
  calls="$test_root/$scenario/calls"
  FAKE_CALLS="$calls" \
  FAKE_SCENARIO="$scenario" \
  PROPERTY_RENTAL_REPO="$repo" \
  PROPERTY_RENTAL_DISPATCH_STATE_DIR="$state_dir" \
  PROPERTY_RENTAL_OPENCLAW_BIN="$fake_openclaw" \
  PROPERTY_RENTAL_MAX_IMMEDIATE_CYCLES=1 \
    "$repo/scripts/openclaw-supervisor-dispatch.sh"
  actual="$(cut -d '|' -f 1 "$calls" | paste -sd ',' -)"
  [ "$actual" = "$expected" ] || {
    echo "$scenario: expected $expected, got $actual" >&2
    exit 1
  }
}

run_case high high openai/gpt-5.6-sol
run_case unknown unknown openai/gpt-5.6-sol
run_case local_success low ollama/qwen35-hermes:latest
run_case local_fail low ollama/qwen35-hermes:latest,openai/gpt-5.6-sol
run_case local_stall low ollama/qwen35-hermes:latest,openai/gpt-5.6-sol
run_case mislabeled_sensitive low openai/gpt-5.6-sol 'payment formatting'

make_repo codex_stall high 'repair approved CI failure'
stall_repo="$test_root/codex_stall/repo"
stall_state_dir="$test_root/codex_stall/state"
stall_calls="$test_root/codex_stall/calls"
set +e
FAKE_CALLS="$stall_calls" \
FAKE_SCENARIO=codex_stall \
PROPERTY_RENTAL_REPO="$stall_repo" \
PROPERTY_RENTAL_DISPATCH_STATE_DIR="$stall_state_dir" \
PROPERTY_RENTAL_OPENCLAW_BIN="$fake_openclaw" \
PROPERTY_RENTAL_MAX_IMMEDIATE_CYCLES=2 \
  "$stall_repo/scripts/openclaw-supervisor-dispatch.sh"
stall_exit=$?
set -e
[ "$stall_exit" -eq 79 ]
[ "$(wc -l <"$stall_calls" | tr -d ' ')" -eq 2 ]
[ "$(sed -n '1p' "$stall_calls" | cut -d '|' -f 2 | sed 's/.*-//')" -eq 1 ]
[ "$(sed -n '2p' "$stall_calls" | cut -d '|' -f 2 | sed 's/.*-//')" -eq 2 ]

make_repo missing_next_action high 'bounded account migration'
missing_repo="$test_root/missing_next_action/repo"
jq 'del(.next_action)' "$missing_repo/ops/STATE.json" >"$missing_repo/ops/STATE.json.new"
mv "$missing_repo/ops/STATE.json.new" "$missing_repo/ops/STATE.json"
missing_preflight="$(PROPERTY_RENTAL_REPO="$missing_repo" "$missing_repo/scripts/openclaw-supervisor-preflight.sh")"
[ "$(printf '%s' "$missing_preflight" | jq -r '.actionable')" = true ]
[ "$(printf '%s' "$missing_preflight" | jq -r '.normalized')" = true ]
[ "$(printf '%s' "$missing_preflight" | jq -r '.state_issue')" = missing_next_action_derived_from_approved_candidate ]

make_repo completed_publication high 'next bounded candidate'
completed_repo="$test_root/completed_publication/repo"
jq '.status="complete_uncommitted" | .next_action="Do not commit or push without a new instruction." | .approval={status:"approved_ready"}' \
  "$completed_repo/ops/STATE.json" >"$completed_repo/ops/STATE.json.new"
mv "$completed_repo/ops/STATE.json.new" "$completed_repo/ops/STATE.json"
completed_preflight="$(PROPERTY_RENTAL_REPO="$completed_repo" "$completed_repo/scripts/openclaw-supervisor-preflight.sh")"
[ "$(printf '%s' "$completed_preflight" | jq -r '.actionable')" = true ]
[ "$(printf '%s' "$completed_preflight" | jq -r '.normalized')" = true ]
[ "$(printf '%s' "$completed_preflight" | jq -r '.state_issue')" = completed_tranche_publication_action_enforced ]
printf '%s' "$completed_preflight" | jq -e '.next_action | contains("standing authorization")' >/dev/null

make_repo completed_status_alias high 'no later candidate selected'
alias_repo="$test_root/completed_status_alias/repo"
jq '.status="implemented_awaiting_supervisor_review"
  | .approval={status:"approved_ready"}
  | .next_action="Wait for supervisor review."' \
  "$alias_repo/ops/STATE.json" >"$alias_repo/ops/STATE.json.new"
mv "$alias_repo/ops/STATE.json.new" "$alias_repo/ops/STATE.json"
alias_preflight="$(PROPERTY_RENTAL_REPO="$alias_repo" "$alias_repo/scripts/openclaw-supervisor-preflight.sh")"
[ "$(printf '%s' "$alias_preflight" | jq -r '.actionable')" = true ]
[ "$(printf '%s' "$alias_preflight" | jq -r '.normalized')" = true ]
[ "$(printf '%s' "$alias_preflight" | jq -r '.state_issue')" = completed_status_alias_publication_enforced ]
printf '%s' "$alias_preflight" | jq -e '.next_action | contains("complete_uncommitted")' >/dev/null

make_repo automatic_repair high 'original approved task'
repair_repo="$test_root/automatic_repair/repo"
jq '.status="not_verified"
  | .approval={status:"approved_active"}
  | .next_action="Wait for Owner approval."
  | .repair={attempts:0,max_attempts:2,scope_preserved:true,failure:"backend CI failed",requires_owner_decision:false,suspected_secret:false,scope_expansion:false,protected_operation:false}' \
  "$repair_repo/ops/STATE.json" >"$repair_repo/ops/STATE.json.new"
mv "$repair_repo/ops/STATE.json.new" "$repair_repo/ops/STATE.json"
repair_preflight="$(PROPERTY_RENTAL_REPO="$repair_repo" "$repair_repo/scripts/openclaw-supervisor-preflight.sh")"
[ "$(printf '%s' "$repair_preflight" | jq -r '.actionable')" = true ]
[ "$(printf '%s' "$repair_preflight" | jq -r '.state_issue')" = bounded_automatic_repair_authorized ]
printf '%s' "$repair_preflight" | jq -e '.next_action | contains("attempt 1 of 2")' >/dev/null

jq '.repair.max_attempts=99' "$repair_repo/ops/STATE.json" >"$repair_repo/ops/STATE.json.new"
mv "$repair_repo/ops/STATE.json.new" "$repair_repo/ops/STATE.json"
capped_preflight="$(PROPERTY_RENTAL_REPO="$repair_repo" "$repair_repo/scripts/openclaw-supervisor-preflight.sh")"
[ "$(printf '%s' "$capped_preflight" | jq -r '.repair_max_attempts')" -eq 2 ]

jq '.repair.attempts=2 | .repair.max_attempts=2' "$repair_repo/ops/STATE.json" >"$repair_repo/ops/STATE.json.new"
mv "$repair_repo/ops/STATE.json.new" "$repair_repo/ops/STATE.json"
exhausted_preflight="$(PROPERTY_RENTAL_REPO="$repair_repo" "$repair_repo/scripts/openclaw-supervisor-preflight.sh")"
[ "$(printf '%s' "$exhausted_preflight" | jq -r '.actionable')" = false ]

jq '.repair.attempts=0 | .repair.requires_owner_decision=true' "$repair_repo/ops/STATE.json" >"$repair_repo/ops/STATE.json.new"
mv "$repair_repo/ops/STATE.json.new" "$repair_repo/ops/STATE.json"
protected_preflight="$(PROPERTY_RENTAL_REPO="$repair_repo" "$repair_repo/scripts/openclaw-supervisor-preflight.sh")"
[ "$(printf '%s' "$protected_preflight" | jq -r '.actionable')" = false ]

make_repo published_next high 'completed tranche action'
published_next_repo="$test_root/published_next/repo"
jq '.status="published"
  | .phase="Phase 2D"
  | .risk_class="low"
  | .next_action="Completed tranche is published."
  | .next_candidate={phase:"Phase 2E",task:"approved password verifier service",status:"approved_ready",risk_class:"high"}' \
  "$published_next_repo/ops/STATE.json" >"$published_next_repo/ops/STATE.json.new"
mv "$published_next_repo/ops/STATE.json.new" "$published_next_repo/ops/STATE.json"
published_next_preflight="$(PROPERTY_RENTAL_REPO="$published_next_repo" "$published_next_repo/scripts/openclaw-supervisor-preflight.sh")"
[ "$(printf '%s' "$published_next_preflight" | jq -r '.actionable')" = true ]
[ "$(printf '%s' "$published_next_preflight" | jq -r '.state_issue')" = published_next_candidate_dispatch_required ]
published_next_packet="$(PROPERTY_RENTAL_REPO="$published_next_repo" "$published_next_repo/scripts/openclaw-task-packet.sh")"
[ "$(printf '%s' "$published_next_packet" | jq -r '.phase')" = 'Phase 2E' ]
[ "$(printf '%s' "$published_next_packet" | jq -r '.risk_class')" = high ]
printf '%s' "$published_next_packet" | jq -e '.task | contains("approved password verifier service")' >/dev/null

make_repo stale_published high 'prohibited unapproved deployment tranche'
stale_repo="$test_root/stale_published/repo"
published_base="$(git -C "$stale_repo" rev-parse HEAD)"
jq --arg commit "$published_base" '
  .status="verified_for_review"
  | .commit=$commit
  | .approval={status:"approved_complete"}
  | .next_action="Owner authorizes the unapproved candidate."
  | .next_candidate.status="not_approved"
' "$stale_repo/ops/STATE.json" >"$stale_repo/ops/STATE.json.new"
mv "$stale_repo/ops/STATE.json.new" "$stale_repo/ops/STATE.json"
git -C "$stale_repo" add ops/STATE.json
git -C "$stale_repo" -c user.name=test -c user.email=test@example.invalid commit -qm 'publish completed tranche'
git -C "$stale_repo" init -q --bare "$test_root/stale_published/origin.git"
git -C "$stale_repo" remote add origin "$test_root/stale_published/origin.git"
git -C "$stale_repo" push -qu origin HEAD
stale_preflight="$(PROPERTY_RENTAL_REPO="$stale_repo" "$stale_repo/scripts/openclaw-supervisor-preflight.sh")"
[ "$(printf '%s' "$stale_preflight" | jq -r '.actionable')" = true ]
[ "$(printf '%s' "$stale_preflight" | jq -r '.normalized')" = true ]
[ "$(printf '%s' "$stale_preflight" | jq -r '.state_issue')" = published_compact_state_reconciliation_required ]
printf '%s' "$stale_preflight" | jq -e '.next_action | startswith("Reconcile compact state with published HEAD ")' >/dev/null
stale_packet="$(PROPERTY_RENTAL_REPO="$stale_repo" "$stale_repo/scripts/openclaw-task-packet.sh")"
[ "$(printf '%s' "$stale_packet" | jq -r '.task')" = "$(printf '%s' "$stale_preflight" | jq -r '.next_action')" ]
printf '%s' "$stale_packet" | jq -e '.task | contains("prohibited unapproved deployment tranche") | not' >/dev/null

echo "OpenClaw routing tests passed"
