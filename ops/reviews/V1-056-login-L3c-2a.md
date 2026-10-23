# V1-056 login sub-slice L3c-2a — sign-in code challenge and the session's MFA proof — review record

Sub-slice L3c-2a of the login slice (ops/V1_056_PLAN.md section 7.3, L3c; L3c-2 split into L3c-2a,
L3c-2b enrollment and L3c-2c recovery codes). Migration `20270130_187`. Base commit: dcab226
(L3c-1). Built on 2026-10-23 in a fresh session. Not pushed. The commit hash is in `git log` (this
record is part of that commit).

## Built

- Migration `20270130_187` (additive): `app.sign_in_mfa_challenges` (only the sha256 digest of the
  pre-authentication token; purpose `challenge` or `enrollment`; for a `challenge` the active
  sign-in code of its own account, checked at insert; the digest of the checked password
  verifier; the keyed wrong-try digests; 5 minutes by the database clock; completed once),
  `app.totp_used_steps` (append-only; the guard locks the enrollment row and refuses a step not
  after the last used one, a future step and a step of a code that is not active),
  `app.browser_session_mfa_proofs` (append-only; a not revoked session made after a completed
  challenge of its own account; a `totp` proof names the challenge's own code with a step used
  since the challenge). No foreign key from the new tables to sessions or enrollments (insert
  guards instead), so the committed truncate tests of those tables are unchanged. Column grants
  to the runtime role only.
- `auth_flow.py`: an account needs MFA when its policy is `required` or it has an active sign-in
  code (the lookup reports it); its sign-in stores a challenge and answers `mfa_required`, or
  `mfa_enrollment_required` without a code; `complete_mfa` with `totp` (current or previous
  30-second step of the database clock, each step once; a wrong code is a wrong try of kind
  `sign_in_code`; a wait answers 429; the right code, in one transaction: the clear first, the
  enrollment lock, the step, the completion, the password-verifier comparison, the session and
  its proof, the live read back); a session of an account that needs MFA is live only with its
  proof, and a `totp` proof only while its code is active (also in the resolver's activity write,
  `session_actor.py`); logs carry the outcome and the request id only.
- `app.py`: the protection key is read once and given to the flow with the derived wrong-try key;
  owner item 4 of 2026-10-23: an API started with a database and no key file logs the warning
  event `security.protected_key_file_missing`, without a key, path or URL (Q-2026-10-23-178).
- Tests: unit `test_runtime_secrets.py` (1 new); PostgreSQL `test_sign_in_code_migration.py`
  (18 tests, one parametrized four ways), last in `scripts/database-test.sh`. Traceability: 19
  entries appended, 1 note of an L3c-1 entry extended.
- Docs: DB-AUTH-003 and DB-AUTH-004 amendments, API-096 amendment, DL-081 (L3c-2a and updated
  tests), README sentence on the warning, Q-2026-10-23-178 (decided under the owner's
  2026-10-22 rule), plan.

## Committed tests changed

- The 27 head-revision strings (`20270129_186` to `20270130_187`) in 15 modules;
  `test_sign_in_wait_migration.py` moves `HEAD` to `20270130_187` and checks migration
  `20270129_186` through a new `KEYED_CLEAR` constant.
- With the approved plan (L3c builds enrollment for a new or reset account), an account that needs
  MFA and has no sign-in code gets `mfa_enrollment_required`:
  `test_auth_flow_migration.py::test_an_account_that_needs_mfa_gets_no_session_before_the_challenge`
  and `test_sign_in_wait_migration.py::test_a_disabled_account_counts_and_an_mfa_password_neither_counts_nor_clears`
  (only that expectation and the docstring).
- `test_runtime_secrets.py::test_create_app_gives_the_derived_key_to_the_sign_in_flow` also checks
  the protection key the flow gets (stricter); `test_access_control.py` lists the new log event
  label, as its comment asks for a new label.
- Not touched in this sub-slice: the rename in `test_deposit_receipt_refund_out_migration.py`
  (owner item 5) waits for the next time that file is touched.

## Read-only search for affected tests

- Truncate refusals: `test_migrations.py` truncates `app.totp_mfa_enrollments` and
  `app.browser_sessions` and expects the history guard's error; a foreign key from the new tables
  would raise the foreign-key refusal first, so the new tables have none.
- Every test that signs in an MFA account (`test_auth_flow_migration.py`,
  `test_sign_in_wait_migration.py`), every session or resolver test (`test_session_actor_migration.py`,
  `test_session_revocation_time_migration.py`) and the bootstrap tests: only the two phase
  expectations above change.
