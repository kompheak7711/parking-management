"""Allocation proposal reads do not inherit stale human authority or move money."""

from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.pq import Format

from property_rental.allocation_read import AllocationHistoryPage, AllocationReadService
from property_rental.payment_allocation import (
    AllocationAuthorizationError,
    AllocationConflictError,
    AllocationInvalidError,
    AllocationNotFoundError,
    AllocationUnavailableError,
)
from test_payment_read import connection, staff


@pytest.mark.parametrize("capability", ["payments.read", "payments.record", "receipts.read"])
def test_allocation_proposal_read_requires_its_own_exact_property_capability(
    capability: str,
) -> None:
    prop = uuid4()
    with patch("property_rental.allocation_read.psycopg.connect") as connect:
        for who in (staff(prop, capability), staff(uuid4(), "payments.allocate")):
            with pytest.raises(AllocationAuthorizationError):
                AllocationReadService("unused").proposal(prop, uuid4(), actor=who)
        connect.assert_not_called()


def test_allocation_proposal_read_snapshot_exact_loader_and_bounded_existing_producer() -> None:
    prop, payment = uuid4(), uuid4()
    who = staff(prop, "payments.allocate")
    proposal = {
        "payment_id": str(payment),
        "targets": [],
        "available_usd_cents": 9_000_000_000_000_000,
    }
    conn = connection()
    conn.execute.return_value.fetchone.side_effect = [(True, True), (proposal,)]
    with patch("property_rental.allocation_read.psycopg.connect", return_value=conn) as connect:
        assert AllocationReadService("runtime-only").proposal(prop, payment, actor=who) == proposal
        connect.assert_called_once_with("runtime-only", connect_timeout=3)
    calls = conn.execute.call_args_list
    assert [call.args[0] for call in calls[:4]] == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
        "SET LOCAL lock_timeout='3000ms'",
        "SET LOCAL statement_timeout='5000ms'",
        "SET LOCAL TIME ZONE 'UTC'",
    ]
    assert calls[4].args[1] == (prop, UUID(who.actor_id))
    assert "identity.identity_kind='HUMAN'" in calls[4].args[0]
    assert calls[5].args[0] == "SELECT app.payment_allocation_proposal(%s,%s,clock_timestamp(),%s)"
    assert calls[5].args[1][:2] == (prop, payment)
    assert isinstance(calls[5].args[1][2], UUID) and calls[5].args[1][2].int != 0
    assert len(calls) == 6
    loader = conn.adapters.get_loader(3802, Format.TEXT)
    assert loader is not None
    assert loader(3802).load(b'{"cents":9223372036854775807,"rate":4080.123456}') == {
        "cents": 9223372036854775807,
        "rate": "4080.123456",
    }


@pytest.mark.parametrize("context", [None, (True, False), (False, False)])
def test_allocation_proposal_read_checks_fresh_human_before_financial_query(
    context: object,
) -> None:
    prop = uuid4()
    conn = connection()
    conn.execute.return_value.fetchone.return_value = context
    with patch("property_rental.allocation_read.psycopg.connect", return_value=conn):
        with pytest.raises(AllocationAuthorizationError):
            AllocationReadService("unused").proposal(
                prop, uuid4(), actor=staff(prop, "payments.allocate")
            )
    assert len(conn.execute.call_args_list) == 5


def test_allocation_proposal_read_missing_property_and_invalid_identity_fail_closed() -> None:
    prop = uuid4()
    who = staff(prop, "payments.allocate")
    conn = connection()
    conn.execute.return_value.fetchone.return_value = (False, True)
    with patch("property_rental.allocation_read.psycopg.connect", return_value=conn) as connect:
        with pytest.raises(AllocationInvalidError):
            AllocationReadService("unused").proposal(prop, UUID(int=0), actor=who)
        connect.assert_not_called()
        with pytest.raises(AllocationNotFoundError):
            AllocationReadService("unused").proposal(prop, uuid4(), actor=who)
    assert len(conn.execute.call_args_list) == 5


@pytest.mark.parametrize(
    "code,expected",
    [
        ("P4901", AllocationNotFoundError),
        ("P0002", AllocationNotFoundError),
        ("42501", AllocationAuthorizationError),
        ("P4506", AllocationAuthorizationError),
        ("P4904", AllocationConflictError),
        ("P4902", AllocationInvalidError),
        ("40001", AllocationUnavailableError),
        ("57014", AllocationUnavailableError),
        ("08006", AllocationUnavailableError),
    ],
)
def test_allocation_proposal_read_safe_database_failure_mapping(
    code: str, expected: type[Exception]
) -> None:
    prop = uuid4()
    error = type("DatabaseFailure", (psycopg.Error,), {"sqlstate": code})("private SQL evidence")
    with patch("property_rental.allocation_read.psycopg.connect", side_effect=error):
        with pytest.raises(expected) as caught:
            AllocationReadService("unused").proposal(
                prop, uuid4(), actor=staff(prop, "payments.allocate")
            )
        assert "private" not in str(caught.value)


