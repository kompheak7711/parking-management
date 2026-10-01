"""V1-051 Credit application and reversal integration on synthetic PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from payment_test_support import seed_payment
from property_rental.billing import PostgresRentBillingService
from property_rental.credit import (
    ApplyCreditCommand,
    CreditAuthorizationError,
    CreditConflictError,
    CreditIdempotencyKeyReused,
    CreditNotFoundError,
    CreditUnavailableError,
    ReverseCreditApplicationCommand,
    ReverseCreditCommand,
)
from property_rental.invoice import (
    AdjustInvoiceCommand,
    AdjustmentType,
    CreateInvoiceDraftCommand,
    InvoiceInvalidError,
    IssueInvoiceCommand,
    PostgresInvoiceService,
    VoidInvoiceCommand,
)
from property_rental.late_payment import (
    CorrectionKind,
    CorrectLatePaymentChargeCommand,
    DecisionOutcome,
    FinalizeLatePaymentDecisionCommand,
    LatePaymentApplicationReversalRequired,
)
from test_billing_service_migration import authenticated, initial_command, setup_billing_source
from test_credit_migration import actor, credit_id, recognize, service
from test_invoice_migration import (
    create_recurring_rent_invoice,
    financial_database_url,
    invoice_api_actor,
    runtime_database_url,
    set_draft_correction_context,
    setup_invoice_api_source,
    setup_signed_lease,
)
from test_late_payment_migration import late_payment_actor
from test_late_payment_migration import service as late_service
from test_lease_migration import create_draft, sign_lease
from test_reservation_migration import (
    migrated_database_url,  # noqa: F401
    setup_reservation_sources,
)


def source(
    url: str,
    amount: int = 100000,
    *,
    period_start: date = date(2027, 3, 1),
) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID]:
    with psycopg.connect(url) as connection:
        human, prop, customer, lease = setup_signed_lease(
            connection,
            start_date=date(period_start.year, 1, 1),
            end_date=date(period_start.year, 12, 31),
        )
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=amount
        )
    credit = credit_id(recognize(prop, payment, human, amount))
    with psycopg.connect(url) as connection:
        invoice, line = create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=customer,
            lease_id=lease,
            period_start=period_start,
        )
    return human, prop, credit, invoice, line, payment


def designated(invoice: UUID, line: UUID, amount: int) -> ApplyCreditCommand:
    return ApplyCreditCommand(
        uuid4(),
        {
            "mode": "DESIGNATED",
            "invoice_id": str(invoice),
            "amount_usd_cents": amount,
            "designation_reference": "Customer instruction",
            "details": [{"invoice_line_id": str(line), "amount_usd_cents": amount}],
        },
    )


def application_id(result: dict[str, object]) -> UUID:
    application = result["application"]
    assert isinstance(application, dict)
    return UUID(str(application["id"]))


def test_credit_application_proposal_post_replay_reverse_and_distinct_source_positions(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, credit, invoice, line, payment = source(migrated_database_url)
    staff = actor(human, prop, "credits.apply")
    proposal = service().application_proposal(prop, credit, invoice, 30000, actor=staff)
    assert proposal["amount_usd_cents"] == 30000
    request = ApplyCreditCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal})
    result = service().apply(prop, credit, request, actor=staff)
    identity = application_id(result)
    assert service().apply(prop, credit, request, actor=staff) == result
    assert (
        service().get_application(prop, identity, actor=actor(human, prop, "credits.read"))
        == result
    )
    assert result["target_balance_usd_cents"] == 50000
    assert result["target_invoice_status"] == "PARTIALLY_PAID"
    position = result["credit_position"]
    assert isinstance(position, dict) and position["available_usd_cents"] == 70000
    details = result["details"]
    assert isinstance(details, list) and len(details) == 1
    assert details[0]["invoice_line_id"] == str(line)
    assert (
        details[0]["proposed_amount_usd_cents"] == details[0]["applied_amount_usd_cents"] == 30000
    )
    assert details[0]["attribution_basis"] == "RENT_FIRST_PROPOSAL"
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT app.invoice_line_payment_value_at(%s,'infinity'),"
            "app.invoice_line_credit_value_at(%s,'infinity'),"
            "app.invoice_line_application_value_at(%s,'infinity'),"
            "app.payment_available_value(%s)",
            (line, line, line, payment),
        ).fetchone() == (0, 30000, 30000, 0)
        assert connection.execute(
            "SELECT count(*) FROM app.payment_allocations WHERE payment_id=%s",
            (payment,),
        ).fetchone() == (0,)
        row = connection.execute("SELECT app.invoice_resource_snapshot(%s)", (invoice,)).fetchone()
        assert row is not None and row[0]["active_application_total"]["minor_units"] == 30000
    with pytest.raises(CreditUnavailableError):
        service().reverse(
            prop,
            credit,
            ReverseCreditCommand(uuid4(), "Wrong recognition"),
            actor=actor(human, prop, "credits.reverse"),
        )
    reversal = ReverseCreditApplicationCommand(uuid4(), "Incorrect application")
    after = service().reverse_application(
        prop,
        identity,
        reversal,
        actor=actor(human, prop, "credits.applications.reverse"),
    )
    assert (
        service().reverse_application(
            prop,
            identity,
            reversal,
            actor=actor(human, prop, "credits.applications.reverse"),
        )
        == after
    )
    assert after["application"] == result["application"]
    assert after["target_balance_usd_cents"] == 80000 and after["target_invoice_status"] == "UNPAID"
    after_position = after["credit_position"]
    assert isinstance(after_position, dict) and after_position["available_usd_cents"] == 100000
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT action,authorization_reference FROM app.audit_events "
            "WHERE entity_id=%s ORDER BY occurred_at",
            (identity,),
        ).fetchall() == [
            ("credit.applied", "credits.apply"),
            ("credit.application.reversed", "credits.applications.reverse"),
        ]
        assert connection.execute(
            "SELECT count(*) FROM app.credit_commands WHERE action='APPLY' AND idempotency_key=%s",
            (request.idempotency_key,),
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT app.credit_applied_value_at("
            "application.customer_credit_id,application.occurred_at),"
            "app.credit_applied_value_at(application.customer_credit_id,reversal.occurred_at),"
            "app.invoice_line_credit_value_at(%s,application.occurred_at),"
            "app.invoice_line_credit_value_at(%s,reversal.occurred_at) "
            "FROM app.customer_credit_applications application "
            "JOIN app.customer_credit_application_reversals reversal "
            "ON reversal.credit_application_id=application.id WHERE application.id=%s",
            (line, line, identity),
        ).fetchone() == (30000, 0, 30000, 0)
    with pytest.raises(CreditUnavailableError):
        service().reverse_application(
            prop,
            identity,
            ReverseCreditApplicationCommand(uuid4(), "Duplicate"),
            actor=actor(human, prop, "credits.applications.reverse"),
        )
    service().reverse(
        prop,
        credit,
        ReverseCreditCommand(uuid4(), "Wrong recognition"),
        actor=actor(human, prop, "credits.reverse"),
    )


def test_credit_application_rejects_stale_proposal_changed_key_and_wrong_customer(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, credit, invoice, line, _ = source(migrated_database_url)
    staff = actor(human, prop, "credits.apply")
    proposal = service().application_proposal(prop, credit, invoice, 30000, actor=staff)
    request = designated(invoice, line, 1)
    service().apply(prop, credit, request, actor=staff)
    with pytest.raises(CreditConflictError):
        service().apply(
            prop,
            credit,
            ApplyCreditCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
            actor=staff,
        )
    with pytest.raises(CreditIdempotencyKeyReused):
        service().apply(
            prop,
            credit,
            ApplyCreditCommand(
                request.idempotency_key, {**request.intent, "designation_reference": "Changed"}
            ),
            actor=staff,
        )
    with psycopg.connect(migrated_database_url) as connection:
        other_human, _, other_customer, other_lease = setup_signed_lease(connection)
        other_invoice, other_line = create_recurring_rent_invoice(
            connection,
            actor_id=other_human,
            customer_id=other_customer,
            lease_id=other_lease,
            period_start=date(2027, 3, 1),
        )
    with pytest.raises(CreditNotFoundError):
        service().application_proposal(prop, credit, other_invoice, 1, actor=staff)
    with pytest.raises(CreditUnavailableError):
        service().apply(prop, credit, designated(other_invoice, other_line, 1), actor=staff)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.customer_credit_applications WHERE customer_credit_id=%s",
            (credit,),
        ).fetchone() == (1,)


@pytest.mark.parametrize("amount", [10001, 80001])
def test_credit_application_source_and_target_bounds_are_atomic(
    migrated_database_url: str,  # noqa: F811
    amount: int,
) -> None:
    human, prop, credit, invoice, line, _ = source(
        migrated_database_url,
        10000 if amount == 10001 else 100000,
    )
    with pytest.raises(CreditUnavailableError):
        service().apply(
            prop,
            credit,
            designated(invoice, line, amount),
            actor=actor(human, prop, "credits.apply"),
        )
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.customer_credit_applications WHERE customer_credit_id=%s",
            (credit,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE action='credit.applied' "
            "AND resulting_state->>'customer_credit_id'=%s",
            (str(credit),),
        ).fetchone() == (0,)


def test_credit_application_competing_credit_and_payment_cannot_overpay_target(
    migrated_database_url: str,  # noqa: F811
) -> None:
    from property_rental.payment_allocation import AllocationUnavailableError
    from test_payment_allocation_migration import actor as allocation_actor
    from test_payment_allocation_migration import designated as allocation_designated
    from test_payment_allocation_migration import service as allocation_service

    human, prop, credit, invoice, line, payment = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT payer_customer_id FROM app.payments WHERE id=%s", (payment,)
        ).fetchone()
        assert row is not None
        second_payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=UUID(str(row[0])),
            amount=100000,
        )
    barrier = Barrier(2)

    def post(kind: str) -> str:
        barrier.wait(timeout=10)
        try:
            if kind == "credit":
                service().apply(
                    prop,
                    credit,
                    designated(invoice, line, 60000),
                    actor=actor(human, prop, "credits.apply"),
                )
            else:
                allocation_service().post(
                    prop,
                    second_payment,
                    allocation_designated(invoice, line, 60000),
                    actor=allocation_actor(human, prop),
                )
            return "posted"
        except (CreditUnavailableError, AllocationUnavailableError):
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(post, ("credit", "payment"))) == ["posted", "rejected"]
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT app.invoice_line_application_value_at(%s,'infinity'),"
            "app.invoice_line_outstanding(%s)",
            (line, line),
        ).fetchone() == (60000, 20000)


def test_credit_application_capabilities_and_fresh_actor_are_independent(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, credit, invoice, line, _ = source(migrated_database_url)
    posting = actor(human, prop, "credits.apply")
    result = service().apply(prop, credit, designated(invoice, line, 1), actor=posting)
    identity = application_id(result)
    with pytest.raises(CreditAuthorizationError):
        service().reverse_application(
            prop,
            identity,
            ReverseCreditApplicationCommand(uuid4(), "Wrong application"),
            actor=posting,
        )
    with pytest.raises(CreditAuthorizationError):
        service().apply(
            prop,
            credit,
            designated(invoice, line, 1),
            actor=actor(human, prop, "credits.applications.reverse"),
        )
    with pytest.raises(CreditAuthorizationError):
        service().get_application(prop, identity, actor=posting)
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    with pytest.raises(CreditAuthorizationError):
        service().get_application(prop, identity, actor=actor(human, prop, "credits.read"))


def test_credit_application_mixed_invoice_default_and_customer_designation(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, lease, occupancy = setup_billing_source(connection)
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=200000
        )
    credit = credit_id(recognize(prop, payment, human, 200000))
    issued = PostgresRentBillingService(financial_database_url(), prop, human).generate(
        initial_command(lease, occupancy),
        actor=authenticated(human, prop),
    )
    with psycopg.connect(migrated_database_url) as connection:
        lines = connection.execute(
            "SELECT id,category FROM app.invoice_lines WHERE invoice_id=%s ORDER BY line_sequence",
            (issued.invoice_id,),
        ).fetchall()
    staff = actor(human, prop, "credits.apply")
    # An actual Customer designation may select Service before unpaid Rent.
    designated_result = service().apply(
        prop,
        credit,
        designated(issued.invoice_id, UUID(str(lines[-1][0])), 10),
        actor=staff,
    )
    designated_details = designated_result["details"]
    assert isinstance(designated_details, list)
    assert designated_details[0]["proposed_amount_usd_cents"] is None
    assert designated_details[0]["attribution_basis"] == "CUSTOMER_DESIGNATED"
    proposal = service().application_proposal(
        prop, credit, issued.invoice_id, issued.rent_usd_cents + 50, actor=staff
    )
    details = proposal["details"]
    assert isinstance(details, list)
    assert [detail["category"] for detail in details] == ["RENT", "SERVICE_CHARGES"]
    assert [detail["amount_usd_cents"] for detail in details] == [issued.rent_usd_cents, 50]
    result = service().apply(
        prop,
        credit,
        ApplyCreditCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
        actor=staff,
    )
    assert result["target_invoice_status"] == "PARTIALLY_PAID"
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT app.invoice_line_outstanding(%s)", (lines[0][0],)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT app.invoice_line_payment_value_at(%s,'infinity'),"
            "app.invoice_line_credit_value_at(%s,'infinity')",
            (lines[0][0], lines[0][0]),
        ).fetchone() == (0, issued.rent_usd_cents)


@pytest.mark.parametrize("designated_charge", [False, True])
def test_credit_application_charge_is_separate_and_correction_respects_consumption(
    migrated_database_url: str,  # noqa: F811
    designated_charge: bool,
) -> None:
    human, prop, credit, invoice, line, _ = source(
        migrated_database_url, period_start=date(2026, 5, 1)
    )
    late_service().finalize_decision(
        prop,
        invoice,
        FinalizeLatePaymentDecisionCommand(
            uuid4(),
            DecisionOutcome.CONFIRMED_DEFAULT,
            8000,
            "Confirmed separate charge",
        ),
        actor=late_payment_actor(human, prop),
    )
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT id FROM app.late_payment_charges WHERE source_invoice_id=%s", (invoice,)
        ).fetchone()
        assert row is not None
        charge = UUID(str(row[0]))
    intent: dict[str, object] = {
        "mode": "DESIGNATED" if designated_charge else "DIRECT_CHARGE",
        "late_payment_charge_id": str(charge),
        "amount_usd_cents": 4000,
    }
    if designated_charge:
        intent["designation_reference"] = "Customer selects separate Charge"
    result = service().apply(
        prop, credit, ApplyCreditCommand(uuid4(), intent), actor=actor(human, prop, "credits.apply")
    )
    assert result["target_balance_usd_cents"] == 4000 and result["target_invoice_status"] is None
    application = result["application"]
    details = result["details"]
    assert isinstance(application, dict) and isinstance(details, list)
    assert application["invoice_id"] is None and application["late_payment_charge_id"] == str(
        charge
    )
    assert application["proposal_trace"] is application["proposal_generated_at"] is None
    assert details[0]["invoice_line_id"] is details[0]["invoice_line_category_snapshot"] is None
    assert details[0]["proposed_amount_usd_cents"] is None
    assert details[0]["attribution_basis"] == (
        "CUSTOMER_DESIGNATED" if designated_charge else "DIRECT_LATE_PAYMENT_CHARGE"
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT status,app.invoice_line_outstanding(%s) FROM app.invoices WHERE id=%s",
            (line, invoice),
        ).fetchone() == ("UNPAID", 80000)
        summary = connection.execute(
            "SELECT app.late_payment_charge_application_summary(%s)", (charge,)
        ).fetchone()
        assert summary is not None
        assert summary[0]["payment_total_usd_cents"] == 0
        assert summary[0]["credit_total_usd_cents"] == summary[0]["active_total_usd_cents"] == 4000
        assert summary[0]["items"][0]["kind"] == "CREDIT_APPLICATION"
    with pytest.raises(LatePaymentApplicationReversalRequired):
        late_service().correct_charge(
            prop,
            charge,
            CorrectLatePaymentChargeCommand(
                uuid4(), CorrectionKind.REDUCTION, "Below applied value", 4001
            ),
            actor=late_payment_actor(human, prop),
        )
    reversed_result = service().reverse_application(
        prop,
        application_id(result),
        ReverseCreditApplicationCommand(uuid4(), "Wrong target"),
        actor=actor(human, prop, "credits.applications.reverse"),
    )
    assert reversed_result["target_balance_usd_cents"] == 8000
    late_service().correct_charge(
        prop,
        charge,
        CorrectLatePaymentChargeCommand(
            uuid4(), CorrectionKind.REDUCTION, "Authorized reduction", 4001
        ),
        actor=late_payment_actor(human, prop),
    )


def test_credit_application_invoice_adjustment_void_and_temporal_guards(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, credit, invoice, line, _ = source(migrated_database_url)
    result = service().apply(
        prop, credit, designated(invoice, line, 20000), actor=actor(human, prop, "credits.apply")
    )
    identity = application_id(result)
    invoices = PostgresInvoiceService(runtime_database_url(), financial_database_url())
    with psycopg.connect(migrated_database_url) as connection:
        version = connection.execute(
            "SELECT version FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
        at = connection.execute(
            "SELECT occurred_at FROM app.customer_credit_applications WHERE id=%s", (identity,)
        ).fetchone()
        assert version is not None and at is not None
        with pytest.raises(psycopg.Error), connection.transaction():
            connection.execute(
                "INSERT INTO app.customer_credit_application_reversals "
                "VALUES(%s,%s,'Backdated',%s,%s,'credits.applications.reverse')",
                (uuid4(), identity, at[0] - timedelta(microseconds=1), human),
            )
        with pytest.raises(psycopg.Error), connection.transaction():
            connection.execute(
                "INSERT INTO app.invoice_adjustments "
                "VALUES(%s,%s,%s,'CREDIT',1,'Backdated source','Backdated',"
                "%s,%s,'invoices.adjust')",
                (uuid4(), invoice, line, at[0] - timedelta(microseconds=1), human),
            )
    with psycopg.connect(migrated_database_url) as connection:
        obligation = connection.execute(
            "SELECT app.invoice_adjusted_line_obligation(%s)", (line,)
        ).fetchone()
        assert obligation is not None
    # BR-INV-044 replaced the older rule: a credit beyond the unpaid amount is accepted and
    # its excess becomes Customer Credit (see test_credit_adjustment_excess_migration.py).
    # Still rejected: a credit beyond the line's adjusted obligation.
    with pytest.raises(InvoiceInvalidError):
        invoices.adjust(
            prop,
            invoice,
            AdjustInvoiceCommand(
                uuid4(),
                line,
                AdjustmentType.CREDIT,
                int(str(obligation[0])) + 1,
                "excess-adjustment",
                "Cannot reduce applied value",
                int(version[0]),
            ),
            actor=invoice_api_actor(human, prop),
        )
    with pytest.raises(InvoiceInvalidError):
        invoices.void(
            prop,
            invoice,
            VoidInvoiceCommand(uuid4(), "Cannot void active Credit", int(version[0])),
            actor=invoice_api_actor(human, prop),
        )
    adjusted = invoices.adjust(
        prop,
        invoice,
        AdjustInvoiceCommand(
            uuid4(),
            line,
            AdjustmentType.CREDIT,
            60000,
            "remaining-adjustment",
            "Reduce remaining amount",
            int(version[0]),
        ),
        actor=invoice_api_actor(human, prop),
    )
    adjusted_balance = adjusted["outstanding_balance"]
    assert isinstance(adjusted_balance, dict)
    assert adjusted["status"] == "PAID" and adjusted_balance["minor_units"] == 0
    after = service().reverse_application(
        prop,
        identity,
        ReverseCreditApplicationCommand(uuid4(), "Wrong application"),
        actor=actor(human, prop, "credits.applications.reverse"),
    )
    assert after["target_invoice_status"] == "UNPAID" and after["target_balance_usd_cents"] == 20000
    with psycopg.connect(migrated_database_url) as connection:
        # The pre-existing adjustment must also be explicitly resolved before VOID.
        connection.execute(
            "INSERT INTO app.invoice_adjustment_reversals "
            "SELECT %s,id,'Wrong adjustment',clock_timestamp(),%s,'invoices.adjustments.reverse' "
            "FROM app.invoice_adjustments WHERE invoice_id=%s "
            "AND source_reference='remaining-adjustment'",
            (uuid4(), human, invoice),
        )
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        updated = connection.execute(
            "SELECT version FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
        assert updated is not None
    voided = invoices.void(
        prop,
        invoice,
        VoidInvoiceCommand(uuid4(), "Correct issued Invoice", int(updated[0])),
        actor=invoice_api_actor(human, prop),
    )
    assert voided["status"] == "VOID"
    readback = service().get_application(prop, identity, actor=actor(human, prop, "credits.read"))
    assert readback["target_invoice_status"] == "VOID" and readback["target_balance_usd_cents"] == 0


def test_credit_application_cross_lease_same_customer_and_source_budget_concurrency(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, credit, invoice, line, payment = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT payer_customer_id FROM app.payments WHERE id=%s", (payment,)
        ).fetchone()
        assert row is not None
        customer = UUID(str(row[0]))
        _, _, unit, _ = setup_reservation_sources(connection)
        lease = create_draft(
            connection,
            actor_id=human,
            unit_id=unit,
            primary_tenant_id=customer,
            start_date=date(2027, 1, 1),
            end_date=date(2027, 12, 31),
        )
        sign_lease(connection, lease, human)
        second_invoice, second_line = create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=customer,
            lease_id=lease,
            period_start=date(2027, 3, 1),
        )
    # Same Customer's other Lease is an eligible Credit target.
    service().apply(
        prop,
        credit,
        designated(second_invoice, second_line, 1),
        actor=actor(human, prop, "credits.apply"),
    )
    start = Barrier(2)

    def post(target: tuple[UUID, UUID]) -> str:
        start.wait(timeout=10)
        try:
            service().apply(
                prop, credit, designated(*target, 60000), actor=actor(human, prop, "credits.apply")
            )
            return "posted"
        except CreditUnavailableError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(post, [(invoice, line), (second_invoice, second_line)])) == [
            "posted",
            "rejected",
        ]
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT app.credit_available_value(%s),app.credit_applied_value_at(%s,'infinity')",
            (credit, credit),
        ).fetchone() == (39999, 60001)


@pytest.mark.parametrize(
    "table",
    [
        "customer_credit_applications",
        "customer_credit_application_details",
        "customer_credit_application_reversals",
    ],
)
def test_credit_application_history_immutable_and_private_write_boundary(
    migrated_database_url: str,  # noqa: F811
    table: str,
) -> None:
    human, prop, credit, invoice, line, _ = source(migrated_database_url)
    result = service().apply(
        prop, credit, designated(invoice, line, 1), actor=actor(human, prop, "credits.apply")
    )
    service().reverse_application(
        prop,
        application_id(result),
        ReverseCreditApplicationCommand(uuid4(), "Wrong application"),
        actor=actor(human, prop, "credits.applications.reverse"),
    )
    with psycopg.connect(migrated_database_url) as connection:
        for statement in (
            f"UPDATE app.{table} SET id=id",
            f"DELETE FROM app.{table}",
            f"TRUNCATE app.{table}",
        ):
            with pytest.raises(psycopg.Error), connection.transaction():
                connection.execute(statement)
        assert connection.execute(
            "SELECT has_table_privilege('prm_runtime',%s,'INSERT'),"
            "has_table_privilege('prm_financial',%s,'INSERT')",
            (f"app.{table}", f"app.{table}"),
        ).fetchone() == (False, False)


def test_credit_application_stale_repeatable_read_target_fails_closed(
    migrated_database_url: str,  # noqa: F811
) -> None:
    from test_payment_allocation_migration import actor as allocation_actor
    from test_payment_allocation_migration import designated as allocation_designated
    from test_payment_allocation_migration import service as allocation_service

    human, prop, credit, invoice, line, payment = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT payer_customer_id FROM app.payments WHERE id=%s", (payment,)
        ).fetchone()
        assert row is not None
        second_payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=UUID(str(row[0])),
            amount=100000,
        )
    with psycopg.connect(financial_database_url()) as stale:
        stale.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        # A service-role read establishes its pre-winner snapshot.
        stale.execute("SELECT app.credit_resource(%s,%s,%s)", (prop, credit, human))
        allocation_service().post(
            prop,
            second_payment,
            allocation_designated(invoice, line, 30000),
            actor=allocation_actor(human, prop),
        )
        with pytest.raises(psycopg.errors.SerializationFailure):
            stale.execute(
                "SELECT app.post_credit_application(%s,%s,%s,%s,%s)",
                (prop, credit, human, uuid4(), Jsonb(designated(invoice, line, 60000).intent)),
            )
        stale.rollback()


def test_credit_application_header_detail_mismatch_rolls_back_every_effect(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, credit, invoice, line, _ = source(migrated_database_url)
    command = designated(invoice, line, 100)
    intent = command.intent
    intent["amount_usd_cents"] = 101
    with pytest.raises(CreditUnavailableError):
        service().apply(
            prop,
            credit,
            ApplyCreditCommand(command.idempotency_key, intent),
            actor=actor(human, prop, "credits.apply"),
        )
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT app.credit_available_value(%s)", (credit,)
        ).fetchone() == (100000,)
        assert connection.execute(
            "SELECT count(*) FROM app.customer_credit_applications WHERE customer_credit_id=%s",
            (credit,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.credit_commands WHERE idempotency_key=%s",
            (command.idempotency_key,),
        ).fetchone() == (0,)


def test_credit_application_bounded_proposal_continues_same_invoice_without_losing_intent(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, first_source = setup_invoice_api_source(
            connection,
            amount_usd_cents=1,
            source_reference="credit-bounded-lines",
        )
        sources = []
        for index in range(500):
            source_id = uuid4()
            connection.execute(
                "INSERT INTO app.authorized_nonrecurring_obligations "
                "(id,customer_id,category,description,authorized_amount_usd_cents,"
                "governing_due_date,due_date_source,source_reference,authorized_at,authorized_by,"
                "authorization_reference) VALUES (%s,%s,'MISCELLANEOUS_CHARGES','Bounded line',1,"
                "current_date+14,'credit-bounded-lines',%s,clock_timestamp(),%s,"
                "'invoice.nonrecurring.authorize')",
                (source_id, customer, f"credit-bounded-line/{index}", human),
            )
            sources.append(source_id)
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=501
        )
    # The obligations are not issued yet; recognition is explicit and source-bounded.
    credit = credit_id(recognize(prop, payment, human, 501))
    invoice_service = PostgresInvoiceService(runtime_database_url(), financial_database_url())
    draft = invoice_service.create_draft(
        prop,
        CreateInvoiceDraftCommand(uuid4(), first_source),
        actor=invoice_api_actor(human, prop),
    )
    invoice = UUID(str(draft["id"]))
    with psycopg.connect(migrated_database_url) as connection:
        set_draft_correction_context(
            connection, actor_id=human, reason="Add authorized bounded lines"
        )
        connection.execute(
            "UPDATE app.invoices SET original_total_usd_cents=501,version=version+1,"
            "updated_at=clock_timestamp(),updated_by=%s WHERE id=%s",
            (human, invoice),
        )
        for index, source_id in enumerate(sources, 2):
            connection.execute(
                "INSERT INTO app.invoice_lines "
                "(id,invoice_id,line_sequence,category,description,amount_usd_cents,"
                "authorized_obligation_id,calculation_trace,created_by) VALUES "
                "(%s,%s,%s,'MISCELLANEOUS_CHARGES','Bounded line',1,%s,%s,%s)",
                (
                    uuid4(),
                    invoice,
                    index,
                    source_id,
                    Jsonb(
                        {
                            "formula": "authorized_source_exact_amount",
                            "authorized_obligation_id": str(source_id),
                            "authorized_amount_usd_cents": 1,
                        }
                    ),
                    human,
                ),
            )
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    invoice_service.issue(
        prop, invoice, IssueInvoiceCommand(uuid4(), 2), actor=invoice_api_actor(human, prop)
    )
    staff = actor(human, prop, "credits.apply")
    for requested, expected_count, remaining in ((501, 500, 1), (1, 1, 0)):
        proposal = service().application_proposal(prop, credit, invoice, requested, actor=staff)
        details = proposal["details"]
        assert isinstance(details, list) and len(details) == expected_count
        assert proposal["requested_amount_usd_cents"] == requested
        assert proposal["amount_usd_cents"] == expected_count
        assert proposal["remaining_requested_usd_cents"] == remaining
        assert proposal["continuation_status"] == ("MORE_ELIGIBLE" if remaining else "COMPLETE")
        result = service().apply(
            prop,
            credit,
            ApplyCreditCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
            actor=staff,
        )
        assert result["target_balance_usd_cents"] == remaining
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT app.credit_available_value(%s)", (credit,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT status FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone() == ("PAID",)
        assert connection.execute(
            "SELECT count(*),sum(amount_usd_cents) FROM app.customer_credit_applications "
            "WHERE customer_credit_id=%s",
            (credit,),
        ).fetchone() == (2, 501)


@pytest.mark.parametrize(
    "field", ["credit_id", "customer_id", "invoice_version", "amount", "detail", "attribution"]
)
def test_credit_application_forged_proposal_is_not_authority(
    migrated_database_url: str,  # noqa: F811
    field: str,
) -> None:
    human, prop, credit, invoice, _, _ = source(migrated_database_url)
    staff = actor(human, prop, "credits.apply")
    proposal = service().application_proposal(prop, credit, invoice, 100, actor=staff)
    if field in {"credit_id", "customer_id"}:
        proposal[field] = str(uuid4())
    elif field == "invoice_version":
        proposal[field] = 999
    elif field == "amount":
        proposal["amount_usd_cents"] = 101
    else:
        details = proposal["details"]
        assert isinstance(details, list)
        if field == "detail":
            details[0]["amount_usd_cents"] = 101
        else:
            details[0]["attribution_basis"] = "SERVICE_PROPOSAL"
    request = ApplyCreditCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal})
    with pytest.raises(CreditConflictError):
        service().apply(prop, credit, request, actor=staff)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.customer_credit_applications WHERE customer_credit_id=%s",
            (credit,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.credit_commands WHERE idempotency_key=%s",
            (request.idempotency_key,),
        ).fetchone() == (0,)
