# V1-056 sub-slice 10e-3e — a return reversal's Credit put-back goes back on its own line: review record

Sub-slice: 10e-3e (migration `20261207_133`). Base commit: 4a026ae (10e-3d-2b-1b). Built on
2026-10-14. Not pushed.

Rule IDs: BR-CREDIT-006, BR-CREDIT-008, BR-SETTLE-013, BR-SETTLE-016; DB-CREDIT-002,
DB-SETTLE-005; owner answers (b) to Q-2026-10-13-104 and (a) to Q-2026-10-13-106. Design:
ops/V1_056_PLAN.md (the "10e-3e pre-code design" bullet). Open: Q-2026-10-14-109 (the frontend
part; blocks only that part).

## Built

- Migration `backend/migrations/versions/20261207_133_settlement_return_reversal_put_back.py`:
  the two label CHECKs relaxed (`PUT_BACK_BY_CORRECTION`, old definitions asserted first); new
  BEFORE INSERT trigger `customer_credit_applications_put_back` with internal
  `app.validate_credit_application_put_back()`; new internal
  `app.settlement_correction_put_back_allowed(...)`; exact-text patches of
  `app.post_final_settlement_credit_application`, `app.assert_settlement_correction_credit_application`,
  `app.validate_credit_application_complete`, `app.assert_settlement_correction_credit_application_confirmed`
  and `app.assert_settlement_return_reversal_allowed` (the 10e-3d-2a Rent-first refusal removed).
- New test module `backend/tests/test_settlement_return_reversal_put_back_migration.py`, last in
  `scripts/database-test.sh`.
