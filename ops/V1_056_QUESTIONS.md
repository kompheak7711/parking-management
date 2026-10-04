# V1-056 questions for the owner

## Q-2026-10-03-1 — Slice 2 stopped: findings remain after review round 2 (RESOLVED: owner chose Option A; slice 2 committed after round 3)

Slice 2 (financial.approve, final_settlements.prepare and the draft model, migration `20261012_77`) is built and its tests pass, but the second and last allowed review round still has findings. Under ops/V1_056_TAKEOVER.md sections 4 and 6 the work stopped. Nothing of slice 2 is committed; the files are in the working tree. Full record: ops/reviews/V1-056-slice-02-financial-drafts.md.

Remaining findings (no blockers):

1. Should-fix (test only): add tests that a repeated withdraw or reject after a decision with a wrong authorization reference is refused, and that a correct repeat replays.
2. Should-fix (test only): add tests that reject and withdraw refuse a blank, padded or missing reason, through the service and directly in the database, and write no decision.
3. Note (code): give `app.confirm_financial_draft_record` a draft-kind parameter and check it, so a later confirm command for one kind can never confirm a draft of another kind.
4. Note (code): add type checks in `FinancialDraftPage` and the withdraw capability argument so bad input gives FinancialDraftInvalidError.

Recommendation: allow me to make these four changes, run the slice 2 tests once, and get one more fresh review (a third round for this slice only). If that review has no should-fix findings, commit slice 2 and continue with slice 3.

Alternative: accept findings 3 and 4 as notes, make only the two test additions (1 and 2), and commit after the targeted run without a third review.

## Q-2026-10-03-2 — Slice 3 stopped before code: Reservation Refunds and forfeitures cannot become drafts as built (ANSWERED 2026-10-04; answers in docs/010)

Your answer to plan Q6 says every Refund and every deposit forfeiture, Reservation ones included, becomes a draft confirmed by `financial.approve`. The Reservation code was built differently, under approved rules:

- **Cancellation is one atomic action with its Deposit outcome.** `app.cancel_reservation_v2` cancels the Reservation and, in the same transaction, records the Security Deposit outcome: a forfeiture for a Customer-caused cancellation (BR-RES-021) or a Refund for a Property-caused cancellation (BR-RES-022). A constraint trigger from migration `20260825_21` (`reservations_financial_outcome_complete`) refuses a cancelled Reservation without its outcome.
- **Expiry is automatic.** BR-RES-016 approves automatic expiration. The expiry worker (`reservation_worker.py`) expires overdue Reservations and records the forfeiture (BR-RES-021) as a service actor, not a person. A draft needs a human preparer, and nobody would be there to prepare it.
- **Outcome corrections** (`app.correct_reservation_deposit_outcome`) replace a Refund or forfeiture under `reservation_deposits.correct`.

To make these drafts, the cancellation and the Deposit outcome must be split. That changes approved behavior (BR-RES-016, BR-RES-021, BR-RES-022) and needs a migration that relaxes the outcome-complete trigger. Under the takeover rules this is a rule conflict, so I stopped. No slice 3 code is written.

Questions (with my recommendation):

1. Reservation cancellation by staff: should the Reservation still be cancelled at once, with the Deposit Refund or forfeiture recorded as a draft that takes effect only when a `financial.approve` holder confirms it? Recommendation: yes. The Unit is released at once; the Deposit stays held (no Refund, no forfeiture) until confirmation. This needs a relaxing migration so that a cancelled Reservation may wait for a pending draft.
2. Automatic expiry: who prepares the forfeiture draft? Recommendation: the worker still expires the Reservation and releases the Unit (BR-RES-016 unchanged), and the forfeiture becomes a pending item that Staff turn into a draft and a `financial.approve` holder confirms. No forfeiture happens automatically.
3. Reservation outcome corrections (replace a Refund with a forfeiture or the reverse): also drafts? Recommendation: yes, as a draft confirmed by `financial.approve`.
4. Refund corrections that already exist (verified return of a Refund, reversal of that correction, under `refunds.correct` and `refunds.corrections.reverse`): BR-AUTH-010 names Refunds, not their corrections. Recommendation: leave them as they are (no draft).
5. Order of work: Recommendation: split slice 3.
   - **3a** (clear now): the Refund methods list, method and reference note on every new Refund, the joint-Signer recipient rule for Pet Deposit Refunds, and Refund drafts for Credit, Payment and Pet Deposit Refunds. The old direct `POST /refunds` returns a clear error.
   - **3b** (after your answers to 1 to 3): Reservation Refunds and Reservation forfeitures as drafts. This also covers the Reservation part of slice 6.
   May I start 3a while you consider 1 to 3?

