# V1-056 slice 3a-2 — Deposit Refund to another Lease Signer: reviews

Slice: 3a-2 (BR-REFUND-015; owner answers to Q-2026-10-04-4). Base: f83fcbf. Commit: the slice 3a-2 checkpoint commit that adds this file (hash recorded in ops/NOW.md). The commit also carries the owner's run-rule update (ops/V1_056_TAKEOVER.md section 5) and the slice 12 open items in ops/V1_056_PLAN.md.

## Built

Migration `20261014_79`: append-only `app.refund_recipient_agreements`; a 14-argument `app.record_refund_draft` for a Pet Deposit Refund to another signed Signer with the written agreement; `app.create_pet_usd_refund_to_signer`; `app.assert_pet_refund_source` relaxed to accept a Signer only with a recorded agreement for the same Refund, Lease and Deposit; `app.confirm_refund_draft` writes the agreement first; `app.customer_ledger_effects` rebuilt from the revision 48 builders with Deposit Refunds and their corrections booked on the Deposit owner and `source_audit.paid_to_customer_id` when the recipient differs; upgrade refuses to run if any earlier Deposit Refund went to someone else. Service `record_pet_draft(..., recipient=SignerRecipient(...))`; `POST /refund-drafts` accepts `recipient_customer_id` with `signer_agreement`.

## PostgreSQL runs (full suite, owner run rule of 2026-10-04)

1. Before review: 1686 passed, 0 failed.
2. After round 1 fixes (guard, deposit match, zero-UUID checks, proof test): 1687 passed, 0 failed.
3. Before round 3 (standing rule): 1687 passed, 0 failed (ops/reviews/V1-056-slice-03a2-round3-full-test-run.txt).
Full backend unit suite before round 3: 3336 passed, 0 failed (ops/reviews/V1-056-slice-03a2-round3-unit-test-run.txt). No correction was needed for a failing run.

## Round 1

Independent: 2 should-fix (earlier ledger results not enforced; no proof test), 3 notes. Security: 4 notes. Fixed: upgrade guard, proof test (test renamed to match what it checks), Deposit match in the agreement check, zero-UUID checks. Accepted in writing: free-text agreement (approver sees it, slice 11c), paid-to id on the owner's ledger behind existing ledger capabilities, agreement in draft payload behind draft read capabilities (docs/008 in slice 12), agreement written before replay check (fails closed).

## Round 2

Security: no findings. Independent: 1 should-fix (traceability note claimed the upgrade guard is tested), 3 notes. Fixed: note wording, confirm replay test with one agreement row, zero-UUID checks for source and review. Open item: unsigned-Signer test (slice 12 list).

## Round 3 (standing rule: round 2 had no blocker and one should-fix)

Combined independent and security review: no blocker, no should-fix. Notes: no test for a correction of a Signer-paid Deposit Refund (added to the slice 12 list); traceability wording for the earlier-shape test overstated Credit coverage (wording corrected).
