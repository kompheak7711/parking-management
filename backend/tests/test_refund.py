"""Immutable exact Refund intents, scoped capabilities, and safe unknown outcomes."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.adapt import AdaptersMap
from psycopg.pq import Format
from psycopg.types.json import JsonbLoader

from property_rental.identity import AuthenticatedActor
from property_rental.refund import (
    CreateUsdRefundCommand,
    RefundAuthorizationError,
    RefundIdempotencyKeyReused,
    RefundInvalidError,
    RefundNotFoundError,
    RefundPage,
    RefundService,
    RefundUnavailableError,
    ReverseRefundCorrectionCommand,
    VerifyUsdRefundReturnCommand,
)
from test_credit import staff


def create() -> CreateUsdRefundCommand:
    return CreateUsdRefundCommand(uuid4(), "PAYMENT", uuid4(), 100, "Return eligible excess")


def returned() -> VerifyUsdRefundReturnCommand:
    return VerifyUsdRefundReturnCommand(
        uuid4(), 100, datetime.now(UTC), "Synthetic bank return", "Verified evidence", "Correction"
    )


@pytest.mark.parametrize("amount", [0, -1, True, 1.5, 9_000_000_000_000_001])
def test_refund_requires_exact_positive_bounded_minor_units(amount: int) -> None:
    with pytest.raises(RefundInvalidError):
        replace(create(), amount_usd_cents=amount)
    with pytest.raises(RefundInvalidError):
        replace(returned(), returned_amount_minor=amount)


@pytest.mark.parametrize("reason", ["", " ", " leading", "trailing ", "x" * 1001, "\x00", "\ud800"])
def test_refund_commands_require_normalized_bounded_valid_text(reason: str) -> None:
    with pytest.raises(RefundInvalidError):
        replace(create(), reason=reason)
    with pytest.raises(RefundInvalidError):
        replace(returned(), reason=reason)
    with pytest.raises(RefundInvalidError):
        ReverseRefundCorrectionCommand(uuid4(), "Evidence", reason)


@pytest.mark.parametrize("field", ["return_method_reference", "evidence_reference"])
@pytest.mark.parametrize("value", ["", " leading", "x" * 501])
def test_refund_verified_return_requires_bounded_evidence(field: str, value: str) -> None:
    with pytest.raises(RefundInvalidError):
        if field == "return_method_reference":
            replace(returned(), return_method_reference=value)
        else:
            replace(returned(), evidence_reference=value)


@pytest.mark.parametrize("kind", ["DEPOSIT", "UNKNOWN", "payment", None])
def test_refund_usd_source_family_is_explicit(kind: str) -> None:
    with pytest.raises(RefundInvalidError):
        replace(create(), source_kind=kind)


@pytest.mark.parametrize("identity", [UUID(int=0), "not-a-uuid"])
def test_refund_commands_require_non_nil_uuid(identity: UUID) -> None:
    with pytest.raises(RefundInvalidError):
        replace(create(), idempotency_key=identity)
    with pytest.raises(RefundInvalidError):
        replace(create(), source_id=identity)
    with pytest.raises(RefundInvalidError):
        replace(returned(), idempotency_key=identity)
    with pytest.raises(RefundInvalidError):
        ReverseRefundCorrectionCommand(identity, "Evidence", "Reason")


@pytest.mark.parametrize(
    "instant",
    [
        datetime(2026, 1, 1),
        "infinity",
        datetime.min.replace(tzinfo=timezone(timedelta(hours=1))),
        datetime.max.replace(tzinfo=timezone(timedelta(hours=-1))),
    ],
)
def test_refund_return_timestamp_must_be_aware_and_representable(instant: datetime) -> None:
    with pytest.raises(RefundInvalidError):
        replace(returned(), returned_at=instant)


def test_refund_commands_are_immutable_and_timestamp_is_canonical() -> None:
    instant = datetime(2026, 9, 6, 7, tzinfo=timezone(timedelta(hours=7)))
    request = replace(returned(), returned_at=instant)
    assert request.returned_at == datetime(2026, 9, 6, tzinfo=UTC)
    assert request.returned_at.tzinfo is UTC
    with pytest.raises(FrozenInstanceError):
        request.returned_amount_minor = 9  # type: ignore[misc]


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, 101])
def test_refund_page_limit_is_bounded_exact_integer(limit: int) -> None:
    with pytest.raises(RefundInvalidError):
        RefundPage(limit)


def test_refund_cursor_is_complete_finite_and_non_nil() -> None:
    for instant, identity in (
        (datetime.now(UTC), None),
        (None, uuid4()),
        (datetime.now(UTC), UUID(int=0)),
        (datetime(2026, 1, 1), uuid4()),
    ):
        with pytest.raises(RefundInvalidError):
            RefundPage(10, instant, identity)


CAPABILITIES = {
    "get": "refunds.read",
    "list": "refunds.read",
    "usd_source": "refunds.create",
    "create_usd": "refunds.create",
    "verify_usd_return": "refunds.correct",
    "reverse_correction": "refunds.corrections.reverse",
}


def invoke(
    service: RefundService, operation: str, prop: UUID, actor: AuthenticatedActor
) -> dict[str, object]:
    target = uuid4()
    if operation == "get":
        return service.get(prop, target, actor=actor)
    if operation == "list":
        return service.list(prop, actor=actor, customer_id=target)
    if operation == "usd_source":
        return service.usd_source(prop, "PAYMENT", target, actor=actor)
    if operation == "create_usd":
        return service.create_usd(prop, create(), actor=actor)
    if operation == "verify_usd_return":
        return service.verify_usd_return(prop, target, returned(), actor=actor)
    return service.reverse_correction(
        prop,
        target,
        uuid4(),
        ReverseRefundCorrectionCommand(uuid4(), "Evidence", "Reason"),
        actor=actor,
    )


@pytest.mark.parametrize("operation", CAPABILITIES)
def test_refund_capabilities_are_independent_and_property_scoped(operation: str) -> None:
    prop = uuid4()
    expected = CAPABILITIES[operation]
    with patch("property_rental.refund.psycopg.connect") as connect:
        for actor in (
            staff(prop),
            staff(uuid4(), expected),
            staff(prop, *(set(CAPABILITIES.values()) - {expected})),
            AuthenticatedActor("not-a-uuid", staff(prop, expected).capability_grants),
        ):
            with pytest.raises(RefundAuthorizationError):
                invoke(RefundService("read", "write"), operation, prop, actor)
        connect.assert_not_called()


@pytest.mark.parametrize("operation", CAPABILITIES)
def test_refund_each_capability_works_alone_with_correct_connection(operation: str) -> None:
    prop = uuid4()
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = ({"exact_usd_cents": 123},)
    with patch("property_rental.refund.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        assert invoke(
            RefundService("read", "write"), operation, prop, staff(prop, CAPABILITIES[operation])
        ) == {"exact_usd_cents": 123}
        connect.assert_called_once_with(
            "read" if operation in {"get", "list", "usd_source"} else "write", connect_timeout=3
        )
    assert connection.execute.call_args_list[0].args == ("SET LOCAL lock_timeout='3000ms'",)
    assert connection.execute.call_args_list[1].args == ("SET LOCAL statement_timeout='5000ms'",)


def test_refund_complete_command_envelope_and_transmission_revalidation() -> None:
    prop = uuid4()
    actor = staff(prop, "refunds.create")
    request = create()
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = ({"refund": {}},)
    with patch("property_rental.refund.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        service = RefundService("read", "write")
        service.create_usd(prop, request, actor=actor)
        connection.execute.assert_called_with(
            "SELECT app.create_usd_refund(%s,%s,%s,%s,%s,%s,%s)",
            (
                prop,
                UUID(actor.actor_id),
                request.idempotency_key,
                "PAYMENT",
                request.source_id,
                100,
                request.reason,
            ),
        )
        connect.reset_mock()
        object.__setattr__(request, "amount_usd_cents", True)
        with pytest.raises(RefundInvalidError):
            service.create_usd(prop, request, actor=actor)
        page = RefundPage()
        object.__setattr__(page, "limit", 1001)
        with pytest.raises(RefundInvalidError):
            service.list(prop, actor=staff(prop, "refunds.read"), page=page)
        connect.assert_not_called()


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        ("P5201", RefundNotFoundError),
        ("P4501", RefundNotFoundError),
        ("P5202", RefundInvalidError),
        ("P5205", RefundIdempotencyKeyReused),
        ("P4506", RefundAuthorizationError),
        ("42501", RefundAuthorizationError),
        ("40001", RefundUnavailableError),
        ("55P03", RefundUnavailableError),
        ("23514", RefundUnavailableError),
        (None, RefundUnavailableError),
    ],
)
def test_refund_failure_preserves_original_command_and_safe_message(
    sqlstate: str | None, expected: type[Exception]
) -> None:
    class DatabaseError(psycopg.Error):
        pass

    error = DatabaseError("Synthetic private diagnostic")
    error.sqlstate = sqlstate
    request = create()
    before = replace(request)
    prop = uuid4()
    with patch("property_rental.refund.psycopg.connect", side_effect=error):
        with pytest.raises(expected) as caught:
            RefundService("read", "write").create_usd(
                prop, request, actor=staff(prop, "refunds.create")
            )
    assert "private diagnostic" not in str(caught.value)
    assert request == before


def test_refund_response_decoder_is_exact_nested_and_connection_local() -> None:
    connection = MagicMock()
    connection.adapters = AdaptersMap(psycopg.adapters)
    connection.execute.return_value.fetchone.return_value = ({"net_refund_usd_cents": 101},)
    prop = uuid4()
    with patch("property_rental.refund.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        RefundService("read", "write").get(prop, uuid4(), actor=staff(prop, "refunds.read"))
    raw = (
        b'{"reference_rate":10000000000.000001,"amount_usd_cents":101,'
        b'"trace":{"ratio":0.1234567890123456789,"values":[4062.123456,1]}}'
    )
    loader = connection.adapters.get_loader(3802, Format.TEXT)
    assert loader is not None
    assert loader(3802).load(raw) == {
        "reference_rate": "10000000000.000001",
        "amount_usd_cents": 101,
        "trace": {"ratio": "0.1234567890123456789", "values": ["4062.123456", 1]},
    }
    assert isinstance(JsonbLoader(3802).load(raw)["reference_rate"], float)
