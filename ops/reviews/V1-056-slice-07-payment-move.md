# V1-056 slice 7 — wrong-Unit Payment move (BR-PAY-042, BR-AUTH-010)

Built: migration `20261020_85_payment_move_drafts.py` (relaxed allocation basis check with `WRONG_UNIT_MOVE`; `validate_payment_allocation_source` and `audit_payment_allocation_event` patched in place; `app.payment_moves`; internal `app.payment_move_source`; `app.record_payment_move_draft` and `app.confirm_payment_move_draft` for the financial role; deferred guards for move allocations, move links and moved-allocation reversals). Service `backend/src/property_rental/payment_move.py`. Frontend: allocation reversal context accepts the new basis. Owner answers: Q-2026-10-05-16 (six recommendations) and Q-2026-10-05-17 (refuse the one-call reversal of a moved allocation). No HTTP route (slice 11d).

## Runs before review round 1

- F1: `frontend/src/financialUiContext.test.ts` alone, 80 passed (check of the new frontend test).
- U1: full backend unit suite, 3398 passed, 1601 skipped (`V1-056-slice-07-unit-test-run.txt`).
- P1: full PostgreSQL suite, 1755 passed (`V1-056-slice-07-full-test-run.txt`).
- F2: frontend format check, lint, type check, 1590 tests, build (`V1-056-slice-07-frontend-checks.txt`).

## Round 1 (independent and security, fresh read-only reviewers)

No blocker.

Should-fix, fixed before round 2:
1. (security) No test proved Property isolation. Added `test_unknown_property_is_not_found_and_moves_nothing`; V1 holds one Property (`properties_singleton_key_unique`), so any other id is refused first (P4501). The service did not map P4501 and reported it as "unresolved"; now `PaymentMoveNotFoundError` (unit mapping test extended).
2. (independent) The frontend payer-scope skip could never run: the backend context function (migration 47) already refuses a target outside the payer scope. Removed; TEST-FE-672 now proves only the reachable case (one-Customer move loads; unknown basis refused); docs/010 corrected.
3. (independent) The BR-PAY-036 split order was unproven. Added `test_moved_amount_follows_the_rent_then_service_order`.
4. (independent) The Credit/Refund block was proven only at recording. Added `test_credit_or_refund_after_the_draft_blocks_confirmation`.
5. (independent) A test name claimed more than it proved. Renamed to `test_credit_adjustment_release_and_its_credit_block_the_move`, note corrected.

Notes taken: one shared instant for the reversal and the new allocation (no over-use window); one `payment_move.confirmed` audit event per move (draft id as correlation id, approver, `financial.approve`, preparer); per-allocation lock taken after the Property check; quoted constraint name; "too many lines" is a conflict; the 16,000-byte draft limit is named in its refusal and in docs/004; concurrency tests for two drafts and two confirms; the Payment reversal test asserts the refusal and the RECEIVED status without pinning the existing allocation service's error mapping; docs/002 and docs/003 sentences name the credit-Adjustment re-post and the identified-Invoice intent.

Answered in writing, no change: the database trusts the backend's actor id and `financial.approve` reference (DL-069 design, as for every draft kind); the confirm locks Payment before Invoices like the existing allocation commands, so a rare deadlock with a credit Adjustment surfaces as a conflict with nothing written; slice 11d must show the reversal of a moved allocation as unavailable and point to a move draft.

## Runs after round 1

- U2: full backend unit suite, 3399 passed, 1606 skipped (`V1-056-slice-07-unit-test-run-2.txt`). Cause: round-1 fixes.
- P2: full PostgreSQL suite, 1 failed, 1759 passed (`V1-056-slice-07-full-test-run-2.txt`). Cause: round-1 fixes. The failure was the new split test's fixture assumption (`assert rent_due + 1 < 80000`; the Initial Rent line is 92,903 cents), not the code.
- Correction 1 for that cause: the test lets the correct Invoice's Customer pay all but 10,000 of its Rent first, so a wrong allocation of 10,001 covers the Rent and one Service cent. Test only; no code changed.
- P3: full PostgreSQL suite, 1760 passed (`V1-056-slice-07-full-test-run-3.txt`). Cause: correction 1 (the database script always runs the full list).
- F3: frontend format check, lint, type check, 1589 tests, build (`V1-056-slice-07-frontend-checks-2.txt`). Cause: round-1 frontend change (one TEST-FE-672 case removed with the dead skip).

## Round 2 (independent and security, fresh read-only reviewers)

No blocker. Round-1 fixes verified. Three should-fix in total, so the work stopped (Q-2026-10-05-18):
1. (security) A Credit released from a moved allocation by a credit Adjustment can be reversed with `credits.reverse`, returning the value to the payer's Payment for a one-call allocation: a cross-Customer path without a draft. Needs an owner decision.
2. (independent) Confirm does not force the correct Invoice's version forward when its status is unchanged; a stale credit Adjustment still passes its version check.
3. (independent) No test for the exemption of a normal Payment's identified Invoice.

Notes: audit key `prepared_by` unreadable by the audit API (rename to `prepared_by_actor_id`); ranking proof with out-of-order lines; credit-Adjustment guard proven alone; fully returned Refund positive case; neutral draft-size wording; approver naming owner item to include payment-move rows; record backend format, lint and type checks.

