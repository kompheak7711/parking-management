"""Vehicle routes (Parking Step 4, owner 2026-10-30).

A vehicle is a record under a Customer: `GET`/`POST /customers/{id}/vehicles`,
`PATCH /vehicles/{id}` and the plate lookup `GET /properties/{id}/vehicles?plate=` that names
every owner with the same plate (the screen warns, nothing is merged). Reading needs
`customers.read`, writing `customers.manage`, as the Customer itself.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from property_rental.browser_security import require_browser_mutation
from property_rental.customer_api import (
    CUSTOMER_MANAGE_CAPABILITY,
    CUSTOMER_READ_CAPABILITY,
    CustomerRecord,
    CustomerResourceFlow,
    CustomerResourceNotFound,
    CustomerResourceUnavailable,
)
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.settings import Settings
from property_rental.vehicle import (
    PLATE_MAX_LENGTH,
    Vehicle,
    VehicleConflictError,
    VehicleCreateCommand,
    VehicleInvalidError,
    VehicleNotFoundError,
    VehicleUnavailableError,
    VehicleUpdateCommand,
    VehicleVersionConflictError,
)

VehicleType = Literal["CAR", "MOTORBIKE", "TUK_TUK", "FOOD_CART"]


class VehicleFlow(Protocol):
    def get(self, vehicle_id: UUID) -> Vehicle: ...

    def of_customer(self, customer_id: UUID) -> tuple[Vehicle, ...]: ...

    def find_by_plate(self, plate_text: str) -> tuple[Vehicle, ...]: ...

    def create(self, command: VehicleCreateCommand, *, actor_id: UUID) -> Vehicle: ...

    def update(self, command: VehicleUpdateCommand, *, actor_id: UUID) -> Vehicle: ...


class UnavailableVehicleFlow:
    def _raise(self) -> None:
        raise VehicleUnavailableError("Vehicle persistence is unavailable")

    def get(self, vehicle_id: UUID) -> Vehicle:
        del vehicle_id
        self._raise()
        raise AssertionError

    def of_customer(self, customer_id: UUID) -> tuple[Vehicle, ...]:
        del customer_id
        self._raise()
        raise AssertionError

    def find_by_plate(self, plate_text: str) -> tuple[Vehicle, ...]:
        del plate_text
        self._raise()
        raise AssertionError

    def create(self, command: VehicleCreateCommand, *, actor_id: UUID) -> Vehicle:
        del command, actor_id
        self._raise()
        raise AssertionError

    def update(self, command: VehicleUpdateCommand, *, actor_id: UUID) -> Vehicle:
        del command, actor_id
        self._raise()
        raise AssertionError


class VehicleCreateSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: UUID
    vehicle_type: VehicleType
    plate_text: Annotated[str, Field(min_length=1, max_length=PLATE_MAX_LENGTH)]


class VehiclePatchSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_type: VehicleType
    plate_text: Annotated[str, Field(min_length=1, max_length=PLATE_MAX_LENGTH)]


def _require_actor(request: Request, resolver: ActorResolver) -> AuthenticatedActor:
    actor = resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return actor


def _can(actor: AuthenticatedActor, property_id: UUID, capability: str) -> bool:
    return is_authorized(
        actor, AuthorizationRequirement(capability=capability, property_id=str(property_id))
    )


def _require_read(actor: AuthenticatedActor, property_id: UUID) -> None:
    if not (
        _can(actor, property_id, CUSTOMER_READ_CAPABILITY)
        or _can(actor, property_id, CUSTOMER_MANAGE_CAPABILITY)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


def _require_manage(actor: AuthenticatedActor, property_id: UUID) -> None:
    if not _can(actor, property_id, CUSTOMER_MANAGE_CAPABILITY):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


def _version(value: str | None) -> int:
    if value is None or not value.startswith('"') or not value.endswith('"'):
        raise HTTPException(status_code=status.HTTP_428_PRECONDITION_REQUIRED)
    try:
        parsed = int(value[1:-1])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST) from exc
    if parsed < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    return parsed


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, (VehicleNotFoundError, CustomerResourceNotFound)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, VehicleVersionConflictError):
        return HTTPException(status_code=status.HTTP_412_PRECONDITION_FAILED)
    if isinstance(exc, VehicleConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT)
    if isinstance(exc, (VehicleInvalidError, ValueError)):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    if isinstance(exc, (VehicleUnavailableError, CustomerResourceUnavailable)):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _body(vehicle: Vehicle) -> dict[str, object]:
    return {
        **asdict(vehicle),
        "vehicle_id": str(vehicle.vehicle_id),
        "customer_id": str(vehicle.customer_id),
    }


def create_vehicle_router(
    resolver: ActorResolver,
    flow: VehicleFlow,
    customers: CustomerResourceFlow,
    settings: Settings,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["vehicles"])

    def customer_of(customer_id: UUID) -> CustomerRecord:
        try:
            return customers.get(customer_id)
        except Exception as exc:
            raise _translate(exc) from exc

    @router.get("/customers/{customer_id}/vehicles")
    def list_vehicles(customer_id: UUID, request: Request) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        record = customer_of(customer_id)
        _require_read(actor, record.property_id)
        try:
            vehicles = flow.of_customer(customer_id)
        except Exception as exc:
            raise _translate(exc) from exc
        return {
            "data": [_body(vehicle) for vehicle in vehicles],
            "meta": {"request_id": request.state.request_id},
        }

    @router.post("/customers/{customer_id}/vehicles", status_code=status.HTTP_201_CREATED)
    def add_vehicle(
        customer_id: UUID,
        source: VehicleCreateSource,
        request: Request,
        response: Response,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        record = customer_of(customer_id)
        _require_manage(actor, record.property_id)
        require_browser_mutation(request, settings)
        if not record.active:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT)
        try:
            vehicle = flow.create(
                VehicleCreateCommand(
                    source.vehicle_id, customer_id, source.vehicle_type, source.plate_text
                ),
                actor_id=UUID(actor.actor_id),
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["ETag"] = f'"{vehicle.version}"'
        return {"data": _body(vehicle), "meta": {"request_id": request.state.request_id}}

    @router.patch("/vehicles/{vehicle_id}")
    def correct_vehicle(
        vehicle_id: UUID,
        source: VehiclePatchSource,
        request: Request,
        response: Response,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            current = flow.get(vehicle_id)
        except Exception as exc:
            raise _translate(exc) from exc
        record = customer_of(current.customer_id)
        _require_manage(actor, record.property_id)
        require_browser_mutation(request, settings)
        try:
            vehicle = flow.update(
                VehicleUpdateCommand(
                    vehicle_id, _version(if_match), source.vehicle_type, source.plate_text
                ),
                actor_id=UUID(actor.actor_id),
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["ETag"] = f'"{vehicle.version}"'
        return {"data": _body(vehicle), "meta": {"request_id": request.state.request_id}}

    @router.get("/properties/{property_id}/vehicles")
    def find_vehicles(
        property_id: UUID,
        request: Request,
        plate: Annotated[str, Query(min_length=1, max_length=PLATE_MAX_LENGTH)],
    ) -> dict[str, object]:
        """Every vehicle whose plate matches without spaces, dashes, dots and case."""
        actor = _require_actor(request, resolver)
        _require_read(actor, property_id)
        try:
            vehicles = flow.find_by_plate(plate)
        except Exception as exc:
            raise _translate(exc) from exc
        return {
            "data": [_body(vehicle) for vehicle in vehicles],
            "meta": {"request_id": request.state.request_id},
        }

    return router
