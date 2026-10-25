"""Real PostgreSQL coverage of the late Utility run (V1-056 slice 12b; DL-071 answer 18).

A Utility period finalized after a SUCCEEDED run for its dates is billed by the scheduled
worker's late Utility run, once and never twice. Tests use 2017, a year no other suite runs.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.billing_run import (
    BillingRunCommand,
    BillingRunConflict,
    BillingRunDetail,
    BillingRunInvalid,
    PostgresBillingRunService,
)
from property_rental.final_utility_invoice import CatchUpUtilityInvoice
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.invoice import INVOICE_ISSUE_CAPABILITY
from test_final_utility_invoice_migration import invoices, issuer
from test_invoice_migration import financial_database_url
from test_invoice_migration import migrated_database_url as migrated_database_url
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
from test_utility_unbilled_periods_migration import unbilled

Y = 2017
START = date(Y, 5, 3)
END = date(Y, 5, 31)
CANDIDATES = "SELECT * FROM app.scheduled_late_utility_candidates(%s,%s,%s,%s)"


def pair(
    url: str, slot: int, end_value: str = "140", *, moved_in: bool = True
) -> tuple[Source, UUID]:
    """A baseline Lease occupied after its baseline, with its May period finalized."""
    s = source(url, slot, 5, year=Y)
    _, base = baseline(url, s)
    period = finalize(s, base, reading(url, s, s.electricity, END, end_value))
    if moved_in:
        occupy(url, s, date(Y, 5, 10))
    return s, period


def candidates(s: Source) -> list[tuple[date, date, date, str, UUID | None]]:
    with psycopg.connect(financial_database_url()) as connection:
        rows = connection.execute(CANDIDATES, (s.prop, s.worker, database_now(), 100)).fetchall()
    return [
        (row[0], row[1], row[2], str(row[3]), None if row[4] is None else UUID(str(row[4])))
        for row in rows
        if (row[1], row[2]) == (START, END)
    ]


def late_run(
    s: Source,
    business_date: date,
    key: str | None = None,
    idempotency_key: UUID | None = None,
    invocation_source: str = "SCHEDULED",
) -> BillingRunDetail:
    # The scheduled worker, or a person through the API (billed by the same service principal).
    api = invocation_source == "API"
    requester = AuthenticatedActor(
        str(s.human if api else s.worker),
        frozenset({CapabilityGrant("billing.generate", frozenset({str(s.prop)}))}),
    )
    service = PostgresBillingRunService(
        financial_database_url(), api_service_actor_id=s.worker if api else None
    )
    return service.execute(
        BillingRunCommand(
            property_id=s.prop,
            run_kind="UTILITIES",
            logical_run_key=key or f"utilities-late/{START}/{END}/{business_date}",
            business_date=business_date,
            period_start=START,
            period_end=END,
            idempotency_key=idempotency_key or uuid4(),
        ),
        actor=requester,
        invocation_source=invocation_source,
    )


def predecessor(url: str, run_id: UUID) -> UUID | None:
    value = one(url, "SELECT predecessor_run_id FROM app.billing_runs WHERE id=%s", run_id)[0]
    return None if value is None else UUID(str(value))


def test_a_period_finalized_after_its_run_is_billed_once_by_a_late_run(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    on_time, on_time_period = pair(url, 1)
    # Not moved in at the first run (skipped NOT_MOVED_IN), moved in before the late run.
    waiting, waiting_period = pair(url, 4, "145", moved_in=False)
    with pytest.raises(BillingRunInvalid) as early:
        # No run of these dates has succeeded yet: a late run is refused.
        late_run(on_time, END, f"utilities-late/{START}/{END}/early")
    assert getattr(early.value.__cause__, "sqlstate", None) == "55000"
    root = run(on_time, START, END)
    assert root.status == "SUCCEEDED"
    assert candidates(on_time) == []
    occupy(url, waiting, date(Y, 5, 10))
    # A late period staff already billed with the catch-up command is not in a late run.
    caught, caught_period = pair(url, 5, "155")
    invoices().catch_up(
        caught.prop,
        caught.lease,
        CatchUpUtilityInvoice(uuid4(), uuid4(), caught_period),
        actor=issuer(caught.human, caught.prop, INVOICE_ISSUE_CAPABILITY),
        request_id="late-run-test",
    )
    late, late_period = pair(url, 2, "150")
    assert unbilled(late)[str(late_period)]["gap_reason"] == "LATE_AFTER_SUCCEEDED_RUN"
    listed = candidates(late)
    assert len(listed) == 1
    business_date, _, _, key, resumed = listed[0]
    # The key names the run it continues.
    assert key == f"utilities-late/{START}/{END}/{business_date}/{root.id}" and resumed is None

    with pytest.raises(BillingRunInvalid) as api_call:
        # Only the scheduled worker starts a late run.
        late_run(late, business_date, f"utilities-late/{START}/{END}/api", None, "API")
    assert getattr(api_call.value.__cause__, "sqlstate", None) == "22023"
    command_key = uuid4()
    billed = late_run(late, business_date, key, command_key)
    assert billed.status == "SUCCEEDED"
    assert predecessor(url, billed.id) == root.id
    outcomes = {
        item.source_id: (item.outcome, item.diagnostic_code) for item in billed.attempts[0].items
    }
    # Only the late period: the periods the first run billed or skipped are not tried again,
    # so the moved-in period is left to the catch-up command; the caught-up one has its line.
    assert outcomes == {late_period: ("GENERATED", None)}
    assert line_count(url, late_period) == 1 and line_count(url, on_time_period) == 1
    assert line_count(url, waiting_period) == 0 and str(waiting_period) in unbilled(waiting)
    assert line_count(url, caught_period) == 1
    # The on-time Due Date (5 June) has passed: the late Invoice is due the Property's
    # configured days after its issue date, the catch-up command's rule.
    assert one(
        url,
        "SELECT invoice.invoice_date,"
        "invoice.due_date=invoice.invoice_date+property.one_time_charge_due_days,"
        "invoice.due_date_rule,invoice.due_date_source "
        "FROM app.invoice_lines AS line JOIN app.invoices AS invoice ON invoice.id=line.invoice_id "
        "JOIN app.properties AS property ON property.id=%s "
        "WHERE line.utility_consumption_period_id=%s",
        late.prop,
        late_period,
    ) == (business_date, True, "ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS", "BR-UTIL-021")
    assert str(late_period) not in unbilled(late)
    assert candidates(late) == []
    # The same command replays the same run; its logical key under another command is refused;
    # another late run of the dates bills nothing again.
    assert late_run(late, business_date, key, command_key).id == billed.id
    with pytest.raises(BillingRunConflict):
        late_run(late, business_date, key)
    again = late_run(late, business_date, f"utilities-late/{START}/{END}/again-{uuid4().hex[:8]}")
    assert predecessor(url, again.id) == billed.id
    assert again.status == "SUCCEEDED" and again.attempts[0].items == ()
    assert line_count(url, late_period) == 1 and line_count(url, on_time_period) == 1


def test_late_candidates_are_financial_only_and_bounded(migrated_database_url: str) -> None:
    signature = "app.scheduled_late_utility_candidates(uuid,uuid,timestamp with time zone,integer)"
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT has_function_privilege('prm_financial',%s,'EXECUTE'),"
            "has_function_privilege('prm_runtime',%s,'EXECUTE'),"
            "has_function_privilege('prm_bootstrap',%s,'EXECUTE'),"
            "has_function_privilege('public',%s,'EXECUTE'),"
            "(SELECT prosecdef FROM pg_proc WHERE oid=%s::regprocedure)",
            (signature, signature, signature, signature, signature),
        ).fetchone() == (True, False, False, False, True)
    s = source(migrated_database_url, 3, 6, year=Y)
    with psycopg.connect(financial_database_url()) as connection:
        for limit in (0, 101, None):
            with pytest.raises(psycopg.Error) as refused:
                connection.execute(CANDIDATES, (s.prop, s.worker, database_now(), limit))
            assert refused.value.sqlstate == "22023"
            connection.rollback()
