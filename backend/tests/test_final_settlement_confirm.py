"""V1-056 sub-slice 8e-3: the Final Settlement confirm checks financial.approve before any
connection and maps every database refusal to a stable error (plan note 16)."""

from uuid import UUID

import psycopg
import pytest

from property_rental.final_settlement import (
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementInvalidError,
    FinalSettlementNotFoundError,
    FinalSettlementService,
    FinalSettlementStaleDraftError,
    FinalSettlementUnavailableError,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant

PROPERTY = UUID(int=7)
HUMAN = UUID(int=8)
DRAFT = UUID(int=21)


def person(*capabilities: str, actor_id: str = str(HUMAN)) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id,
        frozenset(CapabilityGrant(value, frozenset({str(PROPERTY)})) for value in capabilities),
    )


@pytest.fixture
def no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    def connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("no database connection may be opened")

    monkeypatch.setattr(psycopg, "connect", connect)


def test_only_a_financial_approve_holder_confirms_before_any_connection(
    no_connection: None,
) -> None:
    """BR-AUTH-010: preparing a Settlement never lets a person confirm it."""
    service = FinalSettlementService("unused")
    for actor in (
        person(),
        person("final_settlements.prepare"),
        person("deposits.dispose", "refunds.create", "credits.apply"),
        person("financial.approve", actor_id="not-a-uuid"),
        person("financial.approve", actor_id=str(UUID(int=0))),
    ):
        with pytest.raises(FinalSettlementAuthorizationError):
            service.confirm(PROPERTY, DRAFT, actor=actor)
    other = AuthenticatedActor(
        str(HUMAN),
        frozenset({CapabilityGrant("financial.approve", frozenset({str(UUID(int=99))}))}),
    )
    with pytest.raises(FinalSettlementAuthorizationError):
        service.confirm(PROPERTY, DRAFT, actor=other)
    approver = person("financial.approve")
    for property_id, draft_id in ((UUID(int=0), DRAFT), (PROPERTY, UUID(int=0))):
        with pytest.raises(FinalSettlementInvalidError):
            service.confirm(property_id, draft_id, actor=approver)
    with pytest.raises(FinalSettlementInvalidError):
        service.confirm(PROPERTY, "not-a-uuid", actor=approver)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        ("P5S02", FinalSettlementStaleDraftError),
        ("23514", FinalSettlementStaleDraftError),
        ("23505", FinalSettlementStaleDraftError),
        ("P5101", FinalSettlementStaleDraftError),
        ("P5102", FinalSettlementStaleDraftError),
        ("P5104", FinalSettlementStaleDraftError),
        ("55000", FinalSettlementConflictError),
        ("P5S01", FinalSettlementConflictError),
        ("55P03", FinalSettlementConflictError),
        ("40P01", FinalSettlementConflictError),
        ("40001", FinalSettlementConflictError),
        ("42501", FinalSettlementAuthorizationError),
        ("P4506", FinalSettlementAuthorizationError),
        ("P0002", FinalSettlementNotFoundError),
        ("P4501", FinalSettlementNotFoundError),
        ("22023", FinalSettlementInvalidError),
        ("08006", FinalSettlementUnavailableError),
        (None, FinalSettlementUnavailableError),
    ],
)
def test_confirm_failures_map_to_stable_errors(
    monkeypatch: pytest.MonkeyPatch, sqlstate: str | None, expected: type[Exception]
) -> None:
    """A stale draft is a conflict the preparer resolves by preparing again; an inactive approver
    (P4506) is an authorization error; a lock or a detected deadlock is a conflict."""

    class Failure(psycopg.Error):
        pass

    failure = Failure("Synthetic failure")
    failure.sqlstate = sqlstate

    def connect(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(psycopg, "connect", connect)
    with pytest.raises(expected) as refused:
        FinalSettlementService("unused").confirm(PROPERTY, DRAFT, actor=person("financial.approve"))
    assert type(refused.value) is expected
    assert refused.value.__cause__ is failure
    if expected is FinalSettlementStaleDraftError:
        assert isinstance(refused.value, FinalSettlementConflictError)


def test_confirm_sends_the_draft_with_the_financial_approve_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []

    class Connection:
        read_only: bool | None = None

        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> "Connection":
            calls.append((sql, parameters, self.read_only))
            return self

        def fetchone(self) -> tuple[dict[str, object]]:
            return ({"result": {"closing_balance_usd_cents": 0}},)

    def connect(url: str, **kwargs: object) -> Connection:
        calls.append(("connect", url))
        return Connection()

    monkeypatch.setattr(psycopg, "connect", connect)
    result = FinalSettlementService("financial-url").confirm(
        PROPERTY, DRAFT, actor=person("financial.approve")
    )
    assert result == {"result": {"closing_balance_usd_cents": 0}}
    assert calls[0] == ("connect", "financial-url")
    assert calls[-1] == (
        "SELECT app.confirm_final_settlement_draft(%s,%s,%s,%s)",
        (PROPERTY, HUMAN, DRAFT, "financial.approve"),
        None,
    )
