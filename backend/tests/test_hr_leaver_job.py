"""The leaver pass of the billing worker (HRIS phase 6 step 4, PR-HR-009), without a database."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from property_rental.billing_worker import BillingWorkerResult, run_bounded_loop
from property_rental.hr_leaver_job import HrLeaverTurnOffJob, LeaverPassError, LeaverPassResult


class Connection:
    def __init__(self, answer: object) -> None:
        self.answer = answer
        self.asked: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, parameters: tuple[object, ...]) -> Connection:
        if isinstance(self.answer, Exception):
            raise self.answer
        self.asked.append((sql, parameters))
        return self

    def fetchone(self) -> object:
        return self.answer

    def commit(self) -> None:
        self.commits += 1


def job_with(monkeypatch: pytest.MonkeyPatch, answer: object) -> tuple[HrLeaverTurnOffJob, Any]:
    connection = Connection(answer)
    monkeypatch.setattr(
        "property_rental.hr_leaver_job.psycopg.connect", lambda *_a, **_k: connection
    )
    return HrLeaverTurnOffJob("postgresql://unused", property_id=uuid4(), actor_id=uuid4()), (
        connection
    )


def test_the_pass_counts_the_turned_off_users_and_commits_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2027, 5, 3, 1, tzinfo=UTC)
    job, connection = job_with(
        monkeypatch, ({"business_date": "2027-05-03", "turned_off": [{}, {}]},)
    )
    assert job.run(as_of=at) == LeaverPassResult(2)
    assert connection.commits == 1
    assert connection.asked[0][0] == "SELECT app.hr_turn_off_leavers(%s,%s,%s)"
    assert connection.asked[0][1][2] == at
    with pytest.raises(ValueError):
        job.run(as_of=datetime(2027, 5, 3, 1))


def test_a_refusal_or_an_odd_answer_is_one_error(monkeypatch: pytest.MonkeyPatch) -> None:
    at = datetime(2027, 5, 3, 1, tzinfo=UTC)
    refusal = psycopg.errors.InsufficientPrivilege("no")
    for answer, message in (
        (refusal, "42501"),
        (None, "The leaver pass returned no result"),
        (({"turned_off": None},), "The leaver pass returned no list"),
    ):
        job, _ = job_with(monkeypatch, answer)
        with pytest.raises(LeaverPassError, match=message):
            job.run(as_of=at)


def test_the_worker_loop_reports_the_leaver_pass_and_fails_when_it_cannot_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Worker:
        def __init__(self, result: BillingWorkerResult) -> None:
            self.result = result

        def run_once(self, *, as_of: datetime | None = None) -> BillingWorkerResult:
            del as_of
            return self.result

    day = date(2027, 5, 3)
    done = BillingWorkerResult(day, (), leavers=LeaverPassResult(1))
    assert run_bounded_loop(Worker(done), max_iterations=1, poll_interval_seconds=1)
    broken = BillingWorkerResult(day, (), leavers_error="42501")
    assert not run_bounded_loop(Worker(broken), max_iterations=1, poll_interval_seconds=1)
    captured = capsys.readouterr()
    assert captured.out.splitlines() == ["succeeded:0", "leavers:turned_off=1", "succeeded:0"]
    assert captured.err == "leavers:error:42501\n"
