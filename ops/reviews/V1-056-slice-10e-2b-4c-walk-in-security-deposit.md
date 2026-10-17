# V1-056 sub-slice 10e-2b-4c — the walk-in Lease's Security Deposit and a second receipt before signing — review record

Sub-slice: 10e-2b-4c (owner answers to Q-2026-10-17-124; owner note of 2026-10-17 on DL-009).
Migration `20261229_155` (relaxing). Base commit: 0f41a9a. Built on 2026-10-18. Not pushed.

Rule IDs: BR-DEP-001, BR-DEP-002, BR-DEP-004, BR-DEP-005, BR-DEP-006, DL-008, DL-009, DL-066;
BR-RES-020 to BR-RES-022, BR-DEP-015 to BR-DEP-017, BR-REFUND-004 (the DL-009 outcomes);
DB-DEP-001, DB-DEP-002, DB-DEP-007. Design: ops/V1_056_PLAN.md, "10e-2b-4c pre-code design" and
"10e-2b-4c as built".

## Built

- Migration `20261229_155_lease_security_deposit.py`: `deposits_source_shape` gains the walk-in
  branch (a Security Deposit with a Lease and no Reservation); `deposit_commands_action_check`
  also allows `deposit.security.create` (both relaxing); new `app.create_lease_security_deposit`
  (SECURITY DEFINER, `search_path=pg_catalog`, EXECUTE only to `prm_financial`); exact-text patches
  of ten functions, each replacement checked to match once: `app.validate_reservation_security_deposit`,
  `app.validate_deposit_source` (walk-in branch; Reservation branch refuses linking to a Lease with
  a walk-in Security Deposit), `app.validate_deposit_receipt` (walk-in first receipt, signing time),
  `app.record_lease_deposit_receipt` (a Reservation's Deposit before signing; Reservation lock
  before the Deposit), `app.reservation_deposit_draft_source`,
  `app.validate_reservation_financial_outcome`, `app.create_reservation_deposit_outcome`,
  `app.correct_reservation_deposit_outcome` (active receipts only), `app.cancel_reservation`,
  `app.expire_reservation` (report active receipts only).
- Service (`backend/src/property_rental/deposit.py`): `CreateLeaseSecurityDepositCommand`,
  `PostgresDepositService.create_lease_security_deposit` (`deposits.manage`, checked before any
  connection); the `record_receipt` docstring names the Reservation case. Reservation read API
  (`backend/src/property_rental/reservation_api.py`): the received amount counts only active
  receipts.
- Tests: new module `test_lease_security_deposit_migration.py` (fourteen tests, last in
  `scripts/database-test.sh`); three unit tests in `test_deposit.py`.
