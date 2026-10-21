# V1-056 login sub-slice L2a — account and role bundle administration in the database — review record

Sub-slice L2a of the login slice (L2 split into L2a, the database functions, and L2b, the Python
flow, API changes, Settings access routes and frontend client; ops/V1_056_PLAN.md section 7.3).
Migration `20270124_181`. Base commit: 5275e9c (the owner answer to Q-2026-10-21-165, recorded
first, docs only). Built on 2026-10-21 and 2026-10-22 in a fresh session. Not pushed. The commit
hash is in `git log` (this record is part of that commit).

## Owner answer recorded first (commit 5275e9c)

Q-2026-10-21-165 (a): a sign-in code reset or MFA off removes the account's Settings access in the
same step, as a recorded removal; the Owner gives it again after the new code. The owner also
agreed that no build between L3a and L5 is used.

## Built

- `app.user_account_changes` (append-only; UPDATE, DELETE and TRUNCATE refused, 23000): one row
  per account change (version from 2, who, when, non-secret previous and resulting state,
  provenance). An account's version is 1 plus its number of changes.
- Definer functions, executable by `prm_runtime` only. Each refuses any acting account but the
  active Owner class (42501) and any isolation level but READ COMMITTED (55000). Each write
  function writes one secret-free `audit_events` row (`identity.manage_access`, `API`,
  `SUCCEEDED`, the caller's correlation id) in the same transaction.
  - `admin_create_account`: a Manager (MFA `required`) or Staff (MFA `optional`) account, its
    class, its HUMAN identity and the class's default bundle; never an Owner; no password before
    L4; refused without default bundles.
  - `admin_update_account`: display name, audit name, MFA policy, disable, with the expected
    version (40001); never the Owner; an account without a class can only be disabled.
    - Disable revokes unexpired sessions (`account_disabled`) and keeps assignments and Settings
      access as history.
    - A Staff MFA raise revokes sessions (`material_privilege_reduction`,
      `access-admin-mfa-required`; the L1e binding).
    - MFA off (Staff policy set to `optional`) disables the sign-in code enrollment, revokes the
      sessions when one was disabled (`mfa_reset`, `access-admin-mfa-off`) and removes Settings
      access as a recorded removal ("sign-in code turned off"; Q-156 (a), Q-165 (a)); the removed
      grant id is in the audit event.
  - `admin_revoke_account_sessions` (Manager or Staff; `material_privilege_reduction`,
    `access-admin-revoke-sessions`).
  - `admin_create_role_bundle`, `admin_update_role_bundle` (only `bundle` capabilities, expected
    version, the complete set of each version; a smaller set revokes the sessions of every active
    holder).
  - `admin_assign_role_bundle` (an active account with a class, the Owner included),
    `admin_remove_role_assignment` (with a reason; revokes the account's sessions; its route
    waits for Q-2026-10-21-166).
  - `admin_give_settings_access`, `admin_remove_settings_access` (the L1d/L1e functions plus the
    audit event; the give takes a share lock on the account first).
  - Owner-only reads `admin_accounts` (class, version, recorded Settings access) and
    `admin_role_bundles` (current capability set).
- Eight internal functions (not definers, no EXECUTE for any application role), among them
  `app.assert_account_names`: a username, display name or audit name is 1 to 128 characters with
  no space at either end and none of the bundle-name control and invisible characters.
- Tests: `test_access_administration_migration.py`, 16 PostgreSQL tests, last in
  `scripts/database-test.sh`; traceability 16 entries appended; head-revision strings 27 in 15
  modules.
- Docs: docs/004 DB-AUTH-010; docs/008 SEC-014 note; docs/010 DL-081 L2a and "Updated tests"
  lines; plan section 7.3 (split, pre-code design, as-built and review bullets, the L4 note);
  questions Q-2026-10-21-166 to 168.

## Design changes (under the design-change run rule; confirmed as needed and safe by review round 2)

1. Owner-only definer reads instead of SELECT grants on the bundle, assignment, default bundle and
   Settings access relations: three committed tests check that the runtime role cannot read them.
2. MFA off also disables the sign-in code and revokes the sessions (`mfa_reset`): Q-156 (a) makes
   MFA off a reset with "also reset MFA"; otherwise an old code on a lost phone would count again
   when MFA is required (both round 1 reviewers).
3. No `change_kind` column: the audit action names the kind.

## Read-only search for affected tests

- No committed test or helper calls or hand-writes anything this sub-slice refuses (only new
  functions are added).
- No committed test truncates or deletes `app.user_accounts` (the new foreign key).
- Head-wide checks of runtime privileges on the L1 relations (three tests) stay true because the
  runtime role gets no SELECT; catalog comparisons are revision-specific on throwaway databases.
- Committed tests changed: only the 27 head-revision strings.

## Review round 1 (two fresh agents)

Independent: no blocker, 8 should-fix, 12 notes. Security: no blocker, 4 should-fix, 11 notes.
Done:
- `settings_access` was null for an account without a class (fixed, tested).
- MFA off left the sign-in code active (design change 2, tested: the old code no longer counts
  and Settings access needs a new code).
- Account names allowed invisible characters (fixed, tested at create and update).
- Docs were missing (added). `change_kind` (design text amended).
- Tests: every function refused for a disabled Owner and a disabled Manager and at REPEATABLE
  READ and SERIALIZABLE; "no default bundles" on a throwaway database; disable with MFA off;
  bundle reduction scope; invalid MFA value; audit counts; races.
- Race set-up (throwaway database): commit the Property, an Owner and Staff accounts with sign-in
  codes; connection A runs the first call uncommitted; connection B runs the second in a daemon
  thread with `lock_timeout=15s`; a watcher waits up to 5 s until B shows
  `wait_event_type = 'Lock'`; A commits; A is rolled back in `finally` before the join (20 s).
Moved to owner questions: revoke the runtime role's EXECUTE on the unaudited L1d give and remove
(Q-167, a tightening that changes a committed test); a Staff ceiling (Q-168); the assignment
removal route (Q-166).
Notes kept for later sub-slices are in the plan's as-built bullet (L2b error mapping and name
normalization, L3a disabled-account resolver test, L3c new-Manager test, L3d reauthentication and
live-session check, a future enable path).

