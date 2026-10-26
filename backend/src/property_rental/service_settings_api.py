"""Services and Service types in Settings (V1-058 R7b-6a; DL-075; DESIGN.md "Rates and services").

- ``GET /properties/{p}/service-settings`` (``settings.manage``, ``configuration.read`` or
  ``leases.draft``): each Service with its rate today, next change, approval periods and the
  Leases holding it now; each Service type with its Services count; ``can_manage``.
- ``POST /properties/{p}/services`` adds a Service with its first monthly rate (from the 1st of a
  month); ``POST /properties/{p}/services/{id}`` changes its names or its type.
- ``POST /properties/{p}/service-types`` adds a type; ``POST .../service-types/{id}`` changes it;
  ``POST .../service-types/{id}/remove`` removes one with no Services.
- ``GET /properties/{p}/cleaning-settings`` (R7b-6d): the move-out cleaning rates with their Unit
  Types, and every Unit Type with its Units count and its rate.
  ``POST /properties/{p}/cleaning-rates`` adds a rate; ``POST .../cleaning-rates/{id}`` changes it
  (a Unit Type ticked here moves from its other rate); ``POST .../cleaning-rates/{id}/remove``
  removes it. A Unit Type that has Units is never left without a rate: that answers 409
  ``UNIT_TYPE_NEEDS_CLEANING_RATE``. Changing or removing a rate already removed answers 404.

Every change needs ``settings.manage`` (the Owner or a user ticked for Settings access), Origin and
CSRF. The client chooses a new record's id, so sending the same form again answers the same record;
a change names the version it was made from and answers 409 when that version is old. A Lease may
hold only one Service of an "Only one per Lease" type: a change that would break that answers 409.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Final, Protocol, TypeVar
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from property_rental.access_control import SETTINGS_MANAGE_CAPABILITY
from property_rental.api_refusals import Refusal, RefusedRequest
from property_rental.browser_security import require_browser_mutation
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.settings import Settings

READ_CAPABILITIES: Final = (SETTINGS_MANAGE_CAPABILITY, "configuration.read", "leases.draft")
BUSINESS_ZONE: Final = ZoneInfo("Asia/Phnom_Penh")
MAX_RATE_USD_CENTS: Final = 9_000_000_000_000_000

T = TypeVar("T")

Name = Annotated[str, Field(min_length=1, max_length=100)]
KhmerName = Annotated[str | None, Field(default=None, max_length=100)]


class ServiceSettingsNotFound(LookupError):
    """The Property, Service or type is not there."""


class ServiceSettingsInvalid(ValueError):
    """The database refused the values (a name, a type not in the list, a start not on the 1st)."""


class ServiceSettingsConflict(RuntimeError):
    """A rule refused the change (a Lease holds two Services of the type; the type has Services; a
    Unit Type with Units would have no cleaning rate)."""

    def __init__(self, refusal: Refusal) -> None:
        super().__init__()
        self.refusal = refusal


SETTINGS_ID_REUSED: Final = Refusal(
    409, "SETTINGS_ID_REUSED", "This record was already saved with other values."
)
SETTINGS_OUT_OF_DATE: Final = Refusal(
    409, "SETTINGS_OUT_OF_DATE", "Someone changed this first. Read the list again."
)
LEASE_HOLDS_TWO_OF_TYPE: Final = Refusal(
    409,
    "LEASE_HOLDS_TWO_OF_TYPE",
    "A Lease holds two Services of this type, so it cannot be Only one per Lease.",
)
SERVICE_TYPE_HAS_SERVICES: Final = Refusal(
    409, "SERVICE_TYPE_HAS_SERVICES", "A Service type with Services cannot be removed."
)
UNIT_TYPE_NEEDS_CLEANING_RATE: Final = Refusal(
    409,
    "UNIT_TYPE_NEEDS_CLEANING_RATE",
    "A Unit Type that has Units needs a cleaning rate. Put it in another rate first.",
)


class ServiceSettingsIdReused(RuntimeError):
    """A new record's id was used before with other values."""


class ServiceSettingsOutOfDate(RuntimeError):
    """The change was made from an older version, or ran into another change at the same moment."""


class ServiceSettingsForbidden(PermissionError):
    """The database refused the actor."""


class ServiceSettingsUnavailable(RuntimeError):
    """The database could not be reached or answered something unreadable."""


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ServiceCreate(StrictBody):
    service_id: UUID
    name_en: Name
    name_km: KhmerName = None
    service_type_id: UUID | None = None
    monthly_rate_usd_cents: Annotated[int, Field(strict=True, ge=1, le=MAX_RATE_USD_CENTS)]
    starts_on: date


