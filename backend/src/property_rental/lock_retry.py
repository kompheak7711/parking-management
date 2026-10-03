"""Bounded replay of a whole command after a NOWAIT lock refusal (SQLSTATE 55P03)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

import psycopg

T = TypeVar("T")

LOCK_NOT_AVAILABLE = "55P03"
# Pauses before the second, third and fourth attempt. Each attempt runs in its
# own connection and transaction; the previous one is rolled back and closed
# before the pause, so no lock (and never the Payment source lock) is held
# while waiting.
LOCK_RETRY_PAUSES_SECONDS: tuple[float, ...] = (0.25, 0.5, 1.0)


def _pause(seconds: float) -> None:
    time.sleep(seconds)


def retry_lock_not_available(attempt: Callable[[], T]) -> T:
    """Run ``attempt``; replay it unchanged after each 55P03, at most three times.

    ``attempt`` must be an idempotent replay of the same command (same idempotency
    key and parameters) that opens, uses and closes its own transaction. Any other
    error, or a 55P03 on the last attempt, propagates to the caller unchanged.
    """
    for pause in LOCK_RETRY_PAUSES_SECONDS:
        try:
            return attempt()
        except psycopg.Error as exc:
            if exc.sqlstate != LOCK_NOT_AVAILABLE:
                raise
        _pause(pause)
    return attempt()
