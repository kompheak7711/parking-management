"""Post-settlement correction: pet classification of a Damage line (V1-056 sub-slice 10c-2a-5).

Owner answer to Q-2026-10-07-45 (option (a)): a Damage line whose pet classification is wrong
after closure is fixed by a new correction kind, in both directions. Staff record it under
final_settlements.prepare with a reason and an evidence reference; only a financial.approve
holder confirms it (BR-AUTH-010). The charge amount stays the same and the closed inspection
record is not changed: the confirmation writes a classification record linked to the correction
(DB-SETTLE-007, DB-SETTLE-005), which app.invoice_line_is_pet_damage reads before the inspection,
reverses the line's Deposit applications where the corrected classification changes which
Deposit should pay, and runs the shared DL-032 step after closure (DL-032, BR-SETTLE-008,
BR-SETTLE-013) with a new Customer choice at a BR-DEP-027 termination (owner answer 3 to
Q-2026-10-07-44). The closed Settlement is never changed (BR-SETTLE-012).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
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
    PetRemainderDecision,
    SettlementCreditStep,
    SettlementDepositRefund,
    SettlementDepositStep,
    SettlementDepositStepKind,
    SettlementStep,
)
from property_rental.identity import AuthenticatedActor
from property_rental.move_out_inspection import RecordMoveOutInspection
from property_rental.settlement_correction import (
    RecordPetClassificationCorrectionCommand,
    SettlementCorrectionService,
)
from test_customer_ledger_migration import assert_reconciled
from test_deposit_application_reversal_migration import begin
from test_final_settlement_closed_refusal_migration import close
from test_final_settlement_draft_migration import (
    CHOICE,
    LINE,
    PET_FIRST,
    PET_REST,
    STAFF,
    leaving_case,
)
from test_final_settlement_migration import held, one, outstanding, preparer, today
from test_invoice_migration import financial_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_out_inspection_migration import actor as inspection_actor
from test_move_out_inspection_migration import flow as inspection_flow
from test_settlement_correction_migration import LINK, approver, invoice_of, settlement_row
from test_settlement_correction_plan_migration import (
    PET_DAMAGE_ONLY,
    closed_case,
    credit_step,
    deposit_step,
    failure,
    overlay,
    plan,
    plan_draft,
    post,
    refund_step,
    release,
)
from test_settlement_deposit_refund_correction_migration import pet_paid_case
from test_settlement_extra_charge_migration import cause, state

RECORD = "app.record_settlement_pet_classification_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_pet_classification(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.settlement_pet_classification_line(uuid,uuid)",
    "app.validate_settlement_pet_classification()",
    "app.settlement_pet_classification_input(jsonb)",
    "app.settlement_pet_classification_reversals(uuid,uuid,boolean)",
    "app.settlement_pet_classification_source_state(uuid,uuid,uuid)",
    "app.settlement_pet_classification_plan(uuid,uuid,jsonb)",
    "app.settlement_pet_classification_overlay(jsonb,uuid,boolean)",
    "app.settlement_pet_classification_result(uuid)",
)
CHANGED = (
    "app.invoice_line_is_pet_damage(uuid,uuid)",
    "app.settlement_correction_plan_result(uuid,uuid,uuid,jsonb,jsonb)",
    "app.lock_settlement_correction_plan(uuid)",
    "app.settlement_correction_linked(uuid,text,uuid)",
    "app.link_settlement_correction_effect(uuid,text,uuid)",
)
REASON = "The window latch was broken by the earlier tenant, not by the pet"
EVIDENCE = "Vet and neighbour statements, file 12"
NEW_CHOICE = "Primary Tenant agreed on 2026-10-08, by signed note, for this correction"
ALREADY = "The line already has this pet classification"
# Sub-slice 10c-2a-7 (owner answer (a) to Q-2026-10-08-53): a line billed from an inspection
# superseded before closure is eligible too, so the message no longer names a current inspection.
NOT_ELIGIBLE = (
    "A pet classification correction corrects only a Damage line billed from a finding of a "
    "move-out inspection of this Lease"
)


def corrections() -> SettlementCorrectionService:
    return SettlementCorrectionService(financial_database_url())


def approving(person: UUID, prop: UUID) -> AuthenticatedActor:
    return preparer(person, prop, "financial.approve")


def command(
    case: dict[str, Any],
    line: UUID,
    pet_related: bool,
    *steps: SettlementStep,
    pet_remainder: PetRemainderDecision | None = None,
    **changes: Any,
) -> RecordPetClassificationCorrectionCommand:
    return replace(
        RecordPetClassificationCorrectionCommand(
            uuid4(),
            case["settlement"],
            invoice_of(case["url"], line),
            line,
            pet_related,
            EVIDENCE,
            REASON,
            tuple(steps),
            pet_remainder,
        ),
        **changes,
    )


def record(case: dict[str, Any], classification: RecordPetClassificationCorrectionCommand) -> UUID:
    found = corrections().record_pet_classification(
        case["prop"], classification, actor=preparer(case["human"], case["prop"])
    )
    return UUID(str(found["draft_id"]))


def confirm(case: dict[str, Any], draft: UUID) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        corrections().confirm_pet_classification(
            case["prop"], draft, actor=approving(case["person"], case["prop"])
        ),
    )


def is_pet(case: dict[str, Any], line: UUID) -> bool:
    return bool(
        one(case["url"], "SELECT app.invoice_line_is_pet_damage(%s,%s)", line, case["lease"])[0]
    )


def application(url: str, application_id: object) -> tuple[Any, ...]:
    return tuple(
        one(
            url,
            "SELECT deposit_id,invoice_line_id,amount_usd_cents,application_stage "
            "FROM app.deposit_applications WHERE id=%s",
            UUID(str(application_id)),
        )
    )


def reversed_application(url: str, application_id: object) -> bool:
    return bool(
        one(
            url,
            "SELECT EXISTS(SELECT 1 FROM app.deposit_application_reversals "
            "WHERE deposit_application_id=%s)",
            UUID(str(application_id)),
        )[0]
    )


def stage_application(url: str, case: dict[str, Any], stage: str, line: UUID) -> UUID:
    return UUID(
        str(
            one(
                url,
                "SELECT id FROM app.deposit_applications WHERE final_settlement_id=%s "
                "AND application_stage=%s AND invoice_line_id=%s ORDER BY occurred_at LIMIT 1",
                case["settlement"],
                stage,
                line,
            )[0]
        )
    )


def effect_links(url: str, correction: object) -> list[str]:
    """The link kind of each effect of a correction, in effect order."""
    with psycopg.connect(url) as connection:
        rows = connection.execute(
            "SELECT to_jsonb(effect) FROM app.settlement_correction_effects effect "
            "WHERE settlement_correction_id=%s ORDER BY effect_sequence",
            (correction,),
        ).fetchall()
    links = []
    for row in rows:
        effect = cast(dict[str, Any], row[0])
        [link] = [
            key
            for key, value in effect.items()
            if value is not None
            and key not in {"id", "settlement_correction_id", "effect_sequence", "created_at"}
        ]
        links.append(link)
    return links


def closed(url: str) -> dict[str, Any]:
    """The 8c normal-end Settlement closed by the real confirm (sub-slice 10c-2a-2 fixture): the
    Pet Deposit paid the pet damage line first (12,500), the Security Deposit (10,000) and the
    remaining Pet Deposit (2,100) the other Damage line; the Customer got 300 of new Credit."""
    return {**closed_case(url), "url": url}


def test_a_pet_line_corrected_to_not_pet_is_paid_by_the_remaining_pet_deposit_on_a_staff_reason(
    migrated_database_url: str,
) -> None:
    """To not pet damage: the line's Pet-Deposit-first application is reversed (12,500 back to
    the Pet Deposit), the Customer's Credit pays first (300), the remaining Pet Deposit pays the
    rest of the line at DL-032 step 5 on a staff reason (12,200), and its last 300 is refunded.
    The classification record is linked, the reader follows it, the inspection and the closed
    Settlement are unchanged, the ledgers reconcile, and an exact repeat replays."""
    url = migrated_database_url
    case = closed(url)
    pet, pet_line, other_line = case["pet"], case["pet_line"], case["other_line"]
    pet_first = stage_application(url, case, "PET_RELATED_FIRST", pet_line)
    before = settlement_row(url, case["settlement"])
    findings = one(
        url,
        "SELECT count(*) FILTER (WHERE pet_related) FROM app.inspection_damage_findings finding "
        "JOIN app.move_out_inspections inspection ON inspection.id=finding.inspection_id "
        "WHERE inspection.lease_id=%s",
        case["lease"],
    )
    assert (is_pet(case, pet_line), is_pet(case, other_line)) == (True, False)
    draft = record(
        case,
        command(
            case,
            pet_line,
            False,
            SettlementCreditStep(case["new_credit"], LINE, pet_line, 300),
            SettlementDepositStep(PET_REST, pet, LINE, pet_line, 12_200),
            SettlementDepositRefund(pet, 300, case["cash"], "Cash at the desk", case["customer"]),
            pet_remainder=STAFF,
        ),
    )
    # A draft has no effect until it is confirmed.
    assert (state(url, draft), is_pet(case, pet_line), reversed_application(url, pet_first)) == (
        "PENDING",
        True,
        False,
    )
    result = confirm(case, draft)
    correction = result["settlement_correction_id"]
    assert (is_pet(case, pet_line), is_pet(case, other_line)) == (False, False)
    assert one(
        url,
        "SELECT invoice_line_id,pet_related,evidence_reference,reason,actor_id,"
        "authorization_reference FROM app.settlement_pet_classifications "
        "WHERE settlement_correction_id=%s",
        correction,
    ) == (pet_line, False, EVIDENCE, REASON, case["person"], "financial.approve")
    assert reversed_application(url, pet_first)
    [paid] = result["deposit_application_ids"]
    assert application(url, paid) == (pet, pet_line, 12_200, "PET_REMAINDER_EXPLICIT")
    assert len(result["credit_application_ids"]) == 1
    [refunded] = result["deposit_refund_ids"]
    assert one(
        url,
        "SELECT source_deposit_id,usd_accounting_value_cents,recipient_customer_id "
        "FROM app.refunds WHERE id=%s",
        UUID(str(refunded)),
    ) == (pet, 300, case["customer"])
    assert (held(url, pet), outstanding(url, pet_line)) == (0, 0)
    assert effect_links(url, correction) == [
        "settlement_pet_classification_id",
        "deposit_application_reversal_id",
        "customer_credit_application_id",
        "deposit_application_id",
        "refund_id",
    ]
    # The closed Settlement and the inspection it relied on are unchanged.
    assert settlement_row(url, case["settlement"]) == before
    assert (
        one(
            url,
            "SELECT count(*) FILTER (WHERE pet_related) FROM app.inspection_damage_findings "
            "finding JOIN app.move_out_inspections inspection "
            "ON inspection.id=finding.inspection_id WHERE inspection.lease_id=%s",
            case["lease"],
        )
        == findings
    )
    assert one(
        url,
        "SELECT resulting_state->>'variant',resulting_state->>'pet_classification_id' "
        "FROM app.audit_events WHERE action='final_settlement.correction.confirmed' "
        "AND entity_id=%s",
        correction,
    ) == ("PET_DAMAGE_RECLASSIFICATION", result["classification"]["id"])
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])
    assert confirm(case, draft) == result
    # The line now has the corrected classification: the same correction again is refused.
    with pytest.raises(FinalSettlementConflictError) as again:
        record(case, command(case, pet_line, False))
    assert cause(again) == ("55000", ALREADY)


def test_the_draft_is_checked_under_the_corrected_classification_and_the_settlement_rules(
    migrated_database_url: str,
) -> None:
    """The draft's plan is checked under the corrected classification before its record exists:
    a plan that pays the line corrected to not pet damage from the Pet Deposit as pet damage is
    refused when it is recorded. At a normal end the Settlement rules hold too: the Pet Deposit's
    value may not be refunded while the line it can pay at step 5 still owes. Nothing is written."""
    url = migrated_database_url
    case = closed(url)
    pet, pet_line = case["pet"], case["pet_line"]
    credit = SettlementCreditStep(case["new_credit"], LINE, pet_line, 300)
    with pytest.raises(FinalSettlementConflictError) as as_pet:
        record(
            case,
            command(
                case,
                pet_line,
                False,
                credit,
                SettlementDepositStep(PET_FIRST, pet, LINE, pet_line, 12_200),
            ),
        )
    assert cause(as_pet) == ("55000", PET_DAMAGE_ONLY)
    # The whole 12,500 refunded after the Credit: every Deposit ends empty, so the open-debt rule
    # decides (P1 correction 1 of cause A: a 12,200 Refund left 300 held, refused earlier).
    refund = SettlementDepositRefund(
        pet, 12_500, case["cash"], "Cash at the desk", case["customer"]
    )
    with pytest.raises(FinalSettlementConflictError) as refunded:
        record(case, command(case, pet_line, False, credit, refund))
    assert cause(refunded) == (
        "55000",
        "No Deposit Refund while the Lease still has open debt that the Deposit could pay",
    )
    assert (held(url, pet), outstanding(url, pet_line), is_pet(case, pet_line)) == (0, 0, True)


def test_without_a_customer_choice_the_pet_deposit_value_is_refunded_and_the_line_stays_open(
    migrated_database_url: str,
) -> None:
    """At a BR-DEP-027 termination with no Customer choice for this correction, the remaining Pet
    Deposit pays no other debt (owner answer 3 to Q-2026-10-07-44): the 12,500 released from the
    line corrected to not pet damage is refunded to the Primary Tenant and the line stays open
    debt on the Customer's ledger (the Security Deposit was kept at this termination)."""
    url = migrated_database_url
    case = pet_paid_case(url)
    pet, pet_line = case["pet"], case["pet_line"]
    refund = SettlementDepositRefund(
        pet, 12_500, case["cash"], "Cash at the desk", case["customer"]
    )
    result = confirm(case, record(case, command(case, pet_line, False, refund)))
    assert result["deposit_application_ids"] == []
    [refunded] = result["deposit_refund_ids"]
    assert one(
        url,
        "SELECT source_deposit_id,usd_accounting_value_cents,recipient_customer_id "
        "FROM app.refunds WHERE id=%s",
        UUID(str(refunded)),
    ) == (pet, 12_500, case["customer"])
    assert (held(url, pet), outstanding(url, pet_line), is_pet(case, pet_line)) == (
        0,
        12_500,
        False,
    )
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_a_line_corrected_to_pet_damage_with_no_pet_deposit_money_only_records_it(
    migrated_database_url: str,
) -> None:
    """To pet damage while no Pet Deposit holds money: the Security Deposit still is the Deposit
    that pays the line, so nothing is reversed and only the classification record is written;
    the line's applications and both Deposits are unchanged."""
    url = migrated_database_url
    case = closed(url)
    other_line = case["other_line"]
    paying = (case["security_application"], case["pet_rest_application"])
    result = confirm(case, record(case, command(case, other_line, True)))
    assert is_pet(case, other_line) is True
    assert result["deposit_application_reversals"] == []
    assert [reversed_application(url, item) for item in paying] == [False, False]
    assert (held(url, case["security"]), held(url, case["pet"]), outstanding(url, other_line)) == (
        0,
        0,
        0,
    )
    assert effect_links(url, result["settlement_correction_id"]) == [
        "settlement_pet_classification_id"
    ]


