# V1-056 login sub-slice L1c — default role bundles — review record

Sub-slice L1c of the login slice (ops/V1_056_PLAN.md section 7.3). Migration `20270122_179`.
Base commit: 88d5bfd (the owner answers of 2026-10-21 recorded first, docs only: Q-2026-10-21-164
(a) and the new rule "Settings access needs the sign-in code"). Built on 2026-10-21 in a fresh
session. Not pushed. The commit hash is in `git log` (this record is part of that commit).

## Built

- `app.default_role_bundles` (append-only): one row per Property naming its default Owner,
  Manager and Staff bundles (each a bundle of that Property, all different), with time and
  provenance. UPDATE, DELETE and TRUNCATE are refused by the L1b-2 function
  `app.reject_role_bundle_history_change()`, so a `TRUNCATE app.role_bundles CASCADE` keeps its
  message.
- Definer `app.seed_default_role_bundles(property)` (`search_path=pg_catalog`): READ COMMITTED
  only (55000), per-Property advisory lock, unknown Property refused (22023); a Property that
  already has its defaults gets their ids back and nothing changes; otherwise it creates "Owner"
  and "Manager" (every catalog capability with grant path `bundle`, 72 today) and "Staff" (the
  31 of Q-150 (a) with G7), all at version 1, records them, and assigns the Owner bundle to the
  Owner-class account if one exists (seed assignment).
- The migration seeds the Property that already exists (a fresh database has none).
- `prm_runtime` may execute the seed function only; PUBLIC revoked on the function and table.
- `access_control.py`: `STAFF_DEFAULT_BUNDLE_CAPABILITIES` (the 31). The three bundle-name
  constants of the pre-code design were not added (nothing in the code needs them yet); recorded
  in the plan and DL-081.
- `property.py`: `PostgresPropertyConfigurationRepository.add` (the path of
  `property_setup_cli.py`) checks the initialized row and calls the seed in the same transaction
  as `app.initialize_property`.
- Tests: unit `test_access_control.py::test_the_default_staff_bundle_holds_exactly_the_approved_daily_work`;
  PostgreSQL `test_default_role_bundles_migration.py` (7 tests, last in `scripts/database-test.sh`).
  Traceability: 8 entries appended. Head-revision strings: 27 in 15 modules.
- Docs: docs/004 DB-AUTH-009 and the matrix row, docs/005 API-080 note, docs/008 SEC-021 note,
  docs/010 DL-081 (Q-164 answer, L1c lines), plan section 7.3 (pre-code design, as-built bullet,
  L3a ordering rule, L5 test line).

## Implementer's readings (confirmed by both round 1 reviewers as needed and safe)

1. The plan said `property_setup_cli.py` calls the seed; the call sits in the repository's `add`,
   which holds that command's transaction, so a failed seed rolls back the new Property.
