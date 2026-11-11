"""Telegram app pages (bots step 2c, DL-128, API-TG-001).

`GET .../telegram/links` answers the Linked tenants page: the links in force, the link tries that
did not match in the last 24 hours and the links that ended (`telegram.read`).
`POST .../telegram/links/{link_id}/remove` removes a link with a reason (`telegram.operate`).
`GET .../telegram/health` answers the Telegram health page: the relay pulls, the messages not
sent with their last error and each bot's last message in and out (`telegram.read`).
`POST .../telegram/outbox/{message_id}/retry` sends again, once, a message the app gave up on
(`telegram.operate`). No bot key is ever read or shown here.

Step 2d part 2 (DL-170): `GET .../telegram/contact` answers the Contact office page (Waiting and
Answered) and `POST .../telegram/contact/{message_id}/answer` answers one message once, by Reply
(the bot sends it) or Answered by phone (`telegram.contact`). `GET .../telegram/faq` answers the
FAQ page (`telegram.faq`, or `telegram.contact` to read only); `POST .../telegram/faq` saves a
question (a new version; the Owner's is used at once) and
`POST .../telegram/faq/versions/{version_id}/approve` is the Owner's approval (`telegram.faq`).
DL-179: `POST .../telegram/faq/starter` loads the 15 starter questions into an empty FAQ, each
waiting for the Owner (`telegram.faq`).

Step 3a (DL-171): `GET .../visit-requests` answers the Visit requests tab of Bookings: the
requests the Customer bot saved, oldest first, each with the inquiries that joined it
(`visit_requests.read`: the Owner, the Manager and Staff).

Step 3b (DL-172): `GET .../visit-requests/{request_id}` answers one request with its history
(`visit_requests.read`); `POST .../visit-requests/{request_id}/{action}` records one step: take,
call, book (and move) a visit, visited, no-show, close, reopen and sent by hand
(`visit_requests.work`), give to another person and spam (`visit_requests.manage`).
Step 3c (DL-173): reserve (the request became a Reservation; `visit_requests.work`), block and
unblock the Telegram account (`visit_requests.manage`).

DL-214: `GET .../telegram/link-people?lease_id=|booking_id=` lists who on a live Lease or stay
can get a one-time Telegram QR, and `POST .../telegram/link-codes` makes one for a person: the
t.me link and its QR picture, shown once (`leases.sign` for a Lease, `short_stays.desk` for a
Booking).

DL-215: `GET .../telegram/receipts` lists the Receipts of the last 45 days and who got them on
Telegram (`telegram.read`).

DL-217: `GET .../telegram/warnings` lists the late Rent letters and Lease warnings of the last 90
days and who got them on Telegram (`telegram.read`).

DL-216: `GET .../telegram/notices` lists the notices of the last 90 days, the floors and the
Units (`telegram.read`); `POST .../telegram/notices` sends a notice to the people linked to
everyone, some floors or some Units (`telegram.operate`).

The database functions check the rights again.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal, Protocol
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from property_rental.browser_security import require_browser_mutation
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.products_api import (
    REFUSED,
    Json,
    ProductUnavailable,
    _http,
    _refusal,
    _require,
)
from property_rental.settings import Settings
from property_rental.totp_qr import telegram_link_qr_svg

TELEGRAM_READ = "telegram.read"
TELEGRAM_OPERATE = "telegram.operate"
TELEGRAM_CONTACT = "telegram.contact"
TELEGRAM_FAQ = "telegram.faq"
VISIT_REQUESTS_READ = "visit_requests.read"
VISIT_REQUESTS_WORK = "visit_requests.work"
VISIT_REQUESTS_MANAGE = "visit_requests.manage"
LINK_QR_RIGHTS = ("leases.sign", "short_stays.desk")
MANAGER_STEPS = frozenset({"give", "spam", "block", "unblock"})
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
AnswerText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
FaqAnswer = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800)]
VisitAt = Annotated[
    str, StringConstraints(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}$")
]
VisitAction = Literal[
    "take",
    "give",
    "call",
    "book",
    "visited",
    "no-show",
    "close",
    "reopen",
    "spam",
    "sent",
    "reserve",
    "block",
    "unblock",
]


class TelegramPageFlow(Protocol):
    def links(self, property_id: UUID, *, actor_id: str) -> Json: ...

    def remove_link(
        self, property_id: UUID, link_id: UUID, reason: str, *, actor_id: str
    ) -> None: ...

    def health(self, property_id: UUID, *, actor_id: str) -> Json: ...

    def invoices(self, property_id: UUID, *, actor_id: str) -> Json: ...

    def receipts(self, property_id: UUID, *, actor_id: str) -> Json: ...

    def warnings(self, property_id: UUID, *, actor_id: str) -> Json: ...

    def notices(self, property_id: UUID, *, actor_id: str) -> Json: ...

    def send_notice(self, property_id: UUID, body: Json, *, actor_id: str) -> Json: ...

    def retry(self, property_id: UUID, message_id: UUID, *, actor_id: str) -> UUID: ...

    def contact(self, property_id: UUID, *, actor_id: str) -> Json: ...

    def answer(
        self, property_id: UUID, message_id: UUID, how: str, text: str, *, actor_id: str
    ) -> None: ...

    def faq(self, property_id: UUID, *, actor_id: str) -> Json: ...

    def save_faq(self, property_id: UUID, version: Json, *, actor_id: str) -> Json: ...

    def approve_faq(self, property_id: UUID, version_id: UUID, *, actor_id: str) -> Json: ...

    def load_faq_starter(self, property_id: UUID, *, actor_id: str) -> Json: ...

    def visit_requests(self, property_id: UUID, *, actor_id: str) -> Json: ...

    def link_people(
        self, property_id: UUID, lease_id: UUID | None, booking_id: UUID | None, *, actor_id: str
    ) -> Json: ...

    def link_code(
        self,
        property_id: UUID,
        lease_id: UUID | None,
        booking_id: UUID | None,
        customer_id: UUID,
        *,
        actor_id: str,
    ) -> Json: ...

    def visit_request(self, property_id: UUID, request_id: UUID, *, actor_id: str) -> Json: ...

    def visit_step(
        self, property_id: UUID, request_id: UUID, action: str, body: Json, *, actor_id: str
    ) -> None: ...


class UnavailableTelegramPageFlow:
    def links(self, property_id: UUID, **_: object) -> Json:
        raise ProductUnavailable

    def remove_link(self, property_id: UUID, link_id: UUID, reason: str, **_: object) -> None:
        raise ProductUnavailable

    def health(self, property_id: UUID, **_: object) -> Json:
        raise ProductUnavailable

    def invoices(self, property_id: UUID, **_: object) -> Json:
        raise ProductUnavailable

    def receipts(self, property_id: UUID, **_: object) -> Json:
        raise ProductUnavailable

    def warnings(self, property_id: UUID, **_: object) -> Json:
        raise ProductUnavailable

    def notices(self, property_id: UUID, **_: object) -> Json:
        raise ProductUnavailable

    def send_notice(self, property_id: UUID, body: Json, **_: object) -> Json:
        raise ProductUnavailable

    def retry(self, property_id: UUID, message_id: UUID, **_: object) -> UUID:
        raise ProductUnavailable

    def contact(self, property_id: UUID, **_: object) -> Json:
        raise ProductUnavailable

    def answer(self, property_id: UUID, message_id: UUID, how: str, text: str, **_: object) -> None:
        raise ProductUnavailable

    def faq(self, property_id: UUID, **_: object) -> Json:
        raise ProductUnavailable

    def save_faq(self, property_id: UUID, version: Json, **_: object) -> Json:
        raise ProductUnavailable

    def approve_faq(self, property_id: UUID, version_id: UUID, **_: object) -> Json:
        raise ProductUnavailable

    def load_faq_starter(self, property_id: UUID, **_: object) -> Json:
        raise ProductUnavailable

    def visit_requests(self, property_id: UUID, **_: object) -> Json:
        raise ProductUnavailable

    def link_people(
        self, property_id: UUID, lease_id: UUID | None, booking_id: UUID | None, **_: object
    ) -> Json:
        raise ProductUnavailable

    def link_code(
        self,
        property_id: UUID,
        lease_id: UUID | None,
        booking_id: UUID | None,
        customer_id: UUID,
        **_: object,
    ) -> Json:
        raise ProductUnavailable

    def visit_request(self, property_id: UUID, request_id: UUID, **_: object) -> Json:
        raise ProductUnavailable

    def visit_step(
        self, property_id: UUID, request_id: UUID, action: str, body: Json, **_: object
    ) -> None:
        raise ProductUnavailable


def _json(value: object) -> Json:
    if not isinstance(value, dict):
        raise ProductUnavailable("Telegram persistence is unavailable")
    return {str(key): item for key, item in value.items()}


class PostgresTelegramPageFlow:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def _one(self, query: str, parameters: tuple[object, ...]) -> object:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(query, parameters).fetchone()
        except psycopg.Error as exc:
            raise _refusal(exc) from exc
        return None if row is None else row[0]

    def links(self, property_id: UUID, *, actor_id: str) -> Json:
        return _json(
            self._one("SELECT app.telegram_links_page(%s, %s)", (property_id, UUID(actor_id)))
        )

    def remove_link(self, property_id: UUID, link_id: UUID, reason: str, *, actor_id: str) -> None:
        self._one(
            "SELECT app.telegram_tenant_link_remove(%s, %s, %s, %s)::text",
            (property_id, link_id, reason, UUID(actor_id)),
        )

    def health(self, property_id: UUID, *, actor_id: str) -> Json:
        return _json(
            self._one("SELECT app.telegram_health_page(%s, %s)", (property_id, UUID(actor_id)))
        )

    def invoices(self, property_id: UUID, *, actor_id: str) -> Json:
        return _json(
            self._one("SELECT app.telegram_invoices_page(%s, %s)", (property_id, UUID(actor_id)))
        )

    def receipts(self, property_id: UUID, *, actor_id: str) -> Json:
        return _json(
            self._one("SELECT app.telegram_receipts_page(%s, %s)", (property_id, UUID(actor_id)))
        )

    def warnings(self, property_id: UUID, *, actor_id: str) -> Json:
        return _json(
            self._one("SELECT app.telegram_warnings_page(%s, %s)", (property_id, UUID(actor_id)))
        )

    def notices(self, property_id: UUID, *, actor_id: str) -> Json:
        return _json(
            self._one("SELECT app.telegram_notices_page(%s, %s)", (property_id, UUID(actor_id)))
        )

    def send_notice(self, property_id: UUID, body: Json, *, actor_id: str) -> Json:
        return _json(
            self._one(
                "SELECT app.telegram_notice_send(%s, %s::jsonb, %s)",
                (property_id, json.dumps(body), UUID(actor_id)),
            )
        )

    def retry(self, property_id: UUID, message_id: UUID, *, actor_id: str) -> UUID:
        made = self._one(
            "SELECT app.telegram_outbox_retry(%s, %s, %s)",
            (property_id, message_id, UUID(actor_id)),
        )
        return UUID(str(made))

    def contact(self, property_id: UUID, *, actor_id: str) -> Json:
        return _json(
            self._one("SELECT app.telegram_contact_page(%s, %s)", (property_id, UUID(actor_id)))
        )

    def answer(
        self, property_id: UUID, message_id: UUID, how: str, text: str, *, actor_id: str
    ) -> None:
        self._one(
            "SELECT app.telegram_contact_answer(%s, %s, %s, %s, %s)::text",
            (property_id, message_id, how, text, UUID(actor_id)),
        )

    def faq(self, property_id: UUID, *, actor_id: str) -> Json:
        return _json(
            self._one("SELECT app.telegram_faq_page(%s, %s)", (property_id, UUID(actor_id)))
        )

    def save_faq(self, property_id: UUID, version: Json, *, actor_id: str) -> Json:
        question = version.get("question_id")
        body = {key: value for key, value in version.items() if key != "question_id"}
        return _json(
            self._one(
                "SELECT app.telegram_faq_save(%s, %s, %s::jsonb, %s)",
                (
                    property_id,
                    None if question is None else UUID(str(question)),
                    json.dumps(body),
                    UUID(actor_id),
                ),
            )
        )

    def approve_faq(self, property_id: UUID, version_id: UUID, *, actor_id: str) -> Json:
        return _json(
            self._one(
                "SELECT app.telegram_faq_approve(%s, %s, %s)",
                (property_id, version_id, UUID(actor_id)),
            )
        )

    def load_faq_starter(self, property_id: UUID, *, actor_id: str) -> Json:
        return _json(
            self._one("SELECT app.telegram_faq_load_starter(%s, %s)", (property_id, UUID(actor_id)))
        )

    def link_people(
        self, property_id: UUID, lease_id: UUID | None, booking_id: UUID | None, *, actor_id: str
    ) -> Json:
        return _json(
            self._one(
                "SELECT app.telegram_link_people(%s, %s, %s, %s)",
                (property_id, lease_id, booking_id, UUID(actor_id)),
            )
        )

    def link_code(
        self,
        property_id: UUID,
        lease_id: UUID | None,
        booking_id: UUID | None,
        customer_id: UUID,
        *,
        actor_id: str,
    ) -> Json:
        return _json(
            self._one(
                "SELECT app.telegram_link_code_create(%s, %s, %s, %s, %s)",
                (property_id, lease_id, booking_id, customer_id, UUID(actor_id)),
            )
        )

    def visit_requests(self, property_id: UUID, *, actor_id: str) -> Json:
        return _json(
            self._one("SELECT app.visit_requests_page(%s, %s)", (property_id, UUID(actor_id)))
        )

    def visit_request(self, property_id: UUID, request_id: UUID, *, actor_id: str) -> Json:
        return _json(
            self._one(
                "SELECT app.visit_request_detail(%s, %s, %s)",
                (property_id, request_id, UUID(actor_id)),
            )
        )

    def visit_step(
        self, property_id: UUID, request_id: UUID, action: str, body: Json, *, actor_id: str
    ) -> None:
        self._one(
            "SELECT app.visit_request_act(%s, %s, %s, %s::jsonb, %s)::text",
            (property_id, request_id, action, json.dumps(body), UUID(actor_id)),
        )


class RemoveLink(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    reason: Reason


class LinkCode(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    lease_id: UUID | None = Field(default=None, strict=False)
    booking_id: UUID | None = Field(default=None, strict=False)
    customer_id: UUID = Field(strict=False)


NoticeWords = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1500)]


class SendNotice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text_en: NoticeWords = ""
    text_km: NoticeWords = ""
    audience: Literal["ALL", "FLOORS", "UNITS"]
    floors: list[Annotated[str, StringConstraints(max_length=40)]] = Field(
        default_factory=list, max_length=100
    )
    unit_ids: list[UUID] = Field(default_factory=list, max_length=500, strict=False)


class ContactAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    how: Literal["TELEGRAM", "PHONE"]
    answer: AnswerText


class FaqVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    question_id: UUID | None = Field(default=None, strict=False)
    for_bots: Literal["BOTH", "CUSTOMER", "TENANT", "HIDDEN"]
    question_en: Question
    answer_en: FaqAnswer
    question_km: Question
    answer_km: FaqAnswer


class VisitStep(BaseModel):
    """One step on a Visit request; the database checks which fields each step needs."""

    model_config = ConfigDict(extra="forbid", strict=True)

    staff_id: UUID | None = Field(default=None, strict=False)
    answered: bool | None = None
    visit_at: VisitAt | None = None
    reason: (
        Literal[
            "PRICE",
            "TYPE_NOT_FREE",
            "LOCATION",
            "FOUND_OTHER",
            "MOVE_IN_FAR",
            "NO_REACH",
            "OTHER",
            "CANCELLED",
        ]
        | None
    ) = None
    what: Literal["CONFIRMATION", "REMINDER"] | None = None
    note: Reason | None = None
    reservation_id: UUID | None = Field(default=None, strict=False)


def _require_any(
    request: Request, resolver: ActorResolver, capabilities: tuple[str, ...], property_id: UUID
) -> AuthenticatedActor:
    actor = resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    for capability in capabilities:
        if is_authorized(
            actor, AuthorizationRequirement(capability=capability, property_id=str(property_id))
        ):
            return actor
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


def create_telegram_router(
    resolver: ActorResolver, flow: TelegramPageFlow, settings: Settings
) -> APIRouter:
    pages = APIRouter(prefix="/api/v1/properties/{property_id}", tags=["telegram"])

    def envelope(request: Request, data: object) -> Json:
        return {"data": data, "meta": {"request_id": request.state.request_id}}

    @pages.get("/telegram/links")
    def telegram_links(property_id: UUID, request: Request, response: Response) -> Json:
        actor = _require(request, resolver, TELEGRAM_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.links(property_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @pages.post("/telegram/links/{link_id}/remove")
    def remove_telegram_link(
        property_id: UUID, link_id: UUID, body: RemoveLink, request: Request
    ) -> Json:
        actor = _require(request, resolver, TELEGRAM_OPERATE, property_id)
        require_browser_mutation(request, settings)
        try:
            flow.remove_link(property_id, link_id, body.reason, actor_id=actor.actor_id)
            return envelope(request, flow.links(property_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @pages.get("/telegram/health")
    def telegram_health(property_id: UUID, request: Request, response: Response) -> Json:
        actor = _require(request, resolver, TELEGRAM_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.health(property_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @pages.get("/telegram/invoices")
    def telegram_invoices(property_id: UUID, request: Request, response: Response) -> Json:
        actor = _require(request, resolver, TELEGRAM_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.invoices(property_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @pages.get("/telegram/receipts")
    def telegram_receipts(property_id: UUID, request: Request, response: Response) -> Json:
        actor = _require(request, resolver, TELEGRAM_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.receipts(property_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @pages.get("/telegram/warnings")
    def telegram_warnings(property_id: UUID, request: Request, response: Response) -> Json:
        actor = _require(request, resolver, TELEGRAM_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.warnings(property_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @pages.get("/telegram/notices")
    def telegram_notices(property_id: UUID, request: Request, response: Response) -> Json:
        actor = _require(request, resolver, TELEGRAM_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.notices(property_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @pages.post("/telegram/notices", status_code=status.HTTP_201_CREATED)
    def send_telegram_notice(
        property_id: UUID, body: SendNotice, request: Request, response: Response
    ) -> Json:
        actor = _require(request, resolver, TELEGRAM_OPERATE, property_id)
        require_browser_mutation(request, settings)
        response.headers["Cache-Control"] = "private, no-store"
        if body.text_en == "" and body.text_km == "":
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
        sent: Json = {
            "text_en": body.text_en or None,
            "text_km": body.text_km or None,
            "audience": body.audience,
            "floors": body.floors,
            "unit_ids": [str(unit) for unit in body.unit_ids],
        }
        try:
            made = flow.send_notice(property_id, sent, actor_id=actor.actor_id)
            return envelope(
                request,
                {"sent": made, "page": flow.notices(property_id, actor_id=actor.actor_id)},
            )
        except REFUSED as exc:
            raise _http(exc) from exc

    @pages.post("/telegram/outbox/{message_id}/retry", status_code=status.HTTP_201_CREATED)
    def retry_telegram_message(property_id: UUID, message_id: UUID, request: Request) -> Json:
        actor = _require(request, resolver, TELEGRAM_OPERATE, property_id)
        require_browser_mutation(request, settings)
        try:
            made = flow.retry(property_id, message_id, actor_id=actor.actor_id)
            return envelope(
                request,
                {
                    "message_id": str(made),
                    "health": flow.health(property_id, actor_id=actor.actor_id),
                },
            )
        except REFUSED as exc:
            raise _http(exc) from exc

    @pages.get("/telegram/contact")
    def telegram_contact(property_id: UUID, request: Request, response: Response) -> Json:
        actor = _require(request, resolver, TELEGRAM_CONTACT, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.contact(property_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @pages.post("/telegram/contact/{message_id}/answer")
    def answer_telegram_contact(
        property_id: UUID, message_id: UUID, body: ContactAnswer, request: Request
    ) -> Json:
        actor = _require(request, resolver, TELEGRAM_CONTACT, property_id)
        require_browser_mutation(request, settings)
        try:
            flow.answer(property_id, message_id, body.how, body.answer, actor_id=actor.actor_id)
            return envelope(request, flow.contact(property_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @pages.get("/telegram/faq")
    def telegram_faq(property_id: UUID, request: Request, response: Response) -> Json:
        actor = _require_any(request, resolver, (TELEGRAM_FAQ, TELEGRAM_CONTACT), property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.faq(property_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @pages.post("/telegram/faq")
    def save_telegram_faq(property_id: UUID, body: FaqVersion, request: Request) -> Json:
        actor = _require(request, resolver, TELEGRAM_FAQ, property_id)
        require_browser_mutation(request, settings)
        version: Json = {
            "question_id": None if body.question_id is None else str(body.question_id),
            "for_bots": body.for_bots,
            "question_en": body.question_en,
            "answer_en": body.answer_en,
            "question_km": body.question_km,
            "answer_km": body.answer_km,
        }
        try:
            saved = flow.save_faq(property_id, version, actor_id=actor.actor_id)
            return envelope(
                request, {"saved": saved, "faq": flow.faq(property_id, actor_id=actor.actor_id)}
            )
        except REFUSED as exc:
            raise _http(exc) from exc

    @pages.post("/telegram/faq/versions/{version_id}/approve")
    def approve_telegram_faq(property_id: UUID, version_id: UUID, request: Request) -> Json:
        actor = _require(request, resolver, TELEGRAM_FAQ, property_id)
        require_browser_mutation(request, settings)
        try:
            approved = flow.approve_faq(property_id, version_id, actor_id=actor.actor_id)
            return envelope(
                request,
                {"approved": approved, "faq": flow.faq(property_id, actor_id=actor.actor_id)},
            )
        except REFUSED as exc:
            raise _http(exc) from exc

    @pages.post("/telegram/faq/starter")
    def load_telegram_faq_starter(property_id: UUID, request: Request) -> Json:
        actor = _require(request, resolver, TELEGRAM_FAQ, property_id)
        require_browser_mutation(request, settings)
        try:
            loaded = flow.load_faq_starter(property_id, actor_id=actor.actor_id)
            return envelope(
                request, {"loaded": loaded, "faq": flow.faq(property_id, actor_id=actor.actor_id)}
            )
        except REFUSED as exc:
            raise _http(exc) from exc

    @pages.get("/telegram/link-people")
    def telegram_link_people(
        property_id: UUID,
        request: Request,
        response: Response,
        lease_id: UUID | None = None,
        booking_id: UUID | None = None,
    ) -> Json:
        actor = _require_any(request, resolver, LINK_QR_RIGHTS, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        if (lease_id is None) == (booking_id is None):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        try:
            return envelope(
                request,
                flow.link_people(property_id, lease_id, booking_id, actor_id=actor.actor_id),
            )
        except REFUSED as exc:
            raise _http(exc) from exc

    @pages.post("/telegram/link-codes", status_code=status.HTTP_201_CREATED)
    def telegram_link_code(
        property_id: UUID, body: LinkCode, request: Request, response: Response
    ) -> Json:
        actor = _require_any(request, resolver, LINK_QR_RIGHTS, property_id)
        require_browser_mutation(request, settings)
        response.headers["Cache-Control"] = "private, no-store"
        if (body.lease_id is None) == (body.booking_id is None):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        try:
            made = flow.link_code(
                property_id,
                body.lease_id,
                body.booking_id,
                body.customer_id,
                actor_id=actor.actor_id,
            )
        except REFUSED as exc:
            raise _http(exc) from exc
        link = str(made.get("url") or "")
        try:
            picture = telegram_link_qr_svg(link)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        return envelope(request, {**made, "qr_svg": picture})

    @pages.get("/visit-requests")
    def visit_requests(property_id: UUID, request: Request, response: Response) -> Json:
        actor = _require(request, resolver, VISIT_REQUESTS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.visit_requests(property_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @pages.get("/visit-requests/{request_id}")
    def visit_request(
        property_id: UUID, request_id: UUID, request: Request, response: Response
    ) -> Json:
        actor = _require(request, resolver, VISIT_REQUESTS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(
                request, flow.visit_request(property_id, request_id, actor_id=actor.actor_id)
            )
        except REFUSED as exc:
            raise _http(exc) from exc

    @pages.post("/visit-requests/{request_id}/{action}")
    def visit_request_step(
        property_id: UUID, request_id: UUID, action: VisitAction, body: VisitStep, request: Request
    ) -> Json:
        needed = VISIT_REQUESTS_MANAGE if action in MANAGER_STEPS else VISIT_REQUESTS_WORK
        actor = _require(request, resolver, needed, property_id)
        require_browser_mutation(request, settings)
        step: Json = {
            key: str(value) if isinstance(value, UUID) else value
            for key, value in body.model_dump(exclude_none=True).items()
        }
        try:
            flow.visit_step(
                property_id,
                request_id,
                action.upper().replace("-", "_"),
                step,
                actor_id=actor.actor_id,
            )
            return envelope(
                request,
                {
                    "request": flow.visit_request(property_id, request_id, actor_id=actor.actor_id),
                    "page": flow.visit_requests(property_id, actor_id=actor.actor_id),
                },
            )
        except REFUSED as exc:
            raise _http(exc) from exc

    return pages
