"""The slice 11 browser forms stay in step with the API's request models (V1-056 slice 11; API-072,
API-101, API-102). ``frontend/src/settlementForms.ts`` is written from the OpenAPI request bodies
of the slice 11 routes; this test fails when a model changes and the file was not written again.

Write it again with ``uv run python tests/test_settlement_forms_ts.py`` from ``backend``."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Final, cast

from property_rental.app import create_app
from property_rental.settings import Settings

FORMS_PATH: Final = Path(__file__).resolve().parents[2] / "frontend" / "src" / "settlementForms.ts"
# Each slice 11 route with a request body, by the client function that sends it.
ROUTES: Final[dict[str, str]] = {
    "POST /api/v1/properties/{property_id}/units/{unit_id}/cleaning-rates": "CleaningRateInput",
    "POST /api/v1/properties/{property_id}/leases/{lease_id}/cleaning-charge": (
        "CleaningChargeInput"
    ),
    "POST /api/v1/invoices/{invoice_id}/hand-back-resolution": "HandBackResolutionInput",
    "POST /api/v1/leases/{lease_id}/security-deposit": "SecurityDepositCreate",
    "POST /api/v1/deposits/{deposit_id}/receipts": "DepositReceiptCreate",
    "POST /api/v1/properties/{property_id}/financial-drafts/{draft_id}/reject": "ReversalInput",
    "POST /api/v1/properties/{property_id}/financial-drafts/{draft_id}/withdraw": "ReversalInput",
    "POST /api/v1/properties/{property_id}/deposits/{deposit_id}/forfeiture-drafts": (
        "ForfeitureDraftInput"
    ),
    "POST /api/v1/properties/{property_id}/deposit-dispositions/{disposition_id}/reversal-drafts": (
        "ForfeitureReversalDraftInput"
    ),
    "POST /api/v1/properties/{property_id}/deposit-receipts/{receipt_id}/reversal-drafts": (
        "ReceiptReversalDraftInput"
    ),
    "POST /api/v1/properties/{property_id}/payments/{payment_id}/return-drafts": (
        "PaymentReturnDraftInput"
    ),
    "POST /api/v1/properties/{property_id}/payment-allocations/{allocation_id}/move-drafts": (
        "PaymentMoveDraftInput"
    ),
    "POST /api/v1/properties/{property_id}/invoice-adjustments/{adjustment_id}/reversal-drafts": (
        "AdjustmentReversalInput"
    ),
    "POST /api/v1/properties/{property_id}/final-settlements/{settlement_id}/drafts": (
        "FinalSettlementDraftInput"
    ),
    # V1-056 slice 11h: Refund methods in Settings.
    "POST /api/v1/properties/{property_id}/refund-methods": "AddRefundMethodInput",
    "POST /api/v1/properties/{property_id}/refund-methods/{refund_method_id}/state": (
        "RefundMethodStateInput"
    ),
    **{
        "POST /api/v1/properties/{property_id}/final-settlements/{settlement_id}/corrections/"
        f"{route}": model
        for route, model in {
            "extra-charges": "ExtraChargeInput",
            "charge-reductions": "ChargeReductionInput",
            "late-charge-reductions": "LateChargeReductionInput",
            "returned-payments": "ReturnedPaymentInput",
            "payment-moves": "MoveCorrectionInput",
            "adjustment-reversals": "AdjustmentReversalCorrectionInput",
            "refunds": "RefundCorrectionInput",
            "late-charge-refunds": "LateChargeRefundCorrectionInput",
            "pet-classifications": "PetClassificationCorrectionInput",
            "refund-returns": "RefundReturnCorrectionInput",
            "held-value-refunds": "HeldValueRefundCorrectionInput",
            "forfeiture-reversals": "ForfeitureReversalCorrectionInput",
            "deposit-receipt-corrections": "DepositReceiptCorrectionInput",
            "return-reversals": "ReturnReversalCorrectionInput",
        }.items()
    },
}
HEADER: Final = """// Written from the API's request models by
// backend/tests/test_settlement_forms_ts.py (V1-056 slice 11). Do not edit by hand:
// change the model, then write this file again.
// Amounts are integer US cents; ids are UUID text; instants are RFC3339 text with an offset;
// a due_date is a plain YYYY-MM-DD date. Rules between fields (a reason that comes with its
// choice, a finding a Damage charge needs) are checked by the server and answer 422 on the field.
"""


def _schemas() -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    spec = create_app(Settings()).openapi()
    paths = cast(dict[str, dict[str, object]], spec["paths"])
    bodies: dict[str, object] = {}
    for route in ROUTES:
        method, path = route.split(" ", 1)
        operation = cast(dict[str, object], paths[path][method.lower()])
        body = cast(dict[str, object], operation["requestBody"])
        content = cast(dict[str, dict[str, object]], body["content"])
        bodies[route] = content["application/json"]["schema"]
    return bodies, cast(dict[str, dict[str, object]], spec["components"]["schemas"])


def _name(reference: str) -> str:
    return reference.rsplit("/", 1)[-1]


def _type(schema: dict[str, object], used: set[str]) -> str:
    if "$ref" in schema:
        name = _name(str(schema["$ref"]))
        used.add(name)
        return name
    if "const" in schema:
        return json.dumps(schema["const"])
    if "enum" in schema:
        return " | ".join(json.dumps(value) for value in cast(list[object], schema["enum"]))
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [_type(option, used) for option in cast(list[dict[str, object]], schema[key])]
            return " | ".join(dict.fromkeys(options))
    kind = schema.get("type")
    if kind == "array":
        item = _type(cast(dict[str, object], schema["items"]), used)
        return f"({item})[]" if "|" in item else f"{item}[]"
    if kind in {"integer", "number"}:
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "string":
        return "string"
    if kind == "null":
        return "null"
    raise AssertionError(f"unsupported schema {schema}")


def _interface(name: str, schema: dict[str, object], used: set[str]) -> str:
    assert schema.get("type") == "object" and schema.get("additionalProperties") is False, name
    required = set(cast(list[str], schema.get("required", [])))
    lines = [f"export interface {name} {{"]
    for field, value in cast(dict[str, dict[str, object]], schema["properties"]).items():
        optional = "" if field in required else "?"
        lines.append(f"  {field}{optional}: {_type(value, used)};")
    lines.append("}")
    return "\n".join(lines)


def render() -> str:
    bodies, schemas = _schemas()
    used: set[str] = set()
    for route, model in ROUTES.items():
        assert _type(cast(dict[str, object], bodies[route]), used) == model, route
    written: dict[str, str] = {}
    while pending := sorted(used - set(written)):
        for name in pending:
            written[name] = _interface(name, schemas[name], used)
    return HEADER + "".join(f"\n{written[name]}\n" for name in sorted(written))


def test_the_settlement_forms_match_the_request_models() -> None:
    assert FORMS_PATH.read_text(encoding="utf-8") == render()


def test_every_slice_11_form_is_exported() -> None:
    text = FORMS_PATH.read_text(encoding="utf-8")
    exported = set(re.findall(r"^export interface (\w+) \{$", text, re.MULTILINE))
    assert set(ROUTES.values()) <= exported


if __name__ == "__main__":
    FORMS_PATH.write_text(render(), encoding="utf-8")
    sys.stdout.write(f"wrote {FORMS_PATH.name}\n")
