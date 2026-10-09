# V1-056 sub-slice 10c-2b-4 — the stricter Deposit count of HELD_VALUE_REFUND: review record

Sub-slice: 10c-2b-4 (migration `20261116_112`). Base commit: 9c82c79. Not committed (commit hash in
ops/NOW.md once committed).

Rule IDs: BR-SETTLE-008, BR-SETTLE-013, DL-032, BR-AUTH-010; owner answer of 2026-10-09 to the
Deposit counting reported after 10c-2b-3 (Q-2026-10-09-64, an approved tightening). Pre-code
design: ops/V1_056_PLAN.md (10c entry, "10c-2b-4").

## Built

- Migration `20261116_112`: exact-text patches through `pg_get_functiondef` of
  `app.settlement_correction_plan_result` (optional overlay key `held_left`, the per-Deposit
  limit, in place of the every-balance rule), `app.record_settlement_held_value_refund_draft`
  (stores the limit), `app.post_settlement_correction_plan` (passes it for this variant; none
  stored: `{}`) and `app.confirm_settlement_held_value_refund` (a draft without the recomputed
  limit is stale, P5S02). No new function, table or column; no service change.
- Changed committed test (owner instruction, name kept):
  `test_a_credit_return_while_a_deposit_holds_money_is_refunded_with_that_money`.
- Tests: new module `test_settlement_held_deposit_limit_migration.py` (6 tests); 27 head-revision
  assertions; 6 traceability entries and the changed test's note.
- Docs: docs/004, docs/010 (owner answer, sub-slice entry, updated tests, known-limit sentence of
  the Q-2026-10-09-63 entry), the plan, the questions file (Q-2026-10-09-64).

## Read-only search of every backend test

Only the held-value module and the new module call the patched recorder and confirm; the plan-check
tests of 10c-2a-2 and 10c-2b-2a pass no `held_left`; the source checks of the step (choice
re-check order; no `interval` or `age(`) still hold after the patches. The module's Deposit-form
tests use exactly the value left, so only the one Credit-form test showing the old limit changes.
The 27 head-revision assertions move to `20261116_112`.

## Runs

Static checks each in its own call. Lint failed twice for cause A (lines over 100 characters, in
the new module and the changed test; corrections 1 and 2 of 2, the second after the round-1 test
additions); format failed once (cause B, one wrapped call, correction 1 of 2); type check failed
once (cause C, a tuple of overlays needed an annotation, correction 1 of 2); then all clean.
Migration-only check (throwaway copy of `scripts/database-test.sh`): 111 upgrades, head
`20261116_112`.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T1 | PostgreSQL, targeted: the held-value module and the new module (a check before the full run) | 15 passed | first run | `V1-056-slice-10c-2b-4-targeted-test-run.txt` |
| U1 | backend unit, full (under `caffeinate -dims`) | 3663 passed, 1831 skipped, 1 warning (Starlette) | first unit run | `V1-056-slice-10c-2b-4-unit-test-run.txt` |
| P1 | PostgreSQL, full (under `caffeinate -dims`) | 1994 passed, 2 warnings (Starlette; the known pydantic `alias` warning) | first full run | `V1-056-slice-10c-2b-4-full-test-run.txt` |

## Review round 1 (2026-10-09; fresh read-only subagents, independent and security)

