"""A Payment's leftover into a Deposit, no receipt while a Refund is out, and none after a
termination that keeps the Deposit (V1-056 sub-slice 10e-2b-4d).

Owner answers of 2026-10-18 to the 10e-2b-4b-2b report: answer 1, option (d) of Q-2026-10-18-127
until option (a) is built (the receipt writer refuses a receipt into a Deposit whose Refund is
out); answer 2, option (b) of Q-2026-10-18-128 (once the Invoice a Payment names has nothing
outstanding, what is left of that Payment may go into the Deposit; one transfer that pays the
Initial Rent and the Deposit together is normal); answer 3, option (a) of Q-2026-10-18-131 (no
receipt into a Deposit after a termination whose ground keeps it, also after a forfeiture
reversal). Review round 1: the excess check runs after the Payment and Deposit locks, and the
Deposit service replays the receipt after a NOWAIT refusal (DL-067). Option (d) ended in sub-slice
10e-2b-4e-2b-2b, once option (a) was built; its two tests here now show the receipt recorded.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from lease_deposit_forfeiture_test_support import reverse_through_draft
from payment_test_support import seed_payment
from property_rental.deposit import (
    DepositInvalidError,
    DepositServiceUnavailableError,
    PostgresDepositService,
)
from property_rental.lease_termination import TerminationBasis
from refund_test_support import cash
from termination_test_support import approved_test_termination_context
from test_credit_migration import actor
from test_deposit_receipt_record_migration import (
    AVAILABILITY,
    EXCESS,
    FORFEITED,
    KEPT,
    allocator,
    attempt,
    payment,
    pet_case,
    qualify_review,
    receipt_command,
    review_refund,
    terminated_pet_lease_case,
    written,
)
from test_final_settlement_confirm_migration import this_month
from test_final_settlement_migration import held, one
from test_final_settlement_preview_migration import pay
from test_invoice_migration import financial_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated as allocation_designated
from test_payment_allocation_migration import service as allocation_service
from test_payment_move_migration import rows, value
from test_pet_payback_restoration_refusal_migration import owner, wait_until_blocked_by
from test_pet_refund_migration import command as pet_refund_command
from test_refund_service_migration import returned
from test_refund_service_migration import service as refund_service
from test_unpaid_initial_termination_migration import rent_line, signed_with_initial

REVISION = "20261230_156"
WRITER = "app.record_lease_deposit_receipt(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,text,text)"
# The option (d) refusal of sub-slice 10e-2b-4d, removed by sub-slice 10e-2b-4e-2b-2b.
REFUND_OUT = (
    "The Deposit has a Refund that is not fully returned; this receipt is not recorded here"
)
AVAILABLE = "SELECT app.payment_available_value(%s)"
UNRESOLVED = "SELECT app.deposit_has_unresolved_refund(%s)"
# The twelve tables `app.assert_payment_excess_eligible` locks IN SHARE MODE NOWAIT.
OBLIGATION_TABLES = [
    "invoices",
    "invoice_lines",
    "invoice_adjustments",
    "invoice_adjustment_reversals",
    "invoice_void_events",
    "late_payment_charges",
    "late_payment_charge_corrections",
    "late_payment_decisions",
    "payment_allocations",
    "payment_allocation_reversals",
    "customer_credit_applications",
    "customer_credit_application_reversals",
]


def leftover_case(url: str) -> dict[str, Any]:
    """A signed Lease whose Initial Rent Invoice is paid by a transfer that names it and carries
    5,000 more (the review round 1 set-up of the security reviewer)."""
    source = signed_with_initial(url, this_month(url))
    human, prop = source["actor"], source["property"]
    line, owed = rent_line(url, source["invoice"])
    with psycopg.connect(url) as connection:
        transfer = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=source["customer"],
            amount=owed + 5_000,
            invoice_id=source["invoice"],
        )
    posted = allocation_service().post(
        prop,
        transfer,
        allocation_designated(source["invoice"], line, owed),
        actor=allocation_actor(human, prop),
    )
    allocation = UUID(str(cast(list[Any], posted["allocation_ids"])[0]))
    assert value(url, AVAILABLE, transfer) == 5_000
    return {**source, "transfer": transfer, "allocation": allocation, "line": line}


def test_a_receipt_into_a_deposit_whose_refund_is_out_is_recorded(
    migrated_database_url: str,
) -> None:
    """The deliberate one-person path of Q-2026-10-18-127 review round 3: a Pet Deposit (required
    20,000) takes 10,000 from Payment A and pays a 10,000 Pet Refund-review Refund (it holds 0).
    Option (d) refused a receipt from Payment C while the Refund was not fully returned (sub-slice
    10e-2b-4d). Owner answer (a) replaces (d) once it is built, so since sub-slice 10e-2b-4e-2b-2b
    C's receipt is recorded while the Refund is out (the Deposit holds 10,000 and C has nothing
    left); A's later return charges back only its shortfall
    (`test_deposit_receipt_refund_out_migration.py`). The Refund's verified returns of 4,000 and
    6,000 then come back into the Deposit, which ends holding 20,000 with the Refund resolved, as
    before. Renamed in 10e-2b-4e-2b-2b from
    `test_a_receipt_into_a_deposit_whose_refund_is_out_is_refused`."""
    url = migrated_database_url
    case: dict[str, Any] = pet_case(url)
    human, prop, pet = case["human"], case["prop"], case["pet"]
    service: PostgresDepositService = case["service"]
    service.record_receipt(
        receipt_command(pet, payment(url, human, pet, 10_000), 10_000),
        actor=allocator(human, prop),
    )
    refund = review_refund(case, qualify_review(case), 10_000)
    assert held(url, pet) == 0
    later = payment(url, human, pet, 10_000)
    recorded = service.record_receipt(
        receipt_command(pet, later, 10_000), actor=allocator(human, prop)
    )
    assert (recorded.deposit.held_refundable_usd_cents, written(url, pet)) == (10_000, (2, 2, 2))
    assert value(url, UNRESOLVED, pet) is True
    assert value(url, AVAILABLE, later) == 0
    refund_service().verify_usd_return(
        prop, refund, returned(4_000), actor=actor(human, prop, "refunds.correct")
    )
    assert (held(url, pet), value(url, UNRESOLVED, pet)) == (14_000, True)
    refund_service().verify_usd_return(
        prop, refund, returned(6_000), actor=actor(human, prop, "refunds.correct")
    )
    assert (held(url, pet), written(url, pet), value(url, UNRESOLVED, pet)) == (
        20_000,
        (2, 2, 2),
        False,
    )


def test_the_rest_of_a_payment_named_for_the_initial_rent_invoice_goes_into_the_deposit(
    migrated_database_url: str,
) -> None:
    """Owner answer (b) to Q-2026-10-18-128: one transfer names the Initial Rent Invoice and pays
    it and 5,000 more for the Security Deposit balance. While the Invoice is owed the receipt is
    refused (23514, the Credit path's excess check; nothing is written); the Payment's allocation
    then pays the Invoice in full, and the 5,000 left is recorded into the Reservation's Security
    Deposit; one cent more than is left is refused by the receipt table's availability bound."""
    url = migrated_database_url
    source = signed_with_initial(url, this_month(url))
    human, prop, security = source["actor"], source["property"], source["deposit"]
    line, owed = rent_line(url, source["invoice"])
    assert owed > 0
    with psycopg.connect(url) as connection:
        transfer = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=source["customer"],
            amount=owed + 5_000,
            invoice_id=source["invoice"],
        )
    held_before = held(url, security)
    assert attempt(prop, human, security, transfer, 5_000) == ("23514", EXCESS)
    assert (held(url, security), written(url, security)) == (held_before, (1, 0, 0))
    allocation_service().post(
        prop,
        transfer,
        allocation_designated(source["invoice"], line, owed),
        actor=allocation_actor(human, prop),
    )
    assert value(url, "SELECT app.invoice_line_outstanding(%s)", line) == 0
    assert value(url, AVAILABLE, transfer) == 5_000
    assert attempt(prop, human, security, transfer, 5_001) == ("23514", AVAILABILITY)
    service = PostgresDepositService(financial_database_url(), prop, human)
    recorded = service.record_receipt(
        receipt_command(security, transfer, 5_000), actor=allocator(human, prop)
    )
    assert (
        recorded.deposit.held_refundable_usd_cents,
        recorded.payment_available_usd_cents,
        written(url, security),
    ) == (held_before + 5_000, 0, (2, 1, 1))


