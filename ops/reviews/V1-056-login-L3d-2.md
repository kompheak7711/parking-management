# V1-056 login sub-slice L3d-2 — the 15-minute check of the high-risk administration actions — review record

Sub-slice L3d-2 of the login slice (ops/V1_056_PLAN.md section 7.3, L3d). No migration. Base
commit: 24ec433 (L3d-1 docs). Built on 2026-10-24 in the cloud session that finished L3d-1.
Technical points in Q-2026-10-24-184, decided by Claude under the owner's 2026-10-23 22:30 rule.
The commit hash is in `git log` (this record is part of that commit).

## Built

- `access_admin_flow.py`: `RECENT_REAUTHENTICATION` and `_require_recent_reauthentication`, the
  first statement of `create_user`, `update_user` (only when it disables the account or changes
  the MFA policy), `create_role_bundle`, `update_role_bundle`, `assign_role_bundle`,
  `remove_role_assignment` and both Settings access changes; `403 REAUTHENTICATION_REQUIRED`
  otherwise. `revoke_user_sessions` and a names-only change are not checked.
- `access_admin_api.py`: `AdministrationAuditContext` carries the session and reauthentication
  cookies (never in its repr), filled by `_audit_context` on every route.
- `auth_flow.py`: `_write_sign_in_reauthentication` in `complete_mfa` (`totp`) and
  `confirm_mfa_enrollment`; `auth_api.py` sets the reauthentication cookie for both.
- Tests and docs: see DL-081 (L3d-2 lines) and the plan's L3d-2 bullets.

## Review round 1 (one independent and one security agent, read-only, no files written)

- No blocker. Should-fix, done: time limits on the action's connection (5-second statements,
  3-second lock wait, `55P03` answers `TRY_AGAIN`); a guard refusal of the sign-in's
  reauthentication row answers 401, not 503; clarifications of the check order appended to
  Q-2026-10-24-184 and API-080; a new test for idle and absolute expiry, the `FOR SHARE` hold,
  ending the held session in the same transaction, and the order before a stale version.
- Notes, done: a sign-in without a reauthentication clears an old cookie; a stricter stored-digest
  assertion; the set-up change of two fake results recorded in DL-081; the L4 binding written
  under L4; the password age at a sign-in (up to about 20 minutes) accepted in Q-184.
- Notes, not done, with reasons: locking the sign-in code row too (every path that turns an
  Owner's code off also ends the sessions the action holds; L4 keeps that); a check inside the
  `app.admin_*` functions (defence in depth; slice 12 list); a request through the real session
  resolver for the Owner (needs a full sign-in with a real code; the resolver and the route read
  the same `SESSION_COOKIE_NAME` cookie); a test of the sign-in guard race (needs a change
  committed between two statements under the sign-in code's lock); a two-connection race test of
  a whole action (the hold is shown with the check's own query).

## Runs

| Run | What | Result |
| --- | --- | --- |
| T1 | targeted, before the set-up changes | 18 failed (expected), 91 passed |
| T2 | targeted, 10 modules | 2 failed (test set-up), 132 passed |
| T3, T4 | admin module | fixed, 10 passed |
| T5 to T7 | admin, reauthentication, recovery-code sign-in, enrollment modules after round 1 | 76 passed, then admin 11 passed |

## Review round 2 (one agent, correctness and security, read-only, no files written)

- No blocker, no should-fix. The five round-1 fixes checked; the four items not built judged not
  blockers. Notes, done as text only: the cookie clearing is described as the two MFA routes'
  (a password-only sign-in leaves an old cookie, harmless because it is bound to its session);
  the 24-hour case is past both expiries by the table check. Notes, recorded only: creating a
  bundle and a bundle rename are checked (stricter than "changing a bundle", Q-184 point 1); a
  lock wait on a read route would show the change message (reads take no row locks); the
  connection `options` override any `options` in the database URL (L7 deployment docs).
- No round 3: round 2 had no finding that changes code behaviour (run rule: round 3 text and
  assertion fixes commit without another round).
| U1 | whole backend suite without a database | 3,924 passed, 2,488 skipped |
| P1 | full PostgreSQL run (`scripts/database-test.sh`), after round 1 | 2,656 passed |

After P1 only text changed (round 2 notes: two docstrings, one docs line, one traceability note);
ruff, the format check and mypy pass on the final tree.
