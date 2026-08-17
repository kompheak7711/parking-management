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
