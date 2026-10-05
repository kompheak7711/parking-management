"""V1-056 sub-slice 8e-2: the Final Settlement's Credit applications and their internal writer."""

from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from property_rental.credit import (
    ApplyCreditCommand,
    CreditConflictError,
    ReverseCreditApplicationCommand,
)
from property_rental.final_settlement import (
    SettlementCreditStep,
    SettlementDepositStep,
    SettlementTargetKind,
)
from property_rental.invoice import AdjustInvoiceCommand, AdjustmentType, InvoiceConflictError
from test_credit_migration import actor as credit_actor
from test_credit_migration import service as credits
from test_final_settlement_closed_refusal_migration import close, no_lease_charge
from test_final_settlement_draft_migration import (
    LINE,
    PET_REST,
    STAFF,
    leaving_case,
    mixed_rent_case,
    normal_plan,
    record,
    two_signer_case,
    withdraw,
)
from test_final_settlement_migration import charge_remaining, held, line_of, one, outstanding
from test_final_settlement_preview_migration import credit_adjustment, pay, preview
from test_invoice_migration import (
    financial_database_url,
    invoice_api_actor,
    runtime_database_url,
    setup_signed_lease,
)
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_one_time_charges_migration import draft_and_issue, invoices

POST = "SELECT app.post_final_settlement_credit_application(%s,%s,%s,%s,%s)"
POST_SIGNATURE = "app.post_final_settlement_credit_application(uuid,uuid,uuid,uuid,integer)"
CONFIRM = (
    "SELECT app.confirm_financial_draft_record(%s,%s,%s,'FINAL_SETTLEMENT','{}'::jsonb,"
    "'financial.approve')"
)
DEPOSIT_APPLICATION = "SELECT app.post_deposit_application(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
REFUND = "SELECT app.post_final_settlement_deposit_refund(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
INTERNAL = (
    "app.final_settlement_credit_application_id(uuid,integer)",
    "app.assert_final_settlement_credit_application_source()",
    "app.assert_final_settlement_credit_application_confirmed()",
    "app.refuse_final_settlement_credit_application_reversal()",
    POST_SIGNATURE,
)
NOT_IN_DRAFT = (
    "A Final Settlement Credit application must be a Credit step of a waiting or confirmed draft "
    "of this Settlement"
)
NOT_CONFIRMED = (
    "A Final Settlement Credit application needs its draft confirmed under financial.approve by "
    "the same approver"
)
REVERSAL_REFUSED = (
    "A Final Settlement Credit application changes only through a post-settlement correction"
)
RENT_FIRST = (
    "Credit on an Invoice with Rent or Service lines follows the Rent-first proposal unless the "
    "Customer designated the line"
)
CREDIT_FIRST = (
    "Customer Credit is applied before the Final Settlement Deposit applications and Refunds"
)
NOT_A_CREDIT_STEP = "The draft step is not a Customer Credit step"
WRONG_OBLIGATION = (
    "A Final Settlement Credit application pays exactly the obligation of its Credit step"
)
OTHER_LEASE = "The Credit target must be an obligation of the terminated Settlement Lease"
SOURCE_INVALID = "Credit application source, target, amount or chronology is invalid"
REASON = "Final Settlement confirmed by the approver"


def write(
    connection: psycopg.Connection[Any],
    case: dict[str, Any],
    draft: object,
    step: int,
    actor: UUID | None = None,
) -> dict[str, Any]:
    """The internal writer, as the Settlement confirm (8e-3) will call it; no role may call it."""
    found = connection.execute(
        POST, (case["prop"], actor or case["human"], case["settlement"], UUID(str(draft)), step)
    ).fetchone()
    assert found is not None and isinstance(found[0], dict)
    return cast(dict[str, Any], found[0])


def decide(
    connection: psycopg.Connection[Any],
    case: dict[str, Any],
    draft: object,
    approver: UUID | None = None,
) -> None:
    """The draft decision the confirm (8e-3) writes, through the shared slice 2 record."""
    connection.execute(CONFIRM, (case["prop"], approver or case["human"], UUID(str(draft))))


