"""Post-settlement correction: DEPOSIT_RECEIPT_CORRECTION (V1-056 sub-slice 10e-2).

Owner answer (a) to Q-2026-10-08-56, answers 1 and 3 to Q-2026-10-11-83 and answer (a) to
Q-2026-10-11-86: a Lease Deposit receipt that is wrong while its Payment is real is fixed after
closure only by a correction of the closed Final Settlement, prepared under
final_settlements.prepare and confirmed only by financial.approve (BR-SETTLE-013, BR-AUTH-010). In
one transaction, each record linked to the correction, the confirm recovers each Refund paid from
the Deposit by a charge to the person who received it (the Q-2026-10-11-78 rule), reverses the
Deposit's applications (the debt comes back on its obligations and stays with their Customers,
BR-SETTLE-016) and reverses the whole receipt. The freed amount stays unallocated with the Payment
(BR-CREDIT-002 not amended); a kept Deposit is refused until a FORFEITURE_REVERSAL runs.
"""

from __future__ import annotations

import json
from dataclasses import replace
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
    SettlementDepositStep,
)
from property_rental.settlement_correction import RecordDepositReceiptCorrectionCommand
from test_final_settlement_confirm_migration import invoice_of
from test_final_settlement_draft_migration import LINE, SECURITY, leaving_case
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding, preparer
from test_invoice_migration import financial_database_url, register_billing_service_principal
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated
from test_payment_allocation_migration import service as allocations
from test_payment_move_migration import rows, value
from test_payment_return_recovery_migration import CLOSED as CLOSED_ELSEWHERE
from test_payment_return_recovery_migration import (
    RESERVATION,
    SHARED,
    charge,
    due_days,
    planned,
    recovery_row,
    written,
)
from test_settlement_correction_migration import approver, settlement_row
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_extra_charge_migration import approving, cause, corrections, state
from test_settlement_forfeiture_reversal_migration import (
    confirm_reversal,
    kept_case,
    record_reversal,
    reversal_command,
)
from test_settlement_real_path_migration import AGREEMENT, two_signer_kept_case
from test_settlement_refund_return_migration import confirm as confirm_return
from test_settlement_refund_return_migration import net, return_command
from test_settlement_refund_return_migration import record as record_return
from test_settlement_returned_payment_migration import (
    closed_case,
    receipt_payment,
    reconciled,
    status,
)

RECORD = (
    "app.record_settlement_deposit_receipt_correction_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
)
CONFIRM = "app.confirm_settlement_deposit_receipt_correction(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.write_correction_deposit_application_reversals(uuid,uuid,text,uuid[],"
    "timestamp with time zone)",
    "app.settlement_deposit_receipt_correction_input(jsonb)",
    "app.settlement_deposit_receipt_correction_source(uuid,uuid,uuid,uuid)",
    "app.assert_settlement_deposit_receipt_correction_allowed(uuid,uuid,jsonb)",
    "app.settlement_deposit_receipt_correction_result(uuid)",
    "app.post_settlement_deposit_receipt_correction(uuid,uuid,uuid,uuid,uuid,text)",
)
PATCHED = {
    "app.post_settlement_returned_payment(uuid,uuid,uuid,uuid,uuid,text)",
    "app.refund_recovery_allowed(app.refund_corrections)",
    "app.write_payment_return_recoveries(uuid,uuid,uuid,uuid,uuid,jsonb,text,text,"
    "timestamp with time zone,jsonb)",
    "app.lock_settlement_correction_plan(uuid)",
}
REASON = "The receipt was meant for Rent, not for the Deposit"
EVIDENCE = "Bank statement line 5120 and the Customer's written instruction"
LINKS = (
    "authorized_nonrecurring_obligation_id",
    "invoice_id",
    "refund_correction_id",
    "deposit_application_reversal_id",
    "deposit_receipt_reversal_id",
)
RECOVERY_LINKS = ["authorized_nonrecurring_obligation_id", "invoice_id", "refund_correction_id"]
KEPT = (
    "The Deposit has an active forfeiture; reverse it with a forfeiture reversal correction first"
)
NOT_FOUND = "Deposit receipt was not found"
ALREADY = "This Deposit receipt is already reversed"
NOT_OF_LEASE = "This Deposit receipt is not of a Deposit of this Final Settlement's Lease"
NOT_RECEIVED = "Only a received Payment's Deposit receipt can be corrected"
OTHER_SETTLEMENT = "The Deposit has a Deposit application of another Final Settlement"
NO_RECOVERY = "A Refund paid from this Deposit has no planned recovery"
STILL_HOLDS = "The Deposit would not end empty after this receipt correction"
WAITING = "A draft that names this Deposit receipt, its Deposit or its Payment is waiting"
DIRECT = (
    "A closed Final Settlement's Deposit receipt changes only through a post-settlement correction"
)


