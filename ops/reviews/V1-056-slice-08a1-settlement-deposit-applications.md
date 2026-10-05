# V1-056 sub-slice 8a-1 — Final Settlement record and Deposit application record

Status: round 3 (independent and security) has no blocker and no should-fix, so 8a-1 is committed under the standing round-3 rule. The owner answered Q-2026-10-05-22 (2026-10-05): security S1 of round 1 is closed in sub-slice 8r.

Built: migration `20261021_86_final_settlement_deposit_applications.py`, `backend/src/property_rental/final_settlement.py`, the termination readiness field `deposit_applied_usd_cents`, new tests `test_final_settlement.py`, `test_final_settlement_migration.py`, `tests/pre_settlement_test_support.py`, narrowed historical tests and notes (docs/010, docs/004, ops/V1_056_PLAN.md), traceability entries.

## Runs

- U1 backend unit: 1 failed (traceability manifest lacked the new tests; correction 1 for that cause).
- P1 targeted PostgreSQL (new tests, termination readiness, deposit API): errors at setup, migration SQL defect (record variable in a multi-item INTO; correction 1); a latent trigger defect fixed with it (a guard read `NEW.invoice_id` on a table without that column).
- P2 targeted: 3 failed, 3 causes, correction 1 each: test arithmetic (Pet Deposit used up), a historical test asserting `app.final_settlements` absent, the forward59 test reading revision 59 with the current reader.
- P3 targeted: 37 passed.
- U2 backend unit: 3422 passed.
- P4 full PostgreSQL: 1765 passed, 7 failed; same cause as the P2 absence test (historical tests assume the Settlement tables do not exist; correction 2 of 2 for that cause; the pre-run search had missed them).
- P5 full PostgreSQL: 1772 passed.

## Round 1 — security review (fresh reviewer, read-only)

No blocker. Deny by default confirmed: both new tables and all 13 new functions revoked from PUBLIC and the application roles; only `app.start_final_settlement` granted, to `prm_financial`; the service checks `final_settlements.prepare` before any connection; fixed search_path, no dynamic SQL; patches keep owner, privileges and attributes; audit keys classified.

- Should-fix S1 (existing path, not introduced by 8a-1; needs the owner): a Deposit receipt reversal (`deposits.correct`, one call, `app.reverse_deposit_receipt_v2`) returns the receipt's value to its Payment, which stays RECEIVED; a one-call allocation (`payments.allocate`) or Credit recognition then lets that value pay the payer's Invoices. Deposit money then pays debt without a draft or a `financial.approve` holder, without the kept-Deposit rule and outside the DL-032 order; during an active Lease it pays ordinary Invoices before Final Settlement (BR-SETTLE-010). It also works on a kept Security Deposit while its Lease forfeiture draft is pending, because the receipt-reversal trigger checks only Reservation drafts (`payload->>'reservation_id'`). Q-2026-10-05-22.
- Notes: the Customer Ledger must count applications before any writer exists (8a-2); `app.post_deposit_application` trusts the `financial.approve` reference it writes (8e must check the approver; keep it ungranted; consider the human-actor check); the closure transition is validated only by shape (8e); lock order for 8e (lock all targets first in a fixed order); a Settlement-level serialization guard would harden the stage order under REPEATABLE READ; a later superseding inspection can change the pet basis of a recorded application; any future application reversal table must change every reader together; the kept rule is checked at insert time.

## Round 1 — independent review (fresh reviewer, read-only)

No blocker.

- S1: the Payment reversal context (migration 46, result view) and the financial action context (migration 47) compute a Late-payment Charge remaining balance from Payments and Credit only; a Deposit application makes them overstate it. Fix: use `app.late_payment_charge_financial_position`.
- S2: the new 55000 refusal reaches Late-payment Charge correction users as "persistence unavailable" (`late_payment.py` maps unknown codes so). Fix: a mapped code or conflict mapping, with a service-level test.
- S3: docs/004 DB-DEP-005 says the trigger verifies all prior-stage prerequisites; it checks only stage order and type. Fix the text (the draft and confirm enforce the strict order, sub-slices 8c and 8e) or the trigger.
- S4: kept-Deposit tests cover BR-DEP-023 and BR-DEP-022 only; add BR-LEASE-005, BR-LEASE-025, BR-LEASE-028, the Pet Deposit staying applicable at those terminations, and the active-disposition branch.
- S5: no test of owner answer 5 (a Deposit paying an Invoice of another signed Signer).
- Notes: ledger and Deposit history readers (8a-2); the Late-payment Charge resource needs `deposit_total` (11e, docs/005); the Payment that funded a Deposit becomes permanently unsupported in both Payment contexts after Settlement; an unknown target gives 23502 instead of a clear refusal; the closure needs a validator (8e); test details (closed-settlement test uses random ids; least-privilege test could add TRUNCATE/REFERENCES/TRIGGER and PUBLIC; no test of the hand-back basis, Invoice resource or chronology with an application; no concurrent-start test); the VOID/Adjust 55000 maps to `InvoiceInvalidError` (existing mapping); the docs/004 as-built sentence overstates "every Late-payment Charge balance" until S1 is fixed.

## Planned round-1 fixes (after the owner answer; done, see below)

