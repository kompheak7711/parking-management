# V1-056 sub-slice 10e-3d-2d-2b-2 — a return's money on a payment that another Lease's REFUND correction changed is followed into its Refund and payments and undone through the companion — review record

Sub-slice: 10e-3d-2d-2b-2 (owner answers (a) to Q-2026-10-13-103 point 3 and Q-2026-10-13-107;
owner answer 4 of 2026-10-16: a charge-back of the other Lease's Refund goes on that Lease when its
recipient is that Lease's signed Customer). Migration `20261214_140`. Base commit: 88cb214
(10e-3d-2d-2b-1). Built on 2026-10-16. Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-014; DB-SETTLE-005, DB-REFUND-002. Design:
ops/V1_056_PLAN.md, "10e-3d-2d-2b-2 pre-code note" (10e-3d-2d entry); set-up R1 of the 2b-1 review
record.

## Built

- Migration `20261214_140`: new internal `app.settlement_refund_owner(uuid)` (no grant); exact-text
  patches (each anchor found once, else the migration stops) of the follow function (another
  Settlement's `REFUND` correction of a Credit payment, an allow-list), the source function (the
  charged Lease of a Refund part is its holder's Settlement's Lease; the recovery entry's
  `closed_final_settlement_id` is that Lease's Final Settlement; `companions` also from the Refund
  parts), the companion source function (key `recoveries`), the refusal function (companions also
  match the Refund parts; a charge-back of another Settlement's Refund names that Settlement or no
  Lease; the `OTHER_SETTLEMENT` message reworded), the confirm (another Settlement's charge-backs
  linked to its companion; the companion's audit event names them), the result function (each
  companion's `recoveries`), `app.settlement_return_reversal_refund` (a swept Refund of a
  companion's Settlement), `app.refund_recovery_allowed` (the companion branch; since round 2 its own
  `RETURN_REVERSAL` branch takes only a Refund of no other Final Settlement) and
  `app.settlement_return_reversal_recovery_amount` (reads a companion's draft too; implementer's
  addition at build, not in the pre-code note: without it a charge-back of a part of the Refund's
  net linked to a companion would be refused; run rule "Design changes during a build"). No table,
  column, constraint, trigger or lock change.
- Tests: new module `backend/tests/test_settlement_return_reversal_other_refund_follow_migration.py`
  (six tests: R1, R1 with 1,500, S-A and S-B of review round 1, the rolled-back recovery check,
  least privilege), last in `scripts/database-test.sh`; committed tests changed:
  `test_settlement_return_reversal_companion_migration.py::test_a_take_whose_correction_also_refunded_from_the_credit_is_undone_through_the_companion`
  (X0's source now has no open part and lists its parts; X0's refused attempt removed; owner
  answer 4 and answer (a) to Q-2026-10-13-103 point 3; standing rule of 2026-10-11),
  `test_settlement_return_reversal_changed_payment_migration.py::test_the_follow_function_fails_closed`
  (its one case about a Settlement other than the Refund correction's now expects that correction
  to be followed into its 800 Refund; same answers and rule; found by P1), the
  `OTHER_SETTLEMENT` message constant in `test_settlement_returned_value_other_settlements_migration.py`;
  the 27 head-revision assertions in 15 modules move to `20261214_140` (revision strings only,
  `sed`). Traceability: the notes of those two changed tests' entries updated (after the first
  1,598), six appended.
- Docs: docs/004 (DB-SETTLE-005, a 10e-3d-2d-2b-2 paragraph), docs/010, the plan (pre-code note).

Pre-code read (2026-10-16): catalog dumps D1 (the follow, placed, walk, source, refusal, confirm,
result, companion source, recovery writer, recovery allow, recovery scope, application owner,
left, takes and parts functions), D2 (`app.begin_settlement_correction`,
`app.assert_payment_return_recoveries_allowed`, `app.write_correction_one_time_charge`,
`app.settlement_correction_linked`, `app.refuse_closed_final_settlement_change`, the companion id
function), D3 (`app.validate_general_refund_correction`) and D4
(`app.settlement_return_reversal_recovery_amount`); no `REDACTED` marker. Every anchor of the
migration was counted against these bodies before the first run (each found once).

