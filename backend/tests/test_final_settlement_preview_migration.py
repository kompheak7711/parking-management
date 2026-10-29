"""V1-056 sub-slice 8b: the Final Settlement preview and the reversed-forfeiture Deposit path."""

from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from deposit_disposition_test_support import terminate_for_disposition
from deposit_receipt_reversal_test_support import reverse_receipt_through_draft
from lease_deposit_forfeiture_test_support import forfeit_through_draft, reverse_through_draft
from payment_test_support import seed_payment
from property_rental.deposit import PostgresDepositService
from property_rental.deposit_receipt_reversal import (
    DepositReceiptReversalService,
    RecordDepositReceiptReversalCommand,
)
from property_rental.final_settlement import (
    FinalSettlementNotFoundError,
    FinalSettlementReadService,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.invoice import (
    AdjustInvoiceCommand,
    AdjustmentType,
    CorrectInvoiceDraftCommand,
    CreateInvoiceDraftCommand,
    IssueInvoiceCommand,
    PostgresInvoiceService,
    RecordOneTimeChargeCommand,
    RecordUnitCleaningChargeCommand,
    SetUnitCleaningRateCommand,
    VoidInvoiceCommand,
)
from property_rental.late_payment import DecisionOutcome, FinalizeLatePaymentDecisionCommand
from property_rental.lease_deposit_forfeiture import (
    LeaseDepositForfeitureService,
    RecordLeaseDepositForfeitureCommand,
    RecordLeaseDepositReversalCommand,
)
from property_rental.lease_enforcement import NonpaymentEventKind
from property_rental.lease_termination import TerminationBasis
from property_rental.move_out_inspection import (
    INSPECTION_READ,
    INSPECTION_RECORD,
    InspectionFinding,
    PostgresMoveOutInspectionService,
    RecordMoveOutInspection,
)
from property_rental.payment_move import PaymentMoveService, RecordPaymentMoveCommand
from property_rental.refund import CreateUsdRefundCommand, RefundService
from refund_test_support import cash
from test_deposit_migration import seed_historical_deposit_receipt
from test_final_settlement_migration import (
    another_signer_invoice,
    apply,
    charge_remaining,
    held,
    lease_with_charge,
    outstanding,
    overdue_lease_with_pet_damage,
    refused,
    start,
    today,
)
from test_final_utility_invoice_migration import create_final, departed, final_reading, record_final
from test_invoice_migration import (
    create_recurring_rent_invoice,
    financial_database_url,
    invoice_api_actor,
    register_billing_service_principal,
    runtime_database_url,
    setup_signed_lease,
)
from test_late_payment_migration import late_payment_actor
from test_late_payment_migration import service as late_payments
from test_lease_deposit_forfeiture_migration import terminate_on
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_out_final_inputs_migration import missing, used
from test_one_time_charges_migration import draft_and_issue
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated
from test_payment_allocation_migration import service as allocations
from test_payment_move_migration import SOURCE_ACK, TARGET_ACK, allocation_ids
from test_rent_nonpayment_recurring_only_migration import enforcement, open_case
from test_rent_nonpayment_recurring_only_migration import record as record_nonpayment_event
from test_termination_deposit_migration import terminate
from test_unpaid_initial_termination_migration import signed_with_initial
from test_unpaid_initial_termination_migration import terminate as terminate_unpaid
from test_utility_meter_migration import add_meter, add_reading

PREVIEW = "app.final_settlement_preview(uuid,uuid,uuid,text[])"
PREVIEW_SQL = "SELECT app.final_settlement_preview(%s,%s,%s,%s::text[])"
INTERNAL = (
    "app.lease_termination_forfeiture_rule(uuid,uuid,text)",
    "app.lease_deposit_settlement_path(uuid,uuid)",
    "app.lease_deposit_kept_rule(uuid,uuid)",
)
STEPS = [
    (1, "OBLIGATIONS_FINAL"),
    (2, "CUSTOMER_CREDIT"),
    (3, "PET_DEPOSIT_PET_DAMAGE"),
    (4, "SECURITY_DEPOSIT"),
    (5, "PET_DEPOSIT_REMAINDER"),
    (6, "REMAINING_BALANCE"),
    (7, "DEPOSIT_REFUNDS"),
]
APPROVE = "financial.approve"
HIDDEN = {"code": "PENDING_DRAFT"}


def person(human: UUID, prop: UUID, *capabilities: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(human),
        frozenset(
            CapabilityGrant(capability, frozenset({str(prop)})) for capability in capabilities
        ),
    )


def preview(prop: UUID, human: UUID, settlement: UUID, *capabilities: str) -> dict[str, Any]:
    reader = person(human, prop, *(capabilities or ("final_settlements.prepare",)))
    return FinalSettlementReadService(runtime_database_url()).preview(
        prop, settlement, actor=reader
    )


def without_time(view: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in view.items() if key != "previewed_at"}


def issues(view: dict[str, Any], code: str) -> list[dict[str, Any]]:
    return [item for item in view["blocking_issues"] if item["code"] == code]


def codes(view: dict[str, Any]) -> set[str]:
    return {item["code"] for item in view["blocking_issues"]}


def shown(draft: dict[str, object], kind: str, variant: str) -> dict[str, object]:
    return {
        "code": "PENDING_DRAFT",
        "draft_id": draft["draft_id"],
        "kind": kind,
        "variant": variant,
    }


def deposit_of(view: dict[str, Any], deposit: UUID) -> dict[str, Any]:
    return next(item for item in view["deposits"] if item["deposit_id"] == str(deposit))


def path_of(view: dict[str, Any], deposit: UUID) -> tuple[Any, ...]:
    item = deposit_of(view, deposit)
    return item["ground"], item["forfeiture"], item["path"], item["held_usd_cents"]


def step(view: dict[str, Any], number: int) -> dict[str, Any]:
    return cast(dict[str, Any], view["steps"][number - 1])


def scalar(url: str, sql: str, *parameters: object) -> Any:
    with psycopg.connect(url) as connection:
        found = connection.execute(sql, parameters).fetchone()
    assert found is not None
    return found[0]


def forfeitures() -> LeaseDepositForfeitureService:
    return LeaseDepositForfeitureService(financial_database_url())


def invoices() -> PostgresInvoiceService:
    return PostgresInvoiceService(runtime_database_url(), financial_database_url())


def pay(
    url: str, prop: UUID, human: UUID, customer: UUID, invoice: UUID, line: UUID, amount: int
) -> UUID:
    with psycopg.connect(url) as connection:
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=amount
        )
    allocations().post(
        prop, payment, designated(invoice, line, amount), actor=allocation_actor(human, prop)
    )
    return payment


