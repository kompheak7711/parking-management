"""V1-048 Payment facts and reversals against real isolated PostgreSQL."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, Error
from psycopg.types.json import Jsonb

from payment_test_support import seed_method, seed_payment
from test_invoice_migration import financial_database_url, register_billing_service_principal
from test_lease_migration import create_draft
from test_reservation_lifecycle_migration import active_reservation, cancel
from test_reservation_migration import (
    create_reservation,
    migrated_database_url,  # noqa: F401
    setup_reservation_sources,
)


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[Connection[tuple[object, ...]]]:  # noqa: F811
    with psycopg.connect(migrated_database_url) as database:
        yield database
        database.rollback()


def reverse(connection: Connection[tuple[object, ...]], payment_id: UUID, actor_id: UUID) -> UUID:
    reversal = uuid4()
    connection.execute(
        "INSERT INTO app.payment_reversals(id,payment_id,reason,occurred_at,actor_id,"
        "authorization_reference) VALUES (%s,%s,'Duplicate bank receipt',clock_timestamp(),"
        "%s,'payments.reverse')",
        (reversal, payment_id, actor_id),
    )
    return reversal


def test_usd_payment_snapshots_reversal_and_audit(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor, prop, _, customer = setup_reservation_sources(connection)
    payment = seed_payment(
        connection, actor_id=actor, property_id=prop, customer_id=customer, amount=12345
    )
    assert connection.execute(
        "SELECT received_amount_minor,usd_accounting_value_cents,status,"
        "payment_method_code_snapshot=method.code,payment_method_name_snapshot=method.display_name "
        "FROM app.payments AS payment JOIN app.payment_methods AS method "
        "ON method.id=payment.payment_method_id WHERE payment.id=%s",
        (payment,),
    ).fetchone() == (12345, 12345, "RECEIVED", True, True)
    reversal = reverse(connection, payment, actor)
    assert connection.execute(
        "SELECT status FROM app.payments WHERE id=%s", (payment,)
    ).fetchone() == ("REVERSED",)
    assert connection.execute(
        "SELECT action,previous_state->>'status',resulting_state->>'status' "
        "FROM app.audit_events WHERE correlation_id=%s",
        (reversal,),
    ).fetchone() == ("payment.reversed", "RECEIVED", "REVERSED")
    assert connection.execute(
        "SELECT count(*) FROM app.invoices WHERE customer_id=%s", (customer,)
    ).fetchone() == (0,)


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE app.payments SET received_amount_minor=2 WHERE id=%s",
        "UPDATE app.payments SET status='REVERSED' WHERE id=%s",
        "DELETE FROM app.payments WHERE id=%s",
        "UPDATE app.payment_reversals SET reason='replaced' WHERE payment_id=%s",
        "DELETE FROM app.payment_reversals WHERE payment_id=%s",
    ],
)
def test_history_is_immutable(connection: Connection[tuple[object, ...]], mutation: str) -> None:
    actor, prop, _, customer = setup_reservation_sources(connection)
    payment = seed_payment(
        connection, actor_id=actor, property_id=prop, customer_id=customer, amount=100
    )
    if "payment_reversals" in mutation:
        reverse(connection, payment, actor)
    with pytest.raises(Error) as failure:
        connection.execute(mutation, (payment,))
    assert failure.value.sqlstate == "55000"


def test_duplicate_reversal_and_number_are_rejected(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor, prop, _, customer = setup_reservation_sources(connection)
    payment = seed_payment(
        connection, actor_id=actor, property_id=prop, customer_id=customer, amount=100
    )
    with pytest.raises(Error), connection.transaction():
        seed_payment(
            connection,
            actor_id=actor,
            property_id=prop,
            customer_id=customer,
            amount=100,
            payment_id=payment,
        )
    reverse(connection, payment, actor)
    with pytest.raises(Error):
        reverse(connection, payment, actor)


@pytest.mark.parametrize("role", ["prm_runtime", "prm_financial", "prm_bootstrap"])
def test_application_roles_cannot_write_money(
    connection: Connection[tuple[object, ...]], role: str
) -> None:
    assert connection.execute(
        "SELECT has_table_privilege(%s,'app.payments','INSERT'),"
        "has_table_privilege(%s,'app.payments','UPDATE'),"
        "has_table_privilege(%s,'app.payment_reversals','INSERT'),"
        "has_table_privilege(%s,'app.payments','TRUNCATE')",
        (role, role, role, role),
    ).fetchone() == (False, False, False, False)
    assert connection.execute(
        "SELECT convalidated FROM pg_constraint WHERE conname='deposit_receipts_payment_fk'"
    ).fetchone() == (True,)


def test_inactive_human_cannot_confirm_or_reverse(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor, prop, _, customer = setup_reservation_sources(connection)
    payment = seed_payment(
        connection, actor_id=actor, property_id=prop, customer_id=customer, amount=100
    )
    connection.execute(
        "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (actor,)
    )
    with pytest.raises(Error), connection.transaction():
        reverse(connection, payment, actor)
    with pytest.raises(Error), connection.transaction():
        seed_payment(connection, actor_id=actor, property_id=prop, customer_id=customer, amount=100)


def test_service_actor_cannot_confirm_payment(connection: Connection[tuple[object, ...]]) -> None:
    actor, prop, _, customer = setup_reservation_sources(connection)
    service = register_billing_service_principal(connection, property_id=prop, created_by=actor)
    seed_method(connection, actor)
    with pytest.raises(Error) as failure:
        seed_payment(
            connection, actor_id=service, property_id=prop, customer_id=customer, amount=100
        )
    assert failure.value.sqlstate == "55000"


def test_method_snapshot_survives_rename_and_retirement(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor, prop, _, customer = setup_reservation_sources(connection)
    payment = seed_payment(
        connection, actor_id=actor, property_id=prop, customer_id=customer, amount=100
    )
    before = connection.execute(
        "SELECT payment_method_id,payment_method_code_snapshot,"
        "payment_method_name_snapshot FROM app.payments WHERE id=%s",
        (payment,),
    ).fetchone()
    assert before is not None
    connection.execute(
        "UPDATE app.payment_methods SET display_name='Retired synthetic method',"
        "accepted=false,updated_by=%s WHERE id=%s",
        (actor, before[0]),
    )
    assert (
        connection.execute(
            "SELECT payment_method_id,payment_method_code_snapshot,"
            "payment_method_name_snapshot FROM app.payments WHERE id=%s",
            (payment,),
        ).fetchone()
        == before
    )


@pytest.mark.parametrize(
    "scope,owns,allowed",
    [
        ("NORMAL_CUSTOMER", True, True),
        ("NORMAL_CUSTOMER", False, False),
        ("THIRD_PARTY_IDENTIFIED", False, True),
    ],
)
def test_lease_intent_and_third_party_ownership(
    connection: Connection[tuple[object, ...]], scope: str, owns: bool, allowed: bool
) -> None:
    actor, prop, unit, customer = setup_reservation_sources(connection)
    _, _, _, other = setup_reservation_sources(connection)
    lease = create_draft(connection, actor_id=actor, unit_id=unit, primary_tenant_id=customer)

    def confirm() -> UUID:
        return seed_payment(
            connection,
            actor_id=actor,
            property_id=prop,
            customer_id=customer if owns else other,
            amount=100,
            lease_id=lease,
            scope=scope,
        )

    if allowed:
        confirm()
    else:
        with pytest.raises(Error) as failure:
            confirm()
        assert failure.value.sqlstate == "23514"


def test_financial_login_reads_but_cannot_insert_payment(migrated_database_url: str) -> None:  # noqa: F811
    with psycopg.connect(migrated_database_url) as setup:
        actor, prop, _, customer = setup_reservation_sources(setup)
        payment = seed_payment(
            setup, actor_id=actor, property_id=prop, customer_id=customer, amount=100
        )
        setup.commit()
    with psycopg.connect(financial_database_url()) as financial:
        assert financial.execute(
            "SELECT status FROM app.payments WHERE id=%s", (payment,)
        ).fetchone() == ("RECEIVED",)
        assert financial.execute(
            "SELECT app.payment_disposition_summary(%s)->>'deposit_usd_cents'", (payment,)
        ).fetchone() == ("0",)
        with pytest.raises(Error) as failure:
            financial.execute(
                "INSERT INTO app.payment_reversals(id,payment_id,reason,occurred_at,"
                "actor_id,authorization_reference) VALUES (%s,%s,'Synthetic',clock_timestamp(),"
                "%s,'payments.reverse')",
                (uuid4(), payment, actor),
            )
        assert failure.value.sqlstate == "42501"


def fx_payment(
    connection: Connection[tuple[object, ...]],
    *,
    manual: bool = False,
    evidence: bool = True,
    amount: int = 4143,
    usd: int = 101,
    channel: bool = False,
    future: bool = False,
    channel_amount_only: bool = False,
    channel_usd_only: bool = False,
) -> UUID:
    actor, prop, _, customer = setup_reservation_sources(connection)
    method = seed_method(connection, actor)
    fx, payment = uuid4(), uuid4()
    at = (
        datetime.now(UTC) + timedelta(days=1)
        if future
        else datetime.now(UTC) - timedelta(seconds=2)
    )
    trace: dict[str, object] = {"rounding": "CEILING_WHOLE_KHR"}
    if evidence:
        trace.update(
            {"automatic_source_unavailable": True, "fallback_reason": "Synthetic provider outage"}
        )
    connection.execute(
        """INSERT INTO app.exchange_rate_records(id,reference_rate_khr_per_usd,
        markup_basis_points,system_rate_khr_per_usd,rate_source,source_reference,
        applicable_at,entered_by,calculation_trace,channel_actual_currency,
        channel_actual_amount_minor,channel_actual_usd_value_cents,
        channel_transaction_reference,channel_confirmed_at)
        VALUES (%s,4080,50,4101,%s,'Synthetic FX source',%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            fx,
            "ABA_EQUIVALENT_MANUAL" if manual else "ABA_AUTOMATIC",
            at,
            actor if manual else None,
            Jsonb(trace),
            "KHR" if channel else None,
            amount if channel and not channel_usd_only else None,
            usd if channel and not channel_amount_only else None,
            "SYNTHETIC-BANK-REFERENCE" if channel else None,
            at if channel else None,
        ),
    )
    connection.execute(
        """INSERT INTO app.payments(id,payment_number,property_id,payer_customer_id,
        payment_scope_kind,payment_date,payment_method_id,received_currency,
        received_amount_minor,usd_accounting_value_cents,exchange_rate_record_id,
        confirmed_at,confirmed_by,authorization_reference,channel_transaction_reference)
        VALUES (%s,%s,%s,%s,'NORMAL_CUSTOMER',
        (clock_timestamp() AT TIME ZONE 'Asia/Phnom_Penh')::date,%s,'KHR',%s,%s,%s,
        clock_timestamp(),%s,'payments.record',%s)""",
        (
            payment,
            f"TEST-{payment}",
            prop,
            customer,
            method,
            amount,
            usd,
            fx,
            actor,
            "SYNTHETIC-BANK-REFERENCE" if channel else None,
        ),
    )
    return payment


