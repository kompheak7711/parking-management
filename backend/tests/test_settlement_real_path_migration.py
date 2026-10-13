"""Real-path tests before sub-slice 10h (V1-056 plan, "Before 10h" tasks).

Owner answer 2 to Q-2026-10-09-67: the Q-2026-10-09-65 case, settled through real return-only
`REFUND_RETURN` corrections and real `HELD_VALUE_REFUND` corrections in both orders, each ending in
the DL-032 order (the pet damage paid by the Pet Deposit, the other debt by the Security Deposit,
every Refund after the debt; BR-SETTLE-008). Owner answer 1 to Q-2026-10-10-71: on a really closed
two-Signer Lease whose Security Deposit was kept, a `FORFEITURE_REVERSAL` refunds the Deposit to the
second Signer with the written agreement of all Signers (BR-REFUND-015).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest

from lease_deposit_forfeiture_test_support import forfeit_through_draft
from property_rental.billing import PostgresRentBillingService, month_end
from property_rental.deposit import PostgresDepositService
from property_rental.final_settlement import (
    FinalSettlementConflictError,
    FinalSettlementInvalidError,
    SettlementCreditStep,
    SettlementDepositStep,
)
from property_rental.lease import (
    LEASE_DRAFT_CAPABILITY,
    LEASE_SIGN_CAPABILITY,
    LEASE_SIGNER_MANAGE_CAPABILITY,
    LeaseAddSignerCommand,
    LeaseSignCommand,
    PostgresLeaseService,
)
from property_rental.move_out_inspection import InspectionFinding, RecordMoveOutInspection
from property_rental.settlement_correction import ExtraChargeCategory
from test_billing_service_migration import authenticated, initial_command
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import invoice_of, this_month
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
from test_final_settlement_migration import held, one, outstanding, start, today
from test_final_settlement_preview_migration import path_of, pay, preview
from test_invoice_migration import financial_database_url, runtime_database_url
from test_lease_lifecycle_migration import actor, database_now, draft_command, signature_command
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_out_inspection_migration import actor as inspection_actor
from test_move_out_inspection_migration import flow as inspection_flow
from test_reservation_migration import (
    create_reservation,
    reservation_business_date,
    setup_reservation_sources,
)
from test_settlement_correction_migration import approver
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_extra_charge_migration import approving, cause, corrections, extra_charge
from test_settlement_extra_charge_migration import record as record_extra_charge
from test_settlement_forfeiture_reversal_migration import (
    NOTE,
    confirm_reversal,
    disposition_of,
    record_reversal,
    reversal_command,
)
from test_settlement_held_deposit_limit_migration import OPEN_DEBT, SECURITY_FIRST
from test_settlement_held_value_refund_migration import (
    confirm_held,
    deposit_left,
    held_command,
    record_held,
    return_only,
)
from test_termination_deposit_migration import terminate
from test_unpaid_initial_termination_migration import PHNOM_PENH

AGREEMENT = "All Signers agreed in writing on 2026-10-11 that the second Signer receives the Refund"


def security_refund(case: dict[str, Any]) -> UUID:
    """The Final Settlement's own Deposit Refund of the Security Deposit (sub-slice 8d)."""
    return UUID(
        str(
            one(
                case["url"],
                "SELECT refund_id FROM app.final_settlement_refund_details "
                "WHERE final_settlement_id=%s AND deposit_id=%s",
                case["settlement"],
                case["security"],
            )[0]
        )
    )


def extra_charge_line(case: dict[str, Any], **changes: Any) -> UUID:
    """A confirmed EXTRA_CHARGE correction (sub-slice 10b); its one Invoice line."""
    draft = record_extra_charge(case, extra_charge(case["settlement"], **changes))
    result = corrections().confirm_extra_charge(
        case["prop"], draft, actor=approving(case["person"], case["prop"])
    )
    invoice = UUID(str(cast(dict[str, Any], result["invoice"])["id"]))
    return UUID(
        str(one(case["url"], "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", invoice)[0])
    )


