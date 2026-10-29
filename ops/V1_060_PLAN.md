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
- 2026-10-28 B6 (owner session, step 2 checks): the list shows a signed Lease as "Lease active"
  (the script said "Signed"; the script is fixed, the screen is right). The owner asked where to see
  the Initial Rent Invoice, the Security Deposit and the Receipt (Invoices, the Lease page Deposits
  card, Payments then the Receipt number; a Security Deposit is never on an Invoice, the Receipt's
  Paid for lines show it). Owner change: the printed Receipt no longer shows the "Payer note /
  សម្រាប់" line, because the Paid for lines already say what the money paid; the note stays saved
  with the Payment. DESIGN.md 0.32 and the brand-kit Receipt template follow.
- 2026-10-28 B6 (owner session, steps 2b and 3): the owner ticked step 2b (the DL-101 Security
  Deposit retest passed). The owner asked why the printed Initial Rent Invoice has no QR code like
  the sample: the QR code shows only while money is owed (V1-058 R5), and the Initial Rent Invoice
  is paid in full at signing (DL-100). Found from the owner's screenshot: the printed Initial Rent
  Invoice showed the late-payment note, but that Invoice never gets a late-payment charge
  (BR-RENT-009, BR-RENT-029). Fixed: the sheet leaves the note out when its Rent line was billed as
  INITIAL (TEST-FE-1023; the database test locks that mark). The test script said the Initial Rent
  Invoice number starts with RENT-I; it gets a normal INV number (script fixed; step 4 now says
  where the QR code shows).
- 2026-10-28 B6 (owner asks at 07:24): History showed "History could not be read just now" because
  one stored event whose details fail today's stricter public-value checks stopped the whole page
  (and long app-written codes such as deposit_required_amount_adjustment looked token-shaped).
  Fixed: such an event shows with those details withheld, never exposed; a reason that looks like a
  secret shows a fixed "withheld" sentence; app-written codes (lower-case words joined by dots or
  underscores, at most 128 characters) show. All 100,342 events in the cloud test database now read.
  Units table: the owner asked for Unit, Floor, Unit Type and Until, without Customer and Monthly
  Rent; Status stays (decided by Claude under the owner's 2026-10-23 22:30 rule, so the counts and
  chips still match). Until showed "—" for every Unit because the list asked only for Leases running
  today; it now reads every signed Lease and shows the running one, or the next one when none has
  started (BR-LEASE-016, BR-OCC-008). TEST-FE-1024 and three audit API tests added.
- 2026-10-28 B6 (owner asks at 07:24, Add occupant): the owner could not add a friend who started
  living with a tenant after signing. DESIGN.md 0.15 has the "Add occupant" button, but V1-058 step
  L2c-1 left it for a new database command. Built (DL-102, migration 20270327_246,
  app.add_lease_occupant, append-only lease_occupant_additions, POST /leases/{lease_id}/occupants
  under reservations.complete): before the move-in the person is planned and moves in with the
  Lease; after it the person gets an own Occupancy from an own move-in date (not before the Lease's
  move-in, not after the End Date or today). The Lease page Occupants box lists the planned people
  and has the button and dialog (an existing Customer or New Customer). Found and fixed on the way:
  the Lease History did not show a move-in recorded for a Lease signed with its outcome record
  (lease_move_ins was missing from the timeline). Decided by Claude under the owner's 2026-10-23
  22:30 rule: no Primary Tenant after the move-in, a renewal only after its own move-in (R7 renewal
  occupants still open), no deactivated Customer, at most 20 people; no limit per Unit Type exists,
  so none is checked. Tests: 6 database tests, 1 API test, 1 unit test, TEST-FE-1025 to 1029; head
  pins moved to 20270327_246. Runs: the new and nearby database tests 44 passed; frontend 1,892 of
  1,892 when TEST-FE-087 (known slow, V1-060 list) is rerun alone; backend lint, format and types
  passed; traceability passed.
- 2026-10-28 B6 (Add occupant follow-up): a draft that planned nobody meant the Primary Tenant
  alone (Record move-in ticks the tenant then). Adding a friend to such a draft made the Lease
  list only the friend, so Record move-in would have ticked the friend and not the tenant. The
  Lease now lists the Primary Tenant first once someone is added. One database test added. Runs:
  the Add occupant database tests 7 passed, nearby Lease database tests 19 passed, Lease API
  tests 12 passed; backend lint, format and types passed.
