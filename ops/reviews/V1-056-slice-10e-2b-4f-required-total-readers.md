# V1-056 sub-slice 10e-2b-4f — the adjusted required total in the readers of the first amount — review record

Sub-slice: 10e-2b-4f (owner answer (a) to Q-2026-10-18-130: a Deposit's required total is its
first amount plus the adjustments recorded by then, and every reader uses it). Migration
`20270106_163` (one new internal function, two exact-text patches). Base commit: 3bcadd6. Built on
2026-10-19 in one fresh session. Not pushed.

## Built

- Migration `20270106_163_deposit_required_total_readers.py`: new internal
  `app.deposit_required_total_at(deposit, as_of)` (no grant); `app.require_lease_termination_context`
  (the BR-LEASE-005 ground reads the total recorded by the termination time) and
  `app.complete_reservation_move_in` (the old move-in counts only active receipts of the Security
  Deposit and each required Pet Deposit, which must reach at least the current total).
- `backend/src/property_rental/reservation_api.py`: `deposit_required_usd_cents` reads the
  snapshot's total.
- Committed tests changed: the 27 head-revision strings in 15 modules (revision strings only).
- New module `test_deposit_required_total_readers_migration.py` (last in `scripts/database-test.sh`).
- Docs: docs/004 (the move-in note, the unpaid-Initial ground, DB-DEP-003), docs/005 (API-032),
  docs/010, plan (pre-code design, Q-112 entry note, slice 12 known limits), questions (owner
  answers to the 10e-2b-4e-2b-3 report; new Q-2026-10-19-138); traceability appended.

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump of the three readers' functions and the required-total functions (no `REDACTED` marker), saved in `~/Development/prm-run-logs/v1-056-10e-2b-4f-D1.txt` |
| I1/FF1/FC1/L1/Y1 | passed (long-line search first; the import sort, each check in its own call; the formatter rewrapped the new test module, a normal step) |
| M1 | passed |
| T1 | 59 passed |
| U1 | 3866 passed |
| M2 | passed |
| P1 | 2369 passed (the deprecation warning and the known pydantic alias warnings) |
| I2/FF2/FC2/L2/Y2 | passed (after the round 1 fixes; long-line search first) |
| M3 | passed (the migration changed in round 1) |
| T2 | 61 passed |
| U2 | 3866 passed |
| M4 | passed |
| P2 | 2371 passed (the deprecation warning and a known pydantic alias warning) |
| I3/FF3/FC3/L3/Y3 | passed (after the round 2 fixes; long-line search first; the formatter changed nothing) |
| T3 | 10 passed (the new module, the only test file changed since T2) |
| U3 | 3866 passed (before round 3) |
| M5 | passed |
| P3 | 2372 passed (the deprecation warning and a known pydantic alias warning; before round 3; the last full run) |
| FF4/FC4/L4/Y4 | passed (after the round 3 text fixes; no code, migration or test file changed after P3) |
| U4 | 3866 passed |

No check or run failed; no correction was counted.

Full outputs in `~/Development/prm-run-logs/v1-056-10e-2b-4f-*.txt`, one file per attempt.

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: no blocker, 3 should-fix, 5 notes; readings (1) to (4) confirmed. Security: no
blocker, 2 should-fix, 6 notes.

Fixed:

1. Independent should-fix 1 (a design change, for round 2 to confirm): the design said the old
   move-in keeps its equality, "so a total lowered below what was received is still refused, as
   today"; that was wrong, because before this sub-slice a decrease was never read. Set-up (the
   reviewer's): `setup_move_in` (holds 50,000 of 50,000), then a 10,000 decrease (total 40,000):
   HEAD completes the move-in, equality would refuse it as "not fully paid". The move-in now
   requires at least the current total (`NOT COALESCE(received >= total, false)`, so a NULL
   refuses; security note 5 too) and the Pet branch `>=`; new test
   `test_the_old_move_in_takes_a_deposit_holding_more_than_a_decreased_total`; the plan design
   text corrected.
2. Independent should-fix 2 and security note 6 (tests): the NULL-time case used
   `(SELECT id FROM app.deposits LIMIT 1)`, which is NULL in an empty database; it now uses a
   Deposit of the test with a 1,000 increase: `(NULL time, '-infinity', 'infinity', unknown
   Deposit) = (None, 50,000, 51,000, None)`; the least-privilege test also asserts that no
   application role has EXECUTE, that the runtime and financial roles get 42501 on a direct
   call, and that the function has the owner of the two functions that call it.
3. Independent should-fix 3 (text): docs/010 as-built and "Updated tests" entries.
4. Security should-fix 1 (owner): a required-total increase recorded after Lease Start plus five
   days meets the BR-LEASE-005 ground at once, so a Lease paid on time can be terminated before
   the Customer could pay, and a confirmed forfeiture draft keeps the whole held Security Deposit.
   It follows the owner's answer (a); written as Q-2026-10-19-138 with recommendation (b) (an
   increase counts for the ground from five days after its record) and a slice 12 known limit.
