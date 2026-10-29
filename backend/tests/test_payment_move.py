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
    PaymentMoveStaleDraftError,
    PaymentMoveUnavailableError,
    RecordPaymentMoveCommand,
    RecordSettlementPaymentMoveCommand,
    payment_move_draft_id,
    settlement_payment_move_draft_id,
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
        "reason": "Paid on Parking 203, meant for Parking 201",
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
        {"reason": " Paid on the wrong Parking"},
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


def correction(**changes: object) -> RecordSettlementPaymentMoveCommand:
    values: dict[str, object] = {
        "idempotency_key": UUID(int=1),
        "settlement_id": UUID(int=5),
        "allocation_id": UUID(int=2),
        "target_invoice_id": UUID(int=3),
        "reason": "Paid on Parking 203, meant for Parking 201",
        "source_acknowledgement": "Dara Sok, 2026-10-16, in person at the office",
        "target_acknowledgement": "Vanna Chea, 2026-10-16, by telephone",
        **changes,
    }
    return RecordSettlementPaymentMoveCommand(**values)  # type: ignore[arg-type]


def test_payment_move_correction_needs_its_capabilities_before_any_connection(
    no_connection: None,
) -> None:
    """Sub-slice 10g: final_settlements.prepare records the correction, financial.approve
    confirms it; the slice 7 preparer capability does neither."""
    del no_connection
    service = PaymentMoveService("unused")
    for actor in (
        person(),
        person("financial.approve"),
        person("payments.allocations.reverse"),
        person("final_settlements.prepare", actor_id="x"),
    ):
        with pytest.raises(PaymentMoveAuthorizationError):
            service.record_correction(PROPERTY, correction(), actor=actor)
    for actor in (
        person(),
        person("final_settlements.prepare"),
        person("payments.allocate"),
        person("payments.allocations.reverse"),
    ):
        with pytest.raises(PaymentMoveAuthorizationError):
            service.confirm_correction(PROPERTY, UUID(int=4), actor=actor)


def test_payment_move_correction_invalid_input_is_refused_before_any_connection(
    no_connection: None,
) -> None:
    del no_connection
    service = PaymentMoveService("unused")
    for change in (
        {"idempotency_key": UUID(int=0)},
        {"settlement_id": UUID(int=0)},
        {"settlement_id": "not-a-uuid"},
        {"allocation_id": UUID(int=0)},
        {"target_invoice_id": UUID(int=0)},
        {"reason": "x" * 1001},
        {"source_acknowledgement": ""},
        {"target_acknowledgement": "x" * 2001},
    ):
        with pytest.raises(PaymentMoveInvalidError):
            service.record_correction(
                PROPERTY, correction(**change), actor=person("final_settlements.prepare")
            )
    with pytest.raises(PaymentMoveInvalidError):
        service.confirm_correction(PROPERTY, UUID(int=0), actor=person("financial.approve"))


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        ("P0002", PaymentMoveNotFoundError),
        ("42501", PaymentMoveAuthorizationError),
        ("22023", PaymentMoveInvalidError),
        ("P5205", PaymentMoveKeyReused),
        ("P5S02", PaymentMoveStaleDraftError),
        ("P5S01", PaymentMoveConflictError),
        ("55000", PaymentMoveConflictError),
        ("23514", PaymentMoveConflictError),
        ("08006", PaymentMoveUnavailableError),
    ],
)
def test_payment_move_correction_failures_map_to_stable_errors(
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
        PaymentMoveService("unused").record_correction(
            PROPERTY, correction(), actor=person("final_settlements.prepare")
        )
    with pytest.raises(expected):
        PaymentMoveService("unused").confirm_correction(
            PROPERTY, UUID(int=4), actor=person("financial.approve")
        )


def test_payment_move_correction_draft_id_is_its_own() -> None:
    """A stale correction draft is a conflict; the correction's draft id never equals the slice 7
    draft id for the same preparer and key."""
    assert issubclass(PaymentMoveStaleDraftError, PaymentMoveConflictError)
    key = uuid4()
    base = settlement_payment_move_draft_id(PROPERTY, HUMAN, key)
    assert base == settlement_payment_move_draft_id(PROPERTY, HUMAN, key)
    assert base != payment_move_draft_id(PROPERTY, HUMAN, key)
    assert base != settlement_payment_move_draft_id(UUID(int=9), HUMAN, key)
    assert base != settlement_payment_move_draft_id(PROPERTY, UUID(int=9), key)
