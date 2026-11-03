"""Settings > Business on the real database (migration 20270421_271, V1.1 part 2, DL-118).

Owner 31/10/2026 and 01/11/2026: one numbering table for every document (format yy000n, numbers
never jump), Invoice types with late payment Yes/No (every type starts at Yes), the Property's
description and business name, and the business rules the program reads. Every write here is
rolled back.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any
from uuid import UUID

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_unit_migration import insert_actor, insert_property

Connection = psycopg.Connection[Any]
DOCUMENTS = {
    "INVOICE": "INVyy000n",
    "RECEIPT": "RCPyy000n",
    "REFUND": "RFDyy000n",
    "JOURNAL_ENTRY": "JEyy000n",
    "EXPENSE_REQUEST": "ERyy000n",
    "EXPENSE": "EXyy000n",
    "SUPPLIER_BILL": "SByy000n",
    "ADJUSTING_ENTRY": "AJyy000n",
    "FIXED_ASSET": "FAyy000n",
    "MONEY_MOVEMENT": "MVyy000n",
}
SET_RULE = "SELECT app.set_business_rule(%s, %s, %s, %s::date, %s, %s, gen_random_uuid())"


@pytest.fixture
def owner(migrated_database_url: str) -> Iterator[tuple[Connection, UUID, UUID]]:
    with psycopg.connect(migrated_database_url) as connection:
        actor_id = insert_actor(connection)
        existing = connection.execute("SELECT id FROM app.properties").fetchone()
        property_id = UUID(str(existing[0])) if existing else insert_property(connection, actor_id)
        yield connection, property_id, actor_id
        connection.rollback()


def refused(connection: Connection, error: type[Exception], query: str, parameters: Any) -> None:
    with pytest.raises(error):
        with connection.transaction():
            connection.execute(query, parameters)


def scalar(connection: Connection, query: str, parameters: Any = ()) -> Any:
    row = connection.execute(query, parameters).fetchone()
    assert row is not None
    return row[0]


def today(connection: Connection, property_id: UUID) -> date:
    found = scalar(
        connection,
        "SELECT timezone(timezone_name, statement_timestamp())::date FROM app.properties "
        "WHERE id=%s",
        (property_id,),
    )
    assert isinstance(found, date)
    return found


def test_migration_271_follows_the_ledger_head() -> None:
    config = Config("alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    found = scripts.get_revision("20270421_271")
    assert found is not None and found.down_revision == "20270420_270"


def test_every_document_has_one_number_rule_and_every_invoice_type_starts_at_yes(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(runtime_database_url()) as runtime:
        rules = runtime.execute(
            "SELECT DISTINCT ON (document_type) document_type, format FROM app.number_rules "
            "ORDER BY document_type, year DESC"
        ).fetchall()
        assert dict(rules) == DOCUMENTS
        kinds = runtime.execute(
            "SELECT code, late_payment FROM app.invoice_types ORDER BY sort_order"
        ).fetchall()
        assert kinds == [
            ("FIRST_RENT", True),
            ("RENT", True),
            ("UTILITIES", True),
            ("SERVICES", True),
            ("DAMAGE", True),
            ("MISCELLANEOUS", True),
        ]
        codes = runtime.execute(
            "SELECT name.code, name.used_by_app FROM app.business_rule_names AS name "
            "WHERE name.area IN ('BILLING','RESERVATIONS','PRICES','QUOTATIONS','RIEL_RATE')"
        ).fetchall()
        used = {code for code, by_app in codes if by_app}
        assert used == {
            "LATE_PAYMENT_PERCENT",
            "RESERVATION_DAYS",
            "RESERVATION_EXTENSION_DAYS",
            "RESERVATION_DEPOSIT_PERCENT",
        }
        assert {"METER_READING_DAY", "INVOICE_ISSUE_DAY", "RENT_DUE_DAY"} <= {
            code for code, _ in codes
        }


def test_numbers_continue_never_jump_and_a_new_year_starts_at_one(
    owner: tuple[Connection, UUID, UUID],
) -> None:
    connection, _property_id, _actor_id = owner
    connection.execute(
        "INSERT INTO app.number_rules (document_type, year, last_number, format) "
        "VALUES ('INVOICE', 2098, 41, 'INVyy000n')"
    )
    take = "SELECT app.take_document_number(%s, %s)"
    assert scalar(connection, take, ("INVOICE", 2098)) == "INV980042"
    assert scalar(connection, take, ("INVOICE", 2098)) == "INV980043"
    connection.execute(
        "UPDATE app.number_rules SET last_number = 9999 WHERE document_type='INVOICE' AND year=2098"
    )
    assert scalar(connection, take, ("INVOICE", 2098)) == "INV9810000"
    assert scalar(connection, take, ("INVOICE", 2099)) == "INV990001"
    refused(
        connection,
        psycopg.errors.ObjectNotInPrerequisiteState,
        "UPDATE app.number_rules SET last_number = 0 WHERE document_type='INVOICE' AND year=2099",
        (),
    )
    refused(
        connection,
        psycopg.errors.ObjectNotInPrerequisiteState,
        "DELETE FROM app.number_rules WHERE document_type='INVOICE' AND year=2099",
        (),
    )
    refused(connection, psycopg.errors.InvalidParameterValue, take, ("NO_SUCH_DOCUMENT", 2098))


def test_new_letters_are_used_for_the_next_number_with_history_and_must_be_unique(
    owner: tuple[Connection, UUID, UUID],
) -> None:
    connection, property_id, actor_id = owner
    change = "SELECT app.set_number_rule_letters(%s, %s, %s, %s, gen_random_uuid())"
    year = today(connection, property_id).year % 100
    following = scalar(connection, change, (property_id, "RECEIPT", "RC", actor_id))
    assert following.startswith(f"RC{year:02d}")
    event = connection.execute(
        "SELECT action, previous_state->>'format', resulting_state->>'format' "
        "FROM app.audit_events WHERE actor_id=%s",
        (actor_id,),
    ).fetchone()
    assert event == ("settings.number_rule.changed", "RCPyy000n", "RCyy000n")
    assert scalar(connection, "SELECT app.next_document_number('RECEIPT', now())") == following
    refused(
        connection,
        psycopg.errors.UniqueViolation,
        change,
        (property_id, "REFUND", "INV", actor_id),
    )
    refused(
        connection,
        psycopg.errors.InvalidParameterValue,
        change,
        (property_id, "REFUND", "rf1", actor_id),
    )


def test_late_payment_off_for_a_type_needs_a_reason_and_keeps_history(
    owner: tuple[Connection, UUID, UUID],
) -> None:
    connection, property_id, actor_id = owner
    switch = "SELECT app.set_invoice_type_late_payment(%s, %s, %s, %s, %s, gen_random_uuid())"
    gate = "SELECT app.invoice_type_late_payment(%s, %s)"
    refused(
        connection,
        psycopg.errors.InvalidParameterValue,
        switch,
        (property_id, "UTILITIES", False, " ", actor_id),
    )
    assert scalar(connection, gate, ("UTILITIES", None)) is True
    before = scalar(connection, "SELECT version FROM app.invoice_types WHERE code='UTILITIES'")
    assert scalar(connection, switch, (property_id, "UTILITIES", False, "Owner", actor_id)) == (
        before + 1
    )
    assert scalar(connection, gate, ("UTILITIES", None)) is False
    assert scalar(connection, gate, ("RENT", "INITIAL")) is True
    assert scalar(connection, gate, ("RENT", "RECURRING")) is True
    action = scalar(
        connection, "SELECT action FROM app.audit_events WHERE actor_id=%s", (actor_id,)
    )
    assert action == "settings.invoice_type.late_payment_changed"
    refused(
        connection,
        psycopg.errors.ObjectNotInPrerequisiteState,
        "DELETE FROM app.invoice_types",
        (),
    )


def test_the_program_reads_the_late_percent_from_the_rules(
    owner: tuple[Connection, UUID, UUID],
) -> None:
    connection, property_id, actor_id = owner
    now = today(connection, property_id)
    later = now + timedelta(days=5)
    assert (
        scalar(connection, "SELECT app.late_payment_rate_basis_points(%s, %s)", (property_id, now))
        == 1000
    )
    connection.execute(SET_RULE, (property_id, "LATE_PAYMENT_PERCENT", 500, later, "x", actor_id))
    assert (
        scalar(
            connection, "SELECT app.late_payment_rate_basis_points(%s, %s)", (property_id, later)
        )
        == 500
    )
    due = "SELECT app.one_time_charge_due_days(%s, %s)"
    column = "SELECT one_time_charge_due_days FROM app.properties WHERE id=%s"
    assert scalar(connection, due, (property_id, later)) == scalar(
        connection, column, (property_id,)
    )
    for code, wrong in (
        ("LATE_PAYMENT_PERCENT", 10001),
        ("RENT_DUE_DAY", 29),
    ):
        refused(
            connection,
            psycopg.errors.InvalidParameterValue,
            SET_RULE,
            (property_id, code, wrong, later + timedelta(days=1), "x", actor_id),
        )


def test_property_details_change_at_the_expected_version_with_history(
    owner: tuple[Connection, UUID, UUID],
) -> None:
    connection, property_id, actor_id = owner
    version = scalar(connection, "SELECT version FROM app.properties WHERE id=%s", (property_id,))
    details = "SELECT * FROM app.update_property_details(%s, %s, %s, %s, %s, %s, %s)"
    assert (
        connection.execute(
            details, (property_id, "Name", "", "", "", version + 5, actor_id)
        ).fetchone()
        is None
    )
    row = connection.execute(
        details,
        (
            property_id,
            " Chetana ",
            " Rooms near the river ",
            "",
            " CHETANA Co. ",
            version,
            actor_id,
        ),
    ).fetchone()
    assert row is not None
    assert (row[1], row[2], row[4], row[5], row[6]) == (
        "Chetana",
        None,
        version + 1,
        "Rooms near the river",
        "CHETANA Co.",
    )
    action = scalar(
        connection, "SELECT action FROM app.audit_events WHERE actor_id=%s", (actor_id,)
    )
    assert action == "property.details_changed"
    refused(
        connection,
        psycopg.errors.InvalidParameterValue,
        details,
        (property_id, "Name", "x" * 501, "", "", version + 1, actor_id),
    )
