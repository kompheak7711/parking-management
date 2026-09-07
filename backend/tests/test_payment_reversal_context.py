"""Exact scope, continuation, coherent reads and fail-closed context handling."""

from copy import deepcopy
from typing import cast
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.identity import AuthenticatedActor, CapabilityGrant, ObjectScope
from property_rental.payment_read import (
    PaymentReadAuthorizationError,
    PaymentReadInvalidError,
    PaymentReadNotFoundError,
    PaymentReadUnavailableError,
)
from property_rental.payment_reversal_context import (
    PaymentReversalContextChanged,
    PaymentReversalContextService,
    ReversalContextPage,
)
from test_credit_migration import actor


def projection(prop: UUID, payment: UUID, count: int = 2) -> dict[str, object]:
    return {
        "revision_evidence": {
            "property": str(prop),
            "payment": str(payment),
            "view": "impact",
            "payment_status": "RECEIVED",
            "payment_revision": 2,
            "deposit_count": 1,
            "deposit_revision": 3,
            "target_count": 0,
            "target_revision": 0,
        },
        "unsupported_application": False,
        "anchor_found": True,
        "items": [
            {
                "ordinal": 1,
                "kind": "ALLOCATION",
                "id": str(UUID(int=n + 1)),
                "data": {"amount_usd_cents": 99},
            }
            for n in range(count)
        ],
    }


def call(
    raw: dict[str, object], prop: UUID, payment: UUID, page: ReversalContextPage
) -> tuple[dict[str, object], MagicMock]:
    connection = MagicMock()
    source = {
        "payment": {"id": str(payment), "property_id": str(prop)},
        "original_label": "Cash\tcounter\n" + "😀" * 500,
    }
    connection.execute.return_value.fetchone.side_effect = [(True,), (1,), (source,), (raw,)]
    with patch("property_rental.financial_reference.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        result = PaymentReversalContextService("synthetic").get(
            prop, payment, page, actor=actor(uuid4(), prop, "payments.reverse")
        )
    return result, connection


@pytest.mark.parametrize("bad", [0, 101, -1, True, 1.5, "2"])
def test_payment_reversal_context_limit_is_bounded(bad: int) -> None:
    with pytest.raises(PaymentReadInvalidError):
        ReversalContextPage(limit=bad)


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "x",
        "a" * 63 + ":1:" + str(UUID(int=1)),
        "A" * 64 + ":1:" + str(UUID(int=1)),
        "a" * 64 + ":0:" + str(UUID(int=1)),
        "a" * 64 + ":9:" + str(UUID(int=1)),
        "a" * 64 + ":1:" + str(UUID(int=0)),
        "a" * 64 + ":01:" + str(UUID(int=1)),
        "a" * 64 + ":1:" + str(UUID("aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa")).upper(),
    ],
)
def test_payment_reversal_context_cursor_is_finite_canonical(cursor: str) -> None:
    with pytest.raises(PaymentReadInvalidError):
        ReversalContextPage(cursor=cursor)
    with pytest.raises(PaymentReadInvalidError):
        ReversalContextPage(view="result", cursor="a" * 64 + ":5:" + str(UUID(int=1)))


@pytest.mark.parametrize("kind", ["none", "read", "other-property", "global", "object-only"])
def test_payment_reversal_context_action_grant_precedes_database(kind: str) -> None:
    human, prop = uuid4(), uuid4()
    current = {
        "none": actor(human, prop),
        "read": actor(human, prop, "payments.read"),
        "other-property": actor(human, uuid4(), "payments.reverse"),
        "global": AuthenticatedActor(str(human), frozenset({CapabilityGrant("payments.reverse")})),
        "object-only": AuthenticatedActor(
            str(human),
            frozenset(
                {
                    CapabilityGrant(
                        "payments.reverse",
                        object_scopes=frozenset({ObjectScope("property", str(prop))}),
                    )
                }
            ),
        ),
    }[kind]
    with patch("property_rental.financial_reference.psycopg.connect") as connect:
        with pytest.raises(PaymentReadAuthorizationError):
            PaymentReversalContextService("synthetic").get(
                prop, uuid4(), ReversalContextPage(), actor=current
            )
        connect.assert_not_called()


