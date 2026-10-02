"""Overlapping Utility runs, unbilled periods and the catch-up command (slice 7b).

Run tests use 2018, a year no other suite runs. Final-Invoice tests use a real departed Lease
with dates relative to the business date.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.billing_run import (
    BillingRunCommand,
    PostgresBillingRunService,
)
from property_rental.final_utility_invoice import (
    CatchUpUtilityInvoice,
    FinalUtilityInvoiceAuthorizationError,
    FinalUtilityInvoiceConflictError,
    FinalUtilityInvoiceNotFoundError,
    PostgresUnbilledUtilityPeriodsService,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.invoice import INVOICE_ISSUE_CAPABILITY
from property_rental.utility import (
    UTILITY_CALCULATE_CAPABILITY,
    FinalizeActualConsumptionCommand,
    PostgresUtilityService,
)
from property_rental.utility_api import UTILITY_READ_CAPABILITY
from test_final_utility_invoice_migration import (
    create_final,
    departed,
    final_reading,
    invoices,
    issuer,
    record_final,
)
from test_invoice_migration import (
    financial_database_url,
    register_billing_service_principal,
    runtime_database_url,
)
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_move_out_final_inputs_migration import used
from test_utility_baseline_migration import (
    Source,
    baseline,
    database_now,
    finalize,
    line_count,
    occupy,
    one,
    reading,
    run,
    source,
)
from test_utility_consumption_migration import replace_failed_meter

Y = 2018


def pair(
    url: str, slot: int, month: int, end_day: int, end_value: str = "140"
) -> tuple[Source, UUID]:
    """A baseline Lease occupied after its baseline, with its first partial period finalized."""
    s = source(url, slot, month, year=Y)
    _, base = baseline(url, s)
    end = reading(url, s, s.electricity, date(Y, month, end_day), end_value)
    period = finalize(s, base, end)
    occupy(url, s, date(Y, month, 10))
    return s, period


def covering(url: str, slot: int, month: int, last_day: date) -> tuple[Source, UUID]:
    """A Lease with no baseline whose period is the whole month that ends on last_day."""
    s = source(url, slot, month, year=Y)
    occupy(url, s, s.start)
    first = reading(url, s, s.electricity, last_day.replace(day=1) - timedelta(days=1), "10")
    end = reading(url, s, s.electricity, last_day, "50")
    return s, finalize(s, first, end)


def unbilled(s: Source) -> dict[str, dict[str, Any]]:
    page = PostgresUnbilledUtilityPeriodsService(runtime_database_url()).read(
        s.prop, actor=issuer(s.human, s.prop, UTILITY_READ_CAPABILITY)
    )
    return {item["period_id"]: item for item in cast(list[dict[str, Any]], page["items"])}


def test_partial_and_monthly_utility_runs_coexist_in_either_order_and_bill_each_period_once(
    migrated_database_url: str,
) -> None:
    monthly, monthly_period = covering(migrated_database_url, 1, 2, date(Y, 3, 31))
    partial, partial_period = pair(migrated_database_url, 2, 3, 31)
    first = run(monthly, date(Y, 3, 1), date(Y, 3, 31))
    second = run(partial, date(Y, 3, 3), date(Y, 3, 31))
    assert first.status == "SUCCEEDED" and second.status == "SUCCEEDED"
    assert [i.outcome for i in first.attempts[0].items] == ["GENERATED"]
    assert [i.outcome for i in second.attempts[0].items] == ["GENERATED"]
    partial_first, early = pair(migrated_database_url, 3, 4, 30)
    monthly_second, late = covering(migrated_database_url, 4, 3, date(Y, 4, 30))
    assert run(partial_first, date(Y, 4, 3), date(Y, 4, 30)).status == "SUCCEEDED"
    assert run(monthly_second, date(Y, 4, 1), date(Y, 4, 30)).status == "SUCCEEDED"
    for period in (monthly_period, partial_period, early, late):
        assert line_count(migrated_database_url, period) == 1
    definition = one(
        migrated_database_url,
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conname='billing_runs_period_no_overlap'",
    )[0]
    assert "RENT" in definition


def test_late_period_is_listed_billed_only_by_explicit_catch_up_and_never_twice(
    migrated_database_url: str,
) -> None:
    on_time, on_time_period = pair(migrated_database_url, 5, 5, 31)
    assert run(on_time, date(Y, 5, 3), date(Y, 5, 31)).status == "SUCCEEDED"
    late, late_period = pair(migrated_database_url, 6, 5, 31, "150")
    listed = unbilled(late)
    assert str(on_time_period) not in listed
    entry = listed[str(late_period)]
    assert (entry["gap_reason"], entry["can_catch_up"], entry["lease_id"]) == (
        "LATE_AFTER_SUCCEEDED_RUN",
        True,
        str(late.lease),
    )
    assert line_count(migrated_database_url, late_period) == 0
    who = issuer(late.human, late.prop, INVOICE_ISSUE_CAPABILITY)
    invoices().catch_up(
        late.prop,
        late.lease,
        CatchUpUtilityInvoice(uuid4(), uuid4(), late_period),
        actor=who,
        request_id="late-test",
    )
    assert line_count(migrated_database_url, late_period) == 1
    assert str(late_period) not in unbilled(late)
    with pytest.raises(FinalUtilityInvoiceConflictError) as again:
        invoices().catch_up(
            late.prop,
            late.lease,
            CatchUpUtilityInvoice(uuid4(), uuid4(), late_period),
            actor=who,
            request_id="late-test",
        )
    assert again.value.reason == "UTILITY_PERIOD_ALREADY_INVOICED"
    assert one(
        migrated_database_url,
        "SELECT count(*) FROM pg_constraint WHERE conrelid='app.invoice_lines'::regclass "
        "AND contype='u' AND pg_get_constraintdef(oid) LIKE '%%utility_consumption_period_id%%'",
    ) == (1,)
    with psycopg.connect(migrated_database_url) as owner:
        row = owner.execute(
            "SELECT unit_id,start_date,end_date,start_reading_id,end_reading_id "
            "FROM app.utility_consumption_periods WHERE id=%s",
            (late_period,),
        ).fetchone()
        assert row is not None
        with pytest.raises(psycopg.Error):
            owner.execute(
                "INSERT INTO app.utility_consumption_periods(id,unit_id,utility_type,start_date,"
                "end_date,start_reading_id,end_reading_id,calculation_kind,consumption_quantity,"
                "calculation_trace,finalized_at,finalized_by) VALUES (%s,%s,'ELECTRICITY',%s,%s,"
                "%s,%s,'ACTUAL',50,'{}',clock_timestamp(),%s)",
                (uuid4(), row[0], row[1], row[2], row[3], row[4], late.human),
            )


def test_unbilled_list_shows_not_moved_in_periods_and_hides_periods_awaiting_their_run(
    migrated_database_url: str,
) -> None:
    _, waiting_period = pair(migrated_database_url, 7, 7, 31)
    s = source(migrated_database_url, 8, 6, year=Y)
    _, base = baseline(migrated_database_url, s)
    end = reading(migrated_database_url, s, s.electricity, date(Y, 6, 30), "140")
    skipped = finalize(s, base, end)
    assert run(s, date(Y, 6, 3), date(Y, 6, 30)).status == "SUCCEEDED"
    by_id = unbilled(s)
    assert by_id[str(skipped)]["gap_reason"] == "NOT_MOVED_IN"
    assert by_id[str(skipped)]["can_catch_up"] is False
    assert str(waiting_period) not in by_id
    reader = PostgresUnbilledUtilityPeriodsService(runtime_database_url())
    page = reader.read(s.prop, actor=issuer(s.human, s.prop, UTILITY_READ_CAPABILITY), limit=1)
    assert page["creates_invoice"] is False and page["limit"] == 1
    with pytest.raises(FinalUtilityInvoiceNotFoundError):
        reader.read(s.prop, actor=issuer(s.human, s.prop, INVOICE_ISSUE_CAPABILITY))
    with pytest.raises(FinalUtilityInvoiceAuthorizationError):
        invoices().catch_up(
            s.prop,
            s.lease,
            CatchUpUtilityInvoice(uuid4(), uuid4(), skipped),
            actor=issuer(s.human, s.prop, UTILITY_READ_CAPABILITY),
            request_id="late-test",
        )


def test_final_invoice_after_a_meter_replaced_after_the_baseline_starts_at_its_installation(
    migrated_database_url: str,
) -> None:
    leaver = departed(migrated_database_url, 1, 3)
    dep = leaver.dep
    day = leaver.start + timedelta(days=1)
    replacement, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=dep.human,
        unit_id=dep.unit,
        failed_meter_id=dep.electricity,
        failure_date=day,
        replacement_date=day,
    )
    final = final_reading(migrated_database_url, leaver, replacement, "30")
    event = record_final(leaver, (used(replacement, final),))
    result = create_final(leaver, event)
    assert len(result["period_ids"]) == 1 and len(result["created_period_ids"]) == 1
    row = one(
        migrated_database_url,
        "SELECT period.start_date,period.end_date,period.consumption_quantity,reading.meter_id "
        "FROM app.utility_consumption_periods AS period "
        "JOIN app.utility_readings AS reading ON reading.id=period.start_reading_id "
        "WHERE period.id=%s",
        UUID(result["created_period_ids"][0]),
    )
    assert row[:2] == (dep.move_out_date, dep.move_out_date)
    assert row[2] == 30 and row[3] == replacement


def test_final_invoice_drops_a_period_the_monthly_run_already_billed(
    migrated_database_url: str,
) -> None:
    leaver = departed(migrated_database_url, 2, 3)
    dep = leaver.dep
    mid_day = leaver.start + timedelta(days=1)
    mid = final_reading(migrated_database_url, leaver, dep.electricity, "120", mid_day)
    base = one(
        migrated_database_url,
        "SELECT reading_id FROM app.utility_baseline_items WHERE meter_id=%s",
        dep.electricity,
    )[0]
    early = uuid4()
    PostgresUtilityService(financial_database_url(), dep.prop, dep.human).finalize_actual(
        FinalizeActualConsumptionCommand(
            idempotency_key=uuid4(),
            consumption_period_id=early,
            unit_id=dep.unit,
            utility_type="ELECTRICITY",
            start_reading_id=base,
            end_reading_id=mid,
            finalized_at=database_now(),
        ),
        actor=issuer(dep.human, dep.prop, UTILITY_CALCULATE_CAPABILITY),
    )
    with psycopg.connect(migrated_database_url) as owner:
        worker = register_billing_service_principal(
            owner, property_id=dep.prop, created_by=dep.human
        )
    detail = PostgresBillingRunService(financial_database_url()).execute(
        BillingRunCommand(
            property_id=dep.prop,
            run_kind="UTILITIES",
            logical_run_key=f"utilities/final-drop/{uuid4()}",
            business_date=mid_day,
            period_start=mid_day,
            period_end=mid_day,
            idempotency_key=uuid4(),
        ),
        actor=AuthenticatedActor(
            str(worker),
            frozenset({CapabilityGrant("billing.generate", frozenset({str(dep.prop)}))}),
        ),
        invocation_source="SCHEDULED",
    )
    assert detail.status == "SUCCEEDED"
    assert {i.outcome for i in detail.attempts[0].items if i.source_id == early} == {"GENERATED"}
    assert line_count(migrated_database_url, early) == 1
    electricity = final_reading(migrated_database_url, leaver, dep.electricity, "150")
    event = record_final(leaver, (used(dep.electricity, electricity),))
    result = create_final(leaver, event)
    assert str(early) not in result["period_ids"] and len(result["period_ids"]) == 1
    assert line_count(migrated_database_url, early) == 1


def test_utility_unbilled_migration_is_forward_only_and_read_is_runtime_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261008_73")
    assert revision is not None and revision.down_revision == "20261007_72"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
    with psycopg.connect(financial_database_url()) as financial:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            financial.execute("SELECT app.utility_unbilled_periods(%s,%s,1,0)", (uuid4(), uuid4()))
