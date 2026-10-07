"""Exact positions and bounded, snapshot-bound Customer ledger read contracts.

These values describe a projection. They cannot create or change a financial source.
Authorization belongs to the scoped read service, never to possession of a cursor.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

EVENT_ORDER: Mapping[str, int] = {
    "INVOICE_ISSUED": 10,
    "INVOICE_ADJUSTED": 20,
    "INVOICE_ADJUSTMENT_REVERSED": 21,
    "DEPOSIT_REQUIREMENT_ADJUSTED": 22,
    "LATE_PAYMENT_WAIVED": 25,
    "LATE_PAYMENT_CHARGED": 30,
    "LATE_PAYMENT_CORRECTED": 31,
    "PAYMENT_RECEIVED": 40,
    "DEPOSIT_RECEIVED": 45,
    "DEPOSIT_RECEIPT_REVERSED": 46,
    "PAYMENT_ALLOCATED": 50,
    "PAYMENT_ALLOCATION_REVERSED": 51,
    "CREDIT_RECOGNIZED": 60,
    "CREDIT_RECOGNITION_REVERSED": 61,
    "CREDIT_APPLIED": 70,
    "CREDIT_APPLICATION_REVERSED": 71,
    "DEPOSIT_APPLIED": 75,
    "DEPOSIT_APPLICATION_REVERSED": 76,
    "DEPOSIT_DISPOSED": 80,
    "DEPOSIT_DISPOSITION_REVERSED": 81,
    "REFUND_PAID": 82,
    "REFUND_CORRECTED": 83,
    "INVOICE_VOIDED": 90,
    "DRAFT_INVOICE_VOIDED": 90,
    "PAYMENT_REVERSED": 99,
}
MAX_CURSOR_BYTES = 1024
MAX_MONEY_DIGITS = 64


class LedgerInvalidError(ValueError):
    pass


class LedgerSnapshotChangedError(RuntimeError):
    pass


class LedgerReconciliationError(RuntimeError):
    pass


def exact_cents(value: object, *, signed: bool = False) -> int:
    """Accept exact database NUMERIC/integers and canonical decimal strings only."""
    if type(value) is int:
        result = value
    elif isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise LedgerInvalidError("Ledger money must be an exact integer")
        # Bound conversion before int() so exponent-form hostile values are cheap.
        if value and value.adjusted() >= MAX_MONEY_DIGITS:
            raise LedgerInvalidError("Ledger money exceeds the exact read bound")
        result = int(value)
    elif isinstance(value, str) and re.fullmatch(r"-?(0|[1-9][0-9]{0,63})", value):
        if value == "-0":
            raise LedgerInvalidError("Ledger money is not canonical")
        result = int(value)
    else:
        raise LedgerInvalidError("Ledger money must be an exact integer")
    if abs(result) >= 10**MAX_MONEY_DIGITS or (not signed and result < 0):
        raise LedgerInvalidError("Ledger money is outside the read contract")
    return result


def _identity(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise LedgerInvalidError("A non-nil ledger identity is required")


def _instant(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise LedgerInvalidError("Ledger timestamps require a timezone")
    try:
        return value.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise LedgerInvalidError("Ledger timestamp is outside the read contract") from exc


@dataclass(frozen=True, slots=True)
class LedgerPosition:
    invoice: int = 0
    charge: int = 0
    credit: int = 0
    payment: int = 0
    security_deposit: int = 0
    pet_deposit: int = 0

    fields: ClassVar[tuple[str, ...]] = (
        "invoice",
        "charge",
        "credit",
        "payment",
        "security_deposit",
        "pet_deposit",
    )

    def __post_init__(self) -> None:
        for field in self.fields:
            value = getattr(self, field)
            if type(value) is not int:
                raise LedgerInvalidError("Ledger positions require integer cents")
            exact_cents(value)
        exact_cents(self.total_owed)

    @property
    def total_owed(self) -> int:
        return self.invoice + self.charge

    def as_wire(self) -> dict[str, str]:
        # Even small values use the same exact string transport as large totals.
        return {field + "_usd_cents": str(getattr(self, field)) for field in self.fields} | {
            "total_owed_usd_cents": str(self.total_owed)
        }

    def reconcile(self, authoritative: LedgerPosition) -> None:
        if self != authoritative:
            raise LedgerReconciliationError("Ledger history and source position disagree")


@dataclass(frozen=True, slots=True)
class LedgerEventKey:
    occurred_at: datetime
    event_kind: str
    event_id: UUID

    def __post_init__(self) -> None:
        object.__setattr__(self, "occurred_at", _instant(self.occurred_at))
        if not isinstance(self.event_kind, str) or self.event_kind not in EVENT_ORDER:
            raise LedgerInvalidError("Unknown ledger event kind")
        _identity(self.event_id)

    @property
    def order(self) -> tuple[datetime, int, str, UUID]:
        return self.occurred_at, EVENT_ORDER[self.event_kind], self.event_kind, self.event_id


@dataclass(frozen=True, slots=True)
class LedgerFilter:
    from_instant: datetime | None = None
    through_instant: datetime | None = None
    event_kind: str | None = None

    def __post_init__(self) -> None:
        for field in ("from_instant", "through_instant"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _instant(value))
        if self.from_instant is not None and self.through_instant is not None:
            if self.from_instant > self.through_instant:
                raise LedgerInvalidError("Ledger filter dates are reversed")
        if self.event_kind is not None and (
            not isinstance(self.event_kind, str) or self.event_kind not in EVENT_ORDER
        ):
            raise LedgerInvalidError("Unknown ledger filter kind")

    def includes(self, key: LedgerEventKey) -> bool:
        return (
            (self.from_instant is None or key.occurred_at >= self.from_instant)
            and (self.through_instant is None or key.occurred_at <= self.through_instant)
            and (self.event_kind is None or key.event_kind == self.event_kind)
        )

    def fingerprint(self, property_id: UUID, customer_id: UUID) -> str:
        _identity(property_id)
        _identity(customer_id)
        data = [
            str(property_id),
            str(customer_id),
            self.from_instant.isoformat() if self.from_instant else None,
            self.through_instant.isoformat() if self.through_instant else None,
            self.event_kind,
        ]
        return hashlib.sha256(json.dumps(data, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class LedgerCursor:
    scope: str
    revision: str
    after: LedgerEventKey

    def __post_init__(self) -> None:
        for value in (self.scope, self.revision):
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise LedgerInvalidError("Invalid ledger cursor fingerprint")
        if not isinstance(self.after, LedgerEventKey):
            raise LedgerInvalidError("Invalid ledger cursor key")

    def encode(self) -> str:
        payload = [
            1,
            self.scope,
            self.revision,
            self.after.occurred_at.isoformat(),
            self.after.event_kind,
            str(self.after.event_id),
        ]
        return base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        ).decode()

    @classmethod
    def decode(cls, value: str) -> LedgerCursor:
        if not isinstance(value, str) or not 1 <= len(value) <= MAX_CURSOR_BYTES:
            raise LedgerInvalidError("Invalid ledger cursor length")
        try:
            raw = base64.b64decode(value, altchars=b"-_", validate=True)
            data = json.loads(raw)
            if (
                not isinstance(data, list)
                or len(data) != 6
                or type(data[0]) is not int
                or data[0] != 1
            ):
                raise LedgerInvalidError("Invalid ledger cursor version")
            if not all(isinstance(item, str) for item in data[1:]):
                raise LedgerInvalidError("Invalid ledger cursor fields")
            result = cls(
                data[1],
                data[2],
                LedgerEventKey(datetime.fromisoformat(data[3]), data[4], UUID(data[5])),
            )
            if result.encode() != value:
                raise LedgerInvalidError("Ledger cursor is not canonical")
            return result
        except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError) as exc:
            raise LedgerInvalidError("Invalid ledger cursor") from exc

    def validate_snapshot(self, *, scope: str, revision: str) -> None:
        if self.scope != scope:
            raise LedgerInvalidError("Ledger cursor belongs to another scope or filter")
        if self.revision != revision:
            raise LedgerSnapshotChangedError("Financial history changed; refresh the ledger")


@dataclass(frozen=True, slots=True)
class LedgerPage:
    limit: int = 50
    filters: LedgerFilter = LedgerFilter()
    cursor: LedgerCursor | None = None

    def __post_init__(self) -> None:
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise LedgerInvalidError("Ledger page limit must be from 1 through 100")
        if not isinstance(self.filters, LedgerFilter) or (
            self.cursor is not None and not isinstance(self.cursor, LedgerCursor)
        ):
            raise LedgerInvalidError("Invalid ledger page")
