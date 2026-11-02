"""Migration 20270408_258 (V1.1 rework part 1, owner 2026-11-02): Units for rent and DB fixes.

- A Manager or the Owner sets For rent at the Unit's version; each change is kept in History.
- A Unit in use for renting (a draft or signed Lease here) cannot be set not for rent.
- A Unit that is not for rent gets no Reservation and no Lease, and is left out of the Units
  counts on Home and of the Unit occupancy report.
- Fixes 2, 3 and 5 of the 01/11 database review.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.unit_api import (
    PostgresUnitResourceFlow,
    UnitInUseForRenting,
    UnitVersionConflict,
)
from test_lease_api_migration import migrated_database_url as migrated_database_url
from test_lease_api_migration import runtime_database_url
from test_lease_migration import create_draft, setup_sources


def _setup(url: str) -> dict[str, UUID]:
    with psycopg.connect(url) as connection:
        actor, prop, unit, tenant, _ = setup_sources(connection)
        connection.commit()
    return {"actor": actor, "prop": prop, "unit": unit, "tenant": tenant}


def test_for_rent_is_set_at_the_unit_version_and_kept_in_history(
    migrated_database_url: str,
) -> None:
    case = _setup(migrated_database_url)
    flow = PostgresUnitResourceFlow(runtime_database_url())
    actor = str(case["actor"])
    before = flow.get(case["unit"])
    assert before.for_rent is True
    same = flow.set_for_rent(
        case["unit"], for_rent=True, expected_version=before.version, actor_id=actor
    )
    assert same.version == before.version
    kept = flow.set_for_rent(
        case["unit"], for_rent=False, expected_version=before.version, actor_id=actor
    )
    assert kept.for_rent is False and kept.version == before.version + 1
    with pytest.raises(UnitVersionConflict):
        flow.set_for_rent(
            case["unit"], for_rent=True, expected_version=before.version, actor_id=actor
        )
    listed = flow.list(
        case["prop"], unit_status=None, attention=None, limit=100, cursor=None, for_rent=False
    )
    assert case["unit"] in {unit.unit_id for unit in listed.items}
    renting = flow.list(
        case["prop"], unit_status=None, attention=None, limit=100, cursor=None, for_rent=True
    )
    assert case["unit"] not in {unit.unit_id for unit in renting.items}
    back = flow.set_for_rent(
        case["unit"], for_rent=True, expected_version=kept.version, actor_id=actor
    )
    assert back.for_rent is True
    with psycopg.connect(migrated_database_url) as connection:
        history = connection.execute(
            "SELECT previous_state->>'for_rent', resulting_state->>'for_rent' "
            "FROM app.audit_events WHERE entity_id=%s AND action='unit.for_rent_changed' "
            "ORDER BY occurred_at",
            (case["unit"],),
        ).fetchall()
    assert history == [("true", "false"), ("false", "true")]


def test_a_unit_not_for_rent_gets_no_lease_and_is_not_counted(
    migrated_database_url: str,
) -> None:
    case = _setup(migrated_database_url)
    flow = PostgresUnitResourceFlow(runtime_database_url())
    actor = str(case["actor"])
    unit = flow.get(case["unit"])
    flow.set_for_rent(case["unit"], for_rent=False, expected_version=unit.version, actor_id=actor)
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            create_draft(
                connection,
                actor_id=case["actor"],
                unit_id=case["unit"],
                primary_tenant_id=case["tenant"],
            )
        connection.rollback()
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute(
                "INSERT INTO app.reservations("
                "id,unit_id,customer_id,reservation_date,agreed_monthly_rent_usd_cents,"
                "original_expiration_date,effective_expiration_date,status,created_by,"
                "updated_by) VALUES (%s,%s,%s,'2026-12-20',80000,'2027-01-05','2027-01-05',"
                "'ACTIVE',%s,%s)",
                (uuid4(), case["unit"], case["tenant"], case["actor"], case["actor"]),
            )
        connection.rollback()
        occupancy = connection.execute(
            "SELECT pg_catalog.pg_get_functiondef("
            "'app.report_unit_occupancy(uuid,uuid,uuid[])'::regprocedure)"
        ).fetchone()
        home = connection.execute(
            "SELECT pg_catalog.pg_get_functiondef("
            "'app.home_page(uuid,uuid,uuid[],text[])'::regprocedure)"
        ).fetchone()
    assert occupancy is not None and "AND unit.for_rent" in str(occupancy[0])
    assert home is not None and str(home[0]).count("unit.for_rent") == 2


def test_a_unit_with_a_lease_cannot_be_set_not_for_rent(migrated_database_url: str) -> None:
    case = _setup(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        create_draft(
            connection,
            actor_id=case["actor"],
            unit_id=case["unit"],
            primary_tenant_id=case["tenant"],
        )
        connection.commit()
    flow = PostgresUnitResourceFlow(runtime_database_url())
    unit = flow.get(case["unit"])
    with pytest.raises(UnitInUseForRenting):
        flow.set_for_rent(
            case["unit"],
            for_rent=False,
            expected_version=unit.version,
            actor_id=str(case["actor"]),
        )
    assert flow.get(case["unit"]).for_rent is True


def test_runtime_role_cannot_change_for_rent_directly(migrated_database_url: str) -> None:
    case = _setup(migrated_database_url)
    with (
        psycopg.connect(runtime_database_url()) as connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        connection.execute("UPDATE app.units SET for_rent=false WHERE id=%s", (case["unit"],))


def test_the_database_review_fixes_are_in_place(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        indexes = {
            str(row[0])
            for row in connection.execute(
                "SELECT indexname FROM pg_catalog.pg_indexes WHERE schemaname='app'"
            ).fetchall()
        }
        checks = {
            str(row[0])
            for row in connection.execute(
                "SELECT conname FROM pg_catalog.pg_constraint WHERE contype='c' "
                "AND conrelid IN ('app.lease_revisions'::regclass,'app.receipts'::regclass)"
            ).fetchall()
        }
    assert not indexes & {
        "invoice_lines_invoice_idx",
        "service_rates_effective_selection_idx",
        "utility_rates_effective_selection_idx",
        "settlement_correction_refund_details_correction_idx",
    }
    assert indexes >= {
        "payments_lease_idx",
        "invoice_adjustments_invoice_idx",
        "late_payment_charges_customer_idx",
        "receipts_payer_customer_idx",
        "refunds_recipient_customer_idx",
    }
    assert checks >= {
        "lease_revisions_monthly_rent_positive",
        "lease_revisions_status_check",
        "receipts_receipt_number_normalized",
    }
