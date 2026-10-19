"""Post-settlement correction: FORFEITURE_REVERSAL (V1-056 sub-slice 10d).

Owner answer 4 to Q-2026-10-06-36: after a Lease's Final Settlement is closed, the reversal of a
kept Deposit's forfeiture runs only inside a correction of that Settlement, which follows DL-032:
the reversal puts the forfeited money back in the Deposit on the DL-032 path (Q-2026-10-05-24),
each Customer's Credit first pays that Customer's own open debt (Q-2026-10-07-42 answer 1), the
Deposit pays the Lease's open debt in the DL-032 order and only the rest is refunded
(BR-SETTLE-008, BR-REFUND-015). Staff prepare it under final_settlements.prepare and only
financial.approve confirms it (BR-SETTLE-013, BR-AUTH-010). Owner answer 2 to Q-2026-10-10-71: a
forfeiture is reversed this way only when no other forfeiture of the Deposit stays active.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from deposit_disposition_test_support import disposition_context, terminate_for_disposition
from lease_deposit_forfeiture_test_support import (
    forfeit_through_draft,
    record_disposition_as_owner,
    reverse_through_draft,
)
from property_rental.deposit import (
    PostgresDepositService,
    QualifyPetDepositRefundReviewCommand,
    RecordDepositDispositionCommand,
    RecordPetDepartureCommand,
)
from property_rental.final_settlement import (
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementInvalidError,
    FinalSettlementKeyReused,
    FinalSettlementNotFoundError,
    FinalSettlementStaleDraftError,
    SettlementCreditStep,
    SettlementDepositStep,
    SettlementStep,
)
from property_rental.lease_deposit_forfeiture import (
    LeaseDepositForfeitureConflictError,
    LeaseDepositForfeitureInvalidError,
    RecordLeaseDepositReversalCommand,
)
from property_rental.reservation_deposit_draft import (
    RecordReservationDepositDraftCommand,
    ReservationDepositDecision,
)
from property_rental.settlement_correction import RecordForfeitureReversalCorrectionCommand
from refund_test_support import create_pet_refund
from test_credit_migration import actor as refund_actor
from test_customer_ledger_migration import assert_reconciled
from test_deposit_migration import deposit_actor
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import invoice_of, this_month
from test_final_settlement_draft_migration import (
    CREDIT_FIRST,
    LINE,
    NO_REFUND,
    PET_FIRST,
    PET_REST,
    SECURITY,
    STAFF,
    drafts,
    leaving_case,
)
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding, pet_deposit, preparer, start
from test_final_settlement_preview_migration import forfeitures, path_of, pay, person, preview
from test_invoice_migration import (
    financial_database_url,
    register_billing_service_principal,
    runtime_database_url,
)
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_pet_refund_migration import command as pet_command
from test_refund_service_migration import service as refunds
from test_reservation_deposit_draft_migration import cancel_by_staff
from test_reservation_deposit_draft_migration import drafts as reservation_drafts
from test_reservation_deposit_draft_migration import person as reservation_person
from test_reservation_lifecycle_migration import active_reservation
from test_settlement_correction_migration import approver, settlement_row
from test_settlement_correction_plan_migration import new_credit
from test_settlement_extra_charge_migration import (
    approving,
    cause,
    corrections,
    extra_charge,
    state,
)
from test_settlement_extra_charge_migration import record as record_extra_charge
from test_unpaid_initial_termination_migration import rent_line, signed_with_initial

REASON = "The forfeiture was reversed after the owner's review"
EVIDENCE = "Owner review note 12"
NOTE = "Cash handed over at the front desk"
RECORD = "app.record_settlement_forfeiture_reversal_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_forfeiture_reversal(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.settlement_forfeiture_reversal_input(jsonb)",
    "app.settlement_forfeiture_reversal_source_state(uuid,uuid)",
    "app.settlement_forfeiture_reversal_plan(uuid,uuid,jsonb)",
    "app.settlement_forfeiture_reversal_result(uuid)",
)
EVERY_BALANCE = "Every remaining Deposit balance must be applied or refunded"
WAITING = "A draft on a source of this Final Settlement is waiting"
ALREADY = "The forfeiture is already reversed"
ANOTHER = (
    "Another forfeiture of this Deposit stays active; the reversal would not put the Deposit on "
    "the DL-032 path"
)
NOT_FOUND = "Lease Deposit forfeiture was not found"
CLOSED_FORFEITURE = (
    "The Lease's Final Settlement is closed; reverse this forfeiture through a correction of that "
    "Final Settlement"
)
COUNTS = (
    "SELECT (SELECT count(*) FROM app.financial_drafts),"
    "(SELECT count(*) FROM app.settlement_corrections),(SELECT count(*) FROM app.refunds),"
    "(SELECT count(*) FROM app.deposit_applications),"
    "(SELECT count(*) FROM app.deposit_disposition_reversals)"
)
LINKS = (
    "deposit_disposition_reversal_id",
    "customer_credit_application_id",
    "deposit_application_id",
    "refund_id",
)


def disposition_of(url: str, deposit: UUID) -> UUID:
    """The one forfeiture of the Deposit."""
    return UUID(
        str(one(url, "SELECT id FROM app.deposit_dispositions WHERE deposit_id=%s", deposit)[0])
    )


def kept_case(url: str) -> dict[str, Any]:
    """Voluntary early leaving (BR-LEASE-021): the Security Deposit (10,000) is forfeited through
    the draft and kept (BR-DEP-023, BR-DEP-026). The Final Settlement is really closed with the
    plan of the 8e-3 early-leaving test: Credit 400 and the Pet Deposit's 7,500 pay the other
    Damage line, the Pet Deposit pays the pet damage line (12,500), and 4,600 of the other line
    stays open on the Primary Tenant's ledger. A correction approver is ready."""
    case = {**leaving_case(url, start_offset=this_month(url), voluntary=True), "url": url}
    security, pet = case["security"], case["pet"]
    forfeit_through_draft(
        PostgresDepositService(financial_database_url(), case["prop"], case["human"]), security
    )
    case["disposition"] = disposition_of(url, security)
    confirm_settlement(
        case,
        record_settlement(
            case,
            (
                SettlementCreditStep(case["credit"], LINE, case["other_line"], 400),
                SettlementDepositStep(PET_FIRST, pet, LINE, case["pet_line"], 12_500),
                SettlementDepositStep(PET_REST, pet, LINE, case["other_line"], 7_500),
            ),
            pet_remainder=STAFF,
        ),
    )
    assert (held(url, security), held(url, pet), outstanding(url, case["other_line"])) == (
        0,
        0,
        4_600,
    )
    case["person"] = approver(url)
    return case


