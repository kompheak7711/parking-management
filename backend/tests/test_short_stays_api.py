"""Daily and weekly rent API (phase 6 steps 2 and 3).

Reading the calendar, a price and bookings needs `short_stays.read`; a new booking needs
`short_stays.desk` and the browser mutation checks. The database refusals map to 404, 409 and
422, and a night taken at the same moment by someone else is a 409.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.products_api import Json, ProductConflict, ProductNotFound
from property_rental.settings import Settings
from property_rental.short_stays_api import Action

HEADERS = {
    "Origin": "https://localhost",
    "Cookie": "__Host-prm_csrf=stays-token",
    "X-CSRF-Token": "stays-token",
}


@dataclass
class InMemoryStays:
    property_id: UUID = field(default_factory=uuid4)
    booking_id: UUID = field(default_factory=uuid4)
    taken: bool = False
    calls: list[tuple[str, object]] = field(default_factory=list)

    def _check(self, property_id: UUID, booking_id: UUID | None = None) -> None:
        if property_id != self.property_id or booking_id not in (None, self.booking_id):
            raise ProductNotFound("the booking does not exist")

    def calendar(self, property_id: UUID, start: date, days: int, *, actor_id: str) -> Json:
        self._check(property_id)
        self.calls.append(("calendar", (start, days)))
        return {"from": str(start), "days": days, "units": []}

    def price(
        self, property_id: UUID, unit_id: UUID, check_in: date, check_out: date, *, actor_id: str
    ) -> Json:
        self._check(property_id)
        return {"total_usd_cents": 2900 * (check_out - check_in).days, "blockers": []}

    def bookings(self, property_id: UUID, *, actor_id: str) -> list[Json]:
        self._check(property_id)
        return [{"booking_id": str(self.booking_id)}]

    def booking(self, property_id: UUID, booking_id: UUID, *, actor_id: str) -> Json:
        self._check(property_id, booking_id)
        return {"booking_id": str(self.booking_id), "booking_number": "ST260001"}

    def book(self, property_id: UUID, booking: Json, *, actor_id: str) -> UUID:
        self._check(property_id)
        if self.taken:
            raise ProductConflict("The Unit is already booked on one of these nights")
        self.calls.append(("book", booking))
        return self.booking_id

    def housekeeping(self, property_id: UUID, day: date, *, actor_id: str) -> Json:
        self._check(property_id)
        return {"day": str(day), "tasks": []}

    def site_calendars(self, property_id: UUID, *, actor_id: str) -> list[Json]:
        self._check(property_id)
        return [{"calendar_id": "c-1", "site_name": "Agoda"}]

    def calendar_feed(self, token: str) -> Json | None:
        if token != FEED_TOKEN:
            return None
        return {
            "unit_number": "U501",
            "site_name": "Agoda",
            "busy": [{"uid": "st-1", "start_on": "2026-11-10", "end_on": "2026-11-12"}],
        }

    def guest(self, property_id: UUID, customer_id: UUID, *, actor_id: str) -> Json:
        self._check(property_id)
        if customer_id != self.booking_id:
            raise ProductNotFound("the guest does not exist")
        return {"customer_id": str(customer_id), "stays": [], "notes": []}

    def quotes(self, property_id: UUID, *, actor_id: str) -> list[Json]:
        self._check(property_id)
        return [{"quote_id": "q-1", "quote_number": "SQ260001"}]

    def week_report(self, property_id: UUID, start: date, *, actor_id: str) -> Json:
        self._check(property_id)
        self.calls.append(("week_report", start))
        return {"from": start.isoformat(), "units": []}

    def credits_due(self, property_id: UUID, *, actor_id: str) -> list[Json]:
        self._check(property_id)
        self.calls.append(("credits_due", None))
        return []

    def damage_due(self, property_id: UUID, *, actor_id: str) -> list[Json]:
        self._check(property_id)
        self.calls.append(("damage_due", None))
        return [{"booking_id": str(self.booking_id), "problem_count": 1}]

    def notices(self, property_id: UUID, *, actor_id: str) -> Json:
        self._check(property_id)
        self.calls.append(("notices", None))
        return {"notices": [], "stays": [], "rules": {"days": 90}}

    def act(
        self, property_id: UUID, action: Action, target: UUID, body: Json, *, actor_id: str
    ) -> Json:
        self._check(property_id)
        self.calls.append((action, (target, body)))
        return {"booking_id": str(target), "status": "BOOKED"}


FEED_TOKEN = "ab" * 32


def client(flow: InMemoryStays, *capabilities: str) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    return TestClient(create_app(actor_resolver=lambda _: who, short_stay_flow=flow))


def base(flow: InMemoryStays) -> str:
    return f"/api/v1/properties/{flow.property_id}/short-stays"


def test_reading_needs_short_stays_read() -> None:
    flow = InMemoryStays()
    unit = uuid4()
    for url in (
        f"{base(flow)}/calendar?from=2026-11-10&days=14",
        f"{base(flow)}/price?unit_id={unit}&check_in_on=2026-11-10&check_out_on=2026-11-12",
        f"{base(flow)}/bookings",
        f"{base(flow)}/bookings/{flow.booking_id}",
    ):
        assert client(flow).get(url).status_code == 403
        answer = client(flow, "short_stays.read").get(url)
        assert answer.status_code == 200, url
        assert answer.headers["Cache-Control"] == "private, no-store"
    reader = client(flow, "short_stays.read")
    assert reader.get(f"{base(flow)}/calendar?from=2026-11-10&days=90").status_code == 422
    assert reader.get(f"{base(flow)}/bookings/{uuid4()}").status_code == 404
    price = reader.get(
        f"{base(flow)}/price?unit_id={unit}&check_in_on=2026-11-10&check_out_on=2026-11-13"
    )
    assert price.json()["data"]["total_usd_cents"] == 8700


def test_a_booking_needs_the_desk_right_and_a_valid_form() -> None:
    flow = InMemoryStays()
    body = {
        "unit_id": str(uuid4()),
        "customer_id": str(uuid4()),
        "guest_count": 2,
        "check_in_on": "2026-11-10",
        "check_out_on": "2026-11-12",
        "source": "WALK_IN",
        "note": " Late arrival ",
    }
    url = f"{base(flow)}/bookings"
    assert client(flow, "short_stays.read").post(url, json=body, headers=HEADERS).status_code == 403
    desk = client(flow, "short_stays.read", "short_stays.desk")
    assert desk.post(url, json=body).status_code == 403  # no browser mutation checks
    assert desk.post(url, json=body | {"source": "EMAIL"}, headers=HEADERS).status_code == 422
    assert desk.post(url, json=body | {"guest_count": 11}, headers=HEADERS).status_code == 422
    made = desk.post(url, json=body, headers=HEADERS)
    assert made.status_code == 201 and made.json()["data"]["booking_number"] == "ST260001"
    sent = flow.calls[-1][1]
    assert isinstance(sent, dict)
    assert sent["note"] == "Late arrival" and "site_name" not in sent
    flow.taken = True
    assert desk.post(url, json=body, headers=HEADERS).status_code == 409


def test_each_step_of_a_stay_needs_its_own_right() -> None:
    flow = InMemoryStays()
    booking = f"{base(flow)}/bookings/{flow.booking_id}"
    damage = f"{base(flow)}/damages/{uuid4()}/decision"
    steps = (
        (f"{booking}/bill", {"version": 1}, "short_stays.desk"),
        (f"{booking}/paid-on-site", {"version": 2}, "short_stays.desk"),
        (
            f"{booking}/deposit",
            {"kind": "CARD_HOLD", "hold_reference": "HOLD-1"},
            "short_stays.desk",
        ),
        (
            f"{booking}/check-in",
            {"version": 3, "id_copy_made": True, "house_rules_signed": True},
            "short_stays.desk",
        ),
        (f"{booking}/check-out", {"version": 4}, "short_stays.desk"),
        (
            f"{booking}/room-check",
            {"problems": [{"problem_type_id": str(uuid4()), "description": "Broken lamp"}]},
            "short_stays.housekeeping",
        ),
        # DL-222: a damage charge from before is decided by the person who bills damage.
        (damage, {"approve": True}, "damage_charges.bill"),
        (
            f"{booking}/damage",
            {"charge": True, "description": "Broken lamp", "amount_usd_cents": 8000},
            "damage_charges.bill",
        ),
        (f"{booking}/deposit/end", None, "short_stays.desk"),
        (f"{booking}/fee", {"version": 5, "kind": "LATE_CHECK_OUT"}, "short_stays.desk"),
        (f"{booking}/extend", {"version": 6, "check_out_on": "2026-11-12"}, "short_stays.desk"),
        (
            f"{base(flow)}/housekeeping/{uuid4()}",
            {"skip": True, "note": "Do not disturb"},
            "short_stays.housekeeping",
        ),
        # DL-236: the front desk gives a task to one person.
        (
            f"{base(flow)}/housekeeping/{uuid4()}/assign",
            {"employee_id": str(uuid4())},
            "short_stays.desk",
        ),
        (f"{booking}/cancel", {"version": 7, "reason": "Flight changed"}, "short_stays.desk"),
        (f"{booking}/credit", {"amount_usd_cents": 2000, "note": "Sick"}, "short_stays.credit"),
        (f"{booking}/lease", {"lease_id": str(uuid4())}, "short_stays.desk"),
        (
            f"{booking}/discount",
            {"version": 8, "amount_usd_cents": 500, "reason": "Old friend"},
            "short_stays.approve",
        ),
        (f"{booking}/review", None, "short_stays.desk"),
        (
            f"{base(flow)}/guests/{flow.booking_id}/notes",
            {"note": "Quiet guest", "problem_guest": False},
            "short_stays.desk",
        ),
    )
    for url, body, right in steps:
        others = {
            "short_stays.read",
            "short_stays.desk",
            "short_stays.housekeeping",
            "short_stays.approve",
            "short_stays.credit",
            "damage_charges.bill",
        } - {right}
        assert client(flow, *others).post(url, json=body, headers=HEADERS).status_code == 403, url
        answer = client(flow, right).post(url, json=body, headers=HEADERS)
        assert answer.status_code == 200, url
        assert client(flow, right).post(url, json=body).status_code == 403  # no CSRF
    actions = [call[0] for call in flow.calls]
    assert actions == [
        "bill",
        "paid_on_site",
        "deposit",
        "check_in",
        "check_out",
        "room_check",
        "decide",
        "damage",
        "end_deposit",
        "fee",
        "extend",
        "finish_task",
        "assign_task",
        "cancel",
        "credit",
        "link_lease",
        "discount",
        "review",
        "guest_note",
    ]
    assert flow.calls[-3][1] == (
        flow.booking_id,
        {"version": 8, "amount_usd_cents": 500, "reason": "Old friend"},
    )
    desk = client(flow, "short_stays.desk")
    # A card number never reaches the database as last 4 digits; unknown fields are refused.
    for wrong in (
        {"kind": "CARD_HOLD", "card_last4": "41111"},
        {"kind": "CHEQUE"},
        {"kind": "CASH", "card_number": "4111"},
    ):
        assert desk.post(f"{booking}/deposit", json=wrong, headers=HEADERS).status_code == 422
    assert desk.post(f"{booking}/check-in", json={"version": 3}, headers=HEADERS).status_code == 422
    # DL-236: a task is given to a person by id, or to nobody; nothing else is sent.
    assign = f"{base(flow)}/housekeeping/{uuid4()}/assign"
    assert desk.post(assign, json={"employee_id": "Sokha"}, headers=HEADERS).status_code == 422
    assert desk.post(assign, json={"name": "Sokha"}, headers=HEADERS).status_code == 422
    assert desk.post(assign, json={"employee_id": None}, headers=HEADERS).status_code == 200
    action, sent_assign = flow.calls[-1]
    assert action == "assign_task" and isinstance(sent_assign, tuple) and sent_assign[1] == {}
    # DL-222: the room check reports problems, never a cost.
    cleaner = client(flow, "short_stays.housekeeping")
    for wrong_check in (
        {"damage": "Broken lamp", "damage_usd_cents": 8000},
        {"problems": [{"description": "No type"}]},
        {"problems": [{"problem_type_id": str(uuid4()), "description": "Lamp", "cost": 1}]},
    ):
        answer = cleaner.post(f"{booking}/room-check", json=wrong_check, headers=HEADERS)
        assert answer.status_code == 422, wrong_check
    biller = client(flow, "damage_charges.bill")
    for wrong_charge in (
        {"charge": True, "description": "Lamp"},
        {"charge": True, "amount_usd_cents": 8000},
        {"charge": False, "amount_usd_cents": 8000},
        {"charge": False, "description": "Lamp"},
        {"charge": True, "description": "Lamp", "amount_usd_cents": 0},
    ):
        answer = biller.post(f"{booking}/damage", json=wrong_charge, headers=HEADERS)
        assert answer.status_code == 422, wrong_charge
    no_charge = biller.post(
        f"{booking}/damage", json={"charge": False, "note": "Wear"}, headers=HEADERS
    )
    assert no_charge.status_code == 200
    assert flow.calls[-1] == ("damage", (flow.booking_id, {"charge": False, "note": "Wear"}))
    assert desk.post(f"{booking}/cancel", json={"version": 7}, headers=HEADERS).status_code == 422
    approver = client(flow, "short_stays.approve")
    for wrong_discount in (
        {"version": 8, "amount_usd_cents": 500},
        {"version": 8, "amount_usd_cents": 0, "reason": "Free"},
        {"amount_usd_cents": 500, "reason": "No version"},
    ):
        answer = approver.post(f"{booking}/discount", json=wrong_discount, headers=HEADERS)
        assert answer.status_code == 422, wrong_discount
    for wrong_fee in ({"version": 5, "kind": "PARKING"}, {"kind": "LATE_CHECK_OUT"}):
        assert desk.post(f"{booking}/fee", json=wrong_fee, headers=HEADERS).status_code == 422
    assert (
        desk.post(
            f"{booking}/extend", json={"version": 6, "check_out_on": "soon"}, headers=HEADERS
        ).status_code
        == 422
    )


def test_the_cleaning_list_of_a_day_needs_the_read_right() -> None:
    flow = InMemoryStays()
    url = f"{base(flow)}/housekeeping?day=2026-11-05"
    assert client(flow, "short_stays.housekeeping").get(url).status_code == 403
    answer = client(flow, "short_stays.read").get(url)
    assert answer.status_code == 200
    assert answer.json()["data"] == {"day": "2026-11-05", "tasks": []}
    assert answer.headers["Cache-Control"] == "private, no-store"


def test_booking_site_links_need_the_approve_right() -> None:
    flow = InMemoryStays()
    url = f"{base(flow)}/site-calendars"
    assert client(flow, "short_stays.read", "short_stays.desk").get(url).status_code == 403
    approver = client(flow, "short_stays.approve")
    listed = approver.get(url)
    assert listed.status_code == 200 and listed.headers["Cache-Control"] == "private, no-store"
    new = {"unit_id": str(uuid4()), "site_name": " Agoda ", "import_url": "https://a.example/1"}
    desk = client(flow, "short_stays.desk")
    assert desk.post(url, json=new, headers=HEADERS).status_code == 403
    assert approver.post(url, json=new, headers=HEADERS).status_code == 200
    sent = new | {"site_name": "Agoda", "active": True}
    assert flow.calls[-1] == ("site_calendar", (flow.property_id, sent))
    change = {"calendar_id": str(uuid4()), "version": 3, "site_name": "Agoda", "active": False}
    assert approver.post(url, json=change, headers=HEADERS).status_code == 200
    for wrong in (
        new | {"import_url": "http://a.example/1"},
        {"site_name": "Agoda"},
        new | {"calendar_id": str(uuid4()), "version": 1},
        change | {"version": None},
    ):
        assert approver.post(url, json=wrong, headers=HEADERS).status_code == 422, wrong


def test_our_calendar_is_read_by_its_token_without_a_sign_in() -> None:
    flow = InMemoryStays()
    # Off unless the owner opens it: the app stays office-only.
    closed = TestClient(create_app(short_stay_flow=flow))
    assert closed.get(f"/api/v1/short-stays/ical/{FEED_TOKEN}.ics").status_code == 404
    opened = Settings(short_stay_public_calendar=True)
    reader = TestClient(create_app(settings=opened, short_stay_flow=flow))
    answer = reader.get(f"/api/v1/short-stays/ical/{FEED_TOKEN}.ics")
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("text/calendar")
    assert "DTSTART;VALUE=DATE:20261110\r\nDTEND;VALUE=DATE:20261112" in answer.text
    assert "SUMMARY:Not available" in answer.text
    assert reader.get(f"/api/v1/short-stays/ical/{'cd' * 32}.ics").status_code == 404
    assert reader.get("/api/v1/short-stays/ical/short.ics").status_code == 404


def test_quotes_and_a_guests_history() -> None:
    flow = InMemoryStays()
    url = f"{base(flow)}/quotes"
    assert client(flow, "short_stays.desk").get(url).status_code == 403
    listed = client(flow, "short_stays.read").get(url)
    assert listed.status_code == 200 and listed.headers["Cache-Control"] == "private, no-store"
    assert listed.json()["data"][0]["quote_number"] == "SQ260001"
    quote = {
        "unit_id": str(uuid4()),
        "guest_name": " Sok Chenda ",
        "guest_contact": "@chenda",
        "guest_count": 2,
        "check_in_on": "2026-11-20",
        "check_out_on": "2026-11-23",
    }
    assert (
        client(flow, "short_stays.read").post(url, json=quote, headers=HEADERS).status_code == 403
    )
    made = client(flow, "short_stays.desk").post(url, json=quote, headers=HEADERS)
    assert made.status_code == 201
    assert flow.calls[-1] == ("quote", (flow.property_id, quote | {"guest_name": "Sok Chenda"}))
    wrong = quote | {"guest_count": 11}
    assert (
        client(flow, "short_stays.desk").post(url, json=wrong, headers=HEADERS).status_code == 422
    )
    guest = f"{base(flow)}/guests/{flow.booking_id}"
    assert client(flow, "short_stays.desk").get(guest).status_code == 403
    found = client(flow, "short_stays.read").get(guest)
    assert found.status_code == 200 and found.json()["data"]["notes"] == []
    assert client(flow, "short_stays.read").get(f"{base(flow)}/guests/{uuid4()}").status_code == 404


def test_an_unused_credit_ends_with_the_credit_right() -> None:
    flow = InMemoryStays()
    due = f"{base(flow)}/credits-due"
    assert client(flow, "short_stays.desk", "short_stays.approve").get(due).status_code == 403
    answer = client(flow, "short_stays.credit").get(due)
    assert answer.status_code == 200 and answer.headers["Cache-Control"] == "private, no-store"
    assert answer.json()["data"] == []
    end = f"{base(flow)}/bookings/{flow.booking_id}/credit/end"
    assert client(flow, "short_stays.desk").post(end, headers=HEADERS).status_code == 403
    assert client(flow, "short_stays.credit").post(end, headers=HEADERS).status_code == 200
    assert flow.calls[-1][0] == "end_credit"


def test_stays_waiting_for_a_damage_decision_need_the_billing_right() -> None:
    flow = InMemoryStays()
    due = f"{base(flow)}/damage-due"
    for rights in (("short_stays.approve",), ("short_stays.housekeeping", "short_stays.desk")):
        assert client(flow, *rights).get(due).status_code == 403
    answer = client(flow, "damage_charges.bill").get(due)
    assert answer.status_code == 200 and answer.headers["Cache-Control"] == "private, no-store"
    assert answer.json()["data"] == [{"booking_id": str(flow.booking_id), "problem_count": 1}]
    assert flow.calls[-1] == ("damage_due", None)


def test_the_weekly_report_needs_the_approve_right_and_a_complaint_the_desk() -> None:
    flow = InMemoryStays()
    url = f"{base(flow)}/report?from=2026-11-02"
    assert client(flow, "short_stays.read", "short_stays.desk").get(url).status_code == 403
    answer = client(flow, "short_stays.approve").get(url)
    assert answer.status_code == 200 and answer.headers["Cache-Control"] == "private, no-store"
    assert flow.calls[-1][0] == "week_report"
    assert flow.calls[-1][1] == date(2026, 11, 2)
    assert client(flow, "short_stays.approve").get(f"{base(flow)}/report").status_code == 422
    complaints = f"{base(flow)}/complaints"
    body = {"what": " Noise after midnight ", "noted_on": "2026-11-04"}
    assert (
        client(flow, "short_stays.approve").post(complaints, json=body, headers=HEADERS).status_code
        == 403
    )
    made = client(flow, "short_stays.desk").post(complaints, json=body, headers=HEADERS)
    assert made.status_code == 201
    assert flow.calls[-1] == (
        "complaint",
        (flow.property_id, {"what": "Noise after midnight", "noted_on": "2026-11-04"}),
    )
    assert (
        client(flow, "short_stays.desk")
        .post(complaints, json={"what": ""}, headers=HEADERS)
        .status_code
        == 422
    )


def test_guest_notices_read_with_the_read_right_and_warnings_need_the_desk() -> None:
    # DL-238: the short-stay tab of the Notices page, a house-rule warning, a notice told.
    flow = InMemoryStays()
    page = f"{base(flow)}/notices"
    assert client(flow).get(page).status_code == 403
    answer = client(flow, "short_stays.read").get(page)
    assert answer.status_code == 200 and answer.headers["Cache-Control"] == "private, no-store"
    assert answer.json()["data"]["rules"] == {"days": 90}
    warn = f"{base(flow)}/bookings/{flow.booking_id}/warning"
    body = {"reason": " Loud music after 22:00. "}
    reader = client(flow, "short_stays.read")
    assert reader.post(warn, json=body, headers=HEADERS).status_code == 403
    desk = client(flow, "short_stays.desk")
    assert desk.post(warn, json=body).status_code == 403  # no browser mutation checks
    for wrong in ({}, {"reason": "   "}, {"reason": "x" * 501}, body | {"number": 2}):
        assert desk.post(warn, json=wrong, headers=HEADERS).status_code == 422
    assert desk.post(warn, json=body, headers=HEADERS).status_code == 200
    assert flow.calls[-1] == (
        "warn_guest",
        (flow.booking_id, {"reason": "Loud music after 22:00."}),
    )
    notice = uuid4()
    told = f"{base(flow)}/notices/{notice}/told"
    assert reader.post(told, headers=HEADERS).status_code == 403
    assert desk.post(told, headers=HEADERS).status_code == 200
    assert flow.calls[-1] == ("notice_told", (notice, {}))
