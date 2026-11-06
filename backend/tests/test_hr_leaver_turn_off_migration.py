"""HRIS phase 6 step 4: a leaver's app user is turned off after the last working day (PR-HR-009).

Migration 20270503_303 adds app.hr_turn_off_leavers, which the billing worker calls as its
service actor on every pass.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from property_rental.hr_leaver_job import HrLeaverTurnOffJob, LeaverPassResult
from test_hr_employees_migration import HrDatabase, add_employee, make_hr_database, refused, step
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_role_bundle_migration import add_account

TURN_OFF = "SELECT app.hr_turn_off_leavers(%s, %s, statement_timestamp())"


@pytest.fixture(scope="module")
def hr_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_hr_leavers")


def new_user(db: HrDatabase, account_class: str = "staff") -> uuid.UUID:
    with psycopg.connect(db.owner_url) as setup:
        return add_account(setup, account_class)


def linked_employee(db: HrDatabase, user: uuid.UUID, code: str) -> uuid.UUID:
    person = add_employee(db, name_en=f"Leaver {code}", employee_code=code)
    step(db, person, "DETAILS", user_actor_id=str(user))
    return person


def state_of(db: HrDatabase, user: uuid.UUID) -> str:
    with psycopg.connect(db.owner_url) as connection:
        row = connection.execute(
            "SELECT lifecycle_state FROM app.user_accounts WHERE actor_id = %s", (user,)
        ).fetchone()
    assert row is not None
    return str(row[0])


def test_a_leaver_is_turned_off_the_day_after_the_last_working_day(
    hr_database: HrDatabase,
) -> None:
    db = hr_database
    gone, today, later, boss = (new_user(db) for _ in range(4))
    owner_person = linked_employee(db, db.owner, "E-901")
    for user, code, days in ((gone, "E-902", -1), (today, "E-903", 0), (later, "E-904", 3)):
        person = linked_employee(db, user, code)
        step(
            db,
            person,
            "LEAVE",
            db.manager,
            effective_date=str(db.today + timedelta(days=days)),
            reason="Moved away",
        )
    step(
        db,
        owner_person,
        "LEAVE",
        effective_date=str(db.today - timedelta(days=5)),
        reason="Owner record",
    )
    # A working employee with a user and a leaver without a user are not touched.
    linked_employee(db, boss, "E-905")

    job = HrLeaverTurnOffJob(db.financial_url, property_id=db.property_id, actor_id=db.bot)
    assert job.run(as_of=datetime.now(UTC)) == LeaverPassResult(1)
    assert [state_of(db, user) for user in (gone, today, later, boss, db.owner)] == [
        "disabled",
        "active",
        "active",
        "active",
        "active",
    ]
    # The next pass finds nothing new: a turned-off user stays off and is not counted again.
    assert job.run(as_of=datetime.now(UTC)) == LeaverPassResult(0)

    with psycopg.connect(db.owner_url) as connection:
        change = connection.execute(
            "SELECT version, changed_by_actor_id, previous_state ->> 'lifecycle_state', "
            "resulting_state ->> 'lifecycle_state', provenance FROM app.user_account_changes "
            "WHERE actor_id = %s",
            (gone,),
        ).fetchall()
        audit = connection.execute(
            "SELECT actor_id, action, source, reason, authorization_reference, "
            "resulting_state ->> 'leaving_recorded_by' FROM app.audit_events "
            "WHERE entity_type = 'user_account' AND entity_id = %s",
            (gone,),
        ).fetchall()
    # The account history names the person who recorded the leaving (the Manager here).
    assert change == [(2, db.manager, "active", "disabled", "hr-left-turn-off")]
    yesterday = (db.today - timedelta(days=1)).strftime("%d/%m/%Y")
    assert audit == [
        (
            db.bot,
            "identity.account.disabled",
            "SCHEDULED",
            f"Employee E-902 left: the last working day was {yesterday}",
            "hr.employees.manage",
            str(db.manager),
        )
    ]


def test_only_the_worker_runs_the_pass_at_the_real_time(hr_database: HrDatabase) -> None:
    db = hr_database
    # A person cannot run it, even the Owner, and the screens' login has no right to it.
    refused(db.financial_url, "42501", TURN_OFF, db.property_id, db.owner)
    refused(db.runtime_url, "42501", TURN_OFF, db.property_id, db.bot)
    refused(
        db.financial_url,
        "22023",
        "SELECT app.hr_turn_off_leavers(%s, %s, statement_timestamp() - interval '2 hours')",
        db.property_id,
        db.bot,
    )
    # A service actor of another Property is refused.
    refused(db.financial_url, "55000", TURN_OFF, uuid.uuid4(), db.bot)
