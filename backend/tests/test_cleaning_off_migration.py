"""Parking Step 5 (owner 2026-10-30): no move-out cleaning charge on Parking (migration 257).

Property Rental's settlement preview (migration 89) blocks a move-out until a cleaning charge is
issued or the Parking's rate is 0, and Settings cannot store a 0 rate for a Parking Type. Parking
charges no cleaning at move-out, so migration 257 turns that one check off. Everything else
stays: the tables, the rate settings, `app.record_unit_cleaning_charge`, and a cleaning charge
that already exists counts as a normal debt. This file also holds the owner's second Step 5
check: a full Final Settlement with no Pet Deposit is exact to the cent.
"""

from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from alembic.config import Config
from alembic.script import ScriptDirectory

from lease_deposit_forfeiture_test_support import forfeit_through_draft
from property_rental.deposit import PostgresDepositService
from property_rental.identity import AuthenticatedActor
from property_rental.final_settlement import (
    RecordFinalSettlementDraftCommand,
    SettlementDepositRefund,
    SettlementDepositStep,
    SettlementDepositStepKind,
    SettlementTargetKind,
)
from property_rental.invoice import (
    RecordOneTimeChargeCommand,
    RecordUnitCleaningChargeCommand,
    SetUnitCleaningRateCommand,
)
from test_final_settlement_draft_migration import APPROVE, PREPARE, settlements
from test_final_settlement_migration import held, line_of, one, outstanding, start
from test_final_settlement_preview_migration import (
    codes,
    invoices,
    issues,
    pay,
    person,
    preview,
)
from test_final_utility_invoice_migration import (
    create_final,
    departed,
    final_reading,
    record_final,
)
from test_invoice_migration import financial_database_url, setup_signed_lease
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_out_final_inputs_migration import missing, used
from test_one_time_charges_migration import draft_and_issue
from test_termination_deposit_migration import terminate
from test_unpaid_initial_termination_migration import rent_line, signed_with_initial

REVISION = "20270407_257"
PREVIEW = "app.final_settlement_preview(uuid,uuid,uuid,text[])"
CLEANING = "CLEANING_CHARGE_MISSING"


def staff_of(human: UUID, prop: UUID) -> AuthenticatedActor:
    return person(
        human, prop, "invoices.read", "invoices.create", "invoices.issue", "property.manage"
    )


def test_a_moved_out_lease_with_no_cleaning_rate_and_no_charge_is_ready_to_close(
    migrated_database_url: str,
) -> None:
    """Property Rental would list CLEANING_CHARGE_MISSING (NO_RATE) here; Parking does not."""
    url = migrated_database_url
    leaver = departed(url, 5, 4)
    dep = leaver.dep
    human, prop, lease, unit = dep.human, dep.prop, dep.lease, dep.unit
    settlement = start(prop, human, lease)
    view = preview(prop, human, settlement)
    assert view["lease"]["moved_in"] is True
    assert view["lease"]["move_out_date"] == dep.move_out_date.isoformat()
    assert one(url, "SELECT count(*) FROM app.unit_cleaning_rates WHERE unit_id=%s", unit)[0] == 0
    assert (
        one(url, "SELECT count(*) FROM app.unit_cleaning_charges WHERE lease_id=%s", lease)[0] == 0
    )
    assert CLEANING not in codes(view)
    # The final Utility steps still hold the Settlement, as in Property Rental.
    pending = record_final(leaver, (missing(dep.electricity),))
    reading = final_reading(url, leaver, dep.electricity, "150")
    resolved = record_final(leaver, (used(dep.electricity, reading),), supersedes=pending)
    create_final(leaver, resolved)
    view = preview(prop, human, settlement)
    assert issues(view, "FINAL_UTILITY_NOT_ISSUED") == []
    assert CLEANING not in codes(view)
    # Once every kept Deposit's forfeiture is confirmed, nothing blocks the Settlement: no
    # cleaning rate and no cleaning charge, and the move-out can close.
    service = PostgresDepositService(financial_database_url(), prop, human)
    for item in view["deposits"]:
        if item["path"] == "FORFEITURE_REQUIRED":
            forfeit_through_draft(service, UUID(item["deposit_id"]))
    view = preview(prop, human, settlement)
    assert view["blocking_issues"] == [] and view["ready"] is True


def test_a_cleaning_charge_that_exists_still_counts_as_a_normal_debt(
    migrated_database_url: str,
) -> None:
    """The rate settings and `app.record_unit_cleaning_charge` stay; an issued cleaning charge
    is an ordinary open Invoice line of the Settlement, and no preview issue is about it."""
    url = migrated_database_url
    leaver = departed(url, 6, 4)
    dep = leaver.dep
    human, prop, lease, unit = dep.human, dep.prop, dep.lease, dep.unit
    settlement = start(prop, human, lease)
    staff = staff_of(human, prop)
    rate = invoices().set_unit_cleaning_rate(
        prop, SetUnitCleaningRateCommand(uuid4(), unit, None, 2_500, "Configured rate"), actor=staff
    )
    # In Property Rental a rate above zero with no issued charge blocks (NOT_ISSUED).
    assert CLEANING not in codes(preview(prop, human, settlement))
    charge = RecordUnitCleaningChargeCommand(uuid4(), lease, UUID(str(rate["id"])))
    invoices().record_unit_cleaning_charge(prop, charge, actor=staff)
    view = preview(prop, human, settlement)
    assert [
        item["authorized_obligation_id"] for item in issues(view, "ONE_TIME_CHARGE_NOT_INVOICED")
    ] == [str(charge.charge_id)]
    assert CLEANING not in codes(view)
    issued = draft_and_issue(prop, charge.charge_id, staff)
    line = line_of(url, issued["id"])
    assert outstanding(url, line) == 2_500
    view = preview(prop, human, settlement)
    assert CLEANING not in codes(view)
    assert issues(view, "ONE_TIME_CHARGE_NOT_INVOICED") == []
    [person_view] = view["customers"]
    lines = {
        UUID(item["invoice_line_id"]): item["outstanding_usd_cents"]
        for item in person_view["invoice_lines"]
    }
    assert lines[line] == 2_500
    assert view["open_total_usd_cents"] >= 2_500


