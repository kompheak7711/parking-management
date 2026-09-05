"""Credit recognition/reversal persistence slice on isolated synthetic PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from payment_test_support import seed_method, seed_payment
from property_rental.credit import (
    CreditAuthorizationError,
    CreditIdempotencyKeyReused,
    CreditNotFoundError,
    CreditUnavailableError,
    CustomerCreditService,
    RecognizeCreditCommand,
    ReverseCreditCommand,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.late_payment import DecisionOutcome, FinalizeLatePaymentDecisionCommand
from property_rental.payment_allocation import PaymentAllocationService, PostAllocationsCommand
from property_rental.receipt import ReceiptService
from test_invoice_migration import financial_database_url, runtime_database_url
from test_late_payment_migration import late_payment_actor, setup_invoice
from test_late_payment_migration import service as late_service
from test_migrations import _temporary_migration_database
from test_payment_allocation_migration import source as source_with_invoices
from test_payment_migration import fx_payment, reverse
from test_reservation_migration import (
    create_reservation,
    migrated_database_url,  # noqa: F401
    setup_reservation_sources,
)


def service() -> CustomerCreditService:
    return CustomerCreditService(runtime_database_url(), financial_database_url())


def actor(identity: UUID, prop: UUID, *caps: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(identity), frozenset(CapabilityGrant(cap, frozenset({str(prop)})) for cap in caps)
    )


def source(url: str, amount: int = 10000) -> tuple[UUID, UUID, UUID, UUID]:
    with psycopg.connect(url) as connection:
        human, prop, _, customer = setup_reservation_sources(connection)
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=amount
        )
    return human, prop, customer, payment


def recognize(prop: UUID, payment: UUID, human: UUID, amount: int = 8000) -> dict[str, object]:
    return service().recognize(
        prop,
        payment,
        RecognizeCreditCommand(
            uuid4(), amount, "Payer consent evidence", "Retain identified excess"
        ),
        actor=actor(human, prop, "credits.recognize"),
    )


def credit_id(result: dict[str, object]) -> UUID:
    credit = result["credit"]
    assert isinstance(credit, dict)
    return UUID(str(credit["id"]))


def test_credit_explicit_recognition_replay_source_receipt_and_audit(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, payment = source(migrated_database_url)
    staff = actor(human, prop, "credits.recognize", "credits.read", "receipts.read")
    request = RecognizeCreditCommand(
        uuid4(), 8000, "Payer consent evidence", "Retain identified excess"
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.customer_credits WHERE source_payment_id=%s", (payment,)
        ).fetchone() == (0,)
        original = connection.execute(
            "SELECT to_jsonb(p) FROM app.payments p WHERE id=%s", (payment,)
        ).fetchone()
        receipt = connection.execute(
            "SELECT to_jsonb(r) FROM app.receipts r WHERE payment_id=%s", (payment,)
        ).fetchone()
        assert original is not None and receipt is not None
    result = service().recognize(prop, payment, request, actor=staff)
    assert service().recognize(prop, payment, request, actor=staff) == result
    assert service().get(prop, credit_id(result), actor=staff) == result
    credit = result["credit"]
    assert isinstance(credit, dict)
    assert credit["customer_id"] == str(customer)
    assert credit["source_payment_id"] == str(payment)
    assert credit["recognized_usd_cents"] == result["available_usd_cents"] == 8000
    assert credit["customer_authorization_reference"] == "Payer consent evidence"
    assert credit["authorization_reference"] == "credits.recognize"
    assert credit["recognized_by"] == str(human)
    with psycopg.connect(migrated_database_url) as connection:
        assert (
            connection.execute(
                "SELECT to_jsonb(p) FROM app.payments p WHERE id=%s", (payment,)
            ).fetchone()
            == original
        )
        assert (
            connection.execute(
                "SELECT to_jsonb(r) FROM app.receipts r WHERE payment_id=%s", (payment,)
            ).fetchone()
            == receipt
        )
        assert connection.execute(
            "SELECT app.payment_available_value(%s)", (payment,)
        ).fetchone() == (2000,)
        assert connection.execute(
            "SELECT action,actor_id,property_id,customer_id,authorization_reference,"
            "resulting_state->>'customer_authorization_reference' FROM app.audit_events "
            "WHERE entity_id=%s AND action='credit.recognized'",
            (credit_id(result),),
        ).fetchall() == [
            (
                "credit.recognized",
                human,
                prop,
                customer,
                "credits.recognize",
                "Payer consent evidence",
            )
        ]
        assert connection.execute(
            "SELECT count(*) FROM app.customer_credits WHERE source_payment_id=%s", (payment,)
        ).fetchone() == (1,)
    display = ReceiptService(runtime_database_url(), financial_database_url()).for_payment(
        prop, payment, actor=staff
    )
    assert display["payment"] == {
        **{
            key: original[0][key]
            for key in (
                "id",
                "payment_number",
                "property_id",
                "payer_customer_id",
                "payment_date",
                "status",
                "received_currency",
                "received_amount_minor",
                "usd_accounting_value_cents",
            )
        },
        "payment_method": "Synthetic cash method",
    }
    assert display["financial_position"] == {
        "payment_id": str(payment),
        "payer_customer_id": str(customer),
        "property_id": str(prop),
        "status": "RECEIVED",
        "original_usd_cents": 10000,
        "allocated_usd_cents": 0,
        "deposit_directed_usd_cents": 0,
        "available_usd_cents": 2000,
        "allocation_condition": "UNALLOCATED",
    }
    with pytest.raises(CreditIdempotencyKeyReused):
        service().recognize(
            prop,
            payment,
            RecognizeCreditCommand(
                request.idempotency_key, 8001, "Payer consent evidence", "Retain identified excess"
            ),
            actor=staff,
        )


def test_credit_recognition_bounds_and_atomic_failure(migrated_database_url: str) -> None:  # noqa: F811
    human, prop, _, payment = source(migrated_database_url)
    recognize(prop, payment, human, 8000)
    with pytest.raises(CreditUnavailableError):
        recognize(prop, payment, human, 2001)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT sum(recognized_usd_cents) FROM app.customer_credits WHERE source_payment_id=%s",
            (payment,),
        ).fetchone() == (8000,)
        assert connection.execute(
            "SELECT count(*) FROM app.credit_commands WHERE request->>'payment_id'=%s",
            (str(payment),),
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE action='credit.recognized' "
            "AND resulting_state->>'source_payment_id'=%s",
            (str(payment),),
        ).fetchone() == (1,)


def test_credit_reversal_preserves_original_and_releases_source_once(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    result = recognize(prop, payment, human)
    identity = credit_id(result)
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error), connection.transaction():
            reverse(connection, payment, human)
    request = ReverseCreditCommand(uuid4(), "Consent recorded in error")
    reversal_actor = actor(human, prop, "credits.reverse")
    after = service().reverse(prop, identity, request, actor=reversal_actor)
    assert service().reverse(prop, identity, request, actor=reversal_actor) == after
    assert after["available_usd_cents"] == 0 and after["credit"] == result["credit"]
    reversal = after["recognition_reversal"]
    assert isinstance(reversal, dict)
    assert reversal["authorization_reference"] == "credits.reverse"
    assert reversal["actor_id"] == str(human) and reversal["customer_credit_id"] == str(identity)
    with pytest.raises(CreditUnavailableError):
        service().reverse(
            prop,
            identity,
            ReverseCreditCommand(uuid4(), "Duplicate reversal"),
            actor=reversal_actor,
        )
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT app.payment_available_value(%s)", (payment,)
        ).fetchone() == (10000,)
        assert connection.execute(
            "SELECT count(*) FROM app.customer_credit_reversals WHERE customer_credit_id=%s",
            (identity,),
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE action='credit.reversed' AND entity_id=%s",
            (identity,),
        ).fetchone() == (1,)
        reverse(connection, payment, human)
        assert connection.execute(
            "SELECT status FROM app.payments WHERE id=%s", (payment,)
        ).fetchone() == ("REVERSED",)
    historical = service().get(prop, identity, actor=actor(human, prop, "credits.read"))
    assert historical["credit"] == result["credit"]


def test_credit_cannot_be_automatic_while_applicable_invoices_outstanding(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, _ = source_with_invoices(migrated_database_url, amount=200000)
    with pytest.raises(CreditUnavailableError):
        recognize(prop, payment, human, 1)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.customer_credits WHERE source_payment_id=%s", (payment,)
        ).fetchone() == (0,)


def test_credit_khr_source_facts_preserved_without_khr_balance(migrated_database_url: str) -> None:  # noqa: F811
    with psycopg.connect(migrated_database_url) as connection:
        payment = fx_payment(connection)
        row = connection.execute(
            "SELECT confirmed_by,property_id,to_jsonb(p) FROM app.payments p WHERE id=%s",
            (payment,),
        ).fetchone()
        assert row is not None
    human, prop = UUID(str(row[0])), UUID(str(row[1]))
    result = recognize(prop, payment, human, 101)
    assert result["source_payment"] == row[2]
    assert result["available_usd_cents"] == 101 and "available_khr" not in result
    fx = result["exchange_rate"]
    assert isinstance(fx, dict)
    assert fx["id"] == row[2]["exchange_rate_record_id"]
    assert fx["system_rate_khr_per_usd"] == 4101
    assert row[2]["received_amount_minor"] == 4143 and row[2]["usd_accounting_value_cents"] == 101


@pytest.mark.parametrize("reference", ["4062.123456", "10000000000.000001"])
@pytest.mark.parametrize("channel", [False, True])
def test_credit_fractional_fx_and_nested_trace_remain_exact_in_responses(
    migrated_database_url: str,  # noqa: F811
    reference: str,
    channel: bool,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, customer = setup_reservation_sources(connection)
        method = seed_method(connection, human)
        fx, payment = uuid4(), uuid4()
        at = datetime.now(UTC) - timedelta(seconds=2)
        channel_reference = f"Exact-channel/{fx}" if channel else None
        connection.execute(
            "INSERT INTO app.exchange_rate_records("
            "id,reference_rate_khr_per_usd,markup_basis_points,system_rate_khr_per_usd,"
            "rate_source,source_reference,applicable_at,calculation_trace,"
            "channel_actual_currency,channel_actual_rate_khr_per_usd,"
            "channel_transaction_reference,channel_confirmed_at) "
            "VALUES(%s,%s::numeric,50,ceil(%s::numeric*1.005),'ABA_AUTOMATIC',"
            "'Exact synthetic FX',%s,"
            '\'{"ratio":0.1234567890123456789,"values":[10000000000.000001,1]}\','
            "%s,%s,%s,%s)",
            (
                fx,
                reference,
                reference,
                at,
                "KHR" if channel else None,
                Decimal(reference) if channel else None,
                channel_reference,
                at if channel else None,
            ),
        )
        connection.execute(
            "INSERT INTO app.payments(id,payment_number,property_id,payer_customer_id,"
            "payment_scope_kind,payment_date,payment_method_id,received_currency,"
            "received_amount_minor,usd_accounting_value_cents,exchange_rate_record_id,"
            "confirmed_at,confirmed_by,authorization_reference,channel_transaction_reference) "
            "SELECT %s,%s,%s,%s,'NORMAL_CUSTOMER',"
            "(clock_timestamp() AT TIME ZONE 'Asia/Phnom_Penh')::date,%s,'KHR',"
            "ceil(101*COALESCE(channel_actual_rate_khr_per_usd,system_rate_khr_per_usd)*0.01),"
            "101,id,clock_timestamp(),%s,'payments.record',%s "
            "FROM app.exchange_rate_records WHERE id=%s",
            (payment, f"Exact-{payment}", prop, customer, method, human, channel_reference, fx),
        )
        original = connection.execute(
            "SELECT row_to_json(rate)::text,row_to_json(payment)::text,row_to_json(receipt)::text "
            "FROM app.exchange_rate_records rate JOIN app.payments payment "
            "ON payment.exchange_rate_record_id=rate.id "
            "JOIN app.receipts receipt ON receipt.payment_id=payment.id WHERE payment.id=%s",
            (payment,),
        ).fetchone()
    assert original is not None
    staff = actor(human, prop, "credits.recognize", "credits.read", "credits.reverse")
    request = RecognizeCreditCommand(uuid4(), 101, "Payer consent", "Retain exact excess")
    result = service().recognize(prop, payment, request, actor=staff)
    identity = credit_id(result)
    assert service().recognize(prop, payment, request, actor=staff) == result
    assert service().get(prop, identity, actor=staff) == result
    evidence = result["exchange_rate"]
    assert isinstance(evidence, dict)
    assert evidence["reference_rate_khr_per_usd"] == reference
    assert evidence["channel_actual_rate_khr_per_usd"] == (reference if channel else None)
    assert evidence["calculation_trace"] == {
        "ratio": "0.1234567890123456789",
        "values": ["10000000000.000001", 1],
    }
    assert type(result["available_usd_cents"]) is int
    assert type(evidence["system_rate_khr_per_usd"]) is int
    reversal = ReverseCreditCommand(uuid4(), "Payer revoked consent")
    reversed_result = service().reverse(prop, identity, reversal, actor=staff)
    assert reversed_result["exchange_rate"] == evidence
    assert service().reverse(prop, identity, reversal, actor=staff) == reversed_result
    assert service().get(prop, identity, actor=staff) == reversed_result
    with psycopg.connect(migrated_database_url) as connection:
        assert (
            connection.execute(
                "SELECT row_to_json(rate)::text,row_to_json(payment)::text,"
                "row_to_json(receipt)::text "
                "FROM app.exchange_rate_records rate JOIN app.payments payment "
                "ON payment.exchange_rate_record_id=rate.id "
                "JOIN app.receipts receipt ON receipt.payment_id=payment.id WHERE payment.id=%s",
                (payment,),
            ).fetchone()
            == original
        )


@pytest.mark.parametrize(
    "table", ["customer_credits", "customer_credit_reversals", "credit_commands"]
)
def test_credit_history_immutable_and_runtime_has_no_table_writes(
    migrated_database_url: str,  # noqa: F811
    table: str,
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    identity = credit_id(recognize(prop, payment, human))
    service().reverse(
        prop,
        identity,
        ReverseCreditCommand(uuid4(), "Wrong consent"),
        actor=actor(human, prop, "credits.reverse"),
    )
    with psycopg.connect(migrated_database_url) as connection:
        for statement in (
            f"DELETE FROM app.{table}",
            f"UPDATE app.{table} SET "
            + ("action=action" if table == "credit_commands" else "id=id"),
            f"TRUNCATE app.{table}",
        ):
            with pytest.raises(psycopg.Error), connection.transaction():
                connection.execute(statement)
        assert connection.execute(
            "SELECT has_table_privilege('prm_runtime',%s,'INSERT'),"
            "has_table_privilege('prm_financial',%s,'INSERT'),"
            "has_table_privilege('prm_runtime',%s,'UPDATE')",
            (f"app.{table}",) * 3,
        ).fetchone() == (False, False, False)


def test_credit_database_source_customer_authorization_and_time_constraints(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, _prop, customer, payment = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        _, _, _, wrong_customer = setup_reservation_sources(connection)
        for customer_id, consent, at in (
            (wrong_customer, "Consent", datetime.now(UTC)),
            (customer, "", datetime.now(UTC)),
            (customer, "Consent", datetime.now(UTC) - timedelta(days=1)),
        ):
            with pytest.raises(psycopg.Error), connection.transaction():
                connection.execute(
                    "INSERT INTO app.customer_credits "
                    "VALUES(%s,%s,%s,100,%s,%s,%s,'Retain excess','credits.recognize')",
                    (uuid4(), customer_id, payment, consent, at, human),
                )
        assert connection.execute(
            "SELECT count(*) FROM app.customer_credits WHERE source_payment_id=%s", (payment,)
        ).fetchone() == (0,)


def test_credit_concurrent_recognition_never_overspends(migrated_database_url: str) -> None:  # noqa: F811
    human, prop, _, payment = source(migrated_database_url)
    barrier = Barrier(2)

    def worker() -> str:
        barrier.wait()
        try:
            recognize(prop, payment, human, 7000)
            return "posted"
        except CreditUnavailableError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert sorted(results) == ["posted", "rejected"]
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT app.payment_available_value(%s)", (payment,)
        ).fetchone() == (3000,)
        assert connection.execute(
            "SELECT sum(recognized_usd_cents) FROM app.customer_credits WHERE source_payment_id=%s",
            (payment,),
        ).fetchone() == (7000,)


def test_credit_scope_and_fresh_actor_checks(migrated_database_url: str) -> None:  # noqa: F811
    human, prop, _, payment = source(migrated_database_url)
    identity = credit_id(recognize(prop, payment, human))
    with pytest.raises(CreditNotFoundError):
        service().get(prop, uuid4(), actor=actor(human, prop, "credits.read"))
    with pytest.raises(CreditAuthorizationError):
        service().get(prop, identity, actor=actor(human, uuid4(), "credits.read"))
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    with pytest.raises(CreditAuthorizationError):
        service().get(prop, identity, actor=actor(human, prop, "credits.read"))


@pytest.mark.parametrize("isolation", ["repeatable read", "serializable"])
def test_credit_excess_rejects_snapshot_isolation_before_any_event(
    migrated_database_url: str,  # noqa: F811
    isolation: str,
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    key = uuid4()
    with psycopg.connect(financial_database_url()) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL " + isolation)
        with pytest.raises(psycopg.errors.SerializationFailure):
            connection.execute(
                "SELECT app.recognize_customer_credit(%s,%s,%s,%s,100,'Consent','Retain excess')",
                (prop, payment, human, key),
            )
        connection.rollback()
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.customer_credits WHERE source_payment_id=%s", (payment,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.credit_commands WHERE idempotency_key=%s", (key,)
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    "table",
    [
        "invoices",
        "invoice_lines",
        "invoice_adjustments",
        "invoice_adjustment_reversals",
        "invoice_void_events",
        "late_payment_charges",
        "late_payment_charge_corrections",
        "late_payment_decisions",
        "payment_allocations",
        "payment_allocation_reversals",
    ],
)
def test_credit_obligation_set_lock_rejects_competing_writer_without_waiting(
    migrated_database_url: str,  # noqa: F811
    table: str,
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    key = uuid4()
    request = RecognizeCreditCommand(key, 8000, "Consent", "Retain excess")
    staff = actor(human, prop, "credits.recognize")
    with psycopg.connect(migrated_database_url) as writer:
        writer.execute(f"LOCK TABLE app.{table} IN ROW EXCLUSIVE MODE")
        with pytest.raises(CreditUnavailableError) as failure:
            service().recognize(prop, payment, request, actor=staff)
        assert isinstance(failure.value.__cause__, psycopg.errors.LockNotAvailable)
        # Rejection is the NOWAIT boundary, not the three-second timeout.
        assert "could not obtain lock on relation" in str(failure.value.__cause__)
    result = service().recognize(prop, payment, request, actor=staff)
    assert result["available_usd_cents"] == 8000
    assert service().recognize(prop, payment, request, actor=staff) == result
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.credit_commands WHERE idempotency_key=%s", (key,)
        ).fetchone() == (1,)


def test_credit_true_excess_after_full_allocation_preserves_both_consumers(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, invoices = source_with_invoices(migrated_database_url, 200000)
    allocation_service = PaymentAllocationService(runtime_database_url(), financial_database_url())
    staff = actor(human, prop, "payments.allocate")
    proposal = allocation_service.proposal(prop, payment, actor=staff)
    result = allocation_service.post(
        prop,
        payment,
        PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
        actor=staff,
    )
    assert result["available_usd_cents"] == 40000
    credit = recognize(prop, payment, human, 40000)
    assert credit["available_usd_cents"] == 40000
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT app.payment_disposition_summary(%s),app.payment_available_value(%s)",
            (payment, payment),
        ).fetchone() == (
            {
                "allocation_usd_cents": 160000,
                "deposit_usd_cents": 0,
                "credit_usd_cents": 40000,
                "refund_usd_cents": 0,
            },
            0,
        )
        assert connection.execute(
            "SELECT count(*) FROM app.invoices WHERE id=ANY(%s) AND status='PAID'", (invoices,)
        ).fetchone() == (2,)


@pytest.mark.parametrize("overlap", [False, True])
def test_credit_historical_budget_preserves_nonoverlapping_deposit_history(
    migrated_database_url: str,  # noqa: F811
    overlap: bool,
) -> None:
    human, prop, customer, payment = source(migrated_database_url, 10000 if overlap else 20000)
    result = recognize(prop, payment, human, 10000)
    identity = credit_id(result)
    service().reverse(
        prop,
        identity,
        ReverseCreditCommand(uuid4(), "Wrong consent"),
        actor=actor(human, prop, "credits.reverse"),
    )
    with psycopg.connect(migrated_database_url) as connection:
        _, _, unit, _ = setup_reservation_sources(connection)
        row = connection.execute(
            "SELECT credit.recognized_at,reversal.occurred_at FROM app.customer_credits credit "
            "JOIN app.customer_credit_reversals reversal ON reversal.customer_credit_id=credit.id "
            "WHERE credit.id=%s",
            (identity,),
        ).fetchone()
        assert row is not None
        recognized_at, reversed_at = row
    between = recognized_at + (reversed_at - recognized_at) / 2
    assert recognized_at < between < reversed_at

    def receipt() -> None:
        with psycopg.connect(migrated_database_url) as connection:
            create_reservation(
                connection,
                actor_id=human,
                property_id=prop,
                unit_id=unit,
                customer_id=customer,
                accepted_usd_cents=10000,
                existing_payment_id=payment,
                accepted_at=between,
                received_at=between,
            )

    if overlap:
        with pytest.raises(psycopg.errors.CheckViolation, match="Payment historical availability"):
            receipt()
    else:
        receipt()
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT app.payment_credit_value_at(%s,%s),app.payment_credit_value_at(%s,%s)",
            (payment, between, payment, reversed_at),
        ).fetchone() == (10000, 0)
        assert connection.execute(
            "SELECT app.payment_available_value(%s)",
            (payment,),
        ).fetchone() == (10000,)
        assert connection.execute(
            "SELECT count(*) FROM app.deposit_receipts WHERE payment_id=%s",
            (payment,),
        ).fetchone() == (0 if overlap else 1,)


def test_credit_transaction_rollback_removes_event_receipt_and_audit(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    key = uuid4()
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(ValueError, match="Synthetic cancellation"), connection.transaction():
            row = connection.execute(
                "SELECT app.recognize_customer_credit(%s,%s,%s,%s,100,'Consent','Retain excess')",
                (prop, payment, human, key),
            ).fetchone()
            assert row is not None
            identity = credit_id(row[0])
            assert connection.execute(
                "SELECT count(*) FROM app.credit_commands WHERE idempotency_key=%s",
                (key,),
            ).fetchone() == (1,)
            assert connection.execute(
                "SELECT count(*) FROM app.audit_events WHERE entity_id=%s",
                (identity,),
            ).fetchone() == (1,)
            raise ValueError("Synthetic cancellation")
        assert connection.execute(
            "SELECT count(*) FROM app.customer_credits WHERE source_payment_id=%s",
            (payment,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.credit_commands WHERE idempotency_key=%s",
            (key,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE entity_id=%s",
            (identity,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT app.payment_available_value(%s)",
            (payment,),
        ).fetchone() == (10000,)


def test_credit_forward_upgrade_preserves_existing_payment_receipt_and_no_auto_credit() -> None:
    with _temporary_migration_database("prm_credit_history") as url:
        config = Config("alembic.ini")
        command.upgrade(config, "20260906_40")
        human, prop, _, payment = source(url)
        with psycopg.connect(url) as connection:
            original = connection.execute(
                "SELECT to_jsonb(payment),to_jsonb(receipt) FROM app.payments payment "
                "JOIN app.receipts receipt ON receipt.payment_id=payment.id WHERE payment.id=%s",
                (payment,),
            ).fetchone()
            assert original is not None
        command.upgrade(config, "head")
        with psycopg.connect(url) as connection:
            assert (
                connection.execute(
                    "SELECT to_jsonb(payment),to_jsonb(receipt) FROM app.payments payment "
                    "JOIN app.receipts receipt ON receipt.payment_id=payment.id "
                    "WHERE payment.id=%s",
                    (payment,),
                ).fetchone()
                == original
            )
            assert connection.execute("SELECT count(*) FROM app.customer_credits").fetchone() == (
                0,
            )
            result = connection.execute(
                "SELECT app.recognize_customer_credit(%s,%s,%s,%s,100,'Consent','Retain excess')",
                (prop, payment, human, uuid4()),
            ).fetchone()
            assert result is not None and result[0]["available_usd_cents"] == 100


def test_credit_true_excess_requires_separate_charge_as_well_as_invoice_settled(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, invoice, _ = setup_invoice(connection, period_start=date(2026, 5, 1))
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=customer,
            amount=100000,
        )
    late_service().finalize_decision(
        prop,
        invoice,
        FinalizeLatePaymentDecisionCommand(
            uuid4(), DecisionOutcome.CONFIRMED_DEFAULT, 8000, "Confirmed separate charge"
        ),
        actor=late_payment_actor(human, prop),
    )
    allocation_service = PaymentAllocationService(runtime_database_url(), financial_database_url())
    staff = actor(human, prop, "payments.allocate")
    proposal = allocation_service.proposal(prop, payment, actor=staff)
    paid = allocation_service.post(
        prop,
        payment,
        PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
        actor=staff,
    )
    assert paid["available_usd_cents"] == 20000
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT charge.id,invoice.status FROM app.late_payment_charges charge "
            "JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id "
            "WHERE invoice.id=%s",
            (invoice,),
        ).fetchone()
        assert row is not None and row[1] == "PAID"
    with pytest.raises(CreditUnavailableError):
        recognize(prop, payment, human, 1)
    allocation_service.post(
        prop,
        payment,
        PostAllocationsCommand(
            uuid4(),
            {
                "mode": "DIRECT_CHARGE",
                "late_payment_charge_id": str(row[0]),
                "amount_usd_cents": 8000,
            },
        ),
        actor=staff,
    )
    assert recognize(prop, payment, human, 12000)["available_usd_cents"] == 12000
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT app.payment_available_value(%s)",
            (payment,),
        ).fetchone() == (0,)


@pytest.mark.parametrize("isolation", ["read committed", "repeatable read", "serializable"])
@pytest.mark.parametrize("winner_kind", ["credit", "deposit"])
def test_credit_and_deposit_share_payment_budget_in_every_supported_isolation(
    migrated_database_url: str,  # noqa: F811
    isolation: str,
    winner_kind: str,
) -> None:
    human, prop, customer, payment = source(migrated_database_url, 1000)
    with psycopg.connect(migrated_database_url) as connection:
        _, _, unit, _ = setup_reservation_sources(connection)
        _, reservation = create_reservation(
            connection,
            actor_id=human,
            property_id=prop,
            unit_id=unit,
            customer_id=customer,
        )
    with psycopg.connect(migrated_database_url) as stale:
        stale.execute("SET TRANSACTION ISOLATION LEVEL " + isolation)
        stale.execute("SET LOCAL statement_timeout='5000ms'")
        stale.execute("SELECT app.payment_disposition_summary(%s)", (payment,))
        if winner_kind == "credit":
            recognize(prop, payment, human, 1000)
        else:
            with psycopg.connect(migrated_database_url) as winner:
                winner.execute(
                    "INSERT INTO app.deposit_receipts(id,deposit_id,payment_id,amount_usd_cents,"
                    "occurred_at,actor_id) VALUES(%s,%s,%s,1000,clock_timestamp(),%s)",
                    (uuid4(), reservation["deposit_id"], payment, human),
                )
        with pytest.raises(psycopg.Error) as failure:
            if winner_kind == "credit":
                stale.execute(
                    "INSERT INTO app.deposit_receipts(id,deposit_id,payment_id,amount_usd_cents,"
                    "occurred_at,actor_id) VALUES(%s,%s,%s,1000,clock_timestamp(),%s)",
                    (uuid4(), reservation["deposit_id"], payment, human),
                )
            else:
                stale.execute(
                    "SELECT app.recognize_customer_credit"
                    "(%s,%s,%s,%s,1000,'Consent','Retain excess')",
                    (prop, payment, human, uuid4()),
                )
        assert failure.value.sqlstate == ("23514" if isolation == "read committed" else "40001")
        stale.rollback()
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT app.payment_disposition_summary(%s),app.payment_available_value(%s)",
            (payment, payment),
        ).fetchone() == (
            {
                "allocation_usd_cents": 0,
                "deposit_usd_cents": 1000 if winner_kind == "deposit" else 0,
                "credit_usd_cents": 1000 if winner_kind == "credit" else 0,
                "refund_usd_cents": 0,
            },
            0,
        )
