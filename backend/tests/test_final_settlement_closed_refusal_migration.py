"""V1-056 sub-slice 8e-1: one-call changes to a closed Final Settlement's obligations are refused.

Owner answer 7 to Q-2026-10-05-20: after closure, VOID, Adjustments (also through the
resolutions), Late-payment Decisions and Charge corrections, and new charges on the Lease are
refused until the slice 10 correction drafts exist; Payments, allocations, Credit applications and
their ordinary reversals stay open. Owner answers to Q-2026-10-06-33: a billing run skips a Lease
whose Settlement is closed, and a VOID of a DRAFT Invoice of that Lease is refused too. Until the
confirm (8e-3) exists, the tests close a Settlement with the owner helper below; the 8a-1 closure
guard allows exactly that one change.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from payment_test_support import seed_payment
from property_rental.billing_run import BillingRunCommand, PostgresBillingRunService
from property_rental.credit import ApplyCreditCommand, ReverseCreditApplicationCommand
from property_rental.final_utility_invoice import FinalUtilityInvoiceConflictError
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.invoice import (
    AdjustInvoiceCommand,
    AdjustmentType,
    CorrectInvoiceDraftCommand,
    CreateInvoiceDraftCommand,
    InvoiceConflictError,
    InvoiceInvalidError,
    IssueInvoiceCommand,
    RecordOneTimeChargeCommand,
    VoidInvoiceCommand,
)
from property_rental.late_payment import (
    CorrectionKind,
    CorrectLatePaymentChargeCommand,
    DecisionOutcome,
    FinalizeLatePaymentDecisionCommand,
    LatePaymentConflictError,
)
from property_rental.payment_allocation import ReverseAllocationCommand, ReversePaymentCommand
from property_rental.unpaid_initial_termination import (
    ResolveNeverMovedInCommand,
    UnpaidInitialTerminationConflictError,
)
from property_rental.utility import (
    UTILITY_CALCULATE_CAPABILITY,
    FinalizeActualConsumptionCommand,
    PostgresUtilityService,
)
from test_billing_run_migration import service_actor
from test_credit_migration import actor as credit_actor
from test_credit_migration import service as credits
from test_final_settlement_draft_migration import leaving_case
from test_final_settlement_migration import one, outstanding, start, today
from test_final_settlement_preview_migration import invoices, key_card
from test_final_utility_invoice_migration import create_final, departed, final_reading, record_final
from test_invoice_migration import (
    create_recurring_rent_invoice,
    financial_database_url,
    invoice_api_actor,
    register_billing_service_principal,
    setup_signed_lease,
)
from test_late_payment_migration import late_payment_actor
from test_late_payment_migration import service as late_payments
from test_lease_lifecycle_migration import actor as unpaid_initial_actor
from test_lease_migration import create_draft, setup_sources, sign_lease
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_out_final_inputs_migration import used
from test_one_time_charges_migration import draft_and_issue
from test_one_time_charges_migration import staff as invoice_staff
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated
from test_payment_allocation_migration import service as allocations
from test_termination_deposit_migration import terminate
from test_unpaid_initial_termination_migration import ALL as UNPAID_INITIAL_CAPABILITIES
from test_unpaid_initial_termination_migration import service as unpaid_initial
from test_unpaid_initial_termination_migration import signed_with_initial
from test_unpaid_initial_termination_migration import terminate as terminate_unpaid
from test_utility_consumption_migration import database_now
from test_utility_meter_migration import add_meter, add_reading

FUNCTION = "app.refuse_closed_final_settlement_change()"
CLOSED = "A closed Final Settlement changes only through a post-settlement correction"
TABLES = (
    "invoice_void_events",
    "invoice_adjustments",
    "invoice_adjustment_reversals",
    "late_payment_decisions",
    "late_payment_charges",
    "late_payment_charge_corrections",
    "invoices",
    "authorized_nonrecurring_obligations",
)
CLOSE = (
    "UPDATE app.final_settlements SET closed_at=clock_timestamp(),closed_by=%s,"
    "source_snapshot='{}'::jsonb,closing_balance_due_usd_cents=0 WHERE id=%s"
)
ONE_TIME_CHARGE = "SELECT app.record_one_time_charge(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"


def close(url: str, human: UUID, settlement: UUID) -> None:
    """The single closure, as the owner; the confirm (8e-3) will write the real one."""
    with psycopg.connect(url) as connection:
        connection.execute(CLOSE, (human, settlement))


def closed_refusal(
    error: type[Exception], call: Callable[..., object], *args: Any, **kwargs: Any
) -> None:
    """The service reports a conflict and the database cause is the closed Settlement."""
    with pytest.raises(error) as failure:
        call(*args, **kwargs)
    cause = failure.value.__cause__
    assert isinstance(cause, psycopg.Error)
    assert (cause.sqlstate, cause.diag.message_primary) == ("P5S01", CLOSED)


def owner_refusal(url: str, sql: str, *parameters: object) -> tuple[Any, Any]:
    with pytest.raises(psycopg.Error) as failure, psycopg.connect(url) as connection:
        connection.execute(sql, parameters)
    return failure.value.sqlstate, failure.value.diag.message_primary


def count(url: str, sql: str, *parameters: object) -> int:
    return int(one(url, sql, *parameters)[0])


def version(url: str, invoice: UUID) -> int:
    return int(one(url, "SELECT version FROM app.invoices WHERE id=%s", invoice)[0])


def invoice_of(url: str, line: UUID) -> UUID:
    return UUID(str(one(url, "SELECT invoice_id FROM app.invoice_lines WHERE id=%s", line)[0]))


def one_time_charge_row(case: dict[str, Any], charge: UUID) -> tuple[object, ...]:
    command = key_card(case["customer"], case["lease"])
    return (
        case["prop"],
        case["human"],
        charge,
        command.category,
        command.customer_id,
        command.lease_id,
        None,
        command.description,
        command.amount_usd_cents,
        command.reason,
        command.evidence_reference,
    )


def test_a_closed_settlement_refuses_one_call_changes_and_keeps_payments_open(
    migrated_database_url: str,
) -> None:
    """Owner answer 7 to Q-2026-10-05-20 (BR-SETTLE-012, BR-SETTLE-013): VOID, Adjustments, new
    charges and Invoice drafts on the Lease are refused once its Settlement is closed, and write
    nothing; while it is open they work as before; Payments, allocations, Credit applications and
    their reversals stay open after closure."""
    url = migrated_database_url
    case = leaving_case(url)
    human, prop, lease, customer = case["human"], case["prop"], case["lease"], case["customer"]
    staff = invoice_api_actor(human, prop)
    other_invoice = invoice_of(url, case["other_line"])
    # While the Settlement is open a new charge with the Lease is recorded as before.
    open_charge = key_card(customer, lease)
    invoices().record_one_time_charge(prop, open_charge, actor=invoice_staff(human, prop))
    close(url, human, case["settlement"])
    before = (
        count(url, "SELECT count(*) FROM app.invoices WHERE lease_id=%s", lease),
        count(
            url,
            "SELECT count(*) FROM app.authorized_nonrecurring_obligations WHERE lease_id=%s",
            lease,
        ),
        count(
            url, "SELECT count(*) FROM app.invoice_adjustments WHERE invoice_id=%s", other_invoice
        ),
        count(
            url, "SELECT count(*) FROM app.invoice_void_events WHERE invoice_id=%s", other_invoice
        ),
        one(url, "SELECT status,version FROM app.invoices WHERE id=%s", other_invoice),
        outstanding(url, case["other_line"]),
    )
    closed_refusal(
        InvoiceConflictError,
        invoices().void,
        prop,
        other_invoice,
        VoidInvoiceCommand(uuid4(), "Charged by mistake", version(url, other_invoice)),
        actor=staff,
    )
    for kind in (AdjustmentType.CREDIT, AdjustmentType.DEBIT):
        closed_refusal(
            InvoiceConflictError,
            invoices().adjust,
            prop,
            other_invoice,
            AdjustInvoiceCommand(
                uuid4(),
                case["other_line"],
                kind,
                100,
                f"after-closure/{uuid4()}",
                "Approved change",
                version(url, other_invoice),
            ),
            actor=staff,
        )
    closed_refusal(
        InvoiceConflictError,
        invoices().record_one_time_charge,
        prop,
        key_card(customer, lease),
        actor=invoice_staff(human, prop),
    )
    # The charge recorded while the Settlement was open cannot be billed on the Lease now.
    closed_refusal(
        InvoiceConflictError,
        invoices().create_draft,
        prop,
        CreateInvoiceDraftCommand(uuid4(), open_charge.charge_id),
        actor=invoice_staff(human, prop),
    )
    after = (
        count(url, "SELECT count(*) FROM app.invoices WHERE lease_id=%s", lease),
        count(
            url,
            "SELECT count(*) FROM app.authorized_nonrecurring_obligations WHERE lease_id=%s",
            lease,
        ),
        count(
            url, "SELECT count(*) FROM app.invoice_adjustments WHERE invoice_id=%s", other_invoice
        ),
        count(
            url, "SELECT count(*) FROM app.invoice_void_events WHERE invoice_id=%s", other_invoice
        ),
        one(url, "SELECT status,version FROM app.invoices WHERE id=%s", other_invoice),
        outstanding(url, case["other_line"]),
    )
    assert after == before
    # Every guarded table refuses at its own trigger, whoever writes, before any other check; the
    # Adjustment reversal has no writer yet, so a later one inherits the refusal.
    adjustment = one(
        url, "SELECT id FROM app.invoice_adjustments WHERE invoice_id=%s", case["initial"]
    )[0]
    for sql, parameters in (
        ("INSERT INTO app.invoices(id,lease_id) VALUES (%s,%s)", (uuid4(), lease)),
        (
            "INSERT INTO app.authorized_nonrecurring_obligations(id,lease_id) VALUES (%s,%s)",
            (uuid4(), lease),
        ),
        (
            "INSERT INTO app.invoice_void_events(id,invoice_id) VALUES (%s,%s)",
            (uuid4(), other_invoice),
        ),
        (
            "INSERT INTO app.invoice_adjustments(id,invoice_id) VALUES (%s,%s)",
            (uuid4(), other_invoice),
        ),
        (
            "INSERT INTO app.invoice_adjustment_reversals(id,invoice_adjustment_id) VALUES (%s,%s)",
            (uuid4(), adjustment),
        ),
        (
            "INSERT INTO app.late_payment_decisions(id,source_invoice_id) VALUES (%s,%s)",
            (uuid4(), other_invoice),
        ),
        (
            "INSERT INTO app.late_payment_charges(id,source_invoice_id) VALUES (%s,%s)",
            (uuid4(), other_invoice),
        ),
    ):
        assert owner_refusal(url, sql, *parameters) == ("P5S01", CLOSED), sql
    # Payments, allocations, Credit applications and their reversals stay open (answer 7).
    with psycopg.connect(url) as connection:
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=1_000
        )
    allocations().post(
        prop,
        payment,
        designated(other_invoice, case["other_line"], 1_000),
        actor=allocation_actor(human, prop),
    )
    assert outstanding(url, case["other_line"]) == 11_500
    allocation = UUID(
        str(one(url, "SELECT id FROM app.payment_allocations WHERE payment_id=%s", payment)[0])
    )
    allocations().reverse_allocation(
        prop,
        allocation,
        ReverseAllocationCommand(uuid4(), "Paid on the wrong line"),
        actor=allocation_actor(human, prop),
    )
    assert outstanding(url, case["other_line"]) == 12_500
    allocations().reverse_payment(
        prop,
        payment,
        ReversePaymentCommand(uuid4(), "Bank transfer returned"),
        actor=allocation_actor(human, prop),
    )
    assert one(url, "SELECT status FROM app.payments WHERE id=%s", payment) == ("REVERSED",)
    applied = credits().apply(
        prop,
        case["credit"],
        ApplyCreditCommand(
            uuid4(),
            {
                "mode": "DESIGNATED",
                "invoice_id": str(other_invoice),
                "amount_usd_cents": 400,
                "details": [{"invoice_line_id": str(case["other_line"]), "amount_usd_cents": 400}],
                "designation_reference": "Customer asked at the front desk on 2026-10-06",
            },
        ),
        actor=credit_actor(human, prop, "credits.apply"),
    )
    assert outstanding(url, case["other_line"]) == 12_100
    application = UUID(str(cast(dict[str, Any], applied["application"])["id"]))
    credits().reverse_application(
        prop,
        application,
        ReverseCreditApplicationCommand(uuid4(), "Customer changed the instruction"),
        actor=credit_actor(human, prop, "credits.applications.reverse"),
    )
    assert outstanding(url, case["other_line"]) == 12_500


def no_lease_charge(customer: UUID) -> RecordOneTimeChargeCommand:
    """A one-time charge of the Customer that names no Lease."""
    return RecordOneTimeChargeCommand(
        uuid4(),
        "MISCELLANEOUS_CHARGES",
        customer,
        None,
        None,
        "Parking card replacement",
        700,
        "Customer lost the parking card",
        "Front desk log 803",
    )


def test_a_corrected_draft_cannot_bring_a_charge_onto_a_closed_lease(
    migrated_database_url: str,
) -> None:
    """Review round 1, blocker B1: an Invoice draft corrected onto a charge of the Lease and then
    issued would add a charge to the closed Lease by UPDATE. While the Settlement is open, VOID,
    Adjustment and draft correction work as before; after closure the issue of the corrected draft,
    a new correction onto a Lease charge and the VOID of the draft are refused (owner answer 7 to
    Q-2026-10-05-20 and owner answer 3 to Q-2026-10-06-33) and write nothing."""
    url = migrated_database_url
    case = leaving_case(url)
    human, prop, lease, customer = case["human"], case["prop"], case["lease"], case["customer"]
    staff = invoice_staff(human, prop)
    api = invoice_api_actor(human, prop)
    # While the Settlement is open: a Lease charge is billed and VOIDed, so it may be billed again.
    voided = key_card(customer, lease)
    invoices().record_one_time_charge(prop, voided, actor=staff)
    voided_invoice = UUID(str(draft_and_issue(prop, voided.charge_id, staff)["id"]))
    invoices().void(
        prop,
        voided_invoice,
        VoidInvoiceCommand(uuid4(), "Billed on the wrong day", version(url, voided_invoice)),
        actor=api,
    )
    assert one(url, "SELECT status FROM app.invoices WHERE id=%s", voided_invoice) == ("VOID",)
    # ... another is billed and reduced by a credit Adjustment.
    adjusted = key_card(customer, lease)
    invoices().record_one_time_charge(prop, adjusted, actor=staff)
    adjusted_invoice = UUID(str(draft_and_issue(prop, adjusted.charge_id, staff)["id"]))
    adjusted_line = UUID(
        str(one(url, "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", adjusted_invoice)[0])
    )
    invoices().adjust(
        prop,
        adjusted_invoice,
        AdjustInvoiceCommand(
            uuid4(),
            adjusted_line,
            AdjustmentType.CREDIT,
            100,
            f"open-settlement/{uuid4()}",
            "Approved reduction",
            version(url, adjusted_invoice),
        ),
        actor=api,
    )
    assert outstanding(url, adjusted_line) == 1_400
    # ... a draft of a charge with no Lease is corrected onto the VOIDed Lease charge.
    first = no_lease_charge(customer)
    invoices().record_one_time_charge(prop, first, actor=staff)
    corrected = invoices().create_draft(
        prop, CreateInvoiceDraftCommand(uuid4(), first.charge_id), actor=staff
    )
    corrected_id = UUID(str(corrected["id"]))
    invoices().correct_draft(
        prop,
        corrected_id,
        CorrectInvoiceDraftCommand(
            uuid4(), voided.charge_id, "Bill the key card again", cast(int, corrected["version"])
        ),
        actor=staff,
    )
    assert one(url, "SELECT lease_id,status FROM app.invoices WHERE id=%s", corrected_id) == (
        lease,
        "DRAFT",
    )
    # ... and another Lease charge and another no-Lease draft wait.
    unbilled = key_card(customer, lease)
    invoices().record_one_time_charge(prop, unbilled, actor=staff)
    second = no_lease_charge(customer)
    invoices().record_one_time_charge(prop, second, actor=staff)
    other = invoices().create_draft(
        prop, CreateInvoiceDraftCommand(uuid4(), second.charge_id), actor=staff
    )
    other_id = UUID(str(other["id"]))
    close(url, human, case["settlement"])
    snapshot = (
        one(url, "SELECT lease_id,status,version FROM app.invoices WHERE id=%s", corrected_id),
        one(url, "SELECT lease_id,status,version FROM app.invoices WHERE id=%s", other_id),
        count(
            url, "SELECT count(*) FROM app.invoice_void_events WHERE invoice_id=%s", corrected_id
        ),
    )
    # The corrected draft points at the closed Lease's charge: its issue is refused.
    closed_refusal(
        InvoiceConflictError,
        invoices().issue,
        prop,
        corrected_id,
        IssueInvoiceCommand(uuid4(), version(url, corrected_id)),
        actor=staff,
    )
    # A new correction onto a charge of the closed Lease is refused.
    closed_refusal(
        InvoiceConflictError,
        invoices().correct_draft,
        prop,
        other_id,
        CorrectInvoiceDraftCommand(
            uuid4(), unbilled.charge_id, "Bill the key card", version(url, other_id)
        ),
        actor=staff,
    )
    # The VOID of the draft with the closed Lease is refused too (owner answer 3). A one-time charge
    # draft has no Due Date until it is issued, so the earlier rule invoices_due_date_issued
    # (migration 64: only a DRAFT may lack a Due Date) already refuses it, open or closed.
    with pytest.raises(InvoiceInvalidError) as draft_void:
        invoices().void(
            prop,
            corrected_id,
            VoidInvoiceCommand(uuid4(), "Not needed", version(url, corrected_id)),
            actor=api,
        )
    cause = draft_void.value.__cause__
    assert isinstance(cause, psycopg.Error)
    assert (cause.sqlstate, cause.diag.constraint_name) == ("23514", "invoices_due_date_issued")
    assert (
        one(url, "SELECT lease_id,status,version FROM app.invoices WHERE id=%s", corrected_id),
        one(url, "SELECT lease_id,status,version FROM app.invoices WHERE id=%s", other_id),
        count(
            url, "SELECT count(*) FROM app.invoice_void_events WHERE invoice_id=%s", corrected_id
        ),
    ) == snapshot


def rent_lease(url: str, year: int) -> tuple[UUID, UUID, UUID]:
    """A signed Lease for one calendar year before 1879 with its Occupancy, a year no other
    fixture uses (the run fixtures use 1879 to 1900)."""
    with psycopg.connect(url) as owner:
        human, prop, unit, customer, _ = setup_sources(owner)
        lease = create_draft(
            owner,
            actor_id=human,
            unit_id=unit,
            primary_tenant_id=customer,
            start_date=date(year, 1, 1),
            end_date=date(year, 12, 31),
        )
        sign_lease(owner, lease, human)
        owner.execute(
            "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,created_at,"
            "created_by,updated_at,updated_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                uuid4(),
                lease,
                customer,
                date(year, 1, 1),
                datetime(year, 1, 1, tzinfo=UTC),
                human,
                datetime(year, 1, 1, tzinfo=UTC),
                human,
            ),
        )
        owner.commit()
    return human, prop, lease


def test_a_billing_run_skips_a_closed_lease_and_keeps_its_other_invoices_voidable(
    migrated_database_url: str,
) -> None:
    """Owner answer 1 to Q-2026-10-06-33: a scheduled Rent run records a Lease whose Settlement is
    closed as SKIPPED with FINAL_SETTLEMENT_CLOSED, bills the open Lease and succeeds, so the VOID
    of the open Lease's Invoice from that run is not refused because of the closed Lease."""
    url = migrated_database_url
    human, prop, closed_lease = rent_lease(url, 1870)
    _, _, open_lease = rent_lease(url, 1870)
    terminate(url, human, prop, closed_lease, date(1870, 6, 30), voluntary=False)
    close(url, human, start(prop, human, closed_lease))
    with psycopg.connect(url) as owner:
        worker = register_billing_service_principal(owner, property_id=prop, created_by=human)
        owner.commit()
    run = PostgresBillingRunService(financial_database_url()).execute(
        BillingRunCommand(
            property_id=prop,
            run_kind="RENT",
            logical_run_key=f"rent/1870-03/{closed_lease}",
            business_date=date(1870, 2, 25),
            period_start=date(1870, 3, 1),
            period_end=date(1870, 3, 31),
            idempotency_key=uuid4(),
        ),
        actor=service_actor(worker, prop),
        invocation_source="SCHEDULED",
    )
    assert run.status == "SUCCEEDED", run
    items = {item.source_id: item for item in run.attempts[-1].items}
    assert set(items) == {closed_lease, open_lease}
    assert (items[closed_lease].outcome, items[closed_lease].diagnostic_code) == (
        "SKIPPED",
        "FINAL_SETTLEMENT_CLOSED",
    )
    assert items[closed_lease].invoice_id is None
    assert (items[open_lease].outcome, items[open_lease].diagnostic_code) == ("GENERATED", None)
    assert count(url, "SELECT count(*) FROM app.invoices WHERE lease_id=%s", closed_lease) == 0
    generated = items[open_lease].invoice_id
    assert generated is not None
    invoices().void(
        prop,
        generated,
        VoidInvoiceCommand(uuid4(), "Billed in the wrong run", version(url, generated)),
        actor=invoice_api_actor(human, prop),
    )
    assert one(url, "SELECT status FROM app.invoices WHERE id=%s", generated) == ("VOID",)


