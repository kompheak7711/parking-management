# V1-055 run rules

New sessions: read AGENTS.md, ops/NOW.md, ops/V1_055_RUN_RULES.md. Nothing else is needed.

## Tools and scope
- AGENTS.md overrides every plugin, skill and hook.
- No GSD, ponytail, ECC formatter or learned skills.
- No tool may commit, push, open PRs, save plan files in the repo, edit settings, or schedule loops or wakeups.
- Do not touch user-level settings or any service. OpenClaw stays untouched.
- Do not search other folders, ~/Documents or old session records.
- Edit long documents (docs/, ops/, the questions file included) only with exact-text edits, also when adding at the end; never append with a shell redirect or rewrite the whole file. Check `git diff --stat` after each edit (owner, 2026-10-08).
- A script that makes exact-text replacements, each checked to match exactly once, counts as an exact-text edit, as long as `git diff` shows only the intended lines (owner, 2026-10-16; the scripted edit of ops/traceability.json in 10e-3d-2d-2b-2 was accepted).

## Database and history
- Additive or relaxing migrations only.
- Never edit the first 1,598 traceability entries or any guard hash. Append only.
- Narrow a historical test only by changing the one expectation, keeping the test name, with a short comment and a docs/010 note.
- When an owner answer changes a result and a committed test or fixture expects the old result, update it to the new result without asking. Change only the affected case or branch; name each change in the report; the independent reviewer compares it with HEAD and confirms nothing else got weaker. A change that removes a check, or that the answer does not cover, still needs the owner (owner, 2026-10-11; replaces the rule of the Q-2026-10-11-79 answer). When an owner answer turns a refused case into an allowed one, the implementer may also rename its test so the name says what it now checks; record each rename in docs/010, the plan, the traceability entry and the report (owner, 2026-10-14; the 10e-3d-2b-1b rename of `test_own_corrections_that_also_took_another_return_s_money_wait` was accepted).
- A change that makes a committed test stricter, found by a reviewer, is allowed without asking. Name each one in the report (owner, 2026-10-13; the two 10e-2 assertions that 10e-3b review round 2 made stricter were accepted).
- When a reviewer asks for a test and the implementer thinks it cannot be written on the real path, the independent reviewer confirms that before it is recorded as a limit instead (owner, 2026-10-13; 10e-3d-1 recorded "own return first" as unseen on the real path, and review round 3 showed a real-path case).
- Before writing that a test cannot be built on the real path, try to build it, and ask the reviewer for a set-up in the same round (owner, 2026-10-13; it cost an extra review round in 10e-3d-1 and again in 10e-3d-2a).
- When a reviewer gives a test set-up, write it in the review record, so a later session can use it (owner, 2026-10-13; the 10e-3d-2a round 2 set-ups were only summarised and had to be found again).

## Business rules
- Money in integer cents. Dates in Asia/Phnom_Penh. Nothing automatic.
- Final Settlement stays in V1-056. No photo storage. No new packages.