def test_a_full_settlement_with_no_pet_deposit_is_exact_to_the_cent(
    migrated_database_url: str,
) -> None:
    """Owner's Step 5 check: a Lease with a Security Deposit and no Pet Deposit settles a debt
    with odd cents and refunds the rest; every amount matches to the cent and the Settlement
    closes."""
    url = migrated_database_url
    source = signed_with_initial(url, 10)
    human, prop, lease = source["actor"], source["property"], source["lease"]
    customer, day, security = source["customer"], source["today"], source["deposit"]
    assert (
        one(
            url,
            "SELECT count(*) FROM app.deposits WHERE lease_id=%s AND deposit_type='PET'",
            lease,
        )[0]
        == 0
    )
    staff = staff_of(human, prop)
    command = RecordOneTimeChargeCommand(
        uuid4(),
        "MISCELLANEOUS_CHARGES",
        customer,
        lease,
        None,
        "Replacement remote control",
        7_525,
        "Remote control not returned",
        "Front desk log 903",
    )
    invoices().record_one_time_charge(prop, command, actor=staff)
    issued = draft_and_issue(prop, command.charge_id, staff)
    line = line_of(url, issued["id"])
    rent, owed = rent_line(url, source["invoice"])
    pay(url, prop, human, customer, source["invoice"], rent, owed)
    terminate(url, human, prop, lease, day, voluntary=False)
    settlement = start(prop, human, lease)
    view = preview(prop, human, settlement)
    assert view["blocking_issues"] == [] and view["ready"] is True
    assert held(url, security) == 10_000 and outstanding(url, line) == 7_525
    assert view["open_total_usd_cents"] == 7_525
    cash = UUID(str(one(url, "SELECT id FROM app.refund_methods WHERE code='CASH'")[0]))
    draft = settlements().record_draft(
        prop,
        RecordFinalSettlementDraftCommand(
            uuid4(),
            settlement,
            (
                SettlementDepositStep(
                    SettlementDepositStepKind.SECURITY_DEPOSIT,
                    security,
                    SettlementTargetKind.INVOICE_LINE,
                    line,
                    7_525,
                ),
                SettlementDepositRefund(
                    deposit_id=security,
                    amount_usd_cents=2_475,
                    refund_method_id=cash,
                    reference_note="Cash handed over at the front desk",
                    recipient_customer_id=customer,
                    signer_agreement=None,
                ),
            ),
            "Final Settlement prepared from the move-out review",
            None,
        ),
        actor=person(human, prop, PREPARE),
    )
    with psycopg.connect(url) as connection:
        approver_id = setup_signed_lease(connection)[0]
    settlements().confirm(
        prop, UUID(str(draft["draft_id"])), actor=person(approver_id, prop, APPROVE)
    )
    assert outstanding(url, line) == 0
    assert held(url, security) == 0
    assert (
        one(
            url,
            "SELECT coalesce(sum(amount_usd_cents),0) FROM app.deposit_applications"
            " WHERE final_settlement_id=%s",
            settlement,
        )[0]
        == 7_525
    )
    assert (
        one(
            url,
            "SELECT coalesce(sum(amount_usd_cents),0) FROM app.deposit_applications"
            " WHERE deposit_id=%s",
            security,
        )[0]
        == 7_525
    )
    view = preview(prop, human, settlement)
    assert view["settlement"]["closed"] is True
    assert view["open_total_usd_cents"] == 0


def test_the_cleaning_off_migration_is_the_head_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == REVISION
    revision = script.get_revision(REVISION)
    assert revision.down_revision == "20270406_256"
    source = (
        Path(__file__).parents[1] / "migrations" / "versions" / f"{REVISION}_cleaning_charge_off.py"
    ).read_text(encoding="utf-8")
    assert "forward-only" in source and "IF false AND v_moved_in" in source


def test_the_preview_source_has_the_cleaning_check_switched_off(
    migrated_database_url: str,
) -> None:
    source = str(
        one(
            migrated_database_url,
            "SELECT pg_catalog.pg_get_functiondef(CAST(%s AS regprocedure))",
            PREVIEW,
        )[0]
    )
    assert source.count("IF false AND v_moved_in AND v_move_out.id IS NOT NULL") == 1
    # The rest of the function is Property Rental's: the issue code is still in the source.
    assert CLEANING in source
