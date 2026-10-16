"""An Adjustment reversal puts the Credit back on its own line (V1-056 sub-slice 10f-1b).

Owner answer (a) to Q-2026-10-16-118 point 1: an ADJUSTMENT_REVERSAL always puts the Credit back
on the Adjustment's own line, with the label put back by a correction (PUT_BACK_BY_CORRECTION),
even when an earlier line still owes; a put-back restores what was there before and is not a new
allocation; never more than the release or the line's unpaid rest. The label is allowed only on a
put-back that a confirmed ADJUSTMENT_REVERSAL decision of the same transaction lists, and a
deferred check holds it to the Adjustment's line, the release's Credit and the released amount.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from payment_test_support import seed_payment
from property_rental.billing import PostgresRentBillingService
from property_rental.credit import ReverseCreditApplicationCommand
from test_adjustment_reversal_migration import (
    adjustments,
    approver,
    available,
    draft_id,
    preparer,
    put_back_rows,
    reconciled,
    request,
    reversals,
    source_of,
)
from test_billing_service_migration import authenticated, initial_command, setup_billing_source
from test_credit_adjustment_excess_migration import credit as adjust_credit
from test_credit_adjustment_excess_migration import pay
from test_credit_application_migration import designated as credit_designated
from test_credit_application_migration import source as credit_source
from test_credit_migration import actor as credit_actor
from test_credit_migration import service as credits
from test_debit_adjustment_line_block_migration import first_line, outstanding
from test_invoice_migration import create_recurring_rent_invoice, financial_database_url
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_migrations import _temporary_migration_database
from test_payment_allocation_migration import source as allocation_source
from test_payment_move_migration import rows, value

REVISION = "20261220_146"
LABEL = "PUT_BACK_BY_CORRECTION"
ALLOWED = (
    "app.adjustment_reversal_put_back_allowed("
    "app.customer_credit_applications,app.customer_credit_application_details)"
)
VALIDATE = "app.validate_adjustment_reversal_put_back()"
PATCHED = {
    "app.adjustment_reversal_source(uuid,uuid)",
    "app.confirm_adjustment_reversal(uuid,uuid,uuid,text)",
    "app.validate_credit_application_put_back()",
}


def rent_and_service_invoice(url: str) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID]:
    """An issued Initial Invoice with a Rent line and a Service Charges line, and a received
    Payment of the Customer that covers both."""
    with psycopg.connect(url) as connection:
        human, prop, customer, lease, _ = setup_billing_source(connection)
    invoice = (
        PostgresRentBillingService(financial_database_url(), prop, human)
        .generate(initial_command(lease, uuid4()), actor=authenticated(human, prop))
        .invoice_id
    )
    lines = rows(
        url,
        "SELECT category,id FROM app.invoice_lines WHERE invoice_id=%s "
        "AND category IN ('RENT','SERVICE_CHARGES') ORDER BY line_sequence",
        invoice,
    )
    rent = UUID(str(next(found for kind, found in lines if kind == "RENT")))
    service = UUID(str(next(found for kind, found in lines if kind == "SERVICE_CHARGES")))
    with psycopg.connect(url) as connection:
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=customer,
            amount=outstanding(url, rent) + outstanding(url, service),
        )
    return human, prop, invoice, rent, service, payment


def application_columns(url: str, application: UUID) -> tuple[Any, ...]:
    [found] = rows(
        url,
        "SELECT a.proposal_generated_at,a.proposal_trace,a.customer_designation_reference,"
        "d.proposed_amount_usd_cents FROM app.customer_credit_applications a "
        "JOIN app.customer_credit_application_details d "
        "ON d.customer_credit_application_id=a.id WHERE a.id=%s",
        application,
    )
    return found


MESSAGE = (
    "An Adjustment reversal put-back goes back only on its Adjustment's line, within its release"
)
LABEL_REFUSED = "Only a correction's put-back is labelled put back by a correction"


def listed_put_back(
    url: str,
    prop: UUID,
    human: UUID,
    adjustment: UUID,
    result: dict[str, Any],
    put_back: dict[str, Any],
    invoice: UUID,
    target: UUID,
    binding: str,
) -> psycopg.Error | None:
    """As the table owner, in a transaction that is always rolled back: a second confirmed
    ADJUSTMENT_REVERSAL decision naming the stored reversal lists a new labelled put-back of 1
    from the stored put-back's Credit and release, then that put-back is written on the target
    line and the deferred checks run. The decision is of this transaction (THIS_TRANSACTION),
    names the transaction before it (OTHER_TRANSACTION), or is dated before this transaction
    began (BEFORE_THIS_TRANSACTION, written directly into the decisions table)."""
    application, draft = uuid4(), uuid4()
    decision_result = (
        "jsonb_build_object('invoice_adjustment_reversal_id',%s::text,"
        "'invoice_adjustment_id',%s::text,'put_backs',jsonb_build_array("
        "jsonb_build_object('credit_application_id',%s::text,"
        "'customer_credit_id',%s::text,'invoice_credit_excess_release_id',%s::text,"
        "'amount_usd_cents',1)),'debt_usd_cents',0,'transaction_id',"
        + (
            "(pg_current_xact_id()::text::bigint-1)::text)"
            if binding == "OTHER_TRANSACTION"
            else "pg_current_xact_id()::text)"
        )
    )
    values = (
        str(result["invoice_adjustment_reversal_id"]),
        adjustment,
        application,
        str(put_back["customer_credit_id"]),
        str(put_back["invoice_credit_excess_release_id"]),
    )
    with psycopg.connect(url) as connection:
        try:
            connection.execute(
                "SELECT app.insert_financial_draft(%s,%s,%s,'ADJUSTMENT_REVERSAL',"
                "'invoices.adjust',jsonb_build_object('invoice_adjustment_id',%s::text),"
                "'adjustment-reversal:test','A second reversal written by hand')",
                (prop, human, draft, adjustment),
            )
            if binding == "BEFORE_THIS_TRANSACTION":
                connection.execute(
                    "INSERT INTO app.financial_draft_decisions(draft_id,decision,reason,"
                    "decided_at,decided_by,authorization_reference,result) VALUES "
                    "(%s,'CONFIRMED',NULL,transaction_timestamp()-interval '1 second',%s,"
                    f"'financial.approve',{decision_result})",
                    (draft, human, *values),
                )
            else:
                connection.execute(
                    "SELECT app.confirm_financial_draft_record(%s,%s,%s,'ADJUSTMENT_REVERSAL',"
                    f"{decision_result},'financial.approve')",
                    (prop, human, draft, *values),
                )
            connection.execute(
                "INSERT INTO app.customer_credit_applications(id,customer_credit_id,"
                "target_kind,invoice_id,amount_usd_cents,within_invoice_basis,occurred_at,"
                "actor_id,authorization_reference) VALUES (%s,%s,'INVOICE',%s,1,%s,"
                "clock_timestamp(),%s,'credits.apply')",
                (application, str(put_back["customer_credit_id"]), invoice, LABEL, human),
            )
            connection.execute(
                "INSERT INTO app.customer_credit_application_details(id,"
                "customer_credit_application_id,invoice_line_id,obligation_kind,"
                "invoice_line_category_snapshot,applied_amount_usd_cents,attribution_basis,"
                "detail_sequence,calculation_trace) SELECT %s,%s,line.id,'INVOICE_LINE',"
                "line.category,1,%s,1,jsonb_build_object('invoice_adjustment_reversal_id',"
                "%s::text,'invoice_credit_excess_release_id',%s::text) "
                "FROM app.invoice_lines line WHERE line.id=%s",
                (uuid4(), application, LABEL, values[0], values[4], target),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        except psycopg.Error as error:
            return error
        finally:
            connection.rollback()
    return None


def test_two_releases_go_back_on_the_adjustment_s_line_while_the_rent_line_owes(
    migrated_database_url: str,
) -> None:
    """The Service line is paid by two Payment allocations while the Rent line owes; a credit
    Adjustment of the whole Service line releases both as two new Credits. The reversal puts each
    back on the Service line with the label (no proposal, no designation, no proposed amount), in
    the release order; the Service line owes nothing again, the Rent line still owes all of its
    amount, both Credits hold nothing, and the ledger reconciles."""
    url = migrated_database_url
    human, prop, invoice, rent, service, payment = rent_and_service_invoice(url)
    rent_due, service_due = outstanding(url, rent), outstanding(url, service)
    first = service_due // 2
    pay(prop, payment, invoice, service, first, human)
    pay(prop, payment, invoice, service, service_due - first, human)
    effect = cast(
        dict[str, Any],
        adjust_credit(url, human, prop, invoice, service, service_due)["adjustment_effect"],
    )
    released_credits = [UUID(str(item)) for item in cast(list[str], effect["customer_credit_ids"])]
    assert len(released_credits) == 2 and effect["customer_credit_usd_cents"] == service_due
    [adjustment] = adjustments(url, service)
    assert outstanding(url, service) == 0 and outstanding(url, rent) == rent_due
    recorded = reversals().record(prop, request(adjustment), actor=preparer(human, prop))
    source = source_of(recorded)
    releases = cast(list[dict[str, Any]], source["releases"])
    assert sorted(item["released_usd_cents"] for item in releases) == sorted(
        [first, service_due - first]
    )
    assert [item["put_back_usd_cents"] for item in releases] == [
        item["released_usd_cents"] for item in releases
    ]
    assert (source["put_back_usd_cents"], source["debt_usd_cents"]) == (service_due, 0)
    result = reversals().confirm(prop, draft_id(recorded), actor=approver(human, prop))
    put_backs = cast(list[dict[str, Any]], result["put_backs"])
    assert [item["invoice_credit_excess_release_id"] for item in put_backs] == [
        item["invoice_credit_excess_release_id"] for item in releases
    ]
    for item, release in zip(put_backs, releases, strict=True):
        application = UUID(str(item["credit_application_id"]))
        assert put_back_rows(url, application) == [
            (
                UUID(str(release["customer_credit_id"])),
                release["released_usd_cents"],
                LABEL,
                "credits.apply",
                service,
                LABEL,
                "Invoice Adjustment reversal put-back",
            )
        ]
        assert application_columns(url, application) == (None, None, None, None)
    assert outstanding(url, service) == 0 and outstanding(url, rent) == rent_due
    assert [available(url, credit) for credit in released_credits] == [0, 0]
    reconciled(url, invoice)


def test_the_label_is_refused_on_a_row_no_adjustment_reversal_of_this_transaction_lists(
    migrated_database_url: str,
) -> None:
    """A Credit application with the label and no Final Settlement that no confirmed
    ADJUSTMENT_REVERSAL decision of this transaction lists is refused at insert (23514), so an
    ordinary Credit application never carries the label; nothing is written."""
    url = migrated_database_url
    human, prop, payment, invoice_ids = allocation_source(url)
    invoice = invoice_ids[0]
    line = first_line(url, invoice)
    pay(prop, payment, invoice, line, 20_000, human)
    effect = cast(
        dict[str, Any], adjust_credit(url, human, prop, invoice, line, 70_000)["adjustment_effect"]
    )
    [credit] = [UUID(str(item)) for item in cast(list[str], effect["customer_credit_ids"])]
    application = uuid4()
    with psycopg.connect(url) as connection:
        with pytest.raises(psycopg.Error) as refused:
            connection.execute(
                "INSERT INTO app.customer_credit_applications(id,customer_credit_id,target_kind,"
                "invoice_id,late_payment_charge_id,final_settlement_id,amount_usd_cents,"
                "within_invoice_basis,customer_designation_reference,proposal_generated_at,"
                "proposal_trace,occurred_at,actor_id,authorization_reference) "
                "VALUES (%s,%s,'INVOICE',%s,NULL,NULL,1000,%s,NULL,NULL,NULL,clock_timestamp(),"
                "%s,'credits.apply')",
                (application, credit, invoice, LABEL, human),
            )
        connection.rollback()
    assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
        "23514",
        LABEL_REFUSED,
    )
    assert (
        value(url, "SELECT count(*) FROM app.customer_credit_applications WHERE id=%s", application)
        == 0
    )
    assert available(url, credit) == 10_000


def test_the_put_back_check_holds_the_line_the_release_the_credit_and_the_amount(
    migrated_database_url: str,
) -> None:
    """The Service line is paid by two Payment allocations, so a credit Adjustment of the whole
    line releases two new Credits of the same Customer. After a real confirm in a rolled-back
    owner transaction, the deferred check's function accepts the first stored put-back and
    refuses the same row moved to another line, with another detail amount, as a second
    put-back of the whole release, naming another reversal, with another header amount, with the
    Customer's other Credit (review round 1), on another issued Invoice of the same Customer
    (review round 1) or with another label; another transaction's view of the same row is
    refused too. The rollback leaves the draft pending, and the service then confirms it."""
    url = migrated_database_url
    human, prop, invoice, rent, service, payment = rent_and_service_invoice(url)
    service_due = outstanding(url, service)
    first = service_due // 2
    pay(prop, payment, invoice, service, first, human)
    pay(prop, payment, invoice, service, service_due - first, human)
    pay(prop, payment, invoice, rent, outstanding(url, rent), human)
    effect = cast(
        dict[str, Any],
        adjust_credit(url, human, prop, invoice, service, service_due)["adjustment_effect"],
    )
    released_credits = [UUID(str(item)) for item in cast(list[str], effect["customer_credit_ids"])]
    assert len(released_credits) == 2
    [adjustment] = adjustments(url, service)
    [(customer, lease)] = rows(
        url, "SELECT customer_id,lease_id FROM app.invoices WHERE id=%s", invoice
    )
    with psycopg.connect(url) as connection:
        other_invoice, _ = create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=customer,
            lease_id=lease,
            period_start=date(2027, 3, 1),
        )
    recorded = reversals().record(prop, request(adjustment), actor=preparer(human, prop))
    draft = draft_id(recorded)
    allowed = (
        f"SELECT {ALLOWED.split('(')[0]}(a,jsonb_populate_record(d,%s::jsonb)) "
        "FROM app.customer_credit_applications a JOIN app.customer_credit_application_details d "
        "ON d.customer_credit_application_id=a.id WHERE a.id=%s"
    )
    moved_header = (
        f"SELECT {ALLOWED.split('(')[0]}(jsonb_populate_record(a,%s::jsonb),d) "
        "FROM app.customer_credit_applications a JOIN app.customer_credit_application_details d "
        "ON d.customer_credit_application_id=a.id WHERE a.id=%s"
    )
    with psycopg.connect(url) as connection:
        result = connection.execute(
            "SELECT app.confirm_adjustment_reversal(%s,%s,%s,'financial.approve')",
            (prop, human, draft),
        ).fetchone()
        assert result is not None
        put_back, second = cast(list[dict[str, Any]], cast(dict[str, Any], result[0])["put_backs"])
        application = UUID(str(put_back["credit_application_id"]))
        amount = int(put_back["amount_usd_cents"])
        other_credit = str(second["customer_credit_id"])
        assert other_credit != str(put_back["customer_credit_id"]) and amount > 1

        def check(sql: str, changes: str) -> object:
            found = connection.execute(sql, (changes, application)).fetchone()
            assert found is not None
            return found[0]

        assert check(allowed, "{}") is True
        assert check(allowed, f'{{"invoice_line_id": "{rent}"}}') is False
        assert check(allowed, f'{{"applied_amount_usd_cents": {amount - 1}}}') is False
        assert check(allowed, f'{{"id": "{uuid4()}"}}') is False
        assert (
            check(
                allowed,
                '{"calculation_trace": {"reason": "Invoice Adjustment reversal put-back", '
                f'"invoice_adjustment_reversal_id": "{uuid4()}", '
                f'"invoice_credit_excess_release_id": '
                f'"{put_back["invoice_credit_excess_release_id"]}"}}}}',
            )
            is False
        )
        assert check(moved_header, f'{{"amount_usd_cents": {amount - 1}}}') is False
        assert check(moved_header, f'{{"customer_credit_id": "{other_credit}"}}') is False
        assert check(moved_header, f'{{"invoice_id": "{other_invoice}"}}') is False
        assert check(moved_header, '{"within_invoice_basis": "CUSTOMER_DESIGNATED"}') is False
        connection.rollback()
    assert (
        value(url, "SELECT count(*) FROM app.customer_credit_applications WHERE id=%s", application)
        == 0
    )
    assert (
        value(url, "SELECT count(*) FROM app.financial_draft_decisions WHERE draft_id=%s", draft)
        == 0
    )
    confirmed = reversals().confirm(prop, draft, actor=approver(human, prop))
    stored = cast(list[dict[str, Any]], confirmed["put_backs"])[0]
    # Another transaction has no confirmed decision of its own: the stored row is refused there.
    with psycopg.connect(url) as connection:
        stored_id = UUID(str(stored["credit_application_id"]))
        assert connection.execute(allowed, ("{}", stored_id)).fetchone() == (False,)
    assert outstanding(url, service) == 0
    assert [available(url, credit) for credit in released_credits] == [0, 0]
    reconciled(url, invoice)


def test_the_deferred_check_refuses_a_listed_put_back_beyond_its_release(
    migrated_database_url: str,
) -> None:
    """The deferred trigger itself: the Customer's Credit of 100,000 paid 60,000 of an 80,000
    Rent line; a credit Adjustment of 40,000 released 20,000 of that application back to the
    Credit, and a real reversal put the 20,000 back on the line (the line owes 20,000, the Credit
    holds 40,000). The table owner then writes, in a transaction that is always rolled back, a
    second confirmed ADJUSTMENT_REVERSAL decision naming that reversal and listing a new labelled
    put-back of 1 from the same Credit and release. The insert checks let it in (the decision lists
    it; the Credit and the line still have value); the deferred check refuses it because the
    release is already all put back (23514), and nothing is written. The insert trigger refuses
    the same put-back when the decision names the transaction before this one or is dated before
    this transaction began (review round 1, security S2). The Invoice has one line; the other-line
    case is the next test."""
    url = migrated_database_url
    human, prop, credit_value, invoice, line, _ = credit_source(url)
    staff = credit_actor(human, prop, "credits.apply")
    credits().apply(prop, credit_value, credit_designated(invoice, line, 60_000), actor=staff)
    adjust_credit(url, human, prop, invoice, line, 40_000)
    assert available(url, credit_value) == 60_000
    [adjustment] = adjustments(url, line)
    recorded = reversals().record(prop, request(adjustment), actor=preparer(human, prop))
    result = reversals().confirm(prop, draft_id(recorded), actor=approver(human, prop))
    [put_back] = cast(list[dict[str, Any]], result["put_backs"])
    credit = str(put_back["customer_credit_id"])

    def attempt(target: UUID, binding: str = "THIS_TRANSACTION") -> psycopg.Error | None:
        return listed_put_back(
            url, prop, human, adjustment, result, put_back, invoice, target, binding
        )

    assert put_back["amount_usd_cents"] == 20_000 and outstanding(url, line) == 20_000
    refused = attempt(line)
    assert refused is not None
    assert (refused.sqlstate, refused.diag.message_primary) == ("23514", MESSAGE)
    # Review round 1 (security S2): the insert trigger takes only a decision of this
    # transaction, by its transaction id and by its time.
    for binding in ("OTHER_TRANSACTION", "BEFORE_THIS_TRANSACTION"):
        refused = attempt(line, binding)
        assert refused is not None, binding
        assert (refused.sqlstate, refused.diag.message_primary) == (
            "23514",
            LABEL_REFUSED,
        ), binding
    assert (
        value(
            url,
            "SELECT count(*) FROM app.financial_drafts WHERE kind='ADJUSTMENT_REVERSAL' "
            "AND payload->>'invoice_adjustment_id'=%s",
            str(adjustment),
        )
        == 1
    )
    assert credit == str(credit_value)
    assert outstanding(url, line) == 20_000 and available(url, credit_value) == 40_000


def test_the_deferred_check_takes_a_listed_put_back_only_on_the_adjustment_s_line(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent set-up): a Payment paid the whole Service line; a credit
    Adjustment of the line released it as a new Credit, and half of that Credit then paid the
    Rent line. The reversal puts back the rest of the Credit on the Service line, which owes that
    half. After the Rent-line application is reversed, the Credit holds the half and the release
    has room. A hand-written listed put-back of 1 (rolled back) passes the deferred check on the
    Service line and is refused on the Rent line (23514); nothing is written."""
    url = migrated_database_url
    human, prop, invoice, rent, service, payment = rent_and_service_invoice(url)
    rent_due, service_due = outstanding(url, rent), outstanding(url, service)
    part = service_due // 2
    assert part >= 1 and rent_due > part
    pay(prop, payment, invoice, service, service_due, human)
    effect = cast(
        dict[str, Any],
        adjust_credit(url, human, prop, invoice, service, service_due)["adjustment_effect"],
    )
    [credit] = [UUID(str(item)) for item in cast(list[str], effect["customer_credit_ids"])]
    staff = credit_actor(human, prop, "credits.apply")
    credits().apply(prop, credit, credit_designated(invoice, rent, part), actor=staff)
    [adjustment] = adjustments(url, service)
    recorded = reversals().record(prop, request(adjustment), actor=preparer(human, prop))
    result = reversals().confirm(prop, draft_id(recorded), actor=approver(human, prop))
    [put_back] = cast(list[dict[str, Any]], result["put_backs"])
    assert put_back["amount_usd_cents"] == service_due - part
    assert outstanding(url, service) == part
    [(rent_application,)] = rows(
        url,
        "SELECT id FROM app.customer_credit_applications WHERE customer_credit_id=%s "
        "AND within_invoice_basis='CUSTOMER_DESIGNATED'",
        credit,
    )
    credits().reverse_application(
        prop,
        UUID(str(rent_application)),
        ReverseCreditApplicationCommand(uuid4(), "Applied to the wrong line"),
        actor=credit_actor(human, prop, "credits.applications.reverse"),
    )
    assert available(url, credit) == part and outstanding(url, rent) == rent_due
    assert (
        listed_put_back(
            url, prop, human, adjustment, result, put_back, invoice, service, "THIS_TRANSACTION"
        )
        is None
    )
    refused = listed_put_back(
        url, prop, human, adjustment, result, put_back, invoice, rent, "THIS_TRANSACTION"
    )
    assert refused is not None
    assert (refused.sqlstate, refused.diag.message_primary) == ("23514", MESSAGE)
    assert outstanding(url, service) == part and available(url, credit) == part
    reconciled(url, invoice)


