"""USD Refund service transactions, exact replay, bounded reads and independent grants."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql

from payment_test_support import seed_payment
from property_rental.refund import (
    CreateUsdRefundCommand,
    RefundAuthorizationError,
    RefundIdempotencyKeyReused,
    RefundNotFoundError,
    RefundPage,
    RefundService,
    RefundUnavailableError,
    ReverseRefundCorrectionCommand,
    VerifyUsdRefundReturnCommand,
)
from test_credit_migration import actor, credit_id, recognize, source
from test_invoice_migration import financial_database_url, runtime_database_url
from test_payment_migration import fx_payment
from test_refund_migration import correct, refund
from test_reservation_migration import migrated_database_url  # noqa: F401


def service() -> RefundService:
    return RefundService(runtime_database_url(), financial_database_url())


def create(source_id: UUID, amount: int = 8000, kind: str = "PAYMENT") -> CreateUsdRefundCommand:
    return CreateUsdRefundCommand(uuid4(), kind, source_id, amount, "Return eligible excess")


def returned(amount: int = 4000) -> VerifyUsdRefundReturnCommand:
    return VerifyUsdRefundReturnCommand(
        uuid4(),
        amount,
        datetime.now(UTC),
        "Synthetic verified bank return",
        "Synthetic return evidence",
        "Correct demonstrated returned value",
    )


def refund_id(result: dict[str, object]) -> UUID:
    return UUID(str(cast(dict[str, object], result["refund"])["id"]))


def corrections(result: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], cast(dict[str, object], result["corrections"])["items"])


def cursor(page: dict[str, object]) -> RefundPage | None:
    value = page["next_cursor"]
    if value is None:
        return None
    data = cast(dict[str, str], value)
    return RefundPage(1, datetime.fromisoformat(data["occurred_at"]), UUID(data["id"]))


@pytest.mark.parametrize("kind", ["PAYMENT", "CREDIT"])
def test_refund_service_create_source_replay_verified_return_reversal_history(
    migrated_database_url: str,  # noqa: F811
    kind: str,
) -> None:
    human, prop, customer, payment = source(migrated_database_url)
    source_id = credit_id(recognize(prop, payment, human)) if kind == "CREDIT" else payment
    creator = actor(human, prop, "refunds.create")
    reader = actor(human, prop, "refunds.read")
    corrector = actor(human, prop, "refunds.correct")
    reverser = actor(human, prop, "refunds.corrections.reverse")
    preview = service().usd_source(prop, kind, source_id, actor=creator)
    assert preview == {
        "source_type": kind,
        "source_id": str(source_id),
        "recipient_customer_id": str(customer),
        "property_id": str(prop),
        "refund_currency": "USD",
        "available_usd_cents": 8000 if kind == "CREDIT" else 10000,
        "eligible": True,
    }
    command = create(source_id, kind=kind)
    original = service().create_usd(prop, command, actor=creator)
    identity = refund_id(original)
    assert service().get(prop, identity, actor=reader) == original
    assert original["source"] == {"type": kind, "id": str(source_id), "property_id": str(prop)}
    header = cast(dict[str, object], original["refund"])
    assert header["recipient_customer_id"] == str(customer)
    assert header["processed_by"] == str(human)
    assert header["authorization_reference"] == "refunds.create"
    assert header["refund_currency"] == "USD"
    assert header["refund_amount_minor"] == original["net_refund_usd_cents"] == 8000
    assert corrections(original) == []
    return_command = returned()
    corrected = service().verify_usd_return(prop, identity, return_command, actor=corrector)
    assert corrected["net_refund_usd_cents"] == 4000
    correction = corrections(corrected)[0]
    assert correction["verified_return_amount_minor"] == 4000
    assert correction["verified_return_currency"] == "USD"
    assert correction["return_method_reference"] == return_command.return_method_reference
    assert correction["authorization_reference"] == "refunds.correct"
    reversal_command = ReverseRefundCorrectionCommand(
        uuid4(), "Reviewed evidence", "Incorrect correction"
    )
    reversed_result = service().reverse_correction(
        prop, identity, UUID(str(correction["id"])), reversal_command, actor=reverser
    )
    assert reversed_result["net_refund_usd_cents"] == 8000
    assert len(corrections(reversed_result)) == 2
    assert corrections(reversed_result)[0]["reverses_correction_id"] == correction["id"]
    assert (
        corrections(reversed_result)[0]["authorization_reference"] == "refunds.corrections.reverse"
    )
    # Replay returns the immutable response from THAT command, not today's net position.
    assert service().create_usd(prop, command, actor=creator) == original
    assert service().verify_usd_return(prop, identity, return_command, actor=corrector) == corrected
    assert (
        service().reverse_correction(
            prop, identity, UUID(str(correction["id"])), reversal_command, actor=reverser
        )
        == reversed_result
    )
    assert service().get(prop, identity, actor=reader)["refund"] == header
    assert service().list(prop, actor=reader, customer_id=customer)["items"] == [
        {key: reversed_result[key] for key in ("refund", "source", "net_refund_usd_cents")}
    ]
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.refund_commands WHERE property_id=%s AND actor_id=%s",
            (prop, human),
        ).fetchone() == (3,)
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE entity_id=%s AND action LIKE 'refund.%%'",
            (identity,),
        ).fetchone() == (3,)
        assert connection.execute(
            "SELECT app.payment_available_value(%s)", (payment,)
        ).fetchone() == (2000,)
        if kind == "CREDIT":
            assert connection.execute(
                "SELECT app.credit_available_value(%s)", (source_id,)
            ).fetchone() == (0,)
    with pytest.raises(RefundUnavailableError):
        service().reverse_correction(
            prop,
            identity,
            UUID(str(correction["id"])),
            replace(reversal_command, idempotency_key=uuid4()),
            actor=reverser,
        )


def test_refund_service_each_command_key_is_exact_and_actor_scoped(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    staff = actor(human, prop, "refunds.create", "refunds.correct", "refunds.corrections.reverse")
    command = create(payment)
    result = service().create_usd(prop, command, actor=staff)
    identity = refund_id(result)
    with pytest.raises(RefundIdempotencyKeyReused):
        service().create_usd(prop, replace(command, amount_usd_cents=7000), actor=staff)
    other_human, same_prop, _, other_payment = source(migrated_database_url)
    assert same_prop == prop
    other_result = service().create_usd(
        prop,
        replace(command, source_id=other_payment),
        actor=actor(other_human, prop, "refunds.create"),
    )
    assert refund_id(other_result) != identity
    request = returned()
    corrected = service().verify_usd_return(prop, identity, request, actor=staff)
    # An equivalent instant represented in another timezone is identical intent.
    assert (
        service().verify_usd_return(
            prop,
            identity,
            replace(
                request, returned_at=request.returned_at.astimezone(timezone(timedelta(hours=7)))
            ),
            actor=staff,
        )
        == corrected
    )
    with pytest.raises(RefundIdempotencyKeyReused):
        service().verify_usd_return(
            prop, identity, replace(request, evidence_reference="Different"), actor=staff
        )
    correction_id = UUID(str(corrections(corrected)[0]["id"]))
    reversal = ReverseRefundCorrectionCommand(uuid4(), "Evidence", "Correction reversal")
    service().reverse_correction(prop, identity, correction_id, reversal, actor=staff)
    with pytest.raises(RefundIdempotencyKeyReused):
        service().reverse_correction(
            prop, identity, correction_id, replace(reversal, reason="Different"), actor=staff
        )


@pytest.mark.parametrize("action", ["create", "return", "reverse", "get", "list", "source"])
def test_refund_service_fresh_disabled_actor_rejected_before_replay(
    migrated_database_url: str,  # noqa: F811
    action: str,
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    staff = actor(
        human,
        prop,
        "refunds.create",
        "refunds.read",
        "refunds.correct",
        "refunds.corrections.reverse",
    )
    command = create(payment)
    identity = refund_id(service().create_usd(prop, command, actor=staff))
    request = returned()
    correction_id = UUID(
        str(corrections(service().verify_usd_return(prop, identity, request, actor=staff))[0]["id"])
    )
    reversal = ReverseRefundCorrectionCommand(uuid4(), "Evidence", "Correction reversal")
    service().reverse_correction(prop, identity, correction_id, reversal, actor=staff)
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    with pytest.raises(RefundAuthorizationError):
        if action == "create":
            service().create_usd(prop, command, actor=staff)
        elif action == "return":
            service().verify_usd_return(prop, identity, request, actor=staff)
        elif action == "reverse":
            service().reverse_correction(prop, identity, correction_id, reversal, actor=staff)
        elif action == "get":
            service().get(prop, identity, actor=staff)
        elif action == "list":
            service().list(prop, actor=staff)
        else:
            service().usd_source(prop, "PAYMENT", payment, actor=staff)


def test_refund_service_wrong_property_customer_and_resource_are_not_disclosed(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, payment = source(migrated_database_url)
    other_human, _, other_customer, _ = source(migrated_database_url)
    other_prop = uuid4()  # V1 has one Property; an unknown scope must not authorize it.
    staff = actor(human, prop, "refunds.create", "refunds.read", "refunds.correct")
    identity = refund_id(service().create_usd(prop, create(payment), actor=staff))
    other = actor(other_human, other_prop, "refunds.create", "refunds.read", "refunds.correct")
    with pytest.raises(RefundNotFoundError):
        service().get(other_prop, identity, actor=other)
    with pytest.raises(RefundNotFoundError):
        service().usd_source(other_prop, "PAYMENT", payment, actor=other)
    with pytest.raises(RefundNotFoundError):
        service().create_usd(prop, create(uuid4()), actor=staff)
    with pytest.raises(RefundNotFoundError):
        service().verify_usd_return(other_prop, identity, returned(), actor=other)
    with pytest.raises(RefundNotFoundError):
        service().list(other_prop, actor=other, customer_id=customer)
    assert service().list(prop, actor=staff, customer_id=other_customer) == {
        "items": [],
        "next_cursor": None,
    }
    assert service().list(prop, actor=staff, customer_id=uuid4()) == {
        "items": [],
        "next_cursor": None,
    }


@pytest.mark.parametrize("same_key", [False, True])
def test_refund_service_concurrent_commands_replay_once_or_fail_closed(
    migrated_database_url: str,  # noqa: F811
    same_key: bool,
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    staff = actor(human, prop, "refunds.create")
    first = create(payment, 7000)
    commands = [first, first if same_key else replace(first, idempotency_key=uuid4())]
    barrier = Barrier(2)

    def worker(command: CreateUsdRefundCommand) -> UUID | None:
        barrier.wait(timeout=5)
        try:
            return refund_id(service().create_usd(prop, command, actor=staff))
        except RefundUnavailableError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, commands))
    if same_key:
        assert results[0] is not None and results[0] == results[1]
    else:
        assert sum(value is not None for value in results) == 1
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT app.payment_available_value(%s)", (payment,)
        ).fetchone() == (3000,)
        assert connection.execute(
            "SELECT count(*) FROM app.refund_commands WHERE property_id=%s AND actor_id=%s",
            (prop, human),
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM app.refunds WHERE source_payment_id=%s", (payment,)
        ).fetchone() == (1,)


def test_refund_service_transaction_rollback_removes_refund_receipt_and_audit(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    key = uuid4()
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(ValueError, match="Synthetic cancellation"), connection.transaction():
            row = connection.execute(
                "SELECT app.create_usd_refund(%s,%s,%s,'PAYMENT',%s,100,'Return excess')",
                (prop, human, key, payment),
            ).fetchone()
            assert row is not None
            identity = refund_id(row[0])
            assert connection.execute(
                "SELECT count(*) FROM app.refund_commands WHERE idempotency_key=%s", (key,)
            ).fetchone() == (1,)
            assert connection.execute(
                "SELECT count(*) FROM app.audit_events WHERE entity_id=%s", (identity,)
            ).fetchone() == (1,)
            raise ValueError("Synthetic cancellation")
        assert connection.execute(
            "SELECT count(*) FROM app.refund_commands WHERE idempotency_key=%s", (key,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.refunds WHERE id=%s", (identity,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE entity_id=%s", (identity,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT app.payment_available_value(%s)", (payment,)
        ).fetchone() == (10000,)


def test_refund_service_bounded_pages_walk_source_ties_and_strict_corrections(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, payment = source(migrated_database_url)
    reader = actor(human, prop, "refunds.read")
    with psycopg.connect(migrated_database_url) as connection:
        # Equal timestamps are valid across distinct roots, not within one
        # source/correction chain whose chronology is deliberately strict.
        payments = [payment] + [
            seed_payment(
                connection, actor_id=human, property_id=prop, customer_id=customer, amount=10000
            )
            for _ in range(2)
        ]
        at = datetime.now(UTC)
        identities = [
            refund(
                connection,
                human,
                customer,
                payment=payment_id,
                amount=1000,
                overrides={"processed_at": at},
            )
            for payment_id in payments
        ]
        changes = [
            correct(
                connection,
                human,
                identities[0],
                100,
            )
            for _ in range(3)
        ]
    listed: list[str] = []
    page: RefundPage | None = RefundPage(1)
    while page is not None:
        result = service().list(prop, actor=reader, customer_id=customer, page=page)
        items = cast(list[dict[str, object]], result["items"])
        assert len(items) == 1
        listed.append(str(refund_id(items[0])))
        page = cursor(result)
    assert listed == [str(value) for value in sorted(identities, reverse=True)]
    listed = []
    page = RefundPage(1)
    while page is not None:
        result = service().get(prop, identities[0], actor=reader, page=page)
        assert result["net_refund_usd_cents"] == 700
        items = corrections(result)
        assert len(items) == 1
        listed.append(str(items[0]["id"]))
        page = cursor(cast(dict[str, object], result["corrections"]))
    assert listed == [str(value) for value in reversed(changes)]


def test_refund_service_coherent_history_during_concurrent_corrections(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    staff = actor(human, prop, "refunds.create", "refunds.read", "refunds.correct")
    identity = refund_id(service().create_usd(prop, create(payment), actor=staff))
    barrier = Barrier(2)

    def writer() -> None:
        barrier.wait(timeout=5)
        for _ in range(20):
            service().verify_usd_return(prop, identity, returned(10), actor=staff)

    def reader() -> None:
        barrier.wait(timeout=5)
        for _ in range(40):
            result = service().get(prop, identity, actor=staff)
            assert result["net_refund_usd_cents"] == 8000 - sum(
                int(str(item["source_balance_effect_usd_cents"])) for item in corrections(result)
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(writer), pool.submit(reader)]
        for future in futures:
            future.result(timeout=10)
    # A pre-existing repeatable-read snapshot is also internally coherent.
    with psycopg.connect(runtime_database_url()) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        before = connection.execute(
            "SELECT app.refund_resource(%s,%s,%s,50,NULL,NULL)", (prop, identity, human)
        ).fetchone()
        service().verify_usd_return(prop, identity, returned(10), actor=staff)
        assert (
            connection.execute(
                "SELECT app.refund_resource(%s,%s,%s,50,NULL,NULL)", (prop, identity, human)
            ).fetchone()
            == before
        )


@pytest.mark.parametrize("kind", ["PAYMENT", "CREDIT"])
def test_refund_service_khr_origin_refunds_usd_and_preserves_fx(
    migrated_database_url: str,  # noqa: F811
    kind: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        payment = fx_payment(connection, channel=True, channel_rate=Decimal("4101.123456"))
        row = connection.execute(
            "SELECT confirmed_by,property_id FROM app.payments WHERE id=%s", (payment,)
        ).fetchone()
        assert row is not None
        human, prop = map(lambda value: UUID(str(value)), row)
    staff = actor(human, prop, "refunds.create", "refunds.read")
    identity = credit_id(recognize(prop, payment, human, 101)) if kind == "CREDIT" else payment
    preview = service().usd_source(prop, kind, identity, actor=staff)
    assert preview["refund_currency"] == "USD"
    assert preview["available_usd_cents"] == 101
    result = service().create_usd(prop, create(identity, 101, kind), actor=staff)
    payment_data = cast(dict[str, object], result["source_payment"])
    rate = cast(dict[str, object], result["source_exchange_rate"])
    assert payment_data["id"] == str(payment)
    assert payment_data["received_currency"] == "KHR"
    assert rate["channel_actual_rate_khr_per_usd"] == "4101.123456"
    assert payment_data["exchange_rate_record_id"] == rate["id"]
    assert result["net_refund_usd_cents"] == 101
    header = cast(dict[str, object], result["refund"])
    assert header["refund_currency"] == "USD"
    assert header["refund_amount_minor"] == header["usd_accounting_value_cents"] == 101


@pytest.mark.parametrize("kind", ["PAYMENT", "CREDIT"])
def test_khr_origin_usd_partial_returns_reconcile_exact_cents_and_preserve_history(
    migrated_database_url: str,  # noqa: F811
    kind: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        payment = fx_payment(connection, channel=True, amount=4100, usd=101)
        row = connection.execute(
            "SELECT confirmed_by,property_id FROM app.payments WHERE id=%s", (payment,)
        ).fetchone()
        assert row is not None
        human, prop = map(lambda value: UUID(str(value)), row)
        before = connection.execute(
            "SELECT row_to_json(p)::text,row_to_json(fx)::text FROM app.payments p "
            "JOIN app.exchange_rate_records fx ON fx.id=p.exchange_rate_record_id WHERE p.id=%s",
            (payment,),
        ).fetchone()
    staff = actor(
        human,
        prop,
        "refunds.create",
        "refunds.read",
        "refunds.correct",
        "refunds.corrections.reverse",
    )
    source_id = credit_id(recognize(prop, payment, human, 101)) if kind == "CREDIT" else payment
    original_command = create(source_id, 101, kind)
    original = service().create_usd(prop, original_command, actor=staff)
    identity = refund_id(original)
    first_return = returned(1)
    first = service().verify_usd_return(prop, identity, first_return, actor=staff)
    first_correction = UUID(str(corrections(first)[0]["id"]))
    assert first["net_refund_usd_cents"] == 100
    assert service().verify_usd_return(prop, identity, first_return, actor=staff) == first
    assert service().usd_source(prop, kind, source_id, actor=staff)["available_usd_cents"] == 1
    for amount, remaining in ((1, 99), (99, 0)):
        result = service().verify_usd_return(prop, identity, returned(amount), actor=staff)
        assert result["net_refund_usd_cents"] == remaining
    final = service().get(prop, identity, actor=staff)
    assert final["refund"] == original["refund"]
    assert (
        sum(int(str(item["source_balance_effect_usd_cents"])) for item in corrections(final)) == 101
    )
    for item in corrections(final):
        assert item["verified_return_currency"] == "USD"
        assert (
            item["source_balance_effect_original_minor"] == item["source_balance_effect_usd_cents"]
        )
        assert item["verified_return_amount_minor"] == item["source_balance_effect_usd_cents"]
    with pytest.raises(RefundUnavailableError):
        service().verify_usd_return(prop, identity, returned(1), actor=staff)
    assert service().create_usd(prop, original_command, actor=staff) == original
    assert service().usd_source(prop, kind, source_id, actor=staff)["available_usd_cents"] == 101
    reverse_command = ReverseRefundCorrectionCommand(
        uuid4(), "Synthetic reversal evidence", "Reverse one cent"
    )
    reversed_result = service().reverse_correction(
        prop, identity, first_correction, reverse_command, actor=staff
    )
    assert reversed_result["net_refund_usd_cents"] == 1
    assert service().usd_source(prop, kind, source_id, actor=staff)["available_usd_cents"] == 100
    service().create_usd(prop, create(source_id, 100, kind), actor=staff)
    assert service().usd_source(prop, kind, source_id, actor=staff)["available_usd_cents"] == 0
    with psycopg.connect(migrated_database_url) as connection:
        assert (
            connection.execute(
                "SELECT row_to_json(p)::text,row_to_json(fx)::text FROM app.payments p "
                "JOIN app.exchange_rate_records fx ON fx.id=p.exchange_rate_record_id "
                "WHERE p.id=%s",
                (payment,),
            ).fetchone()
            == before
        )


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_refund_command_receipts_are_immutable_and_private(
    migrated_database_url: str,  # noqa: F811
    operation: str,
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    command = create(payment)
    service().create_usd(prop, command, actor=actor(human, prop, "refunds.create"))
    with psycopg.connect(migrated_database_url) as connection:
        query = {
            "UPDATE": (
                "UPDATE app.refund_commands SET completed_at=completed_at WHERE idempotency_key=%s"
            ),
            "DELETE": "DELETE FROM app.refund_commands WHERE idempotency_key=%s",
            "TRUNCATE": "TRUNCATE app.refund_commands",
        }[operation]
        with pytest.raises(psycopg.Error), connection.transaction():
            connection.execute(
                query, (command.idempotency_key,) if operation != "TRUNCATE" else None
            )
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert connection.execute(
                    "SELECT has_table_privilege(%s,'app.refund_commands',%s)", (role, privilege)
                ).fetchone() == (False,)
        for signature in (
            "refund_property_id(uuid)",
            "refund_summary(uuid)",
            "assert_refund_page(integer,timestamptz,uuid)",
            "refund_command_replay(uuid,uuid,text,uuid,jsonb)",
            "require_usd_refund_source(uuid,text,uuid)",
            "require_correctable_usd_refund(uuid,uuid)",
        ):
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, f"app.{signature}")
                ).fetchone() == (False,)


@pytest.mark.parametrize(
    ("limit", "at", "identity"),
    [
        (0, None, None),
        (101, None, None),
        (None, None, None),
        (1, "infinity", uuid4()),
        (1, datetime.now(UTC), None),
        (1, None, uuid4()),
        (1, datetime.now(UTC), UUID(int=0)),
    ],
)
def test_refund_database_page_parameters_fail_closed(
    migrated_database_url: str,  # noqa: F811
    limit: int | None,
    at: datetime | str | None,
    identity: UUID | None,
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    target = refund_id(
        service().create_usd(prop, create(payment), actor=actor(human, prop, "refunds.create"))
    )
    with psycopg.connect(runtime_database_url()) as connection:
        for function, params in (
            ("refund_resource", (prop, target, human, limit, at, identity)),
            ("list_refunds", (prop, human, None, limit, at, identity)),
        ):
            with pytest.raises(psycopg.Error) as caught, connection.transaction():
                connection.execute(
                    sql.SQL("SELECT app.{}(%s,%s,%s,%s,%s,%s)").format(sql.Identifier(function)),
                    params,
                )
            assert caught.value.sqlstate == "P5202"


@pytest.mark.parametrize("action", ["return", "reverse"])
def test_refund_service_correction_rollback_removes_event_receipt_and_audit(
    migrated_database_url: str,  # noqa: F811
    action: str,
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    staff = actor(human, prop, "refunds.create", "refunds.correct")
    identity = refund_id(service().create_usd(prop, create(payment), actor=staff))
    original_correction: UUID | None = None
    if action == "reverse":
        result = service().verify_usd_return(prop, identity, returned(), actor=staff)
        original_correction = UUID(str(corrections(result)[0]["id"]))
    key = uuid4()
    with psycopg.connect(migrated_database_url) as connection:
        before = connection.execute(
            "SELECT app.refund_net_value_at(%s,'infinity'),"
            "(SELECT count(*) FROM app.refund_corrections WHERE refund_id=%s),"
            "(SELECT count(*) FROM app.audit_events WHERE entity_id=%s)",
            (identity, identity, identity),
        ).fetchone()
        with pytest.raises(ValueError, match="Synthetic cancellation"), connection.transaction():
            if action == "return":
                row = connection.execute(
                    "SELECT app.verify_usd_refund_return(%s,%s,%s,%s,100,%s,"
                    "'Method','Evidence','Reason')",
                    (prop, identity, human, key, datetime.now(UTC)),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT app.reverse_refund_correction(%s,%s,%s,%s,%s,'Evidence','Reason')",
                    (prop, identity, original_correction, human, key),
                ).fetchone()
            assert row is not None
            assert connection.execute(
                "SELECT count(*) FROM app.refund_commands WHERE idempotency_key=%s", (key,)
            ).fetchone() == (1,)
            raise ValueError("Synthetic cancellation")
        assert (
            connection.execute(
                "SELECT app.refund_net_value_at(%s,'infinity'),"
                "(SELECT count(*) FROM app.refund_corrections WHERE refund_id=%s),"
                "(SELECT count(*) FROM app.audit_events WHERE entity_id=%s)",
                (identity, identity, identity),
            ).fetchone()
            == before
        )
        assert connection.execute(
            "SELECT count(*) FROM app.refund_commands WHERE idempotency_key=%s", (key,)
        ).fetchone() == (0,)


def test_refund_service_facade_database_roles_are_separated(migrated_database_url: str) -> None:  # noqa: F811
    with psycopg.connect(migrated_database_url) as connection:
        reads = (
            "refund_resource(uuid,uuid,uuid,integer,timestamptz,uuid)",
            "list_refunds(uuid,uuid,uuid,integer,timestamptz,uuid)",
            "usd_refund_source(uuid,uuid,text,uuid)",
        )
        writes = (
            "create_usd_refund(uuid,uuid,uuid,text,uuid,bigint,text)",
            "verify_usd_refund_return(uuid,uuid,uuid,uuid,bigint,timestamptz,text,text,text)",
            "reverse_refund_correction(uuid,uuid,uuid,uuid,uuid,text,text)",
        )
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
            for signature in (*reads, *writes):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, f"app.{signature}")
                ).fetchone() == (
                    role == "prm_financial" or (role == "prm_runtime" and signature in reads),
                )
