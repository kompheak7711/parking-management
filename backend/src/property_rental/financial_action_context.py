"""Purpose-bound selected financial sources; commands retain final authority."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import cast
from uuid import UUID

import psycopg
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

ACTION_CAPABILITIES = {
    "allocation": "payments.allocate",
    "allocation_reversal": "payments.allocations.reverse",
    "receipt_reprint": "receipts.reprint",
    "credit_recognition": "credits.recognize",
    "credit_reversal": "credits.reverse",
    "credit_application": "credits.apply",
    "credit_application_reversal": "credits.applications.reverse",
    "refund_return": "refunds.correct",
    "refund_correction_reversal": "refunds.corrections.reverse",
}
CURSOR = re.compile(
    r"([0-9a-f]{64}):([1-9][0-9]{0,4}):([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})"
)
MAX_ACTION_CONTEXT_BYTES = 1_000_000


class FinancialActionContextChanged(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FinancialActionContextRequest:
    purpose: str
    source_id: UUID
    target_kind: str | None = None
    target_id: UUID | None = None
    refund_id: UUID | None = None
    limit: int = 50
    cursor: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.purpose, str) or self.purpose not in ACTION_CAPABILITIES:
            raise PaymentReadInvalidError("Invalid financial action context")
        _uuid(self.source_id)
        if self.target_kind is not None and (
            not isinstance(self.target_kind, str)
            or self.target_kind not in {"INVOICE", "LATE_PAYMENT_CHARGE"}
            or self.purpose not in {"allocation", "credit_application"}
        ):
            raise PaymentReadInvalidError("Invalid financial action target")
        if (self.target_kind is None) != (self.target_id is None):
            raise PaymentReadInvalidError("Financial target fields must be paired")
        if (self.purpose == "refund_correction_reversal") != (self.refund_id is not None):
            raise PaymentReadInvalidError("Invalid original Refund context")
        for identity in (self.target_id, self.refund_id):
            if identity is not None:
                _uuid(identity)
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise PaymentReadInvalidError("Invalid financial action page size")
        if self.cursor is not None:
            if not isinstance(self.cursor, str) or (match := CURSOR.fullmatch(self.cursor)) is None:
                raise PaymentReadInvalidError("Invalid financial action cursor")
            if int(match[2]) > 32767:
                raise PaymentReadInvalidError("Invalid financial detail sequence")
            _uuid(UUID(match[3]))

    @property
    def anchor(self) -> tuple[str | None, int | None, UUID | None]:
        if self.cursor is None:
            return None, None, None
        revision, sequence, identity = self.cursor.split(":")
        return revision, int(sequence), UUID(identity)


def _unavailable() -> PaymentReadUnavailableError:
    return PaymentReadUnavailableError("Financial action context is unavailable")


def _encode(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise _unavailable() from exc


@dataclass(frozen=True, slots=True)
class FinancialActionContextService:
    database_url: str | None

    def get(
        self,
        property_id: UUID,
        request: FinancialActionContextRequest,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        _uuid(property_id)
        checked = FinancialActionContextRequest(
            request.purpose,
            request.source_id,
            request.target_kind,
            request.target_id,
            request.refund_id,
            request.limit,
            request.cursor,
        )
        if not is_authorized(
            actor, AuthorizationRequirement(ACTION_CAPABILITIES[checked.purpose], str(property_id))
        ):
            raise PaymentReadAuthorizationError("Financial action context is not authorized")
        expected, after_sequence, after_id = checked.anchor
        source: dict[str, object] | None = None
        with FinancialReferenceService(self.database_url)._read(actor, property_id) as connection:
            set_json_loads(_exact_json, connection)
            try:
                row = connection.execute(
                    "SELECT app.financial_action_context_page(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        property_id,
                        UUID(actor.actor_id),
                        checked.purpose,
                        checked.source_id,
                        checked.refund_id,
                        checked.target_kind,
                        checked.target_id,
                        checked.limit,
                        after_sequence,
                        after_id,
                    ),
                ).fetchone()
            except psycopg.Error as exc:
                if exc.sqlstate == "P4501":
                    raise PaymentReadNotFoundError("Financial source was not found") from exc
                if exc.sqlstate == "P4506":
                    raise PaymentReadAuthorizationError("Financial actor is not active") from exc
                if exc.sqlstate == "22023":
                    raise PaymentReadInvalidError("Invalid financial action context") from exc
                raise
            if row is None or len(row) != 1 or not isinstance(row[0], dict):
                raise _unavailable()
            raw = row[0]
            if set(raw) != {
                "source_payment_id",
                "context",
                "target",
                "revision_evidence",
                "unsupported_application",
                "anchor_found",
                "items",
            }:
                raise _unavailable()
            payment_id = raw["source_payment_id"]
            if payment_id is not None:
                try:
                    identity = UUID(payment_id)
                    _uuid(identity)
                    if str(identity) != payment_id:
                        raise ValueError
                except (ValueError, TypeError, AttributeError) as exc:
                    raise _unavailable() from exc
                original = connection.execute(_DETAIL, (property_id, identity)).fetchone()
                if original is None or len(original) != 1 or not isinstance(original[0], dict):
                    raise _unavailable()
                source = original[0]
        if raw["unsupported_application"] is not False or not isinstance(raw["context"], dict):
            raise _unavailable()
        if raw["target"] is not None and not isinstance(raw["target"], dict):
            raise _unavailable()
        evidence = raw["revision_evidence"]
        counters = {
            "payment_revision",
            "deposit_count",
            "deposit_revision",
            "target_count",
            "target_revision",
        }
        binding = {
            "property": str(property_id),
            "purpose": checked.purpose,
            "source": str(checked.source_id),
            "refund": str(checked.refund_id) if checked.refund_id else None,
            "requested_target_kind": checked.target_kind,
            "requested_target": str(checked.target_id) if checked.target_id else None,
            "payment": payment_id,
        }
        if (
            not isinstance(evidence, dict)
            or set(evidence) != counters | set(binding) | {"payment_status"}
            or any(evidence[k] != value for k, value in binding.items())
            or any(type(evidence[k]) is not int or evidence[k] < 0 for k in counters)
            or evidence["payment_status"]
            not in ({"RECEIVED", "REVERSED"} if payment_id else {None})
        ):
            raise _unavailable()
        # Include bounded visible source/target facts as well as the complete guard
        # vector, so a changed display or draft target cannot cross a page boundary.
        revision = hashlib.sha256(
            _encode([evidence, source, raw["context"], raw["target"]])
        ).hexdigest()
        if expected is not None and expected != revision:
            raise FinancialActionContextChanged("Financial context changed; reload it")
        if raw["anchor_found"] is not True:
            raise PaymentReadInvalidError("Financial action cursor was not found")
        items = raw["items"]
        if not isinstance(items, list) or len(items) > checked.limit + 1:
            raise _unavailable()
        kind = {
            "allocation_reversal": "ALLOCATION_LINE",
            "credit_application_reversal": "CREDIT_APPLICATION_LINE",
        }.get(checked.purpose)
        if (
            checked.purpose in {"allocation", "credit_application"}
            and checked.target_kind == "INVOICE"
        ):
            kind = "INVOICE_LINE"
        if kind is None and items:
            raise _unavailable()
        previous = (after_sequence or 0, after_id.int if after_id else 0)
        for item in items:
            if not isinstance(item, dict) or set(item) != {"sequence", "id", "kind", "data"}:
                raise _unavailable()
            sequence = item["sequence"]
            if type(sequence) is not int or not 1 <= sequence <= 32767 or item["kind"] != kind:
                raise _unavailable()
            try:
                identity = UUID(item["id"])
                _uuid(identity)
            except (ValueError, TypeError, AttributeError) as exc:
                raise _unavailable() from exc
            if (
                str(identity) != item["id"]
                or (sequence, identity.int) <= previous
                or not isinstance(item["data"], dict)
            ):
                raise _unavailable()
            previous = (sequence, identity.int)
        visible = items[: checked.limit]
        cursor = None
        if len(items) > checked.limit:
            last = visible[-1]
            cursor = f"{revision}:{last['sequence']}:{last['id']}"
        result = {
            "property_id": str(property_id),
            "purpose": checked.purpose,
            "source_id": str(checked.source_id),
            "refund_id": binding["refund"],
            "requested_target_kind": checked.target_kind,
            "requested_target_id": binding["requested_target"],
            "payment_resource": source,
            "context": raw["context"],
            "target": raw["target"],
            "revision": revision,
            "items": visible,
        }
        if len(_encode(result)) > MAX_ACTION_CONTEXT_BYTES:
            raise _unavailable()
        return {"data": cast(dict[str, object], result), "next_cursor": cursor}
