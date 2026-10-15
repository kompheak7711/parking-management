# V1-056 sub-slice 10e-3d-2d-2c — another Lease's own Final Settlement confirm that used a returned Credit counts against the return and is undone through the companion — review record

Sub-slice: 10e-3d-2d-2c (owner answer (a) to Q-2026-10-15-113). Migration `20261215_141`. Base
commit: c6941db (10e-3d-2d-2b-2). Built on 2026-10-16. Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-014, DL-032; DB-SETTLE-005 (the two hand-built
tests of the owner's notes also DB-REFUND-002). Design: ops/V1_056_PLAN.md, "10e-3d-2d-2c
pre-code note" (10e-3d-2d entry).

## Built

- Migration `20261215_141`: exact-text patches (each anchor found once, else the migration stops)
  of `app.settlement_returned_value_walk` (for a Credit, each Final Settlement whose own confirm
  applied it is a walker, at the time of its first such application, while some return's money
  is left), `app.settlement_returned_value_placed` (such a take placed on the confirm's Credit
  applications, the newest first) and `app.settlement_returned_value_follow` (an application
  with no correction link and a `final_settlement_id` is written by that Final Settlement). No
  new function, table, column, constraint, trigger, lock or grant.
- Tests: new module `backend/tests/test_settlement_return_reversal_settlement_confirm_migration.py`,
  last in `scripts/database-test.sh`: the owner's Q-113 example; a put-back with a later return
  that waits (`CHANGED_APPLICATION`); the time order (review round 1); the two hand-built tests
  of the owner's notes on the 10e-3d-2d-2b-2 limits (review round 1 set-ups (i) and (ii)); least
  privilege and forward-only. Committed tests changed: the 27 head-revision assertions in 15
  modules move to `20261215_141` (revision strings only, a script checking each file's count).
  Traceability: six entries appended.
- Docs: docs/004 (DB-SETTLE-005, a 10e-3d-2d-2c paragraph), docs/010, the plan (pre-code note
  and as-built line).

Pre-code read (2026-10-16): catalog dumps D1 (walk, placed, follow, source, refusal, confirm,
companion source, application owner, result) and D2 (left, takes, parts, put-back check, Credit
application check, Final Settlement application reversal guard, users, held Credit value, Final
Settlement Credit application writer); no `REDACTED` marker. Every anchor was counted against D1
before the first run (each found once).

Read-only search at build (2026-10-16): committed tests in which a Settlement confirm comes after
a return (two hits: `test_settlement_held_value_refund_migration.py::test_a_held_value_refund_refuses_a_correction_that_left_nothing_and_a_stale_draft_waits`
and `test_settlement_returned_value_left_migration.py::test_a_payment_return_and_a_receipt_correction_take_a_return_s_money_its_reversal_charges_back`):
both build a Lease of another Customer, whose confirm applies its own Credit, not the returned
one; no committed test changes. Tests that call the walk directly use Credits that no Settlement
confirm applies after a return.

## Runs

| Run | Result |
|---|---|
| D1, D2 | catalog dumps |
| FC1/L1/Y1 | passed |
| M1 | passed (`20261215_141` head) |
| T1 | 3 passed (the new module) |
| U1 | 3804 passed |
| M2 | passed |
| P1 | 2197 passed (warnings: the known Starlette deprecation and one Pydantic alias warning of the unchanged Credit Refund API tests) |
| FC2/L2/Y2 | passed (after the round 1 tests) |
| T2 | 6 passed (the new module) |
| U2 | 3804 passed |
| M3 | passed |
| P2 | 2200 passed (warnings: the known Starlette deprecation and one Pydantic alias warning of the unchanged Credit Refund API tests) |
| FC3/L3/Y3 | passed (after the round 2 test fixes) |
| T3 | 6 passed (the new module) |
| U3 | 3804 passed |
| M4 | passed |
| P3 | 2200 passed (warnings: the known Starlette deprecation and one Pydantic alias warning of the unchanged Credit Refund API tests) |

Corrections: none (no check or run failed). After P3 only text changed (docs/004 wrap, docs/010,
the plan, this record, ops/NOW.md); no code, migration, test or traceability file changed after
T3, U3 and P3, so no further run.

## Review round 1 (fresh read-only subagents, during P1; told to write no file and run no test, script or database command)

Independent: 0 blockers, 1 should-fix, notes; also the owner's notes of 2026-10-16 (parts B1 and
B2 below). Security: 0 blockers, 1 should-fix, 5 notes.

- Should-fix (both, test; independent SF-1 with set-up S-1, security SF1): nothing proved the
  time order of a confirm walker (a return after the confirm). Added as
  `test_a_return_after_the_other_lease_s_confirm_keeps_its_money`, with both reviewers' checks
  (set-up below).
- Security N2 (text, taken): docs/004 says why a correction's header time and a confirm's first
  application time order correctly (the Credit row lock).
- Security N1 (defence in depth, not taken): a Final Settlement id equal to a correction id would
  mix two walkers; not reachable (a Final Settlement id is a random v4 from the server, a
  correction id an md5 of its draft id); a confirm taker of another Settlement is not flagged by
  the 2b-1 allow-list of the placed function, safe because a confirm takes only through Credit
  applications.
- Security N3 and independent N-6 (test, not taken; optional in both): a confirm application
  later changed by a `REFUND` correction of its own Settlement is followed by the 2b-2 allow-list
  (the follow step is the tested 2b-2 path; the only new element, the owner fallback, is tested
  here). The independent reviewer found no cheap real path (a confirm writes its Credit
  applications before its Deposit applications, and every leaving-fixture damage line is also
  paid by a Deposit, so a `REFUND` correction releases Deposit payments first); a `REFUND` of the
  whole line would reach it. Not built; for the slice 12 list.
- Security N4 (cost, no change): one grouped scan of the Credit's applications per walk call,
  indexed; walk, placed and follow stay internal.
- Security N5 and independent N-4 (optional tests, not taken): a direct test of the P5S01
  refusal of a confirm application's reversal linked to the reversal alone (the general refusal
  is tested in `test_final_settlement_credit_application_migration.py`), and a direct follow call
  on an unlinked application with no Final Settlement.
