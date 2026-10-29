"""Narrow Credit/Refund reads preserve finance and runtime privilege boundaries."""

import json
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.credit_refund_read import (
    CreditRefundReadService,
    FinancialReadAuthorizationError,
    FinancialReadNotFoundError,
    Resource,
)
from refund_test_support import create_usd_refund
from test_credit_application_migration import application_id, designated
from test_credit_application_migration import source as application_source
from test_credit_migration import actor, credit_id, recognize, service, source
from test_invoice_migration import register_billing_service_principal, runtime_database_url
from test_payment_migration import fx_payment
from test_pet_refund_migration import qualified
from test_refund_service_migration import create, refund_id
from test_refund_service_migration import service as refunds
from test_reservation_migration import migrated_database_url  # noqa: F401


def reader() -> CreditRefundReadService:
    return CreditRefundReadService(runtime_database_url())


def snapshot(url: str, payment: UUID) -> object:
    with psycopg.connect(url) as connection:
        return connection.execute(
            "SELECT to_jsonb(p),to_jsonb(r),to_jsonb(g),"
            "(SELECT count(*) FROM app.customer_credits WHERE source_payment_id=p.id),"
            "(SELECT count(*) FROM app.refunds WHERE source_payment_id=p.id),"
            "(SELECT count(*) FROM app.audit_events) "
            "FROM app.payments p LEFT JOIN app.receipts r ON r.payment_id=p.id "
            "LEFT JOIN app.payment_serialization_guards g ON g.payment_id=p.id WHERE p.id=%s",
            (payment,),
        ).fetchone()


