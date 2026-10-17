# V1-056 sub-slice 10e-2b-4d — a Payment's leftover into a Deposit, no receipt while a Refund is out, and none after a termination that keeps the Deposit — review record

Sub-slice: 10e-2b-4d (owner answers of 2026-10-18 to the 10e-2b-4b-2b report: answer 1, option (d)
of Q-2026-10-18-127; answer 2, option (b) of Q-2026-10-18-128; answer 3 waits for
Q-2026-10-18-131). Migration `20261230_156` (one exact-text patch of the receipt writer). Base
commit: 31fbd5a. Built on 2026-10-18; stopped after review round 1 (record, plan and questions
committed in 8b03750). Finished on 2026-10-18 in a fresh session after the owner answers (a) to
Q-2026-10-18-131 and (b) to Q-2026-10-18-132 (sections below the round 1 set-ups). Not pushed.

## Built (in the working tree)

- Migration `20261230_156_deposit_receipt_leftover_and_refund_out.py`: `app.record_lease_deposit_receipt`
  calls `app.assert_payment_excess_eligible` for a Payment confirmed for an Invoice or a
  Late-payment Charge (instead of refusing the whole Payment), placed before the Payment lock
  (round 1 finding: wrong place, see below); refuses a receipt into a Deposit with a Refund that is
  not fully returned (`app.deposit_has_unresolved_refund`, 55000).
- Service: the Deposit service maps 55P03 to a conflict (round 1 finding: DL-067 asks for the
  bounded retry instead, see below).
- Tests: new module `test_deposit_receipt_leftover_migration.py` (three tests); a unit test of the
  55P03 mapping in `test_deposit.py`; committed tests changed: the two intent tests of
  `test_deposit_receipt_record_migration.py` renamed (`..._an_owed_invoice_...`,
  `..._an_owed_late_payment_charge_...`) with their refusal now 23514 and the excess message
  (constant `INTENT` renamed `EXCESS`); 27 head-revision strings to `20261230_156`.