def test_a_line_corrected_to_pet_damage_while_the_pet_deposit_holds_money_is_paid_by_it_first(
    migrated_database_url: str,
) -> None:
    """To pet damage while the Pet Deposit holds money (here 12,500 after an earlier correction,
    built by hand, reversed its pet damage application): the line's Security Deposit application
    is reversed (10,000 back), the Customer's Credit pays first (300), the Pet Deposit pays both
    pet damage lines first (12,200 and 300), the Security Deposit the rest (9,700), and its rest
    (300) is refunded. The remaining Pet Deposit application on the line stays."""
    url = migrated_database_url
    case = closed(url)
    pet, security = case["pet"], case["security"]
    pet_line, other_line = case["pet_line"], case["other_line"]
    pet_first = stage_application(url, case, "PET_RELATED_FIRST", pet_line)
    earlier = plan_draft(url, case, plan(), overlay(), result={})
    with psycopg.connect(url) as connection:
        found = connection.execute(
            "SELECT app.begin_settlement_correction(%s,%s,%s,'financial.approve')",
            (case["prop"], case["person"], earlier),
        ).fetchone()
        assert found is not None
        reversal = uuid4()
        connection.execute(
            "SELECT app.link_settlement_correction_effect(%s,'deposit_application_reversal_id',%s)",
            (found[0], reversal),
        )
        connection.execute(
            "INSERT INTO app.deposit_application_reversals(id,deposit_application_id,reason,"
            "occurred_at,actor_id,authorization_reference) VALUES(%s,%s,%s,"
            "clock_timestamp(),%s,'financial.approve')",
            (reversal, pet_first, REASON, case["person"]),
        )
    assert (held(url, pet), outstanding(url, pet_line)) == (12_500, 12_500)
    refund = SettlementDepositRefund(
        security, 300, case["cash"], "Cash at the desk", case["customer"]
    )
    result = confirm(
        case,
        record(
            case,
            command(
                case,
                other_line,
                True,
                SettlementCreditStep(case["new_credit"], LINE, pet_line, 300),
                SettlementDepositStep(PET_FIRST, pet, LINE, pet_line, 12_200),
                SettlementDepositStep(PET_FIRST, pet, LINE, other_line, 300),
                SettlementDepositStep(
                    SettlementDepositStepKind.SECURITY_DEPOSIT, security, LINE, other_line, 9_700
                ),
                refund,
            ),
        ),
    )
    assert [item["deposit_application_id"] for item in result["deposit_application_reversals"]] == [
        str(case["security_application"])
    ]
    assert not reversed_application(url, case["pet_rest_application"])
    assert [application(url, item) for item in result["deposit_application_ids"]] == [
        (pet, pet_line, 12_200, "PET_RELATED_FIRST"),
        (pet, other_line, 300, "PET_RELATED_FIRST"),
        (security, other_line, 9_700, "SECURITY_EXPLICIT"),
    ]
    assert len(result["deposit_refund_ids"]) == 1
    assert (
        held(url, pet),
        held(url, security),
        outstanding(url, pet_line),
        outstanding(url, other_line),
        is_pet(case, other_line),
    ) == (0, 0, 0, 0, True)