def refused(url: str, *statements: tuple[str, tuple[object, ...]]) -> tuple[Any, Any]:
    """Run the statements in one transaction; the refusal rolls back everything."""
    with pytest.raises(psycopg.Error) as failure, psycopg.connect(url) as connection:
        for sql, parameters in statements:
            connection.execute(sql, parameters)
    return failure.value.sqlstate, failure.value.diag.message_primary


def post(
    case: dict[str, Any], draft: object, step: int, actor: UUID | None = None
) -> tuple[str, tuple[object, ...]]:
    return POST, (case["prop"], actor or case["human"], case["settlement"], UUID(str(draft)), step)


def confirm(
    case: dict[str, Any], draft: object, approver: UUID | None = None
) -> tuple[str, tuple[object, ...]]:
    return CONFIRM, (case["prop"], approver or case["human"], UUID(str(draft)))


def applications(url: str, settlement: UUID) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(
            "SELECT id,customer_credit_id,target_kind,invoice_id,late_payment_charge_id,"
            "amount_usd_cents,within_invoice_basis,customer_designation_reference,"
            "proposal_trace IS NOT NULL,actor_id,authorization_reference "
            "FROM app.customer_credit_applications WHERE final_settlement_id=%s "
            "ORDER BY occurred_at,id",
            (settlement,),
        ).fetchall()


def details(url: str, application: UUID) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(
            "SELECT invoice_line_id,late_payment_charge_id,obligation_kind,"
            "proposed_amount_usd_cents,applied_amount_usd_cents,attribution_basis,detail_sequence,"
            "calculation_trace->>'draft_id',(calculation_trace->>'step_sequence')::integer "
            "FROM app.customer_credit_application_details WHERE customer_credit_application_id=%s "
            "ORDER BY detail_sequence",
            (application,),
        ).fetchall()


def derived(url: str, draft: object, step: int) -> UUID:
    return UUID(
        str(
            one(
                url,
                "SELECT app.final_settlement_credit_application_id(%s,%s)",
                UUID(str(draft)),
                step,
            )[0]
        )
    )


def invoice_of(url: str, line: UUID) -> UUID:
    return UUID(str(one(url, "SELECT invoice_id FROM app.invoice_lines WHERE id=%s", line)[0]))


def count(url: str, sql: str, *parameters: object) -> int:
    return int(one(url, sql, *parameters)[0])


def test_a_settlement_credit_application_pays_an_invoice_without_rent_or_service_lines(
    migrated_database_url: str,
) -> None:
    """BR-SETTLE-004, BR-SETTLE-009 and BR-CREDIT-006: the Settlement's Customer Credit step on a
    Damage Invoice (no Rent or Service line) is written as the existing other applicable
    obligation basis with OTHER_CONFIRMED details, linked to its Final Settlement and authorized by
    the Settlement's financial.approve confirmation (owner answers 1 and 2 to Q-2026-10-06-32)."""
    url = migrated_database_url
    case = leaving_case(url)
    draft = record(case, normal_plan(case), pet_remainder=STAFF)["draft_id"]
    other_invoice = invoice_of(url, case["other_line"])
    with psycopg.connect(url) as connection:
        decide(connection, case, draft)
        written = write(connection, case, draft, 1)
    identity = derived(url, draft, 1)
    assert UUID(written["id"]) == identity
    assert (written["within_invoice_basis"], written["amount_usd_cents"]) == (
        "OTHER_APPLICABLE_OBLIGATION",
        400,
    )
    assert applications(url, case["settlement"]) == [
        (
            identity,
            case["credit"],
            "INVOICE",
            other_invoice,
            None,
            400,
            "OTHER_APPLICABLE_OBLIGATION",
            None,
            False,
            case["human"],
            "financial.approve",
        )
    ]
    assert details(url, identity) == [
        (case["other_line"], None, "INVOICE_LINE", None, 400, "OTHER_CONFIRMED", 1, str(draft), 1)
    ]
    assert outstanding(url, case["other_line"]) == 12_100
    assert one(url, "SELECT app.credit_available_value(%s)", case["credit"]) == (0,)
    # The existing Credit audit records the Settlement's authorization; nothing else moved.
    assert one(
        url,
        "SELECT action,actor_id,authorization_reference FROM app.audit_events "
        "WHERE entity_type='customer_credit_application' AND entity_id=%s",
        identity,
    ) == ("credit.applied", case["human"], "financial.approve")
    assert (held(url, case["security"]), held(url, case["pet"])) == (10_000, 20_000)
    assert (
        count(
            url,
            "SELECT count(*) FROM app.deposit_applications WHERE final_settlement_id=%s",
            case["settlement"],
        )
        == 0
    )
    # A repeat of the step is refused (its Credit is used; the derived id is the last guard), and
    # the writer's own input refusals write nothing.
    assert refused(url, post(case, draft, 1)) == ("23514", SOURCE_INVALID)
    assert refused(url, post(case, draft, 2)) == ("22023", NOT_A_CREDIT_STEP)
    assert refused(url, post(case, draft, 9)) == ("22023", NOT_A_CREDIT_STEP)
    assert refused(url, post(case, draft, 0))[0] == "22023"
    assert refused(url, post(case, uuid4(), 1))[0] == "P0002"
    assert refused(url, (POST, (case["prop"], case["human"], uuid4(), UUID(str(draft)), 1))) == (
        "P0002",
        "Final Settlement was not found",
    )
    assert len(applications(url, case["settlement"])) == 1