def test_a_later_adjustment_re_posts_a_labelled_put_back_with_the_label(
    migrated_database_url: str,
) -> None:
    """A credit Adjustment of 70,000 on an 80,000 line that a Payment paid 20,000 of released
    10,000 as Credit (the allocation's rest is 10,000), and its reversal put the 10,000 back on
    the line with the label. A later credit Adjustment of 65,000 on the same line leaves 15,000 to
    pay, so 5,000 of the 20,000 paid is released: the labelled put-back (the newest payment) is
    reversed whole and its 5,000 rest is posted again with the label; the line owes nothing and
    the Credit holds 5,000."""
    url = migrated_database_url
    human, prop, payment, invoice_ids = allocation_source(url)
    invoice = invoice_ids[0]
    line = first_line(url, invoice)
    pay(prop, payment, invoice, line, 20_000, human)
    effect = cast(
        dict[str, Any], adjust_credit(url, human, prop, invoice, line, 70_000)["adjustment_effect"]
    )
    [credit] = [UUID(str(item)) for item in cast(list[str], effect["customer_credit_ids"])]
    [adjustment] = adjustments(url, line)
    recorded = reversals().record(prop, request(adjustment), actor=preparer(human, prop))
    result = reversals().confirm(prop, draft_id(recorded), actor=approver(human, prop))
    [put_back] = cast(list[dict[str, Any]], result["put_backs"])
    put_back_id = UUID(str(put_back["credit_application_id"]))
    assert outstanding(url, line) == 60_000 and available(url, credit) == 0
    adjust_credit(url, human, prop, invoice, line, 65_000)
    [(reversed_id, replacement, released)] = rows(
        url,
        "SELECT release.reversed_credit_application_id,release.replacement_credit_application_id,"
        "release.released_usd_cents FROM app.invoice_credit_excess_releases release "
        "JOIN app.invoice_adjustments adjustment ON adjustment.id=release.invoice_adjustment_id "
        "WHERE adjustment.invoice_line_id=%s AND adjustment.id<>%s",
        line,
        adjustment,
    )
    assert (reversed_id, released) == (put_back_id, 5_000)
    [(_, amount, header_basis, _, on_line, basis, _)] = put_back_rows(url, UUID(str(replacement)))
    assert (amount, header_basis, on_line, basis) == (5_000, LABEL, line, LABEL)
    assert outstanding(url, line) == 0 and available(url, credit) == 5_000
    reconciled(url, invoice)