5. Security should-fix 2 (test, known limit): a termination entered after a decrease but dated
   before it reads the earlier total. Set-up (the reviewer's): `initial_rent_paid`, t0, a 40,000
   decrease, the termination dated t0: recorded. New test
   `test_a_termination_dated_before_a_decrease_reads_the_earlier_total_known_limit`; the Q-112
   times sub-slice entry in the plan names it.
6. Notes taken: security note 3 (the ground reads the Deposit without its lock; the Q-2026-10-18-133
   lock of the Q-112 times sub-slice) and note 4 (the old move-in reads required Pet Deposits
   without a lock; fix: FOR SHARE in id order after the Security Deposit) on the slice 12 list;
   independent note 4 (design tests (2) and (3) became one test; the Pet test uses 20,000,
   1,000 and 21,000 because `create_pet` fixes 20,000), note 7 (DB-DEP-003 names the snapshot's
   readers) and reading (3)'s side effect (a receipt dated after a past move-in date does not
   count) in docs/004.
7. Not taken: independent note 5 (the questions file keeps the owner's own words of answers 3
   and 4), note 6 (the snapshot in the read API costs more than an inline sum; kept so the read
   uses the one definition), note 8 (the midnight boundary between set-up and move-in; the
   committed move-in tests do the same).
8. Security notes 7 and 8 (review round 2, security note 1): note 7 confirmed the read API
   exposes nothing new (confirmation only); note 8 asked for the docs/010 entry, written with
   independent should-fix 3, and for should-fixes 1 and 2 to be recorded (items 4 and 5).

## Review round 2 (fresh read-only subagents, during P2; same instructions)

Independent: no blocker, 3 should-fix (two text, one test), 3 notes. Security: no blocker, 1
should-fix (text), 3 notes. Both confirmed the round 1 design change (at least the current total,
not equality; NULL refuses in both branches) as needed and safe: who pays and how much do not
change, the receipt check caps active receipts at the total, so `>=` differs from `=` only after
a decrease; confirmed every round 1 fix, the exact-text replacements, the 27 revision strings and
traceability (appended only). Fixed under the round-3 rule (tests and text):

1. Independent should-fix 1 (text): Q-2026-10-19-138 option (b) now reads "from the later of
   Lease Start plus five days and five days after its record", so an increase recorded on Lease
   Start plus three days also gets five days.
2. Independent should-fix 2 and security should-fix 1 (text): Q-138 said no staff action could
   make a Security Deposit paid on time meet the ground before this sub-slice; a receipt
   reversal or a Payment return confirmed under `financial.approve` could (the reviewers'
   set-up: `initial_rent_paid` with 50,000 received, then `reverse_receipt_through_draft`); it
   now says that no required-amount change could, and that one `deposits.manage` command now can.
3. Independent should-fix 3 (test): no test reached the Pet branch's `>=`. Set-up (the
   reviewer's): `setup_move_in`, a pet approval required by the signed terms on the move-in date,
   the 20,000 Pet Deposit, a 20,000 receipt through the writer, a 5,000 decrease (total 15,000):
   the move-in completes. New test
   `test_the_old_move_in_takes_a_pet_deposit_holding_more_than_a_decreased_total`, with a shared
   helper `required_pet_deposit` (also used by the Pet test of round 1).
4. Notes taken: independent note 1 (HEAD completed a decreased total only when the Deposit held
   exactly its first amount; one holding more than its decreased total but not exactly its first
   amount, for example 45,000 held of a 50,000 first amount after a 35,000 second receipt before
   signing and a 10,000 decrease (total 40,000), was refused at HEAD and completes now, a
   relaxation under answer (a): docs/010, plan and this record; wording corrected in round 3); note 2 (the plan's as-built line is written with the commit); note 3 and the Q-138
   case (slice 11 screen notes in the plan); security note 2 (the old move-in's Pet Deposit check
   counts receipts, not the held value; pre-existing; slice 12 item (5)); security note 3 (the
   ground's read without the lock; already slice 12 item (3)).

## Review round 3 (fresh read-only subagents, during P3; same instructions)

Security: no blocker, no should-fix, 3 notes. Independent: no blocker, 1 should-fix (text), 2
notes. Both confirmed every round 2 fix (the Q-2026-10-19-138 wording, the new Pet test and the
shared helper, nothing of the round 1 Pet test weakened, the plan notes) and the whole diff
(migration, NULL handling, exact-text patches, read API, tests, docs, the 27 revision strings,
traceability appended only).

Fixed under the round-3 text rule of 2026-10-16 (text only; no code, migration, test or fixture
change; no round 4):

1. Independent should-fix 1 (text): the HEAD-behaviour example in docs/010, the plan and this
   record described a state the receipt check cannot reach (more than the first amount after a
   decrease); it now names the reviewer's case: 45,000 held of a 50,000 first amount after a
   35,000 second receipt before signing and a 10,000 decrease (total 40,000), refused at HEAD
   and completed now.
2. Notes taken (both reviewers): the docs/010 entry also names slice 12 item (5); this record
   gains the runs after round 2 and this section; the plan's as-built line is written with the
   commit.
3. Not taken: security note 3 (awareness: a decrease can lower the old move-in gate and stop the
   ground; named in the plan's slice 11 note; part of answer (a)).

