"""V1-056 sub-slice 8a-1: the Final Settlement record and the Deposit application record."""

from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from deposit_disposition_test_support import terminate_for_disposition
from payment_test_support import seed_payment
from property_rental.deposit import PostgresDepositService
from property_rental.final_settlement import (
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementNotFoundError,
    FinalSettlementService,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.invoice import (
    CreateInvoiceDraftCommand,
    IssueInvoiceCommand,
    PostgresInvoiceService,
    RecordOneTimeChargeCommand,
)
from property_rental.late_payment import (
    CorrectionKind,
    CorrectLatePaymentChargeCommand,
    DecisionOutcome,
    FinalizeLatePaymentDecisionCommand,
    LatePaymentApplicationReversalRequired,
    LatePaymentConflictError,
)
from property_rental.lease_enforcement import NonpaymentEventKind
from property_rental.lease_termination import TerminationBasis
from property_rental.move_out_inspection import InspectionFinding, RecordMoveOutInspection
from property_rental.payment_allocation import PostAllocationsCommand
from property_rental.termination_invoice import PostgresTerminationInvoiceReadService
from test_deposit_migration import create_pet, deposit_actor, seed_historical_deposit_receipt
from test_invoice_migration import (
    create_recurring_rent_invoice,
    financial_database_url,
    invoice_api_actor,
    register_billing_service_principal,
    runtime_database_url,
    setup_signed_lease,
)
from test_late_payment_migration import late_payment_actor
from test_late_payment_migration import service as late_payments
from test_lease_deposit_forfeiture_migration import terminate_on
from test_lease_migration import create_draft, setup_sources, sign_lease
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_out_inspection_migration import actor as inspection_actor
from test_move_out_inspection_migration import flow as inspection_flow
from test_one_time_charges_migration import damage, draft_and_issue, invoices
from test_one_time_charges_migration import staff as invoice_staff
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import service as allocations
from test_rent_nonpayment_recurring_only_migration import enforcement, open_case
from test_rent_nonpayment_recurring_only_migration import record as record_nonpayment_event
from test_termination_deposit_migration import setup_deposits, terminate
from test_unpaid_initial_termination_migration import signed_with_initial
from test_unpaid_initial_termination_migration import terminate as terminate_unpaid

REASON = "Applied at Final Settlement"


def one(url: str, sql: str, *parameters: object) -> tuple[Any, ...]:
    with psycopg.connect(url) as connection:
        found = connection.execute(sql, parameters).fetchone()
    assert found is not None
    return found


def today(url: str) -> date:
    return cast(date, one(url, "SELECT timezone('Asia/Phnom_Penh',clock_timestamp())::date")[0])


def preparer(human: UUID, prop: UUID, *capabilities: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(human),
        frozenset(
            CapabilityGrant(capability, frozenset({str(prop)}))
            for capability in capabilities or ("final_settlements.prepare",)
        ),
    )


def settlements() -> FinalSettlementService:
    return FinalSettlementService(financial_database_url())


def start(prop: UUID, human: UUID, lease: UUID) -> UUID:
    return UUID(str(settlements().start(prop, lease, actor=preparer(human, prop))["id"]))


def apply(
    url: str,
    prop: UUID,
    human: UUID,
    settlement: UUID,
    deposit: UUID,
    stage: str,
    kind: str,
    target: UUID,
    amount: int,
    order: int,
) -> dict[str, object]:
    """The internal writer, as the Settlement confirm (8e) will call it; no role may call it."""
    with psycopg.connect(url) as connection:
        found = connection.execute(
            "SELECT app.post_deposit_application(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (prop, human, settlement, uuid4(), deposit, stage, kind, target, amount, order, REASON),
        ).fetchone()
    assert found is not None and isinstance(found[0], dict)
    return cast(dict[str, object], found[0])


def refused(url: str, *arguments: object) -> str | None:
    with pytest.raises(psycopg.Error) as failure:
        apply(url, *arguments)  # type: ignore[arg-type]
    return failure.value.sqlstate


def held(url: str, deposit: UUID) -> int:
    return int(one(url, "SELECT app.deposit_held_value_at(%s,'infinity')", deposit)[0])


def outstanding(url: str, line: UUID) -> int:
    return int(one(url, "SELECT app.invoice_line_outstanding(%s)", line)[0])


def charge_remaining(url: str, charge: UUID) -> int:
    return int(
        one(
            url,
            "SELECT remaining_balance_usd_cents FROM app.late_payment_charge_financial_position "
            "WHERE late_payment_charge_id=%s",
            charge,
        )[0]
    )


def invoice_state(url: str, invoice: UUID) -> tuple[Any, ...]:
    return one(url, "SELECT status,version FROM app.invoices WHERE id=%s", invoice)


def line_of(url: str, invoice: object) -> UUID:
    return UUID(
        str(one(url, "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", UUID(str(invoice)))[0])
    )


def pet_deposit(url: str, human: UUID, prop: UUID, lease: UUID, day: date) -> UUID:
    """Approve a pet, create the 20,000-cent Pet Deposit and receive it in full."""
    approval = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.lease_pet_approvals(id,lease_id,approved_date,"
            "deposit_required_by_signed_terms,pet_description,approved_at,approved_by) "
            "VALUES (%s,%s,%s,true,'Synthetic approved pet',clock_timestamp(),%s)",
            (approval, lease, day, human),
        )
    service = PostgresDepositService(financial_database_url(), prop, human)
    pet, _ = create_pet(service, deposit_actor(human, prop), lease, approval, day)
    seed_historical_deposit_receipt(url, deposit_id=pet, actor_id=human, amount_usd_cents=20_000)
    return pet


def overdue_lease_with_pet_damage(url: str) -> dict[str, UUID]:
    """A Lease with an overdue Rent Invoice, its Late-payment Charge, a received Pet Deposit and
    two issued Damage charges (one pet-related), terminated with no forfeiture ground."""
    now = today(url)
    period = (now.replace(day=1) - timedelta(days=62)).replace(day=1)
    with psycopg.connect(url) as connection:
        human, prop, customer, lease = setup_signed_lease(
            connection,
            start_date=date(now.year - 1, 1, 1),
            end_date=date(now.year + 1, 12, 31),
        )
        invoice, rent_line = create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=customer,
            lease_id=lease,
            period_start=period,
        )
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    flow = late_payments()
    review = flow.review(invoice, actor=late_payment_actor(human, prop))
    amount = cast(dict[str, int], review["calculated_default_amount"])["minor_units"]
    flow.finalize_decision(
        prop,
        invoice,
        FinalizeLatePaymentDecisionCommand(
            uuid4(), DecisionOutcome.CONFIRMED_DEFAULT, amount, "Approved default charge"
        ),
        actor=late_payment_actor(human, prop),
    )
    charge = UUID(
        str(
            one(url, "SELECT id FROM app.late_payment_charges WHERE source_invoice_id=%s", invoice)[
                0
            ]
        )
    )
    pet = pet_deposit(url, human, prop, lease, now)
    version = one(url, "SELECT version FROM app.leases WHERE id=%s", lease)
    pet_finding, other_finding = uuid4(), uuid4()
    inspection_flow().record(
        prop,
        lease,
        RecordMoveOutInspection(
            uuid4(),
            uuid4(),
            int(version[0]),
            now,
            "Recorded inspection condition",
            "Approved inspection",
            "Evidence-801",
            "Record actual inspection",
            (
                InspectionFinding(pet_finding, "Scratched door by the pet", True),
                InspectionFinding(other_finding, "Broken window latch", False),
            ),
        ),
        actor=inspection_actor(human, prop),
        request_id="settlement-inspection",
    )
    lines = {}
    for name, finding in (("pet_line", pet_finding), ("other_line", other_finding)):
        command = damage(customer, lease, finding)
        invoices().record_one_time_charge(prop, command, actor=invoice_staff(human, prop))
        issued = draft_and_issue(prop, command.charge_id, invoice_staff(human, prop))
        lines[name] = line_of(url, issued["id"])
        lines[name.replace("line", "invoice")] = UUID(str(issued["id"]))
    terminate(url, human, prop, lease, now, voluntary=False)
    return {
        "human": human,
        "prop": prop,
        "customer": customer,
        "lease": lease,
        "invoice": invoice,
        "rent_line": rent_line,
        "charge": charge,
        "pet": pet,
        **lines,
    }


