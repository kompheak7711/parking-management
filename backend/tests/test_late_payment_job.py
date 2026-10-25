"""The automatic late-payment charge pass and its place in the billing worker (V1-056 slice
11g-1; DL-076 answers 1 to 3). The database decisions are covered by
``test_automatic_late_payment_charge_migration.py``; these tests cover the paging, counting,
failure and log rules of the pass with its database calls replaced."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.billing_worker import BillingWorkerResult, run_bounded_loop
from property_rental.late_payment_job import (
    AutomaticLatePaymentChargeJob,
    Connection,
    LateChargePassError,
    LateChargePassResult,
)

AS_OF = datetime(2026, 11, 6, 0, 5, tzinfo=UTC)
# A refusal that also closes the connection, as a lost server does.
LOST = psycopg.OperationalError("server closed the connection")


class ScriptedJob(AutomaticLatePaymentChargeJob):
    """The pass with each database call answered from a script and recorded."""

    def __init__(
        self,
        *,
        window: dict[str, object],
        pages: list[list[UUID]],
        outcomes: dict[UUID, str | psycopg.Error],
        page_size: int = 2,
    ) -> None:
        super().__init__(
            "postgresql://unused", property_id=uuid4(), actor_id=uuid4(), page_size=page_size
        )
        self.window = window
        self.pages = pages
        self.outcomes = outcomes
        self.afters: list[UUID | None] = []
        self.recorded: list[UUID] = []
        self.finished: list[tuple[int, int, int]] = []
        self.connection = SimpleNamespace(closed=False, broken=False)

    @contextmanager
    def _session(self) -> Iterator[Connection]:
        yield cast(Connection, self.connection)

    def _window(self, connection: Connection, as_of: datetime) -> object:
        assert as_of == AS_OF
        return self.window

    def _candidates(
        self, connection: Connection, as_of: datetime, after: UUID | None
    ) -> list[UUID]:
        assert as_of == AS_OF
        self.afters.append(after)
        return self.pages.pop(0)

    def _record(self, connection: Connection, invoice_id: UUID) -> str:
        self.recorded.append(invoice_id)
        outcome = self.outcomes[invoice_id]
        if outcome is LOST:
            self.connection.broken = True
        if isinstance(outcome, psycopg.Error):
            raise outcome
        return outcome

    def _finish(
        self,
        connection: Connection,
        as_of: datetime,
        charged: int,
        no_amount: int,
        skipped: int,
    ) -> None:
        assert as_of == AS_OF
        self.finished.append((charged, no_amount, skipped))


READY = {"business_date": "2026-11-06", "from_date": "2026-11-06", "ready": True, "done": False}


def test_the_pass_pages_by_invoice_counts_each_outcome_and_marks_the_day_done() -> None:
    first, second, third, fourth = (uuid4() for _ in range(4))
    job = ScriptedJob(
        window=READY,
        pages=[[first, second], [third, fourth], []],
        outcomes={
            first: "CHARGED",
            second: "NO_AMOUNT",
            third: "INITIAL_RENT",
            fourth: "ALREADY_ASSESSED",
        },
    )

    result = job.run(as_of=AS_OF)

    assert job.afters == [None, second, fourth]
    assert job.recorded == [first, second, third, fourth]
    # Another pass charged the fourth Invoice first: it is not counted.
    assert result == LateChargePassResult(date(2026, 11, 6), 1, 1, 1, 0, done=True)
    assert job.finished == [(1, 1, 1)]


def test_a_failed_invoice_is_logged_by_code_only_and_leaves_the_day_open(
    capsys: pytest.CaptureFixture[str],
) -> None:
    locked, timed_out, refused, overflow, new, charged = (uuid4() for _ in range(6))
    job = ScriptedJob(
        window=READY,
        pages=[[locked, timed_out, refused, overflow, new, charged]],
        outcomes={
            locked: psycopg.errors.LockNotAvailable("row is locked"),
            timed_out: psycopg.errors.QueryCanceled("statement timeout"),
            refused: psycopg.errors.CheckViolation("invalid"),
            overflow: psycopg.errors.NumericValueOutOfRange("out of range"),
            new: "SOME_LATER_OUTCOME",
            charged: "CHARGED",
        },
        page_size=9,
    )

    result = job.run(as_of=AS_OF)

    assert job.recorded == [locked, timed_out, refused, overflow, new, charged]
    # An outcome this code does not know is a failure: the day must not be marked done past it.
    assert result == LateChargePassResult(date(2026, 11, 6), charged=1, failed=5, done=False)
    assert job.finished == []
    error = capsys.readouterr().err
    assert error.splitlines() == [
        "late_charge_failed:55P03",
        "late_charge_failed:57014",
        "late_charge_failed:23514",
        "late_charge_failed:22003",
        "late_charge_failed:unknown_outcome",
    ]
    assert str(locked) not in error


def test_a_pass_far_behind_says_so_in_the_log(capsys: pytest.CaptureFixture[str]) -> None:
    job = ScriptedJob(window={**READY, "from_date": "2026-11-01"}, pages=[[]], outcomes={})

    assert job.run(as_of=AS_OF) == LateChargePassResult(date(2026, 11, 6), done=True)
    assert capsys.readouterr().err == "late_charge_catch_up_days:5\n"


@pytest.mark.parametrize(
    ("ready", "done"),
    [(False, False), (True, True)],
    ids=["charge moment not settled", "day already done"],
)
def test_a_day_that_is_not_ready_or_already_done_reads_no_invoice(ready: bool, done: bool) -> None:
    job = ScriptedJob(window={**READY, "ready": ready, "done": done}, pages=[], outcomes={})

    result = job.run(as_of=AS_OF)

    assert result == LateChargePassResult(date(2026, 11, 6), done=done)
    assert job.afters == [] and job.finished == []


def test_the_pass_needs_an_aware_instant_and_a_bounded_page() -> None:
    job = ScriptedJob(window=READY, pages=[], outcomes={})
    with pytest.raises(ValueError, match="timezone-aware"):
        job.run(as_of=datetime(2026, 11, 6, 0, 5))
    for page_size in (0, 1001):
        with pytest.raises(ValueError, match="page_size"):
            AutomaticLatePaymentChargeJob(
                "postgresql://unused", property_id=uuid4(), actor_id=uuid4(), page_size=page_size
            )


def test_the_worker_loop_reports_the_late_charge_pass_and_fails_on_a_failed_invoice(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Worker:
        def __init__(self, late: LateChargePassResult | None) -> None:
            self.late = late

        def run_once(self, *, as_of: datetime | None = None) -> BillingWorkerResult:
            del as_of
            return BillingWorkerResult(date(2026, 11, 6), (), self.late)

    clean = LateChargePassResult(date(2026, 11, 6), charged=2, no_amount=3, done=True)
    assert run_bounded_loop(Worker(clean), max_iterations=1, poll_interval_seconds=1)
    failed = LateChargePassResult(date(2026, 11, 6), charged=1, failed=1)
    assert not run_bounded_loop(Worker(failed), max_iterations=1, poll_interval_seconds=1)
    assert run_bounded_loop(Worker(None), max_iterations=1, poll_interval_seconds=1)
    assert capsys.readouterr().out.splitlines() == [
        "succeeded:0",
        "late_charges:charged=2,no_amount=3,skipped=0,failed=0,done=True",
        "succeeded:0",
        "late_charges:charged=1,no_amount=0,skipped=0,failed=1,done=False",
        "succeeded:0",
    ]


def test_a_lost_connection_stops_the_pass_instead_of_counting_a_failure() -> None:
    lost, later = uuid4(), uuid4()
    job = ScriptedJob(
        window=READY,
        pages=[[lost, later]],
        outcomes={lost: LOST, later: "CHARGED"},
        page_size=5,
    )

    with pytest.raises(psycopg.OperationalError):
        job.run(as_of=AS_OF)
    assert job.recorded == [lost]
    assert job.finished == []


def test_the_worker_loop_fails_and_logs_only_the_code_when_the_pass_cannot_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Worker:
        def run_once(self, *, as_of: datetime | None = None) -> BillingWorkerResult:
            del as_of
            return BillingWorkerResult(date(2026, 11, 6), (), None, "55P03")

    assert not run_bounded_loop(Worker(), max_iterations=1, poll_interval_seconds=1)
    captured = capsys.readouterr()
    assert captured.out.splitlines() == ["succeeded:0"]
    assert captured.err == "late_charges:error:55P03\n"


@pytest.mark.parametrize(
    "error",
    [
        psycopg.errors.InsufficientPrivilege("needs the billing service"),
        psycopg.errors.InvalidParameterValue("invalid instant"),
    ],
    ids=["no privilege", "bad argument"],
)
def test_a_refusal_every_invoice_would_get_stops_the_pass(error: psycopg.Error) -> None:
    first, later = uuid4(), uuid4()
    job = ScriptedJob(
        window=READY, pages=[[first, later]], outcomes={first: error, later: "CHARGED"}, page_size=5
    )

    with pytest.raises(type(error)):
        job.run(as_of=AS_OF)
    assert job.recorded == [first]
    assert job.finished == []


@pytest.mark.parametrize(
    "window",
    [{"ready": True}, {**READY, "business_date": "not a date"}],
    ids=["missing keys", "bad date"],
)
def test_a_window_in_an_unexpected_shape_is_a_pass_error(window: dict[str, object]) -> None:
    job = ScriptedJob(window=window, pages=[], outcomes={})

    with pytest.raises(LateChargePassError):
        job.run(as_of=AS_OF)
    assert job.afters == [] and job.finished == []