## Q-2026-10-04-3 — Slice 3a-1 stopped: one should-fix remains after review round 2 (RESOLVED: owner chose Option A; committed after round 3)

Slice 3a-1 (Refund methods and Refund drafts, migration `20261013_78`) is built; the full PostgreSQL suite passes (1676 passed, 0 failed). Round 2 of the independent review found one should-fix, so the work stopped under ops/V1_056_TAKEOVER.md sections 4 and 6. Nothing of 3a-1 is committed. Full record: ops/reviews/V1-056-slice-03a1-refund-drafts.md.

The should-fix: a Payment Refund draft can go stale when a Rent Invoice or Late-payment Charge of the payer becomes outstanding after the draft was recorded. Confirmation is then correctly refused (no money moves), but the caller gets 503 "outcome unresolved; replay" instead of 422 "stale draft". This will happen in normal use after the monthly Rent run.

Recommendation: allow me to (1) check Payment eligibility before creating the Refund at confirmation and report a stale draft as 422, (2) take the four notes as well where cheap (explicit `variant` and `source_kind` checks, Pet source no longer qualified reported as 422, a direct database test of the note length), (3) run the slice tests and the full PostgreSQL suite once, and (4) get one more fresh independent and security review (a third round for 3a-1 only). If that round has no should-fix, commit 3a-1 and continue with 3a-2.

Alternative: fix only the should-fix, add its test, run once and commit without a third review.

## Q-2026-10-04-4 — Slice 3a-2 stopped before code: which Customer Ledger shows a Deposit Refund paid to another Signer?

BR-REFUND-015 says a Deposit Refund goes to the Primary Tenant unless all Lease Signers agree in writing that another Signer receives it. Today the Customer Ledger projection (migration `20260909_48`, `refund_components`) books every Refund on the ledger of its recipient (`refunds.recipient_customer_id`), with the Deposit balance effect. The Pet and Security Deposits belong to the Primary Tenant (`deposits.customer_id`). If another Signer receives the Refund, that Signer's ledger would show a Deposit leaving that they never paid, and the Primary Tenant's ledger would still show the Deposit as held. No rule says which ledger records it. Under the takeover rules this is a missing rule, so I stopped. No 3a-2 code is written.

Questions (with my recommendation):

1. Which ledger shows the Refund? Recommendation: the Deposit owner's ledger (the Primary Tenant), showing the Refund paid out of the Deposit and naming the Signer who received the money. The receiving Signer's ledger shows no balance change.
2. This needs the ledger projection changed so that a Deposit Refund is booked on the Deposit owner's ledger, plus a new "paid to" field. The change is additive (a new projection version, earlier records unchanged). Is that approved?
3. The written agreement: Recommendation: free text (who agreed, the date, how), 1 to 2,000 characters, recorded with the Refund draft and shown with the Refund. The chosen person must be a Signer of that Lease, and the approver confirms the agreement with the draft. No document upload (no photo or file storage in V1).
4. Scope: Recommendation: apply the rule to the active-Lease Pet Deposit Refund now (slice 3a-2) and to the Final Settlement Deposit Refunds in slice 9 with the same records. Reservation Refunds (3b) have no Lease Signers and always go to the Reservation Customer.
