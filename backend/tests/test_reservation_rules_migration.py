"""Reservations read their business rules on the real database (migration 20270422_272, V1.1
step 2b, DL-119): the longest Reservation, the longest extension and the suggested deposit."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import Connection

from property_rental.reservation_api import (
    EARLIER_RESERVATION_RULES,
    PostgresReservationResourceFlow,
    ReservationRules,
)
from test_move_in_migration import runtime_database_url
from test_reservation_migration import (
    connection,
    create_reservation,
    migrated_database_url,
    reservation_business_date,
    setup_reservation_sources,
)

__all__ = ["connection", "migrated_database_url"]

Sources = tuple[UUID, UUID, UUID, UUID]


def set_rule(connection: Connection[tuple[object, ...]], code: str, value: int, on: date) -> None:
    """A rule change inside the test's own transaction (rolled back after the test)."""
    connection.execute(
        "INSERT INTO app.business_rules (rule_name_id, value, effective_from, reason, created_by) "
        "SELECT name.id, %s, %s, 'test', NULL FROM app.business_rule_names AS name "
        "WHERE name.code = %s",
        (value, on, code),
    )


def make(
    connection: Connection[tuple[object, ...]],
    sources: Sources,
    *,
    expiration_days: int = 10,
    accepted_usd_cents: int = 10_000,
    trace_values: dict[str, object] | None = None,
) -> tuple[tuple[object, ...], dict[str, UUID]]:
    actor_id, property_id, unit_id, customer_id = sources
    return create_reservation(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        unit_id=unit_id,
        customer_id=customer_id,
        expiration_days=expiration_days,
        accepted_usd_cents=accepted_usd_cents,
        trace_values=trace_values,
    )


def refused(connection: Connection[tuple[object, ...]], sqlstate: str, work: object) -> None:
    with pytest.raises(psycopg.Error) as error, connection.transaction():
        work()  # type: ignore[operator]
    assert error.value.sqlstate == sqlstate


def test_migration_272_is_the_head() -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    assert scripts.get_heads() == ["20270422_272"]
    found = scripts.get_revision("20270422_272")
    assert found is not None and found.down_revision == "20270421_271"
    with pytest.raises(RuntimeError, match="forward-only"):
        found.module.downgrade()


