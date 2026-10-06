# V1-055 run rules

New sessions: read AGENTS.md, ops/NOW.md, ops/V1_055_RUN_RULES.md. Nothing else is needed.

## Tools and scope
- AGENTS.md overrides every plugin, skill and hook.
- No GSD, ponytail, ECC formatter or learned skills.
- No tool may commit, push, open PRs, save plan files in the repo, edit settings, or schedule loops or wakeups.
- Do not touch user-level settings or any service. OpenClaw stays untouched.
- Do not search other folders, ~/Documents or old session records.

## Database and history
- Additive or relaxing migrations only.
- Never edit the first 1,598 traceability entries or any guard hash. Append only.
- Narrow a historical test only by changing the one expectation, keeping the test name, with a short comment and a docs/010 note.

## Business rules
- Money in integer cents. Dates in Asia/Phnom_Penh. Nothing automatic.
- Final Settlement stays in V1-056. No photo storage. No new packages.

## Verification
- Read the FULL unfiltered output of database and test runs (rtk proxy).
- One targeted PostgreSQL run per sub-slice where a database is involved, after a read-only search of ALL backend tests for other affected tests.
- No retry. Routine allowance: at most 2 corrections per distinct cause.
- Check new tests for hard-coded values and dates tied to the real clock.
- Before each full PostgreSQL run, first check that the new migration applies on its own, in the cheapest way the repo allows (owner, 2026-10-06; a CASE inside an IF broke the first run of 8c and 8e-2). Today that is a throwaway copy of `scripts/database-test.sh`, kept outside the repo, that runs `uv run alembic upgrade head` on a fresh container instead of pytest. This check is not a test run.
- When a full run output is very large, commit an excerpt and move the full file to `~/Development/prm-run-logs/` (owner, 2026-10-06). Never delete a run output.

## Commits
- One local checkpoint commit per sub-slice, explicit paths, secret and diff scan.
- No push. No amend. Never commit failing or half-finished work.
- Keep ops/NOW.md updated with one short line after every commit: what is done, what is next.
- If context is nearly full: finish and commit the current sub-slice only if green, update NOW.md, tell the owner to start a fresh session.

## Frontend
- TypeScript strict. No any without justification.
- API access only in the client layer.
- Loading, empty, success and error states.
- Forms validated before submission. Accessible labels and keyboard navigation.
- Follow the existing design system. No business logic duplicated from the backend.
- No new packages. No browser tools without owner approval.

## Capabilities and routes
- Reuse existing capabilities: invoices.issue, invoices.create, utility.calculate, utility_readings.record, property.manage, damage_charges.bill.
- A new capability needs an owner answer.
- New routes may be added to docs/005 only for the pending V1-055 items, in the existing API style, and must be listed in the report.

## Automation tests
- Do not run make automation-test until the owner approves, after the agent explains in plain words what it does with the OpenClaw scripts.