- Changed committed tests (owner standing rules of 2026-10-11 and 2026-10-14; owner answer (b) to
  Q-104): the 27 head-revision assertions in 15 modules (one replacement of the exact quoted
  revision, 27 before and 27 after; the own-parts module's own `REVISION` constant unchanged);
  `test_settlement_return_reversal_swept_migration.py::test_a_part_applied_again_on_a_newer_rent_invoice_application_waits`
  renamed `..._passes_the_check` (built sources unchanged; the newer part now passes; the unused
  `RENT_FIRST` constant removed).
- `ops/traceability.json`: the renamed entry changed, seven appended (six in round 1, one in
  round 2). docs/002 (BR-CREDIT-006
  exception), docs/004 (DB-CREDIT-002 and DB-CREDIT-005 value lists, the as-built paragraph, the
  10e-3d-2a refusal marked ended), docs/010, the plan, ops/V1_056_QUESTIONS.md (Q-109).
- Process slip (named for the owner): one round 1 edit of `ops/traceability.json` was made with a
  short Python script doing exact-text replacements (each anchor checked to appear once) instead
  of the Edit tool, so the file was written whole; `git diff` shows only the renamed entry's two
  lines removed and the intended lines added.

## Runs

Static checks each in its own call, formatter on the changed files first. Outputs in
`~/Development/prm-run-logs/` (`V1-056-slice-10e-3e-*`); every targeted and full run under
`caffeinate -dims`. Corrections counted under the owner rule of 2026-10-14 (a formatter run before
the check is not a correction; counts start again in this sub-slice).

| Run | Kind | Result | Cause |
|---|---|---|---|
| C1 | throwaway catalog dump at head 132 (not a test run) | 727 functions | pre-code read |
| M1 | migration-only check | passed | anchors |
| L1 | `ruff check src tests` | 1 E501 (new test docstring) | cause A (lint, line too long), correction 1 of 2 |
| — | formatter, format checks, lint, `mypy` | clean | after the L1 fix |
| T1 | PostgreSQL targeted: put-back, return reversal, returned value left, swept, successor, own parts, Final Settlement Credit applications, Credit applications, correction plan | 96 passed | first |
| U1 | backend unit, full | 3802 passed, 1985 skipped, 1 known warning | first |
| M2 | migration-only check | passed | before P1 |
| P1 | PostgreSQL full | 2149 passed, 3 known warnings (Starlette; pydantic `UnsupportedFieldAttributeWarning` twice) | first |
| L2 | `ruff check src tests` | 1 I001 (import order, new test module) | cause B (lint, import order), correction 1 of 2 |
| — | formatter, format checks, lint, `mypy` | clean | round 1 fixes |
| T2 | PostgreSQL targeted: put-back, swept | 1 failed (`part > 200`: the Trash line is prorated to 161), 16 passed | cause C (test set-up amount), correction 1 of 2 |
| T3 | PostgreSQL targeted: put-back | 1 failed (`A remaining Pet Deposit basis needs a remaining Pet Deposit step`: the Settlement plan named a Pet remainder basis with no remainder step) | cause D (test Settlement plan), correction 1 of 2 |
| T4 | PostgreSQL targeted: put-back | 6 passed | after the C and D fixes |
| U2 | backend unit, full | 3802 passed, 1986 skipped, 1 known warning | round 1 fixes |
| M3 | migration-only check | passed | before P2 |
| P2 | PostgreSQL full | 2150 passed, 2 known warnings (Starlette; pydantic `UnsupportedFieldAttributeWarning` once) | round 1 fixes |

Read-only search before T1 and P1: the changed functions are the Settlement Credit writer (every
Settlement and correction Credit step), the correction Credit checks, the Credit application
completeness check (every Credit application) and the return reversal refusal; 36 test modules
touch them (the targeted run took the nine that read put-backs, Credit labels or the correction
plan; the full run took all). Before P2: since P1 only the new test module and two migration
comments outside function bodies changed.

## Review round 1 (fresh read-only subagents, during P1; told to write no file and run nothing)

Security: 0 blockers, 2 should-fix, 4 notes.
- S1: the header and detail agreement patch had no test, and Staff can send the label on a detail
  of an ordinary Rent-first proposal (stopped today by the proposal recompute, P5104, and the
  agreement check). Fixed: `test_only_a_correction_s_put_back_takes_the_label` sends the label on
  a proposal detail and expects the refusal with nothing written.
- S2: the closed-Settlement case expected any error; the Settlement check runs first. Fixed: it
  expects 55000 "A closed Final Settlement takes no new Credit application"; docstring and
  traceability say so.
- Notes: N1 the re-post branch trusts the internal release writers (only they write release
  rows); N2 the re-posted rest of a put-back is a `credits.apply` row with the label, so the
  one-call reversal screen's label list sees it (Q-109 corrected); N3 the put-back sum reads a JSON
  key with no index (performance only); N4 a put-back whose source names another line is now
  refused only at commit.

Independent: 0 blockers, 4 should-fix, 7 notes, a real-path set-up.
- SF1: Q-109 rested on a wrong fact (see security N2). Fixed: Q-109, the plan and docs/010
  corrected; recommendation now (b).
- SF2: as security S1 (fixed as above). The header-with-label and detail-without-label direction
  of the agreement check is reachable only by a writer linked to a correction, and every such
  writer writes both together; implementer's claim for the round 2 reviewer: it cannot be isolated
  without disabling triggers or hand-writing a linked correction.
- SF3: as security S2 (fixed).
- SF4: the fail-closed test did not isolate every limit. Fixed: other put-backs naming the same
  payment now count on their own (a second detail id with 901 fails, 900 passes, the stored row
  with 901 passes); the random-id case is named as "a trace naming another payment than its step's
  part". Implementer's claim for the round 2 reviewer: "a reversal linked to this same
  correction" and "the restored payment has one detail" cannot be isolated with the function's
  inputs alone (the step's source entry must name the payment, and that entry comes from the
  same correction's stored source).
- Notes: N1 the reachable re-post after closure is the `REFUND` correction's confirm (migration
  100); wording fixed in the migration docstring and comment, docs/004 and docs/010; N2 docs/004
  value lists and the 10e-3d-2a paragraph updated; N3 the re-posted rest keeping the label is an
  implementer's reading (docs/010; named in the owner report); N4 the 100 Refund is now asserted;
  N5 BR-CREDIT-008 and BR-SETTLE-016 added to the real-path entries; N6 performance (slice 12
  candidate); N7 answered by the new Q-104 test below.

Reviewer set-up used (owner rule of 2026-10-13), independent item 8, built as
`test_the_q104_example_puts_the_service_part_back_on_its_own_line` (amounts scaled after T2: the
Trash line of the Initial Invoice is prorated to 161, so S brings back 100, not 200):
1. Lease as `test_settlement_deposit_refund_correction_migration.py::test_a_deposit_application_on_another_line_of_the_invoice_stays`
   (`setup_sources`, `create_draft` 2026-07-27 to 2027-06-30, `sign_lease`, `add_service` Trash and
   Internet, `PostgresRentBillingService.generate(initial_command)`, `pet_deposit`).
2. Pay every Initial Invoice line with `test_final_settlement_preview_migration.pay`: Rent in two
   payments (owed - 1,000, then 1,000), Trash and Internet in full.
3. `terminate`, `bill_unbilled_rent_months`, `start`; a Settlement plan that only refunds the Pet
   Deposit (`settlement_refund(case, "pet", held)`, no Pet remainder decision, T3); `approver`.
4. A REFUND correction of a month invoice's Rent line for 2,000 (`refund_command`,
   `record_refund`, `confirm_refund`): a correction Credit Refund of 2,000, Credit 0.
