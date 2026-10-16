# V1-056 sub-slice 10f-1b — an Adjustment reversal puts the Credit back on its own line — review record

Sub-slice: 10f-1b (owner answer (a) to Q-2026-10-16-118 point 1; point 2 answered (a), nothing
built). Placed by the implementer right after 10f-1 and before 10f-2 ("where it fits best"),
because 10f-2 reuses the 10f-1 put-back. Migration `20261220_146` (relaxing changes and one new
check). Base commit: 7066e47. Built on 2026-10-16. Not pushed.

Rule IDs: BR-CREDIT-006, BR-CREDIT-008, BR-INV-044; DB-CREDIT-002, DB-INV-010. Design:
ops/V1_056_PLAN.md, "10f-1b pre-code design".

## Built

- Migration `20261220_146_adjustment_reversal_put_back_label.py`: exact-text patches of
  `app.adjustment_reversal_source` (the 10f-1 Rent-first refusal ends),
  `app.confirm_adjustment_reversal` (no proposal; every put-back carries `PUT_BACK_BY_CORRECTION`
  on the row and its one detail, on the Adjustment's line) and
  `app.validate_credit_application_put_back` (the label is also allowed on a row with no Final
  Settlement that a confirmed `ADJUSTMENT_REVERSAL` decision of the same transaction lists); new
  internal `app.adjustment_reversal_put_back_allowed` and `app.validate_adjustment_reversal_put_back`
  and the deferred constraint trigger `customer_credit_applications_adjustment_put_back` (one
  detail; listed with the same Credit, amount and release; the trace names the reversal and the
  release; the Adjustment's Invoice and line; the release's Credit; all put-backs naming the
  release at most the released amount). No grant, table or column change.
- Tests: new `test_adjustment_reversal_put_back_migration.py` (8 tests, last in
  `scripts/database-test.sh`).
- Committed tests changed (owner answer changes a result; standing rules of 2026-10-11 and
  2026-10-14): in `test_adjustment_reversal_migration.py`,
  `test_a_released_allocation_s_credit_goes_back_on_its_line` expects the label on the row and
  detail; `test_a_put_back_goes_only_where_the_rent_first_order_also_puts_it` renamed
  `test_a_put_back_goes_on_the_adjustment_s_line_even_when_an_earlier_line_owes` and turned into
  the allowed case (Rent still owes all of its amount); module docstring, the unused placement
  constant and import. The 27 head-revision assertions in 15 modules move to `20261220_146`.
- Traceability: 7 entries appended (3,138 to 3,145); in place: the renamed test, the allocation
  test's note, the hand-back refusal test's note (point 2 answered).
- Docs: docs/002 BR-CREDIT-006 exception; docs/004 DB-INV-010 and DB-CREDIT-002; docs/010 (owner
  answers, as built, updated tests, reviews and runs); the plan (pre-code design, slice 12 notes);
  ops/V1_056_QUESTIONS.md (Q-118 answered).

Implementer's reading during the build (design-change rule; confirmed needed and safe by the
round 1 independent reviewer): the deferred check covers only rows a decision of the transaction
lists. The read-only search before T1 found that the committed 10e-3e test
`test_settlement_return_reversal_put_back_migration.py::test_the_header_and_its_detail_agree_on_the_label`
writes a labelled row with no Final Settlement by hand, with the label trigger disabled, to reach
the agreement check; a check of every such row would refuse it. The rows the check skips are
exactly those the insert trigger refuses, plus release re-posts.

