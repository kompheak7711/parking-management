"""Business rules and the General Ledger rights (migrations 20270413_263 and 20270414_264).

Owner 31/10/2026 (business_rule_names and business_rules with full history), 03/11/2026 06:56
(phase 6 plan: ledger limits on the Business rules page, ledger rights table) and 07:03 (a Manager
approves Expenses up to the Expense limit and tops up petty cash). Every write here is rolled back.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.access_control import (
    BUNDLE_CAPABILITIES,
    MANAGER_DEFAULT_BUNDLE_CAPABILITIES,
    OWNER_ONLY_LEDGER_CAPABILITIES,
    STAFF_DEFAULT_BUNDLE_CAPABILITIES,
)
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_unit_migration import insert_actor, insert_property

Connection = psycopg.Connection[Any]
SET = "SELECT app.set_business_rule(%s, %s, %s, %s::date, %s, %s, gen_random_uuid())"
ADD = (
    "SELECT app.add_business_rule_name(%s, %s, %s, %s, %s, %s, %s, %s::date, %s, %s, "
    "gen_random_uuid())"
)
LEDGER_RULES = {
    "EXPENSE_LIMIT": ("USD_CENTS", 10000),
    "ASSET_LIMIT": ("USD_CENTS", 50000),
    "PETTY_CASH": ("USD_CENTS", 20000),
    "EXP_REPORT_DAYS": ("DAYS", 3),
    "BUDGET_PCT": ("PERCENT", 1000),
    "BUDGET_MIN": ("USD_CENTS", 5000),
    "SUPPLIER_BILL_DAYS": ("DAYS", 30),
    # Phase 6 step 4 (migration 20270417_267, owner 2026-11-03 10:26): years each kind lasts.
    "ASSET_LIFE_1510": ("COUNT", 20),
    "ASSET_LIFE_1520": ("COUNT", 5),
    "ASSET_LIFE_1530": ("COUNT", 3),
}


def refused(
    connection: Connection,
    error: type[Exception],
    query: str,
    parameters: Any = (),
    match: str | None = None,
) -> None:
    with pytest.raises(error, match=match):
        with connection.transaction():
            connection.execute(query, parameters)


@pytest.fixture
def owner_setup(migrated_database_url: str) -> Iterator[tuple[Connection, UUID, UUID]]:
    with psycopg.connect(migrated_database_url) as connection:
        actor_id = insert_actor(connection)
        existing = connection.execute("SELECT id FROM app.properties").fetchone()
        property_id = UUID(str(existing[0])) if existing else insert_property(connection, actor_id)
        yield connection, property_id, actor_id
        connection.rollback()


def today(connection: Connection, property_id: UUID) -> date:
    row = connection.execute(
        "SELECT timezone(timezone_name, statement_timestamp())::date FROM app.properties "
        "WHERE id=%s",
        (property_id,),
    ).fetchone()
    assert row is not None and isinstance(row[0], date)
    return row[0]


def value(connection: Connection, code: str, on: date) -> int | None:
    row = connection.execute("SELECT app.business_rule_value(%s, %s)", (code, on)).fetchone()
    assert row is not None
    return None if row[0] is None else int(row[0])


def test_the_ledger_rules_are_seeded_and_read_by_date(migrated_database_url: str) -> None:
    with psycopg.connect(runtime_database_url()) as runtime:
        rows = runtime.execute(
            "SELECT name.code, name.value_unit, name.area, name.used_by_app, rule.value, "
            "rule.effective_from FROM app.business_rule_names AS name JOIN app.business_rules "
            "AS rule ON rule.rule_name_id = name.id WHERE name.area = 'LEDGER'"
        ).fetchall()
        assert {row[0]: (row[1], row[4]) for row in rows} == LEDGER_RULES
        assert {(row[2], row[3], row[5]) for row in rows} == {("LEDGER", True, date(2026, 1, 1))}
        assert value(runtime, "EXPENSE_LIMIT", date(2027, 1, 1)) == 10000
        assert value(runtime, "EXPENSE_LIMIT", date(2025, 12, 31)) is None
        assert value(runtime, "NO_SUCH_RULE", date(2027, 1, 1)) is None


def test_a_change_is_a_new_dated_row_with_a_reason_and_an_audit_event(
    owner_setup: tuple[Connection, UUID, UUID],
) -> None:
    connection, property_id, actor_id = owner_setup
    now = today(connection, property_id)
    later = now + timedelta(days=10)
    connection.execute(SET, (property_id, "EXPENSE_LIMIT", 15000, later, "More work", actor_id))
    assert value(connection, "EXPENSE_LIMIT", now) == 10000
    assert value(connection, "EXPENSE_LIMIT", later) == 15000
    event = connection.execute(
        "SELECT action, entity_type, reason, previous_state, resulting_state->>'value' "
        "FROM app.audit_events WHERE actor_id=%s AND action LIKE 'settings.business_rule.%%'",
        (actor_id,),
    ).fetchone()
    assert event == (
        "settings.business_rule.changed",
        "business_rule",
        "More work",
        {"code": "EXPENSE_LIMIT", "value": 10000},
        "15000",
    )
    for code, amount, on, reason, error, match in (
        ("EXPENSE_LIMIT", 1, later, "Twice", psycopg.errors.UniqueViolation, None),
        (
            "EXPENSE_LIMIT",
            1,
            now - timedelta(days=1),
            "Past",
            psycopg.errors.InvalidParameterValue,
            "today or later",
        ),
        (
            "EXPENSE_LIMIT",
            1,
            later + timedelta(days=1),
            " ",
            psycopg.errors.CheckViolation,
            "needs a reason",
        ),
        ("NOPE", 1, later, "Unknown", psycopg.errors.InvalidParameterValue, "No business rule"),
        (
            "EXPENSE_LIMIT",
            -1,
            later + timedelta(days=2),
            "Below",
            psycopg.errors.CheckViolation,
            None,
        ),
        (
            "BUDGET_PCT",
            1000001,
            later,
            "Too much",
            psycopg.errors.InvalidParameterValue,
            "fit its unit",
        ),
    ):
        refused(connection, error, SET, (property_id, code, amount, on, reason, actor_id), match)


def test_the_owner_adds_a_rule_the_program_does_not_use_yet(
    owner_setup: tuple[Connection, UUID, UUID],
) -> None:
    connection, property_id, actor_id = owner_setup
    now = today(connection, property_id)
    code = f"TEST_{uuid4().hex[:8].upper()}"
    connection.execute(
        ADD,
        (
            property_id,
            code,
            "Test rule",
            "ច្បាប់សាកល្បង",
            "DAY_OF_MONTH",
            "OTHER",
            5,
            now,
            None,
            actor_id,
        ),
    )
    assert connection.execute(
        "SELECT used_by_app FROM app.business_rule_names WHERE code=%s", (code,)
    ).fetchone() == (False,)
    assert value(connection, code, now) == 5
    for bad_code, unit, amount, error in (
        ("lower_case", "DAYS", 1, psycopg.errors.CheckViolation),
        (code, "DAYS", 1, psycopg.errors.UniqueViolation),
        (f"{code}_B", "WEEKS", 1, psycopg.errors.CheckViolation),
        (f"{code}_C", "DAY_OF_MONTH", 32, psycopg.errors.InvalidParameterValue),
        (f"{code}_D", "YES_NO", 2, psycopg.errors.InvalidParameterValue),
        (f"{code}_E", "TIME_OF_DAY", 1440, psycopg.errors.InvalidParameterValue),
    ):
        refused(
            connection,
            error,
            ADD,
            (property_id, bad_code, "Bad", "Bad", unit, "OTHER", amount, now, None, actor_id),
        )


def test_rule_values_are_append_only_and_names_keep_their_code(
    owner_setup: tuple[Connection, UUID, UUID],
) -> None:
    connection, _, _ = owner_setup
    for query in (
        "UPDATE app.business_rules SET value = 1",
        "DELETE FROM app.business_rules",
        "TRUNCATE app.business_rules CASCADE",
        "UPDATE app.business_rule_names SET code = 'CHANGED' WHERE code = 'EXPENSE_LIMIT'",
        "UPDATE app.business_rule_names SET value_unit = 'DAYS' WHERE code = 'EXPENSE_LIMIT'",
        "DELETE FROM app.business_rule_names WHERE code = 'EXPENSE_LIMIT'",
        "TRUNCATE app.business_rule_names CASCADE",
    ):
        refused(connection, psycopg.errors.ObjectNotInPrerequisiteState, query)
    connection.execute(
        "UPDATE app.business_rule_names SET name_en = 'Expense limit' WHERE code = 'EXPENSE_LIMIT'"
    )
    refused(
        connection,
        psycopg.errors.CheckViolation,
        "INSERT INTO app.business_rules (rule_name_id, value, effective_from) SELECT id, 1, "
        "DATE '2030-01-01' FROM app.business_rule_names WHERE code = 'EXPENSE_LIMIT'",
        match="needs a reason",
    )


def test_the_runtime_only_reads_and_writes_through_the_functions(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(runtime_database_url()) as runtime:
        for query in (
            "INSERT INTO app.business_rule_names (code, name_en, name_kh, value_unit, area) "
            "VALUES ('X_RULE', 'x', 'x', 'DAYS', 'OTHER')",
            "UPDATE app.business_rule_names SET used_by_app = true",
            "DELETE FROM app.business_rules",
        ):
            refused(runtime, psycopg.errors.InsufficientPrivilege, query)
        assert runtime.execute(
            "SELECT has_function_privilege('prm_runtime', 'app.set_business_rule(uuid,text,"
            "bigint,date,text,uuid,uuid)', 'EXECUTE'), has_function_privilege('prm_financial', "
            "'app.business_rule_value(text,date)', 'EXECUTE')"
        ).fetchone() == (True, True)


def test_the_default_bundles_hold_the_ledger_rights_by_role(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        rows = connection.execute(
            "SELECT capability_id, grant_path, provenance FROM app.capabilities "
            "WHERE provenance = 'v1-1-ledger'"
        ).fetchall()
        assert len(rows) == 21 and {row[1] for row in rows} == {"bundle"}
        ledger = {row[0] for row in rows}
        assert ledger <= BUNDLE_CAPABILITIES
        assert OWNER_ONLY_LEDGER_CAPABILITIES < ledger
        assert ledger - OWNER_ONLY_LEDGER_CAPABILITIES <= MANAGER_DEFAULT_BUNDLE_CAPABILITIES
        assert {"expenses.approve", "ledger.petty_cash"} <= MANAGER_DEFAULT_BUNDLE_CAPABILITIES
        assert "expenses.approve_over_limit" in OWNER_ONLY_LEDGER_CAPABILITIES
        assert ledger & STAFF_DEFAULT_BUNDLE_CAPABILITIES == {"expenses.request"}
        # Every existing default bundle holds its role's rights at its current version.
        for column, expected in (
            ("owner_bundle_id", ledger),
            ("manager_bundle_id", ledger - OWNER_ONLY_LEDGER_CAPABILITIES),
            ("staff_bundle_id", {"expenses.request"}),
        ):
            held = connection.execute(
                f"SELECT seeded.property_id, array_agg(held.capability_id) FILTER (WHERE "
                f"held.capability_id = ANY(%s)) FROM app.default_role_bundles AS seeded "
                f"JOIN app.role_bundles AS bundle ON bundle.role_bundle_id = seeded.{column} "
                f"JOIN app.role_bundle_capabilities AS held ON held.role_bundle_id = "
                f"bundle.role_bundle_id AND held.version = bundle.version "
                f"GROUP BY seeded.property_id",
                (sorted(ledger),),
            ).fetchall()
            for _, names in held:
                assert set(names or ()) == expected, column