Read-only search at build (2026-10-16): tests that expect `CHANGED_APPLICATION` from another
Settlement's correction: the changed committed test (R1, a `REFUND` correction; changed) and
`test_the_rest_of_another_lease_s_payment_is_put_back_through_the_companion` (X3's reversal after
a companion changed the payment; a `RETURN_REVERSAL_COMPANION`, still refused, unchanged). Tests
that read the `OTHER_SETTLEMENT` message: the constant in
`test_settlement_returned_value_other_settlements_migration.py`, also imported by the 2b-1 module
(changed once). Tests that read companion draft payloads, companion result entries or audit states
read them by key (no whole-object comparison), so the new `recoveries` keys change nothing. Tests
that call the follow, recovery allow, recovery scope or share functions directly use one
Settlement or compare bodies at their own revision.

## Runs

| Run | Result |
|---|---|
| D1, D2, D3, D4 | catalog dumps |
| FC1/L1/Y1 | passed |
| M1 | passed (`20261214_140` head) |
| T1 | 18 passed, 3 failed: the new module's set-up expected the line to owe the refunded amount after Q; a `REFUND` correction lowers the charge, so it owes 0 (cause A, 1 of 2) |
| FC2/L2/Y2 | passed |
| T2 | 2 passed, 2 failed: the expected charge-back entry lacked `refund_number` (cause A, 2 of 2) |
| FC3/L3/Y3 | passed |
| T3 | 4 passed |
| U1 | 3803 passed, 1 failed: the traceability manifest lacked the four new tests (cause B, 1 of 2) |
| U2, M2 | 3804 passed; migration check passed |
| P1 | 2191 passed, 1 failed: the committed `test_the_follow_function_fails_closed` (changed-payment module) called the follow function with a random Settlement and expected `CHANGED_APPLICATION`; another Settlement's `REFUND` correction is now followed into its Refund (owner answer 4; the build search missed it because it names no real other Settlement) (cause C, 1 of 2) |
| FC4/Y4 | passed |
| L4 | 2 lines too long (cause D, 1 of 2) |
| FC5/Y5 | passed |
| L5 | 1 line too long, the rest of the same rewrap (cause D, 2 of 2) |
| FC6/L6/Y6 | passed |
| M3 | passed |
| T4 | 31 passed (the new module with S-A and S-B, the changed-payment, companion, other-Settlements and other-refunding-take modules) |
| U3, M4 | 3804 passed; migration check passed |
| P2 | 2194 passed (warnings: the known Starlette deprecation and two Pydantic alias warnings of the unchanged Credit Refund API tests) |
| FC7/L7/Y7, M5 | passed (after the round 2 fixes) |
| T5 | 100 passed (the new module and every return reversal and returned-value module, since N-2 changes the reversal's own recovery branch) |
| U4, M6 | 3804 passed; migration check passed |
| P3 | 2194 passed (warnings: the known Starlette deprecation and one Pydantic alias warning of the unchanged Credit Refund API tests); it includes the payment return recovery and Deposit receipt correction modules, which also run the recovery check |
| FC8/L8/Y8 | passed (after the round 3 text fixes) |
| T6 | 6 passed (the new module; last targeted run after the last fix) |
| U5 | 28 passed (`tests/test_traceability.py`; the notes changed after U4) |

After P3 only text changed (a docstring and a comment of the new module, docs, the record, the
plan and traceability notes); T6 and U5 cover those files, so no further full run.
Corrections: cause A (wrong expectations in the new tests) 2 of 2; cause B (traceability) 1 of
2; cause C (the missed committed follow test) 1 of 2; cause D (too-long lines) 2 of 2.

Read-only search after P1: no other test calls the follow function, or a function that reads
it, with another Settlement than the changing correction's (the remaining direct callers use the
correction's own Settlement).

## Review round 1 (fresh read-only subagents, during P1; told to write no file and run no test, script or database command)

Independent: 0 blockers, 1 should-fix, 8 notes. Security: 0 blockers, 2 should-fix, 7 notes.

- Should-fix SF1 (security, a fail-closed check that adds a refusal; independent notes 3 and 4
  the same): a charge-back of another Settlement's Refund whose Settlement is not a listed
  companion would be written by no call of the confirm, with no error (no real path: the own
  Refunds belong to this Settlement, the Refund parts' Settlements are checked against the
  companions). Fixed in the refusal function: such an entry (not the returned Refund's) must
  belong to a listed companion and name that Settlement and its Lease, or no Lease and no
  Settlement. Tests: two more hand-built refusals in the 1,500 test.
- Should-fix SF2 (security, tests): the negative test showed only the unchanged final check.
  Added: after the committed confirm, the recovery check allows the companion's row no more
  outside the confirming transaction; the reversal's draft lists the other Lease's Refund and not
  X0's own Refund.
- Should-fix 1 (independent, test): no real-path test of a charge-back that is only a share of the
  other Lease's Refund's net, the case that needs the `settlement_return_reversal_recovery_amount`
  patch. Added with the reviewer's set-up S-A (below).
- Note 1 (independent, test, taken): a companion with a charge-back, two payment reversals and a
  put-back together; added with set-up S-B (below).
- Note 2 (independent, taken): the rolled-back test also asserts, after moving the link to the
  reversal, that the reversal still lists the Refund, so the refusal is the closed Settlement's
  link rule; the plan's wording "refused by B's guard" corrected.
- Note 5 (independent, taken): every companion's draft source, result entry and audit event now
  carry `recoveries` (`[]` when none); one line in docs/010.
- Note 6 (independent, taken at the commit): an as-built line in the plan.
- Notes N1 (security, taken): explicit parentheses around the follow function's allow-list (a
  code change, covered by M3, T4 and P2); N5 (taken): docs/004 says the charge's audit events on
  the other Lease carry the reversal's evidence plus `companion_settlement_correction_id`; N6
  (taken): an 11e item in the plan for the companion draft's `source.recoveries`.
- Notes checked, no change: independent 7 (the changed committed test is not weaker beyond owner
  answer 4 and answer (a) to Q-103 point 3; constants and revision strings only), 8
  (traceability, clock, flakiness, no committed one-Settlement result changes); security N2 (no
  new recovery or closed-Lease charge path), N3 (privilege), N4 (locks), N7 (the rolled-back test
  is safe).
- Point 2 (independent): the `settlement_return_reversal_recovery_amount` addition is needed (a
  share linked to a companion was refused as not the whole net) and safe (it reads only a
  companion draft linked to the row by its own effect, confirmed by the same actor in this
  transaction, written only by the confirm from the digest-checked source; the recovery check must
  still pass). Confirmed under the run rule "Design changes during a build"; who pays and how much
  do not change.
- Point 3 (independent): no real path to a recipient who is not the other Lease's signed Customer:
  a `REFUND` correction's line is on its Lease (`20261107_103:204`), its Refund goes to the
  Credit's own Customer (`20261107_103:743`, `20260906_41:1174`), a Credit application's target
  Customer is the Credit's (`20260906_41:554`, `:563`), an Invoice on a Lease goes only to a signed
  Customer of it (`20260827_29:838-843`) and `signed_at` is never cleared (`20260826_23:472-473`).
  The no-Lease branch for another Settlement's Refund is defensive; recorded as a limit.

Reviewer's set-up S-A (independent, round 1; built as
`test_two_returns_charge_back_their_shares_of_another_lease_s_refund_in_turn`):
1. The first Lease closed; a REFUND correction of its Initial Rent line refunds 2,000 from a new
   Credit; `second = second_lease(url, monkeypatch, first["customer"])`.
