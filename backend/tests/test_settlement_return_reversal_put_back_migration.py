"""Post-settlement correction: a return reversal's Credit put-back goes back on its own line
(sub-slice 10e-3e).

Owner answer (b) to Q-2026-10-13-104: a Credit part put back on an Invoice with Rent or Service
lines goes back on its own line, even where the Rent-first rule would choose another line today; a
put-back restores what was there before the mistake and is not a new allocation; only for a
put-back linked to the correction, on the same line, never more than the amount reversed there.
Owner answer (a) to Q-2026-10-13-106: such a put-back is labelled "put back by a correction"
(`PUT_BACK_BY_CORRECTION`), and only a correction's put-back may write that label.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from property_rental.billing import PostgresRentBillingService
from property_rental.credit import ApplyCreditCommand, CreditConflictError
from property_rental.final_settlement import SettlementCreditStep
from property_rental.payment_allocation import ReverseAllocationCommand
from rent_month_test_support import bill_unbilled_rent_months
from test_billing_service_migration import add_service, authenticated, initial_command
from test_credit_application_migration import source as credit_source
from test_credit_migration import actor as credit_actor
from test_credit_migration import service as credits
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_draft_migration import LINE
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding, pet_deposit, start, today
from test_final_settlement_preview_migration import pay
from test_invoice_migration import financial_database_url
from test_lease_migration import create_draft, setup_sources, sign_lease
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import service as allocations
from test_settlement_correction_migration import approver, settlement_row
from test_settlement_deposit_refund_correction_migration import command as refund_command
from test_settlement_deposit_refund_correction_migration import confirm_refund, record_refund
from test_settlement_held_value_refund_migration import return_only
from test_settlement_refund_correction_migration import correction as refund_correction
from test_settlement_refund_return_migration import available, refunded_case
from test_settlement_return_reversal_migration import (
    app_catalog,
    confirm_reversal,
    correction_of,
    draft_source,
    record_reversal,
    reversal_command,
)
from test_termination_deposit_migration import terminate
from test_unpaid_initial_termination_migration import rent_line

REVISION = "20261207_133"
LABEL = "PUT_BACK_BY_CORRECTION"
INTERNAL = {
    "app.validate_credit_application_put_back()",
    "app.settlement_correction_put_back_allowed(uuid,app.customer_credit_applications,"
    "app.customer_credit_application_details,integer)",
}
PATCHED = {
    "app.post_final_settlement_credit_application(uuid,uuid,uuid,uuid,integer)",
    "app.assert_settlement_correction_credit_application(app.customer_credit_applications)",
    "app.validate_credit_application_complete()",
    "app.assert_settlement_correction_credit_application_confirmed(app.customer_credit_applications)",
    "app.assert_settlement_return_reversal_allowed(jsonb)",
}
ONLY_PUT_BACK = "Only a correction's put-back is labelled put back by a correction"
APPLICATION = (
    "SELECT application.within_invoice_basis,application.proposal_trace,"
    "application.customer_designation_reference,application.final_settlement_id,"
    "application.authorization_reference,detail.attribution_basis,detail.invoice_line_id,"
    "detail.applied_amount_usd_cents,detail.calculation_trace->>'restores_credit_application_id' "
    "FROM app.customer_credit_applications application "
    "JOIN app.customer_credit_application_details detail "
    "ON detail.customer_credit_application_id=application.id WHERE application.id=%s"
)


def rows(url: str, statement: str, *parameters: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(statement, parameters).fetchall()


def open_rent_line(url: str, case: dict[str, Any]) -> tuple[UUID, int]:
    """Reverse, with one call (open until sub-slice 10h), every Payment allocation still paying
    the Initial Invoice's Rent line, so the line is open after closure; the line and what it
    owes."""
    rent, _ = rent_line(url, case["initial"])
    with psycopg.connect(url) as connection:
        paying = [
            UUID(str(row[0]))
            for row in connection.execute(
                "SELECT DISTINCT allocation.id FROM app.payment_allocations allocation "
                "JOIN app.payment_allocation_details detail "
                "ON detail.payment_allocation_id=allocation.id WHERE detail.invoice_line_id=%s "
                "AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal "
                "WHERE reversal.payment_allocation_id=allocation.id)",
                (rent,),
            ).fetchall()
        ]
    assert paying
    for allocation in paying:
        allocations().reverse_allocation(
            case["prop"],
            allocation,
            ReverseAllocationCommand(uuid4(), "Paid from the wrong transfer"),
            actor=allocation_actor(case["human"], case["prop"]),
        )
    return rent, outstanding(url, rent)


def put_back_case(url: str) -> dict[str, Any]:
    """X1 brings back 300 of a correction's Credit Refund (return only). The Initial Invoice's Rent
    line is then opened, and E brings back 900 (return only) with a step that lets the Credit pay
    1,200 of Rent: E's own 900, then X1's 300. Staff find E's return never happened: E's reversal
    reverses the 1,200 Credit payment whole and puts X1's 300 back on the Rent line."""
    case = refunded_case(url)
    credit = case["refund_credit"]
    return_only(case, case["refund"], 300)
    rent, owed = open_rent_line(url, case)
    assert owed >= 1_200
    earlier = return_only(
        case, case["refund"], 900, SettlementCreditStep(credit, LINE, rent, 1_200)
    )
    [paid] = [
        UUID(str(row[0]))
        for row in rows(
            url,
            "SELECT effect.customer_credit_application_id FROM app.settlement_correction_effects "
            "effect WHERE effect.settlement_correction_id=%s "
            "AND effect.customer_credit_application_id IS NOT NULL",
            earlier,
        )
    ]
    basis, proposal = one(url, APPLICATION, paid)[:2]
    assert (basis, proposal is not None) == ("RENT_THEN_RECURRING_SERVICES_PROPOSAL", True)
    assert (available(url, credit), outstanding(url, rent)) == (0, owed - 1_200)
    before = settlement_row(url, case["settlement"])
    draft = record_reversal(case, reversal_command(case, earlier))
    [reapply] = draft_source(url, draft)["reapply"]
    assert (reapply["application_id"], reapply["target_id"], reapply["amount_usd_cents"]) == (
        str(paid),
        str(rent),
        300,
    )
    result = confirm_reversal(case, draft)
    [restored] = result["reapplied"]
    case.update(
        rent=rent,
        owed=owed,
        paid=paid,
        restored=UUID(str(restored["id"])),
        result=result,
        before=before,
        draft=draft,
    )
    return case


