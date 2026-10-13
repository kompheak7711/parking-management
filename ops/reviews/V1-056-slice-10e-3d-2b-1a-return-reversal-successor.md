# V1-056 sub-slice 10e-3d-2b-1a — a return's money on a payment a later return reversal changed: review record

Sub-slice: 10e-3d-2b-1a (migration `20261205_131`). Base commit: eb5c4a1 (the 10e-3e and
10e-3d-2b designs). Built on 2026-10-13. Committed in the 10e-3d-2b-1a checkpoint commit after a
clean review round 3 (its hash is in git log; this record is part of that commit). Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-014, DL-032; DB-SETTLE-005; owner answer (a) to
Q-2026-10-13-100 point 1. Design: ops/V1_056_PLAN.md (the "10e-3d-2b pre-code design" bullet and
the "10e-3d-2b-1a as built" line).

## Built

- Migration `backend/migrations/versions/20261205_131_settlement_return_reversal_successor.py`:
  new internal `app.settlement_returned_value_successor(text,uuid)` (no grants); exact-text patch
  of `app.settlement_return_reversal_source_state` (one comment and the `swept_state` CTE: an
  application part follows to its successor, with the successor's correction, id and amount, and
  stays open when there is none or the part is more than it).
- New test module `backend/tests/test_settlement_return_reversal_successor_migration.py` (four
  tests as first built; six after the round 1 and round 2 fixes), last in `scripts/database-test.sh`.
- Changed committed tests (owner standing rule of 2026-10-11; owner answer (a) to Q-100 point 1):
  the 27 head-revision assertions in 15 modules (one `sed` of the exact quoted revision, 27 before
  and 27 after); `test_settlement_returned_value_left_migration.py::test_a_part_applied_again_counts_against_the_return_whose_money_it_is`
  (the refused reversal is now confirmed and asserted); in
  `test_settlement_return_reversal_swept_migration.py::test_an_application_with_other_money_on_each_side_is_applied_again`
  the second reversal is now confirmed and asserted. Both names stay true.
- `ops/traceability.json` (Edit tool only): three notes changed (two committed tests' and, in round 1, the new chain test's), six entries appended. docs/004
  (DB-SETTLE-005 paragraph), docs/010, the plan.

## Runs

Static checks, each in its own call (formatter on the changed files first): `ruff format` (F1:
wrapped one long line in the migration; cause A, format, correction 1 of 2), `ruff format --check
src tests`, the same on the migration, `ruff check src tests`, the same on the migration, `mypy`:
clean. Every targeted and full run used `caffeinate -dims`; outputs in `~/Development/prm-run-logs/`
(`V1-056-slice-10e-3d-2b-1a-*`).

| Run | Kind | Result | Cause |
|---|---|---|---|
| M1 | migration-only check | passed | first |
| T1 | PostgreSQL targeted: held-Deposit limit, held-value Refund, pay-back, real-path, return reversal, returned Payment after closure, returned value left, swept, new module | 79 passed | first |
| U1 | backend unit, full | 3802 passed, 1971 skipped, 1 known warning | first |
| M2 | migration-only check | passed | before P1 |
| P1 | PostgreSQL full | 2135 passed, 2 warnings (the known Starlette one; the known intermittent pydantic `UnsupportedFieldAttributeWarning` in `test_credit_refund_api_migration.py::test_credit_refund_competition_fixture_isolates_unrelated_shared_writer`, slice 12 item) | first |

Read-only search before T1 and P1: the patched source function is read by the return reversal
path only; the same eight modules as in 10e-3d-2a plus the new module; the other matches are other
features (`record_reversal` of forfeiture and receipt reversals) or unit mocks.

## Review round 1 (fresh read-only subagents, during P1; told to write no file and run nothing)

Security: 0 blockers, 0 should-fix, 5 notes: (1) the successor did not check that the reversing
correction belongs to the same Final Settlement (built: also the put-back); (2) the Credit detail
lookup was not exactly one (built); (3) the entry lookup was not exactly one (built); (4) the
successor is also called for non-application takes and returns NULL there (harmless); (5) a
followed part names the put-back's correction; only a Refund part's correction is read by the
recovery scope (docs/004 says so).

