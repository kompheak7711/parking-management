# V1-019 context-budget and restoration-recovery repair — independently reviewed; publication pending

- Objective: repair only the bounded V1-019 `sign_in` context and post-exit recovery
  gates under existing durable V1 authorization. No renewed Owner authorization is used.
- Baseline: clean synchronized `d6eb7e73610b2a72cf38f4b32468226e9e76a436` on
  `implementation/foundation`; product files and canonical specifications are unchanged.
- Incident: natural supervisor sequence 365 and Hermes session
  `61d145e0655c5298cbcfa576fff3ff78` completed 2/2 provider calls with 16,881
  input tokens, 422 output tokens, 17,303 counted tokens, and 9,216 separately
  recorded cache-read tokens. No in-flight overshoot or provider-parameter error occurred.
- Context root cause: the packet directed broad compact-state and repository rereads, then
  a one-byte-equals-one-token reservation falsely predicted 109,152 tokens. The repaired
  schema-four packet materializes only exact state, authorization, acceptance, requirement,
  and deterministic path evidence; the guard blocks broad reads and planning and caps tool output.
- Estimation repair: the unchanged 60,000-token ceiling now uses a conservative serialized
  request estimate with persisted byte classes, provider-observed calibration, and a 1,024-token
  validation margin. Unavailable estimation is a recoverable zero-model-attempt routing fault.
- Restoration root cause: the monitor disabled the supervisor after the first recoverable run
  even though `recovery_pending=true`, generation 1, `sign_in` attempt 1 remained eligible.
- Restoration repair: health is bound to run sequences after the captured floor, inherited
  `consecutive_errors` is evidence only, `RECOVERY_SCHEDULED` is nonterminal, and the supervisor
  remains enabled through the exact retry. Unknown/protected failures and bounded exhaustion
  alone use `RESTORATION_FAILED_CLOSED` and disable the supervisor.
- Regression evidence: the exact 9,614-byte historical packet (SHA-256
  `2a6e8126bc9c285f5f400137ab0b97dc87c4c1ca7b40523591128a387d9ccc3b`) and observed
  tool-output sizes prove no broad compact reread, no false 109,152-token reservation, and
  progress or an eligible fresh recovery. End-to-end restoration covers recoverable-then-success
  and exhaustion.
- Verification: PASS. The automation gate passed 108 tests plus compact-state routing,
  visibility-watchdog, shell syntax, and Python compilation. The complete profile passed all
  15/15 gates: backend 333 passed with 105 expected environment skips, disposable PostgreSQL
  105 passed, frontend 3 passed, formatting, linting, strict typing, builds, audits, scope,
  traceability, JSON, and diff checks. Evidence:
  `/private/tmp/property-rental-v1-019-context-restoration-repair-final.json`.
- Independent review: PASS on the exact 13-path snapshot. The first pass found six material
  boundary/test gaps; all six were remediated and regression-covered, and the final pass found
  no blocking or material issue. The reviewer made no edits.
- Safety boundary: supervisor `658ffdaf-1ac1-45a6-a842-f5f7d7a226eb` remains disabled;
  V1-019 product implementation and V1-020 have not started; overlap detection is unchanged.
- Exact next action: publish and require successful GitHub Actions, then install the corrected
  post-exit continuation. It may enable only the exact bounded
  V1-019 `sign_in` recovery after repository-bound CLI overlap clears and must verify progress.

<!-- AUTOMATION_STATUS_BEGIN -->
- Automation candidate state: V1-019 approved and active; product implementation has not started.
- Automation exact next action: publish this repair, then permit only the scheduled V1-019 sign-in recovery.
<!-- AUTOMATION_STATUS_END -->
<!-- POST_EXIT_RESTORATION_BEGIN -->
- The supervisor remains disabled while this repository-bound CLI is active.
- Restoration success requires zero overlap and post-repair run-sequence evidence of bounded V1-019 sign-in progress.
<!-- POST_EXIT_RESTORATION_END -->
