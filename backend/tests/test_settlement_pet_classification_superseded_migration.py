"""A pet classification correction of a line billed from a superseded inspection (V1-056
sub-slice 10c-2a-7).

Owner answer (a) to Q-2026-10-08-53: a Damage line billed from a finding of a move-out inspection
of the Lease that was superseded before closure may take a `PET_DAMAGE_RECLASSIFICATION`
correction, only the change to pet damage (BR-SETTLE-013, BR-MOVEOUT-006, DB-SETTLE-007). The
to-pet reversal rule stays as confirmed by answer 6 to Q-2026-10-08-52: the line's Security
Deposit applications are reversed only while a Pet Deposit on the DL-032 path holds money,
otherwise only the classification record is written (DL-032, BR-SETTLE-008). Each case starts
from a real closure: the inspection is superseded before the confirm by one that repeats both
findings, so the pet line, which still points to the first inspection's finding, is not pet
damage at closure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.final_settlement import (
    FinalSettlementConflictError,
    SettlementCreditStep,
    SettlementDepositStep,
)
from property_rental.move_out_inspection import InspectionFinding, RecordMoveOutInspection
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import this_month
from test_final_settlement_draft_migration import (
    LINE,
    PET_FIRST,
    PET_REST,
    SECURITY,
    STAFF,
    leaving_case,
)
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding, today
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_out_inspection_migration import actor as inspection_actor
from test_move_out_inspection_migration import flow as inspection_flow
from test_settlement_correction_migration import approver
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_extra_charge_migration import cause
from test_settlement_held_value_refund_migration import return_only
from test_settlement_pet_classification_migration import (
    ALREADY,
    EVIDENCE,
    REASON,
    application,
    command,
    confirm,
    effect_links,
    is_pet,
    record,
    reversed_application,
    stage_application,
)
from test_settlement_return_reversal_migration import app_catalog

REVISION = "20261216_142"
COUNTS = (
    "SELECT (SELECT count(*) FROM app.financial_drafts),"
    "(SELECT count(*) FROM app.settlement_corrections),"
    "(SELECT count(*) FROM app.settlement_pet_classifications)"
)


def superseded_case(url: str) -> dict[str, Any]:
    """The leaving case whose move-out inspection is superseded before the real confirm by an
    inspection that repeats both findings (the pet finding under a new id). At closure the pet
    line is not pet damage: the Credit (400) pays the other line, the Security Deposit (10,000)
    and the remaining Pet Deposit (2,500) the pet line, the remaining Pet Deposit (12,100) the
    other line on a staff reason, and the Pet Deposit's rest (5,400) is refunded."""
    case = {**leaving_case(url, start_offset=this_month(url)), "url": url}
    prop, human, lease = case["prop"], case["human"], case["lease"]
    pet, security = case["pet"], case["security"]
    pet_line, other_line = case["pet_line"], case["other_line"]
    earlier = UUID(
        str(one(url, "SELECT id FROM app.move_out_inspections WHERE lease_id=%s", lease)[0])
    )
    inspection, pet_finding = uuid4(), uuid4()
    inspection_flow().record(
        prop,
        lease,
        RecordMoveOutInspection(
            uuid4(),
            inspection,
            int(str(one(url, "SELECT version FROM app.leases WHERE id=%s", lease)[0])),
            today(url),
            "Corrected inspection condition",
            "Approved inspection",
            "Evidence-907",
            "Inspection corrected before the Final Settlement closed",
            (
                InspectionFinding(pet_finding, "Scratched door by the pet", True),
                InspectionFinding(uuid4(), "Broken window latch", False),
            ),
            supersedes_inspection_id=earlier,
        ),
        actor=inspection_actor(human, prop),
        request_id=f"pet-classification-superseded-{inspection}",
    )
    assert (is_pet(case, pet_line), is_pet(case, other_line)) == (False, False)
    plan = (
        SettlementCreditStep(case["credit"], LINE, other_line, 400),
        SettlementDepositStep(SECURITY, security, LINE, pet_line, 10_000),
        SettlementDepositStep(PET_REST, pet, LINE, pet_line, 2_500),
        SettlementDepositStep(PET_REST, pet, LINE, other_line, 12_100),
        settlement_refund(case, "pet", 5_400),
    )
    confirm_settlement(case, record_settlement(case, plan, pet_remainder=STAFF))
    case["inspection"] = inspection
    case["pet_finding"] = pet_finding
    case["security_application"] = stage_application(url, case, "SECURITY_EXPLICIT", pet_line)
    case["pet_rest_application"] = stage_application(url, case, "PET_REMAINDER_EXPLICIT", pet_line)
    case["person"] = approver(url)
    return case


def classification(url: str, correction: object) -> tuple[Any, ...]:
    return tuple(
        one(
            url,
            "SELECT invoice_line_id,pet_related,evidence_reference,reason,actor_id,"
            "authorization_reference FROM app.settlement_pet_classifications "
            "WHERE settlement_correction_id=%s",
            correction,
        )
    )