@pytest.mark.parametrize(
    "manual,channel,amount", [(False, False, 4143), (True, False, 4143), (False, True, 4100)]
)
def test_confirmed_fx_preserves_system_and_channel_evidence(
    connection: Connection[tuple[object, ...]],
    manual: bool,
    channel: bool,
    amount: int,
) -> None:
    payment = fx_payment(connection, manual=manual, channel=channel, amount=amount)
    assert connection.execute(
        "SELECT payment.received_amount_minor,payment.usd_accounting_value_cents,"
        "fx.system_rate_khr_per_usd FROM app.payments payment JOIN app.exchange_rate_records fx "
        "ON fx.id=payment.exchange_rate_record_id WHERE payment.id=%s",
        (payment,),
    ).fetchone() == (amount, 101, 4101)


@pytest.mark.parametrize("case", ["rounding", "manual_provenance", "future"])
def test_invalid_fx_is_rejected(connection: Connection[tuple[object, ...]], case: str) -> None:
    with pytest.raises(Error) as failure:
        fx_payment(
            connection,
            amount=4142 if case == "rounding" else 4143,
            manual=case == "manual_provenance",
            evidence=case != "manual_provenance",
            future=case == "future",
        )
    assert failure.value.sqlstate == "23514"


@pytest.mark.parametrize(
    "amount_only,amount,usd,valid",
    [
        (True, 4101, 100, True),
        (True, 4101, 999, False),
        (False, 4143, 101, True),
        (False, 4142, 101, False),
    ],
)
def test_partial_channel_evidence_does_not_allow_arbitrary_missing_amounts(
    connection: Connection[tuple[object, ...]],
    amount_only: bool,
    amount: int,
    usd: int,
    valid: bool,
) -> None:
    def confirm() -> UUID:
        return fx_payment(
            connection,
            channel=True,
            channel_amount_only=amount_only,
            channel_usd_only=not amount_only,
            amount=amount,
            usd=usd,
        )

    if valid:
        confirm()
    else:
        with pytest.raises(Error) as failure:
            confirm()
        assert failure.value.sqlstate == "23514"


