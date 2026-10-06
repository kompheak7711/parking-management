# V1-056 sub-slice 8f — Credit Refund to the Invoice Customer who is not the payer: review record

Sub-slice: 8f (migration `20261030_95`). Committed after round 3. Base commit: b75e236 (after the
8e-3 follow-up).
Rule IDs: BR-CREDIT-014, BR-AUTH-010, BR-REFUND-002, BR-REFUND-003, BR-REFUND-009,
BR-REFUND-011, BR-REFUND-014, BR-PAY-042; DB-REFUND-001; owner answer to Q-2026-10-05-19.

## Before the build

- Read in order: AGENTS.md, ops/NOW.md, ops/V1_055_RUN_RULES.md, ops/V1_056_TAKEOVER.md, the
  plan's slice 8 design note and the 8f entry (with the slice 9 notes on the Refund of such a
  Credit and on the 23514 mapping), ops/V1_056_QUESTIONS.md, the 8e-3 review record and the
  V1-056 notes in docs/010. Start state checked: tree clean, HEAD b75e236.
- Pre-code design written to the plan's 8f entry (read only; within the plan and docs/004, so no
  owner question). Only Credits that a credit Adjustment released can have a Customer other than
  the payer (Credit recognition requires the payer otherwise; migration 67 is the only exception).
- Read-only search of all backend tests for affected tests: the 26 head-revision assertions in 14
  modules; every test that can observe a 23514 at a Refund draft confirmation (concurrent Refund
  confirmations, Credit recipient refusals): two concurrency tests whose loser may now get a
  conflict (narrowed, docs/010), the slice 7 refusal test already accepts a conflict, and
  `test_refund.py` maps 23514 at recording only (unchanged); the earlier forward-only catalog tests
  compare fixed revision pairs; the whole-database Refund ledger check of slice 3a-2
  (`customer = recipient`) still holds for the new Refunds, and the new module runs last.

## Built

- Migration `20261030_95`: `app.credit_customer_refund_basis`, `app.credit_customer_refund_id`,
  `app.credit_customer_refund_draft`, `app.credit_customer_refund_allowed`,
  `app.assert_credit_customer_refund_confirmed` (deferred constraint trigger
  `refunds_credit_customer_confirmed`), `app.record_credit_customer_refund_draft` (financial role),
  `app.post_credit_customer_refund` (internal); `app.validate_general_refund_source` and
  `app.confirm_refund_draft` patched.
- `refund.py`: `CreateCreditCustomerRefundCommand`, `RefundService.record_credit_customer_draft`;
  `P5206` is a conflict; at confirmation 23514 is a conflict.
- Tests: `test_credit_customer_refund_migration.py` (7; 8 after review round 1),
  `test_credit_customer_refund.py` (5 unit tests, 19 cases; 20 after review round 1); 12
  traceability entries appended (13 after review round 1); the module added to
  `scripts/database-test.sh` (last); docs/004, docs/005, docs/010, the plan.

Static checks (separate commands): `ruff format` on the changed files (three reformatted); `ruff
check src tests` and the migration (one unused variable fixed); `ruff format --check src tests`;
`mypy` (one typing error in the new unit test fixed, then no issues in 296 source files). Once,
after the typing fix, `ruff format` and `ruff check` on the one unit test file were chained in one
shell call; `ruff check`, `ruff format --check` and `mypy` were then run again as separate commands.

Migration-only check before P1 (owner rule): a throwaway copy of `scripts/database-test.sh` outside
the repo runs `alembic upgrade head` on a fresh container; it reached `20261030_95`.

## Runs before review round 1

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U1 | backend unit, full | 1 failed (`test_traceability_manifest_covers_executable_tests`: the new tests had no traceability entries yet), 3495 passed, 1710 skipped, 1 warning (Starlette) | first run of 8f | `V1-056-slice-08f-unit-test-run.txt` |
| U2 | backend unit, full | 3496 passed, 1710 skipped, 1 warning (Starlette) | after correction 1 of cause "missing traceability entries" (12 entries appended) | `V1-056-slice-08f-unit-test-run-2.txt` |
| P1 | PostgreSQL, full (`./scripts/database-test.sh`) | 1873 passed, 1 warning (Starlette) | first run of 8f | `V1-056-slice-08f-full-test-run.txt` |

## Round 1 (2026-10-06)

Both reviewers were fresh read-only subagents given the combined diff, the rule IDs, the takeover
file, the plan's 8f entry and the owner answer; neither edited anything or ran a test.

### Independent review: 0 blockers, 1 should-fix, 9 notes

