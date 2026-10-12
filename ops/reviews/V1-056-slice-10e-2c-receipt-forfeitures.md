# V1-056 sub-slice 10e-2c — a right receipt into a Deposit with a forfeiture ground: review record

Sub-slice: 10e-2c (migration `20261128_124`). Base commit: 5d176fb. Built in one session on
2026-10-12 and committed locally (see git log; the commit right after 5d176fb). Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-008, DL-032, BR-DEP-019, BR-DEP-022, BR-DEP-023, BR-DEP-026,
BR-AUTH-010; DB-SETTLE-005, DB-DEP-002, DB-DEP-004; owner answers to Q-2026-10-12-88 (point 1 (b),
point 2 (c)). Design: ops/V1_056_PLAN.md (the "10e-2c pre-code design" and "10e-2c as built"
bullets).

The same commit records the owner answers of 2026-10-12: Q-2026-10-12-90 (a) (sub-slice 10e-2b-3
before 10h), the lint allowance ruling (Q-2026-10-12-91; the same kind of error is the same cause,
added to ops/V1_055_RUN_RULES.md), the owner's question answered in Q-2026-10-12-92 (nothing in the
app records Pet Deposit money before closure; recommendation: sub-slice 10e-2b-4), and the new
Q-2026-10-12-93 (a forfeited right receipt into a Pet Deposit with a pay-back count; refused until
answered).

## Built

- Migration `backend/migrations/versions/20261128_124_deposit_receipt_correction_forfeitures.py`:
  - DB-SETTLE-005 gains `deposit_disposition_id` (deferrable, unique, in the one-link check); the
    two link functions are rebuilt as in sub-slice 10e-2b-1.
  - New internal functions (no grant): `app.settlement_deposit_receipt_forfeitures(targets,
    reason)` (the forfeitures a correction writes, with basis `TERMINATION_GROUND` or
    `STAFF_CHOICE`) and `app.write_correction_deposit_forfeiture` (the linked forfeiture with its
    disposition context, audit event and Deposit command record, `occurred_at` after the receipt).
  - Exact-text patches: the input (optional `outcome` and `outcome_reason`, both or neither), the
    targets (the choice and the pay-back count), the targets check (the 10e-2b-1 "not supported
    yet" refusal replaced by the point 1 and point 2 rules and the Q-93 refusal), the overlay
    (forfeited money out of the plan), the recorder (`deposit_receipt_forfeitures` in the draft),
    the write helper (the recompute, P5S02, and the writes before the DL-032 step) and the result
    (`deposit_disposition_ids`).
- Service: `CorrectionDepositReceipt` gains `outcome` and `outcome_reason`; `RECEIPT_OUTCOMES`.
- Tests: new PostgreSQL module `backend/tests/test_settlement_deposit_receipt_forfeiture_migration.py`
  (5 tests, last in `scripts/database-test.sh`); two unit tests in
  `backend/tests/test_settlement_correction.py`.
- Changed committed tests (owner standing rule of 2026-10-11): the 27 head-revision assertions in
  15 modules (`20261127_123` to `20261128_124`); in
  `backend/tests/test_settlement_deposit_receipt_rewrite_migration.py` two expectations (the changed
  target with a ground now passes; the reversed Security Deposit without a choice now meets the
  "needs a choice" refusal), the message constant and the docstrings. No fixture changed.
- `ops/traceability.json`: seven entries appended, one later note changed. docs/004 (DB-SETTLE-005,
  DB-DEP-004), docs/010, the plan, ops/V1_056_QUESTIONS.md, ops/V1_055_RUN_RULES.md.

## Runs

Static checks, each in its own call, with the repo scope (`src tests`): lint cause A (one long line
in the new test module): 1 correction, after checking every changed line's length first; format
cause F (one call the formatter joins in the test module; then `ruff format` on the new migration,
outside the repo scope, which counts as the same cause under the owner's ruling of Q-2026-10-12-91
in the stricter reading of the run rules): 2 corrections, the limit. mypy clean. Migration-only
check (`scripts/migration-check.sh`): 123 upgrades, head `20261128_124`, before T1. After T1 and
before U1 and P1 only the migration's docstring changed (DB-DEP-004 added to its rule IDs, text
inside a Python docstring); P1 ran on the final file. Read-only search of
every backend test for the patched and rebuilt functions, the lifted message, the link columns and
the one-link check: affected modules are the new one, the 10e-2b-1 rewrite module (two cases), the
10e-2, 10e-2b-2, correction and forfeiture reversal modules (all in T1 and P1); the catalog tests of
earlier migrations compare fixed revisions and are unaffected.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T1 | PostgreSQL targeted: new, rewrite, recovery line, 10e-2, correction, forfeiture reversal modules | 36 passed, 1 warning (known) | first run | `V1-056-slice-10e-2c-targeted-test-run.txt` |
| U1 | backend unit, full (caffeinate) | 3784 passed, 1921 skipped, 1 warning (known) | first unit run | `V1-056-slice-10e-2c-unit-test-run.txt` (excerpt) |
| P1 | PostgreSQL full (caffeinate) | 2085 passed, 2 warnings (known) | first full run | `V1-056-slice-10e-2c-full-test-run.txt` |

