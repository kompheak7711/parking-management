# V1-056 sub-slice 10e-3d-2b-1b — a return's own uses placed by the walk: review record

Sub-slice: 10e-3d-2b-1b (migration `20261206_132`). Base commit: 941f26f (10e-3d-2b-1a). Built
on 2026-10-14. Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-014, DL-032; DB-SETTLE-005; owner answer (a) to
Q-2026-10-13-100 point 1. Design: ops/V1_056_PLAN.md (the "10e-3d-2b pre-code design" bullet,
"The own uses from the walk", and the "10e-3d-2b-1b as built" line).

## Built

- Migration `backend/migrations/versions/20261206_132_settlement_return_reversal_own_parts.py`:
  new internal `app.settlement_returned_value_parts(uuid,text,uuid,uuid,boolean)` (no grants; the
  10e-3d-2a takes body with `walk_swept=p_swept`); `app.settlement_returned_value_takes` replaced
  by a call to it with true (same signature, settings and privileges); exact-text patches of
  `app.settlement_return_reversal_source_state` (CTE `own_walk`; own takes in `swept_state` with
  `own` true; pooled own lists gated off on the walk path; keys `own_parts`, `own_open`; comments)
  and `app.assert_settlement_return_reversal_allowed` (key shapes; totals present on the walk
  path; own parts checked as swept parts; sum, distinct-record and listed-record checks; open
  own parts with the kind messages; pooled-path checks skipped on the walk path).
- New test module `backend/tests/test_settlement_return_reversal_own_parts_migration.py` (four
  tests as first built, seven after the round 1 fixes), last in `scripts/database-test.sh`.
