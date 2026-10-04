V1-056 takeover rules for Claude Code
Version 1, written 2026-10-03. Owner: kompheak. Save in the repo as ops/V1_056_TAKEOVER.md.

V1-056 scope: Final Settlement, deposits, refunds and permanent correction history. Business rules: docs/010 DL-068 and DL-069, and docs/001, 002 and 003 as amended in commit 6732b8e.

Read order for every new session: AGENTS.md, ops/NOW.md, ops/V1_055_RUN_RULES.md, then this file. If this file and the run rules disagree, the stricter rule wins.

1. Start: plan first, then wait
Before any code, write ops/V1_056_PLAN.md:

the list of slices, in order, each small enough for one checkpoint commit;
for each slice: the rule IDs it covers, the migration (if any), the tests it will add, and whether it needs an independent security review (section 4);
every place where the rules are not clear enough to build. Write these as questions with your recommendation.
Suggested order (change it if you have a reason, and say why):

Lease End Date must be the last day of a month, and a test that no Rent is made after the End Date (BR-LEASE-031).
financial.approve capability and the draft-then-confirm model (BR-AUTH-010).
Unit cleaning rate and the move-out cleaning charge (BR-UNIT-014, BR-MOVEOUT-013).
Hand-back month rules: VOID if unpaid, keep if paid, credit Adjustment for the unpaid rest if partly paid (BR-RENT-030, BR-LEASE-021, BR-RENT-026).
Deposit forfeiture and Pet Deposit cases (BR-DEP-018, 019, 022, 023, 026, 027).
Wrong-Unit Payment move (BR-PAY-042).
Refund methods list and joint-Signer refund recipient (BR-REFUND-014, 015).
Final Settlement: draft, order (DL-032), confirm, debt on the Primary Tenant's Ledger (BR-SETTLE-*).
Post-settlement corrections: linked, never reopen, no time limit (BR-SETTLE-013).
HTTP routes and staff screens for slices 1 to 9.
Update docs 004 to 007, finish traceability for every new rule ID, final gates.
Commit the plan locally, then stop and wait for the owner to approve it. Unattended work starts only after the owner says the plan is approved.

2. What Claude Code may do alone (after plan approval)
Write code, migrations and tests for the approved slices, in order.
Additive or relaxing migrations only. A tightening change needs the owner.
Fix its own failing tests, lint, format and type errors inside the slice, within the routine allowance: at most 2 materially different corrections per distinct cause.
Make one local checkpoint commit per slice, with explicit paths and a secret and diff scan. Never commit failing or half-finished work. No amend.
Update ops/NOW.md with one line after each commit.
Add a short note to docs/010 for any narrowed historical test expectation, as the run rules say.
Use only existing capabilities plus financial.approve. Any other new capability needs the owner.
3. What Claude Code must never do
Push, open a PR, merge, rebase, force anything or change the remote.
Invent a business rule, fee, penalty, forfeiture or automatic action.
Change or delete a financial record. Corrections are always new linked records.
Use floats for money. Money is integer USD cents. Refunds are USD only.
Edit the first 1,598 traceability entries or any guard hash.
Skip, disable or weaken a test, lock, timeout, assertion or gate to get green.
Add packages, store photos, touch OpenClaw, user settings or any outside service.
Run make automation-test.
Search folders outside the repo.
4. Independent reviews
Every slice gets an independent read-only review before its commit:

Done by a fresh reviewer with no memory of writing the code (a new subagent), given only the diff, the rule IDs and this file.
It checks: matches the rules, append-only history kept, money in cents, capability checks on every new function and route, tests really prove the rule.
Every finding is fixed or answered in writing. After fixes, review again. At most 2 review rounds per slice. If findings remain after round 2, stop (section 6).
These slices also get a security review (/security-review or an equivalent fresh read-only reviewer): 2 (approval and capabilities), 5 (deposits), 6 (Payment move), 7 (refunds), 8 (settlement), 10 (HTTP and UI). It checks: deny-by-default, no way for Staff to confirm a draft, no SQL injection, no secrets or customer data in logs or responses, CSRF and session rules on new routes.

Save each review result in ops/reviews/ with the slice name and commit hash.

Standing rule added by the owner on 2026-10-04: If review round 2 has no blocker and at most 2 should-fix findings, Claude Code may do one round 3 without asking the owner. Round 3 must have no should-fix, or Claude Code stops. Before round 3, run the full backend unit suite and the full PostgreSQL suite once each.

5. Test runs
Follow the run rules: one targeted PostgreSQL run per sub-slice, after a read-only search of all backend tests for other affected tests. No retry.
Read and save the full unfiltered output to a file.
Every new rule ID gets a real test and a traceability entry in the slice that builds it. Twelve new IDs from DL-069 have no test yet; CI check TEST-118 fails until they do. That is one more reason not to push.
A known intermittent frontend test (TEST-FE-087, 128) failing once is recorded, not retried and not hidden.
6. Stop conditions
Stop the work, write the reason in ops/NOW.md and in ops/V1_056_QUESTIONS.md, and wait for the owner, when:

a business rule is missing, unclear or conflicts with another rule;
a change would need a tightening migration, a new capability (other than financial.approve), a new package, or a change to an earlier accepted migration;
the routine correction allowance for a cause is used up;
an independent or security review still has findings after round 2;
a test that passed before now fails and the cause is outside the slice;
the full PostgreSQL run or any gate fails at the final step;
anything would touch real customer data, secrets or production;
context is nearly full: finish and commit the slice only if green, update NOW.md, tell the owner to start a fresh session.
When stopped, do not start the next slice.

7. End of V1-056
When all slices are committed:

run the full gates once (backend, PostgreSQL, frontend, type check, lint, audit);
one final independent review of the whole V1-056 diff;
write a short report for the owner: slices and commits, rule IDs covered, review results, known issues, anything that needs a decision;
ask the owner for one push. Do not push before the owner says yes.