Independent S1 to S5 as described; notes taken: clear refusal for an unknown target, the human-actor check in the writer, TRUNCATE/REFERENCES/TRIGGER and PUBLIC in the least-privilege test, a test with the hand-back basis or Invoice resource and the chronology. Then backend unit and full PostgreSQL once each, and review round 2.

## Round-1 fixes (done after the owner answer to Q-2026-10-05-22)

- Independent S1: migration 86 patches `app.payment_reversal_context_page` and `app.financial_action_context_page` in place; the Late-payment Charge remaining balance subtracts `active_applications_usd_cents` from `app.late_payment_charge_financial_position`. Test `test_payment_contexts_count_a_deposit_application_on_a_charge`.
- Independent S2: the Late-payment Charge correction refusal raises P4603, which the service maps to `LatePaymentConflictError`. Test `test_a_charge_correction_after_a_deposit_application_is_a_conflict`.
- Independent S3: docs/004 DB-DEP-005 says what the trigger checks; the prior-stage prerequisites belong to 8c and 8e.
- Independent S4: `test_violation_default_and_unpaid_initial_grounds_keep_only_the_security_deposit` (BR-LEASE-025, BR-LEASE-028, BR-LEASE-005; Pet Deposit stays applicable). The active-disposition branch is answered in docs/010 (no current writer reaches it).
- Independent S5: `test_a_deposit_pays_an_invoice_of_another_signer`.
- Notes taken: unknown target (P0002) and target kind (22023), human approver (42501), least privilege for all seven table privileges and PUBLIC, Invoice resource and chronology assertions, closed-Settlement refusal with a real Deposit and line.

## Runs after the round-1 fixes

Pre-run search (read-only, all backend tests): the fixes add no table, column or function signature; tests that compare function bodies across revisions are bounded to their own revisions; no test compares the head bodies of the two patched context functions; the only test expecting the Late-payment correction refusal code is in `test_final_settlement_migration.py` (updated).

- U3 backend unit: 3422 passed, 1621 skipped (`V1-056-slice-08a1-unit-test-run-3.txt`).
- P6 full PostgreSQL: 1776 passed (`V1-056-slice-08a1-full-test-run-6.txt`).

## Round 2 — security review (fresh reviewer, read-only)

No blocker, no should-fix. Deny by default, in-place patches keep owner and privileges, no Staff path to Deposit money or closure, no injection, no data leaks, P4603 reuse safe (replay lookup first, only writer). Notes: (1) Late-payment readers see `deposit_id` in the application summary (runtime grant, no Property check, UUIDs only), moved to 8a-2 or 11e; (2) human-approver check only in the writer, taken (also in the trigger); (3) a Charge correction below the applied total gets the P4608 message "Active applications must be reversed explicitly", moved to slice 10; (4) 42501 also means a missing grant, documented in docs/010 (fails closed); (5) the move-out snapshot is fixed at start, moved to 8e.

## Round 2 — independent review (fresh reviewer, read-only)

No blocker; two should-fix, both fixed:

- The closure identity rule was untested: the closure test now sends full closures that also change `started_at`, the termination date snapshot or the move-out snapshot (23514), then the plain closure succeeds.
- The Deposit's own history reader (Deposit ledger read in `deposit_api.py`) was not named in any sub-slice: named in 8a-2 (plan split line and docs/010).

Notes: (1) the human-approver test used a random id, now also a real billing service identity, through the writer and through a direct insert; (2) docs/004 now says the Customer's choice for the remaining Pet Deposit is checked by 8c and 8e; (3) a Security Deposit whose forfeiture was reversed stays kept (owner question before 8c, plan); (4) traceability wordings corrected; (5) `app.invoice_adjustment_reversals` guard moved to 8e or slice 10.

## Runs before round 3 (standing rule)

Pre-run search (read-only, all backend tests): the round-2 fixes add no table, column or function signature; the only other tests that write `app.deposit_applications` are the three revision-85 contract tests, which run without migration 86.

- U4 backend unit: 3422 passed, 1621 skipped (`V1-056-slice-08a1-unit-test-run-4.txt`).
- P7 full PostgreSQL: 1776 passed (`V1-056-slice-08a1-full-test-run-7.txt`).

## Round 3 — security review (fresh reviewer, read-only)

No blocker, no should-fix. Deny by default and in-place patches confirmed; no Staff write path; the human-approver check in the trigger is proven by the direct-insert test; P4603 cannot hide a committed request (replay lookup under the advisory lock runs first, only writer). Notes moved to plan slice 12: closure guard should check an active approver and bound `closed_at` (8e); an inactive approver maps to a conflict (8e mapping); `app.deposit_has_active_application` answers for any Deposit UUID (joins the 8a-2/11e reader item); replay test after a Deposit application.

## Round 3 — independent review (fresh reviewer, read-only)

No blocker, no should-fix. Rules, append-only, cents, capabilities, earlier behavior and the round-2 fixes confirmed (the closure test and the direct-insert test fail if their checks are removed). Notes moved to plan slice 12 (tests and traceability only): the stage-type rule tested in one direction; closure test covers three of seven identity columns; the "current inspection" clause untested; BR-SETTLE-010 missing from traceability. Side observation: in the BR-LEASE-005 case the 23514 may come from the target balance, but the kept rule itself is asserted directly and the BR-LEASE-025 case proves the trigger uses it.
