"""V1-056 sub-slice 8e-3: a financial.approve holder confirms the Final Settlement draft and the
Settlement closes for good, with every amount checked to the cent.

The Leases here start on the first day of the current month (``this_month``), so their Initial
Rent covers every day up to the termination today and no recurring Rent month falls inside their
coverage on any date the suite runs (RENT_PERIOD_NOT_BILLED, owner answer 2 to Q-2026-10-06-33).
"""

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from lease_deposit_forfeiture_test_support import forfeit_through_draft, reverse_through_draft
from property_rental.customer_ledger import LedgerPosition
from property_rental.deposit import PostgresDepositService
from property_rental.final_settlement import (
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementInvalidError,
    FinalSettlementNotFoundError,
    FinalSettlementStaleDraftError,
    SettlementCreditStep,
    SettlementDepositStep,
    SettlementTargetKind,
)
from property_rental.invoice import (
    CreateInvoiceDraftCommand,
    RecordOneTimeChargeCommand,
    ResolveHandBackRentCommand,
    SetUnitCleaningRateCommand,
    VoidInvoiceCommand,
)
from property_rental.lease_deposit_forfeiture import RecordLeaseDepositForfeitureCommand
from rent_month_test_support import bill_unbilled_rent_months, unbilled_rent_months
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_draft_migration import (
    CHOICE,
    LINE,
    PET_FIRST,
    PET_REST,
    REASON,
    SECURITY,
    STAFF,
    drafts,
    leaving_case,
    normal_plan,
    record,
    refund,
    settlements,
    two_signer_case,
    withdraw,
)
from test_final_settlement_migration import held, line_of, one, outstanding, start, today
from test_final_settlement_preview_migration import (
    credit_adjustment,
    forfeitures,
    issues,
    key_card,
    path_of,
    pay,
    person,
    preview,
)
from test_final_utility_invoice_migration import create_final, departed, final_reading, record_final
from test_hand_back_rent_migration import (
    AUGUST,
    SEPTEMBER,
    Scenario,
    correct_move_out,
    hand_back,
    lease_with_invoices,
)
from test_hand_back_rent_migration import hand_back_database as hand_back_database
from test_hand_back_rent_migration import invoices as hand_back_invoices
from test_hand_back_rent_migration import staff as hand_back_staff
from test_hand_back_rent_migration import version as invoice_version
from test_invoice_migration import (
    create_recurring_rent_invoice,
    financial_database_url,
    invoice_api_actor,
    runtime_database_url,
    setup_signed_lease,
)
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_out_final_inputs_migration import used
from test_one_time_charges_migration import draft_and_issue, invoices
from test_one_time_charges_migration import staff as invoice_staff
from test_termination_deposit_migration import terminate
from test_unpaid_initial_termination_migration import signed_with_initial

APPROVE = "financial.approve"
PREPARE = "final_settlements.prepare"
CONFIRM = "app.confirm_final_settlement_draft(uuid,uuid,uuid,text)"
CONFIRM_SQL = "SELECT app.confirm_final_settlement_draft(%s,%s,%s,%s)"
INTERNAL = (
    "app.final_settlement_unbilled_rent_months(uuid,timestamp with time zone)",
    "app.final_settlement_deposit_application_id(uuid,integer)",
    "app.final_settlement_refund_id(uuid,uuid)",
    "app.validate_settlement_closure_item()",
    "app.assert_settlement_closure_reconciled()",
)
TABLES = (
    "app.settlement_invoice_items",
    "app.settlement_late_payment_charge_items",
    "app.settlement_invoice_line_items",
)
STALE = "The Final Settlement draft is stale; its sources changed"
BLOCKED = "The Final Settlement has blocking issues"
UNRECONCILED = "Final Settlement closure snapshots must reconcile to its closing balance"
NOTHING_WRITTEN = (0, 0, 0, 0, 0, False)
DESIGNATION = "Primary Tenant asked on 2026-10-06, by signed note, to clear the late charge first"


def this_month(url: str) -> int:
    """The start offset that starts the Lease on the first day of the current month."""
    return today(url).day - 1


def confirm(case: dict[str, Any], draft: dict[str, object], approver: UUID | None = None) -> Any:
    return settlements().confirm(
        case["prop"],
        UUID(str(draft["draft_id"])),
        actor=person(approver or case["human"], case["prop"], APPROVE),
    )


def refusal(call: Any, *args: Any) -> tuple[type[Exception], Any, Any]:
    """The service error and the database refusal behind it: SQLSTATE and message."""
    with pytest.raises(
        (
            FinalSettlementConflictError,
            FinalSettlementAuthorizationError,
            FinalSettlementInvalidError,
            FinalSettlementNotFoundError,
        )
    ) as failure:
        call(*args)
    cause = failure.value.__cause__
    assert isinstance(cause, psycopg.Error)
    return type(failure.value), cause.sqlstate, cause.diag.message_primary


def state(url: str, draft: dict[str, object]) -> str:
    return str(
        one(
            url,
            "SELECT COALESCE((SELECT decision FROM app.financial_draft_decisions "
            "WHERE draft_id=%s),'PENDING')",
            UUID(str(draft["draft_id"])),
        )[0]
    )


def written(url: str, settlement: UUID) -> tuple[Any, ...]:
    """Credit applications, Deposit applications, Refunds, Invoice, line and Charge snapshots of
    the Settlement, and whether it is closed."""
    return one(
        url,
        "SELECT (SELECT count(*) FROM app.customer_credit_applications "
        "WHERE final_settlement_id=%s),"
        "(SELECT count(*) FROM app.deposit_applications WHERE final_settlement_id=%s),"
        "(SELECT count(*) FROM app.final_settlement_refund_details WHERE final_settlement_id=%s),"
        "(SELECT count(*) FROM app.settlement_invoice_items WHERE final_settlement_id=%s),"
        "(SELECT count(*) FROM app.settlement_late_payment_charge_items "
        "WHERE final_settlement_id=%s),"
        "(SELECT closed_at IS NOT NULL FROM app.final_settlements WHERE id=%s)",
        *(settlement,) * 6,
    )


def ledger(url: str, customer: UUID) -> LedgerPosition:
    """The Customer Ledger position, reconciled to its sources (DEPOSIT_APPLIED included)."""
    with psycopg.connect(url) as connection:
        return assert_reconciled(connection, customer)