def test_payment_reversal_waits_for_deposit_unwind(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor, prop, unit, customer = setup_reservation_sources(connection)
    _, ids = create_reservation(
        connection, actor_id=actor, property_id=prop, unit_id=unit, customer_id=customer
    )
    connection.commit()
    with pytest.raises(Error), connection.transaction():
        reverse(connection, ids["payment_id"], actor)
    connection.execute(
        "INSERT INTO app.deposit_receipt_reversals(id,deposit_receipt_id,reason,occurred_at,"
        "actor_id,authorization_reference) VALUES (%s,%s,'Synthetic unwind',clock_timestamp(),"
        "%s,'deposits.correct')",
        (uuid4(), ids["receipt_id"], actor),
    )
    reverse(connection, ids["payment_id"], actor)


def test_concurrent_reversals_have_one_winner(migrated_database_url: str) -> None:  # noqa: F811
    with psycopg.connect(migrated_database_url) as setup:
        actor, prop, _, customer = setup_reservation_sources(setup)
        payment = seed_payment(
            setup, actor_id=actor, property_id=prop, customer_id=customer, amount=100
        )
        setup.commit()
    barrier = Barrier(2)

    def attempt() -> str:
        with psycopg.connect(migrated_database_url) as candidate:
            candidate.execute("SET statement_timeout='10s'")
            barrier.wait(timeout=10)
            try:
                reverse(candidate, payment, actor)
                candidate.commit()
                return "accepted"
            except Error as error:
                candidate.rollback()
                return str(error.sqlstate)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results) == ["23514", "accepted"]


