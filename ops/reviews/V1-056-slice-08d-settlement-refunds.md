# V1-056 sub-slice 8d — Final Settlement Deposit Refund source: review record

Sub-slice: 8d (migration `20261026_91`). Not committed. Base commit: addc992.
Rule IDs: BR-DEP-025, BR-REFUND-007, BR-REFUND-014, BR-REFUND-015, BR-SETTLE-008, BR-AUTH-010,
DL-032, BR-SETTLE-005, BR-SETTLE-017, BR-DEP-026, BR-DEP-027, BR-SETTLE-013; owner answer 3 to
Q-2026-10-05-20, Q-2026-10-05-21, Q-2026-10-05-24 and the owner answer to choice (4a) of sub-slice
8c (Q-2026-10-05-30).

## Before the build (read-only)

- Owner answer to choice (4a) recorded in docs/010 and ops/V1_056_QUESTIONS.md (Q-2026-10-05-30)
  and built first: the 8c plan check gains one variable, one capture at step 5 and one final
  check (three anchors in `app.final_settlement_plan_result`); a small change, so no stop.
- The second pydantic warning of 8c runs P4 and P5: read-only search of every saved full
  PostgreSQL output in ops/reviews. `UnsupportedFieldAttributeWarning` appears in 0 to 2 of every
  run since the first saved one (slice 3a-1, 05356c5), always in
  `test_credit_refund_api_migration.py::test_credit_refund_http_real_competing_refunds_cannot_double_consume_credit`
  or `::test_credit_refund_competition_fixture_isolates_unrelated_shared_writer` (two apps
  called from two threads at once), with a different alias value each time. 8c P1 to P3 had
  none, P4 and P5 one each (`lease_id`, `action`). No 8c test caused it; added to the slice 12
  list, not fixed in 8d.
- Design point found during the build: a new `refunds.final_settlement_id` column (docs/004)
  would add a key to every Refund's JSON (`to_jsonb(refund)` in `app.refund_summary` and the audit),
  and the frontend's financial action context checks those keys exactly
  (`frontend/src/financialActionContext.ts`). The Settlement link is therefore kept in
  `app.final_settlement_refund_details`; `app.refunds` keeps its columns (docs/010 choice (2)).
- Read-only search for affected tests before P1: 26 head-revision assertions in 14 modules
  moved to `20261026_91`; the only test asserting the (4a) behavior is
  `test_a_security_refund_follows_once_no_debt_is_left` (one expectation changed, name kept,
  docs/010 note); the strict-order case with a Security Refund and 600 left keeps its expectation
  (the (4a) check runs after the open-debt check); no test reads the patched function bodies at
  head; catalog tests are pinned to earlier revisions; `test_refund_signer_recipient_migration.py::test_refunds_of_the_earlier_shape_project_exactly_as_before`
  reads every Deposit Refund without a `refund_recipient_agreements` row, so the new module runs
  last (slice 12 item); no test compares a Refund row's keys or the audit `source_event` exactly.

## Runs before review round 1

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U1 | backend unit, full | 3451 passed, 1669 skipped, 1 warning (known Starlette deprecation) | first run of 8d | `V1-056-slice-08d-unit-test-run.txt` |
| P1 | PostgreSQL, full (`./scripts/database-test.sh`) | 1829 passed, 1 warning (same) | first run of 8d | `V1-056-slice-08d-full-test-run.txt` |

Static checks before U1 (separate commands, no test run): `ruff format` on the changed Python
files, `ruff check src tests` and the new migration (clean), `ruff format --check src tests`
(287 files formatted), `mypy` (no issues in 287 source files). No correction used.

## Round 1 (2026-10-05)

Both reviewers were fresh read-only subagents given the diff, the rule IDs, the takeover file and
the owner answers; neither edited anything or ran a test.

### Security review: 0 blockers, 1 should-fix, 4 notes

- SF1: the source check accepts a pending draft, so nothing in the database proves a
  `financial.approve` confirmation when the Refund commits; a draft could be withdrawn or
  rejected after the money moved, any active person could be named as approver, and the
  receipt reversal wait (decision trigger) could be skipped. Fixed: deferred constraint trigger
  `app.assert_final_settlement_refund_confirmed` on `app.final_settlement_refund_details`; a
  Settlement Refund commits only with its draft CONFIRMED under `financial.approve` by the
  Refund's approver; tests for pending at commit, rejected, withdrawn, confirmed by another
  approver, confirmed by the same approver.