def lease_with_charge(url: str) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID, UUID, date]:
    """setup_deposits (Security received, Pet Deposit created) plus an issued one-time charge."""
    human, prop, lease, security, pet, day = setup_deposits(url)
    customer = UUID(str(one(url, "SELECT primary_tenant_id FROM app.leases WHERE id=%s", lease)[0]))
    command = RecordOneTimeChargeCommand(
        uuid4(),
        "MISCELLANEOUS_CHARGES",
        customer,
        lease,
        None,
        "Replacement key card",
        1_500,
        "Customer lost key card",
        "Front desk log 801",
    )
    invoices().record_one_time_charge(prop, command, actor=invoice_staff(human, prop))
    issued = draft_and_issue(prop, command.charge_id, invoice_staff(human, prop))
    return (
        human,
        prop,
        lease,
        security,
        pet,
        UUID(str(issued["id"])),
        line_of(url, issued["id"]),
        day,
    )


def test_a_settlement_opens_once_for_a_terminated_lease_only(migrated_database_url: str) -> None:
    url = migrated_database_url
    human, prop, lease, *_rest, day = lease_with_charge(url)
    with pytest.raises(FinalSettlementConflictError):
        start(prop, human, lease)
    with pytest.raises(FinalSettlementAuthorizationError):
        settlements().start(prop, lease, actor=preparer(human, prop, "financial.approve"))
    with pytest.raises(FinalSettlementNotFoundError):
        settlements().start(prop, uuid4(), actor=preparer(human, prop))
    terminate(url, human, prop, lease, day, voluntary=False)
    opened = settlements().start(prop, lease, actor=preparer(human, prop))
    again = settlements().start(prop, lease, actor=preparer(human, prop))
    assert (opened["created"], again["created"]) == (True, False)
    assert {key: value for key, value in again.items() if key != "created"} == {
        key: value for key, value in opened.items() if key != "created"
    }
    assert (opened["lease_id"], opened["closed"], opened["actual_termination_date"]) == (
        str(lease),
        False,
        day.isoformat(),
    )
    settlement = UUID(str(opened["id"]))
    assert one(
        url,
        "SELECT count(*),min(action),min(authorization_reference) FROM app.audit_events "
        "WHERE entity_type='final_settlement' AND entity_id=%s",
        settlement,
    ) == (1, "final_settlement.started", "final_settlements.prepare")
    with psycopg.connect(url) as connection:
        with pytest.raises(psycopg.Error) as changed:
            connection.execute(
                "UPDATE app.final_settlements SET started_at=started_at+interval '1 second' "
                "WHERE id=%s",
                (settlement,),
            )
    assert changed.value.sqlstate == "23514"
    with psycopg.connect(url) as connection:
        with pytest.raises(psycopg.Error) as deleted:
            connection.execute("DELETE FROM app.final_settlements WHERE id=%s", (settlement,))
    assert deleted.value.sqlstate == "55000"


