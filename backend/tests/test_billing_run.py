"""Focused command, API, and worker semantics for V1-044."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.billing_run import (
    BillingRunAttempt,
    BillingRunCommand,
    BillingRunConflict,
    BillingRunDetail,
    BillingRunUnavailable,
    PostgresBillingRunService,
    billing_run_request_digest,
)
from property_rental.billing_worker import (
    BillingWorkerResult,
    property_local_date,
    run_bounded_loop,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant


def run_detail(command: BillingRunCommand, *, source: str = "API") -> BillingRunDetail:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    return BillingRunDetail(
        id=uuid4(),
        property_id=command.property_id,
        run_kind=command.run_kind,
        logical_run_key=command.logical_run_key,
        business_date=command.business_date,
        period_start=command.period_start,
        period_end=command.period_end,
        idempotency_key=command.idempotency_key,
        request_digest=billing_run_request_digest(command, source),
        correlation_id=uuid4(),
        invocation_source=source,
        requester_actor_id=uuid4(),
        system_actor_id=uuid4(),
        status="SUCCEEDED",
        started_at=now,
        completed_at=now,
        failure_code=None,
        attempts=(BillingRunAttempt(uuid4(), 1, now, now, "SUCCEEDED", None, ()),),
    )


class RecordingFlow:
    def __init__(self) -> None:
        self.commands: list[BillingRunCommand] = []
        self.details: dict[UUID, BillingRunDetail] = {}
        self.digest_by_key: dict[UUID, str] = {}

    def execute(
        self,
        command: BillingRunCommand,
        *,
        actor: AuthenticatedActor,
        invocation_source: str,
    ) -> BillingRunDetail:
        del actor
        digest = billing_run_request_digest(command, invocation_source)
        existing = self.digest_by_key.get(command.idempotency_key)
        if existing is not None and existing != digest:
            raise BillingRunConflict("different input")
        self.digest_by_key[command.idempotency_key] = digest
        self.commands.append(command)
        detail = next(
            (
                item
                for item in self.details.values()
                if item.idempotency_key == command.idempotency_key
            ),
            run_detail(command, source=invocation_source),
        )
        self.details[detail.id] = detail
        return detail

    def get(self, run_id: UUID, *, actor: AuthenticatedActor) -> BillingRunDetail:
        del actor
        return self.details[run_id]


def rent_command() -> BillingRunCommand:
    return BillingRunCommand(
        property_id=uuid4(),
        run_kind="RENT",
        logical_run_key="rent/2026-09",
        business_date=date(2026, 8, 25),
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        idempotency_key=uuid4(),
    )


def test_canonical_digest_binds_idempotency_period_and_invocation_source() -> None:
    command = rent_command()

    digest = billing_run_request_digest(command, "API")

    assert digest == billing_run_request_digest(command, "API")
    assert len(digest) == 64
    assert digest != billing_run_request_digest(replace(command, idempotency_key=uuid4()), "API")
    assert digest != billing_run_request_digest(command, "SCHEDULED")


def test_rent_command_requires_property_local_day_25_and_next_complete_month() -> None:
    valid = rent_command()

    assert valid.period_start == date(2026, 9, 1)
    with pytest.raises(ValueError, match="day 25"):
        replace(valid, business_date=date(2026, 8, 24))
    with pytest.raises(ValueError, match="day 25"):
        replace(valid, period_start=date(2026, 8, 1), period_end=date(2026, 8, 31))


def test_failure_before_transaction_is_visible_without_a_blind_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = rent_command()
    actor = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            {CapabilityGrant("billing.generate", frozenset({str(command.property_id)}))}
        ),
    )

    def unavailable(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise psycopg.OperationalError("injected before transaction")

    monkeypatch.setattr("property_rental.billing_run.psycopg.connect", unavailable)

    with pytest.raises(BillingRunUnavailable, match="persistence is unavailable"):
        PostgresBillingRunService("postgresql://unavailable").execute(
            command, actor=actor, invocation_source="API"
        )


def test_property_local_midnight_is_exact_and_independent_of_host_timezone() -> None:
    before = datetime(2026, 8, 31, 16, 59, 59, 999999, tzinfo=UTC)
    at = datetime(2026, 8, 31, 17, 0, 0, tzinfo=UTC)
    after = datetime(2026, 8, 31, 17, 0, 0, 1, tzinfo=UTC)

    assert property_local_date(before, "Asia/Phnom_Penh") == date(2026, 8, 31)
    assert property_local_date(at, "Asia/Phnom_Penh") == date(2026, 9, 1)
    assert property_local_date(after, "Asia/Phnom_Penh") == date(2026, 9, 1)
    assert property_local_date(at, "America/Los_Angeles") == date(2026, 8, 31)


def test_api_enforces_scope_csrf_replay_and_different_input_conflict() -> None:
    command = rent_command()
    flow = RecordingFlow()
    scope = frozenset({str(command.property_id)})
    actor = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset({CapabilityGrant("billing.generate", scope)}),
    )
    api = TestClient(create_app(actor_resolver=lambda _: actor, billing_run_flow=flow))
    api.cookies.set("__Host-prm_csrf", "csrf")
    payload = {
        "logical_run_key": command.logical_run_key,
        "business_date": command.business_date.isoformat(),
        "period_start": command.period_start.isoformat(),
        "period_end": command.period_end.isoformat(),
    }
    headers = {
        "Origin": "https://localhost",
        "X-CSRF-Token": "csrf",
        "Idempotency-Key": str(command.idempotency_key),
    }

    missing_csrf = api.post(
        f"/api/v1/properties/{command.property_id}/billing-runs/rent",
        json=payload,
        headers={"Idempotency-Key": str(command.idempotency_key)},
    )
    created = api.post(
        f"/api/v1/properties/{command.property_id}/billing-runs/rent",
        json=payload,
        headers=headers,
    )
    replay = api.post(
        f"/api/v1/properties/{command.property_id}/billing-runs/rent",
        json=payload,
        headers=headers,
    )
    conflict = api.post(
        f"/api/v1/properties/{command.property_id}/billing-runs/rent",
        json={**payload, "logical_run_key": "rent/changed"},
        headers=headers,
    )
    wrong_scope = api.post(
        f"/api/v1/properties/{uuid4()}/billing-runs/rent",
        json=payload,
        headers=headers,
    )
    utility = api.post(
        f"/api/v1/properties/{command.property_id}/billing-runs/utilities",
        json={
            "logical_run_key": "utilities/2026-08",
            "business_date": "2026-08-31",
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
        },
        headers={**headers, "Idempotency-Key": str(uuid4())},
    )
    detail = api.get(f"/api/v1/billing-runs/{created.json()['data']['id']}")

    assert missing_csrf.status_code == 403
    assert created.status_code == replay.status_code == detail.status_code == 200
    assert created.json()["data"] == replay.json()["data"]
    assert conflict.status_code == 409
    assert wrong_scope.status_code == 403
    assert utility.status_code == 200
    assert utility.json()["data"]["run_kind"] == "UTILITIES"
    assert detail.headers["Cache-Control"] == "private, no-store"
    assert len(flow.commands) == 3


def test_bounded_worker_loop_uses_capped_backoff_and_stops() -> None:
    class FailingWorker:
        calls = 0

        def run_once(self, *, as_of: datetime | None = None) -> BillingWorkerResult:
            del as_of
            self.calls += 1
            raise RuntimeError("injected")

    worker = FailingWorker()
    sleeps: list[float] = []

    run_bounded_loop(worker, max_iterations=4, poll_interval_seconds=3, sleep=sleeps.append)

    assert worker.calls == 4
    assert sleeps == [2, 3, 3]
