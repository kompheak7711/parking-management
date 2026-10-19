# V1-056 sub-slice 10h-1 — refusals after closure of what a closed Final Settlement relied on — review record

Sub-slice: 10h-1 (owner answers 3 and 4 to Q-2026-10-06-36, answer 5 to Q-2026-10-06-37, the
answer to Q-2026-10-07-39, the owner note of 2026-10-16 on the 10f-2 report and owner answer (a)
to Q-2026-10-17-120 point 2). Migration `20270108_165` (four internal functions, two BEFORE INSERT
triggers, one whole-body replacement of the slice 7 move source). Base commit: 7eb3f98 (the 10h
pre-code design). Built on 2026-10-19 in one fresh session, which stopped after review round 1
and run P1 (Q-2026-10-19-142); finished on 2026-10-19 in a second fresh session after the owner's
answers to Q-2026-10-19-140, -141 and -142. Committed (this record is part of the 10h-1 commit;
see git log). Not pushed.

## Built (in the working tree)

- Migration `20270108_165_settlement_relied_on_reversals.py`: `app.closed_settlements_relying_on_allocation`,
  `app.closed_settlements_relying_on_credit_application` (the 10e-1a "relied on"),
  `app.refuse_relied_on_allocation_reversal()` and `app.refuse_relied_on_credit_application_reversal()`
  (no grant); triggers `a0_payment_allocation_reversals_relied_on` and
  `a1_customer_credit_application_reversals_relied_on` (P5S01, the 8e-1 text, unless every
  Settlement that relied on the record links the reversal to its correction in this transaction);
  `app.payment_move_source` refuses (55000) an allocation a closed Settlement relied on before the
  slice 7 body.
- Services: the allocation service maps P5S01 to a conflict; the Credit service gives the
  closed-Settlement text for the new refusal and keeps its 8e-2 text.
- Committed tests changed: the 27 head-revision strings in 15 modules; the four
  `slice_7_draft_refusal` expectations; the P4904 expectation of the moved allocation's one-call
  reversal; two 10g tests keep their waiting-draft and withdrawn-draft checks with a hand-built
  slice 7 draft (`hand_built_move_draft`).
- New module `test_settlement_relied_on_reversal_migration.py` (nine tests after rounds 1 and 2,
  last in `scripts/database-test.sh`) and new test support module
  `relied_on_reversal_test_support.py` (owner answer (a) to Q-2026-10-19-142).
- Second session, owner answer (a) to Q-2026-10-19-142 (every check and amount unchanged; each
  changed set-up asserts the 10h-1 refusal first and has a short comment; no name became wrong, so
  no rename). Committed tests changed:
  - `test_settlement_return_reversal_put_back_migration.py`: the fixture `open_rent_line` (so
    `put_back_case` and `::test_a_credit_put_back_on_a_rent_invoice_is_labelled_and_names_what_it_restores`,
    `::test_a_later_refund_correction_keeps_the_label_on_the_re_posted_rest`,
    `::test_only_a_correction_s_put_back_takes_the_label`, `::test_the_put_back_rule_fails_closed`)
    and the two reversals in `::test_the_q104_example_puts_the_service_part_back_on_its_own_line`
    (`reverse_allocation_by_hand`: the one-call refusal asserted, then the same database function
    as the owner with only the 10h-1 allocation trigger disabled in that transaction);
  - `test_settlement_return_reversal_other_refunding_take_migration.py::test_a_companion_puts_back_another_lease_s_rent_line_payment_on_its_own_line`
    (no code change; it uses `open_rent_line`);
  - `test_settlement_returned_payment_migration.py::test_refusals_stale_drafts_and_a_deposit_that_would_still_hold_money`
    (the owner insert's refusal asserted in a savepoint, then the insert with that trigger
    disabled, and `SET CONSTRAINTS ALL IMMEDIATE` before the trigger is enabled again);
  - `test_settlement_correction_plan_migration.py::test_credit_released_from_a_payment_pays_its_customer_s_debt_before_the_deposit`
    (in both hand-built correction transactions the ordinary writer's release refusal is asserted,
    then the release is written with that trigger disabled);
  - `test_settlement_payment_move_migration.py`: `hand_built_move_draft` stores the source and
    digest the slice 7 recorder would store (round 1 independent S2, security should-fix 1), and
    the comment above the P5S01 assertion of
    `::test_a_wrong_allocation_the_settlement_relied_on_moves_through_a_correction` is reworded
    (round 3 note).
