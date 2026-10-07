"""Exact money, independent positions and safe Customer ledger paging contracts."""

import base64
import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from property_rental.customer_ledger import (
    EVENT_ORDER,
    LedgerCursor,
    LedgerEventKey,
    LedgerFilter,
    LedgerInvalidError,
    LedgerPage,
    LedgerPosition,
    LedgerReconciliationError,
    LedgerSnapshotChangedError,
    exact_cents,
)


@pytest.mark.parametrize("value", [0, 10**40, "900719925474099300001", Decimal("123.000")])
def test_ledger_money_preserves_exact_integers_beyond_browser_range(value: object) -> None:
    expected = "123" if isinstance(value, Decimal) else str(int(str(value)))
    assert str(exact_cents(value)) == expected


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        1.0,
        "1.0",
        "01",
        "+1",
        "-0",
        " 1",
        "1e3",
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("1.01"),
        Decimal("1e1000000"),
        10**64,
        -1,
        None,
    ],
)
def test_ledger_money_rejects_inexact_noncanonical_and_unbounded_values(value: object) -> None:
    with pytest.raises(LedgerInvalidError):
        exact_cents(value)


def test_ledger_position_keeps_liabilities_and_available_funds_out_of_total_owed() -> None:
    position = LedgerPosition(
        invoice=21000,
        charge=2100,
        credit=30000,
        payment=5000,
        security_deposit=100000,
        pet_deposit=20000,
    )
    assert position.total_owed == 23100
    assert position.as_wire() == {
        "invoice_usd_cents": "21000",
        "charge_usd_cents": "2100",
        "total_owed_usd_cents": "23100",
        "credit_usd_cents": "30000",
        "payment_usd_cents": "5000",
        "security_deposit_usd_cents": "100000",
        "pet_deposit_usd_cents": "20000",
    }
    with pytest.raises(FrozenInstanceError):
        position.invoice = 0  # type: ignore[misc]
    assert LedgerPosition(10**40, 10**40).as_wire()["total_owed_usd_cents"] == str(2 * 10**40)


def test_ledger_reconciliation_detects_equal_total_with_wrong_composition() -> None:
    LedgerPosition(20000, 1000).reconcile(LedgerPosition(20000, 1000))
    with pytest.raises(LedgerReconciliationError):
        LedgerPosition(20000, 1000).reconcile(LedgerPosition(19000, 2000))
    with pytest.raises(LedgerReconciliationError):
        LedgerPosition(payment=1000).reconcile(LedgerPosition(credit=1000))
    with pytest.raises(LedgerInvalidError):
        LedgerPosition(invoice=-1)
    assert exact_cents("-100", signed=True) == -100


def test_ledger_equal_time_order_and_filter_are_deterministic_across_timezones() -> None:
    at = datetime(2026, 9, 9, 3, tzinfo=UTC)
    local = at.astimezone(timezone(timedelta(hours=7)))
    small, large = UUID(int=1), UUID(int=2)
    keys = [
        LedgerEventKey(local, "PAYMENT_RECEIVED", large),
        LedgerEventKey(at, "INVOICE_ISSUED", large),
        LedgerEventKey(at, "PAYMENT_RECEIVED", small),
    ]
    assert sorted(keys, key=lambda key: key.order) == [keys[1], keys[2], keys[0]]
    filters = LedgerFilter(local, local, "PAYMENT_RECEIVED")
    assert [key for key in keys if filters.includes(key)] == [keys[0], keys[2]]
    # Sub-slice 8a-2 adds DEPOSIT_APPLIED, 10c-2a-1 DEPOSIT_APPLICATION_REVERSED (docs/010).
    assert len(EVENT_ORDER) == 25


def test_ledger_cursor_round_trip_binds_scope_filters_and_source_revision() -> None:
    prop, customer = uuid4(), uuid4()
    at = datetime(2026, 9, 9, 3, tzinfo=UTC)
    filters = LedgerFilter(through_instant=at)
    scope = filters.fingerprint(prop, customer)
    cursor = LedgerCursor(scope, "a" * 64, LedgerEventKey(at, "PAYMENT_RECEIVED", uuid4()))
    assert LedgerCursor.decode(cursor.encode()) == cursor
    cursor.validate_snapshot(scope=scope, revision="a" * 64)
    with pytest.raises(LedgerSnapshotChangedError):
        cursor.validate_snapshot(scope=scope, revision="b" * 64)
    for changed in (
        filters.fingerprint(prop, uuid4()),
        filters.fingerprint(uuid4(), customer),
        LedgerFilter().fingerprint(prop, customer),
        LedgerFilter(event_kind="REFUND_PAID").fingerprint(prop, customer),
    ):
        with pytest.raises(LedgerInvalidError):
            cursor.validate_snapshot(scope=changed, revision="a" * 64)
    assert LedgerPage(100, filters, cursor).cursor == cursor


@pytest.mark.parametrize("value", ["", "x" * 1025, "garbage", "W10=", "!!!!", "null", "e30="])
def test_ledger_cursor_rejects_invalid_untrusted_encoding(value: str) -> None:
    with pytest.raises(LedgerInvalidError):
        LedgerCursor.decode(value)


@pytest.mark.parametrize(
    "index,value",
    [
        (0, True),
        (0, 2),
        (1, "a"),
        (2, "x" * 64),
        (3, "2026-09-09"),
        (4, "INVENTED"),
        (5, str(UUID(int=0))),
    ],
)
def test_ledger_cursor_rejects_invalid_fields(index: int, value: object) -> None:
    payload: list[object] = [
        1,
        "a" * 64,
        "b" * 64,
        "2026-09-09T03:00:00+00:00",
        "PAYMENT_RECEIVED",
        str(uuid4()),
    ]
    payload[index] = value
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    with pytest.raises(LedgerInvalidError):
        LedgerCursor.decode(encoded)


@pytest.mark.parametrize("limit", [0, 101, True, 1.0, "1"])
def test_ledger_page_requires_strict_bounded_limit(limit: int) -> None:
    with pytest.raises(LedgerInvalidError):
        LedgerPage(limit)


def test_ledger_filter_requires_aware_ordered_dates_and_known_event_kinds() -> None:
    at = datetime(2026, 9, 9, tzinfo=UTC)
    with pytest.raises(LedgerInvalidError):
        LedgerFilter(at, at - timedelta(seconds=1))
    with pytest.raises(LedgerInvalidError):
        LedgerFilter(datetime(2026, 9, 9))
    with pytest.raises(LedgerInvalidError):
        LedgerFilter(event_kind="journal")
    with pytest.raises(LedgerInvalidError):
        LedgerFilter().fingerprint(UUID(int=0), uuid4())
