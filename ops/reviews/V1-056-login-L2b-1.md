# V1-056 login sub-slice L2b-1 — the administration API contract and the runtime revoke — review record

Sub-slice L2b-1 of the login slice (L2b split into L2b-1, this record, and L2b-2, the PostgreSQL
flow, error mapping, object scopes and wiring; ops/V1_056_PLAN.md section 7.3). Migration
`20270125_182`. Base commit: cb5005b (the owner answers of 2026-10-22 to Q-2026-10-21-166 to 168,
recorded first, docs only). Built on 2026-10-22 in a fresh session. Not pushed. The commit hash
is in `git log` (this record is part of that commit).

## Owner answers recorded first (commit cb5005b)

Q-2026-10-21-166 (a): a route that removes a bundle from an account, Owner only, with a reason;
the docs/005 route approved. Q-167 (a): take away the runtime role's EXECUTE on the unaudited L1d
Settings access functions; the tightening and the one committed test change approved. Q-168 (a):
bundles stay fully configurable; the screen warns before an approval or money capability is added
to a bundle that Staff accounts hold (screen rebuild).

## Built

- Migration `20270125_182`: `REVOKE EXECUTE` on `app.give_settings_access(uuid,uuid,text)` and
  `app.remove_settings_access(uuid,uuid,text)` from `prm_runtime`; nothing else; forward-only.
  The audited `app.admin_*` definer functions keep working.
- `access_admin_api.py`:
  - `UserCreateRequest.account_class` (`manager` or `staff`) replaces `mfa_policy_class`
    (Q-152 (a)); the flow's `create_user` takes the class.
  - `UserAccountView` and `UserAccountData` gain `account_class` (nullable) and
    `settings_access`.
  - New routes `POST /users/{user_id}/settings-access`, `.../settings-access/remove` and
    `POST /users/{user_id}/role-assignments/remove`: actor, `identity.manage_access`, exact
    Origin and CSRF, object scopes (account; bundle for the removal), Property, a reason; a bundle
    of another Property is refused (409) before the flow; results must match the request.
  - The flow protocol and the unavailable flow gain the three methods.
  - `BoundedReason` (review rounds 1 and 2): 1 to 500 characters after trimming; refuses control
    characters, U+2028, U+2029 and direction marks, and a reason with nothing visible; keeps
    U+200B to U+200D for Khmer text.
  - Fail closed (review round 1): a created account of another class or MFA policy, and a
    Settings access result that does not show the change (503).
- Frontend: `adminClient.ts` reads `account_class` and `settings_access` and creates an account
  by its class; the `App.tsx` account form asks for the account class instead of the MFA policy.
