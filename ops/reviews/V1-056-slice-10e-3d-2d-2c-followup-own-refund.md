# V1-056 follow-up test of sub-slice 10e-3d-2d-2c — a confirm application that a `REFUND` correction of its own Lease later changed — review record

Follow-up of sub-slice 10e-3d-2d-2c (owner instruction of 2026-10-16, step 3 of the session
brief). Base commit: 11fc6f1. Tests and records only: no code, migration or fixture change.
Built on 2026-10-16. Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-014, DL-032; DB-SETTLE-005, DB-REFUND-002.
Question: Q-2026-10-16-115.

## The owner's instruction and the result

The instruction: confirm that a return reversal that meets a Final Settlement confirm's Credit
application later changed by a `REFUND` correction of its own Lease is refused and writes
nothing; try the whole-line refund path the 2d-2c round 1 independent reviewer named; if it
reaches the case, add a test that shows the refusal; if not, write that in the slice 12 item.

Result: the whole-line path reaches the case, and the reversal is not refused. Read at head
`20261215_141` (catalog dump D1 of `app.settlement_returned_value_follow` and
`app.settlement_returned_value_placed`; no `REDACTED` marker): the follow function takes an
application with no correction link and a `final_settlement_id` as written by that Final
Settlement (2d-2c), and reads the correction that reversed it through the 2b-2 allow-list (a
`REFUND` correction of another Final Settlement that changed a Credit payment). The money is
then followed into that correction's Refunds and payments, as for a take by another Lease's
correction (owner answer 4 of 2026-10-16; answers (a) to Q-2026-10-13-103 point 3 and
Q-2026-10-13-107). Both round 1 reviewers confirmed this reading from the migrations. So no
refusal test can be written; the new test shows the followed result, and Q-2026-10-16-115 asks
the owner to confirm it (recommendation (a): keep it; (b), a refusal, would be a tightening and
would change the new test).

Before the test, two scratch runs of a probe file that was never committed (deleted before T1):
E1 stopped at the probe's own helper mistake (it called the `pytest.raises` helper `cause` on a
plain exception); E2 showed the result above.

## Built