def test_a_closed_settlement_is_never_changed_again(migrated_database_url: str) -> None:
    """The single closure transition (written by the confirm in 8e) happens once."""
    url = migrated_database_url
    human, prop, lease, security, _pet, _invoice, line, day = lease_with_charge(url)
    terminate(url, human, prop, lease, day, voluntary=False)
    settlement = start(prop, human, lease)
    close = (
        "UPDATE app.final_settlements SET closed_at=clock_timestamp(),closed_by=%s,"
        "source_snapshot='{}'::jsonb,closing_balance_due_usd_cents=%s WHERE id=%s"
    )
    # A closure that also changes an identity or snapshot column is refused (BR-SETTLE-012).
    for change in (
        "started_at=started_at-interval '1 second'",
        "actual_termination_date_snapshot=actual_termination_date_snapshot-1",
        "move_out_date_snapshot=DATE '2000-01-01'",
    ):
        with psycopg.connect(url) as connection:
            with pytest.raises(psycopg.Error) as changed:
                connection.execute(
                    close.replace(" WHERE id", f",{change} WHERE id"), (human, 0, settlement)
                )
        assert changed.value.sqlstate == "23514", change
    assert settlements().start(prop, lease, actor=preparer(human, prop))["closed"] is False
    with psycopg.connect(url) as connection:
        connection.execute(close, (human, 0, settlement))
    for amount in (0, 1):
        with psycopg.connect(url) as connection:
            with pytest.raises(psycopg.Error) as reopened:
                connection.execute(close, (human, amount, settlement))
        assert reopened.value.sqlstate == "55000"
    assert settlements().start(prop, lease, actor=preparer(human, prop))["closed"] is True
    # A Deposit and a line that would otherwise be accepted: only the closure refuses it.
    assert (
        refused(
            url, prop, human, settlement, security, "SECURITY_EXPLICIT", "INVOICE_LINE", line, 1, 1
        )
        == "55000"
    )
    assert held(url, security) > 0 and outstanding(url, line) == 1_500


