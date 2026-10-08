# V1-056 sub-slice 10c-2a-5 — Pet classification correction after closure: review record

Sub-slice: 10c-2a-5 (migration `20261109_105`). Base commit: 37338ca (the 10c-2a-4 checkpoint in
ops/NOW.md). Not committed (commit hash in ops/NOW.md once committed).

Rule IDs: DL-032, BR-SETTLE-008, BR-SETTLE-012, BR-SETTLE-013, BR-DEP-027, BR-AUTH-010;
DB-SETTLE-005, DB-SETTLE-007 (new); owner answer to Q-2026-10-07-45 (option (a)), answer 3 to
Q-2026-10-07-44.

## Built

- Migration `20261109_105`: new append-only table `app.settlement_pet_classifications`
  (DB-SETTLE-007) with its BEFORE INSERT check; DB-SETTLE-005 link
  `settlement_pet_classification_id` (link functions rebuilt); `app.invoice_line_is_pet_damage`
  reads the line's latest classification record before the inspection rule; the step's plan check
  takes an overlay key `pet_damage` (exact-text patch); the lock function takes the line's Invoice
  `FOR UPDATE` for the new variant (exact-text patch); recorder
  `app.record_settlement_pet_classification_draft` (`final_settlements.prepare`) and confirm
  `app.confirm_settlement_pet_classification` (`financial.approve`), both granted to the
  financial role only; internal input, line, reversal, source-state, plan, overlay and result
  functions without grants.
- Service: `RecordPetClassificationCorrectionCommand`,
  `SettlementCorrectionService.record_pet_classification` and `confirm_pet_classification`
  (P5S02 stale).
- Tests: new module `test_settlement_pet_classification_migration.py` (9 tests at P1 and P2, 10
  at P3 after review round 1, 11 after review round 2; last in `scripts/database-test.sh`), three
  unit tests in `test_settlement_correction.py` (16 cases), 26 head-revision assertions in 14
  modules, traceability 12 entries at P1, 13 after round 1, 14 after round 2.
- Docs: docs/002 BR-SETTLE-013 "Amended by" line; docs/004 DB-SETTLE-005 paragraph and the new
  DB-SETTLE-007 section; docs/010 sub-slice entry and updated tests entry; the plan's pre-code
  design.

## Runs

Static checks, each in its own tool call (`ruff format src tests`, `ruff check src tests`,
`ruff format --check src tests`, `mypy`): clean. Migration-only check (the throwaway copy of
`scripts/database-test.sh` in the session scratchpad running `uv run alembic upgrade head`)
reached `20261109_105 (head)`; the migration did not change afterwards. Read-only search of all
backend tests for the changed functions and the effects table: the correction modules of 10a,
10b, 10c-1a, 10c-1b, 10c-2a-1, 10c-2a-2, 10c-2a-3 (their head-time source checks count only
locks, intervals and `age(` calls the patches do not add), `test_final_settlement_migration.py`
(the reader keeps SECURITY DEFINER, its search path and grants), the 10c-2a-4 module, the new
module, the head-revision modules and traceability.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U1 | backend unit, full | 3606 passed, 1784 skipped, 1 warning (Starlette) | first run of 10c-2a-5 | `V1-056-slice-10c-2a-5-unit-test-run.txt` |
| P1 | PostgreSQL, full (under `caffeinate -dims`) | 2 failed, 1945 passed, 3 warnings | first run of 10c-2a-5 | `V1-056-slice-10c-2a-5-full-test-run.txt` |
| P2 | PostgreSQL, full (under `caffeinate -dims`) | 1947 passed, 2 warnings (Starlette; pydantic alias) | correction 1 of cause A | `V1-056-slice-10c-2a-5-full-test-run-2.txt` |