def receipt_of(url: str, deposit: UUID) -> UUID:
    return UUID(str(value(url, "SELECT id FROM app.deposit_receipts WHERE deposit_id=%s", deposit)))


def request(
    case: dict[str, Any], receipt: UUID, **changes: Any
) -> RecordDepositReceiptCorrectionCommand:
    return replace(
        RecordDepositReceiptCorrectionCommand(
            uuid4(), case["settlement"], receipt, REASON, EVIDENCE
        ),
        **changes,
    )


def record(case: dict[str, Any], command: RecordDepositReceiptCorrectionCommand) -> UUID:
    found = corrections().record_deposit_receipt_correction(
        case["prop"], command, actor=preparer(case["human"], case["prop"])
    )
    return UUID(str(found["draft_id"]))


def confirm(case: dict[str, Any], draft: UUID) -> dict[str, Any]:
    return corrections().confirm_deposit_receipt_correction(
        case["prop"], draft, actor=approving(case["person"], case["prop"])
    )


def payload(url: str, draft: UUID) -> dict[str, Any]:
    return cast(
        dict[str, Any], value(url, "SELECT payload FROM app.financial_drafts WHERE id=%s", draft)
    )


def available(url: str, payment: UUID) -> int:
    return int(value(url, "SELECT app.payment_available_value(%s)", payment))


def effect_links(url: str, correction: object) -> list[str]:
    """The name of each effect's one link, in order."""
    found = rows(
        url,
        f"SELECT {','.join(LINKS)} FROM app.settlement_correction_effects "
        "WHERE settlement_correction_id=%s ORDER BY effect_sequence",
        correction,
    )
    return [LINKS[[item is not None for item in row].index(True)] for row in found]


def counts(url: str) -> tuple[Any, ...]:
    return one(
        url,
        "SELECT (SELECT count(*) FROM app.financial_drafts),"
        "(SELECT count(*) FROM app.settlement_corrections),"
        "(SELECT count(*) FROM app.deposit_receipt_reversals),"
        "(SELECT count(*) FROM app.deposit_application_reversals),"
        "(SELECT count(*) FROM app.refund_corrections)",
    )


def source_of(url: str, case: dict[str, Any], receipt: UUID) -> dict[str, Any]:
    """The correction's source of a receipt now, read as the owner."""
    return cast(
        dict[str, Any],
        value(
            url,
            "SELECT app.settlement_deposit_receipt_correction_source(%s,%s,%s,NULL)",
            case["prop"],
            case["settlement"],
            receipt,
        ),
    )


def allowed_check(url: str, case: dict[str, Any], source: dict[str, Any]) -> tuple[Any, Any]:
    """The refusal of the correction's check on a (changed) source, read as the owner; (None,
    None) when it passes."""
    with psycopg.connect(url) as connection:
        try:
            connection.execute(
                "SELECT app.assert_settlement_deposit_receipt_correction_allowed(%s,%s,%s)",
                (case["settlement"], case["lease"], Jsonb(source)),
            )
        except psycopg.Error as refused:
            connection.rollback()
            return refused.sqlstate, refused.diag.message_primary
    return None, None


