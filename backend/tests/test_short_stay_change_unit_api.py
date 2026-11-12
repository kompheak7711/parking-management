"""Change Unit API (DL-224): the Units a booked stay can move to, the move, and the special
discount after a move.

Reading the Units needs `short_stays.read`; the move needs `short_stays.desk`, a Unit and a
reason; the special discount needs `short_stays.approve`, an amount and a reason. Both changes
carry the booking version the screen read and pass the browser mutation checks.
"""

from __future__ import annotations

from uuid import uuid4

from test_short_stays_api import HEADERS, InMemoryStays, base, client

RIGHTS = {
    "short_stays.read",
    "short_stays.desk",
    "short_stays.housekeeping",
    "short_stays.approve",
    "short_stays.credit",
}


def test_the_units_a_stay_can_move_to_need_the_read_right() -> None:
    flow = InMemoryStays()
    url = f"{base(flow)}/bookings/{flow.booking_id}/units"
    assert client(flow, "short_stays.housekeeping").get(url).status_code == 403
    answer = client(flow, "short_stays.read").get(url)
    assert answer.status_code == 200, answer.text
    assert answer.headers["Cache-Control"] == "private, no-store"
    assert flow.calls == [("move_units", (flow.booking_id, {}))]
    unknown = client(flow, "short_stays.read").get(f"{base(flow)}/bookings/not-an-id/units")
    assert unknown.status_code == 422


def test_change_unit_needs_the_front_desk_right_a_unit_and_a_reason() -> None:
    flow = InMemoryStays()
    url = f"{base(flow)}/bookings/{flow.booking_id}/unit"
    unit = str(uuid4())
    body = {"version": 3, "unit_id": unit, "reason": "  A Lease takes the Unit the guest booked "}
    others = RIGHTS - {"short_stays.desk"}
    assert client(flow, *others).post(url, json=body, headers=HEADERS).status_code == 403
    desk = client(flow, "short_stays.desk")
    assert desk.post(url, json=body).status_code == 403  # no CSRF
    assert flow.calls == []
    answer = desk.post(url, json=body, headers=HEADERS)
    assert answer.status_code == 200, answer.text
    assert flow.calls == [
        (
            "change_unit",
            (
                flow.booking_id,
                {
                    "version": 3,
                    "unit_id": unit,
                    "reason": "A Lease takes the Unit the guest booked",
                },
            ),
        )
    ]
    for wrong in (
        {"version": 3, "unit_id": unit},
        {"version": 3, "unit_id": unit, "reason": "   "},
        {"version": 3, "unit_id": unit, "reason": "x" * 501},
        {"version": 3, "reason": "No Unit"},
        {"version": 3, "unit_id": "U505", "reason": "Not an id"},
        {"unit_id": unit, "reason": "No version"},
        {"version": 3, "unit_id": unit, "reason": "A new price", "total_usd_cents": 100},
    ):
        assert desk.post(url, json=wrong, headers=HEADERS).status_code == 422, wrong
    assert len(flow.calls) == 1


def test_the_special_discount_after_a_move_needs_the_approve_right() -> None:
    flow = InMemoryStays()
    url = f"{base(flow)}/bookings/{flow.booking_id}/move-discount"
    body = {"version": 4, "amount_usd_cents": 1000, "reason": "A smaller Unit than booked"}
    others = RIGHTS - {"short_stays.approve"}
    assert client(flow, *others).post(url, json=body, headers=HEADERS).status_code == 403
    approver = client(flow, "short_stays.approve")
    assert approver.post(url, json=body).status_code == 403  # no CSRF
    answer = approver.post(url, json=body, headers=HEADERS)
    assert answer.status_code == 200, answer.text
    assert flow.calls == [("move_discount", (flow.booking_id, body))]
    for wrong in (
        {"version": 4, "amount_usd_cents": 1000},
        {"version": 4, "amount_usd_cents": 0, "reason": "Free"},
        {"version": 4, "amount_usd_cents": 10.5, "reason": "Not whole cents"},
        {"amount_usd_cents": 1000, "reason": "No version"},
    ):
        assert approver.post(url, json=wrong, headers=HEADERS).status_code == 422, wrong
    assert len(flow.calls) == 1
