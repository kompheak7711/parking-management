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
  cp "$source_repo/scripts/openclaw-hermes-task.sh" "$repo/scripts/"
  cp "$source_repo/scripts/openclaw-select-next-candidate.sh" "$repo/scripts/"
  cp "$source_repo/scripts/openclaw-reconcile-published-state.sh" "$repo/scripts/"
  cp "$source_repo/scripts/openclaw-wait-for-ci.sh" "$repo/scripts/"
  cp "$source_repo/scripts/openclaw-supervisor-preflight.sh" "$repo/scripts/"
  cp "$source_repo/scripts/openclaw-task-packet.sh" "$repo/scripts/"
  cp "$source_repo/ops/OPENCLAW_SUPERVISOR_PROMPT.md" "$repo/ops/"
  jq -cn \
    --arg risk "$risk" \
    --arg task "$task" \
    '{status:"approved_ready",active_cycle:"test-cycle",next_action:$task,blockers:[],next_candidate:{phase:"test",task:$task,status:"approved_ready",risk_class:$risk}}' \
    >"$repo/ops/STATE.json"
  printf '%s\n' '# Test' >"$repo/ops/NOW.md"
  printf '%s\n' '# Test' >"$repo/ops/QUEUE.md"
  printf '%s\n' '{"schema_version":1,"total_tranches":1,"tranches":[]}' >"$repo/ops/V1_ROADMAP.json"
  git -C "$repo" init -q
  git -C "$repo" config user.name test
  git -C "$repo" config user.email test@example.invalid
  git -C "$repo" add .
  git -C "$repo" commit -qm test
}

fake_openclaw="$test_root/openclaw"
cp "$source_repo/scripts/test-fixtures/fake-openclaw.sh" "$fake_openclaw"
chmod +x "$fake_openclaw"

helper_capture="$test_root/helper-capture"
helper_wrapper="$test_root/helper-wrapper"
cat >"$helper_wrapper" <<'EOF'
#!/bin/sh
printf '%s' "$1" >"$HELPER_CAPTURE"
EOF
chmod +x "$helper_wrapper"
helper_task="$test_root/helper-task"
printf 'line one\nline two with ${UNEXPANDED}\n' >"$helper_task"
HELPER_CAPTURE="$helper_capture" \
PROPERTY_RENTAL_HERMES_WRAPPER="$helper_wrapper" \
  "$source_repo/scripts/openclaw-hermes-task.sh" "$helper_task"
[ "$(cat "$helper_capture")" = "$(cat "$helper_task")" ]

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
set +e
FAKE_CALLS="$stall_calls" \
FAKE_SCENARIO=codex_stall \
PROPERTY_RENTAL_REPO="$stall_repo" \
PROPERTY_RENTAL_DISPATCH_STATE_DIR="$stall_state_dir" \
PROPERTY_RENTAL_OPENCLAW_BIN="$fake_openclaw" \
PROPERTY_RENTAL_MAX_IMMEDIATE_CYCLES=2 \
  "$stall_repo/scripts/openclaw-supervisor-dispatch.sh"
exhausted_exit=$?
set -e
[ "$exhausted_exit" -eq 0 ]
[ "$(wc -l <"$stall_calls" | tr -d ' ')" -eq 2 ]
exhausted_file="$(find "$stall_state_dir/repair-exhausted" -type f -name '*.json' -print -quit)"
[ -n "$exhausted_file" ]
jq -e '.status == "repair_exhausted" and .attempts == 2 and .alerted == false' "$exhausted_file" >/dev/null

