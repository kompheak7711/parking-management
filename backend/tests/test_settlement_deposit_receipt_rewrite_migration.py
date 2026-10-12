"""Post-settlement correction: the right receipt in a DEPOSIT_RECEIPT_CORRECTION (V1-056 sub-slice
10e-2b-1).

Owner answer 2 to Q-2026-10-11-83, answer (a) to Q-2026-10-11-86 and answers (a), (a), (a) to
Q-2026-10-12-87: after the wrong receipt's reversal, the same correction writes the right receipt
of the same Payment's freed value, into the right Deposit or for the right amount, each linked to
the correction; the draft's DL-032 plan names the new money and the correction's shared DL-032
step applies it in the DL-032 order and refunds the rest. Rule 1: a Deposit holds at most one
active receipt from each Payment. Rule 2: inside such a correction a Security Deposit's first
active receipt may differ from the accepted amount, never above the required amount. Rule 3: the
first Pet Deposit receipt writer, inside a correction only, refused while the Pet Deposit is kept.
A Deposit with a forfeiture ground follows sub-slice 10e-2c (Q-2026-10-12-88; its tests:
test_settlement_deposit_receipt_forfeiture_migration.py). A correction that
charges a Refund back on this Lease names that charge as a placeholder line since sub-slice
10e-2b-2 (its tests: test_settlement_deposit_receipt_recovery_line_migration.py).
"""

from __future__ import annotations

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
    FinalSettlementConflictError,
    FinalSettlementNotFoundError,
    FinalSettlementStaleDraftError,
    SettlementDepositStep,
)
from property_rental.settlement_correction import CorrectionDepositReceipt
from test_final_settlement_draft_migration import (
    LINE,
    PET_FIRST,
    PET_REST,
    SECURITY,
    STAFF,
    drafts,
)
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding, preparer
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_move_migration import rows, value
from test_settlement_correction_migration import settlement_row
from test_settlement_deposit_receipt_correction_migration import (
    REASON,
    available,
    confirm,
    counts,
    payload,
    receipt_of,
    record,
    request,
    source_of,
)
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_extra_charge_migration import (
    approving,
    cause,
    corrections,
    extra_charge,
    state,
)
from test_settlement_extra_charge_migration import record as record_extra_charge
from test_settlement_forfeiture_reversal_migration import (
    confirm_reversal,
    kept_case,
    record_reversal,
    reversal_command,
)
from test_settlement_refund_return_migration import confirm as confirm_return
from test_settlement_refund_return_migration import record as record_return
from test_settlement_refund_return_migration import return_command
from test_settlement_returned_payment_migration import (
    closed_case,
    receipt_payment,
    reconciled,
    status,
)

