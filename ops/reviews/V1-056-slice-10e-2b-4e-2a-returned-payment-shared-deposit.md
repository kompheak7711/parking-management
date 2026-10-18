# V1-056 sub-slice 10e-2b-4e-2a — a returned-Payment correction gives back only a shared Deposit's shortfall — review record

Sub-slice: 10e-2b-4e-2a (owner answer (a) to Q-2026-10-18-127; owner answers (a) to
Q-2026-10-18-134 points 1 and 2, newest first). Migration `20270101_158` (three new internal
functions, exact-text patches). Base commit: 1542fc0. Built on 2026-10-18 in a fresh session. Not
pushed. Sub-slice 10e-2b-4e-2b (the receipt correction of a shared Deposit and the end of option
(d)) follows.

## Built

- Migration `20270101_158_settlement_returned_payment_shared_deposit.py`: new internal
  `app.settlement_returned_payment_shared`, `app.write_settlement_shared_deposit_undo`,
  `app.settlement_shared_deposit_kept_application_allowed` (no grant); patches of
  `app.settlement_returned_payment_source`, `app.assert_settlement_returned_payment_allowed`,
  `app.post_settlement_returned_payment`, `app.settlement_returned_payment_result`,
  `app.assert_payment_return_recoveries_allowed`, `app.write_payment_return_recoveries`,
  `app.payment_return_shortfall_recovery_amount`,
  `app.payment_return_shared_receipt_reversal_allowed`, `app.validate_deposit_receipt_reversal`,
  `app.validate_deposit_application`, `app.write_correction_deposit_forfeiture` and
  `app.payment_return_shared_deposit_recoveries`.
- Tests: new module `test_settlement_returned_payment_shared_deposit_migration.py` (four tests);
  three committed tests changed and renamed (docs/010); 27 head-revision strings.
- Docs: docs/004 (DB-DEP-007 and DB-SETTLE-005 notes), docs/010, plan (pre-code design, as-built
  line, slice 12 items), Q-2026-10-18-135; the owner's answers to Q-2026-10-18-134 and the 4e-1
  report recorded (docs/010, questions, run rules); traceability appended.

## Runs

| Run | Result |
|---|---|
| D1, D2, D3 | catalog dumps (no `REDACTED` markers), saved in `~/Development/prm-run-logs/v1-056-10e-2b-4e-2-D*.txt` |
| M1 | passed |
| FF1/FC1/L1/Y1 | passed (long-line search and import order first: two lines fixed, one import moved; formatter changed one file) |
| T1 | 82 passed |
| U1 | 1 failed, 3865 passed: `test_traceability_manifest_covers_executable_tests` (traceability not yet updated for the new and renamed tests; cause A, 1 of 2) |
| U2 | 3866 passed (the passing run after U1) |
| M2 | passed |
| P1 | 2327 passed |
| FF2/FC2/L2/Y2 | passed (after the round 1 fixes; formatter no change) |
| M3 | passed |
| T2 | 1 failed, 83 passed: the new owner-example test's table refusal got 23503 (the link's foreign key, set immediate by the confirm) instead of 23514 (cause B: test set-up, 1 of 2) |
| FC3/L3 | passed |
| T3 | 4 passed (the passing run after T2) |
| U3 | 3866 passed |
| M4 | passed |
| P2 | 2329 passed (two warnings: the deprecation warning and the known pydantic alias warning of the slice 12 list) |
| FF3/FC4/L4/Y3 | passed (after the round 2 fixes; formatter no change) |
| M5 | passed |
| T4 | 45 passed |
| U4 | 3866 passed (before round 3) |
| P3 | 2329 passed (the full run after the last code and test change; the same two warnings) |
| U5 | 3866 passed (after the round 3 text fixes: traceability notes; no code change) |

Full outputs in `~/Development/prm-run-logs/v1-056-10e-2b-4e-2a-*.txt`, one file per attempt
(the migration checks and the catalog dumps included).

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: no blocker, 1 should-fix, 8 notes. Security: 1 blocker, 3 should-fix, 4 notes.

1. Security B1 (fixed fail closed; new Q-2026-10-18-135): newest first can charge the Customer
   back pay-back money while the kept forfeiture keeps it, because the forfeiture table's
   pay-back limit is read before the bounced receipt is reversed. Fix (the reviewer's proposal,
   a design change for round 2 to confirm): the check refuses (55000) a plan that charges back or
   reverses a Refund or application of a Deposit with pay-back history while a forfeiture of it
   stays active; the confirm checks after its writes that a Deposit with an active forfeiture
   still holds its pay-back count. The reviewer's set-up, built as
   `test_a_kept_pet_deposit_with_pay_back_money_is_refused_until_the_owner_answers`: Pet Deposit
   from Payment A 5,000; a 4,000 Pet Refund-review Refund and its full verified return (count
   4,000); pet noncompliance termination; required total raised by 5,000 and Payment B's 5,000
   receipt (owner insert, as the pay-back fixtures seed receipts); the forfeiture draft takes 6,000;
   the Settlement refunds 4,000; A's correction is refused at record, nothing written (without the
   fix: the Customer charged 4,000 and 5,000 kept forfeited).
