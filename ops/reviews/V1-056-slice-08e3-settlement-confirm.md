# V1-056 sub-slice 8e-3 — Final Settlement confirm and close: review record

Sub-slice: 8e-3 (migration `20261029_94`). Committed after round 3. Base commit: 697d309 (the 8e-2
checkpoint).
Rule IDs: BR-SETTLE-004, BR-SETTLE-007, BR-SETTLE-008, BR-SETTLE-009, BR-SETTLE-011,
BR-SETTLE-012, BR-SETTLE-015, BR-SETTLE-016, BR-SETTLE-017, BR-AUTH-010, DL-032, BR-DEP-023,
BR-DEP-026, BR-DEP-027, BR-CREDIT-006, BR-CREDIT-008, BR-RENT-030; DB-SETTLE-001, DB-SETTLE-002, DB-SETTLE-004,
DB-SETTLE-006; owner answers to Q-2026-10-05-20, -23, -24, Q-2026-10-06-32 (answer 4), -33
(answers 2 and 3) and -34.

## Before the build

- Read in order: AGENTS.md, ops/NOW.md, ops/V1_055_RUN_RULES.md, ops/V1_056_TAKEOVER.md, the
  plan's slice 8 design note and every 8e-3 note, Q-2026-10-05-20, -24, -29, -30, Q-2026-10-06-32,
  -33, the 8c, 8d, 8e-1 and 8e-2 review records and the V1-056 notes in docs/010. Start state
  checked: HEAD 697d309; only the two allowed untracked run outputs.
- Owner answers to the 8e-2 report carried out first: both untracked run outputs moved (not
  deleted) to `~/Development/prm-run-logs/`, git status clean; slice 10 item for a bounced Payment
  whose Credit or Deposit a Settlement used; the two run rules (migration-only check before each
  full PostgreSQL run; large outputs as an excerpt) in ops/V1_055_RUN_RULES.md.
- Design review found one conflict: built literally, the new `RENT_PERIOD_NOT_BILLED` would block
  a Settlement for good after a BR-RENT-030 hand-back VOID, because the billing rule still counts
  the early final month as billable. STOPPED before code (Q-2026-10-06-34); the owner answered
  in session: leave such a month out (the recommendation). Recorded in docs/010 and the questions
  file.
- Read-only search for affected tests: 26 head-revision assertions in 14 modules move to
  `20261029_94` (the 8e-2 forward-only lookup keeps `20261028_93`); the new blocking issue
  touches only tests that read the preview or record a draft for a Lease with unbilled recurring
  Rent months: `two_signer_case` (5 tests in 3 modules), `mixed_rent_case` (2 tests) and
  `test_replaced_one_time_charges_are_listed_as_information`; their inputs now bill and pay those
  months in full (`tests/rent_month_test_support.py`), so their expectations are unchanged; the
  other preview tests with long Leases assert single issue codes, not the whole list; the 8a-1,
  8a-2, 8d and 8e-1 tests write applications or closures as the owner and never call the preview;
  the two exact `blocking_issues == []` assertions in the preview module use Leases that end
  inside their Initial Rent coverage; no catalog test lists the new tables; the patched preview
  and closure guard are read by no other test.

## Built

- Migration `20261029_94`: `app.confirm_final_settlement_draft` (financial role);
  `app.final_settlement_unbilled_rent_months`, `app.final_settlement_deposit_application_id`,
  `app.final_settlement_refund_id`; the tables `app.settlement_invoice_items` (with `id`),
  `app.settlement_late_payment_charge_items`, `app.settlement_invoice_line_items` with insert
  checks, a deferred reconciliation check and append-only triggers; the preview patched with
  `RENT_PERIOD_NOT_BILLED`; the closure guard patched with the approver and clock checks.
- `final_settlement.py`: `FinalSettlementService.confirm`, `FinalSettlementStaleDraftError`,
  `CONFIRM_STALE_STATES`; `P5S01` added to the conflict states.
- Tests: `test_final_settlement_confirm_migration.py` (11), `test_final_settlement_confirm.py`
  (3 unit, 21 cases); 14 traceability entries appended (17 after review round 1); the module added to
  `scripts/database-test.sh` (last); docs/004, docs/005, docs/010, the plan.

Static checks (separate commands): `ruff format` on the changed files; `ruff check src tests` and
the migration (six long lines in the new test module fixed); `ruff format --check src tests`;
`mypy` (one `int(object)` in the new test fixed, then no issues in 294 source files). Once,
after the long-line fix, `ruff format` and `ruff check` were chained in one shell call; all three
checks were then run again as separate commands.

