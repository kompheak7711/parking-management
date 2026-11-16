#!/usr/bin/env python
"""Load the design's sample data (mock-up v81, data.py) into an EMPTY test database.

UI v81 (owner 08/11/2026 09:57): a screen counts as checked only when it looks right with the
design's sample data, so the review app is filled with the same Units, people and money the
mock-up shows: Units U101 to U406 with their Unit Types and rents, the Customers' real names and
phone numbers, one signed Lease per occupied Unit with the design's dates, this month's Rent
Invoices with their payments (three still unpaid), the U406 Reservation with its Deposit and
drafted Lease, the meters and their readings, and two birthdays in the coming week.

The rows are written the way the backend's own integration tests write them (direct SQL as the
migration role). Leases, readings and payments carry the dates they would have had. An Invoice
and a payment allocation cannot be dated in the past: the database stamps the issue time and the
allocation time with the real clock and refuses an issue time before the lines were written
(app.stamp_invoice_detail_change, app.validate_invoice_issuance_lines,
app.validate_payment_allocation_source). So the Rent history of earlier months is NOT made up:
the Invoices are this month's (dated the 25th of last month, due on the 5th, issued the moment
the script runs), their payments are dated in the past week but allocated now, and "Paid on
time" counts them as paid late unless the script runs on or before the 5th. Cards such as
"Overdue" and "Paid on time" fill up as real months pass. Nothing is deleted or changed.

TEST DATABASES ONLY. The script refuses to run when the database already holds a Unit.

    cd backend && MIGRATION_DATABASE_URL=... .venv/bin/python ../scripts/local/seed-design-data.py

Options: --username <owner account> (default "owner"), --today YYYY-MM-DD (default: the
Property's business date). On the Mac test app: sh scripts/local/seed-design-data.sh.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Jsonb

PHNOM_PENH = ZoneInfo("Asia/Phnom_Penh")

# ---- The design's sample data (mock-up round 4, data.py) --------------------------------------
# (Unit number, Primary Tenant, monthly rent in USD cents); None = vacant.
UNITS: list[tuple[str, str | None, int]] = [
    ("U101", "Keo Vannak", 33000), ("U102", "Chan Sreypov", 33000), ("U103", "Lim Sophal", 34000),
    ("U104", "Heng Malis", 34000), ("U105", "Phan Rithy", 35000),
    ("U201", "Ouk Chanthy", 35000), ("U202", "Meas Sokha", 35000), ("U203", "Sok Dara", 35000),
    ("U204", "Nhem Bopha", 36000), ("U205", "Prak Visal", 36000), ("U206", "Seng Dalin", 36000),
    ("U301", "Ly Kimheng", 37000), ("U302", "Touch Sreyleak", 37000), ("U303", "Vong Piseth", 37000),
    ("U304", "Mao Sophea", 38000), ("U305", None, 0), ("U306", "Yin Rachana", 38000),
    ("U401", "Chea Monyrath", 40000), ("U402", "Hun Sovann", 40000), ("U403", "Kim Leakhena", 40000),
    ("U404", "Ros Vichet", 42000), ("U405", "Sam Nary", 42000), ("U406", None, 0),
]
PHONES = {
    n: f"0{10 + i % 8} {100 + i * 37 % 900:03d} {200 + i * 53 % 800:03d}"
    for i, (_, n, _) in enumerate(UNITS)
    if n
}
# Unit Types from docs/001 (BR-UNIT-001): x01, x02 Studio; x03, x04 One bedroom; x05 Two; x06 Three.
UNIT_TYPE = {"1": "STUDIO", "2": "STUDIO", "3": "ONE_BEDROOM", "4": "ONE_BEDROOM",
             "5": "TWO_BEDROOM", "6": "THREE_BEDROOM"}
TYPE_NAMES = {"STUDIO": ("Studio", "ស្ទូឌីយោ"), "ONE_BEDROOM": ("One bedroom", "បន្ទប់គេង 1"),
              "TWO_BEDROOM": ("Two bedroom", "បន្ទប់គេង 2"), "THREE_BEDROOM": ("Three bedroom", "បន្ទប់គេង 3")}
SIZE = {"STUDIO": 28, "ONE_BEDROOM": 36, "TWO_BEDROOM": 52, "THREE_BEDROOM": 68}
ROOMS = {"STUDIO": (0, 1), "ONE_BEDROOM": (1, 1), "TWO_BEDROOM": (2, 2), "THREE_BEDROOM": (3, 2)}
# Leases with fixed dates in the design; the others follow data.py's formula.
FIXED = {"U302": (date(2025, 12, 16), date(2026, 12, 15)), "U104": (date(2026, 1, 1), date(2026, 12, 31)),
         "U105": (date(2026, 11, 1), date(2027, 10, 31)), "U101": (date(2026, 11, 1), date(2027, 10, 31))}
OTHER_SIGNERS = {"U301": ["Ly Sokun"], "U404": ["Ros Dany"]}
EXTRA_PEOPLE = {  # name -> phone
    "Tep Sreymom": "017 455 210", "Pich Sophorn": "093 610 288", "Ly Sokun": "012 902 441",
    "Ros Dany": None, "Ouk Sreyneang": "070 318 905", "Kim Sokha": None, "Ouk Dara": None,
    "Chhay Rotha": "096 771 324", "Long Sreyneang": "011 530 862",
}
EMAILS = {"Keo Vannak": "keo.vannak@gmail.com", "Sok Dara": "sokdara@outlook.com"}
# This month's Rent Invoices still unpaid (the others are paid).
UNPAID = {"U203", "U402", "U304"}
# Birthdays in the coming week (days after today).
BIRTHDAYS = {"Ouk Chanthy": 2, "Sok Dara": 5}


def year_end(start: date) -> date:
    return start.replace(year=start.year + 1) - timedelta(days=1)


def month_end(day: date) -> date:
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def first_recurring_month(start: date) -> date:
    """The first month billed as recurring Rent: the month after the move-in month, or the one
    after that when the Lease starts after the 20th (BR-RENT-005; the move-in month is the
    Initial Rent Invoice's, which this script does not make)."""
    first = month_end(start) + timedelta(days=1)
    if start.day > 20:
        first = month_end(first) + timedelta(days=1)
    return first


def at(day: date, hour: int = 10, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=PHNOM_PENH)


def spread(key: tuple[str, str]) -> int:
    """A small stable number per Invoice, so the sample dates vary but never change."""
    return sum(map(ord, "".join(key)))


@dataclass
class Lease:
    unit: str
    tenant: str
    start: date
    end: date
    rent: int
    status: str = "SIGNED"
    predecessor: Lease | None = None
    signers: list[str] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)

    @property
    def signed_on(self) -> date:
        return self.start - timedelta(days=4)

    @property
    def drafted_on(self) -> date:
        return self.signed_on - timedelta(days=3)


