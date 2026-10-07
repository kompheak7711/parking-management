# V1-056 sub-slice 10c-2a-2 — the shared DL-032 step after closure: review record

Sub-slice: 10c-2a-2 (migration `20261106_102`). Base commit: 6861eec (the 10c-2a-1 checkpoint).
Rule IDs: DL-032, BR-SETTLE-004, BR-SETTLE-005, BR-SETTLE-006, BR-SETTLE-008, BR-SETTLE-013,
BR-SETTLE-017, BR-CREDIT-006, BR-CREDIT-008, BR-CREDIT-014, BR-DEP-027, BR-REFUND-014,
BR-REFUND-015, BR-AUTH-010; DB-SETTLE-005, DB-DEP-005, DB-CREDIT-002, DB-REFUND-001; owner answers 1
and 3 to Q-2026-10-07-41 and 1 and 2 to Q-2026-10-07-42.

## Before the build

- Owner answers to Q-2026-10-07-42 recorded (docs/010, questions file, plan: the "Owner answers to
  Q-2026-10-07-42" bullet of the 10c-2 design; 10c-1b changes in 10c-2a-3; a returned Deposit
  Refund goes back to the Deposit, 10c-2b).
- Pre-code design in the plan (10c entry, "10c-2a-2 pre-code design"), read only: the head
  `20261105_101` dumped from a throwaway database in the session scratchpad; the 8c plan check, the
  8d Deposit Refund source check and writer, the 8e-2 Credit application writer and checks, the 8e-3
  confirm (lock order and step writers), the 10a correction functions, the 10c-1b details table and
  the Deposit application check read in full.
- Long documents edited only with exact-text edits; `git diff --stat` checked after each edit.

## Built

