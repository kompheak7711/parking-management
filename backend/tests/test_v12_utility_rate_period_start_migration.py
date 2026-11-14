"""Q3 (DL-230): the Utility Rate is chosen by the first day of the period of use.

The owner decided on 12 November 2026 that a new rate is used only for use from its start date.
Before, the rate in force on the day the Invoice was made was used for the whole period.

Each test sets its own rates inside a transaction that is rolled back, after hiding the rates
other tests left (as test_utility_consumption_migration does). That needs a database where no
Invoice line uses a rate yet, so this file runs right after that one in the gate list.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import Connection, Error

from test_utility_consumption_migration import (
    direct_finalize_actual,
    hide_utility_rates_for_transaction,
)
from test_utility_consumption_migration import (
    migrated_database_url as migrated_database_url,
)
from test_utility_meter_migration import add_meter, add_reading, utility_source

REVISION = "20270727_379"
PREVIEW = "app.preview_utility_calculation(uuid,text,uuid,timestamptz,uuid)"
NO_RATE = "Generation-date Utility Rate was not found"


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[Connection[tuple[object, ...]]]:
    with psycopg.connect(migrated_database_url) as database_connection:
        yield database_connection
        database_connection.rollback()


def noon(day: date) -> datetime:
    """Midday in Cambodia on that day, as the Invoice run's moment."""
    return datetime(day.year, day.month, day.day, 5, 0, tzinfo=UTC)


def add_rate_from(
    connection: Connection[tuple[object, ...]],
    *,
    actor_id: UUID,
    property_id: UUID,
    start: date,
    usd_per_unit: str,
) -> UUID:
    rate_id = uuid4()
    connection.execute(
        "INSERT INTO app.utility_rates("
        "id,property_id,utility_type,measurement_unit_code,rate_usd_per_unit,"
        "effective_date,notice_at,notice_evidence,actor_id) VALUES "
        "(%s,%s,'ELECTRICITY','KWH',%s,%s,%s::date - INTERVAL '2 days','Q3 TEST',%s)",
        (rate_id, property_id, Decimal(usd_per_unit), start, start, actor_id),
    )
    return rate_id


def period_of_use(
    connection: Connection[tuple[object, ...]], first_reading: date, last_reading: date, used: str
) -> tuple[UUID, UUID, UUID]:
    """One finished period of Electricity use on a new Unit, with no rate set yet.

    The readings are taken on ``first_reading`` and ``last_reading``. The period of use starts
    on the day after the first reading.
    """
    actor_id, property_id, unit_id = utility_source(connection)
    meter_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    start_reading, end_reading = (
        add_reading(
            connection,
            actor_id=actor_id,
            meter_id=meter_id,
            reading_date=day,
            reading_value=value,
        )
        for day, value in ((first_reading, "0"), (last_reading, used))
    )
    period_id = direct_finalize_actual(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        unit_id=unit_id,
        start_reading_id=start_reading,
        end_reading_id=end_reading,
    )
    hide_utility_rates_for_transaction(connection)
    return actor_id, property_id, period_id


def preview(
    connection: Connection[tuple[object, ...]],
    property_id: UUID,
    period_id: UUID,
    made_on: date,
    actor_id: UUID,
) -> tuple[UUID, date, int]:
    row = connection.execute(
        "SELECT (p->>'rate_id')::uuid,(p->>'rate_effective_date')::date,"
        "(p->>'amount_usd_cents')::bigint FROM (SELECT app.preview_utility_calculation("
        "%s,'CONSUMPTION_PERIOD',%s,%s,%s) AS p) AS answer",
        (property_id, period_id, noon(made_on), actor_id),
    ).fetchone()
    assert row is not None
    rate_id, rate_start, amount = row
    assert isinstance(rate_start, date) and isinstance(amount, int)
    return UUID(str(rate_id)), rate_start, amount


def test_the_rate_migration_follows_the_notice_days_and_is_forward_only() -> None:
    scripts = ScriptDirectory.from_config(Config(str(Path(__file__).parents[1] / "alembic.ini")))
    revision = scripts.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == "20270726_413"
    source = Path(revision.path).read_text(encoding="utf-8")
    assert "forward-only" in source
    assert "DELETE FROM" not in source and "DROP TABLE" not in source


def test_a_period_that_started_before_a_new_rate_keeps_the_old_rate_whatever_the_invoice_day(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, period_id = period_of_use(
        connection, date(2026, 1, 1), date(2026, 1, 31), "100"
    )
    old_rate = add_rate_from(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        start=date(2025, 12, 1),
        usd_per_unit="0.25",
    )
    add_rate_from(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        start=date(2026, 1, 15),
        usd_per_unit="0.30",
    )

    # Made before or after the new rate's start: 100 units at the rate of 1 January.
    for made_on in (date(2026, 1, 31), date(2026, 2, 1), date(2026, 6, 30)):
        assert preview(connection, property_id, period_id, made_on, actor_id) == (
            old_rate,
            date(2025, 12, 1),
            2500,
        )


def test_a_period_that_starts_on_the_new_rate_day_uses_the_new_rate(
    connection: Connection[tuple[object, ...]],
) -> None:
    # The first day of a period is the day after its start reading: here 15 January.
    actor_id, property_id, period_id = period_of_use(
        connection, date(2026, 1, 14), date(2026, 2, 15), "100"
    )
    add_rate_from(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        start=date(2025, 12, 1),
        usd_per_unit="0.25",
    )
    new_rate = add_rate_from(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        start=date(2026, 1, 15),
        usd_per_unit="0.30",
    )
    # A still later rate does not reach back, even when the Invoice is made after its start.
    add_rate_from(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        start=date(2026, 2, 1),
        usd_per_unit="0.40",
    )

    assert preview(connection, property_id, period_id, date(2026, 3, 1), actor_id) == (
        new_rate,
        date(2026, 1, 15),
        3000,
    )


def test_a_period_from_before_the_first_rate_uses_the_first_rate_once_it_has_started(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, period_id = period_of_use(
        connection, date(2026, 1, 1), date(2026, 1, 31), "100"
    )
    first_rate = add_rate_from(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        start=date(2026, 2, 10),
        usd_per_unit="0.25",
    )
    add_rate_from(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        start=date(2026, 3, 10),
        usd_per_unit="0.30",
    )

    # No older price exists. Until the first rate has started, the Invoice cannot be made.
    with pytest.raises(Error) as too_early:
        with connection.transaction():
            preview(connection, property_id, period_id, date(2026, 2, 9), actor_id)
    assert too_early.value.sqlstate == "P0002"
    assert NO_RATE in str(too_early.value)

    # From its start day on, and also after a second rate has started, the first rate is used.
    for made_on in (date(2026, 2, 10), date(2026, 4, 1)):
        assert preview(connection, property_id, period_id, made_on, actor_id) == (
            first_rate,
            date(2026, 2, 10),
            2500,
        )


def test_no_rate_at_all_is_refused_with_the_message_the_api_names(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, period_id = period_of_use(
        connection, date(2026, 1, 1), date(2026, 1, 31), "100"
    )

    with pytest.raises(Error) as refused:
        with connection.transaction():
            preview(connection, property_id, period_id, date(2026, 6, 1), actor_id)
    assert refused.value.sqlstate == "P0002"
    assert NO_RATE in str(refused.value)