Read-only search for affected tests (before T1 and P1): every backend test naming
`confirm_adjustment_reversal`, `adjustment_reversal_source`, `validate_credit_application_put_back`,
the label, the Rent-first placement message, the label triggers, or reading `pg_trigger` together
with `customer_credit_applications`. Found: the two 10f-1 cases above and the 10e-3e agreement test
(handled by the reading above); the tie-break test only checks that no trigger is disabled.

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump (read only; no `REDACTED` marker) |
| M1 | passed (`20261220_146` head) |
| FF1/FC1/L1/Y1 | passed (formatter first: one file reformatted) |
| T1 | 2 failed, 20 passed: two new tests with wrong set-ups: a hand-written row refused by the Credit application insert check because its Credit held nothing (cause A, test set-up refused by a business check; correction 1 of 2); a later Adjustment too small to release anything (cause B, a wrong test amount; correction 1 of 2) |
| FF2-FF3/FC2-FC3/L2-L3/Y2-Y3 | passed |
| T2 | 1 failed, 5 passed: the same test, Credit recognition refused while the Customer has open obligations (cause A; correction 2 of 2, allowance used) |
| FF4/FC4/L4/Y4 | passed |
| T3 | 6 passed (the passing rerun after T1 and T2) |
| U1 | 3825 passed |
| M2 | passed |
| P1 | 2226 passed (warnings: the known Starlette deprecation and one Pydantic alias warning of the unchanged Credit Refund API tests) |
| FF5/FC5/Y5 | passed (after the round 1 fixes; formatter first: one file reformatted) |
| L5 | failed: 2 × F841 unused locals left in a test after the helper move (cause C, lint; correction 1 of 2) |
| FF6/FC6/L6/Y6 | passed (the passing rerun after L5) |
| T4 | 1 failed, 22 passed: the round 1 other-line test used 1,000 cents on a 161-cent Service line (cause B, a wrong test amount; correction 2 of 2, allowance used) |
| FF7/FC7/L7/Y7 | passed |
| T5 | 23 passed (the passing rerun after T4) |
| U2 | 3825 passed |
| M3 | passed |
| P2 | 2227 passed (same two known warnings) |
| U3 | 28 passed (`tests/test_traceability.py`, after the round 2 traceability text) |

After P2 only text changed (docs/002, docs/004, docs/010, the plan, ops/traceability.json notes,
this record, ops/NOW.md). Full outputs are in `~/Development/prm-run-logs/v1-056-10f-1b-*.txt`.
Before each lint run the changed files were searched for lines over 100 characters (one docstring
line found and shortened before L1).

## Review round 1 (fresh read-only subagents, during P1; told to write no file and run no test, script or database command)

Security: 0 blockers, 2 should-fix, 10 notes. Independent: 0 blockers, 2 should-fix, notes.

- Should-fix (both reviewers): the "another Credit" case ran only if the shared database held
  another Credit, of any Customer. Fixed: the test pays the Service line with two allocations, so
  two Credits of the same Customer exist, and asserts the other Credit and another issued Invoice
  of the Customer (a recurring Rent Invoice for 2027-03) without a condition.
