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
- 2026-10-25 A4: speed tool built: `scripts/speed-test.sh` (own throw-away database),
  `backend/speed/seed.py` (300 Units, 10 years of made-up history through the real Lease, billing
  and allocation functions: 33,000 Rent Invoices, monthly Meter readings, 1 Unit in 5 with its last
  two months unpaid; about 20 minutes) and `backend/speed/measure.py` (a signed-in Manager reads
  about 25 screens' routes through the real app, then one scheduled Rent run). Limits (decided by
  Claude under the owner's 2026-10-23 22:30 rule): middle read 0.5 s, slowest read 1 s, Rent run
  120 s. First 300-Unit run: two reads too slow. The Invoices list took 0.7 s (no index on its
  order): migration `20270219_207` adds `invoices_invoice_date_order_idx` (6 ms). The Rent
  nonpayment alerts page took 28 s and answered 503 (one function per Rent line): 207 adds a
  set-based balance check before the exact function check, with a test that both give the same
  answer for every Invoice line of the shared test database (1.7 s on the busy machine; the rerun on
  a quiet machine is still to do).
- 2026-10-25 slice 12 item: `test_pending_future_basis_is_preserved_without_utility_invoice`
  failed about 1 run in 6: a real lock-order deadlock between two executions of one Billing Run.
  Migration `20270220_208` makes `app.finish_scheduled_billing_attempt` lock the run row before the
  attempt row, like the other three writers. Before: 3 of 30 runs failed; after: 60 of 60 passed.
  `test_access_control.py` gained the four `sign_in_prune.*` log labels of slice 12c (an old
  failure on `implementation/foundation`).
- 2026-10-25 A3: the DL-067 `LockNotAvailable` cause is proven. With a busier autovacuum on a
  scratch database (naptime 1 s, thresholds 0, cost delay 20 ms) and nothing else running, the
  refund and deposit receipt modules failed with 55P03 on `app.invoices` or `app.invoice_lines` in
  2 of 3 runs (including `test_a_payment_confirmed_for_an_owed_invoice_is_not_a_deposit_receipt`).
  Migration `20270221_209`: when the NOWAIT request of `app.assert_payment_excess_eligible` fails
  and only autovacuum workers hold a conflicting lock, the function waits at most 3 s for the same
  locks (PostgreSQL cancels the autovacuum after `deadlock_timeout`); any session's lock is still
  refused at once. A first version looked at `backend_type`, which the function's owner cannot see
  (4 of 5 runs still failed); the built version uses the missing user of an autovacuum worker.
  After: 10 of 10 busy runs passed. This is a product code change: commit 7575ea0 stays on the work
  branch until the owner says yes (decision card of 2026-10-25). Docs (docs/004, DL entry) follow
  the owner's answer.
- 2026-10-25 PG run 2 (Python 3.11, at 3d8be33, before 208 and 209): 2,763 passed, none failed.
- 2026-10-25 A4 rerun on a quiet machine: 24 of 25 reads passed; the Rent nonpayment alerts page
  still took 1.6 s. Cause: the per-line balance subqueries ran 33,000 times, the day-zero function
  ran once per Invoice, and the high cost estimate switched on JIT compiling (about 0.6 s). 207
  (not merged anywhere yet, so changed in place) now joins one grouped sum per money table with
  the same conditions and writes day zero as `billing_period_start - 1` for RECURRING Invoices;
  the exact function check still runs after it. Second rerun: all 25 reads and the Rent run pass
  (alerts middle 0.44 s, slowest 0.48 s; Rent run 3.9 s). Report: ops/reviews/V1-060-speed-test.md.
- 2026-10-25 PG run 3 (Python 3.11, at 4932274, with 207 to 209): 2,766 passed, none failed.
  Part A is done except the owner items (GitHub Actions billing; the OpenClaw step in CI) and the
  owner test script, which follows the V1-058 screens. Part B starts when V1-058 merges; this
  branch's 207 to 209 then re-chain after V1-058's head (20270314_233 on its branch today).
- 2026-10-25 A2 owner answers: the repository is private on a free GitHub plan (2,000 Actions
  minutes a month; about 480 runs of up to two hours each used them up, so jobs stop at once until
  the monthly reset). Owner yes (17:02): the OpenClaw supervisor routing step is removed from CI
  (the Makefile target and the OpenClaw files stay as they are). Decided by Claude under the
  owner's 2026-10-23 22:30 rule: CI runs on pushes to `main` and `implementation/foundation`, on
  pull requests and by hand (`workflow_dispatch`), not on every work-branch push; the cloud
  threads run the same gates locally before each merge.

