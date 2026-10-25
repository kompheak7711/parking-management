"""V1-057 step 1: the report and export rights and the Home page read (DL-072, DL-079).

The three new rights reach the default Owner and Manager bundles through a new bundle version
and never the Staff bundle; the Home page read gives each section only when the application
passes it, checks the active person and the allowed Property, and lists the dated to-do items.
Rows on the shared test database are rolled back or belong to this module's own Units; the
bundle migration test uses a throwaway database.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.access_control import CAPABILITY_CATALOG, STAFF_DEFAULT_BUNDLE_CAPABILITIES
from property_rental.reports import HOME_SECTIONS, group_home_page, todo_group
from test_billing_service_migration import runtime_database_url, setup_billing_source
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_migrations import _run_alembic, _temporary_migration_database
from test_role_bundle_migration import add_account, the_property

REVISION = "20270301_220"
PREVIOUS = "20270218_206"
NEW_RIGHTS = {"audit.export", "data.export", "reports.read"}
HOME = "SELECT app.home_page(%s,%s,%s::uuid[],%s::text[])"


def today(url: str) -> date:
    with psycopg.connect(url) as connection:
        the_property(connection)
        row = connection.execute(
            "SELECT timezone(p.timezone_name,clock_timestamp())::date FROM app.properties p"
        ).fetchone()
    assert row is not None and isinstance(row[0], date)
    return row[0]


def month_end(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def home(url: str, actor: uuid.UUID, prop: uuid.UUID, sections: list[str]) -> dict[str, Any]:
    with psycopg.connect(url) as connection:
        row = connection.execute(HOME, (actor, prop, [prop], sections)).fetchone()
    assert row is not None
    return cast(dict[str, Any], row[0])


def test_the_new_rights_are_in_the_catalog_with_the_bundle_path(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        rows = connection.execute(
            "SELECT capability_id,description,grant_path FROM app.capabilities "
            "WHERE capability_id = ANY(%s)",
            (sorted(NEW_RIGHTS),),
        ).fetchall()
    assert {row[0]: (row[1], row[2]) for row in rows} == {
        right: (CAPABILITY_CATALOG[right], "bundle") for right in NEW_RIGHTS
    }
    assert not NEW_RIGHTS & STAFF_DEFAULT_BUNDLE_CAPABILITIES


def test_the_migration_gives_the_rights_to_the_owner_and_manager_bundles_only() -> None:
    """A new version of each default Owner and Manager bundle holds its old set plus the three
    rights, with an audit event naming the Owner; the Staff bundle stays as it was; a Property
    set up later gets them by the seed; forward-only."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == PREVIOUS
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database("prm_v1057_rights") as temporary:
        assert _run_alembic("upgrade", PREVIOUS).returncode == 0
        with psycopg.connect(temporary) as setup:
            owner = add_account(setup, "owner")
            property_id = the_property(setup)
            bundles = setup.execute(
                "SELECT owner_bundle_id,manager_bundle_id,staff_bundle_id "
                "FROM app.seed_default_role_bundles(%s)",
                (property_id,),
            ).fetchone()
            setup.commit()
        assert bundles is not None

        def held(connection: psycopg.Connection[Any], bundle: object) -> tuple[int, set[str]]:
            row = connection.execute(
                "SELECT b.version,array_agg(c.capability_id) FROM app.role_bundles b "
                "JOIN app.role_bundle_capabilities c ON c.role_bundle_id=b.role_bundle_id "
                "AND c.version=b.version WHERE b.role_bundle_id=%s GROUP BY b.version",
                (bundle,),
            ).fetchone()
            assert row is not None
            return int(row[0]), set(row[1])

        with psycopg.connect(temporary) as connection:
            before = [held(connection, bundle) for bundle in bundles]
        assert _run_alembic("upgrade", REVISION).returncode == 0
        with psycopg.connect(temporary) as connection:
            after = [held(connection, bundle) for bundle in bundles]
            events = connection.execute(
                "SELECT entity_id,actor_id,resulting_state FROM app.audit_events "
                "WHERE action='identity.role_bundle.updated' ORDER BY entity_id"
            ).fetchall()
        for index in (0, 1):
            assert after[index] == (before[index][0] + 1, before[index][1] | NEW_RIGHTS)
        assert after[2] == before[2] and not NEW_RIGHTS & after[2][1]
        assert sorted(str(row[0]) for row in events) == sorted(str(b) for b in bundles[:2])
        assert all(row[1] == owner for row in events)
        assert all(set(row[2]["added_capability_ids"]) == NEW_RIGHTS for row in events)


