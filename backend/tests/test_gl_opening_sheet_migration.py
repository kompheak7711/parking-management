"""Opening balances read for the ledger screen on the real database (phase 6 step 6, lopen).

Before the books start, the read answers the ledger's first year and the accounts the Owner may
type; once started, the typed lines with their notes and the control lines the app works out;
once posted, the entry's lines, who posted it and when. Read with the runtime login's rights.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from property_rental.ledger_close_api import VIEWS as CLOSE_VIEWS
from property_rental.ledger_money_api import LedgerMoneyNotFound
from property_rental.ledger_opening_api import (
    ACCOUNTS,
    FIRST_YEAR,
    NEEDS_CHECK,
    OPENING,
    POSTED,
    TYPED,
    WORKED_OUT,
    PostgresLedgerOpening,
)
from property_rental.ledger_posting_api import (
    METHOD_ACCOUNTS,
    PostgresLedgerPostingFlow,
)
from property_rental.ledger_posting_api import NEEDS_CHECK as NEEDS_CHECK_LIST
from test_gl_auto_posting_migration import (
    SET_ACCOUNT,
    invoice_paid,
    lines,
    method_of,
    post,
    problem,
)
from test_gl_close_migration import capital, worked_out_net
from test_gl_money_records_migration import Books, Borrowed
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_unit_migration import insert_actor, insert_property


@pytest.fixture
def fresh(migrated_database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Books]:
    """A new Property with no ledger yet, lent to the read inside a savepoint."""
    with psycopg.connect(migrated_database_url) as connection:
        # The Property is a singleton: earlier suites may have kept theirs.
        existing = connection.execute("SELECT id FROM app.properties").fetchone()
        if existing is None:
            property_id = insert_property(connection, insert_actor(connection))
        else:
            property_id = UUID(str(existing[0]))
            started = connection.execute(
                "SELECT 1 FROM app.gl_fiscal_years WHERE property_id = %s", (property_id,)
            ).fetchone()
            if started is not None:
                pytest.skip("The kept Property already has a ledger")
        books = Books(connection, property_id, start=False)
        monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: Borrowed(connection))
        yield books
        connection.rollback()


def test_the_opening_sheet_follows_the_books_from_start_to_posted(fresh: Books) -> None:
    flow = PostgresLedgerOpening("postgresql://unused")
    before = flow.sheet(fresh.property_id)
    assert before["today"] == fresh.today.isoformat()
    assert before["first_year"] is None and before["opening"] is None
    assert before["typed"] == [] and before["worked_out"] == [] and before["posted"] == []

    # The books start next year, so no app record falls after their first day.
    year = fresh.today.year + 1
    fresh.call("gl_begin_ledger", fresh.property_id, fresh.owner, year)
    started = flow.sheet(fresh.property_id)
    assert started["first_year"] == year
    assert started["opening"]["status"] == "DRAFT"
    assert started["opening"]["start_date"] == f"{year}-01-01"
    assert started["opening"]["entry_number"] is None
    codes = {account["code"] for account in started["accounts"]}
    # Control accounts are worked out by the app; tax accounts take no postings.
    assert {"1010", "1520", "3000"} <= codes
    assert not {"1100", "2200"} & codes
    assert all(account["normal_side"] in {"DEBIT", "CREDIT"} for account in started["accounts"])

    worked = worked_out_net(fresh)
    typed = [{"account": "1010", "debit_cents": 50_000, "memo": "Office cash"}]
    typed += [
        {"account": code, "debit_cents": debit or None, "credit_cents": credit or None}
        for code, debit, credit in capital(50_000 + worked)
    ]
    fresh.call("gl_set_opening_lines", fresh.property_id, fresh.owner, Jsonb(typed))
    draft = flow.sheet(fresh.property_id)
    cash = draft["typed"][0]
    assert cash["account_code"] == "1010" and cash["account_name"]
    assert cash["debit_cents"] == 50_000 and cash["credit_cents"] == 0
    assert cash["memo"] == "Office cash"
    assert all(type(line["debit_cents"]) is int for line in draft["typed"])
    assert all("memo" not in line for line in draft["worked_out"])
    net = sum(line["debit_cents"] - line["credit_cents"] for line in draft["worked_out"])
    assert net == worked

    fresh.call("gl_post_opening_balances", fresh.property_id, fresh.owner)
    posted = flow.sheet(fresh.property_id)
    assert posted["opening"]["status"] == "POSTED"
    assert posted["opening"]["entry_number"]
    assert posted["opening"]["posted_at"] is not None
    assert posted["typed"] == [] and posted["worked_out"] == []
    assert sum(line["debit_cents"] for line in posted["posted"]) == sum(
        line["credit_cents"] for line in posted["posted"]
    )
    assert any(
        line["account_code"] == "1010" and line["debit_cents"] == 50_000
        for line in posted["posted"]
    )
    assert posted["needs_check"] == 0


__all__ = ["invoice_paid"]


def test_records_the_posting_job_has_not_met_keep_post_closed_and_show_in_needs_check(
    invoice_paid: tuple[psycopg.Connection[Any], UUID, UUID, UUID, UUID, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Owner test 04/11/2026: Post said "Clear the Needs check list first" while the screen
    showed nothing waiting, because the posting job had not run since the books started."""
    connection, prop, human, _, payment, _ = invoice_paid
    key = f"payment:{payment}"
    connection.execute(
        "INSERT INTO app.gl_opening_balances (id, property_id, start_date, status, created_by) "
        "VALUES (gen_random_uuid(), %s, DATE '2026-01-01', 'DRAFT', %s)",
        (prop, human),
    )
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: Borrowed(connection))
    opening = PostgresLedgerOpening("postgresql://unused")
    needs = PostgresLedgerPostingFlow("postgresql://unused")
    # The Payment Method has no ledger account and the posting job has not run: nothing is kept.
    assert problem(connection, key) is None
    waiting = {row.posting_key: row for row in needs.needs_check(prop)}
    assert "No ledger account is set for the Payment Method" in waiting[key].problem
    assert waiting[key].source_link == {"page": "payments", "detail": f"receipt:{payment}"}
    assert opening.sheet(prop)["needs_check"] == len(waiting) > 0
    owner = Books(connection, prop, start=False).owner
    with pytest.raises(psycopg.Error, match="Clear the Needs check list first"):
        with connection.transaction():
            connection.execute(
                "SELECT app.gl_post_opening_balances(%s, %s, gen_random_uuid())", (prop, owner)
            )
    # Once the method has its account the record can post, so it no longer waits.
    connection.execute(SET_ACCOUNT, (prop, method_of(connection, payment), None, "1010", human))
    # Owner card 04/11/2026 12:12: a second save from the same day wins; both rows stay.
    needs.set_method_account(
        prop,
        kind="PAYMENT",
        method_id=method_of(connection, payment),
        account_code="1020",
        effective_from=date(2026, 1, 1),
        actor_id=str(human),
    )
    method = method_of(connection, payment)
    assert [
        row.account_code
        for row in needs.method_accounts(prop)
        if row.kind == "PAYMENT" and row.method_id == method
    ] == ["1020"]
    saved = connection.execute(
        "SELECT count(*) FROM app.gl_method_accounts WHERE payment_method_id = %s", (method,)
    ).fetchone()
    assert saved == (2,)
    post(connection, prop, human)
    assert ("1020", 30000, 0) in lines(connection, key)
    waiting = {row.posting_key: row for row in needs.needs_check(prop)}
    assert key not in waiting
    assert opening.sheet(prop)["needs_check"] == len(waiting)