- N1: the writer took key locks (details foreign keys) before the source check's row locks; two
  writers on one Settlement could deadlock. Fixed: the writer locks the Settlement `FOR UPDATE`
  and serializes the Deposit before writing. REPEATABLE READ caveat: 8e keeps READ COMMITTED
  (plan note).
- N2: the open-debt check reads Invoices and Charges without locks. Answered: plan note for 8e
  (serialize with every writer that can add or reopen Lease debt).
- N3: the (4a) rule is only in the plan check; the Deposit application trigger accepts a
  remaining-Pet application while a `DL_032` Security Deposit holds money. Answered: both
  writers are internal and 8e re-runs the plan check before any application or Refund (plan
  note); adding it to the 8a-1 trigger would change earlier tests' fixtures.
- N4: the source check does not itself wait for pending receipt reversal or forfeiture drafts.
  Answered: with SF1 the decision trigger (receipt reversal wait) always runs in the same
  transaction, and the deferred Deposit balance check refuses any later change that would make
  the held balance negative.
  Correction (owner answer to Q-2026-10-05-31): this answer was wrong. The deferred check
  accepts a confirmation committed in an earlier transaction, so the decision trigger need not
  run in the Refund's transaction, and a receipt reversal or forfeiture draft recorded after the
  confirmation was not seen by a later Refund (round-2 security SF-A). Fixed after round 2: the
  source check refuses while such a draft waits for the Deposit.

### Independent review: 0 blockers, 3 should-fix, 7 notes

- S1: the 8d edit removed the only assertion that a Customer's-choice basis is stored in the
  draft payload. Fixed: the `used_up` loop asserts `pet_remainder` and `pet_remainder_chosen_by`
  for the staff reason and the Customer's choice.
- S2: three of the four open-debt clauses were never the only reason a test failed. Fixed: the
  Pet Refund at a no-ground termination after the Security Refund, with new debt (staff-step
  clause only); `test_a_br_dep_027_pet_refund_waits_only_for_pet_damage_when_the_security_is_kept`
  (pet-damage clause only); `test_a_security_refund_waits_for_any_debt_even_where_the_pet_deposit_may_not_pay_it`
  (Security clause only); the reversed-forfeiture test keeps the other-Security clause.
- S3: the confirmed-draft branches had no test. Fixed with SF1 above (same approver accepted,
  another approver and a rejected draft refused).
- N4: test order coupling with `test_refund_signer_recipient_migration.py`. Answered: the module
  runs last; slice 12 item to scope that check (a narrowing of a historical test).
- N5: docs/004 DB-REFUND-001 still listed `final_settlement_id` as a column. Fixed: the row and
  the SIGNED-Lease sentence are annotated.
