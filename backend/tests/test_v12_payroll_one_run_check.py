"""Database review of 7 Nov 2026 (DL-202 (A)): one REGULAR payroll run per month and Property.

The afternoon review said the rule lived only in ``hr_make_payroll``. That was wrong: migration
20270501_301 already keeps it with the unique index ``payroll_runs_one_regular``. These tests
prove the guard the owner asked for (two clicks at once, a second run from the owner login) so
the question does not come back; no new migration is needed.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import date, timedelta

import psycopg
import pytest

from test_hr_employees_migration import HrDatabase, add_employee, make_hr_database, run
from test_move_in_migration import migrated_database_url as migrated_database_url

MAKE = "SELECT app.hr_make_payroll(%s, %s, %s, NULL)"
RUNS = (
    "SELECT count(*) FROM app.payroll_runs WHERE property_id = %s AND salary_month = %s "
    "AND run_kind = %s"
)
REGULAR = (
    "SELECT id FROM app.payroll_runs WHERE property_id = %s AND salary_month = %s "
    "AND run_kind = 'REGULAR'"
)
INSERT = (
    "INSERT INTO app.payroll_runs (property_id, run_number, salary_month, run_kind, pay_date, "
    "corrects_run_id, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s)"
)


@pytest.fixture(scope="module")
def pay_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_v12_payroll")


def last_month(today: date) -> date:
    return (today.replace(day=1) - timedelta(days=1)).replace(day=1)


def test_two_payroll_clicks_at_once_make_one_run(pay_database: HrDatabase) -> None:
    db = pay_database
    month = last_month(db.today)
    add_employee(
        db,
        name_en="Sample One",
        name_km="គំរូ មួយ",
        pay={"monthly_salary_usd_cents": 22500, "payment_method": "CASH_USD"},
    )
    outcomes: list[str] = []
    ready = threading.Barrier(2)

    def click() -> None:
        try:
            with psycopg.connect(db.runtime_url) as connection:
                ready.wait()
                connection.execute(MAKE, (db.property_id, month, db.accountant))
                connection.commit()
            outcomes.append("made")
        except psycopg.Error as error:
            outcomes.append(str(error.sqlstate))

    clicks = [threading.Thread(target=click) for _ in range(2)]
    for thread in clicks:
        thread.start()
    for thread in clicks:
        thread.join()
    assert sorted(outcomes) == ["23505", "made"]
    assert run(db.owner_url, RUNS, db.property_id, month, "REGULAR") == 1


def test_the_database_refuses_a_second_regular_run_even_from_the_owner_login(
    pay_database: HrDatabase,
) -> None:
    db = pay_database
    month = last_month(db.today)
    if run(db.owner_url, RUNS, db.property_id, month, "REGULAR") == 0:
        run(db.runtime_url, MAKE, db.property_id, month, db.accountant)
    regular = run(db.owner_url, REGULAR, db.property_id, month)
    pay_day = month + timedelta(days=40)
    with psycopg.connect(db.owner_url) as owner:
        with pytest.raises(psycopg.errors.UniqueViolation):
            owner.execute(
                INSERT, (db.property_id, "PAY999001", month, "REGULAR", pay_day, None, db.owner)
            )
    assert run(db.owner_url, RUNS, db.property_id, month, "REGULAR") == 1
    # A CORRECTION run of the same month is another kind and is allowed on top.
    with psycopg.connect(db.owner_url) as owner:
        owner.execute(
            INSERT, (db.property_id, "PAY999002", month, "CORRECTION", pay_day, regular, db.owner)
        )
        owner.commit()
    assert run(db.owner_url, RUNS, db.property_id, month, "CORRECTION") == 1
