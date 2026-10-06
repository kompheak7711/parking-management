"""V1-056 sub-slice 10b: the extra charge correction service checks the capability before any
connection (final_settlements.prepare records, only financial.approve confirms, BR-AUTH-010),
validates the command, and maps every database refusal to a stable error."""

from dataclasses import replace
from datetime import date, datetime
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg.types.json import Jsonb

from property_rental.final_settlement import (
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementInvalidError,
    FinalSettlementKeyReused,
    FinalSettlementNotFoundError,
    FinalSettlementStaleDraftError,
    FinalSettlementUnavailableError,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.settlement_correction import (
    ExtraChargeCategory,
    RecordExtraChargeCorrectionCommand,
    SettlementCorrectionService,
    settlement_correction_draft_id,
)

PROPERTY = UUID(int=7)
HUMAN = UUID(int=8)
DRAFT = UUID(int=21)
SETTLEMENT = UUID(int=31)
FINDING = UUID(int=41)
INVOICE = UUID(int=51)
KEY = UUID(int=61)


def person(*capabilities: str, actor_id: str = str(HUMAN)) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id,
        frozenset(CapabilityGrant(value, frozenset({str(PROPERTY)})) for value in capabilities),
    )


def command(**changes: Any) -> RecordExtraChargeCorrectionCommand:
    base = RecordExtraChargeCorrectionCommand(
        KEY,
        SETTLEMENT,
        ExtraChargeCategory.MISCELLANEOUS_CHARGES,
        "Replacement key card",
        1_500,
        "Front desk log 7",
        "The key card was missed at the Final Settlement",
    )
    return replace(base, **changes)


@pytest.fixture
def no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    def connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("no database connection may be opened")

    monkeypatch.setattr(psycopg, "connect", connect)


def test_staff_record_and_only_a_financial_approve_holder_confirms_before_any_connection(
    no_connection: None,
) -> None:
    """BR-AUTH-010: preparing a correction never lets a person confirm it, and the approver
    capability alone does not record one."""
    service = SettlementCorrectionService("unused")
    for actor in (
        person(),
        person("financial.approve"),
        person("invoices.create", "damage_charges.bill", "invoices.issue"),
        person("final_settlements.prepare", actor_id="not-a-uuid"),
    ):
        with pytest.raises(FinalSettlementAuthorizationError):
            service.record_extra_charge(PROPERTY, command(), actor=actor)
    for actor in (
        person(),
        person("final_settlements.prepare"),
        person("invoices.create", "invoices.issue", "refunds.create"),
        person("financial.approve", actor_id=str(UUID(int=0))),
    ):
        with pytest.raises(FinalSettlementAuthorizationError):
            service.confirm_extra_charge(PROPERTY, DRAFT, actor=actor)
    other = AuthenticatedActor(
        str(HUMAN),
        frozenset({CapabilityGrant("financial.approve", frozenset({str(UUID(int=99))}))}),
    )
    with pytest.raises(FinalSettlementAuthorizationError):
        service.confirm_extra_charge(PROPERTY, DRAFT, actor=other)
    with pytest.raises(FinalSettlementInvalidError):
        service.confirm_extra_charge(PROPERTY, UUID(int=0), actor=person("financial.approve"))
    with pytest.raises(FinalSettlementInvalidError):
        service.record_extra_charge(
            PROPERTY,
            "not a command",  # type: ignore[arg-type]
            actor=person("final_settlements.prepare"),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"idempotency_key": UUID(int=0)},
        {"settlement_id": "not-a-uuid"},
        {"category": "MISCELLANEOUS_CHARGES"},
        {"description": " padded"},
        {"description": "x" * 1001},
        {"amount_usd_cents": 0},
        {"amount_usd_cents": 10.5},
        {"amount_usd_cents": True},
        {"evidence_reference": ""},
        {"reason": "x" * 501},
        {"inspection_damage_finding_id": FINDING},
        {"category": ExtraChargeCategory.DAMAGE_CHARGES},
        {"corrects_invoice_id": UUID(int=0)},
        {"due_date": date(2026, 10, 30)},
        {"due_date_reason": "Agreed with the Customer"},
        {"due_date": datetime(2026, 10, 30), "due_date_reason": "Agreed with the Customer"},
        {"due_date": date(2026, 10, 30), "due_date_reason": "x" * 501},
    ],
)
def test_the_command_refuses_malformed_input(changes: dict[str, Any]) -> None:
    """BR-INV-044: a Damage charge names one finding, a Miscellaneous charge none; money in whole
    cents; the Due Date override comes with its reason; the reason fits the one-time charge record
    (500 characters)."""
    with pytest.raises(FinalSettlementInvalidError):
        command(**changes)


