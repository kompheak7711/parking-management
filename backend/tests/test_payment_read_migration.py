"""Payment read projections over isolated synthetic current-head PostgreSQL."""

from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest

from payment_test_support import seed_payment
from property_rental.payment_read import (
    _DETAIL,
    PaymentFilters,
    PaymentPage,
    PaymentReadAuthorizationError,
    PaymentReadNotFoundError,
    PaymentReadService,
)
from test_credit_migration import actor, credit_id, recognize, source
from test_invoice_migration import runtime_database_url
from test_payment_migration import fx_payment, reverse
from test_refund_migration import refund
from test_refund_service_migration import create, refund_id, returned
from test_refund_service_migration import service as refunds
from test_reservation_migration import migrated_database_url  # noqa: F401


def service() -> PaymentReadService:
    return PaymentReadService(runtime_database_url())


def header(result: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], result["payment"])


def position(result: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], result["position"])


def items(result: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], result["items"])


def test_payment_read_preserves_original_facts_receipt_and_exact_usd_position(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, payment = source(migrated_database_url, 9_000_000_000_000_000)
    reader = actor(human, prop, "payments.read")
    with psycopg.connect(migrated_database_url) as connection:
        before = connection.execute(
            "SELECT to_jsonb(p),to_jsonb(r),g.revision FROM app.payments p "
            "JOIN app.receipts r ON r.payment_id=p.id "
            "JOIN app.payment_serialization_guards g ON g.payment_id=p.id WHERE p.id=%s",
            (payment,),
        ).fetchone()
        assert before is not None
    detail = service().get(prop, payment, actor=reader)
    assert header(detail) == before[0]
    assert detail["receipt"] == {
        "id": before[1]["id"],
        "receipt_number": before[1]["receipt_number"],
    }
    assert header(detail)["payer_customer_id"] == str(customer)
    assert header(detail)["received_currency"] == "USD"
    assert header(detail)["received_amount_minor"] == 9_000_000_000_000_000
    assert position(detail) == {
        "currency": "USD",
        "original_usd_cents": 9_000_000_000_000_000,
        "available_usd_cents": 9_000_000_000_000_000,
        "dispositions": {
            "allocation_usd_cents": 0,
            "deposit_usd_cents": 0,
            "credit_usd_cents": 0,
            "refund_usd_cents": 0,
        },
    }
    assert detail["exchange_rate"] is None and detail["exchange_rate_evidence_id"] is None
    assert detail["reversal"] is None and detail["property_timezone"] == "Asia/Phnom_Penh"
    assert items(service().list(prop, filters=PaymentFilters(customer), actor=reader)) == [detail]
    with psycopg.connect(migrated_database_url) as connection:
        assert (
            connection.execute(
                "SELECT to_jsonb(p),to_jsonb(r),g.revision FROM app.payments p "
                "JOIN app.receipts r ON r.payment_id=p.id "
                "JOIN app.payment_serialization_guards g ON g.payment_id=p.id WHERE p.id=%s",
                (payment,),
            ).fetchone()
            == before
        )


def test_payment_reads_reconcile_credit_and_direct_usd_refund_without_double_consumption(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    reader = actor(human, prop, "payments.read")
    original = header(service().get(prop, payment, actor=reader))
    credit = credit_id(recognize(prop, payment, human, 2000))
    refunds().create_usd(
        prop, create(credit, 1000, "CREDIT"), actor=actor(human, prop, "refunds.create")
    )
    direct = refunds().create_usd(
        prop, create(payment, 3000), actor=actor(human, prop, "refunds.create")
    )
    refunds().verify_usd_return(
        prop, refund_id(direct), returned(500), actor=actor(human, prop, "refunds.correct")
    )
    current = service().get(prop, payment, actor=reader)
    assert header(current) == original
    assert header(current)["status"] == "RECEIVED"
    assert position(current)["dispositions"] == {
        "allocation_usd_cents": 0,
        "deposit_usd_cents": 0,
        "credit_usd_cents": 2000,
        "refund_usd_cents": 2500,
    }
    assert position(current)["available_usd_cents"] == 5500


def test_payment_reads_keep_method_snapshots_after_configuration_rename_and_retirement(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, payment = source(migrated_database_url)
    reader = actor(human, prop, "payments.read")
    original = service().get(prop, payment, actor=reader)
    method = UUID(str(header(original)["payment_method_id"]))
    with psycopg.connect(migrated_database_url) as connection:
        configured = connection.execute(
            "SELECT display_name,accepted FROM app.payment_methods WHERE id=%s", (method,)
        ).fetchone()
        assert configured is not None
        connection.execute(
            "UPDATE app.payment_methods SET display_name='Synthetic retired method',"
            "accepted=false WHERE id=%s",
            (method,),
        )
    try:
        assert service().get(prop, payment, actor=reader) == original
        assert items(service().list(prop, filters=PaymentFilters(customer), actor=reader)) == [
            original
        ]
    finally:
        # Restore shared synthetic configuration, never rewrite the Payment snapshot.
        with psycopg.connect(migrated_database_url) as connection:
            connection.execute(
                "UPDATE app.payment_methods SET display_name=%s,accepted=%s WHERE id=%s",
                (*configured, method),
            )


def test_payment_reversal_keeps_original_receipt_and_zero_available_value(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, payment = source(migrated_database_url)
    reader = actor(human, prop, "payments.read")
    original = service().get(prop, payment, actor=reader)
    with psycopg.connect(migrated_database_url) as connection:
        reversal = reverse(connection, payment, human)
    current = service().get(prop, payment, actor=reader)
    assert header(current) == {**header(original), "status": "REVERSED"}
    assert current["receipt"] == original["receipt"]
    assert position(current)["original_usd_cents"] == 10000
    assert position(current)["available_usd_cents"] == 0
    assert cast(dict[str, object], current["reversal"])["id"] == str(reversal)
    assert items(
        service().list(prop, filters=PaymentFilters(customer, "REVERSED"), actor=reader)
    ) == [current]
    assert (
        items(service().list(prop, filters=PaymentFilters(customer, "RECEIVED"), actor=reader))
        == []
    )


def test_payment_keysets_filter_customer_method_and_keep_tied_dates_without_duplicates(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, first = source(migrated_database_url)
    ids = [first]
    now = datetime.now(UTC)
    with psycopg.connect(migrated_database_url) as connection:
        for days in (0, 0, 1, 2):
            ids.append(
                seed_payment(
                    connection,
                    actor_id=human,
                    property_id=prop,
                    customer_id=customer,
                    amount=100,
                    confirmed_at=now - timedelta(days=days),
                )
            )
    _, _, other_customer, other_payment = source(migrated_database_url)
    reader = actor(human, prop, "payments.read")
    all_items = items(service().list(prop, filters=PaymentFilters(customer), actor=reader))
    assert {header(item)["id"] for item in all_items} == {str(identity) for identity in ids}
    pairs = [(header(item)["payment_date"], header(item)["id"]) for item in all_items]
    assert pairs == sorted(pairs, reverse=True)
    seen: list[dict[str, object]] = []
    page = PaymentPage(2)
    for _ in range(5):
        result = service().list(prop, page, PaymentFilters(customer), actor=reader)
        assert len(items(result)) <= 2
        seen.extend(items(result))
        if result["next_cursor"] is None:
            break
        cursor = cast(dict[str, str], result["next_cursor"])
        page = PaymentPage(2, date.fromisoformat(cursor["payment_date"]), UUID(cursor["id"]))
    else:
        pytest.fail("Payment cursor did not terminate")
    assert seen == all_items
    assert str(other_payment) not in {header(item)["id"] for item in seen}
    assert header(
        items(service().list(prop, filters=PaymentFilters(other_customer), actor=reader))[0]
    )["id"] == str(other_payment)
    method = UUID(str(header(all_items[0])["payment_method_id"]))
    assert (
        items(
            service().list(
                prop, filters=PaymentFilters(customer, payment_method_id=method), actor=reader
            )
        )
        == all_items
    )
    assert (
        items(
            service().list(
                prop, filters=PaymentFilters(customer, payment_method_id=uuid4()), actor=reader
            )
        )
        == []
    )


def test_payment_khr_read_preserves_original_channel_fx_and_usd_accounting_only(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        payment = fx_payment(connection, channel=True, amount=4100)
        row = connection.execute(
            "SELECT p.confirmed_by,p.property_id,to_jsonb(p),rate::text FROM app.payments p "
            "JOIN app.exchange_rate_records rate ON rate.id=p.exchange_rate_record_id "
            "WHERE p.id=%s",
            (payment,),
        ).fetchone()
        assert row is not None
    human, prop, original, fx_text = row
    detail = service().get(prop, payment, actor=actor(human, prop, "payments.read"))
    assert header(detail) == original
    assert header(detail)["received_currency"] == "KHR"
    assert header(detail)["received_amount_minor"] == 4100
    assert position(detail)["original_usd_cents"] == position(detail)["available_usd_cents"] == 101
    assert position(detail)["currency"] == "USD"
    fx = cast(dict[str, object], detail["exchange_rate"])
    assert fx["reference_rate_khr_per_usd"] == "4080.000000"
    assert fx["system_rate_khr_per_usd"] == 4101
    assert fx["channel_actual_amount_minor"] == 4100
    assert fx["channel_actual_usd_value_cents"] == 101
    assert detail["exchange_rate_evidence_id"] == fx["id"] == original["exchange_rate_record_id"]
    assert "source_reference" not in fx and "calculation_trace" not in fx
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT rate::text FROM app.exchange_rate_records rate WHERE id=%s", (fx["id"],)
        ).fetchone() == (fx_text,)


def test_payment_read_denies_cross_property_missing_and_freshly_disabled_actor(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    wrong_prop = uuid4()
    with pytest.raises(PaymentReadAuthorizationError):
        service().get(prop, payment, actor=actor(human, wrong_prop, "payments.read"))
    with pytest.raises(PaymentReadNotFoundError):
        service().get(wrong_prop, payment, actor=actor(human, wrong_prop, "payments.read"))
    with pytest.raises(PaymentReadNotFoundError):
        service().get(prop, uuid4(), actor=actor(human, prop, "payments.read"))
    with pytest.raises(PaymentReadAuthorizationError):
        service().list(prop, actor=actor(uuid4(), prop, "payments.read"))
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    with pytest.raises(PaymentReadAuthorizationError):
        service().get(prop, payment, actor=actor(human, prop, "payments.read"))
    with pytest.raises(PaymentReadAuthorizationError):
        service().list(prop, actor=actor(human, prop, "payments.read"))


def test_payment_read_snapshot_stays_coherent_across_concurrent_refund_without_guard_writes(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, payment = source(migrated_database_url)
    with psycopg.connect(runtime_database_url()) as reader:
        reader.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        original = reader.execute(_DETAIL, (prop, payment)).fetchone()
        assert original is not None and position(original[0])["available_usd_cents"] == 10000
        with psycopg.connect(migrated_database_url) as writer:
            refund(writer, human, customer, payment=payment, amount=3000)
        assert reader.execute(_DETAIL, (prop, payment)).fetchone() == original
    fresh = service().get(prop, payment, actor=actor(human, prop, "payments.read"))
    assert position(fresh)["available_usd_cents"] == 7000
    assert header(fresh)["status"] == "RECEIVED"
    with psycopg.connect(migrated_database_url) as connection:
        before = connection.execute(
            "SELECT revision FROM app.payment_serialization_guards WHERE payment_id=%s", (payment,)
        ).fetchone()
        service().get(prop, payment, actor=actor(human, prop, "payments.read"))
        service().list(
            prop, filters=PaymentFilters(customer), actor=actor(human, prop, "payments.read")
        )
        assert (
            connection.execute(
                "SELECT revision FROM app.payment_serialization_guards WHERE payment_id=%s",
                (payment,),
            ).fetchone()
            == before
        )
