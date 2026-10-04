# V1-056 slice 6 — Lease Deposit forfeiture drafts: reviews

Slice: 6 (BR-DEP-018, 019, 022, 023, 026; BR-AUTH-010; BR-LEASE-005; owner answers to Q-2026-10-04-10 and Q-2026-10-04-11). Base: 634536b. Status: owner answered Q-2026-10-04-12 and Q-2026-10-04-13 (Option A both); round-1 fixes done; review round 2 below; not committed.

## Built

Migration `20261018_83`: forfeiture drafts for Lease Deposits (`app.lease_deposit_forfeiture_source`, `app.record_lease_deposit_forfeiture_draft`, `app.confirm_lease_deposit_forfeiture_draft`); two more approved grounds (`BR-LEASE-025`, `BR-LEASE-028`) and `BR-LEASE-005` also after move-in in the existing disposition context check; the never-moved-in unpaid-Initial resolution no longer forfeits and defers constraints before each credit Adjustment; `app.physical_move_out_record` refuses a correction that a hand-back resolution relies on (P5N06). Service `lease_deposit_forfeiture.py`; `PhysicalMoveOutResolutionReliance` in `physical_move_out.py`. No HTTP route (none existed for Lease dispositions; draft routes in slice 11c).

## Test runs (PostgreSQL, full suite)

1. 14 failed, 1703 passed (ops/reviews/V1-056-slice-06-bug-first-run.txt). Not valid evidence: the migration and tests were changed while the run was in progress (process error), and the new two-line test assumed two Initial Invoice lines (there are three: Rent and two Trash lines) — test correction 1.
2. Bug-first run with every slice 6 change except the loop fix: 5 failed, 1719 passed (ops/reviews/V1-056-slice-06-bug-first-run-2.txt). The two-line test failed with `CheckViolation: Invoice Adjustment would violate the issued obligation` inside `app.adjust_invoice` called by `app.resolve_unpaid_initial_never_moved_in` — the bug (Q-2026-10-04-10 a). Four other failures were test fixture errors: termination two days after move-in ("Termination chronology is invalid") and a wrong response key — test correction 1 each.
3. Loop fix restored: 1 failed, 1723 passed (ops/reviews/V1-056-slice-06-full-test-run-3.txt). The two-line test passes. The pet-noncompliance test's Pet Deposit held nothing ("The Deposit holds nothing to forfeit") — test correction 1: a Pet Deposit receipt is recorded first.
4. 1724 passed (ops/reviews/V1-056-slice-06-full-test-run-4.txt). Backend unit suite: 3350 passed (ops/reviews/V1-056-slice-06-unit-test-run.txt). Format, lint and type check clean.

Known gap: acceptance of the BR-LEASE-028 ground (with a recorded Serious Default event) is not tested; only its refusal without the event is.

## Round 1

Independent: 1 BLOCKER, 4 SHOULD-FIX, 7 NOTE. Security: 1 BLOCKER, 3 SHOULD-FIX, 6 NOTE. Shared BLOCKER: the financial role still executes the direct Lease disposition functions and `record_disposition` still forfeits at once without a draft (BR-AUTH-010, plan Q6); closing it is a tightening change (revoke), so the work stopped (Q-2026-10-04-12). SHOULD-FIX (to fix before round 2): positive tests for BR-LEASE-025, BR-LEASE-028 with a Serious Default event and BR-LEASE-005 after move-in; stale, key-reuse, disposition-id-reuse, wrong-Property and wrong-Deposit tests; least-privilege test for the revoked grants; service refuses before any connection (unit test); P5801/23P01 mapped to a conflict; `if amount > 0` turned into an assertion; docs/010 run reference corrected (done). Notes: BR-LEASE-025 branch does not re-verify the warnings (termination already did); the disposition audit names `deposits.dispose` with the approval in the draft decision; `resolve_never_moved_in` still asks for `deposits.dispose`; database trusts the passed authorization text (existing draft pattern); cleaning charge also references a move-out record (owner note in Q-2026-10-04-12); missing index on `payload->>'deposit_id'`; P5N06 message passed through (map in the route slice); Pet refusal reasons share one error class in one test; no unit tests for the new service module.

