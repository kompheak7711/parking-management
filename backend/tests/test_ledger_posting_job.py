"""The General Ledger posting job of the billing worker (phase 6 step 2)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from property_rental.billing_worker import BillingWorkerResult, run_bounded_loop
from property_rental.ledger_posting_job import (
    LedgerPostingError,
    LedgerPostingJob,
    LedgerPostingResult,
)


class Result:
    def __init__(self, row: tuple[int, int] | None) -> None:
        self.row = row

    def fetchone(self) -> tuple[int, int] | None:
        return self.row


class Connection:
    def __init__(self, batches: list[tuple[int, int] | Exception]) -> None:
        self.batches = batches
        self.asked: list[tuple[object, ...]] = []
        self.commits = 0
        self.years_kept = 0
        self.month_ends = 0

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, parameters: tuple[object, ...]) -> Result:
        if "app.gl_keep_years_open" in sql:
            self.years_kept += 1
            return Result(None)
        if "app.gl_month_end_work" in sql:
            self.month_ends += 1
            return Result((2, 0))
        assert "app.gl_post_app_records" in sql
        self.asked.append(parameters)
        batch = self.batches.pop(0)
        if isinstance(batch, Exception):
            raise batch
        return Result(batch)

    def commit(self) -> None:
        self.commits += 1


def job_with(
    monkeypatch: pytest.MonkeyPatch, batches: list[tuple[int, int] | Exception], **options: Any
) -> tuple[LedgerPostingJob, Connection]:
    connection = Connection(batches)
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: connection)
    job = LedgerPostingJob("postgresql://unused", property_id=uuid4(), actor_id=uuid4(), **options)
    return job, connection


def test_batches_run_until_one_posts_nothing_new_and_each_batch_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job, connection = job_with(monkeypatch, [(3, 0), (2, 1), (0, 1)], batch=3)
    assert job.run(until=date(2027, 1, 5)) == LedgerPostingResult(5, 1, 2)
    assert [asked[2:] for asked in connection.asked] == [(date(2027, 1, 5), 3)] * 3
    # The year of today is kept open first and the month-end work runs last, each in its own
    # commit.
    assert (connection.years_kept, connection.month_ends, connection.commits) == (1, 1, 5)
    # A short batch means nothing is left.
    job, connection = job_with(monkeypatch, [(2, 0)], batch=3)
    assert job.run(until=date(2027, 1, 5)) == LedgerPostingResult(2, 0, 2)
    assert len(connection.asked) == 1


def test_the_pass_stops_after_its_bound_and_a_database_error_is_one_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job, connection = job_with(monkeypatch, [(1, 0)] * 5, batch=1, max_batches=2)
    assert job.run(until=date(2027, 1, 5)) == LedgerPostingResult(2, 0, 2)
    assert len(connection.asked) == 2
    job, _ = job_with(monkeypatch, [psycopg.errors.InsufficientPrivilege("denied")])
    with pytest.raises(LedgerPostingError, match="42501"):
        job.run(until=date(2027, 1, 5))
    for options in ({"batch": 0}, {"batch": 5001}, {"max_batches": 0}, {"max_batches": 101}):
        with pytest.raises(ValueError):
            LedgerPostingJob(
                "postgresql://unused", property_id=uuid4(), actor_id=uuid4(), **options
            )


def test_the_worker_loop_reports_the_ledger_pass_and_fails_only_when_it_cannot_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Worker:
        def __init__(self, result: BillingWorkerResult) -> None:
            self.result = result

        def run_once(self, *, as_of: datetime | None = None) -> BillingWorkerResult:
            del as_of
            return self.result

    day = date(2027, 1, 5)
    waiting = BillingWorkerResult(day, (), ledger_posting=LedgerPostingResult(4, 2))
    assert run_bounded_loop(Worker(waiting), max_iterations=1, poll_interval_seconds=1)
    broken = BillingWorkerResult(day, (), ledger_posting_error="42501")
    assert not run_bounded_loop(Worker(broken), max_iterations=1, poll_interval_seconds=1)
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "succeeded:0",
        "ledger:posted=4,needs_check=2,month_end=0",
        "succeeded:0",
    ]
    assert captured.err == "ledger:error:42501\n"
