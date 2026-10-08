"""Post-settlement correction: extra charge (V1-056 sub-slice 10b).

BR-SETTLE-013 (owner answers to Q-2026-10-06-36 and Q-2026-10-06-37): a missed amount after a
Final Settlement closes is billed by an EXTRA_CHARGE correction. Staff record it under
final_settlements.prepare with a reason; only a financial.approve holder confirms it
(BR-AUTH-010). The confirmation writes a one-time charge record (BR-INV-044) and its issued
Invoice with the Lease, both linked to the correction (DB-SETTLE-005), to the Customer of the
corrected Invoice or the Primary Tenant (BR-SETTLE-016), with the one-time charge Due Date. The
closed Settlement is never changed (BR-SETTLE-012) and no Late-payment Charge follows.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
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
from property_rental.identity import AuthenticatedActor
from property_rental.invoice import CreateInvoiceDraftCommand, InvoiceConflictError
from property_rental.move_out_inspection import InspectionFinding, RecordMoveOutInspection
from property_rental.settlement_correction import (
    ExtraChargeCategory,
    RecordExtraChargeCorrectionCommand,
    SettlementCorrectionService,
)
from test_customer_ledger_migration import assert_reconciled, history
from test_final_settlement_closed_refusal_migration import (
    CLOSED,
    ONE_TIME_CHARGE,
    close,
    closed_refusal,
    no_lease_charge,
    one_time_charge_row,
    owner_refusal,
)
from test_final_settlement_draft_migration import leaving_case
from test_final_settlement_migration import another_signer_invoice, one, preparer, start, today
from test_final_settlement_preview_migration import key_card
from test_invoice_migration import financial_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_out_inspection_migration import actor as inspection_actor
from test_move_out_inspection_migration import flow as inspection_flow
from test_one_time_charges_migration import invoices
from test_one_time_charges_migration import staff as invoice_staff
from test_settlement_correction_migration import (
    BEGIN,
    LATE_EFFECT,
    LINK,
    NOT_CONFIRMED,
    approver,
    correction_draft,
    count,
    settlement_row,
)
from test_settlement_correction_migration import REASON as CORRECTION_REASON

RECORD = "app.record_settlement_extra_charge_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_extra_charge(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.assert_settlement_correction_invoice_issued()",
    "app.settlement_extra_charge_input(jsonb)",
    "app.settlement_extra_charge_source_state(uuid,uuid,uuid)",
    "app.settlement_extra_charge_plan(uuid,uuid,jsonb,date)",
    "app.settlement_extra_charge_result(uuid)",
)
CHANGED = (
    "app.refuse_closed_final_settlement_change()",
    "app.settlement_correction_linked(uuid,text,uuid)",
    "app.link_settlement_correction_effect(uuid,text,uuid)",
)
REASON = "The replacement key card was missed at the Final Settlement"
NOT_ISSUED = "An Invoice linked to a post-settlement correction must be issued"


def corrections() -> SettlementCorrectionService:
    return SettlementCorrectionService(financial_database_url())


def approving(person: UUID, prop: UUID) -> AuthenticatedActor:
    return preparer(person, prop, "financial.approve")


def extra_charge(settlement: UUID, **changes: Any) -> RecordExtraChargeCorrectionCommand:
    return replace(
        RecordExtraChargeCorrectionCommand(
            uuid4(),
            settlement,
            ExtraChargeCategory.MISCELLANEOUS_CHARGES,
            "Replacement key card",
            1_500,
            "Front desk log 7",
            REASON,
        ),
        **changes,
    )


def record(case: dict[str, Any], command: RecordExtraChargeCorrectionCommand) -> UUID:
    found = corrections().record_extra_charge(
        case["prop"], command, actor=preparer(case["human"], case["prop"])
    )
    return UUID(str(found["draft_id"]))


def state(url: str, draft: UUID) -> str:
    return str(
        one(
            url,
            "SELECT COALESCE((SELECT decision FROM app.financial_draft_decisions "
            "WHERE draft_id=%s),'PENDING')",
            draft,
        )[0]
    )


def cause(failure: pytest.ExceptionInfo[Exception]) -> tuple[Any, Any]:
    """The database refusal behind a service error."""
    error = failure.value.__cause__
    assert isinstance(error, psycopg.Error)
    return error.sqlstate, error.diag.message_primary


def due_days(url: str, prop: UUID) -> int:
    return int(one(url, "SELECT one_time_charge_due_days FROM app.properties WHERE id=%s", prop)[0])


def ledger_events(url: str, customer: UUID, invoice: UUID) -> list[dict[str, object]]:
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)
        return [
            event for event in history(connection, customer) if event["invoice_id"] == str(invoice)
        ]


def test_an_extra_charge_is_a_new_issued_invoice_linked_to_the_closed_settlement(
    migrated_database_url: str,
) -> None:
    """BR-SETTLE-013 and owner answer 6: Staff record the extra charge as a draft with no effect;
    Staff cannot confirm it; a financial.approve holder confirms it, which writes the one-time
    charge record and its issued Invoice to the Primary Tenant (it corrects nothing on an Invoice),
    due on the issue date plus the Property's days, linked to a correction with the draft's
    reason, on the Customer Ledger; the Settlement row and its snapshots stay unchanged; an exact
    repeat replays and nothing is written twice."""
    url = migrated_database_url
    case = leaving_case(url)
    prop, human, lease, customer = case["prop"], case["human"], case["lease"], case["customer"]
    person = approver(url)
    # An open Settlement takes no correction.
    with pytest.raises(FinalSettlementConflictError) as still_open:
        record(case, extra_charge(case["settlement"]))
    assert cause(still_open) == (
        "55000",
        "A post-settlement correction needs a closed Final Settlement",
    )
    # A DRAFT Invoice of the Lease, made before the closure, is not a Settlement obligation.
    lease_charge = key_card(customer, lease)
    invoices().record_one_time_charge(prop, lease_charge, actor=invoice_staff(human, prop))
    lease_draft = invoices().create_draft(
        prop,
        CreateInvoiceDraftCommand(uuid4(), lease_charge.charge_id),
        actor=invoice_staff(human, prop),
    )["id"]
    close(url, human, case["settlement"])
    with pytest.raises(FinalSettlementConflictError) as unissued:
        record(case, extra_charge(case["settlement"], corrects_invoice_id=UUID(str(lease_draft))))
    assert cause(unissued) == (
        "55000",
        "The corrected Invoice is not an issued obligation of this Final Settlement",
    )
    # The database refuses malformed input on its own (review round 2), and writes no draft.
    drafts_before = count(url, "SELECT count(*) FROM app.financial_drafts")
    good = extra_charge(case["settlement"]).charge()
    for malformed in (
        {**good, "surprise": True},
        {**good, "amount_usd_cents": 9_000_000_000_000_001},
        {**good, "amount_usd_cents": "1500"},
        {**good, "amount_usd_cents": 15.5},
        {**good, "due_date": "2026-02-30", "due_date_reason": "Agreed with the Customer"},
        {**good, "due_date": "2026-10-30"},
        {**good, "description": " padded"},
    ):
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            connection.execute(
                "SELECT app.record_settlement_extra_charge_draft(%s,%s,%s,%s,%s,%s,"
                "'final_settlements.prepare')",
                (prop, human, uuid4(), case["settlement"], Jsonb(malformed), REASON),
            )
        assert refused.value.sqlstate == "22023", malformed
    assert count(url, "SELECT count(*) FROM app.financial_drafts") == drafts_before
    before = settlement_row(url, case["settlement"])
    invoices_before = count(url, "SELECT count(*) FROM app.invoices WHERE lease_id=%s", lease)
    command = extra_charge(case["settlement"])
    draft = record(case, command)
    assert state(url, draft) == "PENDING"
    assert count(url, "SELECT count(*) FROM app.invoices WHERE lease_id=%s", lease) == (
        invoices_before
    )
    stored = one(
        url,
        "SELECT kind,prepare_capability,reason,payload->>'variant',payload->>'customer_id',"
        "payload->'charge'->>'amount_usd_cents' FROM app.financial_drafts WHERE id=%s",
        draft,
    )
    assert stored == (
        "SETTLEMENT_CORRECTION",
        "final_settlements.prepare",
        REASON,
        "EXTRA_CHARGE",
        str(customer),
        "1500",
    )
    # Staff cannot confirm: the service refuses before any connection, and the database refuses
    # any other authorization reference.
    with pytest.raises(FinalSettlementAuthorizationError):
        corrections().confirm_extra_charge(prop, draft, actor=preparer(human, prop))
    with pytest.raises(psycopg.Error) as staff, psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.confirm_settlement_extra_charge(%s,%s,%s,%s)",
            (prop, human, draft, "final_settlements.prepare"),
        )
    assert staff.value.sqlstate == "42501"
    assert state(url, draft) == "PENDING"
    # The recorder takes only final_settlements.prepare (review round 1).
    drafts_before = count(url, "SELECT count(*) FROM app.financial_drafts")
    for authorization in ("financial.approve", "invoices.create", None):
        with pytest.raises(psycopg.Error) as recorder, psycopg.connect(url) as connection:
            connection.execute(
                "SELECT app.record_settlement_extra_charge_draft(%s,%s,%s,%s,%s,%s,%s)",
                (
                    prop,
                    human,
                    uuid4(),
                    case["settlement"],
                    Jsonb(extra_charge(case["settlement"]).charge()),
                    REASON,
                    authorization,
                ),
            )
        assert recorder.value.sqlstate == "42501", authorization
    assert count(url, "SELECT count(*) FROM app.financial_drafts") == drafts_before
    # Security review round 1: a one-time charge id a client could derive from the draft no
    # longer blocks the confirm; the records get fresh ids.
    derived = UUID(
        str(
            one(url, "SELECT md5('settlement-extra-charge-obligation:' || %s)::uuid", str(draft))[0]
        )
    )
    invoices().record_one_time_charge(
        prop,
        replace(no_lease_charge(customer), charge_id=derived),
        actor=invoice_staff(human, prop),
    )

    day = today(url)
    result = corrections().confirm_extra_charge(prop, draft, actor=approving(person, prop))
    invoice = cast(dict[str, Any], result["invoice"])
    charge = cast(dict[str, Any], result["one_time_charge"])
    header = cast(dict[str, Any], result["settlement_correction"])
    invoice_id = UUID(str(invoice["id"]))
    obligation = UUID(str(charge["obligation_id"]))
    assert obligation != derived
    # The decision's transaction id never leaves the database (review round 1).
    decision = cast(dict[str, Any], cast(dict[str, Any], result["draft"])["decision"])
    assert decision["decision"] == "CONFIRMED" and "transaction_id" not in decision["result"]
    row = one(
        url,
        "SELECT customer_id,lease_id,primary_category,status,original_total_usd_cents,"
        "invoice_date,due_date,due_date_rule,issued_by,due_date_override_reason "
        "FROM app.invoices WHERE id=%s",
        invoice_id,
    )
    assert row[:5] == (customer, lease, "MISCELLANEOUS_CHARGES", "UNPAID", 1_500)
    assert row[5] in (day, day + timedelta(days=1))
    assert row[6] == row[5] + timedelta(days=due_days(url, prop))
    assert row[7:] == ("ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS", person, None)
    assert one(
        url,
        "SELECT customer_id,lease_id,category,authorized_by,authorization_reference,reason,"
        "authorized_amount_usd_cents FROM app.authorized_nonrecurring_obligations WHERE id=%s",
        obligation,
    ) == (customer, lease, "MISCELLANEOUS_CHARGES", person, "financial.approve", REASON, 1_500)
    correction = UUID(str(header["id"]))
    assert (header["final_settlement_id"], header["reason"], header["actor_id"]) == (
        str(case["settlement"]),
        REASON,
        str(person),
    )
    with psycopg.connect(url) as connection:
        effects = connection.execute(
            "SELECT effect_sequence,authorized_nonrecurring_obligation_id,invoice_id "
            "FROM app.settlement_correction_effects WHERE settlement_correction_id=%s "
            "ORDER BY effect_sequence",
            (correction,),
        ).fetchall()
        audits = connection.execute(
            "SELECT action,authorization_reference FROM app.audit_events "
            "WHERE correlation_id=%s ORDER BY action",
            (correction,),
        ).fetchall()
    assert effects == [(1, obligation, None), (2, None, invoice_id)]
    assert audits == [
        ("final_settlement.correction.confirmed", "financial.approve"),
        ("invoice.created", "financial.approve"),
        ("invoice.issued", "financial.approve"),
        ("invoice.one_time_charge.recorded", "financial.approve"),
    ]
    # The debt is on the Primary Tenant's Customer Ledger (BR-SETTLE-016).
    assert [
        event["invoice_effect_usd_cents"] for event in ledger_events(url, customer, invoice_id)
    ] == [1_500]
    assert settlement_row(url, case["settlement"]) == before
    assert state(url, draft) == "CONFIRMED"
    # An exact repeat by the same approver replays; another approver finds the draft decided.
    assert corrections().confirm_extra_charge(prop, draft, actor=approving(person, prop)) == result
    # The recorder's replay of the decided draft leaves the transaction id out too (round 2).
    replayed = corrections().record_extra_charge(prop, command, actor=preparer(human, prop))
    replayed_decision = cast(dict[str, Any], replayed["decision"])
    assert replayed["state"] == "CONFIRMED"
    assert "transaction_id" not in cast(dict[str, Any], replayed_decision["result"])
    with pytest.raises(FinalSettlementConflictError):
        corrections().confirm_extra_charge(prop, draft, actor=approving(human, prop))
    assert count(url, "SELECT count(*) FROM app.invoices WHERE lease_id=%s", lease) == (
        invoices_before + 1
    )
    # Another draft kind is not an extra charge.
    other = correction_draft(url, case)
    with pytest.raises(FinalSettlementNotFoundError):
        corrections().confirm_extra_charge(prop, other, actor=approving(person, prop))


def test_an_extra_charge_for_another_signers_invoice_goes_to_that_signer(
    migrated_database_url: str,
) -> None:
    """Owner answer 6 and BR-SETTLE-016: a charge that corrects another Signer's Invoice goes to
    that Signer and stays on that Signer's ledger; a Damage charge goes only to the Primary Tenant;
    an Invoice of another Lease is not this Settlement's obligation."""
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
    draft = record(case, extra_charge(settlement, corrects_invoice_id=f["invoice"]))
    result = corrections().confirm_extra_charge(prop, draft, actor=approving(person, prop))
    invoice = UUID(str(cast(dict[str, Any], result["invoice"])["id"]))
    assert one(url, "SELECT customer_id,lease_id FROM app.invoices WHERE id=%s", invoice) == (
        co_signer,
        lease,
    )
    assert [
        event["invoice_effect_usd_cents"] for event in ledger_events(url, co_signer, invoice)
    ] == [1_500]
    assert ledger_events(url, tenant, invoice) == []
    with pytest.raises(FinalSettlementConflictError) as damage:
        record(
            case,
            extra_charge(
                settlement,
                category=ExtraChargeCategory.DAMAGE_CHARGES,
                inspection_damage_finding_id=uuid4(),
                corrects_invoice_id=f["invoice"],
            ),
        )
    assert cause(damage) == ("55000", "A Damage charge goes to the Primary Tenant")
    stranger = another_signer_invoice(url)
    with pytest.raises(FinalSettlementNotFoundError) as foreign:
        record(case, extra_charge(settlement, corrects_invoice_id=stranger["invoice"]))
    assert cause(foreign) == (
        "P0002",
        "The corrected Invoice is not an Invoice of this Final Settlement",
    )