def credit_adjustment(url: str, human: UUID, prop: UUID, invoice: UUID, line: UUID) -> None:
    version = int(scalar(url, "SELECT version FROM app.invoices WHERE id=%s", invoice))
    invoices().adjust(
        prop,
        invoice,
        AdjustInvoiceCommand(
            uuid4(),
            line,
            AdjustmentType.CREDIT,
            400,
            f"approved-credit/{uuid4()}",
            "Approved credit",
            version,
        ),
        actor=invoice_api_actor(human, prop),
    )


def key_card(customer: UUID, lease: UUID) -> RecordOneTimeChargeCommand:
    return RecordOneTimeChargeCommand(
        uuid4(),
        "MISCELLANEOUS_CHARGES",
        customer,
        lease,
        None,
        "Replacement key card",
        1_500,
        "Customer lost key card",
        "Front desk log 802",
    )


def water_period(url: str, leaver: Any) -> UUID:
    """A finalized WATER consumption period of the leaver's Lease, on no Invoice (5 M3)."""
    dep = leaver.dep
    period = uuid4()
    with psycopg.connect(url) as connection:
        water = add_meter(
            connection,
            actor_id=dep.human,
            unit_id=dep.unit,
            utility_type="WATER",
            measurement_unit_code="M3",
            installed_date=leaver.start - timedelta(days=30),
        )
        first = add_reading(
            connection,
            actor_id=dep.human,
            meter_id=water,
            reading_date=leaver.start,
            reading_value="10",
        )
        last = add_reading(
            connection,
            actor_id=dep.human,
            meter_id=water,
            reading_date=dep.move_out_date,
            reading_value="15",
        )
        connection.execute(
            "SELECT app.finalize_actual_utility_consumption("
            "%s,%s,%s,%s,%s,'WATER',%s,%s,clock_timestamp(),%s)",
            (dep.prop, uuid4(), "a" * 64, period, dep.unit, first, last, dep.human),
        )
    return period


def test_the_preview_shows_obligations_and_deposits_in_dl032_order_and_writes_nothing(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = overdue_lease_with_pet_damage(url)
    human, prop, customer = case["human"], case["prop"], case["customer"]
    settlement = start(prop, human, case["lease"])
    view = preview(prop, human, settlement)
    assert [(item["step"], item["kind"]) for item in view["steps"]] == STEPS
    assert view["settlement"]["id"] == str(settlement) and view["settlement"]["closed"] is False
    assert view["lease"]["termination_ground"] is None
    [person_view] = view["customers"]
    assert person_view["customer_id"] == str(customer) and person_view["primary_tenant"] is True
    lines = {UUID(item["invoice_line_id"]): item for item in person_view["invoice_lines"]}
    assert set(lines) == {case["rent_line"], case["pet_line"], case["other_line"]}
    for line, item in lines.items():
        assert item["outstanding_usd_cents"] == outstanding(url, line) > 0
        assert item["pet_damage"] is (line == case["pet_line"])
    assert [
        (UUID(item["late_payment_charge_id"]), item["remaining_usd_cents"])
        for item in person_view["late_payment_charges"]
    ] == [(case["charge"], charge_remaining(url, case["charge"]))]
    total = sum(outstanding(url, line) for line in lines) + charge_remaining(url, case["charge"])
    assert view["open_total_usd_cents"] == total == person_view["open_total_usd_cents"]
    assert step(view, 1)["open_total_usd_cents"] == total
    assert person_view["credits"] == [] and person_view["credit_may_use_usd_cents"] == 0
    # A Pet Deposit with no ground follows DL-032: pet damage first, then the remainder.
    assert path_of(view, case["pet"]) == (None, "NONE", "DL_032", 20_000)
    pet_open = outstanding(url, case["pet_line"])
    assert step(view, 3) == {
        "step": 3,
        "kind": "PET_DEPOSIT_PET_DAMAGE",
        "pet_damage_open_usd_cents": pet_open,
        "deposits": [{"deposit_id": str(case["pet"]), "may_use_usd_cents": min(20_000, pet_open)}],
    }
    assert step(view, 5)["chosen_by"] == "CUSTOMER_OR_STAFF_WITH_REASON"
    assert step(view, 5)["deposits"] == [
        {"deposit_id": str(case["pet"]), "may_use_usd_cents": min(20_000, total)}
    ]
    assert step(view, 6)["stays_with"] == "CUSTOMER_NAMED_ON_EACH_OBLIGATION"
    assert step(view, 7)["default_recipient_customer_id"] == str(customer)
    assert str(case["pet"]) in step(view, 7)["deposits"]
    # The Late-payment Decision is recorded; the Customer moved in and has no move-out yet.
    assert "LATE_PAYMENT_DECISION_MISSING" not in codes(view)
    assert issues(view, "FINAL_UTILITY_NOT_ISSUED") == [
        {"code": "FINAL_UTILITY_NOT_ISSUED", "reason": "MOVE_OUT_NOT_RECORDED"}
    ]
    assert view["ready"] is False
    # An approver reads the same preview; a read-only transaction proves it writes nothing.
    assert without_time(preview(prop, human, settlement, APPROVE)) == without_time(view)
    with psycopg.connect(runtime_database_url()) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        again = connection.execute(
            PREVIEW_SQL, (prop, human, settlement, ["final_settlements.prepare"])
        ).fetchone()
    assert again is not None and without_time(again[0]) == without_time(view)


def test_credit_and_pending_drafts_on_settlement_sources_are_shown_to_allowed_readers(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = overdue_lease_with_pet_damage(url)
    human, prop, customer = case["human"], case["prop"], case["customer"]
    now = today(url)
    # A credit Adjustment on a paid line releases Customer Credit of the Invoice Customer.
    payer = pay(
        url,
        prop,
        human,
        customer,
        case["other_invoice"],
        case["other_line"],
        outstanding(url, case["other_line"]),
    )
    credit_adjustment(url, human, prop, case["other_invoice"], case["other_line"])
    credit = UUID(
        str(scalar(url, "SELECT id FROM app.customer_credits WHERE source_payment_id=%s", payer))
    )
    refunds = RefundService(runtime_database_url(), financial_database_url())
    who = person(human, prop, "refunds.create")
    refund_draft = refunds.record_usd_draft(
        prop,
        CreateUsdRefundCommand(uuid4(), "CREDIT", credit, 400, "Customer asked for the Credit"),
        cash(refunds, prop, who),
        actor=who,
    )
    # A Payment Refund draft of the same Customer's unallocated Payment value.
    with psycopg.connect(url) as connection:
        unallocated = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=700
        )
    payment_draft = refunds.record_usd_draft(
        prop,
        CreateUsdRefundCommand(uuid4(), "PAYMENT", unallocated, 700, "Customer paid twice"),
        cash(refunds, prop, who),
        actor=who,
    )
    # A Payment posted on this Lease by mistake, with a move draft to another Unit's Invoice.
    with psycopg.connect(url) as connection:
        _, _, other_customer, other_lease = setup_signed_lease(
            connection, start_date=date(now.year - 1, 1, 1), end_date=date(now.year + 1, 12, 31)
        )
        correct, _ = create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=other_customer,
            lease_id=other_lease,
            period_start=now.replace(day=1),
        )
        mistaken = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=1_000
        )
    posted = allocations().post(
        prop,
        mistaken,
        designated(case["invoice"], case["rent_line"], 1_000),
        actor=allocation_actor(human, prop),
    )
    move_draft = PaymentMoveService(financial_database_url()).record(
        prop,
        RecordPaymentMoveCommand(
            uuid4(),
            allocation_ids(posted)[0],
            correct,
            "Paid on this Parking by mistake",
            SOURCE_ACK,
            TARGET_ACK,
        ),
        actor=person(human, prop, "payments.allocations.reverse"),
    )
    settlement = start(prop, human, case["lease"])
    view = preview(prop, human, settlement, APPROVE)
    [person_view] = view["customers"]
    assert person_view["credits"] == [
        {"customer_credit_id": str(credit), "available_usd_cents": 400}
    ]
    assert person_view["credit_available_usd_cents"] == 400
    assert person_view["credit_may_use_usd_cents"] == min(400, person_view["open_total_usd_cents"])
    assert step(view, 2)["customers"] == [
        {"customer_id": str(customer), "may_use_usd_cents": person_view["credit_may_use_usd_cents"]}
    ]
    refund_issue = shown(refund_draft, "REFUND", "USD")
    move_issue = shown(move_draft, "PAYMENT_MOVE", "WRONG_UNIT_MOVE")
    payment_issue = shown(payment_draft, "REFUND", "USD")
    assert issues(view, "PENDING_DRAFT") == [refund_issue, payment_issue, move_issue]
    # Every reader sees that drafts block the Settlement; only a reader allowed to read a draft
    # sees which one (the slice 2 and 6b read rule).
    assert issues(preview(prop, human, settlement), "PENDING_DRAFT") == [HIDDEN] * 3
    assert issues(
        preview(prop, human, settlement, "final_settlements.prepare", "refunds.create"),
        "PENDING_DRAFT",
    ) == [refund_issue, payment_issue, HIDDEN]
    # The other Lease's Settlement sees the same move draft through its target Invoice; the
    # Credit Refund draft belongs to a Customer of this Lease only.
    terminate(url, human, prop, other_lease, now, voluntary=False)
    other = preview(prop, human, start(prop, human, other_lease), APPROVE)
    assert issues(other, "PENDING_DRAFT") == [move_issue]


