# V1-056 sub-slice 8e-2 — Final Settlement Credit applications: review record

Sub-slice: 8e-2 (migration `20261028_93`). Not committed. Base commit: 5356f7f (the 8e-1
checkpoint).
Rule IDs: BR-CREDIT-006, BR-CREDIT-008, BR-SETTLE-004, BR-SETTLE-009, BR-SETTLE-012,
BR-SETTLE-013, BR-AUTH-010, DL-032; owner answers 1 to 3 to Q-2026-10-06-32 (answer 4 belongs to
8e-3) and the owner answers to Q-2026-10-05-29.

## Before the build (read only)

- Read in order: AGENTS.md, ops/NOW.md, ops/V1_055_RUN_RULES.md, ops/V1_056_TAKEOVER.md, the
  plan's slice 8 design note and every 8e note, Q-2026-10-05-29, -30, Q-2026-10-06-32, -33, the
  8c, 8d and 8e-1 review records and the V1-056 notes in docs/010. Start state checked: HEAD
  5356f7f, only `ops/reviews/V1-056-slice-08c-full-test-run.txt` untracked.
- The owner answers to Q-2026-10-06-32 are exactly its recommendations 1 to 3 (and 4 for 8e-3),
  so 8e-2 was built without a further stop. No rule was unclear or in conflict.
- Read-only search for affected tests before P1: 26 head-revision assertions in 14 modules moved
  from `20261027_92` to `20261028_93` (only the revision string); the whole-catalog function
  tests are pinned to earlier revisions; no test reads the two relaxed CHECKs, the Credit
  application columns or the triggers of `customer_credit_applications` and
  `customer_credit_application_reversals`; the one test that inserts a reversal as the owner
  (`test_credit_application_migration.py`, a backdated reversal) meets the new refusal only for a
  Settlement row, so its expectation is unchanged; no earlier test writes a Credit application
  with a Settlement; the new module runs last.

## Built

- Migration `20261028_93`: the two CHECKs of migration 41 relaxed (asserted by name and text
  before the change): `final_settlement_id` becomes a foreign key; `financial.approve` only with a
  Settlement, `credits.apply` otherwise. `app.final_settlement_credit_application_id(draft, step)`;
  the source check `app.assert_final_settlement_credit_application_source` (BEFORE INSERT, runs
  first, only for Settlement rows); the deferred check
  `app.assert_final_settlement_credit_application_confirmed`; the reversal refusal
  `app.refuse_final_settlement_credit_application_reversal` (BEFORE INSERT on the reversals, runs
  first, `P5S01`); the writer `app.post_final_settlement_credit_application`. All are definer
  functions with `search_path=pg_catalog`; EXECUTE revoked from PUBLIC, prm_runtime,
  prm_financial and prm_bootstrap; no grant.
- `credit.py` maps `P5S01` to `CreditConflictError`.
- Tests: `test_final_settlement_credit_application_migration.py` (7) and
  `test_final_settlement_credit_application.py` (1 unit); 8 traceability entries appended; the
  module added to `scripts/database-test.sh`; docs/004 (DB-CREDIT-002, DB-CREDIT-003), docs/010,
  the plan (8e-2 as built, notes for 8e-3 and 11e).

Static checks (separate commands): `ruff format` on the changed files; `ruff check src tests` and
the migration (three long lines fixed, then clean); `ruff format --check src tests` (291 files);
`mypy` (one variable annotation added, then no issues in 291 source files). Once, early on,
`ruff check` and `ruff format --check` were chained in one shell call; both were then run again
as separate commands.