REVISION = "20261126_122"
INTERNAL = (
    "app.settlement_deposit_receipt_correction_targets(uuid,jsonb,jsonb)",
    "app.assert_settlement_deposit_receipt_targets_allowed(uuid,jsonb,jsonb)",
    "app.settlement_deposit_receipt_correction_overlay(jsonb,jsonb)",
    "app.write_correction_deposit_receipt(uuid,uuid,uuid,uuid,bigint,text,"
    "timestamp with time zone)",
)
PATCHED = {
    "app.validate_deposit_receipt()",
    "app.settlement_correction_plan_result(uuid,uuid,uuid,jsonb,jsonb)",
    "app.lock_settlement_correction_plan(uuid)",
    "app.record_settlement_deposit_receipt_correction_draft(uuid,uuid,uuid,uuid,jsonb,text,text)",
    "app.post_settlement_deposit_receipt_correction(uuid,uuid,uuid,uuid,uuid,text)",
    "app.settlement_deposit_receipt_correction_result(uuid)",
}
REBUILT = {
    "app.settlement_deposit_receipt_correction_input(jsonb)",
    "app.settlement_correction_linked(uuid,text,uuid)",
    "app.link_settlement_correction_effect(uuid,text,uuid)",
}
LINKS = (
    "deposit_application_reversal_id",
    "deposit_receipt_reversal_id",
    "deposit_receipt_id",
    "deposit_application_id",
    "refund_id",
)
ONE_ACTIVE = "A Deposit holds at most one active receipt from each Payment"
ACCEPTED = "Deposit receipt does not preserve the accepted or required amount"
TARGET_NOT_FOUND = "The Deposit of a new receipt was not found"
OTHER_LEASE = "A new receipt goes only into a Deposit of this Final Settlement's Lease"
KEPT = "A new receipt cannot go into a Deposit the Property keeps"
# Sub-slice 10e-2c (owner answer 2 to Q-2026-10-12-88) ends the "not supported yet" refusal.
NEEDS_CHOICE = (
    "A new receipt into a Deposit whose forfeiture was reversed needs a choice: "
    "DL-032 or a forfeiture again"
)
TAKES_MORE = "The new receipts take more than the corrected receipt frees"
CANNOT_FUND = "The corrected receipt's Payment cannot fund this Deposit"
ALREADY_ACTIVE = "The Deposit already holds an active receipt from this Payment"
EXCEEDS = "A new receipt would exceed the Deposit's required amount"
UNUSED = "Every remaining Deposit balance must be applied or refunded"
NOT_NAMED = "The new receipt is not one the correction's draft names"
NOT_DL032 = "Only a Deposit that follows DL-032 and holds money may be applied"


def effect_links(url: str, correction: object) -> list[str]:
    """The name of each effect's one link, in order (only the links these corrections write)."""
    found = rows(
        url,
        f"SELECT {','.join(LINKS)} FROM app.settlement_correction_effects "
        "WHERE settlement_correction_id=%s ORDER BY effect_sequence",
        correction,
    )
    return [LINKS[[item is not None for item in row].index(True)] for row in found]


def required(url: str, deposit: UUID) -> int:
    return int(
        value(url, "SELECT (app.deposit_snapshot(%s)->>'required_usd_cents')::bigint", deposit)
    )


def receipts_of(url: str, deposit: UUID) -> list[tuple[Any, ...]]:
    """Each receipt of the Deposit in date order: its Payment, amount and whether it is reversed."""
    return rows(
        url,
        "SELECT receipt.payment_id,receipt.amount_usd_cents,EXISTS(SELECT 1 "
        "FROM app.deposit_receipt_reversals reversal WHERE reversal.deposit_receipt_id=receipt.id) "
        "FROM app.deposit_receipts receipt WHERE receipt.deposit_id=%s "
        "ORDER BY receipt.occurred_at,receipt.id",
        deposit,
    )


def direct_receipt(url: str, deposit: UUID, payment: UUID, amount: int, actor: UUID) -> None:
    """Insert a receipt outside any correction, as the owner, and roll it back."""
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.deposit_receipts(id,deposit_id,payment_id,amount_usd_cents,"
            "occurred_at,actor_id) VALUES (gen_random_uuid(),%s,%s,%s,clock_timestamp(),%s)",
            (deposit, payment, amount, actor),
        )
        connection.rollback()


def targets_check(
    url: str, case: dict[str, Any], source: dict[str, Any], targets: list[dict[str, Any]]
) -> tuple[Any, Any]:
    """The refusal of the right receipts' check on a (changed) source, read as the owner; (None,
    None) when it passes."""
    with psycopg.connect(url) as connection:
        try:
            connection.execute(
                "SELECT app.assert_settlement_deposit_receipt_targets_allowed(%s,%s,%s)",
                (case["lease"], Jsonb(source), Jsonb(targets)),
            )
        except psycopg.Error as refused:
            connection.rollback()
            return refused.sqlstate, refused.diag.message_primary
    return None, None