# A published predecessor's exhausted repair metadata and legacy attempt fingerprint must
# not consume any attempts belonging to the newly selected successor tranche.
make_repo tranche_isolation high 'published predecessor'
tranche_repo="$test_root/tranche_isolation/repo"
tranche_state_dir="$test_root/tranche_isolation/state"
tranche_calls="$test_root/tranche_isolation/calls"
printf '%s\n' 'Remaining v1 application tranches are authorized when bounded by canonical documents 001-010.' >"$tranche_repo/ops/QUEUE.md"
jq '
  .status="published"
  | .phase="Identity"
  | .tranche="Published V1-013"
  | .task="Published V1-013 repair"
  | .active_cycle="v1-013-published-repair"
  | .roadmap={current_id:"V1-013",total:2}
  | .approval={status:"approved_complete",implementation_started:true,implementation_completed:true,publication_completed:true}
  | .next_action="Select the approved successor."
  | .next_candidate={phase:"unselected",task:"No successor selected.",status:"not_approved",risk_class:"high",authorities:[]}
  | .repair={tranche_id:"V1-013",attempts:2,max_attempts:2,scope_preserved:true,failure:"V1-013 dependency audit failed",requires_owner_decision:false,suspected_secret:false,scope_expansion:false,protected_operation:false,last_outcome:"repair_attempt_2_published"}
' "$tranche_repo/ops/STATE.json" >"$tranche_repo/ops/STATE.json.new"
mv "$tranche_repo/ops/STATE.json.new" "$tranche_repo/ops/STATE.json"
printf '%s\n' '{"schema_version":1,"total_tranches":2,"tranches":[{"id":"V1-013","order":13,"phase":"Identity","task":"Published V1-013 repair","status":"complete","authorization":"complete","risk_class":"high"},{"id":"V1-014","order":14,"phase":"Identity","task":"Persistent browser-session and revocation store","dependencies":["V1-013"],"authorities":["DB-AUTH-004","API-097","SEC-015-018"],"include":["opaque sessions"],"exclude":["remote access"],"status":"approved_ready","authorization":"durable_v1","risk_class":"high","protected_operation":false}]}' >"$tranche_repo/ops/V1_ROADMAP.json"
git -C "$tranche_repo" add ops/STATE.json ops/QUEUE.md ops/V1_ROADMAP.json
git -C "$tranche_repo" -c user.name=test -c user.email=test@example.invalid commit -qm 'publish V1-013 repair exhaustion'
git -C "$tranche_repo" init -q --bare "$test_root/tranche_isolation/origin.git"
git -C "$tranche_repo" remote add origin "$test_root/tranche_isolation/origin.git"
git -C "$tranche_repo" push -qu -u origin HEAD
PROPERTY_RENTAL_REPO="$tranche_repo" \
PROPERTY_RENTAL_SELECTION_SKIP_REMOTE=true \
  "$tranche_repo/scripts/openclaw-select-next-candidate.sh"
tranche_preflight="$(PROPERTY_RENTAL_REPO="$tranche_repo" "$tranche_repo/scripts/openclaw-supervisor-preflight.sh")"
jq -e '
  .status == "active"
  and .active_cycle == "v1-014-persistent-browser-session-and-revocation-store"
  and .roadmap.current_id == "V1-014"
  and .repair.tranche_id == "V1-014"
  and .repair.attempts == 0
  and .repair.failure == null
' "$tranche_repo/ops/STATE.json" >/dev/null
printf '%s' "$tranche_preflight" | jq -e '
  .attempt_tranche_id == "V1-014"
  and .repair_tranche_id == "V1-014"
  and .repair_attempts == 0
  and .repair_failure == ""
' >/dev/null
legacy_attempt_key="$(printf '%s' "$tranche_preflight" | jq -c '{active_cycle,status,next_action,state_issue,repair_failure}' | shasum -a 256 | awk '{print $1}')"
mkdir -p "$tranche_state_dir/fingerprint-attempts"
printf '2\n' >"$tranche_state_dir/fingerprint-attempts/$legacy_attempt_key"
set +e
FAKE_CALLS="$tranche_calls" \
FAKE_SCENARIO=codex_stall \
PROPERTY_RENTAL_REPO="$tranche_repo" \
PROPERTY_RENTAL_DISPATCH_STATE_DIR="$tranche_state_dir" \
PROPERTY_RENTAL_OPENCLAW_BIN="$fake_openclaw" \
PROPERTY_RENTAL_MAX_IMMEDIATE_CYCLES=2 \
  "$tranche_repo/scripts/openclaw-supervisor-dispatch.sh"
