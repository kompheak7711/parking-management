"""General Ledger automatic posting from the app's money records (migration 20270415_265).

Owner decisions: accrual (01/11/2026), the automatic posting table of the General Ledger design
page and PRD v2 (PR-GL-020 to PR-GL-031), and the phase 6 plan of 03/11/2026 (L3: posting starts
on the ledger's first day; L4: a record dated in a closed month posts on the first day of the first
open month, with a note). The V1 records here are real ones made through the V1 services; each
test opens fiscal year 2026 inside its own transaction, posts, checks and rolls back.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from deposit_receipt_reversal_test_support import reverse_receipt_as_owner
from payment_test_support import seed_payment
from property_rental.deposit import ReverseDepositReceiptCommand
from property_rental.ledger_posting_api import PostgresLedgerPostingFlow
from property_rental.ledger_posting_job import LedgerPostingJob, LedgerPostingResult
from property_rental.payment_allocation import ReverseAllocationCommand
from refund_test_support import create_usd_refund
from test_credit_migration import actor, recognize
from test_credit_migration import source as payment_source
from test_customer_ledger_migration import canonical_invoice
from test_gl_money_records_migration import Borrowed
from test_invoice_migration import financial_database_url, runtime_database_url
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated
from test_payment_allocation_migration import service as allocations
from test_payment_reversal_context_migration import deposit_source
from test_refund_service_migration import create, refund_id
from test_refund_service_migration import service as refunds
from test_reservation_migration import migrated_database_url  # noqa: F401

Connection = psycopg.Connection[Any]
SET_ACCOUNT = (
    "SELECT app.gl_set_method_account(%s, %s, %s, %s, DATE '2026-01-01', %s, gen_random_uuid())"
)


def script_down_revision() -> str | None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    found = ScriptDirectory.from_config(config).get_revision("20270415_265")
    assert found is not None
    return cast(str | None, found.down_revision)


def open_2026(connection: Connection, prop: UUID, human: UUID) -> None:
    """The real ledger starts on 01/01/2027; the records made today need 2026 open."""
    connection.execute("SELECT app.gl_start_ledger(%s, 2026::smallint, %s)", (prop, human))


def post(connection: Connection, prop: UUID, human: UUID) -> tuple[int, int]:
    row = connection.execute(
        "SELECT posted, needs_check FROM app.gl_post_app_records(%s, %s, %s, 5000)",
        (prop, human, date(2026, 12, 31)),
    ).fetchone()
    assert row is not None
    connection.execute("SET CONSTRAINTS app.gl_journal_entries_balanced IMMEDIATE")
    connection.execute("SET CONSTRAINTS app.gl_journal_entries_balanced DEFERRED")
    return int(row[0]), int(row[1])


def lines(connection: Connection, key: str) -> list[tuple[str, int, int]]:
    """The (account, debit, credit) lines of the one entry a posting key made."""
    rows = connection.execute(
        "SELECT account.code, line.debit_cents, line.credit_cents "
        "FROM app.gl_journal_entries AS entry "
        "JOIN app.gl_journal_lines AS line ON line.entry_id = entry.id "
        "JOIN app.gl_accounts AS account ON account.id = line.account_id "
        "WHERE entry.posting_key = %s ORDER BY account.code, line.debit_cents",
        (key,),
    ).fetchall()
    return [(str(row[0]), int(row[1]), int(row[2])) for row in rows]


def entry(connection: Connection, key: str) -> tuple[date, str, str | None] | None:
    row = connection.execute(
        "SELECT entry_date, entry_kind, reason FROM app.gl_journal_entries WHERE posting_key=%s",
        (key,),
    ).fetchone()
    return None if row is None else (row[0], str(row[1]), row[2])


def problem(connection: Connection, key: str) -> str | None:
    row = connection.execute(
        "SELECT problem FROM app.gl_posting_problems WHERE posting_key=%s", (key,)
    ).fetchone()
    return None if row is None else str(row[0])


def method_of(connection: Connection, payment: UUID) -> UUID:
    row = connection.execute(
        "SELECT payment_method_id FROM app.payments WHERE id=%s", (payment,)
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


@pytest.fixture
def invoice_paid(
    migrated_database_url: str,  # noqa: F811
) -> Iterator[tuple[Connection, UUID, UUID, UUID, UUID, UUID]]:
    """A $500 Rent plus $10 Trash Invoice, a $300 Payment used for the Rent, then taken off."""
    human, prop, customer, invoice, rent, _ = canonical_invoice(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=30000
        )
    posted = allocations().post(
        prop, payment, designated(invoice, rent, 30000), actor=allocation_actor(human, prop)
    )
    allocation = UUID(str(cast(list[object], posted["allocation_ids"])[0]))
    allocations().reverse_allocation(
        prop,
        allocation,
        ReverseAllocationCommand(uuid4(), "Used for the wrong Invoice"),
        actor=allocation_actor(human, prop),
    )
    with psycopg.connect(migrated_database_url) as connection:
        open_2026(connection, prop, human)
        yield connection, prop, human, invoice, payment, allocation
        connection.rollback()


def test_an_invoice_payment_and_allocation_post_once_with_the_right_accounts(
    invoice_paid: tuple[Connection, UUID, UUID, UUID, UUID, UUID],
) -> None:
    connection, prop, human, invoice, payment, allocation = invoice_paid
    connection.execute(SET_ACCOUNT, (prop, method_of(connection, payment), None, "1010", human))
    post(connection, prop, human)
    # Accrual: the Invoice is income when it is issued; the July Rent month has started.
    assert lines(connection, f"invoice:{invoice}:issue") == [
        ("1100", 51000, 0),
        ("4010", 0, 50000),
        ("4020", 0, 1000),
    ]
    assert lines(connection, f"payment:{payment}") == [("1010", 30000, 0), ("2210", 0, 30000)]
    assert lines(connection, f"allocation:{allocation}") == [
        ("1100", 0, 30000),
        ("2210", 30000, 0),
    ]
    assert lines(connection, f"allocation:{allocation}:reversal") == [
        ("1100", 30000, 0),
        ("2210", 0, 30000),
    ]
    assert entry(connection, f"invoice:{invoice}:issue") is not None
    assert cast(tuple[date, str, None], entry(connection, f"payment:{payment}"))[1] == "AUTO"
    # Each record posts once: a second run adds nothing for these records.
    post(connection, prop, human)
    count = connection.execute(
        "SELECT count(*) FROM app.gl_journal_entries WHERE posting_key = ANY(%s)",
        (
            [
                f"invoice:{invoice}:issue",
                f"payment:{payment}",
                f"allocation:{allocation}",
                f"allocation:{allocation}:reversal",
            ],
        ),
    ).fetchone()
    assert count == (4,)


def test_a_method_without_an_account_waits_in_needs_check_until_it_is_set(
    invoice_paid: tuple[Connection, UUID, UUID, UUID, UUID, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, prop, human, invoice, payment, _ = invoice_paid
    key = f"payment:{payment}"
    post(connection, prop, human)
    assert entry(connection, key) is None
    assert "No ledger account is set for the Payment Method" in str(problem(connection, key))
    # Step 6 part 1: the Needs check row names the Receipt and opens it by its Payment.
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: Borrowed(connection))
    waiting = {
        row.posting_key: row
        for row in PostgresLedgerPostingFlow("postgresql://unused").needs_check(prop)
    }
    monkeypatch.undo()
    receipt = connection.execute(
        "SELECT receipt_number FROM app.receipts WHERE payment_id = %s", (payment,)
    ).fetchone()
    assert waiting[key].source_number == (None if receipt is None else receipt[0])
    assert waiting[key].source_link == {"page": "payments", "detail": f"receipt:{payment}"}
    assert entry(connection, f"invoice:{invoice}:issue") is not None
    connection.execute(SET_ACCOUNT, (prop, method_of(connection, payment), None, "1020", human))
    post(connection, prop, human)
    assert lines(connection, key) == [("1020", 30000, 0), ("2210", 0, 30000)]
    assert problem(connection, key) is None
    audit = connection.execute(
        "SELECT action, resulting_state->>'account' FROM app.audit_events "
        "WHERE action = 'ledger.method_account.set' AND actor_id = %s",
        (human,),
    ).fetchall()
    assert ("ledger.method_account.set", "1020") in [tuple(row) for row in audit]


def test_a_record_in_a_closed_month_posts_in_the_first_open_month_with_a_note(
    invoice_paid: tuple[Connection, UUID, UUID, UUID, UUID, UUID],
) -> None:
    connection, prop, human, invoice, payment, _ = invoice_paid
    connection.execute(SET_ACCOUNT, (prop, method_of(connection, payment), None, "1010", human))
    today = connection.execute(
        "SELECT timezone(timezone_name, statement_timestamp())::date FROM app.properties "
        "WHERE id=%s",
        (prop,),
    ).fetchone()
    assert today is not None and today[0].year == 2026
    for period in connection.execute(
        "SELECT id FROM app.gl_periods WHERE property_id=%s AND period_no <= %s "
        "AND starts_on >= DATE '2026-01-01' AND starts_on < DATE '2027-01-01' ORDER BY starts_on",
        (prop, today[0].month),
    ).fetchall():
        connection.execute(
            "SELECT app.gl_close_period(%s, %s, %s)",
            (period[0], human, Jsonb({"books_check": True})),
        )
    post(connection, prop, human)
    first_open = date(2026, today[0].month + 1, 1)
    posted = entry(connection, f"payment:{payment}")
    assert posted is not None and posted[0] == first_open
    assert "in a closed month; posted in the first open month" in str(posted[2])
    issued = entry(connection, f"invoice:{invoice}:issue")
    assert issued is not None and issued[0] == first_open


def test_credit_refund_and_deposit_receipts_move_money_not_used_yet(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = payment_source(migrated_database_url)
    credit = recognize(prop, payment, human, 4000)
    refund = create_usd_refund(
        refunds(), prop, create(payment, 3000), actor=actor(human, prop, "refunds.create")
    )
    service, staff, _, deposit, deposit_payment, receipts = deposit_source(migrated_database_url)
    reverse_receipt_as_owner(
        service,
        ReverseDepositReceiptCommand(uuid4(), uuid4(), receipts[0], "Incorrect receipt"),
        actor=staff,
    )
    credit_id = str(cast(dict[str, object], credit["credit"])["id"])
    refund_key = f"refund:{refund_id(refund)}"
    with psycopg.connect(migrated_database_url) as connection:
        open_2026(connection, prop, human)
        if service.property_id != prop:
            open_2026(connection, service.property_id, human)
        for each in {method_of(connection, payment), method_of(connection, deposit_payment)}:
            for where in {prop, service.property_id}:
                connection.execute(SET_ACCOUNT, (where, each, None, "1010", human))
        post(connection, prop, human)
        assert lines(connection, f"credit:{credit_id}") == [
            ("2200", 0, 4000),
            ("2210", 4000, 0),
        ]
        assert "No ledger account is set for the Refund method" in str(
            problem(connection, refund_key)
        )
        method = connection.execute(
            "SELECT refund_method_id FROM app.refund_draft_details WHERE refund_id=%s",
            (refund_id(refund),),
        ).fetchone()
        assert method is not None
        connection.execute(SET_ACCOUNT, (prop, None, method[0], "1010", human))
        post(connection, prop, human)
        assert lines(connection, refund_key) == [("1010", 0, 3000), ("2210", 3000, 0)]
        if service.property_id != prop:
            post(connection, service.property_id, human)
        assert lines(connection, f"deposit_receipt:{receipts[0]}") == [
            ("2110", 0, 10000),
            ("2210", 10000, 0),
        ]
        assert lines(connection, f"deposit_receipt:{receipts[0]}:reversal") == [
            ("2110", 10000, 0),
            ("2210", 0, 10000),
        ]
        assert lines(connection, f"deposit_receipt:{receipts[1]}") == [
            ("2110", 0, 10000),
            ("2210", 10000, 0),
        ]
        assert deposit
        connection.rollback()


def test_rent_billed_for_a_later_month_waits_in_rent_billed_in_advance(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(financial_database_url()) as financial:
        for rent_month, billed_on, account in (
            (date(2027, 2, 1), date(2027, 1, 25), "2050"),
            (date(2027, 2, 1), date(2027, 2, 1), "4010"),
            (date(2027, 2, 15), date(2027, 2, 3), "4010"),
            (date(2027, 1, 1), date(2027, 2, 3), "4010"),
        ):
            row = financial.execute(
                "SELECT app.gl_rent_account(%s, %s)", (rent_month, billed_on)
            ).fetchone()
            assert row == (account,), (rent_month, billed_on)


def test_only_the_financial_role_posts_and_methods_go_to_cash_accounts(
    invoice_paid: tuple[Connection, UUID, UUID, UUID, UUID, UUID],
) -> None:
    connection, prop, human, _, payment, _ = invoice_paid
    method = method_of(connection, payment)
    with psycopg.connect(runtime_database_url()) as runtime:
        assert runtime.execute(
            "SELECT has_function_privilege('prm_runtime', "
            "'app.gl_post_app_records(uuid,uuid,date,integer)', 'EXECUTE'), "
            "has_function_privilege('prm_financial', "
            "'app.gl_post_app_records(uuid,uuid,date,integer)', 'EXECUTE'), "
            "has_function_privilege('prm_runtime', "
            "'app.gl_app_record_events(uuid,date,date)', 'EXECUTE'), "
            "has_table_privilege('prm_runtime', 'app.gl_posting_problems', 'SELECT'), "
            "has_table_privilege('prm_runtime', 'app.gl_posting_problems', 'INSERT')"
        ).fetchone() == (False, True, False, True, False)
    # The billing worker's job runs with the money login; a Property whose ledger has not
    # started yet (it starts on 01/01/2027) posts nothing.
    other = UUID(int=0)
    assert LedgerPostingJob(financial_database_url(), property_id=other, actor_id=human).run(
        until=date(2026, 12, 31)
    ) == LedgerPostingResult(0, 0)
    assert script_down_revision() == "20270414_264"
    for payment_method, refund_method, code, match in (
        (method, None, "4010", "active cash or bank account"),
        (method, None, "9999", "active cash or bank account"),
        (None, None, "1010", "one Payment Method or one Refund method"),
        (method, method, "1010", "one Payment Method or one Refund method"),
    ):
        with pytest.raises(psycopg.errors.InvalidParameterValue, match=match):
            with connection.transaction():
                connection.execute(SET_ACCOUNT, (prop, payment_method, refund_method, code, human))
