"""Real PostgreSQL coverage for Invoice, Receipt and Refund numbers (V1-059 part B).

DL-071 answers 9 and 10 with the DL-075 amendment (migration `20270207_195`): letters, the
2-digit Asia/Phnom_Penh year and a running number that restarts each year per type, grows past
9999, never goes back and is given only when the document is issued.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import psycopg
import pytest
from psycopg import Connection

from test_invoice_migration import (
    create_recurring_rent_invoice,
    migrated_database_url,
    setup_signed_lease,
)

__all__ = ["migrated_database_url"]


def next_number(connection: Connection[tuple[object, ...]], kind: str, at: datetime) -> str:
    row = connection.execute("SELECT app.next_document_number(%s,%s)", (kind, at)).fetchone()
    assert row is not None
    return str(row[0])


def test_numbers_restart_each_phnom_penh_year_and_grow_past_9999(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        # 31 December 18:00 UTC is already 1 January in Phnom Penh.
        new_year = next_number(connection, "INVOICE", datetime(2090, 12, 31, 18, tzinfo=UTC))
        assert new_year == "INV910001"
        assert next_number(connection, "INVOICE", datetime(2091, 3, 1, tzinfo=UTC)) == "INV910002"
        # Each type has its own running number.
        assert next_number(connection, "RECEIPT", datetime(2091, 3, 1, tzinfo=UTC)) == "RCP910001"
        assert next_number(connection, "REFUND", datetime(2091, 3, 1, tzinfo=UTC)) == "RFD910001"
        assert next_number(connection, "INVOICE", datetime(2090, 6, 1, tzinfo=UTC)) == "INV900001"
        connection.execute(
            "UPDATE app.document_number_counters SET last_number=9998 "
            "WHERE document_type='INVOICE' AND number_year=2091"
        )
        assert next_number(connection, "INVOICE", datetime(2091, 5, 1, tzinfo=UTC)) == "INV919999"
        assert next_number(connection, "INVOICE", datetime(2091, 5, 1, tzinfo=UTC)) == "INV9110000"
        connection.rollback()


def test_a_counter_never_goes_back_and_the_letters_can_change(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        assert next_number(connection, "REFUND", datetime(2092, 1, 5, tzinfo=UTC)) == "RFD920001"
        for statement in (
            "UPDATE app.document_number_counters SET last_number=last_number-1 "
            "WHERE document_type='REFUND' AND number_year=2092",
            "DELETE FROM app.document_number_counters "
            "WHERE document_type='REFUND' AND number_year=2092",
        ):
            with pytest.raises(psycopg.Error) as refused, connection.transaction():
                connection.execute(statement)
            assert refused.value.sqlstate == "55000"
        # DL-075: new letters carry on with the same running number.
        connection.execute(
            "UPDATE app.document_number_series SET letters='RF' WHERE document_type='REFUND'"
        )
        assert next_number(connection, "REFUND", datetime(2092, 2, 1, tzinfo=UTC)) == "RF920002"
        for letters in ("R", "REFUNDS", "rfd", "INV"):
            with pytest.raises(psycopg.Error), connection.transaction():
                connection.execute(
                    "UPDATE app.document_number_series SET letters=%s WHERE document_type='REFUND'",
                    (letters,),
                )
        with pytest.raises(psycopg.Error) as unknown, connection.transaction():
            next_number(connection, "LETTER", datetime(2092, 2, 1, tzinfo=UTC))
        assert unknown.value.sqlstate == "22023"
        connection.rollback()


def test_a_draft_invoice_has_only_its_reference_until_it_is_issued(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        actor_id, _, customer_id, lease_id = setup_signed_lease(connection)
        draft_id, _ = create_recurring_rent_invoice(
            connection,
            actor_id=actor_id,
            customer_id=customer_id,
            lease_id=lease_id,
            issue=False,
            invoice_number="RENT-TEST-DRAFT",
        )
        assert connection.execute(
            "SELECT invoice_number, draft_reference FROM app.invoices WHERE id=%s", (draft_id,)
        ).fetchone() == ("RENT-TEST-DRAFT", "RENT-TEST-DRAFT")
        with pytest.raises(psycopg.Error) as typed, connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET invoice_number='INV269999' WHERE id=%s", (draft_id,)
            )
        assert typed.value.sqlstate == "55000"
        connection.execute(
            "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),"
            "issued_by=%s,version=2,updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
            (actor_id, actor_id, draft_id),
        )
        row = connection.execute(
            "SELECT invoice_number, draft_reference, "
            "to_char(issued_at AT TIME ZONE 'Asia/Phnom_Penh', 'YY') "
            "FROM app.invoices WHERE id=%s",
            (draft_id,),
        ).fetchone()
        assert row is not None
        assert re.fullmatch(rf"INV{row[2]}\d{{4,}}", str(row[0]))
        assert row[1] == "RENT-TEST-DRAFT"
        with pytest.raises(psycopg.Error), connection.transaction():
            connection.execute(
                "UPDATE app.invoices SET draft_reference='OTHER' WHERE id=%s", (draft_id,)
            )
        # A draft that is dropped keeps its reference and never takes a number.
        dropped_id, _ = create_recurring_rent_invoice(
            connection,
            actor_id=actor_id,
            customer_id=customer_id,
            lease_id=lease_id,
            period_start=datetime(2027, 3, 1).date(),
            issue=False,
            invoice_number="RENT-TEST-DROPPED",
        )
        # The void event itself is checked at commit; this test rolls back.
        connection.execute("SET CONSTRAINTS ALL DEFERRED")
        connection.execute(
            "UPDATE app.invoices SET status='VOID',version=2,updated_at=statement_timestamp(),"
            "updated_by=%s WHERE id=%s",
            (actor_id, dropped_id),
        )
        assert connection.execute(
            "SELECT invoice_number, draft_reference FROM app.invoices WHERE id=%s", (dropped_id,)
        ).fetchone() == ("RENT-TEST-DROPPED", "RENT-TEST-DROPPED")
        connection.rollback()
