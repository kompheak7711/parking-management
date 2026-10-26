"""V1-058 R7b-6a: Services and Service types in Settings (DL-075; DESIGN.md "Rates and services").

Migration 20270316_235 against a throwaway database at head, as the migration owner in one
transaction that is rolled back: a Service is added with its first rate and approval period, a
repeat answers the same Service, a Lease holds only one Service of an "Only one per Lease" type,
and a type with Services is never removed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

from test_lease_migration import create_draft, setup_sources
from test_lease_migration import migrated_database_url as migrated_database_url

SETTINGS = "settings.manage"


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[Connection[tuple[object, ...]]]:
    with psycopg.connect(migrated_database_url) as database_connection:
        yield database_connection
        database_connection.rollback()


def value(connection: Connection[tuple[object, ...]], sql: str, *parameters: object) -> Any:
    row = connection.execute(sql, parameters).fetchone()
    assert row is not None
    return row[0]


def add_type(
    connection: Connection[tuple[object, ...]],
    property_id: UUID,
    actor_id: UUID,
    name: str,
    one: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = value(
        connection,
        "SELECT app.add_service_type(%s,%s,%s,%s,NULL,%s,%s)",
        property_id,
        actor_id,
        uuid4(),
        name,
        one,
        SETTINGS,
    )
    return result


def add_service(
    connection: Connection[tuple[object, ...]],
    property_id: UUID,
    actor_id: UUID,
    name: str,
    type_id: object,
    service_id: UUID | None = None,
    cents: int = 500,
    starts_on: date = date(2027, 1, 1),
) -> dict[str, Any]:
    result: dict[str, Any] = value(
        connection,
        "SELECT app.add_property_service(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        property_id,
        actor_id,
        service_id or uuid4(),
        name,
        "សេវា",
        type_id,
        cents,
        starts_on,
        SETTINGS,
    )
    return result


def term(
    connection: Connection[tuple[object, ...]],
    lease_id: UUID,
    service_id: object,
    actor_id: UUID,
    starts: date = date(2027, 1, 1),
    through: date | None = None,
) -> None:
    approval = value(
        connection,
        "SELECT id FROM app.property_service_approval_periods WHERE property_service_id=%s",
        service_id,
    )
    connection.execute(
        "INSERT INTO app.lease_service_terms(id,lease_id,property_service_id,applicable_from,"
        "applicable_through,service_approval_period_id,terms_reference,recorded_at,recorded_by) "
        "VALUES (%s,%s,%s,%s,%s,%s,'Chosen on the New Lease form',clock_timestamp(),%s)",
        (uuid4(), lease_id, service_id, starts, through, approval, actor_id),
    )


def test_a_service_is_added_with_its_first_rate_and_approval_and_a_repeat_answers_it(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, *_ = setup_sources(connection)
    trash = add_type(connection, property_id, actor_id, "Trash", True)
    assert trash["one_per_lease"] is True and trash["services"] == 0
    service_id = uuid4()
    added = add_service(
        connection, property_id, actor_id, "Trash Collection", trash["service_type_id"], service_id
    )
    # The first "Trash Collection" gets TRASH_COLLECTION (if the Property has none yet); any other
    # Service gets a code from its id (since R7b-6e it is billed like Trash Collection).
    trash_code = value(
        connection,
        "SELECT count(*) FROM app.property_services WHERE property_id=%s "
        "AND service_code='TRASH_COLLECTION' AND id<>%s",
        property_id,
        service_id,
    )
    assert added["service_code"] == (
        "TRASH_COLLECTION" if trash_code == 0 else "SVC_" + service_id.hex.upper()
    )
    other_id = uuid4()
    other = add_service(connection, property_id, actor_id, "  trash   COLLECTION ", None, other_id)
    assert other["service_code"] == "SVC_" + other_id.hex.upper()
    assert added["name_km"] == "សេវា" and added["version"] == 1
    # The same id and values answer the same Service; other values are refused.
    assert (
        add_service(
            connection,
            property_id,
            actor_id,
            "Trash Collection",
            trash["service_type_id"],
            service_id,
        )
        == added
    )
    connection.execute("SAVEPOINT reuse")
    with pytest.raises(psycopg.errors.UniqueViolation):
        add_service(
            connection, property_id, actor_id, "Trash Collection", None, service_id, cents=600
        )
    connection.execute("ROLLBACK TO SAVEPOINT reuse")
    assert (
        value(
            connection,
            "SELECT monthly_rate_usd_cents FROM app.service_rates WHERE property_service_id=%s",
            service_id,
        )
        == 500
    )
    assert value(
        connection,
        "SELECT effective_from FROM app.property_service_approval_periods "
        "WHERE property_service_id=%s AND effective_through IS NULL",
        service_id,
    ) == date(2027, 1, 1)
    assert (
        value(
            connection,
            "SELECT count(*) FROM app.audit_events WHERE entity_id=%s "
            "AND action='property_service.added' AND authorization_reference=%s",
            service_id,
            SETTINGS,
        )
        == 1
    )
    # A start that is not the 1st, a missing Settings reference, an unknown type are refused.
    for name, call in (
        (
            "day",
            lambda: add_service(
                connection, property_id, actor_id, "Water", None, starts_on=date(2027, 1, 2)
            ),
        ),
        ("type", lambda: add_service(connection, property_id, actor_id, "Water", uuid4())),
    ):
        connection.execute(f"SAVEPOINT {name}")
        with pytest.raises(psycopg.Error) as refused:
            cast(Callable[[], object], call)()
        assert refused.value.sqlstate == "22023"
        connection.execute(f"ROLLBACK TO SAVEPOINT {name}")
    connection.execute("SAVEPOINT reference")
    with pytest.raises(psycopg.Error) as refused:
        connection.execute(
            "SELECT app.add_service_type(%s,%s,%s,'Parking',NULL,false,'property.manage')",
            (property_id, actor_id, uuid4()),
        )
    assert refused.value.sqlstate == "42501"
    connection.execute("ROLLBACK TO SAVEPOINT reference")


def test_a_lease_holds_only_one_service_of_an_only_one_type(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, unit_id, tenant_id, _ = setup_sources(connection)
    trash = add_type(connection, property_id, actor_id, "Trash", True)
    parking = add_type(connection, property_id, actor_id, "Parking", False)
    small = add_service(connection, property_id, actor_id, "Trash small", trash["service_type_id"])
    large = add_service(connection, property_id, actor_id, "Trash large", trash["service_type_id"])
    car = add_service(connection, property_id, actor_id, "Car park", parking["service_type_id"])
    bike = add_service(connection, property_id, actor_id, "Bike park", parking["service_type_id"])
    lease_id = create_draft(
        connection, actor_id=actor_id, unit_id=unit_id, primary_tenant_id=tenant_id
    )
    term(connection, lease_id, small["service_id"], actor_id, through=date(2027, 6, 30))
    term(connection, lease_id, car["service_id"], actor_id)
    term(connection, lease_id, bike["service_id"], actor_id)
    # Another Trash Service at the same time is refused; after the first one ends it is fine.
    connection.execute("SAVEPOINT overlap")
    with pytest.raises(psycopg.errors.CheckViolation):
        term(connection, lease_id, large["service_id"], actor_id, starts=date(2027, 6, 1))
    connection.execute("ROLLBACK TO SAVEPOINT overlap")
    term(connection, lease_id, large["service_id"], actor_id, starts=date(2027, 7, 1))
    # Parking may not become "Only one" while the Lease holds two parking Services.
    connection.execute("SAVEPOINT one")
    with pytest.raises(psycopg.Error) as refused:
        connection.execute(
            "SELECT app.update_service_type(%s,%s,%s,'Parking',NULL,true,1,%s)",
            (property_id, actor_id, parking["service_type_id"], SETTINGS),
        )
    assert refused.value.sqlstate == "P5V01"
    connection.execute("ROLLBACK TO SAVEPOINT one")
    # Nor may the bike park move into the Trash type; a Service type with Services stays.
    connection.execute("SAVEPOINT move")
    with pytest.raises(psycopg.Error) as refused:
        connection.execute(
            "SELECT app.update_property_service(%s,%s,%s,'Car park',NULL,%s,1,%s)",
            (property_id, actor_id, car["service_id"], trash["service_type_id"], SETTINGS),
        )
    assert refused.value.sqlstate == "P5V01"
    connection.execute("ROLLBACK TO SAVEPOINT move")
    connection.execute("SAVEPOINT remove")
    with pytest.raises(psycopg.Error) as refused:
        connection.execute(
            "SELECT app.remove_service_type(%s,%s,%s,1,%s)",
            (property_id, actor_id, parking["service_type_id"], SETTINGS),
        )
    assert refused.value.sqlstate == "P5V02"
    connection.execute("ROLLBACK TO SAVEPOINT remove")
    # A rename keeps the type; an old version answers NULL; an empty type is removed.
    renamed = value(
        connection,
        "SELECT app.update_property_service(%s,%s,%s,'Car parking','ចំណតឡាន',%s,1,%s)",
        property_id,
        actor_id,
        car["service_id"],
        parking["service_type_id"],
        SETTINGS,
    )
    assert renamed["name_en"] == "Car parking" and renamed["version"] == 2
    assert (
        value(
            connection,
            "SELECT app.update_property_service(%s,%s,%s,'Car',NULL,%s,1,%s)",
            property_id,
            actor_id,
            car["service_id"],
            parking["service_type_id"],
            SETTINGS,
        )
        is None
    )
    empty = add_type(connection, property_id, actor_id, "Laundry", False)
    removed = value(
        connection,
        "SELECT app.remove_service_type(%s,%s,%s,1,%s)",
        property_id,
        actor_id,
        empty["service_type_id"],
        SETTINGS,
    )
    assert removed["removed"] is True
    connection.execute("SAVEPOINT removed")
    with pytest.raises(psycopg.Error):
        add_service(connection, property_id, actor_id, "Wash", empty["service_type_id"])
    connection.execute("ROLLBACK TO SAVEPOINT removed")


def test_the_settings_read_gives_rates_approvals_and_leases_using_each_service(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, unit_id, tenant_id, _ = setup_sources(connection)
    trash = add_type(connection, property_id, actor_id, "Trash", True)
    service = add_service(
        connection, property_id, actor_id, "Trash Collection", trash["service_type_id"]
    )
    connection.execute(
        "INSERT INTO app.service_rates(id,property_service_id,monthly_rate_usd_cents,"
        "effective_date,actor_id) VALUES (%s,%s,700,%s,%s)",
        (uuid4(), service["service_id"], date(2027, 9, 1), actor_id),
    )
    lease_id = create_draft(
        connection, actor_id=actor_id, unit_id=unit_id, primary_tenant_id=tenant_id
    )
    term(connection, lease_id, service["service_id"], actor_id)
    read = value(
        connection, "SELECT app.service_settings_read(%s,%s)", property_id, date(2027, 3, 1)
    )
    found = next(item for item in read["services"] if item["service_id"] == service["service_id"])
    assert found["rate_today_usd_cents"] == 500
    assert found["next_rate"] == {"monthly_rate_usd_cents": 700, "effective_date": "2027-09-01"}
    assert found["rates"] == [
        {"monthly_rate_usd_cents": 500, "effective_date": "2027-01-01"},
        {"monthly_rate_usd_cents": 700, "effective_date": "2027-09-01"},
    ]
    assert found["leases_using"] == 1
    assert [period["effective_from"] for period in found["approval_periods"]] == ["2027-01-01"]
    assert (
        next(
            item
            for item in read["service_types"]
            if item["service_type_id"] == trash["service_type_id"]
        )["services"]
        == 1
    )
    assert (
        value(connection, "SELECT app.service_settings_read(%s,%s)", uuid4(), date(2027, 3, 1))
        is None
    )


WRITERS = (
    "app.add_property_service(uuid,uuid,uuid,text,text,uuid,bigint,date,text)",
    "app.update_property_service(uuid,uuid,uuid,text,text,uuid,integer,text)",
    "app.add_service_type(uuid,uuid,uuid,text,text,boolean,text)",
    "app.update_service_type(uuid,uuid,uuid,text,text,boolean,integer,text)",
    "app.remove_service_type(uuid,uuid,uuid,integer,text)",
    "app.service_settings_read(uuid,date)",
)


def test_the_runtime_role_may_only_call_the_settings_functions(
    connection: Connection[tuple[object, ...]],
) -> None:
    for privilege in ("INSERT", "UPDATE", "DELETE"):
        assert (
            value(
                connection,
                "SELECT has_table_privilege('prm_runtime', 'app.service_types', %s)",
                privilege,
            )
            is False
        )
    for signature in WRITERS:
        assert value(
            connection, "SELECT has_function_privilege('prm_runtime', %s, 'EXECUTE')", signature
        )
        assert not value(
            connection,
            "SELECT bool_or(acl.grantee = 0) FROM pg_proc AS proc, "
            "aclexplode(coalesce(proc.proacl, acldefault('f', proc.proowner))) AS acl "
            "WHERE proc.oid = %s::regprocedure AND acl.privilege_type = 'EXECUTE'",
            signature,
        )
        assert value(
            connection,
            "SELECT prosecdef AND proconfig @> ARRAY['search_path=pg_catalog'] "
            "FROM pg_proc WHERE oid = %s::regprocedure",
            signature,
        )


def test_service_history_and_reused_type_ids_are_refused(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, *_ = setup_sources(connection)
    own = add_type(connection, property_id, actor_id, "Parking", False)
    service = add_service(connection, property_id, actor_id, "Car park", own["service_type_id"])
    # The app keeps one Property, so a type of another Property cannot exist; an unknown type
    # id is refused the same way (22023) in the first test.
    # Identity and history stay protected against direct changes.
    for name, sql in (
        (
            "code",
            "UPDATE app.property_services SET service_code='X', version=version+1 WHERE id=%s",
        ),
        (
            "owner",
            "UPDATE app.property_services SET created_by=gen_random_uuid(), "
            "version=version+1 WHERE id=%s",
        ),
        ("jump", "UPDATE app.property_services SET version=version+2 WHERE id=%s"),
        ("delete", "DELETE FROM app.property_services WHERE id=%s"),
    ):
        connection.execute(f"SAVEPOINT {name}")
        with pytest.raises(psycopg.Error) as refused:
            connection.execute(sql, (service["service_id"],))
        assert refused.value.sqlstate == "55000", name
        connection.execute(f"ROLLBACK TO SAVEPOINT {name}")
    # A Service type id used again with other values is refused; the same values answer it.
    type_id = uuid4()
    first = value(
        connection,
        "SELECT app.add_service_type(%s,%s,%s,'Laundry',NULL,false,%s)",
        property_id,
        actor_id,
        type_id,
        SETTINGS,
    )
    assert (
        value(
            connection,
            "SELECT app.add_service_type(%s,%s,%s,'Laundry',NULL,false,%s)",
            property_id,
            actor_id,
            type_id,
            SETTINGS,
        )
        == first
    )
    connection.execute("SAVEPOINT type_reuse")
    with pytest.raises(psycopg.errors.UniqueViolation):
        connection.execute(
            "SELECT app.add_service_type(%s,%s,%s,'Laundry',NULL,true,%s)",
            (property_id, actor_id, type_id, SETTINGS),
        )
    connection.execute("ROLLBACK TO SAVEPOINT type_reuse")
    connection.execute("SAVEPOINT truncate")
    with pytest.raises(psycopg.Error) as refused:
        connection.execute("TRUNCATE app.service_types CASCADE")
    assert refused.value.sqlstate == "55000"
    connection.execute("ROLLBACK TO SAVEPOINT truncate")