Owner answer to Q-2026-10-05-18: finding 1 option (a); round 3 allowed; both round 3 reviewers search once more for any other path from a moved allocation to a different Customer and list what they checked.

## Fixes before round 3

1. Credit reversal: new BEFORE INSERT trigger `customer_credit_reversals_moved_payment` (P4904, mapped to `CreditConflictError`) refuses the one-call reversal of a Credit released from a moved allocation when it belongs to a Customer other than the payer. Tests: two-Customer refusal, one-Customer reversal allowed, service mapping.
2. Confirm forces `app.refresh_allocated_invoice(target,actor,true)`; the split test shows the version advancing while the status stays PARTIALLY_PAID.
3. Identified-Invoice exemption tested (`test_normal_payment_identified_invoice_moves_only_through_a_draft`).
Notes: audit key `prepared_by_actor_id`; credit-Adjustment guard proven alone; fully returned Refund positive case; neutral draft-size wording; plan slice 12 approver-naming item extended to the move rows. Not done, answered in writing: an out-of-category-order fixture (would need Service-source rows no producer creates).

Static checks before round 3 (this session, after the fixes): `ruff format --check src tests` 275 files formatted; `ruff check src tests` all checks passed; `mypy` no issues in 275 source files; `tests/test_payment_move.py` and `tests/test_credit.py` 72 passed.

## Runs before round 3 (standing rule)

- U3: full backend unit suite, 3400 passed, 1608 skipped (`V1-056-slice-07-round3-unit-test-run.txt`).
- P4: full PostgreSQL suite, 1762 passed, the known Starlette and Pydantic warnings (`V1-056-slice-07-round3-full-test-run.txt`).
- Frontend unchanged since F3; no frontend run.

## Round 3 (independent and security, fresh read-only reviewers, owner path search)

No blocker. Round-2 fixes verified correct. Both reviewers listed every path checked (allocation reversal and post, credit and debit Adjustment, adjustment reversal, VOID, hand-back and unpaid-Initial resolutions, Payment reversal, Credit recognition, application, application reversal, reversal, Refund drafts, corrections, verified returns, correction reversals, Deposit receipts and dispositions, Late-payment Charges, another move draft, Final Settlement, direct writes). Two should-fix, so the work stopped (Q-2026-10-05-19):
1. (both) The Credit reversal refusal misses third-party Payments: a moved third-party Payment's Credit released to the payer can be reversed and sent by a one-call third-party allocation or Deposit receipt to the identified Lease's Customer.
2. (independent) The Q-2026-10-05-18 option (a) text and the docs say such a Credit can be refunded through a Refund draft; the existing Refund rules (migration 41) refuse a Credit Refund whose recipient is not the payer, so it can only be applied; consequences (permanent move and Payment-reversal block) undocumented.
Notes: the grants test omits `app.validate_moved_credit_reversal()`; slice 11d must show the reversal as unavailable for every moved allocation (one-Customer moves too); the ops/NOW.md line still says round 2; slice 8 must keep moved-value Credits with their Customer; slice 11d must use the capability-filtered draft reads (acknowledgement text).

Owner answer to Q-2026-10-05-19: keep the refusal, correct the wording, add the Refund-draft refusal test; the Refund of such a Credit to the Invoice Customer is required (BR-CREDIT-014) and planned in slice 9 as a Refund draft confirmed by `financial.approve`; the lasting block is a slice 12 item; fix the third-party gap; one more fresh review of these changes with the same path search; commit only if it has no should-fix.

## Fixes before the extra review (owner-approved)

1. `app.validate_moved_credit_reversal` refuses unless the Payment is a normal Customer Payment and the Credit belongs to its payer; test `test_third_party_payers_own_released_credit_is_not_reversed_back_to_the_identified_lease`.
2. Wording corrected (migration docstring and error text, credit service message, docs/004 DB-PAY-008, docs/010 correcting note); test `test_credit_of_another_customer_from_a_moved_payment_is_not_refunded_to_the_payer`; plan slice 9 item (Refund to the Invoice Customer), slice 8 note, slice 11d notes, slice 12 item (lasting block).
3. Notes: the grants test lists `app.validate_moved_credit_reversal()`; ops/NOW.md line added at the stop.
Static checks after the fixes: `ruff format --check` 275 files formatted, `ruff check` passed, `mypy` no issues.

## Runs before the extra review

- U4: full backend unit suite, 3400 passed, 1610 skipped (`V1-056-slice-07-round4-unit-test-run.txt`). Cause: Q-2026-10-05-19 fixes.
- P5: full PostgreSQL suite, 1764 passed, known warnings (`V1-056-slice-07-round4-full-test-run.txt`). Cause: Q-2026-10-05-19 fixes.

## Extra review (owner-approved, after round 3)

Independent and security, fresh read-only reviewers, limited to the Q-2026-10-05-19 changes, with the owner's path search. No blocker, no should-fix. Both listed every path checked and found no path from a moved allocation to a different Customer without a draft and an approver. Wording notes taken (docs/004, migration docstring, docs/010); test and mapping notes moved to the plan (slices 9, 11d, 12). Slice 7 committed under the owner's condition.
