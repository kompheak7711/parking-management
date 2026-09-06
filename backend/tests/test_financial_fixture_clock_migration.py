"""Synthetic financial fixture clocks must share the database event time domain."""

from dataclasses import replace
from datetime import datetime, timedelta, tzinfo
from typing import Self, cast

import psycopg
import pytest

import test_refund_migration as refund_fixtures
import test_refund_service_migration as return_fixtures
from property_rental.refund import RefundUnavailableError
from test_credit_migration import actor, source
from test_reservation_migration import migrated_database_url  # noqa: F401


@pytest.mark.parametrize("host_offset_seconds", [-60, 60])
def test_financial_fixture_clock_ignores_host_skew_and_preserves_event_chronology(
    migrated_database_url: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    host_offset_seconds: int,
) -> None:
    human, prop, customer, payment = source(migrated_database_url, 1000)

    class ShiftedDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            return super().now(tz) + timedelta(seconds=host_offset_seconds)

    # No real clock is changed. Only these synthetic fixture modules see skew.
    monkeypatch.setattr(refund_fixtures, "datetime", ShiftedDateTime)
    monkeypatch.setattr(return_fixtures, "datetime", ShiftedDateTime)
    with psycopg.connect(migrated_database_url) as connection:
        payment_before = connection.execute(
            "SELECT to_jsonb(p) FROM app.payments p WHERE id=%s", (payment,)
        ).fetchone()
        refund = refund_fixtures.refund(connection, human, customer, payment=payment, amount=800)
        correction = refund_fixtures.correct(connection, human, refund, 100)
        original = connection.execute(
            "SELECT to_jsonb(r) FROM app.refunds r WHERE id=%s", (refund,)
        ).fetchone()
        first = connection.execute(
            "SELECT to_jsonb(c) FROM app.refund_corrections c WHERE id=%s", (correction,)
        ).fetchone()
        assert original is not None and first is not None and payment_before is not None
    request = return_fixtures.returned(100)
    result = return_fixtures.service().verify_usd_return(
        prop, refund, request, actor=actor(human, prop, "refunds.correct")
    )
    assert result["net_refund_usd_cents"] == 600
    with psycopg.connect(migrated_database_url) as connection:
        ordered = connection.execute(
            "SELECT p.confirmed_at<r.processed_at,"
            "bool_and(c.verified_returned_at>=r.processed_at "
            "AND c.verified_returned_at<=c.occurred_at),count(c.id) "
            "FROM app.payments p JOIN app.refunds r ON r.source_payment_id=p.id "
            "JOIN app.refund_corrections c ON c.refund_id=r.id "
            "WHERE r.id=%s GROUP BY p.confirmed_at,r.processed_at",
            (refund,),
        ).fetchone()
        assert ordered == (True, True, 2)
        assert (
            connection.execute(
                "SELECT to_jsonb(p) FROM app.payments p WHERE id=%s", (payment,)
            ).fetchone()
            == payment_before
        )
        assert (
            connection.execute(
                "SELECT to_jsonb(r) FROM app.refunds r WHERE id=%s", (refund,)
            ).fetchone()
            == original
        )
        assert (
            connection.execute(
                "SELECT to_jsonb(c) FROM app.refund_corrections c WHERE id=%s", (correction,)
            ).fetchone()
            == first
        )


@pytest.mark.parametrize("invalid_offset_seconds", [-60, 60])
def test_financial_fixture_clock_does_not_relax_invalid_refund_or_return_chronology(
    migrated_database_url: str,  # noqa: F811
    invalid_offset_seconds: int,
) -> None:
    human, prop, customer, payment = source(migrated_database_url, 1000)
    with psycopg.connect(migrated_database_url) as connection:
        paid = refund_fixtures.refund(connection, human, customer, payment=payment, amount=800)
        row = connection.execute(
            "SELECT processed_at,to_jsonb(r) FROM app.refunds r WHERE id=%s", (paid,)
        ).fetchone()
        assert row is not None and isinstance(row[0], datetime)
        invalid_at = row[0] + timedelta(seconds=invalid_offset_seconds)
        with pytest.raises(psycopg.Error) as failure, connection.transaction():
            refund_fixtures.refund(
                connection,
                human,
                customer,
                payment=payment,
                amount=1,
                overrides={"processed_at": invalid_at},
            )
        assert failure.value.sqlstate == "23514"
    request = replace(return_fixtures.returned(100), returned_at=invalid_at)
    with pytest.raises(RefundUnavailableError) as invalid_return:
        return_fixtures.service().verify_usd_return(
            prop, paid, request, actor=actor(human, prop, "refunds.correct")
        )
    assert isinstance(invalid_return.value.__cause__, psycopg.Error)
    assert invalid_return.value.__cause__.sqlstate == "23514"
    current = return_fixtures.service().get(prop, paid, actor=actor(human, prop, "refunds.read"))
    assert current["refund"] == row[1] and current["net_refund_usd_cents"] == 800
    assert cast(dict[str, object], current["corrections"])["items"] == []