def rows(url: str, sql: str, *parameters: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(sql, parameters).fetchall()


def credit_rows(url: str, settlement: UUID) -> list[tuple[Any, ...]]:
    return rows(
        url,
        "SELECT application.customer_credit_id,application.target_kind,"
        "COALESCE(detail.invoice_line_id,detail.late_payment_charge_id),application.amount_usd_cents,"
        "application.within_invoice_basis,application.customer_designation_reference,"
        "detail.attribution_basis,application.authorization_reference "
        "FROM app.customer_credit_applications application "
        "JOIN app.customer_credit_application_details detail "
        "ON detail.customer_credit_application_id=application.id "
        "WHERE application.final_settlement_id=%s ORDER BY application.occurred_at",
        settlement,
    )


def deposit_rows(url: str, settlement: UUID) -> list[tuple[Any, ...]]:
    return rows(
        url,
        "SELECT deposit_id,application_stage,target_kind,"
        "COALESCE(invoice_line_id,late_payment_charge_id),amount_usd_cents,application_order,"
        "reason "
        "FROM app.deposit_applications WHERE final_settlement_id=%s ORDER BY application_order",
        settlement,
    )


def refund_rows(url: str, settlement: UUID) -> list[tuple[Any, ...]]:
    return rows(
        url,
        "SELECT refund.source_deposit_id,refund.usd_accounting_value_cents,"
        "refund.recipient_customer_id,refund.processed_by,refund.authorization_reference "
        "FROM app.final_settlement_refund_details detail "
        "JOIN app.refunds refund ON refund.id=detail.refund_id "
        "WHERE detail.final_settlement_id=%s ORDER BY refund.source_deposit_id",
        settlement,
    )


def line_snapshots(url: str, settlement: UUID) -> dict[UUID, tuple[Any, ...]]:
    found = rows(
        url,
        "SELECT line.invoice_line_id,line.category_snapshot,line.original_amount_usd_cents,"
        "line.adjustment_net_usd_cents,line.payment_allocated_usd_cents,"
        "line.credit_applied_usd_cents,line.deposit_applied_usd_cents,"
        "line.closing_outstanding_usd_cents "
        "FROM app.settlement_invoice_line_items line "
        "JOIN app.settlement_invoice_items item ON item.id=line.settlement_invoice_item_id "
        "WHERE item.final_settlement_id=%s",
        settlement,
    )
    return {UUID(str(row[0])): tuple(row[1:]) for row in found}


def invoice_of(url: str, line: UUID) -> UUID:
    return UUID(str(one(url, "SELECT invoice_id FROM app.invoice_lines WHERE id=%s", line)[0]))


def owner_draft(
    url: str, case: dict[str, Any], kind: str, capability: str, payload: dict[str, object]
) -> dict[str, object]:
    """A draft written as the table owner, past the recorder's own refusals; a FINAL_SETTLEMENT
    draft gets the current source digest, as if it had been recorded just before."""
    arguments: tuple[object, ...] = (
        case["prop"],
        case["human"],
        uuid4(),
        kind,
        capability,
        Jsonb(payload),
    )
    if kind == "FINAL_SETTLEMENT":
        revision = (
            "'final-settlement:'||encode(sha256(convert_to("
            "app.final_settlement_source_state(%s,%s)::text,'UTF8')),'hex')"
        )
        arguments += (case["prop"], case["settlement"])
    else:
        revision = "NULL"
    found = one(
        url,
        f"SELECT app.insert_financial_draft(%s,%s,%s,%s,%s,%s,{revision},%s)",
        *arguments,
        "Written for the test",
    )
    return cast(dict[str, object], found[0])


def test_a_normal_end_applies_credit_and_deposits_and_refunds_the_rest_to_the_cent(
    migrated_database_url: str,
) -> None:
    """A Lease that ends with no forfeiture ground (the normal-end path, DL-032): Customer Credit
    first, the Pet Deposit pays the pet damage, the Security Deposit pays the open debt, and what
    remains in each Deposit is refunded; nothing stays open. Only a financial.approve holder
    confirms; an exact repeat replays; the Settlement is never changed again."""
    url = migrated_database_url
    case = leaving_case(url, start_offset=this_month(url))
    human, prop, customer, settlement = (
        case["human"],
        case["prop"],
        case["customer"],
        case["settlement"],
    )
    security, pet, pet_line, other_line = (
        case["security"],
        case["pet"],
        case["pet_line"],
        case["other_line"],
    )
    other_invoice, pet_invoice = invoice_of(url, other_line), invoice_of(url, pet_line)
    pay(url, prop, human, customer, other_invoice, other_line, 9_100)
    assert (outstanding(url, pet_line), outstanding(url, other_line)) == (12_500, 3_400)
    assert (held(url, security), held(url, pet)) == (10_000, 20_000)
    plan = (
        SettlementCreditStep(case["credit"], LINE, other_line, 400),
        SettlementDepositStep(PET_FIRST, pet, LINE, pet_line, 12_500),
        SettlementDepositStep(SECURITY, security, LINE, other_line, 3_000),
        refund(case, "security", 7_000),
        refund(case, "pet", 7_500),
    )
    draft = record(case, plan)
    draft_id = UUID(str(draft["draft_id"]))
    assert cast(dict[str, Any], draft["payload"])["closing_balance_usd_cents"] == 0
    # BR-AUTH-010: preparing a Settlement never confirms it, in the service and in the database.
    with pytest.raises(FinalSettlementAuthorizationError):
        settlements().confirm(prop, draft_id, actor=person(human, prop, PREPARE))
    with pytest.raises(psycopg.Error) as wrong, psycopg.connect(url) as connection:
        connection.execute(CONFIRM_SQL, (prop, human, draft_id, PREPARE))
    assert (wrong.value.sqlstate, wrong.value.diag.message_primary) == (
        "42501",
        "Only financial.approve may confirm a Final Settlement draft",
    )
    assert written(url, settlement) == NOTHING_WRITTEN and state(url, draft) == "PENDING"

    # Staff prepared the draft; another person holding financial.approve confirms it, and every
    # record the confirm writes names that approver (review round 2).
    with psycopg.connect(url) as connection:
        approver = setup_signed_lease(connection)[0]
    confirmed = confirm(case, draft, approver)
    result = confirmed["result"]
    assert confirmed["draft"]["state"] == "CONFIRMED"
    assert confirmed["draft"]["prepared_by"] == str(human)
    assert confirmed["draft"]["decision"]["decided_by"] == str(approver)
    assert confirmed["settlement"]["closed"] is True
    assert confirmed["settlement"]["closing_balance_due_usd_cents"] == 0
    assert (result["closing_balance_usd_cents"], result["closing_balances"]) == (0, [])
    # Customer Credit used (DL-032 step 2): 400 on the Damage Invoice, under financial.approve.
    assert credit_rows(url, settlement) == [
        (
            case["credit"],
            "INVOICE",
            other_line,
            400,
            "OTHER_APPLICABLE_OBLIGATION",
            None,
            "OTHER_CONFIRMED",
            APPROVE,
        )
    ]
    # Pet damage paid first, then the Security Deposit applied (DL-032 steps 3 and 4).
    assert deposit_rows(url, settlement) == [
        (pet, "PET_RELATED_FIRST", "INVOICE_LINE", pet_line, 12_500, 1, REASON),
        (security, "SECURITY_EXPLICIT", "INVOICE_LINE", other_line, 3_000, 2, REASON),
    ]
    # What remains in each Deposit is refunded to the Primary Tenant (DL-032 step 7).
    assert refund_rows(url, settlement) == sorted(
        [
            (security, 7_000, customer, approver, APPROVE),
            (pet, 7_500, customer, approver, APPROVE),
        ]
    )
    assert (held(url, security), held(url, pet)) == (0, 0)
    assert (outstanding(url, pet_line), outstanding(url, other_line)) == (0, 0)
    assert one(url, "SELECT app.credit_available_value(%s)", case["credit"])[0] == 0
    position = ledger(url, customer)
    assert (
        position.invoice,
        position.charge,
        position.credit,
        position.security_deposit,
        position.pet_deposit,
    ) == (0, 0, 0, 0, 0)
    # The closure snapshots (DB-SETTLE-002, 006): every issued Invoice of the Lease and its lines.
    lines = line_snapshots(url, settlement)
    assert lines[pet_line] == ("DAMAGE_CHARGES", 12_500, 0, 0, 0, 12_500, 0)
    assert lines[other_line] == ("DAMAGE_CHARGES", 12_500, 0, 9_100, 400, 3_000, 0)
    assert {
        UUID(str(row[0]))
        for row in rows(
            url,
            "SELECT invoice_id FROM app.settlement_invoice_items WHERE final_settlement_id=%s",
            settlement,
        )
    } == {case["initial"], pet_invoice, other_invoice}
    closed_by, closing, snapshot = one(
        url,
        "SELECT closed_by,closing_balance_due_usd_cents,source_snapshot "
        "FROM app.final_settlements WHERE id=%s",
        settlement,
    )
    assert (closed_by, closing) == (approver, 0)
    assert snapshot["draft_id"] == str(draft_id) and snapshot["move_out_event_id"] is None
    assert snapshot["prepared_by"] == str(human)
    assert one(
        url,
        "SELECT ARRAY(SELECT DISTINCT actor FROM ("
        "SELECT actor_id AS actor FROM app.customer_credit_applications "
        "WHERE final_settlement_id=%s "
        "UNION ALL SELECT actor_id FROM app.deposit_applications WHERE final_settlement_id=%s "
        "UNION ALL SELECT included_by FROM app.settlement_invoice_items "
        "WHERE final_settlement_id=%s) actors)",
        settlement,
        settlement,
        settlement,
    )[0] == [approver]
    for key in ("credit_application_ids", "deposit_application_ids", "refund_ids"):
        assert (
            snapshot[key] == result[key]
            and len(result[key])
            == {
                "credit_application_ids": 1,
                "deposit_application_ids": 2,
                "refund_ids": 2,
            }[key]
        )
    audit = rows(
        url,
        "SELECT actor_id,authorization_reference,correlation_id,resulting_state "
        "FROM app.audit_events WHERE action='final_settlement.closed' AND entity_id=%s",
        settlement,
    )
    assert len(audit) == 1 and audit[0][:3] == (approver, APPROVE, draft_id)
    assert audit[0][3]["credit_application_ids"] == result["credit_application_ids"]
    assert written(url, settlement) == (1, 2, 2, 3, 0, True)
    # An exact repeat by the same approver replays the stored result and writes nothing.
    assert confirm(case, draft, approver) == confirmed
    assert written(url, settlement) == (1, 2, 2, 3, 0, True)
    # BR-SETTLE-012: a closed Settlement and its snapshots are never changed again.
    for statement in (
        "UPDATE app.final_settlements SET closing_balance_due_usd_cents=1 WHERE id=%s",
        "UPDATE app.settlement_invoice_items SET outstanding_at_inclusion_usd_cents=1 "
        "WHERE final_settlement_id=%s",
        "DELETE FROM app.settlement_invoice_items WHERE final_settlement_id=%s",
        "UPDATE app.settlement_invoice_line_items SET closing_outstanding_usd_cents=0 "
        "WHERE settlement_invoice_item_id IN (SELECT id FROM app.settlement_invoice_items "
        "WHERE final_settlement_id=%s)",
        "DELETE FROM app.settlement_invoice_line_items WHERE settlement_invoice_item_id IN "
        "(SELECT id FROM app.settlement_invoice_items WHERE final_settlement_id=%s)",
    ):
        with pytest.raises(psycopg.Error) as changed, psycopg.connect(url) as connection:
            connection.execute(statement, (settlement,))
        assert changed.value.sqlstate == "55000", statement
    for table in TABLES:
        with pytest.raises(psycopg.Error) as truncated, psycopg.connect(url) as connection:
            connection.execute(f"TRUNCATE {table} CASCADE")
        assert truncated.value.sqlstate == "55000", table
    with pytest.raises(psycopg.Error) as late, psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.settlement_late_payment_charge_items(final_settlement_id,"
            "late_payment_charge_id,outstanding_at_inclusion_usd_cents,included_at,included_by) "
            "VALUES (%s,%s,0,clock_timestamp(),%s)",
            (settlement, uuid4(), human),
        )
    assert late.value.diag.message_primary == (
        "Closure snapshots are written only while the Final Settlement closes"
    )


def test_debt_larger_than_the_deposits_stays_open_on_the_tenant_s_ledger(
    migrated_database_url: str,
) -> None:
    """BR-SETTLE-007 and BR-SETTLE-016: when the Deposits cannot pay everything, the Credit and
    both Deposits are used in the DL-032 order, nothing is refunded, and the rest stays open as
    debt on the ledger of the person named on the Invoice; nothing is written off."""
    url = migrated_database_url
    case = leaving_case(url, start_offset=this_month(url))
    human, prop, customer, settlement = (
        case["human"],
        case["prop"],
        case["customer"],
        case["settlement"],
    )
    staff = invoice_staff(human, prop)
    appliances = RecordOneTimeChargeCommand(
        uuid4(),
        "MISCELLANEOUS_CHARGES",
        customer,
        case["lease"],
        None,
        "Unreturned furniture",
        15_000,
        "Furniture missing at the move-out review",
        "Move-out log 812",
    )
    invoices().record_one_time_charge(prop, appliances, actor=staff)
    extra_line = line_of(url, draft_and_issue(prop, appliances.charge_id, staff)["id"])
    assert preview(prop, human, settlement)["open_total_usd_cents"] == 40_000
    plan = (
        SettlementCreditStep(case["credit"], LINE, case["other_line"], 400),
        SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], 12_500),
        SettlementDepositStep(SECURITY, case["security"], LINE, case["other_line"], 10_000),
        SettlementDepositStep(PET_REST, case["pet"], LINE, case["other_line"], 2_100),
        SettlementDepositStep(PET_REST, case["pet"], LINE, extra_line, 5_400),
    )
    draft = record(case, plan, pet_remainder=STAFF)
    result = confirm(case, draft)["result"]
    assert result["closing_balance_usd_cents"] == 9_600
    assert result["closing_balances"] == [{"customer_id": str(customer), "open_usd_cents": 9_600}]
    assert [row[4] for row in deposit_rows(url, settlement)] == [12_500, 10_000, 2_100, 5_400]
    # The remaining Pet Deposit records the staff reason of its step 5 decision.
    assert [row[6] for row in deposit_rows(url, settlement)][2:] == [STAFF.staff_reason] * 2
    assert [row[3] for row in credit_rows(url, settlement)] == [400]
    assert refund_rows(url, settlement) == []
    assert (held(url, case["security"]), held(url, case["pet"])) == (0, 0)
    assert (
        outstanding(url, case["pet_line"]),
        outstanding(url, case["other_line"]),
        outstanding(url, extra_line),
    ) == (0, 0, 9_600)
    assert line_snapshots(url, settlement)[extra_line] == (
        "MISCELLANEOUS_CHARGES",
        15_000,
        0,
        0,
        0,
        5_400,
        9_600,
    )
    position = ledger(url, customer)
    assert (position.invoice, position.charge, position.credit) == (9_600, 0, 0)
    assert (position.security_deposit, position.pet_deposit) == (0, 0)
    assert (
        one(
            url,
            "SELECT closing_balance_due_usd_cents FROM app.final_settlements WHERE id=%s",
            settlement,
        )[0]
        == 9_600
    )
    # The debt stays payable after closure (owner answer 7 to Q-2026-10-05-20): a Payment still
    # pays it, and the closed Settlement keeps its closing balance.
    pay(url, prop, human, customer, invoice_of(url, extra_line), extra_line, 9_600)
    assert outstanding(url, extra_line) == 0 and ledger(url, customer).invoice == 0
    assert (
        one(
            url,
            "SELECT closing_balance_due_usd_cents FROM app.final_settlements WHERE id=%s",
            settlement,
        )[0]
        == 9_600
    )