- Docs: docs/004 DB-DEP-002 paragraph, docs/005 note (working tree); plan pre-code design and
  Q-2026-10-18-131 (committed with this record).

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump (`app.record_lease_deposit_receipt` after 4c, `app.lease_termination_forfeiture_rule`; no `REDACTED` markers) |
| M1 | passed (`20261230_156` head) |
| FF1/FC1/L1/Y1 | passed (formatter: no change; long-line search first, one docstring rewrapped before the lint) |
| T1 | 133 passed (the new module, the 4b and 4c modules, `test_deposit.py`, `test_credit_migration.py`, `test_traceability.py`) |
| U1 | 3866 passed |
| M2 | passed |
| P1 | 2 failed, 2304 passed: `test_refund_migration.py::test_usd_refund_correction_rejects_unverified_or_inconsistent_value[changes2]` and `[changes4]`, both `psycopg.errors.LockNotAvailable: could not obtain lock on relation "app.invoice_lines"` from the `NOWAIT` lock in `app.assert_payment_excess_eligible`, reached through `app.validate_general_refund_source` by the test's direct Refund insert. Outside the sub-slice: the module is listed 169th in `scripts/database-test.sh` and ran before every module this sub-slice changes, except the revision-string modules, which only assert the head revision; no 4d change touches that path. The known intermittent failure of DL-067 (Q-2026-10-05-26, Q-2026-10-09-62, Q-2026-10-13-102); this test is not yet on the slice 12 list. Stop condition: Q-2026-10-18-132 |
| FF2/FC2/L2/Y2 | passed (fresh session, after the round 1 fixes and the Q-131 answer; formatter first, no change; long-line search first, none) |
| M3 | passed |
| T2 | 138 passed (`test_deposit.py`, `test_traceability.py`, `test_credit_migration.py`, the 4b, 4c and new modules, in the suite's order) |
| U2 | 3866 passed |
| M4 | passed |
| P2 | 2311 passed (the passing full run after P1; `test_refund_migration.py` passed in full) |
| FF3/FC3/L3/Y3 | passed (after the round 2 fixes; formatter no change; long-line search first, none) |
| M5 | passed (after the nested IF) |
| T3 | 141 passed (T2's set) |
| U3 | 3866 passed (before round 3) |
| M6 | passed |
| P3 | 2314 passed (the full run after the last code and test change, before the round 3 verdicts) |
| UT1 | 28 passed (`test_traceability.py`, after the round 3 text fix of two traceability notes) |

Full outputs in `~/Development/prm-run-logs/v1-056-10e-2b-4d-*.txt`.

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: no blocker, 4 should-fix, notes. Security: no blocker, 2 should-fix, 4 notes. Both
confirmed: the build matches answers 1 and 2; money in cents; append-only; capabilities unchanged;
the committed test changes are exactly the two renames, docstrings, the three refusal
expectations and the constant; no other committed test needed to change; Q-131 is right that
answer 3 changes committed tests. All findings below were fixed after the owner's answers (see
"Round 1 fixes" below).

1. Lock order (independent S1, security S1): NOWAIT only keeps the table lock from waiting; called
   before the Payment lock, the check holds SHARE on twelve obligation tables while the writer
   waits for the Payment guard and row, the Reservation and the Deposit. A writer that locks the
   Payment first and then writes an obligation table (`app.post_payment_allocations`,
   `app.confirm_payment_return`) then deadlocks with it (40P01), and while the receipt waits (up to
   the 3 s lock timeout) every invoice, allocation, Credit and late-fee writer in every Property is
   blocked. The Credit path locks the Payment first and then calls the check. Fix: call the check
   after the Deposit lock (before or after the Refund-out refusal); docs/004, docs/005, the plan
   and the migration docstring to match.
2. DL-067 bounded retry (independent S2, security note 3): the owner's decision of 2026-10-03 says
   the services whose commands reach `app.assert_payment_excess_eligible` replay the command after
   55P03, at most three times, each attempt on its own connection with the same key, and raise
   Unavailable after the last; the Deposit service does not, and its new 55P03 mapping (conflict)
   covers every Deposit command and a lock timeout too. Fix: `retry_lock_not_available` around the
   receipt command; Unavailable after the last attempt, as DL-067 says; withdraw the conflict
   mapping; tests below.
3. Q-131 is incomplete (independent S3): answer 3 also changes
   `test_a_receipt_makes_a_pending_forfeiture_draft_stale` (its 3,000 receipt after the pet
   noncompliance termination; under (a) its scenario cannot be reached through the writer at all,
   because forfeiture drafts exist only under such a ground), the second half of
   `test_a_closure_committed_while_the_writer_waits_is_read_after_the_deposit_lock` (a Pet receipt
   that makes the closing confirm stale) and `test_after_closure_a_deposit_funded_by_two_payments_keeps_a_bounced_payment_received`
   (two Pet receipts after the termination); messages may change in the FORFEITED assertion and
   the forfeiture-wait test, depending on where the refusal goes.
4. docs/010 as-built and updated-tests entries (independent S4): for the commit.
5. Real-path lock tests (security S2): the 55P03 behaviour is shown only by a monkeypatched unit
   test; set-ups below.

Notes: the error order changes for a named Payment with an unknown or closed Deposit (removed by
fix 1); optional coverage (a Late-payment Charge leftover; a named Invoice paid while its own
Charge is owed; a third-party leftover; the Security Deposit of the same Lease while the Pet
Deposit's Refund is out); option (d) can be dodged by reversing a verified return after the second
receipt (one person with `refunds.correct`, `refunds.corrections.reverse` and `payments.allocate`;
fabricated evidence; audited; option (a) closes it; a known limit, test below); two designation
dodges inherited from the Credit check (a temporary allocation of another Payment; a designation to
a DRAFT Invoice), both ending in a state reachable with an undesignated Payment (slice 11 warning,
unless the owner wants DRAFT designations refused).

### Round 1 test set-ups (written in full, run rule of 2026-10-13)

Independent S1 (deadlock with the allocation writer; imports: ThreadPoolExecutor; `owner` and
`wait_until_blocked_by` from `test_pet_payback_restoration_refusal_migration`):

```python
def test_the_excess_check_takes_its_locks_after_the_payment_and_deposit_locks(migrated_database_url: str) -> None:
    url = migrated_database_url
    source = signed_with_initial(url, this_month(url))
    human, prop, security = source["actor"], source["property"], source["deposit"]
    line, owed = rent_line(url, source["invoice"])
    with psycopg.connect(url) as connection:
        transfer = seed_payment(connection, actor_id=human, property_id=prop, customer_id=source["customer"],
                                amount=owed + 5_000, invoice_id=source["invoice"])
    allocation_service().post(prop, transfer, allocation_designated(source["invoice"], line, owed),
                              actor=allocation_actor(human, prop))
    with psycopg.connect(owner()) as allocating:
        allocating.execute("SELECT app.serialize_payment_state(%s)", (transfer,))
        allocating.execute("SELECT 1 FROM app.payments WHERE id=%s FOR UPDATE", (transfer,))
        with ThreadPoolExecutor(1) as pool:
            waiting = pool.submit(attempt, prop, human, security, transfer, 5_000)
            wait_until_blocked_by(url, allocating)
            allocating.execute("LOCK TABLE app.payment_allocations IN ROW EXCLUSIVE MODE")
            allocating.rollback()
            assert waiting.result(timeout=60) == (None, None)
    assert written(url, security) == (2, 1, 1)
```

Security S1 (the same with the Payment return's table, and the held SHARE locks counted):

```python
def leftover_case(url: str) -> dict[str, Any]:
    source = signed_with_initial(url, this_month(url))
    human, prop = source["actor"], source["property"]
    line, owed = rent_line(url, source["invoice"])
    with psycopg.connect(url) as connection:
        transfer = seed_payment(connection, actor_id=human, property_id=prop, customer_id=source["customer"],
                                amount=owed + 5_000, invoice_id=source["invoice"])
    posted = allocation_service().post(prop, transfer, allocation_designated(source["invoice"], line, owed),
                                       actor=allocation_actor(human, prop))
    allocation = UUID(str(cast(list[Any], posted["allocation_ids"])[0]))
    assert value(url, AVAILABLE, transfer) == 5_000
    return {**source, "transfer": transfer, "allocation": allocation, "line": line}


def test_a_leftover_receipt_waiting_for_the_payment_holds_no_obligation_table_lock(migrated_database_url: str) -> None:
    url = migrated_database_url
    case = leftover_case(url)
    human, prop, security, transfer = case["actor"], case["property"], case["deposit"], case["transfer"]
    before = held(url, security)
    with psycopg.connect(url) as holder:
        holder.execute("SELECT app.serialize_payment_state(%s)", (transfer,))
        holder.execute("SELECT 1 FROM app.payments WHERE id=%s FOR UPDATE", (transfer,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(attempt, prop, human, security, transfer, 5_000)
            try:
                wait_until_blocked_by(url, holder)
                share_locks = value(url,
                    "SELECT count(*) FROM pg_catalog.pg_locks held_lock WHERE held_lock.locktype='relation' "
                    "AND held_lock.granted AND held_lock.mode='ShareLock' "
                    "AND held_lock.relation='app.payment_allocation_reversals'::regclass "
                    "AND %s=ANY(pg_catalog.pg_blocking_pids(held_lock.pid))", holder.info.backend_pid)
                assert share_locks == 0
                holder.execute("SET LOCAL lock_timeout='500ms'")
                holder.execute("LOCK TABLE app.payment_allocation_reversals IN ROW EXCLUSIVE MODE")
            finally:
                holder.rollback()
            assert waiting.result(timeout=30) == (None, None)
    assert held(url, security) == before + 5_000
```

Independent S2 (the retry; the error after the last attempt as DL-067 decides):

```python
def test_a_receipt_is_replayed_after_a_nowait_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    property_id, actor_id = uuid4(), uuid4()
    attempts: list[None] = []
    def refuse(*_a: object, **_k: object) -> None:
        attempts.append(None)
        raise psycopg.errors.LockNotAvailable("could not obtain lock")
    monkeypatch.setattr("property_rental.deposit.psycopg.connect", refuse)
    monkeypatch.setattr("property_rental.lock_retry._pause", lambda _s: None)
    service = PostgresDepositService("postgresql://unused", property_id, actor_id)
    allocator = AuthenticatedActor(actor_id=str(actor_id), capability_grants=frozenset(
        {CapabilityGrant(PAYMENT_ALLOCATE_CAPABILITY, frozenset({str(property_id)}))}))
    with pytest.raises(DepositServiceUnavailableError):
        service.record_receipt(RecordDepositReceiptCommand(uuid4(), uuid4(), uuid4(), uuid4(), 100, "Paid"), actor=allocator)
    assert len(attempts) == 4


def test_the_excess_check_refuses_at_once_while_an_obligation_table_is_written(migrated_database_url: str) -> None:
    url = migrated_database_url
    source = signed_with_initial(url, this_month(url))
    human, prop, security = source["actor"], source["property"], source["deposit"]
    with psycopg.connect(url) as connection:
        named = seed_payment(connection, actor_id=human, property_id=prop, customer_id=source["customer"],
                             amount=10_000, invoice_id=source["invoice"])
        unnamed = seed_payment(connection, actor_id=human, property_id=prop, customer_id=source["customer"], amount=5_000)
    service = PostgresDepositService(financial_database_url(), prop, human)
    with psycopg.connect(owner()) as writing:
        writing.execute("LOCK TABLE app.invoice_lines IN ROW EXCLUSIVE MODE")
        started = time.monotonic()
        assert attempt(prop, human, security, named, 5_000)[0] == "55P03"
        assert time.monotonic() - started < 2
        with pytest.raises(DepositServiceUnavailableError):
            service.record_receipt(receipt_command(security, named, 5_000), actor=allocator(human, prop))
        assert attempt(prop, human, security, unnamed, 5_000) == (None, None)
        writing.rollback()
    assert (written(url, security), value(url, AVAILABLE, named)) == ((2, 1, 1), 10_000)
```

Security S2 (an uncommitted allocation reversal; after the retry fix the service error is the
post-retry one):

```python
def test_an_uncommitted_allocation_reversal_keeps_the_leftover_out_of_the_deposit(migrated_database_url: str) -> None:
    url = migrated_database_url
    case = leftover_case(url)
    human, prop, security, transfer = case["actor"], case["property"], case["deposit"], case["transfer"]
    before = held(url, security)
    service = PostgresDepositService(financial_database_url(), prop, human)
    with psycopg.connect(url) as holder:
        holder.execute("SELECT app.reverse_payment_allocation_command(%s,%s,%s,%s,%s,%s)",
                       (prop, case["allocation"], human, uuid4(), "b" * 64, "Allocation posted in error"))
        assert attempt(prop, human, security, transfer, 5_000)[0] == "55P03"
        with pytest.raises(DepositConflictError):   # DepositServiceUnavailableError after the DL-067 retry
            service.record_receipt(receipt_command(security, transfer, 5_000), actor=allocator(human, prop))
        holder.commit()
    assert value(url, "SELECT app.invoice_line_outstanding(%s)", case["line"]) > 0
    assert attempt(prop, human, security, transfer, 5_000) == ("23514", EXCESS)
    assert (held(url, security), written(url, security)) == (before, (1, 0, 0))
```

Independent note 2 (a Refund committed while the writer waits; imports `cash` from
`refund_test_support`, `command as pet_refund_command` from `test_pet_refund_migration`):

```python
def test_a_refund_committed_while_the_writer_waits_refuses_the_receipt(migrated_database_url: str) -> None:
    url = migrated_database_url
    case = pet_case(url)
    human, prop, pet = case["human"], case["prop"], case["pet"]
    case["service"].record_receipt(receipt_command(pet, payment(url, human, pet, 10_000), 10_000), actor=allocator(human, prop))
    review = qualify_review(case)
    refunds = refund_service()
    preparer = actor(human, prop, "refunds.create")
    draft = refunds.record_pet_draft(prop, pet_refund_command(pet, review, 10_000), cash(refunds, prop, preparer), actor=preparer)
    later = payment(url, human, pet, 10_000)
    with psycopg.connect(financial_database_url()) as confirming:
        confirming.execute("SELECT app.confirm_refund_draft(%s,%s,%s,'financial.approve')", (prop, human, UUID(str(draft["draft_id"]))))
        with ThreadPoolExecutor(1) as pool:
            waiting = pool.submit(attempt, prop, human, pet, later, 10_000)
            wait_until_blocked_by(url, confirming)
            confirming.commit()
            assert waiting.result(timeout=60) == ("55000", REFUND_OUT)
    assert (written(url, pet), value(url, AVAILABLE, later)) == ((1, 1, 1), 10_000)
```

Security note 1 (the known limit of option (d); imports `ReverseRefundCorrectionCommand` from
`property_rental.refund`, `return_refused` from `test_payment_return_recovery_migration`, `SHARED`
from the 4b module):

```python
def test_a_reversed_refund_return_leaves_a_later_receipt_in_a_deposit_whose_refund_is_out(migrated_database_url: str) -> None:
    url = migrated_database_url
    case = pet_case(url)
    human, prop, pet = case["human"], case["prop"], case["pet"]
    service: PostgresDepositService = case["service"]
    first = payment(url, human, pet, 10_000)
    service.record_receipt(receipt_command(pet, first, 10_000), actor=allocator(human, prop))
    refund = review_refund(case, qualify_review(case), 10_000)
    refund_service().verify_usd_return(prop, refund, returned(10_000), actor=actor(human, prop, "refunds.correct"))
    later = payment(url, human, pet, 10_000)
    service.record_receipt(receipt_command(pet, later, 10_000), actor=allocator(human, prop))
    correction = UUID(str(value(url, "SELECT id FROM app.refund_corrections WHERE refund_id=%s "
                                     "AND correction_kind='VALUE_CORRECTION'", refund)))
    refund_service().reverse_correction(prop, refund, correction,
        ReverseRefundCorrectionCommand(uuid4(), "Synthetic evidence", "Return recorded in error"),
        actor=actor(human, prop, "refunds.corrections.reverse"))
    assert value(url, "SELECT app.deposit_has_unresolved_refund(%s)", pet) is True
    assert held(url, pet) == 10_000
    assert return_refused(prop, human, first) == ("55000", SHARED)
```

## Owner answers of 2026-10-18 (fresh session) and the round 1 fixes

Owner answers: Q-2026-10-18-132 (b), finish 4d, and a standing run rule for the known
`LockNotAvailable` failure in a module the sub-slice does not change (rerun only those tests once);
Q-2026-10-18-131 (a), answer 3 as written, also after a forfeiture reversal; Q-129 (a); Q-130 (a),
its own sub-slice before 10g-2; the 4c reading and design changes accepted; the option (d) dodge
by reversing a verified return accepted as a known limit (Q-127 (a), 10e-2b-4e, closes it).

Round 1 fixes: (1) lock order: the excess check runs after the Payment and Deposit locks and the
active-forfeiture refusal (migration replacement 1 removed; the second replacement now holds the
three checks); (2) DL-067: `PostgresDepositService.record_receipt` replays the command after 55P03
at most three times (`retry_lock_not_available`; `_fetch` split into `_attempt` and `_fetch`), then
`DepositServiceUnavailableError`; the 55P03 conflict mapping is withdrawn; (3) Q-131 listed every
committed test; (4) docs/010 entries; (5) the real-path lock tests (the round 1 set-ups; the
security S2 set-up adapted: the allocation reversal holds the Payment, so the receipt waits and
then reads the committed reversal, 23514, instead of meeting 55P03). Q-131 (a) built: after the
active-forfeiture refusal, a TERMINATED Lease whose `app.lease_termination_forfeiture_rule` keeps
the Deposit type refuses the receipt (55000, "The Lease's termination ground keeps this Deposit;
this receipt is not recorded here"); it sits after the forfeiture refusal, so the committed
FORFEITED expectations and the forfeiture-wait test keep their message. Not built: the security
note 1 known-limit test of the option (d) dodge (10e-2b-4e closes the dodge and would change it).

Committed tests changed (owner standing rules; names, old and new results in docs/010): in
`test_deposit_receipt_record_migration.py` the two intent tests (renamed in the first session;
23514), `test_on_a_terminated_lease_whose_ground_keeps_the_deposit_a_receipt_is_refused` (renamed
from `test_on_a_terminated_lease_a_receipt_passes_until_closure_and_after_a_forfeiture_reversal`;
both receipts refused), `test_a_receipt_makes_a_pending_forfeiture_draft_stale` (the writer refuses;
its stale checks kept on a hand-built receipt, confirmed by both round 2 reviewers), the second
half of `test_a_closure_committed_while_the_writer_waits_is_read_after_the_deposit_lock` (a
voluntary early termination), `test_after_closure_a_deposit_funded_by_two_payments_keeps_a_bounced_payment_received`
(receipts before the termination); new helper `terminated_pet_lease_case`; 27 revision strings.
The new unit test of the first session (`test_a_nowait_lock_conflict_of_a_deposit_command_is_a_conflict`,
never committed) became `test_a_receipt_is_replayed_after_a_nowait_refusal`.

## Review round 2 (fresh read-only subagents, during P2; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: no blocker, 2 should-fix, 6 notes. Security: no blocker, 2 should-fix, 6 notes. Both
confirmed the lock order (no wait after the NOWAIT SHARE locks: the insert triggers re-take only
the Payment, Deposit and actor locks already held) and the replay as needed and safe (the
design-change rule), the Q-131 refusal as the owner wrote it, the committed test changes (nothing
weaker), and that the stale-confirm checks are worth keeping (the only committed test of the
forfeiture confirm's stale refusal on a change of the held amount; the ground refusal lives only
in the writer, so the confirm's re-read is the table-level guard).

Should-fix (all tests and text; fixed under the round-3 rule of 2026-10-13):
- Independent S1 / security S2: the 55P03 test could hang (calls on the lock holder's thread with
  no lock timeout) and did not prove the replay. Fixed: every call in a worker with a time limit,
  the rollback in a `finally`, the replay's pauses counted (`[0.25, 0.5, 1.0]`).
- Security S1: new `test_a_receipt_refused_by_the_nowait_lock_is_recorded_once_by_its_replay`
  (the reviewer's set-up: the obligation table writer ends during the first pause; the receipt is
  recorded once; a repeat is an exact replay).
- Independent S2: the plan's slice 11 receipt-route notes, the Q-127 and Q-128 known limits, docs/004
  ("after the Payment and Deposit locks").

Notes taken: the ground check as a nested IF (security N6); new
`test_a_leftover_receipt_waiting_for_the_deposit_holds_no_obligation_table_lock` (security N4, the
reviewer's set-up); the receipt beside an uncommitted termination as a known limit with
`test_a_receipt_beside_an_uncommitted_termination_is_recorded_known_limit` (both N1; the security
reviewer's set-up) and new Q-2026-10-18-133 (also the termination dated earlier than its entry);
the docstring and docs/005 say every receipt command is replayed after any 55P03 (independent N4,
security N5); slice 12 list: a second receipt while a Pet Refund draft is pending escapes option
(d) (security N2; 10e-2b-4e closes it), `app.confirm_refund_draft` takes the excess check before
the Payment lock (security N3, pre-existing), more exposure to the known `LockNotAvailable`
(independent N3). For the owner (independent N2): the ground refusal also refuses money received
before the termination but recorded after it; that money becomes a normal Payment. Not taken:
independent N5 (count every ShareLock in schema `app` instead of the twelve tables; the list is
the check's own list) and N6 (optional coverage).

Round 2 test set-ups: each was built as the reviewer gave it (the tests named above are the
set-ups), except the 55P03 test, which joins both reviewers' versions (worker pool and time limits
from security S2, the counted pauses from independent S1).

## Review round 3 (fresh read-only subagents, during P3; same instructions)

Independent: no blocker, no should-fix; 8 notes. Security: no blocker, no should-fix; 5 notes.
Both: every round 2 fix right and complete; the migration's before text matches the writer byte
for byte; the nested IF valid and of the same meaning; no new risk; docs, plan, Q-133 and
traceability accurate.

Notes taken (text only, under the round-3 text rule of 2026-10-16; no code, migration or fixture
change): two traceability notes say the whole-Payment refusal held until 10e-2b-4d; docs/010 item
(3) says the Deposit still holds 15,000; Q-133 says the termination locks the Lease and Unit rows;
docs/004 names the termination dated earlier than its entry and the fail-closed 22023 for an
ambiguous termination record. Not taken (test hygiene, for slice 12): two waiting tests
(`test_an_allocation_reversal_committed_while_the_writer_waits_keeps_the_leftover_out`,
`test_a_refund_committed_while_the_writer_waits_refuses_the_receipt`) call `wait_until_blocked_by`
outside a `try`/`finally`, as committed tests do (a hang only if the worker reached its wait after
the 10 s deadline); the fourth attempt's sqlstate of the 55P03 test is not asserted; the replay test
cannot tell NOWAIT from a lock timeout (the 55P03 test covers it). For Q-133 (security N2): when
option (a) is built, take the termination time after the Deposit locks.