def receipt_after_applications(url: str, correction: object) -> bool:
    """The receipt reversal is dated after every Deposit application reversal the correction
    linked."""
    return bool(
        value(
            url,
            "SELECT (SELECT r.occurred_at FROM app.deposit_receipt_reversals r "
            "JOIN app.settlement_correction_effects e ON e.deposit_receipt_reversal_id=r.id "
            "WHERE e.settlement_correction_id=%s) > ALL(SELECT r.occurred_at "
            "FROM app.deposit_application_reversals r JOIN app.settlement_correction_effects e "
            "ON e.deposit_application_reversal_id=r.id WHERE e.settlement_correction_id=%s)",
            correction,
            correction,
        )
    )


def test_a_wrong_pet_deposit_receipt_is_reversed_and_its_refund_charged_back(
    migrated_database_url: str,
) -> None:
    """The owner's example on the real closure of the 8c normal-end Settlement: the Pet Deposit's
    20,000 receipt was wrong (the Payment was meant for something else). The Settlement had applied
    12,500 to the pet damage line and 2,100 to the other damage line and refunded 5,400. The
    correction recovers the 5,400 Refund by an EXTRA_CHARGE of 5,400 to the Deposit owner on the
    Lease (the person who received it), reverses both Deposit applications (the debt comes back on
    its lines) and the whole receipt (the Pet Deposit ends at 0). The Payment stays RECEIVED with
    20,000 more available and no Credit (BR-CREDIT-002). The Settlement row is unchanged and the
    ledger reconciles."""
    url = migrated_database_url
    case = closed_case(url)
    prop, pet, customer, lease = case["prop"], case["pet"], case["customer"], case["lease"]
    receipt = receipt_of(url, pet)
    payment = receipt_payment(url, pet)
    refund = pet_refund(case)
    before_row = settlement_row(url, case["settlement"])
    before_available = available(url, payment)
    credits = value(
        url, "SELECT count(*) FROM app.customer_credits WHERE source_payment_id=%s", payment
    )
    assert (held(url, pet), net(url, refund)) == (0, 5_400)
    assert (outstanding(url, case["pet_line"]), outstanding(url, case["other_line"])) == (0, 0)
    draft = record(case, request(case, receipt))
    stored = payload(url, draft)
    assert (
        stored["variant"],
        stored["final_settlement_id"],
        stored["lease_id"],
        stored["deposit_receipt_id"],
        stored["deposit_id"],
        stored["payment_id"],
    ) == (
        "DEPOSIT_RECEIPT_CORRECTION",
        str(case["settlement"]),
        str(lease),
        str(receipt),
        str(pet),
        str(payment),
    )
    assert stored["deposit_receipt_correction"] == {
        "deposit_receipt_id": str(receipt),
        "evidence_reference": EVIDENCE,
    }
    source = stored["source"]
    assert sorted(
        (application["invoice_line_id"], application["amount_usd_cents"])
        for application in source["deposit_applications"]
    ) == sorted([(str(case["pet_line"]), 12_500), (str(case["other_line"]), 2_100)])
    [plan] = source["recoveries"]
    assert planned(plan) == (
        "DEPOSIT",
        str(customer),
        str(lease),
        5_400,
        "CLOSED_SETTLEMENT_LEASE",
        False,
        False,
    )
    assert allowed_check(url, case, source) == (None, None)
    result = confirm(case, draft)
    correction = result["settlement_correction"]["id"]
    links = effect_links(url, correction)
    assert sorted(links[:3]) == sorted(RECOVERY_LINKS)
    assert links[3:] == [
        "deposit_application_reversal_id",
        "deposit_application_reversal_id",
        "deposit_receipt_reversal_id",
    ]
    assert receipt_after_applications(url, correction)
    [recovered] = result["recoveries"]
    assert written(recovered) == (str(customer), str(lease), 5_400, "EXTRA_CHARGE")
    assert recovered["refund_id"] == str(refund)
    assert charge(url, recovered["invoice_id"]) == (
        customer,
        lease,
        "MISCELLANEOUS_CHARGES",
        "UNPAID",
        5_400,
        due_days(url, prop),
    )
    number = value(url, "SELECT refund_number FROM app.refunds WHERE id=%s", refund)
    assert (
        value(
            url,
            "SELECT description FROM app.authorized_nonrecurring_obligations WHERE id=%s",
            UUID(str(recovered["authorized_nonrecurring_obligation_id"])),
        )
        == f"Recovery of Refund {number} paid from a corrected Deposit receipt"
    )
    assert recovery_row(url, recovered["refund_correction_id"]) == (
        "RECOVERED_BY_CHARGE",
        5_400,
        5_400,
        0,
        "financial.approve",
        recovered["authorized_nonrecurring_obligation_id"],
    )
    # After the commit the recovery check is false: it accepts the row only while the receipt is
    # still active, inside the confirm that reverses it (the same transaction is tested in
    # test_the_database_guards_of_the_receipt_correction).
    assert (
        value(
            url,
            "SELECT app.refund_recovery_allowed(c) FROM app.refund_corrections c WHERE c.id=%s",
            UUID(str(recovered["refund_correction_id"])),
        )
        is False
    )
    assert result["deposit_receipt"] == {
        "id": str(receipt),
        "deposit_id": str(pet),
        "payment_id": str(payment),
        "amount_usd_cents": 20_000,
    }
    assert len(result["deposit_application_reversal_ids"]) == 2
    receipt_actor, receipt_authorization = one(
        url,
        "SELECT actor_id,authorization_reference FROM app.deposit_receipt_reversals WHERE id=%s",
        UUID(str(result["deposit_receipt_reversal_id"])),
    )
    assert (receipt_actor, receipt_authorization) == (case["person"], "deposits.correct")
    assert result["deposit"] == {"id": str(pet), "held_usd_cents": 0}
    assert result["payment"] == {
        "id": str(payment),
        "status": "RECEIVED",
        "available_usd_cents": before_available + 20_000,
    }
    assert "transaction_id" not in result["draft"]["decision"]["result"]
    assert (
        value(
            url,
            "SELECT count(*) FROM app.audit_events WHERE entity_id=%s "
            "AND action='final_settlement.correction.confirmed' "
            "AND authorization_evidence->>'variant'='DEPOSIT_RECEIPT_CORRECTION' "
            "AND customer_id=%s AND lease_id=%s",
            UUID(str(correction)),
            customer,
            lease,
        )
        == 1
    )
    assert (held(url, pet), net(url, refund)) == (0, 0)
    assert (outstanding(url, case["pet_line"]), outstanding(url, case["other_line"])) == (
        12_500,
        2_100,
    )
    assert status(url, payment) == "RECEIVED"
    assert (
        value(url, "SELECT count(*) FROM app.customer_credits WHERE source_payment_id=%s", payment)
        == credits
    )
    assert settlement_row(url, case["settlement"]) == before_row
    reconciled(url, customer)
    # An exact repeat by the same approver writes nothing and returns the result again.
    before = counts(url)
    assert confirm(case, draft) == result
    assert counts(url) == before


