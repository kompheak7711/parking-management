# V1-056 sub-slice 10e-2 — `DEPOSIT_RECEIPT_CORRECTION`: review record

Sub-slice: 10e-2 (migration `20261124_120`). Base commit: 809bd8f. Built in one session on
2026-10-12 and committed locally (see git log; the commit right after 809bd8f). Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-002, BR-AUTH-010, DL-032; DB-DEP-007,
DB-SETTLE-005; owner answer (a) to Q-2026-10-08-56, answers 1 and 3 to Q-2026-10-11-83, answer
(a) to Q-2026-10-11-86, the Q-2026-10-11-78 rule. Design: ops/V1_056_PLAN.md (10e-2 entry, "10e-2
pre-code design under the answers").

## Built

- Migration `backend/migrations/versions/20261124_120_deposit_receipt_correction.py`: the
  `DEPOSIT_RECEIPT_CORRECTION` variant of the `SETTLEMENT_CORRECTION` draft. Recorder
  `app.record_settlement_deposit_receipt_correction_draft` (`final_settlements.prepare`, READ
  COMMITTED, the `payment-return:` lock of the receipt's Payment) and confirm
  `app.confirm_settlement_deposit_receipt_correction` (`financial.approve`, a person, READ
  COMMITTED, replay, stale P5S02); internal input, source, refusal, result and write helper
  functions and the shared writer `app.write_correction_deposit_application_reversals`. The confirm
  recovers each Refund paid from the Deposit that is not fully returned (a `RECOVERED_BY_CHARGE`
  row and a charge to the person who received it), reverses the Deposit's applications newest
  first and the whole receipt; the freed amount stays unallocated with the Payment; no Credit, no
  Payment reversal, no DL-032 step; a kept Deposit is refused.
- Exact-text patches: `app.post_settlement_returned_payment` (its Deposit-application reversal loop
  moved unchanged into the shared writer), `app.refund_recovery_allowed` (also accepts a recovery
  inside this correction), `app.write_payment_return_recoveries` (the charge says "paid from a
  corrected Deposit receipt" for this variant only), `app.lock_settlement_correction_plan` (the new
  branch).
- Service: `RecordDepositReceiptCorrectionCommand`,
  `SettlementCorrectionService.record_deposit_receipt_correction` and
  `confirm_deposit_receipt_correction` (`backend/src/property_rental/settlement_correction.py`).
- Tests: new PostgreSQL module `backend/tests/test_settlement_deposit_receipt_correction_migration.py`
  (7 tests, last in `scripts/database-test.sh`); three unit tests in
  `backend/tests/test_settlement_correction.py`.
- Changed committed tests: only the 27 head-revision assertions in 15 modules
  (`20261123_119` to `20261124_120`). No fixture changed.
- `ops/traceability.json`: ten entries appended. docs/004 (DB-DEP-007, DB-DER-010 writers,
  DB-REFUND-002, the 10c-2b-2a sentence), docs/010 (sub-slice entry, updated tests, rounds 1 and
  2, owner answers of 2026-10-12), the plan (pre-code design under the answers, 10e-2b and
  10c-2b-6 entries, order), ops/V1_056_QUESTIONS.md (Q-86 answered, new Q-2026-10-12-87).

## Runs

Static checks, each in its own call: format check clean; lint 3 issues on the first run (cause A:
import order in two test files and one long docstring line; 1 correction of 2); after it lint
clean; mypy clean. Migration-only check (`scripts/migration-check.sh`): 119 upgrades, head
`20261124_120`, before T1, before P1 and after the round 1 message change (before T2 and P2).
Read-only search of every backend test for the four patched functions, the recovery wording and
the head revision: the affected modules are the new module, the 10e-1b and 10e-1c modules, the
correction modules that use the lock function and the 15 head modules, all in P1 and P2.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T1 | PostgreSQL targeted: new module, 10e-1b, 10e-1c | 28 passed, 1 warning | first run | `V1-056-slice-10e-2-targeted-test-run.txt` |
| U1 | backend unit, full (caffeinate) | 3762 passed, 1903 skipped, 1 warning | first unit run | `V1-056-slice-10e-2-unit-test-run.txt` |
| P1 | PostgreSQL full (caffeinate) | 2067 passed, 2 warnings (known) | first full run | `V1-056-slice-10e-2-full-test-run.txt` |
| T2 | PostgreSQL targeted: new module | 7 passed, 1 warning | round 1 fixes | `V1-056-slice-10e-2-targeted-test-run-2.txt` |
| U2 | backend unit, full (caffeinate) | 3762 passed, 1904 skipped, 1 warning | round 1 fixes | `V1-056-slice-10e-2-unit-test-run-2.txt` |
| P2 | PostgreSQL full (caffeinate) | 2068 passed, 2 warnings (known) | round 1 fixes changed the migration and tests (run rule) | `V1-056-slice-10e-2-full-test-run-2.txt` |

No run failed. Secret check of all six outputs: no database URL, no `password=`, no
64-character hex string.

## Review round 1 (fresh read-only subagents, during P1)

Independent: 0 blockers, 3 should-fix, 8 notes. Security: 0 blockers, 0 should-fix, 4 notes.

Fixed:
- SF-1 (independent): docs/004 DB-REFUND-002 named only the payment-return context of the
  recovery check; it now names this correction too.
- SF-2 (independent) and security note 1: new `test_the_database_guards_of_the_receipt_correction`
  (malformed input 22023, both authorization strings 42501, exact repeat and reused key, a service
  identity P4506, the confirm outside READ COMMITTED 55000, nothing written, the decided draft's
  replay without the transaction id, another approver 55000) and, in one transaction, a second
  statement after the Pet Deposit receipt's confirm that finds the recovery check false.
- SF-3 (independent): the forward-only test re-applies the migration's replacement pairs to the old
  definitions and compares them with the new ones.
- Notes fixed: the ends-empty refusal says "would not end empty"; the test comment on the
  after-commit recovery check; docs/004 notes for the shared writer and the 10c-2b-2a "until those
  exist" sentence; the plan bullet says which first-line text it replaces.

Listed (docs/010): slice 11e items (the result reads the Payment's available value live; the
generic draft reads still return the decision's transaction id, already listed); slice 12 items
(the reused 10e-1c messages speak of "this Payment's value"; the waiting-draft check matches ids
anywhere in a payload, the 10e-1a pattern; four guard refusals tested only on a changed source).
Answered: the database trusts `prm_financial` for the capability, as every confirm does (security
note 4, no change); the full-run note of the independent reviewer was read before P1 ended (P1
passed 2067).

## Review round 2 (fresh read-only subagents, during P2)

Independent: 0 blockers, 0 should-fix, 7 notes; it compared every changed committed test with HEAD
(27 head-revision lines in 15 modules, nothing else) and found nothing weaker. Security: 0
blockers, 0 should-fix, 3 notes. No round 3.

Text fixed after P2 (no code or test change): the docs/004 refusal list gains the three missing
refusals and one line is rewrapped; the docs/010 round 1 item (3) states exactly what the
forward-only test proves; this record. The other notes are slice 12 items in docs/010: the
authorization-string and HUMAN checks of the confirm are defence in depth behind earlier checks
(no test of their own); the recorder's reason check has no database test; a real-path "already
reversed" record and an INSERT of a recovery row outside a correction; the waiting-draft message
should name a recovered Refund; the shared receipt reversal writer records `deposits.correct`
while the approver acts under `financial.approve` (since 10e-1a); the relaxed recovery check's
second-layer conditions cannot be tested without forged rows.
