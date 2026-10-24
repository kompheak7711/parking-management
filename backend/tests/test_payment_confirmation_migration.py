"""USD confirmation, exact replay, original evidence and forward-only PostgreSQL bridge."""

import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import Literal, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from psycopg.types.json import Jsonb

from payment_test_support import database_instant, seed_method, seed_payment
from property_rental.payment_confirmation import (
    ConfirmUsdPaymentCommand,
    PaymentConfirmationAuthorizationError,
    PaymentConfirmationConflictError,
    PaymentConfirmationInvalidError,
    PaymentConfirmationKeyReused,
    PaymentConfirmationNotFoundError,
    PaymentConfirmationService,
)
from property_rental.payment_read import PaymentReadService
from test_credit_migration import actor
from test_invoice_migration import financial_database_url, runtime_database_url
from test_lease_migration import create_draft
from test_migrations import _temporary_migration_database
from test_payment_migration import reverse
from test_reservation_migration import (  # noqa: F401
    migrated_database_url,
    setup_reservation_sources,
)

PHNOM_PENH = ZoneInfo("Asia/Phnom_Penh")


def service() -> PaymentConfirmationService:
    return PaymentConfirmationService(financial_database_url())


def source(url: str) -> tuple[UUID, UUID, UUID, ConfirmUsdPaymentCommand]:
    with psycopg.connect(url) as connection:
        human, prop, unit, customer = setup_reservation_sources(connection)
        method = seed_method(connection, human)
        at = database_instant(connection) - timedelta(seconds=1)
    return (
        human,
        prop,
        unit,
        ConfirmUsdPaymentCommand(
            uuid4(),
            customer,
            method,
            12345,
            at,
            "Synthetic verified USD receipt",
            payer_intent_memo="Payer supplied reference",
            channel_transaction_reference="Synthetic channel ref",
        ),
    )


def payment_id(result: dict[str, object]) -> UUID:
    return UUID(str(cast(dict[str, object], result["payment"])["id"]))


