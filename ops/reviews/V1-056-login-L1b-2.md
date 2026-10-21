# V1-056 login sub-slice L1b-2 — role bundles, assignments and the grant reader — review record

Sub-slice L1b-2 (the second half of L1b). Migration `20270120_177`. Base commit: 760c3dd (L1b-1).
Built on 2026-10-21 in a fresh session. Stopped after review round 3 for the owner's answer to
Q-2026-10-21-163; the owner answered (a) (fix both, run everything again, review round 4, commit
only if round 4 is clean). Round 4 was clean. Not pushed. The commit hash is in `git log`.

## Built

- `app.role_bundles` holds the current state of a bundle: its Property, its name and its version.
  - A name is trimmed and 1 to 128 characters.
  - A name has no control or invisible format characters (review round 1).
  - A name is unique per Property whatever its capital letters: unique index on `lower(name)`.
  - A new bundle starts at version 1.
  - An update may change only the name and must raise the version by exactly 1.
  - A bundle is never deleted or truncated.
- `app.role_bundle_versions` keeps every version.
  - A trigger writes the version with its name, transaction id and transaction start time.
  - A hand-written version row is refused.
- `app.role_bundle_capabilities` keeps the complete capability set of every version.
  - Only catalog capabilities with grant path `bundle` are allowed: a foreign key to
    `(capability_id, grant_path)` plus a check.
  - Capabilities are written only for the current version, and only by the transaction that
    wrote that version (same transaction id and same start time).
- `app.user_role_assignments` records each assignment, with who assigned it (an account, or null
  for seeds).
  - An account has at most one active assignment of a bundle.
  - That is checked under an advisory lock, at READ COMMITTED only.
- `app.user_role_assignment_removals` ends an assignment at most once, with a reason and who
  removed it.
- The four history relations are append-only.
- Grant reader `app.actor_capability_grants(uuid)`: SQL, STABLE, SECURITY DEFINER,
  `search_path=pg_catalog`.
  - It reads only active, classified accounts.
  - It returns the current capabilities of every actively assigned bundle, with the bundle's
    Property.
  - It gives `identity.manage_access` for every Property to the Owner account class only.
  - Only `prm_runtime` may execute it.
- `access_control.py` gains `PostgresCapabilityGrantReader`.
  - It groups Property ids per capability.
  - It refuses every grant (`CapabilityCatalogMismatch`) for a name outside the catalog, or one
    the reader may not give.
- Tests:
  - `test_role_bundle_migration.py`: 9 PostgreSQL tests, last in `scripts/database-test.sh`.
  - One unit test in `test_access_control.py`.
  - Traceability: 10 entries appended.
  - Head-revision strings: 27 in 15 modules.
- Docs: docs/004 DB-AUTH-007 and the matrix row; docs/010 DL-081 lines; plan section 7.3 (the
  pre-code design and the as-built bullet).

## Read-only search for affected tests (before the first full run)

- Searched for:
  - committed tests and helpers that list triggers, functions or grants (all are
    revision-specific on throwaway databases);
  - head-wide runtime EXECUTE checks (only named functions);
  - tests that delete or truncate `app.properties` or `app.user_accounts` (none).
- Missed: a committed test that truncates `app.capabilities`, the table the new foreign key
  refers to (run P1, cause A).

## Committed tests changed