def design_leases() -> list[Lease]:
    rent_of = {u: r for u, _, r in UNITS}
    occupied = [(u, n) for u, n, _ in UNITS if n]
    leases: list[Lease] = []
    for i, (u, n) in enumerate(occupied):
        if u in FIXED:
            start, end = FIXED[u]
        else:
            mm = (i * 7) % 12 + 1
            start = date(2025 if mm == 12 else 2026, mm, 1)
            end = year_end(start)
        leases.append(Lease(u, n, start, end, rent_of[u], signers=OTHER_SIGNERS.get(u, [])))
    # The U101 Lease is a renewal: the earlier one ended 31/10/2026.
    earlier = Lease("U101", "Keo Vannak", date(2025, 11, 1), date(2026, 10, 31), 32000)
    for lease in leases:
        if lease.unit == "U101":
            lease.predecessor = earlier
    leases.append(earlier)
    return leases


class Seed:
    def __init__(self, connection: psycopg.Connection[tuple[object, ...]], username: str, today: date | None):
        self.c = connection
        row = self.c.execute(
            "SELECT id, timezone(timezone_name, statement_timestamp())::date FROM app.properties"
        ).fetchone()
        if row is None:
            sys.exit("No Property yet: run scripts/local/setup-property.sh first.")
        self.property, business_date = UUID(str(row[0])), row[1]
        assert isinstance(business_date, date)
        self.today = today or business_date
        actor = self.c.execute(
            "SELECT actor_id FROM app.user_accounts WHERE normalized_username=%s", (username,)
        ).fetchone()
        if actor is None:
            sys.exit(f"No account named {username!r}: pass --username.")
        self.actor = UUID(str(actor[0]))
        self.customers: dict[str, UUID] = {}
        self.units: dict[str, UUID] = {}
        self.leases: dict[str, Lease] = {}
        self.counts: dict[str, int] = {}

    def count(self, what: str, n: int = 1) -> None:
        self.counts[what] = self.counts.get(what, 0) + n

    # -- set-up lists and Units --------------------------------------------------------------
    def setup_item(self, kind: str, code: str, name_en: str, name_km: str, order: int) -> UUID:
        found = self.c.execute(
            "SELECT id FROM app.unit_setup_items WHERE property_id=%s AND list_kind=%s AND code=%s"
            " AND removed_at IS NULL",
            (self.property, kind, code),
        ).fetchone()
        if found is not None:
            return UUID(str(found[0]))
        item = uuid4()
        self.c.execute(
            "INSERT INTO app.unit_setup_items(id,property_id,list_kind,code,name_en,name_km,"
            "sort_order,created_by,updated_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (item, self.property, kind, code, name_en, name_km, order, self.actor, self.actor),
        )
        self.count("set-up items")
        return item

    def units_and_customers(self) -> None:
        floors = {f: self.setup_item("FLOOR", f"FLOOR_{f}", f"Floor {f}", f"ជាន់ទី {f}", int(f)) for f in "1234"}
        for i, (code, (en, km)) in enumerate(TYPE_NAMES.items()):
            self.setup_item("UNIT_TYPE", code, en, km, i + 1)
        for u, n, rent in UNITS:
            unit_type = UNIT_TYPE[u[-1]]
            beds, baths = ROOMS[unit_type]
            unit = uuid4()
            self.c.execute(
                "INSERT INTO app.units(id,property_id,unit_number,floor,floor_item_id,unit_type,status,"
                "size_square_metres,bedrooms,bathrooms,default_monthly_rent_usd_cents,created_by,updated_by)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (unit, self.property, u, f"Floor {u[1]}", floors[u[1]], unit_type,
                 "OCCUPIED" if n else "VACANT", SIZE[unit_type], beds, baths, rent or None,
                 self.actor, self.actor),
            )
            self.units[u] = unit
            self.count("Units")
        people: dict[str, str | None] = {n: PHONES[n] for _, n, _ in UNITS if n}
        people.update(EXTRA_PEOPLE)
        for i, name in enumerate(sorted(people)):
            born = date(1975 + (i * 3) % 25, (i * 5) % 12 + 1, (i * 7) % 28 + 1)
            if name in BIRTHDAYS:
                soon = self.today + timedelta(days=BIRTHDAYS[name])
                born = soon.replace(year=1990)
            customer = uuid4()
            self.c.execute(
                "INSERT INTO app.customers(id,legal_name,phone_number,email_address,id_document_number,"
                "date_of_birth,gender,nationality,created_by,updated_by)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,'Cambodian',%s,%s)",
                (customer, name, people[name], EMAILS.get(name),
                 f"0{(10 + i) % 90:02d}{(123456 + i * 7919) % 1000000:06d}", born,
                 "FEMALE" if i % 2 else "MALE", self.actor, self.actor),
            )
            self.customers[name] = customer
            self.count("Customers")

    # -- Leases ------------------------------------------------------------------------------
    def lease(self, lease: Lease) -> None:
        drafted, signed = at(lease.drafted_on, 9), at(lease.signed_on, 11)
        self.c.execute(
            "INSERT INTO app.leases(id,unit_id,primary_tenant_id,start_date,end_date,"
            "monthly_rent_usd_cents,predecessor_lease_id,created_at,updated_at,created_by,updated_by)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (lease.id, self.units[lease.unit], self.customers[lease.tenant], lease.start, lease.end,
             lease.rent, None if lease.predecessor is None else lease.predecessor.id, drafted, drafted,
             self.actor, self.actor),
        )
        for name in [lease.tenant, *lease.signers]:
            self.c.execute(
                "INSERT INTO app.lease_signers(id,lease_id,customer_id,signed_at,added_at,added_by)"
                " VALUES (%s,%s,%s,%s,%s,%s)",
                (uuid4(), lease.id, self.customers[name],
                 signed if lease.status == "SIGNED" else None, drafted, self.actor),
            )
        if lease.status == "SIGNED":
            self.c.execute(
                "UPDATE app.leases SET status='SIGNED', signed_at=%s, version=version+1, updated_at=%s,"
                " updated_by=%s WHERE id=%s",
                (signed, signed, self.actor, lease.id),
            )
            if lease.start <= self.today:
                self.c.execute(
                    "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,created_at,"
                    "updated_at,created_by,updated_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (uuid4(), lease.id, self.customers[lease.tenant], lease.start,
                     at(lease.start, 14), at(lease.start, 14), self.actor, self.actor),
                )
        self.leases[str(lease.id)] = lease
        self.count("Leases")

    # -- Rent Invoices and payments ----------------------------------------------------------
    def payment_method(self) -> UUID:
        method = self.c.execute(
            "SELECT id FROM app.payment_methods WHERE accepted ORDER BY (code='CASH') DESC, code LIMIT 1"
        ).fetchone()
        if method is not None:
            return UUID(str(method[0]))
        cash = uuid4()
        self.c.execute(
            "INSERT INTO app.payment_methods(id,code,display_name,accepted,created_by,updated_by)"
            " VALUES (%s,'CASH','Cash',true,%s,%s)",
            (cash, self.actor, self.actor),
        )
        self.count("payment methods")
        return cash

    def invoice(self, lease: Lease, period_start: date) -> tuple[UUID, UUID]:
        """One recurring Rent Invoice for the month: dated the 25th of the month before (the billing
        day), due on the 5th, issued now (the database allows no earlier issue time)."""
        period_end = month_end(period_start)
        due = period_start + timedelta(days=4)
        invoice_date = (period_start - timedelta(days=1)).replace(day=25)
        invoice, line = uuid4(), uuid4()
        self.c.execute(
            "INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,primary_category,status,"
            "invoice_date,due_date,billing_period_start,billing_period_end,rent_billing_kind,"
            "original_total_usd_cents,due_date_rule,due_date_source,created_by,updated_by)"
            " VALUES (%s,%s,%s,%s,'RENT','DRAFT',%s,%s,%s,%s,'RECURRING',%s,"
            "'RECURRING_RENT_FIFTH','BR-RENT-018',%s,%s)",
            (invoice, f"SEED-{invoice.hex[:12]}", self.customers[lease.tenant], lease.id, invoice_date, due,
             period_start, period_end, lease.rent, self.actor, self.actor),
        )
        self.c.execute(
            "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,"
            "amount_usd_cents,period_start,period_end,source_lease_id,contractual_monthly_usd_cents,"
            "billable_days,calendar_days,calculation_trace,created_by)"
            " VALUES (%s,%s,1,'RENT','Monthly Rent',%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (line, invoice, lease.rent, period_start, period_end, lease.id, lease.rent, period_end.day,
             period_end.day, Jsonb({"formula": "monthly_rent", "amount_usd_cents": lease.rent}), self.actor),
        )
        self.c.execute(
            "INSERT INTO app.invoice_line_calculation_components(id,invoice_line_id,component_sequence,"
            "component_kind,period_start,period_end,contractual_monthly_usd_cents,billable_days,"
            "calendar_days,amount_usd_cents,calculation_trace,created_by)"
            " VALUES (%s,%s,1,'FULL_RECURRING_MONTH',%s,%s,%s,%s,%s,%s,%s,%s)",
            (uuid4(), line, period_start, period_end, lease.rent, period_end.day, period_end.day,
             lease.rent, Jsonb({"formula": "monthly_rent", "amount_usd_cents": lease.rent}), self.actor),
        )
        # The issue time is the database's own: it must not be before the lines were written.
        self.c.execute(
            "UPDATE app.invoices SET status='UNPAID', issued_at=statement_timestamp(), issued_by=%s,"
            " version=2, updated_at=statement_timestamp(), updated_by=%s WHERE id=%s",
            (self.actor, self.actor, invoice),
        )
        self.count("Rent Invoices")
        return invoice, line

    def pay(self, lease: Lease, invoice: UUID, line: UUID, when: datetime, method: UUID) -> None:
        payment = uuid4()
        customer = self.customers[lease.tenant]
        self.c.execute(
            "INSERT INTO app.payments(id,payment_number,property_id,payer_customer_id,payment_scope_kind,"
            "payment_date,payment_method_id,received_currency,received_amount_minor,"
            "usd_accounting_value_cents,confirmed_at,confirmed_by,authorization_reference,lease_id,"
            "identified_invoice_id) VALUES (%s,%s,%s,%s,'NORMAL_CUSTOMER',%s,%s,'USD',%s,%s,%s,%s,"
            "'payments.record',%s,%s)",
            (payment, f"SEED-{payment.hex[:12]}", self.property, customer, when.date(), method,
             lease.rent, lease.rent, when, self.actor, lease.id, invoice),
        )
        allocation = uuid4()
        # An allocation is posted at the database's time, never before the Invoice was issued.
        self.c.execute(
            "INSERT INTO app.payment_allocations(id,payment_id,target_customer_id,target_kind,invoice_id,"
            "amount_usd_cents,between_invoice_basis,within_invoice_basis,customer_designation_reference,"
            "posted_at,posted_by,authorization_reference) VALUES (%s,%s,%s,'INVOICE',%s,%s,"
            "'CUSTOMER_DESIGNATED','CUSTOMER_DESIGNATED','Paid for this Invoice',statement_timestamp(),%s,"
            "'payments.allocate')",
            (allocation, payment, customer, invoice, lease.rent, self.actor),
        )
        self.c.execute(
            "INSERT INTO app.payment_allocation_details(id,payment_allocation_id,invoice_line_id,"
            "obligation_kind,invoice_line_category_snapshot,posted_amount_usd_cents,attribution_basis,"
            "detail_sequence,calculation_trace) VALUES (%s,%s,%s,'INVOICE_LINE','RENT',%s,"
            "'CUSTOMER_DESIGNATED',1,%s)",
            (uuid4(), allocation, line, lease.rent,
             Jsonb({"designation_reference": "Paid for this Invoice", "seed": True})),
        )
        self.c.execute("SELECT app.refresh_allocated_invoice(%s,%s,true)", (invoice, self.actor))
        self.count("payments")

    def rent_history(self) -> None:
        """This month's Rent Invoice of every signed Lease; most are paid in the past week."""
        now = datetime.now(PHNOM_PENH) - timedelta(minutes=1)
        method = self.payment_method()
        period = self.today.replace(day=1)
        payments: list[tuple[datetime, Lease, UUID, UUID]] = []
        for lease in sorted(self.leases.values(), key=lambda lease: lease.unit):
            # A Lease that started this month has no recurring Invoice yet (its first month is
            # the Initial Rent Invoice's).
            if lease.status != "SIGNED" or first_recurring_month(lease.start) > period or lease.end < month_end(period):
                continue
            invoice, line = self.invoice(lease, period)
            if lease.unit in UNPAID:
                continue
            key = (lease.unit, period.strftime("%Y-%m"))
            paid_on = self.today - timedelta(days=spread(key) % 7)
            # The database refuses a payment confirmed in the future: a sample time later today
            # moves back to a minute ago.
            when = min(at(paid_on, 8 + spread(key) % 9, spread(key) % 60), now)
            payments.append((when, lease, invoice, line))
        payments.sort(key=lambda payment: payment[0])
        for when, lease, invoice, line in payments:
            self.pay(lease, invoice, line, when, method)

    # -- the U406 Reservation ------------------------------------------------------------------
    def reservation(self) -> None:
        unit, customer = self.units["U406"], self.customers["Tep Sreymom"]
        reserved_on, expires = self.today - timedelta(days=10), self.today + timedelta(days=4)
        reservation, acceptance, deposit = uuid4(), uuid4(), uuid4()
        made = at(reserved_on, 15, 40)
        self.c.execute(
            "INSERT INTO app.reservations(id,unit_id,customer_id,reservation_date,"
            "agreed_monthly_rent_usd_cents,original_expiration_date,effective_expiration_date,status,"
            "created_at,created_by,updated_at,updated_by) VALUES (%s,%s,%s,%s,50000,%s,%s,'ACTIVE',"
            "%s,%s,%s,%s)",
            (reservation, unit, customer, reserved_on, expires, expires, made, self.actor, made, self.actor),
        )
        self.c.execute(
            "INSERT INTO app.reservation_deposit_acceptances(id,reservation_id,suggested_rate_basis_points,"
            "suggested_amount_usd_cents,accepted_required_amount_usd_cents,acceptance_kind,accepted_at,"
            "accepted_by,reason,authorization_reference,calculation_trace) VALUES (%s,%s,2000,10000,"
            "10000,'NORMAL_SUGGESTION',%s,%s,'Holding deposit agreed at the office',"
            "'reservations.manage',%s)",
            (acceptance, reservation, made, self.actor,
             Jsonb({"agreed_monthly_rent_usd_cents": 50000, "suggested_rate_basis_points": 2000,
                    "suggested_amount_usd_cents": 10000})),
        )
        self.c.execute(
            "INSERT INTO app.deposits(id,deposit_type,customer_id,reservation_id,required_usd_cents,"
            "required_effective_date,created_at,updated_at,created_by,updated_by)"
            " VALUES (%s,'SECURITY',%s,%s,50000,%s,%s,%s,%s,%s)",
            (deposit, customer, reservation, reserved_on, made, made, self.actor, self.actor),
        )
        payment = uuid4()
        self.c.execute(
            "INSERT INTO app.payments(id,payment_number,property_id,payer_customer_id,payment_scope_kind,"
            "payment_date,payment_method_id,received_currency,received_amount_minor,"
            "usd_accounting_value_cents,confirmed_at,confirmed_by,authorization_reference)"
            " VALUES (%s,%s,%s,%s,'NORMAL_CUSTOMER',%s,%s,'USD',10000,10000,%s,%s,'payments.record')",
            (payment, f"SEED-{payment.hex[:12]}", self.property, customer, reserved_on,
             self.payment_method(), made, self.actor),
        )
        self.c.execute(
            "INSERT INTO app.deposit_receipts(id,deposit_id,payment_id,amount_usd_cents,occurred_at,actor_id)"
            " VALUES (%s,%s,%s,10000,%s,%s)",
            (uuid4(), deposit, payment, made + timedelta(minutes=1), self.actor),
        )
        self.c.execute(
            "UPDATE app.units SET status='RESERVED', version=version+1,"
            " updated_at=statement_timestamp(), updated_by=%s WHERE id=%s",
            (self.actor, unit),
        )
        # Her Lease is drafted, not signed yet.
        self.lease(Lease("U406", "Tep Sreymom", self.today + timedelta(days=4),
                         year_end(self.today + timedelta(days=4)), 50000, status="DRAFTED"))
        self.count("Reservations")

    # -- meters and readings -------------------------------------------------------------------
    def meters(self) -> None:
        for i, (u, _, _) in enumerate(UNITS):
            for kind, code, start, step in (("ELECTRICITY", "KWH", 9000 + i * 713, 150 + (i * 37) % 170),
                                            ("WATER", "M3", 400 + i * 29, 5 + (i * 3) % 8)):
                meter = uuid4()
                serial = f"{kind[:2]}-{u}"
                self.c.execute(
                    "INSERT INTO app.utility_meters(id,unit_id,serial_number,utility_type,"
                    "measurement_unit_code,installed_date,created_by,updated_by)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (meter, self.units[u], serial, kind, code, date(2025, 1, 1), self.actor, self.actor),
                )
                value = start
                for month in range(3, 11):  # 24/03/2026 … 24/10/2026
                    day = date(2026, month, 24)
                    self.c.execute(
                        "INSERT INTO app.utility_readings(id,meter_id,reading_date,reading_value,created_at,"
                        "updated_at,created_by,updated_by,source_kind,source_evidence)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'MANUAL','Reading day')",
                        (uuid4(), meter, day, value, at(day, 9), at(day, 9), self.actor, self.actor),
                    )
                    value += step
                self.count("meters")

    def run(self) -> None:
        if self.c.execute("SELECT 1 FROM app.units LIMIT 1").fetchone() is not None:
            sys.exit("This database already holds Units. The design data goes into an EMPTY test database only.")
        self.c.execute("SET CONSTRAINTS ALL DEFERRED")
        self.units_and_customers()
        for lease in sorted(design_leases(), key=lambda lease: (lease.start, lease.unit)):
            self.lease(lease)
        self.rent_history()
        self.reservation()
        self.meters()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--username", default="owner", help="the account the rows are made by")
    parser.add_argument("--today", type=date.fromisoformat, default=None)
    parser.add_argument("--url", default=os.environ.get("MIGRATION_DATABASE_URL"),
                        help="the migration role's database address (MIGRATION_DATABASE_URL)")
    args = parser.parse_args()
    if not args.url:
        sys.exit("Set MIGRATION_DATABASE_URL or pass --url.")
    url = args.url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(url) as connection:
        seed = Seed(connection, args.username, args.today)
        seed.run()
        connection.commit()
    print(json.dumps({"today": seed.today.isoformat(), **seed.counts}, indent=1))


if __name__ == "__main__":
    main()
