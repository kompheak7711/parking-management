"""Recurring-only Rent nonpayment from the 1st; Initial Rent alert and no late fee."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from payment_test_support import seed_payment
from property_rental.billing import PostgresRentBillingService
from property_rental.late_payment import (
    DecisionOutcome,
    FinalizeLatePaymentDecisionCommand,
    LatePaymentConflictError,
    PostgresLatePaymentService,
)
from property_rental.lease_enforcement import (
    NONPAYMENT_OPEN,
    NONPAYMENT_READ,
    LeaseEnforcementAuthorizationError,
    LeaseEnforcementConflictError,
    NonpaymentEventKind,
    OpenRentNonpaymentCase,
    PostgresLeaseEnforcementService,
    RecordRentNonpaymentEvent,
)
from property_rental.lease_enforcement_context import EnforcementPage, PostgresEnforcementContext
from property_rental.payment_allocation import PostAllocationsCommand
from test_billing_service_migration import (
    authenticated,
    financial_database_url,
    initial_command,
    recurring_command,
    runtime_database_url,
    setup_billing_source,
)
from test_invoice_migration import create_recurring_rent_invoice, setup_signed_lease
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_late_payment_migration import late_payment_actor, setup_invoice
from test_lease_enforcement_migration import source as recurring_source
from test_lease_enforcement_migration import staff
from test_migrations import _temporary_migration_database
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import service as allocation_service

PHNOM_PENH = ZoneInfo("Asia/Phnom_Penh")
RECORDED = "SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY t.id),'[]'::jsonb) FROM app.{} t"
RECORDED_TABLES = (
    "rent_nonpayment_cases",
    "rent_nonpayment_events",
    "late_payment_decisions",
    "late_payment_charges",
)
TENANCY = (
    "SELECT to_jsonb(l),to_jsonb(u) FROM app.leases l "
    "JOIN app.units u ON u.id=l.unit_id WHERE l.id=%s"
)


def enforcement(runtime: str | None = None, financial: str | None = None) -> Any:
    return PostgresLeaseEnforcementService(
        runtime or runtime_database_url(), financial or financial_database_url()
    )


def record(
    flow: Any, prop: UUID, lease: UUID, case: UUID, human: UUID, kind: NonpaymentEventKind
) -> dict[str, object]:
    request = RecordRentNonpaymentEvent(
        uuid4(),
        kind,
        "Authorized documented action",
        "Notice-001" if kind is NonpaymentEventKind.TWENTY_DAY_WARNING else None,
        "Delivered to Customer",
        "Management instruction" if kind is NonpaymentEventKind.AUTHORIZED_FOLLOW_UP else None,
    )
    result = flow.record_event(
        prop, lease, case, request, actor=staff(human, prop), request_id="event"
    )
    return cast(dict[str, object], result.body["data"])


def open_case(flow: Any, prop: UUID, lease: UUID, line: UUID, human: UUID) -> UUID:
    result = flow.open_case(
        prop,
        lease,
        OpenRentNonpaymentCase(uuid4(), line, "Open Rent case"),
        actor=staff(human, prop),
        request_id="open",
    )
    return UUID(str(cast(dict[str, object], result.body["data"])["id"]))


def at_midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=PHNOM_PENH)


def today(url: str) -> date:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT timezone('Asia/Phnom_Penh',clock_timestamp())::date"
        ).fetchone()
    assert row is not None and isinstance(row[0], date)
    return row[0]


def initial_invoice(
    url: str, start: date, *, financial: str | None = None
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    with psycopg.connect(url) as connection:
        human, prop, _, lease, occupancy = setup_billing_source(
            connection,
            configure_trash=False,
            configure_internet=False,
            move_in_date=start,
            lease_end_date=start.replace(year=start.year + 1),
        )
    issued = PostgresRentBillingService(
        financial or financial_database_url(), prop, human
    ).generate(
        initial_command(lease, occupancy, period_start=start, issued_at=at_midnight(start)),
        actor=authenticated(human, prop),
    )
    with psycopg.connect(url) as connection:
        line = connection.execute(
            "SELECT id FROM app.invoice_lines WHERE invoice_id=%s AND category='RENT'",
            (issued.invoice_id,),
        ).fetchone()
    assert line is not None
    return human, prop, lease, issued.invoice_id, UUID(str(line[0]))


def pay_line(
    prop: UUID, human: UUID, customer: UUID, invoice: UUID, line: UUID, amount: int, url: str
) -> None:
    with psycopg.connect(url) as connection:
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=amount
        )
    allocation_service().post(
        prop,
        payment,
        PostAllocationsCommand(
            uuid4(),
            {
                "mode": "DESIGNATED",
                "designation_reference": "Rent instruction",
                "targets": [
                    {
                        "invoice_id": str(invoice),
                        "amount_usd_cents": amount,
                        "details": [{"invoice_line_id": str(line), "amount_usd_cents": amount}],
                    }
                ],
            },
        ),
        actor=allocation_actor(human, prop),
    )


def test_day_twenty_and_thirty_count_from_the_first_at_phnom_penh_midnight(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, _, customer, lease = setup_signed_lease(
            connection, start_date=date(2026, 1, 1), end_date=date(2028, 12, 31)
        )
        cases = []
        for period, day_thirty in (
            (date(2026, 8, 1), date(2026, 8, 30)),
            (date(2027, 2, 1), date(2027, 3, 2)),
            (date(2028, 2, 1), date(2028, 3, 1)),
        ):
            invoice, _ = create_recurring_rent_invoice(
                connection,
                actor_id=human,
                customer_id=customer,
                lease_id=lease,
                period_start=period,
            )
            cases.append((invoice, period.replace(day=20), day_thirty))
        query = (
            "SELECT app.rent_nonpayment_milestone_eligible(%s,app.rent_nonpayment_day_zero(%s),"
            "%s,1,false)"
        )
        for invoice, day_twenty, day_thirty in cases:
            for kind, day in (
                ("TWENTY_DAY_WARNING", day_twenty),
                ("THIRTY_DAY_SERIOUS_DEFAULT", day_thirty),
            ):
                boundary = at_midnight(day)
                assert connection.execute(query, (kind, invoice, boundary)).fetchone() == (True,)
                assert connection.execute(
                    query, (kind, invoice, boundary - timedelta(microseconds=1))
                ).fetchone() == (False,)


def test_initial_rent_cannot_open_a_case_by_command_or_storage(migrated_database_url: str) -> None:
    start = today(migrated_database_url) - timedelta(days=40)
    human, prop, lease, invoice, line = initial_invoice(migrated_database_url, start)
    with pytest.raises(LeaseEnforcementConflictError):
        open_case(enforcement(), prop, lease, line, human)
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error) as rejected:
            connection.execute(
                "INSERT INTO app.rent_nonpayment_cases(id,lease_id,customer_id,invoice_id,"
                "rent_invoice_line_id,due_date_snapshot,opened_at,opened_by) "
                "SELECT %s,lease_id,customer_id,id,%s,due_date,clock_timestamp(),%s "
                "FROM app.invoices WHERE id=%s",
                (uuid4(), line, human, invoice),
            )
    assert rejected.value.sqlstate == "23514"


def test_mixed_recurring_invoice_cures_rent_and_rejects_day_thirty(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, lease, occupancy = setup_billing_source(connection)
    billing = PostgresRentBillingService(financial_database_url(), prop, human)
    billing.generate(initial_command(lease, occupancy), actor=authenticated(human, prop))
    # A 27 July Lease Start's Initial Invoice covers August, so bill September.
    september = billing.generate(
        recurring_command(
            lease,
            period_start=date(2026, 9, 1),
            issued_at=datetime(2026, 8, 24, 17, 0, 1, tzinfo=UTC),
        ),
        actor=authenticated(human, prop),
    )
    with psycopg.connect(migrated_database_url) as connection:
        lines: dict[str, UUID] = dict(
            connection.execute(
                "SELECT category,id FROM app.invoice_lines WHERE invoice_id=%s "
                "ORDER BY line_sequence DESC",
                (september.invoice_id,),
            ).fetchall()
        )
        # The generator stamps issued_at with the real clock, so check the day count on the
        # September Invoice directly: 20 September is day 20 and not yet day 30.
        milestone = (
            "SELECT app.rent_nonpayment_milestone_eligible(%s,app.rent_nonpayment_day_zero(%s),"
            "%s,1,false)"
        )
        day_twenty = at_midnight(date(2026, 9, 20))
        assert connection.execute(
            milestone, ("TWENTY_DAY_WARNING", september.invoice_id, day_twenty)
        ).fetchone() == (True,)
        assert connection.execute(
            milestone, ("THIRTY_DAY_SERIOUS_DEFAULT", september.invoice_id, day_twenty)
        ).fetchone() == (False,)
    flow = enforcement()
    with pytest.raises(LeaseEnforcementConflictError):
        open_case(flow, prop, lease, lines["SERVICE_CHARGES"], human)
    case = open_case(flow, prop, lease, lines["RENT"], human)
    record(flow, prop, lease, case, human, NonpaymentEventKind.TWENTY_DAY_WARNING)
    pay_line(
        prop,
        human,
        customer,
        september.invoice_id,
        lines["RENT"],
        september.rent_usd_cents,
        migrated_database_url,
    )
    snapshot = flow.read(prop, lease, "CASE", case_id=case, actor=staff(human, prop))
    assessment = cast(dict[str, object], snapshot["assessment"])
    assert assessment["cure_eligible"] is True
    assert assessment["thirty_day_default_eligible"] is False
    record(flow, prop, lease, case, human, NonpaymentEventKind.CURE)
    with pytest.raises(LeaseEnforcementConflictError):
        record(flow, prop, lease, case, human, NonpaymentEventKind.THIRTY_DAY_SERIOUS_DEFAULT)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT status FROM app.invoices WHERE id=%s", (september.invoice_id,)
        ).fetchone() == ("PARTIALLY_PAID",)


def test_day_thirty_default_changes_no_lease_unit_or_occupancy(migrated_database_url: str) -> None:
    human, prop, _, lease, _, line = recurring_source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        before = connection.execute(TENANCY, (lease,)).fetchone()
        occupancies = connection.execute(
            "SELECT count(*) FROM app.occupancies WHERE lease_id=%s", (lease,)
        ).fetchone()
    flow = enforcement()
    case = open_case(flow, prop, lease, line, human)
    record(flow, prop, lease, case, human, NonpaymentEventKind.TWENTY_DAY_WARNING)
    record(flow, prop, lease, case, human, NonpaymentEventKind.THIRTY_DAY_SERIOUS_DEFAULT)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(TENANCY, (lease,)).fetchone() == before
        assert (
            connection.execute(
                "SELECT count(*) FROM app.occupancies WHERE lease_id=%s", (lease,)
            ).fetchone()
            == occupancies
        )


def alert_ids(prop: UUID, human: UUID) -> set[str]:
    context = PostgresEnforcementContext(runtime_database_url())
    found: set[str] = set()
    after: UUID | None = None
    while True:
        page = context.initial_rent_alerts(
            prop, actor=staff(human, prop, NONPAYMENT_READ), page=EnforcementPage(100, after)
        )
        items = cast(list[dict[str, object]], page["items"])
        found |= {str(item["invoice_id"]) for item in items}
        if page["next_cursor"] is None:
            return found
        after = UUID(str(page["next_cursor"]))


def test_initial_rent_alert_starts_the_day_after_the_due_date_and_ends_when_paid(
    migrated_database_url: str,
) -> None:
    current = today(migrated_database_url)
    due_today = initial_invoice(migrated_database_url, current - timedelta(days=5))
    human, prop, _, invoice, line = initial_invoice(
        migrated_database_url, current - timedelta(days=6)
    )
    alerts = alert_ids(prop, human)
    assert str(invoice) in alerts and str(due_today[3]) not in alerts
    with pytest.raises(LeaseEnforcementAuthorizationError):
        PostgresEnforcementContext(runtime_database_url()).initial_rent_alerts(
            prop, actor=staff(human, prop, NONPAYMENT_OPEN)
        )
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT i.customer_id,app.invoice_line_outstanding(%s) FROM app.invoices i "
            "WHERE i.id=%s",
            (line, invoice),
        ).fetchone()
    assert row is not None
    pay_line(prop, human, row[0], invoice, line, int(row[1]), migrated_database_url)
    assert str(invoice) not in alert_ids(prop, human)


def alert_lines(url: str, prop: UUID) -> set[str]:
    listed: set[str] = set()
    after: str | None = None
    with psycopg.connect(url) as connection:
        while True:
            row = connection.execute(
                "SELECT app.rent_nonpayment_alert_page(%s,100,%s)", (prop, after)
            ).fetchone()
            assert row is not None
            listed |= {str(item["rent_invoice_line_id"]) for item in row[0]["items"]}
            after = row[0]["next_cursor"]
            if after is None:
                return listed


def test_nonpayment_alerts_and_sources_list_only_recurring_rent(
    migrated_database_url: str,
) -> None:
    human, prop, lease, _, initial_line = initial_invoice(
        migrated_database_url, today(migrated_database_url) - timedelta(days=60)
    )
    _, recurring_prop, _, _, _, recurring_line = recurring_source(migrated_database_url)
    sources = PostgresEnforcementContext(runtime_database_url()).read(
        prop, "SOURCES", actor=staff(human, prop), lease_id=lease
    )
    assert all(
        item["rent_invoice_line_id"] != str(initial_line)
        for item in cast(list[dict[str, object]], sources["items"])
    )
    listed = alert_lines(migrated_database_url, recurring_prop)
    assert str(recurring_line) in listed and str(initial_line) not in listed


def test_initial_rent_review_blocks_late_fee_and_recurring_does_not(
    migrated_database_url: str,
) -> None:
    human, prop, _, invoice, _ = initial_invoice(
        migrated_database_url, today(migrated_database_url) - timedelta(days=30)
    )
    late = PostgresLatePaymentService(runtime_database_url(), financial_database_url())
    review = late.review(invoice, actor=late_payment_actor(human, prop))
    assert "INITIAL_RENT_NO_LATE_PAYMENT" in cast(list[str], review["blocking_conditions"])
    assert review["eligible"] is False
    with pytest.raises(LatePaymentConflictError):
        late.finalize_decision(
            prop,
            invoice,
            FinalizeLatePaymentDecisionCommand(
                uuid4(), DecisionOutcome.WAIVED, 0, "Initial Rent has no late fee"
            ),
            actor=late_payment_actor(human, prop),
        )
    with psycopg.connect(migrated_database_url) as connection:
        r_human, r_prop, _, r_invoice, _ = setup_invoice(connection, period_start=date(2026, 5, 1))
    recurring = late.review(r_invoice, actor=late_payment_actor(r_human, r_prop))
    assert "INITIAL_RENT_NO_LATE_PAYMENT" not in cast(list[str], recurring["blocking_conditions"])


def recorded(url: str) -> dict[str, Any]:
    with psycopg.connect(url) as connection:
        return {
            table: connection.execute(RECORDED.format(table)).fetchone()
            for table in RECORDED_TABLES
        }


def test_forward_upgrade_keeps_recorded_history_and_limits_initial_cases(
    migrated_database_url: str,
) -> None:
    assert migrated_database_url
    with _temporary_migration_database("rent_nonpayment_recurring_only") as temporary:
        name = conninfo_to_dict(temporary)["dbname"]
        runtime = make_conninfo(runtime_database_url(), dbname=name)
        financial = make_conninfo(financial_database_url(), dbname=name)
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        alembic_command.upgrade(config, "20261003_67")
        flow = enforcement(runtime, financial)
        late = PostgresLatePaymentService(runtime, financial)
        with psycopg.connect(temporary) as connection:
            human, prop, _, invoice, _ = setup_invoice(connection, period_start=date(2026, 5, 1))
        review = late.review(invoice, actor=late_payment_actor(human, prop))
        late.finalize_decision(
            prop,
            invoice,
            FinalizeLatePaymentDecisionCommand(
                uuid4(),
                DecisionOutcome.CONFIRMED_DEFAULT,
                cast(dict[str, int], review["calculated_default_amount"])["minor_units"],
                "Approved default",
            ),
            actor=late_payment_actor(human, prop),
        )
        r_human, r_prop, _, r_lease, _, r_line = recurring_source(temporary)
        r_case = open_case(flow, r_prop, r_lease, r_line, r_human)
        record(flow, r_prop, r_lease, r_case, r_human, NonpaymentEventKind.TWENTY_DAY_WARNING)
        i_human, i_prop, i_lease, _, i_line = initial_invoice(
            temporary, today(temporary) - timedelta(days=60), financial=financial
        )
        i_case = open_case(flow, i_prop, i_lease, i_line, i_human)
        record(flow, i_prop, i_lease, i_case, i_human, NonpaymentEventKind.TWENTY_DAY_WARNING)
        before = recorded(temporary)
        alembic_command.upgrade(config, "head")
        assert recorded(temporary) == before
        with pytest.raises(LeaseEnforcementConflictError):
            record(
                flow,
                i_prop,
                i_lease,
                i_case,
                i_human,
                NonpaymentEventKind.THIRTY_DAY_SERIOUS_DEFAULT,
            )
        follow_up = record(
            flow, i_prop, i_lease, i_case, i_human, NonpaymentEventKind.AUTHORIZED_FOLLOW_UP
        )
        assert follow_up["event_kind"] == "AUTHORIZED_FOLLOW_UP"
        record(
            flow, r_prop, r_lease, r_case, r_human, NonpaymentEventKind.THIRTY_DAY_SERIOUS_DEFAULT
        )


def test_recurring_only_rent_nonpayment_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261004_68")
    assert revision is not None and revision.down_revision == "20261003_67"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