5. E = `return_only(case, refund, 900 + p)`, p = min(Trash owed, 500).
6. One-call reversal of the 1,000 Rent allocation and the Trash allocation.
7. S = `return_only(case, refund, 100, SettlementCreditStep(credit, LINE, rent, 1_000),
   SettlementCreditStep(credit, LINE, trash, p))`.
8. E's reversal: swept parts 1,000 and p - 100, one put-back of 100 on the Trash line with the
   label while Rent owes 1,000; owed again exactly 900 + p; Credit 0; the ledger reconciles.

## Review round 2 (fresh read-only subagents, during P2; told to write no file anywhere and run nothing)

Security: 0 blockers, 1 should-fix, 5 notes.
- SF-1: the round 1 S1 test never reached the agreement check (the proposal recompute refuses the
  header first, P5104, mapped to `CreditConflictError`; the agreement check's 23514 would map to
  `CreditUnavailableError`). Fixed: the test is pinned with `match="Credit proposal changed"` and
  its docstring and traceability note say so; the agreement check is isolated in the new
  `test_the_header_and_its_detail_agree_on_the_label` with the reviewer's set-up.
- Notes: N1 the bound is the whole reversed detail amount, as the owner worded it; N2 the rule read
  `reapply->(p_sequence-1)`, and a negative JSON index counts from the end (fixed: the rule refuses
  a step before the first; tested with step 0); N3 the forward-only test compares trigger names
  only (slice 12); N4 the implementer's claim (b) confirmed; N5 the record had no P2 yet (added).

Independent: 0 blockers, 2 should-fix, 6 notes.
- SF-A: the Q-104 traceability note said 200 (the test puts back 100). Fixed.
- SF-B: as security SF-1 (fixed as above).
- Item 2: the Q-104 test traced to the cent (p = 161; E 1,061; S 100; Rent 1,000 and Trash 61 owed
  again); at head 132 its reversal is refused at record by the 10e-3d-2a Rent-first refusal (and
  the old writer's proposal would have picked Rent), so the test proves the owner's Q-104 answer.
- Item 3: claims (a) and (b) confirmed; (a) is now tested anyway with the security set-up.
- Item 4: the changed committed tests compared with HEAD: 27 revision-only lines in 15 modules;
  the swept test only lost its refusal assertion and the unused constant, its sources and other
  checks unchanged; nothing else got weaker.
- Notes: N-a a test comment's amount (fixed); N-b P2 (added); N-c the Q-104 test's Lease dates are
  fixed while the termination uses the database's today, inherited from an existing fixture (slice
  12 date-bound item); N-d the plan's pre-code test list (the as-built line names what was built and
  why the rest is not); N-e docs/004's 10e-3c paragraph could point to the label (slice 12); N-f
  BR-CREDIT-008 and BR-SETTLE-016 added to the re-posted-rest entry.