- Test: `test_settlement_return_reversal_settlement_confirm_migration.py::test_a_confirm_application_its_own_lease_s_refund_correction_changed_is_followed`
  (and the `charge_open` import). Set-up on the real path: `confirm_case(url, monkeypatch,
  (300,))`; then a `REFUND` correction Q of the second Lease's whole 12,500 damage line
  (300 + 400 + 10,000 + 1,800) with the steps `settlement_refund(second, "security", 10_000)`
  and `settlement_refund(second, "pet", 1_800)` (a draft without them is refused, 55000, "Every
  remaining Deposit balance must be applied or refunded"). It checks: Q reversed the confirm's
  300 application and refunded 300 from the returned Credit; the walk keeps the confirm as the
  taker of X1's 300 and has no row for Q; X1 has nothing left; X1's source has one part, Q's
  300 Refund, no open part, no payment to undo, the second Settlement as its one companion and
  one charge-back on the second Lease; the reversal's companion charges the 300 back to the
  Customer on the second Lease (linked three times to the companion, named in its audit event,
  the companion plan empty), and outside the confirming transaction the recovery check allows
  the row no more; drafts +2, corrections +2, nothing else; the line owes 0, the Credit 0, Q's
  Refund's net 0, X1's Refund's net 2,000; the ledger reconciles.
- Committed tests changed: none.
- Traceability: one entry appended.
- Records: docs/010 (one entry), the plan (the slice 12 item marked done; the 2d-2c as-built
  line points to it), Q-2026-10-16-115, this record.

Read-only search for affected tests: no product code changed; the new test sits in the last
module of `scripts/database-test.sh`, and the module's later tests compare counts before and
after their own steps only.

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump (follow, placed) |
| E1 | scratch probe stopped by its own helper mistake (not a product or committed test failure) |
| E2 | scratch probe rerun: the case is followed |
| F1/L1/Y1 | passed (the formatter ran first and changed the new test) |
| T1 | 7 passed (the module) |
| U1 | 3804 passed |
| M1 | passed (`20261215_141` head) |
| P1 | 2201 passed (warnings: the known Starlette deprecation and one Pydantic alias warning of the unchanged Credit Refund API tests) |
| F2 | passed (after the round 1 notes; the formatter ran first) |
| L2 | 1 failed: a docstring line of 113 characters (long-line cause A, 1 of 2). The long-line search found it, but the lint ran in the same batch before the fix |
| L3 | passed (after the line fix) |
| Y2 | passed |
| T2 | 7 passed (the module, after the last test change) |
| U2 | 3804 passed |
| M2 | passed |
| P2 | 2201 passed (warnings: the known Starlette deprecation and one Pydantic alias warning of the unchanged Credit Refund API tests) |

After P2 only text changed (this record, docs/010, the plan, ops/NOW.md).

## Review round 1 (fresh read-only subagents, during P1; told to write no file and run no test, script or database command)

Independent: clean (0 blockers, 0 should-fix). Security: 0 blockers, 1 should-fix.

- Security should-fix (text): this record was named in docs/010 but did not exist; written after
  P2 (no file is edited during a run).
- Independent notes, taken: the texts left out the second Lease's own 400 Credit Refund (test
  docstring, docs/010, the Q-115 example; fixed); DL-032 added to the traceability entry; the
  2d-2c as-built line of the plan points to the done item; the Q-115 header no longer says
  "committed" before the commit; optional assertions taken (the companion's audit event, its
  empty plan, its header's Settlement, the recovery check after the commit, and the reviewer's
  walk set-up: the first Settlement's walk rows for the second Settlement and for Q are exactly
  `("DRAW", second Settlement, None, 300, 0, False)` and `("TAKE", second Settlement, X1, 300,
  0, True)`, then `credit_left(X1) == 0`).
- Independent reading confirmed: the follow fallback (141), the allow-list (140), the walk
  (Q's net draw 0, so the confirm stays the taker), the 139 placed rule does not apply (the
  taker is a Final Settlement id and the record a Credit application), and none of the
  downstream refusals fires.
- Security notes (for the owner and the slice 12 list): no money leaves; the debt goes to the
  person who received Q's Refund, on Q's Lease; the confirm needs a human `financial.approve`
  actor and the companion is confirmed in the same call by the same actor; the charge-back is
  allowed only inside the confirming transaction. The same mistaken 300 becomes a different debt
  with or without Q (the line owes again, or a recovery charge on the closed second Lease); the
  first Lease's approver alone creates that debt on the second Lease (as owner answer 4).
  Untested neighbours: Q refunds more from the Credit than the reversed application (a later
  return's money in the same Refund, a follow and a take on one Refund), a `REFUND` of part of
  the line, Q's Refund returned later. Optional defence in depth: the allow-list could also
  require `correction.final_settlement_id = v_credit.final_settlement_id` for a confirm
  application (today the companion checks tie the charge to `app.settlement_refund_owner`).
  Process: the owner expected a refusal; Q-115 lets the owner decide whether work goes on.

## Review round 2 (fresh read-only subagents, during P2; same limits)

Independent: clean (0 blockers, 0 should-fix, 4 notes). Security: clean (0 blockers, 0
should-fix, notes).

Notes kept (optional; not taken, so that no test file changes after P2):
- Independent 1: Q's other Refunds (400, 10,000, 1,800) are stated but not asserted.
- Independent 2: the walk filter's tuple has a trailing comma, so the formatter spreads it over
  several lines (style).
- Independent 3: docs/010 gets a rounds-and-runs line (taken, text).
- Independent 4 and security: the owner confirms whether work goes on while Q-115 is open
  (TAKEOVER section 6).
- Security: the new test does not assert who confirmed the companion (decision `CONFIRMED`,
  the approver, `financial.approve`); that is asserted in
  `test_settlement_return_reversal_companion_migration.py`.
