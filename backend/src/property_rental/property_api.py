"""Authorized HTTP and persistence boundary for the single Property resource."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from property_rental.access_control import (
    PROPERTY_READ_CAPABILITY,
    SETTINGS_MANAGE_CAPABILITY,
)
from property_rental.browser_security import require_browser_mutation
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.property import PropertyConfiguration
from property_rental.settings import Settings

PROPERTY_MANAGE_CAPABILITY = "property.manage"
# Login sub-slice L5 (owner answer (a) to Q-2026-10-21-151): the Property update and its
# configuration are Settings; reading the Property needs `property.read` (Q-2026-10-21-160).
PROPERTY_SETTINGS_CAPABILITY = SETTINGS_MANAGE_CAPABILITY
INITIAL_PROPERTY_VERSION = 1


class PropertyResourceNotFound(LookupError):
    """Raised when the requested Property is not this deployment's Property."""


class PropertyResourceUnavailable(RuntimeError):
    """Raised when Property configuration persistence cannot be reached."""


class PropertyResourceInvalid(ValueError):
    """Raised when a requested Property change violates configuration rules."""


class PropertyVersionConflict(RuntimeError):
    """Raised when a Property mutation does not target the current version."""

    def __init__(self, current_version: int) -> None:
        super().__init__("the Property version precondition was not met")
        self.current_version = current_version


@dataclass(frozen=True, slots=True)
class PaymentMethodConfiguration:
    """One configured Payment Method, retained when it is no longer accepted."""

    method_id: UUID
    code: str
    display_name: str
    accepted: bool

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.display_name.strip():
            raise ValueError("Payment Method code and display name must be nonblank")


@dataclass(frozen=True, slots=True)
class PropertyResource:
    """Versioned representation of the configured Property."""

    property_id: UUID
    name: str
    address_text: str | None
    timezone_name: str
    payment_methods: tuple[PaymentMethodConfiguration, ...] = ()
    version: int = INITIAL_PROPERTY_VERSION

    def __post_init__(self) -> None:
        PropertyConfiguration(
            property_id=self.property_id,
            name=self.name,
            address_text=self.address_text,
            timezone_name=self.timezone_name,
        )
        if self.version < INITIAL_PROPERTY_VERSION:
            raise ValueError("version must be positive")


class PropertyResourceFlow(Protocol):
    """Application operations needed by the Property HTTP resource."""

    def get(self, property_id: UUID) -> PropertyResource:
        """Return the configured Property matching the requested identity."""
        ...

    def patch_source(
        self,
        property_id: UUID,
        *,
        name: str,
        address_text: str | None,
        expected_version: int,
        actor_id: str,
    ) -> PropertyResource:
        """Apply authorized, version-guarded Property source changes."""
        ...

    def patch_configuration(
        self,
        property_id: UUID,
        *,
        payment_methods: tuple[PaymentMethodConfiguration, ...],
        expected_version: int,
        actor_id: str,
    ) -> PropertyResource:
        """Replace the accepted Payment Method configuration."""
        ...


@dataclass(frozen=True, slots=True)
class UnavailablePropertyResourceFlow:
    """Fail closed when Property persistence has not been configured."""

    def get(self, property_id: UUID) -> PropertyResource:
        del property_id
        raise PropertyResourceUnavailable("Property persistence is unavailable")

    def patch_source(
        self,
        property_id: UUID,
        *,
        name: str,
        address_text: str | None,
        expected_version: int,
        actor_id: str,
    ) -> PropertyResource:
        del property_id, name, address_text, expected_version, actor_id
        raise PropertyResourceUnavailable("Property persistence is unavailable")

    def patch_configuration(
        self,
        property_id: UUID,
        *,
        payment_methods: tuple[PaymentMethodConfiguration, ...],
        expected_version: int,
        actor_id: str,
    ) -> PropertyResource:
        del property_id, payment_methods, expected_version, actor_id
        raise PropertyResourceUnavailable("Property persistence is unavailable")


