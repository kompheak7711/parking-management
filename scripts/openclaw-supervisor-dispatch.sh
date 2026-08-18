#!/bin/sh
set -eu

repo="${PROPERTY_RENTAL_REPO:-/Users/sokompheak/Development/property-rental-management}"
state_dir="${PROPERTY_RENTAL_DISPATCH_STATE_DIR:-/Users/sokompheak/.openclaw/state/property-rental-supervisor-dispatch}"
openclaw_bin="${PROPERTY_RENTAL_OPENCLAW_BIN:-openclaw}"
max_cycles="${PROPERTY_RENTAL_MAX_IMMEDIATE_CYCLES:-6}"
reconciler="${PROPERTY_RENTAL_RECONCILER_BIN:-$repo/scripts/openclaw-reconcile-published-state.sh}"
local_model="${PROPERTY_RENTAL_LOCAL_SUPERVISOR_MODEL:-ollama/qwen35-hermes:latest}"
codex_model="${PROPERTY_RENTAL_CODEX_SUPERVISOR_MODEL:-openai/gpt-5.6-sol}"
usage_file="$state_dir/model-usage.jsonl"
lock_dir="$state_dir/lock"
attempt_dir="$state_dir/fingerprint-attempts"
exhausted_dir="$state_dir/repair-exhausted"
max_repair_attempts="${PROPERTY_RENTAL_MAX_REPAIR_ATTEMPTS:-2}"
case "$max_repair_attempts" in
  1|2) ;;
  *) max_repair_attempts=2 ;;
esac

preflight="$($repo/scripts/openclaw-supervisor-preflight.sh)"
actionable="$(printf '%s' "$preflight" | jq -r '.actionable')"
[ "$actionable" = true ] || exit 0

mkdir -p "$state_dir" "$attempt_dir" "$exhausted_dir"
if ! mkdir "$lock_dir" 2>/dev/null; then
  exit 0
fi
result_file="$(mktemp)"
message_file="$(mktemp)"
trap 'rm -f "$result_file" "$message_file"; rmdir "$lock_dir" 2>/dev/null || true' EXIT HUP INT TERM
cycle=0
cumulative_tokens=0

record_usage() {
  recorded_route="$1"
  recorded_model="$2"
  tokens="$(jq -r '.. | objects | select(has("usage")) | .usage.total? // empty' "$result_file" 2>/dev/null | sort -nr | head -1)"
  tokens="${tokens:-0}"
  cumulative_tokens=$((cumulative_tokens + tokens))
  jq -cn \
    --arg timestamp "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
    --arg fingerprint "$fingerprint" \
    --arg route "$recorded_route" \
    --arg model "$recorded_model" \
    --argjson cycle "$((cycle + 1))" \
    --argjson tokens "$tokens" \
    --argjson cumulative_tokens "$cumulative_tokens" \
    '{timestamp: $timestamp, fingerprint: $fingerprint, route: $route, model: $model, immediate_cycle: $cycle, total_tokens: $tokens, cumulative_tokens: $cumulative_tokens}' \
    >>"$usage_file"
}