def reversal_command(
    case: dict[str, Any], *steps: SettlementStep, **changes: Any
) -> RecordForfeitureReversalCorrectionCommand:
    return replace(
        RecordForfeitureReversalCorrectionCommand(
            uuid4(),
            case["settlement"],
            case["disposition"],
            REASON,
            EVIDENCE,
            case["cash"],
            NOTE,
            tuple(steps),
        ),
        **changes,
    )


def record_reversal(
    case: dict[str, Any], command: RecordForfeitureReversalCorrectionCommand
) -> UUID:
    found = corrections().record_forfeiture_reversal(
        case["prop"], command, actor=preparer(case["human"], case["prop"])
    )
    return UUID(str(found["draft_id"]))


def confirm_reversal(case: dict[str, Any], draft: UUID) -> dict[str, Any]:
    return corrections().confirm_forfeiture_reversal(
        case["prop"], draft, actor=approving(case["person"], case["prop"])
    )


def effect_links(url: str, correction: object) -> list[str]:
    """The name of each effect's one link, in order."""
    with psycopg.connect(url) as connection:
        rows = connection.execute(
            f"SELECT {','.join(LINKS)} FROM app.settlement_correction_effects "
            "WHERE settlement_correction_id=%s ORDER BY effect_sequence",
            (correction,),
        ).fetchall()
    return [LINKS[[value is not None for value in row].index(True)] for row in rows]


def reversals(url: str, disposition: UUID) -> int:
    return int(
        one(
            url,
            "SELECT count(*) FROM app.deposit_disposition_reversals "
            "WHERE deposit_disposition_id=%s",
            disposition,
        )[0]
    )


def reverse_forfeiture_by_hand(case: dict[str, Any], disposition: UUID) -> None:
    """Sub-slice 10h-2 hand-built set-up: the 6b reversal's own write
    (app.reverse_deposit_disposition_v2) as the database owner, with only the 10h-2 trigger
    disabled inside that one transaction (enabled again before it commits)."""
    trigger = (
        "app.deposit_disposition_reversals {} TRIGGER "
        "a0_deposit_disposition_reversals_final_settlement"
    )
    with psycopg.connect(case["url"]) as connection:
        connection.execute(f"ALTER TABLE {trigger.format('DISABLE')}")
        connection.execute(
            "SELECT app.reverse_deposit_disposition_v2(%s,%s,%s,%s,%s,%s,%s,%s,'deposits.correct')",
            (
                case["prop"],
                case["human"],
                uuid4(),
                hashlib.sha256(b"hand-built forfeiture reversal").hexdigest(),
                uuid4(),
                disposition,
                "Approved forfeiture correction",
                "Reviewed correction evidence",
            ),
        )
        # The deferred checks of the new row run first, so the table has no pending events.
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        connection.execute(f"ALTER TABLE {trigger.format('ENABLE')}")


def waiting_six_b_draft(case: dict[str, Any]) -> dict[str, object]:
    """A waiting 6b forfeiture reversal draft after closure. Since sub-slice 10h-2 (owner answer 4
    to Q-2026-10-06-36) the 6b recorder refuses it (asserted first: a conflict, P5S01, nothing
    written), so the draft is written by the owner through app.insert_financial_draft with the
    payload and digest the recorder would store (standing rule of 2026-10-19 with
    Q-2026-10-19-144)."""
    url = case["url"]
    counts = one(url, COUNTS)
    with pytest.raises(LeaseDepositForfeitureConflictError) as closed:
        six_b_draft(case)
    assert cause(closed) == ("P5S01", CLOSED_FORFEITURE)
    assert one(url, COUNTS) == counts
    draft = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.insert_financial_draft(%s,%s,%s,'DEPOSIT_FORFEITURE','deposits.correct',"
            "jsonb_build_object('variant','LEASE_FORFEITURE_REVERSAL','disposition_id',d.id,"
            "'reversal_id',%s::uuid,'reason',%s::text,'evidence_reference',%s::text)"
            "||jsonb_build_object('deposit_id',d.deposit_id,'lease_id',d.governing_lease_id,"
            "'amount_usd_cents',d.amount_usd_cents,"
            "'state_version',app.deposit_disposition_state_version(d.deposit_id)),"
            "'deposit-state:'||app.deposit_disposition_state_version(d.deposit_id),%s) "
            "FROM app.deposit_dispositions d WHERE d.id=%s",
            (
                case["prop"],
                case["human"],
                draft,
                uuid4(),
                "Reviewed again",
                "Owner note 3",
                "Reviewed again",
                case["disposition"],
            ),
        )
    return {"draft_id": str(draft)}