def test_a_damage_extra_charge_bills_a_current_unbilled_finding_and_a_stale_draft_waits(
    migrated_database_url: str,
) -> None:
    """BR-INV-044: a Damage charge bills one current, unbilled inspection finding of the Lease,
    here found after closure; the authorized Due Date override is kept and never precedes the
    issue date. A second draft for the same finding becomes stale once the first is confirmed and
    stays pending; an already billed finding and a reused draft key are refused."""
    url = migrated_database_url
    case = leaving_case(url)
    prop, human, lease, customer = case["prop"], case["human"], case["lease"], case["customer"]
    person = approver(url)
    earlier = UUID(
        str(one(url, "SELECT id FROM app.move_out_inspections WHERE lease_id=%s", lease)[0])
    )
    version = int(one(url, "SELECT version FROM app.leases WHERE id=%s", lease)[0])
    # Set-up changed in sub-slice 10c-2a-4 (owner answers to Q-2026-10-08-49 and
    # Q-2026-10-08-50): a supersede after closure is now refused, so the closure-time inspection
    # is superseded before the Settlement closes (its billed findings are then not current), and
    # the damage found after closure is a separate inspection that supersedes nothing.
    inspection_flow().record(
        prop,
        lease,
        RecordMoveOutInspection(
            uuid4(),
            uuid4(),
            version,
            today(url),
            "Corrected inspection condition",
            "Approved inspection",
            "Evidence-901",
            "Inspection corrected before the Final Settlement closed",
            (),
            supersedes_inspection_id=earlier,
        ),
        actor=inspection_actor(human, prop),
        request_id="settlement-extra-charge-correction",
    )
    close(url, human, case["settlement"])
    finding = uuid4()
    inspection_flow().record(
        prop,
        lease,
        RecordMoveOutInspection(
            uuid4(),
            uuid4(),
            version,
            today(url),
            "Later inspection condition",
            "Approved inspection",
            "Evidence-902",
            "Cracked tile found after the Final Settlement",
            (InspectionFinding(finding, "Cracked bathroom tile", False),),
        ),
        actor=inspection_actor(human, prop),
        request_id="settlement-extra-charge-inspection",
    )
    superseded = UUID(
        str(
            one(
                url,
                "SELECT inspection_damage_finding_id FROM app.authorized_nonrecurring_obligations "
                "WHERE lease_id=%s AND inspection_damage_finding_id IS NOT NULL LIMIT 1",
                lease,
            )[0]
        )
    )
    damage: dict[str, Any] = {
        "category": ExtraChargeCategory.DAMAGE_CHARGES,
        "description": "Cracked bathroom tile",
        "amount_usd_cents": 8_000,
    }
    with pytest.raises(FinalSettlementConflictError) as old:
        record(
            case,
            extra_charge(case["settlement"], inspection_damage_finding_id=superseded, **damage),
        )
    assert cause(old) == ("55000", "The damage finding is not on the current inspection")
    with pytest.raises(FinalSettlementConflictError) as early:
        record(
            case,
            extra_charge(
                case["settlement"],
                inspection_damage_finding_id=finding,
                due_date=today(url) - timedelta(days=2),
                due_date_reason="Agreed with the Customer",
                **damage,
            ),
        )
    assert cause(early) == ("55000", "The extra charge Due Date precedes the issue date")
    due = today(url) + timedelta(days=30)
    command = extra_charge(
        case["settlement"],
        inspection_damage_finding_id=finding,
        due_date=due,
        due_date_reason="Agreed with the Customer",
        **damage,
    )
    first = record(case, command)
    assert record(case, command) == first
    with pytest.raises(FinalSettlementKeyReused):
        record(case, replace(command, amount_usd_cents=8_001))
    second = record(case, replace(command, idempotency_key=uuid4()))
    # The confirm runs only at READ COMMITTED, where its checks see what its locks waited for
    # (review round 1); the draft stays pending.
    with pytest.raises(psycopg.Error) as isolation, psycopg.connect(url) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        connection.execute(
            "SELECT app.confirm_settlement_extra_charge(%s,%s,%s,'financial.approve')",
            (prop, person, first),
        )
    assert (isolation.value.sqlstate, isolation.value.diag.message_primary) == (
        "55000",
        "A post-settlement correction is confirmed at READ COMMITTED",
    )
    assert state(url, first) == "PENDING"
    result = corrections().confirm_extra_charge(prop, first, actor=approving(person, prop))
    invoice = UUID(str(cast(dict[str, Any], result["invoice"])["id"]))
    assert one(
        url,
        "SELECT invoice.customer_id,invoice.primary_category,invoice.due_date,"
        "invoice.due_date_override_reason,invoice.due_date_set_by,"
        "obligation.inspection_damage_finding_id FROM app.invoices invoice "
        "JOIN app.invoice_lines line ON line.invoice_id=invoice.id "
        "JOIN app.authorized_nonrecurring_obligations obligation "
        "ON obligation.id=line.authorized_obligation_id WHERE invoice.id=%s",
        invoice,
    ) == (customer, "DAMAGE_CHARGES", due, "Agreed with the Customer", person, finding)
    with pytest.raises(FinalSettlementStaleDraftError) as stale:
        corrections().confirm_extra_charge(prop, second, actor=approving(person, prop))
    assert cause(stale)[0] == "P5S02"
    assert state(url, second) == "PENDING"
    with pytest.raises(FinalSettlementConflictError) as billed:
        record(case, replace(command, idempotency_key=uuid4()))
    assert cause(billed) == ("55000", "The damage finding is already billed")
    assert (
        count(
            url,
            "SELECT count(*) FROM app.authorized_nonrecurring_obligations "
            "WHERE inspection_damage_finding_id=%s",
            finding,
        )
        == 1
    )
    # The database also refuses a reason the one-time charge record cannot keep.
    with pytest.raises(psycopg.Error) as long_reason, psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.record_settlement_extra_charge_draft(%s,%s,%s,%s,%s,%s,"
            "'final_settlements.prepare')",
            (
                prop,
                human,
                uuid4(),
                case["settlement"],
                Jsonb(extra_charge(case["settlement"]).charge()),
                "x" * 501,
            ),
        )
    assert long_reason.value.sqlstate == "22023"
    # A Due Date override that was valid when recorded but precedes the issue date at the
    # confirm is a conflict, and the draft stays pending (review round 2). The table owner
    # records such a draft as the recorder would have done five days earlier.
    past = today(url) - timedelta(days=1)
    late = uuid4()
    with psycopg.connect(url) as connection:
        stored = connection.execute(
            "SELECT app.settlement_extra_charge_input(%s)",
            (
                Jsonb(
                    extra_charge(
                        case["settlement"],
                        due_date=past,
                        due_date_reason="Agreed with the Customer",
                    ).charge()
                ),
            ),
        ).fetchone()
        assert stored is not None
        planned = connection.execute(
            "SELECT app.settlement_extra_charge_plan(%s,%s,%s,%s)",
            (prop, case["settlement"], Jsonb(stored[0]), past - timedelta(days=4)),
        ).fetchone()
        assert planned is not None
        plan = cast(dict[str, Any], planned[0])
        connection.execute(
            "SELECT app.insert_financial_draft(%s,%s,%s,'SETTLEMENT_CORRECTION',"
            "'final_settlements.prepare',%s,%s,%s)",
            (
                prop,
                human,
                late,
                Jsonb(
                    {
                        "variant": "EXTRA_CHARGE",
                        "final_settlement_id": str(case["settlement"]),
                        "lease_id": plan["lease_id"],
                        "customer_id": plan["customer_id"],
                        "charge": plan["charge"],
                    }
                ),
                plan["source_revision"],
                REASON,
            ),
        )
    with pytest.raises(FinalSettlementConflictError) as overdue:
        corrections().confirm_extra_charge(prop, late, actor=approving(person, prop))
    assert cause(overdue) == ("55000", "The extra charge Due Date precedes the issue date")
    assert state(url, late) == "PENDING"


