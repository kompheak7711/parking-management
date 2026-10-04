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

## Q-2026-10-04-5 — Slice 3b stopped: four should-fix findings remain after review round 2

Slice 3b (Reservation Deposit drafts, migration `20261015_80`) is built under your answers to Q-2026-10-03-2. Latest full PostgreSQL run: 1697 passed, 0 failed; backend unit 3341 passed; frontend 1586 passed; lint, type check, format and build clean. Round 2 found no blocker but four should-fix findings in total (security 1, independent 3), more than the standing round-3 allowance of two, so the work stopped under ops/V1_056_TAKEOVER.md sections 4 and 6. Nothing of slice 3b is committed; the files are in the working tree. Full record: ops/reviews/V1-056-slice-03b-reservation-drafts.md.

Remaining should-fix findings:

1. (Security) Tests for isolation: a confirm with a draft of another Property or another Reservation, the slice 3a Refund confirm given a Reservation draft and the reverse, and the role privileges of the two internal helpers and of PUBLIC/runtime on the retired functions. The code already refuses these; only the tests are missing.
2. (Independent) The Reservation read shows `AWAITING_DECISION` for any cancelled Reservation that has no current outcome effect, including earlier Reservations whose Refund was fully returned or whose disposition was reversed after a receipt unwind. Those are not waiting and cannot get a draft. Fix: show `AWAITING_DECISION` only when no outcome record exists (the same test as the waiting list), and add a test.
3. (Independent) A receipt reversed before cancellation: before this slice the cancel and expire functions failed in that case; now the cancellation succeeds and the Deposit (nothing held) can never be decided. Only one receipt is recorded per Reservation, so no money is stranded. Fix: keep the old behaviour by refusing the cancel or expiry when a reversed receipt exists, or record the new behaviour.
4. (Independent, needs your decision) Only one Deposit draft per Reservation may be pending, and a bad draft (Refund number used elsewhere, method turned off, typo) stays pending. Reject and withdraw exist as services but their HTTP routes come in slice 11b, so until then such a Reservation is blocked over HTTP.

Recommendation: allow me to (a) add the isolation tests (1); (b) show `AWAITING_DECISION` only when no outcome record exists, with a test (2); (c) refuse cancel and expiry when the Reservation Deposit has a reversed receipt, which keeps the earlier behaviour (3); (d) bring the reject and withdraw HTTP routes for drafts forward from slice 11b, limited to the Reservation Deposit kinds, with route tests (4); also correct the comment that calls the stale check unreachable (a later receipt on a partly received Deposit can trigger it; it fails safe). Then run the full unit and PostgreSQL suites once each and get one fresh round 3 review of slice 3b. If round 3 has no should-fix, commit slice 3b.

Alternative for 4: accept the block until slice 11b and record it in docs/010.

## Q-2026-10-04-6 — Slice 3b stopped: round 3 has one should-fix (documentation only) (ANSWERED 2026-10-04: Yes; docs/010 corrected and slice 3b committed without another run or review)

Round 3 (independent and security) found no blocker, confirmed that no older database guard was lost in the two replaced functions, and confirmed that every narrowed test follows a real rule change. Both reviewers raised the same should-fix: in docs/010, the "Updated tests (V1-056 slice 3b)" note still says `app.validate_deposit_receipt_reversal` refuses a reversal "while a cancelled Reservation's Deposit has no outcome record" (the round-1 guard) and that the financial role lacks EXECUTE on "the three retired functions" in one narrowed test (that test checks three; four are retired in total). The code refuses only while a Reservation Deposit draft is pending. Under your rule there is no round 4, so nothing is committed.

Recommendation: allow me to correct that docs/010 sentence only (no code or test change), then commit slice 3b without another run or review. Exact replacement: "`app.validate_deposit_receipt_reversal` also refuses a receipt reversal while a Reservation Deposit draft for that Reservation is pending (Q-2026-10-04-5), tested by `test_receipt_reversal_is_refused_only_while_a_draft_is_pending`; no earlier test reverses such a receipt." and "...expects the financial role to lack EXECUTE on the three one-call functions it checks (the fourth, `app.correct_reservation_deposit_disposition_v2`, is checked in `test_reservation_deposit_draft_roles_and_retired_one_call_paths`)".