def test_a_utility_run_skips_only_a_closed_lease_and_keeps_its_other_invoices_voidable(
    migrated_database_url: str,
) -> None:
    """Owner answer 1 to Q-2026-10-06-33 for a Utility run (review round 2): a consumption period
    whose responsible Lease has a closed Settlement is SKIPPED with FINAL_SETTLEMENT_CLOSED and no
    Invoice; a period whose Lease has a Settlement that is started but still open is billed; the
    run succeeds and the billed Invoice can then be VOIDed."""
    url = migrated_database_url
    human, prop, closed_lease = rent_lease(url, 1872)
    _, _, open_lease = rent_lease(url, 1872)
    periods: dict[UUID, UUID] = {}
    with psycopg.connect(url) as owner:
        owner.execute(
            "INSERT INTO app.utility_rates(id,property_id,utility_type,measurement_unit_code,"
            "rate_usd_per_unit,effective_date,notice_at,notice_evidence,actor_id) "
            "VALUES (%s,%s,'ELECTRICITY','KWH',0.25,DATE '1872-01-01',"
            "TIMESTAMPTZ '1871-12-01 00:00:00+07','OWNER-NOTICE',%s)",
            (uuid4(), prop, human),
        )
        worker = register_billing_service_principal(owner, property_id=prop, created_by=human)
        readings: dict[UUID, tuple[UUID, UUID, UUID]] = {}
        for lease in (closed_lease, open_lease):
            row = owner.execute("SELECT unit_id FROM app.leases WHERE id=%s", (lease,)).fetchone()
            assert row is not None
            unit = UUID(str(row[0]))
            meter = add_meter(owner, actor_id=human, unit_id=unit, installed_date=date(1872, 1, 1))
            first = add_reading(
                owner,
                actor_id=human,
                meter_id=meter,
                reading_date=date(1872, 2, 29),
                reading_value="100",
            )
            last = add_reading(
                owner,
                actor_id=human,
                meter_id=meter,
                reading_date=date(1872, 3, 31),
                reading_value="140",
            )
            readings[lease] = (unit, first, last)
        owner.commit()
    utility = PostgresUtilityService(financial_database_url(), prop, human)
    calculator = AuthenticatedActor(
        actor_id=str(human),
        capability_grants=frozenset(
            {CapabilityGrant(UTILITY_CALCULATE_CAPABILITY, frozenset({str(prop)}))}
        ),
    )
    for lease, (unit, first, last) in readings.items():
        periods[lease] = uuid4()
        utility.finalize_actual(
            FinalizeActualConsumptionCommand(
                idempotency_key=uuid4(),
                consumption_period_id=periods[lease],
                unit_id=unit,
                utility_type="ELECTRICITY",
                start_reading_id=first,
                end_reading_id=last,
                finalized_at=database_now(),
            ),
            actor=calculator,
        )
    for lease in (closed_lease, open_lease):
        terminate(url, human, prop, lease, date(1872, 6, 30), voluntary=False)
    close(url, human, start(prop, human, closed_lease))
    start(prop, human, open_lease)
    run = PostgresBillingRunService(financial_database_url()).execute(
        BillingRunCommand(
            property_id=prop,
            run_kind="UTILITIES",
            logical_run_key=f"utilities/1872-03/{periods[closed_lease]}",
            business_date=date(1872, 3, 31),
            period_start=date(1872, 3, 1),
            period_end=date(1872, 3, 31),
            idempotency_key=uuid4(),
        ),
        actor=service_actor(worker, prop),
        invocation_source="SCHEDULED",
    )
    assert run.status == "SUCCEEDED", run
    items = {item.source_id: item for item in run.attempts[-1].items}
    assert set(items) == {periods[closed_lease], periods[open_lease]}
    skipped, billed = items[periods[closed_lease]], items[periods[open_lease]]
    assert (skipped.outcome, skipped.diagnostic_code, skipped.invoice_id) == (
        "SKIPPED",
        "FINAL_SETTLEMENT_CLOSED",
        None,
    )
    assert (billed.outcome, billed.diagnostic_code) == ("GENERATED", None)
    assert count(url, "SELECT count(*) FROM app.invoices WHERE lease_id=%s", closed_lease) == 0
    assert billed.invoice_id is not None
    invoices().void(
        prop,
        billed.invoice_id,
        VoidInvoiceCommand(uuid4(), "Billed in the wrong run", version(url, billed.invoice_id)),
        actor=invoice_api_actor(human, prop),
    )
    assert one(url, "SELECT status FROM app.invoices WHERE id=%s", billed.invoice_id) == ("VOID",)


