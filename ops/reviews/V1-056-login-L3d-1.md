# V1-056 login sub-slice L3d-1 — high-risk reauthentication of a session — review record

Sub-slice L3d-1 of the login slice (ops/V1_056_PLAN.md section 7.3, L3d; L3d split into L3d-1
and L3d-2, the 15-minute check on the routes). Migration `20270203_191`. Base commit: a9fa712
(L3c-2c-2). Built on 2026-10-24 in the same session as L3c-2b to L3c-2c-2. Not pushed. The
commit hash is in `git log` (this record is part of that commit).

## Backup

- After the L3c-2c-2 commit: `git bundle create --all` into the iCloud Drive folder
  `PRM-backups` (`prm-backup-2026-10-24-a9fa712.bundle`, 12,259,738 bytes, sha256
  `5ba0217daec2af9d9d55cbcd4a0893c846361805192566eb3103b6e6cb718681`), `git bundle verify` okay.

## Built

- Migration `20270203_191` (additive): `app.browser_session_reauthentications` (append-only, its
  insert guard, column grants).
- `auth_flow.py`: `reauthenticate` (wait, password, sign-in code, wrong tries counted for the
  username with the session as the source, one write transaction, a new CSRF token);
  `LIVE_SESSION` answers `reauthenticated_at`; `_open_secret` shared with the challenge.
- Tests: PostgreSQL `test_reauthentication_migration.py` (8 tests, two parametrized), last in
  `scripts/database-test.sh`. Traceability: 8 entries appended.
- Docs: API-097 and DB-AUTH-004 amendments, DL-081 lines, Q-2026-10-24-183 (decided under the
  owner's 2026-10-22 rule), plan.

## Committed tests changed

- The 27 head-revision strings (`20270202_190` to `20270203_191`) in 15 modules;
  `test_sign_in_wait_migration.py` moves `HEAD` (and its docstring) to `20270203_191`.
- `test_auth_flow.py::test_the_mfa_reauthentication_and_recovery_code_methods_stay_unavailable` is
  unchanged and still true (no database: unavailable).

## Read-only search for affected tests

- Every test of `reauthenticated_at`, `/reauthenticate` or `reauthenticate` (`test_auth_flow.py`,
  `test_auth_flow_migration.py` expects `None` after a sign-in, `test_authentication_api.py` with
  its own fake flow): no expectation changes.
- `LIVE_SESSION` and `session_view` are used only in `auth_flow.py` and `session_actor.py` (which
  reads the actor column only); the new column does not change them.

## Reviews

- **Round 1** (one independent and one security agent, read-only, during P1): no blocker.
  Should-fixes done:
  - **One reauthentication of an account at a time (both).** It runs on a connection lock
    (`pg_try_advisory_lock` on `reauthentication:` and the account). A parallel one answers 401
    without a password check; the wait is checked and a wrong try counted under the lock. Test
    set-up: the second call is made from inside the first call's password check.
  - **Lock order (independent S1).** In the write transaction the sign-in code and the account
    come before the session; the session is locked `FOR SHARE` last. So a disable or a recovery
    of the Owner's functions no longer deadlocks with it.
  - A guard refusal answers 401.
  - At most one reauthentication per sign-in code step (a unique index).
  - **Tests isolating each claim (independent S3):**
    - a wrong password during a wait is not counted;
    - signed in with the previous step;
    - the window cases `step_used` and `staff_code_off`;
    - a password-only account: a wrong password counted, a second reauthentication moving the
      time on;
    - each `totp` guard condition alone (another account's code with a real used step, a code
      turned off), with a raw positive control and the per-step uniqueness;
    - the `password` refusal for an account with MFA `optional` and an active code.
  - **Recorded:**
    - the session cookie is not replaced (security S2, Q-2026-10-24-183 point 5, slice 12
      list);
    - a binding for L3d-2: only `totp` reauthentications made after the latest password change
      count (security S3);
    - bindings for L4: the password replacement versus reauthentication rows, and the lock order
      of the Staff MFA-off.
  - **Notes kept:**
    - a reused sign-in code step counts as a wrong try (the screen should say "wait for the next
      code", L6);
    - a cookie thief's wrong tries also start the username's wait;
    - refusals are not linked to a session in the log;
    - the guard's step condition is "since the row's transaction began", now said so in the docs.
- **Round 2 (unfinished, 2026-10-24).** The security agent ran, read-only, during P2, and found
  no blocker. It confirmed the round 1 security fixes and accepted the Staff MFA-off deadlock as
  an L4 binding. Its should-fixes, not yet done:
  - **S-1:** the session cookie is not replaced at reauthentication. The CSRF double-submit check
    is not a compensating control, and `GET /auth/session` shows `reauthenticated_at` to a cookie
    thief. Owner answer (2026-10-24): build a separate reauthentication cookie, set only at
    reauthentication and required by L3d-2; this replaces point 5 of Q-2026-10-24-183. The
    reviewer's proposal: a `__Host-prm_reauth` cookie (HttpOnly, Secure, SameSite=Strict, Path=/)
    whose sha256 digest is stored on the `totp` row. Test: a copied session cookie in a second
    client is refused by a Q-157 route after the first client reauthenticates.
  - **S-2 (text):** the L4 binding "or L3d-2 ignores older rows" does not close the
    password-change race, because statement times are not commit times. Drop that alternative
    and require the L4 replacement to revoke the account's sessions in the same transaction. The
    reviewer's deterministic test: an uncommitted password `UPDATE` as the table owner, a
    reauthentication with the old password succeeds, then the commit.
  - **S-3 (low):** successful password-only reauthentications have no rate limit (each costs an
    Argon2id check and an append-only row). Refuse a second one within 60 seconds, before the
    lock and the hashing.
  - Notes:
    - L3d-2 must not use `SessionView.reauthenticated_at`, which also counts `password` rows;
    - the DL-081 line and the plan's build bullet still describe the old write order;
    - the connection-level advisory lock needs direct connections (no PgBouncer transaction
      pooling; a deployment note);
    - optional test: the lock does not cross accounts.

  The independent round 2 agent was blocked by the auto-mode checker at its start (reason
  "[Auto-Mode Bypass]"). It was not retried and the review was not done in the main session.
  Owner answer (2026-10-24): the cloud session runs review round 2 of L3d-1.

## Runs so far (logs on the Mac in ~/Development/prm-run-logs/, prefix `v1-056-login-L3d-1-`)

| Run | Result | Cause |
|---|---|---|
| FF1 (two files reformatted), I1, FC1, L1, Y1 | pass | backend checks |
| M1 | pass | migration-only check |
| T1 | 1 failed, 613 passed | cause A (1 of 2): the guard test read privileges in a transaction the expected truncate refusal had aborted |
| FF2, I2, FC2, L2, Y2 | pass | after the cause A fix |
| T2 | 48 passed | the reauthentication and sign-in modules |
| U1 | 3,924 passed | unit suite |
| P1 | 2,648 passed | full PostgreSQL run (before round 1) |
| FF3 (two files reformatted), I3, FC3, L3, Y3 | pass | after the round 1 fixes |
| T3 | 89 passed | the six auth modules |
| U2 | 3,924 passed | unit suite |
| M2 | pass | migration-only check |
| P2 | 2,651 passed | full PostgreSQL run (after round 1) |