## Owner answers and round-1 fixes (2026-10-04)

Q-2026-10-04-12 Option A and Q-2026-10-04-13 Option A (docs/010): migration `20261018_83` revokes the financial role's EXECUTE on `app.record_lease_deposit_disposition`, `app.record_lease_deposit_disposition_with_context` and `app.reverse_deposit_disposition_v2`; `record_disposition` and `reverse_disposition` refuse with `LeaseDepositDraftRequired`; the Lease reverse route answers 409 `LEASE_DEPOSIT_DRAFT_REQUIRED`; the ledger offers `can_reverse` for no disposition; the reversal draft follows in sub-slice 6b. Tests narrowed per docs/010 ("Updated tests (V1-056 slice 6)"): real draft path where the test's subject is the forfeiture, owner helper (`tests/lease_deposit_forfeiture_test_support.py`) for setup, earlier revisions, the migration 58 function guards and reversals until 6b. Round-1 should-fix items fixed (positive tests for BR-LEASE-025, BR-LEASE-028 with a Serious Default event and BR-LEASE-005 after move-in; refusal test; least-privilege test with the revoked grants; unit tests `tests/test_lease_deposit_forfeiture.py`; P5801 and 23P01 mapped to a conflict; `if amount > 0` turned into an assertion). docs/005 API-042 amended.

Read-only search (Q-2026-10-04-13): no other grant or service method keeps or moves Security, Pet or Reservation Deposit money without a draft and an approver (list in ops/V1_056_QUESTIONS.md, Q-2026-10-04-13).

## Test runs after the owner answers

5. Backend unit suite: 3368 passed, 1576 skipped (database tests), exit 0 (ops/reviews/V1-056-slice-06-unit-test-run-5.txt). PostgreSQL full suite: 1 failed, 1727 passed (ops/reviews/V1-056-slice-06-full-test-run-5.txt). Cause: test error in the new `test_unpaid_initial_security_is_forfeited_also_after_move_in`; it recorded a draft and then called a helper that records a second draft for the same Deposit, which the database correctly refused ("A forfeiture draft for this Deposit is already waiting"). Test correction 1 for this cause: confirm the draft already recorded.
6. PostgreSQL full suite: 1728 passed, exit 0 (ops/reviews/V1-056-slice-06-full-test-run-6.txt). The unit suite was not rerun: the correction changed only a database test, which the unit suite skips.

Format, lint and type check clean (ruff format --check, ruff check, mypy: 271 files).

## Round 2

Independent: 0 BLOCKER, 1 SHOULD-FIX, 9 NOTE. Security: 0 BLOCKER, 0 SHOULD-FIX, 4 NOTE. Security confirmed the round-1 blocker closed: no application role (runtime, financial, bootstrap, PUBLIC) can forfeit or reverse a Lease Deposit forfeiture or otherwise keep or move Deposit money without a draft confirmed under financial.approve.

SHOULD-FIX (independent): the wrong-Property case uses an unknown Property id and so never reaches the Deposit and draft Property checks. Answered in writing: the schema holds one Property (`properties_singleton_key_unique`), so a second real Property cannot exist; any other Property id is unknown and refused first (P4501), as in the slice 3b isolation tests. The test now says so; the Property checks stay as defence.

