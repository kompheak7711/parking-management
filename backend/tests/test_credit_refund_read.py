"""Credit/Refund scope is capability-specific and uses only bounded runtime reads."""

from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.pq import Format

from property_rental.credit_refund_read import (
    CreditRefundReadService,
    FinancialReadAuthorizationError,
    FinancialReadInvalidError,
    FinancialReadNotFoundError,
    FinancialReadUnavailableError,
    Resource,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from test_payment_read import connection, staff


@pytest.mark.parametrize(
    "resource",
    ["property", "customer", "payment", "credit", "credit_application", "refund", "deposit"],
)
def test_credit_refund_scope_runtime_readonly_exact_capability_and_uuid(resource: Resource) -> None:
    prop, identity, foreign = uuid4(), uuid4(), uuid4()
    original = staff(prop, "credits.read")
    actor = AuthenticatedActor(
        original.actor_id,
        original.capability_grants
        | frozenset({CapabilityGrant("refunds.create", frozenset({str(foreign)}))}),
    )
    conn = connection()
    conn.execute.return_value.fetchone.return_value = (prop,)
    with patch("property_rental.credit_refund_read.psycopg.connect", return_value=conn) as connect:
        assert (
            CreditRefundReadService("runtime-only").resolve(
                resource, identity, "credits.read", actor=actor
            )
            == prop
        )
        connect.assert_called_once_with("runtime-only", connect_timeout=3)
    calls = conn.execute.call_args_list
    assert [call.args[0] for call in calls[:4]] == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
        "SET LOCAL lock_timeout='3000ms'",
        "SET LOCAL statement_timeout='5000ms'",
        "SET LOCAL TIME ZONE 'UTC'",
    ]
    assert len(calls) == 5
    assert calls[4].args == (
        "SELECT app.credit_refund_http_scope(%s,%s,%s,%s::uuid[])",
        (resource, identity, UUID(actor.actor_id), [prop]),
    )


@pytest.mark.parametrize(
    "capability", ["payments.read", "credits.recognize", "refunds.read", "credits.apply"]
)
def test_credit_refund_scope_denies_missing_exact_grant_before_connection(capability: str) -> None:
    with patch("property_rental.credit_refund_read.psycopg.connect") as connect:
        with pytest.raises(FinancialReadNotFoundError):
            CreditRefundReadService("unused").resolve(
                "credit", uuid4(), "credits.read", actor=staff(uuid4(), capability)
            )
        connect.assert_not_called()


@pytest.mark.parametrize("identity", ["", "not-a-uuid", "00000000-0000-0000-0000-000000000000"])
def test_credit_refund_scope_malformed_actor_and_property_fail_before_connection(
    identity: str,
) -> None:
    prop = uuid4()
    for who in (
        AuthenticatedActor(
            identity, frozenset({CapabilityGrant("credits.read", frozenset({str(prop)}))})
        ),
        AuthenticatedActor(
            str(uuid4()),
            frozenset({CapabilityGrant("credits.read", frozenset({identity, str(prop)}))}),
        ),
    ):
        with patch("property_rental.credit_refund_read.psycopg.connect") as connect:
            with pytest.raises(FinancialReadAuthorizationError):
                CreditRefundReadService("unused").resolve(
                    "credit", uuid4(), "credits.read", actor=who
                )
            connect.assert_not_called()


@pytest.mark.parametrize(
    "kind,identity", [("invented", uuid4()), ("credit", UUID(int=0)), ("credit", "bad")]
)
def test_credit_refund_scope_rejects_invalid_resource(kind: Resource, identity: UUID) -> None:
    with patch("property_rental.credit_refund_read.psycopg.connect") as connect:
        with pytest.raises(FinancialReadInvalidError):
            CreditRefundReadService("unused").resolve(
                kind, identity, "credits.read", actor=staff(uuid4(), "credits.read")
            )
        connect.assert_not_called()


@pytest.mark.parametrize(
    "code,expected",
    [
        ("42501", FinancialReadAuthorizationError),
        ("P4506", FinancialReadAuthorizationError),
        ("P4501", FinancialReadNotFoundError),
        ("22023", FinancialReadInvalidError),
        ("40001", FinancialReadUnavailableError),
        ("57014", FinancialReadUnavailableError),
        ("08006", FinancialReadUnavailableError),
        (None, FinancialReadUnavailableError),
    ],
)
def test_credit_refund_scope_safe_error_mapping(
    code: str | None, expected: type[Exception]
) -> None:
    error = type("DatabaseFailure", (psycopg.Error,), {"sqlstate": code})(
        "private SQL connection evidence"
    )
    with patch("property_rental.credit_refund_read.psycopg.connect", side_effect=error):
        with pytest.raises(expected) as caught:
            CreditRefundReadService("unused").resolve(
                "credit", uuid4(), "credits.read", actor=staff(uuid4(), "credits.read")
            )
        assert "private" not in str(caught.value)


