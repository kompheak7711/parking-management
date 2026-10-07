# V1-056 sub-slice 10c-1b — Post-settlement Refund of a paid wrong charge: review record

Sub-slice: 10c-1b (migration `20261104_100`). Base commit: 2f8077e (the 10c-1b design stop).
Rule IDs: BR-SETTLE-013, BR-SETTLE-012, BR-CREDIT-014, BR-CREDIT-008, BR-REFUND-014, BR-INV-045,
BR-AUTH-010; DB-SETTLE-003, DB-SETTLE-005, DB-REFUND-001; owner answer 1 to Q-2026-10-06-36 and
the owner answers to Q-2026-10-07-38 and Q-2026-10-07-39.

## Before the build

- Read in order: AGENTS.md, ops/NOW.md, ops/V1_055_RUN_RULES.md, ops/V1_056_TAKEOVER.md, the
  plan's slice 10 design note and the 10c-1b pre-code design, ops/V1_056_QUESTIONS.md (Q-36 to
  Q-39), the 10c-1a review record and the V1-056 notes in docs/010. Start state checked: tree
  clean, HEAD 2f8077e.
- Owner answers recorded (2026-10-07): Q-38 (sub-slice 10c-3 for a wrong Late-payment Charge;
  docs/010, docs/002 BR-SETTLE-013, BR-LATE-005 and BR-CREDIT-014 "Amended by" lines, questions
  file, plan); Q-39 (1) the new table `settlement_correction_refund_details`, docs/004 updated;
  Q-39 (2) the approved tightening of the remainder reversal; the accepted gap until 10h (docs/010,
  plan 10h entry).
- Long documents edited only with exact-text edits; `git diff --stat` checked after each edit:
  questions +11/−2, docs/002 +6, docs/010 +1 then +3 in total, plan +8/−2, +10/−3 after round 1,
  +11/−3 after round 2 (the slice 12 open item) and +12/−3 after round 3 (two text notes),
  docs/004 +46 then +50 after round 1. No edit changed more than intended.
- Read-only design search on a throwaway database at head `20261103_99` (schema dump in the session
  scratchpad): the migration 67 release, the Refund source checks (general, 8f deferred), the
  Credit and allocation writers' lock order, the 8e-1 and 8e-2 refusals, the Refund method checks.
- Read-only search of all backend tests for affected tests: the 26 head-revision assertions in 14
  modules (updated); the catalog comparisons of 8f and 8e-2 run in their own temporary databases at
  their own revisions; the 8e-2 trigger-order test reads the first trigger by name, still the 8e-2
  one (`..._final_settlement` sorts before `..._settlement_remainder`); the whole-catalog privilege
  checks are not affected (the new functions and table are revoked from PUBLIC and every
  application role; the two patched functions keep their privileges).

## Built

- Migration `20261104_100`: table `app.settlement_correction_refund_details` (append-only, no role
  access, BEFORE INSERT and deferred checks); recorder `app.record_settlement_refund_draft` and
  confirm `app.confirm_settlement_refund` (EXECUTE to `prm_financial` only); internal helpers for
  the input shape, the line's paying sources, the source state, the plan and the result; the
  relaxed check `app.settlement_correction_refund_allowed` used by the two patched Refund source
  checks (`app.validate_general_refund_source`, `app.assert_credit_customer_refund_confirmed`); the
  approved remainder refusal trigger `a0_customer_credit_application_reversals_settlement_remainder`.
- Service: `SettlementCorrectionService.record_refund` and `confirm_refund` with
  `RecordRefundCorrectionCommand`.
- Tests: `test_settlement_correction.py` (unit, 4 new tests, 32 cases),
  `test_settlement_refund_correction_migration.py` (PostgreSQL, 5 tests before round 1, 7 after
  round 1, 8 after round 2, 9 after the owner answer to Q-2026-10-07-40; last in
  `scripts/database-test.sh`); traceability 9 entries appended (11 after round 1, 12 after round
  2, 13 after the Q-40 test); 26 head-revision assertions.
- Docs: docs/002, docs/004 (DB-SETTLE-005 and DB-REFUND-001 as built), docs/010 (owner answers,
  the 10c-1b entry with its choices, updated tests), the plan, the questions file. docs/005
  unchanged (no route; slice 11e).

