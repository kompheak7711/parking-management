"""General Ledger money records (migration 20270416_266, phase 6 step 3).

Owner decisions: the expense flow of 02/11/2026 (design page "Expense requests and Expense
reports"), D4 (nobody approves their own; the Owner's own spending goes in at once with a note),
the round 21 and 22 screens of DESIGN.md (Give advance; Record bill returns the change or owes the
staff the extra; Pay back staff; supplier bills paid in part or in full, due 30 days after the
bill date; petty cash topped up to the Petty cash amount; a cash count difference needs a reason
and goes to 6180; riel cash is counted in riel at the rate), and the rights table of 03/11/2026
(06:56 plan L1 and the 07:03 card: a Manager approves up to the Expense limit).

Each test gives three test accounts real role bundles (Owner, Manager and Staff rights of the
default bundles), opens this year in the ledger inside its transaction, and rolls back.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from property_rental.access_control import (
    OWNER_ONLY_LEDGER_CAPABILITIES,
    STAFF_LEDGER_CAPABILITIES,
)
from property_rental.ledger_money_api import (
    ACTIONS,
    LedgerMoneyConflict,
    LedgerMoneyInvalid,
    LedgerMoneyNotFound,
    LedgerMoneyRefused,
    PostgresLedgerMoneyFlow,
)
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_unit_migration import insert_actor, insert_property

Connection = psycopg.Connection[Any]
ADD_ACCOUNT = (
    "INSERT INTO app.user_accounts(actor_id,normalized_username,display_name,audit_name,"
    "lifecycle_state,mfa_policy_class,provenance) "
    "VALUES (%s,%s,'Ledger Test','ledger-test','active',%s,'gl-money-records-test')"
)
ADD_CLASS = (
    "INSERT INTO app.user_account_classes(actor_id,account_class,provenance) "
    "VALUES (%s,%s,'gl-money-records-test')"
)
ADD_BUNDLE = (
    "INSERT INTO app.role_bundles(role_bundle_id,property_id,name,version,provenance) "
    "VALUES (%s,%s,%s,1,'gl-money-records-test')"
)
ADD_CAPABILITY = (
    "INSERT INTO app.role_bundle_capabilities(role_bundle_id,version,capability_id,grant_path) "
    "VALUES (%s,1,%s,'bundle')"
)
ASSIGN = (
    "INSERT INTO app.user_role_assignments(assignment_id,actor_id,role_bundle_id,property_id,"
    "provenance) VALUES (%s,%s,%s,%s,'gl-money-records-test')"
)


class Books:
    """One Property with the ledger open this year and an Owner, a Manager and a Staff."""

    def __init__(self, connection: Connection, property_id: UUID, *, start: bool = True) -> None:
        self.connection = connection
        self.property_id = property_id
        ledger_rights = {
            str(row[0])
            for row in connection.execute(
                "SELECT capability_id FROM app.capabilities WHERE provenance = 'v1-1-ledger'"
            ).fetchall()
        }
        self.owner = self._person("manager", ledger_rights)
        self.manager = self._person("manager", ledger_rights - OWNER_ONLY_LEDGER_CAPABILITIES)
        self.staff = self._person("staff", set(STAFF_LEDGER_CAPABILITIES))
        self.other_staff = self._person("staff", set(STAFF_LEDGER_CAPABILITIES))
        self.today = self.scalar(
            "SELECT timezone(timezone_name, statement_timestamp())::date FROM app.properties "
            "WHERE id = %s",
            (property_id,),
        )
        if start:
            connection.execute(
                "SELECT app.gl_start_ledger(%s, %s::smallint, %s)",
                (property_id, self.today.year, self.owner),
            )

    def _person(self, account_class: str, rights: set[str]) -> UUID:
        actor = uuid4()
        mfa = "required" if account_class == "manager" else "optional"
        self.connection.execute(ADD_ACCOUNT, (actor, f"gl-{actor.hex}", mfa))
        self.connection.execute(ADD_CLASS, (actor, account_class))
        bundle = uuid4()
        self.connection.execute(ADD_BUNDLE, (bundle, self.property_id, f"GL test {bundle.hex}"))
        for right in sorted(rights):
            self.connection.execute(ADD_CAPABILITY, (bundle, right))
        self.connection.execute(ASSIGN, (uuid4(), actor, bundle, self.property_id))
        return actor

    def scalar(self, query: str, parameters: Any = ()) -> Any:
        row = self.connection.execute(query, parameters).fetchone()
        assert row is not None
        return row[0]

    def call(self, function: str, *arguments: Any) -> Any:
        marks = ", ".join(["%s"] * (len(arguments) + 1))
        return self.scalar(f"SELECT app.{function}({marks})", (*arguments, uuid4()))

    def refused(
        self, sqlstate: str, function: str, *arguments: Any, match: str | None = None
    ) -> None:
        with pytest.raises(psycopg.Error, match=match) as caught:
            with self.connection.transaction():
                self.call(function, *arguments)
        assert caught.value.sqlstate == sqlstate, caught.value

    def balance(self, code: str) -> int:
        return int(
            self.scalar(
                "SELECT coalesce(sum(line.debit_cents - line.credit_cents), 0) "
                "FROM app.gl_journal_lines AS line JOIN app.gl_accounts AS account "
                "ON account.id = line.account_id WHERE account.property_id = %s "
                "AND account.code = %s",
                (self.property_id, code),
            )
        )

    def lines(self, key: str) -> list[tuple[str, int, int]]:
        return [
            (str(code), int(debit), int(credit))
            for code, debit, credit in self.connection.execute(
                "SELECT account.code, line.debit_cents, line.credit_cents "
                "FROM app.gl_journal_entries AS entry "
                "JOIN app.gl_journal_lines AS line ON line.entry_id = entry.id "
                "JOIN app.gl_accounts AS account ON account.id = line.account_id "
                "WHERE entry.property_id = %s AND entry.posting_key = %s ORDER BY line.line_no",
                (self.property_id, key),
            ).fetchall()
        ]

    def request(self, request_id: UUID) -> tuple[str, str | None, UUID | None]:
        row = self.connection.execute(
            "SELECT status, own_spending_note, decided_by FROM app.gl_expense_requests "
            "WHERE id = %s",
            (request_id,),
        ).fetchone()
        assert row is not None
        return str(row[0]), row[1], row[2]

    def expense_of(self, request_id: UUID) -> UUID:
        return UUID(
            str(
                self.scalar(
                    "SELECT id FROM app.gl_expenses WHERE expense_request_id = %s",
                    (request_id,),
                )
            )
        )

    def owner_money_in(self, code: str, cents: int) -> None:
        self.call(
            "gl_record_owner_money",
            self.property_id,
            self.owner,
            "IN",
            self.today,
            code,
            cents,
            "Start money",
        )

    def submit(
        self,
        actor: UUID,
        cents: int,
        paid_how: str,
        *,
        kind: str = "REQUEST",
        paid_from: str | None = None,
        supplier: UUID | None = None,
        spent_on: date | None = None,
    ) -> UUID:
        return UUID(
            str(
                self.call(
                    "gl_submit_expense_request",
                    self.property_id,
                    actor,
                    kind,
                    "6050",
                    "Pipe repair, Unit 2",
                    "The pipe leaks",
                    cents,
                    "USD",
                    None,
                    None,
                    supplier,
                    None,
                    spent_on,
                    paid_how,
                    paid_from,
                )
            )
        )

    def rate(self) -> UUID:
        """A riel rate of 4,083 riel to the dollar."""
        rate_id = uuid4()
        self.connection.execute(
            "INSERT INTO app.exchange_rate_records (id, reference_rate_khr_per_usd, "
            "markup_basis_points, system_rate_khr_per_usd, rate_source, source_reference, "
            "applicable_at, entered_by, calculation_trace) VALUES (%s, 4062.500000, 50, 4083, "
            "'ABA_EQUIVALENT_MANUAL', 'Ledger test', statement_timestamp(), %s, %s)",
            (rate_id, self.owner, Jsonb({"system_rate_khr_per_usd": 4083})),
        )
        return rate_id


@pytest.fixture
def books(migrated_database_url: str) -> Iterator[Books]:
    with psycopg.connect(migrated_database_url) as connection:
        existing = connection.execute("SELECT id FROM app.properties").fetchone()
        if existing:
            property_id = UUID(str(existing[0]))
        else:
            property_id = insert_property(connection, insert_actor(connection))
        yield Books(connection, property_id)
        connection.rollback()


def test_an_advance_returns_its_change_or_owes_the_staff_the_extra(books: Books) -> None:
    books.owner_money_in("1010", 100_000)
    request = books.submit(books.staff, 5_000, "ADVANCE")
    assert books.request(request) == ("WAITING", None, None)
    # Staff cannot approve, and nobody approves their own.
    books.refused("42501", "gl_decide_expense_request", request, books.staff, True, None)
    mine = books.submit(books.manager, 1_000, "ADVANCE")
    books.refused(
        "42501",
        "gl_decide_expense_request",
        mine,
        books.manager,
        True,
        None,
        match="their own",
    )
    books.refused("55000", "gl_give_advance", request, books.manager, "1010", books.today)
    books.call("gl_decide_expense_request", request, books.manager, True, None)
    assert books.request(request)[0] == "APPROVED"
    books.refused("55000", "gl_decide_expense_request", request, books.owner, True, None)
    books.refused("42501", "gl_give_advance", request, books.staff, "1010", books.today)
    books.call("gl_give_advance", request, books.manager, "1010", books.today)
    assert books.request(request)[0] == "PAID_OUT"
    assert books.lines(f"expense_request:{request}:advance") == [
        ("1400", 5_000, 0),
        ("1010", 0, 5_000),
    ]
    # $40 spent of the $50 advance: the $10 change goes back to the cash it came from.
    expense = books.call(
        "gl_record_request_bill", request, books.manager, 4_000, books.today, "INV-7", None, None
    )
    assert books.request(request)[0] == "DONE"
    assert books.lines(f"expense:{expense}") == [
        ("6050", 4_000, 0),
        ("1400", 0, 5_000),
        ("1010", 1_000, 0),
    ]
    assert books.balance("1400") == 0
    books.refused("55000", "gl_pay_back_staff", request, books.manager, "1010", books.today)

    # $60 spent of a $50 advance: the staff is owed $10 until paid back once.
    second = books.submit(books.staff, 5_000, "ADVANCE")
    books.call("gl_decide_expense_request", second, books.manager, True, None)
    books.call("gl_give_advance", second, books.manager, "1010", books.today)
    expense = books.call(
        "gl_record_request_bill", second, books.manager, 6_000, books.today, None, None, None
    )
    assert books.lines(f"expense:{expense}") == [
        ("6050", 6_000, 0),
        ("1400", 0, 5_000),
        ("2310", 0, 1_000),
    ]
    payback = books.call("gl_pay_back_staff", second, books.manager, "1010", books.today)
    assert books.lines(f"staff_payback:{payback}") == [("2310", 1_000, 0), ("1010", 0, 1_000)]
    assert books.balance("2310") == 0
    books.refused(
        "55000",
        "gl_pay_back_staff",
        second,
        books.manager,
        "1010",
        books.today,
        match="Nothing is owed",
    )
    assert books.balance("1010") == 100_000 - 4_000 - 6_000
    with pytest.raises(psycopg.Error) as caught:
        with books.connection.transaction():
            books.connection.execute("UPDATE app.gl_staff_paybacks SET amount_cents = 1")
    assert caught.value.sqlstate == "55000"


def test_the_expense_limit_and_the_owners_own_spending(books: Books) -> None:
    big = books.submit(books.staff, 15_000, "CASH", paid_from="1020")
    books.refused(
        "42501",
        "gl_decide_expense_request",
        big,
        books.manager,
        True,
        None,
        match="expenses.approve_over_limit",
    )
    # The Manager may still refuse it, with a reason.
    books.refused("22023", "gl_decide_expense_request", big, books.manager, False, " ")
    books.call("gl_decide_expense_request", big, books.manager, False, "Too much this month")
    assert books.request(big)[0] == "REFUSED"
    again = books.submit(books.staff, 15_000, "CASH", paid_from="1020")
    books.call("gl_decide_expense_request", again, books.owner, True, None)
    assert books.request(again)[:1] == ("APPROVED",)
    # The bill may not be more than what was approved without an advance.
    books.refused(
        "22023",
        "gl_record_request_bill",
        again,
        books.manager,
        15_001,
        books.today,
        None,
        None,
        None,
    )
    expense = books.call(
        "gl_record_request_bill", again, books.manager, 15_000, books.today, None, None, None
    )
    assert books.lines(f"expense:{expense}") == [("6050", 15_000, 0), ("1020", 0, 15_000)]

    # D4: the Owner's own request is approved at once, kept with a note.
    own = books.submit(
        books.owner,
        30_000,
        "PAY_LATER",
        supplier=books.call(
            "gl_add_supplier", books.property_id, books.owner, "Sok Hardware", None, None
        ),
    )
    assert books.request(own) == ("APPROVED", "Owner's own spending", books.owner)
    # The Owner's own urgent report, paid with the Owner's own money, posts at once.
    report = books.submit(
        books.owner, 2_500, "OWN_MONEY", kind="URGENT_REPORT", spent_on=books.today
    )
    assert books.request(report) == ("DONE", "Owner's own spending", books.owner)
    assert books.lines(f"expense:{books.expense_of(report)}") == [
        ("6050", 2_500, 0),
        ("2310", 0, 2_500),
    ]


def test_an_urgent_report_from_petty_cash_posts_when_approved(books: Books) -> None:
    books.owner_money_in("1010", 50_000)
    books.call(
        "gl_top_up_petty_cash", books.property_id, books.manager, books.today, "1010", 20_000
    )
    for wrong in (
        {"kind": "URGENT_REPORT", "paid_from": "1010", "spent_on": books.today},
        {"kind": "URGENT_REPORT", "paid_from": "1030", "spent_on": books.today + timedelta(1)},
        {"kind": "URGENT_REPORT", "paid_from": "1030", "spent_on": None},
    ):
        with pytest.raises(psycopg.Error) as caught:
            with books.connection.transaction():
                books.submit(books.staff, 1_500, "CASH", **wrong)
        assert caught.value.sqlstate == "22023", wrong
    with pytest.raises(psycopg.Error):
        with books.connection.transaction():
            books.submit(books.staff, 1_500, "ADVANCE", kind="URGENT_REPORT", spent_on=books.today)
    report = books.submit(
        books.staff, 1_500, "CASH", kind="URGENT_REPORT", paid_from="1030", spent_on=books.today
    )
    assert books.request(report)[0] == "WAITING"
    books.call("gl_decide_expense_request", report, books.manager, True, None)
    assert books.request(report)[0] == "DONE"
    assert books.lines(f"expense:{books.expense_of(report)}") == [
        ("6050", 1_500, 0),
        ("1030", 0, 1_500),
    ]
    # A waiting request is taken back by the person who sent it, or voided by an approver.
    waiting = books.submit(books.staff, 900, "PAY_LATER")
    books.refused("42501", "gl_void_expense_request", waiting, books.other_staff, "No")
    books.refused("22023", "gl_void_expense_request", waiting, books.staff, " ")
    books.call("gl_void_expense_request", waiting, books.staff, "Sent twice")
    assert books.request(waiting)[0] == "VOID"
    books.refused("55000", "gl_void_expense_request", report, books.manager, "Too late")


def test_a_supplier_bill_is_paid_in_part_or_full_and_voided_only_without_payments(
    books: Books,
) -> None:
    books.owner_money_in("1020", 100_000)
    supplier = books.call(
        "gl_add_supplier", books.property_id, books.staff, "Dara Plumbing", "012 345 678", None
    )
    request = books.submit(books.staff, 3_000, "PAY_LATER", supplier=supplier)
    books.call("gl_decide_expense_request", request, books.manager, True, None)
    expense = books.call(
        "gl_record_request_bill", request, books.manager, 3_000, books.today, "DP-55", None, None
    )
    assert books.lines(f"expense:{expense}") == [("6050", 3_000, 0), ("2010", 0, 3_000)]
    bill, due, status = books.connection.execute(
        "SELECT id, due_date, status FROM app.gl_supplier_bills WHERE expense_id = %s",
        (expense,),
    ).fetchone() or (None, None, None)
    assert (due, status) == (books.today + timedelta(30), "OPEN")
    books.refused("42501", "gl_pay_supplier_bill", bill, books.staff, "1020", books.today, 1_000)
    books.refused("22023", "gl_pay_supplier_bill", bill, books.owner, "1020", books.today, 3_001)
    first = books.call("gl_pay_supplier_bill", bill, books.owner, "1020", books.today, 1_000)
    assert books.lines(f"bill_payment:{first}") == [("2010", 1_000, 0), ("1020", 0, 1_000)]
    second = books.call("gl_pay_supplier_bill", bill, books.owner, "1020", books.today, 2_000)
    assert books.scalar("SELECT status FROM app.gl_supplier_bills WHERE id = %s", (bill,)) == (
        "PAID"
    )
    books.refused("55000", "gl_pay_supplier_bill", bill, books.owner, "1020", books.today, 1)
    books.refused("55000", "gl_void_expense", expense, books.owner, "Wrong bill")
    books.call("gl_reverse_bill_payment", second, books.owner, "Paid the wrong bill")
    assert books.scalar("SELECT status FROM app.gl_supplier_bills WHERE id = %s", (bill,)) == (
        "OPEN"
    )
    books.refused("55000", "gl_reverse_bill_payment", second, books.owner, "Again")
    books.call("gl_reverse_bill_payment", first, books.owner, "Paid the wrong bill")
    books.refused("22023", "gl_void_expense", expense, books.owner, " ")
    books.call("gl_void_expense", expense, books.owner, "Wrong bill")
    assert books.scalar("SELECT status FROM app.gl_supplier_bills WHERE id = %s", (bill,)) == (
        "VOID"
    )
    assert books.lines(f"expense:{expense}:void") == [("6050", 0, 3_000), ("2010", 3_000, 0)]
    assert books.balance("2010") == 0 and books.balance("6050") == 0
    books.refused("55000", "gl_void_expense", expense, books.owner, "Again")


def test_a_straight_expense_in_riel_and_a_pay_later_expense(books: Books) -> None:
    rate = books.rate()
    books.call(
        "gl_move_money",
        books.property_id,
        books.owner,
        books.today,
        "1010",
        "1011",
        10_000,
        10_000,
        408_300,
        rate,
        "Change dollars to riel",
    )
    books.refused(
        "42501",
        "gl_record_expense",
        books.property_id,
        books.staff,
        books.today,
        "6050",
        "Tap",
        1_000,
        "USD",
        None,
        None,
        "1010",
        None,
        None,
        None,
        None,
    )
    expense = books.call(
        "gl_record_expense",
        books.property_id,
        books.manager,
        books.today,
        "6050",
        "Tap washer",
        1_000,
        "KHR",
        40_830,
        rate,
        "1011",
        None,
        None,
        None,
        None,
    )
    assert books.lines(f"expense:{expense}") == [("6050", 1_000, 0), ("1011", 0, 1_000)]
    assert books.connection.execute(
        "SELECT line.original_currency, line.original_amount_minor FROM app.gl_journal_lines "
        "AS line JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id "
        "WHERE entry.posting_key = %s AND line.credit_cents > 0",
        (f"expense:{expense}",),
    ).fetchone() == ("KHR", 40_830)
    # Cash or bank, never the money owed accounts, and an expense goes to a spending account.
    for code in ("2010", "4010"):
        books.refused(
            "22023",
            "gl_record_expense",
            books.property_id,
            books.manager,
            books.today,
            code,
            "Tap",
            1_000,
            "USD",
            None,
            None,
            "1010",
            None,
            None,
            None,
            None,
        )
    # Pay later needs a supplier and the supplier bills right (Manager has it).
    books.refused(
        "22023",
        "gl_record_expense",
        books.property_id,
        books.manager,
        books.today,
        "6050",
        "Paint",
        2_000,
        "USD",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    supplier = books.call(
        "gl_add_supplier", books.property_id, books.owner, "Paint shop", None, None
    )
    later = books.call(
        "gl_record_expense",
        books.property_id,
        books.manager,
        books.today,
        "6050",
        "Paint",
        2_000,
        "USD",
        None,
        None,
        None,
        supplier,
        "PS-1",
        books.today + timedelta(7),
        None,
    )
    assert books.lines(f"expense:{later}") == [("6050", 2_000, 0), ("2010", 0, 2_000)]
    assert books.scalar(
        "SELECT due_date FROM app.gl_supplier_bills WHERE expense_id = %s", (later,)
    ) == books.today + timedelta(7)
    books.refused(
        "22023",
        "gl_record_expense",
        books.property_id,
        books.manager,
        books.today + timedelta(1),
        "6050",
        "Paint",
        2_000,
        "USD",
        None,
        None,
        "1010",
        None,
        None,
        None,
        None,
    )
    books.call("gl_void_expense", expense, books.manager, "Counted twice")
    assert books.lines(f"expense:{expense}:void") == [("6050", 0, 1_000), ("1011", 1_000, 0)]


def test_money_moves_owner_money_and_the_petty_cash_amount(books: Books) -> None:
    books.owner_money_in("1010", 60_000)
    assert books.balance("3000") == -60_000
    books.refused(
        "42501",
        "gl_record_owner_money",
        books.property_id,
        books.manager,
        "IN",
        books.today,
        "1010",
        100,
        None,
    )
    out = books.call(
        "gl_record_owner_money",
        books.property_id,
        books.owner,
        "OUT",
        books.today,
        "1010",
        5_000,
        "For the family",
    )
    assert books.lines(f"owner_money:{out}") == [("3100", 5_000, 0), ("1010", 0, 5_000)]
    move = books.call(
        "gl_move_money",
        books.property_id,
        books.manager,
        books.today,
        "1010",
        "1020",
        10_000,
        None,
        None,
        None,
        "To the bank",
    )
    assert books.lines(f"money_move:{move}") == [("1020", 10_000, 0), ("1010", 0, 10_000)]
    # $100 changed to riel came back as 9,990 cents: the 10 cents go to 4100.
    rate = books.rate()
    riel = books.call(
        "gl_move_money",
        books.property_id,
        books.manager,
        books.today,
        "1010",
        "1011",
        10_000,
        9_990,
        407_892,
        rate,
        None,
    )
    assert books.lines(f"money_move:{riel}") == [
        ("1011", 9_990, 0),
        ("1010", 0, 10_000),
        ("4100", 10, 0),
    ]
    for wrong in (
        ("1010", "1010", 100, None, None, None),
        ("1010", "1020", 100, 90, None, None),
        ("1010", "1020", 100, None, 400_000, rate),
        ("1010", "1011", 100, None, 400_000, None),
        ("1010", "1030", 100, None, None, None),
        ("1010", "2010", 100, None, None, None),
    ):
        books.refused(
            "22023", "gl_move_money", books.property_id, books.manager, books.today, *wrong, None
        )
    books.refused(
        "42501",
        "gl_move_money",
        books.property_id,
        books.staff,
        books.today,
        "1010",
        "1020",
        100,
        None,
        None,
        None,
        None,
    )
    # Petty cash is topped up to the Petty cash amount ($200) at most.
    books.refused(
        "42501", "gl_top_up_petty_cash", books.property_id, books.staff, books.today, "1010", 100
    )
    books.refused(
        "22023", "gl_top_up_petty_cash", books.property_id, books.manager, books.today, "1011", 100
    )
    books.call(
        "gl_top_up_petty_cash", books.property_id, books.manager, books.today, "1010", 15_000
    )
    books.refused(
        "22023",
        "gl_top_up_petty_cash",
        books.property_id,
        books.manager,
        books.today,
        "1020",
        5_001,
        match="15000 cents",
    )
    topup = books.call(
        "gl_top_up_petty_cash", books.property_id, books.manager, books.today, "1020", 5_000
    )
    assert books.lines(f"petty_cash_topup:{topup}") == [("1030", 5_000, 0), ("1020", 0, 5_000)]
    assert books.balance("1030") == 20_000


def test_a_cash_count_difference_needs_a_reason_and_goes_to_6180(books: Books) -> None:
    books.owner_money_in("1010", 30_000)
    books.call(
        "gl_top_up_petty_cash", books.property_id, books.manager, books.today, "1010", 20_000
    )
    same = books.call(
        "gl_count_cash",
        books.property_id,
        books.manager,
        "1030",
        books.today,
        20_000,
        None,
        None,
        None,
    )
    assert books.scalar(
        "SELECT difference_entry_id IS NULL FROM app.gl_cash_counts WHERE id = %s", (same,)
    )
    # One count per cash account each month.
    books.refused(
        "55000",
        "gl_count_cash",
        books.property_id,
        books.manager,
        "1030",
        books.today,
        20_000,
        None,
        None,
        None,
        match="already counted",
    )
    books.refused(
        "22023",
        "gl_count_cash",
        books.property_id,
        books.manager,
        "1010",
        books.today,
        9_500,
        None,
        None,
        " ",
        match="needs a reason",
    )
    short = books.call(
        "gl_count_cash",
        books.property_id,
        books.manager,
        "1010",
        books.today,
        9_500,
        None,
        None,
        "A note was torn",
    )
    assert books.lines(f"cash_count:{short}") == [("6180", 500, 0), ("1010", 0, 500)]
    # Riel cash is counted in riel at the rate: 40,830 riel = $10.00.
    rate = books.rate()
    books.refused(
        "22023",
        "gl_count_cash",
        books.property_id,
        books.manager,
        "1011",
        books.today,
        1_000,
        None,
        None,
        None,
    )
    over = books.call(
        "gl_count_cash",
        books.property_id,
        books.manager,
        "1011",
        books.today,
        None,
        40_830,
        rate,
        "Found in the drawer",
    )
    assert books.lines(f"cash_count:{over}") == [("1011", 1_000, 0), ("6180", 0, 1_000)]
    assert books.connection.execute(
        "SELECT counted_minor, book_minor, counted_riel FROM app.gl_cash_counts WHERE id = %s",
        (over,),
    ).fetchone() == (1_000, 0, 40_830)
    books.refused(
        "22023",
        "gl_count_cash",
        books.property_id,
        books.manager,
        "1020",
        books.today,
        0,
        None,
        None,
        None,
        match="bank",
    )
    books.refused(
        "42501",
        "gl_count_cash",
        books.property_id,
        books.staff,
        "1010",
        books.today,
        9_500,
        None,
        None,
        None,
    )


def test_a_record_in_a_closed_month_or_the_future_is_refused(books: Books) -> None:
    if books.today.month == 1:
        pytest.skip("No earlier month of this year to close")
    january = date(books.today.year, 1, 15)
    books.owner_money_in("1010", 1_000)
    period = books.scalar(
        "SELECT period.id FROM app.gl_periods AS period WHERE period.property_id = %s "
        "AND period.period_no = 1 AND %s BETWEEN period.starts_on AND period.ends_on",
        (books.property_id, january),
    )
    books.connection.execute(
        "SELECT app.gl_close_period(%s, %s, %s)",
        (period, books.owner, Jsonb({"books_check": True})),
    )
    books.refused(
        "55000",
        "gl_record_owner_money",
        books.property_id,
        books.owner,
        "IN",
        january,
        "1010",
        100,
        None,
        match="closed",
    )
    books.refused(
        "22023",
        "gl_record_owner_money",
        books.property_id,
        books.owner,
        "IN",
        books.today + timedelta(1),
        "1010",
        100,
        None,
        match="today or earlier",
    )


def test_the_runtime_login_writes_only_through_the_checked_functions(
    migrated_database_url: str,
) -> None:
    assert migrated_database_url
    with psycopg.connect(runtime_database_url()) as runtime:
        # Without the right the function refuses; the tables cannot be written straight.
        with pytest.raises(psycopg.Error) as caught:
            with runtime.transaction():
                runtime.execute(
                    "SELECT app.gl_record_owner_money(gen_random_uuid(), gen_random_uuid(), "
                    "'IN', current_date, '1010', 100, NULL, gen_random_uuid())"
                )
        assert caught.value.sqlstate == "42501"
        for query in (
            "INSERT INTO app.gl_staff_paybacks (id, property_id, expense_request_id, paid_on, "
            "from_account_id, amount_cents, entry_id, created_by) VALUES (gen_random_uuid(), "
            "gen_random_uuid(), gen_random_uuid(), current_date, gen_random_uuid(), 1, "
            "gen_random_uuid(), gen_random_uuid())",
            "SELECT app.gl_post_request_expense(gen_random_uuid(), gen_random_uuid(), 1, "
            "current_date, NULL, NULL, NULL, gen_random_uuid())",
            "SELECT app.gl_can(gen_random_uuid(), gen_random_uuid(), 'ledger.read')",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with runtime.transaction():
                    runtime.execute(query)
        runtime.rollback()


def test_the_migration_follows_auto_posting() -> None:
    script = ScriptDirectory.from_config(Config(str(Path(__file__).parents[1] / "alembic.ini")))
    found = script.get_revision("20270416_266")
    assert found is not None and found.down_revision == "20270415_265"


class Borrowed:
    """The test's open transaction, lent to the API flow inside a savepoint (no commit)."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.savepoint: Any = None

    def __enter__(self) -> Connection:
        self.savepoint = self.connection.transaction()
        self.savepoint.__enter__()
        return self.connection

    def __exit__(self, *error: Any) -> None:
        self.savepoint.__exit__(*error)


