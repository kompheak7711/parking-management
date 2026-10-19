# V1-056 sub-slice 10h-1b — the ordinary Credit Refund and money a correction brought back — review record

Sub-slice: 10h-1b (owner answer (b) to Q-2026-10-19-141; placement confirmed by the owner on
2026-10-19). Migration `20270109_166` (two internal functions, three exact-text replacements).
Base commit: 06c327c (10h-1). Built on 2026-10-19 in one fresh session. Not pushed.

## Built

- Migration `20270109_166_settlement_returned_credit_refund.py`:
  `app.credit_settlement_returned_value_left(uuid)` (the sum of what every post-settlement return
  into the Credit has left, each Settlement counting only its own corrections' entries) and
  `app.refuse_credit_refund_of_returned_value(uuid,bigint)` (P5S01 when that sum is above 0 and
  the amount is more than the Credit's available value less it), both with no grant;
  `app.record_refund_draft` (twelve arguments) and `app.record_credit_customer_refund_draft` call
  the refusal for a Credit source after their current-state checks; `app.confirm_refund_draft`
  takes the Credit Refund locks and calls it for a Credit source before its variant branch.
- Service: `RefundService._draft_call` maps P5S01 to `RefundConflictError` ("Refund draft
  conflicts with a closed Final Settlement"); the route answers 409.
- Committed tests changed: the 27 head-revision strings in 15 modules;
  `test_settlement_held_value_refund_migration.py::test_a_credit_return_while_a_deposit_holds_money_is_refunded_with_that_money`
  (the ordinary 600 Credit Refund now asserted refused, P5S01, nothing written; the same state then
  reached with the owner's one-call `app.create_usd_refund`, no trigger disabled; comment and
  docstring say so; every later check and amount unchanged; the name stays right).
- New module `test_settlement_returned_credit_refund_migration.py` (seven tests after round 1,
  last in `scripts/database-test.sh`); new unit test
  `test_credit_customer_refund.py::test_a_refund_draft_for_money_a_correction_brought_back_is_a_conflict`.
- Docs: docs/002 (BR-CREDIT-011, BR-SETTLE-013), docs/004 (the 10e-3d count paragraph), docs/005
  (the Refund draft routes), docs/010; traceability appended (eight entries).
- New question Q-2026-10-19-144 (the one-call Credit reversal; recommendation (a); nothing waits).

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump of the Refund draft recorders, the confirm, `app.post_credit_customer_refund` and the returned-value functions (pre-code design); three `REDACTED` markers, each the recorders' amount bound; `~/Development/prm-run-logs/v1-056-10h-q141-D1.txt` |
| M1 | passed |
| I1/FF1/FC1/L1 | passed (long-line search first: two lines fixed; the formatter reformatted the new module, a normal step) |
| Y1 | failed: one `no-untyped-call` in the new unit test (type cause, correction 1 of 2) |
| I2/FF2/FC2/L2/Y2 | passed (the tuple of calls typed) |
| T1 | 116 passed, 3 failed (10 modules in the full-suite order; cause A below) |
| I3/FF3/FC3/L3/Y3 | passed |
| T2 | 4 passed (the new module) |
| U1 | 3867 passed |
| M2 | passed |
| P1 | 2393 passed |
| (after the round 1 fixes) | |
| I4/FF4/FC4 | passed (the import sort and the formatter changed the new module, normal steps) |
| L4 | failed: an unused `time` import in the new module (lint cause, correction 1 of 2) |
| Y4 | passed |
| I5/FF5/FC5/L5/Y5 | passed (the import removed) |
| M3 | passed |
| T3 | 15 passed, 1 failed (the held-value and new modules; cause A below) |
| I6/FF6/FC6/L6/Y6 | passed |
| T4 | 16 passed |
| U2 | 3867 passed |
| M4 | passed |
| P2 | 2396 passed (one known pydantic warning from the unchanged `test_credit_refund_api_migration.py`) |

Cause A (new-test set-ups; correction 1 of 2 at T1, 2 of 2 at T3): (1) at T1, a Refund draft
recorded before the return blocks the return-only correction's record ("A draft on a source of
this Final Settlement is waiting"), so the confirm refusal is reached with a waiting draft written
by the owner through `app.insert_financial_draft` with the recorder's payload; and the Refund
helper's result is read with `refund_id`; (2) at T3, the reviewer's two-Settlement set-up calls
`second_lease`, which expects the Customer's only Credit with value to be the second Lease's own,
so the first case's other 300 of Credit (no return in it) is refunded first.

Full outputs in `~/Development/prm-run-logs/v1-056-10h-1b-*.txt`, one file per attempt.

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: no blocker, 2 should-fix, 7 notes. Security: 1 blocker, 1 should-fix, 6 notes.
Both confirmed: the three anchors match the dump once each; signatures, settings, owners and
grants kept; no new lock order (the confirm takes the same Payment state guard, Payment and Credit
locks its writers take next); P5S01 reaches the user as a bare 409; the fourteen-argument
overload delegates; splitting a Refund into small drafts, an ordinary Credit application, or
another Lease's Settlement opens no way through the draft.

Items and how each was handled:

1. Security B1 (blocker): the one-call Credit reversal (`credits.reverse`) undoes a Credit whose
   whole recognized value is available again (after a correction's Refund of it came back), and
   the money goes back to the Payment, from which a Payment Refund or a new Credit's ordinary
   Refund pays it out without a link to the Settlement. I wrote that both need the payer to owe
   nothing at the Property (`app.assert_payment_excess_eligible`), so that only the link and the
   count are lost; review round 2 showed this is wrong for a Payment confirmed for a named
   Invoice or Late-payment Charge (see round 2). Refusing it is a tightening the owner's answer
   does not name, so it is asked as Q-2026-10-19-144 (recommendation (a), the reviewer's trigger on
   `app.customer_credit_reversals`), and docs/002, docs/004, docs/005 and docs/010 now say the
   path stays open until the answer. The reviewer's set-up (to be built with an answer (a)):
   `refunded_case`, `return_only(case, case["refund"], 2_000)`, then
   `credits().reverse(case["prop"], credit, ReverseCreditCommand(uuid4(), "Wrong recognition"),
   actor=refund_actor(case["human"], case["prop"], "credits.reverse"))` succeeds today; then a
   `PAYMENT` Refund draft of 2,000 from `SELECT source_payment_id FROM app.customer_credits WHERE
   id=%s` is recorded and confirmed.
2. Independent S1 (code, own uncommitted function): each Settlement's walk also lists other
   Settlements' entries for the Credit (sub-slice 10e-3d-2d-1), so the sum counted a return twice
   when two Settlements' corrections returned money into one Credit (fail closed, but against the
   owner's "other money stays refundable"). Fixed: each Settlement counts only its own
   corrections' entries (join on `settlement_corrections.final_settlement_id`), with
   `GREATEST(left,0)` (security N6). New test
   `test_returns_of_two_settlements_into_one_credit_are_counted_once` (the reviewer's set-up).
3. Independent S2 (test): the other-money test used another Credit and a direct call where
   available equals left. New real-path test `test_other_money_in_the_returned_credit_stays_refundable`
   (the reviewer's set-up: the Customer's own 2,000 Credit pays a 1,500 charge after closure, a
   500 `REFUND` correction refunds 500 from it, a return-only correction brings the 500 back; 501
   refused, 500 refunded, 1 cent refused, the held-value Refund pays the rest). The older test's
   traceability note no longer claims the same-Credit case.
4. Security S1 (test): the race the confirm's lock is for. New test
   `test_a_refund_confirm_waiting_for_a_return_reads_the_returned_money` (the reviewer's set-up: a
   return-only correction's confirm holds the locks uncommitted, a Credit Refund draft is recorded,
   its confirm at READ COMMITTED, REPEATABLE READ and SERIALIZABLE, snapshot first, waits; the
   return commits; READ COMMITTED gives P5S01, the others 40001; the draft stays pending and the
   return keeps 2,000 left), using `wait_until_blocked_by`.
5. Security N4 (test): the fourteen-argument recorder with no Signer is refused the same way
   (assertion added to the first test).
6. Security N3 and independent N6 (text): the service message is neutral ("Refund draft conflicts
   with a closed Final Settlement").
7. Independent notes: N1 this record; N2 DL-032 in the first test's traceability; N3 the
   held-value docstring reflowed; N4 the owner-written 600 Refund passed P1 with the module's
   `assert_reconciled`; N5 the plan's money example reworded (other money in the same Credit comes
   from a partial correction Refund, as in item 3); N7 (an exact-repeat replay after a return is
   reachable only with a hand-built draft) kept as a note.
8. Notes confirmed, nothing to do: grants and settings (security N1); lock order (security N2);
   the bypass questions (security, "no bypass" for split drafts, Credit applications and a second
   Settlement).

## Review round 2 (fresh read-only subagents, during P2; same instructions)

Independent: no blocker, 2 should-fix (text only), 6 notes; every round 1 fix confirmed; the
per-Settlement own-entry sum counts each return entry exactly once (every Credit walk covers the
same corrections since migration 137). Security: 1 blocker, 1 should-fix, 4 notes; privileges,
settings, lock order, the own-entry sum and the race test confirmed.

STOPPED here: a blocker after review round 2 (ops/V1_056_TAKEOVER.md section 4; the round-3 rules
need a round 2 without a blocker). Nothing of 10h-1b is committed except this record, the plan,
the questions file and ops/NOW.md.

Security R2-B1 (blocker): the premise of the Q-2026-10-19-144 deferral was wrong.
`app.assert_payment_excess_eligible` (migration 41) checks only the named Invoice for a Payment
confirmed for an Invoice, and only the named Charge for one confirmed for a Late-payment Charge
(confirmed by reading). So after a one-call Credit reversal of a Credit from such a Payment, a
Payment Refund (or a new Credit's ordinary Refund) pays the returned money out in cash while the
Customer owes on the closed Lease. Q-2026-10-19-144 is corrected and now blocks the 10h-1b commit
(recommendation (a): build the reversal refusal inside 10h-1b, then review round 3). The
reviewer's set-up (works today by reading; under (a) the `reverse` call is refused, P5S01, nothing
written): imports `from payment_test_support import seed_payment`,
`from test_credit_migration import credit_id, recognize, service as credits`,
`from property_rental.credit import ReverseCreditCommand`; then `case = refunded_case(url)`; a
1,500 Payment seeded with `invoice_id=case["initial"]` for the Customer and recognized as Credit
`credit`; `invoice, line = unpaid_charge(url, case, case["person"])`;
`apply_credit(case, credit, invoice, line, 1_500)`; a 1,500 `REFUND` correction of that line
(`corrections().confirm_refund(..., record_refund_correction(case, refund_correction(case,
invoice, line, 1_500)), actor=approving(case["person"], case["prop"]))`), whose Refund is from
`credit`; `return_only(case, refund, 1_500)` (1,500 held, 1,500 left); a second
`unpaid_charge` (1,500 owed); `credits().reverse(case["prop"], credit,
ReverseCreditCommand(uuid4(), "Wrong recognition"), actor=refund_actor(case["human"],
case["prop"], "credits.reverse"))` succeeds today; a `PAYMENT` Refund draft of 1,500 of that
Payment then confirms although 1,500 is owed. If a seeded Payment with `invoice_id` is refused for
recognition, a Payment confirmed for the Initial Invoice through the payment service shows the
same gap.

Other round 2 items (not yet fixed; to be fixed with the owner's answer, all text, tests or
fail-closed):
- Security S1 (text): docs/002 (BR-CREDIT-011, BR-SETTLE-013) says "money a post-settlement
  correction brought back"; the code covers a returned Refund recorded by a correction, not other
  correction put-backs into a Credit (a correction's reversal of a Credit application returns
  value to the same Credit). Use the docs/005 wording and name what is not covered.
- Independent should-fix 1 (text): docs/010, "four tests" is now seven; name the three round 1
  tests.
- Independent should-fix 2 (text): the plan's 10h-1b "New tests" item (2) and item (5) (the old
  service message) need an "as built after review round 1" sentence.
- Notes: the race test should store and assert the message too (both reviewers); close the
  `refunder` connection if `BEGIN` fails before the thread starts; the wait helper's failure text
  says "Deposit lock"; a 1-cent refusal at the end of the two-Settlement test; a slice 12 note for a
  real-path version of the held-value test's hand-built 600 Refund (a 600 charge and an ordinary
  Credit application); docs/005 "(when those returns have money left)"; optional fail-closed form
  of the sum (each entry once at its largest value across the walks) or a docs/004 note that the
  join relies on the walks covering the same corrections.