def test_a_security_deposit_receipt_for_the_wrong_amount_is_written_again_and_applied(
    migrated_database_url: str,
) -> None:
    """Owner rules 1 and 2: the 10,000 Security Deposit receipt was really 8,000 Security Deposit
    and 2,000 Rent. The correction reverses the Settlement's 10,000 application on the other damage
    line and the whole receipt, writes an 8,000 receipt from the same Payment into the same
    Deposit (it differs from the accepted 10,000; the required amount stays) and its DL-032 step
    applies the 8,000 to the debt that came back: 2,000 stays owed by the same Customer and 2,000
    stays unallocated with the Payment. The draft shows the overlay and the result the confirm
    checks again. Outside a correction a second active receipt of that Payment is refused."""
    url = migrated_database_url
    case = closed_case(url)
    security, other_line, customer = case["security"], case["other_line"], case["customer"]
    receipt = receipt_of(url, security)
    payment = receipt_payment(url, security)
    before_row = settlement_row(url, case["settlement"])
    before_available = available(url, payment)
    before_required = required(url, security)
    draft = record(
        case,
        request(
            case,
            receipt,
            receipts=(CorrectionDepositReceipt(security, 8_000),),
            steps=(SettlementDepositStep(SECURITY, security, LINE, other_line, 8_000),),
        ),
    )
    stored = payload(url, draft)
    assert stored["plan_overlay"] == {
        "obligations": {f"INVOICE_LINE:{other_line}": 10_000},
        "credits": {},
        "deposits": {},
        "deposits_after": {str(security): 8_000},
    }
    assert (
        stored["plan_result"]["deposit_ids"],
        stored["plan_result"]["open_total_usd_cents"],
        stored["plan_result"]["closing_balance_usd_cents"],
    ) == ([str(security)], 10_000, 2_000)
    assert stored["deposit_receipt_correction"]["receipts"] == [
        {"deposit_id": str(security), "amount_usd_cents": 8_000}
    ]
    result = confirm(case, draft)
    correction = result["settlement_correction"]["id"]
    assert effect_links(url, correction) == [
        "deposit_application_reversal_id",
        "deposit_receipt_reversal_id",
        "deposit_receipt_id",
        "deposit_application_id",
    ]
    [written] = result["new_deposit_receipts"]
    assert (written["deposit_id"], written["amount_usd_cents"]) == (str(security), 8_000)
    assert one(
        url,
        "SELECT payment_id,actor_id FROM app.deposit_receipts WHERE id=%s",
        UUID(str(written["id"])),
    ) == (payment, case["person"])
    [application] = result["deposit_application_ids"]
    assert one(
        url,
        "SELECT deposit_id,invoice_line_id,amount_usd_cents,final_settlement_id "
        "FROM app.deposit_applications WHERE id=%s",
        UUID(str(application)),
    ) == (security, other_line, 8_000, case["settlement"])
    assert result["refund_ids"] == [] and result["credit_application_ids"] == []
    assert receipts_of(url, security) == [(payment, 10_000, True), (payment, 8_000, False)]
    assert (held(url, security), outstanding(url, other_line)) == (0, 2_000)
    assert required(url, security) == before_required
    assert (status(url, payment), available(url, payment)) == (
        "RECEIVED",
        before_available + 2_000,
    )
    assert result["payment"]["available_usd_cents"] == before_available + 2_000
    assert settlement_row(url, case["settlement"]) == before_row
    # The new receipt has its own Deposit audit event, by the approver, under the correction.
    assert one(
        url,
        "SELECT actor_id,authorization_reference,correlation_id,entity_type,reason "
        "FROM app.audit_events WHERE entity_id=%s AND action='deposit.receipt.recorded'",
        UUID(str(written["id"])),
    ) == (case["person"], "financial.approve", UUID(str(correction)), "deposit_receipt", REASON)
    reconciled(url, customer)
    with pytest.raises(psycopg.Error) as second:
        direct_receipt(url, security, payment, 1, case["human"])
    assert (second.value.sqlstate, second.value.diag.message_primary) == ("23505", ONE_ACTIVE)


