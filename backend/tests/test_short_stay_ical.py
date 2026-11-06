"""Daily and weekly rent step 5a: reading and writing booking-site calendars (iCal text)."""

from __future__ import annotations

import urllib.request
from datetime import UTC, datetime
from typing import Any

import pytest

from property_rental.short_stay_calendar_sync import CalendarReadError, fetch_calendar
from property_rental.short_stay_ical import parse_calendar, write_calendar

AGODA = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Agoda//EN\r\n"
    "BEGIN:VEVENT\r\nUID:agoda-1@agoda.com\r\nDTSTART;VALUE=DATE:20261110\r\n"
    "DTEND;VALUE=DATE:20261113\r\nSUMMARY:CLOSED - Not\r\n  available\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:a-2\r\nDTSTART:20261120T140000Z\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:a-3\r\nDTSTART;VALUE=DATE:20261201\r\nDTEND;VALUE=DATE:20261203\r\n"
    "STATUS:CANCELLED\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:a-4\r\nDTSTART:not a date\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261205\r\nDTEND;VALUE=DATE:20261205\r\n"
    "SUMMARY:Blocked\\, owner\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
)


def test_a_site_calendar_is_read_as_booked_ranges() -> None:
    assert parse_calendar(AGODA) == [
        {
            "uid": "agoda-1@agoda.com",
            "start_on": "2026-11-10",
            "end_on": "2026-11-13",
            "summary": "CLOSED - Not available",
        },
        # A date-time is its own day; no end means one night.
        {"uid": "a-2", "start_on": "2026-11-20", "end_on": "2026-11-21", "summary": None},
        # No UID: one is made from the dates; an end on the start day is one night.
        {
            "uid": "no-uid-2026-12-05-2026-12-06",
            "start_on": "2026-12-05",
            "end_on": "2026-12-06",
            "summary": "Blocked, owner",
        },
    ]
    assert parse_calendar("not a calendar") == []


def test_our_calendar_has_busy_dates_only() -> None:
    text = write_calendar(
        "U501 Agoda",
        [{"uid": "st-1", "start_on": "2026-11-10", "end_on": "2026-11-12"}],
        now=datetime(2026, 11, 5, 5, tzinfo=UTC),
    )
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert "UID:st-1@chetana\r\nDTSTAMP:20261105T050000Z\r\n" in text
    assert "DTSTART;VALUE=DATE:20261110\r\nDTEND;VALUE=DATE:20261112\r\n" in text
    assert parse_calendar(text)[0]["end_on"] == "2026-11-12"


def test_a_link_is_read_over_https_only(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(CalendarReadError, match="https"):
        fetch_calendar("http://agoda.example/ical")

    class Answer:
        status = 200

        def __init__(self, body: bytes) -> None:
            self.body = body

        def read(self, limit: int) -> bytes:
            return self.body[:limit]

        def __enter__(self) -> Answer:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    answers = iter([AGODA.encode(), b"<html>login</html>", b"x" * 2_000_001])

    def urlopen(request: Any, timeout: int) -> Answer:
        assert timeout == 20 and request.full_url.startswith("https://")
        return Answer(next(answers))

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert "agoda-1" in fetch_calendar("https://agoda.example/ical")
    with pytest.raises(CalendarReadError, match="not a calendar"):
        fetch_calendar("https://agoda.example/ical")
    with pytest.raises(CalendarReadError, match="2 MB"):
        fetch_calendar("https://agoda.example/ical")

    def offline(request: Any, timeout: int) -> Answer:
        raise OSError("down")

    monkeypatch.setattr(urllib.request, "urlopen", offline)
    with pytest.raises(CalendarReadError, match="could not be reached"):
        fetch_calendar("https://agoda.example/ical")