def test_a_wrong_security_deposit_receipt_frees_the_payment_value_for_the_debt(
    migrated_database_url: str,
) -> None:
    """The Security Deposit's 10,000 receipt, which the Settlement applied to the other damage line,
    was wrong. The direct receipt reversal is still refused after closure (P5S01); the correction
    reverses the Deposit application and then the receipt, with no recovery (nothing was
    refunded). The 10,000 is owed again by the same Customer and stays available on the Payment as
    an overpayment: staff allocate it to the debt that came back, as any allocation after
    closure."""
    url = migrated_database_url
    case = closed_case(url)
    prop, human, security, other_line = (
        case["prop"],
        case["human"],
        case["security"],
        case["other_line"],
    )
    receipt = receipt_of(url, security)
    payment = receipt_payment(url, security)
    before_row = settlement_row(url, case["settlement"])
    before_available = available(url, payment)
    with psycopg.connect(url) as connection, pytest.raises(psycopg.Error) as direct:
        connection.execute(
            "INSERT INTO app.deposit_receipt_reversals(id,deposit_receipt_id,reason,occurred_at,"
            "actor_id,authorization_reference) VALUES (gen_random_uuid(),%s,%s,clock_timestamp(),"
            "%s,'deposits.correct')",
            (receipt, REASON, human),
        )
    assert (direct.value.sqlstate, direct.value.diag.message_primary) == ("P5S01", DIRECT)
    result = confirm(case, record(case, request(case, receipt)))
    correction = result["settlement_correction"]["id"]
    assert effect_links(url, correction) == [
        "deposit_application_reversal_id",
        "deposit_receipt_reversal_id",
    ]
    assert receipt_after_applications(url, correction)
    assert result["recoveries"] == []
    [application_reversal] = result["deposit_application_reversal_ids"]
    assert one(
        url,
        "SELECT actor_id,authorization_reference,reason FROM app.deposit_application_reversals "
        "WHERE id=%s",
        UUID(str(application_reversal)),
    ) == (case["person"], "financial.approve", REASON)
    assert (held(url, security), outstanding(url, other_line)) == (0, 10_000)
    assert status(url, payment) == "RECEIVED"
    assert available(url, payment) == before_available + 10_000
    assert result["payment"]["available_usd_cents"] == before_available + 10_000
    allocations().post(
        prop,
        payment,
        designated(invoice_of(url, other_line), other_line, 10_000),
        actor=allocation_actor(human, prop),
    )
    assert (outstanding(url, other_line), available(url, payment)) == (0, before_available)
    assert settlement_row(url, case["settlement"]) == before_row
    reconciled(url, case["customer"])


