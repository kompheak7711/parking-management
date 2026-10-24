"""Authorized Utility Meter, Reading, batch-entry, and preview API."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Context, Decimal, localcontext
from typing import Annotated, Literal, Protocol, cast
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from property_rental.browser_security import require_browser_mutation
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.measurement_units import fixed_measurement_unit_input
from property_rental.settings import Settings
from property_rental.utility import (
    PostgresUtilityService,
    UtilityCalculationSnapshot,
    UtilityPreviewSourceKind,
)

UTILITY_READ_CAPABILITY = "utility.read"
UTILITY_METER_MANAGE_CAPABILITY = "utility_meters.manage"
UTILITY_READING_RECORD_CAPABILITY = "utility_readings.record"
UTILITY_READING_CORRECT_CAPABILITY = "utility_readings.correct"
UTILITY_CALCULATE_CAPABILITY = "utility.calculate"
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25
MAX_BATCH_SIZE = 100
_READING_VALUE_QUANTUM = Decimal("0.000001")
_READING_VALUE_CONTEXT = Context(prec=20)
_READING_VALUE_ADAPTER: TypeAdapter[Decimal] = TypeAdapter(
    Annotated[
        Decimal,
        Field(ge=0, max_digits=20, decimal_places=6, allow_inf_nan=False),
    ]
)
_CANONICAL_NUMERIC_STRING = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")


class UtilityResourceNotFound(LookupError):
    pass


class UtilityResourceConflict(RuntimeError):
    pass


class UtilityResourceVersionConflict(UtilityResourceConflict):
    def __init__(self, current_version: int) -> None:
        super().__init__("Utility resource version changed")
        self.current_version = current_version


class UtilityResourceIdempotencyConflict(UtilityResourceConflict):
    pass


class MeterSerialNumberInUse(UtilityResourceConflict):
    """Another Meter of the Property, current or replaced, has this serial (DL-071 answer 12)."""


class UtilityResourceInvalid(ValueError):
    pass


class UtilityResourceUnavailable(RuntimeError):
    pass


def _canonical_reading_value(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (Decimal, str)):
        raise UtilityResourceInvalid("Utility reading value is invalid")
    if isinstance(value, str) and _CANONICAL_NUMERIC_STRING.fullmatch(value) is None:
        raise UtilityResourceInvalid("Utility reading value is invalid")
    with localcontext(_READING_VALUE_CONTEXT):
        try:
            normalized = _READING_VALUE_ADAPTER.validate_python(value)
        except ValidationError as exc:
            raise UtilityResourceInvalid("Utility reading value is invalid") from exc
        if normalized == 0:
            normalized = abs(normalized)
        return format(normalized.quantize(_READING_VALUE_QUANTUM), "f")


@dataclass(frozen=True, slots=True)
class MeterReplacementEvidenceRecord:
    id: UUID
    failed_meter_id: UUID
    replacement_meter_id: UUID
    failed_boundary_reading_id: UUID | None
    replacement_initial_reading_id: UUID | None
    failure_date: date | None
    replacement_date: date
    expected_failed_meter_version: int | None
    reason: str
    occurred_at: datetime
    actor_id: UUID
    idempotency_key: UUID | None
    request_digest: str | None
    request_evidence: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class MeterRecord:
    id: UUID
    property_id: UUID
    unit_id: UUID
    utility_type: str
    serial_number: str
    measurement_unit_code: str
    description: str | None
    installed_date: date
    failure_date: date | None
    deactivated_date: date | None
    memo: str | None
    version: int
    created_at: datetime
    created_by: UUID
    updated_at: datetime
    updated_by: UUID
    replaced_meter_id: UUID | None
    replacement_meter_id: UUID | None
    replacement_date: date | None
    replacement_events: tuple[MeterReplacementEvidenceRecord, ...]


@dataclass(frozen=True, slots=True)
class ReadingCorrectionRecord:
    id: UUID
    previous_value: Decimal
    corrected_value: Decimal
    reason: str
    occurred_at: datetime
    actor_id: UUID
    authorization_reference: str


@dataclass(frozen=True, slots=True)
class ReadingRecord:
    id: UUID
    property_id: UUID
    meter_id: UUID
    unit_id: UUID
    utility_type: str
    measurement_unit_code: str
    reading_date: date
    original_value: Decimal
    effective_value: Decimal
    source_kind: str
    source_evidence: str
    validated_at: datetime | None
    validated_by: UUID | None
    version: int
    created_at: datetime
    created_by: UUID
    corrections: tuple[ReadingCorrectionRecord, ...]


@dataclass(frozen=True, slots=True)
class CorrectionImpactRecord:
    consumption_period_id: UUID
    previous_consumption_quantity: Decimal
    corrected_consumption_quantity: Decimal
    billing_effect_kind: str
    invoice_line_id: UUID | None
    source_invoice_id: UUID | None
    calculated_difference_usd_cents: int | None
    invoice_adjustment_id: UUID | None


@dataclass(frozen=True, slots=True)
class CorrectionResult:
    reading: ReadingRecord
    correction: ReadingCorrectionRecord
    impacts: tuple[CorrectionImpactRecord, ...]


@dataclass(frozen=True, slots=True)
class ResourcePage:
    items: tuple[MeterRecord | ReadingRecord, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class BatchItemResult:
    index: int
    idempotency_key: UUID
    status: Literal["SUCCEEDED", "FAILED"]
    reading: ReadingRecord | None = None
    error_code: str | None = None


class UtilityResourceFlow(Protocol):
    def property_for_unit(self, unit_id: UUID) -> UUID: ...

    def property_for_meter(self, meter_id: UUID) -> UUID: ...

    def property_for_reading(self, reading_id: UUID) -> UUID: ...

    def list_meters(self, unit_id: UUID, *, limit: int, cursor: str | None) -> ResourcePage: ...

    def get_meter(self, meter_id: UUID) -> MeterRecord: ...

    def install_meter(
        self,
        unit_id: UUID,
        *,
        payload: dict[str, object],
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> MeterRecord: ...

    def replace_meter(
        self,
        meter_id: UUID,
        *,
        payload: dict[str, object],
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> MeterRecord: ...

    def list_readings(self, meter_id: UUID, *, limit: int, cursor: str | None) -> ResourcePage: ...

    def record_reading(
        self,
        meter_id: UUID,
        *,
        payload: dict[str, object],
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> ReadingRecord: ...

    def correct_reading(
        self,
        reading_id: UUID,
        *,
        payload: dict[str, object],
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> CorrectionResult: ...

    def record_batch(
        self,
        property_id: UUID,
        *,
        mode: str,
        items: list[dict[str, object]],
        actor_id: UUID,
        idempotency_key: UUID | None,
        request_digest: str | None,
    ) -> tuple[BatchItemResult, ...]: ...

    def preview(
        self,
        property_id: UUID,
        *,
        source_kind: UtilityPreviewSourceKind,
        source_id: UUID,
        generation_at: datetime,
        actor: AuthenticatedActor,
    ) -> UtilityCalculationSnapshot: ...


class UnavailableUtilityResourceFlow:
    def __getattr__(self, _: str) -> object:
        raise UtilityResourceUnavailable("Utility persistence is unavailable")


def _encode_cursor(value: date, record_id: UUID) -> str:
    return (
        base64.urlsafe_b64encode(f"{value.isoformat()}|{record_id}".encode()).decode().rstrip("=")
    )


def _decode_cursor(value: str | None) -> tuple[date, UUID] | None:
    if value is None:
        return None
    try:
        raw = base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode()).decode()
        left, right = raw.split("|", 1)
        return date.fromisoformat(left), UUID(right)
    except (ValueError, UnicodeDecodeError) as exc:
        raise UtilityResourceInvalid("Invalid cursor") from exc


def _optional_uuid(value: object) -> UUID | None:
    return None if value is None else UUID(str(value))


def _correction(value: dict[str, object]) -> ReadingCorrectionRecord:
    return ReadingCorrectionRecord(
        id=UUID(str(value["id"])),
        previous_value=Decimal(str(value["previous_value"])),
        corrected_value=Decimal(str(value["corrected_value"])),
        reason=str(value["reason"]),
        occurred_at=datetime.fromisoformat(str(value["occurred_at"])),
        actor_id=UUID(str(value["actor_id"])),
        authorization_reference=str(value["authorization_reference"]),
    )


METER_COLUMNS = """
meter.id,unit.property_id,meter.unit_id,meter.utility_type,meter.serial_number,
meter.measurement_unit_code,meter.description,meter.installed_date,meter.failure_date,
meter.deactivated_date,meter.memo,meter.version,meter.created_at,meter.created_by,
meter.updated_at,meter.updated_by,prior.failed_meter_id,next_event.replacement_meter_id,
COALESCE(prior.replacement_date,next_event.replacement_date),
COALESCE((
  SELECT jsonb_agg(jsonb_build_object(
    'id',replacement_event.id,'failed_meter_id',replacement_event.failed_meter_id,
    'replacement_meter_id',replacement_event.replacement_meter_id,
    'failed_boundary_reading_id',replacement_event.failed_boundary_reading_id,
    'replacement_initial_reading_id',replacement_event.replacement_initial_reading_id,
    'failure_date',replacement_event.failure_date,
    'replacement_date',replacement_event.replacement_date,
    'expected_failed_meter_version',replacement_event.expected_failed_meter_version,
    'reason',replacement_event.reason,'occurred_at',replacement_event.occurred_at,
    'actor_id',replacement_event.actor_id,
    'idempotency_key',replacement_event.request_idempotency_key,
    'request_digest',replacement_event.request_digest,
    'request_evidence',replacement_event.request_evidence
  ) ORDER BY replacement_event.replacement_date,replacement_event.id)
  FROM app.utility_meter_replacements AS replacement_event
  WHERE replacement_event.failed_meter_id=meter.id
     OR replacement_event.replacement_meter_id=meter.id
),'[]'::jsonb)
"""


def _replacement_evidence(value: dict[str, object]) -> MeterReplacementEvidenceRecord:
    raw_request = value["request_evidence"]
    return MeterReplacementEvidenceRecord(
        id=UUID(str(value["id"])),
        failed_meter_id=UUID(str(value["failed_meter_id"])),
        replacement_meter_id=UUID(str(value["replacement_meter_id"])),
        failed_boundary_reading_id=_optional_uuid(value["failed_boundary_reading_id"]),
        replacement_initial_reading_id=_optional_uuid(value["replacement_initial_reading_id"]),
        failure_date=(
            None
            if value["failure_date"] is None
            else date.fromisoformat(str(value["failure_date"]))
        ),
        replacement_date=date.fromisoformat(str(value["replacement_date"])),
        expected_failed_meter_version=(
            None
            if value["expected_failed_meter_version"] is None
            else int(str(value["expected_failed_meter_version"]))
        ),
        reason=str(value["reason"]),
        occurred_at=datetime.fromisoformat(str(value["occurred_at"])),
        actor_id=UUID(str(value["actor_id"])),
        idempotency_key=_optional_uuid(value["idempotency_key"]),
        request_digest=None if value["request_digest"] is None else str(value["request_digest"]),
        request_evidence=(None if raw_request is None else cast(dict[str, object], raw_request)),
    )


def _meter(row: tuple[object, ...]) -> MeterRecord:
    raw_events = cast(list[dict[str, object]], row[19])
    return MeterRecord(
        id=UUID(str(row[0])),
        property_id=UUID(str(row[1])),
        unit_id=UUID(str(row[2])),
        utility_type=str(row[3]),
        serial_number=str(row[4]),
        measurement_unit_code=str(row[5]),
        description=None if row[6] is None else str(row[6]),
        installed_date=cast(date, row[7]),
        failure_date=cast(date | None, row[8]),
        deactivated_date=cast(date | None, row[9]),
        memo=None if row[10] is None else str(row[10]),
        version=int(str(row[11])),
        created_at=cast(datetime, row[12]),
        created_by=UUID(str(row[13])),
        updated_at=cast(datetime, row[14]),
        updated_by=UUID(str(row[15])),
        replaced_meter_id=_optional_uuid(row[16]),
        replacement_meter_id=_optional_uuid(row[17]),
        replacement_date=cast(date | None, row[18]),
        replacement_events=tuple(_replacement_evidence(value) for value in raw_events),
    )


READING_COLUMNS = """
reading.id,unit.property_id,reading.meter_id,meter.unit_id,meter.utility_type,
meter.measurement_unit_code,reading.reading_date,reading.reading_value,
COALESCE((SELECT effective.corrected_value
          FROM app.utility_reading_corrections AS effective
          WHERE effective.reading_id=reading.id
          ORDER BY effective.occurred_at DESC,effective.id DESC LIMIT 1),
         reading.reading_value),reading.source_kind,reading.source_evidence,
