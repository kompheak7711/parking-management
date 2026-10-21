# V1-056 login sub-slice L1e — Settings access needs the sign-in code — review record

Sub-slice L1e of the login slice (new, after L1d and L1c; ops/V1_056_PLAN.md section 7.3).
Migration `20270123_180`. Base commit: a17a1d3 (L1c). Built on 2026-10-21 in the same session.
Not pushed. The commit hash is in `git log` (this record is part of that commit).

## Owner rule (recorded first in commit 88d5bfd)

Any account that holds Settings access must use the sign-in code at every sign-in, like the
Owner and Manager classes; the Owner gives Settings access to a Staff account only after it has
set up its sign-in code, otherwise a plain refusal; no path may leave a Staff account with
Settings access and no sign-in code; a reset or removal path that needs the owner's choice gets
a question. Placed in its own small sub-slice after L1d (the give function and the reader
exist; the sign-in code table exists since migration `20260819_06`).

## Built

- `app.give_settings_access` replaced (same signature, owner, privileges, attributes): after the
  Owner and target checks, a Staff target needs MFA policy `required` and an `active` sign-in
  code enrollment, otherwise 55000 "a Staff account gets Settings access only after it has set
  up its sign-in code". A Manager target is not checked: its class always requires the code
  (L1a) and no session gets an actor before it (L3c).
- `app.actor_capability_grants` replaced (same attributes and privileges): the per-user branch
  gives `settings.manage` to a Manager, and to a Staff account only while its MFA policy is
  `required` and it has an `active` enrollment. So a code reset, a lowered MFA policy, a
  hand-written grant or a give that raced a reset gives nothing (fail closed). The Owner
  branches are unchanged.
- New internal function `app.staff_sign_in_code_is_set_up(account)`: STABLE, not a definer,
  `search_path=pg_catalog`, no EXECUTE for PUBLIC or any application role.
- `access_control.py`: reader docstring only.
- New question Q-2026-10-21-165 (what a reset or MFA-off path does to the grant row;
  recommendation (a): remove it in the same step). Nothing built waits for it.
- Tests: `test_settings_access_sign_in_code_migration.py` (4 PostgreSQL tests, last in
  `scripts/database-test.sh`); traceability 4 entries appended; head-revision strings 27 in 15
  modules.
- Docs: docs/004 DB-AUTH-008 note, docs/008 SEC-013 and SEC-021 notes, docs/010 DL-081 lines,
  plan section 7.3 (new L1e section; L2 Builds pointer).

## Committed tests changed (`test_settings_access_migration.py`)

Under the run rule "A new refusal and a committed test's set-up" (2026-10-19):
- `test_the_owner_gives_and_removes_settings_access` and
  `test_the_reader_gives_settings_access_to_the_owner_and_to_given_accounts_only`: their give to
  a Staff account without a sign-in code is now refused. Each first asserts that refusal (55000,
  the plain message), then gives the account a sign-in code with the new helper
  `add_sign_in_code` (MFA policy `required`, an enrollment written as the table owner and
  activated) and gives again through the real path. Every check and expected result is kept;
  the later "gets nothing" checks are now stronger.
Set-up change caused by the reader's new filter, not by a refusal (recorded separately):
- `test_the_runtime_role_reaches_settings_access_only_through_its_functions`: its committed
  Staff holder gets a committed sign-in code in the set-up, so the runtime reader still returns
  `settings.manage`; the expected result is unchanged.
Plus the 27 head-revision strings (`20270122_179` to `20270123_180`) in 15 modules; nothing
else in those files. Round 2 compared the changes with HEAD and found nothing weaker.

## Read-only search for affected tests

Tests that give Settings access or read a Staff holder's grants: only
`test_settings_access_migration.py` (the three tests above; its race test writes grants by hand
and reads no grants). `test_role_bundle_migration.py` and `test_default_role_bundles_migration.py`
read bundle and Owner grants only (unchanged branches). No head-wide function lists.

## Review round 1 (one fresh agent, both checklists)

No blocker. Two should-fix, both text, both done:
1. Q-165 said a recovery with a recovery code can reset a Staff sign-in code; that mode refuses
   `reset_mfa` and is for the Owner's own account. Fixed: it names the administrative reset with
   `reset_mfa` (API-099) and the emergency procedure (DL-058) of `app.perform_account_recovery`.
2. The reader checks the account, not the session: a Staff session started while MFA was
   `optional` never used the code. Fixed as a binding for later sub-slices (plan L1e point 4,
   DL-081 L1e line, L2 Builds pointer): L2 revokes a Staff account's sessions in the same
   transaction when its MFA policy is raised to `required`, with an L2 test (set-up: commit a
   Staff session with `optional` policy; set the policy to `required` through the L2 path; the
   session is revoked); L3c gives such an account an actor only after the code at every sign-in.
Notes taken: new test `test_a_staff_account_without_a_sign_in_code_keeps_its_bundle_capabilities`
(set-up: the Property; a Staff account without a code; seed the defaults; assign the Staff
default bundle; a hand-written grant; the grants are exactly the 31 Staff-bundle capabilities;
roll back); reader docstring; L2 note on the two 55000 reasons of the give (told apart by
message); L3c note that `active` is only as trustworthy as the L3c code check before activation.

## Review round 2 (one fresh agent, both checklists)

Before it: unit U2 and full PostgreSQL P2 were started on the final code. No blocker, no
should-fix. Notes taken as text: the Q-165 title named L3c, which nothing in it waits for
(removed); the L2 section now points to the session binding. Notes kept: this record; the
enrollment INSERT in the new module repeats the committed helper's (acceptable).

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-login-L1e-`)

| Run | Result | Cause |
|---|---|---|
| FF1, I1, FC1, L1, Y1 | pass | backend checks |
| U1 | 3,876 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 508 passed | targeted: the 15 head-revision modules, the role bundle, Settings access, default bundle and new modules |
| P1 | 2,482 passed | full PostgreSQL run |
| FF2, I2, FC2, L2, Y2 | pass | after the round 1 fixes |
| T2 | 18 passed | targeted: the Settings access, default bundle and new modules |
| U2 | 3,876 passed | unit suite |
| M2 | pass | migration-only check |
| P2 | 2,483 passed | full PostgreSQL run |

- No check or run failed; no correction used.
- No `LockNotAvailable` failure.
- After P2, only text changed: the Q-165 title, the plan L2 pointer, this record and NOW.md.