def test_a_kept_deposit_is_refused_until_a_forfeiture_reversal_runs(
    migrated_database_url: str,
) -> None:
    """Owner answer (a) to Q-2026-10-11-83 point 3: the kept Security Deposit's receipt is refused
    while the forfeiture is active. After the FORFEITURE_REVERSAL correction (the Deposit pays the
    4,600 still open and 5,400 is refunded), the receipt correction recovers the 5,400 Refund by an
    EXTRA_CHARGE to the Customer, reverses the 4,600 application (owed again) and the receipt."""
    url = migrated_database_url
    case = kept_case(url)
    security, other_line, customer = case["security"], case["other_line"], case["customer"]
    receipt = receipt_of(url, security)
    payment = receipt_payment(url, security)
    before = counts(url)
    with pytest.raises(FinalSettlementConflictError) as kept:
        record(case, request(case, receipt))
    assert cause(kept) == ("55000", KEPT)
    assert counts(url) == before
    reversal = confirm_reversal(
        case,
        record_reversal(
            case,
            reversal_command(
                case,
                SettlementDepositStep(SECURITY, security, LINE, other_line, 4_600),
                settlement_refund(case, "security", 5_400),
            ),
        ),
    )
    [paid] = reversal["refunds"]
    assert (held(url, security), outstanding(url, other_line)) == (0, 0)
    before_available = available(url, payment)
    result = confirm(case, record(case, request(case, receipt)))
    [recovered] = result["recoveries"]
    assert written(recovered) == (str(customer), str(case["lease"]), 5_400, "EXTRA_CHARGE")
    assert recovered["refund_id"] == paid["id"]
    assert len(result["deposit_application_reversal_ids"]) == 1
    assert (held(url, security), outstanding(url, other_line)) == (0, 4_600)
    assert net(url, UUID(str(paid["id"]))) == 0
    assert (status(url, payment), available(url, payment)) == (
        "RECEIVED",
        before_available + 10_000,
    )
    reconciled(url, customer)


