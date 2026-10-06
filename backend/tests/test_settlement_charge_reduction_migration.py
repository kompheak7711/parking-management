"""Post-settlement correction: charge reduction (V1-056 sub-slice 10c-1a).

BR-SETTLE-013 (owner answer 1 to Q-2026-10-06-36): a wrong charge that is still unpaid after a
Final Settlement closes has a clear fix, a CHARGE_REDUCTION correction. Staff record it under
final_settlements.prepare with a reason; only a financial.approve holder confirms it
(BR-AUTH-010). The confirmation writes a credit Adjustment of the wrong Invoice line, linked to the
correction (DB-SETTLE-005), on the Invoice's Customer (BR-INV-045). It removes only the unpaid
rest: releasing paid value is a REFUND correction. The closed Settlement is never changed
(BR-SETTLE-012).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from property_rental.final_settlement import (
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementKeyReused,
    FinalSettlementNotFoundError,
    FinalSettlementStaleDraftError,
)
from property_rental.invoice import CreateInvoiceDraftCommand, InvoiceConflictError
from property_rental.settlement_correction import RecordChargeReductionCorrectionCommand
from test_final_settlement_closed_refusal_migration import close, closed_refusal
from test_final_settlement_draft_migration import leaving_case
from test_final_settlement_migration import (
    another_signer_invoice,
    apply,
    line_of,
    one,
    outstanding,
    preparer,
    start,
)
from test_final_settlement_preview_migration import credit_adjustment, key_card, pay
from test_invoice_migration import register_billing_service_principal
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_one_time_charges_migration import invoices
from test_one_time_charges_migration import staff as invoice_staff
from test_settlement_correction_migration import approver, count, settlement_row
from test_settlement_extra_charge_migration import (
    approving,
    cause,
    corrections,
    extra_charge,
    ledger_events,
    state,
)
from test_settlement_extra_charge_migration import record as record_extra_charge
from test_unpaid_initial_termination_migration import rent_line

RECORD = "app.record_settlement_charge_reduction_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_charge_reduction(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.settlement_charge_reduction_input(jsonb)",
    "app.settlement_charge_reduction_source_state(uuid,uuid,uuid)",
    "app.settlement_charge_reduction_plan(uuid,uuid,jsonb)",
    "app.settlement_charge_reduction_result(uuid)",
)
REASON = "The window latch was charged at the wrong amount"
RELEASE = "The charge reduction would release paid value"


def invoice_of(url: str, line: UUID) -> UUID:
    return UUID(str(one(url, "SELECT invoice_id FROM app.invoice_lines WHERE id=%s", line)[0]))


def reduction(
    settlement: UUID, invoice: UUID, line: UUID, amount: int, **changes: Any
) -> RecordChargeReductionCorrectionCommand:
    return replace(
        RecordChargeReductionCorrectionCommand(uuid4(), settlement, invoice, line, amount, REASON),
        **changes,
    )


def record(case: dict[str, Any], command: RecordChargeReductionCorrectionCommand) -> UUID:
    found = corrections().record_charge_reduction(
        case["prop"], command, actor=preparer(case["human"], case["prop"])
    )
    return UUID(str(found["draft_id"]))


def adjustments(url: str, line: UUID) -> int:
    return count(url, "SELECT count(*) FROM app.invoice_adjustments WHERE invoice_line_id=%s", line)


def test_a_charge_reduction_removes_an_unpaid_wrong_charge_through_a_linked_credit_adjustment(
    migrated_database_url: str,
) -> None:
    """Owner answer 1 to Q-2026-10-06-36: Staff record the reduction as a draft with no effect;
    Staff cannot confirm it; a financial.approve holder confirms it, which writes a credit
    Adjustment of the unpaid line, linked to a correction with the draft's reason, on the Invoice
    Customer's ledger; the Settlement row and its snapshots stay unchanged; an exact repeat
    replays. An open Settlement, an Invoice that is not this Settlement's issued obligation, a
    line of another Invoice and a reduction of paid value are refused; the one-call Adjustment
    stays refused after closure."""
    url = migrated_database_url
    case = leaving_case(url)
    prop, human, lease, customer = case["prop"], case["human"], case["lease"], case["customer"]
    person = approver(url)
    line = case["other_line"]
    invoice = invoice_of(url, line)
    command = reduction(case["settlement"], invoice, line, 2_500)
    with pytest.raises(FinalSettlementConflictError) as still_open:
        record(case, command)
    assert cause(still_open) == (
        "55000",
        "A post-settlement correction needs a closed Final Settlement",
    )
    # A DRAFT Invoice of the Lease, made before the closure, is not a Settlement obligation.
    lease_charge = key_card(customer, lease)
    invoices().record_one_time_charge(prop, lease_charge, actor=invoice_staff(human, prop))
    lease_draft = UUID(
        str(
            invoices().create_draft(
                prop,
                CreateInvoiceDraftCommand(uuid4(), lease_charge.charge_id),
                actor=invoice_staff(human, prop),
            )["id"]
        )
    )
    close(url, human, case["settlement"])
    with pytest.raises(FinalSettlementConflictError) as unissued:
        record(case, reduction(case["settlement"], lease_draft, line_of(url, lease_draft), 100))
    assert cause(unissued) == (
        "55000",
        "The reduced Invoice is not an issued obligation of this Final Settlement",
    )
    # The database refuses malformed input on its own and writes no draft.
    drafts_before = count(url, "SELECT count(*) FROM app.financial_drafts")
    good = command.reduction()
    for malformed in (
        {**good, "surprise": True},
        {**good, "amount_usd_cents": 9_000_000_000_000_001},
        {**good, "amount_usd_cents": "2500"},
        {**good, "amount_usd_cents": 2_500.5},
        {**good, "amount_usd_cents": 0},
        {**good, "invoice_line_id": None},
        {**good, "invoice_id": str(UUID(int=0))},
    ):
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            connection.execute(
                "SELECT app.record_settlement_charge_reduction_draft(%s,%s,%s,%s,%s,%s,"
                "'final_settlements.prepare')",
                (prop, human, uuid4(), case["settlement"], Jsonb(malformed), REASON),
            )
        assert refused.value.sqlstate == "22023", malformed
    assert count(url, "SELECT count(*) FROM app.financial_drafts") == drafts_before
    other = leaving_case(url)
    foreign_line = other["other_line"]
    with pytest.raises(FinalSettlementNotFoundError) as foreign:
        record(
            case,
            reduction(case["settlement"], invoice_of(url, foreign_line), foreign_line, 100),
        )
    assert cause(foreign) == (
        "P0002",
        "The reduced Invoice is not an Invoice of this Final Settlement",
    )
    with pytest.raises(FinalSettlementNotFoundError) as elsewhere:
        record(case, reduction(case["settlement"], invoice, case["pet_line"], 100))
    assert cause(elsewhere) == ("P0002", "Invoice line was not found")
    # More than the unpaid rest, or any part of a paid line, would release paid value: a REFUND.
    with pytest.raises(FinalSettlementConflictError) as too_much:
        record(case, reduction(case["settlement"], invoice, line, 12_501))
    assert cause(too_much) == ("55000", RELEASE)
    rent, _ = rent_line(url, case["initial"])
    assert outstanding(url, rent) == 0
    with pytest.raises(FinalSettlementConflictError) as paid:
        record(case, reduction(case["settlement"], case["initial"], rent, 1))
    assert cause(paid) == ("55000", RELEASE)

    before = settlement_row(url, case["settlement"])
    draft = record(case, command)
    assert state(url, draft) == "PENDING"
    assert adjustments(url, line) == 0
    assert one(
        url,
        "SELECT kind,prepare_capability,reason,payload->>'variant',payload->>'customer_id',"
        "payload->'reduction'->>'amount_usd_cents' FROM app.financial_drafts WHERE id=%s",
        draft,
    ) == (
        "SETTLEMENT_CORRECTION",
        "final_settlements.prepare",
        REASON,
        "CHARGE_REDUCTION",
        str(customer),
        "2500",
    )
    # Staff cannot confirm: the service refuses before any connection, and the database refuses
    # any other authorization reference; the recorder takes only final_settlements.prepare.
    with pytest.raises(FinalSettlementAuthorizationError):
        corrections().confirm_charge_reduction(prop, draft, actor=preparer(human, prop))
    with pytest.raises(psycopg.Error) as staff, psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.confirm_settlement_charge_reduction(%s,%s,%s,%s)",
            (prop, human, draft, "final_settlements.prepare"),
        )
    assert staff.value.sqlstate == "42501"
    drafts_before = count(url, "SELECT count(*) FROM app.financial_drafts")
    for authorization in ("financial.approve", "invoices.adjust", None):
        with pytest.raises(psycopg.Error) as recorder, psycopg.connect(url) as connection:
            connection.execute(
                "SELECT app.record_settlement_charge_reduction_draft(%s,%s,%s,%s,%s,%s,%s)",
                (prop, human, uuid4(), case["settlement"], Jsonb(good), REASON, authorization),
            )
        assert recorder.value.sqlstate == "42501", authorization
    assert count(url, "SELECT count(*) FROM app.financial_drafts") == drafts_before
    assert state(url, draft) == "PENDING"

    result = corrections().confirm_charge_reduction(prop, draft, actor=approving(person, prop))
    header = cast(dict[str, Any], result["settlement_correction"])
    adjustment = UUID(str(cast(dict[str, Any], result["invoice_adjustment"])["id"]))
    correction = UUID(str(header["id"]))
    decision = cast(dict[str, Any], cast(dict[str, Any], result["draft"])["decision"])
    assert decision["decision"] == "CONFIRMED" and "transaction_id" not in decision["result"]
    assert one(
        url,
        "SELECT invoice_id,invoice_line_id,adjustment_type,amount_usd_cents,source_reference,"
        "reason,actor_id,authorization_reference FROM app.invoice_adjustments WHERE id=%s",
        adjustment,
    ) == (
        invoice,
        line,
        "CREDIT",
        2_500,
        f"settlement-correction:{correction}",
        REASON,
        person,
        "financial.approve",
    )
    assert outstanding(url, line) == 10_000
    assert one(url, "SELECT status FROM app.invoices WHERE id=%s", invoice) == ("UNPAID",)
    assert (header["final_settlement_id"], header["reason"], header["actor_id"]) == (
        str(case["settlement"]),
        REASON,
        str(person),
    )
    with psycopg.connect(url) as connection:
        effects = connection.execute(
            "SELECT effect_sequence,invoice_adjustment_id FROM app.settlement_correction_effects "
            "WHERE settlement_correction_id=%s ORDER BY effect_sequence",
            (correction,),
        ).fetchall()
        audits = connection.execute(
            "SELECT action,authorization_reference FROM app.audit_events "
            "WHERE correlation_id=%s ORDER BY action",
            (correction,),
        ).fetchall()
    assert effects == [(1, adjustment)]
    assert audits == [
        ("final_settlement.correction.confirmed", "financial.approve"),
        ("invoice.adjusted", "financial.approve"),
    ]
    # The reduction is on the Invoice Customer's Customer Ledger.
    assert [
        event["invoice_effect_usd_cents"] for event in ledger_events(url, customer, invoice)
    ] == [12_500, -2_500]
    assert settlement_row(url, case["settlement"]) == before
    assert state(url, draft) == "CONFIRMED"
    # An exact repeat by the same approver replays; the recorder's replay leaves the transaction
    # id out; another approver finds the draft decided.
    assert corrections().confirm_charge_reduction(prop, draft, actor=approving(person, prop)) == (
        result
    )
    replayed = corrections().record_charge_reduction(prop, command, actor=preparer(human, prop))
    assert replayed["state"] == "CONFIRMED"
    assert "transaction_id" not in cast(
        dict[str, Any], cast(dict[str, Any], replayed["decision"])["result"]
    )
    with pytest.raises(FinalSettlementConflictError):
        corrections().confirm_charge_reduction(prop, draft, actor=approving(human, prop))
    assert adjustments(url, line) == 1
    # The one-call credit Adjustment is not linked, so the 8e-1 refusal still holds.
    closed_refusal(InvoiceConflictError, credit_adjustment, url, human, prop, invoice, line)
    assert adjustments(url, line) == 1


def test_a_partly_paid_line_is_reduced_within_its_unpaid_rest_and_a_changed_line_is_stale(
    migrated_database_url: str,
) -> None:
    """After closure the Customer may still pay (owner answer 7 to Q-2026-10-05-20): a partly
    paid line is reduced by at most its unpaid rest. A draft whose line changed since it was
    recorded (another reduction, or a Payment that would make it release paid value) is stale and
    stays pending; the confirm runs only at READ COMMITTED; a reused draft key is refused."""
    url = migrated_database_url
    case = leaving_case(url)
    prop, human, customer = case["prop"], case["human"], case["customer"]
    person = approver(url)
    close(url, human, case["settlement"])
    line = case["other_line"]
    invoice = invoice_of(url, line)
    pay(url, prop, human, customer, invoice, line, 5_000)
    assert outstanding(url, line) == 7_500
    with pytest.raises(FinalSettlementConflictError) as too_much:
        record(case, reduction(case["settlement"], invoice, line, 7_501))
    assert cause(too_much) == ("55000", RELEASE)
    command = reduction(case["settlement"], invoice, line, 7_500)
    first = record(case, command)
    assert record(case, command) == first
    with pytest.raises(FinalSettlementKeyReused):
        record(case, replace(command, amount_usd_cents=7_499))
    second = record(case, replace(command, idempotency_key=uuid4(), amount_usd_cents=3_000))
    with pytest.raises(psycopg.Error) as isolation, psycopg.connect(url) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        connection.execute(
            "SELECT app.confirm_settlement_charge_reduction(%s,%s,%s,'financial.approve')",
            (prop, person, first),
        )
    assert (isolation.value.sqlstate, isolation.value.diag.message_primary) == (
        "55000",
        "A post-settlement correction is confirmed at READ COMMITTED",
    )
    assert state(url, first) == "PENDING"
    corrections().confirm_charge_reduction(prop, first, actor=approving(person, prop))
    assert outstanding(url, line) == 0
    assert one(url, "SELECT status FROM app.invoices WHERE id=%s", invoice) == ("PAID",)
    with pytest.raises(FinalSettlementStaleDraftError) as stale:
        corrections().confirm_charge_reduction(prop, second, actor=approving(person, prop))
    assert cause(stale)[0] == "P5S02"
    assert state(url, second) == "PENDING"
    with pytest.raises(FinalSettlementConflictError) as paid:
        record(case, reduction(case["settlement"], invoice, line, 1))
    assert cause(paid) == ("55000", RELEASE)
    # A Payment after the draft would make the reduction release paid value: stale, and the
    # line keeps the Payment and no Adjustment.
    pet_line = case["pet_line"]
    pet_invoice = invoice_of(url, pet_line)
    third = record(case, reduction(case["settlement"], pet_invoice, pet_line, 2_000))
    pay(url, prop, human, customer, pet_invoice, pet_line, 12_500)
    with pytest.raises(FinalSettlementStaleDraftError):
        corrections().confirm_charge_reduction(prop, third, actor=approving(person, prop))
    assert state(url, third) == "PENDING"
    assert outstanding(url, pet_line) == 0
    assert adjustments(url, pet_line) == 0


def test_an_invoice_paid_by_a_deposit_application_takes_no_charge_reduction_yet(
    migrated_database_url: str,
) -> None:
    """The 8a-1 refusal stays until sub-slice 10c-2: an Invoice that a Deposit application paid
    takes no Adjustment, also not a reduction of its unpaid rest."""
    url = migrated_database_url
    case = leaving_case(url)
    prop, human = case["prop"], case["human"]
    line = case["pet_line"]
    apply(
        url,
        prop,
        human,
        case["settlement"],
        case["pet"],
        "PET_RELATED_FIRST",
        "INVOICE_LINE",
        line,
        1_000,
        1,
    )
    close(url, human, case["settlement"])
    assert outstanding(url, line) == 11_500
    with pytest.raises(FinalSettlementConflictError) as deposit:
        record(case, reduction(case["settlement"], invoice_of(url, line), line, 500))
    assert cause(deposit) == (
        "55000",
        "A Deposit application paid this obligation at Final Settlement",
    )
    assert adjustments(url, line) == 0


def test_another_signers_reduction_stays_on_that_signer_and_the_variants_do_not_cross(
    migrated_database_url: str,
) -> None:
    """BR-INV-045 and BR-SETTLE-016: a reduction of another Signer's Invoice is that Signer's
    Adjustment and stays on that Signer's ledger (review round 1). One variant's confirm refuses
    the other variant's draft, and a draft key used by one variant is refused for the other. An
    unknown Property and a service identity cannot confirm (BR-AUTH-010)."""
    url = migrated_database_url
    f = another_signer_invoice(url)
    prop, human, lease, tenant, co_signer = (
        f["prop"],
        f["human"],
        f["lease"],
        f["tenant"],
        f["co_signer"],
    )
    settlement = start(prop, human, lease)
    close(url, human, settlement)
    case = {"prop": prop, "human": human}
    person = approver(url)
    invoice = UUID(str(f["invoice"]))
    line = line_of(url, invoice)
    assert outstanding(url, line) == 2_500
    command = reduction(settlement, invoice, line, 1_000)
    draft = record(case, command)
    assert one(
        url, "SELECT payload->>'customer_id' FROM app.financial_drafts WHERE id=%s", draft
    ) == (str(co_signer),)
    # The confirms do not cross: each refuses the other variant's draft as not found.
    extra = record_extra_charge(case, extra_charge(settlement))
    with pytest.raises(FinalSettlementNotFoundError) as crossed:
        corrections().confirm_charge_reduction(prop, extra, actor=approving(person, prop))
    assert cause(crossed) == ("P0002", "Post-settlement correction draft was not found")
    with pytest.raises(FinalSettlementNotFoundError) as reverse:
        corrections().confirm_extra_charge(prop, draft, actor=approving(person, prop))
    assert cause(reverse) == ("P0002", "Post-settlement correction draft was not found")
    assert (state(url, extra), state(url, draft)) == ("PENDING", "PENDING")
    # A draft key of one variant is refused for the other.
    with pytest.raises(FinalSettlementKeyReused):
        corrections().record_extra_charge(
            prop,
            extra_charge(settlement, idempotency_key=command.idempotency_key),
            actor=preparer(human, prop),
        )
    # An unknown Property, and a service identity that is not a person, cannot confirm.
    stranger = uuid4()
    with pytest.raises(FinalSettlementNotFoundError) as unknown:
        corrections().confirm_charge_reduction(stranger, draft, actor=approving(person, stranger))
    assert cause(unknown)[0] == "P4501"
    with psycopg.connect(url) as connection:
        service = register_billing_service_principal(connection, property_id=prop, created_by=human)
    with pytest.raises(FinalSettlementAuthorizationError) as machine:
        corrections().confirm_charge_reduction(prop, draft, actor=approving(service, prop))
    assert cause(machine)[0] == "P4506"
    assert state(url, draft) == "PENDING"

    result = corrections().confirm_charge_reduction(prop, draft, actor=approving(person, prop))
    adjustment = UUID(str(cast(dict[str, Any], result["invoice_adjustment"])["id"]))
    assert one(
        url,
        "SELECT invoice.customer_id,adjustment.amount_usd_cents FROM app.invoice_adjustments "
        "adjustment JOIN app.invoices invoice ON invoice.id=adjustment.invoice_id "
        "WHERE adjustment.id=%s",
        adjustment,
    ) == (co_signer, 1_000)
    assert outstanding(url, line) == 1_500
    assert [
        event["invoice_effect_usd_cents"] for event in ledger_events(url, co_signer, invoice)
    ] == [2_500, -1_000]
    assert ledger_events(url, tenant, invoice) == []


def test_charge_reduction_functions_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (RECORD, CONFIRM, *INTERNAL):
            definer, settings = cast(
                tuple[bool, list[str]],
                connection.execute(
                    "SELECT prosecdef,proconfig FROM pg_catalog.pg_proc "
                    "WHERE oid=CAST(%s AS regprocedure)",
                    (function,),
                ).fetchone(),
            )
            assert definer and "search_path=pg_catalog" in settings, function
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                allowed = role == "prm_financial" and function in (RECORD, CONFIRM)
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (allowed,), (role, function)
            # BR-SETTLE-013, no time limit: no age or deadline in the 10c-1a functions.
            source = connection.execute(
                "SELECT prosrc FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure", (function,)
            ).fetchone()
            assert source is not None
            assert "interval" not in str(source[0]) and "age(" not in str(source[0]), function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261103_99")
    assert revision is not None and revision.down_revision == "20261102_98"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, object], set[str]]:
        with psycopg.connect(database) as connection:
            functions = {
                str(row[0]): row[1]
                for row in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid) "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ).fetchall()
            }
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT c.oid::regclass::text FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND c.relkind IN ('r','v','m','p')"
                ).fetchall()
            }
        return functions, tables

    with _temporary_migration_database("settlement_charge_reduction") as temporary:
        alembic_command.upgrade(config, "20261102_98")
        before_functions, before_tables = catalog(temporary)
        alembic_command.upgrade(config, "20261103_99")
        after_functions, after_tables = catalog(temporary)
    assert after_tables == before_tables
    assert set(after_functions) - set(before_functions) == {RECORD, CONFIRM, *INTERNAL}
    # Additive: no earlier function changes.
    assert all(after_functions[name] == before_functions[name] for name in before_functions)