## Runs before review round 1

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U1 | backend unit, full | 3456 passed, 1688 skipped, 1 warning (known Starlette deprecation) | first run of 8e-2 | `V1-056-slice-08e2-unit-test-run.txt` |
| P1 | PostgreSQL, full (`./scripts/database-test.sh`) | migration `20261028_93` failed with `syntax error at end of input` (a `CASE` inside a PL/pgSQL `IF` condition ends the condition at its `THEN`), so 109 failed and 1548 errors at setup, 193 passed | first run of 8e-2 | `V1-056-slice-08e2-full-test-run-excerpt.txt` (the full 44 MB output stays untracked) |
| P2 | PostgreSQL, full | 3 failed, 1847 passed, 2 warnings | after correction 1 of cause "migration SQL syntax" (the `CASE` in parentheses; every other `IF` checked) | `V1-056-slice-08e2-full-test-run-2.txt` |
| P3 | PostgreSQL, full | 1850 passed, 2 warnings | after correction 1 of cause "draft without the remaining Pet basis" (test only, so U1 stands) | `V1-056-slice-08e2-full-test-run-3.txt` |

P1's two CHECK assertions ran before the failing statement and passed, so the relaxed constraint
names and texts are the ones migration 41 created. P2 failures: three new tests recorded the 8c
normal plan, which has a remaining Pet Deposit step, without its basis; the recorder refused
(22023) before the writer was called. Corrected with `pet_remainder=STAFF`, as the 8c tests do.
The second warning in P2 and P3 is the known intermittent pydantic
`UnsupportedFieldAttributeWarning` in `test_credit_refund_api_migration.py` (slice 12 item);
recorded, not hidden.

## Round 1 (2026-10-06)

Both reviewers were fresh read-only subagents given the diff, the rule IDs, the takeover file, the
plan's 8e notes and the owner answers; neither edited anything or ran a test.

### Independent review: 0 blockers, 2 should-fix, 7 notes

- S1: docs/005 did not say that `POST /credit-applications/{id}/reverse` now answers 409 for a
  Credit application the Settlement made, and the 8e-1 amendment there said all Credit
  reversals stay open. Fixed: API-063 amendment line and the 8e-1 line corrected.
- S2: no test reached the human-approver/`financial.approve` check (42501 at insert) or the
  deferred "pays exactly the obligation of its Credit step" check (23514 at commit). Fixed: rows
  written as the owner in the mixed Rent test (a Settlement header with `credits.apply` refused
  when written; a header matching the designated step with its detail on the Rent line instead
  of the Internet line refused at commit). The `TERMINATED` part of the target check is not
  tested on its own: a Settlement exists only for a TERMINATED Lease (8a-1), so it is defensive,
  as in 8d; the target-Lease part is tested.
- Notes taken: N3 the credit Adjustment excess assertion now also checks the 8e-2 message (the
  8e-1 guard would give the same SQLSTATE); N4 a repeated step with Credit left now meets the
  derived id (23505, `customer_credit_applications_pkey`) in a test, and 23505 is in the 8e-3
  mapping notes; N5 the writer names its own four deferred checks instead of `SET CONSTRAINTS
  ALL DEFERRED` (no payment history budget trigger exists on these two tables; checked in
  migration 41); N6 an inactive approver arrives as 55000 through
  `app.assert_active_financial_actor`, so 8e-3 checks the approver first (plan note); N7 the
  existing `credit.applied` audit does not name the Settlement: 8e-3's audit event names the
  Settlement's Credit applications and the draft (plan note; existing Credit triggers unchanged
  as planned); N9 commit with explicit paths only (the 44 MB P1 output and the 52 MB 8c output
  stay untracked).
- N8 answered: the deferred check accepts a confirmation written later in the same transaction,
  as 8d does; 8e-3 writes its decision first (plan note 12), so `decided_at` precedes the
  applications; not changed, to keep one rule for both Settlement writers.

### Security review: 0 blockers, 1 should-fix, 4 notes