def six_b_draft(case: dict[str, Any]) -> dict[str, object]:
    """A 6b forfeiture reversal draft (deposits.correct), recorded after closure."""
    return forfeitures().record_reversal(
        case["prop"],
        RecordLeaseDepositReversalCommand(
            uuid4(), case["disposition"], uuid4(), "Reviewed again", "Owner note 3"
        ),
        actor=person(case["human"], case["prop"], "deposits.correct"),
    )


def test_a_kept_deposit_pays_the_open_debt_first_and_only_the_rest_is_refunded(
    migrated_database_url: str,
) -> None:
    """Owner answer 4 to Q-2026-10-06-36 on a really closed Settlement whose Security Deposit was
    kept: a correction without a plan leaves the returned money unused and a Refund of all of it
    leaves the 4,600 of open debt (BR-SETTLE-008), both refused with nothing written; a recorded
    draft moves no money and Staff cannot confirm it. The approver's confirm reverses the
    forfeiture (linked, through the existing reversal function: the approver, deposits.correct,
    the draft's reason and evidence), the Security Deposit pays the 4,600 and only 5,400 is
    refunded to the Primary Tenant with the draft's method and note. The Deposit is back on the
    DL-032 path and empty, the Settlement row is unchanged, an exact repeat replays (no result
    shows the decision's transaction id), another approver finds the draft decided, the 6b draft
    and a second correction of the same forfeiture are refused, and the ledger reconciles."""
    url = migrated_database_url
    case = kept_case(url)
    prop, human, settlement = case["prop"], case["human"], case["settlement"]
    security, customer, other_line = case["security"], case["customer"], case["other_line"]
    before = settlement_row(url, settlement)
    assert path_of(preview(prop, human, settlement), security) == (
        "BR-DEP-023",
        "ACTIVE",
        "KEPT",
        0,
    )
    counts = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as unused:
        record_reversal(case, reversal_command(case))
    assert cause(unused) == ("55000", EVERY_BALANCE)
    with pytest.raises(FinalSettlementConflictError) as early:
        record_reversal(case, reversal_command(case, settlement_refund(case, "security", 10_000)))
    assert cause(early) == ("55000", NO_REFUND)
    assert one(url, COUNTS) == counts
    command = reversal_command(
        case,
        SettlementDepositStep(SECURITY, security, LINE, other_line, 4_600),
        settlement_refund(case, "security", 5_400),
    )
    draft = record_reversal(case, command)
    assert one(
        url,
        "SELECT payload->>'variant',payload->>'deposit_disposition_id',payload->>'deposit_id',"
        "(payload->>'amount_usd_cents')::bigint FROM app.financial_drafts WHERE id=%s",
        draft,
    ) == ("FORFEITURE_REVERSAL", str(case["disposition"]), str(security), 10_000)
    with pytest.raises(FinalSettlementAuthorizationError):
        corrections().confirm_forfeiture_reversal(prop, draft, actor=preparer(human, prop))
    assert (held(url, security), reversals(url, case["disposition"]), state(url, draft)) == (
        0,
        0,
        "PENDING",
    )
    result = confirm_reversal(case, draft)
    correction = result["settlement_correction"]["id"]
    assert effect_links(url, correction) == [
        "deposit_disposition_reversal_id",
        "deposit_application_id",
        "refund_id",
    ]
    reversal = result["forfeiture_reversal"]
    assert (
        reversal["deposit_disposition_id"],
        reversal["deposit_id"],
        reversal["amount_usd_cents"],
        reversal["reason"],
        reversal["evidence_reference"],
        reversal["actor_id"],
        reversal["authorization_reference"],
    ) == (
        str(case["disposition"]),
        str(security),
        10_000,
        REASON,
        EVIDENCE,
        str(case["person"]),
        "deposits.correct",
    )
    [applied] = result["deposit_applications"]
    assert (
        applied["deposit_id"],
        applied["application_stage"],
        applied["invoice_line_id"],
        applied["amount_usd_cents"],
    ) == (str(security), "SECURITY_EXPLICIT", str(other_line), 4_600)
    [paid] = result["refunds"]
    assert (
        paid["source_deposit_id"],
        paid["recipient_customer_id"],
        paid["amount_usd_cents"],
        paid["refund_method_id"],
        paid["reference_note"],
        paid["signer_agreement"],
    ) == (str(security), str(customer), 5_400, str(case["cash"]), NOTE, None)
    assert (held(url, security), outstanding(url, other_line), state(url, draft)) == (
        0,
        0,
        "CONFIRMED",
    )
    assert path_of(preview(prop, human, settlement), security) == (
        "BR-DEP-023",
        "REVERSED",
        "DL_032",
        0,
    )
    assert one(
        url,
        "SELECT entity_id,actor_id,authorization_reference FROM app.audit_events "
        "WHERE action='deposit.disposition.reversed' AND correlation_id=%s",
        draft,
    ) == (UUID(str(reversal["id"])), case["person"], "deposits.correct")
    customer_id, confirmed = one(
        url,
        "SELECT customer_id,resulting_state FROM app.audit_events WHERE correlation_id=%s "
        "AND action='final_settlement.correction.confirmed'",
        correction,
    )
    assert (
        customer_id,
        confirmed["variant"],
        confirmed["deposit_disposition_reversal_id"],
        confirmed["reversed_usd_cents"],
        confirmed["deposit_refund_ids"],
    ) == (customer, "FORFEITURE_REVERSAL", reversal["id"], 10_000, [paid["id"]])
    assert confirm_reversal(case, draft) == result
    # No correction result or replay shows the decision's transaction id (sub-slice 10b), also
    # the recorder's replay of the decided draft; another approver finds the draft decided.
    decision = cast(dict[str, Any], result["draft"]["decision"])
    assert decision["decision"] == "CONFIRMED" and "transaction_id" not in decision["result"]
    replayed = corrections().record_forfeiture_reversal(prop, command, actor=preparer(human, prop))
    assert replayed["state"] == "CONFIRMED"
    assert "transaction_id" not in cast(
        dict[str, Any], cast(dict[str, Any], replayed["decision"])["result"]
    )
    with pytest.raises(FinalSettlementConflictError) as decided:
        corrections().confirm_forfeiture_reversal(prop, draft, actor=approving(approver(url), prop))
    assert cause(decided) == ("55000", "Financial draft is already decided")
    with pytest.raises(LeaseDepositForfeitureInvalidError) as six_b:
        six_b_draft(case)
    assert cause(six_b) == ("22023", ALREADY)
    with pytest.raises(FinalSettlementConflictError) as again:
        record_reversal(case, reversal_command(case, settlement_refund(case, "security", 10_000)))
    assert cause(again) == ("55000", ALREADY)
    assert reversals(url, case["disposition"]) == 1
    assert settlement_row(url, settlement) == before
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_with_no_open_debt_the_whole_deposit_is_refunded_only_to_a_signer(
    migrated_database_url: str,
) -> None:
    """After closure the Customer pays the 4,600 that stayed open, so no debt is left. A Refund to
    a Customer who is not a Signer of the Lease is refused (55000), and so is an agreement for the
    Primary Tenant (22023) (BR-REFUND-015; owner answer 1 to Q-2026-10-10-71: the positive
    agreed-Signer path is the shared step's own test). The whole forfeited 10,000 is then refunded
    to the Primary Tenant and the ledger reconciles."""
    url = migrated_database_url
    case = kept_case(url)
    prop, human, customer, other_line = (
        case["prop"],
        case["human"],
        case["customer"],
        case["other_line"],
    )
    pay(url, prop, human, customer, invoice_of(url, other_line), other_line, 4_600)
    assert outstanding(url, other_line) == 0
    counts = one(url, COUNTS)
    # A real Customer of the test database who is not a Signer of this Lease (the approver made
    # by kept_case is one).
    not_a_signer = UUID(
        str(
            one(
                url,
                "SELECT customer.id FROM app.customers customer WHERE NOT EXISTS("
                "SELECT 1 FROM app.lease_signers signer WHERE signer.lease_id=%s "
                "AND signer.customer_id=customer.id) ORDER BY customer.id LIMIT 1",
                case["lease"],
            )[0]
        )
    )
    stranger = settlement_refund(
        case,
        "security",
        10_000,
        recipient_customer_id=not_a_signer,
        signer_agreement="All Signers agreed in writing on 2026-10-10",
    )
    with pytest.raises(FinalSettlementConflictError) as outside:
        record_reversal(case, reversal_command(case, stranger))
    assert cause(outside) == ("55000", "The Refund recipient must be a Signer of the Lease")
    with pytest.raises(FinalSettlementInvalidError) as primary:
        record_reversal(
            case,
            reversal_command(
                case,
                settlement_refund(
                    case, "security", 10_000, signer_agreement="All Signers agreed in writing"
                ),
            ),
        )
    assert cause(primary) == (
        "22023",
        "The Primary Tenant needs no Signer agreement",
    )
    assert one(url, COUNTS) == counts
    result = confirm_reversal(
        case,
        record_reversal(case, reversal_command(case, settlement_refund(case, "security", 10_000))),
    )
    assert effect_links(url, result["settlement_correction"]["id"]) == [
        "deposit_disposition_reversal_id",
        "refund_id",
    ]
    assert result["deposit_applications"] == []
    [paid] = result["refunds"]
    assert (paid["source_deposit_id"], paid["recipient_customer_id"], paid["amount_usd_cents"]) == (
        str(case["security"]),
        str(customer),
        10_000,
    )
    assert held(url, case["security"]) == 0
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_credit_pays_its_customer_first_and_debt_can_take_the_whole_deposit(
    migrated_database_url: str,
) -> None:
    """After closure the Primary Tenant pays the 4,600 that stayed open and gets 300 of Credit
    (Credit is recognized only while no obligation is open), then an EXTRA_CHARGE correction adds
    a 10,600 charge. A plan whose Security Deposit pays before the Credit is refused
    (Q-2026-10-07-42 answer 1, Q-2026-10-05-29); with the Credit first the reversed 10,000 pays
    the charge, nothing is refunded and 300 stays open on the Primary Tenant's ledger
    (BR-SETTLE-016)."""
    url = migrated_database_url
    case = kept_case(url)
    prop, human, security, customer, other_line = (
        case["prop"],
        case["human"],
        case["security"],
        case["customer"],
        case["other_line"],
    )
    pay(url, prop, human, customer, invoice_of(url, other_line), other_line, 4_600)
    credit = new_credit(url, case, 300)
    charged = corrections().confirm_extra_charge(
        prop,
        record_extra_charge(case, extra_charge(case["settlement"], amount_usd_cents=10_600)),
        actor=approving(case["person"], prop),
    )
    invoice = UUID(str(cast(dict[str, Any], charged["invoice"])["id"]))
    charge_line = UUID(
        str(one(url, "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", invoice)[0])
    )
    assert (outstanding(url, other_line), outstanding(url, charge_line)) == (0, 10_600)
    with pytest.raises(FinalSettlementConflictError) as deposit_first:
        record_reversal(
            case,
            reversal_command(
                case, SettlementDepositStep(SECURITY, security, LINE, charge_line, 10_000)
            ),
        )
    assert cause(deposit_first) == ("55000", CREDIT_FIRST)
    result = confirm_reversal(
        case,
        record_reversal(
            case,
            reversal_command(
                case,
                SettlementCreditStep(credit, LINE, charge_line, 300),
                SettlementDepositStep(SECURITY, security, LINE, charge_line, 10_000),
            ),
        ),
    )
    correction = result["settlement_correction"]["id"]
    assert effect_links(url, correction) == [
        "deposit_disposition_reversal_id",
        "customer_credit_application_id",
        "deposit_application_id",
    ]
    assert result["refunds"] == []
    [applied] = result["deposit_applications"]
    assert (applied["deposit_id"], applied["amount_usd_cents"]) == (str(security), 10_000)
    assert (held(url, security), outstanding(url, charge_line)) == (0, 300)
    customer_id, confirmed = one(
        url,
        "SELECT customer_id,resulting_state FROM app.audit_events WHERE correlation_id=%s "
        "AND action='final_settlement.correction.confirmed'",
        correction,
    )
    assert (customer_id, confirmed["deposit_refund_ids"]) == (customer, [])
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_a_forfeiture_reversal_refuses_other_forfeitures_waiting_drafts_and_stale_drafts(
    migrated_database_url: str,
) -> None:
    """Refusals at record, with nothing written: an open Settlement (55000); a forfeiture of
    another Lease, a Reservation forfeiture or an unknown one (P0002); a 6b reversal draft of the
    forfeiture waiting (55000, until it is withdrawn); an inactive Refund method (55000); a Deposit
    Refund step whose method or reference note is not the correction's (22023, BR-REFUND-014). A
    method deactivated between record and confirm is refused at the confirm (55000), the draft
    stays pending and no reversal is written. The database guards: malformed input 22023;
    the recorder takes only final_settlements.prepare and the confirm only financial.approve
    (42501); a reused key P5205 and an exact repeat replays; a service identity that is not a
    person cannot confirm (P4506); the confirm runs only at READ COMMITTED (55000). A 6b draft of
    the Deposit recorded after the correction draft makes it stale (its source digest lists the
    Deposit's waiting drafts): it stays pending and nothing is written. Once that draft is
    withdrawn the same correction draft is confirmed, and its confirm holds the Lease row and the
    Deposit row until it commits (NOWAIT)."""
    url = migrated_database_url
    case = kept_case(url)
    prop, human, security, other_line = (
        case["prop"],
        case["human"],
        case["security"],
        case["other_line"],
    )
    other = {**leaving_case(url, start_offset=this_month(url), voluntary=True), "url": url}
    forfeit_through_draft(
        PostgresDepositService(financial_database_url(), other["prop"], other["human"]),
        other["security"],
    )
    other_disposition = disposition_of(url, other["security"])
    with psycopg.connect(url) as setup:
        actor_id, property_id, _, _, reservation = active_reservation(setup)
        setup.commit()
    cancel_by_staff(actor_id, property_id, reservation)
    outcome = uuid4()
    waiting_outcome = reservation_drafts().record(
        property_id,
        ReservationDepositDecision.DEPOSIT_FORFEITURE,
        RecordReservationDepositDraftCommand(uuid4(), reservation, outcome, "Customer withdrew"),
        actor=reservation_person(
            actor_id, property_id, "reservations.read", "reservation_deposits.dispose"
        ),
    )
    reservation_drafts().confirm(
        property_id,
        reservation,
        UUID(str(waiting_outcome["draft_id"])),
        actor=reservation_person(actor_id, property_id, "financial.approve"),
    )
    method = uuid4()
    with psycopg.connect(runtime_database_url()) as connection:
        connection.execute(
            "SELECT app.create_refund_method(%s,%s,%s,%s,%s,%s)",
            (
                prop,
                human,
                method,
                f"FIX_{method.hex[:8].upper()}",
                "Forfeiture reversal test",
                "property.manage",
            ),
        )
    counts = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as still_open:
        corrections().record_forfeiture_reversal(
            other["prop"],
            RecordForfeitureReversalCorrectionCommand(
                uuid4(),
                other["settlement"],
                other_disposition,
                REASON,
                EVIDENCE,
                other["cash"],
                NOTE,
            ),
            actor=preparer(other["human"], other["prop"]),
        )
    assert cause(still_open) == (
        "55000",
        "A post-settlement correction needs a closed Final Settlement",
    )
    plan = (
        SettlementDepositStep(SECURITY, security, LINE, other_line, 4_600),
        settlement_refund(case, "security", 5_400),
    )
    for elsewhere in (other_disposition, outcome, uuid4()):
        with pytest.raises(FinalSettlementNotFoundError) as missing:
            record_reversal(case, reversal_command(case, *plan, deposit_disposition_id=elsewhere))
        assert cause(missing) == ("P0002", NOT_FOUND)
    # BR-REFUND-014: one Refund method and reference note per correction, both in every Deposit
    # Refund step.
    for step in (
        settlement_refund(case, "security", 5_400, refund_method_id=method),
        settlement_refund(case, "security", 5_400, reference_note="Paid by another note"),
    ):
        with pytest.raises(FinalSettlementInvalidError) as mixed:
            record_reversal(case, reversal_command(case, plan[0], step))
        assert cause(mixed) == (
            "22023",
            "A post-settlement correction has one Refund method, reference note, recipient and "
            "agreement",
        )
    assert one(url, COUNTS) == counts
    # Since sub-slice 10h-2 the 6b recorder refuses after the closure; the waiting draft is
    # hand-built after that refusal is asserted.
    waiting = waiting_six_b_draft(case)
    counts = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as blocked:
        record_reversal(case, reversal_command(case, *plan))
    assert cause(blocked) == ("55000", WAITING)
    assert one(url, COUNTS) == counts
    drafts().withdraw(
        prop,
        UUID(str(waiting["draft_id"])),
        "Recorded in error",
        prepare_capability="deposits.correct",
        actor=person(human, prop, "deposits.correct"),
    )
    # The draft's own method, deactivated after the draft, is a conflict at the confirm; the
    # recorder refuses an inactive method too.
    own_method = record_reversal(
        case,
        reversal_command(
            case,
            plan[0],
            settlement_refund(case, "security", 5_400, refund_method_id=method),
            refund_method_id=method,
        ),
    )
    with psycopg.connect(runtime_database_url()) as connection:
        connection.execute(
            "SELECT app.set_refund_method_active(%s,%s,%s,false,%s)",
            (prop, human, method, "property.manage"),
        )
    counts = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as inactive:
        confirm_reversal(case, own_method)
    assert cause(inactive) == ("55000", "Refund Method is not active")
    # Review round 2: the correction's own method must be active even when no Refund step uses
    # it (without that check this plan is refused for leaving 5,400 unused).
    with pytest.raises(FinalSettlementConflictError) as inactive_record:
        record_reversal(case, reversal_command(case, plan[0], refund_method_id=method))
    assert cause(inactive_record) == ("55000", "Refund Method is not active")
    assert (state(url, own_method), one(url, COUNTS), held(url, security)) == (
        "PENDING",
        counts,
        0,
    )
    good = reversal_command(case, *plan).forfeiture_reversal()
    for malformed in (
        {**good, "surprise": True},
        {key: value for key, value in good.items() if key != "evidence_reference"},
        {**good, "deposit_disposition_id": "not-a-uuid"},
        {**good, "evidence_reference": " padded"},
        {**good, "reference_note": "x" * 501},
        {**good, "plan": []},
    ):
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            connection.execute(
                f"SELECT {RECORD.split('(')[0]}(%s,%s,%s,%s,%s,%s,'final_settlements.prepare')",
                (prop, human, uuid4(), case["settlement"], Jsonb(malformed), REASON),
            )
        assert refused.value.sqlstate == "22023", malformed
    for authorization in ("financial.approve", "deposits.correct", None):
        with pytest.raises(psycopg.Error) as recorder, psycopg.connect(url) as connection:
            connection.execute(
                f"SELECT {RECORD.split('(')[0]}(%s,%s,%s,%s,%s,%s,%s)",
                (prop, human, uuid4(), case["settlement"], Jsonb(good), REASON, authorization),
            )
        assert recorder.value.sqlstate == "42501", authorization
    assert one(url, COUNTS) == counts
    reused = reversal_command(case, *plan)
    first = record_reversal(case, reused)
    assert record_reversal(case, reused) == first
    with pytest.raises(FinalSettlementKeyReused):
        record_reversal(case, replace(reused, reason="Another reason for the same key"))
    with pytest.raises(psycopg.Error) as staff, psycopg.connect(url) as connection:
        connection.execute(
            f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'final_settlements.prepare')",
            (prop, case["person"], first),
        )
    assert staff.value.sqlstate == "42501"
    with psycopg.connect(url) as connection:
        machine = register_billing_service_principal(connection, property_id=prop, created_by=human)
    with pytest.raises(FinalSettlementAuthorizationError) as not_a_person:
        corrections().confirm_forfeiture_reversal(prop, first, actor=approving(machine, prop))
    assert cause(not_a_person)[0] == "P4506"
    with pytest.raises(psycopg.Error) as isolation, psycopg.connect(url) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        connection.execute(
            f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'financial.approve')",
            (prop, case["person"], first),
        )
    assert (isolation.value.sqlstate, isolation.value.diag.message_primary) == (
        "55000",
        "A post-settlement correction is confirmed at READ COMMITTED",
    )
    assert (state(url, first), one(url, COUNTS)[1:]) == ("PENDING", counts[1:])
    # Since sub-slice 10h-2: hand-built after the 6b recorder's refusal is asserted.
    later = waiting_six_b_draft(case)
    with pytest.raises(FinalSettlementStaleDraftError):
        confirm_reversal(case, first)
    assert (state(url, first), reversals(url, case["disposition"]), held(url, security)) == (
        "PENDING",
        0,
        0,
    )
    assert one(url, COUNTS)[1:] == counts[1:]
    drafts().withdraw(
        prop,
        UUID(str(later["draft_id"])),
        "Recorded in error",
        prepare_capability="deposits.correct",
        actor=person(human, prop, "deposits.correct"),
    )
    with psycopg.connect(url) as holder:
        found = holder.execute(
            f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'financial.approve')",
            (prop, case["person"], first),
        ).fetchone()
        assert found is not None
        [paid] = cast(dict[str, Any], found[0])["refunds"]
        assert paid["amount_usd_cents"] == 5_400
        for query, value in (
            ("SELECT 1 FROM app.leases WHERE id=%s FOR UPDATE NOWAIT", case["lease"]),
            ("SELECT 1 FROM app.deposits WHERE id=%s FOR UPDATE NOWAIT", security),
        ):
            with (
                pytest.raises(psycopg.errors.LockNotAvailable),
                psycopg.connect(make_conninfo(url, connect_timeout=10)) as waiting_session,
            ):
                waiting_session.execute(query, (value,))
    assert (state(url, first), held(url, security), outstanding(url, other_line)) == (
        "CONFIRMED",
        0,
        0,
    )


