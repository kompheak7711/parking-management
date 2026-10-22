# V1-056 login sub-slice L3a-2 — the actor resolver — review record

Sub-slice L3a-2 of the login slice (ops/V1_056_PLAN.md section 7.3, second half of L3a).
Migration `20270127_184` (added in review round 1). Base commit: 24913e6 (L3a-1). Built on
2026-10-23 in the same session as L2d and L3a-1. Not pushed. The commit hash is in `git log`
(this record is part of that commit).

## Built

- New `backend/src/property_rental/session_actor.py`: `PostgresSessionActorResolver`. On every
  request with a session cookie, in one READ COMMITTED transaction:
  - record the activity (`last_activity_at = statement_timestamp()`), only for a session of an
    active, classified account with MFA policy `optional`, skipped when a parallel request already
    recorded a later one;
  - read the live session after that write (a session revoked or expired meanwhile gives no actor);
  - read the grants through `PostgresCapabilityGrantReader` (fresh on every request).
  - Then: the Owner's administration scopes on `identity.manage_access`, the actor's own `actor`
    scope on `identity.read_self`. No cookie, a bad token or no live session gives no actor (401);
    a database error or a catalog mismatch answers 503.
- `app.py`: `create_app(actor_resolver=None)` uses the resolver when `APP_DATABASE_URL` is set,
  otherwise denies everyone; tests keep injecting their own resolver.
- `auth_flow.py`: a 5-second statement timeout on every connection; sign-out unchanged except a
  comment (the trigger now covers the race).
- `access_admin_flow.py`: the Owner's scope read has the connect and statement timeouts.
- Migration `20270127_184` (review round 1, relaxing): `app.protect_browser_session_lifecycle`
  replaced with the same signature, owner, privileges and attributes; a revocation records
  `GREATEST(statement time, last activity)`.
- Tests: PostgreSQL `test_session_actor_migration.py` (3) and
  `test_session_revocation_time_migration.py` (3), both last in `scripts/database-test.sh`; unit
  `test_session_actor.py` (4). Traceability: 10 entries appended.