def test_a_credit_put_back_on_a_rent_invoice_is_labelled_and_names_what_it_restores(
    migrated_database_url: str,
) -> None:
    """The put-back on the Rent line carries "put back by a correction" on the payment and on its
    line, no Rent-first proposal, and names the reversed payment it restores; exactly E's 900 is
    owed again, the Credit holds nothing, every record is linked, the Settlement row is unchanged,
    a repeat replays and the ledger reconciles."""
    url = migrated_database_url
    case = put_back_case(url)
    credit, rent, owed, paid, restored = (
        case["refund_credit"],
        case["rent"],
        case["owed"],
        case["paid"],
        case["restored"],
    )
    assert one(url, APPLICATION, restored) == (
        LABEL,
        None,
        None,
        case["settlement"],
        "financial.approve",
        LABEL,
        rent,
        300,
        str(paid),
    )
    assert (available(url, credit), outstanding(url, rent)) == (0, owed - 300)
    assert one(
        url,
        "SELECT count(*) FROM app.settlement_correction_effects "
        "WHERE settlement_correction_id=%s AND customer_credit_application_id=%s",
        correction_of(case["result"]),
        restored,
    ) == (1,)
    assert settlement_row(url, case["settlement"]) == case["before"]
    assert confirm_reversal(case, case["draft"]) == case["result"]
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_the_q104_example_puts_the_service_part_back_on_its_own_line(
    migrated_database_url: str,
) -> None:
    """Owner answer (b) to Q-2026-10-13-104 on the real path (set-up of the round 1 independent
    reviewer): an Initial Invoice with Rent, Trash and Internet lines, all paid; a closed
    Settlement that only refunds the Pet Deposit; a REFUND correction of a month's Rent line pays
    2,000 back as a correction Credit Refund. E brings back 900 + p of it (return only, held). The
    Rent line's last 1,000 and the Trash line (prorated, so p is its whole amount up to 500) are
    opened with one call; S brings back 100 more and its steps let the Credit pay 1,000 of Rent,
    then p of Trash (the Rent-first order). S's own 100 and p - 100 of E's money are on the newer
    Trash payment, E's other 1,000 on the Rent payment. E's reversal reverses both payments whole
    and puts S's 100 back on the Trash line, put back by a correction, while the Rent line is owed,
    so the Rent-first proposal would have chosen Rent: exactly E's 900 + p is owed again (Rent
    1,000, Trash p - 100) and the Credit holds nothing."""
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
    initial = (
        PostgresRentBillingService(financial_database_url(), prop, human)
        .generate(initial_command(lease, uuid4()), actor=authenticated(human, prop))
        .invoice_id
    )
    pet = pet_deposit(url, human, prop, lease, today(url))
    [(rent, rent_owed), (trash, trash_owed), (internet, internet_owed)] = [
        (UUID(str(row[0])), int(row[1]))
        for row in rows(
            url,
            "SELECT id,app.invoice_line_outstanding(id) FROM app.invoice_lines "
            "WHERE invoice_id=%s ORDER BY line_sequence,id",
            initial,
        )
    ]
    part = min(trash_owed, 500)
    assert rent_owed > 1_000 and part > 100
    pay(url, prop, human, tenant, initial, rent, rent_owed - 1_000)
    rent_payment = pay(url, prop, human, tenant, initial, rent, 1_000)
    trash_payment = pay(url, prop, human, tenant, initial, trash, trash_owed)
    pay(url, prop, human, tenant, initial, internet, internet_owed)
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
    confirm_settlement(
        case,
        record_settlement(case, (settlement_refund(case, "pet", held(url, pet)),)),
    )
    case["person"] = approver(url)
    [(month_rent,)] = rows(
        url,
        "SELECT line.id FROM app.invoice_lines line JOIN app.invoices invoice "
        "ON invoice.id=line.invoice_id WHERE invoice.lease_id=%s AND invoice.id<>%s "
        "AND line.category='RENT' AND invoice.status='PAID' "
        "ORDER BY invoice.issued_at,invoice.id LIMIT 1",
        lease,
        initial,
    )
    [paid] = confirm_refund(case, record_refund(case, refund_command(case, month_rent, 2_000)))[
        "refunds"
    ]
    refund, credit = UUID(str(paid["id"])), UUID(str(paid["source_customer_credit_id"]))
    assert (paid["amount_usd_cents"], available(url, credit)) == (2_000, 0)
    earlier = return_only(case, refund, 900 + part)
    for payment in (rent_payment, trash_payment):
        [(allocation,)] = rows(
            url, "SELECT id FROM app.payment_allocations WHERE payment_id=%s", payment
        )
        allocations().reverse_allocation(
            prop,
            UUID(str(allocation)),
            ReverseAllocationCommand(uuid4(), "Paid from the wrong transfer"),
            actor=allocation_actor(human, prop),
        )
    assert (outstanding(url, rent), outstanding(url, trash)) == (1_000, trash_owed)
    return_only(
        case,
        refund,
        100,
        SettlementCreditStep(credit, LINE, rent, 1_000),
        SettlementCreditStep(credit, LINE, trash, part),
    )
    assert (available(url, credit), outstanding(url, rent)) == (0, 0)
    draft = record_reversal(case, reversal_command(case, earlier))
    source = draft_source(url, draft)
    assert sorted(item["part_usd_cents"] for item in source["swept"]) == sorted([1_000, part - 100])
    [reapply] = source["reapply"]
    assert (reapply["target_id"], reapply["amount_usd_cents"]) == (str(trash), 100)
    result = confirm_reversal(case, draft)
    [restored] = result["reapplied"]
    assert one(url, APPLICATION, restored["id"]) == (
        LABEL,
        None,
        None,
        case["settlement"],
        "financial.approve",
        LABEL,
        trash,
        100,
        reapply["application_id"],
    )
    assert (
        available(url, credit),
        outstanding(url, rent),
        outstanding(url, trash),
    ) == (0, 1_000, trash_owed - 100)
    assert outstanding(url, rent) + outstanding(url, trash) - (trash_owed - part) == 900 + part
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, tenant)


