"""Salary loans and payroll on the real database (migration 20270501_301, PR-HR-020..033).

A loan is limited by the business rules and approved by someone other than the one who asked;
its pay-out writes 1210 up and cash down. The payroll list is made after the month ends, by
calendar days rounded half up, with the loan repayment; approval writes one payslip and one
ledger entry per person, Mark paid writes 2300 down, and the month closes only after approval.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import psycopg
import pytest

from test_hr_employees_migration import (
    HrDatabase,
    add_employee,
    make_hr_database,
    refused,
    run,
)
from test_move_in_migration import migrated_database_url as migrated_database_url

ADD_LOAN = "SELECT app.hr_add_loan(%s, %s::jsonb, %s, NULL)"
DECIDE = "SELECT app.hr_decide_loan(%s, %s, %s::jsonb, %s, NULL)"
PAY_OUT = "SELECT app.hr_pay_out_loan(%s, %s, %s, %s, NULL)"
LOANS = "SELECT app.hr_loans_read(%s, %s)"
MAKE = "SELECT app.hr_make_payroll(%s, %s, %s, NULL)"
STEP = "SELECT app.hr_payroll_step(%s, %s, %s, %s::jsonb, %s, NULL)"
READ = "SELECT app.hr_payroll_read(%s, %s, %s, NULL)"
PAY = "SELECT app.hr_pay_salary(%s, %s, %s::jsonb, %s, NULL)"
UNDO = "SELECT app.hr_reverse_salary_payment(%s, %s, %s, %s, NULL)"


def last_month(today: date) -> date:
    return (today.replace(day=1) - timedelta(days=1)).replace(day=1)


@pytest.fixture(scope="module")
def pay_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    for db in make_hr_database("prm_hr_pay"):
        with psycopg.connect(db.owner_url) as setup:
            for year in sorted({last_month(db.today).year, db.today.year}):
                setup.execute(
                    "SELECT app.gl_start_ledger(%s, %s::smallint, %s)",
                    (db.property_id, year, db.owner),
                )
            setup.commit()
        yield db


def salary(cents: int, method: str = "CASH_USD") -> dict[str, Any]:
    terms: dict[str, Any] = {"monthly_salary_usd_cents": cents, "payment_method": method}
    if method == "ABA":
        terms |= {"aba_account_name": "SAMPLE NAME", "aba_account_number": "000 123 456"}
    return terms


def call(db: HrDatabase, sql: str, *params: Any) -> Any:
    return run(db.runtime_url, sql, *params)


def step(db: HrDatabase, payroll: Any, name: str, actor: uuid.UUID, **body: Any) -> None:
    with psycopg.connect(db.runtime_url) as connection:
        connection.execute(STEP, (db.property_id, payroll, name, json.dumps(body), actor))


def entry_lines(db: HrDatabase, key: str) -> list[tuple[str, int, int]]:
    with psycopg.connect(db.owner_url) as connection:
        return [
            (str(row[0]), int(row[1]), int(row[2]))
            for row in connection.execute(
                "SELECT account.code, line.debit_cents, line.credit_cents "
                "FROM app.gl_journal_entries AS entry "
                "JOIN app.gl_journal_lines AS line ON line.entry_id = entry.id "
                "JOIN app.gl_accounts AS account ON account.id = line.account_id "
                "WHERE entry.posting_key = %s ORDER BY line.line_no",
                (key,),
            ).fetchall()
        ]


def test_loans_follow_the_rules(pay_database: HrDatabase) -> None:
    db = pay_database
    person = add_employee(db, name_en="Sample Loan", name_km="គំរូ កម្ចី", pay=salary(20000))
    loan = {
        "employee_id": str(person),
        "amount_usd_cents": 10001,
        "payout_method": "CASH_USD",
        "reason": "Family need",
    }
    message = refused(
        db.runtime_url, "22023", ADD_LOAN, db.property_id, json.dumps(loan), db.accountant
    )
    assert "$100.00" in message
    refused(db.runtime_url, "42501", ADD_LOAN, db.property_id, json.dumps(loan), db.manager)
    first = call(
        db, ADD_LOAN, db.property_id, json.dumps(loan | {"amount_usd_cents": 10000}), db.accountant
    )
    # One open loan per person (business rule LOAN_OPEN_MAX).
    refused(
        db.runtime_url,
        "55000",
        ADD_LOAN,
        db.property_id,
        json.dumps(loan | {"amount_usd_cents": 500}),
        db.accountant,
    )
    refused(
        db.runtime_url,
        "42501",
        DECIDE,
        db.property_id,
        first,
        json.dumps({"decision": "APPROVED"}),
        db.accountant,
    )
    with psycopg.connect(db.runtime_url) as connection:
        connection.execute(
            DECIDE, (db.property_id, first, json.dumps({"decision": "APPROVED"}), db.owner)
        )
    refused(
        db.runtime_url,
        "55000",
        DECIDE,
        db.property_id,
        first,
        json.dumps({"decision": "REFUSED", "reason": "x"}),
        db.owner,
    )
    entry = call(db, PAY_OUT, db.property_id, first, db.today, db.accountant)
    assert entry is not None
    assert entry_lines(db, f"salary_loan_payout:{first}:paid") == [
        ("1210", 10000, 0),
        ("1010", 0, 10000),
    ]
    listed = {item["loan_id"]: item for item in call(db, LOANS, db.property_id, db.owner)["loans"]}
    assert listed[str(first)]["state"] == "PAID_OUT"
    assert listed[str(first)]["owed_usd_cents"] == 10000
    # The Owner's own entry needs a note before the Owner approves it.
    other = add_employee(db, name_en="Sample Other", name_km="គំរូ ផ្សេង", pay=salary(30000))
    own = call(
        db,
        ADD_LOAN,
        db.property_id,
        json.dumps(loan | {"employee_id": str(other), "amount_usd_cents": 5000}),
        db.owner,
    )
    refused(
        db.runtime_url,
        "22023",
        DECIDE,
        db.property_id,
        own,
        json.dumps({"decision": "APPROVED"}),
        db.owner,
    )
    call_ok = json.dumps({"decision": "APPROVED", "own_request_note": "Accountant is away"})
    with psycopg.connect(db.runtime_url) as connection:
        connection.execute(DECIDE, (db.property_id, own, call_ok, db.owner))
    assert run(db.owner_url, "SELECT app.hr_loan_state(%s)", own) == "APPROVED"


def test_payroll_month_payslips_entries_and_pay(pay_database: HrDatabase) -> None:
    db = pay_database
    month = last_month(db.today)
    month_end = db.today.replace(day=1) - timedelta(days=1)
    days = month_end.day
    full = add_employee(db, name_en="Sample Full", name_km="គំរូ ពេញ", pay=salary(22500, "ABA"))
    starts = month.replace(day=10)
    part = add_employee(
        db, name_en="Sample Part", name_km="គំរូ ផ្នែក", start_date=str(starts), pay=salary(25000)
    )
    loan = call(
        db,
        ADD_LOAN,
        db.property_id,
        json.dumps(
            {
                "employee_id": str(full),
                "amount_usd_cents": 5000,
                "payout_method": "ABA_JOINT",
                "repayment_plan": "MONTHLY_AMOUNT",
                "monthly_repayment_usd_cents": 2000,
                "requested_on": str(month.replace(day=15)),
                "reason": "School fees",
            }
        ),
        db.accountant,
    )
    with psycopg.connect(db.runtime_url) as connection:
        connection.execute(
            DECIDE, (db.property_id, loan, json.dumps({"decision": "APPROVED"}), db.owner)
        )
    call(db, PAY_OUT, db.property_id, loan, month.replace(day=15), db.accountant)

    refused(db.runtime_url, "22023", MAKE, db.property_id, db.today.replace(day=1), db.accountant)
    payroll = call(db, MAKE, db.property_id, month, db.accountant)
    refused(db.runtime_url, "23505", MAKE, db.property_id, month, db.accountant)
    found = call(db, READ, db.property_id, payroll, db.owner)
    assert found["state"] == "LIST_MADE" and found["run_number"].startswith("PAY")
    people = {item["employee_id"]: item for item in found["people"]}
    worked = days - 10 + 1
    expected = int((Decimal(25000) * worked / days).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    part_lines = people[str(part)]["lines"]
    assert [
        (line["component"], line["amount_usd_cents"], line["days_worked"]) for line in part_lines
    ] == [("BASE_SALARY", expected, worked)]
    assert [
        (line["component"], line["amount_usd_cents"]) for line in people[str(full)]["lines"]
    ] == [
        ("BASE_SALARY", 22500),
        ("LOAN_REPAYMENT", 2000),
    ]
    refused(db.runtime_url, "42501", STEP, db.property_id, payroll, "ADD_LINE", "{}", db.manager)
    step(
        db,
        payroll,
        "ADD_LINE",
        db.accountant,
        employee_id=str(part),
        component="BONUS",
        amount_usd_cents=1500,
        reason="Extra cleaning",
    )
    step(db, payroll, "SEND", db.accountant)
    refused(
        db.runtime_url,
        "55000",
        STEP,
        db.property_id,
        payroll,
        "ADD_LINE",
        json.dumps(
            {"employee_id": str(part), "component": "BONUS", "amount_usd_cents": 1, "reason": "x"}
        ),
        db.accountant,
    )
    refused(db.runtime_url, "42501", STEP, db.property_id, payroll, "APPROVE", "{}", db.accountant)
    # The month cannot close before its payroll is approved.
    period = run(
        db.owner_url,
        "SELECT id FROM app.gl_periods "
        "WHERE property_id = %s AND starts_on = %s AND period_no <= 12",
        db.property_id,
        month,
    )
    check = "SELECT ok FROM app.gl_month_close_checks(%s) WHERE check_code = 'PAYROLL_APPROVED'"
    assert run(db.owner_url, check, period) is False
    step(db, payroll, "APPROVE", db.owner)
    assert run(db.owner_url, check, period) is True
    found = call(db, READ, db.property_id, payroll, db.owner)
    assert found["state"] == "APPROVED"
    people = {item["employee_id"]: item for item in found["people"]}
    slip = people[str(full)]["payslip"]
    assert (
        slip["earnings_usd_cents"],
        slip["deductions_usd_cents"],
        slip["net_pay_usd_cents"],
    ) == (
        22500,
        2000,
        20500,
    )
    assert entry_lines(db, f"payslip:{slip['payslip_id']}:approved") == [
        ("6030", 22500, 0),
        ("1210", 0, 2000),
        ("2300", 0, 20500),
    ]
    assert run(db.owner_url, "SELECT app.hr_loan_repaid(%s)", loan) == 2000
    # Mark paid, reverse a mistake, and mark paid again.
    payment = call(
        db,
        PAY,
        db.property_id,
        slip["payslip_id"],
        json.dumps({"bank_reference": "ABA 778899"}),
        db.owner,
    )
    assert entry_lines(db, f"salary_payment:{payment}:paid") == [
        ("2300", 20500, 0),
        ("1020", 0, 20500),
    ]
    refused(db.runtime_url, "55000", PAY, db.property_id, slip["payslip_id"], "{}", db.owner)
    refused(db.runtime_url, "42501", PAY, db.property_id, slip["payslip_id"], "{}", db.accountant)
    call(db, UNDO, db.property_id, payment, "Sent to the wrong account", db.owner)
    assert entry_lines(db, f"salary_payment_reversal:{payment}") == [
        ("2300", 0, 20500),
        ("1020", 20500, 0),
    ]
    again = call(
        db, PAY, db.property_id, slip["payslip_id"], json.dumps({"method": "CASH_USD"}), db.owner
    )
    assert entry_lines(db, f"salary_payment:{again}:paid")[1] == ("1010", 0, 20500)
    with psycopg.connect(db.owner_url) as connection:
        for table in ("payslips", "payroll_lines", "salary_payments"):
            with pytest.raises(psycopg.Error) as caught:
                connection.execute(f"DELETE FROM app.{table}")
            assert caught.value.sqlstate == "55000"
            connection.rollback()

    # A mistake after approval goes into a correction payroll.
    correction = call(
        db,
        "SELECT app.hr_make_correction(%s, %s, %s, %s, NULL)",
        db.property_id,
        payroll,
        "Missed bonus",
        db.accountant,
    )
    step(
        db,
        correction,
        "ADD_LINE",
        db.accountant,
        employee_id=str(full),
        component="BONUS",
        amount_usd_cents=1000,
        reason="Missed bonus",
    )
    step(db, correction, "SEND", db.accountant)
    step(db, correction, "APPROVE", db.owner)
    fixed = call(db, READ, db.property_id, correction, db.owner)
    assert fixed["run_kind"] == "CORRECTION"
    assert [
        (item["employee_id"], item["payslip"]["net_pay_usd_cents"]) for item in fixed["people"]
    ] == [(str(full), 1000)]
    runs = call(db, "SELECT app.hr_payrolls_read(%s, %s)", db.property_id, db.accountant)["runs"]
    assert {item["run_id"] for item in runs} >= {str(payroll), str(correction)}
