"""Post-settlement REFUND of a Deposit-paid Late-payment Charge (V1-056 sub-slice 10c-3b-2).

Owner answer 1 to Q-2026-10-09-66 and the owner answer to Q-2026-10-07-46, for a Late-payment
Charge: the REFUND correction of sub-slice 10c-3b-1 also releases Deposit applications on the
Charge, newest first with the Payment allocations and Credit applications (Q-41 answer 2). A
released Deposit application is reversed whole, as a linked Deposit application reversal (sub-slice
10c-2a-1); its value goes back to its Deposit, never to Customer Credit, and the shared DL-032 step
applies or refunds it (BR-SETTLE-008; Credit first, Q-42 answers 1 and 2). The 8a-1 refusal of a
Charge correction while a Deposit application stands lets through only the correction's own linked
Charge correction; every unlinked one stays refused.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.conninfo import make_conninfo

from property_rental.final_settlement import (
    FinalSettlementConflictError,
    SettlementCreditStep,
    SettlementDepositRefund,
    SettlementDepositStep,
    SettlementTargetKind,
)
from property_rental.late_payment import (
    CorrectionKind,
    CorrectLatePaymentChargeCommand,
    LatePaymentConflictError,
)
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_closed_refusal_migration import closed_refusal
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_draft_migration import LINE, PET_REST, STAFF, two_signer_case
from test_final_settlement_draft_migration import drafts as draft_service
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_migration import held, one, outstanding, preparer
from test_final_settlement_preview_migration import pay
from test_late_payment_migration import late_payment_actor
from test_late_payment_migration import service as late_payments
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_settlement_charge_reduction_migration import invoice_of
from test_settlement_correction_migration import (
    BEGIN,
    LINK,
    approver,
    correction_draft,
    settlement_row,
)
from test_settlement_extra_charge_migration import cause, state
from test_settlement_late_charge_reduction_migration import (
    charge_amount,
    charge_corrections,
    unpaid,
)
from test_settlement_late_charge_reduction_migration import command as reduction_command
from test_settlement_late_charge_reduction_migration import record as record_reduction
from test_settlement_late_charge_refund_migration import (
    CONFIRM,
    NOTE,
    REASON,
    available,
    charge_correction_of,
    command,
    confirm,
    drafts,
    pay_charge,
    record,
    refunds_of,
    released_of,
)

CHARGE = SettlementTargetKind.LATE_PAYMENT_CHARGE
INTERNAL = "app.settlement_correction_charge_correction_allowed(uuid,uuid,uuid)"
CHANGED = {
    "app.refuse_deposit_applied_obligation_change()": "DEPOSIT_APPLIED_REPLACEMENTS",
    "app.settlement_late_charge_refund_plan(uuid,uuid,jsonb)": "PLAN_REPLACEMENTS",
    CONFIRM: "CONFIRM_REPLACEMENTS",
}
DEPOSIT_PAID = "A Deposit application paid this obligation at Final Settlement"
EVERY_BALANCE = "Every remaining Deposit balance must be applied or refunded"
NO_REFUND = "No Deposit Refund while the Lease still has open debt that the Deposit could pay"
CREDIT_BEFORE_DEPOSITS = (
    "Each Customer's Credit must pay that Customer's open debt, up to what it can pay, before any "
    "Deposit pays"
)
LINKS = (
    "payment_allocation_reversal_id",
    "credit_application_reversal_id",
    "deposit_application_reversal_id",
    "late_payment_charge_correction_id",
    "payment_allocation_id",
    "customer_credit_application_id",
    "deposit_application_id",
    "refund_id",
)


def deposit_settled_case(url: str, on_charge: int) -> dict[str, Any]:
    """The overdue two-Signer Lease of sub-slice 8c, really closed (sub-slice 8e-3): the Signer's
    Credit pays 400 of the Signer's line and the remaining Pet Deposit (20,000), by staff decision,
    pays ``on_charge`` of the Late-payment Charge (8,000) and the rest of it to the Primary Tenant's
    Rent line (80,000). The Primary Tenant still owes 60,000 + ``on_charge`` of the Rent and the
    1,500 key card; the Signer owes 600; no Deposit holds money. A correction approver is ready."""
    case = {**two_signer_case(url, overdue_rent=True), "url": url}
    pet, charge = case["pet"], case["charge"]
    confirm_settlement(
        case,
        record_settlement(
            case,
            (
                SettlementCreditStep(case["credit"], LINE, case["signer_line"], 400),
                SettlementDepositStep(PET_REST, pet, CHARGE, charge, on_charge),
                SettlementDepositStep(PET_REST, pet, LINE, case["rent_line"], 20_000 - on_charge),
            ),
            pet_remainder=STAFF,
        ),
    )
    case["person"] = approver(url)
    case["key_card"] = invoice_of(url, case["tenant_line"])
    assert (held(url, pet), unpaid(url, charge)) == (0, 8_000 - on_charge)
    return case


def deposit_application(url: str, charge: object) -> UUID:
    found = one(
        url, "SELECT id FROM app.deposit_applications WHERE late_payment_charge_id=%s", charge
    )
    return UUID(str(found[0]))


def effects(url: str, correction_id: object) -> list[str]:
    """The name of each effect's one link, in effect order."""
    with psycopg.connect(url) as connection:
        rows = connection.execute(
            f"SELECT {','.join(LINKS)} FROM app.settlement_correction_effects "
            "WHERE settlement_correction_id=%s ORDER BY effect_sequence",
            (correction_id,),
        ).fetchall()
    return [next(name for name, value in zip(LINKS, row, strict=True) if value) for row in rows]


