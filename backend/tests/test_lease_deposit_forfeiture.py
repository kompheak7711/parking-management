"""V1-056 slice 6: Lease Deposit forfeiture drafts refuse bad input before any connection."""

from datetime import date
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.deposit import (
    DepositAuthorizationError,
    LeaseDepositDraftRequired,
    PostgresDepositService,
    RecordDepositDispositionCommand,
    ReverseDepositDispositionCommand,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease_deposit_forfeiture import (
    LeaseDepositForfeitureAuthorizationError,
    LeaseDepositForfeitureConflictError,
    LeaseDepositForfeitureInvalidError,
    LeaseDepositForfeitureKeyReused,
    LeaseDepositForfeitureNotFoundError,
    LeaseDepositForfeitureService,
    LeaseDepositForfeitureUnavailableError,
    RecordLeaseDepositForfeitureCommand,
    lease_deposit_forfeiture_draft_id,
)

PROPERTY = UUID(int=7)
HUMAN = UUID(int=8)


def person(*capabilities: str, actor_id: str = str(HUMAN)) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id,
        frozenset(CapabilityGrant(value, frozenset({str(PROPERTY)})) for value in capabilities),
    )


def command() -> RecordLeaseDepositForfeitureCommand:
    return RecordLeaseDepositForfeitureCommand(UUID(int=1), UUID(int=2), UUID(int=3), "Left early")


@pytest.fixture
def no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    def connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("no database connection may be opened")

    monkeypatch.setattr(psycopg, "connect", connect)


def test_record_and_confirm_refuse_missing_capability_before_any_connection(
    no_connection: None,
) -> None:
    del no_connection
    service = LeaseDepositForfeitureService("unused")
    for actor in (person(), person("financial.approve"), person("deposits.dispose", actor_id="x")):
        with pytest.raises(LeaseDepositForfeitureAuthorizationError):
            service.record(PROPERTY, command(), actor=actor)
    for actor in (person(), person("deposits.dispose")):
        with pytest.raises(LeaseDepositForfeitureAuthorizationError):
            service.confirm(PROPERTY, UUID(int=2), UUID(int=4), actor=actor)
    with pytest.raises(LeaseDepositForfeitureAuthorizationError):
        service.record(
            PROPERTY, command(), actor=person("deposits.dispose", actor_id=str(UUID(int=0)))
        )


def test_invalid_input_is_refused_before_any_connection(no_connection: None) -> None:
    del no_connection
    service = LeaseDepositForfeitureService("unused")
    for change in (
        {"idempotency_key": UUID(int=0)},
        {"deposit_id": UUID(int=0)},
        {"disposition_id": UUID(int=0)},
        {"reason": ""},
        {"reason": " Left early"},
        {"reason": "x" * 1001},
        {"reason": "Left\x00early"},
    ):
        values = {
            "idempotency_key": UUID(int=1),
            "deposit_id": UUID(int=2),
            "disposition_id": UUID(int=3),
            "reason": "Left early",
            **change,
        }
        with pytest.raises(LeaseDepositForfeitureInvalidError):
            RecordLeaseDepositForfeitureCommand(**values)  # type: ignore[arg-type]
    approver = person("financial.approve")
    with pytest.raises(LeaseDepositForfeitureInvalidError):
        service.confirm(PROPERTY, UUID(int=0), UUID(int=4), actor=approver)
    with pytest.raises(LeaseDepositForfeitureInvalidError):
        service.confirm(PROPERTY, UUID(int=2), UUID(int=0), actor=approver)
    with pytest.raises(LeaseDepositForfeitureInvalidError):
        service.record(UUID(int=0), command(), actor=person("deposits.dispose"))


def test_one_call_lease_disposition_and_reversal_refuse_before_any_connection(
    no_connection: None,
) -> None:
    del no_connection
    service = PostgresDepositService("unused", PROPERTY, HUMAN)
    disposition = RecordDepositDispositionCommand(
        UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4), 100, date(2027, 1, 1), "Approved"
    )
    reversal = ReverseDepositDispositionCommand(
        UUID(int=1), UUID(int=2), UUID(int=3), "Correct evidence", "CASE-1"
    )
    holder = person("deposits.dispose", "deposits.correct")
    with pytest.raises(LeaseDepositDraftRequired, match="forfeiture draft required"):
        service.record_disposition(disposition, actor=holder)
    with pytest.raises(LeaseDepositDraftRequired, match="reversal draft required"):
        service.reverse_disposition(reversal, actor=holder)
    with pytest.raises(DepositAuthorizationError):
        service.record_disposition(disposition, actor=person())
    with pytest.raises(DepositAuthorizationError):
        service.reverse_disposition(reversal, actor=person())


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        ("P0002", LeaseDepositForfeitureNotFoundError),
        ("P4501", LeaseDepositForfeitureNotFoundError),
        ("42501", LeaseDepositForfeitureAuthorizationError),
        ("P4506", LeaseDepositForfeitureAuthorizationError),
        ("22023", LeaseDepositForfeitureInvalidError),
        ("23514", LeaseDepositForfeitureInvalidError),
        ("P5205", LeaseDepositForfeitureKeyReused),
        ("55000", LeaseDepositForfeitureConflictError),
        ("23505", LeaseDepositForfeitureConflictError),
        ("23P01", LeaseDepositForfeitureConflictError),
        ("P5801", LeaseDepositForfeitureConflictError),
        ("40001", LeaseDepositForfeitureConflictError),
        ("XX000", LeaseDepositForfeitureUnavailableError),
    ],
)
def test_database_failures_map_to_stable_errors(
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
        LeaseDepositForfeitureService("unused").record(
            PROPERTY, command(), actor=person("deposits.dispose")
        )


def test_draft_id_is_scoped_to_property_preparer_and_key() -> None:
    key = uuid4()
    base = lease_deposit_forfeiture_draft_id(PROPERTY, HUMAN, key)
    assert base == lease_deposit_forfeiture_draft_id(PROPERTY, HUMAN, key)
    assert base != lease_deposit_forfeiture_draft_id(UUID(int=9), HUMAN, key)
    assert base != lease_deposit_forfeiture_draft_id(PROPERTY, UUID(int=9), key)
    assert base != lease_deposit_forfeiture_draft_id(PROPERTY, HUMAN, uuid4())
