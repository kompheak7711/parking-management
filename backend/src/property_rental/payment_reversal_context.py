"""Read-only Payment reversal impact and historically affected current balances."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from psycopg.types.json import set_json_loads

from property_rental.financial_reference import FinancialReferenceService
from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized
from property_rental.payment_read import (
    _DETAIL,
    PaymentReadAuthorizationError,
    PaymentReadInvalidError,
    PaymentReadNotFoundError,
    PaymentReadUnavailableError,
    _exact_json,
    _uuid,
)

MAX_CONTEXT_DATA_BYTES = 1_000_000
IMPACT_KINDS = (
    "ALLOCATION",
    "ALLOCATION_LINE",
    "CREDIT",
    "CREDIT_APPLICATION",
    "CREDIT_APPLICATION_LINE",
    "DEPOSIT_RECEIPT",
    "DEPOSIT_DISPOSITION",
    "REFUND",
)
RESULT_KINDS = ("INVOICE", "LATE_PAYMENT_CHARGE", "CREDIT", "DEPOSIT")
CURSOR = re.compile(r"([0-9a-f]{64}):([1-8]):([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})")


class PaymentReversalContextChanged(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReversalContextPage:
    view: Literal["impact", "result"] = "impact"
    limit: int = 50
    cursor: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.view, str)
            or self.view not in {"impact", "result"}
            or type(self.limit) is not int
            or not 1 <= self.limit <= 100
        ):
            raise PaymentReadInvalidError("Invalid reversal context page")
        if self.cursor is not None:
            if not isinstance(self.cursor, str) or (match := CURSOR.fullmatch(self.cursor)) is None:
                raise PaymentReadInvalidError("Invalid reversal context cursor")
            _uuid(UUID(match[3]))
            if self.view == "result" and int(match[2]) > 4:
                raise PaymentReadInvalidError("Invalid reversal result cursor")

    @property
    def anchor(self) -> tuple[str | None, int | None, UUID | None]:
        if self.cursor is None:
            return None, None, None
        revision, kind, identity = self.cursor.split(":")
        return revision, int(kind), UUID(identity)


def _unavailable() -> PaymentReadUnavailableError:
    return PaymentReadUnavailableError("Payment reversal context is unavailable")


@dataclass(frozen=True, slots=True)
class PaymentReversalContextService:
    database_url: str | None

    def get(
        self,
        property_id: UUID,
        payment_id: UUID,
        page: ReversalContextPage,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        _uuid(property_id)
        if not is_authorized(actor, AuthorizationRequirement("payments.reverse", str(property_id))):
            raise PaymentReadAuthorizationError("Payment reversal context is not authorized")
        _uuid(payment_id)
        checked = ReversalContextPage(page.view, page.limit, page.cursor)
        expected, ordinal, after_id = checked.anchor
        with FinancialReferenceService(self.database_url)._read(actor, property_id) as connection:
            set_json_loads(_exact_json, connection)
            source = connection.execute(_DETAIL, (property_id, payment_id)).fetchone()
            if source is None:
                raise PaymentReadNotFoundError("Payment was not found")
            if len(source) != 1 or not isinstance(source[0], dict):
                raise _unavailable()
            row = connection.execute(
                "SELECT app.payment_reversal_context_page(%s,%s,%s,%s,%s,%s,%s)",
                (
                    property_id,
                    payment_id,
                    UUID(actor.actor_id),
                    checked.view,
                    checked.limit,
                    ordinal,
                    after_id,
                ),
            ).fetchone()
        if row is None or len(row) != 1 or not isinstance(row[0], dict):
            raise _unavailable()
        raw = row[0]
        if raw.get("unsupported_application") is not False:
            raise _unavailable()
        evidence = raw.get("revision_evidence")
        counters = {
            "payment_revision",
            "deposit_count",
            "deposit_revision",
            "target_count",
            "target_revision",
        }
        if (
            not isinstance(evidence, dict)
            or set(evidence) != counters | {"property", "payment", "view", "payment_status"}
            or evidence["property"] != str(property_id)
            or evidence["payment"] != str(payment_id)
            or evidence["view"] != checked.view
            or evidence["payment_status"] not in {"RECEIVED", "REVERSED"}
            or any(type(evidence[k]) is not int or evidence[k] < 0 for k in counters)
        ):
            raise _unavailable()
        revision = hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if expected is not None and expected != revision:
            raise PaymentReversalContextChanged("Payment reversal context changed; reload it")
        if raw.get("anchor_found") is not True:
            raise PaymentReadInvalidError("Reversal context cursor was not found")
        items = raw.get("items")
        if not isinstance(items, list) or len(items) > checked.limit + 1:
            raise _unavailable()
        kinds = IMPACT_KINDS if checked.view == "impact" else RESULT_KINDS
        previous = (ordinal or 0, after_id.int if after_id else 0)
        for item in items:
            if not isinstance(item, dict) or set(item) != {"ordinal", "kind", "id", "data"}:
                raise _unavailable()
            index = item["ordinal"]
            if (
                type(index) is not int
                or not 1 <= index <= len(kinds)
                or item["kind"] != kinds[index - 1]
            ):
                raise _unavailable()
            try:
                identity = UUID(item["id"])
                _uuid(identity)
            except (ValueError, TypeError, AttributeError) as exc:
                raise _unavailable() from exc
            if (
                str(identity) != item["id"]
                or (index, identity.int) <= previous
                or not isinstance(item["data"], dict)
            ):
                raise _unavailable()
            previous = (index, identity.int)
        visible = items[: checked.limit]
        cursor = None
        if len(items) > checked.limit:
            last = visible[-1]
            cursor = f"{revision}:{last['ordinal']}:{last['id']}"
        result = {
            "payment_resource": source[0],
            "view": checked.view,
            "revision": revision,
            "items": visible,
        }
        try:
            size = len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
            raise _unavailable() from exc
        if size > MAX_CONTEXT_DATA_BYTES:
            raise _unavailable()
        return {"data": cast(dict[str, object], result), "next_cursor": cursor}
