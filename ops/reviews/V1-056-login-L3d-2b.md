# V1-056 login sub-slice L3d-2b — the recovery-code window uses the reauthentication cookie — review record

Sub-slice L3d-2b of the login slice (split from L3d-2; ops/V1_056_PLAN.md section 7.3, L3d). No
migration. Base commit: 9581df2 (L3d-2). Built on 2026-10-24 in the cloud session. Decision:
Q-2026-10-24-184 point 8, decided by Claude under the owner's 2026-10-23 22:30 rule. The commit
hash is in `git log` (this record is part of that commit).

## Built

- `auth_flow.py`: `RECENT_SESSION_REAUTHENTICATION` (the L3d-2 query, moved here) and
  `REAUTHENTICATION_WINDOW`; `_recently_signed_in_with_code` needs the request's reauthentication
  cookie of the session; `RECENT_PROOF` removed; `issue_recovery_codes` and
  `regenerate_recovery_codes` take `reauthentication_token`.
- `auth_api.py`: the protocol, the unavailable flow and both routes pass `__Host-prm_reauth`.
- `access_admin_flow.py`: `RECENT_REAUTHENTICATION` is the moved query plus `FOR SHARE OF
  browser` (the reviewer compared the text with 9581df2: identical).
- Tests and docs: see DL-081 (L3d-2b lines) and the plan.

## Review (one security and correctness agent, read-only, no files written)

- No blocker. Should-fix, done: the API-098 amendment said "401 as before" (wrong: before, a
  session cookie alone got codes in the first 15 minutes) and did not say that a later
  reauthentication reopens the window; both corrected in the new (uncommitted) amendment line.
- Notes, done: the recovery-code case of the refusal test now has a real `totp` reauthentication
  and its cookie, so only the session's recovery-code proof can refuse; the added assertion in
  `signed_in` is recorded in DL-081.
- Notes, not done: no re-check of the reauthentication in the write transaction (the session is
  re-checked and held; the request was authorised when it started, as the reviewer agreed); the
  window test keeps its name (its traceability note says the time is now the reauthentication's);
  no HTTP test that drops the cookie (the flow test covers every cookie case and the API test
  shows the cookie is passed on).

## Runs

| Run | What | Result |
| --- | --- | --- |
| T1 | recovery-code flow and sign-in, admin, reauthentication modules | 71 passed |
| T2 | recovery-code flow module after the review fix | 1 failed (a step in the future; set-up) |
| T3 | the refusal test after the set-up fix | 6 passed |
| U1 | whole backend suite without a database | 3,924 passed, 2,489 skipped |
| P1 | full PostgreSQL run, started before the review fix | 2,657 passed |

The review fix touched only the set-up of one parametrized test (run in T3) and docs.
