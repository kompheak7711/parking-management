"""Credit read cursors, independent permissions and read-connection boundaries."""

from datetime import UTC, datetime, timedelta, timezone
from typing import cast
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from property_rental.credit import (
    CreditAuthorizationError,
    CreditInvalidError,
    CreditLedgerPage,
    CreditPage,
    CustomerCreditService,
)
from test_credit import staff


@pytest.mark.parametrize("limit", [0, 101, -1, True, 1.5, "1"])
def test_credit_read_pages_reject_noninteger_or_unbounded_limits(limit: object) -> None:
    with pytest.raises(CreditInvalidError):
        CreditPage(cast(int, limit))
    with pytest.raises(CreditInvalidError):
        CreditLedgerPage(cast(int, limit))


@pytest.mark.parametrize("invalid", ["partial", "naive", "nil", "kind", "missing_kind"])
def test_credit_read_cursors_require_complete_finite_typed_identity(invalid: str) -> None:
    at, identity = datetime.now(UTC), uuid4()
    values = {
        "partial": (None, "RECOGNITION", identity),
        "naive": (datetime(2026, 1, 1), "RECOGNITION", identity),
        "nil": (at, "RECOGNITION", UUID(int=0)),
        "kind": (at, "UNKNOWN", identity),
        "missing_kind": (at, None, identity),
    }
    instant, kind, key = values[invalid]
    with pytest.raises(CreditInvalidError):
        CreditLedgerPage(1, instant, kind, key)


def test_credit_cursor_normalizes_utc_and_revalidates_at_transmission() -> None:
    at = datetime(2026, 9, 6, 7, tzinfo=timezone(timedelta(hours=7)))
    identity = uuid4()
    assert CreditPage(1, at, identity).after_at == datetime(2026, 9, 6, tzinfo=UTC)
    page = CreditLedgerPage(1, at, "APPLICATION", identity)
    object.__setattr__(page, "after_kind", "UNKNOWN")
    prop = uuid4()
    with patch("property_rental.credit.psycopg.connect") as connect:
        with pytest.raises(CreditInvalidError):
            CustomerCreditService("read", "write").ledger(
                prop, uuid4(), page, actor=staff(prop, "credits.read")
            )
        connect.assert_not_called()


@pytest.mark.parametrize("operation", ["list", "ledger"])
def test_credit_reads_require_independent_exact_property_capability(operation: str) -> None:
    prop, identity = uuid4(), uuid4()
    with patch("property_rental.credit.psycopg.connect") as connect:
        for actor in (
            staff(prop, "credits.recognize", "refunds.read"),
            staff(uuid4(), "credits.read"),
            staff(prop),
        ):
            with pytest.raises(CreditAuthorizationError):
                getattr(CustomerCreditService("read", "write"), operation)(
                    prop, identity, actor=actor
                )
        connect.assert_not_called()


@pytest.mark.parametrize("operation", ["list", "ledger"])
def test_credit_reads_transmit_only_validated_identity_and_read_connection(operation: str) -> None:
    prop, identity, event_id = uuid4(), uuid4(), uuid4()
    actor = staff(prop, "credits.read")
    instant = datetime.now(UTC)
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = ({"items": []},)
    with patch("property_rental.credit.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        service = CustomerCreditService("read", "write")
        expected: tuple[object, ...]
        if operation == "list":
            service.list(prop, identity, CreditPage(4, instant, event_id), actor=actor)
            expected = (prop, identity, UUID(actor.actor_id), 4, instant, event_id)
        else:
            service.ledger(
                prop, identity, CreditLedgerPage(4, instant, "REFUND", event_id), actor=actor
            )
            expected = (prop, identity, UUID(actor.actor_id), 4, instant, "REFUND", event_id)
        connect.assert_called_once_with("read", connect_timeout=3)
        assert connection.execute.call_args.args[1] == expected
