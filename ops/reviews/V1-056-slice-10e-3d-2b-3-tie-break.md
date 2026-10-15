# V1-056 sub-slice 10e-3d-2b-3 — a tie in the newest-first order broken by write order — review record

Sub-slice: 10e-3d-2b-3 (owner answer (a) to Q-2026-10-14-111). Migration `20261209_135`.
Base commit: 7711652. Built on 2026-10-14. Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-016, DL-032; DB-SETTLE-005.
Owner answer (a) to Q-2026-10-14-111: "break the tie by write order, as recommended. Build it
where it fits best before 10h." Placement 10e-3d-2b-3 and the 10e-3d-2c design accepted by the
owner on 2026-10-14. Design: ops/V1_056_PLAN.md, bullet "10e-3d-2b-3 — the Q-2026-10-14-111
answer (a): a tie broken by write order".

## Built

- Migration `20261209_135` (relaxing exact-text patches, each anchor found exactly once, else
  the migration stops): `app.settlement_returned_value_placed` (the taking correction's payments,
  Credit and Deposit), `app.settlement_returned_value_follow` (the changing correction's payments
  in its stream, Credit and Deposit) and `app.settlement_return_reversal_source_state` (the two
  list orders of migration 125 and the `newer` walk of migration 128) order a tie in time by
  `settlement_correction_effects.effect_sequence` descending, then by the id; a Deposit payment
  keeps `application_order` before it. No writer, lock, grant, table, constraint or trigger
  change.
- Tests: new module `backend/tests/test_settlement_returned_value_tie_break_migration.py`, last in
  `scripts/database-test.sh`, three tests. The 27 head-revision assertions in 15 modules move to
  `20261209_135` (revision strings only). Traceability: three entries appended.
- Docs: docs/004 DB-SETTLE-005 paragraph, docs/010, the plan's as-built note.

## Finding for the owner

The premise of Q-2026-10-14-111 ("the rests a Refund correction writes again share one stamped
time") does not hold on the real path. The database refuses a Credit application that is not
later than every earlier event of its Credit (`app.validate_credit_application_source`, migration
41, line 556) and a Deposit application that is not later than the Deposit's latest balance event
(`app.validate_deposit_application`, migration 86, line 409); `application_order` is also unique
per Final Settlement (migration 86, line 316). So two payments of one source never share a time,
no stored result changes, and in practice no waiting draft becomes stale. The tie-break is defence
in depth: it makes the order a rule instead of a consequence of those checks.

## Design change during the build (run rule of 2026-10-14; confirmed by the round 1 independent reviewer)

The planned test "the owner's example on the real path" cannot be built, because the real path
cannot make the tie (above). The tests make the tie by hand on a real correction's two Credit
payments, in an owner transaction that is always rolled back (user triggers disabled only inside
it): the older payment takes the newer one's time, and the payment with the lower id gets the
highest effect sequence, so write order and id order disagree and the id alone would choose the
other payment. A Deposit tie cannot be made even by hand (the unique `application_order`), so the
Deposit form is pinned by the exact-text check of the forward-only test only.

## Runs

Static checks each in its own call, formatter first. Outputs in `~/Development/prm-run-logs/`
(`V1-056-slice-10e-3d-2b-3-*`); every targeted and full run under `caffeinate -dims`.

| Run | Kind | Result | Cause |
|---|---|---|---|
| M1 | migration-only check | passed (head `20261209_135`, 134 upgrades) | first |
| — | backend formatter, format check, lint, `mypy` | clean | first |
| T1 | PostgreSQL targeted: the new module | 2 passed | first |
| U1 | backend unit, full | 3804 passed, 1998 skipped, 1 known warning | first |
| M2 | migration-only check | passed | before P1 |
| P1 | PostgreSQL full | 2162 passed, 2 known warnings (Starlette; pydantic `UnsupportedFieldAttributeWarning` once) | first |
| — | backend formatter (1 file reformatted), format check, lint, `mypy` | clean | round 1 fixes |
| T2 | PostgreSQL targeted: the new module | 3 passed | round 1 fixes |
| U2 | backend unit, full (covers `tests/test_traceability.py` after the new traceability entry) | 3804 passed, 1999 skipped, 1 known warning | round 1 fixes |
| M3 | migration-only check | passed (head `20261209_135`) | before P2 (migration docstring changed after P1) |
| P2 | PostgreSQL full | 2163 passed, 2 known warnings (Starlette; pydantic `UnsupportedFieldAttributeWarning` once) | round 1 fixes (test and migration files changed after P1) |

No check or run failed; no correction used. After P2 only text changed (this record, docs/010,
ops/V1_056_QUESTIONS.md, ops/NOW.md).

## Review round 1 (fresh read-only subagents, during P1; told to write no file anywhere and run nothing)

Independent: 0 blockers, 3 should-fix, 5 notes. Security: 0 blockers, 0 should-fix, 4 notes.

- Should-fix 1 (independent, test): the follow function's stream tie-break had no behaviour test,
  and the implementer's reason (no writer makes a changing correction with two payments from one
  Credit) was wrong: since migration 103 a `REFUND` correction runs the shared DL-032 step after
  its release, and its plan may hold several Credit steps from one Credit. Fixed with the
  reviewer's set-up (below): `test_a_tie_in_a_changing_correction_s_payments_is_broken_by_write_order`.
