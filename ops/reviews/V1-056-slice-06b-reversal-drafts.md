# V1-056 sub-slice 6b — Lease Deposit forfeiture reversal drafts: reviews

Sub-slice: 6b (BR-AUTH-010, BR-DEP-019; owner answers to Q-2026-10-04-13 and Q-2026-10-04-14). Base: 4cfbc73. Status: built, under review; not committed.

## Built

Migration `20261019_84`: `app.lease_deposit_reversal_source` (internal), `app.record_lease_deposit_reversal_draft` (financial role; `deposits.correct`, changed from `deposits.dispose` and `deposits.correct` in round 1), `app.confirm_lease_deposit_reversal_draft` (financial role; only with the `financial.approve` reference; runs `app.reverse_deposit_disposition_v2` with the approver as actor), `app.financial_draft_resource_by_capability` and `app.list_financial_drafts_by_capability` (runtime role); the Lease forfeiture draft also refuses a Reservation draft's `outcome_id`. Service: `LeaseDepositForfeitureService.record_reversal` and `confirm_reversal`; `FinancialDraftService` reads by the prepare capabilities the reader holds. No HTTP route (the Lease reverse route still answers 409; draft routes in slice 11c). Moved notes from slice 6 round 3 handled (docs/010).

## Test runs

1. Backend unit suite: 3373 passed, 1582 skipped (database tests), exit 0 (ops/reviews/V1-056-slice-06b-unit-test-run.txt).
1. PostgreSQL full suite: 1735 passed, exit 0 (ops/reviews/V1-056-slice-06b-full-test-run.txt). No correction was needed.

Format, lint and type check clean (ruff format --check, ruff check, mypy: 272 files). Frontend unchanged.

## Round 1

Independent: 0 BLOCKER, 1 SHOULD-FIX, 8 NOTE. Security: 0 BLOCKER, 0 SHOULD-FIX, 3 NOTE. Security confirmed that no application role or PUBLIC can execute either reversal function; the only path is the new confirm under financial.approve.

SHOULD-FIX (independent): the same person prepared and confirmed, so the tests could not show that the reversal names the approver. Fixed: a second person confirms; the test checks the reversal row, the draft's preparer, the decision's decider and the audit event (actor, `deposits.correct`, correlation id = draft id).

