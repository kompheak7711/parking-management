# V1-056 sub-slice 10g — the wrong-Unit Payment move after closure — review record

Sub-slice: 10g (owner answer 4 to Q-2026-10-06-36; answers 1 and 5 to Q-2026-10-06-37). Migration
`20261222_148` (new functions and one relaxing patch). Base commit: a272a9f. Built on 2026-10-16
and 2026-10-17. Not pushed.

Rule IDs: BR-PAY-042, BR-SETTLE-012, BR-SETTLE-013, BR-SETTLE-016, BR-AUTH-010; DB-PAY-008,
DB-SETTLE-003, DB-SETTLE-005. Design: ops/V1_056_PLAN.md, "10g pre-code design" and "10g as built".

## Built

- Migration `20261222_148_settlement_payment_move.py`: new writers
  `app.record_settlement_payment_move_draft` (`final_settlements.prepare`) and
  `app.confirm_settlement_payment_move` (`financial.approve`, a human approver), EXECUTE to the
  financial role; new internal `app.settlement_payment_move_source`,
  `app.settlement_payment_move_allowed` and `app.settlement_payment_move_result`; one relaxing
  exact-text patch of `app.validate_payment_move` (a `SETTLEMENT_CORRECTION` draft of the variant
  `PAYMENT_MOVE`, confirmed in this transaction by the move's approver, whose decision names the
  move, with the reversal and the new allocation linked; the slice 7 branch unchanged). No table,
  column, trigger or other grant change.
- Service: `property_rental/payment_move.py` gains `RecordSettlementPaymentMoveCommand`,
  `settlement_payment_move_draft_id`, `PaymentMoveStaleDraftError`, `record_correction` and
  `confirm_correction`; the shared mapping maps P5S02 (stale) and P5S01 (conflict), also for slice 7.
- Tests: new `test_settlement_payment_move_migration.py` (9 tests, last in
  `scripts/database-test.sh`); four new unit tests in `test_payment_move.py`.