def test_early_leaving_keeps_the_security_deposit_and_never_lets_it_pay_debt(
    migrated_database_url: str,
) -> None:
    """Voluntary early leaving (BR-LEASE-021): the Security Deposit is kept (BR-DEP-023,
    BR-DEP-026) and never pays debt. Until its forfeiture is confirmed the Settlement cannot close
    (owner answer to Q-2026-10-05-24), also for a draft written before; afterwards the Pet
    Deposit pays the pet damage and, by the staff step, other debt; the rest stays open."""
    url = migrated_database_url
    case = leaving_case(url, start_offset=this_month(url), voluntary=True)
    human, prop, customer, settlement = (
        case["human"],
        case["prop"],
        case["customer"],
        case["settlement"],
    )
    security, pet = case["security"], case["pet"]
    view = preview(prop, human, settlement)
    assert path_of(view, security) == ("BR-DEP-023", "NONE", "FORFEITURE_REQUIRED", 10_000)
    assert issues(view, "RENT_PERIOD_NOT_BILLED") == []
    # A draft written before the blocking issue appeared is refused at the confirm (plan note 5).
    early = owner_draft(
        url,
        case,
        "FINAL_SETTLEMENT",
        PREPARE,
        {
            "variant": "FINAL_SETTLEMENT",
            "final_settlement_id": str(settlement),
            "steps": [],
            "pet_remainder": None,
        },
    )
    assert refusal(confirm, case, early) == (FinalSettlementConflictError, "55000", BLOCKED)
    assert state(url, early) == "PENDING" and written(url, settlement) == NOTHING_WRITTEN
    withdraw(case, early)
    forfeit_through_draft(PostgresDepositService(financial_database_url(), prop, human), security)
    view = preview(prop, human, settlement)
    assert path_of(view, security) == ("BR-DEP-023", "ACTIVE", "KEPT", 0)
    # A kept Security Deposit is never in a plan (BR-DEP-026).
    assert refusal(
        record,
        case,
        (
            SettlementCreditStep(case["credit"], LINE, case["other_line"], 400),
            SettlementDepositStep(SECURITY, security, LINE, case["other_line"], 100),
        ),
    )[1:] == ("55000", "Only a Deposit that follows DL-032 and holds money may be applied")
    plan = (
        SettlementCreditStep(case["credit"], LINE, case["other_line"], 400),
        SettlementDepositStep(PET_FIRST, pet, LINE, case["pet_line"], 12_500),
        SettlementDepositStep(PET_REST, pet, LINE, case["other_line"], 7_500),
    )
    draft = record(case, plan, pet_remainder=STAFF)
    result = confirm(case, draft)["result"]
    assert result["closing_balance_usd_cents"] == 4_600
    assert deposit_rows(url, settlement) == [
        (pet, "PET_RELATED_FIRST", "INVOICE_LINE", case["pet_line"], 12_500, 1, REASON),
        (
            pet,
            "PET_REMAINDER_EXPLICIT",
            "INVOICE_LINE",
            case["other_line"],
            7_500,
            2,
            STAFF.staff_reason,
        ),
    ]
    assert refund_rows(url, settlement) == []
    # The kept Security Deposit paid nothing and is still forfeited.
    assert held(url, security) == 0
    assert (
        one(
            url,
            "SELECT count(*) FROM app.deposit_dispositions disposition "
            "WHERE disposition.deposit_id=%s "
            "AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal "
            "WHERE reversal.deposit_disposition_id=disposition.id)",
            security,
        )[0]
        == 1
    )
    assert (outstanding(url, case["pet_line"]), outstanding(url, case["other_line"])) == (0, 4_600)
    position = ledger(url, customer)
    assert (position.invoice, position.credit, position.pet_deposit) == (4_600, 0, 0)
    assert result["closing_balances"] == [{"customer_id": str(customer), "open_usd_cents": 4_600}]


