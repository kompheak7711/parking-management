# V1-056 sub-slice 8r — Deposit receipt reversal drafts

Status: round 3 (independent and security) has no blocker and no should-fix, so 8r is committed under the standing round-3 rule.

Owner answer to Q-2026-10-05-22 (2026-10-05): (a) a Deposit receipt reversal becomes a draft, prepared under `deposits.correct` and confirmed by a `financial.approve` holder, like the forfeiture reversal (6b); an approved tightening that replaces the Q-2026-10-04-13 answer; (b) built right after 8a-1; (c) check the slice 3b Reservation Deposit receipt reversal and close it too if it can free money the same way.

Built: migration `20261022_87_deposit_receipt_reversal_drafts.py` (draft source, record and confirm functions; receipt reversal guard also matches a pending draft's `deposit_id`; index on the drafts' `deposit_id`; financial role loses EXECUTE on `app.reverse_deposit_receipt_v2`), `backend/src/property_rental/deposit_receipt_reversal.py`, the one-call refusal in `deposit.py`, the route's 409 in `deposit_api.py` and `app.py`, `can_reverse_receipt` and the ledger's `can_reverse` always false, tests `test_deposit_receipt_reversal_draft.py`, `test_deposit_receipt_reversal_draft_migration.py`, `tests/deposit_receipt_reversal_test_support.py`, updated tests (docs/010), docs/004 DB-DEP-007, docs/005, docs/010, traceability.

Answer (c): the Reservation Deposit receipt reversal could free money the same way. A Reservation Deposit receipt is funded by a `NORMAL_CUSTOMER` Payment of the Reservation's Customer; `app.payment_available_value` counts only receipts that are not reversed, so after a one-call reversal a one-call allocation or Credit recognition could use the value. It is closed by the same draft (the receipt reversal function serves both Deposit kinds).

## Runs

Pre-run search (read-only, all backend tests): 8r adds no table or column; index checks in tests are table-specific and none concerns `app.financial_drafts`; no test checks the receipt reversal guard by its text; tests that used the one-call reversal moved to the owner helper or the draft path (docs/010); head-revision assertions moved to `20261022_87`.

- U1 backend unit: 3439 passed, 1626 skipped (`V1-056-slice-08r-unit-test-run.txt`).
- P1 full PostgreSQL: 1782 passed (`V1-056-slice-08r-full-test-run.txt`).

Static checks before each run: `ruff format --check src tests`, `ruff check src tests` and the migration, `mypy`: clean. Migration status: no development database exists (docs/010, 2026-10-03; first `make migrate` with a backup moves to V1-059); every run applies all migrations to fresh databases.

## Round 1 — independent review (fresh reviewer, read-only)

No blocker. Path search clean: the only writer of `app.deposit_receipt_reversals` is `app.reverse_deposit_receipt` (v1, revoked from every role since migration 28), called only by v2 (now revoked) and the new confirm; Reservation receipts use the same functions; the other confirms refuse this variant. Two should-fix, both fixed:

- The pending-draft checks see only `REFUND` and `DEPOSIT_FORFEITURE` drafts, but docs said "any draft": docs/004 and docs/010 name the two kinds; plan 8c/8e must extend the checks to the Final Settlement drafts, with a test.
- The returned-transfer path had no test: `test_a_returned_transfer_is_reversed_after_the_receipt_reversal_draft` (Payment reversal refused while the draft is pending, allowed after confirmation; a rejected draft changes nothing).

Notes: rejection test added (in the returned-transfer test); reverse cross-confirm added (this confirm refuses a Reservation draft id); the security S1 shape with a pending Lease forfeiture or Refund draft is covered by the same guard and the Reservation case (not added); the adjustment date comes from the database clock (as in 8a-1); other drafts can still be recorded while a receipt reversal waits (11c and owner, plan); the draft kind reads as a forfeiture (11c shows the variant; `financial_draft.py` comment fixed); record completed here.

## Round 1 — security review (fresh reviewer, read-only)

