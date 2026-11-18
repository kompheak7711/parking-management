"""UI v81 round 9 (owner 12/11/2026, migration 20270713_364): the Payments list and the Receipt
page name the same things.

Money paid to a one-time charge counts under the type of its Invoice (DL-221): a short stay under
Short stay, its damage under Damage and a miscellaneous charge under Other charges. The one kind
"move-out charges" is gone. The Receipt read gives each Invoice line its parts by Invoice line.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.payment_read import PaymentReadService, receipt_lines, summarize_period
from property_rental.receive_payment import ReceivePaymentCommand
from test_credit_migration import actor
from test_late_charge_payment_proposal_migration import two_months
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_one_time_charges_migration import draft_and_issue, invoices, miscellaneous, staff
from test_payments_summary_migration import KINDS, today
from test_receive_payment_migration import invoice, receive, usd
from test_short_stay_booking_migration import BookingDatabase, short_stay_database
from test_short_stay_check_in_migration import pay, read
from test_short_stay_ledger_migration import a_stay_with_damage

REVISION = "20270713_364"
SUMMARY = "SELECT app.payments_period_summary(%s, %s, %s, %s, 500)"
RECEIPT = "SELECT app.payment_receipt_lines(%s, %s, %s)"


@pytest.fixture(scope="module")
def stay_database(migrated_database_url: str) -> Iterator[BookingDatabase]:
    assert migrated_database_url
    with short_stay_database("prm_payments_paid_for") as database:
        yield database


def test_migration_364_follows_the_lease_numbers_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270712_363"
    assert scripts.get_heads() == ["20270811_434_parking"]
    with pytest.raises(NotImplementedError, match="forward-only"):
        revision.module.downgrade()


def test_a_short_stay_and_its_damage_count_under_the_type_of_their_invoice(
    stay_database: BookingDatabase,
) -> None:
    db = stay_database
    # The guest paid the stay. $80 damage: $50 kept from the cash deposit, $30 on an Invoice.
    made, _ = a_stay_with_damage(db, db.studio, 0, {"kind": "CASH"}, 8000)
    stay = read(db, made)["invoice"]
    with psycopg.connect(db.owner_url) as connection:
        damage = connection.execute(
            "SELECT damage.invoice_id, invoice.customer_id FROM app.short_stay_damages AS damage "
            "JOIN app.invoices AS invoice ON invoice.id = damage.invoice_id "
            "WHERE damage.booking_id = %s",
            (made,),
        ).fetchone()
    assert damage is not None
    pay(db, damage[1], str(damage[0]), 3000)

    with psycopg.connect(db.owner_url) as connection:

        def payment_of(invoice_id: object) -> str:
            found = connection.execute(
                "SELECT payment_id FROM app.payment_allocations WHERE invoice_id = %s",
                (invoice_id,),
            ).fetchall()
            assert len(found) == 1
            return str(found[0][0])

        read_summary = connection.execute(
            SUMMARY,
            (
                db.property_id,
                db.manager,
                db.today - timedelta(days=1),
                db.today + timedelta(days=1),
            ),
        ).fetchone()
        assert read_summary is not None
        summary = read_summary[0]
        rows = {row["payment_id"]: row for row in summary["rows"]}
        stay_payment = payment_of(stay["invoice_id"])
        damage_payment = payment_of(damage[0])
        # The list: each payment names the type of the Invoice it paid.
        assert rows[stay_payment]["kinds"] == {"SHORT_STAY": stay["total_usd_cents"]}
        assert rows[damage_payment]["kinds"] == {"DAMAGE": 3000}

        # The cards: the ten kinds, no "move-out charges", and they add up to the money received.
        totals = summary["totals"]
        assert set(totals["kinds"]) == set(KINDS)
        assert totals["kinds"]["SHORT_STAY"] == {
            "usd_cents": stay["total_usd_cents"],
            "payments": 1,
        }
        assert totals["kinds"]["DAMAGE"] == {"usd_cents": 3000, "payments": 1}
        assert totals["kinds"]["PRODUCTS"] == {"usd_cents": 0, "payments": 0}
        assert totals["kinds"]["OTHER"] == {"usd_cents": 0, "payments": 0}
        assert (
            sum(card["usd_cents"] for card in totals["kinds"].values())
            + totals["left_usd_cents"]
            + totals["refunded_usd_cents"]
            == totals["received_usd_cents"]
        )

        # The Receipt page: the same type, with the parts of the Invoice line under it.
        def receipt_line(payment: str) -> dict[str, Any]:
            found = connection.execute(RECEIPT, (db.property_id, db.manager, payment)).fetchone()
            assert found is not None
            [line] = found[0]["lines"]
            return cast(dict[str, Any], line)

        stay_line = receipt_line(stay_payment)
        assert stay_line["invoice_type"] == "SHORT_STAY"
        assert stay_line["parts"] == {"MISCELLANEOUS_CHARGES": stay["total_usd_cents"]}
        damage_line = receipt_line(damage_payment)
        assert damage_line["invoice_type"] == "DAMAGE"
        assert sum(damage_line["parts"].values()) == damage_line["amount_usd_cents"] == 3000
        connection.rollback()


def test_a_miscellaneous_charge_counts_under_other_charges(migrated_database_url: str) -> None:
    url = migrated_database_url
    case = two_months(url)
    day = today(url)
    who = staff(case["human"], case["prop"])
    command = miscellaneous(case["customer"])
    invoices().record_one_time_charge(case["prop"], command, actor=who)
    issued = draft_and_issue(case["prop"], command.charge_id, who)
    key_card = UUID(str(issued["id"]))
    paid = receive(
        case, ReceivePaymentCommand(usd(case, 1_500), "NAMED", (invoice(key_card, 1_500),))
    )

    reader = PaymentReadService(runtime_database_url())
    summary = cast(
        dict[str, Any],
        summarize_period(
            reader,
            case["prop"],
            day - timedelta(days=1),
            day + timedelta(days=1),
            actor=actor(case["human"], case["prop"], "payments.read"),
        ),
    )
    [row] = [item for item in summary["rows"] if item["payment_id"] == paid["payment"]["id"]]
    assert row["kinds"] == {"OTHER": 1_500}
    assert "MOVEOUT" not in summary["totals"]["kinds"]

    receipt = cast(
        dict[str, Any],
        receipt_lines(
            reader,
            case["prop"],
            UUID(paid["payment"]["id"]),
            actor=actor(case["human"], case["prop"], "receipts.read"),
        ),
    )
    [line] = receipt["lines"]
    assert line["invoice_type"] == "MISCELLANEOUS"
    assert line["parts"] == {"MISCELLANEOUS_CHARGES": 1_500}
