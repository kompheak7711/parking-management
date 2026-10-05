"""V1-056 sub-slice 8a-1: the Final Settlement service refuses bad input before any connection."""

from pathlib import Path
from uuid import UUID

import psycopg
import pytest

from property_rental.final_settlement import (
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementInvalidError,
    FinalSettlementNotFoundError,
    FinalSettlementReadService,
    FinalSettlementService,
    FinalSettlementUnavailableError,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant

PROPERTY = UUID(int=7)
HUMAN = UUID(int=8)
LEASE = UUID(int=9)
SETTLEMENT = UUID(int=10)


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


def test_start_refuses_a_missing_capability_before_any_connection(no_connection: None) -> None:
    service = FinalSettlementService("unused")
    for actor in (
        person(),
        person("financial.approve"),
        person("deposits.dispose"),
        person("final_settlements.prepare", actor_id="not-a-uuid"),
        person("final_settlements.prepare", actor_id=str(UUID(int=0))),
    ):
        with pytest.raises(FinalSettlementAuthorizationError):
            service.start(PROPERTY, LEASE, actor=actor)
    other = AuthenticatedActor(
        str(HUMAN),
        frozenset({CapabilityGrant("final_settlements.prepare", frozenset({str(UUID(int=99))}))}),
    )
    with pytest.raises(FinalSettlementAuthorizationError):
        service.start(PROPERTY, LEASE, actor=other)


def test_start_refuses_invalid_identities_before_any_connection(no_connection: None) -> None:
    service = FinalSettlementService("unused")
    preparer = person("final_settlements.prepare")
    for property_id, lease_id in ((UUID(int=0), LEASE), (PROPERTY, UUID(int=0))):
        with pytest.raises(FinalSettlementInvalidError):
            service.start(property_id, lease_id, actor=preparer)
    with pytest.raises(FinalSettlementInvalidError):
        service.start(PROPERTY, "not-a-uuid", actor=preparer)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        ("P0002", FinalSettlementNotFoundError),
        ("P4501", FinalSettlementNotFoundError),
        ("42501", FinalSettlementAuthorizationError),
        ("P4506", FinalSettlementAuthorizationError),
        ("22023", FinalSettlementInvalidError),
        ("23514", FinalSettlementInvalidError),
        ("55000", FinalSettlementConflictError),
        ("55P03", FinalSettlementConflictError),
        ("40001", FinalSettlementConflictError),
        ("40P01", FinalSettlementConflictError),
        ("23505", FinalSettlementConflictError),
        ("08006", FinalSettlementUnavailableError),
        (None, FinalSettlementUnavailableError),
    ],
)
def test_final_settlement_failures_map_to_stable_errors(
    monkeypatch: pytest.MonkeyPatch, sqlstate: str | None, expected: type[Exception]
) -> None:
    class Failure(psycopg.Error):
        pass

    failure = Failure("Synthetic failure")
    failure.sqlstate = sqlstate

    def connect(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(psycopg, "connect", connect)
    with pytest.raises(expected):
        FinalSettlementService("unused").start(
            PROPERTY, LEASE, actor=person("final_settlements.prepare")
        )


def test_no_application_module_writes_deposit_applications() -> None:
    """Only the Settlement confirm (sub-slice 8e) may call the internal writer."""
    source = Path(__file__).parents[1] / "src" / "property_rental"
    for module in source.glob("*.py"):
        text = module.read_text(encoding="utf-8")
        assert "post_deposit_application" not in text, module.name
        assert "INSERT INTO app.deposit_applications" not in text, module.name


def test_preview_needs_prepare_or_approve_and_valid_identities_before_any_connection(
    no_connection: None,
) -> None:
    """V1-056 sub-slice 8b: preparers and approvers may read the preview; nobody else."""
    service = FinalSettlementReadService("unused")
    for actor in (
        person(),
        person("deposits.dispose"),
        person("invoices.read"),
        person("final_settlements.prepare", actor_id="not-a-uuid"),
        person("financial.approve", actor_id=str(UUID(int=0))),
    ):
        with pytest.raises(FinalSettlementAuthorizationError):
            service.preview(PROPERTY, SETTLEMENT, actor=actor)
    other = AuthenticatedActor(
        str(HUMAN),
        frozenset({CapabilityGrant("financial.approve", frozenset({str(UUID(int=99))}))}),
    )
    with pytest.raises(FinalSettlementAuthorizationError):
        service.preview(PROPERTY, SETTLEMENT, actor=other)
    for property_id, settlement_id in ((UUID(int=0), SETTLEMENT), (PROPERTY, UUID(int=0))):
        with pytest.raises(FinalSettlementInvalidError):
            service.preview(property_id, settlement_id, actor=person("final_settlements.prepare"))


@pytest.mark.parametrize(
    ("capabilities", "passed"),
    [
        (("final_settlements.prepare",), ["final_settlements.prepare"]),
        (("financial.approve",), ["financial.approve"]),
        (
            ("final_settlements.prepare", "refunds.create", "invoices.read"),
            ["final_settlements.prepare", "refunds.create"],
        ),
    ],
)
def test_preview_reads_read_only_through_the_runtime_url_with_the_draft_capabilities(
    monkeypatch: pytest.MonkeyPatch, capabilities: tuple[str, ...], passed: list[str]
) -> None:
    """The reader's draft capabilities decide which pending draft identities it sees."""
    calls: list[tuple[object, ...]] = []

    class Connection:
        read_only = False

        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> "Connection":
            calls.append((sql, parameters, self.read_only))
            return self

        def fetchone(self) -> tuple[dict[str, object]]:
            return ({"ready": False},)

    def connect(url: str, **kwargs: object) -> Connection:
        calls.append(("connect", url))
        return Connection()

    monkeypatch.setattr(psycopg, "connect", connect)
    result = FinalSettlementReadService("runtime-url").preview(
        PROPERTY, SETTLEMENT, actor=person(*capabilities)
    )
    assert result == {"ready": False}
    assert calls[0] == ("connect", "runtime-url")
    assert calls[-1] == (
        "SELECT app.final_settlement_preview(%s,%s,%s,%s)",
        (PROPERTY, HUMAN, SETTLEMENT, passed),
        True,
    )
    assert all(call[-1] is True for call in calls[1:])
