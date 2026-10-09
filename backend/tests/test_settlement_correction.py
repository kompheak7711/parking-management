"""V1-056 sub-slices 10b, 10c-1a and 10c-1b: the extra charge, charge reduction and Refund
correction services check the capability before any connection (final_settlements.prepare records,
only financial.approve confirms, BR-AUTH-010), validate the command, and map every database refusal
to a stable error."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone, tzinfo
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
    RecordChargeReductionCorrectionCommand,
    RecordExtraChargeCorrectionCommand,
    RecordForfeitureReversalCorrectionCommand,
    RecordHeldValueRefundCorrectionCommand,
    RecordLateChargeReductionCorrectionCommand,
    RecordLateChargeRefundCorrectionCommand,
    RecordPetClassificationCorrectionCommand,
    RecordRefundCorrectionCommand,
    RecordRefundReturnCorrectionCommand,
    SettlementCorrectionService,
    settlement_correction_draft_id,
)

PROPERTY = UUID(int=7)
HUMAN = UUID(int=8)
DRAFT = UUID(int=21)
SETTLEMENT = UUID(int=31)
FINDING = UUID(int=41)
INVOICE = UUID(int=51)
LINE = UUID(int=52)
KEY = UUID(int=61)
METHOD = UUID(int=71)


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


def reduction(**changes: Any) -> RecordChargeReductionCorrectionCommand:
    base = RecordChargeReductionCorrectionCommand(
        KEY,
        SETTLEMENT,
        INVOICE,
        LINE,
        2_500,
        "The window latch was charged at the wrong amount",
    )
    return replace(base, **changes)


def test_a_charge_reduction_is_recorded_by_staff_and_confirmed_only_by_an_approver(
    no_connection: None,
) -> None:
    """BR-AUTH-010 (sub-slice 10c-1a): final_settlements.prepare records a charge reduction and
    only financial.approve confirms it, before any connection; the Adjustment capability alone
    does neither."""
    service = SettlementCorrectionService("unused")
    for actor in (
        person(),
        person("financial.approve"),
        person("invoices.adjust", "invoices.void"),
        person("final_settlements.prepare", actor_id="not-a-uuid"),
    ):
        with pytest.raises(FinalSettlementAuthorizationError):
            service.record_charge_reduction(PROPERTY, reduction(), actor=actor)
    for actor in (
        person(),
        person("final_settlements.prepare"),
        person("invoices.adjust"),
        person("financial.approve", actor_id=str(UUID(int=0))),
    ):
        with pytest.raises(FinalSettlementAuthorizationError):
            service.confirm_charge_reduction(PROPERTY, DRAFT, actor=actor)
    with pytest.raises(FinalSettlementInvalidError):
        service.confirm_charge_reduction(PROPERTY, UUID(int=0), actor=person("financial.approve"))
    with pytest.raises(FinalSettlementInvalidError):
        service.record_charge_reduction(
            PROPERTY,
            command(),  # type: ignore[arg-type]
            actor=person("final_settlements.prepare"),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"idempotency_key": UUID(int=0)},
        {"settlement_id": "not-a-uuid"},
        {"invoice_id": UUID(int=0)},
        {"invoice_line_id": str(LINE)},
        {"amount_usd_cents": 0},
        {"amount_usd_cents": -1},
        {"amount_usd_cents": 25.0},
        {"amount_usd_cents": True},
        {"amount_usd_cents": 9_000_000_000_000_001},
        {"reason": ""},
        {"reason": " padded"},
        {"reason": "x" * 501},
    ],
)
def test_the_charge_reduction_command_refuses_malformed_input(changes: dict[str, Any]) -> None:
    """Money in whole positive cents within the cap; the reason fits the Adjustment (500)."""
    with pytest.raises(FinalSettlementInvalidError):
        reduction(**changes)


def test_charge_reduction_record_and_confirm_send_the_stored_reduction(
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
    service = SettlementCorrectionService("financial-url")
    assert service.record_charge_reduction(
        PROPERTY, reduction(), actor=person("final_settlements.prepare")
    ) == {"draft_id": str(DRAFT)}
    assert calls[0] == ("connect", "financial-url")
    sql, parameters = calls[-1]
    assert sql == "SELECT app.record_settlement_charge_reduction_draft(%s,%s,%s,%s,%s,%s,%s)"
    assert isinstance(parameters, tuple)
    assert parameters[:4] == (
        PROPERTY,
        HUMAN,
        settlement_correction_draft_id(PROPERTY, HUMAN, KEY),
        SETTLEMENT,
    )
    stored = parameters[4]
    assert isinstance(stored, Jsonb)
    assert stored.obj == {
        "invoice_id": str(INVOICE),
        "invoice_line_id": str(LINE),
        "amount_usd_cents": 2_500,
    }
    assert parameters[5:] == (
        "The window latch was charged at the wrong amount",
        "final_settlements.prepare",
    )
    calls.clear()
    assert service.confirm_charge_reduction(PROPERTY, DRAFT, actor=person("financial.approve")) == {
        "draft_id": str(DRAFT)
    }
    assert calls[-1] == (
        "SELECT app.confirm_settlement_charge_reduction(%s,%s,%s,%s)",
        (PROPERTY, HUMAN, DRAFT, "financial.approve"),
    )


@pytest.mark.parametrize(
    ("sqlstate", "confirm_error", "record_error"),
    [
        ("P5S02", FinalSettlementStaleDraftError, FinalSettlementUnavailableError),
        ("23505", FinalSettlementConflictError, FinalSettlementConflictError),
        ("55000", FinalSettlementConflictError, FinalSettlementConflictError),
        ("P5S01", FinalSettlementConflictError, FinalSettlementConflictError),
        ("40P01", FinalSettlementConflictError, FinalSettlementConflictError),
        ("42501", FinalSettlementAuthorizationError, FinalSettlementAuthorizationError),
        ("P4506", FinalSettlementAuthorizationError, FinalSettlementAuthorizationError),
        ("P0002", FinalSettlementNotFoundError, FinalSettlementNotFoundError),
        ("22023", FinalSettlementInvalidError, FinalSettlementInvalidError),
        ("23514", FinalSettlementInvalidError, FinalSettlementInvalidError),
        ("P5205", FinalSettlementKeyReused, FinalSettlementKeyReused),
        (None, FinalSettlementUnavailableError, FinalSettlementUnavailableError),
    ],
)
def test_charge_reduction_failures_map_to_stable_errors(
    monkeypatch: pytest.MonkeyPatch,
    sqlstate: str | None,
    confirm_error: type[Exception],
    record_error: type[Exception],
) -> None:
    """A reduction whose line changed since the draft is stale and stays pending; a release of
    paid value, an open Settlement or a Deposit application is a conflict."""

    class Failure(psycopg.Error):
        pass

    failure = Failure("Synthetic failure")
    failure.sqlstate = sqlstate

    def connect(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(psycopg, "connect", connect)
    service = SettlementCorrectionService("unused")
    with pytest.raises(confirm_error) as refused:
        service.confirm_charge_reduction(PROPERTY, DRAFT, actor=person("financial.approve"))
    assert type(refused.value) is confirm_error and refused.value.__cause__ is failure
    with pytest.raises(record_error) as recorded:
        service.record_charge_reduction(
            PROPERTY, reduction(), actor=person("final_settlements.prepare")
        )
    assert type(recorded.value) is record_error and recorded.value.__cause__ is failure


def refund(**changes: Any) -> RecordRefundCorrectionCommand:
    base = RecordRefundCorrectionCommand(
        KEY,
        SETTLEMENT,
        INVOICE,
        LINE,
        2_500,
        METHOD,
        "Cash handed over at the front desk",
        "The window latch was charged twice and paid",
    )
    return replace(base, **changes)


def test_a_refund_correction_is_recorded_by_staff_and_confirmed_only_by_an_approver(
    no_connection: None,
) -> None:
    """BR-AUTH-010 (sub-slice 10c-1b): final_settlements.prepare records a Refund correction and
    only financial.approve confirms it, before any connection; the Refund or Adjustment
    capabilities alone do neither."""
    service = SettlementCorrectionService("unused")
    for actor in (
        person(),
        person("financial.approve"),
        person("refunds.create", "invoices.adjust"),
        person("final_settlements.prepare", actor_id="not-a-uuid"),
    ):
        with pytest.raises(FinalSettlementAuthorizationError):
            service.record_refund(PROPERTY, refund(), actor=actor)
    for actor in (
        person(),
        person("final_settlements.prepare"),
        person("refunds.create", "invoices.adjust"),
        person("financial.approve", actor_id=str(UUID(int=0))),
    ):
        with pytest.raises(FinalSettlementAuthorizationError):
            service.confirm_refund(PROPERTY, DRAFT, actor=actor)
    with pytest.raises(FinalSettlementInvalidError):
        service.confirm_refund(PROPERTY, UUID(int=0), actor=person("financial.approve"))
    with pytest.raises(FinalSettlementInvalidError):
        service.record_refund(
            PROPERTY,
            reduction(),  # type: ignore[arg-type]
            actor=person("final_settlements.prepare"),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"idempotency_key": UUID(int=0)},
        {"settlement_id": "not-a-uuid"},
        {"invoice_id": UUID(int=0)},
        {"invoice_line_id": str(LINE)},
        {"amount_usd_cents": 0},
        {"amount_usd_cents": -1},
        {"amount_usd_cents": 25.0},
        {"amount_usd_cents": True},
        {"amount_usd_cents": 9_000_000_000_000_001},
        {"refund_method_id": None},
        {"refund_method_id": UUID(int=0)},
        {"reference_note": ""},
        {"reference_note": "padded "},
        {"reference_note": "x" * 501},
        {"reference_note": "nul\x00"},
        {"reason": ""},
        {"reason": " padded"},
        {"reason": "x" * 501},
    ],
)
def test_the_refund_correction_command_refuses_malformed_input(changes: dict[str, Any]) -> None:
    """Money in whole positive cents within the cap; a Refund method and a reference note of at
    most 500 characters (BR-REFUND-014); the reason fits the Adjustment (500)."""
    with pytest.raises(FinalSettlementInvalidError):
        refund(**changes)


def test_refund_correction_record_and_confirm_send_the_stored_correction(
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
    service = SettlementCorrectionService("financial-url")
    assert service.record_refund(PROPERTY, refund(), actor=person("final_settlements.prepare")) == {
        "draft_id": str(DRAFT)
    }
    assert calls[0] == ("connect", "financial-url")
    sql, parameters = calls[-1]
    assert sql == "SELECT app.record_settlement_refund_draft(%s,%s,%s,%s,%s,%s,%s)"
    assert isinstance(parameters, tuple)
    assert parameters[:4] == (
        PROPERTY,
        HUMAN,
        settlement_correction_draft_id(PROPERTY, HUMAN, KEY),
        SETTLEMENT,
    )
    stored = parameters[4]
    assert isinstance(stored, Jsonb)
    # Narrowed (V1-056 sub-slice 10c-2a-3): the request also carries the DL-032 plan, empty here.
    assert stored.obj == {
        "invoice_id": str(INVOICE),
        "invoice_line_id": str(LINE),
        "amount_usd_cents": 2_500,
        "refund_method_id": str(METHOD),
        "reference_note": "Cash handed over at the front desk",
        "plan": {"steps": [], "pet_remainder": None},
    }
    assert parameters[5:] == (
        "The window latch was charged twice and paid",
        "final_settlements.prepare",
    )
    calls.clear()
    assert service.confirm_refund(PROPERTY, DRAFT, actor=person("financial.approve")) == {
        "draft_id": str(DRAFT)
    }
    assert calls[-1] == (
        "SELECT app.confirm_settlement_refund(%s,%s,%s,%s)",
        (PROPERTY, HUMAN, DRAFT, "financial.approve"),
    )


@pytest.mark.parametrize(
    ("sqlstate", "confirm_error", "record_error"),
    [
        ("P5S02", FinalSettlementStaleDraftError, FinalSettlementUnavailableError),
        ("23505", FinalSettlementConflictError, FinalSettlementConflictError),
        ("55000", FinalSettlementConflictError, FinalSettlementConflictError),
        ("P5S01", FinalSettlementConflictError, FinalSettlementConflictError),
        ("40P01", FinalSettlementConflictError, FinalSettlementConflictError),
        ("42501", FinalSettlementAuthorizationError, FinalSettlementAuthorizationError),
        ("P4506", FinalSettlementAuthorizationError, FinalSettlementAuthorizationError),
        ("P0002", FinalSettlementNotFoundError, FinalSettlementNotFoundError),
        ("22023", FinalSettlementInvalidError, FinalSettlementInvalidError),
        ("23514", FinalSettlementInvalidError, FinalSettlementInvalidError),
        ("P5205", FinalSettlementKeyReused, FinalSettlementKeyReused),
        (None, FinalSettlementUnavailableError, FinalSettlementUnavailableError),
    ],
)
def test_refund_correction_failures_map_to_stable_errors(
    monkeypatch: pytest.MonkeyPatch,
    sqlstate: str | None,
    confirm_error: type[Exception],
    record_error: type[Exception],
) -> None:
    """A Refund correction whose line or sources changed since the draft is stale and stays
    pending; nothing released, an inactive Refund method, an open Settlement or a Deposit
    application is a conflict."""

    class Failure(psycopg.Error):
        pass

    failure = Failure("Synthetic failure")
    failure.sqlstate = sqlstate

    def connect(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(psycopg, "connect", connect)
    service = SettlementCorrectionService("unused")
    with pytest.raises(confirm_error) as refused:
        service.confirm_refund(PROPERTY, DRAFT, actor=person("financial.approve"))
    assert type(refused.value) is confirm_error and refused.value.__cause__ is failure
    with pytest.raises(record_error) as recorded:
        service.record_refund(PROPERTY, refund(), actor=person("final_settlements.prepare"))
    assert type(recorded.value) is record_error and recorded.value.__cause__ is failure


def classification(**changes: Any) -> RecordPetClassificationCorrectionCommand:
    return replace(
        RecordPetClassificationCorrectionCommand(
            KEY,
            SETTLEMENT,
            INVOICE,
            LINE,
            False,
            "Vet letter 12",
            "The pet did not break the window latch",
        ),
        **changes,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"pet_related": 1},
        {"pet_related": None},
        {"evidence_reference": ""},
        {"evidence_reference": "x" * 501},
        {"reason": "x" * 501},
        {"invoice_line_id": "not-a-uuid"},
        {"steps": ["not a step"]},
        {"pet_remainder": "staff"},
    ],
)
def test_pet_classification_correction_commands_are_validated(changes: dict[str, Any]) -> None:
    """V1-056 sub-slice 10c-2a-5: the corrected classification is true or false; the evidence
    reference and the reason fit the classification record; the plan has typed steps."""
    with pytest.raises(FinalSettlementInvalidError):
        classification(**changes)


def test_pet_classification_correction_record_and_confirm_send_the_stored_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The record call carries the line, the corrected classification, the evidence and the
    DL-032 plan; only final_settlements.prepare records and only financial.approve confirms."""
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
    service = SettlementCorrectionService("financial-url")
    with pytest.raises(FinalSettlementAuthorizationError):
        service.record_pet_classification(
            PROPERTY, classification(), actor=person("financial.approve")
        )
    with pytest.raises(FinalSettlementAuthorizationError):
        service.confirm_pet_classification(
            PROPERTY, DRAFT, actor=person("final_settlements.prepare")
        )
    assert calls == []
    assert service.record_pet_classification(
        PROPERTY, classification(), actor=person("final_settlements.prepare")
    ) == {"draft_id": str(DRAFT)}
    assert calls[0] == ("connect", "financial-url")
    sql, parameters = calls[-1]
    assert sql == "SELECT app.record_settlement_pet_classification_draft(%s,%s,%s,%s,%s,%s,%s)"
    assert isinstance(parameters, tuple)
    assert parameters[:4] == (
        PROPERTY,
        HUMAN,
        settlement_correction_draft_id(PROPERTY, HUMAN, KEY),
        SETTLEMENT,
    )
    stored = parameters[4]
    assert isinstance(stored, Jsonb)
    assert stored.obj == {
        "invoice_id": str(INVOICE),
        "invoice_line_id": str(LINE),
        "pet_related": False,
        "evidence_reference": "Vet letter 12",
        "plan": {"steps": [], "pet_remainder": None},
    }
    assert parameters[5:] == (
        "The pet did not break the window latch",
        "final_settlements.prepare",
    )
    calls.clear()
    assert service.confirm_pet_classification(
        PROPERTY, DRAFT, actor=person("financial.approve")
    ) == {"draft_id": str(DRAFT)}
    assert calls[-1] == (
        "SELECT app.confirm_settlement_pet_classification(%s,%s,%s,%s)",
        (PROPERTY, HUMAN, DRAFT, "financial.approve"),
    )