def test_record_sends_the_stored_charge_under_the_prepare_reference(
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
            calls.append((sql, parameters))
            return self

        def fetchone(self) -> tuple[dict[str, object]]:
            return ({"draft_id": str(DRAFT)},)

    def connect(url: str, **kwargs: object) -> Connection:
        calls.append(("connect", url))
        return Connection()

    monkeypatch.setattr(psycopg, "connect", connect)
    damage = command(
        category=ExtraChargeCategory.DAMAGE_CHARGES,
        inspection_damage_finding_id=FINDING,
        corrects_invoice_id=INVOICE,
        due_date=date(2026, 10, 30),
        due_date_reason="Agreed with the Customer",
    )
    service = SettlementCorrectionService("financial-url")
    assert service.record_extra_charge(
        PROPERTY, damage, actor=person("final_settlements.prepare")
    ) == {"draft_id": str(DRAFT)}
    assert calls[0] == ("connect", "financial-url")
    sql, parameters = calls[-1]
    assert sql == "SELECT app.record_settlement_extra_charge_draft(%s,%s,%s,%s,%s,%s,%s)"
    assert isinstance(parameters, tuple)
    assert parameters[:4] == (
        PROPERTY,
        HUMAN,
        settlement_correction_draft_id(PROPERTY, HUMAN, KEY),
        SETTLEMENT,
    )
    charge = parameters[4]
    assert isinstance(charge, Jsonb)
    assert charge.obj == {
        "category": "DAMAGE_CHARGES",
        "description": "Replacement key card",
        "amount_usd_cents": 1_500,
        "evidence_reference": "Front desk log 7",
        "inspection_damage_finding_id": str(FINDING),
        "corrects_invoice_id": str(INVOICE),
        "due_date": "2026-10-30",
        "due_date_reason": "Agreed with the Customer",
    }
    assert parameters[5:] == (
        "The key card was missed at the Final Settlement",
        "final_settlements.prepare",
    )
    # The draft id keeps the command-key scope: another preparer or key is another draft.
    assert settlement_correction_draft_id(PROPERTY, HUMAN, KEY) != (
        settlement_correction_draft_id(PROPERTY, UUID(int=9), KEY)
    )
    calls.clear()
    assert service.confirm_extra_charge(PROPERTY, DRAFT, actor=person("financial.approve")) == {
        "draft_id": str(DRAFT)
    }
    assert calls[-1] == (
        "SELECT app.confirm_settlement_extra_charge(%s,%s,%s,%s)",
        (PROPERTY, HUMAN, DRAFT, "financial.approve"),
    )


@pytest.mark.parametrize(
    ("sqlstate", "confirm_error", "record_error"),
    [
        ("P5S02", FinalSettlementStaleDraftError, FinalSettlementUnavailableError),
        ("23505", FinalSettlementConflictError, FinalSettlementConflictError),
        ("55000", FinalSettlementConflictError, FinalSettlementConflictError),
        ("P5S01", FinalSettlementConflictError, FinalSettlementConflictError),
        ("55P03", FinalSettlementConflictError, FinalSettlementConflictError),
        ("40P01", FinalSettlementConflictError, FinalSettlementConflictError),
        ("42501", FinalSettlementAuthorizationError, FinalSettlementAuthorizationError),
        ("P4506", FinalSettlementAuthorizationError, FinalSettlementAuthorizationError),
        ("P0002", FinalSettlementNotFoundError, FinalSettlementNotFoundError),
        ("22023", FinalSettlementInvalidError, FinalSettlementInvalidError),
        ("23514", FinalSettlementInvalidError, FinalSettlementInvalidError),
        ("P5205", FinalSettlementKeyReused, FinalSettlementKeyReused),
        ("08006", FinalSettlementUnavailableError, FinalSettlementUnavailableError),
        (None, FinalSettlementUnavailableError, FinalSettlementUnavailableError),
    ],
)
def test_failures_map_to_stable_errors(
    monkeypatch: pytest.MonkeyPatch,
    sqlstate: str | None,
    confirm_error: type[Exception],
    record_error: type[Exception],
) -> None:
    """A stale draft (its sources changed, for example its finding billed since) stays pending
    and is a conflict the preparer resolves by preparing again; business state and a unique
    violation are conflicts (security review round 1: 23505 is not reported as stale)."""

    class Failure(psycopg.Error):
        pass

    failure = Failure("Synthetic failure")
    failure.sqlstate = sqlstate

    def connect(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(psycopg, "connect", connect)
    service = SettlementCorrectionService("unused")
    with pytest.raises(confirm_error) as refused:
        service.confirm_extra_charge(PROPERTY, DRAFT, actor=person("financial.approve"))
    assert type(refused.value) is confirm_error and refused.value.__cause__ is failure
    if confirm_error is FinalSettlementStaleDraftError:
        assert isinstance(refused.value, FinalSettlementConflictError)
    with pytest.raises(record_error) as recorded:
        service.record_extra_charge(PROPERTY, command(), actor=person("final_settlements.prepare"))
    assert type(recorded.value) is record_error and recorded.value.__cause__ is failure
