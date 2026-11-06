"""Daily and weekly rent: calendar, price and bookings (phase 6 step 2).

`GET .../short-stays/calendar` shows every Unit with its bookings, Leases and Reservation for
1 to 62 days, `GET .../short-stays/price` prices a stay in one Unit (with the monthly hint and why
the Unit cannot be booked), and `GET .../short-stays/bookings` and `.../bookings/{id}` read
bookings (`short_stays.read`). `POST .../short-stays/bookings` makes a booking for a guest who is a
Customer (`short_stays.desk`). Step 3 adds the booking's actions: bill, paid on the site,
deposit, check-in, check-out and ending the deposit (`short_stays.desk`), the room check
(`short_stays.housekeeping`) and the decision on damage (`short_stays.approve`). Step 4a adds the
early check-in and late check-out fee and extending a stay (`short_stays.desk`), and the cleaning
list of a day (`GET .../housekeeping`, `short_stays.read`) with its done or skipped cleans
(`short_stays.housekeeping`). Step 4b adds cancel and no-show (`short_stays.desk`) and the
late-cancel credit (`short_stays.credit`). Step 4c links the guest's Lease draft for $50 off its
first month (`short_stays.desk`). Step 5a adds the booking-site calendar links
(`short_stays.approve`) and our own calendar for each site, read by its private token without a
sign-in (`GET /api/v1/short-stays/ical/{token}.ics`: busy dates only). Step 5b adds quotes
(`GET`/`POST .../quotes`), a guest's history and notes (`GET .../guests/{id}`,
`POST .../guests/{id}/notes`), the review request after check-out (`short_stays.desk`) and the
Manager's extra discount before the Invoice (`short_stays.approve`). Step 5c adds the weekly
report (`GET .../report?from=`, `short_stays.approve`) and a monthly tenant's complaint about
short-stay guests (`POST .../complaints`, `short_stays.desk`). Step 5d ends a late-cancel credit
after its use-by day (`POST .../bookings/{id}/credit/end`, `GET .../credits-due`,
`short_stays.credit`). The database
functions check the rights again, price the stay from the owner's rules and keep one booking per
Unit and night.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import PlainTextResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from property_rental.browser_security import require_browser_mutation
from property_rental.identity import ActorResolver
from property_rental.products_api import (
    REFUSED,
    Id,
    Json,
    ProductConflict,
    ProductUnavailable,
    _http,
    _refusal,
    _require,
)
from property_rental.settings import Settings
from property_rental.short_stay_ical import write_calendar

SHORT_STAYS_READ = "short_stays.read"
SHORT_STAYS_DESK = "short_stays.desk"
SHORT_STAYS_HOUSEKEEPING = "short_stays.housekeeping"
SHORT_STAYS_APPROVE = "short_stays.approve"
SHORT_STAYS_CREDIT = "short_stays.credit"
SiteText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Day = Annotated[date, Field(strict=False)]
Action = Literal[
    "bill",
    "paid_on_site",
    "deposit",
    "check_in",
    "check_out",
    "room_check",
    "decide",
    "end_deposit",
    "fee",
    "extend",
    "finish_task",
    "cancel",
    "credit",
    "link_lease",
    "site_calendar",
    "discount",
    "guest_note",
    "review",
    "quote",
    "complaint",
    "end_credit",
]
# Step 3 (migration 20270602_312): each action is one database function that checks the right
# again. "version" is the booking version the screen read (refused with 412 when it changed).
ACTION_SQL: dict[str, str] = {
    "bill": "SELECT app.bill_short_stay(%(p)s, %(t)s, %(v)s, %(a)s, %(c)s)",
    "paid_on_site": "SELECT app.mark_short_stay_paid_on_site(%(p)s, %(t)s, %(v)s, %(a)s, %(c)s)",
    "deposit": "SELECT app.take_short_stay_deposit(%(p)s, %(t)s, %(b)s, %(a)s, %(c)s)",
    "check_in": "SELECT app.check_in_short_stay(%(p)s, %(t)s, %(b)s, %(v)s, %(a)s, %(c)s)",
    "check_out": "SELECT app.check_out_short_stay(%(p)s, %(t)s, %(v)s, %(a)s, %(c)s)",
    "room_check": "SELECT app.check_short_stay_room(%(p)s, %(t)s, %(b)s, %(a)s, %(c)s)",
    "decide": "SELECT app.decide_short_stay_damage(%(p)s, %(t)s, %(b)s, %(a)s, %(c)s)",
    "end_deposit": "SELECT app.end_short_stay_deposit(%(p)s, %(t)s, %(a)s, %(c)s)",
    # Step 4a (migration 20270603_313).
    "fee": "SELECT app.add_short_stay_fee(%(p)s, %(t)s, %(b)s ->> 'kind', %(v)s, %(a)s, %(c)s)",
    "extend": "SELECT app.extend_short_stay(%(p)s, %(t)s, %(b)s, %(v)s, %(a)s, %(c)s)",
    "finish_task": "SELECT app.finish_housekeeping_task(%(p)s, %(t)s, %(b)s, %(a)s, %(c)s)",
    # Step 4b (migration 20270604_314).
    "cancel": "SELECT app.cancel_short_stay(%(p)s, %(t)s, %(b)s, %(v)s, %(a)s, %(c)s)",
    "credit": "SELECT app.give_short_stay_credit(%(p)s, %(t)s, %(b)s, %(a)s, %(c)s)",
    # Step 4c (migration 20270605_315).
    "link_lease": "SELECT app.link_short_stay_lease(%(p)s, %(t)s, %(b)s, %(a)s, %(c)s)",
    # Step 5a (migration 20270606_316): the target is the Property; a change carries its version.
    "site_calendar": (
        "SELECT app.save_booking_site_calendar(%(p)s, %(b)s || "
        "jsonb_strip_nulls(jsonb_build_object('version', %(v)s::integer)), %(a)s, %(c)s)"
    ),
    # Step 5b (migration 20270607_317): a note's target is the guest; a quote's the Property.
    "discount": "SELECT app.give_short_stay_discount(%(p)s, %(t)s, %(b)s, %(v)s, %(a)s, %(c)s)",
    "guest_note": "SELECT app.add_guest_note(%(p)s, %(t)s, %(b)s, %(a)s, %(c)s)",
    "review": "SELECT app.ask_short_stay_review(%(p)s, %(t)s, %(a)s, %(c)s)",
    "quote": "SELECT app.make_short_stay_quote(%(p)s, %(b)s, %(a)s, %(c)s)",
    # Step 5c (migration 20270608_318): the target is the Property.
    "complaint": "SELECT app.record_short_stay_complaint(%(p)s, %(b)s, %(a)s, %(c)s)",
    # Step 5d (migration 20270609_319): a late-cancel credit ends after its use-by day.
    "end_credit": "SELECT app.end_short_stay_credit(%(p)s, %(t)s, %(a)s, %(c)s)",
}


class ShortStayFlow(Protocol):
    def calendar(self, property_id: UUID, start: date, days: int, *, actor_id: str) -> Json: ...

    def price(
        self, property_id: UUID, unit_id: UUID, check_in: date, check_out: date, *, actor_id: str
    ) -> Json: ...

    def bookings(self, property_id: UUID, *, actor_id: str) -> list[Json]: ...

    def booking(self, property_id: UUID, booking_id: UUID, *, actor_id: str) -> Json: ...

    def book(self, property_id: UUID, booking: Json, *, actor_id: str) -> UUID: ...

    def housekeeping(self, property_id: UUID, day: date, *, actor_id: str) -> Json: ...

    def site_calendars(self, property_id: UUID, *, actor_id: str) -> list[Json]: ...

    def calendar_feed(self, token: str) -> Json | None: ...

    def guest(self, property_id: UUID, customer_id: UUID, *, actor_id: str) -> Json: ...

    def quotes(self, property_id: UUID, *, actor_id: str) -> list[Json]: ...

    def week_report(self, property_id: UUID, start: date, *, actor_id: str) -> Json: ...

    def credits_due(self, property_id: UUID, *, actor_id: str) -> list[Json]: ...

    def act(
        self, property_id: UUID, action: Action, target: UUID, body: Json, *, actor_id: str
    ) -> Json: ...


class UnavailableShortStayFlow:
    def calendar(self, property_id: UUID, start: date, days: int, **_: object) -> Json:
        raise ProductUnavailable

    def price(
        self, property_id: UUID, unit_id: UUID, check_in: date, check_out: date, **_: object
    ) -> Json:
        raise ProductUnavailable

    def bookings(self, property_id: UUID, **_: object) -> list[Json]:
        raise ProductUnavailable

    def booking(self, property_id: UUID, booking_id: UUID, **_: object) -> Json:
        raise ProductUnavailable

    def book(self, property_id: UUID, booking: Json, **_: object) -> UUID:
        raise ProductUnavailable

    def housekeeping(self, property_id: UUID, day: date, **_: object) -> Json:
        raise ProductUnavailable

    def site_calendars(self, property_id: UUID, **_: object) -> list[Json]:
        raise ProductUnavailable

    def calendar_feed(self, token: str) -> Json | None:
        raise ProductUnavailable

    def guest(self, property_id: UUID, customer_id: UUID, **_: object) -> Json:
        raise ProductUnavailable

    def quotes(self, property_id: UUID, **_: object) -> list[Json]:
        raise ProductUnavailable

    def week_report(self, property_id: UUID, start: date, **_: object) -> Json:
        raise ProductUnavailable

    def credits_due(self, property_id: UUID, **_: object) -> list[Json]:
        raise ProductUnavailable

    def act(self, property_id: UUID, action: Action, target: UUID, body: Json, **_: object) -> Json:
        raise ProductUnavailable


def _json(value: object) -> Json:
    if not isinstance(value, dict):
        raise ProductUnavailable("Short-stay persistence is unavailable")
    return {str(key): item for key, item in value.items()}


class PostgresShortStayFlow:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def _one(self, query: str, parameters: tuple[object, ...] | dict[str, object]) -> object:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(query, parameters).fetchone()
        except psycopg.Error as exc:
            # Two people booking the same night at once: the database keeps one.
            if exc.sqlstate == "23P01":
                raise ProductConflict("The Unit is already booked on one of these nights") from exc
            raise _refusal(exc) from exc
        return None if row is None else row[0]

    def calendar(self, property_id: UUID, start: date, days: int, *, actor_id: str) -> Json:
        return _json(
            self._one(
                "SELECT app.short_stay_calendar(%s, %s, %s, %s)",
                (property_id, start, days, UUID(actor_id)),
            )
        )

    def price(
        self, property_id: UUID, unit_id: UUID, check_in: date, check_out: date, *, actor_id: str
    ) -> Json:
        return _json(
            self._one(
                "SELECT app.short_stay_price_read(%s, %s, %s, %s, %s)",
                (property_id, unit_id, check_in, check_out, UUID(actor_id)),
            )
        )

    def bookings(self, property_id: UUID, *, actor_id: str) -> list[Json]:
        found = self._one(
            "SELECT app.short_stay_bookings_read(%s, %s)", (property_id, UUID(actor_id))
        )
        if not isinstance(found, list):
            raise ProductUnavailable("Short-stay persistence is unavailable")
        return [_json(item) for item in found]

    def booking(self, property_id: UUID, booking_id: UUID, *, actor_id: str) -> Json:
        return _json(
            self._one(
                "SELECT app.short_stay_booking_read(%s, %s, %s)",
                (property_id, booking_id, UUID(actor_id)),
            )
        )

    def book(self, property_id: UUID, booking: Json, *, actor_id: str) -> UUID:
        made = self._one(
            "SELECT app.make_short_stay_booking(%s, %s, %s, %s)",
            (property_id, Jsonb(booking), UUID(actor_id), uuid4()),
        )
        return UUID(str(made))

    def housekeeping(self, property_id: UUID, day: date, *, actor_id: str) -> Json:
        return _json(
            self._one(
                "SELECT app.short_stay_housekeeping(%s, %s, %s)",
                (property_id, day, UUID(actor_id)),
            )
        )

    def site_calendars(self, property_id: UUID, *, actor_id: str) -> list[Json]:
        found = self._one(
            "SELECT app.booking_site_calendars_read(%s, %s)", (property_id, UUID(actor_id))
        )
        if not isinstance(found, list):
            raise ProductUnavailable("Short-stay persistence is unavailable")
        return [_json(item) for item in found]

    def calendar_feed(self, token: str) -> Json | None:
        found = self._one("SELECT app.booking_site_calendar_feed(%s)", (token,))
        return None if found is None else _json(found)

    def guest(self, property_id: UUID, customer_id: UUID, *, actor_id: str) -> Json:
        return _json(
            self._one(
                "SELECT app.short_stay_guest(%s, %s, %s)",
                (property_id, customer_id, UUID(actor_id)),
            )
        )

    def quotes(self, property_id: UUID, *, actor_id: str) -> list[Json]:
        found = self._one(
            "SELECT app.short_stay_quotes_read(%s, %s)", (property_id, UUID(actor_id))
        )
        if not isinstance(found, list):
            raise ProductUnavailable("Short-stay persistence is unavailable")
        return [_json(item) for item in found]

    def week_report(self, property_id: UUID, start: date, *, actor_id: str) -> Json:
        return _json(
            self._one(
                "SELECT app.short_stay_week_report(%s, %s, %s)",
                (property_id, start, UUID(actor_id)),
            )
        )

    def credits_due(self, property_id: UUID, *, actor_id: str) -> list[Json]:
        found = self._one(
            "SELECT app.short_stay_credits_due(%s, %s)", (property_id, UUID(actor_id))
        )
        if not isinstance(found, list):
            raise ProductUnavailable("Short-stay persistence is unavailable")
        return [_json(item) for item in found]

    def act(
        self, property_id: UUID, action: Action, target: UUID, body: Json, *, actor_id: str
    ) -> Json:
        version = body.pop("version", None)
        return _json(
            self._one(
                ACTION_SQL[action],
                {
                    "p": property_id,
                    "t": target,
                    "v": version,
                    "b": Jsonb(body),
                    "a": UUID(actor_id),
                    "c": uuid4(),
                },
            )
        )


class NewBooking(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    unit_id: Id
    customer_id: Id
    guest_count: Annotated[int, Field(ge=1, le=10)]
    check_in_on: Day
    check_out_on: Day
    source: Literal["WALK_IN", "PHONE", "TELEGRAM", "WEBSITE", "BOOKING_SITE"]
    site_name: SiteText | None = None
    site_reference: SiteText | None = None
    note: Note | None = None


class Version(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Annotated[int, Field(ge=1)]


class CheckIn(Version):
    id_copy_made: bool
    house_rules_signed: bool


class Deposit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["CASH", "CARD_HOLD"]
    # Only the card machine's hold reference; a card number is refused by the database.
    hold_reference: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)] | None
    ) = None
    card_last4: Annotated[str, StringConstraints(pattern=r"^[0-9]{4}$")] | None = None


class RoomCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    note: Note | None = None
    damage: Note | None = None
    damage_usd_cents: Annotated[int, Field(ge=1, le=100_000_000)] | None = None


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    approve: bool
    note: Note | None = None


class Fee(Version):
    kind: Literal["EARLY_CHECK_IN", "LATE_CHECK_OUT"]


class Extend(Version):
    check_out_on: Day


class Finish(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # A skipped clean says why ("do not disturb"); the database refuses one without a note.
    skip: bool = False
    note: Note | None = None


class Cancel(Version):
    reason: Note
    no_show: bool = False


class Credit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    amount_usd_cents: Annotated[int, Field(ge=1, le=100_000_000)]
    note: Note


class SiteCalendar(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # A new link names its Unit; a change names the link and the version the screen read.
    unit_id: Id | None = None
    calendar_id: Id | None = None
    version: Annotated[int, Field(ge=1)] | None = None
    site_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    import_url: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, max_length=2000, pattern=r"^https://[^\s]+$"),
        ]
        | None
    ) = None
    active: bool = True


class LinkLease(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    lease_id: Id


class Discount(Version):
    amount_usd_cents: Annotated[int, Field(ge=1, le=100_000_000)]
    reason: Note


class GuestNote(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    note: Note
    problem_guest: bool = False
    booking_id: Id | None = None


class Complaint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    what: Note
    unit_id: Id | None = None
    noted_on: Day | None = None


class NewQuote(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # A quote names a Customer or just a name and a contact (a Telegram name or a phone).
    unit_id: Id
    customer_id: Id | None = None
    guest_name: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
        | None
    ) = None
    guest_contact: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
        | None
    ) = None
    guest_count: Annotated[int, Field(ge=1, le=10)]
    check_in_on: Day
    check_out_on: Day


def create_short_stays_router(
    resolver: ActorResolver, flow: ShortStayFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/properties/{property_id}/short-stays", tags=["short stays"])

    def envelope(request: Request, data: object) -> Json:
        return {"data": data, "meta": {"request_id": request.state.request_id}}

    def one(property_id: UUID, booking_id: UUID, actor_id: str, request: Request) -> Json:
        try:
            return envelope(request, flow.booking(property_id, booking_id, actor_id=actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.get("/calendar")
    def short_stay_calendar(
        property_id: UUID,
        request: Request,
        response: Response,
        start: Annotated[date, Query(alias="from")],
        days: Annotated[int, Query(ge=1, le=62)] = 14,
    ) -> Json:
        actor = _require(request, resolver, SHORT_STAYS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(
                request, flow.calendar(property_id, start, days, actor_id=actor.actor_id)
            )
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.get("/price")
    def short_stay_price(
        property_id: UUID,
        request: Request,
        response: Response,
        unit_id: UUID,
        check_in_on: date,
        check_out_on: date,
    ) -> Json:
        actor = _require(request, resolver, SHORT_STAYS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(
                request,
                flow.price(
                    property_id, unit_id, check_in_on, check_out_on, actor_id=actor.actor_id
                ),
            )
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.get("/bookings")
    def list_short_stay_bookings(property_id: UUID, request: Request, response: Response) -> Json:
        actor = _require(request, resolver, SHORT_STAYS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.bookings(property_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.get("/bookings/{booking_id}")
    def read_short_stay_booking(
        property_id: UUID, booking_id: UUID, request: Request, response: Response
    ) -> Json:
        actor = _require(request, resolver, SHORT_STAYS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        return one(property_id, booking_id, actor.actor_id, request)

    @router.post("/bookings", status_code=status.HTTP_201_CREATED)
    def make_short_stay_booking(property_id: UUID, booking: NewBooking, request: Request) -> Json:
        actor = _require(request, resolver, SHORT_STAYS_DESK, property_id)
        require_browser_mutation(request, settings)
        body: Json = booking.model_dump(mode="json", exclude_none=True)
        try:
            made = flow.book(property_id, body, actor_id=actor.actor_id)
        except REFUSED as exc:
            raise _http(exc) from exc
        return one(property_id, made, actor.actor_id, request)

    def act(
        request: Request,
        property_id: UUID,
        right: str,
        action: Action,
        target: UUID,
        body: BaseModel | None,
    ) -> Json:
        actor = _require(request, resolver, right, property_id)
        require_browser_mutation(request, settings)
        sent: Json = {} if body is None else body.model_dump(mode="json", exclude_none=True)
        try:
            return envelope(
                request, flow.act(property_id, action, target, sent, actor_id=actor.actor_id)
            )
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.post("/bookings/{booking_id}/bill")
    def bill_short_stay(
        property_id: UUID, booking_id: UUID, body: Version, request: Request
    ) -> Json:
        return act(request, property_id, SHORT_STAYS_DESK, "bill", booking_id, body)

    @router.post("/bookings/{booking_id}/paid-on-site")
    def short_stay_paid_on_site(
        property_id: UUID, booking_id: UUID, body: Version, request: Request
    ) -> Json:
        return act(request, property_id, SHORT_STAYS_DESK, "paid_on_site", booking_id, body)

    @router.post("/bookings/{booking_id}/deposit")
    def take_short_stay_deposit(
        property_id: UUID, booking_id: UUID, body: Deposit, request: Request
    ) -> Json:
        return act(request, property_id, SHORT_STAYS_DESK, "deposit", booking_id, body)

    @router.post("/bookings/{booking_id}/deposit/end")
    def end_short_stay_deposit(property_id: UUID, booking_id: UUID, request: Request) -> Json:
        return act(request, property_id, SHORT_STAYS_DESK, "end_deposit", booking_id, None)

    @router.post("/bookings/{booking_id}/check-in")
    def check_in_short_stay(
        property_id: UUID, booking_id: UUID, body: CheckIn, request: Request
    ) -> Json:
        return act(request, property_id, SHORT_STAYS_DESK, "check_in", booking_id, body)

    @router.post("/bookings/{booking_id}/check-out")
    def check_out_short_stay(
        property_id: UUID, booking_id: UUID, body: Version, request: Request
    ) -> Json:
        return act(request, property_id, SHORT_STAYS_DESK, "check_out", booking_id, body)

    @router.post("/bookings/{booking_id}/room-check")
    def check_short_stay_room(
        property_id: UUID, booking_id: UUID, body: RoomCheck, request: Request
    ) -> Json:
        return act(request, property_id, SHORT_STAYS_HOUSEKEEPING, "room_check", booking_id, body)

    @router.post("/damages/{damage_id}/decision")
    def decide_short_stay_damage(
        property_id: UUID, damage_id: UUID, body: Decision, request: Request
    ) -> Json:
        return act(request, property_id, SHORT_STAYS_APPROVE, "decide", damage_id, body)

    @router.post("/bookings/{booking_id}/fee")
    def add_short_stay_fee(
        property_id: UUID, booking_id: UUID, body: Fee, request: Request
    ) -> Json:
        return act(request, property_id, SHORT_STAYS_DESK, "fee", booking_id, body)

    @router.post("/bookings/{booking_id}/extend")
    def extend_short_stay(
        property_id: UUID, booking_id: UUID, body: Extend, request: Request
    ) -> Json:
        return act(request, property_id, SHORT_STAYS_DESK, "extend", booking_id, body)

    @router.post("/bookings/{booking_id}/cancel")
    def cancel_short_stay(
        property_id: UUID, booking_id: UUID, body: Cancel, request: Request
    ) -> Json:
        return act(request, property_id, SHORT_STAYS_DESK, "cancel", booking_id, body)

    @router.post("/bookings/{booking_id}/credit")
    def give_short_stay_credit(
        property_id: UUID, booking_id: UUID, body: Credit, request: Request
    ) -> Json:
        return act(request, property_id, SHORT_STAYS_CREDIT, "credit", booking_id, body)

    @router.post("/bookings/{booking_id}/credit/end")
    def end_short_stay_credit(property_id: UUID, booking_id: UUID, request: Request) -> Json:
        return act(request, property_id, SHORT_STAYS_CREDIT, "end_credit", booking_id, None)

    @router.get("/credits-due")
    def short_stay_credits_due(property_id: UUID, request: Request, response: Response) -> Json:
        actor = _require(request, resolver, SHORT_STAYS_CREDIT, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.credits_due(property_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.post("/bookings/{booking_id}/lease")
    def link_short_stay_lease(
        property_id: UUID, booking_id: UUID, body: LinkLease, request: Request
    ) -> Json:
        return act(request, property_id, SHORT_STAYS_DESK, "link_lease", booking_id, body)

    @router.post("/bookings/{booking_id}/discount")
    def give_short_stay_discount(
        property_id: UUID, booking_id: UUID, body: Discount, request: Request
    ) -> Json:
        return act(request, property_id, SHORT_STAYS_APPROVE, "discount", booking_id, body)

    @router.post("/bookings/{booking_id}/review")
    def ask_short_stay_review(property_id: UUID, booking_id: UUID, request: Request) -> Json:
        return act(request, property_id, SHORT_STAYS_DESK, "review", booking_id, None)

    @router.get("/guests/{customer_id}")
    def read_short_stay_guest(
        property_id: UUID, customer_id: UUID, request: Request, response: Response
    ) -> Json:
        actor = _require(request, resolver, SHORT_STAYS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.guest(property_id, customer_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.post("/guests/{customer_id}/notes")
    def add_guest_note(
        property_id: UUID, customer_id: UUID, body: GuestNote, request: Request
    ) -> Json:
        return act(request, property_id, SHORT_STAYS_DESK, "guest_note", customer_id, body)

    @router.get("/quotes")
    def short_stay_quotes(property_id: UUID, request: Request, response: Response) -> Json:
        actor = _require(request, resolver, SHORT_STAYS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.quotes(property_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.post("/quotes", status_code=status.HTTP_201_CREATED)
    def make_short_stay_quote(property_id: UUID, body: NewQuote, request: Request) -> Json:
        return act(request, property_id, SHORT_STAYS_DESK, "quote", property_id, body)

    @router.get("/report")
    def short_stay_week_report(
        property_id: UUID,
        request: Request,
        response: Response,
        start: Annotated[date, Query(alias="from")],
    ) -> Json:
        actor = _require(request, resolver, SHORT_STAYS_APPROVE, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.week_report(property_id, start, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.post("/complaints", status_code=status.HTTP_201_CREATED)
    def record_short_stay_complaint(property_id: UUID, body: Complaint, request: Request) -> Json:
        return act(request, property_id, SHORT_STAYS_DESK, "complaint", property_id, body)

    @router.get("/housekeeping")
    def short_stay_housekeeping(
        property_id: UUID, request: Request, response: Response, day: date
    ) -> Json:
        actor = _require(request, resolver, SHORT_STAYS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.housekeeping(property_id, day, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.get("/site-calendars")
    def booking_site_calendars(property_id: UUID, request: Request, response: Response) -> Json:
        actor = _require(request, resolver, SHORT_STAYS_APPROVE, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.site_calendars(property_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.post("/site-calendars")
    def save_booking_site_calendar(property_id: UUID, body: SiteCalendar, request: Request) -> Json:
        if (body.calendar_id is None) == (body.unit_id is None) or (
            body.calendar_id is not None and body.version is None
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A new link names its Unit; a change names the link and its version",
            )
        return act(request, property_id, SHORT_STAYS_APPROVE, "site_calendar", property_id, body)

    @router.post("/housekeeping/{task_id}")
    def finish_housekeeping_task(
        property_id: UUID, task_id: UUID, body: Finish, request: Request
    ) -> Json:
        return act(request, property_id, SHORT_STAYS_HOUSEKEEPING, "finish_task", task_id, body)

    return router


def create_short_stay_feed_router(flow: ShortStayFlow) -> APIRouter:
    """Our calendar for a booking site: no sign-in, the long private token is the key."""
    router = APIRouter(prefix="/api/v1/short-stays", tags=["short stays"])

    @router.get("/ical/{token}.ics", response_class=PlainTextResponse)
    def short_stay_calendar_feed(token: str) -> PlainTextResponse:
        if re.fullmatch(r"[0-9a-f]{64}", token) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            found = flow.calendar_feed(token)
        except REFUSED as exc:
            raise _http(exc) from exc
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        busy = found.get("busy")
        name = f"{found.get('unit_number', '')} {found.get('site_name', '')}".strip()
        return PlainTextResponse(
            write_calendar(name, busy if isinstance(busy, list) else []),
            media_type="text/calendar; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    return router


__all__ = [
    "NewBooking",
    "PostgresShortStayFlow",
    "ShortStayFlow",
    "UnavailableShortStayFlow",
    "create_short_stay_feed_router",
    "create_short_stays_router",
]
