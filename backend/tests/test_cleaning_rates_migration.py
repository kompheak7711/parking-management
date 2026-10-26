"""V1-058 R7b-6d: move-out cleaning rates by Unit Type (DL-075; DESIGN.md "Rates and services").

Migration 20270317_236 against a throwaway database at head, as the migration owner in one
transaction that is rolled back: a rate covers Unit Types and gives every Unit of them its amount,
ticking a type moves it from another rate, a Unit Type with Units is never left without a rate, a
new Unit takes its type's rate (audited under the Unit right) and a Unit moved to a type with no
rate keeps its amount, a repeat answers the same rate, a removed rate refuses every form (P0002), a
Unit Type taken out of the list leaves its rate's list, and only the functions are open to the
runtime role.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

from test_lease_migration import migrated_database_url as migrated_database_url
from test_lease_migration import setup_sources

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


def unit_type(connection: Connection[tuple[object, ...]], property_id: UUID, actor_id: UUID) -> str:
    """A new Unit Type of the list, so the test owns every Unit of it."""
    code: str = value(
        connection,
        "SELECT code FROM app.create_unit_setup_item(%s,%s,'UNIT_TYPE',%s,NULL,90,%s)",
        uuid4(),
        property_id,
        f"Cleaning test {uuid4().hex[:10]}",
        actor_id,
    )
    return code


def add_unit(
    connection: Connection[tuple[object, ...]], property_id: UUID, actor_id: UUID, code: str
) -> UUID:
    unit_id = uuid4()
    connection.execute(
        "INSERT INTO app.units(id,property_id,unit_number,floor,unit_type,status,created_by,"
        "updated_by) VALUES (%s,%s,%s,'1',%s,'VACANT',%s,%s)",
        (unit_id, property_id, f"CLEAN-{unit_id.hex[:12]}", code, actor_id, actor_id),
    )
    return unit_id


def save(
    connection: Connection[tuple[object, ...]],
    property_id: UUID,
    actor_id: UUID,
    rate_id: UUID,
    name: str,
    cents: int,
    types: list[str],
    version: int | None = None,
) -> Any:
    return value(
        connection,
        "SELECT app.save_cleaning_rate(%s,%s,%s,%s,NULL,%s,%s,%s,%s)",
        property_id,
        actor_id,
        rate_id,
        name,
        cents,
        types,
        version,
        SETTINGS,
    )


def unit_rate(connection: Connection[tuple[object, ...]], unit_id: UUID) -> Any:
    row = connection.execute(
        "SELECT rate.rate_usd_cents FROM app.unit_cleaning_rates AS rate WHERE rate.unit_id=%s "
        "AND NOT EXISTS (SELECT 1 FROM app.unit_cleaning_rates AS later "
        "WHERE later.supersedes_rate_id=rate.id)",
        (unit_id,),
    ).fetchone()
    return None if row is None else row[0]


def refused(connection: Connection[tuple[object, ...]], name: str, call: Any) -> str | None:
    connection.execute(f"SAVEPOINT {name}")
    with pytest.raises(psycopg.Error) as error:
        call()
    connection.execute(f"ROLLBACK TO SAVEPOINT {name}")
    return error.value.sqlstate


def test_a_rate_gives_its_unit_types_their_amount_and_ticking_moves_a_type(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, *_ = setup_sources(connection)
    studio = unit_type(connection, property_id, actor_id)
    suite = unit_type(connection, property_id, actor_id)
    studio_unit = add_unit(connection, property_id, actor_id, studio)
    suite_unit = add_unit(connection, property_id, actor_id, suite)
    assert unit_rate(connection, studio_unit) is None

    small_id = uuid4()
    small = save(connection, property_id, actor_id, small_id, " Small ", 1500, [studio, suite])
    assert small["name_en"] == "Small" and small["version"] == 1
    assert small["unit_types"] == sorted([studio, suite])
    assert unit_rate(connection, studio_unit) == 1500
    assert unit_rate(connection, suite_unit) == 1500
    # The same form again after a lost answer answers the same rate; other values are refused.
    assert (
        save(connection, property_id, actor_id, small_id, "Small", 1500, [suite, studio]) == small
    )
    assert (
        refused(
            connection,
            "reuse",
            lambda: save(connection, property_id, actor_id, small_id, "Small", 1600, [studio]),
        )
        == "23505"
    )

    # A second rate that ticks the suite moves it; the suite's Units get the new amount.
    large_id = uuid4()
    large = save(connection, property_id, actor_id, large_id, "Large", 2500, [suite])
    assert large["unit_types"] == [suite]
    assert unit_rate(connection, suite_unit) == 2500
    assert unit_rate(connection, studio_unit) == 1500
    read = value(connection, "SELECT app.cleaning_settings_read(%s)", property_id)
    by_code = {item["code"]: item for item in read["unit_types"]}
    assert by_code[studio]["cleaning_rate_id"] == str(small_id)
    assert by_code[suite]["cleaning_rate_id"] == str(large_id)
    assert by_code[suite]["units"] == 1
    small_now = next(
        rate for rate in read["cleaning_rates"] if rate["cleaning_rate_id"] == str(small_id)
    )
    # Losing a Unit Type is a change: an open form of the first rate is now out of date.
    assert small_now["unit_types"] == [studio] and small_now["version"] == 2

    # A new amount is a new link in each Unit's chain; nothing recorded changes.
    changed = save(connection, property_id, actor_id, small_id, "Small", 1800, [studio], 2)
    assert changed["version"] == 3 and changed["rate_usd_cents"] == 1800
    assert unit_rate(connection, studio_unit) == 1800
    assert (
        value(
            connection, "SELECT count(*) FROM app.unit_cleaning_rates WHERE unit_id=%s", studio_unit
        )
        == 2
    )
    # An old version answers NULL; the same amount adds no link.
    assert save(connection, property_id, actor_id, small_id, "Small", 1900, [studio], 2) is None
    save(connection, property_id, actor_id, small_id, "Small rooms", 1800, [studio], 3)
    assert (
        value(
            connection, "SELECT count(*) FROM app.unit_cleaning_rates WHERE unit_id=%s", studio_unit
        )
        == 2
    )
    # A new Unit, and a Unit whose type changes, take the type's rate.
    later_unit = add_unit(connection, property_id, actor_id, studio)
    assert unit_rate(connection, later_unit) == 1800
    connection.execute(
        "UPDATE app.units SET unit_type=%s, version=version+1 WHERE id=%s", (suite, later_unit)
    )
    assert unit_rate(connection, later_unit) == 2500
    # A link made for a Unit change is audited under the Unit right, not Settings access.
    assert value(
        connection,
        "SELECT array_agg(DISTINCT authorization_reference) FROM app.audit_events "
        "WHERE unit_id=%s AND action='unit.cleaning_rate.set' AND reason LIKE 'Cleaning rate of%%'",
        later_unit,
    ) == ["property.manage"]
    # A Unit Type with no rate yet: the Unit keeps the amount it had (Settings warns of it).
    bare = unit_type(connection, property_id, actor_id)
    connection.execute(
        "UPDATE app.units SET unit_type=%s, version=version+1 WHERE id=%s", (bare, later_unit)
    )
    assert unit_rate(connection, later_unit) == 2500
    read = value(connection, "SELECT app.cleaning_settings_read(%s)", property_id)
    assert next(item for item in read["unit_types"] if item["code"] == bare) == {
        "code": bare,
        "name_en": next(item["name_en"] for item in read["unit_types"] if item["code"] == bare),
        "name_km": None,
        "units": 1,
        "cleaning_rate_id": None,
    }
    assert (
        value(
            connection,
            "SELECT count(*) FROM app.audit_events WHERE entity_id=%s "
            "AND action IN ('cleaning_rate.added','cleaning_rate.changed')",
            small_id,
        )
        == 3
    )


def test_a_unit_type_with_units_is_never_left_without_a_rate(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, *_ = setup_sources(connection)
    studio = unit_type(connection, property_id, actor_id)
    empty = unit_type(connection, property_id, actor_id)
    add_unit(connection, property_id, actor_id, studio)
    rate_id = uuid4()
    save(connection, property_id, actor_id, rate_id, "Small", 1500, [studio, empty])
    # Untick or remove would leave the studio's Units without a rate.
    assert (
        refused(
            connection,
            "untick",
            lambda: save(connection, property_id, actor_id, rate_id, "Small", 1500, [empty], 1),
        )
        == "P5V03"
    )
    assert (
        refused(
            connection,
            "remove",
            lambda: connection.execute(
                "SELECT app.remove_cleaning_rate(%s,%s,%s,1,%s)",
                (property_id, actor_id, rate_id, SETTINGS),
            ),
        )
        == "P5V03"
    )
    # A type with no Units may be unticked.
    kept = save(connection, property_id, actor_id, rate_id, "Small", 1500, [studio], 1)
    assert kept["unit_types"] == [studio] and kept["version"] == 2
    # After the studio moves to another rate, the first one may go.
    save(connection, property_id, actor_id, uuid4(), "Studio", 1700, [studio])
    removed = value(
        connection,
        "SELECT app.remove_cleaning_rate(%s,%s,%s,3,%s)",
        property_id,
        actor_id,
        rate_id,
        SETTINGS,
    )
    assert removed["removed"] is True and removed["unit_types"] == []
    read = value(connection, "SELECT app.cleaning_settings_read(%s)", property_id)
    assert str(rate_id) not in [rate["cleaning_rate_id"] for rate in read["cleaning_rates"]]
    assert (
        next(item for item in read["unit_types"] if item["code"] == empty)["cleaning_rate_id"]
        is None
    )
    # A removed rate is gone for every form, whatever version it was opened at; unknown types,
    # a zero amount and a wrong reference are refused.
    for name, call, state in (
        (
            "gone",
            lambda: save(connection, property_id, actor_id, rate_id, "Small", 1500, [], 1),
            "P0002",
        ),
        (
            "removed_again",
            lambda: connection.execute(
                "SELECT app.remove_cleaning_rate(%s,%s,%s,1,%s)",
                (property_id, actor_id, rate_id, SETTINGS),
            ),
            "P0002",
        ),
        (
            "type",
            lambda: save(connection, property_id, actor_id, uuid4(), "X", 1500, ["NO_SUCH_TYPE"]),
            "22023",
        ),
        ("zero", lambda: save(connection, property_id, actor_id, uuid4(), "X", 0, []), "22023"),
        (
            "missing",
            lambda: save(connection, property_id, actor_id, uuid4(), "X", 100, [], 1),
            "P0002",
        ),
        (
            "reference",
            lambda: connection.execute(
                "SELECT app.save_cleaning_rate(%s,%s,%s,'X',NULL,100,ARRAY[]::text[],NULL,"
                "'property.manage')",
                (property_id, actor_id, uuid4()),
            ),
            "42501",
        ),
    ):
        assert refused(connection, name, call) == state, name
    assert value(connection, "SELECT app.cleaning_settings_read(%s)", uuid4()) is None
    # A Unit Type taken out of the Unit setup list (it has no Units) leaves its rate's list, and
    # sending the same new rate again still answers it.
    spare = unit_type(connection, property_id, actor_id)
    spare_rate = uuid4()
    first = save(connection, property_id, actor_id, spare_rate, "Spare", 900, [spare])
    assert first["unit_types"] == [spare]
    connection.execute(
        "SELECT app.remove_unit_setup_item(id, version, %s) FROM app.unit_setup_items "
        "WHERE property_id=%s AND list_kind='UNIT_TYPE' AND code=%s",
        (actor_id, property_id, spare),
    )
    read = value(connection, "SELECT app.cleaning_settings_read(%s)", property_id)
    shown = next(r for r in read["cleaning_rates"] if r["cleaning_rate_id"] == str(spare_rate))
    assert shown["unit_types"] == []
    assert save(connection, property_id, actor_id, spare_rate, "Spare", 900, [spare]) == shown


SIGNATURES = (
    "app.save_cleaning_rate(uuid,uuid,uuid,text,text,bigint,text[],integer,text)",
    "app.remove_cleaning_rate(uuid,uuid,uuid,integer,text)",
    "app.cleaning_settings_read(uuid)",
)


def test_only_the_functions_are_open_to_the_runtime_role_and_history_is_protected(
    connection: Connection[tuple[object, ...]],
) -> None:
    for table in ("app.cleaning_rates", "app.cleaning_rate_unit_types"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert not value(
                connection,
                "SELECT has_table_privilege('prm_runtime', %s, %s)",
                table,
                privilege,
            )
    for signature in SIGNATURES:
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
    actor_id, property_id, *_ = setup_sources(connection)
    rate_id = uuid4()
    save(connection, property_id, actor_id, rate_id, "Small", 1500, [])
    for name, sql in (
        ("owner", "UPDATE app.cleaning_rates SET created_by=gen_random_uuid(), version=2 "),
        ("jump", "UPDATE app.cleaning_rates SET version=version+2 "),
        ("delete", "DELETE FROM app.cleaning_rates "),
    ):
        assert (
            refused(
                connection,
                name,
                lambda sql=sql: connection.execute(sql + "WHERE id=%s", (rate_id,)),
            )
            == "55000"
        ), name
    assert (
        refused(
            connection,
            "truncate",
            lambda: connection.execute("TRUNCATE app.cleaning_rates CASCADE"),
        )
        == "55000"
    )
