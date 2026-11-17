"""Joint Inspection at move-in and move-out (DL-201, DL-243).

`GET .../joint-inspections` lists the latest Joint Inspections (or one Lease's with `?lease_id=`)
and `GET .../joint-inspections/{id}` reads one with its lines, keys, meters, photos and
signatures (`units.read`). `POST .../joint-inspections` starts a move-in or move-out inspection
(`joint_inspections.record`; with `replaces_id` and a reason it starts a replacement of a finished
one, `joint_inspections.replace`). `POST .../joint-inspections/{id}/save` saves what staff marked
at the version in If-Match. `POST .../joint-inspections/{id}/files?role=...` keeps one photo,
meter photo or finger signature (the raw image is the body: JPG, PNG or WEBP, at most 10 MB) in
the inspection files folder; a signature is for the version in If-Match.
`POST .../joint-inspection-files/{file_id}/remove` takes a photo off a Draft and
`GET .../joint-inspection-files/{file_id}` sends one file back. `POST .../{id}/finish` makes it
Done: a Problem report for each new Broken or Missing line and, at move-out, the damage findings
the tenant caused on the Move-out page.

The database functions check the rights again; a Done inspection never changes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated, Literal, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.routing import APIRoute
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from starlette.types import Message, Receive, Scope, Send

from property_rental.access_control import UNITS_READ_CAPABILITY
from property_rental.browser_security import require_browser_mutation
from property_rental.hr_api import HrFiles
from property_rental.identity import ActorResolver
from property_rental.products_api import (
    REFUSED,
    Id,
    Json,
    ProductNotFound,
    ProductUnavailable,
    _expected_version,
    _http,
    _refusal,
    _require,
)
from property_rental.settings import Settings

JOINT_INSPECTIONS_READ = UNITS_READ_CAPABILITY
JOINT_INSPECTIONS_RECORD = "joint_inspections.record"
JOINT_INSPECTIONS_REPLACE = "joint_inspections.replace"
MAX_FILE_BYTES = 10 * 1024 * 1024
FILE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
Role = Literal["PHOTO", "ELECTRICITY", "WATER", "TENANT_SIGNATURE", "STAFF_SIGNATURE"]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Count = Annotated[int, Field(ge=0, le=99)]
Reading = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,13}(\.[0-9]{1,6})?$")]


class InspectionFiles(HrFiles):
    """The photos and signatures, under their own folder (APP_INSPECTION_FILES_DIRECTORY)."""

    def _path(self, key: str) -> Path:
        if self._root is None:
            raise ProductUnavailable("The inspection files folder is not set up")
        return super()._path(key)


class InspectionRequestRoute(APIRoute):
    """Bound incoming bytes before FastAPI buffers a body (a photo is at most 10 MB)."""

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        received = 0

        async def bounded_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_FILE_BYTES:
                    raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE)
            return message

        await super().handle(scope, bounded_receive, send)


class JointInspectionFlow(Protocol):
    def inspections(
        self, property_id: UUID, lease_id: UUID | None, *, actor_id: str
    ) -> list[Json]: ...

    def inspection(self, property_id: UUID, inspection_id: UUID, *, actor_id: str) -> Json: ...

    def start(self, property_id: UUID, start: Json, *, actor_id: str) -> UUID: ...

    def save(
        self, property_id: UUID, inspection_id: UUID, version: int, changes: Json, *, actor_id: str
    ) -> None: ...

    def add_file(
        self, property_id: UUID, inspection_id: UUID, version: int, file: Json, *, actor_id: str
    ) -> UUID: ...

    def remove_file(self, property_id: UUID, file_id: UUID, *, actor_id: str) -> None: ...

    def file(self, property_id: UUID, file_id: UUID, *, actor_id: str) -> Json: ...

    def finish(
        self, property_id: UUID, inspection_id: UUID, version: int, *, actor_id: str
    ) -> Json: ...


class UnavailableJointInspectionFlow:
    def inspections(self, property_id: UUID, lease_id: UUID | None, **_: object) -> list[Json]:
        raise ProductUnavailable

    def inspection(self, property_id: UUID, inspection_id: UUID, **_: object) -> Json:
        raise ProductUnavailable

    def start(self, property_id: UUID, start: Json, **_: object) -> UUID:
        raise ProductUnavailable

    def save(
        self, property_id: UUID, inspection_id: UUID, version: int, changes: Json, **_: object
    ) -> None:
        raise ProductUnavailable

    def add_file(
        self, property_id: UUID, inspection_id: UUID, version: int, file: Json, **_: object
    ) -> UUID:
        raise ProductUnavailable

    def remove_file(self, property_id: UUID, file_id: UUID, **_: object) -> None:
        raise ProductUnavailable

    def file(self, property_id: UUID, file_id: UUID, **_: object) -> Json:
        raise ProductUnavailable

    def finish(self, property_id: UUID, inspection_id: UUID, version: int, **_: object) -> Json:
        raise ProductUnavailable


def _json(value: object) -> Json:
    if not isinstance(value, dict):
        raise ProductUnavailable("Joint Inspection persistence is unavailable")
    return {str(key): item for key, item in value.items()}


class PostgresJointInspectionFlow:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def _one(self, url: str | None, query: str, parameters: tuple[object, ...]) -> object:
        if url is None:
            raise ProductUnavailable("Joint Inspection persistence is unavailable")
        try:
            with psycopg.connect(url) as connection:
                row = connection.execute(query, parameters).fetchone()
        except psycopg.Error as exc:
            raise _refusal(exc) from exc
        return None if row is None else row[0]

    def inspections(self, property_id: UUID, lease_id: UUID | None, *, actor_id: str) -> list[Json]:
        found = self._one(
            self._database_url,
            "SELECT app.joint_inspections_read(%s, %s, %s)",
            (property_id, UUID(actor_id), lease_id),
        )
        if not isinstance(found, list):
            raise ProductUnavailable("Joint Inspection persistence is unavailable")
        return [_json(item) for item in found]

    def inspection(self, property_id: UUID, inspection_id: UUID, *, actor_id: str) -> Json:
        return _json(
            self._one(
                self._database_url,
                "SELECT app.joint_inspection_read(%s, %s, %s)",
                (property_id, inspection_id, UUID(actor_id)),
            )
        )

    def start(self, property_id: UUID, start: Json, *, actor_id: str) -> UUID:
        made = self._one(
            self._database_url,
            "SELECT app.joint_inspection_start(%s, %s, %s, %s, %s, %s, %s)",
            (
                property_id,
                start["lease_id"],
                start["kind"],
                start.get("replaces_id"),
                start.get("reason"),
                UUID(actor_id),
                uuid4(),
            ),
        )
        return UUID(str(made))

    def save(
        self, property_id: UUID, inspection_id: UUID, version: int, changes: Json, *, actor_id: str
    ) -> None:
        self._one(
            self._database_url,
            "SELECT app.joint_inspection_save(%s, %s, %s, %s, %s)",
            (property_id, inspection_id, version, Jsonb(changes), UUID(actor_id)),
        )

    def add_file(
        self, property_id: UUID, inspection_id: UUID, version: int, file: Json, *, actor_id: str
    ) -> UUID:
        made = self._one(
            self._database_url,
            "SELECT app.joint_inspection_add_file(%s, %s, %s, %s, %s)",
            (property_id, inspection_id, version, Jsonb(file), UUID(actor_id)),
        )
        return UUID(str(made))

    def remove_file(self, property_id: UUID, file_id: UUID, *, actor_id: str) -> None:
        self._one(
            self._database_url,
            "SELECT app.joint_inspection_remove_file(%s, %s, %s)",
            (property_id, file_id, UUID(actor_id)),
        )

    def file(self, property_id: UUID, file_id: UUID, *, actor_id: str) -> Json:
        return _json(
            self._one(
                self._database_url,
                "SELECT app.joint_inspection_file(%s, %s, %s)",
                (property_id, file_id, UUID(actor_id)),
            )
        )

    def finish(
        self, property_id: UUID, inspection_id: UUID, version: int, *, actor_id: str
    ) -> Json:
        return _json(
            self._one(
                self._database_url,
                "SELECT app.joint_inspection_finish(%s, %s, %s, %s, %s)",
                (property_id, inspection_id, version, UUID(actor_id), uuid4()),
            )
        )


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class NewJointInspection(_Body):
    lease_id: Id
    kind: Literal["MOVE_IN", "MOVE_OUT"]
    replaces_id: Id | None = None
    reason: Reason | None = None


class LineChange(_Body):
    line_id: Id
    result: Literal["GOOD", "BROKEN", "MISSING"] | None = None
    note: Note | None = None
    tenant_caused: bool | None = None
    pet_caused: bool | None = None


class Keys(_Body):
    door_keys: Count | None = None
    key_cards: Count | None = None
    mailbox_keys: Count | None = None
    other_keys: Count | None = None
    other_keys_note: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None
    ) = None


class MeterChange(_Body):
    utility_type: Literal["ELECTRICITY", "WATER"]
    reading: Reading | None


class InspectionChanges(_Body):
    lines: Annotated[list[LineChange], Field(max_length=500)] | None = None
    keys: Keys | None = None
    meters: Annotated[list[MeterChange], Field(max_length=2)] | None = None


def _changes(changes: InspectionChanges) -> Json:
    """Only what is sent changes; an empty note clears it."""
    body: Json = {}
    if changes.lines is not None:
        lines: list[Json] = []
        for line in changes.lines:
            entry: Json = {"line_id": str(line.line_id)}
            for name in line.model_fields_set - {"line_id"}:
                value = getattr(line, name)
                entry[name] = None if name == "note" and value == "" else value
            lines.append(entry)
        body["lines"] = lines
    if changes.keys is not None:
        keys: Json = {}
        for name in changes.keys.model_fields_set:
            value = getattr(changes.keys, name)
            keys[name] = None if name == "other_keys_note" and value == "" else value
        body["keys"] = keys
    if changes.meters is not None:
        body["meters"] = [meter.model_dump() for meter in changes.meters]
    return body


def create_joint_inspections_router(
    resolver: ActorResolver, flow: JointInspectionFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/properties/{property_id}",
        tags=["joint inspections"],
        route_class=InspectionRequestRoute,
    )
    files = InspectionFiles(settings.inspection_files_directory)

    def envelope(request: Request, data: object) -> Json:
        return {"data": data, "meta": {"request_id": request.state.request_id}}

    def one(property_id: UUID, inspection_id: UUID, actor_id: str, request: Request) -> Json:
        try:
            return envelope(request, flow.inspection(property_id, inspection_id, actor_id=actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.get("/joint-inspections")
    def list_joint_inspections(
        property_id: UUID, request: Request, response: Response, lease_id: UUID | None = None
    ) -> Json:
        actor = _require(request, resolver, JOINT_INSPECTIONS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(
                request, flow.inspections(property_id, lease_id, actor_id=actor.actor_id)
            )
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.get("/joint-inspections/{inspection_id}")
    def read_joint_inspection(
        property_id: UUID, inspection_id: UUID, request: Request, response: Response
    ) -> Json:
        actor = _require(request, resolver, JOINT_INSPECTIONS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        return one(property_id, inspection_id, actor.actor_id, request)

    @router.post("/joint-inspections", status_code=status.HTTP_201_CREATED)
    def start_joint_inspection(
        property_id: UUID, start: NewJointInspection, request: Request
    ) -> Json:
        right = JOINT_INSPECTIONS_RECORD if start.replaces_id is None else JOINT_INSPECTIONS_REPLACE
        actor = _require(request, resolver, right, property_id)
        require_browser_mutation(request, settings)
        try:
            made = flow.start(property_id, start.model_dump(mode="json"), actor_id=actor.actor_id)
        except REFUSED as exc:
            raise _http(exc) from exc
        return one(property_id, made, actor.actor_id, request)

    @router.post("/joint-inspections/{inspection_id}/save")
    def save_joint_inspection(
        property_id: UUID, inspection_id: UUID, changes: InspectionChanges, request: Request
    ) -> Json:
        actor = _require(request, resolver, JOINT_INSPECTIONS_RECORD, property_id)
        require_browser_mutation(request, settings)
        version = _expected_version(request)
        try:
            flow.save(
                property_id, inspection_id, version, _changes(changes), actor_id=actor.actor_id
            )
        except REFUSED as exc:
            raise _http(exc) from exc
        return one(property_id, inspection_id, actor.actor_id, request)

    @router.post("/joint-inspections/{inspection_id}/files", status_code=status.HTTP_201_CREATED)
    async def add_joint_inspection_file(
        property_id: UUID,
        inspection_id: UUID,
        request: Request,
        role: Role,
        line_id: Annotated[UUID | None, Query()] = None,
    ) -> Json:
        actor = _require(request, resolver, JOINT_INSPECTIONS_RECORD, property_id)
        require_browser_mutation(request, settings)
        version = _expected_version(request)
        media_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        if media_type not in FILE_TYPES:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Use a JPG, PNG or WEBP picture"
            )
        content = await request.body()
        if not content:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The file is empty")
        key = f"inspections/{inspection_id}/{uuid4()}.{FILE_TYPES[media_type]}"
        try:
            files.save(key, content)
        except REFUSED as exc:
            raise _http(exc) from exc
        record: Json = {
            "role": role,
            "media_type": media_type,
            "byte_size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "storage_key": key,
        }
        if line_id is not None:
            record["line_id"] = str(line_id)
        try:
            flow.add_file(property_id, inspection_id, version, record, actor_id=actor.actor_id)
        except REFUSED as exc:
            files.remove(key)
            raise _http(exc) from exc
        return one(property_id, inspection_id, actor.actor_id, request)

    @router.post("/joint-inspection-files/{file_id}/remove")
    def remove_joint_inspection_file(property_id: UUID, file_id: UUID, request: Request) -> Json:
        actor = _require(request, resolver, JOINT_INSPECTIONS_RECORD, property_id)
        require_browser_mutation(request, settings)
        try:
            flow.remove_file(property_id, file_id, actor_id=actor.actor_id)
        except REFUSED as exc:
            raise _http(exc) from exc
        # The file stays on disk: a replacement may still show it, and history keeps it.
        return envelope(request, {"file_id": str(file_id), "removed": True})

    @router.get("/joint-inspection-files/{file_id}")
    def joint_inspection_file(
        property_id: UUID, file_id: UUID, request: Request, response: Response
    ) -> Response:
        actor = _require(request, resolver, JOINT_INSPECTIONS_READ, property_id)
        try:
            found = flow.file(property_id, file_id, actor_id=actor.actor_id)
            content = files.read(str(found["storage_key"]), str(found["sha256"]))
        except REFUSED as exc:
            raise _http(exc) from exc
        return Response(
            content=content,
            media_type=str(found["media_type"]),
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.post("/joint-inspections/{inspection_id}/finish")
    def finish_joint_inspection(property_id: UUID, inspection_id: UUID, request: Request) -> Json:
        actor = _require(request, resolver, JOINT_INSPECTIONS_RECORD, property_id)
        require_browser_mutation(request, settings)
        version = _expected_version(request)
        try:
            done = flow.finish(property_id, inspection_id, version, actor_id=actor.actor_id)
        except REFUSED as exc:
            raise _http(exc) from exc
        read = one(property_id, inspection_id, actor.actor_id, request)
        data = read["data"]
        if not isinstance(data, dict):
            raise _http(ProductNotFound("the Joint Inspection does not exist"))
        return envelope(request, data | {"finished": done})

    return router


__all__ = [
    "InspectionChanges",
    "InspectionFiles",
    "JointInspectionFlow",
    "NewJointInspection",
    "PostgresJointInspectionFlow",
    "UnavailableJointInspectionFlow",
    "create_joint_inspections_router",
]
