# V1-056 sub-slice 10e-3c — only the mistaken amount comes back: review record

Sub-slice: 10e-3c (migration `20261202_128`). Base commit: ca73340. Built in one session on
2026-10-13; this record is committed with it (see git log). Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-016, DL-032; DB-SETTLE-005; owner answer (a) to
Q-2026-10-12-96. Design: ops/V1_056_PLAN.md (the "10e-3c" bullets: pre-code design and as built).

The same commit records the owner answers of 2026-10-13 to Q-2026-10-13-98 and the 10e-4 report
(docs/010, the questions file, the plan's 10h entry and slice 12 list).

## Built

- Migration `backend/migrations/versions/20261202_128_settlement_return_reversal_reapply.py`:
  - new internal `app.settlement_return_reversal_reapply_steps(jsonb)` (no grant): the one-step
    plan of the part applied again;
  - exact-text patches of `app.settlement_return_reversal_source_state` (the newest applications
    up to the rest, and `reapply`), `app.assert_settlement_return_reversal_allowed` (the Q-96
    refusal removed; fail-closed checks of the part; exactly the returned amount comes back when
    the uses are more than it; the source-value check less the part),
    `app.record_settlement_return_reversal_draft` (stores `plan`),
    `app.confirm_settlement_return_reversal` (plan and payload-key checks; the part applied again
    after the return reversal; audit dated at the latest record; `reapplied` in the audit) and
    `app.settlement_return_reversal_result` (`reapplied`).
- `backend/src/property_rental/settlement_correction.py`: docstring of the command only.
- Tests in `backend/tests/test_settlement_return_reversal_migration.py` (no new module).
- Changed committed tests (owner standing rules of 2026-10-11 and 2026-10-13): the 27
  head-revision assertions in 15 modules (`20261201_127` to `20261202_128`); under owner answer (a)
  to Q-96: `test_returned_money_that_also_paid_debt_beyond_its_refunds_waits_for_the_owner`
  renamed `test_returned_money_that_also_paid_debt_is_reversed_and_its_rest_applied_again` (the
  allowed case), `test_the_shared_path_refusals_fail_closed` (built source gains `"reapply": []`;
  the Q-96 branch passes); made stricter at the independent reviewer's request (round 1):
  `test_a_mistaken_credit_return_is_reversed_and_its_new_refund_is_charged_back`,
  `test_a_mistaken_deposit_return_undoes_only_the_returned_deposit_s_uses`,
  `test_a_reversal_keeps_the_applications_when_its_refund_paid_out_the_returned_money` (nothing
  applied again). No fixture changed.
- `ops/traceability.json`: one entry renamed, five notes changed, four entries appended (Edit
  tool only).
- docs/004 (DB-SETTLE-005 return reversal paragraph), docs/010, the plan, ops/NOW.md.

## Runs

Static checks, each in its own call: `ruff check src tests`, `ruff format --check src tests`,
the same two on the new migration file, and `mypy`.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| C1 | throwaway catalog read (upgrade to 127, function definitions dumped to the job scratch directory; not a test run) | 126 upgrades | pre-code read | not saved |
| M1 | migration-only check | passed | first | not saved |
| T1 | PostgreSQL targeted: return reversal module, 10e-4 module (imports it) | 25 passed | first | `V1-056-slice-10e-3c-targeted-test-run.txt` |
| U1 | backend unit, full (caffeinate) | 3802 passed, 1946 skipped, 1 warning (known) | first full unit run | `-unit-test-run.txt` (excerpt) |
| M2 | migration-only check | passed | before P1 | not saved |
| P1 | PostgreSQL full (caffeinate) | 2110 passed, 2 warnings (known kinds) | first full run | `-full-test-run.txt` |
| L1 | `ruff check src tests` | 1 line too long | cause A (lint, my test), correction 1 of 2 | not saved |
| M3 | migration-only check | failed: syntax error (a CASE inside a PL/pgSQL IF condition, not in parentheses) | cause B (migration, my round-1 change), correction 1 of 2 | not saved |
| M3' | migration-only check, same code | failed, same error | rerun only to read the error text (M3 printed only its last lines); no change in between | not saved |
| M4 | migration-only check | passed | cause B fixed | not saved |
| T2 | PostgreSQL targeted: the same two modules | 26 passed | round 1 fixes | `-targeted-test-run-2.txt` |
| U2 | backend unit, full (caffeinate) | 3802 passed, 1947 skipped, 1 warning (known) | round 1 fixes | `-unit-test-run-2.txt` (excerpt) |
| M5 | migration-only check | passed | before P2 | not saved |
| P2 | PostgreSQL full (caffeinate) | 2111 passed, 2 warnings (known kinds) | round 1 fixes | `-full-test-run-2.txt` |
| M6 | migration-only check | passed | round 2 fixes | not saved |
| T3 | PostgreSQL targeted: the same two modules (caffeinate -i) | 18 passed, 8 failed | outside the sub-slice: every failure is `Signature evidence is invalid` in the shared Lease fixtures (the Mac's clock ahead of the Docker VM's; cause C of 10c-2a-3); STOPPED, Q-2026-10-13-99 | `-targeted-test-run-3.txt` |
| K1 | clock check (owner answer (a) to Q-99, step 1): `docker run --rm --pull=never --entrypoint date postgres:17.6 +%s%6N` between two Mac readings, three times; not a test run | in step: the Docker time fell inside the Mac's window each time | before the T3 rerun | not saved |
| T4 | PostgreSQL targeted: the same two modules, the owner-approved rerun of T3 (caffeinate -dims) | 26 passed | Q-99 (a) | `-targeted-test-run-4.txt` |
| U3 | backend unit, full (caffeinate -dims) | 3802 passed, 1947 skipped, 1 warning (known) | before round 3 | `-unit-test-run-3.txt` (excerpt) |
| M7 | migration-only check | passed | before P3 | `~/Development/prm-run-logs/V1-056-slice-10e-3c-migration-check-7.txt` |
| P3 | PostgreSQL full (caffeinate -dims) | 2111 passed, 1 warning (known kind) | before round 3 | `-full-test-run-3.txt` |

Read-only search of every backend test before T1 and before P1: the patched functions are used
only by `test_settlement_return_reversal_migration.py`; `test_returned_payment_after_closure_migration.py`
imports its `PAYBACK_REVISION` and `app_catalog`; the other files that name "return reversal"
test the ordinary Refund return reversal (unchanged) or the service unit tests (no change). No
test compares the whole return reversal source or result outside the module.

## Review round 1 (fresh read-only subagents, during P1)

Security: 0 blockers, 1 should-fix, 6 notes. Independent: 0 blockers, 3 should-fix, 11 notes; it
compared the changed committed tests with HEAD (the renamed Q-96 test, the shared-path test, the
27 head-revision lines) and found nothing else weaker.

Fixed: security SF1 (crafted drafts with another plan, no step or a plan overlay: refused, P0002,
stay pending); independent SF1 (exact boundary), SF2 (earlier cases apply nothing again), SF3
(Deposit plan and dates); security N1 (exact payload keys), N2 with independent N1 (source and
obligation of the part; exactly the returned amount when the uses are more than it); independent
N2 (evaluation order), N3 (audit date), N7 (docstring), N8 (computed amounts), N10 (comment), N11
(numbering in the as-built text). Answered in writing (docs/004, docs/010, plan): security N3
(lock order), N4 (old drafts), N5 (Deposit dating), N6 and independent N4, N5 (known limits; the
Rent-line branch untested), independent N6 (10e-3d note), N9 (one source per Refund).

## Review round 2 (fresh read-only subagents, during P2)

Security: 0 blockers, 0 should-fix, 2 notes. Independent: 0 blockers, 1 should-fix, 8 notes; it
compared every changed committed test with HEAD again (27 head-revision lines, the renamed test,
the shared-path test, the three stricter tests: only additions) and found nothing weaker.

Fixed: independent SF1 (the audit event's date and `reapplied` tested in both real-path tests);
security N2 (the confirm checks the stored Lease; a crafted draft with another Lease is refused);
security N1 (docs/004 and docs/010 narrowed to what the check compares); independent N1 (Deposit
branches and a Refunds-covered entry on built sources), N5 (upstream IDs of the renamed test's
entry), N6 (service docstring). Slice 12 items: independent N2 with security N1 (tighter ties of the
part; not reachable), N4 (the audit reader cannot read the event's keys; pre-existing). Owner
points: independent N7 (run M3' above), N8 (the Rent-line limit, as in docs/004).

## Owner answer to Q-2026-10-13-99 and the reruns

Option (a) in steps (docs/010, questions file). Clock check K1 with the database image already on
the Mac (no pull): in step. T4 (the one rerun of T3) passed; U3, M7, the read-only search (the
same three test files as before P1 and P2) and P3 passed, all under `caffeinate -dims`. M3' accepted
by the owner; the CASE lesson added to the run rules; the Deposit numbering accepted; the Rent-line
refusal test on the slice 12 list (no existing real-path fixture reaches it).

## Review round 3 (owner standing rule; U3 and P3 ran on the final code before it)

Independent: 0 blockers, 0 should-fix, 5 notes. It compared each changed committed test with HEAD
(the 27 head-revision lines in 15 modules, revision only; the renamed Q-96 test and
`test_the_shared_path_refusals_fail_closed`, only the cases owner answer (a) covers; the three
stricter tests, additions only) and found nothing weaker. Security: 0 blockers, 0 should-fix, 2
notes; the saved outputs hold no secret.

Fixed as text after round 3 (docstrings, docs and records only; no SQL body or test code changed):
the owner's Q-96 example stated in dollars with the 1/100 test scale (docs/010, the test
docstring); the migration module docstring narrowed to what the check compares; the questions
file names the 10e-4 confirmation docs/010 states; this record and ops/NOW.md. Slice 12 items:
real-path tests of a part on a Late-payment Charge and of the Deposit tie-break order; the assert's
SQL comment wording; optional conflict mapping of the Credit writer's 23514 (security note 2). A
round 3 reviewer left a scratch copy of the migration text in `/tmp` (outside the repo); it was
removed. Final static checks after the last text change, each in its own call, are listed in the
commit report.
