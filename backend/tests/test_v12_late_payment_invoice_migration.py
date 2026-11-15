"""Real PostgreSQL coverage of the Late-payment Invoice (clean-up step L1, DL-233, migration
20270730_396; BR-LATE-001, BR-INV-016).

The automatic pass no longer writes a late-payment charge of its own kind. It writes the same
decision as before and, in the same step, makes and issues an Invoice of the type Late-payment
for the Customer and the Lease of the late Invoice. That Invoice is owed on the day it is made,
never gets a late-payment charge itself, and is paid, lowered and settled like every Invoice.
A charge made before this step stays as it was made.

The helpers and the pass history rule are those of
``test_automatic_late_payment_charge_migration.py``.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.invoice import AdjustInvoiceCommand, AdjustmentType, InvoiceInvalidError
from property_rental.receive_payment import ReceivePaymentCommand, read_payable
from test_automatic_late_payment_charge_migration import (
    candidates,
    charge_of,
    decision_of,
    moment,
    months_ago,
    overdue,
    record,
    seed_last_run,
)
from test_automatic_late_payment_charge_migration import no_pass_yet as no_pass_yet
from test_credit_adjustment_excess_migration import credit, invoices, version
from test_final_settlement_migration import one, today
from test_invoice_migration import (
    financial_database_url,
    invoice_api_actor,
    runtime_database_url,
)
from test_late_charge_card_migration import card
from test_late_payment_migration import migrated_database_url as migrated_database_url
from test_receive_payment_migration import cashier, receive, usd
from test_receive_payment_migration import invoice as pays
from test_report_month_facts_migration import facts

REVISION = "20270730_396"
LATE_INVOICE = (
    "SELECT late.id,late.invoice_type,late.primary_category,late.status,"
    "late.original_total_usd_cents,late.customer_id,late.lease_id,late.invoice_date,"
    "late.due_date,late.due_date_rule,late.created_by,late.issued_by "
    "FROM app.invoices late JOIN app.late_payment_decisions decision "
    "ON decision.id=late.late_payment_decision_id WHERE decision.source_invoice_id=%s"
)


def charged(url: str, months: int = 1) -> dict[str, Any]:
    """An unpaid Rent Invoice of 800.00 that the pass has just charged: the case of
    ``overdue`` with the Late-payment Invoice of 80.00 in ``late``."""
    case = overdue(url, months_ago(url, months))
    seed_last_run(url, case["prop"], case["service"], case["due"])
    outcome = record(case)
    assert outcome["outcome"] == "CHARGED"
    case["outcome"] = outcome
    case["late"] = UUID(outcome["invoice"]["id"])
    case["url"] = url
    return case


def refusal(url: str, sql: str, *parameters: object) -> tuple[str | None, str | None]:
    with pytest.raises(psycopg.Error) as failure, psycopg.connect(url) as connection:
        connection.execute(sql, parameters)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    return failure.value.sqlstate, failure.value.diag.message_primary


def test_the_migration_follows_the_missed_amount_step_and_is_forward_only(
    migrated_database_url: str,
) -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == "20270729_395"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_the_pass_makes_a_late_payment_invoice_and_no_charge_of_the_old_kind(
    migrated_database_url: str,
) -> None:
    """Rent 800.00 unpaid at 00:00 on the day after its Due Date: a Late-payment Invoice of
    80.00 for the same Customer and Lease, issued by the service and owed on that day."""
    url = migrated_database_url
    case = charged(url)

    # ``charge_of`` reads the Late-payment Invoice and checks that no old charge was written.
    assert charge_of(url, case["invoice"]) == 8_000
    decision = decision_of(url, case["invoice"])
    assert decision is not None
    assert decision[:6] == (80_000, 1000, 8_000, 8_000, "CONFIRMED_DEFAULT", moment(case["due"]))
    with psycopg.connect(url) as connection:
        late = connection.execute(LATE_INVOICE, (case["invoice"],)).fetchall()
        source = connection.execute(
            "SELECT lease_id,invoice_number FROM app.invoices WHERE id=%s", (case["invoice"],)
        ).fetchone()
        assert source is not None
        lines = connection.execute(
            "SELECT category,description,amount_usd_cents,created_by FROM app.invoice_lines "
            "WHERE invoice_id=%s",
            (case["late"],),
        ).fetchall()
    day = today(url)
    assert late == [
        (
            case["late"],
            "LATE_PAYMENT",
            "MISCELLANEOUS_CHARGES",
            "UNPAID",
            8_000,
            case["customer"],
            source[0],
            day,
            day,
            "GOVERNING_SOURCE",
            case["service"],
            case["service"],
        )
    ]
    assert lines == [
        (
            "MISCELLANEOUS_CHARGES",
            f"Late-payment charge of Invoice {source[1]}",
            8_000,
            case["service"],
        )
    ]
    # The result of the pass shows the new Invoice and names the Invoice that was late.
    shown = case["outcome"]["invoice"]
    assert shown["invoice_type"] == "LATE_PAYMENT"
    assert shown["status"] == "UNPAID"
    assert shown["late_payment_of"] == {
        "invoice_id": str(case["invoice"]),
        "invoice_number": source[1],
    }
    # One for an Invoice, for ever.
    assert record(case) == {"outcome": "ALREADY_ASSESSED"}
    assert case["invoice"] not in candidates(case)


def test_a_late_payment_invoice_never_gets_a_late_payment_charge(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = charged(url)

    # The type is in use, its switch is No and stays No.
    assert one(url, "SELECT late_payment,in_use FROM app.invoice_types WHERE code='LATE_PAYMENT'")[
        :2
    ] == (False, True)
    assert refusal(
        url,
        "SELECT app.set_invoice_type_late_payment(%s,'LATE_PAYMENT',true,'Test',%s,%s)",
        case["prop"],
        case["human"],
        uuid4(),
    ) == ("55000", "A Late-payment Invoice never gets a late-payment charge")
    # The pass does not read it, and a direct call adds nothing.
    assert case["late"] not in candidates(case)
    assert record(case, case["late"]) == {"outcome": "LATE_PAYMENT_OFF"}
    assert decision_of(url, case["late"]) is None


def test_only_the_pass_makes_a_late_payment_invoice_and_its_link_never_changes(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = charged(url)

    # The type without its decision, and the decision without the type, are refused.
    assert refusal(
        url,
        "INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,primary_category,"
        "status,invoice_date,original_total_usd_cents,due_date_rule,due_date_source,"
        "created_by,updated_by,invoice_type) SELECT %s,'INV-L1-' || %s,customer_id,lease_id,"
        "'MISCELLANEOUS_CHARGES','DRAFT',invoice_date,100,'ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS',"
        "'BR-INV-018',%s,%s,'LATE_PAYMENT' FROM app.invoices WHERE id=%s",
        uuid4(),
        str(uuid4())[:8],
        case["human"],
        case["human"],
        case["invoice"],
    ) == ("23514", "The Invoice type does not fit the Invoice category")
    assert refusal(
        url,
        "UPDATE app.invoices SET late_payment_decision_id=NULL,version=version+1 WHERE id=%s",
        case["late"],
    ) == ("55000", "The late-payment link is kept as it was made")
    # No app role may state the type through the typed Draft function.
    with psycopg.connect(financial_database_url()) as financial:
        allowed = financial.execute(
            "SELECT has_function_privilege(current_user,oid,'EXECUTE') FROM pg_proc "
            "WHERE proname='create_items_invoice_draft_of_type'"
        ).fetchall()
    assert allowed == [(False,)]


def test_a_late_payment_invoice_is_paid_and_lowered_like_every_invoice(
    migrated_database_url: str,
) -> None:
    """Oldest first pays the late Invoice, then its Late-payment Invoice (the next Due Date).
    A credit Adjustment lowers it; the rest is paid and the Invoice is Paid."""
    url = migrated_database_url
    case = charged(url, 5)

    def owed() -> list[tuple[object, object, object, object]]:
        found = read_payable(
            runtime_database_url(), case["prop"], case["customer"], actor=cashier(case)
        )
        return [
            (item["kind"], item["id"], item["invoice_type"], item["owed_usd_cents"])
            for item in cast(list[dict[str, object]], found["items"])
        ]

    assert owed() == [
        ("INVOICE", str(case["invoice"]), "RENT", 80_000),
        ("INVOICE", str(case["late"]), "LATE_PAYMENT", 8_000),
    ]
    receive(
        case,
        ReceivePaymentCommand(
            usd(case, 83_000),
            "OLDEST_FIRST",
            (pays(case["invoice"], 80_000), pays(case["late"], 3_000)),
        ),
    )
    assert owed() == [("INVOICE", str(case["late"]), "LATE_PAYMENT", 5_000)]
    assert one(url, "SELECT status FROM app.invoices WHERE id=%s", case["late"]) == (
        "PARTIALLY_PAID",
    )

    line = cast(
        UUID, one(url, "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", case["late"])[0]
    )
    credit(url, case["human"], case["prop"], case["late"], line, 2_000)
    assert owed() == [("INVOICE", str(case["late"]), "LATE_PAYMENT", 3_000)]
    receive(
        case,
        ReceivePaymentCommand(usd(case, 3_000), "OLDEST_FIRST", (pays(case["late"], 3_000),)),
    )
    assert owed() == []
    assert one(url, "SELECT status FROM app.invoices WHERE id=%s", case["late"]) == ("PAID",)
    # The decision and the first amount stay as they were made.
    decision = decision_of(url, case["invoice"])
    assert decision is not None and decision[2:4] == (8_000, 8_000)


def test_a_late_payment_invoice_is_never_raised(migrated_database_url: str) -> None:
    """The charge only goes down (BR-LATE-001): a debit Adjustment is refused, by the command
    and by the check of the Adjustment record itself."""
    url = migrated_database_url
    case = charged(url, 7)
    line = cast(
        UUID, one(url, "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", case["late"])[0]
    )

    with pytest.raises(InvoiceInvalidError):
        invoices().adjust(
            case["prop"],
            case["late"],
            AdjustInvoiceCommand(
                uuid4(),
                line,
                AdjustmentType.DEBIT,
                1_000,
                f"raise/{uuid4()}",
                "Raise the charge",
                version(url, case["late"]),
            ),
            actor=invoice_api_actor(case["human"], case["prop"]),
        )
    assert refusal(
        url,
        "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adjustment_type,"
        "amount_usd_cents,source_reference,reason,occurred_at,actor_id,authorization_reference) "
        "VALUES (%s,%s,%s,'DEBIT',1000,'raise','Raise the charge',clock_timestamp(),%s,"
        "'invoices.adjust')",
        uuid4(),
        case["late"],
        line,
        case["human"],
    ) == ("23514", "A Late-payment Invoice is never raised")
    assert one(
        url, "SELECT count(*) FROM app.invoice_adjustments WHERE invoice_id=%s", case["late"]
    ) == (0,)
    # An Invoice of another type is raised as before.
    source_line = cast(UUID, case["line"])
    raised = invoices().adjust(
        case["prop"],
        case["invoice"],
        AdjustInvoiceCommand(
            uuid4(),
            source_line,
            AdjustmentType.DEBIT,
            1_000,
            f"raise/{uuid4()}",
            "Meter read wrong",
            version(url, case["invoice"]),
        ),
        actor=invoice_api_actor(case["human"], case["prop"]),
    )
    assert raised["status"] == "UNPAID"


VOID = "SELECT app.void_invoice(%s,%s,%s,%s,%s,%s,%s,%s,%s)"


def void(url: str, case: dict[str, Any], invoice: UUID) -> None:
    version = one(url, "SELECT version FROM app.invoices WHERE id=%s", invoice)[0]
    with psycopg.connect(financial_database_url()) as financial:
        financial.execute(
            VOID,
            (
                case["prop"],
                invoice,
                case["human"],
                uuid4(),
                "c" * 64,
                version,
                "Made by mistake",
                uuid4(),
                uuid4(),
            ),
        )


def test_the_late_invoice_is_not_made_void_while_its_late_payment_invoice_stands(
    migrated_database_url: str,
) -> None:
    """As with a charge before: first the Late-payment Invoice is made Void, then the Invoice
    that was late may be."""
    url = migrated_database_url
    case = charged(url, 2)

    with pytest.raises(psycopg.Error) as refused:
        void(url, case, case["invoice"])
    assert refused.value.sqlstate == "P4502"
    # The check of the Void record itself says the same, whoever writes it.
    assert refusal(
        url,
        "WITH made AS (UPDATE app.invoices SET status='VOID',version=version+1,"
        "updated_at=clock_timestamp(),updated_by=%s WHERE id=%s RETURNING id,updated_at) "
        "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
        "authorization_reference) SELECT %s,id,'Made by mistake',updated_at,%s,'invoices.void' "
        "FROM made",
        case["human"],
        case["invoice"],
        uuid4(),
        case["human"],
    ) == ("23514", "Invoice VOID dependencies are not resolved")
    void(url, case, case["late"])
    void(url, case, case["invoice"])
    assert one(
        url,
        "SELECT array_agg(status ORDER BY status) FROM app.invoices WHERE id IN (%s,%s)",
        case["invoice"],
        case["late"],
    ) == (["VOID", "VOID"],)


def test_the_card_of_the_late_invoice_names_its_late_payment_invoice(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = charged(url, 3)

    shown = card(case)
    assert shown is not None
    number = one(url, "SELECT invoice_number FROM app.invoices WHERE id=%s", case["late"])[0]
    assert shown["late_invoice"] == {
        "invoice_id": str(case["late"]),
        "invoice_number": number,
        "status": "UNPAID",
    }
    assert shown["charge_id"] is None
    assert (shown["invoice_id"], shown["customer_id"]) == (
        str(case["invoice"]),
        str(case["customer"]),
    )
    assert (shown["by_app"], shown["added_by"]) == (True, None)
    assert (shown["unpaid_at_charge_usd_cents"], shown["rate_basis_points"]) == (80_000, 1000)
    assert (shown["decision_outcome"], shown["calculated_default_usd_cents"]) == (
        "CONFIRMED_DEFAULT",
        8_000,
    )
    assert (shown["original_usd_cents"], shown["now_usd_cents"]) == (8_000, 8_000)
    assert (shown["still_owed_usd_cents"], shown["paid_usd_cents"]) == (8_000, 0)
    assert (shown["changes"], shown["paid_by"]) == ([], [])
    # The Late-payment Invoice has no card of its own.
    assert card(case, case["late"]) is None

    void(url, case, case["late"])
    after = card(case)
    assert after is not None
    assert after["late_invoice"]["status"] == "VOID"
    assert (after["now_usd_cents"], after["still_owed_usd_cents"]) == (0, 0)


def test_the_income_report_counts_a_late_payment_invoice_as_late_payment_income(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    month = today(url).replace(day=1)

    def of_the_month(kind: str, human: UUID, prop: UUID) -> int:
        return sum(
            cast(int, row[3])
            for row in facts("report_income_facts", human, prop)
            if row[1] == month and row[2] == kind
        )

    case = overdue(url, months_ago(url, 4))
    late_before = of_the_month("LATE_PAYMENT_CHARGES", case["human"], case["prop"])
    other_before = of_the_month("MISCELLANEOUS_CHARGES", case["human"], case["prop"])
    seed_last_run(url, case["prop"], case["service"], case["due"])
    assert record(case)["outcome"] == "CHARGED"

    assert of_the_month("LATE_PAYMENT_CHARGES", case["human"], case["prop"]) == late_before + 8_000
    assert of_the_month("MISCELLANEOUS_CHARGES", case["human"], case["prop"]) == other_before
