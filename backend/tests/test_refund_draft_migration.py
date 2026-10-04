"""Refund methods and Refund drafts (BR-REFUND-014, BR-AUTH-010; V1-056 slice 3a)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from payment_test_support import seed_payment
from property_rental.financial_draft import FinancialDraftService
from property_rental.refund import (
    CreateUsdRefundCommand,
    RefundAuthorizationError,
    RefundConflictError,
    RefundIdempotencyKeyReused,
    RefundInvalidError,
    RefundMethodChoice,
    RefundService,
    refund_draft_id,
)
from refund_test_support import CASH_REFERENCE_NOTE, method_id
from test_credit_migration import actor, credit_id, recognize, source
from test_financial_draft_migration import _human
from test_invoice_migration import (
    create_recurring_rent_invoice,
    financial_database_url,
    runtime_database_url,
    setup_signed_lease,
)
from test_migrations import _temporary_migration_database
from test_pet_refund_migration import command as pet_command
from test_pet_refund_migration import qualified
from test_reservation_migration import migrated_database_url  # noqa: F401

NEW_TABLES = {"app.refund_methods", "app.refund_draft_details"}
RETIRED = (
    "app.create_usd_refund(uuid,uuid,uuid,text,uuid,bigint,text)",
    "app.create_pet_usd_refund(uuid,uuid,uuid,uuid,uuid,bigint,text)",
)


def service() -> RefundService:
    return RefundService(runtime_database_url(), financial_database_url())


def usd(source_id: UUID, amount: int = 4000) -> CreateUsdRefundCommand:
    return CreateUsdRefundCommand(uuid4(), "PAYMENT", source_id, amount, "Return eligible excess")


def available(url: str, payment: UUID) -> int:
    with psycopg.connect(url) as connection:
        row = connection.execute("SELECT app.payment_available_value(%s)", (payment,)).fetchone()
    assert row is not None
    return int(cast(int, row[0]))


def refund_count(url: str, payment: UUID) -> int:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT count(*) FROM app.refunds WHERE source_payment_id=%s", (payment,)
        ).fetchone()
    assert row is not None
    return int(cast(int, row[0]))


def test_refund_methods_start_with_cash_and_bank_transfer_and_are_configurable(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, _ = source(migrated_database_url)
    reader = actor(human, prop, "refunds.read")
    items = cast(list[dict[str, object]], service().refund_methods(prop, actor=reader)["items"])
    seeded = {item["code"]: item for item in items if item["seeded"]}
    assert set(seeded) == {"BANK_TRANSFER", "CASH"}
    assert all(item["active"] for item in seeded.values())
    with pytest.raises(RefundAuthorizationError):
        service().refund_methods(prop, actor=actor(human, prop, "payments.read"))

    manager = actor(human, prop, "property.manage")
    created = uuid4()
    code = f"WING_{created.hex[:8].upper()}"
    with psycopg.connect(runtime_database_url()) as connection:
        for reference in ("refunds.create", None):
            with pytest.raises(psycopg.Error) as refused:
                connection.execute(
                    "SELECT app.create_refund_method(%s,%s,%s,%s,%s,%s)",
                    (prop, human, created, code, "Wing transfer", reference),
                )
            assert refused.value.sqlstate == "42501"
            connection.rollback()
        connection.execute(
            "SELECT app.create_refund_method(%s,%s,%s,%s,%s,%s)",
            (prop, human, created, code, "Wing transfer", "property.manage"),
        )
        connection.execute(
            "SELECT app.set_refund_method_active(%s,%s,%s,false,%s)",
            (prop, human, created, "property.manage"),
        )
        connection.commit()
    assert method_id(service(), prop, manager, code) == created

    payment_human, payment_prop, _, payment = source(migrated_database_url)
    with pytest.raises(RefundInvalidError):
        service().record_usd_draft(
            payment_prop,
            usd(payment),
            RefundMethodChoice(created, "Inactive method"),
            actor=actor(payment_human, payment_prop, "refunds.create"),
        )
    for statement in (
        "UPDATE app.refund_methods SET code='CHANGED' WHERE id=%s",
        "UPDATE app.refund_methods SET display_name='Changed' WHERE id=%s",
        "DELETE FROM app.refund_methods WHERE id=%s",
    ):
        with psycopg.connect(migrated_database_url) as connection:
            with pytest.raises(psycopg.Error) as protected:
                connection.execute(statement, (created,))
        assert protected.value.sqlstate == "55000"


def test_refund_draft_has_no_effect_until_an_approver_confirms_it(
    migrated_database_url: str,  # noqa: F811
) -> None:
    preparer_id, prop, customer, payment = source(migrated_database_url)
    approver_id = _human(migrated_database_url, "refund-approver")
    preparer = actor(preparer_id, prop, "refunds.create")
    approver = actor(approver_id, prop, "financial.approve")
    before = available(migrated_database_url, payment)
    bank = RefundMethodChoice(
        method_id(service(), prop, preparer, "BANK_TRANSFER"), "ABA transfer ref 0042"
    )
    request = usd(payment)

    draft = service().record_usd_draft(prop, request, bank, actor=preparer)
    draft_id = UUID(str(draft["draft_id"]))
    assert draft_id == refund_draft_id(prop, preparer_id, "USD", request.idempotency_key)
    assert draft["state"] == "PENDING" and draft["kind"] == "REFUND"
    assert draft["prepared_by"] == str(preparer_id)
    assert service().record_usd_draft(prop, request, bank, actor=preparer) == draft
    with pytest.raises(RefundIdempotencyKeyReused):
        service().record_usd_draft(
            prop,
            CreateUsdRefundCommand(
                request.idempotency_key, "PAYMENT", payment, 3999, request.reason
            ),
            bank,
            actor=preparer,
        )
    assert available(migrated_database_url, payment) == before
    assert refund_count(migrated_database_url, payment) == 0

    with pytest.raises(RefundAuthorizationError):
        service().confirm_draft(prop, draft_id, actor=preparer)
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.Error) as refused:
            connection.execute(
                "SELECT app.confirm_refund_draft(%s,%s,%s,%s)",
                (prop, preparer_id, draft_id, "refunds.create"),
            )
    assert refused.value.sqlstate == "42501"
    assert refund_count(migrated_database_url, payment) == 0

    confirmed = service().confirm_draft(prop, draft_id, actor=approver)
    refund = cast(dict[str, object], confirmed["refund"])
    header = cast(dict[str, object], refund["refund"])
    assert header["recipient_customer_id"] == str(customer)
    assert header["refund_amount_minor"] == 4000 and header["refund_currency"] == "USD"
    assert cast(dict[str, object], confirmed["draft"])["state"] == "CONFIRMED"
    assert available(migrated_database_url, payment) == before - 4000
    assert service().confirm_draft(prop, draft_id, actor=approver) == confirmed
    other = actor(_human(migrated_database_url, "other-approver"), prop, "financial.approve")
    with pytest.raises(RefundConflictError):
        service().confirm_draft(prop, draft_id, actor=other)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT method.code, detail.reference_note, refund.processed_by, draft.prepared_by,"
            " decision.decided_by FROM app.refund_draft_details detail"
            " JOIN app.refund_methods method ON method.id=detail.refund_method_id"
            " JOIN app.refunds refund ON refund.id=detail.refund_id"
            " JOIN app.financial_drafts draft ON draft.id=detail.draft_id"
            " JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id"
            " WHERE detail.draft_id=%s",
            (draft_id,),
        ).fetchone() == (
            "BANK_TRANSFER",
            "ABA transfer ref 0042",
            approver_id,
            preparer_id,
            approver_id,
        )
        with pytest.raises(psycopg.Error) as immutable:
            connection.execute(
                "UPDATE app.refund_draft_details SET reference_note='changed' WHERE draft_id=%s",
                (draft_id,),
            )
    assert immutable.value.sqlstate == "55000"


def test_a_stale_refund_draft_is_refused_and_stays_pending(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    preparer = actor(human, prop, "refunds.create")
    approver = actor(human, prop, "financial.approve")
    cash = RefundMethodChoice(method_id(service(), prop, preparer), CASH_REFERENCE_NOTE)
    whole = available(migrated_database_url, payment)
    first, second = usd(payment, whole), usd(payment, whole)
    first_id = UUID(str(service().record_usd_draft(prop, first, cash, actor=preparer)["draft_id"]))
    second_id = UUID(
        str(service().record_usd_draft(prop, second, cash, actor=preparer)["draft_id"])
    )
    service().confirm_draft(prop, first_id, actor=approver)
    with pytest.raises(RefundInvalidError):
        service().confirm_draft(prop, second_id, actor=approver)
    assert refund_count(migrated_database_url, payment) == 1
    pending = FinancialDraftService(runtime_database_url(), financial_database_url()).get(
        prop, second_id, actor=approver
    )
    assert pending["state"] == "PENDING"


def test_pet_refund_draft_is_confirmed_with_its_method(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, _, deposit, review = qualified(migrated_database_url)
    preparer = actor(human, prop, "refunds.create")
    request = pet_command(deposit, review, 15000)
    cash = RefundMethodChoice(method_id(service(), prop, preparer), "Cash at move-out desk")
    draft_id = UUID(
        str(service().record_pet_draft(prop, request, cash, actor=preparer)["draft_id"])
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.refunds WHERE source_deposit_id=%s", (deposit,)
        ).fetchone() == (0,)
    confirmed = service().confirm_draft(
        prop, draft_id, actor=actor(human, prop, "financial.approve")
    )
    header = cast(dict[str, object], cast(dict[str, object], confirmed["refund"])["refund"])
    assert header["recipient_customer_id"] == str(customer)
    assert header["refund_amount_minor"] == 15000
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT reference_note FROM app.refund_draft_details WHERE draft_id=%s",
            (draft_id,),
        ).fetchone() == ("Cash at move-out desk",)


def test_the_direct_refund_functions_are_closed_to_application_roles(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    for url in (runtime_database_url(), financial_database_url()):
        with psycopg.connect(url) as connection:
            for function in RETIRED:
                assert connection.execute(
                    "SELECT has_function_privilege(current_user,%s,'EXECUTE')", (function,)
                ).fetchone() == (False,)
            for table in sorted(NEW_TABLES):
                assert connection.execute(
                    "SELECT has_table_privilege(current_user,%s,'SELECT')", (table,)
                ).fetchone() == (False,)
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.Error) as refused:
            connection.execute(
                "SELECT app.create_usd_refund(%s,%s,%s,'PAYMENT',%s,100,'Direct attempt')",
                (prop, human, uuid4(), payment),
            )
    assert refused.value.sqlstate == "42501"
    assert refund_count(migrated_database_url, payment) == 0


def test_refund_draft_migration_is_additive_and_forward_only(
    migrated_database_url: str,  # noqa: F811
) -> None:
    assert migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261013_78")
    assert revision is not None and revision.down_revision == "20261012_77"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(url: str) -> tuple[dict[str, object], set[str]]:
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
                    "WHERE n.nspname='app' AND c.relkind IN ('r','v','m','p')"
                ).fetchall()
            }
        return functions, tables

    with _temporary_migration_database("refund_drafts") as temporary:
        alembic_command.upgrade(config, "20261012_77")
        before_functions, before_tables = catalog(temporary)
        alembic_command.upgrade(config, "20261013_78")
        after_functions, after_tables = catalog(temporary)
    assert after_tables - before_tables == NEW_TABLES
    assert before_tables <= after_tables
    assert {name: after_functions[name] for name in before_functions} == before_functions


def test_a_stale_pet_refund_draft_is_refused_and_stays_pending(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, _, deposit, review = qualified(migrated_database_url)
    preparer = actor(human, prop, "refunds.create")
    approver = actor(human, prop, "financial.approve")
    whole = int(
        str(service().pet_source(prop, deposit, review, actor=preparer)["available_usd_cents"])
    )
    cash = RefundMethodChoice(method_id(service(), prop, preparer), CASH_REFERENCE_NOTE)
    first, second = pet_command(deposit, review, whole), pet_command(deposit, review, whole)
    first_id = UUID(str(service().record_pet_draft(prop, first, cash, actor=preparer)["draft_id"]))
    second_id = UUID(
        str(service().record_pet_draft(prop, second, cash, actor=preparer)["draft_id"])
    )
    service().confirm_draft(prop, first_id, actor=approver)
    with pytest.raises(RefundInvalidError):
        service().confirm_draft(prop, second_id, actor=approver)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.refunds WHERE source_deposit_id=%s", (deposit,)
        ).fetchone() == (1,)
    pending = FinancialDraftService(runtime_database_url(), financial_database_url()).get(
        prop, second_id, actor=approver
    )
    assert pending["state"] == "PENDING"


def test_a_method_turned_off_after_drafting_blocks_confirmation_but_not_replay(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    preparer = actor(human, prop, "refunds.create")
    method = uuid4()
    with psycopg.connect(runtime_database_url()) as connection:
        connection.execute(
            "SELECT app.create_refund_method(%s,%s,%s,%s,%s,%s)",
            (prop, human, method, f"TEMP_{method.hex[:8].upper()}", "Temporary", "property.manage"),
        )
        connection.commit()
    choice = RefundMethodChoice(method, "Temporary method note")
    request = usd(payment)
    draft = service().record_usd_draft(prop, request, choice, actor=preparer)
    with psycopg.connect(runtime_database_url()) as connection:
        for reference in ("refunds.create", "financial.approve"):
            with pytest.raises(psycopg.Error) as refused:
                connection.execute(
                    "SELECT app.set_refund_method_active(%s,%s,%s,false,%s)",
                    (prop, human, method, reference),
                )
            assert refused.value.sqlstate == "42501"
            connection.rollback()
        connection.execute(
            "SELECT app.set_refund_method_active(%s,%s,%s,false,%s)",
            (prop, human, method, "property.manage"),
        )
        connection.commit()
    # The exact repeat still replays the recorded draft.
    assert service().record_usd_draft(prop, request, choice, actor=preparer) == draft
    with pytest.raises(RefundInvalidError):
        service().record_usd_draft(prop, usd(payment), choice, actor=preparer)
    with pytest.raises(RefundInvalidError):
        service().confirm_draft(
            prop, UUID(str(draft["draft_id"])), actor=actor(human, prop, "financial.approve")
        )
    assert refund_count(migrated_database_url, payment) == 0


def test_a_credit_refund_draft_pays_the_credit_customer_once_confirmed(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, payment = source(migrated_database_url)
    credit = credit_id(recognize(prop, payment, human, 6000))
    preparer = actor(human, prop, "refunds.create")
    request = CreateUsdRefundCommand(uuid4(), "CREDIT", credit, 2500, "Return Customer Credit")
    cash = RefundMethodChoice(method_id(service(), prop, preparer), CASH_REFERENCE_NOTE)
    draft = service().record_usd_draft(prop, request, cash, actor=preparer)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT app.credit_available_value(%s)", (credit,)
        ).fetchone() == (6000,)
    confirmed = service().confirm_draft(
        prop, UUID(str(draft["draft_id"])), actor=actor(human, prop, "financial.approve")
    )
    refund = cast(dict[str, object], confirmed["refund"])
    assert cast(dict[str, object], refund["refund"])["recipient_customer_id"] == str(customer)
    assert cast(dict[str, object], refund["source"])["id"] == str(credit)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT app.credit_available_value(%s)", (credit,)
        ).fetchone() == (3500,)


def test_a_draft_id_that_is_already_a_refund_command_key_is_refused(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    key = uuid4()
    cash = method_id(service(), prop, actor(human, prop, "refunds.read"))
    with psycopg.connect(migrated_database_url) as connection:
        # An earlier one-call Refund (before drafts) used this key for this person.
        connection.execute(
            "SELECT app.create_usd_refund(%s,%s,%s,'PAYMENT',%s,100,'Earlier direct Refund')",
            (prop, human, key, payment),
        )
        connection.execute(
            "SELECT app.record_refund_draft(%s,%s,%s,'USD','PAYMENT',%s,NULL,200,%s,%s,%s,%s)",
            (prop, human, key, payment, "Second Refund", cash, "Cash", "refunds.create"),
        )
        connection.commit()
    with pytest.raises(RefundIdempotencyKeyReused):
        service().confirm_draft(prop, key, actor=actor(human, prop, "financial.approve"))
    assert refund_count(migrated_database_url, payment) == 1


def test_refund_draft_ids_keep_the_property_person_kind_and_key_scope() -> None:
    prop, other_prop, person, other_person, key = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    base = refund_draft_id(prop, person, "USD", key)
    assert base == refund_draft_id(prop, person, "USD", key)
    assert (
        len(
            {
                base,
                refund_draft_id(other_prop, person, "USD", key),
                refund_draft_id(prop, other_person, "USD", key),
                refund_draft_id(prop, person, "PET", key),
                refund_draft_id(prop, person, "USD", uuid4()),
            }
        )
        == 5
    )


def test_a_payment_draft_is_stale_once_the_payer_has_a_new_unpaid_invoice(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, lease = setup_signed_lease(connection)
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=50_000
        )
        connection.commit()
    preparer = actor(human, prop, "refunds.create")
    cash = RefundMethodChoice(method_id(service(), prop, preparer), CASH_REFERENCE_NOTE)
    draft = service().record_usd_draft(prop, usd(payment, 10_000), cash, actor=preparer)
    with psycopg.connect(migrated_database_url) as connection:
        create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=customer,
            lease_id=lease,
            period_start=date(2027, 2, 1),
        )
        connection.commit()
    with pytest.raises(RefundInvalidError) as stale:
        service().confirm_draft(
            prop, UUID(str(draft["draft_id"])), actor=actor(human, prop, "financial.approve")
        )
    cause = stale.value.__cause__
    assert isinstance(cause, psycopg.Error)
    assert cause.diag.message_primary == ("Refund draft is stale: the payer has unpaid obligations")
    assert refund_count(migrated_database_url, payment) == 0
    pending = FinancialDraftService(runtime_database_url(), financial_database_url()).get(
        prop, UUID(str(draft["draft_id"])), actor=actor(human, prop, "financial.approve")
    )
    assert pending["state"] == "PENDING"


@pytest.mark.parametrize(
    ("source_kind", "note"),
    [("PAYMENT", ""), ("PAYMENT", "x" * 501), ("PAYMENT", " padded "), ("INVOICE", "Cash")],
)
def test_the_database_refuses_a_bad_note_or_source_kind(
    migrated_database_url: str,  # noqa: F811
    source_kind: str,
    note: str,
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    cash = method_id(service(), prop, actor(human, prop, "refunds.read"))
    draft_id = uuid4()
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.Error) as refused:
            connection.execute(
                "SELECT app.record_refund_draft(%s,%s,%s,'USD',%s,%s,NULL,100,%s,%s,%s,%s)",
                (
                    prop,
                    human,
                    draft_id,
                    source_kind,
                    payment,
                    "Return excess",
                    cash,
                    note,
                    "refunds.create",
                ),
            )
    assert refused.value.sqlstate == "P5202"
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.financial_drafts WHERE id=%s", (draft_id,)
        ).fetchone() == (0,)


def test_a_refund_draft_of_an_unknown_variant_is_never_confirmed(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    draft_id = uuid4()
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "SELECT app.insert_financial_draft(%s,%s,%s,'REFUND','refunds.create',%s,NULL,%s)",
            (
                prop,
                human,
                draft_id,
                Jsonb({"variant": "RESERVATION", "source_id": str(payment)}),
                "Not a supported Refund",
            ),
        )
        connection.commit()
    with pytest.raises(RefundInvalidError):
        service().confirm_draft(prop, draft_id, actor=actor(human, prop, "financial.approve"))
    assert refund_count(migrated_database_url, payment) == 0