def test_the_rules_are_read_by_day_with_the_earlier_values_and_a_safe_range(
    connection: Connection[tuple[object, ...]],
) -> None:
    rule = "SELECT app.reservation_rule(%s, %s)"
    today = date(2026, 11, 3)
    for code, earlier in (
        ("RESERVATION_DAYS", 21),
        ("RESERVATION_EXTENSION_DAYS", 14),
        ("RESERVATION_DEPOSIT_PERCENT", 2000),
    ):
        assert connection.execute(rule, (code, today)).fetchone() == (earlier,)
    assert connection.execute(rule, ("LATE_PAYMENT_PERCENT", today)).fetchone() == (None,)
    set_rule(connection, "RESERVATION_DEPOSIT_PERCENT", 2500, date(2095, 1, 1))
    assert connection.execute(
        rule, ("RESERVATION_DEPOSIT_PERCENT", date(2095, 1, 2))
    ).fetchone() == (2500,)
    assert connection.execute(
        rule, ("RESERVATION_DEPOSIT_PERCENT", date(2094, 12, 31))
    ).fetchone() == (2000,)
    suggestion = "SELECT app.reservation_deposit_suggestion(%s, %s)"
    for rent in (1, 2, 3, 12345, 12348, 50000):
        assert connection.execute(suggestion, (rent, today)).fetchone() == ((rent + 2) // 5,)
    assert connection.execute(suggestion, (50001, date(2095, 1, 2))).fetchone() == (12500,)
    used = connection.execute(
        "SELECT code FROM app.business_rule_names WHERE code LIKE 'RESERVATION_%%' "
        "AND used_by_app ORDER BY code"
    ).fetchall()
    assert used == [
        ("RESERVATION_DAYS",),
        ("RESERVATION_DEPOSIT_PERCENT",),
        ("RESERVATION_EXTENSION_DAYS",),
    ]
    for code, wrong in (
        ("RESERVATION_DAYS", 0),
        ("RESERVATION_DAYS", 91),
        ("RESERVATION_EXTENSION_DAYS", 91),
        ("RESERVATION_DEPOSIT_PERCENT", 0),
        ("RESERVATION_DEPOSIT_PERCENT", 10001),
    ):
        refused(
            connection,
            "22023",
            lambda code=code, wrong=wrong: set_rule(connection, code, wrong, date(2096, 1, 1)),
        )


def test_a_reservation_lasts_at_most_the_rule_days(
    connection: Connection[tuple[object, ...]],
) -> None:
    sources = setup_reservation_sources(connection)
    refused(connection, "23514", lambda: make(connection, sources, expiration_days=22))
    today = reservation_business_date(connection, sources[1])
    set_rule(connection, "RESERVATION_DAYS", 30, today)
    refused(connection, "23514", lambda: make(connection, sources, expiration_days=31))
    row, _ = make(connection, sources, expiration_days=30)
    assert row[4] == today + timedelta(days=30)


def test_one_extension_goes_at_most_the_rule_days(
    connection: Connection[tuple[object, ...]],
) -> None:
    sources = setup_reservation_sources(connection)
    actor_id, property_id, _unit_id, _customer_id = sources
    _, identities = make(connection, sources)
    previous = reservation_business_date(connection, property_id) + timedelta(days=10)
    extend = "SELECT * FROM app.extend_reservation(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"

    def ask(days: int) -> tuple[object, ...] | None:
        return connection.execute(
            extend,
            (
                property_id,
                uuid4(),
                "c" * 64,
                uuid4(),
                identities["reservation_id"],
                previous + timedelta(days=days),
                datetime.now(UTC),
                "Move-in needs more time",
                "reservations.extend",
                actor_id,
            ),
        ).fetchone()

    refused(connection, "23514", lambda: ask(15))
    set_rule(connection, "RESERVATION_EXTENSION_DAYS", 20, previous - timedelta(days=10))
    refused(connection, "23514", lambda: ask(21))
    row = ask(20)
    assert row is not None and row[3] == previous + timedelta(days=20)


def test_the_suggested_deposit_follows_the_rule_on_the_reservation_date(
    connection: Connection[tuple[object, ...]],
) -> None:
    sources = setup_reservation_sources(connection)
    today = reservation_business_date(connection, sources[1])
    set_rule(connection, "RESERVATION_DEPOSIT_PERCENT", 2500, today)
    # The earlier 20% is no longer the suggestion.
    refused(connection, "23514", lambda: make(connection, sources))
    _, identities = make(
        connection,
        sources,
        accepted_usd_cents=12_500,
        trace_values={"suggested_rate_basis_points": 2500, "suggested_amount_usd_cents": 12_500},
    )
    saved = connection.execute(
        "SELECT suggested_rate_basis_points, suggested_amount_usd_cents, acceptance_kind "
        "FROM app.reservation_deposit_acceptances WHERE reservation_id = %s",
        (identities["reservation_id"],),
    ).fetchone()
    assert saved == (2500, 12_500, "NORMAL_SUGGESTION")


def test_the_server_reads_the_rules_and_the_saved_suggestion(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as owner:
        sources = setup_reservation_sources(owner)
        _, identities = make(owner, sources)
        owner.commit()
    flow = PostgresReservationResourceFlow(runtime_database_url())
    assert flow.reservation_rules(sources[1], None) == ReservationRules(21, 14, 2000)
    assert flow.reservation_rules(uuid4(), None) == EARLIER_RESERVATION_RULES
    saved = flow.get(identities["reservation_id"])
    assert saved.suggested_deposit_usd_cents == 10_000
    assert saved.suggested_deposit_rate_basis_points == 2000
