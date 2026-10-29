"""Migration 20270402_252 (V1-061, owner 2026-10-29, DL-111): move out one occupant.

- The Primary Tenant never moves out alone; they leave with the Lease.
- A person who signs nothing moves out on their own day.
- A Joint Signer moves out only when every other Signer agrees, and stays a Signer of the Lease.
- The only Signer still living there is refused: the Lease ends through Termination first.
Each move-out is append-only, shows in the Lease History and is answered again for the same key.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.billing import month_end
from property_rental.lease import LEASE_SIGN_CAPABILITY, LeaseDraftSigner, LeaseSignCommand
from property_rental.lease_api import PostgresLeaseResourceFlow
from property_rental.move_in import (
    MOVE_IN_CAPABILITY,
    MoveInConflictError,
    MoveInInvalidError,
    MoveInOccupant,
    MoveInVersionConflictError,
    OccupantMoveOutCommand,
    OccupantMoveOutRefusedError,
    PostgresMoveInService,
    RecordLeaseMoveInCommand,
)
from test_lease_lifecycle_migration import actor, database_now, draft_command, signature_command
from test_lease_occupant_addition_migration import _customer, _walk_in
from test_lease_signing_reservation_migration import business_date, leases
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url

FUNCTION = (
    "app.move_out_lease_occupant(uuid,uuid,text,uuid,uuid,integer,uuid,date,uuid[],text,text,uuid)"
)


class Case:
    def __init__(self, url: str) -> None:
        self.url = url
        self.actor, self.prop, unit, self.tenant = _walk_in(url)
        self.joint = _customer(url, self.actor, "Joint Signer")
        self.friend = _customer(url, self.actor, "Friend")
        service, who = leases(self.actor, self.prop)
        self.today = business_date(url, self.prop)
        draft = replace(
            draft_command(
                unit,
                self.tenant,
                start_date=self.today - timedelta(days=10),
                end_date=month_end(self.today + timedelta(days=365)),
            ),
            additional_signers=(LeaseDraftSigner(uuid4(), self.joint),),
            planned_occupant_customer_ids=(self.tenant, self.joint, self.friend),
        )
        service.draft_with_terms(draft, actor=who)
        self.lease = draft.lease_id
        version = 1
        for signer in [draft.primary_signer_id, draft.additional_signers[0].signer_id]:
            service.record_signature(signature_command(draft.lease_id, signer, version), actor=who)
            version += 1
        service.sign(
            LeaseSignCommand(
                idempotency_key=uuid4(),
                event_id=uuid4(),
                lease_id=draft.lease_id,
                expected_version=version,
                signed_at=database_now(),
                reason="Lease signed",
                authorization_reference=LEASE_SIGN_CAPABILITY,
                reservation_id=None,
            ),
            actor=who,
        )
        self.occupancy = {self.tenant: uuid4(), self.joint: uuid4(), self.friend: uuid4()}
        moved = self.service().record_lease_move_in(
            RecordLeaseMoveInCommand(
                idempotency_key=uuid4(),
                event_id=uuid4(),
                lease_id=self.lease,
                expected_lease_version=version + 1,
                actual_move_in_date=self.today,
                occupants=tuple(
                    MoveInOccupant(occupancy, customer)
                    for customer, occupancy in self.occupancy.items()
                ),
                reason="Move-in recorded",
                authorization_reference=MOVE_IN_CAPABILITY,
            ),
            actor=actor(self.actor, self.prop, MOVE_IN_CAPABILITY),
        )
        self.version = int(str(moved["lease_version"]))

    def service(self) -> PostgresMoveInService:
        return PostgresMoveInService(runtime_database_url(), self.prop, self.actor)

    def command(
        self,
        customer: UUID,
        agreed: tuple[UUID, ...] = (),
        day: date | None = None,
        *,
        key: UUID | None = None,
    ) -> OccupantMoveOutCommand:
        return OccupantMoveOutCommand(
            idempotency_key=uuid4() if key is None else key,
            event_id=uuid4(),
            lease_id=self.lease,
            expected_lease_version=self.version,
            occupancy_id=self.occupancy[customer],
            move_out_date=self.today if day is None else day,
            agreed_signer_customer_ids=agreed,
            reason="Moved to Siem Reap",
            authorization_reference=MOVE_IN_CAPABILITY,
        )

    def move_out(self, command: OccupantMoveOutCommand) -> dict[str, object]:
        result = self.service().move_out_lease_occupant(
            command, actor=actor(self.actor, self.prop, MOVE_IN_CAPABILITY)
        )
        self.version = int(str(result["lease_version"]))
        return result

    def refused(self, command: OccupantMoveOutCommand) -> str:
        with pytest.raises(OccupantMoveOutRefusedError) as refused:
            self.move_out(command)
        return refused.value.reason

    def living(self) -> list[UUID]:
        lease = PostgresLeaseResourceFlow(runtime_database_url()).get(self.lease)
        return sorted(
            value.customer_id for value in lease.occupancies if value.move_out_date is None
        )


def test_a_person_who_signs_nothing_moves_out_on_their_own_day(
    migrated_database_url: str,
) -> None:
    case = Case(migrated_database_url)
    tomorrow = case.today + timedelta(days=1)
    assert case.refused(case.command(case.friend, day=tomorrow)) == "DATE"
    assert case.refused(case.command(case.friend, day=case.today - timedelta(days=1))) == "DATE"
    with pytest.raises(MoveInInvalidError):
        case.move_out(case.command(case.friend, agreed=(case.joint,)))

    command = case.command(case.friend)
    result = case.move_out(command)
    replayed = case.service().move_out_lease_occupant(
        command, actor=actor(case.actor, case.prop, MOVE_IN_CAPABILITY)
    )
    assert replayed == result
    assert (result["was_signer"], result["move_out_date"]) == (False, str(case.today))
    assert case.living() == sorted([case.tenant, case.joint])
    lease = PostgresLeaseResourceFlow(runtime_database_url()).get(case.lease)
    assert [event.event_kind for event in lease.timeline].count("lease.occupant_moved_out") == 1
    # The same key with another request, and moving out twice, are refused.
    with pytest.raises(MoveInConflictError):
        case.move_out(replace(command, reason="Another reason"))
    assert case.refused(case.command(case.friend)) == "NOT_LIVING_THERE"
    with pytest.raises(MoveInVersionConflictError):
        case.move_out(replace(case.command(case.joint, (case.tenant,)), expected_lease_version=1))


def test_the_primary_tenant_never_moves_out_alone(migrated_database_url: str) -> None:
    case = Case(migrated_database_url)
    assert case.refused(case.command(case.tenant, (case.joint,))) == "PRIMARY_TENANT"
    assert case.refused(case.command(case.tenant)) == "PRIMARY_TENANT"
    assert case.living() == sorted([case.tenant, case.joint, case.friend])


def test_a_joint_signer_moves_out_only_when_every_other_signer_agrees(
    migrated_database_url: str,
) -> None:
    case = Case(migrated_database_url)
    assert case.refused(case.command(case.joint)) == "SIGNERS_AGREE"
    assert case.refused(case.command(case.joint, (case.friend,))) == "SIGNERS_AGREE"
    result = case.move_out(case.command(case.joint, (case.tenant,)))
    assert result["was_signer"] is True
    assert result["agreed_signer_customer_ids"] == [str(case.tenant)]
    assert case.living() == sorted([case.tenant, case.friend])
    # They stay a Signer of the Lease and keep its responsibility until it ends.
    lease = PostgresLeaseResourceFlow(runtime_database_url()).get(case.lease)
    assert case.joint in {signer.customer_id for signer in lease.signers}
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT was_signer, agreed_signer_customer_ids, reason, authorization_reference "
            "FROM app.lease_occupant_move_outs WHERE occupancy_id=%s",
            (case.occupancy[case.joint],),
        ).fetchone()
    assert row == (True, [case.tenant], "Moved to Siem Reap", MOVE_IN_CAPABILITY)


def test_a_person_who_signs_nothing_may_leave_the_primary_tenant_alone(
    migrated_database_url: str,
) -> None:
    case = Case(migrated_database_url)
    case.move_out(case.command(case.joint, (case.tenant,)))
    # Only the Primary Tenant, a Signer, still lives there with the friend; the friend may still
    # move out, but no Signer can.
    case.move_out(case.command(case.friend))
    assert case.living() == [case.tenant]
    assert case.refused(case.command(case.tenant, (case.joint,))) == "PRIMARY_TENANT"


def test_the_last_signer_rule_holds_for_a_joint_signer(migrated_database_url: str) -> None:
    """When the Primary Tenant no longer lives there (the Lease is ending), the Joint Signer is
    the last Signer living there and is refused too."""
    case = Case(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.occupancies SET move_out_date=%s, version=version+1 WHERE id=%s",
            (case.today, case.occupancy[case.tenant]),
        )
    assert case.refused(case.command(case.joint, (case.tenant,))) == "LAST_SIGNER"


def test_move_outs_are_permanent_and_only_the_function_writes_them(
    migrated_database_url: str,
) -> None:
    case = Case(migrated_database_url)
    case.move_out(case.command(case.friend))
    with psycopg.connect(runtime_database_url()) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("UPDATE app.lease_occupant_move_outs SET reason='x'")
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute("DELETE FROM app.lease_occupant_move_outs")
        connection.rollback()
        grants = connection.execute(
            "SELECT has_function_privilege('prm_runtime', %s, 'EXECUTE'), "
            "has_function_privilege('prm_financial', %s, 'EXECUTE')",
            (FUNCTION, FUNCTION),
        ).fetchone()
    assert grants == (True, False)


def test_occupant_move_out_migration_is_forward_only() -> None:
    script = ScriptDirectory.from_config(Config(str(Path(__file__).parents[1] / "alembic.ini")))
    revision = script.get_revision("20270402_252")
    assert revision is not None
    assert revision.down_revision == "20270401_251"
