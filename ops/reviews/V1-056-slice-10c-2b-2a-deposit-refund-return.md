# V1-056 sub-slice 10c-2b-2a — returned Deposit Refund, receipt reversal refusal: review record

Sub-slice: 10c-2b-2a (migration `20261112_108`). Base commit: 0d242a2. Not committed (commit hash in
ops/NOW.md once committed).

Rule IDs: BR-SETTLE-008, BR-SETTLE-013, BR-REFUND-014, BR-REFUND-015, DL-032, BR-AUTH-010; owner
answer 3 to Q-2026-10-07-42, answers 3 and 5 to Q-2026-10-08-55, answer 5 to Q-2026-10-08-52, the
answers to Q-2026-10-08-56 and Q-2026-10-08-58.

## Built

- Migration `20261112_108`:
  - The 10c-2b-1 functions replaced in place (`CREATE OR REPLACE`): `REFUND_RETURN` also returns a
    Final Settlement Deposit Refund (8d) and a correction's Deposit Refund. Return only: the
    Deposit holds the amount, no step (`runs_step` false; a plan refused, 22023). With a new
    Refund: the step runs on the Deposit (overlay `deposits`); only on the DL-032 path (55000).
    The return check also binds the reason (10c-2b-1 round-3 note).
  - `app.validate_general_refund_correction` patched: the return check runs before the 8d refusal,
    which now passes only the correction's own return; a Settlement Deposit Refund reads its
    Deposit for lock and chronology.
  - Approved tightening: `app.validate_deposit_receipt_reversal` (insert) and
    `app.record_deposit_receipt_reversal_draft` (record) refuse a closed Settlement's Lease
    Deposit receipt (P5S01), the insert unless a correction of that Settlement links the row.
- Service: the receipt reversal service maps P5S01 to a conflict.
- Tests: new module `test_settlement_deposit_refund_return_migration.py` (6 tests at P1, 10 after
  review rounds 1 and 2); the receipt
  reversal and Lease forfeiture unit tests gain the P5S01 case; the two changed committed 10c-2b-1
  tests (owner answers to Q-58 and Q-59 answer 3, set-up only); 27 head-revision assertions; 10
  traceability entries.
- Docs: docs/004 (DB-SETTLE-005, DB-REFUND-002, DB-DEP-007), docs/005 (receipt reversal
  amendment), docs/010 (answers to Q-58, the sub-slice entry with three choices, updated tests),
  the questions file, the plan.

## Read-only search of every backend test

Receipt reversals: no committed test reverses a Deposit receipt of a Lease whose Final Settlement
is closed (the receipt reversal tests and the Settlement tests that reverse receipts do so before
any closure). Refund corrections of Deposit Refunds: the 8d refusal test keeps its code and
message. The 14 head-revision modules and the 10c-2b-1 module's head assertion. The 10c-2b-1 test
that used the 8d Refund as "not returnable" (changed, owner answer to Q-58).

## Runs

Static checks each in its own call. Lint failed twice on one cause (a docstring line in the edited
10c-2b-1 test; corrections 1 and 2 did not wrap it), then the allowance was used up: STOPPED
(Q-2026-10-08-58); after the owner exception, one text-only fix, lint clean. Format and type check
clean. Migration-only check: 107 upgrades, head `20261112_108`.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T1 | PostgreSQL, targeted: the two return modules (a check before the full run) | 1 failed, 11 passed | cause A (test): the 10c-2b-1 `effect_links` helper knows three link kinds, this correction also writes a Deposit application link (StopIteration); correction 1 of 2: a local helper | `V1-056-slice-10c-2b-2a-targeted-test-run.txt` |
| T2 | PostgreSQL, targeted: the new module | 6 passed | after cause A | `V1-056-slice-10c-2b-2a-targeted-test-run-2.txt` |
| U1 | backend unit, full (under `caffeinate -dims`) | 3629 passed, 1801 skipped (every skip a database URL reason), 1 warning (Starlette) | first unit run | `V1-056-slice-10c-2b-2a-unit-test-run.txt` |
| P1 | PostgreSQL, full (under `caffeinate -dims`) | 1964 passed, 2 warnings (Starlette; the known Pydantic `UnsupportedFieldAttributeWarning` in `test_credit_refund_api_migration`, a slice 12 item since 8d) | first full run | `V1-056-slice-10c-2b-2a-full-test-run.txt` |

