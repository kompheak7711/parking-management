"""V1-057 step 3: the nine registers and lists (DL-072, DL-079 answer 5).

The application keeps the rows of the chosen floor and period, sums every kept row (not only the
page), groups overdue Invoices 1 to 19, 20 to 29 and 30 days or more, lists where Payment money
went with reversals as minus lines in their own month, and shows Utility amounts only to people
with `reports.read`. Each register needs its own read rights.
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
from property_rental.report_registers import (
    REGISTER_NAMES,
    RegisterFilter,
    RegisterName,
    overdue_group,
)
from property_rental.report_registers import build_register as build
from property_rental.settings import Settings

PROPERTY = uuid.uuid4()
U1, U2 = uuid.uuid4(), uuid.uuid4()
UNITS: list[dict[str, object]] = [
    {"id": U1, "unit_number": "U101", "floor": "1", "unit_type": "STUDIO", "status": "OCCUPIED"},
    {"id": U2, "unit_number": "U204", "floor": "2", "unit_type": "STUDIO", "status": "VACANT"},
]


def register(
    name: RegisterName,
    rows: Sequence[dict[str, object]],
    chosen: RegisterFilter | None = None,
    *,
    money: bool = True,
) -> dict[str, Any]:
    return cast(dict[str, Any], build(name, rows, UNITS, chosen or RegisterFilter(), money=money))


def invoice(
    unit: uuid.UUID, issued: date, total: int, paid: int, owed: int, days: int | None, status: str
) -> dict[str, object]:
    return {
        "invoice_id": uuid.uuid4(),
        "invoice_number": f"INV-{issued.isoformat()}",
        "status": status,
        "customer_id": uuid.uuid4(),
        "customer_name": "Sok Dara",
        "lease_id": uuid.uuid4(),
        "unit_id": unit,
        "primary_category": "RENT",
        "rent_billing_kind": "RECURRING",
        "invoice_date": issued,
        "due_date": issued,
        "total_usd_cents": total,
        "paid_usd_cents": paid,
        "other_settled_usd_cents": total - paid - owed,
        "owed_usd_cents": owed,
        "overdue_days": days,
    }


def test_the_overdue_groups_are_1_to_19_20_to_29_and_30_or_more() -> None:
    assert [overdue_group(days) for days in (1, 19, 20, 29, 30, 90)] == [
        "days_1_19",
        "days_1_19",
        "days_20_29",
        "days_20_29",
        "days_30_plus",
        "days_30_plus",
    ]


def test_the_invoice_register_sums_every_kept_row_and_leaves_void_invoices_out() -> None:
    rows = [
        invoice(U1, date(2026, 9, 25), 30_000, 30_000, 0, None, "PAID"),
        invoice(U1, date(2026, 10, 1), 30_000, 10_000, 15_000, 22, "PARTIALLY_PAID"),
        invoice(U2, date(2026, 10, 2), 45_000, 0, 45_000, 5, "UNPAID"),
        invoice(U2, date(2026, 10, 3), 9_000, 0, 0, None, "VOID"),
    ]
    page = register("invoice_register", rows, RegisterFilter(limit=1))
    assert page["row_count"] == 4 and len(page["rows"]) == 1
    summary = page["summary"]
    assert summary["issued_usd_cents"] == 105_000
    assert summary["paid_to_invoices_usd_cents"] == 40_000
    assert summary["other_settled_usd_cents"] == 5_000
    assert summary["owed_usd_cents"] == 60_000
    assert summary["void_count"] == 1
    assert summary["overdue_groups"] == {
        "days_1_19": {"count": 1, "owed_usd_cents": 45_000},
        "days_20_29": {"count": 1, "owed_usd_cents": 15_000},
        "days_30_plus": {"count": 0, "owed_usd_cents": 0},
    }
    assert page["totals"]["total_usd_cents"] == 105_000
    assert page["chart"]["months"][1] == {
        "month": "2026-10",
        "parts": {"other_settled": 5_000, "owed": 60_000, "paid": 10_000},
    }
    floor = register("invoice_register", rows, RegisterFilter(floor="1"))
    assert floor["row_count"] == 2 and floor["rows"][0]["unit_number"] == "U101"
    dated = register("invoice_register", rows, RegisterFilter(from_date=date(2026, 10, 1)))
    assert dated["row_count"] == 3


def payment(
    unit: uuid.UUID | None,
    received: date,
    amount: int,
    parts: list[tuple[str, str | None, int]],
    reversed_on: date | None = None,
    currency: str = "USD",
) -> dict[str, object]:
    return {
        "payment_id": uuid.uuid4(),
        "receipt_number": f"R-{received.isoformat()}",
        "payment_date": received,
        "status": "REVERSED" if reversed_on else "RECEIVED",
        "customer_id": uuid.uuid4(),
        "customer_name": "Sok Dara",
        "unit_id": unit,
        "method_name": "ABA",
        "received_currency": currency,
        "received_amount_minor": amount * 41 if currency == "KHR" else amount,
        "rate_khr_per_usd": 4100 if currency == "KHR" else None,
        "amount_usd_cents": amount,
        "reversed_on": reversed_on,
        "parts": [
            {"kind": kind, "category": category, "unit_id": None, "amount_usd_cents": value}
            for kind, category, value in parts
        ],
    }


def test_the_payments_report_lists_where_money_went_and_reversals_in_their_month() -> None:
    rows = [
        payment(
            U1,
            date(2026, 9, 30),
            50_000,
            [("INVOICES", "RENT", 30_000), ("DEPOSITS", "SECURITY", 20_000)],
        ),
        payment(
            U1,
            date(2026, 10, 2),
            12_000,
            [("INVOICES", "UTILITIES", 2_000), ("NOT_ALLOCATED", None, 10_000)],
            currency="KHR",
        ),
        payment(U2, date(2026, 9, 29), 7_000, [("REVERSED_LATER", None, 7_000)], date(2026, 10, 3)),
    ]
    october = register(
        "payments", rows, RegisterFilter(from_date=date(2026, 10, 1), to_date=date(2026, 10, 31))
    )
    summary = october["summary"]
    assert summary["received_usd_cents"] == 12_000
    assert summary["reversals_usd_cents"] == -7_000
    assert summary["net_usd_cents"] == 5_000
    assert summary["lines"]["INVOICES"] == 2_000
    assert summary["lines"]["NOT_ALLOCATED"] == 10_000
    assert summary["received_other_currency_minor"] == {"KHR": 492_000}
    assert october["rows"][0]["not_allocated_usd_cents"] == 10_000
    every = register("payments", rows)["summary"]
    assert every["received_usd_cents"] == 69_000
    assert every["paid_to_invoices_by_category"] == {"RENT": 30_000, "UTILITIES": 2_000}
    assert every["lines"]["REVERSED_LATER"] == 7_000
    assert sum(every["lines"].values()) == every["received_usd_cents"]
    lines = {line["month"]: line for line in register("payments", rows)["chart"]["month_lines"]}
    assert lines["2026-10"]["REVERSAL"] == -7_000
    assert lines["2026-09"]["REVERSED_LATER"] == 7_000


def test_utility_consumption_shows_amounts_only_with_the_report_right() -> None:
    rows: list[dict[str, object]] = [
        {
            "period_id": uuid.uuid4(),
            "unit_id": U1,
            "month": date(2026, 10, 1),
            "utility_type": kind,
            "period_start": date(2026, 9, 25),
            "period_end": date(2026, 10, 24),
            "quantity": Decimal(quantity),
            "is_estimate": kind == "WATER",
            "amount_usd_cents": amount,
            "billed": True,
        }
        for kind, quantity, amount in (("ELECTRICITY", "120.5", 3_013), ("WATER", "6", 600))
    ]
    staff = register("utility_consumption", rows, money=False)
    assert "amount_usd_cents" not in staff["rows"][0]
    assert "electricity_usd_cents" not in staff["summary"]
    assert "electricity_usd_cents" not in staff["totals"]
    assert staff["summary"]["electricity_kwh"] == "120.5"
    assert staff["summary"]["estimate_count"] == 1
    manager = register("utility_consumption", rows)
    assert manager["summary"]["water_usd_cents"] == 600
    assert manager["chart"]["months"] == [
        {"month": "2026-10", "electricity_kwh": "120.5", "water_m3": "6"}
    ]


def test_the_lists_count_today_and_ignore_the_period_where_it_does_not_apply() -> None:
    occupancy = [
        {
            "unit_id": U1,
            "unit_status": "OCCUPIED",
            "lease_id": uuid.uuid4(),
            "reservation_id": None,
            "customer_id": uuid.uuid4(),
            "customer_name": "Sok Dara",
            "monthly_rent_usd_cents": 30_000,
            "until_date": date(2027, 9, 30),
        },
        {
            "unit_id": U2,
            "unit_status": "CLEANING",
            "lease_id": None,
            "reservation_id": None,
            "customer_id": None,
            "customer_name": None,
            "monthly_rent_usd_cents": None,
            "until_date": None,
        },
    ]
    page = register("unit_occupancy", occupancy, RegisterFilter(from_date=date(2030, 1, 1)))
    assert page["filter"]["period_applies"] is False
    assert page["summary"] == {
        "occupied": 1,
        "reserved": 0,
        "vacant": 0,
        "not_available": 1,
        "unit_count": 2,
    }
    assert page["rows"][0]["unit_type"] == "STUDIO"
    leases = [
        {
            "lease_id": uuid.uuid4(),
            "unit_id": U1,
            "customer_id": uuid.uuid4(),
            "customer_name": "Sok Dara",
            "status": status,
            "start_date": date(2025, 11, 1),
            "end_date": end,
            "actual_termination_date": ended,
            "monthly_rent_usd_cents": 30_000,
            "days_to_end": days,
            "renewal_drafted": False,
        }
        for status, end, ended, days in (
            ("SIGNED", date(2026, 11, 30), None, 36),
            ("TERMINATED", date(2026, 12, 31), date(2026, 8, 15), None),
        )
    ]
    dates = register("lease_dates", leases, RegisterFilter(to_date=date(2026, 9, 1)))
    assert dates["row_count"] == 1 and dates["rows"][0]["end_date"] == date(2026, 8, 15)
    every = register("lease_dates", leases)["summary"]
    assert every == {
        "current_count": 1,
        "ending_60_days_count": 1,
        "ending_without_renewal_count": 1,
        "terminated_count": 1,
    }


def test_audit_activity_counts_by_day_person_and_kind() -> None:
    person = uuid.uuid4()
    rows: list[dict[str, object]] = [
        {
            "day": date(2026, 10, 2),
            "actor_id": person,
            "actor_name": "Chan",
            "action_family": "invoice",
            "event_count": 3,
        },
        {
            "day": date(2026, 10, 2),
            "actor_id": person,
            "actor_name": "Chan",
            "action_family": "payment",
            "event_count": 1,
        },
        {
            "day": date(2026, 10, 1),
            "actor_id": None,
            "actor_name": "System",
            "action_family": "invoice",
            "event_count": 2,
        },
    ]
    page = register("audit_activity", rows, RegisterFilter(floor="1"))
    assert page["rows"] == [{"day": "2026-10-02", "count": 4}, {"day": "2026-10-01", "count": 2}]
    assert page["summary"]["event_count"] == 6
    assert page["summary"]["by_kind"] == [
        {"kind": "invoice", "count": 5},
        {"kind": "payment", "count": 1},
    ]
    assert page["summary"]["by_actor"][0] == {"actor_id": str(person), "name": "Chan", "count": 4}


class FakeStore:
    def __init__(self) -> None:
        self.reads: list[tuple[str, tuple[object, ...]]] = []

    def home_page(
        self, actor_id: uuid.UUID, property_id: uuid.UUID, sections: Sequence[str]
    ) -> dict[str, object]:
        raise AssertionError("not used")

    def rows(
        self,
        read: str,
        actor_id: uuid.UUID,
        property_id: uuid.UUID,
        extra: Sequence[object] = (),
    ) -> list[dict[str, object]]:
        self.reads.append((read, tuple(extra)))
        return []

    def units(self, property_id: uuid.UUID) -> list[dict[str, object]]:
        return list(UNITS)

    def utility_rates(self, property_id: uuid.UUID) -> list[dict[str, object]]:
        return [{"utility_type": "WATER", "rate_usd": "0.60"}]


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


def path(name: str, query: str = "") -> str:
    return f"/api/v1/properties/{PROPERTY}/reports/{name}{query}"


STAFF = (
    "units.read",
    "leases.read",
    "reservations.read",
    "utility.read",
    "invoices.read",
    "payments.read",
    "credits.read",
    "deposits.read",
)


def test_staff_read_only_the_three_operational_reports_without_amounts() -> None:
    store = FakeStore()
    staff = client(person(*STAFF), store)
    allowed = {name: staff.get(path(name)).status_code for name in REGISTER_NAMES}
    assert allowed == {
        "invoice_register": 403,
        "payments": 403,
        "utility_consumption": 200,
        "credit_ledger": 403,
        "deposits": 403,
        "final_settlements": 403,
        "unit_occupancy": 200,
        "lease_dates": 200,
        "audit_activity": 403,
    }
    assert "rates" not in staff.get(path("utility_consumption")).json()["data"]
    assert client(None, store).get(path("lease_dates")).status_code == 401


def test_a_manager_reads_every_register_with_its_filters() -> None:
    store = FakeStore()
    manager = client(person(*STAFF, "reports.read", "audit.view"), store)
    for name in REGISTER_NAMES:
        answer = manager.get(path(name, "?floor=2&from=2026-10-01&to=2026-10-31&limit=50"))
        assert answer.status_code == 200, name
        assert answer.headers["Cache-Control"] == "private, no-store"
        data = answer.json()["data"]
        assert data["report"] == name and data["limit"] == 50
    assert ("report_audit_activity", (date(2026, 10, 1), date(2026, 10, 31))) in store.reads
    assert manager.get(path("utility_consumption")).json()["data"]["rates"][0]["rate_usd"] == "0.60"


def test_the_register_route_refuses_a_wrong_name_filter_or_page() -> None:
    manager = client(person(*STAFF, "reports.read", "audit.view"), FakeStore())
    for query in (
        "?limit=0",
        "?limit=1001",
        "?offset=-1",
        "?from=2026-05-01&to=2026-04-01",
        "?unit=all",
    ):
        assert manager.get(path("invoice_register", query)).status_code == 422, query
    assert manager.get(path("customer_list")).status_code == 422