def test_settlement_credit_on_a_mixed_rent_invoice_follows_the_proposal_or_the_designation(
    migrated_database_url: str,
) -> None:
    """BR-CREDIT-006 (owner answer 1 to Q-2026-10-05-29): on an Invoice with Rent or Service lines
    the writer records the Rent-first proposal with its trace, which the existing Credit check
    re-runs, or the Customer's designation recorded as text; a step that is not the first line of
    the proposal is refused unless the Customer designated it."""
    url = migrated_database_url
    case = mixed_rent_case(url)
    (rent, _), (trash, _), (internet, _) = case["lines"]
    owed = {line: outstanding(url, line) for line, _ in case["lines"]}

    def credit(line: UUID, designation: str | None = None) -> SettlementCreditStep:
        return SettlementCreditStep(case["credit"], LINE, line, owed[line], designation)

    designation = "Primary Tenant asked on 2026-10-06, by signed note, to clear Internet first"
    designated = record(case, (credit(internet, designation), credit(rent), credit(trash)))
    # The designated step, then the proposal for Rent and for the first Service line; checked at
    # once and rolled back.
    with psycopg.connect(url) as connection:
        decide(connection, case, designated["draft_id"])
        steps = [write(connection, case, designated["draft_id"], 1)]
        # Review round 1: a repeat while the Credit and the Invoice still allow it meets the id
        # derived from the draft and the step (each step is written at most once).
        with pytest.raises(psycopg.errors.UniqueViolation) as repeat, connection.transaction():
            write(connection, case, designated["draft_id"], 1)
        assert repeat.value.diag.constraint_name == "customer_credit_applications_pkey"
        steps += [write(connection, case, designated["draft_id"], step) for step in (2, 3)]
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        rows = connection.execute(
            "SELECT application.within_invoice_basis,application.customer_designation_reference,"
            "detail.invoice_line_id,detail.attribution_basis,detail.proposed_amount_usd_cents "
            "FROM app.customer_credit_applications application "
            "JOIN app.customer_credit_application_details detail "
            "ON detail.customer_credit_application_id=application.id "
            "WHERE application.final_settlement_id=%s ORDER BY application.occurred_at",
            (case["settlement"],),
        ).fetchall()
        connection.rollback()
    assert [step["within_invoice_basis"] for step in steps] == [
        "CUSTOMER_DESIGNATED",
        "RENT_THEN_RECURRING_SERVICES_PROPOSAL",
        "RENT_THEN_RECURRING_SERVICES_PROPOSAL",
    ]
    assert rows == [
        ("CUSTOMER_DESIGNATED", designation, internet, "CUSTOMER_DESIGNATED", None),
        ("RENT_THEN_RECURRING_SERVICES_PROPOSAL", None, rent, "RENT_FIRST_PROPOSAL", owed[rent]),
        ("RENT_THEN_RECURRING_SERVICES_PROPOSAL", None, trash, "SERVICE_PROPOSAL", owed[trash]),
    ]
    assert applications(url, case["settlement"]) == []
    # Review round 1: rows written as the owner, bypassing the writer, meet the database checks.
    # The designated step's header with credits.apply is refused when written (BR-AUTH-010); with
    # financial.approve but its detail on the Rent line instead of the step's Internet line, it is
    # refused at commit.
    header = (
        "INSERT INTO app.customer_credit_applications(id,customer_credit_id,target_kind,invoice_id,"
        "final_settlement_id,amount_usd_cents,within_invoice_basis,customer_designation_reference,"
        "occurred_at,actor_id,authorization_reference) VALUES (app.final_settlement_credit_"
        "application_id(%s,1),%s,'INVOICE',%s,%s,%s,'CUSTOMER_DESIGNATED',%s,"
        "COALESCE(%s::timestamptz,clock_timestamp()),%s,%s)"
    )

    def owner_header(
        authorization: str,
        *,
        draft: object = designated["draft_id"],
        amount: int = owed[internet],
        text: str = designation,
        at: object = None,
    ) -> tuple[str, tuple[object, ...]]:
        return header, (
            UUID(str(draft)),
            case["credit"],
            case["invoice"],
            case["settlement"],
            amount,
            text,
            at,
            case["human"],
            authorization,
        )

    assert refused(url, confirm(case, designated["draft_id"]), owner_header("credits.apply")) == (
        "42501",
        "A Final Settlement Credit application needs a human approver under financial.approve",
    )
    detail = (
        "INSERT INTO app.customer_credit_application_details(id,customer_credit_application_id,"
        "invoice_line_id,obligation_kind,invoice_line_category_snapshot,applied_amount_usd_cents,"
        "attribution_basis,detail_sequence,calculation_trace) VALUES (gen_random_uuid(),"
        "app.final_settlement_credit_application_id(%s,1),%s,'INVOICE_LINE','RENT',%s,"
        "'CUSTOMER_DESIGNATED',1,'{}'::jsonb)"
    )
    assert refused(
        url,
        confirm(case, designated["draft_id"]),
        owner_header("financial.approve"),
        (detail, (UUID(str(designated["draft_id"])), rent, owed[internet])),
    ) == ("23514", WRONG_OBLIGATION)
    # Review round 2: a header backdated before the Settlement started is refused when written.
    started = one(
        url, "SELECT started_at FROM app.final_settlements WHERE id=%s", case["settlement"]
    )[0]
    assert refused(
        url,
        confirm(case, designated["draft_id"]),
        owner_header("financial.approve", at=started - timedelta(microseconds=1)),
    ) == ("23514", "A Final Settlement Credit application cannot precede its Final Settlement")
    assert applications(url, case["settlement"]) == []
    withdraw(case, designated)
    proposed = record(case, (credit(rent), credit(trash), credit(internet)))["draft_id"]
    # Review round 2: a header that records a designation on a step without one does not match
    # the step and is refused when written.
    assert refused(
        url,
        confirm(case, proposed),
        owner_header("financial.approve", draft=proposed, amount=owed[rent]),
    ) == ("23514", NOT_IN_DRAFT)
    # Out of the draft's order the proposal pays Rent first, so the Service step is refused.
    assert refused(url, confirm(case, proposed), post(case, proposed, 2)) == ("23514", RENT_FIRST)
    with psycopg.connect(url) as connection:
        decide(connection, case, proposed)
        for step in (1, 2, 3):
            write(connection, case, proposed, step)
    found = applications(url, case["settlement"])
    assert [(row[6], row[8], row[10]) for row in found] == [
        ("RENT_THEN_RECURRING_SERVICES_PROPOSAL", True, "financial.approve")
    ] * 3
    assert [details(url, row[0])[0][:6] for row in found] == [
        (rent, None, "INVOICE_LINE", owed[rent], owed[rent], "RENT_FIRST_PROPOSAL"),
        (trash, None, "INVOICE_LINE", owed[trash], owed[trash], "SERVICE_PROPOSAL"),
        (internet, None, "INVOICE_LINE", owed[internet], owed[internet], "SERVICE_PROPOSAL"),
    ]
    assert all(outstanding(url, line) == 0 for line in owed)
    assert one(url, "SELECT status FROM app.invoices WHERE id=%s", case["invoice"]) == ("PAID",)
    # Each stored trace is the existing proposal of its own moment (one detail, the step's line).
    with psycopg.connect(url) as connection:
        traces = connection.execute(
            "SELECT proposal_trace->'details'->0->>'invoice_line_id',"
            "jsonb_array_length(proposal_trace->'details'),proposal_generated_at=occurred_at "
            "FROM app.customer_credit_applications WHERE final_settlement_id=%s "
            "ORDER BY occurred_at",
            (case["settlement"],),
        ).fetchall()
    assert traces == [(str(rent), 1, True), (str(trash), 1, True), (str(internet), 1, True)]


