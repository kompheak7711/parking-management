"""Strict Payment read envelopes, scoped authorization and safe transport."""

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.adapt import AdaptersMap
from psycopg.pq import Format
from psycopg.types.json import JsonbLoader

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.payment_read import (
    PaymentFilters,
    PaymentPage,
    PaymentReadAuthorizationError,
    PaymentReadInvalidError,
    PaymentReadNotFoundError,
    PaymentReadService,
    PaymentReadUnavailableError,
)


def staff(prop: UUID, cap: str = "payments.read") -> AuthenticatedActor:
    return AuthenticatedActor(
        str(uuid4()), frozenset({CapabilityGrant(cap, frozenset({str(prop)}))})
    )


@pytest.mark.parametrize("limit", [0, -1, 101, True, 1.5, "2"])
def test_payment_pages_reject_noninteger_or_unbounded_limits(limit: int) -> None:
    with pytest.raises(PaymentReadInvalidError):
        PaymentPage(limit)


@pytest.mark.parametrize(
    "day,identity",
    [
        (date(2026, 9, 6), None),
        (None, uuid4()),
        ("2026-09-06", uuid4()),
        (datetime(2026, 9, 6, tzinfo=UTC), uuid4()),
        (date(2026, 9, 6), UUID(int=0)),
        (date(2026, 9, 6), "not-a-uuid"),
    ],
)
def test_payment_cursor_requires_complete_typed_date_and_identity(
    day: date, identity: UUID
) -> None:
    with pytest.raises(PaymentReadInvalidError):
        PaymentPage(50, day, identity)


@pytest.mark.parametrize("status", ["PENDING", "PARTIALLY_ALLOCATED", "received", "", True, []])
def test_payment_filters_reject_invented_statuses_and_invalid_ids(status: str) -> None:
    with pytest.raises(PaymentReadInvalidError):
        PaymentFilters(status=status)
    for field in ("customer_id", "payment_method_id"):
        with pytest.raises(PaymentReadInvalidError):
            PaymentFilters(**{field: UUID(int=0)})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "cap", ["payments.record", "payments.allocate", "receipts.read", "credits.read"]
)
def test_payment_reads_require_separate_exact_property_capability(cap: str) -> None:
    prop = uuid4()
    service = PaymentReadService("unused")
    with patch("property_rental.payment_read.psycopg.connect") as connect:
        for reader in (staff(prop, cap), staff(uuid4())):
            with pytest.raises(PaymentReadAuthorizationError):
                service.list(prop, actor=reader)
            with pytest.raises(PaymentReadAuthorizationError):
                service.get(prop, uuid4(), actor=reader)
        connect.assert_not_called()


def connection() -> MagicMock:
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.adapters = AdaptersMap(psycopg.adapters)
    conn.execute.return_value.fetchone.return_value = (True, True)
    conn.execute.return_value.fetchall.return_value = []
    return conn


def test_payment_reads_use_bounded_readonly_repeatable_snapshot_and_exact_decimal_loader() -> None:
    prop, customer, method, after = uuid4(), uuid4(), uuid4(), uuid4()
    reader = staff(prop)
    conn = connection()
    with patch("property_rental.payment_read.psycopg.connect", return_value=conn) as connect:
        result = PaymentReadService("read-only-source").list(
            prop,
            PaymentPage(100, date(2026, 9, 6), after),
            PaymentFilters(customer, "RECEIVED", method),
            actor=reader,
        )
        assert result == {"items": [], "next_cursor": None, "limit": 100}
        connect.assert_called_once_with("read-only-source", connect_timeout=3)
        calls = conn.execute.call_args_list
        assert calls[0].args == ("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",)
        assert calls[1].args == ("SET LOCAL lock_timeout='3000ms'",)
        assert calls[2].args == ("SET LOCAL statement_timeout='5000ms'",)
        assert calls[3].args == ("SET LOCAL TIME ZONE 'UTC'",)
        assert calls[4].args[1] == (prop, UUID(reader.actor_id))
        assert calls[5].args[1] == (
            prop,
            customer,
            customer,
            "RECEIVED",
            "RECEIVED",
            method,
            method,
            date(2026, 9, 6),
            date(2026, 9, 6),
            after,
            101,
        )
        assert "LIMIT %s" in calls[5].args[0]
        loader_type = conn.adapters.get_loader(3802, Format.TEXT)
        assert loader_type is not None and issubclass(loader_type, JsonbLoader)
        exact = loader_type(3802).load(b'{"cents":9223372036854775807,"rate":4080.123456}')
        assert exact == {"cents": 9223372036854775807, "rate": "4080.123456"}


