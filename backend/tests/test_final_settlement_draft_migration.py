"""V1-056 sub-slice 8c: the Final Settlement draft, its strict DL-032 order and its waits."""

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from deposit_receipt_reversal_test_support import reverse_receipt_as_owner
from payment_test_support import seed_payment
from property_rental.billing import PostgresRentBillingService
from property_rental.deposit import (
    DepositInvalidError,
    PostgresDepositService,
    ReverseDepositReceiptCommand,
)
from property_rental.deposit_receipt_reversal import (
    DepositReceiptReversalConflictError,
    DepositReceiptReversalService,
    RecordDepositReceiptReversalCommand,
)
from property_rental.final_settlement import (
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementInvalidError,
    FinalSettlementKeyReused,
    FinalSettlementNotFoundError,
    FinalSettlementService,
    PetRemainderBasis,
    PetRemainderDecision,
    RecordFinalSettlementDraftCommand,
    SettlementCreditStep,
    SettlementDepositRefund,
    SettlementDepositStep,
    SettlementDepositStepKind,
    SettlementStep,
    SettlementTargetKind,
)
from property_rental.financial_draft import FinancialDraftService
from property_rental.invoice import (
    CorrectInvoiceDraftCommand,
    CreateInvoiceDraftCommand,
    IssueInvoiceCommand,
    RecordOneTimeChargeCommand,
)
from property_rental.late_payment import DecisionOutcome, FinalizeLatePaymentDecisionCommand
from property_rental.move_out_inspection import InspectionFinding, RecordMoveOutInspection
from rent_month_test_support import bill_unbilled_rent_months
from test_billing_service_migration import (
    add_service,
    authenticated,
    initial_command,
    setup_billing_source,
)
from test_credit_migration import credit_id, recognize
from test_deposit_migration import deposit_actor
from test_final_settlement_migration import (
    held,
    line_of,
    one,
    outstanding,
    pet_deposit,
    start,
    today,
)
from test_final_settlement_preview_migration import (
    credit_adjustment,
    key_card,
    pay,
    person,
    preview,
    without_time,
)
from test_invoice_migration import (
    create_recurring_rent_invoice,
    financial_database_url,
    invoice_api_actor,
    runtime_database_url,
    setup_signed_lease,
)
from test_late_payment_migration import late_payment_actor
from test_late_payment_migration import service as late_payments
from test_lease_migration import create_draft, setup_sources, sign_lease
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_out_inspection_migration import actor as inspection_actor
from test_move_out_inspection_migration import flow as inspection_flow
from test_one_time_charges_migration import damage, draft_and_issue, invoices
from test_one_time_charges_migration import staff as invoice_staff
from test_termination_deposit_migration import terminate
from test_unpaid_initial_termination_migration import rent_line, signed_with_initial
from test_unpaid_initial_termination_migration import terminate as terminate_unpaid

RECORD = "app.record_final_settlement_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
RECORD_SQL = "SELECT app.record_final_settlement_draft(%s,%s,%s,%s,%s,%s,%s)"
INTERNAL = (
    "app.final_settlement_plan_id(jsonb)",
    "app.final_settlement_source_state(uuid,uuid)",
    "app.final_settlement_plan_result(uuid,uuid,uuid,jsonb)",
    "app.final_settlement_rent_first_line(uuid,jsonb)",
)
PREPARE = "final_settlements.prepare"
APPROVE = "financial.approve"
REASON = "Final Settlement prepared from the move-out review"
LINE = SettlementTargetKind.INVOICE_LINE
PET_FIRST = SettlementDepositStepKind.PET_DEPOSIT_PET_DAMAGE
SECURITY = SettlementDepositStepKind.SECURITY_DEPOSIT
PET_REST = SettlementDepositStepKind.PET_DEPOSIT_REMAINDER
CREDIT_FIRST = (
    "Each Customer's Credit must pay that Customer's open debt, up to what it can pay, "
    "before any Deposit pays"
)
AFTER_SECURITY = (
    "The remaining Pet Deposit pays only debt still open after the Security Deposit has been used"
)
NO_REFUND = "No Deposit Refund while the Lease still has open debt that the Deposit could pay"
STAFF = PetRemainderDecision(PetRemainderBasis.STAFF_REASON, "The Customer will not pay the rest")
CHOICE = PetRemainderDecision(
    PetRemainderBasis.CUSTOMER_CHOICE,
    "The Customer asked for it",
    "Primary Tenant, 2026-10-05, signed note at the front desk",
)


def settlements() -> FinalSettlementService:
    return FinalSettlementService(financial_database_url())


def drafts() -> FinancialDraftService:
    return FinancialDraftService(runtime_database_url(), financial_database_url())


def leaving_case(
    url: str, *, unpaid_initial: bool = False, start_offset: int = 10, voluntary: bool = False
) -> dict[str, Any]:
    """A signed Lease that never moved in, with its Security Deposit (10,000 held), a Pet Deposit
    (20,000 held) and two issued Damage charges of 12,500, one pet-related. Normally the Initial
    Rent Invoice is paid and a credit Adjustment releases 400 of Customer Credit, then the Lease is
    terminated with no forfeiture ground; with unpaid_initial it is terminated for the unpaid
    Initial Rent (BR-LEASE-005, a BR-DEP-027 termination). The Lease starts start_offset days
    before today; with voluntary the termination is voluntary early leaving (BR-LEASE-021, a
    Security forfeiture ground, BR-DEP-023) instead (sub-slice 8e-3)."""
    source = signed_with_initial(url, start_offset)
    human, prop, lease = source["actor"], source["property"], source["lease"]
    customer, day = source["customer"], source["today"]
    pet = pet_deposit(url, human, prop, lease, day)
    version = one(url, "SELECT version FROM app.leases WHERE id=%s", lease)
    pet_finding, other_finding = uuid4(), uuid4()
    inspection_flow().record(
        prop,
        lease,
        RecordMoveOutInspection(
            uuid4(),
            uuid4(),
            int(version[0]),
            day,
            "Recorded inspection condition",
            "Approved inspection",
            "Evidence-901",
            "Record actual inspection",
            (
                InspectionFinding(pet_finding, "Scratched door by the pet", True),
                InspectionFinding(other_finding, "Broken window latch", False),
            ),
        ),
        actor=inspection_actor(human, prop),
        request_id="settlement-draft-inspection",
    )
    lines: dict[str, UUID] = {}
    for name, finding in (("pet_line", pet_finding), ("other_line", other_finding)):
        command = damage(customer, lease, finding)
        invoices().record_one_time_charge(prop, command, actor=invoice_staff(human, prop))
        issued = draft_and_issue(prop, command.charge_id, invoice_staff(human, prop))
        lines[name] = line_of(url, issued["id"])
    credit = None
    if unpaid_initial:
        terminate_unpaid(url, source)
    else:
        rent, owed = rent_line(url, source["invoice"])
        pay(url, prop, human, customer, source["invoice"], rent, owed)
        credit_adjustment(url, human, prop, source["invoice"], rent)
        credit = UUID(
            str(one(url, "SELECT id FROM app.customer_credits WHERE customer_id=%s", customer)[0])
        )
        terminate(url, human, prop, lease, day, voluntary=voluntary)
    settlement = start(prop, human, lease)
    return {
        "human": human,
        "prop": prop,
        "lease": lease,
        "customer": customer,
        "security": source["deposit"],
        "pet": pet,
        "credit": credit,
        "settlement": settlement,
        "cash": UUID(str(one(url, "SELECT id FROM app.refund_methods WHERE code='CASH'")[0])),
        "initial": source["invoice"],
        **lines,
    }


