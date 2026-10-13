# V1-056 sub-slice 10e-3d-1 — every correction's use of returned money counts: review record

Sub-slice: 10e-3d-1 (migration `20261203_129`). Base commit: 1e6af04 (the 10e-3d design and the
owner answers to the 10e-3c report). Built on 2026-10-13. Stopped after review round 2
(Q-2026-10-13-101, answered (a)), then again after review round 3 and P3 (Q-2026-10-13-102,
answered (a)); committed after the clean review round 4 (commit hash in ops/NOW.md and git log).
Not pushed.

Rule IDs: BR-SETTLE-008, BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-014, DL-032; DB-SETTLE-005; owner
answer (a) to Q-2026-10-12-97 and its detail of 2026-10-13. Design: ops/V1_056_PLAN.md (the
"10e-3d pre-code design" and "10e-3d-1 as built" bullets).

## Built (working tree)

- Migration `backend/migrations/versions/20261203_129_settlement_returned_value_left.py`: new
  internal `app.settlement_returned_value_left(uuid,text,uuid,uuid)` (no grant); exact-text
  patches of `app.settlement_held_deposit_value`, `app.settlement_held_credit_value` (whole
  bodies), `app.settlement_return_reversal_source_state` (`swept_usd_cents`, `left_usd_cents`) and
  `app.assert_settlement_return_reversal_allowed` (the swept refusal and the left-value limit).
- New test module `backend/tests/test_settlement_returned_value_left_migration.py` (nine tests:
  seven through review round 3, two added for the round 3 findings), last in
  `scripts/database-test.sh`.
- Changed committed tests (owner standing rule of 2026-10-11; owner answer (a) to Q-97): the 27
  head-revision assertions in 15 modules (one `sed` replacement of the exact quoted revision,
  counted: 27); `test_settlement_held_deposit_limit_migration.py::test_a_correction_that_names_no_earlier_correction_still_settles_held_money`;
  in `test_settlement_return_reversal_migration.py` the guards test's last refusal and
  `"swept_usd_cents": 0` in the built sources of two refusal-function tests.
- `ops/traceability.json` (four notes changed, nine entries appended; Edit tool only), docs/004,
  docs/010, the plan, the questions file, and the new run rule in ops/V1_055_RUN_RULES.md (owner
  answer 5 of 2026-10-13).

## Runs

Static checks, each in its own call: `ruff check src tests`, `ruff format --check src tests`, the
same two on the migration file, `mypy`. Full outputs in `~/Development/prm-run-logs/`
(`V1-056-slice-10e-3d-1-*`).

| Run | Kind | Result | Cause |
|---|---|---|---|
| C1 | throwaway catalog dump at head 128 (not a test run) | 722 functions | pre-code read |
| M1 | migration-only check | passed | first |
| L1 | `ruff check src tests` | 2 lines too long (new test) | cause A (lint, line length), correction 1 of 2 |
| F1 | `ruff format --check src tests` | 1 file | cause B (formatter), correction 1 of 2 |
| T1 | PostgreSQL targeted: held-value, held-Deposit limit, pay-back, real-path, return reversal, returned Payment after closure, new module | 60 passed | first |
| U1 | backend unit, full | 3802 passed, 1952 skipped, 1 known warning | first |
| M2 | migration-only check | passed | before P1 |
| P1 | PostgreSQL full | 2116 passed, 2 known warnings | first |
| L2 | `ruff check src tests` | import order (I001) | cause C (lint, import order), correction 1 of 2 |
| F2 | `ruff format --check src tests` | 1 file | cause B, correction 2 of 2 (allowance used up) |
| Y1 | `mypy` | 2 errors (untyped service result) | cause D (types), correction 1 of 2 |
| M3 | migration-only check | passed | round 1 fixes |
| T2 | PostgreSQL targeted: the same seven modules | 61 passed | round 1 fixes |
| U2 | backend unit, full | 3802 passed, 1953 skipped, 1 known warning | round 1 fixes |
| M4 | migration-only check | passed | before P2 |
| P2 | PostgreSQL full | 2117 passed, 1 known warning | round 1 fixes |

