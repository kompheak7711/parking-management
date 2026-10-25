"""The Refund reads name the draft variant and the recovery charge (V1-056 slice 11c-1).

BR-CREDIT-014: a Credit that a credit Adjustment released to a Customer other than the payer is
refunded only to that Customer through a CREDIT_CUSTOMER draft, so the Refund source read names
that Customer and the variant. The recovery read itself is checked in
`test_payment_return_recovery_migration.py::test_a_payment_refund_with_no_lease_is_charged_with_no_lease`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from payment_test_support import seed_payment
from property_rental.invoice import CreateInvoiceDraftCommand, VoidInvoiceCommand
from property_rental.refund import CreateUsdRefundCommand
from refund_test_support import create_usd_refund
from test_credit_adjustment_excess_migration import invoices, version
from test_credit_customer_refund_migration import service, staff, third_party_credit
from test_credit_migration import actor, credit_id, recognize, source
from test_invoice_migration import invoice_api_actor
from test_migrations import _temporary_migration_database
from test_payment_return_migration import approver as return_approver
from test_payment_return_migration import draft_id, request, returns
from test_payment_return_migration import preparer as return_preparer
from test_refund_service_migration import refund_id, returned
from test_reservation_migration import (
    migrated_database_url,  # noqa: F401
    setup_reservation_sources,
)

REVISION = "20270209_197"
INTERNAL = ("app.refund_correction_recovery(uuid)",)
PATCHED = {
    "app.usd_refund_source(uuid,uuid,text,uuid)",
    "app.refund_resource(uuid,uuid,uuid,integer,timestamp with time zone,uuid)",
}


def test_a_released_credit_names_its_customer_and_the_credit_customer_variant(
    migrated_database_url: str,  # noqa: F811
) -> None:
    case, credit, payer = third_party_credit(migrated_database_url)
    read = service().usd_source(case.prop, "CREDIT", credit, actor=staff(case))
    with psycopg.connect(migrated_database_url) as connection:
        customer = connection.execute(
            "SELECT customer_id FROM app.customer_credits WHERE id=%s", (credit,)
        ).fetchone()
    assert customer is not None and customer[0] != payer
    assert (read["recipient_customer_id"], read["refund_variant"]) == (
        str(customer[0]),
        "CREDIT_CUSTOMER",
    )
    assert read["eligible"] is True


def test_a_payment_or_its_own_credit_names_the_payer_and_the_usd_variant(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, payment = source(migrated_database_url)
    credit = credit_id(recognize(prop, payment, human, 3000))
    who = actor(human, prop, "refunds.create")
    for kind, identity in (("PAYMENT", payment), ("CREDIT", credit)):
        read = service().usd_source(prop, kind, identity, actor=who)
        assert (read["recipient_customer_id"], read["refund_variant"]) == (str(customer), "USD")


def test_a_recovery_billed_again_after_its_invoice_was_void_shows_the_new_invoice(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """Review round 1: the recovery's Invoice fields all come from one Invoice, the one that is
    not VOID."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        human, prop, _, customer = setup_reservation_sources(connection)
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=900
        )
    refunds = service()
    refund = refund_id(
        create_usd_refund(
            refunds,
            prop,
            CreateUsdRefundCommand(uuid4(), "PAYMENT", payment, 300, "Return the unused part"),
            actor=actor(human, prop, "refunds.create"),
        )
    )
    refunds.verify_usd_return(
        prop, refund, returned(100), actor=actor(human, prop, "refunds.correct")
    )
    draft = returns().record(prop, request(payment), actor=return_preparer(human, prop))
    returns().confirm(prop, draft_id(draft), actor=return_approver(human, prop))

    def recovery() -> dict[str, Any]:
        corrections = cast(
            dict[str, Any],
            refunds.get(prop, refund, actor=actor(human, prop, "refunds.read"))["corrections"],
        )
        return cast(dict[str, Any], corrections["items"][0]["recovery"])

    first = recovery()
    old_invoice = UUID(first["invoice_id"])
    invoices().void(
        prop,
        old_invoice,
        VoidInvoiceCommand(uuid4(), "Billed on the wrong date", version(url, old_invoice)),
        actor=invoice_api_actor(human, prop),
    )
    assert recovery()["invoice_status"] == "VOID"
    again = invoices().create_draft(
        prop,
        CreateInvoiceDraftCommand(uuid4(), UUID(first["authorized_nonrecurring_obligation_id"])),
        actor=invoice_api_actor(human, prop),
    )
    current = recovery()
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT id::text,invoice_number,status,due_date FROM app.invoices WHERE id=%s",
            (again["id"],),
        ).fetchone()
    assert row is not None and row[0] != str(old_invoice)
    assert (
        current["invoice_id"],
        current["invoice_number"],
        current["invoice_status"],
        current["due_date"],
    ) == (row[0], row[1], row[2], None if row[3] is None else row[3].isoformat())
    assert {
        key: value for key, value in current.items() if not key.startswith(("invoice", "due"))
    } == {key: value for key, value in first.items() if not key.startswith(("invoice", "due"))}


def test_the_refund_read_migration_adds_one_internal_function_and_is_forward_only(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """No role calls the new function; the migration adds it, changes only the two reads (each
    exactly as its patch says, privileges and settings kept) and is forward-only."""
    with psycopg.connect(migrated_database_url) as connection:
        for function in INTERNAL:
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (function, role)
            assert connection.execute(
                "SELECT p.prosecdef,p.provolatile,p.proconfig::text FROM pg_catalog.pg_proc p "
                "WHERE p.oid=CAST(%s AS regprocedure)",
                (function,),
            ).fetchone() == (True, "s", "{search_path=pg_catalog,TimeZone=UTC}"), function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270208_196"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def functions(database: str) -> dict[str, tuple[object, ...]]:
        with psycopg.connect(database) as connection:
            return {
                str(row[0]): tuple(row[1:])
                for row in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                    "p.proacl::text,p.proowner,p.prosecdef,p.proconfig::text "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ).fetchall()
            }

    with _temporary_migration_database("refund_reads_variant_recovery") as temporary:
        alembic_command.upgrade(config, "20270208_196")
        before = functions(temporary)
        alembic_command.upgrade(config, REVISION)
        after = functions(temporary)
    assert set(after) - set(before) == set(INTERNAL)
    assert set(before) <= set(after)
    assert {name for name in before if after[name] != before[name]} == PATCHED
    patches = dict(revision.module.PATCHES)
    for name in PATCHED:
        body = str(before[name][0])
        for anchor, replacement in patches[name]:
            assert body.count(anchor) == 1, name
            body = body.replace(anchor, replacement)
        assert after[name][0] == body, name
        assert after[name][1:] == before[name][1:], name