@pytest.mark.parametrize(
    ("sqlstate", "confirm_error"),
    [
        ("P5S02", FinalSettlementStaleDraftError),
        ("55000", FinalSettlementConflictError),
        ("40P01", FinalSettlementConflictError),
        ("42501", FinalSettlementAuthorizationError),
        ("P0002", FinalSettlementNotFoundError),
        ("22023", FinalSettlementInvalidError),
        (None, FinalSettlementUnavailableError),
    ],
)
def test_pet_classification_correction_confirm_maps_database_refusals(
    monkeypatch: pytest.MonkeyPatch, sqlstate: str | None, confirm_error: type[Exception]
) -> None:
    """A draft whose sources changed is stale and stays pending; other refusals keep the Final
    Settlement error mapping."""

    class Failure(psycopg.Error):
        pass

    failure = Failure("Synthetic failure")
    failure.sqlstate = sqlstate

    def connect(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(psycopg, "connect", connect)
    with pytest.raises(confirm_error) as refused:
        SettlementCorrectionService("unused").confirm_pet_classification(
            PROPERTY, DRAFT, actor=person("financial.approve")
        )
    assert type(refused.value) is confirm_error and refused.value.__cause__ is failure


REFUND = UUID(int=81)
RETURNED_AT = datetime.fromisoformat("2026-10-08T09:30:00+07:00")


def refund_return(**changes: Any) -> RecordRefundReturnCorrectionCommand:
    return replace(
        RecordRefundReturnCorrectionCommand(
            KEY,
            SETTLEMENT,
            REFUND,
            1_200,
            RETURNED_AT,
            "Bank transfer came back, reference BT-77",
            "Bank statement line 4",
            "The Refund transfer was returned by the bank",
            METHOD,
            "Cash handed over at the front desk",
        ),
        **changes,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"refund_id": UUID(int=0)},
        {"returned_amount_usd_cents": 0},
        {"returned_amount_usd_cents": 1.5},
        {"returned_amount_usd_cents": True},
        {"returned_at": datetime(2026, 10, 8, 9, 30)},
        {"returned_at": "2026-10-08T09:30:00+07:00"},
        {"return_method_reference": " padded"},
        {"evidence_reference": "x" * 501},
        {"reason": ""},
        {"new_refund_method_id": None},
        {"new_refund_reference_note": None},
        {"new_refund_reference_note": "x" * 501},
        {"steps": ["not a step"]},
        {"pet_remainder": "staff"},
    ],
)
def test_refund_return_correction_commands_are_validated(changes: dict[str, Any]) -> None:
    """V1-056 sub-slice 10c-2b-1: a positive returned amount in cents, a timezone-aware return
    date, the return references and the reason fit the verified return; a new Refund needs both
    its method and its note; the plan has typed steps."""
    with pytest.raises(FinalSettlementInvalidError):
        refund_return(**changes)