The unit-run file is an excerpt (every line except the SKIPPED lines); the full output is in
`~/Development/prm-run-logs/`. Secret check of the three outputs: no database URL, no `password=`,
no 64-character hex string. They show the local home path in a pytest warning, as earlier records
do.

## Review round 1 (fresh read-only subagents, during U1 and P1)

Independent: 0 blockers, 1 should-fix, 7 notes. Security: 0 blockers, 0 should-fix, 6 notes. Both
confirmed: deny by default (no grant; the writer only inside its correction's confirm and only for
what the draft names, proven on the real path), staff cannot add a forfeiture the approver does not
see, only the new receipt's money is forfeited, integer cents, append-only, no injection, no route
change. The independent reviewer compared every changed committed test with HEAD and found nothing
weaker.

Fixed (text only, after P1):
- Independent SF-1: the docs/010 "Updated tests" entry and the plan's as-built bullet were missing.
- Independent notes 4 and 5: docs/004 says the forfeiture row's `occurred_at` (not the context's
  `recorded_at`) is after the receipt, and that the context's state-version check cannot fire here.
- Independent note 6: the as-built bullet states the built signature `(targets, reason)`.

Answered in writing (docs/010, slice 12 items; no code change after P1): the record-time "only the
new money" check skips the corrected receipt's own Deposit, which the 10e-2 "would not end empty"
refusal holds at 0, and the writer's exact check guards it again at the confirm (independent note
2, security note 1); the forfeiture recompute's P5S02 has no test of its own (independent note 3);
the writer's state-version check (independent note 4, security note 4); the missing-rule message
(independent note 7); no real path with two forfeitures or the writer's held-value refusal inside a
confirm, and the point 2 test compares three charge fields (independent note 8); the predictable
idempotency key, denial only, nothing written (security note 2); the `deposits.dispose` label with
the approver traced by the audit event, the link and the decision (security note 3); SECURITY
DEFINER on a function that reads no table, kept as the other internal functions (security note 5);
approver capability and preparer-versus-approver in the slice 11e routes (security note 6).

## Review round 2 (fresh read-only subagents, after P1; only text changed after round 1)

Independent: 0 blockers, 0 should-fix, 5 notes; it compared every changed committed test with HEAD
(27 head-revision lines in 15 modules; the two lifted cases) and found nothing weaker; traceability
only appended after the first 1,598 entries, one later note changed. Security: 0 blockers, 0
should-fix, 5 notes; it found every round 1 answer sound. No round 3.

Fixed (text only): the run rules line keeps the owner's words and marks "in another file or after a
rewrap" as the implementer's stricter reading (independent note 2); this record counts format cause
F as 2 of 2 and says what changed after T1 (independent note 3); ops/NOW.md updated in the commit
(independent note 4); BR-SETTLE-008 added to the point 1 and point 2 traceability entries and
DB-DEP-002 to the point 1 entry (independent note 5).

Listed in docs/010 (slice 12): the Q-93 refusal is proven on changed targets only, with no real Pet
Deposit that has a pay-back count (independent note 1); the writer does not compare the Deposit's
Lease with the correction's Settlement Lease or its rule with the draft's `governing_rule` (safe:
the targets check, the recompute and the link check hold both; security note 1); the forfeiture
recompute's P5S02 has no test (security note 2); the database does not stop a preparer who holds
`financial.approve` from confirming their own draft and trusts the capability text, as every
correction; it matters more now that a `FORFEIT` keeps Customer money (security note 3; slice 11e
or an owner decision); `CorrectionDepositReceipt` raises TypeError, not the invalid-input error,
for an unhashable `outcome` such as a list (security note 4; the slice 11e route model gives a
string); the slice 11e approver screen must show `deposit_receipt_forfeitures` with its basis, rule
and reason (security note 5).
