# V1-056 sub-slice 10i-1 — the termination time from the database clock, and the termination locks the Lease's Deposits — review record

Sub-slice: 10i-1, the first part of the Q-112 times sub-slice (owner answers (a) to
Q-2026-10-14-112 point 1 and (a) to Q-2026-10-18-133). Migration `20270114_171` (four exact-text
replacements, each checked to match once). Base commit: 52bbaae. Built on 2026-10-20 in a fresh
session. Not pushed. The commit hash is in `git log` (this record is part of that commit).

## Owner notes recorded first

The owner notes of 2026-10-20 on the 10h-4b report: Q-2026-10-20-146 stays open (its full text
was printed at the start of the session; nothing is built for it); the 10h-4b test changes are
accepted; screens change only as far as a rule needs to work and be tested; every targeted and
full run gets a time limit long enough for the whole run. Recorded in docs/010 and
ops/V1_056_QUESTIONS.md. New question Q-2026-10-20-147 (the Reservation's holding deposit
`received_at`; recommendation (a); nothing is built for it).

## Built

- Route `POST /leases/{id}/terminate`: no `occurred_at` (422 on a body that sends one); the route
  passes `None`. Service: `LeaseTerminateCommand.occurred_at` is optional; both calls pass
  `COALESCE(%s::timestamptz,statement_timestamp())`.
- `app.terminate_lease_with_context`: the replay compares every saved field except the time; the
  request digest, still compared, binds the given time (null on the route path).
- `app.terminate_lease`: after the Lease and Unit locks and the version and status checks, the
  Lease's Deposits are locked in id order; then a termination stamped with the database's time is
  refused (40001, "The Lease's Deposits changed while this termination waited; record it again")
  when a Deposit balance event or a required-amount adjustment of the Lease is dated after its
  time; then the chronology, context and ground checks.
- `app.adjust_deposit_required_amount`: its row is dated with `clock_timestamp()` after its
  Deposit lock.
- `app.record_active_lease_pet_departure`: locks the Lease (FOR KEY SHARE) before its Pet Deposit.
- Screens: both termination forms send no time; `LeaseTerminateSource` drops `occurred_at`.

## Committed tests changed

1. `test_deposit_receipt_leftover_migration.py::test_a_receipt_beside_an_uncommitted_termination_is_recorded_known_limit`
   renamed under the standing rule
   `test_a_receipt_beside_an_uncommitted_termination_waits_and_is_refused` (owner answer (a) to
   Q-133 changes its result): the receipt waits and is refused (55000, kept); no receipt of the
   Payment is written. Traceability entry 3,243 (index 3242) updated: id and note.
2. Request bodies without `occurred_at`: `test_lease_api.py::test_signer_signing_renewal_and_termination_are_explicit_commands`,
   `test_unpaid_initial_termination_migration.py::terminate_body` (unused `db_now` removed),
   `frontend/src/leaseClient.test.tsx`.
