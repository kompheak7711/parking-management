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

## Q-2026-10-04-10 — Open item found in slice 5 (not blocking): unpaid-Initial termination may fail with two credit Adjustments (ANSWERED 2026-10-04: test then fix in the slice 6 migration; refuse a move-out correction that a hand-back resolution relies on)

While building slice 5 I found that `app.adjust_invoice` ends with `SET CONSTRAINTS ALL IMMEDIATE`, which stays in force for the rest of the transaction. A function that calls it more than once in one transaction then fails on the second call when that call brings the Invoice to zero outstanding (slice 5 run 3). Slice 5 handles this by deferring the constraints again before each call (precedent: migrations 39 and 41).

The accepted migration `20261005_70` (unpaid-Initial termination resolutions) calls `app.adjust_invoice` in a loop the same way (`20261005_70_unpaid_initial_rent_termination.py` lines 236 and 329), so it may fail when more than one Invoice line needs a credit Adjustment. Changing an earlier accepted migration is a stop condition, so I have not touched it and not tested it.

Recommendation: in a later slice (or slice 12), add a test with two lines needing a credit, and if it fails, fix it in a new additive migration that replaces only that function body with the same deferral, under your approval.

Second open question from slice 5 (security review round 1): should a physical move-out correction be refused once a hand-back resolution refers to that move-out record? Today the correction is allowed and the resolution keeps the record it used. Refusing it would change the physical move-out rules, so I did not build it. Recommendation: allow it (as built) and show the resolution with its recorded move-out in the later screens.

## Q-2026-10-04-11 — Slice 6 stopped before code: three gaps for Deposit forfeiture and the Pet Deposit (ANSWERED 2026-10-04: all three recommendations; answers in docs/010)

Slice 6 (BR-DEP-018, 019, 022, 023, 026, 027) is not started; no code is written. A read-only survey found three points the plan and rules do not settle.

What exists today: Lease Deposit dispositions run at once under `deposits.dispose` for three governing rules (`BR-DEP-023` voluntary early, `BR-DEP-022` pet noncompliance, `BR-LEASE-005` unpaid Initial obligation when the Customer never moved in; migrations 58 and 70). The unpaid-Initial termination resolution (migration 70) records its Security Deposit forfeiture inside the same command. There is no Deposit application record at all: `app.deposit_applications` does not exist (migration 28 only checks whether it exists).

Questions (with my recommendation):

