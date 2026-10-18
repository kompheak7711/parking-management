# V1-056 sub-slice 10e-2b-4e-2b-2a — a receipt correction gives back only a shared Deposit's shortfall — review record

Sub-slice: 10e-2b-4e-2b-2a (owner answer (a) to Q-2026-10-18-127, "the receipt correction does
the same"; owner answers (a) to Q-2026-10-18-134, newest first). Migration `20270103_160` (one new
internal function and exact-text patches of nine functions). Base commit: 2e20bf2. Built on
2026-10-18 in a fresh session. Not pushed. Split (implementer, under the owner's rule): sub-slice
10e-2b-4e-2b-2b (the end of option (d) in the receipt writer) follows.

## Built

- Migration `20270103_160_settlement_deposit_receipt_shared_deposit.py`: new internal
  `app.settlement_deposit_receipt_correction_shared(property, source)` (no grant); patches of the
  receipt correction's source, record check, targets check, recorder, write helper and overlay,
  and of the kept-part check, the shortfall recovery amount and the shared receipt reversal check
  (each relaxed branch bound to the `DEPOSIT_RECEIPT_CORRECTION` that links the record, confirmed
  in this transaction, whose stored source lists the Deposit).
- Tests: new module `test_settlement_deposit_receipt_shared_deposit_migration.py` (ten tests, two
  with two cases); 27 head-revision strings; the committed fixture `shared_security_case` gains an
  optional third Payment (default none; no committed caller changes).
- Docs: docs/004 (DB-DEP-007 note, DB-PAY-009 sentence), docs/010, plan (split, pre-code design,
  as-built line, slice 11 note of the owner answers, slice 12 known limits); traceability
  appended; the owner answers to the 10e-2b-4e-2b-1 report recorded (docs/010, questions).

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump (one `REDACTED` marker, a numeric limit in an unrelated input check), saved in `~/Development/prm-run-logs/v1-056-10e-2b-4e-2b-2-D1.txt` |
| M1 | passed |
| FF1/FC1/L1/Y1 | passed (long-line search first: two lines wrapped; formatter reformatted the new test file) |
| T1 | 115 passed |
| U1 | 3866 passed |
| M2 | passed |
| P1 | 2339 passed (two warnings: the deprecation warning and the known pydantic alias warning) |
| FF2/FC2/L2/Y2 | passed (after the round 1 fixes) |
| M3 | passed |
| T2 | 121 passed |
| U2 | FAILED: 1 failed, 3865 passed: `test_traceability.py::test_traceability_manifest_covers_executable_tests`, a new test name already used by the 4e-2a module (cause A, traceability, correction 1 of 2) |
| FF3/FC3/L3/Y3 | passed (after the rename) |
| U3 | 3866 passed (the passing rerun after U2) |
| M4 | passed |
| P2 | FAILED: 1 failed, 2344 passed: `test_deposit_receipt_record_migration.py::test_a_payment_confirmed_for_an_owed_invoice_is_not_a_deposit_receipt`, 55P03 `LockNotAvailable` on `app.invoices` (the known DL-067 failure, in a module this sub-slice does not change) |
| P2-rerun | 1 passed (the standing rerun-once rule; the passing rerun after P2) |
| FF4/FC4/L4/Y4 | passed (after the round 2 fixes) |
| M5 | passed |
| T3 | 123 passed |
| U4 | 3866 passed (before round 3) |
| P3 | 2347 passed (two warnings: the deprecation warning and the known pydantic alias warning; before round 3) |
| FF5/FC5/L5/Y5 | passed (after the Q-2026-10-18-136 message change; formatter changed nothing) |
| M6 | passed |
| T4 | 12 passed (the new module, which holds the only test constant of the message) |
| U5 | 3866 passed |
| P4 | 2347 passed (the same two warnings) |

Full outputs in `~/Development/prm-run-logs/v1-056-10e-2b-4e-2b-2a-*.txt`, one file per attempt.

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: no blocker, 2 should-fix, notes. Security: no blocker, 3 should-fix, 7 notes. Both
worked the two real-path tests to the cent and found every patch matching once and the one-Payment
path unchanged (source `||'{}'`, the same digest).

1. Independent should-fix 1 (fixed, fail closed; a design change confirmed needed and safe by both
   round 2 reviewers): a plan Deposit step equal to the kept application part (the same Deposit,
   stage, target and amount) recorded cleanly but was refused at every confirm (23514), because
   `app.validate_deposit_application` counts the kept part as that step. Now refused at record
   (55000, "A Deposit step of this plan repeats a Deposit application this correction writes
   again; split the step"). Set-up (the reviewer's): `shared_security_case(url, 4_000)`; the
   Settlement applies 12,100 and refunds 1,900; A's correction gives back 1,900 and 8,100 (kept
   4,000); a right 4,000 receipt with one 4,000 step on the line is refused; with 3,000 on the line
   and 1,000 on the placeholder line it passes (the line owes 5,100, the recovery charge 900, A has
   6,000 more available).
2. Both, should-fix (test): the new branch of `app.payment_return_shortfall_recovery_amount` was
   never needed by a test (the recoveries were whole nets). Set-up: `shared_security_case(url,
   20_000)`; the Settlement refunds 17,900; A's correction charges back 10,000 of it (net 7,900),
   reverses no application; with a right 8,000 receipt the plan pays 8,000 of the placeholder line
   (it owes 2,000). Without the branch the recovery insert check would require the whole 17,900.
3. Security should-fix 2 (tests): (a) inside a rolled-back confirm, a second kept part of 10,000
   and one of 9,999, each linked, are refused (23514, "must be a Deposit step of its correction,
   once"); (b) hand-built in a rolled-back owner transaction, the wrapper replaced so its recovery
   asks 10,001 or 9,999 of a 10,000 shortfall: refused by the recovery insert check and by the
   held-history check at the receipt reversal (23514 each); (c) a reversal of the other Payment's
   receipt linked to the correction (replaced in round 2, below).
4. Security should-fix 3 (defence in depth): the new branch of
   `app.payment_return_shared_receipt_reversal_allowed` also requires no active forfeiture of the
   Deposit, so the table keeps the owner's refusal (Q-2026-10-11-83 point 3 (a)).
5. Notes taken: a CASE guard on the plan steps in the recorder checks (security N1); a real-path
   test of a Deposit holding more than the receipt (security N6: a return-only correction of the
   whole 17,900 Settlement Refund; a right receipt refused, "would still hold other money"; without
   one the shortfall is 0 and the Deposit ends holding 7,900); docs/004 states each branch's
   binding exactly (independent). Not taken: the per-use record check and a post-write end check
   (security N2, the same as 4e-2b-1; slice 12); the unchanged decision capability and reversal
   actor checks (security N3, as the 157 and 158 helpers); the stale comment of
   `app.assert_payment_return_recoveries_allowed` (security N4; that function is not patched here;
   slice 12 text item); Payment B not locked (security N5, safe: any write on B's side locks the
   Deposit); the draft size (N7, fails closed).

## Review round 2 (fresh read-only subagents, during P2; same instructions)

Both: no blocker; every round 1 fix confirmed real and correct, and the equal-step refusal
confirmed needed and safe (it refuses exactly the plans that could never confirm; at most one kept
part exists). Independent: 2 should-fix, 6 notes. Security: 2 should-fix, 4 notes. Fixed under the
round-3 rule (tests and a fail-closed refusal):

1. Independent should-fix 1 (fail closed): a plan Customer Credit step beside a kept application
   part recorded cleanly but was refused at every confirm by
   `app.assert_settlement_correction_credit_application` (55000, "Customer Credit is applied
   before the correction's Deposit applications and Refunds"), because the kept part is linked
   before the plan runs, while the plan check requires the Customer's available Credit first. Now
   refused at record (55000, "A Customer Credit step cannot follow a Deposit application this
   correction writes again; refund or apply the Customer's Credit first, or correct the receipt
   without new receipts"; the hint as worded by owner answer (a) to Q-2026-10-18-136, after round
   3), a fifth known limit; staff first refund or apply the Customer's Credit, or correct the
   receipt without new receipts. Set-up
   (the reviewer's): `shared_security_case(url)`, `new_credit(url, case, 1_000)`, a right 8,000
   receipt with steps Credit 1,000 on the line, Security 1,100 on the line and 6,900 on the
   placeholder: refused, nothing written.
2. Both, should-fix (test): the round 1 test of a reversal of B's receipt passed without the
   receipt binding, because A's receipt was already reversed and no other Payment's receipt stayed
   active. Set-up (both reviewers): three Payments (`shared_security_case(url, 10_000, 5_000)`; the
   Settlement refunds 12,900); inside the rolled-back confirm of A's correction the check passes for
   A's reversal and the linked reversal of B's receipt is refused (55000) while C's receipt is
   active; the round 1 version is removed.
3. Security should-fix 2 (test): the no-active-forfeiture clause, in the same rolled-back
   transaction: an active forfeiture of the Deposit inserted by hand with the table's user triggers
   switched off (and on again before the check) makes the check fail for A's reversal.
4. Notes taken: the equal-step refusal compares amounts as text, exactly as the Deposit application
   check does (both reviewers; no 22P02 on a malformed amount); the docs/004 DB-PAY-009 sentence
   names the receipt correction (independent N5); this record, the plan's as-built line and the
   slice 12 items (independent N4). Answered: a second active receipt of one Payment in one Deposit
   is refused by the receipt table itself (owner rule 1 of Q-2026-10-12-87, 23505), so independent
   N2 cannot arise; the conditions reachable only through a digest mismatch stay untested
   (independent N3, security N3; defence in depth); a `FORFEIT` right receipt beside an active kept
   part is the 10e-2c state (independent N6; slice 12 mention); the one-sided table bound (security
   N2; slice 12).

## Review round 3 (fresh read-only subagents, during P3; same instructions)

Security: clean (no blocker, no should-fix; three notes, no action). It confirmed every round 1
and round 2 fix, that the three-Payment test fails without the receipt binding and the hand-built
forfeiture test without the forfeiture clause, and that the trigger switch and the replaced
function stay inside rolled-back transactions (nothing can leak into the shared test database).

Independent: no blocker; one should-fix, text only, but in the migration: the staff hint of the
Customer Credit refusal ("apply the Credit to the open debt first") cannot be followed in the
case its own test builds, because the plan check counts the debt this correction reopens; before
the correction nothing on the Lease may be owed for the Credit to pay. Suggested wording: refund
or apply the Customer's Credit first, or correct the receipt without new receipts. The refusal
itself is exactly right. The same phrase is in the test constant, docs/004, docs/010, the plan's
slice 12 item and this record. Note N1: P3 is now in the run table (passed).

STOPPED after review round 3 (2026-10-18): the round-3 text rule of 2026-10-16 covers text fixes
only with no code, migration or fixture change, and this message is part of the migration. NOT
committed: every file of this sub-slice stays in the working tree. Asked as Q-2026-10-18-136
(recommendation (a), a one-time exception).

## Owner answer and commit (2026-10-18, fresh session)

Q-2026-10-18-136, option (a): the hint now reads "refund or apply the Customer's Credit first, or
correct the receipt without new receipts" in the migration, the test constant `CREDIT_AFTER_KEPT`,
docs/004, docs/010, the plan's slice 12 item and this record; the condition and the error code
(55000) are unchanged. FF5/FC5/L5/Y5, M6, T4, U5 and P4 passed (run table); committed without a
round 4. New standing run rule "Round 3 message fixes" (ops/V1_055_RUN_RULES.md). The split into
2a and 2b and the five fail-closed refusals are accepted as known limits on the slice 12 list.