Independent: 0 blockers, 1 should-fix, 6 notes.
- SF1: no real-path test was left for the 10e-3d-2b refusal that stays (the two committed real-path
  refusals became allowed; only the hand-built `opened("CHANGED_APPLICATION")` case reached the
  message). Fixed with the reviewer's set-up: `test_a_part_on_a_payment_a_refund_correction_changed_waits`.
- Notes: N1 no test of the new owner join (fixed: the chain test asserts the part's correction);
  N2 on the 10e-3c own path the put-back claim holds for the amount only when the own correction
  also brought money back; the `amount >= part` check fails closed (belongs to 10e-3d-2b-1b); N3 a
  part larger than its successor names the successor in `swept_open` (message only); N4 as security
  note 2; N5 text (fixed: the plan's lock-function wording, this record's runs); N6 traceability
  notes changed only after entry 1,598.

Runs after the round 1 fixes (static checks each in its own call, formatter first: no change,
clean):

| Run | Kind | Result | Cause |
|---|---|---|---|
| M3 | migration-only check | passed | round 1 fixes |
| T2 | PostgreSQL targeted: the same nine modules | 80 passed | round 1 fixes |
| U2 | backend unit, full | 3802 passed, 1972 skipped, 1 known warning | round 1 fixes |
| M4 | migration-only check | passed | before P2 |
| P2 | PostgreSQL full | 2136 passed, 1 known warning | round 1 fixes |

## Review round 2 (fresh read-only subagents, during P2; told to write no file and run nothing)

Security: 0 blockers, 0 should-fix, 4 notes: the owner join could also be limited by the record
kind (safe: the link columns are unique); the put-back claim rests on the amount check (round 1
N2); a failing assertion could show the throwaway database URL (the suite-wide pattern, slice 12
item); the least-privilege test could read `proacl` directly.

Independent: 0 blockers, 1 should-fix, 4 notes. Under the owner's round-3 rule of 2026-10-13 (a
should-fix that is only a test, text or a fail-closed refusal), fixed and round 3 runs without
asking.
- SF1: the n-th-entry mapping was proven only for the first put-back. Fixed with the reviewer's
  set-up: `test_a_part_follows_to_the_second_put_back_of_a_reversal`.
- Notes: N1 the test counts in this record and the plan (fixed: six tests, six entries appended);
  N2 the same-Settlement check needs a second look with sub-slice 10e-3d-2d (recorded in docs/010);
  N3 the put-back claim's qualifier (fixed: docs/004 known limit); N4 optional, stricter: the
  converted left-value test could end with `assert_reconciled` (not done: its module does not
  import it and HEAD had none; nothing weaker).

Runs after the round 2 fixes (static checks each in its own call, formatter first: no change,
clean; the migration did not change):

| Run | Kind | Result | Cause |
|---|---|---|---|
| M5 | migration-only check | passed | round 2 fixes |
| T3 | PostgreSQL targeted: the new module (the only changed test file) | 6 passed | round 2 fixes |
| U3 | backend unit, full | 3802 passed, 1973 skipped, 1 known warning | before round 3 |
| M6 | migration-only check | passed | before P3 |
| P3 | PostgreSQL full | 1 failed, 2136 passed: `test_final_settlement_draft_migration.py::test_a_settlement_draft_records_the_dl032_steps_and_changes_nothing`, `Signature evidence is invalid` in `app.record_lease_signature` (a Lease fixture; the host clock cause of 10c-2a-3, outside the sub-slice) | before round 3 |
| K1 | clock check (run rule): `docker run --rm --pull=never --entrypoint date postgres:17.6 +%s%6N` between two Mac readings, three times; not a test run | in step each time (Docker 0.11 to 0.26 s after the first Mac reading, before the second) | after P3 |
| M7 | migration-only check | passed | before P4 |
| P4 | PostgreSQL full, the one allowed rerun | 2137 passed, 3 warnings (the known Starlette one; the known intermittent pydantic `UnsupportedFieldAttributeWarning` in the two `test_credit_refund_api_migration.py` competition tests, slice 12 item) | rerun of P3 |

## Review round 3 (after P4)