class BrokenOffset(tzinfo):
    """A tzinfo whose offset cannot be read."""

    def utcoffset(self, value: datetime | None) -> timedelta:
        raise ValueError("Synthetic broken offset")

    def dst(self, value: datetime | None) -> timedelta:
        return timedelta(0)

    def tzname(self, value: datetime | None) -> str:
        return "Broken"


@pytest.mark.parametrize(
    "instant",
    [
        datetime.min.replace(tzinfo=timezone(timedelta(hours=1))),
        datetime.max.replace(tzinfo=timezone(timedelta(hours=-1))),
        datetime(2026, 10, 8, 9, 30, tzinfo=BrokenOffset()),
    ],
)
def test_a_refund_return_correction_refuses_an_instant_without_a_utc_form(
    instant: datetime,
) -> None:
    """V1-056 sub-slice 10c-2b-2b (10c-2b-1 review round 3 note): an aware return date at the edge
    of the date range, or one whose tzinfo raises, is invalid input, as refund.py _instant."""
    with pytest.raises(FinalSettlementInvalidError):
        refund_return(returned_at=instant)


def test_refund_return_correction_record_and_confirm_send_the_stored_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The record call carries the Refund, the returned amount, the return date and references,
    the new Refund and the DL-032 plan; a return-only draft sends no new Refund; only
    final_settlements.prepare records and only financial.approve confirms."""
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
    service = SettlementCorrectionService("financial-url")
    with pytest.raises(FinalSettlementAuthorizationError):
        service.record_refund_return(PROPERTY, refund_return(), actor=person("financial.approve"))
    with pytest.raises(FinalSettlementAuthorizationError):
        service.confirm_refund_return(PROPERTY, DRAFT, actor=person("final_settlements.prepare"))
    assert calls == []
    assert service.record_refund_return(
        PROPERTY, refund_return(), actor=person("final_settlements.prepare")
    ) == {"draft_id": str(DRAFT)}
    assert calls[0] == ("connect", "financial-url")
    sql, parameters = calls[-1]
    assert sql == "SELECT app.record_settlement_refund_return_draft(%s,%s,%s,%s,%s,%s,%s)"
    assert isinstance(parameters, tuple)
    assert parameters[:4] == (
        PROPERTY,
        HUMAN,
        settlement_correction_draft_id(PROPERTY, HUMAN, KEY),
        SETTLEMENT,
    )
    stored = parameters[4]
    assert isinstance(stored, Jsonb)
    assert stored.obj == {
        "refund_id": str(REFUND),
        "returned_amount_usd_cents": 1_200,
        "returned_at": "2026-10-08T02:30:00+00:00",
        "return_method_reference": "Bank transfer came back, reference BT-77",
        "evidence_reference": "Bank statement line 4",
        "new_refund": {
            "refund_method_id": str(METHOD),
            "reference_note": "Cash handed over at the front desk",
        },
        "plan": {"steps": [], "pet_remainder": None},
    }
    assert parameters[5:] == (
        "The Refund transfer was returned by the bank",
        "final_settlements.prepare",
    )
    service.record_refund_return(
        PROPERTY,
        refund_return(
            new_refund_method_id=None,
            new_refund_reference_note=None,
            returned_at=datetime.fromisoformat("2026-10-08T20:00:00+16:00"),
        ),
        actor=person("final_settlements.prepare"),
    )
    only_return = calls[-1][1]
    assert isinstance(only_return, tuple) and isinstance(only_return[4], Jsonb)
    assert only_return[4].obj["new_refund"] is None
    # Sent in UTC, so an offset PostgreSQL would refuse never reaches it (review round 1).
    assert only_return[4].obj["returned_at"] == "2026-10-08T04:00:00+00:00"
    calls.clear()
    assert service.confirm_refund_return(PROPERTY, DRAFT, actor=person("financial.approve")) == {
        "draft_id": str(DRAFT)
    }
    assert calls[-1] == (
        "SELECT app.confirm_settlement_refund_return(%s,%s,%s,%s)",
        (PROPERTY, HUMAN, DRAFT, "financial.approve"),
    )


@pytest.mark.parametrize(
    ("sqlstate", "confirm_error"),
    [
        ("P5S02", FinalSettlementStaleDraftError),
        ("55000", FinalSettlementConflictError),
        ("40P01", FinalSettlementConflictError),
        ("42501", FinalSettlementAuthorizationError),
        ("P0002", FinalSettlementNotFoundError),
        ("22023", FinalSettlementInvalidError),
        (None, FinalSettlementUnavailableError),
    ],
)
def test_refund_return_correction_confirm_maps_database_refusals(
    monkeypatch: pytest.MonkeyPatch, sqlstate: str | None, confirm_error: type[Exception]
) -> None:
    """A draft whose Refund or Credit changed is stale and stays pending; other refusals keep the
    Final Settlement error mapping."""

    class Failure(psycopg.Error):
        pass

    failure = Failure("Synthetic failure")
    failure.sqlstate = sqlstate

    def connect(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(psycopg, "connect", connect)
    with pytest.raises(confirm_error) as refused:
        SettlementCorrectionService("unused").confirm_refund_return(
            PROPERTY, DRAFT, actor=person("financial.approve")
        )
    assert type(refused.value) is confirm_error and refused.value.__cause__ is failure


EARLIER = UUID(int=91)


def held_value(**changes: Any) -> RecordHeldValueRefundCorrectionCommand:
    return replace(
        RecordHeldValueRefundCorrectionCommand(
            KEY,
            SETTLEMENT,
            EARLIER,
            "The returned Refund is paid out again",
            METHOD,
            "Cash handed over at the front desk",
        ),
        **changes,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"held_from_correction_id": UUID(int=0)},
        {"held_from_correction_id": "not-a-uuid"},
        {"reason": ""},
        {"reason": "x" * 501},
        {"new_refund_method_id": None},
        {"new_refund_reference_note": " padded"},
        {"new_refund_reference_note": "x" * 501},
        {"steps": ["not a step"]},
        {"steps": []},
        {"pet_remainder": "staff"},
    ],
)
def test_held_value_refund_correction_commands_are_validated(changes: dict[str, Any]) -> None:
    """V1-056 sub-slice 10c-2b-3: the earlier correction, a reason, the new Refund's method and
    reference note (both required) and a tuple of typed plan steps."""
    with pytest.raises(FinalSettlementInvalidError):
        held_value(**changes)


def test_held_value_refund_correction_record_and_confirm_send_the_stored_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The record call carries the earlier correction, the new Refund and the DL-032 plan; only
    final_settlements.prepare records and only financial.approve confirms."""
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
    service = SettlementCorrectionService("financial-url")
    with pytest.raises(FinalSettlementAuthorizationError):
        service.record_held_value_refund(PROPERTY, held_value(), actor=person("financial.approve"))
    with pytest.raises(FinalSettlementAuthorizationError):
        service.confirm_held_value_refund(
            PROPERTY, DRAFT, actor=person("final_settlements.prepare")
        )
    assert calls == []
    assert service.record_held_value_refund(
        PROPERTY, held_value(), actor=person("final_settlements.prepare")
    ) == {"draft_id": str(DRAFT)}
    sql, parameters = calls[-1]
    assert sql == "SELECT app.record_settlement_held_value_refund_draft(%s,%s,%s,%s,%s,%s,%s)"
    assert isinstance(parameters, tuple)
    assert parameters[:4] == (
        PROPERTY,
        HUMAN,
        settlement_correction_draft_id(PROPERTY, HUMAN, KEY),
        SETTLEMENT,
    )
    stored = parameters[4]
    assert isinstance(stored, Jsonb)
    assert stored.obj == {
        "held_from_settlement_correction_id": str(EARLIER),
        "new_refund": {
            "refund_method_id": str(METHOD),
            "reference_note": "Cash handed over at the front desk",
        },
        "plan": {"steps": [], "pet_remainder": None},
    }
    assert parameters[5:] == (
        "The returned Refund is paid out again",
        "final_settlements.prepare",
    )
    calls.clear()
    assert service.confirm_held_value_refund(
        PROPERTY, DRAFT, actor=person("financial.approve")
    ) == {"draft_id": str(DRAFT)}
    assert calls[-1] == (
        "SELECT app.confirm_settlement_held_value_refund(%s,%s,%s,%s)",
        (PROPERTY, HUMAN, DRAFT, "financial.approve"),
    )


