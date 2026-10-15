# V1-056 sub-slice 10e-3d-2d-1 — a returned Credit's count takes the corrections of every Final Settlement that use it — review record

Sub-slice: 10e-3d-2d-1 (owner answer (a) to Q-2026-10-13-100 point 2: "a correction on another
Lease of the same Customer that uses the returned Credit counts too"). Migration `20261211_137`.
Base commit: ea2fed1 (10e-3d-2c). Built on 2026-10-15. Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-014, DL-032; DB-SETTLE-005. Design:
ops/V1_056_PLAN.md, bullet "10e-3d-2d — a correction of another Lease's Final Settlement used the
returned Credit" (written 2026-10-15 before the code; split of 10e-3d-2d, owner allowed: 2d-1
counts and refuses the undo; 2d-2 builds the undo with a companion correction of the other Lease's
Settlement, owner answer (a) to Q-2026-10-13-103 point 3) and its as-built note.

## Built

- Migration `20261211_137` (exact-text patches, each anchor found exactly once, else the migration
  stops): `app.settlement_returned_value_walk` (for a Credit, the corrections walked are those of
  the given Settlement and, of every other Final Settlement, those with a linked record the walk
  reads for that Credit, in one order by time and id; a Deposit's walk does not change),
  `app.settlement_returned_value_placed` (a take by a correction of another Final Settlement is one
  open part of kind `OTHER_SETTLEMENT`, record id that correction, before any other kind, so none of
  its records is listed), `app.assert_settlement_return_reversal_allowed` (such a part is refused
  before any other open part: 55000, "A correction of another Lease's Final Settlement used this
  return's money; reversing it waits for sub-slice 10e-3d-2d-2"). No new function; no table,
  column, constraint, trigger, lock or grant change.
- Tests: new module `backend/tests/test_settlement_returned_value_other_settlements_migration.py`
  (four tests), last in `scripts/database-test.sh`; the 27 head-revision assertions in 15 modules
  move to `20261211_137` (revision strings only, `sed`). Traceability: four entries appended.
- Docs: docs/004 (DB-SETTLE-005 paragraph, and a pointer in the 10e-3d-1 paragraph), docs/010, the
  plan's design and as-built notes, one slice 12 item, new Q-2026-10-15-113.

Design changes during the build: none.

Test set-up (for later sessions): the Customer's second Lease is built by the committed leaving
fixture (`test_final_settlement_draft_migration.leaving_case`) with
`test_unpaid_initial_termination_migration.setup_reservation_sources` patched inside
`monkeypatch.context()` to return a new Unit (from the original function) and the first Lease's
Customer. That fixture names the Customer's first Credit (`SELECT id FROM app.customer_credits
WHERE customer_id=%s`, no order), so the test names the second Lease's own Credit (the only one
with value at that point) and closes the second Lease with the same normal-end plan. The first
Lease is the returned-Payment module's `closed_case` plus a `REFUND` correction of its Initial Rent
line refunding 2,000 (as `refunded_case`, without the extra 300 of new Credit the correction-plan
`closed_case` gives, which the second closure would have to use first). The other Lease's use is a
`REFUND_RETURN` of its Settlement Pet Deposit Refund (5,400) after an unpaid 1,500 charge, whose
plan lets the returned Credit pay the charge first.

## Committed tests that change

Only the 27 head-revision strings (`20261210_136` to `20261211_137`) in 15 modules. No committed
expectation changes (read-only search: no committed test has corrections of two Settlements on one
Credit; P1 and P2 confirm).

## Runs

Static checks each in its own call, formatter first (`ruff format src tests`, the repo's scope).
Outputs in `~/Development/prm-run-logs/` (`V1-056-slice-10e-3d-2d-1-*`; the first check of the
session as `V1-056-slice-10e-3d-2c-T7` and `-U4`); every targeted and full run under
`caffeinate -dims`.

| Run | Kind | Result | Cause |
|---|---|---|---|
| T7 | targeted: the 10e-3d-2c module (session's first check) | 7 passed | owner's first check (no 10e-3d-2c code or test file changed after P3 began) |
| U4 | `tests/test_traceability.py` (session's first check) | 28 passed | owner's first check |
| D1 | catalog dump (pre-code read) | failed: one name was not an `app` function (`lock_settlement_correction_draft`); every other definition printed | implementer's wrong name; not a check; the lock function is `app.lock_settlement_correction_plan`, read from the migrations |
| FC1, L1, Y1 | format check, lint, `mypy` | passed | first |
| M1 | migration-only check | passed (head `20261211_137`, 136 upgrades) | first |
| T1 | targeted: new, left, swept, returned-Refund modules | 28 passed, 2 failed ("The Customer Credit is not available to this Final Settlement" at the second Lease's closure) | cause A (test set-up: the fixture named the Customer's first Credit), correction 1 of 2 |
| FC2 | format check | passed | after A1 |
| L2 | lint | failed: import order in the new module | cause B, correction 1 of 2 |
| Y2 | `mypy` | passed | after A1 |
| FC3, L3, Y3 | format check, lint, `mypy` | passed | passing reruns after B1 |
| T2 | targeted: new module | 3 passed | passing rerun after T1 |
| U1 | backend unit, full | 3804 passed, 2010 skipped, 1 known warning | first (after the traceability entries) |
| M2 | migration-only check | passed | before P1 |
| P1 | PostgreSQL full | 2174 passed, 3 known warnings (Starlette; pydantic `UnsupportedFieldAttributeWarning` twice) | first |
| FC4, L4, Y4 | format check (after the formatter), lint, `mypy` | passed | round 1 fixes |
| M3 | migration-only check | passed | migration docstring changed |
| T3 | targeted: new module | 4 passed | round 1 fixes |
| U2 | backend unit, full (covers `tests/test_traceability.py`) | 3804 passed, 2011 skipped, 1 known warning | round 1 fixes; before round 3 (standing round-3 rule) |
| P2 | PostgreSQL full | 2175 passed, 2 known warnings (Starlette; pydantic once) | round 1 fixes (test and migration changed after P1); before round 3 |

Corrections per cause (each sub-slice starts at 0): A (test set-up, the second Lease's Credit) 1
of 2; B (import order) 1 of 2. After P2 only text changed (docs/004, docs/010, the plan, the
questions file, this record, ops/NOW.md); no test covers them, so no targeted run follows (run rule
of 2026-10-15).

## Review round 1 (fresh read-only subagents, during P1; told to write no file and run nothing)

Independent: 0 blockers, 1 should-fix, 7 notes. Security: 0 blockers, 0 should-fix, 7 notes.

- Independent should-fix S1 (test): the owner's harm case (a later return refills the Credit) was
  not tested; both refusals happened while the Credit was empty. Fixed:
  `test_a_later_return_s_money_is_not_paid_out_for_an_earlier_return` with the reviewer's
  to-the-cent variant (set-up below).
- Notes taken: N1 (the `own_open` arm untested: a hand-built case added); N3 and security note 1
  (another Lease's own Final Settlement confirm using the returned Credit is not counted: named in
  docs/004 and the migration docstring as the ordinary Credit spending limit, and asked as
  Q-2026-10-15-113); N4 (the attribution of a later sweep can move to a later return: docs/004 and
  the migration docstring); N5 (wording "before any other open part": migration docstring and plan);
  N6 (this record written before the commit).
- Notes recorded, not changed: N2 and security note 6 (performance of the walk filter: slice 12
  item); N7 (cross-Settlement time order not visible on this path); security note 2 (`own_open`
  only on the walk path; unreachable on the real path; the hand-built case shows the refusal);
  security note 3 (optional cross-Lease stale-draft test: slice 12 item, because a waiting draft on
  the Credit may itself block the other Lease's record); security note 4 (COUNTS leaves out some
  tables; the refusal comes before any write: slice 12 item); security note 5 (hand-built cases on
  the walk path: one added); security note 7 (the message says another Lease's correction exists,
  without ids; same Property and Customer: accepted).

Reviewer's set-up S1 (independent, round 1; built in
`test_a_later_return_s_money_is_not_paid_out_for_an_earlier_return`):

1. The two-Lease case with X1 returning 1,700 of the 2,000 Credit Refund; the other Lease's
   Refund return lets the Credit pay the whole 1,500 charge and refunds the Pet Deposit's 5,400.
2. A later return-only correction X3 of the first Lease returns 300 (the Refund's net becomes 0;
   the Credit holds 500).
3. Counts from both Settlements: X1 (1,700, 1,500, 1,500, 200), X3 (300, 0, 0, 300).
4. X1's reversal refused with the new message, nothing written.
5. A held-value Refund naming X1 refunds exactly 200 (before migration 137 it would refund
   `LEAST(1,700, 500)` = 500); one naming X3 then refunds 300; the Credit ends empty; the ledger
   reconciles.

## Review round 2 (fresh read-only subagents, during P2; told to write no file and run nothing)

Independent: 0 blockers, 1 should-fix, 6 notes. Security: 0 blockers, 0 should-fix, 5 notes. The
should-fix is text, so under the round-3 rule (2026-10-13) it was fixed and round 3 runs without
asking; U2 and P2 ran after the last code change and before round 3.

- Independent should-fix (text): the docs/010 entry named three of the four tests. Fixed.
- Notes taken (text): the attribution can also move to an older return of another Lease
  (independent N2, security note 1: docs/004); a pointer from the 10e-3d-1 paragraph (security
  note 3: docs/004); records confirmed before migration 137 are read with the new attribution and
  fail closed (independent N3, security note 4: docs/004); notes for the 10e-3d-2d-2 design
  (independent N4, security note 5: lock order, B's refusals again under the locks, the same
  Property and approver, no tie in time with the reversal: the plan); the other Lease's own Final
  Settlement confirm named to the owner (independent N5: Q-2026-10-15-113).
- Notes recorded, not changed: an optional test of a reversal allowed before 137 and refused now
  with a refilled Credit (independent N1: slice 12 item); performance (independent N6, security
  note 2: slice 12 item).
- Round 2 independent confirmed: the round 1 fixes are real (the harm test fails without migration
  137 in three places; the hand-built `own_open` case passes every earlier check and reaches the
  new refusal); the three anchors match once; the 27 head strings are the only committed test
  change; traceability is append-only (3,081 HEAD entries an exact prefix, four appended, ids
  unique); no design change changes who pays or how much.

## Review round 3 (fresh read-only subagents; told to write no file and run nothing)

Independent: 0 blockers, 0 should-fix, 4 notes: clean. Security: 0 blockers, 0 should-fix,
4 notes: clean. No further round.

- Independent: every round 2 fix matches the code (both attribution examples traced through the
  walk; the follow function's cut check and the stale check fail closed for records confirmed
  before 137); committed tests compared with HEAD: exactly 27 revision strings in 15 modules
  (6 `get_heads()`, 1 `get_current_head()`, 3 `ScriptDirectory...get_current_head()`, 3
  `cursor.fetchone()`, 14 `alembic_version` literals), nothing weaker; the three anchors match the
  pre-migration bodies byte for byte; each hand-built source passes the earlier checks before the
  new refusal; traceability append-only (3,081 HEAD entries an exact prefix, four appended, ids
  unique); the run table agrees with the text; no design change beyond the owner answers. Notes:
  this record listed ops/NOW.md as changed after P2 before it was (it is updated with the commit);
  the migration docstring names only the later-return direction of the attribution move (docs/004
  names both; not changed: the migration file is unchanged after P2); `own_open` is read only on
  the walk path (unreachable on the pooled path); only the Credit application link of the walk
  filter is tested on the real path (the other links add walk rows that existing terms already
  compute, and another Settlement's Credit reversal stays an open `OTHER_SETTLEMENT` part).
- Security: deny-by-default, no new write path, no cross-Lease data in a stored source or a
  message, fail closed, no SQL injection or secrets (also in the docs and this record),
  concurrency (every writer against the Credit locks its row; the confirm rebuilds the source
  after the locks, P5S02). Notes: the privilege test names four roles (the before-and-after ACL
  comparison catches any grant); the filter is not limited by Property or Customer (extra
  corrections only lower left values or move the attribution); some returns are now allowed that
  were refused before 137 (another Lease's older return is taken first; payouts stay capped; for
  the owner report and the 10e-3d-2d-2 design); performance under locks (slice 12 item).
