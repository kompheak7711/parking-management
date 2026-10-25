# V1-060 release-candidate gate: plan and step log

Started 2026-10-25 in the cloud, thread "Run V1-060 release check", branch
`claude/project-thread-brhisb` from `implementation/foundation` 141e363 (V1-056 complete, migration
head `20270218_206`). Nothing goes to `implementation/foundation` without the owner's yes.

Rules: DL-071 answers 13 to 15 (docs/010), TEST-115 (docs/007), the run rules
(ops/V1_055_RUN_RULES.md) and the owner's 2026-10-23 22:30 rule (Claude decides non-money points
and records them).

## What V1-060 must prove (DL-071)

1. No flaky test and no open security warning in the release candidate. A flaky test is fixed, not
   run again until it passes (TEST-FE-087, TEST-FE-128, TEST-FE-488, TEST-FE-258, TEST-FE-420 and
   the DL-067 `LockNotAvailable` full-run failure by name).
2. A speed test with 300 Units and 10 years of made-up history.
3. One test session by the Owner or the Manager with made-up data, following a short written
   script (reserve, sign, move in, bill, pay, move out, settle). V1-060 is done only when the owner
   says the session passed.

## Order

Part A runs now, on this branch, while V1-057 (reports) and V1-058 (screens) are still being
built. Part B runs only after both are merged into `implementation/foundation`, because the release
candidate is the code that will be used.

### Part A (now)

- A1 Frontend flaky tests: find the cause, fix, prove under heavy load.
- A2 CI: the reasons GitHub CI is red that belong to the code (security advisory, time limits).
- A3 Database flaky lock test: a full PostgreSQL run in the cloud; fix any order or lock failure.
- A4 Speed test tool: `scripts/speed-test.sh` (made-up data maker `backend/speed/seed.py`, timing
  `backend/speed/measure.py`), first results on the current code.
- A5 Owner test script draft (written once the V1-058 screens exist; the session uses those
  screens).

### Part B (after V1-057 and V1-058 merge)

- B1 Merge `implementation/foundation` into this branch; re-chain migrations if needed.
- B2 Full gates on one commit, each run once: backend format, lint, type check, unit tests;
  full PostgreSQL run; frontend format, lint, type check, tests, build; `npm audit`; `pip-audit`
  (runtime and development); deployment config check; backup-restore check.
- B3 Frontend tests under heavy load (two full runs at once next to busy processes): zero failures.
- B4 Speed test on the release candidate: every read within the limits.
- B5 Final independent review (one round; three rounds only for sign-in or session code).
- B6 Owner test session with the written script; the owner says passed or not.
- B7 Owner yes, then push and merge.

## Step log

- 2026-10-25 A1: cause found and fixed (see DL entry at merge). Under heavy load (8 to 12 busy
  processes and two or three full runs at once on 4 cores) the unchanged suite failed 6 to 8 tests
  per run, all by time: the test limit of 5 seconds, or the 1 second wait of Testing Library for a
  screen change. After the fix (`testTimeout` 60 s in `frontend/vite.config.ts`, `asyncUtilTimeout`
  15 s in `frontend/src/test/setup.ts`, the two 5 s waits in `App.test.tsx` removed) five loaded
  runs passed 1,654 of 1,654 except one: TEST-FE-203 read a success line right after the command
  call instead of waiting for it; it now waits (`findByText`). A wrong screen still fails.
- 2026-10-25 A2: `certifi` 2026.7.22 had advisory PYSEC-2026-4320 (development dependencies
  audit, CI "Dependency security" red); now 2026.10.23, only its three lock lines changed;
  `pip-audit` of the development set says no known vulnerabilities. CI time limits raised: backend
  60 min, frontend 30 min, PostgreSQL gate 120 min (the full run takes about 60 minutes; it was
  stopped at 15). Since 2026-10-25 07:04 every CI job ends in 3 seconds with no runner and no log:
  this looks like the GitHub Actions minutes or spending limit of the account, which only the owner
  can see or change. The supervisor routing step (`make automation-test`) fails 7 tests of the old
  OpenClaw automation (packets of V1-019 to V1-021 that look for code that has since changed);
  OpenClaw is the owner's, so this waits for the owner.