@pytest.mark.parametrize("amount", [1, 12345, 9_000_000_000_000_000])
def test_confirmation_records_usd_received_time_unique_receipt_audit_and_no_implicit_money_moves(
    migrated_database_url: str,  # noqa: F811
    amount: int,
) -> None:
    human, prop, _, request = source(migrated_database_url)
    request = replace(
        request, received_at=datetime(2026, 5, 1, 17, 30, tzinfo=UTC), received_amount_minor=amount
    )
    result = service().confirm_usd(prop, request, actor=actor(human, prop, "payments.record"))
    payment = cast(dict[str, object], result["payment"])
    identity = payment_id(result)
    # DL-071 answer 10 (V1-059 part B): RCP, the 2-digit Phnom Penh year of the confirmation
    # and a running number; the Receipt has the same number.
    confirmed_year = (
        datetime.fromisoformat(str(payment["confirmed_at"])).astimezone(PHNOM_PENH).strftime("%y")
    )
    assert re.fullmatch(rf"RCP{confirmed_year}\d{{4,}}", str(payment["payment_number"]))
    assert payment["received_currency"] == "USD"
    assert payment["received_amount_minor"] == payment["usd_accounting_value_cents"] == amount
    assert payment["status"] == "RECEIVED" and payment["exchange_rate_record_id"] is None
    assert payment["payment_date"] == "2026-05-02"
    assert result["received_at"] == "2026-05-01T17:30:00+00:00"
    assert datetime.fromisoformat(str(payment["confirmed_at"])) > request.received_at
    assert (
        payment["confirmed_by"] == str(human)
        and payment["authorization_reference"] == "payments.record"
    )
    assert payment["payer_customer_id"] == str(request.payer_customer_id)
    assert payment["channel_transaction_reference"] == request.channel_transaction_reference
    assert payment["payer_intent_memo"] == request.payer_intent_memo
    assert result["evidence_reference"] == request.evidence_reference
    receipt = cast(dict[str, object], result["receipt"])
    assert (
        receipt["payment_id"] == str(identity)
        and receipt["receipt_number"] == payment["payment_number"]
    )
    with psycopg.connect(migrated_database_url) as connection:
        saved = connection.execute(
            "SELECT request,response,recorded_at FROM app.payment_confirmation_commands "
            "WHERE payment_id=%s",
            (identity,),
        ).fetchone()
        assert saved is not None and saved[0] == request.intent() and saved[1] == result
        assert saved[2] == datetime.fromisoformat(str(payment["confirmed_at"]))
        assert connection.execute(
            "SELECT count(*) FROM app.receipts WHERE payment_id=%s", (identity,)
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE entity_id IN (%s,%s)",
            (identity, receipt["id"]),
        ).fetchone() == (2,)
        assert connection.execute(
            "SELECT count(*) FROM app.payment_allocations WHERE payment_id=%s", (identity,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.customer_credits WHERE source_payment_id=%s", (identity,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.deposit_receipts WHERE payment_id=%s", (identity,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.invoices WHERE customer_id=%s", (request.payer_customer_id,)
        ).fetchone() == (0,)


def test_confirmation_exact_replay_preserves_original_response_after_method_retirement_and_reversal(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, request = source(migrated_database_url)
    authorized = actor(human, prop, "payments.record")
    result = service().confirm_usd(prop, request, actor=authorized)
    identity = payment_id(result)
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.payment_methods SET display_name='Retired synthetic method',"
            "accepted=false WHERE id=%s",
            (request.payment_method_id,),
        )
        reverse(connection, identity, human)
    assert service().confirm_usd(prop, request, actor=authorized) == result
    read = PaymentReadService(runtime_database_url()).get(
        prop, identity, actor=actor(human, prop, "payments.read")
    )
    assert cast(dict[str, object], read["payment"])["status"] == "REVERSED"
    assert (
        cast(dict[str, object], read["payment"])["payment_method_name_snapshot"]
        == cast(dict[str, object], result["payment"])["payment_method_name_snapshot"]
    )
    with pytest.raises(PaymentConfirmationKeyReused):
        service().confirm_usd(prop, replace(request, received_amount_minor=12346), actor=authorized)
    with pytest.raises(PaymentConfirmationConflictError):
        service().confirm_usd(prop, replace(request, idempotency_key=uuid4()), actor=authorized)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.payments WHERE payer_customer_id=%s",
            (request.payer_customer_id,),
        ).fetchone() == (1,)


@pytest.mark.parametrize("different_payload", [False, True])
def test_confirmation_concurrent_same_key_has_one_payment_receipt_and_exact_conflict(
    migrated_database_url: str,  # noqa: F811
    different_payload: bool,
) -> None:
    human, prop, _, request = source(migrated_database_url)
    gate = Barrier(2)

    def confirm(amount: int) -> dict[str, object] | str:
        gate.wait(timeout=5)
        try:
            return service().confirm_usd(
                prop,
                replace(request, received_amount_minor=amount),
                actor=actor(human, prop, "payments.record"),
            )
        except PaymentConfirmationKeyReused:
            return "key_conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(confirm, 12345)
        second = pool.submit(confirm, 12346 if different_payload else 12345)
        results = [first.result(timeout=10), second.result(timeout=10)]
    if different_payload:
        assert results.count("key_conflict") == 1
    else:
        assert results[0] == results[1] and isinstance(results[0], dict)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.payment_confirmation_commands "
            "WHERE actor_id=%s AND idempotency_key=%s",
            (human, request.idempotency_key),
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM app.payments p JOIN app.receipts r ON r.payment_id=p.id "
            "WHERE p.payer_customer_id=%s",
            (request.payer_customer_id,),
        ).fetchone() == (1,)


