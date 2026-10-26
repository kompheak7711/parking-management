"""Staff record the day-20 and day-30 Rent letters (migration 20270310_229, owner 2026-10-25)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.access_control import (
    STAFF_DEFAULT_BUNDLE_CAPABILITIES,
    STAFF_L1C_BUNDLE_CAPABILITIES,
    STAFF_RENT_LETTER_CAPABILITIES,
)
from test_default_role_bundles_migration import (
    add_owner_and_property,
    bundle_capabilities,
    seed,
)
from test_migrations import _run_alembic, _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_role_bundle_migration import add_account, assign, grants, next_version, the_property

REVISION = "20270310_229"
PREVIOUS = "20270309_228"


def version(connection: psycopg.Connection[Any], bundle: uuid.UUID) -> int:
    row = connection.execute(
        "SELECT version FROM app.role_bundles WHERE role_bundle_id=%s", (bundle,)
    ).fetchone()
    assert row is not None
    return int(row[0])


def test_the_staff_letter_rights_are_the_two_rent_case_rights() -> None:
    assert STAFF_RENT_LETTER_CAPABILITIES == {
        "rent_nonpayment.case_manage",
        "rent_nonpayment.event_post",
    }
    assert STAFF_DEFAULT_BUNDLE_CAPABILITIES == (
        STAFF_L1C_BUNDLE_CAPABILITIES | STAFF_RENT_LETTER_CAPABILITIES
    )
    # The Termination notice and Terminate stay with the Owner and Managers.
    assert "leases.terminate" not in STAFF_DEFAULT_BUNDLE_CAPABILITIES
    assert "leases.warn" not in STAFF_DEFAULT_BUNDLE_CAPABILITIES


def test_a_new_property_seeds_staff_with_the_letter_rights(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        property_id = the_property(connection)
        staff = add_account(connection, "staff")
        staff_bundle = seed(connection, property_id)[2]
        assert version(connection, staff_bundle) == 1
        assert bundle_capabilities(connection, staff_bundle) == set(
            STAFF_DEFAULT_BUNDLE_CAPABILITIES
        )
        assign(connection, staff, staff_bundle, property_id)
        assert {capability for capability, _ in grants(connection, staff)} >= set(
            STAFF_RENT_LETTER_CAPABILITIES
        )
        connection.rollback()


@pytest.mark.parametrize("changed_by_owner", [False, True])
def test_the_upgrade_adds_the_rights_only_to_an_untouched_default_staff_bundle(
    migrated_database_url: str, changed_by_owner: bool
) -> None:
    assert migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == PREVIOUS
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    fewer = tuple(sorted(STAFF_L1C_BUNDLE_CAPABILITIES - {"receipts.reprint"}))
    with _temporary_migration_database("prm_staff_letters") as temporary:
        assert _run_alembic("upgrade", PREVIOUS).returncode == 0
        with psycopg.connect(temporary) as setup:
            owner, property_id = add_owner_and_property(setup)
            staff = add_account(setup, "staff")
            staff_bundle = seed(setup, property_id)[2]
            assign(setup, staff, staff_bundle, property_id)
            assert bundle_capabilities(setup, staff_bundle) == set(STAFF_L1C_BUNDLE_CAPABILITIES)
            if changed_by_owner:
                assert next_version(setup, staff_bundle, fewer, "Staff") == 2
            setup.commit()
        assert _run_alembic("upgrade", REVISION).returncode == 0
        with psycopg.connect(temporary) as check:
            events = check.execute(
                "SELECT actor_id,action,entity_id,reason,source,resulting_state "
                "FROM app.audit_events WHERE action='identity.role_bundle.updated' "
                "AND source='ADMINISTRATIVE'"
            ).fetchall()
            if changed_by_owner:
                # The Owner's own change stays as it is.
                assert version(check, staff_bundle) == 2
                assert bundle_capabilities(check, staff_bundle) == set(fewer)
                assert events == []
            else:
                assert version(check, staff_bundle) == 2
                assert bundle_capabilities(check, staff_bundle) == set(
                    STAFF_DEFAULT_BUNDLE_CAPABILITIES
                )
                # Version 1 is kept in the history.
                assert check.execute(
                    "SELECT count(*) FROM app.role_bundle_capabilities "
                    "WHERE role_bundle_id=%s AND version=1",
                    (staff_bundle,),
                ).fetchone() == (len(STAFF_L1C_BUNDLE_CAPABILITIES),)
                assert {capability for capability, _ in grants(check, staff)} == set(
                    STAFF_DEFAULT_BUNDLE_CAPABILITIES
                )
                ((actor, action, entity, reason, source, resulting),) = events
                assert (actor, action, entity, source) == (
                    owner,
                    "identity.role_bundle.updated",
                    staff_bundle,
                    "ADMINISTRATIVE",
                )
                assert "2026-10-25" in reason
                assert resulting == {
                    "version": 2,
                    "added_capability_ids": sorted(STAFF_RENT_LETTER_CAPABILITIES),
                }
            # A new Property would be seeded with the letter rights.
            assert "rent_nonpayment.event_post" in str(
                check.execute(
                    "SELECT pg_catalog.pg_get_functiondef("
                    "'app.seed_default_role_bundles(uuid)'::regprocedure)"
                ).fetchone()
            )