tranche_exit=$?
set -e
[ "$tranche_exit" -eq 79 ]
[ "$(wc -l <"$tranche_calls" | tr -d ' ')" -eq 2 ]
[ "$(sed -n '1p' "$tranche_calls" | cut -d '|' -f 2 | sed 's/.*-//')" -eq 1 ]
[ "$(sed -n '2p' "$tranche_calls" | cut -d '|' -f 2 | sed 's/.*-//')" -eq 2 ]

usage_ledger="$test_root/model-usage.jsonl"
now="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
old='2000-01-01T00:00:00Z'
printf '{"timestamp":"%s","total_tokens":1234}\n{"timestamp":"%s","total_tokens":9999}\nnot-json\n' "$now" "$old" >"$usage_ledger"
PROPERTY_RENTAL_MODEL_USAGE_LEDGER="$usage_ledger" python3 - "$source_repo/scripts/openclaw-daily-report.py" <<'PY'
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("daily_report", sys.argv[1])
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
assert module.recent_model_usage() == [1234]
PY

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

make_repo verified_unpublished_publication high 'next bounded candidate'
verified_unpublished_repo="$test_root/verified_unpublished_publication/repo"
jq '.status="verified_unpublished"
  | .next_action="Review and publish only after an explicit commit/push request."
  | .approval={status:"approved_ready"}' \
  "$verified_unpublished_repo/ops/STATE.json" >"$verified_unpublished_repo/ops/STATE.json.new"
mv "$verified_unpublished_repo/ops/STATE.json.new" "$verified_unpublished_repo/ops/STATE.json"
verified_unpublished_preflight="$(PROPERTY_RENTAL_REPO="$verified_unpublished_repo" "$verified_unpublished_repo/scripts/openclaw-supervisor-preflight.sh")"
[ "$(printf '%s' "$verified_unpublished_preflight" | jq -r '.actionable')" = true ]
[ "$(printf '%s' "$verified_unpublished_preflight" | jq -r '.normalized')" = true ]
[ "$(printf '%s' "$verified_unpublished_preflight" | jq -r '.state_issue')" = completed_tranche_publication_action_enforced ]
printf '%s' "$verified_unpublished_preflight" | jq -e '.next_action | contains("standing authorization")' >/dev/null

make_repo future_completion_status high 'next bounded candidate'
future_completion_repo="$test_root/future_completion_status/repo"
jq '.status="future_worker_completion_label"
  | .next_action="Wait for an explicit instruction."
  | .approval={status:"approved_ready",implementation_started:true,implementation_completed:true,publication_completed:false}' \
  "$future_completion_repo/ops/STATE.json" >"$future_completion_repo/ops/STATE.json.new"
mv "$future_completion_repo/ops/STATE.json.new" "$future_completion_repo/ops/STATE.json"
future_completion_preflight="$(PROPERTY_RENTAL_REPO="$future_completion_repo" "$future_completion_repo/scripts/openclaw-supervisor-preflight.sh")"
[ "$(printf '%s' "$future_completion_preflight" | jq -r '.actionable')" = true ]
[ "$(printf '%s' "$future_completion_preflight" | jq -r '.normalized')" = true ]
[ "$(printf '%s' "$future_completion_preflight" | jq -r '.state_issue')" = completed_tranche_publication_action_enforced ]
printf '%s' "$future_completion_preflight" | jq -e '
  .implementation_started == true
  and .implementation_completed == true
  and .publication_completed == false
  and (.next_action | contains("standing authorization"))
' >/dev/null

