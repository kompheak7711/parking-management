# V1-056 sub-slice 10e-3d-2a — a return's reversal undoes the money another correction paid out: review record

Sub-slice: 10e-3d-2a (migration `20261204_130`). Base commit: bf022f4 (the 10e-3d-2 design).
Built on 2026-10-13. Stopped after review round 2 (three should-fix in total; the standing
round-3 rule allowed at most two): Q-2026-10-13-105. Owner answer (a), a one-time exception; the
round 2 fixes are built and review round 3 is clean (both sections below). Committed in the
10e-3d-2a checkpoint commit (its hash is in git log; this record is part of that commit). Not
pushed.

Rule IDs: BR-SETTLE-008, BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-014, BR-REFUND-015, DL-032;
DB-SETTLE-005, DB-REFUND-002; owner answer (a) to Q-2026-10-13-100 point 1; owner answers (a) to
Q-2026-10-13-103 (recorded this session). Design: ops/V1_056_PLAN.md (the "10e-3d-2 pre-code
design" bullet and the "10e-3d-2a as built" line).

## Built (working tree)

- Migration `backend/migrations/versions/20261204_130_settlement_return_reversal_swept.py`: new
  internal `app.settlement_returned_value_walk` and `app.settlement_returned_value_takes` (no
  grants); whole-body replacement of `app.settlement_returned_value_left` (same results, read from
  the walk); exact-text patches of `app.settlement_return_reversal_source_state` (the swept parts
  in the lists, `swept`, `swept_undone_usd_cents`, `swept_open`, `shared_with_other_returns`, the
  own uses' threshold, the order of the parts applied again), `app.assert_settlement_return_reversal_allowed`,
  `app.settlement_return_reversal_refund` (recovery scope) and
  `app.confirm_settlement_return_reversal` (a loop over the parts applied again).
- New test module `backend/tests/test_settlement_return_reversal_swept_migration.py` (nine tests; eleven after the round 2 fixes),
  last in `scripts/database-test.sh`.
- Changed committed tests (owner standing rule of 2026-10-11; owner answer (a) to Q-100 point 1):
  the 27 head-revision assertions in 15 modules (one `sed` of the exact quoted revision; it also
  touched two intended `20261203_129` references in the new module, restored; counted: 27 in 15);
  in `test_settlement_returned_value_left_migration.py` the Q-97 test renamed
  `test_a_sweep_counts_against_the_earlier_return_and_its_reversal_charges_it_back` (the reversal
  is confirmed and charges 1,000 back), two refusal messages (10e-3d-2b, 10e-3d-2c), the fail-closed
  test's base source (three new keys; four after the round 2 fixes) and its two swept cases (now an incomplete source); in
  `test_settlement_return_reversal_migration.py` two hand-built sources gain the three keys.
- `ops/traceability.json` (Edit tool only): the renamed entry, three notes changed, nine entries
  appended. docs/004 (DB-SETTLE-005 paragraph), docs/010, the plan, the questions file (owner
  answers to Q-103; new Q-2026-10-13-104 and Q-2026-10-13-105).

## Runs

Static checks, each in its own call (formatter on the changed files first): `ruff format`,
`ruff format --check src tests`, the same on the migration, `ruff check src tests`, the same on the
migration, `mypy`. Full outputs in `~/Development/prm-run-logs/` (`V1-056-slice-10e-3d-2a-*`).
Every targeted and full run used `caffeinate -dims`.

| Run | Kind | Result | Cause |
|---|---|---|---|
| C1 | throwaway catalog dump at head 129 (not a test run) | 723 functions | pre-code read; the job's tmp folder also held an older dump of an earlier session (plain file names), so where both exist the hash-suffixed file is head 129; every anchor was then proven by M1 |
| L1 | `ruff check src tests` | 1 line too long (a changed docstring) | cause A (lint, line length), correction 1 of 2 |
| M1 | migration-only check | passed | first |
| T1 | PostgreSQL targeted: held-Deposit limit, held-value Refund, pay-back, real-path, return reversal, returned Payment after closure, returned value left, new module | 69 passed, 1 failed | cause B (a new test's set-up: a return-only Deposit correction takes no DL-032 step), correction 1 of 2 |
| T2 | PostgreSQL targeted: the new module | 6 passed | after cause B |
| U1 | backend unit, full | 3802 passed, 1962 skipped, 1 known warning | first |
| M2 | migration-only check | passed | before P1 |
| P1 | PostgreSQL full | 2126 passed, 1 known warning | first |
| M3 | migration-only check | passed | round 1 fixes |
| T3 | PostgreSQL targeted: the same eight modules | 4 failed | cause C (the new flag inside `uses` changed three committed tests' exact `uses` comparisons; the flag moved to its own key), correction 1 of 2; cause B again (a new Credit-form charge-back test assumed a new Credit Refund pays out the whole Credit; it pays only its own return; test dropped, claim confirmed by review round 2), correction 2 of 2, allowance used up |
| M4 | migration-only check | passed | after causes C and B |
| T4 | PostgreSQL targeted: the same eight modules | 73 passed | after causes C and B |
| U2 | backend unit, full | 3802 passed, 1965 skipped, 1 known warning | round 1 fixes |
| M5 | migration-only check | passed | before P2 |
| P2 | PostgreSQL full | 2129 passed, 1 known warning | round 1 fixes |

Read-only search before T1 and P1 (and again before T3 and P2): the changed functions are read by
the held-value Refund, held-Deposit limit, pay-back, real-path, return reversal and returned value
left modules (the returned-Payment-after-closure module imports the return reversal module); the
other matches (`test_credit_refund_api_migration.py`, `test_deposit_disposition_migration.py`,
`test_refund_service_migration.py`, `test_settlement_correction.py`) are other features or unit
mocks.

## Review round 1 (fresh read-only subagents, during P1; told to write no files; none did)

Independent: 0 blockers, 5 should-fix, notes. Security: 0 blockers, 1 should-fix (the same as
independent 1), 6 notes.

- SF1 (both): the parts applied again were ordered by application uuid, so two Deposit parts of
  different DL-032 stages could fail the Deposit application check (23514) at random. Fixed: DL-032
  stage order, then the original application's time and number.
- SF2: a Credit part applied again on the newer of two reversed applications of an Invoice with
  Rent or Service lines fails the Rent-first proposal at the confirm. Fixed: refused at record and
  confirm with its own message; new Q-2026-10-13-104 (recommendation (b)).
- SF3: the own uses' path (all own corrections' Refunds first) and the walk (per correction) can
  disagree when two or more own corrections paid out and one also took another return's money.
  Fixed: the source flag `shared_with_other_returns` refuses until 10e-3d-2b, which derives the own
  parts from the walk (implementer's placement); real-path test.
- SF4: docs (docs/004 sentence, plan as-built line, docs/010 build entry, stale comments). Fixed.
- SF5: tests the design listed. Added the own uses with a sweep (own part below the returned
  amount); claims recorded for round 2 (two-stage, own plus swept parts applied again, Credit-form
  Refund charge-back).
- Security notes: listed Refunds are not row-locked (safe: the source lock and the Refund
  trigger's checks; recorded in the plan); the swept application arms do not check the
  application's source when nothing is applied again (confirm recomputes the source); no direct
  negative tests of the wider recovery scope; the walk runs several times per source call; the
  draft size cap; the 11c screen must show other recipients' charge-backs.

## Review round 2 (fresh read-only subagents, during P2; told to write no files; none did)

Security: 0 blockers, 0 should-fix. Notes: A, the flag reads false when missing (require it as a
boolean, add it to the hand-built sources); B, the confirm's loop has no ELSE for an unknown
`source_kind` (not reachable; add a raise); round 1 notes 2, 3, 5, 6 still apply; note 4 now five
walks per source call; C, docs did not yet record the round 1 refusals (fixed after the review).

Independent: 0 blockers, 3 should-fix, 7 notes. STOPPED (Q-2026-10-13-105).

- SF1: the two-stage test can be written on the real path (claim 1 refuted): two corrections at
  different stages (a return-only Pet Deposit step at PET_REMAINDER_EXPLICIT and a
  PET_DAMAGE_RECLASSIFICATION at PET_RELATED_FIRST) both take part of E's money.
- SF2: "own uses and a sweep, two parts applied again" is reachable (claim 5a refuted): a
  held-value Refund naming E is the only own correction with records (so the flag stays false) and
  its step also takes another return's money.
- SF3: docs/010 did not record the round 1 changes; docs/004 said three keys (four); this record did
  not exist yet. Text, fixed after the review except as noted in Q-105.
- Claim 5b confirmed: a swept part never falls on a Credit Refund (every Credit Refund writer is
  capped by what its correction released, its own returns and the named left value, and Refunds
  come first in a correction's draw).
- Notes: N1 as security A; N2 the Rent-first check also refuses two applications on the same line
  (the confirm would pass; wrong message) and misses the reverse order (fails at the confirm, safe,
  the known 10e-3c limit); N3 after E's reversal changes an own application of S, S's reversal gets
  the left-value message, not the 10e-3b one (10e-3d-2b scope); N4 a REFUND-variant sweeper's
  re-posted rest counts as its oldest application, so E's part can land on the re-posted rest
  (same Customer and total, a different debt; implementer's reading of "brought back pays out
  first"); N5 two stale comments (cosmetic); N6 Q-104 wording also covers an own application newer
  than a swept one; N7 performance acceptable.

## Owner answer to Q-2026-10-13-105 and the round 2 fixes (fresh session, 2026-10-13)

Option (a), a one-time exception: the two real-path tests, the two fail-closed checks, the runs,
then a round 3 that must be clean, then the commit. Also answered: Q-2026-10-13-104 (b), built as
sub-slice 10e-3e; a new round-3 rule and a rule to try a test on the real path and ask the reviewer
for a set-up in the same round (ops/V1_055_RUN_RULES.md).

- The round 2 reviewer's set-ups were summarised in this record, not kept. Under the new run
  rule, a fresh read-only reviewer (told to write no file and to run nothing) gave the exact
  two-stage set-up (a return-only Credit correction's DL-032 step uses the Pet Deposit at the
  remainder stage while the hold rule keeps the rest; a later pet-damage reclassification uses it
  at the pet-damage stage) and corrected the Credit set-up (third-party payments first, so the
  released Credit leaves no debt open). Both tests passed at their first run (T5).
- Fail-closed: `shared_with_other_returns` must be a boolean (five hand-built sources gain
  `false`, three in committed tests: `test_the_count_and_the_reversal_limit_fail_closed`,
  `test_the_shared_path_refusals_fail_closed`, `test_the_part_applied_again_fails_closed`); the
  confirm's put-back loop has an ELSE that raises 55000 "The return reversal source is
  incomplete" (not reachable; forward-only body check only).
- Text: migration docstring, test docstrings, docs/004, docs/010, the plan, traceability (two new
  entries, one note).

| Run | Kind | Result | Cause |
|---|---|---|---|
| F1 | `ruff format` on the four changed files | reformatted one new test line | cause D (format), correction 1 of 2 |
| F2 | `ruff format --check src tests`; the same on the migration | clean | |
| L2 | `ruff check src tests` | 1 import-order error (I001, the new imports) | cause E (lint, import order), correction 1 of 2 |
| F3, L3, L4, Y2 | format check, lint `src tests`, lint migration, `mypy` | clean | after cause E |
| M6 | migration-only check | passed | round 2 fixes |
| T5 | PostgreSQL targeted: the same eight modules | 75 passed | round 2 fixes |
| U3 | backend unit, full | 3802 passed, 1967 skipped, 1 known warning | round 2 fixes |
| M7 | migration-only check | passed | before P3 |
| P3 | PostgreSQL full | 2131 passed, 1 known warning | round 2 fixes |

The read-only search before T5 and P3 found the same eight modules as before; the other matches
are other features (`record_reversal` of forfeiture and receipt reversals) or unit mocks.

## Review round 3 (fresh read-only subagents, after P3; told to write no file and run nothing)

Independent: 0 blockers, 0 should-fix, 7 notes. It traced both new tests through the walk to the
cent, confirmed they run on the real path and tell stage order from time order, and compared each
changed committed test with HEAD: the 27 head-revision assertions in 15 modules (only the
revision); `test_settlement_return_reversal_migration.py` (two built sources gain four keys, every
case unchanged); `test_settlement_returned_value_left_migration.py` (the renamed Q-97 test now
confirms the reversal, the held-value refusal's no-write check kept; the chain and
payment-return messages; the fail-closed base source gains four keys and two cases move from the
Q-100 message to "incomplete", still 55000). Nothing else got weaker. Notes: N1 stale comments
from migration 128 inside function bodies ("one-step plan", "at most one part") are cosmetic and
change with the next patch of those functions (10e-3e patches them); N2 the own-entry "at most
one" branch is now also refused by the distinct-id check (defence in depth); N3 wording (fixed:
docs/010 H's draw, "a later return" in the plan and traceability); N4 the second test's
`reapplied` order cannot tell its two 300 entries apart (the order is proven at the source); N5
untidy text (fixed: one docs/004 paragraph rewrapped, this record's built section; NOW.md at the
commit); N6 no direct negative test of the wider recovery scope (round 1 and 2 security note);
N7 it relied on the recorded T5 and P3 results.

Security: 0 blockers, 0 should-fix, 5 notes: the confirm's ELSE cannot run (the assert's per-entry
check already refuses an unknown kind); the assert does not refuse the same `record_id` twice in
`swept` (the takes give one row per record and the stored source must equal the recomputed one); no
direct negative test of the wider recovery scope (the draft table is append-only and written only
by the recorder; the confirm recomputes and compares the source); the draft source carries the
other Refund's recipient id (seen only by `final_settlements.prepare` and `financial.approve`
holders; the 11c screen shows it); the round 1 notes (Refunds not row-locked, five walks per source
call, the draft size cap).

After round 3 only text changed (docs/004 rewrap, docs/010, plan and traceability wording, this
record, NOW.md), so P3 covers the commit.

/tmp check: the reviewers wrote no file. The job's tmp folder holds this session's catalog dump,
the patch check script and the patched bodies (scratch, not repo copies).