Every targeted and full run used `caffeinate -dims`. Read-only search before T1 and before P1 and
P2: the patched functions are read only by the held-value Refund, held-Deposit limit, pay-back,
real-path and return reversal modules (and the returned-Payment-after-closure module imports the
return reversal module); no other test reads a left value or the return reversal source.

## Review round 1 (fresh read-only subagents, during P1; told to write no files; none did)

Independent: 1 blocker, 2 should-fix, notes. Security: 0 blockers, 0 should-fix, 6 notes.

- Blocker (fixed): the count read each correction's records as they are now, so a `REFUND`
  correction that releases an application (reversed whole, its rest written again) and refunds the
  released part counted as using returned money. Now each correction's net draw at its own time
  (paid out less brought back, never below 0); a `RETURN_REVERSAL` names its earlier correction.
  Tested (an ordinary application of 1,500 released by a `REFUND` correction of 500: the return
  keeps 1,800 left).
- Should-fix (fixed): the order rules were not proven (new test: the named return first, then the
  oldest); "The Deposit holds no returned money to refund" lost its only tests (answered: unreachable
  by counted paths, kept as a backstop for the known limits; the Credit sibling is tested).
- Notes answered in docs/004 and docs/010 (known limits named; the reversal-limit claim narrowed to
  the counted uses; any value other than 0 refused); security note 1 (clock order) on the slice 12
  list.

## Review round 2 (fresh read-only subagents, during P2; told to write no files; none did)

No blocker. Three should-fix in total, so the standing round-3 rule (at most two) does not apply:
STOPPED (Q-2026-10-13-101).

- Security SF1: the reversal is not limited to the return's own left value when a use's Refund
  came back through a later return (its net is 0, so nothing is undone, while the count took its
  gross payout from the named entry): C1 returns 100 (return only); a held-value Refund naming C1
  pays it out; C4 returns that Refund; C1's reversal then passes (swept 0, the Credit holds 100) and
  takes C4's money. Present since 10e-3; the owner's limit rule covers it.
- Independent SF1: netting can hide a counted payout: a `DEPOSIT_RECEIPT_CORRECTION` brings back
  applications (counted) and reverses the receipt (not counted), so its payout of a return's money
  nets to 0 and the return keeps its left value while the Deposit is empty.
- Independent SF2: "own return first" is not proven by a test (every case pays out everything).
- Notes (text): a part a `RETURN_REVERSAL` applies again does not itself lower the left value under
  the net count (X1's money was taken at X2's time; docs/004, the migration docstring, a test
  docstring and a traceability note say otherwise); a partial sweep limits rather than refuses a
  held-value Refund; every `RETURN_REVERSAL` draft from before 129 is stale (its source gains a
  key); clipping at 0 can understate a left value (fail closed); lost coverage of the Deposit cap
  (slice 12 item). Security notes: definer and grants right; crafted records cannot raise a left
  value; a missing count row reads as swept 0 (not reachable; NULL would fail closed); cost
  acceptable; no secrets in the diff or the run outputs.

## Proposed fixes (after the owner's answer)

See Q-2026-10-13-101: the left-value limit in the reversal check; the correction's own receipts,
receipt reversals, forfeitures and their reversals, and Credit reversals in its net draw; an
own-return-first test if the real path reaches it (otherwise the wording); the text notes; then the
static checks, M5, U3, the read-only search, P3 and review round 3.

## Owner answer to Q-2026-10-13-101 and the round 2 fixes

