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

## Q-2026-10-05-24 — Before sub-slice 8c: answer 3 of Q-2026-10-05-23 conflicts with the text of BR-DEP-023 and BR-DEP-026 (OPEN; does not block 8a-2; needed before 8b's preview path and 8c)

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