Notes fixed: the reversal draft is prepared under `deposits.correct` only, as Option A of Q-2026-10-04-13 says (the first build also required `deposits.dispose`; the draft table's capability checks are relaxed to allow `deposits.correct` for `DEPOSIT_FORFEITURE`); confirm locks the Deposit row before the stale check (security note 2); a reversal id is also refused when an audit event uses it or a draft holds it as a disposition or outcome id (both reviewers); docs/010 wording ("any state", the audit naming outcome), docs/005 6b sentence, the missed ops/NOW.md stop line, the refusal traceability note; the reversal step of `test_disposition_reversal_and_exact_replay_keep_separate_observation_and_saved_result` moved to the draft path; a test that no application module uses the kind-only draft reads. Notes left as open items in ops/V1_056_PLAN.md slice 12 (they need the owner because they refuse more input or revoke): forfeiture-side and Reservation-side id collisions with audit ids and Lease reversal drafts; revoking the kind-only read functions.

Round 2 follows after one full unit run and one full PostgreSQL run.

## Test runs after round 1

2. Backend unit suite: 3374 passed, 1582 skipped (database tests), exit 0 (ops/reviews/V1-056-slice-06b-unit-test-run-2.txt). PostgreSQL full suite: 1735 passed, exit 0 (ops/reviews/V1-056-slice-06b-full-test-run-2.txt). Cause: the round-1 fixes (real changes), not a failure. Format, lint and type check clean.

## Round 2

Independent: 1 BLOCKER, 0 SHOULD-FIX, 5 NOTE. Security: 0 BLOCKER, 1 SHOULD-FIX, 2 NOTE. Both reviewers found the same defect (verified): the decision-table check `financial_draft_decision_shape` (migration 77) accepts a WITHDRAWN decision only with the six earlier prepare capabilities, so after the round-1 change (reversal drafts prepared under `deposits.correct`) the preparer cannot withdraw a reversal draft: `app.withdraw_financial_draft` fails with 23514 and the service reports "storage is unavailable". Reject by a `financial.approve` holder still works; no money can move through this. No test withdraws or rejects a reversal draft, so runs 1 and 2 did not show it. Security confirmed again that the only way to reverse a Lease forfeiture is the new confirm under financial.approve, and that the relaxed constraint opens no new path.

Notes: cross-flow refusal tested in one direction only (reversal confirm given a forfeiture draft, Reservation confirm given a reversal draft untested); read tests lack a `deposits.correct`-only and a `deposits.dispose`-only reader for reversal drafts; no concurrency test for one waiting reversal draft; the "Built" line above and one unit test name still say both capabilities; the reversal row and audit name the approver with `deposits.correct` (should be an owner item, not "closed"); the plan gives migration 84 also to slice 9; the read functions' bound of 7 equals today's number of prepare capabilities.

Under the takeover rules a blocker after round 2 stops the work: sub-slice 6b is STOPPED and NOT committed (Q-2026-10-05-15).

## Owner answer to Q-2026-10-05-15 (2026-10-05) and fixes

Yes to steps 1 to 4. Done: migration 84 also relaxes `financial_draft_decision_shape` (WITHDRAWN may carry `deposits.correct`); `FinancialDraftService` reports 23514 and 23505 as a conflict, not unavailable storage (unit test for the withdraw case); new database tests for withdraw by the preparer and its permission refusals, reject by an approver, new drafts after either, confirmation of a decided draft, both cross-flow directions, `deposits.correct`-only and `deposits.dispose`-only readers, and two reversal drafts at once; the unit test renamed to `test_reversal_needs_deposits_correct_and_approval_before_any_connection` (traceability id updated); the approver naming in the records is an owner item in slice 12; later migration numbers in the plan read "next free number".

## Test runs before round 3

3. Backend unit suite: 3377 passed, 1585 skipped (database tests), exit 0 (ops/reviews/V1-056-slice-06b-unit-test-run-3.txt). PostgreSQL full suite: 1738 passed, exit 0 (ops/reviews/V1-056-slice-06b-full-test-run-3.txt); its 3 warnings are the library warnings already seen in slice 6 run 5 (Starlette test client; pydantic field alias in two Credit/Refund API tests), not from 6b. Cause of the runs: the fixes for Q-2026-10-05-15. Format, lint and type check clean.

## Round 3

Independent: 0 BLOCKER, 0 SHOULD-FIX, 3 NOTE. Security: 0 BLOCKER, 0 SHOULD-FIX, 2 NOTE. As the owner asked, both reviewers listed every capability check for preparing, withdrawing, rejecting and confirming a reversal draft (table checks, database functions, services, routes); every place matches Option A of Q-2026-10-04-13: prepare under `deposits.correct` only, withdraw by the preparer with `deposits.correct`, reject and confirm under `financial.approve` only; no route prepares or confirms (the Lease reverse route answers 409). Security recomputed the final privileges: no application role or PUBLIC can reverse a Lease forfeiture or keep or move Deposit money without a draft confirmed under financial.approve; the relaxed checks open no path for other draft kinds; no permission or rule refusal reaches the user as unavailable storage.

Notes (no change in 6b): the 6b line in ops/NOW.md was stale (updated at the checkpoint); two cross-flow refusal tests are refused by an earlier guard than the one they name (behaviour still proven), and the `deposits.dispose`-only reader is checked with `get` but not `list`; the plan said "pending" Reservation draft while the code refuses any state (plan wording corrected, documentation only); the table checks bind the capability at kind level, the variant binding is in the functions (a tightening CHECK would need the owner); "forfeiture already reversed" and "reversal draft is stale" reach the user as "invalid" (as for a stale forfeiture in slice 6), not as a conflict.

Round 3 has no should-fix, so sub-slice 6b is committed (owner answer to Q-2026-10-05-15).