2. Security S1 (fixed): the shortfall-amount and shared-receipt-reversal helpers are bound to the
   correction that links the record (`IS NOT DISTINCT FROM`, so the `PAYMENT_RETURN` path is
   unchanged), and the receipt reversal to a correction whose plan lists the Deposit. No real path
   found by the reviewer (defence in depth).
3. Security S2 and independent note 3 (fixed): the kept forfeiture needs its listed forfeiture
   reversed by a reversal linked to this correction.
4. Security S3 (fixed, tests): inside a rolled-back confirm, a second kept part (10,000) and one of
   9,999, each linked, are refused by the table (23514, "must be a Deposit step of its correction,
   once"). The reviewer's second case (a 7,901 recovery inside the correction) is not tested: the
   partial-Refund test below proves only that a share is accepted inside the correction (it
   fails without the shortfall-amount patch, 23514); the refusal above the shortfall is the same
   `LEAST` code that the 4e-1 hand-built test refuses (corrected in review round 2).
5. Independent should-fix 1 (fixed, the reviewer's set-up): B's receipt 20,000, the Settlement
   refunds 17,900; plan `[REFUND 17,900 / 10,000 / kept 7,900]`; 10,000 charged back, net 7,900,
   no application reversed, the line owes 0, the Deposit holds 0
   (`test_a_refund_larger_than_the_shortfall_is_charged_back_only_in_part`).
6. Notes taken: amounts compared as integers (independent 4); negative cases of the
   kept-application check (another stage, line, Deposit; independent 2); the forfeiture reversal
   asserted exactly (independent 7); the planner's signature and `plain` (independent 5, security
   N1) and the stale drafts at the migration (independent 9, security N2) in the plan and
   docs/010; the reading of newest first for a Refund paid before closure in docs/010
   (independent 6). Not taken: point 2 after closure (optional, the same window; independent 8),
   a post-write end-state check beyond B1 (security N3: the plan is digest-checked and the held
   history is checked by the table).

## Review round 2 (fresh read-only subagents, during P2; same instructions)

Both: no blocker; every round 1 fix confirmed; both confirm the B1 design change needed and safe
(it only refuses, in the Q-2026-10-18-135 family; before this sub-slice every shared Deposit was
refused). Fixed under the round-3 rule (tests, text and a fail-closed refusal):

- Security should-fix 1 and note 1 (the reviewer's set-up): after closure a return-only
  correction (verified full return of the 4,000 Settlement Refund, no new Refund) brings the
  pay-back money back into the Pet Deposit; A's plan then gives back only 1,000 of the forfeiture
  (no Refund or application use), which only the check after the writes refused. The record check
  now also refuses when a forfeiture stays active and the pay-back count (with payouts) is above
  the held value the plan ends with (`GREATEST(held - receipt, 0)`); the B1 test adds this case
  (refused at record, nothing written, the Deposit holds 4,000). The check after the writes stays
  as defence only, untested (independent note 2: no plan reaches it past the record check).
- Independent should-fix 1 (text): docs/004 DB-REFUND-002 gains a 10e-2b-4e-2a paragraph (two
  recipients, the share inside the correction), and the DB-DEP-007 note names the unresolved-Refund
  skip too.
- Independent should-fix 2 (text): Q-2026-10-18-135 states the real order (B's receipt after the
  return and before the termination); the B1 test keeps its owner-inserted receipt after the
  termination and its docstring says so (the checks read no event times).
- Notes taken: the record's S3 wording above (independent note 3, security note 2); the plan's
  known limit says "pay-back history, also when already paid out" (independent note 1); a comment
  that only the two planners set `shortfall_share` (security note 3); the type check run again
  after the last test edit (independent note 4). Not taken: an exact share from the stored plan in
  the recovery insert check (security note 2; the planner and the digest decide; slice 12 list
  with the 4e-1 note).

## Review round 3 (fresh read-only subagents, during P3; same instructions)

Security: clean (no blocker, no should-fix; one text note). Independent: no code, migration or
test defect; two text should-fix and three notes. Fixed under the round-3 text rule of 2026-10-16,
no round 4 (no code, migration, test or fixture change): docs/010 and the plan's as-built line
name the round 2 change and docs/004 DB-REFUND-002; the docs/004 DB-DEP-007 note names both
branches of the Q-2026-10-18-135 refusal (and the return reversal outside 4e-2b's scope); Q-135's
"What happens now" gives the forfeiture-only example; this table lists the later runs; the last
traceability entry's note names the round 2 case. Both reviewers confirmed the record check and
the check after the writes refuse the same set (no plan passes the first and fails the second).
