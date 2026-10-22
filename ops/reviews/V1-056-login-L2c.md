# V1-056 login sub-slice L2c — hidden characters in names and reasons — review record

Sub-slice L2c of the login slice (new, before L3a; ops/V1_056_PLAN.md section 7.3). Migration
`20270126_183`. Base commit: 8a706c4 (the owner answer to Q-2026-10-22-169, recorded first,
docs only). Built on 2026-10-22 in a fresh session. Not pushed. The commit hash is in `git log`
(this record is part of that commit).

## Owner answer recorded first (commit 8a706c4)

Q-2026-10-22-169 (a): Khmer keyboards put an invisible space (U+200B) between words, so the API
removes U+200B from names and reasons before saving and refuses the few other invisible
characters still accepted; a character that normal Khmer typing needs (for example U+200C or
U+200D) gets a question instead of a refusal; the same rule wherever the login slice checks
names or reasons; other parts of the app (for example Customer names) go on the slice 12 list.
Owner's example: Staff member "សុខា ចាន់" created on an iPad is saved and looks the same.

## Placement

Its own small sub-slice before L3a (the owner allowed "before L3a, or inside L3a"): it changes
the L2b name and reason steps and two database name checks; L3a's sign-in then uses the same
username rule.

## Built

- New `backend/src/property_rental/visible_text.py`: `without_zero_width_spaces`,
  `HIDDEN_NAME_CHARACTERS` and `HIDDEN_REASON_CHARACTERS` (the name list less U+200C, U+200D and
  U+FE0F). After review round 1 the lists are the Unicode default-ignorable characters plus the
  C0 and C1 controls, U+2028, U+2029, U+2800 and U+FFF9 to U+FFFB.
- `access_admin_api.py`: `BoundedName` and `BoundedReason` remove U+200B before the trim and the
  length rule; a reason refuses `HIDDEN_REASON_CHARACTERS` and a reason with nothing visible
  (U+200C, U+200D and U+FE0F do not count as visible; review round 2).
- `access_admin_flow.py`: the name and username steps remove U+200B first; the new constraint
  name maps to 422 `INVALID_NAME`.
- `local_authentication.py`: `normalize_local_username` (the sign-in lookup and the attempt
  limiter key) removes U+200B and makes the username NFC, the same as account creation.
- Migration `20270126_183` (a tightening, approved with the answer):
  - A read-only guard first: the upgrade refuses to run while a stored username is not NFC or
    holds U+200B (review round 1).
  - `app.assert_account_names` is replaced, with the same signature, owner, privileges,
    attributes and message.
  - New check constraint `role_bundles_name_visible_check`.
  - Both refuse, besides the L1b-2 and L2a characters:
    - the new invisible characters;
    - a space other than U+0020, or two U+0020 in a row (review round 1);
    - a name that is not NFC.
- New owner question Q-2026-10-22-170 (U+200C and U+200D in names; U+FE0F in names; U+17B4,
  U+17B5 and flag emoji in reasons; the database space rule; nothing waits).
- Tests: PostgreSQL `test_name_hidden_characters_migration.py` (5 tests, one parametrized: 6
  cases; last in `scripts/database-test.sh`); unit tests: 2 in `test_access_admin_api.py`, 1 in
  `test_access_admin_flow.py`, 1 in `test_local_authentication.py`. Traceability: 9 entries
  appended, one note changed.
- Docs: docs/004 DB-AUTH-007 and DB-AUTH-010 notes; docs/005 API-080 and API-096 notes; docs/010
  DL-081 (Q-169 note, L2c and "Updated tests" lines); plan section 7.3 (L2c section, L4 and L7
  notes, slice 12 item).

## Committed tests changed

- The 27 head-revision strings (`20270125_182` to `20270126_183`) in 15 modules; nothing else.
- `test_access_admin_api.py::test_settings_access_and_assignment_removal_need_a_valid_reason_and_known_fields`:
  the Khmer reason now reaches the flow without U+200B (owner answer); its traceability note
  says so.
- `test_access_admin_flow_migration.py`: one display name in
  `test_the_flow_creates_lists_and_changes_accounts_through_the_audited_functions` and one
  bundle name in `test_the_flow_administers_role_bundles_and_assignments` were refused for
  U+200B. They now hold U+200E, so they are still refused as `INVALID_NAME` by the older checks
  (review round 1). Names with U+200B are now saved without it; the new module checks that.
- `test_access_admin_flow.py::test_every_known_database_message_is_word_for_word_in_the_migrations`:
  its exact set of constraint keys gains `role_bundles_name_visible_check` (found by U1).
- Reviewers of rounds 1 to 3 compared these with HEAD and found nothing weaker.

## Read-only search for affected tests

- Hidden or odd-space names that tests hand to the database directly: only U+200B cases
  (`test_access_administration_migration.py`, `test_role_bundle_migration.py`). The database
  still refuses U+200B, so they are unchanged.
- Names with NBSP or double spaces: only through the flow, which folds them
  (`test_access_admin_flow_migration.py`).
- Function, constraint and catalog lists: they compare fixed revisions on throwaway databases.
- Usernames that are not NFC in upgrade tests: none.
- No truncate list or trigger changes.

## Design changes (under the design-change run rule; confirmed as needed and safe by review round 2)

