"""V1-056 sub-slice 8d: Final Settlement Deposit Refunds and their Refund source check."""

from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.deposit_receipt_reversal import (
    DepositReceiptReversalConflictError,
    DepositReceiptReversalService,
    RecordDepositReceiptReversalCommand,
)
from property_rental.final_settlement import SettlementDepositStep
from property_rental.lease_deposit_forfeiture import (
    RecordLeaseDepositForfeitureCommand,
    RecordLeaseDepositReversalCommand,
)
from test_final_settlement_draft_migration import (
    APPROVE,
    CHOICE,
    LINE,
    PET_FIRST,
    PET_REST,
    SECURITY,
    drafts,
    leaving_case,
    record,
    refund,
    two_signer_case,
    withdraw,
)
from test_final_settlement_migration import apply, held, one, outstanding, pet_deposit, today
from test_final_settlement_preview_migration import forfeitures, key_card, pay, person, preview
from test_invoice_migration import (
    financial_database_url,
    invoice_api_actor,
    runtime_database_url,
    setup_signed_lease,
)
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_one_time_charges_migration import draft_and_issue, invoices

POST = "SELECT app.post_final_settlement_deposit_refund(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
NOTE = "Cash handed over at the front desk"
REASON = "Remaining Deposit refunded at Final Settlement"
AGREEMENT = "All Signers agreed in writing on 2026-10-05 that the Signer receives the Refund"
OPEN_DEBT = "No Deposit Refund while the Lease still has open debt that a Deposit could pay"
DRAFT_WAITING = "A Deposit receipt reversal or forfeiture draft for this Deposit is waiting"
NOT_IN_DRAFT = (
    "A Final Settlement Refund must be a Refund step of a waiting or confirmed draft of this "
    "Settlement"
)
REFUND_KEYS = {
    "id",
    "refund_number",
    "source_payment_id",
    "source_customer_credit_id",
    "source_deposit_id",
    "source_lifecycle_event_id",
    "pet_refund_review_id",
    "recipient_customer_id",
    "refund_amount_minor",
    "refund_currency",
    "usd_accounting_value_cents",
    "processed_at",
    "processed_by",
    "reason",
    "authorization_reference",
}
NOT_CONFIRMED = (
    "A Final Settlement Refund needs its draft confirmed under financial.approve by the same "
    "approver"
)
INTERNAL = (
    "app.assert_final_settlement_refund_source(app.refunds)",
    "app.assert_final_settlement_refund_confirmed()",
    "app.post_final_settlement_deposit_refund(uuid,uuid,uuid,uuid,uuid,uuid,bigint,uuid,uuid,"
    "text,text,text)",
)


def post(
    url: str,
    case: dict[str, Any],
    draft: object,
    deposit: str,
    amount: int,
    **changes: Any,
) -> dict[str, object]:
    """The internal writer, as the Settlement confirm (8e) will call it; no role may call it."""
    values: dict[str, Any] = {
        "actor": case["human"],
        "settlement": case["settlement"],
        "refund": uuid4(),
        "recipient": case["customer"],
        "method": case["cash"],
        "note": NOTE,
        "agreement": None,
    }
    values.update(changes)
    with psycopg.connect(url) as connection:
        found = connection.execute(
            POST,
            (
                case["prop"],
                values["actor"],
                values["settlement"],
                UUID(str(draft)),
                values["refund"],
                case[deposit],
                amount,
                values["recipient"],
                values["method"],
                values["note"],
                values["agreement"],
                REASON,
            ),
        ).fetchone()
    assert found is not None and isinstance(found[0], dict)
    return cast(dict[str, object], found[0])


def refused(url: str, *arguments: Any, **changes: Any) -> tuple[Any, Any]:
    with pytest.raises(psycopg.Error) as failure:
        post(url, *arguments, **changes)
    return failure.value.sqlstate, failure.value.diag.message_primary


def invoice_of(url: str, line: UUID) -> UUID:
    return UUID(str(one(url, "SELECT invoice_id FROM app.invoice_lines WHERE id=%s", line)[0]))


def paid_case(url: str) -> dict[str, Any]:
    """The 8c leaving case with both damage charges paid by the Customer: nothing is owed, so the
    Customer's Credit has nothing to pay and both Deposits are refunded in full."""
    case = leaving_case(url)
    for line in ("pet_line", "other_line"):
        pay(
            url,
            case["prop"],
            case["human"],
            case["customer"],
            invoice_of(url, case[line]),
            case[line],
            12_500,
        )
    view = preview(case["prop"], case["human"], case["settlement"])
    assert view["ready"] is True and view["open_total_usd_cents"] == 0
    return case