def test_a_reversed_forfeiture_follows_dl032_and_a_new_forfeiture_draft_waits(
    migrated_database_url: str,
) -> None:
    """Owner answers to Q-2026-10-05-23 and Q-2026-10-05-24: a Security Deposit whose forfeiture
    was reversed is held again and follows DL-032; a new forfeiture draft for it recorded after
    the Settlement draft holds the confirm back (any pending draft for a Deposit of the Lease),
    and the Settlement draft stays pending until that draft is withdrawn."""
    url = migrated_database_url
    case = leaving_case(url, start_offset=this_month(url), voluntary=True)
    human, prop, customer, settlement = (
        case["human"],
        case["prop"],
        case["customer"],
        case["settlement"],
    )
    security, pet = case["security"], case["pet"]
    service = PostgresDepositService(financial_database_url(), prop, human)
    forfeit_through_draft(service, security)
    disposition = UUID(
        str(one(url, "SELECT id FROM app.deposit_dispositions WHERE deposit_id=%s", security)[0])
    )
    reverse_through_draft(service, disposition)
    assert path_of(preview(prop, human, settlement), security) == (
        "BR-DEP-023",
        "REVERSED",
        "DL_032",
        10_000,
    )
    plan = (
        SettlementCreditStep(case["credit"], LINE, case["other_line"], 400),
        SettlementDepositStep(PET_FIRST, pet, LINE, case["pet_line"], 12_500),
        SettlementDepositStep(SECURITY, security, LINE, case["other_line"], 10_000),
        SettlementDepositStep(PET_REST, pet, LINE, case["other_line"], 2_100),
        refund(case, "pet", 5_400),
    )
    draft = record(case, plan, pet_remainder=STAFF)
    waiting = forfeitures().record(
        prop,
        RecordLeaseDepositForfeitureCommand(uuid4(), security, uuid4(), "Kept again after review"),
        actor=person(human, prop, "deposits.dispose"),
    )
    assert refusal(confirm, case, draft) == (FinalSettlementConflictError, "55000", BLOCKED)
    assert state(url, draft) == "PENDING" and written(url, settlement) == NOTHING_WRITTEN
    drafts().withdraw(
        prop,
        UUID(str(waiting["draft_id"])),
        "Recorded in error",
        prepare_capability="deposits.dispose",
        actor=person(human, prop, "deposits.dispose"),
    )
    result = confirm(case, draft)["result"]
    assert result["closing_balance_usd_cents"] == 0
    assert [(row[0], row[1], row[4]) for row in deposit_rows(url, settlement)] == [
        (pet, "PET_RELATED_FIRST", 12_500),
        (security, "SECURITY_EXPLICIT", 10_000),
        (pet, "PET_REMAINDER_EXPLICIT", 2_100),
    ]
    assert refund_rows(url, settlement) == [(pet, 5_400, customer, human, APPROVE)]
    assert (held(url, security), held(url, pet)) == (0, 0)
    position = ledger(url, customer)
    assert (position.invoice, position.security_deposit, position.pet_deposit) == (0, 0, 0)


