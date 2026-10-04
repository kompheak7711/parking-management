# V1-056 slice 3a-1 — Refund methods and Refund drafts: reviews

Slice: 3a-1 (BR-REFUND-014, BR-AUTH-010, BR-AUTH-008; owner answer to plan Q6 and Q-2026-10-03-2). Base: f085ffb. Commit: the slice 3a-1 checkpoint commit that adds this file (hash recorded in ops/NOW.md). Work stopped after round 2; the owner approved Option A on 2026-10-04 (fix the should-fix and four notes, run both full suites, one round 3).

## What was built

Migration `20261013_78`: `app.refund_methods` (seeded Cash and Bank transfer; `property.manage` adds or turns off), Refund drafts for Credit, Payment and Pet Deposit Refunds (`app.record_refund_draft`, `app.confirm_refund_draft`), append-only `app.refund_draft_details` (method and reference note per Refund), direct EXECUTE on `app.create_usd_refund` and `app.create_pet_usd_refund` revoked from the financial role. Service `RefundService.record_usd_draft`, `record_pet_draft`, `confirm_draft`, `refund_methods`. Routes `POST /refund-drafts` and `POST /properties/{property_id}/refund-drafts/{draft_id}/confirm` (brought forward from slice 11c); old `POST /refunds` answers 409 `REFUND_DRAFT_REQUIRED`. Old tests converted through `tests/refund_test_support.py`; narrowings listed in docs/010.

## Round 1

Independent: 3 should-fix, 5 notes. Security: 4 notes. All fixed or answered (Pet stale check, replay before state checks, no Location header, draft id scoped by Property, person, kind and key, key-reuse guard, extra tests, docs).

## Round 2

Security review: no blocker, no should-fix; all round-1 answers accepted. Notes: global method list under any Property's `property.manage` (accepted round-1 item, for slice 11c); Reservation Refunds still direct (slice 3b, owner answered); confirm should check `variant IN ('USD','PET')` explicitly; unused Idempotency-Key on confirm (documented).

Independent review: no blocker, one should-fix, four notes.

1. Should-fix: a Payment Refund draft can also go stale when a Rent Invoice or Late-payment Charge of the payer becomes outstanding after drafting; the existing eligibility check then raises 23514, which the service maps to 503 "outcome unresolved" instead of the 422 that docs/005 promises. Proposed fix: run `app.assert_payment_excess_eligible` before `app.create_usd_refund` and turn its failure into P5202; add a test (draft, unpaid Invoice for the payer, confirm gives 422, draft stays pending).
2. Note: a Pet draft whose source is no longer qualified gets 404 (P5201), not 422.
3. Note: the database does not itself check `source_kind IN ('PAYMENT','CREDIT')` (Python does).
4. Note: recording does not check the available amount or eligibility, so a draft that can never be confirmed still gets 201.
5. Note: the reference-note length bounds are proven only in Python, not by a direct database call.

A should-fix remains after round 2, so work stopped (takeover section 6). See ops/V1_056_QUESTIONS.md Q-2026-10-04-3.

## Verification

Full PostgreSQL suite: run 1 failed at migration (PL/pgSQL `IF ... CASE ... THEN` syntax; correction 1 of 2); run 2: 17 failed (HTTP tests used the closed route; confirm replay returned the current Refund instead of the original response); run 3: 8 failed (confirm route required a JSON body; missing cache header); after fixes the HTTP file passed (20 of 20); after round-1 fixes the full suite passed: 1676 passed, 0 failed (ops/reviews/V1-056-slice-03a1-full-test-run.txt). Backend unit tests: refund-related 784 passed; traceability test passed; ruff check, ruff format and mypy clean. `make backend-test` before the round-1 fixes: 3329 passed, 5 failed (later fixed: financial-context case 23 and traceability); not re-run in full after the round-1 fixes.

## Round 2 fixes (owner Option A)

Payment eligibility checked before the Refund is created; new unpaid Invoices or Late-payment Charges of the payer make the draft stale (422, stays pending). Explicit kind, capability and variant check at confirmation; `source_kind` checked in the database; a Pet source no longer qualified gives 422; direct database tests for the note length and source kind. Not taken: an availability check at recording (confirmation stays the authoritative check).

## Round 3 — owner-approved

Runs before round 3: full backend unit suite run 1: 3334 passed, 1 failed (traceability check; the new tests were not yet traced because I ran the suite before adding their entries); run 2: 3335 passed, 0 failed (ops/reviews/V1-056-slice-03a1-round3-unit-test-run.txt). Full PostgreSQL suite: 1682 passed, 0 failed (ops/reviews/V1-056-slice-03a1-round3-full-test-run.txt).

Independent review: no blocker, no should-fix. Notes, answered: (1) a confirmed Refund records the approver as `processed_by` with the existing reference `refunds.create`; the preparer and the `financial.approve` decision are in the draft tables. Recorded in docs/010; changing the Refund row would need a relaxing change to the earlier trigger and is not needed for the audit trail. (2) The Pet "no longer qualified" path has no test; it will be added when a later slice gives the fixture a legitimate way to remove a qualification.

Security review: no blocker, no should-fix. Notes, answered: (1) a future second 23514 source inside the eligibility check would be reported as stale; accepted, the function raises 23514 in one place today. (2) Global method list: slice 11c (owner-level check and activation history). (3) Unused Idempotency-Key and body on confirm: documented in docs/005.

The two Refund draft routes were moved forward from slice 11c into this slice and were inside both security review rounds 1 to 3.
