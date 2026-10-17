# V1-056 sub-slice 10e-2b-4b-2b — the receipt writer for an existing Deposit of a Lease — review record

Sub-slice: 10e-2b-4b-2b (owner answer to Q-2026-10-12-92; the 10e-2b-4b-2 split). Migration
`20261228_154` (one new function, one relaxing check). Base commit: a7b181b. Built on 2026-10-18.
Not pushed.

Rule IDs: BR-DEP-002, BR-DEP-004, BR-DEP-005, BR-DEP-006, BR-DEP-009, BR-DEP-010, BR-SETTLE-012,
BR-SETTLE-013, BR-AUTH-008, BR-PAY-024, BR-PAY-026; DB-DEP-002. Design: ops/V1_056_PLAN.md, the
10e-2b-4b entry, "10e-2b-4b-2b pre-code check" and "10e-2b-4b-2b as built".

## Built

- Migration `20261228_154_lease_deposit_receipt_writer.py`: `app.record_lease_deposit_receipt`
  (SECURITY DEFINER, `search_path=pg_catalog`, `TimeZone` UTC, EXECUTE only to `prm_financial`);
  `deposit_commands_action_check` also allows `deposit.receipt.record` (relaxing).
- Service (`backend/src/property_rental/deposit.py`): `RecordDepositReceiptCommand`,
  `DepositReceiptRecord`, `PostgresDepositService.record_receipt` (`payments.allocate`, checked
  before any connection); the error mapping is shared (`_fetch`) and maps P5S01 to
  `DepositConflictError`.
- Tests: new module `test_deposit_receipt_record_migration.py` (thirteen tests, last in
  `scripts/database-test.sh`); three unit tests in `test_deposit.py`. Test support:
  `payment_test_support.seed_payment` gains an optional `late_payment_charge_id` (default none; no
  committed caller changes).