- SF1: the writer (and the existing Credit check, and the 8a Deposit application check) lock the
  target Invoice `FOR UPDATE` after the Settlement row, which breaks the plan's note that 8e-3
  takes the Lease's Invoices `FOR NO KEY UPDATE` and nothing after the Settlement row is a
  stronger Rent Invoice lock (a detected 40P01 possible; no integrity effect). Fixed in the plan
  (amends note 7): before the Settlement row 8e-3 locks the Credit steps' Payments and Credits in
  id order, then the Lease's Charges and Invoices, those a Credit step or Deposit application
  targets `FOR UPDATE` (with their lines for a Credit step), the others `FOR NO KEY UPDATE`.
- Notes: N2 nothing checks that every Credit step was written (8e-3 closure check, plan note);
  N3 the refusal looks at the Settlement link, not at closure (equivalent, as only the confirm
  writes these rows and closes in the same transaction); while such an application stands its
  Credit and its source Payment cannot be reversed (owner information in docs/010 and the plan;
  slice 10 opens it only through a linked correction row); N4 as independent N5 (taken); N5 as
  independent N7 (plan note).

Static checks after the fixes (separate commands): `ruff format` (2 files unchanged), `ruff check
src tests` and the migration (clean), `ruff format --check src tests` (291 files), `mypy` (no
issues in 291 source files).

Read-only search before P4: since P3 only the writer's `SET CONSTRAINTS` statement, the new test
module and documents changed; no other module calls the writer or reads its constraints.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U2 | backend unit, full | 3456 passed, 1688 skipped, 1 warning (Starlette) | after the round-1 fixes | `V1-056-slice-08e2-unit-test-run-2.txt` |
| P4 | PostgreSQL, full | 1850 passed, 2 warnings | after the round-1 fixes | `V1-056-slice-08e2-full-test-run-4.txt` |

The second P4 warning is again the known intermittent pydantic warning in
`test_credit_refund_api_migration.py` (slice 12 item).

## Round 2 (2026-10-06)

Fresh read-only reviewers again (the diff, this record, the plan, the owner answers). Both
confirmed every round-1 fix and written answer (docs/005, the owner-row tests, the 8e-2 message
on the excess path, the 23505 repeat, the four named deferred checks being every deferrable
constraint on the two tables, the plan notes).

### Independent review: 0 blockers, 1 should-fix, 4 notes

- S1: the round-1 lock-order amendment named a lock mode only for targeted Invoices; a Credit step
  or Deposit application on a Late-payment Charge locks the Charge and then its source Invoice
  `FOR UPDATE` (`app.lock_payment_allocation_target`) after the Settlement row. Fixed in the plan:
  a targeted Charge and its source Invoice are locked `FOR UPDATE` (Charge first) before the
  Settlement row.
- N1: docs/004 DB-SETTLE-001 (8e-1) said Credit application reversals are not guarded without the
  8e-2 exception. Fixed: "not guarded by this trigger" with a pointer to DB-CREDIT-003.
- N2: the writer's comment named only plan note 7. Fixed: it names the amended lock order.
- N3: two defensive branches without a test: the header step match for Credit, amount, basis or
  designation, and the Credit-first refusal when the Settlement has only a Refund. Taken for the
  first (an owner-written header with a designation the step does not have is refused, 23514).
  Answered for the second: the Refund source check (8d) already refuses a Refund while debt that a
  Deposit could pay is open, and the Credit-first refusal with a Deposit application is tested;
  the Refund-only branch is defensive against rows written as the owner.
- N4: the source check did not refuse a time before the Settlement started, as 8a and 8d do.
  Taken: `NEW.occurred_at<v_settlement.started_at` refused (23514), with an owner-written
  backdated header in the test.

### Security review: 0 blockers, 1 should-fix, 2 notes

- SF-1: the same as independent S1 (fixed above).
- N-1: one lock-order inversion remains that 8e-3 cannot remove: `app.adjust_invoice` locks its
  Invoice before the credit-excess reversal locks a Payment, so a credit Adjustment reversing an
  ordinary Credit application from the same Payment as a Settlement Credit step can meet 8e-3 in a
  detected deadlock (40P01, mapped to a conflict; the inversion already exists between
  `app.post_credit_application` and `app.adjust_invoice`). Recorded in the plan's 8e-3 notes.