Independent: 0 blockers, 1 should-fix, 4 notes; it confirms the changed committed test (name kept,
every change forced by the new refusal, not weakened; changed assertions listed: the no-plan
refusal became the confirmed Credit-only correction, the Credit-plus-Pet-Refund correction became
the new refusal with nothing written, the Pet Deposit's 2,000 now come from the correction naming
Ed with the same audit check, and naming Ed again gives "nothing left" instead of "Deposit holds
nothing", which the new module now shows on its remaining path). Security: 0 blockers, 1
should-fix, 3 notes; no bypass of authorization, no injection, no data exposure.

- Security SF1: the `held_left` branch dropped the "pet damage first" guard the hold rule keeps
  (owner answer 3 (ii) to Q-2026-10-05-20): a correction limited to the Security Deposit could pay
  open pet damage while the Pet Deposit kept money. Fixed in the migration: while a Pet Deposit
  keeps held money the correction may not use and pet damage stays open after the Pet Deposit's
  step, no Security Deposit is used (55000, the existing message); plan-check test cases for both
  directions.
- Independent SF1 (and security N2): the known-limit text named only the empty-Deposit refusal;
  when held money is less than the value left (a correction naming no earlier correction settled
  it, then a later return brought money back), a correction naming the first may use the later
  return's money and naming the later one is then refused. Fixed as docs (docs/010, docs/004) and a
  test on that path; for the owner (see "For the owner").
- Independent N1: `PET_DAMAGE_RECLASSIFICATION` also settles every held balance; added to the
  known-limit list. The Credit-side sentence now says the earlier correction's own step also lowers
  what it left. Fixed (docs/010).
- Independent N2: "waits as before" was imprecise (the ordering is new; only step 5 is refused).
  Fixed (plan, docs/010).
- Independent N3: Credit before Deposits still fires while a Deposit holds money this correction
  may not use; written in docs/010; for the owner.
- Independent N4, security notes: tests added: a pre-112 Credit-form draft stale; a Deposit-form
  limit refusing use of a second Deposit; an amount above the 9e15 cap. Not added: a two-session
  concurrency test (the digest covers the value left and the held money, as in 10c-2b-3); drafts
  recorded under 110 can never be confirmed and must be withdrawn or rejected (docs/010 says they
  stay pending).

## Runs after the round-1 fixes

Static checks each in its own call (lint cause A correction 2 of 2, see Runs); migration-only check:
111 upgrades, head `20261116_112`.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T2 | PostgreSQL, targeted: the two held-value modules | 15 passed | round-1 code and test fixes | `V1-056-slice-10c-2b-4-targeted-test-run-2.txt` |
| U2 | backend unit, full (under `caffeinate -dims`) | 3663 passed, 1831 skipped, 1 warning | traceability notes changed | `V1-056-slice-10c-2b-4-unit-test-run-2.txt` |
| P2 | PostgreSQL, full (under `caffeinate -dims`) | 1994 passed, 1 warning | round-1 code fix (the pet-damage guard) | `V1-056-slice-10c-2b-4-full-test-run-2.txt` |

## Review round 2 (2026-10-09; fresh read-only subagents, independent and security; read while P2 ran)

Security: 0 blockers, 0 should-fix, 3 notes. Independent: 0 blockers, 1 should-fix, 3 notes. Both
found every round-1 item fixed or answered; the independent reviewer again confirmed the changed
committed test against HEAD.

- Independent SF1: the round-1 guard refused every Security Deposit use while pet damage stayed
  open and a Pet Deposit kept money; Security paying other debt does not break "pet damage first",
  and the broad guard can block both corrections. Fixed: the guard now refuses only a
  `SECURITY_DEPOSIT` step whose target is a pet-damage obligation (a Security Refund while that debt
  stays open is refused by the existing rule); a plan-check case shows a limited Security Deposit
  paying other debt while the pet damage stays open for the Pet Deposit. Security N1 had asked for
  a test of the broad form; the narrow form follows owner answer 3 (ii) to Q-2026-10-05-20 and the
  hold rule of 10c-2b-2a, both about the Security Deposit paying pet damage instead.
- The same reviewer's remaining case: with exact use, a Security correction and a Pet correction
  can each be refused (both Deposits hold other corrections' money, pet damage and other debt are
  open, the remaining Pet Deposit is a staff decision). A rule conflict: STOPPED, Q-2026-10-09-65.
- Security N2: the guard reads `v_pet_after_three` with `COALESCE` now. Security N3 and independent
  N2: the plan's tests bullet updated. Independent N1: the docs/010 Credit-side sentence reworded.
  Independent N3: noted (cause A allowance used up; the round-2 edits passed lint first time).

After the round-2 fix (code, tests, docs): static checks each in its own call clean; migration-only
check 111 upgrades.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T3 | PostgreSQL, targeted: the two held-value modules | 15 passed | round-2 guard narrowing and test | `V1-056-slice-10c-2b-4-targeted-test-run-3.txt` |

No unit or full PostgreSQL run after the round-2 fix: STOPPED for Q-2026-10-09-65 (an answer other
than (a) changes the code again). Round 3 and the commit wait for the owner.

## Owner answers to Q-2026-10-09-65 (2026-10-09) and the changes

Owner: (1) option (b), "at most": a correction may leave part of its earlier correction's value
held for a later correction naming the same earlier correction, must use some of it, and
BR-SETTLE-008 and the DL-032 order stay for every correction; tests for the Q-65 case in both
orders and for a Refund BR-SETTLE-008 refuses; (2) the narrow guard agreed (reason in docs/010);
(3) the Credit side kept, its known limit in docs/010; (4) the 10c-3b findings accepted. Recorded
in docs/010 and ops/V1_056_QUESTIONS.md.

- Code (migration `20261116_112`, not committed, changed in place): the exact-use refusal became
  "uses none of the value": a correction whose limit reaches held money and uses none of it is
  refused with the existing every-balance message; the over-limit refusal and every other rule
  stay.
- Tests (new module, now 7): test 1 rebuilt (a correction leaves 300 of the value held and a later
  one naming the same correction refunds it; none used refused; a Pet Refund while the charge stays
  open refused, BR-SETTLE-008); the plan-check test (200 now passes, an empty plan refused); new
  `test_the_q65_case_is_settled_in_either_order` on the plan check called directly, the state
  carried from one correction to the next (no fixture puts held Security Deposit money and open pet
  damage together after closure for real corrections).
- Docs: docs/004, docs/010 (entry wording, the guard reason, the Credit-side known limit as the code
  counts it), the plan, traceability (one entry added, two notes).

Static checks each in its own call: lint clean first time; format failed once (cause D, a missing
blank line between test functions after the insert; correction 1 of 2), then clean; type check
clean. Migration-only check: 111 upgrades, head `20261116_112`. Read-only search: only the two
held-value modules use the changed behaviour (`held_left`); no other test changes.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T4 | PostgreSQL, targeted: the two held-value modules | 16 passed | owner answer (b) and its tests | `V1-056-slice-10c-2b-4-targeted-test-run-4.txt` |
| U3 | backend unit, full (under `caffeinate -dims`) | 3663 passed, 1832 skipped, 1 warning | standing round-3 rule | `V1-056-slice-10c-2b-4-unit-test-run-3.txt` |
| P3 | PostgreSQL, full (under `caffeinate -dims`) | 1995 passed, 2 warnings (Starlette; the known pydantic `alias` warning) | standing round-3 rule | `V1-056-slice-10c-2b-4-full-test-run-3.txt` |

## Review round 3 (2026-10-09; standing round-3 rule, after U3 and P3; fresh read-only subagents)

Independent: 0 blockers, 0 should-fix, 4 notes. It confirms (b) is built exactly, the tests prove the
owner's cases and fail at HEAD and under the exact-use code, and the changed committed test is not
weakened. Security: 0 blockers, 1 should-fix, no money or authorization finding (no use beyond the
limit, no Refund while debt stays open, DL-032 order kept, no caller can set the limit, no new
SQLSTATE).

- Security SF1 (independent N1 and N2): stale text of the old exact-use rule in the new test
  module's docstring (line 6) and in three plan sentences (the Rule sentence, the plan-check bullet,
  the tests bullet). Text only.
