"""V1-056 sub-slice 8r: Deposit receipt reversal drafts refuse bad input before any connection."""

from uuid import UUID

import psycopg
import pytest

from property_rental.deposit import (
    DepositAuthorizationError,
    DepositReceiptReversalDraftRequired,
    PostgresDepositService,
    ReverseDepositReceiptCommand,
)
from property_rental.deposit_receipt_reversal import (
    DepositReceiptReversalAuthorizationError,
    DepositReceiptReversalConflictError,
    DepositReceiptReversalInvalidError,
    DepositReceiptReversalKeyReused,
    DepositReceiptReversalNotFoundError,
    DepositReceiptReversalService,
    DepositReceiptReversalUnavailableError,
    RecordDepositReceiptReversalCommand,
    deposit_receipt_reversal_draft_id,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant

PROPERTY = UUID(int=7)
HUMAN = UUID(int=8)


def person(*capabilities: str, actor_id: str = str(HUMAN)) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id,
        frozenset(CapabilityGrant(value, frozenset({str(PROPERTY)})) for value in capabilities),
    )


def command() -> RecordDepositReceiptReversalCommand:
    return RecordDepositReceiptReversalCommand(UUID(int=1), UUID(int=2), UUID(int=3), "Returned")


@pytest.fixture
def no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    def connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("no database connection may be opened")

    monkeypatch.setattr(psycopg, "connect", connect)


def test_receipt_reversal_needs_deposits_correct_and_approval_before_any_connection(
    no_connection: None,
) -> None:
    service = DepositReceiptReversalService("unused")
    # Recording needs deposits.correct; financial.approve alone does not prepare.
    for actor in (person(), person("financial.approve"), person("deposits.dispose")):
        with pytest.raises(DepositReceiptReversalAuthorizationError):
            service.record(PROPERTY, command(), actor=actor)
    # Only a financial.approve holder confirms; deposits.correct alone does not.
    for actor in (person(), person("deposits.correct")):
        with pytest.raises(DepositReceiptReversalAuthorizationError):
            service.confirm(PROPERTY, UUID(int=2), UUID(int=4), actor=actor)
    with pytest.raises(DepositReceiptReversalAuthorizationError):
        service.record(PROPERTY, command(), actor=person("deposits.correct", actor_id="nobody"))


def test_receipt_reversal_input_is_refused_before_any_connection(no_connection: None) -> None:
    with pytest.raises(DepositReceiptReversalInvalidError):
        RecordDepositReceiptReversalCommand(UUID(int=1), UUID(int=2), UUID(int=2), "Returned")
    for reason in ("", " Returned", "x" * 501, "Re\x00turned"):
        with pytest.raises(DepositReceiptReversalInvalidError):
            RecordDepositReceiptReversalCommand(UUID(int=1), UUID(int=2), UUID(int=3), reason)
    with pytest.raises(DepositReceiptReversalInvalidError):
        RecordDepositReceiptReversalCommand(UUID(int=0), UUID(int=2), UUID(int=3), "Returned")
    service = DepositReceiptReversalService("unused")
    with pytest.raises(DepositReceiptReversalInvalidError):
        service.confirm(PROPERTY, UUID(int=0), UUID(int=4), actor=person("financial.approve"))
    with pytest.raises(DepositReceiptReversalInvalidError):
        service.record(UUID(int=0), command(), actor=person("deposits.correct"))


def test_one_call_receipt_reversal_refuses_before_any_connection(no_connection: None) -> None:
    service = PostgresDepositService("unused", PROPERTY, HUMAN)
    reversal = ReverseDepositReceiptCommand(UUID(int=1), UUID(int=3), UUID(int=2), "Returned")
    with pytest.raises(DepositReceiptReversalDraftRequired):
        service.reverse_receipt(reversal, actor=person("deposits.correct"))
    with pytest.raises(DepositAuthorizationError):
        service.reverse_receipt(reversal, actor=person("financial.approve"))


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        ("P0002", DepositReceiptReversalNotFoundError),
        ("P4501", DepositReceiptReversalNotFoundError),
        ("42501", DepositReceiptReversalAuthorizationError),
        ("P4506", DepositReceiptReversalAuthorizationError),
        ("22023", DepositReceiptReversalInvalidError),
        ("23514", DepositReceiptReversalInvalidError),
        ("P5205", DepositReceiptReversalKeyReused),
        ("55000", DepositReceiptReversalConflictError),
        ("23505", DepositReceiptReversalConflictError),
        ("P5801", DepositReceiptReversalConflictError),
        ("40001", DepositReceiptReversalConflictError),
        ("XX000", DepositReceiptReversalUnavailableError),
    ],
)
def test_receipt_reversal_failures_map_to_stable_errors(
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
        DepositReceiptReversalService("unused").record(
            PROPERTY, command(), actor=person("deposits.correct")
        )


def test_receipt_reversal_draft_id_is_scoped_to_property_preparer_and_key() -> None:
    first = deposit_receipt_reversal_draft_id(PROPERTY, HUMAN, UUID(int=1))
    assert first == deposit_receipt_reversal_draft_id(PROPERTY, HUMAN, UUID(int=1))
    assert first != deposit_receipt_reversal_draft_id(UUID(int=9), HUMAN, UUID(int=1))
    assert first != deposit_receipt_reversal_draft_id(PROPERTY, UUID(int=9), UUID(int=1))
    assert first != deposit_receipt_reversal_draft_id(PROPERTY, HUMAN, UUID(int=9))
