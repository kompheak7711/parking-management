# V1-056 sub-slice 10e-2b-2 — recovery charges as placeholder lines in a Deposit receipt correction: review record

Sub-slice: 10e-2b-2 (migration `20261127_123`). Base commit: 5e7752f. Built in one session on
2026-10-12 and committed locally (see git log; the commit right after 5e7752f). Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-008, BR-SETTLE-016, DL-032, BR-AUTH-010, BR-CREDIT-008,
BR-REFUND-015; DB-SETTLE-005, DB-DEP-002; the owner instruction of 2026-10-12 with the answers to
Q-2026-10-12-88 (point 4: the draft shows the exact amount and the person of each placeholder
charge line; a test proves the real charges match them exactly); owner answer 1 to
Q-2026-10-12-89. Design: ops/V1_056_PLAN.md (10e-2b split bullet, the owner answers to the
10e-2b-1 report, "10e-2b-2 as built").

The same commit records the owner answers to the two points of the 10e-2b-1 report
(Q-2026-10-12-89) in docs/010, ops/V1_056_QUESTIONS.md and the plan. Point 2 (the receipt table
requires a correction link for a Pet Deposit receipt) is not small: the committed fixtures give a
Pet Deposit its money by a direct insert before closure (34 modules import the Final Settlement
fixtures), so it is sub-slice 10e-2b-3 before 10h, waiting for the new Q-2026-10-12-90.

## Built

- Migration `backend/migrations/versions/20261127_123_deposit_receipt_correction_recovery_lines.py`
  (no table or column change):
  - New internal functions (no grant): `app.settlement_deposit_receipt_recovery_lines` (the
    placeholder lines from the source's recoveries on this Lease),
    `app.settlement_correction_line_id` (a placeholder to its real recovery charge line; any other
    target unchanged), `app.assert_settlement_correction_placeholder_lines` (the exact check,
    P5S02).
  - Exact-text patches: the receipt correction's target check (the 10e-2b-1 refusal lifted; the
    same receipt again refused, 55000), the receipt writer (decision confirmed in this transaction
    by this approver), the recorder (`new_obligations` in the overlay), the shared plan check (the
    key's shape, placeholders as open debt, the Credit of a placeholder Customer the preview does
    not name), the shared DL-032 step (the exact check, then mapped targets), the Credit step
    writer and the three checks that match a correction's Credit or Deposit application with its
    plan step.
- Service: `deposit_receipt_recovery_line_id(draft_id, refund_id)`; the command docstring.
- Tests: new PostgreSQL module `backend/tests/test_settlement_deposit_receipt_recovery_line_migration.py`
  (4 tests, last in `scripts/database-test.sh`); one unit test in
  `backend/tests/test_settlement_correction.py`.
- Changed committed tests (owner standing rule of 2026-10-11): the 27 head-revision assertions in
  15 modules (`20261126_122` to `20261127_123`); in
  `backend/tests/test_settlement_deposit_receipt_rewrite_migration.py` the 10e-2b-1 refusal of a
  correction that charges a Refund back on this Lease ends: the real Pet Deposit call now meets
  the shared "Every remaining Deposit balance must be applied or refunded" refusal (5,500 unused),
  the changed-target check with a recovery now passes; the old message constant and the
  docstrings follow. No fixture changed.
- `ops/traceability.json`: five entries appended, one later note changed. docs/004 (DB-SETTLE-005,
  DB-DEP-002), docs/010 (owner answers, Q-90, sub-slice entry, updated tests, rounds 1 and 2), the
  plan (answers, 10e-2b-3, as built), ops/V1_056_QUESTIONS.md (Q-89 answered, Q-90 open).

## Runs