def twice_forfeited_case(url: str) -> dict[str, Any]:
    """A kept Pet Deposit with two active forfeitures before closure: a Pet Refund-review Refund
    pays 13,000 of the 20,000 Pet Deposit while the Lease is signed; the Lease is terminated for
    pet noncompliance (BR-DEP-022); the Security Deposit is forfeited through the draft; the owner's
    one-call disposition forfeits 5,000 of the Pet Deposit's own 7,000, then the forfeiture draft
    forfeits the remaining 2,000 (since sub-slice 10c-2b-6 no forfeiture may take returned pay-back
    money, so both forfeitures take the Deposit's own money). The Settlement closes with no step.
    A correction approver is ready."""
    source = signed_with_initial(url, this_month(url))
    human, prop, lease = source["actor"], source["property"], source["lease"]
    customer, day = source["customer"], source["today"]
    pet = pet_deposit(url, human, prop, lease, day)
    deposits = PostgresDepositService(financial_database_url(), prop, human)
    who = deposit_actor(human, prop)
    departure = RecordPetDepartureCommand(uuid4(), uuid4(), pet, day, "Pet permanently left")
    deposits.record_pet_departure(departure, actor=who)
    review = QualifyPetDepositRefundReviewCommand(
        uuid4(),
        uuid4(),
        departure.departure_id,
        pet,
        30000,
        "All valid pet costs resolved separately; liability is not capped by Deposit",
        "Synthetic inspection and resolution evidence",
        "Qualified Pet exception",
    )
    deposits.qualify_pet_refund_review(review, actor=who)
    create_pet_refund(
        refunds(),
        prop,
        pet_command(pet, review.review_id, 13_000),
        actor=refund_actor(human, prop, "refunds.create"),
    )
    rent, owed = rent_line(url, source["invoice"])
    pay(url, prop, human, customer, source["invoice"], rent, owed)
    terminate_for_disposition(url, deposits, lease, day)
    case: dict[str, Any] = {
        "url": url,
        "human": human,
        "prop": prop,
        "lease": lease,
        "customer": customer,
        "security": source["deposit"],
        "pet": pet,
        "settlement": start(prop, human, lease),
        "cash": UUID(str(one(url, "SELECT id FROM app.refund_methods WHERE code='CASH'")[0])),
    }
    forfeit_through_draft(deposits, case["security"])
    # Sub-slice 10c-2b-6 (owner answer 4 of 2026-10-12, owner standing rule of 2026-10-11): no
    # forfeiture may take returned pay-back money, so the two active forfeitures this guard test
    # needs both take the Pet Deposit's own money: the owner's one-call disposition forfeits 5,000
    # of the 7,000 it holds, then the forfeiture draft forfeits the remaining 2,000. (The refusals
    # of a forfeiture of returned money are tested in test_pet_deposit_payback_limit_migration.py.)
    assert held(url, pet) == 7_000
    record_disposition_as_owner(
        deposits,
        RecordDepositDispositionCommand(
            uuid4(),
            uuid4(),
            pet,
            lease,
            5_000,
            day,
            "Approved BR-DEP-022 source",
            context=disposition_context(url, pet),
        ),
        actor=who,
    )
    assert held(url, pet) == 2_000
    forfeit_through_draft(deposits, pet)
    assert (held(url, case["security"]), held(url, pet)) == (0, 0)
    confirm_settlement(case, record_settlement(case, ()))
    case["person"] = approver(url)
    return case