def test_a_pet_deposit_receipt_and_then_a_split_security_receipt_are_written(
    migrated_database_url: str,
) -> None:
    """Owner rule 3 and two receipts in one correction. The Pet Deposit's 5,400 Settlement Refund
    comes back (a return-only correction), so the Pet Deposit holds 5,400. Its 20,000 receipt was
    really 18,000: the correction reverses the 12,500 and 2,100 applications and the receipt,
    writes an 18,000 Pet Deposit receipt (the overlay names its held value after the correction,
    18,000, not the 5,400 it holds now), pays pet damage first, then the other damage line by the
    staff decision, and refunds 3,400. Then the Security Deposit's 10,000 receipt was really 8,000
    Security Deposit and 2,000 Pet Deposit: both receipts are written from the same Payment and
    pay the 10,000 that came back, in the DL-032 order; nothing stays with that Payment."""
    url = migrated_database_url
    case = closed_case(url)
    security, pet, customer = case["security"], case["pet"], case["customer"]
    pet_line, other_line = case["pet_line"], case["other_line"]
    confirm_return(
        case, record_return(case, return_command(case, pet_refund(case), 5_400, new=False))
    )
    assert held(url, pet) == 5_400
    pet_payment = receipt_payment(url, pet)
    before_pet_available = available(url, pet_payment)
    draft = record(
        case,
        request(
            case,
            receipt_of(url, pet),
            receipts=(CorrectionDepositReceipt(pet, 18_000),),
            steps=(
                SettlementDepositStep(PET_FIRST, pet, LINE, pet_line, 12_500),
                SettlementDepositStep(PET_REST, pet, LINE, other_line, 2_100),
                settlement_refund(case, "pet", 3_400),
            ),
            pet_remainder=STAFF,
        ),
    )
    stored = payload(url, draft)
    assert stored["plan_overlay"]["obligations"] == {
        f"INVOICE_LINE:{pet_line}": 12_500,
        f"INVOICE_LINE:{other_line}": 2_100,
    }
    assert stored["plan_overlay"]["deposits_after"] == {str(pet): 18_000}
    result = confirm(case, draft)
    assert effect_links(url, result["settlement_correction"]["id"]) == [
        "deposit_application_reversal_id",
        "deposit_application_reversal_id",
        "deposit_receipt_reversal_id",
        "deposit_receipt_id",
        "deposit_application_id",
        "deposit_application_id",
        "refund_id",
    ]
    [refund] = result["refund_ids"]
    assert one(
        url,
        "SELECT source_deposit_id,recipient_customer_id,usd_accounting_value_cents "
        "FROM app.refunds WHERE id=%s",
        UUID(str(refund)),
    ) == (pet, customer, 3_400)
    assert (held(url, pet), outstanding(url, pet_line), outstanding(url, other_line)) == (0, 0, 0)
    assert receipts_of(url, pet) == [(pet_payment, 20_000, True), (pet_payment, 18_000, False)]
    assert available(url, pet_payment) == before_pet_available + 2_000
    reconciled(url, customer)

    receipt = receipt_of(url, security)
    payment = receipt_payment(url, security)
    before_available = available(url, payment)
    result = confirm(
        case,
        record(
            case,
            request(
                case,
                receipt,
                receipts=(
                    CorrectionDepositReceipt(security, 8_000),
                    CorrectionDepositReceipt(pet, 2_000),
                ),
                steps=(
                    SettlementDepositStep(SECURITY, security, LINE, other_line, 8_000),
                    SettlementDepositStep(PET_REST, pet, LINE, other_line, 2_000),
                ),
                pet_remainder=STAFF,
            ),
        ),
    )
    assert [
        (item["deposit_id"], item["amount_usd_cents"]) for item in result["new_deposit_receipts"]
    ] == [(str(security), 8_000), (str(pet), 2_000)]
    assert len(result["deposit_application_ids"]) == 2 and result["refund_ids"] == []
    assert (held(url, security), held(url, pet), outstanding(url, other_line)) == (0, 0, 0)
    assert receipts_of(url, security) == [(payment, 10_000, True), (payment, 8_000, False)]
    assert receipts_of(url, pet)[-1] == (payment, 2_000, False)
    assert available(url, payment) == before_available
    reconciled(url, customer)


