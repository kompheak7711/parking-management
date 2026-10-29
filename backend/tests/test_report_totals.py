"""V1-057 step 2: the four "Totals by Unit and month" reports (DL-079 answers 1 to 4).

The table has the years with records (newest first), twelve months with a blank for a month with
no record, and the year's Total; a Unit or floor filter keeps those Units only, and money with no
Unit counts only in the whole-Property table. The route needs `reports.read`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any, cast

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.report_totals import (
    MonthFact,
    TotalsFilter,
    TotalsReport,
    income_facts,
    payment_facts,
    utility_facts,
)
from property_rental.report_totals import build_totals as build
from property_rental.reports import ReportActor
from property_rental.settings import Settings


def build_totals(
    report: TotalsReport,
    facts: Sequence[MonthFact],
    units: Sequence[dict[str, object]],
    chosen: TotalsFilter,
) -> dict[str, Any]:
    return cast(dict[str, Any], build(report, facts, units, chosen))


PROPERTY = uuid.uuid4()
U1, U2, U3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
UNITS = [
    {"id": U1, "unit_number": "U101", "floor": "1", "unit_type": "STUDIO", "status": "OCCUPIED"},
    {"id": U2, "unit_number": "U204", "floor": "2", "unit_type": "STUDIO", "status": "OCCUPIED"},
    {"id": U3, "unit_number": "U205", "floor": "2", "unit_type": "STUDIO", "status": "VACANT"},
]
INCOME = [
    {"unit_id": U1, "month": date(2026, 9, 1), "kind": "RENT", "amount_usd_cents": 30_000},
    {"unit_id": U1, "month": date(2026, 9, 1), "kind": "UTILITIES", "amount_usd_cents": 2_500},
    {"unit_id": U2, "month": date(2026, 10, 1), "kind": "RENT", "amount_usd_cents": 45_000},
    {"unit_id": U2, "month": date(2026, 10, 1), "kind": "DAMAGE_CHARGES", "amount_usd_cents": 900},
    {
        "unit_id": U2,
        "month": date(2026, 10, 1),
        "kind": "LATE_PAYMENT_CHARGES",
        "amount_usd_cents": -100,
    },
    {"unit_id": U3, "month": date(2025, 12, 1), "kind": "RENT", "amount_usd_cents": 20_000},
]


def test_the_income_table_has_the_years_with_records_and_blank_months() -> None:
    page = build_totals("total_income", income_facts(INCOME), UNITS, TotalsFilter())
    years = page["years"]
    assert isinstance(years, list)
    assert [row["year"] for row in years] == [2026, 2025]
    months_2026 = years[0]["months"]
    assert months_2026[:8] == [None] * 8
    assert months_2026[8:10] == [32_500, 45_800]
    assert months_2026[10:] == [None, None]
    assert years[0]["total"] == 78_300
    assert years[1]["months"][11] == 20_000 and years[1]["total"] == 20_000
    assert page["summary"] == {
        "total": 98_300,
        "highest_month": {"month": "2026-10", "amount": 45_800},
        "highest_unit": {"unit_id": str(U2), "unit_number": "U204", "amount": 45_800},
        "no_unit_amount": 0,
    }
    chart = page["chart"]
    assert isinstance(chart, dict)
    assert chart["months"][-1] == {
        "month": "2026-10",
        "parts": {"move_out_and_damage": 900, "other": -100, "rent": 45_000},
    }
    assert [unit["unit_number"] for unit in chart["top_units"]] == ["U204", "U101", "U205"]


def test_a_unit_floor_or_date_filter_keeps_those_rows_only() -> None:
    facts = income_facts(INCOME)
    one = build_totals("total_income", facts, UNITS, TotalsFilter(unit_id=U1))
    assert one["summary"]["total"] == 32_500
    assert one["filter"]["unit_number"] == "U101"
    floor = build_totals("total_income", facts, UNITS, TotalsFilter(floor="2"))
    assert floor["summary"]["total"] == 65_800
    dated = build_totals(
        "total_income",
        facts,
        UNITS,
        TotalsFilter(from_date=date(2026, 1, 15), to_date=date(2026, 9, 3)),
    )
    assert dated["summary"]["total"] == 32_500
    assert [row["year"] for row in dated["years"]] == [2026]


def test_payment_money_with_no_unit_counts_only_in_the_whole_property_table() -> None:
    rows: list[dict[str, object]] = [
        {
            "unit_id": U1,
            "month": date(2026, 10, 1),
            "kind": "INVOICES",
            "category": "RENT",
            "amount_usd_cents": 30_000,
        },
        {
            "unit_id": U1,
            "month": date(2026, 10, 1),
            "kind": "DEPOSITS",
            "category": "SECURITY",
            "amount_usd_cents": 60_000,
        },
        {
            "unit_id": None,
            "month": date(2026, 10, 1),
            "kind": "NOT_ALLOCATED",
            "category": None,
            "amount_usd_cents": 5_000,
        },
    ]
    facts = payment_facts(rows)
    whole = build_totals("total_payment", facts, UNITS, TotalsFilter())
    assert whole["summary"]["total"] == 95_000
    assert whole["summary"]["no_unit_amount"] == 5_000
    assert whole["chart"]["months"][0]["parts"] == {
        "deposits": 60_000,
        "other": 5_000,
        "paid_to_invoices": 30_000,
    }
    floor = build_totals("total_payment", facts, UNITS, TotalsFilter(floor="1"))
    assert floor["summary"]["total"] == 90_000


def test_the_utility_tables_add_the_quantity_and_mark_estimated_months() -> None:
    def reading(
        unit: uuid.UUID, month: date, kind: str, quantity: str, amount: int, estimate: bool
    ) -> dict[str, object]:
        return {
            "period_id": uuid.uuid4(),
            "unit_id": unit,
            "month": month,
            "utility_type": kind,
            "quantity": Decimal(quantity),
            "is_estimate": estimate,
            "amount_usd_cents": amount,
            "billed": True,
        }

    rows = [
        reading(U1, date(2026, 9, 1), "ELECTRICITY", "120.50", 3_013, False),
        reading(U2, date(2026, 9, 1), "ELECTRICITY", "80", 2_000, True),
        reading(U1, date(2026, 9, 1), "WATER", "6.5", 650, False),
    ]
    page = build_totals(
        "total_electricity", utility_facts(rows, "ELECTRICITY"), UNITS, TotalsFilter()
    )
    year = page["years"][0]
    assert year["months"][8] == 5_013
    assert year["quantities"][8] == "200.5"
    assert year["quantities"][7] is None
    assert year["estimate_months"][8] is True and year["estimate_months"][7] is False
    assert page["summary"]["total_quantity"] == "200.5"
    assert page["summary"]["measurement_unit"] == "KWH"
    water = build_totals("total_water", utility_facts(rows, "WATER"), UNITS, TotalsFilter())
    assert water["summary"]["total"] == 650
    assert water["summary"]["measurement_unit"] == "M3"


def test_an_empty_report_has_no_years_and_no_highest_month() -> None:
    page = build_totals("total_income", [], UNITS, TotalsFilter())
    assert page["years"] == []
    assert page["summary"] == {
        "total": 0,
        "highest_month": None,
        "highest_unit": None,
        "no_unit_amount": 0,
    }
    facts = [MonthFact(None, date(2026, 1, 1), "other", 0)]
    zero = build_totals("total_income", facts, UNITS, TotalsFilter())
    assert zero["years"][0]["months"][0] == 0


class FakeStore:
    def __init__(self) -> None:
        self.reads: list[str] = []

    def home_page(
        self, actor: ReportActor, property_id: uuid.UUID, sections: Sequence[str]
    ) -> dict[str, object]:
        raise AssertionError("not used")

    def rows(
        self,
        read: str,
        actor: ReportActor,
        property_id: uuid.UUID,
        extra: Sequence[object] = (),
    ) -> list[dict[str, object]]:
        self.reads.append(read)
        return list(INCOME) if read == "report_income_facts" else []

    def units(self, property_id: uuid.UUID) -> list[dict[str, object]]:
        return list(UNITS)

    def utility_rates(self, property_id: uuid.UUID) -> list[dict[str, object]]:
        return []


def person(*capabilities: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=str(uuid.uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability, frozenset({str(PROPERTY)})) for capability in capabilities
        ),
    )


def client(actor: AuthenticatedActor | None, store: FakeStore) -> TestClient:
    return TestClient(
        create_app(Settings(database_url=None), actor_resolver=lambda _: actor, report_store=store)
    )


def path(report: str, query: str = "") -> str:
    return f"/api/v1/properties/{PROPERTY}/reports/totals/{report}{query}"


def test_the_totals_route_needs_reports_read() -> None:
    store = FakeStore()
    assert client(None, store).get(path("total_income")).status_code == 401
    staff = person("invoices.read", "payments.read", "utility.read", "units.read")
    assert client(staff, store).get(path("total_income")).status_code == 403
    assert store.reads == []


def test_the_totals_route_reads_the_chosen_report_with_its_filter() -> None:
    store = FakeStore()
    manager = client(person("reports.read"), store)
    answer = manager.get(path("total_income", f"?unit_id={U2}&from=2026-01-01&to=2026-12-31"))
    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "private, no-store"
    data = answer.json()["data"]
    assert data["summary"]["total"] == 45_800
    assert data["filter"] == {
        "unit_id": str(U2),
        "unit_number": "U204",
        "floor": None,
        "from": "2026-01-01",
        "to": "2026-12-31",
    }
    for report, read in (
        ("total_payment", "report_payment_facts"),
        ("total_electricity", "report_utility_facts"),
        ("total_water", "report_utility_facts"),
    ):
        assert manager.get(path(report)).status_code == 200
        assert store.reads[-1] == read


def test_the_totals_route_refuses_a_wrong_report_filter_or_query() -> None:
    manager = client(person("reports.read"), FakeStore())
    assert manager.get(path("total_rent")).status_code == 422
    assert manager.get(path("total_income", "?from=2026-05-01&to=2026-04-01")).status_code == 422
    assert manager.get(path("total_income", f"?unit_id={uuid.uuid4()}")).status_code == 422
    assert manager.get(path("total_income", "?customer=all")).status_code == 422
    assert manager.get(path("total_income", "?floor=")).status_code == 422