def test_adjustment_reversal_put_back_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """No role calls the two new functions; the migration adds them and one deferred trigger,
    patches only the three named functions without changing their privileges or settings, and
    is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (ALLOWED, VALIDATE):
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (function, role)
            definer = connection.execute(
                "SELECT p.prosecdef,p.proconfig[1] FROM pg_catalog.pg_proc p "
                "WHERE p.oid=CAST(%s AS regprocedure)",
                (function,),
            ).fetchone()
            assert definer == (True, "search_path=pg_catalog"), function
        trigger = connection.execute(
            "SELECT t.tgdeferrable,t.tginitdeferred FROM pg_catalog.pg_trigger t "
            "WHERE t.tgrelid='app.customer_credit_applications'::regclass "
            "AND t.tgname='customer_credit_applications_adjustment_put_back'"
        ).fetchone()
        assert trigger == (True, True)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261219_145"
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

    with _temporary_migration_database("adjustment_reversal_put_back") as temporary:
        alembic_command.upgrade(config, "20261219_145")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert after_relations == before_relations
    assert after_triggers - before_triggers == {
        "app.customer_credit_applications:customer_credit_applications_adjustment_put_back"
    }
    assert before_triggers <= after_triggers
    assert set(after_functions) - set(before_functions) == {ALLOWED, VALIDATE}
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED
    # Each patched function changed only its definition, never its privileges or settings.
    for name in PATCHED:
        assert after_functions[name][1:] == before_functions[name][1:], name