def refund_rows(url: str, settlement: UUID) -> int:
    return int(
        one(
            url,
            "SELECT count(*) FROM app.refunds refund JOIN app.final_settlement_refund_details "
            "detail ON detail.refund_id=refund.id WHERE detail.final_settlement_id=%s",
            settlement,
        )[0]
    )


def confirm(url: str, case: dict[str, Any], draft: object, approver: UUID | None = None) -> None:
    """The draft decision the Settlement confirm (8e) writes, through the shared slice 2 record."""
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.confirm_financial_draft_record(%s,%s,%s,'FINAL_SETTLEMENT','{}'::jsonb,"
            "'financial.approve')",
            (case["prop"], approver or case["human"], UUID(str(draft))),
        )


def pay_open_lines(url: str, case: dict[str, Any]) -> None:
    """The Customer pays every open line of the Lease's issued Invoices."""
    with psycopg.connect(url) as connection:
        lines = connection.execute(
            "SELECT line.invoice_id,line.id,app.invoice_line_outstanding(line.id) "
            "FROM app.invoice_lines line JOIN app.invoices invoice ON invoice.id=line.invoice_id "
            "WHERE invoice.lease_id=%s AND invoice.status IN ('UNPAID','PARTIALLY_PAID') "
            "AND app.invoice_line_outstanding(line.id)>0 ORDER BY line.id",
            (case["lease"],),
        ).fetchall()
    for invoice, line, amount in lines:
        pay(url, case["prop"], case["human"], case["customer"], invoice, line, int(amount))


def new_debt(url: str, case: dict[str, Any]) -> tuple[UUID, UUID]:
    """A 1,500 key card charged to the Primary Tenant after the draft: new open debt."""
    staff = invoice_api_actor(case["human"], case["prop"])
    charge = key_card(case["customer"], case["lease"])
    invoices().record_one_time_charge(case["prop"], charge, actor=staff)
    invoice = UUID(str(draft_and_issue(case["prop"], charge.charge_id, staff)["id"]))
    line = UUID(str(one(url, "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", invoice)[0]))
    return invoice, line


def reverse_security_forfeiture(url: str, case: dict[str, Any]) -> None:
    """Forfeit the Security Deposit through its draft, then reverse it through its draft: it is
    held again and follows DL-032 (owner answer to Q-2026-10-05-24)."""
    prop, human, security = case["prop"], case["human"], case["security"]
    approver = person(human, prop, APPROVE)
    forfeiture = forfeitures().record(
        prop,
        RecordLeaseDepositForfeitureCommand(uuid4(), security, uuid4(), "Deposit kept"),
        actor=person(human, prop, "deposits.dispose"),
    )
    forfeitures().confirm(prop, security, UUID(str(forfeiture["draft_id"])), actor=approver)
    disposition = UUID(
        str(one(url, "SELECT id FROM app.deposit_dispositions WHERE deposit_id=%s", security)[0])
    )
    reversal = forfeitures().record_reversal(
        prop,
        RecordLeaseDepositReversalCommand(
            uuid4(), disposition, uuid4(), "Wrong ground recorded", "CASE-8D"
        ),
        actor=person(human, prop, "deposits.correct"),
    )
    forfeitures().confirm_reversal(
        prop, disposition, UUID(str(reversal["draft_id"])), actor=approver
    )


