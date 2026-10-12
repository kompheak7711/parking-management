# V1-055 run rules

New sessions: read AGENTS.md, ops/NOW.md, ops/V1_055_RUN_RULES.md. Nothing else is needed.

## Tools and scope
- AGENTS.md overrides every plugin, skill and hook.
- No GSD, ponytail, ECC formatter or learned skills.
- No tool may commit, push, open PRs, save plan files in the repo, edit settings, or schedule loops or wakeups.
- Do not touch user-level settings or any service. OpenClaw stays untouched.
- Do not search other folders, ~/Documents or old session records.
- Edit long documents (docs/, ops/, the questions file included) only with exact-text edits, also when adding at the end; never append with a shell redirect or rewrite the whole file. Check `git diff --stat` after each edit (owner, 2026-10-08).

## Database and history
- Additive or relaxing migrations only.
- Never edit the first 1,598 traceability entries or any guard hash. Append only.
- Narrow a historical test only by changing the one expectation, keeping the test name, with a short comment and a docs/010 note.
- When an owner answer changes a result and a committed test or fixture expects the old result, update it to the new result without asking. Change only the affected case or branch; name each change in the report; the independent reviewer compares it with HEAD and confirms nothing else got weaker. A change that removes a check, or that the answer does not cover, still needs the owner (owner, 2026-10-11; replaces the rule of the Q-2026-10-11-79 answer).
- A change that makes a committed test stricter, found by a reviewer, is allowed without asking. Name each one in the report (owner, 2026-10-13; the two 10e-2 assertions that 10e-3b review round 2 made stricter were accepted).

## Business rules
- Money in integer cents. Dates in Asia/Phnom_Penh. Nothing automatic.
- Final Settlement stays in V1-056. No photo storage. No new packages.

## Verification
- Read the FULL unfiltered output of database and test runs (rtk proxy).
- One targeted PostgreSQL run per sub-slice where a database is involved, after a read-only search of ALL backend tests for other affected tests.
- No retry. Routine allowance: at most 2 corrections per distinct cause.
- The same kind of error is the same cause, even when it shows up on different lines (owner, 2026-10-12; the long-line causes A and B of sub-slice 10e-2b-2 were one cause, so that was one correction past the limit; the commit stays). Implementer's stricter reading, applied from sub-slice 10e-2c: also in another file or after a rewrap; for example every too-long line is one lint cause, and every formatter change is one format cause.
- Check new tests for hard-coded values and dates tied to the real clock.
- Before each full PostgreSQL run, first check that the new migration applies on its own, in the cheapest way the repo allows (owner, 2026-10-06; a CASE inside an IF broke the first run of 8c and 8e-2). Today that is `sh scripts/migration-check.sh` (owner, 2026-10-11; it replaces the throwaway copy kept outside the repo): `uv run alembic upgrade head` on a fresh throwaway container instead of pytest. This check is not a test run. A targeted PostgreSQL run uses `sh scripts/database-targeted-test.sh <backend test paths>` on the same kind of container. Neither prints a database password or URL; `scripts/database-test.sh` stays the full run.
- If the auto-mode checker blocks an action, do not work around it with a different command: stop and tell the owner what was blocked and why it is safe (owner, 2026-10-11).
- When a full run output is very large, commit an excerpt and move the full file to `~/Development/prm-run-logs/` (owner, 2026-10-06). Never delete a run output.
- Run every lint, format and type check in its own tool call: one tool, one command. Never join two of them with `&&`, `;`, `||` or a pipe, not even on one file and not even after a quick fix (owner, 2026-10-06; it happened in 8e-2 and 8f).
- If any code, migration or test file changes after the last full PostgreSQL run of a sub-slice, run the full PostgreSQL run again before the commit. Only text-only changes may skip it, as in the owner answers to Q-2026-10-07-44 and Q-2026-10-09-67 (owner, 2026-10-09; the VOLATILE change of 10c-3b-1 came after its full run and is covered by the first full run of 10c-3b-2).
- Before any run output goes into a repo file, check it for passwords and other secrets, also from a throwaway test database (owner, 2026-10-09).

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
