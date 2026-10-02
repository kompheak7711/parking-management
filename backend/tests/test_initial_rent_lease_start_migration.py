"""Initial Rent follows the signed Lease Start Date with a proposed or authorized Due Date."""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.billing import (
    BillingIdempotencyKeyReused,
    BillingInvalidError,
    PostgresRentBillingService,
    SetInitialRentDueDateCommand,
    prorated_monthly_usd_cents,
    set_initial_rent_due_date,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.invoice import (
    InvoiceAuthorizationError,
    InvoiceConflictError,
    PostgresInvoiceService,
)
from test_billing_service_migration import (
    authenticated,
    financial_database_url,
    initial_command,
    recurring_command,
)
from test_billing_service_migration import migrated_database_url as migrated_database_url
from test_invoice_migration import runtime_database_url
from test_lease_migration import create_draft, setup_sources, sign_lease


def signed_lease(url: str, start: date, *, arrival: date | None = None) -> tuple[UUID, UUID, UUID]:
    with psycopg.connect(url) as connection:
        actor_id, property_id, unit_id, customer_id, _ = setup_sources(connection)
        lease_id = create_draft(
            connection,
            actor_id=actor_id,
            unit_id=unit_id,
            primary_tenant_id=customer_id,
            start_date=start,
            end_date=date(start.year + 1, 6, 30),
        )
        sign_lease(connection, lease_id, actor_id)
        if arrival is not None:
            connection.execute(
                "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,"
                "created_by,updated_by) VALUES (%s,%s,%s,%s,%s,%s)",
                (uuid4(), lease_id, customer_id, arrival, actor_id, actor_id),
            )
    return actor_id, property_id, lease_id


def issued_on(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 1, tzinfo=UTC)


def invoice_row(url: str, invoice_id: UUID) -> tuple[Any, ...]:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT due_date,due_date_rule,source_occupancy_id,due_date_override_reason,"
            "due_date_set_by,billing_period_start,billing_period_end FROM app.invoices WHERE id=%s",
            (invoice_id,),
        ).fetchone()
    assert row is not None
    return row


def test_initial_rent_uses_lease_start_not_arrival_and_proposes_start_plus_five(
    migrated_database_url: str,
) -> None:
    start = date(2026, 9, 20)
    actor, prop, lease = signed_lease(migrated_database_url, start, arrival=date(2026, 9, 25))
    service = PostgresRentBillingService(financial_database_url(), prop, actor)
    result = service.generate(
        initial_command(lease, uuid4(), period_start=start, issued_at=issued_on(date(2026, 9, 15))),
        actor=authenticated(actor, prop),
    )
    assert result.invoice_date == date(2026, 9, 15)
    assert result.due_date == date(2026, 9, 25)
    assert result.period_start == start and result.period_end == date(2026, 9, 30)
    assert result.rent_usd_cents == prorated_monthly_usd_cents(80000, start, date(2026, 9, 30))
    due, rule, occupancy, reason, set_by, period_start, _ = invoice_row(
        migrated_database_url, result.invoice_id
    )
    assert (due, rule, occupancy, reason, set_by) == (
        date(2026, 9, 25),
        "INITIAL_RENT_LEASE_START_PLUS_FIVE",
        None,
        None,
        None,
    )
    assert period_start == start


def test_authorized_due_date_is_recorded_before_issue_and_fixed_afterwards(
    migrated_database_url: str,
) -> None:
    start = date(2026, 7, 10)
    actor, prop, lease = signed_lease(migrated_database_url, start)
    service = PostgresRentBillingService(financial_database_url(), prop, actor)
    who = authenticated(actor, prop)
    override = SetInitialRentDueDateCommand(uuid4(), lease, date(2026, 7, 20), "Customer payroll")
    recorded = set_initial_rent_due_date(service, override, actor=who)
    assert recorded["due_date"] == "2026-07-20" and recorded["proposed_due_date"] == "2026-07-15"
    assert set_initial_rent_due_date(service, override, actor=who) == recorded
    with pytest.raises(BillingIdempotencyKeyReused):
        set_initial_rent_due_date(
            service,
            SetInitialRentDueDateCommand(
                override.override_id, lease, date(2026, 7, 21), "Customer payroll"
            ),
            actor=who,
        )
    result = service.generate(
        initial_command(lease, uuid4(), period_start=start, issued_at=issued_on(date(2026, 7, 1))),
        actor=who,
    )
    assert result.due_date == date(2026, 7, 20)
    due, _, _, reason, set_by, _, _ = invoice_row(migrated_database_url, result.invoice_id)
    assert (due, reason, set_by) == (date(2026, 7, 20), "Customer payroll", actor)
    with pytest.raises(BillingInvalidError):
        set_initial_rent_due_date(
            service,
            SetInitialRentDueDateCommand(uuid4(), lease, date(2026, 7, 22), "Later change"),
            actor=who,
        )
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute(
                "UPDATE app.invoices SET due_date=%s WHERE id=%s",
                (date(2026, 7, 30), result.invoice_id),
            )
    with psycopg.connect(migrated_database_url) as connection:
        audit = connection.execute(
            "SELECT count(*) FROM app.audit_events "
            "WHERE action='invoice.initial_rent_due_date.set' AND entity_id=%s",
            (override.override_id,),
        ).fetchone()
    assert audit == (1,)


