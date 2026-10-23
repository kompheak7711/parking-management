# V1-056 login sub-slice L3c-1 — protected key file and keyed wrong-try digests — review record

Sub-slice L3c-1 of the login slice (ops/V1_056_PLAN.md section 7.3, first part of L3c). Migration
`20270129_186`. Base commit: 7411d07 (L3b). Built on 2026-10-23 in the same session as L3b. Not
pushed. The commit hash is in `git log` (this record is part of that commit).

## Owner answers built

- Q-2026-10-21-155 (a): the API reads the TOTP protection key from a protected file whose path is
  `APP_TOTP_KEY_FILE`; `APP_PASSWORD_BLOCKLIST_FILE` is the blocklist path (read from L4).
  `.env.example` was opened in this sub-slice only, and gained exactly these two lines, with no
  values:

  ```
  APP_TOTP_KEY_FILE=
  APP_PASSWORD_BLOCKLIST_FILE=
  ```

- Q-2026-10-23-175 (a): the wrong-try digests are keyed with a key derived from the protected key
  file; no new package, no new secret, the key never printed.

## Built

- `settings.py`: `totp_key_file` and `password_blocklist_file` (paths only).
- New `runtime_secrets.py`: `read_protected_totp_key` (open with `O_RDONLY | O_NONBLOCK |
  O_NOCTTY`, read from offset 0, the bootstrap's own `read_root_controlled_totp_key` checks, close
  on every path, fixed messages); `derive_sign_in_try_key` (HKDF-SHA256 from the `cryptography`
  package already in the repository, info `property-rental:sign-in-try-digest:v1`).
- `auth_flow.py`: the wrong-try digests are HMAC-SHA256 under the derived key when there is one,
  plain sha256 otherwise; `PostgresAuthenticationFlow(database_url, *, sign_in_try_key=None)`.
- `app.py`: `create_app` reads the key once at start-up and gives the derived key to the flow; with
  a database and no key file it refuses to start in every environment except `development` and
  `test` (an allowed list).
- Migration `20270129_186` (relaxing): `app.clear_sign_in_wrong_tries` without the comparison of
  the digest with `sha256('username:' || normalized_username)` (the database has no key).
- Tests: unit `test_runtime_secrets.py` (5), `test_auth_flow.py` (1); PostgreSQL
  `test_sign_in_wait_migration.py` (1 new). Traceability: 7 entries appended, 1 renamed.
- Docs: DB-AUTH-011 amendment, DL-081 (L3c-1 and updated tests), README paragraph, plan.

## Committed tests changed

- The 27 head-revision strings (`20270128_185` to `20270129_186`) in 15 modules; in
  `test_sign_in_wait_migration.py` the two head asserts use a new `HEAD` constant (its own
  revision stays `20270128_185`).
- With the owner answer (a) to Q-2026-10-23-175 (standing rules):
  `test_a_clear_with_another_accounts_actor_clears_nothing` renamed
  `test_a_clear_needs_an_active_account_but_cannot_check_a_keyed_digest`; another active account's
  actor now clears (the database cannot check a keyed digest); a disabled account's actor
  refusal is added (stricter).

## Read-only search for affected tests

- No committed test or script builds an app in an environment other than the default with a
  database; `make dev`, the module-level `app` and `database-test.sh` keep the default
  `development`.
- Tests that list the clear function's attributes: only `test_sign_in_wait_migration.py` (kept by
  `CREATE OR REPLACE`).
- `test_deployment_scaffolding.py` and `scripts/validate-deployment-config.py` do not read
  `.env.example` names beyond the database password files.

## Reviews

- **Round 1** (one independent and one security agent; after U1, T1, P1): no blocker.
  - Should-fixes done: the start-up rule became an allowed list (fail closed); tests: `create_app`
    gives the derived key to the flow (independent reviewer's set-up: patch
    `property_rental.app.read_protected_totp_key` and `PostgresAuthenticationFlow`, start in
    `production` with a key file path and in `development` without), a correct sign-in clears
    only its own keyed count (a bystander's 2 keyed tries written as the owner stay), the keyed
    digests are HMAC-SHA256 (unit).
  - Notes done: `O_NONBLOCK | O_NOCTTY` and `lseek(0)`; root skip; DB-AUTH-011 key-change sentence;
    README paragraph; settings comment.
- **Round 2** (one fresh agent, both checklists; after U2, P2): no blocker. Should-fix (text) done:
  the `APP_ENVIRONMENT` default stated in README, DB-AUTH-011 and DL-081, with an L7 binding.
  Notes done: a `/dev/fd/<n>` rewind test; `delenv` in the wiring test; README blocklist wording;
  plan risk wording; L4 binding.
- **Round 3** (one fresh agent, both checklists; after U3, P3): no blocker, no should-fix. Text
  notes done: DL-081 wording of the renamed test; two superseded design sentences marked.
- Notes kept: forked workers sharing one inherited key descriptor could interleave reads (L7: one
  worker or a positional read); on Linux the rewind test passes without the `lseek`; the derived
  key would show in a traceback with locals; the runtime role can clear a count by a direct call
  with any active actor (accepted with Q-175 (a)); L7 adds a start-up check that
  `APP_ENVIRONMENT` is set.

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-login-L3c-1-`)

| Run | Result | Cause |
|---|---|---|
| FF1 (two files reformatted), I1 (one import order fixed), FC1, L1 | pass | backend checks |
| Y1 | fail | cause A (1 of 2): the new test patched `os` through a module that does not export it |
| FF2, I2, FC2, L2, Y2 | pass | after the cause A fix |
| U1 | 3,914 passed | unit suite |
| M1 | pass | migration-only check (new head `20270129_186`) |
| T1 | 512 passed | targeted: the 15 head-revision modules and the four sign-in modules |
| M2 | pass | migration-only check |
| P1 | 2,546 passed | full PostgreSQL run (before round 1) |
| FF3 (one file reformatted), I3, FC3, L3, Y3 | pass | after the round 1 fixes |
| U2 | 3,916 passed | unit suite |
| T2 | 16 passed | targeted: `test_sign_in_wait_migration.py` |
| M3 | pass | migration-only check |
| P2 | 2,546 passed | full PostgreSQL run (before round 2) |
| FF4, I4, FC4, L4, Y4 | pass | after the round 2 fixes |
| U3 | 3,916 passed | unit suite (before round 3) |
| M4 | pass | migration-only check |
| P3 | 2,546 passed | full PostgreSQL run (before round 3) |

- After P3 only text changed: DL-081, the plan, this record and NOW.md.
- No `LockNotAvailable` failure; only the known Starlette and pydantic warnings.
- No frontend file changed.
- Still pending (not touched): the test rename in `test_deposit_receipt_refund_out_migration.py`.
