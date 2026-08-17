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

echo "OpenClaw routing tests passed"
