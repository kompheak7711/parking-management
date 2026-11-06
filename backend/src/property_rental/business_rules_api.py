"""Business rules on the Settings page (V1.1; General Ledger phase 6 step 1, owner 03/11/2026).

`GET /api/v1/properties/{property_id}/business-rules` lists every rule with the value in force
today, a later change if one waits, and the history (`configuration.read`).
`PUT /api/v1/properties/{property_id}/business-rules/{code}` changes a rule from a date that is
not in the past, with a reason; `POST /api/v1/properties/{property_id}/business-rules` adds a new
rule the program does not use yet. Both need `settings.manage` (the Owner, or a user the Owner
gave it). The database functions write the row and the audit event; the program never writes the
tables itself. `read_business_rule` is the one way the program reads a rule's value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

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
ValueUnit = Literal[
    "USD_CENTS",
    "PERCENT",
    "DAYS",
    "DAY_OF_MONTH",
    "COUNT",
    "MINUTES",
    "HOURS",
    "METRES",
    "YES_NO",
    "TIME_OF_DAY",
]
Area = Literal[
    "BILLING",
    "RESERVATIONS",
    "PRICES",
    "QUOTATIONS",
    "RIEL_RATE",
    "LEDGER",
    "STAFF",
    "ATTENDANCE",
    "REPAIRS",
    "SHORT_STAYS",
    "OTHER",
]
CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,62}$")
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class BusinessRuleNotFound(LookupError):
    """No rule has this code, or the Property is not there."""


class BusinessRuleInvalid(ValueError):
    """The value, date or reason is refused."""


class BusinessRuleConflict(RuntimeError):
    """A change for that date or a rule with that code already exists."""


class BusinessRuleUnavailable(RuntimeError):
    """Persistence is unavailable."""


@dataclass(frozen=True, slots=True)
class BusinessRuleValue:
    value: int
    effective_from: date
    reason: str | None
    created_at: datetime
    created_by: UUID | None


@dataclass(frozen=True, slots=True)
class BusinessRule:
    code: str
    name_en: str
    name_kh: str
    value_unit: str
    area: str
    used_by_app: bool
    history: tuple[BusinessRuleValue, ...]

    def in_force(self, on: date) -> BusinessRuleValue | None:
        found = [row for row in self.history if row.effective_from <= on]
        return found[-1] if found else None

    def waiting(self, on: date) -> BusinessRuleValue | None:
        later = [row for row in self.history if row.effective_from > on]
        return later[0] if later else None


class BusinessRuleFlow(Protocol):
    def today(self, property_id: UUID) -> date: ...

    def list_rules(self) -> tuple[BusinessRule, ...]: ...

    def set_rule(
        self,
        property_id: UUID,
        code: str,
        *,
        value: int,
        effective_from: date,
        reason: str,
        actor_id: str,
    ) -> None: ...

    def add_rule(
        self,
        property_id: UUID,
        *,
        code: str,
        name_en: str,
        name_kh: str,
        value_unit: str,
        area: str,
        value: int,
        effective_from: date,
        reason: str | None,
        actor_id: str,
    ) -> None: ...


class UnavailableBusinessRuleFlow:
    def today(self, property_id: UUID) -> date:
        del property_id
        raise BusinessRuleUnavailable

    def list_rules(self) -> tuple[BusinessRule, ...]:
        raise BusinessRuleUnavailable

    def set_rule(self, property_id: UUID, code: str, **_: object) -> None:
        del property_id, code
        raise BusinessRuleUnavailable

    def add_rule(self, property_id: UUID, **_: object) -> None:
        del property_id
        raise BusinessRuleUnavailable


def read_business_rule(
    connection: psycopg.Connection[tuple[object, ...]], code: str, on: date
) -> int:
    """The value of a rule in force on a date; a rule the program needs must be there."""
    row = connection.execute("SELECT app.business_rule_value(%s, %s)", (code, on)).fetchone()
    if row is None or row[0] is None:
        raise BusinessRuleNotFound(code)
    return int(str(row[0]))


def _refusal(exc: psycopg.Error) -> Exception:
    if isinstance(exc, psycopg.errors.UniqueViolation):
        return BusinessRuleConflict("A change for this date already exists")
    if isinstance(exc, psycopg.errors.InvalidParameterValue) and "No business rule" in str(exc):
        return BusinessRuleNotFound("No business rule has this code")
    if isinstance(exc, psycopg.errors.InvalidParameterValue) and "Property" in str(exc):
        return BusinessRuleNotFound("The Property was not found")
    if isinstance(exc, (psycopg.errors.InvalidParameterValue, psycopg.errors.CheckViolation)):
        return BusinessRuleInvalid(str(exc).splitlines()[0])
    return BusinessRuleUnavailable("Business rule persistence is unavailable")


class PostgresBusinessRuleFlow:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def today(self, property_id: UUID) -> date:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    "SELECT timezone(timezone_name, statement_timestamp())::date "
                    "FROM app.properties WHERE id = %s",
                    (property_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise BusinessRuleUnavailable from exc
        if row is None:
            raise BusinessRuleNotFound("The Property was not found")
        return row[0]  # type: ignore[no-any-return]

    def list_rules(self) -> tuple[BusinessRule, ...]:
        try:
            with psycopg.connect(self._database_url) as connection:
                names = connection.execute(
                    "SELECT id, code, name_en, name_kh, value_unit, area, used_by_app "
                    "FROM app.business_rule_names ORDER BY area, code"
                ).fetchall()
                values = connection.execute(
                    "SELECT rule_name_id, value, effective_from, reason, created_at, created_by "
                    "FROM app.business_rules ORDER BY rule_name_id, effective_from"
                ).fetchall()
        except psycopg.Error as exc:
            raise BusinessRuleUnavailable from exc
        history: dict[UUID, list[BusinessRuleValue]] = {}
        for name_id, value, effective_from, reason, created_at, created_by in values:
            history.setdefault(name_id, []).append(
                BusinessRuleValue(value, effective_from, reason, created_at, created_by)
            )
        return tuple(
            BusinessRule(code, name_en, name_kh, unit, area, used, tuple(history.get(rule_id, ())))
            for rule_id, code, name_en, name_kh, unit, area, used in names
        )

    def set_rule(
        self,
        property_id: UUID,
        code: str,
        *,
        value: int,
        effective_from: date,
        reason: str,
        actor_id: str,
    ) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    "SELECT app.set_business_rule(%s, %s, %s, %s, %s, %s, %s)",
                    (property_id, code, value, effective_from, reason, UUID(actor_id), uuid4()),
                )
        except psycopg.Error as exc:
            raise _refusal(exc) from exc

    def add_rule(
        self,
        property_id: UUID,
        *,
        code: str,
        name_en: str,
        name_kh: str,
        value_unit: str,
        area: str,
        value: int,
        effective_from: date,
        reason: str | None,
        actor_id: str,
    ) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    "SELECT app.add_business_rule_name(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        property_id,
                        code,
                        name_en,
                        name_kh,
                        value_unit,
                        area,
                        value,
                        effective_from,
                        reason,
                        UUID(actor_id),
                        uuid4(),
                    ),
                )
        except psycopg.Error as exc:
            if isinstance(exc, psycopg.errors.UniqueViolation):
                raise BusinessRuleConflict("A rule with this code already exists") from exc
            raise _refusal(exc) from exc


class RuleChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    value: int = Field(ge=0, le=100_000_000_000)
    effective_from: date
    reason: Reason

    @field_validator("effective_from", mode="before")
    @classmethod
    def _iso_date(cls, raw: object) -> object:
        return date.fromisoformat(raw) if isinstance(raw, str) else raw


class NewRule(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    code: str
    name_en: Name
    name_kh: Name
    value_unit: ValueUnit
    area: Area
    value: int = Field(ge=0, le=100_000_000_000)
    effective_from: date
    reason: Reason | None = None

    @field_validator("code")
    @classmethod
    def _code(cls, raw: str) -> str:
        if not CODE.fullmatch(raw):
            raise ValueError("code is upper snake case")
        return raw

    @field_validator("effective_from", mode="before")
    @classmethod
    def _iso_date(cls, raw: object) -> object:
        return date.fromisoformat(raw) if isinstance(raw, str) else raw


def _value_body(row: BusinessRuleValue | None) -> dict[str, object] | None:
    if row is None:
        return None
    return {
        "value": row.value,
        "effective_from": row.effective_from.isoformat(),
        "reason": row.reason,
        "created_at": row.created_at.isoformat(),
        "created_by": str(row.created_by) if row.created_by else None,
    }


def _rule_body(rule: BusinessRule, on: date) -> dict[str, object]:
    return {
        "code": rule.code,
        "name_en": rule.name_en,
        "name_kh": rule.name_kh,
        "value_unit": rule.value_unit,
        "area": rule.area,
        "used_by_app": rule.used_by_app,
        "in_force": _value_body(rule.in_force(on)),
        "waiting": _value_body(rule.waiting(on)),
        "history": [_value_body(row) for row in rule.history],
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
    if isinstance(exc, BusinessRuleNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, BusinessRuleConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, BusinessRuleInvalid):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


def create_business_rules_router(
    resolver: ActorResolver, flow: BusinessRuleFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["business-rules"])

    def listing(property_id: UUID, request: Request) -> dict[str, object]:
        try:
            on = flow.today(property_id)
            rules = flow.list_rules()
        except (BusinessRuleNotFound, BusinessRuleUnavailable) as exc:
            raise _http(exc) from exc
        return {
            "data": [_rule_body(rule, on) for rule in rules],
            "meta": {"request_id": request.state.request_id, "today": on.isoformat()},
        }

    @router.get("/properties/{property_id}/business-rules")
    def list_business_rules(
        property_id: UUID, request: Request, response: Response
    ) -> dict[str, object]:
        _require(request, resolver, CONFIGURATION_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        return listing(property_id, request)

    @router.put("/properties/{property_id}/business-rules/{code}")
    def change_business_rule(
        property_id: UUID, code: str, change: RuleChange, request: Request
    ) -> dict[str, object]:
        actor = _require(request, resolver, SETTINGS_MANAGE_CAPABILITY, property_id)
        require_browser_mutation(request, settings)
        if not CODE.fullmatch(code):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            flow.set_rule(
                property_id,
                code,
                value=change.value,
                effective_from=change.effective_from,
                reason=change.reason,
                actor_id=actor.actor_id,
            )
        except (
            BusinessRuleNotFound,
            BusinessRuleConflict,
            BusinessRuleInvalid,
            BusinessRuleUnavailable,
        ) as exc:
            raise _http(exc) from exc
        return listing(property_id, request)

    @router.post("/properties/{property_id}/business-rules", status_code=status.HTTP_201_CREATED)
    def add_business_rule(property_id: UUID, rule: NewRule, request: Request) -> dict[str, object]:
        actor = _require(request, resolver, SETTINGS_MANAGE_CAPABILITY, property_id)
        require_browser_mutation(request, settings)
        try:
            flow.add_rule(
                property_id,
                code=rule.code,
                name_en=rule.name_en,
                name_kh=rule.name_kh,
                value_unit=rule.value_unit,
                area=rule.area,
                value=rule.value,
                effective_from=rule.effective_from,
                reason=rule.reason,
                actor_id=actor.actor_id,
            )
        except (
            BusinessRuleNotFound,
            BusinessRuleConflict,
            BusinessRuleInvalid,
            BusinessRuleUnavailable,
        ) as exc:
            raise _http(exc) from exc
        return listing(property_id, request)

    return router