- Changed committed tests (owner standing rule of 2026-10-11; owner answer (a) to Q-100 point 1):
  the 27 head-revision assertions in 15 modules (one replacement of the exact quoted revision,
  27 before and 27 after; the successor module's own `REVISION` constant unchanged);
  `test_settlement_return_reversal_swept_migration.py::test_own_corrections_that_also_took_another_return_s_money_wait`
  renamed `..._are_undone_per_correction` and turned into the allowed case (set-up unchanged);
  five hand-built sources gained `"own_parts": None, "own_open": None` (two in
  `test_settlement_return_reversal_migration.py`, one in `test_settlement_returned_value_left_migration.py`,
  two in `test_settlement_return_reversal_swept_migration.py`).
- `ops/traceability.json` (Edit tool only): one entry changed (the renamed test, entry 3,034 of
  `entries`, well after the protected first 1,598), seven appended. docs/004 (DB-SETTLE-005 paragraph), docs/010, the plan (as-built line,
  slice 12 items).

## Runs

Static checks, each in its own call, formatter on the changed files first. Outputs in
`~/Development/prm-run-logs/` (`V1-056-slice-10e-3d-2b-1b-*`); every targeted and full run under
`caffeinate -dims`.

| Run | Kind | Result | Cause |
|---|---|---|---|
| F1 | `ruff format` on the changed files | reformatted the new test module | cause A (format), correction 1 of 2 |
| L1 | `ruff check src tests` | 2 RUF005 (tuple concatenation), one in the new module, one in the changed committed test | cause B (lint), correction 1 of 2 |
| — | formatter, `ruff format --check src tests`, the same on the migration, `ruff check src tests`, the same on the migration, `mypy` | clean | after the L1 fix |
| M1 | migration-only check | passed | first |
| T1 | PostgreSQL targeted: held-Deposit limit, held-value Refund, pet pay-back, real-path, return reversal, returned Payment after closure, returned value left, swept, successor, new module | 85 passed | first |
| U1 | backend unit, full | 1 failed (`test_traceability_manifest_covers_executable_tests`: the renamed test and the new tests had no traceability entries yet), 3801 passed | cause C (traceability), correction 1 of 2 |
| U2 | backend unit, full | 3802 passed, 1977 skipped, 1 known warning | after the C fix |
| M2 | migration-only check | passed | before P1 |
| P1 | PostgreSQL full | 2141 passed, 2 known warnings (Starlette; the intermittent pydantic `UnsupportedFieldAttributeWarning`, slice 12 item) | first |

Read-only search before T1 and P1: the changed functions are read only by the return reversal
path (record, confirm and the lock function's `RETURN_REVERSAL` branch); the modules that reverse
returns or read their counts are the ten of T1; the other `record_reversal` matches are other
features (forfeiture and receipt reversals).

## Review round 1 (fresh read-only subagents, during P1; told to write no file and run nothing)

Security: 0 blockers, 4 should-fix, notes.
- SF1: on the walk path the `NOT v_walk` skip made the totals check never refuse, so a walk-path
  source with `"uses": {}` passed. Fixed: on the walk path the three totals must be numbers
  (a fail-closed check that adds a refusal); tested.
- SF2 (also independent SF2): the duplicate-record case was refused by the sum check first.
  Fixed with the reviewer's set-up (the earlier amount 1,200, so only the duplicate check refuses).
- SF3: real-path test of an own Refund returned later on the walk path. Added with the reviewer's
  set-up: `test_an_own_refund_returned_later_waits_for_that_return_s_reversal`.
- SF4: real-path test of an own payment a `REFUND` correction changed. Added with the reviewer's
  set-up: `test_an_own_payment_a_refund_correction_changed_waits`.
- Notes: the walk-path message for an own Refund part above its net is the generic "no longer
  available" (slice 12); a missing earlier amount made the new sum comparison unknown (fixed:
  `COALESCE(...,true)`); about seven walks per source (slice 12); no source check on listed
  records inside the refusal function, pre-existing (slice 12); the least-privilege test checked
  only four roles (fixed: the new function's rights list and owner equal the takes').

Independent: 0 blockers, 2 should-fix, 5 notes.
- SF1: the own-parts terms in the "applied again" count check were not proven (the fail-closed
  base source already met the pooled condition). Fixed with the reviewer's real-path set-up
  (`test_an_own_part_on_a_put_back_with_other_money_is_applied_again`) and its cheaper passing
  case (pooled totals of 0) in the fail-closed test.
- SF2: as security SF2.
- Notes: N1 the pooled-path reading confirmed; the third walk-path condition is not reachable
  today (recorded as defensive in the migration, docs/004 and the plan); N2 a correct, untested
  result change (two own payers, one with source money no return brought back: now placed per
  correction; in docs/010); N3 RETURN_REVERSAL as a taker and double listing: not reachable; N4
  wording ("an own application reversed since") and stale comments (fixed); N5 committed tests
  compared with HEAD: only the renamed test changed its result, the hand-built sources only gained
  the two null keys, 27 revision lines.

Reviewer set-ups used (owner rule of 2026-10-13):
- Independent SF1 (`test_an_own_part_on_a_put_back_with_other_money_is_applied_again`):
  `refunded_case`; X1 = `return_only(case, refund, 300)`; X2 = `return_only(case, refund, 300)`;
  `unpaid_charge`; E = `return_only(case, refund, 900, SettlementCreditStep(credit, LINE,
  charge_line, 1_500))`; reverse X1 only (its 1,200 put-back holds E's 900 and X2's 300); E's
  reversal: own part (put-back, 1,200, 900), one `reapply` entry of 300, `uses` all 0; the
  put-back reversed whole, 300 applied again; Credit 0, charge 1,200 owed; the first payment's
  successor is the new 300.
- Security SF3 (`test_an_own_refund_returned_later_waits_for_that_return_s_reversal`): the steps of
  `test_own_corrections_that_also_took_another_return_s_money_are_undone_per_correction`, then
  `later = return_only(case, paid["id"], 50)`; E's reversal refused with "The returned value is
  no longer available; undo its other use first", COUNTS and DRAFTS unchanged; reverse `later`
  first, then E's reversal goes through.
- Security SF4 (`test_an_own_payment_a_refund_correction_changed_waits`): `refunded_case`;
  E = `return_only(case, refund, 1_500, SettlementCreditStep(credit, LINE, charge_line, 1_500))`;
  `confirm_refund(case, record_refund(case, refund_correction(case, charge_invoice, charge_line,
  300)))`; E's reversal refused with the 10e-3d-2b message, COUNTS and DRAFTS unchanged; the
  source's `own_open` holds one CHANGED_APPLICATION entry.

Runs after the round 1 fixes (static checks each in its own call, formatter first):

| Run | Kind | Result | Cause |
|---|---|---|---|
| F2 | `ruff format` on the changed files | reformatted the new test module | cause A (format), correction 2 of 2 (allowance used) |
| — | `ruff format --check src tests`, the same on the migration, `ruff check src tests`, the same on the migration, `mypy` | clean | round 1 fixes |
| M3 | migration-only check | passed | round 1 fixes |
| T2 | PostgreSQL targeted: the same ten modules | 88 passed | round 1 fixes |
| U3 | backend unit, full | 3802 passed, 1980 skipped, 1 known warning | round 1 fixes |
| M4 | migration-only check | passed | before P2 |
| P2 | PostgreSQL full | 2144 passed, 3 known warnings (Starlette; the intermittent pydantic `UnsupportedFieldAttributeWarning` twice) | round 1 fixes |

## Review round 2 (fresh read-only subagents, during P2; told to write no file and run nothing)

Security: 0 blockers, 0 should-fix, 4 notes: (1) a walk-path real-path test of an own Refund
partly returned while E's part stays within its net (the top-level "has its own return" check;
slice 12, set-up below); (2) the NULL-safe sum comparison was not tested on its own (fixed: an
unknown earlier amount); (3) the walk-path list checks read `own_parts` behind `v_walk AND`,
relying on evaluation order (fixed: nested `IF v_walk THEN IF ... END IF; END IF;`); (4) cost,
about eight walks per walk-path source (already a slice 12 item).