def test_the_refusals_of_a_right_receipt(migrated_database_url: str) -> None:
    """The real refusals (each writes nothing): the Pet Deposit has no room under its required
    amount; more than the corrected receipt frees; a plan that leaves new money unused (the shared
    check), also in a correction that charges the Pet Deposit's 5,400 Settlement Refund back on this
    Lease (refused as such until sub-slice 10e-2b-2 named that charge as a placeholder line). Every
    other refusal on a changed target. A recorded draft is stale at
    its confirm when the Lease's open debt changed (the shared step compares the recorded result)
    and stays pending. After a correction without a new receipt the Security Deposit holds no
    receipt, and outside a correction a receipt that differs from the accepted amount is still
    refused, while the accepted amount from the same Payment passes (the reversed receipt no
    longer blocks it)."""
    url = migrated_database_url
    case = closed_case(url)
    security, pet, other_line, pet_line = (
        case["security"],
        case["pet"],
        case["other_line"],
        case["pet_line"],
    )
    receipt = receipt_of(url, security)
    payment = receipt_payment(url, security)
    before = counts(url)

    def refused(**changes: Any) -> tuple[Any, Any]:
        with pytest.raises(FinalSettlementConflictError) as failure:
            record(case, request(case, changes.pop("receipt", receipt), **changes))
        return cause(failure)

    security_step = SettlementDepositStep(SECURITY, security, LINE, other_line, 8_000)
    assert refused(
        receipts=(
            CorrectionDepositReceipt(security, 8_000),
            CorrectionDepositReceipt(pet, 2_000),
        ),
        steps=(security_step,),
    ) == ("55000", EXCEEDS)
    assert refused(
        receipts=(CorrectionDepositReceipt(security, 10_001),), steps=(security_step,)
    ) == ("55000", TAKES_MORE)
    assert refused(
        receipts=(CorrectionDepositReceipt(security, 8_000),),
        steps=(SettlementDepositStep(SECURITY, security, LINE, other_line, 7_000),),
    ) == ("55000", UNUSED)
    assert refused(
        receipt=receipt_of(url, pet),
        receipts=(CorrectionDepositReceipt(pet, 18_000),),
        steps=(SettlementDepositStep(PET_FIRST, pet, LINE, pet_line, 12_500),),
    ) == ("55000", UNUSED)  # 10e-2b-2: the recovery charge is a placeholder line, 5,500 unused
    with pytest.raises(FinalSettlementNotFoundError) as missing:
        record(
            case,
            request(
                case,
                receipt,
                receipts=(CorrectionDepositReceipt(uuid4(), 8_000),),
                steps=(security_step,),
            ),
        )
    assert cause(missing) == ("P0002", TARGET_NOT_FOUND)
    assert counts(url) == before
    # The writer writes only a receipt its correction's draft names (review round 1): called
    # outside any correction it refuses.
    with psycopg.connect(url) as connection, pytest.raises(psycopg.Error) as unnamed:
        connection.execute(
            "SELECT app.write_correction_deposit_receipt(%s,%s,%s,%s,8000,%s,clock_timestamp())",
            (uuid4(), case["person"], security, payment, REASON),
        )
    assert (unnamed.value.sqlstate, unnamed.value.diag.message_primary) == ("55000", NOT_NAMED)

    source = source_of(url, case, receipt)
    targets = cast(
        list[dict[str, Any]],
        value(
            url,
            "SELECT app.settlement_deposit_receipt_correction_targets(%s,%s,%s)",
            case["prop"],
            Jsonb(source),
            Jsonb([{"deposit_id": str(security), "amount_usd_cents": 8_000}]),
        ),
    )
    [target] = targets
    assert (
        target["path"]["path"],
        target["path"]["ground"],
        target["room_usd_cents"],
        target["payment_funds"],
        target["payment_receipt_active"],
    ) == ("DL_032", None, required(url, security), True, False)
    assert targets_check(url, case, source, targets) == (None, None)
    for change, refusal in (
        ({"found": False}, ("P0002", TARGET_NOT_FOUND)),
        ({"lease_id": str(uuid4())}, ("55000", OTHER_LEASE)),
        ({"path": {**target["path"], "forfeiture": "ACTIVE"}}, ("55000", KEPT)),
        # Sub-slice 10e-2c (owner answer 1 to Q-2026-10-12-88): a ground with no forfeiture now
        # passes; the correction forfeits the new money.
        ({"path": {**target["path"], "ground": "BR-DEP-023"}}, (None, None)),
        ({"amount_usd_cents": 10_001}, ("55000", TAKES_MORE)),
        ({"payment_funds": False}, ("55000", CANNOT_FUND)),
        ({"payment_receipt_active": True}, ("55000", ALREADY_ACTIVE)),
        ({"room_usd_cents": 7_999}, ("55000", EXCEEDS)),
    ):
        assert targets_check(url, case, source, [{**target, **change}]) == refusal, change
    # Sub-slice 10e-2b-2: a recovery charge on this Lease no longer refuses a new receipt.
    assert targets_check(
        url, case, {**source, "recoveries": [{"lease_id": str(case["lease"])}]}, targets
    ) == (None, None)

    draft = record(
        case,
        request(
            case,
            receipt,
            receipts=(CorrectionDepositReceipt(security, 8_000),),
            steps=(security_step,),
        ),
    )
    # A 1,500 EXTRA_CHARGE correction adds open debt on the Lease after the draft was recorded.
    corrections().confirm_extra_charge(
        case["prop"],
        record_extra_charge(case, extra_charge(case["settlement"])),
        actor=approving(case["person"], case["prop"]),
    )
    after_charge = counts(url)
    with pytest.raises(FinalSettlementStaleDraftError):
        confirm(case, draft)
    assert (state(url, draft), counts(url)) == ("PENDING", after_charge)
    assert (held(url, security), receipts_of(url, security)) == (0, [(payment, 10_000, False)])
    drafts().withdraw(
        case["prop"],
        draft,
        "Recorded again without a new receipt",
        prepare_capability="final_settlements.prepare",
        actor=preparer(case["human"], case["prop"]),
    )
    confirm(case, record(case, request(case, receipt)))
    assert receipts_of(url, security) == [(payment, 10_000, True)]
    with pytest.raises(psycopg.Error) as differs:
        direct_receipt(url, security, payment, 8_000, case["human"])
    assert (differs.value.sqlstate, differs.value.diag.message_primary) == ("23514", ACCEPTED)
    direct_receipt(url, security, payment, 10_000, case["human"])


