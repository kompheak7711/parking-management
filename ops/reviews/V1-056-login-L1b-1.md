# V1-056 login sub-slice L1b-1 — the capability catalog — review record

Sub-slice: L1b-1 (the first half of L1b, split by the implementer as the owner's instruction of
2026-10-21 allows). Migration `20270119_176`. Base commit: c73a784 (the questions commit after
L1a a902e56). The work stopped after review round 1 for the owner's answers to Q-2026-10-21-161
((a): `billing.generate` is a bundle capability, Owner and Manager bundles, not Staff) and
Q-2026-10-21-162 ((b): `identity.manage_access` only from the Owner account class, never in a
bundle), given the same day and recorded in ops/V1_056_QUESTIONS.md, docs/010 DL-081 and plan
section 7 (commit of this sub-slice). Not pushed. The commit hash is in `git log`.

## Built

- `app.capabilities` (append-only: UPDATE, DELETE, TRUNCATE refused, 23000), 75 rows: the 70
  capabilities the application checks, `rent_nonpayment.evaluate` (checked only by the database)
  and the four approved names `settings.manage`, `operations.status.read`, `property.read`,
  `units.read`. Each row has one `grant_path`: `per_user` (`settings.manage`), `owner_class`
  (`identity.manage_access`), `service_principal` (`rent_nonpayment.evaluate`), `bundle` (the
  other 72, `billing.generate` included, described "Start a Rent or Utility billing run and read
  its status"); `UNIQUE (capability_id, grant_path)`; names at most 128 characters in the
  lower-case dotted form with their family; a finite `added_at`. `prm_runtime` reads only.
- `backend/src/property_rental/access_control.py` (`CAPABILITY_CATALOG`, the three grant path
  sets, `capability_grant_path`, `BUNDLE_CAPABILITIES`, constants for the new names and
  `identity.manage_access`).
- Tests: `test_access_control.py` (3 unit), `test_capability_catalog_migration.py` (4 DB, last in
  `scripts/database-test.sh`); traceability 7 entries appended; head-revision strings 27 in 15
  modules; docs/004 DB-AUTH-006 and the authentication table row, docs/008 SEC-021 note, docs/010
  DL-081 (the two answers and the L1b-1 lines), plan section 7 (the rows the answers change, the
  L1b split and the L1b-1 pre-code design).

## Review round 1

Independent: no blocker.
- SHOULD-FIX 1: `billing.generate` is a human capability today (API-054, API-055 billing-run routes
  and the run status read in `billing_run_api.py` and `billing_run.py`; shown in `invoice_api.py`);
  "never in a bundle" would leave nobody able to start a billing run after L5, and the description
  "(billing service principal only)" would be wrong for good. Owner question Q-2026-10-21-161.
- SHOULD-FIX 2: the unit test skips `access_control.py`; fix: also check that each dotted constant
  there is a catalog key (keep the count and unused-label checks on the other files).
- SHOULD-FIX 3: traceability entries cite DB-AUTH-001 instead of the new DB-AUTH-006; fix the
  appended entries only.
- Notes: the scan sees only literal constants in top-level files (fails closed; consider an AST
  check that capability arguments are names or constants, or have the L1b-2 grant reader refuse
  non-catalog names); `added_at` has no finite check and `capability_id` no length limit (API
  allows 128); descriptions can never be corrected (stale wording of `property.manage`,
  `service_rates.manage`, `utility_rates.manage` after L5); docs/004 and docs/008 wording
  overstates what the test and L1b-1 enforce; weak traceability links (TEST-086, SEC-014); SEC-020
  not cited in DL-081; `CapabilityView.name` has no catalog column (L2); the new-names test must
  change when L1d and L5 use them.

Security: no blocker.
- SHOULD-FIX S1: one boolean mixes "service principal only" and "per user only"; fix (a): a
  `grant_path` column (`bundle`, `per_user`, `service_principal`; `owner_class` too if Q-162 (b))
  with a check that `assignable_by_bundle = (grant_path = 'bundle')`.
- Notes: add `UNIQUE (capability_id, grant_path)` for an L1b-2 composite foreign key from bundle
  capabilities; `identity.manage_access` in bundles allows self-escalation (owner question
  Q-2026-10-21-162); API-080 shows the service capabilities (L2 hides or refuses them); use
  `fullmatch` in the unit test; a DB-AUTH-006 line that new catalog rows need a security review;
  `added_at`/`provenance` are owner-set; generic 23000 error code.

## Round 1 fixes (made with the owner's answers; all done)

As built, the boolean `assignable_by_bundle` was dropped instead of kept with a check, because
the grant path says the same thing once (a bundle capability is `grant_path = 'bundle'`).

1. `grant_path` column with its check and `UNIQUE (capability_id, grant_path)`; values per the
   answers (recommended: `billing.generate` `bundle` (Q-161 (a)), `identity.manage_access`
   `owner_class` (Q-162 (b)), `settings.manage` `per_user`, `rent_nonpayment.evaluate`
   `service_principal`); `billing.generate` description per the answer.
2. `access_control.py`: grant paths instead of `NOT_ASSIGNABLE_BY_BUNDLE`.
3. Unit test: also check `access_control.py` constants; `fullmatch`.
4. `capability_id` length at most 128; `isfinite(added_at)`.
5. Traceability: DB-AUTH-006 in the appended entries; drop the weak TEST-086 and SEC-014 links.
6. Docs: DB-AUTH-006 and SEC-021 wording (what the test proves; bundles enforced from L1b-2; new
   rows need a security review); DL-081 cites SEC-020; plan L1b-1 design updated.

Round 2 (one fresh agent with both checklists): no blocker. SHOULD-FIX 1: plan section 7.3 L1b
text still described the replaced flag (fixed: the Builds and Tests lines and the L1b-1 design's
Code and Tests sentences). Notes taken: the unit test
`test_the_catalog_holds_the_approved_new_names_and_the_never_in_a_bundle_set` renamed
`test_the_catalog_holds_the_approved_new_names` (it no longer checks such a set; traceability
entry renamed with it); the three grant path sets checked for overlap; the source scan uses
`rglob`; the least-privilege test checks all six application roles (`prm_backup` reads through
`pg_read_all_data`, scripts/postgres-init.sh). Notes kept: owner-set `added_at` and
`provenance`; the generic 23000 code; descriptions never corrected; API-080 will list non-bundle
capabilities (L2 hides or refuses them).

Round 3 (one fresh agent with both checklists; before it, the full unit suite U3 and the full
PostgreSQL run P3): no blocker, no should-fix. Note kept (optional wording): the label kinds in
the plan and the unit test comments do not name "message-type", which DL-081 does.

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-login-L1b-1-`)

| Run | Result | Cause |
|---|---|---|
| FF1, I1, FC1, L1, Y1 | pass | backend checks |
| U1 | 3,873 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 25 passed, 2 failed | cause A (1 of 2): the test compared database `ORDER BY` with Python sorting (collation); cause B (1 of 2): test capability names had a digit, which the format check refuses |
| FF2 (one file reformatted), I2, FC2, L2, Y2 | pass | after the cause A and B fixes |
| T2 | 4 passed | targeted, the new module |
| P1 | 2,456 passed | full PostgreSQL run |
| FF3 (two files reformatted), I3, FC3, L3, Y3 | pass | after the round 1 fixes |
| U2 | 3,874 passed | unit suite |
| M2 | pass | migration-only check |
| T3 | 4 passed | targeted, the new module |
| P2 | 2,456 passed | full PostgreSQL run |
| FF4, I4, FC4, L4, Y4 | pass | after the round 2 fixes |
| T4 | 4 passed | targeted, the new module |
| U3 | 3,874 passed | unit suite (before round 3) |
| P3 | 2,456 passed | full PostgreSQL run (before round 3) |

Two corrections, one per cause (A, B; each 1 of 2). No `LockNotAvailable` failure. After P3 only
text changed (this record and NOW.md).
