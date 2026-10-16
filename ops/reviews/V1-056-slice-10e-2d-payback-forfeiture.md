# V1-056 sub-slice 10e-2d — a forfeited right receipt keeps the pay-back money — review record

Sub-slice: 10e-2d (owner answer (a) to Q-2026-10-12-93). Migration `20261223_149` (exact-text
patches only). Base commit: 238a1c8. Built on 2026-10-17. STOPPED after review round 1 for
Q-2026-10-17-122 (a money-rule blocker); NOT committed. Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-008, DL-032, BR-DEP-022, BR-DEP-023; DB-SETTLE-005, DB-DEP-004.
Design: ops/V1_056_PLAN.md, "10e-2d pre-code design".

## Built (working tree, not committed)

- Migration `20261223_149_deposit_receipt_payback_forfeiture.py`: exact-text patches of
  `app.settlement_deposit_receipt_forfeitures` (the receipt less the pay-back count, only amounts
  above 0), `app.assert_settlement_deposit_receipt_targets_allowed` (the pay-back part of the
  only-new-money refusal replaced by a refusal of a staff choice to forfeit again when the count
  covers the receipt), `app.settlement_deposit_receipt_correction_overlay` and the recorder (each
  receipt's forfeited amount, `forfeit_usd_cents`), and `app.settlement_correction_plan_result` (a
  Pet Deposit with a ground whose `deposits_after` is at most its count passes the record-time path
  check). No new function, table, trigger or grant.
- Tests: new `test_settlement_deposit_receipt_payback_forfeiture_migration.py` (3 tests, one with
  two cases; last in `scripts/database-test.sh`).
