"""Strict, scoped dated-source choices; previews and commands retain final authority."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import cast
from uuid import UUID

import psycopg
from psycopg.types.json import set_json_loads

from property_rental.financial_reference import FinancialReferenceService
from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized
from property_rental.payment_read import (
    PaymentReadAuthorizationError,
    PaymentReadInvalidError,
    PaymentReadNotFoundError,
    PaymentReadUnavailableError,
    _exact_json,
    _uuid,
)

DUE_SOURCE_CAPABILITIES = {"allocation": "payments.allocate", "credit_application": "credits.apply"}
MAX_BALANCE = 9_223_372_036_854_775_807
MAX_RESPONSE_BYTES = 100_000
KINDS = {"ORIGINAL_LINE", "DEBIT_ADJUSTMENT"}
REVISION = re.compile(r"[0-9a-f]{64}")
CURSOR = re.compile(
    r"([0-9a-f]{64}):(ORIGINAL_LINE|DEBIT_ADJUSTMENT):"
    r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})"
)
INSTANT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})"
)


class FinancialDueSourcesChanged(RuntimeError):
    """Current source facts changed or require resolved legacy attribution."""


@dataclass(frozen=True, slots=True)
class FinancialDueSourcesRequest:
    purpose: str
    source_id: UUID
    invoice_id: UUID
    invoice_line_id: UUID
    limit: int = 50
    cursor: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.purpose, str) or self.purpose not in DUE_SOURCE_CAPABILITIES:
            raise PaymentReadInvalidError("Invalid dated-source purpose")
        for identity in (self.source_id, self.invoice_id, self.invoice_line_id):
            _uuid(identity)
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise PaymentReadInvalidError("Invalid dated-source page size")
        if self.cursor is not None:
            if (
                not isinstance(self.cursor, str)
                or len(self.cursor) > 120
                or (match := CURSOR.fullmatch(self.cursor)) is None
            ):
                raise PaymentReadInvalidError("Invalid dated-source cursor")
            _uuid(UUID(match[3]))

    @property
    def anchor(self) -> tuple[str | None, str | None, UUID | None]:
        if self.cursor is None:
            return None, None, None
        revision, kind, identity = self.cursor.split(":")
        return revision, kind, UUID(identity)


def _unavailable() -> PaymentReadUnavailableError:
    return PaymentReadUnavailableError("Dated sources are unavailable")


def _integer(value: object, minimum: int, maximum: int = MAX_BALANCE) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _unavailable()
    return value


def _identity(value: object) -> UUID:
    if not isinstance(value, str) or len(value) != 36:
        raise _unavailable()
    try:
        identity = UUID(value)
    except ValueError as exc:
        raise _unavailable() from exc
    if identity.int == 0 or str(identity) != value:
        raise _unavailable()
    return identity


def _instant(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 40 or INSTANT.fullmatch(value) is None:
        raise _unavailable()
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _unavailable() from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _unavailable()
    return parsed


def _day(value: object) -> date:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise _unavailable()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _unavailable() from exc


def _projection(
    value: object, property_id: UUID, request: FinancialDueSourcesRequest
) -> dict[str, object]:
    binding = {
        "property_id": str(property_id),
        "purpose": request.purpose,
        "source_id": str(request.source_id),
        "invoice_id": str(request.invoice_id),
        "invoice_line_id": str(request.invoice_line_id),
    }
    if not isinstance(value, dict) or set(value) != set(binding) | {
        "invoice_version",
        "revision",
        "as_of",
        "aggregate_outstanding_usd_cents",
        "item_count",
        "has_more",
        "items",
    }:
        raise _unavailable()
    raw = cast(dict[str, object], value)
    if any(raw[key] != expected for key, expected in binding.items()):
        raise _unavailable()
    _integer(raw["invoice_version"], 1, 9_999_999_999)
    revision = raw["revision"]
    if not isinstance(revision, str) or REVISION.fullmatch(revision) is None:
        raise _unavailable()
    expected, after_kind, after_id = request.anchor
    if expected is not None and expected != revision:
        raise FinancialDueSourcesChanged("Dated sources changed; reload the selection")
    at = _instant(raw["as_of"])
    aggregate = _integer(raw["aggregate_outstanding_usd_cents"], 0)
    count = _integer(raw["item_count"], 0)
    more, items = raw["has_more"], raw["items"]
    if (
        type(more) is not bool
        or not isinstance(items, list)
        or len(items) > min(request.limit, count)
    ):
        raise _unavailable()
    if (
        (count == 0) != (aggregate == 0)
        or count > aggregate
        or (
            expected is None
            and (len(items) != min(request.limit, count) or more != (count > request.limit))
        )
        or (expected is not None and (count < 1 or len(items) >= count))
        or (more and (len(items) != request.limit or count <= len(items) + (1 if expected else 0)))
    ):
        raise _unavailable()
    previous: tuple[date, datetime, str, int] | None = None
    seen: set[tuple[str, UUID]] = set()
    total = 0
    for item in items:
        if not isinstance(item, dict) or set(item) != {
            "source_kind",
            "source_id",
            "approved_due_date",
            "source_occurred_at",
            "remaining_usd_cents",
        }:
            raise _unavailable()
        kind = item["source_kind"]
        if not isinstance(kind, str) or kind not in KINDS:
            raise _unavailable()
        identity = _identity(item["source_id"])
        pair = kind, identity
        if (
            pair in seen
            or pair == (after_kind, after_id)
            or (kind == "ORIGINAL_LINE" and identity != request.invoice_line_id)
        ):
            raise _unavailable()
        seen.add(pair)
        occurred = _instant(item["source_occurred_at"])
        if occurred > at:
            raise _unavailable()
        order = _day(item["approved_due_date"]), occurred, kind, identity.int
        if previous is not None and order <= previous:
            raise _unavailable()
        previous = order
        total += _integer(item["remaining_usd_cents"], 1)
    if total > aggregate or (expected is None and not more and total != aggregate):
        raise _unavailable()
    try:
        encoded = json.dumps(
            raw, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise _unavailable() from exc
    if len(encoded) > MAX_RESPONSE_BYTES:
        raise _unavailable()
    next_cursor = None
    if more:
        last = items[-1]
        next_cursor = f"{revision}:{last['source_kind']}:{last['source_id']}"
    return {"data": {k: v for k, v in raw.items() if k != "has_more"}, "next_cursor": next_cursor}


@dataclass(frozen=True, slots=True)
class FinancialDueSourcesService:
    database_url: str | None

    def get(
        self, property_id: UUID, request: FinancialDueSourcesRequest, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        _uuid(property_id)
        checked = FinancialDueSourcesRequest(
            request.purpose,
            request.source_id,
            request.invoice_id,
            request.invoice_line_id,
            request.limit,
            request.cursor,
        )
        if not is_authorized(
            actor,
            AuthorizationRequirement(DUE_SOURCE_CAPABILITIES[checked.purpose], str(property_id)),
        ):
            raise PaymentReadAuthorizationError("Dated sources are not authorized")
        expected, after_kind, after_id = checked.anchor
        with FinancialReferenceService(self.database_url)._read(actor, property_id) as connection:
            set_json_loads(_exact_json, connection)
            try:
                row = connection.execute(
                    "SELECT app.financial_invoice_due_sources_page(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        property_id,
                        UUID(actor.actor_id),
                        checked.purpose,
                        checked.source_id,
                        checked.invoice_id,
                        checked.invoice_line_id,
                        checked.limit,
                        expected,
                        after_kind,
                        after_id,
                    ),
                ).fetchone()
            except psycopg.Error as exc:
                if exc.sqlstate == "P4501":
                    raise PaymentReadNotFoundError("Dated source was not found") from exc
                if exc.sqlstate == "P4506":
                    raise PaymentReadAuthorizationError("Financial actor is not active") from exc
                if exc.sqlstate == "22023":
                    raise PaymentReadInvalidError("Invalid dated-source selection") from exc
                if exc.sqlstate == "P4507":
                    raise FinancialDueSourcesChanged(
                        "Dated sources require reloading or resolved attribution"
                    ) from exc
                raise
            if row is None or len(row) != 1:
                raise _unavailable()
            return _projection(row[0], property_id, checked)
