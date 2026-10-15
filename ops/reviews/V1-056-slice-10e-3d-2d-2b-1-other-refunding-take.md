# V1-056 sub-slice 10e-3d-2d-2b-1 — a take by another Lease's correction that also paid a Refund from the returned Credit is undone through the companion — review record

Sub-slice: 10e-3d-2d-2b-1 (owner answers (a) to Q-2026-10-13-100 point 2 and Q-2026-10-13-103
point 3; owner answer 4 of 2026-10-16 to the 10e-3d-2d-2a round 3 report; split of 10e-3d-2d-2b,
owner allowed: 2b-1 this, 2b-2 the Refund part's charge-back through the companion). Migration
`20261213_139`. Base commit: d67f6d7 (10e-3d-2d-2a). Built on 2026-10-16. Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-014; DB-SETTLE-005. Design: ops/V1_056_PLAN.md,
"10e-3d-2d-2b pre-code note" (10e-3d-2d entry).

## Built

- Migration `20261213_139`: two exact-text patches of `app.settlement_returned_value_placed` (each
  anchor found once, else the migration stops): the `OTHER_SETTLEMENT` opened row of 2d-2a is
  removed, so a take by another Final Settlement's correction that also paid a Refund from the
  source is placed on its records; a part on any record of such a correction other than a Credit
  application (an allow-list, security round 1) is one open `OTHER_SETTLEMENT` part named by that
  correction. No other function, table, column, constraint, trigger, lock or grant change.
- Tests: new module `backend/tests/test_settlement_return_reversal_other_refunding_take_migration.py`
  (six tests), last in `scripts/database-test.sh`; committed test changed in
  `test_settlement_return_reversal_companion_migration.py`:
  `test_a_take_whose_correction_also_refunded_from_the_credit_stays_one_open_part` renamed
  `test_a_take_whose_correction_also_refunded_from_the_credit_is_undone_through_the_companion`
  (refused before, confirmed now; owner answer (a) to Q-2026-10-13-103 point 3; standing rules of
  2026-10-11 and 2026-10-14); the 27 head-revision assertions in 15 modules move to `20261213_139`
  (revision strings only, `sed`). Traceability: one entry renamed with new notes (after the first
  1,598), six appended.
- Docs: docs/004 (DB-SETTLE-005, a 10e-3d-2d-2b-1 paragraph), docs/010, the plan (pre-code note).

Pre-code read (2026-10-16): catalog dump D1 (`scripts/catalog-dump.sh` of the placed, walk, follow,
source, refusal, confirm, recovery writer, recovery allow, recovery scope and lock functions) and
D2 (the result and companion source functions); no `REDACTED` marker.

Read-only search at build (2026-10-16): the tests that expect the 2d-2a `OTHER_SETTLEMENT` part
from the real path: only the renamed test; the hand-built refused-first test in
`test_settlement_returned_value_other_settlements_migration.py` builds its part by hand (unchanged).
The other modules that call the placed function compare bodies at their own revision or use one
Settlement (the patch changes output only for another Settlement's correction). The round 1
independent reviewer's search agrees.

## Runs

Static checks each in its own call, formatter first (`ruff format src tests`). Outputs in
`~/Development/prm-run-logs/` (`V1-056-slice-10e-3d-2d-2b-1-*`); every targeted and full run under
`caffeinate -dims`.

| Run | Kind | Result | Cause |
|---|---|---|---|
| D1, D2 | catalog dumps (pre-code read) | printed | not checks |
| FC1, L1, Y1 | format check, lint, `mypy` | passed | first |
| M1 | migration-only check | passed (head `20261213_139`) | first |
| T1 | targeted: new, companion, 2d-1 modules | 12 passed, 2 failed (new tests: the second Lease's Rent line owes 79,000, more than its Pet Deposit; the Credit must pay all it holds before a Deposit pays, and the reviewer's set-up used a 300 charge) | cause A (test set-up), correction 1 of 2 |
| FC2, L2, Y2 | format check, lint, `mypy` | passed | after A1 |
| T2 | targeted: new module | 3 passed | passing rerun after T1 |
| U1 | backend unit, full | 3804 passed, 2021 skipped, 1 known warning | first |
| M2 | migration-only check | passed | before P1 |
| P1 | PostgreSQL full | 2185 passed, 2 known warnings (Starlette; pydantic) | first |
| FC3, L3, Y3 | format check (after `ruff format src tests`), lint, `mypy` | passed | round 1 fixes |
| M3 | migration-only check | passed | round 1 changed the migration (allow-list) |
| T3 | targeted: new and companion modules | 13 passed | round 1 tests |
| U2 | backend unit, full | 3804 passed, 2024 skipped, 1 known warning | round 1 fixes (traceability) |
| M4 | migration-only check | passed | before P2 |
| P2 | PostgreSQL full | 2188 passed, 2 known warnings (Starlette; pydantic) | round 1 fixes (read-only search before it: only the allow-list changed in code, the same result for a Credit source; the other tests that disable triggers do it in their own rolled-back transactions, run one after another) |
| FC4, L4, Y4 | format check (after `ruff format src tests`), lint, `mypy` | passed | round 2 fixes |
| T4 | targeted: new and companion modules | 13 passed | round 2 tests |
| U3 | backend unit, full | 3804 passed, 2024 skipped, 1 known warning | round 2 fixes (traceability) |
| M5 | migration-only check | passed | before P3 |
| P3 | PostgreSQL full | 2188 passed, 1 known warning (Starlette) | round 2 tests changed after P2 (read-only search: only the two test modules changed, no shared helper) |
| FC5, L5, Y5 | format check (after `ruff format src tests`), lint, `mypy` | passed | round 3 notes: a test comment and the migration docstring |
| M6 | migration-only check | passed | the migration docstring changed |
| T5 | targeted: new and companion modules | 13 passed | last targeted run after the last change (text only: a comment and a docstring, so no further full run) |

Corrections per cause: A (test set-up) 1 of 2.

## Review round 1 (fresh read-only subagents, during P1; told to write no file and run no test, script or database command)

Independent: 0 blockers, 3 should-fix, 5 notes. Security: 0 blockers, 1 should-fix, 3 notes. All
are tests or text, plus one fail-closed code change (security N1).

- Should-fix SF1 (independent, text): "every correction kind that pays a Credit Refund brings back
  at least as much" is not the mechanism for a `REFUND_RETURN` (its own return comes first in the
  draw) or a held-value Refund (its named return comes second); the right wording: the draw covers
  what the correction brought back, its own return, then its named return, before any other
  return's money, and every Credit Refund writer caps its Refund by one of those three (or pays it
  from a Credit it creates). Fixed in the migration docstring, docs/004, docs/010, the plan and the
  new module's docstring.