- N6: lock order. Fixed (security N1).
- N7: the open-debt check is not serialized. Answered (security N2).
- N8: BR-AUTH-010 at commit and (4a) at database level. Fixed (SF1) and answered (security N3).
- N9: the relaxed CHECK's remaining refusals have no 8d test (answered: a CHECK runs after the
  BEFORE triggers, which refuse such rows first; every earlier Refund writer passed in P1, which
  shows the CHECK accepts every earlier shape); the inactive-method case used a method not in
  the draft (fixed: the draft's own method, deactivated after the draft, is refused); the
  duplicate Refund asserted only 23505 (fixed: the constraint name too).
- N10: the signer test claimed BR-SETTLE-016. Fixed: removed from its traceability entry.

Static checks after the fixes (separate commands): `ruff format`, `ruff check src tests` (clean),
`ruff format --check src tests` (287 files formatted), `mypy` (one test variable reused with
another type, renamed; then no issues).

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U2 | backend unit, full | 3451 passed, 1671 skipped, 1 warning (Starlette) | after the round-1 fixes | `V1-056-slice-08d-unit-test-run-2.txt` |
| P2 | PostgreSQL, full | 1831 passed, 2 warnings | after the round-1 fixes | `V1-056-slice-08d-full-test-run-2.txt` |

Read-only search before P2: since P1 only migration `20261026_91`, the 8d module and the draft
module changed; no other module calls the Settlement Refund writer or touches its table; the head
revision is unchanged. The second P2 warning is the known intermittent pydantic
`UnsupportedFieldAttributeWarning` (alias `charge_id`) in
`test_credit_refund_api_migration.py::test_credit_refund_http_real_competing_refunds_cannot_double_consume_credit`
(slice 12 item); recorded, not hidden.

## Round 2 (2026-10-05)

Fresh read-only reviewers again (the full diff, the rule IDs, the takeover file, this record).
Both confirmed every round-1 fix (the deferred confirmation check, the writer's lock order, the
restored basis assertions, the four open-debt clauses each proven alone, the docs/004 row, the
inactive own method, the constraint name, the traceability IDs).

### Security review: 0 blockers, 2 should-fix, 4 notes

- SF-A: the round-1 answer to N4 is wrong. The deferred check accepts a decision committed in an
  earlier transaction, so the receipt reversal wait (decision trigger) need not run in the
  Refund's transaction; the receipt reversal recorder waits only for a pending Settlement draft,
  so a receipt reversal draft recorded after the confirmation is not seen by a later Refund.
  Likewise `app.lease_deposit_settlement_path` gives `DL_032` for a reversed forfeiture while a
  new forfeiture draft waits. No exposure today (internal writer). Suggested: the source check
  refuses (55000) while a pending `DEPOSIT_FORFEITURE` draft (any variant, receipt reversal
  included) exists for the Deposit, with a test; or require the decision in the same transaction.
- SF-B: the deferred check's own conditions are never the only reason a test passes or fails
  (rejected, withdrawn and other-approver cases are refused earlier by the source check).
  Suggested: one transaction each for Refund then confirmation by the same approver (commits)
  and Refund then confirmation by another approver (42501 at commit, nothing written).
- N-1: an earlier `SET CONSTRAINTS ALL IMMEDIATE` in the transaction (for example
  `app.post_credit_application`) makes the writer fail closed (same as independent SF1).
- N-2: 8e plans to lock the Deposit rows before its decision while the writers lock the
  Settlement row first; safe only because 8e serializes on the Settlement advisory lock; record
  it or lock the Settlement row first in 8e.
- N-3: the other round-1 answers are acceptable.
- N-4: Refund JSON unchanged, no data exposure, no injection; only (4a) is a tightening
  (owner-approved); the test's least-privilege list omits the detail mutation trigger function.

### Independent review: 0 blockers, 1 should-fix, 5 notes

- SF1: `app.post_credit_application` ends with `SET CONSTRAINTS ALL IMMEDIATE`, which stays in
  force; the plan has 8e apply Credit steps through it and then call the Refund writer, whose
  details row relies on a deferred key and the deferred confirmation check, so a valid confirmed
  draft would fail (23503 or 42501). Suggested: the writer sets its two constraints DEFERRED
  before writing (migration 83 resets with `SET CONSTRAINTS ALL DEFERRED`), with a test.
- N2: refusal branches without a test: a kept Deposit ("Only a Deposit that follows DL-032 ..."),
  a Deposit of another Lease, a details row naming another Deposit, the writer's P0002 and 22023.
- N3: the 8c entry in docs/010 still describes choice (4a) as allowed; annotate it as rejected.
- N4: docs/002 has no line for the owner answer to Q-2026-10-05-30 (the answers to Q-21 and Q-24
  have "Amended by" lines under BR-SETTLE-005/017 and BR-DEP-026); add one or say in docs/010
  that docs/002 stays unchanged.
- N5: the round-1 N4 answer is inaccurate (same as security SF-A).
- N6: the least-privilege test omits `app.reject_final_settlement_refund_detail_mutation()`.

### Outcome

Round 2 has no blocker but 3 distinct should-fix findings (security SF-A and SF-B, independent
SF1, which security N-1 repeats), more than the standing round-3 rule allows (at most 2). STOPPED,
NOT committed (Q-2026-10-05-31). No fix after round 2 and no run after P2. Corrections used: none.

## Owner answer and fixes after round 2 (2026-10-05)

Owner answered Q-2026-10-05-31: (1) yes, as an owner exception to the standing round-3 rule:
the three fixes and the listed notes, unit and full PostgreSQL once each, then one round 3 with
no blocker and no should-fix, or stop; fix 1 follows the owner's 8r rule (a Refund is refused
while a receipt reversal or forfeiture draft is pending for the same Deposit, also one recorded
after the Settlement draft was confirmed), with tests for both orders; (2) docs/002 lines under
BR-SETTLE-005 and BR-SETTLE-017; (3) the details table is accepted, docs/004 matches; ask first
when a design differs from docs/004 or the plan. Recorded in docs/010 and the questions file.

