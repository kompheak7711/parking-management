# V1-056 sub-slice 10d — FORFEITURE_REVERSAL after closure: review record

Sub-slice: 10d (migration `20261119_115`). Base commit: 4710bdf. Not committed (commit hash in
ops/NOW.md once committed).

Rule IDs: BR-SETTLE-013, BR-SETTLE-008, BR-SETTLE-016, BR-DEP-019, BR-DEP-022, BR-DEP-023,
BR-DEP-026, DL-032, BR-REFUND-014, BR-REFUND-015, BR-CREDIT-006, BR-AUTH-010; owner answer 4 to
Q-2026-10-06-36, answer 1 to Q-2026-10-06-37, answers 1 and 3 to Q-2026-10-07-41, answers 1 to 3
to Q-2026-10-07-42, Q-2026-10-05-24, Q-2026-10-10-69 answer 6, Q-2026-10-10-71. Design:
ops/V1_056_PLAN.md (10d entry, "10d pre-code design"; "10d as built").

## Owner answers given in this session (2026-10-10)

- The six answers to the 10c-3b-2 report (Q-2026-10-10-69; docs/010). Answer 4 led to
  Q-2026-10-10-70 (open, before 10h). Answer 5: the changed 10c-3b-1 test compared with 0139619,
  not weakened (10c-3b-2 record).
- Q-2026-10-10-71 (asked in the session before code): (1) the recipient rules on a kept Deposit
  are tested by refusals only; the positive agreed-Signer Refund test with a two-Signer fixture is
  a plan task before 10h; (2) refuse (55000) a reversal while another forfeiture of the same
  Deposit stays active.

## Built

- Migration `20261119_115` (new functions only; no committed function, table or trigger
  changes): recorder `app.record_settlement_forfeiture_reversal_draft` and confirm
  `app.confirm_settlement_forfeiture_reversal` (EXECUTE to `prm_financial` only); internal
  `app.settlement_forfeiture_reversal_input`, `_source_state`, `_plan`, `_result` (no role).
- Service: `RecordForfeitureReversalCorrectionCommand`,
  `SettlementCorrectionService.record_forfeiture_reversal` and `confirm_forfeiture_reversal`,
  `FORFEITURE_REVERSAL_CONFIRM_STALE_STATES`.
- Tests: new module `test_settlement_forfeiture_reversal_migration.py` (6 tests, last in
  `scripts/database-test.sh`); 3 unit tests (23 cases) in `test_settlement_correction.py`; the 27
  head-revision assertions in 15 modules move to `20261119_115`; 9 traceability entries.
- Docs: docs/004 (DB-DEP-008 and the DB-SETTLE-005 as-built paragraph), docs/010 (sub-slice entry,
  updated tests, owner answers), the plan (10d as built, 10h entry, tasks before 10h, slice 12).

## Read-only search of every backend test

- 27 head-revision assertions in 15 modules (26 in 14 modules and the 10c-2b-1 module's head
  assertion): only the expected revision changes.
- No other test lists the app functions, their grants or the correction variants at head; the
  whole-catalog checks name their own functions; every forward-only test upgrades only to its own
  revision. The new module qualifies a Pet Refund review and runs last, after
  `test_lease_migration.py` (slice 12 note of 8a-2).

## Runs

Static checks each in its own call. Migration-only check (throwaway copy of
`scripts/database-test.sh` running `alembic upgrade head`): 114 upgrades, head `20261119_115`.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T1 | PostgreSQL, targeted: the new module | 4 passed, 2 failed | first run | `V1-056-slice-10d-targeted-test-run.txt` |
| T2 | PostgreSQL, targeted: the new module | 6 passed | T1 causes A and B | `V1-056-slice-10d-targeted-test-run-2.txt` |
| U1 | backend unit, full (under `caffeinate -dims`) | 3702 passed, 1852 skipped, 1 warning (Starlette) | first unit run | `V1-056-slice-10d-unit-test-run.txt` |
| P1 | PostgreSQL, full (under `caffeinate -dims`) | 2015 passed, 2 warnings (Starlette; the known Pydantic alias warning, slice 12) | first full run | `V1-056-slice-10d-full-test-run.txt` |
| T3 | PostgreSQL, targeted: the new module | 6 passed | round-1 test fixes | `V1-056-slice-10d-targeted-test-run-3.txt` |

