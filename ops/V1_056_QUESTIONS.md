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

## Q-2026-10-05-16 — Slice 7 stopped before code: open points in the wrong-Unit Payment move (BR-PAY-042) (ANSWERED 2026-10-05: yes to all six recommendations; Q2 keep the one-Customer two-step path as an ordinary correction under BR-PAY-029; Q3 keep today's late-payment and nonpayment rules, nothing automatic, staff may waive a Late-payment Decision caused only by the mistake; a Payment reversal plus a new Payment is not a move; answers in docs/010)

Slice 7 is not started; no code is written. As you asked, I first searched the backend read-only for every path that can reverse or change a Payment Allocation, and checked BR-PAY-042, DL-068, DL-069 and the plan against the database. Some points are open, so I stopped under your instruction and ops/V1_056_TAKEOVER.md section 6.

**Every path that can reverse or change a Payment Allocation (read-only search, 2026-10-05):**

1. `POST /payment-allocations/{allocation_id}/reverse` (`allocation_receipt_api.py`), `PaymentAllocationService.reverse_allocation`, `app.reverse_payment_allocation_command` (migration `20260905_39`, financial role, `payments.allocations.reverse`): reverses one whole allocation at once, with a reason. No draft, no approver.
2. `POST /payments/{payment_id}/allocations`, `PaymentAllocationService.post`, `app.post_payment_allocations` (migration 39, financial role, `payments.allocate`): posts new allocations of a Payment (proposal, designated, or direct Late-payment Charge). No draft, no approver.
3. `POST /payments/{payment_id}/reverse`, `PaymentAllocationService.reverse_payment`, `app.reverse_payment_command` (migration 39, financial role, `payments.reverse`): reverses the whole Payment; refused while an allocation, Credit or Refund from that Payment is still active (BR-PAY-012). It moves no value.
4. A credit Adjustment on a paid Invoice line: `app.adjust_invoice` calls `app.reverse_line_value_for_credit_excess` and `app.repost_line_value_after_credit_excess` (migration `20261003_67`; internal, no role may call them directly). They reverse allocations on that line and re-post the rest on the same Invoice; the released value becomes Customer Credit of that Invoice's Customer. The hand-back resolution (slice 5) and the unpaid-Initial moved-in resolution (migration 70) reach them through `app.adjust_invoice`. Always the same Invoice.
5. The guards on `app.payment_allocations` and `app.payment_allocation_reversals` (migration 39, never replaced): append-only; a normal Customer Payment may be allocated only to the payer's own Invoices and Late-payment Charges (BR-PAY-025); a third-party Payment only inside its identified Lease or Invoice (BR-PAY-026). A Payment row cannot be updated except its status change to REVERSED (`payments_immutable`).

No other function or route writes allocations or allocation reversals.

**Can a Payment move between Units today without a draft and an approver?**

- Between two different Customers: no. Paths 1 and 2 together cannot put a Payment on another Customer's Invoice, because of the guard in item 5. A third-party Payment is bound to one Lease or Invoice, so it cannot reach another Unit either.
- One Customer with two Units (two Leases): yes. A holder of `payments.allocations.reverse` reverses the allocation on the Unit 203 Invoice, and a holder of `payments.allocate` allocates the same Payment to that Customer's Unit 201 Invoice. Two one-call commands, no draft, no approver. See question 2.
- A Payment reversal (path 3) followed by a new Payment recorded for the other Customer (`payments.record`) gives the same money result, but with a new Payment and a new Receipt. It does not move a Payment, so I do not count it as a move. Tell me if you see it differently.

**What I will do unless you say otherwise** (plan slice 7, plan answers Q3, Q4 and Q16, DL-069):

- Draft kind `PAYMENT_MOVE`, prepared under `payments.allocations.reverse` (the slice 2 constraint), confirmed only by a `financial.approve` holder; the preparer withdraws and an approver rejects, as for the other kinds.
- The draft records the wrong allocation, the correct Invoice, a reason, and two acknowledgements as free text: one by the Customer of the wrong Invoice, one by the Customer of the correct Invoice. Each states who acknowledged, the date and how (1 to 2,000 characters each, like the BR-REFUND-015 agreement). No file upload.
- The correct Invoice must be in the same Property, issued, not VOID, on another Unit, and must have an outstanding balance. The whole wrong allocation moves; if the correct Invoice owes less, the rest stays unallocated on the Payment (Q16). A wrong allocation can be moved at most once.
- Confirm locks the Payment and both Invoices, refuses a stale draft, reverses the wrong allocation and posts the new allocation in one transaction, and links the draft, the reversal and the new allocation in a link table. The Payment row and the Receipt never change. Nothing runs automatically.
- A refusal caused by business state (stale draft, blocked by Credit or Refund) is reported as a conflict, as you answered for slice 11c. No HTTP route or screen before slice 11d.

**Questions (with my recommendation):**

1. (B) **A move between two Customers breaks the payer rule.** The BR-PAY-042 example (paid on Unit 203, meant for Unit 201) needs the Payment to pay another Customer's Invoice. BR-PAY-025, BR-PAY-026 and the guard in item 5 allow a normal Payment only on the payer's own Invoices, and a third-party Payment only inside its identified Lease or Invoice. The Payment record never changes, so the recorded payer stays the Customer of Unit 203. Options:
   - (a) The new allocation made by the move gets its own allocation basis (for example `WRONG_UNIT_MOVE`). Only a confirmed move draft can create it, and it is exempt from the payer and third-party intent checks. This is a relaxing change to the allocation guard in a new migration; migration 39 is not edited. The Customer Ledger already books the use of a Payment on the payer's ledger and the Invoice reduction on the Invoice Customer's ledger, so the ledger needs no change. Consequence: if the correct Invoice owes less (Q16), the rest stays unallocated on the recorded payer, and the normal Credit rule (payer authorization, BR-CREDIT-002) and Refund drafts apply to that payer.
   - (b) Only moves that the existing checks already allow: one Customer with two Units, or a third-party Payment inside its own Lease. The two-Customer case in BR-PAY-042 then cannot be done.
   Recommendation: (a), with one sentence added to BR-PAY-025 and BR-PAY-026 that points to BR-PAY-042.

2. (B) **The one-Customer two-step path (one-call reversal, then one-call allocation to another Unit).** Options:
   - (a) Close it: the one-call allocation refuses to put a Payment on an Invoice or Late-payment Charge of a Unit other than the Unit of any of its earlier one-call reversed allocations; only a confirmed move draft may. This tightens an accepted guard. Side effect: value of that Payment that was never on the wrong Unit could then reach another Unit only through a move draft, which would need a second draft form (value without a source allocation). Some existing tests may need narrowing.
   - (b) Keep it as the ordinary allocation correction of BR-PAY-029: the value stays with the same Customer, so no value moves between Customers. I record this in docs/010. The move draft can still be used for one Customer.
   Recommendation: (b). Closing it exactly needs per-Unit tracking of released value, which the allocation records do not have, and the simple rule in (a) also blocks correct allocations. Choose (a) if every move between Units must have an approver, even for one Customer.

3. (B) **Late-payment and Rent nonpayment counting after the move.** Today a Late-payment Decision is possible for an UNPAID Invoice after its Due Date, and the 20-day warning and 30-day Serious Default count from the day before the billing period starts (`app.rent_nonpayment_day_zero`, migration 68). So a move made 30 days or more after the billing period starts makes the first Customer at once eligible for a Late-payment Decision and the 30-day Serious Default, although the Invoice looked paid until the move. The plan says "evaluation counts from the move"; DL-069 says "the normal late-payment and Rent nonpayment rules apply from then on". Options:
   - (a) Existing rules unchanged: the days count as today; the move records nothing about late payment; staff decide (Decisions and milestones are never automatic, and a Late-payment Decision can be WAIVED). The plan test becomes "after the move the normal rules see the Invoice as unpaid; earlier records are unchanged".
   - (b) Count from the move date for that Invoice: a new start date used by the late-payment and nonpayment checks. This changes accepted rules and functions.
   Recommendation: (a), because it follows "the normal rules" and changes no accepted function; staff can waive.

4. **When Customer Credit or a Refund blocks the move.** Credit and Refunds are recorded per Payment, not per allocation, so "the wrong allocation became Credit or a Refund" can be traced only for a credit Adjustment (`app.invoice_credit_excess_releases`). Recommendation: block the move while the Payment has any Customer Credit that is not reversed, or any Refund that is not fully returned. Staff reverse those first.

5. **The wrong allocation was already reversed.** If staff already reversed the wrong allocation with the one-call reversal (for example before reversing a Credit made from that value), there is no active allocation to move. Recommendation: the draft may also name a wrong allocation reversed by the one-call reversal, when the Payment's unallocated value still covers its amount; confirm then only posts the new allocation.

6. **Which allocations, and how the moved amount is spread.** Recommendation: only an allocation on an Invoice moves, and only to an Invoice (not a Late-payment Charge allocation, and not to a Late-payment Charge), because BR-PAY-042 names Invoices. On the correct Invoice the amount is spread over its lines by the existing within-Invoice default order (BR-PAY-036), worked out when the draft is recorded and stored in it; confirm refuses the draft as stale if that Invoice changed since.

If you accept the recommendations, I build slice 7 with these limits, record them in docs/010, and continue under the run rule and the standing round-3 rule.

## Q-2026-10-05-17 — Slice 7 design: a moved allocation reversed by the one-call reversal (ANSWERED 2026-10-05: refuse the one-call reversal)

Found while designing slice 7, before any code. After a confirmed move the Payment still names its recorded payer (the Unit 203 Customer). If staff later reverse the moved allocation with the one-call reversal (`payments.allocations.reverse`), the value goes back to that payer's Payment, and a one-call allocation (or Credit for that payer) can put it back on the Unit 203 Invoice: a move between two Customers with no draft and no approver.

Options: (1) the one-call reversal refuses a moved allocation (basis `WRONG_UNIT_MOVE`); it changes only through another move draft confirmed by `financial.approve`, or through a credit Adjustment on that Invoice (the value becomes that Invoice Customer's Credit, BR-CREDIT-014); while a moved allocation is active the Payment cannot be reversed (BR-PAY-012), so a Payment that bounces after a move needs a later decision; (2) allow the reversal and lock the released value against every use except a Payment reversal or a new move draft (four accepted guards change); (3) leave the path open and record it. Recommendation: (1).

Owner answer (2026-10-05): option 1, refuse the one-call reversal of a moved allocation. The bounced-Payment case after a move is an open item for slice 12.

## Q-2026-10-05-18 — Slice 7 stopped after review round 2: three should-fix findings (one needs a rule decision) (ANSWERED 2026-10-05: finding 1 option (a), refuse that Credit reversal; round 3 allowed with the three fixes and the notes; both round 3 reviewers search once more for any other path that could move value from a moved allocation to a different Customer without a draft and an approver, and list what they checked)

Slice 7 (wrong-Unit Payment move, migration `20261020_85`) is built; latest runs: backend unit 3399 passed, PostgreSQL 1760 passed (P3), frontend 1589 passed. Review round 2: no blocker, three should-fix in total (security 1, independent 2), more than the standing round-3 allowance of two, so the work stopped under ops/V1_056_TAKEOVER.md sections 4 and 6. Nothing of slice 7 is committed; all files are in the working tree. Record: ops/reviews/V1-056-slice-07-payment-move.md.

Should-fix findings:

1. (security, needs your decision) Moved value can still return to the recorded payer without a draft, through three one-call commands: a credit Adjustment on the correct Invoice turns moved value into the correct Invoice Customer's Credit (BR-CREDIT-014; the Credit's source is still the payer's Payment); `credits.reverse` reverses that Credit (the existing Credit reversal checks no Customer), so the value becomes unallocated on the payer's Payment; a one-call allocation then puts it on the payer's own Invoice. Only `app.reverse_customer_credit` reverses Credits; reversing a credit Adjustment does not reverse its Credit.
   - (a) Recommended: refuse the one-call Credit reversal of a Credit released from a moved allocation when that Credit belongs to a Customer other than the Payment's payer (a new deferred check on Credit reversals, SQLSTATE P4904, the same kind of refusal as your answer to Q-2026-10-05-17; such Credits could not exist before this slice). That Credit then stays with its Customer: it can be applied to that Customer's Invoices or refunded through a Refund draft confirmed by `financial.approve`. A one-Customer move is not affected.
   - (b) Leave it and record the path as a slice 12 open item.
2. (independent) The confirm does not force the correct Invoice's version forward when its status does not change (for example PARTIALLY_PAID to PARTIALLY_PAID), so a credit Adjustment prepared before the move still passes its version check. Fix: force the Invoice refresh as every other allocation writer does, with a test.
3. (independent) No test proves the exemption for a normal Payment's identified Invoice. Fix: add the test.

Notes I would take with them: rename the audit key `prepared_by` to `prepared_by_actor_id` (the audit reader refuses an unclassified key); a test with lines inserted out of category order to prove the Rent-then-Service ranking; the credit-Adjustment guard proven on its own; a fully returned Refund no longer blocks; neutral wording of the draft size refusal; the payment-move reversal and allocation rows added to the slice 12 owner item about approver naming; backend format, lint and type checks recorded in the review record.

Recommendation: allow a round 3: fix the three findings (1 as option (a)) and the notes, run the backend unit and full PostgreSQL suites once each, then one fresh round 3 review (independent and security). If round 3 has no should-fix, commit slice 7.

## Q-2026-10-05-19 — Slice 7 stopped after review round 3: a third-party gap, and a wrong statement in my Q-2026-10-05-18 option (a) (ANSWERED 2026-10-05: option (a), keep the refusal, correct the wording, add the Refund-draft refusal test; the Refund of such a Credit to the Invoice Customer who is not the payer is required by BR-CREDIT-014 and is planned in slice 9 (Final Settlement needs it), as a Refund draft confirmed by financial.approve; the lasting move and Payment-reversal block is a slice 12 item; fix the third-party gap with a test, take the notes, run unit and full PostgreSQL once each, then one more fresh review of these changes with the same path search; commit only if it has no should-fix)

Slice 7 is built with your answers to Q-2026-10-05-16, -17 and -18; latest runs before round 3: backend unit 3400 passed, PostgreSQL 1762 passed (P4). Round 3 (independent and security, both with your path search) found no blocker but two should-fix, so the work stopped (no round 4 under the takeover rules). Nothing of slice 7 is committed; all files are in the working tree. Record: ops/reviews/V1-056-slice-07-payment-move.md. Both reviewers listed every path they checked (allocation reversal and post, credit and debit Adjustments, adjustment reversal, VOID, hand-back and unpaid-Initial resolutions, Payment reversal, Credit recognition, application, application reversal and reversal, Refund drafts, corrections, verified returns and correction reversals, Deposit receipts and dispositions, Late-payment Charges, another move draft, Final Settlement, direct table writes); all are closed except the two points below.

1. **Third-party gap (both reviewers).** The Credit reversal refusal applies only when the Credit belongs to a Customer other than the payer. For a third-party Payment the payer's unallocated value can only go to the identified Lease or Invoice of another Customer. Path: a third-party Payment (identified for Customer C's Lease) is moved, by an approved draft, to the payer's own Invoice on another Unit; a credit Adjustment releases moved value as the payer's own Credit; `credits.reverse` is allowed (same Customer as the payer); a one-call third-party allocation or a Deposit receipt sends it back to C. Fix: refuse the reversal unless the Payment is a normal Customer Payment and the Credit belongs to its payer; add a test of this chain.

2. **My statement in Q-2026-10-05-18 option (a) was wrong.** I wrote that a Credit released from a moved allocation to another Customer "can be refunded through a Refund draft". It cannot: the existing Refund rules (migration 41) require the Refund recipient to be both the Credit's Customer and the Payment's payer, so a Credit of a Customer other than the payer can never be refunded (the confirmation fails). This limit already existed for third-party Payments since migration 67 (BR-CREDIT-014 says a Refund of such Credit goes to that Customer, but no code does it); slice 7 makes it reachable for normal Payments too. Consequences of your answer (a) as built: such a Credit can only be applied to its Customer's Invoices; it can never be reversed or refunded; while it exists (answer 4 counts any Credit that is not reversed) no other allocation of that Payment can be moved and the Payment cannot be reversed; if the Customer has no open Invoice the value has no way out.

Options for 2:
- (a) Keep the refusal (no money can leave without an approver), correct the wording everywhere ("it can be applied to that Customer's Invoices; a Refund to that Customer is not built"), add a test that a Refund draft of such a Credit is refused at confirmation, and add slice 12 open items: a Refund of a Credit to the Invoice Customer who is not the payer (also for third-party Credits since migration 67), and the permanent move and Payment-reversal block caused by such a Credit.
- (b) Remove the Q-2026-10-05-18 refusal and record the Credit reversal path as a slice 12 open item (the path stays open).

Recommendation: fix 1 as described, take (a) for 2, take the two notes (the grants test also lists the new trigger function; the stale ops/NOW.md line), run the backend unit and full PostgreSQL suites once each, then one more fresh review (independent and security, with the same path search) limited to these changes; commit only if it has no should-fix.

## Q-2026-10-05-20 — Slice 8 stopped before code: open points in the Final Settlement design (ANSWERED 2026-10-05: answers in docs/010; answer 5 conflicts with BR-SETTLE-016, see Q-2026-10-05-21)

Slice 8 (Final Settlement, now including the Deposit application record and the confirm, as you asked) is not started; no code is written. I wrote the design note (ops/V1_056_PLAN.md, "Slice 8 design note"), checked it against your rules in docs/010 and docs/002, and searched the backend read-only for every path that can change a balance, a Deposit or a Credit that the Settlement uses. Some points are open, so I stopped under your instruction and ops/V1_056_TAKEOVER.md section 6.

**Read-only path search (2026-10-05).** "Draft" means a draft confirmed by a `financial.approve` holder.

Invoice and Invoice line balances (Settlement obligations):

1. Payment allocation: `POST /payments/{id}/allocations`, `PaymentAllocationService.post`, `app.post_payment_allocations` (`payments.allocate`). One call. Pays an obligation with the payer's own Payment.
2. Allocation reversal: `POST /payment-allocations/{id}/reverse`, `app.reverse_payment_allocation_command` (`payments.allocations.reverse`). One call; refused for a moved allocation (slice 7). The value goes back to the Payment.
3. Payment reversal: `POST /payments/{id}/reverse`, `app.reverse_payment_command` (`payments.reverse`). Refused while an allocation, Credit or Refund from the Payment is active.
4. Wrong-Unit Payment move: draft only (slice 7).
5. Credit application and its reversal: `app.post_credit_application` (`credits.apply`), `app.reverse_credit_application` (`credits.applications.reverse`). One call, same Customer only (BR-CREDIT-008).
6. Invoice VOID: `app.void_invoice` (`invoices.void`). One call.
7. Credit and debit Adjustments: `app.adjust_invoice` (`invoices.adjust`). One call. A credit Adjustment on a paid line releases value as Credit of the Invoice Customer at once (migration 67). Callers: the hand-back resolution (`app.resolve_hand_back_rent_invoice`, slice 5) and the unpaid-Initial resolutions (`app.resolve_unpaid_initial_never_moved_in`, `app.credit_initial_rent_after_termination`; `unpaid_initial.never_moved_in`, `unpaid_initial.moved_in_credit`). No function writes an Adjustment reversal.
8. Late-payment Decision and Charge: `app.finalize_late_payment_decision` (`late_payment.final_decision`) creates a Charge; `app.correct_late_payment_charge` (`late_payment.charge_correction`) changes it. One call each. One Decision per Invoice (migration 29).
9. New obligations on the Lease: `app.record_one_time_charge` (`invoices.create`, Damage with `damage_charges.bill`), `app.record_unit_cleaning_charge` (`invoices.create`), the final Utility Invoice functions (migration 72), `app.create_invoice_draft` and `app.issue_invoice` (`invoices.create`, `invoices.issue`). One call each.

Deposit held balance:

10. Deposit receipts: recorded with a Payment or at Reservation creation. Receipt reversal: `app.reverse_deposit_receipt_v2` (`deposits.correct`), one call, no draft (your answer for slice 6). The command already calls `app.deposit_has_active_application` (migration 28), which starts to count applications once the table exists; the reversal trigger (migration 80 body) checks dispositions and Refunds but not applications.
11. Forfeiture and forfeiture reversal: drafts only (slices 6 and 6b).
12. Pet Deposit Refund: draft only (slice 3a); its source needs a SIGNED Lease, so it is refused after termination.
13. Refund corrections (verified return, correction reversal): `app.verify_usd_refund_return` (`refunds.correct`), `app.reverse_refund_correction` (`refunds.corrections.reverse`). One call, no draft (your answer to Q-2026-10-03-2). A verified return puts value back into the Deposit or Credit; nothing is paid out.
14. Required-amount adjustment, pet departure and Pet Refund qualification: change no held value.
15. Reservation Deposit drafts: act only on a Reservation in status CANCELLED, not on a Lease Deposit.

Customer Credit:

16. Recognition from a Payment's excess: `app.recognize_customer_credit` (`credits.recognize`), with the payer's authorization. From a credit Adjustment: inside item 7.
17. Credit reversal: `app.reverse_customer_credit` (`credits.reverse`); refused for a moved-value Credit (slice 7).
18. Credit and Payment Refunds: drafts only (slice 3a).

Deposit application: no record exists yet (`app.deposit_applications` is only named in migration 28). The earlier slice reviews found no direct table write granted to the runtime or financial role on these tables; the 8a least-privilege test also checks the new tables.

**Result of the search.**

- Before the Settlement is confirmed, no path moves Deposit money without a draft. One-call paths 1 to 9, 16 and 17 can change a Settlement obligation or Credit, but the confirmation re-checks every source and refuses a stale draft, so nothing moves on an old picture.
- After a Settlement is closed, paths 6 to 9 can still change the settled obligations or add new ones for that Lease, with one call and no approver. A credit Adjustment then works like a write-off, and BR-SETTLE-013 and DL-068 say a later fix is a post-settlement correction confirmed by `financial.approve`. See question 7.
- A Credit or Payment Refund draft of a Customer whose Settlement is still open can be confirmed before the Settlement applies that Credit. It has an approver, so I suggest no change: the preview lists pending drafts on the Settlement's sources as a blocking issue.
- New-state guards I will add in sub-slice 8a (not a tightening, because no Deposit application exists before): VOID, Adjustments and Late-payment Charge corrections refuse a target with an active Deposit application, and the receipt-reversal trigger also refuses while an application is active.

**Questions (with my recommendation):**

1. (B) **Can a Deposit pay a Late-payment Charge?** docs/004 DB-DEP-005 says a Deposit application cannot target a separate Late-payment Charge. DL-069 says Late-payment Charges are part of what a leaving Customer owes, and BR-SETTLE-017 lets the remaining Pet Deposit pay "any remaining balance". Options: (a) a Deposit application may target an Invoice line or a Late-payment Charge of the Settlement, as Credit applications already can; docs/004 is updated. (b) Invoice lines only; a Late-payment Charge is paid only by a Payment or Credit, otherwise it stays as debt. Recommendation: (a).

2. (B) **Which terminations use the DL-032 Security Deposit step?** There is no "normal Lease end" basis. A termination record has a basis (`VOLUNTARY_EARLY`, `CUSTOMER_VIOLATION`, `SIGNED_LEASE_OTHER`, `UNPAID_INITIAL_OBLIGATION`) and a governing rule; a Lease that ends on its End Date is recorded with `SIGNED_LEASE_OTHER` (older commands have no context). Every kept case of BR-DEP-026 is found by the slice 6 forfeiture source. Not covered: an early termination with `SIGNED_LEASE_OTHER` that cites no forfeiture rule (for example an end agreed with the Property, or caused by the Property). Options: (a) the Security Deposit is kept only when the forfeiture source finds a Security ground; every other termination, on the End Date or not, follows DL-032 (the Security Deposit may pay remaining charges and the rest is refunded), because BR-DEP-025 refunds every Deposit that is not forfeited; (b) only a termination dated on the Lease End Date follows DL-032; any other termination without a forfeiture ground shows a blocking issue until you decide the case. Recommendation: (a).

3. (B) **How strict is the DL-032 order?** BR-SETTLE-006 says no Deposit is applied automatically, and BR-SETTLE-008 says the Customer must not get Deposit money back while a balance stays unpaid "when that available Deposit has been authorized for application". Options: (a) strict: the draft is refused unless (i) each Customer's available Credit is used on that Customer's open Settlement obligations before any Deposit is applied to them, (ii) the Pet Deposit pays open pet damage before any Pet Deposit Refund, and (iii) where DL-032 applies, the Security Deposit pays the Primary Tenant's open obligations before any Security Deposit Refund; staff still choose which obligations each step pays; the remaining Pet Deposit for other balances stays optional (the Customer's choice, or staff with a reason). (b) order only: staff choose freely which steps to use; the system only checks that the chosen steps run in DL-032 order. Recommendation: (a), because it matches "pays pet damage first and the rest is refunded" and "the Security Deposit may pay remaining charges and the rest is refunded".

4. **Remaining Pet Deposit by staff at the BR-DEP-027 terminations.** BR-DEP-027 says the Pet Deposit pays pet damage first and the rest is refunded "as in DL-013". DL-013 also lets authorized management apply the remaining Pet Deposit to another remaining obligation (DL-032 step 5). I read this as: at unpaid-Initial, non-pet violation and 30-day default terminations, both the Customer's choice and the staff step (with a reason, confirmed by `financial.approve`) are allowed. Recommendation: yes, confirm this reading.

5. (B) **Lease Invoices of a Signer who is not the Primary Tenant.** The billing functions issue the Lease's Rent, Utility, Damage, one-time, cleaning and final Utility Invoices to the Primary Tenant, but an ordinary Invoice draft with the Lease may name any signed Signer (migration 29). BR-SETTLE-016 puts settlement debt on the Primary Tenant's ledger, and an Invoice's Customer never changes. Options: (a) the Settlement includes every issued Invoice of the Lease; an unpaid Invoice of another Signer stays on that Signer's ledger and the preview shows it separately; the Deposits (owned by the Primary Tenant) pay only the Primary Tenant's obligations; Credit pays only its own Customer's obligations (BR-CREDIT-008). (b) Such an Invoice is a blocking issue until it is paid or corrected. Recommendation: (a).

6. (B) **Late-payment Decisions at the Settlement.** Each Invoice has at most one Late-payment Decision. A Decision made after closure would add a new Late-payment Charge outside the closed Settlement. docs/004 DB-SETTLE-001 says closure waits until every applicable Late-payment Charge is final. Options: (a) the preview shows a blocking issue for every Settlement Invoice where the existing late-payment review says a Decision is possible and none is recorded; staff record the Decision (charge, reduce or waive) before closure; (b) no blocking issue; a later Decision is handled as a post-settlement correction. Recommendation: (a).

7. (B) **One-call changes after closure (search result above).** Options: (a) in sub-slice 8e, refuse VOID, Adjustments (including the hand-back and unpaid-Initial resolutions), Late-payment Decisions and Charge corrections on the Invoices and Late-payment Charges of a closed Settlement, and refuse new obligations for that Lease (one-time and Damage charges, cleaning charge, final Utility Invoice, Invoice drafts with the Lease). Payments, allocations, Credit applications and their ordinary reversals stay open, so the Customer can still pay the debt. Changing the settled obligations then waits for the post-settlement correction draft (slice 10). This refuses input that is accepted today, so it is a tightening and needs your approval. (b) Leave these paths open until slice 10 and record them as an open item. Recommendation: (a).

After your answers I record them in docs/010 and start sub-slice 8a under the run rule and the standing round-3 rule.

Owner answers (2026-10-05): (1) yes, a Deposit may pay a Late-payment Charge like any other debt; amend docs/004 (done). (2) yes, the Security Deposit is kept only where a forfeiture ground exists and its forfeiture draft is confirmed; every other termination follows DL-032. (3) yes, strict order: Credit before Deposits, pet damage before any Pet Refund, the Security Deposit pays open debt before any Security Refund; no Refund while this Lease still has open debt that a Deposit could pay. (4) yes, but only when the Customer chooses it; record the Customer's agreement as text (who, the date, how), like the slice 7 acknowledgements, plus the staff reason. (5) changed: include the Signers' Invoices in the Settlement and let the Deposits pay all open debt of this Lease, whoever is named on the Invoice, in the DL-032 order; debt left after that stays on the ledger of the person named on the Invoice; stop and ask if this conflicts with a written rule or the ledger design. (6) yes, every Late-payment Decision must be recorded before closure, shown as a blocking issue. (7) yes, tightening approved: after closure refuse one-call changes to the Settlement's obligations (VOID, Adjustments, Late-payment Decisions and Charge corrections, new charges on the Lease) until the slice 10 correction drafts exist; Payments and Credit applications stay open.

## Q-2026-10-05-21 — Slice 8 stopped again before code: answer 5 conflicts with BR-SETTLE-016, and two wording points (ANSWERED 2026-10-05: yes to all three recommendations; BR-SETTLE-016, BR-DEP-014, PR-DEP-014 and BR-DEP-027 amended; the DL-013 staff step stays at a normal end and at voluntary early leaving; answers in docs/010)

You asked me to stop if answer 5 conflicts with a written rule or the ledger design. I recorded all seven answers (docs/010 and above) and amended docs/004 for answer 1 (DB-DEP-005, DB-DER-007, DB-DER-009). No code is written and no run was made.

What I checked for answer 5:

- **Ledger design: no conflict.** The Customer Ledger already books a third-party Payment's use on the payer's ledger and the Invoice reduction on the Invoice Customer's ledger. A Deposit application to another Signer's Invoice fits the same pattern: the Deposit owner's (Primary Tenant's) ledger shows the Deposit applied, naming the Invoice and its Customer; the Signer's ledger shows the Invoice paid by a Deposit application. BR-LEDGER-003 and BR-LEDGER-006 keep Deposits separate and need an authorized application, which this is. It needs the new ledger projection version already planned in 8a.
- **Deposit rules: no conflict.** BR-DEP-014, BR-SETTLE-006 and docs/004 DB-DEP-005 tie a Deposit application to the Settlement and its Lease, not to one Customer. DL-031 forbids moving Customer Credit between Customers; it does not cover Deposits.

Conflicts and open points:

1. (B) **BR-SETTLE-016 and the DL-069 "Joint Signers" line.** Both say that a balance the Customer does not pay after Final Settlement stays open as debt on the Primary Tenant's Customer Ledger. Your answer 5 keeps the debt left on another Signer's Invoice on that Signer's ledger. An Invoice's Customer can never change (migration 29 guards), so the debt can only stay with the person named on the Invoice. Recommendation: add one sentence to BR-SETTLE-016 (docs/002): "Debt left on an Invoice issued to another Signer of the Lease stays on that Signer's Customer Ledger, because an Invoice's Customer never changes; at Final Settlement the Lease's Deposits may pay it in the DL-032 order (owner answer to Q-2026-10-05-20)." DL-069 text stays unchanged; docs/010 records the link. Alternative: keep BR-SETTLE-016 as written; then an open Invoice of another Signer is a blocking issue until it is paid or corrected.

2. (B) **BR-DEP-014 says "Invoice obligations".** BR-DEP-014 (docs/002) and PR-DEP-014 (docs/003): "Deposits may be applied to Invoice obligations only as part of the Final Settlement process after Lease termination." Your answer 1 lets a Deposit pay a Late-payment Charge, which is a separate obligation, not an Invoice (BR-LEDGER-006). Recommendation: change that sentence in both documents to "Deposits may be applied to Invoice obligations and Late-payment Charges only as part of the Final Settlement process after Lease termination."

3. (Not needed for 8a; needed for 8c) **One case left open by answers 3, 4 and 5.** At an unpaid-Initial, non-pet violation or 30-day default termination, pet damage is paid, the Pet Deposit has a rest, other Lease debt is still open, and the Customer does not choose to use the rest. Answer 4 says the rest pays other debt only when the Customer chooses; answer 3 says no Refund while the Lease has open debt "that a Deposit could pay"; answer 5 says "I do not want to refund a Deposit while the same Lease still has debt". Options:
   - (a) Without the Customer's choice the Pet Deposit cannot pay that debt, so it is not a Deposit that could pay it: the rest is refunded as BR-DEP-027 says, and the debt stays. At a normal end and at voluntary early leaving, DL-013 and BR-SETTLE-017 keep the staff step (with a reason, when the Customer will not pay), so there the rest must pay open debt before any Pet Deposit Refund.
   - (b) The rest is never refunded while the Lease has open debt. Without the Customer's choice it stays held, and the Settlement cannot close until the Customer chooses or the debt is paid. Risk: a Deposit held with no end date.
   - (c) As (a), but the Customer-choice rule applies at every termination: the staff step is removed everywhere, and BR-SETTLE-005 and BR-SETTLE-017 are amended.
   Recommendation: (a), with one sentence added to BR-DEP-027 (docs/002): "At these terminations the remaining Pet Deposit pays other debt only when the Customer chooses it, recorded as text (who, the date, how) with the staff reason; otherwise the rest is refunded (owner answer to Q-2026-10-05-20)."

Points 1 and 2 decide which obligations a Deposit application may pay, which sub-slice 8a builds, so I stopped before 8a. After your answers I amend docs/002 and docs/003 as approved, record them in docs/010 and start 8a under the takeover rules.

## Q-2026-10-05-22 — Sub-slice 8a-1 stopped after review round 1: a Deposit receipt reversal lets Deposit money pay debt without an approver (ANSWERED 2026-10-05: (a) Option (a), the receipt reversal becomes a draft prepared under `deposits.correct` and confirmed by `financial.approve`, an approved tightening that replaces the Q-2026-10-04-13 answer; (b) built as sub-slice 8r right after 8a-1 is committed; (c) 8r also checks the slice 3b Reservation Deposit receipt reversal and closes it too if it can free money the same way, or says why not; (d) continue 8a-1 now with the five independent fixes and the cheap notes, unit and full PostgreSQL once each, then round 2 under the standing round-3 rule; security S1 is answered by 8r; answers in docs/010)

Sub-slice 8a-1 (Final Settlement record and Deposit application record, migration `20261021_86`) is built. Latest runs: backend unit 3422 passed (U2), full PostgreSQL 1772 passed (P5). Round 1: no blocker. The independent review has five should-fix items that I can fix inside the sub-slice. The security review found one should-fix in code that already existed, and only you can settle it. Nothing of 8a-1 is committed; all files are in the working tree. Record: ops/reviews/V1-056-slice-08a1-settlement-deposit-applications.md.

**The finding (security S1, verified by reading the code).**

1. Staff holding `deposits.correct` reverse a Lease Deposit receipt with one call (`app.reverse_deposit_receipt_v2`). No draft is needed; this is your answer to Q-2026-10-04-13.
2. The Payment that funded the receipt stays RECEIVED. Its value counts as unused again, because `app.payment_disposition_summary` counts only receipts that are not reversed.
3. Staff then allocate that value to the payer's Invoices with one call (`payments.allocate`), or recognize it as Credit with the payer's authorization and apply it.

The result: Deposit money pays debt with no draft and no `financial.approve` holder.

- During an active Lease, Deposit money pays ordinary Invoices, which BR-DEP-013 and BR-SETTLE-010 forbid.
- After termination, it skips the kept-Deposit rule (BR-DEP-026) and the DL-032 order.
- It also works on a kept Security Deposit while its Lease forfeiture draft is pending. The receipt-reversal trigger looks only for Reservation drafts (`payload->>'reservation_id'`). The forfeiture draft then fails as stale.

My statement in Q-2026-10-04-13 that a receipt reversal "lowers the held amount but keeps or pays out nothing" was incomplete. It pays out nothing itself, but it frees the money for a one-call allocation. Reservation Deposit receipts have the same two-step path when no Reservation draft is pending. This is not new in 8a-1, and 8a-1 does not make it worse: its new guard refuses a receipt reversal only once a Deposit application exists.

Options:

- **(a) A Deposit receipt reversal becomes a draft.** Staff with `deposits.correct` prepare it, and a `financial.approve` holder confirms it, like the forfeiture reversal (sub-slice 6b). The one-call reversal answers 409 for Lease and Reservation Deposits; revoking the financial role's EXECUTE is a tightening. The pending-draft check also matches `payload->>'deposit_id'`, so a receipt reversal is refused while any draft for that Deposit is pending. A returned transfer still works: the approver confirms the receipt reversal, then the Payment is reversed as today.
- **(b) Keep the one-call reversal, but lock the freed value.** After a Deposit receipt reversal, that Payment's freed value may only be used by a Payment reversal: no allocation, no Credit recognition, no Refund. This changes four accepted guards (allocation, Credit recognition, Payment Refund, Payment move). You chose not to take the same approach for slice 7 (Q-2026-10-05-17).
- **(c) Refuse it after termination only.** Refuse a Lease Deposit receipt reversal once the Lease is TERMINATED, or while a Lease forfeiture draft or a Final Settlement exists. This leaves the path open during an active Lease.
- **(d) Leave it, and record it as an accepted risk.**

Recommendation: (a), because it closes the path everywhere with the draft-then-confirm model the other Deposit corrections already use. I would build it as its own short sub-slice, 8r, right after 8a-1 and before 8b, with its own runs and reviews.

**Also to confirm:**

1. Please allow me to continue 8a-1 now, treating security S1 as answered by sub-slice 8r. Since 8a-1 does not introduce the path, this does not have to wait for 8r.
2. The round-1 fixes I would make:
   - Independent S1: the Payment reversal context and the financial action context read the Late-payment Charge balance from `app.late_payment_charge_financial_position`.
   - Independent S2: the new refusal reaches Late-payment Charge corrections as a conflict, with a service-level test.
   - Independent S3: docs/004 DB-DEP-005 says the trigger checks stage order and Deposit type, and the draft and confirm (8c, 8e) enforce the strict order.
   - Independent S4: tests for the BR-LEASE-005, BR-LEASE-025 and BR-LEASE-028 grounds through the shared rule, and the Pet Deposit staying applicable at those terminations.
   - Independent S5: a test of a Deposit paying another Signer's Invoice.
   - Notes I would take: a clear refusal for an unknown target, the human-actor check in the writer, and a wider least-privilege test.
   After the fixes: backend unit and full PostgreSQL once each, then review round 2 under the standing round-3 rule.

## Q-2026-10-05-23 — Sub-slice 8r report: four points for the owner (ANSWERED 2026-10-05: (1) accepted; (2) tightening approved, built in 8a-2 with a test; (3) a reversed forfeiture leaves the Security Deposit held, DL-032 at settlement unless a new forfeiture draft is confirmed; stop before 8c if this conflicts with a written rule; (4) agreed; answers in docs/010)

The four points of the 8r report (sub-slice 8r committed as 7db72ad):

1. Until slice 11c builds the receipt reversal draft routes, a returned transfer is processed only through the service. Answer: accepted; the screen hides the action; there are no real users yet.
2. While a receipt reversal draft waits, a Refund draft or a forfeiture draft for the same Deposit can still be recorded and confirmed first; refusing them would be a tightening. Answer: tightening approved. Refuse the confirmation of a Refund draft or a forfeiture draft for the same Deposit while a receipt reversal draft is pending; recording stays allowed. Build it in 8a-2 with a test, because it stops money going out that may never have been received.
3. A Security Deposit whose forfeiture was reversed (sub-slice 6b): `app.lease_deposit_kept_rule` reads only the termination record, so that Deposit stays kept and is never applied. Answer: it is held again, as if that forfeiture never happened. At settlement it follows DL-032 (it pays open debt, and the rest is refunded), unless a new forfeiture draft is confirmed. It must never be stuck with no way to apply or refund it. If this conflicts with a written rule, stop and ask before 8c (see Q-2026-10-05-24).
4. 8c and 8e must extend the receipt reversal pending-draft checks to the Final Settlement drafts. Answer: agreed.

## Q-2026-10-05-24 — Before sub-slice 8c: answer 3 of Q-2026-10-05-23 conflicts with the text of BR-DEP-023 and BR-DEP-026 (ANSWERED 2026-10-05: yes to recommendations 1 to 3; sentence added to BR-DEP-026, pointer in BR-DEP-023, note under PR-DEP-023 in docs/003; 8b and 8e handle the three cases; the same rule for a Pet Deposit kept under BR-DEP-022; answers in docs/010)

You asked me to stop before 8c if answer 3 conflicts with a written rule. I checked docs/002 and docs/010 (read only). Sub-slice 8a-2 does not depend on it, so I continue with 8a-2.

What conflicts:

- **BR-DEP-023** (docs/002): "When voluntary early termination is processed under BR-LEASE-021, the Security Deposit is non-refundable and is resolved through an explicit disposition event." Under answer 3, after a reversed forfeiture the rest of that Security Deposit is refunded at Final Settlement unless a new forfeiture is confirmed.
- **BR-DEP-026** (docs/002): "When the Security Deposit is kept, the whole deposit is forfeited ... and is never used to pay what the Customer owes. ... This applies to voluntary early leaving, termination for unpaid Initial Rent or Security Deposit, ... violation ... and ... the 30-day Rent nonpayment default." The text ties "kept" to the termination ground alone. Under answer 3 the same ground can end in DL-032.
- No conflict with answer 2 of Q-2026-10-05-20 (docs/010): the Security Deposit is kept only where the termination record gives a forfeiture ground and its forfeiture draft is confirmed. Answer 3 fits it.
- Inside answer 3, "as if that forfeiture never happened" could also be read as "the ground still applies, so the Settlement waits for a new forfeiture". The next sentence ("at settlement it follows DL-032 ... unless a new forfeiture draft is confirmed") decides it, so I read it that way.

What the code does today (8a-1): `app.lease_deposit_kept_rule` gives the ground from the termination record only, and `app.post_deposit_application` refuses any application from a Security Deposit with a ground. After a reversed forfeiture that Deposit cannot be applied, and 8b's plan lists "kept Deposit still held without a confirmed forfeiture" as a blocking issue, so it would be stuck. 8b, 8c and 8e must change this (a relaxing change of the 8a-1 check).

Recommendation:

1. Add one sentence to BR-DEP-026 (docs/002), and a pointer in BR-DEP-023: "When a confirmed forfeiture of the Security Deposit is reversed, the Deposit is held again; at Final Settlement it follows DL-032 (it pays open debt and the rest is refunded) unless a new forfeiture draft is confirmed (owner answer to Q-2026-10-05-23)."
2. The three cases in the preview (8b) and the confirm (8e): a ground and no forfeiture ever confirmed is a blocking issue (as planned); a ground with a confirmed, active forfeiture is kept and never applied; a ground whose last forfeiture was reversed follows DL-032, and a pending new forfeiture draft for it is a blocking issue.
3. The same rule for a Pet Deposit kept under BR-DEP-022 (pet noncompliance) whose forfeiture was reversed: it is held again and follows the Pet Deposit steps of DL-032, unless a new forfeiture draft is confirmed.

Please confirm 1 to 3, or say what to change. I will not start 8c, or build 8b's path for this case, before your answer.

Owner answer (2026-10-05): yes to the recommendation. Add the sentence to BR-DEP-026 and its note in docs/003. In 8b and 8e handle the three cases: a forfeiture ground with no confirmed forfeiture blocks the Settlement; an active forfeiture keeps the Deposit; a reversed forfeiture follows DL-032. The same rule applies to a Pet Deposit kept for pet noncompliance whose forfeiture was reversed. Recorded in docs/010.

## Q-2026-10-05-25 — Sub-slice 8b stopped after review round 1: two rule points, one extra blocking issue, and the fixes I plan (ANSWERED 2026-10-05: yes to all four recommendations; make the listed fixes, unit and full PostgreSQL once each, then review round 2; answers in docs/010)

Sub-slice 8b (Final Settlement preview, migration `20261024_89`) is built and green: backend unit 3445 passed (U1), full PostgreSQL 1803 passed (P1); no correction used. Review round 1 (record: ops/reviews/V1-056-slice-08b-settlement-preview.md): independent 2 blockers and 4 should-fix, security 0 blockers and 2 should-fix. Nothing is committed and no fix is made yet; all 8b files are in the working tree.

**Questions (with my recommendation):**

1. (B) **Which cleaning rate decides "cleaning charge missing"?** The plan note says "the Unit's rate in force at the move-out is above zero (or no rate is set)"; the slice 4 command charges the Unit's current rate and refuses a zero rate. They differ only when the rate changes after the move-out. As built (plan text): if the rate at the move-out was above zero and staff later set it to 0, the Settlement stays blocked until a positive rate is set again and charged. Options: (a) keep the plan text; (b) use the current rate, the same rule as the command: the issue shows while no cleaning charge is on an issued, non-VOID Invoice and the current rate is above zero or not set; a rate change after the move-out (audited, with a reason, under `property.manage`) decides. Recommendation: (b), because the plan note's reason is "slice 4 refuses the charge", and only the command can clear the issue.

2. (B) **Remaining Pet Deposit (DL-032 step 5) after a reversed pet-noncompliance forfeiture.** BR-DEP-027 (Customer's choice only) names the unpaid-Initial, non-pet violation and 30-day default terminations; your answer to Q-2026-10-05-24 says that Pet Deposit "follows the Pet Deposit steps of DL-032", and DL-032 step 5 allows the Customer's choice or staff with a reason. I built "Customer's choice only" for it, which no rule says. Recommendation: the staff step (with a reason) is allowed at every termination except the three BR-DEP-027 terminations; this also covers a termination with no forfeiture ground (DL-032, your answer 2 to Q-2026-10-05-20).

3. (B) **Utility periods finalized after the final Utility Invoice.** Migration 73 bills such a period only through the catch-up command. Today the preview can show "ready" while a period of this Lease with consumption is on no Invoice, against BR-SETTLE-011. The plan lists only "final Utility Invoice not issued". Recommendation: one more blocking reason, `UTILITY_PERIOD_NOT_BILLED`, for every period this Lease is responsible for with consumption and no Invoice line, whether or not the final Utility Invoice exists, with a test.

4. **A recorded one-time charge of the Lease on no Invoice.** A Damage or Miscellaneous charge source recorded with `record_one_time_charge` but never put on an Invoice draft is not a blocking issue; the plan lists only an Invoice draft that is not issued (the cleaning charge has its own check). Recommendation: add `ONE_TIME_CHARGE_NOT_INVOICED` for a charge source of the Lease that is on no DRAFT or issued, non-VOID Invoice (BR-SETTLE-003, BR-SETTLE-011), with a test. Not needed if you prefer staff to check this themselves.

**Fixes I will make inside 8b after your answers (no rule change):**

- Independent B1: a Deposit with a forfeiture ground and nothing held is not "forfeiture required" (the forfeiture draft refuses a Deposit that holds nothing, so the Settlement would be blocked for ever; the plan says "still held"); it gets the path `NOTHING_HELD`, is never applied and raises no issue; test: unpaid Security Deposit at a BR-LEASE-005 termination becomes ready.
- Independent B2: the Late-payment check also reads PARTIALLY_PAID Invoices, as the existing review allows; test with a partly paid overdue Invoice.
- Independent S3: tests for a BR-DEP-027 termination and for two Customers (obligations per Customer, Credit bounded to its own Customer); plus the kept-rule error branches and the forfeiture reversal and receipt reversal draft cases of the pending-draft check.
- Security S1: a pending draft stays a blocking issue for everyone, but its id, kind and variant are shown only to a `financial.approve` holder or a holder of that draft's prepare capability (the slice 2 and 6b read rule).
- Security S2: tests for an active service identity and a deactivated person (both refused), and the kept rule in the no-EXECUTE list. The second-Property test cannot exist: V1 stores one Property (`properties_singleton_key_unique`).
- Security N1: the preview runs in a read-only transaction.
- Notes for 8e and 11e go to the plan (8e re-checks every blocking issue under its locks; read error wording).

After the fixes: backend unit and full PostgreSQL once each, then review round 2 under the standing round-3 rule.

Owner answer (2026-10-05): yes to all four recommendations: (1) the current cleaning rate decides; (2) the staff step for the remaining Pet Deposit is allowed everywhere except the three BR-DEP-027 terminations; (3) add UTILITY_PERIOD_NOT_BILLED; (4) add ONE_TIME_CHARGE_NOT_INVOICED. Make the fixes listed above, run unit and full PostgreSQL once each, then review round 2 under the takeover rules. Recorded in docs/010.

## Q-2026-10-05-26 — Sub-slice 8b stopped before review round 2: the known lock failure in a test outside 8b (ANSWERED 2026-10-05: option (a), one more full PostgreSQL run; stop if the same test fails again; slice 12 item to make the test robust against LockNotAvailable without weakening it)

The round-1 fixes and your Q-2026-10-05-25 answers are built. Runs: U2 backend unit 3446 passed. P2 full PostgreSQL: one failure in the new 8b test (its WATER meter used the default unit KWH); corrected (correction 1 of 2). P3 full PostgreSQL: the 8b module passed, 1805 passed, and one test outside 8b failed: `test_refund_migration.py::test_usd_refund_khr_origin_uses_recorded_usd_without_repricing`, `LockNotAvailable` on `app.payment_allocations` from the `NOWAIT` lock in `app.assert_payment_excess_eligible`. That module runs before the 8b module, passed in P1 and P2, and 8b changes nothing on that path; it is the known intermittent failure recorded on 2026-10-02 and 2026-10-03 (likely autovacuum, not proven). The run rules allow no retry without a correction, and takeover section 6 says stop. Record: ops/reviews/V1-056-slice-08b-settlement-preview.md.

Options:
- (a) Allow one more full PostgreSQL run (P4) now, recorded as an owner-approved rerun after an outside intermittent failure; if it is green, start review round 2.
- (b) Accept P2 and P3 together as the evidence (every test passed in at least one of them after the correction, and the only P3 failure is outside 8b) and start review round 2; the full run before round 3 (standing rule) checks again.
- (c) Stop 8b and look into the lock failure first.

Recommendation: (a), because a green full run before the reviews is the clearer evidence and it costs one run of about nine minutes.

Owner answer (2026-10-05): option (a). Run the full PostgreSQL suite once more (P4). Record the P3 lock failure in the review record and docs/010 with the test name and the earlier dates. If that same test fails again, stop and report. If the run is green, start review round 2. Slice 12 item: make `test_usd_refund_khr_origin_uses_recorded_usd_without_repricing` robust against LockNotAvailable, without weakening it.

## Q-2026-10-05-27 — Sub-slice 8b stopped after review round 2: a withdrawn one-time charge blocks the Settlement (ANSWERED 2026-10-05: option (b) plus VOIDed charges listed as information; answers in docs/010)

P4 full PostgreSQL passed (1806). Review round 2: security 0 blockers and 0 should-fix; independent 0 blockers and 2 should-fix. Should-fix 2 (plan text) is fixed. Should-fix 1 needs your rule decision. Record: ops/reviews/V1-056-slice-08b-settlement-preview.md.

**The point.** `ONE_TIME_CHARGE_NOT_INVOICED` (your answer 4 to Q-2026-10-05-25) flags every one-time charge source of the Lease that is on no DRAFT or issued, non-VOID Invoice. Two normal commands leave a source like that on purpose: a draft correction moves an Invoice draft from source A to a replacement source B (recorded as `invoice.draft_corrected` with a reason), and a wrong one-time Invoice is VOIDed with a reason. A charge source can never be cancelled, so today the only way to clear the issue is to bill the wrong charge again and remove it with a credit Adjustment. BR-SETTLE-003 speaks of valid obligations only.

Options:
- (a) Keep it as built; staff clear a withdrawn charge by billing it again and crediting it away with a reason.
- (b) Flag only a source still waiting to be billed: leave out a source whose last Invoice was VOIDed (the VOID has a reason) and a source a recorded draft correction replaced; a test for each. Risk: a VOID meant to be followed by a new Invoice is not flagged, so staff must remember to bill it again.
- (c) Remove `ONE_TIME_CHARGE_NOT_INVOICED`; staff check uncharged sources themselves.

Recommendation: (b).

**After your answer** I would also take these review notes, all tests or defensive changes, no rule change: the BR-LEASE-005 unpaid Security Deposit case with a `ready` assertion and `CUSTOMER_ONLY` at BR-LEASE-005 and BR-LEASE-028; a path-only refusal check; a Payment-source Refund pending draft; the Deposit draft capabilities in the masking test; the empty, NULL-element and over-10 capability inputs; a test that the old 3-argument preview does not exist; `UTILITY_PERIOD_NOT_BILLED` before the final Utility Invoice; the Settlement path counting only dispositions of the Lease; `read_only=None` for commands. Then backend unit and full PostgreSQL once each and round 3 under the standing rule.

Owner answer (2026-10-05): option (b), with one addition. `ONE_TIME_CHARGE_NOT_INVOICED` flags only charges still waiting to be billed; a charge whose last Invoice was VOIDed and a charge a draft correction replaced are left out, and the replacement charge is checked like any other charge. Addition: the preview lists the VOIDed charges that were not billed again as information, not as a blocking issue, so the approver sees them; stop if that needs more than a small additive change. (Implementer note: it did not; one more key, `information`.) Tests: a VOIDed charge does not block but is listed; a replaced charge does not block; its replacement blocks until billed. Reason (BR-SETTLE-003): only valid obligations belong in the Settlement, and a VOID or a draft correction withdraws a charge with a recorded reason. Then the Q-27 review notes, unit and full PostgreSQL once each, and round 3 under the standing rule.

## Q-2026-10-05-28 — Sub-slice 8b round-3 owner item: list replaced one-time charges under `information` too? (ANSWERED 2026-10-05: yes; built in 8c; answer in docs/010)

The 8b round-3 review noted that a draft correction may move an Invoice draft from one one-time charge to a charge of another Lease or with no Lease; such a replaced charge neither blocks the Settlement nor appears in the preview. Question: should 8c or 8e also list replaced charges under the preview's `information` key?

Owner answer (2026-10-05): yes. List a replaced one-time charge under the preview's `information` key too, whether its replacement is on this Lease or on another Lease, and show which charge replaced it. It does not block. Build it in 8c with a test, as a small additive change; stop and report if it needs more than that.

## Q-2026-10-05-29 — Sub-slice 8c stopped after review round 1: two Customer Credit points need the owner (ANSWERED 2026-10-05: (a) to both; answers in docs/010)

Sub-slice 8c (Final Settlement draft, migration `20261025_90`) is built and green: backend unit U2 3450 passed, full PostgreSQL P2 1816 passed (U1 and P1 failed on causes inside 8c and were corrected once each; record: ops/reviews/V1-056-slice-08c-settlement-draft.md). Review round 1: security 0 blockers, 1 should-fix; independent 0 blockers, 4 should-fix, two of which need your rule decision. Nothing is committed; all 8c files are in the working tree. Your answer to Q-2026-10-05-28 is built (replaced one-time charges listed under `information`, with a test) and recorded in docs/010.

**Questions (with my recommendation):**

1. (B) **Customer Credit on an Invoice with Rent or Service lines.** BR-CREDIT-006 and the existing Credit application (migration 41) apply Credit on such an Invoice only by the Rent-first, then recurring-Service proposal, or by a Customer designation; any other line choice is refused ("Rent and Service applications require proposal or designation"). The 8c draft lets staff name any Invoice line for a Credit step, so a draft can be accepted that the confirm (8e) would refuse, or that would need a designation the Customer never gave. Options:
   - (a) Keep the existing rule. On an Invoice with Rent or Service lines, a Credit step names the Invoice and an amount; the draft records the Rent-first proposal split that the existing proposal function gives, and the confirm applies it the same way. Staff may name lines only when the step also records the Customer's designation as text (who, the date, how), like the step 5 choice. Other Invoices (Damage, one-time, cleaning, final Utility) and Late-payment Charges keep the free line choice.
   - (b) At Final Settlement staff choose the lines freely (an exception to BR-CREDIT-006 for the Settlement only; docs/002 amended).
   Recommendation: (a), because it changes no written rule and the confirm can reuse the existing Credit application unchanged.

2. (B) **Must Customer Credit be used when no Deposit pays that Customer's debt?** As built, a Customer's Credit must be used (up to what it may pay) only before a Deposit pays that Customer's obligations (owner answer 3, "Credit before Deposits"). DL-032 step 2 and BR-SETTLE-004 ("apply authorized Customer Credit first") have no such condition. Example: voluntary early leaving, Security Deposit kept, no Pet Deposit, the Customer owes 1,000 and holds 300 of Credit; today an empty draft is accepted and the Settlement would close with 1,000 debt and 300 unused Credit on the same Customer. Credit applications stay open after closure (your answer 7 to Q-2026-10-05-20), so nothing is lost, but the closing balance would be overstated. Options:
   - (a) Each Customer's available Credit must be used, up to what it may pay, whenever that Customer has open Settlement debt (DL-032 step 2 as written).
   - (b) Keep the built rule: Credit is required only before a Deposit pays that Customer's obligations; otherwise staff decide.
   Recommendation: (a), because it follows DL-032 and BR-SETTLE-004 as written and keeps the closing balance true; my docs/010 "choice (2)" would be removed.

**Fixes I will make after your answers (no rule change):**

- Both reviewers: the plan check and the source digest read different snapshots (two statements); compute both in one statement so the stored plan and the source revision describe the same state; 8e must do the same and also compare its recomputed result with the stored one.
- Independent S4: tests for a second Signer (Credit of one Customer refused on another Customer's line; Credit-first per Customer; a Deposit Refund to a signed Signer with the Signers' agreement accepted) and for a Late-payment Charge target; the traceability entry that claims BR-CREDIT-008 is then true.
- Small: a JSON-null `target_kind` is refused as invalid (22023), not as "not an open obligation"; the preview's replacement lookup compares UUIDs (index use); the receipt-wait test's traceability names BR-AUTH-010 and BR-SETTLE-011 only.
- Notes for 8e and slice 12 go to the plan: the confirm takes the Settlement advisory lock, then the per-Deposit advisory and row locks in id order, before writing its decision; it re-runs the preview and the plan check and compares the stored closing balances, not only the digest (the digest does not cover pet-damage classification, Signer status or Refund method state); the 16,000-byte draft limit allows about 90 short steps; an index for `deposit_ids` if drafts grow.

After your answers: the fixes, backend unit and full PostgreSQL once each, then review round 2 under the standing round-3 rule.

Owner answer (2026-10-05): (1) option (a). The draft follows the existing Credit rule BR-CREDIT-006: on an Invoice with Rent or Service lines, Credit follows the Rent-first proposal, or the Customer's designation recorded as text (who, the date, how). No Settlement-only exception; docs/002 stays as it is. (2) option (a). Each Customer's Credit is always used against that Customer's own open debt in this Settlement, up to what it can pay, before any Deposit pays; it is never used for another Customer's debt. A Settlement must not show open debt and unused Credit for the same Customer. Make all the fixes listed above, including reading the plan check and the source digest at the same moment, with a test for a payment arriving in between if one can be written; then unit and full PostgreSQL once each and review round 2 under the standing rules.

## Q-2026-10-05-30 — Sub-slice 8c owner item: choice (4a) in docs/010 (ANSWERED 2026-10-05: rejected; recorded in docs/010; built in sub-slice 8d)

The 8c round-3 review listed choice (4a) for the owner: at a termination where the staff step is allowed, staff could use the remaining Pet Deposit for debt the Security Deposit could also pay and then refund the Security Deposit, because the Refund check looked at the debt left after all chosen applications.

Owner answer (2026-10-05): I reject it. The leftover Pet Deposit may pay only the debt that is still open after the Security Deposit has been used. This follows my words "the rest is refunded; the Customer may choose to use the rest for any remaining balance", and the step order the draft already uses (Security Deposit before the remaining Pet Deposit). The same applies when the Customer chooses it. Build the check first in 8d, with a test: a draft in which the remaining Pet Deposit pays debt that the Security Deposit could still pay is refused, at draft time and in the check that 8e runs again at confirm; stop if this needs more than a small change to the 8c check.

## Q-2026-10-05-31 — Sub-slice 8d stopped after review round 2: three should-fix findings (ANSWERED 2026-10-05: (1) yes, owner exception to the standing round-3 rule, fix 1 per the 8r rule with tests for both orders; (2) yes, docs/002 lines added; (3) the details table is accepted, docs/004 matches; answers in docs/010)

Sub-slice 8d (Final Settlement Deposit Refund source, migration `20261026_91`) is built and green, but not committed; all 8d files are in the working tree. Your answer to choice (4a) (Q-2026-10-05-30) is built first, in the plan check that the draft recorder and the 8e confirm share, with a test. Runs: U1 3451 and U2 3451 backend unit passed; P1 1829 and P2 1831 full PostgreSQL passed; no correction used. Record: ops/reviews/V1-056-slice-08d-settlement-refunds.md.

Review round 1 (security 1 should-fix, independent 3 should-fix) was fixed. The main fix is a check at commit: a Settlement Refund commits only when its draft is CONFIRMED under `financial.approve` by the same approver. Round 2 confirmed every round-1 fix but found three new should-fix items. The standing rule allows round 3 only with at most two, so I stopped.

**The three findings (none can move money today, because the writer is internal and 8e is not built):**

1. **(Security SF-A) A pending receipt reversal or forfeiture draft is not seen by a later Refund.** The commit check accepts a confirmation made in an earlier transaction. A receipt reversal draft recorded after that confirmation would not stop a later Refund of the same Deposit (your answer 4 to Q-2026-10-05-23 says they wait for each other). A new forfeiture draft for a Deposit whose forfeiture was reversed is not seen either. My round-1 written answer said the opposite; it was wrong.
2. **(Security SF-B) The commit check's own conditions have no test of their own.** The tests refuse rejected, withdrawn and other-approver drafts earlier, in the source check. No test writes the confirmation in the same transaction as the Refund.
3. **(Independent SF1) The writer fails after the existing Credit application.** `app.post_credit_application` ends with `SET CONSTRAINTS ALL IMMEDIATE`, and that setting stays for the rest of the transaction. The plan has 8e apply the Credit steps through that function and then call the Refund writer. The writer's details row relies on two deferred checks, so even a valid confirmed draft would fail. It fails safe, but 8e could not use the writer as planned.

**Fixes I would make (no rule change):**

- For 1: the Refund source check refuses (55000) while any pending `DEPOSIT_FORFEITURE` draft (forfeiture, forfeiture reversal or receipt reversal) exists for that Deposit, with a test. The recorders take the same Deposit row lock, so READ COMMITTED serializes them. (Correction, 8d review round 3: the forfeiture and forfeiture-reversal recorders take the per-Deposit advisory lock, not the row lock; the Refund check takes that lock too, so READ COMMITTED still serializes them.) I correct the round-1 answer.
- For 2: two single-transaction tests. A Refund followed by the same approver's confirmation commits. A Refund followed by another approver's confirmation is refused at commit (42501) and writes nothing.
- For 3: the writer sets its two deferred checks (the Refund key of the details row and the confirmation check) back to DEFERRED before it writes, as migration 83 already does with `SET CONSTRAINTS ALL DEFERRED`. This only moves those checks to commit. A test runs `SET CONSTRAINTS ALL IMMEDIATE`, then the writer, then the confirmation, in one transaction.
- Notes I would take as well (tests and docs only):
  - tests for a kept Deposit, a Deposit of another Lease and the writer's input refusals;
  - the least-privilege list gains the details trigger function;
  - the 8c entry in docs/010 marks choice (4a) as rejected;
  - an 8e note on lock order (the Settlement advisory lock first, or the Settlement row before the Deposit rows).

**Question:**

(a) Do you want a docs/002 line for your answer to Q-2026-10-05-30, as the answers to Q-21 and Q-24 have? It would be added under BR-SETTLE-005 and BR-SETTLE-017: "Amended by the owner answer to Q-2026-10-05-30 (2026-10-05): the remaining Pet Deposit pays only debt still open after the Security Deposit has been used, also when the Customer chooses it." Or should docs/002 stay unchanged, with docs/010 saying so? Recommendation: add the line, because BR-SETTLE-006 ("no inferred order between Deposit types") otherwise reads as if staff may choose that order.

**Recommendation:** allow the fixes and notes above, then backend unit and full PostgreSQL once each, then one round 3 under the standing rule (no should-fix, or I stop again).

Owner answer (2026-10-05): (1) Yes, as an owner exception to the standing round-3 rule. Make the three fixes and the notes listed in Q-31. For fix 1: a Refund must be refused while a Deposit receipt reversal draft or a forfeiture draft is pending for the same Deposit, even when that draft was recorded after the Settlement draft was confirmed. This is my 8r rule. Add tests for both orders. Correct your round-1 written answer in the review record. Then run backend unit and full PostgreSQL once each, then one round 3. Round 3 must have no blocker and no should-fix, or stop and tell me. (2) Yes. Add the "Amended by the owner answer to Q-2026-10-05-30" line under BR-SETTLE-005 and BR-SETTLE-017 in docs/002. (3) The new table app.final_settlement_refund_details is accepted instead of a refunds.final_settlement_id column. Update docs/004 to match. Next time a design differs from docs/004 or the plan, ask me first.

## Q-2026-10-06-32 — Sub-slice 8e: the Credit steps cannot go through the existing Credit application function as the plan says, and three smaller design points (ANSWERED 2026-10-06: yes to recommendations 1 to 4; answers in docs/010)

Sub-slice 8e (confirm and close) is split into 8e-1 (refusals after closure), 8e-2 (Settlement Credit application writer) and 8e-3 (confirm and close); the split, the 8e notes and the path search are in ops/V1_056_PLAN.md ("8e pre-code review"). No 8e code is written. 8e-1 does not depend on this question, so I continue with 8e-1, as I did with 8a-2 while Q-2026-10-05-24 was open. 8e-2 and 8e-3 wait for your answers, because your rule says to ask first when a design differs from docs/004 or the plan.

**What the plan says and why it cannot be built that way.** The 8e entry says the confirm applies the Credit steps "through the existing Credit application function (its `final_settlement_id` check relaxed to accept the Settlement)". The existing function, `app.post_credit_application` (migration 41, granted to the financial role for the one-call `credits.apply` command):

- has no parameter for the Settlement, so the rows it writes always have `final_settlement_id` NULL; giving it one would let every one-call Credit command name a Settlement;
- has no way to write the existing basis `OTHER_APPLICABLE_OBLIGATION` with `OTHER_CONFIRMED` details, which a Credit step needs on an Invoice without Rent or Service lines (a Damage, one-time, cleaning or final Utility Invoice) when the Customer did not designate the line; its proposal mode fills that Invoice's lines in line order, not the line staff chose (plan note from the 8c review);
- records `credits.apply` and writes a replay row in `app.credit_commands`.

docs/004 DB-CREDIT-002 already describes `final_settlement_id` as a nullable foreign key on the Credit application header; today a CHECK keeps it NULL.

**Questions (with my recommendation):**

1. (B) **How the Settlement writes its Credit applications.**
   - (a) One internal writer for Settlement Credit applications (no grant; only the confirm calls it), like the Deposit application writer (8a) and the Settlement Refund writer (8d). It writes the same header and detail rows the existing function writes: the Rent-first proposal (`RENT_THEN_RECURRING_SERVICES_PROPOSAL`, proposal trace from the existing `app.credit_application_proposal`), the Customer's designation (`CUSTOMER_DESIGNATED`, the step's text), a direct Late-payment Charge (`NOT_APPLICABLE`), and `OTHER_APPLICABLE_OBLIGATION` with `OTHER_CONFIRMED` details on an Invoice without Rent or Service lines. It sets `final_settlement_id`; the CHECK that keeps it NULL becomes a foreign key to `app.final_settlements` (a relaxing change; earlier rows stay NULL). Every existing Credit trigger runs unchanged: same Customer, available Credit, target balance, chronology, reconciliation, history budget and audit. A deferred check, as in 8d, lets a Settlement Credit application commit only with its draft confirmed by the same approver under `financial.approve`.
   - (b) Use `app.post_credit_application` unchanged for the proposal, designated and direct Charge steps (the approver recorded with `credits.apply`, as the slice 7 move rows record `payments.allocate`), keep the Settlement link in a separate link table, and add an internal writer only for `OTHER_APPLICABLE_OBLIGATION`. `final_settlement_id` stays NULL and docs/004 changes. Two paths for one kind of step.
   Recommendation: (a), because one path keeps every Settlement Credit application linked to its Settlement in the place docs/004 already names, and the existing checks still run on every row.

2. (B) **The authorization reference on a Settlement Credit application.** (a) `financial.approve`, allowed only on a row with a `final_settlement_id` (the CHECK `authorization_reference='credits.apply'` relaxed for that case only), like the Deposit applications and Settlement Refunds, which only the confirm writes; (b) `credits.apply` with the approver as actor, which the approver may not hold (the slice 12 owner item on approver naming already lists the slice 6, 6b and 7 rows that do this). Recommendation: (a).

3. (B) **A one-call reversal of a Credit application the Settlement made.** Your answer 7 to Q-2026-10-05-20 keeps "Payments, allocations, Credit applications and their ordinary reversals" open after closure, so the Customer can still pay the debt. A Credit application written by the Settlement is part of the closed Settlement: BR-SETTLE-012 makes its application order and result permanent, and BR-SETTLE-013 (amended by DL-068) puts a later fix into a post-settlement correction. Without a new check, a holder of `credits.applications.reverse` could reverse it with one call and no approver; the Credit returns to the same Customer and the debt reopens (no money leaves). Options: (a) refuse the one-call reversal of a Credit application that has a `final_settlement_id` (only rows no writer could create before, so not a tightening); Credit applications made after closure, and their reversals, stay open; a fix waits for the post-settlement corrections (slice 10, plan Q15: an application reversal waits for a later owner decision); (b) allow it as an ordinary reversal. Recommendation: (a), for the same reason as your answer to Q-2026-10-04-13 (an approver's decision is not undone by one person alone).

4. **The key of the closure line snapshot (DB-SETTLE-006).** docs/004 gives `settlement_invoice_line_items` a foreign key `settlement_invoice_item_id`, but DB-SETTLE-002 gives `settlement_invoice_items` only the primary key `(final_settlement_id, invoice_id)` and no `id`. Options: (a) add `id uuid NOT NULL UNIQUE` to `settlement_invoice_items` and keep its primary key, so DB-SETTLE-006 stays as written; (b) DB-SETTLE-006 refers to `(final_settlement_id, invoice_id)` instead. Recommendation: (a); docs/004 gains the one column.

**What I will do unless you say otherwise (within docs/004 and the plan):** the closure snapshots are written at the confirm after every Settlement Credit application, Deposit application and Refund, so `outstanding_at_inclusion_usd_cents` is the outstanding amount at closure and the snapshot rows add up to `closing_balance_due_usd_cents`; they list every issued, non-VOID Invoice of the Lease (whoever is named on it) and every Late-payment Charge of those Invoices, paid ones included with 0; `included_by` is the approver and `included_at` the closure time.

After your answers I build 8e-2 and then 8e-3 under the run rule and the standing round-3 rule, and I record the answers in docs/010.

Owner answer (2026-10-06): (1) yes, build a new internal writer for the Settlement's Credit applications instead of using the existing function; it follows the same Credit rules (BR-CREDIT-006, Q-2026-10-05-29), records the Settlement link, and has no grant to any role, like the 8d Refund writer. (2) These Credit applications record the Settlement's `financial.approve` confirmation as their authorization. (3) No: a Credit application made by the Settlement cannot be reversed with one call after closure; corrections wait for the slice 10 correction drafts (answer 7 to Q-2026-10-05-20). (4) The key of the line-level closure records: the recommendation, as a technical choice (`id uuid NOT NULL UNIQUE` on `settlement_invoice_items`, its primary key kept). Stop and show the owner before building 8e-2 if the recommendation differs from these answers (implementer note: it does not; recommendations 1 to 4 are exactly these answers).

## Q-2026-10-06-33 — Sub-slice 8e-1 stopped after review round 1: a billing run that meets a closed Settlement can never succeed (ANSWERED 2026-10-06: (b), the run skips a closed Lease and closure waits for every Rent month; a draft VOID stays refused and closure waits for every draft; answers in docs/010)

Sub-slice 8e-1 (refusals after a Final Settlement closes, migration `20261027_92`) is built and green: backend unit U1 3454 passed, full PostgreSQL P1 1839 passed, no correction used. Review round 1 (record: ops/reviews/V1-056-slice-08e1-closed-refusals.md): both reviewers found the same blocker, which I can fix inside the sub-slice; the security reviewer also found one point that only you can settle. Nothing of 8e-1 is committed and no fix is made yet; all 8e-1 files are in the working tree. Q-2026-10-06-32 (8e-2 and 8e-3) is still open.

**The point (security S1, verified by reading the code).** The refusal is a database error, `P5S01`. A scheduled Rent run (or Utility run) catches an item's error and records the item as `ERROR` (`RENT_PERSISTENCE_P5S01`); the run attempt then ends `FAILED` (`ITEM_FAILURE`), and only a later item that is `GENERATED` or `SKIPPED` clears it, so every retry fails again. `app.void_invoice` refuses a run-generated Rent Invoice until its run has SUCCEEDED, so one closed Lease in a run blocks VOID (and the hand-back resolution) for every other Lease's Rent Invoice of that run, with no way out short of a code change. A run meets a closed Lease when a full Rent month inside the Lease's coverage (up to its actual termination date) has no active Rent Invoice: for example a month whose Rent Invoice staff VOIDed to bill it again, or a month a run never billed. The preview has no blocking issue for such a month, so the Settlement can close with it; the 8e plan said the run records `ERROR` "and continues", which hides this.

**Questions (with my recommendation):**

1. (B) **How a billing run treats a Lease whose Final Settlement is closed.**
   - (a) The scheduled Rent and Utility run items check first and record such a Lease as `SKIPPED` with a new diagnostic code `FINAL_SETTLEMENT_CLOSED` (no Invoice), so the run can succeed; the one-call Rent generator and every other writer keep the `P5S01` refusal (a conflict). This is a relaxing change of the run item's allowed outcome codes and of the two item functions (migration 35 bodies patched in a new migration, as earlier slices did); a test runs a Rent run with the closed Lease and another Lease and checks `SKIPPED`, `GENERATED` and a SUCCEEDED run.
   - (b) As (a), and in addition the preview gets a blocking issue `RENT_PERIOD_NOT_BILLED` for a full month inside the Lease's coverage with no active Rent Invoice, so a Settlement cannot close while a Rent month is still to be billed (BR-SETTLE-011: closure waits until every valid final charge is determined). This refuses drafts and confirms that 8c accepts today, so it is a tightening; I would build it in 8e-3 with the confirm's re-check.
   - (c) Keep `ERROR` (the run fails for good; not recommended).
   Recommendation: (b). Without the blocking issue, a forgotten Rent month is silently lost at closure and can only come back as a slice 10 extra charge.

2. **A VOID of a DRAFT Invoice of a closed Lease is refused too** (security note N1). A draft is not an obligation, so this goes slightly beyond your answer 7. Once B1 is fixed (below) and the confirm (8e-3) blocks closure while an Invoice draft of the Lease exists (`INVOICE_DRAFT_NOT_ISSUED`), no such draft can exist, so the refusal can never be met. Recommendation: accept it as built (the safe side) and record it in docs/010; the alternative is to let a DRAFT be VOIDed after closure.

**Fixes I will make after your answers (no rule change):**

- Blocker B1 (both reviewers): the guard is BEFORE INSERT only, but `app.correct_invoice_draft` (`PATCH /invoices/{invoice_id}`) can move an Invoice draft onto a charge of the closed Lease (a charge whose Invoice was VOIDed before closure, or one a draft correction replaced) and `app.issue_invoice` (`POST /invoices/{invoice_id}/issue`) then issues it by UPDATE: a new charge on the closed Lease with one-call routes. Fix: the same guard also BEFORE UPDATE OF `lease_id`, `status` on `app.invoices`, when the row gets a closed Lease or a DRAFT of a closed Lease is issued; a DRAFT may still become VOID (subject to point 2). Tests: the correction onto the closed Lease's charge and the issue of a draft made before closure are refused as a conflict and write nothing.
- Test gaps (independent S1, security S2): a scheduled Rent run item after closure (point 1), one final or catch-up Utility Invoice through its service, a VOID and an Adjustment that still work while the Settlement is open (the branch that locks the target Invoice), a Payment reversal after closure; for the paths that only reach the guarded tables (hand-back, moved-in credit, cleaning, Damage, a draft naming another Signer) the plan's 8e-1 entry and the docs say plainly that the table-level tests and the service mappings prove them, and are not tested one by one.
- Security N4: `app.late_payment_charges` is guarded too (defense in depth).
- Wording: docs/005 (the PATCH and issue routes; no "continues" claim), docs/010 ("a later writer cannot miss it" holds for INSERT and the guarded UPDATE only), the two-connection test's docstring (independent N4).
- Notes for later sub-slices, added to the plan with your answer: 8e-3 locks every Late-payment Charge before its source Invoice and the Invoices `FOR NO KEY UPDATE`, and maps 40P01 and 55P03 to a conflict (independent N1, security N2); slice 10's correction writers pass the guard only through a linked correction row checked in the same transaction, never through a session setting (independent N2, security N3); 11e shows a stable reason for `P5S01` and the Late-payment 409 does not show `eligible: true` (independent N3, security N5); charges with no Lease for the former tenant stay open after closure, outside answer 7 (security N5, for your information).

After your answers: the fixes, backend unit and full PostgreSQL once each, then review round 2 under the standing round-3 rule.

Owner answer (2026-10-06): (1) yes, a billing run skips a closed Lease with a new reason code; add a test that a VOID on an open Lease is never refused because another Lease in the same run is closed. (2) Yes, closure is blocked while a Rent month of the Lease is still unbilled (option (b); built in 8e-3 with the confirm's re-check, as recommended). (3) Yes, keep refusing a VOID of a draft Invoice on a closed Lease; also block closure while the Lease has any draft Invoice, so no draft can be stuck after closure (implementer note: the preview's `INVOICE_DRAFT_NOT_ISSUED`, built in 8b, already blocks the draft and the confirm for every DRAFT with the Lease, whoever is named on it; 8e-3 checks it again under its locks, and the 8e-1 guard on Invoice updates keeps any draft from gaining the Lease after closure). Record all answers in docs/010 and here, add the round-1 notes to the plan, then fix the round-1 blocker (test exactly the path of a corrected draft pointing at a closed Lease's charge and then issued), the should-fix items and the test gaps; backend unit and full PostgreSQL once each, then review round 2 under the standing rules.

## Q-2026-10-06-34 — Sub-slice 8e-3 stopped before code: the new Rent-month blocking issue conflicts with the BR-RENT-030 hand-back VOID (ANSWERED 2026-10-06: leave it out, the recommendation; answer in docs/010)

Sub-slice 8e-3 (confirm and close) is not started; no code is written and no run was made. Before 8e-3 I moved the two untracked run outputs to `~/Development/prm-run-logs/`, added the slice 10 item for a bounced Payment, and added your two rules to ops/V1_055_RUN_RULES.md (migration check before each full PostgreSQL run; large outputs). The design review of 8e-3 found one conflict.

**What your answer says.** Answer 2 to Q-2026-10-06-33: closure is blocked while a Rent month of the Lease is still unbilled, built as the preview blocking issue `RENT_PERIOD_NOT_BILLED` "for a full month inside the Lease's coverage with no active Rent Invoice". I would build it with the rule the Rent billing run already uses (`app.lease_is_billable_for_recurring_period`): every recurring month that a Rent run would bill, with no non-VOID Rent Invoice of the Lease covering it. That is exactly the case that made a run fail in 8e-1.

**The conflict (verified by reading the code).** BR-RENT-030 (slice 5): after a verified voluntary early hand-back before the 5th, staff VOID the unpaid hand-back-month Rent Invoice (and, after the 25th, the next month's). In that case the Lease is terminated under BR-LEASE-021 in the hand-back month, so the billing rule still counts that month as billable (the early final month, BR-RENT-024). Example: hand-back and termination on 3 August, the August Rent Invoice VOIDed under BR-RENT-030. Built literally, `RENT_PERIOD_NOT_BILLED` would show August forever: the Settlement could only close if staff billed August again, which charges the Rent that BR-RENT-030 removed (and the hand-back rule could VOID the new Invoice again).

**Recommendation.** A month whose Rent Invoice was VOIDed by a BR-RENT-030 hand-back resolution (`app.hand_back_rent_resolutions`, action VOID) is not "still unbilled": its Rent was decided under BR-RENT-030. `RENT_PERIOD_NOT_BILLED` leaves it out. Every other month that a Rent run would bill and that has no active Rent Invoice blocks, including a month whose Invoice staff VOIDed for any other reason. Only recurring months are checked (the Initial Rent period is billed by its own command and is not a run month). The confirm checks it again under its locks.

**For your information (not part of 8e-3).** Before a Settlement closes, nothing stops a later Rent generation for a hand-back month VOIDed under BR-RENT-030, because the billing rule still counts it as billable. I would add this to the slice 12 list.

Please confirm the recommendation or say what to change. Nothing else in 8e-3 is unclear; the rest follows the plan notes.

Owner answer (2026-10-06): leave it out, as recommended. A month whose Rent Invoice was VOIDed by a BR-RENT-030 hand-back resolution does not block; every other month a Rent run would bill with no active Rent Invoice blocks, including a month VOIDed for any other reason; recurring months only.

Owner follow-up (2026-10-06, after the 8e-3 report): leave it out, as recommended. The answer also covers next month's Rent Invoice VOIDed by the hand-back resolution when the Customer leaves between the 25th and the month end (slice 5). A month VOIDed for any other reason still blocks. A test for both cases. Built as two tests after commit 660f83e: the existing rule already matches every month whose Rent Invoice a hand-back resolution VOIDed, whatever its coverage, so no code changed.

## Q-2026-10-06-35 — Found in sub-slice 8f review round 1 (not blocking 8f): a third-party Payment's adjustment Credit can still go back to the payer through the one-call Credit reversal (ANSWERED 2026-10-06: yes, the tightening is approved for every Credit that 8f covers, with tests, as sub-slice 8g; answers in docs/010)

Sub-slice 8f (Credit Refund to the Invoice Customer who is not the payer, migration `20261030_95`) does not depend on this question: its code and tests stay the same whatever the answer, so I continue 8f under the standing rules, as with Q-2026-10-04-10 in slice 5. The security reviewer found an earlier path (not created by 8f), and I verified it by reading the code.

**The path.** A third-party Payment (payer X) pays Customer A's Invoice. A credit Adjustment on that Invoice releases 5,000 as A's Customer Credit (BR-CREDIT-014: it belongs to A, and any Refund of it goes to A). A holder of `credits.reverse` can reverse that Credit with one call (`app.reverse_customer_credit`): the Credit reversal refusal of slice 7 (`customer_credit_reversals_moved_payment`, P4904) applies only to a Credit released from a moved (`WRONG_UNIT_MOVE`) allocation. The 5,000 then becomes unallocated value on X's Payment again, and an ordinary Payment Refund draft can pay it to X once the identified Lease or Invoice owes nothing (a `financial.approve` holder confirms it, but it looks like an ordinary Payment Refund). Since migration 67 (third-party credit Adjustments) this path existed; slice 7 closed it only for moved allocations. It conflicts with BR-CREDIT-014 and BR-CREDIT-008 (Credit is not transferred to another Customer). No money leaves without an approver.

**Recommendation.** Refuse the one-call Credit reversal of every Credit that a credit Adjustment released to a Customer other than the payer (`app.credit_customer_refund_basis(credit) IS NOT NULL`, the same P4904 refusal, reported as a conflict), with a test; such a Credit can then only be applied to its Customer's obligations or refunded to its Customer (8f). This refuses input accepted today (a tightening), so it needs your answer; I would build it as its own small sub-slice after 8f (for example 8g), or in slice 10 with the post-settlement corrections. Alternative: keep the path and record it as a slice 12 item.

**Owner answer (2026-10-06).** Yes. Refuse the one-call reversal for every Credit that 8f covers (an adjustment Credit released to a Customer who did not make the Payment), with tests; it follows BR-CREDIT-014 and the owner answer to slice 7. Build it as sub-slice 8g. Record the answer in docs/010 and here. In 8g, also say how staff can fix such a Credit when the credit Adjustment itself was a mistake; if no draft-based way exists, add one to the slice 10 plan. Built in sub-slice 8g (migration `20261031_96`); the mistaken credit Adjustment is in the plan's slice 10 entry.

## Q-2026-10-06-36 — Slice 10 design: the correction kinds, the DB-SETTLE-005 links, and paths that still change a closed Settlement's money (ANSWERED 2026-10-06: yes to points 1 to 7, with a clear fix for an unpaid wrong charge, the wrong-Unit fix after closure and DL-032 for a forfeiture reversal after closure; answers in docs/010)

Slice 10 is designed only (ops/V1_056_PLAN.md, "Slice 10 design note"); no code. I checked the design against your rules: a Settlement is never reopened (no correction changes the Settlement row, its snapshots or the records its confirm wrote); every later fix is a new linked correction with a reason (header DB-SETTLE-003, typed effect links DB-SETTLE-005); the same approvers (Staff prepare under `final_settlements.prepare`, only `financial.approve` confirms); no time limit (no age check). Seven points need you.

1. **The two kinds (extra charge, Refund) do not cover your own slice 10 items.** (a) A bounced Payment whose Credit or Deposit the Settlement used needs the Settlement's Credit application or Deposit application reversed before the Payment can be reversed; plan Q15 left those reversals for a later decision. (b) A wrong charge still unpaid after closure needs only a reduction (credit Adjustment), no Refund. (c) A paid wrong charge needs its value released (credit Adjustment, and for a Deposit-paid charge a Deposit application reversal) before a Refund can pay it, because every Refund needs a source with available value. (d) The mistaken credit Adjustment reversal you asked for in 8g is an Adjustment reversal. **Recommendation:** four correction kinds: `EXTRA_CHARGE`; `REFUND` (credit Adjustment, release, linked Refund; reduction only when unpaid; also a returned Settlement Refund); `RETURNED_PAYMENT` (reverse the Settlement's applications and the Payment's allocations funded by that Payment, then the Payment; debt returns to the original obligations; a Settlement Refund already paid from a Deposit that Payment funded becomes an extra charge to the Deposit owner in the same correction); `ADJUSTMENT_REVERSAL`.
2. **DB-SETTLE-005 (docs/004) lacks links the kinds need.** It has no link for a new charge Invoice, a Payment reversal, a Credit reversal or a Deposit receipt reversal, and it names `deposit_application_reversal_id` for a table that does not exist. **Recommendation:** amend DB-SETTLE-005 to add `invoice_id` (the extra charge Invoice), `payment_reversal_id`, `customer_credit_reversal_id`, `deposit_receipt_reversal_id`, and add a new append-only table `deposit_application_reversals` (written only by a correction); "exactly one FK per row" stays.
3. **One-call paths still change a closed Settlement's money without a draft or an approver** (read-only search, design note): the allocation reversal (`POST /payment-allocations/{allocation_id}/reverse`) and the Credit application reversal (`POST /credit-applications/{application_id}/reverse`) of a record that paid a Settlement obligation before closure bring the debt back and free the value; the Payment reversal then follows. Your answer 7 to Q-2026-10-05-20 kept them open so the Customer can pay the debt. **Recommendation (a tightening):** after closure, refuse these two reversals for allocations and Credit applications that existed at closure on the Settlement's obligations; they change only through a correction (`RETURNED_PAYMENT` or `REFUND`). Allocations and Credit applications made after closure stay reversible. Built last (10f), after `RETURNED_PAYMENT`, so a returned Payment always has a path.
4. **Two draft paths have an approver but no link to the Settlement:** a wrong-Unit Payment move of an allocation that paid a Settlement obligation before closure (reopens that debt), and the reversal of a kept Deposit's forfeiture after closure (the Deposit holds money again, and the closed Settlement can neither apply nor refund it). **Recommendation (a tightening):** after closure refuse the move for such an allocation, and allow the forfeiture reversal only inside a `REFUND` correction that refunds the Deposit in the same transaction (one more DB-SETTLE-005 link, `deposit_disposition_reversal_id`, already listed).
5. **The lasting blocks outside a Settlement** (slice 7 and 8g): a Payment with a moved-value Credit of another Customer, or a third-party Payment with an adjustment Credit of the Invoice Customer, can never be reversed today. **Recommendation:** build the `RETURNED_PAYMENT` mechanism in 10d so it also works for a Payment with no closed Settlement (a draft confirmed by `financial.approve`), which ends both blocks; otherwise they stay slice 12 items.
6. **Extra charge details.** **Recommendation:** the charge goes to the Customer of the obligation it corrects, or to the Primary Tenant when it corrects nothing on an Invoice (BR-SETTLE-016); an existing one-time category; Due Date = issue date + Property due-days with the existing override; no Late-payment Charge on a correction Invoice (the 8e-1 refusal of Late-payment Decisions after closure stays, nothing automatic).
7. **Who prepares the mistaken credit Adjustment reversal.** The 8g plan text says an `invoices.adjust` holder. **Recommendation:** `invoices.adjust` before closure (an ordinary draft), `final_settlements.prepare` after closure (inside a correction); `financial.approve` confirms both.

Until you answer, no slice 10 code. If you approve, I would build 10a first (record and draft, no effect kind), then 10b to 10f in the order of the design note.

**Owner answer (2026-10-06).**

1. Yes, four correction kinds: extra charge, Refund, returned Payment, Adjustment reversal. Also make sure a wrong charge that is still unpaid has a clear fix; if none of the four kinds covers it, add a fifth kind that removes the wrong amount with a credit Adjustment, as a draft. Every kind needs a reason. Staff prepare it, and only a `financial.approve` holder confirms it.
2. Yes. The new link columns and the Deposit application reversal table are approved. Update docs/004 to match.
3. Yes, this tightening is approved. After closure, refuse the one-call reversal of a Payment allocation or a Credit application that existed at closure. Fixes then go through the slice 10 corrections.
4. Yes. Refuse the wrong-Unit Payment move after closure for such an allocation; the design note says how staff fix a real wrong-Unit case after closure. A forfeiture reversal after closure is allowed only inside a correction, which follows DL-032 as answered after 8r and in Q-2026-10-05-24: the Deposit first pays this Lease's debt that is still open, and only the rest is refunded; if that needs a Deposit application inside the correction, include it.
5. Yes. The returned-Payment draft also works with no Settlement and must end the slice 7 and 8g blocks. Test it with a returned third-party Payment whose adjustment Credit was released to another Customer.
6. Yes, no Late-payment Charge on a correction Invoice. Who the extra charge goes to, its category and its Due Date: the recommendations, if they follow the earlier rules (a Signer's own debt stays on the Signer's ledger; other Lease debt goes to the Primary Tenant); otherwise stop and show the owner.
7. Yes. `invoices.adjust` prepares the Adjustment reversal before closure and `final_settlements.prepare` after closure; only a `financial.approve` holder confirms it, in both cases.

Agent check of answer 6 before use: the recommendations follow those rules (docs/010). Recorded in docs/010; the slice 10 design note is updated. Follow-up points that do not block 10a are in Q-2026-10-06-37.

## Q-2026-10-06-37 — Slice 10 follow-up points from the owner answers to Q-2026-10-06-36 (not blocking 10a) (ANSWERED 2026-10-07: yes to points 1 to 5, with one condition on point 5; answers in docs/010)

None of these points changes 10a (the correction record and its passage through the closed-Settlement refusals), so I build 10a now under the standing rules. Each point blocks only the sub-slice named in it.

1. **Two more correction variants** (blocks 10d and 10g). Your answer 4 needs a forfeiture reversal inside a correction, and a fix for a real wrong-Unit case after closure. **Recommendation:** variant `FORFEITURE_REVERSAL` (the reversal, Deposit applications to this Lease's open debt in the DL-032 order, then the Deposit Refund of the rest) and variant `PAYMENT_MOVE` (the slice 7 move, with both Customers' confirmation text, inside a correction of the Settlement whose obligation the wrong allocation paid). Both prepared under `final_settlements.prepare` and confirmed by `financial.approve`, like the other variants.
2. **The returned-Payment record when there is no Settlement** (blocks 10e). docs/004 has no record for it. **Recommendation:** a new append-only table `payment_returns` (one row per returned Payment: the Payment, the draft, the reason, the approver, `financial.approve`, and the Settlement correction when there is one). The slice 7 and 8g refusals and the 8e-2 refusal accept a reversal only when such a row for that Payment was written earlier in the same transaction by the internal writer (never a session setting). docs/004 gains the table.
3. **Who prepares a returned-Payment draft with no Settlement** (blocks 10e). **Recommendation:** `payments.reverse` (the existing Payment reversal capability), as a new draft kind `PAYMENT_RETURN`; with a closed Settlement it is the `RETURNED_PAYMENT` variant under `final_settlements.prepare`. `financial.approve` confirms both.
4. **One more link for the extra charge** (blocks 10b). A one-time charge is first recorded as a one-time charge record (`authorized_nonrecurring_obligations`, migration 65) and then billed on its Invoice; the 8e-1 refusal guards that record too, and DB-SETTLE-005 has no link for it, so an extra charge with the Lease cannot pass. **Recommendation:** add the link `authorized_nonrecurring_obligation_id` to DB-SETTLE-005 in 10b (the same kind of link as the approved ones).
5. **DB-SETTLE-005 context of a linked record** (blocks 10e and 10g). docs/004 says each effect's "Customer/Lease/source context and correlation must match the Settlement correction". Two approved fixes write records of another Lease: the wrong-Unit fix allocates the Payment to the correct Invoice of another Lease (your answer 4), and a returned Payment must reverse all its allocations, Credits and receipts, also those on other Leases, before the Payment can be reversed (your answer 5). 10a does not check context in the table: each variant writer will check it. **Recommendation:** every linked record must belong to the Settlement's Lease, except the correct Invoice's new allocation in a wrong-Unit fix and the returned Payment's own records (its allocations, Credit applications, Credits, Deposit receipts and its reversal); docs/004 says so.
6. **For your information, no answer needed:** the Adjustment reversal before closure needs a new draft kind `ADJUSTMENT_REVERSAL` with the preparer `invoices.adjust` (your answer 7; a relaxing change of the draft kind check in 10f). In 10a the header's `correlation_id` (DB-SETTLE-003) is the draft id, and "a correction years after closure" cannot be run as a test (every writer stamps the database clock), so 10a shows it by checking that the only time checks are "not before the closure" and "not later than the clock plus 5 seconds".

**Owner answer (2026-10-07).**

1. Yes. `FORFEITURE_REVERSAL` and `PAYMENT_MOVE` are correction kinds.
2. Yes. A new append-only table `payment_returns` for a returned Payment with no Settlement. Update docs/004 to match.
3. Yes. `payments.reverse` prepares it as a new draft kind `PAYMENT_RETURN`. Only a `financial.approve` holder confirms it.
4. Yes. Add the one-time charge link (`authorized_nonrecurring_obligation_id`) for the extra charge.
5. Yes, allow exactly these two exceptions to the same-Lease rule: the wrong-Unit move paying another Lease's Invoice, and a returned Payment reversing records on other Leases. One condition: neither may change a record that another Lease's closed Settlement relied on, unless that change is also a confirmed correction of that Settlement. Test it. If this is hard to build, write the case in ops/V1_056_QUESTIONS.md with your recommendation and stop.

Recorded in docs/010; docs/004 DB-SETTLE-005 amended and DB-PAY-009 (`payment_returns`) added. Point 4 is built in sub-slice 10b; points 1, 2, 3 and 5 in 10d, 10e and 10g.

## Q-2026-10-07-38 — Sub-slice 10c: a wrong Late-payment Charge after closure has no fix (not blocking 10c-1a or 10c-1b) (ANSWERED 2026-10-07: yes, sub-slice 10c-3; answers in docs/010)

Your answer 1 to Q-2026-10-06-36 asks for a clear fix for a wrong charge that is still unpaid, and the design note builds `CHARGE_REDUCTION` and `REFUND` as a linked credit Adjustment. A credit Adjustment exists only on an Invoice line. A Late-payment Charge is a separate obligation of the Settlement (DL-069, owner answer 1 to Q-2026-10-05-20); it is corrected only by a Late-payment Charge correction (`app.correct_late_payment_charge`: `REDUCTION`, `CHARGE_REVERSAL`), which the 8e-1 refusal stops after closure. That command never releases paid value: it refuses a result below the Charge's active applications ("Active applications require explicit reversal", P4608). So today a wrong Late-payment Charge after closure has no fix at all, paid or unpaid. The 10a migration already lets a linked Late-payment Charge correction through the 8e-1 refusal, and DB-SETTLE-005 already has the link `late_payment_charge_correction_id`.

**Recommendation:** (a) `CHARGE_REDUCTION` also takes a Late-payment Charge of the Settlement: a linked `REDUCTION` correction of at most its unpaid rest. (b) `REFUND` also takes a paid Late-payment Charge: the correction reverses, as linked records, the allocations, Credit applications and (after 10c-2) Deposit applications that paid the reduced part, newest first; released Payment value becomes Customer Credit of the Customer named on the Charge's Invoice, as BR-CREDIT-014 says for a credit Adjustment; then the linked Refund pays it, as for an Invoice line. Point (b) is a new rule for Late-payment Charges, so it needs your answer. (c) Built as sub-slice 10c-3, after 10c-2; the Late-payment Charge correction then checks Deposit applications before P4608 (8a-1 note).

10c-1a (`CHARGE_REDUCTION` on Invoice lines) and 10c-1b (`REFUND` of Invoice lines paid by Payments or Credits) do not depend on this answer and go ahead under the standing rules.

**Owner answer (2026-10-07).** Yes. Add sub-slice 10c-3 for a wrong Late-payment Charge after closure, using a linked Late-payment Charge correction, prepared under `final_settlements.prepare` and confirmed only by a `financial.approve` holder. For the paid case, treat it like a credit Adjustment of an Invoice line: the released value follows BR-CREDIT-014, so Credit released to a Customer who did not make the Payment is refunded to that Customer. Recorded in docs/010 and docs/002 (BR-SETTLE-013, BR-LATE-005, BR-CREDIT-014); the plan's 10c entry gains sub-slice 10c-3.

## Q-2026-10-07-39 — Sub-slice 10c-1b stopped before code: where a correction's Refunds keep their method and note, and the remainder of a Settlement Credit application (ANSWERED 2026-10-07: yes to (a) and yes to the tightening; answers in docs/010)

10c-1a is committed (656f822). The 10c-1b design is in the plan (10c entry, "10c-1b pre-code design"). A `REFUND` correction reduces a paid line with a linked credit Adjustment; the paid part is released as migration 67 does (newest first: each Payment allocation becomes a new Customer Credit of the Invoice Customer, each Credit application gives its value back to its Credit), and the correction pays one Credit Refund per released source to that Credit's Customer. Two points differ from docs/004 or are not decided:

1. **Refund method and reference note when one correction pays several Refunds.** Every new Refund records a method and a note (BR-REFUND-014). Today they are kept in `refund_draft_details`, which allows one Refund per draft (`draft_id` is unique) and describes Refund drafts; the Settlement's own Deposit Refunds use `final_settlement_refund_details` (owner answer 3 to Q-2026-10-05-31). A line paid by two Payments, or by a Payment and a Credit, gives two Refunds in one correction. Options: (a) a new append-only table `settlement_correction_refund_details` (the Refund, the correction, the draft, the method, the note; no role may read or write it directly), like `final_settlement_refund_details`; docs/004 gains it; one method and note in the draft apply to every Refund of the correction. (b) No new table: a `REFUND` correction may release value from one source only; a larger amount is refused with "prepare one correction per Payment or Credit", and its one Refund keeps its method and note in `refund_draft_details` under the correction draft. **Recommendation: (a)**, because staff need not know the release order, one wrong charge stays one fix, and 8d set the pattern.
2. **A partly released Settlement Credit application.** When the released part is smaller than a Credit application, migration 67 reverses the whole application and writes its remainder as a new ordinary Credit application (no Final Settlement). The Settlement's own Credit application cannot be reversed in one call (8e-2, owner answer 3 to Q-2026-10-06-32), but its re-posted remainder could be. **Recommendation:** in 10c-1b, the one-call reversal of a Credit application that re-posts the remainder of a Settlement Credit application is refused (P5S01, a conflict); such a row exists only through a correction, so this refuses nothing staff can do today. And 10h counts the re-posted remainder of any allocation or Credit application that existed at closure as existing at closure.

For your information, no answer needed: a Credit released from a Payment allocation belongs to the Invoice Customer (BR-CREDIT-014); when that Customer is not the payer, the correction's Refund pays that Customer, as the 8f `CREDIT_CUSTOMER` Refund does, through a relaxing change of the Refund source checks that accepts only a Refund linked to a correction confirmed in the same transaction.

Until you answer, no 10c-1b code.

**Owner answer (2026-10-07).**

1. Yes. Add the new append-only table `settlement_correction_refund_details`, like 8d's `final_settlement_refund_details`, so one correction can pay several Refunds, each with its own method, reference note and recipient. Staff must not have to split a correction by hand. Update docs/004 to match.
2. Yes, this tightening is approved. Refuse the one-call reversal of the leftover ordinary Credit application written when a Refund releases only part of a Settlement Credit application. It is still money the closed Settlement relied on, as in the owner's Q-32 and Q-36 answers.

Also (2026-10-07): the gap until 10h (a one-call allocation reversal, then a `CHARGE_REDUCTION` without a `REFUND` record) is accepted for now, because no money can leave without an approved Refund draft and nothing is live; 10h must close it with a test. Recorded in docs/010; docs/004 gains the table; built in sub-slice 10c-1b.

## Q-2026-10-07-40 — Sub-slice 10c-1b stopped after review round 3: one test gap (the cumulative Refund cap) (ANSWERED 2026-10-07: (a), as an owner exception like Q-2026-10-05-31; the five "For the owner" points answered, point 4 an approved tightening for 10c-2 or 10h; answers in docs/010)

10c-1b is built and green but NOT committed: U3 backend unit 3589 passed, P3 PostgreSQL 1906 passed. Rounds 1 and 2 found no blocker; their findings are fixed or answered (record: ops/reviews/V1-056-slice-10c-1b-refund-correction.md). Round 3: security 0 blockers, 0 should-fix; independent 0 blockers, 1 should-fix. Under your standing rule a round-3 should-fix stops the sub-slice.

The finding: `app.settlement_correction_refund_allowed` (the check that lets a correction's Refund go to a Customer who did not make the Payment) limits a Refund, together with the same correction's other Refunds of the same Credit, to what that correction released to that Credit. The "together with the other Refunds" part is not tested: the test only shows the limit when the correction released nothing. Removing that part would leave every test green. It is defence in depth: no role can write such a Refund, only the confirm can, and the confirm writes exactly one Refund per released amount. The review record also said the round-2 test covered it; that sentence overstated the coverage and is corrected.

Options:
- (a) Add one test now: in one owner transaction, a real confirm that releases an amount to a Credit, then a second linked Refund of 1 cent from the same Credit with its details row, refused (23514). Then U4 and P4, and one more review round (independent and security) limited to the new test and the record, as an owner exception like Q-2026-10-05-31.
- (b) No code change: keep the corrected record text, add the cumulative-cap test to the slice 12 hardening item, and commit 10c-1b as it is (the committed code is exactly what U3 and P3 ran).

**Recommendation: (a).** This check is the database guard on money going to someone other than the payer; one test closes the gap now, and the cost is one short test, two runs and one limited review.

Also for you (no answer needed unless you disagree; listed in the record's "For the owner" section): one Refund method and note per correction draft, stored per Refund; the released Credits are named by the Adjustment's release records, not by a correction link; a possible harmless deadlock with a one-call Adjustment on the same Invoice; correction Refunds stay correctable by the one-call verified return like any Credit Refund (8d made Settlement Deposit Refunds correctable only through a correction); the 10h reading of your yes to Q-39 point 2.

Until you answer, 10c-1b is not committed and 10c-2 does not start.

**Owner answer (2026-10-07).**

- Q-40: option (a), as an owner exception like Q-31. Add the one test (a second 1-cent Refund from the same Credit is refused). Then run the backend unit suite and the full PostgreSQL suite once each. Then one review round limited to the new test and the review record. If that round has no blocker and no should-fix, commit 10c-1b; if it has any, stop.
- "For the owner" points: (1) accepted: one Refund method and one reference note per correction draft, and every Refund goes to the Invoice Customer. (2) Accepted: the released Credits are named by the release records and the audit event, without a correction link. (3) Accepted: the deadlock ends as a conflict, and the draft stays pending. (4) Yes, correction Refunds follow 8d. This tightening is approved: a Credit Refund paid by a post-settlement correction can be corrected only through another post-settlement correction, not by the one-call verified return; otherwise a one-call return could create Credit that pays debt without an approver. Not in 10c-1b: build it with a test in the next sub-slice, or in 10h, and put it in the plan. (5) Yes, both: a re-posted leftover of anything that existed at closure counts as existing at closure.

Recorded in docs/010; the plan's 10c-2 entry gains point 4 (10h at the latest).

## Q-2026-10-07-41 — Sub-slice 10c-2 stopped before code: a Refund of a Deposit-paid charge after closure (ANSWERED 2026-10-07: (a), yes, yes, yes with an optional new Refund; answers in docs/010)

10c-1b is committed (cc5a1ea). The 10c-2 pre-code design is in the plan (10c entry, "10c-2 pre-code design"); it splits 10c-2 into 10c-2a (a wrong charge that a Deposit application paid at closure) and 10c-2b (a returned Refund: a verified return and a new Refund in one correction, for a Settlement Deposit Refund and for a correction's Credit Refund, with your approved tightening). Four points are not decided by the rules or differ from docs/004:

1. **Does the released Deposit value first pay the Lease's open debt (DL-032)?** The design note says a `REFUND` correction refunds the released Deposit value to the Primary Tenant or the agreed Signer. But your answers after 8r and to Q-2026-10-05-24, and your answer 4 to Q-2026-10-06-36 for a forfeiture reversal after closure, say the Deposit first pays this Lease's debt that is still open, and only the rest is refunded; 8d refuses a Settlement Deposit Refund while such debt remains. Debt can stay open after closure when the Deposits ran out, or come later from an `EXTRA_CHARGE` correction. Example: the Security Deposit paid a wrong charge of $100 and was used up, and $50 of other Lease debt stayed open. Options: (a) DL-032 applies: the correction first pays the open debt from the released Deposit value through Deposit applications linked to the correction (staff choose the targets in the draft, in the DL-032 order, checked as the Settlement plan check does), and only the rest is refunded; if nothing is left, the correction has no Refund. The same step is needed by 10d (`FORFEITURE_REVERSAL`), so it is built once in 10c-2a and reused. (b) The released value is always refunded in full; the open debt stays on its ledger. (c) A Deposit `REFUND` correction is refused while such debt remains, until 10d builds the step. **Recommendation: (a)**, because it follows your DL-032 answers and the 8d rule, and (c) would leave the wrong charge with no fix.
2. **Release order when a line was paid by a Deposit application and by Payments or Credits.** Migration 67 releases the newest records first. **Recommendation:** the same rule across all three kinds, by their recorded time; Deposit applications written at closure are then usually released first, so the Deposit gets the value back before a Payment or a Credit does.
3. **Where a correction's Deposit Refund keeps its Deposit and Signer agreement.** `settlement_correction_refund_details` (10c-1b) has the method and note but no Deposit and no `signer_agreement`; `final_settlement_refund_details` (8d) allows one Refund per Deposit per Settlement and is the closure's own record. **Recommendation:** add two nullable columns to `settlement_correction_refund_details` (`deposit_id`, and `signer_agreement`, 1 to 2,000 characters, as 8d), an additive change of a table built in 10c-1b, and relax the 8d Deposit Refund source trigger so it also accepts a Deposit Refund with such a details row of a correction confirmed in the same transaction; the open-debt check of point 1 still applies. One recipient and one agreement per draft (as your answer 1 to the 10c-1b points for the method and note). docs/004 changes to match.
4. **The returned-Refund correction (10c-2b).** **Recommendation:** the draft names the returned Refund (a Settlement Deposit Refund or a correction Credit Refund), the returned amount in cents (part or all, as the one-call verified return allows), the return reference, and the new Refund's method and note (and recipient and agreement for a Deposit); the confirm records the verified return linked to the correction (the existing DB-SETTLE-005 link `refund_correction_id`, built in 10a) and the new Refund; for a Deposit, point 1 applies to the returned value; for a Credit, the new Refund pays the same Customer. Following 8d, the one-call verified return and its one-call reversal are both refused for a correction's Refund (8d refuses every one-call Refund correction of a Settlement Deposit Refund). A one-call reversal of a return recorded by a correction is also refused; a mistaken return record then needs a later correction kind (not built).

Q-2026-10-07-41 does not change 10c-1b. Until you answer, no 10c-2 code.

**Owner answer (2026-10-07).**

1. Yes, option (a). Released Deposit value first pays this Lease's open debt through Deposit applications linked to the correction, then the rest is refunded. It follows every Settlement rule already given: Credit before Deposits (Q-29), the Security Deposit before the remaining Pet Deposit (Q-30), the Pet Deposit choice rules (Q-20, Q-25) and the kept-Deposit cases (Q-24). Build it once and reuse it in 10d. If any of these conflict, stop and ask me.
2. Yes. Newest first across Deposit applications, Payment allocations and Credit applications, as migration 67 does.
3. Yes. Add the two nullable columns to `settlement_correction_refund_details` and update docs/004. Relax the 8d Deposit Refund source check only for a confirmed correction's own Refund, and add a test that it accepts nothing else.
4. Yes, with one change: the new Refund in a returned-Refund correction is optional. If the Customer cannot be reached yet, the correction records the verified return only, and the returned amount stays as that Customer's Credit until a later correction refunds it. Both the one-call return and its one-call reversal stay refused for a correction's Refund. If this does not fit your design, stop and ask me.

Recorded in docs/010. Two conflicts found while applying answers 1 and 4: Q-2026-10-07-42.

## Q-2026-10-07-42 — Sub-slice 10c-2: "Credit before Deposits" after closure, and a returned Deposit Refund (blocks 10c-2a-2, 10c-2a-3 and 10c-2b; not 10c-2a-1) (ANSWERED 2026-10-07: (a) to all three; answers in docs/010)

10c-2a is split (a split needs no owner answer): **10c-2a-1** the Deposit application reversal record (DB-DEP-006) and every reader of Deposit applications (balances, the Invoice status refresh, the Customer Ledger, the Deposit history), written only inside a correction confirmed in the same transaction (corrected after review round 1: no writer yet; the correction writers of 10c-2a-3 and 10e write it); **10c-2a-2** the shared step of your answer 1 (released or held Deposit value first pays the Lease's open debt under the Settlement rules, then the rest is refunded), reused by 10d; **10c-2a-3** the `REFUND` correction of a Deposit-paid line. 10c-2a-1 does not depend on the points below and goes ahead under the standing rules, as 10a did while Q-37 was open.

1. **Customer Credit before Deposits after closure (Q-29 answer 2).** When released Deposit value is to pay open debt and a Customer with open debt on the Lease has Credit available (Credit the same correction releases from a Payment, or Credit the Customer already had), the Settlement rule says that Credit pays that Customer's own open debt first. Options: (a) the correction writes those Credit applications itself, linked to the correction and recorded as Credit applications of that Settlement (so their one-call reversal is refused, as 8e-2), following BR-CREDIT-006 (the Rent-first proposal or the Customer's designation); (b) the correction is refused (a conflict) while such Credit exists; staff first apply it with the ordinary one-call Credit application, then record the correction again. **Recommendation: (a)**, one fix, as the Settlement draft does.
2. **10c-1b refunds released Credit even when its Customer still has open debt.** In the committed 10c-1b, value released from a Payment allocation or a Credit application becomes or returns to the Invoice Customer's Credit and is refunded at once, also when that Customer still owes other debt on the Lease. With answer 1, a mixed line in 10c-2a (paid by a Payment and by a Deposit) would refund the released Credit while the released Deposit value pays that Customer's debt, which breaks "Credit before Deposits". Options: (a) every `REFUND` correction applies all released value under the Settlement rules before any Refund: released Credit first pays its own Customer's open debt (point 1), released Deposit value then pays the Lease's open debt in the DL-032 order, and only the rest is refunded; 10c-1b changes in 10c-2a-3 (a tightening of a committed sub-slice: fewer or no Refunds when the Customer still owes); (b) only Deposit value follows DL-032; released Credit is always refunded as in 10c-1b, and in a mixed line the Deposit pays the debt while the Credit is refunded (an exception to Q-29 for corrections). **Recommendation: (a)**, because it keeps one rule for the Settlement and its corrections.
3. **Answer 4 for a returned Settlement Deposit Refund.** A verified return of a Deposit Refund gives the value back to the Deposit (DB-DER-004: the held balance counts the net Refund after its corrections), not to Customer Credit; there is no path from a Deposit to Customer Credit. Options: (a) for a Deposit Refund, a return-only correction leaves the returned amount held by the Deposit after closure; a later correction refunds it, and before that it first pays the Lease's open debt (answer 1); for a Credit Refund the returned amount stays that Customer's Credit, as you said; (b) a new path moves the returned Deposit value into the Primary Tenant's Credit (a new rule and record). **Recommendation: (a).** With it, "a later correction refunds it" needs a refund-only form of the returned-Refund correction (no new return; it refunds value an earlier returned-Refund correction left, linked to that correction), built in 10c-2b.

For your information, no answer needed: after a return-only correction of a Credit Refund, the Customer may apply that Credit to debt with the ordinary one-call Credit application, as with any Credit after closure (owner answer 7 to Q-2026-10-05-20); the Credit came back through a correction confirmed by an approver, which your tightening asked for.

Until you answer, only 10c-2a-1 is built.

**Owner answer (2026-10-07).**

1. Yes. Before released Deposit value pays open debt, the correction first applies that Customer's own Credit to that Customer's own open debt on this Lease, as the Settlement draft does (Q-29). Credit never pays another Customer's debt. Reuse the 8e-2 Credit application writer with a correction link if you can.
2. Yes, this change is approved. Every Refund correction first uses released Credit against its own Customer's open debt on this Lease, and refunds only the rest. A Customer who has no open debt on this Lease (for example, a third-party payer) gets the Refund as now. Change 10c-1b in 10c-2a-3 as proposed, with tests for both cases.
3. Yes. A returned Deposit Refund goes back to the Deposit, not to Customer Credit. It stays held by the Deposit until a later correction, which first pays this Lease's open debt in the DL-032 order and then refunds the rest. The Q-41 answer 4 (the returned amount stays as Customer Credit) still applies to a returned Credit Refund only.

Recorded in docs/010; the 10c-2 design in the plan is updated.

## Q-2026-10-07-43 — Sub-slice 10c-2a-2 stopped after review round 2: four should-fix findings (ANSWERED 2026-10-07: (a), owner exception; choices 5 confirmed, 16 accepted as a known limit; answers in docs/010)

10c-2a-2 (the shared DL-032 step after closure, migration `20261106_102`) is built and green: backend unit U2 3589 passed, full PostgreSQL P5 1918 passed (P1 and P3 failed on causes inside the slice, corrected once each; record: ops/reviews/V1-056-slice-10c-2a-2-settlement-correction-plan.md). Round 1 (no blocker; 6 should-fix) is fixed with tests. Round 2 found no blocker and no bypass, but four distinct should-fix findings, more than the standing round-3 rule allows. Nothing is committed; all 10c-2a-2 files are in the working tree.

**The four should-fix findings, each with the fix I would make:**

1. (Security SF1, code) The step's lock function takes no Lease row lock (the Settlement confirm locks it `FOR UPDATE`, 10b `FOR SHARE`). A move-out inspection superseded by another user while a correction runs could turn a line the Pet Deposit is paying as pet damage into non-pet debt before the commit. Fix: lock the Lease row `FOR UPDATE` right after the two advisory locks (the Settlement confirm's order), with a two-connection test (another connection's `FOR UPDATE NOWAIT` on the Lease gets 55P03 while the locks are held), and the docs.
2. (Security SF2, tests) The step's own guards are untested inside a live correction: another person than the approver calling it, and the READ COMMITTED refusal. Fix: two refusal tests, each leaving the draft pending.
3. (Independent SF1, tests) BR-DEP-027 and BR-CREDIT-006 are claimed, but their copied branches have no test (the "only the Customer may choose" step 5 refusal and the Pet Deposit Refund while debt remains at a BR-DEP-027 termination; the Rent-first refusal and the proposal and designation bases). Fix: tests with an unpaid-Initial termination (BR-LEASE-005) and a Rent Invoice line, plus the cheap DL-032 order, wrong Deposit type and non-pet line refusals.
4. (Independent SF2, record) The record pointed to a "For the owner" section that did not exist. Done (no code): the record now has it; the three points are below.

I would also take the round-2 notes that cost little: the docs/004 sentence on a partial release (the rest is re-applied only as a plan step), test and traceability wording (test 2 recipient is the payer; test 4 rule IDs; the two stale fields not changed by a test; assertions that the Late-payment Charge test really has its pet damage and Charge steps). The other notes become plan notes for 10c-2a-3, 10c-2b and 10d: a variant must not write a linked Deposit application, Credit application or Deposit Refund outside the step (or a deferred check that the step ran), must call the lock function before begin and lock the released allocation's Payment, and its audit event must name every record.

**Options:**

- (a) As an owner exception like Q-2026-10-05-31 and Q-2026-10-07-40: make fixes 1 to 3 and the cheap notes, run the backend unit suite and the full PostgreSQL suite once each, then one more review round (independent and security); commit only if that round has no blocker and no should-fix.
- (b) Stop 10c-2a-2 here and decide the design points first.

**Recommendation: (a).** Fix 1 is the only code change (a lock, no rule change); 2 and 3 are tests.

**Also for you (named choices in docs/010, not blocking the fixes):**

- Choice 5, first part: Customer Credit before Deposits (your answer 1 to Q-42) applies after closure only when a Deposit holds money; at the Settlement it applies always (Q-29 answer 2). Always after closure would make a Credit-only `REFUND` correction apply the Credit of Customers it does not concern. Is the conditional rule right?
- Choice 5, second part: "released Credit first" (your answer 2 to Q-42) counts all of that Credit's available value, also value it held before the correction (a Credit that a reversed Credit application refills). Is that right, or only the released part?
- Choice 16 (accepted race): the Credit-before-Deposits rule reads every Credit of the Lease's Customers but locks only the Credits the steps name, as the Settlement confirm; a Credit recognized by a concurrent one-call command after the check is not used first. Nothing is overpaid.

Until you answer, no 10c-2a-2 fix and no commit.

**Owner answer (2026-10-07).** Option (a), as an owner exception like Q-31 and Q-40.

1. Fix item 1. The step must hold a lock that really stops the move-out inspection from being superseded while the step runs. Check that the command that supersedes an inspection takes the same lock; if it does not, lock what that command locks, in the lock order of the 8e-3 plan note. Add a test that shows the Pet Deposit cannot pay a line that is no longer pet damage. (Done: `app.move_out_inspection_record` and its insert trigger lock the Lease row `FOR UPDATE`; the step's lock function now locks the same row `FOR UPDATE` right after the two draft locks, as the Settlement confirm.)
2. Fix item 2: test both guards inside a live correction (a person other than the approver; the READ COMMITTED refusal).
3. Fix item 3: add tests for the BR-DEP-027 and BR-CREDIT-006 branches.

Then the backend unit suite and the full PostgreSQL suite once each, then one more independent round and one security round on the three fixes and the code they touch. Commit only if both rounds have no blocker and no should-fix; otherwise stop and report, with no further fix without the owner.

Choices: (1) confirmed: Credit before Deposits after closure applies only when a Deposit holds money; the rule protects Deposit money, and a correction must not apply the Credit of Customers it does not concern. (2) Confirmed: "released Credit first" counts the whole Credit of that Customer, including value it held before the correction; a Customer is never refunded while that Customer owes money on this Lease that the Credit could pay (Q-29). (3) Accepted: Credit recognized by another command right after the step's check is not used first; nothing is overpaid and that Credit stays with the Customer; written as a known limit in docs/010.

Recorded in docs/010.

## Q-2026-10-07-44 — Sub-slice 10c-2a-2 stopped after review round 3: two text should-fix findings (ANSWERED 2026-10-07: (a); inspection supersede refused after closure; a new Customer choice per correction; 10c-1b takes the Lease lock in 10c-2a-3; answers in docs/010)

The three fixes of Q-2026-10-07-43 are built and green: backend unit U3 3589 passed, full PostgreSQL P6 1921 passed (the new module 10 passed), no correction (record: ops/reviews/V1-056-slice-10c-2a-2-settlement-correction-plan.md). Round 3: the security review has no blocker and no should-fix; the independent review has no blocker and two should-fix findings, both verified. Under your answer to Q-43, nothing is fixed and nothing is committed; all 10c-2a-2 files are in the working tree.

**The two should-fix findings (text only; no behaviour change):**

1. The comment before `app.lock_settlement_correction_plan` (migration 102, a SQL comment outside the function body, so not stored in the database) says a variant takes "the draft lock, the Settlement's draft lock and the Lease row first (as sub-slice 10c-1b ...)". The 10c-1b confirm takes no Lease lock, and neither the comment nor the plan's "Notes for the writers" says the variant must take the Lease row `FOR UPDATE`. A later writer that copied 10b's `FOR SHARE` would upgrade the lock after its own sources (deadlock risk, 40P01). Fix: "the Lease row `FOR UPDATE`, as the Settlement confirm", naming 10c-1b only for the two draft locks, in the comment and in the plan note.
2. The inspection test's docstring and its traceability entry cite BR-DEP-027, but that test's Settlement has no termination ground, so BR-DEP-027 does not apply there (the new BR-DEP-027 test covers it). Fix: remove BR-DEP-027 from that entry and docstring.

**Options:**

- (a) Make the two text fixes; run the static checks (each in its own call) and the backend unit suite once (the traceability entry changes; the unit suite checks traceability); no PostgreSQL run, because the migration change is a comment outside any function body and the test change is a docstring; no further review round (as Q-2026-10-04-6); then commit 10c-2a-2.
- (b) As (a), plus a full PostgreSQL run and one more limited review round on the two text fixes.

**Recommendation: (a).** Both findings are wording; the code, the database and every test result stay the same.

**Notes from round 3 for you (not blocking; your decision where marked):**

- (Owner policy) Security N1: the Lease lock makes the step's checks consistent while it runs, but not lasting. After a correction, or the Settlement confirm itself, has committed a pet-damage Deposit application, a user with the inspection capability can still supersede the inspection, and the line stops being pet damage. The money already applied stays applied. Options: refuse an inspection supersede once the Lease's Settlement is closed (a conflict; a tightening that needs you), route such a change through a correction (later sub-slice), or record it as a known limit. My recommendation: refuse the supersede after closure, in its own small sub-slice after 10c-2a-3, because an inspection after closure can otherwise change what the closed Settlement paid as pet damage without an approver.
- (Owner policy) Independent note 7: in the BR-DEP-027 test the correction reuses the Customer's choice text recorded at the Settlement. Should a correction after closure that uses the remaining Pet Deposit at a BR-DEP-027 termination need a new Customer choice? My recommendation: yes; the variant recorders (10c-2a-3, 10d) ask for the Customer's choice again and store it in the draft, because the Customer chose for the Settlement, not for the later correction.
- Optional test hardening (no rule change): a case where only the step itself takes the lock function (without the variant's call); a wrong `within_invoice_basis` on a correction's Credit application refused (23514); a check that the stale test covers every result key; `blocked_by` looks for the Lease row lock in `pg_locks` and waits up to 10 seconds. I would add them in 10c-2a-3, with its own runs.
- Availability (as the Settlement confirm): while a correction runs the step, inserts that name the Lease wait and the `NOWAIT` Lease readers (move-out final inputs, final Utility Invoice, Utility baseline, hand-back Rent) fail at once with 55P03; the variant services map 55P03 and 40P01 to a conflict. I would add one docs/004 line with the text fixes.

Until you answer, no 10c-2a-2 fix, no commit, and no 10c-2a-3.

**Owner answer (2026-10-07).**

1. Option (a). Fix the two texts: the comment before the lock function and the plan note say that 10c-1b does not take the Lease lock and that every later correction type takes the Lease row lock `FOR UPDATE` in the 8e-3 order; the inspection test's docstring and traceability entry do not cite BR-DEP-027. Before skipping the PostgreSQL run, a read-only search confirms that no PostgreSQL test reads the changed comment, docstring or traceability entry (if one does, one full PostgreSQL run). Then the static checks, each in its own call, and the backend unit suite once; if all are clean, commit 10c-2a-2. (Done: the search found no such test; static checks clean; unit U4 3589 passed.)
2. Inspection after closure: yes, the tightening is approved. Once a Settlement is closed, a supersede of its move-out inspection is refused. A wrong pet-damage line after closure is fixed only with a post-settlement correction. The plan names the correction kind staff use; if no kind fits, the question goes here with a recommendation and the work stops. Built in a small sub-slice after 10c-2a-3, with tests. (Plan: sub-slice 10c-2a-4; for a wrong classification no kind fits, Q-2026-10-07-45.)
3. Customer choice: yes. A correction that uses the rest of the Pet Deposit at a BR-DEP-027 termination needs a new Customer choice, recorded for that correction; it does not reuse the choice given for the Settlement; without a new choice the rest of the Pet Deposit is not used for other debt (one agreement per correction, as the Q-41 answer).
4. After 10c-2a-2 is committed, continue with 10c-2a-3. When 10c-1b uses the shared step there, it takes the same Lease lock in the 8e-3 order, with a test, and the comment and the plan note are updated.

Recorded in docs/010.

## Q-2026-10-07-45 — A wrong pet classification of a Damage line after closure: no correction kind fits (blocks only the fix path of sub-slice 10c-2a-4) (ANSWERED 2026-10-07: (a), a new correction kind, sub-slice 10c-2a-5; answer in docs/010)

Your answer 2 to Q-2026-10-07-44 asks which correction kind staff use for a wrong pet-damage line after closure. The plan (10c-2a-4) lists the kinds that fit when the Damage charge itself is wrong: `CHARGE_REDUCTION` (unpaid line), `REFUND` (paid line; for a Deposit-paid line 10c-2a-3, and the released Pet Deposit value then goes through the shared DL-032 step) and `EXTRA_CHARGE` (damage billed too low).

No kind fits when the charge is right but its pet classification is wrong. Example: at closure the Pet Deposit paid a 12,500 Damage line first, as pet damage (DL-032 step 3); later staff learn that the pet did not break the window latch. The charge is still owed, but under DL-032 the Security Deposit should have paid it (step 4), and the Pet Deposit only at step 5 (a staff reason, or at a BR-DEP-027 termination the Customer's choice). The reverse case also exists: a pet-caused line marked not pet, so the Security Deposit paid it while the Pet Deposit was refunded. Every existing kind changes the charge. An inspection supersede cannot carry the fix either: pet damage is read from the current inspection's findings (`app.invoice_line_is_pet_damage`), and a new inspection cannot reuse finding ids, so a supersede makes every line billed from the old inspection no longer pet damage, the correct ones too.

**Options:**

- (a) A new correction kind, for example `PET_DAMAGE_RECLASSIFICATION`, one Damage line per draft (`final_settlements.prepare` records, `financial.approve` confirms): the draft names the line, its corrected classification (pet-related or not) and an evidence reference; the confirm writes an append-only classification record for that line, linked to the correction (a new DB-SETTLE-005 link and table; docs/004 change); `app.invoice_line_is_pet_damage` reads the latest such record before the inspection; when the new classification changes which Deposit should pay, the confirm reverses the line's Deposit applications (10c-2a-1) and runs the shared step (10c-2a-2) on the released value: each Customer's Credit first, then the Deposits in the DL-032 order, and the rest refunded; at a BR-DEP-027 termination the Pet Deposit pays other debt only with a new Customer choice (your answer 3). A Deposit already refunded at closure is not taken back, so the line may stay open debt on the Customer's ledger. One sub-slice after 10c-2a-4, before 10h.
- (b) Record the corrected classification only (an audited record linked to a correction), with no money effect: the Deposit applications stay as paid.
- (c) No reclassification after closure: accept it as a known limit; only a wrong charge is corrected, with the kinds above.

**Recommendation: (a).** DL-032 decides which Deposit pays by this classification, and your answer says a wrong pet-damage line after closure is fixed only with a correction.

**Also (before closure, existing behaviour, for your information and decision):** before closure a supersede of the inspection also makes every line billed from the old inspection no longer pet damage, even when the new inspection repeats the same pet finding, because the Damage charge keeps the old finding's id. The Settlement preview then lets the Security Deposit pay such lines first and the Pet Deposit only at step 5. **Recommendation:** a later sub-slice lets a superseding inspection carry a finding forward (a link from the new finding to the old one) so that a repeated pet finding keeps its lines pet damage; until then, the move-out inspection screen warns staff that a supersede changes the pet status of lines already billed.

Q-2026-10-07-45 does not change 10c-2a-2 or 10c-2a-3. The refusal itself (10c-2a-4) does not depend on it; only the fix path for a wrong classification does.

**Owner answer (2026-10-07).** Option (a); continue with 10c-2a-3 now.

- A new correction kind for a Damage line whose pet classification is wrong after closure. The charge amount stays the same. The closed inspection record is not changed. The correction records the corrected classification and the reason.
- It covers both directions: a line wrongly marked as pet damage, and a line that should have been pet damage.
- It re-runs the shared DL-032 step after closure, with all Settlement rules (Q-24, Q-29, Q-30) and the Q-44 answer 3 (a new Customer choice for this correction).
- It is prepared under `final_settlements.prepare` and confirmed only by a `financial.approve` holder, like every correction.
- Built after 10c-2a-4 and before 10h, with tests for both directions; in the plan (sub-slice 10c-2a-5).

Recorded in docs/010. The point about a supersede before closure is still open for a later decision (not blocking).

## Q-2026-10-07-46 — Sub-slice 10c-2a-3 stopped before code: the Deposit-application refusal of an Adjustment conflicts with the newest-first release (ANSWERED 2026-10-07: (a), with an overpayment and no-Credit condition; answer in docs/010)

The 10c-2a-3 pre-code design is in the plan (10c entry, "10c-2a-3 pre-code design"). One point conflicts, so I stopped before code. Nothing else in the design needs an answer.

**The conflict.** Since sub-slice 8a-1, an Invoice Adjustment is refused while any Deposit application on that Invoice is still active (`app.refuse_deposit_applied_obligation_change`, 55000 "A Deposit application paid this obligation at Final Settlement"). Sub-slice 10c-2a-1 relaxed it only for applications that are reversed. It has no exception for a correction's own Adjustment, and it looks at the whole Invoice, not the corrected line. Your answer 2 to Q-41 says the release takes the newest sources first across Deposit applications, Payment allocations and Credit applications, only until the paid part is covered. So the correction's credit Adjustment is refused when:

- the corrected line has an older Deposit application that the release does not reach (example: the Security Deposit paid 10,000 of a Damage line and a later Payment paid 2,500; a Refund of 2,000 releases only the Payment, and the Security Deposit application stays active), or
- another line of the same Invoice was paid by a Deposit (example: the Security Deposit paid the Rent line and the Trash line of one Invoice; a Refund on the Trash line leaves the Rent line's application active).

The plan's 10c-2a text says the refusal "passes it only when every Deposit application of the line is reversed in the same correction", which cannot hold together with the newest-first release.

**Options:**

- (a) Relaxing change: the refusal lets through a credit Adjustment that is linked to a post-settlement correction of that Invoice's Settlement, confirmed in the same transaction by its approver. This is the path the refusal's own comment names ("An obligation a Deposit application paid changes only through a post-settlement correction"). The release stays newest first (Q-41 answer 2). Deposit applications the release does not reach stay as they are, and they still pay their own lines. Every unlinked Adjustment, VOID or Late-payment Charge correction stays refused (8a-1 and 8e-1). One test shows each example above, and one shows an unlinked Adjustment still refused.
- (b) The release reverses every active Deposit application of the Invoice, then the plan pays the rests again. This is many more records, and the DL-032 rules (Credit first) could change who pays lines the Customer did not ask to correct.
- (c) A `REFUND` correction is refused (a conflict) when the release does not reverse every Deposit application of the Invoice. Staff could not correct these cases until another kind exists.

**Recommendation: (a).** It keeps your newest-first answer. It changes only what the correction itself corrects, and the 8a-1 and 8e-1 refusals still stop every unlinked change. It is a relaxing change of a committed refusal, which the plan text did not foresee, so I ask before building it.

Until you answer, no 10c-2a-3 code.

**Owner answer (2026-10-07).** Option (a).

- Let through only an Invoice Adjustment that is linked to a correction of that Invoice's own Settlement, confirmed in the same transaction by that correction's approver. Every unlinked Adjustment stays refused, as in 8a-1.
- The release stays newest first, as the Q-41 answer 2.
- After such an Adjustment, no line may be paid more than its new amount. Deposit value is freed only by the correction's own Deposit application reversal, following the plan; it never turns into Customer Credit by itself. If the database does not already enforce this on the new path, add the check.
- Tests for both cases (an older Deposit application on the same line that the release does not reach; a Deposit application on another line of the same Invoice), and a test that an unlinked Adjustment on such an Invoice is still refused.

Recorded in docs/010; the 10c-2a-3 design in the plan is updated.

## Q-2026-10-07-47 — Sub-slice 10c-2a-3 stopped before code: the 10c-1b tests need new fixtures, not one changed expectation (ANSWERED 2026-10-07: (a), owner exception for the six tests; answer in docs/010)

Your answer 2 to Q-42 changes 10c-1b: a `REFUND` correction first uses the Credit it releases against that Credit's Customer's open debt on this Lease, and refunds only the rest. In 10c-2a-3 every `REFUND` correction runs the shared DL-032 step for this, with its committed rules (sub-slice 10c-2a-2): every DL-032 Deposit that holds money must be applied or refunded (BR-SETTLE-008), and while a Deposit holds money each Customer's Credit pays that Customer's debt first.

Read-only search: six of the nine 10c-1b tests (`test_settlement_refund_correction_migration.py`) record and confirm Refund corrections on a Settlement closed with `leaving_case` and the owner-written `close()` helper of sub-slice 8e-1 (a seventh uses `close()` but builds its correction by hand through the internal functions; the last two do not close a Settlement). That helper only marks the Settlement closed. It applies nothing, so after closure both Deposits still hold money (Security 10,000, Pet 20,000) and the Invoice Customer still owes both Damage lines (25,000). A real closure (the 8e-3 confirm) never leaves a DL-032 Deposit holding money. In that state every Refund correction of those tests would be refused under the new rules (the released Credit must pay the Customer's open debt first; the held Deposits must be emptied). The run rules let me narrow a historical test only by changing one expectation. These tests need new fixtures, so I stopped before code.

**Options:**

- (a) Rebuild the 10c-1b test fixtures on a real closure: the 8e-3 confirm with a plan that empties both Deposits, as the 10c-2a-2 tests do (`closed_case`), so the Invoice Customer owes nothing on the Lease after closure. Each test keeps its name and what it proves: a Customer with no open debt gets the Refund as in 10c-1b. Amounts and source lists in those tests change with the new closure. A test whose corrected line a Deposit now pays moves to another line paid by a Payment or Credit. Every changed test is listed in docs/010. The new 10c-2a-3 tests prove the case where the Customer owes (released Credit pays the debt first, and only the rest is refunded). The one expectation "a Deposit-paid Invoice waits" changes to accepted, as the narrowing rule allows.
- (b) Narrow each 10c-1b test to expect the new refusal, one expectation each, and move the success paths of 10c-1b into the new 10c-2a-3 module. This follows the narrowing rule literally, but the 10c-1b module would then mostly prove refusals.
- (c) Keep the 10c-1b tests as they are by applying the step only when the correction releases Deposit value. This does not work: the released Credit's Customer still owes 25,000 in those tests, so your Q-42 answer 2 still requires the Credit to pay first.

**Recommendation: (a).** It keeps each 10c-1b test proving its own behaviour, on the state a real closure leaves. The change follows from your approved Q-42 answer 2, not from a weaker test.

Until you answer, no 10c-2a-3 code.

**Owner answer (2026-10-07).** Option (a), as an owner exception to the narrowing rule for these six tests only.

- Rebuild the six 10c-1b tests on a real closure, the 8e-3 confirm, as the 10c-2a-2 tests do.
- Each test keeps its name and must still prove the same 10c-1b behaviour. No assertion about that behaviour is removed or loosened; only the setup, amounts and source lists may change.
- docs/010 lists each changed test with what changed and why.
- The independent reviewer checks each rebuilt test against its old version and confirms that none was weakened.
- New correction tests do not use the test-only close helper. Slice 12 list: check every other test that uses it and leaves a state a real closure cannot leave.

Recorded in docs/010; the slice 12 item is in the plan.

## Q-2026-10-08-48 — Sub-slice 10c-2a-3 stopped after review round 3: two should-fix findings (a test gap and plan text) (ANSWERED 2026-10-08: (a), owner exception like Q-43; answer in docs/010)

10c-2a-3 (the `REFUND` correction of a Deposit-paid charge, migration `20261107_103`) is built, documented and green, but not committed; all files are in the working tree. Record: ops/reviews/V1-056-slice-10c-2a-3-deposit-refund-correction.md.

- Your answers of 2026-10-07 were applied. Cause C was a host clock ahead of the Docker VM clock while the Mac display slept (the lease signature fixtures take host time); it was not product code and not shared test state, so nothing was changed, and later runs ran under `caffeinate`. Cause A was fixed with its second correction (the Q-46 case of a Deposit application on another line stays, with a new Customer choice and nothing refunded). Cause B was fixed with its first correction.
- Runs: U2, U3, U4 backend unit 3589 passed; P3 1928, P5 1929, P6 1929 full PostgreSQL passed. P4 failed once on cause D (my round-1 change of the `failure` test helper rolled back before the deferred checks; one correction).
- Round 1: security 1 should-fix (the corrected Invoice was locked before the Late-payment Charges); independent 2 should-fix (no mixed Payment and Deposit line test; a date-bound fixture). All fixed or answered.
- Round 2: security 1 should-fix (the released sources' Payments were locked in a pass of their own, so Payments were not locked in one id order); independent 0. Fixed; the lock function now takes every Payment and Credit in one id-ordered pass each.
- Round 3: security 0 should-fix. Independent 2 should-fix, so under the standing rule I stopped. Nothing is fixed after round 3 and nothing is committed.

**The two findings:**

1. **(Test gap; touches your Q-47 rule.)** At HEAD, 10c-1b tests 5 and 6 were the only PostgreSQL tests that confirmed a `REFUND` correction whose amount included an unpaid part (12,200 with 12,100 unpaid; 12,300 with 12,200 unpaid). Test 5's last check (`outstanding == 0`) therefore proved that the unpaid part is removed together with the paid part (docs/004: "An unpaid part of the amount is removed with it"). The rebuild pays the line before closure, so both tests now correct 100 on a fully paid line. Every assertion is kept, but that check no longer proves anything, and no other test confirms a `REFUND` with 0 < outstanding < amount. This matters more after 10c-2a-3: on a Deposit-paid line that still owes, `amount - outstanding` decides how much is released, and the step's overlay must match the real state after the Adjustment. The reviewer's derivation says it does, but no test shows it.
2. **(Plan text.)** The plan's "Notes for the writers" (the 10c-2a-2 entries) still tell 10c-2b and 10d to lock "its own sources (for example the Payment of an allocation it releases), then call the lock function". That is the separate pass that round 2 removed as a deadlock risk. The lock function's new branch covers only `REFUND`, so a later variant that followed the note would bring the risk back.

**Options:**

- (a) As an owner exception like Q-2026-10-05-31, Q-2026-10-07-40 and Q-2026-10-07-43:
  - Two new tests in the new module, with the six rebuilt tests unchanged: a charge issued after closure, partly paid by the Customer, refunded for more than the paid part (the unpaid part is removed, the paid part is released and refunded); and a Deposit-paid line that still owes, refunded for more than the paid part (the unpaid part is removed, part of the Deposit application is released and reversed whole, and the plan pays the rest).
  - A docs/010 sentence on the coverage moved from tests 5 and 6.
  - The two plan notes amended: after the Lease row a variant takes no lock of its own; it extends the lock function for its variant.
  - The cheap round-3 notes: the "as amended by 10c-2a-3" marker in the docs/004 10c-1b paragraph; stronger source assertions (no `serialize_payment_state` in the confirm, one Payment and one Credit lock statement in the lock function); "except the Refund method, last" in docs/010.
  - Then static checks, the migration-only check, the backend unit suite and the full PostgreSQL suite once each, and one more limited round (independent and security) on these changes. Commit only if that round has no blocker and no should-fix; otherwise stop and report, with no further fix without you.
- (b) Fix only the plan text, record finding 1 as a slice 12 test item, run the static checks and the backend unit suite, and commit without another review round.

**Recommendation: (a).** Finding 1 is real lost coverage in tests rebuilt under your Q-47 rule. It covers the release arithmetic that 10c-2a-3 now relies on for Deposit-paid lines, so it should be proven before the commit. Finding 2 is text, but it guards the next two sub-slices.

Until you answer, no fix, no commit, and no 10c-2a-4.

**Owner answer (2026-10-08).** Option (a), as an owner exception like Q-43.

- My Q-47 answer said each rebuilt test must still prove the same behaviour. Tests 5 and 6 lost the check of a Refund that includes an unpaid part, so this coverage must come back before the commit.
- Add the two tests: a charge partly paid after closure and refunded for more than the paid part, and a Deposit-paid line that still owes, refunded the same way. Check each amount to the cent, including how much Deposit value is released.
- Leave the six rebuilt tests as they are. Fix the two plan notes and the cheap round-3 notes.
- Run each check once. Then one limited review of the new tests and the changed text. If it finds no blocker and no should-fix, commit 10c-2a-3. If it finds any, stop and report.
- Cause C: the finding is accepted. Keep the Mac awake with `caffeinate` during full runs until the slice 12 item is done.
- After 10c-2a-3 is committed, continue with 10c-2a-4 under the same rules.

Recorded in docs/010.

## Q-2026-10-08-49 — Sub-slice 10c-2a-4 stopped before code: refusing an inspection supersede after closure conflicts with the committed 10b Damage extra charge (ANSWERED 2026-10-08: (a); answer in docs/010)

10c-2a-3 is committed (fe59f0e; NOW.md f2aa647). A read-only check before the 10c-2a-4 design found a conflict, so there is no 10c-2a-4 code and no run.

Your approved tightening (answer 2 to Q-2026-10-07-44): once a Settlement is closed, a supersede of its move-out inspection is refused; a wrong pet-damage line after closure is fixed only with a post-settlement correction.

**The conflict.**
- Sub-slice 10b (`EXTRA_CHARGE`, BR-INV-044, migration `20261102_98`, committed) bills a Damage charge after closure only from a current, unbilled finding of a move-out inspection of the Lease.
- Its committed test `test_a_damage_extra_charge_bills_a_current_unbilled_finding_and_a_stale_draft_waits` (`test_settlement_extra_charge_migration.py`) records damage found after closure by superseding the closure-time inspection (`supersedes_inspection_id=earlier`).
- Under the tightening that supersede is refused. The test would fail, and staff could no longer record damage found after closure that way.

**What the database allows today (read-only check).**
- `app.move_out_inspections` has no rule of one inspection per Lease. An inspection that supersedes nothing can be recorded next to the first one; only the superseded id is unique.
- The pet-damage reader (migration 86), the 10b extra charge (migration 98) and the inspection snapshot treat every inspection that nothing supersedes as current.
- So damage found after closure can be recorded as an independent inspection. It leaves every billed finding current, so no line the Settlement paid changes its pet classification.

**Options:**
- (a) Refuse every supersede after closure, as you approved (P5S01, before anything is written, in the inspection command and its insert trigger, with the service mapping it to a conflict). Damage found after closure is recorded as a new inspection that supersedes nothing.
  - The 10b test changes its setup from a supersede to an independent inspection. It is one committed test; its refusal of the old, already billed finding stays (the expected message may change from "not current" to "already billed"); a docs/010 note.
  - The 10c-2a-2 inspection test changes as the plan says.
  - Before code, a read-only check that no consumer of inspections (physical move-out, the Settlement preview, one-time charges, the readers and screens) assumes a single inspection chain. If one does, I stop again.
- (b) Refuse a supersede after closure only when the superseded inspection has a finding already billed on an Invoice line, which is the case your tightening protects. A supersede of an inspection with only unbilled findings stays allowed. The 10b test still passes only if its superseded inspection has no billed finding, which it has (both Settlement lines were billed from it), so the test changes anyway. This is weaker than your words.
- (c) Withdraw the tightening and keep supersede after closure; wrong pet classifications are fixed only by the 10c-2a-5 correction. Not recommended: a supersede after closure would still change what the closed Settlement paid as pet damage without an approver (the round-3 note of 10c-2a-2).

**Recommendation: (a).**
- It keeps your rule as written.
- Damage found after closure stays billable through 10b.
- No line the closed Settlement paid changes its pet classification.
- The cost is a changed setup in one committed 10b test, plus the 10c-2a-2 test change the plan already names.

Also done in this stop, text only: the plan notes and docs/004 wording carried from the 10c-2a-3 limited review (old clauses removed; the Refund method exception named; "such an Invoice's lines"; the as-built note lists the two new tests).

Until you answer, no 10c-2a-4 code.

**Owner answer (2026-10-08).** Option (a).

- Once a Lease's Settlement is closed, every supersede of a move-out inspection on that Lease is refused. The refusal is a conflict, like the other refusals after closure.
- Damage found after closure is recorded as a new, separate inspection. The inspection the closed Settlement relied on never changes.
- A wrong finding on the inspection the Settlement relied on is fixed only with a post-settlement correction (10c-2a-5 for a wrong pet classification).
- A mistake in an inspection recorded after closure cannot be fixed by a supersede either (a known limit in docs/010). The wrong finding is simply not billed, because billing still needs a correction confirmed by a `financial.approve` holder.
- Before code, check that nothing assumes one chain of inspections per Lease, in particular the readers that decide current findings and pet damage for the Settlement and for corrections. If one does, write it here with a recommendation and stop. (Done 2026-10-08: none found; docs/010.)
- The committed 10b test changes its set-up so that it records the new damage as a separate inspection. It keeps its name and must still prove the same behaviour. A part that can no longer happen after closure is named in docs/010 and in the report. The independent reviewer compares it with its version at HEAD.

Recorded in docs/010.

## Q-2026-10-08-50 — Sub-slice 10c-2a-4 stopped before code: the plan's change to the 10c-2a-2 inspection test cannot be built as written (ANSWERED 2026-10-08: (a), owner exception for this one test; answer in docs/010)

Your answer to Q-2026-10-08-49 is recorded (docs/010, above). The read-only check found nothing that assumes one inspection chain per Lease. The 10c-2a-4 pre-code design is in the plan. There is no 10c-2a-4 code and no run.

**The problem.** Your answer (a) says the 10c-2a-2 inspection test changes "as the plan says". The plan says: "a supersede after closure is now refused; its lock part keeps a Settlement still open or moves to a Lease without a closed Settlement". That cannot be built:

- The test is `test_an_inspection_correction_waits_for_the_step_and_its_line_is_then_no_pet_damage` (`test_settlement_correction_plan_migration.py`, sub-slice 10c-2a-2).
- Its lock part holds the Lease row lock with the post-settlement correction step (`app.post_settlement_correction_plan`). A superseding inspection command waits on that lock. When the holder rolls back, the supersede is written, the line stops being pet damage, and the Pet Deposit can no longer pay it as pet damage.
- The step runs only inside a correction of a closed Settlement. So the lock part cannot use an open Settlement, or a Lease without a closed Settlement.
- After 10c-2a-4, the supersede in this test is refused. Its last part ("its line is then no pet damage") can no longer happen after closure.

**What the design keeps.** The new refusal reads the Lease's Final Settlement row `FOR SHARE` after the command's Lease row lock, as the 8e-1 refusal does. The Settlement confirm and every correction lock the Lease row `FOR UPDATE` first. So a supersede that waits while the Settlement closes sees the closure and is refused. The wait in this test is therefore still real and still matters.

**Options:**

- (a) Keep the test on the closed Settlement. Its lock part stays line for line: the step holds the Lease row lock, the superseding command waits (`blocked_by`, unchanged). The end changes: after the holder rolls back, the command is refused with the new conflict (P5S01) and writes nothing; the line stays pet damage; the step then pays it from the Pet Deposit as pet damage. The name stays (run rule), although its last words describe the behaviour before 10c-2a-4; the docstring, a comment and a docs/010 note say so. More than one expectation changes, so this is an owner exception like Q-2026-10-07-47.
- (b) Move the lock part to an open Settlement, with the Settlement confirm (8e-3) as the lock holder instead of the step. The supersede waits on the confirm's Lease lock; the confirm rolls back; the supersede is written and the line is no longer pet damage. This is close to a new test with another holder, and it no longer tests the correction step's lock.
- (c) Keep the lock part on the closed Settlement, but with an independent inspection (it supersedes nothing). It waits on the step's lock and is then written; the line stays pet damage; the step pays it as pet damage. The refusal itself is tested only in the new 10c-2a-4 module.

**Recommendation: (a).** It keeps the lock part unchanged, shows the refusal at the place where the step runs, and shows that the closed Settlement's pet-damage line does not change. The new 10c-2a-4 module adds a two-connection test of the race the lock order closes: a supersede that waits on the Settlement confirm's Lease lock is refused once the confirm commits.

**For your information (no answer needed unless you disagree):**

1. The 10b test. Its set-up becomes: the closure-time inspection is superseded before the Settlement closes (allowed), then the Settlement closes, then the damage found after closure is recorded as a separate inspection that supersedes nothing. Every assertion stays as at HEAD, including the refusal of the old billed finding as "not on the current inspection" (a finding superseded before closure is still not current after closure). The only part that can no longer happen after closure is recording later damage by a supersede; the new module tests that refusal.
2. An exact repeat (same command key and request) of a supersede committed before closure still returns its saved response after closure. It writes nothing, so it does not change what the Settlement relied on.
3. A supersede of an inspection recorded after closure is refused too (your answer: every supersede on that Lease).

Until you answer, no 10c-2a-4 code.

**Owner answer (2026-10-08).** Option (a), as an owner exception like Q-47, for this one test only.

- Keep the lock part on the closed Settlement. The test must show that the superseding command waits for the step's Lease lock and is then refused (P5S01), and that the line stays pet damage and is paid from the Pet Deposit.
- Keep the test's name. Its docstring and docs/010 say that its last words describe the old behaviour, and why.
- The step's own re-check of pet damage stays as a second guard. If no command can reach it any more, docs/010 says so.
- The independent reviewer compares the test with its version at HEAD and confirms the lock is still proved.
- The 10b test change is accepted as described above.
- Use exact-text edits for the questions file too, also when adding at the end; this rule is added to ops/V1_055_RUN_RULES.md for every later session.

Recorded in docs/010. 10c-2a-4 is built under the takeover rules and the design in the plan.

## Q-2026-10-08-51 — Sub-slice 10c-2a-4 stopped after review round 1: a supersede in a REPEATABLE READ transaction can miss the closure (the fix is a further tightening) (ANSWERED 2026-10-08: (a), tightening approved; answer in docs/010)

10c-2a-4 is built and green before review: backend unit U1 3590 passed, full PostgreSQL P1 1937 passed. Record: ops/reviews/V1-056-slice-10c-2a-4-inspection-supersede-after-closure.md. Review round 1: no blocker; both reviewers found the same should-fix (below). The other findings are fixed in the working tree (a stricter lock-wait check, lock-order wording, a replay test); static checks clean; no run since. Nothing committed.

**The gap.**
- The refusal reads the Lease's Final Settlement row `FOR SHARE` after the Lease row lock. At READ COMMITTED (the only isolation the service uses) this is safe: a supersede that waited while the Settlement closed reads the closure.
- At REPEATABLE READ or SERIALIZABLE the transaction's snapshot is taken at its first statement. If that snapshot is older than the Settlement's start, the Settlement row is not visible: the read finds no row, the insert trigger (same snapshot) finds none either, and the Lease row lock raises nothing, because the Settlement start and confirm lock the Lease row but never change it.
- So a session that opens a REPEATABLE READ transaction before the Settlement starts, waits until the Settlement is closed, and then calls the inspection command can still supersede the inspection the closed Settlement relied on.
- Only a direct database session with the financial role can do this. No screen or service path can.
- My design note said "at REPEATABLE READ the row lock fails with 40001"; that holds only when the Settlement row is in the snapshot (the committed test covers that case).

**Options:**
- (a) Refuse a supersede outside READ COMMITTED: in the command and in the insert trigger, a row with `supersedes_inspection_id` is refused unless the transaction runs at READ COMMITTED (55000, "A move-out inspection is superseded only at READ COMMITTED"), as the Settlement confirm and every correction confirm already require. This also refuses such a supersede before closure. No service path changes, because the service always writes at READ COMMITTED. An inspection that supersedes nothing is not affected. Tests: a REPEATABLE READ snapshot taken before the Settlement starts is refused (55000, nothing written); the existing REPEATABLE READ test then expects 55000; SERIALIZABLE the same. It is a further tightening beyond your words ("after closure"), so it needs you.
- (b) Keep the code. Narrow the wording (docs/004, docs/010, the migration text, the test docstring) to "when the Settlement row is in the snapshot", and record the rest as a known limit: a direct financial-role session at REPEATABLE READ or SERIALIZABLE whose snapshot predates the Settlement start can still supersede after closure.

**Recommendation: (a).** Your rule says every supersede after closure is refused; (a) is the only way the database can guarantee it. The cost falls only on a direct database session that no product path uses.

After your answer: the fix, the docs, static checks, U2 and P2 (under `caffeinate`), then review round 2.

Until you answer, no further 10c-2a-4 change and no commit.

**Owner answer (2026-10-08).** Option (a). This tightening is approved.

- Refuse any inspection supersede outside READ COMMITTED with 55000, before and after closure, as the Settlement confirm and the correction confirms already do.
- No screen or service path changes. If any existing test supersedes outside READ COMMITTED, name it in the report and change only that expectation.
- Add a test for the gap itself: a REPEATABLE READ transaction that started before the Settlement existed is refused when it tries the supersede after closure.
- Fix the design note that said the row lock fails with 40001.
- Then static checks, U2 and P2 under `caffeinate`, then review round 2 under the standing round-3 rule. After 10c-2a-4 is committed, 10c-2a-5 may follow.

Recorded in docs/010.

## Q-2026-10-08-52 — Sub-slice 10c-2a-5 report: six owner items from review rounds 1 and 2 (ANSWERED 2026-10-08; answers in docs/010)

10c-2a-5 was stopped at about 65% context after review round 2, with the round-2 fixes in the working tree and not run (record: ops/reviews/V1-056-slice-10c-2a-5-pet-classification-correction.md). The report named six owner items:

1. The committed `REFUND` confirm (10c-2a-3) does not check the Customer choice again at the confirm. A `PET_DAMAGE_RECLASSIFICATION` confirmed first that leaves the balances unchanged lets a `REFUND` draft with the same choice confirm. Suggested fix: move the re-check into the shared step, a change to committed behaviour.
2. The 10c-2a-1 Deposit application reversal check is not bound to the correction draft's list of reversals (`reversed_applications`, `released_sources`); only owner or definer code can write the table.
3. "A new Customer choice" is compared as exact text; a reworded earlier consent passes.
4. A Damage line billed from a finding of an inspection superseded before closure has no pet classification fix after closure (10c-2a-5 refuses it).
5. The to-pet-damage reversal branch is reachable only from a hand-built state until 10c-2b or 10d returns value to a Pet Deposit.
6. Which Deposit applications the confirm reverses (choice (1) of the docs/010 entry), and the behaviour at a normal end (a line moved to not pet damage is paid by the remaining Pet Deposit with a staff reason).

**Owner answer (2026-10-08).**

1. Yes, this tightening is approved. Every correction confirm that uses a Customer choice re-checks it, including the committed `REFUND` confirm from 10c-2a-3. Make the change in the shared step, with a test. Build it as a small sub-slice right after 10c-2a-5 is committed. (Plan: sub-slice 10c-2a-6.)
2. Add the binding of the 10c-2a-1 reversal check to the draft's list of reversals to the slice 12 list.
3. The exact-text comparison is accepted. docs/010 records it as a known limit: the system cannot prove that a Customer gave a choice again, so the `financial.approve` holder who confirms is the real check.
4. Do not stop for this now. Write the case here with the recommended fix path, and add it to the plan before 10h. The owner answers it before 10h. (Q-2026-10-08-53.)
5. Accepted. Whichever of 10c-2b or 10d first returns value to a Pet Deposit must add a test of the to-pet reversal on a real path, not a hand-built state. In the plan.
6. The reading of which Deposit applications are reversed is confirmed, in both directions. The behaviour at a normal end is also confirmed: a line moved to not pet damage is paid by the remaining Pet Deposit with a staff reason (DL-032 step 5), because no Deposit is refunded while the line still owes.

Recorded in docs/010.

## Q-2026-10-08-53 — A Damage line billed from an inspection superseded before closure has no pet classification fix after closure (not blocking; the owner answers before 10h) (ANSWERED 2026-10-10: (a); sub-slice 10c-2a-7 before 10h; answer in docs/010)

Found in sub-slice 10c-2a-5 review rounds 1 and 2 (security note N2, independent note N2). Owner answer 4 to Q-2026-10-08-52: not a stop; the case is written here with a recommended fix path and placed in the plan before 10h.

**The case.**
- `app.invoice_line_is_pet_damage` reads the finding's flag only while the finding's inspection is current (no other inspection supersedes it). A Damage charge keeps the id of the finding it was billed from.
- Before closure, a supersede of the inspection therefore makes every line billed from the old inspection no longer pet damage, even when the new inspection repeats the same pet finding (Q-2026-10-07-45, "Also"; still open).
- The Settlement then lets the Security Deposit pay such a line first (DL-032 step 4), and the Pet Deposit only at step 5.
- After closure no supersede is possible (10c-2a-4). The `PET_DAMAGE_RECLASSIFICATION` correction (10c-2a-5) is the only fix for a wrong classification, and as built it refuses such a line ("a finding of a current inspection", docs/010 choice (10)), so that the open "Also" point was not decided inside 10c-2a-5.
- Result: when the damage on such a line was caused by the pet, nothing can mark the line as pet damage after closure. Only that direction is concerned: the line already reads as not pet damage.

Example: inspection A has a pet finding, billed as a 12,500 Damage line. Before closure staff supersede A with inspection B to add another finding; B repeats the pet finding, but the line still points to A's finding. At closure the Security Deposit pays the line at step 4, and the Pet Deposit is refunded or pays other debt at step 5.

**Options:**
- (a) Relax the 10c-2a-5 eligibility: a Damage line billed from a finding of any move-out inspection of the Lease, including one superseded before closure, may take a `PET_DAMAGE_RECLASSIFICATION` correction. The reader already lets the latest classification record decide before the inspection rule, so only the eligibility function `app.settlement_pet_classification_line` changes (it is called by the recorder and by the classification insert check). The same-classification refusal then allows only the to-pet direction for such a line. The to-pet reversal rule stays as confirmed (answer 6 to Q-52): the line's Security Deposit applications are reversed only while a Pet Deposit on the DL-032 path holds money; otherwise only the record is written. A relaxing migration in one small sub-slice before 10h, with tests: a line from an inspection superseded before closure set to pet damage (with and without a Pet Deposit holding money); the to-not-pet direction for such a line refused as the same classification; the evidence reference names the new inspection's finding.
- (b) Carry a finding forward on supersede (the Q-45 "Also" recommendation): a link from the new finding to the old one, and the reader treats a carried pet finding as current. This helps future supersedes before closure, but not a Settlement already closed: after closure no supersede is allowed, so no link can be added. Closed cases would still need (a) or a known limit.
- (c) Known limit: such a line keeps its classification after closure. Staff can change only the charge, with the other kinds (`CHARGE_REDUCTION`, `REFUND`, `EXTRA_CHARGE`).

**Recommendation: (a)**, in a small relaxing sub-slice before 10h. The classification record is already the source of truth after closure; (a) only lets staff use it for these lines, under the same `financial.approve` confirm. The "Also" point (b), for the time before closure, stays open for a later decision.

Until the owner answers, nothing changes; 10c-2a-5 keeps refusing such a line.

**Owner answer (2026-10-10).** Yes, the recommendation (a). A small relaxing sub-slice lets the pet classification correction accept a line billed from an inspection superseded before closure. It allows only the change to pet damage.

Recorded in docs/010; the plan names it sub-slice 10c-2a-7 (before 10h; order in the plan's "Owner answers of 2026-10-10" line).

## Q-2026-10-08-54 — Sub-slice 10c-2a-6 stopped before code: the Customer choice re-check in the shared step refuses one committed test (ANSWERED 2026-10-08: (a); answer in docs/010)

10c-2a-5 is committed (8b9a1ca; NOW.md bb571e7). The 10c-2a-6 pre-code design is in the plan (10c-2a-6 entry). There is no 10c-2a-6 code and no run.

**Your rule (answer 1 to Q-2026-10-08-52).** Every correction confirm that uses a Customer choice re-checks it, including the committed `REFUND` confirm. The change goes into the shared step (`app.post_settlement_correction_plan`), with a test.

**The design.** The step re-checks the choice exactly as the recorders and the 10c-2a-5 confirm check it: the text may not equal the confirmed Final Settlement's choice, nor the choice of any other confirmed correction of that Settlement (55000, the same messages). It runs under the Settlement's draft lock, before the stale comparison.

**The conflict.**
- The committed 10c-2a-2 test `test_a_br_dep_027_termination_after_closure` (`test_settlement_correction_plan_migration.py`) builds a correction by hand, with no recorder, and runs the step.
- Its plan uses the `CUSTOMER_CHOICE` basis with the Final Settlement's own choice text (`CHOICE.customer_choice`). The 10c-2a-2 round-3 review named this test (Q-2026-10-07-44, note 7) before your answer 3 required a new choice per correction; only the recorders built later enforce it.
- With the re-check in the step, the test's `post` is refused (55000, "the Final Settlement's choice is not reused"). The test would fail.
- A read-only search of every backend test found no other test that runs the step, or confirms two corrections of one Settlement, with a reused choice.

**Options:**
- (a) The step re-checks both parts (the Settlement's choice and every earlier confirmed correction's choice), as designed. The committed test changes its set-up only: the hand-built correction's choice becomes a new text given for that correction (your answer 3 to Q-2026-10-07-44). Its name and every assertion stay; the Deposit application's reason in the test is the choice's staff-reason field, which does not change. docs/010 note; the independent reviewer compares the test with its version at HEAD.
- (b) The step re-checks only the choices of earlier confirmed corrections, the only part that can change after a draft is recorded. The Final Settlement's choice is fixed at closure, every recorder refuses it, and the 10c-2a-5 confirm checks it again. No committed test changes. The difference: a correction built by hand by the table owner (no recorder) could still reuse the Settlement's choice; no role can do that.

**Recommendation: (a).** It matches your words ("re-checks it") and the 10c-2a-5 confirm, so every variant checks the same thing in one place, and it brings the old test in line with your answer 3. The cost is a set-up change in one committed test.

Until you answer, no 10c-2a-6 code.

**Owner answer (2026-10-08).** Option (a).

- Keep the full re-check in the shared step. It refuses the Final Settlement's own choice text and any earlier confirmed correction's choice.
- In `test_a_br_dep_027_termination_after_closure`, change only the choice text to a new one. Its name and every assertion stay the same. The change is listed in docs/010.
- The independent reviewer compares that test with its version at HEAD and confirms it was not weakened.
- Then build 10c-2a-6 and continue with 10c-2b under the same rules.

Recorded in docs/010.

## Q-2026-10-08-55 — Sub-slice 10c-2b stopped before code: four rule points for the returned-Refund correction, and two paths that move a closed Settlement's Deposit money without a correction (ANSWERED 2026-10-08: yes to points 1 to 4; points 5 and 6 approved tightenings; answers in docs/010)

10c-2a-6 is committed (94230f2; NOW.md 36c14bb). The 10c-2b pre-code design is in the plan (10c entry, "10c-2b pre-code design"), with a proposed split into 10c-2b-1 (a correction's Credit Refund), 10c-2b-2 (a Deposit Refund) and 10c-2b-3 (the refund-only form). There is no 10c-2b code and no run.

**What exists (read-only path search, head `20261110_106`).**
- A Settlement Deposit Refund (8d) and a correction's Deposit Refund can never be returned today: the one-call return and its reversal are refused for every Deposit Refund without a Pet Refund review, with no pass for a correction. 10c-2b-2 relaxes this only for a return linked to a correction confirmed in the same transaction.
- A correction's Credit Refund can still be returned with one call. Your approved tightening (answer 4 to the 10c-1b review record) closes this in 10c-2b-1.
- A return gives the value back to its source: the Credit, or the Deposit (DB-DER-004).

**Rule points (my reading first; please confirm or correct):**

1. **A returned Credit Refund with a new Refund in the same correction.** Your answer 2 to Q-2026-10-07-42 says every Refund correction first uses released Credit against its own Customer's open debt on this Lease. Recommendation: the same here. The returned value goes back to the Credit; the correction runs the shared step, so that Credit first pays its Customer's open debt on this Lease (Rent first or the Customer's designation, BR-CREDIT-006), and only the rest is refunded to the same Customer. A Customer with no open debt on the Lease gets the whole new Refund.
2. **A Credit left by a return-only correction.** Your answer 4 to Q-2026-10-07-41 says the returned amount stays as that Customer's Credit "until a later correction refunds it". Recommendation: the refund-only form (10c-2b-3) refunds it inside a correction. The Customer may also apply it with the ordinary Credit application (your note under Q-42). The ordinary Credit Refund draft (`refunds.create`, `financial.approve`) stays as it is for any Credit; no new tightening.
3. **A returned Deposit Refund with a new Refund in the same correction.** Your answer 3 to Q-42 says the returned amount stays with the Deposit "until a later correction" pays the Lease's open debt in the DL-032 order and refunds the rest. Your answer 4 to Q-41 lets the returned-Refund correction carry the new Refund. Recommendation: both forms. Return only: the Deposit holds the amount. Return with a new Refund: the same correction runs the shared step after the return (open debt in the DL-032 order, every Settlement rule and the Customer choice rules), and only the rest is refunded.
4. **Names.** `REFUND_RETURN` for the returned-Refund correction (with or without a new Refund) and `HELD_VALUE_REFUND` for the refund-only form. Both are variants of the `SETTLEMENT_CORRECTION` draft kind, prepared under `final_settlements.prepare` and confirmed under `financial.approve`.

**Two paths that move a closed Settlement's Deposit money without a correction (each a tightening, so each needs you):**

5. **The receipt reversal draft (8r).** It has no closed-Settlement check. It is held back only by an active Deposit application, an active forfeiture, an unresolved Deposit Refund or a pending draft. Once a Deposit holds money again after closure with none of those (for example, after a return-only correction of its Refund), a receipt reversal draft confirmed by `financial.approve` can send that money back to the Payment. A one-call allocation can then use it, with no correction. Options:
   - (a) After closure, refuse the receipt reversal draft of a Lease Deposit, at record and at confirm (P5S01, a conflict). A bounced receipt Payment after closure is handled by the `RETURNED_PAYMENT` correction (10e).
   - (b) Leave it; approval by `financial.approve` is enough.
   **Recommendation: (a)**, in 10c-2b-2, because your rule is that a closed Settlement's money changes only through a linked correction.
6. **A Pet Refund-review Refund (DL-053) after closure.** It was paid while the Lease was active. After closure its one-call verified return still adds value back to the Pet Deposit, and its one-call reversal takes it out again, with no draft and no approver. Options:
   - (a) After closure, refuse both one-call paths for such a Refund (P5S01). Its return then goes through the 10c-2b `REFUND_RETURN` correction, as for a Settlement Deposit Refund.
   - (b) Leave it.
   **Recommendation: (a)**, in 10c-2b-2. This path existed before 10c-2b; it is not caused by it.

For your information: the Lease forfeiture draft and the forfeiture reversal draft also work after closure without a correction. The reversal is already planned to run only inside a `FORFEITURE_REVERSAL` correction (10d, refused in 10h). A forfeiture draft after closure needs a forfeiture ground and money held, so it reaches only a Deposit that holds money again after a forfeiture reversal. I recommend that 10d refuses it after closure in the same way; no answer is needed now.

**What can go ahead.** 10c-2b-1 does not depend on points 3, 5 and 6. Its return-only form follows your answer 4 to Q-41 as written. Its form with a new Refund depends on point 1. If you agree, the next session builds 10c-2b-1 after your answer to point 1, then 10c-2b-2 after points 3, 5 and 6.

Until you answer, no 10c-2b code.

**Owner answer (2026-10-08).**

1. Yes. A returned Credit Refund's Credit first pays its own Customer's open debt on this Lease, as in every Refund correction (Q-42 answer 2). This holds whether or not the same correction pays a new Refund. Only the rest is refunded, or stays as that Customer's Credit.
2. Yes. Credit left by a return-only correction is that Customer's Credit, as in the Q-41 answer 4. A later correction may refund it, and the ordinary Credit paths stay as they are.
3. Yes. A returned Deposit Refund goes back to the Deposit. When the same correction pays a new Refund, the Deposit value first pays this Lease's open debt in the DL-032 order, with all Settlement rules. Only the rest is refunded.
4. Yes, use the names `REFUND_RETURN` and `HELD_VALUE_REFUND`.
5. Yes, this tightening is approved. After closure, refuse the receipt reversal draft of a Lease Deposit. A Deposit receipt found wrong after closure, for example a bounced Payment, is fixed only through a post-settlement correction. Name that correction kind in the plan. If none fits, write it in this file with a recommendation and stop.
6. Yes, this tightening is approved. After closure, refuse the one-call return of a Pet Refund-review Refund and its reversal, as the Q-40 point 4 answer did for correction Credit Refunds. Such a return is handled by the 10c-2b-2 returned Deposit Refund correction. Test it there.

Recorded in docs/010. Next: 10c-2b-1, 10c-2b-2 and 10c-2b-3 in order.

## Q-2026-10-08-56 — Sub-slice 10c-2b-2 stopped before code: no planned correction kind fixes a Deposit receipt that is wrong for a reason other than a returned Payment (owner answer 5 to Q-2026-10-08-55) (ANSWERED 2026-10-08: (a), and the refusal is built now; answers in docs/010)

10c-2b-1 is committed (be4919a; NOW.md 5148684). Your answer 5 to Q-55 approves refusing the receipt reversal draft of a Lease Deposit after closure, and says a Deposit receipt found wrong after closure is fixed only through a post-settlement correction whose kind the plan names; if none fits, ask first. There is no 10c-2b-2 code and no run.

**What the planned kinds cover.** A Deposit receipt is Payment value placed in a Deposit (DB-DEP-002: the Deposit, the Payment, the amount).
- A receipt whose Payment bounced or was returned: the planned `RETURNED_PAYMENT` kind (sub-slice 10e, your answer 5 to Q-2026-10-06-36) fits. In one correction it reverses the Settlement's Deposit applications of a Deposit that Payment funded, the receipt and the Payment; a Settlement Refund already paid from that Deposit becomes an `EXTRA_CHARGE` to the Deposit owner. I will name it in the plan.
- A receipt that is wrong while its Payment is real (for example, the Payment was meant for Rent but recorded into the Security Deposit, recorded into the wrong Deposit of the Lease, or for the wrong amount): no planned kind fits. `RETURNED_PAYMENT` needs a returned Payment; the other kinds (`EXTRA_CHARGE`, `CHARGE_REDUCTION`, `REFUND`, `PET_DAMAGE_RECLASSIFICATION`, `REFUND_RETURN`, `HELD_VALUE_REFUND`, `ADJUSTMENT_REVERSAL`, `FORFEITURE_REVERSAL`, `PAYMENT_MOVE`) do not reverse a receipt.

**Options for such a receipt after closure:**
- (a) A new correction kind, `DEPOSIT_RECEIPT_CORRECTION` (a variant of the `SETTLEMENT_CORRECTION` draft kind; Staff record it under `final_settlements.prepare` with a reason and evidence; only `financial.approve` confirms). It reuses the `RETURNED_PAYMENT` records without the Payment reversal: it reverses, as linked records, the Settlement's Deposit applications of that Deposit and the receipt; a Settlement Refund already paid from that Deposit becomes an `EXTRA_CHARGE` to the Deposit owner (money that left the Property cannot be undone); the freed Payment value becomes the payer's Customer Credit, which first pays that Customer's open debt on the Lease through the shared DL-032 step, and only the rest is refunded or kept as Credit (your Q-42 and Q-55 rules). Built right after 10e, which builds the shared records.
- (b) No fix kind: after closure, a receipt wrong for a reason other than a returned Payment stays as the closure used it (a known limit in docs/010); staff fix only the money still open, with the existing kinds.

**Recommendation: (a)**, because your answer 5 says a wrong receipt is fixed only through a correction, and (b) would leave such a receipt with no fix. Until the new kind exists, a wrong receipt after closure waits, as a wrong Late-payment Charge waited for 10c-3.

**Also, please confirm:** 10c-2b-2 may build the approved refusal of the receipt reversal draft after closure now, before 10e and the new kind exist. In that time a bounced Deposit Payment after closure also has no fix (as today for a bounced Payment whose Credit the Settlement used, accepted until slice 10). Recommendation: yes; the refusal only removes a path that moves a closed Settlement's money without a correction.

Until you answer, no 10c-2b-2 code. 10c-2b-3 waits for 10c-2b-2.

**Owner answer (2026-10-08).**

1. Yes to the recommendation. A Deposit receipt whose Payment bounced is fixed by `RETURNED_PAYMENT` (10e). A Deposit receipt that is wrong while its Payment is real gets a new correction kind, `DEPOSIT_RECEIPT_CORRECTION`, built right after 10e. It follows all Settlement rules and the DL-032 order, like the other corrections.
2. Yes, 10c-2b-2 may build the approved refusal of the receipt reversal now. Until `DEPOSIT_RECEIPT_CORRECTION` exists, such a receipt has no fix after closure. Write this gap in docs/010 and in the plan. It must be closed before V1-056 ends.

Also answered with the 10c-2b-1 report: docs/010 choice (1) is kept as built (the new Refund is what is left in the Credit after the debt is paid, at most the returned amount; the whole Credit pays the debt first, as the Q-43 answer); docs/010 choice (6) is accepted for now, and the fix path for a return recorded by mistake is Q-2026-10-08-57, answered before 10h together with Q-2026-10-08-53.

Recorded in docs/010. Next: 10c-2b-2, then 10c-2b-3.

## Q-2026-10-08-57 — The fix path for a return recorded by mistake (docs/010 choice (6) of sub-slice 10c-2b-1; not blocking; the owner answers before 10h, with Q-2026-10-08-53) (ANSWERED 2026-10-10: (a); sub-slice 10e-3 before 10h; answer in docs/010)

**The gap.** A `REFUND_RETURN` correction records that a Refund's money came back (a verified return, DB-REFUND-002). That return can never be reversed: the one-call reversal is refused for a correction's Refund and for a Settlement Deposit Refund, and the Refund correction check accepts no reversal row. If the money did not really come back (for example, the bank later takes the returned transfer back), the records show value in the Credit or the Deposit that the Property does not hold. By then the same correction may have used that value: its DL-032 step may have paid the Customer's debt (Settlement Credit applications or Deposit applications linked to the correction), and a new Refund may have paid it out again.

**Options:**
- (a) A new correction variant, `RETURN_REVERSAL` (a variant of the `SETTLEMENT_CORRECTION` draft kind; Staff record it under `final_settlements.prepare` with a reason and evidence; only `financial.approve` confirms), for one return recorded by an earlier correction of the same Settlement. In one transaction, each record linked before it is written: the earlier correction's Credit applications and Deposit applications paid from that value are reversed, so the debt comes back on its obligations and stays on its Customers' ledgers (BR-SETTLE-016); the return is reversed (a linked `CORRECTION_REVERSAL` row, the only one the Refund correction check would accept); and any part of the value that has already left the Property again (a new Refund paid from it) becomes an `EXTRA_CHARGE` to that Customer, as `RETURNED_PAYMENT` does for a Settlement Refund already paid. Built before 10h, after 10e (it shares the 10e rule for an `EXTRA_CHARGE` in the same correction as the step).
- (b) No reversal: a return recorded by mistake is fixed only with an `EXTRA_CHARGE` correction to the Customer for the amount; the return record stays, so the history shows a return that did not happen.

**Recommendation: (a)**, because it keeps the history true (the wrong return is reversed by a linked record, not hidden behind a charge) and puts the debt back where it was. It is added to the plan before 10h.

**Owner answer (2026-10-10).** Yes, the recommendation (a). A `RETURN_REVERSAL` correction undoes what the wrong return paid and reverses the return. Any part that was already refunded again becomes an `EXTRA_CHARGE`.

Recorded in docs/010; the plan names it sub-slice 10e-3 (after 10e and the sub-slice for Q-2026-10-09-61, before 10h).

## Q-2026-10-08-58 — Sub-slice 10c-2b-2a stopped before its first run: the lint correction allowance for one cause is used up (a docstring line I re-wrapped twice) (ANSWERED 2026-10-08: (a), owner exception; answer in docs/010)

Your answers to Q-2026-10-08-56 and to the 10c-2b-1 report are recorded (docs/010, this file with Q-2026-10-08-57, the plan; not committed yet). 10c-2b-2 is split (a split needs no owner answer): **10c-2b-2a** the returned Settlement and correction Deposit Refunds, the approved receipt reversal refusal after closure, and the to-pet-damage test on the real path; **10c-2b-2b** the Pet Refund-review Refund after closure (the approved one-call refusal and its return through the correction; it needs a new test fixture, because no fixture pays a Pet Refund-review Refund on a Lease that later closes).

**What is built (working tree, not committed, not run):** migration `20261112_108` (the `REFUND_RETURN` correction also returns a Settlement Deposit Refund and a correction's Deposit Refund; return only leaves the amount held by the Deposit with no step; with a new Refund the step runs; the receipt reversal recorder and its insert check refuse a closed Settlement's Lease Deposit, P5S01; the relaxed return check also binds the reason), the receipt reversal service maps P5S01 to a conflict, the new test module `test_settlement_deposit_refund_return_migration.py`, the 27 head-revision assertions, and one changed committed test (below). Format and type checks are clean. No migration-only check and no test run yet.

**The stop.** Lint failed on two findings in `test_settlement_refund_return_migration.py`, both from my edit of the 10c-2b-1 test `test_a_returned_refund_correction_refuses_wrong_input_and_a_stale_draft_waits`: import order (fixed) and one docstring line over 100 characters. My two exact-text corrections of that docstring each moved the overlong text to the next line instead of wrapping it, so the line is still too long (E501, line 562). That is two corrections for one cause, and your rule allows at most two.

**The change to the committed 10c-2b-1 test** (needs a docs/010 note under the narrowing rule): that test used the Settlement's own Pet Deposit Refund as "a Refund no correction paid"; 10c-2b-2a makes that Refund returnable, so the test now uses an ordinary Credit Refund (the Customer's own 300 of Credit, refunded through its draft); the expected refusal (55000, "The returned Refund is not a Refund this correction may return"), the test name and every other assertion stay.

**Options:**
- (a) Owner exception for this one cause: one more correction, text only (re-wrap the docstring paragraph so every line is within 100 characters), then the static checks each in its own call, the migration-only check, the read-only search, the unit and PostgreSQL runs, and the review rounds under the standing rules.
- (b) Stop 10c-2b-2a here; the next session starts it again from the working tree.

**Recommendation: (a).** The fix is text only and changes no behaviour.

Until you answer, no further edit and no run.

**Owner answer (2026-10-08).** Option (a), as an owner exception: one more text-only fix, re-wrapping that docstring so every line is within the limit; if lint still fails, stop. (Done: lint passed.) The change to the committed 10c-2b-1 test is accepted: it now uses an ordinary Credit Refund as the Refund that cannot be returned, because answer 3 to Q-55 makes the Settlement Deposit Refund returnable; its name and all its checks stay; a docs/010 note is added and the independent reviewer compares it with its version at HEAD. Check for the reviewers: a returned Deposit Refund on a path other than DL-032 (for example, the Pet Deposit rest refunded at a BR-DEP-027 termination) must still have a way to be refunded again, through 10c-2b-3 or another planned step; if it has none, write it here with a recommendation.

Recorded in docs/010. Next: 10c-2b-2a checks, runs and reviews, then 10c-2b-2b and 10c-2b-3.

## Q-2026-10-08-59 — Sub-slice 10c-2b-2a stopped after review round 1: a returned Deposit Refund can be forfeited again after closure (your path check), and three smaller points (ANSWERED 2026-10-08: 1 (a), 2 allow it, 3 (b), 4 (a); answers in docs/010)

10c-2b-2a is built and green but not committed: U1 3629 passed, full PostgreSQL P1 1964 passed (targeted T1 failed on a test helper, corrected once; record: ops/reviews/V1-056-slice-10c-2b-2a-deposit-refund-return.md). Review round 1: independent 1 blocker, 2 should-fix, 4 notes; security 1 should-fix (the same as independent SF1), 5 notes. The independent reviewer compared the changed 10c-2b-1 test with HEAD: not weakened. All files are in the working tree; no fix is made yet.

**1. Your check (independent SF1, security SF1).** Every Deposit Refund that 10c-2b-2a can return (a Final Settlement Deposit Refund, or a correction's) was paid while its Deposit was on the DL-032 path.
- A Deposit with no forfeiture ground stays on DL-032 for good. That is every Pet Deposit except at a BR-DEP-022 customer-violation termination, so your example, the Pet Deposit rest at a BR-DEP-027 termination, is included. It can always be refunded again: in the same correction with a new Refund (the BR-DEP-027 Pet rules apply), by any later correction that runs the step, or by the 10c-2b-3 refund-only form.
- A Deposit with a ground (BR-DEP-022, BR-DEP-023, BR-LEASE-005, BR-LEASE-025, BR-LEASE-028) is on DL-032 only because its forfeiture was reversed. After a return-only correction it holds money after closure, and nothing stops a new Lease forfeiture draft: the forfeiture draft and the disposition insert have no closure check. That forfeiture changes the closed Settlement's money without a correction (against BR-SETTLE-013) and moves the Deposit to KEPT; a later return of the same Refund is then held by a KEPT Deposit with no refund path (the step and 10c-2b-3 use only DL-032 Deposits). Before 10c-2b-2a this could not happen, because closure leaves every DL-032 Deposit empty.

Options:
- (a) Approved tightening, in 10c-2b-2a: after the Lease's Final Settlement closes, refuse the Lease Deposit forfeiture draft at record and the `deposit_dispositions` insert for that Lease's Deposit (P5S01, a conflict) unless a correction of that Settlement links the row, as the receipt reversal. Then no returnable Deposit Refund can leave DL-032, and the "only on the DL-032 path" refusal of a new Refund stays as defence in depth. (The forfeiture reversal after closure stays planned for 10d/10h, as you approved in Q-2026-10-06-36.)
- (b) Keep the forfeiture path open; record the gap in docs/010; test the 55000 refusal on that real path.

**Recommendation: (a).**

**2. A Credit return-only correction while a Deposit holds returned money (independent SF2).** A Credit `REFUND_RETURN` always runs the step, and the step needs every DL-032 Deposit balance applied or refunded; a return-only draft may not have a Deposit Refund step. So while a Deposit holds an earlier returned amount that no debt takes, a Credit return-only correction is refused (55000) until that Deposit value is handled. Options: (a) accept it as an order of work: staff first refund the held Deposit value (the 10c-2b-3 refund-only form, or a Deposit return with a new Refund), then record the Credit return; documented in docs/010; (b) let a Credit return-only draft carry a Deposit Refund step with its own method and note. **Recommendation: (a)**, because it keeps one Refund method and note per correction (your answer to the 10c-1b points).

**3. The blocker: the reason binding (independent).** I added a check that the return row's reason equals the draft's (a 10c-2b-1 round-3 note, defence in depth). The committed 10c-2b-1 test `test_the_relaxed_refund_correction_check_accepts_nothing_else` writes its hand-built rows with the reason `'Direct'`, so every one of its attempts is now refused by the reason alone and it no longer proves the other conditions; it still passes. Options: (a) remove the reason binding (no committed test changes; the confirm always writes the draft's reason, and no role can write such a row); (b) keep it and change that committed test so its rows carry the draft's reason, with one more attempt with another reason (an owner exception for a committed test, like Q-58). **Recommendation: (a)**, the smaller change; the binding goes to the slice 12 list.

**4. The receipt reversal recorder at REPEATABLE READ (security N2).** Its closure check is a plain read; a REPEATABLE READ caller whose snapshot predates the closure could record a draft that can never be confirmed but blocks correction steps as a pending draft until rejected (the service always uses READ COMMITTED). Options: (a) refuse recording that draft outside READ COMMITTED (55000), a further tightening like your answer to Q-2026-10-08-51; (b) leave it (only a direct database client can do it). **Recommendation: (a).**

**What I fix without an answer, after your answers:** the return-only plan must be exactly the empty plan (security N3); docs/010 notes on drafts recorded under 107 (they fail closed) and on the reversal branch the future `RETURN_REVERSAL` (Q-57) must switch to `source_deposit_id`; added tests (a stale Deposit return draft; a correction's Deposit Refund returned with a new Refund; the receipt reversal confirm path; the 8d branch for a hand-built mismatched row; BR-REFUND-015 traceability). Then the static checks, the migration check, U2, P2 and round 2 under the standing rules.

Until you answer, no further change and no run. 10c-2b-2b and 10c-2b-3 wait.

**Owner answer (2026-10-08).**

1. Yes, option (a); approved tightening. After closure, refuse the Lease Deposit forfeiture draft at record and the forfeiture row at insert (P5S01), unless a correction of that Settlement links it. If no correction kind can link a forfeiture today, write that here with a recommendation, but do not stop.
2. No order of work. Refunds often come back together (for example from the same closed bank account); staff must be able to record each return before they can pay again. A return-only correction pays nothing out, and a Deposit return-only correction already leaves money held (Q-42 answer 3). So allow a Credit return-only correction while a Deposit holds returned money that no debt can take; that money stays held until a later correction refunds it (10c-2b-3). The returned Credit still pays its own Customer's open debt first (Q-55 answer 1). Add a test. If allowing this breaks another rule, write it here and stop.
3. Option (b), as an owner exception like Q-58. Keep the reason check; change only the set-up of `test_the_relaxed_refund_correction_check_accepts_nothing_else` so it again proves what it proved before; its name and checks stay; add a separate test for the reason check; list the change in docs/010; the independent reviewer compares it with HEAD.
4. Yes, option (a); approved tightening. Refuse recording a receipt reversal draft outside READ COMMITTED, as in the Q-51 answer.

Recorded in docs/010. Next: the fixes, the tests, the runs and review round 2, then 10c-2b-2b and 10c-2b-3.

**Implementer note on the "what I fix" list above (review rounds 1 and 2):** added: the exact empty plan, the docs/010 notes, a stale Deposit return draft test, the 8d branch for a hand-built row (the reason test), BR-REFUND-015 traceability; not added: a correction's Deposit Refund returned with a new Refund and the receipt reversal confirm path (a draft cannot be recorded after closure, and closure waits for pending drafts); see the review record.

**Implementer note on answer 1 (no stop, as you said):** no correction kind can link a forfeiture today: DB-SETTLE-005 has no `deposit_disposition_id` link (it has `deposit_disposition_reversal_id`, for 10d), and no planned kind writes a new forfeiture after closure. So the insert refusal passes nothing yet. Recommendation: no link now; if a later kind ever needs to forfeit after closure, it adds the link and the pass in its own sub-slice (a relaxing change).

**Owner answer to the implementer note on answer 1 (2026-10-09).** The note is accepted. After closure, no correction links a forfeiture for now. If a later correction kind needs one, ask the owner first. Recorded in docs/010.

## Q-2026-10-08-60 — The Lease forfeiture draft recorder outside READ COMMITTED (not blocking; review round 2 of sub-slice 10c-2b-2a) (ANSWERED 2026-10-09: (a), tightening approved; answer in docs/010)

Both round-2 reviewers noted: like the receipt reversal recorder before your answer 4 to Q-59, the Lease Deposit forfeiture draft recorder reads the closure with a plain read and has no READ COMMITTED guard. A direct database caller in a REPEATABLE READ transaction whose snapshot predates the closure could record a forfeiture draft after closure. No money moves (the confirm's insert is refused, P5S01), but while that draft is pending every correction that runs the DL-032 step on that Settlement, and every correction Deposit Refund, is refused as a pending draft until someone rejects or withdraws it. The application services always use READ COMMITTED.

Options: (a) the same rule as your answer 4: refuse recording a Lease forfeiture draft outside READ COMMITTED (55000), a further tightening, in 10c-2b-2b; (b) leave it (only a direct database client can do it).

**Recommendation: (a).** Not blocking 10c-2b-2a.

**Owner answer (2026-10-09).** Yes, this tightening is approved. Refuse recording a Lease Deposit forfeiture draft outside READ COMMITTED (55000), as in the answers to Q-2026-10-08-51 and Q-2026-10-08-59. Build it in 10c-2b-2b, with a test.

Further owner instructions given with this answer (2026-10-09):

- 10c-2b-2b must close the gap named in review round 3 of 10c-2b-2a (security N1): an older one-call return of a Pet Refund-review Refund must not be reversed against Pet Deposit money that a return-only correction left held. Add a test for it.
- Q-2026-10-08-53 and Q-2026-10-08-57 stay open. The owner answers them before 10h. The work does not stop for them.

Recorded in docs/010.

## Q-2026-10-09-61 — A returned Pet Refund-review Refund whose Pet Deposit is not on the DL-032 path has no way out after closure (not blocking 10c-2b-2b; blocks only that case in 10c-2b-3) (ANSWERED 2026-10-10: pay back, before and after closure; sub-slice 10c-2b-5 before 10h; answer in docs/010; follow-up Q-2026-10-10-73)

Found while building 10c-2b-2b (the reviewer check of your answer to Q-2026-10-08-58: a returned Deposit Refund off the DL-032 path must still have a way to be refunded again).

**The case.**
- A Pet Refund-review Refund (DL-053) is paid while the Lease is signed, after the pet left.
- Later the Lease is terminated for pet noncompliance with the customer-violation basis (BR-DEP-022). The Pet Deposit then has a forfeiture ground: "non-refundable ... resolved through explicit disposition events".
- At closure that Pet Deposit is empty (path `NOTHING_HELD`) or its rest is forfeited (path `KEPT`).
- After closure the DL-053 Refund comes back (for example a closed bank account). 10c-2b-2b records the return only through `REFUND_RETURN`, and the money goes back to the Pet Deposit (DB-DER-004). The Deposit is then on the path `FORFEITURE_REQUIRED` (or stays `KEPT` with money held).
- The money has no way out: a forfeiture after closure is refused and no correction links one (your answer of 2026-10-09: ask you first); the step, a new Refund in the same correction and the planned refund-only form (10c-2b-3) use only Deposits on the DL-032 path (55000 otherwise, sub-slice 10c-2b-2a). Tested in 10c-2b-2b on the `KEPT` case (`test_a_returned_pet_refund_off_the_dl032_path_is_only_held`).
- Before closure the two cases differ (review round 2 correction of this text; read from the code, not tested before closure):
  - A Pet Deposit with the ground and no forfeiture (`NOTHING_HELD`): a one-call return before closure makes it `FORFEITURE_REQUIRED`, and the Settlement cannot close until it is forfeited (BR-DEP-022). There the rule is clear.
  - A Pet Deposit already forfeited (`KEPT`): a one-call return before closure leaves money held that the Settlement neither requires forfeiting nor refunds ("a kept Deposit is never refunded"); only an optional second forfeiture draft could take it. So the same gap already exists before closure for a `KEPT` Pet Deposit.
- 10c-2b-2b creates no new held state: before it, the one-call return after closure put the same money into that Deposit (and the one-call reversal could take it out again). No money leaves.

**Options (superseded by the owner instruction of 2026-10-09 below; kept as written):**
- (a) A new correction variant that forfeits such returned value after closure under BR-DEP-022, as a linked forfeiture: a DB-SETTLE-005 link `deposit_disposition_id` and the pass in the disposition insert check (a relaxing change); prepared under `final_settlements.prepare` with a reason, confirmed only by `financial.approve`. It would be the first correction that links a forfeiture, which your answer of 2026-10-09 asks me to bring to you first. For a `KEPT` Pet Deposit it is a second forfeiture (disposition) of a Deposit already forfeited once.
- (b) Treat the returned value as refundable: the refund-only form pays the Lease's open debt and refunds the rest also for a Deposit off the DL-032 path. This goes against BR-DEP-022 ("non-refundable").
- (c) Leave the money held as a known gap (recorded in docs/010) until a later decision.

**Recommendation: (a)** (superseded: the recommendation is now "pay back", below), because BR-DEP-022 says such a Pet Deposit is non-refundable and resolved through explicit disposition events, and a closed Settlement changes only through a linked correction. It would be built after 10c-2b-3, in its own sub-slice.

**What goes ahead (while this question is open, as 10c-2a-1 went ahead while Q-2026-10-07-42 was open):** 10c-2b-2b (it records the return only; nothing leaves). 10c-2b-3 for a Credit and for Deposits on the DL-032 path, which does not depend on this answer; it refuses a Deposit off the DL-032 path (55000), as 10c-2b-2a does. Not built until you answer: anything that moves money out of a Deposit off the DL-032 path after closure.

**Owner instruction (2026-10-09).** Not blocking; keep it open; it is in the plan before 10h, next to Q-2026-10-08-53 and Q-2026-10-08-57; the owner answers all three before 10h. No correction that links a forfeiture is built until the owner answers. The case is written out below so the owner can decide; the options (a) to (c) above are replaced by the two options below.

**The case, step by step (read from the code; the after-closure part is tested in 10c-2b-2b).**

1. *When the Pet Refund-review Refund is paid.* Always while the Lease is signed, so always before the termination and before the closure: the pet left, the review qualified (DL-053), and the Refund draft and its confirm need a signed Lease. It pays part or all of what the Pet Deposit held to the Customer (or an agreed Signer, BR-REFUND-015).
2. *The termination.* Later, the Lease is terminated for pet noncompliance (for example a new pet whose required Pet Deposit the Customer refuses to pay, after three warnings), the BR-DEP-022 customer-violation basis. From then on both Deposits have a forfeiture ground ("non-refundable according to the signed Lease ... resolved through explicit disposition events").
3. *The Final Settlement.* If the Pet Deposit still holds money, the Settlement cannot close until that money is forfeited (path `FORFEITURE_REQUIRED`, then `KEPT`). If the DL-053 Refund took everything, the Pet Deposit is empty (`NOTHING_HELD`) and nothing is forfeited. A kept Deposit is never applied to debt or refunded; the Customer's open debt stays on that Customer's ledger (BR-DEP-026 for the Security Deposit, BR-DEP-027 for the Pet Deposit at this termination, BR-SETTLE-016).
4. *The return.* The DL-053 Refund comes back, for example because the bank account was closed. The money goes back to the Pet Deposit (DB-DER-004). Before closure this is the one-call return; after closure only `REFUND_RETURN` (10c-2b-2b). In both cases the money is money that left the Pet Deposit before the termination.

**Option keep.** The returned money stays with the Pet Deposit and is kept under BR-DEP-022.
- After closure: a new correction variant forfeits the returned amount as a linked forfeiture (a DB-SETTLE-005 link `deposit_disposition_id` and the pass in the disposition insert check, a relaxing change), prepared under `final_settlements.prepare` with a reason, confirmed only by `financial.approve`. For a `KEPT` Pet Deposit it is a second forfeiture of a Deposit already forfeited once; for a `NOTHING_HELD` one it is the first.
- Open debt: unchanged. The kept money never pays the Customer's open debt on this Lease; the debt stays on the Customer's ledger (as BR-DEP-026, BR-SETTLE-016).
- Before closure: for a `NOTHING_HELD` Pet Deposit this is already how it works (the return makes it `FORFEITURE_REQUIRED`, and the Settlement waits for the forfeiture). For a `KEPT` Pet Deposit the returned money stays held and nothing requires a second forfeiture today (only an optional second forfeiture draft, which the code reads as allowed; not tested); option keep needs the Settlement preview to require that second forfeiture too.

**Option pay back.** The returned money is refunded to the Customer again, because it had already left the Pet Deposit before the termination; BR-DEP-022 keeps only what the Deposit held at the termination.
- After closure: the refund-only form (10c-2b-3) or a `REFUND_RETURN` with a new Refund also accepts this Pet Deposit, but only for the returned amount of a Pet Refund-review Refund paid before the termination (a relaxing exception to the "only on the DL-032 path" refusal; the rest of the Deposit stays kept). No forfeiture is linked.
- Open debt: as every returned Deposit Refund (owner answer 3 to Q-2026-10-08-55), the returned money first pays this Lease's open debt in the DL-032 order, with the Settlement rules, and only the rest is refunded. If you prefer that it is refunded in full while the debt stays on the ledger, say so; that would be an exception to answer 3.
- Before closure: today the Settlement would force a forfeiture of that money for a `NOTHING_HELD` Pet Deposit (it becomes `FORFEITURE_REQUIRED`), and for a `KEPT` one it would leave it held. Option pay back needs the Settlement to treat the returned amount of a pre-termination DL-053 Refund as DL-032 value in both cases: no forfeiture required for it, it first pays the open debt, and the rest is refunded by the Settlement's own Deposit Refund step.

**Recommendation: pay back.** The DL-053 Refund was a valid Refund of money that already belonged to the Customer before the termination ground existed; the bank return only means the Customer did not receive it. BR-DEP-022 makes the Deposit non-refundable at the termination, that is, the money it held then. Keeping the returned money would forfeit money that was not in the Deposit at the termination, only because of a failed payment. Paying the open debt first follows your answer 3 to Q-2026-10-08-55 for every returned Deposit Refund. The cost is one exception to the DL-032-only rule, for the returned amount of a pre-termination DL-053 Refund only, and the matching change to the Settlement preview before closure. If the signed Lease says that such money is kept too, choose keep.

**Owner answer (2026-10-10).** Pay back, as the option above describes it, both before and after closure. The returned money had already left the Pet Deposit before the termination, so it is the Customer's money. With this answer, check whether the 10d refusal of a reversal while another forfeiture of the same Deposit is active is still needed, and report it.

Recorded in docs/010; the plan names the work sub-slice 10c-2b-5 (after 10e and 10e-2, before 10h).

**Implementer note on the 10d refusal (2026-10-10, read from the code at head `20261119_115`).**

- A Lease Deposit forfeiture always takes the whole held amount (migration `20261018_83`: the draft stores `app.deposit_held_value_at`, and the confirm refuses a stale amount). So a Deposit gets a second active forfeiture only when it holds money again while its first forfeiture stays active.
- Only two things could add money to a forfeited Deposit: a new Deposit receipt, or the return of a Refund paid from it. The only Deposit receipt writer the application roles may run is `app.create_reservation` (the Reservation's Security Deposit, before any Lease), so no receipt reaches a forfeited Deposit. A kept Deposit pays no Settlement Refund, and after closure a forfeiture is refused unless linked (10c-2b-2a). That leaves the returned Pet Refund-review Refund on a `KEPT` Pet Deposit before closure (this question), as Q-2026-10-10-71 found.
- With pay back, that returned money is the Customer's and must not be forfeited. If sub-slice 10c-2b-5 also makes the forfeiture leave the returned amount out (Q-2026-10-10-73), no Deposit can get a second active forfeiture, and the 10d refusal can no longer be reached.
- Recommendation: keep the 10d refusal as it is. It is still needed until 10c-2b-5 is built, it costs nothing afterwards, and removing it would be a relaxing change with no use. 10c-2b-5 adds a test that a second forfeiture of the returned amount is refused, so the refusal stays a guard only.

## Q-2026-10-09-62 — Sub-slice 10c-2b-2b stopped before review round 3: the known lock failure in a test outside 10c-2b-2b (ANSWERED 2026-10-09: option (a); answer in docs/010)

10c-2b-2b is built, reviewed twice and not committed. Record: ops/reviews/V1-056-slice-10c-2b-2b-pet-refund-return.md.

- Review round 1: no blocker; 2 should-fix (tests), fixed. Review round 2: no blocker; independent 2 should-fix (documentation), fixed; security none. So the standing rule allows one round 3, after one full unit run and one full PostgreSQL run.
- U4 (full unit): 3635 passed.
- P2 (full PostgreSQL): 1973 passed, 1 failed. The new 10c-2b-2b module passed (6 tests). The failure is outside 10c-2b-2b: `test_refund_migration.py::test_usd_refund_blocks_source_reversal_until_full_verified_return[False]`, `LockNotAvailable` on `app.payment_allocations` from `LOCK TABLE ... IN SHARE MODE NOWAIT` in `app.assert_payment_excess_eligible`, during a direct Payment Refund insert. The same test passed in P1 (1972 passed) on the same code paths: the round 2 fixes changed only tests and texts in the new module, docs, and a migration docstring.
- This is the known intermittent failure (NOW.md 2026-10-02 and 9f-3, likely autovacuum; Q-2026-10-05-26 for `test_usd_refund_khr_origin_uses_recorded_usd_without_repricing`, the same lock in the same module). 10c-2b-2b does not touch Payment Refunds, `app.validate_general_refund_source` or `app.assert_payment_excess_eligible`.
- The run rule says no retry, and the takeover stops on a test outside the slice that passed before. So I stopped. Nothing is committed and no round 3 has started.

Options:
- (a) Allow one more full PostgreSQL run (P3), recorded as an owner-approved rerun after an outside intermittent failure (as your answer to Q-2026-10-05-26). If it is green, run review round 3; if the same lock failure comes back, stop and report.
- (b) Accept P1 and P2 together as the evidence (every test passed in at least one of them; the only P2 failure is outside 10c-2b-2b) and go to review round 3.
- (c) Stop 10c-2b-2b and look into the lock failure first.

**Recommendation: (a)**, as in Q-2026-10-05-26. Also add this second test name to the slice 12 item that makes the `test_refund_migration.py` tests robust against `LockNotAvailable` without weakening them.

Until you answer, no further 10c-2b-2b change, no run and no commit. 10c-2b-3 waits.

**Owner answer (2026-10-09).** Option (a).

- One more full PostgreSQL run (P3) is allowed. If it is green, do review round 3. If P3 fails again with `LockNotAvailable`, or any other test fails, stop and report.
- Slice 12: add `test_usd_refund_blocks_source_reversal_until_full_verified_return` to the `LockNotAvailable` robustness item, next to `test_usd_refund_khr_origin_uses_recorded_usd_without_repricing`. Look for the cause in the lock code too, not only in the two tests. If the fix needs a product code change, ask the owner first.

Also answered with it (2026-10-09): the return refusals after closure keep P5S01 and 409 for both return routes (a business-state refusal; the 11c plan answers those with 409). The 11c plan gets a note to check the 10c-2b-1 refusal (P5202, 422) and move it to 409, so both routes answer the same way; not changed now. Recorded in docs/010 and the plan.

## Q-2026-10-09-63 — Sub-slice 10c-2b-3 stopped after review round 1: what "linked to that correction" limits in the refund-only form (ANSWERED 2026-10-09: point 1 (a), point 2 keep as built; answers in docs/010)

10c-2b-2b is committed (b4cf091; NOW.md ab434af). 10c-2b-3 (`HELD_VALUE_REFUND`, migration `20261114_110`) is built and green but not committed: U1 3652 passed, P1 1980 passed (targeted T1 failed once on a test that counted drafts of the whole shared database; corrected once). Record: ops/reviews/V1-056-slice-10c-2b-3-held-value-refund.md. Review round 1: no blocker; independent 4 should-fix, security 2 should-fix (they overlap), and notes. Most of them are missing tests that I can add. Two points decide what the code must do, so they need you.

**What the correction does (your answers to Q-42 and Q-55).** A later correction names an earlier return-only `REFUND_RETURN` correction and refunds the value it left. A held Credit first pays its own Customer's open debt on this Lease, and only the rest is refunded to that Customer. Held Deposit money first pays this Lease's open debt in the DL-032 order, and the rest is refunded. The shared step must apply or refund every held DL-032 Deposit balance in the same correction (BR-SETTLE-008).

**Point 1: the Deposit form and the link.**
- Built: a Deposit correction checks only that the Deposit is on the DL-032 path and holds money. It does not check how much of that money came from the named earlier correction.
- So the same earlier correction can be named again after its own money is gone. Example: earlier correction E returns 2,000 to the Pet Deposit; correction H1, linked to E, refunds those 2,000; a second return-only correction E2 returns 1,000 more; a new correction linked to E refunds those 1,000 too. No money is overpaid (each Refund is capped by what the Deposit holds), but the record shows 3,000 refunded against E, which returned only 2,000.
- Options:
  - (a) Each held-value correction may name an earlier correction only while that correction still has value left. For a Deposit: what it returned, less the Deposit applications and Refunds from that Deposit written by the held-value corrections linked to it. For a Credit: what it left, and the Credit must still hold some of it. The step still settles every held DL-032 balance (BR-SETTLE-008), and the audit event lists every Deposit balance it settled.
  - (b) Pooling: the link only says which correction triggered the payout. One held-value correction may refund all held money of a Deposit, whichever earlier corrections returned it. Then the docs must say so, and no further check is added.
- **Recommendation: (a)**, because it keeps the record true to your words "linked to that correction", while the money rules stay as they are.

**Point 2: the Credit form, when other paths use the Credit.**
- Built (docs/010 choice (1)): what E left in a Credit is E's return, less the Credit applications from that Credit written by E's own step and by the linked held-value corrections, and less their Refunds from it. Value the Customer uses through the ordinary paths (a one-call Credit application, an ordinary Credit Refund draft) does not lower what E left; it only lowers the Credit's available value, which also caps the new Refund.
- The new Refund is what is left in the Credit after this correction's own step, at most what E left. A Credit that held other value may therefore pay the debt from that other value and refund all that E left. This is the rule of choice (1) of 10c-2b-1, which you kept.
- Options:
  - (a) Keep as built. The ordinary Credit paths stay as they are (your answer 2 to Q-55), and the available-value cap prevents any overpayment.
  - (b) Stricter: the new Refund is at most what E left less this correction's own step applications from that Credit.
- **Recommendation: (a)**, as for 10c-2b-1.

**What I fix after your answers, with no rule change** (then the static checks, the migration check, the runs and review round 2):
- Tests:
  - the cap where the Credit holds more than E left (two return-only corrections of the same Refund), also on the third-party Credit, so that the relaxed check refuses anything above what was left;
  - E's own step paying part of the Credit to debt;
  - a return-only correction of another Settlement named in this Settlement's draft (P0002);
  - database-level guards: authorization 42501, a non-human approver, REPEATABLE READ 55000, malformed input 22023, key reuse P5205 and the record replay;
  - a NOWAIT check that the confirm holds the Lease row and the Credit row;
  - the Q-59 answer 2 path: a Credit return-only correction while a Deposit holds returned money, then a held-value correction that refunds both.
- Code:
  - the audit event's `customer_id` for a Deposit correction (today the earlier Refund's recipient, not the plan step's);
  - a Credit correction whose Credit no longer holds anything is refused, even when it has other steps;
  - the gate of point 1, if you choose (a).
- Docs: the plan's "as built" line (the left value also subtracts the linked corrections' Credit applications; only the Credit form has the record-time "writes nothing" check), and docs/010 choices (2) and (4) reworded. Choice (2) applies to the Credit form too. Choice (4) is untrue until the point 1 gate exists.

**For the notes, no answer needed:**
- The future `RETURN_REVERSAL` (Q-2026-10-08-57) must make the left value subtract reversed returns.
- The new Refund's method and note are required even when the plan pays everything to debt and no Refund is written. This is the same as the `REFUND` correction.

Until you answer, no further 10c-2b-3 change, no run and no commit. All 10c-2b-3 files are in the working tree.

**Owner answer (2026-10-09).**

1. Yes, option (a). A Deposit correction may name an earlier correction only while that correction still has value left. Write in docs/010 how the value left is counted. Add a test: naming the same correction again after its value is gone is refused, and no money or record changes.
2. Yes, keep it as built, as approved for 10c-2b-1. Credit spent through the ordinary Credit paths lowers only the Credit's available value. The available value still caps every Refund. Write it in docs/010 as a known limit: the value an earlier correction left can be more than the Customer can still get back.

Recorded in docs/010. Next: the round 1 fixes (the listed tests, the audit `customer_id` of a Deposit correction, a Credit correction whose Credit is empty), the static checks, the runs, review rounds 2 and 3 under the standing rule, then the commit.

## Q-2026-10-09-64 — The Deposit counting of the refund-only form, reported after 10c-2b-3 (ANSWERED 2026-10-09: the stricter count, an approved tightening; built as sub-slice 10c-2b-4)

**The point reported after 10c-2b-3.** As committed (migration `20261114_110`), the value an earlier return-only correction left in a Deposit is lowered only by the corrections linked to it, and the shared step of every `HELD_VALUE_REFUND` correction must apply or refund every held DL-032 Deposit balance (BR-SETTLE-008). So a correction that names one earlier correction can also use Deposit money that another earlier correction returned (for example a Credit correction that also refunds the Pet Deposit's returned money, as owner answer 2 to Q-2026-10-08-59 allowed), and the other earlier correction then shows value left that the Deposit no longer holds (the known limit written with owner answer 1 to Q-2026-10-09-63).

**Owner answer (2026-10-09).** I want the stricter count. This tightening is approved.
- A Deposit correction that names an earlier correction may use at most the value that correction has left. This limit covers the Lease debt it pays and the Refund together.
- To use more held money, staff prepare another correction that names the other earlier correction.
- Build it as a small sub-slice before 10c-3b, with a new migration. Do not change any committed migration.
- Change the committed test that shows the old limit so that it proves the new refusal. It keeps its name. The independent reviewer compares it with its version at HEAD and confirms that this is the only change.
- Update the known-limit entry in docs/010.
- Check that the Credit side counts the debt it pays in the same way. If it does not, tell me in your report. Do not change it.

Recorded in docs/010. The pre-code design is in the plan (10c entry, "10c-2b-4").

**Credit side check (your last point; reported, not changed).** The Credit form does not count the debt it pays in the same way. Its new Refund is at most what the earlier correction left, but this correction's own step applications from that Credit are left out of the cap (your answer 2 to Q-2026-10-09-63, kept as built). So the debt it pays and its Refund together may exceed what the earlier correction left: the committed test 1 of 10c-2b-3 has 1,800 left, pays 1,500 to debt and refunds 500.

## Q-2026-10-09-65 — Sub-slice 10c-2b-4 stopped after review round 2: with exact use, two held-value corrections can block each other (ANSWERED 2026-10-09: (b); the narrow guard agreed; Credit side kept; 10c-3b findings accepted; answers in docs/010)

10c-2b-4 (migration `20261116_112`) is built and NOT committed. Runs: T1 15, U1 3663, P1 1994 passed; after the round-1 fixes T2 15, U2 3663, P2 1994 passed; after the round-2 fix T3 15 passed (no full run since). Record: ops/reviews/V1-056-slice-10c-2b-4-held-deposit-limit.md. Review round 1: one should-fix each, both fixed. Review round 2: security 0 blockers, 0 should-fix; independent 0 blockers, 1 should-fix (the new "pet damage first" guard refused every Security Deposit use; it now refuses only a Security Deposit step that pays pet damage). That reviewer also found the case below, which needs you.

**What I built.** Your answer says a correction "may use at most" the value its earlier correction left. BR-SETTLE-008 says every remaining Deposit balance is applied or refunded. I combined the two: a held-value correction applies or refunds exactly the smaller of its value left and what the Deposit holds, so it never leaves part of its own value behind.

**The case.** A termination where the remaining Pet Deposit pays other debt only by the Customer's choice or a staff decision, and the Customer has no Credit. A return-only correction E1 put 300 back in the Pet Deposit, and E2 put 200 back in the Security Deposit. Later, other corrections open 50 of pet damage and 100 of other debt.
- A correction naming E2 must use exactly 200 of the Security Deposit. It may pay the other debt (100). It may not pay the pet damage, because the Pet Deposit pays pet damage first and still holds money. It may not refund the rest while debt stays open. So it is refused.
- A correction naming E1 must use exactly 300 of the Pet Deposit. It pays the pet damage (50). The rest may not pay the other debt while the Security Deposit holds money (the remaining Pet Deposit comes after the Security Deposit), and it may not be refunded while debt stays open. So it is refused.
- Neither correction can be recorded until the Customer pays the other debt. No money is wrong, but staff are stuck.

**Options:**
- (a) Keep exact use. Such a case waits until the Customer pays; docs/010 says so.
- (b) "At most", as your words say: a held-value correction may leave part of its own value held, for a later correction that names the same earlier correction. A Deposit correction must still use some of its own value; one that uses none stays refused with the existing every-balance message, so the committed no-plan test does not change. In the case above: E2 pays the other debt (100) and keeps 100; E1 pays the pet damage and refunds 250; a second correction naming E2 refunds the last 100.
- (c) Keep exact use, but let the Security Deposit pay pet damage when the Pet Deposit's money belongs to another earlier correction. This changes the DL-032 order (pet damage first), so I do not recommend it.

**Recommendation: (b).** It follows your words "at most", keeps every DL-032 rule, and never uses more than the value left.

**For you, not blocking (details in docs/010, 10c-2b-4 entry):**
- When held money is less than the value left (a correction that names no earlier correction settled some of it, then a later return brought money back), a correction naming the first earlier correction may use the later return's money, and naming the later one is then refused. Changing this would change how answer 1 to Q-2026-10-09-63 counts the value left.
- Corrections that name no earlier correction (`REFUND`, `REFUND_RETURN` with a new Refund, `PET_DAMAGE_RECLASSIFICATION`, and a return-only Credit correction under the hold rule) still apply or refund held Deposit money (BR-SETTLE-008).
- Each Customer's Credit still pays that Customer's open debt first whenever a Deposit holds money, also money this correction may not use.

Until you answer: no further 10c-2b-4 change, no run, no commit; 10c-3b is not started (your answers for it are recorded under Q-2026-10-09-66).

**Owner answer (2026-10-09).**

1. Option (b). My words were "at most", and that is what I meant. A correction may leave part of the value that its named correction left in a Deposit. That part stays held for a later correction that names the same earlier correction. The correction must still use some value, so the committed no-plan test does not change. BR-SETTLE-008 and the DL-032 order stay exactly as they are for every correction, including one that leaves value held. Add tests: the Q-65 case is fully settled through more than one correction, once with the Pet Deposit correction first and once with the Security Deposit correction first, and each end result follows the DL-032 order; a correction that leaves value held still cannot pay a Refund that BR-SETTLE-008 would refuse.
2. The narrow guard: agreed. My answer 3 (ii) to Q-2026-10-05-20 and the 10c-2b-2a hold rule only stop the Security Deposit from paying pet damage instead of the Pet Deposit. They never stopped the Security Deposit from paying other debt. Write this reason in docs/010.
3. The Credit side: keep it as built. A Customer's Credit pays that Customer's own debt first, whatever its source (my Q-29 and Q-55 answers). Add to the docs/010 known-limit entry: on the Credit side, only Refunds lower the value an earlier correction left; debt that the correction pays from the Credit does not.
4. 10c-3b: the read-only findings are accepted. Relax `invoice_credit_excess_releases` as described, with exactly one of the two links. The split into Payment and Credit sources first, then Deposit-paid Charges, is fine.
5. Then apply answer 1, the static checks, the migration-only check, the read-only search for affected tests, the full unit run and the full PostgreSQL run under caffeinate, then review round 3 under the standing round-3 rule; commit 10c-2b-4 only if the runs are green and round 3 has no blocker and no should-fix. After that, build 10c-3b.

Recorded in docs/010 (see Q-2026-10-09-67 for the round-3 result). Implementer note on answer 3: in the code, the value an earlier correction left in a Credit is also lowered by the debt that the earlier correction's own step and the other linked held-value corrections paid from that Credit (owner answer 1 to Q-2026-10-09-63); only a held-value correction's own debt payment does not lower its own cap. docs/010 says so, to stay true to the code.

## Q-2026-10-09-66 — Owner answers for sub-slice 10c-3b, given before its design (ANSWERED 2026-10-09)

1. Deposit applications on a paid Late-payment Charge: follow the Q-2026-10-07-46 answer, the same way as for Adjustments. If it does not fit Charges, write why in this file with a recommendation and stop.
2. Where to record the Credit freed from a paid Charge: a technical choice. Use an additive or relaxing migration only. Every money movement must link to the correction that caused it. Write the choice in the design and in docs/004; the reviewers must check it. If the choice would change who gets the money, or the order the money is used in, stop and ask.

Read-only findings so far (head `20261115_111`), for the 10c-3b design: (1) the Q-46 answer fits a Charge: the 8a-1 refusal of a Charge correction (`app.refuse_deposit_applied_obligation_change`, P4603) can let through a Charge correction linked to a correction of its own Settlement confirmed in the same transaction by that approver, and the Charge correction's deferred validator already refuses a result below the active applications (Deposit applications not reversed included), so no Charge can be paid more than its new amount. (2) Recommended record: relax `invoice_credit_excess_releases` (its Adjustment link becomes optional and it gains an optional link to the Late-payment Charge correction, exactly one of the two); most readers key on the released source, its replacement or the Credit, so few need a patch (the release validator, the Credit recognition validator that finds the Customer, the relaxed Credit Refund check and the plan's Credit key). Released Payment value still becomes the Charge Customer's Credit (BR-CREDIT-014), newest first (Q-41 answer 2), and released Credit first pays its own Customer's open debt (Q-42 answer 2): who gets the money and the order do not change. A split like 10c-1b and 10c-2a-3 is likely: Payment and Credit sources first, Deposit-paid Charges second.

## Q-2026-10-09-67 — Sub-slice 10c-2b-4 stopped after review round 3: one text should-fix (stale wording of the old exact-use rule) (ANSWERED 2026-10-09: (a), owner exception as Q-2026-10-07-44; answer in docs/010)

Your answers to Q-2026-10-09-65 are built (option (b), "at most"; the narrow guard; the Credit-side known limit; recorded in docs/010). Runs, all green: T4 16 passed, U3 3663 passed, P3 1995 passed (under caffeinate). Record: ops/reviews/V1-056-slice-10c-2b-4-held-deposit-limit.md. Nothing is committed.

**Review round 3 (standing rule):**
- Independent: 0 blockers, 0 should-fix, 4 notes. It confirms that the migration implements (b) exactly, that the tests prove your requested cases and fail without the code, and that the changed committed test is not weakened.
- Security: 0 blockers, 1 should-fix, which is text only. Checks 1 to 4 pass: no money moves beyond the limit, no Refund while debt stays open, the DL-032 order holds, callers cannot set the limit, and there is no new SQLSTATE.

**The should-fix (both reviewers name it, the independent one as notes).** Four places still describe the old exact-use rule:
- the new test module's docstring (`backend/tests/test_settlement_held_deposit_limit_migration.py`, line 6: "applies or refunds all of that value the Deposit holds");
- three plan sentences (`ops/V1_056_PLAN.md`, the 10c-2b-4 Rule sentence, the plan-check bullet and the tests bullet, which still describe test 1 before (b)).

Independent note 3 is also text: docs/010 says the limit is refused "together with `hold_deposits`"; the code refuses it only with `hold_deposits` true. No code is wrong.

**Options:**
- (a) An owner exception, as for Q-2026-10-07-44: make these text fixes only. Then run lint, format and type check, each in its own call, and one full backend unit run. No PostgreSQL test reads a module docstring or the plan, so there is no PostgreSQL run. Then commit 10c-2b-4.
- (b) The text fixes, then U, P and a limited review round of the text.

**Recommendation: (a).** The fixes change no code and no test assertion.

Until you answer: no change, no run, no commit. 10c-3b is not started.

**Owner answer (2026-10-09).**

1. Option (a), the same exception as Q-2026-10-07-44. Fix the four stale texts and the loose docs/010 sentence. Check with git diff that only text lines changed. Then run the three static checks, each in its own call, and one full unit run. Commit 10c-2b-4 if they are clean.
2. The Q-65 test in both orders is accepted for now. A real-path version, with real corrections recorded and confirmed, not a state carried by hand from one step to the next, is a task in the plan that must be done before 10h. Written in the review record.
3. The docs/010 wording for the Credit side is right: it matches the code, and the docs must match the code. The wording of owner answer 3 to Q-2026-10-09-65 was not exact. Nothing else changes.
4. After 10c-2b-4 is committed, write the 10c-3b pre-code design in the plan and commit it. No code. Then stop and report. A design question goes to this file with a recommendation. The owner starts a fresh session to build 10c-3b.

Recorded in docs/010.

## Q-2026-10-09-68 — Sub-slice 10c-3b-1 before code: the shared plan check refuses a released Charge allocation (ANSWERED 2026-10-09 in the session: patch it)

Found while reading the code for 10c-3b-1, before any code. The shared plan check `app.settlement_correction_plan_result` accepts a released Payment allocation in its Credit overlay only when the allocation is on an Invoice of the Lease (it joins `allocation.invoice_id`). A Late-payment Charge allocation has no Invoice (`invoice_id` is NULL), so every Charge `REFUND` with released Payment value would be refused (55000, "The overlay names a Customer Credit outside this Final Settlement"). The 10c-3b design lists the patched readers and does not list this one.

**Recommendation:** one exact-text patch: the overlay also accepts an allocation on a Late-payment Charge of an Invoice of this Lease, as Credit of the Charge's Customer (BR-CREDIT-014). Who gets the money and the order it is used in do not change. List it in the plan's as-built line, docs/010, the review record and the least-privilege test's changed-function list; the reviewers check it.

**Owner answer (2026-10-09, in the session).** Patch it (the recommendation). Recorded in docs/010.

## Q-2026-10-10-69 — Sub-slice 10c-3b-2 report: six owner items (ANSWERED 2026-10-10; answers in docs/010)

The 10c-3b-2 report (cc01b84, record ops/reviews/V1-056-slice-10c-3b-2-late-charge-deposit-refund.md) left these items for the owner.

**Owner answer (2026-10-10).**

1. The reading of the standing round-3 rule is right: P2 ran after the last code and test change, and only text changed after it, so P2 counts as the full PostgreSQL run before round 3.
2. Choice (4) is accepted: a partly released Deposit application is reversed whole, and the Customer's own Credit pays the rest first (Credit before Deposits).
3. The optional allow-function hardening stays on the slice 12 list. Also in the plan: any sub-slice that adds a new writer that links an Adjustment or a Charge correction must do this hardening first.
4. Report whether staff can still reduce the unpaid rest of a partly Deposit-paid Charge after closure (for example through a `REFUND` correction that ends with nothing refunded). If there is no path at all, write it here with a recommendation for the owner to answer before 10h; do not stop for it.
5. If the independent reviewer did not already compare the changed 10c-3b-1 test with its version at 0139619, do that first, read-only, and record the result in the 10c-3b-2 review record; if it was weakened, stop.
6. The 10d design is accepted, with its three points; the plan's 10h entry must close the 6b reversal draft after closure.

**Implementer notes (2026-10-10).**

- Answer 5: round 1 compared the test with HEAD (2b5f7c9), not with 0139619. Read-only check: only cc01b84 changed `backend/tests/test_settlement_late_charge_refund_migration.py` after 0139619 (`git log 0139619..4710bdf`), so HEAD and 0139619 hold the same version. The diff against 0139619 changes one expected message (`"A Deposit application paid this obligation at Final Settlement"` to `"Every remaining Deposit balance must be applied or refunded"`), adds a two-line comment and changes two docstrings; the SQLSTATE 55000, the unchanged draft count and the zero Charge corrections are still asserted. Not weakened. Recorded in the review record.
- Answer 4: no path reduces only that unpaid rest; see Q-2026-10-10-70.
- Answers 3 and 6: written in the plan (slice 12 item; 10h entry).

## Q-2026-10-10-70 — The unpaid rest of a partly Deposit-paid Charge or Invoice line cannot be reduced on its own after closure (not blocking; the owner answers before 10h) (ANSWERED 2026-10-10: (a), after the allow-function hardening; sub-slices 10c-3c-1 and 10c-3c-2 before 10h; answer in docs/010)

Owner answer 4 to Q-2026-10-10-69 asked whether staff can still reduce the unpaid rest of a partly Deposit-paid Charge after closure. Read from the code at head `20261118_114`:

- `CHARGE_REDUCTION` (the 10c-3a Charge form, migration `20261115_111`, and the 10c-1a Invoice-line form, migration `20261103_99`) refuses any obligation a Deposit application paid that is not reversed (55000, "A Deposit application paid this obligation at Final Settlement").
- `REFUND` (10c-3b-1 and 10c-3b-2 for a Charge, 10c-1b and 10c-2a-3 for a line) refuses an amount that releases no paid value (55000, "The Refund correction releases no paid value; an unpaid charge is removed by a charge reduction"). So its amount must be at least the unpaid rest plus 1 cent of paid value.
- Such a `REFUND` reverses the Deposit application whole, reduces the obligation by the whole amount, and the shared step pays the new rest again from the Deposit. The extra paid part (at least 1 cent) leaves the obligation for good: it pays other open debt on the Lease or is refunded. A correction "that ends with nothing refunded" is possible only when other open debt takes that part; it still removes real debt from the corrected obligation.
- No other correction kind changes the amount of such an obligation, and the one-call writers are refused after closure (8e-1).

So there is no path that reduces only the unpaid rest. Example: a Charge of 3,000 that the Pet Deposit paid 2,000 of at closure, 1,000 unpaid and wrong. A `REFUND` of 1,000 is refused (no paid value); a `REFUND` of 1,001 also removes 1 cent that was rightly owed. The same holds for an Invoice line (choice (4) of sub-slice 10c-2a-3).

**Options:**
- (a) A small relaxing sub-slice before 10h: `CHARGE_REDUCTION` (both forms) accepts an obligation that a Deposit application partly paid, within its unpaid rest (the current obligation less every active application, Deposit applications not reversed included). The Deposit application stays as it is; nothing is released and no money moves. The linked Adjustment or Charge correction passes the 8a-1 refusal through the existing allow functions (the Q-46 answer). The row's own deferred checks already refuse a result below the active applications. Under owner answer 3 to Q-2026-10-10-69 that sub-slice first adds the allow-function hardening (the correction's draft must name this obligation, and the row's correlation must be the correction), because it makes a second writer rely on them.
- (b) Keep it as a known limit: staff use a `REFUND` of the unpaid rest plus the smallest paid part and record the 1 cent difference with an `EXTRA_CHARGE`. The record then shows a Refund and a new charge for what was only a wrong unpaid amount.

**Recommendation: (a).** It removes only the wrong unpaid amount, moves no money, keeps every Deposit rule and uses the Q-46 path the owner already approved. It is a relaxing change of two committed forms, so it needs the owner.

Not blocking 10d: 10d does not change these forms.

**Owner answer (2026-10-10).** Yes, option (a). A small relaxing sub-slice lets `CHARGE_REDUCTION` reduce a partly Deposit-paid obligation within its unpaid rest. Do the hardening from answer 3 to Q-2026-10-10-69 first.

Recorded in docs/010; the plan names the work sub-slices 10c-3c-1 (the allow-function hardening) and 10c-3c-2 (the reduction within the unpaid rest), in that order, before 10h.

## Q-2026-10-10-71 — Sub-slice 10d before code: the agreed-Signer test and a Deposit with a second forfeiture (ANSWERED 2026-10-10 in the session)

Found while reading the code for 10d, before any code.

1. The 10d design lists a test of a Deposit Refund to another signed Signer with the written agreement. No test fixture has a kept (forfeited) Deposit on a Lease with a second signed Signer: `leaving_case` has one Signer, `two_signer_case` has no forfeiture ground, and Signers cannot be added after signing. The agreed-Signer Deposit Refund is written by the shared step, which is already tested on `two_signer_case` (`test_settlement_correction_plan_migration.py`).
2. A Deposit can hold two Lease forfeitures (only in the open Q-2026-10-09-61 case: a kept Pet Deposit gets a returned Pet Refund-review Refund before closure and is forfeited again). Reversing one leaves the Deposit kept (path `KEPT`), so the step cannot use that money.

**Owner answer (2026-10-10, in the session).**

1. Negative checks now: on the real kept-Deposit path, a recipient who is not a Signer is refused and an agreement for the Primary Tenant is refused; the positive agreed-Signer path stays covered by the shared-step test. Add the positive agreed-Signer Refund test on a kept Deposit to the plan's real-path task before 10h, next to the real-path Q-65 test, and build the two-Signer fixture there.
2. Refuse (55000): the recorder and the confirm refuse a reversal while another forfeiture of the same Deposit stays active (the reversal would not put the Deposit on the DL-032 path). Decided with Q-2026-10-09-61 before 10h.

Recorded in docs/010 and the plan.

## Q-2026-10-10-72 — Sub-slice 10e design: three cases a returned Payment cannot handle under the current rules (blocks 10e-1b and 10e-1c; not 10e-1a) (ANSWERED 2026-10-10: point 1 (a), its detail confirmed; points 2 and 3 (a); answers in docs/010)

The 10e pre-code design is in the plan (10e entry). It splits 10e into 10e-1a (`PAYMENT_RETURN` when no closed Final Settlement relied on the Payment's records), 10e-1b (the `RETURNED_PAYMENT` correction) and 10e-1c (a Refund already paid from the returned value). Your answers 2, 3 and 5 to Q-2026-10-06-37 decide 10e-1a completely, so it goes ahead under the standing rules, as 10a did while Q-2026-10-06-37 was open. These three cases are not decided.

**What exists (read from the code at head `20261119_115`).** A Payment reversal (DB-PAY-006) needs every allocation, every Credit recognized from the Payment and every Deposit receipt reversed first, and every Refund paid from the Payment fully returned. A Credit reversal needs the whole Credit still available (nothing applied or refunded). A Deposit receipt reversal is refused while the Deposit has an active forfeiture or a Refund that is not fully returned. These checks keep every balance at zero or above; none of them can be met while money paid out from the returned value is still out.

**1. A Refund already paid from the returned value.** Your rule (answer 1 to Q-2026-10-06-36): "a Settlement Refund already paid from a Deposit that the returned Payment funded cannot be undone ... it becomes an `EXTRA_CHARGE` to the Deposit owner in the same correction". The same happens for a Refund of a Credit the Payment funded (for example the 8g case: a third-party Payment's adjustment Credit refunded to the Invoice Customer) and for a Refund of the Payment itself. The charge alone does not let the records balance: the Refund still counts as money taken from the Deposit, the Credit or the Payment, so the receipt, the Credit and the Payment cannot be reversed (the Deposit would show a negative balance). Example: a Security Deposit of 1,000 funded by one Payment; the Settlement applied 600 to debt and refunded 400; then the Payment bounces. After the 600 is reversed, the Deposit holds 600, but its receipt is 1,000.
- (a) A new Refund correction kind, for example `RECOVERED_BY_CHARGE` (DB-REFUND-002 amendment): a linked row on the Refund for its unreturned amount that gives that amount back to the Refund's source on paper (the Deposit, the Credit or the Payment), so the reversals can run; in the same transaction a linked charge of the same amount to the person who owes it (the Deposit owner for a Deposit Refund, as you said; the Credit's Customer for a Credit Refund; the payer for a Payment Refund). The Refund itself stays: the money really left. With a closed Settlement the charge is the `EXTRA_CHARGE` (10b rules: Due Date, no Late-payment Charge). With no closed Settlement it is an ordinary Miscellaneous one-time charge on the Lease the value came from, issued in the same confirm; a returned Payment whose Refund has no Lease to charge on is refused (a known limit).
- (b) The same as (a) with a closed Settlement only; with no closed Settlement the `PAYMENT_RETURN` is refused while such a Refund is out (a known limit: that Payment cannot be returned in the system).
- (c) No new kind: a returned Payment is refused while any Refund paid from its value is not fully returned (a known limit in both cases; the loss is recorded outside the system).

**Recommendation: (a).** It keeps every balance true, follows your charge rule, and gives the same fix with or without a Settlement. It changes docs/004 (DB-REFUND-002) and is built in 10e-1c. Until then 10e-1a refuses such a Payment (55000).

**2. A kept (forfeited) Deposit that the returned Payment funded.** The Property kept money that never really arrived. Before closure, staff can first reverse the forfeiture with the 6b draft, then return the Payment; 10e-1a refuses until then (55000, with that message). After closure the 6b draft will be refused (10h), and a forfeiture reversal after closure runs only inside a correction (your answer 4 to Q-2026-10-06-36).
- (a) The `RETURNED_PAYMENT` correction reverses that forfeiture as a linked record (DB-SETTLE-005 `deposit_disposition_reversal_id`, through the existing reversal function as 10d does) and then the receipt. Because every Deposit has exactly one receipt today (only `app.create_reservation` writes receipts), the Deposit is then empty, so the DL-032 step has nothing to apply or refund. A Deposit that would still hold money afterwards (a second receipt, or a returned Refund it holds) is refused (55000).
- (b) Refused after closure (a known limit).

**Recommendation: (a)**, built in 10e-1b.

**3. A Payment whose records two closed Final Settlements relied on.** Your condition (answer 5 to Q-2026-10-06-37): a returned Payment may not change a record that another Lease's closed Settlement relied on unless that change is also a confirmed correction of that Settlement. One correction belongs to one Settlement and one draft (the correction header's `correlation_id` is its draft, unique), and a correction writer is the only statement of its transaction, so one confirm cannot write a correction of two Settlements today.
- (a) Refuse (55000) a `RETURNED_PAYMENT` correction or a `PAYMENT_RETURN` draft whose Payment has records relied on by a closed Settlement other than the correction's own (a known limit in docs/010). It needs one Customer with two settled Leases paid by one Payment that later bounces.
- (b) A multi-Settlement correction: one draft that writes one correction header per Settlement in one confirm (a change to DB-SETTLE-003 and to the 10a header rules).

**Recommendation: (a)**, with the refusal tested (your "Test it"); (b) only if you expect such Payments.

**What goes ahead.** 10e-1a (no closed Settlement relied on; it refuses the cases above). 10e-1b waits for points 2 and 3, and 10e-1c for point 1.

**Owner answer (2026-10-10).**

- Point 1 (a Refund already paid out from the bounced Payment's value): the Customer owes that amount back as an `EXTRA_CHARGE`, the same rule as the answer to Q-2026-10-08-57. Use the new correction kind recommended in option (a), so that no Deposit shows a negative balance.
- Points 2 and 3: not decided yet. After 10e-1a is committed, write each case in simple words, with a small example in dollars, the options and the recommendation, here and in the report.
- Do not start 10e-1b or 10e-1c until points 2 and 3 are answered. Continue with the next sub-slices before 10h that Q-72 does not block, starting with 10c-2b-5.

Recorded in docs/010 and the plan (order of the remaining slice 10 work).

**Points 2 and 3 in simple words (written 2026-10-10 after the 10e-1a commit ee8397c; still open).**

*Point 2: a forfeited Deposit paid by a Payment that later bounces.*

Example. A Customer pays a $500 Security Deposit by bank transfer. The Customer leaves early, so the Property keeps the $500 (a forfeiture, BR-DEP-023). The Final Settlement closes. A week later the bank says the $500 transfer bounced. The records now show that the Property kept $500 that never arrived.

What exists today. Before closure, staff first reverse the forfeiture with the forfeiture reversal draft (6b) and then return the Payment (10e-1a refuses until then, with that message). After closure, nothing can return this Payment, and 10h will also refuse the 6b draft.

- (a) The `RETURNED_PAYMENT` correction of that Settlement does it in one step: it reverses the forfeiture (a linked record, as 10d does), then the $500 receipt, then the Payment. The Deposit ends at $0, so there is nothing to apply or refund. The history keeps the forfeiture and its reversal. Afterwards the Customer does not owe the $500, because a forfeiture keeps only money the Deposit really held, and no rule makes an unpaid Deposit a debt. If the Deposit would still hold money afterwards (for example a returned Pet Refund-review Refund), the correction is refused.
- (b) Refused after closure (a known limit). The records keep showing a $500 forfeiture of money that never arrived; staff record the loss outside the system.
- (c) As (a), and in the same correction an `EXTRA_CHARGE` of the forfeited $500 to the Deposit owner, because the signed Lease said the Deposit is kept. This is a new charge rule; I do not recommend adding it unless you want it.

Recommendation: (a). It keeps every balance true and adds no new charge.

*Point 3: one Payment used by two closed Final Settlements.*

Example. One Customer rents Unit 101 (Lease A) and Unit 102 (Lease B). One bank transfer of $1,000 pays $600 of Lease A's last Rent and $400 of Lease B's last Rent. Both Leases end and both Final Settlements close. Then the bank says the $1,000 transfer bounced.

Why it is hard. A Payment can be reversed only when all its uses are reversed in the same step. Each correction belongs to one Settlement, and one confirm writes one correction. So one correction cannot undo both the $600 on Lease A and the $400 on Lease B. (If only Lease A is settled and Lease B is still open, 10e-1b can do it: the $400 on the open Lease is reversed in the same step without a correction.)

- (a) Refuse it (a known limit, with a test). The system says that two closed Final Settlements used this Payment. The $1,000 stays shown as paid, and staff record the loss outside the system.
- (b) One correction draft that writes one correction record per Settlement in one confirm (here two: $600 of debt comes back on Lease A and $400 on Lease B, both on the Customer's ledger). It changes the correction record rules (DB-SETTLE-003 and the 10a header rules) and needs its own sub-slice.

Recommendation: (a) now. It needs one Customer with two settled Leases paid by one transfer that bounces afterwards, which should be rare in V1. Choose (b) if you expect such Payments; (b) can replace (a) later without changing any record already written.

*One detail of point 1 to confirm with these answers.* An `EXTRA_CHARGE` exists only inside a correction of a closed Settlement. Option (a) of point 1 says that with no closed Settlement the charge is an ordinary Miscellaneous one-time charge on the Lease the value came from, issued in the same confirm, and that a returned Payment whose Refund has no Lease to charge on is refused (a known limit). Please confirm this part too; 10e-1c waits for points 2 and 3 anyway.

**Owner answer to points 2 and 3 and the point 1 detail (2026-10-10, fresh session).**

- Point 2 (a kept Deposit paid by a Payment that later bounces): option (a). One `RETURNED_PAYMENT` correction reverses the forfeiture, then the receipt, then the Payment. The Customer does not owe the Deposit amount, because no rule makes an unpaid Deposit a debt. No new charge rule is added.
- Point 3 (one Payment used by two closed Final Settlements): option (a). Refuse it, write it in docs/010 as a known limit, and add a test. Option (b) (one draft that writes one correction per Settlement) goes into the plan as possible later work.
- Point 1 detail: confirmed. With no closed Settlement, the charge is an ordinary one-time Miscellaneous charge on the Lease the money came from. `EXTRA_CHARGE` is used only inside a correction of a closed Settlement.

Recorded in docs/010 and the plan. 10e-1b (points 2 and 3) and 10e-1c (point 1) may now be built.

## Q-2026-10-10-73 — Pay back (Q-2026-10-09-61): may the returned amount still be forfeited? (not blocking 10e; the owner answers before sub-slice 10c-2b-5) (ANSWERED 2026-10-10: (a); answer in docs/010)

Your answer to Q-2026-10-09-61 makes the returned money of a pre-termination Pet Refund-review Refund the Customer's money, before and after closure. Today a Lease Deposit forfeiture always takes the whole held amount (migration `20261018_83`), and before closure nothing stops a forfeiture draft of a Pet Deposit that holds such returned money: a `KEPT` Pet Deposit can be forfeited a second time, and a Pet Deposit that holds the returned money and its own rest can be forfeited whole. Both would keep the Customer's money.

- (a) Approved with pay back: sub-slice 10c-2b-5 makes a Lease Deposit forfeiture leave out the returned amount of a pre-termination Pet Refund-review Refund that the Deposit still holds: the draft forfeits only the rest, and is refused (22023, "The Deposit holds nothing to forfeit") when the returned amount is all it holds. A tightening of the forfeiture draft, with tests; it also makes the 10d refusal (another active forfeiture) unreachable, which stays as a guard (implementer note under Q-2026-10-09-61).
- (b) Leave the forfeiture as it is: staff decide; the Settlement preview only stops requiring a forfeiture of that amount.

**Recommendation: (a)**, because it is what "the Customer's money" means for the forfeiture, and the forfeiture is the only path that could still take it.

**Owner answer (2026-10-10).** Yes, (a). Under pay back, a forfeiture leaves out the returned amount, because that money is the Customer's. Also: keep the 10d refusal as a guard, as recommended under Q-2026-10-09-61.

Recorded in docs/010; built in sub-slice 10c-2b-5.

## Q-2026-10-10-74 — Sub-slice 10e-1a stopped after review round 2: three should-fix findings, all tests (blocks the 10e-1a commit) (ANSWERED 2026-10-10: (a), owner exception; answer in docs/010)

10e-1a (`PAYMENT_RETURN` when no closed Final Settlement relied on the Payment's records, migration `20261120_116`) is built and green but not committed: U3 3725 passed, full PostgreSQL P2 2024 passed (record: ops/reviews/V1-056-slice-10e-1a-payment-return.md). Review round 1 (independent 3 should-fix, security 1 should-fix) was fixed or answered. Review round 2: no blocker; independent 2 should-fix, security 1 should-fix; all three are missing or weak tests, no code fault. The standing rule allows round 3 only with at most two should-fix findings, so I stopped. All files are in the working tree.

**The three findings:**
1. No test proves the new relied-on branches for a Credit whose Settlement or correction use was later reversed or released (independent SF-1). Proposed: a real-path test of the round-1 example: a Credit applied before closure by an ordinary application, released by a `REFUND` correction after closure, its Refund brought back by a `REFUND_RETURN` (the value held on the Credit); the Credit's Payment shows that relied-on record and its return is refused.
2. The recorder's READ COMMITTED test would pass without the guard, because the Payment already has a waiting draft (independent SF-2). Proposed: use a Payment with no waiting draft and assert the guard's own message.
3. No test proves that the relaxed slice 7 and 8g refusals open only for the returned Payment within the same transaction (security S1). Proposed: one financial-role transaction that confirms the return of one Payment, then tries the direct reversal of another Payment's other-Customer Credit and the one-call reversal of another Payment's moved allocation (both P4904), then rolls back.

**Text fixes I would make with them (no rule change):** the lock comment, docs/004, docs/010 and the plan state the lock order exactly (a Charge lock also takes its Invoice), or the confirm takes the Charges first and then every Invoice in one id order (independent N-1; the second is a small code change that removes a possible deadlock between two returns, answered as a conflict today); docs/010 choice (4), the plan's preview line, the docs/010 refusal list and the migration docstring match the as-built behaviour (N-2, N-4); the round-1 overstatements of the recorder test (SF-2).

**Options:**
- (a) Owner exception, as for Q-2026-10-05-31 and Q-2026-10-07-43: I add the three tests and the text fixes, take the lock-order code change of N-1, run the static checks, one full unit run and one full PostgreSQL run, then one round 3 (independent and security) that must have no should-fix; then commit.
- (b) As (a), but keep the lock order as it is and only reword the comment and the docs (no code change; the deadlock stays a rare conflict).
- (c) Commit as it is, with the three tests as slice 12 items.

**Recommendation: (a).** All three are test gaps on rules you set (the relied-on rule of Q-2026-10-06-37 answer 5 and the scope of the relaxed refusals), and the N-1 change is small and removes a known deadlock.

Until you answer, no change and no run. 10e-1b waits for Q-2026-10-10-72 anyway.

**Owner answer (2026-10-10).**

1. Option (a), an owner exception as in Q-2026-10-05-31 and Q-2026-10-07-43. Add the three tests, make the small lock-order change, and fix the text. Then run the static checks, the migration-only check, one full unit run and one full PostgreSQL run. Then do review round 3. Commit 10e-1a only if the runs are green and round 3 has no blocker and no should-fix. If round 3 finds anything, stop.
2. `payments.reverse` as the eighth preparer capability: accepted. The bound of the two draft reads may go from 7 to 8. The two changed expectations in `test_lease_deposit_forfeiture.py` keep their names. The independent reviewer compares them with HEAD and confirms that only the capability count changed.

Recorded in docs/010.

Done: round 3 had no blocker and no should-fix; 10e-1a committed as ee8397c.

## Q-2026-10-10-75 — Sub-slice 10c-2b-5 stopped before code: two points of pay back (blocks 10c-2b-5) (ANSWERED 2026-10-10: point 1 (A); point 2 (b); follow-up Q-2026-10-10-76 blocks 10c-2b-5; answers in docs/010)

10e-1a is committed (ee8397c). The 10c-2b-5 pre-code design is in the plan (10c-2b-5 entry, "10c-2b-5 pre-code design"). It builds your pay-back answer to Q-2026-10-09-61 and answer (a) to Q-2026-10-10-73. Two points are not clear enough to build. There is no 10c-2b-5 code and no run.

**1. Where the returned money counts as DL-032 money.**

Example. A Pet Deposit of $200. While the Lease is signed the Customer gets a $200 Pet Refund-review Refund (the pet left). Later the Lease is terminated for pet noncompliance (BR-DEP-022), the Final Settlement closes and the Pet Deposit is empty. After closure the bank sends the $200 Refund back, so the Pet Deposit holds $200 again.

- (A) The $200 is DL-032 money everywhere, before and after closure. The system shows the Pet Deposit on the DL-032 path for that money, although its forfeiture stays. Before closure the Settlement must apply it to open debt or refund it. After closure the returned-Refund correction with a new Refund and the refund-only correction pay the open debt first and refund the rest; and any later correction that runs the shared DL-032 step must also use it (BR-SETTLE-008), as it must today for money a return-only correction left in a Settlement Deposit. Small change: the Deposit path, the forfeiture amount and one exception in the returned-Refund correction.
- (B) Only where the plan names it: before closure the Settlement preview, plan check and confirm; after closure only the returned-Refund correction with a new Refund and the refund-only correction. Other corrections leave the $200 alone; it stays in the Pet Deposit until one of those two corrections refunds it. About nine functions get their own exception.

Recommendation: (A). It is what "the Customer's money, treated as DL-032 value" means, it treats this money like all other DL-032 money, and it is much less code. It differs from the plan text only after closure, for corrections that run the shared step.

**2. Which returned amount is the Customer's.**

Example. A Pet Deposit of $500. While the Lease is signed the Customer gets a $300 Pet Refund-review Refund, so the Pet Deposit holds $200. Later the Lease is terminated for pet noncompliance.

- Case X: the $300 came back before the termination. At the termination the Pet Deposit holds $500.
- Case Y: the $300 comes back after the termination. At the termination the Pet Deposit holds $200.

The plan text says "the returned amount of a pre-termination Pet Refund-review Refund", which covers both cases. The pay-back option you chose said "it had already left the Pet Deposit before the termination; BR-DEP-022 keeps only what the Deposit held at the termination", which covers only case Y.

- (a) Only money returned after the termination is paid back. Case Y: $300 paid back, $200 forfeited. Case X: all $500 forfeited.
- (b) Any return of a Refund paid before the termination is paid back. Case X: $300 paid back, $200 forfeited, the same as case Y.

Recommendation: (a), because BR-DEP-022 keeps what the Deposit held at the termination, as the option you chose said.

Until you answer, no 10c-2b-5 code. In the plan order, 10e-3 comes after 10c-2b-5 and also reuses the 10e-1c charge (waiting for Q-72). 10c-2a-7, 10c-3c-1 and 10c-3c-2 depend on neither question, but the plan puts them after 10e-3; I do not start them without your word.

**Owner answer (2026-10-10, fresh session).**

1. Point 1: option (A). Returned money under pay back is DL-032 money everywhere, also after closure.
2. Point 2: option (b). Any returned Refund that was paid before the termination is paid back, also when it came back before the termination. This follows the Q-73 answer: returned money is the Customer's, so a forfeiture leaves it out. "BR-DEP-022 keeps only what the Deposit held at the termination" is read as not including returned Refund money. If (b) conflicts with another rule or needs a tightening, write it here with a recommendation and stop.
3. From now on, if one sub-slice waits for an owner answer, the next sub-slice that does not depend on that answer may be built without asking; the report says so.

Recorded in docs/010. Implementer note: answer (b) leaves one rule open, because a Pet Refund-review Refund may be paid again after a return before the termination; see Q-2026-10-10-76. 10c-2b-5 waits for it.

## Q-2026-10-10-76 — Pay back under answer (b) to Q-75: which money a later Pet Refund-review Refund pays (blocks 10c-2b-5) (ANSWERED 2026-10-11: (a); answer in docs/010)

Your answer (b) to Q-2026-10-10-75 point 2 makes the returned money of any Pet Refund-review Refund paid before the termination the Customer's, also when it came back before the termination. A forfeiture leaves it out (Q-73 (a)), and it is DL-032 money everywhere (Q-75 point 1 (A)).

**What the code allows (read at head `20261120_116`).** While the Lease is signed, a Pet Refund-review Refund can be paid again and again from the same review, for any amount up to what the Pet Deposit holds (`app.pet_refund_qualification` and `app.assert_pet_refund_source`: no limit of one Refund per review or per Deposit). So after a return before the termination, staff can pay the returned money out again with a new Pet Refund-review Refund. Under option (a) of Q-75 this could not matter, because no Pet Refund-review Refund is paid after the termination.

**What is missing.** At the termination the system must know how much of the money the Pet Deposit holds is still returned money (paid back) and how much is its own money (forfeited under BR-DEP-022). No rule says which money a later Pet Refund-review Refund pays out: the returned money or the Deposit's own rest.

**Example.** A Pet Deposit of $500. While the Lease is signed:
1. A $300 Pet Refund-review Refund is paid. The Pet Deposit holds $200.
2. The $300 comes back (the bank account was closed). The Pet Deposit holds $500: $200 of its own and $300 returned.
3. Staff pay a new Pet Refund-review Refund of $300 to the Customer's new account. The Pet Deposit holds $200.

Later the Lease is terminated for pet noncompliance.

**Options:**
- (a) A later Pet Refund-review Refund pays the returned money first. In the example the $300 Refund of step 3 pays out the returned $300 again; at the termination the $200 held is the Deposit's own money and is forfeited. With a $100 Refund in step 3, $200 is paid back and $200 is forfeited. The Customer ends with the same money as if the first Refund had arrived. It needs a running count over the Pet Deposit's history (returns add returned money; a return reversal and a later Pet Refund-review Refund take it out first).
- (b) A later Pet Refund-review Refund pays the Deposit's own money first. In the example the $300 Refund of step 3 pays the own $200 and $100 of the returned money; at the termination the $200 held is returned money and is paid back; nothing is forfeited. With a $100 Refund in step 3, $300 is paid back and $100 is forfeited. This is the simple count of the 10c-2b-5 design (the smaller of what the Deposit holds and the returned amount, less return reversals), with "after the termination" removed. The Customer ends with $200 more than if the first Refund had arrived.

**Recommendation: (a)**, because the bank return then changes nothing for the Customer or the Property: the new Refund pays out again exactly the money that came back, and BR-DEP-022 keeps the same own money as without the return. With (b), a bounce followed by a new Refund would also pay back own money that BR-DEP-022 keeps. Neither option needs another tightening: the forfeiture leaving out returned money is your Q-73 answer, extended by your Q-75 answer (b).

**What goes ahead.** 10c-2b-5 waits for this answer (no code, no run). Under your new instruction, the sub-slices that do not depend on it go ahead: 10e-1b, 10e-1c and 10e-2 come before 10c-2b-5 in the plan order anyway. 10e-3 comes after 10c-2b-5 and undoes what a pay-back Refund paid, so it waits too; after 10e-2 the next independent sub-slices are 10c-2a-7, 10c-3c-1, 10c-3c-2, 10f, 10g and the real-path tests.

**Owner answer (2026-10-11).** (a). A new Pet Refund-review Refund pays the returned money first, then the Deposit's own money. A bank return then changes nothing for either side. In the example the Customer ends with $300 and the termination keeps $200.

Recorded in docs/010. 10c-2b-5 may now be built in the plan order (after 10e-2); its pay-back value becomes the running count of option (a): a verified return of a Pet Refund-review Refund paid before the termination adds returned money, and a return reversal or a later Pet Refund-review Refund takes it out first.

## Q-2026-10-10-77 — Sub-slice 10e-1b review round 1: the example in Q-72 point 2 does not happen (ANSWERED 2026-10-10: keep the amount check; answer in docs/010)

The independent reviewer of 10e-1b round 1 (SF-3) found that the written option (a) of Q-2026-10-10-72 point 2 says a Deposit that would still hold money after the return is refused, "for example a returned Pet Refund-review Refund". That example does not happen: a Refund that was paid and then fully returned cancels out, so the Deposit holds exactly the receipt again and the receipt reversal leaves it at $0. The code checks the amount (held value plus the active Deposit applications and forfeitures must equal the Payment's active receipts in that Deposit), so it accepts this case.

- (a) Keep the amount check, correct the example in the docs and add a test of a fully returned Refund on a funded Deposit.
- (b) Refuse any funded Deposit that has a returned Refund (stricter; the text word for word).

Recommendation: (a), because the money really is gone once the bounced Payment's receipt is reversed, and refusing would leave such a Payment with no fix.

**Owner answer (2026-10-10).** (a): keep the amount check, correct the example in the docs, and add a test of a fully returned Refund on a funded Deposit. Then the round-1 fixes for SF-1 and SF-2; each note is fixed, answered in writing or put on the slice 12 list; then the runs and round 2 under the takeover rules and the standing round-3 rule.

Recorded in docs/010.

## Q-2026-10-11-78 — Sub-slice 10e-1c before code: who is charged for a Refund already paid from a bounced Payment, and on which Lease (blocks 10e-1c and so 10e-2) (ANSWERED 2026-10-11: A, B and C as recommended; answer in docs/010)

10e-1b is committed (73cd53b). The 10e-1c pre-code design is in the plan (10e-1c entry). Your answer to Q-2026-10-10-72 point 1 (option (a), its detail confirmed): money already refunded from a bounced Payment's value is owed back; a new Refund correction kind gives that amount back to the Refund's source on paper, and a charge of the same amount goes to the person who owes it, "on the Lease the money came from"; with a closed Final Settlement it is the `EXTRA_CHARGE`; "a returned Payment whose Refund has no Lease to charge on is refused (a known limit)".

**What the code allows (read at head `20261121_117`).** An Invoice that names a Lease must belong to a signed Customer of that Lease. A one-time charge that names a Lease may only bill the Primary Tenant. A Miscellaneous one-time charge with no Lease may bill any Customer (it already exists). A third-party payer is never a signed Customer of the Lease.

**The three kinds of Refund paid from a bounced Payment's value, and the open points.**

*1. A Deposit Refund* (the Deposit the Payment funded: the Settlement's or a correction's Deposit Refund, or a Pet Refund-review Refund, possibly paid to an agreed Signer). Clear: charge the Deposit owner (your rule) on the Deposit's Lease. Example: Security Deposit $1,000 from one Payment; the Settlement applied $600 and refunded $400; the Payment bounces: $600 of debt comes back and the $400 Refund is recovered by a $400 charge to the Deposit owner. Open only for a Reservation Deposit that never became a Lease's (no Lease).

*2. A Credit Refund* (a Credit recognized from the Payment, or released from one of its allocations by a credit Adjustment). The person who owes is the Credit's Customer. Which Lease is "the Lease the money came from" is not written. Example: a $500 Payment pays an Invoice of Lease A in full; a $100 credit Adjustment releases $100 as Credit, which is refunded; the Payment bounces. The $100 came from Lease A's Invoice.

*3. A Payment Refund* (unallocated value of the Payment refunded to the payer). The person who owes is the payer. A Payment of a normal Customer often names no Lease; a third-party Payment names a Lease, but the payer is not its Customer. Example: a Customer pays $1,200 for an $1,000 Invoice; $200 is refunded; the Payment bounces.

**Options.**

- Point A (Credit Refund, which Lease): (a) the Lease of the Invoice or Late-payment Charge whose allocation the credit Adjustment released into that Credit; for a Credit recognized from unallocated value, the Lease the Payment names. (b) Always the Lease the Payment names.
  Recommendation: (a), because that is where the money was used.
- Point B (no Lease, or the person who owes is not a signed Customer of that Lease: a Payment Refund of a payer with no named Lease, any third-party payer, a Reservation Deposit, a Credit with no Lease under A): (a) refused, the known limit you confirmed; such a Payment cannot be returned in the system while its Refund is out. (b) A Miscellaneous one-time charge with no Lease to that person, the existing no-Lease charge; nothing is refused.
  Recommendation: (b), because it keeps every bounced Payment returnable with true records, using a charge form that already exists. It changes the confirmed "refused" detail, so it needs your word.
- Point C (an ordinary charge on a Lease to a Signer who is not the Primary Tenant, for example a Credit Refund paid to a second Signer): (a) charge that Signer on the Lease (a relaxing exception to "Lease one-time charges bill only the Primary Tenant", for this writer only; the `EXTRA_CHARGE` already bills a Signer's own debt to that Signer). (b) Charge the Primary Tenant.
  Recommendation: (a), because the Signer received the money (BR-SETTLE-016: a Signer's own debt stays on that Signer's ledger).

**What goes ahead while this waits.** 10e-1c and 10e-2 (it reuses the 10e-1c charge) wait; 10c-2b-5 waits for Q-2026-10-10-76; 10e-3 comes after both. The next sub-slice that depends on neither answer is 10c-2a-7 (a pet classification fix for a Damage line billed from an inspection superseded before closure), then 10c-3c-1, 10c-3c-2, 10f, 10g and the real-path tests.

**Owner answer (2026-10-11).** The three recommendations are accepted. One plain rule covers all three: the person who received the refund money pays it back.

- A: for a Credit Refund, charge on the Lease where the money was used.
- B: when there is no Lease, or the person is not a Customer of that Lease, create a one-time Miscellaneous charge with no Lease; do not refuse. This replaces the earlier "refused" detail of Q-2026-10-10-72 point 1.
- C: when a second Signer received the money, charge that Signer directly.

Limits: use only charge types and records that already exist; if B needs a new Invoice type, a new charge rule, or a new Customer record for a person who is not yet a Customer, stop and ask first. The charge is the exact amount that was paid out, with no fee and nothing extra. Inside a closed-Settlement correction it is an `EXTRA_CHARGE` in the draft, confirmed with `financial.approve`, as in Q-72 point 1. An unpaid charge stays open; no write-off.

Also answered (10e-1b report, see Q-2026-10-11-79 for the follow-up): the three 10e-1b design choices are accepted; the next report confirms that the correction's own receipt reversal makes the same checks as the receipt reversal function (permission, amount and state), names the test that proves it, and adds a missing check in the next sub-slice that touches that code or puts it on the slice 12 list if it is only hardening. Before 10e-2 the shared helper is split, with the 10e-1a tests unchanged; if a committed test must change, stop and ask.

Recorded in docs/010.

## Q-2026-10-11-79 — Sub-slice 10e-1c: a returned Payment must stop refusing a Refund that is out, and three committed test assertions say it refuses (blocks 10e-1c and so 10e-2) (ANSWERED 2026-10-11: (a); answer in docs/010)

Your answer to Q-78 makes every bounced Payment returnable: the person who received a Refund paid from its value is charged back. With a closed Final Settlement that happens inside the `RETURNED_PAYMENT` correction (10e-1b); with no closed Settlement in the `PAYMENT_RETURN` draft (10e-1a). Today both refuse such a Payment (55000, "A Refund paid from this Payment's value is not fully returned"), as planned "until 10e-1c". Three committed test assertions check that refusal:

- 10e-1a, `test_each_refusal_of_the_source_state_is_checked`: calls the refusal function with a Refund of the Payment, of a Credit and of a Deposit that is out, and expects 55000 each time.
- 10e-1a, `test_refusals_stale_drafts_withdrawal_and_reads`: refunds 30.00 of a third-party Payment's released Credit to the Invoice Customer and expects the return draft to be refused.
- 10e-1b (committed 73cd53b), `test_refusals_stale_drafts_and_a_deposit_that_would_still_hold_money`: the Pet Deposit's Payment, from which the Settlement refunded 54.00, is refused with that message.

You asked to stop before changing a committed test. There is no 10e-1c code.

- (a) Change only those assertions (names kept, a comment, a docs/010 note): the Refund cases are no longer refused; instead the confirm recovers the Refund by a charge of the same amount to the person who received it (your answers to Q-72 point 1 and Q-78). In the 10e-1b test the Pet Deposit's Payment is then recorded and a new 10e-1c test confirms it (54.00 charged back as an `EXTRA_CHARGE`); in the 10e-1a test the 30.00 is charged to the Invoice Customer on that Invoice's Lease.
- (b) Keep the three assertions unchanged and add a separate action for a return with recovery (for example an input flag "recover refunds" on the same draft): without it the refusal stays; with it the charges are written. Staff then choose the action, and a Payment with a Refund out is refused until they use the other one.

Recommendation: (a). It is what your Q-72 point 1 and Q-78 answers describe, the refusal was planned to end in 10e-1c, and (b) adds a second path for the same business case.

What goes ahead while this waits: 10e-1c and 10e-2 (it recovers a Settlement Refund already paid from the corrected Deposit with the 10e-1c charge) wait, with the helper split before 10e-2; 10c-2b-5 and 10e-3 wait for Q-2026-10-10-76. The next sub-slices that depend on neither answer: 10c-2a-7, 10c-3c-1, 10c-3c-2, 10f, 10g and the two real-path tests.

**Owner answer (2026-10-11).**

1. (a). Ending the "Refund not fully returned" refusal follows from the Q-78 answer. Change only the three assertions named above: two in the 10e-1a tests and one in the 10e-1b test. Each changed assertion must now check the new result exactly: who is charged, on which Lease or with no Lease, and the amount. Add a docs/010 note.
2. Keep each test's name unless the name would then say the wrong thing. In that case rename it and update ops/traceability.json in the same commit. The independent reviewer compares each changed test with HEAD and confirms nothing else got weaker.
3. The receipt reversal check of the 10e-1b report is accepted. Add the "Deposit belongs to this Property" check in 10e-1c, as proposed. Also add the test that the direct path (the correction's own receipt reversal) is refused in a bad state in 10e-1c, not in slice 12, because it is cheap and it is on a money path.
4. New standing rule: when an owner answer ends a refusal, and a committed test asserts that refusal, the implementer may change that assertion to the new expected result without asking. The report names each such test, and the independent reviewer compares it with HEAD. Any other change to a committed test still needs the owner.

Recorded in docs/010; the standing rule is also in ops/V1_055_RUN_RULES.md.

## Q-2026-10-11-80 — Sub-slices 10c-2a-7 and 10c-3c-2: each one turns a committed refusal test into an allowed case (blocks those two sub-slices only) (ANSWERED 2026-10-11: (a); answer in docs/010)

Your instruction of 2026-10-11: stop and ask before a committed test changes. A read-only check before code found that two of the next sub-slices you approved change one committed test each, because the test asserts exactly the refusal the sub-slice removes. There is no code for either.

*1. 10c-2a-7* (your answer (a) to Q-2026-10-08-53: a Damage line billed from an inspection superseded before closure may be set to pet damage). The committed 10c-2a-5 test `test_a_line_billed_from_an_inspection_superseded_before_closure_is_not_eligible` records exactly that to-pet correction and expects it refused ("A pet classification correction corrects only a Damage line billed from a finding of a current inspection") with no draft written. After 10c-2a-7 that correction is allowed.

*2. 10c-3c-2* (your answer (a) to Q-2026-10-10-70: `CHARGE_REDUCTION` may reduce a partly Deposit-paid obligation within its unpaid rest). The committed 10c-1a test `test_an_invoice_paid_by_a_deposit_application_takes_no_charge_reduction_yet` reduces by 5.00 a 125.00 Damage line of which the Pet Deposit paid 10.00 (115.00 unpaid) and expects the refusal "A Deposit application paid this obligation at Final Settlement". After 10c-3c-2 that reduction is allowed. (The 10c-3a test `test_a_charge_a_deposit_paid_or_of_another_lease_is_refused` reduces a Charge the Pet Deposit paid in full; it stays refused, and the build keeps that refusal's message for an obligation with no unpaid rest, so that test does not change.)

- (a) In each test change only the expectation (name kept, a comment, a docs/010 note): the correction is recorded and confirmed, and the test checks the result to the cent (the line reads as pet damage; the line owes 110.00 with the 10.00 Deposit application unchanged). The refusal each test protected is still tested by the remaining cases (a line of an inspection superseded before closure still cannot be set to not pet damage; a reduction above the unpaid rest and a fully Deposit-paid Charge stay refused).
- (b) Keep both tests unchanged and leave the two sub-slices unbuilt (the two known limits stay).

Recommendation: (a), because each test asserts the gap you decided to close (both test names already say "not eligible" and "yet", written before your answers).

What goes ahead while this waits: 10c-3c-1 (the allow-function hardening; its pre-code check looks for committed tests it would change first), 10f and 10g pre-code designs, and the two real-path tests (tests only).

**Owner answer (2026-10-11).** (a). Ending these two refusals follows from the Q-53 and Q-70 answers. Change only the expectations of `test_a_line_billed_from_an_inspection_superseded_before_closure_is_not_eligible` (10c-2a-7) and `test_an_invoice_paid_by_a_deposit_application_takes_no_charge_reduction_yet` (10c-3c-2). Keep the tests that show the limits still hold: a correction that is not to-pet on such a line is still refused, and a reduction larger than the unpaid rest is still refused. Keep each test's name unless the name would then say the wrong thing; in that case rename it and update ops/traceability.json in the same commit. The independent reviewer compares each changed test with HEAD and confirms nothing else got weaker.

Recorded in docs/010. Implementer note: both names say the old result ("is not eligible", "takes no charge reduction yet"), so each sub-slice renames its test and updates its traceability entry in the same commit.

## Q-2026-10-11-81 — Sub-slice 10e-1c: three returned Payments that are still refused (not blocking 10e-1c; the owner answers before 10h) (ANSWERED 2026-10-11: 1 (a), 2 (a), 3 (c); follow-up Q-2026-10-11-82 blocks sub-slice 10e-4; answers in docs/010)

10e-1c is built in the working tree (not committed; record ops/reviews/V1-056-slice-10e-1c-payment-return-recovery.md). It recovers every Refund paid from a bounced Payment by a charge to the person who received it, as your Q-78 answers say. Three cases still refuse the return (55000), as they did before 10e-1c. Your answer B said "nothing is refused", so each needs your word.

*1. A Reservation Deposit Refund of a cancelled Reservation.* Example: a Reservation's $100 Security Deposit is paid by bank transfer; the Property cancels and refunds the $100; then the transfer bounces. This Refund belongs to the Reservation's own outcome records, which are corrected only through the Reservation path (its outcome must stay complete), not through a Refund correction.
- (a) Keep it refused (a known limit); staff record the loss outside the system.
- (b) A later small sub-slice: recover it through the Reservation outcome path, with a no-Lease charge to the person refunded (your answer B).
Recommendation: (a) now, (b) only if you expect it; it needs a cancelled Reservation whose refunded deposit transfer bounces.

*2. A Refund of a Deposit that two Payments funded.* Today every Deposit has one receipt (only the Reservation writes receipts), so this cannot happen in normal use; it is a guard: the system cannot tell which Payment the Refund came from.
- (a) Keep the refusal as a guard. (b) Charge the whole Refund to the recipient anyway.
Recommendation: (a).

*3. A Payment whose money was used on a Lease whose Final Settlement is closed, although that Settlement did not rely on the Payment.* Example: after closure the Customer sends $900 naming the closed Lease; $300 is refunded to them; then the transfer bounces. The charge belongs on that Lease, but only a correction of its Settlement may write there, and that correction refuses the Payment because the Settlement did not rely on it. So the Payment cannot be returned at all.
- (a) Keep it refused (the plan's choice; a known limit).
- (b) Charge it with no Lease (as answer B does when there is no Lease).
- (c) Let the RETURNED_PAYMENT correction of that Settlement also take such a Payment, so the charge is an EXTRA_CHARGE on that Lease.
Recommendation: (c), because it keeps "on the Lease where the money was used" and changes that Settlement only through a correction (BR-SETTLE-013). It is a relaxing change to the correction's "did not rely on" refusal, for this case only.

Until you answer, the three cases stay refused (a test shows each), and 10e-1c continues: its commit does not depend on these answers.

**Owner answer (2026-10-11).**

1. Cancelled Reservation Deposit Refund: keep the refusal. Record it in docs/010 as a known limit, with a test, and add it to the later-work list.
2. Deposit funded by two Payments: keep the refusal as a guard, with a test.
3. Payment used on a Lease whose closed Settlement did not rely on it: option (c). That Settlement's correction takes the Payment, and the charge is an `EXTRA_CHARGE` on that Lease. The charge is the exact amount, billed to the Customer whose debt the Payment paid. If the design differs, ask first. Add it to the plan as a sub-slice before 10h, where it fits best.

Recorded in docs/010 and the plan: points 1 and 2 are tested in `test_the_refused_cases_on_real_sources` (sub-slice 10e-1c); the Reservation outcome recovery is in the plan's possible later work; point 3 is sub-slice 10e-4, after 10e-3. The 10e-1c design charges the person who received the refund money (your Q-2026-10-11-78 rule), which can differ from "the Customer whose debt the Payment paid", so Q-2026-10-11-82 asks before 10e-4 is built.

## Q-2026-10-11-82 — Sub-slice 10e-4 (Q-81 point 3): who is charged when the person refunded is not the Customer whose debt the Payment paid (blocks 10e-4 only) (ANSWERED 2026-10-11: (a) with one addition; answer in docs/010)

Your answer to Q-2026-10-11-81 point 3: option (c), "the charge is the exact amount, billed to the Customer whose debt the Payment paid. If your design differs, ask me."

**What the design does.** Sub-slice 10e-1c follows your Q-2026-10-11-78 rule: "the person who received the refund money pays it back". 10e-4 would reuse it. In your Q-81 example both rules give the same person: the Customer sends $900 naming the closed Lease, $300 is refunded to that Customer, the transfer bounces; the correction of that Lease's Settlement charges $300 to that Customer as an `EXTRA_CHARGE` on the Lease.

**Where the two rules differ.** Example: Lease L is closed and has two signed Customers, A (Primary Tenant) and B. After closure B sends $900 naming L. $600 of it pays A's $600 `EXTRA_CHARGE` Invoice; the $300 left is refunded to B. Then the transfer bounces. The correction reverses the $600 allocation, so A owes the $600 again (no new charge is needed for that part). For the $300 Refund:

- (a) Charge B, who received the $300, as an `EXTRA_CHARGE` on L. This is the rule 10e-1c uses for every returned Payment.
- (b) Charge A, whose debt the Payment paid, as an `EXTRA_CHARGE` on L.

When the Payment paid nobody's debt (all of it was unallocated and part of it was refunded), (b) has no Customer, so the person refunded is charged as in (a). Both options charge the exact net amount still out, with no fee.

**Recommendation: (a)**, because B received the $300, and it keeps one rule for every returned Payment (10e-1c and 10e-4).

**What goes ahead.** Only 10e-4 waits. 10e-2, 10c-2b-5, 10e-3, 10c-2a-7, 10c-3c-1, 10c-3c-2, 10f and 10g do not depend on this answer. Until 10e-4 is built, such a Payment stays refused (tested).

**Owner answer (2026-10-11).** Keep the design, with one addition. Use the same rule as Q-78: when the bounced money was refunded to someone, the person who received the Refund pays it back. When no one was refunded, the Customer whose debt the Payment paid is charged. The charge is the exact amount. Add a test for each case.

Recorded in docs/010. Implementer reading, stated in the 10e-4 design and report: in the second case the correction reverses the Payment's allocation, so the debt comes back on its obligation and stays with the Customer whose debt the Payment paid (BR-SETTLE-016), for the exact amount; no second charge is written, because that would bill the same debt twice. 10e-4 is built in the plan order (after 10e-3).

## Q-2026-10-11-83 — Sub-slice 10e-2 stopped before code: three points of the Deposit receipt correction (blocks 10e-2 only) (ANSWERED 2026-10-11: point 1 no amendment, the freed value stays with the Payment; point 2 a new receipt writer; point 3 (a); answer in docs/010)

10e-1c is committed (2eb7389). The 10e-2 pre-code design is in the plan (10e-2 entry). Your answer (a) to Q-2026-10-08-56: a Deposit receipt that is wrong while its Payment is real is fixed after closure by a `DEPOSIT_RECEIPT_CORRECTION`; it reverses the Deposit's applications and the receipt; a Refund already paid from that Deposit is charged back (the Q-78 rule: the person who received it); "the freed Payment value becomes the payer's Customer Credit, which first pays that Customer's open debt on the Lease through the shared step, and only the rest is refunded or kept as Credit". There is no 10e-2 code and no run.

**What the code allows (read at head `20261122_118`).** Only the Reservation writes a Deposit receipt, so every Deposit has one receipt from one Payment. Nothing can write a new receipt into another Deposit or for another amount, and a receipt reversal always takes the whole receipt. After closure, Customer Credit pays debt before any Deposit money (your answer to Q-2026-10-07-42).

*1. The Credit needs your word under BR-CREDIT-002.* BR-CREDIT-002 says unallocated Payment value becomes Customer Credit only after the payer authorizes it, never automatically. The only exception today is a credit Adjustment's release (BR-CREDIT-014). Your Q-56 answer makes the freed value Credit at once.
- (a) Amend BR-CREDIT-002 (and BR-CREDIT-003) for this case, like BR-CREDIT-014: the freed value of a confirmed `DEPOSIT_RECEIPT_CORRECTION` becomes the payer's Credit at once, identified by the correction and the reversed receipt; the `financial.approve` confirm is the authorization.
- (b) The payer's written authorization is an input of the draft (an authorization reference, as a normal Credit needs); without it the freed value is refunded to the payer in the same correction, after the payer's own open debt on the Lease is paid (which itself needs a Credit, so in practice (b) needs the authorization every time).
- (c) The freed value stays unallocated on the Payment (no Credit); it pays no debt in the correction; staff deal with it later (after closure today only a Refund can move it).

Recommendation: (a). It is what your Q-56 answer describes, and the correction already carries a reason, evidence and a `financial.approve` confirm.

*2. "The wrong Deposit" and "the wrong amount".* Example: a Payment of $1,000 was recorded as a $1,000 Security Deposit receipt, but $800 was the Security Deposit and $200 was the Pet Deposit (or $200 was Rent). The Settlement applied $600 of the Security Deposit to debt and refunded $400. Because no function can write a new receipt, the correction cannot move $200 into the Pet Deposit or keep $800 in the Security Deposit.
- (a) As your Q-56 answer reads: the whole $1,000 receipt is reversed; the $600 of debt comes back; the $400 Refund is charged back to the person who received it; the $1,000 becomes the payer's Credit, which pays the $600 and the $400 charge first; nothing is left. In every case the Deposit ends at $0 and the value works as Credit. After closure a Deposit has no further role, so the only difference is the DL-032 order: money that should have been Pet Deposit pays pet damage only if the Credit reaches it in Credit order.
- (b) A correction that also writes a new receipt (into the right Deposit, or for the right amount): a new receipt writer after closure and a new DB-SETTLE-005 link; then the shared step applies that Deposit in its DL-032 place. A larger sub-slice.
- (c) Only the "not a Deposit at all" case (for example meant for Rent) is built; a receipt in the wrong Deposit or for the wrong amount is refused (a known limit).

Recommendation: (a), because it needs no new kind of receipt and gives every case a fix; the result for the Customer is the same total.

*3. A Deposit the Property kept (an active forfeiture).* Example: the $1,000 Security Deposit was kept because the Customer left early; later staff find that the $1,000 receipt was really Rent.
- (a) Refuse (55000) while the Deposit has an active forfeiture: staff first undo the forfeiture with the `FORFEITURE_REVERSAL` correction (10d, which already exists, with its own reason and the DL-032 step), then record the receipt correction.
- (b) The receipt correction reverses the forfeiture itself, as a linked record (as the `RETURNED_PAYMENT` correction does for a bounced Payment, Q-72 point 2).

Recommendation: (a). Whether the Property still keeps a Deposit is a separate decision with its own rule (BR-DEP-019, BR-DEP-023), and 10d already records it; (b) would undo a forfeiture as a side effect of a receipt fix.

**What goes ahead.** 10e-2 waits (no code). The next sub-slice that depends on none of the open answers is 10c-2b-5 (its design is in the plan; Q-76 is answered), then 10e-3, 10c-2a-7, 10c-3c-1, 10c-3c-2, 10f and 10g; 10e-4 waits for Q-82.

**Owner answer (2026-10-11).**

1. Point 1: do not amend BR-CREDIT-002. Money freed by the correction becomes Credit only with the payer's authorization, as the rule says. Until then it stays with the Payment, the way an overpayment works today.
2. Point 2: add a new function that writes the right receipt, so the correction can move the money straight to the right Deposit, or record the right amount, without a Credit step. New functions only, no tightening.
3. Point 3: a Deposit the Property kept: yes, refuse until a `FORFEITURE_REVERSAL` runs first (option (a)).
4. If point 1 or point 2 turns out much bigger than the plan expects, or conflicts with another rule, write it in this file with a recommendation and stop that sub-slice.

Recorded in docs/010. The 10e-2 design in the plan is rewritten to these answers before code.

## Q-2026-10-11-84 — Sub-slice 10c-2b-5 stopped before code: a committed test fixture changes, not only a refusal (blocks 10c-2b-5, and 10e-3 after it) (ANSWERED 2026-10-11: (a); answer in docs/010)

The 10c-2b-5 design is in the plan (pay back, design (A), with your answers (b) to Q-2026-10-10-75 point 2 and (a) to Q-2026-10-10-76). A read-only check of every backend test before code found a change the standing rule does not cover. There is no code and no run.

**The fixture.** The committed fixture `reviewed_case(pet_noncompliance=True)` (sub-slice 10c-2b-2b) builds: a Pet Deposit of $200.00; a Pet Refund-review Refund of $150.00 while the Lease is signed; $30.00 of it comes back before the termination (a verified return); the Lease is terminated for pet noncompliance (BR-DEP-022); both Deposits are forfeited in full ($80.00 of the Pet Deposit); the Final Settlement closes with no step. Two committed tests use it: `test_a_returned_pet_refund_off_the_dl032_path_is_only_held` (10c-2b-2b) and `test_held_pet_deposit_money_off_the_dl032_path_waits_for_the_owner` (10c-2b-3).

**What your answers change in it.** The $30.00 returned before the termination is now the Customer's pay-back money (Q-75 (b), Q-76 (a)). So the forfeiture takes only $50.00 (Q-73 (a)), the Pet Deposit keeps $30.00 on the DL-032 path, and the Settlement must refund or apply it (BR-SETTLE-008). The fixture's Settlement with no step is then refused, so both tests fail inside the fixture before they reach their own assertions.

**The two tests' own assertions** (the refusal "A returned Deposit pays debt or is refunded again only on the DL-032 path" for the kept Pet Deposit after closure) are exactly the refusal your pay-back answer ends. The standing rule lets me change those assertions to the new result (the return with a new Refund, and the held-value Refund, are accepted and pay back the returned money); both names would then say the wrong thing ("is only held", "waits for the owner"), so each is renamed with its traceability entry, and the report names them.

**Options for the fixture:**
- (a) In the `pet_noncompliance` branch only, the Settlement refunds the Pet Deposit's $30.00 pay-back money to the Customer (one Deposit Refund step), and the docstring says so. The forfeiture amounts follow the new rule ($50.00 of the Pet Deposit, the Security Deposit unchanged). Every other use of the fixture is unchanged (no ground, so no pay-back).
- (b) Remove the early $30.00 return from the `pet_noncompliance` branch, so the Settlement still closes with no step; the forfeiture is then $50.00 for another reason (the $150.00 Refund is not returned at all). This changes more of the fixture's history than (a).
- (c) Keep the fixture and leave 10c-2b-5 unbuilt (the pay-back gap stays).

**Recommendation: (a).** It is the smallest change and shows your rule on the fixture itself: the Customer gets back the $30.00 that came back before the termination, and the Property keeps the rest of the Pet Deposit.

**What goes ahead.** 10c-2b-5 waits, and 10e-3 after it (it undoes what a pay-back Refund paid). 10e-2 waits for Q-83 and 10e-4 for Q-82. The next sub-slice that depends on no open answer is 10c-2a-7 (your answers to Q-2026-10-08-53 and Q-2026-10-11-80), then 10c-3c-1, 10c-3c-2, 10f and 10g.

**Owner answer (2026-10-11).** Yes, (a). In the `pet_noncompliance=True` branch of `reviewed_case` only, the Settlement refunds the $30.00 that came back before the termination, and the forfeiture becomes $50.00. This follows the Q-75 and Q-76 answers. Assert both amounts exactly.

Recorded in docs/010.

## Q-2026-10-11-85 — Sub-slice 10c-2a-7 before code: the committed test needs a DL-032 plan, not only a new expectation (blocks 10c-2a-7 only) (ANSWERED 2026-10-11: (a); answer in docs/010)

Your answer (a) to Q-2026-10-11-80: in `test_a_line_billed_from_an_inspection_superseded_before_closure_is_not_eligible` change only the expectation: "the correction is recorded and confirmed, and the test checks the result to the cent". A read-only check before code found that this needs more than the expectation. There is no code and no run.

**Why.** The test closes the Final Settlement by hand (the owner closure helper of sub-slice 8e-1), not by the real confirm. So at closure the Security Deposit still holds $100.00, the Pet Deposit $200.00 and the Customer has $4.00 of Credit, while the two Damage lines ($125.00 each) are unpaid. Every post-settlement correction runs the shared DL-032 step, which refuses a plan that leaves Deposit money unused while debt is open (55000, "Every remaining Deposit balance must be applied or refunded") and requires the Customer's Credit first. The test's correction has no steps, so after 10c-2a-7 it is refused with that message instead of being recorded.

**Options:**
- (a) Keep the test's setup and its correction, and add the steps the DL-032 plan check requires to its command (the Credit first, the Pet Deposit on the line now pet damage, the Security Deposit on the other line, the remaining Pet Deposit with its decision, then a Refund of what is left), so the correction is recorded and confirmed; the test then checks every amount to the cent and that the line reads as pet damage. Only the correction call and the expectation change; the name changes (it would say the wrong thing) with its traceability entry.
- (b) Move the case to the real-closure fixture (the 8e-3 confirm, Deposits used at closure) with the inspection superseded before the confirm; the correction then needs no or few steps. This replaces the test's setup.
- (c) Keep the committed test as it is and test the new rule only in new tests; the committed test then fails (its refusal ends), so (c) is not possible without changing it.

**Recommendation: (a)**, the smallest change that still records and confirms the correction as your answer says. The new tests of 10c-2a-7 (to pet damage with and without Pet Deposit money on the DL-032 path, the other direction still refused, the evidence naming the new inspection's finding) are built on the real-closure fixture.

**What goes ahead.** 10c-2a-7 waits. The next sub-slices that depend on no open answer are 10c-3c-1 (the allow-function hardening; its pre-code check looks for committed tests it would change first), 10c-3c-2 after it, 10f and 10g.

**Owner answer (2026-10-11).** Yes, (a). Keep the setup and add the full DL-032 steps the correction needs. Keep a test that a correction that is not to-pet on such a line is still refused.

Recorded in docs/010.

**Owner standing rule (2026-10-11, replaces the rule of the Q-2026-10-11-79 answer).** When one of the owner's answers changes a result, and a committed test or fixture expects the old result, the implementer may update it to the new result without asking. Change only the affected case or branch. Name each change in the report. The independent reviewer compares it with HEAD and confirms nothing else got weaker. A change that removes a check, or that the answer does not cover, still needs the owner's OK. Also in docs/010 and ops/V1_055_RUN_RULES.md.

## Q-2026-10-11-86 — Sub-slice 10e-2 stopped before code: the "right receipt" function is much bigger than planned and conflicts with two receipt rules (blocks 10e-2 only) (ANSWERED 2026-10-12: (a); the right receipt is sub-slice 10e-2b, which waits for Q-2026-10-12-87; answer in docs/010)

Your answer to Q-2026-10-11-83 point 2: a new function writes the right receipt, so the correction moves the money straight to the right Deposit, or records the right amount; new functions only, no tightening. You also said: if it turns out much bigger than the plan expects, or conflicts with another rule, write it here and stop. A read-only check before code (head `20261122_118`, read from a throwaway database's catalog) found both. There is no 10e-2 code and no run.

**What the database allows today.**

1. A Deposit takes at most one receipt from each Payment: the key `UNIQUE (deposit_id, payment_id)` (DB-DEP-002). A reversed receipt still counts. So the correction cannot reverse the $1,000 receipt and write an $800 receipt into the same Deposit from the same Payment. Changing this needs a change to the table key, not only a new function.
2. A Security Deposit's first receipt must equal the amount its Reservation accepted, and all its receipts together may not pass the required amount (the receipt check). A $1,000 receipt was only possible because the agreed Security Deposit was $1,000. So "$800 was the Security Deposit" means the agreed amount was wrong too: the fix also needs a required-amount decrease (DB-DEP-003; today the one-call `deposits.manage` command, with no closure check) and a receipt that differs from the accepted amount, which the receipt check refuses. Changing this needs a patch of the receipt check, not only a new function.
3. No function writes a Pet Deposit receipt today. Only the Reservation writes receipts, and only for a Security Deposit; `app.create_pet_deposit` creates a Pet Deposit with no money. Moving money into the Pet Deposit would be the first Pet Deposit receipt writer in the system.
4. Your Q-83 example ($1,000 recorded as Security Deposit, really $800 Security Deposit and $200 Pet Deposit) needs all three. Only a whole receipt that belongs whole in another Deposit of the same Lease needs none of points 1 and 2, but still point 3 when that Deposit is the Pet Deposit (a Lease has one Security Deposit).
5. The DL-032 plan is checked when the draft is recorded, before anything is written; a new receipt's money also needs its own overlay key in the plan, a DB-SETTLE-005 link and its own closure checks.

Your point 1 (the freed value stays with the Payment until the payer authorizes Credit) is small and has no conflict: the correction leaves the value unallocated; after the payer's written authorization, staff recognize the Credit the normal way (`app.recognize_customer_credit`; no closure check refuses it), and the next correction that runs the shared DL-032 step uses that Credit first (your answer to Q-2026-10-07-42).

**Options.**

- (a) Build 10e-2 now without a new receipt: as linked records, the correction reverses the Deposit's applications newest first (the debt comes back on its obligations and stays with their Customers, BR-SETTLE-016), recovers each Refund paid from the Deposit by a charge to the person who received it (the 10e-1c writer), and reverses the whole receipt; the freed value stays unallocated with the Payment (your point 1); a Deposit the Property kept is refused until a `FORFEITURE_REVERSAL` runs (your point 3). The right receipt becomes a later sub-slice 10e-2b, built after your word on the three rule points: (i) replace the one-receipt-per-Payment key by a check that a Deposit has at most one active receipt from a Payment; (ii) let a correction receipt differ from the accepted amount, with a required-amount decrease in the same correction; (iii) the first Pet Deposit receipt writer, inside a correction only.
- (b) Build all of it now as one larger sub-slice, with the three changes (i) to (iii) approved by you now.
- (c) Build (a) and keep the right receipt as a known limit: after the correction the money stays with the Payment until the payer authorizes Credit or it is refunded.

**Recommendation: (a).** It gives every wrong receipt a true fix now (the debt comes back to its Customers, the Refund is charged back, the money comes back to the Payment), keeps BR-CREDIT-002 as you said, and keeps the three receipt-rule changes for a separate decision, because (i) and (ii) also change what a Reservation and a Pet Deposit accept before closure.

**What goes ahead.** 10e-2 waits (no code). The next sub-slice that depends on no open answer is 10c-2b-5 (your answer (a) to Q-2026-10-11-84), then 10e-3, 10e-4 (your answer to Q-2026-10-11-82), 10c-2a-7, 10c-3c-1, 10c-3c-2, 10f and 10g.

**Owner answer (2026-10-12).**

1. Option (a). Build 10e-2 now without the new receipt: the correction reverses the wrong receipt, and the freed money stays with the Payment. The right receipt becomes a later sub-slice, 10e-2b. The gap must still close before V1-056 ends, as said in Q-2026-10-08-56.
2. For 10e-2b, the three receipt rules are written as one new question in simple words, each with a short dollar example, the options and a recommendation: Q-2026-10-12-87.
3. The `twice_forfeited_case` fixture change (sub-slice 10c-2b-5): confirmed.
4. The slice 12 tightening (the pay-back limit in the forfeiture's insert check): yes. Returned money is the Customer's, so no path may forfeit it, including the owner-only one-call disposition. Build it as a small sub-slice before 10h, where it fits best. When it lands, change `twice_forfeited_case` so its second forfeiture uses the Deposit's own money, under the standing rule. If that is not possible, tell the owner.

Recorded in docs/010. Placement (implementer): the tightening is sub-slice 10c-2b-6, right after 10e-2 and before 10e-3, because it is small, depends on no open answer, and the 10e-3 and 10h pre-code designs check the invariant it enforces (no money other than pay-back money may be forfeited from a Pet Deposit with the BR-DEP-022 ground).

## Q-2026-10-12-87 — Sub-slice 10e-2b (the right receipt): three receipt rules stand in the way (blocks 10e-2b only) (ANSWERED 2026-10-12: (a), (a), (a); 10e-2b moves up after 10c-2b-6; answer in docs/010)

Your answer to Q-2026-10-11-83 point 2: a new function writes the right receipt, so a `DEPOSIT_RECEIPT_CORRECTION` moves the money straight to the right Deposit, or records the right amount. Your answer (a) to Q-2026-10-11-86 builds 10e-2 first without it: the wrong receipt is reversed and the money stays with the Payment. 10e-2b then writes the right receipt in the same kind of correction. Three rules of the receipt table stop that today (read at head `20261123_119`). Each needs your word. There is no 10e-2b code.

All three examples start the same way: a Payment of $1,000 was recorded as a $1,000 Security Deposit receipt. After closure staff find that the receipt was wrong.

**Rule 1. A Deposit takes only one receipt from each Payment, even after a reversal.**

The table key `UNIQUE (deposit_id, payment_id)` (DB-DEP-002) counts every receipt, also a reversed one.

Example: really $800 was the Security Deposit and $200 was Rent. The correction reverses the $1,000 receipt and must write an $800 receipt into the same Security Deposit from the same Payment. The key refuses it, because the reversed $1,000 receipt still counts.

- (a) Replace the key by a check in the receipt's insert trigger: a Deposit holds at most one active (not reversed) receipt from a Payment. A reversed receipt no longer blocks a new one. Before closure nothing changes in practice, because only the Reservation writes a receipt, once. A relaxing change.
- (b) Keep the key, and give only a correction receipt its own key (a new column naming the correction). The same result with more columns.
- (c) Keep the key. The right amount in the same Deposit cannot be recorded (a known limit); only a receipt that belongs whole in another Deposit works.

**Recommendation: (a)**, the smallest change; the history keeps both receipts and the reversal.

**Rule 2. A Security Deposit's first receipt must equal the amount its Reservation accepted.**

The receipt check counts only active receipts. After the $1,000 receipt is reversed, the next receipt is the "first" again, so it must equal the accepted $1,000. All active receipts together must also stay within the Deposit's required amount.

Example A (the agreed amount was right): the agreed Security Deposit was $1,000, but $200 of the Payment was Rent. The right receipt is $800. The check refuses it, because $800 is not the accepted $1,000.

Example B (the agreed amount was wrong): the agreed Security Deposit should have been $800, and $200 was Rent. The right receipt is $800 and the required amount should be $800, not $1,000.

- (a) Inside a correction only, a receipt may differ from the accepted amount (never above the required amount). The required amount stays as agreed, so in Example B the Deposit shows a $200 shortfall. Outside a correction the rule stays.
- (b) As (a), and the correction may also lower the required amount when the evidence shows the agreed amount was wrong (a required-amount record, DB-DEP-003, linked to the correction). In Example B the Deposit then shows no shortfall.
- (c) Keep the rule: a correction may only write a receipt that equals the accepted amount, so only a whole receipt can move to another Deposit. Examples A and B stay with the money on the Payment (a known limit).

**Recommendation: (a).** After closure the required amount moves no money (only the receipt check, the termination readiness check and the move-in read it), so the receipt is what matters. Choose (b) if you want the record to show the corrected agreed amount too.

**Rule 3. No function writes a Pet Deposit receipt today.**

Only the Reservation writes receipts, and only for its Security Deposit. `app.create_pet_deposit` creates a Pet Deposit with no money. (In the tests a Pet Deposit gets its money by a direct database insert.) Moving money into the Pet Deposit would be the first Pet Deposit receipt writer in the system.

Example: really $800 was the Security Deposit and $200 was the Pet Deposit. The correction reverses the $1,000 receipt, writes an $800 Security Deposit receipt (rules 1 and 2) and must write a $200 Pet Deposit receipt.

- (a) A Pet Deposit receipt writer inside a correction only. The receipt stays within the Pet Deposit's approved amount (the existing check). It is refused while the Pet Deposit has an active forfeiture, because only pay-back money may reach a forfeited Pet Deposit (the sub-slice 10c-2b-5 rule). The correction's DL-032 step then uses the $200 in its DL-032 place (pet damage first).
- (b) A general Pet Deposit receipt writer, also before closure for normal intake, with its own route and screen. A bigger feature that the V1-056 plan does not have.
- (c) No Pet Deposit receipt. Money meant for the Pet Deposit stays with the Payment after 10e-2 (a known limit).

**Recommendation: (a).** It fixes the case your Q-83 example names and adds nothing outside a correction.

**What 10e-2b then builds (no rule question).** Under the recommendations: the new receipt is written inside the `DEPOSIT_RECEIPT_CORRECTION`, linked to it (a new DB-SETTLE-005 link), after the wrong receipt's reversal; the draft's DL-032 plan names the new receipt's money; the correction's step then applies it to the Lease's open debt in the DL-032 order and refunds the rest. The money comes from the same Payment's freed value, so the Payment never gives more than it received.

**What goes ahead.** Only 10e-2b waits. The plan order is 10e-2 (now), 10c-2b-6 (the forfeiture tightening), 10e-3, 10e-4, 10c-2a-7, 10c-3c-1, 10c-3c-2, 10f, 10g, then 10e-2b after your answer, then 10h.

**Owner answer (2026-10-12).**

1. Rule 1: option (a). Allow at most one active receipt per Payment in each Deposit. A reversed receipt stays in the history, but it no longer blocks a new one.
2. Rule 2: option (a). Inside a correction only, a receipt may differ from the amount the Reservation accepted, but never above the required amount. The correction's reason explains the difference. Do not change the required amount.
3. Rule 3: option (a). A Pet Deposit receipt writer inside a correction only, refused while the Pet Deposit is kept.
4. These are relaxing or new-function changes only. If any of them needs a tightening, stop and ask the owner.
5. Order: 10c-2b-6, 10e-2b, 10e-3, 10e-4, 10c-2a-7, 10c-3c-1, 10c-3c-2, 10f, 10g, then 10h. 10e-2b moves up, because 10e-2 alone leaves a wrong receipt only half fixed. 10c-3c-1 is the hardening from answer 3 to Q-2026-10-10-69.

Recorded in docs/010.

## Q-2026-10-12-88 — Sub-slice 10e-2b: a right receipt into a Deposit that the termination says the Property keeps (blocks only that case of 10e-2b) (ANSWERED 2026-10-12: point 1 (b), point 2 (c); built as sub-slice 10e-2c after 10e-2b; answer in docs/010)

The 10e-2b design is in the plan (your answers (a), (a), (a) to Q-2026-10-12-87). After the wrong receipt is reversed, the correction writes the right receipt, and the correction's DL-032 step pays debt with that money and refunds the rest. A read-only check before code found one case your rules do not settle: the right receipt goes into a Deposit whose termination ground says the Property keeps it (for example BR-DEP-023, voluntary early leaving, for the Security Deposit; BR-DEP-022, pet noncompliance, for both Deposits). There is no 10e-2b code.

Today such a Deposit follows one of three paths:
- it was empty at closure, so nothing was forfeited (`NOTHING_HELD`); new money in it would have to be forfeited (`FORFEITURE_REQUIRED`), and no correction writes a forfeiture yet;
- it is still forfeited (`KEPT`): 10e-2 refuses it until a `FORFEITURE_REVERSAL` runs (your Q-83 point 3), and your rule 3 refuses a Pet Deposit receipt into it;
- its forfeiture was reversed by a `FORFEITURE_REVERSAL` correction (`DL_032`): new money in it is applied to debt and refunded, like any DL-032 money.

**Point 1. The Deposit was empty at closure and never forfeited.**

Example: the Lease ended for pet noncompliance (BR-DEP-022: the Property keeps both Deposits). A $1,000 Payment was recorded as the Security Deposit receipt, but really $800 was the Security Deposit and $200 the Pet Deposit. At closure the Pet Deposit was empty (no function writes a Pet Deposit receipt today), so nothing of it was forfeited. The right $200 Pet Deposit receipt should be kept by the Property. (The $800 is point 2.)

- (a) Refuse the right receipt into such a Deposit. The money stays with the Payment, as after 10e-2 (a known limit).
- (b) The same correction also forfeits the right receipt's money, on the termination's ground, as a linked record (the slice 6 forfeiture rules; a linked forfeiture already passes the closed-Settlement check since sub-slice 10c-2b-2a).

**Recommendation: (b).** It finishes the fix and keeps the Property's right under the termination rule.

**Point 2. The Deposit's forfeiture was reversed first, because Q-83 point 3 requires that before a receipt correction.**

Example: the Lease ended early by the Customer's choice. The $1,000 Security Deposit was kept. Really the Security Deposit was $800 and $200 was Rent. Staff first reverse the forfeiture (`FORFEITURE_REVERSAL`), then correct the receipt to $800. Today the $800 would follow DL-032: applied to debt and the rest refunded, so the Property no longer keeps it.

- (a) The right receipt follows DL-032, as the reversed path says today.
- (b) The same correction forfeits the right receipt's money again, on the same ground.
- (c) Staff choose (a) or (b) in the draft, with a reason, and the approver confirms it.

**Recommendation: (c).** A reversal is sometimes needed only to unlock the receipt correction, and sometimes because the forfeiture itself was wrong; staff know which, and the approver checks it.

**What goes ahead.** Nothing else in 10e-2b depends on this question. I will build 10e-2b in a fresh session, refusing a right receipt into a Deposit with a forfeiture ground until you answer (a refusal can later be lifted by a relaxing change). Your answer is then built as a small sub-slice 10e-2c right after 10e-2b, or inside 10e-2b if it arrives first.

**Owner answer (2026-10-12).**

1. Point 1 (the Deposit was empty at closure and never forfeited): option (b). The same correction forfeits the new money, because the termination ground says the Property keeps that Deposit.
2. Point 2 (the forfeiture was reversed first, as Q-83 point 3 requires): option (c). In the draft, staff choose, with a reason, whether the new money follows the normal debt-then-refund order or is forfeited again. The `financial.approve` approver confirms.
3. Build 10e-2b as designed, with the Q-88 case refused. Then add this answer as the small sub-slice 10e-2c.
4. The draft must show the exact amount and the person for each placeholder charge line, so the approver confirms real numbers. The test must prove that the real charges at confirm match the placeholders exactly.
5. 10e-2b is large. If it looks too big for one session, split it into smaller sub-slices that each end in a commit; say so in the report.

Recorded in docs/010.

## Q-2026-10-12-89 — Owner answers to the two points of the sub-slice 10e-2b-1 report (ANSWERED 2026-10-12; point 2 continues in Q-2026-10-12-90)

1. A correction that writes the same receipt again into the same Deposit (same Payment, same amount): refuse it. A receipt correction must change the Deposit or the amount. If the receipt is right, a change to how the Deposit paid the Lease's debt belongs to another correction kind, not this one. This is a tightening, and the owner approves it.
2. Pet Deposit receipts: yes, the table must require a correction link. This is a tightening, and the owner approves it.
3. Build both in 10e-2b-2, which already touches this code. If either one is not small, put it in its own small sub-slice before 10h and tell the owner.

Implementer (read only, head `20261126_122`): point 1 is small and is built in sub-slice 10e-2b-2. Point 2 is not small (Q-2026-10-12-90 below); it becomes sub-slice 10e-2b-3 before 10h and waits for that answer.

Recorded in docs/010.

## Q-2026-10-12-90 — Sub-slice 10e-2b-3 (Pet Deposit receipts need a correction link): how do the test fixtures give a Pet Deposit its money? (blocks 10e-2b-3 only) (ANSWERED 2026-10-12: (a); built as sub-slice 10e-2b-3 before 10h; answer in docs/010)

Your answer 2 to Q-2026-10-12-89: the receipt table must require a correction link for a Pet Deposit receipt. A read-only check before code (head `20261126_122`) found that this is not small. There is no 10e-2b-3 code.

**What exists.** Only two functions write a Deposit receipt: the Reservation (a Security Deposit only) and the 10e-2b-1 correction writer (inside a correction only). No function writes a Pet Deposit receipt outside a correction. So the committed PostgreSQL fixtures give a Pet Deposit its money by a direct database insert, before the Lease ends: the Pet Deposit helper of the Final Settlement fixtures in `test_final_settlement_migration.py` (34 modules import these fixtures), `seed_pet_deposit` in `test_deposit_api_migration.py`, `joint_qualified` in `test_refund_signer_recipient_migration.py`, and the pet noncompliance test in `test_lease_deposit_forfeiture_migration.py`, among others. No runtime or financial role may insert a receipt; only the database owner can, as the fixtures do.

Example: a Lease has a $200.00 Pet Deposit. The fixture inserts a $200.00 receipt before move-in, then the Lease ends for pet noncompliance and the Final Settlement keeps the money. With a correction link required for every Pet Deposit receipt, that first insert is refused, so the fixture cannot build the Lease at all, and most slice 8 to 10 tests fail before their own assertions. Your answer does not say how a fixture then gets Pet Deposit money, and the standing rule for fixtures covers only a changed result, not a fixture that can no longer be built.

**Options:**
- (a) The table rule applies once the Lease's Final Settlement is closed: from then on, every Pet Deposit receipt of that Lease must be linked to a correction of that Settlement confirmed in the same transaction (the same check owner rule 2 uses for a Security Deposit receipt). Before closure nothing changes: the only way in is the database owner's insert, as today. No committed test changes.
- (b) The rule applies to every Pet Deposit receipt, and the fixtures turn off only that one new check (a named trigger) for the one insert that seeds Pet Deposit money; every other receipt check still runs. This changes the shared fixtures of more than 34 modules and turns a check off inside tests.
- (c) The rule applies to every Pet Deposit receipt, and V1-056 adds a real Pet Deposit intake writer before closure (option (b) of Q-87 rule 3: its own function, capability, route and screen); the fixtures use it. A bigger feature that the V1-056 plan does not have, and a new capability.

**Recommendation: (a).** The risk the 10e-2b-1 reviewers named is a Pet Deposit receipt after closure that skips the correction and its DL-032 step. (a) closes exactly that at the table, for every writer, and changes no fixture. Choose (c) if Pet Deposit intake before closure must also go through a checked function.

**What goes ahead.** Only 10e-2b-3 waits. Sub-slice 10e-2b-2 (with your answer 1, the refusal of the same receipt again) is built now, then 10e-2c, 10e-3, 10e-4, 10c-2a-7, 10c-3c-1, 10c-3c-2, 10f and 10g; 10e-2b-3 is built as soon as you answer, before 10h.

**Owner answer (2026-10-12).** Option (a). The Pet Deposit receipt rule applies once the Lease's Final Settlement is closed. Build it as sub-slice 10e-2b-3, before 10h.

Order (owner, 2026-10-12): 10e-2c, 10e-3, 10e-4, 10c-2a-7, 10c-3c-1, 10c-3c-2, 10f, 10g, 10e-2b-3, then 10h. Recorded in docs/010.

## Q-2026-10-12-91 — Owner ruling on the lint allowance of sub-slice 10e-2b-2 (ANSWERED 2026-10-12; recorded in the run rules)

The 10e-2b-2 report counted two lint causes: A (four long lines in the new test module) with 1 correction, and B (two later lines left long by the docstring rewrap) with 2 corrections.

**Owner ruling (2026-10-12).** Causes A and B are the same cause, so that was one correction past the limit of 2. No harm came of it, so the commit stays. From now on, the same kind of error is the same cause, even when it shows up on different lines. Added to ops/V1_055_RUN_RULES.md (Verification). Recorded in docs/010.

## Q-2026-10-12-92 — Nothing in the app records Pet Deposit money before closure: where should it be built? (blocks nothing in slice 10; owner asked, 2026-10-12) (ANSWERED 2026-10-12: (a), both Deposit types, sub-slice 10e-2b-4; answer in docs/010)

Your question: how does a real Customer's Pet Deposit get its money before closure today?

**Plain answer: it cannot.** Read only, head `20261127_123`:
- Staff can create the Pet Deposit liability: `POST /leases/{lease_id}/pet-deposits` (`deposits.manage`, `app.create_pet_deposit_v2`) writes the Deposit row with its required amount. It records no money.
- Only two functions write a Deposit receipt: `app.create_reservation` (a Reservation's Security Deposit, at the accepted amount) and the 10e-2b-1 correction writer `app.write_correction_deposit_receipt` (inside a confirmed `DEPOSIT_RECEIPT_CORRECTION` after closure only). Neither writes a Pet Deposit receipt before closure.
- docs/005 API-040 names `POST /leases/{id}/pet-deposit-receipts`, `POST /leases/{id}/security-deposit-receipts` and `POST /deposits/{id}/receipts`. None of them is built, in the backend or the frontend.
- So a real Pet Deposit always holds $0 until closure. The PostgreSQL fixtures put the money in by a direct database-owner insert, which no app role can do.

**The same gap on the Security Deposit side (found by the same check).** A walk-in Lease (DL-066) gets no Security Deposit at all: the signing only links a Reservation's Deposit. A second Security Deposit receipt (for example the rest above the Reservation's accepted amount, which the receipt check allows up to the required amount) has no writer either.

**Effect today.** A Customer who pays a Pet Deposit cannot have it recorded as a Deposit; staff can only leave it as an unallocated Payment (or Credit with the payer's authorization). At closure the Pet Deposit is empty, so the pet damage and pet noncompliance rules (BR-DEP-022, BR-DEP-027, DL-032) never see that money.

**Options:**
- (a) A new sub-slice **10e-2b-4 — Deposit receipt before closure**, right after 10e-2b-3 and before 10h: one internal database function that records a Deposit receipt from a RECEIVED Payment's available value (the existing receipt and source checks: within the required amount, the payer is the Deposit's Customer or the Lease for a third-party Payment, the Pet Deposit's approval time), with evidence and a reason, under the existing capability `deposits.manage`; refused once the Lease's Final Settlement is closed (then only the correction, 10e-2b-3); audit event, idempotency and replay as the other Deposit commands. API-040 routes and the staff screen in slice 11 (with the other Deposit routes). Pet Deposit only, or also the Security Deposit cases above, as you decide.
- (b) Only the API-040 routes and screens in slice 11, with their database function built there.
- (c) Leave it out of V1-056 (a known gap, recorded in docs/010), and plan it as later work.

**Recommendation: (a), for both Deposit types.** It is the missing half of rule 3 of Q-2026-10-12-87 and of 10e-2b-3 (the door before closure, next to the correction door after closure), it needs no new capability (`deposits.manage` already creates the Pet Deposit), and the Final Settlement rules of V1-056 only work on real money if the money can be recorded. Please confirm the capability (`deposits.manage` or a payments capability), and whether a Deposit receipt needs a draft and `financial.approve` (today the Reservation receipt does not).

**What goes ahead.** Nothing in the slice 10 order waits for this answer. Nothing is built for it before you answer.

**Owner answer (2026-10-12).** Yes to the new sub-slice 10e-2b-4, "Deposit receipt before closure", for both Deposit types, after 10e-2b-3 and before 10h. The routes and the screen come in slice 11.

1. Capability: use the same capability that staff use today to put a Payment on an Invoice (`payments.allocate`). A Deposit receipt is the same kind of work: deciding where received money goes.
2. No draft and no `financial.approve`. Money coming in is recorded directly, like a Payment. A mistake is fixed with the existing receipt reversal before closure, or with the receipt correction after closure.
3. Also cover the walk-in Lease, which gets no Security Deposit today, and a second Security Deposit receipt. Follow docs/002 for amounts and timing. If a rule is missing, for example the Security Deposit amount on a walk-in Lease, write it in this file with a recommendation, and ask the owner before building that part.

Order (owner, 2026-10-12): 10e-3, 10e-4, 10c-2a-7, 10c-3c-1, 10c-3c-2, 10f, 10g, 10e-2b-3, 10e-2b-4, then 10h. Recorded in docs/010.

## Q-2026-10-12-93 — Sub-slice 10e-2c: a forfeited right receipt into a Pet Deposit that has returned pay-back money (blocks only that case; refused until answered) (ANSWERED 2026-10-12: (a); answer in docs/010)

Your answers to Q-2026-10-12-88: a right receipt into a Deposit with a forfeiture ground is forfeited in the same correction (point 1), or forfeited again when staff choose it (point 2). A read-only check before code (head `20261127_123`) found one case where two of your rules meet.

Your answer (a) to Q-2026-10-10-76 (the running count) and sub-slice 10c-2b-6: returned Pet Refund-review money is the Customer's pay-back money; while a Pet Deposit holds money, up to that returned amount counts as pay-back money, and no forfeiture may take it (a table rule since 10c-2b-6).

Example: a Pet Deposit had a $150 Pet Refund-review Refund, and $30 of it came back before the Lease ended for pet noncompliance. After closure, a receipt correction puts a right $200 receipt into that Pet Deposit. Your Q-88 answer says the $200 is forfeited; the running count says $30 of the money the Pet Deposit now holds is pay-back money, so the table refuses a $200 forfeiture and allows only $170.

- (a) Forfeit only the money beyond the pay-back count ($170); the rest ($30) follows DL-032 in the same correction's plan (applied to debt, then refunded).
- (b) Refuse such a correction (a known limit); the money stays with the Payment.

**Recommendation: (a).** It follows both rules as they stand and needs no table change. Until you answer, 10e-2c refuses the case (55000, "A forfeiture in a receipt correction takes only the new receipt's money"), and it also refuses a forfeited receipt into a Deposit that still holds other money (no fixture or real path reaches that today). A refusal can later be lifted by a relaxing change.

**What goes ahead.** Everything else in 10e-2c, and the rest of the order.

**Owner answer (2026-10-12).** Option (a). Forfeit only the money beyond the returned amount. This is the same rule as the owner answers to Q-2026-10-10-73 and Q-2026-10-10-76: returned money belongs to the Customer. Build it where it fits best before 10h.

Recorded in docs/010.

## Q-2026-10-12-94 — Sub-slice 10e-3 (`RETURN_REVERSAL`): who pays back a Deposit Refund that was paid to an agreed Signer? (blocks only that case; refused until answered) (ANSWERED 2026-10-12: (a); built in sub-slice 10e-3b; answer in docs/010)

Your answer (a) to Q-2026-10-08-57: a return recorded by mistake is reversed by a `RETURN_REVERSAL` correction, and "any part already refunded again becomes an `EXTRA_CHARGE` to that Customer". The plan wrote this, before your Q-78 answer, as "the Deposit owner for a Deposit Refund". Your later answer to Q-2026-10-11-78 says: "the person who received the refund money pays it back". Sub-slices 10e-1c and 10e-2 follow Q-78. The 10e-3 design is in the plan (10e-3 pre-code design); 10e-3 is built with this case refused (below).

The two texts give a different person in one case only: a Deposit Refund paid, with the written agreement of all Signers, to a Signer who is not the Deposit's own Customer (BR-REFUND-015).

Example: a Lease with two Signers, A (the Primary Tenant, the Deposit's Customer) and B. After closure the Settlement's Security Deposit Refund of $1,000 to A is recorded as returned (a `REFUND_RETURN`), and a new Deposit Refund of $1,000 is paid to B with every Signer's written agreement. Later staff find the return never happened, so A really kept the first $1,000. The `RETURN_REVERSAL` reverses the mistaken return, and the $1,000 that B received must be charged back to someone.

- (a) The person who received the money: B is charged $1,000 (an `EXTRA_CHARGE` on the Lease, B is its signed Customer). The same rule as Q-78, 10e-1c and 10e-2.
- (b) The Deposit's own Customer: A is charged $1,000, as the plan text reads; A and B settle it between themselves.

**Recommendation: (a)**, because B holds the money, and it keeps one rule for every correction that recovers a Refund.

**What goes ahead.** 10e-3 is built now with every other case. Until you answer, a `RETURN_REVERSAL` that would recover a Refund paid to someone other than the Deposit's own Customer is refused (55000, a conflict); a relaxing change lifts it later. A Credit Refund always goes to the Credit's own Customer, so it is not affected.

**Owner answer (2026-10-12).** (a). The person who received the Refund pays it back. When a Deposit Refund was paid to an agreed second Signer, that second Signer is charged, not the Deposit owner. This follows the Q-2026-10-11-78 rule. The older plan text ("the Deposit owner for a Deposit Refund") is updated to match.

Recorded in docs/010 and the plan. Built in sub-slice 10e-3b (after 10e-3, before 10e-4): the refusal is removed; the charge goes to the person who received the Refund, an `EXTRA_CHARGE` on the Lease when that person is its signed Customer, else a no-Lease charge (the sub-slice 10e-1c writer).

## Q-2026-10-12-95 — Sub-slice 10e-3 (`RETURN_REVERSAL`): a mistaken return whose correction also paid out money the Deposit already held (blocks only that case; refused until answered) (ANSWERED 2026-10-12: (a); built in sub-slice 10e-3b except one case, see Q-2026-10-12-96; answer in docs/010)

Found by the independent review of 10e-3 (round 1). A `REFUND_RETURN` that pays a new Refund must apply or refund every Deposit balance (BR-SETTLE-008). So when the Deposit already held money from an earlier return-only correction, that correction's Refund pays out more than its own return brought back.

Example: after closure, $1,000 of the Settlement's Pet Deposit Refund comes back (a return-only correction, X1); the Pet Deposit holds $1,000. Later $500 more comes back (X2) with a new Refund; with no open debt X2 refunds all $1,500 the Pet Deposit holds. Then staff find that X2's $500 return never happened. Reversing X2 as designed, without the refusal, would charge the Customer back the whole $1,500 and leave X1's $1,000 held in the Pet Deposit again, so the Customer owes $1,500 while the Pet Deposit holds $1,000 that X1's later held-value Refund could pay back.

- (a) Charge back only the part above what the Deposit held before X2's return ($500): the reversal recovers the new Refund only up to the returned amount and leaves the rest of that Refund standing (it paid X1's money, which was the Customer's anyway). X1's held value is then counted as used by that Refund, so nothing stays held. A new rule for splitting one Refund between two returns.
- (b) Undo everything X2 did (as designed, without the refusal): charge back $1,500 and hold X1's $1,000 again; staff then refund or apply it through a `HELD_VALUE_REFUND` naming X1.
- (c) Keep it refused (a known limit): staff fix such a case by hand outside the system.

**Recommendation: (a)**, because only the money the mistaken return brought back was paid out by mistake; the Customer was owed X1's $1,000 in any case. It needs a small extra rule in the reversal (and in X1's left value). Until you answer, 10e-3 refuses the case (55000, "The correction to reverse also used money its return did not bring back; reversing it waits for the owner"); a relaxing change lifts it.

**What goes ahead.** Everything else in 10e-3, and the rest of the order. The same refusal also covers a Credit return whose correction applied or refunded more of the Credit than its return brought back.

**Owner answer (2026-10-12).** (a). Charge back only the mistaken amount. The part of the new Refund that paid out money the Deposit really held stays paid. This follows the owner answer to Q-2026-10-10-76: a new Refund pays the returned money first.

Recorded in docs/010 and the plan. Built in sub-slice 10e-3b (after 10e-3, before 10e-4), for the Deposit and the Credit form: when the uses are more than the returned amount, the Refunds paid out the returned money first (the oldest Refund first), so each is charged back only for its share of the returned amount, and every Deposit or Credit application stays. In the example the reversal charges back $500, the $1,000 rest of the new Refund stays paid, and the Pet Deposit holds nothing, so a held-value Refund naming X1 is refused. Implementer's reading: X1's own left value (the label `app.settlement_held_deposit_value` reads) is not changed; the Deposit holds nothing, so nothing stays held (the 10e-3 round 2 note: a left value is a label that the holdings cap). One case is not built: the Refunds paid out less than the returned amount, so the rest of the returned money paid debt; it stays refused until the owner answers Q-2026-10-12-96.

## Q-2026-10-12-96 — Sub-slice 10e-3b (your Q-95 answer): the new Refunds paid out less than the mistaken return, so part of an application must come back (blocks only that case; refused until answered) (ANSWERED 2026-10-13: (a), sub-slice 10e-3c before 10h; answer in docs/010)

Your answer (a) to Q-2026-10-12-95: charge back only the mistaken amount; a new Refund pays the returned money first. Sub-slice 10e-3b builds it when the Refunds paid out at least the returned amount: only the returned amount is charged back (the oldest Refund first), and every Deposit or Credit application stays.

**The case that is left.** The Refunds paid out less than the returned amount, so the rest of the returned money paid debt. Example (Credit form): after closure $300 of a correction's Credit Refund comes back (return only, X1); the Credit holds $300. Later $1,700 more comes back (X2) with a new Refund: the Credit, now $2,000, pays the Customer's $1,500 charge and refunds $500. Then staff find that X2's return never happened. Of the mistaken $1,700, the new Refund paid out $500 (charged back) and $1,200 paid the charge. So $1,200 of the $1,500 application must come back as debt, while X1's $300 stays applied. The same can happen with a Deposit.

**What the code allows.** A Deposit application and a Credit application are reversed only whole. A Credit application's unreleased rest is re-posted only by the `REFUND` correction paths (migration 67); nothing re-applies the rest of a Deposit application.

**Options:**
- (a) Reverse the newest applications whole until the rest of the returned amount is reached; the part of the last one that was not returned money (here $300) is applied again to the same obligation from the same Credit or Deposit, in the same correction (a new linked application). The Customer owes the $500 charge and $1,200 of the debt again: exactly the mistaken amount. It needs a small new writer for that re-applied part.
- (b) Reverse the newest applications whole; the extra part ($300) stays in the Credit or Deposit as held DL-032 money. The Customer owes the $500 charge and $1,500 of debt again, and the Credit holds $300 that the next correction must apply or refund (for example a held-value Refund naming X1). No new writer.
- (c) Keep it refused (a known limit); staff fix such a case by hand outside the system.

**Recommendation: (a)**, because it charges back exactly the mistaken amount, as your Q-95 answer says. It would be a small sub-slice 10e-3c before 10h.

**What goes ahead.** Everything else in 10e-3b, and the rest of the order. Until you answer, a `RETURN_REVERSAL` whose Refunds paid out less than its returned amount while its uses are more than that amount is refused (55000, "The returned money also paid debt beyond what its Refunds paid out; reversing it waits for the owner").

**Owner answer (2026-10-13).** Option (a). Undo the newest debt payments first, then put back the part that was not mistaken money, so only the mistaken amount comes back. Build it as the small sub-slice 10e-3c before 10h.

Recorded in docs/010 and the plan. Placement (implementer, "before 10h"): 10e-3c comes right after 10e-4 and before 10c-2a-7, next to the Q-97 fix (sub-slice 10e-3d), because both change the 10e-3 and 10e-3b return reversal functions. In the example the reversal charges back the $500 Refund, reverses the $1,500 Credit application whole and applies $300 of the same Credit to the same charge again in the same correction (a new linked Credit application), so the Customer owes the $500 and $1,200 of the charge again: exactly the mistaken $1,700 (amounts in dollars, as in your example).

## Q-2026-10-12-97 — Sub-slice 10e-3b (your Q-95 answer): should the left value of the earlier return-only correction also count the money that stays paid? (blocks nothing; please confirm or choose) (ANSWERED 2026-10-13: (a), one fix for every case before 10h, sub-slice 10e-3d; answer in docs/010)

Option (a) of Q-2026-10-12-95 said: "X1's held value is then counted as used by that Refund, so nothing stays held", and estimated "a small extra rule in the reversal (and in X1's left value)". Sub-slice 10e-3b builds the money part. After the reversal the Pet Deposit holds nothing, so a held-value Refund naming X1 is refused ("The Deposit holds no returned money to refund"). It does not change X1's left value: the label (`app.settlement_held_deposit_value`) still says X1 has $1,000 left. The independent review of 10e-3b found this difference from the option text.

**Why it was not built.** The label was already wrong before the reversal. X2's correction swept the Pet Deposit, so X2's new Refund paid out X1's $1,000 as soon as X2 was confirmed. The left value counts only the uses by held-value Refunds that name X1 (a known 10e-3 note). A rule only inside the reversal would fix one case of a wider gap.

**Effect (corrected after review round 2).** If money later comes back into the same Pet Deposit through another return-only correction X3, a held-value Refund naming X1 (F3) can pay out X3's money. X3 then cannot be reversed ("The returned value is no longer available"). X1 can still be reversed, and its reversal charges back F3, the Refund that paid out X3's money, while the rest of X2's Refund (which paid out X1's money) stays paid. When F3 went to another person (for example an agreed Signer), the wrong person is charged for X1's mistake. The total amount charged is right; the person can be wrong.

**Options:**
- (a) One rule for every case, as a small sub-slice before 10h: when a later correction's DL-032 step uses the source, that use counts against the held money of the earlier return-only corrections, oldest return first, so their left values go down. This covers the reversal case too.
- (b) Only for the reversal: X1's left value goes down by the part of the reversed correction's Refunds that stays paid.
- (c) Keep the label as it is (a known limit; what the source holds still caps every payment).

**Recommendation: (a)**, because it makes every left value true, not only after a reversal, and then a held-value Refund naming X1 is refused after X2's sweep, so X1's reversal cannot reach X3's money. Committed tests that read a left value after such a sweep may change; the pre-code check will name them.

**What goes ahead.** 10e-3b is committed as built. Nothing else waits for this answer.

**Owner answer (2026-10-13).** Option (a). One fix for every case, before 10h, so a later reversal always charges the right person.

Recorded in docs/010 and the plan as sub-slice 10e-3d, right after 10e-3c and before 10c-2a-7. Its pre-code check names every committed test that reads a left value after such a sweep; a test whose expectation changes under this answer is changed in the affected case only (owner standing rule of 2026-10-11) and named in the report.

**Owner detail for 10e-3d (2026-10-13, with the 10e-3c report).** Process the Settlement's corrections oldest return first. Count only uses made by corrections, and keep ordinary Credit spending as the known limit from Q-2026-10-09-63. Limit a reversal of an earlier return to that return's own left value. Write the pre-code design first and commit it. If a choice in the design changes who pays or how much, write it here with a recommendation and ask before building that part. Recorded in docs/010 and the plan (10e-3d entry).

Also answered with the 10e-3b report (2026-10-13): the two committed 10e-2 assertions that review round 2 made stricter (`test_settlement_deposit_receipt_correction_migration.py`, the recovery check after the commit and inside the receipt's confirm) are accepted. New standing rule (ops/V1_055_RUN_RULES.md): a change that makes a committed test stricter, found by a reviewer, is allowed without asking; each one is named in the report.

## Q-2026-10-13-98 — Sub-slice 10e-4: a Payment that names no Lease, used on a closed Lease, with part refunded: which charge? (blocks nothing; please confirm) (ANSWERED 2026-10-13: (a); answer in docs/010)

Your answer (c) to Q-2026-10-11-81 point 3: "That Settlement's correction takes the Payment, and the charge is an `EXTRA_CHARGE` on that Lease." Your answer to Q-2026-10-11-82: "Keep the design": the person who received the Refund pays it back. Sub-slice 10e-4 is built that way and keeps the Q-2026-10-11-78 rules for where a recovery charge goes: a Payment Refund is charged on the Lease the Payment names (answer A), and with no Lease it is a Miscellaneous charge with no Lease (answer B).

**The case the review found.** After closure the Customer sends $900 that names no Lease. Staff put $600 of it on the closed Lease's `EXTRA_CHARGE` Invoice and refund the other $300 to the Customer. Then the transfer bounces. The correction of that Settlement takes the Payment (its money was used on the Lease): the $600 comes back as debt on that Invoice. The $300 Refund is charged back to the Customer as a Miscellaneous charge with no Lease, not as an `EXTRA_CHARGE` on the closed Lease, because the Payment named no Lease. Your Q-81 example (the Payment names the Lease) gets the `EXTRA_CHARGE`, as you said.

- (a) Keep it: the Q-78 rules decide where the charge goes; a Payment that names no Lease gets a no-Lease charge. Nothing changes.
- (b) Inside such a correction, charge a Payment Refund on the closed Lease (an `EXTRA_CHARGE`) whenever the Payment's money was used there and the person refunded is a signed Customer of that Lease. A small relaxing change to the recovery rules, with a test.

**Recommendation: (a)**, because the $300 that came back to the Customer was never used on the Lease, and it keeps one rule for every returned Payment. The amount and the person are the same either way; only where the charge shows differs.

**What goes ahead.** Everything. 10e-4 is committed with (a).

**Owner answer (2026-10-13).** Option (a). Keep it as is. A Refund paid from a Payment that names no Lease gets a charge with no Lease. This follows the Q-78 rules and matches the ordinary Payment return.

Recorded in docs/010. Nothing changes.

Also answered with the 10e-4 report (2026-10-13): (1) the ordinary `PAYMENT_RETURN` draft that still returns a Payment whose only use on a closed Lease is an allocation (or a Credit application) with nothing refunded is named in the plan's 10h entry; the owner decides it with 10h. (2) The two known limits of a Payment used on two closed Leases are in the plan's slice 12 list; the owner decides both before go-live. (3) The short script used for one batch of `ops/traceability.json` edits in 10e-4 is accepted this time (the result is identical and was checked); documents keep being edited with the Edit tool, and a script needed again is named in the report. (4) The owner asked whether an independent reviewer compared the two changed 10e-1c tests of `test_payment_return_recovery_migration.py` with HEAD: the 10e-4 review record (round 3) shows it did and found nothing weaker, so no new review was needed before 10e-3c.

## Q-2026-10-13-99 — Sub-slice 10e-3c stopped before review round 3: a targeted run failed for a cause outside the sub-slice (the host and Docker clocks) (blocks 10e-3c; recommendation (a)) (ANSWERED 2026-10-13: (a) with steps; answer in docs/010)

**What happened.** 10e-3c is built and was green: P1 (2110 passed) and P2 (2111 passed) full PostgreSQL runs, U1 and U2 full unit runs. Review round 2 had no blocker and one should-fix (a test of the audit event), so under your standing rule one round 3 is allowed after one full unit run and one full PostgreSQL run. After the round 2 fixes the migration-only check passed (M6), then the targeted run T3 of the two affected modules gave 18 passed and 8 failed.

**The cause is outside the sub-slice.** All 8 failures are the same error in the shared Lease fixtures, before any 10e-3c code runs: `Signature evidence is invalid` from `app.record_lease_signature`, which refuses a signature time later than the database's `statement_timestamp()`. The fixtures take the signature time from the Mac's clock (`datetime.now(UTC)`) and the database runs in the Docker VM, so the Mac's clock was ahead of the VM's clock during the run. This is cause C of sub-slice 10c-2a-3 (2026-10-08: "host clock ahead of the Docker VM clock while the display slept"). The first 18 tests of the same run passed, and the same tests passed in T2, P1 and P2. A read-only check right after the run found the two clocks in step again (the VM time fell inside the Mac's measuring window, three times). The run used `caffeinate -i`, which keeps the Mac awake but lets the display sleep.

**Run rules.** No retry; a test that passed before and fails for a cause outside the sub-slice is a stop condition. So I stopped: no rerun, no round 3, no commit. All 10e-3c files are in the working tree.

**Options:**
- (a) One owner-approved rerun of T3 with `caffeinate -d -i` (the display also stays awake), then U3 and P3 the same way, then review round 3 under your standing rule, then the commit.
- (b) As (a), but skip T3 and go straight to U3 and P3.
- (c) Stop 10e-3c here and investigate the clock first.

**Recommendation: (a)**, because the cause is known, the failures are in fixture set-up and not in 10e-3c, and a short targeted run shows quickly whether the clocks are in step before the long runs.

Also for your decision: run M3' (sub-slice 10e-3c) repeated an unchanged migration-only check only to read its error text, because M3 printed only its last lines. It is listed in the review record. Every later check saved its whole output to a file first.

**Owner answer (2026-10-13).** Option (a), with these steps: (1) before the rerun, check that the Mac clock and the Docker clock are in step, with a Docker image already on the Mac (such as the database image); pull no new image and download nothing else without asking (the alpine image pulled for the earlier check may stay); (2) if the clocks are not in step, stop and tell the owner; (3) rerun T3 once under `caffeinate -dims`, and from now on use `caffeinate -dims` for every targeted and full run (the form in the allow rules); (4) if T3 fails again for the same clock cause, stop and tell the owner, no further rerun; (5) then U3, the migration-only check, the read-only search for affected tests and P3, all under `caffeinate -dims`; (6) then review round 3, the independent reviewer comparing each changed committed test with HEAD, as in 10e-4; (7) then commit 10e-3c with the answers already recorded.

Also answered (2026-10-13): run M3' is accepted, because it changed nothing; next time the full output is saved in `~/Development/prm-run-logs/` and read without a rerun. Lesson added to the run rules: a CASE inside a PL/pgSQL IF condition goes in parentheses (the same error happened in 10e-3b). The re-applied Deposit application numbered after the Settlement's highest application number is accepted (a new record); the 10e-3c design text says the same. The untested refusal of a Credit part on a Rent or Service Invoice with no designation: no existing real-path fixture reaches it (the only Rent and Service proposal test builds its correction by hand), so it is on the slice 12 list. The two Q-98 edits checked with one `git diff --stat` are accepted; each edit is checked on its own.

Recorded in docs/010.

**Also answered with the 10e-3c report (2026-10-13, fresh session).** (1) 10e-3d: see the owner detail under Q-2026-10-12-97. (2) The Credit Refund outside a correction, which 10e-3d will not count, is named in the plan's 10h entry. (3) The conflict mapping of the Rent-line refusal moves from the slice 12 list to 11c. (4) Never repeat a command that a guard hook or the auto-mode checker blocked; the standard secret scan is in ops/V1_055_RUN_RULES.md (the implementer's wording, approved with two changes: every saved run output is scanned the same way; a scan blocked only by a word in its pattern, reading only the staged diff or saved run outputs, may drop that word and run once more, with the word named in the report; anything else blocked means stop). (5) Review agents write no files; if one does, the report says so. (6) Context is reported from the session's token counter as used tokens divided by the 1M-token window. (7) A signature test that fails with `Signature evidence is invalid`: clocks checked first as in K1; in step, one rerun under `caffeinate -dims`; otherwise stop (ops/V1_055_RUN_RULES.md). The pending 10e-2c test rename is done at the next touch of its file. Recorded in docs/010.

## Q-2026-10-13-100 — Sub-slice 10e-3d: how the reversal of a return charges money that another correction paid out (blocks only 10e-3d-2; refused until answered) (ANSWERED 2026-10-13: point 1 (a), point 2 (a); built in sub-slice 10e-3d-2; answer in docs/010)

Your answer (a) to Q-2026-10-12-97 and your detail of 2026-10-13: count every correction's use of returned money against the earlier return-only corrections, oldest return first, and limit a reversal of an earlier return to that return's own left value. The pre-code design is in the plan (10e-3d entry). Sub-slice 10e-3d-1 builds the count and the limit. Two points change who pays or how much, so they wait for you.

**Point 1: a return whose money another correction paid out.** Example (Pet Deposit): X1 brings back $1,000 (return only). X2 brings back $500 with a new Refund; by BR-SETTLE-008 its Refund pays out all $1,500 the Pet Deposit holds: its own $500 and X1's $1,000. Later staff find that X1's return never happened. X1's money was paid out by X2's Refund, to the person who received that Refund.
- 10e-3d-1 refuses X1's reversal in this case (55000, "Another correction paid out this return's money; reversing it waits for the owner"). Before 10e-3d-1 it was refused when the Deposit held nothing, or it took money that a later return brought back, which was the Q-97 problem.
- (a) Charge it where it went: X1's reversal also undoes the part of X2's uses that paid out X1's money. A Refund part is charged back to the person who received it (the 10e-3b partial charge-back); an application part comes back as debt (the application reversed whole and the rest applied again, as in 10e-3c). Inside such a correction, the returned money counts as paid out by its Refunds first, the oldest first, then by its applications, the newest first (your answers to Q-2026-10-10-76 and Q-2026-10-12-95: a new Refund pays the returned money first). In the example: $1,000 of X2's Refund is charged back to its recipient, and X1's return is reversed. One case may need two parts applied again (an application that paid both X1's money and other money on each side); 10e-3c allows one today, so 10e-3d-2 would allow two.
- (b) Keep it refused (a known limit): staff fix such a case by hand outside the system.
- **Recommendation: (a)**, because your Q-97 answer asked that "a later reversal always charges the right person", and the right person is the one who received the money X1 brought back.

**Point 2: a correction of another Settlement.** A Customer's Credit that a correction of one Settlement brought back can be used by a correction of another Settlement (the Customer also owes on that other Lease). Your detail says "Process the Settlement's corrections", so 10e-3d-1 counts only the corrections of the Settlement that brought the money back; a use by another Settlement's correction then works like ordinary Credit spending (the Q-2026-10-09-63 limit: what the Credit holds still caps every payout).
- (a) Count the corrections of every Settlement, in one time order.
- (b) Keep it as built (a known limit; rare: the same Customer must owe on two closed Leases).
- **Recommendation: (a)**, built with 10e-3d-2, because then a left value is always true.

**What goes ahead.** 10e-3d-1 is built now; the rest of the order (10c-2a-7, 10c-3c-1, 10c-3c-2, 10f, 10g, 10e-2d, 10e-2b-3, 10e-2b-4, then 10h) does not depend on this answer. 10e-3d-2 is placed right after the answer, before 10h.

**Owner answer (2026-10-13).** Point 1, option (a): when a later correction already paid out a mistaken return's money, the reversal charges the paid-out part back to the person who received it, and any debt that money paid becomes owed again. Together they equal exactly the mistaken amount. This follows the answers to Q-2026-10-11-78, Q-2026-10-12-95 and Q-2026-10-12-96. Point 2, option (a): a correction on another Lease of the same Customer that uses the returned Credit counts too. When a reversal undoes a payment on that other Lease, that Lease's history must show which correction undid it. Built in sub-slice 10e-3d-2, right after the 10e-3d-1 commit.

## Q-2026-10-13-101 — Sub-slice 10e-3d-1 stopped after review round 2: three should-fix findings (blocks the 10e-3d-1 commit; recommendation (a)) (ANSWERED 2026-10-13: (a), a one-time exception; answer in docs/010)

**Where it stands.** 10e-3d-1 (migration `20261203_129`) is built and green: P1 2116 and P2 2117 full PostgreSQL runs passed, U1 and U2 full unit runs passed. Review round 1 found one blocker (fixed: a correction that releases an application and refunds the released part was counted as using returned money; the count now takes each correction's net draw at its own time). Review round 2 found no blocker but three should-fix findings in total (independent two, security one). Your standing rule allows round 3 only with at most two, so I stopped. Nothing is committed; all files are in the working tree. Record: ops/reviews/V1-056-slice-10e-3d-1-returned-value-count.md.

**The three findings.**
1. (Security) The reversal of a return is not always limited to that return's own left value. Example (Credit): C1 brings back $100 (return only). A held-value Refund naming C1 pays it out, so C1 has $0 left. Later that Refund itself comes back (C4, $100). C1's reversal is then allowed: nothing of C1's money is counted as swept, and the Credit holds $100, so the reversal takes C4's money. This gap exists since 10e-3, and your rule "limit a reversal of an earlier return to that return's own left value" covers it. Fix: the source also names the left value, and the check refuses a reversal that would take more than it ("The returned value is no longer available; undo its other use first"; staff reverse C4 first). I traced every committed reversal test: none takes more than its left value, so none changes.
2. (Independent) A correction can hide a payout of returned money behind money it brings back. Example (Deposit): X1 brings back $1,000. A receipt correction (10e-2) brings back $2,000 of applications (counted), reverses the $2,000 receipt (not counted) and refunds X1's $1,000. Its net draw is $0, so X1 keeps $1,000 left while the Deposit holds nothing. Fix: count the correction's own Deposit receipts and forfeiture reversals as brought back, and its receipt reversals, forfeitures and Credit reversals as paid out, so its net draw is true (then X1 has $0 left).
3. (Independent) "A correction's own return first" is not proven by a test: in every real case the correction pays out everything the source holds, so the order cannot be seen. Fix: a test where it shows, if the real path reaches one; otherwise the docs say why it cannot be seen.

Also text notes (docs/004, docs/010, the migration and test docstrings, one traceability note) to correct, and one slice 12 item (a test of the Deposit holdings cap when a left value is more than the Deposit holds).

**Options:**
- (a) Owner exception, as for Q-2026-10-10-74: I fix all three and the text notes, run the static checks, the migration-only check, a targeted run, U3, the read-only search and P3 (all under `caffeinate -dims`), then one review round 3. If round 3 has no should-fix, I commit 10e-3d-1.
- (b) As (a), but fix only findings 1 and 3; finding 2 becomes a named known limit, and the fix moves to 10e-3d-2.
- (c) Stop 10e-3d-1 here and keep it uncommitted until 10e-3d-2 is decided.

**Recommendation: (a)**, because all three fixes stay inside your Q-97 answer and its detail (count only correction uses, limit a reversal to its own left value), and none changes a committed test result.

**What goes ahead.** Nothing in the order waits for this, except the commit of 10e-3d-1. The next sub-slice (10c-2a-7) changes different functions, but I will not start it on top of uncommitted work.

**Owner answer (2026-10-13).** Option (a), as a one-time exception to the round-3 rule: all three round-2 findings are inside what 10e-3d-1 is meant to do, and none changes a committed test result. Fix a, b and c and the text notes; run each lint, format and type check in its own call, with the formatter run on the changed files before the format check (cause B used both corrections); then the targeted tests, U3, the migration-only check, the read-only search for affected tests and P3, all under `caffeinate -dims`; then review round 3 (the independent reviewer compares each changed committed test with HEAD), which must be clean, or stop; then commit 10e-3d-1. If context reaches about 65% before the commit, stop, write the state in ops/NOW.md and the review record, and leave the work uncommitted. After the commit, stop (context above 45%).

Also answered: Q-2026-10-13-100 is not answered yet; the next report writes it in plain words (for each point, what happens under each option, with a short money example, and the recommendation with its reason). 10e-3d-2 waits; the next session builds 10c-2a-7 and the sub-slices after it. The `sed` replacement of the 27 head-revision assertions is accepted. Of the two old `/tmp` items, `trace_head_r2.json` (a copy of `ops/traceability.json` at ca73340) is removed and `rev2/anchors.py` (a reviewer's anchor-check script, not a repo copy) stays. Recorded in docs/010.

## Q-2026-10-13-102 — Sub-slice 10e-3d-1 stopped after review round 3 and P3 (blocks the 10e-3d-1 commit; recommendation (a)) (ANSWERED 2026-10-13: (a); answer in docs/010)

**What happened.** The Q-101 fixes are built: the reversal limit to the left value (tested on the real path), the receipt, forfeiture and Credit-reversal terms in the count, the text notes. Static checks clean; T3 62 passed; U3 3802 passed; M5 passed. Two things then failed your conditions:
- **Review round 3 is not clean.** Security found nothing to fix. The independent reviewer found three should-fix:
  1. My claim that "own return first" cannot be seen on the real path is wrong. A return-only Credit return that pays debt with its own step shows it. Example: X1 brings back $300 (return only); X2 brings back $1,700 (return only) and its own step pays $1,500 of a charge from the Credit. Own return first: X1 keeps $300, X2 keeps $200. Oldest first would leave X1 nothing. A test is needed, and the docs need fixing.
  2. The new receipt, forfeiture and Credit-reversal terms (finding (b) of Q-101) have no test.
  3. Some text still describes the round 1 state (plan, docs/010).
- **P3 failed 2 tests outside the sub-slice.** Both are `LockNotAvailable` from the known `NOWAIT` lock in `app.assert_payment_excess_eligible`, in `test_refund_migration.py`: `test_usd_refund_khr_origin_uses_recorded_usd_without_repricing` (already on the slice 12 list, Q-2026-10-05-26) and `test_usd_refund_private_boundary_immutable_history_and_fresh_actor`. No 10e-3d-1 change touches that path. P2 passed with the same tests.

Nothing is committed; all files are in the working tree. Record: ops/reviews/V1-056-slice-10e-3d-1-returned-value-count.md.

**Options:**
- (a) In a fresh session: add the two missing real-path tests (own return first; a returned Payment whose correction reverses the Credit, and a receipt correction after a return), fix the text, run the static checks, T, U4, M6, the read-only search and P4. P4 also shows whether the lock failure comes back. Then review round 4, which must be clean, then the commit.
- (b) As (a), but test finding (b) only through the returned-Payment case. The receipt-correction case would go on the slice 12 list.
- (c) Leave 10e-3d-1 uncommitted until 10e-3d-2 is decided, and build both together.

**Recommendation: (a)** in a fresh session. The fixes are tests and text only; the code is the same code the security reviewer found clean. This session is at about 56% context; the two real-path tests and the full runs would pass your 65% limit before a commit.

**Q-2026-10-13-100 in plain words (your request).** The question is still open. 10e-3d-2 waits for your answer.

*Point 1: a return whose money another correction paid out, then found to be a mistake.*
- Example (Pet Deposit). X1 records that $1,000 of the Settlement's Pet Deposit Refund came back. X2 later records another $500 coming back. Under BR-SETTLE-008, X2's new Refund pays out everything the Pet Deposit holds: $1,500 to the Customer. Then staff find that X1's $1,000 never came back.
- (a) X1's reversal charges the $1,000 to the person who received it: a $1,000 charge to the Customer, and the $1,000 return is removed from the records. If X2 had used some of the money for debt, that part comes back as debt instead. Example: X2 applies $600 to Rent and refunds $900. The Refund counts as paying out X2's own $500 first, then $400 of X1's money; the Rent payment used the other $600 of X1's money. So X1's reversal charges $400 back to the Customer, and $600 of Rent is owed again. That totals $1,000, exactly the mistake.
- (b) X1's reversal stays refused (today's 10e-3d-1 behaviour). The records keep a return that never happened, and staff must fix it outside the system.
- Recommendation: (a). It is the only way the system recovers the mistaken money from the person who received it, which is what your Q-97 answer asked ("a later reversal always charges the right person").

*Point 2: a correction of another Settlement uses the returned money.*
- Example. A Customer has two closed Leases, A and B. A correction of Lease A records $300 of a Credit Refund coming back into the Customer's Credit (return only, X1). Later a correction of Lease B uses that Credit to pay $300 of Lease B debt.
- (a) Count it. X1 then shows $0 left. A held-value Refund naming X1 is refused. If X1's return turns out to be a mistake, point 1 applies: the $300 Lease B payment is undone, and the Lease B debt is owed again.
- (b) Do not count it (today). X1 still shows $300 left while the Credit is empty, so a Refund naming X1 is refused only because the Credit holds nothing. But if other money later comes into that Credit (for example another $300 return, X3), a Refund naming X1 could pay out X3's money, and X3 could then no longer be reversed. That is the same problem as Q-97, rare because the same Customer must owe on two closed Leases.
- Recommendation: (a). It closes the last case where a left value can point at someone else's money. It is built with 10e-3d-2.

**Owner answer (2026-10-13).** Option (a). Add the two real-path tests: one that shows a correction's own return is used first (the X1 $300 and X2 $1,700 case from round 3), and one for a returned Payment whose correction reverses the Credit, plus a receipt correction after a return. Fix the plan and docs/010 so they describe the current state, and fix the wrong docs claim about "own return first". Then run the lint, format and type checks (each in its own call, formatter first), the targeted tests, U4, the migration-only check, the read-only search for affected tests and P4, all under `caffeinate -dims`. Then run review round 4: it must be clean, or stop. The independent reviewer compares each changed committed test with HEAD, including the two hand-built sources that gained `"left_usd_cents": 0`. Then commit 10e-3d-1. If P4 fails only in the known `LockNotAvailable` tests in `test_refund_migration.py`, rerun just those failing tests once under `caffeinate -dims`: if they pass, record it in the review record and continue; if they fail again, stop. Add `test_usd_refund_private_boundary_immutable_history_and_fresh_actor` to the `LockNotAvailable` item on the slice 12 list. Q-2026-10-13-100 is answered (both points (a); see that question). New run rule: when a reviewer asks for a test that the implementer thinks cannot be written on the real path, the independent reviewer confirms that before it is recorded as a limit instead.

## Q-2026-10-13-103 — Sub-slice 10e-3d-2: three cases your Q-100 answer does not decide (blocks only 10e-3d-2c and 10e-3d-2d; refused until answered) (ANSWERED 2026-10-13: points 1, 2 and 3 (a); answer in docs/010)

10e-3d-1 is committed (2c4efc3). The 10e-3d-2 design is in the plan (10e-3d entry, "10e-3d-2 pre-code design"). Your Q-100 answer covers money that a later correction paid out through a Refund (charged back to the person who received it) or through a debt payment (the debt is owed again). Sub-slice 10e-3d-2a builds that, and 10e-3d-2b follows a payment that a later correction changed. Three other cases need you. Until then each stays refused with its own message.

**Point 1: the returned money left the Credit or Deposit because a Payment bounced or a receipt was wrong.**
- Example (Credit). A correction records that $300 of a $2,000 Credit Refund came back (X1). Then the Payment behind that Credit bounces. Its correction charges the Refund's receiver only $1,700 (the Refund less X1's $300) and removes the $300 with the Credit. Later staff find that X1's $300 never came back: the receiver still has the whole $2,000.
- The Deposit form is the same: a receipt correction after X1 charges the Pet Deposit Refund's receiver $1,000 less than the Refund.
- (a) X1's reversal charges the $300 to the person who received that Refund (a second charge-back of the same Refund). In total that person pays back the whole $2,000.
- (b) X1's reversal stays refused (a known limit); staff fix it outside the system.
- **Recommendation: (a)**, because it follows your Q-2026-10-11-78 rule: the person who received the refund money pays it back.

**Point 2: the returned money was kept by a forfeiture of a correction.**
- Example (Pet Deposit). X1 records $1,000 of the Pet Deposit Refund coming back. A later receipt correction (10e-2c) forfeits the Pet Deposit's money, X1's $1,000 included. Then X1 turns out to be a mistake: the Property kept $1,000 that never came back.
- Your Q-2026-10-12-93 answer (sub-slice 10e-2d, in the order before 10h) stops a receipt correction from forfeiting returned money, and 10c-2b-6 already stops a forfeiture of returned pay-back money. After 10e-2d I expect no correction can forfeit returned money.
- (a) Keep it refused now; after 10e-2d I check every forfeiture path. If none can take returned money, the refusal stays as a backstop and nothing more is built.
- (b) Build it now: X1's reversal reverses that forfeiture and forfeits again only the part that was not X1's money (the Property keeps $1,000 less; nobody is charged).
- **Recommendation: (a)**, because the case should disappear with 10e-2d, and (b) would build a path no one can reach.

**Point 3: how the other Lease's history shows the correction (your Q-100 point 2 answer).**
- Example. A Customer has two closed Leases, A and B. A correction of Lease A brings back $300 of Credit (X1). A correction of Lease B uses it to pay $300 of B's debt. X1 is then found to be a mistake: X1's reversal (a correction of A) must undo B's $300 payment, and B's history must show which correction undid it.
- Today the closed Settlement of B refuses any change to its money unless a correction of B's own Settlement, confirmed in the same transaction, is linked.
- (a) X1's reversal also writes a short companion correction of B's Settlement, in the same transaction. It names X1's reversal correction and carries the undone B records. B's correction list and Lease history show it, and the existing refusal stays unchanged.
- (b) X1's reversal alone links the B records; B's refusal is widened to accept a correction of another Settlement of the same Customer. B's history shows the undo through the link to A's correction.
- **Recommendation: (a)**, because B's own history then lists it as one of B's corrections, and the refusal that protects a closed Settlement does not get wider.

**What goes ahead.** 10e-3d-2a and 10e-3d-2b do not depend on this answer and are built next, then 10c-2a-7 and the rest of the order.

**Owner answer (2026-10-13).** Points 1, 2 and 3, each option (a), as recommended.
- Point 1 (a): when a mistaken return's money left through a bounced Payment or a wrong receipt, charge the person who received that Refund. This is the same rule as the answers to Q-2026-10-11-78 and Q-2026-10-13-100: the person who received the money pays it back. If a case does not fit that rule, write it as a question and ask before building that part.
- Point 2 (a): keep the case of money kept by a forfeiture refused. Sub-slice 10e-2d should make it unreachable; check every forfeiture path again when 10e-2d is built.
- Point 3 (a): a companion correction on the other Lease's Settlement shows the undo. It is recorded and confirmed together with the reversal, in one step, so one never exists without the other.

Recorded in docs/010. Order (owner, 2026-10-13): 10e-3d-2a, 10e-3d-2b, 10e-3d-2c, 10e-3d-2d, 10c-2a-7, 10c-3c-1, 10c-3c-2, 10f, 10g, 10e-2d, 10e-2b-3, 10e-2b-4, then 10h.

## Q-2026-10-13-104 — Sub-slice 10e-3d-2a: putting back a part of a Credit payment on a Rent invoice (blocks only that case; refused until answered) (ANSWERED 2026-10-13: (b), its own small sub-slice before 10h; answer in docs/010)

Your Q-100 answer: when a mistaken return's money paid a debt, that debt becomes owed again, and the part of the payment that was not the mistaken money is put back. Sub-slice 10e-3d-2a does this by reversing the whole payment and paying the rest again from the same Credit to the same line (as in your Q-96 answer).

**The case.** The Customer's Credit paid two lines of one invoice that has Rent on it: first the Rent line, then a Service line (the Credit always pays Rent first, unless the Customer chose the line). The mistaken money paid all of the Rent payment and part of the Service payment. Example: Rent 1,000 and Service 500 paid from the Credit; the mistaken $1,300 covers the whole $1,000 Rent payment and $300 of the Service payment. The reversal undoes both payments and must put back the $200 of the Service payment that was not mistaken money. But the Credit's Rent-first rule now pays the Rent line first, so the $200 cannot go back on the Service line, and the reversal fails when it is confirmed.

- (a) Put the $200 back by the Rent-first rule: it pays the Rent line. In total the Customer owes the same $1,300 again, but $800 of it is Rent and $500 is Service (instead of $1,000 Rent and $300 Service).
- (b) Put the $200 back on the Service line, as an exception to the Rent-first rule for a correction's put-back part. The Customer owes $1,000 Rent and $300 Service again, exactly the debts the mistaken money paid.
- (c) Keep it refused (a known limit); staff fix it outside the system.
- **Recommendation: (b)**, because your Q-100 answer says the debt the mistaken money paid becomes owed again, and only (b) gives exactly that debt. A put-back part is not a new choice of where Credit goes; it restores a payment that existed.

**What happens now.** 10e-3d-2a refuses this case before anything is written (55000, "A part applied again on an Invoice with Rent or Service lines would not follow the Rent-first order; reversing this return waits for the owner"). It can happen only when another correction's payments on one such invoice used the mistaken money (review round 2 note: also when an own payment of the reversed correction is newer than another correction's payment on that invoice). Nothing else in the order waits for this answer.

**Owner answer (2026-10-13).** Option (b). When a put-back is a Credit part on an Invoice with Rent or Service lines, put it back on its own line, even where the Rent-first rule would choose another line today. A put-back restores what was there before the mistake; it is not a new allocation. Allow this only for a put-back linked to the correction, on the same line, and never more than the amount that was reversed there. Use the same answer for the 10e-3c put-back, so its known limit ends too. Keep the refusal in 10e-3d-2a as it is now, and build this answer as its own small sub-slice where it fits best before 10h.

Recorded in docs/010 and the plan. Placement (implementer, "where it fits best before 10h"): sub-slice 10e-3e, right after the 10e-3d-2a commit and before 10e-3d-2b, because it ends the refusal 10e-3d-2a adds and the 10e-3c known limit, and the put-backs that 10e-3d-2b and 10e-3d-2c add then use the same path from the start.

## Q-2026-10-13-105 — Sub-slice 10e-3d-2a stopped after review round 2: three should-fix findings (blocks the 10e-3d-2a commit; recommendation (a)) (ANSWERED 2026-10-13: (a), a one-time exception; answer in docs/010)

**Where it stands.** 10e-3d-2a (migration `20261204_130`) is built and green: P1 2126 and P2 2129 full PostgreSQL runs passed, U1 and U2 full unit runs passed. Review round 1 found no blocker and five should-fix (fixed: the order of the parts put back, the Rent-invoice case of Q-2026-10-13-104 refused, a mixed own-use case refused until 10e-3d-2b, docs, one more real-path test). Review round 2: security found nothing to fix; the independent reviewer found three should-fix. Your standing rule allows round 3 only with at most two, so I stopped. Nothing is committed; all files are in the working tree. Record: ops/reviews/V1-056-slice-10e-3d-2a-return-reversal-swept.md. Correction allowance: test cause B is used up (2 of 2); lint cause A and cause C each used 1 of 2.

**The three findings, in plain words.**
1. I said a test of two Deposit put-backs at different DL-032 stages could not be built with today's test data. The reviewer showed it can: two different later corrections, one at each stage, both used the mistaken money. The code fix is already in; only the test is missing.
2. I said a reversal that puts back both one of its own payments and another correction's payment could not happen. The reviewer showed it can: a held-value Refund that names the mistaken return pays a debt partly with another return's money. The code handles it; the test is missing.
3. Text: docs/010 did not yet record the round 1 changes, and docs/004 counted three new keys instead of four. Both are fixed now (text only), and the review record exists.

**Options:**
- (a) Owner exception, as for Q-2026-10-13-101: add the two real-path tests (the reviewer's set-ups) and two small fail-closed hardenings the reviewers noted (the new `shared_with_other_returns` key must be present as true or false, as the other new keys must, with `false` added to the hand-built test sources; the confirm's put-back loop refuses an unknown source kind), fix the stale comments, then each lint, format and type check in its own call (formatter first), the targeted tests, U3, the migration-only check, the read-only search and P3, all under `caffeinate -dims`; then review round 3 (the independent reviewer compares each changed committed test with HEAD), which must be clean, or stop; then commit 10e-3d-2a.
- (b) As (a), but without the two hardenings (they go on the slice 12 list).
- (c) Keep 10e-3d-2a uncommitted and build 10e-3d-2b on top before reviewing again.

**Recommendation: (a)**, because the two tests prove code that is already built and reviewed, the third finding is text and is done, and the two hardenings are small fail-closed checks of the same kind as the other new keys. No owner rule changes and no committed test result changes beyond the new key in the hand-built sources.

**What goes ahead.** Nothing, because the next sub-slices (10e-3d-2b, 2c, 2d) change the same functions and I will not build on uncommitted work. Q-2026-10-13-104 waits too (it blocks only its own case). This session is at about 54% context, above your 45% line for a new sub-slice, so the fixes are for a fresh session.

**Owner answer (2026-10-13).** Option (a), a one-time exception. Add the two real-path tests from round 2, using the reviewer's set-ups: the two-stage Deposit put-back, and one of the return's own payments put back together with another correction's. Add the two fail-closed checks: the `shared_with_other_returns` key must be present, and the put-back loop refuses an unknown source kind. Then run the lint, format and type checks (each in its own call, formatter first), the targeted tests, U3, the migration-only check, the read-only search for affected tests, and P3, all under `caffeinate -dims`. Then run review round 3. It must be clean, or stop. The independent reviewer compares each changed committed test with HEAD. Then commit 10e-3d-2a.

Also answered (2026-10-13):
- Round-3 rule, from now on: if round 2 has no blocker, and every should-fix is only a test, a text change, or a fail-closed check that adds a refusal, fix them and run round 3 without asking, even when there are more than two. Round 3 must still be clean, or stop. Any other kind of should-fix beyond two still needs the owner. Added to ops/V1_055_RUN_RULES.md.
- Before writing that a test cannot be built on the real path, try to build it, and ask the reviewer for a set-up in the same round. This has now cost an extra round twice. Added to ops/V1_055_RUN_RULES.md next to the rule on such claims (implementer's placement, so a new session reads it).
- The rename of `test_a_right_receipt_into_a_deposit_with_a_forfeiture_ground_waits_for_10e_2c` is still pending; it is done the next time that file is touched.
- Order after the 10e-3d-2a commit: 10e-3d-2b, 10e-3d-2c, 10e-3d-2d, 10c-2a-7, 10c-3c-1, 10c-3c-2, 10f, 10g, 10e-2d (the Q-2026-10-12-93 answer), 10e-2b-3, 10e-2b-4, then 10h, with the Q-2026-10-13-104 answer where it fits best before 10h (sub-slice 10e-3e, see that question). A large sub-slice may be split into smaller ones that each end in a commit.

Recorded in docs/010.

## Q-2026-10-13-106 — Sub-slice 10e-3e (your Q-104 answer): how the put-back Credit payment is labelled in the records (blocks only 10e-3e; the 10e-3d-2a refusal stays until answered) (ANSWERED 2026-10-13: (a), a new label written only by a correction's put-back; answer in docs/010)

10e-3d-2a is committed (db910ec). Your Q-104 answer: a Credit put-back on an invoice with Rent or Service lines goes back on its own line, even where the Rent-first rule would choose another line; only for a put-back linked to the correction, on the same line, never more than the amount reversed there; the 10e-3c put-back too.

**What the code does today (read before design).** Every Credit payment records why it went to its line, and the app checks that label at the database and again on the staff screens:
- "Rent then recurring services proposal": the database recomputes the Rent-first proposal at the moment of payment and refuses the payment if the stored proposal differs ("Credit proposal changed; obtain a fresh proposal").
- "Customer designated": needs the Customer's own designation text.
- "Other applicable obligation": refused on an invoice that has Rent or Service lines.
- The staff screen check (`frontend/src/financialActionContext.ts`) accepts only these four labels and shows an error for any other.

So a put-back on its own line cannot be written today with any of the four labels and stay true: it is not a fresh Rent-first proposal, the Customer did not designate it, and the other label is refused on such an invoice.

**Example.** Rent 1,000 and Service 500 were paid from the Credit by the Rent-first proposal. The mistaken money covers the 1,000 Rent payment and 300 of the Service payment. The reversal undoes both and puts 200 back on the Service line. Rent-first would put the 200 on Rent.

**Options.**
- (a) A new label "Put back by a correction" for the put-back payment (on the payment and on its line). The record also names the reversed payment it restores. The database accepts the label only for a put-back of a return reversal: linked to that correction, on the line of a payment the same correction reversed, never more than that payment's amount on that line. The staff screens and their checks learn the new label (a small frontend change with tests; no new package). Readers see plainly that the payment is a put-back, not a Rent-first choice.
- (b) Keep the four labels: the put-back copies the label of the payment it restores ("Rent then recurring services proposal"), with a record that names the reversed payment instead of a fresh proposal; the database check that recomputes the proposal is skipped only for such a put-back. No frontend change. But the record then says "Rent-first proposal" for a payment that does not follow today's Rent-first order, which a reader can misread.
- (c) Keep the 10e-3d-2a refusal (a known limit).

**Recommendation: (a)**, because each financial record must say truly why the money went where it did (AGENTS.md: auditable financial operations), and (a) is the only option where the label is true. It adds one database label value (a relaxing change of two checks) and a small screen change. BR-CREDIT-006 gets a note: a put-back of a return reversal is the exception your Q-104 answer allows.

**What goes ahead.** 10e-3d-2b, 10e-3d-2c, 10e-3d-2d and the rest of the order do not depend on this answer; their put-backs on such an invoice stay refused with the 10e-3d-2a message until 10e-3e is built. 10e-3e is built right after your answer, still before 10h.

**Owner answer (2026-10-13).** Option (a): a new label "put back by a correction", with the small screen change. Only a correction's put-back may write this label. Staff must not be able to choose it for an ordinary Credit payment; the screen only shows it. Recorded in docs/010.

## Q-2026-10-13-107 — Sub-slice 10e-3d-2b: the mistaken money sat in a payment that a later Refund correction or pet-damage reclassification changed (blocks only 10e-3d-2b-2; refused until answered) (ANSWERED 2026-10-13: (a), the order of the Q-100 answer; answer in docs/010)

The 10e-3d-2b design is in the plan (10e-3d entry, "10e-3d-2b pre-code design"). Sub-slice 10e-3d-2b-1 follows a payment that a later return reversal changed: that reversal took out exactly its own return's money and put the rest back, so the mistaken money of another return is in the put-back, unchanged, and no new rule is needed. Two other kinds of correction can change such a payment and pay the money out again in a different form, and there it is not written which part of the money went where.

**The case.** After closure, the Customer's Credit holds 1,000 that a return-only correction E brought back, plus 500 of other Credit. Another correction S lets the Credit pay a 1,500 charge (one payment of 1,500: 1,000 of E's money and 500 of the other money). Later:
- a Refund correction Q finds the charge was 300 too high: it lowers the charge by 300, takes those 300 out of the payment (the payment is reversed and 1,200 is paid again on the charge), and refunds the 300 to the Customer;
- or, for a Deposit, a pet-damage reclassification Q reverses the Deposit's payment of a line and pays the money out again by the DL-032 order (other lines, or a Refund).
Then E's return turns out to be a mistake. Its 1,000 now sits partly in Q's Refund and partly in Q's new payment, and nothing says how much in each.

**Options.**
- (a) Use the order you chose in Q-2026-10-13-100 for any correction: the money Q took back out of the payment pays out first on Q's Refunds (the oldest first), then on Q's payments (the newest first), and the mistaken money keeps its place in that stream. Example: if E's 1,000 were the first 1,000 of S's payment, 300 of it is in Q's Refund (charged back to the Customer who received it) and 700 in the new 1,200 payment (700 of the charge owed again). If E's money were the last 1,000, all of it is in the new payment (1,000 of the charge owed again). Together always exactly the mistaken 1,000.
- (b) Keep the mistaken money on the new payment first, as far as it fits, and in the Refund only for the rest. Example: all 1,000 in the new 1,200 payment (1,000 of the charge owed again), nothing charged back.
- (c) Keep it refused (a known limit; staff fix it outside the system).

**Recommendation: (a)**, because it is the same order you already chose for the money a correction pays out (Q-100: Refunds first, the oldest first, then payments, the newest first), so one rule covers every correction, and the person who received money pays back exactly the part that reached them.

**What goes ahead.** 10e-3d-2b-1 (a payment a return reversal changed, and the own payments placed by the same count) does not depend on this answer and is built next; until then, and for these two kinds until you answer, such a reversal stays refused with its own message ("A later correction changed a payment made with this return's money; reversing it waits for sub-slice 10e-3d-2b").

**Owner answer (2026-10-13).** Option (a): the same order as the Q-2026-10-13-100 answer (what the changing correction took back out of the payment pays out first on its Refunds, the oldest first, then on its payments, the newest first; the mistaken money keeps its place in that stream). Recorded in docs/010; built as sub-slice 10e-3d-2b-2.

## Q-2026-10-13-108 — Sub-slice 10e-3d-2b-1a stopped before its commit: the auto-mode checker blocked the round 3 security review (blocks the 10e-3d-2b-1a commit; recommendation (a)) (ANSWERED 2026-10-13: (a), then the review in the main session; answer in docs/010)

**Where it stands.** 10e-3d-2b-1a (migration `20261205_131`: a return's money on a payment a later return reversal changed follows to that reversal's put-back) is built and green: P4 2137 passed (P3 had one `Signature evidence is invalid` failure in a Lease fixture; the clock check K1 was in step, and P4 was the one allowed rerun), U3 3802 passed. Review round 1: security clean, independent one should-fix (a test), fixed. Review round 2: security clean, independent one should-fix (a test), fixed under your new round-3 rule. Review round 3: the independent reviewer is clean (0 blockers, 0 should-fix). Nothing is committed; every file is in the working tree. Record: ops/reviews/V1-056-slice-10e-3d-2b-1a-return-reversal-successor.md.

**What was blocked.** Starting the fresh read-only security reviewer for round 3 (a subagent told to write no file and run nothing, the same kind of reviewer that ran rounds 1 and 2 of this sub-slice and every earlier round). The auto-mode checker refused it with "Auto-Mode Bypass". Under the run rules I did not repeat it or try another way.

**Why it is safe.** The reviewer only reads the repository (git diff, cat, sed, grep) and reports; it writes nothing, runs nothing and touches no database or service. Since security round 2 (clean), only one test and text changed; the migration did not change.

**Options.**
- (a) You allow the round 3 security review (or run `/security-review` yourself); if it is clean, I commit 10e-3d-2b-1a.
- (b) You accept security rounds 1 and 2 (both clean, on the same migration) and the clean independent round 3 as enough, and I commit 10e-3d-2b-1a.
- (c) Leave it uncommitted.

**Recommendation: (a)**, because the takeover rules give every slice 10 sub-slice a security review before its commit, and round 3 must be clean in both reviews.

**What goes ahead.** Nothing: the next sub-slice (10e-3d-2b-1b) changes the same source function, and I will not build on uncommitted work. Q-2026-10-13-106 and Q-2026-10-13-107 are open too.

**Owner answer (2026-10-13).** Option (a): start the round 3 security reviewer once more, read-only, with the same task as in rounds 1 and 2; if the checker blocks it again, do not retry and do not try another way. The checker blocked it again ("Data Exfiltration"). The owner then said: do not start a reviewer agent again; do the round 3 security review in the main session, read-only, on `git diff HEAD` (the uncommitted 10e-3d-2b-1a work) with the checklist of rounds 1 and 2, check the run outputs only with the standard secret scan, write the result in the review record with a note that the checker blocked the reviewer twice; stop on a blocker or a should-fix; if clean, record the answers to Q-106 and Q-107 and the new run rule, commit 10e-3d-2b-1a, then stop (context above 45%). Result: clean (0 blockers, 0 should-fix; the review record lists the checks and three notes). New run rule (ops/V1_055_RUN_RULES.md): when a reviewer gives a test set-up, it is written in the review record so a later session can use it. Recorded in docs/010.

**Owner answers to the 10e-3d-2b-1a report (2026-10-13, fresh session).** (1) The round 3 security review done in the main session is accepted. (2) From now on, if the auto-mode checker blocks a review agent, do not retry it: do that review in the main session, read-only, on the sub-slice's changes only (`git diff HEAD` plus any new untracked files), with the same checklist, and note the block in the review record; if a second review agent is blocked in the same sub-slice, stop and tell the owner (added to ops/V1_055_RUN_RULES.md). (3) The first two notes of that review go on the slice 12 list: the `owner` join of the source function could also filter by the record kind, and the least-privilege test could check the successor function's rights list directly. Recorded in docs/010 and the plan.

**Owner answers to the 10e-3d-2b-1b report (2026-10-14, fresh session).** (1) The rename of `test_own_corrections_that_also_took_another_return_s_money_wait` to `..._are_undone_per_correction` is accepted; from now on, when an owner answer turns a refused case into an allowed one, the implementer may rename its test so the name says what it now checks, and records each rename (added to the standing rule for committed tests in ops/V1_055_RUN_RULES.md). (2) The extra "brought money back" walk-path condition is accepted, because it only sends such a case to the exact method. (3) Whether the 10e-3d-2b-1b review record shows that the independent reviewer compared each changed committed test with HEAD: it does (review round 3, independent; also review round 1 note N5), so no extra review was run before 10e-3e. (4) The three reviewer scratch files in `/tmp` were all empty (0 bytes) and were removed. (5) Counting corrections: running the formatter before the format check is a normal step, not a correction; a correction counts only when a check or a run fails; counts start again for each sub-slice (added to ops/V1_055_RUN_RULES.md). Recorded in docs/010.

## Q-2026-10-14-109 — Sub-slice 10e-3e: the "small screen change" of your Q-106 answer (blocks only the frontend part of 10e-3e) (ANSWERED 2026-10-14: (b), sub-slice 10e-3e-2; answer in docs/010)

Your answer (a) to Q-2026-10-13-106: a new label "put back by a correction", written only by a correction's put-back, with a small screen change; staff cannot choose it, and the screen only shows it.

**What the screens do today (read before design; corrected after review round 1).**
- The only staff-screen check with a fixed list of labels is `frontend/src/financialActionContext.ts`. It reads a Credit payment on the screen that reverses one Credit payment with one call. A correction's put-back itself is recorded under `financial.approve`, which that screen already refuses for every Final Settlement and correction Credit payment.
- But one case reaches it (found by the round 1 independent reviewer, proven by a new test): when a later `REFUND` correction releases part of a put-back, the rest is re-posted as an ordinary `credits.apply` payment that keeps the label. On the one-call reversal screen of that payment, the label list runs first and the screen shows a general "check the financial fields" error. The database refuses that one-call reversal anyway, so no money is at risk.
- The other screens that show a Credit payment's label (the financial evidence panel and the Customer Ledger evidence) show any label as it is written, with no list.
- No screen lets staff choose a label: staff give a Customer designation or take the Rent-first proposal, and the database decides the label. The database refuses the new label on every row that is not a correction's put-back (or the re-posted rest of one), so staff cannot write it.

**Options.**
- (a) No frontend code change in 10e-3e. The re-posted rest's one-call reversal screen keeps showing the general error; the evidence screens show the label as written.
- (b) Add the new label to the two lists in `financialActionContext.ts`, with a frontend test, so that screen shows the payment and its label; the reversal itself is still refused by the database (a conflict).
- (c) As (b), and also show a readable text ("Put back by a correction") instead of the code wherever a Credit payment's label is shown. Today every label is shown as its code, so this would be the first readable label.

**Recommendation: (b)**, because the screen should show the payment with its true label instead of a general error, which is what your Q-106 answer asked ("the screen only shows it"); (c) changes how every label screen looks, which belongs with the slice 11 screens.

**What goes ahead.** The backend of 10e-3e (the label, the put-back on its own line, the end of the 10e-3d-2a refusal) does not depend on this answer and is built now. With (b) or (c), the frontend part is a small sub-slice 10e-3e-2 after your answer.

**Owner answer (2026-10-14).** Option (b): add the `PUT_BACK_BY_CORRECTION` label to the screen's two lists, so staff see the label and the real refusal reason instead of a general error. Build it as the small sub-slice 10e-3e-2.

Also answered with the 10e-3e report (2026-10-14): (1) the implementer's three readings are accepted (the re-posted rest keeps the label; the label is used only where no existing label is true; the restored payment is read from the draft's stored source); (2) the `ops/traceability.json` change made by a script that wrote the whole file is accepted, because the diff showed only the intended lines; exact-text edits are preferred, and a script used again is named in the report; (3) a new small sub-slice comes first: the cause of the `Signature evidence is invalid` failures in the Lease signature fixture, then a test-set-up-only fix if the cause is the Mac and database clocks. Order: that sub-slice, 10e-3d-2b-2, 10e-3d-2c, 10e-3d-2d, 10e-3e-2, 10c-2a-7, 10c-3c-1, 10c-3c-2, 10f, 10g, 10e-2d, 10e-2b-3, 10e-2b-4, then 10h. Recorded in docs/010.

**Owner answers to the signature fixture clock report and the 10e-3d-2b-2 design (2026-10-14, fresh session).** (1) The signature fixture clock fix (07bca44) is accepted. The run rule "Signature tests and the clock" is retired: from now on a `Signature evidence is invalid` failure is a real failure, and its cause is found as for any other failure (ops/V1_055_RUN_RULES.md). (2) A read-only check of where the real app gets the signing time; if it can come from a clock other than the database's, write it as a question with a recommendation and build nothing before the answer: see Q-2026-10-14-110. (3) The `catalog-dump.sh` copy run from a tmp folder is accepted this once. A catalog dump needed again is added as a committed script under `scripts/` in its own small reviewed commit; like the other scripts, it must not print the database password or the database URL; copies in a tmp folder are not run (ops/V1_055_RUN_RULES.md). (4) The implementer's reading in the 10e-3d-2b-2 design is accepted: a return reversal's put-back keeps each part's place, with the reversed return's money cut out. (5) The pending rename of `test_a_right_receipt_into_a_deposit_with_a_forfeiture_ground_waits_for_10e_2c` is done the next time its file is touched. Order: 10e-3d-2b-2, 10e-3d-2c, 10e-3d-2d, 10e-3e-2, 10c-2a-7, 10c-3c-1 (the hardening of owner answer 3 to Q-2026-10-10-69), 10c-3c-2, 10f, 10g, 10e-2d (the Q-2026-10-12-93 answer), 10e-2b-3, 10e-2b-4, then 10h. Recorded in docs/010.

## Q-2026-10-14-110 — The real app takes the Lease signing time from the staff member's browser clock, and the database refuses any time ahead of its own (blocks nothing in slice 10; nothing is built before your answer) (ANSWERED 2026-10-14: (a), built next as a small sub-slice; answer in docs/010)

**Your request (2026-10-14).** A read-only check: `app.record_lease_signature` refuses a signing time later than the database's time, with no tolerance. Where does the real app get the signing time? If it can come from another clock, a small clock difference could refuse a real signing.

**What the code does (read at head `20261207_133`).**
- The staff Lease screen (`frontend/src/LeaseManagement.tsx`, lines 434 and 461) sets `signed_at` to `new Date().toISOString()`: the clock of the staff member's own computer or phone at the moment of the click.
- The two Lease routes that record a Signer's signature and sign the Lease (`backend/src/property_rental/lease_api.py`) take `signed_at` from the request body and pass it unchanged to the service. The service passes it to `app.record_lease_signature` and to `app.sign_lease_with_reservation`, which calls `app.sign_lease`.
- Both database functions refuse a signing time later than `statement_timestamp()`, the database server's clock (migration 24, lines 286 and 408: "Signature evidence is invalid", "Signing evidence is invalid"). The other time checks only keep the order (not before the Signer was added, not before an earlier signature; lines 304 and 448).
- So the time comes neither from the app server nor from the database: it comes from the browser. That is wider than the app-server case: a staff device clock is set on that device and often runs seconds ahead or behind. A device whose clock runs ahead of the database server's clock by more than the time a request takes to reach the database (milliseconds) has every signing refused. A device that runs behind passes, and the stored signing time is then that much earlier than the real moment.

**Example.** A staff laptop clock runs 3 seconds fast. Staff record the Primary Tenant's signature at 10:00:00 database time: the screen sends 10:00:03, so the database refuses it as invalid evidence. Every retry fails the same way until the laptop clock is corrected.

**Options.**
- (a) The signing time is the database's own time at the moment of the command: the screen stops sending its clock time, and the service or the database function uses `statement_timestamp()`. The existing check stays (it can no longer fail for a clock difference). The request shape changes (`signed_at` dropped or ignored), so docs/005, the client, the screen and their tests change, and a replayed request must still match its first result. A relaxing change; no existing record changes.
- (b) Keep the browser time and allow a small tolerance ahead of the database time (for example 2 minutes) in the two database checks: a relaxing migration. A device more than the tolerance ahead is still refused, and a stored signing time can be up to the tolerance in the future.
- (c) Keep it as is (a known limit): staff devices must keep a correct clock; the screen's error could say so.

**Recommendation: (a)**, because a signing time is evidence and the database clock is the one clock the app controls; it ends the dependence on staff device clocks. It belongs with the Lease screens or the login slice, before the first real use, not inside slice 10. Nothing is built before your answer.

**What goes ahead.** Everything; slice 10 does not depend on this answer.

**Owner answer (2026-10-14).** Option (a). A Lease signing time comes from the database's own clock, not from the browser. This also means nobody can make a signature look earlier by setting a device clock back. Build it next, as a small sub-slice, with the route and screen changes it needs. If it needs a tightening, or a change to committed tests beyond what this answer covers, ask first. Recorded in docs/010.

## Q-2026-10-14-111 — Sub-slice 10e-3d-2b-2 review round 1: two payments written in one correction can tie in the "newest first" order (blocks nothing; nothing is built before your answer) (ANSWERED 2026-10-14: (a), break the tie by write order, before 10h; answer in docs/010)

**What the reviewer found.** Your Q-100 and Q-107 answers place a mistaken return's money on a correction's payments "the newest first". The count orders them by their time, then by their id (sub-slice 10e-3d-2a, migration 130; the follow function of 10e-3d-2b-2 uses the same order). One correction often writes two or more payments from the same source with the same time (for example the rests a Refund correction writes again, which share one stamped time, migration 100). Then the order falls to the random id, so which of those two debts becomes owed again is chosen by chance. The total is always right (exactly the mistaken amount); only which debt is reopened can differ.

**Example.** A Refund correction releases two Credit payments of one Invoice and writes their rests again, 400 on the Rent line and 300 on the Service line, at the same time. A mistaken return's 300 sits in "the newest" of the two: by chance either 300 of Rent or 300 of Service is owed again.

**Options.**
- (a) Break a tie by the order the correction wrote the payments (its effect order: the last written counts as the newest). One rule, always the same result. A small change of the count's order (a relaxing change in effect: no refusal is added); a reversal recorded before it, where such a tie exists, becomes stale at its confirm and is recorded again.
- (b) Keep it as it is (a known limit; the total is always right).

**Recommendation: (a)**, because a financial correction must give the same result every time (AGENTS.md: deterministic calculations). It would be a small sub-slice before 10h, with a test where two payments of one correction share a time.

**What goes ahead.** Everything; nothing waits for this answer.

**Owner answer (2026-10-14).** Option (a): break the tie by write order, as recommended. Build it where it fits best before 10h. Recorded in docs/010.

**Built (2026-10-14, sub-slice 10e-3d-2b-3, migration `20261209_135`).** Correction found by the review: the premise above does not hold on the real path. The rests a Refund correction writes again do not share one stamped time, because the database already refuses a Credit application that is not later than every earlier event of its Credit (migration 41) and a Deposit application that is not later than the Deposit's latest balance event (migration 86, where `application_order` is also unique per Final Settlement). So the tie-break is defence in depth: no stored result changes. The tests make the tie by hand in a transaction that is always rolled back. Details in docs/010 and ops/reviews/V1-056-slice-10e-3d-2b-3-tie-break.md.

**Also answered with the 10e-3d-2b-2 report (2026-10-14).** (1) The implementer's four changes beyond the 10e-3d-2b-2 design are accepted: the put-back of a put-back is followed; the put-back is checked against this Settlement; the recovery scope also accepts a Refund listed among the return's own parts; the one test is built in the other order. (2) New run rule: when the design must change to keep a committed test passing or to make the planned rule work, the implementer may make the change without stopping, if the reviewers in the same round confirm it is needed and safe; each such change is named in the report; a change to who pays or how much still needs the owner's answer first (ops/V1_055_RUN_RULES.md). (3) The two line-targeted `sed` edits in docs/010 and the 10e-3d-2b-2 review record are accepted, because the diff showed only the intended text; exact-text edits are preferred. (4) The pending rename of `test_a_right_receipt_into_a_deposit_with_a_forfeiture_ground_waits_for_10e_2c` is done the next time its file is touched. Order: the Q-110 signing-time sub-slice, 10e-3d-2c, 10e-3d-2d, 10e-3e-2, 10c-2a-7, 10c-3c-1, 10c-3c-2, 10f, 10g, 10e-2d, 10e-2b-3, 10e-2b-4, then 10h; the Q-111 answer where it fits best before 10h. Recorded in docs/010.

## Q-2026-10-14-112 — Signing time sub-slice review round 1: other times the screens take from the device clock, and the database-level backdating limit (blocks nothing; nothing is built before your answer) (ANSWERED 2026-10-14: point 1 (a), read case by case, one small sub-slice after 10h; point 2 (a), a known limit; answer in docs/010)

Your answer (a) to Q-2026-10-14-110 is built for the two signing times: the screen sends no time, the two routes refuse a body that sends one (422), and the service passes the database's own time. Both round 1 reviewers found two related points outside that answer.

**Point 1: other times the screens still take from the device clock.**
- Lease termination: the screen sends `occurred_at: new Date().toISOString()` (`frontend/src/LeaseManagement.tsx`, about line 510; its retry form reuses the time of the first attempt, about lines 118 to 123 and 581). `app.terminate_lease` refuses an `occurred_at` later than the database's statement time, or earlier than the Lease signing time (migration 24, about lines 562 and 563). So the Q-110 problem is the same: a device clock that runs ahead cannot record a termination, and a device clock set back records an earlier termination time.
- Mixed clocks since this sub-slice: the signing time is now the database's, while the termination time is still the device's, and `app.terminate_lease` refuses a termination time before the signing time. A device clock that runs behind the database by a few seconds would have a termination refused only if it is recorded within those seconds after the signing (minor).
- Reservations: the screen sends `approved_at: new Date().toISOString()` for an extension, and the device-clock `now` it keeps when it creates a Reservation is sent as the holding deposit receipt's `received_at` (`frontend/src/ReservationManagement.tsx`, about lines 139, 159 and 193). The database allows both up to 5 seconds ahead of its own time (migration 19), so a small device clock difference does not refuse them as it refuses a termination. A received-money time can rightly be earlier than the command, so the rule "the database's own time at the command" may not fit `received_at`; it would be read with you first.
- Example: a staff laptop runs 3 seconds fast; staff record the termination at 10:00:00 database time; the screen sends 10:00:03 and the database refuses it, as for the signing before your Q-110 answer.
- (a) The same rule as Q-110: each of these times becomes the database's own time at the command, with the same route, screen and test changes, as one small sub-slice before the first real use (with the Lease and Reservation screens of slice 11, not inside slice 10). Each case is read first; a case that needs a tightening or a change to committed tests beyond the answer is asked first.
- (b) Keep them as they are (a known limit; staff devices must keep a correct clock).
- **Recommendation: (a)**, because these times are evidence of the same kind as a signing time, and one clock rule for all of them is simpler for staff.

**Point 2: the database functions still accept an earlier time from the application's own database role.**
- The application's runtime database role can still call `app.record_lease_signature` and `app.sign_lease_with_reservation` with a given time, as long as it is not later than the database's time and keeps the order checks. No route or screen can reach this since this sub-slice; only code running with the server's own database credentials can.
- That role already passes the acting person's id and the reason itself, so it is already trusted with more than the time. Some records stay stamped with the database's own time in any case: the command row of a Signer signature, the signing outcome row with its audit event, and the Lease's `updated_at`. Other records take the given time: the Signer's and the Lease's `signed_at`, and the `lease.sign` row of the Lease history, which the Lease timeline shows (and the copies of these values in the Signer and Lease history rows, each of which also keeps its own database time). So a backdated time from that role would appear on the Lease timeline, but the true time stays on record next to it. (Corrected in review round 2.)
- (a) Leave the database functions as they are (a known limit; the guarantee holds at the routes).
- (b) Make the two functions refuse or ignore a given time: a tightening migration, and committed database tests that pass explicit times (for example the one-microsecond-earlier and one-day-later refusals in `test_lease_lifecycle_migration.py`) would change.
- **Recommendation: (a)**, because the role is the server's own credential, and (b) is a tightening that changes committed tests for no practical gain.

**What goes ahead.** Everything; nothing waits for this answer. The signing time sub-slice is committed without it.

**Owner answer (2026-10-14).** Point 1, option (a), read case by case. When a time means the moment staff save the action, it is taken from the database clock, as for signing. When a time records something that happened before it was saved, like money received earlier, it is not changed: it is written as a new question with a recommendation. A change that needs a tightening, or a change to committed tests beyond what this answer covers, is asked first. Built as one small sub-slice after 10h. Point 2, option (a): a known limit, written in docs/010 and in the slice 12 list.

Also answered with the signing time report (2026-10-14): (1) keeping the optional time in the service commands is accepted, as long as no route passes one; (2) the committed test changes of the signing time sub-slice are accepted (`signed_at` dropped from the two request bodies and from TEST-FE-186, and the one added line in the lifecycle test); (3) the Q-2026-10-14-111 placement as sub-slice 10e-3d-2b-3 and the 10e-3d-2c design are accepted, including the two committed refusal tests that become allowed and are renamed under the standing rule; (4) the pending rename of `test_a_right_receipt_into_a_deposit_with_a_forfeiture_ground_waits_for_10e_2c` is done the next time its file is touched; (5) a run table also lists the passing rerun after each failed check (ops/V1_055_RUN_RULES.md). Order: 10e-3d-2b-3, 10e-3d-2c, 10e-3d-2d, 10e-3e-2, 10c-2a-7, 10c-3c-1 (the hardening of owner answer 3 to Q-2026-10-10-69), 10c-3c-2, 10f, 10g, 10e-2d (the Q-2026-10-12-93 answer), 10e-2b-3, 10e-2b-4, 10h, then the Q-112 times sub-slice; stop before slice 11. Recorded in docs/010.

## Q-2026-10-15-113 — Sub-slice 10e-3d-2d-1 review: another Lease's own Final Settlement uses the returned Credit (blocks nothing; nothing is built before your answer) (ANSWERED 2026-10-15: (a), built with 10e-3d-2d-2; answer in docs/010)

Your answer (a) to Q-2026-10-13-100 point 2: a correction on another Lease of the same Customer that uses the returned Credit counts too. Sub-slice 10e-3d-2d-1 builds that count. Both round 1 reviewers found one case it does not cover, because it is not a correction.

**The case.** A Customer has two Leases, A and B. A's Final Settlement is closed. A correction X1 of A records that 300 of a Credit Refund came back, so the Customer's Credit holds 300 again. B ends later, and B's own Final Settlement (not a correction) lets that Credit pay 300 of B's debt, because each Customer's Credit pays that Customer's open debt first. X1's count does not see this use: X1 still shows 300 left while the Credit is empty. If more money later comes into the Credit (for example another return X3 of 300), a held-value Refund naming X1 could pay out X3's 300, and X1's reversal could take X3's money: the same problem as Q-97. Today this is the known limit of your answer 2 to Q-2026-10-09-63 (Credit spent outside a correction is not counted); what the Credit holds still caps every payout.

**Options.**
- (a) Count a Final Settlement's own Credit payments too, in the same time order, so X1 shows 0 left. A reversal of X1 then has to undo a payment of B's closed Settlement, which needs a correction of B's Settlement: the companion correction of your Q-103 point 3 answer, built in sub-slice 10e-3d-2d-2. So (a) is built with 10e-3d-2d-2, before 10h.
- (b) Keep it as the known limit of Q-63 answer 2 (rare: it needs the Customer's second Lease to close after the return, with debt the Credit pays).

**Recommendation: (a)**, because your Q-100 answer asked that a left value is always true, and a Settlement's own payment uses the Customer's money in the same way as a correction's payment. The undo uses the same companion correction, so it adds little to 10e-3d-2d-2.

**What goes ahead.** Everything; 10e-3d-2d-1 is committed without it, and the 10e-3d-2d-2 design leaves room for it.

**Owner answer (2026-10-15).** Option (a). When the other Lease's own Final Settlement used the returned Credit, count that use too, in the same time order. Build it together with 10e-3d-2d-2. This narrows the known limit of the answer 2 to Q-2026-10-09-63 for this case only; the rest of that answer stays. Also: the changed outcomes of counting in one time order are accepted, as written in docs/004; the performance item stays in the slice 12 list. Recorded in docs/010. Order: 10e-3d-2d-2 (pre-code design first, with this answer), 10e-3e-2, 10c-2a-7, 10c-3c-1, 10c-3c-2, 10f, 10g, 10e-2d, 10e-2b-3, 10e-2b-4, 10h, then the Q-112 times sub-slice; stop before slice 11.

## Q-2026-10-15-114 — Sub-slice 10e-3d-2d-2a stopped after review round 3: one should-fix (blocks the 2d-2a commit; recommendation (a)) (ANSWERED 2026-10-16: (a), a one-time exception; answer in docs/010)

**Where it stands.** The 10e-3d-2d-2 pre-code design and your answers to the 10e-3d-2d-1 report are committed (bd4d654). Sub-slice 10e-3d-2d-2a (the companion correction; migration `20261212_138`) is built and green: P3 2182 and U3 3804 passed after the last code and test change. It is NOT committed; all files are in the working tree. Record: ops/reviews/V1-056-slice-10e-3d-2d-2a-return-reversal-companion.md. Round 1 had one blocker (fixed) and round 2 had two should-fix, a test and text (fixed under the round-3 rule). Round 3: security clean; independent one should-fix and five notes. Your round-3 rule says round 3 must be clean, or I stop. So I stopped.

**The should-fix.** In round 1 I patched two functions so that a return reversal counts only its own Lease's entries when it finds its own put-back: the follow function and `app.settlement_returned_value_successor`. Round 2 asked for a test; I built one on the real path, and it proves the follow function's patch (it fails under the old count). But the successor function has had no caller since migration 134, so that test never runs its patch. Five texts (the test docstring, its traceability note, docs/010, the plan and the review record) say both are tested. Nothing in the app calls the successor function, so no money or record is affected.

**Options.**
- (a) Add one assertion to that test: after X1's reversal, the successor function, asked about the first Lease's 400 payment, returns X1's reversal's own put-back (under the old count it returns nothing). Also take the five round 3 notes (all text, plus one more assertion in the same test: X3's reversal amount, 200) and the security reviewer's wording note for docs/004. Then the targeted run of the changed test files, the full unit and PostgreSQL runs, and the commit, with no fourth review round, as a one-time exception like Q-2026-10-13-101 and Q-2026-10-13-105. The migration file changes only in its docstring (one wrong sentence: "The follow function is not changed").
- (b) As (a), but with a fourth review round (independent and security) before the commit.
- (c) No new assertion: correct the five texts to say only the follow function's count is tested and the successor function has no caller; then the same runs and the commit.

**Recommendation: (a)**, because the assertion is one line on a case already built and green, it proves the remaining patch, and the round 3 reviewers already checked everything else (security clean; independent: every earlier fix real, committed tests not weaker, traceability append-only).

**What goes ahead.** Nothing in the order: 10e-3d-2d-2b builds on 2d-2a's migration, and the other sub-slices wait behind 10e-3d-2d-2 in your order. Context of this session is about 60%, so the next sub-slice starts in a fresh session after your answer.

**Owner answer (2026-10-16).**
1. Option (a), a one-time exception. Add the assertion that `app.settlement_returned_value_successor` returns the reversal's own put-back. Take the other round 3 notes: correct the five texts and add the one more assertion (X3's reversal amount, 200). If a new assertion fails, stop and report; do not change the code under test without a new review round. Then the lint, format and type checks (each in its own call, formatter first), the targeted tests, the full unit run, the migration-only check, the read-only search for affected tests and the full PostgreSQL run, all under `caffeinate -dims`. Then commit 10e-3d-2d-2a, without a round 4.
2. New run rule (ops/V1_055_RUN_RULES.md): if the only should-fix items in round 3 are text fixes or new assertions in tests that are already built and green, with no code, migration or fixture change, make them, rerun the checks and runs, and commit without a round 4; name each one in the report; if a new assertion fails, stop and tell the owner; any other round 3 finding still stops.
3. The implementer's reading for the companion is accepted: the approver records it and confirms it in the same step. The next report says what happens when the approver does not hold `final_settlements.prepare`.
4. The planned reading for 10e-3d-2d-2b is accepted: a charge-back of the other Lease's Refund goes on that Lease when the person who received the Refund is its signed Customer. Who pays and how much stay as the owner set them (Q-2026-10-11-78, Q-2026-10-13-100, Q-2026-10-13-103).
5. Slice 12 list: `app.settlement_returned_value_successor` has had no caller since migration `20261208_134`; decide whether it is still needed.

Also: the pending rename of `test_a_right_receipt_into_a_deposit_with_a_forfeiture_ground_waits_for_10e_2c` is done the next time its file is touched. Order after the 10e-3d-2d-2a commit: 10e-3d-2d-2b, 10e-3d-2d-2c (the Q-2026-10-15-113 answer), 10e-3e-2, 10c-2a-7, 10c-3c-1 (the hardening of owner answer 3 to Q-2026-10-10-69), 10c-3c-2, 10f, 10g, 10e-2d (the Q-2026-10-12-93 answer), 10e-2b-3, 10e-2b-4, 10h, then the Q-112 times sub-slice; stop before slice 11. Recorded in docs/010.

## Q-2026-10-16-115 — The 10e-3d-2d-2c follow-up: a return reversal that meets a confirm application later changed by a `REFUND` correction of its own Lease is followed, not refused (blocks nothing; a test of today's result goes in its own commit) (ANSWERED 2026-10-16: (a); answer in docs/010)

**Your instruction (2026-10-16).** The case 10e-3d-2d-2c did not build: a Final Settlement confirm's Credit application that a `REFUND` correction of its own Lease later changes. Confirm that a return reversal that meets this case is refused and writes nothing; then try the whole-line refund path the reviewer named; if it reaches the case, add a test that shows the refusal.

**What the code does (read at head `20261215_141`, then tried on the real path).** The reversal is not refused. The follow function (`app.settlement_returned_value_follow`) takes the confirm's application as written by its Final Settlement (sub-slice 10e-3d-2d-2c), sees that it was reversed by a correction, and reads that correction through the 10e-3d-2d-2b-2 allow-list: a `REFUND` correction of another Final Settlement that changed a Credit payment. It then follows the money into that correction's Refunds and payments, exactly as for a take by another Lease's correction (your answer 4 of 2026-10-16 and answers (a) to Q-2026-10-13-103 point 3 and Q-2026-10-13-107). This is also what the two round 1 reviewers wrote ("followed by the 2b-2 allow-list").

**Example (the new test, on the real path).** The first Lease's correction X1 brings back 300 of a Refund into the Customer's Credit. The second Lease closes; its own confirm lets that Credit pay 300 of its 12,500 damage line. A `REFUND` correction of the second Lease then refunds the whole line: it reverses the confirm's 300 payment and refunds that 300 from the Credit to the Customer (it also refunds the second Lease's own 400 Credit payment and the released Deposit money: 300 + 400 + 10,000 + 1,800 = 12,500). Now X1 turns out to be a mistake. X1's reversal lists one part (the second Lease's 300 Refund), the second Lease's Settlement as its companion, and a charge-back of that Refund to the Customer on the second Lease. Confirmed, it charges the 300 back on the second Lease through the companion; the line still owes nothing, the Credit ends empty, X1's Refund's net is 2,000 again, and the ledger reconciles.

**Options.**
- (a) Keep it: the case is followed and the person who received the refund money pays it back, on that Lease (Q-2026-10-11-78, answer 4 of 2026-10-16). The new test `test_a_confirm_application_its_own_lease_s_refund_correction_changed_is_followed` shows it.
- (b) Refuse it (fail closed) until a later decision: a tightening of the follow function for an application a Final Settlement confirm wrote; the new test would change to a refusal with nothing written.

**Recommendation: (a)**, because it follows your answers as they stand, and the money that left (the second Lease's Refund) is charged back to the person who received it, exactly as when another Lease's correction took the money.

**What goes ahead.** Everything. The test of today's result is committed on its own (tests and records only, no code change), and the order continues with 10e-3e-2.

**Owner answer (2026-10-16).** Option (a). Keep the case allowed: the reversal charges the 300 back to the Customer on the other Lease, through its companion correction, as the committed test `test_a_confirm_application_its_own_lease_s_refund_correction_changed_is_followed` shows. This follows the owner answers to Q-2026-10-11-78, Q-2026-10-12-95, Q-2026-10-13-103 and Q-2026-10-13-107. The two security notes of the follow-up review (the same mistaken money becomes a different debt with or without a later `REFUND` correction: the line owes again, or a recovery charge on the closed other Lease; the first Lease's approver alone creates that debt on the other Lease) are kept in docs/004 as known behaviour. Nothing is built; no test changes. Recorded in docs/010.

## Q-2026-10-16-116 — Sub-slice 10c-2a-7 review round 1: after a to-pet correction of a line from a superseded inspection, a later correction back to not pet damage passes (blocks nothing; nothing new is built) (ANSWERED 2026-10-16: (a); answer in docs/010)

**What the reviewer found.** Your answer (a) to Q-2026-10-08-53 says the change "allows only the change to pet damage", and your answers to Q-2026-10-11-80 and Q-2026-10-11-85 keep a test that a correction that is not to-pet on such a line is still refused. Sub-slice 10c-2a-7 does that for a fresh line: such a line reads as not pet damage, so the change to not pet damage is refused as the same classification ("The line already has this pet classification"). But after a confirmed to-pet correction, the line reads as pet damage (its latest classification record decides, sub-slice 10c-2a-5), so a later correction back to not pet damage passes, like any other correction of an earlier correction. This is not new code: the 10c-2a-5 reader and checks already work this way. The plan's pre-code check of 2026-10-11 named it, but no owner answer says it in words. The new test `test_a_superseded_inspection_line_with_no_pet_deposit_money_only_records_the_change` shows it.

**Example.** A line billed from inspection A's finding; A was superseded by B before closure. After closure staff record a to-pet correction X1 by mistake (the damage was not caused by the pet), and an approver confirms it. A second correction X2 sets the line back to not pet damage; it reverses what X1 changed under the usual rules and is confirmed by `financial.approve`.

**Options.**
- (a) Keep it: a correction that corrects an earlier correction is allowed, so a mistaken to-pet correction can be fixed with linked records.
- (b) Refuse every change to not pet damage on such a line, also after a to-pet record (a tightening; a mistaken to-pet correction could then never be fixed in the system).

**Recommendation: (a)**, because the answer's limit is about the inspection rule (a fresh line), and BR-SETTLE-013 lets a later fix be a new linked correction.

**What goes ahead.** Everything; 10c-2a-7 is committed with (a) as built, and the next sub-slice follows.

**Owner answer (2026-10-16).** Option (a). Keep it: the line's latest classification decides, so a confirmed correction to pet damage can later be corrected back to not pet damage, with its own approval. Nothing is built. Recorded in docs/010.

## Q-2026-10-16-117 — Sub-slice 10c-3c-1: a committed test whose name no longer fits after the hardening (blocks nothing) (ANSWERED 2026-10-16: (a), and a standing rename rule; answer in docs/010)

**What changed.** Your approved hardening (answer 3 to Q-2026-10-10-69) makes the 8a-1 refusal check that a linked Late-payment Charge correction's correlation is its correction and that the correction's draft names that Charge. The committed test `test_settlement_late_charge_deposit_refund_migration.py::test_a_linked_charge_correction_passes_8a_1_but_no_charge_is_paid_more_than_its_new_amount` builds its correction by hand with a draft that names no Charge, so its approver's row is now refused by 8a-1 (P4603) instead of passing it and being refused at commit (23514). Under the standing rule only its expectation, docstring and a comment changed; the commit-time check is kept with a matching row in the new module `test_settlement_correction_allow_hardening_migration.py`. The run rules say a narrowed historical test keeps its name, and the rename rule covers only a refused case that becomes allowed, so the name, which says "passes 8a-1", now says the wrong thing.

**Options.**
- (a) Rename it, for example `test_a_linked_charge_correction_under_a_draft_naming_no_charge_is_refused_by_8a_1`, with its traceability entry, in the next sub-slice that touches that file.
- (b) Keep the name; docs/010 and the traceability entry explain it.

**Recommendation: (a)**, because a test name should say what the test checks.

**What goes ahead.** Everything; nothing waits for this answer.

**Owner answer (2026-10-16).** Option (a). Rename that test the next time its file is touched. From now on, as a standing rule, the implementer may rename any committed test whose name an owner answer or a hardening has made wrong, without asking; only the name, the docstring and the traceability note change, and each rename is recorded (ops/V1_055_RUN_RULES.md). Also answered with the 10c-3c-1 report: 10c-3c-2 adds tests that reach the two `CHARGE_REDUCTION` writers that 10c-3c-1 confirmed only by reading, and shows they meet the new 8a-1 rule; the slice 12 list gets the old three-argument allow functions of 10c-3c-1, which have no caller (decide whether they are still needed). Order: 10c-3c-2, 10f, 10g, 10e-2d, 10e-2b-3, 10e-2b-4, 10h, then the Q-112 times sub-slice; stop before slice 11. Recorded in docs/010.

## Q-2026-10-16-118 — Sub-slice 10f-1 (the `ADJUSTMENT_REVERSAL` draft before closure): where the put-back goes, and which Adjustments it reverses (blocks only the refused cases; nothing waits) (ANSWERED 2026-10-16: point 1 (a), point 2 (a); answer in docs/010)

Your rule for the mistaken credit Adjustment (slice 10 entry, owner answer to the 8f report; owner answer 7 to Q-2026-10-06-36): an `invoices.adjust` holder prepares a draft, a `financial.approve` holder confirms it, and the confirm writes the Adjustment reversal and puts the released value back "on the line": a released Payment allocation made a new Credit, and the part of that Credit still available is applied to the line; a released Credit application returned its value to a Credit, and the part still available is applied again; any part already used elsewhere or refunded stays as debt on the line. The 10f pre-code design is in the plan. A read-only check found two points.

**Point 1: where the put-back goes when an earlier line still owes.** The Credit proposal (BR-CREDIT-006, `app.credit_application_proposal`) puts Credit on an Invoice Rent first, then Service Charges, then the other lines by their line order, unless the Customer designates lines; it uses the same order on an Invoice with no Rent or Service line (for example a final Utility Invoice with an Electricity line before a Water line). Where a line before the Adjustment's line in that order still owes, your rule ("on the line") and the Credit rule give different lines. For a return reversal you chose the line (answer (b) to Q-2026-10-13-104), with the label "put back by a correction", written only by a correction's put-back (answer (a) to Q-2026-10-13-106).

Example: a Rent Invoice with Rent 500.00 and Service Charges 100.00. A Payment paid the Service line in full; Rent still owes 500.00. Staff record a credit Adjustment of 100.00 on the Service line by mistake, so the 100.00 becomes Customer Credit. The reversal makes the Service line owe 100.00 again. The Rent-first rule would put the 100.00 Credit on the Rent line.

- (a) Put it back on the Adjustment's own line, always, with the same label "put back by a correction" (an Adjustment reversal is a correction confirmed by `financial.approve`). The label check also accepts a put-back of an `ADJUSTMENT_REVERSAL` confirmed in the same transaction, only on the Adjustment's line and never more than the release.
- (b) Keep the refusal of 10f-1: such an Adjustment cannot be reversed while a line before it still owes.
- (c) Follow the Rent-first rule: the Credit goes on the Invoice by the usual order, so in the example the Rent line gets the 100.00 and the Service line owes 100.00.

**Recommendation: (a)**, because it follows your rule and your return-reversal answer: the mistake is undone exactly where it was made. Until you answer, 10f-1 refuses the case (55000) and puts back only where the proposal order also chooses the Adjustment's line, that is, where no line before it still owes, on any Invoice (corrected in review round 1: the first text said this always held on an Invoice without Rent or Service lines, which is not so).

**Point 2: Adjustments that a resolution wrote.** A hand-back resolution (BR-RENT-030) and an unpaid-Initial resolution write credit Adjustments as part of a resolution record. Reversing only the Adjustment would leave the resolution record saying the opposite of the Invoice.

- (a) Keep them refused by the `ADJUSTMENT_REVERSAL` draft (a wrong resolution is decided as its own case when it happens).
- (b) Allow them like any other credit Adjustment.

**Recommendation: (a).** 10f-1 refuses them (55000).

**What goes ahead.** Everything else in 10f-1, then 10f-2 (after closure) and the rest of the order.

**Owner answer (2026-10-16).** Point 1: option (a). Always put the Credit back on the Adjustment's own line, with the "put back by a correction" label, even when an earlier line still owes. This follows the Q-2026-10-13-104 answer: a put-back restores what was there before; it is not a new allocation. Never more than the release or the line's unpaid rest. Point 2: option (a). An Adjustment that a hand-back or unpaid-Initial resolution wrote stays refused. Build point 1 where it fits best, in 10f-2 or as its own small sub-slice before 10g. Recorded in docs/010. Placement (implementer, "where it fits best"): its own small sub-slice 10f-1b, right after 10f-1 and before 10f-2, because it changes the 10f-1 put-back that the 10f-2 correction then reuses from the start (the reason the Q-104 answer was placed as 10e-3e).

## Q-2026-10-16-119 — Sub-slice 10f-2 (the `ADJUSTMENT_REVERSAL` correction after closure): may it reverse an Adjustment that a post-settlement correction wrote? (blocks only that case; refused until answered) (ANSWERED 2026-10-16: (b); answer in docs/010)

Your rule (owner answer 7 to Q-2026-10-06-36): after closure, a mistaken credit Adjustment is reversed only inside a correction prepared under `final_settlements.prepare` and confirmed by `financial.approve`. Sub-slice 10f-1 refuses an Adjustment that a post-settlement correction wrote. After closure, three corrections write credit Adjustments: a `CHARGE_REDUCTION` (removes an unpaid wrong charge; it releases nothing), a `REFUND` (removes a paid wrong charge; the released value is paid out as a Refund in the same correction) and a pet-damage reclassification (moves value between lines and Deposits).

Example: after closure, a `CHARGE_REDUCTION` correction removes 50.00 of a Damage line by mistake (the charge was right). Staff want to undo that reduction, so the line owes the 50.00 again.

- (a) Keep them refused. A mistaken correction is fixed by a new correction of an existing kind (for example an `EXTRA_CHARGE` of 50.00 on a new Invoice).
- (b) Allow the Adjustment of a `CHARGE_REDUCTION` only: it released nothing, so the reversal restores exactly the debt it removed, on the same line, and puts nothing back. Keep the Adjustments of a `REFUND` and of a pet-damage reclassification refused, because their released value already left through a Refund or another step of the same correction.
- (c) Allow every correction's Adjustment like any other credit Adjustment.

**Recommendation: (b)**, because it undoes the mistake exactly where it was made (as your Q-118 answer), and the other two kinds would need their Refund or their Deposit step undone too, which an Adjustment reversal does not do. Until you answer, 10f-2 refuses every correction's Adjustment (55000, as 10f-1 does today); a later relaxing change can lift the refusal.

**What goes ahead.** Everything else in 10f-2: the correction for a credit Adjustment recorded before the closure. The design is in the plan (10f entry, "10f-2 pre-code design").

**Owner answer (2026-10-16).** Option (b). The 10f-2 correction may reverse a credit Adjustment that a post-settlement correction wrote only when that correction is a `CHARGE_REDUCTION`. Its reversal restores exactly the debt the reduction removed. Every other correction's Adjustment stays refused. Recorded in docs/010; built in 10f-2.

**Also answered with the 10f-2 report (2026-10-16).** (1) The four implementer's readings of 10f-2, confirmed needed and safe by the round 1 independent reviewer, are accepted. (2) For 10h: a put-back that an `ADJUSTMENT_REVERSAL` correction made after closure can still be undone by the ordinary Credit application reversal. 10h must close this gap: either refuse that reversal after closure, or route it through a linked correction. If the fix changes who pays or how much, a question with a recommendation is written first. Recorded in docs/010 and the plan (10h entry).

## Q-2026-10-17-120 — Sub-slice 10g review round 1: an allocation that a `PAYMENT_MOVE` correction wrote on another Lease (blocks nothing in 10g; refused until answered) (ANSWERED 2026-10-17: point 1 (a), point 2 (a), point 3 (a); answer in docs/010)

Your answer 5 to Q-2026-10-06-37: the wrong-Unit fix may pay another Lease's Invoice, but no record that another Lease's closed Settlement relied on may change except through a confirmed correction of that Settlement. Sub-slice 10g builds the `PAYMENT_MOVE` correction. Both round 1 reviewers found three related points about the new allocation it writes on the other Lease.

**Point 1: a second mistake has no fix.** Example: Lease A's correction moves 1,000 onto Lease B's line. Later B closes, and its Settlement counts that 1,000. Then staff find B was also the wrong Invoice. A correction of B is refused, because A's correction wrote the allocation; a correction of A is refused, because the allocation is on B's Invoice. Until 10h the ordinary move draft still works; after 10h nothing does. The same holds in the other order: an allocation that B's correction wrote on A's Invoice after A closed is refused by both corrections (the 10g test of a correct Invoice on a closed Lease writes one).
- (a) Keep it refused, as a known limit, like your answer (a) to Q-2026-10-10-72 point 3 (a Payment that two closed Settlements relied on cannot be returned). It needs two mistakes on the same money.
- (b) Allow it only through two linked corrections, one of each Settlement (as the companion correction of Q-2026-10-13-103), as its own sub-slice.
- **Recommendation: (a).** 10g refuses it now (55000, "A correction of another Final Settlement wrote this allocation; this correction cannot move it").

**Point 2: other paths can still change that allocation without A's correction.** While B is open, an ordinary credit Adjustment on B's line can release it into B's Customer's Credit; after B closes, a `REFUND` correction of B can release it; and the ordinary move draft can move it (until 10h).
- (a) 10h refuses each of them for an allocation that a correction of a closed Settlement wrote (fail closed), with tests, as part of the 10h refusals after closure.
- (b) Keep them open (a known limit).
- **Recommendation: (a)**, because your answer 5 says such a record changes only through a correction of the Settlement that relied on it.

**Point 3: a waiting correction draft does not stop the other Lease's Settlement.** The Settlement preview lists a waiting ordinary move draft whose correct Invoice is on the Lease being settled, but not a waiting `PAYMENT_MOVE` correction draft (nor a waiting `PAYMENT_RETURN` or 10f-1 `ADJUSTMENT_REVERSAL` draft). So B's Settlement can close while A's correction waits; B's Deposit may then pay the line that A's Customer's Payment was meant to pay, and A's correction can no longer move the money there.
- (a) 10h adds these waiting drafts to the preview's pending-draft check (fail closed), with a test.
- (b) Keep it (a known limit; staff confirm or withdraw the correction first).
- **Recommendation: (a)**, because the preview already blocks the same move as an ordinary draft.

**What goes ahead.** Everything. 10g is committed with point 1 refused; points 2 and 3 are listed in the 10h entry and wait for your answer. 10h also makes the ordinary move recorder see a waiting correction draft (both reviewers; today only the correction recorder sees a waiting draft of either kind), as part of refusing ordinary move drafts of records a closed Settlement relied on.

**Owner answer (2026-10-17).** Points 1, 2 and 3: option (a) each. Point 1 is a known limit, as in the owner answer to Q-2026-10-10-72 point 3, and stays refused (the 10g refusal "A correction of another Final Settlement wrote this allocation; this correction cannot move it"). Point 2: 10h refuses the other paths that could change an allocation a correction made (a credit Adjustment on the other Lease's Invoice, a `REFUND` correction of the other Lease, and the ordinary move draft). Point 3: 10h adds the waiting correction drafts (the `PAYMENT_MOVE` correction draft, and the `PAYMENT_RETURN` and 10f-1 `ADJUSTMENT_REVERSAL` drafts) to the Settlement preview's pending-draft check. Also answered with the 10g report: the 10g design change is accepted (the move check also requires that the decision names this move); deleting the six scratch copies of the traceability file was right; a wrong allocation on a Payment that also has Customer Credit is asked as Q-2026-10-17-121 (nothing is built); every targeted and full run's full output is saved in `~/Development/prm-run-logs/`, quick reruns included. Recorded in docs/010.

**Also answered with the 10h-3 report (2026-10-20, fresh session; point 3 above is built in 10h-3).** (1) The two additions (the Credit branch of the waiting `PAYMENT_RETURN` draft, and another Settlement's waiting `RETURNED_PAYMENT` correction draft) and the side effect are accepted: a waiting draft must be confirmed, rejected or withdrawn before the closure or a Settlement correction goes ahead. (2) The security reviewer's unverified note of 10h-3 review round 2 (a closed Settlement's waiting Credit-refund correction draft, `REFUND` or `HELD_VALUE_REFUND`, may reach an open Lease the same way) is checked in the 10h-4 pre-code design. If it is real, 10h-4 closes it with the same kind of refusal, as long as no amount changes; if closing it would change who pays or how much, a question with a recommendation and a money example is written instead. (3) The slice 12 note about drafts already waiting when migration `20270111_168` is applied stays on the slice 12 list; there is no live data yet. Order: 10h-4 (pre-code design first), then the Q-112 times sub-slice; stop before slice 11. Recorded in docs/010.

## Q-2026-10-17-121 — A wrong-Unit allocation on a Payment that also has Customer Credit has no fix after closure (blocks nothing; nothing is built before your answer) (ANSWERED 2026-10-17: (a), in 10h or its own small sub-slice before 10h; answer in docs/010)

Found in the 10g review (round 3 note, named in the 10g report). Your answer 4 to Q-2026-10-05-16 (slice 7): Customer Credit and Refunds are recorded per Payment, not per allocation, so a move is refused while the Payment has any Customer Credit that is not reversed, or any Refund that is not fully returned; staff reverse those first. The 10g `PAYMENT_MOVE` correction keeps that rule unchanged (it runs the slice 7 source checks).

**The case.** Before closure, staff can reverse the Credit first (its uses with one call each, then the Credit), and then move. After closure they often cannot: the Final Settlement's DL-032 step applies a Customer's available Credit to that Customer's open debt, or refunds it, and after closure the one-call reversal of a Settlement Credit application is refused (P5S01) and a Settlement Refund cannot be undone in one call. So the Credit cannot be reversed, and the wrong allocation cannot be moved: no path in the system fixes it.

**Example.** Customer A pays 1,200. Staff put 1,000 of it on Lease A's damage line by mistake (it was meant for Lease B's Invoice on another Unit), and the other 200 becomes A's Customer Credit. Lease A's Final Settlement closes; its DL-032 step applies the 200 Credit to A's other open debt. Later staff find the mistake. The `PAYMENT_MOVE` correction of Lease A's Settlement is refused ("Reverse the Customer Credit or Refund from this Payment first"), and the 200 Credit application cannot be reversed after closure.

**Options.**
- (a) Smallest safe fix: inside the `PAYMENT_MOVE` correction only, replace the blanket Credit and Refund refusal with a narrow one. The correction moves only the wrong allocation, which is still active (10g already refuses a reversed allocation), so its value never became Credit or a Refund; the Payment's Credit and Refunds come from its other value, stay with the payer, and do not change, nor does the Settlement's use of them. Still refused: a Payment where a credit Adjustment released any part of an allocation of this Payment on the wrong Invoice (that Credit did come from the wrong money; it may belong to another Customer), and every other slice 7 and 10g refusal. The slice 7 draft keeps the blanket rule (before closure staff can reverse the Credit first). Who pays and how much change exactly as in 10g: Lease A's line owes the 1,000 again, Lease B's Invoice is paid; the 200 stays where the Settlement put it. A relaxing change (one exact-text patch of the 10g source, or a new internal source that the 10g recorder, confirm and insert check use), with real-path tests after a real closure, as its own small sub-slice.
- (b) The correction also undoes the Credit: it reverses the Settlement's 200 Credit application and the Credit, so A's other debt owes 200 again, then moves. This changes who pays beyond the move (A owes more), and it needs a DL-032 decision for any Credit that was refunded.
- (c) Keep it refused (a known limit, written in docs/010 and the slice 12 list); staff fix it outside the system.

**Recommendation: (a)**, because the move changes only the wrong allocation's own value, which is still on that allocation, so the per-Payment reason for the slice 7 rule does not apply to it, and without a fix a closed Lease keeps a debt paid with another Customer's money. If the 200 Credit was also meant for Customer B, that stays a separate case (a known limit, as today), because the Settlement used it.

**What goes ahead.** Everything; nothing waits for this answer. If you choose (a), I suggest it as a small sub-slice right after 10h (it builds on the 10g source, and 10h changes which allocations the move paths accept), before the Q-112 times sub-slice, or in slice 12.

**Owner answer (2026-10-17).** Option (a). Inside the `PAYMENT_MOVE` correction only, replace the blanket Credit and Refund refusal with the narrow one described in option (a). The Payment's Credit and the Settlement's use of it stay as they are. Build it in 10h or in its own small sub-slice before 10h, whichever fits best. Recorded in docs/010. Placement (implementer, "whichever fits best"): its own small sub-slice 10g-2, after 10e-2b-4 and right before 10h, because it changes only the 10g source and the 10h refusals then build on the final move source.

## Q-2026-10-17-122 — Sub-slice 10e-2d stopped after review round 1: the Q-93 rule can pay the Customer's returned money back a second time (blocks the 10e-2d commit; recommendation (b)) (ANSWERED 2026-10-17: (b); answer in docs/010)

**Where it stands.** Sub-slice 10e-2d (your answer (a) to Q-2026-10-12-93; migration `20261223_149`) is built as the plan's "10e-2d pre-code design" says, and green: T1 360, U1 3847 and P1 2247 passed, and no check or run failed. It is NOT committed: the migration, the tests, the docs/004 text and the traceability entries are in the working tree. Record: ops/reviews/V1-056-slice-10e-2d-payback-forfeiture.md. Review round 1: the independent reviewer found no blocker and three should-fix (docs/010 notes, one plan sentence, a real-path test of a staff choice to forfeit again). The security reviewer found one blocker in the money rule, below. I checked it against the new test's own numbers, and it is right.

**What 10e-2d does.** A right receipt that a receipt correction forfeits into a Pet Deposit with returned Pet Refund-review money is forfeited only beyond the pay-back count; the rest follows DL-032 in the same correction (your answer (a) to Q-93). The count is the running count of your answer (a) to Q-2026-10-10-76: returned Pet Refund-review money adds to it; a reversal of such a return and every later Pet Refund-review Refund take it out. When a Final Settlement or a correction applies that money to debt or refunds it, the count does not go down; only what the Deposit holds goes down. The pay-back value is the smaller of the count and what the Deposit holds.

**The problem.** A receipt correction may forfeit a new receipt only into a Deposit that holds nothing else (the 10e-2c rule). A Pet Deposit that has a pay-back count but holds nothing after the closure is empty because its pay-back money was already given to the Customer: the Final Settlement applied it to the Customer's debt or refunded it (DL-032, BR-SETTLE-008). The count did not change. 10e-2d then treats the first part of the new receipt, up to the count, as pay-back money again. So the Customer gets the returned money a second time, out of money the Property should keep.

**Example (the new test, in dollars).** The Pet Deposit held $50. A $50 Pet Refund-review Refund was paid, and $30 of it came back before the Lease ended for pet noncompliance. The Final Settlement refunded that $30 to the Customer. After closure, a receipt correction finds that $50 of the $100 Security Deposit receipt was really Pet Deposit money. 10e-2d forfeits $20 and applies $30 to the Customer's debt. In total the Customer has had $60 of pay-back, against $30 returned. If the receipt had been right from the start, the Pet Deposit would have held $80 at the end: $30 paid back once and $50 forfeited. So the Property keeps $30 less than it should. With a $20 Pet receipt, 10e-2d forfeits nothing. When the debt is smaller than the money, the rest is refunded in cash.

Why this was not in Q-93: its example said "$30 of the money the Pet Deposit now holds is pay-back money", but it did not say that a Pet Deposit that is empty after the closure has already paid that $30 out. That was a gap in the question, not in your answer.

**Options.**
- (a) Keep it as built: the pay-back part of the new receipt is the count, as answered. The Customer can get the returned money twice (a known effect, in docs/010).
- (b) Count only pay-back money the Customer has not had yet: the pay-back value becomes the count less the pay-back money that the Final Settlement and later corrections already applied or refunded from that Deposit and did not undo, never more than what the Deposit holds. In the example the new $50 is forfeited whole, and the Customer has the $30 once. One rule for every path (the Final Settlement, a returned Settlement Refund, a forfeiture, a receipt correction): the results stay the same wherever nothing was paid out yet, and a returned Settlement Refund that brings pay-back money back counts as pay-back money again. It changes how your Q-76 running count is used, so the forfeiture table's pay-back limit (sub-slice 10c-2b-6), the Deposit path and 10e-2d all follow it.
- (c) Keep 10e-2d only where the pay-back money was not paid out yet (for example, the corrected receipt's own Deposit, whose earlier payments and Refunds the correction undoes), and keep the 10e-2c refusal ("A forfeiture in a receipt correction takes only the new receipt's money") where it was paid out: a known limit; the money stays with the Payment.

**Recommendation: (b)**, because your answers to Q-93 and Q-76 say that returned money belongs to the Customer, and the Customer should receive it once, exactly as if the receipt had been right from the start (AGENTS.md: correct, deterministic financial calculations). (b) is larger than 10e-2d as built. It needs its own pre-code design: which payouts count, and a read of every committed test of the pay-back value. If a committed test result changes beyond your answer, I ask first.

Also for your decision with (a) or (c) (a design reading of mine, not in your answer): when the count covers the whole new receipt, 10e-2d forfeits nothing for a Deposit never forfeited, and refuses a staff choice to forfeit again (55000, "Nothing beyond the Customer's pay-back money is left to forfeit; choose DL-032").

**What goes ahead.** Nothing of 10e-2d is committed. The other round 1 findings are fixed with whichever option you choose. Sub-slice 10e-2b-3 changes the same receipt correction code and would take the next migration number, so building it while 10e-2d waits in the working tree would tangle the two commits. I stopped here; context is about 40%.

**Owner answer (2026-10-17).** Option (b). The pay-back count includes only money the Customer has not received yet. Money already paid out, for example by the Final Settlement Refund, is not paid back again. Use this one rule on every path. Where nothing was paid out, the result stays as built. Also confirmed: a staff choice to forfeit again (`FORFEIT`) is refused when the pay-back count covers the whole receipt (the implementer's reading above). Finish 10e-2d with this answer, the security reviewer's $30 / $50 case as a test, and the round 1 should-fix items (including the real-path test of a staff choice to forfeit again, with the reviewer's set-up). Recorded in docs/010.

## Q-2026-10-17-123 — Sub-slice 10e-2d review round 2: a Pet Refund-review Refund recovered by a charge still lowers the pay-back count (blocks nothing today; answer before 10e-2b-4; recommendation (a)) (ANSWERED 2026-10-17: (a), built with 10e-2b-4; answer in docs/010)

Your answer (b) to Q-2026-10-17-122: the pay-back count holds only returned money the Customer has not received yet, one rule on every path. 10e-2d builds it: a payout of the Pet Deposit (a Deposit application, or a Refund other than a Pet Refund-review Refund) takes pay-back money out first, and when the payout is undone (an application reversed, a Refund returned, or a Refund recovered by a charge, so the person who received it pays it back) the money counts as pay-back money again.

**The case.** A Pet Refund-review Refund (DL-053) is counted as you answered Q-2026-10-10-76 (a): a later Pet Refund-review Refund pays out the returned money first. If such a later Refund is then recovered by a charge (a `RECOVERED_BY_CHARGE` row, when the Payment that funded the Pet Deposit bounces or its receipt is corrected), the Customer owes it back, but the count stays lowered, as built in 10c-2b-5. So the Customer pays the Refund back and the Property may still forfeit that money.

**Example.** A Pet Deposit of $500 holds $500. A $300 Pet Refund-review Refund is paid and the $300 comes back (count $300). A new $300 Pet Refund-review Refund pays it out again (count $0). Later the receipt that funded the Pet Deposit is corrected: the new Refund is recovered by a $300 charge, the receipt is reversed, and a right $500 receipt is written. Today the count stays $0, so at a pet noncompliance termination all $500 could be forfeited, and the Customer also owes the $300 charge.

**A second case (review round 3, security; test set-up C of 10e-2d).** The first Pet Refund-review Refund itself is recovered by a charge. In the 10e-2d test: a $50 Pet Refund-review Refund is paid (the count stays $0, nothing had come back yet), $30 comes back (count $30), and the Final Settlement refunds the $30. Then the seeded Pet receipt is reversed by a receipt correction: the Settlement's $30 Refund and the review Refund's $20 that never came back are both recovered by a charge, so the Customer owes $50. 10e-2d counts the Settlement Refund's recovery (count $30 again), but not the review Refund's $20. A new right $50 Pet receipt then forfeits $20, and the Customer still owes the $20 charge, although the whole $50 review Refund has now come back to the Property ($30 by the bank, $20 by the charge). The committed test expects that $20 forfeiture today, as built; it changes with your answer.

**Why it waits.** No real path reaches it today: no function puts money into a Pet Deposit before closure, and a Pet Refund-review Refund is paid only while the Lease is signed, so its recovery needs a Pet receipt from a Payment before closure. Sub-slice 10e-2b-4 (Deposit receipts before closure) makes it reachable.

**Options.**
- (a) A Pet Refund-review Refund's recovery by a charge counts like a verified return of that Refund: what is charged back adds to the count (both examples: the count rises by $300 and by $20). Built with 10e-2b-4, before it lets money into a Pet Deposit before closure; the 10e-2d test of the second case then forfeits nothing and pays the $50 to the charges.
- (b) The recovery gives back only what that Refund took out of the count (the first example rises by $300; the second by $0, because the first Refund took nothing out).
- (c) Keep it as built (a known limit in docs/010).

**Recommendation: (a)**, because your answer (b) to Q-122 asks for one rule on every path, money the Customer pays back by a charge has come back as surely as money the bank returned, and the Customer should not both pay the Refund back and lose the money to a forfeiture.

**What goes ahead.** Everything; 10e-2d does not change it (Pet Refund-review rows count exactly as built).

**Owner answer (2026-10-17).** Option (a). When a Pet Refund-review Refund is recovered by a charge, what is charged back counts like a verified return. The Customer must never both pay money back and lose the same money to a forfeiture. Update the set-up C test's expected forfeiture to match this answer, and name in the report what it was and what it is now. Built with sub-slice 10e-2b-4.

Also answered with the 10e-2d report (2026-10-17): (1) the three implementer's readings that the round 2 reviewers confirmed are accepted: a recovery by a charge undoes the payout; a payout takes pay-back money first; the own-Deposit count leaves its payouts out; (2) the check that now refuses returning the forfeiture reversal's Pet Refund with a new Refund after staff forfeit again is accepted, because it follows the Q-2026-10-17-122 answer and that state could not be reached before; (3) the known limit (a forfeiture into a Deposit that holds unreceived pay-back money is refused) becomes a question only if staff could not finish a correction at all; otherwise a known limit in the plan (implementer finding: staff finish it with a `HELD_VALUE_REFUND` correction first, so it is a known limit in the slice 12 list); (4) the placement of the Q-2026-10-17-121 answer as sub-slice 10g-2, after 10e-2b-4 and before 10h, is accepted. Order: 10e-2b-3, 10e-2b-4, 10g-2, 10h, then the Q-112 times sub-slice; stop before slice 11. Recorded in docs/010.

## Q-2026-10-17-124 — Sub-slice 10e-2b-4c: the walk-in Lease's Security Deposit (blocks only 4c; nothing of 4c is built before your answer) (ANSWERED 2026-10-17: point 1 (a), point 2 (a), point 3 not (a): allowed up to the required total; answer in docs/010)

Your answer 3 to Q-2026-10-12-92: sub-slice 10e-2b-4 also covers the walk-in Lease, which gets no Security Deposit today, and a second Security Deposit receipt; follow docs/002 for amounts and timing, and ask first where a rule is missing. 4a (your Q-123 answer) and 4b (a receipt into an existing Deposit of a Lease, both types, `payments.allocate`) do not depend on this question.

**What exists (read only, head `20261224_150`).** A Security Deposit row is created only by `app.create_reservation`, with the Reservation's accepted amounts: the required total (`accepted_required_amount_usd_cents`) and the initial amount, which its first receipt must equal (BR-DEP-002). The table requires a Reservation for every Security Deposit (`deposits_source_shape`), and the receipt check reads the acceptance through it. The Lease has no Security Deposit amount of its own. A walk-in Lease (DL-066) is signed with no Reservation, so it has no Security Deposit row, and a Customer's money for it can only stay an unallocated Payment. docs/002: every Lease has a required Security Deposit total set by the agreed Lease terms (BR-DEP-004); the balance after the holding deposit is due within five calendar days after the Lease Start Date and never blocks move-in (BR-DEP-006, DL-066); every receipt stays part of the same Security Deposit (BR-DEP-002, BR-DEP-005).

**Point 1: the required amount of a walk-in Lease's Security Deposit.** Nothing records it today.
- (a) Staff create the walk-in Lease's Security Deposit with its required total, as the agreed Lease terms say, through a new Deposit command like the Pet Deposit's (`deposits.manage`, a reason, audited; a SIGNED walk-in Lease only, one Security Deposit per Lease). Later changes use the existing required-amount adjustment.
- (b) The required total is taken from a fixed rule (for example one month's agreed Rent).
- **Recommendation: (a)**, because BR-DEP-004 says the agreed Lease terms decide the amount, the Pet Deposit already works this way, and no fixed rule exists in docs/002.

**Point 2: the first-receipt rule.** For a Reservation, the first receipt must equal the accepted initial amount (BR-DEP-002). A walk-in Lease has no accepted initial amount.
- (a) Any amount from 1 cent up to the required total, in one or more receipts (the only limit is the required total, as for a Pet Deposit).
- (b) The first receipt must be the whole required total.
- **Recommendation: (a)**, because BR-DEP-006 lets the balance come within five days and DL-066 says unpaid Deposit money never blocks move-in, so a partial first payment is normal; the due date stays a reminder, not a write limit.

**Point 3: a second receipt into a Reservation's Security Deposit before the Lease is signed.** The receipt check allows it up to the required total, but no writer exists.
- (a) No: before signing, the Reservation's Deposit holds only the accepted initial amount; a Payment received earlier stays unallocated until the Lease is signed, and then 4b records it into the same Deposit (BR-DEP-005: the same Deposit continues into the Lease).
- (b) Yes, up to the required total, with the 4b writer under `payments.allocate`.
- **Recommendation: (a)**, because BR-DEP-006 places the balance after the holding deposit with the Lease (due after the Lease Start Date), and a Reservation that ends without a Lease would then hold more than the accepted amount, which the Reservation outcome rules (Refund or forfeiture of the accepted amount) do not cover. 4b, as designed, refuses a Deposit with no Lease (55000) until you answer.

**How 4c would be built after your answer.** A relaxing migration: the Deposit shape check also allows a Security Deposit with a Lease and no Reservation; the receipt check's Security branch, for such a Deposit, uses only the required total (and the Lease signing time as the earliest receipt time); the new create command; the 4b writer then records its receipts. Routes and screen in slice 11.

**What goes ahead.** Everything else: 4a, 4b, 10g-2, 10h and the Q-112 times sub-slice. 4c is built at the next sub-slice boundary after your answer.

**Owner answer (2026-10-17).** Point 1: option (a). Staff enter the required Security Deposit total from the Lease terms with the new `deposits.manage` command. A walk-in Lease has the same full Security Deposit as any other Lease. Point 2: option (a). The first receipt may be any amount above zero, up to the required total, never above it. The 20% suggestion applies only to making a Reservation active. The full Security Deposit is still due within five days after the Start Date (DL-066). Point 3: not (a). A second receipt into a Reservation's Security Deposit before signing is allowed, because DL-008 says the rest of the Security Deposit may be paid before or at move-in. It may never take the Deposit above the required total. If the Reservation has no required total yet, staff enter it first with the same `deposits.manage` command of point 1. If this conflicts with another approved rule, a question is written and the rest is built. Recorded in docs/010.

**Owner note (2026-10-17, with the 10e-2b-4b-1 report).** For 10e-2b-4c: DL-009 says Security Deposit received is not refunded when a Customer causes a Reservation to be cancelled or to expire. With the point 3 answer, that includes extra Deposit money paid before signing. Follow DL-009 as written. If the Reservation outcome code cannot handle a Deposit that holds more than the accepted amount, fix that inside 10e-2b-4c. If another rule conflict is found, write a question with a recommendation. Recorded in docs/010.

## Q-2026-10-17-125 — Sub-slice 10e-2b-4a review round 1: a recovery charge that is later forgiven still counts as money that came back (blocks nothing; a known limit until you answer; nothing is built) (ANSWERED 2026-10-17: (a); answer in docs/010)

Your answer (a) to Q-2026-10-17-123: what a charge recovers of a Pet Refund-review Refund counts like a verified return. Sub-slice 10e-2b-4a counts the `RECOVERED_BY_CHARGE` row itself, the amount charged back. Your answer (b) to Q-2026-10-17-122 already counts a payout as undone when its Refund is recovered by a charge (sub-slice 10e-2d), the same way.

**The case (security reviewer, round 1).** The count reads the recovery row, not whether the recovery charge still stands. If the Property later forgives the charge, the money did not come back, but the count still says it did. Today a recovery charge can be reduced after closure by a `CHARGE_REDUCTION` correction (nothing refuses a recovery charge's line; it needs `financial.approve`). Once sub-slice 10e-2b-4b lets Pet Deposit money in before closure, a Pet Refund-review Refund can be recovered by a charge on a Lease that is not closed (the sub-slice 10e-1c Payment return of the Pet Deposit's funding Payment writes the recovery charge on the open Lease; `test_payment_return_recovery_migration.py` shows it with a Pet Deposit seeded by a direct owner insert, which no app role can do), and then one staff member could remove that charge without `financial.approve`: by an ordinary credit Adjustment (`invoices.adjust`) or by a VOID of its unpaid Invoice (`app.void_invoice`) (review round 2).

**Example (the 10e-2d test set-ups B and C, after 4a).** The review Refund's $20 is charged back to the Customer, so the count rises to $50, and a later right $50 Pet receipt is all pay-back money (nothing forfeited). If a `CHARGE_REDUCTION` then removes the $20 charge, the Customer keeps the review Refund's $20 and also had $20 more of pay-back, so the Property is $20 short. The same holds today for a Settlement Refund recovered by a charge whose charge is reduced (10e-2d).

**Options.**
- (a) Count a recovery only as far as its charge still stands: the count takes out what a credit Adjustment, a `CHARGE_REDUCTION` or a VOID of its Invoice removed from the recovery charge's line, for Pet Refund-review Refunds (4a) and for undone payouts (10e-2d) alike. An unpaid charge still counts (the Customer owes it). A small sub-slice before 10h, with real-path tests.
- (b) Refuse a credit Adjustment, a `CHARGE_REDUCTION` and a VOID of a recovery charge's line or Invoice (a fail-closed tightening; a recovery charge is an exact computed amount, so a real mistake in it is fixed by correcting the return or the receipt that caused it).
- (c) Keep it as built (a known limit in docs/010 and the slice 12 list).
- **Recommendation: (a)**, because your answers say the Customer receives returned money exactly once: money the Property forgives has not come back, so it must not count as pay-back money; (a) also keeps staff able to forgive a charge when that is the business decision.

**What goes ahead.** 4a is committed with the known limit. At its commit, on the app's real paths, only a `CHARGE_REDUCTION` confirmed under `financial.approve` can forgive such a charge (the same class as the accepted 10e-2d limit), because a Pet Refund-review Refund needs Pet Deposit money, and before closure no app function records Pet Deposit money yet (Q-2026-10-12-92); after closure the recovery charge sits on the closed Lease, where a VOID or an ordinary Adjustment is refused (P5S01). The 10e-2b-4a security reviewer of round 3 read the 10e-1c open-Lease path as reachable now; it is, but only with Pet Deposit money that today only a test fixture can insert. 4b makes the one-person path above reachable, so I recommend answering before 4b is built; 4b waits for this answer. 10g-2, 10h and the Q-112 times sub-slice do not depend on it. Recorded as a known limit in the slice 12 list until you answer.

**Owner answer (2026-10-17).** Option (a). A recovery counts as money that came back only while its charge stands. If the charge is later forgiven by a `CHARGE_REDUCTION`, a credit Adjustment or a VOID, it stops counting. Build it whether or not the one-person path is reachable today. Recorded in docs/010. Placement (implementer, under the owner's rule that a large sub-slice may be split): sub-slice 10e-2b-4b is split; 10e-2b-4b-1 builds this answer first, and 10e-2b-4b-2 is the receipt writer of the 4b design, because the writer waited for this answer and makes the one-person path reachable.

## Q-2026-10-17-126 — Sub-slice 10e-2b-4b-1 review round 1: a forgiven recovery charge that is restored after a forfeiture (blocks nothing in 10e-2b-4b-1; a known limit until you answer; nothing is built) (ANSWERED 2026-10-17: point 1 (a), point 2 confirmed; answer in docs/010)

Your answer (a) to Q-2026-10-17-125: a recovery counts as returned money only while its charge stands. Sub-slice 10e-2b-4b-1 builds it: what a charge still stands decides how far its recovery counts, and a charge that stands again (an Adjustment reversal, or the same charge billed again after a VOID) counts again exactly as before. The security reviewer of round 1 found one case your answer does not decide.

**The case.** While the charge is forgiven, the count is lower, so a forfeiture of that Pet Deposit may take more. If the charge is later restored, the Customer owes the recovered money again, but the forfeiture already took it. So the Customer both pays the money back and loses it to a forfeiture, which your answer (a) to Q-2026-10-17-123 says must never happen.

**Example.** A Pet Deposit's $150.00 Pet Refund-review Refund is recovered by a $150.00 charge (count $150.00). Staff VOID that charge's Invoice (count $0). A new $150.00 Pet receipt comes in and the Lease ends for pet noncompliance; the whole $150.00 is forfeited on BR-DEP-022, because the count is $0. Then staff bill the same charge again on a new Invoice: the Customer owes $150.00, and the Property keeps the forfeited $150.00. Without the VOID, the $150.00 receipt would have been pay-back money and would have paid the charge (DL-032). After closure the same can happen with a `CHARGE_REDUCTION` whose Adjustment the 10f-2 correction later reverses, around a receipt correction's forfeiture (the 10e-2b-4b-1 bc set-up: the Customer is $15.00 worse off).

**A related point (security reviewer).** A recovery charge whose recipient is not the Lease's signed Customer is an Invoice with no Lease, so the closed-Settlement refusal does not cover it: after closure one staff member with `invoices.void` or `invoices.adjust` can forgive it and so lower the closed Lease's Pet Deposit count. On its own this does not lose money (the Customer is forgiven exactly what the count loses); with the case above it can.

**Options.**
- (a) Refuse a restoration of a recovery charge (billing the same charge again, a DEBIT Adjustment of its line, or an Adjustment reversal) while a forfeiture of the recovered Refund's Deposit that was recorded after the forgiveness is active; staff reverse that forfeiture first (sub-slices 6b and 10d). A fail-closed tightening, with tests.
- (b) Make a forgiveness of a recovery charge final: refuse every later restoration of it (this also refuses the 10f-2 reversal of a `CHARGE_REDUCTION` of such a charge, which your answer (b) to Q-2026-10-16-119 allows today).
- (c) Keep it (a known limit in docs/010 and the slice 12 list).
- **Recommendation: (a)**, because it keeps every correction path you approved and refuses only the one order of events that would charge the Customer for money the Property already kept. Built as its own small sub-slice, (a) also needs a lock that the restoring writers (a DEBIT Adjustment, an Invoice issue, the 10f-1 and 10f-2 reversals) share with the forfeiture writers, covers the no-Lease charge above, and covers a Final Settlement confirm that keeps the Pet Deposit; the pre-code design reads whether a narrower test (refuse only what the Deposit could not hold as pay-back) fits better.

**Point 2 (an implementer's reading, for your confirmation).** A recovery charge's line can also carry a DEBIT Adjustment (an extra charge on the same line). The build counts at most the recovered amount, so a later credit forgives the extra part first. Example: the recovery is $150.00; a $20.00 DEBIT makes the line $170.00; a $30.00 credit leaves $140.00, so $140.00 of the recovery still counts. Read literally ("takes out what a credit Adjustment removed"), $120.00 would count. Recommendation: keep the build, because the DEBIT was never recovered money, so forgiving up to its amount leaves the recovery whole. The build does not depend on the order: it counts the smaller of the recovered amount and what the line still carries, so a DEBIT after a forgiveness makes that much count again (a $30.00 credit, then a $20.00 DEBIT: $140.00 counts), which favours the Customer and is the restoration of point 1. Tested in `test_a_standing_charge_counts_at_most_the_recovered_amount_paid_or_not`.

**What goes ahead.** 10e-2b-4b-1 is committed with point 1 as a known limit and point 2 as built. On the app's real paths today point 1 needs Pet Deposit money that only a test fixture seeds before closure, or, after closure, three corrections confirmed under `financial.approve` (the reduction, the forfeiting receipt correction and the 10f-2 reversal), or one approved forfeiture around a one-person VOID and re-bill (or a one-person credit and later DEBIT Adjustment) of a no-Lease recovery charge. 10e-2b-4b-2 makes the open-Lease path reachable for staff, so it waits for your answer (security review round 2); 10g-2, 10h and the Q-112 times sub-slice do not depend on it.

**Owner answer (2026-10-17).** Point 1: option (a). Refuse restoring a forgiven recovery charge while a forfeiture that relied on the lower count is active. Staff must first reverse that forfeiture with the existing reversal, then restore the charge. The Customer must never owe money that the Property also keeps. Point 2: the implementer's reading is confirmed. When a recovery charge's line also carries a DEBIT, a later credit forgives the DEBIT's part first.

Also answered with the 10e-2b-4b-1 report (2026-10-17): (1) the design change of review round 1 (the recovery counted as if it had been that much smaller, instead of placing each change at its own time) is accepted, and so is the split of 10e-2b-4b into 10e-2b-4b-1 and 10e-2b-4b-2; (2) adding the real-path test for owner answer 5 to the 10e-2b-4a report was right; (3) for 10e-2b-4c, see the owner note under Q-2026-10-17-124. Order: 10e-2b-4b-2 and 10e-2b-4c (with the Q-2026-10-17-124 and Q-2026-10-17-126 answers, in the order that fits best), 10g-2, 10h (with the Q-2026-10-17-120 answer and the post-closure put-back gap), then the Q-112 times sub-slice; stop before slice 11. Recorded in docs/010.

**Also answered with the 10e-2b-4b-2a report (2026-10-18).** (1) The implementer's reading of "relied on the lower count" is confirmed: a forfeiture recorded while the recovery charge stood lower than it stands after the restoration blocks the restoration, also when that forfeiture would have passed without the lower count. Fail closed: staff reverse the forfeiture first. (2) The three design changes of 10e-2b-4b-2a that the reviewers confirmed are accepted: the 40001 refusal after the Deposit lock wait (a recovery charge of that Pet Deposit stands lower now than at the forfeiture's time), the structural rule for a recovery charge's first billing, and the 40001 refusal when a recovery charge of that Pet Deposit was first issued after the forfeiture's time. (3) The new known limit (after closure, two active forfeitures of one Pet Deposit that both relied on the lower count) stays on the slice 12 list; slice 12 looks for a small safe fix and writes a question first if the fix changes who pays or how much. (4) The slice 11 notes are kept (clear messages for these refusals; 40001 shown as "try again"). Order: 10e-2b-4b-2b, 10e-2b-4c (with the Q-2026-10-17-124 answers and the DL-009 note), 10g-2, 10h, then the Q-112 times sub-slice; stop before slice 11. Recorded in docs/010.

## Q-2026-10-18-127 — Sub-slice 10e-2b-4b-2b reviews: a Deposit funded by two Payments has no way out when one Payment bounces (blocks nothing; a known limit until you answer; nothing is built) (ANSWERED 2026-10-18: (a), and (d) until (a) is built; answer in docs/010)

Your answer 2 to Q-2026-10-11-81 kept a guard: a Payment's return is refused while a Deposit that Payment funded also holds another Payment's money and has a Refund that is not fully returned. That answer rested on "this cannot happen in normal use", because every Deposit then had one receipt. The new receipt writer (your answer to Q-2026-10-12-92) and your answer to Q-2026-10-17-124 point 3 (more Security Deposit receipts) make a Deposit funded by two or more Payments normal. The security reviewer of round 1 found the case.

**The case.** Example: a Pet Deposit of $200 takes $100 from Payment A and $100 from Payment B. A $150 Pet Refund-review Refund is paid; the Deposit holds $50. Payment A bounces. A's return is refused (the guard), and B's receipt reversal is refused while the Refund is not returned. Before closure the bounced Payment cannot be recorded as returned until the Refund's money comes back; then its return draft is accepted. The new test `test_a_deposit_funded_by_two_payments_keeps_the_shared_deposit_refusal` shows both.

**A deliberate path (review round 3, security).** One staff member with `payments.allocate` can put a bounced Payment into this state on purpose before its return is confirmed. Example: a Pet Deposit (required $200) takes $100 from Payment A, and a $100 Pet Refund-review Refund is paid (the Deposit holds $0). A bounces; its return would charge the $100 back to the Customer. Before that, staff record another $100 Payment C of the same Customer into the Pet Deposit (within the required amount). A's return is now refused (shared Deposit) and C's receipt cannot be reversed while the Refund is out, so the bounced $100 is not charged back until the Customer returns the Refund. It is a loss to the Property, never a second charge to the Customer, and the receipt is audited with its actor and reason.

**After closure it is wider (review round 2, security).** Every two-Payment Deposit is stuck after closure, with or without a Refund, and also after a Refund came back in full: the `RETURNED_PAYMENT` correction requires each Deposit the Payment funded to end empty ("A Deposit this Payment funded would still hold money after the return"), and the receipt correction has the same rule ("The Deposit would not end empty after this receipt correction"); until this writer only a hand-edited source reached them. Example: a Pet Deposit takes $50 from Payment A and $50 from Payment B; the pet noncompliance forfeiture keeps the $100 and the Settlement closes; A bounces. The ordinary return draft is refused (relied on by the closed Settlement) and the correction is refused (the Deposit would not end empty), so A stays RECEIVED and the books keep $50 that never arrived. The new test `test_after_closure_a_deposit_funded_by_two_payments_keeps_a_bounced_payment_received` shows it. While a return is refused, the bounced Payment's unused value (if any) can still be allocated, recorded into a Deposit, or become Credit or a Refund.

**Options.**
- (a) The return reverses A's receipt when the Deposit still holds at least A's amount; otherwise it first charges back only the shortfall (A's amount less what the Deposit holds) to the person who received the Refund, with the same recovery charge as today, and then reverses the receipt. In the first example: $50 is charged back to the Customer and the Deposit ends at $0; B's $100 stays paid out within the $150 Refund. After closure the `RETURNED_PAYMENT` correction does the same, and its "ends empty" rule (and the receipt correction's) becomes "ends holding only the other Payments' money"; money of A that the Settlement or a forfeiture already used is charged back or reversed by the existing correction rules. The existing correction reverses a funded Deposit's whole forfeiture (your answer to Q-2026-10-10-72 point 2), so in the $50 + $50 example B's forfeited $50 would no longer be kept; the sub-slice that builds (a) must keep B's share where the closed Settlement put it (forfeited or applied), and if that cannot be done without changing who keeps B's money, it is asked first. The pay-back count rules (your answers to Q-2026-10-17-122, Q-123 and Q-125) treat that recovery as today.
- (b) Keep the refusal as a known limit (docs/010 and the slice 12 list); staff wait for the Refund's money to come back, or fix it outside the system.
- (c) As an interim, fail-closed step: refuse a second funding Payment into a Deposit until (a) is built. Not recommended: it would undo your answer to Q-2026-10-17-124 point 3 (more Security Deposit receipts) and most of what this sub-slice builds: every later Security Deposit receipt from a new Payment (your answer to Q-2026-10-12-92, both Deposit types) and any Pet Deposit paid by more than one Payment.
- (d) A narrower interim step (review round 3, security): the receipt writer refuses a receipt into a Deposit that has a Refund not fully returned (`app.deposit_has_unresolved_refund`, 55000), as the receipt reversal already does. On a Lease's Deposit such a Refund exists before closure only as a Pet Refund-review Refund, so later Security Deposit receipts stay allowed. It closes the deliberate path above; it does not fix the after-closure case.
- **Recommendation: (a)**, and (d) until (a) is built, because the Refund was paid from the Deposit's pooled money, and only money that never existed (the shortfall) must be charged back; (a) extends your one-Payment rule to pooled Deposits, and (d) is a small fail-closed refusal that keeps the other receipts this sub-slice builds. It changes who pays in this case, so nothing is built before your answer; it would be its own sub-slice (the Payment return, the returned-Payment correction and the receipt correction), before go-live.

**What goes ahead.** Everything. 10e-2b-4b-2b is committed with the known limit and the two tests of today's refusals; 4c, 10g-2, 10h and the Q-112 times sub-slice do not depend on this answer.

**Owner answer (2026-10-18).** Option (a) and, until (a) is built, option (d). When one of two Payments that funded a Deposit bounces, charge back only the shortfall. Until that is built, refuse a receipt into a Deposit whose Refund is out. Recorded in docs/010. Placement (owner): (d) in one small sub-slice right after 10e-2b-4c, with the answer to Q-2026-10-18-128 and the owner's answer 3 to the 10e-2b-4b-2b report (below Q-2026-10-18-128); (a) where it fits best before slice 11.

## Q-2026-10-18-128 — Sub-slice 10e-2b-4b-2b reviews: a Payment confirmed for an Invoice can never fund a Deposit, also with value left over (blocks nothing; refused until you answer; nothing else is built) (ANSWERED 2026-10-18: (b); answer in docs/010)

Your rules: a Customer may designate the Invoice or Late-payment Charge a Payment is for (BR-PAY-024, BR-PAY-026), and the allocation check then refuses any other target (except a wrong-Unit move confirmed under `financial.approve`, BR-PAY-042). The round 1 security reviewer found that the new receipt writer did not read that designation: one staff member with `payments.allocate` could record a Payment confirmed for the Initial Rent Invoice as a Security Deposit receipt, so the Invoice stays owed and the unpaid-Initial ground could then let a termination keep that money. The writer now refuses (55000) every Payment confirmed for an Invoice or a Late-payment Charge (both round 2 reviewers confirmed this needed and safe; it only refuses).

**What it also refuses (round 2, independent).** The refusal covers the whole Payment, also the value left after its named Invoice is paid. Example: a Customer sends one $1,500 transfer naming the $500 Initial Rent Invoice, meant to cover the Invoice and $1,000 of the Security Deposit balance (both due within five days, DL-066). Staff allocate $500 to the Invoice; the $1,000 left can become Customer Credit (which never funds a Deposit, BR-CREDIT-004 and BR-PAY-019) or a Refund, but not the Deposit receipt. The Deposit stays short until the Customer pays again, or staff refund the $1,000 and record a new Payment.

**Options.**
- (a) Keep the full refusal (fail closed).
- (b) Allow a Deposit receipt from what is left of such a Payment once its named Invoice or Charge has nothing outstanding, under the same checks and locks the Credit path uses for leftover money (`app.assert_payment_excess_eligible`): the Payment's money first goes where the Customer named, and only the rest can fund a Deposit.
- **Recommendation: (b)**, because it follows the Customer's own designation first and then lets the rest serve the Deposit the Customer also owes, as the Credit rule already does for leftover money. It would be its own small sub-slice (a relaxing change of this writer, with tests); until your answer the full refusal stays.

**Also for your awareness (round 2 notes, nothing to decide now).** A Payment that names no Invoice can still be recorded by one staff member as a Deposit receipt while the Initial Rent Invoice is owed (staff choose where an undesignated Payment goes, BR-PAY-020 and BR-PAY-021); the slice 11 screen can warn. The designation is checked in this writer only: `app.create_reservation` and the receipt correction's writer do not read it (pre-existing); moving the check into the receipt table's Payment source trigger would cover every writer, but it is a table tightening that needs your approval (slice 12 list).

**What goes ahead.** Everything; nothing waits for this answer.

**Owner answer (2026-10-18).** Option (b). Once the Invoice a Payment names has nothing outstanding, what is left of that Payment may go into the Deposit. One transfer that pays the Initial Rent and the Deposit together is normal. Recorded in docs/010.

**Also answered with the 10e-2b-4b-2b report (2026-10-18).** (3) A receipt into a Deposit after a termination whose ground keeps that Deposit: refuse it. Money a Customer pays after such a termination must not be forfeited at once. Staff record it as a normal Payment, so it pays open Invoices or becomes Credit (DL-030, Q-2026-10-05-29). If this changes a committed test or conflicts with an approved rule, a question is written with a recommendation and the slice 11 warning is kept instead. (4) The Payment-intent refusal (the round 1 design change of 10e-2b-4b-2b) is accepted. (5) Keeping the test name `test_deposit_acl_uses_only_financial_command_role_and_withholds_receipt_recording` is fine, because its traceability entry is frozen and its checks are still true. (6) Accepted as built: a receipt dated when staff record it; a Pet Deposit receipt after the pet's recorded departure; a third-party Payment funding the tenant's Deposit, with the Refund going to the tenant. Order: 10e-2b-4c (with the Q-2026-10-17-124 answers and the DL-009 note), one small sub-slice for the Q-2026-10-18-127 option (d) refusal, this answer (b) and answer (3), then 10g-2, 10h (with the Q-2026-10-17-120 answer and the post-closure put-back gap), then the Q-112 times sub-slice; the Q-2026-10-18-127 option (a) shortfall charge-back where it fits best before slice 11; stop before slice 11. Recorded in docs/010.

## Q-2026-10-18-129 — Sub-slice 10e-2b-4c: a renewal Lease's Security Deposit (blocks only a renewal Lease's create; refused until you answer; nothing else waits) (ANSWERED 2026-10-18: (a); answer in docs/010)

Your answer (a) to Q-2026-10-17-124 point 1: staff create a walk-in Lease's Security Deposit with its required total. A renewal Lease (a Lease with a predecessor Lease) is also signed with no Reservation (DL-066: a renewal keeps the OCCUPIED Unit), so it looks like a walk-in Lease.

**What exists.** BR-DEP-004: every Lease has a required Security Deposit total. BR-DEP-005: the Security Deposit of a Reservation continues into its Lease, and the system must not refund it and collect it again or create a second Deposit. No rule says whether a renewal keeps its predecessor's Security Deposit. In the database a Deposit names one Lease, and that link cannot change once it is set, so the predecessor's Security Deposit stays on the predecessor Lease and its own Final Settlement settles it.

**Options.**
- (a) Keep the create refused for a renewal Lease ("A renewal Lease's Security Deposit is not created here", 55000) until a later slice decides how a predecessor's Security Deposit carries over into its renewal (a link from the renewal to the same Deposit, never a second Deposit for the same money).
- (b) Let staff create a new Security Deposit for the renewal, as for a walk-in Lease; the predecessor's Security Deposit is settled by the predecessor's Final Settlement (refunded or applied), and the Customer pays the renewal's Deposit again.
- **Recommendation: (a)**, because BR-DEP-005 says the same Security Deposit continues and is never refunded and collected again; (b) would make the Customer pay a second Deposit while the first one is still held.

**What goes ahead.** Everything; 4c is committed with the refusal (in the create and in the table's source check) and a test of both.

**Owner answer (2026-10-18).** Option (a). A renewal Lease's own Security Deposit stays refused until a later slice decides how the earlier Lease's Deposit carries over. Recorded in docs/010 and the plan (slice 12 list).

## Q-2026-10-18-130 — Sub-slice 10e-2b-4c reviews: three readers use the Security Deposit's first required total and ignore later adjustments (blocks nothing; a known limit until you answer; nothing is built) (ANSWERED 2026-10-18: (a), its own small sub-slice before 10g-2; answer in docs/010)

A Deposit's required total is its first amount plus every audited required-amount adjustment (`deposits.manage`; `app.deposit_snapshot`, BR-DEP-004). The receipt checks, the Deposit screens and the Final Settlement use that total. With your answers to Q-2026-10-17-124, adjustments become normal: staff enter a walk-in Lease's total and fix it later with an adjustment, and staff raise a Reservation's total before a second receipt ("enter it first"). The review round 1 reviewers (security should-fix 2, independent note 1) found three readers that still use only the first amount (the `required_usd_cents` column):

1. **The unpaid-Initial termination ground** (BR-LEASE-005, migration `20261005_70`): the ground is met when a Security Deposit of the Lease holds less than its first amount at the termination time. Example: staff create a walk-in Security Deposit of $600.00 by mistake and correct it the same day by a $300.00 decrease. The Customer pays the $300.00 and the Initial Rent. After the Start Date plus five days the ground still reads $300.00 < $600.00, so the Lease can be terminated as if the Deposit were unpaid, and a BR-LEASE-005 forfeiture (confirmed under `financial.approve`) can take the $300.00. An increase does the opposite: a real shortfall does not meet the ground.
2. **The old Reservation move-in** (migration `20260826_25`, only for Leases signed before migration `20261005_69`): it requires the received amount to equal the first amount, so after an increase the move-in is refused; it also counts a reversed receipt as received (review round 2, security note 4), so with $100.00 accepted and a reversed $400.00 second receipt it reads $500.00 and passes as fully paid while $100.00 is held. No money moves.
3. **The Reservation read API** (`reservation_api.py`, `deposit_required_usd_cents`): it shows the first amount, so after an increase the screen can show more received than required.

**Options.**
- (a) Use the required total in effect at the time each reader looks (the first amount plus the adjustments recorded by then) in all three: the ground compares the held value at the termination time with the total in effect at that time; the old move-in and the read API use the current total; and the old move-in counts only active receipts (a tightening of that old path). A small sub-slice before slice 11, with real-path tests.
- (b) Fix only the termination ground (1), which can lose a Customer's money; keep (2) and (3) as known limits for slice 11 and slice 12.
- (c) Keep all three as known limits.
- **Recommendation: (a)**, because BR-DEP-004 defines one required total, and a ground that terminates a Lease and keeps its Deposit must read the same total as every other check. It changes when the BR-LEASE-005 ground is met, so nothing is built before your answer.

**Also for your awareness (review round 2, both reviewers).** With 4c a walk-in Lease can meet the BR-LEASE-005 ground in two new ways, whatever you answer above: (i) staff may create its Security Deposit after the Start Date plus five days, and until its receipts are recorded the ground reads it as unpaid; (ii) until the Q-2026-10-18-128 answer (b) is built, a Customer who paid the Initial Rent and the Deposit in one Payment named for the Invoice cannot have the rest recorded into the Deposit, so the ground reads the Deposit as unpaid. No money leaves without a `financial.approve` forfeiture; the slice 11 termination screen can warn, and the Q-128 sub-slice comes next.

**What goes ahead.** Everything. 4c is committed with this known limit (slice 12 list until answered); none of the next sub-slices depends on it.

**Owner answer (2026-10-18).** Option (a). Fix all three places so they use the adjusted required total (the first amount plus the adjustments recorded by then): the unpaid-Initial ground, the old Reservation move-in (which also counts only active receipts) and the Reservation read API. Build it as its own small sub-slice before 10g-2. Recorded in docs/010.

**Also answered with the 10e-2b-4c report (2026-10-18).** (1) The implementer's reading is confirmed: for a Reservation, "enter the required total first" uses the existing required-amount adjustment (`deposits.manage`); no new command. (2) The three design changes of 10e-2b-4c that the reviewers confirmed are accepted: the Reservation outcome code, the cancellation, the expiration and the read API count only active receipts; the deferred source check refuses linking a Reservation's Deposit to a Lease that already has a walk-in Security Deposit; the create runs at READ COMMITTED only. (3) The known limit that one person could get around option (d) of Q-2026-10-18-127 by reversing a verified return is accepted; option (a) of Q-2026-10-18-127 closes it. Recorded in docs/010.

## Q-2026-10-18-131 — Sub-slice 10e-2b-4d: your answer 3 to the 10e-2b-4b-2b report changes a committed test (blocks only answer 3; the slice 11 warning stays until you answer; nothing of answer 3 is built) (ANSWERED 2026-10-18: (a); answer in docs/010)

Your answer 3: refuse a receipt into a Deposit after a termination whose ground keeps that Deposit; money a Customer pays after such a termination must not be forfeited at once, so staff record it as a normal Payment, which pays open Invoices or becomes Credit (DL-030, Q-2026-10-05-29). You asked for a question with a recommendation if this changes a committed test or conflicts with an approved rule, and to keep the slice 11 warning until then.

**What it changes.** The committed test `test_deposit_receipt_record_migration.py::test_on_a_terminated_lease_a_receipt_passes_until_closure_and_after_a_forfeiture_reversal` (10e-2b-4b-2b review round 1) uses a Lease terminated for pet noncompliance (BR-DEP-022: the Security Deposit and the Pet Deposit are non-refundable). It expects (1) a $50.00 Pet Deposit receipt after the termination to pass, and (2) the forfeited Security Deposit, once its forfeiture is reversed through the 6b draft, to take a $50.00 receipt. Under your answer both are refused, because the termination's ground (read by `app.lease_termination_forfeiture_rule`, the rule the Final Settlement and the forfeiture drafts use) still keeps both Deposits. I found no approved rule in conflict: BR-DEP-022 makes the applicable Deposits non-refundable through explicit disposition events, and says nothing about money paid after the termination.

**One point your answer does not decide.** After an approver reverses a forfeiture (the 6b draft, or the 10d correction after closure), the termination's ground is unchanged, so the Deposit is still one "whose ground keeps it". Should a later receipt into it pass?

**Options.**
- (a) Build your answer as written: the receipt writer refuses (55000) a receipt into a Deposit of a TERMINATED Lease whose termination ground keeps that Deposit type, also after a forfeiture reversal; both expectations of the committed test become refusals (the test is renamed under the standing rule); a TERMINATED Lease whose ground keeps no Deposit of that type still takes receipts until its Final Settlement closes.
- (b) As (a), but a Deposit whose forfeiture an approver reversed takes receipts again (the test's second expectation stays).
- (c) Keep receipts allowed, with the slice 11 warning only.
- **Recommendation: (a)**, because it follows your answer, and a forfeiture reversal corrects a forfeiture record, not the termination's ground; with (a) money paid after such a termination always pays open Invoices or becomes Credit first.

**What goes ahead.** Everything else of 10e-2b-4d (your answers 1, option (d), and 2); answer 3 is built at the next sub-slice boundary after your answer.

**Also from the 10e-2b-4d review round 1 (independent should-fix 3).** Answer 3 changes three more committed tests of the same module, all on a pet noncompliance termination: `test_a_receipt_makes_a_pending_forfeiture_draft_stale` (a $30.00 receipt after the termination makes a pending forfeiture draft stale; under (a) or (b) that scenario can no longer be reached through the writer at all, because a forfeiture draft exists only under a ground that keeps the Deposit, so the test would need another set-up or would lose that check: your decision), the second half of `test_a_closure_committed_while_the_writer_waits_is_read_after_the_deposit_lock` (a Pet receipt that makes the closing confirm stale) and `test_after_closure_a_deposit_funded_by_two_payments_keeps_a_bounced_payment_received` (its set-up records two Pet receipts after the termination). Two more tests may see another refusal message, depending on where the new refusal sits (the active-forfeiture assertion and the forfeiture-wait test).

**Owner answer (2026-10-18).** Option (a). Build answer 3 as written, also after a forfeiture reversal. The four committed tests may change as the standing rule allows. The test whose scenario can no longer be reached through the writer must now assert the refusal. If a reviewer confirms that its other checks are still worth keeping, keep them with a hand-built set-up. Name each changed test in the report. Recorded in docs/010; built in 10e-2b-4d.

## Q-2026-10-18-132 — Sub-slice 10e-2b-4d stopped after review round 1: P1 failed two tests outside the sub-slice with the known `LockNotAvailable` (blocks the 4d commit; recommendation (a)) (ANSWERED 2026-10-18: (b), a standing run rule; answer in docs/010)

**What happened.** The full PostgreSQL run P1 of 10e-2b-4d: 2 failed, 2,304 passed. Both failures are `test_refund_migration.py::test_usd_refund_correction_rejects_unverified_or_inconsistent_value` (cases `changes2` and `changes4`): `LockNotAvailable` on `app.invoice_lines` from the `NOWAIT` lock in `app.assert_payment_excess_eligible`, reached through `app.validate_general_refund_source` by the test's direct Refund insert. That module is listed 169th in `scripts/database-test.sh` and runs before every module this sub-slice changes (the revision-string modules only assert the head revision); no 4d change touches its path. It is the known intermittent failure of DL-067 (Q-2026-10-05-26, Q-2026-10-09-62, Q-2026-10-13-102); this test is not yet on the slice 12 list. The takeover's stop rule applies (a test that passed before fails for a cause outside the sub-slice), so I stopped: 4d is not committed (code, tests, docs/004, docs/005 and traceability stay in the working tree); its plan design, Q-2026-10-18-131, this question, ops/NOW.md and the review record are committed. T1 (133) and U1 (3,866) passed.

**Review round 1 (both reviewers; no blocker; nothing fixed yet; record ops/reviews/V1-056-slice-10e-2b-4d-receipt-leftover-and-refund-out.md, with every set-up).**
1. Lock order (both, should-fix): I placed the excess check before the Payment lock; it then holds SHARE on twelve obligation tables while it waits for the Payment, Reservation and Deposit locks, so it can deadlock with the allocation post or the Payment return confirm, and it blocks those writers in every Property while it waits. Fix: call it after the Deposit lock, as the Credit path does (Payment lock first; `NOWAIT` never waits).
2. Your DL-067 decision (independent should-fix, security note): a service whose command reaches that check replays it after 55P03, at most three times, then answers "unavailable". Fix: the same bounded retry in the Deposit service's receipt command, "unavailable" after the last attempt; the 55P03-as-conflict mapping I added is withdrawn.
3. Q-2026-10-18-131 named only one of the committed tests answer 3 changes (fixed above).
4. docs/010 entries and two real-path lock tests (the reviewers' set-ups).
5. A known limit of option (d) to record: one person with `refunds.correct`, `refunds.corrections.reverse` and `payments.allocate` can lift the refusal with a verified return, record the second receipt and then reverse the return (fabricated evidence; audited); option (a) of Q-127 closes it. Two designation dodges inherited from the Credit check (a temporary allocation of another Payment; a designation to a DRAFT Invoice) end in a state reachable with an undesignated Payment (slice 11 warning).

**Options.**
- (a) I make fixes 1 to 4, record the limits of 5, then run the checks (each in its own call), the targeted tests, U2, the migration-only check, the read-only search and P2; if P2 fails only in the known `LockNotAvailable` tests of `test_refund_migration.py`, I rerun only those failing tests once under `caffeinate -dims` (as your answer to Q-2026-10-13-102): if they pass, I record it and continue; if they fail again, I stop. Then review round 2 and the commit. `test_usd_refund_correction_rejects_unverified_or_inconsistent_value` joins the slice 12 `LockNotAvailable` item.
- (b) As (a), and the rerun-once rule for the known `LockNotAvailable` tests of `test_refund_migration.py` becomes a standing run rule for later sub-slices, so this known failure does not stop each one.
- (c) Something else.
- **Recommendation: (b)**, because the failure is the known DL-067 mechanism in a module no V1-056 sub-slice touches, it has now stopped three sub-slices, and the rerun-once rule still stops the work if it fails twice.

**What goes ahead.** Nothing; I stopped as the takeover says. Next after your answer: finish 10e-2b-4d, then 10g-2, 10h, the Q-112 times sub-slice and the Q-127 (a) shortfall charge-back; stop before slice 11.

**Owner answer (2026-10-18).** Option (b). Finish 4d. New standing rule (ops/V1_055_RUN_RULES.md): when a full run fails only with the known DL-067 `LockNotAvailable` failure, in a module the sub-slice does not change, rerun only those failing tests once and save that log. If they pass, record both runs and go on. If they fail again, or any other test fails, stop and tell the owner. The root cause stays on the slice 12 list. Order: finish 10e-2b-4d (the round 1 fixes and the Q-2026-10-18-131 answer), then 10e-2b-4e (the Q-2026-10-18-127 option (a) shortfall charge-back, replacing option (d)), the Q-2026-10-18-130 sub-slice, 10g-2, 10h (with the Q-2026-10-17-120 answer and the post-closure put-back gap), then the Q-112 times sub-slice; stop before slice 11. Recorded in docs/010.

## Q-2026-10-18-133 — Sub-slice 10e-2b-4d review round 2: a receipt recorded beside an uncommitted termination is not refused (blocks nothing; a known limit until you answer; nothing is built) (ANSWERED 2026-10-18: (a), built with the Q-112 times sub-slice; answer in docs/010)

Your answer 3 (Q-2026-10-18-131 (a)): a receipt into a Deposit after a termination whose ground keeps that Deposit is refused. The writer reads the Lease status after its Payment and Deposit locks, but the termination command locks the Lease and Unit rows, never the Lease's Deposits. Both round 2 reviewers found two edges:

1. **A termination still being saved.** If staff record a receipt in the same moment as another staff member saves the termination, the receipt does not wait, reads the Lease as signed and is recorded, dated after the termination (a window of milliseconds, two people on the same Lease). The test `test_deposit_receipt_leftover_migration.py::test_a_receipt_beside_an_uncommitted_termination_is_recorded_known_limit` shows it.
2. **A termination dated earlier than its entry.** The termination time comes from the screen (one of the Q-2026-10-14-112 times); receipts recorded between that time and the entry stay in the Deposit.

In both cases no money leaves without a `financial.approve` forfeiture, and the receipt can be reversed.

**Options.**
- (a) Close edge 1 with a small hardening: after its Lease lock, the termination command also locks each Deposit of the Lease (in id order; the same Lease-then-Deposit order the closing confirm uses), so a receipt waiting for it reads the termination and is refused. Edge 2 is decided with the Q-112 times sub-slice, which reads the termination time case by case (a time that means the moment staff save the action comes from the database clock). Built in the Q-112 times sub-slice, with a test.
- (b) Keep both as known limits (slice 12 list), with a slice 11 screen warning.
- **Recommendation: (a)**, because your answer says money paid after such a termination must not be forfeited at once, and the lock order is the one every Deposit writer already uses; it only adds a wait and changes no amount.

**What goes ahead.** Everything; 10e-2b-4d is committed with this known limit and its test.

**Owner answer (2026-10-18).** Option (a). A termination also locks the Lease's Deposits, so a receipt cannot slip in while a termination is saved or between a back-dated termination time and its entry. Build it with the Q-112 times sub-slice. Keep the known-limit test `test_a_receipt_beside_an_uncommitted_termination_is_recorded_known_limit` until then. Recorded in docs/010.

**Also answered with the 10e-2b-4d report (2026-10-18).** Money received before a termination but recorded after it is refused into a Deposit that the termination's ground keeps, and becomes a normal Payment: accepted. It pays open Invoices or becomes Credit, as the owner's answer 3 to the 10e-2b-4b-2b report said (DL-030, Q-2026-10-05-29). Recorded in docs/010. Order: 10e-2b-4e (the Q-2026-10-18-127 option (a) shortfall charge-back, replacing option (d); pre-code design first, may be split), 10e-2b-4f (the Q-2026-10-18-130 answer), 10g-2, 10h (with the Q-2026-10-17-120 answer and the post-closure put-back gap), then the Q-112 times sub-slice (with this answer); stop before slice 11.

## Q-2026-10-18-134 — Sub-slice 10e-2b-4e: where the shortfall of a shared Deposit comes back from after closure, and which person pays when two people received its Refunds (blocks only 10e-2b-4e-2 and the two-recipient case; nothing of them is built before your answer) (ANSWERED 2026-10-18: point 1 (a), point 2 (a); answer in docs/010)

Your answer (a) to Q-2026-10-18-127: when one of two Payments that funded a Deposit bounces, the return reverses its receipt when the Deposit still holds at least its amount, and otherwise first charges back only the shortfall (its amount less what the Deposit holds); after closure the `RETURNED_PAYMENT` correction and the receipt correction do the same, and the closed Settlement's use of the other Payments' money stays where it is, "or a question is written first". The pre-code design (plan, "10e-2b-4e pre-code design") splits the work: 10e-2b-4e-1 builds the return before closure now; 10e-2b-4e-2 builds the two corrections after closure. Two points are not decided by the rules.

**Point 1: after closure, which use gives the shortfall back.** Before closure a Lease's Deposit has only one kind of use (its Refunds), so the shortfall is charged back to the person who received the Refund. After closure the Final Settlement has usually used all of the Deposit's money in up to three ways: a forfeiture the Property keeps (BR-DEP-022, BR-DEP-023), Deposit applications that paid the Customer's debt (DL-032), and a Settlement Refund. The money is pooled, so no record says which use was the bounced Payment's money.

Example: a Security Deposit takes $100 from Payment A and $100 from Payment B. At closure the Settlement applies $150 to the Customer's debt and refunds $50 to the Customer. A bounces: the Deposit holds $0, so the shortfall is $100.

- (a) Undo the newest uses first, up to the shortfall: first the Settlement Refund (charged back to its recipient, as today), then the Deposit applications, newest first (the debt comes back on the obligation's Customer, BR-SETTLE-016), then the forfeiture (the Property keeps less; nobody is charged). In the example: the $50 Refund is charged back and $50 of the applications is reversed, so the Customer owes $100 again, and B's $100 stays applied to the debt.
- (b) First reduce what the Property keeps (the forfeiture), then the Deposit applications, then the Refund. In the example the Customer owes the same $100 again, but through other records: $100 of the applications is reversed and the $50 Refund is not charged back; with a forfeited Deposit (A $50 and B $50, all kept, A bounces), (a) and (b) both keep only B's $50, because the forfeiture is the only use.
- (c) Share the shortfall over every use in proportion to its amount.
- **Recommendation: (a)**, because it is the same "newest first" rule as your answers to Q-2026-10-13-100, Q-2026-10-13-107 and Q-2026-10-14-111, and the same as 10e-2b-4e-1 uses for several Refunds before closure; the last money paid out is the money that was never there. A part of a forfeiture or of an application is undone by reversing the record and writing its kept part again, linked to the correction (the 4e-2 pre-code design checks the existing writers first, and asks again if that is not possible without changing who keeps B's money).

**Point 2: a shared Deposit whose unpaid-back Refunds went to two different people.** Before closure the shortfall is charged back newest first among the Deposit's Refunds that are not fully returned. Where they all went to one person, the order changes nothing that person owes. Where they went to two people (for example a Pet Refund-review Refund to the Primary Tenant and a later one to an agreed Signer, BR-REFUND-015), the order decides who pays.

- (a) Newest first in every case: the recipient of the newest Refund pays first, each Refund at most its net.
- (b) Share the shortfall in proportion to each Refund's net.
- (c) Keep refusing that case (a known limit).
- **Recommendation: (a)**, for the same reason as point 1. Until you answer, 10e-2b-4e-1 keeps today's refusal for that case only ("A Deposit this Payment funded also holds another Payment's money and has a Refund that is not fully returned"), while its shortfall is above 0; every one-recipient case is built. Review round 2 (both reviewers): option (d) itself stays unchanged until 10e-2b-4e-2, because your answer kept it "until (a) is built" and (a) includes the corrections after closure. Even with (d), a shared Deposit can still reach unreturned Refunds to two people, and then its bounced Payment's return stays refused until you answer: by a second receipt recorded before both Refunds, by a Refund draft to the second person that is pending when the receipt is recorded and confirmed after it, or by reversing a verified return after the receipt (a known limit; nothing wrong is written: the bounced Payment stays RECEIVED).

**What goes ahead.** 10e-2b-4e-1 (the return before closure; option (d) stays until 10e-2b-4e-2), 10e-2b-4f, 10g-2, 10h and the Q-112 times sub-slice do not depend on this answer. 10e-2b-4e-2 (with the end of option (d)) is built at the next sub-slice boundary after your answer.

**Owner answer (2026-10-18).** Point 1: option (a), newest first. After closure, the shortfall is given back first from the Settlement's Refund, then from its Deposit applications, then from the forfeiture. Point 2: option (a), newest first. When the unreturned Refunds went to two people, the newest Refund's recipient pays first. Recorded in docs/010.

**Also answered with the 10e-2b-4e-1 report (2026-10-18).** (1) The two design changes of 10e-2b-4e-1 are accepted: the new internal `app.payment_return_draft_source` read by the `PAYMENT_RETURN` recorder and confirm, and keeping option (d) unchanged until 10e-2b-4e-2 is built. (2) Rebuilding `ops/traceability.json` from HEAD was the right fix; never re-serialize a whole file with a script; use exact-text edits or appends only (ops/V1_055_RUN_RULES.md). (3) Catalog dumps and migration-only checks are saved in `~/Development/prm-run-logs/` too, one file per attempt (ops/V1_055_RUN_RULES.md). (4) Targeted run T1 of 10e-2b-4e-1 again started from `backend/`: before every script run, check that the working directory is the repository root, and call the script by its absolute path (ops/V1_055_RUN_RULES.md). Order: 10e-2b-4e-2 (the two corrections after closure, with these answers; it ends option (d)), 10e-2b-4f (the Q-2026-10-18-130 answer), 10g-2, 10h (with the Q-2026-10-17-120 answer and the post-closure put-back gap), then the Q-112 times sub-slice (with the Q-2026-10-18-133 answer); stop before slice 11. A large sub-slice may be split into smaller ones that each end in a commit. Recorded in docs/010.

## Q-2026-10-18-135 — Sub-slice 10e-2b-4e-2a review round 1: newest first can charge the Customer back pay-back money that a forfeiture keeps (blocks only that case; refused until you answer; nothing else waits) (ANSWERED 2026-10-18: (a); answer in docs/010)

Your answers (a) to Q-2026-10-18-134: after closure the shortfall of a shared Deposit comes back newest first, first from the Settlement's Refund, then its Deposit applications, then the forfeiture. Your answers to Q-2026-10-10-73, Q-2026-10-17-122 and Q-2026-10-17-123: returned Pet Refund-review money is the Customer's pay-back money, no forfeiture may take it, and the Customer must never both pay money back and lose the same money to a forfeiture. The security reviewer of round 1 found one case where the two rules meet.

**The case (the reviewer's set-up, now a test).** A Pet Deposit takes $50 from Payment A. A $40 Pet Refund-review Refund is paid and comes back in full, so $40 of it is the Customer's pay-back money. After the $40 comes back, Payment B adds $50 (the required total raised); then the Lease ends for pet noncompliance; the forfeiture keeps the $60 beyond the pay-back money; the Final Settlement refunds the $40 pay-back money to the Customer. Then A bounces: the Deposit holds $0, so the shortfall is $50. Newest first charges the Settlement's $40 Refund back to the Customer and reduces the forfeiture by $10 (it keeps $50). The Customer then owes $40 for the pay-back money, and the Property keeps all of B's $50: the pay-back money is lost to the forfeiture. If the shortfall came from the forfeiture first, the Property would keep $10 and the Customer would keep the $40.

**Options.**
- (a) For a Deposit with pay-back money, the shortfall comes from the forfeiture first (the Property keeps less), and only what is left of the shortfall comes newest first from the Refunds and applications; no part of the Customer's pay-back money stays forfeited. In the example: the forfeiture is reduced by $50 and keeps $10; nobody is charged.
- (b) Keep newest first, and also give the Customer back the pay-back money the forfeiture would keep (the forfeiture is reduced further, by $40, and the Deposit then holds $40 that the correction refunds or applies under DL-032). In the example: the Customer is charged $40 and receives $40 back; the forfeiture keeps $10.
- (c) Keep it refused (a known limit; slice 12 list).
- **Recommendation: (a)**, because returned money belongs to the Customer and the bounced money then comes out of what the Property kept, with no charge and no second Refund; (b) reaches the same end by a charge and a Refund of the same $40.

**What happens now.** Until you answer, the correction refuses this case before anything is written (55000, "A Deposit this Payment funded holds the Customer's pay-back money beside a forfeiture; this correction cannot return the Payment"), and the confirm checks the same after its writes. The refusal also covers a plan that gives back only from the forfeiture but would still leave the pay-back money forfeited (for example after a correction recorded the $40 Settlement Refund as returned: the Deposit holds $40, the shortfall is $10, and the forfeiture would keep $50). It needs a Pet Deposit funded by two Payments, returned Pet Refund-review money, a forfeiture and a bounce after closure. The bounced Payment stays RECEIVED; nothing wrong is written.

**What goes ahead.** Everything: 10e-2b-4e-2a is committed with the refusal; 10e-2b-4e-2b, 10e-2b-4f, 10g-2, 10h and the Q-112 times sub-slice do not depend on this answer.

**Owner answer (2026-10-18).** Option (a). For a Deposit that holds pay-back money, the shortfall comes from the forfeiture first. The Property must never keep the Customer's pay-back money. In the example the forfeiture keeps $10 and nobody is charged. Build it in 10e-2b-4e-2b, or as its own small sub-slice right before 10e-2b-4e-2b, whichever fits best. Recorded in docs/010. Placement (implementer, "whichever fits best"): 10e-2b-4e-2b is split; 10e-2b-4e-2b-1 builds this answer first, in the `RETURNED_PAYMENT` correction's shared-Deposit plan that 10e-2b-4e-2a built, and 10e-2b-4e-2b-2 builds the receipt correction of a shared Deposit and ends option (d), so the receipt correction uses the final plan from the start.

**Also answered with the 10e-2b-4e-2a report (2026-10-18).** (1) The implementer's reading of "newest first" by time across every use in force is accepted. 10e-2b-4e-2b adds a test of the case the reading names: a Pet Refund-review Refund paid before closure comes after the Settlement's applications (built in 10e-2b-4e-2b-1, which changes the same plan). (2) The round 1 blocker fix of the security reviewer (B1, a fail-closed refusal), confirmed needed and safe by both round 2 reviewers, is accepted; so are the split of 10e-2b-4e-2 into 10e-2b-4e-2a and 10e-2b-4e-2b and the new known limit on the slice 12 list (a shared Deposit whose plan would write an application's kept part while a forfeiture of that Deposit stays active). Order: this answer and 10e-2b-4e-2b (the receipt correction of a shared Deposit; it ends option (d); pre-code design first), 10e-2b-4f (the Q-2026-10-18-130 answer), 10g-2, 10h (with the Q-2026-10-17-120 answer and the post-closure put-back gap), then the Q-112 times sub-slice (with the Q-2026-10-18-133 answer); stop before slice 11. Recorded in docs/010.

**Also answered with the 10e-2b-4e-2b-1 report (2026-10-18).** (1) Confirmed: the forfeiture may give back more than the shortfall, so that no pay-back money stays forfeited. In the implementer's example (a return-only correction brought the $40 Settlement Refund back; the Deposit holds $40, the shortfall is $10) the forfeiture gives back $50 and keeps $10, and the Deposit holds the $40 until staff refund it with a `HELD_VALUE_REFUND` correction. Slice 11 note: the screens must show Deposit money that is held and waiting to be refunded, so staff do not forget it. (2) Confirmed: a Deposit counts as having pay-back money under the old refusal's condition (a pay-back count without payouts above 0 beside an active forfeiture), including a Pet Refund-review Refund that has not come back yet. Recorded in docs/010.

## Q-2026-10-18-136 — Sub-slice 10e-2b-4e-2b-2a stopped after review round 3: one text should-fix inside the migration (blocks the 2a commit; recommendation (a)) (ANSWERED 2026-10-18: (a), and a standing run rule; answer in docs/010)

**Where it stands.** Sub-slice 10e-2b-4e-2b-2a (the receipt correction of a Deposit funded by two or more Payments gives back only the shortfall, your answer (a) to Q-2026-10-18-127; migration `20270103_160`) is built and green: T3 123, U4 3,866 and P3 2,347 passed after the last code and test change. It is NOT committed; every file is in the working tree. Record: ops/reviews/V1-056-slice-10e-2b-4e-2b-2a-receipt-correction-shared-deposit.md. Rounds 1 and 2 had no blocker (their should-fix items were tests and fail-closed refusals, fixed under the round-3 rule). Round 3: security clean; independent one should-fix, text only.

**The should-fix.** Round 2 added a refusal at record time: a right receipt's plan with a Customer Credit step beside a Deposit application the correction writes again would fail at every confirm, so it is refused at once (55000). Its message tells staff "apply the Credit to the open debt first". The reviewer showed that this hint often cannot be followed: the open debt the plan must pay is the debt this same correction brings back, so before the correction the Customer may owe nothing that the Credit could pay. The refusal is right; only the hint is wrong. The message is a string inside the migration, and your round-3 text rule (2026-10-16) excludes any migration change, so I stopped.

**Options.**
- (a) A one-time exception: change the message to "...; refund or apply the Customer's Credit first, or correct the receipt without new receipts" (the migration string, the test constant, docs/004, docs/010, the plan's slice 12 item and the record), then the checks (each in its own call, formatter first), the migration-only check, the targeted tests, the full unit run, the read-only search and the full PostgreSQL run, all under `caffeinate -dims`, and the commit without a round 4. Nothing else changes; the test already asserts the exact message.
- (b) As (a), with a round 4 (independent and security) before the commit.
- (c) Keep the message; correct only the docs, the plan and the record.

**Recommendation: (a)**, because it changes only the words of a refusal that both round 3 reviewers confirmed is exactly right, and the test that pins the message is already built and green.

**What goes ahead.** Nothing in the order until this is answered: 10e-2b-4e-2b-2b (the end of option (d)) changes the receipt writer that this sub-slice's tests do not touch, but its committed test changes build on this sub-slice's migration number. Context of this session is about 64%, so the next step runs in a fresh session after your answer.

**Owner answer (2026-10-18).** Option (a). Change the Credit refusal message to "refund or apply the Customer's Credit first, or correct the receipt without new receipts" in the migration, the test constant and the docs. Then rerun the checks, the migration-only check, the targeted tests, the unit suite and the full PostgreSQL run, and commit 2a without a round 4. Recorded in docs/010.

**Also answered with the 10e-2b-4e-2b-2a report (2026-10-18).** (1) New standing rule (ops/V1_055_RUN_RULES.md): a round 3 finding that changes only a user-facing message string, in code or in an uncommitted migration, counts as a text fix under the round-3 text rule. Conditions: no logic, condition, error code or amount changes; every test constant for that message changes with it; and the full checks and runs above pass before the commit. A message in a committed migration is never edited. (2) The split into 2a and 2b, and the five fail-closed refusals added during the reviews, are accepted as known limits on the slice 12 list. Order: commit 2a, then 10e-2b-4e-2b-2b (the end of option (d)), 10e-2b-4f (the Q-2026-10-18-130 answer), 10g-2, 10h (with the Q-2026-10-17-120 answer and the post-closure put-back gap), then the Q-112 times sub-slice (with the Q-2026-10-18-133 answer); stop before slice 11. A large sub-slice may be split into smaller ones that each end in a commit. Recorded in docs/010.

## Q-2026-10-19-137 — Sub-slice 10e-2b-4e-2b-2b review round 1: a receipt recorded while a Pet Refund is out cannot be reversed until the Refund comes back (blocks the slice 11 receipt route and screen until you answer; a known limit until then; nothing is built; recommendation (a)) (ANSWERED 2026-10-19: (a), with the narrowing of rounds 2 and 3, a small relaxing sub-slice before 10e-2b-4f; answer in docs/010)

**Where it stands.** Sub-slice 10e-2b-4e-2b-2b ends option (d), as your answer to Q-2026-10-18-127 says ("(d) until (a) is built"; (a) is now built in the return and in both corrections). Both round 1 reviewers confirmed that ending (d) creates no stuck bounced Payment and no state that cannot also be reached with the receipts in the other order. The security reviewer found one practical effect (should-fix 1).

**The case.** The receipt reversal (the 8r draft: `deposits.correct` records, `financial.approve` confirms) is refused while the Deposit has a Refund that is not fully returned ("Deposit receipt has active dependent financial history"). Before this sub-slice, (d) also refused a receipt into such a Deposit, so a receipt recorded by mistake could always be reversed before a Refund was paid from it. Now one staff member with `payments.allocate` can record a Payment into a Pet Deposit whose Pet Refund-review Refund is out, and nobody can reverse that receipt until the Customer returns the Refund in full, the Payment itself bounces, or the Final Settlement uses the money (DL-032); after closure the receipt correction fixes it.

**Example.** A Pet Deposit (required $200.00) takes $100.00 from Payment A, and a $100.00 Pet Refund-review Refund is paid (the Deposit holds $0). The Customer then pays $100.00 by transfer C, which names no Invoice, for the next Rent Invoice, and staff record C as a Pet Deposit receipt by mistake. The reversal of C's receipt is refused, so the Rent Invoice stays owed until the Refund comes back or the Lease is settled. The receipt is audited with its actor and reason. The test `test_deposit_receipt_refund_out_migration.py::test_a_receipt_recorded_while_a_refund_is_out_is_reversed_only_after_the_refund_returns` shows it, also after a partial return. The mistake needs a Payment that names nothing, or one whose named Invoice or Late-payment Charge is already paid; a Payment confirmed for an owed Invoice is refused by the writer (23514, the excess check).

**What it can lead to (review round 2, security).** The Rent stays owed, so Late-payment Charges, the 20-day Warning Notice and the 30-day Serious Nonpayment Default (DL-054) can follow, and a termination on that default keeps the whole Security Deposit (BR-LEASE-028). If the Lease is terminated for pet noncompliance (BR-DEP-022), the Final Settlement does not refund C's money: what the Pet Deposit holds above the pay-back money must be forfeited (a two-person draft), so C's $100.00 can be forfeited while the Rent is still owed; after closure the receipt correction then needs a forfeiture reversal correction first. Before closure the ways out are the Customer returning the Refund in full, C's own return if C really bounced, the Final Settlement, or a second Pet Refund-review Refund under the same review (two people; it pays the Deposit owner, not necessarily C's payer). Staff must never record a verified return or a Payment return that did not happen only to free the receipt; the slice 11 screen text will not suggest it. Today no route reaches the receipt writer (`PostgresDepositService.record_receipt` has no HTTP caller yet), so the limit can arise only once slice 11 builds the receipt route.

**Options.**
- (a) A small relaxing sub-slice before slice 11: the receipt reversal also passes for a receipt recorded after every Refund of that Deposit that is not fully returned (strictly later than each such Refund's processing time), when no return or correction of another Payment of that Deposit was confirmed after this receipt (review round 2, independent should-fix 1: without this condition, in A 10,000, a 10,000 Refund, C 10,000, A's return charging nothing, then D 10,000, C's reversal would pass and take away the money A's no-charge return relied on), and when the Deposit's held history stays at 0 or more (the existing 23514 check); the other refusals (an active forfeiture or Deposit application, a waiting draft, a closed Settlement) stay. In the example, C's receipt is reversed, the Deposit holds $0 again and C's $100.00 can pay the Rent Invoice; a later bounce of A still charges back A's whole shortfall. The security reviewer of round 2 found no case where this lets money leave without an approver, charges a Customer twice or lets the Property keep money it should not. For the build (review round 3, security note 1): state the second condition by its effect, that the Deposit's held value stayed at or above the receipt's amount at every balance event after the receipt, checked at the confirm under the Deposit lock; it then also covers a verified-return reversal that relied on the receipt's money (A 10,000; a 10,000 Refund verified returned in full; C 10,000; A's receipt reversed; the verified return reversed; D 10,000), and any later way money leaves.
- (b) Keep it as a known limit (docs/004 DB-DEP-002, the slice 12 list), with a slice 11 screen warning before such a receipt is saved.
- (c) Bring back a refusal only for this case: refuse a receipt into a Deposit whose Refund is out unless staff confirm a warning in the request. Not recommended: it adds an input field and does not help when the mistake is made anyway.
- **Recommendation: (a)**, because a mistake should be fixable with the existing two-person reversal, and with the narrowing above the rule stays safe; a receipt recorded while a Pet Refund draft is waiting and confirmed after it stays stuck, as with the receipts first (the Refund's approver is the control).

**What goes ahead.** Everything in slice 10; 10e-2b-4e-2b-2b is committed with this known limit and its test. The slice 11 receipt route and its screen (API-040) wait for your answer and, if it is (a), until (a) is built (review round 2, security: a screen warning alone is a weak control; wording of review round 3).

**Owner answer (2026-10-19).** Option (a). Build a small relaxing sub-slice that lets the two-person receipt reversal undo a receipt recorded into a Pet Deposit whose Pet Refund-review Refund is out, with the narrowing that review rounds 2 and 3 found (the receipt is strictly later than every Refund of that Deposit that is not fully returned; the Deposit's held value stayed at or above the receipt's amount at every balance event after the receipt, checked at the confirm under the Deposit lock; the held history stays at 0 or more; every other refusal stays). A wrong receipt must always be fixable by two people. Build it next, before 10e-2b-4f. The slice 11 receipt route and screen wait until it is built. Recorded in docs/010. Placement (implementer): sub-slice 10e-2b-4e-2b-3, right after 10e-2b-4e-2b-2b, because it relaxes the receipt reversal that the end of option (d) left as the only refusal.

**Also answered with the 10e-2b-4e-2b-2b report (2026-10-19).** (2) Treating the one-line addition of a new test module to `scripts/database-test.sh` as part of that module is right. New run rule (ops/V1_055_RUN_RULES.md): adding a new test module to the full-run list in `scripts/database-test.sh` is part of that module and needs no separate mention in the review record. (3) The 10e-2b-4e-2b-2b test renames and the rolled-back writer call in `test_two_recipients_pay_the_shortfall_newest_refund_first` are accepted. Order: 10e-2b-4e-2b-3 (this answer), 10e-2b-4f (the Q-2026-10-18-130 answer; pre-code design first), 10g-2, 10h (with the Q-2026-10-17-120 answer and the post-closure put-back gap), then the Q-112 times sub-slice (with the Q-2026-10-18-133 answer); stop before slice 11. A large sub-slice may be split into smaller ones that each end in a commit. Recorded in docs/010.

**Also answered with the 10e-2b-4e-2b-3 report (2026-10-19).** (1) Leave the committed migration `20270105_162` as it is: its SQL comment and docs/004 have the right wording ("since this transaction began"), and the review record names the difference from its docstring ("confirmed in this transaction"). A committed migration is never edited for text. (2) "Two people": DL-069 stays as it is. In V1, one person who holds both `deposits.correct` and `financial.approve` may record and confirm the reversal alone, the same as other corrections; the record keeps who did each step. The next time `test_deposit_receipt_refund_out_migration.py` is touched, rename `test_a_receipt_recorded_while_a_refund_is_out_is_reversed_by_two_people` to `test_a_receipt_recorded_while_a_refund_is_out_is_reversed_by_a_confirmed_draft`, and new docs and test names say "a confirmed reversal draft" instead of "two people". (3) The two new slice 12 limits are accepted: a receipt whose money a later event took stays unreversible before closure, also after that event is undone; and events at the same time are summed together. (4) Run-rule reminder: run the import sort in its own tool call, never together with a format, lint or type check. Order: 10e-2b-4f (the Q-2026-10-18-130 answer; pre-code design first), 10g-2, 10h (with the Q-2026-10-17-120 answer and the post-closure put-back gap), then the Q-112 times sub-slice (with the Q-2026-10-18-133 answer); stop before slice 11. Recorded in docs/010.

## Q-2026-10-19-138 — Sub-slice 10e-2b-4f review round 1: a required-total increase recorded after Lease Start plus five days meets the unpaid-Initial ground at once (blocks nothing; built as your answer (a) to Q-2026-10-18-130 says; a known limit until you answer) (ANSWERED 2026-10-19: (b), built in the Q-112 times sub-slice; answer in docs/010)

Your answer (a) to Q-2026-10-18-130: the unpaid-Initial termination ground (BR-LEASE-005) compares the Security Deposit's held value at the termination time with the required total in effect at that time (the first amount plus the adjustments recorded by then). Sub-slice 10e-2b-4f builds it. The security reviewer of round 1 found one effect that the question did not show.

**The case.** A Lease started more than five days ago. The Customer paid the Initial Rent and the whole $500.00 Security Deposit on time. A staff member with `deposits.manage` then records an increase of the required total, for example a correction of the signed terms to $600.00 (the command needs only a reason). From that moment the ground is met ($500.00 held is less than $600.00), so a staff member with `leases.terminate` can terminate the Lease for the unpaid Initial obligation at once, before the Customer has had any time to pay the $100.00. A forfeiture draft confirmed by a `financial.approve` holder can then keep the whole $500.00 held (BR-DEP-026: the Security Deposit is kept on this ground; the draft takes all the held money, not only the shortfall). Before this sub-slice no required-amount change could make a Security Deposit paid on time meet the ground, because the ground read only the first amount; only taking money out of the Deposit could (a receipt reversal or a Payment return, each confirmed under `financial.approve`). Now one `deposits.manage` command with a reason, which moves no money, is enough (corrected in review round 2, both reviewers). Every step is audited, and the money leaves only with a `financial.approve` confirm; under DL-069 one person may hold all the capabilities. The test `test_deposit_required_total_readers_migration.py::test_an_increase_counts_for_the_ground_from_its_record_time` shows today's result (a $10.00 increase).

**Options.**
- (a) Keep it as built. The slice 11 termination and forfeiture screens show each required-total adjustment recorded after Lease Start plus five days and the shortfall, so the person who terminates and the approver see it.
- (b) An increase counts for the ground only from the later of Lease Start plus five days and five days after it was recorded, the same five days DL-066 gives for the first total (review round 2, independent: so an increase recorded on Lease Start plus three days also gets five days); a decrease counts from its record, as built. This makes the ground harder to meet (a tightening of the ground), with a test.
- (c) An increase recorded after Lease Start plus five days never counts for the ground; a later shortfall is handled by another ground or as debt.

**Recommendation: (b)**, because the Customer then always has five days to pay any part of the Security Deposit before this ground can end the Lease, as DL-066 gives for the first total, and a correction made by staff alone cannot end a Lease the same day; (c) would let a corrected total never be enforced through this ground.

**Also for your awareness (security should-fix 2; a known limit until the Q-112 times sub-slice).** The termination time still comes from the staff device, so a termination entered after a decrease but dated before it reads the total from before the decrease and can meet the ground (shown by `test_a_termination_dated_before_a_decrease_reads_the_earlier_total_known_limit`). The Q-112 times sub-slice reads the termination time case by case and builds your answer to Q-2026-10-18-133 (a termination also locks the Lease's Deposits, which also closes the read of an adjustment being saved at the same moment, security note 3).

**What goes ahead.** Everything; 10e-2b-4f is committed as your answer (a) says, with this known limit on the slice 12 list.

**Owner answer (2026-10-19).** Option (b). An increase of the required Deposit total counts for the unpaid-Initial termination ground only from the later of Lease Start plus five days and five days after the increase was recorded. The Customer always gets five days to pay an increase. Build it inside the Q-112 times sub-slice, because that sub-slice already changes how the termination ground reads the total by time. If it makes that sub-slice too large, split it into its own small sub-slice right after. Recorded in docs/010.

**Also answered with the 10e-2b-4f report (2026-10-19).** (1) The same fix for the Pet Deposit check in the old move-in is right (confirmed). (2) The design change is confirmed: the old move-in needs the received money to be at least the current required total, and a NULL total is refused. The looser case (45,000 held of a 50,000 first amount, after a decrease to 40,000) is right, because 40,000 is now the required total. (3) The pending rename stays: the next time `test_deposit_receipt_refund_out_migration.py` is touched, `test_a_receipt_recorded_while_a_refund_is_out_is_reversed_by_two_people` is renamed `test_a_receipt_recorded_while_a_refund_is_out_is_reversed_by_a_confirmed_draft`. Order: 10g-2 (pre-code design first), 10h (with the Q-2026-10-17-120 answer and the post-closure put-back gap), then the Q-112 times sub-slice (with the Q-2026-10-18-133 and Q-2026-10-19-138 answers); stop before slice 11. A large sub-slice may be split into smaller ones that each end in a commit. Recorded in docs/010.

## Q-2026-10-19-139 — Sub-slice 10g-2 review round 1: a release of the wrong Payment's money on a Late-payment Charge of the wrong Invoice (blocks nothing; built as (b); a known limit until you answer; nothing else waits) (ANSWERED 2026-10-19: (b), kept as built, a known limit on the slice 12 list; answer in docs/010)

Your answer (a) to Q-2026-10-17-121: inside the `PAYMENT_MOVE` correction, the Payment's other Customer Credit or Refunds no longer block the move, except where a credit Adjustment released any part of an allocation of this Payment on the wrong Invoice. Sub-slice 10g-2 reads that as the release rows of this Payment's allocations whose Invoice is the wrong Invoice. The security reviewer of round 1 found one case the question did not show.

**The case.** A Payment can also pay a Late-payment Charge directly (a Charge allocation, which has no Invoice; BR-PAY-040 treats the Charge as its own obligation). After closure, a Late-payment Charge `REFUND` correction of the same Settlement (the `REFUND` variant with `target_kind` `LATE_PAYMENT_CHARGE`, sub-slice 10c-3b-1, migration `20261117_113`, confirmed under `financial.approve`) can release that Charge allocation into Credit of the Charge's Customer and refund what its DL-032 step does not apply to that Customer's open debt on the Lease. If that Charge belongs to the wrong Invoice, and the same Payment also paid the wrong Invoice, the `PAYMENT_MOVE` correction of the Invoice allocation is accepted today: the release is on the Charge, not on the Invoice. Before 10g-2 the blanket rule refused it. The move itself does not touch the Charge allocation, its Credit or the Refund; the independent reviewer read it as consistent with BR-PAY-040 (the Charge is a separate obligation, like another Invoice, whose release does not block). In the other order (the move confirmed first, the Charge Refund second) both corrections are accepted today, were accepted before 10g-2, and would be under (a), so (a) refuses only the order in which the Charge Refund comes first (review round 2, security). The end records differ only in where the released Charge Credit goes: in that order the Charge Refund's DL-032 step (owner answer 2 to Q-2026-10-07-42) first applies it to the Customer's open debt on the Lease, which then includes the debt the move brought back, and refunds only the rest (wording corrected in review round 3, both reviewers). The built Invoice rule depends on order in the same way for the Payment's other allocations on the wrong Invoice (a `REFUND` correction after the move can still release a newer allocation of the Payment there); it protects in both orders only against a release of part of the moved allocation itself, because once that allocation moves whole it can no longer be released (review round 3, security).

**Options.**
- (a) Also read a release of this Payment's allocation on a Late-payment Charge whose source Invoice is the wrong Invoice, so the correction is refused there too (fail closed; never stricter than the rule before 10g-2), with a real-path test after a real closure. A small sub-slice.
- (b) Keep it as built: a Charge is its own obligation, as another Invoice of the Lease is.

**Recommendation: (b)** (changed in review round 2 from (a); reason reworded in review round 3), because a Charge allocation is never part of the moved allocation or of its release chain (Charge allocations never move, BR-PAY-042 and the slice 7 source), so its release never turns the moved value into Credit or a Refund; it is like a release on another Invoice, or of another allocation of the Payment. Refusing the move would recover nothing and leave the wrong allocation in place, and (a) would refuse only one order of the same two approved corrections. A Charge allocation of a Payment meant for another Unit may still be part of the same mistake; if you want that money followed, it needs its own rule (for example, moving or refunding the Charge allocation too), which (a) does not give.

**What goes ahead.** Everything. 10g-2 is committed with (b) as built and this case on the slice 12 list as a known limit until you answer. No money leaves without a `financial.approve` confirm.

**Owner answer (2026-10-19).** Option (b). Keep it as built. A Late-payment Charge payment is never part of the moved money, and refusing only one order of the same two approved corrections adds nothing. It stays on the slice 12 list as a known limit.

**Also answered with the 10g-2 report (2026-10-19).** (1) The new known limit is accepted: when a credit Adjustment released part of the Payment's allocation on the wrong Invoice, the move stays refused after closure while any Credit of that Payment is not reversed or any Refund of it is not fully returned. (2) Run-rule reminder: a full run goes alone in its own tool call, with no other command in it, not even `git status`. (3) The pending rename stays: the next time `test_deposit_receipt_refund_out_migration.py` is touched, `test_a_receipt_recorded_while_a_refund_is_out_is_reversed_by_two_people` is renamed `test_a_receipt_recorded_while_a_refund_is_out_is_reversed_by_a_confirmed_draft`. Order: 10h (pre-code design first, with the Q-2026-10-17-120 answer and the post-closure put-back gap; the two items the owner decides with 10h, the ordinary `PAYMENT_RETURN` draft after closure and the Credit Refund outside a correction, are written as questions as soon as the design finds them, and the parts of 10h that do not depend on them are built), then the Q-112 times sub-slice (with the Q-2026-10-18-133 and Q-2026-10-19-138 answers); stop before slice 11. Recorded in docs/010.

## Q-2026-10-19-140 — 10h pre-code design: the ordinary Payment return draft after closure (blocks nothing in 10h; nothing is built before your answer; recommendation (a)) (ANSWERED 2026-10-19: (a); answer in docs/010)

Your answer 2 of 2026-10-13 to the 10e-4 report: decide with 10h whether the ordinary `PAYMENT_RETURN` draft (sub-slice 10e-1a: `payments.reverse` records, `financial.approve` confirms) may still return a Payment whose records on a Lease with a closed Final Settlement were all made after the closure.

**What exists.** The `PAYMENT_RETURN` draft refuses a Payment with any record a closed Settlement relied on (an allocation or Credit application made at or before the closure on that Lease, a Settlement Credit application, a record linked to a correction): "return it through a correction of that Final Settlement" (the `RETURNED_PAYMENT` correction, sub-slice 10e-4). A record made after the closure is not one the Settlement relied on, so the draft returns that Payment: it reverses those allocations and Credit applications, the debt comes back on the Lease, and nothing links the return to the Settlement. The `RETURNED_PAYMENT` correction of that Settlement can return the same Payment with the same result, and with every record linked to the Settlement. Your answer 3 to Q-2026-10-06-36 keeps records made after the closure reversible with one call each, and 10h does not change that.

**Example.** Lease A's Final Settlement closed with 500.00 of damage debt. A week later the Customer pays 500.00 by bank transfer P; staff allocate it to the damage line, which then owes 0. The transfer bounces. Today a `payments.reverse` holder records a `PAYMENT_RETURN` draft and a `financial.approve` holder confirms it: the 500.00 allocation is reversed, P is returned, and the damage line owes 500.00 again. The `RETURNED_PAYMENT` correction of A's Settlement would write the same records, linked to the Settlement.

**Options.**
- (a) Keep it: a Payment whose records on the closed Lease were all made after the closure may be returned by the ordinary draft or by the correction. Who pays and how much are the same either way.
- (b) Refuse the ordinary draft for a Payment with any active record on an obligation of a Lease whose Final Settlement is closed, so staff use the `RETURNED_PAYMENT` correction (a tightening of the 10e-1a recorder and confirm; a waiting draft would be refused at its confirm and stay pending).

**Recommendation: (a)**, because those records are not part of what the Settlement relied on, your answer 3 keeps them reversible with one call each, and the draft already needs a `financial.approve` approver; (b) adds a second path rule with no change in who pays or how much.

**What goes ahead.** Everything: 10h-1, 10h-2 and 10h-3 do not depend on this answer. If you choose (b), it is built as a small sub-slice after 10h-3, before the Q-112 times sub-slice.

**Owner answer (2026-10-19).** Option (a). Keep the ordinary Payment return draft after closure. It only reverses records made after the closure, and who pays and how much stay the same as through the correction. Nothing is built. Recorded in docs/010.

## Q-2026-10-19-141 — 10h pre-code design: the Credit Refund outside a correction (blocks nothing in 10h; nothing is built before your answer; recommendation (b)) (ANSWERED 2026-10-19: (b), its own small sub-slice right after 10h-1; answer in docs/010)

Your answer 2 of 2026-10-13 to the 10e-3c report: decide with 10h the Credit Refund outside a correction (the ordinary Refund draft of slice 3a-1: `refunds.create` records, `financial.approve` confirms, no link to a Final Settlement).

**What exists.** After a Final Settlement closes, a post-settlement correction can bring money back into a Customer's Credit, for example a return-only correction that records that a Settlement Refund paid from the Credit came back from the bank. That money then waits in the Credit. A `HELD_VALUE_REFUND` correction naming that return pays it out under DL-032: first the Customer's own open debt on the Lease, then a Refund of the rest; the count of what that return has left (sub-slice 10e-3d) sees it. The ordinary Credit Refund draft has no Settlement check: it can pay the same money out in cash while the Customer still has open debt on the closed Lease, and the return's count does not see it (the known limit of your answer 2 to Q-2026-10-09-63, "Credit spent outside a correction is not counted"). If that return later proves a mistake, its reversal reads 300.00 left in a Credit that is empty.

**Example.** Lease A's Final Settlement refunded the Customer's 300.00 Credit. The bank sends the 300.00 back, and correction X1 records the return, so the Credit holds 300.00 again. Later an `EXTRA_CHARGE` correction bills 100.00 of damage found after the closure. Today staff can refund all 300.00 through the ordinary draft; the 100.00 stays owed and X1 still counts 300.00 left. Through a `HELD_VALUE_REFUND` correction naming X1, 100.00 pays the damage and 200.00 is refunded, and X1 counts 0 left.

**Options.**
- (a) Keep it as the known limit of Q-63 answer 2. Every payout still needs a `financial.approve` approver, and what the Credit holds caps every later payout.
- (b) Refuse the ordinary Credit Refund draft (at record and at confirm) for a Credit that holds money a post-settlement correction brought back, while that return still has money left by its count; staff pay that money out through a `HELD_VALUE_REFUND` correction naming the return. Money a Customer's Credit holds for other reasons (for example an overpayment after the closure) stays refundable through the ordinary draft. A tightening, with real-path tests.
- (c) Count the ordinary Credit Refund in the return's left value and let a later reversal of the return follow that Refund and charge it back to its recipient (the 10e-3d follow), as for a correction's payout. A larger change of the walk functions.

**Recommendation: (b)**, because money a correction brought back after the closure belongs to that Settlement's flow: DL-032 and your answer to Q-2026-10-05-29 say the Customer's Credit pays the Customer's own debt first, and the return's count stays true only if that money leaves through a correction. (c) reaches the same end with much more code, and (a) keeps both effects.

**What goes ahead.** Everything: 10h-1, 10h-2 and 10h-3 do not depend on this answer. If you choose (b) or (c), it is built as a small sub-slice after 10h-3, before the Q-112 times sub-slice.

**Owner answer (2026-10-19).** Option (b). Refuse an ordinary Credit Refund for Credit that holds money a correction brought back. That money leaves only through a correction, so open Lease debt is paid first (DL-032). Build it inside 10h-1 if it is small and touches the same code; otherwise as its own small sub-slice right after 10h-1. Placement (implementer): its own small sub-slice right after 10h-1, because it changes the slice 3a-1 Refund draft recorder and confirm, not the 10h-1 code. Recorded in docs/010.

## Q-2026-10-19-142 — Sub-slice 10h-1 stopped after review round 1 and run P1: eight committed tests build their set-up with a reversal that 10h now refuses (blocks the 10h-1 commit; recommendation (a)) (ANSWERED 2026-10-19: (a); answer in docs/010)

**Where it stands.** Sub-slice 10h-1 (migration `20270108_165`) is built as the 10h pre-code design says: after a Final Settlement closes, an allocation or Credit application it relied on is reversed only through a correction of that Settlement (two insert triggers, and the slice 7 move source refuses such an allocation). It is NOT committed; every file is in the working tree. Checks, M1, M2, T1 (161 passed) and U1 (3,866 passed) are green. P1: 2,378 passed, 8 failed. Record: ops/reviews/V1-056-slice-10h-1-relied-on-reversals.md.

**Why the eight fail.** Each one builds its scenario with a reversal that 10h now refuses, as your answer 3 to Q-2026-10-06-36 asks. None of them checks that reversal; they use it to reach the state they test. My pre-code design said no other committed test does this; that was wrong (my search pattern missed these modules; the independent reviewer found seven, P1 the eighth).
- Six tests (five in `test_settlement_return_reversal_put_back_migration.py`, one in `test_settlement_return_reversal_other_refunding_take_migration.py`) reopen the Initial Invoice's Rent line after a real closure with the one-call allocation reversal (the fixture `open_rent_line`, whose docstring says "open until sub-slice 10h", and the same reversals of the Rent and Trash payments in `put_back_case`), so that a return reversal's put-back then meets an open Rent line (your Q-2026-10-13-104 answer).
- `test_settlement_returned_payment_migration.py::test_refusals_stale_drafts_and_a_deposit_that_would_still_hold_money` writes, as the owner, the same one-call reversal of a closure-era allocation ("still open before sub-slice 10h") to make a waiting `RETURNED_PAYMENT` draft stale.
- `test_settlement_correction_plan_migration.py::test_credit_released_from_a_payment_pays_its_customer_s_debt_before_the_deposit` builds a correction by hand in a transaction that always rolls back and writes its credit Adjustment through the ordinary writer, whose release reversal is not linked to that correction (real corrections link it first).

**Example (the put-back tests).** The Initial Invoice's 1,000 Rent was paid before the closure. Today the test reverses that allocation with one call after the closure, so Rent owes 1,000 again, and then checks that a mistaken return's reversal puts a Credit part back on the Service line, not on the open Rent line. Since 10h the one-call reversal is refused (P5S01), so the test never reaches its check.

**Options.**
- (a) Keep each scenario with a hand-built set-up: a small test helper writes those reversals as the owner, with the two new 10h triggers disabled only inside that set-up transaction (as the earlier `tied_by_hand` helper does inside a rolled-back transaction), and each changed fixture first asserts that the one-call reversal is now refused (P5S01, nothing written). Every check and every amount of the eight tests stays as it is; no product code changes. This extends your answer to Q-2026-10-18-131 (a hand-built set-up for a scenario the writer no longer reaches) to these eight tests.
- (b) Rebuild them on the real path: where a test needs an open Rent line after closure, return the Rent Payment through a `RETURNED_PAYMENT` correction instead of the one-call reversal; the stale-draft test changes the Payment's records another way; the plan test links a real correction's release. This changes records and expected amounts in several tests, so each change is listed for you first.
- (c) Something else.

**Recommendation: (a)**, because these tests check put-backs, stale drafts and the DL-032 plan, not the reversal itself; (a) keeps all their checks unchanged and adds the 10h refusal at the exact place it now applies, while (b) rewrites eight scenarios and their numbers for no gain in what they prove.

**Review round 1 findings that do not wait for this answer (fixed with it, then round 2).** Independent: should-fix S1, the slice 7 move refusal also refuses an allocation that was reversed before the closure (the 10e-1a definition counts only active records; fix: read only active allocations, a relaxing correction of my own code); S2 and security should-fix 1, the hand-built slice 7 draft carries an empty source, so the withdrawn-draft check no longer isolates the decision (fix: build the real source); S3 and security should-fix 2, a test that another Lease's `REFUND` correction cannot release an allocation a `PAYMENT_MOVE` correction wrote (Q-2026-10-17-120 point 2); S4, docs/005 for the credit Adjustment route on an open Lease. Notes to take: tests of the slice 7 confirm refusing a waiting hand-built draft, of records made after the closure in the new module, and of the trigger order; BR-SETTLE-016 and BR-AUTH-010 in the traceability entries; the security reviewer's free hardening (take the locks before the Settlement-row test).

**What goes ahead.** Nothing: 10h-2 would take the next migration number on top of uncommitted 10h-1, and this session is above your 45% line. After your answer, a fresh session makes the fixes, reruns the checks, T, U, M and P, and runs review round 2.

**Owner answer (2026-10-19).** Option (a). Keep each of the eight scenarios with a hand-built set-up, and assert the new 10h-1 refusal first. Every check and amount stays the same. In each changed set-up, add a short comment that the state can no longer be reached by the one-call reversal since 10h-1. List every changed committed test in the review record. Rename any committed test whose name the change makes wrong, under the standing rule. If a scenario can still be reached through a real correction, keep it as it is and add a note to the slice 12 list for a real-path version. Fix all round 1 should-fix items (the ordinary move refusal must not catch allocations reversed before the closure, which the Settlement did not rely on; a real source for the hand-built test draft; the test for the other Lease's `REFUND` correction; the docs/005 route note) and the security reviewer's two test items. Recorded in docs/010.

## Q-2026-10-19-143 — Sub-slice 10h-1 security review round 2: the new refusals rely on the default transaction isolation (blocks nothing; nothing is built before your answer; recommendation (a)) (ANSWERED 2026-10-19: (a), built with 10h-2; answer in docs/010)

**What exists.** The two 10h-1 triggers first take the reversal writer's own locks, then test whether the target's Lease has a Final Settlement row; with no row and no correction link they let the reversal through. Under the default isolation (READ COMMITTED) each statement takes a new snapshot, so the test sees every Settlement started or closed before it. A Settlement row exists from the moment the Settlement is started, long before its closure. So a caller at REPEATABLE READ or SERIALIZABLE whose snapshot is taken after the start is refused anyway: its `FOR SHARE` on that row, which the closure updated, fails with a serialization error (fail closed). The gap is narrower (review round 3, both reviewers): a caller whose snapshot is taken before the Settlement is even started sees no row, takes no Settlement lock, and reverses a record the Settlement then relied on, if the start, the draft and the confirm all commit during its transaction and the confirm changes no row the reversal touches. No route does this today: the allocation, Credit, Payment return and Payment move services set no isolation level and so run at the server default, READ COMMITTED; a changed `default_transaction_isolation` on the database or a role would open the gap to them too. Otherwise it needs direct database access with the financial role. The 8e-1 refusal has the same pattern. The 8e-3 confirm and the correction confirms already refuse any isolation other than READ COMMITTED.

**Example.** A damage Invoice of 500.00 on Lease A is fully paid by a 500.00 allocation. A script with the financial role opens a REPEATABLE READ transaction and reads, before anyone starts A's Final Settlement. Meanwhile staff start the Settlement, record its draft (no step touches the paid damage Invoice) and an approver confirms it: the Settlement closes and relies on the 500.00 allocation. The script then reverses the allocation; its snapshot still shows no Settlement row, so the trigger lets it through and the damage line owes 500.00 again outside a correction.

**Options.**
- (a) Refuse a reversal in both 10h-1 triggers (and in the 8e-1 refusal) when the transaction isolation is not READ COMMITTED, as the 8e-3 confirm does. A tightening, with a test; built with 10h-2, which adds the same kind of trigger for forfeiture reversals.
- (b) Keep it as a known limit on the slice 12 list (only direct database access reaches it).

**Recommendation: (a)**, because it closes the gap with one check per trigger, follows the pattern the confirms already use, and changes no amount or person for any request made through the app.

**What goes ahead.** Everything: 10h-1 is committed without it; the Q-141 sub-slice, 10h-2 and 10h-3 do not depend on it.

**Owner answer (2026-10-19, fresh session).** Option (a). Refuse a reversal in the 10h-1 triggers when the transaction isolation is not READ COMMITTED, and build it with 10h-2. Before building it, search the app code, scripts and tests for any path that sets a stricter isolation level. If one exists, do not break it: write a question with a recommendation and continue with the rest of 10h-2. Also answered: placing the Q-2026-10-19-141 answer (b) in its own sub-slice is right, because it changes the slice 3a-1 Refund draft recorder and confirm. Recorded in docs/010.

**Also answered with the 10h-2 report (2026-10-20, fresh session).** (1) The two isolation gaps the 10h-2 report named (the 8e-1 refusal has no isolation check; a REPEATABLE READ 6b recorder with an older snapshot can still record a waiting 6b draft after the closure) are closed now, the same way as option (a) above: the READ COMMITTED check is added to the 8e-1 refusal, and to the 6b source or recorder. Built as one small fail-closed sub-slice, 10h-4, right after 10h-3; the two notes leave the slice 12 list when it is built. (2) New build order (owner decision of 2026-10-19): after slice 10 is finished (10h-3, 10h-4 and the Q-112 times sub-slice), V1-056 pauses before slice 11. Next come the docs-only rules updates, then the login slice (sessions, MFA, tests), then the existing screens rebuilt to the owner's UI design, with the owner testing each area as it lands. Then slices 11 and 12 are built in the owner's design, then the final gates and the push. None of the new steps starts before the owner sends it. Order now: 10h-3 (pre-code design first), 10h-4, the Q-112 times sub-slice (with the Q-2026-10-18-133 and Q-2026-10-19-138 answers); stop before slice 11. The pending rename in `test_deposit_receipt_refund_out_migration.py` stays until that file is next touched. Recorded in docs/010.

## Q-2026-10-19-144 — Sub-slice 10h-1b review rounds 1 and 2: the one-call Credit reversal still lets money a correction brought back leave without a correction, also while the Customer owes on the closed Lease (blocks the 10h-1b commit; recommendation (a), built inside 10h-1b) (ANSWERED 2026-10-19: (a), built inside 10h-1b; answer in docs/010)

**What exists.** Your answer (b) to Q-2026-10-19-141 is built in 10h-1b for the ordinary Credit Refund draft: it refuses money a post-settlement correction brought back into a Credit. The security reviewer of round 1 found a second way out (by reading; no test runs it yet). The one-call Credit reversal (`credits.reverse`, `app.reverse_customer_credit`) undoes a Credit whose whole recognized value is available again, and the value goes back to the Payment as unused value. That is the case after a correction's Refund of the Credit came back in full. From the Payment, the money can then be refunded through the ordinary Payment Refund draft, or recognized as a new Credit and refunded through the ordinary Credit Refund draft. Neither is linked to the Settlement, and the return's count still shows the money as left.

**What protects the Customer's debt, and where it does not (corrected after review round 2).** In round 1 I wrote that a Payment Refund and a new Credit recognition both need the payer to owe nothing at the Property, so debt is still paid first. The round 2 security reviewer showed that this is wrong, and I confirmed it by reading `app.assert_payment_excess_eligible` (migration 41): for a Payment that names nothing, it checks every open Invoice and Late-payment Charge of the payer at the Property; but for a Payment confirmed for a named Invoice it checks only that Invoice, and for a Payment confirmed for a named Late-payment Charge only that Charge. So when the Credit came from such a Payment, the money can be paid out in cash while the Customer still owes on the closed Lease, which is what your answer (b) forbids. A Credit released to another Customer still cannot be reversed with one call (sub-slice 8g).

**Example.** Lease A's Final Settlement is closed. A correction refunded 2,000 of the Customer's Credit C, and correction X1 records that the 2,000 came back, so C holds 2,000 and X1 has 2,000 left. The Customer owes nothing. A `credits.reverse` holder reverses C: the 2,000 goes back to Payment P. A `refunds.create` holder records a Payment Refund draft of 2,000 and a `financial.approve` holder confirms it. The Customer gets 2,000 in cash with no link to A's Settlement, and X1 still counts 2,000 left (a later reversal of X1 would read money that is gone). Through the correction, a `HELD_VALUE_REFUND` naming X1 pays the same 2,000 to the same Customer, linked. Second example (review round 2): the same, but P was confirmed for the Initial Rent Invoice, which is paid, and an `EXTRA_CHARGE` correction has billed 1,500 of damage on Lease A. The Payment Refund draft of 2,000 still confirms, because the check reads only the Initial Rent Invoice: the Customer gets 2,000 in cash and still owes 1,500 on the closed Lease. Through the correction, 1,500 would pay the damage and only 500 would be refunded.

**Options.**
- (a) Refuse the one-call Credit reversal (P5S01, a conflict) while the Credit holds money a post-settlement correction brought back, unless a correction of that Settlement confirmed in the same transaction links the reversal (a new BEFORE INSERT trigger on `app.customer_credit_reversals` that takes the Credit Refund locks first, as both security reviews set out; the Credit service maps the refusal to a conflict). A tightening, with real-path tests (the round 2 reviewer's set-up is in the review record), built inside 10h-1b before its commit, then review round 3.
- (b) Commit 10h-1b as it is and keep this path as a known limit on the slice 12 list, with the corrected text above (cash can leave while the Customer owes on the closed Lease, for a Credit from a Payment confirmed for a named Invoice or Charge).
- (c) As (a), but as its own small sub-slice right after the 10h-1b commit (10h-1b commits first with the known limit named).

**Recommendation: (a)**, because your answer says that money leaves only through a correction so open Lease debt is paid first, and this path breaks exactly that; it is one fail-closed check, changes no amount, and keeps 10h-1b whole.

**What goes ahead.** Nothing. Review round 2 had a blocker (security), so under the run rules 10h-1b stops after round 2 and is not committed; 10h-2 would take the next migration number on top of the uncommitted 10h-1b. Everything else of 10h-1b is built and green (P2: 2,396 passed); its other round 2 items are text and test notes, listed in the review record.

**Owner answer (2026-10-19, fresh session).** Option (a). Refuse the one-call Credit reversal while the Credit holds money a correction brought back, unless a correction links it. Build it inside 10h-1b. Money a correction brought back leaves only through a correction, so open Lease debt is paid first (DL-032), the same reason as the answer to Q-2026-10-19-141. Also answered: (2) the change to the committed test `test_settlement_held_value_refund_migration.py::test_a_credit_return_while_a_deposit_holds_money_is_refunded_with_that_money` is accepted: it asserts the refusal first, then writes the same 600 Refund through the owner-only one-call writer; every later check and amount stays the same; if its name is now wrong, it is renamed under the standing rule. (3) New standing run rule (ops/V1_055_RUN_RULES.md): when a new refusal breaks a committed test only because its set-up uses the path that is now refused, the set-up is changed the way the answer to Q-2026-10-19-142 says (assert the refusal first, hand-build the same state, keep every check and amount, add the short comment, list it in the review record) without asking; the owner is asked only when a checked amount or an expected result would change. This already covers `test_a_second_active_forfeiture_of_the_deposit_refuses_its_reversal` in 10h-2. (4) The pending rename stays: the next time `test_deposit_receipt_refund_out_migration.py` is touched, `test_a_receipt_recorded_while_a_refund_is_out_is_reversed_by_two_people` is renamed `test_a_receipt_recorded_while_a_refund_is_out_is_reversed_by_a_confirmed_draft`. Order: Q-144 (a) and the round 2 items, review round 3, commit 10h-1b; then 10h-2 (with the Q-2026-10-19-143 answer), 10h-3, the Q-112 times sub-slice (with the Q-2026-10-18-133 and Q-2026-10-19-138 answers); stop before slice 11. Recorded in docs/010.

## Q-2026-10-20-145 — 10h-4 pre-code design: the READ COMMITTED check in the 8e-1 refusal changes three committed tests, and other waiting corrections' Credit steps (blocks only 10h-4b, the 8e-1 part; nothing is built for either point before your answer; recommendation (a) for both) (ANSWERED 2026-10-20: point 1 (a), built as 10h-4b; point 2 answered "(a)" with a reason that reads as (b), asked again as Q-2026-10-20-146; answer in docs/010)

Your answer 1 to the 10h-2 report: add the READ COMMITTED check to the 8e-1 refusal (`app.refuse_closed_final_settlement_change`) and to the 6b source or recorder, the same way as the answer (a) to Q-2026-10-19-143, whose condition says: search the app code, scripts and tests for a path at a stricter isolation level, and if one exists, do not break it, ask. The 10h-4 pre-code design (plan, 10h entry) did that search.

**Point 1: the 8e-1 check would change three committed tests.**
- No app path and no script writes at a stricter level (every such app path is a read-only read). The 6b check breaks nothing and is built now, in 10h-4a.
- The 8e-1 refusal is a BEFORE trigger on eight tables (Invoices, one-time charges, VOID events, Adjustments and their reversals, Late-payment decisions, Charges and Charge corrections). Its triggers are named `a0_...`, so they run before the tables' serialization guards. A check before any read, as in 10h-1, would refuse every write to those tables at REPEATABLE READ or SERIALIZABLE with 55000, also on a Lease with no Final Settlement (a snapshot taken before a Settlement starts cannot see it, so the check cannot wait until it finds one).
- Three committed tests write those tables at REPEATABLE READ with direct SQL to prove the guards: `test_invoice_migration.py::test_concurrent_duplicate_rent_period_and_billing_run_are_rejected` (four two-writer races on Adjustments, VOID events and Late-payment Charge corrections: today one writer commits and the other gets 40001 or 23505), `::test_concurrent_invoice_issuance_serializes_lease_and_service_sources` (an issue at REPEATABLE READ expects 40001), and, by reading, `test_pet_payback_restoration_refusal_migration.py::test_at_repeatable_read_the_later_writer_fails_on_the_deposit_guard` (an Invoice issue at REPEATABLE READ expects the Deposit guard's 40001). With the check, each of these writers would get 55000 before reaching its guard. The exact list is confirmed by a targeted run when the check is built.
- **Example of the gap it closes** (corrected after 10h-4a review round 1, security: a write to an Invoice the closure itself changed, for example one a Deposit paid, already fails on that Invoice's row lock with 40001). A damage Invoice of 500.00 on Lease A is unpaid, A's Deposits are kept (forfeited) and the Customer has no Credit (10h-4a review round 2, security note 1: a Credit application to that Invoice would advance its guard and fail the writer), so the closure leaves the 500.00 as the Customer's debt and does not touch that Invoice. A script with the financial role opens a REPEATABLE READ transaction before anyone starts A's Final Settlement. Staff start it, record the draft, and an approver confirms it: the 500.00 is recorded as debt on the Primary Tenant's Ledger. The script then writes a credit Adjustment of 500.00 on that Invoice (or VOIDs it, or records a Late-payment decision on it); its snapshot shows no Settlement row, so the 8e-1 refusal lets it through, and the debt the closed Settlement recorded is lowered outside a correction. No route can do this; every app path writes at READ COMMITTED. The targeted run of 10h-4b confirms it.
- (a) Build it as you answered (10h-4b): every write to the eight tables at a stricter level is refused (55000) before any read. The three tests change their expected results: each REPEATABLE READ writer asserts the 55000 refusal with nothing written, instead of the guard's 40001 or 23505 (the guards stay in place for every app path, which runs at READ COMMITTED; the races at REPEATABLE READ no longer reach them).
- (b) A narrower check that keeps the three tests unchanged where it can: at a stricter level, refuse a write only on a Lease the snapshot shows TERMINATED (only a terminated Lease can have a Final Settlement, and a termination always updates the Lease row), and for any other Lease lock the Lease row FOR SHARE first, so a termination committed after the snapshot fails the writer (40001) and a later termination waits for it. The Invoice races (signed Leases) keep their results; the pet test (a terminated Lease) would still change unless its issue reaches the Deposit guard first (to be checked by a run). More code, and a new lock on every such write; on an Invoice update the Invoice row is locked before the trigger, so the order becomes Invoice then Lease, against the Settlement confirm's Lease then Invoices: a REPEATABLE READ writer can deadlock with a confirm (40P01, still fail closed).
- (c) Keep it as a known limit (slice 12 list): only direct database access at a stricter level reaches it.
- **Recommendation: (a)**, because it is one check, follows the pattern of the 8e-3 confirm, the correction confirms and the 10h-1 triggers, changes no amount or person for any request made through the app, and the changed tests prove a direct-SQL race at a level no app path uses.

**Point 2: other waiting correction drafts' Credit steps.** Your answer 2 to the 10h-3 report asked me to check the Credit-refund corrections `REFUND` and `HELD_VALUE_REFUND`. `HELD_VALUE_REFUND` is real and is closed in 10h-4a (its Credit is in the draft). `REFUND` is not reached for the money it refunds: it refunds only value its own confirm releases from its own closed Lease's line, which no other path may touch since 10h-1. But a correction draft's plan (the DL-032 step of `REFUND`, `HELD_VALUE_REFUND` and the other variants) can also hold `CUSTOMER_CREDIT` steps that let a Customer's Credit pay that Lease's debt first, and a `REFUND` draft's plan check also reads what is left in each Credit it releases into (10h-4a review round 1, independent N1); another Lease's Settlement can apply other money of the same Credit while the draft waits. The draft is then stale at its confirm (P5S02, fail closed, no wrong money) and must be recorded again with what is left (a `REFUND` draft recorded again refunds the same released amount).
- **Example.** Customer C's Lease A is closed. A `REFUND` correction draft of A waits; its plan lets C's Credit K (800) pay a 500 charge on A first. C's second Lease B is terminated; B's Settlement applies K's 800 to B's cleaning charge and closes. The `REFUND` draft is stale; recorded again, K pays nothing of A's 500, which stays C's debt on A (or a Deposit of A pays it). Had the draft been confirmed first, K would have paid A's 500 and only 300 would have been left for B.
- (a) The preview also lists another Settlement's waiting correction draft (any variant) whose plan has a `CUSTOMER_CREDIT` step on a Credit a person of the Lease holds, or (a `REFUND` draft) which releases value into such a Credit, the same kind of refusal as 10h-3 and 10h-4a; a small sub-slice after the Q-112 times sub-slice, or with 10h-4b.
- (b) Keep it: the waiting draft becomes stale and is recorded again (fail closed); a slice 12 note.
- **Recommendation: (a)**, because your answer to the 10h-3 report sets the rule that a waiting draft is decided before the closure or a correction goes ahead, and this is the last such draft the preview does not list; it changes no amount rule, only the order.

**What goes ahead.** 10h-4a (the 6b check and the `HELD_VALUE_REFUND` draft in the preview), then the Q-112 times sub-slice. 10h-4b and point 2 wait for your answers.

**Owner answer (2026-10-20, fresh session).** Point 1, option (a): build the READ COMMITTED check in the 8e-1 refusal as 10h-4b. The three committed tests that write at REPEATABLE READ by direct SQL change their expected result to the 55000 refusal. What they protect is not lost: for each of the three, check that the guard it tested (the duplicate Rent period and billing run guards, the Invoice issuance serialization, the Deposit guard) is still tested at READ COMMITTED by a committed test; if one is not, add that test in 10h-4b. The three changed tests and any new ones are listed in the review record. Point 2, option (a), "your recommendation", with this reason: a stale correction draft is refused (fail closed) and staff record it again, so no money goes wrong; keep the case on the slice 12 list, and slice 11 must show staff a plain message that the draft is out of date and must be recorded again. The reason matches option (b) (keep it, a slice 12 note), not option (a) (list such drafts in the preview), so point 2 is asked again as Q-2026-10-20-146; nothing is built for it before that answer, and the slice 12 note and the slice 11 message are recorded either way. Also answered: (3) run-rule slip in 10h-4a (a migration check started from `backend/` and batched with a full run): every script is run by its absolute path from the repository root, alone in its own tool call, and the working directory is checked before each script run. (4) The pending rename in `test_deposit_receipt_refund_out_migration.py` is done the next time that file is touched. Order: 10h-4b (pre-code design first), then the Q-112 times sub-slice (with the Q-2026-10-18-133 and Q-2026-10-19-138 answers, pre-code design first); then stop and tell the owner, before slice 11 (ops/V1_056_TAKEOVER.md section 8). Recorded in docs/010.

## Q-2026-10-20-146 — Q-2026-10-20-145 point 2: the answer says option (a) but its reason describes option (b) (blocks nothing in 10h-4b or the Q-112 times sub-slice; nothing is built for point 2 before your answer; recommendation (a)) (ANSWERED 2026-10-20: option (a), for sub-slice 10i-4; answer in docs/010)

**What was asked.** Q-2026-10-20-145 point 2: a closed Settlement's waiting correction draft (any variant) can have a plan with a `CUSTOMER_CREDIT` step on a Credit that a person of another Lease holds, or (a `REFUND` draft) release value into such a Credit. While it waits, that other Lease's Settlement can apply the same Credit first; the waiting draft is then stale at its confirm (P5S02, fail closed) and is recorded again with what is left. Option (a): the preview also lists such a draft (the same kind of refusal as 10h-3 and 10h-4a), so the other Lease's Settlement waits until the draft is decided. Option (b): keep it; the draft becomes stale and is recorded again; a slice 12 note.

**Your answer.** "Option (a), your recommendation. A stale correction draft is refused (fail closed) and staff record it again, so no money goes wrong. Keep the case on the slice 12 list, and slice 11 must show staff a plain message that the draft is out of date and must be recorded again." The label and "your recommendation" say (a). The reason (the stale draft is the accepted result, the case stays on the slice 12 list) is what option (b) says; under (a) the preview would refuse the other Lease's Settlement while the draft waits, so the draft would not become stale that way, and the case would leave the slice 12 list.

**Example.** Customer C's Lease A is closed. A `REFUND` correction draft of A waits; its plan lets C's Credit K (800) pay a 500 charge on A first. C's second Lease B is terminated. Under (a), B's preview shows `PENDING_DRAFT` until the draft is confirmed (K pays A's 500, 300 left for B's cleaning charge) or rejected or withdrawn. Under (b), B's Settlement may apply K's 800 to B's charge and close; the draft is then stale (P5S02, nothing written) and, recorded again, K pays nothing of A's 500, which stays C's debt on A (or a Deposit of A pays it).

**Options.**
- (a) As option (a) of Q-145 point 2: one small fail-closed sub-slice (the preview's pending-draft check also lists such drafts). It changes no amount rule, only the order. Under the build order (ops/V1_056_TAKEOVER.md section 8) slice 10 ends with the Q-112 times sub-slice, so it would be built only when you send it (for example as the first item of the slice 11 and 12 phase, or right after the Q-112 times sub-slice). The slice 11 "out of date, record it again" message is still needed, because two drafts recorded at the same moment can still make one stale (the 10h-4a race note).
- (b) As option (b) of Q-145 point 2: nothing is built; the case stays on the slice 12 list; slice 11 shows staff a plain message that the draft is out of date and must be recorded again.

**Recommendation: (a)**, as in Q-145: your answer to the 10h-3 report sets the rule that a waiting draft is decided before the closure or a correction goes ahead, and this is the last such draft the preview does not list. If you meant (b), say so and nothing is built.

**What goes ahead.** Everything: 10h-4b and the Q-112 times sub-slice do not change the preview's pending-draft check. The slice 12 note and the slice 11 message are recorded now; under (a) the slice 12 note leaves the list when the sub-slice is built.

**Owner note (2026-10-20, fresh session, with the 10h-4b report).** The Q-145 point 2 answer was unclear; this question stays open and nothing is built for it before the owner's answer. The Q-112 times sub-slice does not depend on it and goes ahead.

**Also answered with the 10h-4b report (2026-10-20).** (1) The 10h-4b test changes are accepted, including the changed amounts in `test_invoice_migration.py::test_concurrent_duplicate_rent_period_and_billing_run_are_rejected` (nothing is written when both writers are refused) and the rename of the pet test. (2) Screens: under the new build order all screens are rebuilt to the owner's UI design after the login slice; in the Q-112 times sub-slice the frontend changes only as far as the rule needs to work and be tested, with no polish or redesign. (3) Run-rule slip in 10h-4b (a targeted run was given a background time limit that was too short): every targeted and full run gets a time limit long enough for the whole run. Order: the Q-112 times sub-slice (with the Q-2026-10-18-133 and Q-2026-10-19-138 answers, pre-code design first); then stop and tell the owner, before slice 11. Recorded in docs/010.

**Owner answer (2026-10-20, fresh session, after the 10i-3 report).** Option (a). The preview's pending-draft check also lists a closed Settlement's waiting correction draft whose plan uses, or whose `REFUND` releases value into, a Credit held by a person of another Lease. The other Lease's Settlement waits until that draft is confirmed, rejected or withdrawn. No amount rule changes, only the order. The case leaves the slice 12 list when built. The slice 11 "out of date, record it again" message stays, because two drafts recorded at the same moment can still make one stale. Built in sub-slice 10i-4. Recorded in docs/010.

## Q-2026-10-20-147 — Q-112 times sub-slice: the Reservation's holding deposit `received_at` (blocks nothing in 10i-1 to 10i-3; nothing is built for it before your answer; recommendation (a)) (ANSWERED 2026-10-20: option (a), for sub-slice 10i-4; answer in docs/010)

**What the rule says.** Your answer (a) to Q-2026-10-14-112 point 1: a time that means the moment staff save the action comes from the database clock; a time that records something that happened before it was saved, like money received earlier, is not changed and is asked first. The Reservation create screen sends the device time at the save as `received_at` (`ReservationManagement.tsx`, `const now = new Date().toISOString()`); the route uses it twice: as the holding Security Deposit receipt's time (`app.deposit_receipts.occurred_at`) and as the deposit acceptance's `accepted_at`. Its name says "received", so it is asked first.

**What it records today.** The money's own receipt time is the Payment's `received_at`, entered by staff on the Payment screen and unchanged here. The Reservation create links an already confirmed Payment, and the database refuses a Deposit receipt dated before that Payment's confirmation time (`Deposit receipt Payment source is ineligible`) or more than 5 seconds after its own clock. So this time can never be the earlier moment the money was received; it can only be the moment staff put the confirmed Payment's money into the Deposit, which is what a Lease Deposit receipt already records with the database's own time (sub-slice 10e-2b-4b-2b).

**Example.** A Customer pays 200.00 in cash at 09:00; staff record and confirm the Payment at 09:05 (the Payment keeps "received 09:00"). At 09:40 staff create the Reservation with that Payment. Today the screen sends the device time: on a laptop 3 seconds fast the receipt is dated 09:40:03 (accepted); on one 2 minutes slow, a create right after the Payment's confirmation is refused (the receipt would be dated before the confirmation); on one set to the day before it is refused too. Under (a) the receipt and the acceptance are dated 09:40:00 by the database, and the Payment still says the money came at 09:00.

**Options.**
- (a) Both times come from the database clock at the save, as for the termination and the extension: the screen sends nothing, the route refuses a body that sends `received_at` (422), the service passes the database's statement time. One small sub-slice with its tests (the route and screen tests that send the field change, as the Q-112 answer covers).
- (b) Keep a staff time, but the screen asks for it explicitly (a "put into the Deposit at" field), still checked by the database as today.
- (c) Keep it as it is (a known limit; staff devices must keep a correct clock).

**Recommendation: (a)**, because the time cannot mean the moment the money was received (the database already refuses any time before the Payment's confirmation), the money's real receipt time stays on the Payment, and one clock rule is simpler for staff. If you choose (a), it is built when you send it (the build order pauses V1-056 after the Q-112 times sub-slice).

**What goes ahead.** Everything: 10i-1 to 10i-3 do not change the Reservation create.

**Owner answer (2026-10-20, fresh session).** Option (a): the Reservation holding deposit's receipt time and acceptance time come from the database clock at the save. The screen sends nothing, and the route refuses a body that sends `received_at` (422). The money's real receipt time stays on the Payment. Built in sub-slice 10i-4 (the frontend changes only as far as the rule needs to work and be tested). Recorded in docs/010.

## Q-2026-10-20-148 — Sub-slice 10i-2 security review round 1: a Security Deposit created after signing counts for the unpaid-Initial ground at once (blocks nothing; a known limit since 10e-2b-4c; nothing is built before your answer; recommendation (a)) (ANSWERED 2026-10-20: option (a), for sub-slice 10i-4; answer in docs/010)

**What your answer (b) to Q-2026-10-19-138 built (10i-2).** An increase of the required Security Deposit total counts for the unpaid-Initial termination ground (BR-LEASE-005) only from the later of Lease Start plus five days and five days after it was recorded, so the Customer always gets five days to pay an increase.

**The gap the security reviewer found (not new; on the slice 12 list since 10e-2b-4c as a known limit).** A walk-in Lease's Security Deposit is created by a `deposits.manage` command (`app.create_lease_security_deposit`) at any time after signing, with any first amount. The ground counts that first amount in full from the moment the Deposit exists. So a Deposit created late, or with a first amount higher than agreed, meets the ground at once, the same harm as Q-138 with one create command instead of an increase. Under DL-069 one person may hold `deposits.manage`, `leases.terminate` and `financial.approve`. Today neither the create nor the required-amount adjustment has an HTTP route (both come with slice 11), so staff cannot reach this or the Q-138 case yet; it affects the urgency only.

**Example.** A walk-in Lease starts on 1 March. The Customer pays the Initial Rent on time and hands over 500.00 for the Security Deposit. On 20 March staff create the Security Deposit at 600.00 (by mistake or on purpose) and record the 500.00 receipt. The ground is met at once (500.00 held, 600.00 required, after 6 March): the Lease can be terminated on the unpaid-Initial ground the same day, and a confirmed forfeiture draft keeps the whole 500.00. For an increase from 500.00 to 600.00 on 20 March, 10i-2 makes the Customer wait until 26 March.

**Options.**
- (a) The first amount of a Security Deposit created after the Lease was signed counts for the ground only on a termination business date after its creation date plus five days (the same five days as an increase; `deposits.created_at`, Asia/Phnom_Penh business dates). A Reservation's Deposit (created before signing) keeps today's rule. Every walk-in Security Deposit is created after signing (`app.create_lease_security_deposit` needs a SIGNED Lease), so each gets the five days; one created by Lease Start is not affected in practice, because its five days end by Lease Start plus five days, which the ground already requires. One small fail-closed sub-slice with its tests, built when you send it. Example: the Deposit created on 20 March counts from 26 March.
- (b) Keep it as a known limit (slice 12 list), with the slice 11 termination screen showing a Deposit created after Lease Start plus five days and its shortfall.
- (c) A Security Deposit created after Lease Start plus five days never counts for this ground; a later shortfall is handled by another ground or as debt.

**Recommendation: (a)**, because it gives a late or corrected first amount the same five days your answer gives an increase, and a create command by staff alone could then no longer end a Lease the same day; (c) would leave such a Deposit never enforceable through this ground.

**What goes ahead.** Everything: 10i-2 is committed as built; 10i-3 does not touch the ground. Under the build order (ops/V1_056_TAKEOVER.md section 8) a sub-slice for (a) would be built only when you send it.

**Owner answer (2026-10-20, fresh session).** Option (a): the first amount of a Security Deposit created after the Lease was signed counts for the unpaid-Initial ground only on a termination business date after its creation date plus five days (Asia/Phnom_Penh business dates). A Reservation's Deposit created before signing keeps today's rule. Built in sub-slice 10i-4. Recorded in docs/010.

## Q-2026-10-20-149 — 10i-4 pre-code design: a waiting `REFUND_RETURN` correction draft also gives value back to an existing Credit (blocks nothing; 10i-4c builds your Q-146 answer for `REFUND` only; recommendation (a)) (ANSWERED 2026-10-20: option (a), build in slice 12; answer in docs/010)

**What your answer says.** Q-2026-10-20-146, option (a): the preview also lists a closed Settlement's waiting correction draft whose plan uses, or whose `REFUND` releases value into, a Credit held by a person of another Lease. 10i-4c builds both parts: the plan part for every variant (its `CUSTOMER_CREDIT` steps), and the release part for the variant `REFUND` (its plan overlay `credits`, keyed by the Credit it gives value back to).

**What the answer does not name.** A `REFUND_RETURN` correction draft (sub-slices 10c-2b-1 and 10c-2b-2a: a Credit Refund paid by the closed Settlement came back) has the same overlay shape: it gives the returned amount back to the Credit the Refund came from, and its plan check reads that Credit with the amount added. While it waits, another Lease's Settlement can apply other money of that Credit, and the draft is then stale at its confirm (P5S02, fail closed, nothing written) and is recorded again. Where its plan also has a `CUSTOMER_CREDIT` step on that Credit, the plan part of 10i-4c already lists it; the release part alone does not.

**Example.** Customer C's Lease A is closed; A's Settlement refunded 300.00 of C's Credit K by bank transfer, and the transfer came back. A `REFUND_RETURN` correction draft of A waits; it gives the 300.00 back to K and its plan refunds it again in cash, with no `CUSTOMER_CREDIT` step. K also holds 200.00 of other money. C's second Lease B is terminated and B's Settlement applies K's 200.00 to B's cleaning charge and closes. Under (a) B's preview shows `PENDING_DRAFT` until A's draft is decided, and the draft is never stale this way. Under (b) the draft is stale at its confirm and staff record it again (the same 300.00 is refunded; no amount changes either way).

**Options.**
- (a) The release part also covers `REFUND_RETURN` (its overlay Credit held by a Lease person), in a later small fail-closed sub-slice when you send it, or in 10i-4c now if you say so. Only the order changes.
- (b) Keep it: the draft becomes stale and is recorded again (fail closed); a slice 12 note.

**Recommendation: (a)**, because it is the same case your Q-146 answer closes for `REFUND`, and it changes no amount, only the order.

**What goes ahead.** Everything: 10i-4a, 10i-4b and 10i-4c (for `REFUND`, as answered) do not depend on it.

**Owner answer (2026-10-20, fresh session, docs-only rules update).** Option (a). A waiting `REFUND_RETURN` correction draft is listed by the Final Settlement preview the same way as a `REFUND` draft: the release part of the Q-146 answer also covers a `REFUND_RETURN` draft whose plan overlay gives value back to a Credit held by a person of another Lease, and that other Lease's Settlement waits until the draft is confirmed, rejected or withdrawn. No amount rule changes, only the order. Not built now: the item stays on the slice 12 list, marked "answered (a), build in slice 12". Recorded in docs/010.

## Q-2026-10-21-150 — Login slice: the Staff and Manager bundle lines the rules do not name (blocks L1c; nothing is built before your answer; recommendation (a)) (ANSWERED 2026-10-21: (a), with a note; answer in docs/010)

**What the rules say.** DL-074 answer 1: Owner gets every capability; Manager gets "all daily work, approvals (`financial.approve`), reports, audit history, exports and the health page; no user or role administration"; Staff gets "daily data entry only (Customers, Reservations, Readings, recording Payments, preparing drafts); no approvals, no administration, no audit, no export". DL-080: `leases.sign`, `reservations.extend`, `leases.terminate` and `invoices.void` are Manager actions; Staff prepare the Final Settlement (`final_settlements.prepare`). Your answer G7: Staff get `payments.record` and `payments.allocate`.

**What is clear.** Staff get: `identity.read_self`, `customers.read`, `customers.manage`, `reservations.read`, `reservations.create`, `utility.read`, `utility_readings.record`, `payments.read`, `payments.record`, `payments.allocate`, `receipts.read`, `final_settlements.prepare`. Staff never get: `financial.approve`, `leases.sign`, `reservations.extend`, `leases.terminate`, `invoices.void`, `audit.view`, `identity.manage_access`, Settings access, the health capability, any export. Manager gets everything except `identity.manage_access` and Settings access.

**What the rules do not name for Staff** (each is "daily work" or "preparing a draft" only by reading): the reads `leases.read`, `invoices.read`, `deposits.read`, `credits.read`, `refunds.read`, `customer_ledger.read`, `rent_nonpayment.read`, `configuration.read`, `units.read`, `property.read`; Reservation `reservations.cancel` and move-in `reservations.complete`; Lease `leases.draft`, `lease_signers.manage`, `leases.inspect` (move-out inspection), `leases.move_out`, `leases.warn` (violation warning); Utility `utility_readings.correct`, `utility_meters.manage`, `utility.calculate`, `utility.estimate`; billing `invoices.create`, `invoices.issue`, `invoices.adjust`, `damage_charges.bill`; `receipts.reprint`; Deposits `deposits.manage`, `deposits.refund.qualify` (Pet Deposit review), `reservation_deposits.refund`; draft preparation `refunds.create`, `payments.reverse` (Payment return draft, but also the one-call Payment reversal), `payments.allocations.reverse` (wrong-Unit move draft, but also the one-call allocation reversal); Credit `credits.recognize`, `credits.apply`, `credits.reverse`, `credits.applications.reverse`; `late_payment.review`; `rent_nonpayment.case_manage`, `rent_nonpayment.event_post`; `exchange_rates.manage`. For the Manager: `property.manage` (create and update Units).

**Example.** A Customer pays 250.00 USD in cash for Unit U204's Rent of 250.00. Staff record it and pay the Invoice in one step (G7). The Customer then asks for a reprint of the Receipt: with `receipts.reprint` Staff do it; without it, Staff must call the Manager. The same day a Staff member types the Payment on the wrong Unit: with `payments.allocations.reverse` Staff can undo the allocation in one call (no approval); without it, the Manager does it.

**Options.**
- (a) Staff get every read named above, plus `reservations.cancel`, `reservations.complete`, `leases.draft`, `lease_signers.manage`, `leases.inspect`, `leases.move_out`, `utility.calculate`, `receipts.reprint` and `refunds.create` (a Refund is only a draft until a `financial.approve` holder confirms it). Staff do **not** get `leases.warn`, `utility_readings.correct`, `utility_meters.manage`, `utility.estimate`, `invoices.create`, `invoices.issue`, `invoices.adjust`, `damage_charges.bill`, `deposits.manage`, `deposits.refund.qualify`, `reservation_deposits.refund`, `payments.reverse`, `payments.allocations.reverse`, any `credits.*` change, `late_payment.review`, the `rent_nonpayment.*` changes or `exchange_rates.manage`, because each of them changes money or a Customer's standing at once. The Manager gets `property.manage`.
- (b) Staff get only the "clear" list; everything else is Manager only.
- (c) You give the list line by line.

**Recommendation: (a)**, because it lets Staff serve a Customer at the desk (see the Lease, Invoice, Deposit and Credit, move a Customer in, print a Receipt) while every change that moves money at once or affects a Customer's standing stays with a Manager. The bundles stay editable, so you can move a line later without a code change.

**What goes ahead.** L1a, L1b and L1d do not depend on it. L1c waits.

**Owner answer (2026-10-21, fresh session, with the approval of the login slice plan in commit 2aabe67).** Option (a), as recommended. Staff get no action that moves money at once or changes a Customer's standing. Sign Lease, Extend Reservation and Terminate Lease stay Manager actions (DL-080 item 2): `leases.sign`, `reservations.extend` and `leases.terminate` are in the Owner and Manager bundles only. The Manager gets `property.manage`. Built in L1c. Recorded in docs/010 DL-081.

## Q-2026-10-21-151 — Login slice: the Settings access capability, its name, and which of today's checks it replaces (blocks L1d and L5; nothing is built before your answer; recommendation (a)) (ANSWERED 2026-10-21: (a), with a note; answer in docs/010)

**What the rules say.** DL-074 answer 2: Settings access is its own capability given per user; only the Owner account class gives or removes it; the Owner always has it. DL-075: Settings covers the billing calendar, Reservation limits, Payment Methods, number letters and next numbers, Utility Rates, Services, cleaning rate groups and the Unit setup lists. DL-074 "Build in": the name and which of today's `service_rates.manage`, `utility_rates.manage` and `property.manage` checks it replaces are proposed now.

**Today.** `service_rates.manage` guards the Service rate change; `utility_rates.manage` the Utility Rate change; `property.manage` guards the Property update and configuration (`property_api.py`), the one-time charge due-days setting (`invoice.py`), Unit create and update (`unit_api.py`), the per-Unit cleaning rate (migration `20261016_81`) and a few reads.

**Example.** The Owner ticks Settings access for Manager Dara. Dara changes the Water Rate from a reading day. Staff member Sokha, with the Staff bundle, cannot see the change button. Later the Owner removes Dara's tick; Dara's next request is refused, without signing out.

**Options.**
- (a) Name it `settings.manage`. It replaces `service_rates.manage` and `utility_rates.manage` everywhere, and `property.manage` on the Property update, the Property configuration and the due-days setting. `property.manage` stays for Unit create and update and the per-Unit cleaning rate until the DL-075 Settings screens move the cleaning rate to rate groups (then those use `settings.manage` too). `settings.manage` can never be put in a bundle; it is given only per user, so the Owner keeps control of who has it. The two old capability names stay in the catalog with no route using them.
- (b) As (a), but `property.manage` is replaced everywhere, Unit create and update included (Units are created only by someone with Settings access).
- (c) Another name or split.

**Recommendation: (a)**, because creating a Unit is not one of the DL-075 Settings items, and keeping `settings.manage` out of bundles is the only way "only the Owner gives or removes it" holds once a Manager could edit a bundle.

**What goes ahead.** L1a to L1c and L2 to L4 do not depend on it; L1d and the L5 replacement wait.

**Owner answer (2026-10-21, fresh session, with the approval of the login slice plan in commit 2aabe67).** Option (a), as recommended. The capability is `settings.manage`. It is given per user, never in a bundle; the Owner always has it through the Owner account class. It replaces `service_rates.manage` and `utility_rates.manage` everywhere, and `property.manage` on the Property update, the Property configuration and the due-days setting; `property.manage` stays for Unit create and update and the per-Unit cleaning rate. Built in L1d and L5. Recorded in docs/010 DL-081.

## Q-2026-10-21-152 — Login slice: Owner accounts and what a new account's class sets (blocks L1a and L2; nothing is built before your answer; recommendation (a)) (ANSWERED 2026-10-21: (a); answer in docs/010)

**What the rules say.** DL-058 and DL-074 tie the Owner rights to the account class `owner`; SEC-074 says the bootstrap cannot make another Owner; "later accounts use normal authorized management". The rules do not say whether normal management may make a second account of class `owner`, or what a new account's class sets.

**Example.** Your spouse also runs the business. With (a) they get a Manager account with the Manager bundle and Settings access; they cannot reset you or give Settings access. With (b) you could make them a second Owner, who could then reset Managers and give Settings access too, and who could not be reset by you.

**Options.**
- (a) Exactly one Owner account (the bootstrapped one). The Owner creates Manager or Staff accounts only. The class sets the MFA rule (Manager required, Staff optional, Q-156) and the default bundle given at creation (Manager bundle or Staff bundle); the Owner may change the bundle later. The class never changes; to change a person's class, disable the account and create a new one (history stays).
- (b) The Owner may create more Owner accounts.

**Recommendation: (a)**, because DL-058 has no rule for one Owner recovering another, and one Owner keeps the Owner-only rights in one place.

**What goes ahead.** L1b to L1d. L1a and L2 wait.

**Owner answer (2026-10-21, fresh session, with the approval of the login slice plan in commit 2aabe67).** Option (a), as recommended: exactly one Owner account (the bootstrapped one); the Owner creates Manager or Staff accounts only; the class sets the MFA rule and the default bundle given at creation, and never changes. Built in L1a and L2. Recorded in docs/010 DL-081.

## Q-2026-10-21-153 — Login slice: who makes the one-time password, and a new account's first password (blocks L4; nothing is built before your answer; recommendation (a)) (ANSWERED 2026-10-21: (a); answer in docs/010)

**What the rules say.** DL-080 item 10: the one-time password the Owner gives after a reset works for 24 hours and must be changed at the first sign-in; the new password follows the 15 to 128 character rule. Today the reset screen asks the Owner to type the new password. The rules do not say who makes the one-time password, how a brand-new account gets its first password, or whether the reset also clears MFA.

**Example.** Staff member Sokha forgets her password at 09:00. The Owner presses Reset. With (a) the app shows a one-time password such as `river-candle-7410-orbit` once to the Owner, who tells Sokha in person. Sokha signs in at 09:10 and must choose her own new password before she can do anything. If she waits until 09:01 the next day, the one-time password no longer works and the Owner resets again.

**Options.**
- (a) The app makes the one-time password (random, about 20 characters, easy to read aloud), shows it once to the Owner and never again. A new Manager or Staff account gets its first password the same way (create, then a one-time password with the same 24 hours and forced change). The reset screen keeps the "also reset MFA" tick (today's `reset_mfa`): ticked, the Manager sets up the authenticator again at the next sign-in. An expired one-time password gives the normal "sign-in failed" message.
- (b) The Owner types the one-time password (as today), with the same 24 hours and forced change.

**Recommendation: (a)**, because a typed password tends to be short or reused, and the person changes it at once anyway.

**What goes ahead.** Everything before L4.

**Owner answer (2026-10-21, fresh session, with the approval of the login slice plan in commit 2aabe67).** Option (a), as recommended: the app makes the one-time password, shows it once to the Owner, valid 24 hours with a forced change at the first sign-in; a new Manager or Staff account gets its first password the same way; the reset keeps the "also reset MFA" tick; an expired one-time password gives the normal sign-in failure. Built in L4. Recorded in docs/010 DL-081.

## Q-2026-10-21-154 — Login slice: the details of "5 wrong tries, wait 15 minutes" (blocks L3b; nothing is built before your answer; recommendation (a)) (ANSWERED 2026-10-21: (a); answer in docs/010)

**What the rules say.** DL-080 item 10 and SEC-012: after 5 wrong tries the person waits 15 minutes, with the same message whether or not the account exists; login and recovery are limited by account and by source. The rules do not say when the 15 minutes start, whether tries during the wait add time, whether a correct sign-in clears the count, whether wrong MFA codes count, or the limit per source.

**Example.** At 08:00 someone types "sokha" with wrong passwords five times. With (a), from the 5th try at 08:02 every try for "sokha", even with the right password, gets "Too many tries. Wait 15 minutes and try again." until 08:17; typing more during the wait does not move 08:17. At 08:17 Sokha signs in with her right password and the count starts again from zero. The same message appears for a name that does not exist.

**Options.**
- (a) The count is per username (unknown names included) over a 15-minute window; the wait starts at the 5th wrong try and lasts 15 minutes; tries during the wait are refused without checking the password and do not add time; a correct sign-in clears the count; wrong TOTP codes and wrong recovery codes count as wrong tries for that account; per source address, 20 wrong tries in 15 minutes start the same 15-minute wait for that address; the counts are kept in the database, so a restart does not clear them. Anyone who knows a username can make that person wait 15 minutes; for the Owner that is accepted (the Owner waits, or uses the emergency server procedure).
- (b) As (a), but tries during the wait restart the 15 minutes.
- (c) Other values.

**Recommendation: (a)**, because it matches the words "wait 15 minutes" exactly, and a fixed wait is easy to explain at the desk.

**What goes ahead.** L1a to L3a. L3b waits.

**Owner answer (2026-10-21, fresh session, with the approval of the login slice plan in commit 2aabe67).** Option (a), as recommended: per username (unknown names included), the wait starts at the 5th wrong try within 15 minutes and lasts 15 minutes; tries during the wait are refused without checking the password and add no time; a correct sign-in clears the count; wrong TOTP and recovery codes count; 20 wrong tries per source address in 15 minutes start the same wait for that address; counts kept in the database. The Owner may be made to wait; accepted. Built in L3b. Recorded in docs/010 DL-081.

## Q-2026-10-21-155 — Login slice: password rule for later passwords, and the runtime key and blocklist files (blocks L3c, L4 and L7; nothing is built before your answer; recommendation (a)) (ANSWERED 2026-10-21: (a), with a note; answer in docs/010)

**What the rules say.** SEC-073 and API-100 give the first Owner's password rule in full (15 to 128 code points before and after NFC, local blocklist, no composition rule) and say the TOTP protection key never enters an ordinary environment value; it comes from an already-open root-controlled descriptor or an equivalent protected secret file. DL-080 says only "the 15 to 128 character rule" for the new password after a reset. The running API needs the same TOTP key to check sign-in codes, and today has no setting for it. Adding a path setting means editing `.env.example`, which you told me not to open in this session.

**Example.** After a reset Sokha chooses `chetana residence 2026`. With (a) it is refused because "chetana" is on the local blocklist, and she picks another.

**Options.**
- (a) Every new password (bootstrap, the forced change, later changes) uses one rule: 15 to 128 code points before and after NFC, and the same local blocklist. The API reads the blocklist and the TOTP key from protected files whose paths are settings (`APP_TOTP_KEY_FILE` and `APP_PASSWORD_BLOCKLIST_FILE`, paths only). On the Mac mini the key file is `/usr/local/etc/prm/totp_protection_key` (root-owned, mode 0600) and the API is started by a small wrapper that opens it as root and then runs as your user, like the bootstrap helper. I may open and edit `.env.example` in L3c to add the two path names (names only, no values).
- (b) Later passwords use only the 15 to 128 rule, without the blocklist.

**Recommendation: (a)**, because the same rule everywhere is simpler and the blocklist is what stops the most common guesses.

**What goes ahead.** L1a to L3b. L3c, L4 and L7 wait.

**Owner answer (2026-10-21, fresh session, with the approval of the login slice plan in commit 2aabe67).** Option (a), as recommended: one password rule for every new password (15 to 128 code points before and after NFC, the local blocklist); the API reads the TOTP key and the blocklist from protected files whose paths are the settings `APP_TOTP_KEY_FILE` and `APP_PASSWORD_BLOCKLIST_FILE`. In L3c only, Claude Code may open `.env.example` to add the two path setting names, with no values, and shows the added lines in the report. A real value, key or password is never written into it. The password credentials migration (`20260817_03`), `config/deployment/identity-secret-contract.json` and `docs/DEPLOYMENT_IDENTITY_SECRET_SCAFFOLDING.md` stay closed. Built in L3c, L4 and L7. Recorded in docs/010 DL-081.

## Q-2026-10-21-156 — Login slice: who turns on MFA for a Staff account (blocks the Staff part of L3c; nothing is built before your answer; recommendation (a)) (ANSWERED 2026-10-21: (a); answer in docs/010)

**What the rules say.** DL-056 and SEC-013: MFA is optional for Staff; Staff with MFA enabled must complete it. UI-110: Staff "can securely enroll when authorized". The rules do not say who authorizes it.

**Example.** Staff member Vanna works the evening desk alone and wants extra protection. With (a) the Owner sets Vanna's account to "MFA required"; at her next sign-in Vanna sets up the authenticator and from then on must give a code. Vanna cannot turn it on or off herself.

**Options.**
- (a) Only the Owner (`identity.manage_access`) sets a Staff account's MFA to required or optional; a Staff member does not turn it on alone in V1. Turning it off later is a reset with "also reset MFA" by the Owner.
- (b) A Staff member may turn MFA on for their own account; only the Owner may turn it off.

**Recommendation: (a)**, because it keeps one simple path and the Owner sees every account's MFA state.

**What goes ahead.** Everything except the Staff MFA path of L3c.

**Owner answer (2026-10-21, fresh session, with the approval of the login slice plan in commit 2aabe67).** Option (a), as recommended: only the Owner (`identity.manage_access`) sets a Staff account's MFA to required or optional; turning it off later is a reset with "also reset MFA". Built in L2 and L3c. Recorded in docs/010 DL-081.

## Q-2026-10-21-157 — Login slice: which actions need a recent password check, and how recent (blocks L3d and its routes in L2 and L4; nothing is built before your answer; recommendation (a)) (ANSWERED 2026-10-21: (a); answer in docs/010)

**What the rules say.** SEC-018 and API-097: the deployment must be able to require recent authentication or an extra factor for high-risk administration. The rules do not name the actions or the time.

**Example.** The Owner signed in at 08:00 and leaves the office PC unlocked at 11:00. Someone sits down and tries to reset the Manager's password. With (a) the app first asks for the Owner's password and TOTP code again, because the last check was more than 15 minutes ago.

**Options.**
- (a) A fresh password and TOTP code (within the last 15 minutes) for: resetting an account, creating or disabling an account, changing a bundle or a user's bundle, giving or removing Settings access, and turning a Staff account's MFA on or off. Money actions are not on this list (they keep their capability and draft checks).
- (b) The same list with 5 minutes.
- (c) Another list.

**Recommendation: (a)**, because these actions change who may do what, and 15 minutes avoids asking twice while the Owner sets up one new person.

**What goes ahead.** L1a to L3c.

**Owner answer (2026-10-21, fresh session, with the approval of the login slice plan in commit 2aabe67).** Option (a), as recommended: a fresh password and TOTP code (within the last 15 minutes) for resetting an account, creating or disabling an account, changing a bundle or a user's bundle, giving or removing Settings access, and turning a Staff account's MFA on or off; money actions are not on the list. Built in L3d (and used by the L2 and L4 routes). Recorded in docs/010 DL-081.

## Q-2026-10-21-158 — Login slice: the health route, and new routes in docs/005 (blocks only the health route and the new routes; recommendation (a)) (ANSWERED 2026-10-21: (a), with a note; answer in docs/010)

**What the rules say.** DL-074 answer 3: the health page is for Owner and Manager through a capability in their bundles. API-081 lists `GET /api/v1/operations/status` (API, worker, job, migration and backup freshness). The run rules allow new docs/005 routes only for the pending V1-055 items. The login slice needs three new routes: `POST /api/v1/auth/password-change` (L4), `POST /api/v1/users/{user_id}/settings-access` and `POST /api/v1/users/{user_id}/settings-access/remove` (L2).

**Options.**
- (a) The login slice adds the capability `operations.status.read` to the Owner and Manager bundles now; the route itself is built with V1-059, when the backup job and the Telegram alerts it reports on exist. Your approval of this plan also approves the three new routes above in docs/005.
- (b) The login slice also builds a first `GET /api/v1/operations/status` now (API, database, migration head and billing worker last run; backup "not set up yet").

**Recommendation: (a)**, because half of the status page would report on things that do not exist yet.

**What goes ahead.** Everything except the three routes and the health route.

**Owner answer (2026-10-21, fresh session, with the approval of the login slice plan in commit 2aabe67).** Option (a), as recommended: `operations.status.read` goes into the Owner and Manager bundles now; the route itself is built with V1-059. Approving the plan also approves the three new docs/005 routes: `POST /api/v1/auth/password-change`, `POST /api/v1/users/{user_id}/settings-access` and `POST /api/v1/users/{user_id}/settings-access/remove`; each is written into docs/005 by the sub-slice that builds it. Recorded in docs/010 DL-081.

## Q-2026-10-21-159 — Login slice: how to try the sign-in in a browser on the Mac mini (blocks L7; nothing is built before your answer; recommendation (a)) (ANSWERED 2026-10-21: (a), with a note; answer in docs/010)

**What the rules say.** SEC-015 and SEC-016: session tokens only over protected channels, `Secure` and `HttpOnly` cookies. The code uses `__Host-` cookies and accepts only an `https://` Origin. Today `compose.yaml` runs PostgreSQL only, the API runs on `http://127.0.0.1:8000` and the Vite dev server has no proxy, so a browser cannot sign in locally. Nothing in the rules says how local development is served.

**Options.**
- (a) Vite serves the frontend over HTTPS on `https://localhost:5173` with a certificate you make once with the macOS `openssl` (kept in the ignored `.local/` folder; Safari and Chrome are told to trust it once), and Vite forwards `/api` to the API. No download and no new package. The same setup is the base for the screen rebuild, where you test each area.
- (b) No browser sign-in before V1-059; only automated tests.

**Recommendation: (a)**, because the screen rebuild needs a browser sign-in on your Mac mini anyway.

**What goes ahead.** L1a to L6.

**Owner answer (2026-10-21, fresh session, with the approval of the login slice plan in commit 2aabe67).** Option (a), with one addition: the local certificate covers both `localhost` and the Mac mini's local network name, so the owner can also open the app on an iPad on the same Wi-Fi. The L7 runbook says how to trust the certificate on an iPad. No download and no new package. Built in L7. Recorded in docs/010 DL-081.

## Q-2026-10-21-160 — Login slice: read capabilities for Units and the Property (blocks the L5 part for the four reads; recommendation (a)) (ANSWERED 2026-10-21: (a), with a note; answer in docs/010)

**What the rules say.** SEC-002: access is denied unless the actor has an explicit capability for the action and its Property scope. Today `GET /properties/{property_id}`, `GET /properties/{property_id}/units`, `GET /units/{unit_id}` and `GET /units/{unit_id}/timeline` need only a signed-in user, with no capability and no Property check. A new capability needs your answer.

**Example.** A disabled Staff account cannot sign in at all; but an active account whose bundle you emptied on purpose (for example a person on leave) can still list every Unit and its history today. With (a) it cannot.

**Options.**
- (a) Two new capabilities, `property.read` and `units.read`, in all three default bundles, checked with the Property scope on these four routes.
- (b) Reuse `configuration.read` for all four.

**Recommendation: (a)**, because the Unit list is daily work for everyone, while `configuration.read` is about Settings.

**What goes ahead.** Everything except this part of L5.

**Owner answer (2026-10-21, fresh session, with the approval of the login slice plan in commit 2aabe67).** Option (a), as recommended: `property.read` and `units.read` in all three default bundles, checked with the Property scope on the four reads. In L5 the missing Origin and CSRF checks are also added to `POST /properties/{property_id}/units` and `PATCH /units/{unit_id}`. Built in L1b, L1c and L5. Recorded in docs/010 DL-081.

## Q-2026-10-21-161 — Login sub-slice L1b-1 review round 1: `billing.generate` is also a capability for people today (blocks the L1b-1 commit; the catalog row can never change once written; recommendation (a)) (ANSWERED 2026-10-21: (a); answer in docs/010)

**What the plan says.** The approved login slice plan (section 7.1 and L1b) says `billing.generate` "belongs to the billing service principal only" and can never be put in a role bundle. L1b-1 was built that way: its catalog row says "not assignable by a bundle".

**What the code does (found by the round 1 independent reviewer, checked).** People use `billing.generate` too: `POST /api/v1/properties/{property_id}/billing-runs/rent` and `.../billing-runs/utilities` (API-054, API-055; `billing_run_api.py`, `billing_run.py`) start a Rent or Utility billing run only for a signed-in human who holds `billing.generate` for the Property, and `GET /api/v1/billing-runs/{run_id}` reads a run's status with the same capability; the billing capabilities list shown on screen (`invoice_api.py`) includes it. The scheduled billing job has its own service principal and is not changed by either option.

**Example.** On 25 November the scheduled Rent run did not finish because the Mac mini was restarted. With (a) Manager Dara opens Billing and presses "Run Rent billing" for November; the run makes the missing Rent Invoices once (the run is idempotent). With (b) nobody can start it from the screen; the Owner restarts the job on the server.

**Options.**
- (a) `billing.generate` is a bundle capability. The Owner and Manager bundles hold it (the Manager bundle has "every assignable capability"); the Staff bundle does not (Q-150 (a) keeps `invoices.create` and `invoices.issue` from Staff, and a billing run creates and issues Invoices). Its catalog description becomes "Start a Rent or Utility billing run and read its status". Only `rent_nonpayment.evaluate` stays a service-principal-only capability, and `settings.manage` per user only.
- (b) Keep it out of every bundle, as the plan says. Then from L5 no person can start a billing run or read its status from the screen; API-054, API-055 and the run status read become worker-only (docs/005 changes), and the scheduled job is the only way to bill.

**Recommendation: (a)**, because it keeps today's working routes and fits DL-074 answer 1 ("Manager: all daily work"); the plan's sentence came from a survey that missed these routes.

**What goes ahead.** Nothing in the login slice: L1b-2 to L8 build on the catalog, and the catalog rows are append-only. The L1b-1 round 1 fixes are written down (ops/reviews/V1-056-login-L1b-1.md, a draft, not committed) and are made with your answer.

**Owner answer (2026-10-21, same session, after the L1b-1 stop).** Option (a). `billing.generate` goes in the Owner and Manager bundles, not in the Staff bundle. It is a bundle capability; its catalog description becomes "Start a Rent or Utility billing run and read its status". Built in L1b-1 (the catalog row) and L1c (the bundles). Recorded in docs/010 DL-081.

## Q-2026-10-21-162 — Login sub-slice L1b-1 security review round 1: may `identity.manage_access` be put in a role bundle? (blocks the L1b-1 commit with Q-161; recommendation (b)) (ANSWERED 2026-10-21: (b); answer in docs/010)

**What the rules say.** DL-074 answer 1: Owner "every capability, including user accounts, role bundles and settings"; Manager "no user or role administration". DL-058 and Q-152 (a): exactly one Owner account; the Owner-only resets are tied to the account class, not to a role name. Q-156 (a) says "only the Owner (`identity.manage_access`)". The approved plan (L1c) puts `identity.manage_access` in the Owner bundle and leaves it out of the Manager bundle; bundles stay editable by whoever holds `identity.manage_access`.

**The gap (security reviewer).** As a bundle capability, `identity.manage_access` can be ticked into any bundle by its holder. If it is ever ticked into a bundle a Manager holds, that Manager can create and disable accounts, edit bundles (also their own) and assign bundles, which is the user and role administration DL-074 keeps from Managers. Account resets are not affected: they are decided by the account class.

**Example.** The Owner edits the Manager bundle to add "see users" and by mistake ticks `identity.manage_access`. With (a), Manager Dara can now give herself `financial.approve` through a new bundle and create a Staff account for a friend. With (b) the tick is not offered: only the Owner account administers users and bundles.

**Options.**
- (a) Keep it a bundle capability, as planned. L2 refuses a holder who edits a bundle they hold or their own assignments, and the screen warns when it is ticked.
- (b) Make it an Owner-class capability: never in a bundle (like `settings.manage`); the grant reader gives it to the Owner account class only. The Owner bundle and the Manager bundle then hold the same bundle capabilities; the difference between Owner and Manager is the account class (`identity.manage_access`, `settings.manage`, the resets).
- (c) Make it per user, given only by the Owner (like `settings.manage`).

**Recommendation: (b)**, because there is exactly one Owner account (Q-152 (a)) and DL-074 gives user and role administration to the Owner only; (b) fails closed and needs no self-edit rules.

**What goes ahead.** As for Q-161: nothing, because the catalog row is append-only.

**Owner answer (2026-10-21, same session, after the L1b-1 stop).** Option (b). `identity.manage_access` comes only from the Owner account class and is never in any bundle. This keeps DL-058: only the Owner resets Manager and Staff accounts. Built in L1b-1 (the catalog row: Owner class only) and L1b-2 (the grant reader gives it to the Owner account class). Recorded in docs/010 DL-081.

## Q-2026-10-21-163 — Login sub-slice L1b-2 review round 3: two should-fix findings (blocks the L1b-2 commit; recommendation (a)) (ANSWERED 2026-10-21: (a))

**What happened.** L1b-2 (role bundles, assignments and the grant reader, migration `20270120_177`, not committed) passed review rounds 1 and 2 with no blocker, and every check and run is green (full PostgreSQL run P3: 2,465 passed). Review round 3 found no blocker but two should-fix items. The run rules let me fix round 3 findings without you only when they are text or new test assertions; these two are not, so I stopped.

**The two findings.**
- SF1 (test robustness): the new two-connection race test `test_two_assignments_of_one_bundle_at_the_same_time_wait_and_one_is_refused` can hang instead of failing if its 5-second wait check ever fails (for example on a very slow run): the waiting thread keeps the second connection busy, and the first connection, which holds the lock, is closed only after the second. Fix: roll back the first connection before joining the thread, and give the second connection a 15-second lock timeout. No rule or expected result changes.
- SF2 (a refusal that is narrower than the docs say): the bundle name check refuses control characters and most invisible format characters, but misses a few (for example the "isolate" direction marks U+2066 to U+2069, U+061C, U+180E, U+206A to U+206F, U+FFF9 to U+FFFB and the tag characters), and the control-character class depends on the database locale. Fix: list the C0 and C1 control ranges and these characters explicitly in the uncommitted migration's check, add two test names that must be refused, and keep the docs as written. This only refuses more names; nothing else changes.

**Example.** The Owner names a bundle "Staff" and, by a copy and paste from a chat app, a second one "Staff" with an invisible direction mark inside. Both would show as "Staff" on the bundle screen, and the Owner could assign the wrong one. With SF2 fixed, the second name is refused.

**Options.**
- (a) I make both fixes in the uncommitted L1b-2 work, run all checks and runs again, and do review round 4; I commit only if round 4 is clean, otherwise I stop again.
- (b) As (a), without round 4: commit when all checks and runs are green.
- (c) SF1 as (a); for SF2 I narrow the docs to the exact list of refused characters instead of changing the migration.

**Recommendation: (a)**, because SF2 changes a migration check, which a fresh reviewer should see once more before the rows become permanent.

**What goes ahead.** Nothing: L1c and the later sub-slices build on the L1b-2 tables, and L1b-2 is uncommitted work in the same files.

**Owner answer (2026-10-21, same session, after the L1b-2 stop).** Option (a): make both fixes, run every check and run the run rules need, then do review round 4 with an independent review agent, and commit L1b-2 only if round 4 is clean. If the auto-mode checker blocks that agent again, follow the run rule for a blocked review agent. Then continue with L1c and the later sub-slices; stop after L5 is committed (L6 waits for the owner's sign-in screen description).

## Q-2026-10-21-164 — Login sub-slice L1c: nine capabilities the Staff bundle answer does not name (blocks L1c; recommendation (a)) (ANSWERED 2026-10-21: (a))

**What the rules say.** Your answer to Q-2026-10-21-150 (a) (DL-081) lists what Staff get and what Staff never get, with your note "Staff get no action that moves money at once or changes a Customer's standing". DL-074 answer 1 gives Staff "preparing drafts". The Manager and Owner bundles hold every bundle capability.

**The gap (found in the L1c pre-code survey).** Nine bundle capabilities are in neither list: `deposits.dispose` (Lease Deposit forfeiture draft, and also the one-call Deposit disposition in `deposit.py`), `deposits.correct`, `reservation_deposits.dispose` (Reservation Deposit outcome draft, and also the Reservation cancel with a Security Deposit disposition route in `reservation_api.py`), `reservation_deposits.correct`, `reservation_deposits.override`, `refunds.correct`, `refunds.corrections.reverse`, `late_payment.charge_correction` and `late_payment.final_decision`. (`service_rates.manage` and `utility_rates.manage` are also unnamed, but L5 replaces them with `settings.manage`, which no bundle holds.)

**Example.** A Customer leaves without paying the last Rent and the Manager is out. With (a), Staff member Sokha cannot record the Pet Deposit forfeiture; she notes it and the Manager records the draft and confirms it the next day. With (b), Sokha records the forfeiture draft herself, but the same capability also lets her record a Deposit disposition in one call, which takes effect at once.

**Options.**
- (a) None of the nine is in the Staff bundle (each decides, overrides or corrects money, and two of them also have a one-call path that takes effect at once). The bundles stay editable, so you can add one later.
- (b) Staff also get `deposits.dispose` and `reservation_deposits.dispose` (they prepare drafts), but not the other seven.
- (c) You give the list line by line.

**Recommendation: (a)**, because it follows your note on Q-150 exactly and fails closed; a Manager confirms every money decision anyway.

**What goes ahead.** L1d (Settings access), which does not depend on the Staff bundle. L1c waits; L2 (which gives a new account its class's default bundle) builds on L1c.

**Owner answer (2026-10-21, fresh session).** Option (a), as recommended: none of the nine capabilities (`deposits.dispose`, `deposits.correct`, `reservation_deposits.dispose`, `reservation_deposits.correct`, `reservation_deposits.override`, `refunds.correct`, `refunds.corrections.reverse`, `late_payment.charge_correction`, `late_payment.final_decision`) goes in the Staff bundle. They stay in the Owner and Manager bundles, which hold every bundle capability. Built in L1c, which also records this answer in docs/010 DL-081.

## Owner rule (2026-10-21, fresh session): Settings access needs the sign-in code (MFA) — not a question; recorded here with the answer above

**The rule (owner's words, kept).** Any account that holds Settings access must use the sign-in code at every sign-in, the same as Owner and Manager accounts. The Owner can give Settings access to a Staff account only after that account has set up its sign-in code; if not, the give is refused with a plain message. No path may leave a Staff account with Settings access and no sign-in code. If a reset or removal path needs a choice from the owner, Claude Code writes a question with its recommendation.

**Real-life example (owner's).** Dara is Staff and keeps the riel rate up to date. Someone who learns Dara's password still cannot change Settings without Dara's phone.

**Where it is recorded.** docs/010: an "Amended by DL-081" line under DL-074 answer 2, and a short note in DL-081. It is built in its own small sub-slice after L1d (L1e, planned in ops/V1_056_PLAN.md section 7.3 with its pre-code design); a reset or removal path that needs the owner's choice gets its own question then.

## Q-2026-10-21-165 — Login sub-slice L1e: what a sign-in code reset or "MFA off" does to a Staff account's Settings access (blocks only that part of L2 and L4; recommendation (a)) (ANSWERED 2026-10-21: (a); answer in docs/010)

**What the rules say.** Your rule of 2026-10-21 (DL-081): any account that holds Settings access must use the sign-in code at every sign-in; no path may leave a Staff account with Settings access and no sign-in code. Q-156 (a): turning a Staff account's MFA off is a reset with "also reset MFA" by the Owner. Q-153 (a): the Owner's reset keeps the "also reset MFA" tick. Two built paths can reset a Staff account's sign-in code today, both in `app.perform_account_recovery`: the Owner's administrative reset with "also reset MFA" (`reset_mfa`, route API-099) and the emergency server procedure (DL-058). A recovery with a recovery code cannot reset it (that mode refuses `reset_mfa` and is for the Owner's own account).

**What L1e builds (no choice needed).** The Owner cannot give Settings access to a Staff account without a set-up sign-in code (plain message). And the app gives a Staff account's Settings access only while its sign-in code is set up and asked at every sign-in: after any reset, the Settings changes are refused at the next request, whatever path did it. So the rule already holds for what a person can do.

**The open point.** After such a reset, the Settings access record itself stays: the user list would still show the tick, although it does not work until a new sign-in code is set up.

**Example.** Dara (Staff) has Settings access and keeps the riel rate up to date. Dara's phone is lost; the Owner resets Dara's account with "also reset MFA". With (a), Dara's Settings access ends in the same step (recorded as a removal with the reason "sign-in code reset"); Dara sets up the code on the new phone, and the Owner ticks Settings access again. With (b), the tick stays, but Dara cannot change Settings until the new code is set up, then it works again by itself. With (c), the Owner must first untick Settings access, then the reset is allowed.

**Options.**
- (a) Every path that resets or turns off a Staff account's sign-in code (the Owner's reset with "also reset MFA", the Owner turning MFA off, the emergency server procedure) also ends its Settings access in the same step, as a recorded removal (who, when, reason). The Owner gives it again after the new code is set up.
- (b) The Settings access stays recorded and simply does not work until a new sign-in code is set up (what L1e already does); the user list shows "waiting for sign-in code".
- (c) Those paths are refused while the account has Settings access; the Owner removes it first.

**Recommendation: (a)**, because the user list then always shows the truth, every change of who may change Settings is a decision the Owner sees and records, and a lost phone does not quietly bring access back later. (b) is the most convenient; (c) adds a step at a stressful moment.

**What goes ahead.** L1e is built and does not depend on the answer. L2 (MFA on or off) and L4 (the reset with a one-time password) build their own steps first; only the part that touches Settings access waits. With (a), the existing `reset_mfa` path of `app.perform_account_recovery` (administrative and emergency modes) is the one that changes.

**Owner answer (2026-10-21, fresh session).** Option (a), as recommended. When an account's sign-in code is reset or its MFA is turned off, its Settings access is removed in the same step, as a recorded removal (who, when, reason). The Owner ticks it again once the new code is set up. Owner's example: Dara's phone is lost; the Owner resets Dara's sign-in code, and the user list at once shows that Dara has no Settings access until the Owner gives it again. The owner also agrees with the L1c ordering note: no build between L3a and L5 may be used. Built with the reset and MFA-off steps (L2 for MFA off, L4 for the Owner's reset, and the `reset_mfa` path of `app.perform_account_recovery`). Recorded in docs/010 DL-081.

## Q-2026-10-21-166 — Login sub-slice L2a: no route removes a role bundle from an account (blocks only that route in L2b; recommendation (a)) (ANSWERED 2026-10-22: (a))

**What the rules say.** Q-157 (a) lists "changing a bundle or a user's bundle" as an action that needs a recent password check. API-080 lists only `POST /users/{id}/role-assignments` (assign); no route removes an assignment. The run rules allow new docs/005 routes only with your yes; the plan approval named three new routes, not this one.

**What is built.** L2a builds the database function that removes an assignment (Owner only, with a reason, audited, and it ends the account's sessions because its rights shrink). Nothing can call it from the screen without a route.

**Example.** Staff member Sokha was given the Manager bundle by mistake when covering the desk for a week. With (a) the Owner opens Sokha's account, removes the Manager bundle with the reason "cover week ended", and Sokha's next request is signed out and works with the Staff bundle only. With (b) the Owner must disable Sokha's account and create a new one (Sokha gets a new username and password).

**Options.**
- (a) A new route `POST /api/v1/users/{user_id}/role-assignments/remove` with the bundle id and a reason, Owner only, with the same recent password check as the other Q-157 actions; written into docs/005 API-080 by L2b.
- (b) No removal route in V1: a wrong bundle is fixed by disabling the account and creating a new one.

**Recommendation: (a)**, because removing a bundle is the everyday way to change what a person may do, and Q-157 already treats it as a normal Owner action.

**What goes ahead.** L2a, and every other part of L2b and of the later sub-slices.

**Owner answer (2026-10-22, fresh session).** Option (a), as recommended: a new route `POST /api/v1/users/{user_id}/role-assignments/remove`, Owner only, with the bundle id and a reason; it calls the L2a function, which ends the account's sessions. Approving this answer also approves the new docs/005 route (written into API-080 by L2b). The recent password check of Q-157 is added to it by L3d, as for the other Q-157 routes. Built in L2b. Recorded in docs/010 DL-081.

## Q-2026-10-21-167 — Login sub-slice L2a review round 1: the runtime role may still run the unaudited Settings access functions of L1d (blocks nothing; recommendation (a)) (ANSWERED 2026-10-22: (a))

**What the rules say.** SEC-014: every capability change needs an immutable audit event. L1d built `app.give_settings_access` and `app.remove_settings_access` without an audit event, because the L2 routes would write it; L2a now builds `app.admin_give_settings_access` and `app.admin_remove_settings_access`, which call them and write the audit event. The runtime role (the API's database identity) may still run the two L1d functions directly. Taking that right away is a tightening, and it changes the expected result of a committed test (`test_settings_access_migration.py::test_the_runtime_role_reaches_settings_access_only_through_its_functions`), so it needs your answer.

**Example.** A future programming mistake in the API calls the old give function. With (a) the database refuses it, so no Settings access can be given without an audit event. With (b) the access is given, the grant row keeps who, when and why, but the audit history has no event for it. A second case (review round 2): the old give does not wait for an account change that is under way, so if it runs while the Owner turns Dara's MFA off, Dara can keep a recorded grant that starts working again by itself once a new sign-in code is set up, against your answer to Q-165; the audited give waits and is then refused.

**Options.**
- (a) A small migration in L2b revokes the runtime role's right to run the two L1d functions; the committed test is changed to expect "permission denied" and named in the report; the API calls only the audited functions.
- (b) Keep the right; L2b adds a test that the API never names the two L1d functions.

**Recommendation: (a)**, because it makes "every Settings access change is audited" a database rule rather than a coding habit.

**What goes ahead.** Everything. Until the answer, L2b calls only the audited functions.

**Owner answer (2026-10-22, fresh session).** Option (a), as recommended: in L2b a small migration takes away the runtime role's right to run the older `app.give_settings_access` and `app.remove_settings_access`, so only the audited `app.admin_give_settings_access` and `app.admin_remove_settings_access` are used. The owner approves the tightening and the change to the one committed test (`test_settings_access_migration.py::test_the_runtime_role_reaches_settings_access_only_through_its_functions`, which then expects "permission denied"); the change is named in the L2b report. Built in L2b. Recorded in docs/010 DL-081.

## Q-2026-10-21-168 — Login sub-slice L2a security review round 1: may a Staff account hold approval capabilities through a bundle the Owner edits? (blocks nothing; recommendation (a)) (ANSWERED 2026-10-22: (a))

**What the rules say.** SEC-021 and DL-074 answer 1: bundles are configurable data and a role name gives no power by itself. Your answer to Q-150 (a) lists what the default Staff bundle never gets (for example `financial.approve`, `invoices.void`, `payments.reverse`). Q-152 (a): the account class sets the default bundle at creation, and the Owner may change the bundle later. ops/V1_056_TAKEOVER.md section 4 asks the security review to check that Staff cannot confirm a draft.

**The point.** Today the Owner can add `financial.approve` to the Staff bundle, or assign the Manager bundle to a Staff-class account; that Staff member can then confirm drafts. Nobody else can do this: only the Owner edits bundles and assignments.

**Example.** The Manager is on leave for two weeks and the Owner wants Sokha (Staff) to confirm Refund drafts meanwhile. With (a) the Owner assigns the Manager bundle to Sokha for two weeks and removes it afterwards (Q-166). With (b) that is refused; the Owner must create a Manager account for Sokha.

**Options.**
- (a) Bundles stay fully configurable for every account class; the default Staff bundle keeps the Q-150 list, and the screen rebuild shows a warning when the Owner gives a Staff account a capability from the "never" list.
- (b) A Staff ceiling: a Staff-class account never gets the Q-150 "never" capabilities, whatever bundle it holds (the grant reader leaves them out, and assigning or editing such a bundle for a Staff account is refused).

**Recommendation: (a)**, because SEC-021 makes the bundles your configurable data, only you can change them, and (b) would make the class a hidden second rule that the bundle screen does not show.

**What goes ahead.** Everything; nothing built depends on the answer.

**Owner answer (2026-10-22, fresh session).** Option (a), as recommended: bundles stay fully configurable, as SEC-021 says; there is no Staff ceiling. When the Owner adds an approval or money capability to a bundle that Staff accounts hold, the screen shows a plain warning first. Owner's example: if the Owner adds Refund approval to the Staff bundle, the screen warns that every Staff user with that bundle can now approve Refunds. Nothing in the database or the API changes; the warning is built with the administration screens of the screen rebuild. Recorded in docs/010 DL-081.

## Q-2026-10-22-169 — Login sub-slice L2b-2: hidden characters in names and reasons (blocks nothing; recommendation (a)) (ANSWERED 2026-10-22: (a))

**What the rules say.** Nothing about hidden characters. Review notes of L1b-2, L2a and L2b-1 asked for this question with the name handling of L2b-2.

**What is built today (fail closed).** A bundle name, username, display name or audit name refuses control characters and most invisible characters, among them the zero-width space U+200B, the soft hyphen U+00AD and the direction marks. A reason (free text in the audit history) refuses control characters, line breaks and direction marks, and a reason with nothing visible, but keeps U+200B, U+200C and U+200D, because Khmer text uses them. Before saving, the API makes each name NFC and trims white space at either end, and turns each run of space characters (Unicode space separators) inside into one space; a control character or line break inside a name is not changed and the database refuses it. A username may have no white space but the ordinary space, so "ann lee" written with a no-break space is refused.

**The gaps.** (1) Some Khmer keyboards put a zero-width space (U+200B) between words, so a Khmer name typed that way is refused today with "A name has 1 to 128 visible characters and no hidden characters". (2) A few invisible characters are still accepted: in names, U+034F, the Hangul fillers (U+115F, U+1160, U+3164, U+FFA0) and the invisible Khmer vowels U+17B4 and U+17B5; in reasons, U+00AD, U+180E, U+FEFF, U+2060 to U+2064, U+FFF9 to U+FFFB and the tag characters U+E0000 to U+E007F. (3) The database does not check that a username is NFC, and the sign-in lookup does not make the typed username NFC yet (L3a will use the same rule as account creation). (4) Letters that look alike in other alphabets (for example a Greek "Ο" in "Οwner") are not refused.

**Example.** The Owner creates Staff member "សុខា ចាន់" on an iPad. The keyboard puts a zero-width space after "សុខា". With (a) the name is saved without the hidden character and looks the same on every screen. With (b) the Owner sees the refusal and must type the name again another way.

**Options.**
- (a) The API removes U+200B from a name before saving it (it never changes how the name looks), and refuses every character of gap (2) in names and reasons; a later migration checks that a username is NFC, and sign-in uses the creation rule (gap 3). A bundle name that differs from another only by U+200B is then a duplicate and is refused. Gap (4) stays a practice point: the Owner reads new names on the account list.
- (b) Keep today's rule: names with U+200B are refused; the gap (2) characters are refused too.
- (c) Keep everything as it is today.

**Recommendation: (a)**, because a Khmer name typed in the normal way should be accepted, while a hidden character must never make two names look the same or hide text in the audit history.

**What goes ahead.** Everything. Until the answer, names with U+200B stay refused (fail closed) and the gap (2) characters stay accepted. Option (a) or (b) is a small later change: the API name step, one migration for the name check and the reason check, and their tests.

**Owner answer (2026-10-22, fresh session).** Option (a), as recommended. Khmer keyboards put an invisible space (U+200B) between words, so the API removes U+200B from names and reasons before saving them, and refuses the few other invisible characters still accepted (gap (2)). If one of those others is needed in normal Khmer typing (for example U+200C or U+200D), it is not refused: a new question with a recommendation is written instead. The same rule applies wherever the login slice checks names or reasons (bundle names, usernames, display names, audit names and the reasons of the administration routes; the sign-in lookup uses the creation rule for the username, gap (3)). Gap (4) stays a practice point. Other parts of the app with the same kind of check (for example Customer names) are not changed now; they go on the slice 12 list. Owner's example: the Owner creates Staff member "សុខា ចាន់" on an iPad; it is saved, and the name looks the same on screen. Built in sub-slice L2c, before L3a. Recorded in docs/010 DL-081.

## Q-2026-10-22-170 — Login sub-slice L2c: U+200C and U+200D in names (blocks nothing; recommendation (a)) (ANSWERED 2026-10-22: (a))

**What the rules say.** Your answer to Q-2026-10-22-169 (a): the API removes U+200B from names and reasons and refuses the other hidden characters still accepted; a character that normal Khmer typing needs (for example U+200C or U+200D) is not refused, and a question is written instead.

**What is built today.** Since sub-slice L1b-2 a name (bundle name, username, display name, audit name) refuses U+200C (zero-width non-joiner) and U+200D (zero-width joiner), with the other invisible characters. A reason keeps both. L2c changes neither: it refuses nothing new among them. Unlike U+200B, which only marks where a line may break, U+200C and U+200D can change how the letters around them join, so removing them could change how a name looks.

**The point.** I could not check every Khmer keyboard. If a keyboard you use puts U+200C or U+200D into a name typed in the normal way, that name is refused today with "A name has 1 to 128 visible characters and no hidden characters".

**Example.** The Owner types the new Staff member "សុខា ចាន់" on the iPad: it is saved (L2c removes the U+200B the keyboard adds). The Owner then pastes a name copied from a Word file that holds a U+200C between two letters. With (a) the name is refused and the Owner types it again on the keyboard. With (b) it is saved with the U+200C, and a second account whose name differs only by that U+200C looks the same on the account list.

**Options.**
- (a) Keep refusing U+200C and U+200D in names; reasons keep them.
- (b) Accept U+200C and U+200D inside a name, between two Khmer letters only; usernames and bundle names compare names without them, so two names that differ only by them are refused as duplicates.

**Recommendation: (a)**, because the names typed on the iPad, Mac and Windows Khmer keyboards I know of need only U+200B, which L2c now removes, and a hidden joiner must never make two names look the same. If your keyboard does put U+200C or U+200D into normal names, answer (b).

**Three related points (review rounds 1 and 2 of L2c; all three fail closed today; tell me if any of them is wrong for you).** (1) A name also refuses the emoji variation selector U+FE0F, so a display name with an emoji such as "❤️" is refused (a reason keeps U+FE0F). (2) A reason refuses the old invisible Khmer vowels U+17B4 and U+17B5, so a reason pasted from an old document that holds them is refused and must be typed again; it also refuses the tag characters, so a flag emoji such as the flag of Scotland is refused in a reason (country flags such as 🇰🇭 are kept). (3) The database now also refuses a name with a space other than the ordinary space, or two spaces in a row; the API already turns them into one ordinary space before saving, so nothing typed on a screen changes; it only stops a future program mistake from saving a name that looks like another.

**What goes ahead.** Everything; nothing built waits for this answer.

**Owner answer (2026-10-22, fresh session).** Option (a), as recommended: names keep refusing U+200C and U+200D; reasons keep them. If the owner later finds a Khmer keyboard that puts them into normal names, the owner says so. The three related points: (1) a name keeps refusing an emoji with U+FE0F; names do not need emoji. (2) A reason keeps refusing flag emoji made with tag characters, and U+17B4 and U+17B5. (3) Odd and double spaces are not refused on the screen. The API tidies a name before saving it: every space other than the ordinary space becomes an ordinary space, two or more spaces in a row become one, and spaces at the start and the end are removed. The database rule stays as the last guard. Sign-in tidies the typed username the same way, so the person can still sign in. Owner's example: Staff types "Sokha  Chan" with two spaces on the iPad; it is saved as "Sokha Chan" and nobody sees an error. Binding rule for L7 (the L2c note, made binding by the owner): the protected first-Owner bootstrap stores the username by the same rule as sign-in (NFC, tidied, no U+200B), with a test, so the first Owner can always sign in. Built in a small sub-slice before L3a (the implementer names it in the report). Recorded in docs/010 DL-081.

## Q-2026-10-23-171 — Login sub-slice L2d: tabs and line breaks in names (decided by Claude Code under the owner's 2026-10-22 rule)

**The point.** Q-2026-10-22-170 (a) says odd and double spaces in a name are tidied, not refused. A tab, a line break or another control character is white space too, but it is not a space a keyboard puts between words.

**Decision (technical; it does not change who may do what, money, or what staff may do).** Only the Unicode space separators (category Zs: the ordinary space, the no-break space, the thin and other typographic spaces, the ideographic space) are tidied. A tab, line break or other control character inside a name stays refused (`422 INVALID_NAME`), as before, because it comes from a paste mistake and the database refuses it; at either end of a name it is trimmed, as before. Built in L2d. The owner can change this later.

**Example.** Staff types "Sokha  Chan" with two spaces: saved as "Sokha Chan". A name pasted from a spreadsheet as "Sokha" + tab + "Chan" is refused; the Owner types it again.

## Q-2026-10-23-172 — Login sub-slice L3a-1: flood guard values, the session read and the username length (decided by Claude Code under the owner's 2026-10-22 rule)

**The points (technical; they do not change who may do what, money, or what staff may do).** (1) Until L3b builds your 5-tries rule in the database, sign-in keeps the existing in-memory guard: 20 tries per username and 100 per source address in 15 minutes, per API process. (2) Reading the session (the screen asks when its session ends) does not count as activity, so an idle screen still signs out after 30 minutes. (3) The sign-in username is at most 128 characters, the longest username the app saves.

**Example.** Someone tries 25 passwords for "sokha.chan" in five minutes: from the 21st try every try is refused with the normal sign-in failure until the 15 minutes pass (L3b then makes this 5 tries, as you answered in Q-154). Sokha leaves the iPad on the session page for 31 minutes: the next action asks her to sign in again.

**Decision.** As above. Built in L3a-1. The owner can change it later.

## Q-2026-10-23-173 — Login sub-slice L3a-2: the time a revoked session records, and activity only for usable sessions (decided by Claude Code under the owner's 2026-10-22 rule)

**The points (technical; they do not change who may do what, money, or what staff may do).** (1) From L3a-2 every request counts as activity on the session. When the Owner disables an account, or a person signs out, while that person's own request is being handled, the database refused the revocation because it would be dated a moment before the last activity; a person who kept clicking could stop their own revocation. The revocation is now dated the later of the two times (migration `20270127_184`), so it always succeeds; the time differs from before by at most the moment the two requests overlap. (2) A session that the app refuses (account disabled, needing MFA, without a class) gets no activity recorded.

**Example.** The Owner disables Sokha's account at 10:00:00.000 while Sokha's iPad loads a page at 10:00:00.010. Before: the disable failed with "try again". Now: Sokha's session ends, dated 10:00:00.010, and the next page asks Sokha to sign in.

**Decision.** As above. Built in L3a-2. The owner can change it later.

## Q-2026-10-23-174 — Login sub-slice L3b: technical choices of the wrong-try count (decided by Claude Code under the owner's 2026-10-22 rule)

**The points (technical; they do not change who may do what, money, or what staff may do).** (1) The count keeps sha256 digests of the normalized username and of the request source, never the typed text. (2) The wait answer of `POST /api/v1/auth/login` is the existing generic 429 (`RATE_LIMITED`, "Too many requests.") with `Retry-After` (the seconds left) and `no-store`; the sign-in screen writes the owner's wait message from it in L6. (3) Every refused password check counts as one wrong try: a wrong password, an unknown username, a disabled account and an account without a class, so the answers are the same for every username. (4) A correct password of an account that needs MFA neither counts nor clears: the completed MFA challenge clears the count in L3c, so a known password cannot wipe a count of wrong sign-in codes; before the MFA step the password is checked again for a wait, under the locks of the count (review round 1, security). (5) A correct sign-in clears the wrong tries up to the last one recorded; a parallel wrong try recorded after this sign-in's password check is cleared too (at most one or two tries, so a person who signs in correctly never meets a stale wait). (6) The in-memory flood guard of Q-2026-10-23-172 stays in front and still answers its own refusal with the plain 401.

**Example.** Sokha types a wrong password twice and then the right one: she signs in and the count starts again from zero. Someone types "nobody.here" three times: the third try gets the same 429 with `Retry-After: 300` as Sokha would.

**Decision.** As above. Built in L3b. The owner can change it later.

## Q-2026-10-23-175 — Login sub-slice L3b: the wrong-try rows keep pseudonymous keys for ever (blocks nothing; recommendation (a)) (ANSWERED 2026-10-23: (a))

**What is built.** Every wrong sign-in try is a row with the sha256 digest of the typed username and of the source address. The rows are append-only and never removed, and they are in every backup. A sha256 digest without a secret key can be reversed by trying names, or the whole range of IPv4 addresses, in seconds; if a person types a password into the username box by mistake, its digest stays in the database, and a weak password could be found from a stolen backup by trying many passwords quickly (review round 1, security).

**Example.** Sokha pastes her password into the username box by mistake on 2 November. The row stays. If a backup copy were stolen in 2027, someone could try billions of guesses against that row's digest; a long passphrase still holds, a short or common one may not.

**Options.**
- (a) In L3c, when the API first reads the protected key file (Q-155), key the digests with HMAC-SHA256 under a key derived from it (Python standard library `hmac`, no new package, no new secret), and add an Owner-run way to remove wrong-try rows older than 30 days in slice 12 (an additive, reviewed procedure; the waits never last longer than 15 minutes, so old rows change nothing). The rows written before L3c keep their plain digests until that removal. Note (review round 2): the database cannot make the keyed digest without the key, so (a) also needs a forward migration that replaces the clear's check that the actor's own username gives the digest, with a test that a correct sign-in still clears the count.
- (b) Keep plain sha256 digests and keep the rows for ever.

**Recommendation: (a)**, because it removes the offline guessing risk without a new package or a new secret, and old rows have no use after their wait.

**What goes ahead.** Everything; L3b works the same either way.

**Owner answer (2026-10-23, same session).** Option (a), as recommended: in L3c the digests are keyed with a key derived from the protected key file; no new package, no new secret, and the key is never printed. Removing wrong-try rows older than 30 days goes on the slice 12 list. Recorded in docs/010 DL-081.

## Q-2026-10-23-176 — Login sub-slice L3b: "in a row" has no time limit (blocks nothing; recommendation (a), as built) (ANSWERED 2026-10-23: (a))

**What the rule says.** The owner's amended rule (2026-10-23): after 3 wrong tries in a row the person waits 5 minutes; after 2 more (5 in a row) 15 minutes; then every 2 more another 15 minutes, until a correct sign-in. Q-154 (a) counted wrong tries within 15 minutes; the amended words "in a row" and "until a correct sign-in" have no time limit.

**Example.** Sokha types a wrong password twice on Monday evening and goes home. On Tuesday morning she types it wrong once more. With (a) that is her 3rd wrong try in a row, and she waits 5 minutes. With (b), the Monday tries were more than 15 minutes ago, so Tuesday's try is her first.

**Options.**
- (a) Count every wrong try since the last correct sign-in, with no time limit (as built in L3b).
- (b) Forget wrong tries older than 15 minutes, as Q-154 (a) did.

**One more point (review round 2).** A correct sign-in clears a real person's count, while an unknown username's count never clears. So someone who makes 2 wrong tries for "sokha" and for "nobody", and 1 more for each a day later, sees "nobody" get the wait answer and "sokha" the plain failure if Sokha signed in in between: that shows that "sokha" exists and that she signed in. With (a) this works across days; with (b) only within 15 minutes. It cannot be closed fully without changing the rule that a correct sign-in clears the count.

**Recommendation: (a)**, because it follows the words "in a row" and "until a correct sign-in" exactly; the point above is small next to a 5-minute wait for every typing mistake, but (b) narrows it. Tell me if you meant (b); it is a small change in the count.

**What goes ahead.** Everything; L3b is built with (a).

**Owner answer (2026-10-23, same session).** Option (a), as recommended: no time limit, as built. Recorded in docs/010 DL-081.

## Q-2026-10-23-177 — Login sub-slice L3b review round 3: a burst of parallel tries can still test passwords by timing (blocks the L3b commit; recommendation (a)) (ANSWERED 2026-10-23: (a))

**What review round 3 found (blocker; the round 3 rule says stop).** The wait check before the password check runs in its own short transaction, so up to 20 tries for one username sent at the same moment (the in-memory flood guard's limit per process) all pass it and all have their password checked. The wrong ones after the 3rd get the wait answer at once. A correct one is checked a second time inside the session transaction (the L3a-1 guard against a password reset racing the sign-in) and only then meets the wait; it gets the same wait answer, but about one password check later (tens to hundreds of milliseconds), which a measuring attacker can see. So about 20 passwords per burst are tested while your rule allows 3, then 2.

**Example.** Someone sends 20 guesses for "sokha" in the same second. 19 wrong ones answer "wait" after about 0.1 seconds; if one of them is Sokha's real password, that answer comes after about 0.2 seconds. The attacker now knows her password, although every answer said "wait".

**Options.**
- (a) Remove the second password check from the session transaction: the first check returns which stored password it checked, and the session transaction compares that with the stored password it reads (any change, also a reset to the same password, writes a new stored value, so the L3a-1 reset guard still holds). A correct password that meets a wait then answers after exactly one password check, like a wrong one. New test: count the password checks of a correct sign-in that meets a parallel wait (exactly one). Then all checks and runs again and review round 4.
- (b) Keep the code and record the timing difference as a known limit.

**Recommendation: (a)**, because it closes the gap with a smaller sign-in path, no new package and no change to who may do what; the reset guard keeps working.

**Owner answer (2026-10-23, same session).** Option (a), as recommended: the second password check is replaced by the comparison of the stored password value, with a test that such a sign-in checks the password exactly once; all runs again as the run rules say, then review round 4; L3b is committed only if round 4 finds no blocker, otherwise stop. Recorded in docs/010 DL-081.

**What went ahead.** Nothing in L3b was committed before this answer. L3c, L3d and L4 change the same files (`auth_flow.py`), so they do not start; L5 would share `ops/traceability.json`, the plan and docs with the uncommitted L3b, so it does not start either.


## Q-2026-10-23-178 — Login sub-slice L3c-2a: sign-in code checks and the start-up warning (decided by Claude Code under the owner's 2026-10-22 rule)

**The points (technical; they do not change who may do what, money, or what staff may do).** (1) A sign-in code is accepted for the current 30-second step of the database clock and the step before it, so a code typed at the end of its 30 seconds still works; each step is used once, and only after the last step used. (2) The pre-authentication step lasts 5 minutes (the cookie's own time) and is completed once. (3) The start-up warning of owner item 4 is written when the API starts with a database and without the key file; without a database nobody can sign in, so no warning is written. The application log shows only the event `security.protected_key_file_missing` (the log keeps only fixed fields), never a key, a path or a file's content. (4) A used step and an MFA proof name their enrollment and session without a database foreign key; their insert checks do the same job, so the existing refusal to empty the session and sign-in code tables stays unchanged.

**Example.** Sokha's phone shows 482913 at 09:00:28 and she presses the button at 09:00:31: the code is accepted. Someone who watched her screen types 482913 again at 09:00:40: it is refused, because that step was used.

**Decision.** As above. Built in L3c-2a. The owner can change it later.


## Q-2026-10-23-179 — Login sub-slice L3c-2b: setting up a sign-in code at sign-in (decided by Claude Code under the owner's 2026-10-22 rule)

**The points (technical; they do not change who may do what, money, or what staff may do).** (1) The authenticator app gets the standard `otpauth://totp/` link; it shows the name "Property Rental" and the username, and uses the 6 digits, 30 seconds and SHA-1 that the database stores. (2) A sign-in code set up by the API is stored with the key identifier `runtime-` and 32 hexadecimal characters, derived from the key file with HKDF-SHA256, so another key file gets another identifier and the key itself is never stored or shown. (3) One pre-authentication step sets up one sign-in code: the link is answered once; to get a new link the person signs in again, and that sign-in's set-up turns the unconfirmed code off, so it can no longer be confirmed. (4) During a wait for wrong tries the set-up waits too (429), as the code challenge does. (5) The first code is checked as at the challenge: the current or the previous 30-second step of the database clock, and a wrong code counts as a wrong try.

**Example.** A new Manager, Dara, signs in, scans the link with a phone and closes the page before typing the code. Dara signs in again and gets a new link; the code from the first scan no longer works, and the code from the second scan finishes the sign-in.

**Decision.** As above. Built in L3c-2b. The owner can change it later.


## Q-2026-10-23-180 — Login sub-slice L3c-2b: a new sign-in code after a reset with only the password (needs the owner)

**What happens today (as the approved plan says).** When the Owner resets a person's sign-in code without giving a new password (the reset with "also reset MFA" of the account recovery, the emergency procedure, or turning a Staff account's MFA off and on again), the account has MFA `required` and no sign-in code. At the next sign-in, whoever knows the password sets up a new sign-in code on their own phone. The emergency procedure can do this for the Owner account too.

**Why it matters.** A sign-in code is often reset because a phone was lost or stolen, and then the password may be known to someone else too. With the rule today, that person can sign in first and put the account's sign-in code on their own phone. The usual security advice is that a new sign-in code after a reset needs more than the password.

**Example.** Dara, a Manager, loses a phone that also had the password saved. The Owner resets Dara's sign-in code only. The finder signs in with the saved password before Dara does and sets up the sign-in code on the finder's phone.

**Options.** (a) Recommended: every sign-in code reset of an account that needs MFA also gives a one-time password (the L4 reset), so setting up the new code needs the new password; turning a Staff account's MFA on again counts as a reset. (b) Keep the rule today and tell the Owner, in the reset screen, to reset the password too when a phone is lost. (c) Something else the owner names.

**Nothing waits.** L3c-2b is built as the approved plan says; the answer is built in L4 (or in its own sub-slice before L5).

**Owner answer (2026-10-23): (a).** Every sign-in code reset also issues the L4 one-time password, so setting up a new sign-in code always needs the new password too. This covers the recovery with "also reset MFA" (the Owner's emergency procedure included) and a Staff account's MFA turned off and on again. The owner's example: Sokha loses a phone that has the password saved; the Owner resets Sokha's sign-in code, the old password stops working at once, and the Owner gives Sokha a new one-time password in person, so the finder cannot sign in and put the code on the finder's own phone. Built in L4.


## Q-2026-10-24-181 — Login sub-slice L3c-2c-1: the first recovery codes and their regeneration (decided by Claude Code under the owner's 2026-10-22 rule)

**The points (technical; they do not change who may do what, money, or what staff may do).** (1) The first 10 recovery codes are given once to a session made with the account's sign-in code in the last 15 minutes (review round 1), while the account has no live set of codes; after that, new codes come only by regeneration, which replaces the whole set. (2) Regeneration needs a sign-in code given in the last 15 minutes (the same time as the owner's answer to Q-2026-10-21-157); with an older one the person signs in again. (3) The codes keep the existing format of the bootstrap's codes (43 letters, digits, `-` and `_`, from 32 random bytes) and are stored only as Argon2id verifiers. (4) An account has at most one live set; two requests at the same moment leave one set and the other is refused. (5) The flow writes the codes itself with the existing generator and verifier, in the same database transaction that checks the session. (6) At most 5 sets of one account in 15 minutes (review round 2), so nobody can keep the server busy with the slow hashing; a sixth request is refused and the person waits.

**Example.** Dara, a new Manager, sets up the sign-in code and then saves the 10 recovery codes shown once. Months later Dara wants new codes: Dara signs in with the sign-in code, asks for new codes within 15 minutes, and the old codes stop working at once.

**Decision.** As above. Built in L3c-2c-1. The owner can change it later.


## Q-2026-10-24-182 — Login sub-slice L3c-2c-2: signing in with a recovery code (decided by Claude Code under the owner's 2026-10-22 rule)

**The points (technical; they do not change who may do what, money, or what staff may do).** (1) The recovery codes keep their present form (43 letters, digits, `-` and `_`, as the bootstrap's codes) and stay stored as Argon2id verifiers; a try compares the typed code with every usable code of the account (at most 10), so a wrong and a right code take the same time. This is affordable because a try needs the right password and a 5-minute sign-in step, every wrong try is counted with the waits of the owner's rule, and one account's tries run one at a time. (2) White space typed or pasted around the code is removed; nothing else is changed in what was typed. (3) A wrong recovery code counts as a wrong try, like a wrong sign-in code, recorded as a recovery-code try (review round 2), so the history shows which was guessed. (4) The right code is used up at once and ends every other session of the account, as the existing account recovery with a recovery code does, and the use is recorded in its audit. (5) A session made with a recovery code ends when the account's sign-in code is reset or turned off, or when the codes are replaced (review round 2); codes made before a sign-in code reset never work with the new sign-in code; it cannot get or replace recovery codes (the person signs in with the sign-in code for that, or the Owner resets the sign-in code). (6) A recovery code works only where the account already has a sign-in code; it does not replace setting one up. (Review round 1: point 1 keeps the present form; whether the codes should be easier to copy by hand, for example in groups of letters that ignore upper and lower case, stays open for L7, before the first Owner's codes are printed.)

**Example.** Sokha's phone is in the repair shop. Sokha signs in with the password and one of the 10 recovery codes from the paper in the drawer; that code never works again, and any session Sokha left open elsewhere ends. When the phone is back, Sokha signs in with the sign-in code as before.

**Decision.** As above. Built in L3c-2c-2. The owner can change it later.


## Q-2026-10-24-183 — Login sub-slice L3d-1: how a session is reauthenticated (decided by Claude Code under the owner's 2026-10-22 rule)

**The points (technical; they follow the owner's answer (a) to Q-2026-10-21-157 and do not change who may do what).** (1) A reauthentication asks for the password and, for an account that needs MFA, the sign-in code from the phone; a recovery code is not accepted here, because the owner's answer names "password and TOTP code". An account that needs no MFA (a Staff account without a sign-in code) gives the password alone; none of the actions of Q-157 is open to such an account. (2) A wrong password or sign-in code counts as a wrong try of the username, with the same waits as at sign-in; the screen sends no network address here, so the session stands in for it. (3) Each 30-second step of the sign-in code is used once, also across sign-in and reauthentication. (4) A successful reauthentication gives the screen a new CSRF token. (5) The session cookie itself stays the same (review round 1: a security standard, ASVS, asks for a new one at reauthentication; replacing it needs a new kind of sign-in proof, because a session's proof belongs to one sign-in step; the cookie is `__Host-`, HttpOnly, Secure and SameSite, and every high-risk action also needs the CSRF token; slice 12 list). (6) One reauthentication of an account runs at a time; a second one sent at the same moment is refused at once without being checked or counted.

**Example.** The Owner signed in at 08:00 and wants to disable Dara's account at 11:00: the screen asks for the password and the code on the phone, and after that the Owner has 15 minutes for the actions of Q-157 (the check comes with L3d-2).

**Decision.** As above. Built in L3d-1. The owner can change it later.

**Owner answers (2026-10-24), login sub-slice L3d-1.** (1) The review agent that the auto-mode checker blocked in review round 2 of L3d-1 is not retried on the Mac; the cloud session runs review round 2 of L3d-1. (2) Session cookie at reauthentication: build a separate reauthentication cookie, set only at reauthentication and also required by L3d-2. This replaces point 5 above. The cloud session builds it in L3d-1.

## Q-2026-10-24-184 — Login sub-slice L3d-2: how the 15-minute check of Q-2026-10-21-157 works (decided by Claude under the owner's 2026-10-23 22:30 rule)

**The points (technical; they follow the owner's answer (a) to Q-2026-10-21-157 and do not change who may do what, money, or what staff may do).** (1) The check guards: creating an account; disabling an account; turning an account's MFA on or off; creating a role bundle or changing one; giving a bundle to an account or removing it; giving or removing Settings access; and the Owner's reset of an account (built with L4). A change of an account's names alone is not on the list, and neither is signing an account out everywhere (it only takes access away). (2) Only a reauthentication with the password and the sign-in code counts, made in the last 15 minutes on the database clock, by the same browser session, shown by its separate reauthentication cookie (owner answer of 2026-10-24 to Q-2026-10-24-183); a copied session cookie alone never passes. A password-only reauthentication (an account with no sign-in code) never counts. (3) A sign-in finished with the sign-in code, and the first set-up of a sign-in code, also count as a reauthentication of the new session for 15 minutes, because the person has just typed the password and the code; a sign-in with a recovery code does not. (4) Only the session's latest such reauthentication counts, and only while its sign-in code is still the account's active one. (5) Without one the action answers 403 `REAUTHENTICATION_REQUIRED` ("Please enter your password and sign-in code again, then try again.") and writes nothing; the screen then asks for the password and the code and sends the action again (screens: L6). (6) The check runs first in the action's own transaction, before the capability check; the capability is still checked after it. (7) "Made after the latest password change" is not checked separately: the L4 binding (every password change ends all the account's sessions in the same step) already makes an older reauthentication useless. (8) The window for the first recovery codes and their regeneration also moves to the reauthentication cookie in the next small step, L3d-2b; until then it accepts a sign-in with the sign-in code in the last 15 minutes, as built in L3c-2c-1.

**Example.** The Owner signs in at 08:00 with the password and the code on the phone, and adds Dara's account at 08:10 without being asked again. At 11:00 the Owner wants to disable Dara's account: the app asks for the password and the code again, then the Owner has 15 minutes.

**Decision.** As above, decided by Claude under the owner's 2026-10-23 22:30 rule. Built in L3d-2. The owner can change it later.

**Review round 1 of L3d-2 (2026-10-24), clarifications of the points above.** (6) More exactly: the route's own checks (the administration capability, the account or bundle and the Property) come first, then this check, then the database functions' Owner check; so a signed-in account that is not the Owner and has no recent reauthentication is told to reauthenticate before it is refused. (3) At a sign-in the password is checked when the code is asked for, and the code must follow within 5 minutes (the challenge's life), so the 15 minutes can end up to about 20 minutes after the password was typed; accepted, because the password and the code are one sign-in. (4) The sign-in code is checked as still active when the action starts; every way of turning an Owner's sign-in code off today also ends the account's sessions, which the action holds, and L4 keeps that rule for its resets. The action's connection now has time limits (5 seconds per statement, 3 seconds for a lock wait; a lock wait over the limit answers "Try again").

**Built (2026-10-24), point 8:** login sub-slice L3d-2b moves the window for the first recovery codes and their regeneration to the reauthentication cookie, as described.

## Q-2026-10-24-185 — Login sub-slice L4: how the Owner's reset with a one-time password works (decided by Claude under the owner's 2026-10-23 22:30 rule)

**The points (technical; they follow the owner's answers (a) to Q-2026-10-21-153, Q-2026-10-21-165 and Q-2026-10-23-180 and do not change who may do what, money, or what staff may do).** (1) Records: one append-only row per one-time password (the account, the Owner, the reason, the issue time and its end 24 hours later on the database clock); a mark on the account's password while it is a one-time password not changed yet; a pre-authentication record of 10 minutes for the change step (no session, no actor); one append-only row per change. The password itself is never stored or logged, only its Argon2id verifier. (2) The app makes the one-time password: 16 letters and digits in 4 groups of 4 (for example `k7m2-x9qp-4hrt-w3nd`), from 31 signs that are easy to read aloud (no 0, 1, i, l or o); about 79 bits. Q-153's example used words; the repository has no word list and nothing is downloaded. (3) Order at sign-in: the one-time password, then the new password, then the sign-in code where MFA is required (set up again after "also reset MFA"), then the session. A one-time password used after its 24 hours gets the normal "sign-in failed" answer and counts as a wrong try. (4) The new password follows the shared rule (15 to 128 code points before and after NFC, the local blocklist file) and must differ from the one-time password; the blocklist file is required with a database in every environment except `development` and `test`, and an empty setting counts as unset (L3c-1 binding). (5) Order of locks: every replacement of a password or a sign-in code takes the account's `recovery-codes:` lock, then its `password-credential:` lock, before anything else; every session write (sign-in, sign-in code, recovery code, set-up, reauthentication) takes the `password-credential:` lock shared as its first statement. So a session made with an old password or code either commits first and is ended by the replacement, or waits and is refused (the L3a-1 and L3d-1 bindings). (6) The old recovery function no longer resets in the administrative mode; its emergency mode (the Owner's procedure) resets a sign-in code only with a new password and then also ends the live recovery codes. (7) Only a Manager or Staff account is reset, by its stored class (SEC-075; decides the L1a note); the Owner's own reset is the emergency procedure. (8) A new account: the create step answers its first one-time password in the same transaction. (9) A Staff account's MFA turned off also gives a one-time password in the same transaction and ends its recovery codes (Q-180). (10) Evidence: one row in the recovery audit (administrative, completed) and one in the administration history (`identity.account.one_time_password_given`, with the reason); neither holds the password or its verifier. (11) The Owner sees the one-time password once, in the answer to the reset (or the create), with `Cache-Control: no-store`; it is never shown again.

**Example.** Sokha forgets her password. The Owner presses Reset (with a fresh sign-in code in the last 15 minutes), writes "Forgot the password" and gets `k7m2-x9qp-4hrt-w3nd` once. Sokha's open sessions end at once. She signs in with it, must choose her own new password, then types her sign-in code and is in. If she waits 25 hours, the one-time password gives "sign-in failed" and the Owner resets again.

**Decision.** As above, decided by Claude under the owner's 2026-10-23 22:30 rule. Built in L4a (database), L4b (sign-in and reset) and L4c (the screen types and the docs). The owner can change it later.

**Built (2026-10-24), clarifications from review round 1 (decided by Claude under the owner's 2026-10-23 22:30 rule):** the forced change takes only the account's `password-credential:` lock (it never touches the sign-in code or the recovery codes); the new password is also refused when it is the one-time password in capitals, without its hyphens or with spaces; the emergency mode is stricter than before (a sign-in code is reset only together with a new password). Known and left for later: the emergency mode of `app.perform_account_recovery` can still be called by the runtime role (move it to the server-only role in slice 12); `APP_ENVIRONMENT` defaults to `development`, where the blocklist and the key file are optional (the start-up warning of L3c-1 stays). Review round 2 notes, left for slice 12: the forced change comes before the sign-in code, so a person who learns a one-time password of an account that kept its code can set its password (no session without the code; the Owner resets again); a change step has no limit of refused tries in its 10 minutes (only the holder of the step can try, two Argon2id checks each); the one-time password typed in full-width signs is not refused (outside "case or spacing"); the blocklist file has no owner and mode check like the key file.

## Q-2026-10-24-186 — Login sub-slice L5: how every route is closed to strangers (decided by Claude under the owner's 2026-10-23 22:30 rule)

**The points (technical; they follow the owner's answers (a) to Q-2026-10-21-151 and Q-2026-10-21-160 and do not change who may do what, money, or what staff may do).** (1) One check is added to every group of routes except the health routes, `/identity/me` and the sign-in routes (13 operations, listed in the inventory test). It runs before the request body is validated: without a signed-in user the answer is 401; for a change (anything but GET, HEAD and OPTIONS) the configured Origin and the CSRF pair are then required (403). So a stranger never learns from a validation error what a route expects, and a change from another site is refused before its body is checked. (Review round 1: FastAPI parses the JSON before any check, so a body that is not JSON answers 400; the generated documentation pages are turned off, so no route list is open either.) The route's own checks stay as they were and still run after it. The customer ledger reads keep refusing any GET body first (400 to everyone; they reveal nothing). (2) The signed-in user is found once per request, so a request reads the session and records its activity once. (3) As Q-151 (a) approved: the Service rate and Utility Rate changes, the Property update, the Property configuration update (Payment Methods) and the one-time charge due-days setting check `settings.manage` (the Owner always has it; a Manager or Staff account only when the Owner gives Settings access; L1e). The old names `service_rates.manage` and `utility_rates.manage` stay in the catalog and in the default bundles but no longer open a route; the database functions keep their audit labels for now (an exception to the rule that the stored evidence names the capability used; fixed in slice 12, review round 1). `property.manage` stays for Unit create and update and the move-out cleaning rate (until the DL-075 Settings screen); the riel rate keeps `exchange_rates.manage` (not part of Q-151). (4) The Property configuration read accepts `settings.manage` or `property.manage`, so a Manager who looks after Units still sees the business configuration and a person with Settings access sees what they edit. (5) The route inventory test walks every operation of the app: every one outside the open list answers 401 without a session, with no body, an empty body or an unexpected body; every change answers 403 without the Origin or the CSRF pair; a signed-in user with no capability never gets a change to succeed and gets nothing from a read. Without a database many reads check their capability in the database (503, fail closed) or hide what exists (404), so the test accepts those answers there; the real 403 of the Settings routes is tested on a throwaway database with signed-in accounts.

**Example.** A page on another website tries to send a Utility Rate change with the Owner's cookie: it has no CSRF token, so the answer is 403 before anything is read. Someone without a session tries any route: 401, whatever they send.

**Decision.** As above, decided by Claude under the owner's 2026-10-23 22:30 rule. Built in L5. The owner can change it later.
