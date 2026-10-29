"""Customer ledger source reconstruction on isolated synthetic PostgreSQL."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from deposit_disposition_test_support import disposition_context, terminate_for_disposition
from deposit_receipt_reversal_test_support import reverse_receipt_as_owner
from lease_deposit_forfeiture_test_support import (
    record_disposition_as_owner,
    reverse_disposition_as_owner,
)
from payment_test_support import database_instant, seed_payment
from property_rental.billing import PostgresRentBillingService
from property_rental.credit import ReverseCreditApplicationCommand, ReverseCreditCommand
from property_rental.customer_ledger import EVENT_ORDER, LedgerPosition, exact_cents
from property_rental.deposit import (
    AdjustDepositRequiredAmountCommand,
    DepositAdjustmentType,
    RecordDepositDispositionCommand,
    ReverseDepositDispositionCommand,
    ReverseDepositReceiptCommand,
)
from property_rental.invoice import (
    CreateInvoiceDraftCommand,
    IssueInvoiceCommand,
    PostgresInvoiceService,
    VoidInvoiceCommand,
)
from property_rental.late_payment import (
    CorrectionKind,
    CorrectLatePaymentChargeCommand,
    DecisionOutcome,
    FinalizeLatePaymentDecisionCommand,
    LatePaymentConflictError,
)
from property_rental.payment_allocation import (
    PostAllocationsCommand,
    ReverseAllocationCommand,
    ReversePaymentCommand,
)
from property_rental.refund import ReverseRefundCorrectionCommand
from refund_test_support import create_pet_refund, create_usd_refund
from test_billing_service_migration import (
    add_service,
    authenticated,
    initial_command,
    setup_billing_source,
)
from test_credit_application_migration import application_id
from test_credit_application_migration import designated as credit_designated
from test_credit_application_migration import source as credit_source
from test_credit_migration import (
    actor,
    credit_id,
    recognize,
)
from test_credit_migration import (
    service as credits,
)
from test_credit_migration import (
    source as payment_source,
)
from test_deposit_migration import (
    create_pet,
    seed_historical_deposit_receipt,
    setup_signed_pet_lease,
)
from test_invoice_migration import (
    financial_database_url,
    invoice_api_actor,
    runtime_database_url,
    setup_invoice_api_source,
)
from test_late_payment_migration import late_payment_actor, setup_invoice
from test_late_payment_migration import service as late_service
from test_lease_migration import setup_sources, sign_lease
from test_migrations import _temporary_migration_database
from test_payment_allocation_migration import (
    actor as allocation_actor,
)
from test_payment_allocation_migration import (
    designated,
)
from test_payment_allocation_migration import (
    service as allocations,
)
from test_payment_allocation_migration import source as allocation_source
from test_payment_migration import fx_payment
from test_refund_service_migration import (
    corrections,
    create,
    refund_id,
    returned,
)
from test_refund_service_migration import (
    service as refunds,
)
from test_reservation_migration import migrated_database_url  # noqa: F401

VIEWS = (
    "customer_ledger_effects",
    "customer_account_ledger",
    "customer_ledger_history",
    "customer_ledger_balance_sources",
    "customer_financial_position",
)


def position(connection: psycopg.Connection[tuple[object, ...]], customer: UUID) -> LedgerPosition:
    row = connection.execute(
        (
            "SELECT invoice_outstanding_usd_cents,charge_outstanding"
            "_usd_cents,available_credit_usd_cents,unallocated_payme"
            "nt_usd_cents,security_deposit_held_usd_cents,pet_deposi"
            "t_held_usd_cents FROM app.customer_financial_position WHERE "
            "customer_id=%s"
        ),
        (customer,),
    ).fetchone()
    if row is None:
        return LedgerPosition()
    return LedgerPosition(*(exact_cents(value) for value in row))


def history(
    connection: psycopg.Connection[tuple[object, ...]], customer: UUID
) -> list[dict[str, object]]:
    rows = connection.execute(
        "SELECT to_jsonb(e) FROM app.customer_ledger_history e WHERE customer_id=%s "
        "ORDER BY occurred_at,event_order,event_kind,event_id",
        (customer,),
    ).fetchall()
    return [cast(dict[str, object], row[0]) for row in rows]


def assert_reconciled(
    connection: psycopg.Connection[tuple[object, ...]], customer: UUID
) -> LedgerPosition:
    expected = position(connection, customer)
    events = history(connection, customer)
    if events:
        last = events[-1]
        LedgerPosition(
            *(exact_cents(last[field + "_after_usd_cents"]) for field in LedgerPosition.fields)
        ).reconcile(expected)
    else:
        LedgerPosition().reconcile(expected)
    # Source-level reconciliation catches equal totals with the wrong ownership or
    # line attribution. It includes sources whose complete history now totals zero.
    difference = connection.execute(
        (
            "WITH derived AS (SELECT "
            "property_id,customer_id,balance_kind,balance_source_id,"
            "sum(effect_usd_cents) AS amount FROM "
            "app.customer_ledger_effects WHERE customer_id=%s AND "
            "balance_kind<>'NONE' GROUP BY "
            "property_id,customer_id,balance_kind,balance_source_id), "
            "actual AS (SELECT * FROM "
            "app.customer_ledger_balance_sources WHERE customer_id=%s) "
            "SELECT d.balance_kind,d.balance_source_id,d.amount,a.ba"
            "lance_usd_cents FROM derived d FULL JOIN actual a "
            "USING(property_id,customer_id,balance_kind,balance_sour"
            "ce_id) WHERE COALESCE(d.amount,0)<>COALESCE(a.balance_u"
            "sd_cents,0)"
        ),
        (customer, customer),
    ).fetchall()
    assert difference == []
    assert len({(e["event_kind"], e["event_id"]) for e in events}) == len(events)
    assert all(EVENT_ORDER[str(e["event_kind"])] == e["event_order"] for e in events)
    return expected


def canonical_invoice(url: str) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID]:
    """Actual $500 Rent plus $10 Trash source, before any financial application."""
    with psycopg.connect(url) as connection:
        human, prop, unit, customer, _ = setup_sources(connection)
        lease, occupancy = uuid4(), uuid4()
        connection.execute(
            (
                "INSERT INTO app.leases(id,unit_id,primary_tenant_id,sta"
                "rt_date,end_date,monthly_rent_usd_cents,created_by,upda"
                "ted_by) VALUES(%s,%s,%s,'2026-07-01','2027-06-30',50000"
                ",%s,%s)"
            ),
            (lease, unit, customer, human, human),
        )
        connection.execute(
            (
                "INSERT INTO app.lease_signers(id,lease_id,customer_id,s"
                "igned_at,added_by) VALUES(%s,%s,%s,statement_timestamp(),%s)"
            ),
            (uuid4(), lease, customer, human),
        )
        sign_lease(connection, lease, human)
        connection.execute(
            (
                "INSERT INTO app.occupancies(id,lease_id,customer_id,mov"
                "e_in_date,created_by,updated_by) "
                "VALUES(%s,%s,%s,'2026-07-01',%s,%s)"
            ),
            (occupancy, lease, customer, human, human),
        )
        add_service(
            connection,
            actor_id=human,
            property_id=prop,
            lease_id=lease,
            code="TRASH_COLLECTION",
            display_name="Trash Collection",
            first_rate=1000,
            second_rate=1200,
            applicable_from=date(2026, 7, 1),
        )
        at = datetime(2026, 6, 30, 17, 0, 1, tzinfo=UTC)
    issued = PostgresRentBillingService(financial_database_url(), prop, human).generate(
        initial_command(lease, occupancy, period_start=date(2026, 7, 1), issued_at=at),
        actor=authenticated(human, prop),
    )
    assert issued.rent_usd_cents == 50000 and issued.total_usd_cents == 51000
    with psycopg.connect(url) as connection:
        lines = connection.execute(
            "SELECT id,category FROM app.invoice_lines WHERE invoice_id=%s ORDER BY line_sequence",
            (issued.invoice_id,),
        ).fetchall()
    assert [row[1] for row in lines] == ["RENT", "SERVICE_CHARGES"]
    return human, prop, customer, issued.invoice_id, UUID(str(lines[0][0])), UUID(str(lines[1][0]))


def test_ledger_canonical_rent_service_charge_example_and_original_source_preservation(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, invoice, rent, trash = canonical_invoice(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition(invoice=51000)
        original = connection.execute(
            "SELECT id,amount_usd_cents FROM app.invoice_lines WHERE invoice_id=%s ORDER BY id",
            (invoice,),
        ).fetchall()
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=30000
        )
    allocations().post(
        prop, payment, designated(invoice, rent, 30000), actor=allocation_actor(human, prop)
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition(invoice=21000)
        assert connection.execute(
            (
                "SELECT invoice_line_id,balance_usd_cents FROM "
                "app.customer_ledger_balance_sources WHERE invoice_id=%s "
                "ORDER BY category"
            ),
            (invoice,),
        ).fetchall() == [(rent, 20000), (trash, 1000)]
    # DL-064 (BR-RENT-009): the Initial Rent Invoice has no late-payment charge, so the
    # canonical late charge is now rejected; ledger late charges are covered on recurring Rent.
    with pytest.raises(LatePaymentConflictError):
        late_service().finalize_decision(
            prop,
            invoice,
            FinalizeLatePaymentDecisionCommand(
                uuid4(), DecisionOutcome.CONFIRMED_DEFAULT, 2100, "Confirm canonical late charge"
            ),
            actor=late_payment_actor(human, prop),
        )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition(invoice=21000)
        assert connection.execute(
            "SELECT count(*) FROM app.late_payment_charges WHERE source_invoice_id=%s", (invoice,)
        ).fetchone() == (0,)
        second = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=21000
        )
    allocations().post(
        prop,
        second,
        PostAllocationsCommand(
            uuid4(),
            {
                "mode": "DESIGNATED",
                "designation_reference": "Pay Rent and Trash",
                "targets": [
                    {
                        "invoice_id": str(invoice),
                        "amount_usd_cents": 21000,
                        "details": [
                            {"invoice_line_id": str(rent), "amount_usd_cents": 20000},
                            {"invoice_line_id": str(trash), "amount_usd_cents": 1000},
                        ],
                    },
                ],
            },
        ),
        actor=allocation_actor(human, prop),
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition()
        assert (
            connection.execute(
                "SELECT id,amount_usd_cents FROM app.invoice_lines WHERE invoice_id=%s ORDER BY id",
                (invoice,),
            ).fetchall()
            == original
        )
        events = history(connection, customer)
        assert sum(exact_cents(e["invoice_effect_usd_cents"], signed=True) for e in events) == 0
        assert [
            e["recorded_amount_usd_cents"] for e in events if e["event_kind"] == "INVOICE_ISSUED"
        ] == [51000]
        assert len([e for e in events if e["event_kind"] == "PAYMENT_ALLOCATED"]) == 2


def test_ledger_allocation_and_payment_reversals_restore_separate_positions(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, invoices = allocation_source(migrated_database_url)
    staff = allocation_actor(human, prop)
    proposal = allocations().proposal(prop, payment, actor=staff)
    allocations().post(
        prop,
        payment,
        PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
        actor=staff,
    )
    with psycopg.connect(migrated_database_url) as connection:
        source_row = connection.execute(
            "SELECT payer_customer_id FROM app.payments WHERE id=%s", (payment,)
        ).fetchone()
        assert source_row is not None
        customer = UUID(str(source_row[0]))
        assert assert_reconciled(connection, customer) == LedgerPosition(invoice=60000)
        ids = connection.execute(
            "SELECT id FROM app.payment_allocations WHERE payment_id=%s ORDER BY id", (payment,)
        ).fetchall()
    for row in ids:
        allocations().reverse_allocation(
            prop,
            UUID(str(row[0])),
            ReverseAllocationCommand(uuid4(), "Wrong application"),
            actor=staff,
        )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition(
            invoice=160000, payment=100000
        )
    allocations().reverse_payment(
        prop, payment, ReversePaymentCommand(uuid4(), "Wrong receipt"), actor=staff
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition(invoice=160000)
        kinds = {e["event_kind"] for e in history(connection, customer)}
        assert {
            "PAYMENT_RECEIVED",
            "PAYMENT_REVERSED",
            "PAYMENT_ALLOCATED",
            "PAYMENT_ALLOCATION_REVERSED",
        } <= kinds
        assert len(invoices) == 2


def test_ledger_third_party_application_does_not_transfer_obligation_ownership(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, invoices = allocation_source(migrated_database_url)
    _, _, payer, other_payment = payment_source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT customer_id FROM app.invoices WHERE id=%s", (invoices[0],)
        ).fetchone()
        assert row is not None
        beneficiary = UUID(str(row[0]))
        before_payer = assert_reconciled(connection, payer)
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=payer,
            amount=80000,
            scope="THIRD_PARTY_IDENTIFIED",
            invoice_id=invoices[0],
        )
        line = connection.execute(
            "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", (invoices[0],)
        ).fetchone()
        assert line is not None
    allocations().post(
        prop,
        payment,
        designated(invoices[0], UUID(str(line[0])), 80000),
        actor=allocation_actor(human, prop),
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, payer) == before_payer
        target = assert_reconciled(connection, beneficiary)
        assert target.invoice == 80000
        payer_effect = connection.execute(
            (
                "SELECT invoice_effect_usd_cents,payment_effect_usd_cents "
                "FROM app.customer_account_ledger WHERE customer_id=%s AND "
                "payment_id=%s AND event_kind='PAYMENT_ALLOCATED'"
            ),
            (payer, payment),
        ).fetchone()
        target_effect = connection.execute(
            (
                "SELECT invoice_effect_usd_cents,payment_effect_usd_cents "
                "FROM app.customer_account_ledger WHERE customer_id=%s AND "
                "payment_id=%s AND event_kind='PAYMENT_ALLOCATED'"
            ),
            (beneficiary, payment),
        ).fetchone()
        assert payer_effect == (0, -80000) and target_effect == (-80000, 0)
        assert connection.execute(
            "SELECT payer_customer_id FROM app.payments WHERE id=%s", (other_payment,)
        ).fetchone() == (payer,)


@pytest.mark.parametrize("kind", ["PAYMENT", "CREDIT"])
def test_ledger_refund_return_and_correction_reversal_reconstruct_consumption(
    migrated_database_url: str,  # noqa: F811
    kind: str,
) -> None:
    human, prop, customer, payment = payment_source(migrated_database_url)
    source = credit_id(recognize(prop, payment, human, 10000)) if kind == "CREDIT" else payment
    paid = create_usd_refund(
        refunds(), prop, create(source, 8000, kind), actor=actor(human, prop, "refunds.create")
    )
    identity = refund_id(paid)
    correction = refunds().verify_usd_return(
        prop, identity, returned(3000), actor=actor(human, prop, "refunds.correct")
    )
    with psycopg.connect(migrated_database_url) as connection:
        expected = LedgerPosition(credit=5000) if kind == "CREDIT" else LedgerPosition(payment=5000)
        assert assert_reconciled(connection, customer) == expected
    refunds().reverse_correction(
        prop,
        identity,
        UUID(str(corrections(correction)[0]["id"])),
        ReverseRefundCorrectionCommand(uuid4(), "Return evidence invalid", "Reverse correction"),
        actor=actor(human, prop, "refunds.corrections.reverse"),
    )
    with psycopg.connect(migrated_database_url) as connection:
        expected = LedgerPosition(credit=2000) if kind == "CREDIT" else LedgerPosition(payment=2000)
        assert assert_reconciled(connection, customer) == expected
        events = history(connection, customer)
        assert len([e for e in events if e["event_kind"] == "REFUND_CORRECTED"]) == 2
        assert connection.execute(
            "SELECT usd_accounting_value_cents FROM app.refunds WHERE id=%s", (identity,)
        ).fetchone() == (8000,)


def test_ledger_credit_recognition_application_reversal_and_release_have_no_double_count(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, credit, invoice, line, payment = credit_source(migrated_database_url)
    applied = credits().apply(
        prop,
        credit,
        credit_designated(invoice, line, 30000),
        actor=actor(human, prop, "credits.apply"),
    )
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT customer_id FROM app.customer_credits WHERE id=%s", (credit,)
        ).fetchone()
        assert row is not None
        customer = UUID(str(row[0]))
        assert assert_reconciled(connection, customer) == LedgerPosition(
            invoice=50000, credit=70000
        )
    credits().reverse_application(
        prop,
        application_id(applied),
        ReverseCreditApplicationCommand(uuid4(), "Wrong application"),
        actor=actor(human, prop, "credits.applications.reverse"),
    )
    credits().reverse(
        prop,
        credit,
        ReverseCreditCommand(uuid4(), "Wrong consent"),
        actor=actor(human, prop, "credits.reverse"),
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition(
            invoice=80000, payment=100000
        )
        assert connection.execute(
            "SELECT usd_accounting_value_cents FROM app.payments WHERE id=%s", (payment,)
        ).fetchone() == (100000,)
        assert {e["event_kind"] for e in history(connection, customer)} >= {
            "CREDIT_RECOGNIZED",
            "CREDIT_RECOGNITION_REVERSED",
            "CREDIT_APPLIED",
            "CREDIT_APPLICATION_REVERSED",
        }


def test_ledger_invoice_adjustment_reversal_void_and_draft_void_preserve_history(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, obligation = setup_invoice_api_source(connection)
    invoice_service = PostgresInvoiceService(runtime_database_url(), financial_database_url())
    staff = invoice_api_actor(human, prop)
    draft = invoice_service.create_draft(
        prop, CreateInvoiceDraftCommand(uuid4(), obligation), actor=staff
    )
    invoice = UUID(str(draft["id"]))
    issued = invoice_service.issue(
        prop, invoice, IssueInvoiceCommand(uuid4(), int(str(draft["version"]))), actor=staff
    )
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", (invoice,)
        ).fetchone()
        assert row is not None
        line = UUID(str(row[0]))
        adjustment = uuid4()
        reversal = uuid4()
        connection.execute(
            (
                "INSERT INTO app.invoice_adjustments(id,invoice_id,invoi"
                "ce_line_id,adjustment_type,amount_usd_cents,source_refe"
                "rence,reason,occurred_at,actor_id,authorization_reference) "
                "VALUES(%s,%s,%s,'CREDIT',1000,'ledger-fixture','Authorized "
                "correction',clock_timestamp(),%s,'invoices.adjust')"
            ),
            (adjustment, invoice, line, human),
        )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition(invoice=9000)
        connection.execute(
            (
                "INSERT INTO app.invoice_adjustment_reversals(id,invoice"
                "_adjustment_id,reason,occurred_at,actor_id,authorizatio"
                "n_reference) VALUES(%s,%s,'Incorrect "
                "adjustment',clock_timestamp(),%s,'invoices.adjust')"
            ),
            (reversal, adjustment, human),
        )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition(invoice=10000)
        version = connection.execute(
            "SELECT version FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
        assert version is not None
    invoice_service.void(
        prop,
        invoice,
        VoidInvoiceCommand(uuid4(), "Wrong obligation", int(str(version[0]))),
        actor=staff,
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition()
        kinds = {e["event_kind"] for e in history(connection, customer)}
        assert {
            "INVOICE_ISSUED",
            "INVOICE_ADJUSTED",
            "INVOICE_ADJUSTMENT_REVERSED",
            "INVOICE_VOIDED",
        } <= kinds
        assert issued["original_total"] == {"currency": "USD", "minor_units": 10000}


def test_ledger_separate_charge_corrections_and_reversal_keep_invoice_unchanged(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, invoice, _ = setup_invoice(connection, period_start=date(2026, 5, 1))
    staff = late_payment_actor(human, prop)
    late_service().finalize_decision(
        prop,
        invoice,
        FinalizeLatePaymentDecisionCommand(
            uuid4(), DecisionOutcome.CONFIRMED_DEFAULT, 8000, "Confirm charge"
        ),
        actor=staff,
    )
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT id FROM app.late_payment_charges WHERE source_invoice_id=%s", (invoice,)
        ).fetchone()
        assert row is not None
        charge = UUID(str(row[0]))
    result = late_service().correct_charge(
        prop,
        charge,
        CorrectLatePaymentChargeCommand(
            uuid4(), CorrectionKind.REDUCTION, "Authorized reduction", 3000
        ),
        actor=staff,
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition(invoice=80000, charge=5000)
        row = connection.execute(
            "SELECT id FROM app.late_payment_charge_corrections WHERE late_payment_charge_id=%s",
            (charge,),
        ).fetchone()
        assert row is not None
        correction = UUID(str(row[0]))
    late_service().correct_charge(
        prop,
        charge,
        CorrectLatePaymentChargeCommand(
            uuid4(),
            CorrectionKind.REDUCTION_REVERSAL,
            "Reverse reduction",
            reverses_correction_id=correction,
        ),
        actor=staff,
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition(invoice=80000, charge=8000)
        assert result is not None


def test_ledger_pet_receipt_requirement_disposition_and_reversals_remain_separate(
    migrated_database_url: str,  # noqa: F811
) -> None:
    service, staff, lease, approval, day = setup_signed_pet_lease(migrated_database_url)
    deposit, _ = create_pet(service, staff, lease, approval, day)
    receipt = seed_historical_deposit_receipt(
        migrated_database_url, deposit_id=deposit, actor_id=service.actor_id, amount_usd_cents=20000
    )
    service.adjust_required_amount(
        AdjustDepositRequiredAmountCommand(
            uuid4(),
            uuid4(),
            deposit,
            DepositAdjustmentType.INCREASE,
            2500,
            day,
            "Approved required amount",
        ),
        actor=staff,
    )
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT customer_id FROM app.deposits WHERE id=%s", (deposit,)
        ).fetchone()
        assert row is not None
        customer = UUID(str(row[0]))
        assert assert_reconciled(connection, customer) == LedgerPosition(pet_deposit=20000)
    terminate_for_disposition(migrated_database_url, service, lease, date.today())
    disposition = uuid4()
    record_disposition_as_owner(
        service,
        RecordDepositDispositionCommand(
            uuid4(),
            disposition,
            deposit,
            lease,
            12000,
            date.today(),
            "Authorized disposition",
            context=disposition_context(migrated_database_url, deposit),
        ),
        actor=staff,
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition(pet_deposit=8000)
    reverse_disposition_as_owner(
        service,
        ReverseDepositDispositionCommand(
            uuid4(), uuid4(), disposition, "Wrong disposition", "Evidence corrected"
        ),
        actor=staff,
    )
    reverse_receipt_as_owner(
        service,
        ReverseDepositReceiptCommand(uuid4(), uuid4(), receipt, "Wrong receipt"),
        actor=staff,
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition(payment=20000)
        assert {e["event_kind"] for e in history(connection, customer)} >= {
            "DEPOSIT_REQUIREMENT_ADJUSTED",
            "DEPOSIT_RECEIVED",
            "DEPOSIT_RECEIPT_REVERSED",
            "DEPOSIT_DISPOSED",
            "DEPOSIT_DISPOSITION_REVERSED",
        }


def test_ledger_equal_timestamp_positions_include_all_peers_and_keep_stable_identity(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, _ = payment_source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        at = database_instant(connection)
        ids = [
            seed_payment(
                connection,
                actor_id=human,
                property_id=prop,
                customer_id=customer,
                amount=amount,
                confirmed_at=at,
            )
            for amount in (100, 200, 300)
        ]
    with psycopg.connect(migrated_database_url) as connection:
        events = [
            e
            for e in history(connection, customer)
            if e["event_id"] in {str(identity) for identity in ids}
        ]
        assert [e["event_id"] for e in events] == [str(identity) for identity in sorted(ids)]
        assert all(e["payment_after_usd_cents"] == 10600 for e in events)
        assert assert_reconciled(connection, customer) == LedgerPosition(payment=10600)


def test_ledger_read_only_snapshot_is_coherent_across_concurrent_financial_commit(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, payment = payment_source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as reader:
        reader.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        before = history(reader, customer)
        guard = reader.execute(
            "SELECT revision FROM app.payment_serialization_guards WHERE payment_id=%s", (payment,)
        ).fetchone()
        create_usd_refund(
            refunds(), prop, create(payment, 3000), actor=actor(human, prop, "refunds.create")
        )
        assert history(reader, customer) == before
        assert assert_reconciled(reader, customer) == LedgerPosition(payment=10000)
        assert (
            reader.execute(
                "SELECT revision FROM app.payment_serialization_guards WHERE payment_id=%s",
                (payment,),
            ).fetchone()
            == guard
        )
    with psycopg.connect(migrated_database_url) as fresh:
        assert assert_reconciled(fresh, customer) == LedgerPosition(payment=7000)


def test_ledger_large_exact_aggregates_and_empty_customer(migrated_database_url: str) -> None:  # noqa: F811
    human, prop, customer, payment = payment_source(migrated_database_url, 9_000_000_000_000_000)
    with psycopg.connect(migrated_database_url) as connection:
        seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=customer,
            amount=9_000_000_000_000_000,
        )
        assert assert_reconciled(connection, customer).payment == 18_000_000_000_000_000
        assert history(connection, uuid4()) == []
        assert position(connection, uuid4()) == LedgerPosition()
        assert payment.int != 0


@pytest.mark.parametrize("role", ["prm_runtime", "prm_financial", "prm_bootstrap", "public"])
def test_ledger_projection_has_no_direct_application_role_access_or_writable_views(
    migrated_database_url: str,  # noqa: F811
    role: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        for view in VIEWS:
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert connection.execute(
                    "SELECT has_table_privilege(%s,%s,%s)", (role, "app." + view, privilege)
                ).fetchone() == (False,)
        assert connection.execute(
            (
                "SELECT table_name,is_updatable,is_insertable_into FROM "
                "information_schema.views WHERE table_schema='app' AND "
                "table_name=ANY(%s) ORDER BY table_name"
            ),
            (list(VIEWS),),
        ).fetchall() == [(view, "NO", "NO") for view in sorted(VIEWS)]


def test_ledger_forward_projection_upgrade_preserves_populated_predecessor(
    migrated_database_url: str,  # noqa: F811
) -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["20270407_257"]
    revision = scripts.get_revision("20260909_48")
    assert revision is not None
    assert revision.down_revision == "20260908_47"
    with _temporary_migration_database("ledger_projection") as temporary:
        temporary_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        temporary_config.set_main_option("sqlalchemy.url", temporary)
        # The established helper overrides MIGRATION_DATABASE_URL for this isolated
        # database; no running application's database is used or reset.
        command.upgrade(temporary_config, "20260908_47")
        with psycopg.connect(temporary) as connection:
            human, prop, _, customer, _ = setup_sources(connection)
            payment = seed_payment(
                connection, actor_id=human, property_id=prop, customer_id=customer, amount=12345
            )
            before = connection.execute(
                "SELECT to_jsonb(p) FROM app.payments p WHERE id=%s", (payment,)
            ).fetchone()
            receipts = connection.execute(
                "SELECT to_jsonb(r) FROM app.receipts r WHERE payment_id=%s", (payment,)
            ).fetchall()
        command.upgrade(temporary_config, "head")
        with psycopg.connect(temporary) as connection:
            assert (
                connection.execute(
                    "SELECT to_jsonb(p) FROM app.payments p WHERE id=%s", (payment,)
                ).fetchone()
                == before
            )
            assert (
                connection.execute(
                    "SELECT to_jsonb(r) FROM app.receipts r WHERE payment_id=%s", (payment,)
                ).fetchall()
                == receipts
            )
            assert assert_reconciled(connection, customer) == LedgerPosition(payment=12345)
        module = scripts.get_revision("20260909_48")
        assert module is not None
        with pytest.raises(RuntimeError, match="forward-only"):
            module.module.downgrade()


@pytest.mark.parametrize(
    "manual,channel,amount", [(False, False, 4143), (True, False, 4143), (False, True, 4100)]
)
def test_ledger_retains_original_khr_and_exact_fx_when_refunding_only_usd(
    migrated_database_url: str,  # noqa: F811
    manual: bool,
    channel: bool,
    amount: int,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        payment = fx_payment(connection, manual=manual, channel=channel, amount=amount)
        row = connection.execute(
            "SELECT confirmed_by,property_id,payer_customer_id FROM app.payments WHERE id=%s",
            (payment,),
        ).fetchone()
        assert row is not None
        human, prop, customer = (UUID(str(value)) for value in row)
        payment_before = connection.execute(
            "SELECT to_jsonb(p) FROM app.payments p WHERE id=%s", (payment,)
        ).fetchone()
        fx_before = connection.execute(
            (
                "SELECT to_jsonb(fx) FROM app.exchange_rate_records fx JOIN "
                "app.payments p ON p.exchange_rate_record_id=fx.id WHERE "
                "p.id=%s"
            ),
            (payment,),
        ).fetchone()
    create_usd_refund(
        refunds(), prop, create(payment, 100), actor=actor(human, prop, "refunds.create")
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition(payment=1)
        received = next(
            e for e in history(connection, customer) if e["event_kind"] == "PAYMENT_RECEIVED"
        )
        audit = cast(dict[str, object], received["source_audit"])
        assert audit["received_currency"] == "KHR" and audit["received_amount_minor"] == str(amount)
        assert audit["usd_accounting_value_cents"] == "101"
        rate = cast(dict[str, object], audit["exchange_rate"])
        assert Decimal(str(rate["reference_rate_khr_per_usd"])) == Decimal(4080)
        assert rate["system_rate_khr_per_usd"] == "4101"
        assert rate["channel_actual_usd_value_cents"] == ("101" if channel else None)
        assert rate["rate_source"] == ("ABA_EQUIVALENT_MANUAL" if manual else "ABA_AUTOMATIC")
        assert (
            connection.execute(
                "SELECT to_jsonb(p) FROM app.payments p WHERE id=%s", (payment,)
            ).fetchone()
            == payment_before
        )
        assert (
            connection.execute(
                (
                    "SELECT to_jsonb(fx) FROM app.exchange_rate_records fx JOIN "
                    "app.payments p ON p.exchange_rate_record_id=fx.id WHERE "
                    "p.id=%s"
                ),
                (payment,),
            ).fetchone()
            == fx_before
        )


def test_ledger_draft_void_is_zero_effect_without_issued_obligation(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, obligation = setup_invoice_api_source(connection)
    service = PostgresInvoiceService(runtime_database_url(), financial_database_url())
    staff = invoice_api_actor(human, prop)
    draft = service.create_draft(prop, CreateInvoiceDraftCommand(uuid4(), obligation), actor=staff)
    with psycopg.connect(migrated_database_url) as connection:
        assert history(connection, customer) == []
        assert assert_reconciled(connection, customer) == LedgerPosition()
    service.void(
        prop,
        UUID(str(draft["id"])),
        VoidInvoiceCommand(uuid4(), "Unissued duplicate", int(str(draft["version"]))),
        actor=staff,
    )
    with psycopg.connect(migrated_database_url) as connection:
        events = history(connection, customer)
        assert len(events) == 1 and events[0]["event_kind"] == "DRAFT_INVOICE_VOIDED"
        assert events[0]["invoice_effect_usd_cents"] == 0
        assert assert_reconciled(connection, customer) == LedgerPosition()


def test_ledger_waived_charge_and_whole_charge_reversal_retain_source_events(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, invoice, _ = setup_invoice(connection, period_start=date(2026, 5, 1))
    late_service().finalize_decision(
        prop,
        invoice,
        FinalizeLatePaymentDecisionCommand(uuid4(), DecisionOutcome.WAIVED, 0, "Authorized waiver"),
        actor=late_payment_actor(human, prop),
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition(invoice=80000)
        assert [
            e["recorded_amount_usd_cents"]
            for e in history(connection, customer)
            if e["event_kind"] == "LATE_PAYMENT_WAIVED"
        ] == [0]
        other, other_prop, other_customer, second, _ = setup_invoice(
            connection, period_start=date(2026, 5, 1)
        )
    staff = late_payment_actor(other, other_prop)
    late_service().finalize_decision(
        other_prop,
        second,
        FinalizeLatePaymentDecisionCommand(
            uuid4(), DecisionOutcome.CONFIRMED_DEFAULT, 8000, "Confirm charge"
        ),
        actor=staff,
    )
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT id FROM app.late_payment_charges WHERE source_invoice_id=%s", (second,)
        ).fetchone()
        assert row is not None
        charge = UUID(str(row[0]))
    late_service().correct_charge(
        other_prop,
        charge,
        CorrectLatePaymentChargeCommand(uuid4(), CorrectionKind.CHARGE_REVERSAL, "Wrong charge"),
        actor=staff,
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, other_customer) == LedgerPosition(invoice=80000)
        assert connection.execute(
            "SELECT original_amount_usd_cents FROM app.late_payment_charges WHERE id=%s", (charge,)
        ).fetchone() == (8000,)


def test_ledger_security_refund_coordinated_correction_keeps_liability_distinct(
    migrated_database_url: str,  # noqa: F811
) -> None:
    from test_reservation_lifecycle_migration import active_reservation, cancel

    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, customer, reservation = active_reservation(connection)
        initial = assert_reconciled(connection, customer)
        assert (
            initial.security_deposit > 0
            and initial.credit == initial.payment == initial.total_owed == 0
        )
    identity = uuid4()
    with psycopg.connect(financial_database_url()) as writer:
        cancel(
            writer,
            actor_id=human,
            property_id=prop,
            reservation_id=reservation,
            idempotency_key=uuid4(),
            event_id=uuid4(),
            outcome_id=identity,
            responsibility="PROPERTY",
            property_could_provide_unit=False,
            coordination_reference="Synthetic ledger cancellation",
            refund_number="LEDGER-" + identity.hex,
        )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition()
    from property_rental.refund import RefundInvalidError

    # Reservation refunds retain their coordinated whole-outcome correction path.
    with pytest.raises(RefundInvalidError):
        refunds().verify_usd_return(
            prop, identity, returned(1000), actor=actor(human, prop, "refunds.correct")
        )
    correction, replacement = uuid4(), uuid4()
    # V1-056 slice 3b: the correction is a draft confirmed under financial.approve.
    from reservation_deposit_test_support import correct_reservation_outcome

    with psycopg.connect(financial_database_url()) as writer:
        corrected = correct_reservation_outcome(
            writer,
            actor_id=human,
            property_id=prop,
            reservation_id=reservation,
            idempotency_key=uuid4(),
            correction_id=correction,
            expected_outcome_id=identity,
            replacement_outcome_id=replacement,
            replacement_refund_number="LEDGER-" + replacement.hex,
            reason="Correct duplicated external processing reference",
            evidence_reference="Synthetic coordinated evidence",
        )
        assert corrected is not None
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition()
        assert connection.execute(
            (
                "SELECT refund_id,source_balance_effect_usd_cents FROM "
                "app.refund_corrections WHERE id=%s"
            ),
            (correction,),
        ).fetchone() == (identity, initial.security_deposit)
        events = history(connection, customer)
        assert len([e for e in events if e["event_kind"] == "REFUND_PAID"]) == 2
        assert len([e for e in events if e["event_kind"] == "REFUND_CORRECTED"]) == 1
        # V1-056 sub-slice 8a-1: both tables exist since migration 86; this Customer still has
        # no Final Settlement and no Deposit application.
        assert connection.execute(
            "SELECT (SELECT count(*) FROM app.final_settlements settlement JOIN app.leases lease "
            "ON lease.id=settlement.lease_id WHERE lease.primary_tenant_id=%s),"
            "(SELECT count(*) FROM app.deposit_applications application JOIN app.deposits d "
            "ON d.id=application.deposit_id WHERE d.customer_id=%s)",
            (customer, customer),
        ).fetchone() == (0, 0)


def test_ledger_qualified_pet_refund_and_return_are_distinct_from_credit(
    migrated_database_url: str,  # noqa: F811
) -> None:
    from test_pet_refund_migration import command as pet_command
    from test_pet_refund_migration import qualified

    human, prop, customer, _, deposit, review = qualified(migrated_database_url)
    paid = create_pet_refund(
        refunds(),
        prop,
        pet_command(deposit, review, 15000),
        actor=actor(human, prop, "refunds.create"),
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition(pet_deposit=5000)
    refunds().verify_usd_return(
        prop, refund_id(paid), returned(2000), actor=actor(human, prop, "refunds.correct")
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert assert_reconciled(connection, customer) == LedgerPosition(pet_deposit=7000)


# The canonical fixture owns only these two rates; other suites share its Property.
FIXTURE_TRASH_RATE_DATES = (date(2026, 7, 1), date(2026, 8, 1))


def test_ledger_canonical_fixture_preserves_shared_billing_service_rates(
    migrated_database_url: str,  # noqa: F811
) -> None:
    _, prop, _, _, _, _ = canonical_invoice(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        before = connection.execute(
            "SELECT r.id,r.effective_date,r.monthly_rate_usd_cents FROM app.service_rates r "
            "JOIN app.property_services s ON s.id=r.property_service_id "
            "WHERE s.property_id=%s AND s.service_code='TRASH_COLLECTION' "
            "AND r.effective_date IN (%s,%s) ORDER BY r.effective_date",
            (prop, *FIXTURE_TRASH_RATE_DATES),
        ).fetchall()
        assert [(row[1], row[2]) for row in before] == [
            (date(2026, 7, 1), 1000),
            (date(2026, 8, 1), 1200),
        ]
        setup_billing_source(connection)
        after = connection.execute(
            "SELECT r.id,r.effective_date,r.monthly_rate_usd_cents FROM app.service_rates r "
            "JOIN app.property_services s ON s.id=r.property_service_id "
            "WHERE s.property_id=%s AND s.service_code='TRASH_COLLECTION' "
            "AND r.effective_date IN (%s,%s) ORDER BY r.effective_date",
            (prop, *FIXTURE_TRASH_RATE_DATES),
        ).fetchall()
        assert after == before