Failure and check causes (each correction 1 of 2):

- Lint cause L (before T1): one SQL string over 100 characters in the new test module.
- Type cause M (before T1): a `type: ignore` on the wrong line of a new unit test; replaced by an
  `Any` variable.
- T1 cause A (test fixture): Credit was recognized from a Payment while the Customer still owed
  4,600 ("Applicable obligations must be handled before excess disposition"); the test now pays
  the 4,600 first and then adds the debt with an `EXTRA_CHARGE`.
- T1 cause B (test code): the twice-forfeited case had no `disposition` key for the command
  helper.
- Type cause N (round-1 fixes): one name used for a UUID and an exception in the same test.

Secret check (owner run rule): T1, T2, U1 and P1 searched for database URLs with a password,
`password=` and 64-character hex strings; none found.

## Review round 1 (2026-10-10; fresh read-only subagents, independent and security; during P1)

Independent: 0 blockers, 1 should-fix, 8 notes. Security: 0 blockers, 1 should-fix, 3 notes. Both
traced the confirm (approver, isolation, replay, lock order, link before write, one function),
found no double count (the step checks the real state with an empty overlay), no grant beyond the
recorder and confirm, no dynamic SQL and no transaction id in any result.

- Independent SF1 (the Refund-method refusals and the one-method-and-note rule were untested):
  fixed (test 4: an inactive method at record, a step with another method and with another note,
  a method deactivated between record and confirm with the draft left pending).