def test_payment_reversal_context_same_snapshot_bounded_page_and_original_source() -> None:
    prop, payment = uuid4(), uuid4()
    raw = projection(prop, payment)
    result, connection = call(raw, prop, payment, ReversalContextPage(limit=1))
    data = cast(dict[str, object], result["data"])
    assert len(cast(list[object], data["items"])) == 1
    assert result["next_cursor"] == f"{data['revision']}:1:{UUID(int=1)}"
    source = cast(dict[str, object], data["payment_resource"])
    assert source["original_label"] == "Cash\tcounter\n" + "😀" * 500
    calls = connection.execute.call_args_list
    assert calls[0].args == ("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",)
    assert "identity_kind='HUMAN'" in calls[4].args[0]
    assert calls[-1].args[1][3:] == ("impact", 1, None, None)
    assert not any(
        "INSERT" in c.args[0] or "UPDATE" in c.args[0] or "serialize_" in c.args[0] for c in calls
    )
    raw["items"] = [cast(list[object], raw["items"])[1]]
    next_result, _ = call(
        raw, prop, payment, ReversalContextPage(limit=1, cursor=str(result["next_cursor"]))
    )
    assert next_result["next_cursor"] is None
    assert cast(dict[str, object], next_result["data"])["revision"] == data["revision"]


@pytest.mark.parametrize(
    "counter", ["payment_revision", "deposit_revision", "deposit_count", "payment_status"]
)
def test_payment_reversal_context_changed_revision_rejects_continuation(counter: str) -> None:
    prop, payment = uuid4(), uuid4()
    raw = projection(prop, payment)
    first, _ = call(raw, prop, payment, ReversalContextPage(limit=1))
    changed = deepcopy(raw)
    evidence = cast(dict[str, object], changed["revision_evidence"])
    evidence[counter] = "REVERSED" if counter == "payment_status" else 99
    changed["anchor_found"] = False
    with pytest.raises(PaymentReversalContextChanged):
        call(changed, prop, payment, ReversalContextPage(limit=1, cursor=str(first["next_cursor"])))


@pytest.mark.parametrize(
    "fault",
    ["unsupported", "order", "duplicate", "identity", "kind", "overflow", "revision", "oversize"],
)
def test_payment_reversal_context_refuses_incomplete_or_malformed_projection(fault: str) -> None:
    prop, payment = uuid4(), uuid4()
    raw = projection(prop, payment)
    items = cast(list[dict[str, object]], raw["items"])
    if fault == "unsupported":
        raw["unsupported_application"] = True
    elif fault == "order":
        raw["items"] = list(reversed(items))
    elif fault == "duplicate":
        raw["items"] = [items[0], items[0]]
    elif fault == "identity":
        items[0]["id"] = str(UUID(int=0))
    elif fault == "kind":
        items[0]["kind"] = "REFUND"
    elif fault == "overflow":
        raw["items"] = items * 2
    elif fault == "revision":
        cast(dict[str, object], raw["revision_evidence"])["property"] = str(uuid4())
    else:
        items[0]["data"] = {"unexpected_large_text": "x" * 1_000_001}
    with pytest.raises(PaymentReadUnavailableError):
        call(raw, prop, payment, ReversalContextPage(limit=1))


@pytest.mark.parametrize("fault", ["actor", "property", "payment", "database"])
def test_payment_reversal_context_fresh_identity_source_and_outage_fail_closed(fault: str) -> None:
    prop, human = uuid4(), uuid4()
    connection = MagicMock()
    states = {"actor": [(False,)], "property": [(True,), None], "payment": [(True,), (1,), None]}
    error = (
        PaymentReadAuthorizationError
        if fault == "actor"
        else PaymentReadUnavailableError
        if fault == "database"
        else PaymentReadNotFoundError
    )
    with patch("property_rental.financial_reference.psycopg.connect") as connect:
        if fault == "database":
            connect.side_effect = psycopg.OperationalError("synthetic outage")
        else:
            connect.return_value.__enter__.return_value = connection
            connection.execute.return_value.fetchone.side_effect = states[fault]
        with pytest.raises(error):
            PaymentReversalContextService("synthetic").get(
                prop, uuid4(), ReversalContextPage(), actor=actor(human, prop, "payments.reverse")
            )
