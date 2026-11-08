"""Database review fixes of 7 Nov 2026, DL-202 (E) (migration 20270708_373): the database itself
checks the right ``ledger.accounts.manage`` when a Payment or Refund method's ledger account is
set (owner 8 Nov 2026 04:39). Until now only the API checked it before calling the function.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_gl_close_migration import keep_open
from test_gl_money_records_migration import Books
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_unit_migration import insert_actor, insert_property

REVISION = "20270708_373"
RIGHT = "ledger.accounts.manage"
MAPPINGS = "SELECT count(*) FROM app.gl_method_accounts WHERE property_id = %s"
AUDITS = (
    "SELECT count(*) FROM app.audit_events WHERE property_id = %s "
    "AND action = 'ledger.method_account.set'"
)


@pytest.fixture
def ledger(migrated_database_url: str) -> Iterator[Books]:
    """The ledger began last year; the Owner, a Manager and a Staff person each have a login."""
    with psycopg.connect(migrated_database_url) as connection:
        existing = connection.execute("SELECT id FROM app.properties").fetchone()
        if existing:
            property_id = UUID(str(existing[0]))
        else:
            property_id = insert_property(connection, insert_actor(connection))
        books = Books(connection, property_id, start=False)
        books.call("gl_begin_ledger", property_id, books.owner, books.today.year - 1)
        keep_open(books)
        yield books
        connection.rollback()


def test_migration_373_follows_372_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270707_372"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_only_a_person_with_the_accounts_right_sets_a_method_account(ledger: Books) -> None:
    """The Manager and Staff bundles do not hold ledger.accounts.manage (the Owner's right)."""
    prop = ledger.property_id
    method = ledger.scalar("SELECT id FROM app.payment_methods ORDER BY code LIMIT 1")
    mappings = ledger.scalar(MAPPINGS, (prop,))
    audits = ledger.scalar(AUDITS, (prop,))
    for person in (ledger.manager, ledger.staff, None):
        ledger.refused(
            "42501",
            "gl_set_method_account",
            prop,
            method,
            None,
            "1010",
            date(2026, 1, 1),
            person,
            match=RIGHT,
        )
    # A refused call writes nothing: no account mapping and no audit event.
    assert ledger.scalar(MAPPINGS, (prop,)) == mappings
    assert ledger.scalar(AUDITS, (prop,)) == audits
    made = ledger.call(
        "gl_set_method_account", prop, method, None, "1010", date(2026, 1, 1), ledger.owner
    )
    assert (
        ledger.scalar("SELECT created_by FROM app.gl_method_accounts WHERE id = %s", (made,))
        == ledger.owner
    )
    assert ledger.scalar(MAPPINGS, (prop,)) == mappings + 1
    assert ledger.scalar(AUDITS, (prop,)) == audits + 1
