# V1-056 sub-slice 8a-1 — Final Settlement record and Deposit application record

Status: STOPPED after review round 1 (Q-2026-10-05-22). Not committed; all files are in the working tree.

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

## Planned round-1 fixes (after the owner answer)

Independent S1 to S5 as described; notes taken: clear refusal for an unknown target, the human-actor check in the writer, TRUNCATE/REFERENCES/TRIGGER and PUBLIC in the least-privilege test, a test with the hand-back basis or Invoice resource and the chronology. Then backend unit and full PostgreSQL once each, and review round 2.