- Committed tests changed: the 27 head-revision assertions in 15 modules (revision strings only; a
  script checked each file's count). No other committed expectation changed.
- Traceability: sixteen entries appended (the 3,200th to the 3,215th); no earlier entry changed.
- Docs: docs/004 (DB-DEP-002 paragraph; the 10e-2b-1 paragraph's "only Pet Deposit receipt
  writer" now says "until sub-slice 10e-2b-4b-2b"), docs/005 (API-040 note), docs/010, plan
  (pre-code check, as-built line, slice 11 note, slice 12 known limit and open items), questions
  (owner answers of 2026-10-18; new Q-2026-10-18-127 and Q-2026-10-18-128), run rules (owner process rule (5) of
  2026-10-18).

Read-only search for affected tests (before T1 and before each full run): every test of the
Deposit command action list, of the Deposit service's error mapping (no test expects P5S01 to read
as unavailable), of the functions granted to the financial role (the whole-catalog tests compare
temporary databases at fixed revisions) and every caller of a `record_lease_deposit_receipt` or
`record_receipt` name (the other `record_receipt` names are local receipt-correction helpers):
none expected to change beyond the revision strings.

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump for the pre-code check (read only; no `REDACTED` markers) |
| FF1/FC1/L1/Y1 | passed (formatter first: one file reformatted; long-line search first, two test lines rewrapped before the lint) |
| M1 | passed (`20261228_154` head) |
| T1 | 43 passed (the new module, `test_deposit.py`, `test_deposit_migration.py`) |
| U1 | 3856 passed (includes `test_traceability.py`) |
| M2 | passed |
| P1 | 2281 passed (the known Starlette deprecation warning) |
| FF2/FC2/L2/Y2 | passed (after the round 1 fixes; long-line search first, one test line rewrapped before the lint) |
| M3 | passed (after the round 1 migration change) |
| T2 | 35 passed (the new module, `test_deposit.py`) |
| U2 | 3856 passed (includes `test_traceability.py`; after the round 1 fixes) |
| M4 | passed |
| P2 | 2287 passed (the known Starlette deprecation and Pydantic alias warnings) |
| FF3/FC3/L3/Y3 | passed (after the round 2 fixes; long-line search first, none) |
| M5 | passed (after the round 2 migration text change) |
| T3 | 117 passed (the new module, `test_deposit.py`, `test_traceability.py`, `test_late_payment.py`: every file changed since P2, and both tests that read the traceability manifest) |
| U3 | 3856 passed (includes `test_traceability.py`; before round 3) |
| M6 | passed |
| P3 | 2289 passed (the known Starlette deprecation warning): the full run after the last code and test change, before the round 3 verdicts |
| FF4/FC4/L4/Y4 | passed (after the round 3 text fixes: one test docstring; long-line search first, none) |
| T4 | 93 passed (the new module, `test_traceability.py`, `test_late_payment.py`: every file changed since P3, text only, and both tests that read the traceability manifest) |

Full outputs of every targeted and full run, each attempt in its own file, are in
`~/Development/prm-run-logs/v1-056-10e-2b-4b-2b-*.txt` (format, lint and type checks are short and
not saved).

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: no blocker; two should-fix (tests); eleven notes.

- S1 (fixed, tests): the race claims were untested. Added
  `test_a_closure_committed_while_the_writer_waits_is_read_after_the_deposit_lock` (both orders:
  a Security receipt waiting for the closing confirm reads P5S01, not the forfeiture; a Pet receipt
  holding the Deposit first makes the waiting confirm stale) and
  `test_a_forfeiture_committed_while_the_writer_waits_refuses_the_receipt`.
- S2 (fixed, test): no passing case on a TERMINATED Lease or after a reversed forfeiture. Added
  `test_on_a_terminated_lease_a_receipt_passes_until_closure_and_after_a_forfeiture_reversal`.
- N1, N2 (fixed, text): the input check runs before the lock and the replay; the reason bound is
  new, not a table rule (plan reading (5)).
- N3 (fixed, text): `app.assert_active_financial_actor` does not check the Property for a human;
  the service checks the Property scope (migration docstring, docs/004).
- N4 (fixed, tests): pinned P0002 messages for an unknown Deposit and Payment, an unknown actor
  (55000), a nil Deposit id (22023). The fixtures share one Property, so a Deposit of another
  Property cannot be built here.
- N5 (slice 11 note): 55P03 and 40P01 read as unavailable in the Deposit service; the new 55000
  refusals read as invalid; slice 11 words them as conflicts and "try again".
- N6 (slice 12 open item): the receipt time follows only the Deposit's events; a one-call
  forfeiture that waited is dated before the receipt that committed first.
- N7 (fixed, text): docs/004 "only Pet Deposit receipt writer"; docs/005 "evidence" (the receipt
  keeps a reason); the service docstrings say "signed or terminated".
- N8 (fixed): upstream ids of the new traceability entries.
- N9 (kept, recorded): the committed test name
  `test_deposit_acl_uses_only_financial_command_role_and_withholds_receipt_recording` reads less
  exactly now, but its traceability entry (the 1,212th) is among the first 1,598 entries, which are
  never edited, so it is not renamed; its assertions stay true.
- N10 (fixed): owner process rule (5) also recorded in ops/V1_055_RUN_RULES.md.
- N11 (accepted): test 1's one-microsecond assertion needs the call within 4 seconds of the hand
  insert; the insert is now right before the call.

Security: one blocker, two should-fix, nine notes.

- B1 (fixed, code; a design change the reviewer proposed, to be confirmed in round 2): the writer
  ignored a Payment's confirmed Invoice or Late-payment Charge intent (BR-PAY-024, BR-PAY-026; the
  allocation check refuses any other target). Path: a 10,000 Payment confirmed for the Initial Rent
  Invoice recorded by one staff member as a Security Deposit receipt; the Invoice stays owed, the
  unpaid-Initial ground then lets the termination keep the Deposit with that 10,000. Now refused
  (55000, "A Payment confirmed for an Invoice or a Late-payment Charge is not a Deposit receipt"),
  the last check before the insert. Test:
  `test_a_payment_confirmed_for_an_invoice_is_not_a_deposit_receipt` (the reviewer's set-up below).
- S2 (question and test): a Deposit funded by two Payments has no way out when one bounces while a
  Refund from it is not returned (the shared-Deposit guard of owner answer 2 to Q-2026-10-11-81,
  whose premise "every Deposit has one receipt" this writer ends). Fails closed; who pays would
  change with any fix, so Q-2026-10-18-127 (recommendation (a): charge back only the shortfall),
  a known limit in the slice 12 list, and
  `test_a_deposit_funded_by_two_payments_keeps_the_shared_deposit_refusal`.
- S3 (fixed, tests): the closure race and the stale closing confirm (as independent S1) and a
  pending forfeiture draft made stale by a receipt:
  `test_a_receipt_makes_a_pending_forfeiture_draft_stale`.
- Notes 4, 5, 8, 12 (for the owner, in the report and docs/010): a receipt after a keep-ground
  termination becomes money the approver must forfeit (a slice 11 screen warning); a receipt is
  dated when staff record it; a Pet Deposit receipt is accepted after a recorded departure; a
  third-party Payment naming only the Lease funds the tenant's Deposit.
- Notes 6, 7, 9, 10 (slice 12 open items): the receipt time could also follow the Payment's
  confirmation and latest event; a Payment named by a pending return draft is not refused; the
  audit event's state is the Deposit snapshot only; a service principal passes the actor check.
- Note 11 (slice 11 note): what a `payments.allocate` holder may see; P5S01 now reads as a conflict
  for every Deposit command (docs/005).

### Round 1 test set-ups (written in full, run rule of 2026-10-13)

- Closure while the writer waits (independent S1 (a), security S3 (a)): `case = pet_lease_case(url)`
  (TERMINATED Lease, Security forfeited through the draft, Pet holds 0, Settlement started);
  `draft = record_settlement(case, ())`; a 5,000 Payment of the Security Deposit's Customer; on a
  financial-role connection run `SELECT app.confirm_final_settlement_draft(prop, human, draft_id,
  'financial.approve')` without committing; in a `ThreadPoolExecutor(1)` call the writer for the
  Security Deposit (5,000); `wait_until_blocked_by(url, closing)`; commit; expect
  `("P5S01", CLOSED)` and `written == (1, 0, 0)`.
- Receipt first (independent S1 (b), security S3 (b)): a second `pet_lease_case`, its no-step
  draft, a 5,000 Payment of the Pet Deposit's Customer; the writer for the Pet Deposit on a
  financial-role connection without committing; in a thread `confirm_settlement(case, draft)`;
  wait until it is blocked; commit; expect `FinalSettlementStaleDraftError`, `closed_at` NULL, the
  Pet Deposit holding 5,000 and `written == (1, 1, 1)`.
- Forfeiture while the writer waits (independent S1 (c)): `recovered_case(url, 15_000)`, `void`,
  `terminate`; a 5,000 Payment; on an owner connection `one_call(case, 15_000)` without
  committing; the writer in a thread; wait; commit; expect `("55000", FORFEITED)`, the receipt
  count unchanged, held 0.
- Terminated Lease and reversed forfeiture (independent S2): `pet_lease_case`; the Lease is
  TERMINATED; a 5,000 Pet receipt through the service passes; a 5,000 Security receipt is refused
  (FORFEITED); `reverse_through_draft(deposits, disposition)`; the same Security receipt passes.
- Pending forfeiture draft (security S3 (c), built on the restoration fixture):
  `recovered_case(url, 15_000)`, `void`, `terminate`; `LeaseDepositForfeitureService.record` of
  the whole held amount; a 3,000 receipt passes; the draft's confirm raises the forfeiture
  service's invalid or conflict error; no forfeiture, held 18,000.
- Intent (security B1): `signed_with_initial(url, this_month(url))`; `named` = the Customer's
  10,000 Payment with `invoice_id` the Initial Rent Invoice; `third` = a 10,000
  `THIRD_PARTY_IDENTIFIED` Payment of another Customer with the Lease and that Invoice;
  `lease_only` = the same third-party Payment without the Invoice; `named` and `third` refused
  (55000, the new message), nothing written, both still 10,000 available; `lease_only` passes
  (Security holds 20,000).
- Shared Deposit (security S2): `pet_case`; two 10,000 Payments recorded into the Pet Deposit
  through the service; departure, qualified review and a 15,000 Pet Refund-review Refund (held
  5,000); the first Payment's return draft is refused (55000, the shared-Deposit message); the
  owner path reversal of the second receipt is refused ("Deposit receipt has active dependent
  financial history"); no reversal, held 5,000.

## Review round 2 (fresh read-only subagents, during P2; same instructions)

Independent: no blocker; three should-fix; six notes. Security: no blocker; two should-fix; four
notes. Both confirmed the round 1 design change (the intent refusal) needed and safe: it only
refuses, after the locks, on columns that never change, and it matches the allocation rule.

- Independent SF-1 (fixed, text; new question): the wording "goes only to its identified target"
  holds for Allocations only; what is left after the target may become Credit or a Refund, and the
  writer refuses the whole Payment, leftover included. Reworded in the migration docstring and
  comment, docs/004, docs/010, the plan, the traceability note and the test docstring; new
  Q-2026-10-18-128 (recommendation (b): allow the leftover once the named target has nothing
  outstanding, under the Credit path's checks); a slice 12 known limit until answered.
- Independent SF-2 and security note 3 (fixed, test): the stale forfeiture draft test pins the
  refusal (23514, "Lease Deposit forfeiture draft is stale") and that the draft stays PENDING.
- Independent SF-3 (done): T3 ran every file changed since P2 and both tests that read the
  traceability manifest.
- Security SF-1 and independent N-2 (fixed, test): the Late-payment Charge branch of the intent
  refusal had no test. `seed_payment` gains an optional `late_payment_charge_id`;
  `test_a_payment_confirmed_for_a_late_payment_charge_is_not_a_deposit_receipt` (set-up below).
- Security SF-2 (fixed, text and test): after closure every two-Payment Deposit is stuck, with or
  without a Refund, because the `RETURNED_PAYMENT` correction and the receipt correction require
  the Deposit to end empty; the bounced Payment stays RECEIVED and its unused value stays usable.
  Q-2026-10-18-127 and the slice 12 known limit now say so (option (a) also changes the two "ends
  empty" rules; an interim option (c) is named and not recommended);
  `test_after_closure_a_deposit_funded_by_two_payments_keeps_a_bounced_payment_received` (set-up
  below).
- Independent N-1 (fixed, test): the closure race part (b) pins P5S02.
- Independent N-3 and N-4, security note 2 (owner, in Q-2026-10-18-128 and the slice 12 list): a
  Payment that names nothing can still fund a Deposit while the Initial Rent is owed (staff
  discretion); `app.create_reservation` and the receipt correction's writer do not read the
  designation; a table-level check would be a tightening.
- Independent N-5 (fixed, test): the shared-Deposit test also shows the return draft accepted
  before closure once the Refund came back in full.
- Independent N-6 (fixed, text): the record's entry numbering; two docs/004 wraps.
- Security note 1 (slice 12 list): no test makes the writer wait on the Payment lock; the order
  holds by reading.
- Security note 4 (fixed, unit test): `payments.allocate` granted for another Property is refused
  before any connection.

### Round 2 test set-ups

- Late-payment Charge intent (security SF-1): `overdue_case(url)` (a Late-payment Charge of its
  Customer; the shared Property); `signed_with_initial(url, this_month(url))` for a Security
  Deposit; a 10,000 Payment of the overdue Customer with only `late_payment_charge_id` set; the
  writer refuses it (55000, the intent message) before the receipt table's checks (without the
  Charge branch the table would refuse it as another Customer's Payment, 23514); nothing written;
  the Payment still has 10,000 available.
- After-closure two-Payment Deposit (security SF-2): `pet_lease_case`; two 5,000 Payments recorded
  into the Pet Deposit through the service; `forfeit_through_draft(deposits, pet)` keeps 10,000;
  `closed(case)`; the first Payment's `RETURNED_PAYMENT` correction is refused (55000, "A Deposit
  this Payment funded would still hold money after the return"); its ordinary return draft is
  refused (55000, relied on); the draft, correction, return and reversal counts are unchanged and
  the Payment stays RECEIVED.

## Review round 3 (fresh read-only subagents, during P3; same instructions)

Security: clean (no blocker, no should-fix); three notes. Independent: no blocker; one should-fix,
text only; six notes. Under the round-3 rule of 2026-10-16 (text fixes and new assertions only),
fixed without a round 4:

- Independent S1 (fixed, text): Q-127 option (c) understated its cost; it would also stop every
  later Security Deposit receipt from a new Payment and any Pet Deposit paid by more than one
  Payment.
- Independent N1 (fixed, text): Q-127 and the plan said the return "passes"; the test shows the
  return draft accepted before closure (the confirm is by reading).
- Independent N2 (fixed, text): the shared-Deposit test's docstring and traceability note name the
  round 2 extension.
- Independent N3 and security N2 (fixed, text): under Q-127 option (a), the existing correction
  reverses a funded Deposit's whole forfeiture; the sub-slice that builds (a) keeps the other
  Payment's share where the closed Settlement put it, or asks first.
- Independent N4 and security N3 (fixed, text): Q-128 cites BR-CREDIT-004 and names the wrong-Unit
  move exception; Q-127 says the unused value can also become Credit or a Refund.
- Independent N5 (done): U3 and P3 ran after the round 2 fixes (run table).
- Independent N6 (kept): two uneven docs/004 wraps; they render as one paragraph.
- Security N1 (text, for the owner): one staff member can reach the before-closure Q-127 state on
  purpose (record another Payment into a Pet Deposit whose Refund is out, before the bounced
  Payment's return is confirmed), which blocks that Payment's charge-back; a loss to the Property,
  never a second charge to the Customer. Q-127 gains option (d), refuse a receipt into a Deposit
  with a Refund not fully returned (`app.deposit_has_unresolved_refund`), recommended until (a) is
  built; nothing is built before the owner's answer.
