# V1-056 sub-slice 10e-2d — a forfeited right receipt keeps the pay-back money — review record

Sub-slice: 10e-2d (owner answer (a) to Q-2026-10-12-93). Migration `20261223_149` (exact-text
patches only at first; one new internal function under the Q-122 answer). Base commit: 238a1c8.
Built on 2026-10-17. Stopped after review round 1 for Q-2026-10-17-122 (a money-rule blocker);
finished in a fresh session under the answer and committed after review round 3. Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-008, DL-032, BR-DEP-022, BR-DEP-023; DB-SETTLE-005, DB-DEP-004,
DB-DEP-005.
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
- Traceability: one note of entry 2,987 updated; three entries appended (3,170 to 3,172). At the
  commit: notes of entries 2,974 (the rename) and 2,987 updated; eight entries appended (3,170 to
  3,177).
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

## Status after round 1

Stopped under the takeover stop conditions (a review finding that changes who pays or how much
needs the owner). Nothing of the build was committed; this record, the plan text, the question and
the NOW.md line were committed as records only (e5bcb2b).

## Owner answers (2026-10-17, fresh session)

Q-2026-10-17-122 (b): the pay-back count includes only money the Customer has not received yet;
money already paid out is not paid back again; one rule on every path; where nothing was paid out
the result stays as built. The `FORFEIT` refusal reading is confirmed. Q-2026-10-17-121 (a) is
recorded too (built later as sub-slice 10g-2); its records ride in this commit.

## Built under the answer (working tree, before round 2)

- Design: plan, "Q-122 design" (catalog dumps D3 to D5, read only, no `REDACTED` marker in D3 and
  D4; D5 has one `[HEX REDACTED]` marker outside the copied text).
