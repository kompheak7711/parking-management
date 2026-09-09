"""Strict selectors and snapshot-bound paging for the read-only Customer ledger."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from uuid import UUID

from property_rental.customer_ledger import (
    EVENT_ORDER,
    LedgerCursor,
    LedgerEventKey,
    LedgerFilter,
    LedgerInvalidError,
    LedgerSnapshotChangedError,
)

LEDGER_CAPABILITY = "customer_ledger.read"
BALANCE_FIELDS = {
    "INVOICE": "invoice",
    "LATE_PAYMENT_CHARGE": "charge",
    "CREDIT": "credit",
    "UNALLOCATED_PAYMENT": "payment",
    "SECURITY_DEPOSIT": "security_deposit",
    "PET_DEPOSIT": "pet_deposit",
}


def identity(value: object) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise LedgerInvalidError("A non-nil ledger identity is required")
    return value


def digest(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise LedgerInvalidError("Invalid ledger fingerprint")
    return value


def composition_key(value: object) -> str:
    if not isinstance(value, str) or len(value) > 80:
        raise LedgerInvalidError("Invalid ledger source key")
    kind, separator, source = value.partition(":")
    try:
        if not separator or kind not in BALANCE_FIELDS or str(identity(UUID(source))) != source:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise LedgerInvalidError("Invalid ledger source key") from exc
    return value


@dataclass(frozen=True, slots=True)
class LedgerDetailCursor:
    scope: str
    revision: str
    after: str

    def __post_init__(self) -> None:
        digest(self.scope)
        digest(self.revision)
        if not isinstance(self.after, str) or not 1 <= len(self.after) <= 80:
            raise LedgerInvalidError("Invalid ledger detail cursor key")

    def encode(self) -> str:
        return base64.urlsafe_b64encode(
            json.dumps([1, self.scope, self.revision, self.after], separators=(",", ":")).encode()
        ).decode()

    @classmethod
    def decode(cls, value: str) -> LedgerDetailCursor:
        try:
            if not isinstance(value, str) or not 1 <= len(value) <= 1024:
                raise ValueError
            data = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
            if (
                not isinstance(data, list)
                or len(data) != 4
                or type(data[0]) is not int
                or data[0] != 1
            ):
                raise ValueError
            result = cls(*data[1:])
            if result.encode() != value:
                raise ValueError
            return result
        except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError) as exc:
            raise LedgerInvalidError("Invalid ledger detail cursor") from exc

    def validate_snapshot(self, *, scope: str, revision: str) -> None:
        if self.scope != scope:
            raise LedgerInvalidError("Ledger cursor belongs to another selection")
        if self.revision != revision:
            raise LedgerSnapshotChangedError("Financial sources changed; refresh the ledger")


@dataclass(frozen=True, slots=True)
class LedgerReadRequest:
    section: str = "history"
    limit: int = 50
    filters: LedgerFilter = field(default_factory=LedgerFilter)
    event_kind: str | None = None
    event_id: UUID | None = None
    revision: str | None = None
    cursor: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.section, str) or self.section not in {
            "history",
            "composition",
            "components",
        }:
            raise LedgerInvalidError("Invalid ledger section")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise LedgerInvalidError("Ledger page limit must be from 1 through 100")
        if not isinstance(self.filters, LedgerFilter):
            raise LedgerInvalidError("Invalid ledger filters")
        if self.section != "history" and self.filters != LedgerFilter():
            raise LedgerInvalidError("History filters cannot select source details")
        if self.section == "components":
            if not isinstance(self.event_kind, str) or self.event_kind not in EVENT_ORDER:
                raise LedgerInvalidError("A known source event is required")
            identity(self.event_id)
        elif self.event_kind is not None or self.event_id is not None:
            raise LedgerInvalidError("Event selection requires the components section")
        if self.revision is not None:
            digest(self.revision)
        if self.cursor is not None:
            decoded = self.decoded_cursor()
            assert decoded is not None
            if self.revision is not None and decoded.revision != self.revision:
                raise LedgerInvalidError("Cursor and requested snapshot disagree")

    def fingerprint(self, property_id: UUID, customer_id: UUID) -> str:
        return hashlib.sha256(
            json.dumps(
                [
                    self.filters.fingerprint(property_id, customer_id),
                    self.section,
                    self.event_kind,
                    str(self.event_id) if self.event_id else None,
                ],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    def decoded_cursor(self) -> LedgerCursor | LedgerDetailCursor | None:
        if self.cursor is None:
            return None
        if self.section == "history":
            return LedgerCursor.decode(self.cursor)
        result = LedgerDetailCursor.decode(self.cursor)
        if self.section == "composition":
            composition_key(result.after)
        else:
            digest(result.after)
        return result

    def validate_snapshot(self, property_id: UUID, customer_id: UUID, revision: str) -> None:
        digest(revision)
        cursor = self.decoded_cursor()
        if cursor is not None:
            cursor.validate_snapshot(
                scope=self.fingerprint(property_id, customer_id), revision=revision
            )
        if self.revision is not None and self.revision != revision:
            raise LedgerSnapshotChangedError("Financial sources changed; refresh the ledger")

    def next_cursor(
        self, property_id: UUID, customer_id: UUID, revision: str, after: LedgerEventKey | str
    ) -> str:
        scope = self.fingerprint(property_id, customer_id)
        if self.section == "history":
            if not isinstance(after, LedgerEventKey):
                raise LedgerInvalidError("Invalid history page key")
            return LedgerCursor(scope, revision, after).encode()
        if not isinstance(after, str):
            raise LedgerInvalidError("Invalid detail page key")
        return LedgerDetailCursor(scope, revision, after).encode()
