# V1-056 sub-slice 10e-3b — who pays back, and how much, in a return reversal: review record

Sub-slice: 10e-3b (migration `20261130_126`). Base commit: 321d05b. Built in one session on
2026-10-12 and committed locally (see git log; the commit right after 321d05b). Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-016, BR-REFUND-015, DL-032; DB-REFUND-002, DB-SETTLE-005;
owner answers (a) to Q-2026-10-12-94 and (a) to Q-2026-10-12-95, the Q-2026-10-11-78 rule and the
owner answer to Q-2026-10-10-76 (a new Refund pays the returned money first). Design:
ops/V1_056_PLAN.md (the "10e-3b" bullets, design and as built). Placement: right after 10e-3 and
before 10e-4, because it changes only the 10e-3 functions and tests (owner: "where it fits best
before 10h").

The same commit records the owner answers to Q-94 and Q-95 (docs/010, questions, plan; the older
plan text "the Deposit owner" updated), and opens Q-2026-10-12-96 (the Refunds paid out less than
the returned amount; refused until answered) and Q-2026-10-12-97 (the left value of an earlier
return-only correction; nothing waits for it).

## Built

- Migration `backend/migrations/versions/20261130_126_settlement_return_reversal_payback.py`:
  - New internal functions (no grant): `app.settlement_return_reversal_recovery_amount` (the share
    a confirmed `RETURN_REVERSAL` draft recorded for a recovery row's Refund; 0, so refused, on a
    repeat in the same correction or a draft naming the Refund twice) and
    `app.refund_recovery_source_reference` (the charge reference of the next recovery of a Refund;
    the first stays `refund-recovery:<Refund>`, a later one is numbered).
  - Exact-text patches: `app.settlement_return_reversal_source_state` (totals `uses`; the returned
    amount shared over the Refunds, oldest first, when the uses are more than it and the Refunds
    covered it; then empty application lists), `app.assert_settlement_return_reversal_allowed`
    (the agreed-Signer refusal removed; the Q-95 refusal narrowed to Q-96; a shared-path refusal
    of a Refund with its own return; missing totals refused),
    `app.settlement_return_reversal_refund` (the recorded recipient is the Refund's own),
    `app.validate_general_refund_correction` (a recovery is the recorded share inside a
    `RETURN_REVERSAL`, else the whole net), `app.write_payment_return_recoveries` (a share only
    inside a `RETURN_REVERSAL`; numbered reference), `app.refund_recovery_allowed` (numbered
    reference, counted before the checked row).
- No service, route or frontend change.
- Tests: `backend/tests/test_settlement_return_reversal_migration.py` (12 tests; 5 new).
- Changed committed tests (owner standing rule of 2026-10-11): the 27 head-revision assertions in
  15 modules (`20261129_125` to `20261130_126`); two tests of the 10e-3 module whose refusals the
  owner answers ended, changed in the affected case only and renamed with their traceability
  entries:
  - `test_a_held_value_refund_is_charged_back_and_an_agreed_signer_case_waits` is now
    `test_a_held_value_refund_is_charged_back_and_an_agreed_signer_pays_back_their_refund` (the
    later reversal charges the second Signer 500; the final Pet Deposit Refund net 17,900 instead
    of 17,400, because that return is reversed too);
  - `test_the_database_guards_and_the_refusal_of_uses_beyond_the_return` is now
    `test_the_database_guards_and_a_reversal_of_uses_beyond_the_return` (500 of the 1,500 Refund
    charged back, the 1,000 rest stays paid; plus the round 1 and 2 guard checks).
  No fixture changed.
- `ops/traceability.json`: the two renamed entries changed, five entries appended. docs/004
  (DB-SETTLE-005, DB-REFUND-002), docs/010, the plan, ops/V1_056_QUESTIONS.md, ops/NOW.md.
- The pending rename of `test_a_right_receipt_into_a_deposit_with_a_forfeiture_ground_waits_for_10e_2c`
  stays pending: its file was not touched in this sub-slice.

## Runs

Static checks, each in its own call, with the repo scope (`src tests`) and the new migration file
on its own: lint, format and mypy clean every time (no correction). Read-only search of every
backend test before T1: the removed refusal messages are used only in the 10e-3 module; the
patched writer and checks are exercised by the payment return, payment return recovery, returned
Payment, receipt correction, receipt rewrite and recovery line modules (T3 and T4 ran them).

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| M1 | migration-only check | passed, 125 upgrades | first | not saved |
| T1 | PostgreSQL targeted: 10e-3 module, payment return recovery, receipt correction, recovery line, refund | 67 passed, 1 failed | first run | `V1-056-slice-10e-3b-targeted-test-run.txt` |
| T2 | PostgreSQL targeted: 10e-3 module | 9 passed | cause A (test setup order), correction 1 of 2 | `-targeted-test-run-2.txt` |
| U1 | backend unit, full (caffeinate) | 3802 passed, 1930 skipped, 1 warning (known) | first full unit run | `-unit-test-run.txt` (excerpt) |
| P1 | PostgreSQL full (caffeinate) | 2094 passed, 2 warnings (known kinds) | first full run | `-full-test-run.txt` |
| M2 | migration-only check | FAILED (syntax error) | round 1 fixes; cause B | not saved |
| M3 | migration-only check | same failure | same code, run again only to read the error | not saved |
| M4 | migration-only check | passed | cause B, correction 1 of 2 | not saved |
| T3 | PostgreSQL targeted: 10e-3 module and the six recovery modules | 61 passed | round 1 fixes | `-targeted-test-run-3.txt` |
| U2 | backend unit, full (caffeinate) | 3802 passed, 1933 skipped, 1 warning | round 1 fixes | `-unit-test-run-2.txt` (excerpt) |
| P2 | PostgreSQL full (caffeinate) | 2097 passed, 3 warnings (known kinds) | round 1 fixes | `-full-test-run-2.txt` |
| M5 | migration-only check | passed | round 2 fixes | not saved |
| T4 | PostgreSQL targeted: as T3 | 61 passed | round 2 fixes | `-targeted-test-run-4.txt` |
| U3 | backend unit, full (caffeinate) | 3802 passed, 1933 skipped, 1 warning | round 2 fixes, before round 3 | `-unit-test-run-3.txt` (excerpt) |
| P3 | PostgreSQL full (caffeinate) | 2097 passed, 2 warnings (known kinds) | round 2 fixes, before round 3 | `-full-test-run-3.txt` |

Cause A (my new test): a return-only Credit correction is refused while the Customer has open
debt, so the 300 return had to come before the charge. Cause B (my migration): a `CASE` inside a
plpgsql `IF` condition (the condition ends at the first `THEN`; the same pitfall as 8c and 8e-2);
the planned net is now computed into a variable first. One more migration check did not run: a
working-directory race between parallel tool calls (`exit 127`, the script was not found); it is
not counted. The warnings are the known Starlette deprecation and, depending on test order, the
pydantic `UnsupportedFieldAttributeWarning` in `test_credit_refund_api_migration.py`. The unit
excerpts keep everything before the PASSES section and the summary without the PASSED and
SKIPPED lines; the full unit outputs are in `~/Development/prm-run-logs/`. Secret check of every
output: no database URL with a password, no `password=` value, no 64-character hex secret (only
masked or synthetic fixture values). After P3 only text changed (docs, questions, plan,
traceability notes, this record, the unit excerpts).

## Review round 1 (fresh read-only subagents, during P1)

Security: 0 blockers, 2 should-fix, 6 notes. Independent: 0 blockers, 6 should-fix, 8 notes; no
committed test weaker.

Fixed: security SF1 (a second recovery of a partly recovered Refund failed on the obligation key:
numbered references, tested on the real path when the Pet Deposit's Payment bounces); security SF2
and independent S3 (the writer takes a share only inside a `RETURN_REVERSAL`, tested); security
notes 3 and 4 (the decision check; the shared-path refusal of a Refund with its own return);
independent S2 (applications kept, tested on the real path), S4 (ledger reconciliation), S5
(wording: a Credit keeps what the other uses left), S6 (docs/010 updated-tests note), N3 (fail
closed), N5 (docstring), N7 (traceability tag). Answered in writing: independent S1 (the left
value; Q-2026-10-12-97), N1, N2, N4, N6, N8 (docs/010).

## Review round 2 (fresh read-only subagents, during P2)

Security: 0 blockers, 0 should-fix, 4 notes. Independent: 0 blockers, 2 should-fix, 8 notes; no
committed test weaker.

Fixed: independent SF1 (a repeated recovery of the same share in one correction: refused, tested
with a positive control); independent SF2 (Q-97's effect text corrected); security note 2 (the
numbered reference counted the row itself after it exists, which made two committed 10e-2
assertions false for the wrong reason: the reference now counts only recoveries dated before the
checked row); security note 1 (actor and decision-time ties); notes on the missing-totals message,
counts, docs/010 wording, the plan's as-built line, this record, the docstring.

## Review round 3 (owner standing rule; U3 and P3 ran on the final code before it)

Independent: 0 blockers, 0 should-fix, 4 notes; it compared every changed committed test with HEAD
and found nothing weaker; traceability only the two renamed entries changed, five appended.
Security: 0 blockers, 0 should-fix, 3 notes. Fixed as text: the docs/004 wrap and the unread
`deposit_customer` key named there; the unit excerpts shortened. Listed in docs/010 as slice 12
items: the refusal function's old sum check as defence in depth, the three `uses` keys required as
numbers, local paths in run outputs.
