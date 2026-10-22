# V1-056 login sub-slice L3a-1 — password sign-in, the session read and sign-out — review record

Sub-slice L3a-1 of the login slice (ops/V1_056_PLAN.md section 7.3, L3a split into L3a-1 and
L3a-2). No migration. Base commit: d0e12bd (L2d). Built on 2026-10-23 in the same session as L2d.
Not pushed. The commit hash is in `git log` (this record is part of that commit).

## Placement

L3a is split (the owner allows splitting a large sub-slice): L3a-1 builds sign-in, the session
read and sign-out; L3a-2 builds the per-request actor resolver and its wiring. Until L3a-2 the
resolver still denies everyone, and the L1c ordering rule keeps every build between L3a and L5
unused.

## Built

- New `backend/src/property_rental/auth_flow.py`: `PostgresAuthenticationFlow` (login,
  inspect_session, logout; the MFA, enrollment, reauthentication and recovery-code methods answer
  unavailable until L3c and L3d).
  - Sign-in: the existing `LocalAuthenticationService` (Argon2id, dummy verifier, one generic
    rejection) with a lookup in its own short connection, and the existing in-memory limiter as a
    coarse flood guard (20 tries per username, 100 per source, 15 minutes).
  - MFA policy `required`: phase `mfa_required`, an unstored pre-authentication token, no session.
  - MFA policy `optional`: a session row with the sha256 digest of a random 32-byte token (the
    token only in the cookie) and a new CSRF token; the password is checked again against the
    current verifier in the session transaction (review round 1).
  - Session read: only a session that is not revoked, before both expiries by the database clock,
    of an active, classified account with MFA policy `optional`; no activity recorded.
  - Sign-out: revokes a session that is not revoked and before both expiries (reason `logout`, by
    its own account).
  - 5-second connect timeout; database errors answer 503; nothing secret or the username logged.
- `auth_api.py`: `SessionView` and `SessionData` gain `display_name`; `LoginRequest.username` is
  at most 128 characters.
- `app.py`: `create_app` uses `PostgresAuthenticationFlow` when `APP_DATABASE_URL` is set and no
  flow is given.
- Tests: unit `test_auth_flow.py` (4); PostgreSQL `test_auth_flow_migration.py` (8, last in
  `scripts/database-test.sh`). Traceability: 12 entries appended, one of my new notes reworded.
