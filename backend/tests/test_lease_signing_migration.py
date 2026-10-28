"""Migration 20270325_244 (V1-060 B6, DL-100): the draft Lease's planned Security Deposit, the
amounts due at signing, and the Initial Rent Invoice made right after signing."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg
import pytest

from property_rental.billing import prorated_monthly_usd_cents
from test_invoice_migration import financial_database_url, runtime_database_url
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_lease_migration import create_draft, setup_sources, sign_lease

PLAN = "SELECT app.set_lease_planned_security_deposit(%s,%s,%s,%s,%s,%s,%s)"


def _draft(url: str, start: date) -> tuple[UUID, UUID, UUID]:
    with psycopg.connect(url) as connection:
        actor_id, property_id, unit_id, customer_id, _ = setup_sources(connection)
        lease_id = create_draft(
            connection,
            actor_id=actor_id,
            unit_id=unit_id,
            primary_tenant_id=customer_id,
            start_date=start,
            end_date=date(start.year + 1, 12, 31),
        )
    return actor_id, property_id, lease_id


def _service(
    url: str,
    *,
    actor_id: UUID,
    property_id: UUID,
    lease_id: UUID,
    applicable_from: date,
    rate_cents: int,
) -> None:
    service_id, approval_id = uuid4(), uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.property_services(id,property_id,service_code,display_name,"
            "configured_by,created_by,updated_by) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                service_id,
                property_id,
                f"SIGN-{service_id.hex[:10]}",
                f"Parking {service_id.hex[:6]}",
                actor_id,
                actor_id,
                actor_id,
            ),
        )
        connection.execute(
            "INSERT INTO app.service_rates(id,property_service_id,monthly_rate_usd_cents,"
            "effective_date,occurred_at,actor_id) VALUES (%s,%s,%s,%s,now(),%s)",
            (uuid4(), service_id, rate_cents, applicable_from - timedelta(days=60), actor_id),
        )
        connection.execute(
            "INSERT INTO app.property_service_approval_periods(id,property_service_id,"
            "effective_from,effective_through,approval_reference,approved_at,approved_by,"
            "reason) VALUES (%s,%s,%s,NULL,'owner-sign',now(),%s,'Approved Service')",
            (approval_id, service_id, applicable_from - timedelta(days=60), actor_id),
        )
        connection.execute(
            "INSERT INTO app.lease_service_terms(id,lease_id,property_service_id,"
            "applicable_from,applicable_through,service_approval_period_id,terms_reference,"
            "recorded_at,recorded_by) VALUES (%s,%s,%s,%s,NULL,%s,'signed-terms',now(),%s)",
            (uuid4(), lease_id, service_id, applicable_from, approval_id, actor_id),
        )


def _initial_invoice(property_id: UUID, lease_id: UUID, actor_id: UUID, start: date) -> UUID:
    """The Initial Rent Invoice step of app.sign_lease_with_payment (DL-108)."""
    invoice_id = uuid4()
    with psycopg.connect(financial_database_url()) as connection:
        row = connection.execute(
            "SELECT app.generate_rent_service_invoice"
            "(%s,%s,%s,%s,%s,%s,NULL,'INITIAL',%s,clock_timestamp(),%s,NULL)",
            (
                property_id,
                uuid4(),
                hashlib.sha256(invoice_id.bytes).hexdigest(),
                invoice_id,
                f"RENT-I-{invoice_id.hex[:12]}",
                lease_id,
                start,
                actor_id,
            ),
        ).fetchone()
    assert row is not None
    return UUID(str(cast(dict[str, object], row[0])["invoice_id"]))


def _preview(url: str, property_id: UUID, lease_id: UUID) -> dict[str, object]:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT app.lease_signing_preview(%s,%s)", (property_id, lease_id)
        ).fetchone()
    assert row is not None
    return cast(dict[str, object], row[0])


def test_the_draft_keeps_its_planned_security_deposit_and_only_the_draft(
    migrated_database_url: str,
) -> None:
    actor, prop, lease = _draft(migrated_database_url, date(2027, 2, 10))
    runtime = runtime_database_url()
    first = uuid4()
    with psycopg.connect(runtime) as connection:
        assert connection.execute(
            PLAN, (prop, lease, first, actor, 50_000, "Draft Lease terms", "leases.draft")
        ).fetchone() == (50_000,)
        # A replay of the same save, and the same amount again, add nothing.
        assert connection.execute(
            PLAN, (prop, lease, first, actor, 50_000, "Draft Lease terms", "leases.draft")
        ).fetchone() == (50_000,)
        assert connection.execute(
            PLAN, (prop, lease, uuid4(), actor, 50_000, "Draft Lease terms", "leases.draft")
        ).fetchone() == (50_000,)
        assert connection.execute(
            PLAN, (prop, lease, uuid4(), actor, 60_000, "Customer asked", "leases.draft")
        ).fetchone() == (60_000,)
        connection.commit()
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            connection.execute(
                PLAN, (prop, lease, uuid4(), actor, 0, "Draft Lease terms", "leases.draft")
            )
        connection.rollback()
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            connection.execute(
                PLAN, (prop, lease, uuid4(), actor, 70_000, "Draft Lease terms", "leases.sign")
            )
        connection.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT * FROM app.lease_planned_security_deposits")
    assert _preview(runtime, prop, lease)["planned_security_deposit_usd_cents"] == 60_000
    with psycopg.connect(migrated_database_url) as connection:
        rows = connection.execute(
            "SELECT required_usd_cents FROM app.lease_planned_security_deposits "
            "WHERE lease_id=%s ORDER BY recorded_at",
            (lease,),
        ).fetchall()
        assert rows == [(50_000,), (60_000,)]
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events "
            "WHERE action='lease.security_deposit.planned' AND lease_id=%s",
            (lease,),
        ).fetchone() == (2,)
        with pytest.raises(psycopg.Error):
            connection.execute(
                "UPDATE app.lease_planned_security_deposits SET required_usd_cents=1 "
                "WHERE lease_id=%s",
                (lease,),
            )
        connection.rollback()
        sign_lease(connection, lease, actor)
    with psycopg.connect(runtime) as connection:
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState) as refused:
            connection.execute(
                PLAN, (prop, lease, uuid4(), actor, 70_000, "After signing", "leases.draft")
            )
    assert refused.value.diag.message_primary == (
        "Only a drafted Lease takes a planned Security Deposit"
    )


def test_a_renewal_draft_takes_no_planned_security_deposit(migrated_database_url: str) -> None:
    actor, prop, first = _draft(migrated_database_url, date(2027, 3, 1))
    with psycopg.connect(migrated_database_url) as connection:
        sign_lease(connection, first, actor)
        unit, tenant = connection.execute(
            "SELECT unit_id,primary_tenant_id FROM app.leases WHERE id=%s", (first,)
        ).fetchone() or (None, None)
        renewal = create_draft(
            connection,
            actor_id=actor,
            unit_id=cast(UUID, unit),
            primary_tenant_id=cast(UUID, tenant),
            start_date=date(2029, 1, 1),
            end_date=date(2029, 12, 31),
            predecessor_lease_id=first,
        )
    with psycopg.connect(runtime_database_url()) as connection:
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute(
                PLAN, (prop, renewal, uuid4(), actor, 50_000, "Renewal", "leases.draft")
            )


def test_the_preview_is_the_initial_rent_invoice_made_after_signing(
    migrated_database_url: str,
) -> None:
    start = datetime.now(ZoneInfo("Asia/Phnom_Penh")).date()
    actor, prop, lease = _draft(migrated_database_url, start)
    _service(
        migrated_database_url,
        actor_id=actor,
        property_id=prop,
        lease_id=lease,
        applicable_from=start,
        rate_cents=1_234,
    )
    runtime = runtime_database_url()
    preview = cast(dict[str, object], _preview(runtime, prop, lease)["initial"])
    first_end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    rent = prorated_monthly_usd_cents(80_000, start, first_end)
    if start.day >= 21:
        rent += 80_000
    assert preview["rent_usd_cents"] == rent
    assert preview["due_date"] == (start + timedelta(days=5)).isoformat()
    assert preview["problem"] is None and preview["invoice_id"] is None
    lines = cast(list[dict[str, object]], preview["service_lines"])
    assert len(lines) == (2 if start.day >= 21 else 1)
    # The generator makes it only for a signed Lease; Sign Lease (DL-108) runs it right after the
    # signing, in the same transaction.
    with pytest.raises(psycopg.Error) as early:
        _initial_invoice(prop, lease, actor, start)
    assert early.value.diag.message_primary == "Rent billing requires an applicable signed Lease"
    with psycopg.connect(migrated_database_url) as connection:
        sign_lease(connection, lease, actor)
    made = _initial_invoice(prop, lease, actor, start)
    with psycopg.connect(migrated_database_url) as connection:
        total = connection.execute(
            "SELECT sum(amount_usd_cents) FROM app.invoice_lines WHERE invoice_id=%s",
            (made,),
        ).fetchone()
    assert total is not None and int(str(total[0])) == preview["total_usd_cents"]
    after = cast(dict[str, object], _preview(runtime, prop, lease)["initial"])
    assert after["invoice_id"] == str(made)


def test_a_service_covering_part_of_the_first_month_is_named_before_any_money(
    migrated_database_url: str,
) -> None:
    start = date(2027, 4, 3)
    actor, prop, lease = _draft(migrated_database_url, start)
    _service(
        migrated_database_url,
        actor_id=actor,
        property_id=prop,
        lease_id=lease,
        applicable_from=date(2027, 4, 10),
        rate_cents=1_000,
    )
    preview = cast(dict[str, object], _preview(runtime_database_url(), prop, lease)["initial"])
    assert str(preview["problem"]).startswith("PARTIAL_SERVICE:Parking ")
    assert preview["total_usd_cents"] == prorated_monthly_usd_cents(
        80_000, start, date(2027, 4, 30)
    )