def q65_case(url: str) -> dict[str, Any]:
    """The Q-2026-10-09-65 state on the real path. Before closure the Customer pays 2,300 of the
    other damage line. The Settlement closes: Credit 400 and the Security Deposit 9,800 pay the
    other damage line, the Pet Deposit pays the pet damage line (12,500), and the Security
    Deposit's rest (200) and the Pet Deposit's rest (7,500) are refunded. After closure a
    return-only correction E2 brings back the Security Deposit Refund's 200 and another, E1, 300 of
    the Pet Deposit Refund; a later inspection's pet finding is billed as a 50 Damage charge and a
    100 Miscellaneous charge opens other debt (both `EXTRA_CHARGE`). The Customer has no Credit."""
    case = {**leaving_case(url, start_offset=this_month(url)), "url": url}
    prop, human, customer, lease = case["prop"], case["human"], case["customer"], case["lease"]
    pay(url, prop, human, customer, invoice_of(url, case["other_line"]), case["other_line"], 2_300)
    confirm_settlement(
        case,
        record_settlement(
            case,
            (
                SettlementCreditStep(case["credit"], LINE, case["other_line"], 400),
                SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], 12_500),
                SettlementDepositStep(SECURITY, case["security"], LINE, case["other_line"], 9_800),
                settlement_refund(case, "security", 200),
                settlement_refund(case, "pet", 7_500),
            ),
        ),
    )
    case["person"] = approver(url)
    case["e2"] = return_only(case, security_refund(case), 200)
    case["e1"] = return_only(case, pet_refund(case), 300)
    finding = uuid4()
    inspection_flow().record(
        prop,
        lease,
        RecordMoveOutInspection(
            uuid4(),
            uuid4(),
            int(str(one(url, "SELECT version FROM app.leases WHERE id=%s", lease)[0])),
            today(url),
            "Later inspection condition",
            "Approved inspection",
            "Evidence-911",
            "Pet damage found after the Final Settlement",
            (InspectionFinding(finding, "Chewed door frame", True),),
        ),
        actor=inspection_actor(human, prop),
        request_id=f"q65-real-path-{finding}",
    )
    case["damage_line"] = extra_charge_line(
        case,
        category=ExtraChargeCategory.DAMAGE_CHARGES,
        description="Chewed door frame",
        amount_usd_cents=50,
        inspection_damage_finding_id=finding,
    )
    case["debt_line"] = extra_charge_line(case, amount_usd_cents=100)
    assert (held(url, case["security"]), held(url, case["pet"])) == (200, 300)
    assert (outstanding(url, case["damage_line"]), outstanding(url, case["debt_line"])) == (50, 100)
    assert one(
        url,
        "SELECT count(*) FROM app.customer_credits credit WHERE credit.customer_id=%s "
        "AND app.credit_available_value(credit.id)>0",
        customer,
    ) == (0,)
    assert one(url, "SELECT app.invoice_line_is_pet_damage(%s,%s)", case["damage_line"], lease) == (
        True,
    )
    assert one(url, "SELECT app.invoice_line_is_pet_damage(%s,%s)", case["debt_line"], lease) == (
        False,
    )
    # What each return-only correction left in each Deposit (the Q-65 "at most" rule).
    assert (
        deposit_left(url, case["e1"], case["pet"]),
        deposit_left(url, case["e1"], case["security"]),
        deposit_left(url, case["e2"], case["security"]),
        deposit_left(url, case["e2"], case["pet"]),
    ) == (300, 0, 200, 0)
    return case


def held_refunds(url: str, deposit: UUID) -> list[int]:
    """The Deposit Refunds the held-value corrections paid from this Deposit, oldest first."""
    with psycopg.connect(url) as connection:
        found = connection.execute(
            "SELECT refund.usd_accounting_value_cents FROM app.refunds refund "
            "JOIN app.settlement_correction_refund_details detail ON detail.refund_id=refund.id "
            "WHERE refund.source_deposit_id=%s ORDER BY refund.processed_at,refund.id",
            (deposit,),
        ).fetchall()
    return [int(row[0]) for row in found]


