"""T1 (DL-231): the Invoice type is kept on the Invoice.

The owner decided on 12 November 2026 (DL-226) that the seven Invoice types are kept on the
Invoice: Rent, Utilities, Short stay, Products, Damage, Late-payment, Other charges. Before, the
type was worked out from the category and the links each time it was read.

This file runs last in the gate list, so the check of every Invoice sees what the whole list made.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_invoice_items_migration import KEYS_LOCK_CLEANING, _create, _items, _lease
from test_invoice_migration import invoice_api_actor
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_one_time_charges_migration import invoices

REVISION = "20270728_394"
TYPED_DRAFT = (
    "app.create_items_invoice_draft_of_type("
    "uuid,uuid,uuid,text,uuid,uuid,uuid,uuid,uuid,text,text,jsonb,text)"
)
TYPED_STAY = "app.short_stay_invoice(uuid,uuid,uuid,text,text,jsonb,uuid,text)"
LINKS = {
    "quotations": "PRODUCTS",
    "short_stay_bookings": "SHORT_STAY",
    "short_stay_extra_invoices": "SHORT_STAY",
    "short_stay_credit_ends": "SHORT_STAY",
    "short_stay_damages": "DAMAGE",
}


def test_the_type_migration_follows_the_rate_migration_and_is_forward_only() -> None:
    scripts = ScriptDirectory.from_config(Config(str(Path(__file__).parents[1] / "alembic.ini")))
    revision = scripts.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == "20270727_379"
    source = Path(revision.path).read_text(encoding="utf-8")
    assert "forward-only" in source
    assert "DELETE FROM" not in source and "DROP TABLE" not in source


def test_every_invoice_keeps_the_type_its_category_and_links_say(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT is_nullable FROM information_schema.columns WHERE table_schema='app' "
            "AND table_name='invoices' AND column_name='invoice_type'"
        ).fetchone() == ("NO",)
        # The type is one of the kept types.
        assert connection.execute(
            "SELECT confrelid::regclass::text FROM pg_catalog.pg_constraint "
            "WHERE conrelid='app.invoices'::regclass AND contype='f' "
            "AND conname='invoices_invoice_type_fkey'"
        ).fetchone() == ("app.invoice_types",)
        # No Invoice the tests made, by any way, has another type than the old rule gave it.
        assert connection.execute(
            "SELECT count(*) FROM app.invoices AS invoice "
            "WHERE invoice.invoice_type IS DISTINCT FROM app.invoice_type_from_links(invoice.id)"
        ).fetchone() == (0,)
        # Every read gives the kept type.
        assert connection.execute(
            "SELECT count(*) FROM app.invoices AS invoice "
            "WHERE app.invoice_type_of(invoice.id) IS DISTINCT FROM invoice.invoice_type"
        ).fetchone() == (0,)


def test_a_new_invoice_gets_its_type_when_it_is_made_and_the_type_never_changes(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, customer, lease = _lease(url)
    staff = invoice_api_actor(human, prop)
    draft = invoices().create_items_draft(
        prop, _create(customer, lease, _items(*KEYS_LOCK_CLEANING)), actor=staff
    )
    invoice_id = UUID(str(draft["id"]))
    assert draft["invoice_type"] == "MISCELLANEOUS"
    with psycopg.connect(url) as connection:
        assert connection.execute(
            "SELECT invoice_type FROM app.invoices WHERE id=%s", (invoice_id,)
        ).fetchone() == ("MISCELLANEOUS",)
        # Nobody changes the type, also not on a Draft.
        with pytest.raises(psycopg.Error) as changed:
            with connection.transaction():
                connection.execute(
                    "UPDATE app.invoices SET invoice_type='PRODUCTS', version=version+1, "
                    "updated_at=statement_timestamp() WHERE id=%s",
                    (invoice_id,),
                )
        assert changed.value.sqlstate == "55000"
        assert "The Invoice type is kept as it was made" in str(changed.value)
        # A type that does not fit the category is refused when the Invoice is made.
        with pytest.raises(psycopg.Error) as unfit:
            with connection.transaction():
                connection.execute(
                    "INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,"
                    "primary_category,status,invoice_date,due_date,original_total_usd_cents,"
                    "due_date_rule,due_date_source,created_at,created_by,updated_at,updated_by,"
                    "invoice_type) SELECT gen_random_uuid(),'INV-T1-UNFIT',customer_id,lease_id,"
                    "primary_category,'DRAFT',invoice_date,NULL,original_total_usd_cents,"
                    "due_date_rule,due_date_source,created_at,created_by,updated_at,updated_by,"
                    "'RENT' FROM app.invoices WHERE id=%s",
                    (invoice_id,),
                )
        assert unfit.value.sqlstate == "23514"
        assert "The Invoice type does not fit the Invoice category" in str(unfit.value)


def test_only_the_database_states_a_type_and_a_link_checks_it(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        # The functions that state a type are for the database's own flows (a signed Quotation,
        # a short stay and its damage). No app role may call them.
        for function in (TYPED_DRAFT, TYPED_STAY):
            for role in ("public", "prm_runtime", "prm_financial", "prm_bootstrap"):
                assert connection.execute(
                    "SELECT pg_catalog.has_function_privilege(%s, %s::regprocedure, 'EXECUTE')",
                    (role, function),
                ).fetchone() == (False,), (function, role)
        # A Quotation and each short-stay record may only name an Invoice of their own type.
        found = connection.execute(
            "SELECT relation.relname, "
            "substring(pg_catalog.pg_get_triggerdef(trigger.oid) from '\\(''([A-Z_]+)''\\)$') "
            "FROM pg_catalog.pg_trigger AS trigger "
            "JOIN pg_catalog.pg_class AS relation ON relation.oid=trigger.tgrelid "
            "WHERE trigger.tgname='invoice_type_of_link' AND trigger.tgenabled='O'"
        ).fetchall()
        assert dict(found) == LINKS


def test_late_payment_is_the_seventh_type_and_is_not_in_use_yet(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT name_en, late_payment, in_use FROM app.invoice_types WHERE code='LATE_PAYMENT'"
        ).fetchone() == ("Late-payment", False, False)
        assert connection.execute(
            "SELECT array_agg(code ORDER BY sort_order) FROM app.invoice_types "
            "WHERE code NOT IN ('FIRST_RENT','SERVICES')"
        ).fetchone() == (
            [
                "RENT",
                "UTILITIES",
                "SHORT_STAY",
                "PRODUCTS",
                "DAMAGE",
                "LATE_PAYMENT",
                "MISCELLANEOUS",
            ],
        )