@pytest.mark.parametrize("row", [None, (), (None,), ([],), ({}, {})])
def test_allocation_proposal_read_rejects_invalid_database_shape(row: object) -> None:
    prop = uuid4()
    conn = connection()
    conn.execute.return_value.fetchone.side_effect = [(True, True), row]
    with patch("property_rental.allocation_read.psycopg.connect", return_value=conn):
        with pytest.raises(AllocationUnavailableError):
            AllocationReadService("unused").proposal(
                prop, uuid4(), actor=staff(prop, "payments.allocate")
            )


@pytest.mark.parametrize("limit", [0, -1, 101, True, 1.5, "2"])
def test_allocation_history_rejects_unbounded_or_coerced_pages(limit: int) -> None:
    with pytest.raises(AllocationInvalidError):
        AllocationHistoryPage(limit)


@pytest.mark.parametrize("capability", ["payments.allocate", "payments.reverse", "receipts.read"])
def test_allocation_history_requires_separate_read_capability_before_connection(
    capability: str,
) -> None:
    prop = uuid4()
    with patch("property_rental.allocation_read.psycopg.connect") as connect:
        for who in (staff(prop, capability), staff(uuid4())):
            with pytest.raises(AllocationAuthorizationError):
                AllocationReadService("unused").history(prop, uuid4(), actor=who)
        connect.assert_not_called()


@pytest.mark.parametrize("context", [None, (True, False), (False, False)])
def test_allocation_history_disabled_actor_cannot_query_payment_evidence(context: object) -> None:
    prop = uuid4()
    conn = connection()
    conn.execute.return_value.fetchone.return_value = context
    with patch("property_rental.allocation_read.psycopg.connect", return_value=conn):
        with pytest.raises(AllocationAuthorizationError):
            AllocationReadService("unused").history(prop, uuid4(), actor=staff(prop))
    assert len(conn.execute.call_args_list) == 5


def test_allocation_history_cursor_keeps_exact_payment_and_selected_allocation() -> None:
    prop, payment, allocation, first, following = (uuid4() for _ in range(5))
    conn = connection()
    conn.execute.return_value.fetchone.side_effect = [
        (True, True),
        (payment,),
        ({"id": str(allocation), "proposal_trace": {"amount": 9_223_372_036_854_775_807}},),
    ]
    conn.execute.return_value.fetchall.return_value = [
        ({"id": str(first)},),
        ({"id": str(following)},),
    ]
    with patch("property_rental.allocation_read.psycopg.connect", return_value=conn):
        result = AllocationReadService("unused").history(
            prop, payment, AllocationHistoryPage(1), actor=staff(prop), allocation_id=allocation
        )
    assert result["items"] == [{"id": str(first)}]
    assert result["next_cursor"] == {
        "payment_id": str(payment),
        "allocation_id": str(allocation),
        "after_id": str(first),
    }
    assert result["allocation"] == {
        "id": str(allocation),
        "proposal_trace": {"amount": 9_223_372_036_854_775_807},
    }


def test_allocation_history_response_budget_rejects_without_silently_removing_evidence() -> None:
    prop, payment = uuid4(), uuid4()
    conn = connection()
    conn.execute.return_value.fetchone.side_effect = [(True, True), (payment,)]
    conn.execute.return_value.fetchall.return_value = [
        ({"id": str(uuid4()), "invalid": "x" * 1_048_577},)
    ]
    with patch("property_rental.allocation_read.psycopg.connect", return_value=conn):
        with pytest.raises(AllocationUnavailableError):
            AllocationReadService("unused").history(prop, payment, actor=staff(prop))


@pytest.mark.parametrize("code", ["40001", "57014", "08006"])
def test_allocation_history_database_failures_are_safe(code: str) -> None:
    prop = uuid4()
    error = type("DatabaseFailure", (psycopg.Error,), {"sqlstate": code})("private SQL")
    with patch("property_rental.allocation_read.psycopg.connect", side_effect=error):
        with pytest.raises(
            AllocationUnavailableError, match=r"^Allocation history is unavailable$"
        ):
            AllocationReadService("unused").history(prop, uuid4(), actor=staff(prop))
