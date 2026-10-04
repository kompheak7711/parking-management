# V1-056 slice 5 — Hand-back month Rent Invoices: reviews

Slice: 5 (BR-RENT-030, BR-RENT-026 with the Q-2026-10-04-9 amendment, BR-RENT-024, BR-LEASE-021, BR-MOVEOUT-010; owner answers to Q-2026-10-04-8 and Q-2026-10-04-9). Base: b086992 plus 9a7e288 (BR-RENT-026 amendment). Status: committed after review round 3 (no should-fix). Commit: the slice 5 checkpoint commit that adds this file (hash recorded in ops/NOW.md).

## Built

Migration `20261017_82`: internal `app.hand_back_rent_invoice_basis`; `app.hand_back_rent_invoice_assessment` (runtime role, `invoices.read` and `leases.read`; no Lease, Customer, move-out or date identities); `app.resolve_hand_back_rent_invoice` (financial role; `invoices.void` for VOID, `invoices.adjust` for CREDIT_ADJUSTMENT; reason, expected action, expected version and expected outstanding amount); append-only `app.hand_back_rent_resolutions` with insert validation, VOID event id, Adjustment ids and its own audit event. Service methods in `invoice.py`. No HTTP route (slice 11a).

## Test runs

Backend unit suite: 3348 passed, 1 failed (sed slip, fixed) before review; 3349 passed after the round-1 fixes (ops/reviews/V1-056-slice-05-unit-test-run.txt). Format, lint and type check clean.

PostgreSQL (full suite):

1. 5 failed, 1709 passed (ops/reviews/V1-056-slice-05-full-test-run.txt). Causes: (a) the fixture Lease was signed at the real clock, and a physical move-out may not precede the signing date — correction 1: a local fixture signs the Lease and signer on 20 June 2026 (precedent tests/test_move_in_migration.py); (b) the head-revision sed also changed the new test's expected down_revision — correction 1.
2. 1714 passed (ops/reviews/V1-056-slice-05-full-test-run-2.txt).
3. After the round-1 fixes: 1 failed, 1714 passed (ops/reviews/V1-056-slice-05-full-test-run-3.txt). Cause: the second per-line credit Adjustment was refused because `app.adjust_invoice` ends with `SET CONSTRAINTS ALL IMMEDIATE`, which stays in force, so the next call's deferred check ran before its own Invoice update — correction 1: `SET CONSTRAINTS ALL DEFERRED` before each call (precedent migrations 39 and 41).
4. 1715 passed (ops/reviews/V1-056-slice-05-full-test-run-4.txt).

## Round 1

Security: no blocker; 2 SHOULD-FIX: (1) Lease not locked, so a move-out correction could change the basis during the command — fixed (Lease `FOR SHARE NOWAIT`); whether to refuse a later move-out correction is left to the owner (changes the move-out rules); (2) Lease, move-out and date identities shown to `invoices.read` holders — fixed by removing them from the assessment and the response (no new capability). Notes fixed: derived keys and digests from the hand-back request; own VOID event and Adjustments verified; per-key advisory lock; expected outstanding bound; ambiguous current move-out refused; tests for unknown Property, disabled account and key reuse on another Invoice.

Independent: no blocker; 5 SHOULD-FIX, all fixed: per-key advisory lock; Lease lock; exact status assertions; a two-line partly paid case (Rent and Trash both adjusted); tests that the current move-out date counts, not the termination date, including a corrected move-out record. Notes: audit event, VOID event id and insert validation added; the 24th tested; disabled account tested; refusal messages asserted; verification evidence recorded above. Accepted: no concurrency test; the assessment shows VOID even when `app.void_invoice` will refuse (earlier Adjustment or Late-payment Charge), staff then use the existing commands (docs/010); KEEP shares SQLSTATE 22023 with invalid input (the plan says "fully paid refused"); no notice-date test (the termination context fixture has no notice date; the code reads only the move-out record).

Open item noticed (not in this slice): migration `20261005_70` calls `app.adjust_invoice` in a loop the same way and may fail when more than one line needs a credit Adjustment — recorded for the owner as Q-2026-10-04-10 with the move-out correction question.

## Round 2

Security: no blocker; 1 SHOULD-FIX: the assessment still reveals the termination basis and move-out window to an `invoices.read` holder — fixed by also requiring `leases.read` for the assessment, as the existing termination Invoice readiness read does (the command keeps `invoices.void` / `invoices.adjust`). Notes: the Adjustment source reference showed the move-out id — now `hand-back-rent-resolution:<id>`; derived keys, constraint deferral, actor checks and lock order confirmed sound.

Independent: no blocker; 1 SHOULD-FIX: no notice-date test (plan and BR-RENT-030) — added `test_hand_back_ignores_the_notice_date` with a recorded notice dated 26 August and a move-out on 3 August (August covered, September not). Notes: the second-resolution check now uses the current version and asserts the exact conflict type; BR-RENT-009 removed from the traceability entry; migration 70 item moved to Q-2026-10-04-10 and NOW.md; least-privilege test depth and the zero-outstanding VOID case accepted.

Two SHOULD-FIX in total and no blocker, so round 3 follows under the standing rule. Runs before round 3: backend unit suite 3349 passed (ops/reviews/V1-056-slice-05-round3-unit-test-run.txt); full PostgreSQL run 5: 1716 passed (ops/reviews/V1-056-slice-05-round3-full-test-run.txt).

## Round 3 (standing rule; last round)

Independent: 0 BLOCKER, 0 SHOULD-FIX, 8 NOTE. Security: 0 BLOCKER, 0 SHOULD-FIX, 5 NOTE. All round 1 and 2 fixes confirmed. Notes acted on before commit (wording only, no code or test change): docs/010, a migration SQL comment and this record now say the assessment needs `invoices.read` and `leases.read`; the migration 70 item goes into the ops/NOW.md line. Notes accepted: an `invoices.void` / `invoices.adjust` holder can still infer coverage from the command's refusal or `coverage` field (owner-approved command capabilities; consider in the slice 11a error mapping); the Adjustment reference shows that a hand-back resolution happened; audit rows keep the Lease and move-out ids (audit view needs its own capability); the insert trigger does not re-check that the move-out record is current (only the definer function inserts); P5406/P5401 from the readiness scope check are unmapped but unreachable; the plan's "4th" VOID case is covered by the 3rd (VOID) and the 4th (partly paid) with the 5th refused; the stale-action test catches the parent conflict class; least-privilege test depth; no ambiguous move-out or concurrency test; constraint deferral confirmed sound.