def test_a_settlement_refund_pays_each_deposit_separately_from_its_draft(
    migrated_database_url: str,
) -> None:
    """BR-DEP-025, BR-REFUND-007, BR-REFUND-014 and BR-SETTLE-008: each remaining Deposit is
    refunded by its own Refund event linked to the Final Settlement, with the method and reference
    note of the draft's Refund step, once the draft is confirmed by the approver (BR-AUTH-010); the
    Customer Ledger books it on the Deposit owner."""
    url = migrated_database_url
    case = paid_case(url)
    draft = record(case, (refund(case, "security", 10_000), refund(case, "pet", 20_000)))
    draft_id = draft["draft_id"]
    confirm(url, case, draft_id)
    security = post(url, case, draft_id, "security", 10_000)
    pet = post(url, case, draft_id, "pet", 20_000)
    assert (held(url, case["security"]), held(url, case["pet"])) == (0, 0)
    for result, deposit, amount in ((security, "security", 10_000), (pet, "pet", 20_000)):
        assert result["amount_usd_cents"] == amount and result["draft_id"] == str(draft_id)
        row = one(
            url,
            "SELECT source_deposit_id,recipient_customer_id,"
            "usd_accounting_value_cents,refund_currency,refund_amount_minor,processed_by,"
            "authorization_reference,pet_refund_review_id,source_lifecycle_event_id "
            "FROM app.refunds WHERE id=%s",
            result["refund_id"],
        )
        assert row == (
            case[deposit],
            case["customer"],
            amount,
            "USD",
            amount,
            case["human"],
            APPROVE,
            None,
            None,
        )
        assert one(
            url,
            "SELECT final_settlement_id,deposit_id,draft_id,refund_method_id,reference_note,"
            "signer_agreement FROM app.final_settlement_refund_details WHERE refund_id=%s",
            result["refund_id"],
        ) == (case["settlement"], case[deposit], UUID(str(draft_id)), case["cash"], NOTE, None)
        # The existing readers see a Deposit Refund.
        summary = one(url, "SELECT app.refund_summary(%s)", result["refund_id"])[0]
        assert summary["source"] == {
            "type": "DEPOSIT",
            "id": str(case[deposit]),
            "property_id": str(case["prop"]),
        }
        # The Refund row keeps its keys: the readers and the frontend check them exactly.
        assert set(summary["refund"]) == REFUND_KEYS
        # The Customer Ledger books it on the Deposit owner (slice 3a-2) by Deposit type.
        assert one(
            url,
            "SELECT customer_id,event_kind,balance_kind,effect_usd_cents "
            "FROM app.customer_ledger_effects WHERE refund_id=%s",
            result["refund_id"],
        ) == (
            case["customer"],
            "REFUND_PAID",
            "SECURITY_DEPOSIT" if deposit == "security" else "PET_DEPOSIT",
            -amount,
        )
        # The general Refund audit names the Deposit's Lease and the approver's reference.
        assert one(
            url,
            "SELECT action,authorization_reference,lease_id,customer_id,"
            "resulting_state->>'final_settlement_id' "
            "FROM app.audit_events WHERE entity_type='refund' AND entity_id=%s",
            result["refund_id"],
        ) == ("refund.created", APPROVE, case["lease"], case["customer"], str(case["settlement"]))
    # One Refund per Deposit per Settlement.
    with pytest.raises(psycopg.Error) as again:
        post(url, case, draft_id, "pet", 20_000)
    assert (again.value.sqlstate, again.value.diag.constraint_name) == (
        "23505",
        "final_settlement_refund_once_per_deposit",
    )
    assert refund_rows(url, case["settlement"]) == 2
    # The Refund rows and their details are append-only.
    with psycopg.connect(url) as connection:
        for statement in (
            "UPDATE app.final_settlement_refund_details SET reference_note='Changed' "
            "WHERE refund_id=%s",
            "DELETE FROM app.final_settlement_refund_details WHERE refund_id=%s",
            "UPDATE app.refunds SET reason='Changed' WHERE id=%s",
            "DELETE FROM app.refunds WHERE id=%s",
        ):
            with pytest.raises(psycopg.Error) as mutation, connection.transaction():
                connection.execute(statement, (security["refund_id"],))
            assert mutation.value.sqlstate == "55000", statement
        with pytest.raises(psycopg.Error) as truncation, connection.transaction():
            connection.execute("TRUNCATE app.final_settlement_refund_details")
        assert truncation.value.sqlstate == "55000"