Static checks, each in its own call, with the repo scope (`src tests`): lint cause A (four long
lines in the new test module as first written): 1 correction; its docstring rewrap left two later
lines long (cause B): 2 corrections, the second after checking every line's length first; format
cause F (the round 1 test): 1 correction. mypy clean throughout. The new migration (outside the
repo scope) was formatted with `ruff format` twice. Migration-only check
(`scripts/migration-check.sh`): 122 upgrades, head `20261127_123`, before T1, before T2 and before
T4. Read-only search of every backend test for the patched functions, the lifted message and the
overlay refusals: affected modules are the new one, the 10e-2b-1 rewrite module, the 10e-2 module,
the shared plan module and every correction module with Credit or Deposit steps (all in P1 and P2).

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T1 | PostgreSQL targeted: new, rewrite, 10e-2 modules | 13 passed, 2 failed | first run; cause C (migration): the Credit application insert check matched the draft step's placeholder target, 1 correction of 2 (the three step-match checks mapped); cause D (test): the counts baseline was taken before the draft was recorded, 1 correction of 2 | `V1-056-slice-10e-2b-2-targeted-test-run.txt` |
| T2 | PostgreSQL targeted: the same and the shared plan module | 24 passed, 1 failed | causes C and D fixed; cause E (test): the Credit application's line is in the details table, 1 correction of 2 | `V1-056-slice-10e-2b-2-targeted-test-run-2.txt` |
| T3 | PostgreSQL targeted: new module | 3 passed | cause E fixed | `V1-056-slice-10e-2b-2-targeted-test-run-3.txt` |
| U1 | backend unit, full (caffeinate) | 3776 passed, 1915 skipped, 1 warning (known) | first unit run | `V1-056-slice-10e-2b-2-unit-test-run.txt` (excerpt) |
| P1 | PostgreSQL full (caffeinate) | 2079 passed, 3 warnings (known) | first full run | `V1-056-slice-10e-2b-2-full-test-run.txt` |
| T4 | PostgreSQL targeted: new module | 4 passed | round 1 fixes | `V1-056-slice-10e-2b-2-targeted-test-run-4.txt` |
| U2 | backend unit, full (caffeinate) | 3776 passed, 1916 skipped, 1 warning (known) | round 1 fixes | `V1-056-slice-10e-2b-2-unit-test-run-2.txt` (excerpt) |
| P2 | PostgreSQL full (caffeinate) | 2080 passed, 1 warning (known) | round 1 fixes changed the migration and tests (run rule) | `V1-056-slice-10e-2b-2-full-test-run-2.txt` |

The unit-run files are excerpts (every line except the SKIPPED lines); the full outputs are in
`~/Development/prm-run-logs/`. Secret check of all eight outputs: no database URL, no
`password=`, no 64-character hex string. They show the local home path in a pytest warning, as
earlier records do.

## Review round 1 (fresh read-only subagents, during U1 and P1)

Independent: 0 blockers, 1 should-fix, 6 notes. Security: 0 blockers, 0 should-fix, 5 notes.

Fixed:
- Independent SF-1: no test reached the Credit of a placeholder Customer whom the preview does not
  name. New test on the real two-Signer closure (a FORFEITURE_REVERSAL refunded 10,000 to the
  second Signer, who holds 300 of Credit): the plan check refuses a plan that skips that Credit
  and gives exactly the result the same plan gives on the real charge line after the 10e-2
  correction writes it. The full record-and-confirm path waits for 10e-2c (the fixture's Deposit
  keeps its forfeiture ground); the plan gives it to 10e-2c's tests.
- Security note 1: a JSON null `customer_id` or `refund_id` passed the shape check; the ids must be
  strings (tested).
- Independent note 3: the placeholder amount within the shared overlay limit (tested).
- Independent note 2: one placeholder per Refund in the exact check.
- Independent note 7: DB-DEP-002 in the migration docstring.

Listed (docs/010, slice 12): the mapping and the exact check run for every correction variant
(safe: every recorder builds its own overlay); the three insert and deferred checks trust the
mapping; the exact check's refusals are proven by owner calls (on the real path the source digest
and the recovery writer's own P5S02 check fire first); a recipient's Credit read at record time;
the mapping fails closed (error 21000) if a recovery obligation ever had two lines; docs/005 in
slice 11e. Independent note 5 (the full run is required) was met by P1 and P2; note 6 (classify
the two changes): the same-receipt refusal is the owner's approved tightening, the writer's
same-transaction check a review-driven hardening.

## Review round 2 (fresh read-only subagents, during U2 and P2)

Independent: 0 blockers, 0 should-fix, 7 notes; it compared every changed committed test with HEAD
(27 head-revision lines in 15 modules; the two lifted cases) and found nothing weaker; traceability
only appended after the first 1,598 entries. Security: 0 blockers, 0 should-fix, 5 notes. No round
3.

Text fixed after P2 (no code or test change): docs/004 DB-DEP-002 names the writer's check and the
same-receipt refusal; docs/010 round 2 entry; this record (it did not exist during round 2). Listed
in docs/010 (slice 12): the one-placeholder-per-Refund condition and the existing-obligation
refusal of a placeholder key have no test of their own; the same-receipt refusal is tested at
record time only; the joint-Signer test does not call the recorder's builder and passes
`deposits_after` on the real line; a waiting Refund draft on a placeholder Customer's Credit is
refused only at the confirm; no check that a placeholder key equals its md5. BR-REFUND-015 is
missing from the migration docstring (a code file, left as run).
