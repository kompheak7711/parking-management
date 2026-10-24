"""Real PostgreSQL coverage for V1-031 cancellation Deposit outcomes."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import Error

from reservation_deposit_test_support import correct_reservation_outcome
from test_reservation_lifecycle_migration import (
    active_reservation,
    cancel,
    financial_database_url,
    runtime_database_url,
)


@pytest.fixture(scope="session")
def reservation_outcome_database_url() -> str:
    """Apply all migrations to the disposable PostgreSQL database."""
    database_url = os.environ.get("MIGRATION_DATABASE_URL")
    if database_url is None:
        pytest.skip("MIGRATION_DATABASE_URL is required for migration tests")
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def test_customer_and_property_outcomes_preserve_exact_source_links_and_audit(
    reservation_outcome_database_url: str,
) -> None:
    with psycopg.connect(reservation_outcome_database_url) as setup:
        customer_actor, customer_property, _, _, customer_reservation = active_reservation(setup)
        property_actor, property_property, _, property_customer, property_reservation = (
            active_reservation(setup)
        )
        setup.commit()

    customer_event = uuid4()
    customer_outcome = uuid4()
    with psycopg.connect(financial_database_url()) as runtime:
        customer_row = cancel(
            runtime,
            actor_id=customer_actor,
            property_id=customer_property,
            reservation_id=customer_reservation,
            idempotency_key=uuid4(),
            event_id=customer_event,
            outcome_id=customer_outcome,
        )
        runtime.commit()
    property_event = uuid4()
    property_outcome = uuid4()
    with psycopg.connect(financial_database_url()) as runtime:
        property_row = cancel(
            runtime,
            actor_id=property_actor,
            property_id=property_property,
            reservation_id=property_reservation,
            idempotency_key=uuid4(),
            event_id=property_event,
            outcome_id=property_outcome,
            responsibility="PROPERTY",
            property_could_provide_unit=False,
            coordination_reference="CASE-REFUND-1",
            refund_number="RF-SOURCE-1",
        )
        runtime.commit()

    assert customer_row[11:] == (
        "NON_REFUNDABLE_DISPOSITION",
        customer_outcome,
        None,
    )
    assert property_row[11:13] == ("REFUND", property_outcome)
    # DL-071 answer 10 (V1-059 part B): the database gives the Refund its RFD number.
    assert str(property_row[13]).startswith("RFD")
    with psycopg.connect(reservation_outcome_database_url) as verify:
        assert verify.execute(
            """
            SELECT disposition.governing_reservation_id,
                   disposition.source_lifecycle_event_id,
                   disposition.deposit_id, disposition.amount_usd_cents,
                   audit.resulting_state ->> 'outcome_kind'
            FROM app.deposit_dispositions AS disposition
            JOIN app.audit_events AS audit ON audit.id = disposition.id
            WHERE disposition.id = %s
            """,
            (customer_outcome,),
        ).fetchone() == (
            customer_reservation,
            customer_event,
            customer_row[9],
            customer_row[10],
            "NON_REFUNDABLE_DISPOSITION",
        )
        refund_source = verify.execute(
            """
            SELECT refund.source_lifecycle_event_id, refund.source_deposit_id,
                   refund.recipient_customer_id, refund.usd_accounting_value_cents,
                   refund.refund_currency, refund.refund_amount_minor,
                   audit.resulting_state ->> 'outcome_kind'
            FROM app.refunds AS refund
            JOIN app.audit_events AS audit ON audit.id = refund.id
            WHERE refund.id = %s
            """,
            (property_outcome,),
        ).fetchone()
        assert refund_source == (
            property_event,
            property_row[9],
            property_customer,
            property_row[10],
            "USD",
            property_row[10],
            "REFUND",
        )


def test_identical_concurrent_cancellation_creates_one_outcome(
    reservation_outcome_database_url: str,
) -> None:
    with psycopg.connect(reservation_outcome_database_url) as setup:
        actor_id, property_id, _, _, reservation_id = active_reservation(setup)
        setup.commit()
    barrier = Barrier(2)
    key, event_id, outcome_id = uuid4(), uuid4(), uuid4()

    def attempt(_: int) -> tuple[object, ...]:
        with psycopg.connect(financial_database_url()) as runtime:
            barrier.wait()
            row = cancel(
                runtime,
                actor_id=actor_id,
                property_id=property_id,
                reservation_id=reservation_id,
                idempotency_key=key,
                event_id=event_id,
                outcome_id=outcome_id,
            )
            runtime.commit()
            return row

    with ThreadPoolExecutor(max_workers=2) as executor:
        rows = list(executor.map(attempt, range(2)))
    assert rows[0] == rows[1]
    with psycopg.connect(reservation_outcome_database_url) as verify:
        assert verify.execute(
            "SELECT count(*) FROM app.deposit_dispositions WHERE id = %s",
            (outcome_id,),
        ).fetchone() == (1,)


def test_duplicate_refund_number_rolls_back_cancellation_and_availability(
    reservation_outcome_database_url: str,
) -> None:
    with psycopg.connect(reservation_outcome_database_url) as setup:
        actor1, property1, _, _, reservation1 = active_reservation(setup)
        actor2, property2, unit2, _, reservation2 = active_reservation(setup)
        setup.commit()
    with psycopg.connect(financial_database_url()) as runtime:
        first = cancel(
            runtime,
            actor_id=actor1,
            property_id=property1,
            reservation_id=reservation1,
            idempotency_key=uuid4(),
            event_id=uuid4(),
            responsibility="PROPERTY",
            property_could_provide_unit=False,
            coordination_reference="CASE-A",
        )
        runtime.commit()
    # DL-071 answer 10 (V1-059 part B): the database gives the Refund number; a draft whose
    # reference is that used number is refused and the cancellation rolls back.
    used_number = str(first[13])
    assert used_number.startswith("RFD")
    failed_event = uuid4()
    with psycopg.connect(financial_database_url()) as runtime:
        with pytest.raises(Error) as duplicate:
            cancel(
                runtime,
                actor_id=actor2,
                property_id=property2,
                reservation_id=reservation2,
                idempotency_key=uuid4(),
                event_id=failed_event,
                responsibility="PROPERTY",
                property_could_provide_unit=False,
                coordination_reference="CASE-B",
                refund_number=used_number,
            )
            runtime.commit()
        assert duplicate.value.sqlstate == "23505"
        runtime.rollback()
    with psycopg.connect(reservation_outcome_database_url) as verify:
        assert verify.execute(
            "SELECT status, version FROM app.reservations WHERE id = %s",
            (reservation2,),
        ).fetchone() == ("ACTIVE", 1)
        assert verify.execute(
            "SELECT status FROM app.units WHERE id = %s", (unit2,)
        ).fetchone() == ("RESERVED",)
        assert verify.execute(
            "SELECT count(*) FROM app.reservation_lifecycle_events WHERE id = %s",
            (failed_event,),
        ).fetchone() == (0,)


@pytest.mark.parametrize("responsibility", ["CUSTOMER", "PROPERTY"])
def test_correction_replaces_outcome_without_erasing_financial_history(
    reservation_outcome_database_url: str,
    responsibility: str,
) -> None:
    with psycopg.connect(reservation_outcome_database_url) as setup:
        actor_id, property_id, _, _, reservation_id = active_reservation(setup)
        setup.commit()
    original_id, correction_id, replacement_id = uuid4(), uuid4(), uuid4()
    with psycopg.connect(financial_database_url()) as runtime:
        row = cancel(
            runtime,
            actor_id=actor_id,
            property_id=property_id,
            reservation_id=reservation_id,
            idempotency_key=uuid4(),
            event_id=uuid4(),
            outcome_id=original_id,
            responsibility=responsibility,
            property_could_provide_unit=responsibility == "CUSTOMER",
            coordination_reference=None if responsibility == "CUSTOMER" else "CASE-CORRECT",
            refund_number=None if responsibility == "CUSTOMER" else "RF-ORIGINAL",
        )
        runtime.commit()
    replacement_number = None if responsibility == "CUSTOMER" else "RF-REPLACEMENT"
    # V1-056 slice 3b: the correction is a draft confirmed under financial.approve.
    with psycopg.connect(financial_database_url()) as runtime:
        corrected = correct_reservation_outcome(
            runtime,
            actor_id=actor_id,
            property_id=property_id,
            reservation_id=reservation_id,
            idempotency_key=uuid4(),
            correction_id=correction_id,
            expected_outcome_id=original_id,
            replacement_outcome_id=replacement_id,
            replacement_refund_number=replacement_number,
            reason="Correct duplicated external processing reference",
            evidence_reference="EVIDENCE-CASE-1",
        )
        runtime.commit()
    assert corrected is not None
    assert corrected[12] == replacement_id
    with psycopg.connect(reservation_outcome_database_url) as verify:
        if responsibility == "CUSTOMER":
            assert verify.execute(
                "SELECT deposit_disposition_id FROM app.deposit_disposition_reversals "
                "WHERE id = %s",
                (correction_id,),
            ).fetchone() == (original_id,)
            assert verify.execute(
                "SELECT count(*) FROM app.deposit_dispositions WHERE id IN (%s,%s)",
                (original_id, replacement_id),
            ).fetchone() == (2,)
        else:
            assert verify.execute(
                """
                SELECT refund_id, previous_net_refund_usd_cents,
                       resulting_net_refund_usd_cents
                FROM app.refund_corrections WHERE id = %s
                """,
                (correction_id,),
            ).fetchone() == (original_id, row[10], 0)
            assert verify.execute(
                "SELECT count(*) FROM app.refunds WHERE id IN (%s,%s)",
                (original_id, replacement_id),
            ).fetchone() == (2,)
        assert verify.execute(
            "SELECT count(*) FROM app.audit_events WHERE id IN (%s,%s)",
            (correction_id, replacement_id),
        ).fetchone() == (2,)


def test_concurrent_stale_outcome_correction_has_one_exact_winner(
    reservation_outcome_database_url: str,
) -> None:
    with psycopg.connect(reservation_outcome_database_url) as setup:
        actor_id, property_id, _, _, reservation_id = active_reservation(setup)
        setup.commit()
    original_id = uuid4()
    with psycopg.connect(financial_database_url()) as financial:
        cancel(
            financial,
            actor_id=actor_id,
            property_id=property_id,
            reservation_id=reservation_id,
            idempotency_key=uuid4(),
            event_id=uuid4(),
            outcome_id=original_id,
        )
        financial.commit()

    barrier = Barrier(2)
    attempts = [
        (uuid4(), uuid4(), uuid4(), "b" * 64),
        (uuid4(), uuid4(), uuid4(), "d" * 64),
    ]

    def correct(attempt: tuple[object, object, object, str]) -> str:
        idempotency_key, correction_id, replacement_id, digest = attempt
        with psycopg.connect(financial_database_url()) as financial:
            barrier.wait()
            try:
                # V1-056 slice 3b: each correction is a draft confirmed under financial.approve.
                del digest
                correct_reservation_outcome(
                    financial,
                    actor_id=actor_id,
                    property_id=property_id,
                    reservation_id=reservation_id,
                    idempotency_key=cast(UUID, idempotency_key),
                    correction_id=cast(UUID, correction_id),
                    expected_outcome_id=original_id,
                    replacement_outcome_id=cast(UUID, replacement_id),
                    replacement_refund_number=None,
                    reason="Correct concurrent external processing reference",
                    evidence_reference="EVIDENCE-CONCURRENT-CORRECTION",
                )
                financial.commit()
                return "success"
            except Error as error:
                financial.rollback()
                return str(error.sqlstate)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(correct, attempts))
    assert outcomes == ["40001", "success"]

    correction_ids = tuple(attempt[1] for attempt in attempts)
    replacement_ids = tuple(attempt[2] for attempt in attempts)
    with psycopg.connect(reservation_outcome_database_url) as verify:
        assert verify.execute(
            "SELECT count(*) FROM app.deposit_disposition_reversals "
            "WHERE deposit_disposition_id = %s",
            (original_id,),
        ).fetchone() == (1,)
        assert verify.execute(
            "SELECT count(*) FROM app.deposit_dispositions WHERE id = %s OR id IN (%s,%s)",
            (original_id, *replacement_ids),
        ).fetchone() == (2,)
        assert verify.execute(
            """
            SELECT count(*)
            FROM app.deposit_dispositions AS disposition
            WHERE disposition.governing_reservation_id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM app.deposit_disposition_reversals AS reversal
                  WHERE reversal.deposit_disposition_id = disposition.id
              )
            """,
            (reservation_id,),
        ).fetchone() == (1,)
        assert verify.execute(
            "SELECT count(*) FROM app.deposit_disposition_reversals WHERE id IN (%s,%s)",
            correction_ids,
        ).fetchone() == (1,)
        assert verify.execute(
            "SELECT count(*) FROM app.audit_events WHERE id IN (%s,%s,%s,%s)",
            (*correction_ids, *replacement_ids),
        ).fetchone() == (2,)


def test_financial_history_is_append_only_and_runtime_is_least_privilege(
    reservation_outcome_database_url: str,
) -> None:
    with psycopg.connect(reservation_outcome_database_url) as setup:
        actor_id, property_id, _, _, reservation_id = active_reservation(setup)
        setup.commit()
    outcome_id = uuid4()
    with psycopg.connect(financial_database_url()) as runtime:
        cancel(
            runtime,
            actor_id=actor_id,
            property_id=property_id,
            reservation_id=reservation_id,
            idempotency_key=uuid4(),
            event_id=uuid4(),
            outcome_id=outcome_id,
        )
        runtime.commit()
    with psycopg.connect(reservation_outcome_database_url) as owner:
        with pytest.raises(Error) as rewrite:
            owner.execute(
                "UPDATE app.deposit_dispositions SET reason = 'Rewritten' WHERE id = %s",
                (outcome_id,),
            )
        assert rewrite.value.sqlstate == "55000"
        owner.rollback()
        with pytest.raises(Error) as deletion:
            owner.execute("DELETE FROM app.deposit_dispositions WHERE id = %s", (outcome_id,))
        assert deletion.value.sqlstate == "55000"
        owner.rollback()
    with psycopg.connect(runtime_database_url()) as runtime:
        privileges = runtime.execute(
            """
            SELECT
                has_table_privilege(current_user, 'app.refunds', 'SELECT'),
                has_table_privilege(current_user, 'app.refunds', 'INSERT'),
                has_table_privilege(current_user, 'app.deposit_dispositions', 'UPDATE'),
                has_function_privilege(
                    current_user,
                    'app.correct_reservation_deposit_outcome(uuid,uuid,text,uuid,uuid,uuid,text,uuid,integer,text,text,text,text,uuid)',
                    'EXECUTE'
                )
            """
        ).fetchone()
    assert privileges == (True, False, False, False)
    with psycopg.connect(financial_database_url()) as financial:
        financial_privileges = financial.execute(
            """
            SELECT
                has_table_privilege(current_user, 'app.refunds', 'SELECT'),
                has_table_privilege(current_user, 'app.refunds', 'INSERT'),
                has_table_privilege(current_user, 'app.deposit_dispositions', 'UPDATE'),
                has_function_privilege(
                    current_user,
                    'app.cancel_reservation_v2(uuid,uuid,text,uuid,uuid,text,uuid,integer,text,text,boolean,text,text,text,text,uuid)',
                    'EXECUTE'
                ),
                has_function_privilege(
                    current_user,
                    'app.expire_reservation_v2(uuid,uuid,text,uuid,uuid,uuid,integer,boolean,text,text,uuid)',
                    'EXECUTE'
                ),
                has_function_privilege(
                    current_user,
                    'app.correct_reservation_deposit_outcome(uuid,uuid,text,uuid,uuid,uuid,text,uuid,integer,text,text,text,text,uuid)',
                    'EXECUTE'
                ),
                has_function_privilege(
                    current_user,
                    'app.complete_reservation_deposit_outcome(uuid,uuid,text,uuid,text,uuid,integer,text,text,uuid)',
                    'EXECUTE'
                )
            """
        ).fetchone()
    # V1-056 slice 3b: the one-call cancel, expire and correction functions are retired for the
    # financial role (owner answer to plan Q6); outcomes are confirmed drafts.
    assert financial_privileges == (True, False, False, False, False, False, False)


def test_reservation_outcome_migration_is_forward_only() -> None:
    migration = (
        Path(__file__).parents[1]
        / "migrations/versions/20260825_21_reservation_deposit_outcomes.py"
    )
    source = migration.read_text(encoding="utf-8")
    assert 'revision = "20260825_21"' in source
    assert 'down_revision = "20260825_20"' in source
    assert "Reservation Deposit outcome migration is forward-only" in source