Fixes made:
- SF-A: the source check takes the per-Deposit draft lock, then the Deposit row, and refuses
  (55000) while a pending `DEPOSIT_FORFEITURE` draft (forfeiture, forfeiture reversal, receipt
  reversal) names the Deposit; the writer takes the same locks in the same order after the
  Settlement row. Test: a receipt reversal draft cannot be recorded while the Settlement draft
  waits and, recorded after the confirmation, holds back that Deposit's Refund only; a
  forfeiture draft recorded before and one recorded after the confirmation both hold it back;
  after a withdrawal or rejection the Refund is accepted.
- SF-B: the confirmation in the Refund's own transaction: the same approver commits; another
  approver's confirmation is refused at commit (42501) and writes nothing.
- Independent SF1 (security N-1): the writer sets its two deferred checks back to DEFERRED before
  writing; the same-transaction test starts with `SET CONSTRAINTS ALL IMMEDIATE`.
- Notes: a kept Deposit refused (BR-DEP-026), a Deposit of another Lease, details naming another
  Deposit, the writer's P0002 and 22023; the details trigger function in the least-privilege
  EXECUTE check; the 8c entry in docs/010 marks (4a) rejected; docs/002 lines; docs/004 row and
  as-built paragraph; plan notes for 8e (lock order, the writer's deferred checks, the 8r rule)
  and the owner's ask-first rule.

Static checks (separate commands): `ruff format`, `ruff check src tests` (clean), `mypy` (no
issues in 287 source files).

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U3 | backend unit, full | 3451 passed, 1673 skipped, 1 warning (Starlette) | after the round-2 fixes (owner answer to Q-2026-10-05-31) | `V1-056-slice-08d-unit-test-run-3.txt` |
| P3 | PostgreSQL, full | 1833 passed, 2 warnings | after the round-2 fixes | `V1-056-slice-08d-full-test-run-3.txt` |

Read-only search before P3: since P2 only the Settlement Refund writer and source check (migration
`20261026_91`), the 8d module and documents changed; no other module calls the writer or touches
its table; the head revision is unchanged. The second P3 warning is again the known intermittent
pydantic warning in `test_credit_refund_api_migration.py` (slice 12 item).

## Round 3 (2026-10-05, owner exception to the standing rule, Q-2026-10-05-31)

### Security review: 0 blockers, 0 should-fix, 6 notes

All three round-2 fixes hold (the 8r check covers every `DEPOSIT_FORFEITURE` payload shape, which
all carry `deposit_id`; the commit-time check is tested in the Refund's own transaction; the writer
survives an earlier `SET CONSTRAINTS ALL IMMEDIATE`); no path to a Deposit Refund without a
confirmation; no deadlock among existing functions; no tightening needing the owner. Notes: the 8r
check relies on READ COMMITTED (the forfeiture recorders take only the advisory lock); a later
`SET CONSTRAINTS ALL IMMEDIATE` before the 8e decision fails safe (8e note); 8e refunds in Deposit
id order under the Settlement advisory lock; the source revision is not re-checked, so the writer
stays inside the 8e confirm transaction; no test of a pending forfeiture-reversal draft; the Q-31
text said "the same Deposit row lock" (corrected in the questions file).

### Independent review: 0 blockers, 0 should-fix, 8 notes

Every round-2 fix, the round-2 notes and the corrected round-1 answer check out; rules and owner
answers match; earlier Refund kinds and readers unchanged. Notes: no commit-time test of a
same-approver rejection (the `CONFIRMED` condition alone), and docs/010 over-stated what the
commit check proves (wording corrected); 8e writes its decision before the Refund writer or with
no `SET CONSTRAINTS ... IMMEDIATE` between them (plan note); parts of the exact Refund-step match
are not tested alone; a stale docstring in the narrowed 8c test; NOW.md updated at the
checkpoint; a details row inserted by the table owner is not checked (no role can write it);
loose BR-SETTLE-015 mapping of the forward-only test; docs/010 (4a) wording (corrected).

### Outcome

Round 3 has no blocker and no should-fix, so 8d is committed under the owner's answer to
Q-2026-10-05-31. After round 3 only documents changed (docs/010 wording, plan notes, the
questions file correction, this record); the committed code and tests are exactly what U3 and P3
ran. Test-only and hardening notes are in the plan's slice 12 list. Final runs: U3 backend unit
3451 passed; P3 full PostgreSQL 1833 passed. Corrections used: none.