2. `x0 = return_only(first, refund, 700)`; `x0b = return_only(first, refund, 800)`; the Credit
   holds 1,500.
3. `_, line = unpaid_charge(url, second, second["person"])` (1,500); a REFUND_RETURN of the second
   Lease's Pet Deposit Refund (5,400) with `SettlementCreditStep(credit, LINE, line, 1_500)` and
   `settlement_refund(second, "pet", 5_400)` (C1: X0's 700 first, then X0b's 800).
4. `confirm_refund(second, record_refund(second, refund_command(second, line, 1_500)))` (Q: the
   Credit 0, the line owes 0).
5. Expected: X0's source swept `[(Q, REFUND, q_refund, 1,500, 700)]`, recovery 700 of net 1,500 on
   the second Lease; its reversal charges 700 through a companion; Q's Refund's net 800, the first
   Refund's net 1,200. Then X0b: part 800 of net 800 through a second companion; Q's net 0, the
   first Refund's net 2,000, the Credit 0; reconciled.

Reviewer's set-up S-B (independent, round 1; built as
`test_one_companion_charges_back_reverses_two_payments_and_puts_back_a_rest`):
1. `two_lease_case(..., returned=1_500, credit_paid=1_500)`; `later = return_only(first, refund,
   300)`; `second_charge = charge(url, second, 300)`.
2. `confirm_refund(second, record_refund(second, refund_command(second, first_charge, 200,
   SettlementCreditStep(credit, LINE, second_charge, 300))))`.
3. Reverse X0 (not X1). Expected: X0's source reapply `[(rest, 300)]`, one companion, recovery 200
   on the second Lease; the companion reverses the 300 step and the 1,300 rest, puts 300 back on
   the rest's line and charges 200 back; the first charge owes 1,000, the new charge 300, the
   Credit 0, the other Refund's net 0, X0's Refund's net 1,700; drafts and corrections +2, Credit
   applications +1; X1's reversal afterwards is refused `CHANGED` (the companion changed the
   payment; the 2d-2a limit), writing nothing.