def test_the_home_page_lists_a_lease_near_its_end_and_leaves_out_unpassed_sections(
    migrated_database_url: str,
) -> None:
    now = today(migrated_database_url)
    start = (now.replace(day=1) - timedelta(days=95)).replace(day=1)
    end = month_end(now)
    with psycopg.connect(migrated_database_url) as connection:
        actor, prop, _, lease, _ = setup_billing_source(
            connection,
            configure_trash=False,
            configure_internet=False,
            move_in_date=start,
            lease_end_date=end,
        )
    page = home(runtime_database_url(), actor, prop, ["leases"])
    assert set(page["cards"]) == {"lease_renewal"}
    assert page["business_date"] == now.isoformat()
    mine = [item for item in page["todo"] if item.get("lease_id") == str(lease)]
    assert len(mine) == 1 and mine[0]["kind"] == "lease_ending"
    assert mine[0]["date"] == end.isoformat() and mine[0]["unit_number"]
    assert page["cards"]["lease_renewal"]["count"] >= 1
    assert page["cards"]["lease_renewal"]["end_on_or_before"] == (now + timedelta(60)).isoformat()
    grouped = cast(dict[str, Any], group_home_page(page))
    assert {item["group"] for item in grouped["todo"]} <= {"today", "this_week", "later"}
    nothing = home(runtime_database_url(), actor, prop, [])
    assert nothing["cards"] == {} and nothing["todo"] == [] and nothing["jobs"] == {}
    every = home(runtime_database_url(), actor, prop, list(HOME_SECTIONS))
    assert {
        "units_occupied",
        "pending_payment",
        "overdue",
        "paid_this_month",
        "lease_renewal",
        "waiting_for_approval",
        "meter_readings_missing",
        "letters_due",
    } == set(every["cards"])
    assert set(every["cards"]["paid_this_month"]) == {
        "billed_usd_cents",
        "billed_paid_usd_cents",
        "invoice_count",
        "received_usd_cents",
        "payment_count",
    }
    units = every["cards"]["units_occupied"]
    assert set(units) == {"occupied", "reserved", "vacant", "total"}
    assert units["occupied"] + units["reserved"] + units["vacant"] <= units["total"]
    waiting = every["cards"]["waiting_for_approval"]
    assert set(waiting) == {"count", "money_out_usd_cents", "money_out_count"}
    assert waiting["money_out_count"] <= waiting["count"]
    assert set(every["jobs"]) == {"last_billing_at", "next_billing_date", "rate_updated_at"}
    next_billing = date.fromisoformat(every["jobs"]["next_billing_date"])
    assert next_billing.day == 25 and now <= next_billing <= now + timedelta(31)


def test_the_home_page_checks_the_person_the_property_and_the_sections(
    migrated_database_url: str,
) -> None:
    runtime = runtime_database_url()
    with psycopg.connect(migrated_database_url) as connection:
        prop = the_property(connection)
        active = add_account(connection, "staff")
        disabled = add_account(connection, "staff", "disabled")
        connection.commit()
    with psycopg.connect(runtime) as connection:
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            connection.execute(HOME, (active, prop, [prop], ["units", "salaries"]))
        connection.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(HOME, (disabled, prop, [prop], ["units"]))
        connection.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(HOME, (active, prop, [uuid.uuid4()], ["units"]))
        connection.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT app.report_actor_property(%s,%s,%s::uuid[])", (active, prop, [prop])
            )


def test_to_do_groups_follow_the_property_day() -> None:
    day = date(2026, 10, 25)
    assert todo_group(date(2026, 10, 24), day) == "overdue"
    assert todo_group(day, day) == "today"
    assert todo_group(date(2026, 10, 31), day) == "this_week"
    assert todo_group(date(2026, 11, 1), day) == "later"
