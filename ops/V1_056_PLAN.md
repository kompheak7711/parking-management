# V1-056 plan

Written 2026-10-03 by Claude Code under ops/V1_056_TAKEOVER.md section 1. Status: DRAFT, waiting for owner approval. No slice starts before the owner approves this plan and answers the blocking questions.

Scope: Final Settlement, deposits, refunds and permanent correction history. Rules: DL-068, DL-069 and the docs 001, 002 and 003 amendments in commit 6732b8e. Read with AGENTS.md, ops/V1_055_RUN_RULES.md and ops/V1_056_TAKEOVER.md. The owner asked for this plan file in the repo; that request overrides the run-rules line that forbids tools from saving plan files.

## 1. What exists today (read-only survey)

- Capabilities are code strings checked by the application (for example `deposits.dispose`, `refunds.create`, `invoices.void`, `invoices.adjust`, `credits.apply`). The database checks the active actor and Property lists. There is no capability catalog table; access administration answers "unavailable". Adding `financial.approve` is therefore a code constant plus database function checks, not a catalog row.
- Refunds: `app.refunds` (Reservation Deposit, migration 21) and the Credit/Pet Refund services (migration 41, `refund.py`). Refunds run at once; there is no draft step and no Refund method column.
- Deposit dispositions run at once through `deposits.dispose` for three grounds only: `BR-DEP-022` (pet noncompliance), `BR-DEP-023` (voluntary early), `BR-LEASE-005` (unpaid Initial obligation). Termination bases are `VOLUNTARY_EARLY`, `CUSTOMER_VIOLATION`, `SIGNED_LEASE_OTHER` and `UNPAID_INITIAL_OBLIGATION`.
- Payment Allocation reversal exists (`payment_allocation.py`, `reverse_allocation`).
- Move-out inspection findings carry `pet_related` (migration 60). One-time charges and Damage charges exist (migration 65). The final Utility Invoice exists (migration 72). The Property due-days setting exists (9b).
- Units have no cleaning rate. Payment Methods are a global table `app.payment_methods`.
- Lease `end_date` is optional in the Lease draft and is checked only as later than the Start Date.
- Final Settlement has no code, no table and no traceability entry. docs/004 (DB-SETTLE-001 to 006) and docs/005 (API-070 to 072) already describe the design.
- Last migration: `20261010_75`. New migrations start at `20261011_76`.
- Traceability has 2445 entries, all `implemented`. 12 of the 13 new DL-069 rule IDs have no test (only BR-CREDIT-014 is mapped).

## 2. Order changes and why

- Refund methods and the joint-Signer recipient move from position 7 to position 3. Reason: slices 6 (Pet Deposit rest refunded) and 9 (Settlement Refunds) create Refunds, and every new Refund must carry a method and a reference note. Building the method list first avoids a later rework of those slices.
- Final Settlement (old 8) is split into two slices (draft and preview, then confirm and close). One slice would be too big for one checkpoint.
- HTTP and screens (old 10) are split into five slices, one per area, each with its own commit and security review.
- I recommend a security review also for slice 5 (hand-back VOID and credit Adjustment) and slice 10 (post-settlement corrections), because both change what a Customer owes. The takeover list does not require it; the owner decides (Q17).

## 3. Slices

Each slice: one local checkpoint commit, explicit paths, secret and diff scan, independent review (fresh subagent) before the commit, review saved under `ops/reviews/`, one line in ops/NOW.md after the commit. "Sec" means an extra security review.

### Slice 1 — Lease End Date is a month end (BR-LEASE-031, BR-LEASE-013)
- Change: Lease draft, amend and sign paths reject an End Date that is not the last day of its calendar month. Service validation in `lease.py` plus the same check inside the database draft/sign functions.
- Migration: `20261011_76` replaces the Lease draft and sign function bodies with the extra check. This rejects input that was accepted before, so it is a tightening change (Q1). No table-level CHECK, so existing rows are untouched.
- Tests: rejection of 30 May, acceptance of 31 May and 29 Feb 2028; database function rejects a direct call; no Rent Invoice for a month after the End Date (billing run over the End Date month and the next month). Existing fixtures with non-month-end End Dates (about 19 test files have dated fixtures; one known `2028-01-09`) need narrowing with docs/010 notes.
- Sec: no.

