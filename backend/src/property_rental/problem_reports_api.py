"""Problem reports (V1.1 part 7, DL-124, API-PR-001).

One list for Unit Problems (UP) and Building problems (BP). `GET .../problem-reports` lists the
latest reports, `GET .../problem-reports/{id}` reads one with its history and
`GET .../problem-report-choices` gives the types, shared places, Units and rules for the forms
(`problem_reports.read`). `POST .../problem-reports` adds a report (`problem_reports.add`).
`POST .../problem-reports/{id}/steps` records one step at the version in If-Match
(`problem_reports.plan`; Join and Undo join need `problem_reports.join`).
`POST .../problem-reports/{id}/tenant-answer` records the tenant's answer: Agree makes the Damage
Invoice draft at once for the amount the Manager set, so it runs on the financial connection.

The database functions check the rights again and keep what was reported unchanged.
"""

from __future__ import annotations

from datetime import date, time
from typing import Annotated, Literal, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Request, Response, status
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from property_rental.browser_security import require_browser_mutation
from property_rental.identity import ActorResolver
from property_rental.products_api import (
    REFUSED,
    Id,
    Json,
    ProductUnavailable,
    _expected_version,
    _http,
    _refusal,
    _require,
)
from property_rental.settings import Settings

PROBLEM_REPORTS_READ = "problem_reports.read"
PROBLEM_REPORTS_ADD = "problem_reports.add"
PROBLEM_REPORTS_PLAN = "problem_reports.plan"
PROBLEM_REPORTS_JOIN = "problem_reports.join"
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Floor = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
Description = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
]
Step = Literal[
    "CONTACTED",
    "PLAN",
    "NOT_A_REPAIR",
    "MAKE_JOB",
    "CLEANING",
    "CLOSE_NOTE",
    "CHECKED",
    "DECIDE",
    "PARTS",
    "PARTS_ARRIVED",
    "DONE",
    "TENANT_FIXED",
    "TENANT_NOT_FIXED",
    "CLOSE",
    "JOIN",
    "UNJOIN",
]


class ProblemReportFlow(Protocol):
    def reports(self, property_id: UUID, *, actor_id: str) -> list[Json]: ...

    def report(self, property_id: UUID, report_id: UUID, *, actor_id: str) -> Json: ...

    def choices(self, property_id: UUID, *, actor_id: str) -> Json: ...

    def add(self, property_id: UUID, report: Json, *, actor_id: str) -> UUID: ...

    def step(
        self, property_id: UUID, report_id: UUID, version: int, step: Json, *, actor_id: str
    ) -> None: ...

    def answer(
        self, property_id: UUID, report_id: UUID, version: int, answer: Json, *, actor_id: str
    ) -> None: ...


class UnavailableProblemReportFlow:
    def reports(self, property_id: UUID, **_: object) -> list[Json]:
        raise ProductUnavailable

    def report(self, property_id: UUID, report_id: UUID, **_: object) -> Json:
        raise ProductUnavailable

    def choices(self, property_id: UUID, **_: object) -> Json:
        raise ProductUnavailable

    def add(self, property_id: UUID, report: Json, **_: object) -> UUID:
        raise ProductUnavailable

    def step(
        self, property_id: UUID, report_id: UUID, version: int, step: Json, **_: object
    ) -> None:
        raise ProductUnavailable

    def answer(
        self, property_id: UUID, report_id: UUID, version: int, answer: Json, **_: object
    ) -> None:
        raise ProductUnavailable


def _json(value: object) -> Json:
    if not isinstance(value, dict):
        raise ProductUnavailable("Problem report persistence is unavailable")
    return {str(key): item for key, item in value.items()}


class PostgresProblemReportFlow:
    def __init__(self, database_url: str, financial_database_url: str | None) -> None:
        self._database_url = database_url
        self._financial_database_url = financial_database_url

    def _one(self, url: str | None, query: str, parameters: tuple[object, ...]) -> object:
        if url is None:
            raise ProductUnavailable("Problem report persistence is unavailable")
        try:
            with psycopg.connect(url) as connection:
                row = connection.execute(query, parameters).fetchone()
        except psycopg.Error as exc:
            raise _refusal(exc) from exc
        return None if row is None else row[0]

    def reports(self, property_id: UUID, *, actor_id: str) -> list[Json]:
        found = self._one(
            self._database_url,
            "SELECT app.problem_reports_read(%s, %s)",
            (property_id, UUID(actor_id)),
        )
        if not isinstance(found, list):
            raise ProductUnavailable("Problem report persistence is unavailable")
        return [_json(item) for item in found]

    def report(self, property_id: UUID, report_id: UUID, *, actor_id: str) -> Json:
        return _json(
            self._one(
                self._database_url,
                "SELECT app.problem_report_read(%s, %s, %s)",
                (property_id, report_id, UUID(actor_id)),
            )
        )

    def choices(self, property_id: UUID, *, actor_id: str) -> Json:
        return _json(
            self._one(
                self._database_url,
                "SELECT app.problem_report_choices(%s, %s)",
                (property_id, UUID(actor_id)),
            )
        )

    def add(self, property_id: UUID, report: Json, *, actor_id: str) -> UUID:
        made = self._one(
            self._database_url,
            "SELECT app.add_problem_report(%s, %s, %s, %s)",
            (property_id, Jsonb(report), UUID(actor_id), uuid4()),
        )
        return UUID(str(made))

    def step(
        self, property_id: UUID, report_id: UUID, version: int, step: Json, *, actor_id: str
    ) -> None:
        body = dict(step)
        name = body.pop("step")
        self._one(
            self._database_url,
            "SELECT app.problem_report_step(%s, %s, %s, %s, %s, %s, %s)",
            (property_id, report_id, version, name, Jsonb(body), UUID(actor_id), uuid4()),
        )

    def answer(
        self, property_id: UUID, report_id: UUID, version: int, answer: Json, *, actor_id: str
    ) -> None:
        self._one(
            self._financial_database_url,
            "SELECT app.record_problem_tenant_answer(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                property_id,
                report_id,
                version,
                answer["answer"],
                answer["how"],
                answer["answered_on"],
                answer["said"],
                answer["after_refusal"],
                UUID(actor_id),
                uuid4(),
            ),
        )


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class NewProblemReport(_Body):
    kind: Literal["UNIT", "BUILDING"]
    source: Literal["PHONE", "WALKIN", "SEEN"]
    problem_type_id: Id
    description: Description
    urgent: bool
    unit_id: Id | None = None
    place_item_id: Id | None = None
    place_number: Annotated[int, Field(ge=1, le=99)] | None = None
    problem_place_id: Id | None = None
    floor: Floor | None = None
    may_enter: bool = False
    best_time: Literal["AM", "PM", "ANY"] = "ANY"
    reported_by: Name | None = None
    same_as: Id | None = None