def released_in_draft(url: str, draft: UUID) -> list[dict[str, Any]]:
    found = one(
        url, "SELECT payload->'released_sources' FROM app.financial_drafts WHERE id=%s", draft
    )
    return cast(list[dict[str, Any]], found[0])


def correction_of(result: dict[str, Any]) -> object:
    return cast(dict[str, Any], result["settlement_correction"])["id"]


def reversals_of(result: dict[str, Any]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], result["deposit_application_reversals"])


def test_a_deposit_paid_charge_refund_gives_the_deposit_its_value_and_the_step_pays_again(
    migrated_database_url: str,
) -> None:
    """The remaining Pet Deposit paid the whole Charge (8,000) at closure. A Refund of 1,000
    releases that Deposit application: the draft keeps its whole amount beside the released part,
    the confirm reverses it whole as a linked Deposit application reversal (the draft's reason,
    financial.approve, the approver) and reduces the Charge to 7,000. The 8,000 go back to the Pet
    Deposit, never to Customer Credit. While the Rent stays open no Refund is allowed: an empty plan
    and a plan with a Deposit Refund are refused and write nothing (BR-SETTLE-008); the plan that
    pays the Charge's 7,000 and 1,000 of the Rent again from the Pet Deposit is confirmed with no
    Refund. The confirm waits for the Pet Deposit row; an exact repeat replays; the confirmed audit
    lists the reversal; the Settlement row is unchanged; the ledger reconciles."""
    url = migrated_database_url
    case = deposit_settled_case(url, 8_000)
    pet, charge, tenant = case["pet"], case["charge"], case["tenant"]
    application = deposit_application(url, charge)
    before = settlement_row(url, case["settlement"])
    credit_count = "SELECT count(*) FROM app.customer_credits WHERE customer_id=%s"
    credits_before = one(url, credit_count, tenant)
    assert outstanding(url, case["rent_line"]) == 68_000
    count = drafts(url)
    with pytest.raises(FinalSettlementConflictError) as unused:
        record(case, command(case, 1_000))
    assert cause(unused) == ("55000", EVERY_BALANCE)
    refund_too_early = (
        SettlementDepositStep(PET_REST, pet, CHARGE, charge, 7_000),
        SettlementDepositRefund(pet, 1_000, case["cash"], NOTE, tenant),
    )
    with pytest.raises(FinalSettlementConflictError) as early:
        record(case, command(case, 1_000, steps=refund_too_early, pet_remainder=STAFF))
    assert cause(early) == ("55000", NO_REFUND)
    assert drafts(url) == count
    steps = (
        SettlementDepositStep(PET_REST, pet, CHARGE, charge, 7_000),
        SettlementDepositStep(PET_REST, pet, LINE, case["rent_line"], 1_000),
    )
    draft = record(case, command(case, 1_000, steps=steps, pet_remainder=STAFF))
    assert released_in_draft(url, draft) == [
        {
            "kind": "DEPOSIT_APPLICATION",
            "id": str(application),
            "payment_id": None,
            "credit_id": None,
            "recipient_customer_id": str(tenant),
            "payer_customer_id": None,
            "deposit_id": str(pet),
            "application_usd_cents": 8_000,
            "released_usd_cents": 1_000,
        }
    ]
    with psycopg.connect(url) as holding:
        holding.execute("SELECT 1 FROM app.deposits WHERE id=%s FOR UPDATE", (pet,))
        with (
            pytest.raises(psycopg.errors.LockNotAvailable),
            psycopg.connect(make_conninfo(url, connect_timeout=10)) as waiting,
        ):
            waiting.execute("SET lock_timeout='1s'")
            waiting.execute(
                f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'financial.approve')",
                (case["prop"], case["person"], draft),
            )
        holding.rollback()
    assert (state(url, draft), charge_corrections(url, charge)) == ("PENDING", 0)
    result = confirm(case, draft)
    corrected = charge_correction_of(result)
    assert (
        corrected["correction_kind"],
        corrected["amount_usd_cents"],
        corrected["previous_obligation_usd_cents"],
        corrected["resulting_obligation_usd_cents"],
    ) == ("REDUCTION", 1_000, 8_000, 7_000)
    [reversal] = reversals_of(result)
    assert (
        reversal["deposit_application_id"],
        reversal["deposit_id"],
        reversal["amount_usd_cents"],
    ) == (str(application), str(pet), 8_000)
    assert one(
        url,
        "SELECT reason,actor_id,authorization_reference FROM app.deposit_application_reversals "
        "WHERE deposit_application_id=%s",
        application,
    ) == (REASON, case["person"], "financial.approve")
    assert [
        (item["deposit_id"], item["target_kind"], item["amount_usd_cents"])
        for item in cast(list[dict[str, Any]], result["deposit_applications"])
    ] == [(str(pet), "LATE_PAYMENT_CHARGE", 7_000), (str(pet), "INVOICE_LINE", 1_000)]
    assert (released_of(result), refunds_of(result)) == ([], [])
    correction = correction_of(result)
    assert effects(url, correction) == [
        "deposit_application_reversal_id",
        "late_payment_charge_correction_id",
        "deposit_application_id",
        "deposit_application_id",
    ]
    assert one(
        url,
        "SELECT resulting_state->'deposit_application_reversals'->0->>'id' FROM app.audit_events "
        "WHERE correlation_id=%s AND action='final_settlement.correction.confirmed'",
        correction,
    ) == (reversal["id"],)
    assert confirm(case, draft) == result
    assert (charge_amount(url, charge), unpaid(url, charge)) == (7_000, 0)
    assert (outstanding(url, case["rent_line"]), held(url, pet)) == (67_000, 0)
    assert one(url, credit_count, tenant) == credits_before
    assert settlement_row(url, case["settlement"]) == before
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, tenant)


