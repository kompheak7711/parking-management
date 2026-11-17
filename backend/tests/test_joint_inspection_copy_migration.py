"""The Joint Inspection copy by the Tenant bot (migration 20270807_424, DL-244).

When a Joint Inspection is Done, the pull job queues its copy once for each person linked to its
Lease, in the language the person chose; the send job reads the inspection and where its two
signatures are kept, with the Telegram right only.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_joint_inspections_migration import START, call, finish, mark_all, read, sign
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_problem_reports_migration import ProblemDatabase, refused
from test_problem_reports_migration import problem_database as problem_database

REVISION = "20270807_424"
QUEUE = "SELECT app.telegram_joint_inspections_queue(%s, %s)"
FOR_OUTBOX = "SELECT app.telegram_joint_inspection_for_outbox(%s, %s, %s)"
TENANT = 8870101
LATE = 8870102


def test_migration_424_is_the_head_and_is_forward_only() -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    migration = scripts.get_revision(REVISION)
    assert migration is not None and migration.down_revision == "20270805_423"
    assert scripts.get_heads() == [REVISION]
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.module.downgrade()


def link(db: ProblemDatabase, person: int, at: str = "clock_timestamp()") -> None:
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.tenant_telegram_links (property_id, telegram_user_id, customer_id, "
            f"lease_id, unit_id, linked_at, created_by) VALUES (%s, %s, %s, %s, %s, {at}, %s)",
            (db.property_id, person, db.tenant, db.lease, db.leased_unit, db.owner),
        )


def copies(db: ProblemDatabase, inspection: uuid.UUID) -> list[tuple[Any, ...]]:
    with psycopg.connect(db.owner_url) as connection:
        return [
            tuple(row)
            for row in connection.execute(
                "SELECT outbox.id, outbox.chat_id, outbox.text_code, outbox.language, "
                "outbox.details FROM app.telegram_joint_inspection_notices AS notice "
                "JOIN app.telegram_outbox AS outbox ON outbox.id = notice.outbox_id "
                "WHERE notice.inspection_id = %s ORDER BY notice.created_at",
                (inspection,),
            ).fetchall()
        ]


def test_a_done_inspection_goes_once_to_each_person_linked_to_its_lease(
    problem_database: ProblemDatabase,
) -> None:
    db = problem_database
    link(db, TENANT)
    inspection = uuid.UUID(
        str(call(db, START, db.property_id, db.lease, "MOVE_IN", None, None, db.staff))
    )
    mark_all(db, inspection, db.staff)
    tenant_sign = sign(db, inspection, "TENANT_SIGNATURE", db.staff)
    staff_sign = sign(db, inspection, "STAFF_SIGNATURE", db.staff)
    # A Draft is never sent.
    assert call(db, QUEUE, db.property_id, db.manager) == 0
    finish(db, inspection, db.staff)
    done_at = read(db, inspection)["done_at"]
    assert done_at is not None
    # Someone who links two days after the inspection does not get it.
    link(db, LATE, "clock_timestamp() + interval '2 days'")
    refused(db.runtime_url, "42501", QUEUE, db.property_id, db.staff)
    assert call(db, QUEUE, db.property_id, db.manager) == 1
    assert call(db, QUEUE, db.property_id, db.manager) == 0
    sent = copies(db, inspection)
    assert [(chat, code, language) for _, chat, code, language, _ in sent] == [
        (TENANT, "tenant.joint_inspection", "km")
    ]
    details = sent[0][4]
    number = read(db, inspection)["inspection_number"]
    assert details["number"] == number and details["kind"] == "ពេលចូលស្នាក់នៅ"
    assert details["date"] == db.today.strftime("%d/%m/%Y")

    # The send job reads the inspection and where the two signatures are kept.
    outbox = sent[0][0]
    found = call(db, FOR_OUTBOX, db.property_id, outbox, db.manager)
    assert found["inspection"]["inspection_number"] == number
    assert set(found["files"]) == {str(tenant_sign), str(staff_sign)}
    assert all(
        str(where["storage_key"]).startswith("inspections/") for where in found["files"].values()
    )
    assert call(db, FOR_OUTBOX, db.property_id, uuid.uuid4(), db.manager) is None
    refused(db.runtime_url, "42501", FOR_OUTBOX, db.property_id, outbox, db.staff)
    # What was queued is never changed.
    with pytest.raises(psycopg.Error), psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "DELETE FROM app.telegram_joint_inspection_notices WHERE outbox_id = %s", (outbox,)
        )