Independent: 0 blockers, 1 should-fix, 7 notes. Under the owner's round-3 rule of 2026-10-13 (a
should-fix that is only a test), fixed and round 3 runs without asking.
- SF1: the "each part above 0" term for own parts was not the check that refused its case.
  Fixed with the reviewer's set-up (earlier amount 800, the zero Refund part listed with a zero
  recovery; only that check refuses).
- Notes: N1 the result change of round 1 note N2 is not reachable with today's Credit fixture
  (slice 12); N2 the `shared_own` comment did not name that second case (fixed); N3 the
  REFUND-correction test now also asserts `swept_open` empty (stricter, own new test); N4 the
  `refunded_usd_cents` term and the `COALESCE` were not tested on their own (fixed: each total
  and an unknown earlier amount); N5 this record said the renamed traceability entry was "after
  entry 1,598" (fixed: entry 3,034); N6 the plan line left out the "no record is a part twice"
  check (fixed); N7 the rename of a committed test goes a little past "the affected case only":
  its set-up is unchanged and the rename is recorded in docs/010, the plan and traceability (named
  in the owner report).
- Process slip reported by the reviewer: while comparing the revision lines it wrote three scratch
  files outside the repo (`/tmp/rev_diff_review.txt`, `/tmp/a_rev.txt`, `/tmp/b_rev.txt`).
  Nothing in the repo was touched, no Docker, no test. The files are left for the owner to decide.

Reviewer set-ups from round 2 (owner rule of 2026-10-13):
- Independent SF1 (in `test_the_own_parts_fail_closed`): the walk-path base source with
  `earlier.amount_usd_cents` 800, `own_parts` [the 800 application part, the Refund part with
  `part_usd_cents` 0] and `recoveries` [the recovery with `amount_usd_cents` 0]: INCOMPLETE.