Option (a), a one-time exception. Fixed: (a) the source names `left_usd_cents` and the check
refuses a reversal that takes more than it (tested on the real path: a held-value Refund naming C1
paid C1's 100 out, the Refund came back through C4, and C1's reversal is refused while the Credit
holds C4's 100); `swept_usd_cents` and `left_usd_cents` no longer default to 0. (b) a correction's
own Deposit receipts and forfeiture reversals count as brought back, its receipt reversals and
forfeitures as paid out, and its reversal of the Credit takes all the Credit still holds (no test;
see round 3). (c) answered in docs/004 instead of a test (wrong; see round 3). Text notes fixed in
docs/004, the migration and test docstrings and traceability. In the committed
`test_settlement_return_reversal_migration.py` the two built sources also gain
`"left_usd_cents": 0` (their cases unchanged). The formatter was run on the four changed Python
files before the format check (owner instruction; it changed nothing).

| Run | Kind | Result | Cause |
|---|---|---|---|
| T3 | PostgreSQL targeted: the same seven modules | 62 passed | round 2 fixes |
| U3 | backend unit, full | 3802 passed, 1954 skipped, 1 known warning | round 2 fixes |
| M5 | migration-only check | passed | before P3 |
| P3 | PostgreSQL full | 2 failed, 2116 passed, 2 warnings | outside the sub-slice: both `LockNotAvailable` from the `NOWAIT` lock in `app.assert_payment_excess_eligible`, in `test_refund_migration.py` (`test_usd_refund_private_boundary_immutable_history_and_fresh_actor`, and `test_usd_refund_khr_origin_uses_recorded_usd_without_repricing`, the slice 12 item of Q-2026-10-05-26); no 10e-3d-1 change touches that path; P2 passed the same tests |

Static checks after the fixes, each in its own call: the formatter on the changed files, `ruff
format --check src tests`, the same on the migration, `ruff check src tests`, the same on the
migration, `mypy`: all clean.

## Review round 3 (fresh read-only subagents, during P3; told to write no files; none did)

Security: 0 blockers, 0 should-fix, 5 notes (the new terms are untested; overflow fails closed; six
walks per return-reversal confirm, acceptable; the removed "reversed return leaves nothing" guard is
safe today, cheap to keep; clipping at 0 can refuse a valid reversal, fail closed). Independent: 0
blockers, 3 should-fix, so round 3 is not clean: STOPPED (Q-2026-10-13-102).

- SF1: "own return first" can be seen on the real path: a return-only Credit `REFUND_RETURN` with
  its own step (committed held-value test 1 builds one). X1 returns 300; X2 returns 1,700 return
  only and its step applies 1,500: own first gives X1 300 left and X2 200; oldest first would give
  X1 0. The docs/004 claim is wrong; a test is needed.
- SF2: the round 2 fix (b) has no test (receipts, receipt reversals, forfeitures and their reversals,
  the Credit reversal).
- SF3: text still describes round 1 (plan as-built line, docs/010 entries, the built-source
  `left_usd_cents` change not named in docs/010, an example that is now counted).
- Notes: the new limit cannot newly refuse a committed case (every reversal traced); left values
  never go up; after a Credit reversal the reversal of its returns gets the Q-100 message although
  the Credit holds nothing; stale text in ops/NOW.md and this record; the Deposit-cap slice 12 item
  is only here; the changed committed tests are only the cases the owner answers cover.

/tmp check after round 2: no file from this session's reviewers. Two older items exist from earlier
sessions (`/tmp/rev2/`, 2026-10-12; `/tmp/trace_head_r2.json`, 2026-10-13 03:08); left untouched.

## Owner answer to Q-2026-10-13-102 and the round 3 fixes (fresh session, 2026-10-13)

Option (a) (docs/010, questions file). Built, tests and text only (no migration or product code
change since round 3):

- SF1: new test `test_a_correction_s_own_return_is_used_first` (X1 brings back 300 return only; X2
  brings back 1,700 return only and its step pays 1,500 of a charge: X1 keeps 300, X2 200; X1's
  reversal takes exactly its 300 and puts it back on the Refund; a held-value Refund naming X2
  refunds its 200). The wrong docs/004 claim ("cannot be seen on the real path") is corrected.
- SF2 (owner's scope): new test
  `test_a_payment_return_and_a_receipt_correction_count_what_they_take_from_a_return`: a
  `RETURNED_PAYMENT` correction that charges the Refund's 1,700 rest back and reverses the Credit
  after a 300 return, and a `DEPOSIT_RECEIPT_CORRECTION` whose 20,000 receipt reversal follows a
  1,000 return of the Pet Deposit Refund (applications 14,600 and the 4,400 recovery brought back):
  each earlier return then has nothing left, its reversal is refused with the Q-100 message and
  writes nothing, and (Credit) a held-value Refund naming it is refused. The right receipt,
  forfeiture and forfeiture reversal terms and the Deposit holdings cap test are on the plan's
  slice 12 list.
- SF3: plan (10e-3d-1 as built, the 10e-3d-2 split, the order, slice 12 items), docs/010 (entries
  brought to the current state, `"left_usd_cents": 0` named, rounds 2 and 3, the owner answers),
  docs/004 (own return first; Q-100 answered). Two traceability entries appended for the new tests.
- Owner answer 2: `test_usd_refund_private_boundary_immutable_history_and_fresh_actor` joins the
  slice 12 `LockNotAvailable` item. Owner answers to Q-2026-10-13-100 ((a), (a)) recorded for
  10e-3d-2; new run rule (a reviewer confirms that a test cannot be written on the real path).

Static checks, each in its own call: the formatter on the changed test file (unchanged),
`ruff format --check src tests`, the same on the migration, `ruff check src tests`, the same on the
migration, `mypy`: all clean, no correction.

| Run | Kind | Result | Cause |
|---|---|---|---|
| T4 | PostgreSQL targeted: the same seven modules | 64 passed | round 3 fixes |
| U4 | backend unit, full | 3802 passed, 1956 skipped, 1 known warning | round 3 fixes |
| M6 | migration-only check | passed | before P4 |
| P4 | PostgreSQL full | 1 failed, 2119 passed, 3 warnings | outside the sub-slice: `Signature evidence is invalid` in the Lease signing fixture (`signed_with_initial`) of `test_settlement_held_deposit_limit_migration.py::test_a_draft_recorded_without_the_limit_is_stale`; the known `LockNotAvailable` tests passed |
| K2 | clock check (run rule): `docker run --rm --pull=never --entrypoint date postgres:17.6 +%s%6N` between two Mac readings, three times; not a test run | in step each time | before the rerun |
| M7 | migration-only check | passed | before P5 (no file changed since P4) |
| P5 | PostgreSQL full, the one rerun the signature clock rule allows | 2120 passed, 3 warnings | rerun of P4 |

Read-only search before T4 and P4: since P3 only the new test module changed (no other test imports
it; the patched functions are unchanged). Full outputs in `~/Development/prm-run-logs/`
(`V1-056-slice-10e-3d-1-*-4`, `-5`, `-6`, `-7`); no run output goes into the repo.

## Review round 4 (fresh read-only subagents, after P5; told to write no files; none did)

Independent: 0 blockers, 0 should-fix. Every changed committed test compared with HEAD: the 15
head-revision modules change only the quoted revision (27 assertions); the held-Deposit limit test
follows owner answer (a) to Q-97 with added assertions (lost: a successful confirm under the
Deposit cap, on the slice 12 list); in the return reversal module the guards test's message changes
consistently, and every case of the two hand-built source tests (with `"swept_usd_cents": 0` and
`"left_usd_cents": 0`) still stops at the same check as before. The new tests would fail under an
oldest-first order or without the Credit-reversal or receipt-reversal term. Notes applied (text):
this record, the Q-101 heading marker, two traceability notes naming the left value, the docs/010
placement of the slice 12 item worded as the implementer's. Notes left for 10e-3d-2 (code text that
would force a new full run): the migration docstring, an SQL comment and the test module docstring
still say the reversal "waits for the owner". Cosmetic: uneven wraps in docs/004.

Security: 0 blockers, 0 should-fix. Notes: no role can call the new function; patched functions keep
owner, settings and privileges; no dynamic SQL; no crafted record raises a left value; the new
checks fail closed; known limits documented; the clock-order note stays on slice 12; the new tests
add no rights; secret scan of the diff, the untracked files and the six run outputs: nothing real
(hits are prose about the scan rule and names of existing password test and migration files).

/tmp check after round 4: no file from this session's reviewers; `/tmp/rev2/anchors.py` left alone
(owner instruction).
