"""Exact selection, cross-snapshot denials and fail-closed ledger response handling."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from property_rental.customer_ledger import (
    LedgerCursor,
    LedgerEventKey,
    LedgerFilter,
    LedgerInvalidError,
    LedgerPosition,
    LedgerSnapshotChangedError,
)
from property_rental.customer_ledger_query import (
    LEDGER_CAPABILITY,
    LedgerDetailCursor,
    LedgerReadRequest,
)
from property_rental.customer_ledger_read import (
    CustomerLedgerReadService,
    LedgerAuthorizationError,
    LedgerNotFoundError,
    LedgerUnavailableError,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant, ObjectScope

PROP = UUID(int=11)
CUSTOMER = UUID(int=12)
HUMAN = UUID(int=13)
EVENT = UUID(int=14)
REVISION = "a" * 64


def actor(capability: str = LEDGER_CAPABILITY) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(HUMAN), frozenset({CapabilityGrant(capability, frozenset({str(PROP)}))})
    )


def event() -> dict[str, object]:
    return {
        "property_id": str(PROP),
        "customer_id": str(CUSTOMER),
        "event_kind": "PAYMENT_RECEIVED",
        "event_order": 40,
        "event_id": str(EVENT),
        "occurred_at": "2026-09-09T00:00:00+00:00",
        "business_date": "2026-09-09",
        "source_table": "payments",
        "source_reference": None,
        "recorded_amount_usd_cents": 10,
        "invoice_id": None,
        "late_payment_charge_id": None,
        "payment_id": str(EVENT),
        "customer_credit_id": None,
        "deposit_id": None,
        "refund_id": None,
        "source_audit": {"received_currency": "USD", "received_amount": 10},
        "component_count": 1,
        **{k + "_effect_usd_cents": 10 if k == "payment" else 0 for k in LedgerPosition.fields},
        **{k + "_after_usd_cents": 10 if k == "payment" else 0 for k in LedgerPosition.fields},
    }


def snapshot() -> dict[str, object]:
    position = {k: "10" if k == "payment" else "0" for k in LedgerPosition.fields}
    return {
        "property_id": str(PROP),
        "customer_id": str(CUSTOMER),
        "customer_name": "Synthetic Customer",
        "revision": REVISION,
        "position": position,
        "history_position": dict(position),
        "event_count": 1,
    }


def page() -> dict[str, object]:
    return {
        "property_id": str(PROP),
        "customer_id": str(CUSTOMER),
        "section": "history",
        "items": [event()],
        "more": False,
    }


def connection_for(source: object, rows: object) -> MagicMock:
    connection = MagicMock()
    connection.execute.return_value.fetchone.side_effect = [(PROP,), (source,), (rows,)]
    return connection


def read(connection: MagicMock, request: LedgerReadRequest | None = None) -> dict[str, object]:
    with (
        patch("property_rental.customer_ledger_read.psycopg.connect") as connect,
        patch("property_rental.customer_ledger_read.set_json_loads"),
    ):
        connect.return_value.__enter__.return_value = connection
        return CustomerLedgerReadService("synthetic-runtime").get(
            CUSTOMER, request if request is not None else LedgerReadRequest(), actor=actor()
        )


@pytest.mark.parametrize(
    "values",
    [
        {"section": "edit"},
        {"section": []},
        {"limit": True},
        {"limit": 0},
        {"limit": 101},
        {"filters": None},
        {"revision": ""},
        {"revision": "A" * 64},
        {"revision": True},
        {"cursor": ""},
        {"cursor": "x" * 1025},
        {"cursor": "not-base64"},
        {"event_kind": "PAYMENT_RECEIVED"},
        {"event_id": EVENT},
        {"section": "components"},
        {"section": "components", "event_kind": "BAD", "event_id": EVENT},
        {"section": "components", "event_kind": "PAYMENT_RECEIVED", "event_id": UUID(int=0)},
        {"section": "composition", "filters": LedgerFilter(event_kind="PAYMENT_RECEIVED")},
    ],
)
def test_ledger_query_rejects_invalid_or_ambiguous_selection(values: dict[str, object]) -> None:
    with pytest.raises(LedgerInvalidError):
        LedgerReadRequest(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("section", ["history", "composition", "components"])
def test_ledger_cursor_binds_scope_selection_and_revision_but_allows_page_size_change(
    section: str,
) -> None:
    request = LedgerReadRequest(
        section=section,
        event_kind="PAYMENT_RECEIVED" if section == "components" else None,
        event_id=EVENT if section == "components" else None,
    )
    key = (
        LedgerEventKey(datetime(2026, 9, 9, tzinfo=UTC), "PAYMENT_RECEIVED", EVENT)
        if section == "history"
        else "CREDIT:" + str(EVENT)
        if section == "composition"
        else "b" * 64
    )
    token = request.next_cursor(PROP, CUSTOMER, REVISION, key)
    selected = replace(request, cursor=token, limit=1)
    selected.validate_snapshot(PROP, CUSTOMER, REVISION)
    with pytest.raises(LedgerInvalidError):
        selected.validate_snapshot(uuid4(), CUSTOMER, REVISION)
    with pytest.raises(LedgerInvalidError):
        selected.validate_snapshot(PROP, uuid4(), REVISION)
    with pytest.raises(LedgerSnapshotChangedError):
        selected.validate_snapshot(PROP, CUSTOMER, "c" * 64)
    with pytest.raises(LedgerInvalidError):
        replace(selected, revision="c" * 64)
    if section == "history":
        with pytest.raises(LedgerInvalidError):
            replace(
                selected, filters=LedgerFilter(event_kind="PAYMENT_RECEIVED")
            ).validate_snapshot(PROP, CUSTOMER, REVISION)
    if section == "components":
        with pytest.raises(LedgerInvalidError):
            replace(selected, event_id=uuid4()).validate_snapshot(PROP, CUSTOMER, REVISION)


def test_ledger_detail_cursor_rejects_cross_section_and_noncanonical_or_invalid_keys() -> None:
    query = LedgerReadRequest(section="composition")
    token = query.next_cursor(PROP, CUSTOMER, REVISION, "CREDIT:" + str(EVENT))
    with pytest.raises(LedgerInvalidError):
        LedgerReadRequest(cursor=token)
    for key in ["CREDIT:bad", "NONE:" + str(EVENT), "CREDIT:" + str(UUID(int=0))]:
        with pytest.raises(LedgerInvalidError):
            replace(
                query,
                cursor=LedgerDetailCursor(
                    query.fingerprint(PROP, CUSTOMER), REVISION, key
                ).encode(),
            )
    with pytest.raises(LedgerInvalidError):
        LedgerDetailCursor.decode(token + "=")


def test_ledger_read_uses_one_read_only_snapshot_and_exact_wire_money() -> None:
    connection = connection_for(snapshot(), page())
    result = read(connection)
    data = result["data"]
    assert isinstance(data, dict)
    assert data["position"] == LedgerPosition(payment=10).as_wire()
    items = data["items"]
    assert isinstance(items, list)
    assert items[0]["payment_effect_usd_cents"] == "10"
    assert items[0]["source_audit"]["received_amount"] == "10"
    assert items[0]["position_after_instant"] == LedgerPosition(payment=10).as_wire()
    commands = [c.args[0] for c in connection.execute.call_args_list]
    assert commands[:4] == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
        "SET LOCAL lock_timeout='3000ms'",
        "SET LOCAL statement_timeout='5000ms'",
        "SET LOCAL TIME ZONE 'UTC'",
    ]
    assert len([c for c in commands if c.startswith("SELECT")]) == 3
    assert result["next_cursor"] is None


def test_ledger_read_rejects_changed_snapshot_before_loading_any_page() -> None:
    connection = connection_for(snapshot(), page())
    with pytest.raises(LedgerSnapshotChangedError):
        read(connection, LedgerReadRequest(revision="b" * 64))
    assert not any("customer_ledger_page" in c.args[0] for c in connection.execute.call_args_list)


@pytest.mark.parametrize(
    "field,value",
    [
        ("customer_id", str(UUID(int=99))),
        ("property_id", str(UUID(int=99))),
        ("revision", "bad"),
        ("history_position", {k: "0" for k in LedgerPosition.fields}),
        ("position", {k: "-1" for k in LedgerPosition.fields}),
        ("event_count", True),
        ("customer_name", "x" * 4001),
    ],
)
def test_ledger_read_fails_closed_on_invalid_or_unreconciled_snapshot(
    field: str, value: object
) -> None:
    source = snapshot()
    source[field] = value
    connection = connection_for(source, page())
    with pytest.raises(LedgerUnavailableError):
        read(connection)
    assert not any("customer_ledger_page" in c.args[0] for c in connection.execute.call_args_list)


@pytest.mark.parametrize(
    "field,value",
    [
        ("property_id", str(UUID(int=99))),
        ("customer_id", str(UUID(int=99))),
        ("event_order", 99),
        ("occurred_at", "2026-09-09T00:00:00"),
        ("business_date", "invalid"),
        ("payment_effect_usd_cents", 0.5),
        ("payment_after_usd_cents", -1),
        ("component_count", True),
        ("source_table", "javascript:bad"),
        ("source_audit", {"money": float("nan")}),
    ],
)
def test_ledger_read_rejects_invalid_source_rows_without_returning_partial_data(
    field: str, value: object
) -> None:
    row = event()
    row[field] = value
    rows = page()
    rows["items"] = [row]
    with pytest.raises(LedgerUnavailableError):
        read(connection_for(snapshot(), rows))


def test_ledger_read_rejects_duplicate_or_backward_rows_and_false_pagination() -> None:
    for rows in [
        {**page(), "items": [event(), event()]},
        {**page(), "items": [], "more": True},
        {**page(), "more": True},
    ]:
        with pytest.raises(LedgerUnavailableError):
            read(connection_for(snapshot(), rows))
    key = LedgerEventKey(
        datetime(2026, 9, 9, tzinfo=UTC) + timedelta(seconds=1), "PAYMENT_RECEIVED", EVENT
    )
    query = LedgerReadRequest(
        cursor=LedgerCursor(LedgerReadRequest().fingerprint(PROP, CUSTOMER), REVISION, key).encode()
    )
    with pytest.raises(LedgerUnavailableError):
        read(connection_for(snapshot(), page()), query)


@pytest.mark.parametrize(
    "grant",
    [
        CapabilityGrant("customers.read", frozenset({str(PROP)})),
        CapabilityGrant("payments.record", frozenset({str(PROP)})),
        CapabilityGrant(LEDGER_CAPABILITY),
        CapabilityGrant(
            LEDGER_CAPABILITY, object_scopes=frozenset({ObjectScope("customer", str(CUSTOMER))})
        ),
        CapabilityGrant(LEDGER_CAPABILITY, frozenset({"not-a-property"})),
    ],
)
def test_ledger_read_never_infers_property_access_or_uses_database_without_read_grant(
    grant: CapabilityGrant,
) -> None:
    with patch("property_rental.customer_ledger_read.psycopg.connect") as connect:
        with pytest.raises(LedgerAuthorizationError):
            CustomerLedgerReadService("synthetic").get(
                CUSTOMER,
                LedgerReadRequest(),
                actor=AuthenticatedActor(str(HUMAN), frozenset({grant})),
            )
        connect.assert_not_called()


def test_ledger_read_expected_property_mismatch_stops_before_financial_projection() -> None:
    connection = connection_for(snapshot(), page())
    with (
        patch("property_rental.customer_ledger_read.psycopg.connect") as connect,
        patch("property_rental.customer_ledger_read.set_json_loads"),
    ):
        connect.return_value.__enter__.return_value = connection
        with pytest.raises(LedgerNotFoundError):
            CustomerLedgerReadService("synthetic").get(
                CUSTOMER, LedgerReadRequest(), actor=actor(), expected_property=uuid4()
            )
    assert not any(
        "customer_ledger_snapshot" in c.args[0] for c in connection.execute.call_args_list
    )


def detail_page(section: str) -> dict[str, object]:
    if section == "composition":
        row: dict[str, object] = {
            "property_id": str(PROP),
            "customer_id": str(CUSTOMER),
            "balance_kind": "UNALLOCATED_PAYMENT",
            "balance_source_id": str(EVENT),
            "invoice_id": None,
            "invoice_line_id": None,
            "late_payment_charge_id": None,
            "category": None,
            "description": "Unallocated Payment",
            "balance_usd_cents": "10",
            "detail_key": "UNALLOCATED_PAYMENT:" + str(EVENT),
        }
    else:
        row = {
            k: v
            for k, v in event().items()
            if not k.endswith(("_effect_usd_cents", "_after_usd_cents")) and k != "component_count"
        }
        row.update(
            invoice_line_id=None,
            balance_kind="UNALLOCATED_PAYMENT",
            balance_source_id=str(EVENT),
            effect_usd_cents="10",
            category=None,
            description="Unallocated Payment",
            detail_key="b" * 64,
        )
    return {**page(), "section": section, "items": [row]}


@pytest.mark.parametrize("section", ["composition", "components"])
def test_ledger_detail_pages_preserve_exact_money_and_bound_continuation(section: str) -> None:
    query = LedgerReadRequest(
        section=section,
        limit=1,
        event_kind="PAYMENT_RECEIVED" if section == "components" else None,
        event_id=EVENT if section == "components" else None,
    )
    result = read(connection_for(snapshot(), {**detail_page(section), "more": True}), query)
    assert isinstance(result["next_cursor"], str)
    continued = replace(query, cursor=result["next_cursor"])
    continued.validate_snapshot(PROP, CUSTOMER, REVISION)
    with pytest.raises(LedgerUnavailableError):
        read(connection_for(snapshot(), detail_page(section)), continued)


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("composition", "balance_usd_cents", "0"),
        ("composition", "balance_usd_cents", "-1"),
        ("composition", "balance_usd_cents", 0.5),
        ("composition", "detail_key", "CREDIT:" + str(EVENT)),
        ("composition", "balance_source_id", str(UUID(int=99))),
        ("composition", "customer_id", str(UUID(int=99))),
        ("composition", "description", "x" * 4001),
        ("components", "event_id", str(UUID(int=99))),
        ("components", "event_kind", "INVOICE_ISSUED"),
        ("components", "balance_kind", "NONE"),
        ("components", "balance_kind", "INVALID"),
        ("components", "detail_key", "A" * 64),
        ("components", "source_audit", {"evidence": "x" * 1_048_577}),
        ("components", "effect_usd_cents", "1" * 65),
    ],
)
def test_ledger_detail_pages_fail_closed_on_mismatched_or_oversized_source(
    section: str, field: str, value: object
) -> None:
    rows = detail_page(section)
    row = cast(list[dict[str, object]], rows["items"])[0]
    row[field] = value
    query = LedgerReadRequest(
        section=section,
        event_kind="PAYMENT_RECEIVED" if section == "components" else None,
        event_id=EVENT if section == "components" else None,
    )
    with pytest.raises(LedgerUnavailableError):
        read(connection_for(snapshot(), rows), query)