- Independent notes checked, no change: the walk UNION's types and order (N-1), every committed
  result unchanged by the money-left rule (N-2), the placed branch (N-3), the follow fallback
  only for a confirm's application (N-4: the deferred trigger
  `customer_credit_applications_final_settlement_confirmed` requires the derived id of a
  confirmed `FINAL_SETTLEMENT` draft step; correction writers link before insert; ordinary
  writers leave `final_settlement_id` NULL), no reader joins an application part's
  `settlement_correction_id` to the corrections table (N-5), the revision strings and
  traceability (N-7); N-8 (docs/010 and plan as-built lines) written before the commit.

Reviewer's set-up S-1 (independent, round 1; security SF1 adds the walk rows and the later
return's own reversal; built as `test_a_return_after_the_other_lease_s_confirm_keeps_its_money`):
1. `found = confirm_case(url, monkeypatch, (300,))`; `later = return_only(first, found["refund"], 300)`;
   the Credit holds 300.
2. `counted` from both Settlements `{X1: (300,300,300,0), X3: (300,0,0,300)}`;
   `credit_left` X1 0, X3 300; the second Settlement's walk rows exactly `DRAW 300` and one `TAKE`
   of X1's 300.
3. A held-value Refund naming X1 refused (`55000`, nothing left), COUNTS unchanged; X3's source
   has no part and no companion.
4. X1's source lists the confirm's application (part 300 of 300), nothing to put back, one
   companion; X1's reversal confirmed: the application reversed through the companion; COUNTS
   +2, +2; the line owes 300, the Credit 300, the Refund's net 1,700; X3 still (300,0,0,300).
5. X3's reversal confirmed with no companion: the line 300, the Credit 0, the Refund's net 2,000;
   reconciled.

### Part B1 — the owner's note on the two 10e-3d-2d-2b-2 limits (independent reviewer)

The 2b-2 record showed no reviewer's confirmation that either test could not be built (round 1
point 3 found no real path for (i); round 3 named a route by hand for (ii)). The independent
reviewer found a set-up by hand for both; both are added (owner note: "If a set-up is found, add
the test in 2d-2c").

Set-up (i), a charge-back on no Lease of another Settlement's Refund (built as
`test_a_charge_back_on_no_lease_of_another_lease_s_refund_goes_through_its_companion`); the
reviewer agrees there is no real path:
1. `found = refunding_case(url, monkeypatch, 1_500)`; before the block, the second Lease's id and
   the user triggers of `app.lease_signers`.