def test_no_late_payment_decision_and_unlinked_charges_stay_refused(
    migrated_database_url: str,
) -> None:
    """Owner answer 6: no Late-payment Charge on a correction Invoice (the 8e-1 refusal of
    Late-payment Decisions stays). The 8e-1 refusal still holds for a one-time charge with the
    closed Lease that is not linked, or linked to another Settlement's correction."""
    url = migrated_database_url
    case = leaving_case(url)
    other = leaving_case(url)
    prop, human, lease = case["prop"], case["human"], case["lease"]
    person = approver(url)
    for settled in (case, other):
        close(url, settled["human"], settled["settlement"])
    draft = record(case, extra_charge(case["settlement"]))
    result = corrections().confirm_extra_charge(prop, draft, actor=approving(person, prop))
    invoice = UUID(str(cast(dict[str, Any], result["invoice"])["id"]))
    assert owner_refusal(
        url,
        "INSERT INTO app.late_payment_decisions(id,source_invoice_id) VALUES (%s,%s)",
        uuid4(),
        invoice,
    ) == ("P5S01", CLOSED)
    assert owner_refusal(
        url,
        "INSERT INTO app.late_payment_charges(id,source_invoice_id) VALUES (%s,%s)",
        uuid4(),
        invoice,
    ) == ("P5S01", CLOSED)
    closed_refusal(
        InvoiceConflictError,
        invoices().record_one_time_charge,
        prop,
        key_card(case["customer"], lease),
        actor=invoice_staff(human, prop),
    )
    elsewhere = correction_draft(url, other)
    other_correction = UUID(str(one(url, "SELECT app.settlement_correction_id(%s)", elsewhere)[0]))
    charge = uuid4()
    with pytest.raises(psycopg.Error) as foreign, psycopg.connect(url) as connection:
        connection.execute(BEGIN, (other["prop"], person, elsewhere, "financial.approve"))
        connection.execute(
            LINK, (other_correction, "authorized_nonrecurring_obligation_id", charge)
        )
        connection.execute(ONE_TIME_CHARGE, one_time_charge_row(case, charge))
    assert (foreign.value.sqlstate, foreign.value.diag.message_primary) == ("P5S01", CLOSED)
    assert (
        count(
            url, "SELECT count(*) FROM app.authorized_nonrecurring_obligations WHERE id=%s", charge
        )
        == 0
    )


