"""Synthetic financial fixture clocks must share the database event time domain."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta, tzinfo
from typing import Self, cast
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic import command
from alembic.config import Config

import test_refund_migration as refund_fixtures
import test_refund_service_migration as return_fixtures
from property_rental.refund import RefundUnavailableError
from test_credit_migration import actor, source
from test_invoice_migration import financial_database_url, runtime_database_url
from test_migrations import _required_url, _temporary_migration_database, _url_with_database
from test_reservation_migration import migrated_database_url  # noqa: F401


@pytest.fixture
def clock_database_url(
    migrated_database_url: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[str]:
    """Keep clock-only assertions independent of the full suite's relation locks."""
    del migrated_database_url  # Ensure the ordinary session database is initialized first.
    with _temporary_migration_database("prm_financial_clock") as migration_url:
        database = urlsplit(migration_url).path.removeprefix("/")
        with monkeypatch.context() as environment:
            for name in ("APP_DATABASE_URL", "FINANCIAL_DATABASE_URL"):
                environment.setenv(name, _url_with_database(_required_url(name), database))
            command.upgrade(Config("alembic.ini"), "head")
            yield migration_url


@pytest.mark.parametrize("host_offset_seconds", [-60, 60])
def test_financial_fixture_clock_ignores_host_skew_and_preserves_event_chronology(
    clock_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    host_offset_seconds: int,
) -> None:
    human, prop, customer, payment = source(clock_database_url, 1000)

    class ShiftedDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            return super().now(tz) + timedelta(seconds=host_offset_seconds)

    # No real clock is changed. Only these synthetic fixture modules see skew.
    monkeypatch.setattr(refund_fixtures, "datetime", ShiftedDateTime)
    monkeypatch.setattr(return_fixtures, "datetime", ShiftedDateTime)
    with psycopg.connect(clock_database_url) as connection:
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
    with psycopg.connect(clock_database_url) as connection:
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
    clock_database_url: str,
    invalid_offset_seconds: int,
) -> None:
    human, prop, customer, payment = source(clock_database_url, 1000)
    with psycopg.connect(clock_database_url) as connection:
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


def test_financial_clock_fixture_isolates_shared_relation_contention_without_weakening_nowait(
    migrated_database_url: str,  # noqa: F811
    clock_database_url: str,
) -> None:
    _, _, _, shared_payment = source(migrated_database_url, 1000)
    human, prop, customer, payment = source(clock_database_url, 1000)
    database = urlsplit(clock_database_url).path.removeprefix("/")
    assert database.startswith("prm_financial_clock_")
    assert urlsplit(migrated_database_url).path != urlsplit(clock_database_url).path
    for url in (clock_database_url, runtime_database_url(), financial_database_url()):
        with psycopg.connect(url) as connection:
            assert connection.execute("SELECT current_database()").fetchone() == (database,)
    with (
        psycopg.connect(migrated_database_url) as shared,
        psycopg.connect(migrated_database_url) as blocker,
    ):
        before = shared.execute(
            "SELECT to_jsonb(p) FROM app.payments p WHERE id=%s", (shared_payment,)
        ).fetchone()
        blocker.execute("LOCK TABLE app.invoices IN SHARE UPDATE EXCLUSIVE MODE")
        shared.execute("SET LOCAL lock_timeout='1000ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable) as failure, shared.transaction():
            shared.execute("SELECT app.assert_payment_excess_eligible(%s)", (shared_payment,))
        assert failure.value.sqlstate == "55P03"
        # The production NOWAIT guard remains active in the contended database.
        # Only the clock test's independent database is free of that unrelated lock.
        with psycopg.connect(clock_database_url) as connection:
            paid = refund_fixtures.refund(connection, human, customer, payment=payment, amount=800)
        current = return_fixtures.service().get(
            prop, paid, actor=actor(human, prop, "refunds.read")
        )
        assert current["net_refund_usd_cents"] == 800
        assert (
            shared.execute(
                "SELECT to_jsonb(p) FROM app.payments p WHERE id=%s", (shared_payment,)
            ).fetchone()
            == before
        )
        assert shared.execute(
            "SELECT count(*) FROM app.refunds WHERE source_payment_id=%s", (shared_payment,)
        ).fetchone() == (0,)