- Should-fix (security S2): the insert trigger's transaction binding had no test. Fixed with the
  reviewer's set-up, in the module helper `listed_put_back` (table owner, always rolled back):
  1. Record and confirm a real reversal (its put-back takes the whole release).
  2. `app.insert_financial_draft` of a second `ADJUSTMENT_REVERSAL` draft.
  3. Its decision lists a new labelled put-back of 1 from the same Credit and release:
     (a) through `app.confirm_financial_draft_record` with `transaction_id` set to the
     transaction id minus 1; (b) inserted directly into `app.financial_draft_decisions` with the
     current transaction id and `decided_at` one second before `transaction_timestamp()`.
  4. Insert the labelled header: refused by the insert trigger (23514, "Only a correction's
     put-back is labelled put back by a correction") in both cases.
- Should-fix (independent): the plan's new-tests list did not match the build. Fixed.
- Independent optional set-up, built as `test_the_deferred_check_takes_a_listed_put_back_only_on_the_adjustment_s_line`
  (amounts scaled to the fixture: the Service line is 161 cents, so half of it instead of 1,000):
  1. `rent_and_service_invoice`; pay the Service line S in full.
  2. A credit Adjustment of S on the Service line: Credit C = S.
  3. Apply `part = S // 2` of C designated on the Rent line.
  4. Record and confirm the reversal: put-back S − part; the Service line owes `part`.
  5. Reverse the Rent-line application of C: C holds `part`, the Rent line owes all of it.
  6. `listed_put_back(..., service)` passes (returns None); `listed_put_back(..., rent)` is
     refused (23514, the new check's message).
- Notes taken (text): the migration docstring and comment name migrations 100, 103 and 113 for
  release re-posts; the hand-back test's traceability note names point 2's answer; a local list
  renamed so it no longer shadows the imported `credits`.
- Notes not taken: raising in the deferred check for unlisted rows (security N1; it would refuse
  the committed 10e-3e row, and the insert trigger already refuses unlisted rows); performance of
  the JSON scans (slice 12 list).
- Independent: the narrowing is needed and safe (design-change rule); the changed committed tests
  are not weaker than HEAD; the 27 revision strings only.

## Review round 2 (fresh read-only subagents, during P2; same limits)

Security: clean (0 blockers, 0 should-fix, 7 notes). Independent: 0 blockers, 1 should-fix, 6
notes.

- Should-fix (independent): docs/002 BR-CREDIT-006 still limited the label and the own-line
  exception to a correction's put-back. Fixed: a new exception paragraph for the Adjustment
  reversal's put-back (owner answer (a) to Q-2026-10-16-118 point 1). Text only, so round 3 runs
  under the round-3 rule of 2026-10-13.
- Notes taken (text): the traceability note of the beyond-the-release test names the other-line
  test; the docs/004 wording on rows the insert trigger refuses.
- Notes kept for the slice 12 list: a test on an Invoice without Rent or Service lines (set-up: a
  Miscellaneous Invoice through `miscellaneous(customer)` and `draft_and_issue` of
  `test_one_time_charges_migration.py`, pay the line, `adjust_credit` the whole line, record and
  confirm the reversal, assert the labelled put-back rows, outstanding 0, available 0); an
  isolated "listed with the same amount" assertion (header and detail both at amount − 1) and an
  isolated release-of-another-Adjustment case; `pg_current_xact_id_if_assigned()` in the check
  function (security note 1: `pg_current_xact_id()` assigns a transaction id in a read-only
  transaction); the deferred re-post skip could match the insert trigger's `source_kind` and
  labelled-row conditions (security note 2); the put-back's actor, authorization and time are not
  tied to the decision (security note 4, defence in depth). For slice 11: the comment at
  `frontend/src/financialActionContext.ts:660-662` says only a correction's re-posted rest carries
  the label.

## Review round 3 (fresh read-only subagents, after P2 and U3; round-3 rule of 2026-10-13: round 2 had no blocker and only a text should-fix)

Independent: clean (0 blockers, 0 should-fix, 4 notes). Security: clean (0 blockers, 0
should-fix, 5 notes).

- Independent: the code meets point 1 (a) and leaves point 2 (a) untouched; the docs/002
  exception is accurate and complete; docs/004, docs/010 and the plan match the code; the changed
  committed tests are not weaker than HEAD (the renamed test also asserts that Rent still owes in
  full; the removed pay-Rent-first branch stays covered by the direct-call test); the 27 revision
  strings only; in the beyond-the-release test every condition but the sum holds, so the refusal
  comes from the sum; traceability 3,138 to 3,145, only indices 3124, 3126 and 3129 edited in
  place.
- Security: deny-by-default holds; no path for Staff without `financial.approve`; the transaction
  binding cannot be spoofed by `prm_financial` or `prm_runtime`; no over-release, other line,
  Invoice or Customer's Credit; no injection; no secrets or customer data; the docs/002 text grants
  nothing beyond the code.
- Notes kept for the slice 12 list: `v_proposal` is still declared in
  `app.confirm_adjustment_reversal` and no longer used (remove it the next time that function is
  touched); no test reaches the kind and decision filters (a put-back listed by another draft
  kind's decision or by a WITHDRAWN decision); the database trusts the authorization text the
  financial role passes (pre-existing, every confirm).
- Process note: the round 3 independent reviewer saved one file outside the repository, a copy of
  `git show HEAD:ops/traceability.json`, at this session's scratchpad `trace_head.json`, to compare
  traceability entries. Nothing in the repository was written. It holds no secret. Left in place
  for the owner.
