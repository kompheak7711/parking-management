# V1-056 slice 1 — Lease End Date is a month end: independent review

Slice: 1 (BR-LEASE-031, BR-LEASE-013, DL-069). Reviewed diff base: 4236a86. Commit: the slice 1 checkpoint commit that adds this file (hash recorded in ops/NOW.md).
Reviewers: two fresh read-only subagents, given only the diff, the rule IDs and ops/V1_056_TAKEOVER.md. No security review required for this slice.

## Round 1

No blockers. Every database path that creates, changes or signs a Lease End Date is covered; no table constraint; no existing row changed; grants and SECURITY DEFINER kept; fixtures change only inputs and head pins; traceability only appended.

1. Should-fix: negative tests did not pin the failure cause (the service maps several SQLSTATEs to one error). Fixed: each negative case asserts the database message.
2. Note: the no-Rent-after-End-Date test also passes without migration 76. Answer: intended; DL-069 asks for a test of existing billing behavior. Cause now pinned.
3. Note: the API shows only "Lease command is invalid". Answer: deferred to slice 11a (HTTP error and form validation), as the approved plan lists.
4. Note: the migration anchors depend on exact function text. Answer: accepted; the migration fails when an anchor is not found exactly once.

## Round 2

No blockers, no should-fix. Round-1 fix verified (errors are raised `from exc`, so the cause is the psycopg error). All round-1 answers accepted.

1. Note: `date_trunc('month', date)` uses the session time zone implicitly. Answer: not changed. The result is the same calendar date in every time zone, and a change now would need a third review round, which the takeover rules do not allow.
2. Note: the replay-before-check order is proven only by source position, not by replaying a pre-migration command. Answer: accepted as is; the catalog test proves the order in each function body.

## Verification

Targeted PostgreSQL run: 51 passed, 1 failed (test-only signature spelling, `timestamptz` printed as `timestamp with time zone`; correction 1 of 2). New test file rerun: 4 passed; after the round-1 fix: 4 passed. ruff check, ruff format --check and mypy: clean.