def test_a_deposit_application_counts_as_paid_everywhere(migrated_database_url: str) -> None:
    url = migrated_database_url
    f = overdue_lease_with_pet_damage(url)
    prop, human = f["prop"], f["human"]
    settlement = start(prop, human, f["lease"])
    pet_line = f["pet_line"]
    damage_due = outstanding(url, pet_line)
    rent_due = outstanding(url, f["rent_line"])
    charge_due = charge_remaining(url, f["charge"])
    assert damage_due > 0 and rent_due > 0 and charge_due > 0
    status, version = invoice_state(url, f["pet_invoice"])
    assert status == "UNPAID"
    snapshot_before = one(url, "SELECT app.deposit_snapshot(%s)", f["pet"])[0]
    assert snapshot_before["held_refundable_usd_cents"] == 20_000

    apply(
        url,
        prop,
        human,
        settlement,
        f["pet"],
        "PET_RELATED_FIRST",
        "INVOICE_LINE",
        pet_line,
        damage_due,
        1,
    )
    assert outstanding(url, pet_line) == 0
    assert invoice_state(url, f["pet_invoice"]) == ("PAID", version + 1)
    resource = PostgresInvoiceService(runtime_database_url(), financial_database_url()).get(
        f["pet_invoice"], actor=invoice_api_actor(human, prop)
    )
    assert (resource["status"], cast(dict[str, int], resource["outstanding_balance"])) == (
        "PAID",
        {"currency": "USD", "minor_units": 0},
    )
    # The application is the target's latest event, so later events must come after it.
    assert one(
        url,
        "SELECT app.allocation_target_latest_at('INVOICE',%s)=max(occurred_at) "
        "FROM app.deposit_applications WHERE invoice_line_id=%s",
        f["pet_invoice"],
        pet_line,
    ) == (True,)
    assert held(url, f["pet"]) == 20_000 - damage_due
    assert (
        one(url, "SELECT app.deposit_snapshot(%s)", f["pet"])[0]["held_refundable_usd_cents"]
        == 20_000 - damage_due
    )

    # Leave Pet Deposit for the Rent line too: pay only part of the Late-payment Charge.
    remainder = min(charge_due, 1_000)
    apply(
        url,
        prop,
        human,
        settlement,
        f["pet"],
        "PET_REMAINDER_EXPLICIT",
        "LATE_PAYMENT_CHARGE",
        f["charge"],
        remainder,
        2,
    )
    assert charge_remaining(url, f["charge"]) == charge_due - remainder
    summary = one(url, "SELECT app.late_payment_charge_application_summary(%s)", f["charge"])[0]
    assert (summary["deposit_total_usd_cents"], summary["active_total_usd_cents"]) == (
        remainder,
        remainder,
    )
    assert [item["kind"] for item in summary["items"]] == ["DEPOSIT_APPLICATION"]

    rest = min(rent_due, held(url, f["pet"]))
    apply(
        url,
        prop,
        human,
        settlement,
        f["pet"],
        "PET_REMAINDER_EXPLICIT",
        "INVOICE_LINE",
        f["rent_line"],
        rest,
        3,
    )
    assert outstanding(url, f["rent_line"]) == rent_due - rest
    assert invoice_state(url, f["invoice"])[0] == ("PAID" if rest == rent_due else "PARTIALLY_PAID")
    assert held(url, f["pet"]) == 20_000 - damage_due - remainder - rest

    readiness = PostgresTerminationInvoiceReadService(runtime_database_url(), prop).page(
        f["lease"], actor=preparer(human, prop, "leases.read", "invoices.read")
    )
    by_line = {line.invoice_line_id: line for line in readiness.items}
    assert (
        by_line[pet_line].deposit_applied_usd_cents,
        by_line[pet_line].outstanding_usd_cents,
    ) == (
        damage_due,
        0,
    )
    assert by_line[f["rent_line"]].deposit_applied_usd_cents == rest
    assert one(
        url,
        "SELECT count(*),min(authorization_reference),min(correlation_id::text) "
        "FROM app.audit_events "
        "WHERE action='deposit_application.recorded' AND correlation_id=%s",
        settlement,
    ) == (3, "financial.approve", str(settlement))


