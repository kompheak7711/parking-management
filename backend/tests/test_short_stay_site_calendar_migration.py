"""Daily and weekly rent: booking-site calendars, read every 15 minutes (migration 316).

A booking site's calendar link is read by the billing worker; each booked range is a site hold
that blocks the nights for every booking except one from that same site. Our own calendar is
offered by a private token with busy dates only.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.short_stay_calendar_sync import CalendarReadError, SiteCalendarSync
from test_invoice_migration import financial_database_url
from test_migrations import _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_short_stay_booking_migration import (
    BOOK,
    BookingDatabase,
    booking,
    refused,
    run,
    short_stay_database,
)

REVISION = "20270606_316"
SAVE = "SELECT app.save_booking_site_calendar(%s, %s::jsonb, %s, NULL)"
LINKS = "SELECT app.booking_site_calendars_read(%s, %s)"
DUE = (
    "SELECT coalesce(jsonb_agg(due.calendar_id), '[]') "
    "FROM app.booking_site_calendars_due(%s, %s, 10) AS due"
)
READ = "SELECT app.record_booking_site_calendar_read(%s, %s, %s, %s, %s, %s::jsonb)"
FEED = "SELECT app.booking_site_calendar_feed(%s)"
CALENDAR = "SELECT app.short_stay_calendar(%s, %s, 14, %s)"
PRICE = "SELECT app.short_stay_price_read(%s, %s, %s, %s, %s)"


@pytest.fixture(scope="module")
def stay_database(migrated_database_url: str) -> Iterator[BookingDatabase]:
    assert migrated_database_url
    with short_stay_database("prm_short_stay_site_calendar") as database:
        yield database


def money_url(db: BookingDatabase) -> str:
    return _url_with_database(financial_database_url(), urlsplit(db.owner_url).path.lstrip("/"))


def event(db: BookingDatabase, uid: str, start: int, nights: int) -> dict[str, Any]:
    first = db.today + timedelta(days=start)
    return {
        "uid": uid,
        "start_on": str(first),
        "end_on": str(first + timedelta(days=nights)),
        "summary": "CLOSED - Not available",
    }


def unit_row(found: dict[str, Any], unit: uuid.UUID) -> dict[str, Any]:
    return next(row for row in found["units"] if row["unit_id"] == str(unit))


def test_migration_316_follows_step_4c() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270605_315"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_a_site_calendar_holds_nights_for_that_site_only(stay_database: BookingDatabase) -> None:
    db = stay_database
    link = {
        "unit_id": str(db.studio),
        "site_name": "Agoda",
        "import_url": "https://agoda.example/ical/1",
    }
    # Only the Owner and the Manager set up links; a link is https.
    refused(db.runtime_url, "42501", SAVE, db.property_id, json.dumps(link), db.staff)
    refused(
        db.runtime_url,
        "22023",
        SAVE,
        db.property_id,
        json.dumps(link | {"import_url": "http://agoda.example"}),
        db.manager,
    )
    saved = run(db.runtime_url, SAVE, db.property_id, json.dumps(link), db.manager)
    assert (saved["site_name"], saved["last_read_at"], saved["version"]) == ("Agoda", None, 1)
    assert len(saved["export_token"]) == 64
    assert "already" in refused(
        db.runtime_url,
        "55000",
        SAVE,
        db.property_id,
        json.dumps(link | {"site_name": "agoda"}),
        db.manager,
    )
    calendar = saved["calendar_id"]
    assert run(money_url(db), DUE, db.property_id, db.manager) == [calendar]

    # The worker reads it: two holds; a bad event is left out.
    events = [
        event(db, "a-1", 10, 3),
        event(db, "a-2", 20, 2),
        {"uid": "bad", "start_on": str(db.today), "end_on": str(db.today)},
    ]
    seen = run(
        money_url(db), READ, db.property_id, calendar, db.manager, True, None, json.dumps(events)
    )
    assert seen == 2
    assert run(money_url(db), DUE, db.property_id, db.manager) == []
    read_back = run(db.runtime_url, LINKS, db.property_id, db.manager)[0]
    assert (read_back["last_read_ok"], read_back["holds"], read_back["version"]) == (True, 2, 2)

    # A walk-in for those nights is refused; the same guest typed in from Agoda is not.
    assert "booked on Agoda" in refused(
        db.runtime_url, "55000", BOOK, db.property_id, booking(db, db.studio, 11, 1), db.staff
    )
    price = run(
        db.runtime_url,
        PRICE,
        db.property_id,
        db.studio,
        db.today + timedelta(days=10),
        db.today + timedelta(days=13),
        db.staff,
    )
    assert [hold["site_name"] for hold in price["site_holds"]] == ["Agoda"]
    shown = unit_row(
        run(db.runtime_url, CALENDAR, db.property_id, db.today + timedelta(days=8), db.staff),
        db.studio,
    )
    assert [(hold["start_on"], hold["clash"]) for hold in shown["site_holds"]] == [
        (str(db.today + timedelta(days=10)), False),
        (str(db.today + timedelta(days=20)), False),
    ]
    run(
        db.runtime_url,
        BOOK,
        db.property_id,
        booking(
            db, db.studio, 10, 3, source="BOOKING_SITE", site_name="Agoda", site_reference="A-77"
        ),
        db.staff,
    )
    # Once typed in, the hold is that booking and no longer shows on its own.
    shown = unit_row(
        run(db.runtime_url, CALENDAR, db.property_id, db.today + timedelta(days=8), db.staff),
        db.studio,
    )
    assert [hold["start_on"] for hold in shown["site_holds"]] == [
        str(db.today + timedelta(days=20))
    ]

    # A failed read keeps the holds; a read without the second range marks it gone.
    run(money_url(db), READ, db.property_id, calendar, db.manager, False, "HTTP 503", "[]")
    failed = run(db.runtime_url, LINKS, db.property_id, db.manager)[0]
    assert (failed["last_read_ok"], failed["last_error"], failed["holds"]) == (False, "HTTP 503", 2)
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "UPDATE app.booking_site_calendars SET version = version + 1, "
            "last_read_at = last_read_at - interval '1 hour' WHERE id = %s",
            (calendar,),
        )
    assert run(money_url(db), DUE, db.property_id, db.manager) == [calendar]
    run(
        money_url(db),
        READ,
        db.property_id,
        calendar,
        db.manager,
        True,
        None,
        json.dumps(events[:1]),
    )
    assert run(db.runtime_url, LINKS, db.property_id, db.manager)[0]["holds"] == 1
    run(db.runtime_url, BOOK, db.property_id, booking(db, db.studio, 20, 2), db.staff)
    with psycopg.connect(db.owner_url) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute("DELETE FROM app.booking_site_holds")


def test_our_calendar_shows_busy_nights_by_its_token(stay_database: BookingDatabase) -> None:
    db = stay_database
    airbnb = run(
        db.runtime_url,
        SAVE,
        db.property_id,
        json.dumps({"unit_id": str(db.one_bedroom), "site_name": "Airbnb"}),
        db.manager,
    )
    booking_com = run(
        db.runtime_url,
        SAVE,
        db.property_id,
        json.dumps(
            {
                "unit_id": str(db.one_bedroom),
                "site_name": "Booking.com",
                "import_url": "https://booking.example/ical",
            }
        ),
        db.manager,
    )
    run(
        money_url(db),
        READ,
        db.property_id,
        booking_com["calendar_id"],
        db.manager,
        True,
        None,
        json.dumps([event(db, "b-1", 40, 2)]),
    )
    run(db.runtime_url, BOOK, db.property_id, booking(db, db.one_bedroom, 30, 2), db.staff)
    feed = run(db.runtime_url, FEED, airbnb["export_token"])
    assert (feed["unit_number"], feed["site_name"]) == ("U503", "Airbnb")
    busy = [(row["start_on"], row["end_on"]) for row in feed["busy"]]
    day = [str(db.today + timedelta(days=n)) for n in range(43)]
    assert busy == [(day[30], day[32]), (day[40], day[42])]
    assert all("guest" not in json.dumps(row).lower() for row in feed["busy"])
    # Booking.com's own holds are not sent back to it.
    own = run(db.runtime_url, FEED, booking_com["export_token"])
    assert [(row["start_on"], row["end_on"]) for row in own["busy"]] == [(day[30], day[32])]
    assert run(db.runtime_url, FEED, "0" * 64) is None
    assert run(db.runtime_url, FEED, "not a token") is None
    # Turned off: no feed, and its holds are gone.
    off = run(
        db.runtime_url,
        SAVE,
        db.property_id,
        json.dumps(
            {
                "calendar_id": booking_com["calendar_id"],
                "version": next(
                    link["version"]
                    for link in run(db.runtime_url, LINKS, db.property_id, db.manager)
                    if link["calendar_id"] == booking_com["calendar_id"]
                ),
                "site_name": "Booking.com",
                "import_url": "https://booking.example/ical",
                "active": False,
            }
        ),
        db.manager,
    )
    assert (off["active"], off["holds"]) == (False, 0)
    assert run(db.runtime_url, FEED, booking_com["export_token"]) is None
    refused(
        db.runtime_url,
        "40001",
        SAVE,
        db.property_id,
        json.dumps({"calendar_id": off["calendar_id"], "version": 1, "site_name": "Booking.com"}),
        db.manager,
    )


def test_the_worker_pass_reads_each_due_link(stay_database: BookingDatabase) -> None:
    db = stay_database
    good = run(
        db.runtime_url,
        SAVE,
        db.property_id,
        json.dumps(
            {
                "unit_id": str(db.two_bedroom),
                "site_name": "Agoda",
                "import_url": "https://a.example/2",
            }
        ),
        db.manager,
    )
    bad = run(
        db.runtime_url,
        SAVE,
        db.property_id,
        json.dumps(
            {
                "unit_id": str(db.two_bedroom),
                "site_name": "Airbnb",
                "import_url": "https://b.example/2",
            }
        ),
        db.manager,
    )
    first = db.today + timedelta(days=5)

    def fetch(url: str) -> str:
        if url == "https://b.example/2":
            raise CalendarReadError("The site answered 404")
        return (
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:x-1\r\n"
            f"DTSTART;VALUE=DATE:{first:%Y%m%d}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )

    sync = SiteCalendarSync(
        money_url(db), property_id=db.property_id, actor_id=db.manager, fetch=fetch
    )
    result = sync.run()
    assert (result.read, result.failed) == (1, 1)
    links = {
        link["calendar_id"]: link for link in run(db.runtime_url, LINKS, db.property_id, db.manager)
    }
    assert (links[good["calendar_id"]]["holds"], links[good["calendar_id"]]["last_read_ok"]) == (
        1,
        True,
    )
    assert links[bad["calendar_id"]]["last_error"] == "The site answered 404"
    # Read again only after 15 minutes.
    assert (sync.run().read, sync.run().failed) == (0, 0)
