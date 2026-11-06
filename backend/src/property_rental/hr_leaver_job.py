"""HRIS phase 6 step 4: turn off a leaver's app user after the last working day (PR-HR-009).

The billing worker runs this on every pass, after the ledger posting, under its lock. One call to
`app.hr_turn_off_leavers` with the money login turns off, in one transaction, every linked app
user whose employee's last working day has passed; nothing is kept when it fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

import psycopg


@dataclass(frozen=True, slots=True)
class LeaverPassResult:
    turned_off: int


class LeaverPassError(RuntimeError):
    """The leaver pass failed as a whole; no account was changed."""


class LeaverPass(Protocol):
    def run(self, *, as_of: datetime) -> LeaverPassResult: ...


class HrLeaverTurnOffJob:
    def __init__(self, financial_database_url: str, *, property_id: UUID, actor_id: UUID) -> None:
        self._url = financial_database_url
        self._property_id = property_id
        self._actor_id = actor_id

    def run(self, *, as_of: datetime) -> LeaverPassResult:
        if as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        try:
            with psycopg.connect(self._url) as connection:
                row = connection.execute(
                    "SELECT app.hr_turn_off_leavers(%s,%s,%s)",
                    (self._property_id, self._actor_id, as_of),
                ).fetchone()
                connection.commit()
        except psycopg.Error as exc:
            raise LeaverPassError(getattr(exc, "sqlstate", None) or type(exc).__name__) from exc
        if row is None or not isinstance(row[0], dict):
            raise LeaverPassError("The leaver pass returned no result")
        turned_off = row[0].get("turned_off")
        if not isinstance(turned_off, list):
            raise LeaverPassError("The leaver pass returned no list")
        return LeaverPassResult(len(turned_off))
