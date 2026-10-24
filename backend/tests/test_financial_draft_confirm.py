"""The shared confirm calls each draft kind's own confirm command (V1-056 slice 11b)."""

from __future__ import annotations

import inspect
from typing import Any, ClassVar
from uuid import UUID, uuid4

import pytest

import property_rental.financial_draft_confirm as confirm_module
from property_rental.financial_draft_confirm import (
    DraftConfirmNotAvailable,
    DraftPayloadInvalid,
    PostgresDraftConfirmer,
)
from property_rental.identity import AuthenticatedActor

PROPERTY = uuid4()
DRAFT = uuid4()
WHO = AuthenticatedActor(actor_id=str(uuid4()), capability_grants=frozenset())


class Recorder:
    """Stands in for every service class: records the constructor and the method called."""

    calls: ClassVar[list[tuple[str, str, tuple[Any, ...]]]] = []

    def __init__(self, name: str) -> None:
        self.name = name

    def __call__(self, *urls: str) -> Recorder:
        assert all(isinstance(url, str) for url in urls)
        # The same number of database URLs as the real service takes.
        fields = inspect.signature(REAL_SERVICES[self.name]).parameters
        assert len(urls) == len(fields), self.name
        return self

    def __getattr__(self, method: str) -> Any:
        # Only a method the real service has, with the same positional arguments.
        real = getattr(REAL_SERVICES[self.name], method)
        parameters = [
            parameter
            for parameter in inspect.signature(real).parameters.values()
            if parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        ]

        def call(*arguments: Any, actor: AuthenticatedActor) -> dict[str, object]:
            assert len(arguments) == len(parameters) - 1, (self.name, method)
            assert actor is WHO
            Recorder.calls.append((self.name, method, arguments))
            return {"confirmed": True}

        return call


SERVICE_NAMES = (
    "AdjustmentReversalService",
    "DepositReceiptReversalService",
    "FinalSettlementService",
    "LeaseDepositForfeitureService",
    "PaymentMoveService",
    "PaymentReturnService",
    "RefundService",
    "ReservationDepositDraftService",
    "SettlementCorrectionService",
)
REAL_SERVICES: dict[str, type] = {name: getattr(confirm_module, name) for name in SERVICE_NAMES}


@pytest.fixture(autouse=True)
def recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    Recorder.calls = []
    for name in SERVICE_NAMES:
        monkeypatch.setattr(confirm_module, name, Recorder(name))


def draft(kind: str, **payload: object) -> dict[str, object]:
    return {"draft_id": str(DRAFT), "kind": kind, "payload": payload}


def confirm(value: dict[str, object]) -> tuple[str, str, tuple[Any, ...]]:
    result = PostgresDraftConfirmer("runtime", "financial").confirm(PROPERTY, value, actor=WHO)
    assert result == {"confirmed": True}
    assert len(Recorder.calls) == 1
    return Recorder.calls[0]