def test_settlement_refund_refusals_change_nothing(migrated_database_url: str) -> None:
    """The Refund source check refuses a Refund that is not exactly a Refund step of a pending
    draft of the Settlement or of one the same approver confirmed, names a recipient or method the
    rules do not allow, comes from a closed Settlement, has no human approver or no source
    context, or uses the one-call reference; a Refund commits only once its draft is confirmed by
    the same approver under financial.approve (BR-AUTH-010); nothing is written by a refusal."""
    url = migrated_database_url
    case = paid_case(url)
    prop, human = case["prop"], case["human"]
    steps = (refund(case, "security", 10_000), refund(case, "pet", 20_000))
    conflict, invalid = "55000", "23514"
    # A withdrawn and a rejected draft pay nothing.
    withdrawn = record(case, steps)
    withdraw(case, withdrawn)
    rejected = record(case, steps)
    drafts().reject(
        prop, UUID(str(rejected["draft_id"])), "Recount", actor=person(human, prop, APPROVE)
    )
    # The draft's own method, deactivated after the draft, is refused (BR-REFUND-014).
    method = uuid4()
    with psycopg.connect(runtime_database_url()) as connection:
        connection.execute(
            "SELECT app.create_refund_method(%s,%s,%s,%s,%s,%s)",
            (
                prop,
                human,
                method,
                f"SETTLE_{method.hex[:8].upper()}",
                "Settlement test",
                "property.manage",
            ),
        )
    inactive = record(
        case,
        (refund(case, "security", 10_000, refund_method_id=method), refund(case, "pet", 20_000)),
    )
    with psycopg.connect(runtime_database_url()) as connection:
        connection.execute(
            "SELECT app.set_refund_method_active(%s,%s,%s,false,%s)",
            (prop, human, method, "property.manage"),
        )
    assert refused(url, case, inactive["draft_id"], "security", 10_000, method=method) == (
        conflict,
        "Refund Method is not active",
    )
    withdraw(case, inactive)
    draft = record(case, steps)
    draft_id = draft["draft_id"]
    cases: list[tuple[tuple[Any, ...], dict[str, Any], tuple[str, str]]] = [
        ((withdrawn["draft_id"], "security", 10_000), {}, (invalid, NOT_IN_DRAFT)),
        ((rejected["draft_id"], "security", 10_000), {}, (invalid, NOT_IN_DRAFT)),
        ((draft_id, "security", 9_999), {}, (invalid, NOT_IN_DRAFT)),
        ((draft_id, "security", 10_000), {"note": "Another note"}, (invalid, NOT_IN_DRAFT)),
        (
            (draft_id, "security", 10_000),
            {"agreement": AGREEMENT},
            (invalid, "The Primary Tenant needs no Signer agreement"),
        ),
        (
            (draft_id, "security", 10_000),
            {"recipient": uuid4(), "agreement": AGREEMENT},
            (
                invalid,
                "A Refund to another Signer needs a signed Signer and the written agreement of "
                "all Signers",
            ),
        ),
        (
            (draft_id, "security", 10_000),
            {"actor": UUID(int=1)},
            ("42501", "A Final Settlement Refund needs a human approver"),
        ),
        # Every check passes, but the draft is still pending when the Refund commits.
        ((draft_id, "security", 10_000), {}, ("42501", NOT_CONFIRMED)),
    ]
    for arguments, changes, expected in cases:
        assert refused(url, case, *arguments, **changes) == expected, expected
    # A closed Settlement takes no Refund, in a transaction that is rolled back.
    with pytest.raises(psycopg.Error) as closed, psycopg.connect(url) as connection:
        connection.execute(
            "UPDATE app.final_settlements SET closed_at=clock_timestamp(),closed_by=%s,"
            "source_snapshot='{}'::jsonb,closing_balance_due_usd_cents=0 WHERE id=%s",
            (human, case["settlement"]),
        )
        connection.execute(
            POST,
            (
                prop,
                human,
                case["settlement"],
                draft_id,
                uuid4(),
                case["security"],
                10_000,
                case["customer"],
                case["cash"],
                NOTE,
                None,
                REASON,
            ),
        )
    assert (closed.value.sqlstate, closed.value.diag.message_primary) == (
        conflict,
        "A closed Final Settlement takes no new Refund",
    )
    # A direct Deposit Refund row with no source context is refused; with the Settlement details
    # recorded, the one-call reference refunds.create is refused too (both rolled back).
    insert_refund = (
        "INSERT INTO app.refunds(id,refund_number,recipient_customer_id,source_deposit_id,"
        "usd_accounting_value_cents,refund_currency,refund_amount_minor,reason,processed_at,"
        "processed_by,authorization_reference) VALUES "
        "(%s,%s,%s,%s,10000,'USD',10000,%s,clock_timestamp(),%s,'refunds.create')"
    )
    for with_details, message in (
        (
            False,
            "A Deposit Refund needs its Reservation, Pet Refund review or Final Settlement source",
        ),
        (True, "Final Settlement Refund amount, authorization or chronology is invalid"),
        (
            "pet",
            "A Deposit Refund needs its Reservation, Pet Refund review or Final Settlement source",
        ),
    ):
        with pytest.raises(psycopg.Error) as bare, psycopg.connect(url) as connection:
            refund_id = uuid4()
            if with_details:
                # True: the details name this Deposit; "pet": they name the other Deposit.
                detail_deposit = case["pet"] if with_details == "pet" else case["security"]
                connection.execute(
                    "INSERT INTO app.final_settlement_refund_details(refund_id,final_settlement_id,"
                    "deposit_id,draft_id,refund_method_id,reference_note,signer_agreement,"
                    "recorded_at) VALUES (%s,%s,%s,%s,%s,%s,NULL,clock_timestamp())",
                    (refund_id, case["settlement"], detail_deposit, draft_id, case["cash"], NOTE),
                )
            connection.execute(
                insert_refund,
                (refund_id, f"REF-{refund_id}", case["customer"], case["security"], REASON, human),
            )
        assert (bare.value.sqlstate, bare.value.diag.message_primary) == (invalid, message)
    # A Deposit of another Lease, an unknown Settlement and an invalid Refund identity.
    with psycopg.connect(url) as connection:
        other_lease = setup_signed_lease(connection)[3]
    foreign = {**case, "foreign": pet_deposit(url, human, prop, other_lease, today(url))}
    assert refused(url, foreign, draft_id, "foreign", 100) == (
        invalid,
        "The Refund source must be a Deposit of the terminated Settlement Lease",
    )
    assert refused(url, case, draft_id, "security", 10_000, settlement=uuid4()) == (
        "P0002",
        "Final Settlement was not found",
    )
    assert refused(url, case, draft_id, "security", 10_000, refund=UUID(int=0)) == (
        "22023",
        "Final Settlement Refund input is invalid",
    )
    # No refusal wrote a Refund or a detail.
    assert refund_rows(url, case["settlement"]) == 0
    assert one(
        url,
        "SELECT count(*) FROM app.final_settlement_refund_details WHERE final_settlement_id=%s",
        case["settlement"],
    ) == (0,)
    assert (held(url, case["security"]), held(url, case["pet"])) == (10_000, 20_000)
    # Confirmed by this approver: another active approver may not record its Refunds.
    confirm(url, case, draft_id)
    with psycopg.connect(url) as connection:
        other = setup_signed_lease(connection)[0]
    assert refused(url, case, draft_id, "security", 10_000, actor=other) == (invalid, NOT_IN_DRAFT)
    post(url, case, draft_id, "security", 10_000)
    # New debt after the Security Refund: the Pet Deposit could pay it by the staff step (no
    # BR-DEP-027 ground), so its Refund waits (owner answer 3 to Q-2026-10-05-20).
    invoice, line = new_debt(url, case)
    assert refused(url, case, draft_id, "pet", 20_000) == (conflict, OPEN_DEBT)
    pay(url, prop, human, case["customer"], invoice, line, 1_500)
    post(url, case, draft_id, "pet", 20_000)
    assert refund_rows(url, case["settlement"]) == 2


