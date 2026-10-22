# V1-056 login sub-slice L2b-2 — the PostgreSQL administration flow — review record

Sub-slice L2b-2 of the login slice (ops/V1_056_PLAN.md section 7.3). No migration. Base commit:
2c464fd (L2b-1). Built on 2026-10-22 in the same session. Not pushed. The commit hash is in
`git log` (this record is part of that commit).

## Built

- New `backend/src/property_rental/access_admin_flow.py`:
  - `PostgresAccessAdministrationFlow`: one READ COMMITTED transaction per call; changes only
    through the audited `app.admin_*` functions (never the L1d functions); the session's actor as
    the Owner (a malformed id is a 403 before any call); the request id as the audit correlation
    id (a UUID5 of it in a fixed namespace when it is not a UUID). Every account and bundle change
    and every Settings access change reads its result back and checks it inside the transaction
    (class, MFA policy, version, each changed field, names, Property, Settings access state), so a
    failed check rolls back. Assignments, removals and revocations are checked by the value the
    function returns (the runtime role cannot read those relations).
  - Reads: accounts and bundles through the Owner-only definer reads; the capability list (bundle
    capabilities only) and the authorization history (the `identity.manage_access` audit events of
    the Property, oldest first, time-and-id cursor) after the database's Owner check; account,
    bundle and history lists answer 404 for another Property.
  - Names: the API trims white space at either end (L2b-1); the flow makes names NFC and folds
    runs of space separators inside into one space; control characters and line breaks inside
    reach the database check. A username is NFC, lower case, and has no white space but U+0020.
  - Error mapping: stable codes with fixed plain messages, never database text (docs/005 API-080
    note): only the Owner check's 42501 is a 403; P0002 404; 40001 412 `STALE_VERSION`; known 23505,
    55000, 22023 and 23514 messages and constraint names to their codes; other 23505, 22023, 23514
    and 40P01 to generic codes; `DataError` 422 (checked last, because psycopg raises every class 22
    error as `DataError`); anything else 503.
  - `PostgresAccessAdministrationScopeReader` (the Owner's `user_account` and `role_bundle` object
    scopes; none for any other actor; 503 on any other error) and `with_administration_scopes`.
  - The Owner's reset stays unavailable until L4.
- `access_admin_api.py`: `AccessAdministrationRejected`; `app.py`: its handler (the standard error
  envelope) and the Postgres flow wired when `APP_DATABASE_URL` is set.
- New owner question Q-2026-10-22-169 (hidden characters in names and reasons, username NFC and
  look-alikes; recommendation (a); nothing waits).
- Tests: PostgreSQL `test_access_admin_flow_migration.py` (8 tests on one throwaway database at
  head, last in `scripts/database-test.sh`); unit `test_access_admin_flow.py` (5 tests).
  Traceability: 13 entries appended.
- Docs: docs/005 API-080 notes; docs/010 DL-081 L2b-2 line; plan section 7.3 (pre-code design and
  the as-built and review bullets).

## Committed tests changed

None.

## Read-only search for affected tests

- No migration, so no catalog, privilege, truncate or head-revision test changes.
- `create_app` now uses the Postgres flow when `APP_DATABASE_URL` is set, as in the PostgreSQL
  runs: no committed test outside `test_access_admin_api.py` (a unit module, run without the
  variable) and the route inventory test calls the administration routes.

## Reviews

- Round 1 (two fresh agents). Independent: no blocker; three should-fix (control characters folded
  into spaces; incomplete update result checks; missing tests for reachable codes, rollback and the
  message keys). Security: no blocker; two should-fix (the history and capability reads had no
  database Owner check; usernames with Unicode spaces could look alike, and NFC differs from
  sign-in). All done, as in the plan's round 1 bullet; notes for L3a, L3d and Q-169 kept there.
- Round 2 (one fresh agent, both checklists): no blocker; one should-fix (text: the API trims white
  space at either end), done. Notes taken: create checks inside the transaction, history 404 for
  another Property, a scope reader connection-error test, traceability wording.
- Round 3 (one fresh agent, both checklists; after U5 and P3): no blocker, no should-fix. Notes
  taken as text (docs/005 404 wording, a traceability note). Process note: the round 3 agent ran
  one no-op `python3 -c 1` while counting entries, against its read-only instruction; it wrote
  nothing and touched no database.

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-login-L2b-2-`)

| Run | Result | Cause |
|---|---|---|
| FF1 (three files reformatted), I1, FC1 | pass | backend checks |
| L1 | fail | cause A (1 of 2): the file tool turned `\u` escapes into literal characters (RUF001, a no-break space) |
| Y1 | fail | cause B (1 of 2): redundant casts and a list without a type annotation |
| FF2, I2, FC2, L2, Y2 | pass | after the cause A and B fixes |
| U1 | 3,885 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 4 passed, 3 failed | cause C (1 of 2): psycopg raises 22023 as `DataError`, which the mapping checked first |
| FF3, I3, FC3, L3, Y3 | pass | after the cause C fix |
| T2 | 7 passed | targeted: the new module |
| U2 | 3,885 passed | unit suite |
| M2 | pass | migration-only check |
| P1 | 2,508 passed | full PostgreSQL run |
| FF4, I4, FC4, L4, Y4 | pass | after the round 1 fixes |
| T3 | 8 passed | targeted: the new module |
| U3 | 3,885 passed, 1 failed | cause D (1 of 2): the new message test expected two constraint keys; there are three |
| FF5, I5, FC5, L5, Y5 | pass | after the cause D fix |
| U4 | 3,886 passed | unit suite |
| M3 | pass | migration-only check |
| P2 | 2,509 passed | full PostgreSQL run |
| FF6, I6, FC6, L6, Y6 | pass | after the round 2 fixes |
| T4 | 8 passed | targeted: the new module |
| U5 | 3,886 passed | unit suite (before round 3) |
| M4 | pass | migration-only check |
| P3 | 2,509 passed | full PostgreSQL run (before round 3) |

- One correction each for causes A, B, C and D (each 1 of 2).
- No `LockNotAvailable` failure. P1 to P3 show the known pydantic and Starlette warnings of
  unchanged modules.
- After P3, only text changed: docs/005, the plan, traceability, this record and NOW.md.
- No frontend file changed.