def test_concurrent_deposit_funding_cannot_double_spend(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor, prop, unit, customer = setup_reservation_sources(setup)
        _, first = create_reservation(
            setup, actor_id=actor, property_id=prop, unit_id=unit, customer_id=customer
        )
        _, _, other_unit, _ = setup_reservation_sources(setup)
        _, second = create_reservation(
            setup, actor_id=actor, property_id=prop, unit_id=other_unit, customer_id=customer
        )
        payment = seed_payment(
            setup, actor_id=actor, property_id=prop, customer_id=customer, amount=1000
        )
        setup.commit()
    barrier = Barrier(2)

    def fund(deposit: UUID) -> str:
        with psycopg.connect(migrated_database_url) as candidate:
            candidate.execute("SET statement_timeout='10s'")
            barrier.wait(timeout=10)
            try:
                candidate.execute(
                    "INSERT INTO app.deposit_receipts(id,deposit_id,payment_id,amount_usd_cents,"
                    "occurred_at,actor_id) VALUES (%s,%s,%s,1000,clock_timestamp(),%s)",
                    (uuid4(), deposit, payment, actor),
                )
                candidate.commit()
                return "accepted"
            except Error as error:
                candidate.rollback()
                return str(error.sqlstate)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(fund, [first["deposit_id"], second["deposit_id"]]))
    assert sorted(results) == ["23514", "accepted"]
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT sum(amount_usd_cents) FROM app.deposit_receipts WHERE payment_id=%s", (payment,)
        ).fetchone() == (1000,)


def test_refund_correction_allows_receipt_and_payment_unwind_without_erasing_history(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor, prop, _, _, reservation = active_reservation(connection)
    connection.commit()
    refund = uuid4()
    result = cancel(
        connection,
        actor_id=actor,
        property_id=prop,
        reservation_id=reservation,
        idempotency_key=uuid4(),
        event_id=uuid4(),
        outcome_id=refund,
        responsibility="PROPERTY",
        property_could_provide_unit=False,
        coordination_reference="SYNTHETIC-CORRECTION",
    )
    connection.commit()
    receipt = connection.execute(
        "SELECT id,payment_id,amount_usd_cents FROM app.deposit_receipts WHERE deposit_id=%s",
        (result[9],),
    ).fetchone()
    assert receipt is not None
    with pytest.raises(Error), connection.transaction():
        connection.execute(
            "SELECT app.reverse_deposit_receipt_v2(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                prop,
                actor,
                uuid4(),
                "f" * 64,
                uuid4(),
                receipt[0],
                "Synthetic unwind",
                "deposits.correct",
            ),
        )
    connection.execute(
        "INSERT INTO app.refund_corrections(id,refund_id,correction_kind,"
        "source_balance_effect_usd_cents,previous_net_refund_usd_cents,"
        "resulting_net_refund_usd_cents,reason,evidence_reference,occurred_at,actor_id,"
        "authorization_reference) VALUES (%s,%s,'VALUE_CORRECTION',%s,%s,0,"
        "'Bank proved funds never left','SYNTHETIC-REFUND-FAILURE',clock_timestamp(),"
        "%s,'reservation_deposits.correct')",
        (uuid4(), refund, receipt[2], receipt[2], actor),
    )
    connection.execute(
        "SELECT app.reverse_deposit_receipt_v2(%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            prop,
            actor,
            uuid4(),
            "a" * 64,
            uuid4(),
            receipt[0],
            "Synthetic unwind",
            "deposits.correct",
        ),
    )
    reverse(connection, UUID(str(receipt[1])), actor)
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert connection.execute(
        "SELECT count(*) FROM app.refunds WHERE id=%s", (refund,)
    ).fetchone() == (1,)
    assert connection.execute(
        "SELECT count(*) FROM app.refund_corrections WHERE refund_id=%s", (refund,)
    ).fetchone() == (1,)
