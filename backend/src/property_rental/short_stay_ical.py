"""Daily and weekly rent, phase 6 step 5a: booking-site calendars as iCal text (RFC 5545).

Booking.com, Agoda and Airbnb give each room a calendar link: a plain-text file of VEVENT
blocks, one per booked range. Only the dates and the UID matter; a date-time is read as its
own day. Our calendar for a site is written the same way, with busy ranges only.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import TypedDict


class SiteEvent(TypedDict):
    uid: str
    start_on: str
    end_on: str
    summary: str | None


MAX_EVENTS = 5000


def _unfolded(text: str) -> list[str]:
    """Join folded lines: a line that starts with a space or a tab goes on the one before."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def _day(value: str) -> date | None:
    digits = value.strip()[:8]
    if len(digits) != 8 or not digits.isdigit():
        return None
    try:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None


def _unescape(value: str) -> str:
    return (
        value.replace("\\n", " ")
        .replace("\\N", " ")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
        .strip()
    )


def parse_calendar(text: str) -> list[SiteEvent]:
    """The booked ranges of a calendar file; an event without a readable start is left out."""
    events: list[SiteEvent] = []
    current: dict[str, str] | None = None
    for line in _unfolded(text):
        name, _, value = line.partition(":")
        key = name.split(";", 1)[0].strip().upper()
        if key == "BEGIN" and value.strip().upper() == "VEVENT":
            current = {}
        elif key == "END" and value.strip().upper() == "VEVENT":
            if current is not None:
                found = _event(current)
                if found is not None:
                    events.append(found)
                    if len(events) >= MAX_EVENTS:
                        break
            current = None
        elif current is not None and key in ("UID", "DTSTART", "DTEND", "SUMMARY", "STATUS"):
            current.setdefault(key, value)
    return events


def _event(fields: Mapping[str, str]) -> SiteEvent | None:
    if fields.get("STATUS", "").strip().upper() == "CANCELLED":
        return None
    start = _day(fields.get("DTSTART", ""))
    if start is None:
        return None
    end = _day(fields.get("DTEND", "")) or start + timedelta(days=1)
    if end <= start:
        end = start + timedelta(days=1)
    uid = fields.get("UID", "").strip() or f"no-uid-{start.isoformat()}-{end.isoformat()}"
    summary = _unescape(fields.get("SUMMARY", ""))[:200] or None
    return {
        "uid": uid[:300],
        "start_on": start.isoformat(),
        "end_on": end.isoformat(),
        "summary": summary,
    }


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", " ")


def _compact(day: str) -> str:
    return date.fromisoformat(day).strftime("%Y%m%d")


def write_calendar(
    name: str, busy: Iterable[Mapping[str, object]], *, now: datetime | None = None
) -> str:
    """Our calendar for one site: each busy range is one all-day event, never a guest's name."""
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//CHETANA Residence//Short stays//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
    ]
    for row in busy:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{_escape(str(row['uid']))}@chetana",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{_compact(str(row['start_on']))}",
            f"DTEND;VALUE=DATE:{_compact(str(row['end_on']))}",
            "SUMMARY:Not available",
            "TRANSP:OPAQUE",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


__all__ = ["MAX_EVENTS", "SiteEvent", "parse_calendar", "write_calendar"]