New check named for the owner (10b answer 2): only the approved remainder refusal; it refuses
nothing staff can do today, because a re-posted rest of a Settlement Credit application exists only
through a correction.

## Runs before review round 1

Static checks, each in its own tool call: `ruff format` on the four new or edited Python files (one
reformatted), `ruff check` (clean), `ruff format --check` over src, tests and the new migration (305
files already formatted), `mypy` on the changed files (no issues). Migration-only check before P1
(owner rule): the throwaway copy of `scripts/database-test.sh` in the session scratchpad reached
`20261104_100` on a fresh container.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U1 | backend unit, full | 3589 passed, 1740 skipped, 1 warning (Starlette) | first run of 10c-1b | `V1-056-slice-10c-1b-unit-test-run.txt` |
| P1 | PostgreSQL, full | 1903 passed, 2 warnings (Starlette; Pydantic alias, the known slice 12 item) | first run of 10c-1b | `V1-056-slice-10c-1b-full-test-run.txt` |

No correction was needed.

## Round 1 (2026-10-07)

Both reviewers were fresh read-only subagents given the diff, the new files, the rule IDs, the
takeover file, the plan's slice 10 design note with the 10c entries, the owner answers and a schema
dump at the new head; neither edited anything or ran a test.

### Independent review: 0 blockers, 3 should-fix, 6 notes

- SF1 (the generic audits of the reversals, re-posts, Credits and Refunds do not name the
  correction, against design note point 2; the plan said "the Refund audit keeps its shape"):
  fixed; the `final_settlement.correction.confirmed` event's resulting state now also carries the
  released sources (reversed and re-posted ids, Credits, amounts) next to the Refunds; no earlier
  function changes; plan text reworded; test 1 asserts it.
- SF2 (the Credit-application half of the relaxed check is untested): fixed; new test
  `test_a_credit_released_before_closure_to_the_invoice_customer_is_refunded_to_that_customer`
  (a third-party Payment's Credit released before closure to the Invoice Customer, applied to
  another line, released again by the correction and refunded to that Customer, not the payer).
- SF3 (nothing shows the remainder refusal leaves ordinary re-posts alone): fixed; new test
  `test_an_ordinary_re_posted_credit_application_still_reverses_with_one_call` (a one-call credit
  Adjustment on an open Settlement's Lease re-posts an ordinary application's rest, which still
  reverses with one call).
- N4 (owner answer 1 may be read as one method per Refund): answered; option (a), which the owner
  approved, has one method and note per draft, stored per Refund; every Refund of one correction
  goes to the Invoice Customer; named for the owner below.
- N5 (the released Credits are not linked; DB-SETTLE-003 says the effects identify every event):
  answered; the approved link set has no Credit link; the linked Adjustment's release rows name
  them (docs/010 choice 8); named for the owner below.
- N6 (plan text: "their Credits" in the source revision; the lock order): fixed with as-built text.
- N7 (the 10h entry still said "10h decides"): fixed; it now records the decision of the owner's
  yes to Q-39 point 2, whose recommendation includes it.
- N8 (a one-call `adjust_invoice` or `void_invoice` on the same Invoice locks the Invoice before the
  Payments, so it can deadlock with a confirm): answered; both are refused after closure (8e-1), the
  loser gets 40P01 (a conflict) and the draft stays pending; recorded in the plan for 10h.
- N9 (an inactive method is tested only at confirm): fixed; test 4 also records with it (55000).

### Security review: 0 blockers, 0 should-fix, 3 notes

- N1 (the relaxed check accepted a link to any correction of the Settlement in this transaction,
  and its cap was per Refund, not cumulative): fixed; it now needs the link to the correction its
  details row names, and the Refund together with that correction's other Refunds of the same
  Credit within what the correction released to that Credit.
