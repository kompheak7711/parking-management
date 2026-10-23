# V1-056 login sub-slice L3c-2c-1 — the first recovery codes and their regeneration — review record

Sub-slice L3c-2c-1 of the login slice (ops/V1_056_PLAN.md section 7.3, L3c; L3c-2c split into
L3c-2c-1 and L3c-2c-2, signing in with a recovery code). Migration `20270201_189`. Base commit:
3d5c4ca (L3c-2b). Built on 2026-10-24 in the same session as L3c-2b. Not pushed. The commit hash
is in `git log` (this record is part of that commit).

## Backup

- After the L3c-2b commit, because the power is not reliable today: `git bundle create --all`
  into the iCloud Drive folder `PRM-backups` (`prm-backup-2026-10-23-3d5c4ca.bundle`, 12,211,423
  bytes, sha256 `d9746d2e7cc9f8a578f18d4d05d96cff50471e8bc2260c3139d3c0e1759a98ff`),
  `git bundle verify` okay. No repository file changed for it.

## Built

- Migration `20270201_189` (additive): the partial unique index
  `recovery_code_sets_one_live_per_actor` (at most one set of an account that is not
  invalidated).
- `auth_flow.py` (as built after review rounds 1 and 2): `issue_recovery_codes` and
  `regenerate_recovery_codes`, each one READ COMMITTED transaction: a live session proven with
  the account's active sign-in code within 15 minutes by the database clock; the per-account
  `pg_try_advisory_xact_lock` (refused at once when held); no live set (issue) or the prior set
  locked `FOR UPDATE` (regenerate); at most 5 sets of the account in 15 minutes; then 10 codes
  from the existing generator with Argon2id verifiers; the prior set invalidated by the account
  itself, naming the replacement set; the new set and codes by the account itself; the session
  read again `FOR SHARE` and still proven with an active sign-in code. The new index's
  `UniqueViolation` answers 401. `RecoveryCodeSetData.codes` is `repr=False` (`auth_api.py`).
- Tests: PostgreSQL `test_recovery_code_flow_migration.py` (14 tests, one parametrized six ways
  and one two ways), last in `scripts/database-test.sh`. Traceability: 14 entries appended.