def test_an_older_deposit_application_stays_and_only_the_linked_charge_correction_passes(
    migrated_database_url: str,
) -> None:
    """The Pet Deposit paid 3,000 of the Charge at closure. Since sub-slice 10c-3c-2 (owner answer
    (a) to Q-2026-10-10-70) the 10c-3a CHARGE_REDUCTION form records a reduction within this
    Charge's unpaid rest (withdrawn here by its preparer, so the rest is unchanged), and the
    one-call Charge correction stays refused after closure (P5S01). After closure the Primary
    Tenant pays the Rent, the key card and the Charge's 5,000. A Refund of 2,000 releases only the
    newest source (the Payment allocation); the older Deposit application the release does not
    reach stays and still pays the Charge, and the linked REDUCTION passes the 8a-1 refusal. The
    released Credit is refunded to the Primary Tenant, who owes nothing more. Outside its
    correction's transaction the allow function answers false for that same Charge correction."""
    url = migrated_database_url
    case = deposit_settled_case(url, 3_000)
    prop, human, tenant, charge = case["prop"], case["human"], case["tenant"], case["charge"]
    application = deposit_application(url, charge)
    count = drafts(url)
    # Sub-slice 10c-3c-2: the 1,000 is within the Charge's unpaid rest (5,000), so it is recorded.
    reduction = record_reduction(case, reduction_command(case, 1_000))
    assert (drafts(url), state(url, reduction)) == (count + 1, "PENDING")
    draft_service().withdraw(
        prop,
        reduction,
        "Recorded in error",
        prepare_capability="final_settlements.prepare",
        actor=preparer(human, prop),
    )
    assert state(url, reduction) == "WITHDRAWN"
    closed_refusal(
        LatePaymentConflictError,
        late_payments().correct_charge,
        prop,
        charge,
        CorrectLatePaymentChargeCommand(uuid4(), CorrectionKind.REDUCTION, "Reduced later", 100),
        actor=late_payment_actor(human, prop),
    )
    assert charge_corrections(url, charge) == 0
    pay(url, prop, human, tenant, case["rent"], case["rent_line"], 63_000)
    pay(url, prop, human, tenant, case["key_card"], case["tenant_line"], 1_500)
    allocation = pay_charge(case, 5_000)
    result = confirm(case, record(case, command(case, 2_000)))
    [released] = released_of(result)
    assert (
        released["source_kind"],
        released["reversed_payment_allocation_id"],
        released["released_usd_cents"],
    ) == ("PAYMENT_ALLOCATION", str(allocation), 2_000)
    assert reversals_of(result) == []
    assert one(
        url,
        "SELECT count(*) FROM app.deposit_application_reversals WHERE deposit_application_id=%s",
        application,
    ) == (0,)
    corrected = charge_correction_of(result)
    assert (
        corrected["correction_kind"],
        corrected["previous_obligation_usd_cents"],
        corrected["resulting_obligation_usd_cents"],
    ) == ("REDUCTION", 8_000, 6_000)
    assert one(
        url,
        "SELECT (app.late_payment_charge_application_summary(%s)"
        "->>'deposit_total_usd_cents')::bigint",
        charge,
    ) == (3_000,)
    assert (charge_amount(url, charge), unpaid(url, charge)) == (6_000, 0)
    [refund] = refunds_of(result)
    assert (refund["amount_usd_cents"], refund["recipient_customer_id"]) == (2_000, str(tenant))
    assert effects(url, correction_of(result)) == [
        "payment_allocation_reversal_id",
        "late_payment_charge_correction_id",
        "payment_allocation_id",
        "refund_id",
    ]
    allowed = f"SELECT {INTERNAL.split('(')[0]}(%s,%s,%s)"
    for actor in (case["person"], None):
        assert one(url, allowed, charge, corrected["id"], actor) == (False,), actor
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, tenant)


