"""The shared draft reads leave out the decision's transaction id (V1-056 slice 11b)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast
from uuid import uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from property_rental.financial_draft import FINANCIAL_APPROVE_CAPABILITY
from test_financial_draft_migration import _catalog, _draft, _service, _sources
from test_lease_lifecycle_migration import (
    actor,
    migrated_database_url,  # noqa: F401
)
from test_migrations import _temporary_migration_database

REVISION = "20270208_196"
PATCHED = {
    "app.financial_draft_resource_by_capability(uuid,uuid,uuid,text[])",
    "app.list_financial_drafts_by_capability(uuid,uuid,text[],text,integer,"
    "timestamp with time zone,uuid)",
}


def test_the_shared_reads_leave_out_the_transaction_id_of_a_confirmed_draft(
    migrated_database_url: str,  # noqa: F811
) -> None:
    owner_id, property_id = _sources(migrated_database_url)
    draft_id = _draft(migrated_database_url, property_id, owner_id)
    refund_id = str(uuid4())
    with psycopg.connect(migrated_database_url) as connection:
        confirmed = connection.execute(
            "SELECT app.confirm_financial_draft_record(%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                owner_id,
                draft_id,
                "REFUND",
                Jsonb({"refund_id": refund_id, "transaction_id": "4471"}),
                FINANCIAL_APPROVE_CAPABILITY,
            ),
        ).fetchone()
        connection.commit()
    assert confirmed is not None
    # The confirm command's own answer is unchanged; its replay checks still read the id.
    assert cast(dict[str, dict[str, dict[str, object]]], confirmed[0])["decision"]["result"] == {
        "refund_id": refund_id,
        "transaction_id": "4471",
    }
    approver = actor(owner_id, property_id, FINANCIAL_APPROVE_CAPABILITY)
    read = _service().get(property_id, draft_id, actor=approver)
    listed = [
        item
        for item in cast(
            list[dict[str, object]], _service().list(property_id, actor=approver)["items"]
        )
        if item["draft_id"] == str(draft_id)
    ]
    for value in (read, *listed):
        assert value["state"] == "CONFIRMED"
        assert cast(dict[str, object], value["decision"])["result"] == {"refund_id": refund_id}
        assert "transaction_id" not in json.dumps(value)
    assert len(listed) == 1


def test_the_migration_changes_only_the_two_shared_reads(
    migrated_database_url: str,  # noqa: F811
) -> None:
    assert migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270207_195"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database("draft_reads_transaction_id") as temporary:
        alembic_command.upgrade(config, "20270207_195")
        before_functions, before_tables = _catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_tables = _catalog(temporary)
    assert after_tables == before_tables
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED
    # Each patched function changed only its definition, never its privileges.
    for name in PATCHED:
        assert after_functions[name][1:] == before_functions[name][1:], name
        assert "#- '{decision,result,transaction_id}'" in str(after_functions[name][0])