- Committed tests changed: none, except the 27 head-revision assertions in 15 modules (revision
  strings only; a script checked each file's count) and three imported names in
  `test_payment_move.py`.
- Traceability: 13 entries appended (3,157 to 3,169); two notes of this sub-slice's own new
  entries updated after review round 1.
- Docs: docs/002 (BR-SETTLE-013 amendment, BR-PAY-042 sentence), docs/004 (DB-PAY-008,
  DB-SETTLE-005), docs/010 (owner notes on the 10f-2 report, build, updated tests), the plan (10h,
  11e and slice 12 notes of 10f-2; 10g design, as built, 10h items, slice 12 notes),
  ops/V1_056_QUESTIONS.md (the 10f-2 report answers; new Q-2026-10-17-120).

Read-only search for affected tests (before T1 and P1, again before P2): every backend test naming
`validate_payment_move`, `payment_moves`, `payment_move_source`, the slice 7 recorder and confirm,
`settlement_payment_move_allowed`, and every test enumerating function grants or the whole catalog.
Found: the slice 7 move tests, the Payment return tests and the returned-Payment correction tests
(run in T1); grant checks of named signatures and catalog comparisons between fixed earlier
revisions; none affected.

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump (read only; no `REDACTED` marker) |
| FF1/FC1/L1/Y1 | passed (formatter first: one file reformatted) |
| M1 | passed (`20261222_148` head) |
| T1 | 94 passed (the new module, the slice 7 move modules, the Payment return and returned-Payment modules) |
| T2 | 62 passed (`test_payment_move.py`, `tests/test_traceability.py`; after the rename of the refusal test, whose first name an earlier module already used: the traceability append script's duplicate check refused it before any file was written, so no check or run failed) |
| U1 | 3847 passed |
| M2 | passed |
| P1 | 2240 passed (the known Starlette deprecation and Pydantic alias warnings) |
| FF2/FC2/L2/Y2 | passed (after the round 1 fixes) |
| M3 | passed |
| T3 | 69 passed (the new module, the slice 7 move modules) |
| U2 | 3847 passed |
| P2 | 2243 passed (the known Starlette deprecation warning) |
| FF3/FC3/L3/Y3 | passed (after the round 2 test and text fixes) |
| M4 | passed (the migration docstring changed) |
| T4 | 71 passed (the new module, `test_payment_move.py`, `tests/test_traceability.py`) |
| U3 | 3847 passed (before round 3, standing rule) |
| P3 | 2243 passed (before round 3; the known Starlette and Pydantic alias warnings) |
| T5 | 62 passed (`tests/test_traceability.py`, `test_payment_move.py`; after the round 3 text fixes) |

No check or run failed, so no correction was counted. Full outputs are in
`~/Development/prm-run-logs/v1-056-10g-*.txt` (format, lint and type checks are short and not
saved). T2's output was not saved either (round 3 finding); its 62 tests (`test_payment_move.py` 34, `tests/test_traceability.py` 28) passed again in U1, U3 and T4, whose outputs are saved. Before the first lint run the changed service and test files were searched for lines over
100 characters (one found and wrapped; the migration keeps `# ruff: noqa: E501` as earlier ones).

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: 0 blockers, 4 should-fix, notes. Security: 0 blockers, 3 should-fix, notes.

- Should-fix (independent 1): the two-Settlement case. After Lease A's correction moved money onto
  Lease B and B closed relying on it, neither Settlement's correction can move it again, and the
  refusal message pointed to a path that is always refused. Fixed: the message now says "A
  correction of another Final Settlement wrote this allocation; this correction cannot move it";
  the case is Q-2026-10-17-120 point 1 (recommendation (a), a known limit, as Q-2026-10-10-72 point
  3); the docs say so. The other paths that can still change such an allocation (an ordinary
  credit Adjustment of the other Lease, a `REFUND` correction of the other Lease, the slice 7 move
  draft) are point 2, for 10h.
- Should-fix (both): the slice 7 recorder does not see a waiting correction draft, so "only one may
  wait" was wrong. Not built (it would tighten an existing function): the comment, docs/010 and the
  plan now say the correction recorder refuses while a draft of either kind waits; 10h makes the
  slice 7 recorder refuse its drafts of records a closed Settlement relied on, which covers it.
- Should-fix (independent 3; security 1, second half): the Settlement preview's pending-draft check
  does not list a waiting `PAYMENT_MOVE` correction draft whose correct Invoice is on the Lease being
  settled. Not built (a fail-closed tightening of the preview): Q-2026-10-17-120 point 3, for 10h.
- Should-fix (security 1): a correct Invoice on a Lease whose Settlement is closed was neither
  tested nor documented. It is allowed by the slice 10 design note (owner answer 7 to
  Q-2026-10-05-20). Fixed with the test `test_a_correct_invoice_on_a_closed_lease_takes_the_move`
  and docs/002 and docs/004 sentences.
- Should-fix (independent 4a): a source refusal at confirm. Fixed with
  `test_a_source_refusal_at_confirm_leaves_the_draft_pending` (the correct Invoice paid in full after
  the record; a set-up that 10h does not change, instead of the reviewer's one-call reversal, which
  10h refuses).
- Should-fix (independent 4b; security 3): the patched insert check on the real insert path.
  Fixed with `test_the_move_check_refuses_a_move_row_outside_its_correction`, set-up:
  1. `wrong_at_closure`; a slice 7 draft of the allocation recorded and withdrawn; the correction
     recorded.
  2. As the owner, in one transaction (rolled back): the correction confirmed; a copy of the draft
     with the variant `CHARGE_REDUCTION` inserted with `jsonb_populate_record`.
  3. Copies of the stored move row through
     `INSERT INTO app.payment_moves SELECT (jsonb_populate_record(NULL::app.payment_moves,to_jsonb(m)||changes)).* FROM app.payment_moves m WHERE m.draft_id=...`,
     each in a savepoint: no change (passes the check, 23505), another approver, another id, the
     other-variant draft (23514 "Payment move does not match its draft").
  4. After the real confirm, in a new transaction: another id (23514; replaced in round 2 by the
     stored move itself), and another id under the withdrawn slice 7 draft (23514; only its
     decision differs).
- Note taken (independent): the check also binds the decision's `payment_move_id` to the row
  (`app.settlement_payment_move_allowed` gains `p_move`).
- Notes taken (text): docs/010 "three imported names"; the shared P5S01 mapping named in docs/010;
  docs/002 BR-PAY-042 names 10h.
- Notes kept for slice 12 and slice 11 (the plan's slice 12 list): untested branches (an allocation
  posted after the closure but linked to this Settlement's correction; a non-human approver; a
  Late-payment Charge allocation; an unknown Settlement or allocation); the audit outcome
  `SUCCEEDED` versus slice 7's `SUCCESS`; a Payment with Credit cannot move; strip this variant's
  decision `transaction_id` in the general draft reads; read the payload only through the
  capability-filtered reads; the reason reaches both Customers' records; never log or return the
  database cause.

## Review round 2 (fresh read-only subagents, during P2; same limits)

Security: clean (0 blockers, 0 should-fix, 6 notes). Independent: 0 blockers, 4 should-fix (test
and text only), notes. Both confirm the round 1 `p_move` binding is needed-and-safe defence in
depth, and that not building the two tightenings (the slice 7 recorder's waiting check, inside the
approved 10h tightening; the preview's pending-draft check, asked as Q-2026-10-17-120 point 3) is
sound: until then both fail closed at confirm (shared `payment-move:` lock, unique source, stale or
refused source).

- Should-fix (independent 1): the later-transaction insert used a new id, which the `payment_move_id`
  binding already refuses, so it did not prove the transaction binding. Fixed: the stored move
  itself, with its own id, is refused before the primary key (23514; without the binding it would
  meet the primary key, 23505); docstring, traceability note and this record corrected.
- Should-fix (independent 2): the unit test's confirm loop now also tries
  `payments.allocations.reverse`.
- Should-fix (independent 3; security note 1): docs/004 DB-PAY-008, docs/010 and the migration
  docstring name the binding of the decision to this move.
- Should-fix (independent 4): the plan's 10h item no longer pre-empts Q-2026-10-17-120 point 2: a
  re-posted rest counts as existing at closure by the owner answer to Q-2026-10-07-39; a 10g target
  allocation waits for point 2.
- Notes taken: test 1 also asserts the one-call reversal's cause (P4904); the unit invalid-input
  test gains the zero key; Q-2026-10-17-120 point 1 names the other order (an allocation B's
  correction wrote on A's closed Lease, which the new test writes).
- Notes kept (slice 12 and slice 11): on the insert path the "another approver" and "other-variant
  draft" cases are also refused by older clauses (test 5 covers the approver directly; the variant
  filter alone is untested); the allow function finds the reversal and allocation through any
  effect of the correction (one of each today; optional: also bind them to the decision's ids and
  the header's actor); no test of the recorder's replay after the confirm; a Payment-return test of
  a 10g target allocation counted as relied on; make 10h a prerequisite of the 11d and 11e routes
  for both move kinds (security note 2); the confirm does not take the other Lease's Settlement
  draft lock (slice 7 the same; it fails closed through the Invoice locks and the digest).

## Review round 3 (fresh read-only subagents, after U3 and P3; round-3 rule of 2026-10-13: round 2 had no blocker and only test and text should-fix)

Security: clean (0 blockers, 0 should-fix, 6 notes). Independent: 0 blockers, 2 should-fix (text
only), notes.

- Should-fix (independent 1): the round 2 notes kept for slice 12 were not in the plan. Fixed: the
  plan's slice 12 item "sub-slice 10g review notes" lists them.
- Should-fix (independent 2): T2's output was not saved. Fixed in the runs text above (not rerun;
  its tests passed again in U1, U3 and T4).
- Notes taken (text): the round summaries in the plan's as-built note and in docs/010; round 1
  step 4 marked as replaced in round 2.
- Notes kept: the real-insert test's primary-key case asserts only the code 23505 (slice 12); the
  allow function could also bind the reversal and allocation ids of the decision and recheck the
  draft's preparer capability (slice 12); the replay runs before the active-approver check inside
  the begin function (as 10f-2); the general draft reads' `transaction_id` (slice 11); the service
  keeps the database cause on the exception chain (slice 11: never log or return it); a Payment
  with Customer Credit cannot move after closure (a functional gap named in the owner report).

Under the round 3 text rule of 2026-10-16 (answer 2 to the 10e-3d-2d-2a round 3 report) the two
text fixes were made and the checks rerun; no round 4. After P3 only text changed (the plan,
docs/010, this record and ops/NOW.md at the commit).