def test_a_deposit_refunded_to_the_agreed_signer_is_charged_to_that_signer(
    migrated_database_url: str,
) -> None:
    """Owner answer C to Q-2026-10-11-78 on the real two-Signer closure: a FORFEITURE_REVERSAL
    refunded the kept Security Deposit (10,000) to the second Signer with the written agreement of
    all Signers; then its receipt is found wrong. The correction charges the 10,000 to the second
    Signer, who received it, as an EXTRA_CHARGE on the Lease, and reverses the receipt; both
    ledgers reconcile."""
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
    payment = receipt_payment(url, security)
    result = confirm(case, record(case, request(case, receipt_of(url, security))))
    [recovered] = result["recoveries"]
    assert written(recovered) == (str(co_signer), str(lease), 10_000, "EXTRA_CHARGE")
    assert recovered["refund_id"] == paid["id"]
    assert charge(url, recovered["invoice_id"])[:5] == (
        co_signer,
        lease,
        "MISCELLANEOUS_CHARGES",
        "UNPAID",
        10_000,
    )
    assert result["deposit_application_reversal_ids"] == []
    assert (net(url, UUID(str(paid["id"]))), held(url, security)) == (0, 0)
    assert status(url, payment) == "RECEIVED"
    reconciled(url, case["customer"], co_signer)


