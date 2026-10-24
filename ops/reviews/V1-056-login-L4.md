# V1-056 login sub-slice L4 — the Owner's reset with a one-time password — review record

Sub-slice L4 of the login slice (ops/V1_056_PLAN.md section 7.3, L4). Migration 20270204_192.
Base commit: 95588df (L3d-2b). Built on 2026-10-24 in the cloud session. Decisions: owner answers
(a) to Q-2026-10-21-153, Q-2026-10-21-165 and Q-2026-10-23-180; technical points in
Q-2026-10-24-185, decided by Claude under the owner's 2026-10-23 22:30 rule. The commit hash is in
`git log` (this record is part of that commit).

## Built

- L4a (database): `app.one_time_passwords`, `app.password_change_challenges` and
  `app.password_changes` (append-only); `app.issue_one_time_password` and
  `app.change_one_time_password` (SECURITY DEFINER, `search_path = pg_catalog`); the
  `one_time_password_id` mark on the password row with a column grant to the runtime role;
  `app.perform_account_recovery` replaced (administrative mode refused, emergency mode stricter).
- L4b (flows and API): the Owner's reset after the 15-minute reauthentication; a new account's
  first one-time password; the one-time password when a Staff account's required MFA is turned
  off; `password_change_required` at sign-in and `POST /api/v1/auth/password-change`; the shared
  new-password rule and the blocklist file; `422 PASSWORD_RULE`.
- L4c (screens): the "Choose your own password" form, the one-time password box, the reset form
  without a password field. The designed screens come with L6.
- Tests and docs: see DL-081 (L4 lines), the plan and Q-2026-10-24-185.

## Review round 1 (one security agent and one independent agent, read-only, no files written)

- No blocker. Done: the one-time password in capitals, without hyphens or with spaces is refused
  as a new password (`one_time_password_forms`); the password hashed before the locks; the "did
  not finish" message on the screen; the lock-order wording; field length limits; new tests for a
  forced change that meets a reset, a change step of an account disabled meanwhile, the recovery
  codes ending when MFA is turned off, and the change route's 429 and 503.
- Left for later (recorded in Q-2026-10-24-185): the emergency mode is still callable by the
  runtime role; `APP_ENVIRONMENT` defaults to `development`; MFA-off is decided from the old
  policy; the Python recovery repository still accepts modes the database refuses; the MFA-off
  audit row shows `mfa_disabled=false`; the runtime role can add change steps.

## Review round 2 (one security agent and one correctness agent, read-only, no files written)

- No blocker. Should-fix, done: a flow test for a Staff account with an optional policy but its
  own sign-in code (the change must lead to the code); the lock test now writes its session inside
  the transaction that holds the lock; a screen test for a new account's one-time password
  (TEST-FE-684).
- Notes, done: `begin_mfa_enrollment` takes the password lock like every other sign-in write; the
  422 test checks the rule message; loading the administration clears a shown one-time password.
- Notes, not done (recorded in Q-2026-10-24-185 for slice 12): the change comes before the
  sign-in code; no limit of refused tries per change step; full-width forms; no owner and mode
  check on the blocklist file. Also not done: the two session helpers sign in again after the
  change (harmless); the MFA-off one-time password has no screen yet (no control for it exists).

## Review round 3

One agent, read-only, no files written, on the round 2 fixes only.

- No blocker. Should-fix, done: a test that a sign-in code set-up started before a reset waits
  for the password lock and is then refused with no pending code (it fails without the round 2
  lock, checked by removing the lock once and restoring it).
- Notes, done: the new Staff test also asserts the password-change phase; the 422 test compares
  the message with the literal text the screen shows; the TEST-FE-684 comment says "again", not
  "another property".
- Notes, not done: a create or reset answer still on its way when the administration is loaded
  again can show its one-time password after the clearing (the designed screens of L6 replace
  this form); TEST-FE-684 keeps UI-112 (no accounts UI rule exists; UI-112 holds the L4
  amendment for the one-time password box). The new tests and assertions only, so no round 4
  (run rule).

## Runs

| Run | What | Result |
| --- | --- | --- |
| T1 | first targeted database run | 119 failed (the runtime role could not read the password row; column grant added) |
| T2 | after the grant | 4 failed (set-ups that wrote a credential row after creating an account) |
| T3 | after the set-up changes | 29 passed |
| T4 | after review round 1: flow, L4a, admin flow, session and name modules | 41 passed |
| T5 | after review round 2: flow, L4a and enrollment modules | 45 passed |
| T6 | the flow module after review round 3; the new race test without the lock | 9 passed; 1 failed as expected |
| U1 | whole backend suite without a database, with traceability | 3,936 passed (before round 1) |
| F1 | whole frontend suite | 1,604 passed; TEST-FE-087 intermittent (V1-060 list) |
| F2 | whole frontend suite after review round 3 | 1,607 passed |
| P1 | full PostgreSQL run after review round 3 | 2,675 passed, 1 failed (the password-credential column list in `test_migrations.py` lacked the new column) |
| U2 | whole backend suite without a database after review round 3 | 3,939 passed, 2,508 skipped |
| T7 | `test_migrations.py` after the column fix | 123 passed |

The only change after P1 and U2 is the one expected column in `test_migrations.py` (run in T7)
and docs.