make_repo unknown_state_contract high 'approved bounded work'
unknown_state_repo="$test_root/unknown_state_contract/repo"
printf '%s\n' 'Remaining v1 application tranches are authorized when bounded by canonical documents 001-010.' >"$unknown_state_repo/ops/QUEUE.md"
jq '.status="unexpected_worker_state"
  | .approval={status:"approved_ready",implementation_started:false,implementation_completed:false,publication_completed:false}' \
  "$unknown_state_repo/ops/STATE.json" >"$unknown_state_repo/ops/STATE.json.new"
mv "$unknown_state_repo/ops/STATE.json.new" "$unknown_state_repo/ops/STATE.json"
unknown_state_preflight="$(PROPERTY_RENTAL_REPO="$unknown_state_repo" "$unknown_state_repo/scripts/openclaw-supervisor-preflight.sh")"
[ "$(printf '%s' "$unknown_state_preflight" | jq -r '.actionable')" = true ]
[ "$(printf '%s' "$unknown_state_preflight" | jq -r '.normalized')" = true ]
[ "$(printf '%s' "$unknown_state_preflight" | jq -r '.status_known')" = false ]
[ "$(printf '%s' "$unknown_state_preflight" | jq -r '.state_issue')" = state_contract_repair_authorized ]
printf '%s' "$unknown_state_preflight" | jq -e '.next_action | contains("bounded compact-state contract repair")' >/dev/null

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
  | .repair={tranche_id:"test-cycle",attempts:0,max_attempts:2,scope_preserved:true,failure:"backend CI failed",requires_owner_decision:false,suspected_secret:false,scope_expansion:false,protected_operation:false}' \
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
  | .roadmap={current_id:"V1-001",total:2}
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

make_repo authorized_placeholder high 'completed tranche action'
placeholder_repo="$test_root/authorized_placeholder/repo"
printf '%s\n' 'Remaining v1 application tranches are authorized when bounded by canonical documents 001-010.' >"$placeholder_repo/ops/QUEUE.md"
jq '.status="published"
  | .phase="Phase 2D"
  | .roadmap={current_id:"V1-001",total:2}
  | .approval={status:"approved_complete"}
  | .next_action="Owner selects the next candidate."
  | .next_candidate={phase:"unselected",task:"No subsequent implementation candidate has been selected or authorized.",status:"not_approved",risk_class:"high",authorities:[]}' \
  "$placeholder_repo/ops/STATE.json" >"$placeholder_repo/ops/STATE.json.new"
mv "$placeholder_repo/ops/STATE.json.new" "$placeholder_repo/ops/STATE.json"
printf '%s\n' '{"schema_version":1,"total_tranches":2,"tranches":[{"id":"V1-001","order":1,"status":"complete"},{"id":"V1-002","order":2,"phase":"Phase 2E","task":"bounded successor","status":"approved_ready","authorization":"durable_v1","risk_class":"high","protected_operation":false}]}' >"$placeholder_repo/ops/V1_ROADMAP.json"
placeholder_preflight="$(PROPERTY_RENTAL_REPO="$placeholder_repo" "$placeholder_repo/scripts/openclaw-supervisor-preflight.sh")"
[ "$(printf '%s' "$placeholder_preflight" | jq -r '.actionable')" = true ]
[ "$(printf '%s' "$placeholder_preflight" | jq -r '.state_issue')" = authorized_candidate_selection_required ]
printf '%s' "$placeholder_preflight" | jq -e '.queue_candidate.phase == "Phase 2E"' >/dev/null

# A concrete record for the just-published current tranche is not a successor.
# Route to the next roadmap entry instead of silently stalling publication.
jq '.next_candidate={id:"V1-001",roadmap_id:"V1-001",phase:"Phase 2D",task:"completed current tranche",status:"complete_uncommitted",risk_class:"high"}' \
  "$placeholder_repo/ops/STATE.json" >"$placeholder_repo/ops/STATE.json.new"