def test_refusals_waiting_and_stale_drafts(migrated_database_url: str) -> None:
    """Refused with nothing written: an unknown receipt; a Settlement that is not closed; a reused
    draft id; a second draft while one waits; a recorder outside READ COMMITTED; Staff cannot
    confirm. A draft whose sources changed after it was recorded (the Settlement Refund came back
    through a return-only correction) is stale and stays pending. Each check of the refusal
    function is shown on the real source with one fact changed, read as the owner."""
    url = migrated_database_url
    case = closed_case(url)
    prop, human, pet = case["prop"], case["human"], case["pet"]
    receipt = receipt_of(url, pet)
    before = counts(url)
    with pytest.raises(FinalSettlementNotFoundError) as unknown:
        record(case, request(case, uuid4()))
    assert cause(unknown) == ("P0002", NOT_FOUND)
    open_case = leaving_case(url)
    with pytest.raises(FinalSettlementConflictError) as not_closed:
        record(open_case, request(open_case, receipt_of(url, open_case["security"])))
    assert cause(not_closed) == (
        "55000",
        "A post-settlement correction needs a closed Final Settlement",
    )
    assert counts(url)[1:] == before[1:]
    command = request(case, receipt)
    draft = record(case, command)
    with pytest.raises(FinalSettlementKeyReused):
        record(case, replace(command, reason="Another reason"))
    with pytest.raises(FinalSettlementConflictError) as waiting:
        record(case, request(case, receipt))
    assert cause(waiting) == ("55000", WAITING)
    with psycopg.connect(financial_database_url()) as connection:
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with pytest.raises(psycopg.Error) as isolation:
            connection.execute(
                f"SELECT {RECORD.split('(')[0]}(%s,%s,%s,%s,%s,%s,'final_settlements.prepare')",
                (
                    prop,
                    human,
                    uuid4(),
                    case["settlement"],
                    Jsonb({"deposit_receipt_id": str(receipt), "evidence_reference": EVIDENCE}),
                    REASON,
                ),
            )
    assert (isolation.value.sqlstate, isolation.value.diag.message_primary) == (
        "55000",
        "A Deposit receipt correction draft is recorded at READ COMMITTED",
    )
    with pytest.raises(FinalSettlementAuthorizationError):
        corrections().confirm_deposit_receipt_correction(prop, draft, actor=preparer(human, prop))
    # Each check on the real source (the Pet Deposit's, with its planned recovery), one fact
    # changed at a time; the check passes on the real source apart from this waiting draft.
    source = source_of(url, case, receipt)
    assert source["pending_drafts"] == [str(draft)]
    assert allowed_check(url, case, source) == ("55000", WAITING)
    real = {**source, "pending_drafts": []}
    assert allowed_check(url, case, real) == (None, None)

    def changed(path: tuple[Any, ...], new: object) -> dict[str, Any]:
        copy = json.loads(json.dumps(real))
        target = copy
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = new
        return cast(dict[str, Any], copy)

    for path, new, refusal in (
        (("receipt",), None, ("P0002", NOT_FOUND)),
        (("receipt", "reversed"), True, ("55000", ALREADY)),
        (("deposit", "lease_id"), str(uuid4()), ("55000", NOT_OF_LEASE)),
        (("payment", "status"), "REVERSED", ("55000", NOT_RECEIVED)),
        (("deposit", "active_forfeiture"), True, ("55000", KEPT)),
        (
            ("deposit_applications", 0, "final_settlement_id"),
            str(uuid4()),
            ("55000", OTHER_SETTLEMENT),
        ),
        (("recoveries", 0, "reservation_outcome"), True, ("55000", RESERVATION)),
        (("recoveries", 0, "shared_deposit"), True, ("55000", SHARED)),
        (
            ("recoveries", 0, "closed_final_settlement_id"),
            str(uuid4()),
            ("55000", CLOSED_ELSEWHERE),
        ),
        (("recoveries",), [], ("55000", NO_RECOVERY)),
        (("deposit", "held_usd_cents"), 1, ("55000", STILL_HOLDS)),
    ):
        assert allowed_check(url, case, changed(path, new)) == refusal, path
    # The Settlement's 5,400 Refund comes back (a return-only correction): the draft is stale and
    # stays pending.
    confirm_return(
        case, record_return(case, return_command(case, pet_refund(case), 5_400, new=False))
    )
    with pytest.raises(FinalSettlementStaleDraftError):
        confirm(case, draft)
    assert state(url, draft) == "PENDING"
    assert (
        held(url, pet),
        value(
            url,
            "SELECT count(*) FROM app.deposit_receipt_reversals WHERE deposit_receipt_id=%s",
            receipt,
        ),
    ) == (5_400, 0)


