"""What goes into an export file: the title, the lines above the table and the table rows
(DL-072 answers 3 to 6, 11 and 12; UI-087, UI-089).

A small export (up to `INLINE_ROWS` rows) downloads at once and is not stored; a larger one is
kept 24 hours for the person who made it (an export job, API-078). Every export writes an
audit event with its filters, row count and SHA-256 fingerprint.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Final, Protocol, cast
from uuid import UUID, uuid4

import psycopg

from property_rental.audit import _freeze_audit_value, public_audit_filters
from property_rental.identity import AuthenticatedActor
from property_rental.report_files import (
    AUDIT_COLUMNS,
    REGISTER_COLUMNS,
    Column,
    ExportFile,
    FileType,
    build_file,
    totals_columns,
)
from property_rental.report_registers import REGISTER_NAMES, RegisterFilter
from property_rental.report_totals import TOTALS_REPORTS, UTILITY_TYPES, TotalsFilter
from property_rental.reports import (
    AUDIT_EXPORT_CAPABILITY,
    DATA_EXPORT_CAPABILITY,
    REPORTS_READ_CAPABILITY,
    ReportActor,
    ReportForbiddenError,
    ReportInvalidError,
    ReportNotFoundError,
    ReportService,
    ReportUnavailableError,
    has_capability,
    report_actor,
)

INLINE_ROWS: Final = 1000
MAX_EXPORT_ROWS: Final = 50_000
# A PDF table is slow to lay out, so a PDF holds fewer rows than a spreadsheet; a kept file is at
# most 25 MiB, the limit of `app.report_export_files`.
MAX_PDF_ROWS: Final = 5_000
MAX_FILE_BYTES: Final = 25 * 1024 * 1024

TITLES: Final[Mapping[str, str]] = {
    "total_income": "Total Income by month",
    "total_payment": "Total Payment by month",
    "total_electricity": "Total Electricity by month",
    "total_water": "Total Water by month",
    "invoice_register": "Invoice register and balances",
    "payments": "Payments and allocations",
    "utility_consumption": "Utility consumption",
    "credit_ledger": "Customer Credit ledger",
    "deposits": "Deposit liability and disposition",
    "final_settlements": "Final Settlement register",
    "unit_occupancy": "Unit occupancy",
    "lease_dates": "Lease dates",
    "audit_activity": "Audit activity",
    "audit": "Audit history",
}
LINE_NAMES: Final[Mapping[str, str]] = {
    "INVOICES": "Invoices",
    "LATE_PAYMENT_CHARGES": "Late-payment charges",
    "DEPOSITS": "Deposits",
    "CREDIT": "Customer Credit",
    "REFUNDED": "Refunded",
    "NOT_ALLOCATED": "Not allocated",
    "REVERSED_LATER": "Received, reversed later",
}


@dataclass(frozen=True, slots=True)
class ExportRequest:
    report: str
    file_type: FileType
    floor: str | None = None
    unit_id: UUID | None = None
    from_date: date | None = None
    to_date: date | None = None


@dataclass(frozen=True, slots=True)
class AuditExportRequest:
    file_type: FileType
    from_date: date | None = None
    to_date: date | None = None
    actor_id: UUID | None = None
    action: str | None = None
    unit_id: UUID | None = None


def _day(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def heading_lines(
    *,
    generated_at: datetime,
    floor: str | None = None,
    unit_number: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    period_applies: bool = True,
    money: bool = True,
) -> list[str]:
    """The lines every report shows: scope, period, when it was made and the currency."""
    scope = (
        f"Unit {unit_number}" if unit_number else (f"Floor {floor}" if floor else "Whole Property")
    )
    if not period_applies:
        period = f"As of {_day(generated_at.date())}"
    elif from_date and to_date:
        period = f"{_day(from_date)} to {_day(to_date)}"
    elif from_date:
        period = f"From {_day(from_date)}"
    elif to_date:
        period = f"Up to {_day(to_date)}"
    else:
        period = "All dates"
    lines = [
        f"Scope: {scope}",
        f"Period: {period}",
        f"Generated {generated_at.strftime('%d/%m/%Y %H:%M')}, Property local time",
    ]
    if money:
        lines.append("Amounts in USD; riel shown as information only.")
    return lines


def _money(cents: int) -> str:
    amount = Decimal(cents) / 100
    return f"-${-amount:,.2f}" if amount < 0 else f"${amount:,.2f}"


def paid_for(parts: object) -> str:
    """The "Paid for" text of a Payment row: each line with its amount."""
    if not isinstance(parts, list):
        return ""
    texts = []
    for part in cast(list[Mapping[str, object]], parts):
        name = LINE_NAMES.get(str(part.get("kind")), str(part.get("kind")))
        category = part.get("category")
        label = f"{name} {str(category).replace('_', ' ').title()}" if category else name
        texts.append(f"{label} {_money(int(str(part.get('amount_usd_cents') or 0)))}")
    return "; ".join(texts)


def totals_rows(page: Mapping[str, object], quantities: bool) -> list[dict[str, object]]:
    """The year rows of a Totals table; a Utility table has a quantity row and a USD row."""
    rows: list[dict[str, object]] = []
    measurement = "kWh" if page.get("report") == "total_electricity" else "m³"
    for year in cast(Sequence[Mapping[str, object]], page["years"]):
        months = cast(Sequence[object], year["months"])
        if quantities:
            quantity = cast(Sequence[object], year["quantities"])
            rows.append(
                {
                    "year": year["year"],
                    "what": measurement,
                    **{f"m{index}": value for index, value in enumerate(quantity, start=1)},
                    "total": year["total_quantity"],
                }
            )
            rows.append(
                {
                    "year": year["year"],
                    "what": "USD",
                    **{
                        f"m{index}": None if value is None else Decimal(int(str(value))) / 100
                        for index, value in enumerate(months, start=1)
                    },
                    "total": Decimal(int(str(year["total"]))) / 100,
                }
            )
        else:
            rows.append(
                {
                    "year": year["year"],
                    **{f"m{index}": value for index, value in enumerate(months, start=1)},
                    "total": year["total"],
                }
            )
    return rows


def file_base_name(report: str, generated_at: datetime) -> str:
    return f"{report}_{generated_at.strftime('%Y%m%d_%H%M')}"


def export_details(
    *,
    export_id: UUID,
    report: str,
    file_type: str,
    row_count: int,
    sha256: str,
    delivery: str,
    filters: Mapping[str, object],
) -> dict[str, object]:
    """The details the export's own audit event keeps (DL-072 answers 12 and 14)."""
    return {
        "export_id": str(export_id),
        "report_kind": report,
        "file_type": file_type,
        "row_count": row_count,
        "file_sha256": sha256,
        "delivery_kind": delivery,
        # Keys the audit value rules accept: dates, ids, the action and the floor as a label.
        "filters": public_audit_filters(
            {
                ("floor_label" if key == "floor" else key): (
                    value.isoformat() if isinstance(value, date) else str(value)
                )
                for key, value in filters.items()
                if value is not None
            }
        ),
    }