2. The seed assigns the Owner bundle to the Owner-class account: the bootstrapped Owner exists
   before the Property (`created_by` must be an existing account), and DL-074 answer 1 ("Owner:
   every capability") needs a bundle; Manager and Staff get their bundle at creation in L2.

## Read-only search for affected tests

- Committed tests that TRUNCATE the referenced tables: only `TRUNCATE app.role_bundles CASCADE`
  in `test_role_bundle_migration.py` reaches the new table; same message.
- No committed test calls the Postgres Property repository's `add`; the tests that call
  `app.initialize_property` directly are not seeded.
- No head-wide function or grant lists (the earlier catalog tests are revision-specific).

## Committed tests changed

- The 27 head-revision strings (`20270121_178` to `20270122_179`) in 15 modules; nothing else.

## Review round 1 (two fresh agents)

Independent: no blocker. SF1: the "same transaction" claim and the moved `except` path were not
proven (the service refuses a second Property before `add`). Done: set-up (throwaway database at
179; commit an Owner; call `configure_postgres_property` with the runtime URL plus
`options=-c default_transaction_isolation=serializable`; expect 55000 "default role bundles are
seeded only at READ COMMITTED"; assert zero rows in `app.properties`, `app.role_bundles`,
`app.default_role_bundles`, `app.user_role_assignments`; then a normal setup; then
`PostgresPropertyConfigurationRepository(runtime_url, owner).add(...)` refused with
`PropertyAlreadyConfiguredError`). Notes taken: race test wording; precondition that the shared
database holds no defaults; dropped bundle-name constants recorded; no audit event recorded;
for L2, an Owner seeded without an Owner class assigns the recorded Owner bundle to itself.

Security: no blocker. SF1: Owner and Manager bundles hold `service_rates.manage` and
`utility_rates.manage` while the rate routes check them until L5. Done: no code change (owner
answer: every bundle capability); ordering rule recorded. SF2: the result check ran after the
commit. Done: checked before the commit (test as above). SF3: no test of re-seeding after the
Owner removed or renamed bundles. Done: set-up (seed; insert a removal of the Owner's seed
assignment; `next_version(owner_bundle, its capabilities, "Proprietor")`; seed again; same ids,
3 seeded bundles, one Owner assignment row, Owner grants only `identity.manage_access` and
`settings.manage`). Notes: runtime can call `app.initialize_property` without the seed (fails
closed); no Owner at seed time; the migration's Staff list format (taken: an assert); seed
writes no audit event.

## Review round 2 (one fresh agent, both checklists)

No blocker. One should-fix (text): the ordering rule had to cover the three settings that
Q-151 (a) moves from `property.manage` to `settings.manage` (Property update, Property
configuration, due-days setting) and be written into the L3a and L5 sections. Done: plan L1c
as-built note, new L3a "Ordering rule" bullet, new L5 "Tests" bullet (set-up: throwaway
database, Owner bootstrapped, Property set up through `configure_postgres_property`, a Manager
with the recorded Manager bundle and a Staff account given `settings.manage` after its sign-in
code (L1e), all signed in; the Manager gets 403 on the five settings changes and nothing
changes; after the Owner gives the Manager `settings.manage` all five succeed; the Owner
succeeds with no grant; the Manager still creates and updates a Unit), DL-081 ordering note.
Notes kept: the migration's bare `assert` is removed under `python -O`; L2 should refuse clearly
when a Property has no default record; a bundle named owner, manager or staff on an older
database makes the migration fail loudly.

## Review round 3 (one fresh agent, both checklists)

Before it: full unit run U2 and full PostgreSQL run P2 (only text changed after them). No
blocker, no should-fix. Notes kept: the `STAFF_NEVER` comment in the unit test also holds
`property.manage`, which DL-081 does not list as "never" (Staff lack it because it is not on the
approved list); this record (written now); an `alembic upgrade` run at REPEATABLE READ or
SERIALIZABLE with a Property present refuses (fails safe); the seed's returned ids are not
checked in `property.py` (a failure raises and rolls back).

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-login-L1c-`)

| Run | Result | Cause |
|---|---|---|
| FF1 (two files reformatted), I1, FC1, L1, Y1 | pass | backend checks |
| U1 | 3,876 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 498 passed | targeted: the 15 head-revision modules, the role bundle module and the new module |
| P1 | 2,479 passed | full PostgreSQL run (one extra pydantic `UnsupportedFieldAttributeWarning` in the unchanged `test_credit_refund_api_migration.py`; not in P2) |
| FF2, I2, FC2, L2, Y2 | pass | after the round 1 fixes |
| M2 | pass | migration-only check |
| T2 | 16 passed | targeted: the role bundle module and the new module |
| U2 | 3,876 passed | unit suite |
| P2 | 2,479 passed | full PostgreSQL run |

- No check or run failed; no correction used.
- No `LockNotAvailable` failure.
- After P2, only text changed: plan, DL-081, this record and NOW.md.