def test_confirmation_denies_missing_cross_property_and_disabled_actor_even_on_replay(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, request = source(migrated_database_url)
    authorized = actor(human, prop, "payments.record")
    with pytest.raises(PaymentConfirmationNotFoundError):
        service().confirm_usd(prop, replace(request, payer_customer_id=uuid4()), actor=authorized)
    missing = uuid4()
    with pytest.raises(PaymentConfirmationNotFoundError):
        service().confirm_usd(missing, request, actor=actor(human, missing, "payments.record"))
    result = service().confirm_usd(prop, request, actor=authorized)
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    with pytest.raises(PaymentConfirmationAuthorizationError):
        service().confirm_usd(prop, request, actor=authorized)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT response FROM app.payment_confirmation_commands WHERE payment_id=%s",
            (payment_id(result),),
        ).fetchone() == (result,)


@pytest.mark.parametrize("different_actor", [False, True])
def test_confirmation_distinct_keys_and_actor_scopes_are_independent_not_accidental_replay(
    migrated_database_url: str,  # noqa: F811
    different_actor: bool,
) -> None:
    human, prop, _, request = source(migrated_database_url)
    other, _, _, _ = source(migrated_database_url)
    first = service().confirm_usd(prop, request, actor=actor(human, prop, "payments.record"))
    second = service().confirm_usd(
        prop,
        request if different_actor else replace(request, idempotency_key=uuid4()),
        actor=actor(other if different_actor else human, prop, "payments.record"),
    )
    assert payment_id(first) != payment_id(second)
    assert first["receipt"] != second["receipt"]


@pytest.mark.parametrize(
    "scope,owned,allowed",
    [
        ("NORMAL_CUSTOMER", True, True),
        ("NORMAL_CUSTOMER", False, False),
        ("THIRD_PARTY_IDENTIFIED", False, True),
    ],
)
def test_confirmation_preserves_lease_intent_without_assigning_third_party_ownership(
    migrated_database_url: str,  # noqa: F811
    scope: Literal["NORMAL_CUSTOMER", "THIRD_PARTY_IDENTIFIED"],
    owned: bool,
    allowed: bool,
) -> None:
    human, prop, unit, request = source(migrated_database_url)
    _, _, _, third_party = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        lease = create_draft(
            connection, actor_id=human, unit_id=unit, primary_tenant_id=request.payer_customer_id
        )
    intended = replace(
        request,
        lease_id=lease,
        payment_scope_kind=scope,
        payer_customer_id=request.payer_customer_id if owned else third_party.payer_customer_id,
    )
    if allowed:
        result = service().confirm_usd(prop, intended, actor=actor(human, prop, "payments.record"))
        assert cast(dict[str, object], result["payment"])["payer_customer_id"] == str(
            intended.payer_customer_id
        )
    else:
        with pytest.raises(PaymentConfirmationConflictError):
            service().confirm_usd(prop, intended, actor=actor(human, prop, "payments.record"))
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT primary_tenant_id FROM app.leases WHERE id=%s", (lease,)
        ).fetchone() == (request.payer_customer_id,)
        assert connection.execute(
            "SELECT count(*) FROM app.payment_confirmation_commands WHERE actor_id=%s", (human,)
        ).fetchone() == (int(allowed),)