@dataclass(frozen=True, slots=True)
class ExportResult:
    """A file to download now, or the export job that keeps it 24 hours."""

    export_id: UUID
    file: ExportFile
    expires_at: datetime | None = None


class ExportStore(Protocol):
    def generated_at(self, property_id: UUID) -> datetime: ...

    def record(
        self,
        actor: ReportActor,
        property_id: UUID,
        kind: str,
        capability: str,
        details: dict[str, object],
    ) -> None: ...

    def save(
        self,
        actor: ReportActor,
        property_id: UUID,
        export_id: UUID,
        report: str,
        file_type: FileType,
        file: ExportFile,
        kind: str,
        capability: str,
        details: dict[str, object],
    ) -> datetime: ...

    def take(
        self, actor: ReportActor, property_id: UUID, export_id: UUID
    ) -> dict[str, object] | None: ...

    def audit_rows(
        self, property_id: UUID, request: AuditExportRequest
    ) -> list[dict[str, object]]: ...


def _sql_rows(cursor: psycopg.Cursor[tuple[object, ...]]) -> list[dict[str, object]]:
    names = [column.name for column in cursor.description or ()]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


@dataclass(frozen=True, slots=True)
class PostgresExportStore:
    """Audit records and export files through the definer functions of migration 224."""

    database_url: str

    @contextmanager
    def _connect(self) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
        try:
            with psycopg.connect(self.database_url, connect_timeout=3) as connection:
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='30000ms'")
                yield connection
        except psycopg.Error as exc:
            if exc.sqlstate == "42501":
                raise ReportForbiddenError("Export is denied") from exc
            if exc.sqlstate == "22023":
                raise ReportInvalidError("Export request is invalid") from exc
            raise ReportUnavailableError("Exports are unavailable") from exc

    def generated_at(self, property_id: UUID) -> datetime:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT timezone(timezone_name, statement_timestamp()) FROM app.properties "
                "WHERE id=%s",
                (property_id,),
            ).fetchone()
        if row is None or not isinstance(row[0], datetime):
            raise ReportForbiddenError("Unknown Property")
        return row[0]

    @staticmethod
    def _record(
        connection: psycopg.Connection[tuple[object, ...]],
        actor: ReportActor,
        property_id: UUID,
        kind: str,
        capability: str,
        details: dict[str, object],
    ) -> None:
        try:
            # The History page must be able to read this event back.
            _freeze_audit_value(details, "resulting_state")
        except (TypeError, ValueError) as exc:
            # The filters are already cleaned, so this is a fault in this code, not the request.
            raise ReportUnavailableError("Export details are not audit values") from exc
        connection.execute(
            "SELECT app.record_report_activity(%s,%s,%s::uuid[],%s,%s,%s::jsonb,%s)",
            (
                actor.actor_id,
                property_id,
                list(actor.property_ids),
                kind,
                capability,
                json.dumps(details),
                uuid4(),
            ),
        )

    def record(
        self,
        actor: ReportActor,
        property_id: UUID,
        kind: str,
        capability: str,
        details: dict[str, object],
    ) -> None:
        with self._connect() as connection:
            self._record(connection, actor, property_id, kind, capability, details)

    def save(
        self,
        actor: ReportActor,
        property_id: UUID,
        export_id: UUID,
        report: str,
        file_type: FileType,
        file: ExportFile,
        kind: str,
        capability: str,
        details: dict[str, object],
    ) -> datetime:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT app.store_report_export(%s,%s,%s::uuid[],%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    actor.actor_id,
                    property_id,
                    list(actor.property_ids),
                    export_id,
                    report,
                    file_type,
                    file.file_name,
                    file.media_type,
                    file.content,
                    file.sha256,
                    file.row_count,
                ),
            ).fetchone()
            self._record(connection, actor, property_id, kind, capability, details)
        if row is None or not isinstance(row[0], datetime):
            raise ReportUnavailableError("Export file was not kept")
        return row[0]

    def take(
        self, actor: ReportActor, property_id: UUID, export_id: UUID
    ) -> dict[str, object] | None:
        with self._connect() as connection:
            rows = _sql_rows(
                connection.execute(
                    "SELECT * FROM app.take_report_export(%s,%s,%s::uuid[],%s)",
                    (actor.actor_id, property_id, list(actor.property_ids), export_id),
                )
            )
        return rows[0] if rows else None

    def audit_rows(self, property_id: UUID, request: AuditExportRequest) -> list[dict[str, object]]:
        clauses = ["event.property_id=%s"]
        parameters: list[object] = [property_id]
        for clause, value in (
            ("event.business_date>=%s", request.from_date),
            ("event.business_date<=%s", request.to_date),
            ("event.actor_id=%s", request.actor_id),
            ("event.action=%s", request.action),
        ):
            if value is not None:
                clauses.append(clause)
                parameters.append(value)
        if request.unit_id is not None:
            # The same Unit filter as the History page: events about the Unit and its own record.
            clauses.append(
                "(event.unit_id=%s OR (event.entity_type='unit' AND event.entity_id=%s))"
            )
            parameters.extend((request.unit_id, request.unit_id))
        parameters.append(MAX_EXPORT_ROWS + 1)
        with self._connect() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            return _sql_rows(
                connection.execute(
                    "SELECT timezone(property.timezone_name, event.occurred_at) AS occurred_at,"
                    "COALESCE(account.display_name,'System') AS actor_name,event.action,"
                    "event.entity_type,event.entity_id,unit.unit_number,"
                    "customer.legal_name AS customer_name,event.reason,event.outcome "
                    "FROM app.audit_events event "
                    "JOIN app.properties property ON property.id=event.property_id "
                    "LEFT JOIN app.user_accounts account ON account.actor_id=event.actor_id "
                    "LEFT JOIN app.units unit ON unit.id=COALESCE(event.unit_id,"
                    "CASE WHEN event.entity_type='unit' THEN event.entity_id END) "
                    "LEFT JOIN app.customers customer ON customer.id=event.customer_id "
                    f"WHERE {' AND '.join(clauses)} "
                    "ORDER BY event.occurred_at DESC,event.id DESC LIMIT %s",
                    tuple(parameters),
                )
            )


