# V1-056 sub-slice 8g — One-call reversal refused for a Credit released to another Customer: review record

Sub-slice: 8g (migration `20261031_96`). Base commit: 6dc4f9d (the 8f checkpoint line).
Rule IDs: BR-CREDIT-014, BR-CREDIT-008, BR-AUTH-010; DB-CREDIT-004; owner answer to
Q-2026-10-06-35 (approved tightening).

## Before the build

- Read in order: AGENTS.md, ops/NOW.md, ops/V1_055_RUN_RULES.md, ops/V1_056_TAKEOVER.md,
  ops/V1_056_PLAN.md, ops/V1_056_QUESTIONS.md (Q-18, Q-19, Q-35), the 8f review record and the
  V1-056 notes in docs/010. Start state checked: tree clean, HEAD 6dc4f9d.
- Owner answers to the 8f report recorded first (docs/010, ops/V1_056_QUESTIONS.md Q-35) and the
  new run rule added (ops/V1_055_RUN_RULES.md: one static check per tool call).
- Read-only reading: the only writer of `app.customer_credit_reversals` is
  `app.reverse_customer_credit` (migration 41); the BEFORE INSERT triggers on that table are
  `customer_credit_reversals_moved_payment` (slice 7, no lock) and
  `customer_credit_reversals_validate` (migration 41, locks the Payment and the Credit);
  `app.payments.payer_customer_id` is NOT NULL, so `app.credit_customer_refund_basis` (8f) is NULL
  exactly for the Credits 8f does not cover.
- Read-only search of all backend tests for affected tests: every test that reverses a Credit
  (14 modules; `ReverseCreditCommand`, `app.reverse_customer_credit`, `customer_credit_reversals`,
  the reversal routes). Only `test_payment_move_migration.py` reverses an adjustment Credit of a
  Customer other than the payer, always a moved one, which the slice 7 trigger already refuses
  first (unchanged result); the third-party fixtures in `test_credit_adjustment_excess_migration.py`,
  `test_customer_ledger_migration.py` and `test_financial_action_context_migration.py` never
  reverse their Credit. No test asserts the old service message. Trigger-listing tests name other
  tables only. The 26 head-revision assertions in 14 modules move to `20261031_96`.

## Built

- Migration `20261031_96`: `app.validate_credit_customer_credit_reversal()` (SECURITY DEFINER,
  `search_path=pg_catalog`, no grant) and the BEFORE INSERT trigger
  `customer_credit_reversals_other_customer`: refuses with `P4904` when
  `app.credit_customer_refund_basis(NEW.customer_credit_id)` is not NULL. Forward-only.
- `credit.py`: the `P4904` conflict message now covers both refusals.
- Tests: `test_credit_customer_credit_reversal_migration.py` (4, last in
  `scripts/database-test.sh`), `test_credit_customer_credit_reversal.py` (1 unit test); 5
  traceability entries appended; 26 head-revision assertions; docs/004 DB-CREDIT-004, docs/010,
  the plan (8g entry, slice 10 item for a mistaken credit Adjustment, slice 12 lasting-block item,
  11c/11e note), ops/V1_056_QUESTIONS.md, ops/V1_055_RUN_RULES.md.

Static checks, each in its own tool call: `ruff format` on the four changed backend files (two
reformatted); `ruff check src tests` and the migration (clean); `ruff format --check src tests`
(298 files already formatted); `mypy` (no issues in 298 source files).

Migration-only check before P1 (owner rule): a throwaway copy of `scripts/database-test.sh` in the
session scratchpad runs `alembic upgrade head` on a fresh container; it reached `20261031_96`.

## Runs before review round 1

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U1 | backend unit, full | 3498 passed, 1715 skipped, 1 warning (Starlette) | first run of 8g | `V1-056-slice-08g-unit-test-run.txt` |
| P1 | PostgreSQL, full (`./scripts/database-test.sh`) | 1878 passed, 2 warnings | first run of 8g | `V1-056-slice-08g-full-test-run.txt` |

The second P1 warning is the known intermittent pydantic `UnsupportedFieldAttributeWarning` in
`test_credit_refund_api_migration.py::test_credit_refund_competition_fixture_isolates_unrelated_shared_writer`
(slice 12 item); recorded, not hidden. No correction used.

## Round 1 (2026-10-06)

Both reviewers were fresh read-only subagents given the combined diff, the rule IDs, the takeover
file, the plan's 8g entry and the owner answer; neither edited anything or ran a test.

### Independent review: 0 blockers, 2 should-fix, 6 notes

Confirmed sound: the trigger uses exactly the 8f predicate, so no Credit outside 8f's set is
refused and none inside it is missed; the only writer; grants, definer rights and `search_path`;
no lock needed (immutable inputs); trigger order (tests 3 and 4); each test fails if the trigger is
removed or misplaced; no real-clock values; no earlier test affected; 26 head-revision assertions;
traceability; the Payment-reversal consequence; BR-INV-044; `invoice_adjustment_reversals` has no
writer.

- SF1: the "two one-call ways" to fix a mistaken credit Adjustment were only partly true: the
  second way needs a replacement allocation the one-call reversal accepts (a moved
  `WRONG_UNIT_MOVE` replacement is refused, P4904; none exists when the whole allocation was
  released, and the debit Adjustment is then refused, P4509). Fixed: docs/010 8g entry and the plan
  now say one way works in general and the second only in part, with its limits.
- SF2: `POST /customer-credits/{credit_id}/reverse` now answers 409 for more Credits and docs/005
  did not describe the route or the slice 7 409. Fixed: one amendment under API-062 covering both.