- Security SF1 (the transaction-id rule untested on the new paths): fixed (test 1: the confirm
  result, its replay and the recorder's replay of the decided draft).
- Independent N2 (only the waiting-draft part of the digest was proven): fixed (test 5: a 6b
  confirm after the correction draft makes it stale, P5S02, pending, nothing written; it replaces
  the positive Security reversal there, which test 2 covers).
- Independent N3 (the other-active-forfeiture refusal answers P5S02 at the confirm): stated in the
  plan's as-built line and docs/010.
- Independent N4 (the not-a-Signer recipient was a random id): fixed (a real Customer who is not
  a Signer of the Lease).
- Independent N5 (the "nothing written" claim was measured late): fixed (COUNTS taken before each
  refusal group).
- Independent N6 (no pending forfeiture draft test): not buildable after closure (10c-2b-2a);
  stated in docs/010 and the plan.
- Independent N7 (the waiting-drafts filter cannot use the partial index): slice 12 item.
- Independent N8 and security N2 (the reversal is dated before its correction's decision; its
  audit shows the Deposit before the step): stated in docs/004 and docs/010 (choice (2)).
- Independent N9 (a service identity stops at P4506 before the human check): as in earlier
  variants; no change.
- Security N1 (the reversal row is labelled `deposits.correct` while nobody holds it): stated in
  docs/004 and docs/010 (choice (1)); naming `prepare_capability` in the audit evidence is a
  slice 12 item (it would change the new confirm only).
- Security N3 (race tests): a different-approver assertion added (test 1, 55000); a two-connection
  6b-against-10d test is a slice 12 item.

Fixes after round 1: tests (tests 1, 2, 4 and 5 of the new module), traceability
notes, docs. Static checks each in its own call: type check failed once (cause N), then lint,
format and type check clean. A full unit run and a full PostgreSQL run follow before round 2.

Migration-only check again before P2: 114 upgrades, head `20261119_115`. Read-only search
unchanged (only the new module's tests changed since P1).

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U2 | backend unit, full (under `caffeinate -dims`) | 3702 passed, 1852 skipped, 1 warning (Starlette) | round-1 fixes | `V1-056-slice-10d-unit-test-run-2.txt` |
| P2 | PostgreSQL, full (under `caffeinate -dims`) | 2015 passed, 2 warnings (Starlette; the known Pydantic alias warning) | round-1 test fixes changed a test file after P1 (owner run rule) | `V1-056-slice-10d-full-test-run-2.txt` |

Secret check of T3, U2 and P2: none found.

## Review round 2 (2026-10-10; fresh read-only subagents, independent and security; during P2)

Independent: 0 blockers, 1 should-fix, 4 notes. Security: 0 blockers, 0 should-fix, 2 notes.
Both accepted every round-1 answer; the independent reviewer confirmed that each round-1 test fix
fails without the code it targets, except the one below.

- Independent SF1 (the inactive-method assertion at record did not depend on the new check: its
  Refund step used the same method, so the shared plan check refused it the same way): fixed; the
  plan now has only the Deposit step and names the inactive method as the correction's (without
  the new check it is refused for leaving 5,400 unused). At the confirm the refusal comes from the
  recorder's check run again; the FOR SHARE loop is a lock against a race, proven by behaviour
  only.
- Independent N1 (docs/010 put the Refund-method locks before the stale checks; the migration
  comment said the reversal function locks the Deposit first): fixed (docs/010 text; the lock
  comment now says "as the 6b confirm" and that the methods are locked after the stale checks).
- Independent N2 (the not-a-Signer comment said "of the Property"): fixed (comment).
- Independent N3 (the stale-after-6b part of test 4 did not check that nothing was written):
  fixed (the counts are compared).
- Independent N4 (runs table and secret check incomplete): fixed above.
- Independent minor (owner answer 2 to Q-71 at the confirm): the confirm's 55000 branch is
  unreachable after closure; the digest answers P5S02 first, as the plan's as-built line says.
- Security N1 (two comments said the transaction id "never leaves the database"; the general
  draft reads still return it inside `app.financial_draft_json`): the migration and test comments
  now say no correction result or replay shows it; the plan's 11e item now says that the general
  draft reads must strip it (not new since 10a; no HTTP route yet).
- Security N2 ("Staff cannot confirm" is the service's capability check plus the database's
  authorization string and human-approver checks, as in every earlier correction variant; the 6b
  confirm requires a person only through the active user-account check): recorded here; the
  database does not check the capability itself.

Fixes after round 2: one test assertion changed and one added, comments in the test module and the
migration (no SQL statement changed), docs/010 and plan text. Static checks each in its own call:
lint, format and type check clean. Migration-only check: 114 upgrades, head `20261119_115`.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T4 | PostgreSQL, targeted: the new module | 6 passed | round-2 test fixes | `V1-056-slice-10d-targeted-test-run-4.txt` |

Standing round-3 rule: round 2 has no blocker and one should-fix, so one round 3 follows, after a
full unit run and a full PostgreSQL run.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U3 | backend unit, full (under `caffeinate -dims`) | 3702 passed, 1852 skipped, 1 warning (Starlette) | standing round-3 rule | `V1-056-slice-10d-unit-test-run-3.txt` |
| P3 | PostgreSQL, full (under `caffeinate -dims`) | 2015 passed, 3 warnings (Starlette; two instances of the known Pydantic alias warning) | standing round-3 rule; round-2 fixes changed a test file and migration comments | `V1-056-slice-10d-full-test-run-3.txt` |

Secret check of T4, U3 and P3: none found.

## Review round 3 (2026-10-10; fresh read-only subagents, independent and security; standing rule)

Independent: 0 blockers, 0 should-fix, 3 notes. Security: 0 blockers, 0 should-fix, 3 notes.
Round 3 passes; the commit follows. Both confirmed that each round-1 and round-2 fix fails without
the code it targets, that the counts in the docs match the run outputs, and that no run output or
changed file holds a secret.

- Independent N1 (the rule-ID lists differ: docs/010 left out BR-DEP-022; the migration docstring
  lists fewer IDs): docs/010 fixed (text); the migration docstring is left as it is (no file of
  code changes after P3).
- Independent N2 (owner answer 2 to Q-71 at the confirm answers P5S02 first): already stated in
  the plan's as-built line and above; no change.
- Independent N3 and security N3 (run outputs contain local absolute paths in warnings, as every
  earlier committed output): not a secret; no change.
- Security N1 (the 6b confirm has no explicit human-identity check): the round-2 sentence above is
  reworded (text).
- Security N2 (the least-privilege test checks four roles, as 20 other modules; the other roles
  have no EXECUTE because PUBLIC is revoked and no default privileges exist): no change.

Fixes after round 3: text only (docs/010, this record). No PostgreSQL test and no unit test reads
them (owner answers to Q-2026-10-07-44 and Q-2026-10-09-67).
