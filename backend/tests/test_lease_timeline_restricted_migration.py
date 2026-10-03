"""Restricted Lease timeline events behind the actor's existing read grants (DL-067, 9f-5)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.billing import (
    PostgresRentBillingService,
    SetInitialRentDueDateCommand,
    set_initial_rent_due_date,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease_api import PostgresLeaseResourceFlow
from property_rental.lease_enforcement import NonpaymentEventKind, RecordLeaseWarning
from test_billing_service_migration import authenticated, financial_database_url
from test_initial_rent_lease_start_migration import signed_lease
from test_invoice_migration import runtime_database_url
from test_lease_enforcement_migration import event, opened, staff
from test_lease_enforcement_migration import service as enforcement
from test_migrations import _temporary_migration_database
from test_payment_api_migration import api
from test_reservation_migration import migrated_database_url  # noqa: F401

FUNCTION = (
    "app.lease_timeline_restricted(uuid,uuid,uuid[],uuid[],timestamp with time zone,uuid,integer)"
)
OVERRIDE_KIND = "lease.initial_rent_due_date_override"
NONPAYMENT_KIND = "lease.rent_nonpayment_twenty_day_warning"
RESTRICTED_KINDS = {OVERRIDE_KIND, NONPAYMENT_KIND}


def reader(
    human: UUID, prop: UUID, *caps: str, elsewhere: tuple[str, ...] = ()
) -> AuthenticatedActor:
    other = str(uuid4())
    return AuthenticatedActor(
        str(human),
        frozenset(
            {CapabilityGrant(cap, frozenset({str(prop)})) for cap in ("leases.read", *caps)}
            | {CapabilityGrant(cap, frozenset({other})) for cap in elsewhere}
        ),
    )


def nonpayment_lease(url: str) -> tuple[UUID, UUID, UUID]:
    human, prop, _, lease, _, _, case = opened(url)
    event(prop, lease, case, human, NonpaymentEventKind.TWENTY_DAY_WARNING)
    return human, prop, lease


def override_lease(url: str) -> tuple[UUID, UUID, UUID]:
    human, prop, lease = signed_lease(url, date(2026, 7, 10))
    set_initial_rent_due_date(
        PostgresRentBillingService(financial_database_url(), prop, human),
        SetInitialRentDueDateCommand(uuid4(), lease, date(2026, 7, 20), "Customer payroll"),
        actor=authenticated(human, prop),
    )
    return human, prop, lease


def mixed_lease(url: str) -> tuple[UUID, UUID, UUID]:
    """Three ordinary warnings plus one hidden Rent-nonpayment event and one hidden override."""
    human, prop, _, lease, _, _, case = opened(url)
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT start_date FROM app.leases WHERE id=%s", (lease,)
        ).fetchone()
    assert row is not None and isinstance(row[0], date)
    start = row[0]
    for sequence in (1, 2, 3):
        enforcement().record_warning(
            prop,
            lease,
            RecordLeaseWarning(
                uuid4(),
                sequence,
                start,
                start + timedelta(days=sequence),
                "Documented violation",
                "Signed Lease clause",
                "Letter delivered",
                "Document history",
            ),
            actor=staff(human, prop),
            request_id=f"warning-{sequence}",
        )
    event(prop, lease, case, human, NonpaymentEventKind.TWENTY_DAY_WARNING)
    set_initial_rent_due_date(
        PostgresRentBillingService(financial_database_url(), prop, human),
        SetInitialRentDueDateCommand(
            uuid4(), lease, start + timedelta(days=10), "Customer payroll"
        ),
        actor=authenticated(human, prop),
    )
    return human, prop, lease


def pages(who: AuthenticatedActor, lease: UUID) -> list[tuple[list[dict[str, object]], object]]:
    client = api(who)
    result: list[tuple[list[dict[str, object]], object]] = []
    params: dict[str, str] = {"limit": "1"}
    while True:
        reply = client.get(f"/api/v1/leases/{lease}/timeline", params=params)
        assert reply.status_code == 200, reply.text
        body = reply.json()
        result.append((body["data"], body["page"]["next_cursor"]))
        if body["page"]["next_cursor"] is None:
            return result
        params = {"limit": "1", "cursor": str(body["page"]["next_cursor"])}


def todays_pages(lease: UUID) -> list[tuple[list[dict[str, object]], object]]:
    # The pre-9f-5 read: the same flow with no restricted visibility.
    flow = PostgresLeaseResourceFlow(runtime_database_url())
    result: list[tuple[list[dict[str, object]], object]] = []
    cursor: str | None = None
    while True:
        page = flow.timeline(lease, limit=1, cursor=cursor)
        items: list[dict[str, object]] = [
            {
                "event_id": str(item.event_id),
                "event_kind": item.event_kind,
                "occurred_at": item.occurred_at.isoformat(),
                "reason": item.reason,
                "actor_id": str(item.actor_id),
                "source_reference": item.source_reference,
                "source_href": item.source_href,
            }
            for item in page.items
        ]
        result.append((items, page.next_cursor))
        if page.next_cursor is None:
            return result
        cursor = page.next_cursor


def normalized(
    value: list[tuple[list[dict[str, object]], object]],
) -> list[tuple[list[dict[str, object]], object]]:
    return [
        (
            [
                {
                    **item,
                    "occurred_at": datetime.fromisoformat(str(item["occurred_at"])).isoformat(),
                }
                for item in items
            ],
            cursor,
        )
        for items, cursor in value
    ]


def restricted_rows(
    lease: UUID, human: UUID, invoice: list[UUID] | None, nonpayment: list[UUID] | None
) -> list[tuple[object, ...]]:
    with psycopg.connect(runtime_database_url()) as connection:
        return connection.execute(
            "SELECT event_kind FROM app.lease_timeline_restricted("
            "%s,%s,%s::uuid[],%s::uuid[],NULL,NULL,101)",
            (human, lease, invoice, nonpayment),
        ).fetchall()


def test_lease_timeline_restricted_function_with_empty_lists_returns_no_events(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, unpaid = nonpayment_lease(migrated_database_url)
    owner, override_prop, overridden = override_lease(migrated_database_url)
    for lease, who in ((unpaid, human), (overridden, owner)):
        assert restricted_rows(lease, who, [], []) == []
        assert restricted_rows(lease, who, None, None) == []
        assert restricted_rows(lease, who, [uuid4()], [uuid4()]) == []
    assert restricted_rows(unpaid, human, [prop], []) == []
    assert restricted_rows(unpaid, human, [], [prop]) == [(NONPAYMENT_KIND,)]
    assert restricted_rows(overridden, owner, [], [override_prop]) == []
    assert restricted_rows(overridden, owner, [override_prop], []) == [(OVERRIDE_KIND,)]


def test_lease_timeline_leases_read_only_user_sees_todays_timeline_pages_and_cursor(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, lease = mixed_lease(migrated_database_url)
    # Both hidden events exist for this Lease; a reader with both grants sees them.
    full = reader(human, prop, "invoices.read", "rent_nonpayment.read")
    assert RESTRICTED_KINDS <= {
        str(item["event_kind"]) for items, _ in pages(full, lease) for item in items
    }
    expected = todays_pages(lease)
    # Page size 1: three ordinary warnings give three pages and two cursors.
    assert len(expected) == 3
    assert [cursor is None for _, cursor in expected] == [False, False, True]
    assert all(
        item["event_kind"] == "lease.violation_warning" for items, _ in expected for item in items
    )
    today = PostgresLeaseResourceFlow(runtime_database_url()).get(lease)
    for who in (
        reader(human, prop),
        reader(human, prop, elsewhere=("invoices.read", "rent_nonpayment.read")),
    ):
        seen = pages(who, lease)
        assert normalized(seen) == normalized(expected)
        assert all(
            item["event_kind"] not in RESTRICTED_KINDS for items, _ in seen for item in items
        )
        detail = api(who).get(f"/api/v1/leases/{lease}")
        assert detail.status_code == 200, detail.text
        data = detail.json()["data"]
        assert [item["event_id"] for item in data["timeline"]] == [
            str(item.event_id) for item in today.timeline
        ]
        assert len(data["timeline"]) == 3
        assert data["timeline_next_cursor"] == today.timeline_next_cursor


def test_lease_timeline_shows_each_restricted_kind_only_to_its_read_capability(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, unpaid = nonpayment_lease(migrated_database_url)
    owner, override_prop, overridden = override_lease(migrated_database_url)

    def kinds(who: AuthenticatedActor, lease: UUID) -> set[str]:
        reply = api(who).get(f"/api/v1/leases/{lease}/timeline", params={"limit": "100"})
        assert reply.status_code == 200, reply.text
        return {str(item["event_kind"]) for item in reply.json()["data"]}

    assert NONPAYMENT_KIND in kinds(reader(human, prop, "rent_nonpayment.read"), unpaid)
    assert NONPAYMENT_KIND not in kinds(reader(human, prop, "invoices.read"), unpaid)
    assert OVERRIDE_KIND in kinds(reader(owner, override_prop, "invoices.read"), overridden)
    assert OVERRIDE_KIND not in kinds(
        reader(owner, override_prop, "rent_nonpayment.read"), overridden
    )
    detail = api(reader(owner, override_prop, "invoices.read")).get(f"/api/v1/leases/{overridden}")
    override = next(
        item for item in detail.json()["data"]["timeline"] if item["event_kind"] == OVERRIDE_KIND
    )
    assert override["reason"] == "Customer payroll"
    assert override["source_reference"] == "2026-07-20"
    assert str(override["source_href"]).endswith(f"#timeline-{override['event_id']}")


def test_lease_timeline_mixed_kind_cursor_pages_match_the_full_ordered_timeline(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, lease = mixed_lease(migrated_database_url)
    who = reader(human, prop, "invoices.read", "rent_nonpayment.read")
    paged = [item for items, _ in pages(who, lease) for item in items]
    full = api(who).get(f"/api/v1/leases/{lease}/timeline", params={"limit": "100"}).json()
    assert full["page"]["next_cursor"] is None
    assert paged == full["data"]
    keys = [
        (datetime.fromisoformat(str(item["occurred_at"])), UUID(str(item["event_id"])))
        for item in paged
    ]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)
    assert RESTRICTED_KINDS <= {item["event_kind"] for item in paged}
    assert len(paged) == len(todays_pages(lease)) + 2 == 5


def test_lease_timeline_restricted_function_is_bounded_and_runtime_has_no_table_access(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, lease = nonpayment_lease(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT p.prosecdef,p.provolatile,p.proconfig,"
            "has_function_privilege('prm_runtime',p.oid,'EXECUTE'),"
            "has_function_privilege('prm_financial',p.oid,'EXECUTE'),"
            "EXISTS(SELECT 1 FROM aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a "
            "WHERE a.grantee=0 AND a.privilege_type='EXECUTE') "
            "FROM pg_proc p WHERE p.oid=%s::regprocedure",
            (FUNCTION,),
        ).fetchone()
        assert row is not None
        assert row[0:2] == (True, "s") and "search_path=pg_catalog, pg_temp" in str(row[2])
        assert row[3:] == (True, False, False)
        for table in (
            "initial_rent_due_date_overrides",
            "rent_nonpayment_events",
            "rent_nonpayment_cases",
        ):
            assert connection.execute(
                "SELECT has_table_privilege('prm_runtime',%s,'SELECT'),"
                "has_table_privilege('prm_runtime',%s,'INSERT')",
                (f"app.{table}", f"app.{table}"),
            ).fetchone() == (False, False)
    with psycopg.connect(runtime_database_url()) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT 1 FROM app.rent_nonpayment_events LIMIT 1")
    for actor_id, limit, after in (
        (uuid4(), 1, (None, None)),
        (human, 0, (None, None)),
        (human, 102, (None, None)),
        (human, 1, (datetime.now().astimezone(), None)),
    ):
        with psycopg.connect(runtime_database_url()) as connection:
            with pytest.raises(psycopg.Error) as failure:
                connection.execute(
                    "SELECT * FROM app.lease_timeline_restricted("
                    "%s,%s,%s::uuid[],%s::uuid[],%s::timestamptz,%s::uuid,%s)",
                    (actor_id, lease, [prop], [prop], after[0], after[1], limit),
                ).fetchall()
            assert failure.value.sqlstate in {"42501", "22023"}


def _snapshot(url: str) -> tuple[dict[str, tuple[object, ...]], dict[str, object]]:
    with psycopg.connect(url) as connection:
        functions = {
            str(row[0]): cast(tuple[object, ...], row[1:])
            for row in connection.execute(
                "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                "p.proacl::text,p.prosecdef,p.provolatile FROM pg_catalog.pg_proc p "
                "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname='app' AND p.prokind='f'"
            ).fetchall()
        }
        tables = {
            str(row[0]): row[1]
            for row in connection.execute(
                "SELECT c.oid::regclass::text,c.relacl::text FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='app' AND c.relkind IN ('r','v','m','p')"
            ).fetchall()
        }
    return functions, tables


def test_lease_timeline_restricted_migration_is_additive_and_forward_only(
    migrated_database_url: str,  # noqa: F811
) -> None:
    assert migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261010_75")
    assert revision is not None and revision.down_revision == "20261009_74"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database("lease_timeline_restricted") as temporary:
        alembic_command.upgrade(config, "20261009_74")
        before_functions, before_tables = _snapshot(temporary)
        alembic_command.upgrade(config, "20261010_75")
        after_functions, after_tables = _snapshot(temporary)
    assert after_tables == before_tables
    added = set(after_functions) - set(before_functions)
    assert added == {FUNCTION}
    assert {name: after_functions[name] for name in before_functions} == before_functions
