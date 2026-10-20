# V1-056 sub-slice 10i-3 — the Reservation extension approval time from the database clock — review record

Sub-slice: 10i-3, the last part of the Q-112 times sub-slice (owner answer (a) to
Q-2026-10-14-112 point 1). No migration. Base commit: the 10i-2 commit. Built on 2026-10-20 in
the same session as 10i-1 and 10i-2. Not pushed. The commit hash is in `git log` (this record is
part of that commit).

## Built

- `POST /reservations/{id}/extend`: the body is `notice_id`, `new_expiration_date` and the
  optional `reason_memo`; a body with `approved_at` is refused (422, `body.approved_at`); the
  route passes `approved_at=None`.
- `ReservationExtendCommand.approved_at` is optional; the service passes
  `COALESCE(%s::timestamptz,statement_timestamp())` to `app.extend_reservation_v2`, which replays
  a known request by key and digest before it reads the time.
- Screen and client: `ReservationExtendSource` drops `approved_at`; the extension form sends no
  time.
- Not changed: the Reservation's holding deposit `received_at` (Q-2026-10-20-147).

## Committed tests changed (covered by the answer: the request shape)

- `test_reservation_api.py::test_extend_requires_version_and_records_one_notice_shape`: the body
  drops `approved_at`; the in-memory flow stamps a fixed time when the route sends none.
- `test_reservation_worker_migration.py`: the extension payload drops `approved_at`; the expected
  notice reads its time from the response, and a new assertion checks that it equals the
  `created_at` of the extension's `reservation_commands` row (the statement time).
- `frontend/src/reservationClient.test.ts`: the extension source drops `approved_at`.

## New tests

`test_reservation_api.py::test_extend_route_takes_no_approval_time_from_the_request`;
TEST-FE-680 (`ReservationManagement.test.tsx`). Traceability: 2 entries appended; the first 1,598
entries untouched.

## Reviews

Round 1:
- Independent: clean. Notes: the PostgreSQL check uses the command row's `created_at`, not the
  Reservation's `updated_at` as the design said (the later cancellation in the same test
  overwrites `updated_at`; recorded in the plan as an implementer's reading); the service still
  accepts an explicit time (as for signing); no time-zone check on a given time (as before);
  old clients that send `approved_at` get 422 (documented in API-033).
- Security: clean. Notes: a retry across the deploy (its first digest carried the device time)
  gets a key-reuse conflict and writes nothing; the optional service time is reachable by no
  route.

No should-fix, so no round 2.

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-10i-3-`)

| Run | Result | Cause |
|---|---|---|
| FF1, I1, FC1, L1, Y1 | pass | backend checks |
| FEF1, FEFC1, FEL1, FEY1, FET1 | pass | frontend format, format check, lint, type check, tests (1,599) |
| U1 | 3,870 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 27 passed | targeted, the three Reservation modules |
| P1 | 2,430 passed | full PostgreSQL run |

No failed check or run; no correction. After P1 only text changed (plan, docs/010, this record,
NOW.md).