def test_after_a_termination_only_a_deposit_its_ground_keeps_refuses_a_receipt(
    migrated_database_url: str,
) -> None:
    """Owner answer (a) to Q-2026-10-18-131: on a Lease terminated for voluntary early leaving
    (BR-LEASE-021), whose ground keeps the Security Deposit (BR-DEP-023) but not the Pet Deposit,
    a Pet Deposit receipt is still recorded while the Final Settlement is open; a Security Deposit
    receipt is refused while its forfeiture is active and, once the forfeiture is reversed, by the
    ground (55000); the Security Deposit takes nothing and its Payment keeps its value."""
    url = migrated_database_url
    case = terminated_pet_lease_case(url, voluntary=True)
    human, prop, security, pet = case["human"], case["prop"], case["security"], case["pet"]
    deposits = PostgresDepositService(financial_database_url(), prop, human)
    recorded = deposits.record_receipt(
        receipt_command(pet, payment(url, human, pet, 5_000), 5_000), actor=allocator(human, prop)
    )
    assert (recorded.deposit.held_refundable_usd_cents, written(url, pet)) == (5_000, (1, 1, 1))
    paid_by = payment(url, human, security, 5_000)
    assert attempt(prop, human, security, paid_by, 5_000) == ("55000", FORFEITED)
    dispositions = "SELECT id FROM app.deposit_dispositions WHERE deposit_id=%s"
    [disposition] = [UUID(str(row[0])) for row in rows(url, dispositions, security)]
    reverse_through_draft(deposits, disposition)
    held_before = held(url, security)
    assert attempt(prop, human, security, paid_by, 5_000) == ("55000", KEPT)
    with pytest.raises(DepositInvalidError):
        deposits.record_receipt(
            receipt_command(security, paid_by, 5_000), actor=allocator(human, prop)
        )
    assert (held(url, security), written(url, security), value(url, AVAILABLE, paid_by)) == (
        held_before,
        (1, 0, 0),
        5_000,
    )