def test_a_settlement_credit_application_pays_its_own_customers_late_payment_charge(
    migrated_database_url: str,
) -> None:
    """BR-CREDIT-008 (owner answer to Q-2026-10-05-29): each Customer's Credit pays only that
    Customer's debt: the Signer's Credit pays the Signer's Invoice, the Primary Tenant's Credit a
    Late-payment Charge directly. A draft step that names another Customer's obligation, or an
    obligation outside the Settlement Lease, is refused by the database even when the plan check
    is bypassed."""
    url = migrated_database_url
    case = two_signer_case(url, overdue_rent=True)
    prop, human, tenant = case["prop"], case["human"], case["tenant"]
    # The Primary Tenant pays the key card and a credit Adjustment releases 400 of their Credit.
    key_card_invoice = invoice_of(url, case["tenant_line"])
    pay(url, prop, human, tenant, key_card_invoice, case["tenant_line"], 1_500)
    credit_adjustment(url, human, prop, key_card_invoice, case["tenant_line"])
    tenant_credit = UUID(
        str(one(url, "SELECT id FROM app.customer_credits WHERE customer_id=%s", tenant)[0])
    )
    assert preview(prop, human, case["settlement"])["ready"] is True
    # A no-Lease charge of the Primary Tenant, outside the Settlement.
    staff = invoice_api_actor(human, prop)
    outside = no_lease_charge(tenant)
    invoices().record_one_time_charge(prop, outside, actor=staff)
    outside_line = line_of(url, draft_and_issue(prop, outside.charge_id, staff)["id"])

    def forged(
        credit: UUID, kind: str, target: UUID
    ) -> tuple[UUID, tuple[str, tuple[object, ...]]]:
        """A FINAL_SETTLEMENT draft the plan check would refuse, inserted as the owner."""
        draft = uuid4()
        step = {
            "kind": "CUSTOMER_CREDIT",
            "customer_credit_id": str(credit),
            "target_kind": kind,
            "target_id": str(target),
            "amount_usd_cents": 400,
            "customer_designation": None,
        }
        payload = {
            "variant": "FINAL_SETTLEMENT",
            "final_settlement_id": str(case["settlement"]),
            "steps": [step],
            "pet_remainder": None,
        }
        return draft, (
            "SELECT app.insert_financial_draft(%s,%s,%s,'FINAL_SETTLEMENT',"
            "'final_settlements.prepare',%s,'forged','Forged by the test')",
            (prop, human, draft, Jsonb(payload)),
        )

    # The Signer's Credit on the Primary Tenant's open Late-payment Charge: only the Customer
    # differs.
    signer_on_tenant, insert = forged(case["credit"], "LATE_PAYMENT_CHARGE", case["charge"])
    assert refused(
        url, insert, confirm(case, signer_on_tenant), post(case, signer_on_tenant, 1)
    ) == ("23514", SOURCE_INVALID)
    tenant_outside, insert = forged(tenant_credit, "INVOICE_LINE", outside_line)
    assert refused(url, insert, confirm(case, tenant_outside), post(case, tenant_outside, 1)) == (
        "23514",
        OTHER_LEASE,
    )
    plan = (
        SettlementCreditStep(case["credit"], LINE, case["signer_line"], 400),
        SettlementCreditStep(
            tenant_credit, SettlementTargetKind.LATE_PAYMENT_CHARGE, case["charge"], 400
        ),
        SettlementDepositStep(
            PET_REST, case["pet"], SettlementTargetKind.LATE_PAYMENT_CHARGE, case["charge"], 7_600
        ),
        SettlementDepositStep(PET_REST, case["pet"], LINE, case["signer_line"], 600),
        SettlementDepositStep(PET_REST, case["pet"], LINE, case["rent_line"], 11_800),
    )
    draft = record(case, plan, pet_remainder=STAFF)["draft_id"]
    with psycopg.connect(url) as connection:
        decide(connection, case, draft)
        write(connection, case, draft, 1)
        write(connection, case, draft, 2)
    signer_row, tenant_row = applications(url, case["settlement"])
    assert signer_row[1:7] == (
        case["credit"],
        "INVOICE",
        invoice_of(url, case["signer_line"]),
        None,
        400,
        "OTHER_APPLICABLE_OBLIGATION",
    )
    assert tenant_row[1:9] == (
        tenant_credit,
        "LATE_PAYMENT_CHARGE",
        None,
        case["charge"],
        400,
        "NOT_APPLICABLE",
        None,
        False,
    )
    assert details(url, tenant_row[0]) == [
        (
            None,
            case["charge"],
            "LATE_PAYMENT_CHARGE",
            None,
            400,
            "DIRECT_LATE_PAYMENT_CHARGE",
            1,
            str(draft),
            2,
        )
    ]
    assert charge_remaining(url, case["charge"]) == 7_600
    assert outstanding(url, case["signer_line"]) == 600
    # Only the forged drafts' refusals ran; they left no Credit application.
    assert len(applications(url, case["settlement"])) == 2