def test_a_mixed_charge_is_released_across_a_payment_and_a_deposit_and_credit_pays_first(
    migrated_database_url: str,
) -> None:
    """The Pet Deposit paid 3,000 of the Charge at closure and a Payment the other 5,000 after it
    (newer); the Rent and the Signer's line are paid, the key card (1,500) is open. A Refund of
    6,000 releases newest first across both kinds: the whole Payment allocation (5,000, Credit of
    the Primary Tenant) and the whole Deposit application, of which 1,000 is released and 2,000
    stays the Charge's open obligation. Q-42 answers 1 and 2: a plan that lets the returned Pet
    Deposit money pay the Primary Tenant's debt while that Customer's Credit is unused is refused;
    the plan where the released Credit pays the Charge's 2,000 and the key card first is
    confirmed, then the Pet Deposit's 3,000 and the Credit's 1,500 left are refunded to the Primary
    Tenant."""
    url = migrated_database_url
    case = deposit_settled_case(url, 3_000)
    prop, human, tenant = case["prop"], case["human"], case["tenant"]
    pet, charge = case["pet"], case["charge"]
    application = deposit_application(url, charge)
    pay(url, prop, human, tenant, case["rent"], case["rent_line"], 63_000)
    signer_invoice = invoice_of(url, case["signer_line"])
    pay(url, prop, human, case["co_signer"], signer_invoice, case["signer_line"], 600)
    allocation = pay_charge(case, 5_000)
    count = drafts(url)
    deposit_first = (
        SettlementDepositStep(PET_REST, pet, CHARGE, charge, 2_000),
        SettlementDepositStep(PET_REST, pet, LINE, case["tenant_line"], 1_000),
    )
    with pytest.raises(FinalSettlementConflictError) as refused:
        record(case, command(case, 6_000, steps=deposit_first, pet_remainder=STAFF))
    assert cause(refused) == ("55000", CREDIT_BEFORE_DEPOSITS)
    assert drafts(url) == count
    steps = (
        SettlementCreditStep(allocation, CHARGE, charge, 2_000),
        SettlementCreditStep(allocation, LINE, case["tenant_line"], 1_500),
        SettlementDepositRefund(pet, 3_000, case["cash"], NOTE, tenant),
    )
    draft = record(case, command(case, 6_000, steps=steps))
    assert [
        (item["kind"], item["id"], item.get("application_usd_cents"), item["released_usd_cents"])
        for item in released_in_draft(url, draft)
    ] == [
        ("PAYMENT_ALLOCATION", str(allocation), None, 5_000),
        ("DEPOSIT_APPLICATION", str(application), 3_000, 1_000),
    ]
    result = confirm(case, draft)
    [released] = released_of(result)
    assert (
        released["reversed_payment_allocation_id"],
        released["replacement_payment_allocation_id"],
        released["released_usd_cents"],
    ) == (str(allocation), None, 5_000)
    credit = released["customer_credit_id"]
    assert [item["deposit_application_id"] for item in reversals_of(result)] == [str(application)]
    corrected = charge_correction_of(result)
    assert (
        corrected["correction_kind"],
        corrected["amount_usd_cents"],
        corrected["resulting_obligation_usd_cents"],
    ) == ("REDUCTION", 6_000, 2_000)
    assert [
        (item["customer_credit_id"], item["target_kind"], item["amount_usd_cents"])
        for item in cast(list[dict[str, Any]], result["credit_applications"])
    ] == [(credit, "LATE_PAYMENT_CHARGE", 2_000), (credit, "INVOICE", 1_500)]
    assert [
        (
            item["source_deposit_id"],
            item["source_customer_credit_id"],
            item["recipient_customer_id"],
            item["amount_usd_cents"],
        )
        for item in refunds_of(result)
    ] == [(str(pet), None, str(tenant), 3_000), (None, credit, str(tenant), 1_500)]
    # BR-REFUND-014: both Refunds keep the draft's one method and reference note.
    assert {(item["refund_method_id"], item["reference_note"]) for item in refunds_of(result)} == {
        (str(case["cash"]), NOTE)
    }
    assert effects(url, correction_of(result)) == [
        "payment_allocation_reversal_id",
        "deposit_application_reversal_id",
        "late_payment_charge_correction_id",
        "customer_credit_application_id",
        "customer_credit_application_id",
        "refund_id",
        "refund_id",
    ]
    assert (charge_amount(url, charge), unpaid(url, charge)) == (2_000, 0)
    assert (outstanding(url, case["tenant_line"]), held(url, pet), available(url, credit)) == (
        0,
        0,
        0,
    )
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, tenant)
        assert_reconciled(connection, case["co_signer"])


