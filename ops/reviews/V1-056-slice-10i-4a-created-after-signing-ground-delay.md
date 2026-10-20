# V1-056 sub-slice 10i-4a — a Security Deposit created after signing counts for the unpaid-Initial ground only five days after its creation — review record

Sub-slice: 10i-4a, the first part of sub-slice 10i-4 (owner answer (a) to Q-2026-10-20-148).
Migration `20270116_173` (one whole-body `CREATE OR REPLACE` of an internal function). Base
commit: 52fe203. Built on 2026-10-20 in a fresh session. Not pushed. The commit hash is in
`git log` (this record is part of that commit).

## Owner answers recorded first

The owner answers of 2026-10-20 to the 10i-3 report: (a) to Q-2026-10-20-146, (a) to
Q-2026-10-20-147, (a) to Q-2026-10-20-148; the pending rename in
`test_deposit_receipt_refund_out_migration.py` stays pending (that file is not touched here).
Recorded in docs/010 and ops/V1_056_QUESTIONS.md. Pre-code design for 10i-4a, 10i-4b and 10i-4c
in the plan (catalog dump D1). New question Q-2026-10-20-149 (a waiting `REFUND_RETURN`
correction draft also gives value back to an existing Credit; recommendation (a); nothing waits on
it).

## Built

- `app.deposit_ground_required_total_at(deposit, as_of)` (read only by the BR-LEASE-005 ground):
  the first amount counts at once only for a Deposit with a Reservation created at or before the
  Lease's signing time; every other Deposit (every walk-in Security Deposit) counts its first
  amount only when the Asia/Phnom_Penh business date of its creation plus five days is before the
  business date of the time, and reads 0 before. Adjustments keep the 10i-2 rule. Same signature,
  settings, definer flag; owner and revoked EXECUTE kept.

## Committed tests changed

The 27 head-revision strings in 15 modules (revision strings only; a script checked each file's
count). No other committed test changes (read-only search: every module that terminates on the
ground builds its Deposit through a Reservation; the walk-in Deposit modules never terminate on
the ground; the 10i-2 module checks its own migration by revision).

## New tests

Module `test_deposit_created_after_signing_ground_delay_migration.py` (last in
`scripts/database-test.sh`):
`test_a_deposit_created_after_signing_counts_only_after_its_creation_date_plus_five_days`,
`test_adjustments_of_such_a_deposit_keep_their_own_rules`,
`test_a_walk_in_deposit_dated_before_signing_still_waits_its_five_days` (round 1),
`test_a_reservation_deposit_still_counts_for_the_ground_at_once`,
`test_the_created_after_signing_ground_delay_migration_is_least_privilege_and_forward_only`.
Hand-built set-up (round 1, with the comment the set-up rule asks for): `walk_in_deposit_dated`
writes a walk-in Deposit row with a creation time days ago, because the create stamps its own
statement time; the signing time is the database time of the signing, so such a row is dated
before the signing. Traceability: 5 entries appended; the first 1,598 entries untouched.

## Reviews

Round 1:
- Independent: no blocker; should-fix 1, design test (2) not built (built as the round 1 test
  above; the design's "created six days ago" Deposit is necessarily dated before the signing,
  which the security fix covers); should-fix 2, the slice 12 list not updated (the Q-148 note and
  the "created" part of the 10e-2b-4c known limit marked closed); should-fix 3, no docs/010 build
  entry (written). Notes 4 and 5 taken: the day 5 and day 6 reads count from the Deposit's own
  creation date, with the edge instants. Notes 6 to 8 kept (no test of a Deposit created after
  the termination time or a Lease with no signing time; the least-privilege test checks text
  pieces).
- Security: should-fix 1, a walk-in create statement can start before a signing that commits
  while it waits, so its `created_at` can be at or before `signed_at` and it would count at once
  (fixed, a design change under the run rule, confirmed by both round 2 reviewers: the first
  amount counts at once only when `deposit.reservation_id IS NOT NULL AND
  deposit.created_at<=lease.signed_at`). Notes: the ground can only get harder; the timestamps
  cannot be moved; dates and time zone consistent with 10i-2; least privilege kept.

Round 2:
- Independent: clean. Notes: 10i-1 note (5) is closed in effect (plan updated); no test of a
  Reservation Deposit created after signing (fail closed); the design's rule-reading sentence is
  history; this record still to be written.
- Security: clean. Notes: a Reservation activation that commits after a signing it started
  before counts at once (the owner's rule); a back-dated signing only makes a Reservation Deposit
  wait; the hand-written rows still pass the insert and deferred source checks; the fixed
  Asia/Phnom_Penh time zone is existing behaviour.

No should-fix in round 2, so no round 3.

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-10i-4a-`, and `v1-056-10i-4-D1.txt`)

| Run | Result | Cause |
|---|---|---|
| D1 | done | catalog dump for the 10i-4 pre-code design, no `REDACTED` marker |
| FF1, I1, FC1, L1, Y1 | pass | backend checks |
| U1 | 3,870 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 632 passed | targeted, 29 modules |
| P1 | 2,434 passed | full PostgreSQL run |
| FF2 (one file reformatted), I2, FC2, L2, Y2 | pass | after the round 1 changes |
| M2 | pass | migration-only check |
| T2 | 151 passed | targeted, the 14 ground and Deposit modules |
| U2 | 3,870 passed | unit suite |
| P2 | 2,435 passed | full PostgreSQL run |

No failed check or run; no correction. After P2 only text changed (plan, this record, NOW.md).