- N-2: the `P5S01` mapping sits in the Credit service's shared error handler; only the reversal can
  raise it today. Taken: a comment in `credit.py`.

Round 2 has no blocker and one should-fix (the same finding from both reviewers), so the standing
rule allows one round 3 after the full backend unit and PostgreSQL runs.

## Fixes after round 2 and runs before round 3

Static checks (separate commands): `ruff format` (3 files unchanged), `ruff check src tests` and
the migration (clean), `ruff format --check src tests` (291 files), `mypy` (no issues in 291
source files). Read-only search before P5: since P4 only the source check (one added refusal),
comments, the new test module and documents changed; no other module writes a Settlement Credit
application.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U3 | backend unit, full | 3456 passed, 1688 skipped, 1 warning (Starlette) | standing rule before round 3 | `V1-056-slice-08e2-unit-test-run-3.txt` |
| P5 | PostgreSQL, full | 1850 passed, 2 warnings | standing rule before round 3 | `V1-056-slice-08e2-full-test-run-5.txt` |

The second P5 warning is again the known intermittent pydantic warning in
`test_credit_refund_api_migration.py` (slice 12 item).

## Round 3 (2026-10-06, standing round-3 rule)

### Independent review: 0 blockers, 0 should-fix, 3 notes

Every round-2 fix is in place and correct (the plan lock note covers targeted Late-payment Charges
and their source Invoices, as `app.lock_payment_allocation_target` locks them; the docs/004
pointer; the writer comment; the `started_at` refusal, reached by its owner-written test; the
designation-mismatch owner-row test; the `credit.py` comment, whose claim holds). Rechecked and
sound: both reversal writers meet the `a0_` refusal, trigger order, the four deferred checks,
the writer's Rent-first proposal matching the 8c plan check, the canonical Settlement id in the
draft payload, no reader that breaks (only `financialActionContext.ts`, in the 11e notes), the
409 mapping, docs, traceability (8 appended), the 26 revision-only test changes, no tightening
that needs the owner. Notes: N1 no test of a designated Credit step on a Late-payment Charge (the
same path as the one-call function; an 8e-3 confirm test, plan note); N2 the non-human half of the
42501 check has no test of its own (optional; plan note); N3 two docs/004 lines over the wrap
width (rewrapped).

### Security review: 0 blockers, 0 should-fix, 1 note

The round-2 lock-order fix matches `app.lock_payment_allocation_target`; the remaining
`app.adjust_invoice` inversion is recorded; the `started_at` refusal matches 8a. Final sweep found
nothing: no role reaches the writer or confirms a `FINAL_SETTLEMENT` draft; commit needs the same
human approver's CONFIRMED `financial.approve` decision; rows match their step; Credit pays only
its own Customer's debt on the Settlement Lease; no undo path (both reversal writers refused, a
Credit reversal still needs its applications reversed, rows immutable; the predictable derived ids
give no head start); the serialization-guard updates are already serialized by 8e-3's pre-locks;
fixed messages, no data leak; no tightening beyond owner answer 3. Note N-1 (for the 8e-3
pre-code review, not an 8e-2 defect): place the Lease row lock at an explicit position in the
amended lock order and check it against Lease-first writers such as the unpaid-Initial resolution
(plan note).

### Outcome

Round 3 has no blocker and no should-fix, so 8e-2 is committed under the standing round-3 rule.
After round 3 only documents changed (two docs/004 lines rewrapped, the plan notes, this record,
ops/NOW.md); the committed migration, code and tests are exactly what U3 and P5 ran. Final runs:
U3 backend unit 3456 passed; P5 full PostgreSQL 1850 passed. Corrections used: migration SQL
syntax 1 of 2, draft without the remaining Pet basis 1 of 2. The P1 output
(`V1-056-slice-08e2-full-test-run.txt`, 44 MB) is not committed; the excerpt is.