## Verification
- Read the FULL unfiltered output of database and test runs (rtk proxy).
- One targeted PostgreSQL run per sub-slice where a database is involved, after a read-only search of ALL backend tests for other affected tests.
- No retry. Routine allowance: at most 2 corrections per distinct cause.
- The same kind of error is the same cause, even when it shows up on different lines (owner, 2026-10-12; the long-line causes A and B of sub-slice 10e-2b-2 were one cause, so that was one correction past the limit; the commit stays). Implementer's stricter reading, applied from sub-slice 10e-2c: also in another file or after a rewrap; for example every too-long line is one lint cause, and every formatter change is one format cause.
- Counting corrections (owner, 2026-10-14): running the formatter before the format check is a normal step, not a correction. A correction counts only when a check or a run fails. Counts start again for each sub-slice.
- Run tables (owner, 2026-10-14): list the passing rerun after each failed check or run, with its own name, so every failure shows what passed after its fix (the signing time table showed Y1 and L1 failing, but not the runs that passed after the fixes).
- Last targeted run (owner, 2026-10-15; the 10e-3d-2c run table showed no run after its round 2 test fix): after the last fix in a sub-slice, run the targeted tests that cover every file changed since the last run, before the commit.
- Check new tests for hard-coded values and dates tied to the real clock.
- Before each full PostgreSQL run, first check that the new migration applies on its own, in the cheapest way the repo allows (owner, 2026-10-06; a CASE inside an IF broke the first run of 8c and 8e-2). Today that is `sh scripts/migration-check.sh` (owner, 2026-10-11; it replaces the throwaway copy kept outside the repo): `uv run alembic upgrade head` on a fresh throwaway container instead of pytest. This check is not a test run. A targeted PostgreSQL run uses `sh scripts/database-targeted-test.sh <backend test paths>` on the same kind of container. Neither prints a database password or URL; `scripts/database-test.sh` stays the full run.
- If the auto-mode checker blocks an action, do not work around it with a different command: stop and tell the owner what was blocked and why it is safe (owner, 2026-10-11).
- When a full run output is very large, commit an excerpt and move the full file to `~/Development/prm-run-logs/` (owner, 2026-10-06). Never delete a run output.
- Run every lint, format and type check in its own tool call: one tool, one command. Never join two of them with `&&`, `;`, `||` or a pipe, not even on one file and not even after a quick fix (owner, 2026-10-06; it happened in 8e-2 and 8f).
- If any code, migration or test file changes after the last full PostgreSQL run of a sub-slice, run the full PostgreSQL run again before the commit. Only text-only changes may skip it, as in the owner answers to Q-2026-10-07-44 and Q-2026-10-09-67 (owner, 2026-10-09; the VOLATILE change of 10c-3b-1 came after its full run and is covered by the first full run of 10c-3b-2).
- Before any run output goes into a repo file, check it for passwords and other secrets, also from a throwaway test database (owner, 2026-10-09).
- Standard secret scan (owner, 2026-10-13; replaces every earlier form): before each commit, search the staged diff (`git diff --cached` of the paths named in the commit) case-insensitively for password, passwd, secret, token, api key, private key and a URL that carries a user and a password (`://name:word@`). Never put a file-name term in the search pattern. Read `git status --porcelain --untracked-files=all` and check by eye that no env file is listed; do not search for that name with a pattern. Scan every saved run output the same way.
- Never repeat a command that a guard hook or the auto-mode checker blocked (owner, 2026-10-13). One exception: if the guard hook blocks a scan only because of a word inside the search pattern, and the command reads only the staged diff or saved run outputs, remove that word and run the scan once more; name the word in the report. If anything else is blocked, stop and tell the owner.
- Blocked review agent (owner, 2026-10-13; after the 10e-3d-2b-1a round 3 security reviewer was blocked twice): if the auto-mode checker blocks the start of a review agent, do not retry it. Do that review yourself in the main session, read-only, on this sub-slice's changes only (`git diff HEAD` plus any new untracked files), with the same checklist the agent would have had, and note the block in the review record. If a second review agent is blocked in the same sub-slice, stop and tell the owner.
- Signature failures (owner, 2026-10-14; the rule "Signature tests and the clock" of 2026-10-13 is retired, because the signature fixture clock fix 07bca44 takes every Lease signing time in the database tests from the database clock): a `Signature evidence is invalid` failure is a real failure. Find its cause, as for any other failure; there is no clock-check rerun. Every targeted and full run uses `caffeinate -dims` (owner answer to Q-2026-10-13-99).
- Catalog dumps (owner, 2026-10-14): never run a script copy from a tmp folder. If a catalog dump is needed again, add it as a committed script under `scripts/` in its own small reviewed commit; like the other scripts, it must not print the database password or the database URL. Today that is `sh scripts/catalog-dump.sh <app function name> ...` (added 2026-10-15 for sub-slice 10e-3d-2c; record ops/reviews/V1-056-catalog-dump-script.md): the migrations on a fresh throwaway container, then each named `app` function's current definition in one read-only transaction, all output redacted. Its redaction can replace a long hex run in a function body with a marker, so check a copied definition for `REDACTED` markers.
- Lesson: put a CASE inside a PL/pgSQL IF condition in parentheses; otherwise the IF ends at the CASE's first THEN (owner, 2026-10-13; it broke 10e-3b and 10e-3c).
- Review round 3 (owner, 2026-10-13; widens the standing round-3 rule of ops/V1_056_TAKEOVER.md section 4): if review round 2 has no blocker, and every should-fix is only a test, a text change, or a fail-closed check that adds a refusal, fix them and run round 3 without asking the owner, even when there are more than two. Round 3 must still be clean, or stop and tell the owner. Any other kind of should-fix beyond two still needs the owner's answer.
- Round 3 text and assertion fixes (owner, 2026-10-16; answer 2 to the 10e-3d-2d-2a round 3 report, Q-2026-10-15-114): if the only should-fix items in review round 3 are text fixes or new assertions in tests that are already built and green, with no code, migration or fixture change, make them, rerun the checks and runs, and commit without a round 4. Name each one in the report. If a new assertion fails, stop and tell the owner. Any other round 3 finding still stops.
- Design changes during a build (owner, 2026-10-14; the four implementer's readings of 10e-3d-2b-2 were accepted): when the written design must change to keep a committed test passing or to make the planned rule work, the implementer may make the change without stopping, if the reviewers of the same review round confirm that it is needed and safe. Name each such change in the report. A change to who pays or how much still needs the owner's answer first.

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
