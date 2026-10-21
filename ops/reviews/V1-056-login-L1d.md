# V1-056 login sub-slice L1d — per-user Settings access — review record

Sub-slice L1d of the login slice. Migration `20270121_178`. Base commit: 6b05a54 (L1b-2). Built on
2026-10-21 in the same session as L1b-2. Not pushed. The commit hash is in `git log`.

Order: L1c (default bundles) waits for the owner's answer to Q-2026-10-21-164. That question is
about nine bundle capabilities that the Staff bundle answer does not name; it is written in this
sub-slice's questions file change. L1d does not depend on the default bundles, so it was built
first, as the owner's instruction of 2026-10-21 allows.

## Built

- `app.user_capability_grants` (append-only):
  - stores only `settings.manage` with grant path `per_user`: a check, plus a foreign key to the
    catalog on both columns;
  - records the account, who gave it (an account), when, a reason and provenance (at most 500
    characters);
  - an account has at most one active grant. This is checked under a per-account advisory lock,
    at READ COMMITTED only (23505; 55000 at any other isolation level).
- `app.user_capability_grant_removals` (append-only): a grant ends at most once, with who, when
  and why.
- Both relations refuse UPDATE, DELETE and TRUNCATE (23000).
- Definer function `app.give_settings_access(owner, account, reason)`:
  - the acting account must be the active Owner class (42501);
  - the target must be an active Manager or Staff account (22023).
- Definer function `app.remove_settings_access(owner, account, reason)`:
  - the acting account must be the active Owner class (42501);
  - it takes the same lock, at READ COMMITTED only;
  - it needs an active grant (55000).
- `app.assert_settings_access_owner(uuid)` is the internal Owner check: not a definer, and not
  executable by the runtime role.
- The reader `app.actor_capability_grants` is replaced with the same signature, owner,
  privileges and attributes. It also gives `settings.manage`, for every Property, to:
  - the Owner account class;
  - an active, classified account with an active grant.
- `READER_GRANT_PATHS` accepts `per_user`.
- `prm_runtime` may execute only the two definer functions and the reader.
- Tests:
  - `test_settings_access_migration.py`: 7 PostgreSQL tests, last in `scripts/database-test.sh`;
  - traceability: 7 entries appended, and two L1b-2 notes edited;
  - head-revision strings: 27 in 15 modules.
- Docs:
  - docs/004 DB-AUTH-008 and the matrix row;
  - docs/008 SEC-021 note;
  - docs/010 DL-081 lines;
  - plan section 7.3 (order, pre-code design, as-built bullet).

## Committed tests changed

- The 27 head-revision strings. Nothing else in those modules changed.
- Expectations changed with the approved plan (Q-2026-10-21-151 (a): the Owner always has
  Settings access, and the reader gives it from L1d):
  - `test_role_bundle_migration.py::test_the_grant_reader_gives_an_active_classified_account_its_current_capabilities`:
    the Owner also gets `settings.manage`;
  - `test_access_control.py::test_the_grant_reader_groups_property_ids_and_refuses_names_it_may_not_give`:
    `settings.manage` is now accepted instead of refused.
- Set-up changed because of the new foreign keys:
  - `test_role_bundle_migration.py::test_a_role_bundle_name_is_unique_per_property_and_every_version_is_kept`:
    the catalog TRUNCATE also names `app.user_capability_grants` and
    `app.user_capability_grant_removals`;
  - the check and its message are unchanged.
- Round 2 compared all three with HEAD and found nothing weaker.

## Read-only search for affected tests

- Done before the first full run, and widened after targeted run T1 (cause B) to tests that
  truncate `app.capabilities`, `app.user_accounts` or `app.properties`. It found two such tests:
  - the catalog test: still matches, same message;
  - the L1b-2 name test: changed as above.
- Lesson for later sub-slices: a new foreign key to an existing table also breaks committed tests
  that TRUNCATE the referenced table. Search for them before the first run.

## Review round 1 (one fresh agent, both checklists)

No blocker. Four should-fix items, all done:

