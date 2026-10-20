# V1-056 sub-slice 10h-4b — the closed Final Settlement refusal at READ COMMITTED only — review record

Sub-slice: 10h-4b (owner answer (a) to Q-2026-10-20-145 point 1, 2026-10-20). Migration
`20270113_170` (one exact-text replacement at the start of the body of
`app.refuse_closed_final_settlement_change`, checked to match once). Base commit: 72840fc.
Built on 2026-10-20 in a fresh session. Not pushed.

## Owner answers recorded first

Q-2026-10-20-145 point 1 (a); point 2 answered "(a), your recommendation" with a reason that
describes option (b), so it is asked again as Q-2026-10-20-146 (recommendation (a); nothing is
built for it; the slice 12 note and the slice 11 "out of date, record it again" message are
recorded in the plan either way); the run-rule slip of 10h-4a (every script by its absolute path
from the repository root, alone in its own tool call, working directory checked first); the
pending rename in `test_deposit_receipt_refund_out_migration.py` (that file is not touched in
10h-4b). Recorded in docs/010 and ops/V1_056_QUESTIONS.md.

## Built

- The 8e-1 refusal, the first BEFORE trigger (`a0_`) of Invoices (insert and the guarded
  UPDATE), one-time charges, VOID events, Adjustments and their reversals, Late-payment
  decisions, Charges and Charge corrections, refuses (55000, "An Invoice, Adjustment or
  Late-payment record is written at READ COMMITTED") a write at any other isolation level, before
  any read, also on a Lease with no Final Settlement. No app path writes these tables at a
  stricter level (every REPEATABLE READ app path is read only; the writers pin READ COMMITTED or
  use the server default); services and routes are unchanged. The slice 12 note (1) of 10h-2
  leaves the list (note (5) left with 10h-4a; both now marked closed in the plan).

## Committed tests changed (owner answer (a) to Q-145 point 1)

1. `test_invoice_migration.py::test_concurrent_duplicate_rent_period_and_billing_run_are_rejected`:
   the Adjustment race, the VOID-against-Adjustment race and the Charge correction race expect
   `["55000", "55000"]` instead of one `40001` and one commit; because nothing is written, the
   checked amounts follow: the line obligation 80,000 (was 30,000) after the refused race and
   70,000 (was 20,000) after the unchanged READ COMMITTED replay pair; the Charge 8,000 (was
   7,900). Unchanged: the Rent period race (`invoice_lines`, 23P01), the replay pair (23505), the
   generated-run race.
2. `test_invoice_migration.py::test_concurrent_invoice_issuance_serializes_lease_and_service_sources`:
   the REPEATABLE READ issue against the termination expects 55000 (was 40001); the service-rate
   race is unchanged.
3. `test_pet_payback_restoration_refusal_migration.py`: the REPEATABLE READ issue of the charge
   billed again expects (55000, the new message) instead of the Deposit guard's 40001; the
   REPEATABLE READ forfeiture still fails on the Deposit guard (40001). Renamed under the standing
   rule: `test_at_repeatable_read_the_later_writer_fails_on_the_deposit_guard` became
   `test_at_repeatable_read_an_issue_is_refused_and_a_forfeiture_fails_on_the_deposit_guard`
   (traceability entry 3,198 updated: id and note).
4. The 27 head-revision strings in 15 modules (revision strings only; a script checked each
   file's count).

Each changed assertion carries a short comment. The traceability notes of tests 1 and 2 (entries
among the first 1,598) are not edited; docs/010 says they are now out of date.

## What the three tests protected, still tested at READ COMMITTED (owner's condition)

| Guard | Test at READ COMMITTED |
|---|---|
| Two credit Adjustments on one line (Invoice lock, `invoice-financial` guard) | new: `test_at_read_committed_a_second_credit_adjustment_waits_and_is_refused` |
| VOID against an Adjustment | new: `test_at_read_committed_an_adjustment_waits_for_a_void_and_is_refused` |
| Late-payment Charge correction (Charge lock, `late-charge` guard) | new (review round 1): `test_at_read_committed_a_second_charge_reduction_waits_and_is_refused`; also the service test `test_late_payment_migration.py::test_concurrent_decisions_and_over_reductions_commit_at_most_one_effect` (no proof that its writers overlap) |
| Invoice issue against a termination (`invoice-lease` guard) | new: `test_at_read_committed_an_issue_waits_for_a_termination_and_is_refused` |
| Duplicate Rent period | unchanged: the Rent period race of test 1 writes `invoice_lines` (not guarded) and keeps 23P01 at REPEATABLE READ; the replay pair keeps 23505 at READ COMMITTED |
| Pet Deposit guard | committed: `test_pet_payback_restoration_refusal_migration.py::test_a_restoration_and_a_forfeiture_racing_for_the_deposit_lock_never_both_commit` (both orders); and the REPEATABLE READ forfeiture half of the renamed test |
| Service-rate source guard | unchanged second race of test 2 |

## New tests

New module `test_settlement_closed_change_isolation_migration.py` (seven tests, last in
`scripts/database-test.sh`): (1) the Q-145 gap (REPEATABLE READ and SERIALIZABLE snapshots
older than the Settlement's start; 12,500 Damage line; 55000, nothing written; P5S01 at READ
COMMITTED); (2) a bare insert into each of the eight tables and the guarded issue, at both
levels, refused with the new message before any read; (3) to (5) and (7) the READ COMMITTED
races above (the later writer waits for the earlier writer's lock, proven by
`wait_until_blocked_by`, and is refused after its commit); (6) least privilege and
forward-only. Traceability: seven entries appended.

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump of the five guard functions for the design (`v1-056-10h-4b-D1.txt`), no `REDACTED` marker |
| M1 | passed |
| FF1/I1/FC1/L1/Y1 | passed (FF1 reformatted the new module) |
| U1 | 3867 passed |
| T1 (stopped) | started with a 10-minute background limit, too short for 53 modules; stopped at once (container healthy, no test had run; output kept as `v1-056-10h-4b-T1-stopped.txt`); no leftover container |
| T1 | 1055 passed (53 modules in full-suite order: every module that writes at a stricter level, the changed modules, the head-string modules, the 8e-1 module, the new module) |
| M2 | passed |
| P1 | 2418 passed |
| (after the round 1 fixes) | |
| FF2/I2/FC2/L2/Y2 | passed |
| U2 | 3867 passed |
| T2 | 7 passed (the new module) |
| M3 | passed |
| P2 | 2419 passed |
| (after the round 2 fixes) | |
| FF3/I3/FC3/L3/Y3 | passed |
| U3 | 3867 passed |
| T3 | 42 passed (`test_invoice_migration.py` and the new module, the files changed since P2) |
| M4 | passed |
| P3 | 2416 passed, 3 failed: `test_refund_migration.py::test_usd_refund_correction_rejects_unverified_or_inconsistent_value[changes2]`, `[changes3]` and `[changes4]`, each 55P03 (`LockNotAvailable` of the NOWAIT lock in `app.assert_payment_excess_eligible`, the known DL-067 failure, in a module this sub-slice does not change) |
| P3R | 3 passed (those three tests alone, once, under the standing rerun-once rule) |

Full outputs in `~/Development/prm-run-logs/v1-056-10h-4b-*.txt`, one file per attempt.

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: no blocker, 3 should-fix, 5 notes. Security: no blocker, no should-fix, 6 notes.
Handled:
1. Independent S1 (reviewer's set-up): the Late-payment service test does not prove that its two
   writers overlap; new READ COMMITTED test (7): an 8,000 Charge, the holder's reduction of 100
   (previous 8,000) uncommitted, a second reduction of 100 (previous 8,000) waits for the Charge
   lock and is refused at its commit (40001 "Late-payment correction previous balance is stale");
   one correction, 7,900.
2. Independent S2 (text): the slice 12 notes (1) and (5) of 10h-2 are marked closed in the plan.
3. Independent S3 (text): the Q-146 slice 12 note and the slice 11 message are written in the
   plan.
4. Independent notes: test (1) pins the 12,500 line; the traceability ids of the READ COMMITTED
   tests name DB-TXN-003 (and BR-INV-040 for the issue) instead of DB-SETTLE-005 and BR-LEASE-021;
   this record written.
5. Security note 5: the generator's own 25001 in `test_billing_service_migration.py` was
   confirmed by T1 (passed unchanged).
Notes kept for the owner (no change):
- The message follows the 10h-2 and 10h-4a style ("... is recorded at READ COMMITTED"); a
  reviewer found "is written only at READ COMMITTED" clearer, and it does not name VOID events or
  one-time charges.
- READ UNCOMMITTED is also refused (PostgreSQL runs it as READ COMMITTED; fail closed).
- A role- or database-level `default_transaction_isolation` stricter than READ COMMITTED would
  make every Invoice, Adjustment and Late-payment write fail closed, and some services would show
  a misleading conflict message; money stays right; pinning READ COMMITTED on every mutation
  connection is a later hardening (slice 12 list).
- The Lease-change branch of the guarded Invoice UPDATE is not exercised at a stricter level (the
  same first statement of the same function).
- The invoice races check the SQLSTATE only; the new test (2) pins the message per table.
- `wait_until_blocked_by`'s failure text names the Deposit lock (cosmetic, reused helper).

## Review round 2 (fresh read-only subagents, during P2; same instructions)

Independent: no blocker, 3 should-fix (a test comment, traceability ids, text), 5 notes.
Security: no blocker, no should-fix, 5 notes. Every should-fix is a test or a text change, so
under the round 3 rule they are fixed and round 3 runs without asking the owner (after a full unit
run and a full PostgreSQL run).
Handled:
1. Independent S1: the comment in `test_invoice_migration.py` now names the new module for the
   READ COMMITTED Charge correction race (also security note 2).
2. Independent S2: the Charge test's traceability ids are BR-LATE-005 and DB-TXN-003; the VOID
   test also names BR-INV-046.
3. Independent S3: docs/010 and this record also name the frozen traceability note of
   `test_concurrent_invoice_issuance_serializes_lease_and_service_sources` as out of date.
4. Independent note and security note 1 (both reviewers): `waits_then` rolls the holder back
   before raising when the wait is not seen, so a failing test cannot hang the run.
5. Independent note: docs/004 and docs/010 say "on any row" (also a row with no Lease); the
   Built section of this record and the plan's design keep "also on a Lease with no Final
   Settlement", which is true (corrected in review round 3, independent note 1).
6. Independent note: a slice 12 migration-rules note: `test_receipt_migration.py` runs
   `alembic upgrade` at REPEATABLE READ and SERIALIZABLE, so a later data migration that writes
   these tables must be written for READ COMMITTED.
7. Independent note and security note 3: the plan gets an as-built status line at the commit
   (seven tests, seven traceability entries); security note 4: the commit hash goes into NOW.md
   and the git log, as for earlier sub-slices.
Kept (no change): security note 5 (the check runs only where the 8e-1 triggers fire, by design).

## Review round 3 (fresh read-only subagents, after U3, T3, P3 and P3R; same instructions)

Independent: no blocker, no should-fix, 5 notes. Security: no blocker, no should-fix, 3 notes.
Round 3 is clean; no round 4. Text notes handled after round 3 (ops and docs files only, no code,
migration, test or fixture change, so no run after them):
1. Independent note 1: item 5 of round 2 above corrected (it named the migration docstring).
2. Independent note 2: the plan's as-built status line (seven tests, seven traceability entries,
   the round 1 Charge test).
3. Independent note 4: the uneven line wrap in docs/004.
Notes kept for the owner (no change):
- `waits_then` catches only `AssertionError`; an error of the observer connection itself would
  still leave the second writer waiting until the holder's `with` block ends (test-only, very
  unlikely; both reviewers).
- The VOID race comment in `test_invoice_migration.py` does not name the new module's READ
  COMMITTED VOID test (cosmetic; the record and docs/010 name it).
- A superuser could bypass any trigger with `session_replication_role=replica` (true before this
  sub-slice; out of scope).
- The round 1 and 2 notes above (message wording, READ UNCOMMITTED, a stricter
  `default_transaction_isolation`, the trigger scope).