def test_the_step_rechecks_pet_damage_when_the_classification_changed_after_the_draft(
    migrated_database_url: str,
) -> None:
    """Carried from sub-slice 10c-2a-4 review round 2: the shared step's own re-check of pet
    damage refuses through the step. A correction draft, built by hand, plans to pay the other
    Damage line from the Pet Deposit as pet damage after it was corrected to pet damage; a later
    correction corrects it back to not pet damage; when the first correction's step runs, the Pet
    Deposit cannot pay it as pet damage (55000) and nothing is written."""
    url = migrated_database_url
    case = closed(url)
    pet, security, other_line = case["pet"], case["security"], case["other_line"]
    confirm(case, record(case, command(case, other_line, True)))
    steps = plan(
        credit_step(case["new_credit"], other_line, 300),
        deposit_step("PET_DEPOSIT_PET_DAMAGE", pet, other_line, 2_100),
        deposit_step("SECURITY_DEPOSIT", security, other_line, 5_700),
        refund_step(case, security, 4_300),
    )
    draft = plan_draft(
        url,
        case,
        steps,
        overlay({f"INVOICE_LINE:{other_line}": 8_100}, {str(security): 10_000, str(pet): 2_100}),
    )
    confirm(case, record(case, command(case, other_line, False)))
    assert is_pet(case, other_line) is False

    def step(connection: psycopg.Connection[Any]) -> None:
        release(connection, case, draft)
        post(connection, case, draft)

    assert failure(url, step) == ("55000", PET_DAMAGE_ONLY)
    assert state(url, draft) == "PENDING"
    assert (held(url, pet), held(url, security), outstanding(url, other_line)) == (0, 0, 0)