- Cause A (test plan amounts; correction 1 of 2 used): P1, two new tests. In the to-not-pet test
  the Customer's Credit (300) pays first, so the remaining Pet Deposit (12,500 back) paying 12,200
  left 300 held and the plan check refused it ("Every remaining Deposit balance must be applied or
  refunded"); the plan now refunds that 300. In the record-time refusal test a 12,200 Refund left
  300 held and was refused by the same check before the open-debt rule the test asserts; it now
  refunds the whole 12,500, so the open-debt rule decides. No product code changed. Passed in P2.
- No unit run after correction 1: only the PostgreSQL test module changed (skipped by the unit
  suite) and the traceability note of one test; static checks clean.

## Review round 1 (2026-10-08; fresh read-only subagents, given the diff, the rule IDs, the owner answers and the takeover file)

Independent: 0 blockers, 3 should-fix, 5 notes. Security: 0 blockers, 2 should-fix, 4 notes.

- Chronology (independent SF1, security N1; fixed): "the latest record decides" had no guard; the
  insert check now refuses a record dated at or before the line's latest record, and the confirm
  dates the record after it. Tested (a hand-built record at the latest record's time refused).
- Draft binding (security S1, independent N1; fixed): the insert check now needs the effect row of
  its own correction and exactly the draft's line, classification, evidence and reason
  (`PET_DAMAGE_RECLASSIFICATION` draft). New test
  `test_a_classification_record_is_written_only_as_its_own_draft_prepared_it` (as prepared
  accepted; unlinked, another line, classification, evidence, reason or person, a time before the
  correction or at the latest record refused, 23514; UPDATE and DELETE refused).
- Untested refusals (independent SF2; fixed in part): an open Settlement and a line of another
  Lease added to the refusals test. Not added: a VOID Invoice (after closure VOID is refused by
  8e-1, so a VOID Damage Invoice of a closed Lease needs a fixture VOIDed before closure; the same
  issued-Invoice check is tested in 10b, 10c-1a and 10c-1b) and a record linked to another
  Settlement's correction (the insert check needs `app.settlement_correction_linked` for the
  correction's own Settlement, its own effect row and the draft's line on that Settlement's Lease).
- Earlier correction's choice (independent SF3; fixed): the BR-DEP-027 test records a later
  correction with the same choice and expects the refusal.
- Choice reuse by two pending drafts (security S2, independent N2; fixed for this variant): the
  confirm checks the Customer choice again under the Settlement's draft lock; the BR-DEP-027 test
  records two drafts with the same new choice while both are pending, confirms the first and the
  second is refused (55000) and stays pending. The stale argument of the 10c-2a-3 record does not
  hold when the first correction leaves the balances unchanged (the independent reviewer's
  example). The committed `REFUND` confirm (10c-2a-3) has the same gap; not changed here (owner
  item in the report and NOW.md).
- DL-032 path (both notes; fixed): only a Pet Deposit on the DL-032 path counts as holding money
  for the to-pet-damage reversal.
- Superseded inspection (security N2; fixed conservatively): a line billed from an inspection
  superseded before closure is not eligible, so the owner's open point (carrying a finding
  forward) stays open; docs/010 choice (10).
- Lock test (independent N4; fixed): the least-privilege test checks the confirm's lock order in
  its source and the lock function's variant branch.
- Wording (independent N5; fixed): docs/010 choice (3) and the test docstring give the right
  reason for the open line at a BR-DEP-027 termination; the plan has an as-built line.
- Answered, not changed: the human-approver check is the shared pattern tested in 10b, 10c-1a
  and 10c-1b; security N4 (existing since 10c-2a-1 and 10c-2a-2: nothing at commit forces a
  correction that reverses a Deposit application to run the step, so a hand-built, owner-only
  correction can leave a Deposit holding money after closure; the to-pet-damage reversal branch
  is reachable only from such a state until 10c-2b or 10d) is an owner item.

After the fixes: static checks clean, each in its own call. The migration-only check (the
scratchpad copy regenerated from the current `scripts/database-test.sh`, whose list now names the
new module) failed twice before it reached `20261109_105 (head)`: cause B (my column names in the
DL-032 path condition: `app.deposits` and `app.leases` have no `property_id`; the Property now
comes from the Lease's Final Settlement); corrections 1 and 2 of 2 used. These are the cheap
migration checks, not test runs.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U2 | backend unit, full | 3606 passed, 1785 skipped, 1 warning (Starlette) | review round 1 fixes | `V1-056-slice-10c-2a-5-unit-test-run-2.txt` |
| P3 | PostgreSQL, full (under `caffeinate -dims`) | 1948 passed, 2 warnings (Starlette; pydantic alias) | review round 1 fixes | `V1-056-slice-10c-2a-5-full-test-run-3.txt` |

## Review round 2 (2026-10-08; new fresh read-only subagents, given the full diff, the rule IDs, the owner answers, the takeover file and this record)

Security: 0 blockers, 0 should-fix, 4 notes. Independent: 0 blockers, 2 should-fix, 5 notes. Two
should-fix in total, so one round 3 is allowed under the standing rule (owner, 2026-10-04), after
one full backend unit run and one full PostgreSQL run. STOPPED here at about 65% context: the
round-2 fixes are applied in the working tree and the static checks and the migration-only check
are clean, but there is no run after them and no round 3. Nothing committed.

- Independent SF1 (fixed, test only, not run): three insert-check assertions were refused by
  another clause (the line and classification attempts by the same-classification clause; the
  chronology attempt by the "not before the correction" clause), so the line binding, the
  classification binding and the chronology guard were not proven, nor the confirm's dating. The
  test now makes each attempt fail on its own clause only: a twin draft (pet damage) confirmed
  after the line became pet damage, with a not-pet record (classification binding); a not-pet
  record for the pet damage line under a draft that names the other line (line binding); a
  hand-built record dated 4.5 seconds ahead, committed, then a record dated now (chronology); and
  the confirm of a later draft whose record is dated after that one (the confirm's dating).
- Independent SF2 (fixed, test only, not run): new test
  `test_a_line_billed_from_an_inspection_superseded_before_closure_is_not_eligible` (the 10b
  set-up: the inspection superseded before closure, then the closure; a to-pet correction of the
  line refused with the eligibility message and no draft written).
- Independent N2 (fixed): the eligibility message now says "a finding of a current inspection"
  (migration and tests); docs/002 BR-SETTLE-013 names the excluded lines; owner item below.
- Independent N3 (fixed): docs/004 DB-SETTLE-005 paragraph names the DL-032 path condition; the
  DB-SETTLE-007 rows for `invoice_line_id` and `recorded_at` say "current inspection" and "later
  than the line's latest record". The section order (007 before 006) is left as written: 006 sits
  after the long DB-SETTLE-005 text; not changed.
- Independent N4 (fixed): this record's counts.
- Independent N5 (fixed): the least-privilege test pins the Customer choice re-check between the
  lock function call and the Refund method lock in the confirm's source.
- Independent N1 (answered): the DL-032 path condition is defence in depth; a kept Pet Deposit
  holds nothing after its forfeiture and a Deposit that still needs a forfeiture cannot survive
  closure, so no state reaches it today; no test.
- Security N1 (owner item): the committed `REFUND` confirm (10c-2a-3) does not re-check the
  Customer choice; a `PET_DAMAGE_RECLASSIFICATION` confirmed first that leaves the balances
  unchanged lets a `REFUND` draft with the same choice confirm. Suggested fix: move the re-check
  into `app.post_settlement_correction_plan` (all variants that use the step), a change to
  committed behaviour.
- Security N2 (owner item, defence in depth): the 10c-2a-1 Deposit application reversal check is
  not bound to the correction's draft list of reversals (`reversed_applications`,
  `released_sources`); only owner or definer code can write the table.
- Security N3 (owner decision): "a new Customer choice" is compared as exact text; a reworded
  earlier consent passes; a per-correction choice reference or a documented limit.
- Security N4 (optional, not done): the correction's audit event has an empty `previous_state`;
  the earlier classification can be rebuilt from the append-only table.

## Owner answers and runs after review round 2 (2026-10-08, new session)

The owner answered the six owner items of the report (Q-2026-10-08-52; docs/010): (1) the
Customer choice re-check of every correction confirm moves into the shared step, in sub-slice
10c-2a-6 right after this commit; (2) the reversal-check binding is a slice 12 item; (3) the
exact-text comparison is a known limit in docs/010; (4) the line billed from an inspection
superseded before closure is Q-2026-10-08-53 (open, answered before 10h; plan entry before 10h);
(5) whichever of 10c-2b and 10d first returns value to a Pet Deposit tests the to-pet reversal on
a real path (plan); (6) choices (1) and (3) confirmed. Text only (docs/010, questions, plan).

Before P4: static checks clean, each in its own tool call (`make backend-format-check`,
`make backend-lint`, `make backend-typecheck`); the migration-only check (a new throwaway copy of
`scripts/database-test.sh` in this session's scratchpad running `uv run --extra dev alembic
upgrade head`) reached `20261109_105 (head)` at the first attempt (104 upgrades), so cause B did
not recur; the read-only search of all backend tests for the eligibility message, the new table,
variant and functions, and the head revision found the 14 head-revision modules,
`test_final_settlement_migration.py`, the 10c-2a-2 and 10c-2a-4 modules, the new module and the
unit module; the message is asserted only in the new module.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U3 | backend unit, full (under `caffeinate -dims`) | 3606 passed, 1786 skipped (every skip a database URL reason), 1 warning (Starlette) | review round 2 fixes | `V1-056-slice-10c-2a-5-unit-test-run-3.txt` |
| P4 | PostgreSQL, full (under `caffeinate -dims`) | 1949 passed, 2 warnings (Starlette; pydantic alias in `test_credit_refund_api_migration.py`, the known slice 12 item) | review round 2 fixes | `V1-056-slice-10c-2a-5-full-test-run-4.txt` |

The new module ran 11 tests, all passed (the round-2 test included). No correction.

## Review round 3 (2026-10-08; new fresh read-only subagents, given the diff, the rule IDs, the owner answers, the takeover file and this record)

Under the standing round-3 rule (owner, 2026-10-04), after U3 and P4. Independent: 0 blockers, 0
should-fix, 2 notes. Security: 0 blockers, 0 should-fix, 2 notes. No should-fix, so 10c-2a-5 is
committed (hash in ops/NOW.md).

- Independent N1 (fixed, text only): the plan's as-built line and the ops/NOW.md line still said
  the round-2 fixes were not run; both now name U3, P4 and this round.
- Independent N2 (slice 12 item, not changed): the time-order part of
  `test_a_classification_record_is_written_only_as_its_own_draft_prepared_it` must finish within
  about 4.5 seconds of the record dated ahead; on a very slow host it could fail falsely, never
  pass falsely (as the 3-second lock timeout note of 10c-2a-4).
- Security N1 (slice 12 item, not changed): the `pet_damage` overlay loop of the plan check does
  not call the eligibility function; unreachable today (internal function; the recorder runs the
  eligibility check first; the step passes no `pet_damage` key and compares its whole result).
- Security N2 (slice 12 item, not changed): after a hand-built record dated ahead (up to the
  insert check's 5 seconds), the next confirm dates its record and audit event ahead too; only
  owner-written rows can be dated ahead.

Both reviewers confirmed: the round-2 fixes prove their clauses (each insert-check attempt fails
on its own clause only; the superseded-inspection test fails only on the exclusion), deny-by-default
grants, SECURITY DEFINER with a fixed search path on every new or replaced function, privileges
kept on the patched functions, no dynamic SQL, capability checks before any connection, the 8e-3
lock order, READ COMMITTED, replay and stale handling, cents only, append-only, and no historical
migration or committed test expectation changed apart from the 26 head-revision assertions.
