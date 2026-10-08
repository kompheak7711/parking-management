"""Post-settlement correction: the Customer choice checked again in the shared step (V1-056
sub-slice 10c-2a-6).

Owner answer 3 to Q-2026-10-07-44 and BR-DEP-027: a correction that uses the remaining Pet Deposit
by the Customer's choice needs a choice given for that correction; neither the Final Settlement's
choice nor an earlier correction's is reused. The recorders check it when a draft is recorded. Owner
answer 1 to Q-2026-10-08-52 (approved tightening) and the answer to Q-2026-10-08-54: every
correction confirm that uses a Customer choice checks it again, in the shared DL-032 step after
closure, so two drafts recorded while both were pending cannot both use one choice, whatever their
variants (BR-SETTLE-013, BR-AUTH-010).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from lease_deposit_forfeiture_test_support import forfeit_through_draft
from property_rental.deposit import PostgresDepositService
from property_rental.final_settlement import FinalSettlementConflictError, SettlementDepositStep
from property_rental.settlement_correction import RecordRefundCorrectionCommand
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_draft_migration import CHOICE, LINE, PET_FIRST, PET_REST, leaving_case
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding
from test_invoice_migration import financial_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_settlement_correction_migration import approver
from test_settlement_correction_plan_migration import (
    deposit_step,
    failure,
    overlay,
    pet_first_application,
    plan,
    plan_draft,
    post,
    refund_step,
    release_line,
)
from test_settlement_deposit_refund_correction_migration import command as refund_command
from test_settlement_deposit_refund_correction_migration import (
    confirm_refund,
    pet_paid_case,
    record_refund,
)
from test_settlement_extra_charge_migration import cause, state
from test_settlement_pet_classification_migration import command as classification_command
from test_settlement_pet_classification_migration import confirm as confirm_classification
from test_settlement_pet_classification_migration import is_pet
from test_settlement_pet_classification_migration import record as record_classification

STEP = "app.post_settlement_correction_plan(uuid,uuid,uuid)"
SHARED_CHOICE = "Primary Tenant agreed on 2026-10-08, by signed note, that the Pet Deposit pays"
OTHER_CHOICE = "Primary Tenant agreed again on 2026-10-09, by a second signed note"
EARLIER = (
    "55000",
    "A correction needs the Customer's choice for this correction; an earlier correction's "
    "choice is not reused",
)


def test_a_refund_confirm_checks_the_customer_choice_again_in_the_step(
    migrated_database_url: str,
) -> None:
    """The owner's case (review round 2 of sub-slice 10c-2a-5): at an unpaid-Initial termination
    (a BR-DEP-027 termination; the Pet Deposit's 20,000 paid the pet damage line, 12,500, and by
    the Customer's choice 7,500 of the other Damage line, which owes 5,000; each line on its own
    Invoice), a Refund correction of the other line and a pet classification correction of the
    pet line are recorded while both are pending, with the same new choice. The classification is
    confirmed first and leaves every balance as it was, so the Refund draft is not stale; its
    confirm is refused in the shared step (55000), it stays pending and writes nothing. The same
    Refund with a choice given for it then confirms."""
    url = migrated_database_url
    case = pet_paid_case(url)
    pet, pet_line, other_line = case["pet"], case["pet_line"], case["other_line"]
    shared = replace(CHOICE, customer_choice=SHARED_CHOICE)

    def refund(choice_text: str) -> RecordRefundCorrectionCommand:
        # 6,000 of the other line: its 7,500 Pet application is released whole; the line then
        # owes 6,500, which the remaining Pet Deposit pays by the choice, and 1,000 is refunded.
        return refund_command(
            case,
            other_line,
            6_000,
            SettlementDepositStep(PET_REST, pet, LINE, other_line, 6_500),
            settlement_refund(case, "pet", 1_000),
            pet_remainder=replace(CHOICE, customer_choice=choice_text),
        )

    refund_draft = record_refund(case, refund(SHARED_CHOICE))
    classification_draft = record_classification(
        case,
        classification_command(
            case,
            pet_line,
            False,
            SettlementDepositStep(PET_REST, pet, LINE, pet_line, 12_500),
            pet_remainder=shared,
        ),
    )
    confirm_classification(case, classification_draft)
    # Every balance is as before: the remaining Pet Deposit paid the pet line again.
    assert (held(url, pet), outstanding(url, pet_line), outstanding(url, other_line)) == (
        0,
        0,
        5_000,
    )
    assert is_pet(case, pet_line) is False

    with pytest.raises(FinalSettlementConflictError) as reused:
        confirm_refund(case, refund_draft)
    assert cause(reused) == EARLIER
    assert state(url, refund_draft) == "PENDING"
    assert one(
        url, "SELECT count(*) FROM app.settlement_corrections WHERE correlation_id=%s", refund_draft
    ) == (0,)
    assert (held(url, pet), outstanding(url, other_line)) == (0, 5_000)

    # The same Refund with a choice given for it: nothing else stood in the way. Its source
    # revision and recorded step result equal the refused draft's, so without the re-check the
    # refused draft would have confirmed (review round 1).
    again = record_refund(case, refund(OTHER_CHOICE))
    recorded = "SELECT source_revision,payload->'plan_result' FROM app.financial_drafts WHERE id=%s"
    assert one(url, recorded, again) == one(url, recorded, refund_draft)
    result = confirm_refund(case, again)
    assert [
        (item["application_stage"], item["amount_usd_cents"])
        for item in result["deposit_applications"]
    ] == [("PET_REMAINDER_EXPLICIT", 6_500)]
    [paid] = result["refunds"]
    assert (paid["source_deposit_id"], paid["amount_usd_cents"]) == (str(pet), 1_000)
    assert (held(url, pet), outstanding(url, pet_line), outstanding(url, other_line)) == (0, 0, 0)


def test_the_step_refuses_the_final_settlement_s_own_choice(migrated_database_url: str) -> None:
    """The step's other branch (review round 1): no recorder accepts the Final Settlement's own
    choice, so only a correction built by hand reaches it. The set-up of the 10c-2a-2 BR-DEP-027
    test as at HEAD (its correction reused the Settlement's choice text): the step refuses it
    (55000), the draft stays pending and no correction is written."""
    url = migrated_database_url
    case = leaving_case(url, unpaid_initial=True)
    prop, human = case["prop"], case["human"]
    pet, pet_line, other_line = case["pet"], case["pet_line"], case["other_line"]
    forfeit_through_draft(
        PostgresDepositService(financial_database_url(), prop, human), case["security"]
    )
    confirm_settlement(
        case,
        record_settlement(
            case,
            (
                SettlementDepositStep(PET_FIRST, pet, LINE, pet_line, 12_500),
                SettlementDepositStep(PET_REST, pet, LINE, other_line, 2_000),
                settlement_refund(case, "pet", 5_500),
            ),
            pet_remainder=CHOICE,
        ),
    )
    case["person"] = approver(url)
    pet_first = pet_first_application(url, case)
    draft = plan_draft(
        url,
        case,
        plan(
            deposit_step("PET_DEPOSIT_PET_DAMAGE", pet, pet_line, 8_500),
            deposit_step("PET_DEPOSIT_REMAINDER", pet, other_line, 2_000),
            refund_step(case, pet, 2_000),
            pet_remainder={
                "basis": "CUSTOMER_CHOICE",
                "customer_choice": CHOICE.customer_choice,
                "staff_reason": CHOICE.staff_reason,
            },
        ),
        overlay({f"INVOICE_LINE:{pet_line}": 8_500}, {str(pet): 12_500}),
    )

    def correction(connection: psycopg.Connection[Any]) -> None:
        release_line(connection, case, draft, (pet_first,), pet_line, 4_000)
        post(connection, case, draft)

    assert failure(url, correction) == (
        "55000",
        "A correction needs the Customer's choice for this correction; the Final Settlement's "
        "choice is not reused",
    )
    assert state(url, draft) == "PENDING"
    assert one(
        url, "SELECT count(*) FROM app.settlement_corrections WHERE correlation_id=%s", draft
    ) == (0,)
    assert (held(url, pet), outstanding(url, pet_line), outstanding(url, other_line)) == (
        0,
        0,
        10_500,
    )


def test_the_choice_recheck_is_in_the_step_and_forward_only(migrated_database_url: str) -> None:
    """The re-check sits in the shared step, after its locks and before it reads the plan and
    compares the result; only that function changes, and it keeps its owner, SECURITY DEFINER,
    settings and privileges (no role may call it)."""
    url = migrated_database_url
    source = str(
        one(url, "SELECT prosrc FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure", STEP)[0]
    )
    assert (
        source.index("PERFORM app.lock_settlement_correction_plan(p_draft);")
        < source.index("the Final Settlement''s choice is not reused")
        < source.index("an earlier correction''s choice is not reused")
        < source.index("v_plan:=v_draft.payload->'plan';")
        < source.index("app.settlement_correction_plan_result(")
    )
    assert "draft.id<>p_draft" in source
    with psycopg.connect(url) as connection:
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
            assert connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, STEP)
            ).fetchone() == (False,), role
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261110_106")
    assert revision is not None and revision.down_revision == "20261109_105"
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

    with _temporary_migration_database("settlement_correction_choice_recheck") as temporary:
        alembic_command.upgrade(config, "20261109_105")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, "20261110_106")
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert (after_relations, after_triggers) == (before_relations, before_triggers)
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {STEP}
    # The new body is exactly the old one with the single replacement (review round 1).
    [(anchor, replacement)] = revision.module.STEP_REPLACEMENTS
    assert after_functions[STEP][0] == str(before_functions[STEP][0]).replace(anchor, replacement)
    # Only the body changed: privileges, owner, SECURITY DEFINER and settings kept.
    assert after_functions[STEP][1:] == before_functions[STEP][1:]
    assert after_functions[STEP][3] is True
    assert "search_path=pg_catalog" in str(after_functions[STEP][4])