No blocker. Path closed for Lease and Reservation Deposits; deny by default; in-place guard patch keeps owner and privileges; no cross-kind confirmation; no injection or leaks; the route keeps 404 concealment and the browser mutation rule before the 409. One should-fix, fixed: the least-privilege test now also covers v1 `app.reverse_deposit_receipt`, the guard `app.validate_deposit_receipt_reversal` (owner equal to v2's) and INSERT, UPDATE, DELETE and TRUNCATE on the table. Notes moved to the plan: pending-draft kinds (same as the independent should-fix); the reversal row names the approver under `deposits.correct` (6b pattern; draft id in the audit context with 11c); the approver should see that the Payment value becomes available (11c); service `repr` shows the database URL (slice 12, all services).

## Runs after the round-1 fixes

Pre-run search: the fixes change tests, docs and one comment only; migration 87 is unchanged.

- U2 backend unit: 3439 passed, 1627 skipped (`V1-056-slice-08r-unit-test-run-2.txt`).
- P2 full PostgreSQL: 1783 passed (`V1-056-slice-08r-full-test-run-2.txt`). Three warnings instead of one: the known Starlette deprecation plus two pydantic `UnsupportedFieldAttributeWarning` warnings raised in `test_credit_refund_api_migration.py` (Field `alias` on the credit Refund routes' parameters). 8r does not touch that module; recorded, not changed.

## Round 2 — security review (fresh reviewer, read-only)

No blocker, no should-fix. Path closed (only v1 writes the table; only v2 and the confirm call v1 or v2; no grants); deny by default; guard patch keeps owner and privileges; no deposits.correct-only or cross-kind confirmation; no injection or leaks; route order kept. Notes: the least-privilege test would not catch a column-level INSERT grant, a grant to `prm_human_admin`, `prm_restore` or `prm_backup`, or a new granted wrapper (moved to slice 12: exact grantee sets); no test pinned the 403 before the 409 on the receipt route (taken: new unit test).

## Round 2 — independent review (fresh reviewer, read-only)

No blocker. One should-fix, fixed: every test used one person as preparer and approver, and no test reached the database authorization checks; the main test now confirms as a second person (reversal row, audit event and decision name the approver, the draft names the preparer) and shows 42501 for the record function with `financial.approve` and the confirm function with `deposits.correct`. Notes: migration text said "any draft" (taken, now names the two kinds and 8c/8e); the returned-transfer refusal asserts the service's unresolved-outcome error, and the unchanged RECEIVED status proves nothing changed (kept); a protected traceability note (entry 1221) mentions a receipt-reversal replay after later Deposit activity, which the HTTP test now checks through the draft confirmation (taken); untested refusals of another Property, a 6b draft id and a pending Lease forfeiture draft (single Property schema; the last two moved to slice 12); the 11c entry and docs/006 UI-073 (moved to the plan).

## Runs before round 3 (standing rule)

Pre-run search: since P2 only tests, docs and migration comments changed (one SQL comment inside the record function body); no table, column or signature changed.

- U3 backend unit: 3440 passed, 1627 skipped (`V1-056-slice-08r-unit-test-run-3.txt`).
- P3 full PostgreSQL: 1783 passed (`V1-056-slice-08r-full-test-run-3.txt`); warnings: the known Starlette deprecation and one of the two pydantic `UnsupportedFieldAttributeWarning` warnings from `test_credit_refund_api_migration.py` (unrelated to 8r, as in P2).

## Round 3 — security review (fresh reviewer, read-only)

No blocker, no should-fix. Path closed for Lease and Reservation Deposits; deny by default; guard patch keeps owner, privileges and the kind filter; no deposits.correct-only or cross-kind confirmation; concurrent approvers cannot both succeed; decision before the reversal rolls back with it; no injection or leaks; route order kept. Notes: the reversal-id reuse check reads ids across Properties (same as 6b; single-Property schema); the database trusts the capability string and the application checks the grant (established BR-AUTH-010 split); the frontend client still has the one-call reverse call, unreachable (11c, UI-073); moved plan entries are correct.

## Round 3 — independent review (fresh reviewer, read-only)

No blocker, no should-fix. Notes, moved to plan slice 12 or answered here: the record status line (updated now); the test name and traceability note of `test_a_receipt_reversal_waits_for_any_pending_draft_of_its_deposit` say "any" or "another" draft, while the checks see `REFUND` and `DEPOSIT_FORFEITURE` drafts only (slice 12 wording, or 8c/8e when the Settlement drafts extend the checks); the second approver comes from another setup and the database does not check Property membership for invoice command actors (existing design, the application checks it); the catch-all error assertion in the returned-transfer test (kept); a Lease forfeiture draft's id check does not look at a pending receipt reversal draft's `reversal_id`, and a clash fails safe with 23505 (existing pattern); no route until 11c.