def test_a_settlement_refund_is_not_corrected_by_a_one_call_correction(
    migrated_database_url: str,
) -> None:
    """A Final Settlement Refund is corrected only through a post-settlement correction
    (BR-SETTLE-013, slice 10); the one-call Refund correction path refuses it, and a Deposit
    application of the Settlement after its Refunds is refused (BR-SETTLE-008)."""
    url = migrated_database_url
    case = paid_case(url)
    draft = record(case, (refund(case, "security", 10_000), refund(case, "pet", 20_000)))
    confirm(url, case, draft["draft_id"])
    result = post(url, case, draft["draft_id"], "security", 10_000)
    with pytest.raises(psycopg.Error) as path, psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.require_correctable_usd_refund(%s,%s)", (case["prop"], result["refund_id"])
        )
    assert (path.value.sqlstate, path.value.diag.message_primary) == (
        "P5202",
        "Refund requires its source-specific coordinated correction path",
    )
    with pytest.raises(psycopg.Error) as direct, psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.refund_corrections(id,refund_id,correction_kind,"
            "source_balance_effect_usd_cents,source_balance_effect_original_minor,"
            "previous_net_refund_usd_cents,resulting_net_refund_usd_cents,reason,"
            "evidence_reference,occurred_at,actor_id,authorization_reference,"
            "verified_return_amount_minor,verified_return_currency,verified_returned_at,"
            "return_method_reference) VALUES (%s,%s,'VALUE_CORRECTION',100,100,10000,9900,"
            "'Returned to the office','Bank slip',clock_timestamp(),%s,'refunds.correct',100,"
            "'USD',clock_timestamp(),'Bank slip 1')",
            (uuid4(), result["refund_id"], case["human"]),
        )
    assert (direct.value.sqlstate, direct.value.diag.message_primary) == (
        "23514",
        "A Final Settlement Refund is corrected only through a post-settlement correction",
    )
    with pytest.raises(psycopg.Error) as late, psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.post_deposit_application(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                case["prop"],
                case["human"],
                case["settlement"],
                uuid4(),
                case["pet"],
                "PET_RELATED_FIRST",
                "INVOICE_LINE",
                case["pet_line"],
                1,
                1,
                REASON,
            ),
        )
    assert (late.value.sqlstate, late.value.diag.message_primary) == (
        "55000",
        "Deposit applications are recorded before the Final Settlement Refunds",
    )
    assert held(url, case["security"]) == 0 and held(url, case["pet"]) == 20_000