def test_a_linked_invoice_is_issued_before_commit_and_the_decision_must_be_this_transactions(
    migrated_database_url: str,
) -> None:
    """The commit check (10a security review round 2 note): a correction never commits with a
    linked Invoice still DRAFT, also when the check runs early under SET CONSTRAINTS. The
    decided_at bound (10a round 3 notes): a CONFIRMED decision carrying this transaction's id but
    written before the transaction started gives no effect, no link and no commit."""
    url = migrated_database_url
    case = leaving_case(url)
    prop, human, customer = case["prop"], case["human"], case["customer"]
    person = approver(url)
    close(url, human, case["settlement"])
    staff = invoice_staff(human, prop)
    free = no_lease_charge(customer)
    invoices().record_one_time_charge(prop, free, actor=staff)
    pending = UUID(
        str(
            invoices().create_draft(
                prop, CreateInvoiceDraftCommand(uuid4(), free.charge_id), actor=staff
            )["id"]
        )
    )
    for immediate in (False, True):
        draft = correction_draft(url, case)
        correction = UUID(str(one(url, "SELECT app.settlement_correction_id(%s)", draft)[0]))
        with pytest.raises(psycopg.Error) as linked, psycopg.connect(url) as connection:
            connection.execute(BEGIN, (prop, person, draft, "financial.approve"))
            connection.execute(LINK, (correction, "invoice_id", pending))
            if immediate:
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert (linked.value.sqlstate, linked.value.diag.message_primary) == ("23514", NOT_ISSUED)
        assert state(url, draft) == "PENDING"
    # Security review round 1: the check is positive, so a caller who makes it run at once, before
    # the linked Invoice is written, gets the refusal instead of using the check up.
    draft = correction_draft(url, case)
    correction = UUID(str(one(url, "SELECT app.settlement_correction_id(%s)", draft)[0]))
    with pytest.raises(psycopg.Error) as early, psycopg.connect(url) as connection:
        connection.execute(
            "SET CONSTRAINTS app.settlement_correction_effects_invoice_issued IMMEDIATE"
        )
        connection.execute(BEGIN, (prop, person, draft, "financial.approve"))
        connection.execute(LINK, (correction, "invoice_id", uuid4()))
    assert (early.value.sqlstate, early.value.diag.message_primary) == ("23514", NOT_ISSUED)
    assert state(url, draft) == "PENDING"

    draft = correction_draft(url, case)
    header = uuid4()
    effect = (
        "INSERT INTO app.settlement_correction_effects(id,settlement_correction_id,effect_sequence,"
        "invoice_id) VALUES (%s,%s,1,%s)"
    )
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.financial_draft_decisions(draft_id,decision,decided_at,decided_by,"
            "authorization_reference,result) VALUES (%s,'CONFIRMED',"
            "transaction_timestamp()-interval '1 second',%s,'financial.approve',"
            "jsonb_build_object('transaction_id',pg_current_xact_id()::text))",
            (draft, person),
        )
        connection.execute(
            "INSERT INTO app.settlement_corrections(id,final_settlement_id,reason,occurred_at,"
            "actor_id,authorization_reference,correlation_id) VALUES (%s,%s,%s,clock_timestamp(),"
            "%s,'financial.approve',%s)",
            (header, case["settlement"], CORRECTION_REASON, person, draft),
        )
        connection.execute("SAVEPOINT effect")
        with pytest.raises(psycopg.Error) as late:
            connection.execute(effect, (uuid4(), header, case["initial"]))
        assert (late.value.sqlstate, late.value.diag.message_primary) == ("23514", LATE_EFFECT)
        connection.execute("ROLLBACK TO SAVEPOINT effect")
        # The table owner disables the effect check in this transaction only, to reach the link
        # check and the commit check; the transaction is always rolled back below.
        connection.execute(
            "ALTER TABLE app.settlement_correction_effects "
            "DISABLE TRIGGER settlement_correction_effects_validate"
        )
        connection.execute(effect, (uuid4(), header, case["initial"]))
        assert connection.execute(
            "SELECT app.settlement_correction_linked(%s,'invoices',%s)",
            (case["settlement"], case["initial"]),
        ).fetchone() == (False,)
        # The commit check, run now so the transaction never commits.
        with pytest.raises(psycopg.Error) as bound:
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        connection.rollback()
    assert (bound.value.sqlstate, bound.value.diag.message_primary) == ("42501", NOT_CONFIRMED)
    # The rollback kept the effect check enabled.
    with psycopg.connect(url) as connection:
        assert connection.execute(
            "SELECT tgenabled FROM pg_catalog.pg_trigger "
            "WHERE tgname='settlement_correction_effects_validate'"
        ).fetchone() == ("O",)
    assert count(url, "SELECT count(*) FROM app.settlement_corrections WHERE id=%s", header) == 0
    assert state(url, draft) == "PENDING"


