# V1-056 login sub-slice L6 — the sign-in screens — review record

Sub-slice L6 of the login slice (ops/V1_056_PLAN.md section 7.3, L6). No migration.
Base commit: 3950b87 (L5). Built on 2026-10-24 in the cloud session. Decisions: the owner chose
on 2026-10-21 08:45 ("Yes, in login") that L6 builds the 9 sign-in screens of the owner's
mock-up; the owner approved the `qrcode` library on 2026-10-23; technical and wording points in
Q-2026-10-24-187, decided by Claude under the owner's 2026-10-23 22:30 rule. The commit hash is
in `git log` (this record is part of that commit).

## Built

- A full-screen sign-in layer (`SignInScreens.tsx`, `signInText.ts`, `signIn.css`) in the
  CHETANA brand, in Khmer and English, with the fonts and logo served by the app. Screens: Sign
  in, Two-step sign-in (code or recovery code), Forgot your password, Choose a new password, Set
  up two-step sign-in (QR picture and key), Your recovery codes (once, after the set-up), and You
  were signed out (30 minutes without use, or the 24-hour limit). It follows the server's phase
  and opens the app only on `authenticated`. The old sign-in forms in `App.tsx` are removed.
- The enrollment answer gains `qr_code_svg` (`totp_qr.py`, `qrcode` 8.2); the TOTP issuer is
  "CHETANA Residence".
- `GET /api/v1/auth/recovery-codes` (plan bindings of L3c-2c-1 review rounds 1 and 2): the live
  recovery-code set without its codes, or null; the account screen shows it and replaces it by
  its id. The runtime role could already read the columns, so no migration.
- `authClient.ts`: `RateLimitedError` (with `Retry-After`) and `ServiceUnavailableError`, the
  display name, the QR picture and the live-set read.
- Tests: `SignInScreens.test.tsx` (TEST-FE-686 to TEST-FE-705), TEST-FE-706 and TEST-FE-707,
  TEST-FE-AUTH-012 to TEST-FE-AUTH-014, `test_totp_qr.py`, the live-set API and PostgreSQL
  tests; changed committed tests in docs/010, "Updated tests (login sub-slice L6)".

## Review round 1 (one independent agent, read-only, no files written)

- No blocker. The app opens only after `authenticated`; no secret reaches storage, the address
  or a log; the QR picture is shown as an image, so nothing in it can run.
- Should-fix, all done: (1) a session restore answering while a sign-in was on its way could
  open the app for the older session (the TEST-FE-110 mix-up): the sign-in now raises the
  operation sequence when it is sent (TEST-FE-706); (2) the signed-out screen said nobody used
  the app for 30 minutes, but every request moves the server's 30 minutes on and the timer
  started at sign-in: the app now asks the server first and stays open while the server holds
  the session for the same person (TEST-FE-705); (3) React 19 writes a controlled box's text
  into its `value` attribute, so a typed password was in the page's HTML: passwords and codes
  are now read from their boxes and never kept in state (TEST-FE-702); (4) a set-up that could
  not start left a screen with no QR code and no way on: it goes back to sign in with the wait
  or offline message, and the set-up screen says the QR code is coming (TEST-FE-704);
  (5) au_rc_used asked a recovery-code session to make codes it cannot: new text (Khmer needs
  the native check); (6) "Back to sign in" did not drop a running request: a generation
  counter drops its answer (TEST-FE-703); (7) nothing showed a running request: "Please wait…"
  with `aria-busy`.
- Notes taken: `$` in a name is shown as typed; the rule list is no longer a live region; a
  hidden username box helps password managers; the QR picture is 200 px. Notes kept: the
  client's step clock starts slightly after the server's (a 401 just before the client's limit
  says the code is wrong; safe); copied recovery codes stay in the clipboard (from the mock-up;
  the text warns); a reload on the recovery-codes screen opens the app without the codes (the
  account screen now shows the live set, so the person can replace it); focus after sign-in and
  the announcement of notes that come with a new view are for the screen rebuild; the fonts are
  TTF (WOFF2 later); `uv.lock` also gained greenlet wheel entries from the newer uv (harmless);
  `test_totp_qr.py` checks the picture against the library's matrix, not by decoding it (no
  decoder is installed here; the first real set-up at L7 scans it with a phone before the
  Owner relies on it).
- Tests whose names said more than they test: TEST-FE-700 retitled; TEST-FE-AUTH-013 now says
  the picture is only checked to start as an SVG.

## Review round 2 (one fresh agent, read-only, no files written)

- Blocker, fixed: round 1 fix 3 left the boxes without keys, so React reused the username box as
  the code box after a sign-in (controlled to uncontrolled), and it opened holding the
  username; every two-step sign-in was affected. Each field now has its own key; TEST-FE-708
  checks that every code and password box opens empty after the step before it, with no React
  warning (it fails without the keys).
- Should-fix, both done: (1) the account screen showed "could not be checked" while the
  live-set read was still running: it now shows nothing until the answer (TEST-FE-707 checks
  the running read); (2) no test for the timer's two other branches: TEST-FE-709 (another
  person's session, and no answer from the server, both end the app).
- Notes kept: the live-set read needs a live session, reads only its own account, returns no
  codes or verifiers and records no activity (so the timer's check cannot keep a session
  alive); a future CSP must allow `data:` images for the QR picture; "Back to sign in" after a
  confirmed set-up drops the first codes' answer (the account screen then shows the set and
  offers to replace it); `made_by` "other" reads "Made by the server set-up" (only the
  bootstrap writes another provenance today).
- Every round 1 fix checked: correct (the timer cannot loop, keep a session forever, or end one
  late).

## Review round 3 (one fresh agent, read-only, no files written)

- No blocker, no should-fix. The key fix was checked through every view change in memory: no
  box is reused for another field, every new box opens empty, the refs read and clear the live
  box, no secret box has a `value` attribute, and React gives no warning. Without the keys the
  code box reopens holding the username, as round 2 found. The live-set loading logic and
  TEST-FE-707 to TEST-FE-709 test what they say.
- Note taken: TEST-FE-708 now also types a code and a recovery code before each switch and
  checks that the next box opens empty. Notes kept: the account screen's layout moves a little
  when the live-set answer arrives.

## Runs

- Static checks: ruff, format and mypy (backend); prettier, eslint and tsc (frontend): clean.
- Targeted PostgreSQL (T1): the live-set read, the HTTP recovery-code routes and the enrollment
  module: 29 passed.
- F4 (full frontend with build, after round 1): 1,633 passed; F5 (after round 3): 1,635 passed.
- U1 (full backend unit, after round 1): 3,962 passed, 1 failed:
  `test_server_secret_source_names_cannot_be_frontend_environment_inputs` reads every file of
  `frontend/src` as text and stopped at the font files. The fonts moved to `frontend/assets/fonts`
  (outside `src`; the build still bundles them); the scan and the traceability audit then
  passed (42).
- P1 (full PostgreSQL): 2,677 passed, 1 failed:
  `test_settlement_return_reversal_migration.py::test_a_mistaken_credit_return_is_reversed_and_its_new_refund_is_charged_back`
  hit the 5-second statement timeout inside `app.record_settlement_return_reversal_draft` under
  the full run's load. L6 changes no money code or migration; R1 (that module alone): 18
  passed. Added to the slice 12 list of intermittent full-run failures (V1-060 needs them
  fixed, not rerun).