## Q-2026-10-04-7 — Slice 4 stopped before commit: cleaning charge category differs from the approved plan (ANSWERED 2026-10-04: Option B, keep `MISCELLANEOUS_CHARGES` with the link table)

Slice 4 (Unit cleaning rate and move-out cleaning charge, migration `20261016_81`) is built. Review round 1 found one should-fix that only you can settle, so nothing of slice 4 is committed; the files are in the working tree. Record: ops/reviews/V1-056-slice-04-cleaning-charge.md.

The approved plan (slice 4) says the cleaning charge uses a new one-time charge category `UNIT_CLEANING`. I built it with the existing `MISCELLANEOUS_CHARGES` category plus a link table `app.unit_cleaning_charges` (rate snapshot, Lease, Unit, move-out event, at most one per Lease). The reviewer is right that this differs from what you approved:

- The cleaning charge shows as "Miscellaneous" in Invoice category lists, filters and the ledger; the line description says "Unit cleaning charge".
- Staff with `invoices.create` can still record an ordinary Miscellaneous charge and call it cleaning, with any amount and none of the cleaning checks. The Settlement check in slice 8 would read only the linked cleaning charge.

Options:

- **Option A — follow the plan: new category `UNIT_CLEANING`.** A new relaxing migration adds the value to the category checks of `app.authorized_nonrecurring_obligations`, `app.invoice_lines` and `app.active_invoice_source_claims`, and patches the functions that list the one-time categories (Invoice line and issuance validators, draft correction, `app.record_one_time_charge` keeps refusing it so only the cleaning command can create it). Python category lists, the Invoice API category filter, the frontend Invoice client type and labels, and their tests change too. No earlier migration is edited. Cost: a larger slice touching Invoice code that many tests cover; one more full PostgreSQL run and review.
- **Option B — keep `MISCELLANEOUS_CHARGES` with the link table** (as built). Smaller and lower risk. Reports and the ledger show the category Miscellaneous; the cleaning charge is found through the link table.

Recommendation: Option B for V1, because the link table already identifies every cleaning charge exactly and the Settlement and reports can use it; choose Option A if you want cleaning shown as its own category in Invoice lists and the ledger.

If you choose B, I will record the decision in docs/010, get the round 2 review of the test changes, and commit slice 4 if round 2 has no findings (or under the standing round-3 rule). If you choose A, I will build it in this slice, run the full suites once, and get round 2.

## Q-2026-10-04-8 — Slice 5 stopped before code: three gaps in the hand-back month rule (BR-RENT-030) (ANSWERED 2026-10-04; answers in docs/010)

Slice 5 (hand-back month: VOID if unpaid, keep if paid, credit Adjustment for the unpaid rest) is not started; no code is written. A read-only survey found three points the rules do not settle. Under ops/V1_056_TAKEOVER.md section 6 and your rule to ask before building anything differently, I stopped.

What I will do unless you say otherwise (these follow the rules and the plan): the date that counts is the actual move-out date of the current physical move-out record; "paid" means Payments and Customer Credit applied to the Invoice, so "fully paid" is nothing outstanding and "partly paid" is something applied and something outstanding; the credit Adjustment removes each line's outstanding amount (Rent and fixed Service lines, plan Q9); one explicit staff command per Invoice checks the conditions and performs the VOID (`invoices.void`) or the credit Adjustments (`invoices.adjust`) with a reason, linked to the move-out record; nothing runs automatically. Recurring Rent is due on the 5th (BR-RENT-009), so a hand-back before the 5th meets no Late-payment Charge on that month's Invoice.

Questions (with my recommendation):