def test_a_linked_charge_correction_under_a_draft_naming_no_charge_is_refused_by_8a_1(
    migrated_database_url: str,
) -> None:
    """Owner answer to Q-2026-10-07-46 for a Charge, by hand inside one correction of this
    Settlement: the remaining Pet Deposit paid the whole Charge (8,000). Renamed in sub-slice
    10c-3c-2 (owner answer (a) to Q-2026-10-16-117): the earlier name said the row passes 8a-1.
    Sub-slice 10c-3c-1 (owner answer 3 to Q-2026-10-10-69, the approved hardening): this
    hand-built correction's draft names no Charge, so a Charge correction linked to it is refused
    by the 8a-1 refusal (P4603) whether its approver or another actor writes it; the commit-time
    check (a REDUCTION below the Deposit application that still pays the Charge, 23514) is kept
    with a matching row in test_settlement_correction_allow_hardening_migration.py. Nothing is
    written."""
    url = migrated_database_url
    case = deposit_settled_case(url, 8_000)
    charge = case["charge"]
    draft = correction_draft(url, case)
    allowed = f"SELECT {INTERNAL.split('(')[0]}(%s,%s,%s)"

    def reduce_by(actor: UUID) -> psycopg.Error:
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            found = connection.execute(
                BEGIN, (case["prop"], case["person"], draft, "financial.approve")
            ).fetchone()
            assert found is not None
            row = uuid4()
            connection.execute(LINK, (found[0], "late_payment_charge_correction_id", row))
            connection.execute(
                "INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,"
                "correction_kind,amount_usd_cents,reverses_correction_id,reason,"
                "previous_obligation_usd_cents,resulting_obligation_usd_cents,occurred_at,actor_id,"
                "authorization_reference,correlation_id) VALUES (%s,%s,'REDUCTION',1000,NULL,%s,"
                "8000,7000,app.settlement_late_charge_instant(%s,NULL),%s,'financial.approve',%s)",
                (row, charge, REASON, charge, actor, found[0]),
            )
            assert connection.execute(allowed, (charge, row, actor)).fetchone() == (True,)
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        return refused.value

    # Sub-slice 10c-3c-1: the insert is refused before the in-transaction call of the old
    # three-argument function, which is no longer reached.
    overpaid = reduce_by(case["person"])
    assert (overpaid.sqlstate, overpaid.diag.message_primary) == ("P4603", DEPOSIT_PAID)
    other = reduce_by(case["human"])
    assert (other.sqlstate, other.diag.message_primary) == ("P4603", DEPOSIT_PAID)
    assert (state(url, draft), charge_corrections(url, charge)) == ("PENDING", 0)
    assert (charge_amount(url, charge), unpaid(url, charge)) == (8_000, 0)


