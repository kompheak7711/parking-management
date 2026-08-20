#!/bin/sh
set -eu

repo="${PROPERTY_RENTAL_REPO:-/Users/sokompheak/Development/property-rental-management}"
state_dir="${PROPERTY_RENTAL_DISPATCH_STATE_DIR:-/Users/sokompheak/.openclaw/state/property-rental-supervisor-dispatch}"
openclaw_bin="${PROPERTY_RENTAL_OPENCLAW_BIN:-openclaw}"
max_cycles="${PROPERTY_RENTAL_MAX_IMMEDIATE_CYCLES:-6}"
reconciler="${PROPERTY_RENTAL_RECONCILER_BIN:-$repo/scripts/openclaw-reconcile-published-state.sh}"
selector="${PROPERTY_RENTAL_SELECTOR_BIN:-$repo/scripts/openclaw-select-next-candidate.sh}"
local_model="${PROPERTY_RENTAL_LOCAL_SUPERVISOR_MODEL:-ollama/qwen35-hermes:latest}"
codex_model="${PROPERTY_RENTAL_CODEX_SUPERVISOR_MODEL:-openai/gpt-5.6-sol}"
usage_file="$state_dir/model-usage.jsonl"
lock_dir="$state_dir/lock"
attempt_dir="$state_dir/fingerprint-attempts"
exhausted_dir="$state_dir/repair-exhausted"
oversized_dir="$state_dir/oversized-fingerprints"
max_repair_attempts="${PROPERTY_RENTAL_MAX_REPAIR_ATTEMPTS:-2}"
token_ceiling=60000
case "$max_repair_attempts" in
  1|2) ;;
  *) max_repair_attempts=2 ;;
esac

preflight="$($repo/scripts/openclaw-supervisor-preflight.sh)"
actionable="$(printf '%s' "$preflight" | jq -r '.actionable')"
[ "$actionable" = true ] || exit 0

mkdir -p "$state_dir" "$attempt_dir" "$exhausted_dir" "$oversized_dir"
if ! mkdir "$lock_dir" 2>/dev/null; then
  exit 0
fi
result_file="$(mktemp)"
message_file="$(mktemp)"
compact_message_file="$(mktemp)"
trap 'rm -f "$result_file" "$message_file" "$compact_message_file"; rmdir "$lock_dir" 2>/dev/null || true' EXIT HUP INT TERM
cycle=0
cumulative_tokens=0

record_usage() {
  recorded_event="$1"
  recorded_route="$2"
  recorded_model="$3"
  recorded_session="$4"
  tokens="$(jq -r '.. | objects | select(has("usage")) | .usage.total? // empty' "$result_file" 2>/dev/null | sort -nr | head -1)"
  tokens="${tokens:-0}"
  cumulative_tokens=$((cumulative_tokens + tokens))
  jq -cn \
    --arg timestamp "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
    --arg fingerprint "$fingerprint" \
    --arg event "$recorded_event" \
    --arg route "$recorded_route" \
    --arg model "$recorded_model" \
    --arg session_id "$recorded_session" \
    --argjson cycle "$((cycle + 1))" \
    --argjson tokens "$tokens" \
    --argjson cumulative_tokens "$cumulative_tokens" \
    '{timestamp: $timestamp, fingerprint: $fingerprint, event: $event, route: $route, model: $model, session_id: $session_id, immediate_cycle: $cycle, total_tokens: $tokens, cumulative_tokens: $cumulative_tokens}' \
    >>"$usage_file"
}

record_token_ceiling_failure() {
  jq -cn \
    --arg timestamp "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
    --arg fingerprint "$fingerprint" \
    --arg route "$execution_route" \
    --arg model "$model" \
    --arg session_id "$execution_session" \
    --argjson cycle "$((cycle + 1))" \
    --argjson observed_total_tokens "$tokens" \
    --argjson token_ceiling "$token_ceiling" \
    '{timestamp:$timestamp,fingerprint:$fingerprint,event:"token_ceiling_failure",route:$route,model:$model,session_id:$session_id,immediate_cycle:$cycle,total_tokens:0,observed_total_tokens:$observed_total_tokens,token_ceiling:$token_ceiling}' \
    >>"$usage_file"
}