- Docs: docs/002 (BR-PAY-042, BR-SETTLE-013), docs/004 (DB-PAY-008, DB-SETTLE-005), docs/005
  (API-059, API-063), docs/010; traceability appended (six entries).

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump of the 10h functions (pre-code design), no `REDACTED` marker, `~/Development/prm-run-logs/v1-056-10h-D1.txt` |
| I1/FF1/FC1/L1/Y1 | passed (long-line search first: three lines rewrapped; the formatter reformatted the new module, a normal step; each check in its own call) |
| M1 | passed |
| T1 | 161 passed (12 modules in the full-suite order: slice 7 move, allocations, Credit applications, 8e-1, 8e-2, the `REFUND`, Late-payment Charge `REFUND`, after-closure return, 10f-2, 10g, 10g-2 and the new module) |
| U1 | 3866 passed |
| M2 | passed |
| P1 | 2378 passed, 8 failed (cause A below) |
| (second session, after the owner's answers and the round 1 fixes) | |
| I2/FF2/FC2/L2/Y2 | passed (long-line search first: one line rewrapped; the formatter reformatted two test files, a normal step; each check in its own call) |
| M3 | passed |
| T2 | 193 passed, 3 failed (16 modules in the full-suite order; cause B below) |
| I3/FF3/FC3/L3/Y3 | passed (the import sort merged two imports, a normal step) |
| T3 | 18 passed (the two modules changed since T2: returned Payment, new module) |
| U2 | 3866 passed |
| M4 | passed |
| P2 | 2389 passed |
| I4/FF4/FC4/L4/Y4, M5 | passed (after the round 2 fixes) |
| T4 | 41 passed (the five modules changed since T3) |
| U3 | 3866 passed |
| P3 | 2389 passed (two pydantic warnings from the unchanged `test_credit_refund_api_migration.py`) |
| I5/FF5/FC5/L5/Y5 | passed (after the round 3 text and assertion fixes) |
| T5 | 50 passed (the six modules changed since P3) |
| U4 | 3866 passed |
| M6 | passed |
| P4 | 2389 passed |

Cause A (P1, 8 failures; outside the read-only search of the pre-code design, which missed these
modules): each test builds its scenario with a reversal the new triggers refuse.
`test_settlement_return_reversal_put_back_migration.py::test_a_credit_put_back_on_a_rent_invoice_is_labelled_and_names_what_it_restores`,
`::test_the_q104_example_puts_the_service_part_back_on_its_own_line`,
`::test_a_later_refund_correction_keeps_the_label_on_the_re_posted_rest`,
`::test_only_a_correction_s_put_back_takes_the_label`, `::test_the_put_back_rule_fails_closed`
and `test_settlement_return_reversal_other_refunding_take_migration.py::test_a_companion_puts_back_another_lease_s_rent_line_payment_on_its_own_line`
(the one-call reversal in `open_rent_line` and `put_back_case`, "open until sub-slice 10h");
`test_settlement_returned_payment_migration.py::test_refusals_stale_drafts_and_a_deposit_that_would_still_hold_money`
(an owner insert of the same reversal, "still open before sub-slice 10h");
`test_settlement_correction_plan_migration.py::test_credit_released_from_a_payment_pays_its_customer_s_debt_before_the_deposit`
(a hand-built correction in a rolled-back transaction whose ordinary credit Adjustment's release
reversal is not linked). Fixing them changes their set-ups, not an expected result, so the owner
decides: Q-2026-10-19-142 (recommendation (a), a hand-built set-up). No correction counted.

Cause B (T2, 3 failures; one cause, a new or hand-built test set-up refused by the database;
correction 1 of 2): (1) the hand-built owner insert of the returned-Payment test left its deferred
check pending, so the trigger could not be enabled again in that transaction (55006); the
deferred checks now run first (`SET CONSTRAINTS ALL IMMEDIATE`). (2) The first form of the new
`REFUND` test asked to release value its plan could not place ("Every remaining Deposit balance
must be applied or refunded"); it was rebuilt with the second Lease closed first and an
`EXTRA_CHARGE`, so the moved allocation is the only paid value. (3) The new after-closure test
recognized Credit while a charge was open ("Applicable obligations must be handled before excess
disposition"); the Credit is now recognized first. T3 passed.

Full outputs in `~/Development/prm-run-logs/v1-056-10h-1-*.txt`, one file per attempt.

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: 2 blockers, 4 should-fix, 6 notes. Security: no blocker, 2 should-fix (tests only), 5
notes; every writer of both tables covered, the link cannot be faked, lock order matches the
insert checks, the 8e-1 refusal, the 8e-3 confirm and the correction lock helper; privileges and
settings kept; nothing exposed.

Round 1 items (all fixed in the second session after owner answer (a) to Q-2026-10-19-142;
items 1 to 5 and every note of item 6):

1. Independent B1 and B2 (= P1 cause A): the eight set-ups above; the design's claim that no other
   committed test reverses such a record was wrong (the plan's 10h entry is corrected).
2. Independent S1 (code, relaxing): `app.closed_settlements_relying_on_allocation` does not leave
   out reversed allocations, so the slice 7 wrapper refuses the move of an allocation reversed
   before the closure, which the Settlement did not rely on (the 10e-1a definition reads active
   records). Fix: read only active allocations in the wrapper's check.
3. Independent S2 and security should-fix 1 (test): `hand_built_move_draft` stores an empty
   `source`, so the withdrawn-draft attempt fails on the payload clauses of
   `app.validate_payment_move`, not only on the decision; build the real source (for example
   `app.wrong_unit_move_source(...,false)` on the owner connection).
4. Independent S3 and security should-fix 2 (test): no test of another Lease's `REFUND` correction
   releasing an allocation a `PAYMENT_MOVE` correction wrote (Q-2026-10-17-120 point 2). Security
   set-up: close Lease B first (as in `test_a_correct_invoice_on_a_closed_lease_takes_the_move`),
   let A's `PAYMENT_MOVE` correction put the allocation X on B's line, then a B `REFUND`
   correction that would release X: P5S01, the draft stays pending, nothing written.
5. Independent S4 (docs): docs/005 should also name the credit Adjustment route
   (`POST /invoices/{invoice_id}/adjustments`), which now answers 409 on an open Lease when its
   release would reverse a record a correction wrote.
6. Notes to take: a test of the slice 7 confirm refusing a waiting hand-built draft of a relied-on
   allocation (55000, the draft stays pending); a test in the new module that records made after
   the closure still reverse (today the committed `test_final_settlement_closed_refusal_migration.py`
   covers it); the trigger order and FOR EACH ROW in the least-privilege test; BR-SETTLE-016 and
   BR-AUTH-010 in the traceability entries; security N1 hardening (take the payment state, Payment
   and target locks before the Settlement-row test, so a Settlement started during a lock wait is
   seen).
7. Notes confirmed, nothing to do: the serialization guards advance twice per reversal on a Lease
   with a Settlement row (harmless); the new triggers run before the insert check's active-actor
   check (every writer checks the actor first); for an allocation of the same Property the slice 7
   refusal comes before the body's target checks (no leak).

How round 1 was fixed (second session): S1, `app.payment_move_source` refuses only when the
allocation was not reversed at or before the relying Settlement's closure (new test
`test_an_allocation_reversed_before_the_closure_keeps_the_slice_7_move`); S2, the real source and
digest in `hand_built_move_draft`; S3, new test
`test_another_lease_s_refund_correction_cannot_release_an_allocation_a_move_correction_wrote`
(the security reviewer's set-up with the second Lease closed first and an `EXTRA_CHARGE`); S4,
the docs/005 note; notes: the slice 7 confirm refusal of a hand-built waiting draft (first test of
the new module), `test_records_made_after_the_closure_still_reverse_with_one_call`, the trigger
order and FOR EACH ROW in the least-privilege test, BR-SETTLE-016 and BR-AUTH-010 in traceability,
and security N1 (both triggers take the insert check's locks before they test for a Settlement
row).

## Review round 2 (fresh read-only subagents, during P2; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: no blocker, 2 should-fix, 5 notes; every round 1 item fixed. Security: no blocker, no
should-fix, 4 notes; should-fix 1 and 2 and note N1 fixed; every writer covered, the link cannot
be faked, no new deadlock cycle, the S1 relaxation moves nothing a closed Settlement relied on.

Fixed (test and text only, so round 3 ran under the round-3 rule): independent S-1, the refusing
side of S1 is now tested (a slice 7 move draft of the wrong allocation the correction reversed
after the closure is refused, 55000); S-2, the docs/005 note covers an Invoice whose Lease has no
closed Final Settlement (none yet, or one still open). Notes taken: plan lines, a migration
comment on why a second reversal of an allocation reversed before the closure gets the
closed-Settlement refusal first, DB-PAY-008 in traceability, `assert not connection.autocommit` in
the helper (security note 2). Security note 1 (the triggers rely on READ COMMITTED) is a
tightening, so it is asked as Q-2026-10-19-143 (recommendation (a)); nothing waits. Kept as is:
the hand-built reversal's idempotency digest hashes the raw reason, not the service's exact JSON
(nothing reads it). Notes confirmed: the serialization guards now advance twice on every
reversal (harmless; no test counts them); committed test rows that break the invariant stay in
their own Properties (owner answer (a) allows it).

## Review round 3 (fresh read-only subagents, after U3 and P3; same instructions)

Independent: no blocker, 2 should-fix (both text-only), 3 notes. Security: no blocker, 1
should-fix (text-only), 3 notes. Fixed under the round-3 text and assertion rule (no round 4):
both reviewers, the Q-2026-10-19-143 "What exists" and example described a case that is in fact
refused (a Settlement row exists from its start, and a REPEATABLE READ caller whose snapshot is
later meets a serialization error); the real gap needs a snapshot taken before the Settlement is
started, and the services run at READ COMMITTED only by the server default; independent S2, the
plan line said both slice 7 move tests assert the refusal (only the first does). Notes taken (a
comment and new assertions in tests already built and green): the reworded comment in
`test_settlement_payment_move_migration.py`; the `REFUND` test also asserts that the refusal's
context names `app.refuse_relied_on_allocation_reversal()` (the 8e-1 refusal has the same code and
text); the helper re-enables and commits the triggers and then fails when its body ended the
transaction. Then I5/FF5/FC5/L5/Y5, T5, U4, M6 and P4 passed. Notes kept for slice 12: "relied
on" is decided by timestamps (`posted_at`, `occurred_at` against `closed_at`), not commit order
(the 10e-1a definition, not new); the triggers' docstring names the insert check's locks but not
its first `user_accounts FOR SHARE` (harmless, the writers take it earlier).
