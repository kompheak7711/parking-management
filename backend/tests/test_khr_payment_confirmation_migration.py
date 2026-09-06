"""Atomic incoming KHR/FX confirmation, original channel evidence and exact replay."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from psycopg.types.json import Jsonb

from property_rental.configuration_api import ExchangeRateSourceUnavailable
from property_rental.khr_payment_confirmation import (
    ConfirmKhrPaymentCommand,
    KhrChannelEvidence,
    KhrPaymentConfirmationService,
    ManualKhrReference,
)
from property_rental.payment_confirmation import (
    PaymentConfirmationAuthorizationError,
    PaymentConfirmationConflictError,
    PaymentConfirmationInvalidError,
    PaymentConfirmationKeyReused,
    PaymentConfirmationNotFoundError,
    PaymentConfirmationService,
    PaymentConfirmationUnavailableError,
)
from test_credit_migration import actor
from test_invoice_migration import financial_database_url, runtime_database_url
from test_khr_payment_confirmation import Provider, provider
from test_migrations import _temporary_migration_database
from test_payment_confirmation_migration import source as usd_source
from test_payment_migration import fx_payment, reverse
from test_reservation_migration import migrated_database_url  # noqa: F401


def source(url: str) -> tuple[UUID, UUID, ConfirmKhrPaymentCommand, Provider]:
    human, prop, _, usd = usd_source(url)
    request = ConfirmKhrPaymentCommand(
        usd.idempotency_key,
        usd.payer_customer_id,
        usd.payment_method_id,
        40871,
        1001,
        usd.received_at,
        "Verified synthetic incoming KHR receipt",
    )
    return human, prop, request, provider(usd.received_at)


def identity(result: dict[str, object], key: str = "payment") -> UUID:
    return UUID(str(cast(dict[str, object], result[key])["id"]))


def fx_count(url: str) -> int:
    with psycopg.connect(url) as connection:
        row = connection.execute("SELECT count(*) FROM app.exchange_rate_records").fetchone()
        assert row is not None
        return cast(int, row[0])


def assert_no_events(
    url: str, request: ConfirmKhrPaymentCommand, human: UUID, before_fx: int
) -> None:
    assert fx_count(url) == before_fx
    with psycopg.connect(url) as connection:
        for relation in ("payments", "receipts"):
            assert connection.execute(
                psycopg.sql.SQL("SELECT count(*) FROM app.{} WHERE payer_customer_id=%s").format(
                    psycopg.sql.Identifier(relation)
                ),
                (request.payer_customer_id,),
            ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.payment_confirmation_commands WHERE actor_id=%s", (human,)
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    "reference,usd,khr,system",
    [
        ("4062", 1, 41, 4083),
        ("4062", 1001, 40871, 4083),
        ("4000", 100, 4020, 4020),
        ("0.000001", 1, 1, 1),
        ("99999999999999.999999", 1, 1005000000000, 100500000000000),
        ("0.000001", 9000000000000000, 90000000000000, 1),
    ],
)
def test_khr_confirmation_automatic_rounding_and_atomic_original_facts(
    migrated_database_url: str,  # noqa: F811
    reference: str,
    usd: int,
    khr: int,
    system: int,
) -> None:
    human, prop, request, selected = source(migrated_database_url)
    request = replace(request, usd_amount_cents=usd, received_amount_minor=khr)
    selected.quote = replace(selected.quote, reference_rate_khr_per_usd=Decimal(reference))
    result = KhrPaymentConfirmationService(financial_database_url(), selected).confirm_khr(
        prop, request, actor=actor(human, prop, "payments.record")
    )
    payment, fx = (
        cast(dict[str, object], result["payment"]),
        cast(dict[str, object], result["exchange_rate_record"]),
    )
    assert payment["received_currency"] == "KHR" and payment["received_amount_minor"] == khr
    assert payment["usd_accounting_value_cents"] == usd and payment["status"] == "RECEIVED"
    assert payment["exchange_rate_record_id"] == fx["id"]
    assert Decimal(str(fx["reference_rate_khr_per_usd"])) == Decimal(reference)
    assert fx["markup_basis_points"] == 50 and fx["system_rate_khr_per_usd"] == system
    assert fx["rate_source"] == "ABA_AUTOMATIC" and fx["entered_by"] is None
    assert (
        fx["channel_actual_amount_minor"] is None and fx["channel_actual_usd_value_cents"] is None
    )
    assert datetime.fromisoformat(str(result["received_at"])) == request.received_at
    assert result["evidence_reference"] == request.evidence_reference
    trace = cast(dict[str, object], fx["calculation_trace"])
    assert trace["payable_khr"] == khr and trace["automatic_source_unavailable"] is False
    assert Decimal(str(trace["unrounded_payable_khr"])) == Decimal(usd) * system / 100
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.receipts WHERE payment_id=%s", (identity(result),)
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT request FROM app.payment_confirmation_commands WHERE payment_id=%s",
            (identity(result),),
        ).fetchone() == (request.intent(),)
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE entity_id IN (%s,%s,%s)",
            (
                identity(result),
                identity(result, "receipt"),
                identity(result, "exchange_rate_record"),
            ),
        ).fetchone() == (3,)
        for relation in ("payment_allocations", "deposit_receipts"):
            assert connection.execute(
                psycopg.sql.SQL("SELECT count(*) FROM app.{} WHERE payment_id=%s").format(
                    psycopg.sql.Identifier(relation)
                ),
                (identity(result),),
            ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.customer_credits WHERE source_payment_id=%s",
            (identity(result),),
        ).fetchone() == (0,)


@pytest.mark.parametrize("currency", ["USD", "KHR"])
@pytest.mark.parametrize("microsecond", [0, 1, 10, 1000, 10000, 35750, 100000, 999999])
def test_payment_confirmation_timestamp_precision_preserves_original_intent_and_replay(
    migrated_database_url: str,  # noqa: F811
    currency: str,
    microsecond: int,
) -> None:
    human, prop, _, usd = usd_source(migrated_database_url)
    at = (usd.received_at - timedelta(seconds=1)).replace(microsecond=microsecond)
    authorized = actor(human, prop, "payments.record")
    if currency == "USD":
        usd_request = replace(usd, received_at=at)
        usd_flow = PaymentConfirmationService(financial_database_url())
        result = usd_flow.confirm_usd(prop, usd_request, actor=authorized)
        replay = usd_flow.confirm_usd(prop, usd_request, actor=authorized)
        original_intent = usd_request.intent()
    else:
        khr_request = ConfirmKhrPaymentCommand(
            usd.idempotency_key,
            usd.payer_customer_id,
            usd.payment_method_id,
            40871,
            1001,
            at,
            "Synthetic precision evidence",
        )
        khr_flow = KhrPaymentConfirmationService(financial_database_url(), provider(at))
        result = khr_flow.confirm_khr(prop, khr_request, actor=authorized)
        replay = khr_flow.confirm_khr(prop, khr_request, actor=authorized)
        original_intent = khr_request.intent()
    received = result["received_at"]
    assert isinstance(received, str)
    instant = datetime.fromisoformat(received)
    # Fractional trailing zeroes are optional RFC3339 presentation, not lost precision.
    assert instant == at and instant.microsecond == microsecond
    assert instant.utcoffset() == timedelta(0) and instant.tzinfo == UTC
    assert replay == result
    with psycopg.connect(migrated_database_url) as connection:
        saved = connection.execute(
            "SELECT request,response FROM app.payment_confirmation_commands WHERE payment_id=%s",
            (identity(result),),
        ).fetchone()
        assert saved is not None and saved[0] == original_intent and saved[1] == result
        assert saved[0]["received_at"] == at.isoformat()
        assert connection.execute(
            "SELECT count(*) FROM app.payments WHERE payer_customer_id=%s",
            (usd.payer_customer_id,),
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM app.receipts WHERE payment_id=%s", (identity(result),)
        ).fetchone() == (1,)


def test_khr_confirmation_manual_requires_outage_permission_and_replays_after_recovery_and_reversal(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, request, selected = source(migrated_database_url)
    manual = ManualKhrReference(
        Decimal("4062"),
        "Verified manual ABA equivalent",
        request.received_at,
        "Approved source unavailable",
    )
    request = replace(request, manual_reference=manual)
    flow = KhrPaymentConfirmationService(financial_database_url(), selected)
    before = fx_count(migrated_database_url)
    authorized = actor(human, prop, "payments.record", "exchange_rates.manage")
    with pytest.raises(PaymentConfirmationAuthorizationError):
        flow.confirm_khr(prop, request, actor=actor(human, prop, "payments.record"))
    assert selected.calls == 0
    with pytest.raises(PaymentConfirmationConflictError):
        flow.confirm_khr(prop, request, actor=authorized)
    assert_no_events(migrated_database_url, request, human, before)
    selected.error = ExchangeRateSourceUnavailable()
    result = flow.confirm_khr(prop, request, actor=authorized)
    fx = cast(dict[str, object], result["exchange_rate_record"])
    assert fx["rate_source"] == "ABA_EQUIVALENT_MANUAL" and fx["entered_by"] == str(human)
    assert (
        cast(dict[str, object], fx["calculation_trace"])["fallback_reason"]
        == manual.fallback_reason
    )
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.payment_methods SET accepted=false,"
            "display_name='Retired synthetic method' WHERE id=%s",
            (request.payment_method_id,),
        )
        reverse(connection, identity(result), human)
    selected.error = AssertionError("Replay must never fetch a new rate")
    assert flow.confirm_khr(prop, request, actor=authorized) == result
    with pytest.raises(PaymentConfirmationKeyReused):
        flow.confirm_khr(
            prop,
            replace(request, manual_reference=replace(manual, fallback_reason="Changed intent")),
            actor=authorized,
        )
    assert fx_count(migrated_database_url) == before + 1


@pytest.mark.parametrize(
    "kind,khr,usd",
    [
        ("amount_only", 40871, 1001),
        ("half_up", 4020, 101),
        ("rate_only", 4105, 101),
        ("usd_only", 40871, 1001),
        ("all_actual", 4100, 101),
        ("currency_only", 40871, 1001),
    ],
)
def test_khr_confirmation_channel_supplied_facts_control_only_their_fields(
    migrated_database_url: str,  # noqa: F811
    kind: str,
    khr: int,
    usd: int,
) -> None:
    human, prop, request, selected = source(migrated_database_url)
    evidence = KhrChannelEvidence(
        "Original synthetic channel reference",
        request.received_at,
        actual_currency="KHR" if kind in {"all_actual", "currency_only"} else None,
        actual_amount_minor=khr if kind in {"amount_only", "half_up", "all_actual"} else None,
        actual_usd_value_cents=usd if kind in {"usd_only", "all_actual"} else None,
        actual_rate_khr_per_usd=Decimal("4000")
        if kind == "half_up"
        else Decimal("4064.123456")
        if kind in {"rate_only", "all_actual"}
        else None,
    )
    request = replace(
        request,
        received_amount_minor=khr,
        usd_amount_cents=usd,
        channel_evidence=evidence,
        channel_transaction_reference=evidence.transaction_reference,
    )
    result = KhrPaymentConfirmationService(financial_database_url(), selected).confirm_khr(
        prop, request, actor=actor(human, prop, "payments.record")
    )
    payment, fx = (
        cast(dict[str, object], result["payment"]),
        cast(dict[str, object], result["exchange_rate_record"]),
    )
    assert payment["received_amount_minor"] == khr and payment["usd_accounting_value_cents"] == usd
    assert fx["system_rate_khr_per_usd"] == 4083
    assert fx["channel_actual_amount_minor"] == evidence.actual_amount_minor
    assert fx["channel_actual_usd_value_cents"] == evidence.actual_usd_value_cents
    assert fx["channel_actual_currency"] == evidence.actual_currency
    assert fx["channel_transaction_reference"] == evidence.transaction_reference
    if evidence.actual_rate_khr_per_usd is None:
        assert fx["channel_actual_rate_khr_per_usd"] is None
    else:
        assert (
            Decimal(str(fx["channel_actual_rate_khr_per_usd"])) == evidence.actual_rate_khr_per_usd
        )


@pytest.mark.parametrize("different", [False, True])
def test_khr_confirmation_concurrent_exact_key_has_one_fx_payment_receipt(
    migrated_database_url: str,  # noqa: F811
    different: bool,
) -> None:
    human, prop, request, selected = source(migrated_database_url)
    gate = Barrier(2)
    before = fx_count(migrated_database_url)

    def confirm(changed: bool) -> dict[str, object] | str:
        gate.wait(timeout=5)
        supplied = (
            replace(request, evidence_reference="Different verified reference")
            if changed
            else request
        )
        try:
            return KhrPaymentConfirmationService(financial_database_url(), selected).confirm_khr(
                prop, supplied, actor=actor(human, prop, "payments.record")
            )
        except PaymentConfirmationKeyReused:
            return "key_conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(confirm, False), pool.submit(confirm, different)
        results = [first.result(timeout=10), second.result(timeout=10)]
    assert results.count("key_conflict") == (1 if different else 0)
    if not different:
        assert results[0] == results[1]
    assert selected.calls == 1 and fx_count(migrated_database_url) == before + 1
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.payments p JOIN app.receipts r ON r.payment_id=p.id "
            "WHERE p.payer_customer_id=%s",
            (request.payer_customer_id,),
        ).fetchone() == (1,)


def test_khr_confirmation_replay_shares_usd_key_namespace_and_checks_fresh_actor(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, request, selected = source(migrated_database_url)
    flow = KhrPaymentConfirmationService(financial_database_url(), selected)
    before = fx_count(migrated_database_url)
    with pytest.raises(PaymentConfirmationNotFoundError):
        flow.confirm_khr(
            prop,
            replace(request, payer_customer_id=uuid4()),
            actor=actor(human, prop, "payments.record"),
        )
    assert_no_events(migrated_database_url, request, human, before)
    result = flow.confirm_khr(prop, request, actor=actor(human, prop, "payments.record"))
    _, _, _, usd = usd_source(migrated_database_url)
    with pytest.raises(PaymentConfirmationKeyReused):
        PaymentConfirmationService(financial_database_url()).confirm_usd(
            prop,
            replace(usd, idempotency_key=request.idempotency_key),
            actor=actor(human, prop, "payments.record"),
        )
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    with pytest.raises(PaymentConfirmationAuthorizationError):
        flow.confirm_khr(prop, request, actor=actor(human, prop, "payments.record"))
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT request FROM app.payment_confirmation_commands WHERE payment_id=%s",
            (identity(result),),
        ).fetchone() == (request.intent(),)


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("request", "received_currency", "USD"),
        ("request", "received_amount_minor", True),
        ("request", "received_amount_minor", 1.5),
        ("request", "received_amount_minor", 40870),
        ("request", "usd_amount_cents", 1002),
        ("request", "usd_accounting_value_cents", 1),
        ("request", "status", "RECEIVED"),
        ("request", "received_at", "infinity"),
        ("request", "payment_scope_kind", None),
        ("request", "payer_customer_id", "bad"),
        ("request", "manual_reference", {}),
        ("request", "channel_evidence", {}),
        ("request", "evidence_reference", "\t"),
        ("request", "payer_intent_memo", "\u0085"),
        ("request", "channel_transaction_reference", "reference\u3000"),
        ("selection", "reference_rate_khr_per_usd", 4062),
        ("selection", "reference_rate_khr_per_usd", "0.000000"),
        ("selection", "reference_rate_khr_per_usd", "4062.0000001"),
        ("selection", "reference_rate_khr_per_usd", "NaN"),
        ("selection", "system_rate_khr_per_usd", 1),
        ("selection", "source_reference", "\n"),
        ("selection", "applicable_at", "infinity"),
        ("selection", "automatic_source_unavailable", True),
        ("selection", "rate_source", "OTHER_PROVIDER"),
        ("selection", "fallback_reason", "Unapproved fallback"),
    ],
)
def test_khr_confirmation_raw_json_denies_untrusted_envelopes_without_any_events(
    migrated_database_url: str,  # noqa: F811
    target: str,
    field: str,
    value: object,
) -> None:
    human, prop, request, selected = source(migrated_database_url)
    intent, selection = (
        request.intent(),
        KhrPaymentConfirmationService("unused", selected)._selection(None),
    )
    (intent if target == "request" else selection)[field] = value
    before = fx_count(migrated_database_url)
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.Error) as failure:
            connection.execute(
                "SELECT app.confirm_khr_payment(%s,%s,%s,%s,%s)",
                (prop, human, request.idempotency_key, Jsonb(intent), Jsonb(selection)),
            )
        assert failure.value.sqlstate in {"P5302", "P5305", "23514"}
    assert_no_events(migrated_database_url, request, human, before)


def test_khr_confirmation_source_failure_future_time_and_retired_method_roll_back_fx(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, request, selected = source(migrated_database_url)
    authorized = actor(human, prop, "payments.record")
    flow = KhrPaymentConfirmationService(financial_database_url(), selected)
    before = fx_count(migrated_database_url)
    selected.error = ExchangeRateSourceUnavailable()
    with pytest.raises(PaymentConfirmationUnavailableError):
        flow.confirm_khr(prop, request, actor=authorized)
    selected.error = None
    with pytest.raises(PaymentConfirmationInvalidError):
        flow.confirm_khr(
            prop,
            replace(request, received_at=request.received_at + timedelta(days=1)),
            actor=authorized,
        )
    original_quote = selected.quote
    selected.quote = replace(original_quote, applicable_at=request.received_at + timedelta(days=1))
    with pytest.raises(PaymentConfirmationInvalidError):
        flow.confirm_khr(prop, request, actor=authorized)
    selected.quote = original_quote
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.payment_methods SET accepted=false WHERE id=%s",
            (request.payment_method_id,),
        )
    with pytest.raises(PaymentConfirmationConflictError):
        flow.confirm_khr(prop, request, actor=authorized)
    assert_no_events(migrated_database_url, request, human, before)


def test_khr_confirmation_private_helpers_and_financial_only_commands(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, request, selected = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
            assert connection.execute(
                "SELECT has_function_privilege(%s,"
                "'app.khr_confirmation_text(jsonb,integer,boolean)','EXECUTE'), "
                "has_function_privilege(%s,'app.confirm_khr_payment(uuid,uuid,uuid,jsonb,jsonb)',"
                "'EXECUTE'), has_function_privilege(%s,"
                "'app.replay_khr_payment_confirmation(uuid,uuid,uuid,jsonb)','EXECUTE')",
                (role, role, role),
            ).fetchone() == (False, role == "prm_financial", role == "prm_financial")
    with psycopg.connect(runtime_database_url()) as connection:
        with pytest.raises(psycopg.Error) as failure:
            connection.execute(
                "SELECT app.confirm_khr_payment(%s,%s,%s,%s,%s)",
                (
                    prop,
                    human,
                    request.idempotency_key,
                    Jsonb(request.intent()),
                    Jsonb(KhrPaymentConfirmationService("unused", selected)._selection(None)),
                ),
            )
        assert failure.value.sqlstate == "42501"


def test_khr_confirmation_forward_upgrade_preserves_existing_payment_receipt_and_fx() -> None:
    with _temporary_migration_database("prm_khr_confirmation_history") as url:
        config = Config("alembic.ini")
        alembic_command.upgrade(config, "20260906_42")
        with psycopg.connect(url) as connection:
            payment = fx_payment(connection)
            original = connection.execute(
                "SELECT to_jsonb(p),to_jsonb(r),to_jsonb(fx) FROM app.payments p "
                "JOIN app.receipts r ON r.payment_id=p.id JOIN app.exchange_rate_records fx "
                "ON fx.id=p.exchange_rate_record_id WHERE p.id=%s",
                (payment,),
            ).fetchone()
            assert original is not None
        alembic_command.upgrade(config, "head")
        with psycopg.connect(url) as connection:
            assert (
                connection.execute(
                    "SELECT to_jsonb(p),to_jsonb(r),to_jsonb(fx) FROM app.payments p "
                    "JOIN app.receipts r ON r.payment_id=p.id JOIN app.exchange_rate_records fx "
                    "ON fx.id=p.exchange_rate_record_id WHERE p.id=%s",
                    (payment,),
                ).fetchone()
                == original
            )
            assert connection.execute(
                "SELECT count(*) FROM app.payment_confirmation_commands"
            ).fetchone() == (0,)
