"""Employees and payroll (HRIS phase 6, PR-HR-001..068).

One router for the HR screens: Employees (and their documents and Telegram links), staff
requests from the staff bot, Salary loans, Payroll and payslips, Attendance, overtime and the
QR places and cards. Each route checks the coarse right first; the database functions check it
again with the finer rules (Owner only, nobody approves their own request, salaries hidden
without See salaries) and keep every change as a new row.

Uploaded documents and the bot's card photos are files on disk under APP_HR_FILES_DIRECTORY;
the database keeps their SHA-256, size, type and storage key. Without that folder an upload or a
download answers 503.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.routing import APIRoute
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from starlette.types import Message, Receive, Scope, Send

from property_rental.browser_security import require_browser_mutation
from property_rental.identity import ActorResolver
from property_rental.products_api import (
    REFUSED,
    Id,
    Json,
    ProductConflict,
    ProductForbidden,
    ProductNotFound,
    ProductRefused,
    ProductStale,
    ProductUnavailable,
    _expected_version,
    _http,
    _require,
)
from property_rental.settings import Settings

EMPLOYEES_READ = "hr.employees.read"
EMPLOYEES_MANAGE = "hr.employees.manage"
SALARIES_READ = "hr.salaries.read"
SALARIES_MANAGE = "hr.salaries.manage"
LOANS_PREPARE = "hr.loans.prepare"
LOANS_APPROVE = "hr.loans.approve"
PAYROLL_PREPARE = "hr.payroll.prepare"
PAYROLL_APPROVE = "hr.payroll.approve"
PAYROLL_PAY = "hr.payroll.pay"
ATTENDANCE_READ = "hr.attendance.read"
ATTENDANCE_MANAGE = "hr.attendance.manage"
OVERTIME_APPROVE = "hr.overtime.approve"

MAX_FILE_BYTES = 20 * 1024 * 1024
FILE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "application/pdf": "pdf"}

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Clock = Annotated[str, StringConstraints(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]
Day = Annotated[date, Field(strict=False)]
Cents = Annotated[int, Field(ge=1, le=999_999_999)]
Version = Annotated[int, Field(ge=1)]
ReportRole = Literal["CLEANER", "TECHNICIAN", "CARETAKER", "METER_READER", "AUTHORIZER"]
# Only the Property caretaker picks a shift; the database gives every other job OFFICE hours.
CaretakerShift = Literal["MORNING", "AFTERNOON", "NIGHT"]
ShiftCode = Literal["MORNING", "AFTERNOON", "NIGHT", "OFFICE"]


class HrFlow(Protocol):
    def call(self, function: str, parameters: tuple[object, ...]) -> object:
        """Run `SELECT app.<function>(...)` and return its one value."""
        ...


class UnavailableHrFlow:
    def call(self, function: str, parameters: tuple[object, ...]) -> object:
        raise ProductUnavailable


# Every database function the router may call, with its number of arguments.
FUNCTIONS = {
    "hr_employees_read": 2,
    "hr_employee_read": 4,
    "hr_choices": 2,
    "hr_add_employee": 4,
    "hr_employee_step": 7,
    "hr_add_employee_document": 5,
    "hr_employee_document_file": 4,
    "hr_staff_requests_read": 2,
    "hr_decide_staff_request": 5,
    "hr_loans_read": 2,
    "hr_add_loan": 4,
    "hr_decide_loan": 5,
    "hr_pay_out_loan": 5,
    "hr_payrolls_read": 2,
    "hr_payroll_read": 4,
    "hr_make_payroll": 4,
    "hr_make_correction": 5,
    "hr_payroll_step": 6,
    "hr_pay_salary": 5,
    "hr_reverse_salary_payment": 5,
    "hr_attendance_day": 3,
    "hr_attendance_week": 3,
    "hr_attendance_month": 3,
    "hr_attendance_entry": 4,
    "hr_plan_day": 4,
    "hr_request_overtime": 4,
    "hr_decide_overtime": 5,
    "hr_overtime_read": 3,
    "hr_accept_scan": 5,
    "hr_scan_photo_file": 3,
    "hr_attendance_places": 2,
    "hr_set_place_pin": 7,
    "hr_new_place_qr": 5,
    "hr_new_card_qr": 5,
    "hr_employee_card": 3,
}


def _refusal(exc: psycopg.Error) -> Exception:
    message = str(exc).splitlines()[0] if str(exc) else ""
    state = exc.sqlstate or ""
    if state == "42501":
        return ProductForbidden(message)
    if state == "40001":
        return ProductStale(message)
    if state in {"23505", "55000"}:
        return ProductConflict(message)
    if state == "22023" and ("not found" in message or "does not exist" in message):
        return ProductNotFound(message)
    if state in {"22023", "23514", "22003", "23502", "22P02", "22007", "22008"}:
        return ProductRefused(message)
    return ProductUnavailable("HR persistence is unavailable")


class PostgresHrFlow:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def call(self, function: str, parameters: tuple[object, ...]) -> object:
        if FUNCTIONS.get(function) != len(parameters):
            raise ProductUnavailable("HR persistence is unavailable")
        values = tuple(Jsonb(item) if isinstance(item, dict) else item for item in parameters)
        query = sql.SQL("SELECT app.{}({})").format(
            sql.Identifier(function), sql.SQL(", ").join([sql.Placeholder()] * len(values))
        )
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    query,
                    values,
                ).fetchone()
        except psycopg.Error as exc:
            raise _refusal(exc) from exc
        return None if row is None else row[0]


class HrFiles:
    """Files under one folder; a storage key is a relative path the database checked."""

    def __init__(self, directory: str | None) -> None:
        self._root = Path(directory).resolve() if directory else None

    def _path(self, key: str) -> Path:
        if self._root is None:
            raise ProductUnavailable("The HR files folder is not set up")
        path = (self._root / key).resolve()
        if self._root not in path.parents:
            raise ProductNotFound("The file was not found")
        return path

    def save(self, key: str, content: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.part")
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)

    def remove(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def read(self, key: str, sha256: str) -> bytes:
        path = self._path(key)
        try:
            content = path.read_bytes()
        except FileNotFoundError as exc:
            raise ProductNotFound("The file was not found") from exc
        if hashlib.sha256(content).hexdigest() != sha256:
            raise ProductUnavailable("The file does not match what was saved")
        return content


class HrRequestRoute(APIRoute):
    """Bound incoming bytes before FastAPI buffers a body (documents are at most 20 MB)."""

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        received = 0

        async def bounded_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_FILE_BYTES:
                    raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE)
            return message

        await super().handle(scope, bounded_receive, send)


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PayTerms(_Body):
    monthly_salary_usd_cents: Cents
    payment_method: Literal["CASH_USD", "ABA"]
    aba_account_name: Name | None = None
    aba_account_number: Short | None = None


class Identity(_Body):
    id_type: Literal["NATIONAL_ID", "PASSPORT", "OTHER"]
    id_number: Short | None = None
    date_of_birth: Day | None = None
    home_address: Text | None = None
    place_of_birth: Text | None = None


class NewIdentity(_Body):
    """Owner 06/11/2026: every new employee comes with these."""

    id_type: Literal["NATIONAL_ID", "PASSPORT"]
    id_number: Short
    date_of_birth: Day
    home_address: Text
    place_of_birth: Text


class IdPhoto(_Body):
    """The photo or scan of the ID card or passport, sent with the new employee."""

    file_name: Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=r"^[^/\\]+$")]
    media_type: Literal["image/jpeg", "image/png", "application/pdf"]
    content_base64: Annotated[str, StringConstraints(min_length=4, max_length=28_000_000)]


class NewEmployee(_Body):
    name_en: Name
    name_km: Name
    phone: Short | None = None
    job_title_id: Id
    shift_code: CaretakerShift | None = None
    usual_day_off: Annotated[int, Field(ge=1, le=7)] | None = None
    start_date: Day
    user_actor_id: Id | None = None
    reason: Text | None = None
    pay: PayTerms | None = None
    identity: NewIdentity
    id_photo: IdPhoto
    # The ID number belonged to someone who has left: save only after "Hire again?".
    hire_again: bool | None = None


class EmployeeStep(_Body):
    step: Literal[
        "DETAILS",
        "JOB",
        "LEAVE",
        "PAY",
        "IDENTITY",
        "TELEGRAM_LINK",
        "TELEGRAM_UNLINK",
        "DOCUMENT_REMOVE",
    ]
    reason: Text | None = None
    effective_date: Day | None = None
    name_en: Name | None = None
    name_km: Name | None = None
    phone: Short | None = None
    user_actor_id: Id | None = None
    job_title_id: Id | None = None
    shift_code: CaretakerShift | None = None
    usual_day_off: Annotated[int, Field(ge=1, le=7)] | None = None
    monthly_salary_usd_cents: Cents | None = None
    payment_method: Literal["CASH_USD", "ABA"] | None = None
    aba_account_name: Name | None = None
    aba_account_number: Short | None = None
    id_type: Literal["NATIONAL_ID", "PASSPORT", "OTHER"] | None = None
    id_number: Short | None = None
    date_of_birth: Day | None = None
    home_address: Text | None = None
    place_of_birth: Text | None = None
    telegram_user_id: Annotated[int, Field(ge=1)] | None = None
    report_role: ReportRole | None = None
    link_id: Id | None = None
    document_id: Id | None = None


class StaffRequestDecision(_Body):
    decision: Literal["LINKED", "REFUSED"]
    employee_id: Id | None = None
    roles: list[ReportRole] | None = None
    reason: Text | None = None


class NewLoan(_Body):
    employee_id: Id
    amount_usd_cents: Cents
    payout_method: Literal["CASH_USD", "ABA_JOINT"]
    repayment_plan: Literal["NEXT_SALARY", "MONTHLY_AMOUNT"] = "NEXT_SALARY"
    monthly_repayment_usd_cents: Cents | None = None
    request_channel: Literal["APP", "TELEGRAM"] = "APP"
    requested_on: Day | None = None
    reason: Text


class Decision(_Body):
    decision: Literal["APPROVED", "REFUSED"]
    reason: Text | None = None
    own_request_note: Text | None = None


class LoanPayOut(_Body):
    paid_on: Day


class NewPayroll(_Body):
    salary_month: Day


class Reason(_Body):
    reason: Text


class PayrollStep(_Body):
    step: Literal["ADD_LINE", "REMOVE_LINE", "SEND", "SEND_BACK", "APPROVE"]
    employee_id: Id | None = None
    component: (
        Literal["BONUS", "OTHER_PLUS", "OTHER_MINUS", "OVERTIME", "DAYS_NOT_WORKED"] | None
    ) = None
    amount_usd_cents: Cents | None = None
    line_id: Id | None = None
    reason: Text | None = None
    own_request_note: Text | None = None


class SalaryPayment(_Body):
    paid_on: Day
    method: Literal["CASH_USD", "ABA_JOINT"] | None = None
    bank_reference: Short | None = None
    own_request_note: Text | None = None


class AttendanceEntry(_Body):
    employee_id: Id
    work_date: Day
    status: Literal["WORKED", "ABSENT", "LEAVE_ANNUAL", "LEAVE_SICK", "LEAVE_UNPAID", "DAY_OFF"]
    shift_code: ShiftCode | None = None
    check_in: Clock | None = None
    check_out: Clock | None = None
    reason: Text


class PlanDay(_Body):
    employee_id: Id
    work_date: Day
    shift_code: ShiftCode | None = None
    reason: Text | None = None


class OvertimeAsk(_Body):
    employee_id: Id
    work_date: Day
    starts_at: Clock
    ends_at: Clock
    reason: Text


class ScanAcceptance(_Body):
    note: Text | None = None


class PlacePin(_Body):
    latitude: Annotated[float, Field(ge=-90, le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]
    reason: Text | None = None


class NewCode(_Body):
    reason: Text | None = None


def create_hr_router(resolver: ActorResolver, flow: HrFlow, settings: Settings) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/properties/{property_id}/hr",
        tags=["employees and payroll"],
        route_class=HrRequestRoute,
    )
    files = HrFiles(settings.hr_files_directory)

    def envelope(request: Request, data: object) -> Json:
        return {"data": data, "meta": {"request_id": request.state.request_id}}

    def ask(function: str, *parameters: object) -> object:
        try:
            return flow.call(function, parameters)
        except REFUSED as exc:
            raise _http(exc) from exc

    def reader(right: str) -> Callable[[UUID, Request, Response], UUID]:
        def check(property_id: UUID, request: Request, response: Response) -> UUID:
            actor = _require(request, resolver, right, property_id)
            response.headers["Cache-Control"] = "private, no-store"
            return UUID(actor.actor_id)

        return check

    def writer(right: str, property_id: UUID, request: Request) -> UUID:
        actor = _require(request, resolver, right, property_id)
        require_browser_mutation(request, settings)
        return UUID(actor.actor_id)

    def _require_any(request: Request, property_id: UUID, *rights: str) -> UUID:
        for right in rights[:-1]:
            try:
                return UUID(_require(request, resolver, right, property_id).actor_id)
            except HTTPException as exc:
                if exc.status_code != status.HTTP_403_FORBIDDEN:
                    raise
        return UUID(_require(request, resolver, rights[-1], property_id).actor_id)

    def body(model: BaseModel) -> Json:
        return model.model_dump(mode="json", exclude_none=True)

    def employee(request: Request, property_id: UUID, employee_id: UUID, actor: UUID) -> Json:
        return envelope(request, ask("hr_employee_read", property_id, employee_id, actor, uuid4()))

    def payroll(request: Request, property_id: UUID, run_id: UUID, actor: UUID) -> Json:
        return envelope(request, ask("hr_payroll_read", property_id, run_id, actor, uuid4()))

    def download(found: object, response: Response) -> Response:
        if not isinstance(found, dict):
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            content = files.read(str(found["storage_key"]), str(found["sha256"]))
        except REFUSED as exc:
            raise _http(exc) from exc
        name = str(found.get("original_name") or "file").replace('"', "")
        return Response(
            content=content,
            media_type=str(found["media_type"]),
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": f'attachment; filename="{name}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    # Employees (PR-HR-010..019)
    @router.get("/employees")
    def list_employees(property_id: UUID, request: Request, response: Response) -> Json:
        actor = reader(EMPLOYEES_READ)(property_id, request, response)
        return envelope(request, ask("hr_employees_read", property_id, actor))

    @router.get("/choices")
    def hr_choices(property_id: UUID, request: Request, response: Response) -> Json:
        actor = reader(EMPLOYEES_READ)(property_id, request, response)
        return envelope(request, ask("hr_choices", property_id, actor))

    @router.get("/employees/{employee_id}")
    def read_employee(
        property_id: UUID, employee_id: UUID, request: Request, response: Response
    ) -> Json:
        actor = reader(EMPLOYEES_READ)(property_id, request, response)
        return employee(request, property_id, employee_id, actor)

    @router.post("/employees", status_code=status.HTTP_201_CREATED)
    def add_employee(property_id: UUID, form: NewEmployee, request: Request) -> Json:
        # Whoever adds an employee enters the ID details and photo; the salary needs the
        # salary right.
        actor = writer(SALARIES_MANAGE if form.pay else EMPLOYEES_MANAGE, property_id, request)
        try:
            content = base64.b64decode(form.id_photo.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The ID photo could not be read"
            ) from exc
        if not content:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The file is empty")
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE)
        key = f"hr/documents/new/{uuid4()}.{FILE_TYPES[form.id_photo.media_type]}"
        try:
            files.save(key, content)
        except REFUSED as exc:
            raise _http(exc) from exc
        change = body(form)
        del change["id_photo"]
        change["id_document"] = {
            "original_name": form.id_photo.file_name.strip(),
            "media_type": form.id_photo.media_type,
            "byte_size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "storage_key": key,
        }
        try:
            made = flow.call("hr_add_employee", (property_id, change, actor, uuid4()))
        except REFUSED as exc:
            files.remove(key)
            raise _http(exc) from exc
        return employee(request, property_id, UUID(str(made)), actor)

    @router.post("/employees/{employee_id}/steps")
    def employee_step(
        property_id: UUID, employee_id: UUID, form: EmployeeStep, request: Request
    ) -> Json:
        right = SALARIES_MANAGE if form.step in ("PAY", "IDENTITY") else EMPLOYEES_MANAGE
        actor = writer(right, property_id, request)
        version = _expected_version(request)
        change = body(form)
        name = change.pop("step")
        ask("hr_employee_step", property_id, employee_id, version, name, change, actor, uuid4())
        return employee(request, property_id, employee_id, actor)

    @router.post("/employees/{employee_id}/documents", status_code=status.HTTP_201_CREATED)
    async def add_document(
        property_id: UUID,
        employee_id: UUID,
        request: Request,
        kind: Literal["ID_CARD", "CONTRACT", "CERTIFICATE", "OTHER"],
        title: Annotated[str, Query(min_length=1, max_length=120)],
        file_name: Annotated[str, Query(min_length=1, max_length=200, pattern=r"^[^/\\]+$")],
        expires_on: date | None = None,
    ) -> Json:
        actor = writer(EMPLOYEES_MANAGE, property_id, request)
        media_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        if media_type not in FILE_TYPES:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Use a JPG, PNG or PDF file"
            )
        content = await request.body()
        if not content:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The file is empty")
        key = f"hr/documents/{employee_id}/{uuid4()}.{FILE_TYPES[media_type]}"
        try:
            files.save(key, content)
        except REFUSED as exc:
            raise _http(exc) from exc
        record: Json = {
            "kind": kind,
            "title": title.strip(),
            "original_name": file_name.strip(),
            "media_type": media_type,
            "byte_size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "storage_key": key,
        }
        if expires_on is not None:
            record["expires_on"] = expires_on.isoformat()
        try:
            flow.call(
                "hr_add_employee_document", (property_id, employee_id, record, actor, uuid4())
            )
        except REFUSED as exc:
            files.remove(key)
            raise _http(exc) from exc
        return employee(request, property_id, employee_id, actor)

    @router.get("/documents/{document_id}/file")
    def document_file(
        property_id: UUID, document_id: UUID, request: Request, response: Response
    ) -> Response:
        actor = reader(EMPLOYEES_READ)(property_id, request, response)
        found = ask("hr_employee_document_file", property_id, document_id, actor, uuid4())
        return download(found, response)

    # Staff requests from the staff bot (PR-HR-018)
    @router.get("/staff-requests")
    def staff_requests(property_id: UUID, request: Request, response: Response) -> Json:
        actor = reader(EMPLOYEES_READ)(property_id, request, response)
        return envelope(request, ask("hr_staff_requests_read", property_id, actor))

    @router.post("/staff-requests/{request_id}/decision")
    def decide_staff_request(
        property_id: UUID, request_id: UUID, form: StaffRequestDecision, request: Request
    ) -> Json:
        actor = writer(EMPLOYEES_MANAGE, property_id, request)
        ask("hr_decide_staff_request", property_id, request_id, body(form), actor, uuid4())
        return envelope(request, ask("hr_staff_requests_read", property_id, actor))

    # Salary loans (PR-HR-020..024)
    @router.get("/loans")
    def list_loans(property_id: UUID, request: Request, response: Response) -> Json:
        actor = reader(SALARIES_READ)(property_id, request, response)
        return envelope(request, ask("hr_loans_read", property_id, actor))

    @router.post("/loans", status_code=status.HTTP_201_CREATED)
    def add_loan(property_id: UUID, form: NewLoan, request: Request) -> Json:
        actor = writer(LOANS_PREPARE, property_id, request)
        made = ask("hr_add_loan", property_id, body(form), actor, uuid4())
        return envelope(request, {"loan_id": str(made)})

    @router.post("/loans/{loan_id}/decision")
    def decide_loan(property_id: UUID, loan_id: UUID, form: Decision, request: Request) -> Json:
        actor = writer(LOANS_APPROVE, property_id, request)
        ask("hr_decide_loan", property_id, loan_id, body(form), actor, uuid4())
        return envelope(request, ask("hr_loans_read", property_id, actor))

    @router.post("/loans/{loan_id}/pay-out")
    def pay_out_loan(property_id: UUID, loan_id: UUID, form: LoanPayOut, request: Request) -> Json:
        actor = writer(LOANS_PREPARE, property_id, request)
        entry = ask("hr_pay_out_loan", property_id, loan_id, form.paid_on, actor, uuid4())
        return envelope(request, {"entry_id": None if entry is None else str(entry)})

    # Payroll and payslips (PR-HR-025..035)
    @router.get("/payrolls")
    def list_payrolls(property_id: UUID, request: Request, response: Response) -> Json:
        actor = reader(SALARIES_READ)(property_id, request, response)
        return envelope(request, ask("hr_payrolls_read", property_id, actor))

    @router.get("/payrolls/{run_id}")
    def read_payroll(property_id: UUID, run_id: UUID, request: Request, response: Response) -> Json:
        actor = reader(SALARIES_READ)(property_id, request, response)
        return payroll(request, property_id, run_id, actor)

    @router.post("/payrolls", status_code=status.HTTP_201_CREATED)
    def make_payroll(property_id: UUID, form: NewPayroll, request: Request) -> Json:
        actor = writer(PAYROLL_PREPARE, property_id, request)
        made = ask("hr_make_payroll", property_id, form.salary_month, actor, uuid4())
        return payroll(request, property_id, UUID(str(made)), actor)

    @router.post("/payrolls/{run_id}/correction", status_code=status.HTTP_201_CREATED)
    def make_correction(property_id: UUID, run_id: UUID, form: Reason, request: Request) -> Json:
        actor = writer(PAYROLL_PREPARE, property_id, request)
        made = ask("hr_make_correction", property_id, run_id, form.reason, actor, uuid4())
        return payroll(request, property_id, UUID(str(made)), actor)

    @router.post("/payrolls/{run_id}/steps")
    def payroll_step(property_id: UUID, run_id: UUID, form: PayrollStep, request: Request) -> Json:
        right = PAYROLL_APPROVE if form.step in ("SEND_BACK", "APPROVE") else PAYROLL_PREPARE
        actor = writer(right, property_id, request)
        change = body(form)
        name = change.pop("step")
        ask("hr_payroll_step", property_id, run_id, name, change, actor, uuid4())
        return payroll(request, property_id, run_id, actor)

    @router.post("/payslips/{payslip_id}/payment", status_code=status.HTTP_201_CREATED)
    def pay_salary(
        property_id: UUID, payslip_id: UUID, form: SalaryPayment, request: Request
    ) -> Json:
        actor = writer(PAYROLL_PAY, property_id, request)
        made = ask("hr_pay_salary", property_id, payslip_id, body(form), actor, uuid4())
        return envelope(request, {"payment_id": str(made)})

    @router.post("/salary-payments/{payment_id}/reversal", status_code=status.HTTP_201_CREATED)
    def reverse_salary_payment(
        property_id: UUID, payment_id: UUID, form: Reason, request: Request
    ) -> Json:
        actor = writer(PAYROLL_PAY, property_id, request)
        made = ask(
            "hr_reverse_salary_payment", property_id, payment_id, form.reason, actor, uuid4()
        )
        return envelope(request, {"reversal_id": None if made is None else str(made)})

    # Attendance and overtime (PR-HR-050..059)
    @router.get("/attendance/day")
    def attendance_day(
        property_id: UUID, request: Request, response: Response, day: date | None = None
    ) -> Json:
        actor = reader(ATTENDANCE_READ)(property_id, request, response)
        return envelope(request, ask("hr_attendance_day", property_id, day, actor))

    @router.get("/attendance/week")
    def attendance_week(
        property_id: UUID, request: Request, response: Response, monday: date | None = None
    ) -> Json:
        actor = reader(ATTENDANCE_READ)(property_id, request, response)
        return envelope(request, ask("hr_attendance_week", property_id, monday, actor))

    @router.get("/attendance/month")
    def attendance_month(
        property_id: UUID, request: Request, response: Response, month: date | None = None
    ) -> Json:
        actor = reader(ATTENDANCE_READ)(property_id, request, response)
        return envelope(request, ask("hr_attendance_month", property_id, month, actor))

    @router.post("/attendance/entries", status_code=status.HTTP_201_CREATED)
    def attendance_entry(property_id: UUID, form: AttendanceEntry, request: Request) -> Json:
        actor = writer(ATTENDANCE_MANAGE, property_id, request)
        ask("hr_attendance_entry", property_id, body(form), actor, uuid4())
        return envelope(request, ask("hr_attendance_day", property_id, form.work_date, actor))

    @router.post("/attendance/plan")
    def plan_day(property_id: UUID, form: PlanDay, request: Request) -> Json:
        actor = writer(ATTENDANCE_MANAGE, property_id, request)
        ask("hr_plan_day", property_id, body(form), actor, uuid4())
        return envelope(request, ask("hr_attendance_week", property_id, form.work_date, actor))

    @router.get("/overtime")
    def list_overtime(
        property_id: UUID, request: Request, response: Response, month: date | None = None
    ) -> Json:
        actor = reader(ATTENDANCE_READ)(property_id, request, response)
        return envelope(request, ask("hr_overtime_read", property_id, month, actor))

    @router.post("/overtime", status_code=status.HTTP_201_CREATED)
    def ask_overtime(property_id: UUID, form: OvertimeAsk, request: Request) -> Json:
        actor = writer(ATTENDANCE_MANAGE, property_id, request)
        ask("hr_request_overtime", property_id, body(form), actor, uuid4())
        return envelope(request, ask("hr_overtime_read", property_id, form.work_date, actor))

    @router.post("/overtime/{request_id}/decision")
    def decide_overtime(
        property_id: UUID, request_id: UUID, form: Decision, request: Request
    ) -> Json:
        actor = writer(OVERTIME_APPROVE, property_id, request)
        ask("hr_decide_overtime", property_id, request_id, body(form), actor, uuid4())
        return envelope(request, ask("hr_overtime_read", property_id, None, actor))

    # QR check-in (PR-HR-060..068)
    @router.post("/attendance/scans/{scan_id}/acceptance")
    def accept_scan(
        property_id: UUID, scan_id: UUID, form: ScanAcceptance, request: Request
    ) -> Json:
        actor = writer(ATTENDANCE_MANAGE, property_id, request)
        ask("hr_accept_scan", property_id, scan_id, form.note, actor, uuid4())
        return envelope(request, {"scan_id": str(scan_id), "accepted": True})

    @router.get("/attendance/scans/{scan_id}/photo")
    def scan_photo(
        property_id: UUID, scan_id: UUID, request: Request, response: Response
    ) -> Response:
        actor = reader(ATTENDANCE_READ)(property_id, request, response)
        return download(ask("hr_scan_photo_file", property_id, scan_id, actor), response)

    @router.get("/attendance/places")
    def attendance_places(property_id: UUID, request: Request, response: Response) -> Json:
        actor = reader(ATTENDANCE_READ)(property_id, request, response)
        return envelope(request, ask("hr_attendance_places", property_id, actor))

    @router.post("/attendance/places/{place_id}/pin")
    def set_place_pin(property_id: UUID, place_id: UUID, form: PlacePin, request: Request) -> Json:
        actor = writer(ATTENDANCE_MANAGE, property_id, request)
        ask(
            "hr_set_place_pin",
            property_id,
            place_id,
            form.latitude,
            form.longitude,
            form.reason,
            actor,
            uuid4(),
        )
        return envelope(request, ask("hr_attendance_places", property_id, actor))

    @router.post("/attendance/places/{place_id}/qr", status_code=status.HTTP_201_CREATED)
    def new_place_qr(
        property_id: UUID, place_id: UUID, form: NewCode, request: Request, response: Response
    ) -> Json:
        actor = writer(ATTENDANCE_MANAGE, property_id, request)
        response.headers["Cache-Control"] = "private, no-store"
        code = ask("hr_new_place_qr", property_id, place_id, form.reason, actor, uuid4())
        return envelope(request, {"place_id": str(place_id), "code": code})

    @router.get("/employees/{employee_id}/card")
    def employee_card(
        property_id: UUID, employee_id: UUID, request: Request, response: Response
    ) -> Json:
        actor = _require_any(request, property_id, ATTENDANCE_READ, EMPLOYEES_READ)
        response.headers["Cache-Control"] = "private, no-store"
        return envelope(request, ask("hr_employee_card", property_id, employee_id, actor))

    @router.post("/employees/{employee_id}/card-qr", status_code=status.HTTP_201_CREATED)
    def new_card_qr(
        property_id: UUID, employee_id: UUID, form: NewCode, request: Request, response: Response
    ) -> Json:
        actor = writer(ATTENDANCE_MANAGE, property_id, request)
        response.headers["Cache-Control"] = "private, no-store"
        code = ask("hr_new_card_qr", property_id, employee_id, form.reason, actor, uuid4())
        return envelope(request, {"employee_id": str(employee_id), "code": code})

    return router


__all__ = [
    "FUNCTIONS",
    "HrFlow",
    "PostgresHrFlow",
    "UnavailableHrFlow",
    "create_hr_router",
]