@pytest.mark.parametrize(
    ("sqlstate", "confirm_error"),
    [
        ("P5S02", FinalSettlementStaleDraftError),
        ("55000", FinalSettlementConflictError),
        ("42501", FinalSettlementAuthorizationError),
        ("P0002", FinalSettlementNotFoundError),
        ("22023", FinalSettlementInvalidError),
        (None, FinalSettlementUnavailableError),
    ],
)
def test_held_value_refund_correction_confirm_maps_database_refusals(
    monkeypatch: pytest.MonkeyPatch, sqlstate: str | None, confirm_error: type[Exception]
) -> None:
    """A draft whose earlier correction, Credit or Deposit changed is stale and stays pending;
    other refusals keep the Final Settlement error mapping."""

    class Failure(psycopg.Error):
        pass

    failure = Failure("Synthetic failure")
    failure.sqlstate = sqlstate

    def connect(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(psycopg, "connect", connect)
    with pytest.raises(confirm_error) as refused:
        SettlementCorrectionService("unused").confirm_held_value_refund(
            PROPERTY, DRAFT, actor=person("financial.approve")
        )
    assert type(refused.value) is confirm_error and refused.value.__cause__ is failure


DISPOSITION = UUID(int=92)


def forfeiture_reversal(**changes: Any) -> RecordForfeitureReversalCorrectionCommand:
    return replace(
        RecordForfeitureReversalCorrectionCommand(
            KEY,
            SETTLEMENT,
            DISPOSITION,
            "The forfeiture was recorded in error",
            "Owner review note 12",
            METHOD,
            "Cash handed over at the front desk",
        ),
        **changes,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"idempotency_key": UUID(int=0)},
        {"settlement_id": "not-a-uuid"},
        {"deposit_disposition_id": UUID(int=0)},
        {"deposit_disposition_id": "not-a-uuid"},
        {"reason": ""},
        {"reason": "x" * 501},
        {"evidence_reference": ""},
        {"evidence_reference": " padded"},
        {"evidence_reference": "x" * 501},
        {"refund_method_id": None},
        {"reference_note": " padded"},
        {"reference_note": "x" * 501},
        {"steps": ["not a step"]},
        {"steps": []},
        {"pet_remainder": "staff"},
    ],
)
def test_forfeiture_reversal_correction_commands_are_validated(changes: dict[str, Any]) -> None:
    """V1-056 sub-slice 10d: the forfeiture, a reason, the evidence reference, the Refund method and
    reference note (both required) and a tuple of typed plan steps."""
    with pytest.raises(FinalSettlementInvalidError):
        forfeiture_reversal(**changes)