def refund(
    case: dict[str, Any], deposit: str, amount: int, **changes: Any
) -> SettlementDepositRefund:
    values: dict[str, Any] = {
        "deposit_id": case[deposit],
        "amount_usd_cents": amount,
        "refund_method_id": case["cash"],
        "reference_note": "Cash handed over at the front desk",
        "recipient_customer_id": case["customer"],
        "signer_agreement": None,
    }
    values.update(changes)
    return SettlementDepositRefund(**values)


def normal_plan(case: dict[str, Any]) -> tuple[SettlementStep, ...]:
    """Credit 400 first, the Pet Deposit pays the pet damage, the Security Deposit and the rest of
    the Pet Deposit pay the other damage, and the Pet Deposit's rest is refunded."""
    return (
        SettlementCreditStep(case["credit"], LINE, case["other_line"], 400),
        SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], 12_500),
        SettlementDepositStep(SECURITY, case["security"], LINE, case["other_line"], 10_000),
        SettlementDepositStep(PET_REST, case["pet"], LINE, case["other_line"], 2_100),
        refund(case, "pet", 5_400),
    )


def record(
    case: dict[str, Any],
    steps: tuple[SettlementStep, ...],
    *,
    pet_remainder: PetRemainderDecision | None = None,
    key: UUID | None = None,
    reason: str = REASON,
) -> dict[str, object]:
    return settlements().record_draft(
        case["prop"],
        RecordFinalSettlementDraftCommand(
            key or uuid4(), case["settlement"], steps, reason, pet_remainder
        ),
        actor=person(case["human"], case["prop"], PREPARE),
    )


def refusal(call: Callable[..., object], *args: Any, **kwargs: Any) -> tuple[Any, Any]:
    """The database refusal behind the service error: SQLSTATE and message."""
    with pytest.raises((FinalSettlementInvalidError, FinalSettlementConflictError)) as failure:
        call(*args, **kwargs)
    cause = failure.value.__cause__
    assert isinstance(cause, psycopg.Error)
    return cause.sqlstate, cause.diag.message_primary


def withdraw(case: dict[str, Any], draft: dict[str, object]) -> None:
    drafts().withdraw(
        case["prop"],
        UUID(str(draft["draft_id"])),
        "Prepared again",
        prepare_capability=PREPARE,
        actor=person(case["human"], case["prop"], PREPARE),
    )


def settlement_drafts(url: str, settlement: UUID) -> int:
    return int(
        one(
            url,
            "SELECT count(*) FROM app.financial_drafts WHERE kind='FINAL_SETTLEMENT' "
            "AND payload->>'final_settlement_id'=%s",
            str(settlement),
        )[0]
    )


def balances(url: str, case: dict[str, Any]) -> tuple[Any, ...]:
    return (
        held(url, case["security"]),
        held(url, case["pet"]),
        outstanding(url, case["pet_line"]),
        outstanding(url, case["other_line"]),
        one(url, "SELECT app.credit_available_value(%s)", case["credit"])[0],
        one(
            url,
            "SELECT count(*) FROM app.deposit_applications WHERE final_settlement_id=%s",
            case["settlement"],
        )[0],
    )


