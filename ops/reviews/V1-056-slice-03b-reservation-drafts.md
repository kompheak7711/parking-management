# V1-056 slice 3b — Reservation Deposit drafts: reviews

Slice: 3b (BR-AUTH-010, BR-RES-016, BR-RES-020, BR-RES-021, BR-RES-022, BR-REFUND-014, BR-REFUND-015, BR-DEP-018; owner answers to Q-2026-10-03-2). Base: e949935. Status: committed after the owner's answer to Q-2026-10-04-6. Commit: the slice 3b checkpoint commit that adds this file (hash recorded in ops/NOW.md).

## Built

Migration `20261015_80`: relaxed outcome-complete trigger (a cancelled Reservation may wait with no outcome record; revision-41 guard kept); `app.cancel_reservation_v3`, `app.expire_reservation_v3` (lifecycle and Unit release only); `app.record_reservation_deposit_draft`, `app.record_reservation_deposit_correction_draft`, `app.confirm_reservation_deposit_draft`; `app.list_reservations_awaiting_deposit_decision`; receipt reversal refused while a Deposit waits; partial expression index on draft `reservation_id`; financial role loses the four one-call functions. Service `reservation_deposit_draft.py`; routes for drafts, correction drafts, confirm and the waiting list; retired routes answer 409 `RESERVATION_DEPOSIT_DRAFT_REQUIRED`; worker never forfeits; Reservation screen cancel form without outcome fields.

## PostgreSQL runs (full suite)

1. Before review: all DB tests errored — PL/pgSQL `IF ... IS DISTINCT FROM CASE ... THEN` syntax (migration never applied). Correction 1 for that cause.
2. 131 failed — replaced trigger lost the revision-41 guard for non-Reservation Refunds (NoDataFound); one KeyError from a narrowed test. Correction 1 for each cause.
3. 1694 passed, 0 failed.
4. After round 1 fixes: 1 failed — receipt-reversal guard too broad (blocked the earlier unwind after a fully corrected Reservation Refund). Correction 1 for that cause.
5. 1697 passed, 0 failed (output file ops/reviews/V1-056-slice-03b-full-test-run.txt is not in the working tree at commit time; the round-3 run outputs are).
Backend unit suite: 3341 passed (before round 1 fixes; API unit tests rerun after). Frontend: 1586 passed; build clean.

## Round 1

Independent: no blocker; 2 should-fix (key reuse untested; stale test reached the wrong check), 8 notes. Security: no blocker; 2 should-fix (reversed receipt could strand a waiting Deposit; confirm Idempotency-Key not stored), 4 notes. Fixed: receipt-reversal guard; key-reuse tests (DB and HTTP); stale test replaced and stale check marked defensive; index; list numbering after LIMIT; two-person confirm and concurrent one-pending tests; docs/002 amendment lines; docs/010 notes. Answered in writing: confirm key not stored (same contract as slice 3a API-065); database trusts the financial.approve reference (slice 2 design); preparer may confirm with financial.approve (owner answer Q4).

## Round 2

Security: no blocker; 1 should-fix (isolation and privilege tests missing), 5 notes (approval string trusted; slice 3a replay branch could filter on prepare capability; error-response Cache-Control path list; draft reads check only active actor; stale check can fire on a later receipt). Independent: no blocker; 3 should-fix (AWAITING_DECISION shown for earlier zero-effect outcomes; cancel with a pre-reversed receipt now succeeds; a bad pending draft blocks the Reservation until slice 11b routes), notes. Four should-fix exceed the standing round-3 allowance, so the work stopped (Q-2026-10-04-5).

## Owner answers (Q-2026-10-04-5) and round-2 fixes

Option A approved. Fixed: isolation and privilege tests; AWAITING_DECISION only when a Deposit is held and no outcome record exists; no held Deposit means not waiting and not listed; receipt reversal refused only while a Reservation Deposit draft is pending (guard narrowed); reject and withdraw for Reservation Deposit drafts brought forward from slice 11b (plan Q5 rules; route, service and database checks; no money moves). Revoke of the four one-call functions approved as an exception (docs/010).

Runs before round 3: backend unit suite 3343 passed (ops/reviews/V1-056-slice-03b-round3-unit-test-run.txt); full PostgreSQL run 6: 1701 passed, first try (ops/reviews/V1-056-slice-03b-round3-full-test-run.txt).

## Round 3 (owner exception; last round)

Independent: no blocker. Check A (replaced functions vs previous versions incl. revision 41 and 38 patches): no guard lost; only the intended additions. Check B (narrowed tests): all follow a real rule change. 1 SHOULD-FIX: docs/010 "Updated tests (V1-056 slice 3b)" sentence still says the receipt reversal is refused "while a cancelled Reservation's Deposit has no outcome record" (round-1 guard); notes (read inlines the held/outcome test; variable name; plain CREATE INDEX lock).
Security: no blocker. Check A: no guard lost, SECURITY DEFINER, search_path and ACLs kept. Check B: no narrowing hides a security regression. Same SHOULD-FIX (also: the sentence says "three retired functions", four are retired); notes (Cache-Control on error responses of the list path; partly reversed receipt listed but undraftable — impossible with one receipt per Reservation; 403/404 existence pattern; confirm key not stored; trust-model items).

Result: round 3 has a should-fix, so slice 3b is NOT committed (owner rule: no round 4).

## Owner answer (Q-2026-10-04-6, 2026-10-04)

Yes. The docs/010 "Updated tests (V1-056 slice 3b)" note now carries the exact receipt-guard sentence from Q-2026-10-04-6, and says that `test_financial_history_is_append_only_and_runtime_is_least_privilege` checks three of the four retired functions and that `test_reservation_deposit_draft_roles_and_retired_one_call_paths` in `tests/test_reservation_deposit_draft_migration.py` checks the fourth. No code or test change, no new run and no new review (owner instruction). The three round-3 notes (Cache-Control on waiting-list error responses, the inline held/outcome check in the Reservation read, the plain CREATE INDEX lock) are in the slice 12 open list in ops/V1_056_PLAN.md.