@pytest.mark.parametrize(
    "field,value",
    [
        ("received_currency", "KHR"),
        ("status", "RECEIVED"),
        ("usd_accounting_value_cents", 1),
        ("allocations", []),
        ("received_amount_minor", True),
        ("received_amount_minor", 1.5),
        ("received_amount_minor", 0),
        ("received_amount_minor", 9_000_000_000_000_001),
        ("received_at", "infinity"),
        ("received_at", "2026-05-01"),
        ("received_at", None),
        ("payer_customer_id", "not-a-uuid"),
        ("payment_method_id", None),
        ("evidence_reference", " leading"),
        ("evidence_reference", None),
        ("payment_scope_kind", None),
        ("payment_scope_kind", "THIRD_PARTY_IDENTIFIED"),
    ],
)
def test_confirmation_database_rejects_untrusted_shapes_and_rolls_back_every_event(
    migrated_database_url: str,  # noqa: F811
    field: str,
    value: object,
) -> None:
    human, prop, _, request = source(migrated_database_url)
    intent = request.intent()
    intent[field] = value
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.Error) as failure:
            connection.execute(
                "SELECT app.confirm_usd_payment(%s,%s,%s,%s)",
                (prop, human, request.idempotency_key, Jsonb(intent)),
            )
        assert failure.value.sqlstate in {"P5302", "23514"}
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.payments WHERE payer_customer_id=%s",
            (request.payer_customer_id,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.payment_confirmation_commands WHERE actor_id=%s", (human,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.receipts WHERE payer_customer_id=%s",
            (request.payer_customer_id,),
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    "field", ["evidence_reference", "payer_intent_memo", "channel_transaction_reference"]
)
def test_confirmation_raw_evidence_rejects_python_whitespace_without_financial_events(
    migrated_database_url: str,  # noqa: F811
    field: str,
) -> None:
    human, prop, _, request = source(migrated_database_url)
    # Enumerate the Python contract, including Unicode separators and C0 controls;
    # SQL validation must not depend on the database locale's definition of space.
    whitespace = [chr(code) for code in range(0x110000) if chr(code).isspace()]
    constructors: dict[str, Callable[[str], ConfirmUsdPaymentCommand]] = {
        "evidence_reference": lambda value: replace(request, evidence_reference=value),
        "payer_intent_memo": lambda value: replace(request, payer_intent_memo=value),
        "channel_transaction_reference": lambda value: replace(
            request, channel_transaction_reference=value
        ),
    }
    with psycopg.connect(financial_database_url()) as connection:
        for character in whitespace:
            for value in (character, character + "Evidence", "Evidence" + character):
                with pytest.raises(PaymentConfirmationInvalidError):
                    constructors[field](value)
                intent = request.intent()
                intent[field] = value
                with pytest.raises(psycopg.Error) as failure, connection.transaction():
                    connection.execute(
                        "SELECT app.confirm_usd_payment(%s,%s,%s,%s)",
                        (prop, human, request.idempotency_key, Jsonb(intent)),
                    )
                assert failure.value.sqlstate == "P5302", (field, repr(value))
    with psycopg.connect(migrated_database_url) as connection:
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
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE entity_type IN ('payment','receipt') "
            "AND actor_id=%s",
            (human,),
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    "field", ["evidence_reference", "payer_intent_memo", "channel_transaction_reference"]
)
def test_confirmation_raw_evidence_preserves_valid_interior_whitespace_and_nonspace_edges(
    migrated_database_url: str,  # noqa: F811
    field: str,
) -> None:
    human, prop, _, request = source(migrated_database_url)
    value = (
        "\u200bEvidence\t\n\u001c\u0085\u00a0\u1680\u2000\u2028\u202f\u205f\u3000unchanged\u200b"
    )
    assert value == value.strip()  # U+200B is not Python whitespace.
    constructors = {
        "evidence_reference": lambda: replace(request, evidence_reference=value),
        "payer_intent_memo": lambda: replace(request, payer_intent_memo=value),
        "channel_transaction_reference": lambda: replace(
            request, channel_transaction_reference=value
        ),
    }
    intent = constructors[field]().intent()
    with psycopg.connect(financial_database_url()) as connection:
        result = connection.execute(
            "SELECT app.confirm_usd_payment(%s,%s,%s,%s)",
            (prop, human, request.idempotency_key, Jsonb(intent)),
        ).fetchone()
        assert result is not None
    with psycopg.connect(migrated_database_url) as connection:
        saved = connection.execute(
            "SELECT request FROM app.payment_confirmation_commands WHERE idempotency_key=%s",
            (request.idempotency_key,),
        ).fetchone()
        assert saved == (intent,) and saved[0][field] == value


