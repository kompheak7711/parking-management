"""Deposit Refund to another Lease Signer with a written agreement (BR-REFUND-015; slice 3a-2)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from payment_test_support import seed_deposit_payment
from property_rental.deposit import (
    PostgresDepositService,
    QualifyPetDepositRefundReviewCommand,
    RecordPetDepartureCommand,
)
from property_rental.refund import (
    RefundInvalidError,
    RefundMethodChoice,
    RefundService,
    SignerRecipient,
)
from refund_test_support import CASH_REFERENCE_NOTE, create_usd_refund, method_id
from test_credit_migration import actor, source
from test_deposit_migration import create_pet, deposit_actor
from test_invoice_migration import financial_database_url, runtime_database_url
from test_lease_migration import create_draft, setup_sources, sign_lease
from test_migrations import _temporary_migration_database
from test_pet_refund_migration import command as pet_command
from test_pet_refund_migration import qualified
from test_refund_draft_migration import usd as usd_command
from test_reservation_migration import migrated_database_url  # noqa: F401

AGREEMENT = "All Signers agreed in writing on 2026-10-04 at the office; signed note kept on file"


def service() -> RefundService:
    return RefundService(runtime_database_url(), financial_database_url())


def joint_qualified(url: str) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID]:
    """A qualified Pet Deposit on a Lease signed by the Primary Tenant and a second Signer."""
    with psycopg.connect(url) as connection:
        human, prop, unit, tenant, co_signer = setup_sources(connection)
        clock = connection.execute(
            "SELECT timezone(timezone_name, statement_timestamp())::date "
            "FROM app.properties WHERE id=%s",
            (prop,),
        ).fetchone()
        assert clock is not None
        today = cast(date, clock[0])
        lease = create_draft(
            connection,
            actor_id=human,
            unit_id=unit,
            primary_tenant_id=tenant,
            start_date=today - timedelta(days=30),
            end_date=today + timedelta(days=335),
        )
        connection.execute(
            "INSERT INTO app.lease_signers(id,lease_id,customer_id,signed_at,added_by) "
            "VALUES (%s,%s,%s,statement_timestamp(),%s)",
            (uuid4(), lease, co_signer, human),
        )
        sign_lease(connection, lease, human)
        approval = uuid4()
        connection.execute(
            "INSERT INTO app.lease_pet_approvals(id,lease_id,approved_date,"
            "deposit_required_by_signed_terms,pet_description,approved_at,approved_by) "
            "VALUES (%s,%s,%s,true,'Approved cat',clock_timestamp(),%s)",
            (approval, lease, today - timedelta(days=1), human),
        )
        connection.commit()
    deposits = PostgresDepositService(financial_database_url(), prop, human)
    who = deposit_actor(human, prop)
    deposit, _ = create_pet(deposits, who, lease, approval, today - timedelta(days=1))
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.deposit_receipts(id,deposit_id,payment_id,amount_usd_cents,"
            "occurred_at,actor_id) VALUES (%s,%s,%s,20000,clock_timestamp(),%s)",
            (
                uuid4(),
                deposit,
                seed_deposit_payment(connection, deposit_id=deposit, actor_id=human, amount=20_000),
                human,
            ),
        )
        connection.commit()
    departure = RecordPetDepartureCommand(uuid4(), uuid4(), deposit, today, "Pet permanently left")
    deposits.record_pet_departure(departure, actor=who)
    review = QualifyPetDepositRefundReviewCommand(
        uuid4(),
        uuid4(),
        departure.departure_id,
        deposit,
        30000,
        "All valid pet costs resolved separately; liability is not capped by Deposit",
        "Synthetic inspection and resolution evidence",
        "Qualified Pet exception",
    )
    deposits.qualify_pet_refund_review(review, actor=who)
    return human, prop, tenant, co_signer, deposit, review.review_id


def ledger_rows(url: str, refund: str) -> list[tuple[object, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(
            "SELECT customer_id,balance_kind,effect_usd_cents,"
            "source_audit->>'paid_to_customer_id' FROM app.customer_ledger_effects "
            "WHERE refund_id=%s AND event_kind='REFUND_PAID'",
            (refund,),
        ).fetchall()


def test_a_pet_refund_goes_to_an_agreed_signer_and_books_on_the_owner_ledger(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, tenant, co_signer, deposit, review = joint_qualified(migrated_database_url)
    preparer = actor(human, prop, "refunds.create")
    cash = RefundMethodChoice(method_id(service(), prop, preparer), CASH_REFERENCE_NOTE)
    request = pet_command(deposit, review, 12_000)
    signer = SignerRecipient(co_signer, AGREEMENT)
    draft = service().record_pet_draft(prop, request, cash, actor=preparer, recipient=signer)
    assert cast(dict[str, object], draft["payload"])["recipient_customer_id"] == str(co_signer)
    assert (
        service().record_pet_draft(prop, request, cash, actor=preparer, recipient=signer) == draft
    )
    confirmed = service().confirm_draft(
        prop, UUID(str(draft["draft_id"])), actor=actor(human, prop, "financial.approve")
    )
    header = cast(dict[str, object], cast(dict[str, object], confirmed["refund"])["refund"])
    assert header["recipient_customer_id"] == str(co_signer)
    assert (
        service().confirm_draft(
            prop, UUID(str(draft["draft_id"])), actor=actor(human, prop, "financial.approve")
        )
        == confirmed
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT recipient_customer_id,agreement_text FROM app.refund_recipient_agreements "
            "WHERE deposit_id=%s",
            (deposit,),
        ).fetchall() == [(co_signer, AGREEMENT)]
        with pytest.raises(psycopg.Error) as immutable:
            connection.execute(
                "UPDATE app.refund_recipient_agreements SET agreement_text='x' WHERE refund_id=%s",
                (header["id"],),
            )
    assert immutable.value.sqlstate == "55000"
    # The owner's ledger shows the Pet Deposit leaving and names the Signer who was paid.
    assert ledger_rows(migrated_database_url, str(header["id"])) == [
        (tenant, "PET_DEPOSIT", -12000, str(co_signer))
    ]


def test_the_default_recipient_stays_the_primary_tenant_with_no_paid_to(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, _, deposit, review = qualified(migrated_database_url)
    preparer = actor(human, prop, "refunds.create")
    cash = RefundMethodChoice(method_id(service(), prop, preparer), CASH_REFERENCE_NOTE)
    draft = service().record_pet_draft(
        prop, pet_command(deposit, review, 5000), cash, actor=preparer
    )
    confirmed = service().confirm_draft(
        prop, UUID(str(draft["draft_id"])), actor=actor(human, prop, "financial.approve")
    )
    header = cast(dict[str, object], cast(dict[str, object], confirmed["refund"])["refund"])
    assert header["recipient_customer_id"] == str(customer)
    assert ledger_rows(migrated_database_url, str(header["id"])) == [
        (customer, "PET_DEPOSIT", -5000, None)
    ]


def test_only_another_signer_with_a_written_agreement_may_receive_it(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, tenant, co_signer, deposit, review = joint_qualified(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        _, _, _, outsider, _ = setup_sources(connection)
        connection.commit()
    preparer = actor(human, prop, "refunds.create")
    cash = RefundMethodChoice(method_id(service(), prop, preparer), CASH_REFERENCE_NOTE)
    for customer in (outsider, tenant):
        with pytest.raises(RefundInvalidError):
            service().record_pet_draft(
                prop,
                pet_command(deposit, review, 1000),
                cash,
                actor=preparer,
                recipient=SignerRecipient(customer, AGREEMENT),
            )
    payment_source = uuid4()
    cash_id = cash.refund_method_id
    for variant, source_kind, source_id, review_id, recipient, agreement in (
        ("PET", None, deposit, review, co_signer, None),
        ("PET", None, deposit, review, co_signer, ""),
        ("PET", None, deposit, review, co_signer, " padded "),
        ("PET", None, deposit, review, co_signer, "x" * 2001),
        ("USD", "PAYMENT", payment_source, None, co_signer, AGREEMENT),
    ):
        with psycopg.connect(financial_database_url()) as connection:
            with pytest.raises(psycopg.Error) as refused:
                connection.execute(
                    "SELECT app.record_refund_draft("
                    "%s,%s,%s,%s,%s,%s,%s,1000,'Return',%s,'Cash',%s,%s,%s)",
                    (
                        prop,
                        human,
                        uuid4(),
                        variant,
                        source_kind,
                        source_id,
                        review_id,
                        cash_id,
                        "refunds.create",
                        recipient,
                        agreement,
                    ),
                )
        assert refused.value.sqlstate == "P5202"
    # Without a recorded agreement the Refund row cannot name another Signer.
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error) as unagreed:
            connection.execute(
                "SELECT app.create_pet_usd_refund_to_signer(%s,%s,%s,%s,%s,1000,%s,%s,%s)",
                (prop, human, uuid4(), deposit, review, "No agreement", uuid4(), co_signer),
            )
    assert unagreed.value.sqlstate == "23514"
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.refunds WHERE source_deposit_id=%s", (deposit,)
        ).fetchone() == (0,)


def test_signer_recipient_migration_is_forward_only_and_changes_only_two_functions(
    migrated_database_url: str,  # noqa: F811
) -> None:
    assert migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261014_79")
    assert revision is not None and revision.down_revision == "20261013_78"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(url: str) -> tuple[dict[str, object], set[str], tuple[object, ...]]:
        with psycopg.connect(url) as connection:
            functions = {
                str(row[0]): row[1]
                for row in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid) "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ).fetchall()
            }
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT c.oid::regclass::text FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND c.relkind='r'"
                ).fetchall()
            }
            columns = tuple(
                connection.execute(
                    "SELECT attname,atttypid::regtype::text FROM pg_catalog.pg_attribute "
                    "WHERE attrelid='app.customer_ledger_effects'::regclass AND attnum>0 "
                    "ORDER BY attnum"
                ).fetchall()
            )
        return functions, tables, columns

    with _temporary_migration_database("refund_signer") as temporary:
        alembic_command.upgrade(config, "20261013_78")
        before_functions, before_tables, before_columns = catalog(temporary)
        alembic_command.upgrade(config, "20261014_79")
        after_functions, after_tables, after_columns = catalog(temporary)
    assert after_tables - before_tables == {"app.refund_recipient_agreements"}
    assert after_columns == before_columns
    changed = {name for name in before_functions if after_functions[name] != before_functions[name]}
    assert changed == {
        "app.assert_pet_refund_source(app.refunds)",
        "app.confirm_refund_draft(uuid,uuid,uuid,text)",
    }


def test_refunds_of_the_earlier_shape_project_exactly_as_before(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """Without an agreement every Refund and correction keeps the revision 48 ledger result."""
    human, prop, _, payment = source(migrated_database_url)
    create_usd_refund(
        service(), prop, usd_command(payment), actor=actor(human, prop, "refunds.create")
    )
    pet_human, pet_prop, _, _, deposit, review = qualified(migrated_database_url)
    pet_preparer = actor(pet_human, pet_prop, "refunds.create")
    cash = RefundMethodChoice(method_id(service(), pet_prop, pet_preparer), CASH_REFERENCE_NOTE)
    draft = service().record_pet_draft(
        pet_prop, pet_command(deposit, review, 3000), cash, actor=pet_preparer
    )
    service().confirm_draft(
        pet_prop,
        UUID(str(draft["draft_id"])),
        actor=actor(pet_human, pet_prop, "financial.approve"),
    )
    with psycopg.connect(migrated_database_url) as connection:
        rows = connection.execute(
            "SELECT e.event_kind,e.customer_id=f.recipient_customer_id,"
            "e.source_audit ? 'paid_to_customer_id',f.source_deposit_id IS NOT NULL "
            "FROM app.customer_ledger_effects e JOIN app.refunds f ON f.id=e.refund_id "
            "WHERE e.event_kind IN ('REFUND_PAID','REFUND_CORRECTED') AND NOT EXISTS("
            "SELECT 1 FROM app.refund_recipient_agreements a WHERE a.refund_id=f.id)"
        ).fetchall()
    assert rows
    assert {row[3] for row in rows} == {True, False}
    # Old projection: customer = recipient and no paid-to key, for every such row.
    assert all(row[1] is True and row[2] is False for row in rows)
