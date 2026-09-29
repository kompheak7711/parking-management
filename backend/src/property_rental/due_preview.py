"""Detached read-only designation inputs and typed dated confirmation evidence."""

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, cast
from uuid import UUID

MAX_AMOUNT = 9_000_000_000_000_000
MAX_BALANCE = 9_223_372_036_854_775_807
SOURCE_KINDS = {"ORIGINAL_LINE", "DEBIT_ADJUSTMENT"}


class PreviewInputError(ValueError):
    """The preview selection or confirmation is not a bounded exact value."""


def _amount(value: object, limit: int = MAX_AMOUNT) -> int:
    if type(value) is not int or not 1 <= value <= limit:
        raise PreviewInputError("A positive bounded exact integer is required")
    return value


def _identity(value: object) -> UUID:
    if not isinstance(value, str):
        raise PreviewInputError("A UUID string is required")
    try:
        identity = UUID(value)
    except ValueError as exc:
        raise PreviewInputError("A UUID string is required") from exc
    if identity.int == 0:
        raise PreviewInputError("A non-nil UUID is required")
    return identity


def _object(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise PreviewInputError("Unexpected or missing fields")
    return cast(dict[str, object], value)


def _rows(value: object, limit: int) -> list[object]:
    if not isinstance(value, list) or not 1 <= len(value) <= limit:
        raise PreviewInputError("A nonempty bounded selection is required")
    return value


def _source(part: dict[str, object]) -> tuple[str, UUID]:
    kind = part["source_kind"]
    if not isinstance(kind, str) or kind not in SOURCE_KINDS:
        raise PreviewInputError("Unknown dated source kind")
    return kind, _identity(part["source_id"])


def _exact_values(value: object, depth: int = 0) -> None:
    if depth > 24:
        raise PreviewInputError("Preview nesting exceeds its bound")
    if isinstance(value, str):
        if "\x00" in value:
            raise PreviewInputError("NUL is not permitted")
        return
    if type(value) is int and abs(value) <= MAX_AMOUNT:
        return
    if isinstance(value, list):
        for child in value:
            _exact_values(child, depth + 1)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for key, child in value.items():
            _exact_values(key, depth + 1)
            _exact_values(child, depth + 1)
        return
    raise PreviewInputError("Only bounded exact integers, strings, objects and arrays are allowed")


def _preview_details(value: object, expected: int) -> tuple[int, int]:
    details = _rows(value, 500)
    total = 0
    parts_count = 0
    seen: set[UUID] = set()
    for value in details:
        keys = {"invoice_line_id", "amount_usd_cents"}
        if isinstance(value, dict) and "source_parts" in value:
            keys.add("source_parts")
        detail = _object(value, keys)
        line = _identity(detail["invoice_line_id"])
        if line in seen:
            raise PreviewInputError("Duplicate Invoice line")
        seen.add(line)
        amount = _amount(detail["amount_usd_cents"])
        total += amount
        if "source_parts" in detail:
            selected = _rows(detail["source_parts"], 500)
            sources: set[tuple[str, UUID]] = set()
            selected_total = 0
            for value in selected:
                part = _object(value, {"source_kind", "source_id", "amount_usd_cents"})
                source = _source(part)
                if source in sources:
                    raise PreviewInputError("Duplicate dated source")
                sources.add(source)
                selected_total += _amount(part["amount_usd_cents"])
            if selected_total != amount:
                raise PreviewInputError("Selected source total does not match the line")
            parts_count += len(selected)
    if total != expected:
        raise PreviewInputError("Selected line total does not match the Invoice")
    return len(details), parts_count


def _validate_preview(kind: str, intent: dict[str, object]) -> None:
    if kind not in {"PAYMENT", "CREDIT"} or intent.get("mode") != "DESIGNATED":
        raise PreviewInputError("A Payment or Credit designation is required")
    reference = intent.get("designation_reference")
    if (
        not isinstance(reference, str)
        or not 1 <= len(reference) <= 500
        or reference != reference.strip()
    ):
        raise PreviewInputError("A normalized Customer designation reference is required")
    if kind == "PAYMENT":
        _object(intent, {"mode", "designation_reference", "targets"})
        targets = _rows(intent["targets"], 100)
    else:
        targets = [
            {
                key: value
                for key, value in intent.items()
                if key not in {"mode", "designation_reference"}
            }
        ]
    total = 0
    details_count = 0
    parts_count = 0
    seen: set[tuple[str, UUID]] = set()
    for value in targets:
        invoice = isinstance(value, dict) and "invoice_id" in value
        key = "invoice_id" if invoice else "late_payment_charge_id"
        keys = {key, "amount_usd_cents"}
        if invoice:
            keys.add("details")
        target = _object(value, keys)
        identity = key, _identity(target[key])
        if identity in seen:
            raise PreviewInputError("Duplicate target")
        seen.add(identity)
        amount = _amount(target["amount_usd_cents"])
        total += amount
        if invoice:
            detail_count, source_count = _preview_details(target["details"], amount)
            details_count += detail_count
            parts_count += source_count
        if details_count > 500 or parts_count > 500 or total > MAX_AMOUNT:
            raise PreviewInputError("Whole designation exceeds its bound")


@dataclass(frozen=True, slots=True, init=False)
class DesignationPreviewInput:
    kind: Literal["PAYMENT", "CREDIT"]
    _intent_json: str

    def __init__(self, kind: Literal["PAYMENT", "CREDIT"], intent: dict[str, object]) -> None:
        try:
            _exact_values(intent)
            encoded = json.dumps(
                intent, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
            )
            if len(encoded.encode()) > 250_000:
                raise PreviewInputError("Preview exceeds its UTF-8 envelope bound")
            detached = json.loads(encoded)
            if not isinstance(detached, dict):
                raise PreviewInputError("Preview must be an object")
            _validate_preview(kind, detached)
        except (RecursionError, UnicodeError, TypeError, ValueError) as exc:
            raise PreviewInputError("Designation preview input is invalid") from exc
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "_intent_json", encoded)

    @property
    def intent(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(self._intent_json))