- Should-fix SF2 (independent, tests): only the `REFUND` kind of the three newly allowed other-Lease
  corrections had a real-path test. Added with the reviewer's set-ups S1 and S2 (below).
- Should-fix SF3 (independent, one assertion and plan text): a real path to another Settlement's
  Refund exists through the follow function (set-up R1 below), inside the renamed test's own
  set-up. Added: X0's source has one open `CHANGED_APPLICATION` part (the other Lease's 1,500
  payment, part 1,500) and X0's reversal is refused (`CHANGED`). The plan's 2b-2 entry now says 2b-2
  is that follow step, with the warning that relaxing the follow function alone would charge the
  Refund part on this Settlement's Lease (`swept_paid`), against owner answer 4.
- Should-fix S1 (security, test): the placed function's `OTHER_SETTLEMENT` naming had no
  behavioural test. Added with the reviewer's method (an owner transaction that is always rolled
  back), using a mixed take: see "Security set-up" below.
- Note N1 (security, code, taken): the CASE is an allow-list (`placed.kind<>'CREDIT_APPLICATION'`),
  so any record of another Settlement's correction other than a Credit application stays open
  (a fail-closed check; the same result today).
- Notes N2 (both, taken): the renamed test asserts `source["recoveries"] == []`,
  `result["recoveries"] == []` and that the other Lease's 200 Refund keeps its net.
- Note N3 (security, text, taken): a take by another Settlement's correction that also reversed the
  Credit or a return is still refused, now with the `CREDIT_REVERSAL` message or the general one
  (docs/004, docs/010).
- Note N3 (independent, optional test): a hand-built mixed source is covered by the security set-up
  test (a real source with the mixed shape, refused whole).