def test_a_br_dep_027_reclassification_needs_a_new_customer_choice(
    migrated_database_url: str,
) -> None:
    """Owner answer 3 to Q-2026-10-07-44 and BR-DEP-027: at an unpaid-Initial termination the
    remaining Pet Deposit pays the line corrected to not pet damage only by a Customer choice
    given for this correction; neither the Final Settlement's choice nor an earlier correction's
    is reused, at record and again at the confirm (review round 1: two drafts recorded while both
    were pending may carry the same choice; the second confirm is refused and stays pending)."""
    url = migrated_database_url
    case = pet_paid_case(url)
    pet, pet_line, other_line = case["pet"], case["pet_line"], case["other_line"]
    rest = SettlementDepositStep(PET_REST, pet, LINE, pet_line, 12_500)
    with pytest.raises(FinalSettlementConflictError) as reused:
        record(case, command(case, pet_line, False, rest, pet_remainder=CHOICE))
    assert cause(reused) == (
        "55000",
        "A correction needs the Customer's choice for this correction; the Final Settlement's "
        "choice is not reused",
    )
    new_choice = replace(CHOICE, customer_choice=NEW_CHOICE)
    first = record(case, command(case, pet_line, False, rest, pet_remainder=new_choice))
    second = record(case, command(case, pet_line, False, rest, pet_remainder=new_choice))
    result = confirm(case, first)
    [paid] = result["deposit_application_ids"]
    assert application(url, paid) == (pet, pet_line, 12_500, "PET_REMAINDER_EXPLICIT")
    assert (held(url, pet), outstanding(url, pet_line), is_pet(case, pet_line)) == (0, 0, False)
    earlier = (
        "55000",
        "A correction needs the Customer's choice for this correction; an earlier correction's "
        "choice is not reused",
    )
    with pytest.raises(FinalSettlementConflictError) as twice:
        confirm(case, second)
    assert cause(twice) == earlier
    assert state(url, second) == "PENDING"
    with pytest.raises(FinalSettlementConflictError) as again:
        record(case, command(case, other_line, True, pet_remainder=new_choice))
    assert cause(again) == earlier