Confirmed sound: the patch anchors (each exactly once; migrations 79 and 91 do not touch them), no
CASE inside an IF condition, `credit_customer_refund_allowed` never returns NULL, recording under
`refunds.create` and confirming under `financial.approve` in the service and the database, the
recipient always the Credit's Customer, the payer rule lifted only for Credits a credit Adjustment
released to another Customer, the lock order (draft lock, method, Payment, Credit; amount checked
after the locks), exactly-once and replay, 23514 as a conflict only at confirmation, the other
Refund variants and the Final Settlement writers unaffected, grants, cents, append-only history,
the narrowed tests, docs and traceability.

- SF1: the frontend action context (`credit()`, `refundSummary()`) and the Refund source read
  still assume the payer is the recipient; the plan lacked notes for 11c and 11e. Fixed: plan notes
  (8f "Notes from the 8f review round 1") and the docs/004 sentence on correction paths qualified.
- N1 untested clauses of the two checks: fixed,
  `test_only_the_same_approver_s_confirmation_and_details_let_the_refund_stand`.
- N2 the writer does not set its deferred check back to DEFERRED: fixed (as the 8d writer).
- N3 Final Settlement preview test: answered (docs/010), slice 12 item.
- N4 HTTP confirmation test: answered, slice 11c with the record route.
- N5 stale text: fixed (docs/004 DB-PAY-008 rewritten, the slice 7 test comment, the plan's slice 9
  bullets).
- N6 rule-ID lists: fixed (migration docstring, docs/010 heading).
- N7 draft lookup cost, N8 the pre-existing timing case of the concurrency test, N9 the unreachable
  `P5206` re-check: answered (docs/010), N7 and N8 slice 12 items.

### Security review: 0 blockers, 0 should-fix, 6 notes

Confirmed sound: only one writer of such a Refund and only through the confirmation of its own
draft; the recipient checks; the basis cannot be forged (immutable inputs, append-only releases);
the draft match (kind, capability, variant, Property, source, recipient, amount, reason, derived
id); collisions and replay; Staff cannot confirm; grants and `search_path`; no injection; static
error text; 23514 as a conflict; lock order and races; the Final Settlement preview and confirm;
Refund corrections; the slice 7 refusals; no new route.

- N1 (earlier path, not created by 8f): a third-party Payment's adjustment Credit (not from a moved
  allocation) can still be reversed with one call, so its value can go back to the payer through an
  ordinary Payment Refund. Fixing it refuses input accepted today: owner question Q-2026-10-06-35,
  not blocking 8f (8f's code does not depend on it).
- N2 a Reservation Refund draft's client-chosen `outcome_id` or `refund_number` can take the derived
  Refund id or number first, and the confirmation's 23505 was reported as "replay": fixed, 23505 at
  Refund draft confirmation is a conflict (unit test); the same latent clash for the 8d and 8e
  derived ids is a slice 12 item.
- N3 as independent N2: fixed.
- N4 the Refund resource embeds the payer's source Payment (memo, channel reference): slice 11c note.
- N5 the audit event's Lease comes from the source Payment: slice 12 note.
- N6 `refunds.create` on the Refund row: documented choice 3, slice 12 owner item.

## Runs after the round-1 fixes

Static checks (separate commands): `ruff format` (no change), `ruff check src tests` and the
migration (one long line fixed, then clean), `ruff format --check src tests`, `mypy` (no issues in
296 source files). Read-only search: since P1 the migration (the DEFERRED reset, the docstring), the
confirmation's mapping (23505), the new tests, one comment in `test_payment_move_migration.py`,
docs and traceability changed; no other test sees a 23505 at a Refund draft confirmation.
Migration-only check before P2: reached `20261030_95`.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U3 | backend unit, full | 3497 passed, 1711 skipped, 1 warning (Starlette) | after the round-1 fixes | `V1-056-slice-08f-unit-test-run-3.txt` |
| P2 | PostgreSQL, full | 1874 passed, 2 warnings | after the round-1 fixes | `V1-056-slice-08f-full-test-run-2.txt` |

The second P2 warning is the known intermittent pydantic `UnsupportedFieldAttributeWarning` in
`test_credit_refund_api_migration.py::test_credit_refund_competition_fixture_isolates_unrelated_shared_writer`
(slice 12 item); recorded, not hidden.

## Round 2 (2026-10-06)

Fresh read-only reviewers again (the combined diff, this record, the plan, the owner answers).

### Independent review: 0 blockers, 1 should-fix, 4 notes

Every round-1 fix and written answer verified; the 23514 and 23505 mapping cannot hide a committed
outcome (a lost reply has no SQLSTATE and replays); the DEFERRED reset and the later
`SET CONSTRAINTS ALL IMMEDIATE` fire the check inside the command with both rows visible; patch
anchors, rules, locks, tests, docs and traceability re-checked.

- SF1: the round-1 clause test proved only the deferred check's details clause (both of its
  failing cases lacked the details row), so the decision clause of the deferred check was
  untested and the docs overclaimed "each clause". Fixed: the test also writes the Refund while its
  draft waits with the details row and no decision, with another approver's CONFIRMED decision, and
  with a REJECTED decision (each 42501 at commit), asserts every refusal's message, and notes that
  `authorization_reference` cannot be broken alone (`financial_draft_decision_shape`).
