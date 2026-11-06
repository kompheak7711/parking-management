"""HRIS phase 1 on the real database (migration 20270430_300): rights, Employees, Telegram staff.

The Owner holds every HR right; the Manager sees and manages employees and attendance but not
salaries; Staff hold none. Salaries and ID details stay out of reads without See salaries. History
is never typed over, and the staff bot works as a service actor.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest

from test_default_role_bundles_migration import SEED_QUERY
from test_invoice_migration import financial_database_url
from test_migrations import _run_alembic, _temporary_migration_database, _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_role_bundle_migration import add_account, the_property

GRANTS = "SELECT capability_id FROM app.actor_capability_grants(%s)"
ADD = "SELECT app.hr_add_employee(%s, %s::jsonb, %s, NULL)"
STEP = "SELECT app.hr_employee_step(%s, %s, %s, %s, %s::jsonb, %s, NULL)"
READ = "SELECT app.hr_employee_read(%s, %s, %s, NULL)"
LIST = "SELECT app.hr_employees_read(%s, %s)"
HR = {
    "hr.employees.read",
    "hr.employees.manage",
    "hr.salaries.read",
    "hr.salaries.manage",
    "hr.loans.prepare",
    "hr.loans.approve",
    "hr.payroll.prepare",
    "hr.payroll.approve",
    "hr.payroll.pay",
    "hr.attendance.read",
    "hr.attendance.manage",
    "hr.overtime.approve",
}
MANAGER = {
    "hr.employees.read",
    "hr.employees.manage",
    "hr.attendance.read",
    "hr.attendance.manage",
    "hr.overtime.approve",
}


@dataclass(frozen=True)
class HrDatabase:
    owner_url: str
    runtime_url: str
    financial_url: str
    property_id: uuid.UUID
    owner: uuid.UUID
    manager: uuid.UUID
    staff: uuid.UUID
    accountant: uuid.UUID
    bot: uuid.UUID
    today: date


def make_hr_database(prefix: str) -> Iterator[HrDatabase]:
    with _temporary_migration_database(prefix) as temporary:
        assert _run_alembic("upgrade", "head").returncode == 0
        name = urlsplit(temporary).path.lstrip("/")
        runtime_url = _url_with_database(runtime_database_url(), name)
        financial_url = _url_with_database(financial_database_url(), name)
        with psycopg.connect(temporary) as setup:
            property_id = the_property(setup)
            owner = add_account(setup, "owner")
            manager = add_account(setup, "manager")
            staff = add_account(setup, "staff")
            accountant = add_account(setup, "staff")
            seeded = setup.execute(SEED_QUERY, (property_id,)).fetchone()
            assert seeded is not None
            accountant_role = uuid.uuid4()
            setup.execute(
                "INSERT INTO app.role_bundles (role_bundle_id, property_id, name, name_kh, "
                "version, settings_access, provenance) "
                "VALUES (%s, %s, 'Accountant', 'គណនេយ្យករ', 1, false, 'test')",
                (accountant_role, property_id),
            )
            setup.execute(
                "INSERT INTO app.role_bundle_capabilities (role_bundle_id, version, capability_id)"
                " SELECT %s, 1, capability_id FROM app.permission_capabilities "
                "WHERE permission_code IN ('BASIC', 'HR_EMPLOYEES_SEE', 'HR_SALARIES')",
                (accountant_role,),
            )
            for actor, bundle in (
                (manager, seeded[1]),
                (staff, seeded[2]),
                (accountant, accountant_role),
            ):
                setup.execute(
                    "INSERT INTO app.user_role_assignments (assignment_id, actor_id, "
                    "role_bundle_id, property_id, provenance) VALUES (%s, %s, %s, %s, 'test')",
                    (uuid.uuid4(), actor, bundle, property_id),
                )
            bot = uuid.uuid4()
            # Any SERVICE identity stands for the staff bot here (the Telegram thread adds its own).
            setup.execute(
                "INSERT INTO app.billing_service_principals (actor_id, property_id, capability, "
                "lifecycle_state, created_by) VALUES (%s, %s, 'billing.generate', 'active', %s)",
                (bot, property_id, owner),
            )
            today = setup.execute(
                "SELECT timezone(timezone_name, statement_timestamp())::date FROM app.properties "
                "WHERE id = %s",
                (property_id,),
            ).fetchone()
            assert today is not None
            setup.commit()
        yield HrDatabase(
            temporary,
            runtime_url,
            financial_url,
            property_id,
            owner,
            manager,
            staff,
            accountant,
            bot,
            today[0],
        )


@pytest.fixture(scope="module")
def hr_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_hr_people")


def run(url: str, sql: str, *params: Any) -> Any:
    with psycopg.connect(url) as connection:
        row = connection.execute(sql, params).fetchone()
        assert row is not None
        return row[0]


def refused(url: str, state: str, sql: str, *params: Any) -> str:
    with pytest.raises(psycopg.Error) as caught:
        run(url, sql, *params)
    assert caught.value.sqlstate == state, caught.value
    return str(caught.value)


def job_id(db: HrDatabase, code: str) -> str:
    return str(run(db.owner_url, "SELECT id FROM app.job_titles WHERE code = %s", code))


IDENTITY = {
    "id_type": "NATIONAL_ID",
    "id_number": "010101010",
    "date_of_birth": "1995-04-14",
    "home_address": "Sample street, Phnom Penh",
    "place_of_birth": "Kandal",
}


def id_document() -> dict[str, Any]:
    """What the API keeps for the ID photo it saved first (a new storage key each time)."""
    return {
        "original_name": "id-card.jpg",
        "media_type": "image/jpeg",
        "byte_size": 1234,
        "sha256": "a" * 64,
        "storage_key": f"hr/documents/new/{uuid.uuid4()}.jpg",
    }


def add_employee(db: HrDatabase, actor: uuid.UUID | None = None, **body: Any) -> uuid.UUID:
    identity = dict(body.pop("identity", IDENTITY))
    if identity.get("id_number") == IDENTITY["id_number"]:
        # One ID number is one person (migration 305): each sample person gets their own.
        identity["id_number"] = f"T{uuid.uuid4().hex[:12].upper()}"
    form = {
        "name_en": "Chan Dara",
        "name_km": "ចាន់ ដារ៉ា",
        "job_title_id": job_id(db, "CARETAKER"),
        "shift_code": "MORNING",
        "start_date": str(db.today - timedelta(days=60)),
        "identity": identity,
        "id_document": id_document(),
    } | body
    made = run(db.runtime_url, ADD, db.property_id, json.dumps(form), actor or db.owner)
    return uuid.UUID(str(made))


def read(db: HrDatabase, employee: uuid.UUID, actor: uuid.UUID | None = None) -> dict[str, Any]:
    found = run(db.runtime_url, READ, db.property_id, employee, actor or db.owner)
    assert isinstance(found, dict)
    return found


def step(
    db: HrDatabase, employee: uuid.UUID, name: str, actor: uuid.UUID | None = None, **body: Any
) -> None:
    version = read(db, employee)["version"]
    with psycopg.connect(db.runtime_url) as connection:
        connection.execute(
            STEP,
            (db.property_id, employee, version, name, json.dumps(body), actor or db.owner),
        )


PAY = {"monthly_salary_usd_cents": 22500, "payment_method": "CASH_USD"}


def test_rights_follow_the_plan(hr_database: HrDatabase) -> None:
    db = hr_database
    with psycopg.connect(db.owner_url) as connection:

        def held(actor: uuid.UUID) -> set[str]:
            rows = connection.execute(GRANTS, (actor,)).fetchall()
            return {str(row[0]) for row in rows} & HR

        assert held(db.owner) == HR
        assert held(db.manager) == MANAGER
        assert held(db.staff) == set()
        groups = connection.execute(
            "SELECT permission_code, group_code FROM app.permissions "
            "WHERE permission_code LIKE 'HR\\_%' ORDER BY sort_order"
        ).fetchall()
        assert groups == [
            ("HR_EMPLOYEES_SEE", "ADMIN"),
            ("HR_EMPLOYEES", "ADMIN"),
            ("HR_SALARIES", "ADMIN"),
            ("HR_PAY_APPROVE", "ADMIN"),
            ("HR_ATTENDANCE", "ADMIN"),
        ]
        rules = connection.execute(
            "SELECT name.code, app.business_rule_value(name.code, %s) FROM "
            "app.business_rule_names AS name WHERE name.area = 'STAFF' ORDER BY name.code",
            (db.today,),
        ).fetchall()
        # Migration 301 adds LOAN_OPEN_MAX (open loans per person).
        assert rules == [("LOAN_OPEN_MAX", 1), ("LOAN_PCT", 5000), ("PAY_DAY", 5)]
        numbers = connection.execute(
            "SELECT DISTINCT document_type, format FROM app.number_rules "
            "WHERE document_type IN ('SALARY_LOAN', 'PAYROLL', 'OVERTIME') ORDER BY 1"
        ).fetchall()
        assert numbers == [
            ("OVERTIME", "OTyy000n"),
            ("PAYROLL", "PAYyy000n"),
            ("SALARY_LOAN", "SLyy000n"),
        ]
        foreign = connection.execute(
            "SELECT confrelid::regclass::text FROM pg_constraint "
            "WHERE conname = 'gl_journal_lines_employee_fkey'"
        ).fetchone()
        assert foreign == ("app.employees",)


def test_manager_adds_employees_without_salaries(hr_database: HrDatabase) -> None:
    db = hr_database
    # The Manager enters the ID details and the ID photo with a new employee, but does not
    # see them afterwards (owner 06/11/2026 09:05).
    first = add_employee(
        db,
        db.manager,
        name_en="Sok Lina",
        name_km="សុខ លីណា",
        job_title_id=job_id(db, "CLEANER"),
        usual_day_off=7,
    )
    found = read(db, first, db.manager)
    assert found["employee_code"].startswith("E-")
    assert found["state"] == "ACTIVE"
    assert found["job_title"]["code"] == "CLEANER"
    # Only the caretaker works shifts: a cleaner works office hours, whatever the form said,
    # and takes 2 days off a month on request instead of a usual day off (owner 06/11 10:24).
    assert (found["shift_code"], found["usual_day_off"]) == ("OFFICE", None)
    assert found["pay"] is None and found["pay_history"] is None and found["identity"] is None
    assert found["can_see_salaries"] is False
    owner_view = read(db, first)
    assert owner_view["identity"]["home_address"] == "Sample street, Phnom Penh"
    assert owner_view["identity"]["place_of_birth"] == "Kandal"
    assert [item["kind"] for item in owner_view["documents"]] == ["ID_CARD"]
    refused(
        db.runtime_url,
        "42501",
        ADD,
        db.property_id,
        json.dumps(
            {
                "name_en": "Keo Sophal",
                "name_km": "កែវ សុផល",
                "job_title_id": job_id(db, "TECHNICIAN"),
                "shift_code": "AFTERNOON",
                "usual_day_off": 1,
                "start_date": str(db.today),
                "pay": PAY,
            }
        ),
        db.manager,
    )
    refused(db.runtime_url, "42501", LIST, db.property_id, db.staff)
    # Someone with See salaries adds the salary later; the Manager never sees it.
    step(db, first, "PAY", db.accountant, effective_date=found["hired_on"], reason="Start", **PAY)
    assert read(db, first)["pay"]["monthly_salary_usd_cents"] == 22500
    listed = {
        item["employee_id"]: item for item in run(db.runtime_url, LIST, db.property_id, db.manager)
    }
    assert listed[str(first)]["pay"] is None
    refused(
        db.runtime_url,
        "42501",
        STEP,
        db.property_id,
        first,
        None,
        "PAY",
        json.dumps({"effective_date": str(db.today), "reason": "Raise"} | PAY),
        db.manager,
    )


def test_owner_adds_salary_and_history_is_kept(hr_database: HrDatabase) -> None:
    db = hr_database
    person = add_employee(
        db,
        name_en="Vann Sreypov",
        name_km="វ៉ាន់ ស្រីពៅ",
        pay={
            "monthly_salary_usd_cents": 30000,
            "payment_method": "ABA",
            "aba_account_name": "VANN SREYPOV",
            "aba_account_number": "000 111 222",
        },
        job_title_id=job_id(db, "FRONT_DESK"),
        usual_day_off=7,
        identity=IDENTITY | {"id_number": "020202020"},
    )
    found = read(db, person)
    assert found["pay"]["payment_method"] == "ABA"
    assert found["identity"]["id_number"] == "020202020"
    step(
        db,
        person,
        "JOB",
        effective_date=str(db.today),
        job_title_id=job_id(db, "CARETAKER"),
        shift_code="AFTERNOON",
        reason="Now the caretaker",
    )
    step(db, person, "JOB", effective_date=str(db.today), shift_code="NIGHT", reason="Nights")
    step(
        db,
        person,
        "PAY",
        effective_date=str(db.today),
        monthly_salary_usd_cents=32000,
        payment_method="CASH_USD",
        reason="Raise",
    )
    found = read(db, person)
    assert [event["event_type"] for event in found["history"]] == [
        "SHIFT_CHANGE",
        "JOB_CHANGE",
        "HIRED",
    ]
    assert found["shift_code"] == "NIGHT" and found["job_title"]["code"] == "CARETAKER"
    # The caretaker has no usual day off; the Weekly plan sets the rest day.
    assert found["usual_day_off"] is None
    assert found["pay"]["monthly_salary_usd_cents"] == 32000
    assert len(found["pay_history"]) == 2
    with psycopg.connect(db.owner_url) as connection:
        for table in ("employment_events", "employee_pay_terms", "employee_identity_records"):
            with pytest.raises(psycopg.Error) as caught:
                connection.execute(f"DELETE FROM app.{table}")
            assert caught.value.sqlstate == "55000"
            connection.rollback()
        with pytest.raises(psycopg.Error) as caught:
            connection.execute("UPDATE app.employees SET employee_code = 'E-999'")
        assert caught.value.sqlstate == "55000"
    # The accountant's read of salaries is in History; the Owner's is not.
    read(db, person, db.accountant)
    reads = run(
        db.owner_url,
        "SELECT count(*) FROM app.audit_events WHERE action = 'hr.employee.private_read' "
        "AND entity_id = %s AND actor_id = %s",
        person,
        db.accountant,
    )
    assert reads == 1
    step(db, person, "LEAVE", effective_date=str(db.today - timedelta(days=1)), reason="Moved away")
    assert read(db, person)["state"] == "LEFT"
    refused(
        db.runtime_url,
        "55000",
        STEP,
        db.property_id,
        person,
        None,
        "LEAVE",
        json.dumps({"effective_date": str(db.today), "reason": "Again"}),
        db.owner,
    )


def test_runtime_reads_hr_only_through_functions(hr_database: HrDatabase) -> None:
    db = hr_database
    with psycopg.connect(db.runtime_url) as connection:
        for table in ("employees", "employee_pay_terms", "employee_identity_records"):
            with pytest.raises(psycopg.Error) as caught:
                connection.execute(f"SELECT * FROM app.{table}")
            assert caught.value.sqlstate == "42501"
            connection.rollback()
        assert connection.execute("SELECT count(*) FROM app.job_titles").fetchone() == (6,)


def test_telegram_staff_request_and_links(hr_database: HrDatabase) -> None:
    db = hr_database
    worker = add_employee(db, name_en="Ly Rith", name_km="លី រិទ្ធ")
    other = add_employee(db, name_en="Mao Kim", name_km="ម៉ៅ គីម")
    start = "SELECT app.hr_record_staff_request(%s, %s, %s, %s, NULL, %s)"
    refused(db.runtime_url, "42501", start, db.property_id, 5550001, "Rith", None, db.owner)
    waiting = run(db.runtime_url, start, db.property_id, 5550001, "Rith", "012345678", db.bot)
    assert waiting["state"] == "WAITING"
    again = run(db.runtime_url, start, db.property_id, 5550001, "Rith", None, db.bot)
    assert again["request_id"] == waiting["request_id"]
    listed = run(
        db.runtime_url, "SELECT app.hr_staff_requests_read(%s, %s)", db.property_id, db.manager
    )
    assert [item["telegram_user_id"] for item in listed] == [5550001]
    decide = "SELECT app.hr_decide_staff_request(%s, %s, %s::jsonb, %s, NULL)"
    refused(
        db.runtime_url,
        "42501",
        decide,
        db.property_id,
        waiting["request_id"],
        json.dumps({"decision": "LINKED", "employee_id": str(worker), "roles": ["AUTHORIZER"]}),
        db.manager,
    )
    with psycopg.connect(db.runtime_url) as connection:
        connection.execute(
            decide,
            (
                db.property_id,
                waiting["request_id"],
                json.dumps(
                    {
                        "decision": "LINKED",
                        "employee_id": str(worker),
                        "roles": ["CLEANER", "METER_READER"],
                    }
                ),
                db.manager,
            ),
        )
    who = run(
        db.runtime_url, "SELECT app.hr_telegram_staff(%s, %s, %s)", db.property_id, 5550001, db.bot
    )
    assert who["linked"] is True and who["roles"] == ["CLEANER", "METER_READER"]
    assert (
        run(db.runtime_url, start, db.property_id, 5550001, "Rith", None, db.bot)["state"]
        == "LINKED"
    )
    # One Telegram account belongs to one employee while linked.
    refused(
        db.runtime_url,
        "23505",
        STEP,
        db.property_id,
        other,
        None,
        "TELEGRAM_LINK",
        json.dumps({"telegram_user_id": 5550001, "report_role": "CLEANER", "reason": "Test"}),
        db.owner,
    )
    links = read(db, worker)["telegram"]
    step(db, worker, "TELEGRAM_UNLINK", link_id=links[0]["link_id"], reason="Lost phone")
    assert len(read(db, worker)["telegram"]) == 1
    step(db, worker, "LEAVE", effective_date=str(db.today - timedelta(days=1)), reason="Left")
    gone = run(
        db.runtime_url, "SELECT app.hr_telegram_staff(%s, %s, %s)", db.property_id, 5550001, db.bot
    )
    assert gone == {"linked": False}


def test_documents_keep_the_file_and_hide_id_cards(hr_database: HrDatabase) -> None:
    db = hr_database
    person = add_employee(db, name_en="Heng Dara", name_km="ហេង ដារ៉ា")
    add_doc = "SELECT app.hr_add_employee_document(%s, %s, %s::jsonb, %s, NULL)"

    def body(kind: str) -> str:
        return json.dumps(
            {
                "kind": kind,
                "title": "Paper " + kind,
                "sha256": "a" * 64,
                "byte_size": 1200,
                "media_type": "application/pdf",
                "original_name": "paper.pdf",
                "storage_key": f"hr/{uuid.uuid4().hex}.pdf",
            }
        )

    refused(db.runtime_url, "42501", add_doc, db.property_id, person, body("ID_CARD"), db.manager)
    contract = run(db.runtime_url, add_doc, db.property_id, person, body("CONTRACT"), db.manager)
    card = run(db.runtime_url, add_doc, db.property_id, person, body("ID_CARD"), db.owner)
    assert [item["kind"] for item in read(db, person, db.manager)["documents"]] == ["CONTRACT"]
    # The ID photo from Add employee and the one added later.
    assert sorted(item["kind"] for item in read(db, person)["documents"]) == [
        "CONTRACT",
        "ID_CARD",
        "ID_CARD",
    ]
    where = "SELECT app.hr_employee_document_file(%s, %s, %s, NULL)"
    refused(db.runtime_url, "42501", where, db.property_id, card, db.manager)
    assert run(db.runtime_url, where, db.property_id, contract, db.manager)["media_type"] == (
        "application/pdf"
    )
    step(db, person, "DOCUMENT_REMOVE", db.manager, document_id=str(contract), reason="Old")
    assert [item["kind"] for item in read(db, person)["documents"]] == ["ID_CARD", "ID_CARD"]
