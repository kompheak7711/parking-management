# V1-056 login sub-slice L8 — close the login slice — review record

Sub-slice L8 of the login slice (ops/V1_056_PLAN.md section 7.3, L8). No migration. Base commit:
7738b3f (V1-059 part B merged after L7c). Built on 2026-10-24 in the cloud session. Decisions on
the findings below: decided by Claude under the owner's 2026-10-23 22:30 rule (no money, no
who-may-do-what). The commit hash is in `git log` (this record is part of that commit).

## Gates before the review (on 7738b3f)

Full PostgreSQL run 2,688 passed and 2 failed (the ID-number race test, fixed in 7738b3f, and the
known statement timeout of `test_settlement_return_reversal_migration.py`, slice 12 list); unit
4,061 passed; frontend 1,640 passed with format, lint, types and build.

## Final review of the whole login slice

Three read-only review agents (no files written), each over the whole login slice diff from
L1a to L7c: (1) the sign-in screens and the first-Owner set-up, (2) authorization (route
inventory, capabilities, Settings access, account administration), (3) authentication (passwords,
sign-in waits, TOTP, recovery codes, sessions, reauthentication, the key file).

### Reviewer 1: screens and the first-Owner set-up

- BLOCKER, fixed: the set-up ended without saying whether the Owner was made. `bootstrap-owner.sh`
  now keeps the set-up's exit status, clears the terminal and its scrollback, and says "The first
  Owner account is made." or "The set-up stopped and saved nothing (or the Owner was already
  made)." with what to do next (password rule, code, sentence; delete the new CHETANA entry in
  the authenticator; run step 5 again; throw away the codes). Test
  `test_local_run_scripts.py::test_the_owner_set_up_says_whether_the_owner_was_made`.
- Should-fix, fixed: the set-up accepted only the code of the current 30-second step, so a code
  read at second 27 and typed at second 31 failed the whole set-up. It now accepts this or the
  previous step, as sign-in does, and removes spaces typed inside the code. Test
  `test_set_up_code_of_this_or_the_previous_step_is_accepted_and_spaces_are_removed`.
- Should-fix, fixed: the recovery-code sentence had to match exactly in capitals. It is now
  compared without case and with runs of spaces made one. Test
  `test_acknowledgement_in_lower_case_or_with_extra_spaces_commits`.
- Should-fix, fixed: when sign-out did not reach the office computer, the screen went back to
  sign-in while the server session lived on. It now stays signed in and says "Sign out did not
  reach the office computer. Check the connection and sign out again." Test TEST-FE-710.
- Note, fixed: `autoCorrect="off"` on the username and code fields (iPad Safari).
- Note, fixed: the README names the authenticator entry CHETANA and says to sign in only at the
  `https://NAME.local:5173` address (`localhost` gets 403 by the Origin rule).
- Note, kept: another browser tab acting as another person (Q-2026-10-24-187 point 16).
- Note, kept: U+200B in display names (the L2c rule); the refusal message explains it.
- Open: the texts `au_rc_used` and `au_fg_owner_s` point to an emergency procedure that has no
  runbook yet; the QR picture has not been scanned by a real phone; the Khmer texts need the
  native check. Listed in ops/V1_056_PLAN.md.

### Reviewer 2: authorization

- No blocker.
- Note, fixed: account administration, audit, Property and Unit reads sent no caching rule. The
  middleware now sends `private, no-store` with `Vary: Cookie` on every `/api/v1/` answer that sets
  no caching rule of its own (answers that set `no-store` keep it). The account list test checks it.
- Note, slice 12: the runtime database role can create sessions and reauthentication proofs
  directly (the trust model of the app role); narrow its direct grants.
- Note, text only: the Q-2026-10-23-180 wording in the questions file.
- Note, already on the slice 12 list: Settings changes are audited under the old capability names.

### Reviewer 3: authentication

- No blocker.
- S1, open before V1-060: anyone who knows a username can keep that account, the Owner included,
  waiting without end by sending wrong passwords, and the emergency recovery does not clear the
  waits. The fix needs a migration (a definer function that clears the waits of one account, for
  a server-only role, used by the emergency recovery) and/or no username wait when a live MFA
  session reauthenticates. Listed in ops/V1_056_PLAN.md as an open item before V1-060.
- N1, slice 12: the runtime role's direct grants (as reviewer 2).
- N2, fixed: request and enrollment models now hide the password, code, provisioning link and QR
  picture when printed (`repr=False`). Test
  `test_request_and_enrollment_models_never_print_a_password_code_or_key`.
- N3, kept: a sign-out answered 401 leaves stale cookies in the browser; they are refused by the
  server and replaced at the next sign-in.

## Runs after the fixes

Backend format, lint and type check clean; targeted tests 107 passed (local run scripts,
bootstrap CLI, authentication API, account administration API); targeted PostgreSQL 158 passed
(bootstrap, sign-in wait, sign-in flow, reauthentication, recovery codes, sign-in codes,
account administration, one-time password); frontend 1,641 passed with format, lint, types and
build; traceability 28 passed and the TEST-118 audit passed. The full unit and PostgreSQL runs
are in ops/NOW.md and the docs/010 entry.
