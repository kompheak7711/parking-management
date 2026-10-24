# V1-059 part B — Meter units and serials, Customer ID number, document numbers — review record

Built on 2026-10-24 in a cloud session on the work branch `claude/project-thread-42lf25`, after
part A was merged into `implementation/foundation` as ebc0b7a (DL-082). The owner chose "Start
all of part B now" on 2026-10-24 13:27, before V1-056 slices 11 and 12; that choice is also the
owner's go-ahead for the two tightening checks (Customer ID number, Meter serial). Scope:
DL-071 answers 9 to 12 with the DL-075 amendment. Nothing ran on the office computer or on
real data. No decision log number yet: the merge gives this work its DL number.

## Built

- Step 1 (05b6ca7, migration `20270205_193`): `measurement_units.py` fixes the unit code from
  the Utility Type (`KWH` for electricity, `M3` for water) for Meter installs and Utility rates
  and refuses another code; the screens show kWh and m³. The trigger
  `utility_meters_serial_unique` refuses a new Meter whose serial (spaces and dashes removed,
  any case) is used by any Meter of the Property, replaced Meters included, under a lock per
  Property; the API answers 409 `METER_SERIAL_NUMBER_IN_USE`.
- Step 2 (e2c8633, migration `20270206_194`): `customers.id_document_number` with a unique
  index on its compared form; new create and update functions (required on create, never
  cleared); the audit records only that the number was recorded or changed. The API answers 409
  `CUSTOMER_ID_NUMBER_IN_USE` with the existing Customer's id and name (never the number). The
  number shows in the Customer detail only (not the list, search or exports). Screens ask for it
  on create and allow a correction on update; an older Customer shows "Not recorded yet".
- Step 3 (migration `20270207_195`): `app.document_number_series` (INV, RCP, RFD; 2 to 5
  capital letters, all different) and `app.document_number_counters` (one per type and Phnom
  Penh year, forward only); `app.next_document_number`. Triggers give the number: an Invoice at
  issue (a DRAFT keeps its internal reference, also kept in `draft_reference`), a Payment at
  confirmation (RCP) and its Receipt the same number, a Refund when it is recorded (RFD). The
  check `receipt_number = 'R-' || id` is dropped. Three functions that returned the number they
  wrote now read it back. The Reservation Deposit draft bodies no longer take `refund_number`
  (422 if sent); the draft carries `DRAFT-<outcome id>`. The frontend Receipt check accepts a
  Receipt that has its Payment's number (or an earlier `R-<id>`).
- Docs: "Built in V1-059 part B" lines in docs/004 and docs/005.
- `scripts/database-test.sh` lists the three new PostgreSQL suites.

## Decided by Claude under the owner's 2026-10-23 22:30 rule (no money, no who-may-do-what)

1. A DRAFT Invoice keeps its internal reference (RENT-..., UTIL-..., INV-yyyymmdd-...) in
   `invoice_number` until it is issued, so no reader needs a null number; the INV number then
   replaces it and the reference stays in `draft_reference`. Staff see the reference on draft
   screens; a Customer never sees a draft. A clearer draft label is left to the screen rebuild.
2. The number year is the Phnom Penh date of `issued_at` (Invoice), `confirmed_at` (Payment and
   Receipt) and `processed_at` (Refund).
3. The counter row stays locked until the transaction ends, so a rolled-back issue leaves no gap.
4. Earlier records keep their numbers; each counter starts after the highest number already
   used in the new format.
5. ID number: 1 to 64 characters, compared without spaces and dashes and ignoring case.

## Review round 1 (one independent agent, read-only)

- No blocker. It checked the trigger order on all four tables, that every function writing an
  old-format number only writes it into the column the trigger overwrites, and the migration
  safety of 193 to 195.
- Should-fix, both done: (1) the earlier create functions without the ID number were still
  open to the runtime role: EXECUTE revoked in `20270206_194` (new test
  `test_the_runtime_role_cannot_create_a_customer_without_the_number`); (2) the counters started
  empty, so a staff-typed Refund number such as `RFD260001` would have blocked every Refund of
  the year: `20270207_195` starts each counter after the highest number already used.
- Notes left: a Reservation Deposit draft saved before 195 with a typed number gets an RFD number
  at confirmation without telling staff (no real data yet); when two creates race past the
  friendly check, PostgreSQL's unique-violation detail holds the compared ID number and may reach
  the database server log (V1-060: check the server log settings before go-live); the replay
  table keeps the number for the replay window; a replacement Meter copies the failed Meter's unit
  code (only KWH and M3 exist); one counter row per type serializes issues of that type (no
  deadlock pair found); the draft reference `INV-yyyymmdd-...` looks like a number; the Payment
  allocation tie-break by `invoice_number` (same due date and same issue time only) compares text,
  so `INV2610000` sorts before `INV269999`; the large-names allocation test no longer tests the
  proposal byte limit with long Invoice Numbers (an issued Invoice's number is short now).

## Runs (logs in ~/prm-run-logs/ of the cloud container)

| Run | Result |
|---|---|
| P1 targeted PostgreSQL run (64 files) | stopped by the 30-minute background limit |
| P2 same with names, on a reused dev database | 35 failed, 1,678 passed |
| P3 the 35 failures on a fresh database | 11 failed: 4 configuration tests (a Service code left by an earlier file in this run order; they pass when the file runs first, and CI runs files in the script's order), 3 statement timeouts under CPU load, 4 real (old Refund numbers in a ledger test, a fixed Meter serial reused across Units in two tests, an allocation test that read Invoice Numbers before issue): fixed |
| Fresh database: configuration, utility API, deposit API, allocation tie-break | 44 passed |
| P4 timeouts again, allocation file, customer files, test_migrations, new suites | 3 failed, 218 passed: 2 statement timeouts (`test_credit_application_bounded_proposal_continues_same_invoice_without_losing_intent`, `test_financial_action_context_database_complete_500_line_sources_and_stale_pages`) also fail on a fresh database with the foundation code at ebc0b7a in this container, so they are not caused by part B; 1 real: the large-names allocation test expected long Invoice Numbers in the proposal, which issued Invoices no longer have (now 100 targets either way; 2 passed) |
| U2 full backend unit run | 1 failed (`database-test.sh` did not list the new suites: fixed; 14 passed after), 4,039 passed |
| F1 frontend full run (during the backend runs) | 1 timeout (TEST-FE-394, passes alone; V1-060 flaky list), 1,639 passed |
| Frontend lint, typecheck, format, build | clean |
| Backend ruff check, ruff format, mypy | clean |
| P5 every suite (`scripts/database-test.sh`, fresh database, after the push) | 9 failed, 2,680 passed in 1 h 32 min: 3 upgrade tests compared whole Invoice rows before and after the upgrade and now leave out the new `draft_reference` (and `id_document_number`), as they already did for migration 64's columns; 6 statement timeouts late in the long run (the 2 known ones and 4 settlement tests) |
| P6 the 9 on a fresh database | the 3 upgrade tests and the 4 settlement tests: 12 passed (with the rest of their files); the 2 known timeouts fail on the foundation code too |