- Committed tests changed: `test_deposit_receipt_record_migration.py::test_the_writer_refuses_before_signing_after_closure_and_while_a_forfeiture_is_active`
  renamed `test_the_writer_takes_a_reservation_deposit_and_refuses_after_closure_and_while_forfeited`;
  its first case (a receipt into an ACTIVE Reservation's Security Deposit before signing) changes
  from refused (55000, nothing written) to recorded (2 receipts, 1 audit event, 1 command), owner
  answer to Q-2026-10-17-124 point 3; its unused `NO_LEASE` constant is removed; the 27
  head-revision assertions in 15 modules (revision strings only; a script checked each file's
  count).
- Traceability: seventeen entries appended (the 3,216th to the 3,232nd); one entry of
  10e-2b-4b-2b (the 3,203rd) renamed with its note (rename rule); no frozen entry changed.
- Docs: docs/004 (DB-DEP-001 and DB-DEP-002 paragraphs), docs/005 (note for slice 11), docs/010,
  plan (pre-code design, as-built line, slice 11 notes, slice 12 known limits and open items),
  questions (owner answers of 2026-10-18 to Q-127 and Q-128 and the report items; new
  Q-2026-10-18-129 and Q-2026-10-18-130).

Read-only search for affected tests (before T1, P1, P2 and P3): every test of the Deposit command
action list, the Deposit shape and source checks, the receipt check, the receipt writer, the
Reservation outcome functions, cancellation and expiration (`deposit_received_usd_cents`), the
Reservation read API, the old move-in, and every test that reverses a Reservation Deposit receipt;
none expected to change beyond the named test and the revision strings.

## Runs

| Run | Result |
|---|---|
| D1, D2, D3 | catalog dumps for the pre-code design and the round 1 fix (read only; no `REDACTED` markers) |
| M1 | passed (`20261229_155` head) |
| FF1/FC1/L1/Y1 | passed (formatter first: one file reformatted; long-line search first, six test lines rewrapped before the lint) |
| T1 | 128 passed (the new module, the 4b module, `test_deposit.py`, `test_deposit_migration.py`, the Reservation, signing and Reservation draft modules, `test_traceability.py`) |
| U1 | 3865 passed |
| M2 | passed |
| P1 | 2297 passed |
| FF2/FC2/L2/Y2 | passed (after the round 1 fixes; formatter one file; long-line search first, two lines rewrapped) |
| M3 | did not run: the script stopped at its `cd backend` ("No such file or directory") before any migration; it was sent in the same message as the four checks above; cause A, run start, correction 1 of 2 |
| M4 | passed (M3 sent alone) |
| T2 | 148 passed (T1's set plus the Reservation outcome and move-in modules) |
| U2 | 3865 passed |
| M5 | passed |
| P2 | 2302 passed |
| FF3/FC3/L3/Y3 | passed (after the round 2 fix; formatter one file) |
| M6 | passed |
| T3 | 1 failed, 212 passed: `test_reservation_worker_migration.py::test_failure_concurrent_retry_and_replay_produce_one_logical_execution` (3 expired, expected 2). Cause B (test isolation, inside the sub-slice): the new module ran first and `test_a_receipt_into_a_reservation_deposit_is_refused_once_the_reservation_has_ended` left an ACTIVE past-date Reservation in the shared test Property; fix: the test expires it at the end (correction 1 of 2) |
| FF4/FC4/L4/Y4 | passed |
| T4 | 1 failed, 212 passed: the worker test passed (fix B confirmed); `test_reservation_lifecycle_migration.py::test_expiration_uses_end_of_date_is_bounded_and_preserves_classification` saw another due Reservation. Cause C (targeted run order): T4 listed the worker module before the lifecycle module; the worker tests leave past-date Reservations, and the full suite runs the lifecycle module first; correction 1 of 2: the same set in the suite's order |
| T5 | 213 passed (the suite's order for the lifecycle and worker modules, the new module still first) |
| U3 | 3865 passed (before round 3) |
| M7 | passed |
| P3 | 2303 passed (the full run after the last code and test change, before the round 3 verdicts) |

After P3 only text changed (docs/010, the plan, the questions, this record, ops/NOW.md); no test reads
those files. Full outputs of every targeted and full run, each attempt in its own file, are in
`~/Development/prm-run-logs/v1-056-10e-2b-4c-*.txt` (format, lint and type checks are short and not
saved).

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: 1 blocker, 3 should-fix, 8 notes.
- B1 (blocker): a Reservation Deposit with a reversed extra receipt (a bounced second Payment)
  could never get its DL-009 outcome ("Reservation Deposit has a reversed receipt"); the owner
  note says to fix such a case inside 4c. Fixed (design change, confirmed in round 2): the draft
  source, the insert check, the outcome writer and the outcome correction count only active
  receipts; the draft source refusal is gone. Test
  `test_dl_009_classifies_the_active_money_after_an_extra_receipt_is_reversed` (the reviewer's
  set-up, both responsibilities).
- S1: Q-2026-10-18-129 cited but not written; renewal and Primary Tenant conditions untested.
  Fixed: the question written; test `test_a_renewal_or_another_customer_gets_no_walk_in_security_deposit`
  (the reviewer's set-up).
- S2: lock order tested one way only. Fixed: test
  `test_a_receipt_that_waits_for_a_signing_or_a_cancellation_reads_the_committed_state` (the
  reviewer's set-up and its twin).
- S3: docs not written. Fixed: docs/004, docs/005, docs/010, plan.
- Notes: N1 (three readers of the first required amount): Q-2026-10-18-130. N2 (the Lease
  resource's `security_deposit_id`), N3 (stale confirm comment), N5 (readings for the owner): plan
  slice 11 and slice 12 notes, docs/010. N4: the least-privilege test compares the whole shape
  check. N6: the refusal message is neutral. N7 (owner inserts can bypass the create's date): no
  change. N8 (two-Payment Reservation Deposits after a Refund): the Q-127 family.

Security: no blocker, 2 should-fix, 4 notes.
- SF1: the old Reservation move-in could link a Reservation's Deposit to a walk-in Lease that
  already has a Security Deposit. Fixed (design change, confirmed in round 2): the deferred source
  check's Reservation branch refuses it. Test
  `test_a_walk_in_lease_with_a_security_deposit_takes_no_reservation_deposit_at_move_in` (the
  reviewer's set-up, with the refusal's cause asserted).
- SF2: the unpaid-Initial ground reads the first required amount: Q-2026-10-18-130 (it changes
  when a termination ground is met; the owner decides).
- Note 1: the create had no READ COMMITTED guard. Fixed; test
  `test_the_create_runs_only_at_read_committed`.
- Note 2: the reversed-receipt limit is reachable through a Payment return: closed by the B1 fix;
  the reverse order (a bounce after the outcome) is in the slice 12 open items.
- Note 3: race test (same as S2). Note 4: the forfeiture draft should show the extra money (slice 11).

## Review round 2 (fresh read-only subagents, during P2; same instructions)

Independent: no blocker, 1 should-fix, 3 notes; all round 1 fixes right, needed and safe.
- S1: reversed receipts were still reported as received by `app.cancel_reservation`,
  `app.expire_reservation` (stored in the command result) and the Reservation read API. Fixed
  under the standing round-3 rule (one should-fix): the not-reversed condition in the LEFT JOIN's
  ON clause (a Deposit whose receipts are all reversed still gives one row for INTO STRICT); test
  `test_a_reversed_extra_receipt_is_not_shown_as_received` (the reviewer's set-up). The old move-in
  gate, which also counts reversed receipts, is a tightening of an old path: added to
  Q-2026-10-18-130.
- Notes: stale texts (fixed: docstrings say ten functions; the migration docstring); one Security
  Deposit per Lease rests on the trigger and the Lease lock (slice 12 open item); a walk-in Deposit
  created after the Start Date plus five days meets the BR-LEASE-005 ground (Q-130, slice 11 note).

Security: no blocker, no should-fix, 5 notes (all pre-existing or text): a waiting
`PAYMENT_RETURN` draft does not block a Reservation outcome confirm (slice 12 open item; set-up
below); Q-130 additions (ii) and the old move-in's reversed receipts (written into Q-130); the old
move-in has no isolation guard; texts.

### Round 2 test set-up (written in full, run rule of 2026-10-13; not built: it needs a tightening)

Security note 1 (should pass after an owner-approved fix that extends
`app.refuse_confirmation_during_receipt_reversal_draft` to `PAYMENT_RETURN` drafts naming a
Payment that funded the Deposit):

```python
def test_a_waiting_payment_return_draft_blocks_the_reservation_outcome_confirm(migrated_database_url):
    url = migrated_database_url
    case = reservation_case(url)
    human, prop, deposit = case["human"], case["prop"], case["deposit"]
    bounced = payment(url, human, deposit, 20_000)
    case["service"].record_receipt(receipt_command(deposit, bounced, 20_000), actor=allocator(human, prop))
    PaymentReturnService(financial_database_url()).record(
        prop, RecordPaymentReturnCommand(uuid4(), bounced, "Bank returned the transfer", "BANK-RETURN-1"),
        actor=person(human, prop, "payments.reverse"))
    cancel(case, CancellationResponsibility.CUSTOMER)
    draft = drafts().record(prop, ReservationDepositDecision.DEPOSIT_FORFEITURE,
        RecordReservationDepositDraftCommand(uuid4(), case["reservation"], uuid4(), "Customer withdrew"),
        actor=person(human, prop, "reservation_deposits.dispose"))
    with pytest.raises(ReservationDepositDraftConflictError):   # today: confirms 30,000
        drafts().confirm(prop, case["reservation"], UUID(str(draft["draft_id"])),
                         actor=person(human, prop, "financial.approve"))
    assert held(url, deposit) == 30_000
```

## Review round 3 (fresh read-only subagents, during P3; same instructions)

Independent: no blocker, no should-fix; the round 2 fix right and complete; 6 notes: reversed
receipts listed with no mark on the Reservation screen (slice 11 note); Q-130 option (a) now also
names the old move-in's active-receipt count (text fixed); the expiration with a reversed receipt
is proven only by the least-privilege test's exact replacement (optional test); the outcome
correction's patched sum is not read (harmless; slice 12 open item); docs/010, the review record
and the plan's as-built line (written); the 4b test's design text (the as-built line says what
was built).

Security: no blocker, no should-fix; nothing since round 2 opens a new risk; 4 notes: one
Security Deposit per Lease rests on checks and locks (slice 12 open item); the create's
closed-Settlement refusal cannot be reached (kept fail closed); Q-130 and Q-127 limits unchanged;
command results stored before this migration keep the gross amount (display only).