def test_a_signer_s_own_invoice_keeps_its_debt_on_the_signer_s_ledger(
    migrated_database_url: str,
) -> None:
    """BR-SETTLE-016 (owner answers to Q-2026-10-05-20 and -21): the Settlement includes the
    Invoice of another Signer; each Customer's Credit pays only that Customer's debt; the Pet
    Deposit may pay any debt of the Lease; debt left stays on the ledger of the person named on
    each Invoice. A Customer's designated Credit step on a Late-payment Charge is recorded as
    designated (8e-2 review round 3 note)."""
    url = migrated_database_url
    case = two_signer_case(url, overdue_rent=True)
    human, prop, settlement = case["human"], case["prop"], case["settlement"]
    tenant, signer, pet, charge = case["tenant"], case["co_signer"], case["pet"], case["charge"]
    # The Primary Tenant pays the key card and a credit Adjustment releases 400 of their Credit.
    key_invoice = invoice_of(url, case["tenant_line"])
    pay(url, prop, human, tenant, key_invoice, case["tenant_line"], 1_500)
    credit_adjustment(url, human, prop, key_invoice, case["tenant_line"])
    tenant_credit = UUID(
        str(one(url, "SELECT id FROM app.customer_credits WHERE customer_id=%s", tenant)[0])
    )
    view = preview(prop, human, settlement)
    assert view["ready"] is True and view["open_total_usd_cents"] == 80_000 + 8_000 + 1_000
    charge_kind = SettlementTargetKind.LATE_PAYMENT_CHARGE
    plan = (
        SettlementCreditStep(case["credit"], LINE, case["signer_line"], 400),
        SettlementCreditStep(tenant_credit, charge_kind, charge, 400, DESIGNATION),
        SettlementDepositStep(PET_REST, pet, charge_kind, charge, 7_600),
        SettlementDepositStep(PET_REST, pet, LINE, case["rent_line"], 12_400),
    )
    draft = record(case, plan, pet_remainder=STAFF)
    result = confirm(case, draft)["result"]
    assert result["closing_balance_usd_cents"] == 67_600 + 600
    assert result["closing_balances"] == [
        {"customer_id": str(tenant), "open_usd_cents": 67_600},
        {"customer_id": str(signer), "open_usd_cents": 600},
    ]
    assert credit_rows(url, settlement) == [
        (
            case["credit"],
            "INVOICE",
            case["signer_line"],
            400,
            "OTHER_APPLICABLE_OBLIGATION",
            None,
            "OTHER_CONFIRMED",
            APPROVE,
        ),
        (
            tenant_credit,
            "LATE_PAYMENT_CHARGE",
            charge,
            400,
            "CUSTOMER_DESIGNATED",
            DESIGNATION,
            "CUSTOMER_DESIGNATED",
            APPROVE,
        ),
    ]
    assert [(row[2], row[3], row[4]) for row in deposit_rows(url, settlement)] == [
        ("LATE_PAYMENT_CHARGE", charge, 7_600),
        ("INVOICE_LINE", case["rent_line"], 12_400),
    ]
    assert refund_rows(url, settlement) == [] and held(url, pet) == 0
    assert (outstanding(url, case["rent_line"]), outstanding(url, case["signer_line"])) == (
        67_600,
        600,
    )
    assert (
        one(
            url,
            "SELECT outstanding_at_inclusion_usd_cents "
            "FROM app.settlement_late_payment_charge_items "
            "WHERE final_settlement_id=%s AND late_payment_charge_id=%s",
            settlement,
            charge,
        )[0]
        == 0
    )
    for statement in (
        "UPDATE app.settlement_late_payment_charge_items SET outstanding_at_inclusion_usd_cents=1 "
        "WHERE final_settlement_id=%s",
        "DELETE FROM app.settlement_late_payment_charge_items WHERE final_settlement_id=%s",
    ):
        with pytest.raises(psycopg.Error) as changed, psycopg.connect(url) as connection:
            connection.execute(statement, (settlement,))
        assert changed.value.sqlstate == "55000", statement
    tenant_position, signer_position = ledger(url, tenant), ledger(url, signer)
    assert (tenant_position.invoice, tenant_position.charge, tenant_position.credit) == (
        67_600,
        0,
        0,
    )
    assert tenant_position.pet_deposit == 0
    assert (signer_position.invoice, signer_position.charge, signer_position.credit) == (600, 0, 0)