- Security note 1 (slice 12, not built): E0 = `return_only(case, refund, 300)`; E =
  `return_only(case, refund, 1_700, SettlementCreditStep(credit, LINE, first_line, 1_500))`;
  `third_party_payment(..., second_line, 1_300)`; a held-value Refund H naming E whose step pays
  200 of `second_line` and which refunds 300 (H's draw: E's 200, then E0's 300; E's 200 on the
  Refund); `later = return_only(case, H_refund, 50)` (net 250, still at least the 200 part); E's
  reversal refused with "A Refund paid from the returned value has its own return; reverse that
  return first", COUNTS and DRAFTS unchanged; after `reverse(case, later)` E's reversal reverses
  the 1,500 payment and recovers 200 from the 300 Refund, and H's 200 payment stays.

Runs after the round 2 fixes (static checks each in its own call; `ruff format --diff` first,
read-only, because format cause A had used both corrections; then the formatter: no change):

| Run | Kind | Result | Cause |
|---|---|---|---|
| — | `ruff format --diff`, `ruff format` on the changed files, `ruff format --check src tests`, the same on the migration, `ruff check src tests`, the same on the migration, `mypy` | clean, no change | round 2 fixes |
| M5 | migration-only check | passed | round 2 fixes |
| T3 | PostgreSQL targeted: the same ten modules | 88 passed | round 2 fixes |
| U4 | backend unit, full | 3802 passed, 1980 skipped, 1 known warning | before round 3 |
| M6 | migration-only check | passed | before P3 |
| P3 | PostgreSQL full | 2144 passed, 1 known warning (Starlette) | before round 3 |

## Review round 3 (fresh read-only subagents, after P3; told to write no file anywhere)

Independent: 0 blockers, 0 should-fix, 5 notes. It verified every round 2 fix (the nested IF's
parentheses, each isolated fail-closed case traced), the walk-path condition and the own takes,
compared each changed committed test with HEAD (27 revision-only lines in 15 modules; the five
hand-built sources gained only the two null keys; the renamed test's set-up unchanged, only the
`holding` binding split out), and found the docs, plan, traceability and this record consistent.
Notes (slice 12): (1) `test_an_own_refund_returned_later_waits_for_that_return_s_reversal` proves
the open CHANGED_REFUND part only through the shared message; a direct assertion on the source
(after `later`, `own_open` = [CHANGED_REFUND, REFUND, the Refund, 200] and `own_parts` = E's 1,500
application part only) is cheap; (2) a passing hand-built case with two own reapply entries
(earlier 1,100; another own part {second application 600, part 100} listed at 600 from the same
Credit with a 500 reapply entry; passes as is and with pooled totals of 0) would prove that
clause has no over-refusal; (3) the migration docstring and the fail-closed test's traceability
note leave out the walk-path totals check (the traceability note is corrected; the docstring is
left, because a migration change would need another full run); (4) the 10e-3d-2b design text in
the plan says H's 300 application is placed per correction, while as built it is E0's money and
stays (history kept; the as-built line and docs/010 are right); (5) the composed reference file
outside the repo lacks migration 130's DECLARE line (reference only).

Security: 0 blockers, 0 should-fix. It verified the nested IF (`v_walk` never NULL; the inner
condition never NULL), that every other read of the own keys goes through the CASE guards, the
comment-only source change, deny-by-default (the PUBLIC revoke also covers the other roles; the
default grant is never visible outside the one migration transaction), scoping and exact amounts,
integer cents, no dynamic SQL, fixed messages, no update or delete. Notes: the totals check's
`v_walk AND` is harmless (plain `jsonb_typeof` comparisons); two parts following to one later
application would be refused as incomplete (not reachable); cost unchanged since round 2; the
round 2 reviewer's scratch files in `/tmp` still wait for the owner.

Round 3 is clean (independent and security).