- N2 the DEFERRED reset had no test: fixed, the same test ends with the real confirmation after an
  earlier `SET CONSTRAINTS ALL IMMEDIATE` in its transaction (succeeds).
- N3 the confirmation sets ALL constraints IMMEDIATE, not only its own: answered (docs/010), the
  same as `app.create_usd_refund` on every USD confirmation; a top-level command.
- N4 stale counts in this record: fixed.
- N5 the 23505 mapping has only a mocked test: the slice 12 item says so.

### Security review: 0 blockers, 0 should-fix, 1 note

Verified: one writer reachable only through its own draft's confirmation (every
`INSERT INTO app.refunds` site listed; no dynamic SQL; no role writes the tables); the allowed
function never returns NULL; draft matching (only server-built payloads); the DEFERRED reset cannot
be abused (no grant; a deferred check always fires at commit; the confirm writes the details and
decision outside any exception block); replay and approver identity; error mapping (no committed
outcome hidden, static text, bare HTTP status); locks and races; Final Settlement, Refund corrections
and the slice 7 interplay; definer rights, `search_path`, grants; no route or logging change;
Q-2026-10-06-35 predates 8f and is not widened.

- N1 the 8f derived Refund id and number can be taken first by a Reservation Refund draft's
  client-chosen values (denial of service only): the slice 12 item now names 8f.

Round 2 has no blocker and 1 should-fix, so the standing rule allows one round 3 after the full
backend unit and PostgreSQL runs.

## Runs before round 3

Static checks (separate commands): `ruff format` (the test reformatted), `ruff check src tests` and
the migration (clean), `ruff format --check src tests`, `mypy` (no issues in 296 source files).
Read-only search: since P2 only the new test module, docs, traceability, the plan and this record
changed; migration 95 and `refund.py` unchanged. Migration-only check before P3: reached
`20261030_95`.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U4 | backend unit, full | 3497 passed, 1711 skipped, 1 warning (Starlette) | standing rule before round 3 | `V1-056-slice-08f-unit-test-run-4.txt` |
| P3 | PostgreSQL, full | 1874 passed, 2 warnings | standing rule before round 3 | `V1-056-slice-08f-full-test-run-3.txt` |

The second P3 warning is the known intermittent pydantic `UnsupportedFieldAttributeWarning`, this
time in `test_credit_refund_api_migration.py::test_credit_refund_http_real_competing_refunds_cannot_double_consume_credit`
(slice 12 item).

## Round 3 (2026-10-06, standing round-3 rule)

### Independent review: 0 blockers, 0 should-fix, 3 notes

Every round-2 fix verified: each of the six cases of the extended clause test fails if its clause
is removed, the expected messages match the raise sites exactly, and the final confirmation after
`SET CONSTRAINTS ALL IMMEDIATE` proves the writer's DEFERRED reset; final sweep of anchors, the one
writer, which Credits qualify, locks, replay, error mapping, capabilities, grants, history, cents,
the Final Settlement preview, the historical test changes, counts, runs and documents found
nothing. Notes (slice 12 items): N1 no direct test of each draft-match clause and of the release
clause (unreachable today: the only writer copies the row from the draft); N2 "another approver"
in the test is the preparer (wording; the clause holds for any other person; docs/010 reworded, the
test stays as run); N3 the earlier direct-write test asserts SQLSTATEs only.

### Security review: 0 blockers, 0 should-fix, 1 note

Verified that migration 95 and `refund.py` are unchanged since round 2, and a final sweep:
deny-by-default and grants, no Staff confirmation, value only to the Credit's Customer, definer
rights and `search_path`, no injection, no customer or database text in responses or logs, the
error mapping never hides a committed outcome, lock order and races, no new route, the round-2 notes
handled. N1: the deferred check's 42501 maps to an authorization error (404), not a conflict, if a
later change broke the confirmation's write order; unreachable today; slice 12 item.

### Outcome

Round 3 has no blocker and no should-fix, so 8f is committed under the standing round-3 rule. After
round 3 only documents changed (docs/010 wording and round-3 entry, the plan's slice 12 item, this
record, ops/NOW.md); the committed migration, code and tests are exactly what U4 and P3 ran. Final
runs: U4 backend unit 3497 passed; P3 full PostgreSQL 1874 passed. Corrections used: missing
traceability entries 1 of 2. Every run output is small (at most about 200 KB) and committed; nothing
was moved to `~/Development/prm-run-logs/`. Owner question open, not blocking: Q-2026-10-06-35.