def test_the_database_guards_of_the_receipt_correction(migrated_database_url: str) -> None:
    """The database guards (review round 1): malformed input 22023; the recorder takes only
    final_settlements.prepare and the confirm only financial.approve (42501); an exact repeat
    replays and a reused key with another reason is P5205; a service identity that is not a person
    cannot confirm (P4506); the confirm runs only at READ COMMITTED (55000); no refusal writes
    anything. Once confirmed, the recorder's repeat replays the decided draft without the
    decision's transaction id and another approver finds it decided (55000). Inside a confirm's own
    transaction a second statement finds the recovery check false, because the receipt is already
    reversed."""
    url = migrated_database_url
    case = closed_case(url)
    prop, human, security, pet = case["prop"], case["human"], case["security"], case["pet"]
    receipt = receipt_of(url, security)
    before = counts(url)
    good = request(case, receipt).deposit_receipt_correction()
    for malformed in (
        {**good, "surprise": True},
        {key: item for key, item in good.items() if key != "evidence_reference"},
        {**good, "deposit_receipt_id": "not-a-uuid"},
        {**good, "deposit_receipt_id": str(UUID(int=0))},
        {**good, "evidence_reference": " padded"},
        {**good, "evidence_reference": "x" * 501},
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
    assert counts(url) == before
    command = request(case, receipt)
    first = record(case, command)
    assert record(case, command) == first
    with pytest.raises(FinalSettlementKeyReused):
        record(case, replace(command, reason="Another reason for the same key"))
    with pytest.raises(psycopg.Error) as staff, psycopg.connect(url) as connection:
        connection.execute(
            f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'final_settlements.prepare')",
            (prop, case["person"], first),
        )
    assert staff.value.sqlstate == "42501"
    with psycopg.connect(url) as connection:
        machine = register_billing_service_principal(connection, property_id=prop, created_by=human)
    with pytest.raises(FinalSettlementAuthorizationError) as not_a_person:
        corrections().confirm_deposit_receipt_correction(
            prop, first, actor=approving(machine, prop)
        )
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
    assert (state(url, first), counts(url)[1:], held(url, security)) == ("PENDING", before[1:], 0)
    result = confirm(case, first)
    decision = cast(dict[str, Any], result["draft"]["decision"])
    assert decision["decision"] == "CONFIRMED" and "transaction_id" not in decision["result"]
    replayed = corrections().record_deposit_receipt_correction(
        prop, command, actor=preparer(human, prop)
    )
    assert replayed["state"] == "CONFIRMED"
    assert "transaction_id" not in cast(
        dict[str, Any], cast(dict[str, Any], replayed["decision"])["result"]
    )
    with pytest.raises(FinalSettlementConflictError) as decided:
        corrections().confirm_deposit_receipt_correction(
            prop, first, actor=approving(approver(url), prop)
        )
    assert cause(decided) == ("55000", "Financial draft is already decided")
    # Security review round 1: inside the Pet Deposit receipt's confirm, a later statement of the
    # same transaction finds its recovery row no longer allowed (the receipt is reversed).
    pet_draft = record(case, request(case, receipt_of(url, pet)))
    with psycopg.connect(url) as connection:
        connection.execute(
            f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'financial.approve')",
            (prop, case["person"], pet_draft),
        )
        found = connection.execute(
            "SELECT bool_and(app.refund_recovery_allowed(c)),count(*) "
            "FROM app.refund_corrections c JOIN app.settlement_correction_effects e "
            "ON e.refund_correction_id=c.id "
            "WHERE e.settlement_correction_id=app.settlement_correction_id(%s)",
            (pet_draft,),
        ).fetchone()
        assert found == (False, 1)
        connection.rollback()
    assert (state(url, pet_draft), held(url, pet)) == ("PENDING", 0)


def test_deposit_receipt_corrections_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Only the financial role records and confirms; no role calls the internal functions; each new
    function is SECURITY DEFINER with the fixed search path; the migration adds only its functions,
    changes only the four listed functions (their privileges and settings kept) and is
    forward-only."""
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
            assert connection.execute(
                "SELECT p.prosecdef,p.proconfig[1] FROM pg_catalog.pg_proc p "
                "WHERE p.oid=CAST(%s AS regprocedure)",
                (function,),
            ).fetchone() == (True, "search_path=pg_catalog"), function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("20261124_120")
    assert revision is not None and revision.down_revision == "20261123_119"
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

    with _temporary_migration_database("settlement_deposit_receipt_correction") as temporary:
        alembic_command.upgrade(config, "20261123_119")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, "20261124_120")
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert (after_relations, after_triggers) == (before_relations, before_triggers)
    assert set(after_functions) - set(before_functions) == {RECORD, CONFIRM, *INTERNAL}
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED
    # Each patched function changed only its definition, never its privileges or settings, and its
    # new definition is exactly the old one with the module's replacements (review round 1): the
    # moved loop and the 10e-1a and 10e-1b recovery wording stay as they were.
    for name in PATCHED:
        assert after_functions[name][1:] == before_functions[name][1:], name
    assert {function for function, _ in revision.module.PATCHES} == PATCHED
    for function, replacements in revision.module.PATCHES:
        body = str(before_functions[function][0])
        for anchor, replacement in replacements:
            assert body.count(anchor) == 1, function
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function