def test_credit_refund_read_all_resource_scopes_and_no_side_effects(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, payment = source(migrated_database_url)
    credit = credit_id(recognize(prop, payment, human, 5000))
    refund = refund_id(
        create_usd_refund(
            refunds(), prop, create(payment, 1000), actor=actor(human, prop, "refunds.create")
        )
    )
    before = snapshot(migrated_database_url, payment)
    who = actor(human, prop, "credits.read", "refunds.create", "refunds.read")
    resources: tuple[tuple[Resource, UUID], ...] = (
        ("property", prop),
        ("customer", customer),
        ("payment", payment),
        ("credit", credit),
        ("refund", refund),
    )
    for kind, identity in resources:
        assert reader().resolve(kind, identity, "credits.read", actor=who) == prop
        with pytest.raises(FinancialReadNotFoundError):
            reader().resolve(
                kind, identity, "credits.read", actor=actor(human, uuid4(), "credits.read")
            )
        with pytest.raises(FinancialReadNotFoundError):
            reader().resolve(kind, uuid4(), "credits.read", actor=who)
    payment_audit = reader().source_audit(prop, "PAYMENT", payment, actor=who)
    assert reader().source_audit(prop, "CREDIT", credit, actor=who) == payment_audit
    assert payment_audit["source_exchange_rate"] is None
    assert snapshot(migrated_database_url, payment) == before


def test_credit_refund_read_application_and_deposit_scopes(migrated_database_url: str) -> None:  # noqa: F811
    human, prop, credit, invoice, line, _ = application_source(migrated_database_url)
    who = actor(human, prop, "credits.apply", "credits.read")
    application = application_id(
        service().apply(prop, credit, designated(invoice, line, 1000), actor=who)
    )
    assert reader().resolve("credit_application", application, "credits.read", actor=who) == prop
    pet_human, pet_property, _, _, deposit, _ = qualified(migrated_database_url)
    assert (
        reader().resolve(
            "deposit",
            deposit,
            "refunds.create",
            actor=actor(pet_human, pet_property, "refunds.create"),
        )
        == pet_property
    )


def test_credit_refund_read_fresh_human_and_missing_scope_fail_closed(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    who = actor(human, prop, "refunds.create")
    assert reader().resolve("payment", payment, "refunds.create", actor=who) == prop
    with psycopg.connect(migrated_database_url) as connection:
        nonhuman_id = register_billing_service_principal(
            connection, property_id=prop, created_by=human
        )
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    before = snapshot(migrated_database_url, payment)
    identities = [human, uuid4()]
    identities.append(nonhuman_id)
    for identity in identities:
        denied = actor(identity, prop, "refunds.create")
        for resource in (payment, uuid4()):
            with pytest.raises(FinancialReadAuthorizationError):
                reader().resolve("payment", resource, "refunds.create", actor=denied)
        with pytest.raises(FinancialReadAuthorizationError):
            reader().source_audit(prop, "PAYMENT", payment, actor=denied)
    assert snapshot(migrated_database_url, payment) == before


def test_credit_refund_read_khr_audit_remains_original_exact_and_private(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        payment = fx_payment(connection, channel=True, channel_rate=Decimal("4100.123456"))
        row = connection.execute(
            "SELECT confirmed_by,property_id,to_jsonb(p) FROM app.payments p WHERE id=%s",
            (payment,),
        ).fetchone()
        assert row is not None
        human, prop, original = row
    credit = credit_id(recognize(prop, payment, human, 100))
    who = actor(human, prop, "refunds.create")
    before = snapshot(migrated_database_url, payment)
    audit = reader().source_audit(prop, "CREDIT", credit, actor=who)
    assert audit["source_payment"] == original
    exchange = audit["source_exchange_rate"]
    assert isinstance(exchange, dict)
    assert exchange["channel_actual_rate_khr_per_usd"] == "4100.123456"
    assert audit == reader().source_audit(prop, "PAYMENT", payment, actor=who)
    assert "idempotency" not in json.dumps(audit) and "canonical_command" not in json.dumps(audit)
    assert snapshot(migrated_database_url, payment) == before


@pytest.mark.parametrize(
    "invalid", ["unknown_kind", "nil_id", "nil_property", "null_element", "nested", "empty", "null"]
)
def test_credit_refund_read_sql_scope_rejects_invalid_boundaries(
    migrated_database_url: str,  # noqa: F811
    invalid: str,
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    kind, identity = "payment", payment
    properties: object = [prop]
    if invalid == "unknown_kind":
        kind = "private_command"
    elif invalid == "nil_id":
        identity = UUID(int=0)
    elif invalid == "nil_property":
        properties = [UUID(int=0)]
    elif invalid == "null_element":
        properties = [None]
    elif invalid == "nested":
        properties = [[prop]]
    elif invalid == "empty":
        properties = []
    else:
        properties = None
    with (
        psycopg.connect(runtime_database_url()) as connection,
        pytest.raises(psycopg.Error) as caught,
    ):
        connection.execute(
            "SELECT app.credit_refund_http_scope(%s,%s,%s,%s::uuid[])",
            (kind, identity, human, properties),
        )
    assert caught.value.sqlstate == ("P4501" if invalid in {"empty", "null"} else "22023")


def test_credit_refund_read_migration_graph_and_execute_only_privileges(
    migrated_database_url: str,  # noqa: F811
) -> None:
    config = Config("alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["20270402_252"]
    revision = scripts.get_revision("20260907_45")
    assert revision is not None and revision.down_revision == "20260907_44"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20270402_252",
        )
        for signature in (
            "app.credit_refund_http_scope(text,uuid,uuid,uuid[])",
            "app.credit_refund_http_source_audit(uuid,text,uuid,uuid)",
        ):
            row = connection.execute(
                "SELECT prosecdef,provolatile,proconfig FROM pg_proc WHERE oid=%s::regprocedure",
                (signature,),
            ).fetchone()
            assert row is not None and row[:2] == (True, "s")
            assert "search_path=pg_catalog" in row[2]
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)
                ).fetchone() == (role == "prm_runtime",)
        for table in (
            "customer_credits",
            "customer_credit_applications",
            "credit_commands",
            "refund_commands",
            "payment_confirmation_commands",
        ):
            assert connection.execute(
                "SELECT has_table_privilege('prm_runtime',%s,"
                "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')",
                (f"app.{table}",),
            ).fetchone() == (False,)


@pytest.mark.parametrize("currency", ["USD", "KHR"])
def test_credit_refund_read_confirmed_receipt_evidence_is_original_and_not_command_response(
    migrated_database_url: str,  # noqa: F811
    currency: str,
) -> None:
    from property_rental.khr_payment_confirmation import KhrPaymentConfirmationService
    from test_invoice_migration import financial_database_url
    from test_khr_payment_confirmation_migration import identity
    from test_khr_payment_confirmation_migration import source as khr_source
    from test_payment_confirmation_migration import service as confirmations
    from test_payment_confirmation_migration import source as usd_source

    if currency == "USD":
        human, prop, _, usd = usd_source(migrated_database_url)
        result = confirmations().confirm_usd(prop, usd, actor=actor(human, prop, "payments.record"))
        key = usd.idempotency_key
    else:
        human, prop, khr, provider = khr_source(migrated_database_url)
        result = KhrPaymentConfirmationService(financial_database_url(), provider).confirm_khr(
            prop, khr, actor=actor(human, prop, "payments.record")
        )
        key = khr.idempotency_key
    payment = identity(result)
    credit = credit_id(recognize(prop, payment, human, 100))
    who = actor(human, prop, "refunds.create")
    before = snapshot(migrated_database_url, payment)
    audit = reader().source_audit(prop, "PAYMENT", payment, actor=who)
    assert audit["receipt_evidence"] == {
        "received_at": result["received_at"],
        "evidence_reference": result["evidence_reference"],
    }
    assert reader().source_audit(prop, "CREDIT", credit, actor=who) == audit
    assert set(audit) == {"source_payment", "source_exchange_rate", "receipt_evidence"}
    assert str(key) not in json.dumps(audit)
    assert snapshot(migrated_database_url, payment) == before