### Slice 2 — `financial.approve` and the draft-then-confirm model (BR-AUTH-010, BR-AUTH-008, BR-AUTH-009)
- Change: new capability constant `financial.approve`. New generic tables `app.financial_drafts` (id, Property, kind, payload JSON with fixed schema per kind, prepared_by, prepared_at, reason, expected financial revision) and `app.financial_draft_events` (append-only: CONFIRMED, REJECTED, WITHDRAWN, with actor, time, reason). A draft has no financial effect. Confirm runs the kind's existing command function in the same transaction, with the confirming actor, and fails if the source changed since the draft (financial revision check). Each draft is confirmed at most once (unique partial index on CONFIRMED).
- Migration: `20261012_77` additive (two tables, guard triggers that forbid UPDATE and DELETE, SECURITY DEFINER functions `app.record_financial_draft`, `app.confirm_financial_draft`, `app.close_financial_draft`, EXECUTE to the runtime role only).
- Tests: Staff without `financial.approve` cannot confirm (service and database); draft has no effect on balances, ledger or Deposit; confirm is idempotent and once only; stale draft rejected; reject and withdraw need a reason; history is append-only (UPDATE and DELETE refused).
- Sec: yes.

### Slice 3 — Refund methods and joint-Signer recipient (BR-REFUND-014, BR-REFUND-015)
- Change: configured Refund methods list (seeded with Cash and Bank transfer), managed by `property.manage`. New Refunds record a method and a reference note. Deposit Refund recipient is the Primary Tenant unless a recorded written agreement of all Signers names another Signer; the named person must be a Signer of that Lease. All amounts USD cents. No deadline.
- Migration: `20261013_78` additive: `app.refund_methods`, nullable `refund_method_id` and `reference_note` on new Refund rows (old rows keep null), a Refund draft kind, a recipient-agreement table.
- Tests: method required for every new Refund; inactive method rejected; note length bounds; recipient is the Primary Tenant by default; another Signer only with agreement text; a non-Signer rejected; USD only; old Refund rows unchanged.
- Sec: yes (old slice 7).

### Slice 4 — Unit cleaning rate and move-out cleaning charge (BR-UNIT-014, BR-MOVEOUT-013, BR-SVC-001, BR-MOVEOUT-006)
- Change: Unit cleaning rate in USD cents, set with `property.manage`, history kept. At move-out an authorized user issues the cleaning charge as a one-time charge from the Unit's rate at that moment (rate snapshot on the line). Due Date = issue date + Property due-days, with the existing BR-INV-018 override. Reduction only by a linked credit Adjustment with a reason. Refused when the Customer never moved in. Billed at most once per Lease.
- Migration: `20261014_79` additive: Unit cleaning rate history table, new one-time charge category `UNIT_CLEANING`, issue function.
- Tests: charge equals the rate at issue; later rate change leaves the charge unchanged; never-moved-in refused; second charge refused; Due Date default and override; reduction by credit Adjustment only.
- Sec: no.

### Slice 5 — Hand-back month (BR-RENT-030, BR-RENT-024, BR-RENT-026, BR-LEASE-021, BR-MOVEOUT-010)
- Change: a service that, for an early-terminated Lease with a hand-back date before the 5th, lets an authorized user (a) VOID the whole unpaid hand-back-month Rent Invoice with a reason, including fixed Service lines, and the next month's Invoice generated on the 25th when the hand-back is between the 25th and the month end; (b) keep a fully paid Invoice (no action); (c) remove the unpaid rest of a partly paid Invoice with a linked credit Adjustment and a reason. It checks the conditions and refuses otherwise. Nothing runs automatically. Uses existing `invoices.void` and `invoices.adjust` (Q8).
- Migration: `20261015_80` additive (eligibility read function and a guarded wrapper over the existing VOID and Adjustment functions).
- Tests: hand-back on the 4th unpaid gives whole VOID with Trash line; on the 5th refused (BR-RENT-024 applies); fully paid refused; partly paid gives credit Adjustment equal to the unpaid rest; hand-back on the 26th covers the next month's Invoice; notice date ignored; original Invoice and Payment rows unchanged.
- Sec: recommended (Q17).

### Slice 6 — Deposit forfeiture and Pet Deposit cases (BR-DEP-018, 019, 022, 023, 026, 027)
- Change: forfeiture and Pet Deposit use become draft kinds confirmed by `financial.approve`. Forfeiture is always the whole Security Deposit and is never applied to what the Customer owes. New grounds: non-pet violation termination and 30-day Rent nonpayment default termination (Q10). Pet Deposit at those terminations and at unpaid-Initial termination pays valid pet damage first (findings with `pet_related`) and the rest is refunded through a Refund draft (slice 3). Pet noncompliance keeps both deposits (BR-DEP-022 unchanged).
- Migration: `20261016_81` additive: new disposition ground values, draft kinds, a guard that a forfeited Security Deposit cannot be the source of any application.
- Tests: each ground; forfeiture equals the full held amount; an application from a forfeited deposit is refused at the database; Pet Deposit pays pet damage first and the Refund draft gets the rest; pet noncompliance keeps both; draft has no effect until confirmed; audit fields per BR-DEP-019.
- Sec: yes.