- Independent N3: docs/010 says the limit is refused "together with `hold_deposits`"; the code
  refuses it only with `hold_deposits` true. Text only.
- Independent N4: the Q-65 two-order test shows the order through the plans the check accepts, not
  real balances; test 1 proves the write path of partial use (as recorded above).

STOPPED under the standing rule (a should-fix in round 3): Q-2026-10-09-67, recommendation (a): the
text fixes, static checks, one unit run, commit (owner exception as for Q-2026-10-07-44). Not
committed.

## Owner answers to Q-2026-10-09-67 (2026-10-09) and the commit

Owner: (1) option (a), the exception of Q-2026-10-07-44; (2) the Q-65 test in both orders on the
plan check called directly is accepted for now; a real-path version with real corrections recorded
and confirmed (not a state carried by hand from one step to the next) is a plan task that must be
done before 10h (ops/V1_056_PLAN.md, "Before 10h — a real-path test of the Q-2026-10-09-65
case"); (3) the docs/010 Credit-side wording is right because it matches the code; (4) after the
commit, the 10c-3b pre-code design, then a stop. Recorded in docs/010 and ops/V1_056_QUESTIONS.md.

- Text fixes only: the new test module's docstring (lines 6 to 9) and three plan sentences (the
  Rule sentence, the plan-check bullet, the tests bullet) now state "at most, must use some"; the
  docs/010 sentence says the limit is refused together with `hold_deposits` true. `git diff`
  against copies taken before the edits shows only those docstring and text lines changed.
- Static checks each in its own call: lint, format and type check clean.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U4 | backend unit, full (under `caffeinate -dims`) | 3663 passed, 1832 skipped, 1 warning | owner answer (a) to Q-2026-10-09-67 (text fixes) | `V1-056-slice-10c-2b-4-unit-test-run-4.txt` |

No PostgreSQL run after the text fixes (owner answer (a): no PostgreSQL test reads a module
docstring or the plan). Committed next (commit hash in ops/NOW.md).

## For the owner

- The Credit side does not count the debt it pays in the same way (owner check, not changed):
  docs/010 10c-2b-4 entry.
- Attribution when held money is less than the value left (independent SF1): a correction naming
  the first earlier correction may use money a later return brought back. A stricter attribution
  would change the counting of owner answer 1 to Q-2026-10-09-63; not changed.
- Corrections that name no earlier correction (`REFUND`, `REFUND_RETURN` with a new Refund,
  `PET_DAMAGE_RECLASSIFICATION`, a return-only Credit correction under the hold rule) still settle
  held money (BR-SETTLE-008); not changed.
