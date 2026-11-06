"""Daily and weekly rent, phase 6 step 5a: read the booking sites' calendars (owner D1).

The billing worker runs this pass on every loop (every 5 minutes by default); the database hands
out only the links not read in the last 15 minutes. Each link is read over https with a short
time limit and a size limit; what it says replaces that link's site holds. A link that cannot be
read keeps its holds and shows its error to the Owner and the Manager.
"""

from __future__ import annotations

import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from property_rental.short_stay_ical import parse_calendar

TIMEOUT_SECONDS = 20
MAX_BYTES = 2_000_000
BATCH = 20
UNREADABLE = "The calendar has an event that cannot be read"

Fetch = Callable[[str], str]


class CalendarReadError(RuntimeError):
    """A calendar link could not be read; the message is shown to the Owner."""


def fetch_calendar(url: str) -> str:
    """Read one calendar link (https only), at most 2 MB."""
    if not url.startswith("https://"):
        raise CalendarReadError("The calendar link starts with https://")
    request = urllib.request.Request(
        url, headers={"User-Agent": "CHETANA-Residence-calendar/1.0", "Accept": "text/calendar"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as answer:
            status = int(getattr(answer, "status", 200))
            if status != 200:
                raise CalendarReadError(f"The site answered {status}")
            body = answer.read(MAX_BYTES + 1)
    except CalendarReadError:
        raise
    except OSError as exc:
        raise CalendarReadError(f"The site could not be reached ({type(exc).__name__})") from exc
    if len(body) > MAX_BYTES:
        raise CalendarReadError("The calendar is larger than 2 MB")
    text: str = bytes(body).decode("utf-8", errors="replace")
    if "BEGIN:VCALENDAR" not in text.upper():
        raise CalendarReadError("The link is not a calendar")
    return text


@dataclass(frozen=True, slots=True)
class SiteCalendarResult:
    read: int
    failed: int


class SiteCalendarPass(Protocol):
    def run(self) -> SiteCalendarResult: ...


class SiteCalendarSync:
    def __init__(
        self,
        financial_database_url: str,
        *,
        property_id: UUID,
        actor_id: UUID,
        fetch: Fetch = fetch_calendar,
        batch: int = BATCH,
    ) -> None:
        self._url = financial_database_url
        self._property_id = property_id
        self._actor_id = actor_id
        self._fetch = fetch
        self._batch = batch

    def run(self) -> SiteCalendarResult:
        with psycopg.connect(self._url) as connection:
            due = connection.execute(
                "SELECT calendar_id, import_url FROM app.booking_site_calendars_due(%s, %s, %s)",
                (self._property_id, self._actor_id, self._batch),
            ).fetchall()
        read = failed = 0
        for calendar_id, import_url in due:
            # The network read happens outside any database transaction.
            try:
                events = parse_calendar(self._fetch(str(import_url)))
                ok, error = True, None
            except CalendarReadError as exc:
                events, ok, error = [], False, str(exc)
            try:
                self._record(calendar_id, ok, error, events)
            except psycopg.Error:
                # The database refused what the file said: keep the holds, show the problem.
                ok = False
                self._record(calendar_id, False, UNREADABLE, [])
            if ok:
                read += 1
            else:
                failed += 1
        return SiteCalendarResult(read, failed)

    def _record(self, calendar_id: object, ok: bool, error: str | None, events: object) -> None:
        with psycopg.connect(self._url) as connection:
            connection.execute(
                "SELECT app.record_booking_site_calendar_read(%s, %s, %s, %s, %s, %s)",
                (self._property_id, calendar_id, self._actor_id, ok, error, Jsonb(events)),
            )


__all__ = [
    "CalendarReadError",
    "SiteCalendarPass",
    "SiteCalendarResult",
    "SiteCalendarSync",
    "fetch_calendar",
]
