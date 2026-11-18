"""The Joint Inspection on the real database (migration 20270805_423, DL-201, DL-243).

Staff mark every place and item Good, Broken or Missing, count the keys and write the meter
numbers; the tenant signs first, then the staff member. Finishing makes a Problem report for
each new Broken or Missing line and, at move-out, the damage findings the tenant caused.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_move_in_migration import migrated_database_url as migrated_database_url
from test_problem_reports_migration import ProblemDatabase, refused, run
from test_problem_reports_migration import problem_database as problem_database

REVISION = "20270805_423"
START = "SELECT app.joint_inspection_start(%s, %s, %s, %s, %s, %s, NULL)"
SAVE = "SELECT app.joint_inspection_save(%s, %s, %s, %s::jsonb, %s)"
ADD_FILE = "SELECT app.joint_inspection_add_file(%s, %s, %s, %s::jsonb, %s)"
REMOVE_FILE = "SELECT app.joint_inspection_remove_file(%s, %s, %s)"
FILE = "SELECT app.joint_inspection_file(%s, %s, %s)"
FINISH = "SELECT app.joint_inspection_finish(%s, %s, %s, %s, NULL)"
READ = "SELECT app.joint_inspection_read(%s, %s, %s)"
LIST = "SELECT app.joint_inspections_read(%s, %s, %s)"

__all__ = ["migrated_database_url", "problem_database"]


def test_migration_423_follows_the_head_and_is_forward_only() -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    migration = scripts.get_revision(REVISION)
    assert migration is not None and migration.down_revision == "20270804_422"
    # The copy by the Tenant bot (DL-244) follows it.
    assert scripts.get_heads() == ["20270810_433_parking"]
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.module.downgrade()


def call(db: ProblemDatabase, sql: str, *params: Any) -> Any:
    with psycopg.connect(db.runtime_url) as connection:
        row = connection.execute(sql, params).fetchone()
        return None if row is None else row[0]


def read(db: ProblemDatabase, inspection: uuid.UUID) -> dict[str, Any]:
    found = call(db, READ, db.property_id, inspection, db.staff)
    assert isinstance(found, dict)
    return found


def save(db: ProblemDatabase, inspection: uuid.UUID, actor: uuid.UUID, **changes: Any) -> None:
    version = read(db, inspection)["version"]
    call(db, SAVE, db.property_id, inspection, version, json.dumps(changes), actor)


def sign(db: ProblemDatabase, inspection: uuid.UUID, role: str, actor: uuid.UUID) -> uuid.UUID:
    version = read(db, inspection)["version"]
    body = {
        "role": role,
        "media_type": "image/png",
        "byte_size": 1200,
        "sha256": "a" * 64,
        "storage_key": f"inspections/{inspection}/{uuid.uuid4()}.png",
    }
    return uuid.UUID(
        str(call(db, ADD_FILE, db.property_id, inspection, version, json.dumps(body), actor))
    )


def mark_all(
    db: ProblemDatabase, inspection: uuid.UUID, actor: uuid.UUID, **special: dict[str, Any]
) -> None:
    lines = []
    for line in read(db, inspection)["lines"]:
        lines.append(
            {"line_id": line["line_id"], "result": "GOOD"} | special.get(line["group_en"], {})
        )
    meters = [
        {"utility_type": meter["utility_type"], "reading": "1250.5"}
        for meter in read(db, inspection)["meters"]
    ]
    save(
        db,
        inspection,
        actor,
        lines=lines,
        meters=meters,
        keys={"door_keys": 2, "key_cards": 1, "mailbox_keys": 1, "other_keys": 0},
    )


def finish(db: ProblemDatabase, inspection: uuid.UUID, actor: uuid.UUID) -> dict[str, Any]:
    version = read(db, inspection)["version"]
    done = call(db, FINISH, db.property_id, inspection, version, actor)
    assert isinstance(done, dict)
    return done


def add_meter(db: ProblemDatabase) -> uuid.UUID:
    meter = uuid.uuid4()
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.utility_meters (id, unit_id, serial_number, utility_type, "
            "measurement_unit_code, installed_date, created_by, updated_by) "
            "VALUES (%s, %s, 'E-1001', 'ELECTRICITY', 'KWH', %s, %s, %s)",
            (meter, db.leased_unit, db.today - timedelta(days=400), db.owner, db.owner),
        )
    return meter


def test_a_move_in_then_a_move_out_joint_inspection(problem_database: ProblemDatabase) -> None:
    db = problem_database
    add_meter(db)
    # Staff start it; there is one Draft at a time; a reason is only for a replacement.
    refused(
        db.runtime_url, "22023", START, db.property_id, db.lease, "MOVE_IN", None, "x", db.staff
    )
    refused(db.runtime_url, "22023", START, db.property_id, db.lease, "LATER", None, None, db.staff)
    refused(
        db.runtime_url,
        "42501",
        START,
        db.property_id,
        db.lease,
        "MOVE_IN",
        None,
        None,
        uuid.uuid4(),
    )
    move_in = uuid.UUID(
        str(call(db, START, db.property_id, db.lease, "MOVE_IN", None, None, db.staff))
    )
    refused(
        db.runtime_url, "55000", START, db.property_id, db.lease, "MOVE_IN", None, None, db.staff
    )

    found = read(db, move_in)
    assert found["status"] == "DRAFT" and found["kind"] == "MOVE_IN"
    assert found["inspection_number"].startswith("JI")
    assert found["unit_number"] == "U101" and found["tenant_name"] == "Sok Dara"
    assert [line["line_kind"] for line in found["lines"]] == ["PLACE"]
    assert [meter["utility_type"] for meter in found["meters"]] == ["ELECTRICITY"]
    bedroom = found["lines"][0]
    assert bedroom["group_en"] == "Bedroom"

    # A place is never Missing; a problem needs a note before signing.
    refused(
        db.runtime_url,
        "22023",
        SAVE,
        db.property_id,
        move_in,
        found["version"],
        json.dumps({"lines": [{"line_id": bedroom["line_id"], "result": "MISSING"}]}),
        db.staff,
    )
    # Tenant caused is only at move-out.
    refused(
        db.runtime_url,
        "22023",
        SAVE,
        db.property_id,
        move_in,
        found["version"],
        json.dumps(
            {"lines": [{"line_id": bedroom["line_id"], "result": "BROKEN", "tenant_caused": True}]}
        ),
        db.staff,
    )
    # An old version is refused.
    mark_all(db, move_in, db.staff, Bedroom={"result": "BROKEN"})
    refused(
        db.runtime_url,
        "40001",
        SAVE,
        db.property_id,
        move_in,
        found["version"],
        json.dumps({"lines": []}),
        db.staff,
    )
    refused(
        db.runtime_url,
        "22023",
        ADD_FILE,
        db.property_id,
        move_in,
        read(db, move_in)["version"],
        json.dumps(
            {
                "role": "TENANT_SIGNATURE",
                "media_type": "image/png",
                "byte_size": 9,
                "sha256": "b" * 64,
                "storage_key": f"inspections/{move_in}/{uuid.uuid4()}.png",
            }
        ),
        db.staff,
    )
    save(
        db,
        move_in,
        db.staff,
        lines=[{"line_id": bedroom["line_id"], "note": "Window latch broken"}],
    )

    # The tenant signs first; a change after signing clears both signatures.
    refused(
        db.runtime_url,
        "22023",
        ADD_FILE,
        db.property_id,
        move_in,
        read(db, move_in)["version"],
        json.dumps(
            {
                "role": "STAFF_SIGNATURE",
                "media_type": "image/png",
                "byte_size": 9,
                "sha256": "b" * 64,
                "storage_key": f"inspections/{move_in}/{uuid.uuid4()}.png",
            }
        ),
        db.staff,
    )
    sign(db, move_in, "TENANT_SIGNATURE", db.staff)
    sign(db, move_in, "STAFF_SIGNATURE", db.staff)
    save(db, move_in, db.staff, keys={"door_keys": 3})
    assert read(db, move_in)["signatures"]["tenant"] is None
    refused(
        db.runtime_url,
        "22023",
        FINISH,
        db.property_id,
        move_in,
        read(db, move_in)["version"],
        db.staff,
    )
    tenant_mark = sign(db, move_in, "TENANT_SIGNATURE", db.staff)
    sign(db, move_in, "STAFF_SIGNATURE", db.staff)
    assert call(db, FILE, db.property_id, tenant_mark, db.staff)["media_type"] == "image/png"

    done = finish(db, move_in, db.staff)
    assert len(done["reports"]) == 1 and done["damage_findings"] == 0
    found = read(db, move_in)
    assert found["status"] == "DONE" and found["lines"][0]["problem_report"] is not None
    report = run(
        db.owner_url,
        "SELECT row_to_json(r) FROM app.problem_reports r WHERE id = %s",
        found["lines"][0]["problem_report"]["report_id"],
    )
    assert report["source"] == "JOINT_INSPECTION" and report["lease_id"] == str(db.lease)
    assert "Window latch broken" in report["description"]
    # Done is locked; only a Manager starts a replacement.
    refused(
        db.runtime_url,
        "55000",
        SAVE,
        db.property_id,
        move_in,
        found["version"],
        json.dumps({"keys": {"door_keys": 1}}),
        db.staff,
    )
    refused(
        db.owner_url,
        "55000",
        "UPDATE app.joint_inspections SET door_keys = 9 WHERE id = %s RETURNING id",
        move_in,
    )
    refused(
        db.owner_url,
        "55000",
        "DELETE FROM app.joint_inspections WHERE id = %s RETURNING id",
        move_in,
    )
    refused(
        db.runtime_url, "55000", START, db.property_id, db.lease, "MOVE_IN", None, None, db.staff
    )
    refused(
        db.runtime_url,
        "42501",
        START,
        db.property_id,
        db.lease,
        "MOVE_IN",
        move_in,
        "Wrong count",
        db.staff,
    )

    # Move-out: the move-in result shows beside each line.
    move_out = uuid.UUID(
        str(call(db, START, db.property_id, db.lease, "MOVE_OUT", None, None, db.staff))
    )
    found = read(db, move_out)
    assert found["move_in_id"] == str(move_in)
    assert found["lines"][0]["move_in_result"] == "BROKEN"
    assert found["move_in_keys"]["door_keys"] == 3
    # Same as at move-in: no Tenant caused, and no new report.
    mark_all(db, move_out, db.staff, Bedroom={"result": "BROKEN", "note": "Latch still broken"})
    refused(
        db.runtime_url,
        "22023",
        SAVE,
        db.property_id,
        move_out,
        read(db, move_out)["version"],
        json.dumps({"lines": [{"line_id": found["lines"][0]["line_id"], "tenant_caused": True}]}),
        db.staff,
    )
    sign(db, move_out, "TENANT_SIGNATURE", db.staff)
    sign(db, move_out, "STAFF_SIGNATURE", db.staff)
    done = finish(db, move_out, db.staff)
    assert done["reports"] == [] and done["damage_findings"] == 0
    first_v1 = read(db, move_out)["move_out_inspection_id"]
    assert first_v1 is not None

    # A Manager replaces the move-out; it starts from what the first one said.
    refused(
        db.runtime_url,
        "22023",
        START,
        db.property_id,
        db.lease,
        "MOVE_OUT",
        move_out,
        " ",
        db.manager,
    )
    again = uuid.UUID(
        str(
            call(
                db,
                START,
                db.property_id,
                db.lease,
                "MOVE_OUT",
                move_out,
                "Tenant asked for a second look",
                db.manager,
            )
        )
    )
    copied = read(db, again)
    assert copied["replaces"]["inspection_id"] == str(move_out)
    assert copied["lines"][0]["result"] == "BROKEN" and copied["keys"]["door_keys"] == 2
    # Signatures are never copied.
    assert copied["signatures"]["tenant"] is None
    sign(db, again, "TENANT_SIGNATURE", db.manager)
    sign(db, again, "STAFF_SIGNATURE", db.manager)
    finish(db, again, db.manager)
    assert read(db, move_out)["status"] == "REPLACED"
    second_v1 = read(db, again)["move_out_inspection_id"]
    assert run(
        db.owner_url,
        "SELECT supersedes_inspection_id FROM app.move_out_inspections WHERE id = %s",
        second_v1,
    ) == uuid.UUID(first_v1)

    listed = call(db, LIST, db.property_id, db.staff, db.lease)
    assert [(row["kind"], row["status"]) for row in listed] == [
        ("MOVE_OUT", "DONE"),
        ("MOVE_OUT", "REPLACED"),
        ("MOVE_IN", "DONE"),
    ]
    assert all(row["lease_id"] == str(db.lease) for row in listed)


def test_tenant_caused_lines_become_damage_findings(problem_database: ProblemDatabase) -> None:
    db = problem_database
    # A second Lease on the empty Unit, with no move-in inspection.
    from test_lease_migration import create_draft, sign_lease

    with psycopg.connect(db.owner_url) as connection:
        lease = create_draft(
            connection,
            actor_id=db.owner,
            unit_id=db.empty_unit,
            primary_tenant_id=db.tenant,
            start_date=db.today - timedelta(days=20),
            end_date=db.today + timedelta(days=340),
        )
        sign_lease(connection, lease, db.owner)
        connection.commit()
    move_out = uuid.UUID(
        str(call(db, START, db.property_id, lease, "MOVE_OUT", None, None, db.staff))
    )
    line = read(db, move_out)["lines"][0]
    assert line["move_in_result"] is None
    mark_all(
        db,
        move_out,
        db.staff,
        Bedroom={
            "result": "BROKEN",
            "note": "Hole in the wall",
            "tenant_caused": True,
            "pet_caused": True,
        },
    )
    sign(db, move_out, "TENANT_SIGNATURE", db.staff)
    sign(db, move_out, "STAFF_SIGNATURE", db.staff)
    done = finish(db, move_out, db.staff)
    assert done["damage_findings"] == 1 and len(done["reports"]) == 1
    found = read(db, move_out)
    finding = run(
        db.owner_url,
        "SELECT row_to_json(f) FROM app.inspection_damage_findings f WHERE id = %s",
        found["lines"][0]["finding_id"],
    )
    assert finding["pet_related"] is True and "Hole in the wall" in finding["description"]