1. The hidden-character lists also hold:
   - the variation selectors;
   - U+180B to U+180F and U+2800;
   - U+FFF0 to U+FFF8;
   - U+1BCA0 to U+1BCA3 and U+1D173 to U+1D17A;
   - U+E0080 to U+E0FFF.

   For example, "staff" and "staff" with U+FE00 look the same. A reason keeps U+FE0F.
2. The database name checks refuse a space other than U+0020 and two U+0020 in a row. The API
   already folds them, so this only stops a caller that skips the API. It is in Q-170 so the
   owner sees the tightening.
3. The migration guard on stored usernames (read-only).

## Reviews

- **Round 1** (two fresh agents).
  - Independent: no blocker. Three should-fix:
    - a committed flow case lost its coverage of the older check;
    - the test claimed an exact comparison it did not make;
    - the DL-081 wording was too wide.
  - Security: no blocker. Four should-fix:
    - more invisible characters;
    - the database space rules;
    - the username guard;
    - a sign-in normalization test.
  - All done. Notes taken: function attributes in the forward-only test, update-path tests, and
    the L4 and L7 notes.
  - Test set-up (exact comparison): on the module's throwaway database at head, as the
    migration owner:
    - create `pg_temp.refused_account_names(int[])` and `pg_temp.refused_bundle_names(uuid,
      int[])`. Each tries 'A' || chr(point) || 'B' per point in its own subtransaction and
      returns the points refused with 22023 or 23514;
    - the candidates are U+0001 to U+FFFF without surrogates, U+1BC00 to U+1BCFF, U+1D100 to
      U+1D1FF and U+E0000 to U+E0FFF;
    - the expected set is the Python list, plus the folded spaces, plus the database's own set
      of points that make the name not NFC;
    - roll back at the end.
- **Round 2** (one fresh agent, both checklists; after U3 and P2): no blocker; the three design
  changes confirmed. Two should-fix, both done:
  - a reason of only U+FE0F was accepted (now refused);
  - the reason list had no full test (new unit test over every code point).

  Notes taken: Q-170 points; the locale provider assertion; the U+200B guard case; a bundle
  rename case; the docs/005 API-096 note; the docs/004 note on names saved before L2c.
- **Round 3** (one fresh agent, both checklists; after U4 and P3): no blocker, and no code,
  migration or test should-fix. Two text should-fix were done under the round-3 text rule:
  - the Q-170 heading;
  - the docs/005 U+0000 wording.

  Notes taken as text: the DL-081 Q-169 wording and the L3a note. Process note: the round 3
  agent ran one no-op `python3 -c 1` against its read-only instruction. It wrote nothing and
  touched no database.
- Notes kept for later sub-slices:
  - L3a keeps the sign-in username bounded;
  - L4 moves the recovery reason to `BoundedReason`;
  - L7 makes the bootstrap username follow `normalize_local_username`, with a test;
  - the screen rebuild shows names and reasons in an isolated text direction;
  - Unicode version gap: Python has Unicode 14, PostgreSQL 15.1 (fails closed).

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-login-L2c-`)

| Run | Result | Cause |
|---|---|---|
| FF1, I1, FC1, L1 | pass | backend checks |
| Y1 | fail | cause A (1 of 2): new test indexed `object` values |
| FF2, I2, FC2, L2 | pass | after the cause A fix |
| Y2 | fail | cause A (2 of 2): mypy narrowed a tuple after an equality assert |
| FF3, I3, FC3, L3, Y3 | pass | after the second cause A fix (list-slice comparisons) |
| U1 | 3,887 passed, 1 failed | cause B (1 of 2): the exact constraint-key set lacked the new constraint |
| FF4, I4, FC4, L4, Y4 | pass | after the cause B fix |
| U2 | 3,888 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 526 passed | targeted: the 15 head-revision modules and the five bundle and administration modules |
| M2 | pass | migration-only check |
| P1 | 2,513 passed | full PostgreSQL run |
| FF5 (one file reformatted), I5, FC5, L5, Y5 | pass | after the round 1 fixes |
| M3 | pass | migration-only check |
| T2 | 44 passed, 1 failed | cause C (1 of 2): the rewritten test lost an `update_user` argument |
| FF6, I6, FC6, L6, Y6 | pass | after the cause C fix |
| T3 | 45 passed | targeted: the bundle, administration, flow and new modules |
| U3 | 3,889 passed | unit suite |
| M4 | pass | migration-only check |
| P2 | 2,514 passed | full PostgreSQL run |
| FF7, I7, FC7, L7, Y7 | pass | after the round 2 fixes |
| M5 | pass | migration-only check |
| T4 | 14 passed | targeted: the flow and new modules |
| U4 | 3,890 passed | unit suite (before round 3) |
| M6 | pass | migration-only check |
| P3 | 2,515 passed | full PostgreSQL run (before round 3) |

- Cause A used 2 of 2 corrections; causes B and C used 1 of 2 each.
- No `LockNotAvailable` failure. P1 to P3 show only the known Starlette warning and (P2, P3) the
  known pydantic `UnsupportedFieldAttributeWarning` of the unchanged
  `test_credit_refund_api_migration.py`.
- After P3, only text changed: docs/005, docs/010, the questions file, the plan, this record and
  NOW.md.
- No frontend file changed.
- Still pending (not touched): the test rename in `test_deposit_receipt_refund_out_migration.py`.