- Docs: DB-AUTH-003 and API-098 amendments, DL-081 lines, Q-2026-10-24-181 (decided under the
  owner's 2026-10-22 rule), plan.

## Committed tests changed

- The 27 head-revision strings (`20270131_188` to `20270201_189`) in 15 modules;
  `test_sign_in_wait_migration.py` moves `HEAD` (and the docstring that names it) to
  `20270201_189`.
- `test_auth_flow.py::test_the_mfa_reauthentication_and_recovery_code_methods_stay_unavailable` is
  unchanged and still true (no database: unavailable).

## Read-only search for affected tests

- Every module that writes `app.recovery_code_sets` (`test_migrations.py`,
  `test_recovery_code_issuance.py`, `test_recovery_code_regeneration.py`,
  `test_authentication_api.py`): each writes one live set per account, and the existing
  regeneration repository invalidates the prior set before it inserts the new one, so the new
  index changes no expectation.
- The bootstrap tests write one set for the Owner.

## Reviews

- **Round 1** (one independent and one security agent, read-only, during P1): no blocker.
  Should-fixes done (fail-closed refusals, a cheaper refusal and tests):
  - security S1: the first codes also need a sign-in code given in the last 15 minutes, so a
    session left open cannot take them later (and the person could not replace them);
  - both: every check, and for a regeneration the prior set's lock, runs before the slow
    hashing, all in one READ COMMITTED transaction;
  - security S2: a per-account `pg_try_advisory_xact_lock`, so one account's codes are made once
    at a time and a parallel request answers 401 without hashing;
  - a repeated code raises instead of looping; `RecoveryCodeSetData.codes` is `repr=False`;
  - tests:
    - a refused set costs no hashing (reviewer's set-up: `_new_recovery_codes` replaced with one
      that fails the test);
    - a sign-out while the codes are hashed. The reviewer's set-up (holding the account row) cannot
      place the sign-out there, because the sign-out's revocation waits for that row too, so the
      sign-out is made from inside the hashing step;
    - two parallel regenerations of one set (reviewer's set-up: the owner holds the account row);
    - a code of a replaced set refused by `app.perform_account_recovery`;
    - the codes never logged;
    - the refusals also for regeneration, a turned-off sign-in code and a recovery-code session
      (written as the table owner until L3c-2c-2).
  - Moved to bindings, as recorded in the plan:
    - security S3 (signing in with a recovery code must not try 10 Argon2id verifiers per
      attempt; the code format): binding for L3c-2c-2;
    - a read of the live set's id (so the Owner can replace the bootstrap's set): binding for L6;
    - a sign-in code reset also invalidates the live set: binding for L4.
  - Notes kept: refusals are logged without a reason; the runtime role can write recovery-code
    rows directly (column grants); the migration fails closed on a database with two live sets
    of one account.
- **Round 2** (one fresh independent and one fresh security agent, read-only, during P3): no
  blocker. Every round 1 fix is confirmed. The open transaction during the hashing is confirmed
  safe: no idle or lock timeout is set, and the statement timeout covers statements only. Done
  under the round-3 rule (tests, text, fail-closed refusals):
  - the regeneration refusals use a real live set written as the table owner, so only the session
    can refuse them (independent);
  - the per-account lock comes first in both methods, so the later checks see a parallel
    request's commit and a second regeneration is refused at once instead of waiting on the set's
    row (both, notes);
  - at most 5 sets of an account in 15 minutes, checked before the hashing (security S2; decided
    under the owner's 2026-10-22 rule, Q-2026-10-24-181 point 6);
  - the session read before the commit is locked `FOR SHARE` and checks the sign-in code again
    (security);
  - the invalidation names the replacement set (independent);
  - tests:
    - the hashing counted in the two parallel tests (`count_hashing`);
    - the 5-set limit (4 invalidated and 1 live set written as the table owner, made now or 16
      minutes ago);
    - the response model's printed form;
  - the stale design bullets and this record's counts are brought up to date (independent).

  Moved to bindings (plan):
  - L4: the reset takes the generation lock, blocking, before it invalidates the live set
    (security S1: a regeneration during a reset could otherwise leave a live set). The reviewer's
    test set-up: a regeneration paused after its hashing (a wrapped `_new_recovery_codes` waiting
    on an event) while the reset waits; then no set is live.
  - L6: the set-id read shows the set's time and origin, and the screen must not treat these 401
    answers as signed out.
  - L3d: whether a fresh reauthentication also opens the 15-minute window.
- **Round 3** (one fresh agent, both checklists, read-only, during P4): no blocker, no
  should-fix. Every round 2 fix is confirmed, and no lock cycle was found with
  `app.perform_account_recovery` or `app.admin_update_account`. Three text notes, done:
  - the order sentence of the DL-081 line;
  - the plan's tests bullet points to the review-round tests;
  - the L4 binding gives the reason the reset must take the advisory lock before any other
    lock, with the MFA-off test set-up.

  Kept (no action): the final read locks the session row, not the sign-in code row. Every path
  that turns a code off also revokes the session, so it waits for that lock.
- **Found while building (run T3):** an in-process alembic migration in the same test run turns
  existing loggers off (`fileConfig` in migrations/env.py), so the new log test turns the flow's
  logger on again. An earlier absence-only log check can pass without records: slice 12 list
  (plan).

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-login-L3c-2c-1-`)

| Run | Result | Cause |
|---|---|---|
| FF1 (two files reformatted), I1, FC1, L1, Y1 | pass | backend checks |
| U1 | 3,922 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 1 failed, 570 passed | cause A (1 of 2): the parallel test signed one account in twice in one 30-second step (each step is used once) |
| FF2, I2, FC2, L2, Y2 | pass | after the cause A fix (the previous and the current step) |
| T2 | 59 passed | the three MFA modules |
| P1 | 2,605 passed | full PostgreSQL run (before round 1) |
| FF3 (one file reformatted), I3, FC3, L3, Y3 | pass | after the round 1 fixes |
| T3 | 1 failed, 77 passed | cause B (1 of 2): the log test saw no records (the flow's logger turned off by alembic's `fileConfig` earlier in the run) |
| FF4, I4, FC4, L4, Y4 | pass | after the cause B fix |
| T4 | 78 passed | the five auth modules |
| U2 | 3,922 passed | unit suite |
| M2, P2 | not run | the implementer started them in parallel with U2 and both began in `backend/`, so the scripts stopped before any test (not a failure cause; containers removed) |
| M3 | pass | migration-only check, from the repository root |
| P3 | 2,613 passed | full PostgreSQL run (before round 2) |
| FF5 (one file reformatted), I5, FC5 | pass | after the round 2 fixes |
| L5 | fail | cause C (1 of 2): a line over 100 characters |
| FF6, I6, FC6, L6, Y5, Y6 | pass | after the cause C fix (Y5 ran before the fix, Y6 after) |
| T5 | 79 passed | the five auth modules |
| U3 | 3,922 passed | unit suite |
| M4 | pass | migration-only check |
| P4 | 2,614 passed | full PostgreSQL run (last) |

- After P4 only text changed: the round 3 notes (DL-081, plan), this record and ops/NOW.md.
- Only the known Starlette and pydantic warnings.
- Every saved run output scanned for secrets: only test and migration file names match.
- No frontend file changed.