- New internal `app.lease_deposit_payback_count_as(deposit, returned_refund, returned_amount,
  without_payouts)`; patched: the count, the returned-Refund check, the receipt correction targets
  (the corrected receipt's own Deposit without payouts), the overlay (`corrected_deposit_id`),
  `app.settlement_correction_plan_result` (the key's check and the 10e-2d branch); the five patches
  of the first build stay. Eight patched functions, one new.
- Tests: the security reviewer's $30 / $50 case (both receipts forfeited whole; non-review Refunds
  3,000, applications 0, count 0), the round 1 staff-choice set-up on the real path (5,000
  forfeited whole), the count on the real path (a return-only correction of the Settlement Refund
  puts 1,000 back; a hand-built rolled-back application and its reversal), the plan check with the
  key; the round 1 comment fix in the committed forfeiture test.
- Read-only search for affected tests before T2: every test naming the pay-back functions, the
  path, the forfeiture source, the disposition check, the returned-Refund plan, the receipt
  correction functions, `deposits_after` or the plan result, and every module that creates Pet
  Refund-review Refunds and touches a Deposit with a ground after a payout (27 modules in T2).

## Runs (this session)

| Run | Result |
|---|---|
| D3, D4, D5 | catalog dumps (read only) |
| M3 | passed |
| FF2/FC2/L2/Y2 | passed (formatter first; long lines fixed before L2 by the formatter) |
| T2 | 4 failed, 538 passed: cause A (the new least-privilege test read the wrong tuple index; 1 of 2), cause B (two committed whole-overlay expectations lack `corrected_deposit_id`; 1 of 2), cause C (`test_refund_signer_recipient_migration.py::test_refunds_of_the_earlier_shape_project_exactly_as_before` ran after Settlement modules: the known order dependency of the slice 12 list, plan "Open item (sub-slice 8d, tests only)"; 1 of 2, fixed by the run order) |
| T3 | 20 passed (the signer test first, the new module, the two changed committed modules): the passing rerun after A, B and C |
| U2 | 3847 passed |
| M4 | passed |
| P2 | 2249 passed (the known Starlette deprecation and Pydantic alias warnings) |
| FF3/FC3/L3/Y3 | passed (after the round 2 fixes) |
| M5 | passed |
| T4 | 299 passed (the new module, the three changed committed modules, the service unit tests) |
| U3 | 3847 passed |
| M6 | passed |
| P3 | 2253 passed (the same known warnings) |

Full outputs: `~/Development/prm-run-logs/v1-056-10e-2d-*.txt` (the format, lint and type checks
are short and not saved).

## Review round 2 (fresh read-only subagents, during P2; told to write no files at all, scratch files included, and to run no test, script or database command)

Security: 0 blockers, 1 should-fix, notes. Independent: 0 blockers, 4 should-fix, notes. Blocker B1
of round 1 is closed on every path traced (Settlement Refund and application, correction
application and Refund, forfeiture reversal Refund, returned Settlement Refund, return reversal,
recovery by a charge); the new count is never above the as-built count. Both reviewers confirm the
three implementer's readings as needed and safe: (i) a `RECOVERED_BY_CHARGE` recovery undoes the
payout (the other reading would charge the Customer and let the Property keep the money); (ii) a
payout takes pay-back money first; (iii) the corrected receipt's own Deposit is counted without
payouts, with the server-built `corrected_deposit_id`. No changed committed test got weaker (the
two overlay expectations are stricter; the rename changes name and traceability only).

Should-fix, all fixed (tests, text, one fail-closed check):
- Security S1 / independent 2: the core money path (a partial forfeiture whose pay-back part the
  step applies, the writer's exact check with a pay-back value, the own-Deposit count) had no
  real-path test, and the plan's "no real path" for the own Deposit was wrong: the seeded Pet
  receipt has a RECEIVED Payment and a committed test corrects such a receipt into the same Pet
  Deposit (`test_settlement_deposit_receipt_recovery_line_migration.py:140`). Fixed with the
  set-ups below; plan corrected.
- Independent 1: the plan promised a test of a return reversal and of a recovery by a charge in the
  count test. The recovery is now tested on the real path (set-ups B, C, A, D); the plan text no
  longer claims a separate return reversal test (the same sum of Refund correction effects).
- Independent 3: the hand-built own-Deposit assertion at the count (`!= ONLY_DL_032`) was weak:
  removed; set-up A records such a draft on the real path.
- Independent 4: the rename and the two changed overlay expectations are now in the plan and
  docs/010, and the rename in the traceability file; docs/010 build and "Updated tests" notes written.
- Security note 2 (fail closed): the plan check's 10e-2d branch now wraps its condition in
  `COALESCE(...,false)`, so a missing value refuses.
- Notes taken as text: the migration docstring calls the lower count an owner-approved narrowing
  (security note 6; docs/010 too); the service docstrings of the receipt correction name the
  pay-back count (round 1 note); the param ids of the first test; the traceability wording of the
  plan-check entry.

Notes kept (for the report): a new-Refund return of the forfeiture reversal's Pet Refund after a
staff re-forfeit is refused (count 0; answer (b); unreachable at HEAD); the other-money refusal is
reachable on a real path (a Pet Deposit holding unreceived pay-back money after a return-only
correction): a known limit; security note 5, a Pet Refund-review Refund recovered by a charge still
lowers the count as built: asked as Q-2026-10-17-123 (before 10e-2b-4, recommendation (a));
security note 7, for 10e-2b-3 and 10e-2b-4: the forfeiture formula relies on the target holding
nothing else after the correction (if that is relaxed, use the held amount after the correction);
`app.lease_deposit_kept_rule` in the plan check can raise 22023 rather than 55000 for a Pet Deposit
off DL-032 without a termination (no path reaches it); payouts include applications to any debt
of the Lease and Refunds to an agreed Signer ("applied or refunded").

### Round 2 test set-ups (written in full, run rule of 2026-10-13)

- A (security and independent; the corrected receipt's own Pet Deposit): `payback_ground_case(url)`
  (count 0, without payouts 3,000, held 0). Correct `receipt_of(url, pet)` (the seeded 5,000, its
  Payment P) with `receipts=(CorrectionDepositReceipt(pet, X),)`, X = 4,000 or 2,000; the
  correction recovers by a charge the review Refund's 2,000 and `settlement_pet_refund`'s 3,000
  (held 0 + 2,000 + 3,000 = 5,000, the Deposit ends empty); steps: `PET_REST` of min(X, 3,000) onto
  the placeholder `deposit_receipt_recovery_line_id(draft_id, settlement refund)`, `pet_remainder=STAFF`.
  At record: target count 3,000; X 4,000 lists a 1,000 `TERMINATION_GROUND` forfeiture on BR-DEP-022
  (X 2,000 lists none); `deposits_after` {pet: min(X, 3,000)}, `corrected_deposit_id` pet; open 5,000,
  closing 5,000 less min(X, 3,000). At confirm: both recoveries linked, the 5,000 receipt reversed
  and the X receipt written, X 4,000 forfeits 1,000 (linked, after the receipt), the application
  pays min(X, 3,000) on the Settlement Refund's recovery line, the review Refund's line owes 2,000,
  held 0, count 0 (X 4,000) or 1,000 (X 2,000), without payouts 3,000, path KEPT or NOTHING_HELD,
  `available(P)` up by 5,000 less X, the ledger reconciles.
- B (independent; reading (i) alone): `payback_ground_case(url)`, then record and confirm
  `request(case, receipt_of(url, pet))` with no receipts: the recovery lines are 3,000 and 2,000,
  held 0, count 3,000, path NOTHING_HELD.
- C (independent; a forfeited right receipt into another Pet Deposit whose count is above 0 after
  payouts): after B, the receipt correction of the 10,000 Security receipt with Security 5,000
  (`DL_032`) and Pet 5,000 (`record_correction(case, 5_000, 5_000)`): forfeiture 2,000
  (`TERMINATION_GROUND`), `deposits_after` {security 5,000, pet 3,000}; at confirm 2,000 forfeited,
  applications Security 5,000 and Pet 3,000 on the 10,000 recovery line (2,000 owed), count 0, path
  KEPT, the ledger reconciles. (The security reviewer's optional set-up C, the same through the
  RETURNED_PAYMENT correction of the seeded Pet Payment, is not built: set-up B reaches the same
  state through the receipt correction.)
- D (both; the staff choice refusal on the real path): `payback_ground_case(url, forfeit_pet=True)`,
  then the B-style correction of the seeded 8,000 Pet receipt (recoveries 2,000, 3,000 and 3,000;
  count 3,000, held 0, forfeiture reversed, path DL_032); `record_correction(case, 5_000, 3_000,
  "FORFEIT")` is refused (55000, "Nothing beyond the Customer's pay-back money is left to forfeit;
  choose DL-032"), nothing written; `(5_000, 5_000, "FORFEIT")` lists 2,000 `STAFF_CHOICE` with the
  outcome reason, `deposits_after` pet 3,000, and the confirm applies Security 5,000 and Pet 3,000,
  count 0, path KEPT, the ledger reconciles.
- The security reviewer's set-up B (the forfeit_pet case's own Pet receipt with a partial
  `STAFF_CHOICE` forfeiture) is covered by A (own Deposit) and D (staff choice).

All four built as tests in the new module (A parametrized); T4 and P3 passed.

## Review round 3 (fresh read-only subagents, after U3 and P3; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: clean (0 blockers, 0 should-fix; four optional notes). Security: clean for code and
security (0 blockers, no code should-fix); one should-fix in the records and two notes. Both
confirm every round 2 should-fix fixed, B1 closed, the own-Deposit count unreachable by crafted
input (the source and the overlay are built by the server; the plan result has no grant), no
changed committed test weaker, the texts matching the code and the runs the right evidence.

Fixed under the run rule "Round 3 text and assertion fixes" (no code, migration logic or fixture
change; no round 4):
- Security S1 (records): Q-2026-10-17-123 did not cover set-up C, where the Pet Refund-review
  Refund's own unreturned 2,000 is recovered by a charge and the new receipt still forfeits 2,000:
  the question now has that case and three options, recommendation (a) a recovery by a charge
  counts like a verified return; the test's 2,000 is marked as depending on the answer (plan,
  docs/010, the test's docstring).
- New assertions in built tests (security N1, independent note 4): set-up D asserts the linked
  2,000 `STAFF_CHOICE` forfeiture row and the 2,000 still owed on the recovery line; set-up A at
  2,000 asserts that the draft has no forfeiture key (independent note 3).
- Text: docs/004 and the migration docstring say that a count that would still be too high fails
  closed at the confirm (security N2); the record's status, rule IDs, traceability count and the
  overlay-expectation wording (independent notes 1 and 2).

| Run | Result |
|---|---|
| FF4/FC4/L4/Y4 | passed |
| M7 | passed |
| T5 | 10 passed (the new module; the last targeted run of every file changed since P3) |
| P4 | 2253 passed (the known Starlette deprecation warning) |

Status: committed (see git log). Not pushed.
