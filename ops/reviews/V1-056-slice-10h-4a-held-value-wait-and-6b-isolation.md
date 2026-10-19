# V1-056 sub-slice 10h-4a — a waiting held-value Refund draft in the preview, and the 6b draft at READ COMMITTED only — review record

Sub-slice: 10h-4a (owner answer 1 of 2026-10-20 to the 10h-2 report; owner answer 2 of
2026-10-20 to the 10h-3 report). Migration `20270112_169` (two exact-text replacements: the
pending-draft filter of `app.final_settlement_preview` and the start of
`app.lease_deposit_reversal_source`, each part checked to match once). Base commit: 9f41f17.
Built on 2026-10-20 in a fresh session. Not pushed.

## Split

The pre-code design's search for paths at a stricter isolation level (the condition of the
answer (a) to Q-2026-10-19-143) found that the READ COMMITTED check in the 8e-1 refusal would
change the expected results of three committed tests that write its tables at REPEATABLE READ
with direct SQL (`test_invoice_migration.py::test_concurrent_duplicate_rent_period_and_billing_run_are_rejected`,
`::test_concurrent_invoice_issuance_serializes_lease_and_service_sources`,
`test_pet_payback_restoration_refusal_migration.py::test_at_repeatable_read_the_later_writer_fails_on_the_deposit_guard`).
That part is asked as Q-2026-10-20-145 point 1 and becomes sub-slice 10h-4b. 10h-4a builds the
rest.

## Built