def test_a_stale_or_blocked_draft_is_refused_and_stays_pending(
    migrated_database_url: str,
) -> None:
    """Plan notes 4, 6, 8 and 16; owner answer 3 to Q-2026-10-06-33: under its locks the confirm
    refuses a draft whose sources changed (stale), a waiting receipt reversal draft of a Deposit
    of the Lease, and an Invoice draft of the Lease; an inactive approver is an authorization
    error. Each refusal writes nothing and leaves the draft pending."""
    url = migrated_database_url
    case = leaving_case(url, start_offset=this_month(url))
    human, prop, customer, settlement = (
        case["human"],
        case["prop"],
        case["customer"],
        case["settlement"],
    )
    other_invoice = invoice_of(url, case["other_line"])
    draft = record(case, normal_plan(case), pet_remainder=STAFF)
    pay(url, prop, human, customer, other_invoice, case["other_line"], 100)
    assert refusal(confirm, case, draft) == (FinalSettlementStaleDraftError, "P5S02", STALE)
    assert state(url, draft) == "PENDING" and written(url, settlement) == NOTHING_WRITTEN
    withdraw(case, draft)
    plan = (
        SettlementCreditStep(case["credit"], LINE, case["other_line"], 400),
        SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], 12_500),
        SettlementDepositStep(SECURITY, case["security"], LINE, case["other_line"], 10_000),
        SettlementDepositStep(PET_REST, case["pet"], LINE, case["other_line"], 2_000),
        refund(case, "pet", 5_500),
    )
    draft = record(case, plan, pet_remainder=STAFF)
    # A receipt reversal draft waiting for the Security Deposit (its recorder refuses while the
    # Settlement draft waits, sub-slice 8c, so it is written as the owner) holds the confirm back.
    reversal = owner_draft(
        url,
        case,
        "DEPOSIT_FORFEITURE",
        "deposits.dispose",
        {"variant": "DEPOSIT_RECEIPT_REVERSAL", "deposit_id": str(case["security"])},
    )
    assert refusal(confirm, case, draft) == (FinalSettlementConflictError, "55000", BLOCKED)
    assert state(url, draft) == "PENDING" and written(url, settlement) == NOTHING_WRITTEN
    drafts().withdraw(
        prop,
        UUID(str(reversal["draft_id"])),
        "Recorded in error",
        prepare_capability="deposits.dispose",
        actor=person(human, prop, "deposits.dispose"),
    )
    # An Invoice draft with the Lease makes the Settlement draft stale; a draft whose digest
    # already includes it is refused by the blocking issue checked again under the locks.
    charge = key_card(customer, case["lease"])
    staff = invoice_api_actor(human, prop)
    invoices().record_one_time_charge(prop, charge, actor=staff)
    invoices().create_draft(prop, CreateInvoiceDraftCommand(uuid4(), charge.charge_id), actor=staff)
    assert refusal(confirm, case, draft) == (FinalSettlementStaleDraftError, "P5S02", STALE)
    assert issues(preview(prop, human, settlement), "INVOICE_DRAFT_NOT_ISSUED") != []
    later = owner_draft(
        url,
        case,
        "FINAL_SETTLEMENT",
        PREPARE,
        {
            "variant": "FINAL_SETTLEMENT",
            "final_settlement_id": str(settlement),
            "steps": [],
            "pet_remainder": None,
        },
    )
    assert refusal(confirm, case, later) == (FinalSettlementConflictError, "55000", BLOCKED)
    assert (state(url, draft), state(url, later)) == ("PENDING", "PENDING")
    assert written(url, settlement) == NOTHING_WRITTEN
    # An approver whose account is no longer active is an authorization error (plan note 16).
    with psycopg.connect(url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    assert refusal(confirm, case, later)[:2] == (FinalSettlementAuthorizationError, "P4506")
    assert written(url, settlement) == NOTHING_WRITTEN


def test_the_confirm_refuses_other_drafts_approvers_and_isolation_levels(
    migrated_database_url: str,
) -> None:
    """Plan note 16 and BR-AUTH-010 at the confirm's own boundary (review round 1): an unknown
    Property (V1 has one Property per database) and a draft of another kind are not found; a
    rejected or withdrawn draft, and a confirmed one for another approver, is a conflict; a
    transaction that is not READ COMMITTED is refused (plan note 15). Each refusal writes
    nothing."""
    url = migrated_database_url
    case = leaving_case(url, start_offset=this_month(url))
    human, prop, settlement = case["human"], case["prop"], case["settlement"]
    with psycopg.connect(url) as connection:
        other_human = setup_signed_lease(connection)[0]
    decided = (FinalSettlementConflictError, "55000", "Financial draft is already decided")
    rejected = record(case, normal_plan(case), pet_remainder=STAFF)
    drafts().reject(
        prop,
        UUID(str(rejected["draft_id"])),
        "Amounts to review",
        actor=person(human, prop, APPROVE),
    )
    assert refusal(confirm, case, rejected) == decided
    withdrawn = record(case, normal_plan(case), pet_remainder=STAFF)
    withdraw(case, withdrawn)
    assert refusal(confirm, case, withdrawn) == decided
    draft = record(case, normal_plan(case), pet_remainder=STAFF)
    draft_id = UUID(str(draft["draft_id"]))
    not_found = (FinalSettlementNotFoundError, "P0002", "Final Settlement draft was not found")
    unknown = uuid4()
    assert refusal(
        lambda: settlements().confirm(unknown, draft_id, actor=person(human, unknown, APPROVE))
    ) == (FinalSettlementNotFoundError, "P4501", "Invoice Property was not found")
    move = owner_draft(
        url, case, "PAYMENT_MOVE", "payments.allocations.reverse", {"variant": "WRONG_UNIT_MOVE"}
    )
    assert refusal(confirm, case, move) == not_found
    with pytest.raises(psycopg.Error) as isolation, psycopg.connect(url) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        connection.execute(CONFIRM_SQL, (prop, human, draft_id, APPROVE))
    assert (isolation.value.sqlstate, isolation.value.diag.message_primary) == (
        "55000",
        "A Final Settlement is confirmed at READ COMMITTED",
    )
    assert state(url, draft) == "PENDING" and written(url, settlement) == NOTHING_WRITTEN
    confirmed = confirm(case, draft)
    after = written(url, settlement)
    # Once confirmed, only the same approver replays; another approver meets a decided draft.
    assert refusal(confirm, case, draft, other_human) == decided
    assert confirm(case, draft) == confirmed and written(url, settlement) == after


def test_a_moved_out_lease_closes_with_its_current_move_out(migrated_database_url: str) -> None:
    """Plan note 1 (review rounds 1 and 2): the closure records the current physical move-out,
    not the one the Settlement saw when it started; a Lease whose kept Deposits cannot pay and
    whose Customer holds no Credit closes with an empty plan, its whole debt (the final Utility
    Invoice included) staying open on the Customer's ledger."""
    url = migrated_database_url
    leaver = departed(url, 9, 11)
    dep = leaver.dep
    human, prop, lease = dep.human, dep.prop, dep.lease
    settlement = start(prop, human, lease)
    started = one(
        url, "SELECT move_out_date_snapshot FROM app.final_settlements WHERE id=%s", settlement
    )[0]
    assert started == dep.move_out_date
    # The move-out is corrected after the Settlement started.
    corrected = correct_move_out(
        url,
        Scenario(human, prop, leaver.customer, lease, {}, None),
        dep.request,
        dep.move_out_date + timedelta(days=1),
    )
    dep = replace(
        dep,
        physical_event=corrected.event_id,
        move_out_date=corrected.actual_move_out_date,
        request=corrected,
    )
    leaver = replace(leaver, dep=dep)
    reading = final_reading(url, leaver, dep.electricity, "150")
    final = create_final(leaver, record_final(leaver, (used(dep.electricity, reading),)))
    staff = person(
        human, prop, "invoices.read", "invoices.create", "invoices.issue", "property.manage"
    )
    invoices().set_unit_cleaning_rate(
        prop,
        SetUnitCleaningRateCommand(uuid4(), dep.unit, None, 0, "No cleaning charge"),
        actor=staff,
    )
    service = PostgresDepositService(financial_database_url(), prop, human)
    for item in preview(prop, human, settlement)["deposits"]:
        if item["path"] == "FORFEITURE_REQUIRED":
            forfeit_through_draft(service, UUID(item["deposit_id"]))
    view = preview(prop, human, settlement)
    assert view["blocking_issues"] == [] and view["ready"] is True
    assert view["lease"]["move_out_date"] == dep.move_out_date.isoformat()
    assert all(item["path"] != "DL_032" or item["held_usd_cents"] == 0 for item in view["deposits"])
    assert all(item["credit_may_use_usd_cents"] == 0 for item in view["customers"])
    open_total = view["open_total_usd_cents"]
    assert open_total > 0
    case = {"human": human, "prop": prop, "settlement": settlement}
    result = confirm(case, record(case, ()))["result"]
    assert result["closing_balance_usd_cents"] == open_total
    snapshot = one(
        url, "SELECT source_snapshot FROM app.final_settlements WHERE id=%s", settlement
    )[0]
    assert (snapshot["move_out_event_id"], snapshot["move_out_date"]) == (
        str(corrected.event_id),
        corrected.actual_move_out_date.isoformat(),
    )
    assert corrected.actual_move_out_date != started
    assert (
        one(
            url, "SELECT move_out_date_snapshot FROM app.final_settlements WHERE id=%s", settlement
        )[0]
        == started
    )
    final_invoice = UUID(str(final["invoice_id"]))
    assert one(
        url,
        "SELECT outstanding_at_inclusion_usd_cents FROM app.settlement_invoice_items "
        "WHERE final_settlement_id=%s AND invoice_id=%s",
        settlement,
        final_invoice,
    )[0] == sum(
        outstanding(url, UUID(str(row[0])))
        for row in rows(url, "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", final_invoice)
    )
    assert ledger(url, leaver.customer).invoice == open_total


def test_a_br_dep_027_termination_refunds_the_pet_rest_while_debt_stays(
    migrated_database_url: str,
) -> None:
    """Unpaid Initial Rent (BR-LEASE-005), a BR-DEP-027 termination (review round 1): the Security
    Deposit is kept; the Pet Deposit pays the pet damage, then other debt only by the Customer's
    choice (recorded as text), and its rest is refunded while the other debt stays open; the
    plan check and the Refund writer's own open-debt check agree (Q-2026-10-05-21)."""
    url = migrated_database_url
    case = leaving_case(url, unpaid_initial=True)
    human, prop, customer, settlement = (
        case["human"],
        case["prop"],
        case["customer"],
        case["settlement"],
    )
    pet, pet_line, other_line = case["pet"], case["pet_line"], case["other_line"]
    forfeit_through_draft(
        PostgresDepositService(financial_database_url(), prop, human), case["security"]
    )
    view = preview(prop, human, settlement)
    assert path_of(view, case["security"]) == ("BR-LEASE-005", "ACTIVE", "KEPT", 0)
    assert view["ready"] is True
    open_total = view["open_total_usd_cents"]
    initial_owed = open_total - 25_000
    assert initial_owed > 0
    plan = (
        SettlementDepositStep(PET_FIRST, pet, LINE, pet_line, 12_500),
        SettlementDepositStep(PET_REST, pet, LINE, other_line, 2_000),
        refund(case, "pet", 5_500),
    )
    assert refusal(lambda: record(case, plan, pet_remainder=STAFF))[1:] == (
        "55000",
        "At this termination only the Customer may choose to use the remaining Pet Deposit",
    )
    draft = record(case, plan, pet_remainder=CHOICE)
    assert cast(dict[str, Any], draft["payload"])["pet_remainder"] == {
        "basis": "CUSTOMER_CHOICE",
        "staff_reason": CHOICE.staff_reason,
        "customer_choice": CHOICE.customer_choice,
    }
    result = confirm(case, draft)["result"]
    assert result["closing_balance_usd_cents"] == open_total - 14_500
    assert deposit_rows(url, settlement) == [
        (pet, "PET_RELATED_FIRST", "INVOICE_LINE", pet_line, 12_500, 1, REASON),
        (pet, "PET_REMAINDER_EXPLICIT", "INVOICE_LINE", other_line, 2_000, 2, CHOICE.staff_reason),
    ]
    assert refund_rows(url, settlement) == [(pet, 5_500, customer, human, APPROVE)]
    assert (held(url, pet), held(url, case["security"])) == (0, 0)
    assert (outstanding(url, pet_line), outstanding(url, other_line)) == (0, 10_500)
    position = ledger(url, customer)
    assert (position.invoice, position.pet_deposit, position.security_deposit) == (
        open_total - 14_500,
        0,
        0,
    )


def test_a_settlement_waits_for_every_unbilled_rent_month(migrated_database_url: str) -> None:
    """Owner answer 2 to Q-2026-10-06-33 and the answer to Q-2026-10-06-34: while a recurring
    Rent month that a Rent run would bill has no active Rent Invoice, the Settlement shows
    RENT_PERIOD_NOT_BILLED and no draft is recorded, also for a month whose Invoice staff VOIDed
    for a reason other than the hand-back rule; once every such month is billed nothing blocks.
    The Lease started 100 days ago, so at least one full recurring month lies inside its coverage
    on any run date."""
    url = migrated_database_url
    source = signed_with_initial(url, 100)
    human, prop, lease = source["actor"], source["property"], source["lease"]
    terminate(url, human, prop, lease, source["today"], voluntary=False)
    settlement = start(prop, human, lease)
    months = unbilled_rent_months(url, lease)
    assert months != []
    # A month billed and then VOIDed by staff (not under BR-RENT-030) is unbilled again.
    with psycopg.connect(url) as connection:
        voided, _ = create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=source["customer"],
            lease_id=lease,
            period_start=cast(date, months[0][0]),
            add_occupancy=False,
        )
    assert unbilled_rent_months(url, lease) == months[1:]
    invoices().void(
        prop,
        voided,
        VoidInvoiceCommand(uuid4(), "Billed in error", invoice_version(url, voided)),
        actor=invoice_api_actor(human, prop),
    )
    assert unbilled_rent_months(url, lease) == months
    view = preview(prop, human, settlement)
    assert view["blocking_issues"] == [
        {
            "code": "RENT_PERIOD_NOT_BILLED",
            "period_start": cast(date, first).isoformat(),
            "period_end": cast(date, last).isoformat(),
        }
        for first, last in months
    ]
    assert view["ready"] is False
    case = {"human": human, "prop": prop, "settlement": settlement}
    assert refusal(record, case, ()) == (FinalSettlementConflictError, "55000", BLOCKED)
    billed = bill_unbilled_rent_months(url, human, prop, lease)
    assert len(billed) == len(months)
    view = preview(prop, human, settlement)
    assert view["blocking_issues"] == [] and view["ready"] is True


