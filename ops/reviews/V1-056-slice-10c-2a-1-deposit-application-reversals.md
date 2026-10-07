# V1-056 sub-slice 10c-2a-1 — Deposit application reversals: review record

Sub-slice: 10c-2a-1 (migration `20261105_101`). Base commit: e3ff722 (the 10c-2 split and
Q-2026-10-07-42 recorded).
Rule IDs: BR-SETTLE-013, BR-SETTLE-012, BR-SETTLE-009, BR-LEDGER-003, BR-AUTH-010; DB-DEP-006,
DB-SETTLE-005, DB-DER-004, DB-DER-010; owner answer 2 to Q-2026-10-06-36 and the owner answers to
Q-2026-10-07-41.

## Before the build

- Owner answers to Q-2026-10-07-41 recorded (docs/010, questions file; f6cd81c). Applying answers
  1 and 4 found two conflicts, written as Q-2026-10-07-42 with recommendations; it blocks
  10c-2a-2, 10c-2a-3 and 10c-2b, not 10c-2a-1 (the reversal record and its readers depend on
  none of its points), as 10a was built while Q-37 was open. 10c-2a split into 10c-2a-1, -2, -3
  (a split needs no owner answer).
- Pre-code design in the plan (10c entry, "10c-2a-1 pre-code design"), read only: the head
  `20261104_100` dumped from a throwaway database in the session scratchpad (598 functions, 517
  triggers, 10 views); every function and view that reads `app.deposit_applications` listed and
  sorted into readers that must ignore reversed applications and readers that must not.
- Long documents edited only with exact-text edits; `git diff --stat` checked after each edit.

## Built

- Migration `20261105_101`: `app.deposit_application_reversals` (DB-DEP-006; append-only; no role
  access; BEFORE INSERT check; deferred status refresh); DB-SETTLE-005 link
  `deposit_application_reversal_id` with the one-link check and the two link functions rebuilt
  (the 10b pattern, all 16 earlier links kept); "not reversed" in `invoice_line_deposit_value_at`
  (as of its time), `deposit_balance_events`, `deposit_snapshot`,
  `late_payment_charge_application_summary` and the 8a-1 refusal; the reversal time in
  `allocation_target_latest_at`; the ledger event `DEPOSIT_APPLICATION_REVERSED` (order 76) and
  its page filter; the bounded Deposit history read `app.deposit_application_reversal_history`
  (runtime EXECUTE only).
- Application and frontend: `customer_ledger.py` and `customerLedgerClient.ts` event kind,
  `deposit_api.py` Deposit history rows `APPLICATION_REVERSAL_*`.
- Tests: new module `test_deposit_application_reversal_migration.py` (4 tests, last in
  `scripts/database-test.sh`); traceability 4 entries appended; 26 head-revision assertions in
  14 modules; two narrowed count expectations (`test_customer_ledger.py`, TEST-FE-564).
- Docs: docs/004 (DB-DEP-005 pointer, DB-DEP-006 as built, DB-SETTLE-005 link, DB-DER-010 event),
  docs/005 (ledger kind, Deposit history rows), docs/006 (labels), docs/010 (entry, updated
  tests), the plan, the questions file (Q-42 wording corrected after round 1).

New check named for the owner (10b answer 2): only the BEFORE INSERT check of the new table; it
refuses nothing anyone could do before (no role can write the table and no writer exists).

## Runs before review round 1