## Review round 1 (2026-10-08; fresh read-only subagents, independent and security)

Independent: 1 blocker, 2 should-fix, 4 notes. Security: 0 blockers, 1 should-fix (the same point as
independent SF1), 5 notes. STOPPED (Q-2026-10-08-59): the fix of SF1 is a tightening, and the
blocker's fix either changes a committed test or removes a binding. No fix is made yet.

- Changed committed test (owner answer to Q-58): the independent reviewer compared it with HEAD:
  name and every assertion unchanged, only the first refusal's input (an ordinary 300 Credit
  Refund) and the docstring; not weakened.
- Blocker (independent): the reason binding added in 108 makes the committed 10c-2b-1 test
  `test_the_relaxed_refund_correction_check_accepts_nothing_else` vacuous: its hand-built rows use
  the reason `'Direct'`, so every attempt is now refused by the reason alone and the "draft's own
  return passes, a second one is refused" block never reaches its second insert. The test still
  passes (P1), so the loss is invisible. Options in Q-59.
- SF1 (independent and security; the owner's check on Q-58): a returnable Deposit Refund (8d or a
  correction's) is always paid on the DL-032 path. A Deposit with no forfeiture ground (every Pet
  Deposit except at a BR-DEP-022 termination, the owner's BR-DEP-027 example included) stays on
  DL-032 for good and can be refunded again (the same correction with a new Refund, any later step,
  10c-2b-3). A Deposit with a ground is on DL-032 only because its forfeiture was reversed; after a
  return-only correction it holds money after closure, and the Lease forfeiture draft (no closure
  check) can forfeit it again without a correction, moving it to KEPT; a later return of the same
  Refund is then held by a KEPT Deposit with no refund path (the step and 10c-2b-3 ignore Deposits
  off DL-032). Fix: a tightening (Q-59).
- SF2 (independent): a Credit `REFUND_RETURN` always runs the step, and the step needs every
  DL-032 Deposit balance applied or refunded; a return-only draft may not have a Deposit Refund
  step. So while a Deposit holds an earlier returned amount that no debt takes, a Credit return-only
  correction is refused (55000) until that Deposit value is handled. Owner choice (Q-59).
- Security N2: the receipt reversal recorder's closure check is a plain read; a REPEATABLE READ
  caller whose snapshot predates the closure could record a draft (never confirmable, but it would
  block correction steps as a pending draft). Fix: a READ COMMITTED check in the recorder (a further
  tightening, Q-59).
- Security N3: the return-only plan is checked only for empty `steps` and null `pet_remainder`;
  other keys would be stored. Fix (no owner needed): require exactly the empty plan.
- Independent N1, security N4: a REFUND_RETURN draft recorded under 107 cannot be confirmed after
  108 (no `runs_step`; the digest gained a `deposit` key); it fails closed (P0002 or stale);
  nothing is live. Fix: a docs/010 note.
- Independent N2, security N5: the reversal branch of the Refund correction check still keys on
  `pet_refund_review_id`; unreachable today; the future `RETURN_REVERSAL` (Q-57) must switch it to
  `source_deposit_id`. Fix: a plan note under Q-57.
- Independent N3: NOW.md line out of date (updated with this stop).
- Independent N4, security N6: test gaps (a Deposit Refund of another closed Settlement; a stale
  Deposit return draft; a correction's Deposit Refund returned with a new Refund; the receipt
  reversal confirm path; a refused one-call reversal of a correction-written Deposit return;
  BR-REFUND-015 has no traceability entry in this sub-slice; the 55000 non-DL-032 branch has no
  test). Fix with the round-1 fixes after the owner answer.
- Security N6: the one-call return of a Pet Refund-review Refund stays open after closure until
  10c-2b-2b (owner answer 6 to Q-55).

## Owner answers to Q-2026-10-08-59 and the round-1 fixes

Answers (docs/010): 1 (a) forfeiture refused after closure; 2 allow a Credit return-only
correction while a Deposit holds returned money that no debt can take; 3 (b) keep the reason check,
change only the set-up of the committed test, add a reason test; 4 (a) READ COMMITTED for the
receipt reversal recorder. Fixes:

- Blocker (answer 3): `RETURN_ROW`/`return_values` in the 10c-2b-1 module carry the draft's reason
  by default (set-up only; name and assertions as at HEAD); new
  `test_the_return_check_binds_the_draft_s_reason` (on a Settlement Deposit Refund: another reason
  refused by the 8d check, the draft's reason passes).
- SF1 (answer 1): the forfeiture recorder refuses a closed Settlement's Lease Deposit (P5S01, before
  the ground check) and the disposition insert check refuses such a row unless linked (no kind
  links a forfeiture yet; the implementer note in Q-59 says so; the insert check is defence in
  depth for a draft the recorder takes, and the barrier for a draft recorded after closure by a
  REPEATABLE READ caller, Q-60; a direct insert meets `deposit_dispositions_require_context`
  first); the forfeiture service maps P5S01 to a conflict (unit case added); test.
- SF2 (answer 2): the plan check's overlay flag `hold_deposits` (only a return-only Credit
  `REFUND_RETURN` records it; the step keeps it): a DL-032 Deposit may keep returned money that no
  open debt can take; test (both the accepted hold and the refusal when open debt could take it).
