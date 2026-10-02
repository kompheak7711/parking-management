"""Final and catch-up Utility Invoices on real PostgreSQL.

Catch-up tests use 2019 (a year no other suite runs) with their own months, because the monthly
Utility run rejects overlapping run ranges. Final-Invoice tests build a real departed Lease whose
dates are relative to the business date and never run the monthly run.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.final_utility_invoice import (
    CatchUpUtilityInvoice,
    CreateFinalUtilityInvoice,
    FinalUtilityInvoiceAuthorizationError,
    FinalUtilityInvoiceConflictError,
    FinalUtilityInvoiceInvalidError,
    FinalUtilityInvoiceKeyReused,
    FinalUtilityInvoiceNotFoundError,
    PostgresFinalUtilityInvoiceService,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.invoice import INVOICE_ISSUE_CAPABILITY
from property_rental.move_in import MoveInOccupant
from property_rental.physical_move_out import EndedOccupancy, RecordPhysicalMoveOut
from property_rental.utility import (
    UTILITY_CALCULATE_CAPABILITY,
    FinalizeActualConsumptionCommand,
    PostgresUtilityService,
)
from property_rental.utility_baseline import (
    BASELINE_RECORD,
    BaselineItem,
    PostgresUtilityBaselineService,
    RecordUtilityBaseline,
)
from test_invoice_migration import financial_database_url, runtime_database_url
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import setup_historical_move_in
from test_move_out_final_inputs_migration import Departure, missing, used
from test_move_out_final_inputs_migration import command as final_input_command
from test_move_out_final_inputs_migration import record as record_final_inputs
from test_physical_move_out_migration import record as record_departure
from test_termination_deposit_migration import terminate
from test_utility_baseline_migration import (
    YEAR,
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
from test_utility_meter_migration import add_meter, add_reading


def issuer(human: UUID, prop: UUID, *capabilities: str) -> AuthenticatedActor:
    caps = capabilities or (INVOICE_ISSUE_CAPABILITY, UTILITY_CALCULATE_CAPABILITY)
    return AuthenticatedActor(
        str(human), frozenset(CapabilityGrant(c, frozenset({str(prop)})) for c in caps)
    )


def invoices() -> PostgresFinalUtilityInvoiceService:
    return PostgresFinalUtilityInvoiceService(financial_database_url())


def today(url: str, prop: UUID) -> tuple[date, int]:
    row = one(
        url,
        "SELECT timezone(timezone_name,clock_timestamp())::date,one_time_charge_due_days "
        "FROM app.properties WHERE id=%s",
        prop,
    )
    return cast(date, row[0]), int(row[1])


def invoice_row(url: str, invoice: UUID) -> tuple[Any, ...]:
    return one(
        url,
        "SELECT status,primary_category,due_date,due_date_rule,due_date_source,"
        "due_date_override_reason,due_date_set_by,original_total_usd_cents "
        "FROM app.invoices WHERE id=%s",
        invoice,
    )


def data_of(body: dict[str, object]) -> dict[str, Any]:
    return cast(dict[str, Any], body["data"])


# ---- catch-up for a period skipped as NOT_MOVED_IN (2019 fixtures) -------------------------


def test_catch_up_bills_a_not_moved_in_period_once_then_the_monthly_run_continues(
    migrated_database_url: str,
) -> None:
    s = source(migrated_database_url, 21, 10)
    _, base = baseline(migrated_database_url, s)
    october_end = reading(migrated_database_url, s, s.electricity, date(YEAR, 10, 31), "140")
    november_end = reading(migrated_database_url, s, s.electricity, date(YEAR, 11, 30), "200")
    first = finalize(s, base, october_end)
    second = finalize(s, october_end, november_end)
    skipped = run(s, date(YEAR, 10, 3), date(YEAR, 10, 31))
    assert skipped.status == "SUCCEEDED"
    assert skipped.attempts[0].items[0].diagnostic_code == "NOT_MOVED_IN"
    occupy(migrated_database_url, s, date(YEAR, 11, 5))
    who = issuer(s.human, s.prop, INVOICE_ISSUE_CAPABILITY)
    invoice = uuid4()
    command = CatchUpUtilityInvoice(uuid4(), invoice, first)
    result = invoices().catch_up(s.prop, s.lease, command, actor=who, request_id="catch-up-test")
    assert (
        invoices().catch_up(s.prop, s.lease, command, actor=who, request_id="catch-up-test")
        == result
    )
    business_date, days = today(migrated_database_url, s.prop)
    row = invoice_row(migrated_database_url, invoice)
    assert row[:5] == (
        "UNPAID",
        "UTILITIES",
        business_date + timedelta(days=days),
        "ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS",
        "BR-UTIL-021",
    )
    assert row[5] is None and row[6] is None
    assert line_count(migrated_database_url, first) == 1
    assert one(
        migrated_database_url,
        "SELECT line.period_start,line.period_end,line.calculation_trace->>'responsible_lease_id' "
        "FROM app.invoice_lines AS line WHERE line.utility_consumption_period_id=%s",
        first,
    ) == (date(YEAR, 10, 3), date(YEAR, 10, 31), str(s.lease))
    assert data_of(result.body)["total_usd_cents"] == row[7]
    with pytest.raises(FinalUtilityInvoiceConflictError) as again:
        invoices().catch_up(
            s.prop,
            s.lease,
            CatchUpUtilityInvoice(uuid4(), uuid4(), first),
            actor=who,
            request_id="catch-up-test",
        )
    assert again.value.reason == "UTILITY_PERIOD_ALREADY_INVOICED"
    month = run(s, date(YEAR, 11, 1), date(YEAR, 11, 30))
    assert month.status == "SUCCEEDED" and month.attempts[0].items[0].outcome == "GENERATED"
    assert line_count(migrated_database_url, first) == 1
    assert line_count(migrated_database_url, second) == 1


def test_catch_up_refuses_a_lease_that_never_moved_in_and_honors_an_authorized_due_date(
    migrated_database_url: str,
) -> None:
    s = source(migrated_database_url, 22, 12)
    _, base = baseline(migrated_database_url, s)
    december_end = reading(migrated_database_url, s, s.electricity, date(YEAR, 12, 31), "140")
    period = finalize(s, base, december_end)
    assert run(s, date(YEAR, 12, 3), date(YEAR, 12, 31)).status == "SUCCEEDED"
    who = issuer(s.human, s.prop, INVOICE_ISSUE_CAPABILITY)
    with pytest.raises(FinalUtilityInvoiceInvalidError) as never:
        invoices().catch_up(
            s.prop,
            s.lease,
            CatchUpUtilityInvoice(uuid4(), uuid4(), period),
            actor=who,
            request_id="catch-up-test",
        )
    assert never.value.reason == "UTILITY_NOT_MOVED_IN"
    assert line_count(migrated_database_url, period) == 0
    occupy(migrated_database_url, s, date(YEAR, 12, 20))
    with pytest.raises(FinalUtilityInvoiceAuthorizationError):
        invoices().catch_up(
            s.prop,
            s.lease,
            CatchUpUtilityInvoice(uuid4(), uuid4(), period),
            actor=issuer(s.human, s.prop, UTILITY_CALCULATE_CAPABILITY),
            request_id="catch-up-test",
        )
    business_date, _ = today(migrated_database_url, s.prop)
    with pytest.raises(FinalUtilityInvoiceInvalidError):
        invoices().catch_up(
            s.prop,
            s.lease,
            CatchUpUtilityInvoice(
                uuid4(),
                uuid4(),
                period,
                due_date=business_date - timedelta(days=1),
                due_date_reason="Back-dated",
            ),
            actor=who,
            request_id="catch-up-test",
        )
    assert line_count(migrated_database_url, period) == 0
    invoice, key = uuid4(), uuid4()
    override = business_date + timedelta(days=30)
    command = CatchUpUtilityInvoice(
        key, invoice, period, due_date=override, due_date_reason="Owner agreed a later date"
    )
    invoices().catch_up(s.prop, s.lease, command, actor=who, request_id="catch-up-test")
    row = invoice_row(migrated_database_url, invoice)
    assert (row[2], row[5], row[6]) == (override, "Owner agreed a later date", s.human)
    with pytest.raises(FinalUtilityInvoiceKeyReused):
        invoices().catch_up(
            s.prop,
            s.lease,
            CatchUpUtilityInvoice(
                key, uuid4(), period, due_date=override, due_date_reason="Owner agreed a later date"
            ),
            actor=who,
            request_id="catch-up-test",
        )
    with pytest.raises(FinalUtilityInvoiceNotFoundError):
        invoices().catch_up(
            s.prop,
            uuid4(),
            CatchUpUtilityInvoice(uuid4(), uuid4(), period),
            actor=who,
            request_id="catch-up-test",
        )


# ---- final Utility Invoice for a real departed Lease ---------------------------------------


@dataclass(frozen=True)
class Leaver:
    dep: Departure
    start: date
    move_in: date
    customer: UUID


def departed(url: str, slot: int) -> Leaver:
    """A signed Lease with an electricity baseline that then moved in, left and was terminated."""
    move_flow, staff, move = setup_historical_move_in(
        url, signed_day_offset=-1, receipt_day_offset=-1
    )
    human, prop, lease = move_flow.actor_id, move_flow.property_id, move.lease_id
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT unit_id,start_date,primary_tenant_id FROM app.leases WHERE id=%s", (lease,)
        ).fetchone()
        assert row is not None
        unit, start, customer = cast(UUID, row[0]), cast(date, row[1]), cast(UUID, row[2])
        electricity = add_meter(
            connection, actor_id=human, unit_id=unit, installed_date=start - timedelta(days=30)
        )
        connection.execute(
            "INSERT INTO app.utility_rates(id,property_id,utility_type,measurement_unit_code,"
            "rate_usd_per_unit,effective_date,notice_at,notice_evidence,actor_id) "
            "VALUES (%s,%s,'ELECTRICITY','KWH',0.25,%s,TIMESTAMPTZ '2015-01-01 00:00:00+07',"
            "'OWNER-NOTICE',%s)",
            (uuid4(), prop, date(2015, 2, slot), human),
        )
        base_e = add_reading(
            connection,
            actor_id=human,
            meter_id=electricity,
            reading_date=start,
            reading_value="100",
        )
        connection.commit()
    PostgresUtilityBaselineService(runtime_database_url(), financial_database_url()).record(
        prop,
        lease,
        RecordUtilityBaseline(
            uuid4(),
            uuid4(),
            start,
            (BaselineItem(electricity, base_e),),
            "Baseline recorded after cleaning and repair",
            "Handover sheet 17",
        ),
        actor=issuer(human, prop, BASELINE_RECORD),
        request_id="baseline-test",
    )
    move = replace(move, occupants=(MoveInOccupant(uuid4(), customer),))
    result = move_flow.complete(move, actor=staff)
    termination = terminate(url, human, prop, lease, move.actual_move_in_date + timedelta(days=2))
    with psycopg.connect(url) as connection:
        versions = connection.execute(
            "SELECT l.version,u.version FROM app.leases l JOIN app.units u ON u.id=l.unit_id "
            "WHERE l.id=%s",
            (lease,),
        ).fetchone()
    assert versions is not None
    request = RecordPhysicalMoveOut(
        uuid4(),
        uuid4(),
        termination,
        int(versions[0]),
        int(versions[1]),
        move.actual_move_in_date + timedelta(days=1),
        "CLEANING",
        tuple(EndedOccupancy(identity, 1) for identity in result.occupancy_ids),
        "Observed departure confirmed",
        "Authorized move-out",
        "Synthetic departure evidence",
    )
    record_departure(prop, lease, human, request)
    dep = Departure(
        human,
        prop,
        lease,
        unit,
        request.event_id,
        request.actual_move_out_date,
        electricity,
        electricity,
        request,
    )
    return Leaver(dep, start, move.actual_move_in_date, customer)


def final_reading(
    url: str, leaver: Leaver, meter: UUID, value: str, day: date | None = None
) -> UUID:
    with psycopg.connect(url) as connection:
        return add_reading(
            connection,
            actor_id=leaver.dep.human,
            meter_id=meter,
            reading_date=day or leaver.dep.move_out_date,
            reading_value=value,
        )


def record_final(leaver: Leaver, items: Any, *, supersedes: UUID | None = None) -> UUID:
    event = uuid4()
    record_final_inputs(
        leaver.dep, final_input_command(leaver.dep, items, supersedes=supersedes, event=event)
    )
    return event


def create_final(
    leaver: Leaver, event: UUID, *, invoice: UUID | None = None, key: UUID | None = None, **due: Any
) -> dict[str, Any]:
    dep = leaver.dep
    response = invoices().create_final(
        dep.prop,
        dep.lease,
        CreateFinalUtilityInvoice(key or uuid4(), invoice or uuid4(), event, **due),
        actor=issuer(dep.human, dep.prop),
        request_id="final-test",
    )
    return data_of(response.body)


def test_final_invoice_bills_a_lease_that_leaves_in_its_first_month_once(
    migrated_database_url: str,
) -> None:
    leaver = departed(migrated_database_url, 24)
    dep = leaver.dep
    electricity = final_reading(migrated_database_url, leaver, dep.electricity, "150")
    event = record_final(leaver, (used(dep.electricity, electricity),))
    invoice, key = uuid4(), uuid4()
    first = create_final(leaver, event, invoice=invoice, key=key)
    assert create_final(leaver, event, invoice=invoice, key=key) == first
    business_date, days = today(migrated_database_url, dep.prop)
    row = invoice_row(migrated_database_url, invoice)
    assert row[:5] == (
        "UNPAID",
        "UTILITIES",
        business_date + timedelta(days=days),
        "ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS",
        "BR-UTIL-021",
    )
    assert len(first["created_period_ids"]) == 1 and len(first["period_ids"]) == 1
    lines = one(
        migrated_database_url,
        "SELECT count(*),min(period_start),max(period_end),sum(amount_usd_cents) "
        "FROM app.invoice_lines WHERE invoice_id=%s",
        invoice,
    )
    assert lines == (1, leaver.start + timedelta(days=1), dep.move_out_date, row[7])
    assert row[7] == first["total_usd_cents"] and row[7] > 0
    for period in first["period_ids"]:
        assert line_count(migrated_database_url, UUID(period)) == 1
    assert one(
        migrated_database_url,
        "SELECT count(*) FROM app.audit_events WHERE action='utility.final_invoice.create' "
        "AND entity_id=%s",
        invoice,
    ) == (1,)
    with pytest.raises(FinalUtilityInvoiceConflictError):
        create_final(leaver, event)
    with pytest.raises(FinalUtilityInvoiceKeyReused):
        create_final(leaver, uuid4(), invoice=invoice, key=key)


def test_final_invoice_also_bills_an_earlier_finalized_period_nobody_billed(
    migrated_database_url: str,
) -> None:
    leaver = departed(migrated_database_url, 25)
    dep = leaver.dep
    mid_day = leaver.start + timedelta(days=1)
    mid = final_reading(migrated_database_url, leaver, dep.electricity, "120", mid_day)
    with psycopg.connect(migrated_database_url) as connection:
        base = connection.execute(
            "SELECT reading_id FROM app.utility_baseline_items WHERE meter_id=%s",
            (dep.electricity,),
        ).fetchone()
    assert base is not None
    early = uuid4()
    PostgresUtilityService(financial_database_url(), dep.prop, dep.human).finalize_actual(
        FinalizeActualConsumptionCommand(
            idempotency_key=uuid4(),
            consumption_period_id=early,
            unit_id=dep.unit,
            utility_type="ELECTRICITY",
            start_reading_id=cast(UUID, base[0]),
            end_reading_id=mid,
            finalized_at=database_now(),
        ),
        actor=issuer(dep.human, dep.prop),
    )
    electricity = final_reading(migrated_database_url, leaver, dep.electricity, "150")
    event = record_final(leaver, (used(dep.electricity, electricity),))
    invoice = uuid4()
    result = create_final(leaver, event, invoice=invoice)
    assert len(result["period_ids"]) == 2 and len(result["created_period_ids"]) == 1
    assert str(early) in result["period_ids"] and str(early) not in result["created_period_ids"]
    assert line_count(migrated_database_url, early) == 1
    assert one(
        migrated_database_url, "SELECT count(*) FROM app.invoice_lines WHERE invoice_id=%s", invoice
    ) == (2,)


def test_final_invoice_waits_for_every_meter_and_a_superseded_event_cannot_be_billed(
    migrated_database_url: str,
) -> None:
    leaver = departed(migrated_database_url, 26)
    dep = leaver.dep
    pending = record_final(leaver, (missing(dep.electricity),))
    with pytest.raises(FinalUtilityInvoiceInvalidError) as waiting:
        create_final(leaver, pending)
    assert waiting.value.reason == "UTILITY_UNRESOLVED_FINAL_INPUT"
    assert one(
        migrated_database_url,
        "SELECT count(*) FROM app.invoices WHERE lease_id=%s AND primary_category='UTILITIES'",
        dep.lease,
    ) == (0,)
    electricity = final_reading(migrated_database_url, leaver, dep.electricity, "150")
    resolved = record_final(leaver, (used(dep.electricity, electricity),), supersedes=pending)
    with pytest.raises(FinalUtilityInvoiceConflictError):
        create_final(leaver, pending)
    invoice = uuid4()
    assert len(create_final(leaver, resolved, invoice=invoice)["period_ids"]) == 1


def test_final_invoice_honors_an_authorized_due_date_and_needs_both_capabilities(
    migrated_database_url: str,
) -> None:
    leaver = departed(migrated_database_url, 27)
    dep = leaver.dep
    electricity = final_reading(migrated_database_url, leaver, dep.electricity, "150")
    event = record_final(leaver, (used(dep.electricity, electricity),))
    with pytest.raises(FinalUtilityInvoiceAuthorizationError):
        invoices().create_final(
            dep.prop,
            dep.lease,
            CreateFinalUtilityInvoice(uuid4(), uuid4(), event),
            actor=issuer(dep.human, dep.prop, INVOICE_ISSUE_CAPABILITY),
            request_id="final-test",
        )
    business_date, _ = today(migrated_database_url, dep.prop)
    with pytest.raises(FinalUtilityInvoiceInvalidError):
        create_final(
            leaver,
            event,
            due_date=business_date - timedelta(days=1),
            due_date_reason="Back-dated",
        )
    invoice = uuid4()
    override = business_date + timedelta(days=21)
    create_final(
        leaver, event, invoice=invoice, due_date=override, due_date_reason="Owner agreed a date"
    )
    row = invoice_row(migrated_database_url, invoice)
    assert (row[2], row[5], row[6]) == (override, "Owner agreed a date", dep.human)


def test_utility_invoice_history_is_append_only_and_unreachable_by_runtime_roles(
    migrated_database_url: str,
) -> None:
    s = source(migrated_database_url, 23, 11)
    with psycopg.connect(migrated_database_url) as owner:
        for statement in (
            "UPDATE app.utility_invoice_commands SET action='FINAL'",
            "DELETE FROM app.utility_invoice_commands",
            "TRUNCATE app.utility_invoice_commands",
        ):
            with pytest.raises(psycopg.Error):
                owner.execute(statement)
            owner.rollback()
    for url in (runtime_database_url(), financial_database_url()):
        with psycopg.connect(url) as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT 1 FROM app.utility_invoice_commands LIMIT 1")
            connection.rollback()
    with psycopg.connect(runtime_database_url()) as runtime:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            runtime.execute(
                "SELECT app.utility_catch_up_invoice_create(%s,%s,%s,%s,%s,%s,%s)",
                (s.prop, s.lease, s.human, uuid4(), "0" * 64, "{}", "request"),
            )
    with psycopg.connect(financial_database_url()) as financial:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            financial.execute(
                "SELECT app.utility_invoice_build("
                "%s,%s,%s,%s,%s,'FINAL',ARRAY[]::uuid[],NULL,NULL)",
                (s.prop, s.lease, s.human, uuid4(), uuid4()),
            )


def test_final_utility_invoice_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261007_72")
    assert revision is not None and revision.down_revision == "20261006_71"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