def test_a_br_dep_027_pet_refund_waits_only_for_pet_damage_when_the_security_is_kept(
    migrated_database_url: str,
) -> None:
    """Unpaid Initial Rent (BR-LEASE-005, a BR-DEP-027 termination) with the Security Deposit
    kept by a confirmed forfeiture (BR-DEP-026): the Pet Deposit Refund waits for the pet damage
    only; without the Customer's choice the rest is refunded and the other debt stays
    (Q-2026-10-05-21)."""
    url = migrated_database_url
    case = leaving_case(url, unpaid_initial=True)
    prop, human, security = case["prop"], case["human"], case["security"]
    approver = person(human, prop, APPROVE)
    forfeiture = forfeitures().record(
        prop,
        RecordLeaseDepositForfeitureCommand(uuid4(), security, uuid4(), "Deposit kept"),
        actor=person(human, prop, "deposits.dispose"),
    )
    forfeitures().confirm(prop, security, UUID(str(forfeiture["draft_id"])), actor=approver)
    view = preview(prop, human, case["settlement"])
    assert view["ready"] is True and view["steps"][4]["chosen_by"] == "CUSTOMER_ONLY"
    assert held(url, security) == 0
    draft = record(
        case,
        (
            SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], 12_500),
            refund(case, "pet", 7_500),
        ),
    )
    draft_id = draft["draft_id"]
    confirm(url, case, draft_id)
    # A kept Security Deposit is never refunded (BR-DEP-026).
    assert refused(url, case, draft_id, "security", 1) == (
        "23514",
        "Only a Deposit that follows DL-032 is refunded at Final Settlement",
    )
    assert refused(url, case, draft_id, "pet", 7_500) == ("55000", OPEN_DEBT)
    apply(
        url,
        prop,
        human,
        case["settlement"],
        case["pet"],
        "PET_RELATED_FIRST",
        "INVOICE_LINE",
        case["pet_line"],
        12_500,
        1,
    )
    post(url, case, draft_id, "pet", 7_500)
    assert held(url, case["pet"]) == 0 and outstanding(url, case["other_line"]) == 12_500


def test_a_br_dep_027_pet_refund_waits_for_pet_damage_and_a_usable_security_deposit(
    migrated_database_url: str,
) -> None:
    """Unpaid Initial Rent (BR-LEASE-005) with the Security Deposit's forfeiture reversed, so it
    follows DL-032 (owner answer to Q-2026-10-05-24). The Pet Deposit Refund waits for the pet
    damage and for the Security Deposit, which could pay the other debt; without the Customer's
    choice it does not wait for that debt (Q-2026-10-05-21)."""
    url = migrated_database_url
    case = leaving_case(url, unpaid_initial=True)
    prop, human, security = case["prop"], case["human"], case["security"]
    reverse_security_forfeiture(url, case)
    view = preview(prop, human, case["settlement"])
    assert view["ready"] is True and view["steps"][4]["chosen_by"] == "CUSTOMER_ONLY"
    assert held(url, security) == 10_000
    draft = record(
        case,
        (
            SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], 12_500),
            SettlementDepositStep(SECURITY, security, LINE, case["other_line"], 10_000),
            refund(case, "pet", 7_500),
        ),
    )
    draft_id = draft["draft_id"]
    confirm(url, case, draft_id)
    apply(
        url,
        prop,
        human,
        case["settlement"],
        case["pet"],
        "PET_RELATED_FIRST",
        "INVOICE_LINE",
        case["pet_line"],
        12_500,
        1,
    )
    # Pet damage is paid; the Security Deposit could still pay the other debt.
    assert refused(url, case, draft_id, "pet", 7_500) == ("55000", OPEN_DEBT)
    apply(
        url,
        prop,
        human,
        case["settlement"],
        security,
        "SECURITY_EXPLICIT",
        "INVOICE_LINE",
        case["other_line"],
        10_000,
        2,
    )
    # Now only debt the Pet Deposit may not pay without the Customer's choice is left.
    owed = outstanding(url, case["other_line"])
    assert owed == 2_500
    post(url, case, draft_id, "pet", 7_500)
    assert (held(url, case["pet"]), held(url, security)) == (0, 0)
    assert outstanding(url, case["other_line"]) == owed


def test_a_security_refund_waits_for_any_debt_even_where_the_pet_deposit_may_not_pay_it(
    migrated_database_url: str,
) -> None:
    """Unpaid Initial Rent (BR-LEASE-005) with the Security Deposit's forfeiture reversed: the
    Security Deposit may pay any open debt of the Lease, so its Refund waits for new debt even
    where the Pet Deposit may not pay it without the Customer's choice (owner answer 3 to
    Q-2026-10-05-20)."""
    url = migrated_database_url
    case = leaving_case(url, unpaid_initial=True)
    prop, human = case["prop"], case["human"]
    reverse_security_forfeiture(url, case)
    pay_open_lines(url, case)
    view = preview(prop, human, case["settlement"])
    assert view["ready"] is True and view["open_total_usd_cents"] == 0
    draft = record(case, (refund(case, "security", 10_000), refund(case, "pet", 20_000)))
    draft_id = draft["draft_id"]
    confirm(url, case, draft_id)
    invoice, line = new_debt(url, case)
    assert refused(url, case, draft_id, "security", 10_000) == ("55000", OPEN_DEBT)
    pay(url, prop, human, case["customer"], invoice, line, 1_500)
    post(url, case, draft_id, "security", 10_000)
    post(url, case, draft_id, "pet", 20_000)
    assert (held(url, case["security"]), held(url, case["pet"])) == (0, 0)


