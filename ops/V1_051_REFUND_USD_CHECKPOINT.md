# V1-051 USD Refund persistence checkpoint — partial, unpublished

Updated 2026-09-05T22:51:00Z. Parent7655b099d9decccf7cacf07cc97622671102bef8.
Sole checkout /Users/sokompheak/Development/property-rental-management-v1-051, codex/v1-051-direct.
Authority ops/CODEX_TAKEOVER_V1_048_053.md and frozen ops/V1_051_SCOPE.md unchanged.
This is NOT full V1-051 acceptance, publication or closure. Creditc162b07 remains accepted.

## Implemented private persistence slice

Extend existing app.refunds/refund_corrections in unpublished migration41 only.
Exactly one Payment/Credit/Deposit source; legacy Deposit requires its Reservation
lifecycle and unchanged full-refund/coordinated-replacement guards. No historical
financial row rewrite or fabricated return evidence. USD-only constraints remain
until the later KHR slice; active-Pet and Final Settlement requests fail closed.

USD Payment excess and Credit Refunds recheck active actor, source recipient, current
availability and strict source chronology under shared Payment MVCC serialization.
Direct Payment Refunds consume Payment; Credit Refunds consume Credit only.
Current and historical Payment/Credit budgets, reversal/proposal dependencies and
Receipt captured disposition summary include the new consumers without double debit.

Append-only USD value corrections require exact demonstrated return amount/currency,
timestamp/method/evidence/reason/actor/authority. Correction reversals reference one
active original, preserve exact opposite effects and reject already-spent or reversed
source value. Net Refund stays between zero and immutable original. New events audit
atomically with Property-local date and source links. New helpers are private:
no runtime/financial grants or generic writes, no public Refund command facade yet.

## Verification evidence

- New33 PostgreSQL cases pass within full isolated679PASS/zero skips103.23seconds.
  Includes concurrent USD Payment/Credit spending, stale Repeatable Read rejection,
  source reversal/verified-return dependencies, historical Deposit overlap,
  Credit application after return, immutability and atomic audit, wrong amount/evidence,
  and fail-closed original-KHR-as-USD. Existing Reservation/Deposit regressions pass.
- Backend876PASS/656database-only skips39.63seconds; all656 separately covered by
  the full PostgreSQL gate. Format139/Ruff/mypy139/build/import PASS.
- Traceability and publication secret guard PASS. New suite explicitly registered.
- Initial test lint/type invocation failures fixed by correct repository invocation,
  typed override dictionaries and normalized test layout; no assertion weakening.
- Migration SHA25620260300d35790c2d74de78475b4b878487fa33647e7bd308291d8e02d5c12bb.
- Test SHA2566b5a86f3dd2d7d70d7b942784f6a671f015a3f878453cffee13477e0b2561c88.
- Automation189PASS66.534seconds; deployment configuration, state routing, watchdog,
  retired restoration, shell syntax and script compilation PASS. Staged/frozen cumulative
  whitespace and fresh independent Astra max Standard read-only exact-checkpoint review next.
  Complete frontend/audits/full cumulative V1-051 review remain future release gates.

## Exact next action

Freeze this partial checkpoint and inspect one fresh independent review, with no
duplicate worker or worktree. Resolve findings through bounded materially different
corrections. On zero findings continue same51checkout: transactional USD Refund
commands, immutable exact replay/response, separate Property capabilities and bounded
reads; then original-KHR/Credit-KHR and qualified active-Pet paths, retained-history
upgrade/concurrency tests, and bounded Credit history. No full51release until complete.

OpenClaw singleton658ffdaf-1ac1-45a6-a842-f5f7d7a226eb disabled30minutes/no nextRun;
no running tasks or V1-051 claim/attempt. Existing tracking-only cardc5621f97 remains
blocked solely against OpenClaw admission, not an owner blocker. Main44d93 and remote
cc3d18e unchanged; predecessorCI33986122538 all4SUCCESS. All126worktrees retained.
Existing native10minute follow-up ACTIVE. Actual coordinator22:36turn_context
gpt-6-astra/xhigh; localservice_tierdefault, provider Standard attestation unavailable.
After full51closure proceed52then53; at53closedpausefollowup/leaveOpenClawdisabled/no54.
No production/access/credentials/customerdata/paid/destructive/forcepush/historyrewrite
or retained-worktree deletion. No routine authorization required.