- Note N4 (independent): this record created before the commit, with the search result above.
- Notes N1 and N5 (independent): the SQL patches and the other changes checked and found right
  (anchors, column names, the primary-key join, one-Settlement and Deposit cases unchanged, the
  sum check, the renamed test's set-up unchanged, revision strings only, traceability entries 1 to
  3,089 identical, ids unique, no real-clock values).
- Q2 (independent): another Settlement's bounced Payment cannot take the return's money (the
  return's correction makes the first Settlement rely on the Credit, so the other Settlement's
  `RETURNED_PAYMENT` is refused; a reversal before the return is placed before its entry). That
  part of 2b-2 is not built.

Reviewer's set-up R1 (independent, round 1; for 10e-3d-2d-2b-2):
1. `two_lease_case(url, monkeypatch, returned=1_500, credit_paid=1_500)`: X0 (first Lease) brings
   back 1,500; the second Lease's C1 pays its charge line L1 1,500 from the Credit.
2. `confirm_refund(second, record_refund(second, refund_command(second, L1, 600)))`: C2 reverses
   C1's 1,500 application, writes 900 again and refunds 600 from the Credit to the Customer; the
   Credit ends at 0.
3. In X0's source, C1's application was reversed by C2 of another Settlement: the follow function
   stops (`CHANGED_APPLICATION` 1,500), and recording X0's reversal is refused (`CHANGED`).
4. Under the same-Settlement rule X0's money sits as 600 on C2's Refund and 900 on the 900 written
   again; 2b-2 should give a 600 charge-back to the Customer on the second Lease, the 900 reversed
   through the companion (L1 owes 900), the Credit at 0 and the first Lease's Refund's net 2,000
   again. With 1,500 instead of 600 the whole 1,500 sits on C2's Refund. The renamed test's own
   set-up has it too (X0's 1,500 maps to C2's 200 Refund, its 300 payment, then 1,000 of the 1,300
   written again).

Reviewer's set-up S1 (independent, round 1; built as
`test_a_take_by_another_lease_s_refund_return_with_a_new_refund_is_undone`):
1. `two_lease_case(…, returned=1_500, credit_paid=1_500)`.
2. C2 = `refund_command(second, L1, 400)`: reverses 1,500, writes 1,100 again, refunds 400 from the
   Credit; the Credit is 0.
3. `E = return_only(first, refund, 300)`; the Credit is 300.
4. `l2 = charge(url, second, 300)`.
5. `confirm(second, record(second, return_command(second, C2_refund, 400,
   SettlementCreditStep(credit, LINE, l2, 300))))`: a new Refund of 400; the Credit ends at 0; the
   walk gives its own take of 400 at offset 0 and E's 300 at offset 400 over the Refund [0,400) and
   the l2 payment [400,700).
6. E's source: `swept == [(CREDIT_APPLICATION, l2 payment, 300, 300)]`, `swept_open == []`, one
   companion; E's reversal: l2 owes 300, the Credit is 0, the new Refund keeps 400, the first
   Lease's Refund's net is 500.

Reviewer's set-up S2 (independent, round 1; built as
`test_a_take_by_another_lease_s_held_value_refund_is_undone`): steps 1–2 of S1;
`N = return_only(second, C2_refund, 400)` (Credit 400); `E = return_only(first, refund, 300)`
(Credit 700); `l2 = charge(url, second, 300)`; `confirm_held(second, record_held(second,
held_command(second, N, SettlementCreditStep(credit, LINE, l2, 300))))` (Refund 400; the walk gives
the named take of 400 at offset 0 and E's 300 at offset 400); the same source and reversal
expectations as S1; N's left value stays 0 from both Settlements.

Security set-up (security round 1, method by the reviewer; built as
`test_a_part_on_another_lease_s_refund_stays_one_open_part_refused_first`): the renamed test's
set-up up to the other Lease's `REFUND` correction C2 (refunds 200, pays a new 300 charge, writes
1,300 again); then, in an owner transaction that is always rolled back, the user triggers of
`app.settlement_correction_effects` are disabled and C2's effect rows that link its Credit
application reversal are deleted, so C2 brought nothing back: its draw starts at 0 and X1's 300
falls on C2's 200 Refund and 100 of its 300 payment. The placed function gives
`('OTHER_SETTLEMENT', C2, 200)` and `('CREDIT_APPLICATION', the 300 payment, 100)`; the source holds
the open part, `swept_usd_cents` 300 and `swept_undone_usd_cents` 100; the refusal function refuses
it with the `OTHER_SETTLEMENT` message (55000). After the rollback every trigger is enabled and
C2's links are as before.