reading.validated_at,reading.validated_by,
reading.version+(SELECT count(*) FROM app.utility_reading_corrections AS count_correction
                 WHERE count_correction.reading_id=reading.id),
reading.created_at,reading.created_by,
COALESCE((SELECT jsonb_agg(jsonb_build_object(
  'id',correction.id,'previous_value',correction.previous_value,
  'corrected_value',correction.corrected_value,'reason',correction.reason,
  'occurred_at',correction.occurred_at,'actor_id',correction.actor_id,
  'authorization_reference',correction.authorization_reference)
  ORDER BY correction.occurred_at,correction.id)
 FROM app.utility_reading_corrections AS correction
 WHERE correction.reading_id=reading.id),'[]'::jsonb)
"""


def _reading(row: tuple[object, ...]) -> ReadingRecord:
    raw = cast(list[dict[str, object]], row[16])
    return ReadingRecord(
        id=UUID(str(row[0])),
        property_id=UUID(str(row[1])),
        meter_id=UUID(str(row[2])),
        unit_id=UUID(str(row[3])),
        utility_type=str(row[4]),
        measurement_unit_code=str(row[5]),
        reading_date=cast(date, row[6]),
        original_value=Decimal(str(row[7])),
        effective_value=Decimal(str(row[8])),
        source_kind=str(row[9]),
        source_evidence=str(row[10]),
        validated_at=cast(datetime | None, row[11]),
        validated_by=_optional_uuid(row[12]),
        version=int(str(row[13])),
        created_at=cast(datetime, row[14]),
        created_by=UUID(str(row[15])),
        corrections=tuple(_correction(value) for value in raw),
    )


@dataclass(frozen=True, slots=True)
class PostgresUtilityResourceFlow:
    database_url: str
    financial_database_url: str | None = None

    @staticmethod
    def _map_error(exc: psycopg.Error) -> Exception:
        message = str(exc).lower()
        if exc.sqlstate == "P0002":
            return UtilityResourceNotFound("Utility resource was not found")
        if exc.sqlstate == "PRV01":
            try:
                return UtilityResourceVersionConflict(int(exc.diag.message_detail or "0"))
            except ValueError:
                return UtilityResourceConflict("Utility version changed")
        if exc.sqlstate == "23505" and "idempotency" in message:
            return UtilityResourceIdempotencyConflict("Idempotency key was reused")
        if exc.sqlstate == "23505" and "meter serial number" in message:
            return MeterSerialNumberInUse("Meter serial number is already used")
        if exc.sqlstate in {"23505", "23P01", "40001", "55P03", "55000"}:
            return UtilityResourceConflict("Utility command conflicted")
        if exc.sqlstate in {"22003", "22023", "23514", "23502"}:
            return UtilityResourceInvalid("Utility source evidence is invalid")
        return UtilityResourceUnavailable("Utility persistence is unavailable")

    def _one(self, query: str, parameters: tuple[object, ...]) -> tuple[object, ...]:
        try:
            with psycopg.connect(self.database_url) as connection:
                row = connection.execute(query, parameters).fetchone()
        except psycopg.Error as exc:
            raise self._map_error(exc) from exc
        if row is None:
            raise UtilityResourceNotFound("Utility resource was not found")
        return row

    def property_for_unit(self, unit_id: UUID) -> UUID:
        return UUID(str(self._one("SELECT property_id FROM app.units WHERE id=%s", (unit_id,))[0]))

    def property_for_meter(self, meter_id: UUID) -> UUID:
        return UUID(
            str(
                self._one(
                    """SELECT unit.property_id FROM app.utility_meters meter
                   JOIN app.units unit ON unit.id=meter.unit_id WHERE meter.id=%s""",
                    (meter_id,),
                )[0]
            )
        )

    def property_for_reading(self, reading_id: UUID) -> UUID:
        return UUID(
            str(
                self._one(
                    """SELECT unit.property_id FROM app.utility_readings reading
                   JOIN app.utility_meters meter ON meter.id=reading.meter_id
                   JOIN app.units unit ON unit.id=meter.unit_id WHERE reading.id=%s""",
                    (reading_id,),
                )[0]
            )
        )

    def list_meters(self, unit_id: UUID, *, limit: int, cursor: str | None) -> ResourcePage:
        decoded = _decode_cursor(cursor)
        clause = "" if decoded is None else "AND (meter.installed_date,meter.id)<(%s,%s)"
        parameters: list[object] = [unit_id]
        if decoded is not None:
            parameters.extend(decoded)
        parameters.append(limit + 1)
        query = f"""SELECT {METER_COLUMNS} FROM app.utility_meters meter
            JOIN app.units unit ON unit.id=meter.unit_id
            LEFT JOIN app.utility_meter_replacements prior ON prior.replacement_meter_id=meter.id
            LEFT JOIN app.utility_meter_replacements next_event
              ON next_event.failed_meter_id=meter.id
            WHERE meter.unit_id=%s {clause}
            ORDER BY meter.installed_date DESC,meter.id DESC LIMIT %s"""
        try:
            with psycopg.connect(self.database_url) as connection:
                rows = connection.execute(query, tuple(parameters)).fetchall()
        except psycopg.Error as exc:
            raise self._map_error(exc) from exc
        records = tuple(_meter(row) for row in rows[:limit])
        next_cursor = (
            _encode_cursor(records[-1].installed_date, records[-1].id)
            if len(rows) > limit and records
            else None
        )
        return ResourcePage(records, next_cursor)

    def get_meter(self, meter_id: UUID) -> MeterRecord:
        return _meter(
            self._one(
                f"""SELECT {METER_COLUMNS} FROM app.utility_meters meter
            JOIN app.units unit ON unit.id=meter.unit_id
            LEFT JOIN app.utility_meter_replacements prior ON prior.replacement_meter_id=meter.id
            LEFT JOIN app.utility_meter_replacements next_event
              ON next_event.failed_meter_id=meter.id
            WHERE meter.id=%s""",
                (meter_id,),
            )
        )

    def _command_id(self, function: str, parameters: tuple[object, ...]) -> UUID:
        row = self._one(f"SELECT app.{function}({','.join(['%s'] * len(parameters))})", parameters)
        return UUID(str(row[0]))

    def install_meter(
        self,
        unit_id: UUID,
        *,
        payload: dict[str, object],
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> MeterRecord:
        meter_id, reading_id = uuid4(), uuid4()
        initial = cast(dict[str, object], payload["initial_reading"])
        result = self._command_id(
            "install_utility_meter_api",
            (
                unit_id,
                meter_id,
                reading_id,
                payload["utility_type"],
                payload["serial_number"],
                payload["measurement_unit_code"],
                payload.get("description"),
                payload["installed_date"],
                payload.get("memo"),
                initial["reading_date"],
                initial["reading_value"],
                initial["source_evidence"],
                actor_id,
                idempotency_key,
                request_digest,
            ),
        )
        return self.get_meter(result)

    def replace_meter(
        self,
        meter_id: UUID,
        *,
        payload: dict[str, object],
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> MeterRecord:
        replacement_id, reading_id, event_id = uuid4(), uuid4(), uuid4()
        replacement = cast(dict[str, object], payload["replacement_meter"])
        initial = cast(dict[str, object], payload["replacement_initial_reading"])
        result = self._command_id(
            "replace_utility_meter_api",
            (
                meter_id,
                replacement_id,
                reading_id,
                event_id,
                payload["expected_version"],
                payload["failed_boundary_reading_id"],
                payload["failure_date"],
                payload["replacement_date"],
                payload["reason"],
                replacement["serial_number"],
                replacement.get("description"),
                replacement.get("memo"),
                initial["reading_date"],
                initial["reading_value"],
                initial["source_evidence"],
                actor_id,
                idempotency_key,
                request_digest,
            ),
        )
        return self.get_meter(result)

    def list_readings(self, meter_id: UUID, *, limit: int, cursor: str | None) -> ResourcePage:
        decoded = _decode_cursor(cursor)
        clause = "" if decoded is None else "AND (reading.reading_date,reading.id)<(%s,%s)"
        parameters: list[object] = [meter_id]
        if decoded is not None:
            parameters.extend(decoded)
        parameters.append(limit + 1)
        query = f"""SELECT {READING_COLUMNS} FROM app.utility_readings reading
            JOIN app.utility_meters meter ON meter.id=reading.meter_id
            JOIN app.units unit ON unit.id=meter.unit_id
            WHERE reading.meter_id=%s {clause}
            ORDER BY reading.reading_date DESC,reading.id DESC LIMIT %s"""
        try:
            with psycopg.connect(self.database_url) as connection:
                rows = connection.execute(query, tuple(parameters)).fetchall()
        except psycopg.Error as exc:
            raise self._map_error(exc) from exc
        records = tuple(_reading(row) for row in rows[:limit])
        next_cursor = (
            _encode_cursor(records[-1].reading_date, records[-1].id)
            if len(rows) > limit and records
            else None
        )
        return ResourcePage(records, next_cursor)

    def _get_reading(self, reading_id: UUID) -> ReadingRecord:
        return _reading(
            self._one(
                f"""SELECT {READING_COLUMNS} FROM app.utility_readings reading
            JOIN app.utility_meters meter ON meter.id=reading.meter_id
            JOIN app.units unit ON unit.id=meter.unit_id WHERE reading.id=%s""",
                (reading_id,),
            )
        )

    @staticmethod
    def _record_on_connection(
        connection: psycopg.Connection[object],
        meter_id: UUID,
        payload: dict[str, object],
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> UUID:
        reading_id = uuid4()
        row = connection.execute(
            "SELECT app.record_utility_reading_api(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                meter_id,
                reading_id,
                payload["expected_meter_version"],
                payload["reading_date"],
                _canonical_reading_value(payload["reading_value"]),
                payload.get("source_kind", "MANUAL"),
                payload["source_evidence"],
                actor_id,
                idempotency_key,
                request_digest,
            ),
        ).fetchone()
        if row is None:
            raise UtilityResourceUnavailable("Reading command returned no result")
        return UUID(str(cast(tuple[object, ...], row)[0]))

    def record_reading(
        self,
        meter_id: UUID,
        *,
        payload: dict[str, object],
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> ReadingRecord:
        try:
            with psycopg.connect(self.database_url) as connection:
                reading_id = self._record_on_connection(
                    connection, meter_id, payload, actor_id, idempotency_key, request_digest
                )
        except psycopg.Error as exc:
            raise self._map_error(exc) from exc
        return self._get_reading(reading_id)

    def correct_reading(
        self,
        reading_id: UUID,
        *,
        payload: dict[str, object],
        actor_id: UUID,
        idempotency_key: UUID,
        request_digest: str,
    ) -> CorrectionResult:
        correction_id = uuid4()
        result = self._command_id(
            "correct_utility_reading_api",
            (
                reading_id,
                correction_id,
                payload["expected_version"],
                payload["corrected_value"],
                payload["reason"],
                payload["authorization_reference"],
                actor_id,
                idempotency_key,
                request_digest,
            ),
        )
        reading = self._get_reading(reading_id)
        correction = next((item for item in reading.corrections if item.id == result), None)
        if correction is None:
            raise UtilityResourceUnavailable("Correction result was not found")
        try:
            with psycopg.connect(self.database_url) as connection:
                rows = connection.execute(
                    """SELECT consumption_period_id,previous_consumption_quantity,
                    corrected_consumption_quantity,billing_effect_kind,invoice_line_id,source_invoice_id,
                    calculated_difference_usd_cents,invoice_adjustment_id
                    FROM app.utility_reading_correction_impacts WHERE reading_correction_id=%s
                    ORDER BY consumption_period_id""",
                    (result,),
                ).fetchall()
        except psycopg.Error as exc:
            raise self._map_error(exc) from exc
        impacts = tuple(
            CorrectionImpactRecord(
                consumption_period_id=UUID(str(row[0])),
                previous_consumption_quantity=Decimal(str(row[1])),
                corrected_consumption_quantity=Decimal(str(row[2])),
                billing_effect_kind=str(row[3]),
                invoice_line_id=_optional_uuid(row[4]),
                source_invoice_id=_optional_uuid(row[5]),
                calculated_difference_usd_cents=None if row[6] is None else int(str(row[6])),
                invoice_adjustment_id=_optional_uuid(row[7]),
            )
            for row in rows
        )
        return CorrectionResult(reading, correction, impacts)

    def record_batch(
        self,
        property_id: UUID,
        *,
        mode: str,
        items: list[dict[str, object]],
        actor_id: UUID,
        idempotency_key: UUID | None,
        request_digest: str | None,
    ) -> tuple[BatchItemResult, ...]:
        if mode == "ATOMIC_ALL":
            if idempotency_key is None or request_digest is None:
                raise UtilityResourceInvalid("Atomic batch idempotency evidence is required")
            batch_id = uuid4()
            command_items = []
            for index, item in enumerate(items):
                reading = cast(dict[str, object], item["reading"])
                command_items.append(
                    {
                        "index": index,
                        "idempotency_key": str(cast(UUID, item["idempotency_key"])),
                        "meter_id": str(cast(UUID, item["meter_id"])),
                        "reading_id": str(uuid4()),
                        "expected_meter_version": reading["expected_meter_version"],
                        "reading_date": cast(date, reading["reading_date"]).isoformat(),
                        "reading_value": _canonical_reading_value(reading["reading_value"]),
                        "source_kind": reading.get("source_kind", "MANUAL"),
                        "source_evidence": reading["source_evidence"],
                    }
                )
            try:
                with psycopg.connect(self.database_url) as connection:
                    row = connection.execute(
                        "SELECT app.record_utility_reading_batch_api(%s,%s,%s::jsonb,%s,%s,%s)",
                        (
                            property_id,
                            batch_id,
                            json.dumps(command_items, separators=(",", ":")),
                            actor_id,
                            idempotency_key,
                            request_digest,
                        ),
                    ).fetchone()
            except psycopg.Error as exc:
                raise self._map_error(exc) from exc
            if row is None:
                raise UtilityResourceUnavailable("Atomic Reading batch returned no result")
            raw = cast(list[dict[str, object]], cast(tuple[object, ...], row)[0])
            return tuple(
                BatchItemResult(
                    index=int(str(item["index"])),
                    idempotency_key=UUID(str(item["idempotency_key"])),
                    status=cast(Literal["SUCCEEDED", "FAILED"], str(item["status"])),
                    reading=(
                        None
                        if item.get("reading_id") is None
                        else self._get_reading(UUID(str(item["reading_id"])))
                    ),
                    error_code=(
                        None if item.get("error_code") is None else str(item["error_code"])
                    ),
                )
                for item in raw
            )

        raw_results: list[tuple[int, UUID, str, UUID | None, str | None]] = []

        def record_item(connection: psycopg.Connection[object], item: dict[str, object]) -> UUID:
            meter_property = connection.execute(
                """SELECT unit.property_id
                FROM app.utility_meters meter
                JOIN app.units unit ON unit.id=meter.unit_id
                WHERE meter.id=%s""",
                (item["meter_id"],),
            ).fetchone()
            if meter_property is None:
                raise UtilityResourceNotFound("Meter was not found")
            if UUID(str(cast(tuple[object, ...], meter_property)[0])) != property_id:
                raise UtilityResourceNotFound("Meter was not found")
            return self._record_on_connection(
                connection,
                cast(UUID, item["meter_id"]),
                cast(dict[str, object], item["reading"]),
                actor_id,
                cast(UUID, item["idempotency_key"]),
                cast(str, item["request_digest"]),
            )

        try:
            with psycopg.connect(self.database_url) as connection:
                for index, item in enumerate(items):
                    key = cast(UUID, item["idempotency_key"])
                    try:
                        with connection.transaction():
                            reading_id = record_item(connection, item)
                        raw_results.append((index, key, "SUCCEEDED", reading_id, None))
                    except (psycopg.Error, UtilityResourceNotFound) as exc:
                        mapped = self._map_error(exc) if isinstance(exc, psycopg.Error) else exc
                        code = (
                            "NOT_FOUND"
                            if isinstance(mapped, UtilityResourceNotFound)
                            else "CONFLICT"
                            if isinstance(mapped, UtilityResourceConflict)
                            else "VALIDATION_ERROR"
                            if isinstance(mapped, UtilityResourceInvalid)
                            else "SERVICE_UNAVAILABLE"
                        )
                        raw_results.append((index, key, "FAILED", None, code))
        except (
            UtilityResourceNotFound,
            UtilityResourceConflict,
            UtilityResourceInvalid,
            UtilityResourceUnavailable,
        ):
            raise
        except psycopg.Error as exc:
            raise self._map_error(exc) from exc
        return tuple(
            BatchItemResult(
                index,
                key,
                cast(Literal["SUCCEEDED", "FAILED"], item_status),
                None if reading_id is None else self._get_reading(reading_id),
                error_code,
            )
            for index, key, item_status, reading_id, error_code in raw_results
        )

    def preview(
        self,
        property_id: UUID,
        *,
        source_kind: UtilityPreviewSourceKind,
        source_id: UUID,
        generation_at: datetime,
        actor: AuthenticatedActor,
    ) -> UtilityCalculationSnapshot:
        if self.financial_database_url is None:
            raise UtilityResourceUnavailable("Financial Utility persistence is unavailable")
        try:
            return PostgresUtilityService(
                self.financial_database_url, property_id, UUID(actor.actor_id)
            ).preview(source_id, generation_at, source_kind=source_kind, actor=actor)
        except (LookupError, ValueError, PermissionError, RuntimeError) as exc:
            name = type(exc).__name__
            if "NotFound" in name:
                raise UtilityResourceNotFound("Utility preview source was not found") from exc
            if "Conflict" in name:
                raise UtilityResourceConflict("Utility preview conflicted") from exc
            if "Invalid" in name:
                raise UtilityResourceInvalid("Utility preview is invalid") from exc
            if "Authorization" in name:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from exc
            raise UtilityResourceUnavailable("Utility preview is unavailable") from exc


class InitialReadingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reading_date: date
    reading_value: Decimal = Field(ge=0, max_digits=20, decimal_places=6)
    source_evidence: str = Field(min_length=1, max_length=500)

    @field_validator("reading_value")
    @classmethod
    def finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("reading_value must be finite")
        return value


class MeterInstallInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    utility_type: Literal["ELECTRICITY", "WATER"]
    serial_number: str = Field(min_length=1, max_length=200)
    measurement_unit_code: str = Field(min_length=1, max_length=50)
    description: str | None = Field(default=None, min_length=1, max_length=500)
    installed_date: date
    memo: str | None = Field(default=None, min_length=1, max_length=500)
    initial_reading: InitialReadingInput

    @model_validator(mode="before")
    @classmethod
    def fixed_measurement_unit(cls, data: object) -> object:
        return fixed_measurement_unit_input(data)

    @model_validator(mode="after")
    def boundary(self) -> MeterInstallInput:
        if self.initial_reading.reading_date != self.installed_date:
            raise ValueError("initial reading must establish the installation boundary")
        return self


class ReplacementMeterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    serial_number: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=500)
    memo: str | None = Field(default=None, min_length=1, max_length=500)


class MeterReplaceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    failed_boundary_reading_id: UUID
    failure_date: date
    replacement_date: date
    reason: str = Field(min_length=1, max_length=500)
    replacement_meter: ReplacementMeterInput
    replacement_initial_reading: InitialReadingInput

    @model_validator(mode="after")
    def boundary(self) -> MeterReplaceInput:
        if self.replacement_date <= self.failure_date:
            raise ValueError("replacement_date must follow failure_date")
        if self.replacement_initial_reading.reading_date != self.replacement_date:
            raise ValueError("replacement initial reading must establish the replacement boundary")
        return self


class ReadingCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_meter_version: int = Field(ge=1)
    reading_date: date
    reading_value: Decimal = Field(ge=0, max_digits=20, decimal_places=6)
    source_kind: Literal["MANUAL"] = "MANUAL"
    source_evidence: str = Field(min_length=1, max_length=500)

    @field_validator("reading_value")
    @classmethod
    def finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("reading_value must be finite")
        return value


class ReadingCorrectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    corrected_value: Decimal = Field(ge=0, max_digits=20, decimal_places=6)
    reason: str = Field(min_length=1, max_length=500)
    authorization_reference: str = Field(min_length=1, max_length=200)

    @field_validator("corrected_value")
    @classmethod
    def finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("corrected_value must be finite")
        return value


class BatchReadingItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: UUID
    meter_id: UUID
    reading: ReadingCreateInput


class ReadingBatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["ATOMIC_ALL", "PARTIAL"]
    items: list[BatchReadingItem] = Field(min_length=1, max_length=MAX_BATCH_SIZE)

    @model_validator(mode="after")
    def unique_keys(self) -> ReadingBatchInput:
        keys = [item.idempotency_key for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("batch idempotency keys must be unique")
        return self


class PreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    property_id: UUID
    source_kind: Literal["CONSUMPTION_PERIOD", "ESTIMATION_CASE"]
    source_id: UUID
    generation_at: datetime

    @field_validator("generation_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generation_at must be timezone-aware")
        return value


def _digest(payload: BaseModel, action: str, target_id: UUID) -> str:
    encoded = json.dumps(
        {
            "action": action,
            "target_id": str(target_id),
            "payload": payload.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _actor(request: Request, resolver: ActorResolver) -> AuthenticatedActor:
    actor = resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return actor


def _actor_id(actor: AuthenticatedActor) -> UUID:
    try:
        return UUID(actor.actor_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from exc


def _authorized(actor: AuthenticatedActor, capability: str, property_id: UUID) -> None:
    if not is_authorized(
        actor, AuthorizationRequirement(capability=capability, property_id=str(property_id))
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


def _authorized_detail(actor: AuthenticatedActor, capability: str, property_id: UUID) -> None:
    if not is_authorized(
        actor, AuthorizationRequirement(capability=capability, property_id=str(property_id))
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


def _invoke(command: Callable[[], object]) -> object:
    try:
        return command()
    except UtilityResourceNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except UtilityResourceVersionConflict:
        raise
    except MeterSerialNumberInUse:
        raise
    except (UtilityResourceConflict, UtilityResourceIdempotencyConflict) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT) from exc
    except UtilityResourceInvalid as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    except UtilityResourceUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc


def _value(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _meter_body(record: MeterRecord) -> dict[str, object]:
    return {
        "id": str(record.id),
        "property_id": str(record.property_id),
        "unit_id": str(record.unit_id),
        "utility_type": record.utility_type,
        "serial_number": record.serial_number,
        "measurement_unit_code": record.measurement_unit_code,
        "description": record.description,
        "installed_date": record.installed_date.isoformat(),
        "failure_date": record.failure_date.isoformat() if record.failure_date else None,
        "deactivated_date": record.deactivated_date.isoformat()
        if record.deactivated_date
        else None,
        "current": record.deactivated_date is None,
        "version": record.version,
        "memo": record.memo,
        "provenance": {
            "created_at": record.created_at.isoformat(),
            "created_by": str(record.created_by),
            "updated_at": record.updated_at.isoformat(),
            "updated_by": str(record.updated_by),
        },
        "replacement": {
            "replaced_meter_id": str(record.replaced_meter_id)
            if record.replaced_meter_id
            else None,
            "replacement_meter_id": str(record.replacement_meter_id)
            if record.replacement_meter_id
            else None,
            "replacement_date": record.replacement_date.isoformat()
            if record.replacement_date
            else None,
            "events": [
                {
                    "id": str(event.id),
                    "failed_meter_id": str(event.failed_meter_id),
                    "replacement_meter_id": str(event.replacement_meter_id),
                    "failed_boundary_reading_id": str(event.failed_boundary_reading_id)
                    if event.failed_boundary_reading_id
                    else None,
                    "replacement_initial_reading_id": str(event.replacement_initial_reading_id)
                    if event.replacement_initial_reading_id
                    else None,
                    "failure_date": event.failure_date.isoformat() if event.failure_date else None,
                    "replacement_date": event.replacement_date.isoformat(),
                    "expected_failed_meter_version": event.expected_failed_meter_version,
                    "reason": event.reason,
                    "occurred_at": event.occurred_at.isoformat(),
                    "actor_id": str(event.actor_id),
                    "idempotency_key": str(event.idempotency_key)
                    if event.idempotency_key
                    else None,
                    "request_digest": event.request_digest,
                    "request_evidence": event.request_evidence,
                }
                for event in record.replacement_events
            ],
        },
        "readings_url": f"/api/v1/meters/{record.id}/readings",
    }


def _correction_body(record: ReadingCorrectionRecord) -> dict[str, object]:
    return {
        "id": str(record.id),
        "previous_value": _value(record.previous_value),
        "corrected_value": _value(record.corrected_value),
        "reason": record.reason,
        "occurred_at": record.occurred_at.isoformat(),
        "actor_id": str(record.actor_id),
        "authorization_reference": record.authorization_reference,
    }


def _reading_body(record: ReadingRecord) -> dict[str, object]:
    return {
        "id": str(record.id),
        "property_id": str(record.property_id),
        "meter_id": str(record.meter_id),
        "unit_id": str(record.unit_id),
        "utility_type": record.utility_type,
        "measurement_unit_code": record.measurement_unit_code,
        "reading_date": record.reading_date.isoformat(),
        "period": {"boundary_date": record.reading_date.isoformat()},
        "original_value": _value(record.original_value),
        "effective_value": _value(record.effective_value),
        "validated": record.validated_at is not None,
        "validated_at": record.validated_at.isoformat() if record.validated_at else None,
        "validated_by": str(record.validated_by) if record.validated_by else None,
        "source": {"kind": record.source_kind, "evidence": record.source_evidence},
        "version": record.version,
        "provenance": {
            "created_at": record.created_at.isoformat(),
            "created_by": str(record.created_by),
        },
        "corrections": [_correction_body(item) for item in record.corrections],
    }


def _snapshot_body(value: UtilityCalculationSnapshot) -> dict[str, object]:
    body = asdict(value)
    for key, item in tuple(body.items()):
        if isinstance(item, (UUID, date, datetime)):
            body[key] = item.isoformat() if not isinstance(item, UUID) else str(item)
        elif isinstance(item, Decimal):
            body[key] = _value(item)
        elif hasattr(item, "value"):
            body[key] = item.value
    body["basis_period_ids"] = [str(item) for item in value.basis_period_ids]
    body["basis_sources"] = [
        {key: str(item) for key, item in asdict(source).items()} for source in value.basis_sources
    ]
    return body


def _allow_query(request: Request, allowed: set[str]) -> None:
    if set(request.query_params).difference(allowed):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)


def create_utility_router(
    resolver: ActorResolver, flow: UtilityResourceFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["utilities"])

    def page(page: ResourcePage, request: Request, limit: int) -> dict[str, object]:
        items = [
            _meter_body(item) if isinstance(item, MeterRecord) else _reading_body(item)
            for item in page.items
        ]
        return {
            "data": items,
            "page": {"limit": limit, "next_cursor": page.next_cursor},
            "meta": {"request_id": request.state.request_id},
        }

    @router.get("/units/{unit_id}/meters")
    def list_meters(
        unit_id: UUID,
        request: Request,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        cursor: Annotated[str | None, Query(max_length=256)] = None,
    ) -> dict[str, object]:
        _allow_query(request, {"limit", "cursor"})
        actor = _actor(request, resolver)
        property_id = cast(UUID, _invoke(lambda: flow.property_for_unit(unit_id)))
        _authorized(actor, UTILITY_READ_CAPABILITY, property_id)
        return page(
            cast(
                ResourcePage, _invoke(lambda: flow.list_meters(unit_id, limit=limit, cursor=cursor))
            ),
            request,
            limit,
        )

    @router.post("/units/{unit_id}/meters", status_code=status.HTTP_201_CREATED)
    def install_meter(
        unit_id: UUID,
        body: MeterInstallInput,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        _allow_query(request, set())
        actor = _actor(request, resolver)
        property_id = cast(UUID, _invoke(lambda: flow.property_for_unit(unit_id)))
        _authorized(actor, UTILITY_METER_MANAGE_CAPABILITY, property_id)
        require_browser_mutation(request, settings)
        record = cast(
            MeterRecord,
            _invoke(
                lambda: flow.install_meter(
                    unit_id,
                    payload=body.model_dump(),
                    actor_id=_actor_id(actor),
                    idempotency_key=idempotency_key,
                    request_digest=_digest(body, "INSTALL_METER", unit_id),
                )
            ),
        )
        response.headers["Location"] = f"/api/v1/meters/{record.id}"
        response.headers["ETag"] = f'"{record.version}"'
        return {"data": _meter_body(record), "meta": {"request_id": request.state.request_id}}

    @router.get("/meters/{meter_id}")
    def get_meter(meter_id: UUID, request: Request, response: Response) -> dict[str, object]:
        _allow_query(request, set())
        actor = _actor(request, resolver)
        record = cast(MeterRecord, _invoke(lambda: flow.get_meter(meter_id)))
        _authorized_detail(actor, UTILITY_READ_CAPABILITY, record.property_id)
        response.headers["ETag"] = f'"{record.version}"'
        return {"data": _meter_body(record), "meta": {"request_id": request.state.request_id}}

    @router.post("/meters/{meter_id}/replace", status_code=status.HTTP_201_CREATED)
    def replace_meter(
        meter_id: UUID,
        body: MeterReplaceInput,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        _allow_query(request, set())
        actor = _actor(request, resolver)
        property_id = cast(UUID, _invoke(lambda: flow.property_for_meter(meter_id)))
        _authorized(actor, UTILITY_METER_MANAGE_CAPABILITY, property_id)
        require_browser_mutation(request, settings)
        record = cast(
            MeterRecord,
            _invoke(
                lambda: flow.replace_meter(
                    meter_id,
                    payload=body.model_dump(),
                    actor_id=_actor_id(actor),
                    idempotency_key=idempotency_key,
                    request_digest=_digest(body, "REPLACE_METER", meter_id),
                )
            ),
        )
        response.headers["Location"] = f"/api/v1/meters/{record.id}"
        response.headers["ETag"] = f'"{record.version}"'
        return {"data": _meter_body(record), "meta": {"request_id": request.state.request_id}}

    @router.get("/meters/{meter_id}/readings")
    def list_readings(
        meter_id: UUID,
        request: Request,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        cursor: Annotated[str | None, Query(max_length=256)] = None,
    ) -> dict[str, object]:
        _allow_query(request, {"limit", "cursor"})
        actor = _actor(request, resolver)
        property_id = cast(UUID, _invoke(lambda: flow.property_for_meter(meter_id)))
        _authorized_detail(actor, UTILITY_READ_CAPABILITY, property_id)
        return page(
            cast(
                ResourcePage,
                _invoke(lambda: flow.list_readings(meter_id, limit=limit, cursor=cursor)),
            ),
            request,
            limit,
        )

    @router.post("/meters/{meter_id}/readings", status_code=status.HTTP_201_CREATED)
    def record_reading(
        meter_id: UUID,
        body: ReadingCreateInput,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        _allow_query(request, set())
        actor = _actor(request, resolver)
        property_id = cast(UUID, _invoke(lambda: flow.property_for_meter(meter_id)))
        _authorized(actor, UTILITY_READING_RECORD_CAPABILITY, property_id)
        require_browser_mutation(request, settings)
        record = cast(
            ReadingRecord,
            _invoke(
                lambda: flow.record_reading(
                    meter_id,
                    payload=body.model_dump(),
                    actor_id=_actor_id(actor),
                    idempotency_key=idempotency_key,
                    request_digest=_digest(body, "RECORD_READING", meter_id),
                )
            ),
        )
        response.headers["Location"] = f"/api/v1/utility-readings/{record.id}"
        response.headers["ETag"] = f'"{record.version}"'
        return {"data": _reading_body(record), "meta": {"request_id": request.state.request_id}}

    @router.post("/utility-readings/{reading_id}/correct", status_code=status.HTTP_201_CREATED)
    def correct_reading(
        reading_id: UUID,
        body: ReadingCorrectInput,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        _allow_query(request, set())
        actor = _actor(request, resolver)
        property_id = cast(UUID, _invoke(lambda: flow.property_for_reading(reading_id)))
        _authorized(actor, UTILITY_READING_CORRECT_CAPABILITY, property_id)
        require_browser_mutation(request, settings)
        result = cast(
            CorrectionResult,
            _invoke(
                lambda: flow.correct_reading(
                    reading_id,
                    payload=body.model_dump(),
                    actor_id=_actor_id(actor),
                    idempotency_key=idempotency_key,
                    request_digest=_digest(body, "CORRECT_READING", reading_id),
                )
            ),
        )
        response.headers["Location"] = (
            f"/api/v1/utility-readings/{reading_id}/corrections/{result.correction.id}"
        )
        return {
            "data": {
                "reading": _reading_body(result.reading),
                "correction": _correction_body(result.correction),
                "affected_calculations": [
                    {
                        "consumption_period_id": str(item.consumption_period_id),
                        "previous_consumption_quantity": _value(item.previous_consumption_quantity),
                        "corrected_consumption_quantity": _value(
                            item.corrected_consumption_quantity
                        ),
                        "billing_effect_kind": item.billing_effect_kind,
                        "issued_line": {
                            "invoice_line_id": str(item.invoice_line_id)
                            if item.invoice_line_id
                            else None,
                            "source_invoice_id": str(item.source_invoice_id)
                            if item.source_invoice_id
                            else None,
                            "calculated_difference_usd_cents": item.calculated_difference_usd_cents,
                            "invoice_adjustment_id": str(item.invoice_adjustment_id)
                            if item.invoice_adjustment_id
                            else None,
                        },
                    }
                    for item in result.impacts
                ],
            },
            "meta": {"request_id": request.state.request_id},
        }

    @router.post("/properties/{property_id}/utility-readings:batch")
    def record_batch(
        property_id: UUID,
        body: ReadingBatchInput,
        request: Request,
        idempotency_key: Annotated[UUID | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, object]:
        _allow_query(request, set())
        actor = _actor(request, resolver)
        _authorized(actor, UTILITY_READING_RECORD_CAPABILITY, property_id)
        require_browser_mutation(request, settings)
        if body.mode == "ATOMIC_ALL" and idempotency_key is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Idempotency-Key is required for ATOMIC_ALL",
            )
        items = [
            {
                "idempotency_key": item.idempotency_key,
                "meter_id": item.meter_id,
                "reading": item.reading.model_dump(),
                "request_digest": _digest(item.reading, "RECORD_READING", item.meter_id),
            }
            for item in body.items
        ]
        results = cast(
            tuple[BatchItemResult, ...],
            _invoke(
                lambda: flow.record_batch(
                    property_id,
                    mode=body.mode,
                    items=items,
                    actor_id=_actor_id(actor),
                    idempotency_key=idempotency_key,
                    request_digest=(
                        _digest(body, "RECORD_READING_BATCH", property_id)
                        if body.mode == "ATOMIC_ALL"
                        else None
                    ),
                )
            ),
        )
        return {
            "data": {
                "mode": body.mode,
                "items": [
                    {
                        "index": item.index,
                        "idempotency_key": str(item.idempotency_key),
                        "status": item.status,
                        "reading": _reading_body(item.reading) if item.reading else None,
                        "error": None if item.error_code is None else {"code": item.error_code},
                    }
                    for item in results
                ],
            },
            "meta": {"request_id": request.state.request_id},
        }

    @router.post("/utility-billing/preview")
    def preview(body: PreviewInput, request: Request) -> dict[str, object]:
        _allow_query(request, set())
        actor = _actor(request, resolver)
        _authorized(actor, UTILITY_CALCULATE_CAPABILITY, body.property_id)
        require_browser_mutation(request, settings)
        snapshot = cast(
            UtilityCalculationSnapshot,
            _invoke(
                lambda: flow.preview(
                    body.property_id,
                    source_kind=UtilityPreviewSourceKind(body.source_kind),
                    source_id=body.source_id,
                    generation_at=body.generation_at,
                    actor=actor,
                )
            ),
        )
        return {
            "data": _snapshot_body(snapshot),
            "meta": {"request_id": request.state.request_id, "persisted": False, "issued": False},
        }

    return router