while [ "$cycle" -lt "$max_cycles" ]; do
  preflight="$($repo/scripts/openclaw-supervisor-preflight.sh)"
  actionable="$(printf '%s' "$preflight" | jq -r '.actionable')"
  [ "$actionable" = true ] || exit 0

  if [ "$(printf '%s' "$preflight" | jq -r '.state_issue')" = published_compact_state_reconciliation_required ]; then
    "$reconciler"
    cycle=$((cycle + 1))
    continue
  fi

  fingerprint="$(printf '%s' "$preflight" | shasum -a 256 | awk '{print $1}')"
  attempt_key="$(printf '%s' "$preflight" | jq -c '{active_cycle,status,next_action,state_issue,repair_failure}' | shasum -a 256 | awk '{print $1}')"
  attempt_file="$attempt_dir/$attempt_key"
  exhausted_file="$exhausted_dir/$attempt_key.json"
  attempts=0
  if [ -f "$attempt_file" ]; then
    attempts="$(cat "$attempt_file")"
  fi
  if [ "$attempts" -ge "$max_repair_attempts" ]; then
    if [ ! -f "$exhausted_file" ]; then
      jq -cn \
        --arg timestamp "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        --arg attempt_key "$attempt_key" \
        --arg fingerprint "$fingerprint" \
        --arg phase "$(printf '%s' "$preflight" | jq -r '.active_cycle')" \
        --arg next_action "$(printf '%s' "$preflight" | jq -r '.next_action')" \
        --argjson attempts "$attempts" \
        '{status:"repair_exhausted",timestamp:$timestamp,attempt_key:$attempt_key,fingerprint:$fingerprint,phase:$phase,next_action:$next_action,attempts:$attempts,alerted:false}' \
        >"$exhausted_file"
    fi
    exit 0
  fi
  attempts=$((attempts + 1))
  printf '%s\n' "$attempts" >"$attempt_file"
  : >"$result_file"

  task_packet="$($repo/scripts/openclaw-task-packet.sh)"
  task_file="$state_dir/hermes-task-$fingerprint.txt"
  printf '%s\n' "$(printf '%s' "$task_packet" | jq -r '.task')" >"$task_file"
  risk_class="$(printf '%s' "$task_packet" | jq -r '.risk_class')"
  route=codex
  model="$codex_model"
  if [ "$risk_class" = low ]; then
    route=local
    model="$local_model"
  fi

  {
    cat "$repo/ops/OPENCLAW_SUPERVISOR_PROMPT.md"
    printf '\n\nDeterministic task packet:\n```json\n%s\n```\n' "$task_packet"
    printf '\nExecution route: %s. Use model %s.\n' "$route" "$model"
    printf '\nInvoke Hermes with this exact task-file command; do not use an undeclared shell variable:\n`PROPERTY_RENTAL_HERMES_ROUTE=%s %s/scripts/openclaw-hermes-task.sh %s`\n' "$route" "$repo" "$task_file"
    if [ "$attempts" -gt 1 ]; then
      printf '\nThis is bounded automatic repair attempt %s of %s for an unchanged approved technical failure. Diagnose the prior no-progress/tool failure, preserve scope, add regression evidence, and do not request redundant Owner permission.\n' "$attempts" "$max_repair_attempts"
    fi
  } >"$message_file"

  if ! "$openclaw_bin" agent \
    --agent property-rental-supervisor \
    --session-id "property-rental-$fingerprint-$route-$attempts" \
    --message-file "$message_file" \
    --model "$model" \
    --thinking low \
    --timeout 1800 \
    --json >"$result_file"; then
    record_usage "$route" "$model"
    if [ "$route" != local ]; then
      if [ "$attempts" -lt "$max_repair_attempts" ]; then
        cycle=$((cycle + 1))
        continue
      fi
      echo "Supervisor Codex cycle failed after $attempts bounded attempts; Owner attention is required." >&2
      exit 70
    fi
    route=codex-escalation
    model="$codex_model"
    printf '\nExecution route override: codex-escalation. Invoke Hermes with PROPERTY_RENTAL_HERMES_ROUTE=codex. The local execution failed; diagnose it and perform one bounded Codex escalation.\n' >>"$message_file"
    : >"$result_file"
    if ! "$openclaw_bin" agent \
      --agent property-rental-supervisor \
      --session-id "property-rental-$fingerprint-$route-$attempts" \
      --message-file "$message_file" \
      --model "$model" \
      --thinking low \
      --timeout 1800 \
      --json >"$result_file"; then
      record_usage "$route" "$model"
      if [ "$attempts" -lt "$max_repair_attempts" ]; then
        cycle=$((cycle + 1))
        continue
      fi
      echo "Local cycle and bounded Codex escalation both failed; identical state will not be retried automatically." >&2
      exit 70
    fi
  fi

  record_usage "$route" "$model"

  if [ "$route" = local ] && [ "$tokens" -gt 30000 ]; then
    echo "Local supervisor cycle exceeded the 30000-token tranche ceiling ($tokens); publication requires Codex review." >&2
    exit 78
  fi

  if [ "$tokens" -gt 60000 ]; then
    echo "Supervisor model cycle exceeded the 60000-token tranche ceiling ($tokens); further identical runs are suppressed." >&2
    exit 78
  fi

  postflight="$($repo/scripts/openclaw-supervisor-preflight.sh)"
  if [ "$(printf '%s' "$postflight" | jq -r '.actionable')" = true ] && [ "$postflight" = "$preflight" ] && [ "$route" = local ]; then
    route=codex-escalation
    model="$codex_model"
    printf '\nExecution route override: codex-escalation. Invoke Hermes with PROPERTY_RENTAL_HERMES_ROUTE=codex. Local execution returned without advancing compact state; diagnose and complete one bounded Codex escalation.\n' >>"$message_file"
    : >"$result_file"
    if ! "$openclaw_bin" agent \
      --agent property-rental-supervisor \
      --session-id "property-rental-$fingerprint-$route-$attempts" \
      --message-file "$message_file" \
      --model "$model" \
      --thinking low \
      --timeout 1800 \
      --json >"$result_file"; then
      record_usage "$route" "$model"
      if [ "$attempts" -lt "$max_repair_attempts" ]; then
        cycle=$((cycle + 1))
        continue
      fi
      echo "Local no-progress cycle and Codex escalation both failed." >&2
      exit 70
    fi
    record_usage "$route" "$model"
    postflight="$($repo/scripts/openclaw-supervisor-preflight.sh)"
  fi

  if [ "$(printf '%s' "$postflight" | jq -r '.actionable')" = true ] && [ "$postflight" = "$preflight" ]; then
    if [ "$attempts" -lt "$max_repair_attempts" ]; then
      cycle=$((cycle + 1))
      continue
    fi
    echo "Supervisor completed without advancing compact state after $attempts bounded attempts; Owner attention is required." >&2
    exit 79
  fi

  cycle=$((cycle + 1))
done

# A bounded chain prevents a mistaken state transition from creating an unbounded
# model loop. If more approved work remains, the ordinary scheduler resumes it.
exit 0