def test_a_later_refund_correction_keeps_the_label_on_the_re_posted_rest(
    migrated_database_url: str,
) -> None:
    """A later REFUND correction of the Rent line removes its unpaid rest and releases 100 more,
    which the newest payment, the put-back, gives back (the REFUND correction's re-post, as
    migration 67): the put-back's re-posted rest of 200 keeps the label; the released 100 is
    refunded to the Customer."""
    url = migrated_database_url
    case = put_back_case(url)
    rent, restored = case["rent"], case["restored"]
    unpaid = outstanding(url, rent)
    result = confirm_refund(
        case, record_refund(case, refund_correction(case, case["initial"], rent, unpaid + 100))
    )
    [paid] = result["refunds"]
    assert (paid["amount_usd_cents"], paid["recipient_customer_id"]) == (
        100,
        str(case["customer"]),
    )
    [(rest,)] = rows(
        url,
        "SELECT replacement_credit_application_id FROM app.invoice_credit_excess_releases "
        "WHERE reversed_credit_application_id=%s",
        restored,
    )
    assert one(url, APPLICATION, rest)[:6] == (
        LABEL,
        None,
        None,
        None,
        "credits.apply",
        LABEL,
    )
    assert one(url, APPLICATION, rest)[7] == 200
    assert outstanding(url, rent) == 0
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_only_a_correction_s_put_back_takes_the_label(migrated_database_url: str) -> None:
    """The label on an ordinary Credit application (no Final Settlement) is refused before any
    other check. A closed Settlement's own row with no correction link is refused by the
    Settlement check, which runs first (review round 1). Staff who send the label on a detail of
    an ordinary Rent-first proposal are refused by the proposal recompute (P5104) and nothing is
    written (security review round 1; review round 2: the cause pinned)."""
    url = migrated_database_url
    case = put_back_case(url)
    insert = (
        "INSERT INTO app.customer_credit_applications(id,customer_credit_id,target_kind,invoice_id,"
        "final_settlement_id,amount_usd_cents,within_invoice_basis,occurred_at,actor_id,"
        "authorization_reference) VALUES (%s,%s,'INVOICE',%s,%s,100,%s,clock_timestamp(),%s,%s)"
    )
    with pytest.raises(psycopg.Error) as ordinary, psycopg.connect(url) as connection:
        connection.execute(
            insert,
            (
                uuid4(),
                case["refund_credit"],
                case["initial"],
                None,
                LABEL,
                case["human"],
                "credits.apply",
            ),
        )
    assert (ordinary.value.sqlstate, ordinary.value.diag.message_primary) == (
        "23514",
        ONLY_PUT_BACK,
    )
    with pytest.raises(psycopg.Error) as settlement_row_refused, psycopg.connect(url) as connection:
        connection.execute(
            insert,
            (
                uuid4(),
                case["refund_credit"],
                case["initial"],
                case["settlement"],
                LABEL,
                case["person"],
                "financial.approve",
            ),
        )
    assert (
        settlement_row_refused.value.sqlstate,
        settlement_row_refused.value.diag.message_primary,
    ) == ("55000", "A closed Final Settlement takes no new Credit application")
    human, prop, credit, invoice, _, _ = credit_source(url)
    staff = credit_actor(human, prop, "credits.apply")
    proposal = credits().application_proposal(prop, credit, invoice, 100, actor=staff)
    details = proposal["details"]
    assert isinstance(details, list)
    details[0]["attribution_basis"] = LABEL
    with pytest.raises(CreditConflictError, match="Credit proposal changed"):
        credits().apply(
            prop,
            credit,
            ApplyCreditCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
            actor=staff,
        )
    assert one(
        url,
        "SELECT count(*) FROM app.customer_credit_applications WHERE customer_credit_id=%s",
        credit,
    ) == (0,)


