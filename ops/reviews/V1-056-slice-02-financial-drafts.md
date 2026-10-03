# V1-056 slice 2 — financial.approve and drafts: reviews

Slice: 2 (BR-AUTH-010, BR-AUTH-008, BR-AUTH-009, DL-069). Reviewed diff base: f11e085. Commit: the slice 2 checkpoint commit that adds this file (hash recorded in ops/NOW.md). Work stopped after round 2; the owner approved Option A on 2026-10-03: fix all four round-2 findings and one extra review round for slice 2 only.

## Round 1 — independent review

1. Should-fix: kind not tied to prepare capability. Fixed: table CHECK and test.
2. Should-fix: no other-Property test. Fixed: new test for get, list, reject and withdraw through another Property id.
3. Should-fix: confirm record had no reference check. Fixed: `p_authorization_reference`, 42501 unless `financial.approve`; tested.
4. Should-fix: plan items not delivered. Answered in docs/010: confirm commands, stale-draft check, idempotent confirm and no-effect tests move to the kind slices.
5. Note: withdraw replay before reference check. Fixed.
6. Note: WITHDRAWN reference unrestricted. Fixed with a CHECK.
7. Note: any prepare capability reads all kinds. Fixed: reads filtered by kind.
8. Note: no concurrent-decision test. Accepted; added with the first confirm command.

## Round 1 — security review

1. Should-fix: confirm reference. Fixed (as above).
2. Note: kind/capability pairing. Fixed.
3. Note: reader breadth. Fixed.
4. Note: database trusts the asserted reference. Accepted existing design (capabilities are not stored in the database).
5. Note: withdraw ordering. Fixed.

## Round 2 — combined independent and security review

No blockers. All round-1 answers accepted and every fix judged correct. Remaining findings:

1. Should-fix: the new ordering fixes have no test (withdraw or reject repeated after a decision with a wrong reference must be refused; a correct repeat must replay).
2. Should-fix: no test that reject and withdraw refuse a blank, padded or missing reason (service: FinancialDraftInvalidError; database: 22023; no decision row).
3. Note: `app.confirm_financial_draft_record` does not take the draft kind; add `p_kind` and check it now.
4. Note: `FinancialDraftPage.after_prepared_at` and `prepare_capability` lack type checks (AttributeError or TypeError instead of FinancialDraftInvalidError).

Findings remained after round 2, so work stopped (takeover sections 4 and 6); see ops/V1_056_QUESTIONS.md. All four were then fixed under the owner's Option A: repeat-after-decision tests for reject and withdraw, reason tests (service and database), a draft-kind parameter on the confirm record, and input type checks.

## Verification so far

Targeted PostgreSQL runs: first run 31 passed, 1 failed (pin bump also rewrote the new test's own revisions; correction 1 of 2 for that cause); slice 2 file 7 passed; after round-1 fixes 8 passed, 1 failed (test assertion ignored that final_settlements.prepare also reads SETTLEMENT_CORRECTION drafts; correction 1 of 2 for that cause); then 9 passed. ruff check, ruff format and mypy clean.

## Round 3 — owner-approved extra round (slice 2 only)

Run before the round: one targeted PostgreSQL run, 65 passed (13 slice 2 tests and the full 52-test slice 1 set); full output in ops/reviews/V1-056-slice-02-round3-test-run.txt.

Independent review: no blocker, no should-fix. All earlier answers accepted; every check proven load-bearing by a test. Notes, answered:
1. "Deposit use" is not a draft kind yet. Answer: Pet Deposit use at Final Settlement is part of the FINAL_SETTLEMENT draft (slices 8 and 9). If slice 6 needs a separate kind, it widens the kind CHECK, the kind/capability CHECK and the kinds-array bound in a relaxing migration; recorded in docs/010.
2. Keyset paging is not tested across two pages. Answer: accepted; added with the draft list route in slice 11b.
3. Constraint errors from later kind commands would show as "Unavailable". Answer: accepted; each kind slice maps its own errors when its confirm command is added.

Security review: no blocker, no should-fix. Notes, answered:
1. The database trusts the asserted reference for callers holding the role credentials. Answer: accepted existing design (round 1, security note 4).
2. Withdraw reveals whether a draft id exists to a holder of a prepare capability (not-found before preparer check). Answer: accepted; ids are random UUIDs and the caller must already hold a prepare capability for the Property.
