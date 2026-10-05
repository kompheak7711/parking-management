"""V1-056 sub-slice 8r: Deposit receipt reversals are drafts confirmed by financial.approve."""

from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from deposit_receipt_reversal_test_support import approver
from lease_deposit_forfeiture_test_support import owner_database_url
from property_rental.deposit import (
    AdjustDepositRequiredAmountCommand,
    DepositAdjustmentType,
    DepositReceiptReversalDraftRequired,
    ReverseDepositReceiptCommand,
)
from property_rental.deposit_receipt_reversal import (
    DepositReceiptReversalAuthorizationError,
    DepositReceiptReversalConflictError,
    DepositReceiptReversalInvalidError,
    DepositReceiptReversalKeyReused,
    DepositReceiptReversalNotFoundError,
    DepositReceiptReversalService,
    RecordDepositReceiptReversalCommand,
)
from property_rental.financial_draft import FinancialDraftService
from property_rental.lease_deposit_forfeiture import (
    LeaseDepositForfeitureNotFoundError,
    LeaseDepositForfeitureService,
)
from property_rental.payment_allocation import (
    AllocationUnavailableError,
    ReversePaymentCommand,
)
from property_rental.reservation_deposit_draft import (
    RecordReservationDepositDraftCommand,
    ReservationDepositDecision,
)
from test_invoice_migration import financial_database_url, runtime_database_url
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import service as allocations
from test_payment_reversal_context_migration import deposit_source
from test_reservation_deposit_draft_migration import cancel_by_staff, drafts, person
from test_reservation_lifecycle_migration import active_reservation
from test_termination_deposit_migration import setup_deposits

ONE_CALL = "app.reverse_deposit_receipt_v2(uuid,uuid,uuid,text,uuid,uuid,text,text)"
RECORD = "app.record_deposit_receipt_reversal_draft(uuid,uuid,uuid,uuid,uuid,text,text)"
CONFIRM = "app.confirm_deposit_receipt_reversal_draft(uuid,uuid,uuid,uuid,text)"
SOURCE = "app.deposit_receipt_reversal_source(uuid,uuid)"
EARLIER = "app.reverse_deposit_receipt(uuid,uuid,uuid,text,uuid,uuid,text,text)"
GUARD = "app.validate_deposit_receipt_reversal()"


def one(url: str, sql: str, *parameters: object) -> tuple[Any, ...]:
    with psycopg.connect(url) as connection:
        found = connection.execute(sql, parameters).fetchone()
    assert found is not None
    return found


def held(url: str, deposit: UUID) -> int:
    return int(one(url, "SELECT app.deposit_held_value_at(%s,'infinity')", deposit)[0])


def available(url: str, payment: UUID) -> int:
    return int(one(url, "SELECT app.payment_available_value(%s)", payment)[0])


def decisions(url: str, draft: UUID) -> int:
    return int(
        one(url, "SELECT count(*) FROM app.financial_draft_decisions WHERE draft_id=%s", draft)[0]
    )


def reversals() -> DepositReceiptReversalService:
    return DepositReceiptReversalService(financial_database_url())


def record(
    prop: UUID,
    human: UUID,
    receipt: UUID,
    *,
    key: UUID | None = None,
    reversal: UUID | None = None,
    reason: str = "Transfer returned by the bank",
    capabilities: tuple[str, ...] = ("deposits.correct",),
) -> dict[str, object]:
    return reversals().record(
        prop,
        RecordDepositReceiptReversalCommand(key or uuid4(), receipt, reversal or uuid4(), reason),
        actor=approver(human, prop, *capabilities),
    )


def confirm(prop: UUID, human: UUID, receipt: UUID, draft: object) -> dict[str, object]:
    return reversals().confirm(
        prop, receipt, UUID(str(draft)), actor=approver(human, prop, "financial.approve")
    )


def withdraw(prop: UUID, human: UUID, draft: object) -> None:
    FinancialDraftService(runtime_database_url(), financial_database_url()).withdraw(
        prop,
        UUID(str(draft)),
        "Recorded against the wrong receipt",
        prepare_capability="deposits.correct",
        actor=approver(human, prop, "deposits.correct"),
    )