def test_forfeiture_reversal_correction_record_and_confirm_send_the_stored_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The record call carries the forfeiture, the evidence reference, the Refund method and note
    and the DL-032 plan; only final_settlements.prepare records and only financial.approve
    confirms."""
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
    service = SettlementCorrectionService("financial-url")
    with pytest.raises(FinalSettlementAuthorizationError):
        service.record_forfeiture_reversal(
            PROPERTY, forfeiture_reversal(), actor=person("financial.approve")
        )
    with pytest.raises(FinalSettlementAuthorizationError):
        service.confirm_forfeiture_reversal(
            PROPERTY, DRAFT, actor=person("final_settlements.prepare")
        )
    wrong_kind: Any = held_value()
    with pytest.raises(FinalSettlementInvalidError):
        service.record_forfeiture_reversal(
            PROPERTY, wrong_kind, actor=person("final_settlements.prepare")
        )
    assert calls == []
    assert service.record_forfeiture_reversal(
        PROPERTY, forfeiture_reversal(), actor=person("final_settlements.prepare")
    ) == {"draft_id": str(DRAFT)}
    sql, parameters = calls[-1]
    assert sql == "SELECT app.record_settlement_forfeiture_reversal_draft(%s,%s,%s,%s,%s,%s,%s)"
    assert isinstance(parameters, tuple)
    assert parameters[:4] == (
        PROPERTY,
        HUMAN,
        settlement_correction_draft_id(PROPERTY, HUMAN, KEY),
        SETTLEMENT,
    )
    stored = parameters[4]
    assert isinstance(stored, Jsonb)
    assert stored.obj == {
        "deposit_disposition_id": str(DISPOSITION),
        "evidence_reference": "Owner review note 12",
        "refund_method_id": str(METHOD),
        "reference_note": "Cash handed over at the front desk",
        "plan": {"steps": [], "pet_remainder": None},
    }
    assert parameters[5:] == (
        "The forfeiture was recorded in error",
        "final_settlements.prepare",
    )
    calls.clear()
    assert service.confirm_forfeiture_reversal(
        PROPERTY, DRAFT, actor=person("financial.approve")
    ) == {"draft_id": str(DRAFT)}
    assert calls[-1] == (
        "SELECT app.confirm_settlement_forfeiture_reversal(%s,%s,%s,%s)",
        (PROPERTY, HUMAN, DRAFT, "financial.approve"),
    )


@pytest.mark.parametrize(
    ("sqlstate", "confirm_error"),
    [
        ("P5S02", FinalSettlementStaleDraftError),
        ("55000", FinalSettlementConflictError),
        ("42501", FinalSettlementAuthorizationError),
        ("P0002", FinalSettlementNotFoundError),
        ("22023", FinalSettlementInvalidError),
        ("P5205", FinalSettlementKeyReused),
        (None, FinalSettlementUnavailableError),
    ],
)
def test_forfeiture_reversal_correction_confirm_maps_database_refusals(
    monkeypatch: pytest.MonkeyPatch, sqlstate: str | None, confirm_error: type[Exception]
) -> None:
    """A draft whose forfeiture, Deposit or Settlement sources changed is stale and stays pending;
    other refusals keep the Final Settlement error mapping."""

    class Failure(psycopg.Error):
        pass

    failure = Failure("Synthetic failure")
    failure.sqlstate = sqlstate

    def connect(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(psycopg, "connect", connect)
    with pytest.raises(confirm_error) as refused:
        SettlementCorrectionService("unused").confirm_forfeiture_reversal(
            PROPERTY, DRAFT, actor=person("financial.approve")
        )
    assert type(refused.value) is confirm_error and refused.value.__cause__ is failure


CHARGE = UUID(int=81)


def late_charge_reduction(**changes: Any) -> RecordLateChargeReductionCorrectionCommand:
    base = RecordLateChargeReductionCorrectionCommand(
        KEY, SETTLEMENT, CHARGE, 1_000, "The Late-payment Charge used the wrong rate"
    )
    return replace(base, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"idempotency_key": UUID(int=0)},
        {"settlement_id": "not-a-uuid"},
        {"late_payment_charge_id": UUID(int=0)},
        {"amount_usd_cents": 0},
        {"amount_usd_cents": 10.0},
        {"amount_usd_cents": True},
        {"amount_usd_cents": 9_000_000_000_000_001},
        {"reason": " padded"},
        {"reason": "x" * 501},
    ],
)
def test_the_late_charge_reduction_command_refuses_malformed_input(
    changes: dict[str, Any],
) -> None:
    """Sub-slice 10c-3a: money in whole positive cents within the cap; the reason fits the Charge
    correction (500)."""
    with pytest.raises(FinalSettlementInvalidError):
        late_charge_reduction(**changes)


def test_a_late_charge_reduction_is_recorded_by_staff_and_confirmed_only_by_an_approver(
    no_connection: None,
) -> None:
    """BR-AUTH-010 (sub-slice 10c-3a): final_settlements.prepare records a Late-payment Charge
    reduction and only financial.approve confirms it, before any connection; the Late-payment
    capability alone does neither."""
    service = SettlementCorrectionService("unused")
    for actor in (
        person(),
        person("financial.approve"),
        person("late_payment.charge_correction"),
    ):
        with pytest.raises(FinalSettlementAuthorizationError):
            service.record_late_charge_reduction(PROPERTY, late_charge_reduction(), actor=actor)
    for actor in (
        person(),
        person("final_settlements.prepare"),
        person("late_payment.charge_correction"),
    ):
        with pytest.raises(FinalSettlementAuthorizationError):
            service.confirm_late_charge_reduction(PROPERTY, DRAFT, actor=actor)
    with pytest.raises(FinalSettlementInvalidError):
        service.confirm_late_charge_reduction(
            PROPERTY, UUID(int=0), actor=person("financial.approve")
        )
    with pytest.raises(FinalSettlementInvalidError):
        service.record_late_charge_reduction(
            PROPERTY,
            reduction(),  # type: ignore[arg-type]
            actor=person("final_settlements.prepare"),
        )


def test_late_charge_reduction_record_and_confirm_send_the_stored_reduction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sub-slice 10c-3a: the recorder sends the Charge and the amount; the confirm maps a changed
    Charge to a stale draft (P5S02) and keeps the Final Settlement mapping for the rest."""
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

    monkeypatch.setattr(psycopg, "connect", lambda url, **kwargs: Connection())
    service = SettlementCorrectionService("financial-url")
    assert service.record_late_charge_reduction(
        PROPERTY, late_charge_reduction(), actor=person("final_settlements.prepare")
    ) == {"draft_id": str(DRAFT)}
    sql, parameters = calls[-1]
    assert sql == ("SELECT app.record_settlement_late_charge_reduction_draft(%s,%s,%s,%s,%s,%s,%s)")
    assert isinstance(parameters, tuple)
    assert parameters[:4] == (
        PROPERTY,
        HUMAN,
        settlement_correction_draft_id(PROPERTY, HUMAN, KEY),
        SETTLEMENT,
    )
    stored = parameters[4]
    assert isinstance(stored, Jsonb)
    assert stored.obj == {"late_payment_charge_id": str(CHARGE), "amount_usd_cents": 1_000}
    assert parameters[5:] == (
        "The Late-payment Charge used the wrong rate",
        "final_settlements.prepare",
    )
    assert service.confirm_late_charge_reduction(
        PROPERTY, DRAFT, actor=person("financial.approve")
    ) == {"draft_id": str(DRAFT)}
    assert calls[-1] == (
        "SELECT app.confirm_settlement_late_charge_reduction(%s,%s,%s,%s)",
        (PROPERTY, HUMAN, DRAFT, "financial.approve"),
    )

    class Failure(psycopg.Error):
        pass

    for sqlstate, error in (
        ("P5S02", FinalSettlementStaleDraftError),
        ("55000", FinalSettlementConflictError),
        ("P0002", FinalSettlementNotFoundError),
        ("42501", FinalSettlementAuthorizationError),
    ):
        failure = Failure("Synthetic failure")
        failure.sqlstate = sqlstate

        def refuse(*args: object, failure: Failure = failure, **kwargs: object) -> None:
            raise failure

        monkeypatch.setattr(psycopg, "connect", refuse)
        with pytest.raises(error) as refused:
            service.confirm_late_charge_reduction(
                PROPERTY, DRAFT, actor=person("financial.approve")
            )
        assert type(refused.value) is error and refused.value.__cause__ is failure


