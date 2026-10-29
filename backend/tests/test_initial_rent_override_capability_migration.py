"""The override audit names the capability it was authorized under; no earlier record changes."""

from datetime import date
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.billing import PostgresRentBillingService, SetInitialRentDueDateCommand
from property_rental.billing import set_initial_rent_due_date as billing_set_due_date
from property_rental.invoice import PostgresInvoiceService
from test_billing_service_migration import authenticated, financial_database_url
from test_initial_rent_lease_start_migration import signed_lease
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_invoice_migration import runtime_database_url
from test_migrations import _temporary_migration_database
from test_reservation_migration import create_reservation, setup_reservation_sources

AUDIT = (
    "SELECT authorization_reference,authorization_evidence->>'capability' "
    "FROM app.audit_events WHERE action='invoice.initial_rent_due_date.set' AND entity_id=%s"
)


def test_each_path_records_the_capability_it_was_authorized_under(
    migrated_database_url: str,
) -> None:
    actor, prop, lease = signed_lease(migrated_database_url, date(2026, 7, 12))
    human = SetInitialRentDueDateCommand(uuid4(), lease, date(2026, 7, 22), "Customer payroll")
    PostgresInvoiceService(
        runtime_database_url(), financial_database_url()
    ).set_initial_rent_due_date(
        prop,
        human,
        actor=authenticated_with(actor, prop, "invoices.issue"),
    )
    billing = SetInitialRentDueDateCommand(uuid4(), lease, date(2026, 7, 23), "Service later date")
    billing_set_due_date(
        PostgresRentBillingService(financial_database_url(), prop, actor),
        billing,
        actor=authenticated(actor, prop),
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(AUDIT, (human.override_id,)).fetchone() == (
            "invoices.issue",
            "invoices.issue",
        )
        assert connection.execute(AUDIT, (billing.override_id,)).fetchone() == (
            "billing.generate",
            "billing.generate",
        )


def authenticated_with(actor: Any, prop: Any, capability: str) -> Any:
    from property_rental.identity import AuthenticatedActor, CapabilityGrant

    return AuthenticatedActor(
        str(actor), frozenset({CapabilityGrant(capability, frozenset({str(prop)}))})
    )


def test_an_unknown_capability_is_refused_and_leaves_nothing_behind(
    migrated_database_url: str,
) -> None:
    actor, prop, lease = signed_lease(migrated_database_url, date(2026, 7, 13))
    override = uuid4()
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error) as refused:
            connection.execute(
                "SELECT app.set_initial_rent_due_date(%s,%s,%s,%s,%s,%s,%s)",
                (prop, lease, actor, override, date(2026, 7, 23), "Payroll", "invoices.void"),
            )
    assert refused.value.sqlstate == "22023"
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(AUDIT, (override,)).fetchone() is None


def test_runtime_role_cannot_call_the_old_sign_function_directly(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT has_function_privilege('prm_runtime',"
            "'app.sign_lease(uuid,uuid,text,uuid,uuid,integer,timestamptz,text,uuid)','EXECUTE'),"
            "has_function_privilege('prm_runtime',"
            "'app.sign_lease_with_reservation(uuid,uuid,text,uuid,uuid,integer,timestamptz,"
            "text,uuid,uuid)','EXECUTE')"
        ).fetchone() == (False, True)


def test_upgrade_keeps_every_earlier_record(migrated_database_url: str) -> None:
    assert migrated_database_url
    with _temporary_migration_database("override_capability") as temporary:
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        alembic_command.upgrade(config, "20261008_73")
        with psycopg.connect(temporary) as connection:
            actor_id, prop, unit, customer = setup_reservation_sources(connection)
            create_reservation(
                connection,
                actor_id=actor_id,
                property_id=prop,
                unit_id=unit,
                customer_id=customer,
                expiration_days=10,
            )
        # V1-058 migration 227 adds the Unit setup columns (NULL, or the Floor item linked from
        # the Floor text) and audits the Unit setup items it creates; V1-061 migration 251 adds the
        # default Rent (NULL); nothing earlier changes.
        units_row = (
            "to_jsonb(t)-ARRAY['floor_item_id','size_square_metres','bedrooms','bathrooms',"
            "'view_item_id','kitchen_item_id','notes',"
            "'default_monthly_rent_usd_cents']"
        )
        tables = {
            "audit_events": ("to_jsonb(t)", "WHERE t.entity_type <> 'unit_setup_item'"),
            "reservations": ("to_jsonb(t)", ""),
            "deposits": ("to_jsonb(t)", ""),
            "leases": ("to_jsonb(t)", ""),
            "units": (units_row, ""),
        }

        def snapshot() -> list[Any]:
            with psycopg.connect(temporary) as connection:
                return [
                    connection.execute(
                        f"SELECT COALESCE(jsonb_agg({row} ORDER BY t.id),'[]'::jsonb) "
                        f"FROM app.{table} t {where}"
                    ).fetchone()
                    for table, (row, where) in tables.items()
                ]

        before = snapshot()
        alembic_command.upgrade(config, "head")
        assert snapshot() == before


def test_override_capability_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261009_74")
    assert revision is not None and revision.down_revision == "20261008_73"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
