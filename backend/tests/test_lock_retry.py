"""Bounded replay after a NOWAIT lock refusal (DL-067, slice 9f-4)."""

from __future__ import annotations

import psycopg
import pytest

from property_rental import lock_retry
from property_rental.lock_retry import retry_lock_not_available


def _error(sqlstate: str | None) -> psycopg.Error:
    class DatabaseError(psycopg.Error):
        pass

    error = DatabaseError("Synthetic database error")
    error.sqlstate = sqlstate
    return error


@pytest.fixture
def pauses(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(lock_retry, "_pause", recorded.append)
    return recorded


def test_lock_retry_returns_first_success_without_pausing(pauses: list[float]) -> None:
    calls: list[int] = []

    def attempt() -> str:
        calls.append(1)
        return "done"

    assert retry_lock_not_available(attempt) == "done"
    assert calls == [1]
    assert pauses == []


def test_lock_retry_replays_after_lock_refusal_until_success(pauses: list[float]) -> None:
    outcomes: list[psycopg.Error | str] = [_error("55P03"), _error("55P03"), "done"]

    def attempt() -> str:
        outcome = outcomes.pop(0)
        if isinstance(outcome, psycopg.Error):
            raise outcome
        return outcome

    assert retry_lock_not_available(attempt) == "done"
    assert outcomes == []
    assert pauses == [0.25, 0.5]


def test_lock_retry_stops_after_three_replays_with_the_last_error(pauses: list[float]) -> None:
    errors = [_error("55P03") for _ in range(4)]
    calls: list[int] = []

    def attempt() -> str:
        calls.append(1)
        raise errors[len(calls) - 1]

    with pytest.raises(psycopg.Error) as caught:
        retry_lock_not_available(attempt)
    assert caught.value is errors[3]
    assert len(calls) == 4
    assert pauses == [0.25, 0.5, 1.0]


@pytest.mark.parametrize("sqlstate", ["40001", "40P01", "57014", "P5102", None])
def test_lock_retry_never_replays_other_errors(pauses: list[float], sqlstate: str | None) -> None:
    error = _error(sqlstate)
    calls: list[int] = []

    def attempt() -> str:
        calls.append(1)
        raise error

    with pytest.raises(psycopg.Error) as caught:
        retry_lock_not_available(attempt)
    assert caught.value is error
    assert calls == [1]
    assert pauses == []


@pytest.mark.parametrize("service_name", ["credit", "refund"])
def test_lock_retry_replays_the_same_service_command_in_a_new_connection(
    pauses: list[float], service_name: str
) -> None:
    from unittest.mock import MagicMock, patch
    from uuid import uuid4

    from property_rental.credit import CustomerCreditService, RecognizeCreditCommand
    from property_rental.refund import RefundService
    from test_credit import staff

    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = ({"id": "synthetic"},)
    opened = MagicMock()
    opened.__enter__.return_value = connection
    prop = uuid4()
    with patch(
        f"property_rental.{service_name}.psycopg.connect",
        side_effect=[_error("55P03"), opened],
    ) as connect:
        if service_name == "credit":
            request = RecognizeCreditCommand(uuid4(), 100, "Payer consent", "Retain excess")
            result = CustomerCreditService("read", "write").recognize(
                prop, uuid4(), request, actor=staff(prop, "credits.recognize")
            )
        else:
            # V1-056 slice 3a: a Refund is created by confirming its draft.
            result = RefundService("read", "write").confirm_draft(
                prop, uuid4(), actor=staff(prop, "financial.approve")
            )
    assert result == {"id": "synthetic"}
    assert connect.call_count == 2
    assert connect.call_args_list[0] == connect.call_args_list[1]
    command = [call for call in connection.execute.call_args_list if "SELECT" in call.args[0]]
    assert len(command) == 1
    assert pauses == [0.25]