Reviewer set-up used (security SF-1), built as `test_the_header_and_its_detail_agree_on_the_label`:
on the owner connection, in one transaction that is always rolled back, `ALTER TABLE
app.customer_credit_applications DISABLE TRIGGER customer_credit_applications_put_back`; insert an
ordinary header (`credits.apply`, no Final Settlement) with the label on a fresh Credit and Rent
Invoice (`test_credit_application_migration.source`) and a detail with another label;
`SET CONSTRAINTS ALL IMMEDIATE` gives 23514 "Credit attribution and financial position must
reconcile"; the same with the label on the detail passes; afterwards the trigger is enabled
(`tgenabled = 'O'`) and nothing is written.

Runs after the round 2 fixes (static checks each in its own call, formatter first):

| Run | Kind | Result | Cause |
|---|---|---|---|
| — | formatter, format checks, lint, `mypy` | clean, no change | round 2 fixes |
| M4 | migration-only check | passed | round 2 fixes (the step guard) |
| T5 | PostgreSQL targeted: put-back | 7 passed | round 2 fixes |
| U3 | backend unit, full | 3802 passed, 1987 skipped, 1 known warning | before round 3 |
| M5 | migration-only check | passed | before P3 |
| P3 | PostgreSQL full | 13 failed, 2138 passed: every failure `Signature evidence is invalid` in the Lease signature fixture (`signed_with_initial`, through `closed_case` or the Q-104 Lease), outside the sub-slice | cause E (host and Docker clocks), not a correction |
| K1 | clock check (run rule): `docker run --rm --pull=never --entrypoint date postgres:17.6 +%s%6N` between two Mac readings, three times; not a test run (a first try on `postgres:16-alpine` printed seconds only, because its `date` has no `%6N`) | in step each time (Docker 75 to 82 ms after the first Mac reading, 82 to 88 ms before the second) | run rule |
| M6 | migration-only check | passed | before P4 |
| P4 | PostgreSQL full, the one allowed rerun under `caffeinate -dims` | 2151 passed, 1 known warning (Starlette) | rerun after K1 |

## Review round 3 (fresh read-only subagents, after P4; told to write no file anywhere and run nothing)

Independent: 0 blockers, 0 should-fix, 4 notes. It verified each round 2 fix: the ordinary-proposal
test is pinned to the proposal recompute (P5104); in the agreement test only the new clause refuses
the negative case, the positive case passes every deferred check, the transaction is always rolled
back and the trigger stays enabled; step 0 would have passed before the guard and now fails; the
traceability amounts. It compared every changed committed test with HEAD (27 revision-only lines in
15 modules; the swept test only lost its refusal assertion and the unused constant; nothing else
weaker). Notes: (1) this record said "six appended" (fixed: seven); (2) the two Credit tests use the
shared `test_credit_application_migration.source` with its fixed 2027 dates (inherited); (3) the
label trigger's refusal of a Settlement's own row on an open Settlement is not tested directly (the
closed case is refused first by the Settlement check, accepted in round 1); (4)
`frontend/src/financialResponse.ts:202` has a fixed list for proposal details only, which never
carry the label.

Security: 0 blockers, 0 should-fix, 5 notes: the re-post branch trusts the internal writers (only
the `REFUND` correction re-post is reachable after closure); the re-posted rest carries the label
under `credits.apply` with the approving staff member as actor (implementer's reading, named for
the owner); the cap is the whole reversed detail amount, as the owner worded it; the cap's sum also
counts put-backs reversed later (errs towards refusing; performance, slice 12); the agreement test
needs the migration URL to be the table owner (it fails loudly otherwise). It scanned the diff, the
new files and the 18 cited run logs for secrets: none.

Round 3 is clean (independent and security).