def late_charge_refund(**changes: Any) -> RecordLateChargeRefundCorrectionCommand:
    base = RecordLateChargeRefundCorrectionCommand(
        KEY,
        SETTLEMENT,
        CHARGE,
        3_000,
        METHOD,
        "Cash handed over at the front desk",
        "The Late-payment Charge used the wrong rate and was paid",
    )
    return replace(base, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"idempotency_key": UUID(int=0)},
        {"settlement_id": "not-a-uuid"},
        {"late_payment_charge_id": UUID(int=0)},
        {"amount_usd_cents": 0},
        {"amount_usd_cents": 10.0},
        {"amount_usd_cents": True},
        {"amount_usd_cents": 9_000_000_000_000_001},
        {"refund_method_id": None},
        {"reference_note": " padded"},
        {"reference_note": "x" * 501},
        {"reason": "x" * 501},
        {"steps": [object()]},
        {"steps": (object(),)},
        {"pet_remainder": "STAFF"},
    ],
)
def test_the_late_charge_refund_command_refuses_malformed_input(changes: dict[str, Any]) -> None:
    """Sub-slice 10c-3b-1: money in whole positive cents within the cap; a Refund method and a
    reference note (BR-REFUND-014); the reason fits the Charge correction (500); the plan in the
    Final Settlement format."""
    with pytest.raises(FinalSettlementInvalidError):
        late_charge_refund(**changes)


