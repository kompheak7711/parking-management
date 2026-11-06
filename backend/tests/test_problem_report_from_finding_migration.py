"""A Problem report from a move-out inspection finding (migration 20270512_292, DL-132).

The New Problem report copies the Unit and the text of a finding; the report keeps the link, a
finding has at most one report, and a replaced inspection makes none.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.move_out_inspection import (
    INSPECTION_READ,
    INSPECTION_RECORD,
    InspectionFinding,
    PostgresMoveOutInspectionService,
    RecordMoveOutInspection,
)
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_problem_reports_migration import (
    ProblemDatabase,
    add,
    read,
    refused,
    run,
    type_id,
)
from test_problem_reports_migration import problem_database as problem_database

REVISION = "20270512_292"
FINDING = "SELECT app.problem_report_finding(%s, %s, %s)"
ADD = "SELECT app.add_problem_report(%s, %s::jsonb, %s, NULL)"

__all__ = ["migrated_database_url", "problem_database"]


def test_migration_292_follows_the_monthly_report_and_is_forward_only() -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    migration = scripts.get_revision(REVISION)
    assert migration is not None
    assert migration.down_revision == "20270511_291"
    assert scripts.get_heads() == ["20270624_335"]
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.module.downgrade()


def inspect(
    db: ProblemDatabase, *texts: str, supersedes: uuid.UUID | None = None
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    findings = [InspectionFinding(uuid.uuid4(), words, False) for words in texts]
    command = RecordMoveOutInspection(
        uuid.uuid4(),
        uuid.uuid4(),
        int(str(run(db.owner_url, "SELECT version FROM app.leases WHERE id = %s", db.lease))),
        db.today,
        "Checked at move-out",
        "Manager walk-through",
        "Photos 1-3",
        "Move-out inspection",
        tuple(findings),
        supersedes_inspection_id=supersedes,
    )
    who = AuthenticatedActor(
        str(db.owner),
        frozenset(
            CapabilityGrant(capability, frozenset({str(db.property_id)}))
            for capability in (INSPECTION_READ, INSPECTION_RECORD)
        ),
    )
    PostgresMoveOutInspectionService(db.runtime_url, db.financial_url).record(
        db.property_id, db.lease, command, actor=who, request_id=f"find-{uuid.uuid4().hex[:8]}"
    )
    return command.inspection_id, [finding.finding_id for finding in findings]


def finding(db: ProblemDatabase, actor: uuid.UUID, found: uuid.UUID) -> dict[str, Any]:
    answer = run(db.runtime_url, FINDING, db.property_id, actor, found)
    assert isinstance(answer, dict)
    return answer


def from_finding(db: ProblemDatabase, found: uuid.UUID, **change: Any) -> uuid.UUID:
    return add(
        db,
        db.staff,
        **{
            "kind": "UNIT",
            "source": "INSPECTION",
            "unit_id": str(db.leased_unit),
            "problem_type_id": type_id(db, "OTHER"),
            "description": "Bedroom door handle broken",
            "finding_id": str(found),
        }
        | change,
    )


def test_a_finding_makes_one_problem_report_in_the_inspected_unit(
    problem_database: ProblemDatabase,
) -> None:
    db = problem_database
    inspection, (handle, tile) = inspect(db, "Bedroom door handle broken", "Cracked tile")
    copied = finding(db, db.staff, handle)
    assert copied["unit_id"] == str(db.leased_unit) and copied["unit_number"] == "U101"
    assert copied["description"] == "Bedroom door handle broken"
    assert copied["inspection_id"] == str(inspection) and copied["report"] is None
    assert copied["replaced"] is False

    # The source and the finding go together, in the inspected Unit, as a Unit Problem.
    body = {"kind": "UNIT", "unit_id": str(db.leased_unit),
            "problem_type_id": type_id(db, "OTHER"), "description": "x"}  # fmt: skip
    refused(db.runtime_url, "22023", ADD, db.property_id,
            json_of(body | {"source": "INSPECTION"}), db.staff)  # fmt: skip
    refused(db.runtime_url, "22023", ADD, db.property_id,
            json_of(body | {"source": "SEEN", "finding_id": str(handle)}), db.staff)  # fmt: skip
    refused(db.runtime_url, "22023", ADD, db.property_id,
            json_of(body | {"source": "INSPECTION", "finding_id": str(handle),
                            "unit_id": str(db.empty_unit)}), db.staff)  # fmt: skip
    refused(db.runtime_url, "22023", ADD, db.property_id,
            json_of(body | {"source": "INSPECTION", "finding_id": str(uuid.uuid4())}),
            db.staff)  # fmt: skip

    made = from_finding(db, handle)
    report = read(db, made)
    assert report["source"] == "INSPECTION" and report["kind"] == "UNIT"
    assert report["finding"]["finding_id"] == str(handle)
    assert report["finding"]["inspection_date"] == str(db.today)
    again = finding(db, db.staff, handle)
    assert again["report"] == {"report_id": str(made), "report_number": report["report_number"]}
    # One report for one finding; the link is never changed.
    refused(db.runtime_url, "55000", ADD, db.property_id,
            json_of({"kind": "UNIT", "source": "INSPECTION", "unit_id": str(db.leased_unit),
                     "problem_type_id": type_id(db, "OTHER"), "description": "Again",
                     "urgent": False, "finding_id": str(handle)}), db.staff)  # fmt: skip
    refused(db.owner_url, "55000",
            "UPDATE app.problem_report_inspection_links SET created_at = now() "
            "WHERE report_id = %s RETURNING report_id", made)  # fmt: skip

    # A replaced inspection makes no report; its replacement does.
    newer, (newer_tile,) = inspect(db, "Cracked tile", supersedes=inspection)
    assert finding(db, db.staff, tile)["replaced"] is True
    refused(db.runtime_url, "55000", ADD, db.property_id,
            json_of({"kind": "UNIT", "source": "INSPECTION", "unit_id": str(db.leased_unit),
                     "problem_type_id": type_id(db, "OTHER"), "description": "Tile",
                     "urgent": False, "finding_id": str(tile)}), db.staff)  # fmt: skip
    assert read(db, from_finding(db, newer_tile))["finding"]["inspection_id"] == str(newer)
    # Reading a finding for a new report needs the add right.
    refused(db.runtime_url, "42501", FINDING, db.property_id, uuid.uuid4(), handle)
    refused(db.runtime_url, "22023", FINDING, db.property_id, db.staff, uuid.uuid4())


def json_of(body: dict[str, Any]) -> str:
    return json.dumps({"urgent": False} | body)