def validate_due_confirmation(details: object, total: object, version: object) -> None:
    """Validate shape and exact totals without rewriting captured source evidence."""
    _amount(version, 9_999_999_999)
    expected = _amount(total)
    seen: set[UUID] = set()
    actual = 0
    count = 0
    for value in _rows(details, 500):
        detail = _object(value, {"invoice_line_id", "amount_usd_cents", "due_attribution"})
        line = _identity(detail["invoice_line_id"])
        if line in seen:
            raise PreviewInputError("Duplicate confirmation line")
        seen.add(line)
        amount = _amount(detail["amount_usd_cents"])
        actual += amount
        due = _object(detail["due_attribution"], {"basis", "parts"})
        if due["basis"] not in ("EARLIEST_DUE", "CUSTOMER_DESIGNATED"):
            raise PreviewInputError("Unknown attribution basis")
        selected_total = 0
        sources: set[tuple[str, UUID]] = set()
        for value in _rows(due["parts"], 500):
            part = _object(
                value,
                {
                    "source_kind",
                    "source_id",
                    "approved_due_date",
                    "source_occurred_at",
                    "outstanding_usd_cents",
                    "amount_usd_cents",
                },
            )
            source = _source(part)
            if source in sources:
                raise PreviewInputError("Duplicate confirmation source")
            sources.add(source)
            approved = part["approved_due_date"]
            occurred = part["source_occurred_at"]
            if (
                not isinstance(approved, str)
                or date.fromisoformat(approved).isoformat() != approved
            ):
                raise PreviewInputError("An exact approved date is required")
            if not isinstance(occurred, str) or "T" not in occurred:
                raise PreviewInputError("A timezone-aware source timestamp is required")
            instant = datetime.fromisoformat(occurred)
            if instant.tzinfo is None or instant.utcoffset() is None:
                raise PreviewInputError("A timezone-aware source timestamp is required")
            applied = _amount(part["amount_usd_cents"])
            if applied > _amount(part["outstanding_usd_cents"], MAX_BALANCE):
                raise PreviewInputError("Confirmed amount exceeds the source")
            selected_total += applied
            count += 1
            if count > 500:
                raise PreviewInputError("Whole confirmation exceeds its part bound")
        if selected_total != amount:
            raise PreviewInputError("Confirmation parts do not match the line")
    if actual != expected:
        raise PreviewInputError("Confirmation lines do not match the Invoice")