def test_payment_list_uses_exclusive_last_visible_cursor_without_extra_row_leak() -> None:
    prop = uuid4()
    identities = [str(uuid4()), str(uuid4())]
    rows = [{"payment": {"id": identity, "payment_date": "2026-09-06"}} for identity in identities]
    conn = connection()
    conn.execute.return_value.fetchall.return_value = [(row,) for row in rows]
    with patch("property_rental.payment_read.psycopg.connect", return_value=conn):
        result = PaymentReadService("unused").list(prop, PaymentPage(1), actor=staff(prop))
    assert result == {"items": rows[:1], "next_cursor": rows[0]["payment"], "limit": 1}


def test_payment_forged_envelopes_revalidated_before_connection() -> None:
    prop = uuid4()
    page = PaymentPage()
    filters = PaymentFilters()
    object.__setattr__(page, "limit", True)
    object.__setattr__(filters, "status", "PENDING")
    with patch("property_rental.payment_read.psycopg.connect") as connect:
        with pytest.raises(PaymentReadInvalidError):
            PaymentReadService("unused").list(prop, page, actor=staff(prop))
        with pytest.raises(PaymentReadInvalidError):
            PaymentReadService("unused").list(prop, filters=filters, actor=staff(prop))
        connect.assert_not_called()


@pytest.mark.parametrize("context", [(True, False), (False, False), None])
def test_payment_inactive_actor_never_queries_financial_rows(context: object) -> None:
    prop = uuid4()
    conn = connection()
    conn.execute.return_value.fetchone.return_value = context
    with patch("property_rental.payment_read.psycopg.connect", return_value=conn):
        with pytest.raises(PaymentReadAuthorizationError):
            PaymentReadService("unused").get(prop, uuid4(), actor=staff(prop))
    assert len(conn.execute.call_args_list) == 5


def test_payment_missing_property_and_payment_return_safe_not_found() -> None:
    prop = uuid4()
    conn = connection()
    with patch("property_rental.payment_read.psycopg.connect", return_value=conn):
        with pytest.raises(PaymentReadNotFoundError, match="Payment was not found"):
            PaymentReadService("unused").get(prop, uuid4(), actor=staff(prop))
        conn.execute.return_value.fetchone.return_value = (False, True)
        with pytest.raises(PaymentReadNotFoundError, match="Property was not found"):
            PaymentReadService("unused").list(prop, actor=staff(prop))


@pytest.mark.parametrize("sqlstate", ["42501", "40001", "57014", "08006", "23514"])
def test_payment_read_errors_redact_database_details(sqlstate: str) -> None:
    prop = uuid4()
    expected = PaymentReadAuthorizationError if sqlstate == "42501" else PaymentReadUnavailableError
    error = psycopg.errors.lookup(sqlstate)("sensitive database detail")
    with patch("property_rental.payment_read.psycopg.connect", side_effect=error):
        with pytest.raises(expected) as failure:
            PaymentReadService("unused").get(prop, uuid4(), actor=staff(prop))
        assert "sensitive" not in str(failure.value)


def test_payment_invalid_resource_or_actor_identity_fails_before_connection() -> None:
    prop = uuid4()
    valid = staff(prop)
    with patch("property_rental.payment_read.psycopg.connect") as connect:
        for identity in ("invalid", str(UUID(int=0))):
            reader = AuthenticatedActor(identity, valid.capability_grants)
            with pytest.raises(PaymentReadAuthorizationError):
                PaymentReadService("unused").list(prop, actor=reader)
        with pytest.raises(PaymentReadInvalidError):
            PaymentReadService("unused").get(prop, UUID(int=0), actor=valid)
        connect.assert_not_called()