def test_a_receipt_reversal_is_a_draft_until_an_approver_confirms(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    service, _staff, _lease, deposit, payment, receipts = deposit_source(url)
    prop, human = service.property_id, service.actor_id
    assert (held(url, deposit), available(url, payment)) == (20_000, 10_000)
    with pytest.raises(DepositReceiptReversalDraftRequired):
        service.reverse_receipt(
            ReverseDepositReceiptCommand(uuid4(), uuid4(), receipts[0], "Returned transfer"),
            actor=approver(human, prop, "deposits.correct"),
        )
    recorded = record(prop, human, receipts[0])
    draft = UUID(str(recorded["draft_id"]))
    payload = cast(dict[str, object], recorded["payload"])
    assert (recorded["kind"], recorded["prepare_capability"]) == (
        "DEPOSIT_FORFEITURE",
        "deposits.correct",
    )
    assert (payload["variant"], payload["receipt_id"], payload["deposit_id"]) == (
        "DEPOSIT_RECEIPT_REVERSAL",
        str(receipts[0]),
        str(deposit),
    )
    # No financial effect before confirmation: the Payment's value is not freed.
    assert (held(url, deposit), available(url, payment)) == (20_000, 10_000)
    with pytest.raises(DepositReceiptReversalAuthorizationError):
        reversals().confirm(
            prop, receipts[0], draft, actor=approver(human, prop, "deposits.correct")
        )
    assert decisions(url, draft) == 0
    # The database also refuses the wrong authorization reference for each step.
    with psycopg.connect(financial_database_url()) as connection:
        for sql, parameters in (
            (
                "SELECT app.confirm_deposit_receipt_reversal_draft(%s,%s,%s,%s,%s)",
                (prop, human, receipts[0], draft, "deposits.correct"),
            ),
            (
                "SELECT app.record_deposit_receipt_reversal_draft(%s,%s,%s,%s,%s,%s,%s)",
                (prop, human, uuid4(), receipts[1], uuid4(), "Returned", "financial.approve"),
            ),
        ):
            with pytest.raises(psycopg.Error) as refused, connection.transaction():
                connection.execute(sql, parameters)
            assert refused.value.sqlstate == "42501"
    assert decisions(url, draft) == 0
    # Another person confirms, so the records show the approver, not the preparer.
    second = setup_deposits(url)[0]
    assert second != human
    confirmed = confirm(prop, second, receipts[0], draft)
    assert (held(url, deposit), available(url, payment)) == (10_000, 20_000)
    assert confirm(prop, second, receipts[0], draft) == confirmed
    assert one(
        url,
        "SELECT id::text,actor_id,authorization_reference FROM app.deposit_receipt_reversals "
        "WHERE deposit_receipt_id=%s",
        receipts[0],
    ) == (payload["reversal_id"], second, "deposits.correct")
    assert one(
        url,
        "SELECT draft.prepared_by,decision.decision,decision.decided_by,"
        "decision.authorization_reference FROM app.financial_drafts draft "
        "JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id "
        "WHERE draft.id=%s",
        draft,
    ) == (human, "CONFIRMED", second, "financial.approve")
    assert one(
        url,
        "SELECT count(*),min(action),min(actor_id::text),min(correlation_id::text) "
        "FROM app.audit_events WHERE id=%s",
        UUID(str(payload["reversal_id"])),
    ) == (1, "deposit.receipt.reversed", str(second), str(draft))


def test_a_returned_transfer_is_reversed_after_the_receipt_reversal_draft(
    migrated_database_url: str,
) -> None:
    """A rejected draft changes nothing; the Payment is reversed only after the confirmation."""
    url = migrated_database_url
    service, _staff, _lease, deposit, payment, receipts = deposit_source(url)
    prop, human = service.property_id, service.actor_id
    rejected = record(prop, human, receipts[0])
    FinancialDraftService(runtime_database_url(), financial_database_url()).reject(
        prop,
        UUID(str(rejected["draft_id"])),
        "Bank statement shows the transfer arrived",
        actor=approver(human, prop, "financial.approve"),
    )
    assert decisions(url, UUID(str(rejected["draft_id"]))) == 1
    assert (held(url, deposit), available(url, payment)) == (20_000, 10_000)
    recorded = record(prop, human, receipts[0])
    returned = ReversePaymentCommand(uuid4(), "Transfer returned by the bank")
    # While the receipt reversal is only a draft, the Payment still funds the Deposit.
    with pytest.raises(AllocationUnavailableError):
        allocations().reverse_payment(prop, payment, returned, actor=allocation_actor(human, prop))
    assert one(url, "SELECT status FROM app.payments WHERE id=%s", payment) == ("RECEIVED",)
    confirm(prop, human, receipts[0], recorded["draft_id"])
    reversed_payment = allocations().reverse_payment(
        prop,
        payment,
        ReversePaymentCommand(uuid4(), "Transfer returned by the bank"),
        actor=allocation_actor(human, prop),
    )
    assert reversed_payment["status"] == "REVERSED"
    assert (held(url, deposit), available(url, payment)) == (10_000, 0)


def test_a_receipt_reversal_waits_for_any_pending_draft_of_its_deposit(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    service, _staff, _lease, deposit, _payment, receipts = deposit_source(url)
    prop, human = service.property_id, service.actor_id
    first = record(prop, human, receipts[0])
    with pytest.raises(DepositReceiptReversalConflictError):
        record(prop, human, receipts[1])
    # The receipt reversal guard finds the pending draft by its deposit_id.
    with psycopg.connect(owner_database_url(financial_database_url())) as owner:
        with pytest.raises(psycopg.Error) as refused:
            owner.execute(
                f"SELECT {ONE_CALL.split('(')[0]}(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    prop,
                    human,
                    uuid4(),
                    "a" * 64,
                    uuid4(),
                    receipts[1],
                    "Returned",
                    "deposits.correct",
                ),
            )
    assert refused.value.sqlstate == "55000"
    withdraw(prop, human, first["draft_id"])
    second = record(prop, human, receipts[1])
    confirm(prop, human, receipts[1], second["draft_id"])
    assert held(url, deposit) == 10_000


def test_a_reservation_deposit_receipt_reversal_is_a_draft_too(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    with psycopg.connect(url) as setup:
        human, prop, _, _, reservation = active_reservation(setup)
        setup.commit()
    receipt, deposit = one(
        url,
        "SELECT receipt.id,receipt.deposit_id FROM app.deposit_receipts receipt "
        "JOIN app.deposits deposit ON deposit.id=receipt.deposit_id "
        "WHERE deposit.reservation_id=%s",
        reservation,
    )
    amount = held(url, deposit)
    assert amount > 0
    cancel_by_staff(human, prop, reservation)
    staff = person(human, prop, "reservation_deposits.dispose")

    def forfeiture_draft() -> UUID:
        found = drafts().record(
            prop,
            ReservationDepositDecision.DEPOSIT_FORFEITURE,
            RecordReservationDepositDraftCommand(uuid4(), reservation, uuid4(), "Forfeit"),
            actor=staff,
        )
        return UUID(str(found["draft_id"]))

    def withdraw_forfeiture(draft: UUID) -> None:
        drafts().withdraw(
            prop,
            reservation,
            ReservationDepositDecision.DEPOSIT_FORFEITURE,
            draft,
            "Receipt must be corrected first",
            actor=staff,
        )

    # A pending Reservation draft refuses a new receipt reversal draft ...
    pending = forfeiture_draft()
    with pytest.raises(DepositReceiptReversalConflictError):
        record(prop, human, receipt)
    withdraw_forfeiture(pending)
    # ... and a Reservation draft recorded later refuses its confirmation; it stays pending.
    recorded = record(prop, human, receipt)
    pending = forfeiture_draft()
    # This confirm does not confirm another kind of Deposit draft.
    with pytest.raises(DepositReceiptReversalNotFoundError):
        confirm(prop, human, receipt, pending)
    with pytest.raises(DepositReceiptReversalConflictError):
        confirm(prop, human, receipt, recorded["draft_id"])
    assert decisions(url, UUID(str(recorded["draft_id"]))) == 0
    assert held(url, deposit) == amount
    withdraw_forfeiture(pending)
    confirm(prop, human, receipt, recorded["draft_id"])
    assert held(url, deposit) == 0


def test_receipt_reversal_draft_refusals_change_nothing(migrated_database_url: str) -> None:
    url = migrated_database_url
    service, _staff, _lease, deposit, _payment, receipts = deposit_source(url)
    prop, human = service.property_id, service.actor_id
    key, reversal = uuid4(), uuid4()
    first = record(prop, human, receipts[0], key=key, reversal=reversal)
    assert record(prop, human, receipts[0], key=key, reversal=reversal) == first
    with pytest.raises(DepositReceiptReversalKeyReused):
        record(prop, human, receipts[0], key=key, reversal=reversal, reason="Another reason")
    with pytest.raises(DepositReceiptReversalNotFoundError):
        record(prop, human, uuid4())
    # The forfeiture reversal confirm cannot confirm a receipt reversal draft.
    with pytest.raises(LeaseDepositForfeitureNotFoundError):
        LeaseDepositForfeitureService(financial_database_url()).confirm_reversal(
            prop,
            receipts[0],
            UUID(str(first["draft_id"])),
            actor=approver(human, prop, "financial.approve"),
        )
    # A Deposit that changed after the draft was recorded makes the draft stale.
    service.adjust_required_amount(
        AdjustDepositRequiredAmountCommand(
            uuid4(),
            uuid4(),
            deposit,
            DepositAdjustmentType.INCREASE,
            1_000,
            one(url, "SELECT timezone('Asia/Phnom_Penh',clock_timestamp())::date")[0],
            "Later signed-term correction",
        ),
        actor=approver(human, prop, "deposits.manage"),
    )
    with pytest.raises(DepositReceiptReversalInvalidError):
        confirm(prop, human, receipts[0], first["draft_id"])
    assert decisions(url, UUID(str(first["draft_id"]))) == 0
    assert held(url, deposit) == 20_000
    # A reversal id is used once, also by a withdrawn draft.
    withdraw(prop, human, first["draft_id"])
    with pytest.raises(DepositReceiptReversalKeyReused):
        record(prop, human, receipts[0], reversal=reversal)
    # An already reversed receipt is refused.
    second = record(prop, human, receipts[1])
    confirm(prop, human, receipts[1], second["draft_id"])
    with pytest.raises(DepositReceiptReversalInvalidError):
        record(prop, human, receipts[1])
    assert held(url, deposit) == 10_000


def test_receipt_reversal_grants_are_least_privilege(migrated_database_url: str) -> None:
    with psycopg.connect(financial_database_url()) as financial:
        with pytest.raises(psycopg.Error) as denied:
            financial.execute(
                f"SELECT {ONE_CALL.split('(')[0]}(%s,%s,%s,%s,%s,%s,%s,%s)",
                (uuid4(), uuid4(), uuid4(), "a" * 64, uuid4(), uuid4(), "Returned", "x"),
            )
    assert denied.value.sqlstate == "42501"
    with psycopg.connect(migrated_database_url) as connection:
        for table_privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            for role in ("public", "prm_runtime", "prm_financial", "prm_bootstrap"):
                assert connection.execute(
                    "SELECT has_table_privilege(%s,'app.deposit_receipt_reversals',%s)",
                    (role, table_privilege),
                ).fetchone() == (False,), (role, table_privilege)
        # The in-place patch keeps the guard's owner.
        assert connection.execute(
            "SELECT (SELECT proowner FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure)"
            "=(SELECT proowner FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure)",
            (GUARD, ONE_CALL),
        ).fetchone() == (True,)
        for function in (ONE_CALL, EARLIER, GUARD, RECORD, CONFIRM, SOURCE):
            definer, config = connection.execute(
                "SELECT prosecdef,proconfig FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure",
                (function,),
            ).fetchone() or (None, None)
            assert definer is True and "search_path=pg_catalog" in (config or []), function
            for role in ("public", "prm_runtime", "prm_financial", "prm_bootstrap"):
                allowed = connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone()
                expected = role == "prm_financial" and function in (RECORD, CONFIRM)
                assert allowed == (expected,), (role, function)


def test_receipt_reversal_draft_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261022_87")
    assert revision is not None and revision.down_revision == "20261021_86"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