def test_a_second_active_forfeiture_of_the_deposit_refuses_its_reversal(
    migrated_database_url: str,
) -> None:
    """Owner answer 2 to Q-2026-10-10-71: the kept Pet Deposit has two active forfeitures, so the
    reversal of either one would leave it kept and off the DL-032 path; both are refused (55000)
    and no draft is recorded. A correction draft for the Security Deposit's single forfeiture is
    recorded; that forfeiture is then reversed outside the correction, so the correction draft is
    stale at its confirm (its digest names the forfeiture's reversals; P5S02, not the record-time
    55000), stays pending and writes nothing. Since sub-slice 10h-2 the 6b draft is refused after
    the closure (asserted first), so that reversal is written by hand."""
    url = migrated_database_url
    case = twice_forfeited_case(url)
    pet, security = case["pet"], case["security"]
    with psycopg.connect(url) as connection:
        first, second = (
            UUID(str(row[0]))
            for row in connection.execute(
                "SELECT id FROM app.deposit_dispositions WHERE deposit_id=%s ORDER BY occurred_at",
                (pet,),
            ).fetchall()
        )
    case["disposition"] = first
    counts = one(url, COUNTS)
    for disposition, amount in ((first, 5_000), (second, 2_000)):
        with pytest.raises(FinalSettlementConflictError) as kept:
            record_reversal(
                case,
                reversal_command(
                    case,
                    settlement_refund(case, "pet", amount),
                    deposit_disposition_id=disposition,
                ),
            )
        assert cause(kept) == ("55000", ANOTHER)
    assert one(url, COUNTS) == counts
    case["disposition"] = disposition_of(url, security)
    draft = record_reversal(
        case, reversal_command(case, settlement_refund(case, "security", 10_000))
    )
    # Since sub-slice 10h-2 (owner answer 4 to Q-2026-10-06-36) the 6b draft cannot reverse a
    # forfeiture after the closure, so this state can no longer be reached through it: the
    # refusal is asserted first, then the same reversal is written by hand (standing rule of
    # 2026-10-19 with Q-2026-10-19-144).
    counts = one(url, COUNTS)
    with pytest.raises(LeaseDepositForfeitureConflictError) as closed:
        reverse_through_draft(
            PostgresDepositService(financial_database_url(), case["prop"], case["human"]),
            case["disposition"],
        )
    assert cause(closed) == ("P5S01", CLOSED_FORFEITURE)
    assert (one(url, COUNTS), reversals(url, case["disposition"])) == (counts, 0)
    reverse_forfeiture_by_hand(case, case["disposition"])
    counts = one(url, COUNTS)
    with pytest.raises(FinalSettlementStaleDraftError):
        confirm_reversal(case, draft)
    assert (state(url, draft), one(url, COUNTS), reversals(url, case["disposition"])) == (
        "PENDING",
        counts,
        1,
    )
    assert (held(url, security), held(url, pet)) == (10_000, 0)


