"""The repair cost of a Problem report (migration 20270510_290, DL-130).

Staff type the cost in dollars or riel after the repair is done. A Manager checks it with the
receipt; the check makes one Expense report (already spent) per currency on 6050 Repairs and
maintenance for the Unit, which then follows the normal Expense approval.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from test_move_in_migration import migrated_database_url as migrated_database_url
from test_problem_reports_migration import (
    ProblemDatabase,
    plan,
    read,
    refused,
    run,
    step,
    unit_problem,
)
from test_problem_reports_migration import problem_database as problem_database

REVISION = "20270510_290"
COST = "SELECT app.record_problem_report_cost(%s, %s, %s, %s::jsonb, %s, NULL)"
CHECK = "SELECT app.check_problem_report_cost(%s, %s, %s, %s::jsonb, %s, NULL)"
RATE = 4083


def test_only_the_owner_and_manager_check_repair_costs(
    problem_database: ProblemDatabase,
) -> None:
    db = problem_database
    with psycopg.connect(db.owner_url) as connection:
        held = {
            actor: {
                row[0]
                for row in connection.execute(
                    "SELECT capability_id FROM app.actor_capability_grants(%s)", (actor,)
                )
            }
            for actor in (db.owner, db.manager, db.staff)
        }
        permission = connection.execute(
            "SELECT permission.group_code, permission.name_en FROM app.permissions AS permission "
            "JOIN app.permission_capabilities AS mapped "
            "ON mapped.permission_code = permission.permission_code "
            "WHERE mapped.capability_id = 'problem_reports.costs'"
        ).fetchall()
    assert "problem_reports.costs" in held[db.owner] & held[db.manager]
    assert "problem_reports.costs" not in held[db.staff]
    assert permission == [("OPERATIONS", "Check repair costs")]


def test_migration_290_follows_the_ledger_and_is_forward_only() -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    migration = scripts.get_revision(REVISION)
    assert migration is not None
    assert migration.down_revision == "20270429_279"
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.module.downgrade()


@pytest.fixture(scope="module")
def costs(problem_database: ProblemDatabase) -> ProblemDatabase:
    """The ledger open this year and a riel rate of 4,083 riel to the dollar."""
    db = problem_database
    with psycopg.connect(db.owner_url) as setup:
        setup.execute(
            "SELECT app.gl_start_ledger(%s, %s::smallint, %s)",
            (db.property_id, db.today.year, db.owner),
        )
        setup.execute(
            "INSERT INTO app.exchange_rate_records (id, reference_rate_khr_per_usd, "
            "markup_basis_points, system_rate_khr_per_usd, rate_source, source_reference, "
            "applicable_at, entered_by, calculation_trace) VALUES (%s, 4062.500000, 50, %s, "
            "'ABA_EQUIVALENT_MANUAL', 'Repair cost test', statement_timestamp(), %s, %s)",
            (uuid.uuid4(), RATE, db.owner, Jsonb({"system_rate_khr_per_usd": RATE})),
        )
        setup.commit()
    return db


def done_repair(db: ProblemDatabase) -> uuid.UUID:
    report = unit_problem(db)
    plan(db, report)
    step(db, report, "CHECKED", db.manager, cause="WEAR")
    step(db, report, "DECIDE", db.manager, pays="OWNER")
    step(db, report, "DONE", db.manager)
    return report


def enter(db: ProblemDatabase, report: uuid.UUID, actor: uuid.UUID, **body: Any) -> int:
    version = read(db, report)["version"]
    return int(run(db.runtime_url, COST, db.property_id, report, version, json.dumps(body), actor))


def check(db: ProblemDatabase, report: uuid.UUID, actor: uuid.UUID, **body: Any) -> int:
    version = read(db, report)["version"]
    return int(run(db.runtime_url, CHECK, db.property_id, report, version, json.dumps(body), actor))


def requests(db: ProblemDatabase, report: uuid.UUID) -> list[tuple[Any, ...]]:
    with psycopg.connect(db.owner_url) as connection:
        return connection.execute(
            "SELECT made.currency, request.request_kind, request.status, request.amount_cents, "
            "request.original_currency, request.original_amount_minor, request.unit_id, "
            "account.code, request.requested_by, request.paid_how, request.id "
            "FROM app.problem_report_cost_sets AS cost_set "
            "JOIN app.problem_report_cost_checks AS checked ON checked.set_id = cost_set.id "
            "JOIN app.problem_report_cost_expense_requests AS made ON made.check_id = checked.id "
            "JOIN app.gl_expense_requests AS request ON request.id = made.expense_request_id "
            "JOIN app.gl_accounts AS account ON account.id = request.account_id "
            "WHERE cost_set.report_id = %s ORDER BY cost_set.set_no, made.currency DESC",
            (report,),
        ).fetchall()


LINES = [
    {"kind": "PARTS", "description": "New tap", "currency": "USD", "amount_minor": 1250},
    {"kind": "OUTSIDE_WORKER", "description": "Plumber", "currency": "KHR", "amount_minor": 40000},
    {"kind": "PARTS", "description": "Pipe tape", "currency": "USD", "amount_minor": 150},
]


def test_staff_type_the_cost_and_a_manager_check_makes_the_expense_reports(
    costs: ProblemDatabase,
) -> None:
    db = costs
    report = unit_problem(db)
    version = read(db, report)["version"]
    # Only once the repair is planned.
    refused(db.runtime_url, "55000", COST, db.property_id, report, version,
            json.dumps({"lines": LINES}), db.staff)  # fmt: skip
    plan(db, report)
    step(db, report, "CHECKED", db.manager, cause="WEAR")
    step(db, report, "DECIDE", db.manager, pays="OWNER")
    step(db, report, "DONE", db.manager)
    version = read(db, report)["version"]
    for body, state in (
        ({"lines": []}, "22023"),
        ({"no_cost": True, "lines": LINES}, "22023"),
        ({"lines": [LINES[0] | {"amount_minor": 0}]}, "22023"),
        ({"lines": [LINES[0] | {"amount_minor": 12.5}]}, "22023"),
        ({"lines": [LINES[0] | {"currency": "EUR"}]}, "22023"),
        ({"lines": [LINES[0] | {"kind": "STAFF"}]}, "22023"),
        ({"lines": [LINES[0] | {"description": " "}]}, "22023"),
        ({"lines": [LINES[0]] * 21}, "22023"),
    ):
        refused(db.runtime_url, state, COST, db.property_id, report, version,
                json.dumps(body), db.staff)  # fmt: skip
    refused(db.runtime_url, "40001", COST, db.property_id, report, version - 1,
            json.dumps({"lines": LINES}), db.staff)  # fmt: skip
    # A first entry, then a corrected one: the newest is the one shown; both are kept.
    enter(db, report, db.staff, lines=LINES[:1])
    assert enter(db, report, db.staff, lines=LINES, note="Plumber paid in riel") == version + 2
    found = read(db, report)
    cost = found["cost"]
    assert cost["set_no"] == 2 and not cost["no_cost"] and cost["note"] == "Plumber paid in riel"
    assert [line["amount_minor"] for line in cost["lines"]] == [1250, 40000, 150]
    assert cost["totals"] == [
        {"currency": "USD", "amount_minor": 1400},
        {"currency": "KHR", "amount_minor": 40000},
    ]
    assert cost["check"] is None and cost["expense_requests"] == [] and cost["can_enter"]
    # Staff do not check; a check needs the receipt and how it was paid.
    version = found["version"]
    good = {"receipt_seen": True, "spent_on": str(db.today), "paid_how": "OWN_MONEY"}
    refused(db.runtime_url, "42501", CHECK, db.property_id, report, version,
            json.dumps(good), db.staff)  # fmt: skip
    for body in (
        good | {"receipt_seen": False},
        good | {"spent_on": "not a day"},
        good | {"paid_how": "ADVANCE"},
        good | {"paid_from_code": "1010"},
        good | {"paid_how": "CASH"},
    ):
        refused(db.runtime_url, "22023", CHECK, db.property_id, report, version,
                json.dumps(body), db.manager)  # fmt: skip
    check(db, report, db.manager, **good)
    made = requests(db, report)
    assert [row[:8] for row in made] == [
        ("USD", "URGENT_REPORT", "WAITING", 1400, "USD", None, db.leased_unit, "6050"),
        ("KHR", "URGENT_REPORT", "WAITING", round(40000 * 100 / RATE), "KHR", 40000,
         db.leased_unit, "6050"),
    ]  # fmt: skip
    assert {row[8] for row in made} == {db.manager} and {row[9] for row in made} == {"OWN_MONEY"}
    cost = read(db, report)["cost"]
    assert cost["check"]["receipt_seen"] and cost["check"]["paid_how"] == "OWN_MONEY"
    assert [item["status"] for item in cost["expense_requests"]] == ["WAITING", "WAITING"]
    assert not cost["can_enter"]
    history = [event["step"] for event in read(db, report)["history"]]
    assert history[-3:] == ["COST_ENTERED", "COST_ENTERED", "COST_CHECKED"]
    # A checked cost is locked and is not checked twice.
    version = read(db, report)["version"]
    refused(db.runtime_url, "55000", COST, db.property_id, report, version,
            json.dumps({"lines": LINES}), db.staff)  # fmt: skip
    refused(db.runtime_url, "55000", CHECK, db.property_id, report, version,
            json.dumps(good), db.manager)  # fmt: skip
    # When the approver refuses every Expense report, staff may type the cost again.
    with psycopg.connect(db.owner_url) as connection:
        for row in made:
            connection.execute(
                "SELECT app.gl_decide_expense_request(%s, %s, false, 'No receipt kept', %s)",
                (row[10], db.owner, uuid.uuid4()),
            )
    assert read(db, report)["cost"]["can_enter"]
    enter(db, report, db.staff, no_cost=True, note="Fixed by our own staff")
    cost = read(db, report)["cost"]
    assert cost["no_cost"] and cost["lines"] == [] and cost["check"] is None
    refused(db.runtime_url, "55000", CHECK, db.property_id, report,
            read(db, report)["version"], json.dumps(good), db.manager)  # fmt: skip


def test_an_approved_repair_cost_is_posted_to_repairs_for_the_unit(
    costs: ProblemDatabase,
) -> None:
    db = costs
    report = done_repair(db)
    enter(db, report, db.staff, lines=LINES[:1])
    check(db, report, db.manager, receipt_seen=True, spent_on=str(db.today), paid_how="OWN_MONEY")
    (made,) = requests(db, report)
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "SELECT app.gl_decide_expense_request(%s, %s, true, NULL, %s)",
            (made[10], db.owner, uuid.uuid4()),
        )
        posted = connection.execute(
            "SELECT expense.amount_cents, expense.unit_id, account.code "
            "FROM app.gl_expenses AS expense "
            "JOIN app.gl_journal_lines AS line ON line.entry_id = expense.entry_id "
            "JOIN app.gl_accounts AS account ON account.id = line.account_id "
            "WHERE expense.expense_request_id = %s AND line.debit_cents > 0",
            (made[10],),
        ).fetchall()
    assert posted == [(1250, db.leased_unit, "6050")]
    assert read(db, report)["cost"]["expense_requests"][0]["status"] == "DONE"


def test_cost_history_is_never_changed(costs: ProblemDatabase) -> None:
    db = costs
    report = done_repair(db)
    enter(db, report, db.staff, lines=LINES[:1])
    with psycopg.connect(db.owner_url) as connection:
        for sql in (
            "UPDATE app.problem_report_cost_lines SET amount_minor = 1",
            "DELETE FROM app.problem_report_cost_sets",
            "TRUNCATE app.problem_report_cost_lines CASCADE",
        ):
            with pytest.raises(psycopg.Error) as caught, connection.transaction():
                connection.execute(sql)
            assert caught.value.sqlstate == "55000"
    with psycopg.connect(db.runtime_url) as runtime:
        with pytest.raises(psycopg.Error) as caught:
            runtime.execute(
                "INSERT INTO app.problem_report_cost_sets (report_id, set_no, entered_by) "
                "VALUES (%s, 9, %s)",
                (report, db.staff),
            )
        assert caught.value.sqlstate == "42501"
    # The list does not carry the cost; the report does.
    listed = run(
        db.runtime_url, "SELECT app.problem_reports_read(%s, %s)", db.property_id, db.owner
    )
    assert all(item.get("cost") is None for item in listed)
    assert read(db, report)["cost"]["set_no"] == 1