def test_a_late_charge_refund_is_recorded_by_staff_and_confirmed_only_by_an_approver(
    no_connection: None,
) -> None:
    """BR-AUTH-010 (sub-slice 10c-3b-1): final_settlements.prepare records a Late-payment Charge
    Refund and only financial.approve confirms it, before any connection; the Refund capability
    alone does neither."""
    service = SettlementCorrectionService("unused")
    for actor in (person(), person("financial.approve"), person("refunds.create")):
        with pytest.raises(FinalSettlementAuthorizationError):
            service.record_late_charge_refund(PROPERTY, late_charge_refund(), actor=actor)
    for actor in (person(), person("final_settlements.prepare"), person("refunds.create")):
        with pytest.raises(FinalSettlementAuthorizationError):
            service.confirm_late_charge_refund(PROPERTY, DRAFT, actor=actor)
    with pytest.raises(FinalSettlementInvalidError):
        service.confirm_late_charge_refund(PROPERTY, UUID(int=0), actor=person("financial.approve"))
    with pytest.raises(FinalSettlementInvalidError):
        service.record_late_charge_refund(
            PROPERTY,
            refund(),  # type: ignore[arg-type]
            actor=person("final_settlements.prepare"),
        )


def test_late_charge_refund_record_and_confirm_send_the_stored_refund(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sub-slice 10c-3b-1: the recorder sends the Charge, the amount, the Refund method, the note
    and the plan; the confirm maps a changed Charge or source to a stale draft (P5S02) and keeps the
    Final Settlement mapping for the rest."""
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

    monkeypatch.setattr(psycopg, "connect", lambda url, **kwargs: Connection())
    service = SettlementCorrectionService("financial-url")
    assert service.record_late_charge_refund(
        PROPERTY, late_charge_refund(), actor=person("final_settlements.prepare")
    ) == {"draft_id": str(DRAFT)}
    sql, parameters = calls[-1]
    assert sql == "SELECT app.record_settlement_late_charge_refund_draft(%s,%s,%s,%s,%s,%s,%s)"
    assert isinstance(parameters, tuple)
    assert parameters[:4] == (
        PROPERTY,
        HUMAN,
        settlement_correction_draft_id(PROPERTY, HUMAN, KEY),
        SETTLEMENT,
    )
    stored = parameters[4]
    assert isinstance(stored, Jsonb)
    assert stored.obj == {
        "late_payment_charge_id": str(CHARGE),
        "amount_usd_cents": 3_000,
        "refund_method_id": str(METHOD),
        "reference_note": "Cash handed over at the front desk",
        "plan": {"steps": [], "pet_remainder": None},
    }
    assert parameters[5:] == (
        "The Late-payment Charge used the wrong rate and was paid",
        "final_settlements.prepare",
    )
    assert service.confirm_late_charge_refund(
        PROPERTY, DRAFT, actor=person("financial.approve")
    ) == {"draft_id": str(DRAFT)}
    assert calls[-1] == (
        "SELECT app.confirm_settlement_late_charge_refund(%s,%s,%s,%s)",
        (PROPERTY, HUMAN, DRAFT, "financial.approve"),
    )

    class Failure(psycopg.Error):
        pass

    for sqlstate, error in (
        ("P5S02", FinalSettlementStaleDraftError),
        ("55000", FinalSettlementConflictError),
        ("P0002", FinalSettlementNotFoundError),
        ("42501", FinalSettlementAuthorizationError),
    ):
        failure = Failure("Synthetic failure")
        failure.sqlstate = sqlstate

        def refuse(*args: object, failure: Failure = failure, **kwargs: object) -> None:
            raise failure

        monkeypatch.setattr(psycopg, "connect", refuse)
        with pytest.raises(error) as refused:
            service.confirm_late_charge_refund(PROPERTY, DRAFT, actor=person("financial.approve"))
        assert type(refused.value) is error and refused.value.__cause__ is failure
