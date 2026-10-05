"""V1-056 sub-slice 8a-1: the Final Settlement service refuses bad input before any connection."""

from pathlib import Path
from uuid import UUID

import psycopg
import pytest

from property_rental.final_settlement import (
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementInvalidError,
    FinalSettlementKeyReused,
    FinalSettlementNotFoundError,
    FinalSettlementReadService,
    FinalSettlementService,
    FinalSettlementUnavailableError,
    PetRemainderBasis,
    PetRemainderDecision,
    RecordFinalSettlementDraftCommand,
    SettlementCreditStep,
    SettlementDepositRefund,
    SettlementDepositStep,
    SettlementDepositStepKind,
    SettlementTargetKind,
    final_settlement_draft_id,
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


def _plan_command(**changes: object) -> "RecordFinalSettlementDraftCommand":
    values: dict[str, object] = {
        "idempotency_key": UUID(int=11),
        "settlement_id": SETTLEMENT,
        "steps": (
            SettlementCreditStep(
                UUID(int=12), SettlementTargetKind.INVOICE_LINE, UUID(int=13), 400
            ),
            SettlementDepositStep(
                SettlementDepositStepKind.PET_DEPOSIT_REMAINDER,
                UUID(int=14),
                SettlementTargetKind.LATE_PAYMENT_CHARGE,
                UUID(int=15),
                700,
            ),
            SettlementDepositRefund(UUID(int=14), 300, UUID(int=16), "Cash at the desk", HUMAN),
        ),
        "reason": "Settlement prepared",
        "pet_remainder": PetRemainderDecision(
            PetRemainderBasis.CUSTOMER_CHOICE, "Customer asked", "Tenant, 2026-10-05, in writing"
        ),
    }
    values.update(changes)
    return RecordFinalSettlementDraftCommand(**values)  # type: ignore[arg-type]


def test_settlement_draft_commands_refuse_bad_input_before_any_connection(
    no_connection: None,
) -> None:
    """V1-056 sub-slice 8c: the service checks the input shape; the database checks the rules."""
    line = SettlementTargetKind.INVOICE_LINE
    for build in (
        lambda: SettlementCreditStep(UUID(int=0), line, UUID(int=13), 400),
        lambda: SettlementCreditStep(UUID(int=12), "INVOICE_LINE", UUID(int=13), 400),  # type: ignore[arg-type]
        lambda: SettlementCreditStep(UUID(int=12), line, UUID(int=13), 0),
        lambda: SettlementCreditStep(UUID(int=12), line, UUID(int=13), True),
        lambda: SettlementCreditStep(UUID(int=12), line, UUID(int=13), 9_000_000_000_000_001),
        lambda: SettlementCreditStep(UUID(int=12), line, UUID(int=13), 400, "d" * 501),
        lambda: SettlementCreditStep(UUID(int=12), line, UUID(int=13), 400, " Tenant"),
        lambda: SettlementDepositStep(
            "SECURITY_DEPOSIT",  # type: ignore[arg-type]
            UUID(int=14),
            line,
            UUID(int=13),
            1,
        ),
        lambda: SettlementDepositRefund(UUID(int=14), 300, UUID(int=16), " note", HUMAN),
        lambda: SettlementDepositRefund(UUID(int=14), 300, UUID(int=16), "n" * 501, HUMAN),
        lambda: SettlementDepositRefund(UUID(int=14), 300, UUID(int=16), "note", HUMAN, ""),
        lambda: PetRemainderDecision(PetRemainderBasis.CUSTOMER_CHOICE, "Customer asked"),
        lambda: PetRemainderDecision(PetRemainderBasis.STAFF_REASON, "Will not pay", "Choice"),
        lambda: PetRemainderDecision(PetRemainderBasis.STAFF_REASON, "r" * 1001),
        lambda: _plan_command(steps=[]),
        lambda: _plan_command(steps=("not a step",)),
        lambda: _plan_command(steps=(_plan_command().steps[0],) * 201),
        lambda: _plan_command(reason=""),
        lambda: _plan_command(settlement_id=UUID(int=0)),
        lambda: _plan_command(pet_remainder="CUSTOMER_CHOICE"),
    ):
        with pytest.raises(FinalSettlementInvalidError):
            build()
    service = FinalSettlementService("unused")
    for actor in (
        person(),
        person("financial.approve"),
        person("deposits.dispose"),
        person("final_settlements.prepare", actor_id="not-a-uuid"),
    ):
        with pytest.raises(FinalSettlementAuthorizationError):
            service.record_draft(PROPERTY, _plan_command(), actor=actor)


def test_settlement_draft_sends_the_plan_with_a_stable_draft_id(
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
            return ({"state": "PENDING"},)

    def connect(url: str, **kwargs: object) -> Connection:
        calls.append(("connect", url))
        return Connection()

    monkeypatch.setattr(psycopg, "connect", connect)
    command = _plan_command()
    result = FinalSettlementService("financial-url").record_draft(
        PROPERTY, command, actor=person("final_settlements.prepare")
    )
    assert result == {"state": "PENDING"}
    assert calls[0] == ("connect", "financial-url")
    sql, parameters, read_only = calls[-1]
    assert sql == "SELECT app.record_final_settlement_draft(%s,%s,%s,%s,%s,%s,%s)"
    assert read_only is None
    assert isinstance(parameters, tuple)
    draft_id = final_settlement_draft_id(PROPERTY, HUMAN, command.idempotency_key)
    assert parameters[:4] == (PROPERTY, HUMAN, draft_id, SETTLEMENT)
    assert parameters[5:] == ("Settlement prepared", "final_settlements.prepare")
    assert parameters[4].obj == {
        "steps": [
            {
                "kind": "CUSTOMER_CREDIT",
                "customer_credit_id": str(UUID(int=12)),
                "target_kind": "INVOICE_LINE",
                "target_id": str(UUID(int=13)),
                "amount_usd_cents": 400,
                "customer_designation": None,
            },
            {
                "kind": "PET_DEPOSIT_REMAINDER",
                "deposit_id": str(UUID(int=14)),
                "target_kind": "LATE_PAYMENT_CHARGE",
                "target_id": str(UUID(int=15)),
                "amount_usd_cents": 700,
            },
            {
                "kind": "DEPOSIT_REFUNDS",
                "deposit_id": str(UUID(int=14)),
                "amount_usd_cents": 300,
                "refund_method_id": str(UUID(int=16)),
                "reference_note": "Cash at the desk",
                "recipient_customer_id": str(HUMAN),
                "signer_agreement": None,
            },
        ],
        "pet_remainder": {
            "basis": "CUSTOMER_CHOICE",
            "staff_reason": "Customer asked",
            "customer_choice": "Tenant, 2026-10-05, in writing",
        },
    }
    # The same preparer, Property and key always give the same draft; another key does not.
    assert draft_id == final_settlement_draft_id(PROPERTY, HUMAN, UUID(int=11))
    assert draft_id != final_settlement_draft_id(PROPERTY, HUMAN, UUID(int=17))
    assert draft_id != final_settlement_draft_id(PROPERTY, UUID(int=18), UUID(int=11))


def test_a_reused_settlement_draft_key_is_a_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    class Failure(psycopg.Error):
        pass

    failure = Failure("Synthetic failure")
    failure.sqlstate = "P5205"

    def connect(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(psycopg, "connect", connect)
    with pytest.raises(FinalSettlementKeyReused):
        FinalSettlementService("unused").record_draft(
            PROPERTY, _plan_command(), actor=person("final_settlements.prepare")
        )
