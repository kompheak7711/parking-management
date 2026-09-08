"""Independent action grants, captured scope, coherent pages and response budgets."""

from copy import deepcopy
from dataclasses import replace
from typing import cast
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from property_rental.financial_action_context import (
    ACTION_CAPABILITIES,
    FinancialActionContextChanged,
    FinancialActionContextRequest,
    FinancialActionContextService,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant, ObjectScope
from property_rental.payment_read import (
    PaymentReadAuthorizationError,
    PaymentReadInvalidError,
    PaymentReadUnavailableError,
)
from test_credit_migration import actor


def request(purpose: str = "allocation") -> FinancialActionContextRequest:
    return FinancialActionContextRequest(
        purpose, uuid4(), refund_id=uuid4() if purpose == "refund_correction_reversal" else None
    )


def projection(
    prop: UUID, req: FinancialActionContextRequest, payment: UUID | None
) -> dict[str, object]:
    return {
        "source_payment_id": str(payment) if payment else None,
        "context": {},
        "target": None,
        "items": [],
        "item_count": 0,
        "unsupported_application": False,
        "anchor_found": True,
        "revision_evidence": {
            "property": str(prop),
            "purpose": req.purpose,
            "source": str(req.source_id),
            "refund": str(req.refund_id) if req.refund_id else None,
            "requested_target_kind": req.target_kind,
            "requested_target": str(req.target_id) if req.target_id else None,
            "payment": str(payment) if payment else None,
            "payment_status": "RECEIVED" if payment else None,
            "payment_revision": 1,
            "deposit_count": 1,
            "deposit_revision": 2,
            "target_count": 0,
            "target_revision": 0,
            "target_invoice_version": 0,
            "target_draft_event_count": 0,
            "target_draft_event_max": 0,
        },
    }


def read(
    raw: dict[str, object],
    prop: UUID,
    req: FinancialActionContextRequest,
    source: dict[str, object] | None = None,
) -> tuple[dict[str, object], MagicMock]:
    connection = MagicMock()
    connection.execute.return_value.fetchone.side_effect = [
        (True,),
        (1,),
        (raw,),
        (
            source
            or {
                "payment": {"id": raw["source_payment_id"], "property_id": str(prop)},
                "available_usd_cents": 9007199254740993,
            },
        ),
    ]
    with patch("property_rental.financial_reference.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        value = FinancialActionContextService("synthetic").get(
            prop, req, actor=actor(uuid4(), prop, ACTION_CAPABILITIES[req.purpose])
        )
    return value, connection


@pytest.mark.parametrize("purpose", ACTION_CAPABILITIES)
def test_financial_action_context_sole_action_grant_uses_one_bounded_read_snapshot(
    purpose: str,
) -> None:
    prop, payment = uuid4(), uuid4()
    req = request(purpose)
    result, connection = read(projection(prop, req, payment), prop, req)
    value = cast(dict[str, object], result["data"])
    assert value["purpose"] == purpose and value["source_id"] == str(req.source_id)
    assert value["property_id"] == str(prop) and result["next_cursor"] is None
    assert (
        cast(dict[str, object], value["payment_resource"])["available_usd_cents"]
        == 9007199254740993
    )
    statements = [call.args[0] for call in connection.execute.call_args_list]
    assert statements[:4] == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
        "SET LOCAL lock_timeout='3000ms'",
        "SET LOCAL statement_timeout='5000ms'",
        "SET LOCAL TIME ZONE 'UTC'",
    ]
    assert (
        "financial_action_context_page" in statements[6]
        and "WITH selected AS MATERIALIZED" in statements[7]
    )
    assert connection.execute.call_args_list[6].args[1][2:5] == (
        purpose,
        req.source_id,
        req.refund_id,
    )
    assert not any("FOR SHARE" in sql or "serialize_" in sql for sql in statements)


@pytest.mark.parametrize("purpose", ACTION_CAPABILITIES)
@pytest.mark.parametrize(
    "scope", ["absent", "global", "object", "wrong_property", "general_read", "other_action"]
)
def test_financial_action_context_never_synthesizes_an_action_grant(
    purpose: str, scope: str
) -> None:
    prop, human = uuid4(), uuid4()
    req = request(purpose)
    cap = ACTION_CAPABILITIES[purpose]
    grants = {
        "absent": frozenset(),
        "global": frozenset({CapabilityGrant(cap)}),
        "object": frozenset(
            {
                CapabilityGrant(
                    cap, object_scopes=frozenset({ObjectScope("payment", str(req.source_id))})
                )
            }
        ),
        "wrong_property": frozenset({CapabilityGrant(cap, frozenset({str(uuid4())}))}),
        "general_read": frozenset({CapabilityGrant("payments.read", frozenset({str(prop)}))}),
        "other_action": frozenset({CapabilityGrant("payments.reverse", frozenset({str(prop)}))}),
    }
    with patch("property_rental.financial_reference.psycopg.connect") as connect:
        with pytest.raises(PaymentReadAuthorizationError):
            FinancialActionContextService("synthetic").get(
                prop, req, actor=AuthenticatedActor(str(human), grants[scope])
            )
        connect.assert_not_called()


@pytest.mark.parametrize("bad", [0, 101, -1, True, 1.5, "2"])
def test_financial_action_context_page_limits_are_strict(bad: int) -> None:
    with pytest.raises(PaymentReadInvalidError):
        replace(request(), limit=bad)


