# V1-056 sub-slice 10f-1 — the mistaken credit Adjustment reversal before closure — review record

Sub-slice: 10f-1 (owner answer 7 to Q-2026-10-06-36; the slice 10 entry of the plan, from the owner
answer to the 8f report). 10f is split (allowed without asking): 10f-1 the ordinary
`ADJUSTMENT_REVERSAL` draft before closure, 10f-2 the correction after closure. Migration
`20261219_145` (relaxing changes and new functions). Base commit: 8f57766. Built on 2026-10-16.
Not pushed.

Rule IDs: BR-INV-044, BR-CREDIT-006, BR-CREDIT-008, BR-AUTH-010, BR-SETTLE-013; DB-INV-010,
DB-CREDIT-002. Design: ops/V1_056_PLAN.md, "10f pre-code design" and its as-built line. New owner
question: Q-2026-10-16-118 (put-back placement when an earlier line owes; Adjustments a resolution
wrote; both refused until answered; nothing waits).

## Built

- Migration `20261219_145_adjustment_reversal_drafts.py`: the draft kind `ADJUSTMENT_REVERSAL`
  with the preparer `invoices.adjust` (kind, preparer, kind-preparer and WITHDRAWN checks); the two
  capability-scoped draft reads accept nine capabilities (exact-text patches); new internal
  `app.adjustment_reversal_source`, `app.adjustment_reversal_instant`,
  `app.adjustment_reversal_result`; the recorder `app.record_adjustment_reversal_draft` and the
  confirm `app.confirm_adjustment_reversal` (EXECUTE to `prm_financial` only).
- Service `property_rental/adjustment_reversal.py`; `financial_draft.py` gains the kind and its
  preparer.
- Tests: new `test_adjustment_reversal_migration.py` (9 tests, last in `scripts/database-test.sh`)
  and `test_adjustment_reversal.py` (21 unit cases).
