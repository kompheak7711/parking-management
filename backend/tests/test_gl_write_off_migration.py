"""General Ledger write-off of Customer debt (migration 20270419_269, phase 6 step 4 part 3).

Owner decisions: DESIGN.md gap G6 (Write off is on an unpaid Invoice after the Final Settlement is
closed, Owner only, with a reason; 6160 debit, 1110 credit for a late-payment charge and 1100
credit for everything else; it is not a payment) and the approved database plan (a write-off is
a V1 charge reduction correction marked in app.gl_write_offs; automatic posting sends it to 6160).

The Final Settlement cases are the V1 ones (committed); each write-off runs in a transaction that
rolls back.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from payment_test_support import seed_payment
from property_rental.ledger_close_api import PostgresLedgerCloseFlow
from property_rental.ledger_money_api import LedgerMoneyNotFound, LedgerMoneyRefused
from property_rental.refund import CreateUsdRefundCommand, ReverseRefundCorrectionCommand
from refund_test_support import create_usd_refund
from test_credit_migration import actor
from test_final_settlement_closed_refusal_migration import close
from test_final_settlement_draft_migration import leaving_case
from test_gl_money_records_migration import Books, Borrowed
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_payment_return_migration import approver as return_approver
from test_payment_return_migration import draft_id, request, returns
from test_payment_return_migration import preparer as return_preparer
from test_refund_service_migration import refund_id, returned
from test_refund_service_migration import service as refund_service
from test_reservation_migration import setup_reservation_sources
from test_settlement_late_charge_reduction_migration import closed_overdue_case

REASON = "The Customer left the country and cannot be reached"


@pytest.fixture
def closed_case(migrated_database_url: str) -> dict[str, Any]:
    case = leaving_case(migrated_database_url)
    close(migrated_database_url, case["human"], case["settlement"])
    return case


@contextmanager
def books_for(url: str, property_id: UUID) -> Iterator[Books]:
    with psycopg.connect(url) as connection:
        yield Books(connection, property_id, start=False)
        connection.rollback()


def line_target(books: Books, line: UUID, cents: int) -> Jsonb:
    invoice = books.scalar("SELECT invoice_id FROM app.invoice_lines WHERE id = %s", (line,))
    return Jsonb(
        {"invoice_id": str(invoice), "invoice_line_id": str(line), "amount_usd_cents": cents}
    )


def events(books: Books, source_type: str) -> list[tuple[str, str, list[dict[str, Any]]]]:
    return [
        (str(key), str(description), list(lines))
        for key, description, lines in books.connection.execute(
            "SELECT posting_key, description, lines FROM app.gl_app_record_events(%s, %s, %s) "
            "WHERE source_type = %s",
            (books.property_id, date(2000, 1, 1), date(2100, 1, 1), source_type),
        ).fetchall()
    ]


def sides(lines: list[dict[str, Any]]) -> list[tuple[str, int, int]]:
    return [
        (
            str(line["account"]),
            int(line.get("debit_cents") or 0),
            int(line.get("credit_cents") or 0),
        )
        for line in lines
    ]


def test_an_unpaid_charge_is_written_off_to_6160_by_the_owner_with_a_reason(
    migrated_database_url: str, closed_case: dict[str, Any]
) -> None:
    with books_for(migrated_database_url, closed_case["prop"]) as books:
        target = line_target(books, closed_case["other_line"], 2_500)
        settlement = closed_case["settlement"]
        # Owner only (a Manager lacks ledger.write_off), with a reason.
        books.refused(
            "42501", "gl_write_off", books.property_id, books.manager, settlement, target, REASON
        )
        for reason in ("", " ", "x" * 501):
            books.refused(
                "22023", "gl_write_off", books.property_id, books.owner, settlement, target, reason
            )
        books.refused(
            "22023", "gl_write_off", books.property_id, books.owner, settlement, Jsonb([]), REASON
        )
        before = {key for key, _, _ in events(books, "INVOICE_ADJUSTMENT")}
        written = books.call(
            "gl_write_off", books.property_id, books.owner, settlement, target, REASON
        )
        row = books.connection.execute(
            "SELECT write_off.amount_cents, write_off.reason, write_off.approved_by, "
            "adjustment.adjustment_type, adjustment.invoice_line_id "
            "FROM app.gl_write_offs AS write_off "
            "JOIN app.settlement_correction_effects AS effect "
            "ON effect.settlement_correction_id = write_off.settlement_correction_id "
            "JOIN app.invoice_adjustments AS adjustment "
            "ON adjustment.id = effect.invoice_adjustment_id WHERE write_off.id = %s",
            (written,),
        ).fetchone()
        assert row == (2_500, REASON, books.owner, "CREDIT", closed_case["other_line"])
        # Automatic posting takes it off 1100 against 6160, not against income.
        [(key, description, lines)] = [
            event for event in events(books, "INVOICE_ADJUSTMENT") if event[0] not in before
        ]
        assert description.endswith(" written off")
        assert sorted(sides(lines)) == [("1100", 0, 2_500), ("6160", 2_500, 0)]
        assert key.startswith("invoice_adjustment:")
        assert (
            books.scalar(
                "SELECT count(*) FROM app.audit_events WHERE action = 'ledger.write_off' "
                "AND entity_id = %s",
                (written,),
            )
            == 1
        )
        # More than the unpaid rest is refused by the V1 correction checks.
        with pytest.raises(psycopg.Error):
            with books.connection.transaction():
                books.call(
                    "gl_write_off",
                    books.property_id,
                    books.owner,
                    settlement,
                    line_target(books, closed_case["other_line"], 10**12),
                    REASON,
                )


def test_a_late_payment_charge_is_written_off_against_1110(migrated_database_url: str) -> None:
    case = closed_overdue_case(migrated_database_url)
    with books_for(migrated_database_url, case["prop"]) as books:
        before = {key for key, _, _ in events(books, "LATE_PAYMENT_CHARGE_CORRECTION")}
        target = Jsonb({"late_payment_charge_id": str(case["charge"]), "amount_usd_cents": 1_000})
        written = books.call(
            "gl_write_off", books.property_id, books.owner, case["settlement"], target, REASON
        )
        assert (
            books.scalar("SELECT amount_cents FROM app.gl_write_offs WHERE id = %s", (written,))
            == 1_000
        )
        [(_, _, lines)] = [
            event
            for event in events(books, "LATE_PAYMENT_CHARGE_CORRECTION")
            if event[0] not in before
        ]
        assert sorted(sides(lines)) == [("1110", 0, 1_000), ("6160", 1_000, 0)]


def test_the_runtime_login_writes_off_only_through_the_checked_function(
    migrated_database_url: str,
) -> None:
    assert migrated_database_url
    with psycopg.connect(runtime_database_url()) as runtime:
        with pytest.raises(psycopg.Error) as caught:
            with runtime.transaction():
                runtime.execute(
                    "SELECT app.gl_write_off(gen_random_uuid(), gen_random_uuid(), "
                    "gen_random_uuid(), '{}', 'x', NULL)"
                )
        assert caught.value.sqlstate == "42501"
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with runtime.transaction():
                runtime.execute("INSERT INTO app.gl_write_offs (id) VALUES (gen_random_uuid())")
        runtime.rollback()


def test_the_migration_follows_fixed_assets() -> None:
    script = ScriptDirectory.from_config(Config(str(Path(__file__).parents[1] / "alembic.ini")))
    found = script.get_revision("20270419_269")
    assert found is not None and found.down_revision == "20270418_268"


def test_the_api_flow_writes_off_and_lists_the_write_offs(
    migrated_database_url: str, closed_case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    with books_for(migrated_database_url, closed_case["prop"]) as books:
        borrowed = Borrowed(books.connection)
        monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: borrowed)
        flow = PostgresLedgerCloseFlow("postgresql://unused")
        line = closed_case["other_line"]
        invoice = books.scalar("SELECT invoice_id FROM app.invoice_lines WHERE id = %s", (line,))
        values = {
            "final_settlement_id": closed_case["settlement"],
            "target": {
                "invoice_id": str(invoice),
                "invoice_line_id": str(line),
                "amount_usd_cents": 1_500,
            },
            "reason": REASON,
        }
        with pytest.raises(LedgerMoneyRefused, match=r"ledger\.write_off"):
            flow.write("write_off", books.property_id, str(books.manager), values)
        made = flow.write("write_off", books.property_id, str(books.owner), values)
        listed = [
            row for row in flow.rows("write-offs", books.property_id) if row["id"] == str(made)
        ]
        assert [(row["invoice_id"], row["amount_cents"], row["reason"]) for row in listed] == [
            (str(invoice), 1_500, REASON)
        ]
        with pytest.raises(LedgerMoneyNotFound):
            flow.write(
                "write_off",
                books.property_id,
                str(books.owner),
                {**values, "final_settlement_id": UUID(int=1)},
            )


def test_a_refund_correction_posts_by_itself(migrated_database_url: str) -> None:
    """Owner's cards of 03/11/2026 13:05 and 13:10: 300 of a Payment is refunded; 100 comes back
    (into the Refund method's account, back to money not used yet 2210); that give-back is
    undone; 100 comes back again; then the Payment bounces and the 200 still out is charged to
    the payer (back to 2210 against 4080, as the recovery Invoice posts 1100 against 4080)."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        human, prop, _, customer = setup_reservation_sources(connection)
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=900
        )
    refund = refund_id(
        create_usd_refund(
            refund_service(),
            prop,
            CreateUsdRefundCommand(uuid4(), "PAYMENT", payment, 300, "Return the unused part"),
            actor=actor(human, prop, "refunds.create"),
        )
    )
    refund_service().verify_usd_return(
        prop, refund, returned(100), actor=actor(human, prop, "refunds.correct")
    )
    with psycopg.connect(url) as connection:
        first = connection.execute(
            "SELECT id FROM app.refund_corrections WHERE refund_id = %s", (refund,)
        ).fetchone()
    assert first is not None
    refund_service().reverse_correction(
        prop,
        refund,
        UUID(str(first[0])),
        ReverseRefundCorrectionCommand(uuid4(), "Return evidence invalid", "Reverse correction"),
        actor=actor(human, prop, "refunds.corrections.reverse"),
    )
    refund_service().verify_usd_return(
        prop, refund, returned(100), actor=actor(human, prop, "refunds.correct")
    )
    draft = returns().record(prop, request(payment), actor=return_preparer(human, prop))
    returns().confirm(prop, draft_id(draft), actor=return_approver(human, prop))

    with books_for(url, prop) as books:
        method = books.scalar(
            "SELECT coalesce(draft.refund_method_id, settled.refund_method_id, "
            "corrected.refund_method_id) FROM app.refunds AS r "
            "LEFT JOIN app.refund_draft_details AS draft ON draft.refund_id = r.id "
            "LEFT JOIN app.final_settlement_refund_details AS settled ON settled.refund_id = r.id "
            "LEFT JOIN app.settlement_correction_refund_details AS corrected "
            "ON corrected.refund_id = r.id WHERE r.id = %s",
            (refund,),
        )

        def posted() -> list[tuple[str, str | None, list[tuple[str, int, int]]]]:
            return [
                (str(kind), problem, sides(lines))
                for kind, problem, lines in books.connection.execute(
                    "SELECT k.correction_kind, event.problem, event.lines "
                    "FROM app.gl_app_record_events(%s, %s, %s) AS event "
                    "JOIN app.refund_corrections AS k ON k.id = event.source_id "
                    "WHERE event.source_type = 'REFUND_CORRECTION' AND k.refund_id = %s "
                    "ORDER BY k.occurred_at, k.id",
                    (books.property_id, date(2000, 1, 1), date(2100, 1, 1), refund),
                ).fetchall()
            ]

        if (
            method is not None
            and books.scalar(
                "SELECT count(*) FROM app.gl_method_accounts WHERE refund_method_id = %s", (method,)
            )
            == 0
        ):
            # Without a ledger account for the method, money given back waits in Needs check.
            assert {problem for kind, problem, _ in posted() if kind != "RECOVERED_BY_CHARGE"} == {
                "No ledger account is set for the Refund method"
            }
            books.connection.execute(
                "SELECT app.gl_start_ledger(%s, %s::smallint, %s)",
                (books.property_id, books.today.year, books.owner),
            )
            books.call(
                "gl_set_method_account",
                books.property_id,
                None,
                method,
                "1010",
                date(2000, 1, 1),
                books.owner,
            )
        cash = books.scalar(
            "SELECT account.code FROM app.gl_method_accounts AS map JOIN app.gl_accounts AS "
            "account ON account.id = map.account_id WHERE map.refund_method_id = %s "
            "ORDER BY map.effective_from DESC LIMIT 1",
            (method,),
        )
        assert posted() == [
            ("VALUE_CORRECTION", None, [(cash, 100, 0), ("2210", 0, 100)]),
            ("CORRECTION_REVERSAL", None, [("2210", 100, 0), (cash, 0, 100)]),
            ("VALUE_CORRECTION", None, [(cash, 100, 0), ("2210", 0, 100)]),
            ("RECOVERED_BY_CHARGE", None, [("4080", 200, 0), ("2210", 0, 200)]),
        ]