def test_a_settlement_credit_application_commits_only_with_its_draft_confirmed_by_the_approver(
    migrated_database_url: str,
) -> None:
    """BR-AUTH-010 (as the Settlement Refunds, sub-slice 8d): the row is written only while its
    draft waits or is confirmed by the same approver and commits only with that confirmation, in
    the same transaction or before it. In the confirm's order (decision, Credit steps, Deposit
    applications, Refunds, in one transaction) the Settlement writers compose, also after an
    earlier SET CONSTRAINTS ALL IMMEDIATE; Customer Credit comes first (DL-032 step 2)."""
    url = migrated_database_url
    case = leaving_case(url)
    prop, human, settlement = case["prop"], case["human"], case["settlement"]
    with psycopg.connect(url) as connection:
        other = setup_signed_lease(connection)[0]
    first = record(case, normal_plan(case), pet_remainder=STAFF)
    # Pending at commit, or confirmed by another approver in the same transaction: refused at
    # commit.
    assert refused(url, post(case, first["draft_id"], 1)) == ("42501", NOT_CONFIRMED)
    assert refused(
        url, post(case, first["draft_id"], 1), confirm(case, first["draft_id"], other)
    ) == ("42501", NOT_CONFIRMED)
    # Confirmed by another approver before: refused when written.
    assert refused(
        url, confirm(case, first["draft_id"], other), post(case, first["draft_id"], 1)
    ) == ("23514", NOT_IN_DRAFT)
    # A withdrawn draft is no longer a source.
    withdraw(case, first)
    assert refused(url, post(case, first["draft_id"], 1)) == ("23514", NOT_IN_DRAFT)
    assert applications(url, settlement) == []
    draft = UUID(str(record(case, normal_plan(case), pet_remainder=STAFF)["draft_id"]))
    with psycopg.connect(url) as connection:
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        decide(connection, case, draft)
        write(connection, case, draft, 1)
        for order, (deposit, stage, line, amount) in enumerate(
            (
                (case["pet"], "PET_RELATED_FIRST", case["pet_line"], 12_500),
                (case["security"], "SECURITY_EXPLICIT", case["other_line"], 10_000),
                (case["pet"], "PET_REMAINDER_EXPLICIT", case["other_line"], 2_100),
            ),
            start=1,
        ):
            connection.execute(
                DEPOSIT_APPLICATION,
                (
                    prop,
                    human,
                    settlement,
                    uuid4(),
                    deposit,
                    stage,
                    "INVOICE_LINE",
                    line,
                    amount,
                    order,
                    REASON,
                ),
            )
        # DL-032 step 2: no Settlement Credit application once a Deposit paid.
        with pytest.raises(psycopg.Error) as late, connection.transaction():
            write(connection, case, draft, 1)
        assert (late.value.sqlstate, late.value.diag.message_primary) == ("55000", CREDIT_FIRST)
        connection.execute(
            REFUND,
            (
                prop,
                human,
                settlement,
                draft,
                uuid4(),
                case["pet"],
                5_400,
                case["customer"],
                case["cash"],
                "Cash handed over at the front desk",
                None,
                REASON,
            ),
        )
    assert len(applications(url, settlement)) == 1
    assert (
        count(
            url,
            "SELECT count(*) FROM app.deposit_applications WHERE final_settlement_id=%s",
            settlement,
        )
        == 3
    )
    assert (
        count(
            url,
            "SELECT count(*) FROM app.final_settlement_refund_details WHERE final_settlement_id=%s",
            settlement,
        )
        == 1
    )
    assert (held(url, case["security"]), held(url, case["pet"])) == (0, 0)
    assert (outstanding(url, case["pet_line"]), outstanding(url, case["other_line"])) == (0, 0)
    assert one(
        url,
        "SELECT decision,decided_by FROM app.financial_draft_decisions WHERE draft_id=%s",
        draft,
    ) == ("CONFIRMED", human)