def test_the_api_flow_calls_each_function_and_reads_the_records(
    books: Books, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: Borrowed(books.connection))
    flow = PostgresLedgerMoneyFlow("postgresql://unused")
    prop, day = books.property_id, books.today.isoformat()

    def write(action: str, actor: UUID, target: UUID | None = None, **values: Any) -> UUID | None:
        fields = {name: values.get(name) for name in ACTIONS[action].fields}
        return flow.write(action, prop, str(actor), fields, target)

    write(
        "owner_money",
        books.owner,
        direction="IN",
        moved_on=day,
        account_code="1010",
        amount_cents=50_000,
    )
    supplier = write("add_supplier", books.staff, name="Dara Plumbing")
    request = write(
        "submit_request",
        books.staff,
        kind="REQUEST",
        account_code="6050",
        description="Pipe",
        reason="Leak",
        amount_cents=3_000,
        currency="USD",
        paid_how="ADVANCE",
    )
    assert request is not None
    with pytest.raises(LedgerMoneyRefused, match=r"expenses\.approve"):
        write("decide_request", books.staff, request, approve=True)
    write("decide_request", books.manager, request, approve=True)
    write("give_advance", books.manager, request, from_code="1010", paid_on=day)
    write(
        "record_bill", books.manager, request, spent_cents=3_500, spent_on=day, supplier_id=supplier
    )
    write("pay_back_staff", books.manager, request, from_code="1010", paid_on=day)
    later = write(
        "record_expense",
        books.manager,
        expense_date=day,
        account_code="6050",
        description="Paint",
        amount_cents=2_000,
        currency="USD",
        supplier_id=supplier,
    )
    [bill] = flow.rows("supplier-bills", prop)
    assert (bill["expense_id"], bill["still_to_pay_cents"]) == (str(later), 2_000)
    payment = write(
        "pay_bill", books.owner, UUID(bill["id"]), from_code="1010", paid_on=day, amount_cents=500
    )
    assert flow.rows("supplier-bills", prop)[0]["still_to_pay_cents"] == 1_500
    write("reverse_bill_payment", books.owner, payment, reason="Wrong amount")
    write("void_expense", books.manager, later, reason="Wrong supplier")
    write(
        "move_money",
        books.manager,
        moved_on=day,
        from_code="1010",
        to_code="1020",
        amount_cents=1_000,
    )
    write(
        "top_up_petty_cash", books.manager, topped_up_on=day, from_code="1010", amount_cents=5_000
    )
    write("count_cash", books.manager, account_code="1030", counted_on=day, counted_cents=5_000)
    with pytest.raises(LedgerMoneyConflict, match="already counted"):
        write("count_cash", books.manager, account_code="1030", counted_on=day, counted_cents=5_000)
    with pytest.raises(LedgerMoneyInvalid):
        write(
            "move_money",
            books.manager,
            moved_on=day,
            from_code="1010",
            to_code="1010",
            amount_cents=1,
        )
    with pytest.raises(LedgerMoneyNotFound):
        write("void_expense", books.manager, uuid4(), reason="No such expense")
    # An urgent report sent later than the report days is marked late.
    report = write(
        "submit_request",
        books.staff,
        kind="URGENT_REPORT",
        account_code="6050",
        description="Bulb",
        reason="Dark stairs",
        amount_cents=300,
        currency="USD",
        spent_on=books.today - timedelta(days=4),
        paid_how="OWN_MONEY",
    )
    rows = {row["id"]: row for row in flow.expense_requests(prop, requested_by=str(books.staff))}
    assert rows[str(request)]["status"] == "DONE"
    assert rows[str(request)]["owed_to_staff_cents"] == 0
    assert rows[str(report)]["is_late"] is True and rows[str(request)]["is_late"] is False
    assert flow.expense_requests(prop, requested_by=str(books.other_staff)) == ()
    expenses = flow.rows("expenses", prop)
    assert {row["status"] for row in expenses} == {"POSTED", "VOID"}
    assert [row["name"] for row in flow.rows("suppliers", prop)] == ["Dara Plumbing"]
