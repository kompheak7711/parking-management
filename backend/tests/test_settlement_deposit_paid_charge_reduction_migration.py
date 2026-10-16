"""A charge reduction of the unpaid rest of a partly Deposit-paid obligation (V1-056 sub-slice
10c-3c-2).

Owner answer (a) to Q-2026-10-10-70: after the Lease's Final Settlement is closed, a
`CHARGE_REDUCTION` correction (the 10c-3a Late-payment Charge form and the 10c-1a Invoice-line
form) accepts an obligation that a Deposit application partly paid, within its unpaid rest (the
current obligation less every active application, Deposit applications not reversed included).
The Deposit application stays; nothing is released and no money moves; a reduction above the
unpaid rest stays refused, and an obligation the Deposit application paid with no unpaid rest left
keeps the Deposit refusal (owner answer (a) to Q-2026-10-11-80) (BR-SETTLE-013, BR-SETTLE-012,
BR-LATE-005, BR-AUTH-010, DL-032).
Owner answer 3 of 2026-10-16 to the 10c-3c-1 report: both writers reach the 8a-1 refusal here,
because an active Deposit application pays the obligation when the confirm writes its linked row,
and the row meets the hardened rule of sub-slice 10c-3c-1 (its reference or correlation names the
correction, whose draft names exactly that obligation).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.billing import PostgresRentBillingService
from property_rental.final_settlement import (
    FinalSettlementConflictError,
    SettlementCreditStep,
    SettlementDepositStep,
    SettlementTargetKind,
)
from property_rental.late_payment import CorrectionKind, CorrectLatePaymentChargeCommand
from rent_month_test_support import bill_unbilled_rent_months
from test_billing_service_migration import add_service, authenticated, initial_command
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_draft_migration import CHOICE, LINE, PET_REST, STAFF, two_signer_case
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_migration import held, one, outstanding, pet_deposit, start, today
from test_invoice_migration import financial_database_url
from test_late_payment_migration import late_payment_actor
from test_late_payment_migration import service as late_payments
from test_lease_migration import create_draft, setup_sources, sign_lease
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_settlement_charge_reduction_migration import adjustments, invoice_of, reduction
from test_settlement_charge_reduction_migration import record as record_line_reduction
from test_settlement_correction_migration import approver, settlement_row
from test_settlement_extra_charge_migration import approving, cause, corrections
from test_settlement_late_charge_reduction_migration import (
    RELEASES_PAID,
    charge_amount,
    charge_corrections,
    unpaid,
)
from test_settlement_late_charge_reduction_migration import command as charge_reduction
from test_settlement_late_charge_reduction_migration import confirm as confirm_charge_reduction
from test_settlement_late_charge_reduction_migration import record as record_charge_reduction
from test_settlement_return_reversal_migration import app_catalog
from test_termination_deposit_migration import terminate

REVISION = "20261218_144"
CHARGE = SettlementTargetKind.LATE_PAYMENT_CHARGE
DEPOSIT_PAID = "A Deposit application paid this obligation at Final Settlement"
DRAFTS = "SELECT count(*) FROM app.financial_drafts"
APPLICATION = (
    "SELECT application.amount_usd_cents,application.occurred_at,(SELECT count(*) FROM "
    "app.deposit_application_reversals reversal WHERE reversal.deposit_application_id="
    "application.id) FROM app.deposit_applications application WHERE "
)
DRAFT_OF = (
    "SELECT draft.payload->>'variant',draft.payload->'target_kind',draft.payload->'reduction' "
    "FROM app.settlement_corrections correction JOIN app.financial_drafts draft "
    "ON draft.id=correction.correlation_id WHERE correction.id=%s"
)
EFFECTS = (
    "SELECT array_agg(invoice_adjustment_id ORDER BY effect_sequence),"
    "array_agg(late_payment_charge_correction_id ORDER BY effect_sequence) "
    "FROM app.settlement_correction_effects WHERE settlement_correction_id=%s"
)
Steps = Callable[[dict[str, Any]], tuple[SettlementDepositStep, ...]]


def closed_two_signer_case(url: str, *, charge_before: int, pet_steps: Steps) -> dict[str, Any]:
    """The overdue two-Signer Lease of sub-slice 8c, its Late-payment Charge of 8,000 first
    reduced to ``charge_before`` by the one-call Charge correction while the Settlement is still
    open, then really closed by the 8e-3 confirm: the Signer's Credit pays 400 of the Signer's line
    and the remaining Pet Deposit (20,000), by staff decision, pays ``pet_steps``; no Deposit holds
    money. A correction approver is ready."""
    case = {**two_signer_case(url, overdue_rent=True), "url": url}
    prop, human, charge = case["prop"], case["human"], case["charge"]
    if charge_before != 8_000:
        late_payments().correct_charge(
            prop,
            charge,
            CorrectLatePaymentChargeCommand(
                uuid4(),
                CorrectionKind.REDUCTION,
                "The Late-payment Charge used the wrong rate",
                8_000 - charge_before,
            ),
            actor=late_payment_actor(human, prop),
        )
    assert charge_amount(url, charge) == charge_before
    confirm_settlement(
        case,
        record_settlement(
            case,
            (
                SettlementCreditStep(case["credit"], LINE, case["signer_line"], 400),
                *pet_steps(case),
            ),
            pet_remainder=STAFF,
        ),
    )
    assert held(url, case["pet"]) == 0
    case["person"] = approver(url)
    return case


def drafts(url: str) -> int:
    return int(one(url, DRAFTS)[0])


def test_a_charge_the_pet_deposit_partly_paid_is_reduced_within_its_unpaid_rest(
    migrated_database_url: str,
) -> None:
    """The Q-2026-10-10-70 example to the cent: a 3,000 Late-payment Charge, 2,000 of it paid by
    the Pet Deposit at closure (the rest of the Pet Deposit, 18,000, pays the Rent line). After
    closure a reduction of 1,001 is refused (it would release paid value) and nothing is written;
    a reduction of 1,000 is recorded and confirmed as one linked REDUCTION (3,000 to 2,000), so the
    Charge owes nothing, and a further reduction keeps the Deposit refusal (owner answer (a) to
    Q-2026-10-11-80). The Deposit application stays as it was (2,000, not reversed), no Deposit
    holds money, the closed Settlement row is unchanged and the ledger reconciles. Owner answer 3
    of 2026-10-16: the Deposit application was active when the confirm wrote its Charge correction,
    so the 8a-1 refusal ran and let it through; its correlation is the correction, whose draft
    names exactly this Charge."""
    url = migrated_database_url
    case = closed_two_signer_case(
        url,
        charge_before=3_000,
        pet_steps=lambda case: (
            SettlementDepositStep(PET_REST, case["pet"], CHARGE, case["charge"], 2_000),
            SettlementDepositStep(PET_REST, case["pet"], LINE, case["rent_line"], 18_000),
        ),
    )
    charge, tenant = case["charge"], case["tenant"]
    on_charge = APPLICATION + "application.late_payment_charge_id=%s"
    application = one(url, on_charge, charge)
    assert (application[0], application[2]) == (2_000, 0)
    assert (charge_amount(url, charge), unpaid(url, charge)) == (3_000, 1_000)
    before = settlement_row(url, case["settlement"])
    count = drafts(url)
    with pytest.raises(FinalSettlementConflictError) as above_rest:
        record_charge_reduction(case, charge_reduction(case, 1_001))
    assert cause(above_rest) == ("55000", RELEASES_PAID)
    assert (drafts(url), charge_corrections(url, charge)) == (count, 1)
    result = confirm_charge_reduction(
        case, record_charge_reduction(case, charge_reduction(case, 1_000))
    )
    corrected = cast(dict[str, Any], result["late_payment_charge_correction"])
    assert (
        corrected["correction_kind"],
        corrected["amount_usd_cents"],
        corrected["previous_obligation_usd_cents"],
        corrected["resulting_obligation_usd_cents"],
    ) == ("REDUCTION", 1_000, 3_000, 2_000)
    assert (charge_amount(url, charge), unpaid(url, charge)) == (2_000, 0)
    assert one(url, on_charge, charge) == application
    assert held(url, case["pet"]) == 0
    # Owner answer (a) to Q-2026-10-11-80: with no unpaid rest left, the Deposit-paid Charge keeps
    # the Deposit refusal.
    count = drafts(url)
    with pytest.raises(FinalSettlementConflictError) as no_rest:
        record_charge_reduction(case, charge_reduction(case, 1))
    assert cause(no_rest) == ("55000", DEPOSIT_PAID)
    assert (drafts(url), charge_corrections(url, charge)) == (count, 2)
    correction = str(cast(dict[str, Any], result["settlement_correction"])["id"])
    row = one(
        url,
        "SELECT correlation_id,occurred_at FROM app.late_payment_charge_corrections WHERE id=%s",
        corrected["id"],
    )
    assert str(row[0]) == correction and application[1] < row[1]
    assert one(url, EFFECTS, correction) == ([None], [UUID(str(corrected["id"]))])
    assert one(url, DRAFT_OF, correction) == (
        "CHARGE_REDUCTION",
        "LATE_PAYMENT_CHARGE",
        {"late_payment_charge_id": str(charge), "amount_usd_cents": 1_000},
    )
    assert settlement_row(url, case["settlement"]) == before
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, tenant)


def test_an_invoice_line_the_pet_deposit_partly_paid_is_reduced_within_its_unpaid_rest(
    migrated_database_url: str,
) -> None:
    """The Invoice-line form: at closure the Pet Deposit pays 1,000 of the Primary Tenant's 1,500
    key card line (and 8,000 of the Charge and 11,000 of the Rent line). After closure a reduction
    of 501 is refused (it would release paid value) and nothing is written; a reduction of the
    unpaid 500 is recorded and confirmed as one linked credit Adjustment, so the line owes nothing,
    and a further reduction keeps the Deposit refusal (owner answer (a) to Q-2026-10-11-80). The
    Deposit application stays as it was (1,000, not reversed), the closed Settlement row is
    unchanged and the ledger reconciles. Owner answer 3 of 2026-10-16: the Deposit application was
    active when the confirm wrote its Adjustment, so the 8a-1 refusal ran and let it through; its
    reference names the correction, whose draft names exactly this Invoice and line."""
    url = migrated_database_url
    case = closed_two_signer_case(
        url,
        charge_before=8_000,
        pet_steps=lambda case: (
            SettlementDepositStep(PET_REST, case["pet"], LINE, case["tenant_line"], 1_000),
            SettlementDepositStep(PET_REST, case["pet"], CHARGE, case["charge"], 8_000),
            SettlementDepositStep(PET_REST, case["pet"], LINE, case["rent_line"], 11_000),
        ),
    )
    line, tenant = case["tenant_line"], case["tenant"]
    invoice = invoice_of(url, line)
    on_line = APPLICATION + "application.invoice_line_id=%s"
    application = one(url, on_line, line)
    assert (application[0], application[2]) == (1_000, 0)
    assert outstanding(url, line) == 500
    before = settlement_row(url, case["settlement"])
    count = drafts(url)
    with pytest.raises(FinalSettlementConflictError) as above_rest:
        record_line_reduction(case, reduction(case["settlement"], invoice, line, 501))
    assert cause(above_rest) == ("55000", RELEASES_PAID)
    assert (drafts(url), adjustments(url, line)) == (count, 0)
    draft = record_line_reduction(case, reduction(case["settlement"], invoice, line, 500))
    result = corrections().confirm_charge_reduction(
        case["prop"], draft, actor=approving(case["person"], case["prop"])
    )
    adjustment = cast(dict[str, Any], result["invoice_adjustment"])
    correction = str(cast(dict[str, Any], result["settlement_correction"])["id"])
    assert (
        adjustment["adjustment_type"],
        adjustment["amount_usd_cents"],
        adjustment["invoice_line_id"],
        adjustment["source_reference"],
    ) == ("CREDIT", 500, str(line), f"settlement-correction:{correction}")
    assert (outstanding(url, line), adjustments(url, line), held(url, case["pet"])) == (0, 1, 0)
    assert one(url, on_line, line) == application
    # Owner answer (a) to Q-2026-10-11-80: with no unpaid rest left, the Deposit-paid line keeps
    # the Deposit refusal.
    count = drafts(url)
    with pytest.raises(FinalSettlementConflictError) as no_rest:
        record_line_reduction(case, reduction(case["settlement"], invoice, line, 1))
    assert cause(no_rest) == ("55000", DEPOSIT_PAID)
    assert (drafts(url), adjustments(url, line)) == (count, 1)
    occurred = one(
        url, "SELECT occurred_at FROM app.invoice_adjustments WHERE id=%s", adjustment["id"]
    )
    assert application[1] < occurred[0]
    assert one(url, EFFECTS, correction) == ([UUID(str(adjustment["id"]))], [None])
    assert one(url, DRAFT_OF, correction) == (
        "CHARGE_REDUCTION",
        None,
        {"invoice_id": str(invoice), "invoice_line_id": str(line), "amount_usd_cents": 500},
    )
    assert settlement_row(url, case["settlement"]) == before
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, tenant)


def test_another_line_of_an_invoice_the_pet_deposit_partly_paid_is_reduced_within_its_rest(
    migrated_database_url: str,
) -> None:
    """The implementer's reading of sub-slice 10c-3c-2 (review round 1): the old Invoice-line
    refusal covered the whole Invoice, so its removal also lets a line that no Deposit application
    pays take a reduction of its unpaid rest when another line of its Invoice is Deposit-paid. At
    closure the remaining Pet Deposit, by the Customer's choice, pays the first Service line of one
    Initial Invoice and part of its Rent line; the second Service line takes no Deposit money. After
    closure a reduction above that line's unpaid rest is refused and nothing is written; the whole
    unpaid rest is recorded and confirmed as one linked credit Adjustment of that line only, so it
    owes nothing. Both Deposit applications on the other lines stay as they were, the Rent line
    still owes its rest, no Deposit holds money, the closed Settlement row is unchanged and the
    ledger reconciles. The 8a-1 refusal covers the whole Invoice, so it ran and let the Adjustment
    through only because its reference names the correction, whose draft names exactly this line.
    The Lease and its services use the shared Property's existing terms with fixed dates (as
    mixed_rent_case and test_a_deposit_application_on_another_line_of_the_invoice_stays)."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        human, prop, unit, tenant, _ = setup_sources(connection)
        lease = create_draft(
            connection,
            actor_id=human,
            unit_id=unit,
            primary_tenant_id=tenant,
            start_date=date(2026, 7, 27),
            end_date=date(2027, 6, 30),
        )
        sign_lease(connection, lease, human)
        for code, name, first_rate, second_rate in (
            ("TRASH_COLLECTION", "Trash Collection", 1_000, 1_200),
            ("INTERNET", "Internet", 2_500, 2_700),
        ):
            add_service(
                connection,
                actor_id=human,
                property_id=prop,
                lease_id=lease,
                code=code,
                display_name=name,
                first_rate=first_rate,
                second_rate=second_rate,
            )
    issued = PostgresRentBillingService(financial_database_url(), prop, human).generate(
        initial_command(lease, uuid4()), actor=authenticated(human, prop)
    )
    invoice = issued.invoice_id
    pet = pet_deposit(url, human, prop, lease, today(url))
    terminate(url, human, prop, lease, today(url), voluntary=False)
    bill_unbilled_rent_months(url, human, prop, lease)
    case: dict[str, Any] = {
        "url": url,
        "human": human,
        "prop": prop,
        "lease": lease,
        "customer": tenant,
        "pet": pet,
        "settlement": start(prop, human, lease),
        "cash": UUID(str(one(url, "SELECT id FROM app.refund_methods WHERE code='CASH'")[0])),
    }
    with psycopg.connect(url) as connection:
        lines = [
            (UUID(str(row[0])), str(row[1]), int(row[2]))
            for row in connection.execute(
                "SELECT id,category,app.invoice_line_outstanding(id) FROM app.invoice_lines "
                "WHERE invoice_id=%s ORDER BY line_sequence,id",
                (invoice,),
            ).fetchall()
        ]
    [(rent, rent_owed)] = [(line, owed) for line, category, owed in lines if category == "RENT"]
    [(service, service_owed), (other, other_owed)] = [
        (line, owed) for line, category, owed in lines if category != "RENT"
    ]
    rent_paid = held(url, pet) - service_owed
    assert service_owed > 0 and other_owed > 0 and 0 < rent_paid < rent_owed
    confirm_settlement(
        case,
        record_settlement(
            case,
            (
                SettlementDepositStep(PET_REST, pet, LINE, service, service_owed),
                SettlementDepositStep(PET_REST, pet, LINE, rent, rent_paid),
            ),
            pet_remainder=CHOICE,
        ),
    )
    case["person"] = approver(url)
    on_line = APPLICATION + "application.invoice_line_id=%s"
    applications = [one(url, on_line, line) for line in (service, rent)]
    assert [(found[0], found[2]) for found in applications] == [(service_owed, 0), (rent_paid, 0)]
    no_application = "SELECT count(*) FROM app.deposit_applications WHERE invoice_line_id=%s"
    assert one(url, no_application, other) == (0,)
    assert (held(url, pet), outstanding(url, other), outstanding(url, rent)) == (
        0,
        other_owed,
        rent_owed - rent_paid,
    )
    before = settlement_row(url, case["settlement"])
    count = drafts(url)
    with pytest.raises(FinalSettlementConflictError) as above_rest:
        record_line_reduction(case, reduction(case["settlement"], invoice, other, other_owed + 1))
    assert cause(above_rest) == ("55000", RELEASES_PAID)
    assert (drafts(url), adjustments(url, other)) == (count, 0)
    draft = record_line_reduction(case, reduction(case["settlement"], invoice, other, other_owed))
    result = corrections().confirm_charge_reduction(
        prop, draft, actor=approving(case["person"], prop)
    )
    adjustment = cast(dict[str, Any], result["invoice_adjustment"])
    correction = str(cast(dict[str, Any], result["settlement_correction"])["id"])
    assert (
        adjustment["adjustment_type"],
        adjustment["amount_usd_cents"],
        adjustment["invoice_line_id"],
        adjustment["source_reference"],
    ) == ("CREDIT", other_owed, str(other), f"settlement-correction:{correction}")
    assert (outstanding(url, other), outstanding(url, rent), held(url, pet)) == (
        0,
        rent_owed - rent_paid,
        0,
    )
    assert (adjustments(url, service), adjustments(url, rent)) == (0, 0)
    assert [one(url, on_line, line) for line in (service, rent)] == applications
    occurred = one(
        url, "SELECT occurred_at FROM app.invoice_adjustments WHERE id=%s", adjustment["id"]
    )
    assert max(found[1] for found in applications) < occurred[0]
    assert one(url, EFFECTS, correction) == ([UUID(str(adjustment["id"]))], [None])
    assert one(url, DRAFT_OF, correction) == (
        "CHARGE_REDUCTION",
        None,
        {"invoice_id": str(invoice), "invoice_line_id": str(other), "amount_usd_cents": other_owed},
    )
    assert settlement_row(url, case["settlement"]) == before
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, tenant)


def test_deposit_paid_charge_reduction_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Migration 144 changes only the two charge reduction plan functions: each new body is exactly
    the old one with the module's replacement (its anchor found once), so the old unconditional
    Deposit refusal is gone; privileges, owner, definer and settings are kept; no function,
    constraint or trigger is added or removed; it is forward-only."""
    url = migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261217_143"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    patched = dict(revision.module.PATCHES)
    with psycopg.connect(url) as connection:
        for name in patched:
            found = connection.execute(
                "SELECT prosrc FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure", (name,)
            ).fetchone()
            assert found is not None
            for anchor, _, _ in patched[name]:
                assert anchor not in str(found[0]), name
    with _temporary_migration_database("settlement_deposit_paid_charge_reduction") as temporary:
        alembic_command.upgrade(config, "20261217_143")
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
