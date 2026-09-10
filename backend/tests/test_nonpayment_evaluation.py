"""Read-only evaluator entry point and safe, bounded operational evidence."""

from __future__ import annotations

import json
import sys
from typing import Self
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental import nonpayment_evaluation as module
from property_rental.lease_enforcement import LeaseEnforcementUnavailableError
from property_rental.lease_enforcement_context import EnforcementPage


def test_evaluation_cli_requires_its_dedicated_connection_and_never_uses_financial_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("APP_NONPAYMENT_EVALUATION_DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_FINANCIAL_DATABASE_URL", "SYNTHETIC-PRIVATE-CONNECTION")
    monkeypatch.setattr(
        sys, "argv", ["evaluation", "--property-id", str(uuid4()), "--actor-id", str(uuid4())]
    )
    with pytest.raises(SystemExit) as failure:
        module.main()
    assert failure.value.code == 2
    output = capsys.readouterr()
    assert "APP_NONPAYMENT_EVALUATION_DATABASE_URL is required" in output.err
    assert "SYNTHETIC-PRIVATE-CONNECTION" not in output.out + output.err


def test_evaluation_cli_emits_only_bounded_summary_and_preserves_continuation_cursor(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    actor, prop, cursor = uuid4(), uuid4(), uuid4()
    observed: list[tuple[str, UUID, UUID, EnforcementPage | None]] = []

    def evaluate(
        self: module.ScheduledRentNonpaymentEvaluator, page: EnforcementPage | None = None
    ) -> dict[str, object]:
        observed.append((self.database_url, self.property_id, self.actor_id, page))
        return {
            "items": [{"synthetic_private_source": "never-log-this"}],
            "next_cursor": str(cursor),
            "business_date": "2026-09-10",
        }

    monkeypatch.setenv("APP_NONPAYMENT_EVALUATION_DATABASE_URL", "SYNTHETIC-CONNECTION")
    monkeypatch.setattr(module.ScheduledRentNonpaymentEvaluator, "run_once", evaluate)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluation",
            "--property-id",
            str(prop),
            "--actor-id",
            str(actor),
            "--limit",
            "1",
            "--cursor",
            str(cursor),
        ],
    )
    assert module.main() == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "status": "evaluated",
        "count": 1,
        "next_cursor": str(cursor),
        "business_date": "2026-09-10",
    }
    assert observed == [("SYNTHETIC-CONNECTION", prop, actor, EnforcementPage(1, cursor))]
    assert "never-log-this" not in output.out + output.err
    assert "SYNTHETIC-CONNECTION" not in output.out + output.err


def test_evaluation_cli_failure_is_retryable_without_logging_connection_or_source_details(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(
        self: module.ScheduledRentNonpaymentEvaluator, page: EnforcementPage | None = None
    ) -> dict[str, object]:
        raise LeaseEnforcementUnavailableError("SYNTHETIC-PRIVATE-DETAILS")

    monkeypatch.setenv("APP_NONPAYMENT_EVALUATION_DATABASE_URL", "SYNTHETIC-CONNECTION")
    monkeypatch.setattr(module.ScheduledRentNonpaymentEvaluator, "run_once", fail)
    monkeypatch.setattr(
        sys, "argv", ["evaluation", "--property-id", str(uuid4()), "--actor-id", str(uuid4())]
    )
    assert module.main() == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "status": "failed",
        "error_type": "LeaseEnforcementUnavailableError",
    }
    assert "SYNTHETIC" not in output.out + output.err


def test_evaluation_adapter_sets_read_only_before_every_query_and_preserves_page_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor, prop, cursor = uuid4(), uuid4(), uuid4()
    calls: list[tuple[str, object]] = []
    result: dict[str, object] = {"items": [], "next_cursor": None, "business_date": "2026-09-10"}

    class Connection:
        read_only = False

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def execute(self, query: str, parameters: object = None) -> Self:
            assert self.read_only is True
            calls.append((query, parameters))
            return self

        def fetchone(self) -> tuple[dict[str, object]]:
            return (result,)

    def connect(conninfo: str, *, connect_timeout: int) -> Connection:
        assert conninfo == "SYNTHETIC-CONNECTION" and connect_timeout == 3
        return Connection()

    monkeypatch.setattr(psycopg, "connect", connect)
    assert (
        module.ScheduledRentNonpaymentEvaluator("SYNTHETIC-CONNECTION", prop, actor).run_once(
            EnforcementPage(1, cursor)
        )
        == result
    )
    assert calls == [
        ("SET LOCAL statement_timeout='5000ms'", None),
        ("SET LOCAL lock_timeout='3000ms'", None),
        ("SELECT app.scheduled_rent_nonpayment_evaluation(%s,%s,%s,%s)", (actor, prop, 1, cursor)),
    ]
