# V1-019 sign-in context-routing v4 repair — independently reviewed; publication pending

- Objective: recover only the exhausted bounded V1-019 `sign_in` route under the
  Owner's direct-takeover authorization. Product and canonical files remain unchanged.
- Baseline: synchronized `d6eb7e73610b2a72cf38f4b32468226e9e76a436` on
  `implementation/foundation`; supervisor `658ffdaf-1ac1-45a6-a842-f5f7d7a226eb`
  remains disabled during repair and publication.
- Exact incident: three preserved Hermes sessions ended with zero completed substages and
  zero product paths. The last two repeated the same ten-file full-read batch, returned the
  complete 36,000-byte session allowance, and then reached the unchanged 60,000-token guard.
- Packet repair: schema 5 deterministically embeds the AST-derived login contract, the
  aggregate-bounded current frontend evidence, exact requirement excerpts, five frontend read paths,
  eight exact write paths, and the shortest sign-in implementation sequence.
- Guard repair: the full provider-returned tool-call batch is reserved atomically before any
  tool executes. Oversized batches return valid structured results; an identical retry becomes
  a separate context-materialization checkpoint and consumes no ceiling-recovery attempt.
  Reservation identity mirrors every Hermes schema coercion. Policy-rejected and unreserved calls
  fail closed before another provider call, and parallel rejection controls reserve and charge the
  same cumulative tool-context allowance atomically.
- Recovery repair: the exact exhausted candidate, attempt, failure, marker, manifests, tasks,
  budgets, usage, and session diagnostics are archived before this authorization is consumed
  once. Unknown/protected failures cannot reuse it. Materialization-marker reentry is supported.
- Scope repair: the Hermes manifest enforces the packet's exact sign-in write allowlist.
  The login URL is derived from router and decorator AST literals and fails closed on drift.
- Verification: PASS, complete profile 15/15. Backend 333 passed with 105 expected local
  database skips; disposable PostgreSQL 105 passed; frontend 3 passed; automation 124 passed;
  format, lint, typing, builds, audits, traceability, JSON, publication guards, and diff checks
  passed. Evidence: `/private/tmp/property-rental-v1-019-routing-v4-verification-final.json`.
- Independent review: nine passes found thirty findings (sixteen P1, twelve P2, two P3);
  all were corrected and regression-covered. The latest pass closed production middleware
  fail-open behavior, interrupted-attempt and partial-work restoration reentry, crash-atomic
  marker resolution, exact incident-session validation, and artifact symlink escape handling,
  including symlinked parent directories. Final independent verdict: PASS, no material findings.
- Safety: token ceiling remains exactly 60,000. V1-020 has not started. No product attempt or
  prior historical evidence was deleted or rewritten.
- Exact next action: publish only this repair, require successful
  GitHub Actions, then run the repair-bound continuation and prove bounded `sign_in` progress.

<!-- AUTOMATION_STATUS_BEGIN -->
- Automation candidate state: V1-019 approved and active; product implementation has not started.
- Automation exact next action: publish this repair, then permit only the fresh bounded V1-019 sign-in sequence.
<!-- AUTOMATION_STATUS_END -->
