"""Post-settlement correction: recovery charges as placeholder lines in a Deposit receipt
correction's plan (V1-056 sub-slice 10e-2b-2).

The owner instruction of 2026-10-12 with the answers to Q-2026-10-12-88: a
DEPOSIT_RECEIPT_CORRECTION with a right receipt may also charge back a Refund paid from the
corrected receipt's Deposit on this Lease; the draft names that charge as a placeholder line with
its Customer, Lease and exact amount, the DL-032 plan may pay it, and at the confirm the real
charge equals the placeholder exactly and the steps on it pay the real line. Owner answer 1 to
Q-2026-10-12-89: a receipt correction must change the Deposit or the amount. The right-receipt
writer runs only inside its correction's confirm (10e-2b-1 review round 2).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from property_rental.final_settlement import (
    FinalSettlementConflictError,
    SettlementCreditStep,
    SettlementDepositStep,
)
from property_rental.settlement_correction import (
    CorrectionDepositReceipt,
    deposit_receipt_recovery_line_id,
    settlement_correction_draft_id,
)
from test_final_settlement_draft_migration import LINE, PET_FIRST, PET_REST, SECURITY, STAFF
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_move_migration import rows, value
from test_settlement_correction_plan_migration import credit_step, deposit_step, new_credit
from test_settlement_deposit_receipt_correction_migration import (
    REASON,
    available,
    confirm,
    counts,
    payload,
    receipt_of,
    record,
    request,
)
from test_settlement_deposit_receipt_rewrite_migration import receipts_of
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_extra_charge_migration import cause, state
from test_settlement_forfeiture_reversal_migration import (
    confirm_reversal,
    record_reversal,
    reversal_command,
)
from test_settlement_real_path_migration import AGREEMENT, two_signer_kept_case
from test_settlement_returned_payment_migration import closed_case, receipt_payment, reconciled

REVISION = "20261127_123"
INTERNAL = (
    "app.settlement_deposit_receipt_recovery_lines(uuid,uuid,jsonb)",
    "app.settlement_correction_line_id(uuid,jsonb,uuid)",
    "app.assert_settlement_correction_placeholder_lines(uuid,jsonb)",
)
PATCHED = {
    "app.assert_settlement_deposit_receipt_targets_allowed(uuid,jsonb,jsonb)",
    "app.write_correction_deposit_receipt(uuid,uuid,uuid,uuid,bigint,text,"
    "timestamp with time zone)",
    "app.record_settlement_deposit_receipt_correction_draft(uuid,uuid,uuid,uuid,jsonb,text,text)",
    "app.settlement_correction_plan_result(uuid,uuid,uuid,jsonb,jsonb)",
    "app.post_settlement_correction_plan(uuid,uuid,uuid)",
    "app.post_final_settlement_credit_application(uuid,uuid,uuid,uuid,integer)",
    "app.assert_settlement_correction_credit_application(app.customer_credit_applications)",
    "app.assert_settlement_correction_credit_application_confirmed("
    "app.customer_credit_applications)",
    "app.validate_deposit_application()",
}
SAME = "A receipt correction must change the Deposit or the amount"
NOT_NAMED = "The new receipt is not one the correction's draft names"
OUTSIDE_CONFIRM = "A new receipt is written only inside its correction's confirm"
MISMATCH = "A recovery charge does not match its placeholder line in the draft"
INVALID_OVERLAY = "Post-settlement correction overlay is invalid"
OUTSIDE = "The overlay names an obligation outside this Final Settlement"
CREDIT_FIRST = (
    "Each Customer's Credit must pay that Customer's open debt, up to what it can pay, "
    "before any Deposit pays"
)


def recovery_line(url: str, refund: UUID) -> tuple[Any, ...]:
    """The real recovery charge of a Refund: its line, the Invoice's Customer and Lease, the line's
    amount and category, and the correction that links its RECOVERED_BY_CHARGE row."""
    return one(
        url,
        "SELECT line.id,invoice.customer_id,invoice.lease_id,line.amount_usd_cents,line.category,"
        "effect.settlement_correction_id FROM app.refund_corrections recovery "
        "JOIN app.invoice_lines line "
        "ON line.authorized_obligation_id=recovery.recovery_obligation_id "
        "JOIN app.invoices invoice ON invoice.id=line.invoice_id "
        "JOIN app.settlement_correction_effects effect ON effect.refund_correction_id=recovery.id "
        "WHERE recovery.refund_id=%s AND recovery.correction_kind='RECOVERED_BY_CHARGE'",
        refund,
    )


def owner_refusal(url: str, sql: str, *parameters: object) -> tuple[Any, Any]:
    """The refusal of one statement run as the owner, rolled back; (None, None) when it passes."""
    with psycopg.connect(url) as connection:
        try:
            connection.execute(sql, parameters)
        except psycopg.Error as refused:
            connection.rollback()
            return refused.sqlstate, refused.diag.message_primary
        connection.rollback()
    return None, None


def test_a_pet_receipt_correction_pays_the_recovery_charge_its_placeholder_line_names(
    migrated_database_url: str,
) -> None:
    """The Pet Deposit's 20,000 receipt was really 18,000, and its 5,400 Settlement Refund was paid
    to the Primary Tenant. The draft names the Refund's recovery charge on this Lease as a
    placeholder line with the person and the exact amount (5,400); the plan pays it: the
    Customer's 1,000 Credit first, then pet damage (12,500), the other damage line (2,100) and
    3,400 of the charge from the new Pet Deposit money; 1,000 of the charge stays owed and 2,000
    stays with the Payment. At the confirm the real charge equals the placeholder to the cent
    (Customer, Lease, amount) and both the Credit and the Deposit steps pay the real line."""
    url = migrated_database_url
    case = closed_case(url)
    pet, customer, lease = case["pet"], case["customer"], case["lease"]
    pet_line, other_line = case["pet_line"], case["other_line"]
    refund = pet_refund(case)
    credit = new_credit(url, case, 1_000)
    receipt = receipt_of(url, pet)
    pet_payment = receipt_payment(url, pet)
    before_available = available(url, pet_payment)
    base = request(case, receipt, receipts=(CorrectionDepositReceipt(pet, 18_000),))
    draft_id = settlement_correction_draft_id(case["prop"], case["human"], base.idempotency_key)
    placeholder = deposit_receipt_recovery_line_id(draft_id, refund)
    draft = record(
        case,
        replace(
            base,
            steps=(
                SettlementCreditStep(credit, LINE, placeholder, 1_000),
                SettlementDepositStep(PET_FIRST, pet, LINE, pet_line, 12_500),
                SettlementDepositStep(PET_REST, pet, LINE, other_line, 2_100),
                SettlementDepositStep(PET_REST, pet, LINE, placeholder, 3_400),
            ),
            pet_remainder=STAFF,
        ),
    )
    assert draft == draft_id
    stored = payload(url, draft)
    # The draft shows the person and the exact amount of the placeholder line.
    assert stored["plan_overlay"] == {
        "obligations": {f"INVOICE_LINE:{pet_line}": 12_500, f"INVOICE_LINE:{other_line}": 2_100},
        "credits": {},
        "deposits": {},
        "deposits_after": {str(pet): 18_000},
        # Sub-slice 10e-2d (owner answer (b) to Q-2026-10-17-122): the corrected receipt's
        # Deposit, which the plan check counts without the payouts this correction undoes.
        "corrected_deposit_id": str(pet),
        "new_obligations": {
            str(placeholder): {
                "refund_id": str(refund),
                "customer_id": str(customer),
                "lease_id": str(lease),
                "amount_usd_cents": 5_400,
            }
        },
    }
    assert (
        stored["plan_result"]["open_total_usd_cents"],
        stored["plan_result"]["closing_balance_usd_cents"],
        stored["plan_result"]["closing_balances"],
    ) == (20_000, 1_000, [{"customer_id": str(customer), "open_usd_cents": 1_000}])
    result = confirm(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    real_line, *charge = recovery_line(url, refund)
    # The real charge equals the placeholder exactly.
    assert charge == [customer, lease, 5_400, "MISCELLANEOUS_CHARGES", correction]
    [credit_application] = result["credit_application_ids"]
    assert one(
        url,
        "SELECT application.customer_credit_id,detail.invoice_line_id,application.amount_usd_cents "
        "FROM app.customer_credit_applications application "
        "JOIN app.customer_credit_application_details detail "
        "ON detail.customer_credit_application_id=application.id WHERE application.id=%s",
        UUID(str(credit_application)),
    ) == (credit, real_line, 1_000)
    assert [
        one(
            url,
            "SELECT deposit_id,invoice_line_id,amount_usd_cents FROM app.deposit_applications "
            "WHERE id=%s",
            UUID(str(application)),
        )
        for application in result["deposit_application_ids"]
    ] == [(pet, pet_line, 12_500), (pet, other_line, 2_100), (pet, real_line, 3_400)]
    assert result["refund_ids"] == []
    assert (
        outstanding(url, real_line),
        outstanding(url, pet_line),
        outstanding(url, other_line),
        held(url, pet),
    ) == (1_000, 0, 0, 0)
    assert receipts_of(url, pet) == [(pet_payment, 20_000, True), (pet_payment, 18_000, False)]
    assert available(url, pet_payment) == before_available + 2_000
    reconciled(url, customer)

    # The mapping and the exact check, read as the owner after the commit.
    lines = stored["plan_overlay"]["new_obligations"]
    mapped = "SELECT app.settlement_correction_line_id(%s,%s,%s)"
    assert value(url, mapped, correction, Jsonb(lines), placeholder) == real_line
    assert value(url, mapped, correction, Jsonb(lines), other_line) == other_line
    check = "SELECT app.assert_settlement_correction_placeholder_lines(%s,%s)"
    assert owner_refusal(url, check, correction, Jsonb(lines)) == (None, None)
    entry = lines[str(placeholder)]
    for changed in (
        {str(placeholder): {**entry, "amount_usd_cents": 5_401}},
        {str(placeholder): {**entry, "customer_id": str(uuid4())}},
        {str(placeholder): {**entry, "lease_id": str(uuid4())}},
        {str(placeholder): {**entry, "refund_id": str(uuid4())}},
        {str(placeholder): entry, str(uuid4()): entry},
        {},
    ):
        assert owner_refusal(url, check, correction, Jsonb(changed)) == ("P5S02", MISMATCH), changed


def test_a_signer_outside_the_preview_keeps_the_credit_first_rule_on_a_placeholder_line(
    migrated_database_url: str,
) -> None:
    """Review round 1 on the real two-Signer closure: a FORFEITURE_REVERSAL refunded the Security
    Deposit's 10,000 to the second Signer, who is named on no Invoice of the Lease and holds 300 of
    Credit. With that Refund's recovery charge as a placeholder line, the plan check counts the
    Signer's Credit before the charge's Invoice exists: a plan whose Security Deposit pays the
    placeholder without that Credit is refused (Credit first), and the plan with it gives exactly
    the result the same plan gives on the real charge line once the charge is written (what the
    shared step compares at the confirm). The real path waits for sub-slice 10e-2c: this Deposit
    keeps its forfeiture ground, so a right receipt into it is refused until then."""
    url = migrated_database_url
    case = two_signer_kept_case(url)
    security, co_signer, lease = case["security"], case["co_signer"], case["lease"]
    reversal = confirm_reversal(
        case,
        record_reversal(
            case,
            reversal_command(
                case,
                settlement_refund(
                    case,
                    "security",
                    10_000,
                    recipient_customer_id=co_signer,
                    signer_agreement=AGREEMENT,
                ),
            ),
        ),
    )
    [paid] = reversal["refunds"]
    refund = UUID(str(paid["id"]))
    credit = new_credit(url, case, 300, co_signer)
    plan_result = "SELECT app.settlement_correction_plan_result(%s,%s,%s,%s,%s)-'source_revision'"

    def named() -> set[str]:
        customers = value(
            url,
            "SELECT app.final_settlement_preview(%s,%s,%s,"
            "ARRAY['final_settlements.prepare'])->'customers'",
            case["prop"],
            case["human"],
            case["settlement"],
        )
        return {str(person["customer_id"]) for person in customers}

    def arguments(target: object, *steps: dict[str, Any]) -> tuple[object, ...]:
        overlay: dict[str, Any] = {
            "obligations": {},
            "credits": {},
            "deposits": {},
            "deposits_after": {str(security): 1_000},
        }
        if target == placeholder:
            overlay["new_obligations"] = {
                str(placeholder): {
                    "refund_id": str(refund),
                    "customer_id": str(co_signer),
                    "lease_id": str(lease),
                    "amount_usd_cents": 10_000,
                }
            }
        return (
            case["prop"],
            case["human"],
            case["settlement"],
            Jsonb({"steps": list(steps), "pet_remainder": None}),
            Jsonb(overlay),
        )

    placeholder = uuid4()
    assert str(co_signer) not in named()
    deposit_only = deposit_step("SECURITY_DEPOSIT", security, placeholder, 1_000)
    assert owner_refusal(url, plan_result, *arguments(placeholder, deposit_only)) == (
        "55000",
        CREDIT_FIRST,
    )
    before = value(
        url,
        plan_result,
        *arguments(
            placeholder,
            credit_step(credit, placeholder, 300),
            deposit_step("SECURITY_DEPOSIT", security, placeholder, 1_000),
        ),
    )
    assert (
        before["open_total_usd_cents"],
        before["closing_balance_usd_cents"],
        before["closing_balances"],
    ) == (10_000, 8_700, [{"customer_id": str(co_signer), "open_usd_cents": 8_700}])

    # The 10e-2 correction (no right receipt) writes the real charge on the Lease.
    confirm(case, record(case, request(case, receipt_of(url, security))))
    real_line, *charge = recovery_line(url, refund)
    assert charge[:3] == [co_signer, lease, 10_000]
    assert str(co_signer) in named()
    assert owner_refusal(
        url,
        plan_result,
        *arguments(real_line, deposit_step("SECURITY_DEPOSIT", security, real_line, 1_000)),
    ) == ("55000", CREDIT_FIRST)
    after = value(
        url,
        plan_result,
        *arguments(
            real_line,
            credit_step(credit, real_line, 300),
            deposit_step("SECURITY_DEPOSIT", security, real_line, 1_000),
        ),
    )
    assert after == before


def test_the_same_receipt_again_and_a_receipt_outside_its_confirm_are_refused(
    migrated_database_url: str,
) -> None:
    """Owner answer 1 to Q-2026-10-12-89: the Security Deposit's 10,000 receipt written again into
    the same Deposit for the same 10,000 is refused (nothing written); 8,000 passes. The plan check
    refuses a malformed placeholder line (22023) and one on another Lease (55000). The receipt
    writer, inside the confirm's own transaction, refuses another amount, Deposit or Payment than
    the draft names; after the commit it refuses even the named receipt."""
    url = migrated_database_url
    case = closed_case(url)
    security, pet, other_line = case["security"], case["pet"], case["other_line"]
    receipt = receipt_of(url, security)
    payment = receipt_payment(url, security)
    before = counts(url)
    with pytest.raises(FinalSettlementConflictError) as same:
        record(
            case,
            request(
                case,
                receipt,
                receipts=(CorrectionDepositReceipt(security, 10_000),),
                steps=(SettlementDepositStep(SECURITY, security, LINE, other_line, 10_000),),
            ),
        )
    assert cause(same) == ("55000", SAME)
    assert counts(url) == before

    def plan_result(placeholder: dict[str, Any]) -> tuple[Any, Any]:
        return owner_refusal(
            url,
            "SELECT app.settlement_correction_plan_result(%s,%s,%s,%s,%s)",
            case["prop"],
            case["human"],
            case["settlement"],
            Jsonb({"steps": [], "pet_remainder": None}),
            Jsonb(
                {
                    "obligations": {},
                    "credits": {},
                    "deposits": {},
                    "new_obligations": {str(uuid4()): placeholder},
                }
            ),
        )

    entry = {
        "refund_id": str(uuid4()),
        "customer_id": str(case["customer"]),
        "lease_id": str(case["lease"]),
        "amount_usd_cents": 1_000,
    }
    for malformed in (
        {**entry, "amount_usd_cents": 0},
        {**entry, "amount_usd_cents": "1000"},
        {**entry, "amount_usd_cents": 9_000_000_000_000_001},
        {**entry, "customer_id": "not-a-uuid"},
        {**entry, "customer_id": None},
        {**entry, "refund_id": None},
        {key: item for key, item in entry.items() if key != "refund_id"},
    ):
        assert plan_result(malformed) == ("22023", INVALID_OVERLAY), malformed
    assert plan_result({**entry, "lease_id": str(uuid4())}) == ("55000", OUTSIDE)

    draft = record(
        case,
        request(
            case,
            receipt,
            receipts=(CorrectionDepositReceipt(security, 8_000),),
            steps=(SettlementDepositStep(SECURITY, security, LINE, other_line, 8_000),),
        ),
    )
    recorded = counts(url)
    other_payment = receipt_payment(url, pet)
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.confirm_settlement_deposit_receipt_correction("
            "%s,%s,%s,'financial.approve')",
            (case["prop"], case["person"], draft),
        )
        correction = connection.execute(
            "SELECT id FROM app.settlement_corrections WHERE correlation_id=%s", (draft,)
        ).fetchone()
        assert correction is not None
        for deposit, source, amount in (
            (security, payment, 7_999),
            (pet, payment, 8_000),
            (security, other_payment, 8_000),
        ):
            with pytest.raises(psycopg.Error) as unnamed, connection.transaction():
                connection.execute(
                    "SELECT app.write_correction_deposit_receipt(%s,%s,%s,%s,%s,%s,"
                    "clock_timestamp())",
                    (correction[0], case["person"], deposit, source, amount, REASON),
                )
            assert (unnamed.value.sqlstate, unnamed.value.diag.message_primary) == (
                "55000",
                NOT_NAMED,
            ), (deposit, source, amount)
        connection.rollback()
    assert (state(url, draft), counts(url)) == ("PENDING", recorded)
    result = confirm(case, draft)
    correction_id = UUID(str(result["settlement_correction"]["id"]))
    assert receipts_of(url, security) == [(payment, 10_000, True), (payment, 8_000, False)]
    after = counts(url)
    assert owner_refusal(
        url,
        "SELECT app.write_correction_deposit_receipt(%s,%s,%s,%s,8000,%s,clock_timestamp())",
        correction_id,
        case["person"],
        security,
        payment,
        REASON,
    ) == ("55000", OUTSIDE_CONFIRM)
    assert counts(url) == after
    assert receipts_of(url, security) == [(payment, 10_000, True), (payment, 8_000, False)]


def test_recovery_lines_are_least_privilege_and_forward_only(migrated_database_url: str) -> None:
    """No role calls the new internal functions; each is SECURITY DEFINER with the fixed search
    path; the migration adds only its functions, changes no table, constraint or trigger, changes
    only the listed functions (privileges and settings kept; each patched body is exactly the old
    one with the module's replacements) and is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in INTERNAL:
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (function, role)
            assert connection.execute(
                "SELECT p.prosecdef,p.proconfig[1] FROM pg_catalog.pg_proc p "
                "WHERE p.oid=CAST(%s AS regprocedure)",
                (function,),
            ).fetchone() == (True, "search_path=pg_catalog"), function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261126_122"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, tuple[object, ...]], set[str], set[str]]:
        functions = {
            str(row[0]): tuple(row[1:])
            for row in rows(
                database,
                "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                "p.proacl::text,p.proowner,p.prosecdef,p.proconfig::text "
                "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'",
            )
        }
        constraints = {
            ":".join(str(item) for item in row)
            for row in rows(
                database,
                "SELECT c.conrelid::regclass::text,c.conname,"
                "pg_catalog.pg_get_constraintdef(c.oid) "
                "FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_namespace n "
                "ON n.oid=c.connamespace WHERE n.nspname='app'",
            )
        }
        columns_and_triggers = {
            ":".join(str(item) for item in row)
            for row in rows(
                database,
                "SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod) "
                "FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='app' AND a.attnum>0 AND NOT a.attisdropped "
                "UNION ALL SELECT t.tgrelid::regclass::text,t.tgname,'trigger' "
                "FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='app' AND NOT t.tgisinternal",
            )
        }
        return functions, constraints, columns_and_triggers

    with _temporary_migration_database("settlement_deposit_receipt_recovery_line") as temporary:
        alembic_command.upgrade(config, "20261126_122")
        before_functions, before_constraints, before_tables = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_tables = catalog(temporary)
    assert (after_constraints, after_tables) == (before_constraints, before_tables)
    assert set(after_functions) - set(before_functions) == set(INTERNAL)
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED
    for name in PATCHED:
        assert after_functions[name][1:] == before_functions[name][1:], name
    assert {function for function, _ in revision.module.PATCHES} == PATCHED
    for function, replacements in revision.module.PATCHES:
        body = str(before_functions[function][0])
        for anchor, replacement in replacements:
            assert body.count(anchor) == 1, function
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function
