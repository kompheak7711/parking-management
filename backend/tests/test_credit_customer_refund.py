"""Credit Customer Refund drafts in the Refund service (V1-056 sub-slice 8f, BR-CREDIT-014)."""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.refund import (
    CreateCreditCustomerRefundCommand,
    RefundAuthorizationError,
    RefundConflictError,
    RefundInvalidError,
    RefundMethodChoice,
    RefundService,
    RefundUnavailableError,
    refund_draft_id,
)
from test_credit import staff

RECORD_SQL = "SELECT app.record_credit_customer_refund_draft(%s,%s,%s,%s,%s,%s,%s,%s,%s)"


def command() -> CreateCreditCustomerRefundCommand:
    return CreateCreditCustomerRefundCommand(uuid4(), uuid4(), 300, "Return the Customer Credit")


def method() -> RefundMethodChoice:
    return RefundMethodChoice(uuid4(), "Cash handed over at the office")


def failing(sqlstate: str | None) -> psycopg.Error:
    class DatabaseError(psycopg.Error):
        pass

    error = DatabaseError("Synthetic private diagnostic")
    error.sqlstate = sqlstate
    return error


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("idempotency_key", UUID(int=0)),
        ("credit_id", UUID(int=0)),
        ("amount_usd_cents", 0),
        ("amount_usd_cents", 9_000_000_000_000_001),
        ("amount_usd_cents", True),
        ("reason", ""),
        ("reason", " padded "),
        ("reason", "x" * 1001),
    ],
)
def test_credit_customer_refund_command_is_exact_and_bounded(field: str, bad: object) -> None:
    values: dict[str, Any] = {
        "idempotency_key": uuid4(),
        "credit_id": uuid4(),
        "amount_usd_cents": 300,
        "reason": "Return the Customer Credit",
    }
    CreateCreditCustomerRefundCommand(**values)
    values[field] = bad
    with pytest.raises(RefundInvalidError):
        CreateCreditCustomerRefundCommand(**values)


def test_credit_customer_draft_needs_refunds_create_for_the_property() -> None:
    prop = uuid4()
    with patch("property_rental.refund.psycopg.connect") as connect:
        for actor in (
            staff(prop),
            staff(uuid4(), "refunds.create"),
            staff(prop, "financial.approve", "refunds.read", "credits.apply"),
        ):
            with pytest.raises(RefundAuthorizationError):
                RefundService("read", "write").record_credit_customer_draft(
                    prop, command(), method(), actor=actor
                )
        connect.assert_not_called()


def test_credit_customer_draft_sends_the_derived_draft_and_the_exact_values() -> None:
    prop = uuid4()
    actor = staff(prop, "refunds.create")
    request, choice = command(), method()
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = ({"draft_id": "x"},)
    with patch("property_rental.refund.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        assert RefundService("read", "write").record_credit_customer_draft(
            prop, request, choice, actor=actor
        ) == {"draft_id": "x"}
        connect.assert_called_once_with("write", connect_timeout=3)
    actor_id = UUID(actor.actor_id)
    connection.execute.assert_called_with(
        RECORD_SQL,
        (
            prop,
            actor_id,
            refund_draft_id(prop, actor_id, "CREDIT_CUSTOMER", request.idempotency_key),
            request.credit_id,
            300,
            "Return the Customer Credit",
            choice.refund_method_id,
            choice.reference_note,
            "refunds.create",
        ),
    )
    # The draft id is scoped like every Refund draft: another variant gives another id.
    assert refund_draft_id(prop, actor_id, "CREDIT_CUSTOMER", request.idempotency_key) != (
        refund_draft_id(prop, actor_id, "USD", request.idempotency_key)
    )


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        ("P5206", RefundConflictError),
        ("23514", RefundUnavailableError),
        (None, RefundUnavailableError),
    ],
)
def test_credit_customer_draft_failures_are_mapped_without_private_text(
    sqlstate: str | None, expected: type[Exception]
) -> None:
    prop = uuid4()
    with patch("property_rental.refund.psycopg.connect", side_effect=failing(sqlstate)):
        with pytest.raises(expected) as caught:
            RefundService("read", "write").record_credit_customer_draft(
                prop, command(), method(), actor=staff(prop, "refunds.create")
            )
    assert "private diagnostic" not in str(caught.value)


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        # Sub-slice 8f: a check or unique violation at confirmation rolled back and left the draft
        # pending.
        ("23514", RefundConflictError),
        ("23505", RefundConflictError),
        ("P5206", RefundConflictError),
        ("P5202", RefundInvalidError),
        ("42501", RefundAuthorizationError),
        ("40001", RefundUnavailableError),
        (None, RefundUnavailableError),
    ],
)
def test_refund_draft_confirmation_maps_a_check_violation_to_a_conflict(
    sqlstate: str | None, expected: type[Exception]
) -> None:
    prop = uuid4()
    with patch("property_rental.refund.psycopg.connect", side_effect=failing(sqlstate)):
        with pytest.raises(expected) as caught:
            RefundService("read", "write").confirm_draft(
                prop, uuid4(), actor=staff(prop, "financial.approve")
            )
    assert "private diagnostic" not in str(caught.value)


def test_a_refund_draft_for_money_a_correction_brought_back_is_a_conflict() -> None:
    """Sub-slice 10h-1b (owner answer (b) to Q-2026-10-19-141): the closed-Settlement refusal
    (P5S01) of a Credit Refund draft at record or at confirm is a conflict, not an unknown
    outcome, and carries no database text."""
    prop = uuid4()
    service = RefundService("read", "write")
    attempts: tuple[Callable[[], object], ...] = (
        lambda: service.record_credit_customer_draft(
            prop, command(), method(), actor=staff(prop, "refunds.create")
        ),
        lambda: service.confirm_draft(prop, uuid4(), actor=staff(prop, "financial.approve")),
    )
    for attempt in attempts:
        with patch("property_rental.refund.psycopg.connect", side_effect=failing("P5S01")):
            with pytest.raises(RefundConflictError) as caught:
                attempt()
        assert "private diagnostic" not in str(caught.value)
        assert "Final Settlement" in str(caught.value)
