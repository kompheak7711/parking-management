# V1-056 login sub-slice L1a — the account class — review record

Sub-slice: L1a of the login slice (ops/V1_056_PLAN.md section 7.3). Migration `20270118_175`.
Base commit: 0ec4ecb (the owner's approval and answers, recorded first, docs only). Built on
2026-10-21 in a fresh session. Not pushed. The commit hash is in `git log` (this record is part of
that commit).

## Owner answers recorded first

Commit 0ec4ecb: the owner approved the login slice plan of 2aabe67 and answered Q-2026-10-21-150
to 160 with (a), with notes; recorded in docs/010 DL-081, ops/V1_056_QUESTIONS.md and plan
section 7. The pending rename in `test_deposit_receipt_refund_out_migration.py` stays pending (that
file is not touched here).

## Built

- `app.user_account_classes` (new, append-only): `actor_id` (key; foreign key to
  `app.user_accounts`, ON UPDATE and ON DELETE RESTRICT), `account_class` (`owner`, `manager`,
  `staff`), `classified_at`, non-blank `provenance`. Partial unique index
  `user_account_classes_single_owner` (at most one `owner`).
- `app.reject_user_account_class_change()`: BEFORE UPDATE OR DELETE (row) and BEFORE TRUNCATE
  refuse (23000, "user account class is immutable").
- `app.require_user_account_class_mfa()`: BEFORE INSERT; an `owner` or `manager` class needs the
  account's `mfa_policy_class` `required`, read with a share lock on the account row (23514, "an
  Owner or Manager account requires MFA").
- `app.reject_privileged_account_optional_mfa()`: AFTER UPDATE on `app.user_accounts` for each row
  whose new MFA policy is not `required`: an MFA policy is lowered only at READ COMMITTED (55000,
  "an MFA policy can be lowered only at READ COMMITTED"), and an `owner` or `manager` account's
  MFA cannot stop being required (23514).
- The three trigger functions are not definers, have `search_path=pg_catalog` and no EXECUTE for
  PUBLIC. `prm_runtime` gets SELECT on the new relation only.
- Backfill: one `owner` row for the bootstrap closure's actor (`login-slice-account-class-backfill`);
  no row or column of `app.user_accounts` changes.
- `app.establish_initial_owner_bootstrap`: one exact-text change inserts the `owner` class right
  after the account row (same signature, owner, ACL, definer flag and settings).
- `local_authentication.py`: `PostgresLocalAccountRepository.find_by_username` joins the class, so
  an unclassified account cannot be found for sign-in (the dummy verifier still runs).
- `account_recovery.py`: new `PostgresRecoveryAccountResolver` (the stored class of an active,
  classified account; otherwise None); the authorizer docstring updated.

## Design changes (under the design-change run rule; confirmed by the round 1 independent reviewer)

1. No check that every new account carries a class: about 100 committed test set-ups in 14 modules
   insert `app.user_accounts` rows without a class as the migration owner. Fail closed instead (no
   sign-in, no recovery, no grants from L1b; no application role can give a class).
2. A separate relation instead of the planned `account_class` column: `ALTER TABLE
   app.user_accounts ADD COLUMN` (and `ADD CONSTRAINT`) need ACCESS EXCLUSIVE and deadlocked the
   committed whole-chain upgrade test
   `test_migrations.py::test_v1_042_upgrade_front_door_gate_prevents_service_writer_deadlock`
   (run T1, cause B). `CREATE TABLE ... REFERENCES` and `CREATE TRIGGER` take SHARE ROW EXCLUSIVE,
   which does not conflict with readers or foreign-key checks. DB-AUTH-001 already keeps
   assignments in separate relations.

## Committed tests changed

- The 27 head-revision strings in 15 modules (revision strings only; a script checked each file's
  count; `test_settlement_preview_credit_step_wait_migration.py` keeps its own `REVISION`).
- `test_local_authentication.py::test_repository_normalizes_username_through_local_account_persistence`
  also asserts the class join (stricter; asked by the round 1 independent reviewer).
- A first change to `test_migrations.py::test_user_accounts_storage_has_bounded_identity_and_policy_columns`
  (the planned column) was reverted with design change 2; that test is unchanged.

## New tests

Module `test_account_class_migration.py` (last in `scripts/database-test.sh`), 12 functions, 14
cases: `test_an_account_class_is_owner_manager_staff_or_not_given`,
`test_owner_and_manager_accounts_require_mfa`,
`test_a_class_and_an_mfa_change_at_the_same_time_wait_for_each_other` (round 1),
`test_an_mfa_policy_is_lowered_only_at_read_committed` (round 1; REPEATABLE READ and SERIALIZABLE),
`test_a_class_given_from_a_snapshot_older_than_an_mfa_change_fails` (round 2 note; both levels),
`test_at_most_one_owner_account_exists`, `test_a_class_once_given_never_changes_or_goes_away`,
`test_the_bootstrapped_owner_has_class_owner_and_no_second_owner_can_be_added`,
`test_the_migration_classes_only_the_bootstrapped_owner` (round 1: the closed bootstrap stays
closed), `test_the_recovery_resolver_reads_only_the_stored_class_of_an_active_account`,
`test_an_account_without_a_class_cannot_be_found_for_sign_in`,
`test_the_account_class_migration_is_least_privilege_and_forward_only`. Traceability: 12 entries
appended; the earlier entries are untouched. Committed rows on the shared test database: Manager,
Staff, disabled and unclassified accounts only (no Owner; Owner tests roll back or use throwaway
databases).

## Reviews

Round 1 (two fresh read-only agents):
- Independent: no blocker. Should-fix 1, no race test (built: both orders at READ COMMITTED with a
  lock timeout; set-up: commit an account with MFA `required`; B lowers MFA uncommitted, A with
  `lock_timeout='200ms'` inserts a Manager class and gets `LockNotAvailable`, B commits, A again
  gets 23514; then A inserts a Manager class uncommitted, B's MFA lowering times out, A commits, B
  again gets 23514). Should-fix 2, the closed bootstrap after the upgrade (built in the backfill
  test). Notes taken: AFTER trigger and READ COMMITTED (with the security fix), the sign-in unit
  assertion, the recovery docstring, docs/004 wording, stale plan text. Note 2 (a closure check
  requiring an Owner class) not built: committed closure tests in `test_migrations.py` call
  `app.attempt_initial_owner_bootstrap_closure` for accounts without a class; instead an L7
  runbook rule. Notes kept for later: L2 refuses `owner` at create and records who gave a class
  (SEC-075); L4 decides a class check in `app.perform_account_recovery`; L1b, L2 and L3a keep the
  invariant that every authority path joins the class. Both design changes confirmed as needed
  and safe.
- Security: no blocker. Should-fix S1, under REPEATABLE READ an MFA lowering could miss a Manager
  class committed after its snapshot (built: the READ COMMITTED refusal; set-up: commit an
  account with MFA `required`; A starts REPEATABLE READ and reads; B (autocommit) gives the
  Manager class; A lowers the MFA and gets 55000). Notes as above (N1 AFTER trigger taken; N2 to N4
  and N7 kept for L2, L3 and L4; N5 lock levels; N6 committed test rows).

Round 2 (one fresh read-only agent with both checklists): no blocker, no should-fix. Notes taken:
the share-lock comment reworded, with a new test (set-up: commit an account with MFA `required`;
A starts REPEATABLE READ or SERIALIZABLE and reads; B (autocommit) lowers the MFA; A gives the
Manager class and gets 40001); L7 runbook lines (the backfill refuses if the closure's actor no
longer requires MFA; a bootstrap closed without an Owner class needs a reviewed forward
migration); stale plan Tests line marked. Notes kept: READ UNCOMMITTED is refused too (fail
closed); ad-hoc runs on a long-lived database upgraded from 174 with a committed test closure.

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-login-L1a-`)

| Run | Result | Cause |
|---|---|---|
| FF1, I1, FC1, L1 | pass | backend checks |
| Y1 | fail | cause A (1 of 2): psycopg connections passed to the repository protocols without `cast` |
| FF2, I2, FC2, L2, Y2 | pass | after the cause A fix |
| U1 | 3,871 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 145 passed, 2 failed | cause B (1 of 2): the V1-042 whole-chain upgrade test deadlocked on the column design; cause C (1 of 2): the new least-privilege test read the wrong catalog field |
| FF3, I3, FC3, L3, Y3 | pass | after the redesign (design change 2) and the cause C fix |
| M2 | pass | migration-only check |
| T2 | 147 passed | targeted: test_migrations.py, the 15 head-revision tests, the new module |
| U2 | 3,871 passed | unit suite |
| M3 | pass | migration-only check |
| P1 | 2,447 passed | full PostgreSQL run |
| FF4 (one file reformatted), I4, FC4, L4, Y4 | pass | after the round 1 fixes |
| M4 | pass | migration-only check |
| T3 | 13 passed | targeted: the deadlock test and the new module |
| U3 | 3,871 passed | unit suite |
| P2 | 2,450 passed | full PostgreSQL run |
| FF5, I5, FC5, L5, Y5 | pass | after the round 2 notes |
| M5 | pass | migration-only check |
| T4 | 14 passed | targeted: the new module |
| U4 | 3,871 passed | unit suite |
| P3 | 2,451 passed, 1 failed | full PostgreSQL run; the one failure is the known DL-067 `LockNotAvailable` (55P03, `could not obtain lock` on `invoice_lines`, the NOWAIT lock) in `test_deposit_receipt_record_migration.py::test_a_payment_confirmed_for_an_owed_invoice_is_not_a_deposit_receipt`, a module this sub-slice does not change |
| R1 | 1 passed | the rerun-once of that test under the standing `LockNotAvailable` rule |

Three corrections, one per cause (A, B, C; each 1 of 2). One known `LockNotAvailable` failure (P3), passed on its one rerun (R1); its test is added to the slice 12 root-cause item. Process
slip: the first append of DL-081 (in the answers commit's working tree) used a shell redirect,
which the run rules forbid; it was undone with `git checkout` of that file and appended again by a
script before commit 0ec4ecb.