def applied(url: str, deposit: UUID, line: UUID) -> int:
    """What the Deposit's applications that are not reversed paid on the line."""
    return int(
        one(
            url,
            "SELECT COALESCE(sum(application.amount_usd_cents),0) FROM app.deposit_applications "
            "application WHERE application.deposit_id=%s AND application.invoice_line_id=%s "
            "AND NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal "
            "WHERE reversal.deposit_application_id=application.id)",
            deposit,
            line,
        )[0]
    )


def ends_in_dl032_order(case: dict[str, Any]) -> None:
    """The end state of either order: the pet damage paid by the Pet Deposit, the other debt by the
    Security Deposit, 250 and 100 refunded, both Deposits empty and nothing left of either return
    (that each Refund came after the debt is shown by the refusals and balances of the test)."""
    url, pet, security = case["url"], case["pet"], case["security"]
    assert (deposit_left(url, case["e1"], pet), deposit_left(url, case["e2"], security)) == (0, 0)
    assert (outstanding(url, case["damage_line"]), outstanding(url, case["debt_line"])) == (0, 0)
    assert (applied(url, pet, case["damage_line"]), applied(url, security, case["debt_line"])) == (
        50,
        100,
    )
    assert (applied(url, security, case["damage_line"]), applied(url, pet, case["debt_line"])) == (
        0,
        0,
    )
    assert (held_refunds(url, pet), held_refunds(url, security)) == ([250], [100])
    assert (held(url, pet), held(url, security)) == (0, 0)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_the_q65_case_is_settled_security_first_on_the_real_path(
    migrated_database_url: str,
) -> None:
    """Owner answer 2 to Q-2026-10-09-67, Security Deposit correction first: E2's held-value
    correction refunding its 100 while the pet damage stays open is refused; E2's correction pays
    the other debt (100) and keeps 100 held; E1's correction pays the pet damage (50) and refunds
    250; E2's next correction refunds its 100. The end is in the DL-032 order."""
    url = migrated_database_url
    case = q65_case(url)
    other_debt = SettlementDepositStep(SECURITY, case["security"], LINE, case["debt_line"], 100)
    pet_damage = SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["damage_line"], 50)
    with pytest.raises(FinalSettlementConflictError) as early:
        record_held(
            case,
            held_command(case, case["e2"], other_debt, settlement_refund(case, "security", 100)),
        )
    assert cause(early) == ("55000", OPEN_DEBT)
    confirm_held(case, record_held(case, held_command(case, case["e2"], other_debt)))
    assert (held(url, case["security"]), outstanding(url, case["debt_line"])) == (100, 0)
    confirm_held(
        case,
        record_held(
            case, held_command(case, case["e1"], pet_damage, settlement_refund(case, "pet", 250))
        ),
    )
    assert (held(url, case["pet"]), outstanding(url, case["damage_line"])) == (0, 0)
    confirm_held(
        case,
        record_held(case, held_command(case, case["e2"], settlement_refund(case, "security", 100))),
    )
    ends_in_dl032_order(case)


