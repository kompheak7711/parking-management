"""Credit scalar intent, capability separation and unresolved-outcome boundaries."""

from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.credit import (
    ApplyCreditCommand,
    CreditAuthorizationError,
    CreditConflictError,
    CreditIdempotencyKeyReused,
    CreditInvalidError,
    CreditNotFoundError,
    CreditUnavailableError,
    CustomerCreditService,
    RecognizeCreditCommand,
    ReverseCreditApplicationCommand,
    ReverseCreditCommand,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant


def staff(prop: UUID, *caps: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(uuid4()), frozenset(CapabilityGrant(cap, frozenset({str(prop)})) for cap in caps)
    )


@pytest.mark.parametrize("amount", [0, -1, True, 1.5, 9_000_000_000_000_001])
def test_credit_recognition_requires_positive_exact_bounded_cents(amount: int) -> None:
    with pytest.raises(CreditInvalidError):
        RecognizeCreditCommand(uuid4(), amount, "Payer consent", "Retain identified excess")


@pytest.mark.parametrize("reference", ["", " ", " leading", "trailing ", "x" * 501])
def test_credit_recognition_requires_explicit_normalized_payer_authorization(
    reference: str,
) -> None:
    with pytest.raises(CreditInvalidError):
        RecognizeCreditCommand(uuid4(), 100, reference, "Retain identified excess")


@pytest.mark.parametrize("reason", ["", " ", " leading", "trailing ", "x" * 1001])
def test_credit_commands_require_bounded_reasons(reason: str) -> None:
    with pytest.raises(CreditInvalidError):
        RecognizeCreditCommand(uuid4(), 100, "Payer consent", reason)
    with pytest.raises(CreditInvalidError):
        ReverseCreditCommand(uuid4(), reason)


def test_credit_command_uuid_and_immutable_scalars() -> None:
    command = RecognizeCreditCommand(uuid4(), 9_000_000_000_000_000, "x" * 500, "y" * 1000)
    assert command.amount_usd_cents == 9_000_000_000_000_000
    with pytest.raises(FrozenInstanceError):
        command.amount_usd_cents = 1  # type: ignore[misc]  # Runtime immutability probe.
    with pytest.raises(CreditInvalidError):
        RecognizeCreditCommand(UUID(int=0), 100, "Consent", "Retain excess")
    with pytest.raises(CreditInvalidError):
        ReverseCreditCommand(UUID(int=0), "Wrong consent")


@pytest.mark.parametrize("operation", ["get", "recognize", "reverse"])
def test_credit_capabilities_and_property_scope_are_independent(operation: str) -> None:
    prop, target = uuid4(), uuid4()
    expected = {
        "get": "credits.read",
        "recognize": "credits.recognize",
        "reverse": "credits.reverse",
    }[operation]
    service = CustomerCreditService("unused", "unused")
    with patch("property_rental.credit.psycopg.connect") as connect:
        for actor in (
            staff(prop),
            staff(uuid4(), expected),
            staff(
                prop,
                *[
                    cap
                    for cap in ("credits.read", "credits.recognize", "credits.reverse")
                    if cap != expected
                ],
            ),
        ):
            with pytest.raises(CreditAuthorizationError):
                if operation == "recognize":
                    service.recognize(
                        prop,
                        target,
                        RecognizeCreditCommand(uuid4(), 100, "Consent", "Excess"),
                        actor=actor,
                    )
                elif operation == "reverse":
                    service.reverse(
                        prop, target, ReverseCreditCommand(uuid4(), "Wrong consent"), actor=actor
                    )
                else:
                    service.get(prop, target, actor=actor)
        connect.assert_not_called()


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        ("P5101", CreditNotFoundError),
        ("P4501", CreditNotFoundError),
        ("P5102", CreditInvalidError),
        ("P5105", CreditIdempotencyKeyReused),
        ("P5104", CreditConflictError),
        ("P4506", CreditAuthorizationError),
        ("42501", CreditAuthorizationError),
        ("40001", CreditUnavailableError),
        ("55P03", CreditUnavailableError),
        ("23514", CreditUnavailableError),
        (None, CreditUnavailableError),
    ],
)
def test_credit_failure_preserves_exact_replay_and_safe_message(
    sqlstate: str | None, expected: type[Exception]
) -> None:
    class DatabaseError(psycopg.Error):
        pass

    error = DatabaseError("Synthetic private diagnostic")
    error.sqlstate = sqlstate
    prop = uuid4()
    request = RecognizeCreditCommand(uuid4(), 12345, "Payer consent", "Retain excess")
    with patch("property_rental.credit.psycopg.connect", side_effect=error):
        with pytest.raises(expected) as caught:
            CustomerCreditService("read-only", "financial").recognize(
                prop, uuid4(), request, actor=staff(prop, "credits.recognize")
            )
    assert "Synthetic private diagnostic" not in str(caught.value)
    assert request.amount_usd_cents == 12345 and request.idempotency_key.int != 0


def test_credit_recognition_uses_financial_connection_and_complete_exact_envelope() -> None:
    prop, payment = uuid4(), uuid4()
    actor = staff(prop, "credits.recognize")
    request = RecognizeCreditCommand(uuid4(), 12345, "Payer consent", "Retain identified excess")
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = ({"credit": {"id": "synthetic"}},)
    with patch("property_rental.credit.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        result = CustomerCreditService("read-only", "financial").recognize(
            prop, payment, request, actor=actor
        )
        connect.assert_called_once_with("financial", connect_timeout=3)
    assert result == {"credit": {"id": "synthetic"}}
    connection.execute.assert_called_with(
        "SELECT app.recognize_customer_credit(%s,%s,%s,%s,%s,%s,%s)",
        (
            prop,
            payment,
            UUID(actor.actor_id),
            request.idempotency_key,
            12345,
            "Payer consent",
            "Retain identified excess",
        ),
    )