class ServiceChange(StrictBody):
    name_en: Name
    name_km: KhmerName = None
    service_type_id: UUID | None = None
    version: Annotated[int, Field(strict=True, ge=1)]


class ServiceTypeCreate(StrictBody):
    service_type_id: UUID
    name_en: Name
    name_km: KhmerName = None
    one_per_lease: Annotated[bool, Field(strict=True)]


class ServiceTypeChange(StrictBody):
    name_en: Name
    name_km: KhmerName = None
    one_per_lease: Annotated[bool, Field(strict=True)]
    version: Annotated[int, Field(strict=True, ge=1)]


class ServiceTypeRemove(StrictBody):
    version: Annotated[int, Field(strict=True, ge=1)]


UnitTypeCode = Annotated[str, Field(pattern=r"^[A-Z0-9][A-Z0-9_]{0,39}$")]


class CleaningRateChange(StrictBody):
    name_en: Name
    name_km: KhmerName = None
    rate_usd_cents: Annotated[int, Field(strict=True, ge=1, le=MAX_RATE_USD_CENTS)]
    unit_types: Annotated[list[UnitTypeCode], Field(max_length=200)]
    version: Annotated[int, Field(strict=True, ge=1)]


class CleaningRateCreate(StrictBody):
    cleaning_rate_id: UUID
    name_en: Name
    name_km: KhmerName = None
    rate_usd_cents: Annotated[int, Field(strict=True, ge=1, le=MAX_RATE_USD_CENTS)]
    unit_types: Annotated[list[UnitTypeCode], Field(max_length=200)]


class ServiceSettingsFlow(Protocol):
    def read(self, property_id: UUID, today: date) -> dict[str, object]: ...

    def add_service(
        self, property_id: UUID, actor_id: UUID, body: ServiceCreate
    ) -> dict[str, object]: ...

    def change_service(
        self, property_id: UUID, actor_id: UUID, service_id: UUID, body: ServiceChange
    ) -> dict[str, object]: ...

    def add_type(
        self, property_id: UUID, actor_id: UUID, body: ServiceTypeCreate
    ) -> dict[str, object]: ...

    def change_type(
        self, property_id: UUID, actor_id: UUID, type_id: UUID, body: ServiceTypeChange
    ) -> dict[str, object]: ...

    def remove_type(
        self, property_id: UUID, actor_id: UUID, type_id: UUID, version: int
    ) -> dict[str, object]: ...

    def read_cleaning(self, property_id: UUID) -> dict[str, object]: ...

    def save_cleaning_rate(
        self,
        property_id: UUID,
        actor_id: UUID,
        rate_id: UUID,
        body: CleaningRateCreate | CleaningRateChange,
    ) -> dict[str, object]: ...

    def remove_cleaning_rate(
        self, property_id: UUID, actor_id: UUID, rate_id: UUID, version: int
    ) -> dict[str, object]: ...


def _refusal(error: psycopg.Error) -> Exception:
    code = error.sqlstate
    if code in {"P0002", "P4501"}:
        return ServiceSettingsNotFound()
    if code in {"22023", "23514", "22001", "22P02", "23503"}:
        return ServiceSettingsInvalid()
    if code == "23505":
        return ServiceSettingsIdReused()
    if code == "P5V01":
        return ServiceSettingsConflict(LEASE_HOLDS_TWO_OF_TYPE)
    if code == "P5V02":
        return ServiceSettingsConflict(SERVICE_TYPE_HAS_SERVICES)
    if code == "P5V03":
        return ServiceSettingsConflict(UNIT_TYPE_NEEDS_CLEANING_RATE)
    if code in {"40P01", "40001"}:
        # Another change ran at the same moment; nothing was saved, so it may be sent again.
        return ServiceSettingsOutOfDate()
    if code in {"42501", "P4506"}:
        return ServiceSettingsForbidden()
    return ServiceSettingsUnavailable()


