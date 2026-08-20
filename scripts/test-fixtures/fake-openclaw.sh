#!/bin/sh
set -eu

command_kind=agent
transport=gateway
model=""
session=""
message_file=""
message=""
params=""
if [ "${1:-}" = gateway ] && [ "${2:-}" = call ] && [ "${3:-}" = agent ]; then
  command_kind=gateway-call
  shift 3
elif [ "${1:-}" = agent ]; then
  shift
fi
while [ "$#" -gt 0 ]; do
  case "$1" in
    --model) model="$2"; shift 2 ;;
    --session-id) session="$2"; shift 2 ;;
    --message-file) message_file="$2"; shift 2 ;;
    --params) params="$2"; shift 2 ;;
    --local) transport=local; shift ;;
    *) shift ;;
  esac
done
if [ "$command_kind" = gateway-call ]; then
  model="$(printf '%s' "$params" | jq -r '.model')"
  session="$(printf '%s' "$params" | jq -r '.sessionId')"
  message="$(printf '%s' "$params" | jq -r '.message')"
else
  message="$(cat "$message_file")"
fi
prior_calls=0
if [ -f "$FAKE_CALLS" ]; then
  prior_calls="$(wc -l <"$FAKE_CALLS" | tr -d ' ')"
fi
call_number=$((prior_calls + 1))
message_capture="$FAKE_CALLS.message.$call_number"
printf '%s\n' "$message" >"$message_capture"
printf '%s|%s|%s|%s\n' "$model" "$session" "$transport" "$message_capture" >>"$FAKE_CALLS"
grep -q 'openclaw-hermes-task.sh' "$message_capture"
task_file="$(sed -n 's/.*openclaw-hermes-task.sh \([^`]*\)`.*/\1/p' "$message_capture" | tail -1)"
[ -f "$task_file" ]
[ -n "$(tr -d '[:space:]' <"$task_file")" ]
if [ "$FAKE_SCENARIO" = gateway_timeout_oversized ] && [ "$call_number" -eq 1 ]; then
  [ "$command_kind" = gateway-call ]
  printf '%s\n' '{"ok":false,"error":{"code":"TIMEOUT","message":"gateway request timed out"}}'
  exit 1
fi
if [ "$FAKE_SCENARIO" = gateway_timeout_oversized ] && [ "$call_number" -eq 2 ]; then
  [ "$transport" = local ]
  printf '%s\n' '{"usage":{"total":42904}}'
  exit 0
fi
if [ "$FAKE_SCENARIO" = gateway_timeout_oversized ]; then
  printf '%s\n' '{"usage":{"input":1678,"output":151,"cacheRead":99072,"total":100901}}'
  exit 0
fi
if [ "$FAKE_SCENARIO" = ceiling_exact ]; then
  jq '.status="published" | .next_action=""' "$PROPERTY_RENTAL_REPO/ops/STATE.json" >"$PROPERTY_RENTAL_REPO/ops/STATE.json.new"
  mv "$PROPERTY_RENTAL_REPO/ops/STATE.json.new" "$PROPERTY_RENTAL_REPO/ops/STATE.json"
  printf '%s\n' '{"usage":{"total":60000}}'
  exit 0
fi
case "$FAKE_SCENARIO:$model" in
  local_fail:ollama/*)
    printf '%s\n' '{"usage":{"total":1200}}'
    exit 1
    ;;
  local_stall:ollama/*)
    printf '%s\n' '{"usage":{"total":1300}}'
    exit 0
    ;;
  codex_stall:openai/*)
    printf '%s\n' '{"usage":{"total":1500}}'
    exit 0
    ;;
esac
case "$FAKE_SCENARIO:$model" in
  local_fail:openai/*|local_stall:openai/*)
    grep -q 'Execution route override: codex-escalation' "$message_capture"
    grep -q 'PROPERTY_RENTAL_HERMES_ROUTE=codex' "$message_capture"
    ;;
esac
jq '.status="published" | .next_action=""' "$PROPERTY_RENTAL_REPO/ops/STATE.json" >"$PROPERTY_RENTAL_REPO/ops/STATE.json.new"
mv "$PROPERTY_RENTAL_REPO/ops/STATE.json.new" "$PROPERTY_RENTAL_REPO/ops/STATE.json"
printf '%s\n' '{"usage":{"total":1400}}'