3. The 27 head-revision strings in 15 modules (revision strings only; a script checked each
   file's count).

## New tests

`test_lease.py::test_terminate_command_accepts_no_time_and_keeps_the_time_zone_rule`;
`test_lease_api.py::test_terminate_route_takes_no_termination_time_from_the_request`; new module
`test_termination_database_time_migration.py` (last in `scripts/database-test.sh`):
`test_http_termination_time_is_the_database_time`,
`test_a_termination_waits_for_a_decrease_being_saved_and_reads_it`,
`test_an_adjustment_waits_for_a_termination_being_saved`,
`test_a_deposit_change_saved_while_a_termination_waits_refuses_it` (receipt and decrease; round 1),
`test_a_pet_departure_waits_for_a_termination_and_is_refused` (round 1),
`test_the_termination_database_time_migration_is_least_privilege_and_forward_only`; frontend
TEST-FE-678 and TEST-FE-679. Traceability: 10 entries appended; the first 1,598 entries untouched.

## Reviews

Round 1:
- Independent: blocker 1, the Pet departure writer locked its Pet Deposit and then took the
  Lease key through the foreign key of `lease_pet_departures`, a new deadlock (40P01) with the
  termination's Deposit lock (fixed: Lease FOR KEY SHARE first); should-fix 2, docs/004 and the
  plan claimed no Deposit writer can deadlock (fixed); note 3, an adjustment whose statement
  started first but lost the lock race was dated before the termination (fixed:
  `clock_timestamp()` after its lock); notes 4 and 5 (old clients get 422 instead of a replay, by
  design; checks confirmed).
- Security: should-fix 1, the termination time is the start of its statement and its locks come
  later, so a curing receipt or decrease committed while it waited, dated after its time, was
  missed by the BR-LEASE-005 ground (fixed: the 40001 refusal, with the test the reviewer asked
  for: the termination starts first and waits on the Unit while the change commits); notes:
  `app.confirm_payment_return` takes a Deposit before the Lease key (already deadlocking with a
  termination on the `invoice-lease` key before 10i-1; slice 12 note), the replay relaxation is
  safe, backdating is closed at the route, the path relies on READ COMMITTED.

Round 2:
- Security: clean; notes: the Initial-Invoice half of the ground has the same (pre-existing,
  narrower) race; `qualify_active_lease_pet_refund_review` can record on a just-terminated Lease
  (pre-existing); the 40001 reaches staff as the stale-version message; a stale call took the
  Deposit locks.
- Independent: should-fix 1, the plan, docs/010 and the record did not yet record the round 1
  changes and the rename (fixed); should-fix 2, the Deposit lock and the 40001 check came before
  the version and status checks, so a termination refused anyway could wait on, and deadlock
  with, a Deposit writer (fixed: moved after the status check; a design change, confirmed in
  round 3); notes: misleading message; a walk-in Security Deposit created while a termination
  waits is not compared; two tests prove their order only by the catalog check; the departure's
  Lease lock has no Property filter; the 10e-2b-4f known-limit docstring is updated in 10i-2.

Round 3 (standing round-3 rule: no blocker and two should-fix in round 2; the full unit and
PostgreSQL runs U3 and P3 passed before it):
- Independent: clean (notes: two plan lines still showed the pre-code wording, fixed as text;
  this record was still to be written).
- Security: clean (notes: message wording, the departure's brief Lease lock across Properties, a
  receipt dated up to 5 seconds ahead gives a short 40001, no receipt-holds-the-Deposit test).

New slice 12 notes (plan): items (1) to (7) of "Notes (sub-slice 10i-1 review rounds 1 and 2)".

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-10i-1-`)

| Run | Result | Cause |
|---|---|---|
| D1 (`v1-056-q112-times-D1-catalog.txt`) | done | catalog dump for the pre-code design |
| FF1, I1, FC1, L1 | pass | first checks |
| Y1 | failed | cause A (1 of 2): mypy narrowed `flow.terminate_command` to None in the new route test |
| FF2, L2, Y2 | pass | after the cause A fix |
| FEF1, FEFC1, FEL1, FEY1, FET1 | pass | frontend format, format check, lint, type check, tests (1,598) |
| U1 | 3,869 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 431 passed | targeted, 29 modules |
| P1 | 2,423 passed | full PostgreSQL run |
| FF3, I2 (fixed one import order), FC2, L3, Y3 | pass | after the round 1 fixes |
| M2 | pass | migration-only check |
| T2 | 394 passed | targeted, 32 modules (departure, adjustment and termination tests) |
| U2 | 3,869 passed | unit suite |
| P2 | 2,426 passed | full PostgreSQL run |
| FF4, I3, L4, Y4 | pass | after the round 2 fix |
| M3 | pass | migration-only check |
| T3 | 434 passed | targeted, the T1 modules |
| U3 | 3,869 passed | unit suite (before round 3) |
| P3 | 2,426 passed | full PostgreSQL run (before round 3) |

One correction (Y1, cause A, 1 of 2). No `LockNotAvailable` failure. After P3 only text changed
(two plan lines, this record, NOW.md).
