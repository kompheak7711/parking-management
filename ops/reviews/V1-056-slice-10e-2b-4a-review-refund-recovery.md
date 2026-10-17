# V1-056 sub-slice 10e-2b-4a — a Pet Refund-review Refund recovered by a charge counts as returned — review record

Sub-slice: 10e-2b-4a (owner answer (a) to Q-2026-10-17-123). Migration `20261225_151` (one
exact-text patch of `app.lease_deposit_payback_count_as`). Base commit: 9198b57. Built on
2026-10-17. Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-008, DL-032, BR-DEP-022, DL-053; DB-DEP-004, DB-REFUND-002.
Design: ops/V1_056_PLAN.md, "10e-2b-4 pre-code design", "10e-2b-4a" and "10e-2b-4a as built".

## Built

- Migration `20261225_151_pet_review_refund_recovery_payback.py`: the Pet Refund-review part of the
  count also adds each `RECOVERED_BY_CHARGE` row of such a Refund; without payouts (the receipt
  correction's own corrected Deposit) it also adds, at the end, what is still to recover of each
  Pet Refund-review Refund of the Deposit; at the same moment and event order an addition comes
  before a subtraction (`ORDER BY 1,2,4 DESC,3`, review round 1). No new function, table,
  trigger, constraint or grant.
- Tests: in `test_settlement_deposit_receipt_payback_forfeiture_migration.py`, three new tests (the
  own Pet Deposit forfeiting beyond the review Refund it charges back, the same-instant tie in both
  id orders, least privilege and forward-only) and a second case of set-ups B and C.
- Committed tests changed (owner answer (a) to Q-2026-10-17-123, owner note 3 of 2026-10-17 to the
  10e-2b-3 report): the fixture's own-Deposit count; set-ups A, B and C, D; the plan-check and count
  tests' own-Deposit values; each with its old and new value in docs/010 ("Updated tests (V1-056
  sub-slice 10e-2b-4a)"). The 27 head-revision assertions in 15 modules (revision strings only; a
  script checked each file's count).
- Traceability: five notes of entries after the first 1,598 updated (entries 3,171 to 3,177),
  three entries appended (3,181 to 3,183).
- Docs: docs/004 (a pointer under DB-DEP-004 and the bullet under DB-DEP-005); docs/010; plan; questions (Q-2026-10-17-124 for 4c, Q-2026-10-17-125
  from review round 1).

Read-only search for affected tests (before T1 and P1): every test of the count functions, of the
Deposit path's pay-back value and of the forfeiture source; every test that pays a Pet
Refund-review Refund and then returns its Payment or corrects its receipt
(`test_payment_return_migration.py`, `test_payment_return_recovery_migration.py`: no count, path or
forfeiture assertion afterwards); every receipt correction of a Pet receipt. Only the 10e-2d module
changes, plus the fixture used by `test_settlement_pet_receipt_link_migration.py` (its own results
do not change).

## Runs

