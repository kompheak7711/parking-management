"""V1-057 reads: the Home page, the reports and the audit search record (API-076, API-077, DL-072,
DL-079).

The runtime role reads the records only through the bounded definer functions of migration
`20270301_220` and later: the database checks the active person and that the Property is one the
application passes from the person's grants; this module checks the capabilities. Amounts are
integer USD cents (DL-060); nothing here writes a financial record.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Final, Protocol, cast
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.types.json import set_json_loads

from property_rental.access_control import UNITS_READ_CAPABILITY
from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized
from property_rental.report_registers import (
    REGISTER_READS,
    RegisterFilter,
    RegisterName,
    build_register,
)
from property_rental.report_totals import (
    UTILITY_TYPES,
    TotalsFilter,
    TotalsReport,
    build_totals,
    income_facts,
    payment_facts,
    utility_facts,
)

REPORTS_READ_CAPABILITY: Final = "reports.read"
AUDIT_EXPORT_CAPABILITY: Final = "audit.export"
DATA_EXPORT_CAPABILITY: Final = "data.export"

# Each Home section and the read rights that show it (any one of them). A section the person may
# not read is left out whole, never shown as zero (DL-079 answer 9; DL-072 answer 5).
HOME_SECTIONS: Final[Mapping[str, tuple[str, ...]]] = {
    "units": (UNITS_READ_CAPABILITY,),
    "invoices": ("invoices.read",),
    "payments": ("payments.read",),
    "leases": ("leases.read",),
    "reservations": ("reservations.read",),
    "approvals": ("financial.approve",),
    "deposit_decisions": ("reservation_deposits.dispose", "financial.approve"),
    "readings": ("utility.read",),
    "letters": ("rent_nonpayment.read",),
    "settlements": ("final_settlements.prepare", "financial.approve"),
}
TODO_GROUPS: Final = ("overdue", "today", "this_week", "later")
# Items dated by when a wait began (not a due day) stay under Today while they wait; the screen
# shows how long ago (DESIGN.md Home).
WAITING_KINDS: Final = frozenset({"draft_waiting", "deposit_decision", "settlement_open"})


class ReportUnavailableError(RuntimeError):
    """The report store cannot answer now."""


class ReportForbiddenError(PermissionError):
    """The person may not read this report for this Property."""


class ReportNotFoundError(LookupError):
    pass


class ReportInvalidError(ValueError):
    """The report request is outside its bounds."""


def _exact_json(value: str | bytes) -> object:
    # Amounts stay exact: a JSON number with a fraction is kept as text, never a float.
    return json.loads(value, parse_float=str)


def has_capability(actor: AuthenticatedActor, capability: str, property_id: UUID) -> bool:
    return is_authorized(actor, AuthorizationRequirement(capability, str(property_id)))


def home_sections(actor: AuthenticatedActor, property_id: UUID) -> tuple[str, ...]:
    """The Home sections this person may see for the Property, in a fixed order."""
    return tuple(
        section
        for section, capabilities in HOME_SECTIONS.items()
        if any(has_capability(actor, capability, property_id) for capability in capabilities)
    )


def todo_group(day: date, today: date) -> str:
    """Overdue, Today, This week (the next six days) or Later (DL-079 answer 9)."""
    if day < today:
        return "overdue"
    if day == today:
        return "today"
    if (day - today).days <= 6:
        return "this_week"
    return "later"


def group_home_page(page: Mapping[str, object]) -> dict[str, object]:
    """Add the to-do group to each dated item and a count per group."""
    today = date.fromisoformat(str(page["business_date"]))
    items = page.get("todo")
    if not isinstance(items, list):
        raise ReportUnavailableError("Home page answer is invalid")
    grouped: list[dict[str, object]] = []
    counts = dict.fromkeys(TODO_GROUPS, 0)
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("date"), str):
            raise ReportUnavailableError("Home page answer is invalid")
        day = date.fromisoformat(cast(str, item["date"]))
        if item.get("kind") in WAITING_KINDS and day <= today:
            group = "today"
        else:
            group = todo_group(day, today)
        counts[group] += 1
        grouped.append({**cast(dict[str, object], item), "group": group})
    return {**page, "todo": grouped, "todo_counts": counts}


# The bounded definer reads a report may call, by name (migration `20270302_221` and later).
REPORT_READS: Final = frozenset(
    {
        "report_income_facts",
        "report_payment_facts",
        "report_utility_facts",
        *REGISTER_READS.values(),
    }
)
# The rights each register needs (all of them). Money registers need `reports.read`; the Staff
# reports need the read rights of their records (DL-072 answer 5); Audit activity needs the
# audit search right. Utility consumption shows amounts and Rates only with `reports.read`.
REGISTER_RIGHTS: Final[Mapping[str, tuple[str, ...]]] = {
    "invoice_register": (REPORTS_READ_CAPABILITY,),
    "payments": (REPORTS_READ_CAPABILITY,),
    "credit_ledger": (REPORTS_READ_CAPABILITY,),
    "deposits": (REPORTS_READ_CAPABILITY,),
    "final_settlements": (REPORTS_READ_CAPABILITY,),
    "utility_consumption": ("utility.read",),
    "unit_occupancy": (UNITS_READ_CAPABILITY, "leases.read", "reservations.read"),
    "lease_dates": ("leases.read",),
    "audit_activity": ("audit.view",),
}


class ReportStore(Protocol):
    def home_page(
        self, actor_id: UUID, property_id: UUID, sections: Sequence[str]
    ) -> dict[str, object]: ...

    def rows(
        self, read: str, actor_id: UUID, property_id: UUID, extra: Sequence[object] = ()
    ) -> list[dict[str, object]]: ...

    def units(self, property_id: UUID) -> list[dict[str, object]]: ...

    def utility_rates(self, property_id: UUID) -> list[dict[str, object]]: ...


@dataclass(frozen=True, slots=True)
class PostgresReportStore:
    """One bounded read-only transaction per call, through the definer functions only."""

    database_url: str

    @contextmanager
    def _read(self) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
        try:
            with psycopg.connect(self.database_url, connect_timeout=3) as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='15000ms'")
                connection.execute("SET LOCAL TIME ZONE 'UTC'")
                set_json_loads(_exact_json, connection)
                yield connection
        except psycopg.Error as exc:
            if exc.sqlstate == "42501":
                raise ReportForbiddenError("Report access is denied") from exc
            if exc.sqlstate == "22023":
                raise ReportInvalidError("Report request is invalid") from exc
            raise ReportUnavailableError("Reports are unavailable") from exc

    def home_page(
        self, actor_id: UUID, property_id: UUID, sections: Sequence[str]
    ) -> dict[str, object]:
        with self._read() as connection:
            row = connection.execute(
                "SELECT app.home_page(%s,%s,%s::uuid[],%s::text[])",
                (actor_id, property_id, [property_id], list(sections)),
            ).fetchone()
        if row is None or not isinstance(row[0], dict):
            raise ReportUnavailableError("Home page answer is invalid")
        return cast(dict[str, object], row[0])

    def rows(
        self, read: str, actor_id: UUID, property_id: UUID, extra: Sequence[object] = ()
    ) -> list[dict[str, object]]:
        if read not in REPORT_READS:
            raise ReportInvalidError("Unknown report read")
        arguments = sql.SQL("%s,%s,%s::uuid[]") + sql.SQL("").join(sql.SQL(",%s") for _ in extra)
        with self._read() as connection:
            cursor = connection.execute(
                sql.SQL("SELECT * FROM app.{}({})").format(sql.Identifier(read), arguments),
                (actor_id, property_id, [property_id], *extra),
            )
            names = [column.name for column in cursor.description or ()]
            return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    def units(self, property_id: UUID) -> list[dict[str, object]]:
        with self._read() as connection:
            cursor = connection.execute(
                "SELECT id,unit_number,floor,unit_type,status FROM app.units "
                "WHERE property_id=%s ORDER BY unit_number,id",
                (property_id,),
            )
            names = [column.name for column in cursor.description or ()]
            return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    def utility_rates(self, property_id: UUID) -> list[dict[str, object]]:
        with self._read() as connection:
            cursor = connection.execute(
                "SELECT utility_type,measurement_unit_code,rate_usd_per_unit::text AS rate_usd,"
                "effective_date FROM app.utility_rates WHERE property_id=%s "
                "ORDER BY effective_date DESC,utility_type,id",
                (property_id,),
            )
            names = [column.name for column in cursor.description or ()]
            return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


class UnavailableReportStore:
    def home_page(
        self, actor_id: UUID, property_id: UUID, sections: Sequence[str]
    ) -> dict[str, object]:
        del actor_id, property_id, sections
        raise ReportUnavailableError("Reports are unavailable")

    def rows(
        self, read: str, actor_id: UUID, property_id: UUID, extra: Sequence[object] = ()
    ) -> list[dict[str, object]]:
        del read, actor_id, property_id, extra
        raise ReportUnavailableError("Reports are unavailable")

    def units(self, property_id: UUID) -> list[dict[str, object]]:
        del property_id
        raise ReportUnavailableError("Reports are unavailable")

    def utility_rates(self, property_id: UUID) -> list[dict[str, object]]:
        del property_id
        raise ReportUnavailableError("Reports are unavailable")


@dataclass(frozen=True, slots=True)
class ReportService:
    store: ReportStore

    def home_page(self, actor: AuthenticatedActor, property_id: UUID) -> dict[str, object]:
        sections = home_sections(actor, property_id)
        if not sections:
            raise ReportForbiddenError("Home page needs a read right")
        page = self.store.home_page(UUID(actor.actor_id), property_id, sections)
        return {**group_home_page(page), "sections": list(sections)}

    def totals(
        self,
        actor: AuthenticatedActor,
        property_id: UUID,
        report: TotalsReport,
        chosen: TotalsFilter,
    ) -> dict[str, object]:
        """One of the four "Totals by Unit and month" reports (DL-079 answers 1 to 4)."""
        if not has_capability(actor, REPORTS_READ_CAPABILITY, property_id):
            raise ReportForbiddenError("Totals need reports.read")
        if (
            chosen.from_date is not None
            and chosen.to_date is not None
            and chosen.from_date > chosen.to_date
        ):
            raise ReportInvalidError("From is after To")
        actor_id = UUID(actor.actor_id)
        if report == "total_income":
            facts = income_facts(self.store.rows("report_income_facts", actor_id, property_id))
        elif report == "total_payment":
            facts = payment_facts(self.store.rows("report_payment_facts", actor_id, property_id))
        else:
            facts = utility_facts(
                self.store.rows("report_utility_facts", actor_id, property_id),
                UTILITY_TYPES[report],
            )
        units = self.store.units(property_id)
        if chosen.unit_id is not None and all(
            str(unit["id"]) != str(chosen.unit_id) for unit in units
        ):
            raise ReportInvalidError("Unknown Unit")
        return build_totals(report, facts, units, chosen)

    def register(
        self,
        actor: AuthenticatedActor,
        property_id: UUID,
        name: RegisterName,
        chosen: RegisterFilter,
    ) -> dict[str, object]:
        """One of the nine registers and lists (DL-079 answer 5)."""
        if not all(has_capability(actor, right, property_id) for right in REGISTER_RIGHTS[name]):
            raise ReportForbiddenError("The register needs its read rights")
        if (
            chosen.from_date is not None
            and chosen.to_date is not None
            and chosen.from_date > chosen.to_date
        ):
            raise ReportInvalidError("From is after To")
        actor_id = UUID(actor.actor_id)
        extra: tuple[object, ...] = ()
        if name == "audit_activity":
            extra = (chosen.from_date, chosen.to_date)
        rows = self.store.rows(REGISTER_READS[name], actor_id, property_id, extra)
        money = has_capability(actor, REPORTS_READ_CAPABILITY, property_id)
        page = build_register(name, rows, self.store.units(property_id), chosen, money=money)
        if name == "utility_consumption" and money:
            page["rates"] = self.store.utility_rates(property_id)
        return page
