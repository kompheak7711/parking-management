# V1-056 sub-slice 10h-1 — refusals after closure of what a closed Final Settlement relied on — review record

Sub-slice: 10h-1 (owner answers 3 and 4 to Q-2026-10-06-36, answer 5 to Q-2026-10-06-37, the
answer to Q-2026-10-07-39, the owner note of 2026-10-16 on the 10f-2 report and owner answer (a)
to Q-2026-10-17-120 point 2). Migration `20270108_165` (four internal functions, two BEFORE INSERT
triggers, one whole-body replacement of the slice 7 move source). Base commit: 7eb3f98 (the 10h
pre-code design). Built on 2026-10-19 in one fresh session. NOT committed: STOPPED after review
round 1 and run P1 (Q-2026-10-19-142). Not pushed.

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
- New module `test_settlement_relied_on_reversal_migration.py` (six tests, last in
  `scripts/database-test.sh`).
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

Full outputs in `~/Development/prm-run-logs/v1-056-10h-1-*.txt`, one file per attempt.

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: 2 blockers, 4 should-fix, 6 notes. Security: no blocker, 2 should-fix (tests only), 5
notes; every writer of both tables covered, the link cannot be faked, lock order matches the
insert checks, the 8e-1 refusal, the 8e-3 confirm and the correction lock helper; privileges and
settings kept; nothing exposed.

Open (waiting for Q-2026-10-19-142; nothing fixed yet):

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