def test_a_settlement_refund_to_another_signer_needs_the_signers_agreement(
    migrated_database_url: str,
) -> None:
    """BR-REFUND-015: a Deposit Refund goes to the Primary Tenant, or to another signed Signer
    with the written agreement of all Signers; the Customer Ledger books it on the Deposit owner
    and names the Signer who was paid (slice 3a-2)."""
    url = migrated_database_url
    case = two_signer_case(url)
    prop, human = case["prop"], case["human"]
    signer_line = case["signer_line"]
    pay(url, prop, human, case["co_signer"], invoice_of(url, signer_line), signer_line, 1_000)
    to_signer = refund(
        case, "pet", 18_500, recipient_customer_id=case["co_signer"], signer_agreement=AGREEMENT
    )
    draft = record(
        case,
        (
            SettlementDepositStep(PET_REST, case["pet"], LINE, case["tenant_line"], 1_500),
            to_signer,
        ),
        pet_remainder=CHOICE,
    )
    draft_id = draft["draft_id"]
    confirm(url, case, draft_id)
    apply(
        url,
        prop,
        human,
        case["settlement"],
        case["pet"],
        "PET_REMAINDER_EXPLICIT",
        "INVOICE_LINE",
        case["tenant_line"],
        1_500,
        1,
    )
    signer_refusal = (
        "23514",
        "A Refund to another Signer needs a signed Signer and the written agreement of all Signers",
    )
    assert refused(url, case, draft_id, "pet", 18_500, recipient=case["co_signer"]) == (
        signer_refusal
    )
    assert (
        refused(url, case, draft_id, "pet", 18_500, recipient=uuid4(), agreement=AGREEMENT)
        == signer_refusal
    )
    result = post(
        url, case, draft_id, "pet", 18_500, recipient=case["co_signer"], agreement=AGREEMENT
    )
    assert one(
        url,
        "SELECT recipient_customer_id FROM app.refunds WHERE id=%s",
        result["refund_id"],
    ) == (case["co_signer"],)
    assert one(
        url,
        "SELECT customer_id,source_audit->>'paid_to_customer_id' FROM app.customer_ledger_effects "
        "WHERE refund_id=%s",
        result["refund_id"],
    ) == (case["tenant"], str(case["co_signer"]))
    assert one(
        url,
        "SELECT signer_agreement FROM app.final_settlement_refund_details WHERE refund_id=%s",
        result["refund_id"],
    ) == (AGREEMENT,)


def test_a_settlement_refund_waits_for_a_receipt_reversal_or_forfeiture_draft(
    migrated_database_url: str,
) -> None:
    """The owner's 8r rule (answer to Q-2026-10-05-31): no Settlement Refund while a Deposit
    receipt reversal draft or a forfeiture draft waits for the same Deposit, whether it was
    recorded before the Settlement draft was confirmed or after it; the other Deposit is not
    held back, and once that draft is decided the Refund is accepted."""
    url = migrated_database_url
    # A receipt reversal draft: while the Settlement draft waits none can be recorded (8c), so
    # it can only come after the confirmation.
    case = paid_case(url)
    prop, human = case["prop"], case["human"]
    corrector = person(human, prop, "deposits.correct", APPROVE)
    receipt = UUID(
        str(
            one(url, "SELECT id FROM app.deposit_receipts WHERE deposit_id=%s", case["security"])[0]
        )
    )
    reversals = DepositReceiptReversalService(financial_database_url())
    draft_id = record(case, (refund(case, "security", 10_000), refund(case, "pet", 20_000)))[
        "draft_id"
    ]
    with pytest.raises(DepositReceiptReversalConflictError):
        reversals.record(
            prop,
            RecordDepositReceiptReversalCommand(uuid4(), receipt, uuid4(), "Transfer returned"),
            actor=corrector,
        )
    confirm(url, case, draft_id)
    waiting = reversals.record(
        prop,
        RecordDepositReceiptReversalCommand(uuid4(), receipt, uuid4(), "Transfer returned"),
        actor=corrector,
    )
    assert refused(url, case, draft_id, "security", 10_000) == ("55000", DRAFT_WAITING)
    post(url, case, draft_id, "pet", 20_000)
    drafts().reject(prop, UUID(str(waiting["draft_id"])), "Transfer cleared", actor=corrector)
    post(url, case, draft_id, "security", 10_000)
    assert refund_rows(url, case["settlement"]) == 2
    # A forfeiture draft, recorded before the confirmation and after it.
    case = leaving_case(url, unpaid_initial=True)
    prop, human, security = case["prop"], case["human"], case["security"]
    reverse_security_forfeiture(url, case)
    pay_open_lines(url, case)
    draft_id = record(case, (refund(case, "security", 10_000), refund(case, "pet", 20_000)))[
        "draft_id"
    ]
    disposer = person(human, prop, "deposits.dispose")

    def forfeiture() -> UUID:
        recorded = forfeitures().record(
            prop,
            RecordLeaseDepositForfeitureCommand(uuid4(), security, uuid4(), "Deposit kept"),
            actor=disposer,
        )
        return UUID(str(recorded["draft_id"]))

    before = forfeiture()
    confirm(url, case, draft_id)
    assert refused(url, case, draft_id, "security", 10_000) == ("55000", DRAFT_WAITING)
    drafts().withdraw(
        prop, before, "Recorded by mistake", prepare_capability="deposits.dispose", actor=disposer
    )
    after = forfeiture()
    assert refused(url, case, draft_id, "security", 10_000) == ("55000", DRAFT_WAITING)
    post(url, case, draft_id, "pet", 20_000)
    drafts().reject(prop, after, "Wrong ground", actor=person(human, prop, APPROVE))
    post(url, case, draft_id, "security", 10_000)
    assert (held(url, security), held(url, case["pet"])) == (0, 0)


