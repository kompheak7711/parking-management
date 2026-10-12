# V1-056 sub-slice 10e-2b-1 — the right receipt in a Deposit receipt correction: review record

Sub-slice: 10e-2b-1 (migration `20261126_122`). Base commit: 7757940. Built in one session on
2026-10-12 and committed locally (see git log; the commit right after 7757940). Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-008, BR-SETTLE-016, DL-032, BR-AUTH-010, BR-CREDIT-002;
DB-DEP-002, DB-SETTLE-005; owner answer 2 to Q-2026-10-11-83, answer (a) to Q-2026-10-11-86,
answers (a), (a), (a) to Q-2026-10-12-87, the owner instruction of 2026-10-12 with the answers to
Q-2026-10-12-88. Design: ops/V1_056_PLAN.md (10e-2b entry, "10e-2b pre-code design", the split
bullet and "10e-2b-1 as built").

The same commit records the owner answers to Q-2026-10-12-88 (point 1 (b), point 2 (c); built as
sub-slice 10e-2c) and the split of 10e-2b into 10e-2b-1 and 10e-2b-2 (owner instruction: the
implementer may split without asking) in docs/010, ops/V1_056_QUESTIONS.md and the plan.

## Built

- Migration `backend/migrations/versions/20261126_122_deposit_receipt_correction_receipts.py`:
  - Rule 1: the key `UNIQUE (deposit_id, payment_id)` is dropped; `app.validate_deposit_receipt`
    refuses a second active receipt of one Payment in one Deposit (23505).
  - Rule 2: in the same check a Security Deposit's first active receipt may differ from the accepted
    amount only when a correction of the Lease's closed Final Settlement, confirmed in this
    transaction, links it; the required-amount check is unchanged.
  - DB-SETTLE-005 gains `deposit_receipt_id` (the link functions rebuilt as in sub-slice 10c-2a-5).
  - New internal functions (no grant): `app.settlement_deposit_receipt_correction_targets`,
    `app.assert_settlement_deposit_receipt_targets_allowed`,
    `app.settlement_deposit_receipt_correction_overlay`, `app.write_correction_deposit_receipt`
    (rule 3: the only Pet Deposit receipt writer; it writes only a receipt its correction's draft
    names, from that draft's Payment, with a `deposit.receipt.recorded` Deposit audit event).
  - The 10e-2 input function is replaced in place (optional `receipts` and `plan`, both or neither).
  - Exact-text patches: `app.validate_deposit_receipt`, `app.settlement_correction_plan_result`
    (optional overlay key `deposits_after`, absolute, above 0 only on the DL-032 path),
    `app.lock_settlement_correction_plan` (a receipt correction with a plan locks its targets), the
    10e-2 recorder (targets check, overlay, plan result in the payload), write helper (targets
    check under the locks; the new receipts, then `app.post_settlement_correction_plan`) and result
    (four id lists).
- Service: `CorrectionDepositReceipt`; `RecordDepositReceiptCorrectionCommand` gains `receipts`,
  `steps` and `pet_remainder` (a plan only with a receipt).
- Tests: new PostgreSQL module `backend/tests/test_settlement_deposit_receipt_rewrite_migration.py`
  (5 tests, last in `scripts/database-test.sh`); three unit tests in
  `backend/tests/test_settlement_correction.py`.
- Changed committed tests: only the 27 head-revision assertions in 15 modules
  (`20261125_121` to `20261126_122`). No fixture changed.
- `ops/traceability.json`: eight entries appended. docs/004 (DB-DEP-002, DB-SETTLE-005, a pointer in
  DB-DEP-007), docs/010 (owner answers, split, sub-slice entry, updated tests, rounds 1 and 2), the
  plan (answers, split, as built), ops/V1_056_QUESTIONS.md (Q-88 answered).

## Runs

Static checks, each in its own call: format check 2 files on the first run (cause A: formatting of
the two new test files; 1 correction of 2, `ruff format` on those files), then clean; lint 2 long
lines (cause A, the same cause: 2 corrections of 2 used), then clean; mypy clean. After the round 1
fixes: format, lint and mypy clean. Migration-only check (`scripts/migration-check.sh`): 121
upgrades, head `20261126_122`, before T1 and again before T2. Read-only search of every backend test
for the dropped key, its error, the rebuilt one-link check, constraint reads of the changed tables
and 23505 receipt expectations: none outside the new module; the patched shared step and lock
function are used by every correction module, all in P1 and P2.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T1 | PostgreSQL targeted: new module, 10e-2 module | 11 passed, 1 failed | first run; cause B: the test assumed a Security Deposit required amount of 10,000 (it is 50,000), 1 correction of 2 | `V1-056-slice-10e-2b-1-targeted-test-run.txt` |
| U1 | backend unit, full (caffeinate) | 3774 passed, 1912 skipped, 1 failed | first unit run; cause C: traceability had no entries for the new tests, 1 correction of 2 | `V1-056-slice-10e-2b-1-unit-test-run.txt` (excerpt) |
| P1 | PostgreSQL full (caffeinate) | 2076 passed, 3 warnings (known) | first full run | `V1-056-slice-10e-2b-1-full-test-run.txt` |
| T2 | PostgreSQL targeted: new module, 10e-2 module | 12 passed, 1 warning | round 1 fixes | `V1-056-slice-10e-2b-1-targeted-test-run-2.txt` |
| U2 | backend unit, full (caffeinate) | 3775 passed, 1912 skipped, 1 warning | round 1 fixes and traceability | `V1-056-slice-10e-2b-1-unit-test-run-2.txt` (excerpt) |
| P2 | PostgreSQL full (caffeinate) | 2076 passed, 1 warning (known) | round 1 fixes changed the migration and tests (run rule) | `V1-056-slice-10e-2b-1-full-test-run-2.txt` |

The unit-run files are excerpts (every line except the SKIPPED lines); the full outputs are in
`~/Development/prm-run-logs/`. Secret check of all six outputs: no database URL, no `password=`, no
64-character hex string.

## Review round 1 (fresh read-only subagents, during U1 and P1)

Independent: 0 blockers, 2 should-fix, 5 notes. Security: 0 blockers, 1 should-fix, 4 notes.

Fixed:
- Security SF-1 (and independent note 4): the new receipt had no Deposit audit event of its own; the
  writer now writes `deposit.receipt.recorded` (tested).
- Independent SF-1: docs/004, docs/010, the plan's as-built line and traceability were missing.
- Independent SF-2: refusals were proven only on edited JSON; new real-path refusals: a kept target
  Deposit (the Pet receipt of the real kept case), an unknown Deposit (P0002), the writer outside its
  correction, and the plan check refusing a held value for a Deposit off the DL-032 path.
- Security note 1: the writer checks that its correction's draft names the receipt and its Payment.
- Both reviewers' note: `deposits_after` above 0 only on the DL-032 path.
- Independent note 3: the confirm's audit event is dated after the step's records.
- Independent note 5: a comment and docs/004 name the rule 1 check's dependence on the Deposit lock.

Listed (docs/010, slice 12): owner rule 3 is held by the single internal writer, not by the table
(requiring a correction link for every Pet Deposit receipt would be a tightening, so it needs the
owner's word); a two-connection test of rule 1; a Deposit of another Lease is tested only on a
changed target; the outside-a-correction receipt checks roll back before the deferred budget
triggers. Independent note 1 (the 10e-2 result gains four empty id lists): docs/005 in slice 11e.

## Review round 2 (fresh read-only subagents, during U2 and P2)

Independent: 0 blockers, 0 should-fix, 6 notes; it compared every changed committed test with HEAD
(27 head-revision lines in 15 modules; three unit tests added) and found nothing weaker; traceability
only appended, every new entry names an existing test; all 13 patch anchors count once in the
head-120 catalog. Security: 0 blockers, 0 should-fix, 4 notes. No round 3.

Text fixed after P2 (no code or test change): BR-CREDIT-002 in the first new test's traceability
entry; docs/004 DB-DEP-007 ("no DL-032 step" holds without right receipts) and DB-DEP-002 (the
audit event's statement time); docs/010; this record. Carried into sub-slice 10e-2b-2 (it changes
the same writer): the writer also requires its correction's decision confirmed in the current
transaction (both reviewers), with real-path tests of the draft-naming refusal. Slice 12 items: the
receipt audit event has no linked source event and no Deposit command row; a test of the confirm
audit event's time. Point for the owner: a correction that writes the same receipt again into the
same Deposit changes only the DL-032 use of that money; it is accepted today (it needs a reason and
the `financial.approve` confirm).
