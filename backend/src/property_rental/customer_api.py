"""Authenticated Customer resources with minimized lists and preserved history."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from threading import Lock
from time import monotonic
from typing import Annotated, Final, Protocol, cast
from uuid import UUID

import psycopg
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from property_rental.auth_api import CSRF_COOKIE_NAME
from property_rental.customer import (
    CUSTOMER_CONNECT_TIMEOUT_SECONDS,
    CUSTOMER_LOCK_TIMEOUT_MS,
    ID_DOCUMENT_NUMBER_MAX_LENGTH,
    Customer,
    CustomerCommandContext,
    CustomerIdentityAlreadyExistsError,
    CustomerIdNumberInUse,
    CustomerRepository,
    CustomerReuseRequired,
    CustomerService,
    CustomerVersionConflict,
    PostgresCustomerRepository,
    _customer_from_row,
    canonical_email,
    id_document_match_key,
    normalize_optional,
)
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.settings import Settings

CUSTOMER_READ_CAPABILITY: Final = "customers.read"
CUSTOMER_MANAGE_CAPABILITY: Final = "customers.manage"
AUDIT_VIEW_CAPABILITY: Final = "audit.view"
DEFAULT_PAGE_SIZE: Final = 50
MAX_PAGE_SIZE: Final = 100
DEFAULT_DEPOSIT_PAGE_SIZE: Final = 50
CUSTOMER_QUERY_TIMEOUT_MS: Final = 3_000
CUSTOMER_SEARCH_WINDOW_SECONDS: Final = 1.0
CUSTOMER_SEARCH_MAX_REQUESTS: Final = 20
CUSTOMER_SEARCH_MAX_KEYS: Final = 10_000
CUSTOMER_COMMAND_ACTIONS: Final = frozenset({"create", "update", "deactivate"})
POSTGRES_INTEGER_MAX: Final = 2_147_483_647


class CustomerResourceNotFound(LookupError):
    """Raised when a Customer or its Property context does not exist."""


class CustomerResourceUnavailable(RuntimeError):
    """Raised when Customer persistence is unavailable."""


class CustomerResourceInvalid(ValueError):
    """Raised when a Customer command violates the bounded contract."""


class CustomerCommandIdentityConflict(RuntimeError):
    """Raised when a client command identity is reused for different input."""


class CustomerIdempotencyKeyReused(CustomerCommandIdentityConflict):
    """Raised only when one idempotency key is reused with different canonical input."""


def _customer_command_parameter_error(
    exc: psycopg.errors.InvalidParameterValue,
) -> CustomerCommandIdentityConflict:
    """Classify the repository-owned SQL contract without exposing database diagnostics."""
    if "Customer command identity was reused for different input" in str(exc):
        return CustomerIdempotencyKeyReused("Customer idempotency key was reused")
    return CustomerCommandIdentityConflict("Customer command input was rejected")


class CustomerLifecycleConflict(RuntimeError):
    """Raised when a Customer lifecycle command targets an incompatible state."""

    def __init__(self, current_version: int) -> None:
        super().__init__("the Customer lifecycle state conflicts with the command")
        self.current_version = current_version


class CustomerSearchRateGuard(Protocol):
    def allow(self, *, actor_id: str, source: str, property_id: UUID) -> bool: ...


class PostgresCustomerSearchRateGuard:
    """Enforce one shared Customer-search budget across all API workers."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def allow(self, *, actor_id: str, source: str, property_id: UUID) -> bool:
        key = hashlib.sha256(f"{actor_id}\0{source}\0{property_id}".encode()).hexdigest()
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=CUSTOMER_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                PostgresCustomerResourceFlow._bound_query(connection)
                row = connection.execute(
                    "SELECT app.consume_customer_search_rate(%s, %s, %s)",
                    (key, CUSTOMER_SEARCH_MAX_REQUESTS, CUSTOMER_SEARCH_WINDOW_SECONDS),
                ).fetchone()
        except psycopg.Error as exc:
            raise CustomerResourceUnavailable(
                "Customer search rate protection is unavailable"
            ) from exc
        return row is not None and bool(row[0])


class SlidingWindowCustomerSearchRateGuard:
    """Bound Customer list/search pressure per actor, source, and Property."""

    def __init__(
        self,
        *,
        maximum: int = CUSTOMER_SEARCH_MAX_REQUESTS,
        maximum_keys: int = CUSTOMER_SEARCH_MAX_KEYS,
        window_seconds: float = CUSTOMER_SEARCH_WINDOW_SECONDS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._maximum = maximum
        self._maximum_keys = maximum_keys
        self._window_seconds = window_seconds
        self._clock = clock
        self._attempts: OrderedDict[tuple[str, str, UUID], deque[float]] = OrderedDict()
        self._lock = Lock()

    def allow(self, *, actor_id: str, source: str, property_id: UUID) -> bool:
        now = self._clock()
        key = (actor_id, source, property_id)
        with self._lock:
            cutoff = now - self._window_seconds
            attempts = self._attempts.get(key)
            if attempts is None:
                if len(self._attempts) >= self._maximum_keys:
                    expired = [
                        candidate
                        for candidate, timestamps in self._attempts.items()
                        if not timestamps or timestamps[-1] <= cutoff
                    ]
                    for candidate in expired:
                        del self._attempts[candidate]
                if len(self._attempts) >= self._maximum_keys:
                    return False
                attempts = deque()
                self._attempts[key] = attempts
            else:
                self._attempts.move_to_end(key)
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= self._maximum:
                return False
            attempts.append(now)
            return True


class CustomerReuseConflict(Exception):
    """Expose only minimized plausible matches for an explicit reuse decision."""

    def __init__(self, candidates: tuple[Customer, ...]) -> None:
        super().__init__("Customer reuse decision is required")
        self.candidates = candidates


class CustomerIdNumberConflict(Exception):
    """Another Customer has the same ID number (DL-071 answer 11)."""

    def __init__(self, existing: Customer | None) -> None:
        super().__init__("Customer ID number is already used")
        self.existing = existing


def customer_id_number_conflict_response(
    request: Request,
    exc: CustomerIdNumberConflict,
) -> JSONResponse:
    """Name only the existing Customer (id and name), never the number itself."""
    request_id = request.state.request_id
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": {
                "code": "CUSTOMER_ID_NUMBER_IN_USE",
                "message": (
                    "Another Customer already has this ID number or passport number. "
                    "Use the existing Customer."
                ),
                "fields": ["id_document_number"],
                "rule_ids": ["BR-CUST-002"],
                "current_version": None,
                "existing_customer": (
                    None
                    if exc.existing is None
                    else {
                        "customer_id": str(exc.existing.customer_id),
                        "legal_name": exc.existing.legal_name,
                    }
                ),
            },
            "meta": {"request_id": request_id},
        },
        headers={"X-Request-ID": request_id, "Cache-Control": "private, no-store"},
    )


def customer_idempotency_key_reused_response(request: Request) -> JSONResponse:
    """Return the dedicated API-016 error without exposing stored command input."""
    request_id = request.state.request_id
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": {
                "code": "IDEMPOTENCY_KEY_REUSED",
                "message": "The idempotency key was already used for different input.",
                "fields": [],
                "rule_ids": ["API-016"],
                "current_version": None,
            },
            "meta": {"request_id": request_id},
        },
        headers={"X-Request-ID": request_id},
    )


def customer_reuse_conflict_response(
    request: Request,
    exc: CustomerReuseConflict,
) -> JSONResponse:
    """Return a canonical minimized conflict without leaking match source fields."""
    request_id = request.state.request_id
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": {
                "code": "CUSTOMER_REUSE_REQUIRED",
                "message": " ".join(
                    (
                        "Review the possible existing Customer before",
                        "creating a distinct identity.",
                    )
                ),
                "fields": ["email_address", "phone_number"],
                "rule_ids": ["BR-CUST-002"],
                "current_version": None,
                "reuse_candidates": [
                    {
                        "customer_id": str(candidate.customer_id),
                        "legal_name": candidate.legal_name,
                    }
                    for candidate in exc.candidates
                ],
            },
            "meta": {"request_id": request_id},
        },
        headers={"X-Request-ID": request_id},
    )