## Review round 2 (fresh read-only subagents, during U3, M4 and P2; told to write no file and run no test, script or database command)

Independent: 0 blockers, 2 should-fix (one test, one text), 4 notes. Security: 0 blockers, 1
should-fix (test), 6 notes. Every round 1 fix confirmed; the changed committed tests (the
companion test, the follow test of the changed-payment module, the message constant, the 27
revision strings) are not weaker beyond owner answer 4 and answer (a) to Q-2026-10-13-103 point 3;
the follow test's new expectation is exactly the approved allow-list, and its other side stays
covered on the real path (another Settlement's companion still gives `CHANGED`). The independent
reviewer saved a copy of HEAD's traceability file in the session scratchpad (outside the repo).

Under the round-3 rule (no blocker; every should-fix a test or a text change):
- Should-fix (both, test): two of the SF1 check's three branches had no test of their own. Added
  in the 1,500 test: a charge-back that names the second Settlement but the first Lease (only the
  Lease branch refuses) and a source with no Refund part, no swept total and no companion whose
  charge-back of the second Settlement's Refund stays (the companion-membership branch).
- Should-fix (independent, text): the record's test counts and changed-test list, and the docs/010
  "Updated tests" list, were stale after round 1; fixed; the plan's as-built line names the
  changed follow test.
- Note N-2 (security, a fail-closed check that adds a refusal, taken): the widened
  `app.settlement_return_reversal_refund` also feeds the recovery check's `RETURN_REVERSAL`
  branch, so a row for another Settlement's Refund linked to the reversal alone was refused by one
  layer (the closed Settlement's link) instead of two; that branch now also requires the Refund
  to have no owner or the reversal's own Settlement.
- Note 1 (independent, code, taken): the confirm's companion loop's EXISTS also leaves out the
  returned Refund, as its list does.
- Note 4 (independent, text, taken): the migration docstring names the companion membership.
- Notes kept: independent 2 (no test of `companion_settlement_correction_id` in the charge's audit
  evidence; docs/004 says so from the code), 3 (no action); security N-1 (an optional unreachable
  Deposit call of the follow function), N-3 to N-6 (checked, no change; N-6 the same text fix as
  above).

## Review round 3 (fresh read-only subagents, during U4, M6 and P3; told to write no file and run no test, script or database command)

Independent: 0 blockers, 2 should-fix (both text), 4 notes. Security: 0 blockers, 1 should-fix
(text), 4 notes. Both confirmed every round 2 fix: the two new hand-built refusals each reach only
their own branch of the new refusal check (the Lease branch; the companion-membership branch, on
the pooled path); the N-2 condition's parentheses and precedence are right, it restores two
layers, and it cannot refuse an existing same-Settlement recovery (the returned Refund's owner is
this Settlement or none; a held-value Refund's held-from correction is of the same Settlement; a
Final Settlement Deposit Refund has no effect row); the confirm writes every recovery exactly once
or the refusal function refuses it. The independent reviewer noted that docs/004 changed while it
read (the round 3 security text fix, made in parallel).

Fixed under the round 3 rule for text fixes (owner, 2026-10-16), no round 4:
- Should-fix (both, text): the rolled-back test's docstring and comment and its traceability notes
  said the row linked to the reversal is refused "only because" the other Lease's Settlement no
  longer links it; since N-2 it is refused twice over. Reworded.
- Should-fix (independent, text): docs/010 and this record's Built list now name the N-2 narrowing;
  docs/004 got the same clause (security note).
- Note (independent 4, taken): the run table and this section; a docs/010 review-rounds bullet.

Notes kept:
- Security: a new assertion `source["own_parts"] is None` in the 1,500 test would pin the pooled
  path of the companion-membership case. Not taken, so that no test code changes after P3 (the
  independent reviewer confirms the source is on the pooled path).
- Both: N-2 has no isolating test, and none is possible at row level. A row is linked to one
  correction only, so the closed Settlement's link check always refuses it too. Isolating N-2
  would need a fixture change (clearing the other Settlement's `closed_at` in a rolled-back
  transaction). Recorded as a defense-in-depth limit.
- Security: P3 ran after the round 2 fixes and covers the other recovery paths
  (`test_payment_return_recovery_migration.py`, `test_settlement_deposit_receipt_correction_migration.py`).
- Independent 2 and 3: checked, no change.