def test_a_final_utility_invoice_is_refused_after_closure(migrated_database_url: str) -> None:
    """The final Utility Invoice service reports the closed Settlement as a conflict (answer 7) and
    writes no Invoice."""
    url = migrated_database_url
    leaver = departed(url, 3, 6)
    dep = leaver.dep
    reading = final_reading(url, leaver, dep.electricity, "150")
    event = record_final(leaver, (used(dep.electricity, reading),))
    close(url, dep.human, start(dep.prop, dep.human, dep.lease))
    before = count(url, "SELECT count(*) FROM app.invoices WHERE lease_id=%s", dep.lease)
    closed_refusal(FinalUtilityInvoiceConflictError, create_final, leaver, event)
    assert count(url, "SELECT count(*) FROM app.invoices WHERE lease_id=%s", dep.lease) == before


def overdue_case(url: str) -> dict[str, Any]:
    """A terminated Lease with two overdue Rent Invoices: the first has its Late-payment Charge,
    the second has no Late-payment Decision yet; its Final Settlement is started."""
    now = today(url)
    first = (now.replace(day=1) - timedelta(days=95)).replace(day=1)
    second = (now.replace(day=1) - timedelta(days=62)).replace(day=1)
    with psycopg.connect(url) as connection:
        human, prop, customer, lease = setup_signed_lease(
            connection, start_date=date(now.year - 1, 1, 1), end_date=date(now.year + 1, 12, 31)
        )
        rent: list[UUID] = []
        for period in (first, second):
            invoice, _line = create_recurring_rent_invoice(
                connection,
                actor_id=human,
                customer_id=customer,
                lease_id=lease,
                period_start=period,
            )
            rent.append(invoice)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    flow = late_payments()
    review = flow.review(rent[0], actor=late_payment_actor(human, prop))
    amount = cast(dict[str, int], review["calculated_default_amount"])["minor_units"]
    flow.finalize_decision(
        prop,
        rent[0],
        FinalizeLatePaymentDecisionCommand(
            uuid4(), DecisionOutcome.CONFIRMED_DEFAULT, amount, "Approved default charge"
        ),
        actor=late_payment_actor(human, prop),
    )
    charge = UUID(
        str(
            one(url, "SELECT id FROM app.late_payment_charges WHERE source_invoice_id=%s", rent[0])[
                0
            ]
        )
    )
    terminate(url, human, prop, lease, now, voluntary=False)
    return {
        "human": human,
        "prop": prop,
        "customer": customer,
        "lease": lease,
        "charged": rent[0],
        "undecided": rent[1],
        "charge": charge,
        "settlement": start(prop, human, lease),
        "later_period": (now.replace(day=1) - timedelta(days=31)).replace(day=1),
    }