1. **The Pet Deposit "pays valid pet damage first" (BR-DEP-027).** Paying a Damage charge from the Pet Deposit needs a new kind of financial record (a Deposit application), counted as paid in every Invoice outstanding and status calculation and in the Customer Ledger. That is a large change to code many slices rely on, and the same record is what the Final Settlement needs for DL-032 steps 3 to 5 (slices 8 and 9, DB-SETTLE). Options: (a) build the Deposit application in slice 6; (b) build it once, in the Final Settlement slices, and in slice 6 build only the forfeiture drafts; the Pet Deposit outcome under BR-DEP-027 (damage first, rest refunded) is then decided at Final Settlement. Recommendation: (b), because the remaining Pet Deposit to refund can only be known after the damage is paid, and building the application twice would risk two different rules.
2. **Working out the forfeiture ground from the termination record (plan Q10).** The termination's governing rule identifies most cases: `BR-LEASE-021` voluntary early (Security forfeited), `BR-DEP-022` with basis `CUSTOMER_VIOLATION` pet noncompliance (both deposits forfeited), `BR-LEASE-025` with basis `CUSTOMER_VIOLATION` non-pet violation (Security forfeited), `BR-LEASE-005` with basis `UNPAID_INITIAL_OBLIGATION` (Security forfeited, now also when the Customer moved in, BR-DEP-026). But no termination record is linked to the 30-day Rent nonpayment default: the termination context has no Serious Default event field and no code refers to `BR-LEASE-028`. Recommendation: accept the 30-day default ground only when the termination's governing rule is `BR-LEASE-028` and a `THIRTY_DAY_SERIOUS_DEFAULT` event is recorded for that Lease on or before the termination date; otherwise refuse (as Q10 says).
3. **Existing direct forfeiture paths (plan Q6: every Deposit forfeiture becomes a draft).** The direct `deposits.dispose` route for Lease Deposits would answer 409 and point to the draft route, as slice 3b did for Reservations. The unpaid-Initial termination resolution (migration 70) forfeits the Security Deposit inside its command. Options: (a) the resolution stops forfeiting and staff record a forfeiture draft afterwards, confirmed by `financial.approve` (a relaxing change of an accepted migration's function, like slice 3b); (b) leave that resolution as approved (its forfeiture stays immediate). Recommendation: (a), so that every forfeiture follows the same draft-then-confirm rule.

If you accept the recommendations, slice 6 builds: forfeiture drafts (`DEPOSIT_FORFEITURE`, `deposits.dispose` to prepare, `financial.approve` to confirm) for every BR-DEP-026 ground and for both deposits under BR-DEP-022, always the whole held amount, never applied to what the Customer owes; the ground taken from the termination record; the direct Lease disposition route answering 409; and the migration 70 change in (3). The BR-DEP-027 Pet Deposit outcome moves to slices 8 and 9.

## Q-2026-10-04-12 — Slice 6 stopped after review round 1: a direct Lease Deposit forfeiture is still possible (ANSWERED 2026-10-04: Option A; real draft and confirm path where a test checks the forfeiture, owner test helper only for setup; do not block move-out corrections for the cleaning charge)

Slice 6 (migration `20261018_83`) is built and its full PostgreSQL run passes (1724), but both round-1 reviewers found the same blocker. Nothing of slice 6 is committed; the files are in the working tree. Record: ops/reviews/V1-056-slice-06-lease-deposit-forfeiture.md.

The blocker: the financial role still executes `app.record_lease_deposit_disposition_with_context` and `app.record_lease_deposit_disposition` (migration 58), and the service method `PostgresDepositService.record_disposition` still forfeits a Lease Deposit at once under `deposits.dispose`, without a draft or a `financial.approve` holder. My earlier statement that there was "no direct route to retire" was wrong in effect: there is no HTTP route, but the database grant and the service method are a direct path. Slice 6 also widened that function to the new grounds. This breaks BR-AUTH-010 and your answer to plan Q6.

Closing it is a tightening change (revoking an EXECUTE grant), which needs your approval, as the slice 3b revoke did.

Recommendation (Option A): in migration `20261018_83`, revoke the financial role's EXECUTE on both direct Lease disposition functions (an approved exception like slice 3b; the draft confirm keeps calling them as the function owner); make `record_disposition` refuse with a clear "forfeiture draft required" error; and narrow the existing tests that create Lease dispositions through `record_disposition` (about eight test files) by calling the database function through a test helper as the database owner, so their assertions stay unchanged, with a docs/010 note per test.

Also from round 1 (no decision needed; I will fix them before round 2): tests that confirm a `BR-LEASE-025` draft, a `BR-LEASE-028` draft with a recorded Serious Default event and a `BR-LEASE-005` draft after move-in; stale-draft, key-reuse, disposition-id-reuse, wrong-Property and wrong-Deposit tests; the least-privilege test also asserting the revoked grants; a unit test that the service refuses before any connection; error mapping of P5801 and 23P01 to a conflict; one guarded `if` turned into an assertion; the docs/010 note corrected (the bug failed in run 2, not run 1).

One related note for you (no change unless you say so): a Unit cleaning charge (slice 4) also records the move-out event it relied on, but a move-out correction does not change the charge, so I recommend not blocking corrections for it.

## Q-2026-10-04-13 — Slice 6 stopped before the round-1 fixes: a Lease Deposit forfeiture can be reversed directly (ANSWERED 2026-10-04: Option A; revoke in migration 83, route and service answer 409 in slice 6, reversal draft in sub-slice 6b; Deposit receipt reversal stays as it is)

You answered Q-2026-10-04-12 (Option A) and asked for one more read-only search of the whole backend for any database grant or service method that can keep or move Deposit money without a draft and an approver, and to stop if another one is found. One is found. No file of slice 6 has been changed since your answer; nothing is committed.

The finding: a confirmed Lease Deposit forfeiture can be reversed at once, without a draft and without a `financial.approve` holder.

- HTTP: `POST /deposit-dispositions/{disposition_id}/reverse` (`deposit_api.py`, `reverse_disposition_route`), under `deposits.correct` with a reason and an evidence reference.
- Service: `DepositFlow.reverse_disposition` and `PostgresDepositService.reverse_disposition`.
- Database: `app.reverse_deposit_disposition_v2` (migration `20260826_28`), EXECUTE granted to the financial role; it calls `app.reverse_deposit_disposition` (migration `20260826_27`), which accepts Lease dispositions only.
- Effect: the forfeited amount returns to the held Deposit. No money is paid out by the reversal itself; any later Refund or new forfeiture of that Deposit still needs a draft and an approver. But a holder of `deposits.correct` alone can undo a forfeiture that a `financial.approve` holder confirmed.
- The Reservation equivalent is already a draft (your answer to Q-2026-10-03-2: "Reservation outcome corrections are drafts too"; the route refuses Reservation dispositions since slice 3b). Refund corrections (verified returns and their reversal) stay without a draft by the same answer. BR-AUTH-010 names forfeiture, not its reversal.

Everything else the search found is already draft-only or outside the rule:

- Lease forfeiture: `app.record_lease_deposit_disposition` and `app.record_lease_deposit_disposition_with_context` (migrations 27 and 58) and `PostgresDepositService.record_disposition` — being closed under your Option A answer to Q-2026-10-04-12.
- Reservation Deposit: `app.cancel_reservation_v2`, `app.expire_reservation_v2`, `app.correct_reservation_deposit_outcome`, `app.correct_reservation_deposit_disposition_v2` revoked from the financial role (migration 80); `app.complete_reservation_deposit_outcome` and `app.create_reservation_deposit_outcome` never granted to it; only the draft record and confirm functions remain.
- Refunds (Credit, Payment, Pet Deposit): `app.create_usd_refund` and `app.create_pet_usd_refund` revoked (migration 78); `app.create_pet_usd_refund_to_signer` internal (migration 79); `POST /refunds` answers 409; only `app.record_refund_draft` and `app.confirm_refund_draft` remain.
- Unpaid-Initial termination: the never-moved-in resolution stops forfeiting in slice 6; the moved-in resolution (`app.credit_initial_rent_after_termination`) only records credit Adjustments and does not touch a Deposit.
- Refund corrections: `app.verify_usd_refund_return`, `app.reverse_refund_correction` (`refunds.correct`, `refunds.corrections.reverse`) — no draft by your answer to Q-2026-10-03-2.
- Deposit receipt reversal: `app.reverse_deposit_receipt_v2` (`deposits.correct`, `POST` receipt reverse route) records that money recorded as received was not received (for example a returned transfer). It lowers the held amount but keeps or pays out nothing; I treat it like a Payment reversal and do not count it as a finding. Tell me if you see it differently.
- No other function that writes Deposit dispositions, Deposit reversals or Refunds is executable by the financial or runtime role; no Deposit application record exists yet (slice 9).

Options:

- **Option A — make the Lease forfeiture reversal a draft too**, like the Reservation outcome corrections. In migration `20261018_83`: revoke the financial role's EXECUTE on `app.reverse_deposit_disposition_v2` (a tightening change, needs your approval); the route and service answer 409 "forfeiture reversal draft required" for Lease dispositions; the existing reversal tests use the owner test helper for setup or move to the draft path. The reversal draft itself (record under `deposits.correct`, confirm under `financial.approve`) is either built in slice 6 as well, or in a short sub-slice 6b right after slice 6 (until then a Lease forfeiture cannot be reversed; nothing is published, so no user is affected).
- **Option B — leave the reversal as it is** and record in docs/010 that a forfeiture reversal is a correction like a Refund correction: it returns the money to the held Deposit, pays nothing out, and every later outflow still needs a draft and an approver.

Recommendation: Option A with the reversal draft in sub-slice 6b, because your Reservation answer treats forfeiture corrections as drafts and Option B lets `deposits.correct` alone undo an approver's decision. Option B is acceptable if you prefer to keep reversals quick for staff; no money can leave the Deposit through it.

After your answer I continue with your Q-2026-10-04-12 instructions (revoke, `record_disposition` refusal, test narrowing, the round-1 fixes), then one full backend unit run, one full PostgreSQL run, and review round 2.

## Q-2026-10-04-14 — Slice 6 stopped: round 3 has one should-fix (stale screen text and docs) (ANSWERED 2026-10-04: Option A, text and docs only, one frontend test, frontend checks once, commit; the round-3 notes and the draft-read filter move to sub-slice 6b; the owner helper for tests of the old function's own checks is accepted)

Slice 6 is built with your answers to Q-2026-10-04-12 and Q-2026-10-04-13. Latest runs: backend unit 3368 passed (run 7), PostgreSQL 1729 passed (run 8); format, lint and type check clean. Round 3 security review: no blocker, no should-fix. Round 3 independent review: no blocker, one should-fix, so under your standing rule I stopped. Nothing is committed; all files are in the working tree. Record: ops/reviews/V1-056-slice-06-lease-deposit-forfeiture.md.

The should-fix: migration 83 stops the never-moved-in unpaid-Initial resolution from forfeiting the Security Deposit, but the staff screen still says it does. The confirm dialog (`frontend/src/LeaseManagement.tsx:620`) asks "Forfeit the Security Deposit, VOID or credit the Initial Rent Invoice and release the Unit?", and the form description (`:1499`) says "Forfeits the Security Deposit under BR-LEASE-005". docs/004 (line 293), docs/006 (lines 343 and 740) and docs/007 (line 736) say the same. Staff could believe the Deposit is settled while it stays held until a forfeiture draft is confirmed. No frontend test asserts these strings.

Options:

- **Option A (recommended): correct the text now.** Change the two screen strings to say the resolution VOIDs or credits the Initial Rent Invoice and releases the Unit, and that the Security Deposit is forfeited only through a forfeiture draft confirmed by a `financial.approve` holder. Correct the four doc lines the same way. Also take three cheap round-3 notes: the disposition-id reservation also checks a Reservation draft's `outcome_id` (migration 83, same function), a test for a disposition id used only by a recorded disposition, and the stale status lines (ops/NOW.md, the "Known gap" line in the review record). Then run the frontend gates (format, lint, type check, tests, build) and the backend unit and PostgreSQL suites once each, and commit slice 6 without a round 4. If you prefer, I can drop the migration note and change only text and docs; then only the frontend gates need to run.
- **Option B: answer in writing.** Add a named open item to ops/V1_056_PLAN.md (slice 11c) for the two screen strings and the four doc lines, add one line to the docs/010 slice 6 note saying they are stale until then, and commit slice 6 as it is now (runs 7 and 8).

Open for later either way (recorded, no change in slice 6): the disposition-id check is not serialized across Deposits and has no index; draft reads are filtered by kind only (to fix before the slice 11b/11c draft routes); the BR-LEASE-028 date boundary has no test; the disposition audit names `deposits.dispose` with the approver as actor (revisit in slice 6b).

## Q-2026-10-05-15 — Sub-slice 6b stopped after review round 2: a reversal draft cannot be withdrawn (ANSWERED 2026-10-05: yes to steps 1 to 4; a database refusal for a permission or rule reason must reach the user as a permission or conflict error, with a test for the withdraw case; round 3 reviewers list every capability check for preparing, withdrawing, rejecting and confirming a reversal draft and confirm they match Option A of Q-2026-10-04-13; commit 6b if round 3 has no should-fix)

Sub-slice 6b (Lease Deposit forfeiture reversal drafts, migration `20261019_84`) is built: unit 3374 and PostgreSQL 1735 passed (run 2). Review round 2: the independent reviewer found one blocker, the security reviewer the same defect as a should-fix. Under ops/V1_056_TAKEOVER.md a blocker after round 2 stops the work, and the standing round-3 rule does not apply. Nothing of 6b is committed; all files are in the working tree. Record: ops/reviews/V1-056-slice-06b-reversal-drafts.md.

The defect (verified): after round 1, reversal drafts are prepared under `deposits.correct`, as your Option A wording says. I relaxed the two capability checks on the draft table, but not the third check, on the decision table (`financial_draft_decision_shape`, migration 77), which lists the capabilities allowed for a WITHDRAWN decision. So the preparer cannot withdraw a reversal draft: the database refuses it and the service reports "storage is unavailable". A `financial.approve` holder can still reject it. No money can move through this; but a mistaken reversal draft blocks a new one for that forfeiture until an approver rejects it. No test withdrew a reversal draft, so the runs passed.

Recommendation: allow me to
1. relax that decision check in migration 84 (add `deposits.correct` to the WITHDRAWN list; a relaxing change, like the draft-table checks);
2. add tests: the preparer withdraws; another `deposits.correct` holder and a wrong capability are refused; an approver rejects; a new reversal draft can follow a withdrawal or rejection; confirming a decided draft is refused; the two missing cross-flow refusals; readers with only `deposits.correct` or only `deposits.dispose`; two reversal drafts recorded at once;
3. fix the wording notes (review record "Built" line, one unit test name and its traceability id, migration numbers in the plan) and list the "approver named with `deposits.correct` in the reversal row and audit" point as an owner item in slice 12 instead of calling it closed;
4. run the backend unit and PostgreSQL suites once each, then get one fresh round 3 review (independent and security). If round 3 has no should-fix, commit 6b and continue with slice 7.

Alternative: treat the two reports as one should-fix (they describe one defect), and continue under the standing round-3 rule with the same steps 1 to 4.