class UnavailableExportStore:
    def generated_at(self, property_id: UUID) -> datetime:
        raise ReportUnavailableError("Exports are unavailable")

    def record(
        self,
        actor: ReportActor,
        property_id: UUID,
        kind: str,
        capability: str,
        details: dict[str, object],
    ) -> None:
        raise ReportUnavailableError("Exports are unavailable")

    def save(
        self,
        actor: ReportActor,
        property_id: UUID,
        export_id: UUID,
        report: str,
        file_type: FileType,
        file: ExportFile,
        kind: str,
        capability: str,
        details: dict[str, object],
    ) -> datetime:
        raise ReportUnavailableError("Exports are unavailable")

    def take(
        self, actor: ReportActor, property_id: UUID, export_id: UUID
    ) -> dict[str, object] | None:
        raise ReportUnavailableError("Exports are unavailable")

    def audit_rows(self, property_id: UUID, request: AuditExportRequest) -> list[dict[str, object]]:
        raise ReportUnavailableError("Exports are unavailable")


def _check_rows(file_type: FileType, row_count: int) -> None:
    limit = MAX_PDF_ROWS if file_type == "pdf" else MAX_EXPORT_ROWS
    if row_count > limit:
        raise ReportInvalidError("Too many rows for one file; choose a shorter period")


