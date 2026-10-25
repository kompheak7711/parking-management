"""The nine registers and lists of the Reports page (DL-072, DL-079 answer 5, DESIGN.md Reports).

Each register reads its rows from one bounded definer function (migration `20270304_223`, and
`20270302_221` for Utility consumption), keeps the rows of the chosen floor and period, and adds
a summary, the chart data and the footer totals over every kept row; the rows themselves come a
page at a time. Amounts are integer USD cents; KHR is information only and never added to USD
(DL-060, DL-072 answer 11). Unit occupancy and Lease dates show the records as they are today,
and Deposit liability shows what is held now, so the period does not apply to them.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Final, Literal, cast

RegisterName = Literal[
    "invoice_register",
    "payments",
    "utility_consumption",
    "credit_ledger",
    "deposits",
    "final_settlements",
    "unit_occupancy",
    "lease_dates",
    "audit_activity",
]
REGISTER_NAMES: Final[tuple[RegisterName, ...]] = (
    "invoice_register",
    "payments",
    "utility_consumption",
    "credit_ledger",
    "deposits",
    "final_settlements",
    "unit_occupancy",
    "lease_dates",
    "audit_activity",
)

# The bounded read of each register.
REGISTER_READS: Final[Mapping[RegisterName, str]] = {
    "invoice_register": "report_invoice_register",
    "payments": "report_payment_register",
    "utility_consumption": "report_utility_facts",
    "credit_ledger": "report_credit_ledger",
    "deposits": "report_deposit_register",
    "final_settlements": "report_final_settlement_register",
    "unit_occupancy": "report_unit_occupancy",
    "lease_dates": "report_lease_dates",
    "audit_activity": "report_audit_activity",
}
NO_PERIOD: Final = frozenset({"deposits", "unit_occupancy"})
# Overdue groups (DL-072 answer 2).
OVERDUE_GROUPS: Final = ("days_1_19", "days_20_29", "days_30_plus")
DEFAULT_LIMIT: Final = 200
MAX_LIMIT: Final = 1000


@dataclass(frozen=True, slots=True)
class RegisterFilter:
    floor: str | None = None
    from_date: date | None = None
    to_date: date | None = None
    offset: int = 0
    limit: int = DEFAULT_LIMIT


@dataclass(frozen=True, slots=True)
class Built:
    rows: list[dict[str, object]]
    summary: dict[str, object]
    chart: Mapping[str, object]
    totals: Mapping[str, object] | None = None


Row = dict[str, object]


def _int(value: object) -> int:
    return int(cast(int, value or 0))


def _day(value: object) -> date | None:
    if value is None:
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _month(value: object) -> str:
    day = _day(value)
    assert day is not None
    return day.isoformat()[:7]


def _sum(rows: Iterable[Row], key: str) -> int:
    return sum(_int(row[key]) for row in rows)


def overdue_group(days: int) -> str:
    if days < 20:
        return "days_1_19"
    if days < 30:
        return "days_20_29"
    return "days_30_plus"


def _invoice_register(rows: Sequence[Row], money: bool) -> Built:
    del money
    counted = [row for row in rows if row["status"] != "VOID"]
    groups = {name: {"count": 0, "owed_usd_cents": 0} for name in OVERDUE_GROUPS}
    months: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        if row["overdue_days"] is not None:
            row["overdue_group"] = overdue_group(_int(row["overdue_days"]))
            group = groups[cast(str, row["overdue_group"])]
            group["count"] += 1
            group["owed_usd_cents"] += _int(row["owed_usd_cents"])
    for row in counted:
        month = months[_month(row["invoice_date"])]
        for key in ("paid_usd_cents", "other_settled_usd_cents", "owed_usd_cents"):
            month[key.removesuffix("_usd_cents")] += _int(row[key])
    totals = {
        key: _sum(counted, key)
        for key in (
            "total_usd_cents",
            "paid_usd_cents",
            "other_settled_usd_cents",
            "owed_usd_cents",
        )
    }
    summary: dict[str, object] = {
        "issued_usd_cents": totals["total_usd_cents"],
        "paid_to_invoices_usd_cents": totals["paid_usd_cents"],
        "other_settled_usd_cents": totals["other_settled_usd_cents"],
        "owed_usd_cents": totals["owed_usd_cents"],
        "invoice_count": len(counted),
        "void_count": len(rows) - len(counted),
        "overdue_groups": groups,
        "by_status": dict(sorted(Counter(str(row["status"]) for row in rows).items())),
    }
    chart = {
        "months": [
            {"month": key, "parts": dict(sorted(months[key].items()))} for key in sorted(months)
        ]
    }
    return Built(list(rows), summary, chart, totals)


# The Payments report lines (DL-072 answer 10, DL-079 answer 7).
PAYMENT_LINES: Final = (
    "INVOICES",
    "LATE_PAYMENT_CHARGES",
    "DEPOSITS",
    "CREDIT",
    "REFUNDED",
    "NOT_ALLOCATED",
    "REVERSED_LATER",
)


def _parts(row: Row) -> list[dict[str, object]]:
    parts = row.get("parts")
    return cast(list[dict[str, object]], parts if isinstance(parts, list) else [])


def _payments(rows: Sequence[Row], reversals: Sequence[Row]) -> Built:
    lines: dict[str, int] = dict.fromkeys(PAYMENT_LINES, 0)
    categories: dict[str, int] = defaultdict(int)
    months: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    khr: dict[str, int] = defaultdict(int)
    for row in rows:
        month = months[_month(row["payment_date"])]
        month["received"] += _int(row["amount_usd_cents"])
        if row["received_currency"] != "USD":
            khr[str(row["received_currency"])] += _int(row["received_amount_minor"])
        unallocated = 0
        for part in _parts(row):
            kind, amount = str(part["kind"]), _int(part["amount_usd_cents"])
            lines[kind] = lines.get(kind, 0) + amount
            month[kind] += amount
            if kind == "INVOICES":
                categories[str(part["category"])] += amount
            if kind in {"NOT_ALLOCATED", "REVERSED_LATER"}:
                unallocated += amount
        row["not_allocated_usd_cents"] = unallocated
    reversed_total = _sum(reversals, "amount_usd_cents")
    for row in reversals:
        months[_month(row["reversed_on"])]["REVERSAL"] -= _int(row["amount_usd_cents"])
    received = _sum(rows, "amount_usd_cents")
    summary: dict[str, object] = {
        "received_usd_cents": received,
        "lines": lines,
        "paid_to_invoices_by_category": dict(sorted(categories.items())),
        "reversals_usd_cents": -reversed_total,
        "net_usd_cents": received - reversed_total,
        "payment_count": len(rows),
        "received_other_currency_minor": dict(sorted(khr.items())),
    }
    chart = {
        "months": [
            {
                "month": key,
                "parts": {
                    "paid_to_invoices": months[key]["INVOICES"],
                    "deposits": months[key]["DEPOSITS"],
                    "other": sum(
                        amount
                        for kind, amount in months[key].items()
                        if kind not in {"INVOICES", "DEPOSITS", "received"}
                    ),
                },
            }
            for key in sorted(months)
        ],
        "month_lines": [
            {"month": key, **{kind: months[key][kind] for kind in (*PAYMENT_LINES, "REVERSAL")}}
            for key in sorted(months)
        ],
    }
    totals = {
        "amount_usd_cents": received,
        "not_allocated_usd_cents": _sum(rows, "not_allocated_usd_cents"),
    }
    return Built(list(rows), summary, chart, totals)


def _quantity(value: object) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(0)


def _text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return "0" if text in {"-0", ""} else text


def _utility(rows: Sequence[Row], money: bool) -> Built:
    quantity: dict[str, Decimal] = defaultdict(Decimal)
    amount: dict[str, int] = defaultdict(int)
    months: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    kept: list[Row] = []
    for row in rows:
        kind = str(row["utility_type"])
        used = _quantity(row["quantity"])
        quantity[kind] += used
        amount[kind] += _int(row["amount_usd_cents"])
        months[_month(row["month"])][kind] += used
        out = {
            key: row[key]
            for key in (
                "period_id",
                "unit_id",
                "unit_number",
                "floor",
                "utility_type",
                "period_start",
                "period_end",
                "is_estimate",
                "billed",
            )
        }
        out["quantity"] = _text(used)
        if money:
            out["amount_usd_cents"] = _int(row["amount_usd_cents"])
        kept.append(out)
    summary: dict[str, object] = {
        "electricity_kwh": _text(quantity["ELECTRICITY"]),
        "water_m3": _text(quantity["WATER"]),
        "estimate_count": sum(1 for row in rows if row["is_estimate"]),
        "period_count": len(rows),
    }
    totals: dict[str, object] = {
        "electricity_kwh": summary["electricity_kwh"],
        "water_m3": summary["water_m3"],
    }
    if money:
        summary["electricity_usd_cents"] = amount["ELECTRICITY"]
        summary["water_usd_cents"] = amount["WATER"]
        totals["electricity_usd_cents"] = amount["ELECTRICITY"]
        totals["water_usd_cents"] = amount["WATER"]
    chart = {
        "months": [
            {
                "month": key,
                "electricity_kwh": _text(months[key]["ELECTRICITY"]),
                "water_m3": _text(months[key]["WATER"]),
            }
            for key in sorted(months)
        ]
    }
    return Built(kept, summary, chart, totals)


def _money_bars(rows: Sequence[Row], keys: Sequence[str]) -> Built:
    totals: dict[str, object] = {key: _sum(rows, key) for key in keys}
    bars = [{"key": key.removesuffix("_usd_cents"), "amount": totals[key]} for key in keys]
    return Built(list(rows), dict(totals), {"bars": bars}, dict(totals))


def _credit_ledger(rows: Sequence[Row], money: bool) -> Built:
    del money
    keys = (
        "recognized_usd_cents",
        "applied_usd_cents",
        "refunded_usd_cents",
        "reversed_usd_cents",
        "available_usd_cents",
    )
    built = _money_bars(rows, keys)
    built.summary["credit_count"] = len(rows)
    return built


def _deposits(rows: Sequence[Row], money: bool) -> Built:
    del money
    keys = (
        "received_usd_cents",
        "applied_usd_cents",
        "kept_usd_cents",
        "refunded_usd_cents",
        "held_usd_cents",
    )
    built = _money_bars(rows, keys)
    by_type: dict[str, int] = defaultdict(int)
    for row in rows:
        by_type[str(row["deposit_type"])] += _int(row["held_usd_cents"])
    built.summary["held_by_type"] = dict(sorted(by_type.items()))
    built.summary["deposit_count"] = len(rows)
    return built


def _final_settlements(rows: Sequence[Row], money: bool) -> Built:
    del money
    keys = (
        "deposits_applied_usd_cents",
        "credit_applied_usd_cents",
        "deposits_kept_usd_cents",
        "refunded_usd_cents",
        "balance_due_usd_cents",
    )
    for row in rows:
        row["status"] = "CLOSED" if row["closed_on"] is not None else "OPEN"
    built = _money_bars(rows, keys)
    built.summary["open_count"] = sum(1 for row in rows if row["status"] == "OPEN")
    built.summary["closed_count"] = sum(1 for row in rows if row["status"] == "CLOSED")
    return built


# Unit statuses that are neither occupied, reserved nor vacant count as "not available".
NOT_AVAILABLE: Final = frozenset({"UNDER_MAINTENANCE", "CLEANING", "OUT_OF_SERVICE"})


def _without_rent(rows: Sequence[Row], money: bool) -> list[Row]:
    """Rent shows only to a person with `reports.read` (DL-072 answer 5: Staff see no money)."""
    if money:
        return list(rows)
    return [
        {key: value for key, value in row.items() if key != "monthly_rent_usd_cents"}
        for row in rows
    ]


def _unit_occupancy(rows: Sequence[Row], money: bool) -> Built:
    counts = {
        "occupied": sum(1 for row in rows if row["unit_status"] == "OCCUPIED"),
        "reserved": sum(1 for row in rows if row["unit_status"] == "RESERVED"),
        "vacant": sum(1 for row in rows if row["unit_status"] == "VACANT"),
        "not_available": sum(1 for row in rows if row["unit_status"] in NOT_AVAILABLE),
    }
    summary: dict[str, object] = {**counts, "unit_count": len(rows)}
    chart = {"bars": [{"key": key, "count": value} for key, value in counts.items()]}
    return Built(_without_rent(rows, money), summary, chart)


def _is_current(row: Row) -> bool:
    """A signed Lease whose Start Date has come and whose End Date has not passed."""
    days_to_end = _int(row["days_to_end"])
    if row["status"] != "SIGNED" or days_to_end < 0:
        return False
    end = row["end_date"]
    end_date = end if isinstance(end, date) else date.fromisoformat(str(end))
    start = row["start_date"]
    start_date = start if isinstance(start, date) else date.fromisoformat(str(start))
    return start_date <= end_date - timedelta(days=days_to_end)


def _lease_dates(rows: Sequence[Row], money: bool) -> Built:
    signed = [row for row in rows if row["status"] == "SIGNED"]
    ending = [row for row in signed if 0 <= _int(row["days_to_end"]) <= 60]
    by_month = Counter(_month(row["end_date"]) for row in signed)
    summary: dict[str, object] = {
        "current_count": sum(1 for row in rows if _is_current(row)),
        "ending_60_days_count": len(ending),
        "ending_without_renewal_count": sum(1 for row in ending if not row["renewal_drafted"]),
        "terminated_count": sum(1 for row in rows if row["status"] == "TERMINATED"),
    }
    chart = {"months": [{"month": key, "count": by_month[key]} for key in sorted(by_month)]}
    return Built(_without_rent(rows, money), summary, chart)


def _audit_activity(rows: Sequence[Row], money: bool) -> Built:
    del money
    days: dict[str, int] = defaultdict(int)
    actors: dict[tuple[str, str], int] = defaultdict(int)
    kinds: dict[str, int] = defaultdict(int)
    for row in rows:
        count = _int(row["event_count"])
        days[str(row["day"])] += count
        actors[(str(row["actor_id"]), str(row["actor_name"]))] += count
        kinds[str(row["action_family"])] += count
    day_rows: list[Row] = [{"day": key, "count": days[key]} for key in sorted(days, reverse=True)]
    summary: dict[str, object] = {
        "event_count": sum(days.values()),
        "by_actor": [
            {"actor_id": key[0], "name": key[1], "count": value}
            for key, value in sorted(actors.items(), key=lambda item: (-item[1], item[0][1]))
        ],
        "by_kind": [
            {"kind": key, "count": value}
            for key, value in sorted(kinds.items(), key=lambda item: (-item[1], item[0]))
        ],
    }
    chart = {"days": [{"day": key, "count": days[key]} for key in sorted(days)]}
    return Built(day_rows, summary, chart, {"count": summary["event_count"]})


BUILDERS: Final[Mapping[RegisterName, Callable[[Sequence[Row], bool], Built]]] = {
    "invoice_register": _invoice_register,
    "utility_consumption": _utility,
    "credit_ledger": _credit_ledger,
    "deposits": _deposits,
    "final_settlements": _final_settlements,
    "unit_occupancy": _unit_occupancy,
    "lease_dates": _lease_dates,
    "audit_activity": _audit_activity,
}

# The date each register's period filter looks at.
PERIOD_DATES: Final[Mapping[RegisterName, str]] = {
    "invoice_register": "invoice_date",
    "payments": "payment_date",
    "utility_consumption": "period_end",
    "credit_ledger": "recognized_on",
    "final_settlements": "started_on",
    "lease_dates": "end_date",
    "audit_activity": "day",
}


def _in_period(day: date | None, chosen: RegisterFilter) -> bool:
    if day is None:
        return False
    if chosen.from_date is not None and day < chosen.from_date:
        return False
    return not (chosen.to_date is not None and day > chosen.to_date)


def build_register(
    name: RegisterName,
    rows: Sequence[Row],
    units: Sequence[Mapping[str, object]],
    chosen: RegisterFilter,
    *,
    money: bool,
) -> dict[str, object]:
    """Filter, sum and page one register's rows."""
    unit_info = {str(unit["id"]): unit for unit in units}
    named: list[Row] = []
    for source in rows:
        row = dict(source)
        unit = unit_info.get(str(row.get("unit_id"))) if row.get("unit_id") is not None else None
        if "unit_id" in row:
            row["unit_number"] = None if unit is None else unit["unit_number"]
            row["floor"] = None if unit is None else unit["floor"]
        if name == "unit_occupancy" and unit is not None:
            row["unit_type"] = unit["unit_type"]
        named.append(row)
    if chosen.floor is not None and name != "audit_activity":
        named = [row for row in named if row.get("floor") == chosen.floor]
    period = name not in NO_PERIOD
    if name == "lease_dates":
        for row in named:
            row["end_date"] = row["actual_termination_date"] or row["end_date"]
    if period:
        key = PERIOD_DATES[name]
        kept = [row for row in named if _in_period(_day(row[key]), chosen)]
    else:
        kept = named
    if name == "payments":
        reversals = [row for row in named if _in_period(_day(row["reversed_on"]), chosen)]
        built = _payments(kept, reversals)
    else:
        built = BUILDERS[name](kept, money)
    page = built.rows[chosen.offset : chosen.offset + chosen.limit]
    return {
        "report": name,
        "currency": "USD",
        "filter": {
            "floor": chosen.floor,
            "from": None if chosen.from_date is None else chosen.from_date.isoformat(),
            "to": None if chosen.to_date is None else chosen.to_date.isoformat(),
            "period_applies": period,
        },
        "summary": built.summary,
        "chart": built.chart,
        "totals": built.totals,
        "rows": page,
        "row_count": len(built.rows),
        "offset": chosen.offset,
        "limit": chosen.limit,
    }
