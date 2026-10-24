"""Receipt identity, immutable history, authorization and no-new-money PostgreSQL tests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier
from time import monotonic, sleep
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import DBAPIError

from payment_test_support import seed_payment
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.receipt import (
    ReceiptAuthorizationError,
    ReceiptIdempotencyKeyReused,
    ReceiptInvalidError,
    ReceiptNotFoundError,
    ReceiptService,
    ReceiptUnavailableError,
    ReprintReceiptCommand,
)
from test_invoice_migration import financial_database_url, runtime_database_url
from test_migrations import _temporary_migration_database
from test_payment_migration import fx_payment, reverse
from test_reservation_migration import (
    create_reservation,
    migrated_database_url,  # noqa: F401
    setup_reservation_sources,
)


def service() -> ReceiptService:
    return ReceiptService(runtime_database_url(), financial_database_url())


def actor(identity: UUID, prop: UUID, *caps: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(identity),
        frozenset(CapabilityGrant(cap, frozenset({str(prop)})) for cap in caps),
    )


def source(url: str) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    with psycopg.connect(url) as connection:
        human, prop, _, customer = setup_reservation_sources(connection)
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=12345
        )
        row = connection.execute(
            "SELECT id FROM app.receipts WHERE payment_id=%s", (payment,)
        ).fetchone()
        assert row is not None
    return human, prop, customer, payment, UUID(str(row[0]))


def payment_number(database_url: str, payment: UUID) -> str:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            "SELECT payment_number FROM app.payments WHERE id=%s", (payment,)
        ).fetchone()
    assert row is not None and str(row[0]).startswith("RCP")
    return str(row[0])


def test_receipt_confirmation_identity_money_and_audit(migrated_database_url: str) -> None:  # noqa: F811
    human, prop, customer, payment, receipt = source(migrated_database_url)
    staff = actor(human, prop, "receipts.read")
    result = service().get(prop, receipt, actor=staff)
    assert result == service().for_payment(prop, payment, actor=staff)
    identity = result["receipt"]
    assert isinstance(identity, dict)
    assert identity["id"] == str(receipt)
    # DL-071 answer 10 (V1-059 part B): the Receipt has its Payment's number (RCP...).
    assert identity["receipt_number"] == payment_number(migrated_database_url, payment)
    assert identity["payment_id"] == str(payment)
    assert identity["payer_customer_id"] == str(customer)
    assert identity["issued_by"] == str(human)
    money = result["payment"]
    assert isinstance(money, dict)
    assert money["received_amount_minor"] == money["usd_accounting_value_cents"] == 12345
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.receipts WHERE payment_id=%s", (payment,)
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM app.payment_allocations WHERE payment_id=%s", (payment,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE entity_id=%s AND action='receipt.issued' "
            "AND actor_id=%s AND property_id=%s AND resulting_state->>'payment_id'=%s",
            (receipt, human, prop, str(payment)),
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT receipt.issued_at>=payment.confirmed_at FROM app.receipts receipt "
            "JOIN app.payments payment ON payment.id=receipt.payment_id WHERE receipt.id=%s",
            (receipt,),
        ).fetchone() == (True,)


def test_receipt_identity_snapshot_preserves_original_payer_name(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, _, receipt = source(migrated_database_url)
    staff = actor(human, prop, "receipts.read")
    before = service().get(prop, receipt, actor=staff)["receipt"]
    with psycopg.connect(migrated_database_url) as connection:
        name = connection.execute(
            "SELECT legal_name FROM app.customers WHERE id=%s", (customer,)
        ).fetchone()
        assert name is not None
        assert isinstance(before, dict)
        assert before["identity_snapshot"] == {"payer_legal_name": name[0]}
        connection.execute(
            "SELECT * FROM app.update_customer(%s,'Changed synthetic name',"
            "'012345678',NULL,NULL,NULL,1,%s,%s)",
            (customer, human, uuid4()),
        )
        assert connection.execute(
            "SELECT legal_name FROM app.customers WHERE id=%s", (customer,)
        ).fetchone() == ("Changed synthetic name",)
    assert service().get(prop, receipt, actor=staff)["receipt"] == before


def test_receipt_confirmation_rollback_is_atomic(migrated_database_url: str) -> None:  # noqa: F811
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, customer = setup_reservation_sources(connection)
        payment = uuid4()
        with pytest.raises(ValueError), connection.transaction():
            seed_payment(
                connection,
                actor_id=human,
                property_id=prop,
                customer_id=customer,
                amount=100,
                payment_id=payment,
            )
            assert connection.execute(
                "SELECT count(*) FROM app.receipts WHERE payment_id=%s", (payment,)
            ).fetchone() == (1,)
            raise ValueError("Synthetic transaction cancellation")
        assert connection.execute(
            "SELECT count(*) FROM app.payments WHERE id=%s", (payment,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.receipts WHERE payment_id=%s", (payment,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE resulting_state->>'payment_id'=%s",
            (str(payment),),
        ).fetchone() == (0,)


def test_receipt_reprint_replay_conflict_and_no_new_money(migrated_database_url: str) -> None:  # noqa: F811
    human, prop, _, payment, receipt = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        printer, printer_prop, _, _ = setup_reservation_sources(connection)
        assert printer != human and printer_prop == prop
        payments_before = connection.execute(
            "SELECT id FROM app.payments WHERE property_id=%s ORDER BY id", (prop,)
        ).fetchall()
        confirmations_before = connection.execute(
            "SELECT id FROM app.audit_events WHERE property_id=%s "
            "AND action='payment.confirmed' ORDER BY id",
            (prop,),
        ).fetchall()
        started = connection.execute("SELECT clock_timestamp()").fetchone()
        assert started is not None
    staff = actor(printer, prop, "receipts.reprint", "receipts.read")
    before = service().get(prop, receipt, actor=staff)
    request = ReprintReceiptCommand(uuid4(), "Paper damaged", "Front desk copy")
    result = service().reprint(prop, receipt, request, actor=staff)
    assert service().reprint(prop, receipt, request, actor=staff) == result
    assert result["receipt_id"] == str(receipt)
    assert result["payment_id"] == str(payment)
    assert result["receipt_number"] == payment_number(migrated_database_url, payment)
    with pytest.raises(ReceiptIdempotencyKeyReused):
        service().reprint(
            prop,
            receipt,
            ReprintReceiptCommand(request.idempotency_key, "Different reason"),
            actor=staff,
        )
    with pytest.raises(ReceiptIdempotencyKeyReused):
        service().reprint(
            prop,
            receipt,
            ReprintReceiptCommand(request.idempotency_key, request.reason, "Other copy"),
            actor=staff,
        )
    assert service().get(prop, receipt, actor=staff) == before
    history = service().history(prop, receipt, actor=staff)
    assert history["events"] == [result["reprint"]]
    assert history["has_more"] is False
    with psycopg.connect(migrated_database_url) as connection:
        finished = connection.execute("SELECT clock_timestamp()").fetchone()
        assert finished is not None
        assert (
            connection.execute(
                "SELECT id FROM app.payments WHERE property_id=%s ORDER BY id", (prop,)
            ).fetchall()
            == payments_before
        )
        assert (
            connection.execute(
                "SELECT id FROM app.audit_events WHERE property_id=%s "
                "AND action='payment.confirmed' ORDER BY id",
                (prop,),
            ).fetchall()
            == confirmations_before
        )
        persisted = connection.execute(
            "SELECT id,reprinted_by,reprinted_at,reason,delivery_reference "
            "FROM app.receipt_reprints WHERE receipt_id=%s",
            (receipt,),
        ).fetchall()
        assert len(persisted) == 1
        event_id, reprinted_by, reprinted_at, reason, delivery = persisted[0]
        assert reprinted_by == printer
        assert started[0] <= reprinted_at <= finished[0]
        assert reason == "Paper damaged" and delivery == "Front desk copy"
        returned = result["reprint"]
        assert isinstance(returned, dict)
        assert returned["reprinted_by"] == str(printer)
        assert datetime.fromisoformat(str(returned["reprinted_at"])) == reprinted_at
        assert returned["reason"] == reason and returned["delivery_reference"] == delivery
        assert connection.execute(
            "SELECT actor_id,occurred_at,reason,resulting_state->>'event_id' "
            "FROM app.audit_events WHERE entity_id=%s AND action='receipt.reprinted'",
            (receipt,),
        ).fetchall() == [(printer, reprinted_at, "Paper damaged", str(event_id))]
        assert connection.execute(
            "SELECT count(*) FROM app.payments WHERE id=%s", (payment,)
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM app.receipts WHERE payment_id=%s", (payment,)
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE entity_id=%s "
            "AND action='receipt.reprinted' "
            "AND correlation_id=%s AND authorization_reference='receipts.reprint'",
            (receipt, request.idempotency_key),
        ).fetchone() == (1,)


def test_receipt_reprint_survives_payment_reversal(migrated_database_url: str) -> None:  # noqa: F811
    human, prop, _, payment, receipt = source(migrated_database_url)
    staff = actor(human, prop, "receipts.read", "receipts.reprint")
    original = service().get(prop, receipt, actor=staff)["receipt"]
    first = service().reprint(
        prop, receipt, ReprintReceiptCommand(uuid4(), "Original copy"), actor=staff
    )
    with psycopg.connect(migrated_database_url) as connection:
        reverse(connection, payment, human)
    second = service().reprint(
        prop, receipt, ReprintReceiptCommand(uuid4(), "Historical copy"), actor=staff
    )
    assert first["receipt_id"] == second["receipt_id"] == str(receipt)
    resource = service().get(prop, receipt, actor=staff)
    assert resource["receipt"] == original
    assert isinstance(resource["payment"], dict)
    assert resource["payment"]["status"] == "REVERSED"
    events = service().history(prop, receipt, actor=staff)["events"]
    assert isinstance(events, list) and len(events) == 2


def test_receipt_independent_capabilities_and_disabled_replay(migrated_database_url: str) -> None:  # noqa: F811
    human, prop, _, _, receipt = source(migrated_database_url)
    reader = actor(human, prop, "receipts.read")
    printer = actor(human, prop, "receipts.reprint")
    request = ReprintReceiptCommand(uuid4(), "Requested copy")
    service().get(prop, receipt, actor=reader)
    with pytest.raises(ReceiptAuthorizationError):
        service().reprint(prop, receipt, request, actor=reader)
    service().reprint(prop, receipt, request, actor=printer)
    with pytest.raises(ReceiptAuthorizationError):
        service().get(prop, receipt, actor=printer)
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    with pytest.raises(ReceiptAuthorizationError):
        service().reprint(prop, receipt, request, actor=printer)
    with pytest.raises(ReceiptAuthorizationError):
        service().get(prop, receipt, actor=reader)


@pytest.mark.parametrize(
    "operation",
    [
        "UPDATE app.receipts SET receipt_number='changed' WHERE id=%s",
        "DELETE FROM app.receipts WHERE id=%s",
        "UPDATE app.receipt_reprints SET reason='changed' WHERE receipt_id=%s",
        "DELETE FROM app.receipt_reprints WHERE receipt_id=%s",
        "UPDATE app.receipt_reprint_commands SET reason='changed' WHERE receipt_id=%s",
        "DELETE FROM app.receipt_reprint_commands WHERE receipt_id=%s",
    ],
)
def test_receipt_and_reprint_history_immutable(migrated_database_url: str, operation: str) -> None:  # noqa: F811
    human, prop, _, _, receipt = source(migrated_database_url)
    service().reprint(
        prop,
        receipt,
        ReprintReceiptCommand(uuid4(), "Copy"),
        actor=actor(human, prop, "receipts.reprint"),
    )
    with (
        psycopg.connect(migrated_database_url) as connection,
        pytest.raises(psycopg.Error) as error,
    ):
        connection.execute(operation, (receipt,))
    assert error.value.sqlstate == "55000"


def test_receipt_concurrent_same_key_creates_one_reprint(migrated_database_url: str) -> None:  # noqa: F811
    human, prop, _, _, receipt = source(migrated_database_url)
    staff = actor(human, prop, "receipts.reprint", "receipts.read")
    request = ReprintReceiptCommand(uuid4(), "Concurrent retry")
    barrier = Barrier(2)

    def run() -> dict[str, object]:
        barrier.wait(timeout=10)
        return service().reprint(prop, receipt, request, actor=staff)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(run), pool.submit(run)
        assert a.result(timeout=15) == b.result(timeout=15)
    events = service().history(prop, receipt, actor=staff)["events"]
    assert isinstance(events, list) and len(events) == 1


def test_receipt_history_keyset_paging_and_cross_receipt_cursor(migrated_database_url: str) -> None:  # noqa: F811
    human, prop, _, _, receipt = source(migrated_database_url)
    staff = actor(human, prop, "receipts.reprint", "receipts.read")
    events = [
        service().reprint(prop, receipt, ReprintReceiptCommand(uuid4(), f"Copy {i}"), actor=staff)[
            "reprint"
        ]
        for i in range(3)
    ]
    first = service().history(prop, receipt, actor=staff, limit=2)
    assert first["events"] == events[:2] and first["has_more"] is True
    assert isinstance(events[1], dict)
    second = service().history(
        prop, receipt, actor=staff, after_id=UUID(str(events[1]["id"])), limit=2
    )
    assert second["events"] == events[2:] and second["has_more"] is False
    with pytest.raises(ReceiptInvalidError):
        service().history(prop, receipt, actor=staff, after_id=uuid4())
    other_human, other_prop, _, _, other_receipt = source(migrated_database_url)
    other = service().reprint(
        other_prop,
        other_receipt,
        ReprintReceiptCommand(uuid4(), "Other receipt"),
        actor=actor(other_human, other_prop, "receipts.reprint"),
    )["reprint"]
    assert isinstance(other, dict)
    with pytest.raises(ReceiptInvalidError):
        service().history(prop, receipt, actor=staff, after_id=UUID(str(other["id"])))


def test_receipt_storage_and_private_helpers_least_privilege(migrated_database_url: str) -> None:  # noqa: F811
    with psycopg.connect(migrated_database_url) as connection:
        for table in ("receipts", "receipt_reprints", "receipt_reprint_commands"):
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
                for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                    assert connection.execute(
                        "SELECT has_table_privilege(%s,%s,%s)", (role, f"app.{table}", privilege)
                    ).fetchone() == (False,)
        for name in (
            "validate_receipt_identity",
            "issue_payment_receipt",
            "audit_receipt_event",
            "validate_receipt_reprint",
        ):
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, f"app.{name}()")
                ).fetchone() == (False,)
        assert connection.execute(
            "SELECT has_function_privilege('prm_runtime',"
            "'app.reprint_receipt(uuid,uuid,uuid,uuid,text,text)','EXECUTE')"
        ).fetchone() == (False,)


def test_receipt_migration_refuses_fabricated_legacy_issuance() -> None:
    with _temporary_migration_database("prm_receipt_history") as url:
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", url)
        # Override the migration environment through its supported test hook.
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"MIGRATION_DATABASE_URL": url}):
            command.upgrade(config, "20260905_39")
            with psycopg.connect(
                url.replace("postgresql+psycopg://", "postgresql://", 1)
            ) as connection:
                human, prop, _, customer = setup_reservation_sources(connection)
                payment = seed_payment(
                    connection, actor_id=human, property_id=prop, customer_id=customer, amount=100
                )
            with pytest.raises(Exception, match="explicit reconciliation"):
                command.upgrade(config, "head")
            with psycopg.connect(
                url.replace("postgresql+psycopg://", "postgresql://", 1)
            ) as connection:
                assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                    "20260905_39",
                )
                assert connection.execute("SELECT to_regclass('app.receipts')").fetchone() == (
                    None,
                )
                assert connection.execute(
                    "SELECT count(*) FROM app.payments WHERE id=%s", (payment,)
                ).fetchone() == (1,)


def test_receipt_wrong_property_is_not_found_without_history_leak(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment, receipt = source(migrated_database_url)
    # This single-Property application cannot create another real Property;
    # exercise an explicit distinct scope identifier, not a reused fixture.
    other_prop = uuid4()
    assert other_prop != prop
    reader = actor(human, other_prop, "receipts.read", "receipts.reprint")
    with pytest.raises(ReceiptNotFoundError):
        service().get(other_prop, receipt, actor=reader)
    with pytest.raises(ReceiptNotFoundError):
        service().for_payment(other_prop, payment, actor=reader)
    with pytest.raises(ReceiptNotFoundError):
        service().history(other_prop, receipt, actor=reader)
    with pytest.raises(ReceiptNotFoundError):
        service().reprint(other_prop, receipt, ReprintReceiptCommand(uuid4(), "Copy"), actor=reader)
    assert (
        service().history(prop, receipt, actor=actor(human, prop, "receipts.read"))["events"] == []
    )


def test_receipt_khr_display_joins_exact_authoritative_fx(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        payment = fx_payment(connection)
        row = connection.execute(
            "SELECT confirmed_by,property_id,exchange_rate_record_id FROM app.payments WHERE id=%s",
            (payment,),
        ).fetchone()
        assert row is not None
    human, prop, rate = (UUID(str(value)) for value in row)
    result = service().for_payment(prop, payment, actor=actor(human, prop, "receipts.read"))
    money, fx = result["payment"], result["fx"]
    assert isinstance(money, dict) and isinstance(fx, dict)
    assert money["received_currency"] == "KHR"
    assert money["received_amount_minor"] == 4143
    assert money["usd_accounting_value_cents"] == 101
    assert fx["record_id"] == str(rate)
    assert fx["system_rate_khr_per_usd"] == "4101"


def test_receipt_allocation_reversal_changes_display_not_original_identity(
    migrated_database_url: str,  # noqa: F811
) -> None:
    from property_rental.payment_allocation import PostAllocationsCommand, ReverseAllocationCommand
    from test_payment_allocation_migration import actor as allocator
    from test_payment_allocation_migration import service as allocation_service
    from test_payment_allocation_migration import source as allocation_source

    human, prop, payment, _ = allocation_source(migrated_database_url)
    reader = actor(human, prop, "receipts.read", "receipts.reprint")
    before = service().for_payment(prop, payment, actor=reader)
    receipt = before["receipt"]
    assert isinstance(receipt, dict)
    receipt_id = UUID(str(receipt["id"]))
    allocation_actor = allocator(human, prop)
    proposal = allocation_service().proposal(prop, payment, actor=allocation_actor)
    posted = allocation_service().post(
        prop,
        payment,
        PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
        actor=allocation_actor,
    )
    after = service().get(prop, receipt_id, actor=reader)
    assert after["receipt"] == receipt
    position = after["financial_position"]
    assert isinstance(position, dict)
    assert position["allocated_usd_cents"] == 100_000 and position["available_usd_cents"] == 0
    printed = service().reprint(
        prop, receipt_id, ReprintReceiptCommand(uuid4(), "Allocated copy"), actor=reader
    )
    allocations = posted["allocation_ids"]
    assert isinstance(allocations, list)
    for allocation in allocations:
        allocation_service().reverse_allocation(
            prop,
            UUID(str(allocation)),
            ReverseAllocationCommand(uuid4(), "Correction"),
            actor=allocation_actor,
        )
    final = service().get(prop, receipt_id, actor=reader)
    assert final["receipt"] == receipt
    position = final["financial_position"]
    assert isinstance(position, dict)
    assert position["allocated_usd_cents"] == 0 and position["available_usd_cents"] == 100_000
    assert service().history(prop, receipt_id, actor=reader)["events"] == [printed["reprint"]]


def test_receipt_reprint_transaction_rollback_leaves_no_event_or_audit(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, _, receipt = source(migrated_database_url)
    key = uuid4()
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(ValueError), connection.transaction():
            connection.execute(
                "SELECT app.reprint_receipt(%s,%s,%s,%s,'Rollback copy',NULL)",
                (prop, receipt, human, key),
            )
            assert connection.execute(
                "SELECT count(*) FROM app.receipt_reprint_commands WHERE idempotency_key=%s", (key,)
            ).fetchone() == (1,)
            raise ValueError("Synthetic cancellation")
        assert connection.execute(
            "SELECT count(*) FROM app.receipt_reprints WHERE correlation_id=%s", (key,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.receipt_reprint_commands WHERE idempotency_key=%s", (key,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE correlation_id=%s", (key,)
        ).fetchone() == (0,)


def test_receipt_duplicate_payment_identity_is_rejected(
    migrated_database_url: str,  # noqa: F811
) -> None:
    _, _, _, payment, receipt = source(migrated_database_url)
    identity = uuid4()
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.errors.UniqueViolation), connection.transaction():
            connection.execute(
                "INSERT INTO app.receipts SELECT %s,%s,payment_id,payer_customer_id,"
                "issued_at,issued_by,identity_snapshot FROM app.receipts WHERE id=%s",
                (identity, f"R-{identity}", receipt),
            )
        assert connection.execute(
            "SELECT count(*) FROM app.receipts WHERE payment_id=%s", (payment,)
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM app.audit_events WHERE entity_id=%s", (identity,)
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    "reason,delivery", [("", None), (" Copy", None), ("Copy", ""), ("Copy", "x" * 501)]
)
def test_receipt_sql_command_bounds_fail_without_event(
    migrated_database_url: str,  # noqa: F811
    reason: str,
    delivery: str | None,
) -> None:
    human, prop, _, _, receipt = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error) as error, connection.transaction():
            connection.execute(
                "SELECT app.reprint_receipt(%s,%s,%s,%s,%s,%s)",
                (prop, receipt, human, uuid4(), reason, delivery),
            )
        assert error.value.sqlstate == "P5002"
        assert connection.execute(
            "SELECT count(*) FROM app.receipt_reprints WHERE receipt_id=%s", (receipt,)
        ).fetchone() == (0,)


def test_receipt_key_cannot_be_retargeted_but_another_actor_has_own_namespace(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, _, receipt = source(migrated_database_url)
    other_human, same_prop, _, _, other_receipt = source(migrated_database_url)
    assert same_prop == prop and other_human != human and other_receipt != receipt
    request = ReprintReceiptCommand(uuid4(), "Copy")
    first = service().reprint(prop, receipt, request, actor=actor(human, prop, "receipts.reprint"))
    with pytest.raises(ReceiptIdempotencyKeyReused):
        service().reprint(
            prop, other_receipt, request, actor=actor(human, prop, "receipts.reprint")
        )
    second = service().reprint(
        prop, receipt, request, actor=actor(other_human, prop, "receipts.reprint")
    )
    assert first["reprint"] != second["reprint"]
    events = service().history(prop, receipt, actor=actor(human, prop, "receipts.read"))["events"]
    assert isinstance(events, list) and len(events) == 2


def test_receipt_display_waits_for_source_payment_write_lock(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment, receipt = source(migrated_database_url)
    reader = actor(human, prop, "receipts.read")
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute("SELECT id FROM app.payments WHERE id=%s FOR UPDATE", (payment,))
        with pytest.raises(ReceiptUnavailableError) as error:
            service().get(prop, receipt, actor=reader)
        assert isinstance(error.value.__cause__, psycopg.errors.LockNotAvailable)
    resource = service().get(prop, receipt, actor=reader)
    position = resource["financial_position"]
    assert isinstance(position, dict)
    assert position["original_usd_cents"] == position["available_usd_cents"] == 12345
    assert position["allocated_usd_cents"] == 0


def test_receipt_migration_waits_for_writer_then_refuses_legacy_payment() -> None:
    with _temporary_migration_database("prm_receipt_overlap") as url:
        config = Config("alembic.ini")
        command.upgrade(config, "20260905_39")
        with psycopg.connect(url) as setup:
            human, prop, _, customer = setup_reservation_sources(setup)
        with psycopg.connect(url) as writer:
            payment = seed_payment(
                writer, actor_id=human, property_id=prop, customer_id=customer, amount=321
            )
            with ThreadPoolExecutor(max_workers=1) as pool:
                upgrade = pool.submit(command.upgrade, config, "head")
                blocked = False
                try:
                    deadline = monotonic() + 10
                    with psycopg.connect(url, autocommit=True) as observer:
                        while monotonic() < deadline and not upgrade.done():
                            blocked = observer.execute(
                                "SELECT EXISTS(SELECT 1 FROM pg_locks "
                                "WHERE relation='app.payments'::regclass AND NOT granted "
                                "AND mode='ShareRowExclusiveLock')"
                            ).fetchone() == (True,)
                            if blocked:
                                break
                            sleep(0.02)
                finally:
                    # Release only this test's writer before waiting for migration.
                    writer.commit()
                with pytest.raises(DBAPIError, match="explicit reconciliation"):
                    upgrade.result(timeout=15)
                assert blocked, "Upgrade must exclude concurrent inserts before inspecting history"
        with psycopg.connect(url) as observer:
            assert observer.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "20260905_39",
            )
            assert observer.execute("SELECT to_regclass('app.receipts')").fetchone() == (None,)
            assert observer.execute(
                "SELECT usd_accounting_value_cents FROM app.payments WHERE id=%s", (payment,)
            ).fetchone() == (321,)
            assert observer.execute(
                "SELECT count(*) FROM app.audit_events WHERE action='receipt.issued' "
                "AND resulting_state->>'payment_id'=%s",
                (str(payment),),
            ).fetchone() == (0,)


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_receipt_migration_rejects_stale_snapshot_isolation(isolation: str) -> None:
    with _temporary_migration_database("prm_receipt_isolation") as url:
        config = Config("alembic.ini")
        command.upgrade(config, "20260905_39")
        config.set_main_option("sqlalchemy.isolation_level", isolation)
        with pytest.raises(DBAPIError, match="requires read committed isolation"):
            command.upgrade(config, "head")
        with psycopg.connect(url) as observer:
            assert observer.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "20260905_39",
            )
            assert observer.execute("SELECT to_regclass('app.receipts')").fetchone() == (None,)


def test_receipt_display_snapshot_is_coherent_during_deposit_reversal() -> None:
    with _temporary_migration_database("prm_receipt_snapshot") as url:
        command.upgrade(Config("alembic.ini"), "head")
        with psycopg.connect(url) as setup:
            human, prop, unit, customer = setup_reservation_sources(setup)
            _, ids = create_reservation(
                setup, actor_id=human, property_id=prop, unit_id=unit, customer_id=customer
            )
            receipt_row = setup.execute(
                "SELECT id FROM app.receipts WHERE payment_id=%s", (ids["payment_id"],)
            ).fetchone()
            assert receipt_row is not None
            receipt = receipt_row[0]
            definition = setup.execute(
                "SELECT pg_get_functiondef('app.payment_disposition_summary(uuid)'::regprocedure)"
            ).fetchone()
            assert definition is not None and isinstance(definition[0], str)
            assert "app.payment_disposition_summary(" in definition[0]
            # Test-only pause in this uniquely owned database, not in production code.
            # Copy the real summary, then replace its original OID-preserving entry
            # point so both view and function consumers traverse the same gate.
            setup.execute(
                definition[0].replace(
                    "app.payment_disposition_summary(", "app.receipt_test_disposition_source(", 1
                )
            )
            setup.execute("""
                CREATE OR REPLACE FUNCTION app.payment_disposition_summary(p_payment_id uuid)
                RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
                SET search_path=pg_catalog AS $$
                DECLARE captured jsonb;
                BEGIN
                    captured:=app.receipt_test_disposition_source(p_payment_id);
                    IF current_setting('application_name')='receipt_consistency_reader' THEN
                        PERFORM pg_advisory_xact_lock(3218491050::bigint);
                    END IF;
                    RETURN captured;
                END $$
            """)

        def read_position() -> dict[str, object]:
            with psycopg.connect(url, application_name="receipt_consistency_reader") as reader:
                reader.execute("SET LOCAL statement_timeout='15s'")
                row = reader.execute(
                    "SELECT app.receipt_resource(%s,%s,%s)", (prop, receipt, human)
                ).fetchone()
                assert row is not None
                return dict(row[0]["financial_position"])

        with psycopg.connect(url, autocommit=True) as gate:
            gate.execute("SELECT pg_advisory_lock(3218491050::bigint)")
            with ThreadPoolExecutor(max_workers=1) as pool:
                reading = pool.submit(read_position)
                try:
                    blocked = False
                    deadline = monotonic() + 10
                    while monotonic() < deadline and not reading.done():
                        blocked = gate.execute(
                            "SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
                            "WHERE datname=current_database() "
                            "AND application_name='receipt_consistency_reader' "
                            "AND wait_event='advisory')"
                        ).fetchone() == (True,)
                        if blocked:
                            break
                        sleep(0.02)
                    assert blocked, "Reader must pause after capturing the old source position"
                    with psycopg.connect(url) as writer:
                        writer.execute("SET LOCAL lock_timeout='1s'")
                        writer.execute(
                            "SELECT app.reverse_deposit_receipt_v2(%s,%s,%s,%s,%s,%s,%s,%s)",
                            (
                                prop,
                                human,
                                uuid4(),
                                "f" * 64,
                                uuid4(),
                                ids["receipt_id"],
                                "Synthetic concurrent Receipt display reversal",
                                "deposits.correct",
                            ),
                        )
                    # Reversal committed before the paused Receipt response completes.
                    assert not reading.done()
                finally:
                    gate.execute("SELECT pg_advisory_unlock(3218491050::bigint)")
                before = reading.result(timeout=15)
        after = read_position()
        assert before["original_usd_cents"] == after["original_usd_cents"] == 10000
        assert before["allocated_usd_cents"] == after["allocated_usd_cents"] == 0
        assert before["deposit_directed_usd_cents"] == 10000
        assert before["available_usd_cents"] == 0
        assert after["deposit_directed_usd_cents"] == 0
        assert after["available_usd_cents"] == 10000
        assert before["allocation_condition"] == after["allocation_condition"] == "UNALLOCATED"