Independent (fresh read-only subagent; told to write no file and run nothing): 0 blockers, 0
should-fix, 3 notes. It traced the new test to the cent (a wrong n-th mapping would fail the line
and amount checks and be refused, so the test proves the mapping beyond the first entry), found
the successor and the patch correct, compared each changed committed test with HEAD (27
revision-only assertions; the two converted refusals keep everything before them; nothing weaker;
owner answer (a) to Q-100 point 1 covers both), and found the docs and runs consistent. Notes: N1
the n-th mapping is proven on the real path for the Credit form only (a Deposit put-back at
position 2 or later, and a Deposit chain through two put-backs, share the same ranking and loop;
candidates for 10e-3d-2b-1b); N2 only two committed traceability notes changed (the third edit was
inside an entry this sub-slice appended); N3 the pooled own-path limit is correctly scoped.

Security: the auto-mode checker blocked the fresh read-only security reviewer twice: first
"Auto-Mode Bypass" (STOPPED, Q-2026-10-13-108), then, at the one start the owner allowed,
"Data Exfiltration". Neither was repeated or worked around. The owner then told me to do the round
3 security review in the main session, read-only, on the uncommitted work (`git diff HEAD`, plus
the two untracked files `git diff HEAD` does not show: the migration and the new test module), with
the checklist of rounds 1 and 2, and to check the run outputs only with the standard secret scan.

Round 3 security (main session, read-only): 0 blockers, 0 should-fix, 3 notes.
- Deny-by-default: the successor is SECURITY DEFINER with `search_path=pg_catalog`, names every
  table with `app.`, and is revoked from PUBLIC and the three application roles (no grant); the
  source function is replaced from its own `pg_get_functiondef` text with CREATE OR REPLACE, so its
  owner, ACL and settings stay (the forward-only test compares them).
- No SQL injection or dynamic SQL: no EXECUTE in either function; the migration binds the signature
  as a parameter and its REVOKE text uses constants.
- No secrets or customer data: the successor returns only a uuid or NULL and raises nothing; the
  new test module and the migration have no `print`; the standard secret scan of `git diff HEAD`,
  the two untracked files and every saved run output of this sub-slice finds nothing (the only
  matches in the run outputs are a migration name, "password-credential storage", and a test file
  name, `test_password_security`).
- No following to another Customer, Settlement, source or obligation: each step requires a
  reversal linked to a `RETURN_REVERSAL` correction of the application's own Final Settlement whose
  stored source (recomputed and compared at its confirm; drafts are append-only) lists the
  application exactly once, and a put-back of the same Final Settlement, Credit or Deposit, target,
  Invoice, line or Late-payment Charge, stage, the entry's exact amount and strictly less than
  before.
- Bounded cost: at most 100 steps, and the amount falls at every step.
- Money stays integer cents (bigint; the JSON amount is compared as text, fail closed); the
  migration only creates and replaces functions and revokes, so no financial record is updated or
  deleted.
- Notes: the owner join could also be limited by the record kind (safe: the link columns are
  unique); the least-privilege test checks PUBLIC and the three application roles, not `proacl`
  directly; a failing database assertion can show the throwaway database URL (the suite-wide
  pattern on the slice 12 list).

Reviewer set-ups used in this sub-slice (owner rule of 2026-10-13: a reviewer's test set-up is
written in the review record):
- Round 1 SF1 (`test_a_part_on_a_payment_a_refund_correction_changed_waits`): `refunded_case`; a
  return-only correction of 300; one `unpaid_charge`; a return-only correction of 1,200 whose step
  lets the returned Credit pay 1,500 of that charge (one application); a Refund correction of 300
  on that line (`refund_correction`, `record_refund`, `confirm_refund`); then the successor of the
  application is none and the first return's reversal is refused with the 10e-3d-2b message,
  nothing written.
- Round 2 SF1 (`test_a_part_follows_to_the_second_put_back_of_a_reversal`): `refunded_case`;
  return-only corrections X0 300, X1 600, X3 300; two `unpaid_charge` lines; a return-only
  correction X2 of 300 whose step lets the Credit pay 600 of the first line and then 900 of the
  second; reverse X1 (put-backs 300 on the first payment and 600 on the second, in that order);
  then X0's 300 follows to the second put-back (600), which X0's reversal reverses whole, putting
  300 back.

Round 3 is clean (independent and security).