- Tests asserting start-up log events: `test_operations.py` (no database, so no warning) and the
  label list in `test_access_control.py`.

## Reviews

- **Round 1** (one independent and one security agent): no blocker. Should-fixes done: the
  used-step guard locks the enrollment row and refuses a future step; tests of the window on an
  unused code, "completed once" with a later step, an `enrollment` token after a code is set up,
  a change inside the session-transaction window (parametrized: a parallel wait, the code off, a
  new password, the account disabled; reviewers' set-up: wrap `challenge_wait_seconds`), two
  parallel uses of one code, a parallel step. Notes done: a `challenge` keeps its own sign-in
  code (design change, confirmed by round 2), the tightened proof guard, request ids in the logs,
  real digests in the expired-challenge test, nothing written on a refusal. Kept: the code
  request's own source is not counted (known limit); one key file for AES-GCM and the HKDF input.
- **Power loss** (owner, 2026-10-23): the Mac mini lost power during unit run U2; recovery check
  clean, every changed file complete, all checks and runs repeated from the start. Not a failure
  cause; no correction allowance used.
- **Round 2** (one fresh independent and one fresh security agent): no blocker; the design change
  and the no-foreign-key choice confirmed. Should-fixes done under the round-3 rule (a fail-closed
  refusal and tests): the challenge insert guard; tests of the challenge's own code and of each
  proof guard condition alone with a positive control (reviewer's set-up: complete C1 with step-1,
  complete C2 as owner, a proof for the older session, a later session without a step since, a
  revoked session, then a live later session after a step is recorded). Notes done: a `totp`
  proof counts only while its code is active (with a test), the lock-wait helper reads `pg_locks`
  and the tests assert the wait, docs/004 wording, `database_url=None` in the warning test, a
  token over 128 characters refused. Bindings recorded for L3c-2b, L3c-2c and L4 (plan).
- **Round 3** (one fresh agent, both checklists): no blocker, no should-fix. Notes kept for L3c-2b
  (code or test changes): `mfa_assurance` falls back to `none` when the proof's code is off; the
  lock-wait helper counts only the test database's waits and waits up to 10 seconds;
  `ACTIVE_ENROLLMENT_OF` with `FOR SHARE`. Added to the L3c-2c binding: whether a code reset ends
  recovery-code sessions.

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-login-L3c-2a-`)

| Run | Result | Cause |
|---|---|---|
| FF1 (two files reformatted), I1, FC1, L1 | pass | backend checks |
| Y1 | fail | cause A (1 of 2): `bytes()` on an untyped test row |
| FF2, I2, FC2, L2, Y2 | pass | after the cause A fix |
| U1 | 3,918 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 524 passed | targeted: 15 head-revision modules and the five sign-in modules |
| M2 | pass | migration-only check |
| P1 | aborted | the implementer started it with a 10-minute background limit; stopped, containers cleaned up |
| P2 | 2,557 passed, 1 failed | known DL-067 `LockNotAvailable` (`55P03`) in `test_credit_migration.py`, not changed by this sub-slice |
| R1 | 1 passed | the one failing test rerun once (rule of Q-2026-10-18-132) |
| FF3 (one file reformatted), I3, FC3 | pass | after the round 1 fixes |
| L3 | fail | cause B (1 of 2): RUF005, a tuple joined with `+` |
| FF4, I4, FC4, L4, Y3 | pass | after the cause B fix |
| T2 | 48 passed | the five sign-in modules |
| U2 | not finished | power loss (not a failure cause) |
| FF5, I5, FC5, L5, Y4 | pass | repeated after the power loss |
| U3 | 3,918 passed | unit suite |
| M3 | pass | migration-only check |
| T3 | 530 passed | targeted, the T1 modules |
| M4 | pass | migration-only check |
| P3 | 2,564 passed | full PostgreSQL run (before round 2) |
| FF6, I6, FC6, L6, Y5 | pass | after the round 2 fixes |
| M5 | pass | migration-only check |
| T4 | 2 failed, 49 passed | cause C (1 of 2): the lock-wait query missed row-lock waits (a `transactionid` lock has no database) |
| FF7, I7, FC7, L7, Y6 | pass | after the cause C fix |
| T5 | 51 passed | the five sign-in modules |
| U4 | 3,918 passed | unit suite (before round 3) |
| M6 | pass | migration-only check |
| P4 | 2,567 passed | full PostgreSQL run (before round 3) |

- After P4 only text changed: the plan and this record, and NOW.md.
- Only the known Starlette and pydantic warnings.
- No frontend file changed.