@pytest.mark.parametrize("row", [(), ({}, {}), ([],), ({},), (uuid4(),), (str(uuid4()),)])
def test_credit_refund_scope_rejects_malformed_or_foreign_result(row: object) -> None:
    conn = connection()
    conn.execute.return_value.fetchone.return_value = row
    with patch("property_rental.credit_refund_read.psycopg.connect", return_value=conn):
        with pytest.raises(FinancialReadUnavailableError):
            CreditRefundReadService("unused").resolve(
                "credit", uuid4(), "credits.read", actor=staff(uuid4(), "credits.read")
            )


@pytest.mark.parametrize("row", [None, (None,)])
def test_credit_refund_scope_missing_resource(row: object) -> None:
    conn = connection()
    conn.execute.return_value.fetchone.return_value = row
    with patch("property_rental.credit_refund_read.psycopg.connect", return_value=conn):
        with pytest.raises(FinancialReadNotFoundError):
            CreditRefundReadService("unused").resolve(
                "refund", uuid4(), "refunds.read", actor=staff(uuid4(), "refunds.read")
            )


def test_credit_refund_read_missing_runtime_has_no_financial_fallback() -> None:
    with patch("property_rental.credit_refund_read.psycopg.connect") as connect:
        with pytest.raises(FinancialReadUnavailableError):
            CreditRefundReadService(None).resolve(
                "refund", uuid4(), "refunds.read", actor=staff(uuid4(), "refunds.read")
            )
        connect.assert_not_called()


def test_credit_refund_source_audit_exact_json_and_command_permission() -> None:
    prop, payment = uuid4(), uuid4()
    who = staff(prop, "refunds.create")
    result = {
        "source_payment": {
            "id": str(payment),
            "property_id": str(prop),
            "usd_accounting_value_cents": 9_000_000_000_000_000,
        },
        "source_exchange_rate": {"rate": "4080.123456789"},
        "receipt_evidence": {"evidence_reference": "Original evidence"},
    }
    conn = connection()
    conn.execute.return_value.fetchone.return_value = (result,)
    with patch("property_rental.credit_refund_read.psycopg.connect", return_value=conn):
        assert (
            CreditRefundReadService("runtime").source_audit(prop, "PAYMENT", payment, actor=who)
            == result
        )
    assert conn.execute.call_args.args == (
        "SELECT app.credit_refund_http_source_audit(%s,%s,%s,%s)",
        (prop, "PAYMENT", payment, UUID(who.actor_id)),
    )
    loader = conn.adapters.get_loader(3802, Format.TEXT)
    assert loader is not None
    assert loader(3802).load(b'{"cents":9223372036854775807,"rate":4080.123456789}') == {
        "cents": 9223372036854775807,
        "rate": "4080.123456789",
    }
    with patch("property_rental.credit_refund_read.psycopg.connect") as connect:
        for denied in (staff(prop, "refunds.read"), staff(uuid4(), "refunds.create")):
            with pytest.raises(FinancialReadAuthorizationError):
                CreditRefundReadService("unused").source_audit(
                    prop, "PAYMENT", payment, actor=denied
                )
        connect.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        "foreign_property",
        "foreign_payment",
        "missing_payment",
        "missing_object",
        "oversized",
        "nonfinite",
        "invalid_unicode",
    ],
)
def test_credit_refund_source_audit_bounds_and_scope(failure: str) -> None:
    prop, payment = uuid4(), uuid4()
    result: object = {"source_payment": {"id": str(payment), "property_id": str(prop)}}
    assert isinstance(result, dict)
    if failure == "foreign_property":
        result["source_payment"]["property_id"] = str(uuid4())
    elif failure == "foreign_payment":
        result["source_payment"]["id"] = str(uuid4())
    elif failure == "missing_payment":
        result = {}
    elif failure == "missing_object":
        result = []
    elif failure == "oversized":
        result["evidence"] = "x" * 1_048_576
    elif failure == "nonfinite":
        result["evidence"] = float("nan")
    else:
        result["evidence"] = "\ud800"
    conn = connection()
    conn.execute.return_value.fetchone.return_value = (result,)
    with patch("property_rental.credit_refund_read.psycopg.connect", return_value=conn):
        with pytest.raises(FinancialReadUnavailableError):
            CreditRefundReadService("unused").source_audit(
                prop, "PAYMENT", payment, actor=staff(prop, "refunds.create")
            )
