"""Preview capability, coherent read-only transport and safe failure boundaries."""

from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.pq import Format

from property_rental.allocation_read import AllocationReadService
from property_rental.credit import (
    CreditAuthorizationError,
    CreditConflictError,
    CreditInvalidError,
    CreditNotFoundError,
    CreditUnavailableError,
    CustomerCreditService,
)
from property_rental.payment_allocation import (
    AllocationAuthorizationError,
    AllocationConflictError,
    AllocationInvalidError,
    AllocationNotFoundError,
    AllocationUnavailableError,
)
from test_due_preview import KINDS, Kind, selection
from test_payment_read import connection, staff


def service(kind: Kind) -> Any:
    if kind == "PAYMENT":
        return AllocationReadService("preview-read").designation_preview
    return CustomerCreditService("preview-read", "financial-never").application_preview


def capability(kind: Kind) -> str:
    return "payments.allocate" if kind == "PAYMENT" else "credits.apply"


def module(kind: Kind) -> str:
    return "property_rental." + ("allocation_read" if kind == "PAYMENT" else "credit")


@pytest.mark.parametrize("kind", KINDS)
def test_due_preview_service_uses_readonly_runtime_and_seals_selection_before_connect(
    kind: Kind,
) -> None:
    prop, money = uuid4(), uuid4()
    actor = staff(prop, capability(kind))
    original = selection(kind, "explicit")
    conn = connection()
    result = {"property_id": str(prop), "amount_usd_cents": 100, "intent": original.copy()}
    conn.execute.return_value.fetchone.return_value = (result,)

    def connect_and_mutate(*args: object, **kwargs: object) -> Any:
        original["designation_reference"] = "Changed after capture"
        return conn

    with patch(module(kind) + ".psycopg.connect", side_effect=connect_and_mutate) as connect:
        assert service(kind)(prop, money, original, actor=actor) == result
        connect.assert_called_once_with("preview-read", connect_timeout=3)
    calls = conn.execute.call_args_list
    assert [call.args[0] for call in calls[:4]] == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
        "SET LOCAL lock_timeout='3000ms'",
        "SET LOCAL statement_timeout='5000ms'",
        "SET LOCAL TIME ZONE 'UTC'",
    ]
    name = "payment_allocation" if kind == "PAYMENT" else "credit_application"
    assert calls[4].args[0] == f"SELECT app.{name}_designation_preview(%s,%s,%s,%s)"
    parameters = calls[4].args[1]
    assert parameters[:3] == (prop, money, UUID(actor.actor_id))
    assert len(parameters) == 4
    assert parameters[3].obj["designation_reference"] == "Customer instruction"
    assert len(calls) == 5
    loader = conn.adapters.get_loader(3802, Format.TEXT)
    assert loader is not None
    assert loader(3802).load(b'{"cents":9223372036854775807,"rate":4080.125}') == {
        "cents": 9223372036854775807,
        "rate": "4080.125",
    }


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("case", ["missing", "wrong_property", "wrong_action"])
def test_due_preview_service_denies_wrong_capability_before_connection(
    kind: Kind, case: str
) -> None:
    prop = uuid4()
    actor = staff(
        uuid4() if case == "wrong_property" else prop,
        *(
            []
            if case == "missing"
            else ["credits.read" if case == "wrong_action" else capability(kind)]
        ),
    )
    expected = AllocationAuthorizationError if kind == "PAYMENT" else CreditAuthorizationError
    with patch(module(kind) + ".psycopg.connect") as connect:
        with pytest.raises(expected):
            service(kind)(prop, uuid4(), selection(kind), actor=actor)
        connect.assert_not_called()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("case", ["source", "property", "intent"])
def test_due_preview_service_rejects_invalid_inputs_without_connection(
    kind: Kind, case: str
) -> None:
    prop = UUID(int=0) if case == "property" else uuid4()
    source = UUID(int=0) if case == "source" else uuid4()
    intent = selection(kind)
    if case == "intent":
        intent["mode"] = "PROPOSAL"
    expected = AllocationInvalidError if kind == "PAYMENT" else CreditInvalidError
    with patch(module(kind) + ".psycopg.connect") as connect:
        with pytest.raises(expected):
            service(kind)(prop, source, intent, actor=staff(prop, capability(kind)))
        connect.assert_not_called()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "category",
    [
        "missing",
        "invalid",
        "conflict",
        "actor",
        "permission",
        "timeout",
        "serialization",
        "connection",
    ],
)
def test_due_preview_service_maps_database_errors_without_command_recovery(
    kind: Kind, category: str
) -> None:
    prefix = "P49" if kind == "PAYMENT" else "P51"
    code = {
        "missing": prefix + "01",
        "invalid": prefix + "02",
        "conflict": prefix + "04",
        "actor": "P4506",
        "permission": "42501",
        "timeout": "57014",
        "serialization": "40001",
        "connection": "08006",
    }[category]
    classes = (
        (
            AllocationNotFoundError,
            AllocationInvalidError,
            AllocationConflictError,
            AllocationAuthorizationError,
            AllocationUnavailableError,
        )
        if kind == "PAYMENT"
        else (
            CreditNotFoundError,
            CreditInvalidError,
            CreditConflictError,
            CreditAuthorizationError,
            CreditUnavailableError,
        )
    )
    index = {"missing": 0, "invalid": 1, "conflict": 2, "actor": 3, "permission": 3}.get(
        category, 4
    )
    error = type("PreviewFailure", (psycopg.Error,), {"sqlstate": code})("private database text")
    prop = uuid4()
    with patch(module(kind) + ".psycopg.connect", side_effect=error):
        with pytest.raises(classes[index]) as caught:
            service(kind)(prop, uuid4(), selection(kind), actor=staff(prop, capability(kind)))
    assert "private" not in str(caught.value)
    assert "replay" not in str(caught.value) and "command" not in str(caught.value)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("row", [None, (), (None,), ([],), ({}, {})])
def test_due_preview_service_missing_or_malformed_result_is_unavailable(
    kind: Kind, row: object
) -> None:
    prop = uuid4()
    conn = connection()
    conn.execute.return_value.fetchone.return_value = row
    expected = AllocationUnavailableError if kind == "PAYMENT" else CreditUnavailableError
    with patch(module(kind) + ".psycopg.connect", return_value=conn):
        with pytest.raises(expected):
            service(kind)(prop, uuid4(), selection(kind), actor=staff(prop, capability(kind)))