### Slice 7 — Wrong-Unit Payment move (BR-PAY-042)
- Change: a draft records the source allocation, target Invoice and the confirmation text (both Customers, who, date, how). Confirm by `financial.approve` reverses the wrong allocation and allocates the same Payment to the target Invoice in one transaction. Blocked if the released value already became Customer Credit or a Refund that is not reversed. Payment amount, date and Receipt never change. No Credit moves between Customers.
- Migration: `20261017_82` additive (draft kind, move link table, confirm function).
- Tests: move succeeds and both Invoices show correct balances; first Invoice becomes unpaid and later late-payment/nonpayment evaluation counts from the move, earlier records unchanged; blocked when Credit or Refund exists; Payment row and Receipt unchanged; Staff cannot confirm.
- Sec: yes.

### Slice 8 — Final Settlement draft and preview (BR-SETTLE-001 to 007, 016, 017, DL-032)
- Change: `final_settlements` (one per terminated Lease), obligation snapshots (Invoices, Late-payment Charges, cleaning charge), preview in DL-032 order: obligations, Customer Credit first, Pet Deposit to pet-related lines, explicit Security Deposit applications (not when forfeited), explicit remaining Pet Deposit (Customer choice or staff with reason), remaining balance, Refunds. Blocking issues listed (for example final Utility not issued, cleaning charge missing).
- Migration: `20261018_83` additive (DB-SETTLE-001, 002, 004, 006 plus the draft kind).
- Tests: order is exactly DL-032; no inferred FIFO between Deposit types; forfeited Security Deposit never offered; normal Lease end offers Security Deposit then refund of the rest; preview changes nothing.
- Sec: yes.

### Slice 9 — Final Settlement confirm and close (BR-SETTLE-008 to 015, 016)
- Change: confirm by `financial.approve` executes the chosen Credit applications, Deposit applications and Refunds in DL-032 order and closes the Settlement in one transaction, revalidating every source. The unpaid rest stays as debt on the Primary Tenant's Customer Ledger; no write-off. A closed Settlement is never reopened.
- Migration: `20261019_84` additive (close function, closure snapshot, guards forbidding UPDATE of closed rows).
- Tests: atomic close; stale draft rejected; debt shows on the Primary Tenant's ledger for joint Signers; no reopen path exists at the database; every step is a separate linked record.
- Sec: yes.

### Slice 10 — Post-settlement corrections (BR-SETTLE-013)
- Change: correction draft linked to the closed Settlement with a reason; kinds per Q15; confirm by `financial.approve`; no time limit; the closed Settlement row is never changed.
- Migration: `20261020_85` additive (DB-SETTLE-003, 005).
- Tests: correction years after closure accepted; closed Settlement row unchanged; correction effect linked by exactly one typed foreign key; Staff cannot confirm.
- Sec: recommended (Q17).

### Slices 11a to 11e — HTTP routes and staff screens
- 11a: Lease End Date error, Unit cleaning rate, cleaning charge, hand-back month actions.
- 11b: draft list, draft detail, confirm, reject, withdraw (shared by all kinds).
- 11c: Refund methods, Refund drafts, joint-Signer agreement, deposit forfeiture and Pet Deposit drafts.
- 11d: Wrong-Unit Payment move.
- 11e: Final Settlement (API-070 to 072), preview, confirm, corrections.
- Each: routes in the existing style, docs/005 entries, frontend client layer, screens with loading, empty, success and error states, accessible forms, backend route tests and frontend tests.
- Sec: yes for every part (CSRF, session, deny-by-default, no Staff confirm, no customer data in logs).
- Note: the app still has no working login, so there is no browser check; that waits for the login slice (DL-067).

### Slice 12 — Documentation, traceability, final gates
- docs 004 to 007 updated; every new rule ID has a test and an appended traceability entry; TEST-118 passes locally.
- Full gates once: backend format, lint, type check, tests; full PostgreSQL suite; frontend format, lint, type check, tests, build; audit (the known braces advisory stays until V1-059).
- Final independent review of the whole V1-056 diff, owner report, request for one push.

## 4. Questions for the owner (with my recommendation)

Blocking questions are marked (B). I will not start a slice whose question is open.