def test_deposit_application_refusals_change_nothing(migrated_database_url: str) -> None:
    url = migrated_database_url
    f = overdue_lease_with_pet_damage(url)
    prop, human = f["prop"], f["human"]
    settlement = start(prop, human, f["lease"])
    other = overdue_lease_with_pet_damage(url)
    other_settlement = start(other["prop"], other["human"], other["lease"])
    base = (url, prop, human, settlement, f["pet"])
    # The first Pet stage pays only pet-related Damage lines, and only Invoice lines.
    assert refused(*base, "PET_RELATED_FIRST", "INVOICE_LINE", f["other_line"], 1, 1) == "23514"
    assert refused(*base, "PET_RELATED_FIRST", "INVOICE_LINE", f["rent_line"], 1, 1) == "23514"
    assert refused(*base, "PET_RELATED_FIRST", "LATE_PAYMENT_CHARGE", f["charge"], 1, 1) == "23514"
    # A Security stage needs a Security Deposit.
    assert refused(*base, "SECURITY_EXPLICIT", "INVOICE_LINE", f["rent_line"], 1, 1) == "23514"
    # Not more than the Deposit holds, nor more than the obligation still owes.
    assert refused(*base, "PET_REMAINDER_EXPLICIT", "INVOICE_LINE", f["rent_line"], 20_001, 1) == (
        "23514"
    )
    damage_due = outstanding(url, f["pet_line"])
    assert refused(
        *base, "PET_RELATED_FIRST", "INVOICE_LINE", f["pet_line"], damage_due + 1, 1
    ) == ("23514")
    # Targets and Deposits of another Lease are refused.
    assert refused(*base, "PET_REMAINDER_EXPLICIT", "INVOICE_LINE", other["rent_line"], 1, 1) == (
        "23514"
    )
    assert (
        refused(
            url,
            prop,
            human,
            settlement,
            other["pet"],
            "PET_REMAINDER_EXPLICIT",
            "INVOICE_LINE",
            f["rent_line"],
            1,
            1,
        )
        == "23514"
    )
    assert (
        refused(
            url,
            prop,
            human,
            other_settlement,
            f["pet"],
            "PET_REMAINDER_EXPLICIT",
            "INVOICE_LINE",
            other["rent_line"],
            1,
            1,
        )
        == "23514"
    )
    # An unknown target is refused clearly, and the approver must be a person.
    assert refused(*base, "PET_REMAINDER_EXPLICIT", "INVOICE_LINE", uuid4(), 1, 1) == "P0002"
    assert refused(*base, "PET_REMAINDER_EXPLICIT", "LATE_PAYMENT_CHARGE", uuid4(), 1, 1) == "P0002"
    assert refused(*base, "PET_REMAINDER_EXPLICIT", "INVOICE", f["invoice"], 1, 1) == "22023"
    with psycopg.connect(url) as connection:
        service_actor = register_billing_service_principal(
            connection, property_id=prop, created_by=human
        )
    for approver in (uuid4(), service_actor):
        assert (
            refused(
                url,
                prop,
                approver,
                settlement,
                f["pet"],
                "PET_REMAINDER_EXPLICIT",
                "INVOICE_LINE",
                f["rent_line"],
                1,
                1,
            )
            == "42501"
        )
    # The record's own check refuses a service identity for any future writer too.
    with psycopg.connect(url) as connection:
        with pytest.raises(psycopg.Error) as direct:
            connection.execute(
                "INSERT INTO app.deposit_applications(id,final_settlement_id,deposit_id,"
                "target_kind,invoice_id,invoice_line_id,application_stage,amount_usd_cents,"
                "application_order,reason,occurred_at,actor_id,authorization_reference) "
                "VALUES (%s,%s,%s,'INVOICE_LINE',%s,%s,'PET_REMAINDER_EXPLICIT',1,1,%s,"
                "clock_timestamp(),%s,'financial.approve')",
                (
                    uuid4(),
                    settlement,
                    f["pet"],
                    f["invoice"],
                    f["rent_line"],
                    REASON,
                    service_actor,
                ),
            )
    assert direct.value.sqlstate == "42501"
    # DL-032 order: no earlier stage after a later one; the order number only grows.
    apply(*base, "PET_REMAINDER_EXPLICIT", "INVOICE_LINE", f["rent_line"], 1, 5)
    assert refused(*base, "PET_RELATED_FIRST", "INVOICE_LINE", f["pet_line"], 1, 6) == "23514"
    assert refused(*base, "PET_REMAINDER_EXPLICIT", "INVOICE_LINE", f["rent_line"], 1, 5) == "23514"
    assert refused(*base, "PET_REMAINDER_EXPLICIT", "INVOICE_LINE", f["rent_line"], 1, 4) == "23514"
    assert one(
        url,
        "SELECT count(*) FROM app.deposit_applications WHERE final_settlement_id=%s",
        settlement,
    ) == (1,)
    assert held(url, f["pet"]) == 19_999
    with psycopg.connect(url) as connection:
        for statement in (
            "UPDATE app.deposit_applications SET amount_usd_cents=2 WHERE final_settlement_id=%s",
            "DELETE FROM app.deposit_applications WHERE final_settlement_id=%s",
        ):
            with pytest.raises(psycopg.Error) as mutated:
                with connection.transaction():
                    connection.execute(statement, (settlement,))
            assert mutated.value.sqlstate == "55000"


def test_kept_deposits_are_never_applied(migrated_database_url: str) -> None:
    url = migrated_database_url
    # Voluntary early leaving keeps the Security Deposit (BR-DEP-023): it is never applied, even
    # before its forfeiture draft is confirmed.
    human, prop, lease, security, _pet, invoice, line, day = lease_with_charge(url)
    assert held(url, security) > 0
    terminate(url, human, prop, lease, day)
    settlement = start(prop, human, lease)
    assert (
        refused(
            url,
            prop,
            human,
            settlement,
            security,
            "SECURITY_EXPLICIT",
            "INVOICE_LINE",
            line,
            100,
            1,
        )
        == "23514"
    )
    # Pet noncompliance keeps both deposits (BR-DEP-022).
    human, prop, lease, security, pet, invoice, line, day = lease_with_charge(url)
    seed_historical_deposit_receipt(url, deposit_id=pet, actor_id=human, amount_usd_cents=1_000)
    terminate_for_disposition(
        url, PostgresDepositService(financial_database_url(), prop, human), lease, day
    )
    settlement = start(prop, human, lease)
    for deposit, stage in ((security, "SECURITY_EXPLICIT"), (pet, "PET_REMAINDER_EXPLICIT")):
        assert (
            refused(url, prop, human, settlement, deposit, stage, "INVOICE_LINE", line, 100, 1)
            == "23514"
        )
    # Any other termination follows DL-032: the Security Deposit may pay the open debt.
    human, prop, lease, security, _pet, invoice, line, day = lease_with_charge(url)
    terminate(url, human, prop, lease, day, voluntary=False)
    settlement = start(prop, human, lease)
    apply(
        url, prop, human, settlement, security, "SECURITY_EXPLICIT", "INVOICE_LINE", line, 1_500, 1
    )
    assert outstanding(url, line) == 0 and invoice_state(url, invoice)[0] == "PAID"


