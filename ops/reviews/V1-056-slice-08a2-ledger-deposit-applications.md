# V1-056 sub-slice 8a-2 — Deposit applications in the Customer Ledger and the Deposit history

Status: round 3 (independent and security) has no blocker and no should-fix, so 8a-2 is committed under the standing round-3 rule.

Owner answers to Q-2026-10-05-23 (2026-10-05, the four points of the 8r report): (1) accepted, a receipt reversal works only through the service until 11c; (2) approved tightening, refuse the confirmation of a Refund or forfeiture draft for a Deposit while a receipt reversal draft for it is pending, recording stays allowed, built in 8a-2 with a test; (3) a Security Deposit whose forfeiture was reversed is held again and follows DL-032 unless a new forfeiture draft is confirmed; stop before 8c on a rule conflict (checked: conflicts with the text of BR-DEP-023 and BR-DEP-026, Q-2026-10-05-24, open, not blocking 8a-2); (4) agreed, 8c and 8e extend the pending-draft checks.

Built: migration `20261023_88_deposit_application_ledger.py` (ledger projection version with `DEPOSIT_APPLIED`, ledger page filter, bounded `app.deposit_application_history`, the decision trigger `financial_draft_decisions_wait_for_receipt_reversal`, and the receipt reversal draft recorder now locking the Deposit row); `customer_ledger.py` (event order), `deposit_api.py` (application events in the Deposit history), `refund.py` (the refusal is a conflict); frontend ledger label, Deposit client type and history label; tests in `test_deposit_application_ledger_migration.py`, `test_deposit_receipt_reversal_draft_migration.py`, `test_pet_refund_migration.py`, `DepositManagement.test.tsx`; docs 004, 005, 006, 010; plan notes; traceability appended (11 entries).

## Runs

Pre-run search (read-only, all backend tests) before each PostgreSQL run: no test compares the ledger view text, the decision table's triggers or the runtime function set at head; head-revision assertions moved to `20261023_88`; `EVENT_ORDER` count and the frontend history row count narrowed (docs/010); no other test confirms a Refund or forfeiture draft while a receipt reversal draft is pending. Before P2 also: the only unscoped count my tests could disturb is the Pet Refund review count in `test_lease_migration.py`; the only head-code read on an old revision is `test_v1_038...`.

- U1 backend unit: 3441 passed, 1634 skipped (`V1-056-slice-08a2-unit-test-run.txt`).
- P1 full PostgreSQL: 2 failed, 1789 passed (`V1-056-slice-08a2-full-test-run.txt`). Cause A: `test_migrations.py::test_v1_038_upgrade_projects_legacy_pet_departure_authorization` runs the head Deposit ledger read on a database held at revision `20260831_37`, where `app.deposit_application_history` does not exist. Cause B: `test_lease_migration.py::test_nonbilling_lease_event_term_and_pet_stores_are_append_only` counts every Pet Refund review of the shared database, and the new Pet Refund wait test ran before it. Correction A1: that test reads the departure authorization by the same derivation (docs/010). Correction B1: the new test moved to `test_pet_refund_migration.py`, which runs after it.
- Unintended run: one command meant to check the lint exit code also started `make backend-test` with its output discarded; it was stopped within two minutes, no result used.
- U2 targeted: `tests/test_traceability.py` 28 passed (`...-unit-test-run-2-targeted.txt`), cause: the moved test's manifest path; it covers the only unit test the move affects.
- P2 full PostgreSQL: 1791 passed (`...-full-test-run-2.txt`). Two extra warnings are pydantic schema warnings in credit refund API tests (no model changed).
- F1 frontend: 1591 passed (`...-frontend-test-run.txt`); frontend build passed.
- Static checks: `V1-056-slice-08a2-static-checks.txt` (ruff format and check, mypy, frontend format, lint, typecheck, build: all exit 0).
- U3 backend unit: 3441 passed, 1636 skipped; P3 full PostgreSQL: 1793 passed (round-1 fixes).
- U4 backend unit: 3441 passed, 1637 skipped; P4 full PostgreSQL: 1794 passed (round-2 fix; the standing rule's runs before round 3).

Migration status: no development database exists (docs/010, 2026-10-03); every run applies all migrations to fresh databases.

## Round 1 — independent review

No blocker. Should-fix: (1) race between a confirm and a receipt reversal draft being recorded (the recorder held only an advisory lock; Pet Refund and Reservation confirms lock only the Deposit row) — fixed: the recorder locks the Deposit row after its advisory lock, two-connection test; (2) boundary tests — added: withdrawal and rejection pass while pending, 6b forfeiture reversal is not held back; (3) the `test_v1_038` change replaces a production read — answered in writing (revision 37 database cannot call a migration-88 object). Notes taken: uuid comparisons in the trigger, both-pending case in docs/004, exact header count, static check outputs saved. Notes moved to the plan (slice 12): message-text mapping in `RefundService`, test-order coupling on the Pet Refund review count.

## Round 1 — security review

No blocker. One should-fix, the same race, fixed as above. Notes: the history read has no actor parameter (acceptable; narrower than the direct table grants of the Deposit read); each ledger names the other Customer when they differ (owner-approved); the in-place ledger page patch is sound; no bypass of the trigger; Final Settlement drafts are for 8c/8e.

## Round 2 — independent review

No blocker. One should-fix: the round-1 written answer was inadequate, because no head test reached the legacy combined-qualification branch of the Deposit ledger read — fixed: `test_the_deposit_history_reads_a_legacy_combined_qualification_departure` reads such a departure through the production read. Notes taken: the exact guarantee and the READ COMMITTED reliance in the migration and docs/004; `pg_blocking_pids` check in the race test.

## Round 2 — security review

No blocker, no should-fix. Race closed in both orders; no deadlock cycle (every holder of the advisory lock takes it before the Deposit row); patch keeps owner and ACL; trigger casts safe for every payload shape. Notes: wording of the guarantee (taken), isolation dependency (taken as documentation), no concurrent Reservation test (plan, slice 12).

## Round 3 — independent review

No blocker, no should-fix. The legacy-branch test exercises the LATERAL branch and fails if it breaks; docs accurate. Notes (plan, slice 12): the recorder could call `app.serialize_deposit_state` instead of a bare row lock so a stricter isolation fails with 40001; the migration docstring says "after the wait for the Deposit row", which for the Lease forfeiture confirm is the advisory lock (docs/004 is exact); a confirm-stage race test could join the Reservation concurrency test.

## Round 3 — security review

No blocker, no should-fix. Nothing since round 2 changed security behavior. Notes (plan, slice 12): the trigger or the confirm services could enforce READ COMMITTED; the least-privilege test could also check the trigger function's definer settings and PUBLIC directly; committed run outputs contain no credentials or customer data.
