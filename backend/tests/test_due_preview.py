"""Exact immutable preview choices and historical-compatible Credit confirmations."""

import copy
import json
from dataclasses import FrozenInstanceError
from typing import Any, Literal
from uuid import uuid4

import pytest

from property_rental.credit import ApplyCreditCommand, CreditInvalidError
from property_rental.due_preview import DesignationPreviewInput, PreviewInputError

Kind = Literal["PAYMENT", "CREDIT"]
KINDS: list[Kind] = ["PAYMENT", "CREDIT"]


def selection(kind: Kind, mode: str = "default") -> dict[str, Any]:
    line = str(uuid4())
    detail: dict[str, Any] = {"invoice_line_id": line, "amount_usd_cents": 100}
    if mode == "explicit":
        detail["source_parts"] = [
            {"source_kind": "DEBIT_ADJUSTMENT", "source_id": str(uuid4()), "amount_usd_cents": 100}
        ]
    target = (
        {"late_payment_charge_id": str(uuid4()), "amount_usd_cents": 100}
        if mode == "charge"
        else {"invoice_id": str(uuid4()), "amount_usd_cents": 100, "details": [detail]}
    )
    intent = {"mode": "DESIGNATED", "designation_reference": "Customer instruction"}
    return {**intent, "targets": [target]} if kind == "PAYMENT" else {**intent, **target}


def selected_target(kind: Kind, intent: dict[str, Any]) -> dict[str, Any]:
    return intent["targets"][0] if kind == "PAYMENT" else intent


def confirmation() -> dict[str, Any]:
    intent = selection("CREDIT")
    intent["invoice_version"] = 3
    detail = intent["details"][0]
    detail["due_attribution"] = {
        "basis": "EARLIEST_DUE",
        "parts": [
            {
                "source_kind": "ORIGINAL_LINE",
                "source_id": detail["invoice_line_id"],
                "approved_due_date": "2027-02-05",
                "source_occurred_at": "2026-09-16T11:00:00+00:00",
                "outstanding_usd_cents": 9_223_372_036_854_775_807,
                "amount_usd_cents": 100,
            }
        ],
    }
    return intent


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("mode", ["default", "explicit", "charge"])
def test_due_preview_preserves_customer_selection_as_a_detached_read(kind: Kind, mode: str) -> None:
    intent = selection(kind, mode)
    original = copy.deepcopy(intent)
    request = DesignationPreviewInput(kind, intent)
    intent["designation_reference"] = "Changed by caller"
    selected_target(kind, intent)["amount_usd_cents"] = 999
    detached = request.intent
    selected_target(kind, detached)["amount_usd_cents"] = 888
    assert request.intent == original
    assert not hasattr(request, "idempotency_key")
    dynamic: Any = request
    with pytest.raises(FrozenInstanceError):
        dynamic.kind = "CREDIT" if kind == "PAYMENT" else "PAYMENT"


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "case",
    [
        "mode",
        "reference",
        "unknown",
        "id",
        "amount_bool",
        "amount_float",
        "amount_string",
        "amount_zero",
        "amount_negative",
        "amount_large",
        "version",
        "computed",
        "missing_detail",
        "duplicate_line",
        "line_total",
        "source_total",
        "source_kind",
        "source_unknown",
        "duplicate_source",
        "nul",
        "byte_limit",
        "source_empty",
    ],
)
def test_due_preview_rejects_malformed_or_premature_confirmation(kind: Kind, case: str) -> None:
    intent = selection(kind, "explicit")
    target = selected_target(kind, intent)
    detail = target["details"][0]
    part = detail["source_parts"][0]
    if case == "mode":
        intent["mode"] = "PROPOSAL"
    elif case == "reference":
        intent["designation_reference"] = " invalid "
    elif case == "unknown":
        intent["idempotency_key"] = str(uuid4())
    elif case == "id":
        target["invoice_id"] = "00000000-0000-0000-0000-000000000000"
    elif case.startswith("amount_"):
        target["amount_usd_cents"] = {
            "bool": True,
            "float": 100.0,
            "string": "100",
            "zero": 0,
            "negative": -1,
            "large": 9_000_000_000_000_001,
        }[case.removeprefix("amount_")]
    elif case == "version":
        target["invoice_version"] = 1
    elif case == "computed":
        detail["due_attribution"] = {"basis": "EARLIEST_DUE", "parts": []}
    elif case == "missing_detail":
        target["details"] = []
    elif case == "duplicate_line":
        target["details"].append(copy.deepcopy(detail))
    elif case == "line_total":
        detail["amount_usd_cents"] = 99
    elif case == "source_total":
        part["amount_usd_cents"] = 99
    elif case == "source_kind":
        part["source_kind"] = "UNKNOWN"
    elif case == "source_unknown":
        part["approved_due_date"] = "2027-01-01"
    elif case == "duplicate_source":
        detail["source_parts"].append(copy.deepcopy(part))
    elif case == "nul":
        intent["designation_reference"] = "x\x00y"
    elif case == "byte_limit":
        intent["designation_reference"] = "界" * 100_000
    elif case == "source_empty":
        detail["source_parts"] = []
    with pytest.raises(PreviewInputError):
        DesignationPreviewInput(kind, intent)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("count", [500, 501])