Static checks, each in its own tool call: backend `ruff format` (new and edited files), `ruff
check` (2 long lines and 2 invalid suppression comments in the new test, fixed by hand, then
clean), `ruff format --check` (306 files), `mypy` on the changed files (one return type in a test
helper, fixed, then clean); frontend prettier on the two edited files, `npm run lint`, `npm run
format:check`, `npm run typecheck`. One slip: the frontend `format:check` call also ran a `grep`
of package.json and piped its output to `tail` in the same tool call (not two checks; recorded
because the run rule asks for one command per call). Migration-only check before P1 (owner
rule; the throwaway copy regenerated after the suite list changed): reached `20261105_101`.
Read-only search of all backend tests: the head-revision assertions, the two event-kind counts,
the ledger-view and catalog tests (the ledger page keeps its attributes and privileges; the
event-order map gains the kind; no whole-catalog list is affected).

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| F1 | frontend, full | 1592 passed | first run of 10c-2a-1 (ledger label) | `V1-056-slice-10c-2a-1-frontend-test-run.txt` |
| U1 | backend unit, full | 3589 passed, 1748 skipped, 1 warning (Starlette) | first run of 10c-2a-1 | `V1-056-slice-10c-2a-1-unit-test-run.txt` |
| P1 | PostgreSQL, full | 1 failed, 1910 passed, 2 warnings (Starlette; Pydantic alias, slice 12 item) | first run of 10c-2a-1 | `V1-056-slice-10c-2a-1-full-test-run.txt` |
| P2 | PostgreSQL, full | 1911 passed, 1 warning (Starlette) | after correction 1 of cause A | `V1-056-slice-10c-2a-1-full-test-run-2.txt` |

Cause A (test expectation, correction 1 of 2): TRUNCATE of the new table is refused by
PostgreSQL itself (0A000, "cannot truncate a table referenced in a foreign key constraint")
because the correction link refers to it, before the no-truncate trigger runs; the refusal is
right, the expected error was wrong.

## Round 1 (2026-10-07)

Fresh read-only subagents (independent and security), given the diff, the new files, the rule IDs,
the takeover rules and the design note; neither edited anything or ran a test.

### Independent review: 0 blockers, 3 should-fix, 8 notes

- SF1 (the reversal's time is checked less strictly than every similar record: no lock, no
  "later than the latest event" of the target or the Deposit, so a reversal could be dated before
  a later Payment allocation and rewrite past balances): fixed; the check locks the Deposit
  (`app.serialize_deposit_state`) and then the Invoice or Charge
  (`app.lock_payment_allocation_target`), and needs `occurred_at` later than
  `app.allocation_target_latest_at` and `app.deposit_balance_latest_at` and not before the
  correction, as the Deposit application's check (migration 86); tests for each bound.
- SF2 (the Late-payment Charge branch of the relaxed 8a-1 refusal is untested): fixed; test 3 adds
  a linked Late-payment Charge correction refused (P4603) while the application is active and
  accepted once the same correction reversed it.
- SF3 (the later writers were named as 10c-2a-3 and 10d; 10d writes Deposit applications and 10e
  reverses them): fixed in the migration docstring, docs/004 and docs/010 (10c-2a-3 and 10e).
- N (no Invoice status refresh; a stored status could stay stale until a writer refreshes it):
  taken; a deferred trigger refreshes the reversed line's Invoice status and version at commit, as
  the application's own trigger does (docs/010 choice 5 changed); test 1 asserts UNPAID and a new
  version.
- N (Q-42 described 10c-2a-1 with "an internal writer" and "Invoice status" readers): fixed; the
  Q-42 sentence is corrected in place, marked "corrected after review round 1".
- N (the "before the application" bound cannot be reached on its own): answered; it is covered by
  the target and Deposit latest-event bounds (the application is an event of both); the closure
  bound is implied by the correction bound (corrected after round 2: the earlier text named the
  closure bound).
