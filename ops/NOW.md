# Automation visibility and watchdog guardrails

- Objective: prevent silent stops and ambiguous idle periods while keeping routine
  OpenClaw checks model-free and Telegram notifications non-repetitive.
- Current task: complete and published on `implementation/foundation`; no implementation
  cycle is active.
- Supervisor: token-free preflight remains every 30 minutes. An unchanged actionable
  fingerprint now receives one model attempt only, uses an isolated session with low
  reasoning, records usage, and stops above the 100,000-token cycle ceiling.
- Visibility watchdog: model-free every 30 minutes; reports new publication/approval,
  stalls over two hours, unhealthy supervisor state, and recovery. Event signatures
  are persisted outside Git and identical messages are suppressed.
- Daily report: model-free at 08:00 Asia/Phnom_Penh; records health, last check/state
  update, Git status, 24-hour model usage, idle reason, blockers, commits, and exact
  next action.
- Verification: Python compilation, Ruff, shell syntax, healthy publication,
  deduplication, failure, recovery, and stalled-work fixtures passed. The live watchdog
  completed silently in 66 ms with no model usage; the live daily report completed in
  1.046 seconds and delivered to Telegram. All repository and database gates passed.
- Canonical docs and application code remain unchanged.
- Blocker: none.
- Exact next action: obtain owner approval for the first bounded Phase 2 identity and
  security tranche.
