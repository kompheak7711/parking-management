"""D3 (DL-232) in the General Ledger: a missed amount is income of what was missed.

An amount missed on a fully paid Rent line is billed on a new one-time Invoice of the type Rent.
When that Invoice is issued, the Ledger counts it as Rent income (4010), not as Other income
(4080).
"""

from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

import psycopg

from property_rental.invoice import IssueInvoiceCommand
from test_gl_auto_posting_migration import lines, open_2026, post
from test_invoice_items_migration import KEYS_LOCK_CLEANING, _create, _items
from test_invoice_migration import invoice_api_actor
from test_one_time_charges_migration import invoices
from test_reservation_migration import migrated_database_url as migrated_database_url
from test_v12_missed_amount_type_migration import MISSED, missed, paid_rent


def test_the_ledger_counts_a_missed_rent_amount_as_rent_income(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, customer, lease, _, rent, _ = paid_rent(url)
    staff = invoice_api_actor(human, prop)
    issued: list[UUID] = []
    for command in (
        missed(customer, lease, rent),
        _create(customer, lease, _items(*KEYS_LOCK_CLEANING)),
    ):
        draft = invoices().create_items_draft(prop, command, actor=staff)
        invoices().issue(
            prop,
            UUID(str(draft["id"])),
            IssueInvoiceCommand(uuid4(), cast(int, draft["version"])),
            actor=staff,
        )
        issued.append(UUID(str(draft["id"])))
    with psycopg.connect(url) as connection:
        open_2026(connection, prop, human)
        post(connection, prop, human)
        assert lines(connection, f"invoice:{issued[0]}:issue") == [
            ("1100", MISSED, 0),
            ("4010", 0, MISSED),
        ]
        # A one-time charge that names no missed line is Other income, as before.
        plain = lines(connection, f"invoice:{issued[1]}:issue")
        assert {account for account, _, credit in plain if credit} == {"4080"}
        connection.rollback()