- 2026-10-28 B6 (owner asks at 07:24, Reports page): the Reports menu opened a "comes with
  V1-057" note. Built the Reports screens on the V1-057 data (DESIGN.md round 4): the list shows
  only the reports the person may read, in the owner's order and two groups; the four Totals
  tables (years by month, a Unit filter, Summary, chart, Top 5 Units); the nine registers (one bar
  for floor and period, a Summary card with a chart, the full table with a footer total and the
  Generated line, a link on each record, 200 rows at a time with Show more); Export to a
  spreadsheet or a PDF through the V1-057 export (owner answer of 21/10: .xlsx and PDF). Decided by
  Claude under the owner's 2026-10-23 22:30 rule: the Reports menu item shows to anyone who may
  read one report (before, it needed Payments or Invoices read, so a person with only Lease,
  Utility or History reads never saw it; TEST-FE-810 now also lists Reports for audit.view); Paid
  for in the Payments register shows one kind per line, as on the Payments list; the scope and
  period stay the same from one report to the next while the page is open. Known gaps: registers
  filter by floor only (no Unit filter in the V1-057 API); the PDF has no Khmer font; the Khmer
  words need a native speaker's check. Tests TEST-FE-1030 to 1060. Looked at on an iPad-size
  screen (1180 x 820) with sample data: no page overflow; wide registers scroll inside their card.