1. **Which terminations?** BR-RENT-030 says "a Customer leaving before the Lease End Date". BR-RENT-024 and BR-LEASE-021, which it amends, are about voluntary early leaving. Does it also apply when the Lease was terminated for a violation, for the 30-day Rent nonpayment default, for pet noncompliance, or for unpaid Initial Rent or Security Deposit? Recommendation: voluntary early leaving only (a verified BR-LEASE-021 termination with basis `VOLUNTARY_EARLY`); for the other bases the command refuses, and staff keep the existing VOID and Adjustment commands with a reason.
2. **The next month's Invoice when the hand-back is between the 25th and the month end.** The rule says it is VOIDed when unpaid. It does not say what happens when that next month's Invoice is fully or partly paid. Options: (a) treat it like the hand-back month: fully paid is kept (the Customer may stay until the end of that month), partly paid gets a credit Adjustment for the unpaid rest; (b) only the unpaid VOID is built; a paid or partly paid next-month Invoice is refused by the command and handled by staff with the existing commands. Recommendation: (b), because the rule names only the VOID for that Invoice and (a) would let the Property keep a month's Rent after the Customer left.
3. **The Initial Rent Invoice.** When the hand-back month is the Lease's first month, that month's Rent is on the Initial Rent Invoice, which has its own unpaid follow-up rules (BR-RENT-009, DL-064, unpaid-Initial termination). Recommendation: the command covers only recurring Rent Invoices (generated on the 25th); an Initial Rent Invoice stays with the existing Initial Rent rules and commands.

If you accept the recommendations, I build slice 5 as planned with these limits, record them in docs/010, and continue under the run rule and the standing round-3 rule.

Owner answers (2026-10-04): (1) voluntary early leaving only; other termination bases use the existing VOID and Adjustment commands. (2) The next month's Invoice (hand-back between the 25th and the month end) is treated like the hand-back month: unpaid VOID with a reason; fully paid kept, no Refund and no credit, the Customer may stay until that month ends; partly paid keeps the paid part and a credit Adjustment removes the unpaid rest. (3) Only the monthly Rent Invoices generated on the 25th; the Initial Rent Invoice keeps its existing rules. Defaults approved: current move-out record date; Payments and Customer Credit count as paid; per-line credit Adjustment; one explicit staff command per Invoice under `invoices.void` or `invoices.adjust`, with a reason; nothing automatic.

## Q-2026-10-04-9 — Slice 5 stopped before code: the kept, fully paid next-month Invoice conflicts with the text of BR-RENT-026 (ANSWERED 2026-10-04: Option A; sentence added to BR-RENT-026 and PR-RENT-026)

You asked me to stop if your answers to Q-2026-10-04-8 conflict with a written rule. One does.

BR-RENT-026 (docs/002, and PR traceability in docs/003): "If advance billing created a Rent Invoice for a period that is no longer valid after an approved termination, the original Invoice must not be silently edited or deleted. It must follow the controlled VOID or linked Adjustment process, including resolution of active financial dependencies." Its DL-068/DL-069 amendment covers only the VOID case.

Your answer 2 keeps a fully paid next-month Rent Invoice with no VOID and no Adjustment (the Customer may stay until that month ends). For a hand-back between the 25th and the month end, that whole next month comes after the Lease's actual termination date, so by the BR-RENT-026 text the Invoice is "for a period that is no longer valid" and must go through VOID or a linked Adjustment. The unpaid case (VOID) and the partly paid case (linked credit Adjustment) already follow BR-RENT-026; only the fully paid case does not.

No code depends on the answer: for a fully paid Invoice the slice 5 command records nothing and moves no money either way. The question is which written rule is right.

Recommendation: approve a one-sentence amendment to BR-RENT-026 (and its docs/003 traceability note): "Under BR-RENT-030, a fully paid Rent Invoice for the hand-back month, or for the next month when the hand-back is between the 25th and the month end, is kept as issued with no VOID, Refund or credit Adjustment (DL-068, Q-2026-10-04-8)." I would add it to docs/002 and docs/003 and record it in docs/010, then build slice 5.

Alternative: the fully paid next-month Invoice must follow BR-RENT-026 after all; then tell me which process (VOID would require reversing the Payment Allocations first; a credit Adjustment on a fully paid line is allowed and its excess becomes Customer Credit (migration 20261003_67). Either way the paid Rent would come back to the Customer as Credit, which your answer 2 rules out).
