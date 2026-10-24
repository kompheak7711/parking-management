"""Real PostgreSQL coverage for V1-040 Rent and fixed-Service billing."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from time import monotonic, sleep
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import Connection, Error
from psycopg.conninfo import make_conninfo

from property_rental.billing import (
    BILLING_GENERATE_CAPABILITY,
    BillingAuthorizationError,
    BillingConflictError,
    BillingIdempotencyKeyReused,
    BillingInvalidError,
    GenerateRentInvoiceCommand,
    PostgresRentBillingService,
    RentBillingKind,
    billing_request_digest,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease_termination import TerminationBasis
from termination_test_support import terminate_test_lease
from test_invoice_migration import (
    create_recurring_rent_invoice,
    register_billing_service_principal,
    set_draft_correction_context,
)
from test_lease_migration import create_draft, setup_sources, sign_lease


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    value = os.environ.get("MIGRATION_DATABASE_URL")
    if value is None:
        pytest.skip("MIGRATION_DATABASE_URL is required")
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[Connection[tuple[object, ...]]]:
    with psycopg.connect(migrated_database_url) as database_connection:
        yield database_connection
        database_connection.rollback()


def financial_database_url() -> str:
    value = os.environ.get("FINANCIAL_DATABASE_URL")
    if value is None:
        pytest.skip("FINANCIAL_DATABASE_URL is required")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def runtime_database_url() -> str:
    value = os.environ.get("APP_DATABASE_URL")
    if value is None:
        pytest.skip("APP_DATABASE_URL is required")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def admin_database_url() -> str:
    value = os.environ.get("TEST_ADMIN_DATABASE_URL")
    if value is None:
        pytest.skip("TEST_ADMIN_DATABASE_URL is required")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def authenticated(actor_id: UUID, property_id: UUID) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            {CapabilityGrant(BILLING_GENERATE_CAPABILITY, frozenset({str(property_id)}))}
        ),
    )


def add_service(
    connection: Connection[tuple[object, ...]],
    *,
    actor_id: UUID,
    property_id: UUID,
    lease_id: UUID,
    code: str,
    display_name: str,
    first_rate: int,
    second_rate: int,
    approval_from: date = date(2026, 7, 1),
    approval_through: date = date(2026, 12, 31),
    applicable_from: date = date(2026, 7, 27),
    applicable_through: date = date(2026, 12, 31),
    first_rate_effective: date = date(2026, 7, 1),
    second_rate_effective: date = date(2026, 8, 1),
) -> tuple[UUID, UUID, UUID]:
    existing = connection.execute(
        "SELECT service.id FROM app.property_services AS service "
        "WHERE service.property_id=%s AND service.service_code=%s",
        (property_id, code),
    ).fetchone()
    if existing is None:
        service_id = uuid4()
        connection.execute(
            "INSERT INTO app.property_services(id,property_id,service_code,display_name,"
            "configured_by,created_by,updated_by) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (service_id, property_id, code, display_name, actor_id, actor_id, actor_id),
        )
    else:
        service_id = UUID(str(existing[0]))
    for amount, effective_date in (
        (first_rate, first_rate_effective),
        (second_rate, second_rate_effective),
    ):
        existing_rate = connection.execute(
            "SELECT monthly_rate_usd_cents FROM app.service_rates "
            "WHERE property_service_id=%s AND effective_date=%s",
            (service_id, effective_date),
        ).fetchone()
        if existing_rate is None:
            connection.execute(
                "INSERT INTO app.service_rates(id,property_service_id,monthly_rate_usd_cents,"
                "effective_date,actor_id) VALUES (%s,%s,%s,%s,%s)",
                (uuid4(), service_id, amount, effective_date, actor_id),
            )
        else:
            assert int(str(existing_rate[0])) == amount
    existing_approval = connection.execute(
        "SELECT id FROM app.property_service_approval_periods "
        "WHERE property_service_id=%s AND effective_from=%s AND effective_through=%s",
        (service_id, approval_from, approval_through),
    ).fetchone()
    if existing_approval is None:
        approval_id = uuid4()
        connection.execute(
            "INSERT INTO app.property_service_approval_periods(id,property_service_id,"
            "effective_from,effective_through,approval_reference,approved_at,approved_by,"
            "reason) VALUES (%s,%s,%s,%s,%s,statement_timestamp(),%s,%s)",
            (
                approval_id,
                service_id,
                approval_from,
                approval_through,
                f"OWNER-{code}-{approval_from.isoformat()}",
                actor_id,
                f"Approved {display_name}",
            ),
        )
    else:
        approval_id = UUID(str(existing_approval[0]))
    term_id = uuid4()
    connection.execute(
        "INSERT INTO app.lease_service_terms(id,lease_id,property_service_id,applicable_from,"
        "applicable_through,service_approval_period_id,terms_reference,recorded_at,recorded_by) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,statement_timestamp(),%s)",
        (
            term_id,
            lease_id,
            service_id,
            applicable_from,
            applicable_through,
            approval_id,
            f"LEASE-{code}-{applicable_from.isoformat()}",
            actor_id,
        ),
    )
    return service_id, approval_id, term_id


def setup_billing_source(
    connection: Connection[tuple[object, ...]],
    *,
    configure_trash: bool = True,
    configure_internet: bool = True,
    move_in_date: date = date(2026, 7, 27),
    lease_end_date: date = date(2027, 6, 30),
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    actor_id, property_id, unit_id, customer_id, _ = setup_sources(connection)
    lease_id = create_draft(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        primary_tenant_id=customer_id,
        start_date=move_in_date,
        end_date=lease_end_date,
    )
    sign_lease(connection, lease_id, actor_id)
    occupancy_id = uuid4()
    connection.execute(
        "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,created_by,updated_by) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (occupancy_id, lease_id, customer_id, move_in_date, actor_id, actor_id),
    )
    if configure_trash:
        add_service(
            connection,
            actor_id=actor_id,
            property_id=property_id,
            lease_id=lease_id,
            code="TRASH_COLLECTION",
            display_name="Trash Collection",
            first_rate=1_000,
            second_rate=1_200,
        )
    if configure_internet:
        add_service(
            connection,
            actor_id=actor_id,
            property_id=property_id,
            lease_id=lease_id,
            code="INTERNET",
            display_name="Internet",
            first_rate=2_500,
            second_rate=2_700,
        )
    connection.commit()
    return actor_id, property_id, customer_id, lease_id, occupancy_id


def initial_command(
    lease_id: UUID, occupancy_id: UUID, **changes: object
) -> GenerateRentInvoiceCommand:
    values: dict[str, object] = {
        "idempotency_key": uuid4(),
        "invoice_id": uuid4(),
        "invoice_number": f"INV-{uuid4().hex}",
        "lease_id": lease_id,
        "billing_kind": RentBillingKind.INITIAL,
        "period_start": date(2026, 7, 27),
        "issued_at": datetime(2026, 7, 26, 17, 0, 1, tzinfo=UTC),
        "source_occupancy_id": None,
    }
    values.update(changes)
    return GenerateRentInvoiceCommand(**values)  # type: ignore[arg-type]


def recurring_command(lease_id: UUID, **changes: object) -> GenerateRentInvoiceCommand:
    values: dict[str, object] = {
        "idempotency_key": uuid4(),
        "invoice_id": uuid4(),
        "invoice_number": f"INV-{uuid4().hex}",
        "lease_id": lease_id,
        "billing_kind": RentBillingKind.RECURRING,
        "period_start": date(2026, 9, 1),
        "issued_at": datetime(2026, 8, 24, 17, 0, 1, tzinfo=UTC),
    }
    values.update(changes)
    return GenerateRentInvoiceCommand(**values)  # type: ignore[arg-type]


def test_initial_invoice_preserves_rent_service_components_and_excludes_unapproved_type(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(connection)
    service = PostgresRentBillingService(financial_database_url(), property_id, actor_id)
    result = service.generate(
        initial_command(lease_id, occupancy_id), actor=authenticated(actor_id, property_id)
    )
    assert result.rent_usd_cents == 92_903
    assert result.service_usd_cents == 1_361
    assert result.total_usd_cents == 94_264
    assert result.due_date == date(2026, 8, 1)
    assert result.period_end == date(2026, 8, 31)
    assert result.service_line_count == 2
    assert result.status == "UNPAID"
    audit_row = connection.execute(
        "SELECT invoice.invoice_date,invoice.issued_at,invoice.created_at,command.completed_at,"
        "clock_timestamp() FROM app.invoices AS invoice "
        "JOIN app.rent_billing_commands AS command ON command.invoice_id=invoice.id "
        "WHERE invoice.id=%s",
        (result.invoice_id,),
    ).fetchone()
    assert audit_row is not None
    invoice_date, issued_at, created_at, completed_at, database_now = cast(
        tuple[date, datetime, datetime, datetime, datetime], audit_row
    )
    assert invoice_date == date(2026, 7, 27)
    assert issued_at == created_at
    assert completed_at >= issued_at
    assert issued_at > initial_command(lease_id, occupancy_id).issued_at
    assert database_now - issued_at < timedelta(seconds=10)
    assert connection.execute(
        "SELECT line.line_sequence,service.service_code,line.amount_usd_cents,"
        "line.service_rate_id IS NOT NULL,line.contractual_monthly_usd_cents "
        "FROM app.invoice_lines AS line "
        "JOIN app.property_services AS service ON service.id=line.property_service_id "
        "WHERE line.invoice_id=%s AND line.category='SERVICE_CHARGES' "
        "ORDER BY line.line_sequence",
        (result.invoice_id,),
    ).fetchall() == [
        (2, "TRASH_COLLECTION", 161, True, 1_000),
        (3, "TRASH_COLLECTION", 1_200, True, 1_200),
    ]
    assert connection.execute(
        "SELECT line.line_sequence,component_sequence,component_kind,"
        "service_monthly_rate_usd_cents,"
        "component.billable_days,component.calendar_days,component.amount_usd_cents "
        "FROM app.invoice_line_calculation_components AS component "
        "JOIN app.invoice_lines AS line ON line.id=component.invoice_line_id "
        "WHERE line.invoice_id=%s AND line.category='SERVICE_CHARGES' "
        "ORDER BY line.line_sequence,component_sequence",
        (result.invoice_id,),
    ).fetchall() == [
        (2, 1, "PRORATED_MOVE_IN_MONTH", 1_000, 5, 31, 161),
        (3, 1, "FULL_FOLLOWING_MONTH", 1_200, 31, 31, 1_200),
    ]


def test_initial_invoice_bills_service_that_becomes_eligible_only_in_second_month(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(
        connection,
        configure_trash=False,
        configure_internet=False,
        move_in_date=date(2025, 7, 27),
        lease_end_date=date(2026, 6, 30),
    )
    _, approval_id, term_id = add_service(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        lease_id=lease_id,
        code="TRASH_COLLECTION",
        display_name="Trash Collection",
        first_rate=1_000,
        second_rate=1_200,
        approval_from=date(2025, 8, 1),
        approval_through=date(2025, 12, 31),
        applicable_from=date(2025, 8, 1),
        applicable_through=date(2025, 12, 31),
        first_rate_effective=date(2025, 7, 1),
        second_rate_effective=date(2025, 8, 1),
    )
    connection.commit()
    result = PostgresRentBillingService(financial_database_url(), property_id, actor_id).generate(
        initial_command(
            lease_id,
            occupancy_id,
            period_start=date(2025, 7, 27),
            issued_at=datetime(2025, 7, 26, 17, 0, 1, tzinfo=UTC),
        ),
        actor=authenticated(actor_id, property_id),
    )
    assert result.service_usd_cents == 1_200
    assert result.service_line_count == 1
    assert connection.execute(
        "SELECT period_start,period_end,service_approval_period_id,lease_service_term_id,"
        "amount_usd_cents FROM app.invoice_lines "
        "WHERE invoice_id=%s AND category='SERVICE_CHARGES'",
        (result.invoice_id,),
    ).fetchone() == (date(2025, 8, 1), date(2025, 8, 31), approval_id, term_id, 1_200)


def test_initial_invoice_preserves_adjacent_service_approval_provenance(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(
        connection,
        configure_trash=False,
        configure_internet=False,
        move_in_date=date(2024, 7, 27),
        lease_end_date=date(2025, 6, 30),
    )
    _, july_approval_id, july_term_id = add_service(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        lease_id=lease_id,
        code="TRASH_COLLECTION",
        display_name="Trash Collection",
        first_rate=1_000,
        second_rate=1_200,
        approval_from=date(2024, 7, 1),
        approval_through=date(2024, 7, 31),
        applicable_from=date(2024, 7, 27),
        applicable_through=date(2024, 7, 31),
        first_rate_effective=date(2024, 7, 1),
        second_rate_effective=date(2024, 8, 1),
    )
    _, august_approval_id, august_term_id = add_service(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        lease_id=lease_id,
        code="TRASH_COLLECTION",
        display_name="Trash Collection",
        first_rate=1_000,
        second_rate=1_200,
        approval_from=date(2024, 8, 1),
        approval_through=date(2024, 12, 31),
        applicable_from=date(2024, 8, 1),
        applicable_through=date(2024, 12, 31),
        first_rate_effective=date(2024, 7, 1),
        second_rate_effective=date(2024, 8, 1),
    )
    connection.commit()
    result = PostgresRentBillingService(financial_database_url(), property_id, actor_id).generate(
        initial_command(
            lease_id,
            occupancy_id,
            period_start=date(2024, 7, 27),
            issued_at=datetime(2024, 7, 26, 17, 0, 1, tzinfo=UTC),
        ),
        actor=authenticated(actor_id, property_id),
    )
    assert result.service_usd_cents == 1_361
    assert result.service_line_count == 2
    assert connection.execute(
        "SELECT period_start,period_end,service_approval_period_id,lease_service_term_id "
        "FROM app.invoice_lines WHERE invoice_id=%s AND category='SERVICE_CHARGES' "
        "ORDER BY period_start",
        (result.invoice_id,),
    ).fetchall() == [
        (date(2024, 7, 27), date(2024, 7, 31), july_approval_id, july_term_id),
        (date(2024, 8, 1), date(2024, 8, 31), august_approval_id, august_term_id),
    ]


def test_replay_is_stable_and_changed_digest_is_rejected(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(connection)
    service = PostgresRentBillingService(financial_database_url(), property_id, actor_id)
    actor = authenticated(actor_id, property_id)
    value = initial_command(lease_id, occupancy_id)
    first = service.generate(value, actor=actor)
    assert service.generate(value, actor=actor) == first
    assert (
        service.generate(
            replace(value, issued_at=value.issued_at.astimezone(timezone(timedelta(hours=7)))),
            actor=actor,
        )
        == first
    )
    with pytest.raises(BillingIdempotencyKeyReused):
        service.generate(
            initial_command(
                lease_id,
                occupancy_id,
                idempotency_key=value.idempotency_key,
                invoice_id=value.invoice_id,
                invoice_number=f"{value.invoice_number}-changed",
            ),
            actor=actor,
        )
    assert connection.execute(
        "SELECT count(*) FROM app.rent_billing_commands WHERE invoice_id=%s",
        (first.invoice_id,),
    ).fetchone() == (1,)


def test_direct_financial_replay_requires_digest_and_every_request_field(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(connection)
    command_value = initial_command(lease_id, occupancy_id)
    service = PostgresRentBillingService(financial_database_url(), property_id, actor_id)
    service.generate(command_value, actor=authenticated(actor_id, property_id))
    digest = billing_request_digest(command_value)

    with psycopg.connect(financial_database_url()) as financial:
        with pytest.raises(Error) as conflict:
            financial.execute(
                "SELECT app.generate_rent_service_invoice(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    property_id,
                    command_value.idempotency_key,
                    digest,
                    command_value.invoice_id,
                    f"{command_value.invoice_number}-tampered",
                    lease_id,
                    None,
                    command_value.billing_kind,
                    command_value.period_start,
                    command_value.issued_at,
                    actor_id,
                    None,
                ),
            )
        assert conflict.value.sqlstate == "23505"

    with psycopg.connect(financial_database_url()) as financial:
        with pytest.raises(Error) as missing_digest:
            financial.execute(
                "SELECT app.generate_rent_service_invoice(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    property_id,
                    command_value.idempotency_key,
                    None,
                    command_value.invoice_id,
                    command_value.invoice_number,
                    lease_id,
                    None,
                    command_value.billing_kind,
                    command_value.period_start,
                    command_value.issued_at,
                    actor_id,
                    None,
                ),
            )
        assert missing_digest.value.sqlstate == "22023"
    with psycopg.connect(financial_database_url()) as financial:
        with pytest.raises(Error) as missing_kind:
            financial.execute(
                "SELECT app.generate_rent_service_invoice(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    property_id,
                    command_value.idempotency_key,
                    digest,
                    command_value.invoice_id,
                    command_value.invoice_number,
                    lease_id,
                    None,
                    None,
                    command_value.period_start,
                    command_value.issued_at,
                    actor_id,
                    None,
                ),
            )
        assert missing_kind.value.sqlstate == "22023"
    assert connection.execute(
        "SELECT count(*) FROM app.rent_billing_commands WHERE idempotency_key=%s",
        (command_value.idempotency_key,),
    ).fetchone() == (1,)


def test_replay_rechecks_current_actor_lifecycle(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(connection)
    service = PostgresRentBillingService(financial_database_url(), property_id, actor_id)
    actor = authenticated(actor_id, property_id)
    value = initial_command(lease_id, occupancy_id)
    service.generate(value, actor=actor)
    connection.execute(
        "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s",
        (actor_id,),
    )
    connection.commit()
    with pytest.raises(BillingAuthorizationError, match="no longer active"):
        service.generate(value, actor=actor)
    assert connection.execute(
        "SELECT count(*) FROM app.rent_billing_commands WHERE idempotency_key=%s",
        (value.idempotency_key,),
    ).fetchone() == (1,)


def test_future_initial_and_recurring_business_dates_are_rejected_without_writes(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(connection)
    service = PostgresRentBillingService(financial_database_url(), property_id, actor_id)
    actor = authenticated(actor_id, property_id)
    future = datetime.now(UTC) + timedelta(days=1)
    for value in (
        initial_command(lease_id, occupancy_id, issued_at=future),
        recurring_command(lease_id, issued_at=future),
    ):
        with pytest.raises(BillingInvalidError):
            service.generate(value, actor=actor)
    assert connection.execute(
        "SELECT count(*) FROM app.rent_billing_commands WHERE lease_id=%s", (lease_id,)
    ).fetchone() == (0,)
    assert connection.execute(
        "SELECT count(*) FROM app.invoices WHERE lease_id=%s", (lease_id,)
    ).fetchone() == (0,)


def test_initial_period_cannot_cross_contractual_or_processed_termination_boundary(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(
        connection,
        configure_trash=False,
        configure_internet=False,
        lease_end_date=date(2026, 8, 15),
    )
    service = PostgresRentBillingService(financial_database_url(), property_id, actor_id)
    with pytest.raises(BillingInvalidError):
        service.generate(
            initial_command(lease_id, occupancy_id),
            actor=authenticated(actor_id, property_id),
        )
    assert connection.execute(
        "SELECT count(*) FROM app.invoices WHERE lease_id=%s", (lease_id,)
    ).fetchone() == (0,)
    assert connection.execute(
        "SELECT count(*) FROM app.rent_billing_commands WHERE lease_id=%s", (lease_id,)
    ).fetchone() == (0,)

    business_date_row = connection.execute(
        "SELECT timezone('Asia/Phnom_Penh',statement_timestamp())::date"
    ).fetchone()
    assert business_date_row is not None
    business_date = cast(date, business_date_row[0])
    actor_2, property_2, _, lease_2, occupancy_2 = setup_billing_source(
        connection,
        configure_trash=False,
        configure_internet=False,
        move_in_date=business_date,
        lease_end_date=business_date + timedelta(days=365),
    )
    occurred_at_row = connection.execute("SELECT statement_timestamp()").fetchone()
    assert occurred_at_row is not None
    occurred_at = cast(datetime, occurred_at_row[0])
    version = connection.execute(
        "SELECT version FROM app.leases WHERE id=%s", (lease_2,)
    ).fetchone()
    assert version is not None
    terminate_test_lease(
        connection,
        property_id=property_2,
        actor_id=actor_2,
        lease_id=lease_2,
        expected_version=int(str(version[0])),
        actual_date=business_date,
        occurred_at=occurred_at,
        governing="AUTHORIZED-ACTUAL-TERMINATION-001",
        reason="Authorized same-day termination",
        basis=TerminationBasis.SIGNED_LEASE_OTHER,
    )
    connection.commit()
    with pytest.raises(BillingInvalidError):
        PostgresRentBillingService(financial_database_url(), property_2, actor_2).generate(
            initial_command(
                lease_2,
                occupancy_2,
                period_start=business_date,
                issued_at=occurred_at,
            ),
            actor=authenticated(actor_2, property_2),
        )
    assert connection.execute(
        "SELECT count(*) FROM app.invoices WHERE lease_id=%s", (lease_2,)
    ).fetchone() == (0,)


@pytest.mark.parametrize(
    ("move_in_date", "approval_from", "approval_through", "applicable_from", "applicable_through"),
    (
        (
            date(2022, 7, 27),
            date(2022, 7, 29),
            date(2022, 12, 31),
            date(2022, 7, 29),
            date(2022, 12, 31),
        ),
        (
            date(2023, 7, 10),
            date(2023, 7, 1),
            date(2023, 7, 20),
            date(2023, 7, 10),
            date(2023, 7, 20),
        ),
    ),
)
def test_partial_month_service_configuration_fails_explicitly_without_underbilling(
    connection: Connection[tuple[object, ...]],
    move_in_date: date,
    approval_from: date,
    approval_through: date,
    applicable_from: date,
    applicable_through: date,
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(
        connection,
        configure_trash=False,
        configure_internet=False,
        move_in_date=move_in_date,
        lease_end_date=move_in_date + timedelta(days=365),
    )
    add_service(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        lease_id=lease_id,
        code="TRASH_COLLECTION",
        display_name="Trash Collection",
        first_rate=1_000,
        second_rate=1_200,
        approval_from=approval_from,
        approval_through=approval_through,
        applicable_from=applicable_from,
        applicable_through=applicable_through,
        first_rate_effective=move_in_date.replace(day=1),
        second_rate_effective=(move_in_date.replace(day=28) + timedelta(days=4)).replace(day=1),
    )
    connection.commit()
    with pytest.raises(BillingInvalidError):
        PostgresRentBillingService(financial_database_url(), property_id, actor_id).generate(
            initial_command(
                lease_id,
                occupancy_id,
                period_start=move_in_date,
                issued_at=datetime.combine(
                    move_in_date,
                    datetime.min.time(),
                    tzinfo=timezone(timedelta(hours=7)),
                ),
            ),
            actor=authenticated(actor_id, property_id),
        )
    assert connection.execute(
        "SELECT count(*) FROM app.invoices WHERE lease_id=%s", (lease_id,)
    ).fetchone() == (0,)
    assert connection.execute(
        "SELECT count(*) FROM app.rent_billing_commands WHERE lease_id=%s", (lease_id,)
    ).fetchone() == (0,)


def test_exact_unproven_existing_invoice_is_never_adopted_as_generated(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, customer_id, lease_id, _ = setup_billing_source(
        connection,
        configure_trash=False,
        configure_internet=False,
    )
    invoice_id, _ = create_recurring_rent_invoice(
        connection,
        actor_id=actor_id,
        customer_id=customer_id,
        lease_id=lease_id,
        period_start=date(2026, 9, 1),
        issue=False,
        validate_immediately=False,
    )
    set_draft_correction_context(
        connection,
        actor_id=actor_id,
        reason="Production-shaped legacy Invoice chronology fixture",
    )
    connection.execute(
        "UPDATE app.invoices SET invoice_date=%s,status='UNPAID',issued_at=statement_timestamp(),"
        "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
        (date(2026, 8, 25), actor_id, actor_id, invoice_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    connection.commit()
    with pytest.raises(BillingConflictError):
        PostgresRentBillingService(financial_database_url(), property_id, actor_id).generate(
            recurring_command(lease_id),
            actor=authenticated(actor_id, property_id),
        )
    assert connection.execute(
        "SELECT count(*) FROM app.rent_billing_commands WHERE lease_id=%s", (lease_id,)
    ).fetchone() == (0,)


def test_existing_invoice_adoption_rejects_out_of_scope_billing_run_attempt(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(connection)
    human_service = PostgresRentBillingService(financial_database_url(), property_id, actor_id)
    human_actor = authenticated(actor_id, property_id)
    human_service.generate(initial_command(lease_id, occupancy_id), actor=human_actor)
    existing = human_service.generate(recurring_command(lease_id), actor=human_actor)

    service_actor_id = register_billing_service_principal(
        connection,
        property_id=property_id,
        created_by=actor_id,
    )
    run_id = uuid4()
    attempt_id = uuid4()
    connection.execute(
        "INSERT INTO app.billing_runs(id,property_id,run_kind,logical_run_key,business_date,"
        "period_start,period_end,idempotency_key,system_actor_id,status,started_at) VALUES "
        "(%s,%s,'RENT',%s,'2026-07-25','2026-08-01','2026-08-31',%s,%s,'RUNNING',"
        "statement_timestamp())",
        (run_id, property_id, f"wrong-period-{run_id.hex}", uuid4(), service_actor_id),
    )
    connection.execute(
        "INSERT INTO app.billing_run_attempts(id,billing_run_id,attempt_number,started_at,outcome) "
        "VALUES (%s,%s,1,statement_timestamp(),'RUNNING')",
        (attempt_id, run_id),
    )
    connection.commit()

    with pytest.raises(BillingInvalidError):
        PostgresRentBillingService(
            financial_database_url(), property_id, service_actor_id
        ).generate(
            recurring_command(
                lease_id,
                originating_billing_run_attempt_id=attempt_id,
            ),
            actor=authenticated(service_actor_id, property_id),
        )
    assert connection.execute(
        "SELECT count(*) FROM app.rent_billing_commands WHERE invoice_id=%s",
        (existing.invoice_id,),
    ).fetchone() == (1,)


def test_nonidentical_overlap_conflicts_instead_of_returning_partial_coverage(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(connection)
    service = PostgresRentBillingService(financial_database_url(), property_id, actor_id)
    actor = authenticated(actor_id, property_id)
    initial = service.generate(initial_command(lease_id, occupancy_id), actor=actor)
    overlapping_recurring = recurring_command(
        lease_id,
        period_start=date(2026, 8, 1),
        issued_at=datetime(2026, 7, 24, 17, 0, 1, tzinfo=UTC),
    )
    with pytest.raises(BillingConflictError):
        service.generate(overlapping_recurring, actor=actor)
    assert connection.execute(
        "SELECT id FROM app.invoices WHERE lease_id=%s", (lease_id,)
    ).fetchall() == [(initial.invoice_id,)]
    assert connection.execute(
        "SELECT count(*) FROM app.rent_billing_commands WHERE lease_id=%s",
        (lease_id,),
    ).fetchone() == (1,)


def test_concurrent_recurring_generation_produces_one_invoice_and_historical_rate(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(connection)
    service = PostgresRentBillingService(financial_database_url(), property_id, actor_id)
    actor = authenticated(actor_id, property_id)
    service.generate(initial_command(lease_id, occupancy_id), actor=actor)
    commands = (recurring_command(lease_id), recurring_command(lease_id))
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda value: service.generate(value, actor=actor), commands))
    assert results[0].invoice_id == results[1].invoice_id
    assert results[0].rent_usd_cents == 80_000
    assert results[0].service_usd_cents == 1_200
    assert results[0].invoice_date == date(2026, 8, 25)
    assert results[0].due_date == date(2026, 9, 5)
    assert connection.execute(
        "SELECT count(*) FROM app.invoices WHERE lease_id=%s AND rent_billing_kind='RECURRING'",
        (lease_id,),
    ).fetchone() == (1,)
    assert connection.execute(
        "SELECT count(*),min(result_snapshot->>'invoice_id'),max(result_snapshot->>'invoice_id') "
        "FROM app.rent_billing_commands WHERE lease_id=%s AND billing_kind='RECURRING'",
        (lease_id,),
    ).fetchone() == (2, str(results[0].invoice_id), str(results[0].invoice_id))


def test_blocked_earlier_command_completes_after_the_adopted_invoice_chronology(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(
        connection,
        configure_trash=False,
        configure_internet=False,
    )
    actor = authenticated(actor_id, property_id)
    earlier_command = initial_command(lease_id, occupancy_id)
    later_command = initial_command(lease_id, occupancy_id)
    application_name = f"v1040-earlier-{uuid4().hex}"
    earlier_service = PostgresRentBillingService(
        make_conninfo(financial_database_url(), application_name=application_name),
        property_id,
        actor_id,
    )
    later_service = PostgresRentBillingService(financial_database_url(), property_id, actor_id)
    lock_key = f"rent-billing-command:{property_id}:{actor_id}:{earlier_command.idempotency_key}"

    with psycopg.connect(financial_database_url()) as blocker:
        blocker.execute(
            "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(%s,0))",
            (lock_key,),
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            earlier_future = executor.submit(earlier_service.generate, earlier_command, actor=actor)
            with psycopg.connect(admin_database_url(), autocommit=True) as observer:
                deadline = monotonic() + 5
                while monotonic() < deadline:
                    waiting = observer.execute(
                        "SELECT wait_event_type FROM pg_catalog.pg_stat_activity "
                        "WHERE application_name=%s AND state='active'",
                        (application_name,),
                    ).fetchone()
                    if waiting is not None and waiting[0] == "Lock":
                        break
                    sleep(0.02)
                else:
                    pytest.fail("earlier billing command did not block on its command lock")
            later = later_service.generate(later_command, actor=actor)
            blocker.commit()
            earlier = earlier_future.result(timeout=5)

    assert earlier.invoice_id == later.invoice_id
    chronology = connection.execute(
        "SELECT invoice.issued_at,earlier.completed_at,later.completed_at "
        "FROM app.invoices AS invoice "
        "JOIN app.rent_billing_commands AS earlier "
        "ON earlier.idempotency_key=%s AND earlier.invoice_id=invoice.id "
        "JOIN app.rent_billing_commands AS later "
        "ON later.idempotency_key=%s AND later.invoice_id=invoice.id",
        (earlier_command.idempotency_key, later_command.idempotency_key),
    ).fetchone()
    assert chronology is not None
    issued_at, earlier_completed_at, later_completed_at = cast(
        tuple[datetime, datetime, datetime], chronology
    )
    assert later_completed_at >= issued_at
    assert earlier_completed_at >= later_completed_at


def test_concurrent_service_rate_cannot_cross_the_durable_selection_cutoff(
    connection: Connection[tuple[object, ...]],
    migrated_database_url: str,
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(
        connection,
        configure_internet=False,
    )
    service_id_row = connection.execute(
        "SELECT id FROM app.property_services "
        "WHERE property_id=%s AND service_code='TRASH_COLLECTION'",
        (property_id,),
    ).fetchone()
    assert service_id_row is not None
    service_id = UUID(str(service_id_row[0]))
    command = initial_command(lease_id, occupancy_id)
    application_name = f"v1040-cutoff-{uuid4().hex}"
    billing_service = PostgresRentBillingService(
        make_conninfo(financial_database_url(), application_name=application_name),
        property_id,
        actor_id,
    )
    actor = authenticated(actor_id, property_id)
    lock_key = f"rent:{lease_id}"
    inserted_rate_id = uuid4()
    writer_application_name = f"v1040-rate-writer-{uuid4().hex}"

    def insert_rate() -> None:
        with psycopg.connect(
            make_conninfo(migrated_database_url, application_name=writer_application_name)
        ) as writer:
            writer.execute(
                "INSERT INTO app.service_rates(id,property_service_id,"
                "monthly_rate_usd_cents,effective_date,actor_id) "
                "VALUES (%s,%s,9900,%s,%s)",
                (inserted_rate_id, service_id, date(2026, 7, 27), actor_id),
            )

    with psycopg.connect(financial_database_url()) as blocker:
        blocker.execute(
            "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(%s,0))",
            (lock_key,),
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            billing_future = executor.submit(billing_service.generate, command, actor=actor)
            with psycopg.connect(admin_database_url(), autocommit=True) as observer:
                deadline = monotonic() + 5
                while monotonic() < deadline:
                    waiting = observer.execute(
                        "SELECT wait_event_type FROM pg_catalog.pg_stat_activity "
                        "WHERE application_name=%s AND state='active'",
                        (application_name,),
                    ).fetchone()
                    if waiting is not None and waiting[0] == "Lock":
                        break
                    sleep(0.02)
                else:
                    pytest.fail("billing command did not hold the Property Service lock")
                writer_future = executor.submit(insert_rate)
                deadline = monotonic() + 5
                while monotonic() < deadline:
                    waiting = observer.execute(
                        "SELECT wait_event_type FROM pg_catalog.pg_stat_activity "
                        "WHERE application_name=%s AND state='active'",
                        (writer_application_name,),
                    ).fetchone()
                    if waiting is not None and waiting[0] == "Lock":
                        break
                    sleep(0.02)
                else:
                    pytest.fail("Service rate writer did not serialize behind billing")
            blocker.commit()
            result = billing_future.result(timeout=5)
            with pytest.raises(Error) as retroactive_rate:
                writer_future.result(timeout=5)

    assert result.service_usd_cents == 1_361
    assert retroactive_rate.value.sqlstate == "23514"
    chronology = connection.execute(
        "SELECT command.source_selection_cutoff,invoice.issued_at "
        "FROM app.rent_billing_commands AS command "
        "JOIN app.invoices AS invoice ON invoice.id=command.invoice_id "
        "WHERE command.idempotency_key=%s",
        (command.idempotency_key,),
    ).fetchone()
    assert chronology is not None
    selection_cutoff, invoice_issued_at = cast(tuple[datetime, datetime], chronology)
    assert invoice_issued_at == selection_cutoff
    assert connection.execute(
        "SELECT count(*) FROM app.service_rates WHERE id=%s", (inserted_rate_id,)
    ).fetchone() == (0,)


def test_service_source_late_commit_is_serialized_before_cutoff_and_reread(
    connection: Connection[tuple[object, ...]],
    migrated_database_url: str,
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(
        connection,
        configure_internet=False,
    )
    service_id_row = connection.execute(
        "SELECT id FROM app.property_services "
        "WHERE property_id=%s AND service_code='TRASH_COLLECTION'",
        (property_id,),
    ).fetchone()
    assert service_id_row is not None
    service_id = UUID(str(service_id_row[0]))
    inserted_rate_id = uuid4()
    command = initial_command(lease_id, occupancy_id)
    application_name = f"v1040-late-service-{uuid4().hex}"
    service = PostgresRentBillingService(
        make_conninfo(financial_database_url(), application_name=application_name),
        property_id,
        actor_id,
    )

    with psycopg.connect(migrated_database_url) as source_writer:
        occurred_at_row = source_writer.execute(
            "INSERT INTO app.service_rates(id,property_service_id,"
            "monthly_rate_usd_cents,effective_date,actor_id) "
            "VALUES (%s,%s,9900,%s,%s) RETURNING occurred_at",
            (inserted_rate_id, service_id, date(2026, 7, 27), actor_id),
        ).fetchone()
        assert occurred_at_row is not None
        occurred_at = cast(datetime, occurred_at_row[0])
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                service.generate,
                command,
                actor=authenticated(actor_id, property_id),
            )
            with psycopg.connect(admin_database_url(), autocommit=True) as observer:
                deadline = monotonic() + 5
                while monotonic() < deadline:
                    waiting = observer.execute(
                        "SELECT wait_event_type FROM pg_catalog.pg_stat_activity "
                        "WHERE application_name=%s AND state='active'",
                        (application_name,),
                    ).fetchone()
                    if waiting is not None and waiting[0] == "Lock":
                        break
                    sleep(0.02)
                else:
                    pytest.fail("billing did not wait for the in-flight Service source")
            source_writer.commit()
            result = future.result(timeout=5)

    assert result.service_usd_cents == 2_797
    chronology = connection.execute(
        "SELECT rate.occurred_at,command.source_selection_cutoff,invoice.issued_at,"
        "min(component.created_at),max(component.created_at) "
        "FROM app.service_rates AS rate "
        "JOIN app.rent_billing_commands AS command ON command.idempotency_key=%s "
        "JOIN app.invoices AS invoice ON invoice.id=command.invoice_id "
        "JOIN app.invoice_lines AS line ON line.invoice_id=invoice.id "
        "JOIN app.invoice_line_calculation_components AS component "
        "ON component.invoice_line_id=line.id WHERE rate.id=%s "
        "GROUP BY rate.occurred_at,command.source_selection_cutoff,invoice.issued_at",
        (command.idempotency_key, inserted_rate_id),
    ).fetchone()
    assert chronology is not None
    stored_rate_at, selection_cutoff, invoice_issued_at, first_component_at, last_component_at = (
        cast(tuple[datetime, datetime, datetime, datetime, datetime], chronology)
    )
    assert stored_rate_at == occurred_at <= selection_cutoff == invoice_issued_at
    assert first_component_at == last_component_at == selection_cutoff


def test_combined_lease_and_service_writer_serializes_at_property_boundary(
    connection: Connection[tuple[object, ...]],
    migrated_database_url: str,
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(
        connection,
        configure_internet=False,
    )
    service_id_row = connection.execute(
        "SELECT id FROM app.property_services "
        "WHERE property_id=%s AND service_code='TRASH_COLLECTION'",
        (property_id,),
    ).fetchone()
    assert service_id_row is not None
    service_id = UUID(str(service_id_row[0]))
    command = initial_command(lease_id, occupancy_id)
    application_name = f"v1040-combined-source-{uuid4().hex}"
    service = PostgresRentBillingService(
        make_conninfo(financial_database_url(), application_name=application_name),
        property_id,
        actor_id,
    )

    with psycopg.connect(migrated_database_url) as source_writer:
        source_writer.execute(
            "UPDATE app.leases SET version=version+1,updated_at=clock_timestamp(),"
            "updated_by=%s WHERE id=%s",
            (actor_id, lease_id),
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                service.generate,
                command,
                actor=authenticated(actor_id, property_id),
            )
            with psycopg.connect(admin_database_url(), autocommit=True) as observer:
                deadline = monotonic() + 5
                while monotonic() < deadline:
                    waiting = observer.execute(
                        "SELECT wait_event_type FROM pg_catalog.pg_stat_activity "
                        "WHERE application_name=%s AND state='active'",
                        (application_name,),
                    ).fetchone()
                    if waiting is not None and waiting[0] == "Lock":
                        break
                    sleep(0.02)
                else:
                    pytest.fail("billing did not wait for the combined source writer")
            source_writer.execute(
                "INSERT INTO app.service_rates(id,property_service_id,"
                "monthly_rate_usd_cents,effective_date,actor_id) "
                "VALUES (%s,%s,9900,%s,%s)",
                (uuid4(), service_id, date(2026, 7, 26), actor_id),
            )
            source_writer.commit()
            result = future.result(timeout=5)

    assert result.service_usd_cents > 0


def test_billing_avoids_reverse_tuple_to_property_lock_deadlock(
    connection: Connection[tuple[object, ...]],
    migrated_database_url: str,
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(connection)
    connection.commit()
    command = initial_command(lease_id, occupancy_id)
    source_application_name = f"v1040-reverse-source-{uuid4().hex}"
    billing_application_name = f"v1040-reverse-billing-{uuid4().hex}"
    service = PostgresRentBillingService(
        make_conninfo(financial_database_url(), application_name=billing_application_name),
        property_id,
        actor_id,
    )

    def update_lease() -> int:
        with psycopg.connect(
            make_conninfo(migrated_database_url, application_name=source_application_name)
        ) as source_writer:
            source_writer.execute("SET LOCAL statement_timeout='10s'")
            updated = source_writer.execute(
                "UPDATE app.leases SET version=version+1,"
                "updated_at=clock_timestamp(),updated_by=%s WHERE id=%s "
                "RETURNING version",
                (actor_id, lease_id),
            ).fetchone()
            assert updated is not None
            return int(updated[0])

    with psycopg.connect(migrated_database_url) as table_blocker:
        table_blocker.execute("LOCK TABLE app.units IN ACCESS EXCLUSIVE MODE")
        with ThreadPoolExecutor(max_workers=2) as executor:
            source_future = executor.submit(update_lease)
            with psycopg.connect(admin_database_url(), autocommit=True) as observer:
                deadline = monotonic() + 5
                while monotonic() < deadline:
                    source_wait = observer.execute(
                        "SELECT wait_event_type FROM pg_catalog.pg_stat_activity "
                        "WHERE application_name=%s AND state='active'",
                        (source_application_name,),
                    ).fetchone()
                    if source_wait is not None and source_wait[0] == "Lock":
                        break
                    sleep(0.02)
                else:
                    pytest.fail("Lease writer did not pause after locking its tuple")

                billing_future = executor.submit(
                    service.generate,
                    command,
                    actor=authenticated(actor_id, property_id),
                )
                deadline = monotonic() + 5
                while monotonic() < deadline:
                    billing_wait = observer.execute(
                        "SELECT wait_event_type FROM pg_catalog.pg_stat_activity "
                        "WHERE application_name=%s AND state='active'",
                        (billing_application_name,),
                    ).fetchone()
                    if billing_wait is not None and billing_wait[0] == "Lock":
                        break
                    sleep(0.02)
                else:
                    pytest.fail("Billing did not reach the Property-owned source read")
            assert not source_future.done()
            table_blocker.commit()
            result = billing_future.result(timeout=10)
            updated_version = source_future.result(timeout=10)

    assert result.invoice_id == command.invoice_id
    assert updated_version > 0
    assert connection.execute(
        "SELECT count(*) FROM app.invoices WHERE id=%s", (command.invoice_id,)
    ).fetchone() == (1,)


def test_cutoff_is_captured_after_concurrent_lease_signing_and_occupancy_commit(
    connection: Connection[tuple[object, ...]],
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, customer_id, _ = setup_sources(connection)
    lease_id = create_draft(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        primary_tenant_id=customer_id,
        start_date=date(2026, 7, 27),
        end_date=date(2027, 6, 30),
    )
    occupancy_id = uuid4()
    command = initial_command(lease_id, occupancy_id)
    connection.commit()
    application_name = f"v1040-source-cutoff-{uuid4().hex}"
    service = PostgresRentBillingService(
        make_conninfo(financial_database_url(), application_name=application_name),
        property_id,
        actor_id,
    )
    actor = authenticated(actor_id, property_id)
    lock_key = f"invoice-property-service:{property_id}"

    with psycopg.connect(migrated_database_url) as source_writer:
        source_writer.execute(
            "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(%s,0))",
            (lock_key,),
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(service.generate, command, actor=actor)
            with psycopg.connect(admin_database_url(), autocommit=True) as observer:
                deadline = monotonic() + 5
                while monotonic() < deadline:
                    waiting = observer.execute(
                        "SELECT wait_event_type FROM pg_catalog.pg_stat_activity "
                        "WHERE application_name=%s AND state='active'",
                        (application_name,),
                    ).fetchone()
                    if waiting is not None and waiting[0] == "Lock":
                        break
                    sleep(0.02)
                else:
                    pytest.fail("billing command did not block on Lease source serialization")
            sign_lease(source_writer, lease_id, actor_id)
            source_writer.execute(
                "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,"
                "created_by,updated_by) VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    occupancy_id,
                    lease_id,
                    customer_id,
                    date(2026, 7, 27),
                    actor_id,
                    actor_id,
                ),
            )
            source_times = source_writer.execute(
                "SELECT lease.signed_at,lease.updated_at,occupancy.created_at,"
                "occupancy.updated_at FROM app.leases AS lease "
                "JOIN app.occupancies AS occupancy ON occupancy.lease_id=lease.id "
                "WHERE lease.id=%s AND occupancy.id=%s",
                (lease_id, occupancy_id),
            ).fetchone()
            assert source_times is not None
            source_writer.commit()
            result = future.result(timeout=5)

    assert result.invoice_id == command.invoice_id
    cutoff_row = connection.execute(
        "SELECT command.source_selection_cutoff,invoice.issued_at "
        "FROM app.rent_billing_commands AS command "
        "JOIN app.invoices AS invoice ON invoice.id=command.invoice_id "
        "WHERE command.idempotency_key=%s",
        (command.idempotency_key,),
    ).fetchone()
    assert cutoff_row is not None
    selection_cutoff, invoice_issued_at = cast(tuple[datetime, datetime], cutoff_row)
    signed_at, lease_updated_at, occupancy_created_at, occupancy_updated_at = cast(
        tuple[datetime, datetime, datetime, datetime], source_times
    )
    assert selection_cutoff == invoice_issued_at
    assert max(signed_at, lease_updated_at, occupancy_created_at, occupancy_updated_at) <= (
        selection_cutoff
    )


@pytest.mark.parametrize("configured_isolation", ("repeatable read", "serializable"))
def test_service_pins_read_committed_for_stable_concurrent_replay(
    connection: Connection[tuple[object, ...]], configured_isolation: str
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(connection)
    isolation_option = configured_isolation.replace(" ", "\\ ")
    service = PostgresRentBillingService(
        make_conninfo(
            financial_database_url(),
            options=f"-c default_transaction_isolation={isolation_option}",
        ),
        property_id,
        actor_id,
    )
    actor = authenticated(actor_id, property_id)
    initial = initial_command(lease_id, occupancy_id)
    with ThreadPoolExecutor(max_workers=2) as executor:
        identical = list(executor.map(lambda _: service.generate(initial, actor=actor), range(2)))
    assert identical[0] == identical[1]
    recurring = (recurring_command(lease_id), recurring_command(lease_id))
    with ThreadPoolExecutor(max_workers=2) as executor:
        distinct = list(executor.map(lambda value: service.generate(value, actor=actor), recurring))
    assert distinct[0] == distinct[1]
    assert connection.execute(
        "SELECT billing_kind,count(*),count(DISTINCT invoice_id) "
        "FROM app.rent_billing_commands WHERE lease_id=%s "
        "GROUP BY billing_kind ORDER BY billing_kind",
        (lease_id,),
    ).fetchall() == [("INITIAL", 1, 1), ("RECURRING", 2, 1)]


@pytest.mark.parametrize("configured_isolation", ("repeatable read", "serializable"))
def test_direct_financial_function_rejects_stale_snapshot_isolation(
    connection: Connection[tuple[object, ...]], configured_isolation: str
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(connection)
    value = initial_command(lease_id, occupancy_id)
    isolation_option = configured_isolation.replace(" ", "\\ ")
    with psycopg.connect(
        make_conninfo(
            financial_database_url(),
            options=f"-c default_transaction_isolation={isolation_option}",
        )
    ) as financial:
        with pytest.raises(Error) as rejected:
            financial.execute(
                "SELECT app.generate_rent_service_invoice(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    property_id,
                    value.idempotency_key,
                    billing_request_digest(value),
                    value.invoice_id,
                    value.invoice_number,
                    lease_id,
                    occupancy_id,
                    value.billing_kind,
                    value.period_start,
                    value.issued_at,
                    actor_id,
                    None,
                ),
            )
        assert rejected.value.sqlstate == "25001"

    assert connection.execute(
        "SELECT count(*) FROM app.invoices WHERE id=%s", (value.invoice_id,)
    ).fetchone() == (0,)
    assert connection.execute(
        "SELECT count(*) FROM app.rent_billing_commands WHERE idempotency_key=%s",
        (value.idempotency_key,),
    ).fetchone() == (0,)


def test_runtime_role_cannot_generate_or_mutate_financial_history(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, lease_id, occupancy_id = setup_billing_source(connection)
    value = initial_command(lease_id, occupancy_id)
    with psycopg.connect(runtime_database_url()) as runtime:
        with pytest.raises(Error) as denied:
            runtime.execute(
                "SELECT app.generate_rent_service_invoice(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    property_id,
                    value.idempotency_key,
                    "0" * 64,
                    value.invoice_id,
                    value.invoice_number,
                    lease_id,
                    occupancy_id,
                    value.billing_kind,
                    value.period_start,
                    value.issued_at,
                    actor_id,
                    None,
                ),
            )
        assert denied.value.sqlstate == "42501"
    assert connection.execute(
        "SELECT has_table_privilege('prm_financial','app.rent_billing_commands','INSERT'),"
        "has_table_privilege('prm_financial','app.rent_billing_commands','SELECT'),"
        "has_function_privilege('prm_financial',"
        "'app.generate_rent_service_invoice(uuid,uuid,text,uuid,text,uuid,uuid,text,date,"
        "timestamp with time zone,uuid,uuid)','EXECUTE')"
    ).fetchone() == (False, True, True)


def test_v1_040_is_forward_only_and_is_the_migration_head(
    connection: Connection[tuple[object, ...]],
) -> None:
    assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
        "20270207_195",
    )
    with pytest.raises(RuntimeError, match="forward-only"):
        command.downgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "-1")


def _processed_final_month_source(
    connection: Connection[tuple[object, ...]],
    period_start: date,
    *,
    governing_reference: str = "BR-LEASE-021",
    end_day: int | None = None,
    late_move_in: bool = False,
    terminate: bool = True,
    legacy_termination: bool = False,
    trash: bool = False,
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    previous_month = (period_start - timedelta(days=1)).replace(day=1)
    move_in = previous_month.replace(day=27 if late_move_in else 1)
    lease_end = period_start.replace(day=end_day) if end_day else period_start + timedelta(days=180)
    source = setup_billing_source(
        connection,
        configure_trash=False,
        configure_internet=False,
        move_in_date=move_in,
        lease_end_date=lease_end,
    )
    human, prop, _, lease, _ = source
    if trash:
        add_service(
            connection,
            actor_id=human,
            property_id=prop,
            lease_id=lease,
            code="TRASH_COLLECTION",
            display_name="Trash Collection",
            first_rate=1_000,
            second_rate=1_000,
            approval_from=move_in,
            approval_through=lease_end,
            applicable_from=move_in,
            applicable_through=lease_end,
            first_rate_effective=move_in,
            second_rate_effective=period_start,
        )
    if terminate:
        version = connection.execute(
            "SELECT version FROM app.leases WHERE id=%s", (lease,)
        ).fetchone()
        assert version is not None
        terminate_test_lease(
            connection,
            property_id=prop,
            actor_id=human,
            lease_id=lease,
            expected_version=int(str(version[0])),
            actual_date=period_start.replace(day=10),
            governing=governing_reference,
            reason="Management processed the documented actual departure",
            basis=(
                TerminationBasis.VOLUNTARY_EARLY
                if governing_reference == "BR-LEASE-021"
                else TerminationBasis.SIGNED_LEASE_OTHER
            ),
            request_digest="b" * 64,
            legacy=legacy_termination,
        )
    connection.commit()
    return source


def _processed_final_month_request(lease: UUID, period_start: date) -> GenerateRentInvoiceCommand:
    prior = period_start - timedelta(days=1)
    return recurring_command(
        lease,
        period_start=period_start,
        issued_at=datetime(prior.year, prior.month, 25, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("period_start", "last_day"),
    (
        (date(2025, 2, 1), 28),
        (date(2024, 2, 1), 29),
        (date(2026, 4, 1), 30),
        (date(2026, 7, 1), 31),
    ),
)
def test_processed_final_month_generates_full_rent_and_valid_services(
    final_month_service_connection: Connection[tuple[object, ...]],
    period_start: date,
    last_day: int,
) -> None:
    connection = final_month_service_connection
    human, prop, _, lease, occupancy = _processed_final_month_source(
        connection, period_start, trash=True
    )
    before = connection.execute(
        "SELECT to_jsonb(l),to_jsonb(o) FROM app.leases l "
        "JOIN app.occupancies o ON o.lease_id=l.id "
        "WHERE l.id=%s AND o.id=%s",
        (lease, occupancy),
    ).fetchone()
    flow = PostgresRentBillingService(financial_database_url(), prop, human)
    request = _processed_final_month_request(lease, period_start)
    result = flow.generate(request, actor=authenticated(human, prop))
    assert result.rent_usd_cents == 80_000
    assert result.service_usd_cents == 1_000
    assert result.total_usd_cents == 81_000
    assert result.period_end == period_start.replace(day=last_day)
    assert result.due_date == period_start.replace(day=5)
    assert result.service_line_count == 1
    assert flow.generate(request, actor=authenticated(human, prop)) == result
    assert connection.execute(
        "SELECT due_date_source,due_date_rule FROM app.invoices WHERE id=%s",
        (result.invoice_id,),
    ).fetchone() == ("BR-RENT-024", "RECURRING_RENT_FIFTH")
    assert (
        connection.execute(
            "SELECT to_jsonb(l),to_jsonb(o) FROM app.leases l "
            "JOIN app.occupancies o ON o.lease_id=l.id "
            "WHERE l.id=%s AND o.id=%s",
            (lease, occupancy),
        ).fetchone()
        == before
    )
    assert connection.execute(
        "SELECT billable_days,calendar_days,contractual_monthly_usd_cents,amount_usd_cents "
        "FROM app.invoice_lines WHERE invoice_id=%s AND category='RENT'",
        (result.invoice_id,),
    ).fetchone() == (last_day, last_day, 80_000, 80_000)
    assert connection.execute(
        "SELECT count(*) FROM app.deposits WHERE lease_id=%s", (lease,)
    ).fetchone() == (0,)
    assert connection.execute(
        "SELECT count(*) FROM app.invoices WHERE lease_id=%s", (lease,)
    ).fetchone() == (1,)


def test_processed_final_month_can_end_after_original_end_date(
    connection: Connection[tuple[object, ...]],
) -> None:
    period = date(2026, 7, 1)
    human, prop, _, lease, _ = _processed_final_month_source(connection, period, end_day=20)
    result = PostgresRentBillingService(financial_database_url(), prop, human).generate(
        _processed_final_month_request(lease, period),
        actor=authenticated(human, prop),
    )
    assert result.period_end == date(2026, 7, 31)
    assert result.rent_usd_cents == result.total_usd_cents == 80_000


@pytest.mark.parametrize(
    ("governing", "end_day", "late_move_in", "target"),
    (
        ("APPROVED-OTHER-TERMINATION", None, False, date(2026, 7, 1)),
        ("BR-LEASE-021", 10, False, date(2026, 7, 1)),
        ("BR-LEASE-021", 9, False, date(2026, 7, 1)),
        ("BR-LEASE-021", None, True, date(2026, 7, 1)),
        ("BR-LEASE-021", None, False, date(2026, 8, 1)),
    ),
)
def test_processed_final_month_rejects_unsupported_or_already_covered_periods(
    connection: Connection[tuple[object, ...]],
    governing: str,
    end_day: int | None,
    late_move_in: bool,
    target: date,
) -> None:
    from contextlib import ExitStack

    from psycopg.conninfo import conninfo_to_dict

    from test_migrations import _temporary_migration_database

    historical_boundary = end_day in (9, 10)
    with ExitStack() as stack:
        financial_url = financial_database_url()
        if historical_boundary:
            temporary = stack.enter_context(
                _temporary_migration_database("old_termination_boundary")
            )
            config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
            command.upgrade(config, "20260914_53")
            connection = stack.enter_context(psycopg.connect(temporary))
            financial_url = make_conninfo(
                financial_url, dbname=conninfo_to_dict(temporary)["dbname"]
            )
        human, prop, _, lease, _ = _processed_final_month_source(
            connection,
            date(2026, 7, 1),
            governing_reference=governing,
            end_day=end_day,
            late_move_in=late_move_in,
            legacy_termination=historical_boundary,
        )
        if historical_boundary:
            command.upgrade(config, "head")
        with pytest.raises(BillingInvalidError):
            PostgresRentBillingService(financial_url, prop, human).generate(
                _processed_final_month_request(lease, target),
                actor=authenticated(human, prop),
            )
        assert connection.execute(
            "SELECT count(*) FROM app.invoices WHERE lease_id=%s", (lease,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.rent_billing_commands WHERE lease_id=%s", (lease,)
        ).fetchone() == (0,)


def test_processed_final_month_concurrent_commands_converge_and_reject_changed_retry(
    connection: Connection[tuple[object, ...]],
) -> None:
    period = date(2026, 7, 1)
    human, prop, _, lease, _ = _processed_final_month_source(connection, period)
    flow = PostgresRentBillingService(financial_database_url(), prop, human)
    actor = authenticated(human, prop)
    requests = [_processed_final_month_request(lease, period) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(flow.generate, value, actor=actor) for value in requests]
        results = [future.result(timeout=10) for future in futures]
    assert results[0] == results[1]
    assert connection.execute(
        "SELECT count(*) FROM app.invoices WHERE lease_id=%s", (lease,)
    ).fetchone() == (1,)
    assert connection.execute(
        "SELECT count(*) FROM app.rent_billing_commands WHERE lease_id=%s", (lease,)
    ).fetchone() == (2,)
    with pytest.raises(BillingIdempotencyKeyReused):
        flow.generate(replace(requests[0], invoice_number="CHANGED-RETRY"), actor=actor)


def test_processed_final_month_preserves_authorized_advance_invoice_and_exact_replay(
    connection: Connection[tuple[object, ...]],
) -> None:
    period = date(2026, 7, 1)
    human, prop, _, lease, _ = _processed_final_month_source(connection, period, terminate=False)
    flow = PostgresRentBillingService(financial_database_url(), prop, human)
    actor = authenticated(human, prop)
    request = _processed_final_month_request(lease, period)
    result = flow.generate(request, actor=actor)
    before = connection.execute(
        "SELECT to_jsonb(i) FROM app.invoices i WHERE id=%s", (result.invoice_id,)
    ).fetchone()
    version = connection.execute("SELECT version FROM app.leases WHERE id=%s", (lease,)).fetchone()
    assert version is not None
    terminate_test_lease(
        connection,
        property_id=prop,
        actor_id=human,
        lease_id=lease,
        expected_version=int(str(version[0])),
        actual_date=period.replace(day=10),
        governing="BR-LEASE-021",
        reason="Approved actual voluntary early termination",
        basis=TerminationBasis.VOLUNTARY_EARLY,
        request_digest="c" * 64,
    )
    connection.commit()
    assert flow.generate(request, actor=actor) == result
    assert flow.generate(_processed_final_month_request(lease, period), actor=actor) == result
    assert (
        connection.execute(
            "SELECT to_jsonb(i) FROM app.invoices i WHERE id=%s", (result.invoice_id,)
        ).fetchone()
        == before
    )
    assert connection.execute(
        "SELECT due_date_source FROM app.invoices WHERE id=%s", (result.invoice_id,)
    ).fetchone() == ("BR-RENT-018",)


def test_processed_final_month_requires_existing_actor_property_and_billing_capability(
    connection: Connection[tuple[object, ...]],
) -> None:
    period = date(2026, 7, 1)
    human, prop, _, lease, _ = _processed_final_month_source(connection, period)
    flow = PostgresRentBillingService(financial_database_url(), prop, human)
    request = _processed_final_month_request(lease, period)
    for actor in (
        AuthenticatedActor(str(human), frozenset()),
        authenticated(human, uuid4()),
        authenticated(uuid4(), prop),
    ):
        with pytest.raises(BillingAuthorizationError):
            flow.generate(request, actor=actor)
    assert connection.execute(
        "SELECT count(*) FROM app.invoices WHERE lease_id=%s", (lease,)
    ).fetchone() == (0,)


@pytest.fixture
def final_month_service_connection(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Connection[tuple[object, ...]]]:
    from psycopg.conninfo import conninfo_to_dict

    from test_migrations import _temporary_migration_database

    assert migrated_database_url
    # V1 has one Property per database. Isolate historical Service calendars by
    # using the existing disposable-database harness, not another Property row.
    with _temporary_migration_database("final_month_service") as temporary:
        command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
        database = conninfo_to_dict(temporary)["dbname"]
        monkeypatch.setenv(
            "FINANCIAL_DATABASE_URL",
            make_conninfo(financial_database_url(), dbname=database),
        )
        with psycopg.connect(temporary) as connection:
            yield connection


def test_processed_final_month_upgrade_preserves_functions_grants_and_business_history(
    migrated_database_url: str,
) -> None:
    from psycopg.conninfo import conninfo_to_dict

    from test_migrations import _temporary_migration_database

    assert migrated_database_url
    signature = (
        "app.generate_rent_service_invoice(uuid,uuid,text,uuid,text,uuid,uuid,text,date,"
        "timestamp with time zone,uuid,uuid)"
    )
    function_query = (
        "SELECT p.oid,pg_catalog.pg_get_functiondef(p.oid),p.proacl::text,p.proowner,"
        "p.prosecdef,p.provolatile,p.proisstrict,p.proparallel,p.proconfig "
        "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='app' AND p.prokind='f' ORDER BY p.oid"
    )
    tables = (
        "leases",
        "occupancies",
        "lease_commands",
        "invoices",
        "invoice_lines",
        "invoice_line_calculation_components",
        "rent_billing_commands",
        "audit_events",
    )
    with _temporary_migration_database("final_month_upgrade") as temporary:
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        command.upgrade(config, "20260911_52")
        period = date(2026, 7, 1)
        with psycopg.connect(temporary) as setup:
            human, prop, _, lease, _ = _processed_final_month_source(
                setup, period, legacy_termination=True
            )
            other, other_prop, _, other_lease, _ = _processed_final_month_source(
                setup,
                period,
                terminate=False,
            )
            target_row = setup.execute(
                "SELECT %s::regprocedure::oid,"
                "'app.validate_invoice_issuance_lines()'::regprocedure::oid",
                (signature,),
            ).fetchone()
            assert target_row is not None
            changed_oids = set(target_row)
        database = conninfo_to_dict(temporary)["dbname"]
        url = make_conninfo(financial_database_url(), dbname=database)
        flow = PostgresRentBillingService(url, prop, human)
        request = _processed_final_month_request(lease, period)
        with pytest.raises(BillingInvalidError):
            flow.generate(request, actor=authenticated(human, prop))
        old_flow = PostgresRentBillingService(url, other_prop, other)
        old_request = _processed_final_month_request(other_lease, period)
        old_result = old_flow.generate(old_request, actor=authenticated(other, other_prop))
        with psycopg.connect(temporary) as check:
            functions_before = {row[0]: row[1:] for row in check.execute(function_query)}
            history_before = {
                table: check.execute(
                    psycopg.sql.SQL(
                        "SELECT to_jsonb(t) FROM app.{} t ORDER BY to_jsonb(t)::text"
                    ).format(psycopg.sql.Identifier(table))
                ).fetchall()
                for table in tables
            }
        command.upgrade(config, "20260914_53")
        with psycopg.connect(temporary) as check:
            functions_after = {row[0]: row[1:] for row in check.execute(function_query)}
            assert functions_before.keys() == functions_after.keys()
            assert {
                oid for oid in functions_before if functions_before[oid] != functions_after[oid]
            } == changed_oids
            for oid in changed_oids:
                assert functions_before[oid][1:] == functions_after[oid][1:]
            for table in tables:
                assert (
                    check.execute(
                        psycopg.sql.SQL(
                            "SELECT to_jsonb(t) FROM app.{} t ORDER BY to_jsonb(t)::text"
                        ).format(psycopg.sql.Identifier(table))
                    ).fetchall()
                    == history_before[table]
                )
        assert old_flow.generate(old_request, actor=authenticated(other, other_prop)) == old_result
        result = flow.generate(request, actor=authenticated(human, prop))
        assert result.period_end == date(2026, 7, 31)
        assert result.rent_usd_cents == 80_000
        assert flow.generate(request, actor=authenticated(human, prop)) == result
