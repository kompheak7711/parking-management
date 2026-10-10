"""V1-056 sub-slice 10e-1a: returned-Payment drafts refuse bad input before any connection."""

from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.financial_draft import KIND_PREPARE_CAPABILITIES, FinancialDraftKind
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.payment_return import (
    PaymentReturnAuthorizationError,
    PaymentReturnConflictError,
    PaymentReturnInvalidError,
    PaymentReturnKeyReused,
    PaymentReturnNotFoundError,
    PaymentReturnService,
    PaymentReturnStaleDraftError,
    PaymentReturnUnavailableError,
    RecordPaymentReturnCommand,
    payment_return_draft_id,
)

PROPERTY = UUID(int=7)
HUMAN = UUID(int=8)


def person(*capabilities: str, actor_id: str = str(HUMAN)) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id,
        frozenset(CapabilityGrant(value, frozenset({str(PROPERTY)})) for value in capabilities),
    )


def command(**changes: object) -> RecordPaymentReturnCommand:
    values: dict[str, object] = {
        "idempotency_key": UUID(int=1),
        "payment_id": UUID(int=2),
        "reason": "The bank returned the transfer",
        "evidence_reference": "Bank return notice 4471",
        **changes,
    }
    return RecordPaymentReturnCommand(**values)  # type: ignore[arg-type]


@pytest.fixture
def no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    def connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("no database connection may be opened")

    monkeypatch.setattr(psycopg, "connect", connect)


def test_payment_return_record_and_confirm_refuse_missing_capability_before_any_connection(
    no_connection: None,
) -> None:
    del no_connection
    service = PaymentReturnService("unused")
    for actor in (
        person(),
        person("financial.approve"),
        person("payments.allocations.reverse"),
        person("payments.reverse", actor_id="x"),
        person("payments.reverse", actor_id=str(UUID(int=0))),
    ):
        with pytest.raises(PaymentReturnAuthorizationError):
            service.record(PROPERTY, command(), actor=actor)
    for actor in (person(), person("payments.reverse"), person("payments.allocations.reverse")):
        with pytest.raises(PaymentReturnAuthorizationError):
            service.confirm(PROPERTY, UUID(int=4), actor=actor)


def test_payment_return_invalid_input_is_refused_before_any_connection(
    no_connection: None,
) -> None:
    del no_connection
    service = PaymentReturnService("unused")
    for change in (
        {"idempotency_key": UUID(int=0)},
        {"payment_id": UUID(int=0)},
        {"payment_id": "not-a-uuid"},
        {"reason": ""},
        {"reason": " The bank returned it"},
        {"reason": "x" * 1001},
        {"evidence_reference": ""},
        {"evidence_reference": "Notice\x00"},
        {"evidence_reference": "Notice 4471 "},
        {"evidence_reference": "x" * 501},
    ):
        with pytest.raises(PaymentReturnInvalidError):
            service.record(PROPERTY, command(**change), actor=person("payments.reverse"))
    with pytest.raises(PaymentReturnInvalidError):
        service.confirm(PROPERTY, UUID(int=0), actor=person("financial.approve"))
    with pytest.raises(PaymentReturnInvalidError):
        service.record(UUID(int=0), command(), actor=person("payments.reverse"))
    # The limits are inclusive.
    assert command(reason="x" * 1000, evidence_reference="y" * 500).reason == "x" * 1000


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        ("P0002", PaymentReturnNotFoundError),
        ("P4901", PaymentReturnNotFoundError),
        ("P4501", PaymentReturnNotFoundError),
        ("42501", PaymentReturnAuthorizationError),
        ("P4506", PaymentReturnAuthorizationError),
        ("22023", PaymentReturnInvalidError),
        ("P5205", PaymentReturnKeyReused),
        ("P5S02", PaymentReturnStaleDraftError),
        ("55000", PaymentReturnConflictError),
        ("23514", PaymentReturnConflictError),
        ("23505", PaymentReturnConflictError),
        ("P4904", PaymentReturnConflictError),
        ("P5S01", PaymentReturnConflictError),
        ("40001", PaymentReturnConflictError),
        ("40P01", PaymentReturnConflictError),
        ("55P03", PaymentReturnConflictError),
        ("08006", PaymentReturnUnavailableError),
        ("57014", PaymentReturnUnavailableError),
    ],
)
def test_payment_return_database_failures_map_to_stable_errors(
    monkeypatch: pytest.MonkeyPatch, sqlstate: str, expected: type[Exception]
) -> None:
    class Failure(psycopg.Error):
        pass

    failure = Failure("Synthetic private diagnostic")
    failure.sqlstate = sqlstate

    def connect(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(psycopg, "connect", connect)
    with pytest.raises(expected) as recorded:
        PaymentReturnService("unused").record(PROPERTY, command(), actor=person("payments.reverse"))
    assert "Synthetic private diagnostic" not in str(recorded.value)
    with pytest.raises(expected):
        PaymentReturnService("unused").confirm(
            PROPERTY, UUID(int=4), actor=person("financial.approve")
        )


def test_payment_return_business_state_refusals_are_conflicts() -> None:
    # Owner answer for slice 11c (2026-10-05): stale or blocked drafts reach the user as conflicts.
    assert issubclass(PaymentReturnKeyReused, PaymentReturnConflictError)
    assert issubclass(PaymentReturnStaleDraftError, PaymentReturnConflictError)
    assert not issubclass(PaymentReturnConflictError, ValueError)


def test_payment_return_draft_id_is_scoped_to_property_preparer_and_key() -> None:
    key = uuid4()
    base = payment_return_draft_id(PROPERTY, HUMAN, key)
    assert base == payment_return_draft_id(PROPERTY, HUMAN, key)
    assert base != payment_return_draft_id(UUID(int=9), HUMAN, key)
    assert base != payment_return_draft_id(PROPERTY, UUID(int=9), key)
    assert base != payment_return_draft_id(PROPERTY, HUMAN, uuid4())


def test_payment_return_drafts_are_prepared_only_under_the_payment_reversal_capability() -> None:
    # Owner answer 3 to Q-2026-10-06-37.
    assert KIND_PREPARE_CAPABILITIES[FinancialDraftKind.PAYMENT_RETURN] == frozenset(
        {"payments.reverse"}
    )