class ProblemStep(_Body):
    step: Step
    note: Text | None = None
    how: Literal["PHONE", "VISIT"] | None = None
    technician: Name | None = None
    visit_on: Annotated[date, Field(strict=False)] | None = None
    visit_at: Annotated[time, Field(strict=False)] | None = None
    cleaner: Name | None = None
    cause: Literal["WEAR", "DAMAGE", "UNSURE"] | None = None
    fixed: bool | None = None
    pays: Literal["OWNER", "TENANT"] | None = None
    amount_usd_cents: Annotated[int, Field(ge=1, le=999_999_999)] | None = None
    reason: Text | None = None
    main_id: Id | None = None


class TenantAnswer(_Body):
    answer: Literal["AGREED", "REFUSED"]
    how: Literal["SIGNED", "TELEGRAM", "PHONE", "IN_PERSON"]
    answered_on: Annotated[date, Field(strict=False)]
    said: Text | None = None
    after_refusal: Literal["OWNER_PAYS", "MOVE_OUT"] | None = None


def create_problem_reports_router(
    resolver: ActorResolver, flow: ProblemReportFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/properties/{property_id}", tags=["problem reports"])

    def envelope(request: Request, data: object) -> Json:
        return {"data": data, "meta": {"request_id": request.state.request_id}}

    def one(property_id: UUID, report_id: UUID, actor_id: str, request: Request) -> Json:
        try:
            return envelope(request, flow.report(property_id, report_id, actor_id=actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.get("/problem-reports")
    def list_problem_reports(property_id: UUID, request: Request, response: Response) -> Json:
        actor = _require(request, resolver, PROBLEM_REPORTS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.reports(property_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.get("/problem-report-choices")
    def problem_report_choices(property_id: UUID, request: Request, response: Response) -> Json:
        actor = _require(request, resolver, PROBLEM_REPORTS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.choices(property_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.get("/problem-reports/{report_id}")
    def read_problem_report(
        property_id: UUID, report_id: UUID, request: Request, response: Response
    ) -> Json:
        actor = _require(request, resolver, PROBLEM_REPORTS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        return one(property_id, report_id, actor.actor_id, request)

    @router.post("/problem-reports", status_code=status.HTTP_201_CREATED)
    def add_problem_report(property_id: UUID, report: NewProblemReport, request: Request) -> Json:
        actor = _require(request, resolver, PROBLEM_REPORTS_ADD, property_id)
        require_browser_mutation(request, settings)
        body: Json = report.model_dump(mode="json", exclude_none=True)
        try:
            made = flow.add(property_id, body, actor_id=actor.actor_id)
        except REFUSED as exc:
            raise _http(exc) from exc
        return one(property_id, made, actor.actor_id, request)

    @router.post("/problem-reports/{report_id}/steps")
    def problem_report_step(
        property_id: UUID, report_id: UUID, step: ProblemStep, request: Request
    ) -> Json:
        right = PROBLEM_REPORTS_JOIN if step.step in ("JOIN", "UNJOIN") else PROBLEM_REPORTS_PLAN
        actor = _require(request, resolver, right, property_id)
        require_browser_mutation(request, settings)
        version = _expected_version(request)
        body: Json = step.model_dump(mode="json", exclude_none=True)
        if step.visit_at is not None:
            body["visit_at"] = step.visit_at.strftime("%H:%M")
        try:
            flow.step(property_id, report_id, version, body, actor_id=actor.actor_id)
        except REFUSED as exc:
            raise _http(exc) from exc
        return one(property_id, report_id, actor.actor_id, request)

    @router.post("/problem-reports/{report_id}/tenant-answer")
    def problem_report_tenant_answer(
        property_id: UUID, report_id: UUID, answer: TenantAnswer, request: Request
    ) -> Json:
        actor = _require(request, resolver, PROBLEM_REPORTS_PLAN, property_id)
        require_browser_mutation(request, settings)
        version = _expected_version(request)
        try:
            flow.answer(
                property_id, report_id, version, answer.model_dump(), actor_id=actor.actor_id
            )
        except REFUSED as exc:
            raise _http(exc) from exc
        return one(property_id, report_id, actor.actor_id, request)

    return router


__all__ = [
    "NewProblemReport",
    "PostgresProblemReportFlow",
    "ProblemReportFlow",
    "UnavailableProblemReportFlow",
    "create_problem_reports_router",
]