def test_the_header_and_its_detail_agree_on_the_label(migrated_database_url: str) -> None:
    """Review round 2 (security set-up): the agreement check refuses a header with the label whose
    detail has another label, and accepts both with the label. Every writer writes both together,
    so the table owner disables the label trigger in a transaction that is always rolled back, to
    reach the deferred check with a header the trigger would refuse."""
    url = migrated_database_url
    human, _, credit, invoice, line, _ = credit_source(url)
    category = one(url, "SELECT category FROM app.invoice_lines WHERE id=%s", line)[0]
    header = (
        "INSERT INTO app.customer_credit_applications(id,customer_credit_id,target_kind,invoice_id,"
        "amount_usd_cents,within_invoice_basis,occurred_at,actor_id,authorization_reference) "
        "VALUES (%s,%s,'INVOICE',%s,100,%s,clock_timestamp(),%s,'credits.apply')"
    )
    detail = (
        "INSERT INTO app.customer_credit_application_details(id,customer_credit_application_id,"
        "invoice_line_id,obligation_kind,invoice_line_category_snapshot,applied_amount_usd_cents,"
        "attribution_basis,detail_sequence,calculation_trace) "
        "VALUES (%s,%s,%s,'INVOICE_LINE',%s,100,%s,1,'{}'::jsonb)"
    )

    def attempt(detail_basis: str) -> psycopg.Error | None:
        application = uuid4()
        with psycopg.connect(url) as connection:
            try:
                connection.execute(
                    "ALTER TABLE app.customer_credit_applications "
                    "DISABLE TRIGGER customer_credit_applications_put_back"
                )
                connection.execute(header, (application, credit, invoice, LABEL, human))
                connection.execute(detail, (uuid4(), application, line, category, detail_basis))
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
            except psycopg.Error as error:
                return error
            finally:
                connection.rollback()
        return None

    assert attempt(LABEL) is None
    refused = attempt("OTHER_CONFIRMED")
    assert refused is not None
    assert (refused.sqlstate, refused.diag.message_primary) == (
        "23514",
        "Credit attribution and financial position must reconcile",
    )
    # The rollbacks kept the label trigger enabled and wrote nothing.
    assert one(
        url,
        "SELECT tgenabled FROM pg_catalog.pg_trigger "
        "WHERE tgname='customer_credit_applications_put_back'",
    ) == ("O",)
    assert one(
        url,
        "SELECT count(*) FROM app.customer_credit_applications WHERE customer_credit_id=%s",
        credit,
    ) == (0,)


