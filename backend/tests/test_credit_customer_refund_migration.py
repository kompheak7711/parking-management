"""Credit Refund to the Invoice Customer who is not the payer (V1-056 sub-slice 8f).

BR-CREDIT-014: a Customer Credit that a credit Adjustment released belongs to the Customer named
on the Invoice, also when another person paid (a third-party Payment, or a wrong-Unit move to
another Customer), and any Refund of it goes to that Customer. The Refund is a CREDIT_CUSTOMER
Refund draft prepared under refunds.create and confirmed by a financial.approve holder
(BR-AUTH-010; owner answer to Q-2026-10-05-19).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from property_rental.customer_ledger import LedgerPosition
from property_rental.identity import AuthenticatedActor
from property_rental.refund import (
    CreateCreditCustomerRefundCommand,
    CreateUsdRefundCommand,
    RefundAuthorizationError,
    RefundConflictError,
    RefundIdempotencyKeyReused,
    RefundInvalidError,
    RefundNotFoundError,
    RefundService,
    refund_draft_id,
)
from refund_test_support import CASH_REFERENCE_NOTE, cash, create_usd_refund
from test_credit_adjustment_excess_migration import credit as credit_adjustment
from test_credit_migration import credit_id, recognize
from test_credit_migration import source as credit_source
from test_customer_ledger_migration import assert_reconciled
from test_invoice_migration import financial_database_url, runtime_database_url
from test_migrations import _temporary_migration_database
from test_payment_move_migration import (
    WrongAllocation,
    draft_id,
    drafts,
    move,
    moves,
    person,
    released_credit,
    rows,
    value,
    wrong_allocation,
)
from test_payment_move_migration import approver as move_approver
from test_payment_move_migration import preparer as move_preparer
from test_refund_service_migration import refund_id, returned
from test_reservation_migration import migrated_database_url  # noqa: F401

RECORD = "app.record_credit_customer_refund_draft(uuid,uuid,uuid,uuid,bigint,text,uuid,text,text)"
CONFIRM = "app.confirm_refund_draft(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.credit_customer_refund_basis(uuid)",
    "app.credit_customer_refund_id(uuid)",
    "app.credit_customer_refund_draft(app.refunds)",
    "app.credit_customer_refund_allowed(app.refunds)",
    "app.assert_credit_customer_refund_confirmed()",
    "app.post_credit_customer_refund(uuid,uuid,uuid)",
)
REASON = "Return the Customer Credit"
NOT_COVERED = "P5206"


def service() -> RefundService:
    return RefundService(runtime_database_url(), financial_database_url())


def staff(case: WrongAllocation) -> AuthenticatedActor:
    return person(case.human, case.prop, "refunds.create", "refunds.read")


def approving(case: WrongAllocation) -> AuthenticatedActor:
    """Another person, holding financial.approve only."""
    return person(case.approver, case.prop, "financial.approve")


def command(credit: UUID, amount: int) -> CreateCreditCustomerRefundCommand:
    return CreateCreditCustomerRefundCommand(uuid4(), credit, amount, REASON)


def third_party_credit(url: str) -> tuple[WrongAllocation, UUID, UUID]:
    """A third-party Payment pays the Unit 203 Invoice in full; a credit Adjustment of 5,000 then
    releases 5,000 as Customer Credit of the Invoice Customer, who is not the payer."""
    case = wrong_allocation(url, scope="THIRD_PARTY_IDENTIFIED")
    credit_adjustment(url, case.human, case.prop, case.invoice_wrong, case.line_wrong, 5_000)
    credit = UUID(
        str(
            value(
                url,
                "SELECT credit.id FROM app.customer_credits credit "
                "JOIN app.invoice_credit_excess_releases release "
                "ON release.customer_credit_id=credit.id WHERE credit.source_payment_id=%s",
                case.payment,
            )
        )
    )
    payer = UUID(
        str(value(url, "SELECT payer_customer_id FROM app.payments WHERE id=%s", case.payment))
    )
    return case, credit, payer


def moved_credit(url: str) -> tuple[WrongAllocation, UUID]:
    """BR-PAY-042: the Unit 203 Customer's Payment is moved to the Unit 201 Invoice; a credit
    Adjustment of 5,000 there releases 5,000 as Credit of the Unit 201 Customer (not the payer)."""
    case = wrong_allocation(url)
    moves().confirm(
        case.prop,
        draft_id(moves().record(case.prop, move(case), actor=move_preparer(case))),
        actor=move_approver(case),
    )
    credit_adjustment(url, case.human, case.prop, case.invoice_right, case.line_right, 5_000)
    return case, released_credit(url, case.payment)


def available(url: str, credit: UUID) -> int:
    return int(str(value(url, "SELECT app.credit_available_value(%s)", credit)))


def refunds_of(url: str, credit: UUID) -> list[tuple[Any, ...]]:
    return rows(
        url,
        "SELECT id,recipient_customer_id,usd_accounting_value_cents FROM app.refunds "
        "WHERE source_customer_credit_id=%s ORDER BY processed_at,id",
        credit,
    )


def ledger(url: str, customer: UUID) -> LedgerPosition:
    """The Customer Ledger position, reconciled to its sources."""
    with psycopg.connect(url) as connection:
        return assert_reconciled(connection, customer)


def ledger_rows(url: str, refund: UUID) -> list[tuple[Any, ...]]:
    return rows(
        url,
        "SELECT event_kind,customer_id,balance_kind,effect_usd_cents "
        "FROM app.customer_ledger_effects WHERE refund_id=%s ORDER BY event_kind",
        refund,
    )


def state(url: str, draft: UUID) -> str | None:
    """The draft's decision, or None while it is pending."""
    found = rows(url, "SELECT decision FROM app.financial_draft_decisions WHERE draft_id=%s", draft)
    return None if not found else str(found[0][0])