## Review round 2 (fresh read-only subagents, during P2; told to write no file and run no test, script or database command)

Independent: 0 blockers, 1 should-fix (plan text), 6 notes. Security: 0 blockers, 0 should-fix, 4
notes. Both confirmed every round 1 fix as real and correct; the allow-list CASE changes no
one-Settlement, Credit or Deposit result; the hand-made test calls the patched placed function and
tells 138 and 139 apart, always rolls back and opens no second connection under its lock; the
renamed committed test is not weaker beyond owner answer (a) to Q-2026-10-13-103 point 3;
traceability 3,092 to 3,098 entries, one rename (entry 3,090) and six appended, ids unique. Under
the round-3 rule (2026-10-13) the should-fix and the notes, all tests and text, are fixed and round
3 runs without asking.

- Should-fix (independent, plan text): "X1's 300 sits on that correction's newest applications" was
  wrong; X1's 300 sits on the older of its two payments, the 1,300 written again, at the end of the
  newest-first layout. Fixed in the plan.
- Notes taken (independent): docs/004 "the oldest first of the newest-first layout" reworded (the
  committed case named) and "no real path through a take reaches it" softened to "was found" (the
  Refund caps are enforced by the writers); docs/010 "the checks before the reversal are unchanged"
  corrected to "before X1's source"; the plan's as-built line names S1, S2 and the hand-made test;
  this record's run table completed; the renamed test takes its counts before X0's refused attempt;
  S2 checks N's left value 0 after the reversal too.
- Notes taken (security): N1 the renamed test again proves that the refused attempt writes nothing
  (the check HEAD had for the refused reversal; the counts now taken before X0's refused attempt);
  N2 the hand-made test compares every trigger's state before and after instead of assuming
  enabled; N4 a comment that nothing inside its transaction may open another connection.
- Note kept for 2b-2 (security N3): the `OTHER_SETTLEMENT` message still says "waits for sub-slice
  10e-3d-2d-2"; reworded when 2b-2 changes the refusal function (plan).

## Review round 3 (fresh read-only subagents, during P3; told to write no file and run no test, script or database command)

Independent: clean (0 blockers, 0 should-fix, 6 notes). Security: clean (0 blockers, 0 should-fix,
4 notes). Both confirmed every round 2 fix; the changed committed test is not weaker beyond owner
answer (a) to Q-2026-10-13-103 point 3 (its refused attempt still writes nothing); the 15 modules
change only the 27 revision strings; traceability entries 1 to 3,089 untouched, one rename, six
appended, ids unique; least privilege, fail-closed behaviour and the hand-made test's safety
confirmed; no secret in the new texts.

Notes taken (text only; then FC5, L5, Y5, M6 and T5, no further full run):
- The run table completed (T4, U3, M5, P3 and the runs after the notes).
- The hand-made test's comment on its lock reworded (both reviewers): another connection would read
  the committed state, not the hidden links, and a record or confirm would wait on the ALTER's lock.
- docs/010: the renamed test's two added checks and its refused attempt that still writes nothing
  named.
- The plan's pre-code note softened as docs/004 ("no real path through a take was found; the caps
  are enforced by the Refund writers").
- docs/004: one long line rewrapped.
- Security: the migration docstring and docs/004 say that for a Deposit source such a take stays
  refused (unreachable; each record an open part, an uncovered stretch fails the sum check). This
  corrects round 1 note N1's "Deposit cases unchanged" above: the result for a Deposit source is
  still a refusal, now per record instead of one whole part.
- docs/010: the review rounds and runs bullet for 2b-1 added.

Notes kept (optional, for 2b-2): a test that pins the message of a take by another Settlement's
correction that also reversed the Credit or a return (now the `CREDIT_REVERSAL` or general
message); rewording of the `OTHER_SETTLEMENT` message.
