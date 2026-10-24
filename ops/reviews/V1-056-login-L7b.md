# V1-056 login sub-slice L7b — the server set-up stores the Owner's username in the sign-in form — review record

Sub-slice L7b of the login slice (ops/V1_056_PLAN.md section 7.3, L7: the L2c note and the
binding of owner answer Q-2026-10-22-170 (a)). No migration. Built on 2026-10-24 in the cloud
session after L7a. The commit hash is in `git log`.

## Built

- `PostgresInitialOwnerBootstrapRepository` stores `normalize_local_username(username)` (NFC,
  spaces tidied, lower case), the form sign-in looks up and account creation stores, instead
  of `casefold()`, which differed for letters such as ß and did not make the name NFC.
- `BootstrapRequest` keeps its refusals (empty, edge spaces, characters that are not
  printable, a username that tidying would change) and now also applies the account name rule
  of account creation (`app.assert_account_names`), which the bootstrap SQL does not run, to the
  stored username and to the display and audit names: 1 to 128 characters, NFC, no two spaces
  in a row, none of the hidden characters.
- Tests: the PostgreSQL test `test_migrations.py::test_the_bootstrap_stores_the_owner_username_as_sign_in_looks_it_up`
  (it fails with the old storage: "sokhá strasse" stored, "sokhá straße" looked up), and the unit
  tests `test_request_refuses_a_username_whose_stored_form_would_not_be_nfc` and
  `test_request_refuses_names_that_account_creation_refuses`; the docstring of
  `test_request_refuses_a_username_that_sign_in_would_tidy` brought up to date.

## Review round 1 (one independent agent, read-only, no files written)

- No blocker. The stored value equals what sign-in computes for every accepted username; no
  circular import; the PostgreSQL test tests what it says.
- Should-fix, done: lower case can undo NFC ("J̌ohn" lowers to a decomposed j-caron), which
  account creation refuses; the bootstrap now refuses such a username (unit test).
- Notes taken: the docs said "U+200B removed" where the bootstrap refuses it.

## Review round 2 (one fresh agent, read-only, no files written)

- No blocker. Round 1 fix checked.
- Should-fix, done: hidden but printable characters (U+3164 and others) and names over 128
  characters (lower case can grow a name) were accepted, because the bootstrap SQL does not run
  `app.assert_account_names`; the request now applies that rule to the three names (unit test).

## Review round 3 (one fresh agent, read-only, no files written)

- No blocker. The Python hidden-character class covers every SQL class of the rule; Python and
  PostgreSQL count length the same way; nothing the CLI, README or plan passes is refused.
- Should-fix, done without a round 4 (one more condition of the same rule, with test cases that
  fail without it): two spaces in a row in the display or audit name were accepted; now refused,
  and the three texts that said the whole rule applied are corrected.
- Notes kept: the bootstrap stays stricter than account creation in a few cases (a display name
  with U+200B, which Khmer keyboards add and creation removes, is refused with the generic
  "invalid initial Owner bootstrap identity"): the L7 runbook tells the Owner to type the
  display name without it.

## Runs

- Static checks: ruff, format and mypy (418 files): clean.
- T0: the new PostgreSQL test against the old storage: failed as expected.
- T1 (the new PostgreSQL test, the production recovery factory test, the bootstrap, account
  class and local authentication modules): 69 passed.
- Unit: `test_initial_owner_bootstrap_cli.py` 30 passed after round 3.