def test_a_third_party_paid_credit_is_refunded_to_the_invoice_customer_after_approval(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """BR-CREDIT-014 and BR-AUTH-010: the Credit of the Invoice Customer, released from a
    third-party Payment, is refunded to that Customer only after a financial.approve holder
    confirms the draft; every amount is exact to the cent, the payer's ledger does not change, and
    a verified return restores the Credit."""
    url = migrated_database_url
    case, credit, payer = third_party_credit(url)
    customer = case.customer_wrong
    assert (
        value(url, "SELECT customer_id FROM app.customer_credits WHERE id=%s", credit) == customer
    )
    assert customer != payer and available(url, credit) == 5_000
    payer_before = ledger(url, payer)
    choice = cash(service(), case.prop, staff(case))
    request = command(credit, 3_000)
    draft = service().record_credit_customer_draft(case.prop, request, choice, actor=staff(case))
    identity = UUID(str(draft["draft_id"]))
    assert identity == refund_draft_id(
        case.prop, case.human, "CREDIT_CUSTOMER", request.idempotency_key
    )
    assert (draft["kind"], draft["prepare_capability"], draft["state"]) == (
        "REFUND",
        "refunds.create",
        "PENDING",
    )
    assert draft["payload"] == {
        "variant": "CREDIT_CUSTOMER",
        "source_kind": "CREDIT",
        "source_id": str(credit),
        "recipient_customer_id": str(customer),
        "amount_usd_cents": 3_000,
        "reason": REASON,
        "refund_method_id": str(choice.refund_method_id),
        "reference_note": CASH_REFERENCE_NOTE,
    }
    # A draft has no financial effect; an exact repeat returns the same draft.
    assert refunds_of(url, credit) == [] and available(url, credit) == 5_000
    assert (
        service().record_credit_customer_draft(case.prop, request, choice, actor=staff(case))
        == draft
    )
    # Staff cannot confirm, in the service and in the database.
    with pytest.raises(RefundAuthorizationError):
        service().confirm_draft(case.prop, identity, actor=staff(case))
    with pytest.raises(psycopg.Error) as refused, psycopg.connect(financial_database_url()) as c:
        c.execute(
            "SELECT app.confirm_refund_draft(%s,%s,%s,%s)",
            (case.prop, case.human, identity, "refunds.create"),
        )
    assert refused.value.sqlstate == "42501"
    assert refunds_of(url, credit) == [] and state(url, identity) is None

    confirmed = service().confirm_draft(case.prop, identity, actor=approving(case))
    refund = refund_id(cast(dict[str, object], confirmed["refund"]))
    header = cast(dict[str, object], cast(dict[str, object], confirmed["refund"])["refund"])
    assert header["recipient_customer_id"] == str(customer)
    assert cast(dict[str, object], confirmed["draft"])["state"] == "CONFIRMED"
    assert rows(
        url,
        "SELECT recipient_customer_id,source_customer_credit_id,source_payment_id,"
        "source_deposit_id,usd_accounting_value_cents,refund_currency,refund_amount_minor,"
        "reason,processed_by,authorization_reference,app.credit_customer_refund_id(%s)=id "
        "FROM app.refunds WHERE id=%s",
        identity,
        refund,
    ) == [
        (
            customer,
            credit,
            None,
            None,
            3_000,
            "USD",
            3_000,
            REASON,
            case.approver,
            "refunds.create",
            True,
        )
    ]
    assert rows(
        url,
        "SELECT draft_id,refund_method_id,reference_note FROM app.refund_draft_details "
        "WHERE refund_id=%s",
        refund,
    ) == [(identity, choice.refund_method_id, CASH_REFERENCE_NOTE)]
    assert rows(
        url,
        "SELECT decision,decided_by,authorization_reference FROM app.financial_draft_decisions "
        "WHERE draft_id=%s",
        identity,
    ) == [("CONFIRMED", case.approver, "financial.approve")]
    assert rows(
        url,
        "SELECT actor_id,customer_id,authorization_reference FROM app.audit_events "
        "WHERE entity_id=%s AND action='refund.created'",
        refund,
    ) == [(case.approver, customer, "refunds.create")]
    assert available(url, credit) == 2_000
    # The Credit's Customer's ledger books the Refund on the Credit; the payer's does not change.
    assert ledger_rows(url, refund) == [("REFUND_PAID", customer, "CREDIT", -3_000)]
    assert ledger(url, customer).credit == 2_000
    assert ledger(url, payer) == payer_before
    # An exact repeat by the approver replays; another approver finds the draft decided.
    assert service().confirm_draft(case.prop, identity, actor=approving(case)) == confirmed
    with pytest.raises(RefundConflictError):
        service().confirm_draft(
            case.prop, identity, actor=person(case.human, case.prop, "financial.approve")
        )
    assert [row[0] for row in refunds_of(url, credit)] == [refund]
    # BR-REFUND-011: a verified return of part of the Refund restores that Credit value.
    corrected = service().verify_usd_return(
        case.prop, refund, returned(1_000), actor=person(case.human, case.prop, "refunds.correct")
    )
    assert corrected["net_refund_usd_cents"] == 2_000
    assert available(url, credit) == 3_000
    assert ledger_rows(url, refund) == [
        ("REFUND_CORRECTED", customer, "CREDIT", 1_000),
        ("REFUND_PAID", customer, "CREDIT", -3_000),
    ]
    assert ledger(url, customer).credit == 3_000
    assert ledger(url, payer) == payer_before


def test_a_credit_from_a_moved_allocation_is_refunded_to_its_customer_not_the_payer(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """Q-2026-10-05-19 and BR-PAY-042: the Credit released from a moved allocation belongs to the
    Unit 201 Customer. The ordinary Credit Refund draft pays only the payer, so it is refused at
    confirmation as a conflict and stays pending (the 23514 refusal, sub-slice 8f); the
    CREDIT_CUSTOMER draft pays the whole Credit to the Unit 201 Customer."""
    url = migrated_database_url
    case, credit = moved_credit(url)
    assert value(url, "SELECT customer_id FROM app.customer_credits WHERE id=%s", credit) == (
        case.customer_right
    )
    assert value(url, "SELECT payer_customer_id FROM app.payments WHERE id=%s", case.payment) == (
        case.customer_wrong
    )
    payer_before = ledger(url, case.customer_wrong)
    choice = cash(service(), case.prop, staff(case))
    ordinary = service().record_usd_draft(
        case.prop,
        CreateUsdRefundCommand(uuid4(), "CREDIT", credit, 5_000, REASON),
        choice,
        actor=staff(case),
    )
    ordinary_id = UUID(str(ordinary["draft_id"]))
    with pytest.raises(RefundConflictError) as conflict:
        service().confirm_draft(case.prop, ordinary_id, actor=approving(case))
    cause = conflict.value.__cause__
    assert isinstance(cause, psycopg.Error) and cause.sqlstate == "23514"
    assert state(url, ordinary_id) is None and refunds_of(url, credit) == []

    draft = service().record_credit_customer_draft(
        case.prop, command(credit, 5_000), choice, actor=staff(case)
    )
    confirmed = service().confirm_draft(
        case.prop, UUID(str(draft["draft_id"])), actor=approving(case)
    )
    refund = refund_id(cast(dict[str, object], confirmed["refund"]))
    assert refunds_of(url, credit) == [(refund, case.customer_right, 5_000)]
    assert available(url, credit) == 0
    assert ledger_rows(url, refund) == [("REFUND_PAID", case.customer_right, "CREDIT", -5_000)]
    assert ledger(url, case.customer_right).credit == 0
    assert ledger(url, case.customer_wrong) == payer_before
    # The ordinary draft is now stale (no Credit left): refused, still pending; the preparer
    # withdraws it.
    with pytest.raises(RefundInvalidError):
        service().confirm_draft(case.prop, ordinary_id, actor=approving(case))
    assert state(url, ordinary_id) is None
    drafts().withdraw(
        case.prop,
        ordinary_id,
        "Recorded with the wrong recipient",
        prepare_capability="refunds.create",
        actor=staff(case),
    )
    assert state(url, ordinary_id) == "WITHDRAWN"
    assert refunds_of(url, credit) == [(refund, case.customer_right, 5_000)]


def test_the_credit_customer_draft_covers_only_credits_released_to_another_customer(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """The variant refuses, as a conflict and recording nothing, the payer's own recognized
    Credit and an adjustment Credit of a Customer who is the payer (the ordinary Credit Refund
    draft still pays that payer); an unknown Credit is not found; recording needs refunds.create."""
    url = migrated_database_url
    human, prop, _, payment = credit_source(url, 2_000)
    own = credit_id(recognize(prop, payment, human, 1_000))
    preparer = person(human, prop, "refunds.create", "refunds.read")
    choice = cash(service(), prop, preparer)
    for credit in (own, uuid4()):
        request = command(credit, 500)
        expected = RefundConflictError if credit == own else RefundNotFoundError
        with pytest.raises(expected) as refused:
            service().record_credit_customer_draft(prop, request, choice, actor=preparer)
        if credit == own:
            cause = refused.value.__cause__
            assert isinstance(cause, psycopg.Error) and cause.sqlstate == NOT_COVERED
        assert (
            value(
                url,
                "SELECT count(*) FROM app.financial_drafts WHERE id=%s",
                refund_draft_id(prop, human, "CREDIT_CUSTOMER", request.idempotency_key),
            )
            == 0
        )
    # An adjustment Credit whose Customer is the payer: the variant refuses it, the ordinary
    # Credit Refund draft pays it to that Customer as before.
    case = wrong_allocation(url)
    credit_adjustment(url, case.human, case.prop, case.invoice_wrong, case.line_wrong, 5_000)
    payer_credit = UUID(
        str(
            value(
                url,
                "SELECT release.customer_credit_id FROM app.invoice_credit_excess_releases release "
                "JOIN app.customer_credits credit ON credit.id=release.customer_credit_id "
                "WHERE credit.source_payment_id=%s",
                case.payment,
            )
        )
    )
    with pytest.raises(RefundConflictError) as refused:
        service().record_credit_customer_draft(
            case.prop, command(payer_credit, 5_000), choice, actor=staff(case)
        )
    cause = refused.value.__cause__
    assert isinstance(cause, psycopg.Error) and cause.sqlstate == NOT_COVERED
    paid = create_usd_refund(
        service(),
        case.prop,
        CreateUsdRefundCommand(uuid4(), "CREDIT", payer_credit, 5_000, REASON),
        actor=staff(case),
    )
    assert cast(dict[str, object], paid["refund"])["recipient_customer_id"] == str(
        case.customer_wrong
    )
    # Recording needs refunds.create, in the service and in the database.
    with pytest.raises(RefundAuthorizationError):
        service().record_credit_customer_draft(
            prop, command(own, 500), choice, actor=person(human, prop, "credits.apply")
        )
    with pytest.raises(psycopg.Error) as denied, psycopg.connect(financial_database_url()) as c:
        c.execute(
            f"SELECT {RECORD.split('(')[0]}(%s,%s,%s,%s,500,%s,%s,%s,'credits.apply')",
            (prop, human, uuid4(), own, REASON, choice.refund_method_id, CASH_REFERENCE_NOTE),
        )
    assert denied.value.sqlstate == "42501"


def test_a_stale_or_rejected_credit_customer_draft_pays_nothing(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """A draft whose amount is no longer available is refused at confirmation and stays pending;
    a rejected draft cannot be confirmed; a reused key with another body is refused."""
    url = migrated_database_url
    case, credit, _ = third_party_credit(url)
    choice = cash(service(), case.prop, staff(case))
    first = service().record_credit_customer_draft(
        case.prop, command(credit, 4_000), choice, actor=staff(case)
    )
    second_request = command(credit, 2_000)
    second = service().record_credit_customer_draft(
        case.prop, second_request, choice, actor=staff(case)
    )
    with pytest.raises(RefundIdempotencyKeyReused):
        service().record_credit_customer_draft(
            case.prop,
            CreateCreditCustomerRefundCommand(
                second_request.idempotency_key, credit, 1_000, REASON
            ),
            choice,
            actor=staff(case),
        )
    service().confirm_draft(case.prop, UUID(str(first["draft_id"])), actor=approving(case))
    second_id = UUID(str(second["draft_id"]))
    with pytest.raises(RefundInvalidError):
        service().confirm_draft(case.prop, second_id, actor=approving(case))
    assert state(url, second_id) is None
    assert [row[2] for row in refunds_of(url, credit)] == [4_000] and available(
        url, credit
    ) == 1_000
    drafts().reject(case.prop, second_id, "Amount no longer available", actor=approving(case))
    with pytest.raises(RefundConflictError):
        service().confirm_draft(case.prop, second_id, actor=approving(case))
    assert state(url, second_id) == "REJECTED"
    assert [row[2] for row in refunds_of(url, credit)] == [4_000] and available(
        url, credit
    ) == 1_000


def test_a_credit_customer_refund_is_written_only_through_its_confirmed_draft(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """Defense in depth: without a matching draft the Refund source check refuses a Refund to the
    Invoice Customer (23514); with a pending draft but no confirmation the deferred check refuses
    the commit (42501); the writer has no grant."""
    url = migrated_database_url
    case, credit, _ = third_party_credit(url)
    insert = (
        "INSERT INTO app.refunds(id,refund_number,recipient_customer_id,source_customer_credit_id,"
        "usd_accounting_value_cents,refund_currency,refund_amount_minor,reason,processed_at,"
        "processed_by,authorization_reference) VALUES (%s,'REF-'||%s::text,%s,%s,%s,'USD',%s,%s,"
        "clock_timestamp(),%s,'refunds.create')"
    )
    loose = uuid4()
    with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
        connection.execute(
            insert, (loose, loose, case.customer_wrong, credit, 1_000, 1_000, REASON, case.approver)
        )
    assert refused.value.sqlstate == "23514"
    draft = service().record_credit_customer_draft(
        case.prop,
        command(credit, 1_000),
        cash(service(), case.prop, staff(case)),
        actor=staff(case),
    )
    identity = UUID(str(draft["draft_id"]))
    derived = UUID(str(value(url, "SELECT app.credit_customer_refund_id(%s)", identity)))
    with pytest.raises(psycopg.Error) as unconfirmed:
        with psycopg.connect(url) as connection:
            connection.execute(
                insert,
                (
                    derived,
                    derived,
                    case.customer_wrong,
                    credit,
                    1_000,
                    1_000,
                    REASON,
                    case.approver,
                ),
            )
    assert unconfirmed.value.sqlstate == "42501"
    with pytest.raises(psycopg.Error) as denied, psycopg.connect(financial_database_url()) as c:
        c.execute(
            "SELECT app.post_credit_customer_refund(%s,%s,%s)",
            (case.prop, case.approver, identity),
        )
    assert denied.value.sqlstate == "42501"
    assert refunds_of(url, credit) == [] and available(url, credit) == 5_000
    assert state(url, identity) is None


def test_only_the_same_approver_s_confirmation_and_details_let_the_refund_stand(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """Each clause of the two checks (review rounds 1 and 2). The source check refuses at once a
    Refund whose draft has a decision that is not a CONFIRMED one by the Refund's approver. The
    deferred check refuses at commit a Refund written while its draft waits unless the same
    approver's CONFIRMED decision and the details row both exist. (CONFIRMED always records
    financial.approve, financial_draft_decision_shape, so that clause cannot be broken alone.)
    Every attempt is rolled back; the real confirmation still succeeds after an earlier
    SET CONSTRAINTS ALL IMMEDIATE in its transaction, because the writer keeps its own check
    deferred."""
    url = migrated_database_url
    case, credit, _ = third_party_credit(url)
    choice = cash(service(), case.prop, staff(case))
    draft = service().record_credit_customer_draft(
        case.prop, command(credit, 1_000), choice, actor=staff(case)
    )
    identity = UUID(str(draft["draft_id"]))
    derived = UUID(str(value(url, "SELECT app.credit_customer_refund_id(%s)", identity)))
    decide = (
        "INSERT INTO app.financial_draft_decisions(draft_id,decision,reason,decided_at,decided_by,"
        "authorization_reference,result) "
        "VALUES (%s,%s,%s,clock_timestamp(),%s,'financial.approve',%s)"
    )
    insert = (
        "INSERT INTO app.refunds(id,refund_number,recipient_customer_id,source_customer_credit_id,"
        "usd_accounting_value_cents,refund_currency,refund_amount_minor,reason,processed_at,"
        "processed_by,authorization_reference) VALUES (%s,'REF-'||%s::text,%s,%s,1000,'USD',1000,"
        "%s,clock_timestamp(),%s,'refunds.create')"
    )
    details = (
        "INSERT INTO app.refund_draft_details(refund_id,draft_id,refund_method_id,reference_note,"
        "recorded_at) VALUES (%s,%s,%s,%s,clock_timestamp())"
    )
    source_refusal = ("23514", "Refund source, amount, authorization or chronology is invalid")
    confirm_refusal = (
        "42501",
        "A Credit Refund to the Invoice Customer needs its draft confirmed under financial.approve "
        "by the same approver",
    )
    confirmed_by_approver = (
        identity,
        "CONFIRMED",
        None,
        case.approver,
        Jsonb({"refund_id": str(derived)}),
    )
    confirmed_by_other = (
        identity,
        "CONFIRMED",
        None,
        case.human,
        Jsonb({"refund_id": str(derived)}),
    )
    rejected = (identity, "REJECTED", "Not this recipient", case.approver, None)
    refund = (derived, derived, case.customer_wrong, credit, REASON, case.approver)
    detail = (derived, identity, choice.refund_method_id, CASH_REFERENCE_NOTE)
    # (decision before the Refund, write the details row, decision after the Refund, expected)
    attempts: tuple[tuple[Any, bool, Any, tuple[str, str]], ...] = (
        (confirmed_by_other, False, None, source_refusal),  # confirmed by another approver
        (rejected, False, None, source_refusal),  # a decision that is not CONFIRMED
        (confirmed_by_approver, False, None, confirm_refusal),  # no details row
        (None, True, None, confirm_refusal),  # details row, no decision
        (None, True, confirmed_by_other, confirm_refusal),  # details, confirmed by another approver
        (None, True, rejected, confirm_refusal),  # details, a decision that is not CONFIRMED
    )
    for before, with_details, after, expected in attempts:
        with pytest.raises(psycopg.Error) as refused:
            with psycopg.connect(url) as connection:
                if before is not None:
                    connection.execute(decide, before)
                connection.execute(insert, refund)
                if with_details:
                    connection.execute(details, detail)
                if after is not None:
                    connection.execute(decide, after)
        found = (refused.value.sqlstate, refused.value.diag.message_primary)
        assert found == expected, (before, with_details, after)
    assert refunds_of(url, credit) == [] and available(url, credit) == 5_000
    assert state(url, identity) is None
    # The real confirmation, after an earlier SET CONSTRAINTS ALL IMMEDIATE in its transaction.
    with psycopg.connect(url) as connection:
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        connection.execute(
            "SELECT app.confirm_refund_draft(%s,%s,%s,'financial.approve')",
            (case.prop, case.approver, identity),
        )
    assert refunds_of(url, credit) == [(derived, case.customer_wrong, 1_000)]
    assert available(url, credit) == 4_000 and state(url, identity) == "CONFIRMED"


def test_credit_customer_refund_records_are_least_privilege(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        for function in INTERNAL:
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (role, function)
        assert connection.execute(
            "SELECT has_function_privilege('prm_financial',%s,'EXECUTE'),"
            "has_function_privilege('prm_runtime',%s,'EXECUTE'),"
            "has_function_privilege('prm_bootstrap',%s,'EXECUTE'),"
            "has_function_privilege('public',%s,'EXECUTE')",
            (RECORD,) * 4,
        ).fetchone() == (True, False, False, False)
        for function in (RECORD, *INTERNAL):
            definer, settings = cast(
                tuple[bool, list[str]],
                connection.execute(
                    "SELECT prosecdef,proconfig FROM pg_catalog.pg_proc "
                    "WHERE oid=CAST(%s AS regprocedure)",
                    (function,),
                ).fetchone(),
            )
            assert definer and "search_path=pg_catalog" in settings, function
        assert connection.execute(
            "SELECT tgdeferrable,tginitdeferred FROM pg_catalog.pg_trigger "
            "WHERE tgrelid='app.refunds'::regclass AND tgname='refunds_credit_customer_confirmed'"
        ).fetchone() == (True, True)


def test_credit_customer_refund_migration_is_forward_only_and_changes_two_functions(
    migrated_database_url: str,  # noqa: F811
) -> None:
    assert migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261030_95")
    assert revision is not None and revision.down_revision == "20261029_94"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(url: str) -> tuple[dict[str, object], set[str]]:
        with psycopg.connect(url) as connection:
            functions = {
                str(row[0]): row[1]
                for row in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid) "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ).fetchall()
            }
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT c.oid::regclass::text FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND c.relkind IN ('r','v','m','p')"
                ).fetchall()
            }
        return functions, tables

    with _temporary_migration_database("credit_customer_refund") as temporary:
        alembic_command.upgrade(config, "20261029_94")
        before_functions, before_tables = catalog(temporary)
        alembic_command.upgrade(config, "20261030_95")
        after_functions, after_tables = catalog(temporary)
    assert after_tables == before_tables
    assert set(after_functions) - set(before_functions) == {RECORD, *INTERNAL}
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {
        CONFIRM,
        "app.validate_general_refund_source()",
    }