1. (B, slice 1) Making the Lease draft and sign functions reject a non-month-end End Date is a tightening change. Does DL-069 ("V1-056 adds the validation") count as owner approval for this one tightening? Recommendation: yes, function check only, no table CHECK, existing rows untouched, historical fixtures narrowed with docs/010 notes.
2. (slice 1) The End Date is optional on a Lease draft. Recommendation: check it only when present, and require a month-end End Date at signing.
3. (B, slice 2) Which existing capability lets Staff record each draft kind? Recommendation: Refund drafts `refunds.create`; forfeiture and Deposit use `deposits.dispose`; Payment move the existing allocation reversal capability; Final Settlement and corrections need a preparer capability that does not exist. Options: reuse `deposits.dispose`, or approve a new `final_settlements.prepare`. I recommend the new `final_settlements.prepare` because SEC-020 lists "prepare and close Final Settlements" as its own family; this needs your answer.
4. (B, slice 2) May the same person prepare and confirm a draft (for example the Owner alone)? Recommendation: allowed, both actors recorded, because SEC-022 says the system must not require two people; you can still give Staff only the prepare capability.
5. (slice 2) Draft life: Recommendation: a draft can be rejected (approver) or withdrawn (preparer) with a reason; no expiry; confirm fails if the underlying balances changed since the draft.
6. (B, slices 3 and 6) Existing direct paths run at once today: Credit Refunds, Pet Refunds, Reservation Deposit Refunds and dispositions, and termination deposit dispositions. BR-AUTH-010 says Refunds and deposit forfeiture are drafts. Recommendation: from V1-056 every new Refund and every Deposit forfeiture (Lease and Reservation) goes through a draft; the old direct routes return a clear error pointing to the draft route; old records stay unchanged. This changes existing API behavior and existing tests. Please confirm, or limit drafts to Lease-related actions only.
7. (slice 3) Refund methods: one global list like Payment Methods, or per Property? Recommendation: global, like `app.payment_methods`.
8. (slice 5) Does the hand-back VOID or credit Adjustment need a draft and `financial.approve`? BR-AUTH-010 does not list it. Recommendation: no draft; existing `invoices.void` and `invoices.adjust` with a reason.
9. (slice 5) Partly paid hand-back Invoice: the credit Adjustment removes the unpaid rest of every line (Rent and fixed Service lines), consistent with the whole-Invoice VOID. Recommendation: yes, per line.
10. (B, slice 6) How does the system know the forfeiture ground? Termination bases today are `VOLUNTARY_EARLY`, `CUSTOMER_VIOLATION`, `SIGNED_LEASE_OTHER` and `UNPAID_INITIAL_OBLIGATION`; pet versus non-pet violation and the 30-day Rent nonpayment default are not separate bases. Recommendation: the forfeiture draft takes the ground from the termination record (governing rule and linked warnings or Serious Default event) and refuses when it cannot be derived; no new termination basis.
11. (slice 6) Existing disposition functions may accept a partial forfeiture amount. Requiring the full amount for new forfeitures rejects input that was accepted before. Recommendation: enforce full amount only in the new draft path; leave the old function as is (it is no longer reachable once Q6 is approved).
12. (slice 6) "Valid pet damage" means move-out inspection findings with `pet_related = true` that were billed as Damage charges. Recommendation: yes; nothing else counts unless staff link it with a reason.
13. (B, slice 4) Is the cleaning charge issued by an explicit staff command, or created by the system at move-out? Rules say nothing is automatic. Recommendation: explicit command; Final Settlement preview shows a blocking issue until it is issued (or the Customer never moved in).
14. (slice 4) Which Invoice carries it, and what if the Unit has no rate? Recommendation: its own one-time charge Invoice at move-out (the final Utility Invoice may be issued at a different time); a Unit with no configured rate blocks the charge until a rate is set. A rate of 0 is allowed and gives no charge line.
15. (B, slice 10) Post-settlement correction kinds. BR-SETTLE-013 names "extra charge or Refund". Recommendation: only those two kinds in V1-056 (a linked one-time charge Invoice, or a linked Refund draft). Reversal of a Settlement Deposit application or of a Credit application waits for a later owner decision.
16. (slice 7) Payment move limits. Recommendation: same Property only; the whole wrong allocation moves; if the target Invoice owes less, the rest stays as unallocated Payment value (not Credit) until the normal recognition rules apply.
17. Security reviews for slices 5 and 10 in addition to the required ones? Recommendation: yes.
18. Existing tests that assert immediate Refund or disposition behavior will need narrowing if Q6 is approved. Recommendation: narrow only the one expectation per test, keep test names, docs/010 note per test, as the run rules require.

## 5. Risks

- Lock behavior: Deposit and Refund confirms will call `app.assert_payment_excess_eligible` with NOWAIT; the 9f-4 bounded retry is reused, not changed.
- Fixture narrowing for slice 1 and Q6 may touch many tests; each is listed in the slice commit and docs/010.
- Frontend intermittent tests TEST-FE-087, TEST-FE-128 and TEST-FE-488 are recorded if they fail once, not retried.
- TEST-118 fails until slice 12; nothing is pushed before that.
