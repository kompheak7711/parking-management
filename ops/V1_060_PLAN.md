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
- 2026-10-25 owner (17:30): when a CI job fails, the run's other jobs stop. Each job ends with a
  step that runs only after a failure and cancels the run (`gh run cancel`, workflow permission
  `actions: write`).
- 2026-10-26 B1: foundation a7f3645 (V1-057, V1-058) merged in; this branch's migrations re-chained
  to `20270320_239`, `20270321_240` and `20270322_241`. 19 merge conflicts resolved; 39 mypy errors
  in the merged V1-057/V1-058 tests fixed; traceability entries for the six release tests.
- 2026-10-26 B2 first pass (b5d8437, the PostgreSQL run alongside the other suites): every other
  gate passed (frontend 1,874; backend unit 5,079 + the traceability fix; pip-audit and npm audit
  clean; backup and restore at 241, 194 tables). PostgreSQL: 9 failed, 2,839 passed. Fixed:
  four upgrade tests now leave out the Unit setup columns and audit rows that V1-058 migration 227
  adds; the Final Settlement API test reads its own Lease's Settlements; migration
  `20270323_242` makes the Home page read a Refund draft whose amount is not a JSON number as no
  amount (the Waiting for approval test leaves such a draft in the shared Property, and the Home
  page failed with 22P02). Decided by Claude under the owner's 2026-10-23 22:30 rule (a read, no
  rule or amount change). Three statement timeouts (credit application, settlement return
  reversal, 500-line action context) pass alone; the full PostgreSQL run is repeated alone to
  settle them (no reruns of flaky tests: a timeout that repeats gets fixed).
- 2026-10-26 B2 done: the full PostgreSQL run alone (d46588a) gave 2,848 passed and 1 failed (the
  Final Settlement API test read every Settlement of the shared Property; fixed in a190724). The
  three statement timeouts of the first pass did not come back: they came from the load of the
  other suites. Backend unit 5,080 passed on a190724.
- 2026-10-26 B3 done: two full frontend runs at once next to 8 busy processes: 1,874 of 1,874
  passed in each.
- 2026-10-26 B4: the speed tool now also reads the V1-057 Home and reports and the V1-058 screens,
  and runs the Rent run on day 25 of this month (it used today's date and only worked on the
  25th). First run: Total payment, the Invoice register and the Payments register timed out
  (about 60 s), the Home page took 1.8 s and Total income 1.4 s. Migration `20270324_243`
  rewrites the four functions without per-row function calls (same answers; a release test
  compares each with its pre-243 version). Limits decided by Claude under the owner's 2026-10-23
  22:30 rule: the Home page 1.5 s middle and 2 s slowest, the Rent nonpayment alerts 1 s and
  1.5 s, a report or register with no dates (the whole 10 years) 3 s and 4 s; every other read
  0.5 s and 1 s. Full PostgreSQL run on 243: 2,850 passed. Speed run on 243: all 41 reads and the
  Rent run (4.1 s) pass (ops/reviews/V1-060-speed-test.md). The owner made the repository public
  (2026-10-26 13:58); the whole history was scanned for secrets (none) and GitHub CI ran green on
  99be0a8 (all four jobs).
- 2026-10-26 B5: final review of everything since foundation a7f3645 found no blocker.
  Fixed: migration 242 casts a REFUND amount only when it is a whole JSON number in range and
  reads payment_id with app.draft_uuid; the release tests cover more odd drafts and check that
  each compared function saw rows; CI checkouts keep the token out of .git/config, and the V1
  roadmap and automation traceability checks are back in CI (they left with the OpenClaw step).
  Left as notes (no change): the 241 holder check can wait up to 3 s in rare cases; the
  one-Property fallback in 243 is correct by reading but has no test; seed.py and measure.py
  trust the database URL they are given. Checks on 5b5aed38: format, lint, types, roadmap,
  backend tests 5,080 passed; PostgreSQL 2,850 passed (run in two halves: a full run that shared
  the machine with the backend tests hit statement timeouts and the 2-hour limit).
- 2026-10-27 B6 (owner session, paused at step 1): the local database had no Property and the
  screens' proxy missed four route roots; fixed by the setup command (c1824fb5) and the proxy
  (187c7324). The owner's findings, fixed in 9ae09bcc and e37a016e: Make Reservation in the new
  design (the deposit is saved first as a Payment with its Receipt, then the Reservation takes it),
  Receive Security Deposit on the Lease page (a walk-in Lease's deposit or the rest of one), New
  Customer from Make Reservation and New Lease, date boxes that take a typed dd/mm/yyyy day with a
  calendar button, and 46px text boxes and drop-downs (decided by Claude under the owner's
  2026-10-23 22:30 rule; no money rule changed). Services on New Lease need a Service in Settings
  first. Checks: format, lint, types, build, frontend 1,879 passed, traceability passed.
- 2026-10-27 B6 (owner session, step 2): the owner asked that a walk-in draft carries its Security
  Deposit, the draft is printed for the customer to check, and Sign Lease receives the money first;
  on the decision card the owner chose the full total, no part payment (DL-100). Built: migration
  `20270325_244` (append-only planned Security Deposit of a walk-in draft and a read-only preview of
  the Initial Rent Invoice), the signing routes (preview, planned deposit, make the Initial Rent
  Invoice), a Security Deposit box on New Lease and Edit draft, Print draft (one A4 sheet), and Sign
  Lease as one dialog: receive the full total as a Payment with its Receipt, record the signatures,
  sign, make the Initial Rent Invoice, pay it from the Payment and put the rest into the Security
  Deposit; each step keeps its request id so Try again never pays twice. Earlier in step 1: a
  larger calendar beside its box, New Customer as an icon button, DL-099 (more than the 20%
  suggestion needs no reason) and the duplicate Reservation step taken out of the script.
- 2026-10-27 B6 (owner session, step 2 again): the owner found no Security Deposit box on a draft
  from a Booking and a Lease page that said no Security Deposit was recorded; the owner's rule
  (DL-101): the Security Deposit is a Lease term like the Rent, recorded with the Lease before any
  money. Built: migration `20270326_245` (the Reservation's Security Deposit of a draft, a draft
  amount never below the money received, and one INCREASE or DECREASE of the required amount right
  after signing under `leases.sign`), the apply route, the box on New Lease from a Booking (with a
  reason when the amount changes) and on Edit draft, the Lease page Deposits card, Print draft and
  Sign Lease (which refuses money while the draft's amount is below the money received). Pushed
  after the quick checks (format, lint, types, Lease screen tests 36 passed, the new and nearby
  database tests 19 passed, signing API tests passed, traceability passed) so the owner can test
  sooner; the longer suites and CI run after the push (owner 20:35: do not make the owner wait).