- N3 "recognition checks" is the wrong name for `customer_credit_reversals_validate`: fixed
  ("Credit reversal checks") in the migration docstring, the test comment, docs/004, docs/010, the
  plan and the new traceability entry.
- N4 the slice 10 addition overstated the slice 7 refusal and did not cover Credit-application
  releases or several releases: fixed (plan slice 10).
- N5 the docs/010 consequence understated the block: fixed (no path reverses such a Credit after
  8g; blocked until a controlled path exists).
- N6 the unit test repeats the slice 7 unit test except for the message assertion: answered; kept,
  because the new message is what 8g changes in the service.
- N7 the plan's 8g bullet lacked BR-AUTH-010: fixed.
- N8 security review: answered; it ran in parallel (below).

### Security review: 0 blockers, 0 should-fix, 4 notes

Main answer: after 8g no value of such a Credit reaches the payer or any Customer other than the
Credit's Customer without a draft confirmed by `financial.approve`. Paths checked: Credit reversal,
basis coverage (only two Credit writers; `payer_customer_id` NOT NULL), ordinary and Settlement
Credit applications, Credit application reversals and their releases, credit and debit Adjustments,
replacement allocation reversal, Payment reversal, every Refund draft variant, Refund corrections
and verified returns, Payment move drafts, Deposit receipts, the Final Settlement writers, direct
table writes and role rights, `search_path`, grants, error text, the payer's own Credits.

- N1 the lasting block of a third-party Payment with such a Credit: recorded in docs/010 and the
  plan's slice 12 item; named in the 8g report for the owner; the slice 10 design raises it.
- N2 "recognition checks" wording: fixed (as independent N3).
- N3 migration 96 does not look for a covered Credit reversed before 8g: answered; no persistent
  database exists (docs/010, 2026-10-03; the first real `make migrate` is V1-059) and nothing is
  published, so migrations 67 to 96 are always applied together and no such reversal can exist.
- N4 test gaps: answered. The basis does not read the Payment's scope, so a non-moved
  third-party adjustment Credit whose Customer is the payer takes the same branch as the normal
  Payment case of test 2 (basis NULL, reversal allowed; such a Credit is outside the owner answer);
  a separate test would add no branch. The 409 is covered in two steps: the new unit test (P4904
  to `CreditConflictError`) and `test_credit_refund_api.py` (`CreditConflictError` to 409); a
  route test with a real database can come with the 11c and 11e screens.

## After the round-1 fixes

Only text changed: docs (004, 005, 010), the plan, this record, one traceability note, the
migration docstring and one test comment. No executable line changed, so no test run (the run rules
allow a rerun only after a real correction). Static checks, each in its own tool call: `ruff
format` on the two edited Python files (unchanged), `ruff check src tests` and the migration
(clean), `ruff format --check src tests` (298 files already formatted), `mypy` (no issues in 298
source files).

## Round 2 (2026-10-06)

Fresh read-only reviewers again (the full diff, the round-1-to-2 diff, this record, the owner
answer); neither edited anything or ran a test.

### Independent review: 0 blockers, 0 should-fix, 3 notes

Every round-1 fix and answer verified against the code: the 8f predicate, the one writer, definer
rights, no lock needed, trigger order, replay, forward-only; SF1 (replacement allocation only when
value remains, line exactly fully paid after a release, moved allocation and move draft refusals,
8e-1 after closure); SF2 and the docs/005 paragraph; N3 and N4; the tests; 26 head-revision
assertions; traceability; text-only changes since U1 and P1.

- N1 the plan's 8g "Consequence" bullet was weaker than docs/010: fixed (same wording).
- N2 this record pointed to a plan note on an HTTP 409 test that does not exist: fixed (the 409 is
  covered by the unit test and `test_credit_refund_api.py`; a real-database route test can come
  with 11c and 11e).
- N3 "one one-call way" is several ordinary commands without a draft; docs/005 could point to the
  missing `CREDIT_CUSTOMER` record route: fixed (docs/010, the plan, docs/005 now refers to
  API-065).

### Security review: 0 blockers, 0 should-fix, 3 notes

Independent path search (Credit reversal; bypass by roles, schema, triggers; trigger order and
NEW; basis coverage fixed at Credit creation; every Credit application kind; application
reversals and releases; every Refund kind and the deferred check; verified returns; the payer's
Payment Refund; Payment reversal; Payment move drafts; replacement allocation reversal; VOID;
`invoice_adjustment_reversals`; Deposits; error text and logs; grants, definer rights and
`search_path`; the payer's own Credits): the value of such a Credit goes only to that Customer's
obligations, a Final Settlement Credit application of that Customer, or a `CREDIT_CUSTOMER`
Refund to that Customer confirmed under `financial.approve`. Round-1 answers N3 and N4 agreed.

- N1 docs/005 cross-reference to the missing record route: fixed (as independent N3).
- N2 the lasting block of a third-party Payment stays named for the owner in the 8g report.
- N3 the round-1 N3 answer rests on an operational fact: if a database were ever built at a
  revision between 67 and 95 and used before 96, a one-off read-only query would be needed to find
  earlier reversals of covered Credits. Answered: 96 is the head in this commit and no persistent
  database exists; recorded here.

### Outcome

Round 2 has no blocker and no should-fix, so 8g is committed without a round 3. After round 2
only text changed (docs/005, docs/010, the plan, this record); the migration, code and tests are
exactly what U1 and P1 ran except the migration docstring and one test comment changed after
round 1 (text only, re-checked by `ruff` and `mypy`). Final runs: U1 backend unit 3498 passed; P1
full PostgreSQL 1878 passed. Corrections used: none. Run outputs are small (unit about 140 KB,
PostgreSQL 11 KB) and committed; nothing moved to `~/Development/prm-run-logs/`.
