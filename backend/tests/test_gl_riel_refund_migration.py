"""A Refund paid straight from a riel account (migration 20270612_321, DL-161).

Owner 05/11/2026 07:25: "Refund straight from riel account." The Refund stays in dollars for
the tenant; the riel that left the riel account is typed once in Ledger > Needs check, and the
Refund then posts out of the riel account with its riel.

The Payment and the Refund are made through the V1 services; the ledger part runs inside one
transaction and rolls back.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.ledger_money_api import PostgresLedgerMoneyFlow
from refund_test_support import create_usd_refund
from test_credit_migration import actor
from test_credit_migration import source as payment_source
from test_gl_auto_posting_migration import SET_ACCOUNT, open_2026, post, problem
from test_gl_money_records_migration import Books, Borrowed
from test_gl_riel_bank_migration import riel_lines
from test_refund_service_migration import create, refund_id
from test_refund_service_migration import service as refunds
from test_reservation_migration import migrated_database_url  # noqa: F401

Connection = psycopg.Connection[Any]
TYPE_RIEL = "Type the riel paid for this Refund"
READY = "Ready: it posts at the next run"


def waiting(connection: Connection, prop: UUID, key: str) -> str | None:
    row = connection.execute(
        "SELECT problem FROM app.gl_waiting_records(%s) WHERE posting_key = %s", (prop, key)
    ).fetchone()
    return None if row is None else str(row[0])


def test_a_refund_from_the_riel_bank_waits_for_its_riel_then_posts_with_it(
    migrated_database_url: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    human, prop, _, payment = payment_source(migrated_database_url)
    made = create_usd_refund(
        refunds(), prop, create(payment, 3000), actor=actor(human, prop, "refunds.create")
    )
    refund = refund_id(made)
    key = f"refund:{refund}"
    with psycopg.connect(migrated_database_url) as connection:
        books = Books(connection, prop, start=False)
        open_2026(connection, prop, human)
        method = connection.execute(
            "SELECT refund_method_id FROM app.refund_draft_details WHERE refund_id = %s",
            (refund,),
        ).fetchone()
        assert method is not None
        post(connection, prop, human)
        assert "No ledger account is set for the Refund method" in str(problem(connection, key))
        # With no riel account yet there is no riel to type.
        books.refused(
            "55000",
            "gl_record_refund_riel",
            prop,
            books.owner,
            refund,
            410_000,
            match="does not wait for riel",
        )
        # A Refund method may now go to the riel bank (a Payment Method still may not).
        connection.execute(SET_ACCOUNT, (prop, None, method[0], "1021", human))
        # Needs check shows the problem as it is now, before the next run.
        assert waiting(connection, prop, key) == TYPE_RIEL
        post(connection, prop, human)
        assert problem(connection, key) == TYPE_RIEL
        assert riel_lines(connection, key) == []
        books.refused(
            "42501", "gl_record_refund_riel", prop, books.staff, refund, 12_300, match="right"
        )
        books.refused(
            "22023", "gl_record_refund_riel", prop, books.owner, refund, 0, match="more than 0"
        )
        books.refused(
            "P0002", "gl_record_refund_riel", prop, books.owner, uuid4(), 12_300, match="No such"
        )
        monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: Borrowed(connection))
        typed = PostgresLedgerMoneyFlow("postgresql://unused").write(
            "refund_riel",
            prop,
            str(books.manager),
            {"refund_id": refund, "riel_minor": 123_000},
        )
        assert isinstance(typed, UUID)
        books.refused(
            "55000",
            "gl_record_refund_riel",
            prop,
            books.owner,
            refund,
            123_000,
            match="already typed",
        )
        assert waiting(connection, prop, key) == READY
        audit = connection.execute(
            "SELECT actor_id, resulting_state ->> 'riel_minor' FROM app.audit_events "
            "WHERE action = 'ledger.refund_riel.recorded' AND entity_id = %s",
            (typed,),
        ).fetchone()
        assert audit == (books.manager, "123000")
        post(connection, prop, human)
        # The tenant got $30; 123,000 riel left the riel bank.
        assert riel_lines(connection, key) == [
            ("2210", 3000, 0, "USD", None),
            ("1021", 0, 3000, "KHR", 123_000),
        ]
        assert problem(connection, key) is None
        assert waiting(connection, prop, key) is None
        # The typed riel is kept as it is.
        with pytest.raises(psycopg.Error):
            with connection.transaction():
                connection.execute(
                    "UPDATE app.gl_refund_riel SET riel_minor = 1 WHERE id = %s", (typed,)
                )
        connection.rollback()


def test_only_the_function_writes_the_typed_riel(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT has_table_privilege('prm_runtime', 'app.gl_refund_riel', 'SELECT'), "
            "has_table_privilege('prm_runtime', 'app.gl_refund_riel', 'INSERT'), "
            "has_function_privilege('prm_runtime', "
            "'app.gl_record_refund_riel(uuid,uuid,uuid,bigint,uuid)', 'EXECUTE')"
        ).fetchone()
    assert row == (True, False, True)