def test_the_confirmation_decides_the_commit_also_in_the_same_transaction(
    migrated_database_url: str,
) -> None:
    """BR-AUTH-010 at commit (review round 2): a Refund written before its draft's confirmation in
    the same transaction commits only when the same approver confirms; with another approver's
    confirmation nothing is written. An earlier SET CONSTRAINTS ALL IMMEDIATE in the transaction
    (as app.post_credit_application leaves it) does not stop the writer."""
    url = migrated_database_url
    case = paid_case(url)
    prop, human = case["prop"], case["human"]
    draft_id = record(case, (refund(case, "security", 10_000), refund(case, "pet", 20_000)))[
        "draft_id"
    ]
    with psycopg.connect(url) as connection:
        other = setup_signed_lease(connection)[0]
    confirm_sql = (
        "SELECT app.confirm_financial_draft_record(%s,%s,%s,'FINAL_SETTLEMENT','{}'::jsonb,"
        "'financial.approve')"
    )

    def write(approver: UUID, immediate: bool) -> None:
        with psycopg.connect(url) as connection:
            if immediate:
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
            connection.execute(
                POST,
                (
                    prop,
                    human,
                    case["settlement"],
                    draft_id,
                    uuid4(),
                    case["security"],
                    10_000,
                    case["customer"],
                    case["cash"],
                    NOTE,
                    None,
                    REASON,
                ),
            )
            connection.execute(confirm_sql, (prop, approver, draft_id))

    with pytest.raises(psycopg.Error) as another:
        write(other, False)
    assert (another.value.sqlstate, another.value.diag.message_primary) == (
        "42501",
        NOT_CONFIRMED,
    )
    assert refund_rows(url, case["settlement"]) == 0
    assert one(
        url, "SELECT count(*) FROM app.financial_draft_decisions WHERE draft_id=%s", draft_id
    ) == (0,)
    write(human, True)
    assert refund_rows(url, case["settlement"]) == 1 and held(url, case["security"]) == 0
    assert one(
        url,
        "SELECT decision,decided_by FROM app.financial_draft_decisions WHERE draft_id=%s",
        draft_id,
    ) == ("CONFIRMED", human)


def test_settlement_refund_records_are_least_privilege(migrated_database_url: str) -> None:
    url = migrated_database_url
    privileges = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
    roles = ("public", "prm_runtime", "prm_financial", "prm_bootstrap")
    with psycopg.connect(url) as connection:
        for role in roles:
            for privilege in privileges:
                assert connection.execute(
                    "SELECT has_table_privilege(%s,'app.final_settlement_refund_details',%s)",
                    (role, privilege),
                ).fetchone() == (False,), (role, privilege)
            for signature in (*INTERNAL, "app.reject_final_settlement_refund_detail_mutation()"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)
                ).fetchone() == (False,), (role, signature)
        for signature in INTERNAL:
            definer, config = cast(
                tuple[bool, list[str] | None],
                connection.execute(
                    "SELECT prosecdef,proconfig FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure",
                    (signature,),
                ).fetchone(),
            )
            assert definer is True and "search_path=pg_catalog" in (config or []), signature


def test_final_settlement_refund_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261026_91")
    assert revision is not None and revision.down_revision == "20261025_90"
    module = revision.module
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