def test_the_q65_case_is_settled_pet_first_on_the_real_path(
    migrated_database_url: str,
) -> None:
    """Owner answer 2 to Q-2026-10-09-67, Pet Deposit correction first: E1's correction refunding
    250 while the other debt stays open, or paying that debt with the rest of the Pet Deposit
    before the Security Deposit, is refused; E1's correction pays the pet damage and keeps 250
    held; E2's correction pays the other debt and refunds 100; E1's next correction refunds its
    250. The end is in the DL-032 order."""
    url = migrated_database_url
    case = q65_case(url)
    other_debt = SettlementDepositStep(SECURITY, case["security"], LINE, case["debt_line"], 100)
    pet_damage = SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["damage_line"], 50)
    pet_rest = SettlementDepositStep(PET_REST, case["pet"], LINE, case["debt_line"], 100)
    with pytest.raises(FinalSettlementConflictError) as early:
        record_held(
            case, held_command(case, case["e1"], pet_damage, settlement_refund(case, "pet", 250))
        )
    assert cause(early) == ("55000", OPEN_DEBT)
    with pytest.raises(FinalSettlementConflictError) as before_security:
        record_held(case, held_command(case, case["e1"], pet_damage, pet_rest, pet_remainder=STAFF))
    assert cause(before_security) == ("55000", SECURITY_FIRST)
    confirm_held(case, record_held(case, held_command(case, case["e1"], pet_damage)))
    assert (held(url, case["pet"]), outstanding(url, case["damage_line"])) == (250, 0)
    confirm_held(
        case,
        record_held(
            case,
            held_command(case, case["e2"], other_debt, settlement_refund(case, "security", 100)),
        ),
    )
    assert (held(url, case["security"]), outstanding(url, case["debt_line"])) == (0, 0)
    confirm_held(
        case,
        record_held(case, held_command(case, case["e1"], settlement_refund(case, "pet", 250))),
    )
    ends_in_dl032_order(case)


def two_signer_kept_case(url: str) -> dict[str, Any]:
    """A real two-Signer Lease: reserved by the Primary Tenant (Security Deposit 10,000 received
    through the Reservation), a second Signer added and signed before the Lease is signed, the
    Initial Rent Invoice issued and paid. Voluntary early leaving (BR-LEASE-021) gives the
    Security Deposit its forfeiture ground; it is forfeited through the draft and kept
    (BR-DEP-023), and the Final Settlement is really closed with nothing owed."""
    with psycopg.connect(url) as connection:
        human, prop, unit, customer = setup_reservation_sources(connection)
        co_signer = setup_reservation_sources(connection)[3]
        _, ids = create_reservation(
            connection,
            actor_id=human,
            property_id=prop,
            unit_id=unit,
            customer_id=customer,
            expiration_days=10,
        )
        day = reservation_business_date(connection, prop)
    first = day - timedelta(days=this_month(url))
    leases = PostgresLeaseService(runtime_database_url(), prop, human)
    who = actor(
        human, prop, LEASE_DRAFT_CAPABILITY, LEASE_SIGN_CAPABILITY, LEASE_SIGNER_MANAGE_CAPABILITY
    )
    draft = draft_command(
        unit, customer, start_date=first, end_date=month_end(first + timedelta(days=365))
    )
    leases.draft(draft, actor=who)
    leases.record_signature(
        signature_command(draft.lease_id, draft.primary_signer_id, 1), actor=who
    )
    co_signer_id = uuid4()
    leases.add_signer(
        LeaseAddSignerCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=draft.lease_id,
            signer_id=co_signer_id,
            customer_id=co_signer,
            expected_version=2,
            reason="Add jointly responsible Lease Signer",
            authorization_reference=LEASE_SIGNER_MANAGE_CAPABILITY,
        ),
        actor=who,
    )
    leases.record_signature(signature_command(draft.lease_id, co_signer_id, 3), actor=who)
    signed = leases.sign(
        LeaseSignCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=draft.lease_id,
            expected_version=4,
            signed_at=database_now(),
            reason="Every Lease Signer completed signing",
            authorization_reference=LEASE_SIGN_CAPABILITY,
            reservation_id=ids["reservation_id"],
        ),
        actor=who,
    )
    assert (signed.signer_count, signed.signed_signer_count) == (2, 2)
    issued = PostgresRentBillingService(financial_database_url(), prop, human).generate(
        initial_command(
            draft.lease_id,
            uuid4(),
            period_start=first,
            issued_at=datetime(first.year, first.month, first.day, tzinfo=PHNOM_PENH),
        ),
        actor=authenticated(human, prop),
    )
    rent, owed = cast(
        tuple[Any, Any],
        one(
            url,
            "SELECT id,app.invoice_line_outstanding(id) FROM app.invoice_lines "
            "WHERE invoice_id=%s AND category='RENT'",
            issued.invoice_id,
        ),
    )
    pay(url, prop, human, customer, issued.invoice_id, UUID(str(rent)), int(owed))
    assert outstanding(url, UUID(str(rent))) == 0
    terminate(url, human, prop, draft.lease_id, day, voluntary=True)
    security = ids["deposit_id"]
    forfeit_through_draft(PostgresDepositService(financial_database_url(), prop, human), security)
    case: dict[str, Any] = {
        "url": url,
        "human": human,
        "prop": prop,
        "lease": draft.lease_id,
        "customer": customer,
        "co_signer": co_signer,
        "security": security,
        "settlement": start(prop, human, draft.lease_id),
        "cash": UUID(str(one(url, "SELECT id FROM app.refund_methods WHERE code='CASH'")[0])),
    }
    case["disposition"] = disposition_of(url, security)
    confirm_settlement(case, record_settlement(case, ()))
    case["person"] = approver(url)
    assert held(url, security) == 0
    return case