- Committed tests changed: `test_lease_deposit_forfeiture.py` (the preparer bound 8 to 9; the
  approver's preparer list gains `invoices.adjust`); the 27 head-revision assertions in 15 modules
  move to `20261219_145`.
- Traceability: 15 entries appended; the note at index 2555 updated in place.
- Docs: docs/004 DB-INV-010; docs/010 (owner notes on the 10c-3c-2 report, as built, updated tests,
  reviews and runs); the plan (pre-code design, as-built line, slice 11 and 12 notes);
  ops/V1_056_QUESTIONS.md (Q-2026-10-16-118).

Read-only search for affected tests (before T1 and P1): every backend test naming
`PREPARE_CAPABILITIES`, `KIND_PREPARE_CAPABILITIES`, the draft capability bounds, the two draft read
functions, the draft constraints and `app.invoice_adjustment_reversals`. Found: the bound in
`test_capability_scoped_reads_fit_the_database_bound`. Missed, found by T1: the approver's literal
preparer list in `test_draft_reads_pass_only_the_prepare_capabilities_the_reader_holds`. The tests
that insert Adjustment reversals directly as the owner are unaffected (no trigger changed).

## Runs

| Run | Result |
|---|---|
| D1-D4 | catalog dumps (read only; two `[HEX REDACTED]` markers, both in money bounds, not copied) |
| FF1/FC1 | passed (formatter first: one file reformatted) |
| L1 | failed: 7 × RUF100 unused `noqa: F811` in the new module (cause A, lint; correction 1 of 2) |
| FC2/L2/Y1 | passed (the passing rerun after L1) |
| M1 | passed (`20261219_145` head) |
| T1 | 1 failed, 54 passed: the approver's preparer list in `test_lease_deposit_forfeiture.py` (cause B, a committed test the search missed; correction 1 of 2) |
| T2 | 26 passed (the passing rerun after T1) |
| U1 | 1 failed: `test_traceability_manifest_covers_executable_tests`, no entries yet (cause C, traceability; correction 1 of 2) |
| U2 | 1 failed: the same test, a duplicate test id `test_refusals_stale_drafts_withdrawal_and_reads` (cause C; correction 2 of 2, allowance used) |
| T3 | 28 passed (`tests/test_traceability.py`, the passing rerun after U2) |
| FF3/FC3/L3/Y2 | passed |
| U3 | 3825 passed |
| M2 | passed |
| P1 | 2219 passed (warnings: the known Starlette deprecation and one Pydantic alias warning of the unchanged Credit Refund API tests) |
| FF4/FC4/L4/Y3 | passed (after the round 1 fixes; formatter first, no change) |
| M3 | passed |
| T4 | 30 passed |
| U4 | 3825 passed |
| M4 | passed |
| P2 | 2220 passed (warning: the known Starlette deprecation) |

After P2 only text changed (docs/004, docs/010, the plan, this record, ops/NOW.md). Full outputs
are in `~/Development/prm-run-logs/v1-056-10f-1-*.txt`.

## Review round 1 (fresh read-only subagents, during P1; told to write no file and run no test, script or database command)

Security: 0 blockers, 0 should-fix, 7 notes. Independent: 0 blockers, 3 should-fix, 10 notes.

- Should-fix 1 (independent): Q-2026-10-16-118 said the put-back always goes on the line on an
  Invoice without Rent or Service lines; the proposal order (and the refusal) uses line order on
  any Invoice, so a final Utility Invoice with an owing Electricity line before the paid Water line
  is refused too. Fixed in the text (Q-118, the plan, docs/004); the refusal stays fail-closed for
  any Invoice until the owner answers.
- Should-fix 2 (independent): no test of two releases (the earlier put-back from the same Credit
  counted). Fixed with `test_two_releases_of_one_credit_count_the_earlier_put_back`, the
  reviewer's set-up:
  1. `credit_source`: Credit X 100,000; the line 80,000.
  2. Apply X designated 50,000 to the line, then 30,000; the line owes 0.
  3. A credit Adjustment of 40,000 on the line: the newer application is released whole (R1,
     30,000), then 10,000 of the older one (R2), its 40,000 re-posted; X holds 60,000.
  4. The 2027-04 recurring Invoice; apply 25,000 of X to it; X holds 35,000.
  5. Record: R1 available 35,000, put back 30,000, debt 0; R2 available 5,000, put back 5,000,
     debt 5,000; totals 35,000 and 5,000.
  6. Confirm: two put-backs on the line in increasing time; the line owes 5,000; X holds 0;
     PARTIALLY_PAID; version +2; the ledger reconciles.
- Should-fix 3 (independent): docs/010 had no note for the changed committed tests. Fixed (the
  as-built and "Updated tests" entries).
- Notes taken: the plan and docs/004 said the source lists the line's unpaid rest after the
  reversal; the field is the current unpaid amount (text corrected); the version guard now counts
  the second advance of a put-back (code: `version>2147483647-2` with a put-back, CASE in
  parentheses); the lock-order comment names the writers that lock the Invoice first (security note
  4); the put-back's actor and trace ids asserted (independent note 5); a direct database refusal
  of a confirm under `invoices.adjust` (security note 3); slice 11 notes (strip the decision's
  transaction id for this kind too, security note 2; the reason is shown on the ledger and the
  audit event, note 6; whether `invoices.adjust` holders may see the released Credits' available
  values, note 7); the fungible Credit reading in docs/010 (independent note 6).
- Notes kept for slice 12 (plan list): a deferred confirm-only check on the reversals table
  (security note 1; it would change committed tests that insert reversals directly, so it needs the
  owner); a database cap of each put-back by its release (independent note 7); tests of the
  unpaid-Initial resolution, correction-linked and not-issued refusals and of a non-human or
  inactive approver; the put-back applications' general audit reason; docs/002 BR-AUTH-010 and
  BR-INV-044 (independent note 8); the Settlement preview's capability bound now reached.
- Noted, no change: the lock order with `app.adjust_invoice` and the Final Settlement confirm can
  deadlock (detected, 40P01, a conflict, nothing written); the database trusts the
  `financial.approve` reference from `prm_financial`, as every draft kind; an unmapped SQLSTATE maps
  to "preserve and replay", as the template; the new tests use fixed dates only.

## Review round 2 (fresh read-only subagents, during P2; same limits)

Independent: clean (0 blockers, 0 should-fix, 5 notes). Security: clean (0 blockers, 0 should-fix,
4 notes).

- Independent: every round 1 fix confirmed; the two-release test proves the "earlier put-back
  counted" rule (without it the second release would show 35,000 available and no debt); the
  version guard is correct and before the first write; no money, chronology, refusal or grant gap
  found; the changed committed tests are not weaker than HEAD (27 revision strings in 15 modules;
  the preparer list stays an exact set); traceability 3,123 to 3,138 entries, the only in-place
  change at index 2555.
- Security: deny-by-default, the Staff-confirm refusal (service and database), no injection, no
  transaction id in results or replays, the lock order, READ COMMITTED, the stale digest,
  atomicity and the money caps all hold; the parenthesized CASE is correct.
- Notes taken (text): the docs/010 review and run entry (independent 1); the not-issued refusal
  named in docs/004, docs/010 and the plan, whose "Which Adjustment" bullet now gives P0002 only
  for an Adjustment not on the Property (independent 2); the plan's lock wording, "each released
  Credit's Payment" (independent 4).
- Notes kept for slice 12 (plan list): the payload limit of about 40 releases, refused as invalid
  input (independent 5, security 4); the put-back's `credits.apply` reference (security 2); the
  wider lock set (security 3); the migration docstring's refusal list and the 7 in the
  `test_capability_scoped_reads_fit_the_database_bound` docstring (independent 2 and 3; no
  migration or test file changed after P2). Security 1 (the transaction id and Credit values in the
  general draft reads) is already a slice 11 note.
- No round 3: round 2 has no should-fix.
