# V1-056 sub-slice 10e-1a — PAYMENT_RETURN with no closed Settlement relied on: review record

Sub-slice: 10e-1a (migration `20261120_116`). Base commit: 91da0c4. Not committed (commit hash in
ops/NOW.md once committed).

Rule IDs: BR-SETTLE-013, BR-SETTLE-016, BR-PAY-042, BR-CREDIT-014, BR-AUTH-010; DB-PAY-006,
DB-PAY-009; owner answers 1 and 5 to Q-2026-10-06-36, answers 2, 3 and 5 to Q-2026-10-06-37. Open:
Q-2026-10-10-72 (its cases are refused here). Design: ops/V1_056_PLAN.md (10e entry, "10e pre-code
design", "10e-1a", "10e-1a as built").

## Owner answers given in this session (2026-10-10)

- Q-2026-10-08-53 (a), Q-2026-10-08-57 (a), Q-2026-10-09-61 pay back, Q-2026-10-10-70 (a): recorded
  in docs/010 and the questions file; their sub-slices placed in the plan before 10h (464234a).
- New questions: Q-2026-10-10-72 (blocks 10e-1b and 10e-1c), Q-2026-10-10-73 (before 10c-2b-5).

## Built

- Migration `20261120_116`: table `app.payment_returns` (DB-PAY-009) with its BEFORE INSERT check,
  deferred confirmed-in-this-transaction check and append-only triggers; recorder
  `app.record_payment_return_draft` and confirm `app.confirm_payment_return` (EXECUTE to
  `prm_financial` only); internal `app.payment_return_in_transaction`, `_source`,
  `assert_payment_return_allowed`, `_result`, `_receipt_key` and the trigger functions (no role).
  Relaxing: the draft kind, preparer, pair and WITHDRAWN checks gain `PAYMENT_RETURN` and
  `payments.reverse`; exact-text patches of the slice 7 refusals
  (`app.validate_wrong_unit_move_reversal`, `app.validate_moved_credit_reversal`), the sub-slice 8g
  refusal (`app.validate_credit_customer_credit_reversal`) and the bound of the two
  capability-scoped draft reads (seven to eight).
- Service: `property_rental/payment_return.py` (`RecordPaymentReturnCommand`,
  `PaymentReturnService`); `FinancialDraftKind.PAYMENT_RETURN` with preparer `payments.reverse`.
- Tests: new module `test_payment_return_migration.py` (7 tests, last in
  `scripts/database-test.sh`); `test_payment_return.py` (6 unit tests); 27 head-revision assertions
  in 15 modules move to `20261120_116`; two `test_lease_deposit_forfeiture.py` expectations
  (docs/010); 13 traceability entries.
- Docs: docs/004 (DB-PAY-009 as built), docs/010 (sub-slice entry, updated tests), the plan (10e-1a
  as built).

## Read-only search of every backend test

- 27 head-revision assertions in 15 modules: only the expected revision changes.
- The new preparer capability: `test_capability_scoped_reads_fit_the_database_bound` (the bound)
  was found before the first run; `test_draft_reads_pass_only_the_prepare_capabilities_the_reader_holds`
  (the full list of a `financial.approve` reader's capabilities, written with double quotes) was
  missed by the search and found by U1 (cause B below).
- No other test lists the draft kinds, the preparer capabilities, the app functions or their
  grants at head; tests that name the three patched refusals check only their privileges, which
  CREATE OR REPLACE keeps; every forward-only test upgrades only to its own revision.

## Runs

Static checks each in its own call (`ruff check src tests`, `ruff format --check src tests`,
`mypy`). Migration-only check (throwaway copy of `scripts/database-test.sh` running
`alembic upgrade head`) before T1 and again before P1: 115 upgrades, head `20261120_116`.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T1 | PostgreSQL, targeted: the new module | 3 passed, 4 failed | first run | `V1-056-slice-10e-1a-targeted-test-run.txt` |
| T2 | PostgreSQL, targeted: the new module | 7 passed | T1 cause A | `V1-056-slice-10e-1a-targeted-test-run-2.txt` |
| U1 | backend unit, full (under `caffeinate -dims`) | 3724 passed, 1 failed, 1859 skipped | first unit run | `V1-056-slice-10e-1a-unit-test-run.txt` |
| U2 | backend unit, full (under `caffeinate -dims`) | 3725 passed, 1859 skipped, 1 warning (Starlette) | U1 cause B | `V1-056-slice-10e-1a-unit-test-run-2.txt` |
| P1 | PostgreSQL, full (under `caffeinate -dims`) | 2022 passed, 1 warning (Starlette) | first full run | `V1-056-slice-10e-1a-full-test-run.txt` |

Failure and check causes (each correction 1 of 2):

- Lint cause L (before T1): two string lines over 100 characters in the new test module.
- T1 cause A (migration): the exact-text patch of `app.validate_moved_credit_reversal` put the new
  condition after the closing parenthesis of its EXISTS subquery, so every Credit reversal failed
  with 42P01 ("missing FROM-clause entry for table payment"); the condition now sits inside the
  subquery. All four T1 failures had this cause.
- U1 cause B (committed test expectation): the read-only search missed the full capability list in
  `test_draft_reads_pass_only_the_prepare_capabilities_the_reader_holds`; `payments.reverse` added
  to that expected list (name kept, comment, docs/010).

Secret check (owner run rule): T1, T2, U1, U2 and P1 searched for database URLs with a password,
`password=` and 64-character hex strings; none found.

## Review round 1 (2026-10-10; fresh read-only subagents, independent and security; during P1)

Security: 0 blockers, 1 should-fix, 6 notes. Grants, the Staff-cannot-confirm path, the
payment_returns commit check, the reach of the three relaxed refusals (keyed to the returned
Payment, true only after its confirm, and every one of its records then reversed), isolation, no
dynamic SQL and the error mapping were traced and found sound.

- Security SF1 (the generic draft reads `app.financial_draft_resource_by_capability` and
  `app.list_financial_drafts_by_capability` still return the decision's `transaction_id` of a
  confirmed `PAYMENT_RETURN` draft through `app.financial_draft_json`; the design line "no result
  shows it" is not true for them): see "Fixes after round 1".
- Security N1 (the recorder has no READ COMMITTED guard; a REPEATABLE READ caller could record a
  second pending draft for one Payment): see "Fixes after round 1".
- Security N2 (the wrong-Unit relaxation relies on every writer of a moved allocation's reversal
  running `SET CONSTRAINTS ALL IMMEDIATE`): see "Fixes after round 1".
- Security N3 (the moved-Credit relaxation is keyed on the moved allocation's Payment, not the
  Credit's own source Payment; equal by construction today): see "Fixes after round 1".
- Security N4 (the pending-draft check searches the payload text, so a free-text field naming
  another Payment's id can block that Payment's return until the draft is rejected; availability
  only): slice 12 item.
- Security N5 (every 55000 reaches staff as one conflict message; the oversize-payload 22023 reads
  as "invalid"): 11c item (stable reason codes, no database text).
- Security N6 (the draft reason is copied onto every reversal row and shows on each affected
  Customer's ledger, also a Customer other than the payer): 11c item (screen guidance: no payer
  personal data in the reason).

Independent: 0 blockers, 3 should-fix, 10 notes. Append-only history, cents, the capability and
approver checks, replay, stale-before-decision, grants, the exact-text patches, chronology and the
race with a closing Settlement were traced and found sound.

- Independent SF1 (the relied-on rule misses a Credit whose Settlement or correction use was later
  reversed or released, for example a Credit application released by a `REFUND` correction whose
  Refund a `REFUND_RETURN` brought back, leaving value held on the Credit): fixed (six more
  `CUSTOMER_CREDIT` branches: a Settlement application, an application linked to a correction, an
  application whose reversal a correction linked, an application whose release a correction
  linked, a Refund of the Credit linked to a correction and a Refund correction linked to a
  correction; "five" corrected after round 2, N-4).
- Independent SF2 (test gaps): fixed: (a) the owner's 8g case now applies 2,000 of the Credit to
  another Invoice of the Invoice Customer and checks both Invoices owe again; a Late-payment Charge
  allocation is returned after closure; every refusal of the source state (active forfeiture,
  Deposit application, Payment, Credit and Deposit Refunds, waiting draft, status, unknown
  Payment) is checked with its SQLSTATE and message; (b) the relied-on kinds are read as the owner
  and a Payment whose only record is an allocation made before the closure is refused; a
  correction's re-posted allocation and released Credit are refused; (c) a draft recorded before
  the closure is stale after it and stays pending; (d) a service identity cannot confirm (P4506)
  and a return row whose Payment is not reversed is refused at commit (23514). Not built as real
  paths: a Payment Refund and a Deposit Refund that are not returned, and a waiting draft of
  another kind (the refusal reads the same source fields; the Credit Refund case is a real path).
- Independent SF3 (docs): docs/004 (DB-PAY-009 as built, the DB-PAY-008 and 8g exceptions),
  docs/010 (entry, updated tests, round-1 line) and the plan were written while round 1 ran; the
  8e-2 refusal is stated as not relaxed for a `PAYMENT_RETURN`. The docstring of
  `test_capability_scoped_reads_fit_the_database_bound` keeps its historical text; the comment
  states the new bound.
- Independent N1 (lock order: one mixed id order, targets of reversed records too): fixed (active
  records only; Late-payment Charges first, then Invoices).
- Independent N2 (receipt reversals dated with the statement time, before the return row): stated
  in docs/004 and docs/010 (choice (2)).
- Independent N3 (a closure between record and confirm gives P5S02, not 55000): stated in the
  plan's as-built line and docs/010; tested.
- Independent N4 (= security SF1, the transaction id in the generic draft reads) and security SF1:
  not changed in this sub-slice; the plan's 11c note now covers `PAYMENT_RETURN` drafts and
  `payments.reverse` readers (as the 11e note for correction drafts, which also stays open there);
  the design line now reads "no confirm result or replay shows it".
- Independent N5 (the result finds reversals by time and actor), N7 (the unused kind-only reads
  accept five kinds) and security N2 and N4: slice 12 items.
- Independent N6 (oversize payload, 22023): a known limit in docs/004 and docs/010; 11c maps it as
  a conflict.
- Independent N8 and security N3 (moved-Credit pass keyed on the moved allocation's Payment):
  fixed (keyed on the Credit's own source Payment).
- Independent N9 (receipt reversal named `deposits.correct`): docs/010 choice (1), slice 12
  approver-naming item.
- Security N1 (recorder without the READ COMMITTED guard): fixed (55000), tested.

## Fixes after round 1

Migration (relied-on Credit branches, recorder isolation guard, lock order, moved-Credit key), the
new test module (two new tests and the additions above), traceability (two new entries, two notes
updated), docs/004, docs/010 and the plan. Static checks each in its own call: type check failed
once (cause M: `unpaid` imported from a module that only re-exports it; imported from its own
module), then lint failed once (cause N: import order after that move; sorted by `ruff check --fix`
on the new module only), then lint, format and type check clean.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T3 | PostgreSQL, targeted: the new module | 9 passed | round-1 fixes | `V1-056-slice-10e-1a-targeted-test-run-3.txt` |
| U3 | backend unit, full (under `caffeinate -dims`) | 3725 passed, 1861 skipped, 1 warning (Starlette) | round-1 fixes changed tests and traceability | `V1-056-slice-10e-1a-unit-test-run-3.txt` |
| P2 | PostgreSQL, full (under `caffeinate -dims`) | 2024 passed, 2 warnings (Starlette; the known Pydantic alias warning, slice 12) | round-1 fixes changed the migration and tests (owner run rule) | `V1-056-slice-10e-1a-full-test-run-2.txt` |

Migration-only check before P2: 115 upgrades, head `20261120_116`. Secret check of T3, U3 and P2:
none found.

## Review round 2 (2026-10-10; fresh read-only subagents, independent and security; during P2)

Independent: 0 blockers, 2 should-fix, 5 notes. Security: 0 blockers, 1 should-fix, 4 notes. Both
confirmed the round-1 fixes that are code (the six new `CUSTOMER_CREDIT` branches are correct SQL
against the real columns; the recorder guard; the moved-Credit key) and accepted every deferral
(the transaction id in the generic draft reads to 11c; the slice 12 items; the reason codes and
ledger reason to 11c; the oversize limit; no real path for a Payment or Deposit Refund that is not
returned, because the readers never return NULL and DB-PAY-006 still guards the Payment).

- Independent SF-1 (no test proves the correction-linked Credit branches: the late-charge test's
  `CUSTOMER_CREDIT` also comes from the round-1 release branch, so deleting the new branches leaves
  every test green): open. Proposed fix: a real-path test of the round-1 example (a Credit applied
  before closure by an ordinary application, released by a `REFUND` correction after closure, its
  Refund brought back by a `REFUND_RETURN`, so the value is held on the Credit; the Credit's Payment
  shows `CUSTOMER_CREDIT` and is refused), with helpers from `test_settlement_refund_return_migration.py`.
- Independent SF-2 (the recorder READ COMMITTED test passes without the guard: a pending draft of
  the same Payment already makes the call fail with 55000): open. Proposed fix: assert the message
  ("A Payment return draft is recorded at READ COMMITTED") and use a Payment with no pending draft;
  the round-1 entries above, the docs/010 round-1 line and the traceability note overstate it until
  then.
- Security S1 (no test proves the relaxed refusals are scoped to the returned Payment within the
  same transaction: every "refusal still holds" check runs in another transaction): open. Proposed
  fix: one `prm_financial` transaction that confirms the return of Payment P and then tries the
  direct reversal of another Payment's other-Customer Credit (P4904) and the one-call reversal of
  another Payment's moved allocation (P4904), then rolls back.
- Independent N-1 (the lock comment and docs overstate the order: the Charge lock also locks its
  source Invoice at once, so two returns can still deadlock, 40P01, a conflict): proposed fix: one
  pass over the Charges FOR UPDATE, then every Invoice (targets and the Charges' source Invoices)
  in id order, or reword the comment and docs.
- Independent N-2 (docs/010 choice (4) and the plan's preview line still say a draft pending at
  closure is refused, as built it is stale; the docs/010 refusal list omits the active Deposit
  application; the migration docstring omits the new Credit cases): text fixes.
- Independent N-3 (no full run after the round-1 fixes in the record): answered: U3 and P2 above.
- Independent N-4 ("five" branches, six in the code) and N-5 (the kept docstring "at most 7"):
  text.
- Security notes 1 to 4: the wrong-Unit pass hardening can wait for slice 12 but must be revisited
  before 10e-1b adds a second writer of `payment_returns`; 11c also strips the transaction id from
  the kind-only draft reads; the ledger pages show no reason (only the staff Credit ledger does);
  the full runs after the fixes (answered: U3, P2).

Standing round-3 rule: round 2 has no blocker but three should-fix findings (all tests), more than
two, so round 3 needs the owner. STOPPED, NOT committed (Q-2026-10-10-74). All files are in the
working tree; no fix of round 2 is made yet.

## Owner answers (2026-10-10, fresh session)

Q-2026-10-10-74 option (a), an owner exception as for Q-2026-10-05-31 and Q-2026-10-07-43: the
three tests, the lock-order change and the text fixes; static checks, the migration-only check, one
full unit run and one full PostgreSQL run; then round 3, which must have no blocker and no
should-fix; otherwise stop. `payments.reverse` as the eighth preparer capability is accepted; the
independent reviewer compares the two changed `test_lease_deposit_forfeiture.py` expectations with
HEAD. Also answered: Q-2026-10-10-73 (a), Q-2026-10-10-72 point 1 (a); points 2 and 3 open
(docs/010, questions file).

## Fixes after round 2

- Independent SF-1: new test `test_a_credit_a_correction_left_held_keeps_its_payment_for_that_correction`
  (the round-1 example on the real path: a Credit applied before the real closure, released whole
  by a `REFUND` correction, its Refund brought back whole by a return-only `REFUND_RETURN`; the
  Payment has no active allocation or application and nothing refunded; its only relied-on record
  is `CUSTOMER_CREDIT` of that Settlement; `app.assert_payment_return_allowed` passes on the same
  source without it; the return is refused).
- Independent SF-2: the recorder READ COMMITTED check now uses a Payment with no waiting draft,
  asserts the guard's message and that no draft is written, then records the draft at READ
  COMMITTED.
- Security S1: new test `test_the_relaxed_refusals_open_only_for_the_payment_returned_in_the_transaction`
  (one `prm_financial` transaction confirms the return of a third-party Payment, then the one-call
  reversals of another third-party Payment's released Credit, of a moved Payment's moved-value
  Credit and of its moved allocation are each refused with P4904 and their own message; rollback;
  nothing stays).
- Independent N-1 (code): the confirm locks the targets in two passes, every Late-payment Charge in
  id order, then every Invoice in id order (the Invoice targets and the Charges' source Invoices
  together), as the Final Settlement confirm; comment, docs/004, docs/010 and the plan state it.
- Independent N-2 and N-4 (text): docs/010 choice (4) and the plan's preview line say stale
  (P5S02); the docs/010 refusal list names the active Deposit application; the migration docstring
  names the round-1 Credit cases and the other refusals; "five" branches corrected to six above.
  N-5: the docstring of `test_capability_scoped_reads_fit_the_database_bound` keeps its historical
  text on purpose (the run rule changes only the one expectation, with a comment).
- Traceability: two new entries, the `test_refusals_stale_drafts_withdrawal_and_reads` note updated.

Static checks each in its own call: `ruff check src tests` clean; `ruff format --check src tests`
failed once (cause F: one comprehension line in the new test module; correction 1 of 2,
`ruff format` on that file only), then clean; `mypy` clean; lint clean again after the format.
Migration-only check (throwaway copy of `scripts/database-test.sh` running `alembic upgrade head`,
kept in the session scratchpad): 115 upgrades, head `20261120_116`. Read-only search of every
backend test: no other test reads `app.confirm_payment_return` or the changed text; the tests
that name the payment-return objects only assert the head revision.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U4 | backend unit, full (under `caffeinate -dims`) | 3725 passed, 1863 skipped, 1 warning (Starlette) | round-2 fixes (owner answer (a) to Q-74) | `V1-056-slice-10e-1a-unit-test-run-4.txt` |
| P3 | PostgreSQL, full (under `caffeinate -dims`) | 2026 passed, 2 warnings (Starlette; the known Pydantic alias warning) | round-2 fixes changed the migration and tests | `V1-056-slice-10e-1a-full-test-run-3.txt` |

A first start of U4 failed before pytest ran (a wrong relative path for the output file in the
shell command); it was not a test run. Secret check of U4 and P3: none found.

## Review round 3 (2026-10-10; fresh read-only subagents, independent and security; after U4 and P3)

Independent: 0 blockers, 0 should-fix, 3 notes. Every round-2 finding fixed: SF-1 (with the six
round-1 branches deleted, `relied_on` would be empty, the assertion and the refusal would fail;
the only other branch needs a release whose `customer_credit_id` is this Credit, and the one such
release came from an Adjustment no correction links); SF-2 (without the guard the REPEATABLE READ
call would record a draft); S1 (one non-autocommit `prm_financial` transaction; each message is
raised only by one patched function); N-1 (valid SQL, the same rows as
`app.lock_payment_allocation_target` at trigger depth 0, Charges then Invoices by id, as the
Final Settlement confirm; no new deadlock or missed lock). Owner answer 2, check against HEAD:
only two lines of `test_lease_deposit_forfeiture.py` changed (`payments.reverse` added with a
comment to the expected capability set of a `financial.approve` reader, and `<= 7` to `<= 8` with a
comment); names, docstrings and all other assertions unchanged; nothing weakened.

- Independent note 1 (the plan's as-built line does not say Deposits are locked with the
  forfeiture advisory lock and the row, not `app.serialize_deposit_state`): fixed in the plan
  (as-built item (2)).
- Independent note 2 (the migration docstring's "Relaxing changes" line leaves out the 7-to-8
  bound patch, which the patch comment, docs/004 and docs/010 state): not changed, so that no
  migration file changes after P3; recorded here.
- Independent note 3 ("every Credit recognized from the Payment" should say "that is not
  reversed"): fixed in docs/004 and in the plan's as-built item (2); the design line keeps its text.

Security: 0 blockers, 0 should-fix, 4 notes. S1 fixed (one transaction, the trigger order tells the
two Credit refusals apart, the deferred trigger fires because the confirm set its constraints
immediate, all cases share the one Property, nothing stays after rollback); the new lock code keeps
every earlier lock, SECURITY DEFINER with `search_path=pg_catalog`, no dynamic SQL, no reach into
another Property; grants as designed; no secrets or customer data in the files or run outputs.

- Security N1 (no test reaches the confirm's human check behind P4506; defence in depth, as the
  Final Settlement confirm): slice 12 item.
- Security N2 (the table-privilege loop omits TRUNCATE, REFERENCES and TRIGGER; `REVOKE ALL`
  covers them): slice 12 item.
- Security N3 (two warning lines in the run outputs show the developer's local path, as earlier
  committed outputs): no action.
- Security N4 (docs/004 lock-order text matches the code): confirmation.

Round 3 has no blocker and no should-fix, so 10e-1a is committed under owner answer (a) to
Q-2026-10-10-74. Only documents changed after P3 (the plan, docs/004 and this record).
