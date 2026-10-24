"""Authorized effective-dated configuration API built on V1-027 persistence."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import ROUND_CEILING, Decimal
from typing import Annotated, Generic, Literal, Protocol, TypeVar, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from property_rental.access_control import SETTINGS_MANAGE_CAPABILITY
from property_rental.browser_security import require_browser_mutation
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.settings import Settings

CONFIGURATION_READ_CAPABILITY = "configuration.read"
# Login sub-slice L5 (owner answer (a) to Q-2026-10-21-151): Service and Utility Rates are
# Settings; `service_rates.manage` and `utility_rates.manage` stay in the catalog, unused.
SERVICE_RATE_MANAGE_CAPABILITY = SETTINGS_MANAGE_CAPABILITY
UTILITY_RATE_MANAGE_CAPABILITY = SETTINGS_MANAGE_CAPABILITY
EXCHANGE_RATE_MANAGE_CAPABILITY = "exchange_rates.manage"
MAX_PAGE_SIZE = 100


class ConfigurationNotFound(LookupError):
    """Requested Property or configuration record was not found."""


class ConfigurationUnavailable(RuntimeError):
    """Persistence is unavailable."""


class ConfigurationConflict(RuntimeError):
    """The append command conflicts with existing history."""


class ConfigurationIdempotencyConflict(ConfigurationConflict):
    """An idempotency key was reused for different input."""


class ExchangeRateSourceUnavailable(RuntimeError):
    """The server-owned automatic ABA-equivalent source is unavailable."""


@dataclass(frozen=True, slots=True)
class ExchangeRateQuote:
    reference_rate_khr_per_usd: Decimal
    source_reference: str
    applicable_at: datetime


class ExchangeRateProvider(Protocol):
    def current_sell_rate(self) -> ExchangeRateQuote: ...


class UnavailableExchangeRateProvider:
    def current_sell_rate(self) -> ExchangeRateQuote:
        raise ExchangeRateSourceUnavailable


@dataclass(frozen=True, slots=True)
class ConfiguredServiceRecord:
    id: UUID
    property_id: UUID
    service_code: str
    display_name: str


@dataclass(frozen=True, slots=True)
class ServiceRateRecord:
    id: UUID
    property_id: UUID
    property_service_id: UUID
    service_code: str
    display_name: str
    monthly_rate_usd_cents: int
    effective_date: date
    source_memo: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class UtilityRateRecord:
    id: UUID
    property_id: UUID
    utility_type: str
    measurement_unit_code: str
    rate_usd_per_unit: Decimal
    effective_date: date
    notice_at: datetime
    notice_evidence: str
    source_memo: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ExchangeRateRecord:
    id: UUID
    reference_rate_khr_per_usd: Decimal
    system_rate_khr_per_usd: int
    rate_source: str
    source_reference: str | None
    applicable_at: datetime
    usd_amount_cents: int
    unrounded_payable_khr: Decimal
    payable_khr: int
    fallback_reason: str | None = None


ConfigurationRecord = (
    ConfiguredServiceRecord | ServiceRateRecord | UtilityRateRecord | ExchangeRateRecord
)
Record = TypeVar("Record", bound=ConfigurationRecord)


@dataclass(frozen=True, slots=True)
class ConfigurationPage(Generic[Record]):
    items: tuple[Record, ...]
    next_cursor: str | None


class ConfigurationFlow(Protocol):
    def list_configured_services(
        self, property_id: UUID, *, limit: int, cursor: str | None
    ) -> ConfigurationPage[ConfiguredServiceRecord]: ...

    def list_service_rates(
        self, property_id: UUID, *, limit: int, cursor: str | None
    ) -> ConfigurationPage[ServiceRateRecord]: ...

    def get_service_rate(self, rate_id: UUID) -> ServiceRateRecord: ...

    def create_service_rate(
        self,
        property_id: UUID,
        *,
        rate_id: UUID,
        property_service_id: UUID,
        monthly_rate_usd_cents: int,
        effective_date: date,
        source_memo: str | None,
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> ServiceRateRecord: ...

    def list_utility_rates(
        self, property_id: UUID, *, limit: int, cursor: str | None
    ) -> ConfigurationPage[UtilityRateRecord]: ...

    def get_utility_rate(self, rate_id: UUID) -> UtilityRateRecord: ...

    def create_utility_rate(
        self,
        property_id: UUID,
        *,
        rate_id: UUID,
        utility_type: str,
        measurement_unit_code: str,
        rate_usd_per_unit: Decimal,
        effective_date: date,
        notice_at: datetime,
        notice_evidence: str,
        source_memo: str | None,
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> UtilityRateRecord: ...

    def list_exchange_rates(
        self, property_id: UUID, *, limit: int, cursor: str | None
    ) -> ConfigurationPage[ExchangeRateRecord]: ...

    def confirm_exchange_rate(
        self,
        property_id: UUID,
        *,
        record: ExchangeRateRecord,
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> ExchangeRateRecord: ...

    def get_exchange_rate_replay(
        self,
        property_id: UUID,
        *,
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> ExchangeRateRecord | None: ...


class UnavailableConfigurationFlow:
    """Fail closed when PostgreSQL is not configured."""

    def __getattr__(self, _: str) -> object:
        raise ConfigurationUnavailable("Configuration persistence is unavailable")


def _cursor(applicable: date | datetime, record_id: UUID) -> str:
    raw = f"{applicable.isoformat()}|{record_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(
    value: str | None, *, temporal: Literal["date", "datetime"]
) -> tuple[object, UUID] | None:
    if value is None:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        left, right = raw.split("|", 1)
        instant: object = (
            date.fromisoformat(left) if temporal == "date" else datetime.fromisoformat(left)
        )
        return instant, UUID(right)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid cursor") from exc


def _text_cursor(value: str, record_id: UUID) -> str:
    raw = f"{value}|{record_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_text_cursor(value: str | None) -> tuple[str, UUID] | None:
    if value is None:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        left, right = raw.rsplit("|", 1)
        if not left:
            raise ValueError
        return left, UUID(right)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid cursor") from exc


def _page(
    rows: list[Record],
    limit: int,
    applicable_value: Callable[[Record], date | datetime],
) -> ConfigurationPage[Record]:
    visible = rows[:limit]
    if len(rows) <= limit or not visible:
        return ConfigurationPage(tuple(visible), None)
    last = visible[-1]
    applicable = applicable_value(last)
    return ConfigurationPage(tuple(visible), _cursor(applicable, last.id))


@dataclass(frozen=True, slots=True)
class PostgresConfigurationFlow:
    database_url: str

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self.database_url)

    def list_configured_services(
        self, property_id: UUID, *, limit: int, cursor: str | None
    ) -> ConfigurationPage[ConfiguredServiceRecord]:
        decoded = _decode_text_cursor(cursor)
        clause = "" if decoded is None else "AND (service_code, id) > (%s, %s)"
        parameters: tuple[object, ...] = (
            (property_id,) if decoded is None else (property_id, *decoded)
        )
        try:
            with self._connect() as connection:
                exists = connection.execute(
                    "SELECT 1 FROM app.properties WHERE id = %s", (property_id,)
                ).fetchone()
                if exists is None:
                    raise ConfigurationNotFound
                rows = connection.execute(
                    f"""
                    SELECT id, property_id, service_code, display_name
                    FROM app.property_services
                    WHERE property_id = %s {clause}
                    ORDER BY service_code, id
                    LIMIT %s
                    """,
                    (*parameters, limit + 1),
                ).fetchall()
        except ConfigurationNotFound:
            raise
        except psycopg.Error as exc:
            raise ConfigurationUnavailable from exc
        records = [
            ConfiguredServiceRecord(
                id=UUID(str(row[0])),
                property_id=UUID(str(row[1])),
                service_code=str(row[2]),
                display_name=str(row[3]),
            )
            for row in rows
        ]
        visible = records[:limit]
        next_cursor = None
        if len(records) > limit and visible:
            last = visible[-1]
            next_cursor = _text_cursor(last.service_code, last.id)
        return ConfigurationPage(tuple(visible), next_cursor)

    @staticmethod
    def _service(row: tuple[object, ...]) -> ServiceRateRecord:
        if not isinstance(row[6], date) or not isinstance(row[8], datetime):
            raise ConfigurationUnavailable("Service-rate evidence is invalid")
        return ServiceRateRecord(
            UUID(str(row[0])),
            UUID(str(row[1])),
            UUID(str(row[2])),
            str(row[3]),
            str(row[4]),
            int(str(row[5])),
            row[6],
            None if row[7] is None else str(row[7]),
            row[8],
        )

    @staticmethod
    def _utility(row: tuple[object, ...]) -> UtilityRateRecord:
        if (
            not isinstance(row[5], date)
            or not isinstance(row[6], datetime)
            or not isinstance(row[9], datetime)
        ):
            raise ConfigurationUnavailable("Utility-rate evidence is invalid")
        return UtilityRateRecord(
            UUID(str(row[0])),
            UUID(str(row[1])),
            str(row[2]),
            str(row[3]),
            Decimal(str(row[4])),
            row[5],
            row[6],
            str(row[7]),
            None if row[8] is None else str(row[8]),
            row[9],
        )

    @staticmethod
    def _exchange(row: tuple[object, ...]) -> ExchangeRateRecord:
        trace = row[6]
        if not isinstance(trace, dict) or not isinstance(row[5], datetime):
            raise ConfigurationUnavailable("Exchange-rate evidence is invalid")
        return ExchangeRateRecord(
            UUID(str(row[0])),
            Decimal(str(row[1])),
            int(str(row[2])),
            str(row[3]),
            None if row[4] is None else str(row[4]),
            row[5],
            int(trace["usd_amount_cents"]),
            Decimal(str(trace["unrounded_payable_khr"])),
            int(trace["payable_khr"]),
            None if trace.get("fallback_reason") is None else str(trace["fallback_reason"]),
        )

    def list_service_rates(
        self, property_id: UUID, *, limit: int, cursor: str | None
    ) -> ConfigurationPage[ServiceRateRecord]:
        decoded = _decode_cursor(cursor, temporal="date")
        clause = "" if decoded is None else "AND (rate.effective_date, rate.id) < (%s, %s)"
        parameters: tuple[object, ...] = (
            (property_id,) if decoded is None else (property_id, *decoded)
        )
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT rate.id, service.property_id, service.id,
                           service.service_code, service.display_name,
                           rate.monthly_rate_usd_cents, rate.effective_date,
                           rate.source_memo, rate.occurred_at
                    FROM app.service_rates AS rate
                    JOIN app.property_services AS service
                      ON service.id = rate.property_service_id
                    WHERE service.property_id = %s {clause}
                    ORDER BY rate.effective_date DESC, rate.id DESC
                    LIMIT %s
                    """,
                    (*parameters, limit + 1),
                ).fetchall()
        except psycopg.Error as exc:
            raise ConfigurationUnavailable from exc
        return _page(
            [self._service(row) for row in rows],
            limit,
            lambda item: item.effective_date,
        )

    def get_service_rate(self, rate_id: UUID) -> ServiceRateRecord:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT rate.id, service.property_id, service.id,
                           service.service_code, service.display_name,
                           rate.monthly_rate_usd_cents, rate.effective_date,
                           rate.source_memo, rate.occurred_at
                    FROM app.service_rates AS rate
                    JOIN app.property_services AS service
                      ON service.id = rate.property_service_id
                    WHERE rate.id = %s
                    """,
                    (rate_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise ConfigurationUnavailable from exc
        if row is None:
            raise ConfigurationNotFound
        return self._service(row)

    def create_service_rate(self, property_id: UUID, **values: object) -> ServiceRateRecord:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM app.execute_service_rate(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        property_id,
                        values["idempotency_key"],
                        values["request_digest"],
                        values["rate_id"],
                        values["property_service_id"],
                        values["monthly_rate_usd_cents"],
                        values["effective_date"],
                        values["source_memo"],
                        values["actor_id"],
                    ),
                ).fetchone()
        except psycopg.errors.NoDataFound as exc:
            raise ConfigurationNotFound from exc
        except psycopg.errors.RaiseException as exc:
            if exc.sqlstate == "P0001":
                raise ConfigurationIdempotencyConflict from exc
            raise ConfigurationConflict from exc
        except psycopg.errors.UniqueViolation as exc:
            raise ConfigurationConflict from exc
        except psycopg.Error as exc:
            raise ConfigurationUnavailable from exc
        if row is None:
            raise ConfigurationNotFound
        return self._service(row)

    def list_utility_rates(
        self, property_id: UUID, *, limit: int, cursor: str | None
    ) -> ConfigurationPage[UtilityRateRecord]:
        decoded = _decode_cursor(cursor, temporal="date")
        clause = "" if decoded is None else "AND (effective_date, id) < (%s, %s)"
        parameters: tuple[object, ...] = (
            (property_id,) if decoded is None else (property_id, *decoded)
        )
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT id, property_id, utility_type, measurement_unit_code,
                           rate_usd_per_unit, effective_date, notice_at,
                           notice_evidence, source_memo, occurred_at
                    FROM app.utility_rates
                    WHERE property_id = %s {clause}
                    ORDER BY effective_date DESC, id DESC
                    LIMIT %s
                    """,
                    (*parameters, limit + 1),
                ).fetchall()
        except psycopg.Error as exc:
            raise ConfigurationUnavailable from exc
        return _page(
            [self._utility(row) for row in rows],
            limit,
            lambda item: item.effective_date,
        )

    def get_utility_rate(self, rate_id: UUID) -> UtilityRateRecord:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT id, property_id, utility_type, measurement_unit_code,
                           rate_usd_per_unit, effective_date, notice_at,
                           notice_evidence, source_memo, occurred_at
                    FROM app.utility_rates WHERE id = %s
                    """,
                    (rate_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise ConfigurationUnavailable from exc
        if row is None:
            raise ConfigurationNotFound
        return self._utility(row)

    def create_utility_rate(self, property_id: UUID, **values: object) -> UtilityRateRecord:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM app.execute_utility_rate(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        property_id,
                        values["idempotency_key"],
                        values["request_digest"],
                        values["rate_id"],
                        values["utility_type"],
                        values["measurement_unit_code"],
                        values["rate_usd_per_unit"],
                        values["effective_date"],
                        values["notice_at"],
                        values["notice_evidence"],
                        values["source_memo"],
                        values["actor_id"],
                    ),
                ).fetchone()
        except psycopg.errors.NoDataFound as exc:
            raise ConfigurationNotFound from exc
        except psycopg.errors.RaiseException as exc:
            if exc.sqlstate == "P0001":
                raise ConfigurationIdempotencyConflict from exc
            raise ConfigurationConflict from exc
        except (psycopg.errors.UniqueViolation, psycopg.errors.CheckViolation) as exc:
            raise ConfigurationConflict from exc
        except psycopg.Error as exc:
            raise ConfigurationUnavailable from exc
        if row is None:
            raise ConfigurationNotFound
        return self._utility(row)

    def list_exchange_rates(
        self, property_id: UUID, *, limit: int, cursor: str | None
    ) -> ConfigurationPage[ExchangeRateRecord]:
        decoded = _decode_cursor(cursor, temporal="datetime")
        cursor_at: object | None = None if decoded is None else decoded[0]
        cursor_id: object | None = None if decoded is None else decoded[1]
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM app.list_exchange_rates_for_property(%s,%s,%s,%s)",
                    (property_id, limit + 1, cursor_at, cursor_id),
                ).fetchall()
        except psycopg.errors.NoDataFound as exc:
            raise ConfigurationNotFound from exc
        except psycopg.Error as exc:
            raise ConfigurationUnavailable from exc
        return _page(
            [self._exchange(row) for row in rows],
            limit,
            lambda item: item.applicable_at,
        )

    def confirm_exchange_rate(
        self,
        property_id: UUID,
        *,
        record: ExchangeRateRecord,
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> ExchangeRateRecord:
        trace = {
            "usd_amount_cents": record.usd_amount_cents,
            "unrounded_payable_khr": str(record.unrounded_payable_khr),
            "payable_khr": record.payable_khr,
            "markup_basis_points": 50,
            "rounding": "CEILING_WHOLE_KHR",
            "automatic_source_unavailable": record.rate_source == "ABA_EQUIVALENT_MANUAL",
            "fallback_reason": record.fallback_reason,
        }
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM app.execute_exchange_rate(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        property_id,
                        idempotency_key,
                        request_digest,
                        record.id,
                        record.reference_rate_khr_per_usd,
                        record.system_rate_khr_per_usd,
                        record.rate_source,
                        record.source_reference,
                        record.applicable_at,
                        actor_id,
                        Jsonb(trace),
                    ),
                ).fetchone()
        except psycopg.errors.NoDataFound as exc:
            raise ConfigurationNotFound from exc
        except psycopg.errors.RaiseException as exc:
            if exc.sqlstate == "P0001":
                raise ConfigurationIdempotencyConflict from exc
            raise ConfigurationConflict from exc
        except psycopg.Error as exc:
            raise ConfigurationUnavailable from exc
        if row is None:
            raise ConfigurationNotFound
        return self._exchange(row)

    def get_exchange_rate_replay(
        self,
        property_id: UUID,
        *,
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> ExchangeRateRecord | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM app.replay_exchange_rate_command(%s,%s,%s,%s)",
                    (property_id, actor_id, idempotency_key, request_digest),
                ).fetchone()
        except psycopg.errors.RaiseException as exc:
            if exc.sqlstate == "P0001":
                raise ConfigurationIdempotencyConflict from exc
            raise ConfigurationConflict from exc
        except psycopg.Error as exc:
            raise ConfigurationUnavailable from exc
        return None if row is None else self._exchange(row)


class ServiceRateCreate(BaseModel):
    model_config = ConfigDict(frozen=True)
    property_service_id: UUID
    monthly_rate_usd_cents: int = Field(gt=0, le=1_000_000_000)
    effective_date: date
    source_memo: str | None = Field(default=None, max_length=500)


class UtilityRateCreate(BaseModel):
    model_config = ConfigDict(frozen=True)
    utility_type: Literal["ELECTRICITY", "WATER"]
    measurement_unit_code: str = Field(min_length=1, max_length=32)
    rate_usd_per_unit: Decimal = Field(gt=0, max_digits=20, decimal_places=8)
    effective_date: date
    notice_at: datetime
    notice_evidence: str = Field(min_length=1, max_length=500)
    source_memo: str | None = Field(default=None, max_length=500)

    @field_validator("measurement_unit_code", "notice_evidence", "source_memo")
    @classmethod
    def normalized_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("must be nonblank")
        return normalized

    @model_validator(mode="after")
    def valid_notice_window(self) -> UtilityRateCreate:
        if self.notice_at.tzinfo is None:
            raise ValueError("notice_at must include a timezone")
        local_notice_date = self.notice_at.astimezone(ZoneInfo("Asia/Phnom_Penh")).date()
        if local_notice_date >= self.effective_date:
            raise ValueError("advance notice must precede the effective date")
        return self


class ExchangeRateConfirm(BaseModel):
    model_config = ConfigDict(frozen=True)
    rate_source: Literal["ABA_AUTOMATIC", "ABA_EQUIVALENT_MANUAL"]
    reference_rate_khr_per_usd: Decimal | None = Field(
        default=None, gt=0, max_digits=20, decimal_places=6
    )
    source_reference: str | None = Field(default=None, max_length=500)
    applicable_at: datetime | None = None
    automatic_source_unavailable: bool = False
    fallback_reason: str | None = Field(default=None, max_length=500)
    usd_amount_cents: int = Field(gt=0, le=1_000_000_000_00)

    @field_validator("source_reference", "fallback_reason")
    @classmethod
    def normalized_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def valid_source_evidence(self) -> ExchangeRateConfirm:
        if self.rate_source == "ABA_AUTOMATIC":
            if (
                any(
                    value is not None
                    for value in (
                        self.reference_rate_khr_per_usd,
                        self.source_reference,
                        self.applicable_at,
                        self.fallback_reason,
                    )
                )
                or self.automatic_source_unavailable
            ):
                raise ValueError("automatic source evidence is server-owned")
            return self
        if not self.automatic_source_unavailable:
            raise ValueError("manual fallback requires automatic-source unavailability")
        if (
            self.reference_rate_khr_per_usd is None
            or self.source_reference is None
            or self.applicable_at is None
            or self.fallback_reason is None
        ):
            raise ValueError("manual fallback requires complete bounded evidence")
        if self.applicable_at.tzinfo is None:
            raise ValueError("applicable_at must include a timezone")
        return self


def _actor(request: Request, resolver: ActorResolver) -> AuthenticatedActor:
    actor = resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return actor


def _authorized(actor: AuthenticatedActor, capability: str, property_id: UUID) -> None:
    if not is_authorized(
        actor, AuthorizationRequirement(capability=capability, property_id=str(property_id))
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


def _authorized_detail(actor: AuthenticatedActor, capability: str, property_id: UUID) -> None:
    if not is_authorized(
        actor,
        AuthorizationRequirement(capability=capability, property_id=str(property_id)),
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


def _actor_uuid(actor: AuthenticatedActor) -> UUID:
    try:
        return UUID(actor.actor_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from exc


def _allow_query(request: Request, allowed: set[str]) -> None:
    if set(request.query_params).difference(allowed):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)


def _digest(model: BaseModel) -> str:
    payload = json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _body(record: ConfigurationRecord) -> dict[str, object]:
    decoded = json.loads(json.dumps(asdict(record), default=str))
    if not isinstance(decoded, dict):
        raise ConfigurationUnavailable("Configuration serialization failed")
    return cast(dict[str, object], decoded)


Result = TypeVar("Result")


def _invoke(operation: Callable[[], Result]) -> Result:
    try:
        return operation()
    except ConfigurationNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except ConfigurationIdempotencyConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT) from exc
    except ConfigurationConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST) from exc
    except ExchangeRateSourceUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
    except ConfigurationUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc


def create_configuration_router(
    actor_resolver: ActorResolver,
    flow: ConfigurationFlow,
    settings: Settings,
    exchange_rate_provider: ExchangeRateProvider | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["configuration"])
    provider = exchange_rate_provider or UnavailableExchangeRateProvider()

    def page_response(
        page: ConfigurationPage[Record], request: Request, limit: int
    ) -> dict[str, object]:
        return {
            "data": [_body(item) for item in page.items],
            "page": {"limit": limit, "next_cursor": page.next_cursor},
            "meta": {"request_id": request.state.request_id},
        }

    @router.get("/properties/{property_id}/configuration-capabilities")
    def configuration_capabilities(property_id: UUID, request: Request) -> dict[str, object]:
        actor = _actor(request, actor_resolver)

        def allowed(capability: str) -> bool:
            return is_authorized(
                actor,
                AuthorizationRequirement(capability=capability, property_id=str(property_id)),
            )

        return {
            "data": {
                "read": allowed(CONFIGURATION_READ_CAPABILITY),
                "manage_service_rates": allowed(SERVICE_RATE_MANAGE_CAPABILITY),
                "manage_utility_rates": allowed(UTILITY_RATE_MANAGE_CAPABILITY),
                "manage_exchange_rates": allowed(EXCHANGE_RATE_MANAGE_CAPABILITY),
            },
            "meta": {"request_id": request.state.request_id},
        }

    @router.get("/properties/{property_id}/configured-services")
    def list_configured_services(
        property_id: UUID,
        request: Request,
        limit: int = Query(25, ge=1, le=MAX_PAGE_SIZE),
        cursor: Annotated[str | None, Query(max_length=256)] = None,
    ) -> dict[str, object]:
        _allow_query(request, {"limit", "cursor"})
        actor = _actor(request, actor_resolver)
        _authorized(actor, CONFIGURATION_READ_CAPABILITY, property_id)
        return page_response(
            _invoke(lambda: flow.list_configured_services(property_id, limit=limit, cursor=cursor)),
            request,
            limit,
        )

    @router.get("/properties/{property_id}/service-rates")
    def list_service_rates(
        property_id: UUID,
        request: Request,
        limit: int = Query(25, ge=1, le=MAX_PAGE_SIZE),
        cursor: Annotated[str | None, Query(max_length=256)] = None,
    ) -> dict[str, object]:
        _allow_query(request, {"limit", "cursor"})
        actor = _actor(request, actor_resolver)
        _authorized(actor, CONFIGURATION_READ_CAPABILITY, property_id)
        return page_response(
            _invoke(lambda: flow.list_service_rates(property_id, limit=limit, cursor=cursor)),
            request,
            limit,
        )

    @router.post("/properties/{property_id}/service-rates", status_code=status.HTTP_201_CREATED)
    def create_service_rate(
        property_id: UUID,
        body: ServiceRateCreate,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        _allow_query(request, set())
        actor = _actor(request, actor_resolver)
        _authorized(actor, SERVICE_RATE_MANAGE_CAPABILITY, property_id)
        require_browser_mutation(request, settings)
        record = _invoke(
            lambda: flow.create_service_rate(
                property_id,
                rate_id=uuid4(),
                property_service_id=body.property_service_id,
                monthly_rate_usd_cents=body.monthly_rate_usd_cents,
                effective_date=body.effective_date,
                source_memo=body.source_memo.strip() if body.source_memo else None,
                actor_id=_actor_uuid(actor),
                idempotency_key=idempotency_key,
                request_digest=_digest(body),
            )
        )
        response.headers["Location"] = f"/api/v1/service-rates/{record.id}"
        return {
            "data": _body(record),
            "meta": {"request_id": request.state.request_id},
        }

    @router.get("/service-rates/{rate_id}")
    def get_service_rate(rate_id: UUID, request: Request) -> dict[str, object]:
        actor = _actor(request, actor_resolver)
        record = _invoke(lambda: flow.get_service_rate(rate_id))
        _authorized_detail(actor, CONFIGURATION_READ_CAPABILITY, record.property_id)
        return {
            "data": _body(record),
            "meta": {"request_id": request.state.request_id},
        }

    @router.get("/properties/{property_id}/utility-rates")
    def list_utility_rates(
        property_id: UUID,
        request: Request,
        limit: int = Query(25, ge=1, le=MAX_PAGE_SIZE),
        cursor: Annotated[str | None, Query(max_length=256)] = None,
    ) -> dict[str, object]:
        _allow_query(request, {"limit", "cursor"})
        actor = _actor(request, actor_resolver)
        _authorized(actor, CONFIGURATION_READ_CAPABILITY, property_id)
        return page_response(
            _invoke(lambda: flow.list_utility_rates(property_id, limit=limit, cursor=cursor)),
            request,
            limit,
        )

    @router.post("/properties/{property_id}/utility-rates", status_code=status.HTTP_201_CREATED)
    def create_utility_rate(
        property_id: UUID,
        body: UtilityRateCreate,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        _allow_query(request, set())
        actor = _actor(request, actor_resolver)
        _authorized(actor, UTILITY_RATE_MANAGE_CAPABILITY, property_id)
        require_browser_mutation(request, settings)
        record = _invoke(
            lambda: flow.create_utility_rate(
                property_id,
                rate_id=uuid4(),
                utility_type=body.utility_type,
                measurement_unit_code=body.measurement_unit_code,
                rate_usd_per_unit=body.rate_usd_per_unit,
                effective_date=body.effective_date,
                notice_at=body.notice_at,
                notice_evidence=body.notice_evidence,
                source_memo=body.source_memo,
                actor_id=_actor_uuid(actor),
                idempotency_key=idempotency_key,
                request_digest=_digest(body),
            )
        )
        response.headers["Location"] = f"/api/v1/utility-rates/{record.id}"
        return {
            "data": _body(record),
            "meta": {"request_id": request.state.request_id},
        }

    @router.get("/utility-rates/{rate_id}")
    def get_utility_rate(rate_id: UUID, request: Request) -> dict[str, object]:
        actor = _actor(request, actor_resolver)
        record = _invoke(lambda: flow.get_utility_rate(rate_id))
        _authorized_detail(actor, CONFIGURATION_READ_CAPABILITY, record.property_id)
        return {
            "data": _body(record),
            "meta": {"request_id": request.state.request_id},
        }

    @router.get("/properties/{property_id}/exchange-rates")
    def list_exchange_rates(
        property_id: UUID,
        request: Request,
        limit: int = Query(25, ge=1, le=MAX_PAGE_SIZE),
        cursor: Annotated[str | None, Query(max_length=256)] = None,
    ) -> dict[str, object]:
        _allow_query(request, {"limit", "cursor"})
        actor = _actor(request, actor_resolver)
        _authorized(actor, CONFIGURATION_READ_CAPABILITY, property_id)
        return page_response(
            _invoke(lambda: flow.list_exchange_rates(property_id, limit=limit, cursor=cursor)),
            request,
            limit,
        )

    @router.post("/properties/{property_id}/exchange-rates:confirm")
    def confirm_exchange_rate(
        property_id: UUID,
        body: ExchangeRateConfirm,
        request: Request,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        _allow_query(request, set())
        actor = _actor(request, actor_resolver)
        _authorized(actor, EXCHANGE_RATE_MANAGE_CAPABILITY, property_id)
        require_browser_mutation(request, settings)
        actor_id = _actor_uuid(actor)
        request_digest = _digest(body)
        replay = _invoke(
            lambda: flow.get_exchange_rate_replay(
                property_id,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
        )
        if replay is not None:
            return {
                "data": _body(replay),
                "meta": {"request_id": request.state.request_id},
            }
        if body.rate_source == "ABA_AUTOMATIC":
            quote = _invoke(provider.current_sell_rate)
            reference_rate = quote.reference_rate_khr_per_usd
            source_reference = quote.source_reference.strip()
            applicable_at = quote.applicable_at
            fallback_reason = None
            if (
                reference_rate <= 0
                or not source_reference
                or len(source_reference) > 500
                or applicable_at.tzinfo is None
            ):
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        else:
            try:
                provider.current_sell_rate()
            except ExchangeRateSourceUnavailable:
                pass
            else:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT)
            reference_rate = cast(Decimal, body.reference_rate_khr_per_usd)
            source_reference = cast(str, body.source_reference)
            applicable_at = cast(datetime, body.applicable_at)
            fallback_reason = cast(str, body.fallback_reason)
        system_rate = int(
            (reference_rate * Decimal("1.005")).to_integral_value(rounding=ROUND_CEILING)
        )
        unrounded = Decimal(body.usd_amount_cents) * Decimal(system_rate) / Decimal(100)
        record = ExchangeRateRecord(
            uuid4(),
            reference_rate,
            system_rate,
            body.rate_source,
            source_reference,
            applicable_at,
            body.usd_amount_cents,
            unrounded,
            int(unrounded.to_integral_value(rounding=ROUND_CEILING)),
            fallback_reason,
        )
        persisted = _invoke(
            lambda: flow.confirm_exchange_rate(
                property_id,
                record=record,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
        )
        return {
            "data": _body(persisted),
            "meta": {"request_id": request.state.request_id},
        }

    return router