@pytest.mark.parametrize("bad", ["", "all", "credits.read", None, [], 1])
def test_financial_action_context_purpose_is_finite(bad: str) -> None:
    with pytest.raises(PaymentReadInvalidError):
        request(bad)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_id": UUID(int=0)},
        {"source_id": "bad"},
        {"target_kind": "INVOICE"},
        {"target_id": UUID(int=1)},
        {"target_kind": "SETTLEMENT", "target_id": UUID(int=1)},
        {"target_kind": "INVOICE", "target_id": UUID(int=0)},
        {"refund_id": UUID(int=1)},
        {"cursor": ""},
        {"cursor": "x"},
        {"cursor": "a" * 64 + ":0:" + str(UUID(int=1))},
        {"cursor": "a" * 64 + ":01:" + str(UUID(int=1))},
        {"cursor": "a" * 64 + ":32768:" + str(UUID(int=1))},
        {"cursor": "A" * 64 + ":1:" + str(UUID(int=1))},
        {"cursor": "a" * 64 + ":1:" + str(UUID(int=0))},
    ],
)
def test_financial_action_context_rejects_invalid_identity_target_and_cursor(
    changes: dict[str, object],
) -> None:
    with pytest.raises(PaymentReadInvalidError):
        FinancialActionContextRequest(
            "allocation",
            cast(UUID, changes.get("source_id", uuid4())),
            target_kind=cast(str | None, changes.get("target_kind")),
            target_id=cast(UUID | None, changes.get("target_id")),
            refund_id=cast(UUID | None, changes.get("refund_id")),
            cursor=cast(str | None, changes.get("cursor")),
        )


def test_financial_action_context_reversal_cannot_replace_original_target_or_refund() -> None:
    for purpose in ACTION_CAPABILITIES.keys() - {"allocation", "credit_application"}:
        with pytest.raises(PaymentReadInvalidError):
            replace(request(purpose), target_kind="INVOICE", target_id=uuid4())
    with pytest.raises(PaymentReadInvalidError):
        FinancialActionContextRequest("refund_correction_reversal", uuid4())


def test_financial_action_context_continuation_binds_source_target_and_current_facts() -> None:
    prop, payment = uuid4(), uuid4()
    req = replace(request(), target_kind="INVOICE", target_id=uuid4(), limit=1)
    raw = projection(prop, req, payment)
    raw["item_count"] = 2
    raw["items"] = [
        {
            "sequence": n,
            "id": str(UUID(int=n)),
            "kind": "INVOICE_LINE",
            "data": {"outstanding_usd_cents": 500},
        }
        for n in (1, 2)
    ]
    first, _ = read(raw, prop, req)
    cursor = cast(str, first["next_cursor"])
    assert cursor.endswith(":1:" + str(UUID(int=1)))
    second_raw = deepcopy(raw)
    second_raw["items"] = cast(list[object], raw["items"])[1:]
    second, _ = read(second_raw, prop, replace(req, cursor=cursor))
    assert second["next_cursor"] is None
    assert (
        cast(dict[str, object], first["data"])["revision"]
        == cast(dict[str, object], second["data"])["revision"]
    )
    for key in (
        "payment_revision",
        "deposit_count",
        "deposit_revision",
        "target_count",
        "target_revision",
        "target_invoice_version",
        "target_draft_event_count",
        "target_draft_event_max",
    ):
        changed = deepcopy(second_raw)
        cast(dict[str, object], changed["revision_evidence"])[key] = 99
        changed["anchor_found"] = False
        with pytest.raises(FinancialActionContextChanged):
            read(changed, prop, replace(req, cursor=cursor))
    for key, value in [
        ("context", {"original": "changed"}),
        ("target", {"status": "VOID"}),
        ("item_count", 3),
    ]:
        changed = deepcopy(second_raw)
        changed[key] = value
        with pytest.raises(FinancialActionContextChanged):
            read(changed, prop, replace(req, cursor=cursor))
    with pytest.raises(FinancialActionContextChanged):
        read(second_raw, prop, replace(req, cursor=cursor), {"available_usd_cents": 0})
    with pytest.raises(PaymentReadInvalidError):
        read(second_raw | {"anchor_found": False}, prop, replace(req, cursor=cursor))


@pytest.mark.parametrize(
    "key,value",
    [
        ("unsupported_application", True),
        ("context", None),
        ("target", []),
        ("items", {}),
        ("source_payment_id", "bad"),
        ("revision_evidence", {}),
        ("item_count", -1),
        ("item_count", 32768),
        ("item_count", True),
        ("item_count", "0"),
        ("item_count", 1),
        ("items", [{"sequence": 1, "id": str(UUID(int=1)), "kind": None, "data": {}}]),
    ],
)
def test_financial_action_context_malformed_projection_fails_closed(
    key: str, value: object
) -> None:
    prop, payment = uuid4(), uuid4()
    req = request()
    with pytest.raises(PaymentReadUnavailableError):
        read(projection(prop, req, payment) | {key: value}, prop, req)


def test_financial_action_context_utf8_budget_counts_combined_source_and_context() -> None:
    prop, payment = uuid4(), uuid4()
    req = request()
    raw = projection(prop, req, payment)
    raw["context"] = {"description": "😀" * 140000}
    with pytest.raises(PaymentReadUnavailableError):
        read(raw, prop, req, {"description": "😀" * 140000})
    valid, _ = read(projection(prop, req, payment), prop, req, {"method": "Cash\tCounter\n😀"})
    assert cast(dict[str, object], valid["data"])["payment_resource"] == {
        "method": "Cash\tCounter\n😀"
    }


def test_financial_action_context_deposit_refund_has_no_invented_payment() -> None:
    prop = uuid4()
    req = request("refund_return")
    result, connection = read(projection(prop, req, None), prop, req)
    assert cast(dict[str, object], result["data"])["payment_resource"] is None
    assert len(connection.execute.call_args_list) == 7