def test_late_payment_decisions_and_uninvoiced_charges_block_until_recorded(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    now = today(url)
    first_period = (now.replace(day=1) - timedelta(days=93)).replace(day=1)
    second_period = (now.replace(day=1) - timedelta(days=62)).replace(day=1)
    with psycopg.connect(url) as connection:
        human, prop, customer, lease = setup_signed_lease(
            connection, start_date=date(now.year - 1, 1, 1), end_date=date(now.year + 1, 12, 31)
        )
        older, older_line = create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=customer,
            lease_id=lease,
            period_start=first_period,
        )
        newer, _ = create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=customer,
            lease_id=lease,
            period_start=second_period,
        )
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    # A partly paid overdue Invoice may also get a Late-payment Decision (migration 39).
    pay(url, prop, human, customer, older, older_line, 1_000)
    assert scalar(url, "SELECT status FROM app.invoices WHERE id=%s", older) == "PARTIALLY_PAID"
    staff = invoice_api_actor(human, prop)
    charge = key_card(customer, lease)
    invoices().record_one_time_charge(prop, charge, actor=staff)
    terminate(url, human, prop, lease, now, voluntary=False)
    settlement = start(prop, human, lease)
    view = preview(prop, human, settlement)
    assert issues(view, "LATE_PAYMENT_DECISION_MISSING") == [
        {
            "code": "LATE_PAYMENT_DECISION_MISSING",
            "invoice_id": str(invoice),
            "customer_id": str(customer),
        }
        for invoice in (older, newer)
    ]
    assert issues(view, "ONE_TIME_CHARGE_NOT_INVOICED") == [
        {
            "code": "ONE_TIME_CHARGE_NOT_INVOICED",
            "authorized_obligation_id": str(charge.charge_id),
            "customer_id": str(customer),
            "category": "MISCELLANEOUS_CHARGES",
        }
    ]
    assert issues(view, "INVOICE_DRAFT_NOT_ISSUED") == []
    draft = invoices().create_draft(
        prop, CreateInvoiceDraftCommand(uuid4(), charge.charge_id), actor=staff
    )
    view = preview(prop, human, settlement)
    assert issues(view, "ONE_TIME_CHARGE_NOT_INVOICED") == []
    assert issues(view, "INVOICE_DRAFT_NOT_ISSUED") == [
        {
            "code": "INVOICE_DRAFT_NOT_ISSUED",
            "invoice_id": draft["id"],
            "customer_id": str(customer),
        }
    ]
    flow = late_payments()
    for invoice in (older, newer):
        review = flow.review(invoice, actor=late_payment_actor(human, prop))
        flow.finalize_decision(
            prop,
            invoice,
            FinalizeLatePaymentDecisionCommand(
                uuid4(),
                DecisionOutcome.CONFIRMED_DEFAULT,
                cast(dict[str, int], review["calculated_default_amount"])["minor_units"],
                "Approved default charge",
            ),
            actor=late_payment_actor(human, prop),
        )
    invoices().issue(
        prop,
        UUID(str(draft["id"])),
        IssueInvoiceCommand(uuid4(), cast(int, draft["version"])),
        actor=staff,
    )
    view = preview(prop, human, settlement)
    assert not codes(view) & {
        "LATE_PAYMENT_DECISION_MISSING",
        "ONE_TIME_CHARGE_NOT_INVOICED",
        "INVOICE_DRAFT_NOT_ISSUED",
    }
    # The new Late-payment Charges and the issued charge are now Settlement obligations.
    [person_view] = view["customers"]
    assert len(person_view["late_payment_charges"]) == 2
    assert draft["id"] in {item["invoice_id"] for item in person_view["invoice_lines"]}


