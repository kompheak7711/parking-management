# V1-056 login sub-slice L2d — tidy spaces in names and at sign-in — review record

Sub-slice L2d of the login slice (new, before L3a; ops/V1_056_PLAN.md section 7.3). No
migration. Base commit: 759f373 (the owner answer to Q-2026-10-22-170 and the owner's speed
rules, recorded first, docs only). Built on 2026-10-22 and 2026-10-23 in a fresh session. Not
pushed. The commit hash is in `git log` (this record is part of that commit).

## Owner answer recorded first (commit 759f373)

Q-2026-10-22-170 (a): names keep refusing U+200C, U+200D and an emoji with U+FE0F; reasons keep
refusing flag emoji, U+17B4 and U+17B5. Odd and double spaces are not refused on the screen: the
API tidies a name before saving (other spaces become ordinary spaces, a run becomes one, the ends
are trimmed); the database rule stays the last guard; sign-in tidies the typed username the same
way. Owner's example: Staff types "Sokha  Chan" with two spaces on the iPad; it is saved as
"Sokha Chan" and nobody sees an error. Binding for L7: the first-Owner bootstrap stores the
username by the sign-in rule, with a test.

## Placement

Its own small sub-slice before L3a (the owner allowed "before L3a, or inside L3a"): it changes the
same name, username and sign-in lookup steps as L2c, and L3a then builds the sign-in on the
finished username rule.

## Built

- `visible_text.py`: `SPACE_SEPARATORS` (moved from the flow; Unicode category Zs) and
  `tidy_spaces` (each run becomes one U+0020, none at either end).
- `access_admin_api.py`: `BoundedName` removes U+200B and tidies spaces before the trim and the
  128 limit. New `RecoveryReason` keeps the L2c rule for the Owner's reset reason (review round
  1), until L4 moves it to `BoundedReason`.
- `access_admin_flow.py`: `normalized_name` uses `tidy_spaces`; `normalized_username` is
  `normalize_local_username` followed by a refusal of any white space left that is not U+0020.
- `local_authentication.py`: `normalize_local_username` (the sign-in lookup and the attempt
  limiter key) removes U+200B, makes the username NFC, tidies spaces and lower-cases it.
- `initial_owner_bootstrap.py`: `BootstrapRequest` refuses a username that `tidy_spaces` would
  change (review round 1, security; design change, see below).
- Database: nothing changes; the L2c name checks stay the last guard. Frontend: nothing changes
  (the account form only checks that the display name is not blank).
- Tests: unit — 1 in `test_local_authentication.py`, 2 in `test_access_admin_flow.py`, 1 in
  `test_access_admin_api.py`, 1 in `test_initial_owner_bootstrap_cli.py`; PostgreSQL — 1 in
  `test_name_hidden_characters_migration.py` (already in the full-run list). Traceability: 6
  entries appended, three notes changed (entries after the first 1,598).