def test_confirmation_future_received_time_rejects_without_consuming_key(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, request = source(migrated_database_url)
    with pytest.raises(PaymentConfirmationInvalidError):
        service().confirm_usd(
            prop,
            replace(request, received_at=request.received_at + timedelta(days=1)),
            actor=actor(human, prop, "payments.record"),
        )
    assert payment_id(
        service().confirm_usd(prop, request, actor=actor(human, prop, "payments.record"))
    )


def test_confirmation_append_only_records_and_narrow_function_grants(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, request = source(migrated_database_url)
    result = service().confirm_usd(prop, request, actor=actor(human, prop, "payments.record"))
    with psycopg.connect(migrated_database_url) as connection:
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
            assert connection.execute(
                "SELECT has_table_privilege(%s,'app.payment_confirmation_commands',"
                "'INSERT,UPDATE,DELETE,TRUNCATE'), has_function_privilege(%s,"
                "'app.confirm_usd_payment(uuid,uuid,uuid,jsonb)','EXECUTE'), "
                "has_function_privilege(%s,'app.payment_confirmation_replay(uuid,uuid,uuid,jsonb)',"
                "'EXECUTE')",
                (role, role, role),
            ).fetchone() == (False, role == "prm_financial", False)
        for mutation in (
            "UPDATE app.payment_confirmation_commands SET request='{}'::jsonb",
            "DELETE FROM app.payment_confirmation_commands",
            "TRUNCATE app.payment_confirmation_commands",
        ):
            with pytest.raises(psycopg.Error) as failure, connection.transaction():
                connection.execute(mutation)
            assert failure.value.sqlstate == "55000"
        assert connection.execute(
            "SELECT response FROM app.payment_confirmation_commands WHERE payment_id=%s",
            (payment_id(result),),
        ).fetchone() == (result,)
    with psycopg.connect(runtime_database_url()) as connection:
        with pytest.raises(psycopg.Error) as failure:
            connection.execute(
                "SELECT app.confirm_usd_payment(%s,%s,%s,%s)",
                (prop, human, request.idempotency_key, Jsonb(request.intent())),
            )
        assert failure.value.sqlstate == "42501"


def test_confirmation_upgrade_preserves_revision41_history_without_received_backfill() -> None:
    with _temporary_migration_database("prm_payment_confirmation_history") as url:
        config = Config("alembic.ini")
        alembic_command.upgrade(config, "20260906_41")
        human, prop, _, request = source(url)
        with psycopg.connect(url) as connection:
            identity = seed_payment(
                connection,
                actor_id=human,
                property_id=prop,
                customer_id=request.payer_customer_id,
                amount=100,
            )
            original = connection.execute(
                "SELECT to_jsonb(p),to_jsonb(r) FROM app.payments p "
                "JOIN app.receipts r ON r.payment_id=p.id WHERE p.id=%s",
                (identity,),
            ).fetchone()
            assert original is not None
        alembic_command.upgrade(config, "head")
        with psycopg.connect(url) as connection:
            assert (
                connection.execute(
                    "SELECT to_jsonb(p),to_jsonb(r) FROM app.payments p "
                    "JOIN app.receipts r ON r.payment_id=p.id WHERE p.id=%s",
                    (identity,),
                ).fetchone()
                == original
            )
            assert connection.execute(
                "SELECT count(*) FROM app.payment_confirmation_commands"
            ).fetchone() == (0,)
            confirmed = connection.execute(
                "SELECT app.confirm_usd_payment(%s,%s,%s,%s)",
                (prop, human, request.idempotency_key, Jsonb(request.intent())),
            ).fetchone()
            assert confirmed is not None and confirmed[0]["payment"]["received_currency"] == "USD"
