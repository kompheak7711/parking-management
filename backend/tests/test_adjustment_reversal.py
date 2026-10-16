"""V1-056 sub-slice 10f-1: Adjustment reversal drafts refuse bad input before any connection."""

from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.adjustment_reversal import (
    AdjustmentReversalAuthorizationError,
    AdjustmentReversalConflictError,
    AdjustmentReversalInvalidError,
    AdjustmentReversalKeyReused,
    AdjustmentReversalNotFoundError,
    AdjustmentReversalService,
    AdjustmentReversalStaleDraftError,
    AdjustmentReversalUnavailableError,
    RecordAdjustmentReversalCommand,
    adjustment_reversal_draft_id,
)
from property_rental.financial_draft import (
    KIND_PREPARE_CAPABILITIES,
    PREPARE_CAPABILITIES,
    FinancialDraftKind,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant

PROPERTY = UUID(int=7)
HUMAN = UUID(int=8)


def person(*capabilities: str, actor_id: str = str(HUMAN)) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id,
        frozenset(CapabilityGrant(value, frozenset({str(PROPERTY)})) for value in capabilities),
    )


def command(**changes: object) -> RecordAdjustmentReversalCommand:
    values: dict[str, object] = {
        "idempotency_key": UUID(int=1),
        "adjustment_id": UUID(int=2),
        "reason": "The credit was recorded on the wrong Invoice",
        **changes,
    }
    return RecordAdjustmentReversalCommand(**values)  # type: ignore[arg-type]


@pytest.fixture
def no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    def connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("no database connection may be opened")

    monkeypatch.setattr(psycopg, "connect", connect)


def test_adjustment_reversal_record_and_confirm_refuse_missing_capability_before_any_connection(
    no_connection: None,
) -> None:
    del no_connection
    service = AdjustmentReversalService("unused")
    for actor in (
        person(),
        person("financial.approve"),
        person("credits.apply"),
        person("invoices.adjust", actor_id="x"),
        person("invoices.adjust", actor_id=str(UUID(int=0))),
    ):
        with pytest.raises(AdjustmentReversalAuthorizationError):
            service.record(PROPERTY, command(), actor=actor)
    for actor in (person(), person("invoices.adjust"), person("invoices.adjust", "credits.apply")):
        with pytest.raises(AdjustmentReversalAuthorizationError):
            service.confirm(PROPERTY, UUID(int=4), actor=actor)


def test_adjustment_reversal_invalid_input_is_refused_before_any_connection(
    no_connection: None,
) -> None:
    del no_connection
    service = AdjustmentReversalService("unused")
    for change in (
        {"idempotency_key": UUID(int=0)},
        {"adjustment_id": UUID(int=0)},
        {"adjustment_id": "not-a-uuid"},
        {"reason": ""},
        {"reason": " The credit was wrong"},
        {"reason": "Wrong\x00"},
        {"reason": "x" * 1001},
    ):
        with pytest.raises(AdjustmentReversalInvalidError):
            service.record(PROPERTY, command(**change), actor=person("invoices.adjust"))
    with pytest.raises(AdjustmentReversalInvalidError):
        service.confirm(PROPERTY, UUID(int=0), actor=person("financial.approve"))
    with pytest.raises(AdjustmentReversalInvalidError):
        service.record(UUID(int=0), command(), actor=person("invoices.adjust"))
    # The limit is inclusive.
    assert command(reason="x" * 1000).reason == "x" * 1000


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        ("P0002", AdjustmentReversalNotFoundError),
        ("P4501", AdjustmentReversalNotFoundError),
        ("42501", AdjustmentReversalAuthorizationError),
        ("P4506", AdjustmentReversalAuthorizationError),
        ("22023", AdjustmentReversalInvalidError),
        ("P5205", AdjustmentReversalKeyReused),
        ("P5S02", AdjustmentReversalStaleDraftError),
        ("55000", AdjustmentReversalConflictError),
        ("23514", AdjustmentReversalConflictError),
        ("23505", AdjustmentReversalConflictError),
        ("P5S01", AdjustmentReversalConflictError),
        ("40001", AdjustmentReversalConflictError),
        ("40P01", AdjustmentReversalConflictError),
        ("55P03", AdjustmentReversalConflictError),
        ("08006", AdjustmentReversalUnavailableError),
        ("57014", AdjustmentReversalUnavailableError),
    ],
)
def test_adjustment_reversal_database_failures_map_to_stable_errors(
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
        AdjustmentReversalService("unused").record(
            PROPERTY, command(), actor=person("invoices.adjust")
        )
    assert "Synthetic private diagnostic" not in str(recorded.value)
    with pytest.raises(expected):
        AdjustmentReversalService("unused").confirm(
            PROPERTY, UUID(int=4), actor=person("financial.approve")
        )


def test_adjustment_reversal_business_state_refusals_are_conflicts() -> None:
    assert issubclass(AdjustmentReversalKeyReused, AdjustmentReversalConflictError)
    assert issubclass(AdjustmentReversalStaleDraftError, AdjustmentReversalConflictError)
    assert not issubclass(AdjustmentReversalConflictError, ValueError)


def test_adjustment_reversal_draft_id_is_scoped_to_property_preparer_and_key() -> None:
    key = uuid4()
    base = adjustment_reversal_draft_id(PROPERTY, HUMAN, key)
    assert base == adjustment_reversal_draft_id(PROPERTY, HUMAN, key)
    assert base != adjustment_reversal_draft_id(UUID(int=9), HUMAN, key)
    assert base != adjustment_reversal_draft_id(PROPERTY, UUID(int=9), key)
    assert base != adjustment_reversal_draft_id(PROPERTY, HUMAN, uuid4())


def test_adjustment_reversal_drafts_are_prepared_only_under_the_adjustment_capability() -> None:
    # Owner answer 7 to Q-2026-10-06-36.
    assert KIND_PREPARE_CAPABILITIES[FinancialDraftKind.ADJUSTMENT_REVERSAL] == frozenset(
        {"invoices.adjust"}
    )
    # Nine preparer capabilities: the draft reads and the Settlement preview accept them all.
    assert len(PREPARE_CAPABILITIES) == 9