def test_three_forfeiture_cases_of_a_security_deposit(migrated_database_url: str) -> None:
    """Owner answer to Q-2026-10-05-24: no forfeiture yet blocks; an active one keeps the
    Deposit; a reversed one follows DL-032, and the Deposit may then be applied."""
    url = migrated_database_url
    human, prop, lease, security, _pet, _invoice, line, day = lease_with_charge(url)
    amount = held(url, security)
    terminate(url, human, prop, lease, day)
    settlement = start(prop, human, lease)
    view = preview(prop, human, settlement)
    assert path_of(view, security) == ("BR-DEP-023", "NONE", "FORFEITURE_REQUIRED", amount)
    assert issues(view, "FORFEITURE_NOT_CONFIRMED") == [
        {
            "code": "FORFEITURE_NOT_CONFIRMED",
            "deposit_id": str(security),
            "deposit_type": "SECURITY",
            "ground": "BR-DEP-023",
        }
    ]
    assert step(view, 4)["deposits"] == [] and str(security) not in step(view, 7)["deposits"]
    # Voluntary early leaving keeps the DL-013 staff step for the remaining Pet Deposit.
    assert step(view, 5)["chosen_by"] == "CUSTOMER_OR_STAFF_WITH_REASON"
    stage = ("SECURITY_EXPLICIT", "INVOICE_LINE", line)
    assert refused(url, prop, human, settlement, security, *stage, 100, 1) == "23514"
    # A pending forfeiture draft is a blocking issue too.
    first = forfeitures().record(
        prop,
        RecordLeaseDepositForfeitureCommand(uuid4(), security, uuid4(), "Deposit kept"),
        actor=person(human, prop, "deposits.dispose"),
    )
    assert issues(preview(prop, human, settlement, APPROVE), "PENDING_DRAFT") == [
        shown(first, "DEPOSIT_FORFEITURE", "LEASE_FORFEITURE")
    ]
    by_capability = {
        capability: issues(
            preview(prop, human, settlement, "final_settlements.prepare", capability),
            "PENDING_DRAFT",
        )
        for capability in ("deposits.dispose", "deposits.correct")
    }
    assert by_capability == {
        "deposits.dispose": [shown(first, "DEPOSIT_FORFEITURE", "LEASE_FORFEITURE")],
        "deposits.correct": [HIDDEN],
    }
    forfeitures().confirm(
        prop, security, UUID(str(first["draft_id"])), actor=person(human, prop, APPROVE)
    )
    view = preview(prop, human, settlement)
    assert path_of(view, security) == ("BR-DEP-023", "ACTIVE", "KEPT", 0)
    assert not codes(view) & {"FORFEITURE_NOT_CONFIRMED", "PENDING_DRAFT"}
    assert step(view, 4)["deposits"] == [] and str(security) not in step(view, 7)["deposits"]
    assert refused(url, prop, human, settlement, security, *stage, 100, 1) == "23514"
    # The forfeiture reversal draft waits as a blocking issue; once confirmed, the Deposit is
    # held again and follows DL-032.
    disposition = UUID(
        str(scalar(url, "SELECT id FROM app.deposit_dispositions WHERE deposit_id=%s", security))
    )
    reversal = forfeitures().record_reversal(
        prop,
        RecordLeaseDepositReversalCommand(
            uuid4(), disposition, uuid4(), "Wrong ground recorded", "CASE-8B"
        ),
        actor=person(human, prop, "deposits.correct"),
    )
    assert issues(preview(prop, human, settlement, APPROVE), "PENDING_DRAFT") == [
        shown(reversal, "DEPOSIT_FORFEITURE", "LEASE_FORFEITURE_REVERSAL")
    ]
    assert issues(
        preview(prop, human, settlement, "final_settlements.prepare", "deposits.correct"),
        "PENDING_DRAFT",
    ) == [shown(reversal, "DEPOSIT_FORFEITURE", "LEASE_FORFEITURE_REVERSAL")]
    assert issues(
        preview(prop, human, settlement, "final_settlements.prepare", "deposits.dispose"),
        "PENDING_DRAFT",
    ) == [HIDDEN]
    forfeitures().confirm_reversal(
        prop, disposition, UUID(str(reversal["draft_id"])), actor=person(human, prop, APPROVE)
    )
    view = preview(prop, human, settlement)
    assert path_of(view, security) == ("BR-DEP-023", "REVERSED", "DL_032", amount)
    assert not codes(view) & {"FORFEITURE_NOT_CONFIRMED", "PENDING_DRAFT"}
    assert step(view, 4)["deposits"] == [
        {
            "deposit_id": str(security),
            "may_use_usd_cents": min(amount, view["open_total_usd_cents"]),
        }
    ]
    assert str(security) in step(view, 7)["deposits"]
    # A new forfeiture draft for it waits as a blocking issue.
    second = forfeitures().record(
        prop,
        RecordLeaseDepositForfeitureCommand(uuid4(), security, uuid4(), "Deposit kept"),
        actor=person(human, prop, "deposits.dispose"),
    )
    assert issues(preview(prop, human, settlement, APPROVE), "PENDING_DRAFT") == [
        shown(second, "DEPOSIT_FORFEITURE", "LEASE_FORFEITURE")
    ]
    # The relaxed 8a-1 guard: the Deposit whose forfeiture was reversed may pay the open debt.
    apply(url, prop, human, settlement, security, *stage, 1_500, 1)
    assert outstanding(url, line) == 0 and held(url, security) == amount - 1_500