def test_a_pet_classification_correction_refuses_what_it_cannot_correct(
    migrated_database_url: str,
) -> None:
    """Refusals: the same classification, a line that is not a Damage line billed from a finding,
    a line of another Invoice, malformed input; Staff cannot confirm; READ COMMITTED only; an
    exact repeat replays and a reused key is refused; a draft whose sources changed is stale and
    stays pending."""
    url = migrated_database_url
    case = closed(url)
    prop, pet_line, other_line = case["prop"], case["pet_line"], case["other_line"]
    with pytest.raises(FinalSettlementConflictError) as same:
        record(case, command(case, pet_line, True))
    assert cause(same) == ("55000", ALREADY)
    rent_line = UUID(
        str(one(url, "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", case["initial"])[0])
    )
    with pytest.raises(FinalSettlementConflictError) as rent:
        record(case, command(case, rent_line, True))
    assert cause(rent) == ("55000", NOT_ELIGIBLE)
    with pytest.raises(FinalSettlementNotFoundError) as elsewhere:
        record(case, command(case, pet_line, False, invoice_id=invoice_of(url, other_line)))
    assert cause(elsewhere) == ("P0002", "Invoice line was not found")
    # Review round 1: a Settlement that is still open, and a line of another Lease.
    other = {**leaving_case(url), "url": url}
    with pytest.raises(FinalSettlementConflictError) as still_open:
        record(other, command(other, other["pet_line"], False))
    assert cause(still_open) == (
        "55000",
        "A post-settlement correction needs a closed Final Settlement",
    )
    with pytest.raises(FinalSettlementNotFoundError) as foreign:
        record(case, command(case, other["pet_line"], False))
    assert cause(foreign) == (
        "P0002",
        "The corrected Invoice is not an Invoice of this Final Settlement",
    )
    with pytest.raises(psycopg.Error) as malformed, psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.record_settlement_pet_classification_draft(%s,%s,%s,%s,%s,%s,"
            "'final_settlements.prepare')",
            (
                prop,
                case["human"],
                uuid4(),
                case["settlement"],
                Jsonb({"invoice_id": str(invoice_of(url, pet_line)), "pet_related": "no"}),
                REASON,
            ),
        )
    assert malformed.value.sqlstate == "22023"
    classification = command(case, other_line, True)
    first = record(case, classification)
    assert record(case, classification) == first
    with pytest.raises(FinalSettlementKeyReused):
        record(case, replace(classification, evidence_reference="Another file"))
    second = record(case, replace(classification, idempotency_key=uuid4()))
    with pytest.raises(FinalSettlementAuthorizationError):
        corrections().confirm_pet_classification(prop, first, actor=preparer(case["human"], prop))
    with pytest.raises(psycopg.Error) as isolation, psycopg.connect(url) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        connection.execute(
            "SELECT app.confirm_settlement_pet_classification(%s,%s,%s,'financial.approve')",
            (prop, case["person"], first),
        )
    assert (isolation.value.sqlstate, isolation.value.diag.message_primary) == (
        "55000",
        "A post-settlement correction is confirmed at READ COMMITTED",
    )
    confirm(case, first)
    with pytest.raises(FinalSettlementStaleDraftError) as stale:
        confirm(case, second)
    assert cause(stale)[0] == "P5S02"
    assert (state(url, first), state(url, second)) == ("CONFIRMED", "PENDING")