def test_a_month_voided_by_the_hand_back_rule_does_not_block(hand_back_database: str) -> None:
    """Owner answer to Q-2026-10-06-34: after a voluntary hand-back on 3 August the August Rent
    Invoice is VOIDed under BR-RENT-030; the billing rule still counts August as billable (the
    early final month), but the month is decided, so RENT_PERIOD_NOT_BILLED leaves it out."""
    url = hand_back_database
    scenario = lease_with_invoices(url, (AUGUST,))
    august = scenario.invoices[AUGUST]
    hand_back(url, scenario, date(2026, 8, 3))
    who = hand_back_staff(scenario.human, scenario.prop)
    owed = hand_back_invoices().hand_back_rent_assessment(scenario.prop, august, actor=who)
    assert (owed["coverage"], owed["action"]) == ("HAND_BACK_MONTH", "VOID")
    assert unbilled_rent_months(url, scenario.lease) == []
    hand_back_invoices().resolve_hand_back_rent(
        scenario.prop,
        august,
        ResolveHandBackRentCommand(
            uuid4(),
            "VOID",
            int(str(owed["outstanding_usd_cents"])),
            "Customer handed back the Parking on 3 August",
            invoice_version(url, august),
        ),
        actor=who,
    )
    assert (
        one(
            url,
            "SELECT app.lease_is_billable_for_recurring_period(%s,%s,%s,statement_timestamp())",
            scenario.lease,
            AUGUST,
            date(2026, 8, 31),
        )[0]
        is True
    )
    assert unbilled_rent_months(url, scenario.lease) == []
    settlement = start(scenario.prop, scenario.human, scenario.lease)
    assert (
        issues(preview(scenario.prop, scenario.human, settlement), "RENT_PERIOD_NOT_BILLED") == []
    )


def rent_issue(first: date) -> dict[str, str]:
    """The RENT_PERIOD_NOT_BILLED issue of the calendar month that starts on first."""
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return {
        "code": "RENT_PERIOD_NOT_BILLED",
        "period_start": first.isoformat(),
        "period_end": last.isoformat(),
    }