def test_late_payment_decisions_charge_corrections_and_rent_are_refused_after_closure(
    migrated_database_url: str,
) -> None:
    """Every Late-payment Decision is recorded before closure (Q-2026-10-05-20 answer 6); after
    closure a new Decision, a Charge correction and a new Rent Invoice of the Lease are refused
    (answer 7) and write nothing."""
    url = migrated_database_url
    case = overdue_case(url)
    human, prop = case["human"], case["prop"]
    review = late_payments().review(case["undecided"], actor=late_payment_actor(human, prop))
    assert review["eligible"] is True
    close(url, human, case["settlement"])
    closed_refusal(
        LatePaymentConflictError,
        late_payments().finalize_decision,
        prop,
        case["undecided"],
        FinalizeLatePaymentDecisionCommand(
            uuid4(), DecisionOutcome.WAIVED, 0, "Waived after the Settlement"
        ),
        actor=late_payment_actor(human, prop),
    )
    closed_refusal(
        LatePaymentConflictError,
        late_payments().correct_charge,
        prop,
        case["charge"],
        CorrectLatePaymentChargeCommand(uuid4(), CorrectionKind.REDUCTION, "Reduced later", 100),
        actor=late_payment_actor(human, prop),
    )
    assert (
        count(
            url,
            "SELECT count(*) FROM app.late_payment_decisions WHERE source_invoice_id=%s",
            case["undecided"],
        )
        == 0
    )
    assert (
        count(
            url,
            "SELECT count(*) FROM app.late_payment_charge_corrections "
            "WHERE late_payment_charge_id=%s",
            case["charge"],
        )
        == 0
    )
    invoices_before = count(
        url, "SELECT count(*) FROM app.invoices WHERE lease_id=%s", case["lease"]
    )
    with pytest.raises(psycopg.Error) as rent, psycopg.connect(url) as connection:
        create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=case["customer"],
            lease_id=case["lease"],
            period_start=case["later_period"],
        )
    assert (rent.value.sqlstate, rent.value.diag.message_primary) == ("P5S01", CLOSED)
    assert count(url, "SELECT count(*) FROM app.invoices WHERE lease_id=%s", case["lease"]) == (
        invoices_before
    )
    assert owner_refusal(
        url,
        "INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id) VALUES (%s,%s)",
        uuid4(),
        case["charge"],
    ) == ("P5S01", CLOSED)