1. **A disabled account's Settings access could not be removed.** It came back when the account
   was enabled again, and a disable racing a give could leave such a grant.
   - Fixed by a design change, under the design-change run rule: a removal checks only the
     acting Owner, and the target check moved into the give function.
   - Test: the Owner removes a disabled Staff account's grant; after the account is enabled
     again, it has no Settings access.
2. **No test showed that a removal takes the lock.**
   - Built, as an extra block of the race test.
   - Set-up:
     1. Commit a Manager giver, a Staff holder and a grant written by hand.
     2. Connection `first`: add an Owner, uncommitted, and run the removal, uncommitted.
     3. Connection `second` (`lock_timeout=15s`, in a thread): insert a grant for the holder.
     4. A watcher waits until `second` shows `('Lock','advisory')`.
     5. `first` rolls back.
     6. `second` gets 23505 "this account already has Settings access".
3. **The TRUNCATE set-up change was not recorded.** It is now recorded in DL-081 and the plan.
4. **The "audited" tests of the plan's L1d section were dropped without a record.**
   - Recorded: the functions write no audit event; the L2 routes write it in the same
     transaction (SEC-014, SEC-075).
   - The grant and removal rows keep who, when and why.

Notes taken:
- a test: an unclassified account with a hand-written grant gets nothing;
- a DB-AUTH-008 line on the Property scope (every Property, as for `identity.manage_access`).

Notes kept for L2:
- pass the acting Owner only from the session;
- run the Q-157 reauthentication first;
- validate the reason;
- write the audit event in the same READ COMMITTED transaction;
- map 42501, 22023, 23505 and 55000 to consistent errors;
- decide what disabling an account does to its assignments and grants.

Note for the owner: a Staff account with optional MFA can hold Settings access; the rules do not
ask for MFA there.

## Review round 2 (one fresh agent, both checklists)

No blocker, no should-fix. The design change is confirmed as **needed** and **safe**:
- Needed: "only the Owner gives or removes" did not hold for a disabled account.
- Safe:
  - a removal only takes access away;
  - it still needs the active Owner class, the same lock, READ COMMITTED and an active grant;
  - the Owner never has a grant row, because a give to the Owner is refused.

The other checks also held:
- the round 1 tests;
- the replaced reader: byte-for-byte the same earlier branches;
- the committed test changes compared with HEAD;
- least privilege for the six roles;
- traceability;
- the docs.

Notes:
1. The give function reads the target's active state without a row lock. A disable committed at
   the same moment can leave a grant on a disabled account; the reader gives it nothing and the
   Owner can remove it. Kept for L2, which may lock the account row (`FOR SHARE`) when it gives.
2. The traceability notes cite SEC-014 and SEC-075 without an audit event. Taken as text: the
   notes now say that the audit event comes with L2.
3. The removal's lock and READ COMMITTED rule was not stated. Taken as text in docs/004 and
   DL-081.
4. The acting Owner id is a parameter that the runtime role is trusted to pass from the session;
   this is the same pattern as the earlier definers. Already in the plan's L2 notes.

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-login-L1d-`)

| Run | Result | Cause |
|---|---|---|
| FF1, I1, FC1 | pass | backend checks |
| L1 | fail | cause A (1 of 2): a docstring edit joined two lines (167 characters) |
| FF2, I2, FC2, L2, Y1 | pass | after the cause A fix |
| U1 | 3,875 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 38 passed, 1 failed | cause B (1 of 2): the new foreign key to `app.capabilities` refused the L1b-2 test's catalog TRUNCATE before the trigger |
| FF3, I3, FC3, L3, Y2 | pass | after the cause B fix (set-up) |
| T2 | 20 passed | targeted: the catalog, role bundle and new modules |
| M2 | pass | migration-only check |
| P1 | 2,472 passed | full PostgreSQL run |
| FF4, I4, FC4, L4, Y3 | pass | after the round 1 fixes |
| M3 | pass | migration-only check |
| T3 | 20 passed | targeted: the same three modules |
| U2 | 3,875 passed | unit suite |
| P2 | 2,472 passed | full PostgreSQL run |

- One correction for cause A (1 of 2) and one for cause B (1 of 2).
- No `LockNotAvailable` failure.
- After P2, only text changed: the round 2 notes, this record and NOW.md.