mv "$placeholder_repo/ops/STATE.json.new" "$placeholder_repo/ops/STATE.json"
stale_current_preflight="$(PROPERTY_RENTAL_REPO="$placeholder_repo" "$placeholder_repo/scripts/openclaw-supervisor-preflight.sh")"
[ "$(printf '%s' "$stale_current_preflight" | jq -r '.actionable')" = true ]
[ "$(printf '%s' "$stale_current_preflight" | jq -r '.state_issue')" = authorized_candidate_selection_required ]
printf '%s' "$stale_current_preflight" | jq -e '.queue_candidate.phase == "Phase 2E"' >/dev/null

for variant in null missing alternate; do
  case "$variant" in
    null) filter='.next_candidate=null | .next_action="Await an explicitly bounded next candidate; do not infer or broaden scope."' ;;
    missing) filter='del(.next_candidate) | del(.next_action)' ;;
    alternate) filter='.next_candidate={phase:"unselected",task:"Choose later",status:"not_approved"} | .next_action="Nothing else selected."' ;;
  esac
  jq "$filter" "$placeholder_repo/ops/STATE.json" >"$placeholder_repo/ops/STATE.json.new"
  mv "$placeholder_repo/ops/STATE.json.new" "$placeholder_repo/ops/STATE.json"
  variant_preflight="$(PROPERTY_RENTAL_REPO="$placeholder_repo" "$placeholder_repo/scripts/openclaw-supervisor-preflight.sh")"
  [ "$(printf '%s' "$variant_preflight" | jq -r '.state_issue')" = authorized_candidate_selection_required ]
done

jq '.next_candidate={phase:"Production",task:"Provision actual production secrets",status:"not_approved",risk_class:"high"}' \
  "$placeholder_repo/ops/STATE.json" >"$placeholder_repo/ops/STATE.json.new"
mv "$placeholder_repo/ops/STATE.json.new" "$placeholder_repo/ops/STATE.json"
protected_candidate_preflight="$(PROPERTY_RENTAL_REPO="$placeholder_repo" "$placeholder_repo/scripts/openclaw-supervisor-preflight.sh")"
[ "$(printf '%s' "$protected_candidate_preflight" | jq -r '.actionable')" = false ]

jq '.next_candidate=null' \
  "$placeholder_repo/ops/STATE.json" >"$placeholder_repo/ops/STATE.json.new"
mv "$placeholder_repo/ops/STATE.json.new" "$placeholder_repo/ops/STATE.json"
printf '%s\n' '{"schema_version":1,"total_tranches":2,"tranches":[{"id":"V1-001","order":1,"status":"complete"}]}' >"$placeholder_repo/ops/V1_ROADMAP.json"
missing_handoff_preflight="$(PROPERTY_RENTAL_REPO="$placeholder_repo" "$placeholder_repo/scripts/openclaw-supervisor-preflight.sh")"
[ "$(printf '%s' "$missing_handoff_preflight" | jq -r '.actionable')" = false ]
[ "$(printf '%s' "$missing_handoff_preflight" | jq -r '.state_issue')" = handoff_missing ]

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

make_reconciliation_repo() {
  reconciliation_scenario="$1"
  make_repo "$reconciliation_scenario" high 'prohibited unapproved deployment tranche'
  reconciliation_repo="$test_root/$reconciliation_scenario/repo"
  reconciliation_base="$(git -C "$reconciliation_repo" rev-parse HEAD)"
  jq --arg commit "$reconciliation_base" '
    .status="verified_for_review"
    | .commit=$commit
    | .approval={status:"approved_complete",implementation_started:true,implementation_completed:true,publication_completed:false}
    | .next_action="Owner authorizes the unapproved candidate."
    | .next_candidate.status="not_approved"
  ' "$reconciliation_repo/ops/STATE.json" >"$reconciliation_repo/ops/STATE.json.new"
  mv "$reconciliation_repo/ops/STATE.json.new" "$reconciliation_repo/ops/STATE.json"
  cat >"$reconciliation_repo/scripts/openclaw-wait-for-ci.sh" <<'EOF'
#!/bin/sh
set -eu
printf '%s\n' "$1" >>"$FAKE_CI_CALLS"
case "$FAKE_CI_MODE" in
  success) exit 0 ;;
  failed) exit 74 ;;
  missing) exit 75 ;;
  *) exit 2 ;;