def test_proposed_due_date_before_issue_requires_an_authorized_due_date(
    migrated_database_url: str,
) -> None:
    start = date(2026, 7, 10)
    actor, prop, lease = signed_lease(migrated_database_url, start)
    service = PostgresRentBillingService(financial_database_url(), prop, actor)
    who = authenticated(actor, prop)
    late = issued_on(date(2026, 7, 20))
    with pytest.raises(BillingInvalidError):
        service.generate(
            initial_command(lease, uuid4(), period_start=start, issued_at=late), actor=who
        )
    set_initial_rent_due_date(
        service,
        SetInitialRentDueDateCommand(uuid4(), lease, date(2026, 7, 25), "Issued late"),
        actor=who,
    )
    result = service.generate(
        initial_command(lease, uuid4(), period_start=start, issued_at=late), actor=who
    )
    assert result.due_date == date(2026, 7, 25)


def test_initial_rent_rejects_an_occupancy_source(migrated_database_url: str) -> None:
    start = date(2026, 7, 10)
    actor, prop, lease = signed_lease(migrated_database_url, start, arrival=start)
    with pytest.raises(ValueError, match="source_occupancy_id"):
        initial_command(lease, uuid4(), source_occupancy_id=uuid4())
    command = initial_command(lease, uuid4(), period_start=start, issued_at=issued_on(start))
    with psycopg.connect(migrated_database_url) as owner:
        occupancy = owner.execute(
            "SELECT id FROM app.occupancies WHERE lease_id=%s", (lease,)
        ).fetchone()
    assert occupancy is not None
    with psycopg.connect(financial_database_url()) as financial:
        with pytest.raises(psycopg.Error) as rejected:
            financial.execute(
                "SELECT app.generate_rent_service_invoice(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    prop,
                    command.idempotency_key,
                    "a" * 64,
                    command.invoice_id,
                    command.invoice_number,
                    lease,
                    occupancy[0],
                    "INITIAL",
                    start,
                    command.issued_at,
                    actor,
                    None,
                ),
            )
    assert rejected.value.sqlstate == "22023"


def test_recurring_rent_follows_lease_start_coverage_without_an_occupancy(
    migrated_database_url: str,
) -> None:
    start = date(2026, 7, 10)
    actor, prop, lease = signed_lease(migrated_database_url, start)
    service = PostgresRentBillingService(financial_database_url(), prop, actor)
    who = authenticated(actor, prop)
    service.generate(
        initial_command(lease, uuid4(), period_start=start, issued_at=issued_on(date(2026, 7, 1))),
        actor=who,
    )
    august = service.generate(
        recurring_command(
            lease,
            period_start=date(2026, 8, 1),
            issued_at=datetime(2026, 7, 24, 17, 0, 1, tzinfo=UTC),
        ),
        actor=who,
    )
    assert august.due_date == date(2026, 8, 5)
    with pytest.raises(BillingInvalidError):
        service.generate(
            recurring_command(
                lease,
                period_start=date(2026, 7, 1),
                issued_at=datetime(2026, 6, 24, 17, 0, 1, tzinfo=UTC),
            ),
            actor=who,
        )


def test_issued_due_date_and_override_shape_constraints(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        names = {
            str(row[0])
            for row in connection.execute(
                "SELECT conname FROM pg_catalog.pg_constraint "
                "WHERE conrelid='app.invoices'::regclass AND contype='c'"
            )
        }
        nullable = connection.execute(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema='app' AND table_name='invoices' AND column_name='due_date'"
        ).fetchone()
    assert {"invoices_due_date_issued", "invoices_due_date_override_shape"} <= names
    assert nullable == ("YES",)


def test_initial_rent_lease_start_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261001_64")
    assert revision is not None and revision.down_revision == "20260917_63"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()


def test_initial_rent_override_through_the_invoice_service_needs_invoices_issue(
    migrated_database_url: str,
) -> None:
    start = date(2026, 7, 11)
    actor, prop, lease = signed_lease(migrated_database_url, start)
    service = PostgresInvoiceService(runtime_database_url(), financial_database_url())

    def holder(capability: str) -> AuthenticatedActor:
        return AuthenticatedActor(
            str(actor), frozenset({CapabilityGrant(capability, frozenset({str(prop)}))})
        )

    override = SetInitialRentDueDateCommand(uuid4(), lease, date(2026, 7, 21), "Customer payroll")
    with pytest.raises(InvoiceAuthorizationError):
        service.set_initial_rent_due_date(prop, override, actor=holder("invoices.create"))
    recorded = service.set_initial_rent_due_date(prop, override, actor=holder("invoices.issue"))
    assert recorded["due_date"] == "2026-07-21" and recorded["proposed_due_date"] == "2026-07-16"
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT authorization_reference,authorization_evidence->>'capability' "
            "FROM app.audit_events WHERE action='invoice.initial_rent_due_date.set' "
            "AND entity_id=%s",
            (override.override_id,),
        ).fetchone() == ("invoices.issue", "invoices.issue")
    assert (
        service.set_initial_rent_due_date(prop, override, actor=holder("invoices.issue"))
        == recorded
    )
    with pytest.raises(InvoiceConflictError):
        service.set_initial_rent_due_date(
            prop,
            SetInitialRentDueDateCommand(
                override.override_id, lease, date(2026, 7, 22), "Customer payroll"
            ),
            actor=holder("invoices.issue"),
        )