@dataclass(frozen=True, slots=True)
class CustomerRecord:
    customer: Customer
    property_id: UUID
    deactivated_at: datetime | None = None
    deactivation_reason: str | None = None

    @property
    def active(self) -> bool:
        return self.deactivated_at is None


@dataclass(frozen=True, slots=True)
class CustomerPage:
    items: tuple[CustomerRecord, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class CustomerHistoryEvent:
    event_id: UUID
    occurred_at: datetime
    actor_id: UUID
    action: str
    reason: str
    previous_state: object | None
    resulting_state: object | None
    correlation_id: UUID
    outcome: str


@dataclass(frozen=True, slots=True)
class CustomerHistoryPage:
    items: tuple[CustomerHistoryEvent, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class CustomerCommandStatus:
    recorded: bool
    record: CustomerRecord | None
    event_id: UUID | None = None
    expired: bool = False


class CustomerResourceFlow(Protocol):
    def list(
        self,
        property_id: UUID,
        *,
        query: str | None,
        active: bool | None,
        limit: int,
        cursor: str | None,
    ) -> CustomerPage: ...

    def get(self, customer_id: UUID) -> CustomerRecord: ...

    def detail(
        self,
        customer_id: UUID,
        *,
        limit: int,
        cursor: str | None,
    ) -> tuple[CustomerRecord, CustomerHistoryPage]: ...

    def create(
        self,
        property_id: UUID,
        *,
        customer_id: UUID,
        legal_name: str,
        phone_number: str | None,
        email_address: str | None,
        contact_address: str | None,
        memo: str | None,
        confirmed_distinct: bool,
        actor_id: str,
        idempotency_key: UUID,
        request_digest: str,
        id_document_number: str | None = None,
    ) -> CustomerRecord: ...

    def update(
        self,
        customer_id: UUID,
        *,
        legal_name: str,
        phone_number: str | None,
        email_address: str | None,
        contact_address: str | None,
        memo: str | None,
        confirmed_distinct: bool,
        expected_version: int,
        actor_id: str,
        idempotency_key: UUID,
        request_digest: str,
        id_document_number: str | None = None,
    ) -> CustomerRecord: ...

    def deactivate(
        self,
        customer_id: UUID,
        *,
        reason: str,
        expected_version: int,
        actor_id: str,
        idempotency_key: UUID,
        request_digest: str,
    ) -> CustomerRecord: ...

    def command_status(
        self,
        *,
        property_id: UUID,
        customer_id: UUID,
        action: str,
        idempotency_key: UUID,
        actor_id: str,
        request_digest: str | None = None,
    ) -> CustomerCommandStatus: ...

    def command_history(
        self,
        *,
        property_id: UUID,
        customer_id: UUID,
        event_id: UUID,
    ) -> CustomerHistoryPage: ...

    def history(
        self,
        customer_id: UUID,
        *,
        property_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> CustomerHistoryPage: ...

    def financial_summary(
        self,
        customer_id: UUID,
        *,
        deposit_limit: int,
        deposit_cursor: str | None,
    ) -> dict[str, object]: ...


class UnavailableCustomerResourceFlow:
    """Fail closed when Customer persistence is not configured."""

    def _fail(self) -> None:
        raise CustomerResourceUnavailable("Customer persistence is unavailable")

    def list(
        self,
        property_id: UUID,
        *,
        query: str | None,
        active: bool | None,
        limit: int,
        cursor: str | None,
    ) -> CustomerPage:
        del property_id, query, active, limit, cursor
        self._fail()
        raise AssertionError

    def get(self, customer_id: UUID) -> CustomerRecord:
        del customer_id
        self._fail()
        raise AssertionError

    def detail(
        self,
        customer_id: UUID,
        *,
        limit: int,
        cursor: str | None,
    ) -> tuple[CustomerRecord, CustomerHistoryPage]:
        del customer_id, limit, cursor
        self._fail()
        raise AssertionError

    def create(
        self,
        property_id: UUID,
        *,
        customer_id: UUID,
        legal_name: str,
        phone_number: str | None,
        email_address: str | None,
        contact_address: str | None,
        memo: str | None,
        confirmed_distinct: bool,
        actor_id: str,
        idempotency_key: UUID,
        request_digest: str,
        id_document_number: str | None = None,
    ) -> CustomerRecord:
        del (
            property_id,
            customer_id,
            legal_name,
            phone_number,
            email_address,
            contact_address,
            memo,
            confirmed_distinct,
            actor_id,
            idempotency_key,
            request_digest,
            id_document_number,
        )
        self._fail()
        raise AssertionError

    def update(
        self,
        customer_id: UUID,
        *,
        legal_name: str,
        phone_number: str | None,
        email_address: str | None,
        contact_address: str | None,
        memo: str | None,
        confirmed_distinct: bool,
        expected_version: int,
        actor_id: str,
        idempotency_key: UUID,
        request_digest: str,
        id_document_number: str | None = None,
    ) -> CustomerRecord:
        del (
            customer_id,
            legal_name,
            phone_number,
            email_address,
            contact_address,
            memo,
            confirmed_distinct,
            expected_version,
            actor_id,
            idempotency_key,
            request_digest,
            id_document_number,
        )
        self._fail()
        raise AssertionError

    def deactivate(
        self,
        customer_id: UUID,
        *,
        reason: str,
        expected_version: int,
        actor_id: str,
        idempotency_key: UUID,
        request_digest: str,
    ) -> CustomerRecord:
        del customer_id, reason, expected_version, actor_id, idempotency_key, request_digest
        self._fail()
        raise AssertionError

    def command_status(
        self,
        *,
        property_id: UUID,
        customer_id: UUID,
        action: str,
        idempotency_key: UUID,
        actor_id: str,
        request_digest: str | None = None,
    ) -> CustomerCommandStatus:
        del property_id, customer_id, action, idempotency_key, actor_id, request_digest
        self._fail()
        raise AssertionError

    def command_history(
        self,
        *,
        property_id: UUID,
        customer_id: UUID,
        event_id: UUID,
    ) -> CustomerHistoryPage:
        del property_id, customer_id, event_id
        self._fail()
        raise AssertionError

    def history(
        self,
        customer_id: UUID,
        *,
        property_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> CustomerHistoryPage:
        del customer_id, property_id, limit, cursor
        self._fail()
        raise AssertionError

    def financial_summary(
        self,
        customer_id: UUID,
        *,
        deposit_limit: int,
        deposit_cursor: str | None,
    ) -> dict[str, object]:
        del customer_id, deposit_limit, deposit_cursor
        self._fail()
        raise AssertionError


def _encode_cursor(customer_id: UUID) -> str:
    raw = json.dumps(str(customer_id), separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> UUID | None:
    if cursor is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        value = json.loads(raw)
        if not isinstance(value, str):
            raise ValueError
        return UUID(value)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise CustomerResourceInvalid("cursor is invalid") from exc


def _encode_deposit_cursor(required_effective_date: date, deposit_id: UUID) -> str:
    raw = json.dumps(
        [required_effective_date.isoformat(), str(deposit_id)], separators=(",", ":")
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_deposit_cursor(cursor: str | None) -> tuple[date, UUID] | None:
    if cursor is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        value = json.loads(raw)
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError
        return date.fromisoformat(str(value[0])), UUID(str(value[1]))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise CustomerResourceInvalid("Deposit cursor is invalid") from exc


def _encode_history_cursor(occurred_at: datetime, event_id: UUID) -> str:
    raw = json.dumps([occurred_at.isoformat(), str(event_id)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_history_cursor(cursor: str | None) -> tuple[datetime, UUID] | None:
    if cursor is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        value = json.loads(raw)
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError
        occurred_at = datetime.fromisoformat(str(value[0]))
        if occurred_at.utcoffset() is None:
            raise ValueError
        return occurred_at.astimezone(UTC), UUID(str(value[1]))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise CustomerResourceInvalid("history cursor is invalid") from exc


def _command_digest(
    *,
    action: str,
    property_id: UUID,
    customer_id: UUID,
    payload: dict[str, object],
) -> str:
    serialized = json.dumps(
        {
            "action": action,
            "property_id": str(property_id),
            "customer_id": str(customer_id),
            "payload": payload,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _record(row: tuple[object, ...]) -> CustomerRecord:
    """Map a Customer row; the ID number, when read, is the eleventh column."""
    id_document_number = row[10] if len(row) > 10 else None
    return CustomerRecord(
        customer=_customer_from_row((*row[:7], id_document_number)),
        property_id=UUID(str(row[9])),
        deactivated_at=cast(datetime | None, row[7]),
        deactivation_reason=None if row[8] is None else str(row[8]),
    )


def _archived_lifecycle(
    action: str, resulting_state: dict[str, object]
) -> tuple[datetime | None, str | None]:
    if action in {"create", "update"}:
        return None, None
    if action != "deactivate":
        raise CustomerResourceUnavailable("Customer command audit evidence is unavailable")
    raw_deactivated_at = resulting_state.get("deactivated_at")
    raw_reason = resulting_state.get("deactivation_reason")
    if not isinstance(raw_deactivated_at, str) or not isinstance(raw_reason, str):
        raise CustomerResourceUnavailable("Customer command audit evidence is unavailable")
    try:
        deactivated_at = datetime.fromisoformat(raw_deactivated_at)
    except ValueError as exc:
        raise CustomerResourceUnavailable("Customer command audit evidence is unavailable") from exc
    if deactivated_at.utcoffset() is None or not raw_reason.strip():
        raise CustomerResourceUnavailable("Customer command audit evidence is unavailable")
    return deactivated_at, raw_reason


def _history_event(row: tuple[object, ...]) -> CustomerHistoryEvent:
    return CustomerHistoryEvent(
        event_id=UUID(str(row[0])),
        occurred_at=cast(datetime, row[1]),
        actor_id=UUID(str(row[2])),
        action=str(row[3]),
        reason=str(row[4]),
        previous_state=row[5],
        resulting_state=row[6],
        correlation_id=UUID(str(row[7])),
        outcome=str(row[8]),
    )


class PostgresCustomerResourceFlow:
    """Bounded Customer queries and history-preserving commands."""

    _columns: Final = (
        "customer.id, customer.legal_name, customer.phone_number, "
        "customer.email_address, customer.contact_address, customer.memo, "
        "customer.version, customer.deactivated_at, customer.deactivation_reason, "
        "property.id, customer.id_document_number"
    )
    _list_columns: Final = (
        "customer.id, left(customer.legal_name, 255), NULL::text, NULL::text, "
        "NULL::text, NULL::text, customer.version, customer.deactivated_at, "
        "NULL::text, property.id"
    )

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @staticmethod
    def _bound_query(connection: psycopg.Connection[tuple[object, ...]]) -> None:
        connection.execute(
            "SELECT pg_catalog.set_config('lock_timeout', %s, true)",
            (str(CUSTOMER_LOCK_TIMEOUT_MS),),
        )
        connection.execute(
            "SELECT pg_catalog.set_config('statement_timeout', %s, true)",
            (str(CUSTOMER_QUERY_TIMEOUT_MS),),
        )

    def _repository(
        self,
        actor_id: str,
        command: CustomerCommandContext | None = None,
    ) -> CustomerRepository:
        return PostgresCustomerRepository(self._database_url, UUID(actor_id), command)

    def _command_context(
        self,
        *,
        property_id: UUID,
        action: str,
        idempotency_key: UUID,
        request_digest: str,
    ) -> CustomerCommandContext:
        return CustomerCommandContext(property_id, action, idempotency_key, request_digest)

    def list(
        self,
        property_id: UUID,
        *,
        query: str | None,
        active: bool | None,
        limit: int,
        cursor: str | None,
    ) -> CustomerPage:
        decoded = _decode_cursor(cursor)
        clauses = ["property.id = %s"]
        parameters: list[object] = [property_id]
        if query is not None:
            normalized = query.strip()
            if not normalized or "\x00" in normalized:
                raise CustomerResourceInvalid("query must not be blank")
            clauses.append(
                "(left(lower(customer.legal_name), 255) "
                "LIKE lower(%s) ESCAPE E'\\\\' "
                "OR left(lower(customer.email_address), 320) "
                "LIKE lower(%s) ESCAPE E'\\\\' "
                "OR left(regexp_replace(customer.phone_number, '[^0-9]', '', 'g'), 100) "
                "LIKE %s ESCAPE E'\\\\')"
            )
            escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            phone_key = "".join(character for character in normalized if character in "0123456789")
            parameters.extend((f"{escaped}%", f"{escaped}%", f"{phone_key or escaped}%"))
        if active is not None:
            clauses.append(
                "customer.deactivated_at IS NULL"
                if active
                else "customer.deactivated_at IS NOT NULL"
            )
        if decoded is not None:
            clauses.append("customer.id > %s")
            parameters.append(decoded)
        parameters.append(limit + 1)
        sql = (
            f"SELECT {self._list_columns} FROM app.customers AS customer "
            "CROSS JOIN app.properties AS property WHERE "
            + " AND ".join(clauses)
            + " ORDER BY customer.id LIMIT %s"
        )
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=CUSTOMER_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                self._bound_query(connection)
                rows = connection.execute(sql, tuple(parameters)).fetchall()
                property_exists = connection.execute(
                    "SELECT 1 FROM app.properties WHERE id = %s", (property_id,)
                ).fetchone()
        except psycopg.Error as exc:
            raise CustomerResourceUnavailable("Customer persistence is unavailable") from exc
        if property_exists is None:
            raise CustomerResourceNotFound("Property was not found")
        records = tuple(_record(row) for row in rows[:limit])
        next_cursor = None
        if len(rows) > limit and records:
            last = records[-1].customer
            next_cursor = _encode_cursor(last.customer_id)
        return CustomerPage(records, next_cursor)

    def get(self, customer_id: UUID) -> CustomerRecord:
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=CUSTOMER_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                self._bound_query(connection)
                row = connection.execute(
                    f"SELECT {self._columns} FROM app.customers AS customer "
                    "CROSS JOIN app.properties AS property WHERE customer.id = %s",
                    (customer_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise CustomerResourceUnavailable("Customer persistence is unavailable") from exc
        if row is None:
            raise CustomerResourceNotFound("Customer was not found")
        return _record(row)

    def detail(
        self,
        customer_id: UUID,
        *,
        limit: int,
        cursor: str | None,
    ) -> tuple[CustomerRecord, CustomerHistoryPage]:
        """Read current Customer source data and history from one database snapshot."""
        decoded = _decode_history_cursor(cursor)
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=CUSTOMER_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                self._bound_query(connection)
                row = connection.execute(
                    f"SELECT {self._columns} FROM app.customers AS customer "
                    "CROSS JOIN app.properties AS property WHERE customer.id = %s",
                    (customer_id,),
                ).fetchone()
                if row is None:
                    raise CustomerResourceNotFound("Customer was not found")
                record = _record(row)
                history = self._history_page(
                    connection,
                    customer_id,
                    property_id=record.property_id,
                    limit=limit,
                    decoded_cursor=decoded,
                )
        except CustomerResourceNotFound:
            raise
        except psycopg.Error as exc:
            raise CustomerResourceUnavailable("Customer persistence is unavailable") from exc
        return record, history

    def create(
        self,
        property_id: UUID,
        *,
        customer_id: UUID,
        legal_name: str,
        phone_number: str | None,
        email_address: str | None,
        contact_address: str | None,
        memo: str | None,
        confirmed_distinct: bool,
        actor_id: str,
        idempotency_key: UUID,
        request_digest: str,
        id_document_number: str | None = None,
    ) -> CustomerRecord:
        replay = self.command_status(
            property_id=property_id,
            customer_id=customer_id,
            action="create",
            idempotency_key=idempotency_key,
            actor_id=actor_id,
            request_digest=request_digest,
        )
        if replay.recorded:
            if replay.record is None:
                raise CustomerCommandIdentityConflict("Customer command result is invalid")
            return replay.record
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=CUSTOMER_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                self._bound_query(connection)
                exists = connection.execute(
                    "SELECT 1 FROM app.properties WHERE id = %s", (property_id,)
                ).fetchone()
            if exists is None:
                raise CustomerResourceNotFound("Property was not found")
            try:
                created = CustomerService(
                    self._repository(
                        actor_id,
                        self._command_context(
                            property_id=property_id,
                            action="create",
                            idempotency_key=idempotency_key,
                            request_digest=request_digest,
                        ),
                    )
                ).create(
                    customer_id,
                    legal_name=legal_name,
                    phone_number=phone_number,
                    email_address=email_address,
                    contact_address=contact_address,
                    memo=memo,
                    confirmed_distinct=confirmed_distinct,
                    id_document_number=id_document_number,
                )
            except CustomerIdentityAlreadyExistsError:
                raise CustomerCommandIdentityConflict(
                    "Customer command identity was already used"
                ) from None
            return CustomerRecord(created, property_id)
        except (CustomerResourceNotFound, CustomerReuseRequired, CustomerIdNumberInUse):
            raise
        except psycopg.errors.InvalidParameterValue as exc:
            raise _customer_command_parameter_error(exc) from exc
        except ValueError as exc:
            raise CustomerResourceInvalid("Customer source fields are invalid") from exc
        except psycopg.Error as exc:
            raise CustomerResourceUnavailable("Customer persistence is unavailable") from exc

    def update(
        self,
        customer_id: UUID,
        *,
        legal_name: str,
        phone_number: str | None,
        email_address: str | None,
        contact_address: str | None,
        memo: str | None,
        confirmed_distinct: bool,
        expected_version: int,
        actor_id: str,
        idempotency_key: UUID,
        request_digest: str,
        id_document_number: str | None = None,
    ) -> CustomerRecord:
        initial = self.get(customer_id)
        replay = self.command_status(
            property_id=initial.property_id,
            customer_id=customer_id,
            action="update",
            idempotency_key=idempotency_key,
            actor_id=actor_id,
            request_digest=request_digest,
        )
        if replay.recorded:
            if replay.record is None:
                raise CustomerCommandIdentityConflict("Customer command result is invalid")
            return replay.record
        current = self.get(customer_id)
        if current.customer.version != expected_version:
            # An equivalent concurrent retry may have observed no command before
            # the first transaction committed. The version and command record are
            # committed atomically, so recheck the exact identity before returning
            # a stale-version conflict.
            replay = self.command_status(
                property_id=current.property_id,
                customer_id=customer_id,
                action="update",
                idempotency_key=idempotency_key,
                actor_id=actor_id,
                request_digest=request_digest,
            )
            if replay.recorded:
                if replay.record is None:
                    raise CustomerCommandIdentityConflict("Customer command result is invalid")
                return replay.record
            raise CustomerVersionConflict(current.customer.version)
        if not current.active:
            raise CustomerLifecycleConflict(current.customer.version)
        try:
            updated = CustomerService(
                self._repository(
                    actor_id,
                    self._command_context(
                        property_id=current.property_id,
                        action="update",
                        idempotency_key=idempotency_key,
                        request_digest=request_digest,
                    ),
                )
            ).update(
                current.customer,
                legal_name=legal_name,
                phone_number=phone_number,
                email_address=email_address,
                contact_address=contact_address,
                memo=memo,
                confirmed_distinct=confirmed_distinct,
                id_document_number=id_document_number,
            )
            return CustomerRecord(
                updated,
                current.property_id,
                current.deactivated_at,
                current.deactivation_reason,
            )
        except (CustomerReuseRequired, CustomerIdNumberInUse):
            raise
        except psycopg.errors.InvalidParameterValue as exc:
            raise _customer_command_parameter_error(exc) from exc
        except ValueError as exc:
            raise CustomerResourceInvalid("Customer source fields are invalid") from exc
        except psycopg.Error as exc:
            raise CustomerResourceUnavailable("Customer persistence is unavailable") from exc

    def deactivate(
        self,
        customer_id: UUID,
        *,
        reason: str,
        expected_version: int,
        actor_id: str,
        idempotency_key: UUID,
        request_digest: str,
    ) -> CustomerRecord:
        normalized = reason.strip()
        if not normalized:
            raise CustomerResourceInvalid("deactivation reason is required")
        current_record = self.get(customer_id)
        replay = self.command_status(
            property_id=current_record.property_id,
            customer_id=customer_id,
            action="deactivate",
            idempotency_key=idempotency_key,
            actor_id=actor_id,
            request_digest=request_digest,
        )
        if replay.recorded:
            if replay.record is None:
                raise CustomerCommandIdentityConflict("Customer command result is invalid")
            return replay.record
        if not current_record.active:
            raise CustomerLifecycleConflict(current_record.customer.version)
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=CUSTOMER_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                self._bound_query(connection)
                row = connection.execute(
                    "SELECT * FROM app.execute_customer_deactivate(%s, %s, %s, %s, %s, %s, %s)",
                    (
                        current_record.property_id,
                        idempotency_key,
                        request_digest,
                        customer_id,
                        normalized,
                        expected_version,
                        UUID(actor_id),
                    ),
                ).fetchone()
                if row is None:
                    current = connection.execute(
                        "SELECT version FROM app.customers WHERE id = %s", (customer_id,)
                    ).fetchone()
                    if current is None:
                        raise CustomerResourceNotFound("Customer was not found")
                    raise CustomerVersionConflict(int(str(current[0])))
            return CustomerRecord(
                _customer_from_row(row[:7]),
                current_record.property_id,
                deactivated_at=cast(datetime, row[7]),
                deactivation_reason=str(row[8]),
            )
        except (CustomerLifecycleConflict, CustomerResourceNotFound, CustomerVersionConflict):
            raise
        except psycopg.errors.InvalidParameterValue as exc:
            raise _customer_command_parameter_error(exc) from exc
        except psycopg.errors.CheckViolation as exc:
            fresh = self.get(customer_id)
            if not fresh.active:
                raise CustomerLifecycleConflict(fresh.customer.version) from exc
            raise CustomerResourceInvalid("deactivation reason is invalid") from exc
        except psycopg.Error as exc:
            raise CustomerResourceUnavailable("Customer persistence is unavailable") from exc

    def command_status(
        self,
        *,
        property_id: UUID,
        customer_id: UUID,
        action: str,
        idempotency_key: UUID,
        actor_id: str,
        request_digest: str | None = None,
    ) -> CustomerCommandStatus:
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=CUSTOMER_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                self._bound_query(connection)
                row = connection.execute(
                    "SELECT * FROM app.get_customer_command(%s, %s, %s, %s, %s, %s)",
                    (
                        UUID(actor_id),
                        property_id,
                        action,
                        idempotency_key,
                        customer_id,
                        request_digest,
                    ),
                ).fetchone()
                tombstone = None
                if row is None:
                    tombstone = connection.execute(
                        """
                        SELECT tombstone.customer_id, tombstone.event_id,
                               tombstone.request_digest, audit.resulting_state,
                               customer.legal_name, customer.phone_number,
                               customer.email_address, customer.contact_address,
                               customer.memo, customer.version,
                               customer.deactivated_at, customer.deactivation_reason
                        FROM app.customer_command_tombstones AS tombstone
                        JOIN app.audit_events AS audit
                          ON audit.id = tombstone.event_id
                         AND audit.actor_id = tombstone.actor_id
                         AND audit.property_id = tombstone.property_id
                         AND audit.customer_id = tombstone.customer_id
                         AND audit.outcome = 'SUCCEEDED'
                        JOIN app.customers AS customer
                          ON customer.id = tombstone.customer_id
                        WHERE tombstone.actor_id = %s
                          AND tombstone.property_id = %s
                          AND tombstone.action = %s
                          AND tombstone.idempotency_key = %s
                        """,
                        (UUID(actor_id), property_id, action, idempotency_key),
                    ).fetchone()
                    if tombstone is not None and (
                        UUID(str(tombstone[0])) != customer_id
                        or (request_digest is not None and str(tombstone[2]) != request_digest)
                    ):
                        raise CustomerIdempotencyKeyReused("Customer idempotency key was reused")
                    if tombstone is not None:
                        state = tombstone[3]
                        if not isinstance(state, dict):
                            raise CustomerResourceUnavailable(
                                "Customer command audit evidence is unavailable"
                            )

                        def archived_or_current(key: str, current_index: int) -> object:
                            return state[key] if key in state else tombstone[current_index]

                        deactivated_at, deactivation_reason = _archived_lifecycle(action, state)
                        row = (
                            tombstone[0],
                            archived_or_current("legal_name", 4),
                            archived_or_current("phone_number", 5),
                            archived_or_current("email_address", 6),
                            archived_or_current("contact_address", 7),
                            archived_or_current("memo", 8),
                            archived_or_current("version", 9),
                            deactivated_at,
                            deactivation_reason,
                            property_id,
                            tombstone[1],
                        )
        except psycopg.errors.InvalidParameterValue as exc:
            raise _customer_command_parameter_error(exc) from exc
        except psycopg.Error as exc:
            raise CustomerResourceUnavailable("Customer command status is unavailable") from exc
        return CustomerCommandStatus(
            row is not None,
            None if row is None else self._with_current_id_number(_record(row[:10])),
            None if row is None else UUID(str(row[10])),
            tombstone is not None,
        )

    def _with_current_id_number(self, record: CustomerRecord) -> CustomerRecord:
        """A replayed command shows the Customer's current ID number (V1-059 part B)."""
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=CUSTOMER_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                self._bound_query(connection)
                row = connection.execute(
                    "SELECT id_document_number FROM app.customers WHERE id = %s",
                    (record.customer.customer_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise CustomerResourceUnavailable("Customer command status is unavailable") from exc
        if row is None or row[0] is None:
            return record
        customer = record.customer
        return CustomerRecord(
            _customer_from_row(
                (
                    customer.customer_id,
                    customer.legal_name,
                    customer.phone_number,
                    customer.email_address,
                    customer.contact_address,
                    customer.memo,
                    customer.version,
                    row[0],
                )
            ),
            record.property_id,
            record.deactivated_at,
            record.deactivation_reason,
        )

    def command_history(
        self,
        *,
        property_id: UUID,
        customer_id: UUID,
        event_id: UUID,
    ) -> CustomerHistoryPage:
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=CUSTOMER_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                self._bound_query(connection)
                row = connection.execute(
                    """
                    SELECT id, occurred_at, actor_id, action, reason, previous_state,
                           resulting_state, correlation_id, outcome
                    FROM app.audit_events
                    WHERE id = %s AND property_id = %s AND customer_id = %s
                    """,
                    (event_id, property_id, customer_id),
                ).fetchone()
        except psycopg.Error as exc:
            raise CustomerResourceUnavailable("Customer command history is unavailable") from exc
        if row is None:
            return CustomerHistoryPage((), None)
        return CustomerHistoryPage((_history_event(row),), None)

    def history(
        self,
        customer_id: UUID,
        *,
        property_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> CustomerHistoryPage:
        decoded = _decode_history_cursor(cursor)
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=CUSTOMER_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                self._bound_query(connection)
                return self._history_page(
                    connection,
                    customer_id,
                    property_id=property_id,
                    limit=limit,
                    decoded_cursor=decoded,
                )
        except psycopg.Error as exc:
            raise CustomerResourceUnavailable("Customer history is unavailable") from exc

    @staticmethod
    def _history_page(
        connection: psycopg.Connection[tuple[object, ...]],
        customer_id: UUID,
        *,
        property_id: UUID,
        limit: int,
        decoded_cursor: tuple[datetime, UUID] | None,
    ) -> CustomerHistoryPage:
        parameters: list[object] = [property_id, customer_id]
        cursor_clause = ""
        if decoded_cursor is not None:
            cursor_clause = "AND (occurred_at, id) < (%s, %s)"
            parameters.extend(decoded_cursor)
        parameters.append(limit + 1)
        rows = connection.execute(
            f"""
            SELECT id, occurred_at, actor_id, action, reason, previous_state,
                   resulting_state, correlation_id, outcome
            FROM app.audit_events
            WHERE property_id = %s AND customer_id = %s
            {cursor_clause}
            ORDER BY occurred_at DESC, id DESC
            LIMIT %s
            """,
            tuple(parameters),
        ).fetchall()
        events = tuple(_history_event(row) for row in rows[:limit])
        next_cursor = None
        if len(rows) > limit and events:
            last = events[-1]
            next_cursor = _encode_history_cursor(last.occurred_at, last.event_id)
        return CustomerHistoryPage(events, next_cursor)

    def financial_summary(
        self,
        customer_id: UUID,
        *,
        deposit_limit: int,
        deposit_cursor: str | None,
    ) -> dict[str, object]:
        current = self.get(customer_id)
        decoded_cursor = _decode_deposit_cursor(deposit_cursor)
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=CUSTOMER_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                self._bound_query(connection)
                totals = connection.execute(
                    "SELECT count(*),"
                    "COALESCE(sum((snapshot.value->>'required_usd_cents')::bigint),0),"
                    "COALESCE(sum((snapshot.value->>'received_usd_cents')::bigint),0),"
                    "COALESCE(sum((snapshot.value->>'held_refundable_usd_cents')::bigint),0),"
                    "COALESCE(sum((snapshot.value->>'outstanding_required_usd_cents')::bigint),0) "
                    "FROM app.deposits AS deposit "
                    "LEFT JOIN app.reservations AS reservation "
                    "ON reservation.id=deposit.reservation_id "
                    "LEFT JOIN app.leases AS lease ON lease.id=deposit.lease_id "
                    "JOIN app.units AS unit "
                    "ON unit.id=COALESCE(reservation.unit_id,lease.unit_id) "
                    "CROSS JOIN LATERAL (SELECT app.deposit_snapshot(deposit.id) AS value) "
                    "AS snapshot "
                    "WHERE deposit.customer_id=%s AND unit.property_id=%s",
                    (customer_id, current.property_id),
                ).fetchone()
                if totals is None:
                    raise CustomerResourceUnavailable(
                        "Customer Deposit aggregate evidence is unavailable"
                    )
                cursor_clause = ""
                parameters: list[object] = [customer_id, current.property_id]
                if decoded_cursor is not None:
                    cursor_clause = "AND (deposit.required_effective_date,deposit.id)<(%s,%s) "
                    parameters.extend(decoded_cursor)
                parameters.append(deposit_limit + 1)
                rows = connection.execute(
                    "SELECT app.deposit_resource_snapshot(deposit.id) "
                    ",deposit.required_effective_date,deposit.id "
                    "FROM app.deposits AS deposit "
                    "LEFT JOIN app.reservations AS reservation "
                    "ON reservation.id=deposit.reservation_id "
                    "LEFT JOIN app.leases AS lease ON lease.id=deposit.lease_id "
                    "JOIN app.units AS unit "
                    "ON unit.id=COALESCE(reservation.unit_id,lease.unit_id) "
                    "WHERE deposit.customer_id=%s "
                    "AND unit.property_id=%s "
                    + cursor_clause
                    + "ORDER BY deposit.required_effective_date DESC,deposit.id DESC LIMIT %s",
                    tuple(parameters),
                ).fetchall()
        except psycopg.Error as exc:
            raise CustomerResourceUnavailable(
                "Customer Deposit liabilities are unavailable"
            ) from exc
        liabilities: list[dict[str, object]] = []
        for row in rows[:deposit_limit]:
            snapshot = row[0]
            if not isinstance(snapshot, dict):
                raise CustomerResourceUnavailable(
                    "Customer Deposit liability evidence is unavailable"
                )
            liabilities.append(
                {
                    "deposit_id": snapshot["deposit_id"],
                    "deposit_type": snapshot["deposit_type"],
                    "reservation_id": snapshot.get("reservation_id"),
                    "lease_id": snapshot.get("lease_id"),
                    "pet_approval_id": snapshot.get("pet_approval_id"),
                    "required_usd_cents": snapshot["required_usd_cents"],
                    "received_usd_cents": snapshot["received_usd_cents"],
                    "held_refundable_usd_cents": snapshot["held_refundable_usd_cents"],
                    "outstanding_required_usd_cents": snapshot["outstanding_required_usd_cents"],
                }
            )
        next_cursor = None
        if len(rows) > deposit_limit and liabilities:
            last = rows[deposit_limit - 1]
            next_cursor = _encode_deposit_cursor(cast(date, last[1]), UUID(str(last[2])))
        return {
            "source_status": "PARTIALLY_AVAILABLE",
            "source_availability": {
                "deposits": "AVAILABLE",
                "invoices": "UNAVAILABLE_NOT_IMPLEMENTED",
                "late_charges": "UNAVAILABLE_NOT_IMPLEMENTED",
                "payments": "UNAVAILABLE_NOT_IMPLEMENTED",
                "customer_credit": "UNAVAILABLE_NOT_IMPLEMENTED",
            },
            "currency_summaries": [],
            "deposit_liabilities": liabilities,
            "deposit_liabilities_page": {
                "next_cursor": next_cursor,
                "limit": deposit_limit,
            },
            "deposit_aggregate": {
                "count": int(str(totals[0])),
                "required_usd_cents": int(str(totals[1])),
                "received_usd_cents": int(str(totals[2])),
                "held_refundable_usd_cents": int(str(totals[3])),
                "outstanding_required_usd_cents": int(str(totals[4])),
            },
            "customer_credit_is_separate_from_deposit": True,
        }


def _normalize_required_command_text(value: object) -> object:
    """Normalize string input before Pydantic applies the canonical length bound."""
    return value.strip() if isinstance(value, str) else value


def _normalize_optional_command_text(value: object) -> object:
    """Normalize optional string input before Pydantic applies its length bound."""
    return normalize_optional(value) if isinstance(value, str) else value


class CustomerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: UUID
    legal_name: str = Field(min_length=1, max_length=255)
    phone_number: str | None = Field(default=None, max_length=100)
    email_address: str | None = Field(default=None, max_length=320)
    contact_address: str | None = Field(default=None, max_length=1000)
    memo: str | None = Field(default=None, max_length=5000)
    confirmed_distinct: StrictBool = False
    id_document_number: str = Field(min_length=1, max_length=ID_DOCUMENT_NUMBER_MAX_LENGTH)

    @field_validator("legal_name", "id_document_number", mode="before")
    @classmethod
    def normalize_legal_name(cls, value: object) -> object:
        del cls
        return _normalize_required_command_text(value)

    @field_validator("id_document_number")
    @classmethod
    def validate_id_document_number(cls, value: str) -> str:
        del cls
        _validate_customer_text(value)
        return _validate_id_document_number(value)

    @field_validator("phone_number", "email_address", "contact_address", "memo", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        del cls
        return _normalize_optional_command_text(value)

    @field_validator("legal_name", "phone_number", "email_address", "contact_address", "memo")
    @classmethod
    def reject_incompatible_text(cls, value: str | None) -> str | None:
        del cls
        _validate_customer_text(value)
        return value

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        del cls
        normalized = normalize_optional(value)
        if normalized is not None and (
            not any(character in "0123456789" for character in normalized)
            or any(character not in "0123456789+-.() " for character in normalized)
        ):
            raise ValueError("phone_number must use supported ASCII phone characters")
        return value

    @field_validator("email_address")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        del cls
        return _validate_email_address(value)


class CustomerPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone_number: str | None = Field(default=None, max_length=100)
    email_address: str | None = Field(default=None, max_length=320)
    contact_address: str | None = Field(default=None, max_length=1000)
    memo: str | None = Field(default=None, max_length=5000)
    confirmed_distinct: StrictBool = False
    deactivate: StrictBool = False
    deactivation_reason: str | None = Field(default=None, max_length=1000)
    id_document_number: str | None = Field(
        default=None, min_length=1, max_length=ID_DOCUMENT_NUMBER_MAX_LENGTH
    )

    @field_validator("legal_name", "id_document_number", mode="before")
    @classmethod
    def normalize_legal_name(cls, value: object) -> object:
        del cls
        return _normalize_required_command_text(value)

    @field_validator("id_document_number")
    @classmethod
    def validate_id_document_number(cls, value: str | None) -> str | None:
        """A recorded ID number may be corrected; it is never cleared (null is refused)."""
        del cls
        if value is None:
            raise ValueError("id_document_number cannot be removed")
        _validate_customer_text(value)
        return _validate_id_document_number(value)

    @field_validator(
        "phone_number",
        "email_address",
        "contact_address",
        "memo",
        "deactivation_reason",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        del cls
        return _normalize_optional_command_text(value)

    @field_validator(
        "legal_name",
        "phone_number",
        "email_address",
        "contact_address",
        "memo",
        "deactivation_reason",
    )
    @classmethod
    def reject_incompatible_text(cls, value: str | None) -> str | None:
        del cls
        _validate_customer_text(value)
        return value

    @field_validator("email_address")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        del cls
        return _validate_email_address(value)


def _validate_id_document_number(value: str) -> str:
    """The ID number must hold at least one letter or digit (DL-071 answer 11)."""
    if id_document_match_key(value) is None:
        raise ValueError("id_document_number must hold a letter or a digit")
    return value


def _validate_customer_text(value: str | None) -> None:
    """Reject text that cannot be represented as scalar UTF-8 application data."""
    if value is None:
        return
    if "\x00" in value:
        raise ValueError("Customer text must not contain NUL characters")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValueError("Customer text must contain only Unicode scalar values")


def _validate_email_address(value: str | None) -> str | None:
    """Reject malformed contact addresses without normalizing stored source data."""
    normalized = normalize_optional(value)
    if normalized is None:
        return value
    if normalized.count("@") != 1 or re.search(r"\s", normalized):
        raise ValueError("email_address must be a structurally valid address")
    local, domain = normalized.rsplit("@", 1)
    if not normalized.isascii():
        raise ValueError("email_address must use ASCII or an ASCII IDN form")
    if (
        not local
        or len(local) > 64
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
        or re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local) is None
        or not domain
        or domain.startswith(".")
        or domain.endswith(".")
        or ".." in domain
    ):
        raise ValueError("email_address must be a structurally valid address")
    try:
        ascii_domain = domain.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("email_address must use a valid domain") from exc
    if len(ascii_domain) > 255 or any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or re.fullmatch(r"[A-Za-z0-9-]+", label) is None
        for label in ascii_domain.split(".")
    ):
        raise ValueError("email_address must use a valid domain")
    return canonical_email(value)


def _require_actor(request: Request, resolver: ActorResolver) -> AuthenticatedActor:
    actor = resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return actor


def _can_manage(actor: AuthenticatedActor, property_id: UUID) -> bool:
    return is_authorized(
        actor,
        AuthorizationRequirement(
            capability=CUSTOMER_MANAGE_CAPABILITY,
            property_id=str(property_id),
        ),
    )


def _can_read(actor: AuthenticatedActor, property_id: UUID) -> bool:
    return is_authorized(
        actor,
        AuthorizationRequirement(
            capability=CUSTOMER_READ_CAPABILITY,
            property_id=str(property_id),
        ),
    ) or _can_manage(actor, property_id)


def _can_view_audit(actor: AuthenticatedActor, property_id: UUID) -> bool:
    return is_authorized(
        actor,
        AuthorizationRequirement(
            capability=AUDIT_VIEW_CAPABILITY,
            property_id=str(property_id),
        ),
    )


def _require_reader(actor: AuthenticatedActor, property_id: UUID) -> None:
    if not _can_read(actor, property_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


def _require_manager(actor: AuthenticatedActor, property_id: UUID) -> None:
    if not _can_manage(actor, property_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


def _require_browser_mutation(request: Request, settings: Settings) -> None:
    if request.headers.get("origin") != settings.allowed_browser_origin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get("X-CSRF-Token")
    if (
        cookie_token is None
        or header_token is None
        or not hmac.compare_digest(cookie_token, header_token)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


def _requested_version(value: str | None, current: int) -> int:
    if value is None:
        raise HTTPException(status_code=status.HTTP_412_PRECONDITION_FAILED)
    candidate = value.strip()
    if candidate.startswith("W/"):
        raise CustomerVersionConflict(current)
    if len(candidate) >= 2 and candidate[0] == candidate[-1] == '"':
        candidate = candidate[1:-1]
    try:
        parsed = int(candidate)
    except ValueError as exc:
        raise CustomerVersionConflict(current) from exc
    if not 1 <= parsed <= POSTGRES_INTEGER_MAX:
        raise CustomerVersionConflict(current)
    return parsed


def _canonical_create_payload(command: CustomerCreate) -> dict[str, object]:
    """Hash the same normalized source values that CustomerService persists."""
    return {
        "legal_name": command.legal_name.strip(),
        "phone_number": normalize_optional(command.phone_number),
        "email_address": normalize_optional(command.email_address),
        "contact_address": normalize_optional(command.contact_address),
        "memo": normalize_optional(command.memo),
        "confirmed_distinct": command.confirmed_distinct,
        "id_document_number": command.id_document_number.strip(),
    }


def _canonical_update_payload(
    patch: CustomerPatch,
    *,
    expected_version: int,
) -> dict[str, object]:
    """Hash only normalized submitted fields, independent of later Customer state."""
    payload: dict[str, object] = {
        "expected_version": expected_version,
        "confirmed_distinct": patch.confirmed_distinct,
    }
    for field_name in (
        "legal_name",
        "phone_number",
        "email_address",
        "contact_address",
        "memo",
        "id_document_number",
    ):
        if field_name not in patch.model_fields_set:
            continue
        value = getattr(patch, field_name)
        payload[field_name] = (
            (value or "").strip()
            if field_name == "legal_name"
            else normalize_optional(cast(str | None, value))
        )
    return payload


def _required_idempotency_key(value: str | None) -> UUID:
    if value is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST) from exc
    if parsed.int == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    return parsed


def _minimal(record: CustomerRecord) -> dict[str, object]:
    return {
        "customer_id": str(record.customer.customer_id),
        "legal_name": record.customer.legal_name,
        "active": record.active,
        "relationship_indicators": [],
    }


def _detail(
    record: CustomerRecord,
    *,
    can_manage: bool,
    can_view_audit: bool,
    audit_history_available: bool,
    history: CustomerHistoryPage,
) -> dict[str, object]:
    customer = record.customer
    return {
        "customer_id": str(customer.customer_id),
        "legal_name": customer.legal_name,
        "phone_number": customer.phone_number,
        "email_address": customer.email_address,
        "contact_address": customer.contact_address,
        "memo": customer.memo,
        "id_document_number": customer.id_document_number,
        "version": customer.version,
        "active": record.active,
        "deactivated_at": (
            None if record.deactivated_at is None else record.deactivated_at.isoformat()
        ),
        "deactivation_reason": record.deactivation_reason,
        "relationships": {
            "reservations": [],
            "primary_tenant_leases": [],
            "signer_leases": [],
            "occupancies": [],
            "invoices": [],
            "payments": [],
            "customer_credit": [],
            "refunds": [],
        },
        "audit_history": [
            {
                **asdict(event),
                "event_id": str(event.event_id),
                "occurred_at": event.occurred_at.isoformat(),
                "actor_id": str(event.actor_id),
                "correlation_id": str(event.correlation_id),
            }
            for event in history.items
        ],
        "audit_history_next_cursor": history.next_cursor,
        "can_manage": can_manage,
        "can_deactivate": can_manage and record.active,
        "can_view_audit": can_view_audit,
        "audit_history_available": audit_history_available,
    }


def create_customer_router(
    resolver: ActorResolver,
    flow: CustomerResourceFlow,
    settings: Settings,
    search_rate_guard: CustomerSearchRateGuard | None = None,
) -> APIRouter:
    """Create the approved Customer collection, detail, and summary routes."""
    router = APIRouter(prefix="/api/v1", tags=["customers"])
    effective_search_rate_guard = search_rate_guard or (
        PostgresCustomerSearchRateGuard(flow._database_url)
        if isinstance(flow, PostgresCustomerResourceFlow)
        else SlidingWindowCustomerSearchRateGuard()
    )

    def protect_customer_response(response: Response) -> None:
        """Prevent browser or intermediary reuse of confidential Customer data."""
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "Cookie"

    def get_record(customer_id: UUID) -> CustomerRecord:
        try:
            return flow.get(customer_id)
        except CustomerResourceNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except CustomerResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc

    def mutation_history(
        actor: AuthenticatedActor,
        record: CustomerRecord,
        action: str,
        idempotency_key: UUID,
    ) -> tuple[CustomerHistoryPage, bool]:
        """Keep command replay bodies stable; detail reads expose current audit history."""
        del actor, record, action, idempotency_key
        return CustomerHistoryPage((), None), False

    @router.get("/properties/{property_id}/customers")
    def list_customers(
        property_id: UUID,
        request: Request,
        response: Response,
        query: Annotated[str | None, Query(max_length=255)] = None,
        active: bool | None = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        _require_reader(actor, property_id)
        unknown_filters = set(request.query_params).difference(
            {"active", "cursor", "limit", "query"}
        )
        if unknown_filters:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        if query is not None:
            try:
                _validate_customer_text(query)
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
        try:
            allowed = effective_search_rate_guard.allow(
                actor_id=actor.actor_id,
                source=request.client.host if request.client is not None else "unavailable",
                property_id=property_id,
            )
        except CustomerResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        if not allowed:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS)
        try:
            page = flow.list(
                property_id,
                query=query,
                active=active,
                limit=limit,
                cursor=cursor,
            )
        except CustomerResourceNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except CustomerResourceInvalid as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
        except CustomerResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        protect_customer_response(response)
        return {
            "data": [_minimal(record) for record in page.items],
            "page": {"next_cursor": page.next_cursor, "limit": limit},
            "meta": {
                "request_id": request.state.request_id,
                "can_manage": _can_manage(actor, property_id),
            },
        }

    @router.post("/properties/{property_id}/customers", status_code=status.HTTP_201_CREATED)
    def create_customer(
        property_id: UUID,
        command: CustomerCreate,
        request: Request,
        response: Response,
        idempotency_key_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        _require_manager(actor, property_id)
        _require_browser_mutation(request, settings)
        idempotency_key = _required_idempotency_key(idempotency_key_header)
        try:
            record = flow.create(
                property_id,
                customer_id=command.customer_id,
                legal_name=command.legal_name,
                phone_number=command.phone_number,
                email_address=command.email_address,
                contact_address=command.contact_address,
                memo=command.memo,
                confirmed_distinct=command.confirmed_distinct,
                id_document_number=command.id_document_number,
                actor_id=actor.actor_id,
                idempotency_key=idempotency_key,
                request_digest=_command_digest(
                    action="create",
                    property_id=property_id,
                    customer_id=command.customer_id,
                    payload=_canonical_create_payload(command),
                ),
            )
        except CustomerReuseRequired as exc:
            raise CustomerReuseConflict(exc.candidates) from exc
        except CustomerIdNumberInUse as exc:
            raise CustomerIdNumberConflict(exc.existing) from exc
        except CustomerIdempotencyKeyReused:
            raise
        except CustomerCommandIdentityConflict as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT) from exc
        except CustomerResourceNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except CustomerResourceInvalid as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
        except CustomerResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        response.headers["ETag"] = f'"{record.customer.version}"'
        response.headers["Location"] = f"/api/v1/customers/{record.customer.customer_id}"
        protect_customer_response(response)
        history, history_available = mutation_history(actor, record, "create", idempotency_key)
        return {
            "data": _detail(
                record,
                can_manage=True,
                can_view_audit=_can_view_audit(actor, property_id),
                audit_history_available=history_available,
                history=history,
            ),
            "meta": {"request_id": request.state.request_id},
        }

    @router.get("/properties/{property_id}/customers/{customer_id}/command-status")
    def customer_command_status(
        property_id: UUID,
        customer_id: UUID,
        request: Request,
        response: Response,
        action: Annotated[str | None, Query(pattern="^(create|update|deactivate)$")] = None,
        idempotency_key: Annotated[UUID | None, Query(alias="idempotency_key")] = None,
    ) -> dict[str, object]:
        """Authoritatively reconcile a client-generated Customer creation identity."""
        actor = _require_actor(request, resolver)
        _require_manager(actor, property_id)
        if action is None or idempotency_key is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        if set(request.query_params).difference({"action", "idempotency_key"}):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        try:
            # Verify that the authorized Property still exists even when the
            # client-generated Customer identity was never committed.
            flow.list(property_id, query=None, active=None, limit=1, cursor=None)
        except CustomerResourceNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except CustomerResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        try:
            command_status = flow.command_status(
                property_id=property_id,
                customer_id=customer_id,
                action=action,
                idempotency_key=idempotency_key,
                actor_id=actor.actor_id,
            )
        except CustomerIdempotencyKeyReused:
            raise
        except CustomerCommandIdentityConflict as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT) from exc
        except CustomerResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        customer = None
        if command_status.record is not None:
            customer = _detail(
                command_status.record,
                can_manage=True,
                can_view_audit=False,
                audit_history_available=False,
                history=CustomerHistoryPage((), None),
            )
        protect_customer_response(response)
        return {
            "data": {
                "recorded": command_status.recorded,
                "expired": command_status.expired,
                "customer": customer,
            },
            "meta": {"request_id": request.state.request_id},
        }

    @router.get("/customers/{customer_id}")
    def get_customer(
        customer_id: UUID,
        request: Request,
        response: Response,
        history_cursor: Annotated[str | None, Query(max_length=512)] = None,
        history_limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        unknown_filters = set(request.query_params).difference({"history_cursor", "history_limit"})
        if unknown_filters:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        record = get_record(customer_id)
        if not _can_read(actor, record.property_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        can_view_audit = _can_view_audit(actor, record.property_id)
        history = CustomerHistoryPage((), None)
        if can_view_audit:
            try:
                record, history = flow.detail(
                    customer_id,
                    limit=history_limit,
                    cursor=history_cursor,
                )
            except CustomerResourceNotFound as exc:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
            except CustomerResourceInvalid as exc:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
            except CustomerResourceUnavailable as exc:
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        response.headers["ETag"] = f'"{record.customer.version}"'
        protect_customer_response(response)
        return {
            "data": _detail(
                record,
                can_manage=_can_manage(actor, record.property_id),
                can_view_audit=can_view_audit,
                audit_history_available=can_view_audit,
                history=history,
            ),
            "meta": {"request_id": request.state.request_id},
        }

    @router.patch("/customers/{customer_id}")
    def patch_customer(
        customer_id: UUID,
        patch: CustomerPatch,
        request: Request,
        response: Response,
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        current = get_record(customer_id)
        if not _can_manage(actor, current.property_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        _require_browser_mutation(request, settings)
        idempotency_key = _required_idempotency_key(idempotency_key_header)
        expected = _requested_version(if_match, current.customer.version)
        source_fields = {
            "legal_name",
            "phone_number",
            "email_address",
            "contact_address",
            "memo",
            "id_document_number",
        }
        changed_source_fields = source_fields.intersection(patch.model_fields_set)
        try:
            if patch.deactivate:
                if changed_source_fields or patch.deactivation_reason is None:
                    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
                record = flow.deactivate(
                    customer_id,
                    reason=patch.deactivation_reason,
                    expected_version=expected,
                    actor_id=actor.actor_id,
                    idempotency_key=idempotency_key,
                    request_digest=_command_digest(
                        action="deactivate",
                        property_id=current.property_id,
                        customer_id=customer_id,
                        payload={
                            "expected_version": expected,
                            "reason": patch.deactivation_reason.strip(),
                        },
                    ),
                )
            else:
                if not changed_source_fields or "deactivation_reason" in patch.model_fields_set:
                    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
                legal_name = (
                    current.customer.legal_name
                    if "legal_name" not in patch.model_fields_set
                    else (patch.legal_name or "").strip()
                )
                phone_number = (
                    current.customer.phone_number
                    if "phone_number" not in patch.model_fields_set
                    else normalize_optional(patch.phone_number)
                )
                email_address = (
                    current.customer.email_address
                    if "email_address" not in patch.model_fields_set
                    else normalize_optional(patch.email_address)
                )
                contact_address = (
                    current.customer.contact_address
                    if "contact_address" not in patch.model_fields_set
                    else normalize_optional(patch.contact_address)
                )
                memo = (
                    current.customer.memo
                    if "memo" not in patch.model_fields_set
                    else normalize_optional(patch.memo)
                )
                record = flow.update(
                    customer_id,
                    legal_name=legal_name,
                    phone_number=phone_number,
                    email_address=email_address,
                    contact_address=contact_address,
                    memo=memo,
                    confirmed_distinct=patch.confirmed_distinct,
                    id_document_number=(
                        patch.id_document_number
                        if "id_document_number" in patch.model_fields_set
                        else None
                    ),
                    expected_version=expected,
                    actor_id=actor.actor_id,
                    idempotency_key=idempotency_key,
                    request_digest=_command_digest(
                        action="update",
                        property_id=current.property_id,
                        customer_id=customer_id,
                        payload=_canonical_update_payload(
                            patch,
                            expected_version=expected,
                        ),
                    ),
                )
        except CustomerReuseRequired as exc:
            raise CustomerReuseConflict(exc.candidates) from exc
        except CustomerIdNumberInUse as exc:
            raise CustomerIdNumberConflict(exc.existing) from exc
        except CustomerIdempotencyKeyReused:
            raise
        except CustomerCommandIdentityConflict as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT) from exc
        except CustomerResourceNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except CustomerResourceInvalid as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
        except CustomerResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        response.headers["ETag"] = f'"{record.customer.version}"'
        protect_customer_response(response)
        history, history_available = mutation_history(
            actor,
            record,
            "deactivate" if patch.deactivate else "update",
            idempotency_key,
        )
        return {
            "data": _detail(
                record,
                can_manage=True,
                can_view_audit=_can_view_audit(actor, current.property_id),
                audit_history_available=history_available,
                history=history,
            ),
            "meta": {"request_id": request.state.request_id},
        }

    @router.get("/customers/{customer_id}/financial-summary")
    def customer_financial_summary(
        customer_id: UUID,
        request: Request,
        response: Response,
        deposit_limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_DEPOSIT_PAGE_SIZE,
        deposit_cursor: Annotated[str | None, Query(max_length=512)] = None,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        if set(request.query_params) - {"deposit_limit", "deposit_cursor"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        record = get_record(customer_id)
        if not _can_read(actor, record.property_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            summary = flow.financial_summary(
                customer_id,
                deposit_limit=deposit_limit,
                deposit_cursor=deposit_cursor,
            )
        except CustomerResourceNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except CustomerResourceInvalid as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST) from exc
        except CustomerResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        protect_customer_response(response)
        return {"data": summary, "meta": {"request_id": request.state.request_id}}

    return router


def _minimal_record(customer: Customer) -> dict[str, object]:
    return {
        "customer_id": str(customer.customer_id),
        "legal_name": customer.legal_name,
    }
