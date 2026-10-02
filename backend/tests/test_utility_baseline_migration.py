"""Utility baseline Readings start a Customer's Utility responsibility for a Lease.

The single-Property Utility run rejects overlapping run date ranges, takes its rate and Invoice
date from the run's business date, and cannot bill a future period. These tests therefore use
2019, a year no other suite runs, one month per run and their own rate date (``slot``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.billing_run import (
    BillingRunCommand,
    BillingRunDetail,
    PostgresBillingRunService,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.utility import (
    UTILITY_CALCULATE_CAPABILITY,
    FinalizeActualConsumptionCommand,
    PostgresUtilityService,
)
from property_rental.utility_baseline import (
    BASELINE_READ,
    BASELINE_RECORD,
    BaselineItem,
    PostgresUtilityBaselineService,
    RecordUtilityBaseline,
    UtilityBaselineAuthorizationError,
    UtilityBaselineConflictError,
    UtilityBaselineInvalidError,
    UtilityBaselineKeyReused,
    UtilityBaselineNotFoundError,
)
from test_invoice_migration import (
    financial_database_url,
    register_billing_service_principal,
    runtime_database_url,
)
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_lease_migration import create_draft, setup_sources, sign_lease
from test_utility_consumption_migration import replace_failed_meter
from test_utility_meter_migration import add_meter, add_reading

NEW_TABLES = ("utility_baseline_events", "utility_baseline_items", "utility_baseline_commands")
YEAR = 2019


@dataclass(frozen=True)
class Source:
    human: UUID
    prop: UUID
    unit: UUID
    customer: UUID
    lease: UUID
    worker: UUID
    electricity: UUID
    month: int
    year: int = YEAR

    @property
    def start(self) -> date:
        return date(self.year, self.month, 3)

    @property
    def baseline_day(self) -> date:
        return date(self.year, self.month, 2)


def source(url: str, slot: int, month: int, *, sign: bool = True, year: int = YEAR) -> Source:
    """One Unit, Lease starting on the 3rd of the month, Meter and a rate dated by slot."""
    with psycopg.connect(url) as connection:
        human, prop, unit, customer, _ = setup_sources(connection)
        lease = create_draft(
            connection,
            actor_id=human,
            unit_id=unit,
            primary_tenant_id=customer,
            start_date=date(year, month, 3),
            end_date=date(year + 1, 6, 30),
        )
        if sign:
            sign_lease(connection, lease, human)
        electricity = add_meter(
            connection, actor_id=human, unit_id=unit, installed_date=date(year, 1, 1)
        )
        connection.execute(
            "INSERT INTO app.utility_rates(id,property_id,utility_type,measurement_unit_code,"
            "rate_usd_per_unit,effective_date,notice_at,notice_evidence,actor_id) "
            "VALUES (%s,%s,'ELECTRICITY','KWH',0.25,%s,%s,"
            "'OWNER-NOTICE',%s)",
            (uuid4(), prop, date(year, 1, slot + 1), datetime(year - 1, 12, 1, tzinfo=UTC), human),
        )
        worker = register_billing_service_principal(connection, property_id=prop, created_by=human)
        connection.commit()
    return Source(human, prop, unit, customer, lease, worker, electricity, month, year)


def add_water(url: str, s: Source) -> UUID:
    with psycopg.connect(url) as connection:
        return add_meter(
            connection,
            actor_id=s.human,
            unit_id=s.unit,
            utility_type="WATER",
            measurement_unit_code="M3",
            installed_date=date(YEAR, 1, 1),
        )


def reading(
    url: str, s: Source, meter: UUID, day: date, value: str = "100", *, validated: bool = True
) -> UUID:
    with psycopg.connect(url) as connection:
        return add_reading(
            connection,
            actor_id=s.human,
            meter_id=meter,
            reading_date=day,
            reading_value=value,
            validated=validated,
        )


def occupy(url: str, s: Source, day: date) -> None:
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,created_by,"
            "updated_by) VALUES (%s,%s,%s,%s,%s,%s)",
            (uuid4(), s.lease, s.customer, day, s.human, s.human),
        )


def one(url: str, query: str, *parameters: object) -> tuple[Any, ...]:
    with psycopg.connect(url) as connection:
        row = connection.execute(query, parameters).fetchone()
    assert row is not None
    return row


def service() -> PostgresUtilityBaselineService:
    return PostgresUtilityBaselineService(runtime_database_url(), financial_database_url())


def actor(s: Source, *capabilities: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(s.human),
        frozenset(
            CapabilityGrant(capability, frozenset({str(s.prop)}))
            for capability in (capabilities or (BASELINE_READ, BASELINE_RECORD))
        ),
    )


def command(
    s: Source,
    items: tuple[BaselineItem, ...],
    *,
    day: date | None = None,
    supersedes: UUID | None = None,
    key: UUID | None = None,
    event: UUID | None = None,
) -> RecordUtilityBaseline:
    return RecordUtilityBaseline(
        key or uuid4(),
        event or uuid4(),
        day or s.baseline_day,
        items,
        "Baseline recorded after cleaning and repair",
        "Handover sheet 17",
        supersedes,
    )


def record(
    s: Source,
    value: RecordUtilityBaseline,
    *,
    who: AuthenticatedActor | None = None,
    lease: UUID | None = None,
) -> dict[str, object]:
    return (
        service()
        .record(s.prop, lease or s.lease, value, actor=who or actor(s), request_id="baseline-test")
        .body
    )


def baseline(
    url: str,
    s: Source,
    *,
    day: date | None = None,
    value: str = "100",
    supersedes: UUID | None = None,
) -> tuple[UUID, UUID]:
    """Record one electricity baseline Reading and return its event and Reading identities."""
    reading_id = reading(url, s, s.electricity, day or s.baseline_day, value)
    event = uuid4()
    record(
        s,
        command(
            s,
            (BaselineItem(s.electricity, reading_id),),
            day=day,
            supersedes=supersedes,
            event=event,
        ),
    )
    return event, reading_id


def database_now() -> datetime:
    return cast(datetime, one(financial_database_url(), "SELECT clock_timestamp()")[0])


def finalize(s: Source, start_reading: UUID, end_reading: UUID) -> UUID:
    period = uuid4()
    calculator = AuthenticatedActor(
        str(s.human),
        frozenset({CapabilityGrant(UTILITY_CALCULATE_CAPABILITY, frozenset({str(s.prop)}))}),
    )
    PostgresUtilityService(financial_database_url(), s.prop, s.human).finalize_actual(
        FinalizeActualConsumptionCommand(
            idempotency_key=uuid4(),
            consumption_period_id=period,
            unit_id=s.unit,
            utility_type="ELECTRICITY",
            start_reading_id=start_reading,
            end_reading_id=end_reading,
            finalized_at=database_now(),
        ),
        actor=calculator,
    )
    return period


def run(s: Source, start: date, end: date) -> BillingRunDetail:
    worker = AuthenticatedActor(
        str(s.worker), frozenset({CapabilityGrant("billing.generate", frozenset({str(s.prop)}))})
    )
    return PostgresBillingRunService(financial_database_url()).execute(
        BillingRunCommand(
            property_id=s.prop,
            run_kind="UTILITIES",
            logical_run_key=f"utilities/{start}/{end}/{uuid4()}",
            business_date=end,
            period_start=start,
            period_end=end,
            idempotency_key=uuid4(),
        ),
        actor=worker,
        invocation_source="SCHEDULED",
    )


def line_count(url: str, period: UUID) -> int:
    return int(
        one(
            url,
            "SELECT count(*) FROM app.invoice_lines AS line "
            "JOIN app.invoices AS invoice ON invoice.id=line.invoice_id "
            "WHERE line.utility_consumption_period_id=%s AND invoice.status<>'VOID'",
            period,
        )[0]
    )


def boundary(url: str, s: Source) -> date | None:
    return cast(date | None, one(url, "SELECT app.utility_baseline_boundary(%s)", s.lease)[0])


def event_count(url: str, *leases: UUID) -> int:
    marks = ",".join(["%s"] * len(leases))
    return int(
        one(
            url,
            f"SELECT count(*) FROM app.utility_baseline_events WHERE lease_id IN ({marks})",
            *leases,
        )[0]
    )


def test_baseline_is_recorded_once_replayed_audited_and_creates_nothing_else(
    migrated_database_url: str,
) -> None:
    s = source(migrated_database_url, 1, 2)
    reading_id = reading(migrated_database_url, s, s.electricity, s.baseline_day)
    value = command(s, (BaselineItem(s.electricity, reading_id),))
    readings_before = one(migrated_database_url, "SELECT count(*) FROM app.utility_readings")
    periods_before = one(
        migrated_database_url, "SELECT count(*) FROM app.utility_consumption_periods"
    )
    first = record(s, value)
    assert record(s, value) == first
    data = cast(dict[str, object], first["data"])
    assert data["baseline_date"] == str(s.baseline_day)
    assert data["responsibility_starts_on"] == str(s.start)
    assert data["creates_reading"] is False and data["creates_charge"] is False
    items = cast(list[dict[str, object]], data["items"])
    assert [item["reading_id"] for item in items] == [str(reading_id)]
    assert event_count(migrated_database_url, s.lease) == 1
    assert one(
        migrated_database_url,
        "SELECT count(*),min(action),min(authorization_reference) FROM app.audit_events "
        "WHERE entity_type='utility_baseline' AND entity_id=%s",
        value.event_id,
    ) == (1, "utility.baseline.record", "utility_readings.record")
    assert (
        one(migrated_database_url, "SELECT count(*) FROM app.utility_readings") == readings_before
    )
    assert (
        one(migrated_database_url, "SELECT count(*) FROM app.utility_consumption_periods")
        == periods_before
    )
    assert boundary(migrated_database_url, s) == s.start
    page = service().read(s.prop, s.lease, actor=actor(s))
    assert page["total"] == 1 and page["creates_charge"] is False
    assert cast(list[dict[str, object]], page["items"])[0]["event_status"] == "CURRENT"
    with pytest.raises(UtilityBaselineKeyReused):
        record(s, command(s, (BaselineItem(s.electricity, reading_id),), key=value.idempotency_key))


def test_baseline_may_be_dated_on_the_lease_start_date_but_never_after_it(
    migrated_database_url: str,
) -> None:
    on_start = source(migrated_database_url, 2, 2)
    event, _ = baseline(migrated_database_url, on_start, day=on_start.start)
    assert one(
        migrated_database_url,
        "SELECT baseline_date FROM app.utility_baseline_events WHERE id=%s",
        event,
    ) == (on_start.start,)
    before = source(migrated_database_url, 3, 2)
    baseline(migrated_database_url, before, day=date(YEAR, 1, 25))
    after = source(migrated_database_url, 4, 2)
    late_day = date(YEAR, 2, 4)
    late = reading(migrated_database_url, after, after.electricity, late_day)
    with pytest.raises(UtilityBaselineInvalidError):
        record(after, command(after, (BaselineItem(after.electricity, late),), day=late_day))
    assert event_count(migrated_database_url, after.lease) == 0


def test_baseline_requires_every_applicable_validated_reading_on_the_baseline_date(
    migrated_database_url: str,
) -> None:
    s = source(migrated_database_url, 5, 2)
    water = add_water(migrated_database_url, s)
    electric_reading = reading(migrated_database_url, s, s.electricity, s.baseline_day)
    water_reading = reading(migrated_database_url, s, water, s.baseline_day, "20")
    with pytest.raises(UtilityBaselineInvalidError):
        record(s, command(s, (BaselineItem(s.electricity, electric_reading),)))
    unvalidated = reading(migrated_database_url, s, water, date(YEAR, 2, 1), "19", validated=False)
    with pytest.raises(UtilityBaselineInvalidError):
        record(
            s,
            command(
                s,
                (BaselineItem(s.electricity, electric_reading), BaselineItem(water, unvalidated)),
            ),
        )
    after_baseline = reading(migrated_database_url, s, water, date(YEAR, 2, 3), "21")
    with pytest.raises(UtilityBaselineInvalidError):
        record(
            s,
            command(
                s,
                (
                    BaselineItem(s.electricity, electric_reading),
                    BaselineItem(water, after_baseline),
                ),
            ),
        )
    with pytest.raises(UtilityBaselineNotFoundError):
        record(
            s,
            command(
                s,
                (
                    BaselineItem(s.electricity, water_reading),
                    BaselineItem(water, electric_reading),
                ),
            ),
        )
    assert event_count(migrated_database_url, s.lease) == 0
    both = (BaselineItem(s.electricity, electric_reading), BaselineItem(water, water_reading))
    body = record(s, command(s, both))
    assert len(cast(list[object], cast(dict[str, object], body["data"])["items"])) == 2


def test_baseline_follows_the_active_meters_when_a_meter_was_replaced_before_it(
    migrated_database_url: str,
) -> None:
    s = source(migrated_database_url, 6, 2)
    reading(migrated_database_url, s, s.electricity, date(YEAR, 1, 19), "10")
    replacement, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=s.human,
        unit_id=s.unit,
        failed_meter_id=s.electricity,
        failure_date=date(YEAR, 1, 20),
        replacement_date=date(YEAR, 1, 21),
    )
    new_reading = reading(migrated_database_url, s, replacement, s.baseline_day, "5")
    with pytest.raises(UtilityBaselineInvalidError):
        record(s, command(s, (BaselineItem(s.electricity, uuid4()),)))
    record(s, command(s, (BaselineItem(replacement, new_reading),)))
    assert one(
        migrated_database_url,
        "SELECT count(*) FROM app.utility_baseline_items AS item "
        "JOIN app.utility_baseline_events AS event ON event.id=item.event_id "
        "WHERE event.lease_id=%s AND item.meter_id=%s",
        s.lease,
        replacement,
    ) == (1,)


def test_baseline_is_rejected_for_unsigned_occupied_unknown_or_unauthorized_leases(
    migrated_database_url: str,
) -> None:
    draft = source(migrated_database_url, 7, 2, sign=False)
    draft_reading = reading(migrated_database_url, draft, draft.electricity, draft.baseline_day)
    with pytest.raises(UtilityBaselineInvalidError):
        record(draft, command(draft, (BaselineItem(draft.electricity, draft_reading),)))
    occupied = source(migrated_database_url, 8, 2)
    occupied_reading = reading(
        migrated_database_url, occupied, occupied.electricity, occupied.baseline_day
    )
    occupy(migrated_database_url, occupied, occupied.start)
    with pytest.raises(UtilityBaselineInvalidError):
        record(occupied, command(occupied, (BaselineItem(occupied.electricity, occupied_reading),)))
    ready = source(migrated_database_url, 9, 2)
    ready_reading = reading(migrated_database_url, ready, ready.electricity, ready.baseline_day)
    items = (BaselineItem(ready.electricity, ready_reading),)
    with pytest.raises(UtilityBaselineNotFoundError):
        record(ready, command(ready, items), lease=uuid4())
    with pytest.raises(UtilityBaselineAuthorizationError):
        record(ready, command(ready, items), who=actor(ready, BASELINE_READ))
    with pytest.raises(UtilityBaselineNotFoundError):
        service().read(ready.prop, ready.lease, actor=actor(ready, BASELINE_RECORD))
    assert event_count(migrated_database_url, draft.lease, occupied.lease, ready.lease) == 0


def test_new_baseline_supersedes_only_when_dated_later_and_only_once(
    migrated_database_url: str,
) -> None:
    s = source(migrated_database_url, 10, 2)
    first, first_reading = baseline(migrated_database_url, s, day=date(YEAR, 1, 31), value="90")
    middle_day = date(YEAR, 2, 1)
    middle_reading = reading(migrated_database_url, s, s.electricity, middle_day, "95")
    with pytest.raises(UtilityBaselineConflictError):
        record(s, command(s, (BaselineItem(s.electricity, first_reading),)))
    second, _ = baseline(migrated_database_url, s, supersedes=first)
    assert boundary(migrated_database_url, s) == s.start
    page = service().read(s.prop, s.lease, actor=actor(s))
    statuses = {
        item["event_id"]: item["event_status"] for item in cast(list[dict[str, Any]], page["items"])
    }
    assert statuses == {str(first): "SUPERSEDED", str(second): "CURRENT"}
    earlier = (BaselineItem(s.electricity, middle_reading),)
    with pytest.raises(UtilityBaselineInvalidError):
        record(s, command(s, earlier, day=middle_day, supersedes=second))
    with pytest.raises(UtilityBaselineConflictError):
        record(s, command(s, earlier, day=middle_day, supersedes=first))


def test_baseline_that_would_split_an_existing_period_is_rejected(
    migrated_database_url: str,
) -> None:
    s = source(migrated_database_url, 11, 2)
    start = reading(migrated_database_url, s, s.electricity, date(YEAR, 1, 20), "50")
    end = reading(migrated_database_url, s, s.electricity, date(YEAR, 1, 30), "60")
    finalize(s, start, end)
    with psycopg.connect(migrated_database_url) as owner:
        with pytest.raises(psycopg.errors.CheckViolation, match="split"):
            owner.execute(
                "INSERT INTO app.utility_baseline_events(id,property_id,lease_id,unit_id,"
                "baseline_date,reason,evidence_reference,occurred_at,actor_id) "
                "VALUES (%s,%s,%s,%s,%s,'reason','evidence',clock_timestamp(),%s)",
                (uuid4(), s.prop, s.lease, s.unit, date(YEAR, 1, 25), s.human),
            )
    record(s, command(s, (BaselineItem(s.electricity, end),), day=date(YEAR, 1, 30)))
    assert boundary(migrated_database_url, s) == date(YEAR, 1, 31)


def test_baseline_moves_the_responsibility_boundary_for_new_leases_only(
    migrated_database_url: str,
) -> None:
    with_baseline = source(migrated_database_url, 12, 2)
    baseline(migrated_database_url, with_baseline, day=date(YEAR, 1, 25))
    without = source(migrated_database_url, 13, 2)
    stable = "SELECT app.utility_responsibility_window_is_stable(%s,%s,%s)"
    window = (date(YEAR, 1, 26), date(YEAR, 2, 28))
    assert one(migrated_database_url, stable, with_baseline.unit, *window) == (True,)
    assert one(migrated_database_url, stable, without.unit, *window) == (False,)
    assert boundary(migrated_database_url, without) is None
    occupy(migrated_database_url, with_baseline, date(YEAR, 2, 10))


def test_first_partial_period_is_billed_once_for_a_lease_that_stays_several_months(
    migrated_database_url: str,
) -> None:
    s = source(migrated_database_url, 14, 3)
    _, baseline_reading = baseline(migrated_database_url, s)
    march_end = reading(migrated_database_url, s, s.electricity, date(YEAR, 3, 31), "140")
    april_end = reading(migrated_database_url, s, s.electricity, date(YEAR, 4, 30), "200")
    first = finalize(s, baseline_reading, march_end)
    second = finalize(s, march_end, april_end)
    occupy(migrated_database_url, s, date(YEAR, 3, 10))
    partial = run(s, date(YEAR, 3, 3), date(YEAR, 3, 31))
    assert partial.status == "SUCCEEDED", partial
    assert (partial.period_start, partial.period_end) == (date(YEAR, 3, 3), date(YEAR, 3, 31))
    assert [item.outcome for item in partial.attempts[0].items] == ["GENERATED"]
    month = run(s, date(YEAR, 4, 1), date(YEAR, 4, 30))
    assert month.status == "SUCCEEDED", month
    assert [item.outcome for item in month.attempts[0].items] == ["GENERATED"]
    lines = {
        period: one(
            migrated_database_url,
            "SELECT line.period_start,line.period_end,"
            "line.calculation_trace->>'responsible_lease_id' "
            "FROM app.invoice_lines AS line WHERE line.utility_consumption_period_id=%s",
            period,
        )
        for period in (first, second)
    }
    assert lines[first] == (date(YEAR, 3, 3), date(YEAR, 3, 31), str(s.lease))
    assert lines[second] == (date(YEAR, 4, 1), date(YEAR, 4, 30), str(s.lease))
    assert line_count(migrated_database_url, first) == 1
    assert line_count(migrated_database_url, second) == 1


def test_first_partial_period_of_a_lease_that_never_moves_in_is_skipped_not_failed(
    migrated_database_url: str,
) -> None:
    s = source(migrated_database_url, 15, 5)
    _, baseline_reading = baseline(migrated_database_url, s)
    may_end = reading(migrated_database_url, s, s.electricity, date(YEAR, 5, 31), "140")
    period = finalize(s, baseline_reading, may_end)
    result = run(s, date(YEAR, 5, 3), date(YEAR, 5, 31))
    assert result.status == "SUCCEEDED", result
    item = result.attempts[0].items[0]
    assert (item.outcome, item.diagnostic_code, item.invoice_id) == (
        "SKIPPED",
        "NOT_MOVED_IN",
        None,
    )
    assert line_count(migrated_database_url, period) == 0


def test_period_between_tenants_is_property_borne_and_skipped(
    migrated_database_url: str,
) -> None:
    s = source(migrated_database_url, 16, 6)
    previous_final = reading(migrated_database_url, s, s.electricity, date(YEAR, 5, 31), "80")
    _, baseline_reading = baseline(migrated_database_url, s, value="85")
    between = finalize(s, previous_final, baseline_reading)
    result = run(s, date(YEAR, 6, 1), date(YEAR, 6, 2))
    assert result.status == "SUCCEEDED", result
    item = result.attempts[0].items[0]
    assert (item.outcome, item.diagnostic_code) == ("SKIPPED", "PROPERTY_BORNE_CONSUMPTION")
    assert line_count(migrated_database_url, between) == 0


def test_lease_without_baseline_keeps_its_exact_monthly_run_results(
    migrated_database_url: str,
) -> None:
    covered = source(migrated_database_url, 17, 7)
    occupy(migrated_database_url, covered, covered.start)
    start = reading(migrated_database_url, covered, covered.electricity, covered.baseline_day, "10")
    end = reading(migrated_database_url, covered, covered.electricity, date(YEAR, 7, 31), "50")
    period = finalize(covered, start, end)
    billed = run(covered, date(YEAR, 7, 3), date(YEAR, 7, 31))
    assert billed.status == "SUCCEEDED", billed
    assert billed.attempts[0].items[0].outcome == "GENERATED"
    assert line_count(migrated_database_url, period) == 1

    unoccupied = source(migrated_database_url, 18, 8)
    start = reading(
        migrated_database_url, unoccupied, unoccupied.electricity, unoccupied.baseline_day, "10"
    )
    end = reading(
        migrated_database_url, unoccupied, unoccupied.electricity, date(YEAR, 8, 31), "50"
    )
    failed_period = finalize(unoccupied, start, end)
    failed = run(unoccupied, date(YEAR, 8, 3), date(YEAR, 8, 31))
    assert failed.attempts[0].outcome == "FAILED", failed
    item = failed.attempts[0].items[0]
    assert (item.outcome, item.diagnostic_code) == ("ERROR", "UTILITY_PERSISTENCE_P0002")
    assert line_count(migrated_database_url, failed_period) == 0

    split = source(migrated_database_url, 19, 9)
    start = reading(migrated_database_url, split, split.electricity, split.baseline_day, "10")
    end = reading(migrated_database_url, split, split.electricity, date(YEAR, 9, 30), "50")
    finalize(split, start, end)
    with pytest.raises(psycopg.errors.CheckViolation):
        occupy(migrated_database_url, split, date(YEAR, 9, 10))


def test_baseline_history_is_append_only_and_unreachable_by_runtime_roles(
    migrated_database_url: str,
) -> None:
    s = source(migrated_database_url, 20, 2)
    event, _ = baseline(migrated_database_url, s)
    with psycopg.connect(migrated_database_url) as owner:
        for statement in (
            "UPDATE app.utility_baseline_events SET reason='changed' WHERE id=%s",
            "DELETE FROM app.utility_baseline_events WHERE id=%s",
            "UPDATE app.utility_baseline_items SET reading_version=2 WHERE event_id=%s",
            "DELETE FROM app.utility_baseline_commands WHERE event_id=%s",
        ):
            with pytest.raises(psycopg.Error):
                owner.execute(statement, (event,))
            owner.rollback()
        with pytest.raises(psycopg.Error):
            owner.execute("TRUNCATE app.utility_baseline_items")
        owner.rollback()
    for url in (runtime_database_url(), financial_database_url()):
        with psycopg.connect(url) as connection:
            for table in NEW_TABLES:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(f"SELECT 1 FROM app.{table} LIMIT 1")
                connection.rollback()
    with psycopg.connect(runtime_database_url()) as runtime:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            runtime.execute(
                "SELECT app.utility_baseline_record(%s,%s,%s,%s,%s,%s,%s)",
                (s.prop, s.lease, s.human, uuid4(), "0" * 64, "{}", "request"),
            )


def test_utility_baseline_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261006_71")
    assert revision is not None and revision.down_revision == "20261005_70"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