@dataclass(frozen=True, slots=True)
class PostgresPropertyResourceFlow:
    """Read the authoritative one-row Property configuration from PostgreSQL."""

    database_url: str

    @staticmethod
    def _resource(
        row: tuple[object, ...],
        methods: list[tuple[object, ...]],
    ) -> PropertyResource:
        return PropertyResource(
            property_id=UUID(str(row[0])),
            name=str(row[1]),
            address_text=None if row[2] is None else str(row[2]),
            timezone_name=str(row[3]),
            version=int(str(row[4])),
            payment_methods=tuple(
                PaymentMethodConfiguration(
                    method_id=UUID(str(method[0])),
                    code=str(method[1]),
                    display_name=str(method[2]),
                    accepted=bool(method[3]),
                )
                for method in methods
            ),
        )

    @staticmethod
    def _methods(connection: psycopg.Connection[tuple[object, ...]]) -> list[tuple[object, ...]]:
        return connection.execute(
            """
            SELECT id, code, display_name, accepted
            FROM app.payment_methods
            ORDER BY code
            """
        ).fetchall()

    def get(self, property_id: UUID) -> PropertyResource:
        try:
            with psycopg.connect(self.database_url) as connection:
                rows = connection.execute(
                    """
                    SELECT
                        configuration.property_id,
                        configuration.name,
                        configuration.address_text,
                        configuration.timezone_name,
                        configuration.version,
                        method.id,
                        method.code,
                        method.display_name,
                        method.accepted
                    FROM app.property_configuration AS configuration
                    LEFT JOIN app.payment_methods AS method ON true
                    WHERE configuration.property_id = %s
                    ORDER BY method.code
                    """,
                    (property_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise PropertyResourceUnavailable("Property persistence is unavailable") from exc

        if not rows:
            raise PropertyResourceNotFound("Property was not found")
        row = rows[0][:5]
        methods: list[tuple[object, ...]] = [
            (item[5], item[6], item[7], item[8]) for item in rows if item[5] is not None
        ]
        return self._resource(row, methods)

    def patch_source(
        self,
        property_id: UUID,
        *,
        name: str,
        address_text: str | None,
        expected_version: int,
        actor_id: str,
    ) -> PropertyResource:
        try:
            PropertyResource(
                property_id=property_id,
                name=name,
                address_text=address_text,
                timezone_name="Asia/Phnom_Penh",
                version=expected_version + 1,
            )
        except ValueError as exc:
            raise PropertyResourceInvalid("Property source fields are invalid") from exc
        try:
            with psycopg.connect(self.database_url) as connection:
                row = connection.execute(
                    """
                    SELECT
                        property_id,
                        name,
                        address_text,
                        timezone_name,
                        version
                    FROM app.update_property_source(%s, %s, %s, %s, %s)
                    """,
                    (property_id, name, address_text or "", expected_version, actor_id),
                ).fetchone()
                if row is None:
                    current = connection.execute(
                        """
                        SELECT version
                        FROM app.property_configuration
                        WHERE property_id = %s
                        """,
                        (property_id,),
                    ).fetchone()
                    methods: list[tuple[object, ...]] = []
                else:
                    methods = self._methods(connection)
        except psycopg.Error as exc:
            raise PropertyResourceUnavailable("Property persistence is unavailable") from exc
        if row is None:
            if current is None:
                raise PropertyResourceNotFound("Property was not found")
            raise PropertyVersionConflict(int(current[0]))
        return self._resource(row, methods)

    def patch_configuration(
        self,
        property_id: UUID,
        *,
        payment_methods: tuple[PaymentMethodConfiguration, ...],
        expected_version: int,
        actor_id: str,
    ) -> PropertyResource:
        payload = [
            {
                "id": str(method.method_id),
                "code": method.code.strip(),
                "display_name": method.display_name.strip(),
                "accepted": method.accepted,
            }
            for method in payment_methods
        ]
        try:
            with psycopg.connect(self.database_url) as connection:
                row = connection.execute(
                    """
                    SELECT
                        property_id,
                        name,
                        address_text,
                        timezone_name,
                        version
                    FROM app.replace_property_payment_methods(%s, %s, %s, %s)
                    """,
                    (property_id, Jsonb(payload), expected_version, actor_id),
                ).fetchone()
                if row is None:
                    current = connection.execute(
                        """
                        SELECT version
                        FROM app.property_configuration
                        WHERE property_id = %s
                        """,
                        (property_id,),
                    ).fetchone()
                    methods = []
                else:
                    methods = self._methods(connection)
        except psycopg.errors.InvalidParameterValue as exc:
            raise PropertyResourceInvalid("Payment Method configuration is invalid") from exc
        except psycopg.Error as exc:
            raise PropertyResourceUnavailable("Property persistence is unavailable") from exc
        if row is None:
            if current is None:
                raise PropertyResourceNotFound("Property was not found")
            raise PropertyVersionConflict(int(current[0]))
        return self._resource(row, methods)


class PropertyPatch(BaseModel):
    """Documented mutable fields accepted by the Property resource."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    address_text: str | None = Field(default=None, max_length=2000)


class PaymentMethodPatch(BaseModel):
    """One complete configured Payment Method value."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=255)
    accepted: bool


class PropertyConfigurationPatch(BaseModel):
    """Complete accepted Payment Method configuration replacement."""

    model_config = ConfigDict(extra="forbid")

    timezone_name: str = Field(pattern="^Asia/Phnom_Penh$")
    payment_methods: list[PaymentMethodPatch] = Field(max_length=100)


def _require_actor(request: Request, actor_resolver: ActorResolver) -> AuthenticatedActor:
    actor = actor_resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return actor


def _allowed(actor: AuthenticatedActor, capability: str, property_id: UUID) -> bool:
    return is_authorized(
        actor,
        AuthorizationRequirement(capability=capability, property_id=str(property_id)),
    )


def _require_capability(
    actor: AuthenticatedActor,
    property_id: UUID,
    *capabilities: str,
) -> None:
    """403 unless the actor holds one of `capabilities` for this Property."""
    if not any(_allowed(actor, capability, property_id) for capability in capabilities):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


def _expected_version(if_match: str | None, current_version: int) -> int:
    if if_match is None:
        raise PropertyVersionConflict(current_version)
    candidate = if_match.strip()
    if candidate.startswith("W/"):
        raise PropertyVersionConflict(current_version)
    if len(candidate) >= 2 and candidate[0] == candidate[-1] == '"':
        candidate = candidate[1:-1]
    try:
        version = int(candidate)
    except ValueError as exc:
        raise PropertyVersionConflict(current_version) from exc
    if version != current_version:
        raise PropertyVersionConflict(current_version)
    return version


def _resource_body(resource: PropertyResource, request: Request) -> dict[str, object]:
    return {
        "data": {
            "property_id": str(resource.property_id),
            "name": resource.name,
            "address_text": resource.address_text,
            "timezone_name": resource.timezone_name,
            "version": resource.version,
            "configuration": {
                "timezone_name": resource.timezone_name,
                "accepted_payment_methods": [
                    {
                        "code": method.code,
                        "display_name": method.display_name,
                    }
                    for method in resource.payment_methods
                    if method.accepted
                ],
            },
        },
        "meta": {"request_id": request.state.request_id},
    }


def _configuration_body(
    resource: PropertyResource,
    request: Request,
) -> dict[str, object]:
    return {
        "data": {
            "property_id": str(resource.property_id),
            "timezone_name": resource.timezone_name,
            "payment_methods": [
                {
                    "code": method.code,
                    "display_name": method.display_name,
                    "accepted": method.accepted,
                }
                for method in resource.payment_methods
            ],
            "version": resource.version,
        },
        "meta": {"request_id": request.state.request_id},
    }


def _get_resource(flow: PropertyResourceFlow, property_id: UUID) -> PropertyResource:
    try:
        return flow.get(property_id)
    except PropertyResourceNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except PropertyResourceUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc


def _patch_resource(
    flow: PropertyResourceFlow,
    property_id: UUID,
    patch: PropertyPatch,
    if_match: str | None,
    actor: AuthenticatedActor,
) -> PropertyResource:
    current = _get_resource(flow, property_id)
    expected_version = _expected_version(if_match, current.version)
    try:
        return flow.patch_source(
            property_id,
            name=patch.name,
            address_text=patch.address_text,
            expected_version=expected_version,
            actor_id=actor.actor_id,
        )
    except PropertyResourceNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except PropertyResourceInvalid as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    except PropertyResourceUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc


def _patch_configuration(
    flow: PropertyResourceFlow,
    property_id: UUID,
    patch: PropertyConfigurationPatch,
    if_match: str | None,
    actor: AuthenticatedActor,
) -> PropertyResource:
    current = _get_resource(flow, property_id)
    expected_version = _expected_version(if_match, current.version)
    current_ids = {method.code: method.method_id for method in current.payment_methods}
    try:
        methods = tuple(
            PaymentMethodConfiguration(
                method_id=current_ids.get(method.code.strip(), uuid4()),
                code=method.code.strip(),
                display_name=method.display_name.strip(),
                accepted=method.accepted,
            )
            for method in patch.payment_methods
        )
        if len({method.code for method in methods}) != len(methods):
            raise ValueError("Payment Method codes must be unique")
        return flow.patch_configuration(
            property_id,
            payment_methods=methods,
            expected_version=expected_version,
            actor_id=actor.actor_id,
        )
    except PropertyResourceNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except (PropertyResourceInvalid, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    except PropertyResourceUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc


def create_property_router(
    actor_resolver: ActorResolver,
    flow: PropertyResourceFlow,
    settings: Settings,
) -> APIRouter:
    """Create authenticated Property and Property-configuration routes."""
    router = APIRouter(prefix="/properties", tags=["properties"])

    @router.get("/{property_id}")
    def get_property(
        property_id: UUID,
        request: Request,
        response: Response,
    ) -> dict[str, object]:
        actor = _require_actor(request, actor_resolver)
        _require_capability(actor, property_id, PROPERTY_READ_CAPABILITY)
        resource = _get_resource(flow, property_id)
        response.headers["ETag"] = f'"{resource.version}"'
        return _resource_body(resource, request)

    @router.patch("/{property_id}")
    def patch_property(
        property_id: UUID,
        patch: PropertyPatch,
        request: Request,
        response: Response,
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, object]:
        actor = _require_actor(request, actor_resolver)
        _require_capability(actor, property_id, PROPERTY_SETTINGS_CAPABILITY)
        require_browser_mutation(request, settings)
        resource = _patch_resource(flow, property_id, patch, if_match, actor)
        response.headers["ETag"] = f'"{resource.version}"'
        return _resource_body(resource, request)

    @router.get("/{property_id}/configuration")
    def get_property_configuration(
        property_id: UUID,
        request: Request,
        response: Response,
    ) -> dict[str, object]:
        actor = _require_actor(request, actor_resolver)
        # Login sub-slice L5 (Q-2026-10-24-186): the person who changes it, or a Property
        # manager as before, may read it.
        _require_capability(
            actor, property_id, PROPERTY_SETTINGS_CAPABILITY, PROPERTY_MANAGE_CAPABILITY
        )
        resource = _get_resource(flow, property_id)
        response.headers["ETag"] = f'"{resource.version}"'
        return _configuration_body(resource, request)

    @router.patch("/{property_id}/configuration")
    def patch_property_configuration(
        property_id: UUID,
        patch: PropertyConfigurationPatch,
        request: Request,
        response: Response,
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, object]:
        actor = _require_actor(request, actor_resolver)
        _require_capability(actor, property_id, PROPERTY_SETTINGS_CAPABILITY)
        require_browser_mutation(request, settings)
        resource = _patch_configuration(flow, property_id, patch, if_match, actor)
        response.headers["ETag"] = f'"{resource.version}"'
        return _configuration_body(resource, request)

    return router