def test_forfeiture_reversal_records_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Only the financial role records and confirms a forfeiture reversal correction; no role
    calls its internal functions; the migration adds only its functions, changes no committed
    function, table or trigger and is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (RECORD, CONFIRM, *INTERNAL):
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (role == "prm_financial" and function in (RECORD, CONFIRM),), (
                    function,
                    role,
                )
            definer = connection.execute(
                "SELECT p.prosecdef,p.proconfig[1] FROM pg_catalog.pg_proc p "
                "WHERE p.oid=CAST(%s AS regprocedure)",
                (function,),
            ).fetchone()
            assert definer == (True, "search_path=pg_catalog"), function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("20261119_115")
    assert revision is not None and revision.down_revision == "20261118_114"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, tuple[object, ...]], set[str], set[str]]:
        with psycopg.connect(database) as connection:
            functions = {
                str(row[0]): tuple(row[1:])
                for row in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                    "p.proacl::text,p.proowner,p.prosecdef,p.proconfig::text "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ).fetchall()
            }
            relations = {
                str(row[0])
                for row in connection.execute(
                    "SELECT c.oid::regclass::text FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND c.relkind IN ('r','v','m','p')"
                ).fetchall()
            }
            triggers = {
                f"{row[0]}:{row[1]}"
                for row in connection.execute(
                    "SELECT t.tgrelid::regclass::text,t.tgname FROM pg_catalog.pg_trigger t "
                    "JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND NOT t.tgisinternal"
                ).fetchall()
            }
        return functions, relations, triggers

    with _temporary_migration_database("settlement_forfeiture_reversal") as temporary:
        alembic_command.upgrade(config, "20261118_114")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, "20261119_115")
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert (after_relations, after_triggers) == (before_relations, before_triggers)
    assert set(after_functions) - set(before_functions) == {RECORD, CONFIRM, *INTERNAL}
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set()