def test_a_leftover_receipt_waiting_for_the_payment_holds_no_obligation_table_lock(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent S1 and security S1): the excess check runs after the Payment
    and Deposit locks. While another transaction holds the Payment (its guard and row, as the
    allocation post and the Payment return confirm do before they write obligation tables), a
    leftover receipt waiting for it holds no SHARE lock on any of the twelve obligation tables, so
    that transaction still writes them at once (a lock that would wait is refused after 500 ms;
    with the check before the Payment lock it deadlocked); once it ends, the receipt is
    recorded."""
    url = migrated_database_url
    case = leftover_case(url)
    human, prop, security, transfer = (
        case["actor"],
        case["property"],
        case["deposit"],
        case["transfer"],
    )
    before = held(url, security)
    with psycopg.connect(url) as holder:
        holder.execute("SELECT app.serialize_payment_state(%s)", (transfer,))
        holder.execute("SELECT 1 FROM app.payments WHERE id=%s FOR UPDATE", (transfer,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(attempt, prop, human, security, transfer, 5_000)
            try:
                wait_until_blocked_by(url, holder)
                share_locks = value(
                    url,
                    "SELECT count(*) FROM pg_catalog.pg_locks held_lock "
                    "JOIN pg_catalog.pg_class relation ON relation.oid=held_lock.relation "
                    "JOIN pg_catalog.pg_namespace namespace ON namespace.oid=relation.relnamespace "
                    "WHERE held_lock.locktype='relation' AND held_lock.granted "
                    "AND held_lock.mode='ShareLock' AND namespace.nspname='app' "
                    "AND relation.relname::text=ANY(%s) "
                    "AND %s=ANY(pg_catalog.pg_blocking_pids(held_lock.pid))",
                    OBLIGATION_TABLES,
                    holder.info.backend_pid,
                )
                assert share_locks == 0
                holder.execute("SET LOCAL lock_timeout='500ms'")
                holder.execute(
                    "LOCK TABLE app.payment_allocations,app.payment_allocation_reversals "
                    "IN ROW EXCLUSIVE MODE"
                )
            finally:
                holder.rollback()
            assert waiting.result(timeout=30) == (None, None)
    assert (held(url, security), written(url, security)) == (before + 5_000, (2, 1, 1))


def test_a_leftover_receipt_waiting_for_the_deposit_holds_no_obligation_table_lock(
    migrated_database_url: str,
) -> None:
    """Review round 2 (security note 4; the reviewer's set-up): the excess check also comes after
    the Deposit lock. While another transaction holds the Security Deposit's guard, a leftover
    receipt that holds its Payment and waits for the Deposit holds no obligation table lock, so
    that transaction writes the allocation and Invoice line tables at once (a lock that would
    wait is refused after 500 ms); once it ends, the receipt is recorded."""
    url = migrated_database_url
    case = leftover_case(url)
    human, prop, security, transfer = (
        case["actor"],
        case["property"],
        case["deposit"],
        case["transfer"],
    )
    before = held(url, security)
    with psycopg.connect(url) as holder:
        holder.execute("SELECT app.serialize_deposit_state(%s)", (security,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(attempt, prop, human, security, transfer, 5_000)
            try:
                wait_until_blocked_by(url, holder)
                holder.execute("SET LOCAL lock_timeout='500ms'")
                holder.execute(
                    "LOCK TABLE app.payment_allocations,app.invoice_lines IN ROW EXCLUSIVE MODE"
                )
            finally:
                holder.rollback()
            assert waiting.result(timeout=30) == (None, None)
    assert (held(url, security), written(url, security)) == (before + 5_000, (2, 1, 1))


def test_a_receipt_beside_an_uncommitted_termination_waits_and_is_refused(
    migrated_database_url: str,
) -> None:
    """Review round 2 (both reviewers, note 1) showed a receipt recorded beside an uncommitted
    termination; owner answer (a) to Q-2026-10-18-133 (sub-slice 10i-1, renamed from
    `test_a_receipt_beside_an_uncommitted_termination_is_recorded_known_limit`): the termination
    also locks the Lease's Deposits, so a receipt saved while a voluntary early termination (whose
    ground keeps the Security Deposit) is still uncommitted waits for it and, after its commit,
    reads the terminated Lease and is refused (55000); no receipt of that Payment is written, and
    the next receipt is refused the same way."""
    url = migrated_database_url
    source = signed_with_initial(url, this_month(url))
    human, prop, lease, security = (
        source["actor"],
        source["property"],
        source["lease"],
        source["deposit"],
    )
    rent, owed = rent_line(url, source["invoice"])
    pay(url, prop, human, source["customer"], source["invoice"], rent, owed)
    paid_by = payment(url, human, security, 5_000)
    context = approved_test_termination_context(TerminationBasis.VOLUNTARY_EARLY, warning_ids=())
    with psycopg.connect(url) as terminating, ThreadPoolExecutor(max_workers=1) as pool:
        row = terminating.execute(
            "SELECT version,clock_timestamp() FROM app.leases WHERE id=%s", (lease,)
        ).fetchone()
        assert row is not None
        terminating.execute(
            "SELECT app.terminate_lease_with_context(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                prop,
                uuid4(),
                "b" * 64,
                uuid4(),
                lease,
                row[0],
                source["today"],
                row[1],
                "BR-LEASE-021",
                "Approved synthetic voluntary departure",
                human,
                Jsonb(context.intent()),
            ),
        )
        try:
            recorded = pool.submit(attempt, prop, human, security, paid_by, 5_000)
            wait_until_blocked_by(url, terminating)
            assert not recorded.done()
        finally:
            terminating.commit()
        assert recorded.result(timeout=10) == ("55000", KEPT)
    assert value(url, "SELECT count(*) FROM app.deposit_receipts WHERE payment_id=%s", paid_by) == 0
    assert value(
        url, "SELECT app.lease_termination_forfeiture_rule(%s,%s,'SECURITY')", prop, lease
    ) == ("BR-DEP-023")
    assert attempt(prop, human, security, payment(url, human, security, 100), 100) == (
        "55000",
        KEPT,
    )


def test_the_excess_check_refuses_at_once_while_an_obligation_table_is_written(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review round 1 (independent S2, security S2; DL-067): while another transaction writes an
    obligation table (a ROW EXCLUSIVE lock on the Invoice lines), the excess check's NOWAIT lock
    refuses a receipt from a Payment named for an Invoice at once (55P03); the service replays the
    receipt three times, each attempt refused by the database (its three pauses are counted), and
    then answers unavailable; a Payment that names nothing does not reach the check and is
    recorded. The named Payment keeps its value. Review round 2 (both reviewers): every call runs
    in a worker with a time limit, so a lost NOWAIT fails the test instead of hanging it."""
    url = migrated_database_url
    source = signed_with_initial(url, this_month(url))
    human, prop, security = source["actor"], source["property"], source["deposit"]
    with psycopg.connect(url) as connection:
        named = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=source["customer"],
            amount=10_000,
            invoice_id=source["invoice"],
        )
        unnamed = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=source["customer"],
            amount=5_000,
        )
    pauses: list[float] = []
    monkeypatch.setattr("property_rental.lock_retry._pause", pauses.append)
    service = PostgresDepositService(financial_database_url(), prop, human)
    with psycopg.connect(owner()) as writing, ThreadPoolExecutor(max_workers=1) as pool:
        writing.execute("LOCK TABLE app.invoice_lines IN ROW EXCLUSIVE MODE")
        try:
            started = time.monotonic()
            refused = pool.submit(attempt, prop, human, security, named, 5_000).result(timeout=5)
            assert refused[0] == "55P03"
            assert time.monotonic() - started < 2
            replayed = pool.submit(
                service.record_receipt,
                receipt_command(security, named, 5_000),
                actor=allocator(human, prop),
            )
            with pytest.raises(DepositServiceUnavailableError):
                replayed.result(timeout=30)
            assert pauses == [0.25, 0.5, 1.0]
            recorded = pool.submit(attempt, prop, human, security, unnamed, 5_000)
            assert recorded.result(timeout=5) == (None, None)
        finally:
            writing.rollback()
    assert (written(url, security), value(url, AVAILABLE, named)) == ((2, 1, 1), 10_000)