def test_a_right_receipt_into_a_deposit_with_a_forfeiture_ground_waits_for_10e_2c(
    migrated_database_url: str,
) -> None:
    """Owner rule 3 and Q-2026-10-11-83 point 3 on the real path: while the Security Deposit is
    kept (voluntary early leaving, BR-DEP-023), the Pet Deposit's receipt correction may not move
    money into it, and the plan check refuses a held value for it after the correction.
    Q-2026-10-12-88 point 2: once a FORFEITURE_REVERSAL correction puts it back on the DL-032 path
    (Q-2026-10-11-83 point 3), a right receipt into it needs the staff's choice (sub-slice 10e-2c,
    point 2 (c)); without one it is refused. Nothing is written."""
    url = migrated_database_url
    case = kept_case(url)
    security, pet, other_line = case["security"], case["pet"], case["other_line"]
    before = counts(url)
    with pytest.raises(FinalSettlementConflictError) as kept:
        record(
            case,
            request(
                case,
                receipt_of(url, pet),
                receipts=(CorrectionDepositReceipt(security, 1_000),),
                steps=(SettlementDepositStep(SECURITY, security, LINE, other_line, 1_000),),
            ),
        )
    assert cause(kept) == ("55000", KEPT)
    with psycopg.connect(url) as connection, pytest.raises(psycopg.Error) as off_path:
        connection.execute(
            "SELECT app.settlement_correction_plan_result(%s,%s,%s,%s,%s)",
            (
                case["prop"],
                case["human"],
                case["settlement"],
                Jsonb({"steps": [], "pet_remainder": None}),
                Jsonb(
                    {
                        "obligations": {},
                        "credits": {},
                        "deposits": {},
                        "deposits_after": {str(security): 1_000},
                    }
                ),
            ),
        )
    assert (off_path.value.sqlstate, off_path.value.diag.message_primary) == ("55000", NOT_DL032)
    assert counts(url) == before
    confirm_reversal(
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
    before = counts(url)
    with pytest.raises(FinalSettlementConflictError) as ground:
        record(
            case,
            request(
                case,
                receipt_of(url, security),
                receipts=(CorrectionDepositReceipt(security, 8_000),),
                steps=(SettlementDepositStep(SECURITY, security, LINE, other_line, 8_000),),
            ),
        )
    assert cause(ground) == ("55000", NEEDS_CHOICE)
    assert counts(url) == before


def test_right_receipts_are_least_privilege_and_forward_only(migrated_database_url: str) -> None:
    """No role calls the new internal functions; each is SECURITY DEFINER with the fixed search
    path; the migration adds only its functions, replaces the receipt key by the check, adds the
    deposit_receipt_id link, changes only the listed functions (privileges and settings kept; each
    patched body is exactly the old one with the module's replacements) and is forward-only."""
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
    assert revision is not None and revision.down_revision == "20261125_121"
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
            constraints = {
                f"{row[0]}:{row[1]}:{row[2]}"
                for row in connection.execute(
                    "SELECT c.conrelid::regclass::text,c.conname,"
                    "pg_catalog.pg_get_constraintdef(c.oid) "
                    "FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=c.connamespace WHERE n.nspname='app'"
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
        return functions, constraints, triggers

    with _temporary_migration_database("settlement_deposit_receipt_rewrite") as temporary:
        alembic_command.upgrade(config, "20261125_121")
        before_functions, before_constraints, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = catalog(temporary)
    assert after_triggers == before_triggers
    removed = before_constraints - after_constraints
    added = after_constraints - before_constraints
    assert {item.split(":")[1] for item in removed} == {
        "deposit_receipts_deposit_payment_unique",
        "settlement_correction_effect_one_link",
    }
    assert {item.split(":")[1] for item in added} == {
        "settlement_correction_effect_one_link",
        "settlement_correction_effects_deposit_receipt_id_fkey",
        "settlement_correction_effects_deposit_receipt_id_key",
    }
    assert (
        "app.settlement_correction_effects:settlement_correction_effects_deposit_receipt_id_fkey:"
        "FOREIGN KEY (deposit_receipt_id) REFERENCES app.deposit_receipts(id) ON DELETE RESTRICT "
        "DEFERRABLE INITIALLY DEFERRED"
    ) in added
    [one_link] = [item for item in added if ":settlement_correction_effect_one_link:" in item]
    assert one_link.endswith("deposit_receipt_id) = 1))")
    assert set(after_functions) - set(before_functions) == set(INTERNAL)
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED | REBUILT
    for name in PATCHED | REBUILT:
        assert after_functions[name][1:] == before_functions[name][1:], name
    assert {function for function, _ in revision.module.PATCHES} == PATCHED
    for function, replacements in revision.module.PATCHES:
        body = str(before_functions[function][0])
        for anchor, replacement in replacements:
            assert body.count(anchor) == 1, function
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function