2. One owner connection, always rolled back, no other connection inside: `ALTER TABLE
   app.lease_signers DISABLE TRIGGER USER`; `UPDATE app.lease_signers SET signed_at=NULL WHERE
   lease_id=<second Lease> AND customer_id=<first Customer>` (1 row).
3. X0's source on that connection: `recoveries == [{**expected_recovery(found, 1_500),
   "lease_id": None, "charge": "NO_LEASE", "closed_final_settlement_id": None}]`, companions
   `[second Settlement]`; `app.assert_settlement_return_reversal_allowed(source)` passes.
4. Record the draft by SQL on that connection (`app.record_settlement_return_reversal_draft`,
   the derived draft id, the command's `return_reversal()` input, `final_settlements.prepare`; a
   draft recorded before the block would be stale), then confirm it by SQL (`financial.approve`).
5. `result["recoveries"] == []`; the companion's one recovery `(other_refund, None, 1_500)`; the
   recovery, its charge and its Invoice linked to the companion header; the Invoice has no Lease
   and bills the first Customer; the other Refund's net 0, X0's Refund's net 2,000, the Credit 0;
   reconciled. After the rollback the triggers are as before and there is no recovery row.

Set-up (ii), the 2b-2 security round 2 check N-2 on its own (built as
`test_the_return_reversal_s_own_branch_alone_refuses_another_settlement_s_refund`):
1. `found = refunding_case(url, monkeypatch, 600)`; X0's reversal recorded through the service;
   before the block, the user triggers of `app.settlement_correction_effects` and
   `app.final_settlements` and the second Settlement's four closure fields.
2. One owner connection, always rolled back: the confirm by SQL; the companion's charge-back row
   allowed `(True, 600)`.
3. `ALTER TABLE app.final_settlements DISABLE TRIGGER USER`; `UPDATE app.final_settlements SET
   closed_at=NULL, closed_by=NULL, source_snapshot=NULL, closing_balance_due_usd_cents=NULL WHERE
   id=<second Settlement>` (the closure shape check needs all four NULL together); still
   `(True, 600)`.
4. Move the effect row to the return reversal as the committed rolled-back test does: `(False,
   600)`. With the second Settlement open, the closed-Settlement link rule cannot refuse it and
   the companion branch no longer matches; every other condition of the reversal's own branch
   holds (the reversal still lists the Refund), so only N-2 refuses.
5. After the rollback both tables' triggers and the closure are as before, and there is no
   recovery row.
Optional step not taken: in the same transaction, replace the function without the N-2 clause
and expect `(True, 600)`.

### Part B2 — the owner's note: the tests 2b-2 changed, compared with their earlier version (`git diff 88cb214 c6941db`)

- `test_settlement_return_reversal_companion_migration.py::test_a_take_whose_correction_also_refunded_from_the_credit_is_undone_through_the_companion`:
  X0's source went from one `CHANGED_APPLICATION` part of 1,500 to no open part with exact parts
  (`REFUND` 200, the step 300, 1,000 of the rest; sum 1,500; the reversed 1,500 payment not
  listed); the refused attempt (recording X0's reversal gave `("55000", CHANGED)` with COUNTS
  unchanged) was removed. A refused case became allowed, covered by owner answer 4 of 2026-10-16
  and answers (a) to Q-2026-10-13-103 point 3 and Q-2026-10-13-107; nothing else got weaker (the
  parts are asserted to the cent; the counts before X1's reversal are still taken). The removed
  checks stay covered: set-up S-B of the 2b-2 module confirms X0's reversal on the same set-up
  and a later `CHANGED` refusal that writes nothing; 2c's put-back test and the 2a module have
  `CHANGED` refusals with counts unchanged.
- `test_settlement_return_reversal_changed_payment_migration.py::test_the_follow_function_fails_closed`:
  the case with another (random) Settlement went from "stops open" to "followed into the 800
  Refund", exactly the approved `REFUND` allow-list; the other cases are unchanged. Note: no
  direct case is left for the allow-list's other side (a Deposit, or a variant other than
  `REFUND` and the companion, of another Settlement); the real path covers the companion
  variant. Optional; for the slice 12 list.
- The `OTHER_SETTLEMENT` message constant: text only; every test that uses it still asserts the
  refusal.
- The revision strings: 27 lines out and 27 in, revision strings only.

## Review round 2 (fresh read-only subagents, during P2; told to write no file and run no test, script or database command)

Independent: 0 blockers, 3 should-fix (all tests), 4 notes. Security: 0 blockers, 1 should-fix
(test, the same as independent SF-2), 4 notes. Both confirmed the round 1 fixes; the security
reviewer confirmed the docs/004 lock-order sentence (every correction that writes a Credit record
calls `app.lock_settlement_correction_plan`, which locks the Credit rows, before
`app.begin_settlement_correction` stamps its header; `app.post_final_settlement_credit_application`
locks the Credit before it sets each application's time). The independent reviewer rebuilt
`app.refund_recovery_allowed` from migrations 118, 120, 125, 126 and 140 and confirmed that test
(ii)'s last `(False, 600)` is refused by N-2 alone, and that test (i)'s state is reachable only by
hand (`app.guard_lease_signer` refuses clearing `signed_at`).

Fixed under the round-3 rule (no blocker; every should-fix a test or a text change):
- Independent SF-1 (test): the time-order test showed the outcome but not the order (walkers take
  the returns oldest first, so a confirm walker placed after X3 would also take X1's money). Added:
  the confirm's take of X1 comes before X3's entry in the walk.
- Independent SF-2, security SF-1 (test): test (i) built its expected recovery inside the
  rolled-back block through a helper that opens a connection of its own, against the block's
  comment; it is now built before the block.
- Independent SF-3, security N-1 (test): test (i) never ran the checks deferred to the commit;
  `SET CONSTRAINTS ALL IMMEDIATE` now runs after the confirm, inside the block.
- Independent N-4, security N-4 (tests, taken): both hand-built tests also check after the
  rollback that COUNTS is unchanged, and test (i) that the Signer's `signed_at` is restored.
- Independent N-2 (text): test 1's docstring and traceability note said "a confirm before every
  return"; now "a confirm of a Credit with no return's money left" (its Credit has no return).
- Security N-2 (text): docs/004 and docs/010 gave "each Lease's own confirm before its
  corrections" as an example of a confirm that is not a walker; since migration 137 another
  Lease's return into the same Credit can come before it; now "a confirm before every return into
  that Credit".
- Independent N-3 (text): the docs/004 paragraph re-wrapped at 100.

Notes kept: independent N-1 optional (replace the function without the N-2 clause in test (ii)
and expect `(True, 600)`); security N-3 (a companion takes the Credit lock through its return
reversal's call; companions are not walkers); security N-4 (the rolled-back tests leave only
sequence gaps and, in test (ii), the pending draft recorded before the block, as the committed
tests do).

## Review round 3 (fresh read-only subagents, during P3; told to write no file and run no test, script or database command)

Independent: clean (0 blockers, 0 should-fix, 3 notes). Security: clean (0 blockers, 0
should-fix, 3 notes). Both confirmed every round 2 fix: the order assertion proves the confirm's
walker comes first (it would fail otherwise); no second connection inside either rolled-back
block; `SET CONSTRAINTS ALL IMMEDIATE` runs the deferred checks of test (i)'s confirm; the checks
after the rollback; the text fixes. The independent reviewer confirmed again from migrations
118, 125, 126 and 140 that test (ii)'s last refusal comes from N-2 alone, and that each test
would fail without its patch (walk, placed, follow, the money-left rule, the order).

Taken (text only):
- Independent note 1: this record's run table now shows U3, M4 and P3, and docs/010 has the
  review-rounds entry for 2d-2c.
- Independent note 2: the docs/004 paragraph re-wrapped (cosmetic).

Notes kept (optional; not taken, so that no test file changes after P3):
- Security 1: the comment in test (i)'s block says a second connection "would wait on the
  ALTER's lock"; that holds for a writer (the ALTER's SHARE ROW EXCLUSIVE lock does not block a
  plain read, which would see the old committed rows). The rule itself is right.
- Security 2: test (i)'s check that `signed_at` is restored could also assert that it was not
  NULL before the block.
- Security 3 and independent 3: test (ii) runs no `SET CONSTRAINTS ALL IMMEDIATE` (it asserts the
  recovery check's result; the committed 2b-2 test confirms the same reversal with a real
  commit), and could replace the function without the N-2 clause in the same transaction and
  expect `(True, 600)`.