| Run | Result |
|---|---|
| D1, D2 | catalog dumps for the pre-code design (read only; no `REDACTED` marker) |
| FF1/FC1/L1/Y1 | passed (formatter first, no file changed; long-line search first, none) |
| M1 (first attempt) | not started: `sh: scripts/migration-check.sh: No such file or directory` (the shell was in `backend/`); no check ran |
| M1 | passed (`20261225_151` head; script by its absolute path) |
| T1 | 15 passed (the 10e-2d module and the 10e-2b-3 module) |
| U1 | 3847 passed |
| M2 | passed |
| P1 | 2258 passed (the known Starlette deprecation and Pydantic alias warnings) |
| FF2/FC2/L2/Y2 | passed (after the round 1 fixes; formatter first, no file changed) |
| M3, T2 (first attempts) | not started (the shell was in `backend/`: the migration script's `cd backend` failed, and the targeted script printed "Test file is missing"; the second line was overwritten by the passing T2 output); no check or test ran |
| M3 | passed |
| T2 | 17 passed (the same two modules) |
| U2 | 3847 passed (includes `test_traceability.py`) |
| P2 | 2260 passed (the known warnings) |
| FF3/FC3 | passed (after the round 2 fixes; formatter first) |
| L3 | FAILED: `E501 Line too long (117 > 100)` at the tie test's docstring (line 1074). The long-line search found the line, but the lint call was started in the same batch, before the fix. Lint correction 1 of 2 (cause: a line over the limit) |
| Y3, M4 | passed |
| T3 | 17 passed (before the lint fix) |
| FF4/FC4/L4/Y4 | passed (after rewrapping the docstring; long-line search first, none) |
| T4 | 14 passed (the 10e-2d module, after the docstring fix) |
| U3 | 3847 passed |
| M5 | passed |
| P3 | 2260 passed (the known warnings): the full run after the last test and migration change |
| FC5/L5 | passed (after the round 3 text fixes; no Python file changed) |
| U4 | 3847 passed (includes `test_traceability.py`); no full run after the round 3 text-only fixes (run rule: text-only changes may skip it) |

One check failed (L3; lint correction 1 of 2); no test run failed. The not-started attempts are a wrong working
directory of the shell, not a failure of a check. Full outputs of every targeted and full run are in
`~/Development/prm-run-logs/v1-056-10e-2b-4a-*.txt` (format, lint and type checks are short and not
saved).

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: 0 blockers, 3 should-fix. Security: 1 blocker, 1 should-fix.

- Security B1 (blocker, fixed): a return reversal's charge-back of a returned Pet Refund-review
  Refund (sub-slice 10e-3d-2c, migration `20261210_136`) is dated at the same instant as the
  return's `CORRECTION_REVERSAL`; both are order 0, so `ORDER BY 1,2,3` let the random correction
  id decide the clamped count (0 or 2,000 in the reviewer's chain: a Customer paid back twice).
  Fixed: `ORDER BY 1,2,4 DESC,3` (an addition first: the "returns come first" rule); a hand-built
  rolled-back test of the tie in both id orders (the reviewer's set-up, below).
- Security S1 (should-fix, asked): the count reads the recovery row, not whether the recovery charge
  still stands; a forgiven charge still counts (the same holds for 10e-2d's undone payouts). Asked
  as Q-2026-10-17-125 (recommendation (a)); a known limit in the slice 12 list until answered.
- Independent S1 (fixed): set-up C's partial forfeiture on the ground (`TERMINATION_GROUND`) had no
  replacement; the B/C test has a second case, 3,000 Security and 7,000 Pet (2,000 forfeited, 2,000
  owed), the reviewer's set-up.
- Independent S2 (fixed): set-up A's `forfeited` branches could no longer run; removed. Named for
  the owner: with this fixture the own Deposit cannot forfeit on the ground (its Payment holds only
  the 5,000 the count covers), so the ground label of an own-Deposit forfeiture is tested only on
  hand-built targets; the own-Deposit forfeiture writer is tested on the real path with a staff
  choice.
- Independent S3 (fixed): docs/010 as-built and "Updated tests" entries, the plan's as-built line.
- Notes taken: the migration docstring names the stricter reach of the re-forfeit refusal; the
  Q-124 wording ("4b, as designed, refuses"); the plan's "no other path" claim corrected; the
  separate count test of the design is covered by the changed B/C test (named in the plan).

### Round 1 test set-ups (written in full, run rule of 2026-10-13)

- Independent S1 (built as the second case of `test_a_payout_recovered_by_a_charge_is_payback_money_again`):
  `case = payback_ground_case(url)`; `correct_pet_receipt(case)`; `(held, payback_count, path)`
  of the Pet Deposit `== (0, 5_000, "NOTHING_HELD")`; `draft = record_correction(case, 3_000,
  7_000)`; the draft lists one forfeiture of 2,000 (`BR-DEP-022`, `TERMINATION_GROUND`, `REASON`);
  `deposits_after == {security: 3_000, pet: 5_000}`; after `confirm`: the forfeiture linked to the
  correction, applications Security 3,000 and Pet 5,000 on the Security Refund's recovery line,
  2,000 owed, no Refund, the Pet Deposit `(0, 0, "KEPT")`, the ledger reconciles.
- Security B1 (built as `test_a_charge_back_at_the_instant_of_a_return_reversal_counts_alike_in_either_id_order`):
  `case = payback_ground_case(url)` (count 0 after the Settlement Refund); the review Refund's one
  `VALUE_CORRECTION`; in an owner transaction that is always rolled back, with the user triggers of
  `app.refund_corrections` disabled and the recovery charge's foreign key dropped, insert at
  `transaction_timestamp()+1s` a `CORRECTION_REVERSAL` of that return (-3,000; net 2,000 to 5,000)
  and a `RECOVERED_BY_CHARGE` of the review Refund (+3,000; net 5,000 to 2,000), once with ids
  (reversal `UUID(int=1)`, charge-back max) and once swapped; the count is 0 both times (the old
  order gave 3,000 in the first pass).

## Review round 2 (fresh read-only subagents, during P2; same instructions)

Independent: 0 blockers, 1 should-fix (text). Security: 0 blockers, 2 should-fix (text; a test
assertion). Both confirm the round 1 fixes: the sort is complete and deterministic (only order 0
has mixed signs; additions first equals one net event; no earlier result changes, because no other
mixed-sign tie can be written), the cents of every changed and new test, the rollback of the
hand-built test, least privilege and forward-only.

Fixed under the round-3 rule (text and a test assertion only; no code logic change):
- Independent SF1: Q-2026-10-17-125 and the slice 12 limit also name a VOID of an unpaid recovery
  charge's Invoice (`app.void_invoice`), in the case and in options (a) and (b).
- Security S1: Q-2026-10-17-125 no longer says 4b does not change the picture: once 4b lets Pet
  Deposit money in before closure, one staff member could forgive such a charge on an open Lease
  (credit Adjustment or VOID) without `financial.approve`; 4b waits for the answer (plan and
  questions).
- Security S2 and independent note 2 (stricter test): the tie test first inserts the charge-back
  alone and asserts 3,000, then the reversal and asserts 0; afterwards it asserts that the review
  Refund still has only its one correction and that the recovery foreign key still exists.
- Independent notes 1, 3 and 4 (text): the charge-back's sub-slice is 10e-3d-2c (migration
  docstring, test docstring, plan); the plan names `app.validate_general_refund_correction` as the
  guard that a recovery row is never reversed; docs/010 names set-up D's old `deposits_after` and
  applications.
- Independent note 5: the removed own-Deposit ground case is put to the owner in the report.
- Independent note 6: this record.

## Review round 3 (fresh read-only subagents, during P3; same instructions)

Independent: 0 blockers, 1 should-fix (text). Security: 0 blockers, 1 should-fix (records). Both
confirm every round 2 fix, the tie test's rollback and assertions, the migration SQL, the cents of
every changed and new test, the traceability changes and the 27 revision strings.

Fixed under the round 3 text rule (text only; no code, migration, test or fixture change; no round
4):
- Independent: docs/004 had only the bullet under DB-DEP-005 while the plan and this record said
  DB-DEP-004; a 10e-2b-4a pointer is added under DB-DEP-004 and the references name both.
- Security S1: the records did not name how a Pet Refund-review Refund gets a recovery charge on an
  open Lease: the sub-slice 10e-1c Payment return of the Pet Deposit's funding Payment
  (`test_payment_return_recovery_migration.py` shows it on a Pet Deposit seeded by a direct owner
  insert). Q-2026-10-17-125 and the plan now name it. The reviewer read the one-person path (a VOID
  or credit Adjustment of that charge) as reachable at this commit; on the app's real paths it is
  not, because no app function records Pet Deposit money before closure until 4b (Q-2026-10-12-92),
  and after closure the recovery charge sits on the closed Lease, where a VOID or an ordinary
  Adjustment is refused (P5S01; the independent reviewer of round 3 confirmed this). Put to the
  owner in the report; 4b waits for Q-2026-10-17-125.
- Notes kept: the migration docstring line of the round 2 edit is longer than 100 characters
  (the file keeps `# ruff: noqa: E501`; cosmetic, not rewrapped after P3); the tie test's
  traceability note could also name the round 2 assertions (optional); the lost real-path
  own-Deposit forfeiture on the ground is asked of the owner in the report.

Status: committed (see git log). Not pushed.

## Follow-up review (2026-10-17, owner answer 5 to the 10e-2b-4a report; fresh read-only subagent, told to write no files at all, scratch files included, and to run no test, script or database command)

Question: under the owner answers (a) to Q-2026-10-17-123, (a) to Q-2026-10-17-125 and to
Q-2026-10-17-124, does any real path still reach the removed check, the corrected receipt's own
Pet Deposit forfeiting a right receipt on the termination ground (`TERMINATION_GROUND`)?

Verdict: not reachable at HEAD, and not reachable with the planned 10e-2b-4b receipt writer;
reachable once the Q-125 answer is built. Reasons (the reviewer's, checked against the cited code):
the ground basis needs a Deposit never forfeited (`20261128_124`), the right receipts together
never take more than the corrected receipt frees and a right receipt into the same Deposit has
another amount (`20261127_123`, `20261126_122`), so R < C; the 10e-2 end-empty check makes C the
Deposit's only active receipt, and the own-Deposit count K (the running count without payouts plus
what is still to recover, 4a) is C less (held plus applications plus the other Refunds' net) plus
the running count; at closure a ground Deposit holds at most pay-back money (FORFEITURE_REQUIRED
blocks the confirm), and after closure only a new receipt (forfeited beyond the count, so ACTIVE) or
a forfeiture reversal (then STAFF_CHOICE) raises the held side, so C ≤ K and nothing is forfeited.
The 4b writer adds receipts only before closure and the closure check still applies. The Q-125
answer is the first event after closure that lowers the count without changing the held side, so
K < C becomes possible.

Outcome: the test is added in sub-slice 10e-2b-4b-1 (the Q-125 answer) on the real path (the
reviewer's route, made concrete there: set-up B/C, a `CHARGE_REDUCTION` of the review Refund's
recovery charge, then a receipt correction of the Pet receipt itself with a smaller right receipt).
If that build shows the case unreachable after all, the next review round confirms it before the
removal is recorded as accepted.