esac
EOF
  chmod +x "$reconciliation_repo/scripts/openclaw-wait-for-ci.sh"
  git -C "$reconciliation_repo" add ops/STATE.json scripts/openclaw-wait-for-ci.sh
  git -C "$reconciliation_repo" commit -qm 'publish completed tranche'
  git -C "$reconciliation_repo" init -q --bare "$test_root/$reconciliation_scenario/origin.git"
  git -C "$reconciliation_repo" remote add origin "$test_root/$reconciliation_scenario/origin.git"
  git -C "$reconciliation_repo" push -qu -u origin HEAD
}

# Candidate CI is a precondition of publication-state mutation. A failed or missing
# candidate run must leave compact state, local HEAD, and the remote unchanged.
for ci_mode in failed missing; do
  make_reconciliation_repo "reconcile_$ci_mode"
  reconcile_repo="$reconciliation_repo"
  reconcile_head="$(git -C "$reconcile_repo" rev-parse HEAD)"
  reconcile_state="$(shasum -a 256 "$reconcile_repo/ops/STATE.json" | awk '{print $1}')"
  reconcile_calls="$test_root/reconcile_$ci_mode/ci-calls"
  set +e
  FAKE_CI_CALLS="$reconcile_calls" \
  FAKE_CI_MODE="$ci_mode" \
  PROPERTY_RENTAL_REPO="$reconcile_repo" \
    "$reconcile_repo/scripts/openclaw-reconcile-published-state.sh"
  reconcile_exit=$?
  set -e
  case "$ci_mode" in
    failed) [ "$reconcile_exit" -eq 74 ] ;;
    missing) [ "$reconcile_exit" -eq 75 ] ;;
  esac
  [ "$(git -C "$reconcile_repo" rev-parse HEAD)" = "$reconcile_head" ]
  [ "$(git -C "$reconcile_repo" rev-parse '@{upstream}')" = "$reconcile_head" ]
  [ "$(shasum -a 256 "$reconcile_repo/ops/STATE.json" | awk '{print $1}')" = "$reconcile_state" ]
  [ -z "$(git -C "$reconcile_repo" status --porcelain=v1)" ]
  [ "$(cat "$reconcile_calls")" = "$reconcile_head" ]
done

# Successful candidate CI permits reconciliation, and the pushed reconciliation
# commit remains subject to its own CI verification.
make_reconciliation_repo reconcile_success
reconcile_repo="$reconciliation_repo"
candidate_head="$(git -C "$reconcile_repo" rev-parse HEAD)"
reconcile_calls="$test_root/reconcile_success/ci-calls"
FAKE_CI_CALLS="$reconcile_calls" \
FAKE_CI_MODE=success \
PROPERTY_RENTAL_REPO="$reconcile_repo" \
  "$reconcile_repo/scripts/openclaw-reconcile-published-state.sh"
reconciliation_head="$(git -C "$reconcile_repo" rev-parse HEAD)"
[ "$reconciliation_head" != "$candidate_head" ]
[ "$(git -C "$reconcile_repo" rev-parse '@{upstream}')" = "$reconciliation_head" ]
[ "$(sed -n '1p' "$reconcile_calls")" = "$candidate_head" ]
[ "$(sed -n '2p' "$reconcile_calls")" = "$reconciliation_head" ]
[ "$(wc -l <"$reconcile_calls" | tr -d ' ')" -eq 2 ]
jq -e --arg commit "$candidate_head" '
  .status == "published"
  and .approval.publication_completed == true
  and .commit == $commit
' "$reconcile_repo/ops/STATE.json" >/dev/null

echo "OpenClaw routing tests passed"
