"""V1-056 slice 7: wrong-Unit Payment move drafts refuse bad input before any connection."""

from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.credit import CreditConflictError, CustomerCreditService, ReverseCreditCommand
from property_rental.financial_draft import KIND_PREPARE_CAPABILITIES, FinancialDraftKind
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.payment_move import (
    PaymentMoveAuthorizationError,
    PaymentMoveConflictError,
    PaymentMoveInvalidError,
    PaymentMoveKeyReused,
    PaymentMoveNotFoundError,
    PaymentMoveService,
    PaymentMoveUnavailableError,
    RecordPaymentMoveCommand,
    payment_move_draft_id,
)

PROPERTY = UUID(int=7)
HUMAN = UUID(int=8)


def person(*capabilities: str, actor_id: str = str(HUMAN)) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id,
        frozenset(CapabilityGrant(value, frozenset({str(PROPERTY)})) for value in capabilities),
    )


def command(**changes: object) -> RecordPaymentMoveCommand:
    values: dict[str, object] = {
        "idempotency_key": UUID(int=1),
        "allocation_id": UUID(int=2),
        "target_invoice_id": UUID(int=3),
        "reason": "Paid on Unit 203, meant for Unit 201",
        "source_acknowledgement": "Dara Sok, 2026-10-04, in person at the office",
        "target_acknowledgement": "Vanna Chea, 2026-10-04, by telephone",
        **changes,
    }
    return RecordPaymentMoveCommand(**values)  # type: ignore[arg-type]


@pytest.fixture
def no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    def connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("no database connection may be opened")

    monkeypatch.setattr(psycopg, "connect", connect)


def test_payment_move_record_and_confirm_refuse_missing_capability_before_any_connection(
    no_connection: None,
) -> None:
    del no_connection
    service = PaymentMoveService("unused")
    for actor in (
        person(),
        person("financial.approve"),
        person("payments.allocate"),
        person("payments.allocations.reverse", actor_id="x"),
        person("payments.allocations.reverse", actor_id=str(UUID(int=0))),
    ):
        with pytest.raises(PaymentMoveAuthorizationError):
            service.record(PROPERTY, command(), actor=actor)
    for actor in (person(), person("payments.allocations.reverse"), person("payments.allocate")):
        with pytest.raises(PaymentMoveAuthorizationError):
            service.confirm(PROPERTY, UUID(int=4), actor=actor)


def test_payment_move_invalid_input_is_refused_before_any_connection(no_connection: None) -> None:
    del no_connection
    service = PaymentMoveService("unused")
    for change in (
        {"idempotency_key": UUID(int=0)},
        {"allocation_id": UUID(int=0)},
        {"target_invoice_id": UUID(int=0)},
        {"allocation_id": "not-a-uuid"},
        {"reason": ""},
        {"reason": " Paid on the wrong Unit"},
        {"reason": "x" * 1001},
        {"source_acknowledgement": ""},
        {"source_acknowledgement": "Dara Sok\x00"},
        {"source_acknowledgement": "x" * 2001},
        {"target_acknowledgement": "Vanna Chea, by telephone "},
        {"target_acknowledgement": "x" * 2001},
    ):
        with pytest.raises(PaymentMoveInvalidError):
            service.record(
                PROPERTY, command(**change), actor=person("payments.allocations.reverse")
            )
    with pytest.raises(PaymentMoveInvalidError):
        service.confirm(PROPERTY, UUID(int=0), actor=person("financial.approve"))
    with pytest.raises(PaymentMoveInvalidError):
        service.record(UUID(int=0), command(), actor=person("payments.allocations.reverse"))
    # The limits are inclusive.
    assert command(reason="x" * 1000, source_acknowledgement="y" * 2000).reason == "x" * 1000


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        ("P0002", PaymentMoveNotFoundError),
        ("P4901", PaymentMoveNotFoundError),
        ("P4501", PaymentMoveNotFoundError),
        ("42501", PaymentMoveAuthorizationError),
        ("P4506", PaymentMoveAuthorizationError),
        ("22023", PaymentMoveInvalidError),
        ("P5205", PaymentMoveKeyReused),
        ("55000", PaymentMoveConflictError),
        ("23514", PaymentMoveConflictError),
        ("23505", PaymentMoveConflictError),
        ("P4904", PaymentMoveConflictError),
        ("40001", PaymentMoveConflictError),
        ("40P01", PaymentMoveConflictError),
        ("55P03", PaymentMoveConflictError),
        ("08006", PaymentMoveUnavailableError),
        ("57014", PaymentMoveUnavailableError),
    ],
)
def test_payment_move_database_failures_map_to_stable_errors(
    monkeypatch: pytest.MonkeyPatch, sqlstate: str, expected: type[Exception]
) -> None:
    class Failure(psycopg.Error):
        pass

    failure = Failure("Synthetic failure")
    failure.sqlstate = sqlstate

    def connect(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(psycopg, "connect", connect)
    with pytest.raises(expected):
        PaymentMoveService("unused").record(
            PROPERTY, command(), actor=person("payments.allocations.reverse")
        )
    with pytest.raises(expected):
        PaymentMoveService("unused").confirm(
            PROPERTY, UUID(int=4), actor=person("financial.approve")
        )


def test_payment_move_business_state_refusals_are_conflicts() -> None:
    # Owner answer for slice 11c (2026-10-05): stale or blocked drafts reach the user as conflicts.
    assert issubclass(PaymentMoveKeyReused, PaymentMoveConflictError)
    assert not issubclass(PaymentMoveConflictError, ValueError)


def test_payment_move_draft_id_is_scoped_to_property_preparer_and_key() -> None:
    key = uuid4()
    base = payment_move_draft_id(PROPERTY, HUMAN, key)
    assert base == payment_move_draft_id(PROPERTY, HUMAN, key)
    assert base != payment_move_draft_id(UUID(int=9), HUMAN, key)
    assert base != payment_move_draft_id(PROPERTY, UUID(int=9), key)
    assert base != payment_move_draft_id(PROPERTY, HUMAN, uuid4())


def test_payment_move_drafts_are_prepared_only_under_the_allocation_reversal_capability() -> None:
    assert KIND_PREPARE_CAPABILITIES[FinancialDraftKind.PAYMENT_MOVE] == frozenset(
        {"payments.allocations.reverse"}
    )


def test_credit_reversal_of_moved_payment_value_is_a_conflict() -> None:
    # Q-2026-10-05-18: the Credit reversal refusal (P4904) reaches the user as a conflict.
    class Failure(psycopg.Error):
        pass

    failure = Failure("Synthetic private diagnostic")
    failure.sqlstate = "P4904"
    actor = AuthenticatedActor(
        str(HUMAN), frozenset({CapabilityGrant("credits.reverse", frozenset({str(PROPERTY)}))})
    )
    with patch("property_rental.credit.psycopg.connect", side_effect=failure):
        with pytest.raises(CreditConflictError) as caught:
            CustomerCreditService("read-only", "financial").reverse(
                PROPERTY, UUID(int=5), ReverseCreditCommand(UUID(int=6), "Return"), actor=actor
            )
    assert "Synthetic private diagnostic" not in str(caught.value)