def test_a_kept_deposit_is_refunded_to_the_agreed_second_signer_on_the_real_path(
    migrated_database_url: str,
) -> None:
    """Owner answer 1 to Q-2026-10-10-71 (BR-REFUND-015): on the really closed two-Signer Lease the
    approver confirms a `FORFEITURE_REVERSAL` whose Deposit Refund pays the whole 10,000 to the
    second Signer with the written agreement of all Signers. The Refund is the Deposit owner's,
    paid to the Signer: its recipient, method, note and agreement are recorded; the Customer
    Ledger books it once, on the Primary Tenant with the Signer as paid-to; the Deposit is empty
    and back on the DL-032 path; both ledgers reconcile. Without the written agreement the same
    Refund to the Signer is refused (22023) and nothing is recorded."""
    url = migrated_database_url
    case = two_signer_kept_case(url)
    prop, human, security = case["prop"], case["human"], case["security"]
    assert path_of(preview(prop, human, case["settlement"]), security) == (
        "BR-DEP-023",
        "ACTIVE",
        "KEPT",
        0,
    )
    drafts = one(url, "SELECT count(*) FROM app.financial_drafts")
    with pytest.raises(FinalSettlementInvalidError) as no_agreement:
        record_reversal(
            case,
            reversal_command(
                case,
                settlement_refund(
                    case, "security", 10_000, recipient_customer_id=case["co_signer"]
                ),
            ),
        )
    assert cause(no_agreement) == (
        "22023",
        "A Refund to another Signer needs the written agreement of all Signers",
    )
    assert one(url, "SELECT count(*) FROM app.financial_drafts") == drafts
    result = confirm_reversal(
        case,
        record_reversal(
            case,
            reversal_command(
                case,
                settlement_refund(
                    case,
                    "security",
                    10_000,
                    recipient_customer_id=case["co_signer"],
                    signer_agreement=AGREEMENT,
                ),
            ),
        ),
    )
    [paid] = result["refunds"]
    assert (
        paid["source_deposit_id"],
        paid["recipient_customer_id"],
        paid["amount_usd_cents"],
        paid["refund_method_id"],
        paid["reference_note"],
        paid["signer_agreement"],
    ) == (str(security), str(case["co_signer"]), 10_000, str(case["cash"]), NOTE, AGREEMENT)
    with psycopg.connect(url) as connection:
        booked = connection.execute(
            "SELECT customer_id,source_audit->>'paid_to_customer_id' "
            "FROM app.customer_ledger_effects WHERE refund_id=%s AND event_kind='REFUND_PAID'",
            (UUID(str(paid["id"])),),
        ).fetchall()
    assert booked == [(case["customer"], str(case["co_signer"]))]
    assert one(
        url,
        "SELECT count(*) FROM app.customer_ledger_effects WHERE customer_id=%s",
        case["co_signer"],
    ) == (0,)
    assert held(url, security) == 0
    assert path_of(preview(prop, human, case["settlement"]), security) == (
        "BR-DEP-023",
        "REVERSED",
        "DL_032",
        0,
    )
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])
        assert_reconciled(connection, case["co_signer"])
