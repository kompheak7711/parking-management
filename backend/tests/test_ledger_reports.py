"""General Ledger reports (phase 6 step 5): the builders' totals and checks, and the route.

DESIGN.md round 22 (Financial statements) and gap G1 (Excel and PDF files with the period and
Closed or "Open, may still change"; the aging reports say "As at today").
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.ledger_money_api import LedgerMoneyInvalid, LedgerMoneyNotFound
from property_rental.ledger_reports import (
    OPEN,
    TODAY,
    LedgerReport,
    ReportName,
    ReportParams,
    account_detail,
    balance_sheet,
    bills_aging,
    budget_against_actual,
    cash_flow,
    customer_aging,
    month_end,
    months_back,
    profit_and_loss,
    trial_balance,
)


def by_name(report: LedgerReport) -> dict[str, dict[str, object]]:
    return {str(row["name"]): row for row in report.rows if row.get("name")}


def test_the_trial_balance_totals_both_sides_and_says_when_they_differ() -> None:
    good = trial_balance(
        [("1010", "Cash", 50_000, 0), ("4010", "Rent", 0, 50_000)], period="As at", state=OPEN
    )
    assert good.rows[-1] == {
        "line": "total",
        "code": None,
        "name": "Total",
        "debit": 50_000,
        "credit": 50_000,
    }
    assert (good.check_ok, good.check_text) == (True, "Debits equal credits")
    bad = trial_balance([("1010", "Cash", 50_000, 0)], period="", state=OPEN)
    assert (bad.check_ok, bad.check_text) == (False, "Debits and credits differ by $500.00")


def test_profit_and_loss_has_the_five_columns_gross_profit_and_the_margins() -> None:
    report = profit_and_loss(
        {
            "this_month": [
                ("INCOME", "4010", "Rent", 100_000),
                ("INCOME", "4030", "Electricity billed", 20_000),
                ("COST_OF_SALES", "5010", "Cost of products sold", 3_000),
                ("EXPENSE", "6010", "Electricity bill", 15_000),
            ],
            "last_month": [("INCOME", "4010", "Rent", 90_000)],
            "same_month_last_year": [("INCOME", "4010", "Rent", 80_000)],
            "year_to_date": [
                ("INCOME", "4010", "Rent", 190_000),
                ("INCOME", "4030", "Electricity billed", 20_000),
                ("COST_OF_SALES", "5010", "Cost of products sold", 3_000),
                ("EXPENSE", "6010", "Electricity bill", 15_000),
            ],
        },
        book_profit=192_000,
        period="January 2027",
        state=OPEN,
    )
    rows = by_name(report)
    assert rows["Rent"] == {
        "line": "account",
        "code": "4010",
        "name": "Rent",
        "this_month": 100_000,
        "last_month": 90_000,
        "same_month_last_year": 80_000,
        "year_to_date": 190_000,
        "difference": 10_000,
    }
    assert rows["Gross profit"]["this_month"] == 117_000
    assert rows["Profit (or loss)"]["this_month"] == 102_000
    assert rows["Profit (or loss)"]["year_to_date"] == 192_000
    assert rows["Margin: electricity (4030 less 6010)"]["this_month"] == 5_000
    assert rows["Margin: products (4080 less 5010)"]["this_month"] == -3_000
    assert (report.check_ok, report.check_text) == (
        True,
        "Profit this year matches the Balance sheet",
    )
    assert [column.key for column in report.columns][2:] == [
        "this_month",
        "last_month",
        "same_month_last_year",
        "year_to_date",
        "difference",
    ]
    closed = profit_and_loss({}, book_profit=None, period="", state=OPEN)
    assert closed.check_ok and "3900" in closed.check_text
    off = profit_and_loss({}, book_profit=100, period="", state=OPEN)
    assert (off.check_ok, off.check_text) == (
        False,
        "Profit this year and the Balance sheet differ by $1.00",
    )


def test_the_balance_sheet_groups_and_adds_profit_this_year_so_it_balances() -> None:
    report = balance_sheet(
        [
            ("1010", "Cash", "ASSET", "CURRENT", 120_000, 20_000),
            ("1520", "Furniture", "ASSET", "NON_CURRENT", 60_000, 0),
            ("1590", "Accumulated depreciation", "ASSET", "NON_CURRENT", 0, 1_000),
            ("2100", "Security Deposits held", "LIABILITY", "CURRENT", 0, 50_000),
            ("3000", "Owner's capital", "EQUITY", None, 0, 60_000),
            ("4010", "Rent", "INCOME", None, 0, 50_000),
            ("6140", "Depreciation", "EXPENSE", None, 1_000, 0),
        ],
        period="As at",
        state=OPEN,
    )
    rows = by_name(report)
    assert rows["Accumulated depreciation"]["amount"] == -1_000
    assert rows["Total building and equipment after depreciation"]["amount"] == 59_000
    assert rows["Profit this year not closed yet"]["amount"] == 49_000
    assert rows["Total assets"]["amount"] == 159_000
    assert rows["Owed plus Owner's equity"]["amount"] == 159_000
    assert report.check_ok
    assert report.extra == {"profit_this_year_cents": 49_000}
    assert [row["name"] for row in report.rows if row["line"] == "heading"] == [
        "Assets within 12 months",
        "Building and equipment after depreciation",
        "Owed within 12 months",
        "Owner's equity",
    ]


def test_cash_flow_runs_from_cash_at_start_to_cash_at_end() -> None:
    flows = [
        ("OPERATING", "1100", "Customer debt", 70_000),
        ("OPERATING", "6050", "Repairs", -5_000),
        ("INVESTING", "1530", "Office equipment", -60_000),
        ("FINANCING", "3000", "Owner's capital", 100_000),
    ]
    report = cash_flow(10_000, flows, 115_000, period="", state=OPEN)
    rows = by_name(report)
    assert rows["Total daily business"]["amount"] == 65_000
    assert rows["Total equipment"]["amount"] == -60_000
    assert rows["Total owner money and loans"]["amount"] == 100_000
    assert rows["Change in cash"]["amount"] == 105_000
    assert report.check_ok
    wrong = cash_flow(10_000, flows, 100_000, period="", state=OPEN)
    assert wrong.check_text.endswith("differ by $150.00")


def test_account_detail_ends_on_the_account_balance() -> None:
    lines = [
        (None, date(2027, 1, 1), "Opening balance", None, 0, 0, 10_000),
        ("JE270001", date(2027, 1, 5), "Rent received", None, 80_000, 0, 90_000),
        ("JE270002", date(2027, 1, 9), "Bank fee", "ABA", 0, 500, 89_500),
    ]
    report = account_detail("1020", "ABA Bank", lines, 89_500, period="", state=OPEN)
    assert report.title == "Account detail: 1020 ABA Bank"
    assert report.rows[0]["line"] == "total"
    assert report.rows[2]["debit"] is None and report.rows[2]["credit"] == 500
    assert report.check_ok
    assert not account_detail("1020", "ABA", lines, 1, period="", state=OPEN).check_ok


def test_aging_puts_each_debt_in_its_group_as_at_today() -> None:
    today = date(2027, 5, 31)
    report = customer_aging(
        [
            ("Sok Dara", "101", date(2027, 6, 5), 80_000),
            ("Sok Dara", "101", date(2027, 5, 31), 1_000),
            ("Sok Dara", "101", date(2027, 5, 30), 2_000),
            ("Chan Lina", "202", date(2027, 4, 1), 3_000),
            ("Chan Lina", "202", date(2027, 3, 15), 4_000),
            ("Chan Lina", "202", date(2027, 1, 31), 5_000),
            ("Keo Visal", None, None, 600),
        ],
        today,
        95_600,
    )
    rows = {(row["customer_name"], row["unit_number"]): row for row in report.rows}
    assert rows[("Sok Dara", "101")] | {"line": "account"} == {
        "line": "account",
        "customer_name": "Sok Dara",
        "unit_number": "101",
        "not_due": 81_000,
        "days_1_30": 2_000,
        "days_31_60": 0,
        "days_61_90": 0,
        "over_90": 0,
        "total": 83_000,
    }
    lina = rows[("Chan Lina", "202")]
    assert (lina["days_31_60"], lina["days_61_90"], lina["over_90"]) == (3_000, 4_000, 5_000)
    assert rows[("Total", None)]["total"] == 95_600
    assert (report.state, report.check_ok) == (TODAY, True)
    assert report.period == "As at today, 31/05/2027"
    assert not customer_aging([], today, 1).check_ok


def test_supplier_bill_aging_adds_staff_advances_and_money_owed_to_staff() -> None:
    report = bills_aging(
        [("Dara Plumbing", date(2027, 5, 1), 2_500), ("EDC", date(2027, 6, 30), 9_000)],
        date(2027, 5, 31),
        11_500,
        3_000,
        700,
    )
    rows = by_name(report) | {str(row["supplier"]): row for row in report.rows}
    assert rows["Dara Plumbing"]["days_1_30"] == 2_500
    assert rows["EDC"]["not_due"] == 9_000
    assert rows["Total supplier bills"]["total"] == 11_500
    assert rows["Staff advances (1400)"]["total"] == 3_000
    assert rows["Money owed to staff (2310)"]["total"] == 700
    assert report.check_ok


def test_budget_marks_a_line_more_than_ten_percent_and_fifty_dollars_off() -> None:
    report = budget_against_actual(
        [
            ("6050", "Repairs", 1, 40_000),
            ("6050", "Repairs", 2, 40_000),
            ("6070", "Internet", 2, 10_000),
            ("4010", "Rent", 2, 1_000_000),
        ],
        {"6050": 50_000, "6070": 14_000, "4010": 1_000_000},
        {"6050": 85_000, "6070": 14_000, "4010": 1_000_000},
        {},
        month_no=2,
        percent_hundredths=1_000,
        smallest=5_000,
        approved_version=2,
        period="",
        state=OPEN,
    )
    rows = by_name(report)
    # $100 and 25% off this month; $50 and 6.25% off in the year: only the month is marked.
    assert (rows["Repairs"]["month_off"], rows["Repairs"]["year_off"]) == (True, False)
    assert rows["Repairs"]["budget_year"] == 80_000
    # 40% off but only $40: not marked.
    assert rows["Internet"]["month_off"] is False
    assert rows["Rent"]["difference_month"] == 0
    assert (report.check_ok, report.check_text) == (
        False,
        "1 lines are more than the Budget warning off",
    )
    none = budget_against_actual(
        [],
        {},
        {},
        {},
        month_no=1,
        percent_hundredths=1_000,
        smallest=5_000,
        approved_version=None,
        period="",
        state=OPEN,
    )
    assert (none.check_ok, none.check_text) == (False, "There is no approved budget for this year")


def test_month_helpers() -> None:
    assert month_end(date(2027, 2, 3)) == date(2027, 2, 28)
    assert month_end(date(2028, 12, 31)) == date(2028, 12, 31)
    assert months_back(date(2027, 1, 15), 1) == date(2026, 12, 1)
    assert months_back(date(2027, 3, 15), 12) == date(2026, 3, 1)


@dataclass
class InMemoryReports:
    property_id: UUID = field(default_factory=uuid4)
    asked: list[tuple[str, ReportParams]] = field(default_factory=list)
    refuse: Exception | None = None

    def report(
        self, name: ReportName, property_id: UUID, actor_id: str, params: ReportParams
    ) -> LedgerReport:
        del actor_id
        if property_id != self.property_id:
            raise LedgerMoneyNotFound
        if self.refuse is not None:
            raise self.refuse
        self.asked.append((name, params))
        made = trial_balance(
            [("1010", "Cash on hand (USD)", 1_250, 0), ("4010", "Rent", 0, 1_250)],
            period="As at 31/01/2027",
            state=OPEN,
        )
        return LedgerReport(
            name,
            made.title,
            made.period,
            made.state,
            made.columns,
            made.rows,
            made.check_ok,
            made.check_text,
            date(2027, 2, 1),
        )


def client(flow: InMemoryReports, *capabilities: str) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    return TestClient(create_app(actor_resolver=lambda _: who, ledger_report_flow=flow))


def test_a_report_needs_the_ledger_right_and_is_not_cached() -> None:
    flow = InMemoryReports()
    base = f"/api/v1/properties/{flow.property_id}/ledger/reports"
    assert client(flow, "expenses.request").get(f"{base}/trial-balance").status_code == 403
    reader = client(flow, "ledger.read")
    answer = reader.get(f"{base}/trial-balance", params={"as_of": "2027-01-31"})
    assert answer.status_code == 200
    assert answer.headers["cache-control"] == "private, no-store"
    data = answer.json()["data"]
    assert data["state"] == OPEN and data["check"] == {"ok": True, "text": "Debits equal credits"}
    assert data["columns"][2] == {"key": "debit", "label": "Debit", "kind": "money"}
    assert flow.asked[-1] == ("trial-balance", ReportParams(as_of=date(2027, 1, 31)))
    assert reader.get(f"{base}/no-such-report").status_code == 422
    other = f"/api/v1/properties/{uuid4()}/ledger/reports/trial-balance"
    assert reader.get(other).status_code == 403


def test_each_report_takes_only_its_own_values() -> None:
    flow = InMemoryReports()
    base = f"/api/v1/properties/{flow.property_id}/ledger/reports"
    reader = client(flow, "ledger.read")
    assert reader.get(f"{base}/trial-balance", params={"month": "2027-01-01"}).status_code == 422
    assert reader.get(f"{base}/customer-aging", params={"as_of": "2027-01-01"}).status_code == 422
    assert reader.get(f"{base}/account-detail").status_code == 422
    assert reader.get(f"{base}/account-detail", params={"account": "10"}).status_code == 422
    backwards = {"from": "2027-02-01", "to": "2027-01-01"}
    assert reader.get(f"{base}/cash-flow", params=backwards).status_code == 422
    assert reader.get(f"{base}/cash-flow", params={"format": "csv"}).status_code == 422
    found = reader.get(
        f"{base}/account-detail",
        params={"account": "1020", "from": "2027-01-01", "to": "2027-01-31"},
    )
    assert found.status_code == 200
    assert flow.asked[-1] == (
        "account-detail",
        ReportParams(start=date(2027, 1, 1), end=date(2027, 1, 31), account="1020"),
    )
    assert reader.get(f"{base}/budget", params={"month": "2027-02-14"}).status_code == 200
    assert flow.asked[-1] == ("budget", ReportParams(month=date(2027, 2, 14)))
    flow.refuse = LedgerMoneyInvalid("The first day is after the last day")
    refused = reader.get(f"{base}/cash-flow")
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "LEDGER_MONEY_INVALID"


def test_a_report_downloads_as_excel_and_as_a_pdf_with_the_period_and_check() -> None:
    flow = InMemoryReports()
    base = f"/api/v1/properties/{flow.property_id}/ledger/reports"
    reader = client(flow, "ledger.read")
    excel = reader.get(f"{base}/trial-balance", params={"format": "xlsx"})
    assert excel.status_code == 200
    assert excel.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "trial-balance-2027-02-01.xlsx" in excel.headers["content-disposition"]
    assert excel.headers["x-export-rows"] == "3"
    sheet = load_workbook(io.BytesIO(excel.content)).active
    assert sheet is not None
    cells = [row[0] for row in sheet.iter_rows(values_only=True)]
    assert cells[:5] == [
        "Trial balance",
        "As at 31/01/2027",
        OPEN,
        "Check: Debits equal credits",
        "Amounts in US dollars. Made on 01/02/2027.",
    ]
    pdf = reader.get(f"{base}/trial-balance", params={"format": "pdf"})
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert len(pdf.headers["x-export-sha256"]) == 64