- The 6b source refuses (55000, "A Lease Deposit forfeiture reversal draft is recorded and
  confirmed at READ COMMITTED") a call at any other isolation level, before any read. The 6b
  recorder still replays an exact repeat first; a refused confirm leaves the draft pending. No
  app path or committed test records or confirms a 6b draft at a stricter level. The slice 12
  note (5) of 10h-2 leaves the list; note (1) stays until 10h-4b.
- The security reviewer's note of the 10h-3 report, checked: real for `HELD_VALUE_REFUND`; not
  for the money a `REFUND` correction refunds. The preview also lists another Settlement's
  waiting `HELD_VALUE_REFUND` correction draft whose Credit a Settlement Customer holds (not a
  Settlement's own; a Deposit held-value draft names no Credit and is not listed). Each amount
  follows the existing rules in the order the drafts are decided; the refusal adds only a wait.
  The plan Credit steps and released Credits of other waiting correction drafts are asked as
  Q-2026-10-20-145 point 2.
- Committed tests changed: none, except the 27 head-revision strings in 15 modules.
- New module `test_settlement_held_value_wait_migration.py` (three tests, last in
  `scripts/database-test.sh`). Docs: docs/002 BR-SETTLE-002, docs/004 (the preview's issues and
  the 6b section), docs/010; traceability appended (three entries).

## Runs

| Run | Result |
|---|---|
| D1, D2 | catalog dumps for the pre-code design; D1 has two `REDACTED` markers (the input functions' amount bound), nothing copied from them |
| M1 | passed |
| FF1/I1/FC1 | passed (I1 sorted one import) |
| L1 | failed: 2 long lines in the new module after the formatter's rewrap (cause A, 1 of 2) |
| FF2/I2/FC2/L2 | passed (the catalog queries reuse the 10h-3 `STRUCTURE` constant) |
| Y1 | failed: a `dict[str, str]` passed where `dict[str, object]` is expected (cause B, 1 of 2) |
| FF3/I3/FC3/L3/Y2 | passed (the issue dict annotated) |
| T1 | 79 passed (10 modules in full-suite order) |
| U1 | 3867 passed |
| M2 | passed |
| P1 | 2411 passed, 1 failed: `test_credit_migration.py::test_credit_and_deposit_share_payment_budget_in_every_supported_isolation[deposit-read committed]`, 55P03 (`LockNotAvailable` of the NOWAIT lock in `app.assert_payment_excess_eligible`, the known DL-067 failure, in a module this sub-slice does not change) |
| P1R | 1 passed (that test alone, once, under the standing rerun-once rule) |
| (after the round 1 fixes) | |
| FF4/I4/FC4/L4/Y3 | passed |
| T2 | 3 passed (the new module) |
| U2 | 3867 passed |
| M3 | failed to start: `cd: backend: No such file or directory`; it was started from `backend/` (the unit run had left the shell there) and in the same batch as P2, against the run rules |
| P2 (stopped) | started in that same batch before M3 passed; stopped at once (its container had not started; output kept as `v1-056-10h-4a-P2-stopped.txt`); no leftover container |
| M4 | passed (alone, from the repository root) |
| P2 | 2412 passed |

Full outputs in `~/Development/prm-run-logs/v1-056-10h-4a-*.txt` and `v1-056-10h-4-D1.txt`,
`-D2.txt`, one file per attempt. After P2 only ops files changed (text).

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: no blocker, 2 should-fix, 5 notes. Security: no blocker, 1 should-fix, 4 notes.
Handled:
1. Independent S1: docs/002, docs/004 and the docs/010 entries written.
2. Independent S2 (reviewer's set-up): a fresh Lease none of whose people holds the Credit has no
   `PENDING_DRAFT` while the held-value draft waits.
3. Security note 2, independent N4 (reviewer's set-up): after the first held-value draft is
   withdrawn, B records its Settlement draft that applies the Credit; a new held-value draft then
   refuses that draft's confirm (55000 "The Final Settlement has blocking issues"); it stays
   pending, the Credit keeps 2,000 and B's line its 12,500; after the held-value confirm the early
   draft is withdrawn and B closes.
4. Security S1 (text): the Q-145 point 1 example used a write already refused by the Invoice row
   lock (40001); replaced by a write on an Invoice the closure does not touch (kept Deposits, the
   debt left on the ledger); option (b)'s deadlock cost added.
5. Independent N1 (text): a `REFUND` draft's released Credit is in its plan overlay, so another
   Lease's use of that Credit's other money also makes it stale (fail closed); plan reading (ii)
   and Q-145 point 2 corrected.
6. Independent N2 (text): the plan names every module with two Settlements of one Customer and a
   held-value Refund.
7. Not added (coverage only, the same preview path): a Deposit-variant held-value negative case
   (its `customer_credit_id` is JSON null), a closed B's correction step refused while a
   held-value draft waits (the 10h-3 test (iii) path), a hidden-identity reader (every preview
   reader holds `final_settlements.prepare` or `financial.approve`, and correction drafts are
   prepared under `final_settlements.prepare`).

## Review round 2 (fresh read-only subagents, during P2; same instructions)

Independent: no blocker, no should-fix, 5 notes. Security: no blocker, no should-fix, 5 notes.
Round 2 is clean, so there is no round 3. Text notes handled after P2 (ops files only):
1. Security N1: the Q-145 example also says the Customer has no Credit.
2. Independent N2, N3: the plan's 10h-4a status line and this record.
Notes kept for the owner (no change):
- Two held-value drafts on one Credit for two Settlements can hold each other only if recorded
  at the same moment (each recorder's plan check runs before the other commits); in sequence the
  second is refused. A held-value draft recorded during another Settlement's closure is stale at
  its confirm (P5S02). Both fail closed, as the 10h-3 race note; withdrawing or rejecting one
  draft clears them (security N2, N3; independent N4).
- A `final_settlements.prepare` holder can hold another Lease's closure, and the corrections of
  other closed Settlements of that Credit's Customer, with a held-value draft, only where held
  value exists; an approver can reject it (the same class as the Refund-draft holds).
- The 6b check also refuses `read uncommitted` (PostgreSQL runs it as READ COMMITTED); a
  role-level `default_transaction_isolation` would make every 6b call fail closed. The 10h-2
  forfeiture reversal trigger still has no isolation check of its own (every writer reaches it
  through the draft or a correction at READ COMMITTED; defence in depth only).
- Independent N1: the test does not assert that B's early draft is refused once the Credit holds
  0 before it is withdrawn (the existing stale check); independent N5: test 1's traceability
  entry could also name BR-SETTLE-012 and DL-032.

## Process deviation (for the owner)

M3 and P2 were sent in one batch, M3 from `backend/`. M3 failed to start and P2 started without
a passing migration-only check. P2 was stopped before its container started, M4 ran alone from
the repository root and passed, and P2 then ran alone. No result was taken from the stopped run.
