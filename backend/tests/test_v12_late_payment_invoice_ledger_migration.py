"""L1 (DL-233) in the General Ledger: a Late-payment Invoice is late-payment income.

The pass makes a Late-payment Invoice in place of a charge of the old kind. When it is issued,
the Ledger posts the debt to the Invoice account (1100) like every Invoice, and the income to
the late-payment income account (4050), as with a charge before, not to Other income (4080).
"""

from __future__ import annotations

import psycopg

from test_automatic_late_payment_charge_migration import no_pass_yet as no_pass_yet
from test_credit_adjustment_excess_migration import credit
from test_gl_auto_posting_migration import lines, open_2026, post
from test_late_payment_migration import migrated_database_url as migrated_database_url
from test_v12_late_payment_invoice_migration import charged, void


def test_the_ledger_counts_a_late_payment_invoice_as_late_payment_income(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = charged(url, 6)
    with psycopg.connect(url) as connection:
        open_2026(connection, case["prop"], case["human"])
        post(connection, case["prop"], case["human"])
        assert lines(connection, f"invoice:{case['late']}:issue") == [
            ("1100", 8_000, 0),
            ("4050", 0, 8_000),
        ]
        connection.rollback()


def test_the_ledger_takes_a_lowered_and_a_void_late_payment_invoice_out_of_late_payment_income(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    lowered = charged(url, 7)
    with psycopg.connect(url) as connection:
        line = connection.execute(
            "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", (lowered["late"],)
        ).fetchone()
    assert line is not None
    credit(url, lowered["human"], lowered["prop"], lowered["late"], line[0], 2_000)
    with psycopg.connect(url) as connection:
        adjustment = connection.execute(
            "SELECT id FROM app.invoice_adjustments WHERE invoice_id=%s", (lowered["late"],)
        ).fetchone()
        assert adjustment is not None
        open_2026(connection, lowered["prop"], lowered["human"])
        post(connection, lowered["prop"], lowered["human"])
        assert lines(connection, f"invoice_adjustment:{adjustment[0]}") == [
            ("1100", 0, 2_000),
            ("4050", 2_000, 0),
        ]
        connection.rollback()

    ended = charged(url, 8)
    void(url, ended, ended["late"])
    with psycopg.connect(url) as connection:
        open_2026(connection, ended["prop"], ended["human"])
        post(connection, ended["prop"], ended["human"])
        assert lines(connection, f"invoice:{ended['late']}:void") == [
            ("1100", 0, 8_000),
            ("4050", 8_000, 0),
        ]
        connection.rollback()