- 2026-10-28 (B6, owner ask of 10:04, decided by Claude under the owner's 2026-10-23 22:30 rule):
  Add meter now lists only the Units that have no current meter of the chosen kind. Changing the
  kind clears a chosen Unit that already has that kind. When every Unit already has one, the
  dialog says to change a broken meter with Replace meter on its page. The check when saving
  stays. Tests TEST-FE-884 (changed) and TEST-FE-1061 (new).
- 2026-10-28 (B6, owner ask of 10:04, decided by Claude under the owner's 2026-10-23 22:30 rule):
  a low-use check beside the high-use one. When a new reading's use is under a third of the
  usual (the average of the last three uses) in an Occupied Unit, the Meter readings screen asks
  to check the meter still works before saving, with Save anyway; Import marks the line with a
  check note. An empty Unit uses little, so it is not checked, and a usual under 6 is not
  checked. Tests TEST-FE-1062 and TEST-FE-1063.
- 2026-10-28 (B6, owner ask of 09:56, DL-103): Create Invoice made one Invoice for each charge.
  On the decision card the owner chose "Yes, build it now" with four rules: the amount is a whole
  quantity times a unit price in cents, exactly; a part payment pays the items from the top down;
  one reason and one approval for the whole Invoice; at most 20 items. Built: migration
  20270328_247 (each item is its own approved one-time charge that keeps its quantity and unit
  price, with a check that the amount is exactly their product; app.create_items_invoice_draft
  makes the charges and one Miscellaneous Draft in one step; app.replace_invoice_draft_items is
  Edit items on such a Draft, with a reason for the change; the Final Settlement preview lists an
  item taken off a Draft as information), POST /properties/{id}/invoices/drafts and
  PUT /invoices/{id}/items (invoices.create), and the screens: an items table with Add item and
  the total, a confirmation that lists every item, Edit items on a Draft made there, and
  "2 × $15.00" under each item on the printed Invoice. DESIGN.md 0.33. Decided by Claude under the
  owner's 2026-10-23 22:30 rule: quantity 1 to 9,999, unit price at most $9,999,999.99, item names
  at most 80 characters on the screen, a changed Customer, Lease, reason or approval makes every
  item new, and on an iPad on its side the form takes the whole width (looked at with sample data
  at 1180 x 820, 820 x 1180 and 390 x 844: no page overflow). Tests: 8 database tests, 2 API tests,
  TEST-FE-1064 to 1067 (new) and TEST-FE-904 (changed: Create Invoice now saves all items in one
  request); head pins moved to 20270328_247. Runs: the new database tests 8 passed; the Invoice
  API, service, one-time charge and Final Settlement draft tests passed; frontend 1,930 of 1,930;
  backend lint, format and types passed; traceability passed. On the long-used local test
  database 5 older Invoice migration tests failed on rows left by earlier runs (fixed keys on the
  shared first Property, for example the billing run key generated-void-completion-race); CI runs
  on a fresh database.
- 2026-10-28 (B6, owner ask of 10:04, DL-104): "after found broken meter, how to report or
  change meter status?" The approved DESIGN.md "Report broken" was not built: only Replace meter
  wrote the failure date, so a meter found broken stayed Working. Built: migration 20270329_248
  (app.report_utility_meter_failure_api sets the failure date of a working meter at the expected
  version; the append-only app.utility_meter_failure_reports keeps what is wrong, who and when;
  the command replay accepts REPORT_METER_FAILURE), POST /meters/{id}/report-broken
  (utility_meters.manage) and failure_report on the Meter, and the screens: a Report broken
  button with the MANAGER badge on a working meter's page, a dialog with the day found broken
  (today at first; not before the newest reading, not after today) and what is wrong, a note that
  it cannot be undone, "What is wrong" in the meter's facts, and the reported day kept in Replace
  meter. The lower-reading message now says a Manager reports the meter broken. Decided by Claude
  under the owner's 2026-10-23 22:30 rule (DL-104): the date limits, one report per meter with no
  undo, utility_meters.manage. Tests: 4 database tests, 1 API test, TEST-FE-1068 to 1070 (new);
  TEST-FE-876 and TEST-FE-888 (changed: the lower-reading message; the kept found-broken day);
  head pins moved to 20270329_248. CI for 69c8a521 stopped at once because the migration gate
  list did not have tests/test_invoice_items_migration.py; fixed in 415fdc62, and the new
  Report broken file is in the list too. Runs on a new local test database: the new database
  tests, the Utility suites and the head-pin tests 117 passed; the upgrade tests with moved pins
  10 passed; backend lint, format and types passed; frontend 1,933 of 1,933; traceability passed.
  Open: no meter command (Add, Replace, Report broken) writes an audit event, so none shows on the
  History page; the meter page shows them.
- 2026-10-28 (B6, owner report of 13:12, DL-105): Issue the final Utility Invoice for U201
  showed "The hand-back was not saved". Cause: no Utility Rate was in effect on the generation
  date (BR-UTIL-015); Settings lets a new Rate start only on a reading day after today, so the
  Rates set on 27/10 started on 24/11/2026; the database refusal had no stable reason, so the
  route answered VALIDATION_ERROR and the dialog fell back to the hand-back text. Reproduced on a
  new local test database (only a future Rate: 422 VALIDATION_ERROR). The owner kept the rule for
  the first Rate (asked with a decision card; answered in words) and asked for the dates of the
  local test database to be changed by hand: a paste (tried on the local test database first)
  moves the Rates that start on 24/11/2026 to 24/10/2026 with tenants told on 20/10/2026, and the
  final Invoice then works. Built: the final and catch-up routes answer 422
  UTILITY_RATE_NOT_IN_EFFECT; the dialog says no rate is in effect and points to Settings, Rates
  and services; any other refusal says "This was not saved", never the hand-back text. Tests: 1
  unit test, 1 database test, TEST-FE-1071 (new). No migration.
- 2026-10-28 (B6, owner report of 13:38, DL-106): the Final Settlement of U201 said "Not ready
  yet. First: A Manager records the kept Deposit." The Lease ended before its End Date, so the
  whole Security Deposit is kept (BR-DEP-023) and the Settlement waits for the confirmed kept
  record; the keep draft route and its confirm existed since slice 11c-3, but no screen called
  the route. Built: "Record kept Security Deposit" (or Pet Deposit), marked Manager, on the Final
  Settlement step for a person with deposits.dispose; the dialog names the amount and the ground,
  asks for a reason and records the LEASE_FORFEITURE draft (same record id and key on Try again);
  while the draft waits, the step says it waits for approval with a link for an approver. Tests:
  TEST-FE-1072 and TEST-FE-1073 (new). No migration and no backend change.
- 2026-10-28 (B6, owner question of 14:30, "how about after closure"): the owner closed the
  Final Settlement of U201 and asked about step 6. Answered: nothing is due; step 6 is only for a
  charge found later (a correction draft that the Owner or a Manager confirms); a refund after
  closure comes later; money that stays owed is received in Payments as usual. Built (screens
  only; decided by Claude under the owner's 2026-10-23 22:30 rule): after closure step 6 says
  "The move-out is finished. Use this step only if something comes up later." and its mark says
  "If needed" instead of "Now". Tests: TEST-FE-998 (changed). No migration.
- 2026-10-28 (B6, owner report of 16:07, DL-107): New Lease on the Unit page opened only the
  Leases list, and some buttons looked like text boxes (a secondary button was Paper with the
  same grey edge as a text box). Built (screens only; decided by Claude under the owner's
  2026-10-23 22:30 rule): New Lease opens the New Lease form with that Unit chosen (or the draft
  from its Booking); Open Lease, Open draft Lease and Open Reservation open that record; every
  button has a light green fill, green words and a green edge (also the switch rows, the square
  icon buttons and the calendar buttons), checked in light and dark. Tests: TEST-FE-1074,
  TEST-FE-1075 and TEST-FE-1076 (new), TEST-FE-029 (changed). No migration.
- 2026-10-28 B6 result (owner, 16:07): "Everything good. only automatic billing. I will wait to
  see it later. I can say V1-060 session passed." B6 passed. The automatic billing runs on its
  own dates, so the owner watches it when it runs. Next: B7, merge into
  `implementation/foundation` once CI is green on the final commit.
- 2026-10-28 B7 (owner yes on the merge card, 16:35: "Yes, merge after the checks"): the final
  review of all B6 fixes (backend, money screens, Reports screens) found that Sign Lease saved its
  money, signatures, signing, Initial Rent Invoice and Security Deposit as seven requests (a lost
  answer could take the money twice or leave a Lease signed without its Initial Rent Invoice, and
  the money paid the oldest Invoices first), and smaller points. Built (DL-108, migration
  20270330_249; decided by Claude under the owner's 2026-10-23 22:30 rule, no money rule): Sign
  Lease is one database transaction (`POST /leases/{lease_id}/sign-with-payment`,
  `app.sign_lease_with_payment`; the DL-100 Initial Rent Invoice route and the DL-101 apply route
  are removed); Receive Security Deposit and Make Reservation send the very same request on Try
  again, and 408, 429 and 5xx count as no answer; Make Reservation stops less than the suggestion
  before any money without `reservation_deposits.override` and fixes the Rent with the money; New
  Lease and Edit draft save the draft's Security Deposit as its own step with Try again; real-day
  checks in Terminate, Inspection, Meters and Letters; Reports Totals count whole months, the
  footer Total label, the Audit chart title and the chart column label; drop-down arrows, small
  text contrast and the dark chart colour. Tests: 10 new database tests, 6 new API tests,
  TEST-FE-1077 to TEST-FE-1089 (new; TEST-FE-1081 is in the reservation client tests, which the
  manifest does not list), TEST-FE-850, 851, 853, 1018, 1020 and 1040 (changed); the two API
  tests of the removed routes are gone. Follow-ups (not built): Make Reservation and Receive
  Security Deposit still save the money and the record as two requests (each safe to try again);
  `POST /leases/{lease_id}/sign` still signs without money (the screen no longer uses it); the
  planned Security Deposit save has no If-Match; the DL-101 change of the required amount at
  signing is kept to once per Lease by an audit lookup, not a database constraint; Add occupant
  counts only the people listed, so a draft that planned nobody can reach 21 with the Primary
  Tenant while Record move-in takes at most 20; the Utility consumption report count mixes rows
  and grouped lines; dates that look right but do not exist pass some other screens' format
  checks (the server refuses them). TEST-FE-918 (Payments reprint) failed once in about 20 runs:
  intermittent, like TEST-FE-087, TEST-FE-128 and TEST-FE-488.
- 2026-10-28 B7 second review (DL-109): independent reviews of DL-108 (the Sign Lease command, the
  money screens, the Reports screens). Found: a draft from a Reservation that later ended (cancelled
  or expired) was signed as a walk-in with no Security Deposit, and the command changed the ended
  Reservation's Security Deposit; some definite refusals inside the command were answered as not
  known (503); after a lost answer, Receive Security Deposit and Make Reservation let the money be
  changed and sent as a new Payment; and smaller points. Built (migration 20270331_250; decided by
  Claude under the owner's 2026-10-23 22:30 rule, no money rule): Sign Lease locks the Unit, the
  active Reservation and the Security Deposit first, refuses such a draft before any money
  (SIGNING_RESERVATION_ENDED), applies the draft's amount only to the Security Deposit it took and
  ends with exactly one Security Deposit received in full; an error inside the command is a refusal
  (SIGNING_DATES_TAKEN, SIGNING_PAYMENT_SOURCE_GONE, SIGNING_REFUSED) and only a deadlock, lock
  wait, timeout, lost connection or failed commit is not known; the two money dialogs keep every
  money box fixed after a lost answer, stay not known after 401, 403 or 404 on Try again, say when
  the money is saved but the rest is not (with the Receipt), ask once more on Close while the money
  may be saved, and Make Reservation looks up its own Reservation after a lost answer, keeps no Unit
  that is not vacant and waits for the person's rights before less than the suggestion; the Lease
  page says when a draft's Security Deposit is being read or could not be read; closing Sign Lease
  reads the Lease again; date boxes add slashes only at the end and take no year before 1900; Escape
  on the calendar closes only the calendar; Reports footer "Total, all rows", the Total Payment
  note, Pick dates keeps the typed days, one chart label; the older forms' drop-downs keep their
  arrow. Tests: 7 new database tests, 1 new API test, TEST-FE-1090 to TEST-FE-1094 (new;
  TEST-FE-1095 is in the reservation client tests, which the manifest does not list), TEST-FE-851,
  1040, 1082, 1086 and 1088 (changed); scripts/database-test.sh runs the new database test file.
  Owner question (open): should a draft whose Reservation ended be signed as a walk-in Lease with a
  new Security Deposit? Until then it is refused. Follow-ups (not built): `POST
  /leases/{lease_id}/sign` still signs without money; a planned Security Deposit save of the amount
  already planned does not keep its id from reuse; the signing time is a moment before the Payment
  time (same transaction); a retry after the person lost a right is refused though the first request
  was saved; the signing preview does not give the total for a walk-in draft whose Customer holds an
  active Reservation of the Unit; Khmer screens show the server's English words for some refusals;
  the Edit draft deposit box does not follow a changed Rent; This month on a Totals table shows the
  days, not the whole month; Letters and Record notice give the order message for a date that is not
  a real day; one such test per dialog; the hover colour of chart columns.
- 2026-10-28 B7 third review (DL-109): an independent review of the DL-109 work (the Sign Lease
  command and route, the money screens). No serious find; its smaller points are built (no new
  migration; decided by Claude under the owner's 2026-10-23 22:30 rule, no money rule): Sign Lease
  answers `SIGNING_DATES_TAKEN` only for the signed-Lease dates check
  (`leases_signed_period_exclusive`) and `SIGNING_REFUSED` for another exclusion check; a way of
  payment switched off after the dialog opened is `SIGNING_PAYMENT_SOURCE_GONE` ("switched off");
  after a lost answer a Try again that never leaves the browser stays not known in Receive Security
  Deposit and in both steps of Make Reservation, and in its Reservation step "not signed in", "not
  allowed" and "not found" also stay not known, with no lookup; Escape only asks while the money
  may be saved, and only "Close anyway" closes (a held key counts once); closing Receive Security
  Deposit reads the Lease again and closing Make Reservation reads the list again; the money saved
  but the Reservation refused as changed no longer asks to change the Unit or the Customer; the
  Make Reservation Payment memo no longer depends on the screen language; a whole day pasted as
  eight digits gets its slashes. Tests: 2 new database tests (another Customer holds the Unit; a
  way of payment switched off); the two ended-Reservation tests now plan the Security Deposit at
  the money received (the case signed with no Security Deposit before); the API test of command
  errors (changed); TEST-FE-1096 to TEST-FE-1104 (new) and TEST-FE-1091 (changed: a fixed clock).
  Follow-ups (not built): Sign Lease and Cancel or expire Reservation lock in a different order, so
  a deadlock answers Sign Lease as not known (safe to send again) or fails that expiry run; a
  Reservation past its expiration day is refused only after the Payment step inside the command
  (nothing is saved); the signing preview still offers an ended Reservation's Security Deposit, and
  the refusal could say that a new draft is needed; after a lost Payment answer in Make
  Reservation a first refusal on a later step shows not known; Back, reload or a link leave a money
  dialog without asking; the Reservation lookup reads "not found" as none even after the person's
  rights changed; a Try again after another person signed in on the same screen can read a refusal
  as not saved.
- 2026-10-28 22:12 UTC B7 done: CI run 517 passed on `df3ec76d`, and `implementation/foundation`
  was fast-forwarded from `a7f36455` to `df3ec76d` (no force), with the owner's yes on the merge
  card. The owner got the update steps (pull; restart the API with `sh scripts/local/migrate.sh`
  first, for migration 20270331_250; reload).
- 2026-10-29 owner answer (decision card "Should a draft be signed after its Reservation ended?"):
  "Keep refusing". Such a draft stays refused (`SIGNING_RESERVATION_ENDED`); staff make a new
  draft, and the ended Reservation keeps its own Security Deposit (DL-009). The DL-109 owner
  question is closed; no code change.