- Should-fix 2 (independent, test): the order of the listed payments (the first source anchor)
  was not checked. Fixed: both tests assert the order of E's `credit_applications` list, on the
  real path (newest first) and under the tie (write order).
- Should-fix 3 (independent, text): the record and the docs must correct the premise of Q-111
  and cite the trigger checks, not "every writer stamps". Fixed: migration docstring, test module
  docstring, docs/004, docs/010, the plan, this record.
- Claims confirmed by the independent reviewer: the tie is impossible on the real path (confirmed
  under the run rule; the database checks above), so the hand-built tie is the only way to test
  it; every live newest-first order is patched and the copies in migrations 130 and 132 are dead;
  the unpatched orders (named Deposit application reversals, the 10e-3d-2a listing of the parts
  applied again, the `REFUND` release order) never decide who pays or how much; effect sequences
  of two corrections are compared only on a time tie, which cannot happen, and the id decides
  what is left; no refusal added and no result changes where times differ.
- Notes taken (text): the Deposit-form tie-break can never decide (unique `application_order`),
  said in docs/004 and the test module docstring; the migration docstring now describes the source
  lists as the own and swept payments the reversal undoes and the `newer` walk as the pooled own
  path's choice; "the first test shows it" reworded.
- Notes not taken: a stricter cross-correction key (correction time, correction id, effect
  sequence) is not needed, because the comparison is never reached.
- Security notes (no fix): one index lookup per row in the source function's sort (unique link
  columns; negligible at V1 scale); staff choose the step order and so the write order, but every
  payment is already stamped later in that order, so the tie-break gives no new lever and a
  confirm still needs `financial.approve`; the test's `ALTER TABLE ... DISABLE TRIGGER` holds a
  lock for one short rolled-back transaction in the test database only; the named Deposit
  application reversal writer keeps its order (consistency only). Least privilege, SQL built from
  constant text, `effect_sequence` written only by the internal `app.link_settlement_correction_effect`,
  the rollback before psycopg's commit-on-exit, and the 27 revision-only test changes all checked.
  Secret scan of the diff and the two new files: clean; no env file listed.

Reviewer's set-up for the follow test (independent, round 1; built as given):

1. `case = refunded_case(url)`; `earlier = return_only(case, refund, 1_000)` (E).
2. `_, L1 = unpaid_charge(...)`; `return_only(case, refund, 500, SettlementCreditStep(credit, LINE,
   L1, 1_500))` (S): one payment P, S's own money at [0,500), E's at [500,1500).
3. After S, `L2` and `L3` with `unpaid_charge`; `third_party_payment(..., L2, 1_000)` and
   `(..., L3, 800)`: open debt 500 and 700.