def test_late_charge_deposit_refund_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """No role calls the new allow function (SECURITY DEFINER, search_path pg_catalog); no time
    limit (BR-SETTLE-013); the migration adds only that function, changes only the three patched
    functions (each new body exactly the old one with its replacements, privileges, owner,
    SECURITY DEFINER and settings kept) and no table or trigger; it is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
            assert connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, INTERNAL)
            ).fetchone() == (False,), role
        assert connection.execute(
            "SELECT prosecdef,proconfig::text FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure",
            (INTERNAL,),
        ).fetchone() == (True, "{search_path=pg_catalog}")
    for function in (INTERNAL, *CHANGED):
        source = str(
            one(url, "SELECT prosrc FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure", function)[
                0
            ]
        )
        assert re.search(r"(?<![a-z_])age\(", source) is None, function
        assert set(re.findall(r"interval '([^']*)'", source)) <= {"1 microsecond"}, function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261118_114")
    assert revision is not None and revision.down_revision == "20261117_113"
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
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='app'"
                ).fetchall()
            }
            triggers = {
                f"{row[0]}:{row[1]}:{row[2]}"
                for row in connection.execute(
                    "SELECT t.tgrelid::regclass::text,t.tgname,t.tgfoid::regprocedure::text "
                    "FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND NOT t.tgisinternal"
                ).fetchall()
            }
        return functions, relations, triggers

    with _temporary_migration_database("settlement_late_charge_deposit_refund") as temporary:
        alembic_command.upgrade(config, "20261117_113")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, "20261118_114")
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert (after_relations, after_triggers) == (before_relations, before_triggers)
    assert set(after_functions) - set(before_functions) == {INTERNAL}
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set(CHANGED)
    for function, replacements in CHANGED.items():
        body = str(before_functions[function][0])
        for anchor, replacement in getattr(revision.module, replacements):
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function
        assert after_functions[function][1:] == before_functions[function][1:], function