@dataclass(frozen=True, slots=True)
class ExportService:
    reports: ReportService
    store: ExportStore

    def _deliver(
        self,
        actor: AuthenticatedActor,
        property_id: UUID,
        report: str,
        file_type: FileType,
        file: ExportFile,
        kind: str,
        capability: str,
        filters: Mapping[str, object],
    ) -> ExportResult:
        if len(file.content) > MAX_FILE_BYTES:
            raise ReportInvalidError("The file is too large; choose a shorter period")
        export_id = uuid4()
        who = report_actor(actor)
        delivery = "download" if file.row_count <= INLINE_ROWS else "job"
        details = export_details(
            export_id=export_id,
            report=report,
            file_type=file_type,
            row_count=file.row_count,
            sha256=file.sha256,
            delivery=delivery,
            filters=filters,
        )
        if delivery == "download":
            self.store.record(who, property_id, kind, capability, details)
            return ExportResult(export_id, file)
        expires_at = self.store.save(
            who, property_id, export_id, report, file_type, file, kind, capability, details
        )
        return ExportResult(export_id, file, expires_at)

    def export(
        self, actor: AuthenticatedActor, property_id: UUID, request: ExportRequest
    ) -> ExportResult:
        """A report file: the four Totals tables or one of the nine registers (data.export)."""
        if not has_capability(actor, DATA_EXPORT_CAPABILITY, property_id):
            raise ReportForbiddenError("Export needs data.export")
        generated = self.store.generated_at(property_id)
        filters = {
            "floor": request.floor,
            "unit_id": request.unit_id,
            "from_date": request.from_date,
            "to_date": request.to_date,
        }
        if request.report in TOTALS_REPORTS:
            report = request.report
            chosen = TotalsFilter(
                request.unit_id, request.floor, request.from_date, request.to_date
            )
            page = self.reports.totals(actor, property_id, report, chosen)
            quantities = report in UTILITY_TYPES
            rows = totals_rows(page, quantities)
            columns: Sequence[Column] = totals_columns(quantities)
            filter_text = cast(Mapping[str, object], page["filter"])
            lines = heading_lines(
                generated_at=generated,
                floor=request.floor,
                unit_number=cast(str | None, filter_text.get("unit_number")),
                from_date=request.from_date,
                to_date=request.to_date,
            )
        elif request.report in REGISTER_NAMES:
            if request.unit_id is not None:
                raise ReportInvalidError("A register is filtered by floor, not by Unit")
            name = request.report
            register = RegisterFilter(
                request.floor, request.from_date, request.to_date, 0, MAX_EXPORT_ROWS
            )
            page = self.reports.register(actor, property_id, name, register)
            if cast(int, page["row_count"]) > MAX_EXPORT_ROWS:
                raise ReportInvalidError("Too many rows for one file; choose a shorter period")
            rows = [dict(row) for row in cast(Sequence[Mapping[str, object]], page["rows"])]
            if name == "payments":
                for row in rows:
                    row["paid_for"] = paid_for(row.get("parts"))
            money = has_capability(actor, REPORTS_READ_CAPABILITY, property_id)
            columns = [
                column for column in REGISTER_COLUMNS[name] if money or column.kind != "money"
            ]
            period = cast(Mapping[str, object], page["filter"])["period_applies"]
            lines = heading_lines(
                generated_at=generated,
                floor=request.floor,
                from_date=request.from_date,
                to_date=request.to_date,
                period_applies=bool(period),
                money=name not in {"audit_activity"},
            )
        else:
            raise ReportInvalidError("Unknown report")
        _check_rows(request.file_type, len(rows))
        file = build_file(
            request.file_type,
            file_base_name(request.report, generated),
            TITLES[request.report],
            lines,
            columns,
            rows,
        )
        return self._deliver(
            actor,
            property_id,
            request.report,
            request.file_type,
            file,
            "report_export",
            DATA_EXPORT_CAPABILITY,
            filters,
        )

    def audit_export(
        self, actor: AuthenticatedActor, property_id: UUID, request: AuditExportRequest
    ) -> ExportResult:
        """The audit history file (audit.export, SEC-032) with its SHA-256 in its own event."""
        if not has_capability(actor, AUDIT_EXPORT_CAPABILITY, property_id):
            raise ReportForbiddenError("Audit export needs audit.export")
        if (
            request.from_date is not None
            and request.to_date is not None
            and request.from_date > request.to_date
        ):
            raise ReportInvalidError("From is after To")
        generated = self.store.generated_at(property_id)
        rows = self.store.audit_rows(property_id, request)
        _check_rows(request.file_type, len(rows))
        file = build_file(
            request.file_type,
            file_base_name("audit", generated),
            TITLES["audit"],
            heading_lines(
                generated_at=generated,
                from_date=request.from_date,
                to_date=request.to_date,
                money=False,
            ),
            AUDIT_COLUMNS,
            rows,
        )
        filters = {
            "from_date": request.from_date,
            "to_date": request.to_date,
            "actor_id": request.actor_id,
            "action": request.action,
            "unit_id": request.unit_id,
        }
        return self._deliver(
            actor,
            property_id,
            "audit",
            request.file_type,
            file,
            "audit_export",
            AUDIT_EXPORT_CAPABILITY,
            filters,
        )

    def take(
        self, actor: AuthenticatedActor, property_id: UUID, export_id: UUID
    ) -> dict[str, object]:
        """A kept export file, for the person who made it, while it is fresh (24 hours)."""
        allowed = has_capability(actor, DATA_EXPORT_CAPABILITY, property_id) or has_capability(
            actor, AUDIT_EXPORT_CAPABILITY, property_id
        )
        if not allowed:
            raise ReportForbiddenError("Download needs an export right")
        kept = self.store.take(report_actor(actor), property_id, export_id)
        if kept is None:
            raise ReportNotFoundError("The export file is gone or was never made")
        right = AUDIT_EXPORT_CAPABILITY if kept["report"] == "audit" else DATA_EXPORT_CAPABILITY
        if not has_capability(actor, right, property_id):
            raise ReportForbiddenError("Download needs the right that made the file")
        return kept