def test_a_next_month_voided_by_the_hand_back_rule_does_not_block(
    hand_back_database: str,
) -> None:
    """Owner answer to Q-2026-10-06-34 (follow-up, 2026-10-06): after a hand-back between the
    25th and the month end, the hand-back resolution VOIDs next month's Rent Invoice (BR-RENT-030,
    slice 5). With the termination dated in that next month, the billing rule counts the month as
    billable (the early final month), but its Rent was decided, so it does not block."""
    url = hand_back_database
    scenario = lease_with_invoices(url, (AUGUST, SEPTEMBER))
    september = scenario.invoices[SEPTEMBER]
    hand_back(url, scenario, date(2026, 8, 26), terminated_on=date(2026, 9, 10))
    who = hand_back_staff(scenario.human, scenario.prop)
    owed = hand_back_invoices().hand_back_rent_assessment(scenario.prop, september, actor=who)
    assert (owed["coverage"], owed["action"]) == ("NEXT_MONTH", "VOID")
    assert unbilled_rent_months(url, scenario.lease) == []
    hand_back_invoices().resolve_hand_back_rent(
        scenario.prop,
        september,
        ResolveHandBackRentCommand(
            uuid4(),
            "VOID",
            int(str(owed["outstanding_usd_cents"])),
            "Customer handed back the Parking on 26 August",
            invoice_version(url, september),
        ),
        actor=who,
    )
    assert (
        one(
            url,
            "SELECT app.lease_is_billable_for_recurring_period(%s,%s,%s,statement_timestamp())",
            scenario.lease,
            SEPTEMBER,
            date(2026, 9, 30),
        )[0]
        is True
    )
    assert unbilled_rent_months(url, scenario.lease) == []
    settlement = start(scenario.prop, scenario.human, scenario.lease)
    assert (
        issues(preview(scenario.prop, scenario.human, settlement), "RENT_PERIOD_NOT_BILLED") == []
    )


def test_a_month_voided_for_another_reason_still_blocks_after_a_hand_back(
    hand_back_database: str,
) -> None:
    """Owner answer to Q-2026-10-06-34 (follow-up, 2026-10-06): only a BR-RENT-030 hand-back
    resolution decides a month. The same Rent Invoices VOIDed by staff for another reason (a plain
    VOID, not the hand-back resolution) leave the month unbilled, and it blocks: the hand-back
    month (hand-back before the 5th) and the next month (hand-back on or after the 25th, the
    termination dated in that month)."""
    url = hand_back_database
    early = lease_with_invoices(url, (AUGUST,))
    hand_back(url, early, date(2026, 8, 3))
    late = lease_with_invoices(url, (AUGUST, SEPTEMBER))
    hand_back(url, late, date(2026, 8, 26), terminated_on=date(2026, 9, 10))
    for scenario, month in ((early, AUGUST), (late, SEPTEMBER)):
        invoice = scenario.invoices[month]
        assert unbilled_rent_months(url, scenario.lease) == []
        hand_back_invoices().void(
            scenario.prop,
            invoice,
            VoidInvoiceCommand(uuid4(), "Billed in error", invoice_version(url, invoice)),
            actor=hand_back_staff(scenario.human, scenario.prop),
        )
        assert (
            one(
                url,
                "SELECT count(*) FROM app.hand_back_rent_resolutions WHERE invoice_id=%s",
                invoice,
            )[0]
            == 0
        )
        issue = rent_issue(month)
        assert unbilled_rent_months(url, scenario.lease) == [
            (date.fromisoformat(issue["period_start"]), date.fromisoformat(issue["period_end"]))
        ]
        settlement = start(scenario.prop, scenario.human, scenario.lease)
        view = preview(scenario.prop, scenario.human, settlement)
        assert issues(view, "RENT_PERIOD_NOT_BILLED") == [issue] and view["ready"] is False


def test_the_closure_guard_and_snapshots_refuse_what_the_confirm_would_not_write(
    migrated_database_url: str,
) -> None:
    """Plan note 3: every closure needs an active human approver and a time not later than the
    clock; a closure snapshot is written only while its Settlement closes and must reconcile to
    the closing balance at commit (DB-SETTLE-006 deferred closure validation)."""
    url = migrated_database_url
    case = leaving_case(url, start_offset=this_month(url))
    human, settlement = case["human"], case["settlement"]
    with pytest.raises(psycopg.Error) as unreconciled, psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.settlement_invoice_items(final_settlement_id,invoice_id,id,"
            "outstanding_at_inclusion_usd_cents,included_at,included_by) "
            "VALUES (%s,%s,%s,0,clock_timestamp(),%s)",
            (settlement, case["initial"], uuid4(), human),
        )
    assert (unreconciled.value.sqlstate, unreconciled.value.diag.message_primary) == (
        "23514",
        UNRECONCILED,
    )
    with pytest.raises(psycopg.Error) as mismatched, psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.settlement_invoice_items(final_settlement_id,invoice_id,id,"
            "outstanding_at_inclusion_usd_cents,included_at,included_by) "
            "VALUES (%s,%s,%s,1,clock_timestamp(),%s)",
            (settlement, case["initial"], uuid4(), human),
        )
    assert mismatched.value.sqlstate == "23514"
    close = (
        "UPDATE app.final_settlements SET closed_at={at},closed_by=%s,"
        "source_snapshot='{{}}'::jsonb,closing_balance_due_usd_cents=0 WHERE id=%s"
    )
    with pytest.raises(psycopg.Error) as future, psycopg.connect(url) as connection:
        connection.execute(
            close.format(at="clock_timestamp()+interval '1 hour'"), (human, settlement)
        )
    assert (future.value.sqlstate, future.value.diag.message_primary) == (
        "23514",
        "A Final Settlement closure cannot be dated in the future",
    )
    with psycopg.connect(url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    with pytest.raises(psycopg.Error) as inactive, psycopg.connect(url) as connection:
        connection.execute(close.format(at="clock_timestamp()"), (human, settlement))
    assert (inactive.value.sqlstate, inactive.value.diag.message_primary) == (
        "42501",
        "A Final Settlement is closed only by an active human approver",
    )
    assert written(url, settlement) == NOTHING_WRITTEN


def test_settlement_confirm_records_are_least_privilege(migrated_database_url: str) -> None:
    """Only the financial role may call the confirm; its helpers, the snapshot checks and the
    snapshot tables are internal (no role may read or write them)."""
    url = migrated_database_url
    with psycopg.connect(url) as owner:
        for signature in (CONFIRM, *INTERNAL):
            definer, config, grantees = cast(
                tuple[bool, list[str] | None, list[str]],
                owner.execute(
                    "SELECT p.prosecdef,p.proconfig,ARRAY(SELECT acl.grantee::regrole::text "
                    "FROM aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) acl "
                    "WHERE acl.grantee<>p.proowner ORDER BY 1) "
                    "FROM pg_catalog.pg_proc p WHERE p.oid=%s::regprocedure",
                    (signature,),
                ).fetchone(),
            )
            assert definer is True and "search_path=pg_catalog" in (config or []), signature
            assert grantees == (["prm_financial"] if signature == CONFIRM else []), signature
            for role in ("public", "prm_runtime", "prm_bootstrap"):
                assert owner.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)
                ).fetchone() == (False,), (role, signature)
        # The append-only trigger function is no definer and has no grantee either.
        assert owner.execute(
            "SELECT ARRAY(SELECT acl.grantee::regrole::text "
            "FROM aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) acl "
            "WHERE acl.grantee<>p.proowner) FROM pg_catalog.pg_proc p "
            "WHERE p.oid='app.reject_settlement_closure_item_mutation()'::regprocedure"
        ).fetchone() == ([],)
        for table in TABLES:
            for role in ("public", "prm_runtime", "prm_financial", "prm_bootstrap"):
                assert owner.execute(
                    "SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')",
                    (role, table),
                ).fetchone() == (False,), (role, table)
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        psycopg.connect(runtime_database_url()) as connection,
    ):
        connection.execute(CONFIRM_SQL, (uuid4(), uuid4(), uuid4(), APPROVE))


def test_final_settlement_confirm_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261029_94")
    assert revision is not None and revision.down_revision == "20261028_93"
    module = revision.module
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
