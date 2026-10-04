"""Real PostgreSQL singleton, retry, and catch-up coverage for V1-032."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from payment_test_support import seed_payment
from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.reservation import ReservationServiceUnavailableError
from property_rental.reservation_api import PostgresReservationResourceFlow
from property_rental.reservation_worker import (
    ExpirationRunResult,
    ReservationExpirationWorker,
    run_scheduled,
)
from reservation_deposit_test_support import confirm_reservation_outcome
from test_reservation_lifecycle_migration import (
    expired_reservation,
    financial_database_url,
    runtime_database_url,
)
from test_reservation_migration import reservation_business_date, setup_reservation_sources


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    database_url = os.environ.get("MIGRATION_DATABASE_URL")
    if database_url is None:
        pytest.skip("MIGRATION_DATABASE_URL is required for migration tests")
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def worker(property_id: UUID, actor_id: UUID, *, limit: int = 100) -> ReservationExpirationWorker:
    return ReservationExpirationWorker(
        runtime_database_url(),
        financial_database_url(),
        property_id=property_id,
        actor_id=actor_id,
        limit=limit,
    )


def test_failure_concurrent_retry_and_replay_produce_one_logical_execution(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, unit_id, _customer_id, reservation_id, deposit_id = (
            expired_reservation(setup)
        )
        _, same_property_id, second_unit_id, _, second_reservation_id, second_deposit_id = (
            expired_reservation(setup)
        )
        assert same_property_id == property_id
        setup.commit()
    failing = ReservationExpirationWorker(
        runtime_database_url(),
        "postgresql://127.0.0.1:1/unavailable",
        property_id=property_id,
        actor_id=actor_id,
    )
    with pytest.raises(ReservationServiceUnavailableError):
        failing.run()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: worker(property_id, actor_id, limit=1).run(), range(2)))
    replay = worker(property_id, actor_id).run()

    assert sum(result.expired for result in results) == 2
    assert {result.outcome for result in results}.issubset(
        {"succeeded", "singleton_skipped", "already_succeeded"}
    )
    assert replay.outcome == "already_succeeded"
    with psycopg.connect(migrated_database_url) as check:
        reservation = check.execute(
            "SELECT status, cancellation_reason_code FROM app.reservations WHERE id = %s",
            (reservation_id,),
        ).fetchone()
        unit = check.execute("SELECT status FROM app.units WHERE id = %s", (unit_id,)).fetchone()
        run = check.execute(
            "SELECT status, attempt_count, candidate_count, expired_count, failure_code "
            "FROM app.reservation_expiration_runs WHERE property_id = %s",
            (property_id,),
        ).fetchone()
        outcomes = check.execute(
            "SELECT count(*) FROM app.deposit_dispositions "
            "WHERE (deposit_id, governing_reservation_id) IN ((%s,%s),(%s,%s))",
            (deposit_id, reservation_id, second_deposit_id, second_reservation_id),
        ).fetchone()
        second_reservation = check.execute(
            "SELECT status, cancellation_reason_code FROM app.reservations WHERE id = %s",
            (second_reservation_id,),
        ).fetchone()
        second_unit = check.execute(
            "SELECT status FROM app.units WHERE id = %s", (second_unit_id,)
        ).fetchone()
        attempts = check.execute(
            "SELECT attempt_number,status,failure_code,candidate_count,expired_count "
            "FROM app.reservation_expiration_attempts WHERE run_id=%s "
            "ORDER BY attempt_number",
            (replay.run_id,),
        ).fetchall()
    assert reservation == ("CANCELLED", "RESERVATION_EXPIRED")
    assert unit == ("VACANT",)
    assert second_reservation == ("CANCELLED", "RESERVATION_EXPIRED")
    assert second_unit == ("VACANT",)
    assert run == ("SUCCEEDED", 2, 2, 2, None)
    # V1-056 slice 3b: expiry never forfeits; the forfeiture waits for a confirmed draft.
    assert outcomes == (0,)
    assert attempts == [
        (1, "FAILED", "ReservationServiceUnavailableError", 0, 0),
        (2, "SUCCEEDED", None, 2, 2),
    ]


def test_runtime_role_cannot_rewrite_or_delete_run_evidence(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, *_ = expired_reservation(setup)
        setup.commit()
    result = worker(property_id, actor_id).run()

    for statement in (
        "UPDATE app.reservation_expiration_runs SET expired_count = 99 WHERE id = %s",
        "DELETE FROM app.reservation_expiration_runs WHERE id = %s",
    ):
        with psycopg.connect(runtime_database_url()) as runtime:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                runtime.execute(statement, (result.run_id,))


def test_downtime_catch_up_preserves_the_first_missed_logical_date(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, _, _, reservation_id, _ = expired_reservation(setup, days_past=3)
        current_date = setup.execute(
            "SELECT timezone(timezone_name,clock_timestamp())::date "
            "FROM app.properties WHERE id=%s",
            (property_id,),
        ).fetchone()
        setup.commit()
    assert current_date is not None

    result = worker(property_id, actor_id).run()

    assert result.business_date == current_date[0] - timedelta(days=2)
    with psycopg.connect(migrated_database_url) as check:
        row = check.execute(
            "SELECT business_date,status FROM app.reservation_expiration_runs WHERE id=%s",
            (result.run_id,),
        ).fetchone()
        reservation = check.execute(
            "SELECT status FROM app.reservations WHERE id=%s", (reservation_id,)
        ).fetchone()
    assert row == (result.business_date, "SUCCEEDED")
    assert reservation == ("CANCELLED",)


def test_http_detail_reads_real_postgres_receipt_lifecycle_and_outcome_evidence(
    migrated_database_url: str,
) -> None:
    # V1-056 slice 3b: expiry never forfeits, so this test expires its own Reservation and
    # confirms the forfeiture draft before reading the outcome evidence.
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, _, _, reservation_id, _ = expired_reservation(setup)
        setup.commit()
    with psycopg.connect(financial_database_url()) as financial:
        # The expiry command the worker runs (worker runs are keyed by logical date, and the
        # shared test Property already has today's run).
        financial.execute(
            "SELECT * FROM app.expire_reservation_v3(%s,%s,%s,%s,%s,1,true,%s,%s)",
            (
                property_id,
                uuid4(),
                "e" * 64,
                uuid4(),
                reservation_id,
                "reservations.cancel",
                actor_id,
            ),
        ).fetchone()
        confirm_reservation_outcome(
            financial,
            actor_id=actor_id,
            property_id=property_id,
            reservation_id=reservation_id,
            idempotency_key=uuid4(),
            outcome_id=uuid4(),
            responsibility="CUSTOMER",
            reason="Reservation expired while the Property could provide the Unit",
        )
    scope = frozenset({str(property_id)})
    authenticated = AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset({CapabilityGrant("reservations.read", scope)}),
    )
    flow = PostgresReservationResourceFlow(runtime_database_url(), financial_database_url())
    direct = flow.get(reservation_id)
    assert direct.receipts and direct.lifecycle_events and direct.deposit_outcomes
    api = TestClient(
        create_app(
            actor_resolver=lambda _: authenticated,
            reservation_resource_flow=flow,
        )
    )

    response = api.get(f"/reservations/{reservation_id}")

    assert response.status_code == 200
    resource = response.json()["data"]
    assert resource["receipts"][0]["payment_id"]
    assert resource["lifecycle_events"][0]["reason_code"] == "RESERVATION_EXPIRED"
    assert resource["deposit_outcomes"][0]["outcome_kind"] == "DISPOSITION"
    assert (
        resource["deposit_outcomes"][0]["source_lifecycle_event_id"]
        == resource["lifecycle_events"][0]["event_id"]
    )


def test_http_mutations_reach_real_postgres_with_security_replay_and_rollback(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, unit_id, customer_id = setup_reservation_sources(setup)
        business_date = reservation_business_date(setup, property_id)
        setup.commit()
    scope = frozenset({str(property_id)})
    authenticated = AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            CapabilityGrant(capability, scope)
            for capability in (
                "reservations.read",
                "reservations.create",
                "reservations.extend",
                "reservations.cancel",
                "reservation_deposits.dispose",
                "financial.approve",
            )
        ),
    )
    api = TestClient(
        create_app(
            actor_resolver=lambda _: authenticated,
            reservation_resource_flow=PostgresReservationResourceFlow(
                runtime_database_url(), financial_database_url()
            ),
        )
    )
    api.cookies.set("__Host-prm_csrf", "csrf")

    reservation_id = uuid4()
    deposit_id = uuid4()
    acceptance_id = uuid4()
    receipt_id = uuid4()
    payment_id = uuid4()
    payment_confirmed_at = datetime.now(UTC)
    with psycopg.connect(migrated_database_url) as setup:
        seed_payment(
            setup,
            actor_id=actor_id,
            property_id=property_id,
            customer_id=customer_id,
            amount=10_001,
            payment_id=payment_id,
            confirmed_at=payment_confirmed_at,
        )
        setup.commit()
    create_key = uuid4()
    create_payload = {
        "reservation_id": str(reservation_id),
        "unit_id": str(unit_id),
        "customer_id": str(customer_id),
        "reservation_date": business_date.isoformat(),
        "agreed_monthly_rent_usd_cents": 50_003,
        "expiration_date": (business_date + timedelta(days=10)).isoformat(),
        "acceptance_id": str(acceptance_id),
        "accepted_initial_deposit_usd_cents": 10_001,
        "required_security_deposit_usd_cents": 50_000,
        "acceptance_reason": "Accepted half-up normal suggestion",
        "deposit_id": str(deposit_id),
        "receipt_id": str(receipt_id),
        "payment_id": str(payment_id),
        "received_at": payment_confirmed_at.isoformat().replace("+00:00", "Z"),
    }

    missing_csrf_id = uuid4()
    missing_csrf_acceptance_id = uuid4()
    missing_csrf_deposit_id = uuid4()
    missing_csrf_receipt_id = uuid4()
    missing_csrf_payment_id = uuid4()
    missing_csrf_key = uuid4()
    missing_csrf_payload = {
        **create_payload,
        "reservation_id": str(missing_csrf_id),
        "acceptance_id": str(missing_csrf_acceptance_id),
        "deposit_id": str(missing_csrf_deposit_id),
        "receipt_id": str(missing_csrf_receipt_id),
        "payment_id": str(missing_csrf_payment_id),
    }
    missing_csrf = api.post(
        f"/properties/{property_id}/reservations",
        json=missing_csrf_payload,
        headers={"Origin": "https://localhost", "Idempotency-Key": str(missing_csrf_key)},
    )
    wrong_scope_key = uuid4()
    wrong_scope = api.post(
        f"/properties/{uuid4()}/reservations",
        json=create_payload,
        headers={
            "Origin": "https://localhost",
            "X-CSRF-Token": "csrf",
            "Idempotency-Key": str(wrong_scope_key),
        },
    )
    create_headers = {
        "Origin": "https://localhost",
        "X-CSRF-Token": "csrf",
        "Idempotency-Key": str(create_key),
    }
    created = api.post(
        f"/properties/{property_id}/reservations", json=create_payload, headers=create_headers
    )
    create_replay = api.post(
        f"/properties/{property_id}/reservations", json=create_payload, headers=create_headers
    )

    conflicting_id = uuid4()
    conflicting_acceptance_id = uuid4()
    conflicting_deposit_id = uuid4()
    conflicting_receipt_id = uuid4()
    conflicting_payment_id = uuid4()
    conflict_key = uuid4()
    conflicting_payload = {
        **create_payload,
        "reservation_id": str(conflicting_id),
        "acceptance_id": str(conflicting_acceptance_id),
        "deposit_id": str(conflicting_deposit_id),
        "receipt_id": str(conflicting_receipt_id),
        "payment_id": str(conflicting_payment_id),
    }
    conflict = api.post(
        f"/properties/{property_id}/reservations",
        json=conflicting_payload,
        headers={**create_headers, "Idempotency-Key": str(conflict_key)},
    )

    extend_key = uuid4()
    notice_id = uuid4()
    extend_payload = {
        "notice_id": str(notice_id),
        "new_expiration_date": (business_date + timedelta(days=12)).isoformat(),
        "approved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "reason_memo": "Approved extension",
    }
    extend_headers = {
        **create_headers,
        "Idempotency-Key": str(extend_key),
        "If-Match": '"1"',
    }
    extended = api.post(
        f"/reservations/{reservation_id}/extend", json=extend_payload, headers=extend_headers
    )
    extend_replay = api.post(
        f"/reservations/{reservation_id}/extend", json=extend_payload, headers=extend_headers
    )
    stale_notice_id = uuid4()
    stale_extend_key = uuid4()
    stale_extend = api.post(
        f"/reservations/{reservation_id}/extend",
        json={**extend_payload, "notice_id": str(stale_notice_id)},
        headers={**extend_headers, "Idempotency-Key": str(stale_extend_key)},
    )

    cancel_event_id = uuid4()
    cancel_outcome_id = uuid4()
    cancel_key = uuid4()
    # V1-056 slice 3b: the cancel route only cancels; the Deposit forfeiture is a draft that a
    # financial.approve holder confirms (the earlier atomic route records nothing now).
    cancel_payload = {
        "event_id": str(cancel_event_id),
        "reason_code": "CUSTOMER_WITHDREW",
        "responsibility": "CUSTOMER",
        "property_could_provide_unit": True,
        "reason_memo": "Customer request",
        "coordination_reference": None,
    }
    cancel_headers = {
        **create_headers,
        "Idempotency-Key": str(cancel_key),
        "If-Match": '"2"',
    }
    cancelled = api.post(
        f"/reservations/{reservation_id}/cancel",
        json=cancel_payload,
        headers=cancel_headers,
    )
    cancel_replay = api.post(
        f"/reservations/{reservation_id}/cancel",
        json=cancel_payload,
        headers=cancel_headers,
    )
    changed_cancel_replay = api.post(
        f"/reservations/{reservation_id}/cancel",
        json={**cancel_payload, "reason_memo": "Changed customer evidence"},
        headers=cancel_headers,
    )
    draft_headers = {**create_headers, "Idempotency-Key": str(uuid4())}
    draft = api.post(
        f"/reservations/{reservation_id}/deposit-drafts",
        json={"outcome_id": str(cancel_outcome_id), "reason": "Customer request"},
        headers=draft_headers,
    )
    assert draft.status_code == 201, draft.json()
    confirmed = api.post(
        f"/reservations/{reservation_id}/deposit-drafts/{draft.json()['data']['draft_id']}/confirm",
        headers=create_headers,
    )
    assert confirmed.status_code == 200, confirmed.json()

    assert missing_csrf.status_code == 403
    assert wrong_scope.status_code == 404
    assert created.status_code == create_replay.status_code == 201, created.json()
    assert created.headers["location"] == f"/reservations/{reservation_id}"
    created_resource = created.json()["data"]
    assert created_resource == create_replay.json()["data"]
    assert created_resource["version"] == 1
    assert created_resource["deposit_id"] == str(deposit_id)
    assert created_resource["deposit_required_usd_cents"] == 50_000
    assert created_resource["deposit_received_usd_cents"] == 10_001
    assert created_resource["receipts"] == [
        {
            "receipt_id": str(receipt_id),
            "payment_id": str(payment_id),
            "amount_usd_cents": 10_001,
            "occurred_at": create_payload["received_at"],
            "actor_id": str(actor_id),
        }
    ]
    assert conflict.status_code == 409
    assert extended.status_code == extend_replay.status_code == 200
    extended_resource = extended.json()["data"]
    assert extended_resource == extend_replay.json()["data"]
    assert extended_resource["version"] == 2
    assert extended_resource["extension_notice"] == {
        "notice_id": str(notice_id),
        "previous_expiration_date": create_payload["expiration_date"],
        "new_expiration_date": extend_payload["new_expiration_date"],
        "approved_at": extend_payload["approved_at"],
        "reason_memo": extend_payload["reason_memo"],
    }
    assert stale_extend.status_code == 412
    assert cancelled.status_code == cancel_replay.status_code == 200
    assert cancelled.headers["cache-control"] == "private, no-store"
    cancelled_result = cancelled.json()["data"]
    assert cancelled_result == cancel_replay.json()["data"]
    assert changed_cancel_replay.status_code == 409
    assert changed_cancel_replay.json()["error"] == {
        "code": "IDEMPOTENCY_KEY_REUSED",
        "message": "The idempotency key was already used for different input.",
        "fields": [],
        "rule_ids": ["API-016"],
        "current_version": None,
    }
    cancelled_resource = api.get(f"/reservations/{reservation_id}").json()["data"]
    assert cancelled_resource["version"] == 3
    assert cancelled_resource["deposit_outcome_state"] == "NON_REFUNDABLE_DISPOSITION"
    assert cancelled_resource["lifecycle_events"] == [
        {
            "event_id": cancel_payload["event_id"],
            "event_kind": "CANCELLATION",
            "reason_code": cancel_payload["reason_code"],
            "responsibility": cancel_payload["responsibility"],
            "reason_memo": cancel_payload["reason_memo"],
            "coordination_reference": None,
            "authorization_reference": "reservations.cancel",
            "occurred_at": cancelled_resource["lifecycle_events"][0]["occurred_at"],
            "business_date": business_date.isoformat(),
            "actor_id": str(actor_id),
        }
    ]
    assert cancelled_resource["deposit_outcomes"] == [
        {
            "outcome_id": str(cancel_outcome_id),
            "outcome_kind": "DISPOSITION",
            "amount_usd_cents": 10_001,
            "source_lifecycle_event_id": cancel_payload["event_id"],
            "reason": cancel_payload["reason_memo"],
            "occurred_at": cancelled_resource["deposit_outcomes"][0]["occurred_at"],
            "actor_id": str(actor_id),
            "authorization_reference": "reservation_deposits.dispose",
        }
    ]

    with psycopg.connect(migrated_database_url) as check:
        persisted = check.execute(
            "SELECT reservation.status,reservation.version,unit.status,"
            "(SELECT count(*) FROM app.reservation_extension_notices WHERE reservation_id=%s),"
            "(SELECT count(*) FROM app.reservation_lifecycle_events WHERE reservation_id=%s),"
            "(SELECT count(*) FROM app.deposit_dispositions "
            " WHERE deposit_id=%s AND governing_reservation_id=%s) "
            "FROM app.reservations AS reservation JOIN app.units AS unit "
            "ON unit.id=reservation.unit_id WHERE reservation.id=%s",
            (reservation_id, reservation_id, deposit_id, reservation_id, reservation_id),
        ).fetchone()
        rolled_back = check.execute(
            "SELECT "
            "(SELECT count(*) FROM app.reservations WHERE id IN (%s,%s)),"
            "(SELECT count(*) FROM app.reservation_deposit_acceptances WHERE id IN (%s,%s)),"
            "(SELECT count(*) FROM app.deposits WHERE id IN (%s,%s)),"
            "(SELECT count(*) FROM app.deposit_receipts WHERE id IN (%s,%s)),"
            "(SELECT count(*) FROM app.reservation_extension_notices WHERE id=%s),"
            "(SELECT count(*) FROM app.reservation_commands "
            " WHERE idempotency_key IN (%s,%s,%s,%s))",
            (
                missing_csrf_id,
                conflicting_id,
                missing_csrf_acceptance_id,
                conflicting_acceptance_id,
                missing_csrf_deposit_id,
                conflicting_deposit_id,
                missing_csrf_receipt_id,
                conflicting_receipt_id,
                stale_notice_id,
                missing_csrf_key,
                wrong_scope_key,
                conflict_key,
                stale_extend_key,
            ),
        ).fetchone()
        receipt_link = check.execute(
            "SELECT receipt.id,receipt.payment_id,receipt.deposit_id,receipt.amount_usd_cents "
            "FROM app.deposit_receipts AS receipt WHERE receipt.id=%s",
            (receipt_id,),
        ).fetchone()
        notice_history = check.execute(
            "SELECT id,original_expiration_date,previous_expiration_date,new_expiration_date,"
            "approved_by,reason_memo,authorization_reference "
            "FROM app.reservation_extension_notices WHERE id=%s",
            (notice_id,),
        ).fetchone()
        cancellation_links = check.execute(
            "SELECT event.id,event.reservation_id,event.expected_version,event.resulting_version,"
            "disposition.id,disposition.deposit_id,disposition.governing_reservation_id,"
            "disposition.source_lifecycle_event_id,disposition.amount_usd_cents "
            "FROM app.reservation_lifecycle_events AS event "
            "JOIN app.deposit_dispositions AS disposition "
            "ON disposition.source_lifecycle_event_id=event.id "
            "WHERE event.id=%s AND disposition.id=%s",
            (cancel_event_id, cancel_outcome_id),
        ).fetchone()
        command_evidence = check.execute(
            "SELECT action,idempotency_key,result_id,request_digest,result_snapshot "
            "FROM app.reservation_commands WHERE actor_id=%s AND property_id=%s "
            "AND idempotency_key IN (%s,%s,%s) ORDER BY action",
            (actor_id, property_id, create_key, extend_key, cancel_key),
        ).fetchall()
    assert persisted == ("CANCELLED", 3, "VACANT", 1, 1, 1)
    assert rolled_back == (0, 0, 0, 0, 0, 0)
    assert receipt_link == (receipt_id, payment_id, deposit_id, 10_001)
    assert notice_history == (
        notice_id,
        business_date + timedelta(days=10),
        business_date + timedelta(days=10),
        business_date + timedelta(days=12),
        actor_id,
        "Approved extension",
        "reservations.extend",
    )
    assert cancellation_links == (
        cancel_event_id,
        reservation_id,
        2,
        3,
        cancel_outcome_id,
        deposit_id,
        reservation_id,
        cancel_event_id,
        10_001,
    )
    assert [(row[0], row[1], row[2]) for row in command_evidence] == [
        ("reservation.cancel", cancel_key, cancel_event_id),
        ("reservation.create", create_key, reservation_id),
        ("reservation.extend", extend_key, notice_id),
    ]
    assert all(len(row[3]) == 64 and isinstance(row[4], dict) for row in command_evidence)
    assert [row[4]["version"] for row in command_evidence] == [3, 1, 2]

    correction_draft = api.post(
        f"/reservations/{reservation_id}/deposit-correction-drafts",
        json={
            "expected_outcome_id": str(cancel_outcome_id),
            "correction_id": str(uuid4()),
            "replacement_outcome_id": str(uuid4()),
            "reason": "Correct cancellation evidence",
            "evidence_reference": "case-v1-038-replay",
        },
        headers={**create_headers, "Idempotency-Key": str(uuid4())},
    )
    assert correction_draft.status_code == 404
    correction_actor = AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=authenticated.capability_grants
        | {CapabilityGrant("reservation_deposits.correct", scope)},
    )
    correction_api = TestClient(
        create_app(
            actor_resolver=lambda _: correction_actor,
            reservation_resource_flow=PostgresReservationResourceFlow(
                runtime_database_url(), financial_database_url()
            ),
        )
    )
    correction_api.cookies.set("__Host-prm_csrf", "csrf")
    correction_draft = correction_api.post(
        f"/reservations/{reservation_id}/deposit-correction-drafts",
        json={
            "expected_outcome_id": str(cancel_outcome_id),
            "correction_id": str(uuid4()),
            "replacement_outcome_id": str(uuid4()),
            "reason": "Correct cancellation evidence",
            "evidence_reference": "case-v1-038-replay",
        },
        headers={**create_headers, "Idempotency-Key": str(uuid4())},
    )
    assert correction_draft.status_code == 201, correction_draft.json()
    corrected = correction_api.post(
        f"/reservations/{reservation_id}/deposit-drafts/"
        f"{correction_draft.json()['data']['draft_id']}/confirm",
        headers=create_headers,
    )
    assert corrected.status_code == 200, corrected.json()
    replay_after_correction = api.post(
        f"/reservations/{reservation_id}/cancel",
        json=cancel_payload,
        headers=cancel_headers,
    )
    assert replay_after_correction.status_code == 200
    # The cancel route answers with the current Reservation, so the replay keeps the
    # cancellation identity and version while the Deposit outcome shows the correction.
    replayed = replay_after_correction.json()["data"]
    assert (replayed["reservation_id"], replayed["version"], replayed["status"]) == (
        cancelled_result["reservation_id"],
        cancelled_result["version"],
        cancelled_result["status"],
    )


def test_run_identity_is_property_scoped_and_nonzero() -> None:
    with pytest.raises(ValueError, match="limit"):
        ReservationExpirationWorker(
            "postgresql://unused",
            "postgresql://unused",
            property_id=uuid4(),
            actor_id=uuid4(),
            limit=101,
        )


def test_automatic_runner_repeats_until_stopped_and_once_runs_exactly_once() -> None:
    class FakeWorker:
        calls = 0

        def run(self) -> ExpirationRunResult:
            self.calls += 1
            return ExpirationRunResult(None, None, 0, 0, "succeeded")

    worker_instance = FakeWorker()
    run_scheduled(worker_instance, once=True, poll_interval_seconds=300, sleep=lambda _: None)
    assert worker_instance.calls == 1

    def stop(_: float) -> None:
        raise RuntimeError("scheduled stop")

    with pytest.raises(RuntimeError, match="scheduled stop"):
        run_scheduled(
            worker_instance,
            once=False,
            poll_interval_seconds=300,
            sleep=stop,
        )
    assert worker_instance.calls == 2

    class TransientWorker(FakeWorker):
        def run(self) -> ExpirationRunResult:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transient")
            return ExpirationRunResult(None, None, 0, 0, "succeeded")

    transient = TransientWorker()
    delays: list[float] = []
    run_scheduled(
        transient,
        once=True,
        poll_interval_seconds=300,
        sleep=delays.append,
    )
    assert transient.calls == 2
    assert delays == [2]
