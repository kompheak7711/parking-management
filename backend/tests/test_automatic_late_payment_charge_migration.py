"""Real PostgreSQL coverage of the automatic late-payment charge (V1-056 slice 11g-1; DL-076
answers 1 to 3, DL-075 answer 1, owner card of 2026-10-25 "No charge").

At 00:00 Property time on the day after an Invoice's Due Date the billing worker's pass adds one
charge of 10 percent of the amount unpaid at that moment, rounded half-up to the cent. An Invoice
already late on the pass's first day gets none; a missed day is caught up with the balance of its
own midnight. Recurring Rent is due on the 5th, so every charge day here is a 6th.

An Invoice is issued now by the shared helper; a test that needs it issued before its charge
moment backdates the issue (and any earlier Adjustment) as the table owner with the table's own
triggers off for that one statement, as other tests backdate rows they cannot reach otherwise.

V1 holds one Property, so every test shares it and its pass history: each test starts and ends
with no pass recorded (the owner removes the rows, triggers off), uses its own Rent month, and
records its own Invoices directly after setting the last finished pass, so other tests' Invoices
never change its result. The database refuses a pass instant older than an hour, so the paging
and counting of a whole pass are covered by ``test_late_payment_job.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from typing import Any, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg
import pytest
from psycopg.types.json import Jsonb

from property_rental.billing_worker import ScheduledBillingWorker
from property_rental.late_payment_job import (
    AutomaticLatePaymentChargeJob,
    LateChargePassError,
    LateChargePassResult,
)
from test_final_settlement_closed_refusal_migration import close, overdue_case
from test_final_settlement_migration import one, today
from test_invoice_migration import (
    create_recurring_rent_invoice,
    financial_database_url,
    register_billing_service_principal,
    runtime_database_url,
    setup_signed_lease,
)
from test_late_payment_migration import migrated_database_url as migrated_database_url
from test_late_payment_migration import setup_invoice
from test_unpaid_initial_termination_migration import signed_with_initial

PHNOM_PENH = ZoneInfo("Asia/Phnom_Penh")
AUTOMATIC = "late_payment.automatic_charge"
REASON = "Automatic late-payment charge (DL-076)"
WINDOW = "SELECT app.automatic_late_payment_charge_window(%s,%s,%s)"
CANDIDATES = "SELECT * FROM app.automatic_late_payment_charge_candidates(%s,%s,%s,%s,%s)"
RECORD = "SELECT app.record_automatic_late_payment_charge(%s,%s,%s,%s,%s,%s)"
RUN = "SELECT app.record_late_payment_charge_run(%s,%s,%s,%s,%s,%s)"
ADJUST = (
    "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adjustment_type,"
    "amount_usd_cents,source_reference,reason,occurred_at,actor_id,authorization_reference) "
    "VALUES (%s,%s,%s,'CREDIT',%s,%s,'Valid amount already applied',"
    "COALESCE(%s,clock_timestamp()),%s,'invoices.adjust')"
)


def moment(due: date) -> datetime:
    """The charge moment of a Due Date: 00:00 Property time on the next day."""
    return datetime.combine(due + timedelta(days=1), time(0), tzinfo=PHNOM_PENH)


def months_ago(url: str, count: int) -> date:
    first = today(url).replace(day=1)
    for _ in range(count):
        first = (first - timedelta(days=1)).replace(day=1)
    return first


def due_of(period: date) -> date:
    return period + timedelta(days=4)


def backdate_issue(url: str, invoice: UUID, issued_at: datetime) -> None:
    with psycopg.connect(url) as owner:
        owner.execute("ALTER TABLE app.invoices DISABLE TRIGGER USER")
        owner.execute(
            "UPDATE app.invoices SET created_at=%s,issued_at=%s WHERE id=%s",
            (issued_at, issued_at, invoice),
        )
        owner.execute("ALTER TABLE app.invoices ENABLE TRIGGER USER")


def adjust(
    url: str,
    human: UUID,
    invoice: UUID,
    line: UUID,
    amount: int,
    occurred_at: datetime | None = None,
) -> None:
    """A CREDIT Adjustment now, or backdated to occurred_at (before the charge moment)."""
    row = (uuid4(), invoice, line, amount, f"paid/{uuid4()}", occurred_at, human)
    with psycopg.connect(url) as owner:
        if occurred_at is None:
            owner.execute(ADJUST, row)
        else:
            owner.execute("ALTER TABLE app.invoice_adjustments DISABLE TRIGGER USER")
            owner.execute(ADJUST, row)
            owner.execute("ALTER TABLE app.invoice_adjustments ENABLE TRIGGER USER")
        owner.execute("SET CONSTRAINTS ALL IMMEDIATE")


def clear_runs(url: str) -> None:
    with psycopg.connect(url) as owner:
        owner.execute("ALTER TABLE app.late_payment_charge_runs DISABLE TRIGGER USER")
        owner.execute("DELETE FROM app.late_payment_charge_runs")
        owner.execute("ALTER TABLE app.late_payment_charge_runs ENABLE TRIGGER USER")


@pytest.fixture(autouse=True)
def no_pass_yet(migrated_database_url: str) -> Iterator[None]:
    clear_runs(migrated_database_url)
    yield
    clear_runs(migrated_database_url)


def seed_last_run(url: str, prop: UUID, service: UUID, day: date) -> None:
    """The last finished pass was on `day` (and none later), so a pass covers the charge days
    after it."""
    clear_runs(url)
    with psycopg.connect(url) as owner:
        owner.execute(
            "INSERT INTO app.late_payment_charge_runs(property_id,business_date,system_actor_id,"
            "recorded_at,charged_count,no_amount_count,skipped_count) "
            "VALUES (%s,%s,%s,clock_timestamp(),0,0,0)",
            (prop, day, service),
        )


def overdue(url: str, period: date, *, backdated: bool = True) -> dict[str, Any]:
    """A signed Lease with an unpaid recurring Rent Invoice of 800.00 for the month starting
    `period`, issued before its charge moment, and a new billing service principal."""
    with psycopg.connect(url) as connection:
        human, prop, customer, invoice, line = setup_invoice(connection, period_start=period)
        service = register_billing_service_principal(connection, property_id=prop, created_by=human)
        connection.commit()
    if backdated:
        backdate_issue(url, invoice, moment(due_of(period)) - timedelta(days=10))
    return {
        "human": human,
        "prop": prop,
        "customer": customer,
        "invoice": invoice,
        "line": line,
        "service": service,
        "due": due_of(period),
    }


def job(case: dict[str, Any]) -> AutomaticLatePaymentChargeJob:
    return AutomaticLatePaymentChargeJob(
        financial_database_url(), property_id=case["prop"], actor_id=case["service"]
    )


def record(case: dict[str, Any], invoice: UUID | None = None) -> dict[str, Any]:
    with psycopg.connect(financial_database_url()) as financial:
        row = financial.execute(
            RECORD,
            (case["prop"], case["service"], invoice or case["invoice"], uuid4(), uuid4(), uuid4()),
        ).fetchone()
    assert row is not None
    return cast(dict[str, Any], row[0])


def candidates(case: dict[str, Any]) -> set[UUID]:
    """Every candidate of a pass now (paged by id, as the job does)."""
    found: set[UUID] = set()
    after: UUID | None = None
    with psycopg.connect(financial_database_url()) as financial:
        now = financial.execute("SELECT clock_timestamp()").fetchone()
        assert now is not None
        while True:
            page = [
                cast(UUID, row[0])
                for row in financial.execute(
                    CANDIDATES, (case["prop"], case["service"], now[0], after, 1000)
                ).fetchall()
            ]
            found.update(page)
            if len(page) < 1000:
                return found
            after = page[-1]


def decision_of(url: str, invoice: UUID) -> tuple[Any, ...] | None:
    with psycopg.connect(url) as connection:
        return connection.execute(
            "SELECT overdue_balance_at_assessment_usd_cents,default_rate_basis_points,"
            "calculated_default_amount_usd_cents,approved_amount_usd_cents,decision_outcome,"
            "assessed_at,finalized_by,finalized_by_service,reason,authorization_reference "
            "FROM app.late_payment_decisions WHERE source_invoice_id=%s",
            (invoice,),
        ).fetchone()


def charge_of(url: str, invoice: UUID) -> int | None:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT original_amount_usd_cents FROM app.late_payment_charges "
            "WHERE source_invoice_id=%s",
            (invoice,),
        ).fetchone()
    return None if row is None else cast(int, row[0])


def runs_of(url: str, prop: UUID) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(
            "SELECT business_date FROM app.late_payment_charge_runs "
            "WHERE property_id=%s ORDER BY business_date",
            (prop,),
        ).fetchall()


def refusal(url: str, sql: str, *parameters: object) -> tuple[str | None, str | None]:
    with pytest.raises(psycopg.Error) as failure, psycopg.connect(url) as connection:
        connection.execute(sql, parameters)
    return failure.value.sqlstate, failure.value.diag.message_primary


def test_an_invoice_late_before_the_first_pass_gets_no_charge_and_a_day_is_done_once(
    migrated_database_url: str,
) -> None:
    """Owner card of 2026-10-25 ("No charge"): before any pass the first charge day is today,
    so an Invoice already late gets no charge, from the pass or from a direct call; a finished
    day is recorded once and not read again; the next day starts after it."""
    url = migrated_database_url
    case = overdue(url, months_ago(url, 5))

    assert case["invoice"] not in candidates(case)
    assert record(case) == {"outcome": "NOT_IN_WINDOW"}
    now = cast(datetime, one(url, "SELECT clock_timestamp()")[0])
    first = job(case).run(as_of=now)
    assert (first.business_date, first.failed) == (today(url), 0)
    assert charge_of(url, case["invoice"]) is None
    # Only a pass in the first 10 seconds of a Property day waits (not ready, nothing recorded).
    assert first.done
    assert runs_of(url, case["prop"]) == [(today(url),)]
    assert job(case).run(as_of=now) == LateChargePassResult(today(url), done=True)
    assert record(case) == {"outcome": "NOT_IN_WINDOW"}
    # A pass instant older than an hour is refused: it could mark past days done.
    assert (
        refusal(
            financial_database_url(),
            RUN,
            case["prop"],
            case["service"],
            now - timedelta(hours=2),
            0,
            0,
            0,
        )[0]
        == "22023"
    )


@pytest.mark.parametrize(
    ("unpaid", "paid_after", "expected"),
    [
        (80_000, 1_000, 8_000),
        (80_000, 79_999, 8_000),
        (12_345, 1_000, 1_235),
        (5, 0, 1),
        (4, 0, None),
        (0, 0, None),
    ],
    ids=[
        "whole",
        "nearly all paid after midnight",
        "half up",
        "half cent up",
        "rounds to nothing",
        "paid on time",
    ],
)
def test_the_charge_is_ten_percent_of_the_amount_unpaid_at_midnight_rounded_half_up(
    migrated_database_url: str, unpaid: int, paid_after: int, expected: int | None
) -> None:
    """DL-076 answers 1 and 2: the amount unpaid at 00:00 counts; money received after it does
    not lower the charge, even when it pays nearly all of the Invoice; a charge that rounds to
    nothing writes no record."""
    url = migrated_database_url
    case = overdue(url, months_ago(url, 1))
    charge_moment = moment(case["due"])
    if unpaid < 80_000:
        adjust(
            url,
            case["human"],
            case["invoice"],
            case["line"],
            80_000 - unpaid,
            charge_moment - timedelta(hours=1),
        )
    if paid_after:
        adjust(url, case["human"], case["invoice"], case["line"], paid_after)
    seed_last_run(url, case["prop"], case["service"], case["due"])
    assert case["invoice"] in candidates(case)

    outcome = record(case)

    if expected is None:
        assert outcome == {"outcome": "NO_AMOUNT"}
        assert decision_of(url, case["invoice"]) is None
        assert charge_of(url, case["invoice"]) is None
        return
    assert outcome["outcome"] == "CHARGED"
    assert outcome["charge"]["original_amount"] == {"currency": "USD", "minor_units": expected}
    # The snapshots name the service as the actor.
    assert outcome["charge"]["created_by"] == str(case["service"])
    assert decision_of(url, case["invoice"]) == (
        unpaid,
        1000,
        expected,
        expected,
        "CONFIRMED_DEFAULT",
        charge_moment,
        None,
        case["service"],
        REASON,
        AUTOMATIC,
    )
    assert charge_of(url, case["invoice"]) == expected
    with psycopg.connect(url) as connection:
        assert connection.execute(
            "SELECT actor_id,action,source,outcome,authorization_reference,"
            "authorization_evidence->>'principal_capability' FROM app.audit_events "
            "WHERE entity_type='late_payment_charge' AND entity_id=("
            "SELECT id FROM app.late_payment_charges WHERE source_invoice_id=%s)",
            (case["invoice"],),
        ).fetchall() == [
            (
                case["service"],
                "late_payment.charge_added",
                "SCHEDULED",
                "SUCCEEDED",
                AUTOMATIC,
                "billing.generate",
            )
        ]
        assert connection.execute(
            "SELECT created_by FROM app.late_payment_charge_financial_position "
            "WHERE source_invoice_id=%s",
            (case["invoice"],),
        ).fetchone() == (case["service"],)
    # One charge per Invoice: a second try adds nothing, and the Invoice leaves the candidates.
    assert record(case) == {"outcome": "ALREADY_ASSESSED"}
    assert case["invoice"] not in candidates(case)


def test_a_missed_day_is_caught_up_with_the_balance_of_its_own_midnight(
    migrated_database_url: str,
) -> None:
    """The worker was off on the charge day: the next pass covers every day since the last one
    and charges the amount unpaid at that day's 00:00, not the amount unpaid now; a day at or
    before the last finished pass is not covered again. Both sides of the boundary: the last
    pass on the charge day itself, then on the Due Date (the day before the charge day)."""
    url = migrated_database_url
    case = overdue(url, months_ago(url, 2))
    adjust(url, case["human"], case["invoice"], case["line"], 70_000)
    seed_last_run(url, case["prop"], case["service"], case["due"] + timedelta(days=1))
    assert case["invoice"] not in candidates(case)
    assert record(case) == {"outcome": "NOT_IN_WINDOW"}

    seed_last_run(url, case["prop"], case["service"], case["due"])
    assert case["invoice"] in candidates(case)
    assert record(case)["outcome"] == "CHARGED"
    assert charge_of(url, case["invoice"]) == 8_000


def test_the_pass_skips_invoices_the_rule_does_not_charge(migrated_database_url: str) -> None:
    """An Invoice issued after its charge moment gets none (reading recorded under DL-076), and
    so do a DRAFT Invoice, Initial Rent (BR-INV-051) and an Invoice of a Lease whose Final
    Settlement is closed (BR-SETTLE-012). Skipped Invoices write nothing."""
    url = migrated_database_url
    late_issue = overdue(url, months_ago(url, 1), backdated=False)
    seed_last_run(url, late_issue["prop"], late_issue["service"], late_issue["due"])
    assert record(late_issue) == {"outcome": "ISSUED_AFTER_CHARGE_TIME"}
    assert decision_of(url, late_issue["invoice"]) is None
    with psycopg.connect(url) as connection:
        human, _prop, customer, lease = setup_signed_lease(
            connection, start_date=date(2025, 1, 1), end_date=date(2027, 12, 31)
        )
        draft, _line = create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=customer,
            lease_id=lease,
            period_start=months_ago(url, 1),
            issue=False,
        )
        connection.commit()
    assert draft not in candidates(late_issue)
    assert record(late_issue, draft) == {"outcome": "NOT_ISSUED_OR_VOID"}

    # BR-INV-051: Initial Rent never gets a late-payment charge.
    initial = signed_with_initial(url, 40)
    with psycopg.connect(url) as connection:
        initial_service = register_billing_service_principal(
            connection, property_id=initial["property"], created_by=initial["actor"]
        )
    initial_case = {"prop": initial["property"], "service": initial_service}
    initial_due = cast(
        date, one(url, "SELECT due_date FROM app.invoices WHERE id=%s", initial["invoice"])[0]
    )
    seed_last_run(url, initial["property"], initial_service, initial_due)
    assert record(initial_case, initial["invoice"]) == {"outcome": "INITIAL_RENT"}
    assert decision_of(url, initial["invoice"]) is None

    case = overdue_case(url)
    undecided = case["undecided"]
    due = cast(date, one(url, "SELECT due_date FROM app.invoices WHERE id=%s", undecided)[0])
    backdate_issue(url, undecided, moment(due) - timedelta(days=10))
    with psycopg.connect(url) as connection:
        service = register_billing_service_principal(
            connection, property_id=case["prop"], created_by=case["human"]
        )
    close(url, case["human"], case["settlement"])
    closed = {"prop": case["prop"], "service": service, "invoice": undecided}
    seed_last_run(url, case["prop"], service, due)
    assert undecided in candidates(closed)
    assert record(closed) == {"outcome": "FINAL_SETTLEMENT_CLOSED"}
    assert decision_of(url, undecided) is None


def test_two_passes_at_once_add_one_charge(migrated_database_url: str) -> None:
    url = migrated_database_url
    case = overdue(url, months_ago(url, 8))
    seed_last_run(url, case["prop"], case["service"], case["due"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(result["outcome"] for result in pool.map(lambda _: record(case), (1, 2)))

    assert outcomes == ["ALREADY_ASSESSED", "CHARGED"]
    with psycopg.connect(url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.late_payment_charges WHERE source_invoice_id=%s",
            (case["invoice"],),
        ).fetchone() == (1,)


def test_the_billing_worker_runs_the_pass_only_while_it_holds_its_lock(
    migrated_database_url: str,
) -> None:
    """The worker runs the charge pass after its billing runs at the real time, only when it
    holds the Property's worker lock, and reports a failed pass without losing its billing
    runs."""
    url = migrated_database_url
    case = overdue(url, months_ago(url, 3))

    class NoBilling:
        """The billing runs are covered by test_billing_run_migration.py."""

        def execute(self, *args: object, **kwargs: object) -> object:
            return "billing run"

    class Pass:
        def __init__(self, failure: Exception | None = None) -> None:
            self.calls: list[datetime] = []
            self.failure = failure

        def run(self, *, as_of: datetime) -> LateChargePassResult:
            self.calls.append(as_of)
            if self.failure is not None:
                raise self.failure
            return LateChargePassResult(today(url), done=True)

    def worker(late: Pass) -> ScheduledBillingWorker:
        return ScheduledBillingWorker(
            financial_database_url(),
            property_id=case["prop"],
            actor_id=case["service"],
            max_catchup_runs=1,
            service=cast(Any, NoBilling()),
            late_charges=late,
        )

    late = Pass()
    result = worker(late).run_once(as_of=datetime(2026, 8, 31, 12, tzinfo=PHNOM_PENH))
    assert result.late_charges == LateChargePassResult(today(url), done=True)
    assert len(late.calls) == 1 and late.calls[0].utcoffset() is not None
    # The real time, not the billing catch-up instant.
    assert late.calls[0] > datetime(2026, 8, 31, 12, tzinfo=PHNOM_PENH)

    locked = Pass()
    with psycopg.connect(financial_database_url()) as holder:
        assert holder.execute(
            "SELECT app.try_scheduled_billing_worker_lock(%s,%s)", (case["prop"], case["service"])
        ).fetchone() == (True,)
        blocked = worker(locked).run_once()
    assert blocked.late_charges is None and locked.calls == []

    for failure, code in (
        (psycopg.errors.LockNotAvailable("busy"), "55P03"),
        (LateChargePassError("unexpected window"), "LateChargePassError"),
    ):
        failed = worker(Pass(failure)).run_once(as_of=datetime(2026, 8, 31, 12, tzinfo=PHNOM_PENH))
        assert (failed.late_charges, failed.late_charges_error) == (None, code)
        # The billing runs of the same pass are still reported.
        assert (failed.current_business_date, failed.runs) == (
            result.current_business_date,
            result.runs,
        )


def test_only_the_property_s_billing_service_runs_the_pass_and_records_are_checked(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = overdue(url, months_ago(url, 7))
    other = overdue(url, months_ago(url, 9))
    with psycopg.connect(url) as owner:
        owner.execute(
            "UPDATE app.billing_service_principals SET lifecycle_state='disabled',"
            "disabled_at=clock_timestamp(),disabled_by=%s WHERE actor_id=%s",
            (other["human"], other["service"]),
        )
    now = cast(datetime, one(url, "SELECT clock_timestamp()")[0])
    needs_service = "The automatic late-payment charge needs the Property's billing service"
    financial = financial_database_url()
    for actor in (case["human"], other["service"]):
        for sql, parameters in (
            (WINDOW, (case["prop"], actor, now)),
            (CANDIDATES, (case["prop"], actor, now, None, 10)),
            (RECORD, (case["prop"], actor, case["invoice"], uuid4(), uuid4(), uuid4())),
            (RUN, (case["prop"], actor, now, 0, 0, 0)),
        ):
            assert refusal(financial, sql, *parameters) == ("42501", needs_service)
    prop, service = case["prop"], case["service"]
    for limit in (0, 1001):
        assert refusal(financial, CANDIDATES, prop, service, now, None, limit)[0] == "22023"
    assert refusal(financial, WINDOW, prop, service, now - timedelta(hours=2))[0] == "22023"
    assert (
        refusal(financial, RECORD, prop, service, case["invoice"], UUID(int=0), uuid4(), uuid4())[0]
        == "22023"
    )
    assert refusal(financial, RECORD, prop, service, uuid4(), uuid4(), uuid4(), uuid4()) == (
        "P4601",
        "Late-payment Invoice was not found",
    )
    # An instant later than the database clock counts as now.
    with psycopg.connect(financial) as connection:
        window = connection.execute(WINDOW, (prop, service, now + timedelta(days=40))).fetchone()
    assert window is not None and window[0]["business_date"] == today(url).isoformat()

    seed_last_run(url, prop, service, case["due"])
    assert record(case)["outcome"] == "CHARGED"
    assert (
        refusal(
            url,
            "UPDATE app.late_payment_charge_runs SET charged_count=9 WHERE property_id=%s",
            prop,
        )[0]
        is not None
    )
    for role_url in (financial, runtime_database_url()):
        assert refusal(role_url, "SELECT count(*) FROM app.late_payment_charge_runs")[0] == "42501"

    # The decision check: an automatic decision must match the rule exactly, a person's decision
    # needs a person, and exactly one actor is named.
    seed_last_run(url, prop, service, other["due"])
    for authorization, amount, message in (
        (AUTOMATIC, 7_999, "Automatic late-payment charge is invalid"),
        ("late_payment.final_decision", 8_000, "A person's late-payment decision needs a person"),
    ):
        decision = uuid4()
        with pytest.raises(psycopg.Error) as invalid, psycopg.connect(url) as owner:
            owner.execute(
                "INSERT INTO app.late_payment_decisions(id,source_invoice_id,customer_id,"
                "source_due_date,overdue_balance_at_assessment_usd_cents,"
                "default_rate_basis_points,calculated_default_amount_usd_cents,decision_outcome,"
                "approved_amount_usd_cents,assessed_at,finalized_at,finalized_by_service,reason,"
                "authorization_reference,calculation_trace) VALUES (%s,%s,%s,%s,80000,1000,%s,"
                "'CONFIRMED_DEFAULT',%s,%s,clock_timestamp(),%s,%s,%s,%s)",
                (
                    decision,
                    other["invoice"],
                    other["customer"],
                    other["due"],
                    amount,
                    amount,
                    moment(other["due"]),
                    service,
                    REASON,
                    authorization,
                    Jsonb({}),
                ),
            )
            owner.execute(
                "INSERT INTO app.late_payment_charges(id,customer_id,source_invoice_id,"
                "late_payment_decision_id,original_amount_usd_cents,payable_at,created_at,"
                "created_by_service) SELECT %s,customer_id,source_invoice_id,id,"
                "approved_amount_usd_cents,finalized_at,finalized_at,finalized_by_service "
                "FROM app.late_payment_decisions WHERE id=%s",
                (uuid4(), decision),
            )
            owner.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert (invalid.value.sqlstate, invalid.value.diag.message_primary) == ("23514", message)
    with pytest.raises(psycopg.Error) as both, psycopg.connect(url) as owner:
        owner.execute(
            "INSERT INTO app.late_payment_decisions(id,source_invoice_id,customer_id,"
            "source_due_date,overdue_balance_at_assessment_usd_cents,default_rate_basis_points,"
            "calculated_default_amount_usd_cents,decision_outcome,approved_amount_usd_cents,"
            "assessed_at,finalized_at,finalized_by,finalized_by_service,reason,"
            "authorization_reference,calculation_trace) VALUES (%s,%s,%s,%s,80000,1000,8000,"
            "'CONFIRMED_DEFAULT',8000,%s,clock_timestamp(),%s,%s,%s,%s,%s)",
            (
                uuid4(),
                other["invoice"],
                other["customer"],
                other["due"],
                moment(other["due"]),
                other["human"],
                service,
                REASON,
                AUTOMATIC,
                Jsonb({}),
            ),
        )
    assert both.value.sqlstate == "23514"

    with psycopg.connect(url) as connection:
        assert connection.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname='late_payment_decisions_rate_whole_percent'"
        ).fetchone() == (
            "CHECK ((((default_rate_basis_points >= 0) AND (default_rate_basis_points <= 1000)) "
            "AND (((default_rate_basis_points)::integer % 100) = 0)))",
        )
        record_function = "app.record_automatic_late_payment_charge(uuid,uuid,uuid,uuid,uuid,uuid)"
        privileges = connection.execute(
            "SELECT has_function_privilege('prm_runtime',%s,'EXECUTE'),"
            "has_function_privilege('prm_financial',%s,'EXECUTE'),"
            "has_function_privilege('prm_financial','app.late_payment_rate_basis_points(uuid,date)',"
            "'EXECUTE'),has_function_privilege('prm_financial',"
            "'app.require_late_payment_charge_job(uuid,uuid)','EXECUTE'),"
            "has_function_privilege('prm_financial',"
            "'app.late_payment_first_charge_day(uuid,timestamp with time zone,text)','EXECUTE'),"
            "has_table_privilege('prm_financial','app.late_payment_charge_runs','INSERT'),"
            "has_table_privilege('prm_bootstrap','app.late_payment_charge_runs','SELECT')",
            (record_function, record_function),
        ).fetchone()
    assert privileges == (False, True, False, False, False, False, False)
    with pytest.raises(psycopg.Error) as runtime, psycopg.connect(runtime_database_url()) as rt:
        rt.execute(WINDOW, (prop, service, now))
    assert runtime.value.sqlstate == "42501"