- Committed tests changed: `test_settlement_deposit_receipt_forfeiture_migration.py::
  test_the_outcome_input_and_the_new_money_refusals` (the two hand-built targets with a pay-back
  count of 1 moved from refused to passing, a comment, the docstring; owner standing rule, answer
  (a) to Q-93); the 27 head-revision assertions in 15 modules (revision strings only; a script
  checked each file's count).
- Traceability: one note of entry 2,987 updated; three entries appended (3,170 to 3,172).
- Docs: docs/004 (the receipt correction forfeiture paragraph).

Read-only search for affected tests (before T1 and P1): every backend test naming the five patched
functions, `deposits_after`, `deposit_receipt_forfeitures`, the receipt correction recorder or the
pay-back functions (13 modules, all in T1); tests reading function bodies (`prosrc`,
`pg_get_functiondef`) compare fixed earlier revisions or do not name the replaced texts; none
affected beyond T1.

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump of the receipt correction functions and the Deposit path (read only; no `REDACTED` marker) |
| D2 | catalog dump of `app.settlement_correction_plan_result` (read only; one `[HEX REDACTED]` marker, outside the patched text) |
| M1 | passed (`20261223_149` head) |
| FF1/FC1/L1/Y1 | passed (formatter first: one file reformatted); before L1 the changed files were searched for lines over 100 characters (the migration keeps `# ruff: noqa: E501`; one pre-existing long line in the committed test) |
| T1 | 360 passed (the new module and the 12 affected modules) |
| U1 | 3847 passed |
| M2 | passed |
| P1 | 2247 passed (the known Starlette deprecation and Pydantic alias warnings) |

No check or run failed, so no correction was counted. Full outputs are in
`~/Development/prm-run-logs/v1-056-10e-2d-*.txt` (format, lint and type checks are short and not
saved).

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Security: 1 blocker, 2 should-fix, notes. Independent: 0 blockers, 3 should-fix, notes.

- Blocker (security B1; checked by the implementer on the new test's numbers): the pay-back count is
  never lowered by a Final Settlement's or a correction's application or Refund of the pay-back
  money, and a target Deposit other than the corrected receipt's must hold nothing; so a Pet
  Deposit with a count that is empty after the closure has already given that money to the
  Customer. 10e-2d treats the new receipt's money up to the count as pay-back again: in the test
  (count 3,000, refunded 3,000 at closure, a new 5,000 Pet receipt) it forfeits 2,000 and applies
  3,000 for the Customer, 6,000 of pay-back against 3,000 returned; with the receipt right from the
  start, 5,000 would be forfeited. Not fixed: who pays and how much needs the owner
  (Q-2026-10-17-122, recommendation (b)). Reviewer's proposed assertion set (for whichever answer):
  after the 5,000/5,000 confirm, the Pet Deposit's non-review Refunds total 3,000, its correction
  applications total 3,000, `app.lease_deposit_payback_count` is 3,000 and the forfeiture 2,000.
- Should-fix (both): docs/010 has no 10e-2d build note and no "Updated tests (V1-056 sub-slice
  10e-2d)" note; the plan has no as-built bullet. Waits with the sub-slice (written at the commit).
- Should-fix (independent 2): the plan's design said the committed test also gains a `FORFEIT`
  target whose count covers the receipt; that case is only in the new module. Fixed in the plan text.
- Should-fix (independent 3; security S2): a staff choice to forfeit again (`FORFEIT`) with a count
  is tested only on hand-built targets. Set-up (independent; the security set-up is the same with a
  7,000 seed and a 2,000 forfeiture draft): a variant of `payback_ground_case`: seed 8,000 into the
  Pet Deposit; a 5,000 Pet Refund-review Refund, 3,000 returned (holds 6,000, count 3,000);
  terminate; `forfeit_through_draft(deposits, pet)` (forfeits 3,000) and the Security Deposit's
  forfeiture through the draft; the Settlement refunds the Pet Deposit's 3,000 (DL_032); a
  `FORFEITURE_REVERSAL` of the Pet forfeiture (refunds 3,000; `case["disposition"]` the Pet
  disposition), then of the Security forfeiture (refunds 10,000); the receipt correction of the
  10,000 Security receipt: 5,000 Security `DL_032` and 5,000 Pet `FORFEIT` with
  `OUTCOME_REASON`. Expected: the draft lists 2,000 `STAFF_CHOICE` with `OUTCOME_REASON`,
  `deposits_after` {Security 5,000, Pet 3,000}; the confirm forfeits 2,000 (linked), the Pet path is
  DL_032 before the step and KEPT after it; 5,000 and 3,000 applied to the placeholder line, 2,000
  owed; the count stays 3,000; the ledger reconciles; a 3,000 Pet `FORFEIT` receipt is refused at
  record (55000, "Nothing beyond the Customer's pay-back money is left to forfeit; choose DL-032"),
  counts unchanged. Waits for the Q-122 answer (the expected amounts depend on it).
- Notes (security): the relaxed plan check is reachable only through the receipt correction
  recorder (internal function; the overlay is built by the server from checked targets); the
  confirm-time step reads the real path and compares the whole result (P5S02); no grant, owner,
  security-definer or search-path change; no SQL injection (constant signatures, catalog text plus
  constant replacements); integer cents; no data in the new message; append-only, each record
  linked first; the relaxed check also accepts a Deposit with an active forfeiture (the path rule's
  first branch; the recorder refuses such a target); the forfeiture list and the targets check use
  the count for any Deposit type (a Security Deposit's count is always 0; fails closed), so the
  committed test's comment "takes the 7,999 beyond the count" on the hand-built Security target is
  wrong (the writer would refuse it): fix the comment or use a Pet target; the commit must leave
  out the unrelated Q-120 and Q-121 records or name them.
- Notes (independent): docs/004 "a changed pay-back count ... usually meets the targets check
  first" now holds only because after closure a count change comes with a held change; the 10e-2c
  sentence "The result gains `deposit_disposition_ids`" now follows the 10e-2d block (move the
  block); DB-DEP-004 has no 10e-2d pointer; the plan check's `PET` and ground conditions are not
  exercised by a test (unreachable through the recorder); optional staleness test (record the
  5,000/5,000 draft, then a return-only correction of the review Refund, 1,000: refused while the
  draft waits, or the confirm refused with 55000 or P5S02 and nothing written); the corrected
  receipt's own Deposit as a target with a count is untested; the other-money refusal is reachable
  on a real path (a Pet Deposit with a ground holding pay-back money after a return-only
  correction, `test_settlement_pet_payback_migration.py`), against the Q-93 text "no real path
  reaches that today"; the refusal of a staff choice when the count covers the receipt is an
  implementer's reading (named in Q-122); the plan-check test depends on today's pending-draft check
  (recheck in 10h); service docstrings `settlement_correction.py:774-776` and `:839-842` still say
  the whole receipt is forfeited; no BR-DEP-023 case with a count.

## Status

Stopped under the takeover stop conditions (a review finding that changes who pays or how much
needs the owner). Nothing of the build is committed; this record, the plan text, the question and
the NOW.md line are committed as records only.
