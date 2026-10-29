"""The four "Totals by Unit and month" reports (DL-079 answers 1 to 4, DESIGN.md Reports).

Each report is a table with the years down the side (newest first, only years that have
records), January to December across and a Total for each year. A Unit or floor filter keeps
the rows of those Units; with no filter every Unit is added together, and money that belongs to
no Unit (a Payment not tied to a Lease, for example) counts only in the whole-Property table.
The summary gives the total, the highest month and the highest Unit; the chart data gives each
month's parts and the top five Units. Money is integer USD cents; quantities are exact decimals
written as text.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final, Literal, cast
from uuid import UUID

TotalsReport = Literal["total_income", "total_payment", "total_electricity", "total_water"]
TOTALS_REPORTS: Final[tuple[TotalsReport, ...]] = (
    "total_income",
    "total_payment",
    "total_electricity",
    "total_water",
)

# The parts of the stacked month chart (DESIGN.md: Rent, Utilities, Move-out and damage for
# Income; Paid to Invoices, Deposits, Other for Payments).
INCOME_GROUPS: Final[Mapping[str, str]] = {
    "RENT": "rent",
    "SERVICE_CHARGES": "rent",
    # V1.1 (owner 2026-10-29): a Services Invoice line counts with Rent and Monthly Services.
    "REGULAR_SERVICE_CHARGES": "rent",
    "UTILITIES": "utilities",
    "DAMAGE_CHARGES": "move_out_and_damage",
    "MISCELLANEOUS_CHARGES": "move_out_and_damage",
    "LATE_PAYMENT_CHARGES": "other",
    "DEPOSIT_KEPT": "other",
}
PAYMENT_GROUPS: Final[Mapping[str, str]] = {
    "INVOICES": "paid_to_invoices",
    "DEPOSITS": "deposits",
}
UTILITY_TYPES: Final[Mapping[str, str]] = {
    "total_electricity": "ELECTRICITY",
    "total_water": "WATER",
}
MEASUREMENT_UNITS: Final[Mapping[str, str]] = {"ELECTRICITY": "KWH", "WATER": "M3"}


@dataclass(frozen=True, slots=True)
class TotalsFilter:
    unit_id: UUID | None = None
    floor: str | None = None
    from_date: date | None = None
    to_date: date | None = None


@dataclass(frozen=True, slots=True)
class MonthFact:
    unit_id: UUID | None
    month: date
    group: str
    amount: int
    quantity: Decimal | None = None
    estimate: bool = False


def _uuid(value: object) -> UUID | None:
    if value is None:
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


def _month(value: object) -> date:
    if isinstance(value, date):
        return value.replace(day=1)
    return date.fromisoformat(str(value)).replace(day=1)


def income_facts(rows: Iterable[Mapping[str, object]]) -> list[MonthFact]:
    return [
        MonthFact(
            _uuid(row["unit_id"]),
            _month(row["month"]),
            INCOME_GROUPS.get(str(row["kind"]), "other"),
            int(cast(int, row["amount_usd_cents"])),
        )
        for row in rows
    ]


def payment_facts(rows: Iterable[Mapping[str, object]]) -> list[MonthFact]:
    return [
        MonthFact(
            _uuid(row["unit_id"]),
            _month(row["month"]),
            PAYMENT_GROUPS.get(str(row["kind"]), "other"),
            int(cast(int, row["amount_usd_cents"])),
        )
        for row in rows
    ]


def utility_facts(rows: Iterable[Mapping[str, object]], utility_type: str) -> list[MonthFact]:
    return [
        MonthFact(
            _uuid(row["unit_id"]),
            _month(row["month"]),
            "estimate" if row["is_estimate"] else "reading",
            int(cast(int, row["amount_usd_cents"])),
            Decimal(str(row["quantity"])) if row["quantity"] is not None else None,
            bool(row["is_estimate"]),
        )
        for row in rows
        if row["utility_type"] == utility_type
    ]


def _quantity_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return "0" if text in {"-0", ""} else text


def _in_scope(fact: MonthFact, chosen: TotalsFilter, floors: Mapping[UUID, str | None]) -> bool:
    if chosen.unit_id is not None and fact.unit_id != chosen.unit_id:
        return False
    if chosen.floor is not None and (
        fact.unit_id is None or floors.get(fact.unit_id) != chosen.floor
    ):
        return False
    if chosen.from_date is not None and fact.month < chosen.from_date.replace(day=1):
        return False
    return not (chosen.to_date is not None and fact.month > chosen.to_date.replace(day=1))


def build_totals(
    report: TotalsReport,
    facts: Sequence[MonthFact],
    units: Sequence[Mapping[str, object]],
    chosen: TotalsFilter,
) -> dict[str, object]:
    """The year-by-month table, its summary and its chart data."""
    numbers = {cast(UUID, _uuid(unit["id"])): str(unit["unit_number"]) for unit in units}
    floors = {
        cast(UUID, _uuid(unit["id"])): (None if unit["floor"] is None else str(unit["floor"]))
        for unit in units
    }
    kept = [fact for fact in facts if _in_scope(fact, chosen, floors)]
    quantities = report in UTILITY_TYPES
    by_month: dict[date, int] = defaultdict(int)
    by_month_quantity: dict[date, Decimal] = defaultdict(Decimal)
    by_month_group: dict[date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_unit: dict[UUID | None, int] = defaultdict(int)
    by_unit_quantity: dict[UUID | None, Decimal] = defaultdict(Decimal)
    estimate_months: set[date] = set()
    for fact in kept:
        by_month[fact.month] += fact.amount
        by_month_group[fact.month][fact.group] += fact.amount
        by_unit[fact.unit_id] += fact.amount
        if fact.quantity is not None:
            by_month_quantity[fact.month] += fact.quantity
            by_unit_quantity[fact.unit_id] += fact.quantity
        if fact.estimate:
            estimate_months.add(fact.month)
    months_with_records = set(by_month) | set(by_month_quantity)
    years = sorted({month.year for month in months_with_records}, reverse=True)
    table: list[dict[str, object]] = []
    for year in years:
        cells = [date(year, number, 1) for number in range(1, 13)]
        row: dict[str, object] = {
            "year": year,
            "months": [by_month[cell] if cell in months_with_records else None for cell in cells],
            "total": sum(by_month[cell] for cell in cells if cell in months_with_records),
        }
        if quantities:
            row["quantities"] = [
                _quantity_text(by_month_quantity[cell]) if cell in months_with_records else None
                for cell in cells
            ]
            row["total_quantity"] = _quantity_text(
                sum((by_month_quantity[cell] for cell in cells), Decimal(0))
            )
            row["estimate_months"] = [cell in estimate_months for cell in cells]
        table.append(row)
    total = sum(by_month.values())
    highest_month = max(sorted(by_month), key=lambda month: by_month[month], default=None)
    named_units = {unit: amount for unit, amount in by_unit.items() if unit is not None}
    ranked = sorted(named_units, key=lambda unit: (-named_units[unit], numbers.get(unit, "")))
    summary: dict[str, object] = {
        "total": total,
        "highest_month": (
            None
            if highest_month is None
            else {"month": highest_month.isoformat()[:7], "amount": by_month[highest_month]}
        ),
        "highest_unit": (
            None
            if not ranked
            else {
                "unit_id": str(ranked[0]),
                "unit_number": numbers.get(ranked[0]),
                "amount": named_units[ranked[0]],
            }
        ),
        "no_unit_amount": by_unit.get(None, 0),
    }
    if quantities:
        summary["total_quantity"] = _quantity_text(sum(by_month_quantity.values(), Decimal(0)))
        summary["measurement_unit"] = MEASUREMENT_UNITS[UTILITY_TYPES[report]]
    chart = {
        "months": [
            {"month": month.isoformat()[:7], "parts": dict(sorted(by_month_group[month].items()))}
            for month in sorted(months_with_records)
        ],
        "top_units": [
            {"unit_id": str(unit), "unit_number": numbers.get(unit), "amount": named_units[unit]}
            for unit in ranked[:5]
        ],
    }
    return {
        "report": report,
        "currency": "USD",
        "filter": {
            "unit_id": None if chosen.unit_id is None else str(chosen.unit_id),
            "unit_number": None if chosen.unit_id is None else numbers.get(chosen.unit_id),
            "floor": chosen.floor,
            "from": None if chosen.from_date is None else chosen.from_date.isoformat(),
            "to": None if chosen.to_date is None else chosen.to_date.isoformat(),
        },
        "years": table,
        "summary": summary,
        "chart": chart,
    }