# The shared slice 6 rule read for a Pet Deposit at the Lease's termination record.
PET_RULE = (
    "SELECT app.lease_deposit_forfeiture_rule('PET',event.governing_event_reference,"
    "context.context_data->>'basis',lease.id,lease.actual_termination_date,lease.end_date) "
    "FROM app.leases lease JOIN app.lease_commands event ON event.lease_id=lease.id "
    "AND event.action='lease.terminate' AND event.occurred_at=lease.terminated_at "
    "LEFT JOIN app.lease_termination_contexts context ON context.command_event_id=event.event_id "
    "WHERE lease.id=%s"
)


def kept_security_refused(
    url: str, prop: UUID, human: UUID, lease: UUID, security: UUID, line: UUID, ground: str
) -> UUID:
    """The termination ground keeps the Security Deposit; the Pet Deposit is not kept."""
    settlement = start(prop, human, lease)
    assert one(url, "SELECT app.lease_deposit_kept_rule(%s,%s)", prop, security) == (ground,)
    assert one(url, PET_RULE, lease) == (None,)
    amount = held(url, security)
    assert amount > 0
    assert (
        refused(
            url, prop, human, settlement, security, "SECURITY_EXPLICIT", "INVOICE_LINE", line, 1, 1
        )
        == "23514"
    )
    assert held(url, security) == amount
    return settlement


def test_violation_default_and_unpaid_initial_grounds_keep_only_the_security_deposit(
    migrated_database_url: str,
) -> None:
    """BR-DEP-026 through the shared rule; the Pet Deposit stays applicable (BR-DEP-027)."""
    url = migrated_database_url
    # Non-pet violation (BR-LEASE-025): the Pet Deposit still pays the debt.
    human, prop, lease, security, pet, invoice, line, day = lease_with_charge(url)
    seed_historical_deposit_receipt(url, deposit_id=pet, actor_id=human, amount_usd_cents=1_000)
    terminate_on(
        url,
        human,
        prop,
        lease,
        day,
        "BR-LEASE-025",
        TerminationBasis.CUSTOMER_VIOLATION,
        warnings=True,
    )
    settlement = kept_security_refused(url, prop, human, lease, security, line, "BR-LEASE-025")
    apply(
        url, prop, human, settlement, pet, "PET_REMAINDER_EXPLICIT", "INVOICE_LINE", line, 1_000, 1
    )
    assert (outstanding(url, line), held(url, pet)) == (500, 0)
    assert invoice_state(url, invoice)[0] == "PARTIALLY_PAID"

    # 30-day Rent nonpayment default (BR-LEASE-028) with its recorded Serious Default event.
    source = signed_with_initial(url, 120)
    human, prop, lease = source["actor"], source["property"], source["lease"]
    period = (source["today"] - timedelta(days=35)).replace(day=1)
    with psycopg.connect(url) as connection:
        _, rent_line = create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=source["customer"],
            lease_id=lease,
            period_start=period,
        )
    flow = enforcement()
    case = open_case(flow, prop, lease, rent_line, human)
    record_nonpayment_event(
        flow, prop, lease, case, human, NonpaymentEventKind.THIRTY_DAY_SERIOUS_DEFAULT
    )
    terminate_on(
        url,
        human,
        prop,
        lease,
        source["today"],
        "BR-LEASE-028",
        TerminationBasis.SIGNED_LEASE_OTHER,
        warnings=False,
    )
    kept_security_refused(url, prop, human, lease, source["deposit"], rent_line, "BR-LEASE-028")

    # Unpaid Initial Rent or Security Deposit (BR-LEASE-005).
    source = signed_with_initial(url, 10)
    terminate_unpaid(url, source)
    kept_security_refused(
        url,
        source["property"],
        source["actor"],
        source["lease"],
        source["deposit"],
        line_of(url, source["invoice"]),
        "BR-LEASE-005",
    )