def test_a_receipt_refused_by_the_nowait_lock_is_recorded_once_by_its_replay(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review round 2 (security S1; DL-067 on the real path): the first attempt of a leftover
    receipt meets the NOWAIT refusal (55P03) while another transaction writes the Invoice lines;
    that transaction ends during the first pause; the replay of the same command records the
    receipt once, and a later repeat of the command is an exact replay that writes nothing."""
    url = migrated_database_url
    case = leftover_case(url)
    human, prop, security, transfer = (
        case["actor"],
        case["property"],
        case["deposit"],
        case["transfer"],
    )
    before = held(url, security)
    service = PostgresDepositService(financial_database_url(), prop, human)
    command = receipt_command(security, transfer, 5_000)
    pauses: list[float] = []
    with psycopg.connect(owner()) as writing:
        writing.execute("LOCK TABLE app.invoice_lines IN ROW EXCLUSIVE MODE")

        def release(seconds: float) -> None:
            pauses.append(seconds)
            writing.rollback()

        monkeypatch.setattr("property_rental.lock_retry._pause", release)
        recorded = service.record_receipt(command, actor=allocator(human, prop))
    assert pauses == [0.25]
    assert (
        recorded.deposit.held_refundable_usd_cents,
        recorded.payment_available_usd_cents,
        written(url, security),
    ) == (before + 5_000, 0, (2, 1, 1))
    service.record_receipt(command, actor=allocator(human, prop))
    assert (held(url, security), written(url, security)) == (before + 5_000, (2, 1, 1))


def test_an_allocation_reversal_committed_while_the_writer_waits_keeps_the_leftover_out(
    migrated_database_url: str,
) -> None:
    """Review round 1 (security S2, adapted to the lock order fix: the allocation reversal holds
    the Payment, so the receipt now waits for it instead of meeting the NOWAIT refusal): the
    excess check reads after the Payment lock. A leftover receipt that waits for an uncommitted
    one-call reversal of its Payment's allocation reads the committed reversal: the named Invoice
    is owed again, so the receipt is refused (23514, also through the service) and nothing is
    written."""
    url = migrated_database_url
    case = leftover_case(url)
    human, prop, security, transfer = (
        case["actor"],
        case["property"],
        case["deposit"],
        case["transfer"],
    )
    before = held(url, security)
    with psycopg.connect(url) as holder:
        holder.execute(
            "SELECT app.reverse_payment_allocation_command(%s,%s,%s,%s,%s,%s)",
            (prop, case["allocation"], human, uuid4(), "b" * 64, "Allocation posted in error"),
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(attempt, prop, human, security, transfer, 5_000)
            wait_until_blocked_by(url, holder)
            holder.commit()
            assert waiting.result(timeout=30) == ("23514", EXCESS)
    assert value(url, "SELECT app.invoice_line_outstanding(%s)", case["line"]) > 0
    service = PostgresDepositService(financial_database_url(), prop, human)
    with pytest.raises(DepositInvalidError):
        service.record_receipt(
            receipt_command(security, transfer, 5_000), actor=allocator(human, prop)
        )
    assert (held(url, security), written(url, security)) == (before, (1, 0, 0))


def test_a_receipt_waiting_for_a_refund_confirm_is_recorded_after_it(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent note 2): the writer reads after the Deposit lock. A Pet Deposit
    holds 10,000; the confirm of a 10,000 Pet Refund-review Refund holds it; a receipt that waits
    for that confirm reads the committed Refund. Option (d) refused it (55000) until sub-slice
    10e-2b-4e-2b-2b ended (d); now it is recorded after the confirm, and the Deposit holds 10,000
    with the Refund out. Renamed in 10e-2b-4e-2b-2b from
    `test_a_refund_committed_while_the_writer_waits_refuses_the_receipt`."""
    url = migrated_database_url
    case: dict[str, Any] = pet_case(url)
    human, prop, pet = case["human"], case["prop"], case["pet"]
    service: PostgresDepositService = case["service"]
    service.record_receipt(
        receipt_command(pet, payment(url, human, pet, 10_000), 10_000),
        actor=allocator(human, prop),
    )
    review = qualify_review(case)
    refunds = refund_service()
    preparer = actor(human, prop, "refunds.create")
    draft = refunds.record_pet_draft(
        prop,
        pet_refund_command(pet, review, 10_000),
        cash(refunds, prop, preparer),
        actor=preparer,
    )
    later = payment(url, human, pet, 10_000)
    with psycopg.connect(financial_database_url()) as confirming:
        confirming.execute(
            "SELECT app.confirm_refund_draft(%s,%s,%s,'financial.approve')",
            (prop, human, UUID(str(draft["draft_id"]))),
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(attempt, prop, human, pet, later, 10_000)
            wait_until_blocked_by(url, confirming)
            confirming.commit()
            assert waiting.result(timeout=60) == (None, None)
    assert (written(url, pet), held(url, pet), value(url, AVAILABLE, later)) == (
        (2, 2, 2),
        10_000,
        0,
    )
    # Review round 1 of sub-slice 10e-2b-4e-2b-2b (independent note 1): recorded after the
    # Refund, which is still out.
    assert value(
        url,
        "SELECT (SELECT occurred_at FROM app.deposit_receipts WHERE payment_id=%s)"
        ">(SELECT max(processed_at) FROM app.refunds WHERE source_deposit_id=%s)",
        later,
        pet,
    )
    assert value(url, UNRESOLVED, pet) is True


def test_the_receipt_leftover_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Sub-slice 10e-2b-4d patches only the receipt writer, by exactly its listed replacements,
    with the same owner, privileges and settings; no other function, constraint or trigger
    changes, and it is forward-only."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261229_155"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    assert one(
        migrated_database_url,
        "SELECT has_function_privilege('prm_runtime',p.oid,'EXECUTE'),"
        "has_function_privilege('prm_financial',p.oid,'EXECUTE') "
        "FROM pg_catalog.pg_proc p WHERE p.oid=CAST(%s AS regprocedure)",
        WRITER,
    ) == (False, True)

    def catalog(database: str) -> tuple[dict[str, tuple[Any, ...]], set[str]]:
        functions = {
            str(row[0]): tuple(row[1:])
            for row in rows(
                database,
                "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                "p.proacl::text,p.proowner,p.prosecdef,p.proconfig::text "
                "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'",
            )
        }
        others = {
            ":".join(str(item) for item in row)
            for row in rows(
                database,
                "SELECT 'constraint',c.conrelid::regclass::text,c.conname,"
                "pg_catalog.pg_get_constraintdef(c.oid) "
                "FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_namespace n "
                "ON n.oid=c.connamespace WHERE n.nspname='app' AND c.contype<>'t' "
                "UNION ALL SELECT 'trigger',t.tgrelid::regclass::text,t.tgname,t.tgenabled::text "
                "FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='app' AND NOT t.tgisinternal",
            )
        }
        return functions, others

    with _temporary_migration_database("deposit_receipt_leftover") as temporary:
        alembic_command.upgrade(config, "20261229_155")
        before_functions, before_others = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_others = catalog(temporary)
    assert after_others == before_others
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {WRITER}
    expected = before_functions[WRITER][0]
    for before, after in revision.module.WRITER_REPLACEMENTS:
        assert expected.count(before) == 1
        expected = expected.replace(before, after)
    assert after_functions[WRITER][0] == expected
    assert after_functions[WRITER][1:] == before_functions[WRITER][1:]
