"""Problem reports on the real database (migration 20270426_276, V1.1 part 7, DL-124).

One list for Unit Problems (UP) and Building problems (BP). Each step is a history row; what
was reported never changes. The tenant's Agree makes the Damage Invoice draft at once for the
amount the Manager set; a Refuse charges nothing. Joined reports follow their main report.
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
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_default_role_bundles_migration import SEED_QUERY
from test_invoice_migration import financial_database_url
from test_lease_migration import create_draft, sign_lease
from test_migrations import _run_alembic, _temporary_migration_database, _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_role_bundle_migration import add_account, the_property

REVISION = "20270426_276"
GRANTS = "SELECT capability_id FROM app.actor_capability_grants(%s)"
RIGHTS = {
    "problem_reports.read",
    "problem_reports.add",
    "problem_reports.plan",
    "problem_reports.join",
}
ADD = "SELECT app.add_problem_report(%s, %s::jsonb, %s, NULL)"
STEP = "SELECT app.problem_report_step(%s, %s, %s, %s, %s::jsonb, %s, NULL)"
ANSWER = "SELECT app.record_problem_tenant_answer(%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)"
READ = "SELECT app.problem_report_read(%s, %s, %s)"


@dataclass(frozen=True)
class ProblemDatabase:
    owner_url: str
    runtime_url: str
    financial_url: str
    property_id: uuid.UUID
    owner: uuid.UUID
    manager: uuid.UUID
    staff: uuid.UUID
    leased_unit: uuid.UUID
    empty_unit: uuid.UUID
    bedroom: uuid.UUID
    tenant: uuid.UUID
    lease: uuid.UUID
    today: date


@pytest.fixture(scope="module")
def problem_database(migrated_database_url: str) -> Iterator[ProblemDatabase]:
    assert migrated_database_url
    with _temporary_migration_database("prm_problems") as temporary:
        assert _run_alembic("upgrade", "head").returncode == 0
        name = urlsplit(temporary).path.lstrip("/")
        runtime_url = _url_with_database(runtime_database_url(), name)
        financial_url = _url_with_database(financial_database_url(), name)
        with psycopg.connect(temporary) as setup:
            property_id = the_property(setup)
            owner = add_account(setup, "owner")
            manager = add_account(setup, "manager")
            staff = add_account(setup, "staff")
            seeded = setup.execute(SEED_QUERY, (property_id,)).fetchone()
            assert seeded is not None
            for actor, bundle in ((manager, seeded[1]), (staff, seeded[2])):
                setup.execute(
                    "INSERT INTO app.user_role_assignments (assignment_id, actor_id, "
                    "role_bundle_id, property_id, provenance) VALUES (%s, %s, %s, %s, 'test')",
                    (uuid.uuid4(), actor, bundle, property_id),
                )
            bedroom = setup.execute(
                "SELECT id FROM app.unit_setup_items WHERE property_id = %s "
                "AND list_kind = 'UNIT_FEATURE' AND code = 'BEDROOM'",
                (property_id,),
            ).fetchone()
            assert bedroom is not None
            today = setup.execute(
                "SELECT timezone(timezone_name, statement_timestamp())::date FROM app.properties "
                "WHERE id = %s",
                (property_id,),
            ).fetchone()
            assert today is not None
            units = []
            for number in ("U101", "U102"):
                unit = uuid.uuid4()
                setup.execute(
                    "INSERT INTO app.units (id, property_id, unit_number, floor, unit_type, "
                    "status, created_by, updated_by) "
                    "VALUES (%s, %s, %s, '1', 'ONE_BEDROOM', 'VACANT', %s, %s)",
                    (unit, property_id, number, owner, owner),
                )
                setup.execute(
                    "INSERT INTO app.unit_features (unit_id, item_id, feature_count)"
                    " VALUES (%s, %s, 1)",
                    (unit, bedroom[0]),
                )
                units.append(unit)
            tenant = uuid.uuid4()
            setup.execute(
                "INSERT INTO app.customers (id, legal_name, phone_number, created_by, updated_by) "
                "VALUES (%s, 'Sok Dara', '012 888 111', %s, %s)",
                (tenant, owner, owner),
            )
            lease = create_draft(
                setup,
                actor_id=owner,
                unit_id=units[0],
                primary_tenant_id=tenant,
                start_date=today[0] - timedelta(days=30),
                end_date=today[0] + timedelta(days=330),
            )
            sign_lease(setup, lease, owner)
            setup.commit()
        yield ProblemDatabase(
            temporary,
            runtime_url,
            financial_url,
            property_id,
            owner,
            manager,
            staff,
            units[0],
            units[1],
            uuid.UUID(str(bedroom[0])),
            tenant,
            lease,
            today[0],
        )


def run(url: str, sql: str, *params: Any) -> Any:
    with psycopg.connect(url) as connection:
        row = connection.execute(sql, params).fetchone()
        assert row is not None
        return row[0]


def refused(url: str, state: str, sql: str, *params: Any) -> None:
    with pytest.raises(psycopg.Error) as caught:
        run(url, sql, *params)
    assert caught.value.sqlstate == state, caught.value


def type_id(db: ProblemDatabase, code: str) -> str:
    return str(run(db.owner_url, "SELECT id FROM app.problem_types WHERE code = %s", code))


def place_id(db: ProblemDatabase, code: str) -> str:
    return str(run(db.owner_url, "SELECT id FROM app.problem_places WHERE code = %s", code))


def add(db: ProblemDatabase, actor: uuid.UUID, **report: Any) -> uuid.UUID:
    body = {"source": "PHONE", "urgent": False, "description": "The tap leaks"} | report
    return uuid.UUID(str(run(db.runtime_url, ADD, db.property_id, json.dumps(body), actor)))


def read(db: ProblemDatabase, report: uuid.UUID) -> dict[str, Any]:
    found = run(db.runtime_url, READ, db.property_id, report, db.owner)
    assert isinstance(found, dict)
    return found


def step(db: ProblemDatabase, report: uuid.UUID, name: str, actor: uuid.UUID, **body: Any) -> int:
    version = read(db, report)["version"]
    return int(
        run(db.runtime_url, STEP, db.property_id, report, version, name, json.dumps(body), actor)
    )


def plan(db: ProblemDatabase, report: uuid.UUID) -> None:
    step(
        db,
        report,
        "PLAN",
        db.manager,
        technician="Chan Rith",
        visit_on=str(db.today + timedelta(days=1)),
        visit_at="09:30",
    )


def unit_problem(db: ProblemDatabase, **report: Any) -> uuid.UUID:
    return add(
        db,
        db.staff,
        kind="UNIT",
        unit_id=str(db.leased_unit),
        problem_type_id=type_id(db, "WATER"),
        **report,
    )


def test_migration_276_follows_the_quotations() -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    migration = scripts.get_revision(REVISION)
    assert migration is not None
    assert migration.down_revision == "20270425_275"
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.module.downgrade()


def test_rights_rules_and_numbers_are_seeded(problem_database: ProblemDatabase) -> None:
    db = problem_database
    with psycopg.connect(db.owner_url) as connection:
        held = {
            actor: {row[0] for row in connection.execute(GRANTS, (actor,))}
            for actor in (db.owner, db.manager, db.staff)
        }
        assert RIGHTS <= held[db.owner] and RIGHTS <= held[db.manager]
        assert held[db.staff] & RIGHTS == {"problem_reports.read", "problem_reports.add"}
        rules: dict[str, Any] = dict(
            connection.execute(
                "SELECT name.code, rule.value FROM app.business_rule_names AS name "
                "JOIN app.business_rules AS rule ON rule.rule_name_id = name.id "
                "WHERE name.area = 'REPAIRS' AND name.used_by_app"
            ).fetchall()
        )
        assert rules == {
            "REPEAT_COUNT": 3,
            "REPEAT_DAYS": 90,
            "TR_URGENT_HOURS": 1,
            "TR_PLAN_WORKDAYS": 1,
            "TR_AUTO_CLOSE_DAYS": 3,
        }
        formats = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT document_type, format FROM app.number_rules "
                "WHERE document_type IN ('UNIT_PROBLEM', 'BUILDING_PROBLEM')"
            )
        }
        assert formats == {"UNIT_PROBLEM": "UPyy000n", "BUILDING_PROBLEM": "BPyy000n"}
        types = connection.execute(
            "SELECT count(*), count(*) FILTER (WHERE always_urgent) FROM app.problem_types"
        ).fetchone()
        assert types == (12, 1)
    choices = run(
        db.runtime_url, "SELECT app.problem_report_choices(%s, %s)", db.property_id, db.staff
    )
    assert len(choices["types"]) == 12 and len(choices["places"]) == 9
    unit = next(item for item in choices["units"] if item["unit_number"] == "U101")
    assert unit["customer_name"] == "Sok Dara" and unit["places"][0]["number"] == 1


def test_a_unit_problem_the_tenant_pays_makes_the_damage_draft_when_agreed(
    problem_database: ProblemDatabase,
) -> None:
    db = problem_database
    report = unit_problem(db, place_item_id=str(db.bedroom), place_number=1, may_enter=True)
    found = read(db, report)
    assert found["report_number"].startswith("UP") and found["state"] == "RECEIVED"
    assert found["customer_name"] == "Sok Dara" and found["lease_id"] == str(db.lease)
    assert found["place"]["number"] == 1 and found["history"][0]["step"] == "RECEIVED"
    # Staff add reports; only a Manager or the Owner plans them.
    refused(db.runtime_url, "42501", STEP, db.property_id, report, 1, "PLAN", "{}", db.staff)
    # A stale version is refused, and a time outside 07:00 to 16:30 too.
    refused(
        db.runtime_url,
        "40001",
        STEP,
        db.property_id,
        report,
        9,
        "NOT_A_REPAIR",
        '{"note": "x"}',
        db.manager,
    )
    late = json.dumps(
        {"technician": "Chan", "visit_on": str(db.today + timedelta(days=1)), "visit_at": "17:00"}
    )
    refused(db.runtime_url, "22023", STEP, db.property_id, report, 1, "PLAN", late, db.manager)
    refused(db.runtime_url, "55000", STEP, db.property_id, report, 1, "CONTACTED",
            '{"how": "PHONE"}', db.manager)  # fmt: skip
    plan(db, report)
    assert read(db, report)["state"] == "PLANNED"
    step(db, report, "CHECKED", db.manager, cause="DAMAGE", note="The door was kicked")
    refused(
        db.runtime_url,
        "22023",
        STEP,
        db.property_id,
        report,
        read(db, report)["version"],
        "DECIDE",
        '{"pays": "TENANT", "amount_usd_cents": 0, "reason": "x"}',
        db.manager,
    )
    step(
        db, report, "DECIDE", db.manager, pays="TENANT", amount_usd_cents=4500, reason="Kicked door"
    )
    waiting = read(db, report)
    assert waiting["state"] == "WAITING_TENANT" and waiting["damage"] is None
    assert (
        run(
            db.owner_url,
            "SELECT count(*) FROM app.authorized_nonrecurring_obligations "
            "WHERE problem_report_id = %s",
            report,
        )
        == 0
    )
    version = waiting["version"]
    # Only the financial connection records the answer.
    refused(
        db.runtime_url,
        "42501",
        ANSWER,
        db.property_id,
        report,
        version,
        "AGREED",
        "PHONE",
        db.today,
        None,
        None,
        db.manager,
    )
    run(
        db.financial_url,
        ANSWER,
        db.property_id,
        report,
        version,
        "AGREED",
        "PHONE",
        db.today,
        None,
        None,
        db.manager,
    )
    agreed = read(db, report)
    assert agreed["state"] == "REPAIR_PLANNED" and agreed["tenant_answer"] == "AGREED"
    damage = agreed["damage"]
    assert damage["invoice_status"] == "DRAFT" and damage["amount_usd_cents"] == 4500
    with psycopg.connect(db.owner_url) as connection:
        invoice = connection.execute(
            "SELECT invoice.primary_category, invoice.customer_id, invoice.lease_id, "
            "invoice.original_total_usd_cents, invoice.due_date_rule FROM app.invoices AS invoice "
            "WHERE invoice.id = %s",
            (damage["invoice_id"],),
        ).fetchone()
    assert invoice == (
        "DAMAGE_CHARGES",
        db.tenant,
        db.lease,
        4500,
        "ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS",
    )
    step(db, report, "PARTS", db.manager)
    step(db, report, "PARTS_ARRIVED", db.manager)
    step(db, report, "DONE", db.manager)
    done = read(db, report)
    assert done["state"] == "DONE" and done["closes_on"] is not None
    step(db, report, "TENANT_FIXED", db.manager)
    closed = read(db, report)
    assert closed["state"] == "CLOSED"
    assert [entry["step"] for entry in closed["history"]] == [
        "RECEIVED",
        "PLANNED",
        "CHECKED",
        "TENANT_PAYS",
        "TENANT_AGREED",
        "WAITING_PARTS",
        "PARTS_ARRIVED",
        "DONE",
        "FIXED",
    ]
    # History is never changed, and what was reported stays.
    refused(db.owner_url, "55000", "UPDATE app.problem_report_events SET note = 'x'")
    refused(
        db.owner_url,
        "55000",
        "UPDATE app.problem_reports SET description = 'x', version = version + 1 WHERE id = %s",
        report,
    )


def test_a_refused_charge_or_a_unit_without_a_lease_charges_nothing(
    problem_database: ProblemDatabase,
) -> None:
    db = problem_database
    report = unit_problem(db, urgent=True, description="No water at all")
    step(db, report, "CONTACTED", db.manager, how="PHONE")
    plan(db, report)
    step(db, report, "CHECKED", db.manager, cause="DAMAGE", fixed=True)
    step(db, report, "DECIDE", db.manager, pays="TENANT", amount_usd_cents=2000, reason="Pipe hit")
    version = read(db, report)["version"]
    refused(
        db.financial_url,
        "22023",
        ANSWER,
        db.property_id,
        report,
        version,
        "REFUSED",
        "IN_PERSON",
        db.today,
        None,
        "MOVE_OUT",
        db.manager,
    )
    run(
        db.financial_url,
        ANSWER,
        db.property_id,
        report,
        version,
        "REFUSED",
        "IN_PERSON",
        db.today,
        "It was old",
        "MOVE_OUT",
        db.manager,
    )
    found = read(db, report)
    assert found["state"] == "CLOSED" and found["close_note"] == "Left for the move-out inspection"
    assert found["damage"] is None
    empty = add(
        db,
        db.staff,
        kind="UNIT",
        unit_id=str(db.empty_unit),
        problem_type_id=type_id(db, "SAFETY"),
        source="SEEN",
        description="Smoke from the socket",
    )
    seen = read(db, empty)
    assert seen["urgent"] and seen["always_urgent"] and seen["customer_id"] is None
    step(db, empty, "CONTACTED", db.manager, how="VISIT")
    plan(db, empty)
    step(db, empty, "CHECKED", db.manager, cause="UNSURE")
    refused(
        db.runtime_url,
        "55000",
        STEP,
        db.property_id,
        empty,
        read(db, empty)["version"],
        "DECIDE",
        '{"pays": "TENANT", "amount_usd_cents": 100, "reason": "x"}',
        db.manager,
    )
    step(db, empty, "DECIDE", db.manager, pays="OWNER")
    step(db, empty, "DONE", db.manager)
    refused(
        db.runtime_url,
        "55000",
        STEP,
        db.property_id,
        empty,
        read(db, empty)["version"],
        "TENANT_FIXED",
        "{}",
        db.manager,
    )
    step(db, empty, "CLOSE", db.manager, note="Checked by the Manager")
    assert read(db, empty)["state"] == "CLOSED"


def test_building_problems_join_and_a_manager_undoes_a_join(
    problem_database: ProblemDatabase,
) -> None:
    db = problem_database
    lift = place_id(db, "LIFT")
    main = add(
        db,
        db.staff,
        kind="BUILDING",
        problem_place_id=lift,
        floor="3",
        problem_type_id=type_id(db, "ELECTRICITY"),
        description="The lift does not move",
        reported_by="Sok Dara (U101)",
    )
    first = read(db, main)
    assert first["report_number"].startswith("BP") and first["floor"] == "3"
    # A Building problem needs a repair job before a visit is planned.
    refused(db.runtime_url, "55000", STEP, db.property_id, main, 1, "PLAN",
            json.dumps({"technician": "A", "visit_on": str(db.today + timedelta(days=1)),
                        "visit_at": "10:00"}), db.manager)  # fmt: skip
    same = add(
        db,
        db.staff,
        kind="BUILDING",
        problem_place_id=lift,
        problem_type_id=type_id(db, "ELECTRICITY"),
        description="Lift stuck",
        same_as=str(main),
    )
    joined = read(db, same)
    assert joined["state"] == "JOINED" and joined["joined_to"]["report_id"] == str(main)
    assert [kid["report_id"] for kid in read(db, main)["joined"]] == [str(same)]
    refused(
        db.runtime_url,
        "42501",
        STEP,
        db.property_id,
        same,
        joined["version"],
        "UNJOIN",
        '{"note": "Not the same"}',
        db.staff,
    )
    step(db, same, "UNJOIN", db.manager, note="Another lift")
    assert read(db, same)["state"] == "RECEIVED" and read(db, main)["joined"] == []
    step(db, same, "JOIN", db.manager, main_id=str(main), reason="Same lift after all")
    assert read(db, same)["state"] == "JOINED"
    step(db, main, "MAKE_JOB", db.manager)
    plan(db, main)
    other = add(
        db,
        db.staff,
        kind="BUILDING",
        problem_place_id=place_id(db, "STAIRS"),
        problem_type_id=type_id(db, "CLEANING"),
        description="Dirty stairs",
    )
    step(db, other, "CLEANING", db.manager, cleaner="Srey Pov")
    assert read(db, other)["state"] == "DONE"


def test_late_and_repeat_are_worked_out_when_read(problem_database: ProblemDatabase) -> None:
    db = problem_database
    aircon = type_id(db, "AIR_CONDITIONER")
    reports = [
        add(
            db,
            db.staff,
            kind="UNIT",
            unit_id=str(db.empty_unit),
            problem_type_id=aircon,
            description=f"AC noise {number}",
        )
        for number in range(3)
    ]
    assert read(db, reports[1])["repeat"] is None
    repeat = read(db, reports[2])["repeat"]
    assert [item["report_id"] for item in repeat] == [str(item) for item in reports]
    with psycopg.connect(db.owner_url) as connection:
        number = connection.execute(
            "SELECT app.take_document_number('UNIT_PROBLEM', 2026)"
        ).fetchone()
        assert number is not None
        old = uuid.uuid4()
        connection.execute(
            "INSERT INTO app.problem_reports (id, property_id, report_number, kind, unit_id, "
            "problem_type_id, description, urgent, source, created_at, created_by) "
            "VALUES (%s, %s, %s, 'UNIT', %s, %s, 'Leak', true, 'PHONE', "
            "statement_timestamp() - interval '2 hours', %s)",
            (old, db.property_id, number[0], db.empty_unit, type_id(db, "WATER"), db.owner),
        )
    assert read(db, old)["late"] == "URGENT"