- Docs: docs/004 DB-AUTH-010 note; docs/005 API-080 and API-096 notes; docs/010 DL-081 (L2d and
  "Updated tests" lines); plan section 7.3 (L2d section, L7 binding line); the questions file
  (one decision under the owner's 2026-10-22 rule).

## Decided by Claude Code under the owner's 2026-10-22 rule

- Tabs, line breaks and other control characters are not spaces: they are not tidied and stay
  refused (a paste mistake; the database refuses them). Recorded in ops/V1_056_QUESTIONS.md as
  Q-2026-10-23-171.

## Committed tests changed (the owner answer changes the result)

- `test_access_admin_flow.py::test_names_are_nfc_with_single_spaces_and_usernames_lower_case`:
  the usernames with U+00A0, U+2009 and U+3000 are now saved as "ann lee" instead of refused;
  "ann" + tab + "lee" is still refused. Traceability note updated.
- `test_access_admin_flow_migration.py::test_the_flow_refuses_each_reachable_case_and_rolls_back_a_mismatched_result`:
  the username refused as `INVALID_NAME` now holds a tab instead of a no-break space (found by
  the read-only search before T1). Traceability note updated.
- `test_name_hidden_characters_migration.py` imports `SPACE_SEPARATORS` from `visible_text`.
- Reviewers of rounds 1 to 3 compared these with HEAD and found nothing weaker.

## Read-only search for affected tests

- Tests that call `normalized_username`, `normalize_local_username`, `find_by_username`,
  `create_user(` or `SPACE_SEPARATORS`, and tests that hand names with odd or double spaces to
  the flow or the database: only the two committed cases above changed result. Display names
  with double spaces in `test_access_admin_flow_migration.py` were already folded.
- `BootstrapRequest` users (`test_initial_owner_bootstrap_cli.py`, `test_migrations.py`) use
  usernames with no spaces.
- No function, grant, trigger or truncate list changes.

## Design change (under the design-change run rule; confirmed as needed and safe by review round 2)

1. The first-Owner bootstrap request refuses a username that tidying would change (two spaces in
   a row; other spaces and spaces at either end were already refused as not printable or not
   trimmed). Reason: the bootstrap database function stores the username as typed and runs no
   name check, and sign-in now tidies, so such an Owner could never sign in. The database
   function is not changed; L7 still makes the bootstrap store the full sign-in form (NFC,
   tidied, no U+200B), with a test (binding).

## Reviews

- **Round 1** (two fresh agents; after U1 and P1).
  - Independent: no blocker. Two should-fix, both done:
    - the Owner's reset reason was tidied as a name (now `RecoveryReason`);
    - the database test proved sign-in only by string equality (now a real lookup as the
      runtime role, with a test credential row written as the table owner).
  - Security: no blocker. Two should-fix:
    - the bootstrap could store a username with two spaces that sign-in would no longer find
      (design change 1);
    - a username with two spaces saved before migration `20270126_183` would no longer be found:
      written answer, no guard (no persistent database exists; the administration functions refuse
      such a name after that migration; the bootstrap request refuses it since L2d).
  - Optional notes done: docs/004 note, `visible_text` docstring, docs/005 wording, a name of only
    odd spaces refused, a test that `SPACE_SEPARATORS` is exactly Unicode Zs.
- **Round 2** (one fresh agent, both checklists; after U2 and P2): no blocker; design change 1
  confirmed; the written answer accepted. One text should-fix (the pre-183 wording in DL-081 and
  the plan) and a docs/004 wording note, both done. Note kept: the API test of a name of only
  spaces checks the 422 status, not the error code (no test change after P2).
- **Round 3** (one fresh agent, both checklists): no blocker. One text should-fix, done under the
  round-3 text rule: a test docstring said "tested above" for a test below it. Optional text done:
  "such as" before the list of refused white space in DL-081.
- Notes kept for later sub-slices:
  - L7: the bootstrap stores `casefold()` with no NFC step ("ß" stored as "ss", sign-in looks for
    "ß"), and its display and audit names are not tidied (binding L7 rule);
  - pydantic `strip_whitespace` trims a tab or line break at either end of a name at creation,
    while sign-in does not (fails closed; pre-existing);
  - L3a keeps the sign-in username bounded (`LoginRequest.username` is at most 256 characters);
  - L4 moves the reset reason to `BoundedReason`.

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-login-L2d-`)

| Run | Result | Cause |
|---|---|---|
| FF1, I1, FC1, L1, Y1 | pass | backend checks |
| U1 | 3,893 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 38 passed | targeted: account class, role bundle, administration flow and name modules |
| M2 | pass | migration-only check |
| P1 | 2,516 passed | full PostgreSQL run |
| FF2 (two files reformatted), I2, FC2 | pass | after the round 1 fixes |
| L2 | fail | cause A (1 of 2): a new docstring line of 102 characters |
| FF3, I3, FC3, L3, Y2 | pass | after the cause A fix |
| U2 | 3,895 passed | unit suite |
| M3 | pass | migration-only check |
| T2 | 29 passed | targeted: account class, administration flow and name modules |
| P2 | 2,516 passed | full PostgreSQL run (before round 2 and round 3) |
| FF4, I4, FC4, L4, Y3 | pass | after the round 3 text fixes |
| M4 | pass | migration-only check |
| T3 | 7 passed | targeted: the name module (round 3 docstring) |

- Cause A used 1 of 2 corrections.
- No `LockNotAvailable` failure. P1 and P2 show only the two known warnings.
- After P2, only text changed: a test docstring, docs/004, docs/010, the plan, the questions
  file, this record and NOW.md.
- Process note: I2 was started in the same tool call as a read-only `git diff --stat`, against
  the one-check-per-call rule; it passed and nothing else ran with it.
- No frontend file changed.
- Still pending (not touched): the test rename in `test_deposit_receipt_refund_out_migration.py`.