SUBJECT = uuid4()
CASES: list[tuple[dict[str, object], tuple[str, str, tuple[Any, ...]]]] = [
    (draft("REFUND", variant="USD"), ("RefundService", "confirm_draft", (PROPERTY, DRAFT))),
    (draft("REFUND", variant="PET"), ("RefundService", "confirm_draft", (PROPERTY, DRAFT))),
    (
        draft("REFUND", variant="CREDIT_CUSTOMER"),
        ("RefundService", "confirm_draft", (PROPERTY, DRAFT)),
    ),
    (
        draft("REFUND", variant="RESERVATION_OUTCOME", reservation_id=str(SUBJECT)),
        ("ReservationDepositDraftService", "confirm", (PROPERTY, SUBJECT, DRAFT)),
    ),
    (
        draft("DEPOSIT_FORFEITURE", variant="RESERVATION_CORRECTION", reservation_id=str(SUBJECT)),
        ("ReservationDepositDraftService", "confirm", (PROPERTY, SUBJECT, DRAFT)),
    ),
    (
        draft("DEPOSIT_FORFEITURE", variant="LEASE_FORFEITURE", deposit_id=str(SUBJECT)),
        ("LeaseDepositForfeitureService", "confirm", (PROPERTY, SUBJECT, DRAFT)),
    ),
    (
        draft(
            "DEPOSIT_FORFEITURE", variant="LEASE_FORFEITURE_REVERSAL", disposition_id=str(SUBJECT)
        ),
        ("LeaseDepositForfeitureService", "confirm_reversal", (PROPERTY, SUBJECT, DRAFT)),
    ),
    (
        draft("DEPOSIT_FORFEITURE", variant="DEPOSIT_RECEIPT_REVERSAL", receipt_id=str(SUBJECT)),
        ("DepositReceiptReversalService", "confirm", (PROPERTY, SUBJECT, DRAFT)),
    ),
    (
        draft("PAYMENT_MOVE", variant="WRONG_UNIT_MOVE"),
        ("PaymentMoveService", "confirm", (PROPERTY, DRAFT)),
    ),
    (
        draft("FINAL_SETTLEMENT", variant="FINAL_SETTLEMENT"),
        ("FinalSettlementService", "confirm", (PROPERTY, DRAFT)),
    ),
    (draft("PAYMENT_RETURN"), ("PaymentReturnService", "confirm", (PROPERTY, DRAFT))),
    (
        draft("ADJUSTMENT_REVERSAL", variant="ADJUSTMENT_REVERSAL"),
        ("AdjustmentReversalService", "confirm", (PROPERTY, DRAFT)),
    ),
    *[
        (
            draft("SETTLEMENT_CORRECTION", variant=variant, **extra),
            ("SettlementCorrectionService", method, (PROPERTY, DRAFT)),
        )
        for variant, extra, method in (
            ("EXTRA_CHARGE", {}, "confirm_extra_charge"),
            ("CHARGE_REDUCTION", {}, "confirm_charge_reduction"),
            ("CHARGE_REDUCTION", {"target_kind": "INVOICE_LINE"}, "confirm_charge_reduction"),
            (
                "CHARGE_REDUCTION",
                {"target_kind": "LATE_PAYMENT_CHARGE"},
                "confirm_late_charge_reduction",
            ),
            ("REFUND", {}, "confirm_refund"),
            ("REFUND", {"target_kind": "LATE_PAYMENT_CHARGE"}, "confirm_late_charge_refund"),
            ("PET_DAMAGE_RECLASSIFICATION", {}, "confirm_pet_classification"),
            ("REFUND_RETURN", {}, "confirm_refund_return"),
            ("HELD_VALUE_REFUND", {}, "confirm_held_value_refund"),
            ("FORFEITURE_REVERSAL", {}, "confirm_forfeiture_reversal"),
            ("RETURNED_PAYMENT", {}, "confirm_returned_payment"),
            ("DEPOSIT_RECEIPT_CORRECTION", {}, "confirm_deposit_receipt_correction"),
            ("RETURN_REVERSAL", {}, "confirm_return_reversal"),
        )
    ],
    (
        draft("SETTLEMENT_CORRECTION", variant="PAYMENT_MOVE"),
        ("PaymentMoveService", "confirm_correction", (PROPERTY, DRAFT)),
    ),
    (
        draft("SETTLEMENT_CORRECTION", variant="ADJUSTMENT_REVERSAL"),
        ("AdjustmentReversalService", "confirm_correction", (PROPERTY, DRAFT)),
    ),
]


@pytest.mark.parametrize(("value", "expected"), CASES)
def test_each_kind_and_variant_reaches_its_own_confirm(
    value: dict[str, object], expected: tuple[str, str, tuple[Any, ...]]
) -> None:
    assert confirm(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        # A companion is confirmed inside its return reversal, never alone.
        draft("SETTLEMENT_CORRECTION", variant="RETURN_REVERSAL_COMPANION"),
        draft("SETTLEMENT_CORRECTION", variant="EXTRA_CHARGE", target_kind="LATE_PAYMENT_CHARGE"),
        draft("REFUND", variant="SOMETHING_NEW"),
        draft("DEPOSIT_FORFEITURE"),
    ],
)
def test_a_draft_without_a_shared_confirm_is_refused_before_any_command(
    value: dict[str, object],
) -> None:
    with pytest.raises(DraftConfirmNotAvailable):
        PostgresDraftConfirmer("runtime", "financial").confirm(PROPERTY, value, actor=WHO)
    assert Recorder.calls == []


@pytest.mark.parametrize("identity", [None, "", "not-a-uuid", str(UUID(int=0)), 7])
def test_a_missing_identifier_is_a_server_contract_error(identity: object) -> None:
    value = draft("DEPOSIT_FORFEITURE", variant="LEASE_FORFEITURE", deposit_id=identity)
    with pytest.raises(DraftPayloadInvalid):
        PostgresDraftConfirmer("runtime", "financial").confirm(PROPERTY, value, actor=WHO)
    assert Recorder.calls == []