- N (the reason check is weaker than the application's): fixed; `app.lease_notice_text_valid`
  (22023), tested with a leading no-break space.
- N (the ledger filter and the runtime ledger read are not exercised; no case with different
  Customers for the Deposit and the Invoice): the filtered read is now tested; the two-Customer
  case is answered: the components are those of `DEPOSIT_APPLIED` (8a-2 tests both cases) with the
  opposite effect.
- N (BR-LEDGER-003 missing from traceability): added to test 1.
- N (docs gaps: DB-DEP-005's 8a-1 bullet, the receipt reversal no longer held back, a receipt
  reversal draft after closure): fixed (docs/004 pointer and DB-DEP-006 text) and a plan note for
  10c-2a-3 or 10e.
- N (an unreachable `SET CONSTRAINTS ALL IMMEDIATE` in test 1): removed.

### Security review: 0 blockers, 1 should-fix, 5 notes

- SF (the same as independent SF1, also: not before the correction header, and the Deposit and
  target serialization guards not advanced): fixed as SF1 above.
- N1 (the relaxed 8a-1 refusal passes an obligation whose applications are reversed by any
  correction, not only the same one; safe because the 8e-1 refusal still needs a link to a
  correction confirmed in the same transaction): answered; docs/010 choice 3 states it.
- N2 (a reversal dated up to 5 seconds ahead counts in current reads at once and in "as of now"
  reads later; the same as Deposit applications, and conservative): no change.
- N3 (for the writers and 10h: status refresh, receipt reversal draft): the status refresh is now
  the table's own; the receipt reversal note is in the plan.
- N4 (test gaps: unknown application, NULL actor, a second Deposit in the history read): the
  unknown application is tested (23503); a NULL actor is refused by the trigger itself (23514,
  `NULL IS DISTINCT FROM` the approver; corrected after round 2, NOT NULL is checked after BEFORE
  triggers); the history read's Property scope is tested with an unknown Property.
- N5 (`search_path=pg_catalog` without `pg_temp`): the existing convention; slice 12 hardening item
  already lists it.

## Runs after the round-1 fixes

Static checks, each in its own tool call: `ruff format` (test reformatted), `ruff check` (clean),
`ruff format --check` (306 files), `mypy` (no issues). Migration-only check before P2 (after cause
A), before P3 and before P4: reached `20261105_101`. Read-only search: since P2 the migration gained the locks, the time
bounds, the reason check and the deferred refresh, the new module gained tests, traceability and
docs changed; no reversal exists outside the new module, so no other test is affected.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U2 | backend unit, full | 3589 passed, 1748 skipped, 1 warning (Starlette) | round-1 fixes (traceability) | `V1-056-slice-10c-2a-1-unit-test-run-2.txt` |
| P3 | PostgreSQL, full | 2 failed, 1909 passed, 1 warning (Starlette) | round-1 fixes | `V1-056-slice-10c-2a-1-full-test-run-3.txt` |
| P4 | PostgreSQL, full | 1911 passed, 2 warnings (Starlette; Pydantic alias, slice 12 item) | after correction 1 of causes B and C | `V1-056-slice-10c-2a-1-full-test-run-4.txt` |

Cause B (test query, correction 1 of 2): the new chronology test read
`payment_allocations.invoice_line_id`, which does not exist (allocations name the Invoice);
42703. Cause C (test list, correction 1 of 2): the forward-only test's list of new functions
lacked the new deferred refresh function. Both were test mistakes; the migration did not change.

Corrections used: cause A 1 of 2, cause B 1 of 2, cause C 1 of 2.

## Round 2 (2026-10-07)

Fresh read-only subagents again (the diff, the new files, this record); neither edited anything
or ran a test. Both verified every round-1 fix and answer; the migration code holds.

### Independent review: 0 blockers, 1 should-fix, 5 notes

- SF (the "later than the target's latest event" test did not prove that bound: the Payment
  allocation was posted before the correction began, so the "not before the correction" bound
  refused the reversal too; removing the target bound left the suite green; this record said
  "tests for each bound"): fixed; the allocation is now posted (committed from another connection)
  after `begin` inside the open correction transaction, the test asserts it is later than the
  correction header, and the reversal dated at it is refused; only the target bound can refuse it.
- N1 (the closure case is also refused by the correction bound; the application bound is covered
  by the latest-event bounds): text corrected above.
- N2 (a NULL actor is refused by the trigger, not by NOT NULL): text corrected above.
- N3 (no migration-only check recorded before P2): it was run before P2; the record now says so.
- N4 (TRUNCATE is refused by the foreign key first; the no-truncate trigger is only checked for
  existence): no change; the trigger stays as the table's own guard.
- N5 (the plan's test list still named a "before the application" refusal): fixed (plan).

### Security review: 0 blockers, 1 should-fix, 5 notes

- SF (the same as independent SF): fixed as above.
- N (a NULL `occurred_at` passes every time bound in the trigger and fails only at NOT NULL):
  taken; the trigger refuses it itself.
- N (an Adjustment, VOID or Late-payment Charge correction that follows a reversal on the same
  obligation has time checks that count Payment and Credit records but not Deposit applications or
  reversals): plan note for the writers (10c-2a-3, 10e): date reversals from the clock (as the
  bounds allow) or add Deposit records to those checks.
- N (no test that an unlinked one-call change is still refused after a reversal): fixed; test 3
  shows a one-call credit Adjustment of the now Deposit-free Invoice refused with the 8e-1 P5S01.
- N (the Deposit receipt reversal draft after closure once every application is reversed): already
  a plan note; it must be closed in 10c-2a-3 or 10e.
- N (the 10c-1a and 10c-1b planners still refuse any Deposit-paid Invoice, reversed or not): by
  design until 10c-2a-3.

## Runs before round 3 (standing rule)

Static checks, each in its own tool call: `ruff format` (test reformatted), `ruff check` (clean),
`ruff format --check` (306 files), `mypy` on the changed files (no issues). Migration-only check
before P5: reached `20261105_101`. Read-only search: since P4 only the migration's NULL time
guard, the new module's tests, traceability, the plan and this record changed; no other test is
affected.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U3 | backend unit, full | 3589 passed, 1748 skipped, 1 warning (Starlette) | standing rule before round 3 (round-2 fixes) | `V1-056-slice-10c-2a-1-unit-test-run-3.txt` |
| P5 | PostgreSQL, full | 1911 passed, 2 warnings (Starlette; Pydantic alias, slice 12 item) | standing rule before round 3 (round-2 fixes) | `V1-056-slice-10c-2a-1-full-test-run-5.txt` |

No run failed.

## Round 3 (2026-10-07, standing rule)

Fresh read-only subagents again; neither edited anything or ran a test. Both verified every
round-1 and round-2 fix and answer.

### Independent review: 0 blockers, 0 should-fix, 5 notes

- N (the plan's pre-code test bullet still lists a "before the application" refusal): fixed
  (text; the bullet now points to the as-built list).
- N (the NULL time guard is untested; removing it only changes 23514 to 23502): no change.
- N (no test exercises the Deposit and target locks; as the Deposit application precedent): plan
  note for the writers (keep the lock order) already present.
- N (the closure-bound case is also refused by the correction bound): already stated above.
- N (no frontend production build recorded): `npm run build` run once before the commit; built
  (the existing chunk-size warning only).

### Security review: 0 blockers, 0 should-fix, 4 notes

- N1 (NULL time and NULL actor refusals untested; NOT NULL refuses both anyway): no change.
- N2 (the closure and "not before the application" bounds only back up the others): already
  stated above.
- N3 (the check accepts a reversal linked to any type of correction of the Settlement, as every
  10a link does; the writers must make sure the confirmed draft describes the reversal): plan note
  for 10c-2a-3 and 10e.
- N4 (once a writer exists, a Deposit can hold money after closure; besides the receipt reversal
  draft, the writers should confirm that no other one-call outflow, such as a Pet Refund-review
  Refund or a Lease forfeiture, can take that amount without a correction): plan note for
  10c-2a-3 and 10e.

Result: no blocker and no should-fix, so 10c-2a-1 is committed under the standing round-3 rule.
After round 3 only text changed (this record, the plan and docs/010) and the frontend build ran;
the migration, application code, tests and manifest are exactly what U3 and P5 ran.
