# V1-056 sub-slice 10c-2b-6 — the pay-back limit in the forfeiture's insert check: review record

Sub-slice: 10c-2b-6 (migration `20261125_121`). Base commit: ed96f98. Built in one session on
2026-10-12 and committed locally (see git log; the commit right after ed96f98). Not pushed.

Rule IDs: BR-DEP-022, DL-032; owner answer (a) to Q-2026-10-10-73 and owner answer 4 of
2026-10-12 (the slice 12 tightening from sub-slice 10c-2b-5, approved). Design: ops/V1_056_PLAN.md
(10c-2b-6 entry, "10c-2b-6 pre-code check").

The same commit records the owner answers to Q-2026-10-12-87 (sub-slice 10e-2b: rules 1, 2 and 3
option (a); the new order 10c-2b-6, 10e-2b, 10e-3, 10e-4, 10c-2a-7, 10c-3c-1, 10c-3c-2, 10f, 10g,
10h) in docs/010, ops/V1_056_QUESTIONS.md and the plan.

## Built

- Migration `backend/migrations/versions/20261125_121_pet_deposit_payback_limit.py`: an exact-text
  patch of the Lease Deposit disposition insert check `app.validate_lease_deposit_disposition()`.
  After the held-value check (unchanged, still first) it refuses an amount above the held value
  less `app.lease_deposit_payback_value(deposit)` (23514, "Lease Deposit disposition would forfeit
  returned pay-back money"), so no writer, the owner-only one-call disposition included, forfeits
  returned Pet Refund-review money. The forfeiture draft path is unchanged (its source already
  takes exactly that amount). No other function, table or trigger changes; forward-only.
- Tests: new PostgreSQL module `backend/tests/test_pet_deposit_payback_limit_migration.py`
  (3 tests, last in `scripts/database-test.sh`): the Q-2026-10-09-61 shape (the draft refused
  22023, the one-call of all the pay-back money and of 1 cent refused 23514, nothing written, the
  Deposit stays on the DL-032 path); the boundary (8,001 keeps the old message, 5,001 refused,
  exactly 5,000 accepted, then the draft refused 22023; the Security Deposit's draft takes its
  whole held value); least privilege and forward-only (only the check changes, by the listed pair).

## Changed committed tests (owner answer 4 of 2026-10-12, owner standing rule of 2026-10-11)

- The 10d fixture `twice_forfeited_case` (`backend/tests/test_settlement_forfeiture_reversal_migration.py`):
  the Pet Refund-review Refund pays 13,000 instead of 15,000 (the Pet Deposit keeps 7,000 of its own
  money); the owner's one-call disposition forfeits 5,000, then the forfeiture draft forfeits the
  remaining 2,000. The two forfeitures swap paths (at HEAD the draft wrote the 5,000 and the
  one-call the 2,000), because the draft always takes all the held money beyond pay-back money.
  The 2,000 return and the fixture's 22023 draft check leave the fixture (no pay-back money
  remains in it); that check moves to the new module, in the same shape. The unused imports
  `refund_id` and `returned` are removed. The test that uses the fixture
  (`test_a_second_active_forfeiture_of_the_deposit_refuses_its_reversal`) keeps its amounts
  (5,000 then 2,000 by `occurred_at`), both 55000 refusals, the stale draft and its end state.
- The 27 head-revision assertions in 15 modules: `20261124_120` to `20261125_121`, nothing else.
- `ops/traceability.json`: three entries appended; the note of the 10d test that uses the fixture
  is updated (an entry after the first 1,598).
- docs/004 (the 10c-2b-6 bullet under DB-DEP-005 and a pointer under DB-DEP-004), docs/010 (owner
  answers, sub-slice entry, updated tests, review round 1), the plan (10e-2b answers and placement,
  order, 10c-2b-6 pre-code check), ops/V1_056_QUESTIONS.md (Q-87 answered).

## Runs

Static checks, each in its own call: format check clean; lint 1 issue on the first run (cause A:
`refund_id` imported but unused in the changed 10d module after the fixture change; 1 correction
of 2), then lint clean; mypy clean before and after the correction. Migration-only check
(`scripts/migration-check.sh`): 120 upgrades, head `20261125_121`, before T1 and P1. Read-only
catalog read of head `20261124_120` on a throwaway container for the pre-code check (not a test
run). Read-only search of every backend test for one-call dispositions and forfeiture drafts on a
Pet Deposit with returned Pet Refund-review money (plan, pre-code check point 3): the affected
tests are the new module, the 10d test that uses the fixture, the 10c-2b-5 module and
`test_refund_history_participates_in_posting_observation`, all in T1 and P1; the 15 head modules
are in P1.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T1 | PostgreSQL targeted: new module, the 10d fixture's test, the 10c-2b-5 module, the refund-history test | 17 passed, 1 warning | first run | `V1-056-slice-10c-2b-6-targeted-test-run.txt` |
| U1 | backend unit, full (caffeinate) | 3762 passed, 1907 skipped, 1 warning | first unit run | `V1-056-slice-10c-2b-6-unit-test-run.txt` |
| P1 | PostgreSQL full (caffeinate) | 2071 passed, 1 warning | first full run | `V1-056-slice-10c-2b-6-full-test-run.txt` |

No run failed. Secret check of all three outputs: no database URL, no `password=`, no 40- or
64-character hex string.

## Review round 1 (fresh read-only subagents, during P1)

Independent: 0 blockers, 1 should-fix, 7 notes. Security: 0 blockers, 0 should-fix, 3 notes.

Fixed (text only, after P1; no code or test change, so no new run):
- Should-fix (independent): the traceability note of the 10d test said "a one-call return between
  them" and "with no return"; it now says "until sub-slice 10c-2b-6 a one-call return between them".
- Notes fixed: the swapped forfeiture paths are named in docs/010 and here; docs/004 DB-DEP-004
  points to the new refusal; the plan's 10e-2b header gives the new placement; this record exists.
- Answered: the 22023 check that left the fixture is in the new module in the same shape
  (confirmed by the independent reviewer, stronger); the Q-87 record's wording restates the chosen
  options; the owner answers are recorded in this commit, as in the 10e-2 commit, and named in the
  commit message; the security reviewer re-scanned the run outputs (clean; P1 rescanned after it
  ended).
- Slice 12 items (docs/010): the held value of the check (`app.deposit_snapshot`) and of the
  pay-back value (`app.deposit_held_value_at`) should stay equal (a test or a comment); the
  concurrency safety rests on the Deposit row lock taken before the values are read (the
  `b_deposit_balance_source` trigger and the check's own `FOR UPDATE OF deposit`; a comment or a
  two-connection test); the "nothing written" check could also count the command records.

## Review round 2 (fresh read-only subagents, after P1; only text changed since)

Independent: 0 blockers, 0 should-fix, 4 notes; it compared every changed committed test with HEAD
(the fixture, its two removed imports, 27 head-revision lines in 15 modules) and found nothing
weaker. Security: 0 blockers, 0 should-fix, 2 notes. No round 3.

Text fixed after round 2 (no code or test change): the traceability note of the 10d test says the
10c-2b-5 one-call was used until 10c-2b-6; the plan's 10e-2b entry no longer says nothing is built
until the owner answers; the plan's "10c-2b-6 as built" line; the slice 12 concurrency item names
both Deposit locks. Answered: the check fails closed if the two held-value formulas ever differ
(slice 12 item above); the run outputs show the local home path, not a secret (as in earlier
records).