def test_a_superseded_inspection_line_with_no_pet_deposit_money_only_records_the_change(
    migrated_database_url: str,
) -> None:
    """The change to not pet damage is refused as the same classification and writes nothing.
    The change to pet damage, its evidence reference naming the new inspection's pet finding,
    writes only the classification record (no Pet Deposit holds money): nothing is reversed and
    the Deposits, applications and line are unchanged. A later correction back to not pet damage
    passes by the latest-record rule (it corrects the earlier correction)."""
    url = migrated_database_url
    case = superseded_case(url)
    pet, security, pet_line = case["pet"], case["security"], case["pet_line"]
    paying = (case["security_application"], case["pet_rest_application"])
    assert [application(url, item) for item in paying] == [
        (security, pet_line, 10_000, "SECURITY_EXPLICIT"),
        (pet, pet_line, 2_500, "PET_REMAINDER_EXPLICIT"),
    ]
    before = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as same:
        record(case, command(case, pet_line, False))
    assert cause(same) == ("55000", ALREADY)
    assert one(url, COUNTS) == before
    evidence = (
        f"Pet finding {case['pet_finding']} of inspection {case['inspection']}, "
        "which superseded the billed inspection before closure"
    )
    result = confirm(case, record(case, command(case, pet_line, True, evidence_reference=evidence)))
    correction = result["settlement_correction_id"]
    assert classification(url, correction) == (
        pet_line,
        True,
        evidence,
        REASON,
        case["person"],
        "financial.approve",
    )
    assert result["deposit_application_reversals"] == []
    assert [reversed_application(url, item) for item in paying] == [False, False]
    assert (
        is_pet(case, pet_line),
        held(url, pet),
        held(url, security),
        outstanding(url, pet_line),
    ) == (True, 0, 0, 0)
    assert effect_links(url, correction) == ["settlement_pet_classification_id"]
    back = confirm(case, record(case, command(case, pet_line, False)))
    assert classification(url, back["settlement_correction_id"])[:3] == (
        pet_line,
        False,
        EVIDENCE,
    )
    assert back["deposit_application_reversals"] == []
    assert (is_pet(case, pet_line), outstanding(url, pet_line)) == (False, 0)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_a_superseded_inspection_line_set_to_pet_damage_is_paid_by_the_pet_deposit_first(
    migrated_database_url: str,
) -> None:
    """A return-only correction brings 2,000 of the Settlement's Pet Deposit Refund back, so the
    Pet Deposit on the DL-032 path holds 2,000. The change to pet damage then reverses the line's
    Security Deposit application (10,000 back), the Pet Deposit pays the line first (2,000), the
    Security Deposit the rest (8,000), and its rest (2,000) is refunded to the Customer; the
    remaining Pet Deposit application on the line (2,500) stays."""
    url = migrated_database_url
    case = superseded_case(url)
    pet, security, pet_line = case["pet"], case["security"], case["pet_line"]
    return_only(case, pet_refund(case), 2_000)
    assert (held(url, pet), held(url, security), outstanding(url, pet_line)) == (2_000, 0, 0)
    result = confirm(
        case,
        record(
            case,
            command(
                case,
                pet_line,
                True,
                SettlementDepositStep(PET_FIRST, pet, LINE, pet_line, 2_000),
                SettlementDepositStep(SECURITY, security, LINE, pet_line, 8_000),
                settlement_refund(case, "security", 2_000),
            ),
        ),
    )
    correction = result["settlement_correction_id"]
    assert classification(url, correction) == (
        pet_line,
        True,
        EVIDENCE,
        REASON,
        case["person"],
        "financial.approve",
    )
    assert [item["deposit_application_id"] for item in result["deposit_application_reversals"]] == [
        str(case["security_application"])
    ]
    assert reversed_application(url, case["security_application"])
    assert not reversed_application(url, case["pet_rest_application"])
    assert [application(url, item) for item in result["deposit_application_ids"]] == [
        (pet, pet_line, 2_000, "PET_RELATED_FIRST"),
        (security, pet_line, 8_000, "SECURITY_EXPLICIT"),
    ]
    [refunded] = result["deposit_refund_ids"]
    assert one(
        url,
        "SELECT source_deposit_id,usd_accounting_value_cents,recipient_customer_id "
        "FROM app.refunds WHERE id=%s",
        UUID(str(refunded)),
    ) == (security, 2_000, case["customer"])
    assert (
        is_pet(case, pet_line),
        held(url, pet),
        held(url, security),
        outstanding(url, pet_line),
        outstanding(url, case["other_line"]),
    ) == (True, 0, 0, 0, 0)
    assert effect_links(url, correction) == [
        "settlement_pet_classification_id",
        "deposit_application_reversal_id",
        "deposit_application_id",
        "deposit_application_id",
        "refund_id",
    ]
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_the_superseded_inspection_rule_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Migration 142 adds no function and changes only the two listed functions (each body
    exactly the old one with the module's replacements, each anchor found as often as listed;
    privileges, owner, definer and settings kept); no constraint or trigger changes; it is
    forward-only. Neither function is callable by an application role."""
    url = migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261215_141"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    patched = dict(revision.module.PATCHES)
    with psycopg.connect(url) as connection:
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
            for function in patched:
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (role, function)
    with _temporary_migration_database("settlement_pet_classification_superseded") as temporary:
        alembic_command.upgrade(config, "20261215_141")
        before_functions, before_constraints, before_triggers = app_catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = app_catalog(temporary)
    assert (after_triggers, after_constraints) == (before_triggers, before_constraints)
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set(patched)
    for name, replacements in patched.items():
        assert after_functions[name][1:] == before_functions[name][1:], name
        body = str(before_functions[name][0])
        for anchor, replacement, count in replacements:
            assert body.count(anchor) == count, name
            body = body.replace(anchor, replacement)
        assert after_functions[name][0] == body, name