- Docs: docs/005 API-096 pointer and API-097 note; docs/010 DL-081 (L3a-1 and "Updated tests"
  lines); plan section 7.3 (pre-code design, as-built lines, bindings under L3c and L4); the
  questions file (Q-2026-10-23-172, decided under the owner's 2026-10-22 rule).

## Decided by Claude Code under the owner's 2026-10-22 rule (Q-2026-10-23-172)

- The flood guard values until L3b (20 per username, 100 per source, 15 minutes, per process).
- The session read records no activity.
- The sign-in username is at most 128 characters.

## Committed tests changed (approved plan: the session shows the display name)

- `test_authentication_api.py::test_successful_local_login_sets_protected_session_and_csrf_cookies`
  and `test_authentication_api.py::test_authenticated_session_inspection_returns_only_bounded_non_secret_state`
  expect the new `display_name` key (their traceability entries are among the first 1,598 and are
  not changed). Reviewers of rounds 1 to 3 found nothing weakened.

## Read-only search for affected tests

- Tests that build `create_app` with a database URL: none calls `/api/v1/auth/*` (they pass their
  own actor resolver, or call only the health routes, whose app now builds the flow without a
  connection).
- Tests that list or count `app.browser_sessions` rows (`test_migrations.py`,
  `test_access_administration_migration.py`) use their own databases; no grant, function or
  trigger changes.
- `test_authentication_api.py` (unit): two exact session shapes (changed above).

## Security checklist (security-and-hardening skill, as the owner asked)

- Trust boundary: the HTTP request (username, password, cookies, Origin, CSRF header).
- Assets: the password verifier, the session token, the grants.
- STRIDE: spoofing (Argon2id, sha256 token digest, random tokens from `secrets`); tampering
  (parameterized SQL only); repudiation (session rows keep who signed in and out and when);
  disclosure (one 401 body, no secrets in logs or answers, `no-store`); denial of service (bounded
  inputs, connect timeout, flood guard; database count in L3b); elevation (no session or actor
  before MFA where required; grants read fresh in L3a-2).

## Bindings for later sub-slices

- L4 (rounds 1 and 2): every password or sign-in code replacement and a session write that checked
  the old one must not both commit (today the second check leaves a gap between that read and the
  commit).
- L3c (round 2): a session only after the MFA challenge for any account with an active sign-in
  code enrollment, also with MFA policy `optional`.
- L3a-2 (round 3): a logout racing an activity update with a later time could break
  `CHECK (revoked_at >= last_activity_at)` and answer 503; handle it and test it.
- L3b and L7: the source key is the connecting address; behind a reverse proxy every person shares
  one source.

## Reviews

- **Round 1** (two fresh agents; after U1, T1 and P1).
  - Independent: no blocker. Should-fix: tests of the account conditions of the session read, a
    test of fail closed on a database error, a connect timeout. All done. Notes done: the first
    database test compares only its own rows; the unit docstring no longer claims no connection;
    docs/005 names the MFA policy condition.
  - Security: no blocker. Should-fix: a password reset racing a sign-in (the password is checked
    again in the session transaction; the rest is binding for L4), tests of disabled and
    MFA-raised sessions, of fail closed, and of the flood guard. All done.
- **Round 2** (one fresh agent, both checklists; after U2 and P2): no blocker; one text should-fix
  done (the L4 binding names every replacement path); notes taken as text (the L3c binding, a
  docs/005 API-096 pointer).
- **Round 3** (one fresh agent, both checklists): no blocker; one text should-fix done under the
  round-3 text rule (sign-out wording in docs/005, DL-081 and the plan: it revokes a session that
  is not revoked and before both expiries, whatever the account's state); text notes done (a test
  docstring, a flow docstring, docs/005 precision); binding for L3a-2 recorded.
- Notes kept: the 128-character limit applies before tidying (rare 422); the absolute expiry
  cannot be tested apart from the idle one (the table caps idle at absolute); signing in again
  does not revoke an older session; the in-memory limiter never forgets keys; no statement
  timeout until L3a-2; "similar timing" is not measured by a test (one verify on every refusal,
  two on a success).

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-login-L3a-1-`)

| Run | Result | Cause |
|---|---|---|
| FF1 (two files reformatted), I1 (one import order fixed), FC1, L1, Y1 | pass | backend checks |
| U1 | 3,898 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 5 passed | targeted: the new module |
| P1 | 2,521 passed | full PostgreSQL run |
| FF2 (two files reformatted), I2 (one import order fixed), FC2, L2, Y2 | pass | after the round 1 fixes |
| U2 | 3,899 passed | unit suite |
| M2 | pass | migration-only check |
| T2 | 7 passed, 1 failed | cause A (1 of 2): a test set-up updated a password credential without the actor and provenance the table requires |
| FF3, I3, FC3, L3, Y3 | pass | after the cause A fix |
| M3 | pass | migration-only check |
| T3 | 8 passed | targeted: the new module |
| P2 | 2,524 passed | full PostgreSQL run (before rounds 2 and 3) |
| FF4, I4, FC4, L4, Y4 | pass | after the round 3 text fixes |
| M4 | pass | migration-only check |
| T4 | 8 passed | targeted: the new module (round 3 docstring) |
| U3 | 25 passed | targeted unit: `test_auth_flow.py`, `test_authentication_api.py` (round 3 flow docstring) |

- Cause A used 1 of 2 corrections.
- No `LockNotAvailable` failure. P1 and P2 show only the known Starlette and pydantic warnings.
- After P2, only text changed: two docstrings, docs/005, docs/010, the plan, the questions file,
  this record and NOW.md.
- No frontend file changed.
- Still pending (not touched): the test rename in `test_deposit_receipt_refund_out_migration.py`.