def test_a_deposit_pays_an_invoice_of_another_signer(migrated_database_url: str) -> None:
    """Owner answer 5: a Lease Deposit pays any Signer's debt; the Invoice keeps its Customer."""
    url = migrated_database_url
    now = today(url)
    first = date(now.year - 1, 1, 1)
    with psycopg.connect(url) as connection:
        human, prop, unit, tenant, co_signer = setup_sources(connection)
        lease = create_draft(
            connection,
            actor_id=human,
            unit_id=unit,
            primary_tenant_id=tenant,
            start_date=first,
            end_date=date(now.year + 1, 12, 31),
        )
        connection.execute(
            "INSERT INTO app.lease_signers(id,lease_id,customer_id,signed_at,added_by) "
            "VALUES (%s,%s,%s,statement_timestamp(),%s)",
            (uuid4(), lease, co_signer, human),
        )
        sign_lease(connection, lease, human)
        connection.execute(
            "INSERT INTO app.occupancies(id,lease_id,customer_id,move_in_date,"
            "created_by,updated_by) VALUES (%s,%s,%s,%s,%s,%s)",
            (uuid4(), lease, tenant, first, human, human),
        )
        obligation = uuid4()
        reference = f"approved-obligation/{obligation}"
        connection.execute(
            "INSERT INTO app.authorized_nonrecurring_obligations("
            "id,customer_id,lease_id,category,description,authorized_amount_usd_cents,"
            "governing_due_date,due_date_source,source_reference,authorized_at,authorized_by,"
            "authorization_reference) VALUES (%s,%s,%s,'MISCELLANEOUS_CHARGES',"
            "'Authorized replacement key',2500,current_date+14,%s,%s,clock_timestamp(),%s,"
            "'invoice.nonrecurring.authorize')",
            (obligation, co_signer, lease, reference, reference, human),
        )
    service = PostgresInvoiceService(runtime_database_url(), financial_database_url())
    staff = invoice_api_actor(human, prop)
    draft = service.create_draft(prop, CreateInvoiceDraftCommand(uuid4(), obligation), actor=staff)
    invoice = UUID(str(draft["id"]))
    service.issue(
        prop, invoice, IssueInvoiceCommand(uuid4(), int(str(draft["version"]))), actor=staff
    )
    line = line_of(url, invoice)
    pet = pet_deposit(url, human, prop, lease, now)
    terminate(url, human, prop, lease, now, voluntary=False)
    settlement = start(prop, human, lease)
    apply(
        url, prop, human, settlement, pet, "PET_REMAINDER_EXPLICIT", "INVOICE_LINE", line, 2_500, 1
    )
    assert (outstanding(url, line), invoice_state(url, invoice)[0], held(url, pet)) == (
        0,
        "PAID",
        17_500,
    )
    assert one(
        url,
        "SELECT invoice.customer_id,deposit.customer_id FROM app.invoices invoice,"
        "app.deposits deposit WHERE invoice.id=%s AND deposit.id=%s",
        invoice,
        pet,
    ) == (co_signer, tenant)


def test_payment_contexts_count_a_deposit_application_on_a_charge(
    migrated_database_url: str,
) -> None:
    """Both Payment action contexts read the Charge balance from its financial position."""
    url = migrated_database_url
    f = overdue_lease_with_pet_damage(url)
    prop, human, charge = f["prop"], f["human"], f["charge"]
    charge_due = charge_remaining(url, charge)
    assert charge_due > 300
    with psycopg.connect(url) as connection:
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=f["customer"], amount=1_000
        )
    allocations().post(
        prop,
        payment,
        PostAllocationsCommand(
            uuid4(),
            {
                "mode": "DIRECT_CHARGE",
                "late_payment_charge_id": str(charge),
                "amount_usd_cents": 100,
            },
        ),
        actor=allocation_actor(human, prop),
    )
    settlement = start(prop, human, f["lease"])
    apply(
        url,
        prop,
        human,
        settlement,
        f["pet"],
        "PET_REMAINDER_EXPLICIT",
        "LATE_PAYMENT_CHARGE",
        charge,
        200,
        1,
    )
    assert charge_remaining(url, charge) == charge_due - 300
    with psycopg.connect(url) as connection:
        found = connection.execute(
            "SELECT app.payment_reversal_context_page(%s,%s,%s,'result',100,NULL,NULL)",
            (prop, payment, human),
        ).fetchone()
        assert found is not None
        items = [item for item in found[0]["items"] if item["kind"] == "LATE_PAYMENT_CHARGE"]
        assert [item["data"]["remaining_balance_usd_cents"] for item in items] == [charge_due - 300]
        found = connection.execute(
            "SELECT app.financial_action_context_page(%s,%s,'allocation',%s,NULL,"
            "'LATE_PAYMENT_CHARGE',%s,50,NULL,NULL)",
            (prop, human, payment, charge),
        ).fetchone()
        assert found is not None
        assert found[0]["target"]["remaining_balance_usd_cents"] == charge_due - 300


def test_a_charge_correction_after_a_deposit_application_is_a_conflict(
    migrated_database_url: str,
) -> None:
    """The refusal reaches the Late-payment service as a conflict, not as an unknown outcome."""
    url = migrated_database_url
    f = overdue_lease_with_pet_damage(url)
    prop, human, charge = f["prop"], f["human"], f["charge"]
    settlement = start(prop, human, f["lease"])
    apply(
        url,
        prop,
        human,
        settlement,
        f["pet"],
        "PET_REMAINDER_EXPLICIT",
        "LATE_PAYMENT_CHARGE",
        charge,
        1,
        1,
    )
    before = charge_remaining(url, charge)
    assert before > 2
    with pytest.raises(LatePaymentConflictError) as failure:
        late_payments().correct_charge(
            prop,
            charge,
            CorrectLatePaymentChargeCommand(
                uuid4(), CorrectionKind.REDUCTION, "Reduce after settlement", 1
            ),
            actor=late_payment_actor(human, prop),
        )
    assert not isinstance(failure.value, LatePaymentApplicationReversalRequired)
    assert charge_remaining(url, charge) == before
    assert one(
        url,
        "SELECT count(*) FROM app.late_payment_charge_corrections WHERE late_payment_charge_id=%s",
        charge,
    ) == (0,)


