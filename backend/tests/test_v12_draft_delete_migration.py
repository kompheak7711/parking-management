"""A Draft Invoice is changed freely and may be deleted (D6, DL-239; BR-INV-015).

Owner (12 Nov 2026, DL-226, D6). Before, a Draft was changed with a reason kept in its history,
and an unwanted Draft became Void with a reason. Now a Draft is changed with no reason asked and
may be deleted; its history starts when it is issued. An issued Invoice never changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.invoice import (
    CreateItemsInvoiceDraftCommand,
    DeleteInvoiceDraftCommand,
    InvoiceInvalidError,
    InvoiceNotFoundError,
    InvoiceVersionConflict,
    IssueInvoiceCommand,
    ReplaceInvoiceDraftItemsCommand,
)
from test_invoice_items_migration import EVIDENCE, KEYS_LOCK_CLEANING, REASON, _items, _lease
from test_invoice_migration import invoice_api_actor
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_one_time_charges_migration import invoices

DELETE = "app.delete_invoice_draft(uuid,uuid,uuid,integer,uuid)"


def counts(url: str, invoice: UUID) -> tuple[int, int, int, int, int]:
    """The Draft, its lines, its source claims, its revision history and its command records."""
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT (SELECT count(*) FROM app.invoices WHERE id=%(id)s),"
            "(SELECT count(*) FROM app.invoice_lines WHERE invoice_id=%(id)s),"
            "(SELECT count(*) FROM app.active_invoice_source_claims WHERE invoice_id=%(id)s),"
            "(SELECT count(*) FROM app.invoice_draft_revision_events WHERE invoice_id=%(id)s),"
            "(SELECT count(*) FROM app.invoice_commands WHERE invoice_id=%(id)s)",
            {"id": invoice},
        ).fetchone()
    assert row is not None
    return cast(tuple[int, int, int, int, int], tuple(int(value) for value in row))


def deleted_audits(url: str, invoice: UUID) -> list[tuple[object, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(
            "SELECT action,reason,authorization_reference FROM app.audit_events "
            "WHERE entity_type='invoice' AND entity_id=%s AND action='invoice.draft_deleted'",
            (invoice,),
        ).fetchall()


def draft(url: str) -> tuple[UUID, UUID, UUID, UUID, dict[str, object]]:
    human, prop, customer, lease = _lease(url)
    made = invoices().create_items_draft(
        prop,
        CreateItemsInvoiceDraftCommand(
            uuid4(), customer, lease, REASON, EVIDENCE, _items(*KEYS_LOCK_CLEANING)
        ),
        actor=invoice_api_actor(human, prop),
    )
    return human, prop, customer, lease, made


def test_a_draft_is_changed_with_no_reason_asked(migrated_database_url: str) -> None:
    url = migrated_database_url
    human, prop, customer, lease, made = draft(url)
    staff = invoice_api_actor(human, prop)
    invoice = UUID(str(made["id"]))
    changed = invoices().replace_draft_items(
        prop,
        invoice,
        ReplaceInvoiceDraftItemsCommand(
            uuid4(),
            customer,
            lease,
            REASON,
            EVIDENCE,
            None,
            _items(("Key copy", 3, 1_500)),
            cast(int, made["version"]),
        ),
        actor=staff,
    )
    assert changed["original_total"] == {"currency": "USD", "minor_units": 4_500}
    assert changed["status"] == "DRAFT"


def test_a_draft_is_deleted_with_its_lines_and_draft_history(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, customer, lease, made = draft(url)
    staff = invoice_api_actor(human, prop)
    invoice = UUID(str(made["id"]))
    # A change first, so the Draft has revision history too.
    changed = invoices().replace_draft_items(
        prop,
        invoice,
        ReplaceInvoiceDraftItemsCommand(
            uuid4(),
            customer,
            lease,
            REASON,
            EVIDENCE,
            None,
            _items(("Door lock", 1, 3_999)),
            cast(int, made["version"]),
        ),
        actor=staff,
    )
    before = counts(url, invoice)
    assert before[0] == 1 and before[1] == 1 and before[3] > 0 and before[4] == 2

    result = invoices().delete_draft(
        prop, invoice, DeleteInvoiceDraftCommand(cast(int, changed["version"])), actor=staff
    )
    assert result == {"invoice_id": str(invoice), "deleted": True}
    assert counts(url, invoice) == (0, 0, 0, 0, 0)
    assert deleted_audits(url, invoice) == [
        ("invoice.draft_deleted", "Draft Invoice deleted before issue", "invoices.create")
    ]
    # Deleting again: the Draft is not there any more.
    with pytest.raises(InvoiceNotFoundError):
        invoices().delete_draft(
            prop, invoice, DeleteInvoiceDraftCommand(cast(int, changed["version"])), actor=staff
        )


def test_an_issued_invoice_or_an_old_version_is_never_deleted(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, _customer, _lease_id, made = draft(url)
    staff = invoice_api_actor(human, prop)
    invoice = UUID(str(made["id"]))
    with pytest.raises(InvoiceVersionConflict):
        invoices().delete_draft(
            prop, invoice, DeleteInvoiceDraftCommand(cast(int, made["version"]) + 1), actor=staff
        )
    issued = invoices().issue(
        prop, invoice, IssueInvoiceCommand(uuid4(), cast(int, made["version"])), actor=staff
    )
    with pytest.raises(InvoiceInvalidError):
        invoices().delete_draft(
            prop, invoice, DeleteInvoiceDraftCommand(cast(int, issued["version"])), actor=staff
        )
    assert counts(url, invoice)[0] == 1
    # The protections hold outside the command too.
    with psycopg.connect(url) as connection, pytest.raises(psycopg.Error) as refused:
        connection.execute("DELETE FROM app.invoices WHERE id=%s", (invoice,))
    assert refused.value.sqlstate == "55000"


def test_a_draft_that_another_record_names_is_not_deleted(migrated_database_url: str) -> None:
    url = migrated_database_url
    human, prop, _customer, _lease_id, made = draft(url)
    staff = invoice_api_actor(human, prop)
    invoice = UUID(str(made["id"]))
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(
            "CREATE SCHEMA d6_probe;"
            "CREATE TABLE d6_probe.names_invoice(invoice_id uuid REFERENCES app.invoices(id))"
        )
        connection.execute("INSERT INTO d6_probe.names_invoice VALUES (%s)", (invoice,))
    try:
        with pytest.raises(InvoiceInvalidError):
            invoices().delete_draft(
                prop, invoice, DeleteInvoiceDraftCommand(cast(int, made["version"])), actor=staff
            )
        assert counts(url, invoice)[0] == 1
    finally:
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute("DROP SCHEMA d6_probe CASCADE")


def test_only_the_financial_role_may_delete_a_draft_and_the_migration_is_the_head(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        grants = connection.execute(
            "SELECT role,has_function_privilege(role,%s,'EXECUTE') "
            "FROM unnest(ARRAY['prm_runtime','prm_financial','prm_bootstrap']) role ORDER BY role",
            (DELETE,),
        ).fetchall()
        head = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert grants == [("prm_bootstrap", False), ("prm_financial", True), ("prm_runtime", False)]
    # The applied head is this migration or one built on it (a later step or a join).
    assert head is not None and _applies("20270802_399", str(head[0]))


def _applies(revision: str, head: str) -> bool:
    scripts = ScriptDirectory.from_config(Config(str(Path(__file__).parents[1] / "alembic.ini")))
    return any(script.revision == revision for script in scripts.walk_revisions("base", head))