INSERT_RECORD = (
    "INSERT INTO app.settlement_pet_classifications(id,settlement_correction_id,invoice_line_id,"
    "pet_related,evidence_reference,reason,recorded_at,actor_id,authorization_reference) "
    "VALUES (%s,%s,%s,%s,%s,%s,COALESCE(%s,clock_timestamp()),%s,'financial.approve')"
)
INVALID = ("23514", "Pet classification correction source is invalid")


def test_a_classification_record_is_written_only_as_its_own_draft_prepared_it(
    migrated_database_url: str,
) -> None:
    """DB-SETTLE-007 insert check (review round 1): inside a correction confirmed in this
    transaction by its approver, a record written by the table owner is accepted only linked to
    its own correction and exactly as its PET_DAMAGE_RECLASSIFICATION draft prepared it: not
    unlinked, not for another line, classification, evidence or reason, not by another person,
    not dated before the correction, and not dated at or before the line's latest record; the
    confirm dates its record after the line's latest one. Each refusal is refused by its own
    clause only: every other clause passes for that attempt (review round 2). The table is
    append-only."""
    url = migrated_database_url
    case = closed(url)
    pet_line, other_line = case["pet_line"], case["other_line"]

    def attempt(
        draft: UUID, *, link: bool = True, commit: bool = False, **changes: Any
    ) -> tuple[Any, Any] | None:
        values: dict[str, Any] = {
            "line": other_line,
            "pet": True,
            "evidence": EVIDENCE,
            "reason": REASON,
            "at": None,
            "actor": case["person"],
        }
        values.update(changes)
        with psycopg.connect(url) as connection:
            try:
                correction = begin(connection, case, draft)
                identity = uuid4()
                if link:
                    connection.execute(
                        LINK, (correction, "settlement_pet_classification_id", identity)
                    )
                connection.execute(
                    INSERT_RECORD,
                    (
                        identity,
                        correction,
                        values["line"],
                        values["pet"],
                        values["evidence"],
                        values["reason"],
                        values["at"],
                        values["actor"],
                    ),
                )
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
                if commit:
                    connection.commit()
            except psycopg.Error as error:
                return error.sqlstate, error.diag.message_primary
            finally:
                connection.rollback()
        return None

    draft = record(case, command(case, other_line, True))
    twin = record(case, command(case, other_line, True))
    assert attempt(draft) is None
    assert attempt(draft, link=False) == INVALID
    assert attempt(draft, evidence="Another file") == INVALID
    assert attempt(draft, reason="Another reason for the correction") == INVALID
    assert attempt(draft, actor=case["human"]) == INVALID
    hour_ago = one(url, "SELECT clock_timestamp()-interval '1 hour'")[0]
    assert attempt(draft, at=hour_ago) == INVALID
    assert state(url, draft) == "PENDING"
    result = confirm(case, draft)
    correction = result["settlement_correction_id"]
    # The other line is pet damage now. The twin draft says pet damage too, so a record that says
    # not pet damage differs from the current classification but not from its draft's.
    assert attempt(twin, pet=False) == INVALID
    back = record(case, command(case, other_line, False))
    # The pet damage line is pet damage: a not-pet record for it differs from its current
    # classification, but its draft names the other line.
    assert attempt(back, line=pet_line, pet=False) == INVALID
    assert attempt(back, pet=False) is None
    # Chronology: a hand-built record dated 4.5 seconds ahead is committed; a record dated now
    # differs from it and matches its own draft, but is not later than the line's latest record.
    ahead_at = one(url, "SELECT clock_timestamp()+interval '4.5 seconds'")[0]
    assert attempt(back, pet=False, commit=True, at=ahead_at) is None
    again = record(case, command(case, other_line, True))
    assert attempt(again) == INVALID
    # The confirm dates its record after the line's latest record.
    later = confirm(case, again)
    assert datetime.fromisoformat(str(later["classification"]["recorded_at"])) > ahead_at
    assert is_pet(case, other_line) is True
    for statement in (
        "UPDATE app.settlement_pet_classifications SET pet_related=false "
        "WHERE settlement_correction_id=%s",
        "DELETE FROM app.settlement_pet_classifications WHERE settlement_correction_id=%s",
    ):
        with pytest.raises(psycopg.Error), psycopg.connect(url) as connection:
            connection.execute(statement, (correction,))
    assert one(
        url,
        "SELECT pet_related FROM app.settlement_pet_classifications "
        "WHERE settlement_correction_id=%s",
        correction,
    ) == (True,)