def test_paid_obligations_and_deposit_receipts_are_protected(migrated_database_url: str) -> None:
    url = migrated_database_url
    f = overdue_lease_with_pet_damage(url)
    prop, human = f["prop"], f["human"]
    settlement = start(prop, human, f["lease"])
    apply(
        url,
        prop,
        human,
        settlement,
        f["pet"],
        "PET_REMAINDER_EXPLICIT",
        "LATE_PAYMENT_CHARGE",
        f["charge"],
        1,
        1,
    )
    apply(
        url,
        prop,
        human,
        settlement,
        f["pet"],
        "PET_REMAINDER_EXPLICIT",
        "INVOICE_LINE",
        f["rent_line"],
        1,
        2,
    )
    receipt, payment = one(
        url, "SELECT id,payment_id FROM app.deposit_receipts WHERE deposit_id=%s", f["pet"]
    )
    # The Payment that funded the Deposit now reaches an active Deposit application: both
    # Payment action contexts report it as unsupported (migrations 46 and 47 forward checks).
    with psycopg.connect(url) as connection:
        for view in ("impact", "result"):
            found = connection.execute(
                "SELECT app.payment_reversal_context_page(%s,%s,%s,%s,100,NULL,NULL)",
                (prop, payment, human, view),
            ).fetchone()
            assert found is not None and found[0]["unsupported_application"] is True
        found = connection.execute(
            "SELECT app.financial_action_context_page(%s,%s,'allocation',"
            "%s,NULL,NULL,NULL,50,NULL,NULL)",
            (prop, human, payment),
        ).fetchone()
        assert found is not None and found[0]["unsupported_application"] is True
    statements = (
        (
            "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
            "authorization_reference) VALUES (%s,%s,'Mistaken Invoice',clock_timestamp(),%s,"
            "'invoices.void')",
            (uuid4(), f["invoice"], human),
        ),
        (
            "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adjustment_type,"
            "amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
            "authorization_reference) VALUES (%s,%s,%s,'CREDIT',1,'settled','Reduce',"
            "clock_timestamp(),%s,'invoices.adjust')",
            (uuid4(), f["invoice"], f["rent_line"], human),
        ),
        (
            "INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,"
            "correction_kind,amount_usd_cents,reason,previous_obligation_usd_cents,"
            "resulting_obligation_usd_cents,occurred_at,actor_id,authorization_reference) "
            "SELECT %s,id,'REDUCTION',1,'Reduce',original_amount_usd_cents,"
            "original_amount_usd_cents-1,clock_timestamp(),%s,'late_payment.charge_correction' "
            "FROM app.late_payment_charges WHERE id=%s",
            (uuid4(), human, f["charge"]),
        ),
        (
            "INSERT INTO app.deposit_receipt_reversals(id,deposit_receipt_id,reason,occurred_at,"
            "actor_id,authorization_reference) VALUES (%s,%s,'Returned transfer',clock_timestamp(),"
            "%s,'deposits.correct')",
            (uuid4(), receipt, human),
        ),
    )
    # The Late-payment Charge correction refusal uses the Late-payment conflict code.
    expected = ("55000", "55000", "P4603", "55000")
    for (statement, parameters), sqlstate in zip(statements, expected, strict=True):
        with psycopg.connect(url) as connection:
            with pytest.raises(psycopg.Error) as failure:
                connection.execute(statement, parameters)
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert failure.value.sqlstate == sqlstate, statement


def test_settlement_records_are_least_privilege(migrated_database_url: str) -> None:
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        privileges = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
        for table in ("app.final_settlements", "app.deposit_applications"):
            for role in ("public", "prm_runtime", "prm_financial", "prm_bootstrap"):
                for privilege in privileges:
                    assert connection.execute(
                        "SELECT has_table_privilege(%s,%s,%s)", (role, table, privilege)
                    ).fetchone() == (False,), (role, table, privilege)
        functions = connection.execute(
            "SELECT p.oid::regprocedure::text,p.prosecdef,p.proconfig FROM pg_catalog.pg_proc p "
            "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='app' AND "
            "p.proname IN ('start_final_settlement','post_deposit_application',"
            "'final_settlement_json','lease_deposit_forfeiture_rule','lease_deposit_kept_rule',"
            "'invoice_line_is_pet_damage',"
            "'invoice_line_deposit_value_at','validate_final_settlement','reject_final_settlement_change',"
            "'validate_deposit_application','validate_deposit_application_complete',"
            "'refuse_deposit_applied_obligation_change')"
        ).fetchall()
        assert len(functions) == 12
        for signature, definer, config in functions:
            assert definer is True and "search_path=pg_catalog" in (config or []), signature
            for role in ("public", "prm_runtime", "prm_financial", "prm_bootstrap"):
                allowed = connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)
                ).fetchone()
                expected = role == "prm_financial" and signature.startswith(
                    "app.start_final_settlement("
                )
                assert allowed == (expected,), (role, signature)


def test_final_settlement_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261021_86")
    assert revision is not None and revision.down_revision == "20261020_85"
    module = revision.module
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