Migration-only check before each full PostgreSQL run (owner rule): a throwaway copy of
`scripts/database-test.sh` outside the repo runs `alembic upgrade head` on a fresh container;
before P1 and before P2 it reached `20261029_94` with exit 0.

## Runs before review round 1

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U1 | backend unit, full | 3477 passed, 1698 skipped, 1 warning (known Starlette deprecation) | first run of 8e-3 | `V1-056-slice-08e3-unit-test-run.txt` |
| P1 | PostgreSQL, full (`./scripts/database-test.sh`) | 1 failed (`test_a_stale_or_blocked_draft_is_refused_and_stays_pending`: after the 100 payment the other line owed 12,400, so the test's second plan left 400 open and its Pet Refund was refused by the plan check, 55000), 1860 passed, 2 warnings | first run of 8e-3 | `V1-056-slice-08e3-full-test-run.txt` |
| P2 | PostgreSQL, full | 1861 passed, 2 warnings | after correction 1 of cause "stale-test plan arithmetic" (Pet remainder 2,000 and Refund 5,500; test only, so U1 stands) | `V1-056-slice-08e3-full-test-run-2.txt` |

The second warning in P1 and P2 is the known intermittent pydantic
`UnsupportedFieldAttributeWarning` in
`test_credit_refund_api_migration.py::test_credit_refund_http_real_competing_refunds_cannot_double_consume_credit`
(slice 12 item); recorded, not hidden. In P1 every fixture change and every other new test
passed, including the four end-to-end Settlements.

## Round 1 (2026-10-06)

Both reviewers were fresh read-only subagents given the combined diff, the rule IDs, the takeover
file, the plan's 8e notes and the owner answers; neither edited anything or ran a test.

### Security review: 0 blockers, 1 should-fix, 5 notes

Confirmed sound: deny-by-default (only the confirm is granted, to `prm_financial`; definer
functions with `search_path=pg_catalog`), no Staff path to a confirm, stale or owner-written
drafts cannot move money (digest and full plan result compared under every lock; the writers and
the closure check re-check each step), replay only for the same approver, the kept Security
Deposit and open-debt rules enforced three times, READ COMMITTED enforced, lock order against
every writer that adds or reopens Lease debt, no injection or data leak, error mapping per plan
note 16, no tightening beyond the owner answers.

- SF1: the confirm's own refusals (another Property, another kind, a rejected or withdrawn
  draft, a second approver after confirmation, a non-human approver, another isolation level)
  had no test. Fixed: `test_the_confirm_refuses_other_drafts_approvers_and_isolation_levels`
  (the non-human case answered below).
- N2 two-connection test: optional (plan); answered in docs/010 (14).
- N3 internal invariant refusals (23514) reported as stale: answered (9).
- N4 a deferred check tying every closure to a CONFIRMED decision: answered (11), slice 12.
- N5 least-privilege test: taken (the append-only trigger function; PUBLIC on the tables).
- N6 the confirm runs under the shared 3-second statement timeout: owner item (15), slice 12.

### Independent review: 0 blockers, 3 should-fix, 8 notes

Confirmed: lock order, the locked checks, write order (decision first, nothing IMMEDIATE before
the Refund writer), the closure check, the snapshots, the audit event, error mapping, cents,
append-only, grants; the changed historical test inputs keep their expectations meaningful
(months billed and paid in full before any draft); no clock-dependent dates; traceability
append-only.