def test_unpaid_initial_resolutions_are_refused_after_closure(migrated_database_url: str) -> None:
    """The unpaid-Initial resolutions VOID or credit the Initial Rent Invoice; after closure they
    are refused as a conflict (answer 7) and nothing changes."""
    url = migrated_database_url
    source = signed_with_initial(url, 10)
    event = terminate_unpaid(url, source)
    settlement = start(source["property"], source["actor"], source["lease"])
    close(url, source["actor"], settlement)
    snapshot = (
        one(url, "SELECT status,version FROM app.invoices WHERE id=%s", source["invoice"]),
        one(url, "SELECT status FROM app.units WHERE id=%s", source["unit"]),
    )
    closed_refusal(
        UnpaidInitialTerminationConflictError,
        unpaid_initial(source).resolve_never_moved_in,
        ResolveNeverMovedInCommand(
            uuid4(), uuid4(), event, "VACANT", "Customer never moved in and did not pay"
        ),
        actor=unpaid_initial_actor(
            source["actor"], source["property"], *UNPAID_INITIAL_CAPABILITIES
        ),
    )
    assert (
        one(url, "SELECT status,version FROM app.invoices WHERE id=%s", source["invoice"]),
        one(url, "SELECT status FROM app.units WHERE id=%s", source["unit"]),
    ) == snapshot