4. Q = `confirm_refund(case, record_refund(case, command(case, L1, 1_500,
   SettlementCreditStep(credit, LINE, L2, 500), SettlementCreditStep(credit, LINE, L3, 700))))`
   (helpers of `test_settlement_deposit_refund_correction_migration.py`): Q releases P whole,
   pays 500 and 700 again from the same Credit and refunds 300.
5. Real path: following E's stretch of P (offset 500, part 1,000) gives the L3 payment (700,
   offset 200, part 500) and the L2 payment (500, offset 0, part 500).
6. Then the same always rolled-back owner transaction: Q's two payments share one time and the
   lower id gets `max+1`; follow and E's `source["swept"]` follow write order, differ from the
   id-only result, and a second read gives the same.

## Review round 2 (fresh read-only subagents, during P2; told to write no file anywhere and run nothing)

Independent: 0 blockers, 0 should-fix, 3 notes: clean. Security: 0 blockers, 0 should-fix,
4 notes: clean. No round 3 is needed.

- Independent: each round 1 fix checked (the follow test exercises the patched stream
  `row_number()` of migration 134 under the tie and asserts `by_write != by_id`; both tests
  assert the listed order on the real path and under the tie; the premise texts match migrations
  41 line 556, 86 lines 316 and 409, kept by the later patches 67, 89, 91, 102 and 123, and
  migration 100 stamps each rest with `credit_excess_instant`); the test arithmetic checked by
  hand for both id orders; `tied_by_hand` restores everything (rollback before psycopg's
  commit-on-exit; `max+1` cannot collide with the unique sequence); the owner-answer records
  agree with each other; the 27 changed committed lines compared with HEAD are revision strings
  only, nothing weaker; traceability parses, three entries only appended. The reviewer disclosed
  one read-only `awk` and one `python3 -I` JSON parse.
- Notes taken (text): the Q-2026-10-14-111 body in ops/V1_056_QUESTIONS.md still said the rests
  share one stamped time; a "Built" paragraph under the owner answer now corrects it; this
  record's run table now lists U2, M3 and P2.
- Note not taken (slice 12 candidate, optional): the helper's post-check expects every user
  trigger of the two tables to be enabled ('O'); comparing `tgenabled` before and after would
  stay right if a trigger is ever set to ALWAYS or REPLICA. Also harmless: the migration
  docstring names BR-SETTLE-008 and the follow test's traceability entry adds BR-CREDIT-014.
- Security: the helper's trigger disabling and updates cannot leak (rollback on every path,
  serial run, earlier connections closed before the ALTER); the f-string takes table names from
  a literal tuple; a NULL sequence would sort first under DESC but cannot occur (unique links,
  every ranked row is a linked effect, and the key never decides). Least privilege tested;
  `effect_sequence` assigned only by the internal `app.link_settlement_correction_effect` in
  every version (migrations 97, 98, 101, 105, 122, 124); the 27 test changes are revision strings
  only. Standard secret scan of `git diff HEAD`, the untracked files and the nine saved run
  outputs (P2 as far as written): clean (only prose words, a migration title and a test module
  name); no env file or backup listed.

Commit after the standard secret scan of the staged diff and the saved run outputs.

## Correction (2026-10-15, sub-slice 10e-3d-2c)

The statement above that "a Deposit tie cannot be made even by hand" was the implementer's; no
reviewer of this sub-slice confirmed it. On the owner's instruction the round 1 independent
reviewer of sub-slice 10e-3d-2c checked it and found it wrong: inside an always rolled-back owner
transaction the unique constraint `deposit_applications_settlement_order` can be dropped too
(DDL is transactional), so two Deposit payments of one correction can share their time and
application order. The test `test_a_deposit_tie_made_by_hand_is_broken_by_write_order` was added
in sub-slice 10e-3d-2c; its set-up is in ops/reviews/V1-056-slice-10e-3d-2c-return-reversal-returned-refund.md.