- Migration `20261106_102`: `app.settlement_correction_plan_result` (the correction plan check
  with its overlay), `app.settlement_correction_overlay_amount`, `app.settlement_correction_credit_id`
  (plan key to Credit), `app.lock_settlement_correction_plan` (the step's locks),
  `app.post_settlement_correction_plan` (the step inside its correction),
  `app.post_settlement_correction_deposit_refund` and
  `app.assert_settlement_correction_deposit_refund_source` (a correction's Deposit Refund),
  `app.assert_settlement_correction_credit_application` and its deferred twin (a correction's
  Credit application); exact-text patches of the 8e-2 writer and its two checks, the Deposit
  application check, the 8d Deposit Refund source check and `app.settlement_correction_refund_allowed`;
  `settlement_correction_refund_details` gains `deposit_id` and `signer_agreement`. No grant.
- Tests: new module `test_settlement_correction_plan_migration.py` (7 tests after review round 1, last in
  `scripts/database-test.sh`); traceability 7 entries appended; 26 head-revision assertions in 14
  modules.
- Docs: docs/004 (DB-CREDIT-002, DB-DEP-005, DB-REFUND-001 as built, DB-SETTLE-005 step), docs/010
  (answers, entry with choices, updated tests), the plan, the questions file.

New check named for the owner (10b answer 2): none refuses anything anyone could do before; the
relaxed checks still refuse every record that is not a correction's own.

## Runs before review round 1

Static checks, each in its own tool call: `ruff format` (new files), `ruff check` (one slip: the
first call was `ruff check .`, wider than the Makefile's `src tests`; it flagged only E501 in old
migrations, which the repository's lint does not cover; then `ruff check src tests` clean),
`ruff format --check src tests` (306 files), `mypy` (no issues). Migration-only check before P1 and
before P2 (throwaway copy of `scripts/database-test.sh` in the session scratchpad): reached
`20261106_102`. Read-only search of all backend tests: the 26 head-revision assertions; the tests
that name the patched functions (`test_final_settlement_credit_application_migration.py`,
`test_final_settlement_refund_migration.py`, `test_settlement_refund_correction_migration.py`)
compare their own revisions or write details rows by column list, so the new nullable columns and
the unchanged Settlement paths do not affect them; no whole-catalog list is affected.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U1 | backend unit, full | 3589 passed, 1753 skipped, 1 warning (Starlette) | first run of 10c-2a-2 | `V1-056-slice-10c-2a-2-unit-test-run.txt` |
| P1 | PostgreSQL, full | 4 failed, 1912 passed, 1 warning (Starlette) | first run of 10c-2a-2 | `V1-056-slice-10c-2a-2-full-test-run.txt` |
| P2 | PostgreSQL, full | 1916 passed, 1 warning (Starlette) | after correction 1 of causes A and B | `V1-056-slice-10c-2a-2-full-test-run-2.txt` |

Cause A (migration, correction 1 of 2): the step links each record before it writes it (deferred
effect keys), but `app.adjust_invoice`, used by the tests' hand-built release, runs `SET
CONSTRAINTS ALL IMMEDIATE`, so the link key was checked at once (23503) in three tests. A variant may
call such an existing writer before the step, so the step now moves its own three link keys back to
commit (`SET CONSTRAINTS ... DEFERRED`, as the 8d and 8e-2 writers do their checks), and the Deposit
Refund writer does the same for its key; the tests' own direct links do the same. Cause B (test,
correction 1 of 2): the least-privilege test's text check for `age(` matched
`invoice_line_is_pet_damage(`; it now looks for a call of `age(` only (a regular expression).

Corrections used: cause A 1 of 2, cause B 1 of 2.

## Round 1 (2026-10-07)

Fresh read-only subagents (independent and security), given the migration, the new module, the
tracked diff, the rule IDs, the takeover rules and the design note; neither edited anything or ran a
test.

### Independent review: 0 blockers, 4 should-fix, 5 notes

- SF1 (R1, Credit before Deposits, applies only when a Deposit holds money, while the Settlement
  draft applies it always; the docs called it "the Settlement rule"): docs corrected (docs/010
  choice 5, the plan's R1 line); kept as built, because Q-42 answer 1 says "before released Deposit
  value pays open debt" and an unconditional rule would force a Credit-only correction to apply the
  Credit of Customers it does not concern; named for the owner (see "For the owner").
- SF2 (a correction's Deposit application is not tied to a step of its plan): fixed; the relaxed
  check needs a Deposit step of the correction's plan (Deposit, stage, target, amount), each step at
  most once (23514); tests for an off-plan application and a step used twice.
- SF3 (the relaxed checks are not proven to accept nothing else): fixed with tests: the deferred
  Credit check (the 8e-2 writer called twice for one step, refused at commit); the Deposit Refund
  check (details naming another Deposit, the Primary Tenant with an agreement, a customer who is not
  a Signer with an agreement, a waiting receipt reversal draft, an inactive method (added after P4,
  see the runs below)); the Credit Refund
  details check (`app.settlement_correction_refund_allowed` true without a Deposit, false with one);
  the stale check now compares the whole result and a test changes each field.
- SF4 (promised tests not built; BR-CREDIT-008 claimed without two Customers; no Late-payment
  Charge target): fixed with two tests (two Signers: the Signer's Credit refused on the Primary
  Tenant's line, per-Customer Credit first, a Refund to the other signed Signer with the agreement
  in the details row; a Late-payment Charge paid by released Credit and the Pet Deposit, and records
  of one Settlement linked to another Settlement's correction refused); BR-CREDIT-008 removed from
  the two entries that do not test it; "a kept Deposit" replaced in the plan by the empty-Deposit
  refusal (a kept Deposit holds nothing after closure; 10d tests one an overlay gives back).
- N5 (lock order not the Settlement confirm's; advisory locks and READ COMMITTED left to the
  variant): fixed; the lock function takes the draft and Settlement draft locks first and the
  Settlement row before the Deposits; the step checks READ COMMITTED and takes its locks again.
- N6 (stale comparison partial): fixed with SF3 (whole result).
- N7 (R2 counts all of a Credit's value): named as a choice in docs/010 (choice 5) and for the owner.
- N8 (the step's Deposit applications get no microsecond bump; as 8e-3): plan note for the writers
  and slice 12.
- N9 (docs wording; BR-CREDIT-014 missing in the docstring): fixed.

### Security review: 0 blockers, 2 should-fix, 4 notes

- S1 (the same as independent SF2): fixed as above.
- S2 (deny cases missing: another Settlement's correction, a kept Deposit, a Refund to a signed
  Signer, the deferred Credit check, the Credit Refund details check, the stage order within one
  correction): fixed with the tests above and a stage-order test (a Security Deposit step after a
  remaining Pet Deposit step, 23514); the kept Deposit as for SF4.
- N1 (the step relies on the variant for locks and READ COMMITTED): fixed as independent N5.
- N2 (Credit before Deposits reads Credits it does not lock): accepted race, docs/010 choice 16
  (as the Settlement confirm; nothing is overpaid).
- N3 (once per Deposit and the details' Deposit only by triggers): fixed; unique key
  `settlement_correction_refund_details_once_per_deposit` and the deferred details check also needs
  the details to name the Refund's own Deposit (a patch of the 10c-1b function, refusing nothing
  anyone could do before).
- N4 (the open-debt rule of a correction's Deposit Refund holds only at its insert): plan note for
  10c-2a-3 and 10e (the step stays the last writer of Lease debt, or a deferred re-check).

## Runs after the round-1 fixes

Static checks, each in its own tool call: `ruff format`, `ruff check src tests` (two long lines in
the test, fixed by hand, then clean), `ruff format --check src tests` (306 files), `mypy` (one
missing type in the test, fixed, then no issues). Migration-only check before P3 and before P4:
reached `20261106_102`. Read-only search: since P2 the migration gained the Deposit application
plan match, the details key and check, the lock order and the step's own checks; the module gained
tests; no reversal, correction Credit application, Deposit application or Deposit Refund exists
outside the new module, and the 10c-1b details rows name no Deposit, so no other test is affected.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U2 | backend unit, full | 3589 passed, 1755 skipped, 1 warning (Starlette) | round-1 fixes (traceability) | `V1-056-slice-10c-2a-2-unit-test-run-2.txt` |
| P3 | PostgreSQL, full | 1 failed, 1917 passed, 1 warning (Starlette) | round-1 fixes | `V1-056-slice-10c-2a-2-full-test-run-3.txt` |
| P4 | PostgreSQL, full | 1918 passed, 2 warnings (Starlette; Pydantic alias, slice 12 item) | after correction 1 of cause C | `V1-056-slice-10c-2a-2-full-test-run-4.txt` |

Cause C (test fixture, correction 1 of 2): the new Late-payment Charge test recognized Credit from
a new Payment's excess for a Customer with open debt; the existing excess rule refuses it
(`Applicable obligations must be handled before excess disposition`, 23514, reported by the Credit
service as "outcome unresolved"). The test now gets the Credit as such a Customer can: a Payment of
the other line after closure, released by the correction's own credit Adjustment (BR-CREDIT-014),
named by its plan key. The migration did not change.

Corrections used: cause A 1 of 2, cause B 1 of 2, cause C 1 of 2.

After P4 one test was added (an inactive Refund method refuses a correction's Deposit Refund,
55000; the method is deactivated inside the attempt, which rolls back), because this record first
said wrongly that a method cannot be deactivated in a test. Static checks again, each in its own
call (format, `ruff check src tests`, `ruff format --check src tests`, `mypy`): clean.
Migration-only check before P5: reached `20261106_102`. Only the new module changed, so no other
test is affected.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| P5 | PostgreSQL, full | 1918 passed, 3 warnings (Starlette; two Pydantic alias, slice 12 item) | the added inactive-method test | `V1-056-slice-10c-2a-2-full-test-run-5.txt` |

## Round 2 (2026-10-07)

Fresh read-only subagents again (the code, the tracked diff and this record); neither edited
anything or ran a test. Both verified the round-1 fixes in the code: the Deposit application plan
match and its once count, the unique details key and the details' Deposit check, the whole-result
stale comparison, the new deny-case tests and the two-Customer and Late-payment Charge tests. Both
found no bypass: no role or one-call command can write a Settlement-linked Credit application, a
Deposit application or a Deposit Refund after closure without a correction confirmed in the same
transaction by its approver, matching its plan.

### Independent review: 0 blockers, 2 should-fix, 8 notes

- SF1: rule IDs claimed whose new code paths have no test: BR-DEP-027 (the CUSTOMER_ONLY step 5
  refusal of the copied plan check; the Pet Refund while debt remains at a BR-DEP-027 termination
  in the new Deposit Refund source check) and BR-CREDIT-006 (the Rent-first refusal; the
  `RENT_THEN_RECURRING_SERVICES_PROPOSAL` and `CUSTOMER_DESIGNATED` bases of the new Credit check).
  Proposed fix: tests with an unpaid-Initial termination (BR-LEASE-005) and a Rent Invoice line,
  or remove the two IDs from the claims.
- SF2: this record pointed to a "For the owner" section that did not exist. Added below.
- N-1 (the lock function takes no Lease row lock; the same point is the security SF1).
- N-2 (docs/004 still says a partial Deposit application release "re-posts the rest"; after the
  round-1 plan match the rest can only be re-applied as a plan step of the step).
- N-3 (this record's "Built" counts): fixed above.
- N-4 (the stale test changes 6 of the 8 compared fields; `lease_id` and `termination_ground` not).
- N-5 (test 2's comment and traceability say "a Customer other than the payer"; the recipient
  there is the payer; DB-REFUND-001 missing in that entry).
- N-6 (test 4's traceability entry lacks BR-REFUND-014 and BR-REFUND-015 and the inactive method).
- N-7 (the step's READ COMMITTED refusal is untested; the same point is the security SF2).
- N-8 (the Late-payment Charge test builds its plan from data-dependent branches; assert that the
  Pet Deposit step on the Charge and the pet damage step exist).

### Security review: 0 blockers, 2 should-fix, 3 notes

- SF1: the lock function takes no Lease row lock, while the Settlement confirm locks the Lease row
  `FOR UPDATE` and 10b locks it `FOR SHARE`. Scenario: while a correction runs the step and writes
  a `PET_RELATED_FIRST` application, a user with the inspection capability supersedes the move-out
  inspection (`app.move_out_inspection_record`, financial role, locks only the Lease row) before
  the correction commits; the line is then no longer pet damage, so the Pet Deposit paid non-pet
  debt as pet damage (at a BR-DEP-027 termination, without the Customer's choice). Proposed fix:
  lock the Lease row (`FOR SHARE`, or `FOR UPDATE` as the Settlement confirm) after the two
  advisory locks, with a two-connection test, and the docs.
- SF2: the step's own deny branches are untested: the step called inside a live correction by
  someone other than its approver, and the READ COMMITTED refusal (round-1 fix). Proposed fix: two
  refusal cases (REPEATABLE READ; another person), each leaving the draft pending.
- N1 (the triggers tie records to the plan stored in the draft; the plan-wide rules hold only
  through the step: a variant that writes a linked Deposit application, Credit application or
  Deposit Refund directly would skip them; a writer rule and a source-text test per variant, or a
  deferred check that the step ran).
- N2 (lock order depends on the variant calling the lock function before begin and locking the
  released allocation's Payment; only a detected deadlock otherwise).
- N3 (a correction's Deposit Refund and Deposit applications carry thin audit context: the Refund
  audit names neither the Settlement nor the correction; each variant's audit event must name
  every record; optionally extend the Refund audit).

Result: no blocker, but four distinct should-fix findings after round 2 (independent SF1 and SF2,
security SF1 and SF2), more than the standing round-3 rule allows. Stopped before any round-2 fix,
NOT committed (Q-2026-10-07-43). All 10c-2a-2 files are in the working tree.

## For the owner

- docs/010 choice 5, first part: Customer Credit before Deposits (Q-42 answer 1) applies only
  when a Deposit holds money. The Settlement draft applies it always (Q-29 answer 2). Applied
  always after closure, a Credit-only `REFUND` correction would have to apply the Credit of
  Customers it does not concern. Is the conditional rule right?
- docs/010 choice 5, second part: released Credit first (Q-42 answer 2) counts all of that
  Credit's available value, also value it held before the correction (an existing Credit that a
  reversed Credit application refills). Is that right, or only the released part?
- docs/010 choice 16 (accepted race): the Credit-before-Deposits rule reads every available Credit
  of the Lease's Customers but locks only the Credits the steps name, as the Settlement confirm
  does; a Credit recognized by a concurrent one-call command after the step's check is not used
  first. Nothing is overpaid.

Owner answers (2026-10-07, Q-2026-10-07-43): option (a) as an owner exception; choice 5 (both
parts) confirmed; choice 16 accepted as a known limit (docs/010).

## Fixes after the owner answer to Q-2026-10-07-43

- Fix 1 (security SF1): `app.move_out_inspection_record` (20260915_60) and its insert trigger lock
  the Lease row `FOR UPDATE`; the step's lock function did not. It now locks the same row
  `FOR UPDATE` right after the two draft locks (the 8e-3 order). New test
  `test_an_inspection_correction_waits_for_the_step_and_its_line_is_then_no_pet_damage`: the
  inspection service (second connection) waits on the holder while the step runs; after the
  holder rolls back and the supersede commits, the step refuses the Pet Deposit pet-damage step
  (55000 "The Pet Deposit first pays only valid pet damage"); the draft stays pending.
- Fix 2 (security SF2): in `test_the_relaxed_checks_accept_only_a_correction_s_own_records`, the
  step inside a live correction for another person (23514) and at REPEATABLE READ (55000); the
  draft stays pending.
- Fix 3 (independent SF1): `test_a_br_dep_027_termination_after_closure` (staff reason refused at
  an unpaid-Initial termination; with the Customer's choice the Pet Deposit's rest is refunded
  while other debt stays open, accepted by the plan check and the Deposit Refund source check) and
  `test_credit_after_closure_follows_the_rent_first_proposal_or_the_designation` (Rent-first
  refusals; CUSTOMER_DESIGNATED and the proposal bases on the written rows).
- Cheap round-2 notes: DL-032 order, Deposit type and non-pet line refusals; the stale test changes
  all 8 recorded fields; the Late-payment Charge test asserts its pet damage and Charge steps;
  test 2 comment and traceability wording (DB-REFUND-001); test 4 entry gains BR-REFUND-014 and
  BR-REFUND-015; docs/004 partial-release sentence and the step's lock order; plan notes for the
  writers.

## Runs after the fixes

Static checks, each in its own tool call: `ruff format` (the two files), `ruff check src tests`
(clean), `ruff format --check src tests` (306 files), `mypy` (no issues). Migration-only check
before P6 (throwaway copy of `scripts/database-test.sh` in the session scratchpad): reached
`20261106_102`. Read-only search: only the new module calls the step's functions; the changed
lock function is new in 102, so no other test compares it.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U3 | backend unit, full | 3589 passed, 1758 skipped, 1 warning (Starlette) | owner answer to Q-43 (fixes 1 to 3) | `V1-056-slice-10c-2a-2-unit-test-run-3.txt` |
| P6 | PostgreSQL, full | 1921 passed, 1 warning (Starlette); the new module 10 passed | owner answer to Q-43 (fixes 1 to 3) | `V1-056-slice-10c-2a-2-full-test-run-6.txt` |

No correction was needed.

## Round 3 (2026-10-07, owner exception)

Fresh read-only subagents (independent and security), limited to the three fixes and the code they
touch; neither edited anything or ran a test.

### Security review: 0 blockers, 0 should-fix, 5 notes

Verified: the inspection command waits on the step's Lease lock; no new deadlock (the inspection
command holds only `FOR SHARE` on the property and user account rows while it waits; the order is
the Settlement confirm's); the other facts the step reads (termination ground, Deposit path and
held amount, the steps' Credits, new charges after closure, pet-damage sources) are covered by the
Lease lock, the Deposit locks, the Credit locks or the 8e-1 refusals; both guard tests reach the
step's own checks; no grant; no secrets or personal data.

- N1 (owner policy, outside the three fixes): the lock makes the step's checks consistent, not
  lasting: after a correction (or the Settlement confirm itself) commits a pet-damage Deposit
  application, a user with the inspection capability can still supersede the inspection, and the
  line stops being pet damage. Options: refuse an inspection supersede once the Lease's Settlement
  is closed (a conflict), or route it through a correction; or record it as a known limit.
- N2: the lock function comment credits 10c-1b with the Lease lock; 10c-1b takes none (same as the
  independent SF1).
- N3: the inspection test cannot catch a regression of the step's own lock call (the hand-built
  variant calls the lock function first); optional extra case without the variant's call.
- N4: the Credit check's basis comparison is tested only on the passing path; optional direct
  linked application with a wrong basis (23514).
- N5: while a correction runs the step, inserts that name the Lease wait and the `NOWAIT` Lease
  readers fail at once (55P03), as with the Settlement confirm; the variants' services map 55P03
  and 40P01 to a conflict.

### Independent review: 0 blockers, 2 should-fix, 6 notes

- SF1 (comment and plan text): the lock function comment (migration 102, before
  `app.lock_settlement_correction_plan`) says a variant takes "the draft lock, the Settlement's
  draft lock and the Lease row first (as sub-slice 10c-1b ...)", but the 10c-1b confirm takes no
  Lease lock, and neither the comment nor the plan's "Notes for the writers" says the variant must
  take it `FOR UPDATE`; a writer that copies 10b's `FOR SHARE` and then its sources would upgrade
  the lock after them (40P01 risk). Verified. Proposed fix: "the Lease row `FOR UPDATE`, as the
  Settlement confirm", naming 10c-1b only for the draft locks, in the comment and the plan.
- SF2 (traceability): the inspection test's docstring and traceability entry cite BR-DEP-027, but
  `closed_case` has no termination ground, so BR-DEP-027 does not apply there (the BR-DEP-027 test
  covers it). Verified. Proposed fix: remove BR-DEP-027 from that entry and docstring.
- Notes: `blocked_by` proves a wait on some holder lock, not the Lease row (checked by hand), and
  its 2-second start deadline could be longer; same as security N3; a one-line check that the
  stale test covers every result key; same as security N4; the BR-DEP-027 test reuses the
  Settlement's Customer choice text (whether a correction after closure needs a fresh Customer
  choice is an owner question); the `FOR SHARE NOWAIT` Lease writers fail fast while the step runs
  (worth a docs/004 line).

Result: round 3 has two should-fix findings (both text: a code comment, the plan text, one
traceability entry and one test docstring; no behaviour change). Under the owner's answer to
Q-2026-10-07-43, STOPPED before any fix, NOT committed (Q-2026-10-07-44).

## After the owner answer to Q-2026-10-07-44 (option (a))

- SF1 fixed: the comment before `app.lock_settlement_correction_plan` and the plan's "Notes for
  the writers" say that 10c-1b as committed takes no Lease lock and that every later correction
  type (and 10c-1b once it uses the step in 10c-2a-3) takes the Lease row `FOR UPDATE` in the 8e-3
  order, never `FOR SHARE` first.
- SF2 fixed: BR-DEP-027 removed from the inspection test's docstring and traceability entry.
- Read-only search (owner condition for skipping the PostgreSQL run): no PostgreSQL test reads
  the traceability file or a test docstring; the tests that read migration source read only their
  own historical migrations (16, 19, 20, 21, 23, 24, 25, 31, 33, 34); the changed comment lies
  outside every function body, so the database is unchanged. No PostgreSQL run.
- Static checks, each in its own tool call: `ruff format` (2 files unchanged), `ruff check src
  tests` (clean), `ruff format --check src tests` (306 files), `mypy` (no issues).

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U4 | backend unit, full | 3589 passed, 1758 skipped, 1 warning (Starlette) | Q-44 text fixes (traceability entry) | `V1-056-slice-10c-2a-2-unit-test-run-4.txt` |

Owner answers 2 to 4 of Q-2026-10-07-44 (inspection supersede refused after closure, sub-slice
10c-2a-4; a new Customer choice per correction; 10c-1b takes the Lease lock in 10c-2a-3) are in
docs/010 and the plan; the open kind question for a wrong pet classification is
Q-2026-10-07-45. Committed (see ops/NOW.md).