@dataclass(frozen=True, slots=True)
class PostgresServiceSettingsFlow:
    database_url: str | None

    def _one(self, sql: str, parameters: tuple[object, ...]) -> object:
        if self.database_url is None:
            raise ServiceSettingsUnavailable
        try:
            with psycopg.connect(self.database_url) as connection:
                row = connection.execute(sql, parameters).fetchone()
        except psycopg.Error as exc:
            raise _refusal(exc) from exc
        return None if row is None else row[0]

    @staticmethod
    def _record(value: object) -> dict[str, object]:
        if value is None:
            raise ServiceSettingsOutOfDate
        if not isinstance(value, dict):
            raise ServiceSettingsUnavailable
        return value

    def read(self, property_id: UUID, today: date) -> dict[str, object]:
        value = self._one("SELECT app.service_settings_read(%s, %s)", (property_id, today))
        if value is None:
            raise ServiceSettingsNotFound
        return self._record(value)

    def add_service(
        self, property_id: UUID, actor_id: UUID, body: ServiceCreate
    ) -> dict[str, object]:
        return self._record(
            self._one(
                "SELECT app.add_property_service(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    property_id,
                    actor_id,
                    body.service_id,
                    body.name_en,
                    body.name_km or None,
                    body.service_type_id,
                    body.monthly_rate_usd_cents,
                    body.starts_on,
                    SETTINGS_MANAGE_CAPABILITY,
                ),
            )
        )

    def change_service(
        self, property_id: UUID, actor_id: UUID, service_id: UUID, body: ServiceChange
    ) -> dict[str, object]:
        return self._record(
            self._one(
                "SELECT app.update_property_service(%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    property_id,
                    actor_id,
                    service_id,
                    body.name_en,
                    body.name_km or None,
                    body.service_type_id,
                    body.version,
                    SETTINGS_MANAGE_CAPABILITY,
                ),
            )
        )

    def add_type(
        self, property_id: UUID, actor_id: UUID, body: ServiceTypeCreate
    ) -> dict[str, object]:
        return self._record(
            self._one(
                "SELECT app.add_service_type(%s, %s, %s, %s, %s, %s, %s)",
                (
                    property_id,
                    actor_id,
                    body.service_type_id,
                    body.name_en,
                    body.name_km or None,
                    body.one_per_lease,
                    SETTINGS_MANAGE_CAPABILITY,
                ),
            )
        )

    def change_type(
        self, property_id: UUID, actor_id: UUID, type_id: UUID, body: ServiceTypeChange
    ) -> dict[str, object]:
        return self._record(
            self._one(
                "SELECT app.update_service_type(%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    property_id,
                    actor_id,
                    type_id,
                    body.name_en,
                    body.name_km or None,
                    body.one_per_lease,
                    body.version,
                    SETTINGS_MANAGE_CAPABILITY,
                ),
            )
        )

    def remove_type(
        self, property_id: UUID, actor_id: UUID, type_id: UUID, version: int
    ) -> dict[str, object]:
        return self._record(
            self._one(
                "SELECT app.remove_service_type(%s, %s, %s, %s, %s)",
                (property_id, actor_id, type_id, version, SETTINGS_MANAGE_CAPABILITY),
            )
        )

    def read_cleaning(self, property_id: UUID) -> dict[str, object]:
        value = self._one("SELECT app.cleaning_settings_read(%s)", (property_id,))
        if value is None:
            raise ServiceSettingsNotFound
        return self._record(value)

    def save_cleaning_rate(
        self,
        property_id: UUID,
        actor_id: UUID,
        rate_id: UUID,
        body: CleaningRateCreate | CleaningRateChange,
    ) -> dict[str, object]:
        return self._record(
            self._one(
                "SELECT app.save_cleaning_rate(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    property_id,
                    actor_id,
                    rate_id,
                    body.name_en,
                    body.name_km or None,
                    body.rate_usd_cents,
                    body.unit_types,
                    body.version if isinstance(body, CleaningRateChange) else None,
                    SETTINGS_MANAGE_CAPABILITY,
                ),
            )
        )

    def remove_cleaning_rate(
        self, property_id: UUID, actor_id: UUID, rate_id: UUID, version: int
    ) -> dict[str, object]:
        return self._record(
            self._one(
                "SELECT app.remove_cleaning_rate(%s, %s, %s, %s, %s)",
                (property_id, actor_id, rate_id, version, SETTINGS_MANAGE_CAPABILITY),
            )
        )


def _allowed(actor: AuthenticatedActor, capability: str, property_id: UUID) -> bool:
    return is_authorized(
        actor, AuthorizationRequirement(capability=capability, property_id=str(property_id))
    )


