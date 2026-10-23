# V1-056 login sub-slice L3c-2b — setting up a sign-in code at sign-in — review record

Sub-slice L3c-2b of the login slice (ops/V1_056_PLAN.md section 7.3, L3c; L3c-2 split into
L3c-2a, L3c-2b enrollment and L3c-2c recovery codes). Migration `20270131_188`. Base commit:
634b5d5 (L3c-2a). Built on 2026-10-23 in the same session as L3c-2a, after the second power loss
of the day and its recovery check. Not pushed. The commit hash is in `git log` (this record is
part of that commit).

## Power loss and recovery (owner, 2026-10-23)

- The Mac mini lost power again after the L3c-2a commit; the working tree was clean, so no
  L3c-2b work was on disk and this sub-slice started from ops/NOW.md. Recovery check: `git
  status` clean on `implementation/foundation`, `git log` head 634b5d5, no stash, `git fsck --no-dangling` without errors, no `.git/index.lock`, Docker answering.
- Backup before building: `git bundle create --all` into the iCloud Drive folder `PRM-backups`
  (`prm-backup-2026-10-23-634b5d5.bundle`, 12,190,131 bytes, sha256
  `05c552aac464ccc8c76b676b0d3444a16349915b00564a93b952ccbd96da7b4d`), `git bundle verify` okay. No
  repository file changed for it.
- Not a failure cause; no correction allowance used.

## Built

- Migration `20270131_188` (additive): `app.sign_in_code_enrollment_starts` (the challenge as
  primary key, the account, the started pending sign-in code (unique, no foreign key, so the
  committed truncate refusal of `app.totp_mfa_enrollments` is unchanged), the start time;
  append-only; column grants to the runtime role only); its insert guard: an open `enrollment`
  challenge of the start's own account, the account active, classified, MFA `required` and no
  active sign-in code (the L3c-2a binding), and a pending code of that account made since the
  challenge. `app.check_browser_session_mfa_proof` replaced (same signature, owner and
  privileges), every earlier condition kept, one more accepted case: a `totp` proof of a
  completed `enrollment` challenge for the code it started, with a step used since the challenge
  (the L3c-2a binding).
- `auth_flow.py`: `begin_mfa_enrollment` (the open `enrollment` challenge read, the wait checked,
  then in one transaction the challenge locked, a start committed meanwhile seen by a new
  statement, the password verifier compared, an unconfirmed pending code of an earlier sign-in
  turned off by the account itself, a new 160-bit secret protected with AES-256-GCM under the key
  file and the key identifier derived from it, the pending row and the start; a `UniqueViolation`
  answers the generic rejection; the standard `otpauth://totp/` link answered once);
  `confirm_mfa_enrollment` (the started challenge of an account with MFA still `required`, the
  wait, the code for the current or previous step of the database clock, a wrong code counted;
  the right code in one transaction: the clear first, the pending code locked and activated, the
  step, the challenge completed, the verifier compared, the session and its `totp` proof, the live
  read back); the shared steps of `complete_mfa` moved into helpers without changing its order or
  answers; `LIVE_SESSION`'s `mfa_assurance` is `none` when the proof no longer counts.
- `runtime_secrets.py`: `derive_totp_key_identifier` (HKDF-SHA256, own purpose).
- Tests: unit `test_runtime_secrets.py` (1 new), `test_auth_flow.py` (1 new); PostgreSQL
  `test_sign_in_code_enrollment_migration.py` (19 tests, two parametrized), last in
  `scripts/database-test.sh`. Traceability: 21 entries appended.