def test_a_closure_and_a_change_of_its_obligations_wait_for_each_other(
    migrated_database_url: str,
) -> None:
    """The refusal locks the Settlement row FOR SHARE: a change waits for a running closure and is
    then refused, and a closure waits for a running change (note 14 of the 8e pre-code review)."""
    url = migrated_database_url
    case = leaving_case(url)
    human = case["human"]
    # A change in progress holds the Settlement row; the closure cannot take it meanwhile.
    with psycopg.connect(financial_database_url()) as change:
        change.execute(ONE_TIME_CHARGE, one_time_charge_row(case, uuid4()))
        with pytest.raises(psycopg.Error) as waiting, psycopg.connect(url) as closure:
            closure.execute("SET lock_timeout='300ms'")
            closure.execute(CLOSE, (human, case["settlement"]))
        assert waiting.value.sqlstate == "55P03"
    # A closure in progress holds the Settlement row; the change cannot take it meanwhile, and
    # once the closure has committed the change is refused.
    with psycopg.connect(url) as closure:
        closure.execute(CLOSE, (human, case["settlement"]))
        with (
            pytest.raises(psycopg.Error) as blocked,
            psycopg.connect(financial_database_url()) as change,
        ):
            change.execute("SET lock_timeout='300ms'")
            change.execute(ONE_TIME_CHARGE, one_time_charge_row(case, uuid4()))
        assert blocked.value.sqlstate == "55P03"
    with (
        pytest.raises(psycopg.Error) as refused,
        psycopg.connect(financial_database_url()) as change,
    ):
        change.execute(ONE_TIME_CHARGE, one_time_charge_row(case, uuid4()))
    assert (refused.value.sqlstate, refused.value.diag.message_primary) == ("P5S01", CLOSED)
    assert (
        count(
            url,
            "SELECT count(*) FROM app.authorized_nonrecurring_obligations WHERE lease_id=%s",
            case["lease"],
        )
        == 3
    )