- Docs: docs/004 DB-AUTH-004 note; docs/005 API-097 note; docs/010 DL-081 (L3a-2 and "Updated
  tests" lines); plan section 7.3 (L3a-2 as built, rounds 1 to 3); the questions file
  (Q-2026-10-23-173, decided under the owner's 2026-10-22 rule).

## Committed tests changed

- The 27 head-revision strings (`20270126_183` to `20270127_184`) in 15 modules; nothing else.

## Read-only search for affected tests

- Tests that build `create_app` with a database URL and no resolver call only health or auth
  routes; with no session cookie the resolver gives no actor without a database, as before.
- Tests that list functions, triggers or grants of `app.browser_sessions`: only
  `test_migrations.py` (EXECUTE of the trigger function for `prm_runtime`, kept by
  `CREATE OR REPLACE`).
- No test sends a session cookie to a protected route except the new modules.

## Design change (under the design-change run rule; confirmed as needed and safe by review round 2)

1. Migration `20270127_184`. Every request now records activity, so a revocation whose statement
   started before a parallel activity committed broke `CHECK (revoked_at >= last_activity_at)` and
   rolled back. This covers sign-out and every Owner revocation (disable, Staff MFA raise, smaller
   bundle, assignment removal, explicit revocation, password and MFA resets), so a person who kept
   using the app could stop their own revocation (review round 1, security blocker). A revocation
   now records the later of its statement time and the last activity. The planned sign-out guard
   and second statement are not built.

## Reviews

- **Round 1** (two fresh agents; after U1, T1 and P1).
  - Security: one blocker (above), fixed by design change 1. Should-fix: timeouts on the Owner
    scope read; tests of the Owner branch, the scope-reader error and a catalog mismatch. Done
    (the Owner branch and the mismatch with stand-ins, because no Owner session can be resolved
    before L3c).
  - Independent: no blocker. Should-fix: the same race; the scope-read timeouts; the Owner branch
    untested; a real-database test of the sign-out race instead of a stand-in. All done.
  - Test set-up (reviewer's, as built): as the table owner, lock the session row `FOR UPDATE`;
    start the revocation in a thread; wait until `pg_locks` shows an ungranted lock (a row wait is
    a `transactionid` lock with no database; `pg_stat_activity` hides another role's wait from a
    role that is not a superuser); record an activity on the held row and commit; the revocation
    must succeed with a revocation time equal to that activity.
  - Notes done: the activity is recorded only for a usable session; 401 after sign-out on a
    protected route.
- **Round 2** (one fresh agent, both checklists; after U2 and P2): no blocker; design change 1
  confirmed; the race tests confirmed to reproduce the failing order. Should-fix, all done: the
  DL-081 line no longer said "no migration" (text); equality asserts in the race tests (test); a
  no-activity check for refused sessions (test); a docstring that claimed more than the test checks
  (text).
- **Round 3** (one fresh agent, both checklists; after U3 and P3): no blocker; one text should-fix
  done under the round-3 text rule (DL-081 records the round 2 confirmation and tests).
- Notes kept:
  - startup `options` replace any options in `APP_DATABASE_URL` and do not work behind a pooler
    in transaction mode (deployment note for L7);
  - a cross-site top-level GET (`SameSite=Lax`) also counts as activity;
  - resolver database failures are not logged;
  - an Owner audit row may be dated a few milliseconds before the session's revocation time;
  - the forward-only test reads the owner and ACL but does not assert them;
  - the lock watcher counts any ungranted lock with no database (a stray match makes the equality
    assert fail, never pass);
  - the Owner scopes are read on a second connection after the grants (reachable only from L3c).
- Bindings still open: L3c (a session only after MFA for any account with an active sign-in code
  enrollment), L4 (a password or MFA replacement and a racing session write must not both commit).

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-login-L3a-2-`)

| Run | Result | Cause |
|---|---|---|
| FF1 (two files reformatted), I1 (one import order fixed), FC1, L1 | pass | backend checks |
| Y1 | fail | cause A (1 of 2): a list in a new unit test did not match its parameter type |
| FF2, I2, FC2, L2, Y2 | pass | after the cause A fix |
| U1 | 3,902 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 11 passed | targeted: `test_auth_flow_migration.py`, `test_session_actor_migration.py` |
| P1 | 2,527 passed | full PostgreSQL run |
| FF3 (one file reformatted), I3 (one import order fixed), FC3, L3 | pass | after the round 1 fixes |
| Y3 | fail | cause A (2 of 2): the new unit test patched attributes through a module that does not export them |
| FF4, I4 (one import order fixed), FC4, L4, Y4 | pass | after the second cause A fix |
| U2 | 3,903 passed | unit suite |
| M2 | pass | migration-only check (new head `20270127_184`) |
| T2 | 510 passed, 2 failed | cause B (1 of 2): the race tests looked for the wait in `pg_stat_activity`, which hides another role's wait |
| FF5, I5, FC5, L5, Y5, M3 | pass | after the first cause B fix |
| T3 | 1 passed, 2 failed | cause B (2 of 2): the `pg_locks` query joined the database, but a row wait is a lock with no database |
| FF6, I6, FC6, L6, Y6, M4 | pass | after the second cause B fix |
| T4 | 3 passed | targeted: `test_session_revocation_time_migration.py` |
| P2 | 2,530 passed | full PostgreSQL run (before round 2) |
| FF7, I7, FC7, L7, Y7, M5 | pass | after the round 2 fixes |
| T5 | 6 passed | targeted: the two new database modules |
| U3 | 3,903 passed | unit suite (before round 3) |
| P3 | 2,530 passed | full PostgreSQL run (before round 3) |

- Cause A used 2 of 2 corrections; cause B used 2 of 2.
- T2 covered the 15 head-revision modules, `test_access_administration_migration.py` and the
  three session modules (512 tests).
- No `LockNotAvailable` failure. P1 to P3 show only the known Starlette and pydantic warnings.
- After P3, only text changed: docs/010, the plan, the questions file, this record and NOW.md.
- Process note: the P1 full run was started in the same message as the two round 1 review agents
  (not in the same call as another check).
- No frontend file changed.
- Still pending (not touched): the test rename in `test_deposit_receipt_refund_out_migration.py`.
