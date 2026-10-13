"""BR-LEASE-031: a Lease End Date is the last day of a calendar month (DL-069, V1-056 slice 1)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import Connection

from property_rental.billing import BillingInvalidError, PostgresRentBillingService
from property_rental.lease import (
    LEASE_DRAFT_CAPABILITY,
    LEASE_SIGN_CAPABILITY,
    LeaseCommandInvalidError,
    LeaseSignCommand,
    LeaseUpdateDraftCommand,
    PostgresLeaseService,
)
from test_billing_service_migration import (
    authenticated,
    financial_database_url,
    initial_command,
    recurring_command,
    setup_billing_source,
)
from test_lease_lifecycle_migration import (
    actor,
    database_now,
    draft_command,
    migrated_database_url,  # noqa: F401
    runtime_database_url,
    setup_sources,
)
from test_lease_migration import create_draft
from test_migrations import _temporary_migration_database

MONTH_END_FUNCTIONS = {
    "app.create_lease_draft(uuid,uuid,text,uuid,uuid,uuid,uuid,uuid,date,date,bigint,uuid,text,uuid)",
    "app.create_lease_draft_with_terms(uuid,uuid,text,uuid,uuid,uuid,uuid,uuid,date,date,bigint,"
    "uuid,jsonb,jsonb,jsonb,jsonb,uuid,text,uuid)",
    "app.update_lease_draft(uuid,uuid,text,uuid,uuid,integer,date,date,bigint,text,text,uuid)",
    "app.sign_lease(uuid,uuid,text,uuid,uuid,integer,timestamp with time zone,text,uuid)",
}


MONTH_END_MESSAGE = "Lease End Date must be the last day of a calendar month"


def _cause(failure: pytest.ExceptionInfo[Exception]) -> str:
    cause = failure.value.__cause__
    assert isinstance(cause, psycopg.Error)
    return str(cause.diag.message_primary)


@pytest.fixture
def connection(
    migrated_database_url: str,  # noqa: F811
) -> Iterator[Connection[tuple[object, ...]]]:
    with psycopg.connect(migrated_database_url) as database_connection:
        yield database_connection
        database_connection.rollback()


def _sources(url: str) -> tuple[UUID, UUID, UUID, UUID]:
    with psycopg.connect(url) as setup:
        actor_id, property_id, unit_id, tenant_id, _ = setup_sources(setup)
        setup.commit()
    return actor_id, property_id, unit_id, tenant_id


def _lease_count(url: str, lease_id: UUID) -> int:
    with psycopg.connect(url) as check:
        row = check.execute("SELECT count(*) FROM app.leases WHERE id=%s", (lease_id,)).fetchone()
    assert row is not None
    return int(cast(int, row[0]))


def test_lease_draft_and_update_accept_only_a_month_end_end_date(
    migrated_database_url: str,  # noqa: F811
) -> None:
    actor_id, property_id, unit_id, tenant_id = _sources(migrated_database_url)
    who = actor(actor_id, property_id, LEASE_DRAFT_CAPABILITY)
    service = PostgresLeaseService(runtime_database_url(), property_id, actor_id)

    for end_date in (date(2027, 5, 30), date(2028, 2, 28), date(2027, 6, 1)):
        rejected = draft_command(
            unit_id, tenant_id, start_date=date(2026, 4, 10), end_date=end_date
        )
        with pytest.raises(LeaseCommandInvalidError) as failure:
            service.draft(rejected, actor=who)
        assert _cause(failure) == MONTH_END_MESSAGE
        with pytest.raises(LeaseCommandInvalidError) as failure:
            service.draft_with_terms(rejected, actor=who)
        assert _cause(failure) == MONTH_END_MESSAGE
        assert _lease_count(migrated_database_url, rejected.lease_id) == 0

    accepted = {}
    for end_date in (date(2027, 5, 31), date(2028, 2, 29), date(2027, 2, 28)):
        command = draft_command(unit_id, tenant_id, start_date=date(2026, 4, 10), end_date=end_date)
        accepted[end_date] = service.draft(command, actor=who)
        assert accepted[end_date].end_date == end_date
    with_terms = draft_command(
        unit_id, tenant_id, start_date=date(2026, 4, 10), end_date=date(2027, 4, 30)
    )
    assert service.draft_with_terms(with_terms, actor=who).end_date == date(2027, 4, 30)
    open_terms = replace(draft_command(unit_id, tenant_id), start_date=None, end_date=None)
    assert service.draft(open_terms, actor=who).end_date is None

    lease = accepted[date(2027, 5, 31)]

    def update(end_date: date, version: int) -> LeaseUpdateDraftCommand:
        return LeaseUpdateDraftCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=lease.lease_id,
            expected_version=version,
            start_date=date(2026, 4, 10),
            end_date=end_date,
            monthly_rent_usd_cents=80_000,
            reason="Authorized End Date correction",
            authorization_reference=LEASE_DRAFT_CAPABILITY,
        )

    with pytest.raises(LeaseCommandInvalidError) as failure:
        service.update_draft(update(date(2027, 6, 29), lease.version), actor=who)
    assert _cause(failure) == MONTH_END_MESSAGE
    updated = service.update_draft(update(date(2027, 6, 30), lease.version), actor=who)
    assert updated.end_date == date(2027, 6, 30)
    assert updated.version == lease.version + 1


def test_signing_rejects_a_stored_end_date_that_is_not_a_month_end(
    migrated_database_url: str,  # noqa: F811
) -> None:
    actor_id, property_id, unit_id, tenant_id = _sources(migrated_database_url)
    with psycopg.connect(migrated_database_url) as setup:
        # No table constraint: a row written before the rule keeps its End Date.
        legacy = create_draft(
            setup,
            actor_id=actor_id,
            unit_id=unit_id,
            primary_tenant_id=tenant_id,
            start_date=date(2026, 7, 16),
            end_date=date(2027, 7, 15),
        )
        setup.commit()
    who = actor(actor_id, property_id, LEASE_SIGN_CAPABILITY)
    service = PostgresLeaseService(runtime_database_url(), property_id, actor_id)

    def sign(lease_id: UUID) -> LeaseSignCommand:
        return LeaseSignCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=lease_id,
            expected_version=1,
            signed_at=database_now(),
            reason="Sign the complete Lease",
            authorization_reference=LEASE_SIGN_CAPABILITY,
        )

    with pytest.raises(LeaseCommandInvalidError) as failure:
        service.sign(sign(legacy), actor=who)
    assert _cause(failure) == MONTH_END_MESSAGE
    with psycopg.connect(migrated_database_url) as check:
        assert check.execute(
            "SELECT status,version,end_date FROM app.leases WHERE id=%s", (legacy,)
        ).fetchone() == ("DRAFTED", 1, date(2027, 7, 15))
        assert check.execute(
            "SELECT count(*) FROM app.lease_commands WHERE lease_id=%s AND action='lease.sign'",
            (legacy,),
        ).fetchone() == (0,)

    actor_id, property_id, unit_id, tenant_id = _sources(migrated_database_url)
    with psycopg.connect(migrated_database_url) as setup:
        month_end = create_draft(
            setup,
            actor_id=actor_id,
            unit_id=unit_id,
            primary_tenant_id=tenant_id,
            start_date=date(2026, 7, 16),
            end_date=date(2027, 7, 31),
        )
        setup.commit()
    who = actor(actor_id, property_id, LEASE_SIGN_CAPABILITY)
    service = PostgresLeaseService(runtime_database_url(), property_id, actor_id)
    signed = service.sign(sign(month_end), actor=who)
    assert signed.end_date == date(2027, 7, 31)
    assert signed.version == 2


def test_no_rent_invoice_is_generated_for_a_month_after_the_end_date(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _, ended_lease, ended_occupancy = setup_billing_source(
        connection,
        configure_trash=False,
        configure_internet=False,
        lease_end_date=date(2026, 8, 31),
    )
    service = PostgresRentBillingService(financial_database_url(), property_id, actor_id)
    initial = service.generate(
        initial_command(ended_lease, ended_occupancy), actor=authenticated(actor_id, property_id)
    )
    assert initial.period_end == date(2026, 8, 31)
    with pytest.raises(BillingInvalidError) as failure:
        service.generate(
            recurring_command(ended_lease, period_start=date(2026, 9, 1)),
            actor=authenticated(actor_id, property_id),
        )
    assert _cause(failure) == "Rent billing period is outside contractual Lease coverage"
    assert connection.execute(
        "SELECT rent_billing_kind FROM app.invoices WHERE lease_id=%s", (ended_lease,)
    ).fetchall() == [("INITIAL",)]

    actor_id, property_id, _, covered_lease, covered_occupancy = setup_billing_source(
        connection,
        configure_trash=False,
        configure_internet=False,
        lease_end_date=date(2026, 9, 30),
    )
    service = PostgresRentBillingService(financial_database_url(), property_id, actor_id)
    service.generate(
        initial_command(covered_lease, covered_occupancy),
        actor=authenticated(actor_id, property_id),
    )
    covered = service.generate(
        recurring_command(covered_lease, period_start=date(2026, 9, 1)),
        actor=authenticated(actor_id, property_id),
    )
    assert covered.period_end == date(2026, 9, 30)


def _catalog(url: str) -> tuple[dict[str, tuple[object, ...]], set[tuple[object, ...]]]:
    with psycopg.connect(url) as connection:
        functions = {
            str(row[0]): cast(tuple[object, ...], row[1:])
            for row in connection.execute(
                "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                "p.proacl::text,p.prosecdef FROM pg_catalog.pg_proc p "
                "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname='app' AND p.prokind='f'"
            ).fetchall()
        }
        relations = {
            cast(tuple[object, ...], row)
            for row in connection.execute(
                "SELECT c.oid::regclass::text,c.relacl::text,con.conname,"
                "pg_catalog.pg_get_constraintdef(con.oid) FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "LEFT JOIN pg_catalog.pg_constraint con ON con.conrelid=c.oid "
                "WHERE n.nspname='app' AND c.relkind IN ('r','v','m','p')"
            ).fetchall()
        }
    return functions, relations


def test_month_end_migration_changes_only_the_four_functions_and_is_forward_only(
    migrated_database_url: str,  # noqa: F811
) -> None:
    assert migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261011_76")
    assert revision is not None and revision.down_revision == "20261010_75"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database("lease_end_month_end") as temporary:
        alembic_command.upgrade(config, "20261010_75")
        before_functions, before_relations = _catalog(temporary)
        alembic_command.upgrade(config, "20261011_76")
        after_functions, after_relations = _catalog(temporary)
    assert after_relations == before_relations
    assert set(after_functions) == set(before_functions)
    changed = {name for name in before_functions if after_functions[name] != before_functions[name]}
    assert changed == MONTH_END_FUNCTIONS
    for name in MONTH_END_FUNCTIONS:
        before_definition, before_acl, before_definer = before_functions[name]
        after_definition, after_acl, after_definer = after_functions[name]
        assert (after_acl, after_definer) == (before_acl, before_definer)
        text = str(after_definition)
        check = text.index("Lease End Date must be the last day of a calendar month")
        replay = text.find("IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;")
        assert replay != -1 and replay < check
        assert str(before_definition).count("last day of a calendar month") == 0
