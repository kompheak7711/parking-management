# V1-056 sub-slice 10c-2b-5 — pay back returned Pet Refund-review money: review record

Sub-slice: 10c-2b-5 (migration `20261123_119`). Base commit: 4b220e3. Built in one session on
2026-10-11 and committed locally (see git log; the commit right after 4b220e3). Not pushed.

Rule IDs: BR-DEP-022, BR-SETTLE-008, BR-SETTLE-013, DL-032, DL-053; owner answer pay back to
Q-2026-10-09-61, (a) to Q-2026-10-10-73, (A) and (b) to Q-2026-10-10-75, (a) to Q-2026-10-10-76,
(a) to Q-2026-10-11-84; owner standing rule of 2026-10-11 (an answer that changes a result lets the
implementer update the committed test or fixture, affected case only). Design: ops/V1_056_PLAN.md
(10c-2b-5 entry).

## Built

- Migration `backend/migrations/versions/20261123_119_pet_deposit_payback.py`: new internal
  functions (no grant) `lease_deposit_payback_count` (the running count),
  `lease_deposit_payback_value` (smaller of the count and what the Pet Deposit holds; 0 for a
  Security Deposit) and `lease_deposit_payback_after_return` (the returned-Refund plan's
  exception); exact-text patches of `lease_deposit_settlement_path` (key `payback_usd_cents`; a
  Deposit with a ground whose held money is above 0 and all pay-back money is `DL_032`),
  `lease_deposit_forfeiture_source` (forfeits only money beyond the pay-back value; 22023 when
  nothing is beyond) and `settlement_refund_return_plan` (accepts a Pet Deposit whose held money
  after the return would be all pay-back money).
- New module `backend/tests/test_settlement_pet_payback_migration.py` (last in
  `scripts/database-test.sh`): the running count (three cases, the Q-76 example to the cent), an
  empty Pet Deposit with returned money before closure (with and without debt), a forfeiture that
  leaves money returned before the termination for the Settlement, after closure an empty and a
  kept Pet Deposit paying returned money to the open debt first, the refusing side of the
  exception, least privilege and forward-only.
- Changed committed tests and fixtures (owner standing rule; each named in docs/010):
  1. `reviewed_case(pet_noncompliance=True)` (`test_settlement_pet_refund_return_migration.py`,
     that branch only, owner answer (a) to Q-2026-10-11-84): forfeitures 10,000 and 5,000 and the
     Settlement's 3,000 Refund asserted exactly.
  2. `test_a_returned_pet_refund_off_the_dl032_path_is_only_held` renamed
     `test_a_returned_pet_refund_after_a_pet_noncompliance_termination_is_paid_back`.
  3. `test_held_pet_deposit_money_off_the_dl032_path_waits_for_the_owner` renamed
     `test_held_pet_deposit_money_after_a_pet_noncompliance_termination_is_paid_back`.
  4. The 10d fixture `twice_forfeited_case` (`test_settlement_forfeiture_reversal_migration.py`):
     its second forfeiture is refused as a draft (22023, now asserted) and written with the owner's
     one-call disposition. No owner answer names this fixture; it follows from Q-73 (a), Q-75 and
     Q-76 (the draft path can no longer reach two active forfeitures). Named for the owner.
  5. 27 head-revision assertions in 15 modules move to `20261123_119`.
- `ops/traceability.json`: two entries renamed with notes, the 10d entry's note extended, seven
  entries appended. docs/004 (DB-DEP notes, the returned-Refund note, the amended KEPT sentence),
  docs/010 (sub-slice entry, updated tests, rounds 1 and 2), the plan (as built).

## Runs

Static checks, each in its own call: format check (2 corrections, cause: long lines in the new
test module, 2 of 2 used), lint clean, mypy clean. Migration-only check
(`scripts/migration-check.sh`): 118 upgrades, head `20261123_119`, before T1, before P1, after the
round 1 migration fix and before P2. Read-only search of every backend test for the patched and
new functions, the fixture, `pet_noncompliance`, forfeiture drafts with Pet Refund-review
Refunds and the revisions: the affected modules are the three changed modules, the 15 head
modules and the new module, all in P1 and P2.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T1 | PostgreSQL targeted: new module, 10c-2b-2b, 10c-2b-3, 10d modules | 28 passed, 1 warning | first run | `V1-056-slice-10c-2b-5-targeted-test-run.txt` |
| U1 | backend unit, full (caffeinate) | 3744 passed, 1894 skipped, 1 warning | first unit run | `...-unit-test-run.txt` |
| P1 | PostgreSQL full (caffeinate) | 2058 passed, 1 warning | first full run | `...-full-test-run.txt` |
| T2 | PostgreSQL targeted: new module | 10 passed, 1 warning | round 1 fixes | `...-targeted-test-run-2.txt` |
| U2 | backend unit, full (caffeinate) | 3744 passed, 1897 skipped, 1 warning | round 1 fixes | `...-unit-test-run-2.txt` |
| P2 | PostgreSQL full (caffeinate) | 2061 passed, 2 warnings (known) | round 1 fixes changed the migration and tests (run rule) | `...-full-test-run-2.txt` |

No run failed. Secret check of all six outputs: no database URL with credentials, no
`password=`, no 64-character hex string.

## Review round 1 (fresh read-only subagents, during P1)

Independent: 0 blockers, 2 should-fix, 7 notes. Security: 0 blockers, 1 should-fix, 4 notes.

Fixed:
- SF (both): no test was left for the "only on the DL-032 path" refusal of the returned-Refund and
  held-value forms after the two committed tests changed; new
  `test_a_kept_pet_deposit_holding_its_own_money_is_not_paid_back` (a hand-built kept Pet Deposit
  with 1,000 own and 3,000 pay-back money; both forms refused, no draft; the helper false for 0,
  none and a Security Deposit).
- SF (independent): matrix cells added: a kept Pet Deposit after closure with open debt
  (`test_after_closure_a_kept_pet_deposit_pays_returned_money_to_the_open_debt_first`) and an
  empty Pet Deposit before closure with no debt (parameter of the before-closure test).
- Notes fixed: the helper requires the Deposit to hold money after the return; the
  least-privilege test checks SECURITY DEFINER and `search_path`; docs/004 states the invariant,
  when `payback_usd_cents` has an effect, and amends the KEPT sentence.

Listed for slice 12 (docs/010): the same pay-back limit in the disposition insert check (a
tightening for the owner); the 10d guard's docstring and message; a test of the
`RECOVERED_BY_CHARGE` exclusion and of a Settlement Refund's return not counting; the invariant as
a check item in the 10e-3 and 10h pre-code designs; a stale comment in migration `20261114_110`.

## Review round 2 (fresh read-only subagents, during P2)

Independent: 0 blockers, 0 should-fix, 6 notes. It compared every changed committed test and
fixture with HEAD: nothing weaker; on the 10d fixture no check removed (HEAD's second forfeiture
had no assertion; the fixture adds the 22023 check). Security: 0 blockers, 0 should-fix, 5 notes.

Notes: two docs/004 wordings fixed (text only, after P2: the KEPT sentence needs held money; the
invariant names a Pet Deposit receipt writer); the rest listed for slice 12 in docs/010 (docs/002
BR-DEP-022/026/027 amendment lines; the helper does not read the ground, equivalent today; the
forfeiture source mixes `infinity` and the statement time, equal today; the helper test's
Security Deposit case fails on the Refund mismatch). Round 2 has no should-fix, so no round 3.