- Tests: 5 new unit tests in `test_access_admin_api.py`; PostgreSQL module
  `test_settings_access_runtime_revoke_migration.py` (2 tests, last in `scripts/database-test.sh`);
  `adminClient.test.ts` TEST-FE-ADMIN-005 (the client test file is outside the traceability
  manifest's frontend scope, like TEST-FE-ADMIN-001 to 004). Traceability: 7 entries appended,
  one L1d note changed.
- Docs: docs/004 DB-AUTH-008 note; docs/005 API-079 and API-080 notes; docs/010 DL-081 (owner
  answers, L2b-1 and "Updated tests" lines); plan section 7.3 (split, pre-code design, as-built
  bullets).

## Committed tests changed

- The 27 head-revision strings (`20270124_181` to `20270125_182`) in 15 modules; nothing else.
- `test_settings_access_migration.py::test_the_runtime_role_reaches_settings_access_only_through_its_functions`:
  the runtime role's calls of the two L1d functions expect "permission denied" instead of the
  Owner refusal (same exception type; Q-167 (a), approved by the owner). Its traceability note
  changed with it (review round 2).
- `test_access_admin_api.py` (owner answers Q-152 (a), Q-158 (a), Q-166 (a)): the fake flow takes
  `account_class`, builds accounts with the two new fields and records the three new calls; the
  create payloads send `account_class`; the OpenAPI test lists the three new operations and
  expects `account_class`; the account list check expects the two new fields. Only
  `mfa_policy_class` to `account_class` swaps were removed.
- `test_initial_owner_bootstrap_cli.py::test_fastapi_openapi_inventory_has_no_bootstrap_or_unauthenticated_owner_reset_route`:
  the three new routes added to its exact inventory (Q-158 (a), Q-166 (a); found by U1).
- Frontend fixtures in `adminClient.test.ts` and `App.test.tsx` gain the two fields.
- Reviewers of rounds 1 to 3 compared these with HEAD and found nothing weaker.

## Read-only search for affected tests

- Callers of the two revoked functions: only `test_settings_access_migration.py` (the runtime-role
  test; its other calls use the migration owner) and `test_settings_access_sign_in_code_migration.py`
  (migration owner, and a catalog pinned to revision 180 on a throwaway database).
- Tests that list function privileges at head: none names the two functions; the L1d, L1e and L2a
  least-privilege tests compare catalogs at their own revisions on throwaway databases.
- No new foreign key, truncate list or trigger. Missed: the unit route inventory test (cause A).

## Reviews

- Round 1 (two fresh agents): independent, no blocker, one should-fix (check the returned Settings
  access and class); security, no blocker, three should-fix (the same two result checks; the
  reason's character rule). All done, with tests. Notes taken: mismatch tests for another Property,
  bundle and missing account; a null-class frontend case.
- Round 2 (one fresh agent, both checklists): no blocker; three should-fix (two text: the stale L1d
  traceability note and the unnamed route inventory change; one refusal: a reason with nothing
  visible). All done. Notes taken: more character examples, a 503 case for an assignment of
  another Property, carry-over notes for L2b-2 (result checks before commit; an owner question on
  the invisible characters still accepted), L4 (the recovery reason) and the screen rebuild.
- Round 3 (one fresh agent, both checklists; after U5 and P3): no blocker, no should-fix. Notes
  taken as text: docs/005 names the reason's character rule; U+00AD and U+180E added to the list
  for the L2b-2 question.

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-login-L2b-1-`)

| Run | Result | Cause |
|---|---|---|
| FF1 (one file reformatted), I1, FC1, L1, Y1 | pass | backend checks |
| FFE1, FCE1, LE1, YE1 | pass | frontend checks |
| UE1 | 1,601 passed | frontend tests |
| U1 | 3,878 passed, 2 failed | cause A (1 of 2): the route inventory test lacked the three new routes; cause B (1 of 2): the traceability entry for TEST-FE-ADMIN-005 is outside the manifest's frontend scope |
| FF2, I2, FC2, L2, Y2 | pass | after the cause A and B fixes (manifest rebuilt from HEAD and appended again) |
| U2 | 3,880 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 491 passed | targeted: the 15 head-revision modules and the two Settings access modules |
| B1 | pass | frontend build |
| M2 | pass | migration-only check |
| P1 | 2,501 passed | full PostgreSQL run |
| FF3, I3, FC3, L3, Y3 | pass | after the round 1 fixes |
| FFE2, FCE2, LE2, YE2 | pass | frontend checks after the round 1 fixes |
| UE2 | 1,601 passed | frontend tests |
| U3 | 3,880 passed, 1 failed | cause C (1 of 2): a new reason test case put U+2028 at the end, where trimming removes it |
| FF4, I4, FC4, L4, Y4 | pass | after the cause C fix |
| U4 | 3,881 passed | unit suite |
| M3 | pass | migration-only check |
| P2 | 2,501 passed | full PostgreSQL run |
| FF5, I5, FC5, L5, Y5 | pass | after the round 2 fixes |
| U5 | 3,881 passed | unit suite (before round 3) |
| M4 | pass | migration-only check |
| P3 | 2,501 passed | full PostgreSQL run (before round 3) |

- One correction each for causes A, B and C (each 1 of 2).
- No `LockNotAvailable` failure. P2 and P3 show the known pydantic `UnsupportedFieldAttributeWarning`
  of the unchanged `test_credit_refund_api_migration.py`, as in L1c and L2a.
- After P3, only text changed: docs/005, the plan, this record and NOW.md.
- Still pending (not touched): the test rename in `test_deposit_receipt_refund_out_migration.py`.