persist_oversized_tombstone() {
  tombstone_file="$oversized_dir/$fingerprint.json"
  tombstone_tmp="$(mktemp "$oversized_dir/.oversized-$fingerprint.XXXXXX")"
  jq -cn \
    --arg timestamp "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
    --arg fingerprint "$fingerprint" \
    --arg route "$execution_route" \
    --arg model "$model" \
    --arg session_id "$execution_session" \
    --argjson observed_total_tokens "$tokens" \
    --argjson token_ceiling "$token_ceiling" \
    '{status:"oversized_fingerprint_suppressed",timestamp:$timestamp,actionable_fingerprint:$fingerprint,route:$route,model:$model,session_id:$session_id,observed_total_tokens:$observed_total_tokens,token_ceiling:$token_ceiling}' \
    >"$tombstone_tmp"
  mv "$tombstone_tmp" "$tombstone_file"
}

gateway_timed_out() {
  jq -e '.. | strings | select(test("timeout|timed out"; "i"))' "$result_file" >/dev/null 2>&1
}

write_compact_fallback_message() {
  compact_route="$1"
  compact_model="$2"
  {
    printf '%s\n' 'Fresh dispatcher-controlled gateway-timeout fallback. Do not load or infer any prior conversational or tool context.'
    printf '\nDeterministic compact state:\n```json\n%s\n```\n' "$preflight"
    printf '\nDeterministic task packet:\n```json\n%s\n```\n' "$task_packet"
    printf '\nExecution route: %s. Use model %s.\n' "$compact_route" "$compact_model"
    printf '\nInvoke Hermes with this exact task-file command; do not use an undeclared shell variable:\n`PROPERTY_RENTAL_HERMES_ROUTE=%s %s/scripts/openclaw-hermes-task.sh %s`\n' "$compact_route" "$repo" "$task_file"
  } >"$compact_message_file"
}

execute_cycle() {
  cycle_route="$1"
  cycle_model="$2"
  cycle_session="$3"
  cycle_message_file="$4"
  gateway_params="$(jq -cn \
    --rawfile message "$cycle_message_file" \
    --arg agent_id property-rental-supervisor \
    --arg session_id "$cycle_session" \
    --arg model "$cycle_model" \
    --arg idempotency_key "$cycle_session" \
    '{message:$message,agentId:$agent_id,sessionId:$session_id,model:$model,thinking:"low",timeout:1800,idempotencyKey:$idempotency_key}')"
  : >"$result_file"
  if "$openclaw_bin" gateway call agent \
    --expect-final \
    --json \
    --timeout 1800000 \
    --params "$gateway_params" >"$result_file"; then
    execution_route="$cycle_route"
    execution_session="$cycle_session"
    record_usage model_cycle "$execution_route" "$cycle_model" "$execution_session"
    return 0
  fi

  execution_route="$cycle_route-gateway"
  execution_session="$cycle_session"
  record_usage gateway_failure "$execution_route" "$cycle_model" "$execution_session"
  gateway_timed_out || return 1

  fallback_session="$cycle_session-fallback-$(date -u '+%Y%m%dT%H%M%S')-$$-$cycle"
  write_compact_fallback_message "$cycle_route" "$cycle_model"
  echo "Gateway request failed; dispatcher started a fresh compact-only local fallback session $fallback_session." >&2
  : >"$result_file"
  if "$openclaw_bin" agent \
    --local \
    --agent property-rental-supervisor \
    --session-id "$fallback_session" \
    --message-file "$compact_message_file" \
    --model "$cycle_model" \
    --thinking low \
    --timeout 1800 \
    --json >"$result_file"; then
    execution_route="$cycle_route-gateway-fallback"
    execution_session="$fallback_session"
    record_usage gateway_fallback_model_cycle "$execution_route" "$cycle_model" "$execution_session"
    return 0
  fi
  execution_route="$cycle_route-gateway-fallback"
  execution_session="$fallback_session"
  record_usage gateway_fallback_failure "$execution_route" "$cycle_model" "$execution_session"
  return 1
}

