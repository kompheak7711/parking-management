"""V1-056 sub-slice 6b: Lease Deposit forfeiture reversal drafts and capability-scoped reads."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Barrier
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from deposit_disposition_test_support import disposition_context
from lease_deposit_forfeiture_test_support import (
    forfeit_through_draft,
    record_disposition_as_owner,
    reverse_disposition_as_owner,
)
from property_rental.deposit import (
    AdjustDepositRequiredAmountCommand,
    DepositAdjustmentType,
    PostgresDepositService,
    RecordDepositDispositionCommand,
    ReverseDepositDispositionCommand,
)
from property_rental.financial_draft import (
    FinancialDraftAuthorizationError,
    FinancialDraftNotFoundError,
    FinancialDraftService,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease_deposit_forfeiture import (
    LeaseDepositForfeitureAuthorizationError,
    LeaseDepositForfeitureConflictError,
    LeaseDepositForfeitureInvalidError,
    LeaseDepositForfeitureKeyReused,
    LeaseDepositForfeitureNotFoundError,
    LeaseDepositForfeitureService,
    RecordLeaseDepositForfeitureCommand,
    RecordLeaseDepositReversalCommand,
    lease_deposit_reversal_draft_id,
)
from property_rental.reservation_deposit_draft import (
    RecordReservationDepositDraftCommand,
    ReservationDepositDecision,
    ReservationDepositDraftNotFoundError,
)
from test_deposit_migration import deposit_actor
from test_invoice_migration import financial_database_url
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_reservation_deposit_draft_migration import cancel_by_staff
from test_reservation_deposit_draft_migration import drafts as reservation_drafts
from test_reservation_deposit_draft_migration import person as reservation_person
from test_reservation_lifecycle_migration import active_reservation
from test_termination_deposit_migration import setup_deposits
from test_termination_deposit_migration import terminate as terminate_voluntary

RECORD = "app.record_lease_deposit_reversal_draft(uuid,uuid,uuid,uuid,uuid,text,text,text)"
CONFIRM = "app.confirm_lease_deposit_reversal_draft(uuid,uuid,uuid,uuid,text)"
SOURCE = "app.lease_deposit_reversal_source(uuid,uuid)"
READS = (
    "app.financial_draft_resource_by_capability(uuid,uuid,uuid,text[])",
    "app.list_financial_drafts_by_capability(uuid,uuid,text[],text,integer,"
    "timestamp with time zone,uuid)",
)


def staff(human: UUID, prop: UUID, *capabilities: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(human),
        frozenset(CapabilityGrant(value, frozenset({str(prop)})) for value in capabilities),
    )


def forfeitures() -> LeaseDepositForfeitureService:
    return LeaseDepositForfeitureService(financial_database_url())


def row(url: str, query: str, *parameters: object) -> Any:
    with psycopg.connect(url) as connection:
        return connection.execute(query, parameters).fetchone()


def held(url: str, deposit: UUID) -> int:
    return int(row(url, "SELECT app.deposit_held_value_at(%s,statement_timestamp())", deposit)[0])


def reversals(url: str, disposition: UUID) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(
            "SELECT id,actor_id,authorization_reference FROM app.deposit_disposition_reversals "
            "WHERE deposit_disposition_id=%s",
            (disposition,),
        ).fetchall()


def decisions(url: str, draft_id: UUID) -> int:
    return int(
        row(url, "SELECT count(*) FROM app.financial_draft_decisions WHERE draft_id=%s", draft_id)[
            0
        ]
    )


def forfeited_security(url: str) -> tuple[UUID, UUID, UUID, date, UUID, int]:
    """A voluntary early termination whose whole Security Deposit was forfeited by a draft."""
    human, prop, lease, security, _, day = setup_deposits(url)
    terminate_voluntary(url, human, prop, lease, day)
    amount = held(url, security)
    assert amount > 0
    disposition = uuid4()
    forfeit_through_draft(
        PostgresDepositService(financial_database_url(), prop, human),
        security,
        disposition_id=disposition,
    )
    assert held(url, security) == 0
    return human, prop, security, day, disposition, amount


def reversal(disposition: UUID, **changes: Any) -> RecordLeaseDepositReversalCommand:
    values: dict[str, Any] = {
        "idempotency_key": uuid4(),
        "disposition_id": disposition,
        "reversal_id": uuid4(),
        "reason": "Wrong ground recorded",
        "evidence_reference": "CASE-6B",
        **changes,
    }
    return RecordLeaseDepositReversalCommand(**values)


def test_forfeiture_reversal_is_a_draft_until_an_approver_confirms(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, security, _, disposition, amount = forfeited_security(url)
    command = reversal(disposition)
    for who in (
        staff(human, prop, "deposits.dispose"),
        staff(human, prop, "financial.approve"),
    ):
        with pytest.raises(LeaseDepositForfeitureAuthorizationError):
            forfeitures().record_reversal(prop, command, actor=who)
    # Owner answer to Q-2026-10-04-13 (Option A): Staff record the reversal under deposits.correct.
    preparer = staff(human, prop, "deposits.correct")
    recorded = forfeitures().record_reversal(prop, command, actor=preparer)
    assert forfeitures().record_reversal(prop, command, actor=preparer) == recorded
    draft_id = lease_deposit_reversal_draft_id(prop, human, command.idempotency_key)
    assert recorded["draft_id"] == str(draft_id)
    assert (recorded["kind"], recorded["prepare_capability"]) == (
        "DEPOSIT_FORFEITURE",
        "deposits.correct",
    )
    payload = cast(dict[str, object], recorded["payload"])
    assert (
        payload["variant"],
        payload["disposition_id"],
        payload["deposit_id"],
        payload["amount_usd_cents"],
    ) == ("LEASE_FORFEITURE_REVERSAL", str(disposition), str(security), amount)
    # A draft has no financial effect (BR-AUTH-010).
    assert held(url, security) == 0 and reversals(url, disposition) == []
    with pytest.raises(LeaseDepositForfeitureAuthorizationError):
        forfeitures().confirm_reversal(prop, disposition, draft_id, actor=preparer)
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.Error) as refused:
            connection.execute(
                "SELECT app.confirm_lease_deposit_reversal_draft(%s,%s,%s,%s,%s)",
                (prop, human, disposition, draft_id, "deposits.correct"),
            )
    assert refused.value.sqlstate == "42501"
    # Another person confirms, so the records show the approver, not the preparer (BR-DEP-019).
    second = setup_deposits(url)[0]
    assert second != human
    approver = staff(second, prop, "financial.approve")
    confirmed = forfeitures().confirm_reversal(prop, disposition, draft_id, actor=approver)
    assert forfeitures().confirm_reversal(prop, disposition, draft_id, actor=approver) == confirmed
    deposit = cast(dict[str, object], confirmed["deposit"])
    assert deposit["deposit_disposition_reversal_id"] == str(command.reversal_id)
    assert held(url, security) == amount
    assert reversals(url, disposition) == [(command.reversal_id, second, "deposits.correct")]
    assert row(
        url,
        "SELECT draft.prepared_by,decision.decision,decision.decided_by,"
        "decision.authorization_reference FROM app.financial_drafts draft "
        "JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id "
        "WHERE draft.id=%s",
        draft_id,
    ) == (human, "CONFIRMED", second, "financial.approve")
    assert row(
        url,
        "SELECT action,actor_id,authorization_reference,correlation_id "
        "FROM app.audit_events WHERE id=%s",
        command.reversal_id,
    ) == ("deposit.disposition.reversed", second, "deposits.correct", draft_id)
    with pytest.raises(LeaseDepositForfeitureInvalidError):
        forfeitures().record_reversal(prop, reversal(disposition), actor=preparer)
    # The Deposit is held again; a new forfeiture is a new draft.
    forfeit_through_draft(PostgresDepositService(financial_database_url(), prop, human), security)
    assert held(url, security) == 0


def test_reversal_draft_refusals_change_nothing(migrated_database_url: str) -> None:
    """One waiting draft, identity reuse, wrong Property or forfeiture, flows and staleness."""
    url = migrated_database_url
    human, prop, security, day, disposition, _ = forfeited_security(url)
    preparer = staff(human, prop, "deposits.correct")
    approver = staff(human, prop, "financial.approve")
    command = reversal(disposition)
    draft_id = UUID(str(forfeitures().record_reversal(prop, command, actor=preparer)["draft_id"]))
    with pytest.raises(LeaseDepositForfeitureConflictError):
        forfeitures().record_reversal(prop, reversal(disposition), actor=preparer)
    with pytest.raises(LeaseDepositForfeitureKeyReused):
        forfeitures().record_reversal(
            prop,
            reversal(
                disposition,
                idempotency_key=command.idempotency_key,
                reversal_id=command.reversal_id,
                reason="Changed reason",
            ),
            actor=preparer,
        )
    other_human, other_prop, _, _, other_disposition, _ = forfeited_security(url)
    other_preparer = staff(other_human, other_prop, "deposits.correct")
    # A reversal id held by a waiting draft, and one used by a recorded reversal only.
    with pytest.raises(LeaseDepositForfeitureKeyReused):
        forfeitures().record_reversal(
            other_prop,
            reversal(other_disposition, reversal_id=command.reversal_id),
            actor=other_preparer,
        )
    third_human, third_prop, _, _, third_disposition, _ = forfeited_security(url)
    recorded_reversal = uuid4()
    reverse_disposition_as_owner(
        PostgresDepositService(financial_database_url(), third_prop, third_human),
        ReverseDepositDispositionCommand(
            uuid4(), recorded_reversal, third_disposition, "Owner setup", "CASE-6B-SETUP"
        ),
        actor=deposit_actor(third_human, third_prop),
    )
    # Disposition ids are also audit and draft ids, so they cannot become reversal ids.
    for used in (recorded_reversal, third_disposition):
        with pytest.raises(LeaseDepositForfeitureKeyReused):
            forfeitures().record_reversal(
                other_prop,
                reversal(other_disposition, reversal_id=used),
                actor=other_preparer,
            )
    # The schema holds one Property, so any other Property id is unknown and refused first.
    unknown = uuid4()
    with pytest.raises(LeaseDepositForfeitureNotFoundError):
        forfeitures().record_reversal(
            unknown,
            reversal(disposition),
            actor=staff(human, unknown, "deposits.correct"),
        )
    with pytest.raises(LeaseDepositForfeitureNotFoundError):
        forfeitures().record_reversal(prop, reversal(uuid4()), actor=preparer)
    with pytest.raises(LeaseDepositForfeitureNotFoundError):
        forfeitures().confirm_reversal(prop, other_disposition, draft_id, actor=approver)
    # The forfeiture confirm cannot confirm a reversal draft.
    with pytest.raises(LeaseDepositForfeitureNotFoundError):
        forfeitures().confirm(prop, security, draft_id, actor=approver)
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.errors.InvalidParameterValue, match="input is invalid"):
            connection.execute(
                "SELECT app.record_lease_deposit_reversal_draft(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    other_prop,
                    other_human,
                    uuid4(),
                    other_disposition,
                    uuid4(),
                    "Wrong ground\n",
                    "CASE-6B",
                    "deposits.correct",
                ),
            )
    assert reversals(url, other_disposition) == []
    assert reversals(url, disposition) == [] and decisions(url, draft_id) == 0
    # A Deposit change after the draft makes it stale: refused, still pending, nothing reversed.
    PostgresDepositService(financial_database_url(), prop, human).adjust_required_amount(
        AdjustDepositRequiredAmountCommand(
            uuid4(),
            uuid4(),
            security,
            DepositAdjustmentType.INCREASE,
            1_000,
            day,
            "Approved correction after the draft",
        ),
        actor=deposit_actor(human, prop),
    )
    with pytest.raises(LeaseDepositForfeitureInvalidError):
        forfeitures().confirm_reversal(prop, disposition, draft_id, actor=approver)
    assert reversals(url, disposition) == [] and decisions(url, draft_id) == 0
    assert held(url, security) == 0


def drafts_service() -> FinancialDraftService:
    return FinancialDraftService(runtime_database_url(), financial_database_url())


def decision(url: str, draft_id: UUID) -> tuple[Any, ...] | None:
    found: tuple[Any, ...] | None = row(
        url,
        "SELECT decision,authorization_reference,decided_by FROM app.financial_draft_decisions "
        "WHERE draft_id=%s",
        draft_id,
    )
    return found


def test_reversal_draft_withdraw_reject_and_reads_follow_deposits_correct(
    migrated_database_url: str,
) -> None:
    """Owner answers to Q-2026-10-04-13 (Option A) and Q-2026-10-05-15."""
    url = migrated_database_url
    human, prop, _, _, disposition, _ = forfeited_security(url)
    second = setup_deposits(url)[0]
    preparer = staff(human, prop, "deposits.correct")
    approver = staff(second, prop, "financial.approve")
    reads = drafts_service()
    first = UUID(
        str(forfeitures().record_reversal(prop, reversal(disposition), actor=preparer)["draft_id"])
    )
    # Reads: deposits.correct sees reversal drafts; deposits.dispose alone does not.
    assert reads.get(prop, first, actor=preparer)["prepare_capability"] == "deposits.correct"
    assert {
        item["prepare_capability"]
        for item in cast(list[dict[str, object]], reads.list(prop, actor=preparer)["items"])
    } == {"deposits.correct"}
    with pytest.raises(FinancialDraftNotFoundError):
        reads.get(prop, first, actor=staff(human, prop, "deposits.dispose"))
    # Withdraw: only the preparer, only with the draft's own capability.
    with pytest.raises(FinancialDraftAuthorizationError):
        reads.withdraw(
            prop,
            first,
            "Not mine",
            prepare_capability="deposits.correct",
            actor=staff(second, prop, "deposits.correct"),
        )
    with pytest.raises(FinancialDraftAuthorizationError):
        reads.withdraw(
            prop,
            first,
            "Wrong capability",
            prepare_capability="deposits.dispose",
            actor=staff(human, prop, "deposits.correct", "deposits.dispose"),
        )
    assert decision(url, first) is None
    withdrawn = reads.withdraw(
        prop, first, "Recorded by mistake", prepare_capability="deposits.correct", actor=preparer
    )
    assert withdrawn["state"] == "WITHDRAWN"
    assert decision(url, first) == ("WITHDRAWN", "deposits.correct", human)
    with pytest.raises(LeaseDepositForfeitureConflictError):
        forfeitures().confirm_reversal(prop, disposition, first, actor=approver)
    # A new reversal draft may follow; an approver rejects it; a third may follow again.
    again = UUID(
        str(forfeitures().record_reversal(prop, reversal(disposition), actor=preparer)["draft_id"])
    )
    rejected = reads.reject(prop, again, "Evidence incomplete", actor=approver)
    assert rejected["state"] == "REJECTED"
    assert decision(url, again) == ("REJECTED", "financial.approve", second)
    with pytest.raises(LeaseDepositForfeitureConflictError):
        forfeitures().confirm_reversal(prop, disposition, again, actor=approver)
    forfeitures().record_reversal(prop, reversal(disposition), actor=preparer)
    assert reversals(url, disposition) == []


def test_cross_flow_confirms_refuse_each_others_drafts(migrated_database_url: str) -> None:
    url = migrated_database_url
    human, prop, _, _, disposition, _ = forfeited_security(url)
    reversal_draft = UUID(
        str(
            forfeitures().record_reversal(
                prop, reversal(disposition), actor=staff(human, prop, "deposits.correct")
            )["draft_id"]
        )
    )
    other_human, other_prop, lease, security, _, day = setup_deposits(url)
    terminate_voluntary(url, other_human, other_prop, lease, day)
    forfeiture_draft = UUID(
        str(
            forfeitures().record(
                other_prop,
                RecordLeaseDepositForfeitureCommand(uuid4(), security, uuid4(), "Left early"),
                actor=staff(other_human, other_prop, "deposits.dispose"),
            )["draft_id"]
        )
    )
    approver = staff(human, prop, "financial.approve")
    with pytest.raises(LeaseDepositForfeitureNotFoundError):
        forfeitures().confirm_reversal(prop, disposition, forfeiture_draft, actor=approver)
    with pytest.raises(LeaseDepositForfeitureNotFoundError):
        forfeitures().confirm(other_prop, security, reversal_draft, actor=approver)
    with psycopg.connect(url) as setup:
        actor_id, property_id, _, _, reservation_id = active_reservation(setup)
        setup.commit()
    cancel_by_staff(actor_id, property_id, reservation_id)
    with pytest.raises(ReservationDepositDraftNotFoundError):
        reservation_drafts().confirm(
            property_id,
            reservation_id,
            reversal_draft,
            actor=reservation_person(actor_id, property_id, "financial.approve"),
        )
    for draft_id in (reversal_draft, forfeiture_draft):
        assert decision(url, draft_id) is None
    assert reversals(url, disposition) == [] and held(url, security) > 0


def test_concurrent_reversal_drafts_for_one_forfeiture_leave_one_waiting(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, _, _, disposition, _ = forfeited_security(url)
    preparer = staff(human, prop, "deposits.correct")
    barrier = Barrier(2)

    def attempt(_: int) -> str:
        barrier.wait(timeout=5)
        try:
            forfeitures().record_reversal(prop, reversal(disposition), actor=preparer)
        except LeaseDepositForfeitureConflictError:
            return "conflict"
        return "recorded"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(attempt, range(2))) == ["conflict", "recorded"]
    assert row(
        url,
        "SELECT count(*) FROM app.financial_drafts WHERE payload->>'variant'="
        "'LEASE_FORFEITURE_REVERSAL' AND payload->>'disposition_id'=%s",
        str(disposition),
    ) == (1,)
    assert reversals(url, disposition) == []


def test_forfeiture_draft_refuses_a_disposition_id_already_used_elsewhere(
    migrated_database_url: str,
) -> None:
    """Moved from slice 6 round 3: recorded disposition only, and a Reservation draft."""
    url = migrated_database_url
    human, prop, lease, security, _, day = setup_deposits(url)
    terminate_voluntary(url, human, prop, lease, day)
    service = PostgresDepositService(financial_database_url(), prop, human)
    recorded = uuid4()
    record_disposition_as_owner(
        service,
        RecordDepositDispositionCommand(
            uuid4(),
            recorded,
            security,
            lease,
            1_000,
            day,
            "Owner setup of an earlier partial disposition",
            context=disposition_context(url, security),
        ),
        actor=deposit_actor(human, prop),
    )
    assert (
        row(
            url,
            "SELECT count(*) FROM app.financial_drafts "
            "WHERE %s IN (payload->>'disposition_id',payload->>'outcome_id')",
            str(recorded),
        )[0]
        == 0
    )
    preparer = staff(human, prop, "deposits.dispose")
    with pytest.raises(LeaseDepositForfeitureKeyReused):
        forfeitures().record(
            prop,
            RecordLeaseDepositForfeitureCommand(uuid4(), security, recorded, "Left early"),
            actor=preparer,
        )
    with psycopg.connect(url) as setup:
        actor_id, property_id, _, _, reservation_id = active_reservation(setup)
        setup.commit()
    cancel_by_staff(actor_id, property_id, reservation_id)
    outcome_id = uuid4()
    reservation_drafts().record(
        property_id,
        ReservationDepositDecision.DEPOSIT_FORFEITURE,
        RecordReservationDepositDraftCommand(
            uuid4(), reservation_id, outcome_id, "Customer withdrew before move-in"
        ),
        actor=reservation_person(
            actor_id, property_id, "reservations.read", "reservation_deposits.dispose"
        ),
    )
    with pytest.raises(LeaseDepositForfeitureKeyReused):
        forfeitures().record(
            prop,
            RecordLeaseDepositForfeitureCommand(uuid4(), security, outcome_id, "Left early"),
            actor=preparer,
        )
    assert (
        row(
            url,
            "SELECT count(*) FROM app.financial_drafts "
            "WHERE payload->>'variant'='LEASE_FORFEITURE' AND payload->>'deposit_id'=%s",
            str(security),
        )[0]
        == 0
    )


def test_draft_reads_follow_the_capability_each_draft_was_prepared_under(
    migrated_database_url: str,
) -> None:
    """Moved from slice 6 round 3: kind alone no longer decides who may read a draft."""
    url = migrated_database_url
    human, prop, lease, security, _, day = setup_deposits(url)
    terminate_voluntary(url, human, prop, lease, day)
    lease_draft = str(
        forfeitures().record(
            prop,
            RecordLeaseDepositForfeitureCommand(uuid4(), security, uuid4(), "Left early"),
            actor=staff(human, prop, "deposits.dispose"),
        )["draft_id"]
    )
    with psycopg.connect(url) as setup:
        actor_id, property_id, _, _, reservation_id = active_reservation(setup)
        setup.commit()
    assert property_id == prop
    cancel_by_staff(actor_id, property_id, reservation_id)
    reservation_draft = str(
        reservation_drafts().record(
            property_id,
            ReservationDepositDecision.DEPOSIT_FORFEITURE,
            RecordReservationDepositDraftCommand(
                uuid4(), reservation_id, uuid4(), "Customer withdrew before move-in"
            ),
            actor=reservation_person(
                actor_id, property_id, "reservations.read", "reservation_deposits.dispose"
            ),
        )["draft_id"]
    )
    reads = FinancialDraftService(runtime_database_url(), financial_database_url())
    lease_reader = staff(human, prop, "deposits.dispose")
    reservation_reader = staff(human, prop, "reservation_deposits.dispose")
    approver = staff(human, prop, "financial.approve")

    def listed(reader: AuthenticatedActor) -> list[dict[str, object]]:
        return cast(list[dict[str, object]], reads.list(prop, actor=reader)["items"])

    assert reads.get(prop, UUID(lease_draft), actor=lease_reader)["draft_id"] == lease_draft
    with pytest.raises(FinancialDraftNotFoundError):
        reads.get(prop, UUID(reservation_draft), actor=lease_reader)
    with pytest.raises(FinancialDraftNotFoundError):
        reads.get(prop, UUID(lease_draft), actor=reservation_reader)
    assert (
        reads.get(prop, UUID(reservation_draft), actor=reservation_reader)["draft_id"]
        == reservation_draft
    )
    for reader, capability, seen, hidden in (
        (lease_reader, "deposits.dispose", lease_draft, reservation_draft),
        (reservation_reader, "reservation_deposits.dispose", reservation_draft, lease_draft),
    ):
        items = listed(reader)
        assert {item["prepare_capability"] for item in items} == {capability}
        identities = {item["draft_id"] for item in items}
        assert seen in identities and hidden not in identities
    assert {lease_draft, reservation_draft} <= {item["draft_id"] for item in listed(approver)}


def test_reversal_and_read_functions_are_least_privilege(migrated_database_url: str) -> None:
    assert migrated_database_url
    expected = {
        "prm_financial": {RECORD, CONFIRM},
        "prm_runtime": set(READS),
        "prm_bootstrap": set(),
        "public": set(),
    }
    with psycopg.connect(runtime_database_url()) as connection:
        for role, allowed in expected.items():
            for function in (RECORD, CONFIRM, SOURCE, *READS):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (function in allowed,), (role, function)


def test_lease_deposit_reversal_draft_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261019_84")
    assert revision is not None and revision.down_revision == "20261018_83"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