def test_a_line_billed_from_an_inspection_superseded_before_closure_takes_the_change_to_pet_damage(
    migrated_database_url: str,
) -> None:
    """Review round 1 choice (10), tested in review round 2: a Damage line billed from an
    inspection superseded before closure is not pet damage under the inspection rule. Sub-slice
    10c-2a-7 (owner answers (a) to Q-2026-10-08-53, Q-2026-10-11-80 and Q-2026-10-11-85; renamed,
    the setup kept): the change to not pet damage is still refused as the same classification and
    nothing is recorded; the change to pet damage is recorded and confirmed with the full DL-032
    steps of this hand-closed Settlement (the Credit 400 and the Security Deposit 10,000 and the
    remaining Pet Deposit 2,100 on a staff reason pay the other line, the Pet Deposit 12,500 the
    pet line, its rest 5,400 is refunded), checked to the cent."""
    url = migrated_database_url
    case = {**leaving_case(url), "url": url}
    prop, human, lease, pet_line = case["prop"], case["human"], case["lease"], case["pet_line"]
    earlier = UUID(
        str(one(url, "SELECT id FROM app.move_out_inspections WHERE lease_id=%s", lease)[0])
    )
    inspection_flow().record(
        prop,
        lease,
        RecordMoveOutInspection(
            uuid4(),
            uuid4(),
            int(str(one(url, "SELECT version FROM app.leases WHERE id=%s", lease)[0])),
            today(url),
            "Corrected inspection condition",
            "Approved inspection",
            "Evidence-906",
            "Inspection corrected before the Final Settlement closed",
            (),
            supersedes_inspection_id=earlier,
        ),
        actor=inspection_actor(human, prop),
        request_id="pet-classification-superseded",
    )
    close(url, human, case["settlement"])
    assert is_pet(case, pet_line) is False
    with pytest.raises(FinalSettlementConflictError) as refused:
        record(case, command(case, pet_line, False))
    assert cause(refused) == ("55000", ALREADY)
    assert one(
        url,
        "SELECT count(*) FROM app.financial_drafts WHERE kind='SETTLEMENT_CORRECTION' "
        "AND payload->>'final_settlement_id'=%s",
        str(case["settlement"]),
    ) == (0,)
    case["person"] = approver(url)
    pet, security, other_line = case["pet"], case["security"], case["other_line"]
    result = confirm(
        case,
        record(
            case,
            command(
                case,
                pet_line,
                True,
                SettlementCreditStep(case["credit"], LINE, other_line, 400),
                SettlementDepositStep(PET_FIRST, pet, LINE, pet_line, 12_500),
                SettlementDepositStep(
                    SettlementDepositStepKind.SECURITY_DEPOSIT, security, LINE, other_line, 10_000
                ),
                SettlementDepositStep(PET_REST, pet, LINE, other_line, 2_100),
                SettlementDepositRefund(
                    pet, 5_400, case["cash"], "Cash at the desk", case["customer"]
                ),
                pet_remainder=STAFF,
            ),
        ),
    )
    correction = result["settlement_correction_id"]
    assert one(
        url,
        "SELECT invoice_line_id,pet_related,evidence_reference,reason,actor_id,"
        "authorization_reference FROM app.settlement_pet_classifications "
        "WHERE settlement_correction_id=%s",
        correction,
    ) == (pet_line, True, EVIDENCE, REASON, case["person"], "financial.approve")
    assert result["deposit_application_reversals"] == []
    assert len(result["credit_application_ids"]) == 1
    assert [application(url, item) for item in result["deposit_application_ids"]] == [
        (pet, pet_line, 12_500, "PET_RELATED_FIRST"),
        (security, other_line, 10_000, "SECURITY_EXPLICIT"),
        (pet, other_line, 2_100, "PET_REMAINDER_EXPLICIT"),
    ]
    [refunded] = result["deposit_refund_ids"]
    assert one(
        url,
        "SELECT source_deposit_id,usd_accounting_value_cents,recipient_customer_id "
        "FROM app.refunds WHERE id=%s",
        UUID(str(refunded)),
    ) == (pet, 5_400, case["customer"])
    assert (
        is_pet(case, pet_line),
        is_pet(case, other_line),
        held(url, pet),
        held(url, security),
        outstanding(url, pet_line),
        outstanding(url, other_line),
        int(one(url, "SELECT app.credit_available_value(%s)", case["credit"])[0]),
    ) == (True, False, 0, 0, 0, 0, 0)
    assert effect_links(url, correction) == [
        "settlement_pet_classification_id",
        "customer_credit_application_id",
        "deposit_application_id",
        "deposit_application_id",
        "deposit_application_id",
        "refund_id",
    ]
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_the_pet_classification_correction_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    # The confirm's lock order (the 8e-3 order, as 10c-2a-3): the Settlement's draft lock, the
    # Lease row FOR UPDATE, the shared lock function (which takes this variant's line Invoice FOR
    # UPDATE in its Invoice pass), the Refund methods FOR SHARE, and only then the decision.
    source = str(
        one(url, "SELECT prosrc FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure", CONFIRM)[0]
    )
    assert (
        source.index("'final-settlement-draft:'")
        < source.index("FROM app.leases WHERE id=v_settlement.lease_id FOR UPDATE")
        < source.index("PERFORM app.lock_settlement_correction_plan(p_draft);")
        # Review round 2: the Customer choice re-check runs under the Settlement's draft lock.
        < source.index("an earlier correction''s choice is not reused")
        < source.index("FROM app.refund_methods WHERE id=v_method AND active FOR SHARE")
        < source.index("app.begin_settlement_correction(")
    )
    locks = str(
        one(
            url,
            "SELECT prosrc FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure",
            "app.lock_settlement_correction_plan(uuid)",
        )[0]
    )
    assert "v_draft.payload->>'variant'='PET_DAMAGE_RECLASSIFICATION'" in locks
    with psycopg.connect(url) as connection:
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
            assert connection.execute(
                "SELECT has_table_privilege(%s,'app.settlement_pet_classifications',"
                "'SELECT,INSERT,UPDATE,DELETE')",
                (role,),
            ).fetchone() == (False,), role
            for function in INTERNAL:
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (role, function)
        for function in (RECORD, CONFIRM):
            assert [
                connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone()
                for role in ("prm_financial", "prm_runtime", "prm_bootstrap")
            ] == [(True,), (False,), (False,)], function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261109_105")
    assert revision is not None and revision.down_revision == "20261108_104"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, tuple[object, ...]], set[str], set[str]]:
        with psycopg.connect(database) as connection:
            functions = {
                str(row[0]): tuple(row[1:])
                for row in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                    "p.proacl::text FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
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

    with _temporary_migration_database("settlement_pet_classification") as temporary:
        alembic_command.upgrade(config, "20261108_104")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, "20261109_105")
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert after_relations - before_relations == {"app.settlement_pet_classifications"}
    assert before_relations <= after_relations
    assert after_triggers - before_triggers == {
        "app.settlement_pet_classifications:settlement_pet_classifications_append_only",
        "app.settlement_pet_classifications:settlement_pet_classifications_no_truncate",
        "app.settlement_pet_classifications:settlement_pet_classifications_source",
    }
    assert set(after_functions) - set(before_functions) == {*INTERNAL, RECORD, CONFIRM}
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set(CHANGED)
    for name in CHANGED:
        # Only the body changed: privileges kept.
        assert after_functions[name][1] == before_functions[name][1], name