def test_extra_charge_functions_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (RECORD, CONFIRM, *INTERNAL, *CHANGED):
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
        assert connection.execute(
            "SELECT tgdeferrable,tginitdeferred FROM pg_catalog.pg_trigger "
            "WHERE tgrelid='app.settlement_correction_effects'::regclass "
            "AND tgname='settlement_correction_effects_invoice_issued'"
        ).fetchone() == (True, True)
        assert connection.execute(
            "SELECT condeferrable,condeferred,confrelid::regclass::text "
            "FROM pg_catalog.pg_constraint "
            "WHERE conrelid='app.settlement_correction_effects'::regclass AND contype='f' "
            "AND conkey=ARRAY[(SELECT attnum FROM pg_catalog.pg_attribute WHERE "
            "attrelid='app.settlement_correction_effects'::regclass "
            "AND attname='authorized_nonrecurring_obligation_id')]"
        ).fetchone() == (True, True, "app.authorized_nonrecurring_obligations")
        # The new link is unique and inside the one-link check (review round 2).
        assert connection.execute(
            "SELECT count(*) FROM pg_catalog.pg_constraint "
            "WHERE conrelid='app.settlement_correction_effects'::regclass AND contype='u' "
            "AND conkey=ARRAY[(SELECT attnum FROM pg_catalog.pg_attribute WHERE "
            "attrelid='app.settlement_correction_effects'::regclass "
            "AND attname='authorized_nonrecurring_obligation_id')]"
        ).fetchone() == (1,)
        one_link = connection.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_catalog.pg_constraint "
            "WHERE conname='settlement_correction_effect_one_link'"
        ).fetchone()
        assert one_link is not None and "authorized_nonrecurring_obligation_id" in str(one_link[0])
        # BR-SETTLE-013, no time limit: the 10b functions carry no age or deadline either.
        for function in (RECORD, CONFIRM, *INTERNAL):
            source = connection.execute(
                "SELECT prosrc FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure", (function,)
            ).fetchone()
            assert source is not None
            assert "interval" not in str(source[0]) and "age(" not in str(source[0]), function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261102_98")
    assert revision is not None and revision.down_revision == "20261101_97"
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

    with _temporary_migration_database("settlement_extra_charge") as temporary:
        alembic_command.upgrade(config, "20261101_97")
        before_functions, before_tables = catalog(temporary)
        alembic_command.upgrade(config, "20261102_98")
        after_functions, after_tables = catalog(temporary)
    assert after_tables == before_tables
    assert set(after_functions) - set(before_functions) == {RECORD, CONFIRM, *INTERNAL}
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set(CHANGED)