- S1: plan note 1 (current move-out in the closure snapshot) not proven. Fixed:
  `test_a_moved_out_lease_closes_with_its_current_move_out`. Two current move-out records cannot
  be created (the move-out record's own checks), so that refusal stays defensive (answer 10).
- S2: the Rent-month tests did not pin the rule's edges. Fixed: a month whose Rent Invoice staff
  VOIDed for another reason still blocks; the whole blocking list before billing; a ready
  Settlement after.
- S3: no confirm of a BR-DEP-027 termination or of the Customer's choice. Fixed:
  `test_a_br_dep_027_termination_refunds_the_pet_rest_while_debt_stays`.
- Notes taken: N4 and N5 docs/004 wording; N6 the Refund order compares uuids; N8 a comment on
  the final `SET CONSTRAINTS ALL IMMEDIATE`; N10 append-only tests for every snapshot table and
  TRUNCATE. Answered in docs/010: N7 (8, `P0002`), N9 (13, the decision trigger stays defense in
  depth), N10 non-human approver (12) and the optional two-connection test (14); N8 the
  `Asia/Phnom_Penh` business date repeats the existing pattern of migration 86.

## Runs after the round-1 fixes

Static checks (separate commands): `ruff format`; `ruff check src tests` and the migration (one
import order fixed); `ruff format --check src tests`; `mypy` (no issues in 294 source files).
Read-only search before U2 and P3: since P2 only migration 94 (two ORDER BY casts, a comment),
the new test module, docs and traceability changed; no other module reads them.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U2 | backend unit, full | 3477 passed, 1701 skipped, 1 warning (Starlette) | after the round-1 fixes | `V1-056-slice-08e3-unit-test-run-2.txt` |
| P3 | PostgreSQL, full | 2 failed, 1862 passed, 2 warnings | after the round-1 fixes | `V1-056-slice-08e3-full-test-run-3.txt` |
| P4 | PostgreSQL, full | 1864 passed, 3 warnings | after correction 1 of cause "single test Property" and correction 1 of cause "departed rate slot" (test only, so U2 stands) | `V1-056-slice-08e3-full-test-run-4.txt` |

P3 failures, both in the new round-1 tests: (1) the refusal test took a second Property from
`setup_signed_lease`, but the test database has one Property, so the confirm with that Property
succeeded; corrected: an unknown Property is refused (P4501, not found). (2) `departed(url, 3, 6)`
reused the Utility rate date of the 8e-1 module (unique per Property, type and date); corrected:
a free slot. The migration-only check ran before P3 and P4 (exit 0). The warnings are the known
Starlette deprecation and the intermittent pydantic warning in `test_credit_refund_api_migration.py`.

## Round 2 (2026-10-06)

Fresh read-only reviewers again (the combined diff, this record, the plan, the owner answers).

### Independent review: 0 blockers, 2 should-fix, 3 notes

Every round-1 fix and written answer (8 to 15) verified; no new problem from the fixes; the
changed fixtures only add billed and fully paid months.

- SF1: no confirm by a person other than the preparer, so the approver fields could not be told
  from the preparer. Fixed: the normal-end test is confirmed by a second `financial.approve`
  person; the decision, `closed_by`, every snapshot's `included_by`, the audit actor, the Credit
  and Deposit applications and the Refunds name the approver, the closure snapshot names the
  preparer, and the replay is by the approver.
- SF2: the move-out test did not prove "current". Fixed: the move-out is corrected after the
  Settlement started; the closure snapshot names the correction while `move_out_date_snapshot`
  keeps the start-time date.
- N1 (a snapshot insert relied on Late-payment Charges of earlier modules): fixed (VALUES with a
  new id). N2 (Late-payment Charge snapshot UPDATE and DELETE): fixed in the two-Signer test.
  N3 (wording "another Property"; the traceability count): fixed.

### Security review: 0 blockers, 0 should-fix, 4 notes

Round-1 fix and the written answers verified (one Property per database:
`properties_singleton_key_unique`; a non-human active account cannot exist). Deny-by-default,
no Staff or one-call path, stale and owner-written drafts, replay, kept Deposit and open-debt
rules, lock order, READ COMMITTED, no injection or data leak re-checked; no tightening beyond the
owner answers.

- N1: a second detected deadlock pair (the Lease forfeiture confirm takes the per-Deposit draft
  lock, then the Lease row); docs/010 choice (1) said one inversion. Fixed in the wording; no code
  change (the Settlement confirm would be refused anyway by that pending forfeiture draft).
- N2: as independent N2 (fixed).
- N3: the deferred reconciliation re-runs per snapshot row; added to the owner item (answer 15).
- N4: a server whose default isolation is not READ COMMITTED would see every confirm as a
  conflict; answered in docs/010 (the service never changes the default).

Round 2 has no blocker and 2 should-fix (both independent, both tests), so the standing rule
allows one round 3 after the full backend unit and PostgreSQL runs.

## Runs before round 3

Static checks (separate commands): `ruff format`, `ruff check src tests` and the migration
(clean), `ruff format --check src tests`, `mypy` (no issues in 294 source files). Read-only search
before U3 and P5: since P4 only the new test module, docs, traceability and this record changed;
migration 94 unchanged. Migration-only check before P5: exit 0.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U3 | backend unit, full | 3477 passed, 1701 skipped, 1 warning (Starlette) | standing rule before round 3 | `V1-056-slice-08e3-unit-test-run-3.txt` |
| P5 | PostgreSQL, full | 1864 passed, 1 warning (Starlette) | standing rule before round 3 | `V1-056-slice-08e3-full-test-run-5.txt` |

## Round 3 (2026-10-06, standing round-3 rule)

### Independent review: 0 blockers, 0 should-fix, 5 notes

Every round-2 fix verified (second approver named on every written record, the preparer in the
closure snapshot; the move-out corrected after the start proves "current"; the Late-payment Charge
snapshot UPDATE and DELETE refused; the VALUES insert; wording); final sweep of the owner rules,
Deposits and debt, clock independence of every fixture, the changed fixtures, revision assertions,
traceability (17 appended) and error mapping found nothing. Notes: N1 the snapshot-insert test
asserts only 23514, not the insert check's message; N2 no failing case for the line-snapshot
insert check, the line CHECK and the Charge-snapshot amount check (a second layer: no role may
write these tables); N3 a Charge snapshot's `included_by` is not asserted under a second approver;
N4 rule-ID headings (taken: this record, the docs/010 heading; the migration docstring stays as
run); N5 docs/004 said "each snapshot row" starts the deferred check (taken). N1 to N3 are slice
12 items.

### Security review: 0 blockers, 0 should-fix, 0 notes

Verified that since round 2 only the new test module, docs/010, this record and traceability
changed (migration 94 and `final_settlement.py` byte-identical), the round-2 fixes, and a full
sweep: deny-by-default, no Staff or one-call path (the only `UPDATE app.final_settlements` is the
confirm), stale or owner-written drafts, replay, kept Deposit and open-debt rules, lock order and
races, READ COMMITTED, no injection or data leak, error mapping, no tightening beyond the owner
answers.

### Outcome

Round 3 has no blocker and no should-fix, so 8e-3 is committed under the standing round-3 rule.
After round 3 only documents changed (docs/004 wording, docs/010 heading and round-3 entry, the
plan's slice 12 and 11e notes, this record, ops/NOW.md); the committed migration, code and tests
are exactly what U3 and P5 ran. Final runs: U3 backend unit 3477 passed; P5 full PostgreSQL 1864
passed. Corrections used: stale-test plan arithmetic 1 of 2, single test Property 1 of 2,
departed rate slot 1 of 2. All run outputs are small (at most 200 KB) and committed; nothing was
moved to `~/Development/prm-run-logs/` for 8e-3.

## Follow-up after the 8e-3 report (2026-10-06): owner answer on the hand-back months

Owner: leave it out, as recommended; the answer also covers next month's Rent Invoice VOIDed by
the hand-back resolution after a hand-back between the 25th and the month end (slice 5); a month
VOIDed for any other reason still blocks; a test for both cases. The committed rule already leaves
out every month whose Rent Invoice a hand-back resolution VOIDed, whatever its coverage, so no code
changed. Added `test_a_next_month_voided_by_the_hand_back_rule_does_not_block` (hand-back on 26
August, termination dated 10 September, so the billing rule counts September as billable; the
resolution VOIDs it; it does not block) and
`test_a_month_voided_for_another_reason_still_blocks_after_a_hand_back` (the hand-back month and
next month VOIDed by a plain staff VOID instead; each blocks with `RENT_PERIOD_NOT_BILLED`); two
traceability entries appended; docs/010 and the questions file record the answer.

Static checks (separate commands): `ruff format` (the new tests reformatted), `ruff check src
tests` (clean), `ruff format --check src tests` (294 files formatted), `mypy` (no issues in 294
source files). Read-only search: no code or migration changed; only the two new tests are
affected, and each uses its own temporary database. Migration-only check before P6: exit 0.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U4 | backend unit, full | 3477 passed, 1703 skipped, 1 warning (Starlette) | owner follow-up (traceability) | `V1-056-slice-08e3-unit-test-run-4.txt` |
| P6 | PostgreSQL, full | 1866 passed, 3 warnings | owner follow-up | `V1-056-slice-08e3-full-test-run-6.txt` |

The P6 warnings are the Starlette deprecation and the known intermittent pydantic warning in two
`test_credit_refund_api_migration.py` tests (slice 12 item).

Independent review (fresh read-only reviewer, tests and documents only, so no security review):
0 blockers, 0 should-fix, 4 notes. It confirmed that September is billable only through the
early-final-month rule, that the plain VOID writes no resolution, and that an exclusion of any
VOIDed month or of the hand-back month only would fail one of the tests. Notes: three test
additions (slice 12 list in the plan) and the docs/004 wording (taken). The committed tests are
exactly what P6 ran.