def test_the_closed_settlement_guard_runs_first_and_is_least_privilege(
    migrated_database_url: str,
) -> None:
    """One definer function, no role may call it; on each guarded table its BEFORE INSERT trigger
    runs first, before the 8a-1 Deposit-application refusal and the source locks."""
    with psycopg.connect(migrated_database_url) as owner:
        definer, config = cast(
            tuple[bool, list[str] | None],
            owner.execute(
                "SELECT prosecdef,proconfig FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure",
                (FUNCTION,),
            ).fetchone(),
        )
        assert definer is True and "search_path=pg_catalog" in (config or [])
        for role in ("PUBLIC", "prm_runtime", "prm_financial", "prm_bootstrap"):
            grantee = "public" if role == "PUBLIC" else role
            assert owner.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (grantee, FUNCTION)
            ).fetchone() == (False,), role
        for table in TABLES:
            rows = owner.execute(
                "SELECT tgname,tgfoid::regprocedure::text,tgenabled FROM pg_trigger "
                "WHERE tgrelid=%s::regclass AND NOT tgisinternal "
                "AND (tgtype & 1)=1 AND (tgtype & 2)=2 AND (tgtype & 4)=4 ORDER BY tgname",
                (f"app.{table}",),
            ).fetchall()
            assert rows[0] == (
                f"a0_{table}_final_settlement_closed",
                "app.refuse_closed_final_settlement_change()",
                "O",
            ), table
        # Review round 1, blocker B1: an existing Invoice row that gets a Lease, or a DRAFT with a
        # Lease that is issued, meets the same guard before every other BEFORE UPDATE trigger.
        updates = owner.execute(
            "SELECT tgname,tgfoid::regprocedure::text,tgenabled,pg_get_triggerdef(oid) "
            "FROM pg_trigger WHERE tgrelid='app.invoices'::regclass AND NOT tgisinternal "
            "AND (tgtype & 1)=1 AND (tgtype & 2)=2 AND (tgtype & 16)=16 ORDER BY tgname"
        ).fetchall()
        name, function, enabled, definition = updates[0]
        assert (name, function, enabled) == (
            "a0_invoices_final_settlement_closed_update",
            "app.refuse_closed_final_settlement_change()",
            "O",
        )
        # The two run item functions patched for owner answer 1 to Q-2026-10-06-33 keep their
        # definer settings and grants.
        for signature in (
            "app.record_scheduled_rent_item(uuid,uuid,uuid,uuid,text,uuid,text,uuid,timestamptz)",
            "app.record_scheduled_utility_item(uuid,uuid,text,uuid,uuid,text,uuid,timestamptz)",
        ):
            item_definer, item_config = cast(
                tuple[bool, list[str] | None],
                owner.execute(
                    "SELECT prosecdef,proconfig FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure",
                    (signature,),
                ).fetchone(),
            )
            assert item_definer is True and "search_path=pg_catalog" in (item_config or [])
            for role, allowed in (
                ("prm_financial", True),
                ("prm_runtime", False),
                ("prm_bootstrap", False),
                ("public", False),
            ):
                assert owner.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)
                ).fetchone() == (allowed,), (signature, role)
        for part in (
            "BEFORE UPDATE OF lease_id, status ON app.invoices",
            "old.lease_id IS DISTINCT FROM new.lease_id",
            "old.status = 'DRAFT'",
        ):
            assert part in str(definition), part


def test_final_settlement_closed_refusal_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261027_92")
    assert revision is not None and revision.down_revision == "20261026_91"
    module = revision.module
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