def test_a_pet_deposit_kept_for_pet_noncompliance_follows_dl032_after_its_reversal(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, lease, security, pet, _invoice, line, day = lease_with_charge(url)
    seed_historical_deposit_receipt(url, deposit_id=pet, actor_id=human, amount_usd_cents=1_000)
    service = PostgresDepositService(financial_database_url(), prop, human)
    terminate_for_disposition(url, service, lease, day)
    settlement = start(prop, human, lease)
    view = preview(prop, human, settlement)
    security_held = held(url, security)
    assert path_of(view, security) == ("BR-DEP-022", "NONE", "FORFEITURE_REQUIRED", security_held)
    assert path_of(view, pet) == ("BR-DEP-022", "NONE", "FORFEITURE_REQUIRED", 1_000)
    assert len(issues(view, "FORFEITURE_NOT_CONFIRMED")) == 2
    for deposit in (security, pet):
        forfeit_through_draft(service, deposit)
    view = preview(prop, human, settlement)
    assert path_of(view, pet) == ("BR-DEP-022", "ACTIVE", "KEPT", 0)
    assert issues(view, "FORFEITURE_NOT_CONFIRMED") == []
    disposition = UUID(
        str(scalar(url, "SELECT id FROM app.deposit_dispositions WHERE deposit_id=%s", pet))
    )
    reverse_through_draft(service, disposition)
    view = preview(prop, human, settlement)
    assert path_of(view, pet) == ("BR-DEP-022", "REVERSED", "DL_032", 1_000)
    assert path_of(view, security) == ("BR-DEP-022", "ACTIVE", "KEPT", 0)
    # Pet noncompliance is not a BR-DEP-027 termination, so the DL-013 staff step stays (owner
    # answer 2 to Q-2026-10-05-25); the Security Deposit stays kept.
    assert step(view, 5)["chosen_by"] == "CUSTOMER_OR_STAFF_WITH_REASON"
    assert step(view, 5)["deposits"] == [
        {"deposit_id": str(pet), "may_use_usd_cents": min(1_000, view["open_total_usd_cents"])}
    ]
    assert step(view, 4)["deposits"] == [] and step(view, 7)["deposits"] == [str(pet)]
    stage = ("SECURITY_EXPLICIT", "INVOICE_LINE", line)
    assert refused(url, prop, human, settlement, security, *stage, 100, 1) == "23514"
    apply(
        url, prop, human, settlement, pet, "PET_REMAINDER_EXPLICIT", "INVOICE_LINE", line, 1_000, 1
    )
    assert held(url, pet) == 0


def test_a_br_dep_027_termination_keeps_security_and_lets_only_the_customer_choose(
    migrated_database_url: str,
) -> None:
    """Non-pet violation (BR-LEASE-025): the Security Deposit waits for its forfeiture, the Pet
    Deposit follows DL-032 and its remainder pays other debt only by the Customer's choice."""
    url = migrated_database_url
    human, prop, lease, security, pet, _invoice, _line, day = lease_with_charge(url)
    seed_historical_deposit_receipt(url, deposit_id=pet, actor_id=human, amount_usd_cents=1_000)
    terminate_on(
        url,
        human,
        prop,
        lease,
        day,
        "BR-LEASE-025",
        TerminationBasis.CUSTOMER_VIOLATION,
        warnings=True,
    )
    view = preview(prop, human, start(prop, human, lease))
    assert view["lease"]["termination_ground"] == "BR-LEASE-025"
    assert path_of(view, security) == (
        "BR-LEASE-025",
        "NONE",
        "FORFEITURE_REQUIRED",
        held(url, security),
    )
    assert path_of(view, pet) == (None, "NONE", "DL_032", 1_000)
    assert step(view, 5)["chosen_by"] == "CUSTOMER_ONLY"
    assert [item["deposit_id"] for item in step(view, 5)["deposits"]] == [str(pet)]
    assert step(view, 4)["deposits"] == [] and step(view, 7)["deposits"] == [str(pet)]


def test_a_kept_deposit_that_holds_nothing_does_not_block_the_settlement(
    migrated_database_url: str,
) -> None:
    """A Pet Deposit never paid at a pet-noncompliance termination has nothing to forfeit."""
    url = migrated_database_url
    human, prop, lease, security, pet, _invoice, line, day = lease_with_charge(url)
    assert held(url, pet) == 0
    service = PostgresDepositService(financial_database_url(), prop, human)
    terminate_for_disposition(url, service, lease, day)
    settlement = start(prop, human, lease)
    view = preview(prop, human, settlement)
    assert path_of(view, pet) == ("BR-DEP-022", "NONE", "NOTHING_HELD", 0)
    assert [item["deposit_id"] for item in issues(view, "FORFEITURE_NOT_CONFIRMED")] == [
        str(security)
    ]
    assert str(pet) not in step(view, 7)["deposits"]
    stage = ("PET_REMAINDER_EXPLICIT", "INVOICE_LINE", line)
    # The path guard refuses before any amount check.
    with pytest.raises(psycopg.Error) as failure:
        apply(url, prop, human, settlement, pet, *stage, 1, 1)
    assert failure.value.sqlstate == "23514"
    assert failure.value.diag.message_primary == (
        "A kept Deposit is never applied to what the Customer owes"
    )
    forfeit_through_draft(service, security)
    assert issues(preview(prop, human, settlement), "FORFEITURE_NOT_CONFIRMED") == []


def test_obligations_and_credit_stay_with_each_customer_of_the_lease(
    migrated_database_url: str,
) -> None:
    """Another Signer's Invoice is a Settlement obligation of that Signer; a Customer's Credit
    may pay only that Customer's obligations (BR-CREDIT-008)."""
    url = migrated_database_url
    case = another_signer_invoice(url)
    human, prop, tenant, co_signer = case["human"], case["prop"], case["tenant"], case["co_signer"]
    payer = pay(
        url, prop, human, co_signer, case["invoice"], case["line"], outstanding(url, case["line"])
    )
    credit_adjustment(url, human, prop, case["invoice"], case["line"])
    credit = UUID(
        str(scalar(url, "SELECT id FROM app.customer_credits WHERE source_payment_id=%s", payer))
    )
    staff = invoice_api_actor(human, prop)
    charge = key_card(tenant, case["lease"])
    invoices().record_one_time_charge(prop, charge, actor=staff)
    tenant_invoice = draft_and_issue(prop, charge.charge_id, staff)
    settlement = start(prop, human, case["lease"])
    view = preview(prop, human, settlement, APPROVE)
    tenant_view, signer_view = view["customers"]
    assert (tenant_view["customer_id"], tenant_view["primary_tenant"]) == (str(tenant), True)
    assert (signer_view["customer_id"], signer_view["primary_tenant"]) == (str(co_signer), False)
    assert [item["invoice_id"] for item in tenant_view["invoice_lines"]] == [tenant_invoice["id"]]
    assert tenant_view["open_total_usd_cents"] == 1_500 and tenant_view["credits"] == []
    assert signer_view["invoice_lines"] == [] and signer_view["open_total_usd_cents"] == 0
    assert signer_view["credits"] == [
        {"customer_credit_id": str(credit), "available_usd_cents": 400}
    ]
    assert signer_view["credit_may_use_usd_cents"] == 0
    assert step(view, 2)["customers"] == [
        {"customer_id": str(tenant), "may_use_usd_cents": 0},
        {"customer_id": str(co_signer), "may_use_usd_cents": 0},
    ]
    # The Deposits may pay any open debt of the Lease, whoever is named (owner answer 5).
    assert step(view, 5)["deposits"] == [
        {"deposit_id": str(case["pet"]), "may_use_usd_cents": view["open_total_usd_cents"]}
    ]
    # A pending receipt reversal draft of the Lease's Deposit blocks the Settlement too.
    receipt = UUID(
        str(scalar(url, "SELECT id FROM app.deposit_receipts WHERE deposit_id=%s", case["pet"]))
    )
    reversal = DepositReceiptReversalService(financial_database_url()).record(
        prop,
        RecordDepositReceiptReversalCommand(
            uuid4(), receipt, uuid4(), "Transfer returned by the bank"
        ),
        actor=person(human, prop, "deposits.correct"),
    )
    assert issues(preview(prop, human, settlement, APPROVE), "PENDING_DRAFT") == [
        shown(reversal, "DEPOSIT_FORFEITURE", "DEPOSIT_RECEIPT_REVERSAL")
    ]


def test_a_moved_out_lease_waits_for_final_utility_cleaning_and_billed_periods(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    leaver = departed(url, 1, 4)
    dep = leaver.dep
    human, prop, lease, unit = dep.human, dep.prop, dep.lease, dep.unit
    settlement = start(prop, human, lease)

    def utility(view: dict[str, Any]) -> list[str]:
        return [item["reason"] for item in issues(view, "FINAL_UTILITY_NOT_ISSUED")]

    def cleaning(view: dict[str, Any]) -> list[tuple[str, Any]]:
        return [
            (item["reason"], item["rate_usd_cents"])
            for item in issues(view, "CLEANING_CHARGE_MISSING")
        ]

    view = preview(prop, human, settlement)
    assert view["lease"]["moved_in"] is True
    assert view["lease"]["move_out_date"] == dep.move_out_date.isoformat()
    assert utility(view) == ["FINAL_INPUTS_NOT_RECORDED"]
    assert cleaning(view) == [("NO_RATE", None)]
    pending = record_final(leaver, (missing(dep.electricity),))
    assert utility(preview(prop, human, settlement)) == ["FINAL_INPUT_UNRESOLVED"]
    reading = final_reading(url, leaver, dep.electricity, "150")
    resolved = record_final(leaver, (used(dep.electricity, reading),), supersedes=pending)
    assert utility(preview(prop, human, settlement)) == ["FINAL_INVOICE_NOT_ISSUED"]
    create_final(leaver, resolved)
    view = preview(prop, human, settlement)
    assert utility(view) == [] and issues(view, "UTILITY_PERIOD_NOT_BILLED") == []
    # Cleaning: the Unit's current rate decides (owner answer 1 to Q-2026-10-05-25).
    staff = person(
        human, prop, "invoices.read", "invoices.create", "invoices.issue", "property.manage"
    )
    rate = invoices().set_unit_cleaning_rate(
        prop, SetUnitCleaningRateCommand(uuid4(), unit, None, 2_500, "Configured rate"), actor=staff
    )
    assert cleaning(preview(prop, human, settlement)) == [("NOT_ISSUED", 2_500)]
    zero = invoices().set_unit_cleaning_rate(
        prop,
        SetUnitCleaningRateCommand(uuid4(), unit, UUID(str(rate["id"])), 0, "No cleaning charge"),
        actor=staff,
    )
    assert cleaning(preview(prop, human, settlement)) == []
    again = invoices().set_unit_cleaning_rate(
        prop,
        SetUnitCleaningRateCommand(uuid4(), unit, UUID(str(zero["id"])), 2_500, "Rate restored"),
        actor=staff,
    )
    charge = RecordUnitCleaningChargeCommand(uuid4(), lease, UUID(str(again["id"])))
    invoices().record_unit_cleaning_charge(prop, charge, actor=staff)
    view = preview(prop, human, settlement)
    assert cleaning(view) == [("NOT_ISSUED", 2_500)]
    assert [
        item["authorized_obligation_id"] for item in issues(view, "ONE_TIME_CHARGE_NOT_INVOICED")
    ] == [str(charge.charge_id)]
    draft = invoices().create_draft(
        prop, CreateInvoiceDraftCommand(uuid4(), charge.charge_id), actor=staff
    )
    view = preview(prop, human, settlement)
    # A recorded charge on an Invoice draft is not yet on an issued Invoice.
    assert cleaning(view) == [("NOT_ISSUED", 2_500)]
    assert issues(view, "ONE_TIME_CHARGE_NOT_INVOICED") == []
    assert [item["invoice_id"] for item in issues(view, "INVOICE_DRAFT_NOT_ISSUED")] == [
        draft["id"]
    ]
    invoices().issue(
        prop,
        UUID(str(draft["id"])),
        IssueInvoiceCommand(uuid4(), cast(int, draft["version"])),
        actor=staff,
    )
    view = preview(prop, human, settlement)
    assert not codes(view) & {"CLEANING_CHARGE_MISSING", "INVOICE_DRAFT_NOT_ISSUED"}
    # Once every kept Deposit's forfeiture is confirmed, nothing blocks the Settlement.
    service = PostgresDepositService(financial_database_url(), prop, human)
    for item in view["deposits"]:
        if item["path"] == "FORFEITURE_REQUIRED":
            forfeit_through_draft(service, UUID(item["deposit_id"]))
    view = preview(prop, human, settlement)
    assert view["blocking_issues"] == [] and view["ready"] is True
    # A Utility period of this Lease finalized after the final Utility Invoice, with
    # consumption and on no Invoice, blocks again (owner answer 3 to Q-2026-10-05-25).
    period = water_period(url, leaver)
    view = preview(prop, human, settlement)
    assert [
        (item["utility_consumption_period_id"], item["utility_type"])
        for item in issues(view, "UTILITY_PERIOD_NOT_BILLED")
    ] == [(str(period), "WATER")]
    assert view["ready"] is False


def test_a_final_reading_without_consumption_needs_no_final_utility_invoice(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    leaver = departed(url, 2, 4)
    dep = leaver.dep
    settlement = start(dep.prop, dep.human, dep.lease)
    reading = final_reading(url, leaver, dep.electricity, "100")
    record_final(leaver, (used(dep.electricity, reading),))
    view = preview(dep.prop, dep.human, settlement)
    assert issues(view, "FINAL_UTILITY_NOT_ISSUED") == []
    # Before the final Utility Invoice, a period with consumption on no Invoice blocks twice:
    # the final Invoice is due and the period is not billed (owner answer 3 to Q-2026-10-05-25).
    period = water_period(url, leaver)
    view = preview(dep.prop, dep.human, settlement)
    assert [item["reason"] for item in issues(view, "FINAL_UTILITY_NOT_ISSUED")] == [
        "FINAL_INVOICE_NOT_ISSUED"
    ]
    assert [
        item["utility_consumption_period_id"] for item in issues(view, "UTILITY_PERIOD_NOT_BILLED")
    ] == [str(period)]


def test_a_unit_with_no_meter_needs_no_final_utility_inputs(
    migrated_database_url: str,
) -> None:
    # V1-058 R7b-7 (owner 2026-10-26, "Meters decide"): a store room with no electricity or water
    # has no Meter, so no final readings and no final Utility Invoice hold its Settlement.
    leaver = departed(migrated_database_url, 3, 4, with_meter=False)
    dep = leaver.dep
    settlement = start(dep.prop, dep.human, dep.lease)
    view = preview(dep.prop, dep.human, settlement)
    assert view["lease"]["moved_in"] is True
    assert issues(view, "FINAL_UTILITY_NOT_ISSUED") == []
    assert issues(view, "UTILITY_PERIOD_NOT_BILLED") == []
    # The Home "Refund due by" to-do counts from the inspection alone (DL-073 item 4).
    lease_version = int(
        scalar(migrated_database_url, "SELECT version FROM app.leases WHERE id=%s", dep.lease)
    )
    PostgresMoveOutInspectionService(runtime_database_url(), financial_database_url()).record(
        dep.prop,
        dep.lease,
        RecordMoveOutInspection(
            uuid4(),
            uuid4(),
            lease_version,
            dep.move_out_date,
            "Store room empty and clean",
            "Approved inspection",
            "Evidence-238",
            "Final inspection",
            (InspectionFinding(uuid4(), "Door condition", False),),
        ),
        actor=person(dep.human, dep.prop, INSPECTION_READ, INSPECTION_RECORD),
        request_id="inspect-238",
    )
    with psycopg.connect(runtime_database_url()) as connection:
        row = connection.execute(
            "SELECT app.home_page(%s,%s,%s::uuid[],%s::text[])",
            (dep.human, dep.prop, [dep.prop], ["settlements"]),
        ).fetchone()
    assert row is not None
    due = [
        item
        for item in cast(dict[str, Any], row[0])["todo"]
        if item["kind"] == "refund_due" and item["lease_id"] == str(dep.lease)
    ]
    assert [item["date"] for item in due] == [(dep.move_out_date + timedelta(days=7)).isoformat()]


def test_a_meter_in_on_the_hand_back_day_still_needs_final_inputs(
    migrated_database_url: str,
) -> None:
    # The no-Meter rule counts the Meters the final inputs must name: a Meter put in after the
    # hand-back day is not one of them; a Meter in on the hand-back day itself is.
    url = migrated_database_url
    leaver = departed(url, 4, 4, with_meter=False)
    dep = leaver.dep
    settlement = start(dep.prop, dep.human, dep.lease)

    def utility(view: dict[str, Any]) -> list[str]:
        return [item["reason"] for item in issues(view, "FINAL_UTILITY_NOT_ISSUED")]

    with psycopg.connect(url) as connection:
        add_meter(
            connection,
            actor_id=dep.human,
            unit_id=dep.unit,
            installed_date=dep.move_out_date + timedelta(days=1),
        )
    assert utility(preview(dep.prop, dep.human, settlement)) == []
    with psycopg.connect(url) as connection:
        add_meter(
            connection,
            actor_id=dep.human,
            unit_id=dep.unit,
            utility_type="WATER",
            measurement_unit_code="M3",
            installed_date=dep.move_out_date,
        )
    assert utility(preview(dep.prop, dep.human, settlement)) == ["FINAL_INPUTS_NOT_RECORDED"]


def test_withdrawn_one_time_charges_do_not_block_and_voided_ones_are_listed(
    migrated_database_url: str,
) -> None:
    """Owner answer to Q-2026-10-05-27: only a charge still waiting to be billed blocks."""
    url = migrated_database_url
    now = today(url)
    with psycopg.connect(url) as connection:
        human, prop, customer, lease = setup_signed_lease(
            connection, start_date=date(now.year - 1, 1, 1), end_date=date(now.year + 1, 12, 31)
        )
    staff = invoice_api_actor(human, prop)
    # A charge billed by mistake and VOIDed with a reason.
    voided = key_card(customer, lease)
    invoices().record_one_time_charge(prop, voided, actor=staff)
    issued = draft_and_issue(prop, voided.charge_id, staff)
    invoices().void(
        prop,
        UUID(str(issued["id"])),
        VoidInvoiceCommand(uuid4(), "Key card was returned", cast(int, issued["version"])),
        actor=staff,
    )
    # A charge on an Invoice draft that a draft correction replaced with another charge.
    replaced = key_card(customer, lease)
    invoices().record_one_time_charge(prop, replaced, actor=staff)
    draft = invoices().create_draft(
        prop, CreateInvoiceDraftCommand(uuid4(), replaced.charge_id), actor=staff
    )
    replacement = key_card(customer, lease)
    invoices().record_one_time_charge(prop, replacement, actor=staff)
    corrected = invoices().correct_draft(
        prop,
        UUID(str(draft["id"])),
        CorrectInvoiceDraftCommand(
            uuid4(), replacement.charge_id, "Wrong charge on the draft", cast(int, draft["version"])
        ),
        actor=staff,
    )
    # A charge recorded later and never put on an Invoice.
    waiting = key_card(customer, lease)
    invoices().record_one_time_charge(prop, waiting, actor=staff)
    terminate(url, human, prop, lease, now, voluntary=False)
    settlement = start(prop, human, lease)
    view = preview(prop, human, settlement)
    assert [
        item["authorized_obligation_id"] for item in issues(view, "ONE_TIME_CHARGE_NOT_INVOICED")
    ] == [str(waiting.charge_id)]
    # The replacement charge is checked like any other: its Invoice draft blocks until issued.
    assert [item["invoice_id"] for item in issues(view, "INVOICE_DRAFT_NOT_ISSUED")] == [
        draft["id"]
    ]
    voided_info = {
        "code": "VOIDED_CHARGE_NOT_BILLED_AGAIN",
        "authorized_obligation_id": str(voided.charge_id),
        "customer_id": str(customer),
        "category": "MISCELLANEOUS_CHARGES",
        "amount_usd_cents": 1_500,
    }
    # Narrowed in V1-056 sub-slice 8c (owner answer to Q-2026-10-05-28): the replaced charge is
    # listed too, with the charge that replaced it; it still does not block.
    replaced_info = {
        "code": "CHARGE_REPLACED_BY_DRAFT_CORRECTION",
        "authorized_obligation_id": str(replaced.charge_id),
        "customer_id": str(customer),
        "category": "MISCELLANEOUS_CHARGES",
        "amount_usd_cents": 1_500,
        "replacement_authorized_obligation_id": str(replacement.charge_id),
        "replacement_lease_id": str(lease),
    }
    assert view["information"] == [voided_info, replaced_info]
    invoices().issue(
        prop,
        UUID(str(draft["id"])),
        IssueInvoiceCommand(uuid4(), cast(int, corrected["version"])),
        actor=staff,
    )
    after = draft_and_issue(prop, waiting.charge_id, staff)
    view = preview(prop, human, settlement)
    assert not codes(view) & {"ONE_TIME_CHARGE_NOT_INVOICED", "INVOICE_DRAFT_NOT_ISSUED"}
    assert view["information"] == [voided_info, replaced_info]
    lines = {item["invoice_id"] for item in view["customers"][0]["invoice_lines"]}
    assert {draft["id"], after["id"]} <= lines and issued["id"] not in lines


def test_unpaid_initial_and_default_terminations_let_only_the_customer_choose(
    migrated_database_url: str,
) -> None:
    """BR-DEP-027 terminations: BR-LEASE-005 with nothing held can become ready; BR-LEASE-028."""
    url = migrated_database_url
    source = signed_with_initial(url, 10)
    terminate_unpaid(url, source)
    prop, human, deposit = source["property"], source["actor"], source["deposit"]
    with psycopg.connect(url) as connection:
        receipts = connection.execute(
            "SELECT id FROM app.deposit_receipts WHERE deposit_id=%s ORDER BY occurred_at,id",
            (deposit,),
        ).fetchall()
    for (receipt,) in receipts:
        reverse_receipt_through_draft(financial_database_url(), prop, human, UUID(str(receipt)))
    view = preview(prop, human, start(prop, human, source["lease"]))
    assert view["lease"]["termination_ground"] == "BR-LEASE-005"
    assert path_of(view, deposit) == ("BR-LEASE-005", "NONE", "NOTHING_HELD", 0)
    assert step(view, 5)["chosen_by"] == "CUSTOMER_ONLY"
    assert view["blocking_issues"] == [] and view["ready"] is True
    # 30-day Rent nonpayment default (BR-LEASE-028) with its recorded Serious Default event.
    source = signed_with_initial(url, 120)
    human, prop, lease = source["actor"], source["property"], source["lease"]
    period = (source["today"] - timedelta(days=35)).replace(day=1)
    with psycopg.connect(url) as connection:
        _, rent_line = create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=source["customer"],
            lease_id=lease,
            period_start=period,
        )
    flow = enforcement()
    case = open_case(flow, prop, lease, rent_line, human)
    record_nonpayment_event(
        flow, prop, lease, case, human, NonpaymentEventKind.THIRTY_DAY_SERIOUS_DEFAULT
    )
    terminate_on(
        url,
        human,
        prop,
        lease,
        source["today"],
        "BR-LEASE-028",
        TerminationBasis.SIGNED_LEASE_OTHER,
        warnings=False,
    )
    view = preview(prop, human, start(prop, human, lease))
    assert view["lease"]["termination_ground"] == "BR-LEASE-028"
    assert step(view, 5)["chosen_by"] == "CUSTOMER_ONLY"


def test_the_preview_refuses_unknown_actors_and_settlements_and_is_least_privilege(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, lease, security, _pet, _invoice, _line, day = lease_with_charge(url)
    # The kept rule keeps its earlier errors: an unknown Deposit or another Property is not
    # found, and a Lease that is not terminated is refused.
    for kept, sqlstate in (
        ((prop, uuid4()), "P0002"),
        ((uuid4(), security), "P0002"),
        ((prop, security), "22023"),
    ):
        with psycopg.connect(url) as connection:
            with pytest.raises(psycopg.Error) as failure:
                connection.execute("SELECT app.lease_deposit_kept_rule(%s,%s)", kept)
        assert failure.value.sqlstate == sqlstate, kept
    terminate(url, human, prop, lease, day, voluntary=False)
    settlement = start(prop, human, lease)
    with pytest.raises(FinalSettlementNotFoundError):
        preview(prop, human, uuid4())
    with psycopg.connect(url) as connection:
        service_actor = register_billing_service_principal(
            connection, property_id=prop, created_by=human
        )
    allowed = ["final_settlements.prepare"]
    for arguments, sqlstate in (
        ((prop, uuid4(), settlement, allowed), "42501"),
        ((prop, service_actor, settlement, allowed), "42501"),
        ((uuid4(), human, settlement, allowed), "P0002"),
        ((prop, human, None, allowed), "22023"),
        ((prop, human, settlement, None), "22023"),
        ((prop, human, settlement, []), "22023"),
        ((prop, human, settlement, [None]), "22023"),
        ((prop, human, settlement, ["final_settlements.prepare"] * 11), "22023"),
    ):
        with psycopg.connect(runtime_database_url()) as connection:
            with pytest.raises(psycopg.Error) as failure:
                connection.execute(PREVIEW_SQL, arguments)
        assert failure.value.sqlstate == sqlstate, arguments
    with psycopg.connect(url) as connection:
        for role, expected in (
            ("prm_runtime", True),
            ("prm_financial", False),
            ("prm_bootstrap", False),
            ("prm_human_admin", False),
        ):
            assert connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, PREVIEW)
            ).fetchone() == (expected,), role
            for function in INTERNAL:
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (role, function)
        for function in (PREVIEW, *INTERNAL):
            row = connection.execute(
                "SELECT p.prosecdef,p.provolatile,p.proconfig,"
                "has_function_privilege('public',p.oid,'EXECUTE') "
                "FROM pg_proc p WHERE p.oid=CAST(%s AS regprocedure)",
                (function,),
            ).fetchone()
            assert row is not None
            assert (row[0], row[1], row[3]) == (True, "s", False), function
            assert "search_path=pg_catalog" in row[2], function
        # Only the 4-argument preview exists (an earlier 3-argument version was never kept).
        assert connection.execute(
            "SELECT to_regprocedure('app.final_settlement_preview(uuid,uuid,uuid)')"
        ).fetchone() == (None,)
        # A deactivated person may not read the preview.
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    with psycopg.connect(runtime_database_url()) as connection:
        with pytest.raises(psycopg.Error) as failure:
            connection.execute(PREVIEW_SQL, (prop, human, settlement, allowed))
    assert failure.value.sqlstate == "42501"


def test_final_settlement_preview_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261024_89")
    assert revision is not None and revision.down_revision == "20261023_88"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
