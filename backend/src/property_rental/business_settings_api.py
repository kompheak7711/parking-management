"""Settings > Business: document numbering and Invoice types (V1.1 rework part 2, DL-118).

`GET /api/v1/properties/{property_id}/number-rules` lists each document's letters, this year's
last number and the next number (`configuration.read`). `PUT .../number-rules/{document_type}`
changes the letters (`settings.manage`); new numbers use them and printed numbers never change.

`GET /api/v1/properties/{property_id}/invoice-types` lists the kinds of Invoice with late payment
Yes/No (`configuration.read`). `PUT .../invoice-types/{code}` switches late payment on or off with
a reason (`settings.manage`). The database functions write the rows and the History; the program
never writes the tables itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from property_rental.access_control import SETTINGS_MANAGE_CAPABILITY
from property_rental.browser_security import require_browser_mutation
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.settings import Settings

CONFIGURATION_READ = "configuration.read"
CODE = re.compile(r"^[A-Z][A-Z_]{1,40}$")
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class BusinessSettingNotFound(LookupError):
    """No document or Invoice type has this code, or the Property is not there."""


class BusinessSettingInvalid(ValueError):
    """The letters or the reason are refused."""


class BusinessSettingConflict(RuntimeError):
    """Another document already uses these letters."""


class BusinessSettingUnavailable(RuntimeError):
    """Persistence is unavailable."""


@dataclass(frozen=True, slots=True)
class NumberRule:
    document_type: str
    year: int
    last_number: int
    format: str
    updated_at: datetime
    updated_by: UUID | None

    @property
    def letters(self) -> str:
        return self.format.removesuffix("yy000n")

    @property
    def next_number(self) -> str:
        following = self.last_number + 1
        digits = f"{following:04d}"
        return f"{self.letters}{self.year % 100:02d}{digits}"


@dataclass(frozen=True, slots=True)
class InvoiceType:
    code: str
    name_en: str
    name_kh: str
    late_payment: bool
    version: int
    updated_at: datetime
    updated_by: UUID | None


class BusinessSettingsFlow(Protocol):
    def number_rules(self, property_id: UUID) -> tuple[NumberRule, ...]: ...

    def set_letters(
        self, property_id: UUID, document_type: str, *, letters: str, actor_id: str
    ) -> None: ...

    def invoice_types(self) -> tuple[InvoiceType, ...]: ...

    def set_late_payment(
        self, property_id: UUID, code: str, *, late_payment: bool, reason: str, actor_id: str
    ) -> None: ...


class UnavailableBusinessSettingsFlow:
    def number_rules(self, property_id: UUID) -> tuple[NumberRule, ...]:
        del property_id
        raise BusinessSettingUnavailable

    def set_letters(self, property_id: UUID, document_type: str, **_: object) -> None:
        del property_id, document_type
        raise BusinessSettingUnavailable

    def invoice_types(self) -> tuple[InvoiceType, ...]:
        raise BusinessSettingUnavailable

    def set_late_payment(self, property_id: UUID, code: str, **_: object) -> None:
        del property_id, code
        raise BusinessSettingUnavailable


def _refusal(exc: psycopg.Error) -> Exception:
    message = str(exc).splitlines()[0] if str(exc) else ""
    if isinstance(exc, psycopg.errors.UniqueViolation):
        return BusinessSettingConflict("Another document uses these letters")
    if isinstance(exc, psycopg.errors.InvalidParameterValue) and (
        "Unknown" in message or "No Invoice type" in message or "Property" in message
    ):
        return BusinessSettingNotFound(message)
    if isinstance(exc, (psycopg.errors.InvalidParameterValue, psycopg.errors.CheckViolation)):
        return BusinessSettingInvalid(message)
    return BusinessSettingUnavailable("Business settings persistence is unavailable")


class PostgresBusinessSettingsFlow:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def number_rules(self, property_id: UUID) -> tuple[NumberRule, ...]:
        """Each document's row for this year: this year's row, else the latest one."""
        try:
            with psycopg.connect(self._database_url) as connection:
                found = connection.execute(
                    "SELECT date_part('year', timezone(timezone_name, statement_timestamp()))"
                    "::integer FROM app.properties WHERE id = %s",
                    (property_id,),
                ).fetchone()
                if found is None:
                    raise BusinessSettingNotFound("The Property was not found")
                year = int(str(found[0]))
                rows = connection.execute(
                    """
                    SELECT DISTINCT ON (rule.document_type)
                        rule.document_type, rule.year, rule.last_number, rule.format,
                        rule.updated_at, rule.updated_by
                    FROM app.number_rules AS rule
                    WHERE rule.year <= %s
                    ORDER BY rule.document_type, rule.year DESC
                    """,
                    (year,),
                ).fetchall()
        except psycopg.Error as exc:
            raise BusinessSettingUnavailable from exc
        rules = []
        for document_type, row_year, last_number, number_format, updated_at, by in rows:
            this_year = int(str(row_year)) == year
            rules.append(
                NumberRule(
                    str(document_type),
                    year,
                    # A new year starts again at 0001.
                    int(str(last_number)) if this_year else 0,
                    str(number_format),
                    updated_at,
                    None if by is None else UUID(str(by)),
                )
            )
        return tuple(rules)

    def set_letters(
        self, property_id: UUID, document_type: str, *, letters: str, actor_id: str
    ) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    "SELECT app.set_number_rule_letters(%s, %s, %s, %s, %s)",
                    (property_id, document_type, letters, UUID(actor_id), uuid4()),
                )
        except psycopg.Error as exc:
            raise _refusal(exc) from exc

    def invoice_types(self) -> tuple[InvoiceType, ...]:
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    "SELECT code, name_en, name_kh, late_payment, version, updated_at, "
                    "updated_by FROM app.invoice_types WHERE in_use ORDER BY sort_order, code"
                ).fetchall()
        except psycopg.Error as exc:
            raise BusinessSettingUnavailable from exc
        return tuple(
            InvoiceType(
                str(code),
                str(name_en),
                str(name_kh),
                bool(late_payment),
                int(str(version)),
                updated_at,
                None if by is None else UUID(str(by)),
            )
            for code, name_en, name_kh, late_payment, version, updated_at, by in rows
        )

    def set_late_payment(
        self, property_id: UUID, code: str, *, late_payment: bool, reason: str, actor_id: str
    ) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    "SELECT app.set_invoice_type_late_payment(%s, %s, %s, %s, %s, %s)",
                    (property_id, code, late_payment, reason, UUID(actor_id), uuid4()),
                )
        except psycopg.Error as exc:
            raise _refusal(exc) from exc


class LettersChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    letters: str = Field(pattern=r"^[A-Z]{2,5}$")


class LatePaymentChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    late_payment: bool
    reason: Reason


def _number_body(rule: NumberRule) -> dict[str, object]:
    return {
        "document_type": rule.document_type,
        "letters": rule.letters,
        "format": rule.format,
        "year": rule.year,
        "last_number": rule.last_number,
        "next_number": rule.next_number,
        "updated_at": rule.updated_at.isoformat(),
        "updated_by": None if rule.updated_by is None else str(rule.updated_by),
    }


def _type_body(kind: InvoiceType) -> dict[str, object]:
    return {
        "code": kind.code,
        "name_en": kind.name_en,
        "name_kh": kind.name_kh,
        "late_payment": kind.late_payment,
        "version": kind.version,
        "updated_at": kind.updated_at.isoformat(),
        "updated_by": None if kind.updated_by is None else str(kind.updated_by),
    }


def _require(
    request: Request, resolver: ActorResolver, capability: str, property_id: UUID
) -> AuthenticatedActor:
    actor = resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if not is_authorized(
        actor, AuthorizationRequirement(capability=capability, property_id=str(property_id))
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return actor


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, BusinessSettingNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, BusinessSettingConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, BusinessSettingInvalid):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


REFUSED = (
    BusinessSettingNotFound,
    BusinessSettingConflict,
    BusinessSettingInvalid,
    BusinessSettingUnavailable,
)


def create_business_settings_router(
    resolver: ActorResolver, flow: BusinessSettingsFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["business-settings"])

    def numbers(property_id: UUID, request: Request) -> dict[str, object]:
        try:
            rules = flow.number_rules(property_id)
        except REFUSED as exc:
            raise _http(exc) from exc
        return {
            "data": [_number_body(rule) for rule in rules],
            "meta": {"request_id": request.state.request_id},
        }

    def types(request: Request) -> dict[str, object]:
        try:
            kinds = flow.invoice_types()
        except REFUSED as exc:
            raise _http(exc) from exc
        return {
            "data": [_type_body(kind) for kind in kinds],
            "meta": {"request_id": request.state.request_id},
        }

    @router.get("/properties/{property_id}/number-rules")
    def list_number_rules(
        property_id: UUID, request: Request, response: Response
    ) -> dict[str, object]:
        _require(request, resolver, CONFIGURATION_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        return numbers(property_id, request)

    @router.put("/properties/{property_id}/number-rules/{document_type}")
    def change_number_letters(
        property_id: UUID, document_type: str, change: LettersChange, request: Request
    ) -> dict[str, object]:
        actor = _require(request, resolver, SETTINGS_MANAGE_CAPABILITY, property_id)
        require_browser_mutation(request, settings)
        if not CODE.fullmatch(document_type):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            flow.set_letters(
                property_id, document_type, letters=change.letters, actor_id=actor.actor_id
            )
        except REFUSED as exc:
            raise _http(exc) from exc
        return numbers(property_id, request)

    @router.get("/properties/{property_id}/invoice-types")
    def list_invoice_types(
        property_id: UUID, request: Request, response: Response
    ) -> dict[str, object]:
        _require(request, resolver, CONFIGURATION_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        return types(request)

    @router.put("/properties/{property_id}/invoice-types/{code}")
    def change_invoice_type(
        property_id: UUID, code: str, change: LatePaymentChange, request: Request
    ) -> dict[str, object]:
        actor = _require(request, resolver, SETTINGS_MANAGE_CAPABILITY, property_id)
        require_browser_mutation(request, settings)
        if not CODE.fullmatch(code):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            flow.set_late_payment(
                property_id,
                code,
                late_payment=change.late_payment,
                reason=change.reason,
                actor_id=actor.actor_id,
            )
        except REFUSED as exc:
            raise _http(exc) from exc
        return types(request)

    return router