- N2 (the details table's only check was the confirmed correction): fixed in part; the BEFORE
  INSERT check also needs the Refund already linked to that correction, and a new deferred check
  (`settlement_correction_refund_details_approver`) needs the Refund processed by the correction's
  approver; answered for the rest: a check that every `refund_id` effect has a details row would
  need a trigger on the 10a effects table; the only writer writes both in one loop step; slice 12
  item if wanted.
- N3 (the same deadlock as independent N8): answered as N8.

## Runs after the round-1 fixes

Static checks, each in its own tool call: `ruff format` on the migration and the test file
(unchanged), `ruff check` (2 issues: an import order and an unused variable after a test helper
refactor; fixed by hand, then clean), `ruff format --check` over src, tests and the new migration
(305 files), `mypy` once on the test file alone by mistake (wrong scope: without the src file in
the call mypy cannot resolve `property_rental` and reports setup noise; nothing changed), then
`mypy` on the changed files with the usual scope (no issues). Migration-only check before P2:
reached `20261104_100`. Read-only search: since P1 only the new migration, the new module,
traceability and docs changed; no other test is affected.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U2 | backend unit, full | 3589 passed, 1742 skipped, 1 warning (Starlette) | after the round-1 fixes (traceability, new tests) | `V1-056-slice-10c-1b-unit-test-run-2.txt` |
| P2 | PostgreSQL, full | 1905 passed, 2 warnings (Starlette; Pydantic alias) | after the round-1 fixes | `V1-056-slice-10c-1b-full-test-run-2.txt` |

Corrections used: one round-1 fix set (review findings, not a run failure); no run failed.

## Round 2 (2026-10-07)

Fresh read-only reviewers again (the full diff, the new files, this record, the owner answers);
neither edited anything or ran a test. Both verified every round-1 fix and written answer.

### Independent review: 0 blockers, 2 should-fix, 2 notes

- SF-A (the checks added in round 1 have no test: the link to the named correction, the cumulative
  cap, the linked-Refund requirement of the details row and the deferred approver check): fixed;
  new test `test_the_relaxed_refund_checks_hold_inside_a_hand_built_correction` builds a
  correction by hand through the internal 10a functions in one owner transaction and shows (a) a
  Refund of a Credit to its Customer who is not the payer refused (23514) even with its details row
  and link, because the correction released nothing to that Credit (the relaxed check is false
  while the link check is true), (b) a details row refused (23514) while its Refund is not linked,
  (c) a Refund to the payer with a details row refused at `SET CONSTRAINTS ALL IMMEDIATE` (42501)
  when another actor processed it; the draft stays pending; traceability entry added.
- SF-B (this record promised an owner section that did not exist): fixed; see "For the owner"
  below.
- N (the plan's "As answered" bullet did not name the round-1 checks of the details table): fixed.
- N (this record said docs/004 +52; it is +50): fixed.

### Security review: 0 blockers, 0 should-fix, 2 notes

- N1 (the per-Credit cap and recipient checks run only on the relaxed path, when the recipient is
  not the payer; a correction Refund to the payer is bounded by the Credit's available value only):
  answered; only the confirm can write these Refunds and it takes every amount from the plan
  recomputed under the locks; the optional hardening (the cap and a draft match in the deferred
  details check) is a slice 12 item.
- N2 (the general draft reads still return the decision's transaction id, and a `REFUND` draft's
  payload shows the payer, the Payment ids and the note to `final_settlements.prepare` holders):
  answered; the existing 11e item (10b) strips the transaction id and decides what draft readers
  see.

## Runs before round 3 (standing rule)

Static checks, each in its own tool call: `ruff format` on the test file (one reformatted), `ruff
check` (one line over 100 characters, wrapped by hand, then clean), `ruff format --check` (305
files, then the test file again), `mypy` on the changed files (no issues, twice). Migration-only
check before P3: reached `20261104_100`. Read-only search: since P2 only the new module,
traceability, the plan and this record changed.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U3 | backend unit, full | 3589 passed, 1743 skipped, 1 warning (Starlette) | standing rule before round 3 (new test) | `V1-056-slice-10c-1b-unit-test-run-3.txt` |
| P3 | PostgreSQL, full | 1906 passed, 4 warnings (Starlette; three Pydantic alias warnings, the known slice 12 item, whose count follows the test order) | standing rule before round 3 (new test) | `V1-056-slice-10c-1b-full-test-run-3.txt` |

## For the owner

- Q-39 answer 1 reading: the draft holds one Refund method and one reference note (option (a)),
  stored in each Refund's own details row; every Refund of one correction goes to the Invoice
  Customer, because every released value belongs to that Customer (BR-CREDIT-014, BR-CREDIT-008).
  If you want a different method per Refund, that is a later change of the draft input.
- The released Customer Credits have no DB-SETTLE-005 link (the approved link set has none); the
  linked Adjustment's `invoice_credit_excess_releases` rows name them, and the correction's audit
  event lists them.
- A one-call `adjust_invoice` or `void_invoice` on the same Invoice of a closed Settlement can
  deadlock with a confirm (opposite lock order); both are refused after closure anyway; the loser
  gets a conflict and the draft stays pending (plan note for 10h).
- Not built: a check that every Refund linked to a correction has its details row (it needs a
  trigger on the 10a effects table; the only writer writes both together), and the extra cap for a
  correction Refund to the payer; slice 12 items.
- The 10h entry now records that 10h counts the re-posted rest of a closure-era record as existing
  at closure, from your yes to Q-39 point 2, whose recommendation included it; tell me if you meant
  only the Credit application refusal.
- New check named under the 10b answer 2 rule: only the approved remainder refusal.
- docs/010 choice 9: a correction's Credit Refund stays correctable by the one-call verified
  return and its reversal, like any Credit Refund (the value returns to the Credit, not to the
  Settlement's obligations); 8d made Settlement Deposit Refunds correctable only through a
  correction. Tell me if correction Refunds should follow the 8d rule (a tightening).

## Round 3 (2026-10-07): STOPPED

Fresh read-only reviewers again; neither edited anything or ran a test. Both verified every
round-1 and round-2 fix and answer except the one below.

### Independent review: 0 blockers, 1 should-fix, 4 notes

- SF (the cumulative term of the per-Credit cap in `app.settlement_correction_refund_allowed`, "the
  correction's other Refunds of the same Credit", is never exercised: test case (a) uses a
  correction that released nothing, which a per-Refund cap refuses too; deleting the term leaves
  all 8 tests green; this record's round-2 SF-A text said the cumulative cap was covered): NOT
  fixed; under the standing rule a round-3 should-fix stops the sub-slice; Q-2026-10-07-40 asks the
  owner (options and recommendation there). The SF-A text above overstates the coverage: the new
  test isolates the link, details and approver checks and the cap at zero released, not the
  cumulative term.
- N1 (the plan's 10c-1b test list misses the three tests added in rounds 1 and 2): fixed (text).
- N2 (the round-2 security N2 answer points to an 11e item that covers only the transaction id):
  fixed (text); the plan gains an 11e line on what a `REFUND` correction draft shows its readers.
- N3 (stale counts in this record): fixed (text).
- N4 (docs/010 choice 9 missing from the owner section): fixed (text), above.

### Security review: 0 blockers, 0 should-fix, 1 note

- N (the same gap: no test shows a second Refund of the same Credit refused once the correction's
  earlier Refunds use up what it released; defence in depth only, no role can write such a Refund;
  suggested test: in one owner transaction a real `app.confirm_settlement_refund`, then `SET
  CONSTRAINTS ALL DEFERRED`, a new linked Refund id with its details row and a direct 1-cent Refund
  of the same Credit by the approver, expecting 23514): part of Q-2026-10-07-40.

After round 3 only text changed (this record and the plan). No executable line, test or
traceability entry changed: the migration, service, tests and manifest are exactly what U3 and P3
ran. Nothing is committed.

## Owner answers (2026-10-07, fresh session)

- Q-2026-10-07-40: option (a), as an owner exception like Q-2026-10-05-31: add the one test, run
  the backend unit suite and the full PostgreSQL suite once each, then one review round limited to
  the new test and this record; commit only if that round has no blocker and no should-fix.
- "For the owner" points: (1) accepted: one Refund method and one reference note per correction
  draft, every Refund to the Invoice Customer; (2) accepted: the released Credits are named by the
  release records and the audit event, without a correction link; (3) accepted: the deadlock ends
  as a conflict and the draft stays pending; (4) yes, correction Refunds follow 8d: approved
  tightening, a Credit Refund paid by a post-settlement correction is corrected only through
  another post-settlement correction, not by the one-call verified return (otherwise a one-call
  return could create Credit that pays debt without an approver); NOT built in 10c-1b; built with
  a test in the next sub-slice or in 10h (plan); (5) yes, both: a re-posted leftover of anything
  that existed at closure counts as existing at closure (10h).
- Recorded in docs/010, ops/V1_056_QUESTIONS.md and the plan.

## The Q-40 test (owner answer (a))

Start state checked before any change: HEAD 2f8077e, every 10c-1b file (migration `20261104_100`
included) in the working tree and not committed, no historical migration different from HEAD.

New test `test_a_second_refund_of_the_same_credit_beyond_what_the_correction_released_is_refused`
(traceability entry added in test order inside the uncommitted 10c-1b block; no committed entry
touched): before closure a third-party Payment's Credit of 400 is released
to the Invoice Customer (not the payer) and 300 of it is applied to the pet line, so 100 stays
available; after closure, in one owner transaction, the real `app.confirm_settlement_refund`
releases 100 of that application back to the Credit and refunds it (one Refund of 100); then `SET
CONSTRAINTS ALL DEFERRED`, a new Refund id linked to the same correction with its details row,
and a direct 1-cent Refund of the same Credit to the same Customer, processed by the approver at
`GREATEST(clock_timestamp(), credit_latest_at + 1 microsecond)` (the writer's chronology), is
refused (23514, the general Refund source message). Inside the transaction the test first shows
the Credit still has 100 available, the new Refund is linked, and
`app.settlement_correction_refund_allowed` is false for it: per Refund (1 ≤ 100) it would pass, so
only the cumulative term refuses it; without that term the in-transaction assertion would get
true and the test would fail there (reasoned from the code; no mutation was run). Afterwards the draft is pending, the 1-cent Refund does not exist and the
Credit still has 100 available. No executable line outside the test module and the traceability
manifest changed.

Static checks, each in its own tool call: `ruff format` on the test file (unchanged), `ruff check`
over src, tests and the new migration (one line over 100 characters in the new test, wrapped by
hand, then clean), `ruff format --check` (305 files already formatted), `mypy` on the changed
files with the usual scope (no issues). Migration-only check before P4 (owner rule): the throwaway
copy of `scripts/database-test.sh` in the session scratchpad reached `20261104_100` on a fresh
container. Read-only search: since P3 only the new test, traceability and text changed; the new
module runs last, and the two tests after the new one read only their own ids or the catalog.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U4 | backend unit, full | 3589 passed, 1744 skipped, 1 warning (Starlette) | owner answer (a) to Q-40 (new test) | `V1-056-slice-10c-1b-unit-test-run-4.txt` |
| P4 | PostgreSQL, full | 1907 passed, 1 warning (Starlette; no Pydantic alias warning this run) | owner answer (a) to Q-40 (new test) | `V1-056-slice-10c-1b-full-test-run-4.txt` |

No run failed; no correction was needed.

## Owner-exception round (2026-10-07): the new test and this record only

Fresh read-only reviewers (independent and security), limited by the owner to the new test, its
traceability entry and this record; neither edited anything, ran a test or used a database. This
test closes the round-3 independent should-fix and the round-3 security note (the cumulative cap).

### Independent review: 0 blockers, 0 should-fix, 5 notes

- N1 (the confirm runs inside the same `pytest.raises(psycopg.Error)` block, so a future confirm
  failing with the same 23514 would also satisfy the test): noted; today the in-transaction
  assertions run only after the confirm returns, and the module's success-path tests would fail on
  such a change; optional hardening (raise only around the final insert) added to the plan's slice
  12 test item.
- N2 (the final `available == 100` is the same whether the confirm rolled back or committed; the
  PENDING draft is the rollback evidence): answered; no claim relies on it.
- N3 (the record said the insert and commit would succeed without the term; the test fails earlier,
  at the in-transaction assertion; reasoned, not run): fixed (text above).
- N4 (the traceability entry was inserted in test order, not appended at the end; no committed
  entry touched): fixed (text above).
- N5 (the static checks and the migration-only check cannot be verified from the repository): no
  change; they are listed above as run.

### Security review: 0 blockers, 0 should-fix, 5 notes

- N1 (as independent N1): noted, the same slice 12 item.
- N2 ("only the cumulative cap is not met" is inferred across the helper, the first Refund and the
  assertion; a guard call with 0 cents expecting true would show it in one place): optional; added
  to the same slice 12 item.
- N3 (the commit-time behaviour without the term is reasoned, not run; the test fails at the
  assertion first): fixed with independent N3.
- N4 (`<` instead of `<=` in the cap is caught by the success-path tests, not by this test): no
  change.
- N5 (the record did not say this test closes the round-3 findings): fixed (the sentence at the top
  of this section).

Result: no blocker and no should-fix, so 10c-1b is committed under the owner's answer to Q-40.
After this round only text changed (this record and the plan's slice 12 item); the migration,
service, tests and manifest are exactly what U4 and P4 ran.