enforce_token_ceiling() {
  if [ "$tokens" -gt "$token_ceiling" ]; then
    persist_oversized_tombstone
    record_token_ceiling_failure
    echo "Supervisor model cycle exceeded the 60000-token tranche ceiling ($tokens); further identical runs are suppressed." >&2
    exit 78
  fi
  if [ "$route" = local ] && [ "$tokens" -gt 30000 ]; then
    echo "Local supervisor cycle exceeded the 30000-token tranche ceiling ($tokens); publication requires Codex review." >&2
    exit 78
  fi
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
  if [ "$(printf '%s' "$preflight" | jq -r '.state_issue')" = authorized_candidate_selection_required ]; then
    "$selector"
    cycle=$((cycle + 1))
    continue
  fi

  fingerprint="$(printf '%s' "$preflight" | shasum -a 256 | awk '{print $1}')"
  oversized_file="$oversized_dir/$fingerprint.json"
  if [ -f "$oversized_file" ]; then
    echo "Actionable fingerprint $fingerprint previously exceeded the 60000-token tranche ceiling; no model call was made." >&2
    exit 78
  fi
  attempt_key="$(printf '%s' "$preflight" | jq -c '{attempt_tranche_id,active_cycle,status,next_action,state_issue,repair_failure}' | shasum -a 256 | awk '{print $1}')"
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
        --arg tranche_id "$(printf '%s' "$preflight" | jq -r '.attempt_tranche_id')" \
        --arg phase "$(printf '%s' "$preflight" | jq -r '.active_cycle')" \
        --arg next_action "$(printf '%s' "$preflight" | jq -r '.next_action')" \
        --argjson attempts "$attempts" \
        '{status:"repair_exhausted",timestamp:$timestamp,attempt_key:$attempt_key,fingerprint:$fingerprint,tranche_id:$tranche_id,phase:$phase,next_action:$next_action,attempts:$attempts,alerted:false}' \
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

  session_id="property-rental-$fingerprint-$route-$attempts"
  if ! execute_cycle "$route" "$model" "$session_id" "$message_file"; then
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
    session_id="property-rental-$fingerprint-$route-$attempts"
    if ! execute_cycle "$route" "$model" "$session_id" "$message_file"; then
      if [ "$attempts" -lt "$max_repair_attempts" ]; then
        cycle=$((cycle + 1))
        continue
      fi
      echo "Local cycle and bounded Codex escalation both failed; identical state will not be retried automatically." >&2
      exit 70
    fi
  fi

  enforce_token_ceiling

  postflight="$($repo/scripts/openclaw-supervisor-preflight.sh)"
  if [ "$(printf '%s' "$postflight" | jq -r '.actionable')" = true ] && [ "$postflight" = "$preflight" ] && [ "$route" = local ]; then
    route=codex-escalation
    model="$codex_model"
    printf '\nExecution route override: codex-escalation. Invoke Hermes with PROPERTY_RENTAL_HERMES_ROUTE=codex. Local execution returned without advancing compact state; diagnose and complete one bounded Codex escalation.\n' >>"$message_file"
    session_id="property-rental-$fingerprint-$route-$attempts"
    if ! execute_cycle "$route" "$model" "$session_id" "$message_file"; then
      if [ "$attempts" -lt "$max_repair_attempts" ]; then
        cycle=$((cycle + 1))
        continue
      fi
      echo "Local no-progress cycle and Codex escalation both failed." >&2
      exit 70
    fi
    enforce_token_ceiling
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
