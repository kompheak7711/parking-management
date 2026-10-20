# V1-056 sub-slice 10i-4b — the Reservation holding deposit's receipt and acceptance time from the database clock — review record

Sub-slice: 10i-4b, the second part of sub-slice 10i-4 (owner answer (a) to Q-2026-10-20-147). No
migration. Base commit: c5f1588 (10i-4a). Built on 2026-10-20 in the same session as 10i-4a. Not
pushed. The commit hash is in `git log` (this record is part of that commit).

## Built

- `POST /properties/{property_id}/reservations`: `ReservationCreate` drops `received_at`
  (`extra="forbid"`, so a body that sends it is refused, 422 `body.received_at`); the route
  passes `accepted_at=None` and `received_at=None`.
- `ReservationCreateCommand.accepted_at` and `received_at` are optional; the service passes
  `COALESCE(%s::timestamptz,statement_timestamp())` for both to `app.create_reservation`
  (unchanged), so both are the one statement time. The request digest carries the two nulls, so
  a retry with the same key and body replays.
- Screen and client: `ReservationCreateSource` drops `received_at`; the create form sends no time.
- Not changed: the Payment's own `received_at`; the database checks.

## Committed tests changed (covered by the answer: the request shape)

- `test_reservation_api.py`: the two create bodies drop `received_at`.
- `test_reservation_worker_migration.py`: the create payload drops it; the expected receipt time
  is read from the response, and a new assertion checks that the receipt's `occurred_at` and the
  acceptance's `accepted_at` equal the `created_at` of the create's `reservation_commands` row; the
  Payment's confirmation time comes from the database clock (`database_now()`), because the
  receipt is now dated by the database and a receipt dated before its Payment's confirmation is
  refused (the container clock can lag the host clock); the unused `datetime` and `UTC` imports
  are removed.

## New tests

`test_reservation_api.py::test_create_route_takes_no_receipt_time_from_the_request`;
TEST-FE-681 (`ReservationManagement.test.tsx`). Traceability: 2 entries appended; the first 1,598
entries untouched.

## Reviews

Round 1:
- Independent: clean. Notes: the plan named API-031 and UI-034 (the right IDs are API-032 and
  UI-032; corrected in the as-built entry); the in-memory flow needed no fixed time (its create
  never reads the times); the worker test could pass `confirmed_at=None` (equivalent); the Q-112
  point 2 known limit now also covers the Reservation create (recorded).
- Security: clean. Notes (slice 12 list): a create waiting on a lock while the same Payment's
  confirmation commits can be refused (23514, 422, nothing written, a retry succeeds); a create
  waiting across Property-local midnight dates its receipt the day before its Reservation date (as
  the device time could).

No should-fix, so no round 2.

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-10i-4b-`)

| Run | Result | Cause |
|---|---|---|
| FF1, I1 (sorted one import), FC1, L1, Y1 | pass | backend checks |
| FEF1 | pass | frontend formatter |
| FEFC1, FEL1, FEY1, FET1 | failed to start | sent in one parallel batch with FEF1; npm read the repository root (`Could not read package.json`); no check ran |
| FEFC2, FEL2, FEY2, FET2 | pass | each alone from `frontend/` (tests 1,600) |
| U1 | 3,871 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 68 passed | targeted, the five Reservation database modules and the route tests |
| P1 | 2,435 passed | full PostgreSQL run |
| FEB1 | pass | frontend production build |

No failed check or run; no correction (the four failed starts ran no check). Process slip: the
frontend checks were sent in one batch instead of one at a time; each was then run alone. After
P1 only text changed (plan, docs/010, this record, NOW.md).