## Review round 2 (one fresh agent, both checklists)

No blocker; one should-fix (text): the traceability count of internal functions, the runtime
privilege sentence and the MFA-off session condition in DB-AUTH-010 (all fixed). Tests made
stricter or added: escaped invisible characters, column-privilege checks, a fifth race (MFA off
first, then the give waits and is refused). Q-167 gained the reviewer's race example. Notes kept:
L2b maps 23514 to a retryable conflict and a give to an unknown account answers 422; L3c and L4
invalidate recovery codes on a code reset; name rule gaps (Unicode edge spaces, U+2028, U+2029,
U+034F, Hangul fillers, Khmer U+17B4 and U+17B5) for a later question with the L2b name handling.

## Review round 3 (one fresh agent, both checklists)

Before it: unit U3 and full PostgreSQL P3. No blocker, no should-fix. Notes taken as text: the
race test's traceability note names five races; the migration docstring and DB-AUTH-010 say each
write function writes the audit event; DL-081 records the design changes as confirmed; the L4
section gains the Q-165 (a) removal on the `reset_mfa` path with its tests. Note kept for L2b:
map a deadlock (40P01) of a bundle reduction to a retryable conflict.

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-login-L2a-`)

| Run | Result | Cause |
|---|---|---|
| FF1 (one file reformatted), I1, FC1 | pass | backend checks |
| L1 | fail | cause A (1 of 2): RUF005 (tuple concatenation in the new test) |
| FF2, I2, FC2, L2, Y1 | pass | after the cause A fix |
| U1 | 3,876 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 492 passed, 1 failed | cause B (1 of 2): the new least-privilege test missed the backup role's `pg_read_all_data` |
| FF3, I3, FC3, L3, Y2 | pass | after the cause B fix |
| T2 | 11 passed | targeted: the new module |
| M2 | pass | migration-only check |
| P1 | 2,494 passed | full PostgreSQL run |
| FF4 (one file reformatted), I4, FC4, L4, Y3 | pass | after the round 1 fixes |
| M3 | pass | migration-only check |
| T3 | 16 passed | targeted: the new module |
| U2 | 3,876 passed | unit suite |
| M4 | pass | migration-only check |
| P2 | 2,499 passed | full PostgreSQL run (two pydantic `UnsupportedFieldAttributeWarning` in the unchanged `test_credit_refund_api_migration.py`, as in the L1c P1; not in P3) |
| FF5, I5, FC5, L5, Y4 | pass | after the round 2 fixes |
| T4 | 16 passed | targeted: the new module |
| U3 | 3,876 passed | unit suite (before round 3) |
| M5 | pass | migration-only check |
| P3 | 2,499 passed | full PostgreSQL run (before round 3) |
| FC6, L6 | pass | after the round 3 text notes (migration docstring) |

- One correction for cause A (1 of 2) and one for cause B (1 of 2).
- No `LockNotAvailable` failure.
- After P3, only text changed: the migration docstring, DB-AUTH-010, DL-081, the plan, the
  traceability note, this record and NOW.md.