def test_a_settlement_draft_records_the_dl032_steps_and_changes_nothing(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = leaving_case(url)
    human, prop, settlement = case["human"], case["prop"], case["settlement"]
    assert (held(url, case["security"]), held(url, case["pet"])) == (10_000, 20_000)
    assert (outstanding(url, case["pet_line"]), outstanding(url, case["other_line"])) == (
        12_500,
        12_500,
    )
    view = preview(prop, human, settlement)
    assert view["ready"] is True and view["open_total_usd_cents"] == 25_000
    before = balances(url, case)
    key = uuid4()
    draft = record(case, normal_plan(case), pet_remainder=STAFF, key=key)
    assert (draft["kind"], draft["prepare_capability"], draft["state"]) == (
        "FINAL_SETTLEMENT",
        PREPARE,
        "PENDING",
    )
    assert draft["prepared_by"] == str(human) and draft["reason"] == REASON
    payload = cast(dict[str, Any], draft["payload"])
    command = RecordFinalSettlementDraftCommand(key, settlement, normal_plan(case), REASON, STAFF)
    assert payload["steps"] == command.plan()["steps"]
    assert payload["pet_remainder"] == STAFF.payload()
    assert payload["final_settlement_id"] == str(settlement)
    assert payload["lease_id"] == str(case["lease"]) and payload["termination_ground"] is None
    assert payload["pet_remainder_chosen_by"] == "CUSTOMER_OR_STAFF_WITH_REASON"
    assert payload["deposit_ids"] == sorted([str(case["security"]), str(case["pet"])])
    assert payload["open_total_usd_cents"] == 25_000
    assert payload["closing_balance_usd_cents"] == 0 and payload["closing_balances"] == []
    # The source revision is the digest of every Settlement source's current state.
    digest = one(
        url,
        "SELECT encode(sha256(convert_to(app.final_settlement_source_state(%s,%s)::text,"
        "'UTF8')),'hex')",
        prop,
        settlement,
    )[0]
    assert draft["source_revision"] == f"final-settlement:{digest}"
    # A draft has no financial effect (BR-AUTH-010).
    assert balances(url, case) == before
    assert without_time(preview(prop, human, settlement)) == without_time(view)
    # An exact repeat replays; the same key with another plan is refused.
    assert record(case, normal_plan(case), pet_remainder=STAFF, key=key) == draft
    with pytest.raises(FinalSettlementKeyReused):
        record(case, normal_plan(case), pet_remainder=STAFF, key=key, reason="Another reason")
    # One pending draft per Settlement; the preparer may withdraw it and prepare again.
    assert refusal(record, case, normal_plan(case), pet_remainder=STAFF) == (
        "55000",
        "A Final Settlement draft is already waiting",
    )
    withdraw(case, draft)
    again = record(case, normal_plan(case), pet_remainder=STAFF)
    rejected = drafts().reject(
        prop,
        UUID(str(again["draft_id"])),
        "Recount the Deposits",
        actor=person(human, prop, APPROVE),
    )
    assert rejected["state"] == "REJECTED" and settlement_drafts(url, settlement) == 2
    assert balances(url, case) == before
    # Only final_settlements.prepare records a draft.
    for capabilities in ((APPROVE,), ("deposits.dispose",), ("refunds.create",)):
        with pytest.raises(FinalSettlementAuthorizationError):
            settlements().record_draft(
                prop,
                RecordFinalSettlementDraftCommand(
                    uuid4(), settlement, normal_plan(case), REASON, STAFF
                ),
                actor=person(human, prop, *capabilities),
            )


def test_the_strict_dl032_order_refuses_plans_that_break_it(migrated_database_url: str) -> None:
    url = migrated_database_url
    case = leaving_case(url)
    credit, pet, security = case["credit"], case["pet"], case["security"]
    pet_line, other_line = case["pet_line"], case["other_line"]

    def applied(
        kind: SettlementDepositStepKind, deposit: UUID, line: UUID, amount: int
    ) -> SettlementDepositStep:
        return SettlementDepositStep(kind, deposit, LINE, line, amount)

    first = SettlementCreditStep(credit, LINE, other_line, 400)
    pet_damage = applied(PET_FIRST, pet, pet_line, 12_500)
    security_step = applied(SECURITY, security, other_line, 10_000)
    rest = applied(PET_REST, pet, other_line, 2_100)
    pet_refund = refund(case, "pet", 5_400)
    agreement = "All Signers agreed in writing"
    conflict, invalid = "55000", "22023"
    no_refund = "No Deposit Refund while the Lease still has open debt that the Deposit could pay"
    cases: list[tuple[tuple[SettlementStep, ...], PetRemainderDecision | None, tuple[str, str]]] = [
        # Owner answer 3 (i): Credit before Deposits on the same Customer's obligations.
        (
            (
                pet_damage,
                security_step,
                applied(PET_REST, pet, other_line, 2_500),
                refund(case, "pet", 5_000),
            ),
            STAFF,
            (conflict, CREDIT_FIRST),
        ),
        (
            (first, security_step, pet_damage, rest, pet_refund),
            STAFF,
            (invalid, "Final Settlement steps must follow the DL-032 order"),
        ),
        (
            (first, applied(PET_FIRST, pet, other_line, 12_100)),
            None,
            (conflict, "The Pet Deposit first pays only valid pet damage"),
        ),
        (
            (first, applied(PET_FIRST, security, pet_line, 10_000)),
            None,
            (conflict, "The Deposit type does not match the DL-032 step"),
        ),
        (
            (first, applied(SECURITY, security, other_line, 12_101)),
            None,
            (conflict, "The amount exceeds what the obligation still owes"),
        ),
        (
            (SettlementCreditStep(credit, LINE, other_line, 401),),
            None,
            (conflict, "The amount exceeds the available Customer Credit"),
        ),
        (
            (SettlementCreditStep(uuid4(), LINE, other_line, 400),),
            None,
            (conflict, "The Customer Credit is not available to this Final Settlement"),
        ),
        (
            (first, applied(SECURITY, security, uuid4(), 100)),
            None,
            (conflict, "The target is not an open obligation of this Final Settlement"),
        ),
        (
            (first, pet_damage, applied(SECURITY, security, other_line, 12_100)),
            None,
            (conflict, "The amount exceeds what the Deposit holds"),
        ),
        # BR-SETTLE-008: every remaining Deposit balance is applied or refunded.
        (
            (first, pet_damage, security_step, rest),
            STAFF,
            (conflict, "Every remaining Deposit balance must be applied or refunded"),
        ),
        # Owner answer 3 (iii): no Refund while debt remains that the Deposit could pay; with no
        # BR-DEP-027 ground the staff step lets the Pet Deposit pay that debt.
        (
            (first, pet_damage, security_step, refund(case, "pet", 7_500)),
            None,
            (conflict, no_refund),
        ),
        (
            (
                first,
                pet_damage,
                applied(SECURITY, security, other_line, 4_000),
                applied(PET_REST, pet, other_line, 7_500),
                refund(case, "security", 6_000),
            ),
            STAFF,
            (conflict, no_refund),
        ),
        # Owner answer 3 (ii): pet damage before any other Pet Deposit use or Refund.
        (
            (
                first,
                applied(PET_FIRST, pet, pet_line, 2_500),
                applied(SECURITY, security, pet_line, 10_000),
                applied(PET_REST, pet, other_line, 12_100),
                refund(case, "pet", 5_400),
            ),
            STAFF,
            (conflict, "The Pet Deposit pays open pet damage before any other use or Refund"),
        ),
        # DL-032 step 5 needs the Customer's choice or the staff reason, and only then.
        (
            (first, pet_damage, security_step, rest, pet_refund),
            None,
            (invalid, "The remaining Pet Deposit needs the Customer's choice or the staff reason"),
        ),
        (
            (first, pet_damage, security_step, refund(case, "pet", 7_500)),
            STAFF,
            (invalid, "A remaining Pet Deposit basis needs a remaining Pet Deposit step"),
        ),
        # BR-REFUND-014 and BR-REFUND-015.
        (
            (
                first,
                pet_damage,
                security_step,
                rest,
                refund(case, "pet", 5_400, refund_method_id=uuid4()),
            ),
            STAFF,
            (conflict, "Refund Method is not active"),
        ),
        (
            (
                first,
                pet_damage,
                security_step,
                rest,
                refund(case, "pet", 5_400, signer_agreement=agreement),
            ),
            STAFF,
            (invalid, "The Primary Tenant needs no Signer agreement"),
        ),
        (
            (
                first,
                pet_damage,
                security_step,
                rest,
                refund(case, "pet", 5_400, recipient_customer_id=uuid4()),
            ),
            STAFF,
            (invalid, "A Refund to another Signer needs the written agreement of all Signers"),
        ),
        (
            (
                first,
                pet_damage,
                security_step,
                rest,
                refund(
                    case, "pet", 5_400, recipient_customer_id=uuid4(), signer_agreement=agreement
                ),
            ),
            STAFF,
            (conflict, "The Refund recipient must be a Signer of the Lease"),
        ),
        (
            (
                first,
                pet_damage,
                security_step,
                rest,
                refund(case, "pet", 2_000),
                refund(case, "pet", 3_400),
            ),
            STAFF,
            (invalid, "A Deposit has at most one Refund in a Final Settlement draft"),
        ),
    ]
    for steps, basis, expected in cases:
        assert refusal(record, case, steps, pet_remainder=basis) == expected, expected
    # Malformed plans the service cannot send are refused by the database too.
    good = RecordFinalSettlementDraftCommand(
        uuid4(), case["settlement"], normal_plan(case), REASON, STAFF
    ).plan()
    credit_step = cast(list[dict[str, Any]], good["steps"])[0]
    malformed: list[tuple[object, str]] = [
        ([], "Final Settlement plan is invalid"),
        ({**good, "extra": 1}, "Final Settlement plan is invalid"),
        (
            {**good, "steps": [{**credit_step, "kind": "WRITE_OFF"}]},
            "Final Settlement step kind is invalid",
        ),
    ]
    for change in (
        {"amount_usd_cents": "400"},
        {"amount_usd_cents": 0},
        {"amount_usd_cents": 1.5},
        {"note": "x"},
        {"target_id": str(UUID(int=0))},
        {"target_kind": None},
        {"customer_designation": " Tenant at the desk"},
        {"customer_designation": 5},
    ):
        malformed.append(
            ({**good, "steps": [{**credit_step, **change}]}, "Final Settlement step is invalid")
        )
    with psycopg.connect(financial_database_url()) as connection:
        for plan, message in malformed:
            with pytest.raises(psycopg.Error) as failure, connection.transaction():
                connection.execute(
                    RECORD_SQL,
                    (
                        case["prop"],
                        case["human"],
                        uuid4(),
                        case["settlement"],
                        Jsonb(plan),
                        REASON,
                        PREPARE,
                    ),
                )
            assert (failure.value.sqlstate, failure.value.diag.message_primary) == (
                invalid,
                message,
            )
    # No refusal left a draft behind; the valid plan is recorded.
    assert settlement_drafts(url, case["settlement"]) == 0
    record(case, normal_plan(case), pet_remainder=STAFF)
    assert settlement_drafts(url, case["settlement"]) == 1


def test_a_payment_after_the_draft_makes_its_source_revision_stale(
    migrated_database_url: str,
) -> None:
    """The plan check and the source digest are read in one call on one snapshot (Q-2026-10-05-29
    fixes). A payment that commits between two statements of one call cannot be scheduled from a
    test, because the call has no pause point; a payment after the draft is the observable case:
    the digest changes and the stored plan no longer passes the check (the confirm, 8e)."""
    url = migrated_database_url
    case = leaving_case(url)
    prop, human, settlement = case["prop"], case["human"], case["settlement"]
    draft = record(case, normal_plan(case), pet_remainder=STAFF)
    stored = cast(dict[str, Any], draft["payload"])
    plan = Jsonb({"steps": stored["steps"], "pet_remainder": stored["pet_remainder"]})
    check = "SELECT app.final_settlement_plan_result(%s,%s,%s,%s)"
    with psycopg.connect(url) as connection:
        fresh = connection.execute(check, (prop, human, settlement, plan)).fetchone()
    assert fresh is not None
    assert fresh[0]["source_revision"] == draft["source_revision"]
    assert {key: fresh[0][key] for key in ("closing_balance_usd_cents", "deposit_ids")} == {
        key: stored[key] for key in ("closing_balance_usd_cents", "deposit_ids")
    }
    other_invoice = one(
        url, "SELECT invoice_id FROM app.invoice_lines WHERE id=%s", case["other_line"]
    )[0]
    pay(url, prop, human, case["customer"], other_invoice, case["other_line"], 2_500)
    digest = one(
        url,
        "SELECT 'final-settlement:'||encode(sha256(convert_to("
        "app.final_settlement_source_state(%s,%s)::text,'UTF8')),'hex')",
        prop,
        settlement,
    )[0]
    assert digest != draft["source_revision"]
    with pytest.raises(psycopg.Error) as failure, psycopg.connect(url) as connection:
        connection.execute(check, (prop, human, settlement, plan))
    assert (failure.value.sqlstate, failure.value.diag.message_primary) == (
        "55000",
        "The amount exceeds what the obligation still owes",
    )


def two_signer_case(url: str, *, overdue_rent: bool = False) -> dict[str, Any]:
    """A signed Lease with a second signed Signer who lives there; the Primary Tenant never moved
    in, so no final Utility or cleaning issue applies. The Primary Tenant owes a 1,500 key card
    and holds a received Pet Deposit of 20,000; the Signer owes 1,000 and holds 400 of Credit
    released from a paid Invoice. With overdue_rent the Primary Tenant also owes an overdue Rent
    Invoice (80,000) and its Late-payment Charge (8,000)."""
    now = today(url)
    first = now.replace(year=now.year - 1, month=1, day=1)
    with psycopg.connect(url) as connection:
        human, prop, unit, tenant, co_signer = setup_sources(connection)
        lease = create_draft(
            connection,
            actor_id=human,
            unit_id=unit,
            primary_tenant_id=tenant,
            start_date=first,
            end_date=now.replace(year=now.year + 1, month=12, day=31),
        )
        connection.execute(
            "INSERT INTO app.lease_signers(id,lease_id,customer_id,signed_at,added_by) "
            "VALUES (%s,%s,%s,statement_timestamp(),%s)",
            (uuid4(), lease, co_signer, human),
        )
        sign_lease(connection, lease, human)
        connection.execute(
            "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,"
            "created_by,updated_by) VALUES (%s,%s,%s,%s,%s,%s)",
            (uuid4(), lease, co_signer, first, human, human),
        )
        rent = None
        if overdue_rent:
            period = (now.replace(day=1) - timedelta(days=62)).replace(day=1)
            rent, rent_line_id = create_recurring_rent_invoice(
                connection, actor_id=human, customer_id=tenant, lease_id=lease, period_start=period
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    staff = invoice_api_actor(human, prop)
    lines: dict[str, UUID] = {}
    invoices_of: dict[str, UUID] = {}
    # The billing commands bill the Primary Tenant; an Invoice of another Signer comes from an
    # authorized obligation naming that Signer (migration 29), as in the 8a fixture.
    for name, amount in (("paid", 2_500), ("signer", 1_000)):
        obligation = uuid4()
        reference = f"approved-obligation/{obligation}"
        with psycopg.connect(url) as connection:
            connection.execute(
                "INSERT INTO app.authorized_nonrecurring_obligations("
                "id,customer_id,lease_id,category,description,authorized_amount_usd_cents,"
                "governing_due_date,due_date_source,source_reference,authorized_at,authorized_by,"
                "authorization_reference) VALUES (%s,%s,%s,'MISCELLANEOUS_CHARGES',"
                "'Authorized replacement key',%s,current_date+14,%s,%s,clock_timestamp(),%s,"
                "'invoice.nonrecurring.authorize')",
                (obligation, co_signer, lease, amount, reference, reference, human),
            )
        draft = invoices().create_draft(
            prop, CreateInvoiceDraftCommand(uuid4(), obligation), actor=staff
        )
        invoices_of[name] = UUID(str(draft["id"]))
        invoices().issue(
            prop,
            invoices_of[name],
            IssueInvoiceCommand(uuid4(), int(str(draft["version"]))),
            actor=staff,
        )
        lines[name] = line_of(url, invoices_of[name])
    tenant_charge = key_card(tenant, lease)
    invoices().record_one_time_charge(prop, tenant_charge, actor=staff)
    lines["tenant"] = line_of(url, draft_and_issue(prop, tenant_charge.charge_id, staff)["id"])
    # A credit Adjustment on the Signer's paid line releases 400 of the Signer's Credit.
    pay(url, prop, human, co_signer, invoices_of["paid"], lines["paid"], 2_500)
    credit_adjustment(url, human, prop, invoices_of["paid"], lines["paid"])
    credit = UUID(
        str(one(url, "SELECT id FROM app.customer_credits WHERE customer_id=%s", co_signer)[0])
    )
    charge_id = None
    if rent is not None:
        flow = late_payments()
        review = flow.review(rent, actor=late_payment_actor(human, prop))
        amount = cast(dict[str, int], review["calculated_default_amount"])["minor_units"]
        flow.finalize_decision(
            prop,
            rent,
            FinalizeLatePaymentDecisionCommand(
                uuid4(), DecisionOutcome.CONFIRMED_DEFAULT, amount, "Approved default charge"
            ),
            actor=late_payment_actor(human, prop),
        )
        charge_id = UUID(
            str(
                one(
                    url, "SELECT id FROM app.late_payment_charges WHERE source_invoice_id=%s", rent
                )[0]
            )
        )
    pet = pet_deposit(url, human, prop, lease, now)
    terminate(url, human, prop, lease, now, voluntary=False)
    # Sub-slice 8e-3: every Rent month of the Lease is billed and paid (RENT_PERIOD_NOT_BILLED).
    bill_unbilled_rent_months(url, human, prop, lease)
    return {
        "human": human,
        "prop": prop,
        "lease": lease,
        "tenant": tenant,
        "customer": tenant,
        "co_signer": co_signer,
        "credit": credit,
        "pet": pet,
        "rent": rent,
        "rent_line": rent_line_id if rent is not None else None,
        "charge": charge_id,
        "signer_line": lines["signer"],
        "tenant_line": lines["tenant"],
        "settlement": start(prop, human, lease),
        "cash": UUID(str(one(url, "SELECT id FROM app.refund_methods WHERE code='CASH'")[0])),
    }


def test_each_customer_s_credit_pays_only_and_always_its_own_debt(
    migrated_database_url: str,
) -> None:
    """BR-CREDIT-008 and owner answer 2 to Q-2026-10-05-29: the Signer's Credit pays only the
    Signer's debt, and must pay it even when no Deposit pays the Signer; a Deposit Refund may go to
    the other signed Signer with the written agreement of all Signers (BR-REFUND-015)."""
    url = migrated_database_url
    case = two_signer_case(url)
    view = preview(case["prop"], case["human"], case["settlement"])
    assert view["ready"] is True and view["open_total_usd_cents"] == 2_500
    signer_credit = SettlementCreditStep(case["credit"], LINE, case["signer_line"], 400)
    pet_rest = SettlementDepositStep(PET_REST, case["pet"], LINE, case["tenant_line"], 1_500)
    agreement = "All Signers agreed in writing on 2026-10-05 that the Signer receives the Refund"
    to_signer = refund(
        case,
        "pet",
        17_900,
        recipient_customer_id=case["co_signer"],
        signer_agreement=agreement,
    )
    signer_rest = SettlementDepositStep(PET_REST, case["pet"], LINE, case["signer_line"], 600)
    assert refusal(
        record,
        case,
        (SettlementCreditStep(case["credit"], LINE, case["tenant_line"], 400),),
    ) == ("55000", "A Customer Credit pays only its own Customer's obligations")
    # The Pet Deposit pays only the Primary Tenant here; the Signer's Credit must still be used.
    assert refusal(
        record,
        case,
        (pet_rest, refund(case, "pet", 18_500)),
        pet_remainder=STAFF,
    ) == ("55000", CREDIT_FIRST)
    assert refusal(
        record,
        case,
        (
            SettlementCreditStep(case["credit"], LINE, case["signer_line"], 300),
            pet_rest,
            SettlementDepositStep(PET_REST, case["pet"], LINE, case["signer_line"], 700),
            refund(case, "pet", 17_800),
        ),
        pet_remainder=STAFF,
    ) == ("55000", CREDIT_FIRST)
    draft = record(case, (signer_credit, pet_rest, signer_rest, to_signer), pet_remainder=STAFF)
    payload = cast(dict[str, Any], draft["payload"])
    assert payload["closing_balance_usd_cents"] == 0 and payload["closing_balances"] == []
    assert payload["steps"][-1]["recipient_customer_id"] == str(case["co_signer"])
    assert payload["steps"][-1]["signer_agreement"] == agreement


def test_a_late_payment_charge_and_a_rent_invoice_follow_the_credit_and_deposit_rules(
    migrated_database_url: str,
) -> None:
    """A Deposit may pay a Late-payment Charge and a Rent line (owner answer 1 to
    Q-2026-10-05-20); the closing balance stays with the Customer named on each obligation."""
    url = migrated_database_url
    case = two_signer_case(url, overdue_rent=True)
    view = preview(case["prop"], case["human"], case["settlement"])
    assert view["ready"] is True
    assert (outstanding(url, case["rent_line"]), view["open_total_usd_cents"]) == (
        80_000,
        80_000 + 8_000 + 2_500,
    )
    plan = (
        SettlementCreditStep(case["credit"], LINE, case["signer_line"], 400),
        SettlementDepositStep(
            PET_REST, case["pet"], SettlementTargetKind.LATE_PAYMENT_CHARGE, case["charge"], 8_000
        ),
        SettlementDepositStep(PET_REST, case["pet"], LINE, case["signer_line"], 600),
        SettlementDepositStep(PET_REST, case["pet"], LINE, case["rent_line"], 11_400),
    )
    draft = record(case, plan, pet_remainder=STAFF)
    payload = cast(dict[str, Any], draft["payload"])
    assert payload["steps"][1]["target_kind"] == "LATE_PAYMENT_CHARGE"
    assert payload["closing_balance_usd_cents"] == 80_000 + 1_500 - 11_400
    assert payload["closing_balances"] == [
        {"customer_id": str(case["tenant"]), "open_usd_cents": 80_000 + 1_500 - 11_400}
    ]


def test_credit_on_a_rent_invoice_follows_the_rent_first_proposal_order(
    migrated_database_url: str,
) -> None:
    """BR-CREDIT-006 (owner answer 1 to Q-2026-10-05-29): on an Invoice with Rent or Service lines
    the first line that still owes, in the order of the Credit proposal (Rent, then recurring
    Services, then the others by line order), is the only line Credit may pay without the
    Customer's designation; other Invoices are not restricted."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        human, prop, _customer, lease, occupancy = setup_billing_source(connection)
    issued = PostgresRentBillingService(financial_database_url(), prop, human).generate(
        initial_command(lease, occupancy), actor=authenticated(human, prop)
    )
    with psycopg.connect(url) as connection:
        lines = [
            (UUID(str(row[0])), str(row[1]))
            for row in connection.execute(
                "SELECT id,category FROM app.invoice_lines WHERE invoice_id=%s "
                "ORDER BY line_sequence,id",
                (issued.invoice_id,),
            ).fetchall()
        ]
    assert lines[0][1] == "RENT" and len(lines) >= 2
    first_line = "SELECT app.final_settlement_rent_first_line(%s,%s)"

    def first(open_lines: dict[UUID, int]) -> object:
        open_map = Jsonb({f"INVOICE_LINE:{line}": amount for line, amount in open_lines.items()})
        return one(url, first_line, issued.invoice_id, open_map)[0]

    everything = {line: 100 for line, _ in lines}
    assert first(everything) == lines[0][0]
    assert first({**everything, lines[0][0]: 0}) == lines[1][0]
    assert first({line: 0 for line, _ in lines}) is None
    # An Invoice without Rent or Service lines is not restricted.
    other = two_signer_case(url)
    other_invoice = one(
        url, "SELECT invoice_id FROM app.invoice_lines WHERE id=%s", other["tenant_line"]
    )[0]
    assert (
        one(url, first_line, other_invoice, Jsonb({f"INVOICE_LINE:{other['tenant_line']}": 1}))[0]
        is None
    )


def mixed_rent_case(url: str) -> dict[str, Any]:
    """A Lease that never moved in, whose Initial Rent Invoice has a Rent line and two recurring
    Service lines (the billing fixture's Trash Collection and Internet terms, without its
    occupancy), terminated with no ground; the Primary Tenant holds 500,000 of Credit, more than
    the Invoice owes, so the Credit must pay the whole Invoice (owner answer 2 to Q-2026-10-05-29).
    Initial Rent has no Late-payment review (migration 68)."""
    with psycopg.connect(url) as connection:
        human, prop, unit, tenant, _ = setup_sources(connection)
        lease = create_draft(
            connection,
            actor_id=human,
            unit_id=unit,
            primary_tenant_id=tenant,
            start_date=date(2026, 7, 27),
            end_date=date(2027, 6, 30),
        )
        sign_lease(connection, lease, human)
        for code, name, first_rate, second_rate in (
            ("TRASH_COLLECTION", "Trash Collection", 1_000, 1_200),
            ("INTERNET", "Internet", 2_500, 2_700),
        ):
            add_service(
                connection,
                actor_id=human,
                property_id=prop,
                lease_id=lease,
                code=code,
                display_name=name,
                first_rate=first_rate,
                second_rate=second_rate,
            )
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=tenant, amount=500_000
        )
        connection.commit()
    # The Payment's excess becomes Credit before any obligation exists: recognition is refused
    # while the payer has applicable obligations (app.assert_payment_excess_eligible).
    credit = credit_id(recognize(prop, payment, human, 500_000))
    issued = PostgresRentBillingService(financial_database_url(), prop, human).generate(
        initial_command(lease, uuid4()), actor=authenticated(human, prop)
    )
    with psycopg.connect(url) as connection:
        lines = [
            (UUID(str(row[0])), str(row[1]))
            for row in connection.execute(
                "SELECT id,category FROM app.invoice_lines WHERE invoice_id=%s "
                "ORDER BY line_sequence,id",
                (issued.invoice_id,),
            ).fetchall()
        ]
    terminate(url, human, prop, lease, today(url), voluntary=False)
    # Sub-slice 8e-3: every Rent month of the Lease is billed and paid (RENT_PERIOD_NOT_BILLED).
    bill_unbilled_rent_months(url, human, prop, lease)
    return {
        "human": human,
        "prop": prop,
        "lease": lease,
        "customer": tenant,
        "credit": credit,
        "invoice": issued.invoice_id,
        "lines": lines,
        "settlement": start(prop, human, lease),
        "cash": UUID(str(one(url, "SELECT id FROM app.refund_methods WHERE code='CASH'")[0])),
    }


def test_credit_on_a_mixed_rent_invoice_follows_the_proposal_or_a_designation(
    migrated_database_url: str,
) -> None:
    """BR-CREDIT-006 (owner answer 1 to Q-2026-10-05-29) through the plan check: without the
    Customer's designation, Credit pays the Rent line before the Service lines, and the Service
    lines in their order, as the Credit proposal does; with the designation staff may name any
    line, and the text is stored."""
    url = migrated_database_url
    case = mixed_rent_case(url)
    view = preview(case["prop"], case["human"], case["settlement"])
    assert view["ready"] is True
    (rent, rent_category), (trash, trash_category), (internet, internet_category) = case["lines"]
    assert (rent_category, trash_category, internet_category) == (
        "RENT",
        "SERVICE_CHARGES",
        "SERVICE_CHARGES",
    )
    owed = {line: outstanding(url, line) for line, _ in case["lines"]}
    assert all(amount > 0 for amount in owed.values())
    assert view["open_total_usd_cents"] == sum(owed.values()) < 500_000

    def credit(line: UUID, designation: str | None = None) -> SettlementCreditStep:
        return SettlementCreditStep(case["credit"], LINE, line, owed[line], designation)

    rent_first = (
        "Credit on an Invoice with Rent or Service lines follows the Rent-first proposal unless "
        "the Customer designated the line"
    )
    for steps in (
        (credit(trash), credit(rent), credit(internet)),
        (credit(rent), credit(internet), credit(trash)),
    ):
        assert refusal(record, case, steps) == ("55000", rent_first)
    # The proposal order (Rent, then Services by line order) closes the Invoice.
    proposed = record(case, (credit(rent), credit(trash), credit(internet)))
    assert cast(dict[str, Any], proposed["payload"])["closing_balance_usd_cents"] == 0
    withdraw(case, proposed)
    # The Customer's designation lets staff pay a Service line first; the text is kept.
    designation = "Primary Tenant asked on 2026-10-05, by signed note, to clear Internet first"
    designated = record(case, (credit(internet, designation), credit(rent), credit(trash)))
    stored = cast(dict[str, Any], designated["payload"])["steps"]
    assert [step["customer_designation"] for step in stored] == [designation, None, None]
    # The helper gives the same order as the existing Credit proposal.
    with psycopg.connect(url) as connection:
        found = connection.execute(
            "SELECT app.credit_application_proposal(%s,%s,%s,%s,clock_timestamp())",
            (case["prop"], case["credit"], case["invoice"], sum(owed.values())),
        ).fetchone()
    assert found is not None
    proposal_order = [UUID(item["invoice_line_id"]) for item in found[0]["details"]]
    assert proposal_order == [rent, trash, internet]


def test_a_security_refund_follows_once_no_debt_is_left(migrated_database_url: str) -> None:
    """Owner answer 3 (iii): the Security Deposit may be refunded once the debt is paid; staff
    choose which Deposit pays which obligation (BR-SETTLE-006)."""
    url = migrated_database_url
    case = leaving_case(url)
    # Owner answer to choice (4a) of sub-slice 8c (2026-10-05, built in 8d): this plan uses the
    # remaining Pet Deposit for debt the Security Deposit could still pay, so it is now refused.
    # The test name is kept under the run rules; the accepted Security Refund is in
    # test_the_remaining_pet_deposit_pays_only_debt_left_after_the_security_deposit (docs/010).
    assert refusal(
        record,
        case,
        (
            SettlementCreditStep(case["credit"], LINE, case["other_line"], 400),
            SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], 12_500),
            SettlementDepositStep(SECURITY, case["security"], LINE, case["other_line"], 4_600),
            SettlementDepositStep(PET_REST, case["pet"], LINE, case["other_line"], 7_500),
            refund(case, "security", 5_400),
        ),
        pet_remainder=CHOICE,
    ) == ("55000", AFTER_SECURITY)


def test_the_remaining_pet_deposit_pays_only_debt_left_after_the_security_deposit(
    migrated_database_url: str,
) -> None:
    """Owner answer to choice (4a) of sub-slice 8c (2026-10-05, built in 8d): the remaining Pet
    Deposit (DL-032 step 5) pays only debt still open after the Security Deposit has been used,
    by the staff step or by the Customer's choice. Refused at draft time and by the plan check
    the confirm (8e) runs again. A Security Deposit Refund follows only when no debt is left."""
    url = migrated_database_url
    case = leaving_case(url)
    prop, human, settlement = case["prop"], case["human"], case["settlement"]
    first = SettlementCreditStep(case["credit"], LINE, case["other_line"], 400)
    pet_damage = SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], 12_500)

    def security(amount: int) -> SettlementDepositStep:
        return SettlementDepositStep(SECURITY, case["security"], LINE, case["other_line"], amount)

    def pet_rest(amount: int) -> SettlementDepositStep:
        return SettlementDepositStep(PET_REST, case["pet"], LINE, case["other_line"], amount)

    # The other damage owes 12,100 after the Credit. The Security Deposit pays 4,600 and keeps
    # 5,400, the remaining Pet Deposit pays the other 7,500 and the Security Deposit is refunded:
    # no debt is left, but the Pet Deposit paid debt the Security Deposit could still pay.
    four_a = (first, pet_damage, security(4_600), pet_rest(7_500), refund(case, "security", 5_400))
    for basis in (STAFF, CHOICE):
        assert refusal(record, case, four_a, pet_remainder=basis) == (
            "55000",
            AFTER_SECURITY,
        ), basis
    # One cent left in the Security Deposit is enough to refuse step 5.
    one_cent = (
        first,
        pet_damage,
        security(9_999),
        pet_rest(2_101),
        refund(case, "security", 1),
        refund(case, "pet", 5_399),
    )
    assert refusal(record, case, one_cent, pet_remainder=STAFF) == ("55000", AFTER_SECURITY)
    # The plan check that the confirm (8e) calls again refuses the same plan.
    plan = RecordFinalSettlementDraftCommand(uuid4(), settlement, four_a, REASON, CHOICE).plan()
    with pytest.raises(psycopg.Error) as failure, psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.final_settlement_plan_result(%s,%s,%s,%s)",
            (prop, human, settlement, Jsonb(plan)),
        )
    assert (failure.value.sqlstate, failure.value.diag.message_primary) == (
        "55000",
        AFTER_SECURITY,
    )
    # A Security Refund while debt is left stays refused (owner answer 3 (iii)).
    early = (first, pet_damage, security(4_000), refund(case, "security", 6_000))
    assert refusal(record, case, (*early, refund(case, "pet", 7_500))) == ("55000", NO_REFUND)
    assert settlement_drafts(url, settlement) == 0
    # Once the Security Deposit is used up, the remaining Pet Deposit may pay the rest, by the
    # staff step or by the Customer's choice.
    for basis in (STAFF, CHOICE):
        used_up = record(case, normal_plan(case), pet_remainder=basis)
        stored = cast(dict[str, Any], used_up["payload"])
        assert stored["closing_balance_usd_cents"] == 0
        # The basis, with the Customer's choice as text (who, the date, how), is stored.
        assert stored["pet_remainder"] == basis.payload()
        assert stored["pet_remainder_chosen_by"] == "CUSTOMER_OR_STAFF_WITH_REASON"
        withdraw(case, used_up)
    # With less debt the Security Deposit pays all of it and its rest is refunded.
    other_invoice = one(
        url, "SELECT invoice_id FROM app.invoice_lines WHERE id=%s", case["other_line"]
    )[0]
    pay(url, prop, human, case["customer"], other_invoice, case["other_line"], 5_000)
    draft = record(
        case,
        (
            first,
            pet_damage,
            security(7_100),
            refund(case, "security", 2_900),
            refund(case, "pet", 7_500),
        ),
    )
    payload = cast(dict[str, Any], draft["payload"])
    assert payload["closing_balance_usd_cents"] == 0
    assert [step["kind"] for step in payload["steps"]][-2:] == ["DEPOSIT_REFUNDS"] * 2


def test_a_br_dep_027_termination_lets_only_the_customer_choose_the_pet_remainder(
    migrated_database_url: str,
) -> None:
    """Unpaid Initial Rent (BR-LEASE-005): the Security Deposit holds nothing after its receipts
    are reversed; the Pet Deposit pays pet damage first, then other debt only by the Customer's
    choice, otherwise its rest is refunded and the debt stays (Q-2026-10-05-21)."""
    url = migrated_database_url
    case = leaving_case(url, unpaid_initial=True)
    prop, human = case["prop"], case["human"]
    with psycopg.connect(url) as connection:
        receipts = connection.execute(
            "SELECT id FROM app.deposit_receipts WHERE deposit_id=%s ORDER BY occurred_at,id",
            (case["security"],),
        ).fetchall()
    for (receipt,) in receipts:
        reversal = DepositReceiptReversalService(financial_database_url())
        approver = person(human, prop, "deposits.correct", APPROVE)
        recorded = reversal.record(
            prop,
            RecordDepositReceiptReversalCommand(uuid4(), UUID(str(receipt)), uuid4(), "Returned"),
            actor=approver,
        )
        reversal.confirm(prop, UUID(str(receipt)), UUID(str(recorded["draft_id"])), actor=approver)
    view = preview(prop, human, case["settlement"])
    assert view["ready"] is True and view["lease"]["termination_ground"] == "BR-LEASE-005"
    assert view["steps"][4]["chosen_by"] == "CUSTOMER_ONLY"
    debt = view["open_total_usd_cents"] - 12_500
    pet_damage = SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], 12_500)
    rest = SettlementDepositStep(PET_REST, case["pet"], LINE, case["other_line"], 7_500)
    assert refusal(record, case, (pet_damage, rest), pet_remainder=STAFF) == (
        "55000",
        "At this termination only the Customer may choose to use the remaining Pet Deposit",
    )
    nothing_held = SettlementDepositStep(SECURITY, case["security"], LINE, case["other_line"], 1)
    assert refusal(record, case, (nothing_held,)) == (
        "55000",
        "Only a Deposit that follows DL-032 and holds money may be applied",
    )
    chosen = record(case, (pet_damage, rest), pet_remainder=CHOICE)
    assert cast(dict[str, Any], chosen["payload"])["closing_balance_usd_cents"] == debt - 7_500
    withdraw(case, chosen)
    # Without the Customer's choice the rest is refunded and the debt stays.
    refunded = record(case, (pet_damage, refund(case, "pet", 7_500)))
    payload = cast(dict[str, Any], refunded["payload"])
    assert payload["closing_balance_usd_cents"] == debt
    assert payload["closing_balances"] == [
        {"customer_id": str(case["customer"]), "open_usd_cents": debt}
    ]
    assert payload["deposit_ids"] == [str(case["pet"])]


def test_receipt_reversals_and_settlement_drafts_wait_for_each_other(
    migrated_database_url: str,
) -> None:
    """Owner answer 4 to Q-2026-10-05-23, in both directions."""
    url = migrated_database_url
    case = leaving_case(url)
    prop, human = case["prop"], case["human"]
    receipt = UUID(
        str(one(url, "SELECT id FROM app.deposit_receipts WHERE deposit_id=%s", case["pet"])[0])
    )
    reversals = DepositReceiptReversalService(financial_database_url())
    corrector = person(human, prop, "deposits.correct", APPROVE)
    # A receipt reversal draft that waits blocks the Settlement draft (preview PENDING_DRAFT).
    waiting = reversals.record(
        prop,
        RecordDepositReceiptReversalCommand(uuid4(), receipt, uuid4(), "Transfer returned"),
        actor=corrector,
    )
    assert refusal(record, case, normal_plan(case), pet_remainder=STAFF) == (
        "55000",
        "The Final Settlement has blocking issues",
    )
    drafts().withdraw(
        prop,
        UUID(str(waiting["draft_id"])),
        "Recorded by mistake",
        prepare_capability="deposits.correct",
        actor=corrector,
    )
    draft = record(case, normal_plan(case), pet_remainder=STAFF)
    # While the Settlement draft waits, no receipt reversal of a Deposit it uses is recorded ...
    with pytest.raises(DepositReceiptReversalConflictError):
        reversals.record(
            prop,
            RecordDepositReceiptReversalCommand(uuid4(), receipt, uuid4(), "Transfer returned"),
            actor=corrector,
        )
    # ... or confirmed: the receipt reversal guard refuses even the earlier one-call path.
    with pytest.raises(DepositInvalidError) as failure:
        reverse_receipt_as_owner(
            PostgresDepositService(financial_database_url(), prop, human),
            ReverseDepositReceiptCommand(uuid4(), uuid4(), receipt, "Transfer returned"),
            actor=deposit_actor(human, prop),
        )
    cause = failure.value.__cause__
    assert isinstance(cause, psycopg.Error)
    assert cause.diag.message_primary == "Deposit receipt has active dependent financial history"
    # A Settlement draft is not confirmed while a receipt reversal draft of its Deposit waits.
    # The recorder refuses that order, so the waiting draft is written as the owner.
    reversal_draft = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.insert_financial_draft(%s,%s,%s,'DEPOSIT_FORFEITURE','deposits.correct',"
            "%s,'deposit-state:0','Transfer returned')",
            (
                prop,
                human,
                reversal_draft,
                Jsonb(
                    {
                        "variant": "DEPOSIT_RECEIPT_REVERSAL",
                        "deposit_id": str(case["pet"]),
                        "receipt_id": str(receipt),
                        "reversal_id": str(uuid4()),
                    }
                ),
            ),
        )
    confirm = (
        "SELECT app.confirm_financial_draft_record(%s,%s,%s,'FINAL_SETTLEMENT','{}'::jsonb,"
        "'financial.approve')"
    )
    with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
        connection.execute(confirm, (prop, human, draft["draft_id"]))
    assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
        "55000",
        "A Deposit receipt reversal draft for this Deposit is waiting",
    )
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.withdraw_financial_draft(%s,%s,%s,%s,'deposits.correct')",
            (prop, human, reversal_draft, "Recorded by mistake"),
        )
        connection.execute(confirm, (prop, human, draft["draft_id"]))
    assert one(
        url,
        "SELECT decision FROM app.financial_draft_decisions WHERE draft_id=%s",
        draft["draft_id"],
    ) == ("CONFIRMED",)


def test_replaced_one_time_charges_are_listed_as_information(migrated_database_url: str) -> None:
    """Owner answer to Q-2026-10-05-28: a charge a draft correction replaced is listed with the
    charge that replaced it, whether that charge is on another Lease or on no Lease."""
    url = migrated_database_url
    now = today(url)
    with psycopg.connect(url) as connection:
        human, prop, customer, lease = setup_signed_lease(
            connection,
            start_date=now.replace(year=now.year - 1, month=1, day=1),
            end_date=now.replace(year=now.year + 1, month=12, day=31),
            with_occupancy=False,
        )
        _, _, other_customer, other_lease = setup_signed_lease(
            connection,
            start_date=now.replace(year=now.year - 1, month=1, day=1),
            end_date=now.replace(year=now.year + 1, month=12, day=31),
            with_occupancy=False,
        )
    staff = invoice_api_actor(human, prop)
    no_lease = RecordOneTimeChargeCommand(
        uuid4(),
        "MISCELLANEOUS_CHARGES",
        customer,
        None,
        None,
        "Replacement key card",
        1_500,
        "Customer lost key card",
        "Front desk log 903",
    )
    replaced: list[tuple[RecordOneTimeChargeCommand, RecordOneTimeChargeCommand]] = [
        (key_card(customer, lease), key_card(other_customer, other_lease)),
        (key_card(customer, lease), no_lease),
    ]
    for charge, replacement in replaced:
        invoices().record_one_time_charge(prop, charge, actor=staff)
        draft = invoices().create_draft(
            prop, CreateInvoiceDraftCommand(uuid4(), charge.charge_id), actor=staff
        )
        invoices().record_one_time_charge(prop, replacement, actor=staff)
        invoices().correct_draft(
            prop,
            UUID(str(draft["id"])),
            CorrectInvoiceDraftCommand(
                uuid4(),
                replacement.charge_id,
                "Wrong charge on the draft",
                cast(int, draft["version"]),
            ),
            actor=staff,
        )
    terminate(url, human, prop, lease, now, voluntary=False)
    # Sub-slice 8e-3: every Rent month of the Lease is billed and paid (RENT_PERIOD_NOT_BILLED).
    bill_unbilled_rent_months(url, human, prop, lease)
    view = preview(prop, human, start(prop, human, lease))
    assert view["information"] == [
        {
            "code": "CHARGE_REPLACED_BY_DRAFT_CORRECTION",
            "authorized_obligation_id": str(charge.charge_id),
            "customer_id": str(customer),
            "category": "MISCELLANEOUS_CHARGES",
            "amount_usd_cents": 1_500,
            "replacement_authorized_obligation_id": str(replacement.charge_id),
            "replacement_lease_id": None if replacement.lease_id is None else str(other_lease),
        }
        for charge, replacement in replaced
    ]
    # Neither replaced charge blocks, and the drafts moved to another Lease or to none.
    assert view["blocking_issues"] == [] and view["ready"] is True


def test_settlement_drafts_are_least_privilege(migrated_database_url: str) -> None:
    url = migrated_database_url
    case = leaving_case(url)
    prop, human, settlement = case["prop"], case["human"], case["settlement"]
    with psycopg.connect(url) as connection:
        for role in ("public", "prm_runtime", "prm_financial", "prm_bootstrap"):
            assert connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, RECORD)
            ).fetchone() == ((role == "prm_financial"),), role
            for function in INTERNAL:
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (role, function)
        for function in (RECORD, *INTERNAL[1:]):
            assert connection.execute(
                "SELECT prosecdef,proconfig @> ARRAY['search_path=pg_catalog'] FROM pg_proc "
                "WHERE oid=%s::regprocedure",
                (function,),
            ).fetchone() == (True, True), function
    plan = Jsonb(
        RecordFinalSettlementDraftCommand(
            uuid4(), settlement, normal_plan(case), REASON, STAFF
        ).plan()
    )
    with (
        pytest.raises(psycopg.Error) as failure,
        psycopg.connect(runtime_database_url()) as runtime,
    ):
        runtime.execute(RECORD_SQL, (prop, human, uuid4(), settlement, plan, REASON, PREPARE))
    assert failure.value.sqlstate == "42501"
    with psycopg.connect(financial_database_url()) as connection:
        for authorization in ("financial.approve", "deposits.dispose"):
            with pytest.raises(psycopg.Error) as failure, connection.transaction():
                connection.execute(
                    RECORD_SQL, (prop, human, uuid4(), settlement, plan, REASON, authorization)
                )
            assert failure.value.sqlstate == "42501"
    with pytest.raises(FinalSettlementNotFoundError):
        settlements().record_draft(
            prop,
            RecordFinalSettlementDraftCommand(uuid4(), uuid4(), normal_plan(case), REASON, STAFF),
            actor=person(human, prop, PREPARE),
        )
    assert settlement_drafts(url, settlement) == 0


def test_final_settlement_draft_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261025_90")
    assert revision is not None and revision.down_revision == "20261024_89"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