def test_credit_read_uses_scoped_read_connection_and_actor() -> None:
    prop, credit = uuid4(), uuid4()
    actor = staff(prop, "credits.read")
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = ({"available_usd_cents": 12345},)
    with patch("property_rental.credit.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        result = CustomerCreditService("read-only", "financial").get(prop, credit, actor=actor)
        connect.assert_called_once_with("read-only", connect_timeout=3)
    assert result == {"available_usd_cents": 12345}
    connection.execute.assert_called_with(
        "SELECT app.credit_resource(%s,%s,%s)", (prop, credit, UUID(actor.actor_id))
    )


def test_credit_application_command_seals_deep_intent_before_transmission() -> None:
    prop, credit, invoice, line = uuid4(), uuid4(), uuid4(), uuid4()
    original: dict[str, object] = {
        "mode": "DESIGNATED",
        "invoice_id": str(invoice),
        "amount_usd_cents": 100,
        "designation_reference": "Customer instruction",
        "details": [{"invoice_line_id": str(line), "amount_usd_cents": 100}],
    }
    command = ApplyCreditCommand(uuid4(), original)
    original["amount_usd_cents"] = 999
    details = original["details"]
    assert isinstance(details, list)
    details[0]["amount_usd_cents"] = 999
    detached = command.intent
    detached["amount_usd_cents"] = 888
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = ({"application": {"id": "synthetic"}},)
    with patch("property_rental.credit.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        CustomerCreditService("read", "financial").apply(
            prop,
            credit,
            command,
            actor=staff(prop, "credits.apply"),
        )
        connect.assert_called_once_with("financial", connect_timeout=3)
    parameters = connection.execute.call_args.args[1]
    transmitted = parameters[-1].obj
    assert transmitted["amount_usd_cents"] == 100
    assert transmitted["details"][0]["amount_usd_cents"] == 100
    assert transmitted == command.intent
    assert parameters[3] == command.idempotency_key


@pytest.mark.parametrize("amount", [True, 1.1, 0, -1, "100", 9_000_000_000_000_001])
def test_credit_application_intent_rejects_nonexact_or_unbounded_money(amount: object) -> None:
    with pytest.raises(CreditInvalidError):
        ApplyCreditCommand(
            uuid4(),
            {
                "mode": "DIRECT_CHARGE",
                "late_payment_charge_id": str(uuid4()),
                "amount_usd_cents": amount,
            },
        )


@pytest.mark.parametrize(
    "mutation", ["nil", "both_targets", "unknown_field", "missing_reference", "empty_details"]
)
def test_credit_application_intent_rejects_malformed_target_and_designation(mutation: str) -> None:
    intent: dict[str, object] = {
        "mode": "DESIGNATED",
        "invoice_id": str(uuid4()),
        "amount_usd_cents": 100,
        "designation_reference": "Instruction",
        "details": [{"invoice_line_id": str(uuid4()), "amount_usd_cents": 100}],
    }
    if mutation == "nil":
        intent["invoice_id"] = str(UUID(int=0))
    elif mutation == "both_targets":
        intent["late_payment_charge_id"] = str(uuid4())
    elif mutation == "unknown_field":
        intent["available_usd_cents"] = 100
    elif mutation == "missing_reference":
        del intent["designation_reference"]
    else:
        intent["details"] = []
    with pytest.raises(CreditInvalidError):
        ApplyCreditCommand(uuid4(), intent)


def test_credit_application_intent_utf8_and_nesting_bounds() -> None:
    proposal: dict[str, object] = {"invoice_id": str(uuid4()), "amount_usd_cents": 1}
    with pytest.raises(CreditInvalidError):
        ApplyCreditCommand(
            uuid4(), {"mode": "PROPOSAL", "proposal": {**proposal, "text": "界" * 100000}}
        )
    nested: object = None
    for _ in range(30):
        nested = [nested]
    with pytest.raises(CreditInvalidError):
        ApplyCreditCommand(uuid4(), {"mode": "PROPOSAL", "proposal": {**proposal, "trace": nested}})
    # Authoritative target snapshots may exceed the individual command money bound.
    valid = ApplyCreditCommand(
        uuid4(),
        {
            "mode": "PROPOSAL",
            "proposal": {
                **proposal,
                "details": [{"outstanding_usd_cents": 9_223_372_036_854_775_807}],
            },
        },
    )
    assert valid.intent["proposal"] is not None


@pytest.mark.parametrize("operation", ["proposal", "apply", "read", "reverse"])
def test_credit_application_capabilities_remain_separable_before_database_access(
    operation: str,
) -> None:
    prop, credit, target = uuid4(), uuid4(), uuid4()
    service = CustomerCreditService("unused", "unused")
    with patch("property_rental.credit.psycopg.connect") as connect:
        with pytest.raises(CreditAuthorizationError):
            if operation == "proposal":
                service.application_proposal(
                    prop, credit, target, 1, actor=staff(prop, "credits.read")
                )
            elif operation == "apply":
                service.apply(
                    prop,
                    credit,
                    ApplyCreditCommand(
                        uuid4(),
                        {
                            "mode": "DIRECT_CHARGE",
                            "late_payment_charge_id": str(target),
                            "amount_usd_cents": 1,
                        },
                    ),
                    actor=staff(prop, "credits.applications.reverse"),
                )
            elif operation == "read":
                service.get_application(prop, target, actor=staff(prop, "credits.apply"))
            else:
                service.reverse_application(
                    prop,
                    target,
                    ReverseCreditApplicationCommand(uuid4(), "Reason"),
                    actor=staff(prop, "credits.apply"),
                )
        connect.assert_not_called()
