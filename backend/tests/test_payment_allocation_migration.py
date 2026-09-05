"""V1-049 exact allocation and reversal integration against isolated PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from payment_test_support import seed_payment
from property_rental.billing import PostgresRentBillingService
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.invoice import (
    AdjustInvoiceCommand,
    AdjustmentType,
    InvoiceInvalidError,
    PostgresInvoiceService,
)
from property_rental.late_payment import (
    CorrectionKind,
    CorrectLatePaymentChargeCommand,
    DecisionOutcome,
    FinalizeLatePaymentDecisionCommand,
    LatePaymentApplicationReversalRequired,
)
from property_rental.payment_allocation import (
    AllocationConflictError,
    AllocationIdempotencyKeyReused,
    AllocationUnavailableError,
    PaymentAllocationService,
    PostAllocationsCommand,
    ReverseAllocationCommand,
    ReversePaymentCommand,
)
from test_billing_service_migration import authenticated, initial_command, setup_billing_source
from test_invoice_migration import (
    create_recurring_rent_invoice,
    financial_database_url,
    invoice_api_actor,
    runtime_database_url,
    setup_signed_lease,
)
from test_late_payment_migration import late_payment_actor, setup_invoice
from test_late_payment_migration import service as late_service
from test_reservation_migration import (
    create_reservation,
    migrated_database_url,  # noqa: F401
    setup_reservation_sources,
)


def service() -> PaymentAllocationService:
    return PaymentAllocationService(runtime_database_url(), financial_database_url())


def actor(identity: UUID, prop: UUID) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(identity),
        frozenset(
            CapabilityGrant(capability, frozenset({str(prop)}))
            for capability in ("payments.allocate", "payments.reverse")
        ),
    )


def source(url: str, amount: int = 100_000) -> tuple[UUID, UUID, UUID, list[UUID]]:
    with psycopg.connect(url) as connection:
        human, prop, customer, lease = setup_signed_lease(connection)
        invoices = []
        # Deliberately insert the later Due Date first.
        for month in (3, 2):
            invoice, _ = create_recurring_rent_invoice(
                connection,
                actor_id=human,
                customer_id=customer,
                lease_id=lease,
                period_start=date(2027, month, 1),
            )
            invoices.append(invoice)
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=amount
        )
    return human, prop, payment, invoices


def test_allocation_proposal_explicit_post_replay_reverse_and_positions(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, invoices = source(migrated_database_url)
    staff = actor(human, prop)
    proposal = service().proposal(prop, payment, actor=staff)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.payment_allocations WHERE payment_id=%s", (payment,)
        ).fetchone() == (0,)
    targets = proposal["targets"]
    assert isinstance(targets, list)
    assert [item["invoice_id"] for item in targets] == [str(invoices[1]), str(invoices[0])]
    assert [item["amount_usd_cents"] for item in targets] == [80_000, 20_000]
    command = PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal})
    result = service().post(prop, payment, command, actor=staff)
    assert result["available_usd_cents"] == 0
    assert service().post(prop, payment, command, actor=staff) == result
    with psycopg.connect(migrated_database_url) as connection:
        rows = connection.execute(
            "SELECT id,status FROM app.invoices WHERE id=ANY(%s)", (invoices,)
        ).fetchall()
        assert dict(rows) == {invoices[1]: "PAID", invoices[0]: "PARTIALLY_PAID"}
        assert connection.execute(
            "SELECT allocated_usd_cents,available_usd_cents,allocation_condition "
            "FROM app.payment_financial_position WHERE payment_id=%s",
            (payment,),
        ).fetchone() == (100_000, 0, "FULLY_ALLOCATED")
        snapshot = connection.execute(
            "SELECT app.invoice_resource_snapshot(%s)", (invoices[0],)
        ).fetchone()
        assert snapshot is not None
        assert snapshot[0]["outstanding_balance"]["minor_units"] == 60_000
        assert snapshot[0]["active_application_total"]["minor_units"] == 20_000
    with pytest.raises(AllocationUnavailableError):
        service().reverse_payment(
            prop, payment, ReversePaymentCommand(uuid4(), "Receipt duplicated"), actor=staff
        )
    allocations = result["allocation_ids"]
    assert isinstance(allocations, list)
    for allocation in allocations:
        reversal = ReverseAllocationCommand(uuid4(), "Undo incorrect assignment")
        first = service().reverse_allocation(prop, UUID(str(allocation)), reversal, actor=staff)
        assert (
            service().reverse_allocation(prop, UUID(str(allocation)), reversal, actor=staff)
            == first
        )
    final_command = ReversePaymentCommand(uuid4(), "Receipt duplicated")
    reversed_payment = service().reverse_payment(prop, payment, final_command, actor=staff)
    assert service().reverse_payment(prop, payment, final_command, actor=staff) == reversed_payment
    assert reversed_payment["status"] == "REVERSED"
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.invoices WHERE id=ANY(%s) AND status='UNPAID'", (invoices,)
        ).fetchone() == (2,)
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE entity_type='payment_allocation' "
            "AND entity_id=ANY(%s)",
            ([UUID(str(value)) for value in allocations],),
        ).fetchone() == (4,)


def test_allocation_rejects_stale_proposal_and_reused_intent(migrated_database_url: str) -> None:  # noqa: F811
    human, prop, payment, _ = source(migrated_database_url)
    staff = actor(human, prop)
    proposal = service().proposal(prop, payment, actor=staff)
    targets = proposal["targets"]
    assert isinstance(targets, list)
    first = targets[0]
    intent: dict[str, object] = {
        "mode": "DESIGNATED",
        "designation_reference": "Customer instruction 1",
        "targets": [
            {
                "invoice_id": first["invoice_id"],
                "amount_usd_cents": 1,
                "details": [
                    {
                        "invoice_line_id": first["details"][0]["invoice_line_id"],
                        "amount_usd_cents": 1,
                    }
                ],
            }
        ],
    }
    command = PostAllocationsCommand(uuid4(), intent)
    service().post(prop, payment, command, actor=staff)
    with pytest.raises(AllocationConflictError):
        service().post(
            prop,
            payment,
            PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
            actor=staff,
        )
    with pytest.raises(AllocationIdempotencyKeyReused):
        service().post(
            prop,
            payment,
            PostAllocationsCommand(
                command.idempotency_key,
                {**intent, "designation_reference": "Different instruction"},
            ),
            actor=staff,
        )


def designated(invoice: UUID, line: UUID, amount: int) -> PostAllocationsCommand:
    return PostAllocationsCommand(
        uuid4(),
        {
            "mode": "DESIGNATED",
            "designation_reference": "Explicit customer instruction",
            "targets": [
                {
                    "invoice_id": str(invoice),
                    "amount_usd_cents": amount,
                    "details": [{"invoice_line_id": str(line), "amount_usd_cents": amount}],
                }
            ],
        },
    )


def test_allocation_competing_payments_cannot_overpay_one_line(migrated_database_url: str) -> None:  # noqa: F811
    human, prop, payment, invoices = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT customer_id FROM app.invoices WHERE id=%s", (invoices[0],)
        ).fetchone()
        assert row is not None
        second = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=UUID(str(row[0])),
            amount=100_000,
        )
        line = connection.execute(
            "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", (invoices[0],)
        ).fetchone()
        assert line is not None
        line_id = UUID(str(line[0]))
    start = Barrier(2)

    def post(identity: UUID) -> str:
        start.wait(timeout=10)
        try:
            service().post(
                prop, identity, designated(invoices[0], line_id, 80_000), actor=actor(human, prop)
            )
        except AllocationUnavailableError:
            return "rejected"
        return "posted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(post, [payment, second])) == ["posted", "rejected"]
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT app.invoice_line_outstanding(%s)", (line_id,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT sum(amount_usd_cents) FROM app.payment_allocations WHERE invoice_id=%s",
            (invoices[0],),
        ).fetchone() == (80_000,)


def test_allocation_adjustments_cannot_credit_already_applied_value(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, invoices = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", (invoices[0],)
        ).fetchone()
        assert row is not None
        line_id = UUID(str(row[0]))
    service().post(
        prop, payment, designated(invoices[0], line_id, 20_000), actor=actor(human, prop)
    )
    invoices_service = PostgresInvoiceService(runtime_database_url(), financial_database_url())
    with psycopg.connect(migrated_database_url) as connection:
        version = connection.execute(
            "SELECT version FROM app.invoices WHERE id=%s", (invoices[0],)
        ).fetchone()
        assert version is not None
    with pytest.raises(InvoiceInvalidError):
        invoices_service.adjust(
            prop,
            invoices[0],
            AdjustInvoiceCommand(
                uuid4(),
                line_id,
                AdjustmentType.CREDIT,
                60_001,
                "approved-adjustment/over",
                "Cannot credit applied value",
                int(str(version[0])),
            ),
            actor=invoice_api_actor(human, prop),
        )
    result = invoices_service.adjust(
        prop,
        invoices[0],
        AdjustInvoiceCommand(
            uuid4(),
            line_id,
            AdjustmentType.CREDIT,
            60_000,
            "approved-adjustment/exact",
            "Reduce remaining obligation",
            int(str(version[0])),
        ),
        actor=invoice_api_actor(human, prop),
    )
    assert result["status"] == "PAID"
    assert result["outstanding_balance"] == {"currency": "USD", "minor_units": 0}
    assert result["adjusted_total"] == {"currency": "USD", "minor_units": 20_000}


def test_allocation_charge_is_separate_and_corrections_respect_consumption(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, invoice, _ = setup_invoice(connection, period_start=date(2026, 5, 1))
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=10_000
        )
    late_service().finalize_decision(
        prop,
        invoice,
        FinalizeLatePaymentDecisionCommand(
            uuid4(), DecisionOutcome.CONFIRMED_DEFAULT, 8_000, "Confirm default late charge"
        ),
        actor=late_payment_actor(human, prop),
    )
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT id FROM app.late_payment_charges WHERE source_invoice_id=%s", (invoice,)
        ).fetchone()
        assert row is not None
        charge = UUID(str(row[0]))
    result = service().post(
        prop,
        payment,
        PostAllocationsCommand(
            uuid4(),
            {
                "mode": "DESIGNATED",
                "designation_reference": "Customer selects separate late charge",
                "targets": [{"late_payment_charge_id": str(charge), "amount_usd_cents": 4_000}],
            },
        ),
        actor=actor(human, prop),
    )
    assert result["available_usd_cents"] == 6_000
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT status,app.invoice_line_outstanding(line.id) FROM app.invoices invoice "
            "JOIN app.invoice_lines line ON line.invoice_id=invoice.id WHERE invoice.id=%s",
            (invoice,),
        ).fetchone() == ("UNPAID", 80_000)
        assert connection.execute(
            "SELECT remaining_balance_usd_cents FROM app.late_payment_charge_financial_position "
            "WHERE late_payment_charge_id=%s",
            (charge,),
        ).fetchone() == (4_000,)
    with pytest.raises(LatePaymentApplicationReversalRequired):
        late_service().correct_charge(
            prop,
            charge,
            CorrectLatePaymentChargeCommand(
                uuid4(), CorrectionKind.REDUCTION, "Would reduce below allocation", 4_001
            ),
            actor=late_payment_actor(human, prop),
        )


def test_allocation_third_party_is_bound_to_identified_invoice(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, invoices = source(migrated_database_url)
    _, _, other_payment, _ = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        payer = connection.execute(
            "SELECT payer_customer_id FROM app.payments WHERE id=%s", (other_payment,)
        ).fetchone()
        assert payer is not None
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=UUID(str(payer[0])),
            amount=100_000,
            scope="THIRD_PARTY_IDENTIFIED",
            invoice_id=invoices[0],
        )
        line = connection.execute(
            "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", (invoices[1],)
        ).fetchone()
        assert line is not None
    staff = actor(human, prop)
    proposal = service().proposal(prop, payment, actor=staff)
    targets = proposal["targets"]
    assert isinstance(targets, list)
    assert [target["invoice_id"] for target in targets] == [str(invoices[0])]
    with pytest.raises(AllocationUnavailableError):
        service().post(prop, payment, designated(invoices[1], UUID(str(line[0])), 1), actor=staff)
    result = service().post(
        prop,
        payment,
        PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
        actor=staff,
    )
    assert result["available_usd_cents"] == 20_000
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT between_invoice_basis,customer_designation_reference "
            "FROM app.payment_allocations WHERE payment_id=%s",
            (payment,),
        ).fetchone() == ("THIRD_PARTY_DESIGNATED", f"confirmed-payment:{payment}")


def test_allocation_repeatable_read_stale_target_is_rejected(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, invoices = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT customer_id FROM app.invoices WHERE id=%s", (invoices[0],)
        ).fetchone()
        assert row is not None
        second = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=UUID(str(row[0])),
            amount=100_000,
        )
        row = connection.execute(
            "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", (invoices[0],)
        ).fetchone()
        assert row is not None
        line = UUID(str(row[0]))
    with psycopg.connect(financial_database_url()) as stale:
        stale.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        stale.execute("SET LOCAL lock_timeout='3000ms'")
        assert stale.execute("SELECT app.invoice_line_outstanding(%s)", (line,)).fetchone() == (
            80_000,
        )
        service().post(
            prop, payment, designated(invoices[0], line, 10_000), actor=actor(human, prop)
        )
        with pytest.raises(psycopg.errors.SerializationFailure):
            stale.execute(
                "SELECT app.post_payment_allocations(%s,%s,%s,%s,%s,%s)",
                (
                    prop,
                    second,
                    human,
                    uuid4(),
                    "a" * 64,
                    Jsonb(designated(invoices[0], line, 80_000).intent),
                ),
            )
        stale.rollback()


def test_allocation_history_as_of_and_private_write_boundary(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, invoices = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", (invoices[0],)
        ).fetchone()
        assert row is not None
        line = UUID(str(row[0]))
    result = service().post(
        prop, payment, designated(invoices[0], line, 10_000), actor=actor(human, prop)
    )
    ids = result["allocation_ids"]
    assert isinstance(ids, list)
    allocation = UUID(str(ids[0]))
    service().reverse_allocation(
        prop,
        allocation,
        ReverseAllocationCommand(uuid4(), "Correct allocation"),
        actor=actor(human, prop),
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT app.invoice_line_outstanding_at(%s,allocation.posted_at), "
            "app.invoice_line_outstanding_at(%s,reversal.occurred_at) "
            "FROM app.payment_allocations allocation "
            "JOIN app.payment_allocation_reversals reversal "
            "ON reversal.payment_allocation_id=allocation.id WHERE allocation.id=%s",
            (line, line, allocation),
        ).fetchone() == (70_000, 80_000)
        with pytest.raises(psycopg.Error) as failure:
            connection.execute("DELETE FROM app.payment_allocations WHERE id=%s", (allocation,))
        assert failure.value.sqlstate == "55000"
        connection.rollback()
    for login in (financial_database_url(), runtime_database_url()):
        with psycopg.connect(login) as connection:
            assert connection.execute(
                "SELECT has_table_privilege(current_user,'app.payment_allocations','INSERT'), "
                "has_function_privilege(current_user,'app.lock_payment_allocation_target(text,uuid)','EXECUTE')"
            ).fetchone() == (False, False)


@pytest.mark.parametrize("mutation", ["amount", "due_date", "line", "sequence", "trace"])
def test_allocation_generated_proposal_tampering_is_rejected(
    migrated_database_url: str,  # noqa: F811
    mutation: str,
) -> None:
    human, prop, payment, _ = source(migrated_database_url)
    staff = actor(human, prop)
    proposal = service().proposal(prop, payment, actor=staff)
    targets = proposal["targets"]
    assert isinstance(targets, list)
    if mutation == "amount":
        targets[0]["amount_usd_cents"] -= 1
    elif mutation == "due_date":
        targets[0]["due_date"] = "2020-01-01"
    elif mutation == "line":
        targets[0]["details"][0]["invoice_line_id"] = str(uuid4())
    elif mutation == "sequence":
        targets[0]["sequence"] = 2
    else:
        proposal["policy"] = "MANUAL_OVERRIDE"
    with pytest.raises(AllocationConflictError):
        service().post(
            prop,
            payment,
            PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
            actor=staff,
        )
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.payment_allocations WHERE payment_id=%s", (payment,)
        ).fetchone() == (0,)


def test_allocation_mixed_invoice_preserves_rent_first_and_line_designation(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, lease, occupancy = setup_billing_source(connection)
    issued = PostgresRentBillingService(financial_database_url(), prop, human).generate(
        initial_command(lease, occupancy), actor=authenticated(human, prop)
    )
    with psycopg.connect(migrated_database_url) as connection:
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=customer,
            amount=issued.rent_usd_cents + 50,
        )
        extra = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=10
        )
        lines = connection.execute(
            "SELECT id,category FROM app.invoice_lines WHERE invoice_id=%s ORDER BY line_sequence",
            (issued.invoice_id,),
        ).fetchall()
    # Explicit Service designation is allowed while Rent still remains unpaid.
    service().post(
        prop,
        extra,
        designated(issued.invoice_id, UUID(str(lines[-1][0])), 10),
        actor=actor(human, prop),
    )
    proposal = service().proposal(prop, payment, actor=actor(human, prop))
    targets = proposal["targets"]
    assert isinstance(targets, list)
    details = targets[0]["details"]
    assert [detail["category"] for detail in details] == ["RENT", "SERVICE_CHARGES"]
    assert [detail["amount_usd_cents"] for detail in details] == [issued.rent_usd_cents, 50]
    service().post(
        prop,
        payment,
        PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
        actor=actor(human, prop),
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT app.invoice_line_outstanding(%s)", (lines[0][0],)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT status FROM app.invoices WHERE id=%s", (issued.invoice_id,)
        ).fetchone() == ("PARTIALLY_PAID",)


@pytest.mark.parametrize("amount,expected", [(1, 0), (80_001, 0), (200_000, 40_000)])
def test_allocation_exact_amount_boundaries_leave_excess_unallocated(
    migrated_database_url: str,  # noqa: F811
    amount: int,
    expected: int,
) -> None:
    human, prop, payment, _ = source(migrated_database_url, amount)
    staff = actor(human, prop)
    proposal = service().proposal(prop, payment, actor=staff)
    result = service().post(
        prop,
        payment,
        PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
        actor=staff,
    )
    assert result["available_usd_cents"] == expected
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT usd_accounting_value_cents FROM app.payments WHERE id=%s", (payment,)
        ).fetchone() == (amount,)
        assert connection.execute(
            "SELECT app.payment_disposition_summary(%s)", (payment,)
        ).fetchone() == (
            {
                "deposit_usd_cents": 0,
                "allocation_usd_cents": amount - expected,
                "credit_usd_cents": 0,
                "refund_usd_cents": 0,
            },
        )


@pytest.mark.parametrize("isolation", ["read committed", "repeatable read", "serializable"])
@pytest.mark.parametrize("winner_kind", ["allocation", "deposit"])
def test_allocation_and_deposit_share_one_payment_budget(
    migrated_database_url: str,  # noqa: F811
    isolation: str,
    winner_kind: str,
) -> None:
    human, prop, payment, invoices = source(migrated_database_url, 1000)
    with psycopg.connect(migrated_database_url) as connection:
        _, _, unit, _ = setup_reservation_sources(connection)
        row = connection.execute(
            "SELECT customer_id FROM app.invoices WHERE id=%s", (invoices[0],)
        ).fetchone()
        assert row is not None
        _, reservation = create_reservation(
            connection,
            actor_id=human,
            property_id=prop,
            unit_id=unit,
            customer_id=UUID(str(row[0])),
        )
        line = connection.execute(
            "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", (invoices[0],)
        ).fetchone()
        assert line is not None
        command = designated(invoices[0], UUID(str(line[0])), 1000)
    with psycopg.connect(migrated_database_url) as stale:
        stale.execute("SET TRANSACTION ISOLATION LEVEL " + isolation)
        stale.execute("SET LOCAL statement_timeout='5000ms'")
        stale.execute("SELECT app.payment_disposition_summary(%s)", (payment,))
        if winner_kind == "allocation":
            service().post(prop, payment, command, actor=actor(human, prop))
        else:
            with psycopg.connect(migrated_database_url) as winner:
                winner.execute(
                    "INSERT INTO app.deposit_receipts(id,deposit_id,payment_id,amount_usd_cents,"
                    "occurred_at,actor_id) VALUES(%s,%s,%s,1000,clock_timestamp(),%s)",
                    (uuid4(), reservation["deposit_id"], payment, human),
                )
        with pytest.raises(psycopg.Error) as failure:
            if winner_kind == "allocation":
                stale.execute(
                    "INSERT INTO app.deposit_receipts(id,deposit_id,payment_id,amount_usd_cents,"
                    "occurred_at,actor_id) VALUES(%s,%s,%s,1000,clock_timestamp(),%s)",
                    (uuid4(), reservation["deposit_id"], payment, human),
                )
            else:
                stale.execute(
                    "SELECT app.post_payment_allocations(%s,%s,%s,%s,%s,%s)",
                    (
                        prop,
                        payment,
                        human,
                        command.idempotency_key,
                        "b" * 64,
                        Jsonb(command.intent),
                    ),
                )
        assert failure.value.sqlstate == ("23514" if isolation == "read committed" else "40001")
        stale.rollback()
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT available_usd_cents,allocation_condition "
            "FROM app.payment_financial_position WHERE payment_id=%s",
            (payment,),
        ).fetchone() == (0, "FULLY_ALLOCATED" if winner_kind == "allocation" else "UNALLOCATED")