- Docs: DB-AUTH-003 and DB-AUTH-004 amendments, API-096 amendment, DL-081 (L3c-2b and updated
  tests), Q-2026-10-23-179 (decided under the owner's 2026-10-22 rule), plan.

## Committed tests changed

- The 27 head-revision strings (`20270130_187` to `20270131_188`) in 15 modules;
  `test_sign_in_wait_migration.py` moves `HEAD` to `20270131_188` (and the docstring that names
  it).
- `test_sign_in_code_migration.py` (L3c-2a review round 3 notes): the lock-wait helper also needs
  the waiting connection to belong to the test database (joined with `pg_stat_activity` on the
  pid), and its two thread tests wait up to 10 seconds instead of 3; no assertion changed.
- `test_auth_flow.py::test_the_mfa_reauthentication_and_recovery_code_methods_stay_unavailable` is
  unchanged and still true (a flow without the protection key answers unavailable for begin and
  confirm).

## Read-only search for affected tests

- Every module naming `browser_session_mfa_proofs`, `totp_used_steps` or `sign_in_mfa_challenges`:
  only `test_sign_in_code_migration.py`.
- Every test of `mfa_assurance`, the enrollment routes or methods
  (`test_authentication_api.py` uses its own fake flow; `test_initial_owner_bootstrap_cli.py`
  lists the routes; `test_auth_flow.py`): no expectation changes.
- No inventory test lists the authentication tables or functions; the log event label list of
  `test_access_control.py` is unchanged (no new event label).

## Reviews

- **Round 1** (one independent and one security agent, read-only, during P1): no blocker.
  Should-fixes done:
  - Security: the start compares the current password verifier with the one the sign-in
    checked, so a sign-in from before a password reset starts nothing (reviewer's set-up: token A,
    a new verifier written as the table owner, token B with the new password started, then A
    refused; B's code still pending and nothing replaced).
  - Independent: the start checks the wait before the transaction that locks the challenge; it
    sees a start committed meanwhile in a new statement after `FOR UPDATE OF challenge`; a
    `UniqueViolation` answers 401 instead of 503 (reviewer's set-up: the owner holds the
    challenge row, two starts of one token, then commit).
  - Independent: the first code needs MFA still `required`, because MFA turned off while a start
    commits can leave the started code pending (set-up: MFA made `optional` by hand after the
    start).
  - Independent: `FOR SHARE` taken out of `ACTIVE_ENROLLMENT_OF`. It takes the code row before
    the account row and can deadlock with `app.admin_update_account`. This is a design change: the
    L3c-2a round 3 note is not built, and the sign-in keeps its fail-closed 503. Confirmed by
    round 2.
  - Tests:
    - a start during a wait (three wrong tries recorded on the runtime role with the stored
      digests);
    - the two tokens do not cross;
    - a code turned off while the first code waits (the owner's uncommitted disable);
    - each condition of the new proof case alone, with a positive control (a started, activated,
      completed challenge with no used step, then a step; a second challenge that started
      nothing, then the starter);
    - the start guard's pending condition alone, and the second start meeting the primary key;
    - the 129-character token stored as a real challenge.
  - Notes kept:
    - the admin races rest on the foreign-key `KEY SHARE` lock of the account row;
    - a never-confirmed pending code counts as live in the recovery audit (cosmetic);
    - the start guard's expiry, completion and account-state conditions are reached through the
      flow only;
    - N5 (anyone with the password of an account without a code can set one up; by DL-056)
      becomes Q-2026-10-23-180.
  - Binding added for L4: the password replacement also covers the first code and the start; the
    runtime role cannot row-lock `app.user_accounts` or `app.password_credentials` (SELECT only),
    so that needs a definer function or a column grant.
- **Round 2** (one fresh independent and one fresh security agent, read-only, during P2): no
  blocker. Every round 1 fix and both design changes confirmed. Done under the round-3 rule (a
  test, a fail-closed narrowing, text):
  - a test of two parallel starts of two challenges of one account. Reviewer's set-up: the owner
    holds `SELECT 1 FROM app.user_accounts WHERE actor_id = %s FOR UPDATE`; two threads begin with
    two tokens; wait for two lock waits; commit; outcomes rejected and started, one pending code,
    one start.
  - the 401 mapping narrowed to `totp_mfa_enrollments_one_live_per_actor` and
    `sign_in_code_enrollment_starts_pkey` (any other violation stays 503);
  - API-096 names MFA no longer `required`, and DB-AUTH-003 names "classified";
  - the parallel first-code test's docstring names the clear's username lock;
  - the plan's tests bullet no longer lists the removed `FOR SHARE` test.

  The security should-fix is a business question for the owner, not a code change. It is
  recorded as Q-2026-10-23-180 (a new sign-in code after a reset with only the password; widens
  N5; recommendation (a)); nothing waits on it. Notes kept (plan):
  - the code-row-then-account-key lock order also in the first code, the code challenge and the
    replacement (fail-safe; L4 binding);
  - a start-guard refusal caused by a concurrent change answers 503 (fails closed);
  - a recovery with `p_reset_mfa` can miss a code that a start commits meanwhile;
  - MFA off and on again within 5 minutes lets an old start be confirmed (with Q-180);
  - no test isolates `CHALLENGE_STARTED` and `LOCK_PENDING_ENROLLMENT`;
  - the clear count assertion has meaning only in the window test's `wait` case;
  - the 300-second wait assertion's timing (as in earlier modules).
- **Owner answer (2026-10-23, while P3 ran): Q-2026-10-23-180 (a).** Every sign-in code reset
  also issues the L4 one-time password, so setting up a new sign-in code always needs the new
  password too: the recovery with "also reset MFA" (the Owner's emergency procedure included) and
  Staff MFA turned off and on again. Recorded in the questions file, in DL-081 and as an L4
  binding in the plan; built in L4. Text only.
- **Round 3** (one fresh agent, both checklists, read-only, during P3): no blocker, no
  should-fix. Every round 2 fix is confirmed: the new test reaches the `UniqueViolation` path
  through two different challenges, and the constraint names match. Three wording notes, done
  (text only):
  - the docstring of the two-challenge test: the first start waits at the account key and the
    second at the one-live index;
  - the traceability count is 21, not 20, in the plan and this record;
  - Q-2026-10-23-179 point (3): it is the later sign-in's set-up that turns the unconfirmed code
    off.

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-login-L3c-2b-`)

| Run | Result | Cause |
|---|---|---|
| FF1 (two files reformatted), I1, FC1, L1, Y1 | pass | backend checks |
| U1 | 1 failed, 3,920 passed | cause A (1 of 2): the new tests had no traceability entries |
| U2 | 42 passed | after the cause A fix: traceability and the two changed unit modules |
| M1 | pass | migration-only check |
| T1 | 3 failed, 550 passed | cause B (1 of 2): the guard test made a Manager's MFA `optional` (refused for Owner and Manager); cause C (1 of 2): the implementer's module order in the call, so `test_invoice_migration.py` and `test_utility_meter_migration.py` met Utility Rates of other modules in the shared module database (the L3c-2a order passes) |
| FF2, I2, FC2, L2, Y2 | pass | after the cause B fix (a Staff account) |
| T2 | 553 passed | targeted, the same modules in the L3c-2a order |
| U3 | 3,921 passed | unit suite |
| M2 | pass | migration-only check |
| P1 | 2,587 passed | full PostgreSQL run (before round 1) |
| FF3, I3, FC3, L3, Y3 | pass | after the round 1 fixes |
| T3 | 77 passed | the six sign-in modules |
| U4 | 3,921 passed | unit suite |
| M3 | pass | migration-only check |
| P2 | 2,593 passed | full PostgreSQL run (before round 2) |
| FF4, I4, FC4, L4, Y4 | pass | after the round 2 fixes |
| T4 | 78 passed | the six sign-in modules |
| U5 | 3,921 passed | unit suite |
| M4 | pass | migration-only check |
| P3 | 2,594 passed | full PostgreSQL run (before round 3) |
| FF5, I5, FC5, L5, Y5 | pass | after the round 3 wording notes (one test docstring) |
| T5 | 27 passed | the enrollment module |
| M5 | pass | migration-only check |
| P4 | 2,594 passed | full PostgreSQL run (last) |

- After P4 only text changed: this record and ops/NOW.md.
- Only the known Starlette and pydantic warnings.
- Every saved run output scanned for secrets: only test and migration file names match.
- No frontend file changed.