def test_due_preview_counts_explicit_parts_across_the_entire_selection(
    kind: Kind, count: int
) -> None:
    intent = selection(kind)
    target = selected_target(kind, intent)
    target["amount_usd_cents"] = count
    target["details"] = [
        {
            "invoice_line_id": str(uuid4()),
            "amount_usd_cents": size,
            "source_parts": [
                {
                    "source_kind": "DEBIT_ADJUSTMENT",
                    "source_id": str(uuid4()),
                    "amount_usd_cents": 1,
                }
                for _ in range(size)
            ],
        }
        for size in (250, count - 250)
    ]
    if count == 500:
        assert DesignationPreviewInput(kind, intent).intent == intent
    else:
        with pytest.raises(PreviewInputError):
            DesignationPreviewInput(kind, intent)


@pytest.mark.parametrize(
    "case", ["target_count", "duplicate_target", "whole_amount", "whole_details"]
)
def test_due_payment_preview_whole_command_limits_and_identity(case: str) -> None:
    intent = selection("PAYMENT")
    first = intent["targets"][0]
    if case == "target_count":
        intent["targets"] = [selection("PAYMENT", "charge")["targets"][0] for _ in range(101)]
    elif case == "duplicate_target":
        intent["targets"].append(copy.deepcopy(first))
    elif case == "whole_amount":
        intent["targets"] = [
            {"late_payment_charge_id": str(uuid4()), "amount_usd_cents": 9_000_000_000_000_000}
            for _ in range(2)
        ]
    else:
        intent["targets"] = [
            {
                "invoice_id": str(uuid4()),
                "amount_usd_cents": size,
                "details": [
                    {"invoice_line_id": str(uuid4()), "amount_usd_cents": 1} for _ in range(size)
                ],
            }
            for size in (250, 251)
        ]
    with pytest.raises(PreviewInputError):
        DesignationPreviewInput("PAYMENT", intent)


