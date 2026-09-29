"""Dated-source request, authorization, transaction and exact response boundaries."""

from copy import deepcopy
from dataclasses import replace
from typing import Any, cast
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.financial_due_sources import (
    DUE_SOURCE_CAPABILITIES,
    MAX_BALANCE,
    FinancialDueSourcesChanged,
    FinancialDueSourcesRequest,
    FinancialDueSourcesService,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant, ObjectScope
from property_rental.payment_read import (
    PaymentReadAuthorizationError,
    PaymentReadInvalidError,
    PaymentReadNotFoundError,
    PaymentReadUnavailableError,
)

PURPOSES = ["allocation", "credit_application"]


def request(purpose: str = "allocation", **changes: Any) -> FinancialDueSourcesRequest:
    return replace(FinancialDueSourcesRequest(purpose, uuid4(), uuid4(), uuid4(), 2), **changes)


def staff(prop: UUID, purpose: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(uuid4()),
        frozenset({CapabilityGrant(DUE_SOURCE_CAPABILITIES[purpose], frozenset({str(prop)}))}),
    )


def projection(prop: UUID, req: FinancialDueSourcesRequest) -> dict[str, Any]:
    return {
        "property_id": str(prop),
        "purpose": req.purpose,
        "source_id": str(req.source_id),
        "invoice_id": str(req.invoice_id),
        "invoice_line_id": str(req.invoice_line_id),
        "invoice_version": 3,
        "revision": "a" * 64,
        "as_of": "2026-09-16T00:00:00+00:00",
        "aggregate_outstanding_usd_cents": 150,
        "item_count": 3,
        "has_more": True,
        "items": [
            {
                "source_kind": "DEBIT_ADJUSTMENT",
                "source_id": str(UUID(int=1)),
                "approved_due_date": "2027-01-01",
                "source_occurred_at": "2026-09-01T00:00:00+00:00",
                "remaining_usd_cents": 50,
            },
            {
                "source_kind": "ORIGINAL_LINE",
                "source_id": str(req.invoice_line_id),
                "approved_due_date": "2027-02-01",
                "source_occurred_at": "2026-09-01T00:00:00+00:00",
                "remaining_usd_cents": 50,
            },
        ],
    }


def read(
    raw: object, prop: UUID, req: FinancialDueSourcesRequest
) -> tuple[dict[str, object], MagicMock]:
    who = staff(prop, req.purpose)
    connection = MagicMock()
    connection.execute.return_value.fetchone.side_effect = [(True,), (1,), (raw,)]
    with patch("property_rental.financial_reference.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        result = FinancialDueSourcesService("synthetic").get(prop, req, actor=who)
        connect.assert_called_once_with("synthetic", connect_timeout=3)
    statements = [x.args[0] for x in connection.execute.call_args_list]
    assert statements[:4] == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
        "SET LOCAL lock_timeout='3000ms'",
        "SET LOCAL statement_timeout='5000ms'",
        "SET LOCAL TIME ZONE 'UTC'",
    ]
    assert len(statements) == 7 and "financial_invoice_due_sources_page" in statements[-1]
    assert connection.execute.call_args_list[-1].args[1] == (
        prop,
        UUID(who.actor_id),
        req.purpose,
        req.source_id,
        req.invoice_id,
        req.invoice_line_id,
        req.limit,
        *req.anchor,
    )
    assert not any(
        "FOR SHARE" in text or "FOR UPDATE" in text or "serialize_" in text for text in statements
    )
    return result, connection


@pytest.mark.parametrize("purpose", PURPOSES)
@pytest.mark.parametrize("limit", [1, 50, 100])
def test_due_sources_request_accepts_finite_purposes_and_limits(purpose: str, limit: int) -> None:
    req = request(purpose, limit=limit)
    assert req.anchor == (None, None, None)
    continued = replace(req, cursor="a" * 64 + ":DEBIT_ADJUSTMENT:" + str(UUID(int=1)))
    assert continued.anchor == ("a" * 64, "DEBIT_ADJUSTMENT", UUID(int=1))


BAD_REQUEST_CHANGES: list[dict[str, Any]] = [
    {"purpose": None},
    {"purpose": []},
    {"purpose": 1},
    {"purpose": ""},
    {"purpose": "payments.read"},
    {"purpose": "refund"},
    {"source_id": UUID("00000000-0000-0000-0000-000000000000")},
    {"source_id": "bad"},
    {"source_id": None},
    {"invoice_id": UUID("00000000-0000-0000-0000-000000000000")},
    {"invoice_id": "bad"},
    {"invoice_id": None},
    {"invoice_line_id": UUID("00000000-0000-0000-0000-000000000000")},
    {"invoice_line_id": "bad"},
    {"invoice_line_id": None},
    {"limit": 0},
    {"limit": 101},
    {"limit": -1},
    {"limit": True},
    {"limit": 1.5},
    {"limit": "2"},
    {"cursor": ""},
    {"cursor": "x"},
    {"cursor": 1},
    {"cursor": []},
    {
        "cursor": (
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            "a"
        )
    },
    {
        "cursor": (
            "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
            "AAAA:ORIGINAL_LINE:00000000-0000-0000-0000-000000000001"
        )
    },
    {
        "cursor": (
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            "aaaa:PAYMENT:00000000-0000-0000-0000-000000000001"
        )
    },
    {
        "cursor": (
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            "aaaa:ORIGINAL_LINE:00000000-0000-0000-0000-000000000000"
        )
    },
    {
        "cursor": (
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            "aaaa:ORIGINAL_LINE:00000000000000000000000000000001"
        )
    },
    {
        "cursor": (
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            "aaaa:ORIGINAL_LINE:00000000-0000-0000-0000-000000000001 "
        )
    },
]


@pytest.mark.parametrize("changes", BAD_REQUEST_CHANGES)
def test_due_sources_request_rejects_unbounded_or_ambiguous_values(changes: dict[str, Any]) -> None:
    with pytest.raises(PaymentReadInvalidError):
        request(**changes)


@pytest.mark.parametrize("purpose", PURPOSES)
@pytest.mark.parametrize("phase", ["first", "continued", "exhausted", "zero"])
def test_due_sources_service_preserves_exact_facts_and_snapshot(purpose: str, phase: str) -> None:
    prop, req = uuid4(), request(purpose)
    raw = projection(prop, req)
    if phase in {"continued", "exhausted"}:
        req = replace(req, cursor="a" * 64 + ":DEBIT_ADJUSTMENT:" + str(UUID(int=1)))
        raw["has_more"] = False
        raw["items"] = [] if phase == "exhausted" else [raw["items"][1]]
    elif phase == "zero":
        raw.update(has_more=False, items=[], item_count=0, aggregate_outstanding_usd_cents=0)
    before = deepcopy(raw)
    result, _ = read(raw, prop, req)
    assert raw == before and result["data"] == {k: v for k, v in raw.items() if k != "has_more"}
    assert result["next_cursor"] == (
        "a" * 64 + ":ORIGINAL_LINE:" + str(req.invoice_line_id) if phase == "first" else None
    )


@pytest.mark.parametrize("purpose", PURPOSES)
@pytest.mark.parametrize(
    "scope", ["absent", "global", "object", "wrong_property", "general_read", "other_action"]
)
def test_due_sources_service_requires_exact_action_before_connection(
    purpose: str, scope: str
) -> None:
    prop, req = uuid4(), request(purpose)
    cap = DUE_SOURCE_CAPABILITIES[purpose]
    grants = {
        "absent": frozenset(),
        "global": frozenset({CapabilityGrant(cap)}),
        "object": frozenset(
            {
                CapabilityGrant(
                    cap, object_scopes=frozenset({ObjectScope("invoice", str(req.invoice_id))})
                )
            }
        ),
        "wrong_property": frozenset({CapabilityGrant(cap, frozenset({str(uuid4())}))}),
        "general_read": frozenset({CapabilityGrant("payments.read", frozenset({str(prop)}))}),
        "other_action": frozenset({CapabilityGrant("payments.reverse", frozenset({str(prop)}))}),
    }
    with patch("property_rental.financial_reference.psycopg.connect") as connect:
        with pytest.raises(PaymentReadAuthorizationError):
            FinancialDueSourcesService("synthetic").get(
                prop, req, actor=AuthenticatedActor(str(uuid4()), grants[scope])
            )
        connect.assert_not_called()


BAD_PROJECTIONS = [
    "extra",
    "missing",
    "property_id",
    "purpose",
    "source_id",
    "invoice_id",
    "invoice_line_id",
    "invoice_version_zero",
    "invoice_version_bool",
    "invoice_version_over",
    "revision",
    "asof_naive",
    "asof_invalid",
    "asof_infinite",
    "asof_fractional_seconds",
    "aggregate_negative",
    "aggregate_bool",
    "aggregate_fraction",
    "aggregate_over",
    "aggregate_small",
    "count_negative",
    "count_bool",
    "count_fraction",
    "count_over",
    "count_small",
    "more_number",
    "more_false",
    "items_not_list",
    "items_too_many",
    "items_empty",
    "item_extra",
    "item_missing",
    "source_kind",
    "source_kind_type",
    "source_nil",
    "source_noncanonical",
    "original_wrong_line",
    "duplicate",
    "order",
    "date_invalid",
    "date_noncanonical",
    "occurred_naive",
    "occurred_future",
    "remaining_zero",
    "remaining_bool",
    "remaining_fraction",
    "remaining_over",
    "empty_nonzero",
    "complete_total",
    "item_not_object",
]


@pytest.mark.parametrize("case", BAD_PROJECTIONS)
def test_due_sources_service_rejects_malformed_or_mismatched_projection(case: str) -> None:
    prop, req = uuid4(), request()
    raw = projection(prop, req)
    first = raw["items"][0]
    if case == "extra":
        raw["unexpected"] = 1
    elif case == "missing":
        del raw["revision"]
    elif case in {"property_id", "purpose", "source_id", "invoice_id", "invoice_line_id"}:
        raw[case] = str(uuid4())
    elif case.startswith("invoice_version_"):
        raw["invoice_version"] = {"zero": 0, "bool": True, "over": 10_000_000_000}[
            case.removeprefix("invoice_version_")
        ]
    elif case == "revision":
        raw["revision"] = "A" * 64
    elif case.startswith("asof_"):
        raw["as_of"] = {
            "naive": "2026-09-16T00:00:00",
            "invalid": "2026-02-30T00:00:00Z",
            "infinite": "infinity",
            "fractional_seconds": "2026-09-16T00:00:00.1234567Z",
        }[case.removeprefix("asof_")]
    elif case.startswith("aggregate_"):
        raw["aggregate_outstanding_usd_cents"] = {
            "negative": -1,
            "bool": True,
            "fraction": 150.5,
            "over": MAX_BALANCE + 1,
            "small": 80,
        }[case.removeprefix("aggregate_")]
    elif case.startswith("count_"):
        raw["item_count"] = {
            "negative": -1,
            "bool": True,
            "fraction": 3.5,
            "over": MAX_BALANCE + 1,
            "small": 1,
        }[case.removeprefix("count_")]
    elif case == "more_number":
        raw["has_more"] = 1
    elif case == "more_false":
        raw["has_more"] = False
    elif case == "items_not_list":
        raw["items"] = {}
    elif case == "items_too_many":
        raw["items"].append(deepcopy(first))
    elif case == "items_empty":
        raw["items"] = []
    elif case == "item_extra":
        first["unexpected"] = 1
    elif case == "item_missing":
        del first["approved_due_date"]
    elif case == "source_kind":
        first["source_kind"] = "PAYMENT"
    elif case == "source_kind_type":
        first["source_kind"] = []
    elif case == "source_nil":
        first["source_id"] = str(UUID(int=0))
    elif case == "source_noncanonical":
        first["source_id"] = UUID(int=1).hex
    elif case == "original_wrong_line":
        first["source_kind"] = "ORIGINAL_LINE"
    elif case == "duplicate":
        raw["items"][1] = deepcopy(first)
    elif case == "order":
        raw["items"].reverse()
    elif case == "date_invalid":
        first["approved_due_date"] = "2027-02-30"
    elif case == "date_noncanonical":
        first["approved_due_date"] = "20270201"
    elif case == "occurred_naive":
        first["source_occurred_at"] = "2026-09-01T00:00:00"
    elif case == "occurred_future":
        first["source_occurred_at"] = "2026-09-17T00:00:00Z"
    elif case.startswith("remaining_"):
        first["remaining_usd_cents"] = {
            "zero": 0,
            "bool": True,
            "fraction": 50.5,
            "over": MAX_BALANCE + 1,
        }[case.removeprefix("remaining_")]
    elif case == "empty_nonzero":
        raw.update(items=[], item_count=0, has_more=False)
    elif case == "complete_total":
        raw.update(item_count=2, has_more=False)
    else:
        raw["items"][0] = "invalid"
    with pytest.raises(PaymentReadUnavailableError):
        read(raw, prop, req)


@pytest.mark.parametrize(
    "case", ["revision", "anchor_repeated", "count_zero", "count_too_small", "more_with_empty"]
)
def test_due_sources_service_rejects_inconsistent_continuation(case: str) -> None:
    prop, req = uuid4(), request(cursor="a" * 64 + ":DEBIT_ADJUSTMENT:" + str(UUID(int=1)))
    raw = projection(prop, req)
    raw.update(items=[raw["items"][1]], has_more=False)
    if case == "revision":
        raw["revision"] = "b" * 64
    elif case == "anchor_repeated":
        raw["items"][0].update(source_kind="DEBIT_ADJUSTMENT", source_id=str(UUID(int=1)))
    elif case == "count_zero":
        raw.update(items=[], item_count=0, aggregate_outstanding_usd_cents=0)
    elif case == "count_too_small":
        raw["item_count"] = 1
    else:
        raw.update(items=[], has_more=True)
    with pytest.raises(
        FinancialDueSourcesChanged if case == "revision" else PaymentReadUnavailableError
    ):
        read(raw, prop, req)


@pytest.mark.parametrize("purpose", PURPOSES)
def test_due_sources_service_preserves_bigint_and_maximum_page_without_rounding(
    purpose: str,
) -> None:
    prop, req = uuid4(), request(purpose, limit=100)
    raw = projection(prop, req)
    item = raw["items"][0]
    raw.update(
        invoice_version=9_999_999_999,
        aggregate_outstanding_usd_cents=MAX_BALANCE,
        item_count=100,
        has_more=False,
        items=[
            item
            | {
                "source_id": str(UUID(int=n)),
                "remaining_usd_cents": MAX_BALANCE - 99 if n == 1 else 1,
            }
            for n in range(1, 101)
        ],
    )
    result, _ = read(raw, prop, req)
    assert (
        cast(dict[str, Any], result["data"])["items"][0]["remaining_usd_cents"] == MAX_BALANCE - 99
    )
    assert (
        result["next_cursor"] is None and len(cast(dict[str, Any], result["data"])["items"]) == 100
    )


@pytest.mark.parametrize("purpose", PURPOSES)
@pytest.mark.parametrize(
    "code,expected",
    [
        ("P4501", PaymentReadNotFoundError),
        ("P4506", PaymentReadAuthorizationError),
        ("22023", PaymentReadInvalidError),
        ("P4507", FinancialDueSourcesChanged),
        ("42501", PaymentReadAuthorizationError),
        ("57014", PaymentReadUnavailableError),
        ("55P03", PaymentReadUnavailableError),
        ("54000", PaymentReadUnavailableError),
    ],
)
def test_due_sources_service_maps_sql_failures_without_retry(
    purpose: str, code: str, expected: type[Exception]
) -> None:
    prop, req = uuid4(), request(purpose)
    connection = MagicMock()
    failure_type = type("SyntheticDatabaseError", (psycopg.Error,), {"sqlstate": code})
    connection.execute.return_value.fetchone.side_effect = [
        (True,),
        (1,),
        failure_type("Synthetic private detail"),
    ]
    with patch("property_rental.financial_reference.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        with pytest.raises(expected) as error:
            FinancialDueSourcesService("synthetic").get(prop, req, actor=staff(prop, purpose))
        assert "Synthetic private detail" not in str(error.value)
        assert connect.call_count == 1 and connection.execute.call_count == 7


@pytest.mark.parametrize(
    "case",
    [
        "no_database",
        "inactive",
        "missing_property",
        "malformed_row",
        "missing_row",
        "invalid_actor",
    ],
)
def test_due_sources_service_requires_fresh_available_context(case: str) -> None:
    prop, req = uuid4(), request()
    who = staff(prop, req.purpose)
    connection = MagicMock()
    rows: list[Any] = [(True,), (1,), (projection(prop, req),)]
    if case == "inactive":
        rows = [(False,)]
    elif case == "missing_property":
        rows = [(True,), None]
    elif case == "malformed_row":
        rows[-1] = ({}, {})
    elif case == "missing_row":
        rows[-1] = None
    elif case == "invalid_actor":
        who = AuthenticatedActor("invalid", who.capability_grants)
    connection.execute.return_value.fetchone.side_effect = rows
    expected = (
        PaymentReadAuthorizationError
        if case in {"inactive", "invalid_actor"}
        else PaymentReadNotFoundError
        if case == "missing_property"
        else PaymentReadUnavailableError
    )
    with patch("property_rental.financial_reference.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        with pytest.raises(expected):
            FinancialDueSourcesService(None if case == "no_database" else "synthetic").get(
                prop, req, actor=who
            )
        if case in {"no_database", "invalid_actor"}:
            connect.assert_not_called()