def test_the_put_back_rule_fails_closed(migrated_database_url: str) -> None:
    """The deferred put-back rule on the real put-back's rows: it holds as written; other
    put-backs naming the same payment count towards its amount; it fails for a trace naming
    another payment than its step's part or none, another Credit, another line, more than the
    reversed amount, another label, another step, and for a correction that is not a return
    reversal."""
    url = migrated_database_url
    case = put_back_case(url)
    correction = correction_of(case["result"])
    application, detail = one(
        url,
        "SELECT to_jsonb(application),to_jsonb(detail) FROM app.customer_credit_applications "
        "application JOIN app.customer_credit_application_details detail "
        "ON detail.customer_credit_application_id=application.id WHERE application.id=%s",
        case["restored"],
    )
    sequence = int(detail["calculation_trace"]["step_sequence"])
    other_line = one(
        url, "SELECT id FROM app.invoice_lines WHERE id<>%s ORDER BY id LIMIT 1", case["rent"]
    )[0]
    check = (
        "SELECT app.settlement_correction_put_back_allowed(%s,"
        "jsonb_populate_record(NULL::app.customer_credit_applications,%s),"
        "jsonb_populate_record(NULL::app.customer_credit_application_details,%s),%s)"
    )

    def allowed(
        app_row: dict[str, Any],
        detail_row: dict[str, Any],
        step: int = sequence,
        of: object = correction,
    ) -> bool:
        return bool(one(url, check, of, Jsonb(app_row), Jsonb(detail_row), step)[0])

    def traced(**changes: Any) -> dict[str, Any]:
        trace = {**detail["calculation_trace"], **changes}
        return {**detail, "calculation_trace": {k: v for k, v in trace.items() if v is not None}}

    assert allowed(application, detail)
    # Review round 1: other put-backs naming the same payment count towards its amount. The
    # stored put-back (300) and another of 901 are more than the reversed 1,200, another of 900
    # is not, and the stored row itself at 901 is not either.
    assert allowed(application, {**detail, "applied_amount_usd_cents": 901})
    assert not allowed(application, {**detail, "id": str(uuid4()), "applied_amount_usd_cents": 901})
    assert allowed(application, {**detail, "id": str(uuid4()), "applied_amount_usd_cents": 900})
    failing = [
        # A trace naming another payment than its step's part applied again.
        (application, traced(restores_credit_application_id=str(uuid4()))),
        (
            application,
            {
                **detail,
                "calculation_trace": {
                    k: v
                    for k, v in detail["calculation_trace"].items()
                    if k != "restores_credit_application_id"
                },
            },
        ),
        ({**application, "customer_credit_id": str(uuid4())}, detail),
        (application, {**detail, "applied_amount_usd_cents": 1_201}),
        ({**application, "within_invoice_basis": "RENT_THEN_RECURRING_SERVICES_PROPOSAL"}, detail),
        (application, {**detail, "invoice_line_id": str(other_line)}),
    ]
    for app_row, detail_row in failing:
        assert not allowed(app_row, detail_row), (app_row, detail_row)
    assert not allowed(application, detail, step=sequence + 1)
    # Review round 2 (security note): a step before the first never reads the source from its end.
    assert not allowed(application, detail, step=0)
    # A correction that is not a return reversal: its Credit applications name no restored payment.
    other_correction = one(
        url,
        "SELECT correction.id FROM app.settlement_corrections correction "
        "JOIN app.financial_drafts draft ON draft.id=correction.correlation_id "
        "WHERE correction.final_settlement_id=%s "
        "AND draft.payload->>'variant'<>'RETURN_REVERSAL' ORDER BY correction.occurred_at LIMIT 1",
        case["settlement"],
    )[0]
    assert not allowed(application, detail, of=other_correction)
    plain = {**application, "within_invoice_basis": "OTHER_APPLICABLE_OBLIGATION"}
    assert allowed(plain, traced(restores_credit_application_id=None), of=other_correction)


def test_the_put_back_rule_is_least_privilege_and_forward_only(migrated_database_url: str) -> None:
    """No role calls the two new functions, each SECURITY DEFINER with the fixed search path;
    migration 133 adds only them and the label trigger, relaxes only the two label CHECKs, changes
    only the five listed functions (each patched body is exactly the old one with the module's
    replacements), and is forward-only."""
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
    assert revision is not None and revision.down_revision == "20261206_132"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database("settlement_return_reversal_put_back") as temporary:
        alembic_command.upgrade(config, "20261206_132")
        before_functions, before_constraints, before_triggers = app_catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = app_catalog(temporary)
    assert after_triggers - before_triggers == {
        "app.customer_credit_applications:customer_credit_applications_put_back"
    }
    assert before_triggers <= after_triggers
    changed = {item.split(":")[1] for item in before_constraints ^ after_constraints}
    assert changed == {
        "customer_credit_applications_within_invoice_basis_check",
        "customer_credit_application_details_attribution_basis_check",
    }
    assert all(LABEL in item for item in after_constraints - before_constraints)
    assert set(after_functions) - set(before_functions) == INTERNAL
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
