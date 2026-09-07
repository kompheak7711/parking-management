"""Fresh-human, capability-scoped runtime reads for Credit/Refund HTTP adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

import psycopg
from psycopg.types.json import set_json_loads

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized

Resource = Literal[
    "property", "customer", "payment", "credit", "credit_application", "refund", "deposit"
]
RESOURCE_KINDS = frozenset(
    {"property", "customer", "payment", "credit", "credit_application", "refund", "deposit"}
)
MAX_SOURCE_AUDIT_BYTES = 1_048_576


class FinancialReadNotFoundError(LookupError):
    pass


class FinancialReadAuthorizationError(PermissionError):
    pass


class FinancialReadInvalidError(ValueError):
    pass


class FinancialReadUnavailableError(RuntimeError):
    pass


def _uuid(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise FinancialReadInvalidError("A non-nil UUID is required")


def _actor_id(actor: AuthenticatedActor) -> UUID:
    try:
        identity = UUID(actor.actor_id)
        _uuid(identity)
        return identity
    except (ValueError, TypeError, AttributeError) as exc:
        raise FinancialReadAuthorizationError("Financial actor is not authorized") from exc


def _exact_json(value: str | bytes) -> object:
    return json.loads(value, parse_float=str)


@dataclass(frozen=True, slots=True)
class CreditRefundReadService:
    database_url: str | None

    def _query(self, sql: str, parameters: tuple[object, ...]) -> object:
        if self.database_url is None:
            raise FinancialReadUnavailableError("Financial reads are unavailable")
        try:
            with psycopg.connect(self.database_url, connect_timeout=3) as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                connection.execute("SET LOCAL TIME ZONE 'UTC'")
                set_json_loads(_exact_json, connection)
                row = connection.execute(sql, parameters).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate in {"42501", "P4506"}:
                raise FinancialReadAuthorizationError("Financial actor is not authorized") from exc
            if exc.sqlstate == "P4501":
                raise FinancialReadNotFoundError("Financial resource was not found") from exc
            if exc.sqlstate == "22023":
                raise FinancialReadInvalidError("Financial scope is invalid") from exc
            raise FinancialReadUnavailableError("Financial reads are unavailable") from exc
        if row is None:
            raise FinancialReadNotFoundError("Financial resource was not found")
        if not isinstance(row, tuple) or len(row) != 1:
            raise FinancialReadUnavailableError("Financial read response is invalid")
        if row[0] is None:
            raise FinancialReadNotFoundError("Financial resource was not found")
        return cast(object, row[0])

    def resolve(
        self, resource: Resource, identity: UUID, capability: str, *, actor: AuthenticatedActor
    ) -> UUID:
        if resource not in RESOURCE_KINDS:
            raise FinancialReadInvalidError("Financial resource kind is invalid")
        _uuid(identity)
        actor_id = _actor_id(actor)
        try:
            properties = sorted(
                {
                    UUID(value)
                    for grant in actor.capability_grants
                    if grant.capability == capability
                    for value in grant.property_ids
                }
            )
            for prop in properties:
                _uuid(prop)
        except (ValueError, TypeError, AttributeError) as exc:
            raise FinancialReadAuthorizationError("Financial scope is not authorized") from exc
        if not properties:
            raise FinancialReadNotFoundError("Financial resource was not found")
        result = self._query(
            "SELECT app.credit_refund_http_scope(%s,%s,%s,%s::uuid[])",
            (resource, identity, actor_id, properties),
        )
        if not isinstance(result, UUID) or result not in properties:
            raise FinancialReadUnavailableError("Financial scope response is invalid")
        return result

    def source_audit(
        self,
        property_id: UUID,
        source_kind: Literal["PAYMENT", "CREDIT"],
        source_id: UUID,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        _uuid(property_id)
        _uuid(source_id)
        if source_kind not in {"PAYMENT", "CREDIT"}:
            raise FinancialReadInvalidError("Financial source kind is invalid")
        if not is_authorized(actor, AuthorizationRequirement("refunds.create", str(property_id))):
            raise FinancialReadAuthorizationError("Refund source is not authorized")
        result = self._query(
            "SELECT app.credit_refund_http_source_audit(%s,%s,%s,%s)",
            (property_id, source_kind, source_id, _actor_id(actor)),
        )
        if not isinstance(result, dict):
            raise FinancialReadUnavailableError("Financial source response is invalid")
        payment = result.get("source_payment")
        if not isinstance(payment, dict) or payment.get("property_id") != str(property_id):
            raise FinancialReadUnavailableError("Financial source scope is invalid")
        if source_kind == "PAYMENT" and payment.get("id") != str(source_id):
            raise FinancialReadUnavailableError("Financial source identity is invalid")
        try:
            size = len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode())
        except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
            raise FinancialReadUnavailableError("Financial source evidence is invalid") from exc
        if size > MAX_SOURCE_AUDIT_BYTES:
            raise FinancialReadUnavailableError("Financial source evidence exceeds read bound")
        return cast(dict[str, object], result)