def test_a_settlement_credit_application_is_never_reversed_with_one_call(
    migrated_database_url: str,
) -> None:
    """Owner answer 3 to Q-2026-10-06-32 (BR-SETTLE-012, BR-SETTLE-013): after closure the one-call
    reversal of a Credit application the Settlement made is refused as a conflict, and the credit
    Adjustment excess path cannot reverse it either; a closed Settlement takes no new one.
    Ordinary Credit applications and their one-call reversals stay open (owner answer 7 to
    Q-2026-10-05-20, sub-slice 8e-1)."""
    url = migrated_database_url
    case = leaving_case(url)
    prop, human, customer = case["prop"], case["human"], case["customer"]
    draft = record(case, normal_plan(case), pet_remainder=STAFF)["draft_id"]
    with psycopg.connect(url) as connection:
        decide(connection, case, draft)
        written = write(connection, case, draft, 1)
    close(url, human, case["settlement"])
    settlement_application = UUID(written["id"])
    assert refused(url, post(case, draft, 1)) == (
        "55000",
        "A closed Final Settlement takes no new Credit application",
    )
    with pytest.raises(CreditConflictError) as failure:
        credits().reverse_application(
            prop,
            settlement_application,
            ReverseCreditApplicationCommand(uuid4(), "Customer changed the instruction"),
            actor=credit_actor(human, prop, "credits.applications.reverse"),
        )
    cause = failure.value.__cause__
    assert isinstance(cause, psycopg.Error)
    assert (cause.sqlstate, cause.diag.message_primary) == ("P5S01", REVERSAL_REFUSED)
    # A credit Adjustment beyond the unpaid amount would reverse it to release Credit: refused.
    other_invoice = invoice_of(url, case["other_line"])
    version = int(one(url, "SELECT version FROM app.invoices WHERE id=%s", other_invoice)[0])
    with pytest.raises(InvoiceConflictError) as adjustment:
        invoices().adjust(
            prop,
            other_invoice,
            AdjustInvoiceCommand(
                uuid4(),
                case["other_line"],
                AdjustmentType.CREDIT,
                12_200,
                f"approved-credit/{uuid4()}",
                "Approved credit",
                version,
            ),
            actor=invoice_api_actor(human, prop),
        )
    # The 8e-2 refusal itself (the 8e-1 guard on the Adjustment row would also give P5S01).
    adjustment_cause = adjustment.value.__cause__
    assert isinstance(adjustment_cause, psycopg.Error)
    assert (adjustment_cause.sqlstate, adjustment_cause.diag.message_primary) == (
        "P5S01",
        REVERSAL_REFUSED,
    )
    assert (
        count(
            url,
            "SELECT count(*) FROM app.customer_credit_application_reversals WHERE "
            "credit_application_id=%s",
            settlement_application,
        )
        == 0
    )
    assert (
        count(
            url, "SELECT count(*) FROM app.invoice_adjustments WHERE invoice_id=%s", other_invoice
        )
        == 0
    )
    assert outstanding(url, case["other_line"]) == 12_100
    # An ordinary Credit (released from a no-Lease charge after closure) is applied to the
    # Settlement's open debt and reversed with one call.
    staff = invoice_api_actor(human, prop)
    charge = no_lease_charge(customer)
    invoices().record_one_time_charge(prop, charge, actor=staff)
    outside_invoice = UUID(str(draft_and_issue(prop, charge.charge_id, staff)["id"]))
    outside_line = line_of(url, outside_invoice)
    pay(url, prop, human, customer, outside_invoice, outside_line, 700)
    credit_adjustment(url, human, prop, outside_invoice, outside_line)
    ordinary_credit = UUID(
        str(
            one(
                url,
                "SELECT id FROM app.customer_credits WHERE customer_id=%s AND id<>%s",
                customer,
                case["credit"],
            )[0]
        )
    )
    applied = credits().apply(
        prop,
        ordinary_credit,
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
    assert outstanding(url, case["other_line"]) == 11_700
    ordinary = cast(dict[str, Any], applied["application"])
    assert (ordinary["final_settlement_id"], ordinary["authorization_reference"]) == (
        None,
        "credits.apply",
    )
    credits().reverse_application(
        prop,
        UUID(str(ordinary["id"])),
        ReverseCreditApplicationCommand(uuid4(), "Customer changed the instruction"),
        actor=credit_actor(human, prop, "credits.applications.reverse"),
    )
    assert outstanding(url, case["other_line"]) == 12_100
    assert applications(url, case["settlement"])[0][0] == settlement_application


def test_no_role_can_write_a_settlement_credit_application(migrated_database_url: str) -> None:
    """Owner answer 1 to Q-2026-10-06-32: the writer and its checks are internal, like the 8d
    Refund writer: no role holds EXECUTE and a call as the financial or runtime role is refused.
    The relaxed CHECK lets financial.approve stand only on a row linked to a Settlement; the
    reversal refusal runs before the existing reversal checks and their locks."""
    url = migrated_database_url
    with psycopg.connect(url) as owner:
        for signature in INTERNAL:
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
            # No grantee but the owner: PUBLIC (grantee 0) would show as "-".
            assert grantees == [], (signature, grantees)
            for role in ("public", "prm_runtime", "prm_financial", "prm_bootstrap"):
                assert owner.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)
                ).fetchone() == (False,), (role, signature)
        definitions: dict[str, str] = dict(
            owner.execute(
                "SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid='app.customer_credit_applications'::regclass "
                "AND conname IN ('customer_credit_applications_authorization_reference_check',"
                "'customer_credit_applications_final_settlement_fk')"
            ).fetchall()
        )
        reversal_triggers = owner.execute(
            "SELECT tgname,tgfoid::regprocedure::text FROM pg_trigger "
            "WHERE tgrelid='app.customer_credit_application_reversals'::regclass "
            "AND NOT tgisinternal AND (tgtype & 2)=2 AND (tgtype & 4)=4 ORDER BY tgname"
        ).fetchall()
    assert definitions == {
        "customer_credit_applications_authorization_reference_check": (
            "CHECK ((((final_settlement_id IS NULL) AND (authorization_reference = "
            "'credits.apply'::text)) OR ((final_settlement_id IS NOT NULL) AND "
            "(authorization_reference = 'financial.approve'::text))))"
        ),
        "customer_credit_applications_final_settlement_fk": (
            "FOREIGN KEY (final_settlement_id) REFERENCES app.final_settlements(id) "
            "ON DELETE RESTRICT"
        ),
    }
    assert reversal_triggers[0] == (
        "a0_customer_credit_application_reversals_final_settlement",
        "app.refuse_final_settlement_credit_application_reversal()",
    )
    arguments = (uuid4(), uuid4(), uuid4(), uuid4(), 1)
    for role_url in (financial_database_url(), runtime_database_url()):
        with (
            pytest.raises(psycopg.errors.InsufficientPrivilege),
            psycopg.connect(role_url) as connection,
        ):
            connection.execute(POST, arguments)


def test_final_settlement_credit_application_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261028_93")
    assert revision is not None and revision.down_revision == "20261027_92"
    module = revision.module
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
