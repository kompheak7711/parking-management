"""Private USD-only Refund source/correction substrate and immutable source evidence."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, sql

from property_rental.credit import CreditUnavailableError, ReverseCreditCommand
from test_credit_application_migration import designated
from test_credit_application_migration import source as application_source
from test_credit_migration import actor, credit_id, recognize, service, source
from test_payment_migration import fx_payment, reverse
from test_reservation_migration import (
    create_reservation,
    migrated_database_url,  # noqa: F401
    setup_reservation_sources,
)


def insert_event(
    connection: Connection[tuple[object, ...]], table: str, values: dict[str, object]
) -> UUID:
    connection.execute(
        sql.SQL("INSERT INTO app.{} ({}) VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(",").join(map(sql.Identifier, values)),
            sql.SQL(",").join(sql.Placeholder() for _ in values),
        ),
        list(values.values()),
    )
    return UUID(str(values["id"]))


def refund(
    connection: Connection[tuple[object, ...]],
    human: UUID,
    customer: UUID,
    *,
    payment: UUID | None = None,
    credit: UUID | None = None,
    amount: int = 8000,
    overrides: dict[str, object] | None = None,
) -> UUID:
    identity = uuid4()
    return insert_event(
        connection,
        "refunds",
        {
            "id": identity,
            "refund_number": f"REF-{identity}",
            "recipient_customer_id": customer,
            "source_payment_id": payment,
            "source_customer_credit_id": credit,
            "usd_accounting_value_cents": amount,
            "refund_currency": "USD",
            "refund_amount_minor": amount,
            "reason": "Return eligible excess",
            "processed_at": datetime.now(UTC),
            "processed_by": human,
            "authorization_reference": "refunds.create",
            **(overrides or {}),
        },
    )


def correct(
    connection: Connection[tuple[object, ...]],
    human: UUID,
    identity: UUID,
    amount: int = 4000,
    *,
    reverses: UUID | None = None,
    overrides: dict[str, object] | None = None,
) -> UUID:
    row = connection.execute(
        "SELECT app.refund_net_value_at(%s,'infinity')", (identity,)
    ).fetchone()
    assert row is not None
    net = int(str(row[0]))
    now = datetime.now(UTC)
    return insert_event(
        connection,
        "refund_corrections",
        {
            "id": uuid4(),
            "refund_id": identity,
            "correction_kind": "VALUE_CORRECTION" if reverses is None else "CORRECTION_REVERSAL",
            "reverses_correction_id": reverses,
            "source_balance_effect_usd_cents": amount,
            "source_balance_effect_original_minor": amount,
            "previous_net_refund_usd_cents": net,
            "resulting_net_refund_usd_cents": net - amount,
            "reason": "Correct demonstrated returned value",
            "evidence_reference": "Synthetic return evidence",
            "occurred_at": now,
            "actor_id": human,
            "authorization_reference": "refunds.correct"
            if reverses is None
            else "refunds.corrections.reverse",
            "verified_return_amount_minor": amount if reverses is None else None,
            "verified_return_currency": "USD" if reverses is None else None,
            "verified_returned_at": now if reverses is None else None,
            "return_method_reference": "Synthetic bank reference" if reverses is None else None,
            **(overrides or {}),
        },
    )


@pytest.mark.parametrize("credit_source", [False, True])
def test_usd_refund_source_history_audit_and_no_double_consumption(
    migrated_database_url: str,  # noqa: F811
    credit_source: bool,
) -> None:
    human, prop, customer, payment = source(migrated_database_url)
    credit = credit_id(recognize(prop, payment, human)) if credit_source else None
    with psycopg.connect(migrated_database_url) as connection:
        original = connection.execute(
            "SELECT to_jsonb(p) FROM app.payments p WHERE id=%s", (payment,)
        ).fetchone()
        receipt = connection.execute(
            "SELECT to_jsonb(r) FROM app.receipts r WHERE payment_id=%s", (payment,)
        ).fetchone()
        identity = refund(
            connection, human, customer, payment=None if credit_source else payment, credit=credit
        )
        snapshot = connection.execute(
            "SELECT to_jsonb(r) FROM app.refunds r WHERE id=%s", (identity,)
        ).fetchone()
        assert connection.execute(
            "SELECT app.payment_available_value(%s)", (payment,)
        ).fetchone() == (2000,)
        if credit is not None:
            assert connection.execute(
                "SELECT app.credit_available_value(%s)", (credit,)
            ).fetchone() == (0,)
        correction = correct(connection, human, identity)
        reversal = correct(connection, human, identity, -4000, reverses=correction)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        times = connection.execute(
            "SELECT r.processed_at,c.occurred_at,x.occurred_at FROM app.refunds r "
            "JOIN app.refund_corrections c ON c.refund_id=r.id JOIN app.refund_corrections x "
            "ON x.reverses_correction_id=c.id WHERE r.id=%s",
            (identity,),
        ).fetchone()
        assert times is not None
        for at, expected in zip(times, (8000, 4000, 8000), strict=True):
            assert connection.execute(
                "SELECT app.refund_net_value_at(%s,%s)", (identity, at)
            ).fetchone() == (expected,)
        assert (
            connection.execute(
                "SELECT to_jsonb(r) FROM app.refunds r WHERE id=%s", (identity,)
            ).fetchone()
            == snapshot
        )
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
        audits = connection.execute(
            "SELECT action,actor_id,property_id,customer_id,correlation_id,"
            "business_date=(occurred_at AT TIME ZONE "
            "(SELECT timezone_name FROM app.properties WHERE id=%s))::date "
            "FROM app.audit_events WHERE entity_id=%s ORDER BY occurred_at,id",
            (prop, identity),
        ).fetchall()
        assert audits == [
            ("refund.created", human, prop, customer, identity, True),
            ("refund.value_corrected", human, prop, customer, correction, True),
            ("refund.correction_reversed", human, prop, customer, reversal, True),
        ]


@pytest.mark.parametrize(
    "changes",
    [
        {"usd_accounting_value_cents": 10001, "refund_amount_minor": 10001},
        {"usd_accounting_value_cents": 0, "refund_amount_minor": 0},
        {"refund_amount_minor": 7999},
        {"recipient_customer_id": UUID(int=0)},
        {"authorization_reference": "credits.recognize"},
        {"processed_at": datetime(2020, 1, 1, tzinfo=UTC)},
        {"processed_at": datetime(2099, 1, 1, tzinfo=UTC)},
        {"refund_currency": "KHR"},
        {"reason": "x" * 1001},
    ],
)
def test_usd_refund_invalid_source_amount_or_evidence_is_atomic(
    migrated_database_url: str,  # noqa: F811
    changes: dict[str, object],
) -> None:
    human, _, customer, payment = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error), connection.transaction():
            refund(connection, human, customer, payment=payment, overrides=changes)
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert connection.execute(
            "SELECT count(*) FROM app.refunds WHERE source_payment_id=%s", (payment,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events "
            "WHERE action='refund.created' AND customer_id=%s",
            (customer,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT app.payment_available_value(%s)", (payment,)
        ).fetchone() == (10000,)


@pytest.mark.parametrize(
    "changes",
    [
        {"verified_return_amount_minor": None},
        {"verified_return_currency": "KHR"},
        {"verified_return_amount_minor": 3999},
        {"source_balance_effect_original_minor": 3999},
        {"verified_returned_at": datetime(2020, 1, 1, tzinfo=UTC)},
        {"verified_returned_at": datetime(2099, 1, 1, tzinfo=UTC)},
        {"return_method_reference": " "},
        {"previous_net_refund_usd_cents": 7000},
        {"authorization_reference": "refunds.create"},
        {
            "source_balance_effect_usd_cents": 8001,
            "source_balance_effect_original_minor": 8001,
            "verified_return_amount_minor": 8001,
            "resulting_net_refund_usd_cents": -1,
        },
        {"evidence_reference": "x" * 501},
    ],
)
def test_usd_refund_correction_rejects_unverified_or_inconsistent_value(
    migrated_database_url: str,  # noqa: F811
    changes: dict[str, object],
) -> None:
    human, _, customer, payment = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        identity = refund(connection, human, customer, payment=payment)
        with pytest.raises(psycopg.Error), connection.transaction():
            correct(connection, human, identity, overrides=changes)
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert connection.execute(
            "SELECT app.refund_net_value_at(%s,'infinity')", (identity,)
        ).fetchone() == (8000,)
        assert connection.execute(
            "SELECT count(*) FROM app.refund_corrections WHERE refund_id=%s", (identity,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE entity_id=%s", (identity,)
        ).fetchone() == (1,)


def test_usd_refund_correction_reversal_cannot_reconsume_spent_source(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, payment = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        identity = refund(connection, human, customer, payment=payment)
        correction = correct(connection, human, identity)
    credit = credit_id(recognize(prop, payment, human, 6000))
    with psycopg.connect(migrated_database_url) as connection:
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="no longer available"),
            connection.transaction(),
        ):
            correct(connection, human, identity, -4000, reverses=correction)
    service().reverse(
        prop,
        credit,
        ReverseCreditCommand(uuid4(), "Correct consent"),
        actor=actor(human, prop, "credits.reverse"),
    )
    with psycopg.connect(migrated_database_url) as connection:
        correct(connection, human, identity, -4000, reverses=correction)
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            correct(connection, human, identity, -4000, reverses=correction)
        assert connection.execute(
            "SELECT app.payment_available_value(%s)", (payment,)
        ).fetchone() == (2000,)


def test_usd_credit_refund_return_cannot_be_reversed_after_application(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, credit, invoice, line, payment = application_source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT payer_customer_id FROM app.payments WHERE id=%s", (payment,)
        ).fetchone()
        assert row is not None
        identity = refund(connection, human, UUID(str(row[0])), credit=credit, amount=80000)
        correction = correct(connection, human, identity, 40000)
    service().apply(
        prop, credit, designated(invoice, line, 60000), actor=actor(human, prop, "credits.apply")
    )
    with psycopg.connect(migrated_database_url) as connection:
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="no longer available"),
            connection.transaction(),
        ):
            correct(connection, human, identity, -40000, reverses=correction)
        assert connection.execute(
            "SELECT app.credit_available_value(%s),app.payment_available_value(%s)",
            (credit, payment),
        ).fetchone() == (0, 0)


@pytest.mark.parametrize("credit_source", [False, True])
def test_usd_refund_blocks_source_reversal_until_full_verified_return(
    migrated_database_url: str,  # noqa: F811
    credit_source: bool,
) -> None:
    human, prop, customer, payment = source(migrated_database_url)
    credit = credit_id(recognize(prop, payment, human, 10000)) if credit_source else None
    with psycopg.connect(migrated_database_url) as connection:
        identity = refund(
            connection,
            human,
            customer,
            payment=None if credit_source else payment,
            credit=credit,
            amount=10000,
        )
    if credit is not None:
        with pytest.raises(CreditUnavailableError):
            service().reverse(
                prop,
                credit,
                ReverseCreditCommand(uuid4(), "Correct consent"),
                actor=actor(human, prop, "credits.reverse"),
            )
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            reverse(connection, payment, human)
        correction = correct(connection, human, identity, 10000)
    if credit is not None:
        service().reverse(
            prop,
            credit,
            ReverseCreditCommand(uuid4(), "Correct consent"),
            actor=actor(human, prop, "credits.reverse"),
        )
    with psycopg.connect(migrated_database_url) as connection:
        reverse(connection, payment, human)
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            correct(connection, human, identity, -10000, reverses=correction)
        assert connection.execute(
            "SELECT app.refund_net_value_at(%s,'infinity')", (identity,)
        ).fetchone() == (0,)


@pytest.mark.parametrize("credit_source", [False, True])
def test_usd_refund_concurrent_consumers_never_overspend(
    migrated_database_url: str,  # noqa: F811
    credit_source: bool,
) -> None:
    human, prop, customer, payment = source(migrated_database_url)
    credit = credit_id(recognize(prop, payment, human, 10000)) if credit_source else None
    barrier = Barrier(2)

    def worker() -> str:
        barrier.wait()
        try:
            with psycopg.connect(migrated_database_url) as connection:
                connection.execute("SET LOCAL lock_timeout='3s'")
                refund(
                    connection,
                    human,
                    customer,
                    payment=None if credit_source else payment,
                    credit=credit,
                    amount=7000,
                )
            return "posted"
        except psycopg.errors.CheckViolation:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert sorted(results) == ["posted", "rejected"]
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT sum(usd_accounting_value_cents) FROM app.refunds "
            "WHERE recipient_customer_id=%s",
            (customer,),
        ).fetchone() == (7000,)


def test_usd_credit_refund_stale_repeatable_read_fails_closed(migrated_database_url: str) -> None:  # noqa: F811
    human, prop, customer, payment = source(migrated_database_url)
    credit = credit_id(recognize(prop, payment, human, 10000))
    with psycopg.connect(migrated_database_url) as stale:
        stale.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        assert stale.execute("SELECT app.credit_available_value(%s)", (credit,)).fetchone() == (
            10000,
        )
        with psycopg.connect(migrated_database_url) as winner:
            refund(winner, human, customer, credit=credit, amount=7000)
        with pytest.raises(psycopg.errors.SerializationFailure):
            refund(stale, human, customer, credit=credit, amount=7000)
        stale.rollback()


@pytest.mark.parametrize("overlap", [False, True])
def test_usd_refund_historical_budget_rejects_backdated_deposit_overlap(
    migrated_database_url: str,  # noqa: F811
    overlap: bool,
) -> None:
    human, _, customer, payment = source(migrated_database_url, 10000 if overlap else 20000)
    with psycopg.connect(migrated_database_url) as connection:
        identity = refund(connection, human, customer, payment=payment, amount=10000)
        correct(connection, human, identity, 10000)
        row = connection.execute(
            "SELECT r.processed_at,c.occurred_at FROM app.refunds r "
            "JOIN app.refund_corrections c ON c.refund_id=r.id WHERE r.id=%s",
            (identity,),
        ).fetchone()
        assert row is not None
        between = row[0] + (row[1] - row[0]) / 2
        assert row[0] < between < row[1]
        _, prop, unit, _ = setup_reservation_sources(connection)

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


def test_usd_refund_private_boundary_immutable_history_and_fresh_actor(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, _, customer, payment = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        identity = refund(connection, human, customer, payment=payment)
        correction = correct(connection, human, identity)
        for table, event in (("refunds", identity), ("refund_corrections", correction)):
            for mutation in (
                "UPDATE app.{} SET reason='Rewrite' WHERE id=%s",
                "DELETE FROM app.{} WHERE id=%s",
            ):
                with pytest.raises(psycopg.Error), connection.transaction():
                    connection.execute(sql.SQL(mutation).format(sql.Identifier(table)), (event,))
            assert connection.execute(
                "SELECT has_table_privilege('prm_runtime',%s,'INSERT'),"
                "has_table_privilege('prm_financial',%s,'INSERT')",
                (f"app.{table}", f"app.{table}"),
            ).fetchone() == (False, False)
        for function in (
            "refund_net_value_at(uuid,timestamptz)",
            "lock_refund_payment_source(uuid,uuid)",
            "validate_general_refund_source()",
            "validate_general_refund_correction()",
        ):
            assert connection.execute(
                "SELECT has_function_privilege('prm_runtime',%s,'EXECUTE'),"
                "has_function_privilege('prm_financial',%s,'EXECUTE')",
                (f"app.{function}", f"app.{function}"),
            ).fetchone() == (False, False)
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
        with pytest.raises(psycopg.Error), connection.transaction():
            refund(connection, human, customer, payment=payment, amount=100)
        with pytest.raises(psycopg.Error), connection.transaction():
            correct(connection, human, identity, 100)


def test_usd_refund_khr_origin_uses_recorded_usd_without_repricing(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        payment = fx_payment(connection, channel=True, amount=4100, usd=101)
        row = connection.execute(
            "SELECT confirmed_by,payer_customer_id FROM app.payments WHERE id=%s", (payment,)
        ).fetchone()
        assert row is not None
        before = connection.execute(
            "SELECT row_to_json(p)::text,row_to_json(fx)::text FROM app.payments p "
            "JOIN app.exchange_rate_records fx ON fx.id=p.exchange_rate_record_id WHERE p.id=%s",
            (payment,),
        ).fetchone()
        identity = refund(
            connection, UUID(str(row[0])), UUID(str(row[1])), payment=payment, amount=101
        )
        assert connection.execute(
            "SELECT refund_currency,refund_amount_minor,usd_accounting_value_cents "
            "FROM app.refunds WHERE id=%s",
            (identity,),
        ).fetchone() == ("USD", 101, 101)
        assert connection.execute(
            "SELECT app.payment_available_value(%s)", (payment,)
        ).fetchone() == (0,)
        assert (
            connection.execute(
                "SELECT row_to_json(p)::text,row_to_json(fx)::text FROM app.payments p "
                "JOIN app.exchange_rate_records fx ON fx.id=p.exchange_rate_record_id "
                "WHERE p.id=%s",
                (payment,),
            ).fetchone()
            == before
        )