- Security N2 (answer 4): the receipt reversal recorder refuses outside READ COMMITTED (55000); test.
- Security N3: the return-only Deposit plan must be exactly the empty plan.
- Notes: docs/010 notes on drafts recorded under 107 and on the reversal branch for Q-57; a stale
  second Deposit return draft test. Not added (noted): a Deposit Refund of another closed
  Settlement; a correction's Deposit Refund returned with a new Refund; the receipt reversal
  confirm path (a draft cannot be recorded after closure, and closure waits for pending drafts).

Static checks each in its own call: lint failed on the round-1 test additions (import order and two
long lines; cause: lint of the new tests, correction 1 of 2), then on import order again after the
forfeiture import (correction 2 of 2, fixed by the import sorter), then clean; format and type
check clean. Migration-only check: 107 upgrades, head `20261112_108`.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T3 | PostgreSQL, targeted: the 10c-2a-6 module (reads the step's source) and both return modules | 18 passed | round-1 fixes | `V1-056-slice-10c-2b-2a-targeted-test-run-3.txt` |
| U2 | backend unit, full | 3629 passed, 1804 skipped (database URL reasons), 1 warning (Starlette) | round-1 fixes | `V1-056-slice-10c-2b-2a-unit-test-run-2.txt` |
| P2 | PostgreSQL, full | 1967 passed, 2 warnings (Starlette; the known Pydantic warning) | round-1 fixes | `V1-056-slice-10c-2b-2a-full-test-run-2.txt` |
| T4 | PostgreSQL, targeted: the 10c-2b-2a module (the only database test changed after P2: the forfeiture test expects the conflict error) | 9 passed | forfeiture service mapping | `V1-056-slice-10c-2b-2a-targeted-test-run-4.txt` |
| U3 | backend unit, full | 3630 passed, 1804 skipped, 1 warning (Starlette) | forfeiture service mapping (one new unit case) | `V1-056-slice-10c-2b-2a-unit-test-run-3.txt` |

## Review round 2 (2026-10-08; new fresh read-only subagents, independent and security)

Independent: 0 blockers, 2 should-fix, 6 notes; both changed 10c-2b-1 tests compared with HEAD:
names and assertions unchanged, set-up only, not weakened. Security: 0 blockers, 0 should-fix, 3
notes; every round-1 fix verified; no path sets `hold_deposits` other than a return-only Credit
`REFUND_RETURN`. Under the standing rule one round 3 follows, after the full runs below.

- SF1 (independent; fixed, code and test): the hold rule's Pet branch measured pet damage open at
  the end of the plan, so a held-mode plan could pay pet damage with the Security Deposit while the
  Pet Deposit kept money (against "the Pet Deposit pays open pet damage before any other use").
  Now it uses `v_pet_after_three` (pet damage open after the Pet Deposit's own step).
- SF2 (independent; fixed, tests): new `test_the_hold_rule_keeps_only_money_no_open_debt_can_take`
  (the plan check with a crafted overlay on a closed Settlement: the Security branch refused; the
  pet-damage branch refused when the Security Deposit pays the pet damage; the plan with the
  Customer's Credit first and the Pet Deposit paying the pet damage accepted); the refusal plan of
  the Credit return-only test now uses both Credits. Not tested: a Pet Deposit keeping money with
  other debt open at a BR-DEP-027 termination without a Customer choice (no fixture; docs/010).
- Independent N1, security N1: the Lease forfeiture recorder has no READ COMMITTED guard (a
  tightening): Q-2026-10-08-60 (not blocking); the "not reachable" wording is corrected (the insert
  check is the barrier for such a draft).
- Independent N2: the trigger that fires first is `deposit_dispositions_require_context` (the
  Deposit disposition context trigger); docs/010 and this record corrected.
- Independent N3: docs/004 BR-SETTLE-008 sentence names the hold exception.
- Independent N4: plan updated (Q-59 outcomes; the reversal-branch note under Q-57); NOW.md at
  commit.
- Independent N5: the exact empty plan is tested with a non-null `pet_remainder`.
- Independent N6: counts updated (10 tests in the new module, 10 traceability entries; the
  forfeiture service unit case named in docs/010).
- Security N2: tests not added are listed in the questions file note; a refused one-call reversal
  of a correction-written Deposit return is not added (the one-call paths refuse every
  correction's Refund before any lock, tested on Credit Refunds in 10c-2b-1).
- Security N3: the forfeiture reversal after closure stays planned for 10d/10h.

After the fixes: format, lint and type check clean, each in its own call (the formatter and the
import sorter were applied before the checks); migration-only check 107 upgrades, head
`20261112_108`.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T5 | PostgreSQL, targeted: the 10c-2b-2a module | 10 passed | review round 2 fixes | `V1-056-slice-10c-2b-2a-targeted-test-run-5.txt` |
| U4 | backend unit, full (under `caffeinate -dims`) | 3630 passed, 1805 skipped, 1 warning (Starlette) | standing rule before round 3 | `V1-056-slice-10c-2b-2a-unit-test-run-4.txt` |
| P3 | PostgreSQL, full (under `caffeinate -dims`) | 1968 passed, 3 warnings (Starlette; the known Pydantic `UnsupportedFieldAttributeWarning` in two `test_credit_refund_api_migration` tests, slice 12 item) | standing rule before round 3 | `V1-056-slice-10c-2b-2a-full-test-run-3.txt` |

## Review round 3 (2026-10-08; new fresh read-only subagents, independent and security; the standing rule's round 3)

Independent: 0 blockers, 0 should-fix, 7 notes; both changed 10c-2b-1 tests compared with HEAD
again (set-up and the first refusal's input only; names and assertions unchanged; not weakened).
Security: 0 blockers, 0 should-fix, 4 notes. No should-fix, so 10c-2b-2a is committed (hash in
ops/NOW.md). Text fixes after round 3 (no code or test behaviour changed; static checks only):

- Independent N1, N2: the migration's and the test module's docstrings name every patched function
  and the Q-59 additions.
- Independent N3: this section's counts; docs/010 says the Q-58 test's docstring is re-wrapped and
  reworded.
- Independent N4: NOW.md at commit.
- Independent N5: docs/004 DB-DEP-004 cross-reference to the forfeiture refusal; two long lines
  re-wrapped.
- Independent N6 (carried into 10c-2b-2b, plan): the service turns an aware `returned_at` at the
  edge of the date range into `FinalSettlementInvalidError` (from the 10c-2b-1 round-3 notes).
- Independent N7 (not added): a test of the disposition insert refusal itself (it needs a
  hand-built context or a disabled trigger); the forward-only test pins its body.
- Security N1 (plan, 10c-2b-2b; do not push 2a without 2b): after 108 a return-only correction can
  leave the Pet Deposit holding money, so a one-call reversal of a Pet Refund-review Refund's return
  recorded before closure could use it (no money is paid out); 2b refuses both one-call paths after
  closure, with a test on that state.
- Security N2 (optional, not built): refuse `hold_deposits` with a non-empty `deposits` overlay
  (defence in depth; only the recorder builds overlays).
- Security N3: Q-2026-10-08-60 (open, not blocking).
- Security N4: a return-only Deposit correction runs no plan check, so no pending-draft check; any
  Deposit draft pending after closure cannot be confirmed (P5S01 at insert), and a Deposit Refund
  still waits for it.