- The 27 head-revision strings, nothing else in those modules.
- Historical narrowing, under the run rule: in
  `test_capability_catalog_migration.py::test_the_capability_catalog_is_append_only`, only the
  `TRUNCATE app.capabilities` case changed.
  - It now expects `FeatureNotSupported` ("cannot truncate a table referenced in a foreign key
    constraint"), because the new foreign key refuses the truncate before the trigger runs.
  - The comment and the docs/010 note are added.
  - The trigger's own refusal is now checked in the new module, with both tables in one TRUNCATE
    and the exact message.
  - Round 3 compared it with HEAD and found nothing weaker.

## Review round 1 (two fresh agents)

**Independent review: no blocker.**
- S1: the race test did not prove that the check runs after the lock.
  - Built: a waiting thread, seen in `pg_stat_activity` waiting on the advisory lock before the
    first assignment commits, then refused.
  - Set-up:
    1. Commit a Staff account and a bundle.
    2. `first` assigns and stays uncommitted.
    3. A thread assigns on `second`.
    4. A watcher polls `wait_event_type, wait_event` for `second`'s pid until it reads
       `('Lock','advisory')` (5 s deadline).
    5. `first` commits; the thread gets `UniqueViolation`.
- S2: assigned and removed actors are not referenced. Built: foreign keys to `app.user_accounts`,
  with a test.
- S3: Owner-class gaps. Built:
  - a disabled Owner with a bundle gets nothing (in a `force_rollback` savepoint, because at most
    one Owner exists);
  - an active Owner with a bundle gets the bundle's capabilities plus `identity.manage_access`.
- Notes taken:
  - the Python reader refuses catalog names it may not give;
  - SEC-003 is in traceability;
  - the docs/004 matrix row;
  - names are unique whatever their capital letters.

**Security review: no blocker.**
- S1: "a recorded version never changes" relied on `xid8` being unique, which a pg_dump logical
  restore can break.
  - Built: `recorded_transaction_started_at`, checked together with the transaction id.
  - Set-up (owner only, rolled back):
    1. Create a bundle and raise it to version 2.
    2. `ALTER TABLE app.role_bundle_versions DISABLE TRIGGER role_bundle_versions_are_append_only`.
    3. Move version 2's start time to 2000-01-01.
    4. Enable the trigger again.
    5. Inserting a version 2 capability is refused.
- S2: the same as the independent review's S2.
- S3: the same as the independent review's S3.
- Note taken: names have no control or invisible format characters, and reason and provenance
  are at most 500 characters.
- Notes kept for later sub-slices (also in the plan's as-built bullet):
  - **L1d:** restate SECURITY DEFINER, STABLE, `search_path` and the grants when it replaces the
    reader.
  - **L2:**
    - use the expected version;
    - write each version's complete capability set;
    - check `identity.manage_access` inside each writer and record the acting account;
    - decide what disabling an account does to its assignments.
  - **L3a:**
    - pass only the session's actor to the reader;
    - read on every request at READ COMMITTED, with no caching;
    - turn a mismatch into a refusal;
    - require MFA for the Owner and Manager classes;
    - normalize Property ids from requests.

## Review round 2

- The review agent could not start: the auto-mode classifier gave no verdict, because a hook
  rewrote the Agent call. As the blocked-agent run rule says, it was not retried. I did the round
  myself in the main session, read-only, on this sub-slice's changes, with both checklists.
- Result: no blocker. Two should-fix items, both done:
  - the new module's catalog TRUNCATE check now matches the exact message "capability catalog is
    append-only" (stricter test);
  - the plan's L1b-2 bullet now records the round 1 as-built changes (text).

## Review round 3 (one fresh agent, both checklists)

Before it ran: full unit suite U3 and full PostgreSQL run P3. Result: no blocker, two should-fix.
Work stopped for Q-2026-10-21-163; the owner answered (a), and both fixes were made as below.

- **SF1: the race test can hang instead of failing.**
  - If the 5-second assert fires, `second.__exit__` waits for the thread, the thread waits for the
    lock, and `first` is still open and holds the lock.
  - Fix: `first.rollback()` in the `finally` before the join, and a 15 s lock timeout on `second`.
- **SF2: the name check misses some invisible format characters that the docs say are refused.**
  - Missing: U+2066 to U+2069, U+061C, U+180E, U+206A to U+206F, U+FFF9 to U+FFFB and the tag
    characters U+E0000 to U+E007F. Also, `[[:cntrl:]]` depends on the database locale.
  - Fix: explicit C0 and C1 control ranges and these characters in the uncommitted migration's
    check; test names with U+2067 and U+0085.
- Notes:
  1. Any runtime caller may read any actor's grants. This is a reviewed design point: L3a passes
     only the session's actor.
  2. A logical restore must load data with triggers disabled; the future backup and restore
     runbook needs this.
  3. The migration takes SHARE ROW EXCLUSIVE locks with no lock timeout; run it with the writers
     stopped, as before.
  4. The `GrantCursor` protocol's signatures may not match psycopg structurally; L3a should type it
     against the real connection.
  5. "Null only for seeds" is not enforced; the L1c and L2 writers enforce it.
  6. DB-AUTH-007 does not say that `role_bundles` also refuses TRUNCATE; DL-081 cites SEC-017
     where the tests and traceability do not.

## Round 3 fixes (owner answer (a) to Q-2026-10-21-163)

- SF1: the second connection of the race test opens with `lock_timeout=15s`, and the `finally`
  rolls back the first connection before joining the thread (join timeout 20 s).
- SF2: the bundle name check lists the C0 and C1 control ranges (U+0001 to U+001F, U+007F to
  U+009F) and U+00AD, U+061C, U+180E, U+200B to U+200F, U+202A to U+202E, U+2060 to U+206F,
  U+FEFF, U+FFF9 to U+FFFB and the tag characters U+E0000 to U+E007F; new refused test names
  with U+2067, U+0085 and U+E0041.
- Text: DB-AUTH-007 says that `role_bundles` also refuses TRUNCATE; plan bullet for rounds 2 and 3.

## Review round 4 (one fresh independent agent, both checklists)

No blocker, no should-fix. It checked every path of the race test (a failed deadline check, a
thread error, a failed commit: none can hang), the PostgreSQL escapes and ranges (none overlaps
Khmer U+1780 to U+17FF or U+19E0 to U+19FF; U+17B4 and U+17B5 are accepted), the narrowed
committed test against HEAD (only the TRUNCATE case), traceability and least privilege. Notes:
1. A Khmer bundle name typed on a keyboard that inserts U+200B for a space is refused (fail
   closed); L2 decides how the API treats it (kept in the plan).
2. The docs claimed "no invisible format characters" while some rarer ones are not listed (for
   example U+0600 to U+0605, U+06DD, U+070F); taken as text: docs/004, DL-081 and the
   traceability note now name the exact list.
3. NBSP and other Unicode spaces, variation selectors and decomposed text are not covered; L2
   applies NFC, trims Unicode spaces and collapses spaces before saving (kept in the plan).
4. `[[:cntrl:]]` still depends on the locale (U+2028 and U+2029 under en_US.utf8); the listed
   ranges do not.
5. Optional tests: one refused name per range, and accepted Khmer and English names.
6. Optional race-test hardening: a daemon thread and a try/finally around the rollback.
7. L2 takes several assignments of one account in sorted bundle order (kept in the plan).
8. This record was out of date (updated here).

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-login-L1b-2-`)

| Run | Result | Cause |
|---|---|---|
| FF1, I1, FC1, L1, Y1 | pass | backend checks |
| U1 | 3,875 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 31 passed | targeted: the 23 head-revision tests and the new module |
| P1 | 2,463 passed, 1 failed | cause A (1 of 2): the committed catalog append-only test's `TRUNCATE app.capabilities` is now refused by the new foreign key first |
| FF2, I2, FC2, L2, Y2 | pass | after the cause A fix and the round 1 fixes |
| U2 | 3,875 passed | unit suite |
| M2 | pass | migration-only check |
| T2 | 13 passed | targeted: the catalog module and the new module |
| P2 | 2,465 passed | full PostgreSQL run |
| FF3, I3, FC3, L3, Y3 | pass | after the round 2 fixes |
| T3 | 9 passed | targeted: the new module |
| U3 | 3,875 passed | unit suite (before round 3) |
| M3 | pass | migration-only check |
| P3 | 2,465 passed | full PostgreSQL run (before round 3) |
| FF4, I4, FC4, L4, Y4 | pass | after the round 3 fixes |
| M4 | pass | migration-only check |
| T4 | 13 passed | targeted: the catalog module and the new module |
| U4 | 3,875 passed | unit suite |
| P4 | not run (exit 1) | cause B (1 of 2): the background run started in `backend/` (`cd: backend: No such file or directory`), against the script-start rule; no test ran |
| P5 | 2,465 passed | full PostgreSQL run, started from the repository root |

- One correction for cause A (1 of 2) and one for cause B (1 of 2).
- No `LockNotAvailable` failure.
- After P5, only text changed: the docs and traceability wording of round 4 note 2, the plan
  notes, this record, NOW.md and the questions file.