Notes taken (no rule change): draft reason check equals the confirmation's (`app.lease_notice_text_valid`); a disposition id held by any forfeiture draft is refused for a new draft; neutral Pet refusal message (BR-DEP-024, BR-DEP-027); P5N06 labelled as an owner-approved tightening; docs/005 receipt-only sentence; the unpaid-Initial narrowed test asserts the held amount unchanged; new tests: Serious Default event of another Lease, two concurrent drafts for one Deposit, reserved disposition id, newline reason, 403 without CSRF on the Lease reverse route; Q-2026-10-04-13 marked answered. Notes left (docs/010): BR-LEASE-028 date boundary untested; database trusts the passed authorization text (existing draft pattern); disposition audit names deposits.dispose with the approver as actor (revisit in 6b); one person may prepare and confirm (plan Q4).

Round 2 has no blocker and one should-fix, so one round 3 follows under the standing rule, after one full unit run and one full PostgreSQL run.

## Test runs before round 3

7. Backend unit suite: 3368 passed, 1577 skipped (database tests), exit 0 (ops/reviews/V1-056-slice-06-unit-test-run-7.txt).
8. PostgreSQL full suite: 1729 passed, exit 0 (ops/reviews/V1-056-slice-06-full-test-run-8.txt).

## Round 3

Security: 0 BLOCKER, 0 SHOULD-FIX, 2 NOTE. Final EXECUTE privileges recomputed from every migration: no application role or PUBLIC can forfeit, reverse a forfeiture or otherwise keep or move Deposit money without a draft confirmed under financial.approve. Notes: (1) the disposition-id reservation does not cover Reservation drafts, which carry the future disposition id as `outcome_id`; a clash only makes the later confirm fail safely (23505); (2) draft reads are filtered by kind only; a holder of only one dispose capability could read the other family's forfeiture drafts once the draft read service gets a route (slice 11b/11c).

Independent: 0 BLOCKER, 1 SHOULD-FIX, 5 NOTE. The wrong-Property answer was judged sound; no weakened assertion; every docs/010 per-test note matches the code.

SHOULD-FIX (independent, verified): the staff screen still says the never-moved-in unpaid-Initial resolution forfeits the Security Deposit (`frontend/src/LeaseManagement.tsx:620` confirm dialog, `:1499` description), and docs/004 line 293, docs/006 lines 343 and 740 and docs/007 line 736 say the same. Migration 83 removed that forfeiture; the resolution route is live since V1-055 9c, so staff would confirm a dialog promising a forfeiture that no longer happens while the Deposit stays held. No frontend test asserts these strings.

Notes: (1) as security note 1; docs/010 and this record overstate the reservation ("any DEPOSIT_FORFEITURE draft"); (2) the disposition-id check is not serialized across Deposits and has no index (later confirm fails safely); (3) the "already recorded disposition" refusal is not tested on its own; (4) ops/NOW.md last line stale; (5) the "Known gap" line in this record (BR-LEASE-028 acceptance untested) is now closed by `test_thirty_day_default_ground_forfeits_with_a_recorded_serious_default_event`.

Under the standing rule round 3 must have no should-fix, so slice 6 is STOPPED and NOT committed (Q-2026-10-04-14).

## Owner answer to Q-2026-10-04-14 (2026-10-04)

Option A, text and docs only: the two never-moved-in screen strings in `frontend/src/LeaseManagement.tsx` and the passages in docs/004, docs/006 (two) and docs/007 now say the Security Deposit stays held until a forfeiture draft is confirmed; new frontend test TEST-FE-671 (traceability entry appended). Backend runs 7 and 8 stand (no backend file changed). The round-3 notes (Reservation `outcome_id` clash, test for an id used only by a recorded disposition, stale status lines including the "Known gap" line above) and the draft-read filter note move to sub-slice 6b (ops/V1_056_PLAN.md). The owner accepted the owner helper for tests of the migration 58 function's own checks.

Frontend checks once (ops/reviews/V1-056-slice-06-frontend-checks.txt): format, lint and type check clean; 38 files, 1587 tests passed (TEST-FE-671 included); build passed (existing chunk-size warning only). Backend `tests/test_traceability.py` (it reads the frontend test IDs): 28 passed.
