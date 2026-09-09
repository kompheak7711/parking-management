"""Coherent, scoped runtime reads of the authoritative Customer ledger projection."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import cast
from uuid import UUID

import psycopg
from psycopg.types.json import set_json_loads

from property_rental.customer_ledger import (
    EVENT_ORDER,
    LedgerCursor,
    LedgerEventKey,
    LedgerInvalidError,
    LedgerPosition,
    exact_cents,
)
from property_rental.customer_ledger_query import (
    BALANCE_FIELDS,
    LEDGER_CAPABILITY,
    LedgerDetailCursor,
    LedgerReadRequest,
    composition_key,
    digest,
    identity,
)
from property_rental.identity import AuthenticatedActor


class LedgerNotFoundError(LookupError):
    pass


class LedgerAuthorizationError(PermissionError):
    pass


class LedgerUnavailableError(RuntimeError):
    pass


def _mapping(value: object, keys: set[str] | None = None) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise LedgerInvalidError("Invalid ledger response object")
    if keys is not None and set(value) != keys:
        raise LedgerInvalidError("Invalid ledger response fields")
    return cast(dict[str, object], value)


def _uuid(value: object) -> UUID:
    if not isinstance(value, str):
        raise LedgerInvalidError("Invalid ledger response identity")
    result = identity(UUID(value))
    if str(result) != value:
        raise LedgerInvalidError("Noncanonical ledger identity")
    return result


def _text(value: object, maximum: int = 4000) -> str:
    if not isinstance(value, str) or len(value.encode()) > maximum:
        raise LedgerInvalidError("Invalid ledger response text")
    return value


def _count(value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= 2**53 - 1:
        raise LedgerInvalidError("Invalid ledger response count")
    return value


def _position(value: object) -> LedgerPosition:
    row = _mapping(value, set(LedgerPosition.fields))
    return LedgerPosition(**{k: exact_cents(row[k]) for k in LedgerPosition.fields})


def _exact_json(value: str | bytes) -> object:
    return json.loads(value, parse_float=str)


def _audit(value: object, depth: int = 0) -> object:
    if depth > 12:
        raise LedgerInvalidError("Ledger source evidence exceeds depth bound")
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        return str(value)
    if isinstance(value, str):
        return _text(value, 1_048_576)
    if isinstance(value, list) and len(value) <= 1000:
        return [_audit(v, depth + 1) for v in value]
    if isinstance(value, dict) and len(value) <= 1000:
        return {_text(k, 200): _audit(v, depth + 1) for k, v in value.items()}
    raise LedgerInvalidError("Invalid ledger source evidence")


_LINKS = {
    "invoice_id",
    "late_payment_charge_id",
    "payment_id",
    "customer_credit_id",
    "deposit_id",
    "refund_id",
}
_COMMON = {
    "property_id",
    "customer_id",
    "event_kind",
    "event_order",
    "event_id",
    "occurred_at",
    "business_date",
    "source_table",
    "source_reference",
    "recorded_amount_usd_cents",
    "source_audit",
} | _LINKS
_HISTORY = (
    _COMMON
    | {"component_count"}
    | {
        k + suffix
        for k in LedgerPosition.fields
        for suffix in ("_effect_usd_cents", "_after_usd_cents")
    }
)
_COMPONENT = _COMMON | {
    "invoice_line_id",
    "balance_kind",
    "balance_source_id",
    "effect_usd_cents",
    "category",
    "description",
    "detail_key",
}
_COMPOSITION = {
    "property_id",
    "customer_id",
    "balance_kind",
    "balance_source_id",
    "invoice_id",
    "invoice_line_id",
    "late_payment_charge_id",
    "category",
    "description",
    "balance_usd_cents",
    "detail_key",
}


def _scope(row: dict[str, object], prop: UUID, customer: UUID) -> None:
    if _uuid(row["property_id"]) != prop or _uuid(row["customer_id"]) != customer:
        raise LedgerInvalidError("Ledger response scope mismatch")


def _row(
    value: object, query: LedgerReadRequest, prop: UUID, customer: UUID
) -> tuple[dict[str, object], LedgerEventKey | str]:
    page_key: LedgerEventKey | str
    row = dict(
        _mapping(
            value,
            {"history": _HISTORY, "components": _COMPONENT, "composition": _COMPOSITION}[
                query.section
            ],
        )
    )
    _scope(row, prop, customer)
    for key in _LINKS | {"invoice_line_id", "balance_source_id"}:
        if row.get(key) is not None:
            _uuid(row[key])
    for key in ("source_reference", "category", "description"):
        if row.get(key) is not None:
            _text(row[key])
    if query.section == "composition":
        page_key = composition_key(row["detail_key"])
        if page_key != str(row["balance_kind"]) + ":" + str(row["balance_source_id"]):
            raise LedgerInvalidError("Invalid balance source key")
        if exact_cents(row["balance_usd_cents"]) <= 0:
            raise LedgerInvalidError("Composition must describe remaining value")
    else:
        kind = _text(row["event_kind"], 80)
        instant = datetime.fromisoformat(_text(row["occurred_at"], 64))
        event = LedgerEventKey(instant, kind, _uuid(row["event_id"]))
        if type(row["event_order"]) is not int or row["event_order"] != EVENT_ORDER[kind]:
            raise LedgerInvalidError("Invalid ledger event order")
        day = _text(row["business_date"], 10)
        if date.fromisoformat(day).isoformat() != day:
            raise LedgerInvalidError("Invalid ledger business date")
        if re.fullmatch("[a-z_]{1,80}", _text(row["source_table"], 80)) is None:
            raise LedgerInvalidError("Invalid ledger source type")
        source_audit = _mapping(row["source_audit"])
        if len(json.dumps(source_audit, allow_nan=False).encode()) > 1_048_576:
            raise LedgerInvalidError("Ledger source evidence exceeds bound")
        row["source_audit"] = _audit(source_audit)
        if query.section == "history":
            if not query.filters.includes(event):
                raise LedgerInvalidError("Ledger response violates history filter")
            _count(row["component_count"], minimum=1)
            position = LedgerPosition(
                **{k: exact_cents(row[k + "_after_usd_cents"]) for k in LedgerPosition.fields}
            )
            row["position_after_instant"] = position.as_wire()
            for k in LedgerPosition.fields:
                del row[k + "_after_usd_cents"]
            page_key = event
        else:
            if (event.event_kind, event.event_id) != (query.event_kind, query.event_id):
                raise LedgerInvalidError("Ledger component belongs to another event")
            page_key = digest(row["detail_key"])
            if row["balance_kind"] not in {*BALANCE_FIELDS, "NONE"}:
                raise LedgerInvalidError("Invalid ledger component balance")
            if (
                row["balance_kind"] == "NONE"
                and exact_cents(row["effect_usd_cents"], signed=True) != 0
            ):
                raise LedgerInvalidError("Presentation history has a financial effect")
    for k, v in row.items():
        if k.endswith("_usd_cents") and v is not None:
            row[k] = str(
                exact_cents(v, signed=k == "effect_usd_cents" or k.endswith("_effect_usd_cents"))
            )
    return row, page_key


def _actor_scope(actor: AuthenticatedActor) -> tuple[UUID, list[UUID]]:
    try:
        actor_id = _uuid(actor.actor_id)
        properties = sorted(
            {
                _uuid(p)
                for g in actor.capability_grants
                if g.capability == LEDGER_CAPABILITY
                for p in g.property_ids
            }
        )
    except (LedgerInvalidError, ValueError, TypeError, AttributeError) as exc:
        raise LedgerAuthorizationError("Ledger authorization is invalid") from exc
    if not properties:
        raise LedgerAuthorizationError("Ledger read permission is required")
    return actor_id, properties


def _json_result(
    connection: psycopg.Connection[tuple[object, ...]], sql: str, parameters: tuple[object, ...]
) -> dict[str, object]:
    row = connection.execute(sql, parameters).fetchone()
    if not isinstance(row, tuple) or len(row) != 1:
        raise LedgerUnavailableError("Ledger read response is unavailable")
    try:
        return _mapping(row[0])
    except LedgerInvalidError as exc:
        raise LedgerUnavailableError("Ledger read response is invalid") from exc


@dataclass(frozen=True, slots=True)
class CustomerLedgerReadService:
    database_url: str | None

    @contextmanager
    def _read(self) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
        if self.database_url is None:
            raise LedgerUnavailableError("Ledger reads are unavailable")
        try:
            with psycopg.connect(self.database_url, connect_timeout=3) as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                connection.execute("SET LOCAL TIME ZONE 'UTC'")
                set_json_loads(_exact_json, connection)
                yield connection
        except psycopg.Error as exc:
            if exc.sqlstate == "P4501":
                raise LedgerNotFoundError("Ledger resource was not found") from exc
            if exc.sqlstate in {"P4506", "42501"}:
                raise LedgerAuthorizationError("Ledger access is denied") from exc
            if exc.sqlstate == "22023":
                raise LedgerInvalidError("Ledger request is invalid") from exc
            raise LedgerUnavailableError("Ledger reads are unavailable") from exc

    def get(
        self,
        customer_id: UUID,
        query: LedgerReadRequest,
        *,
        actor: AuthenticatedActor,
        expected_property: UUID | None = None,
    ) -> dict[str, object]:
        identity(customer_id)
        if not isinstance(query, LedgerReadRequest):
            raise LedgerInvalidError("Invalid ledger request")
        if expected_property is not None:
            identity(expected_property)
        actor_id, properties = _actor_scope(actor)
        with self._read() as connection:
            scoped = connection.execute(
                "SELECT app.credit_refund_http_scope(%s,%s,%s,%s::uuid[])",
                ("customer", customer_id, actor_id, properties),
            ).fetchone()
            if not isinstance(scoped, tuple) or len(scoped) != 1 or scoped[0] not in properties:
                raise LedgerUnavailableError("Ledger scope response is invalid")
            prop = identity(scoped[0])
            if expected_property is not None and prop != expected_property:
                raise LedgerNotFoundError("Ledger resource was not found")
            snapshot = _json_result(
                connection,
                "SELECT app.customer_ledger_snapshot(%s,%s,%s)",
                (prop, customer_id, actor_id),
            )
            try:
                _mapping(
                    snapshot,
                    {
                        "property_id",
                        "customer_id",
                        "customer_name",
                        "revision",
                        "position",
                        "history_position",
                        "event_count",
                    },
                )
                _scope(snapshot, prop, customer_id)
                name = _text(snapshot["customer_name"])
                revision = digest(snapshot["revision"])
                position = _position(snapshot["position"])
                position.reconcile(_position(snapshot["history_position"]))
                count = _count(snapshot["event_count"])
            except (
                ValueError,
                TypeError,
                KeyError,
                OverflowError,
                UnicodeError,
                RuntimeError,
            ) as exc:
                raise LedgerUnavailableError("Ledger snapshot could not be reconciled") from exc
            query.validate_snapshot(prop, customer_id, revision)
            cursor = query.decoded_cursor()
            after = cursor.after if isinstance(cursor, LedgerCursor) else None
            result = _json_result(
                connection,
                "SELECT app.customer_ledger_page(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    prop,
                    customer_id,
                    actor_id,
                    query.section,
                    query.limit,
                    query.filters.from_instant,
                    query.filters.through_instant,
                    query.filters.event_kind,
                    query.event_kind,
                    query.event_id,
                    after.occurred_at if after else None,
                    after.event_kind if after else None,
                    after.event_id if after else None,
                    cursor.after if isinstance(cursor, LedgerDetailCursor) else None,
                ),
            )
        try:
            _mapping(result, {"property_id", "customer_id", "section", "items", "more"})
            _scope(result, prop, customer_id)
            if result["section"] != query.section or type(result["more"]) is not bool:
                raise LedgerInvalidError("Invalid ledger page metadata")
            raw_items = result["items"]
            if not isinstance(raw_items, list) or len(raw_items) > query.limit:
                raise LedgerInvalidError("Invalid ledger page length")
            if result["more"] and len(raw_items) != query.limit:
                raise LedgerInvalidError("Incomplete ledger continuation page")
            if len(json.dumps(result, allow_nan=False).encode()) > 4_194_304:
                raise LedgerInvalidError("Ledger page exceeds response bound")
            rows = [_row(item, query, prop, customer_id) for item in raw_items]
            previous: tuple[datetime, int, str, UUID] | str | None = None
            if cursor is not None:
                previous = cursor.after.order if isinstance(cursor, LedgerCursor) else cursor.after
            for _, key in rows:
                order = key.order if isinstance(key, LedgerEventKey) else key
                if previous is not None:
                    if isinstance(order, tuple):
                        if not isinstance(previous, tuple) or order <= previous:
                            raise LedgerInvalidError("Ledger page is not strictly ordered")
                    elif not isinstance(previous, str) or order <= previous:
                        raise LedgerInvalidError("Ledger page is not strictly ordered")
                previous = order
            next_cursor = (
                query.next_cursor(prop, customer_id, revision, rows[-1][1])
                if result["more"]
                else None
            )
            return {
                "data": {
                    "property_id": str(prop),
                    "customer_id": str(customer_id),
                    "customer_name": name,
                    "source_revision": revision,
                    "position": position.as_wire(),
                    "event_count": count,
                    "section": query.section,
                    "items": [r for r, _ in rows],
                },
                "next_cursor": next_cursor,
            }
        except (
            ValueError,
            TypeError,
            KeyError,
            OverflowError,
            UnicodeError,
            RecursionError,
        ) as exc:
            raise LedgerUnavailableError("Ledger page response is invalid") from exc

    def customers(
        self,
        limit: int,
        after: UUID | None,
        *,
        actor: AuthenticatedActor,
        expected_property: UUID | None = None,
    ) -> dict[str, object]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise LedgerInvalidError("Invalid ledger Customer limit")
        if after is not None:
            identity(after)
        if expected_property is not None:
            identity(expected_property)
        actor_id, properties = _actor_scope(actor)
        with self._read() as connection:
            result = _json_result(
                connection,
                "SELECT app.customer_ledger_customers(%s,%s::uuid[],%s,%s)",
                (actor_id, properties, limit, after),
            )
        try:
            _mapping(result, {"property_id", "items", "more"})
            prop = _uuid(result["property_id"])
            if prop not in properties:
                raise LedgerInvalidError("Ledger Customer scope mismatch")
            if expected_property is not None and prop != expected_property:
                raise LedgerNotFoundError("Ledger resource was not found")
            rows = result["items"]
            if not isinstance(rows, list) or len(rows) > limit or type(result["more"]) is not bool:
                raise LedgerInvalidError("Invalid ledger Customer page")
            if result["more"] and len(rows) != limit:
                raise LedgerInvalidError("Incomplete ledger Customer page")
            previous = after
            for row in rows:
                item = _mapping(row, {"id", "legal_name"})
                key = _uuid(item["id"])
                if previous is not None and key <= previous:
                    raise LedgerInvalidError("Ledger Customer page is not ordered")
                _text(item["legal_name"])
                previous = key
            return {
                "property_id": str(prop),
                "items": rows,
                "next_cursor": str(previous) if result["more"] else None,
            }
        except (ValueError, TypeError, KeyError, OverflowError, UnicodeError) as exc:
            raise LedgerUnavailableError("Ledger Customer response is invalid") from exc