@pytest.mark.parametrize("mode", ["legacy", "dated", "charge", "proposal"])
def test_due_credit_confirmation_keeps_captured_payload_and_historical_encoding(mode: str) -> None:
    if mode == "dated":
        intent = confirmation()
    elif mode == "proposal":
        intent = {
            "mode": "PROPOSAL",
            "proposal": {
                "invoice_id": str(uuid4()),
                "amount_usd_cents": 100,
                "source_trace": {"original": "unchanged"},
            },
        }
    else:
        intent = selection("CREDIT", "charge" if mode == "charge" else "default")
    original = copy.deepcopy(intent)
    expected = json.dumps(original, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    command = ApplyCreditCommand(uuid4(), intent)
    intent.clear()
    detached = command.intent
    detached.clear()
    assert command.intent == original
    assert command._intent_json == expected


@pytest.mark.parametrize(
    "case",
    [
        "version_missing",
        "version_bool",
        "version_zero",
        "version_large",
        "due_missing",
        "parts_empty",
        "source_parts",
        "basis",
        "part_unknown",
        "source_kind",
        "date",
        "date_compact",
        "timestamp_naive",
        "timestamp_bad",
        "outstanding_small",
        "outstanding_large",
        "amount_bool",
        "part_total",
        "line_total",
        "duplicate_line",
        "duplicate_part",
        "mixed",
    ],
)
def test_due_credit_confirmation_rejects_incomplete_or_ambiguous_metadata(case: str) -> None:
    intent = confirmation()
    detail = intent["details"][0]
    due = detail["due_attribution"]
    part = due["parts"][0]
    if case == "version_missing":
        del intent["invoice_version"]
    elif case == "version_bool":
        intent["invoice_version"] = True
    elif case == "version_zero":
        intent["invoice_version"] = 0
    elif case == "version_large":
        intent["invoice_version"] = 10_000_000_000
    elif case == "due_missing":
        del detail["due_attribution"]
    elif case == "parts_empty":
        due["parts"] = []
    elif case == "source_parts":
        detail["source_parts"] = []
    elif case == "basis":
        due["basis"] = "UNKNOWN"
    elif case == "part_unknown":
        part["balance_override"] = 100
    elif case == "source_kind":
        part["source_kind"] = "CREDIT_ADJUSTMENT"
    elif case == "date":
        part["approved_due_date"] = "2027-02-30"
    elif case == "date_compact":
        part["approved_due_date"] = "20270205"
    elif case == "timestamp_naive":
        part["source_occurred_at"] = "2026-09-16T11:00:00"
    elif case == "timestamp_bad":
        part["source_occurred_at"] = "invalid"
    elif case == "outstanding_small":
        part["outstanding_usd_cents"] = 99
    elif case == "outstanding_large":
        part["outstanding_usd_cents"] = 9_223_372_036_854_775_808
    elif case == "amount_bool":
        part["amount_usd_cents"] = True
    elif case == "part_total":
        part["amount_usd_cents"] = 99
    elif case == "line_total":
        intent["amount_usd_cents"] = 101
    elif case == "duplicate_line":
        intent["details"].append(copy.deepcopy(detail))
    elif case == "duplicate_part":
        due["parts"].append(copy.deepcopy(part))
    elif case == "mixed":
        intent["details"].append({"invoice_line_id": str(uuid4()), "amount_usd_cents": 1})
    with pytest.raises(CreditInvalidError):
        ApplyCreditCommand(uuid4(), intent)


@pytest.mark.parametrize("count", [500, 501])
def test_due_credit_confirmation_counts_parts_across_lines_without_normalizing(count: int) -> None:
    intent = confirmation()
    template = intent["details"][0]
    intent["amount_usd_cents"] = count
    intent["details"] = []
    for size in (250, count - 250):
        detail = copy.deepcopy(template)
        detail["invoice_line_id"] = str(uuid4())
        detail["amount_usd_cents"] = size
        detail["due_attribution"]["basis"] = "CUSTOMER_DESIGNATED"
        detail["due_attribution"]["parts"] = [
            {
                **template["due_attribution"]["parts"][0],
                "source_kind": "DEBIT_ADJUSTMENT",
                "source_id": str(uuid4()),
                "amount_usd_cents": 1,
            }
            for _ in range(size)
        ]
        intent["details"].append(detail)
    if count == 500:
        assert ApplyCreditCommand(uuid4(), intent).intent == intent
    else:
        with pytest.raises(CreditInvalidError):
            ApplyCreditCommand(uuid4(), intent)
