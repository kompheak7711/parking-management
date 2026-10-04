"""V1-056 slice 6: Lease Deposit forfeiture drafts refuse bad input before any connection."""

from datetime import date
from pathlib import Path
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
from property_rental.financial_draft import (
    PREPARE_CAPABILITIES,
    FinancialDraftConflictError,
    FinancialDraftService,
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
    RecordLeaseDepositReversalCommand,
    lease_deposit_forfeiture_draft_id,
    lease_deposit_reversal_draft_id,
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


def reversal_command() -> RecordLeaseDepositReversalCommand:
    return RecordLeaseDepositReversalCommand(
        UUID(int=1), UUID(int=2), UUID(int=3), "Wrong ground recorded", "CASE-1"
    )


def test_reversal_needs_deposits_correct_and_approval_before_any_connection(
    no_connection: None,
) -> None:
    """V1-056 sub-slice 6b: deposits.correct prepares, financial.approve confirms."""
    del no_connection
    service = LeaseDepositForfeitureService("unused")
    for actor in (
        person(),
        person("deposits.dispose"),
        person("financial.approve"),
        person("deposits.correct", actor_id="x"),
    ):
        with pytest.raises(LeaseDepositForfeitureAuthorizationError):
            service.record_reversal(PROPERTY, reversal_command(), actor=actor)
    for actor in (person(), person("deposits.dispose", "deposits.correct")):
        with pytest.raises(LeaseDepositForfeitureAuthorizationError):
            service.confirm_reversal(PROPERTY, UUID(int=2), UUID(int=4), actor=actor)
    approver = person("financial.approve")
    with pytest.raises(LeaseDepositForfeitureInvalidError):
        service.confirm_reversal(PROPERTY, UUID(int=0), UUID(int=4), actor=approver)
    with pytest.raises(LeaseDepositForfeitureInvalidError):
        service.confirm_reversal(PROPERTY, UUID(int=2), UUID(int=0), actor=approver)


def test_reversal_input_is_refused_before_any_connection(no_connection: None) -> None:
    del no_connection
    for change in (
        {"idempotency_key": UUID(int=0)},
        {"disposition_id": UUID(int=0)},
        {"reversal_id": UUID(int=0)},
        {"reversal_id": UUID(int=2)},
        {"reason": ""},
        {"reason": "x" * 501},
        {"evidence_reference": " CASE-1"},
        {"evidence_reference": "x" * 501},
    ):
        values = {
            "idempotency_key": UUID(int=1),
            "disposition_id": UUID(int=2),
            "reversal_id": UUID(int=3),
            "reason": "Wrong ground recorded",
            "evidence_reference": "CASE-1",
            **change,
        }
        with pytest.raises(LeaseDepositForfeitureInvalidError):
            RecordLeaseDepositReversalCommand(**values)  # type: ignore[arg-type]


def test_reversal_draft_id_is_scoped_and_differs_from_the_forfeiture_draft_id() -> None:
    key = uuid4()
    base = lease_deposit_reversal_draft_id(PROPERTY, HUMAN, key)
    assert base == lease_deposit_reversal_draft_id(PROPERTY, HUMAN, key)
    assert base != lease_deposit_reversal_draft_id(UUID(int=9), HUMAN, key)
    assert base != lease_deposit_reversal_draft_id(PROPERTY, UUID(int=9), key)
    assert base != lease_deposit_forfeiture_draft_id(PROPERTY, HUMAN, key)


def test_draft_reads_pass_only_the_prepare_capabilities_the_reader_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V1-056 sub-slice 6b: reads are scoped by the preparing capability, not only the kind."""
    calls: list[tuple[str, tuple[object, ...]]] = []

    class Result:
        def fetchone(self) -> tuple[object, ...]:
            return ({"items": []},)

    class Connection:
        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> Result:
            calls.append((sql, parameters))
            return Result()

    def connect(*args: object, **kwargs: object) -> Connection:
        return Connection()

    monkeypatch.setattr(psycopg, "connect", connect)
    reads = FinancialDraftService("unused", "unused")
    for actor, expected in (
        (person("deposits.dispose"), ["deposits.dispose"]),
        (person("deposits.correct"), ["deposits.correct"]),
        (person("reservation_deposits.dispose", "deposits.read"), ["reservation_deposits.dispose"]),
        (
            person("financial.approve"),
            sorted(
                {
                    "refunds.create",
                    "deposits.dispose",
                    "reservation_deposits.dispose",
                    "reservation_deposits.refund",
                    "payments.allocations.reverse",
                    "final_settlements.prepare",
                    "deposits.correct",
                }
            ),
        ),
    ):
        calls.clear()
        reads.list(PROPERTY, actor=actor)
        sql, parameters = calls[-1]
        assert "app.list_financial_drafts_by_capability(" in sql
        assert parameters[2] == expected
        calls.clear()
        reads.get(PROPERTY, UUID(int=5), actor=actor)
        sql, parameters = calls[-1]
        assert "app.financial_draft_resource_by_capability(" in sql
        assert parameters[3] == expected


def test_no_application_module_uses_the_kind_only_draft_reads() -> None:
    """The kind-only read functions stay granted (no revoke without the owner) but are unused."""
    source = Path(__file__).parents[1] / "src" / "property_rental"
    for module in source.glob("*.py"):
        text = module.read_text()
        assert "app.financial_draft_resource(" not in text, module
        assert "app.list_financial_drafts(" not in text, module


def test_capability_scoped_reads_fit_the_database_bound() -> None:
    """The read functions accept at most 7 capabilities (migration 20261019_84)."""
    assert 1 <= len(PREPARE_CAPABILITIES) <= 7


@pytest.mark.parametrize("sqlstate", ["23514", "23505"])
def test_a_refused_withdrawal_is_a_conflict_not_unavailable_storage(
    monkeypatch: pytest.MonkeyPatch, sqlstate: str
) -> None:
    """Owner answer to Q-2026-10-05-15: a refusal by a database rule reaches the user clearly."""

    class Refused(psycopg.Error):
        pass

    failure = Refused("Synthetic refusal by a decision rule")
    failure.sqlstate = sqlstate

    def connect(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(psycopg, "connect", connect)
    with pytest.raises(FinancialDraftConflictError):
        FinancialDraftService("unused", "unused").withdraw(
            PROPERTY,
            UUID(int=5),
            "Recorded by mistake",
            prepare_capability="deposits.correct",
            actor=person("deposits.correct"),
        )