def _invoke(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except ServiceSettingsNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except ServiceSettingsInvalid as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    except ServiceSettingsIdReused as exc:
        raise RefusedRequest(SETTINGS_ID_REUSED) from exc
    except ServiceSettingsOutOfDate as exc:
        raise RefusedRequest(SETTINGS_OUT_OF_DATE) from exc
    except ServiceSettingsConflict as exc:
        raise RefusedRequest(exc.refusal) from exc
    except ServiceSettingsForbidden as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from exc
    except ServiceSettingsUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc


def business_today() -> date:
    return datetime.now(BUSINESS_ZONE).date()


def create_service_settings_router(
    actor_resolver: ActorResolver,
    flow: ServiceSettingsFlow,
    settings: Settings,
    today: Callable[[], date] = business_today,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["settings"])

    def actor_of(request: Request) -> AuthenticatedActor:
        actor = actor_resolver(request)
        if actor is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return actor

    def manager(request: Request, property_id: UUID) -> UUID:
        actor = actor_of(request)
        if not _allowed(actor, SETTINGS_MANAGE_CAPABILITY, property_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        require_browser_mutation(request, settings)
        return UUID(actor.actor_id)

    def answer(request: Request, data: object) -> dict[str, object]:
        return {"data": data, "meta": {"request_id": request.state.request_id}}

    @router.get("/properties/{property_id}/service-settings")
    def read(property_id: UUID, request: Request) -> dict[str, object]:
        if set(request.query_params):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        actor = actor_of(request)
        if not any(_allowed(actor, item, property_id) for item in READ_CAPABILITIES):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        day = today()
        data = _invoke(lambda: flow.read(property_id, day))
        return answer(
            request,
            {
                **data,
                "today": day.isoformat(),
                "can_manage": _allowed(actor, SETTINGS_MANAGE_CAPABILITY, property_id),
            },
        )

    @router.post("/properties/{property_id}/services", status_code=status.HTTP_201_CREATED)
    def add_service(property_id: UUID, body: ServiceCreate, request: Request) -> dict[str, object]:
        actor_id = manager(request, property_id)
        if body.starts_on.day != 1:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        return answer(request, _invoke(lambda: flow.add_service(property_id, actor_id, body)))

    @router.post("/properties/{property_id}/services/{service_id}")
    def change_service(
        property_id: UUID, service_id: UUID, body: ServiceChange, request: Request
    ) -> dict[str, object]:
        actor_id = manager(request, property_id)
        return answer(
            request,
            _invoke(lambda: flow.change_service(property_id, actor_id, service_id, body)),
        )

    @router.post("/properties/{property_id}/service-types", status_code=status.HTTP_201_CREATED)
    def add_type(property_id: UUID, body: ServiceTypeCreate, request: Request) -> dict[str, object]:
        actor_id = manager(request, property_id)
        return answer(request, _invoke(lambda: flow.add_type(property_id, actor_id, body)))

    @router.post("/properties/{property_id}/service-types/{type_id}")
    def change_type(
        property_id: UUID, type_id: UUID, body: ServiceTypeChange, request: Request
    ) -> dict[str, object]:
        actor_id = manager(request, property_id)
        return answer(
            request, _invoke(lambda: flow.change_type(property_id, actor_id, type_id, body))
        )

    @router.post("/properties/{property_id}/service-types/{type_id}/remove")
    def remove_type(
        property_id: UUID, type_id: UUID, body: ServiceTypeRemove, request: Request
    ) -> dict[str, object]:
        actor_id = manager(request, property_id)
        return answer(
            request,
            _invoke(lambda: flow.remove_type(property_id, actor_id, type_id, body.version)),
        )

    @router.get("/properties/{property_id}/cleaning-settings")
    def read_cleaning(property_id: UUID, request: Request) -> dict[str, object]:
        if set(request.query_params):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        actor = actor_of(request)
        if not any(_allowed(actor, item, property_id) for item in READ_CAPABILITIES):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        data = _invoke(lambda: flow.read_cleaning(property_id))
        return answer(
            request,
            {**data, "can_manage": _allowed(actor, SETTINGS_MANAGE_CAPABILITY, property_id)},
        )

    @router.post("/properties/{property_id}/cleaning-rates", status_code=status.HTTP_201_CREATED)
    def add_cleaning_rate(
        property_id: UUID, body: CleaningRateCreate, request: Request
    ) -> dict[str, object]:
        actor_id = manager(request, property_id)
        return answer(
            request,
            _invoke(
                lambda: flow.save_cleaning_rate(property_id, actor_id, body.cleaning_rate_id, body)
            ),
        )

    @router.post("/properties/{property_id}/cleaning-rates/{rate_id}")
    def change_cleaning_rate(
        property_id: UUID, rate_id: UUID, body: CleaningRateChange, request: Request
    ) -> dict[str, object]:
        actor_id = manager(request, property_id)
        return answer(
            request, _invoke(lambda: flow.save_cleaning_rate(property_id, actor_id, rate_id, body))
        )

    @router.post("/properties/{property_id}/cleaning-rates/{rate_id}/remove")
    def remove_cleaning_rate(
        property_id: UUID, rate_id: UUID, body: ServiceTypeRemove, request: Request
    ) -> dict[str, object]:
        actor_id = manager(request, property_id)
        return answer(
            request,
            _invoke(
                lambda: flow.remove_cleaning_rate(property_id, actor_id, rate_id, body.version)
            ),
        )

    return router
