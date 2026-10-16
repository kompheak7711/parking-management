# V1-056 sub-slice 10c-2a-7 — a pet classification correction of a line billed from an inspection superseded before closure — review record

Sub-slice: 10c-2a-7 (owner answers (a) to Q-2026-10-08-53, Q-2026-10-11-80 and Q-2026-10-11-85).
Migration `20261216_142` (a relaxing change). Base commit: 9dc446f. Built on 2026-10-16. Not
pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-008, BR-MOVEOUT-006, DL-032; DB-SETTLE-007, DB-SETTLE-005.
Design: ops/V1_056_PLAN.md, "10c-2a-7 pre-code note" and its as-built line. Question raised:
Q-2026-10-16-116 (blocks nothing). The same commit records the owner answer (a) to
Q-2026-10-16-115 (docs/010, the questions file, docs/004 known behaviour, the plan's slice 12
item).

## Built

- Migration `20261216_142_settlement_pet_classification_superseded.py`: exact-text patches, each
  anchor checked to appear once, of `app.settlement_pet_classification_line` (its `NOT EXISTS`
  clause on a superseding inspection dropped, with a comment) and of the refusal message of
  `app.settlement_pet_classification_plan` ("... billed from a finding of a move-out inspection of
  this Lease", 55000 as before). Catalog dump D1 showed both bodies equal the migration 105 text.
- Committed test changed (owner answers (a) to Q-80 and Q-85; standing rules of 2026-10-11 and
  2026-10-14): `test_a_line_billed_from_an_inspection_superseded_before_closure_is_not_eligible`
  renamed `test_a_line_billed_from_an_inspection_superseded_before_closure_takes_the_change_to_pet_damage`;
  setup kept (hand closure); its refused draft is now the change to not pet damage (55000
  `ALREADY`, no draft); then the to-pet correction with the full DL-032 steps, checked to the
  cent. The message constant `NOT_ELIGIBLE` follows the new text (its Rent-line case, the
  expectation only). The `approver` import added.
- New module `test_settlement_pet_classification_superseded_migration.py` (last in
  `scripts/database-test.sh`): (a) no Pet Deposit money, only the record (evidence naming the new
  inspection's pet finding), the change to not pet damage refused on the fresh line, a later
  correction back passing (Q-116); (b) after a return-only correction of 2,000 of the Pet Deposit
  Refund, the Security Deposit application reversed, Pet Deposit 2,000 first, Security 8,000, its
  rest 2,000 refunded, the remaining Pet Deposit application kept; (c) least privilege and
  forward-only.
- 27 head-revision assertions in 15 modules moved to `20261216_142` (script, count per file
  checked). Traceability: the renamed entry (index 2821) updated in place; three entries appended.
- Docs: docs/004 DB-SETTLE-007 (table row, insert-check text, an "As built" paragraph), docs/010
  (as built, updated tests, this round's runs), the plan, Q-2026-10-16-116.

Read-only search for affected tests: only migration 105 and 142 name the two functions; only
`test_settlement_pet_classification_migration.py` asserts the old message or a superseded-line
correction; the other modules that use `PET_DAMAGE_RECLASSIFICATION` use lines of current
inspections.

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump of the two functions (no `REDACTED` marker) |
| FF1/FC1/L1/Y1 | backend format (formatter first, no change), format check, lint, type check passed; the long-line search before the lint found one line in the test and it was wrapped by hand |
| M1 | passed (`20261216_142` head) |
| T1 | 14 passed (the two pet classification modules) |
| U1 | 3804 passed |
| M2 | passed |
| P1 | 2204 passed (warnings: the known Starlette deprecation and two Pydantic alias warnings of the unchanged Credit Refund API tests) |
| FF2/FC2/L2/Y2 | passed (after the round 1 fixes; formatter first, no change) |
| T2 | 14 passed (after the last test change) |
| U2 | 3804 passed |
| M3 | passed |
| P2 | 2204 passed (warnings: the known Starlette deprecation and one Pydantic alias warning of the unchanged Credit Refund API tests) |

No check or run failed, so no correction. After P2 only text changed (this record, docs/010, the
plan, ops/NOW.md).

## Review round 1 (fresh read-only subagents, during P1; told to write no file and run no test, script or database command)

Independent: 0 blockers, 1 should-fix, 4 notes. Security: 0 blockers, 1 should-fix (text), notes.

- Independent should-fix S1: the new test shows a correction back to not pet damage after a to-pet
  record (the latest-record rule of 10c-2a-5; no new code), which no owner answer states in words.
  Handled by writing Q-2026-10-16-116 (recommendation (a), keep) and naming it in docs/004 and
  docs/010; no code change.
- Security should-fix: docs/004 DB-SETTLE-007 still said "a current inspection", and docs/010 had
  no "Updated tests" entry (the docs entries were planned after the run). Fixed after P1.
- Independent notes taken: N1 the migration docstring's rule ids (BR-DEP-022 out, BR-SETTLE-008
  and DB-SETTLE-005 in); N2 test (b) reads the classification row back. Not taken: N3 a direct
  insert-trigger test of a to-not-pet record on a fresh superseded line (optional; the trigger uses
  the same two functions); N4 the temporary database name is cut to 63 characters (harmless, as in
  committed modules).
- Security findings: privileges, owner, definer and search path kept by CREATE OR REPLACE from
  the catalog; no grant change; no Staff-only money path (the recorder writes only a draft, the
  confirm needs a human `financial.approve`, the insert check binds the record to its own draft
  and correction); no line of another Lease, non-Damage line or VOID Invoice passes; no supersede
  after closure (migration 104, command and trigger, READ COMMITTED only); no injection; no secret
  or database URL in the tests. Notes: no pet classification test of a VOID Invoice line (gap from
  105, enforced in code); the least-privilege test checks the application roles and PUBLIC, not
  the login roles (covered by the PUBLIC and unchanged-ACL checks).
- The independent reviewer compared the changed committed module with HEAD: only the `approver`
  import, the `NOT_ELIGIBLE` text and the renamed test changed; the refused case still checks that
  no draft is written; nothing removed or weakened.

## Review round 2 (fresh read-only subagents, during U2 and P2; same limits)

Independent: clean (0 blockers, 0 should-fix, 4 optional notes). Security: clean (0 blockers, 0
should-fix, 2 notes).

- Independent: the S1 handling is acceptable (no new code; option (b) would be a tightening; the
  plan's pre-code check of 2026-10-11 named the behaviour before the owner answered Q-85); the
  round 1 fixes are real; the committed module compared with HEAD again, nothing weaker;
  traceability append-only beyond the first 1,598 entries.
- Notes taken (text): this record written before the commit (both reviewers); the plan points to
  Q-116.
- Notes kept (tests only, optional; not taken, so that no test file changes after P2; slice 12
  list): the new module's docstring could say "only the change to pet damage on a fresh line";
  test (a)'s correction back could also check `effect_links` and the held values; N3 of round 1.
- Security: Q-116 has no security angle (the same recorder under `final_settlements.prepare`, the
  same human `financial.approve` confirm, the same insert check; its money effect is the existing
  10c-2a-5 rule).