def test_the_runtime_login_can_run_the_opening_read(migrated_database_url: str) -> None:
    assert migrated_database_url
    with pytest.raises(LedgerMoneyNotFound):
        PostgresLedgerOpening(runtime_database_url()).sheet(uuid4())
    with psycopg.connect(runtime_database_url()) as connection:
        key = {"prop": uuid4(), "opening": uuid4(), "entry": uuid4()}
        for query in (FIRST_YEAR, OPENING, ACCOUNTS, TYPED, WORKED_OUT, POSTED, NEEDS_CHECK):
            connection.execute(query, key)


def test_the_runtime_login_can_run_the_needs_check_reads(migrated_database_url: str) -> None:
    """Owner test 04/11/2026: Needs check failed for every Property, because the runtime login
    may not read app.refund_methods; both of its reads now go through functions."""
    assert migrated_database_url
    with psycopg.connect(runtime_database_url()) as connection:
        connection.execute(NEEDS_CHECK_LIST, (uuid4(),)).fetchall()
        methods = connection.execute(
            METHOD_ACCOUNTS, {"prop": uuid4(), "day": date(2026, 11, 4)}
        ).fetchall()
    kinds = {str(row[0]) for row in methods}
    assert "REFUND" in kinds
    assert all(row[4] is None and row[6] is None for row in methods)


def test_the_runtime_login_can_run_every_close_list(migrated_database_url: str) -> None:
    """The same check for the close lists: the write-off list read app.settlement_corrections,
    which the runtime login may not read; it now reads the Final Settlement through a function."""
    assert migrated_database_url
    with psycopg.connect(runtime_database_url()) as connection:
        for view, query in CLOSE_VIEWS.items():
            try:
                connection.execute(
                    query, {"prop": uuid4(), "target": uuid4(), "account": "1010"}
                ).fetchall()
            except psycopg.errors.InsufficientPrivilege as exc:  # pragma: no cover - failure path
                pytest.fail(f"{view}: {exc}")
