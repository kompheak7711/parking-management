"""Receipt command validation, independent capability boundaries and safe failures."""

from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.receipt import (
    ReceiptAuthorizationError,
    ReceiptIdempotencyKeyReused,
    ReceiptInvalidError,
    ReceiptNotFoundError,
    ReceiptService,
    ReceiptUnavailableError,
    ReprintReceiptCommand,
)


def staff(prop: UUID, *caps: str, identity: str | None = None) -> AuthenticatedActor:
    return AuthenticatedActor(
        identity if identity is not None else str(uuid4()),
        frozenset(CapabilityGrant(cap, frozenset({str(prop)})) for cap in caps),
    )


@pytest.mark.parametrize("reason", ["", " ", " leading", "trailing ", "x" * 1001])
def test_receipt_command_rejects_invalid_reason(reason: str) -> None:
    with pytest.raises(ReceiptInvalidError):
        ReprintReceiptCommand(uuid4(), reason)


@pytest.mark.parametrize("delivery", ["", " ", " leading", "trailing ", "x" * 501])
def test_receipt_command_rejects_invalid_delivery(delivery: str) -> None:
    with pytest.raises(ReceiptInvalidError):
        ReprintReceiptCommand(uuid4(), "Copy", delivery)


def test_receipt_command_bounds_identity_and_immutability() -> None:
    request = ReprintReceiptCommand(uuid4(), "x" * 1000, "y" * 500)
    assert len(request.reason) == 1000 and request.delivery_reference == "y" * 500
    with pytest.raises(FrozenInstanceError):
        request.reason = "Changed"  # type: ignore[misc]  # Exercise the runtime frozen guard.
    with pytest.raises(ReceiptInvalidError):
        ReprintReceiptCommand(UUID(int=0), "Copy")


@pytest.mark.parametrize("operation", ["get", "for_payment", "history", "reprint"])
def test_receipt_capability_and_scope_are_checked_before_database(operation: str) -> None:
    prop, receipt = uuid4(), uuid4()
    expected = "receipts.reprint" if operation == "reprint" else "receipts.read"
    other = "receipts.read" if operation == "reprint" else "receipts.reprint"
    service = ReceiptService("unused", "unused")
    with patch("property_rental.receipt.psycopg.connect") as connect:
        for actor in (staff(prop, other), staff(uuid4(), expected), staff(prop)):
            with pytest.raises(ReceiptAuthorizationError):
                if operation == "reprint":
                    service.reprint(
                        prop, receipt, ReprintReceiptCommand(uuid4(), "Copy"), actor=actor
                    )
                else:
                    getattr(service, operation)(prop, receipt, actor=actor)
        connect.assert_not_called()


@pytest.mark.parametrize("identity", ["not-a-uuid", str(UUID(int=0))])
def test_receipt_invalid_actor_cannot_reach_database(identity: str) -> None:
    prop = uuid4()
    with patch("property_rental.receipt.psycopg.connect") as connect:
        with pytest.raises(ReceiptAuthorizationError):
            ReceiptService("unused", "unused").get(
                prop, uuid4(), actor=staff(prop, "receipts.read", identity=identity)
            )
        connect.assert_not_called()


@pytest.mark.parametrize("limit", [0, 101, True, 1.5])
def test_receipt_history_rejects_invalid_bounds(limit: int) -> None:
    prop = uuid4()
    with patch("property_rental.receipt.psycopg.connect") as connect:
        with pytest.raises(ReceiptInvalidError):
            ReceiptService("unused", "unused").history(
                prop, uuid4(), actor=staff(prop, "receipts.read"), limit=limit
            )
        connect.assert_not_called()


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        ("P5001", ReceiptNotFoundError),
        ("P4501", ReceiptNotFoundError),
        ("P5002", ReceiptInvalidError),
        ("P5005", ReceiptIdempotencyKeyReused),
        ("P4506", ReceiptAuthorizationError),
        ("42501", ReceiptAuthorizationError),
        ("40001", ReceiptUnavailableError),
        ("55P03", ReceiptUnavailableError),
        (None, ReceiptUnavailableError),
    ],
)
def test_receipt_database_errors_preserve_safe_outcome(
    sqlstate: str | None, expected: type[Exception]
) -> None:
    class DatabaseError(psycopg.Error):
        pass

    error = DatabaseError("Synthetic diagnostic must not be the public message")
    error.sqlstate = sqlstate
    prop = uuid4()
    request = ReprintReceiptCommand(uuid4(), "Copy")
    with patch("property_rental.receipt.psycopg.connect", side_effect=error):
        with pytest.raises(expected) as caught:
            ReceiptService("read-only", "financial").reprint(
                prop, uuid4(), request, actor=staff(prop, "receipts.reprint")
            )
    assert "Synthetic diagnostic" not in str(caught.value)
    assert request.reason == "Copy" and request.idempotency_key.int != 0


def test_receipt_reprint_uses_financial_connection_and_exact_parameters() -> None:
    prop, receipt = uuid4(), uuid4()
    actor = staff(prop, "receipts.reprint")
    request = ReprintReceiptCommand(uuid4(), "Copy", "Front desk")
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = ({"receipt_id": str(receipt)},)
    with patch("property_rental.receipt.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        result = ReceiptService("read-only", "financial").reprint(
            prop, receipt, request, actor=actor
        )
        connect.assert_called_once_with("financial", connect_timeout=3)
    assert result == {"receipt_id": str(receipt)}
    connection.execute.assert_called_with(
        "SELECT app.reprint_receipt(%s,%s,%s,%s,%s,%s)",
        (prop, receipt, UUID(actor.actor_id), request.idempotency_key, "Copy", "Front desk"),
    )
