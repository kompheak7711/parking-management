"""Deposit application reversals (V1-056 sub-slice 10c-2a-1).

DB-DEP-006 (owner answer 2 to Q-2026-10-06-36): a Final Settlement Deposit application is
reversed only through a post-settlement correction of its Settlement confirmed in the same
transaction (BR-SETTLE-013, BR-AUTH-010), so the Deposit holds the amount again and the obligation
owes it again (DB-DER-004). Every reader counts only applications not reversed; the Customer
Ledger shows the reversal on both ledgers (DB-DER-010) and the Deposit history shows it
(BR-SETTLE-009). No correction writer exists yet, so these tests build the correction by hand
through the internal sub-slice 10a functions, in one owner transaction, as no role can.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.customer_ledger import LedgerFilter
from property_rental.customer_ledger_query import LEDGER_CAPABILITY, LedgerReadRequest
from property_rental.customer_ledger_read import CustomerLedgerReadService
from property_rental.deposit_api import PostgresDepositResourceFlow
from test_credit_migration import actor
from test_customer_ledger_migration import assert_reconciled, history
from test_final_settlement_closed_refusal_migration import CLOSED, close
from test_final_settlement_draft_migration import leaving_case
from test_final_settlement_migration import (
    apply,
    charge_remaining,
    held,
    invoice_state,
    one,
    outstanding,
    overdue_lease_with_pet_damage,
    start,
)
from test_final_settlement_preview_migration import pay
from test_invoice_migration import runtime_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_settlement_correction_migration import (
    BEGIN,
    LINK,
    approver,
    correction_draft,
    count,
    credit_adjustment,
    settlement_row,
)
from test_settlement_extra_charge_migration import state

HISTORY = "app.deposit_application_reversal_history(uuid,uuid)"
INTERNAL = (
    "app.reject_deposit_application_reversal_mutation()",
    "app.validate_deposit_application_reversal()",
    "app.complete_deposit_application_reversal()",
)
CHANGED = (
    "app.invoice_line_deposit_value_at(uuid,timestamp with time zone)",
    "app.deposit_balance_events(uuid)",
    "app.deposit_snapshot(uuid)",
    "app.late_payment_charge_application_summary(uuid)",
    "app.refuse_deposit_applied_obligation_change()",
    "app.allocation_target_latest_at(text,uuid)",
    "app.customer_ledger_page(uuid,uuid,uuid,text,integer,timestamp with time zone,"
    "timestamp with time zone,text,text,uuid,timestamp with time zone,text,uuid,text)",
    "app.settlement_correction_linked(uuid,text,uuid)",
    "app.link_settlement_correction_effect(uuid,text,uuid)",
)
REVERSE = (
    "INSERT INTO app.deposit_application_reversals(id,deposit_application_id,reason,occurred_at,"
    "actor_id,authorization_reference) VALUES (%s,%s,%s,clock_timestamp(),%s,'financial.approve')"
)
REASON = "The pet damage charge was billed twice"
UNLINKED = "A Deposit application is reversed only through a post-settlement correction"
INVALID = "Deposit application reversal actor, authorization or chronology is invalid"
DEPOSIT_PAID = "A Deposit application paid this obligation at Final Settlement"


def reversal_case(url: str) -> dict[str, Any]:
    """A closed Settlement whose Pet Deposit paid 1,000 of the pet damage line and up to 500 of
    the Late-payment Charge, with the approver and a waiting correction draft."""
    f = overdue_lease_with_pet_damage(url)
    prop, human = f["prop"], f["human"]
    settlement = start(prop, human, f["lease"])
    case: dict[str, Any] = {**f, "settlement": settlement}
    case["damage_due"] = outstanding(url, f["pet_line"])
    case["charge_due"] = charge_remaining(url, f["charge"])
    apply(
        url,
        prop,
        human,
        settlement,
        f["pet"],
        "PET_RELATED_FIRST",
        "INVOICE_LINE",
        f["pet_line"],
        1_000,
        1,
    )
    # Leave at least 1 cent of the Charge unpaid, so a 1-cent reduction stays above what is paid.
    assert case["charge_due"] > 1
    case["charge_paid"] = min(case["charge_due"] - 1, 500)
    apply(
        url,
        prop,
        human,
        settlement,
        f["pet"],
        "PET_REMAINDER_EXPLICIT",
        "LATE_PAYMENT_CHARGE",
        f["charge"],
        case["charge_paid"],
        2,
    )
    for order, name in ((1, "line_application"), (2, "charge_application")):
        case[name] = UUID(
            str(
                one(
                    url,
                    "SELECT id FROM app.deposit_applications "
                    "WHERE final_settlement_id=%s AND application_order=%s",
                    settlement,
                    order,
                )[0]
            )
        )
    close(url, human, settlement)
    case["person"] = approver(url)
    case["draft"] = correction_draft(url, case)
    return case


def begin(connection: psycopg.Connection[Any], case: dict[str, Any], draft: UUID) -> UUID:
    found = connection.execute(
        BEGIN, (case["prop"], case["person"], draft, "financial.approve")
    ).fetchone()
    assert found is not None
    return UUID(str(found[0]))


def reverse(
    connection: psycopg.Connection[Any],
    correction: UUID,
    application: UUID,
    actor: UUID,
    *,
    link: bool = True,
) -> UUID:
    reversal = uuid4()
    if link:
        connection.execute(LINK, (correction, "deposit_application_reversal_id", reversal))
    connection.execute(REVERSE, (reversal, application, REASON, actor))
    return reversal


def refusal(error: pytest.ExceptionInfo[psycopg.Error]) -> tuple[str | None, str | None]:
    return error.value.sqlstate, error.value.diag.message_primary


def reversed_events(connection: psycopg.Connection[Any], customer: UUID) -> list[dict[str, object]]:
    return [
        event
        for event in history(connection, customer)
        if event["event_kind"] == "DEPOSIT_APPLICATION_REVERSED"
    ]


def test_a_reversed_deposit_application_pays_nothing_and_the_deposit_holds_it_again(
    migrated_database_url: str,
) -> None:
    """DB-DEP-006, DB-DER-004, DB-DER-010 and BR-SETTLE-009: once a correction reverses the two
    applications, the Pet Deposit holds the amounts again, the line and the Charge owe them again,
    every reader agrees, both ledgers reconcile and the Deposit history shows each reversal. The
    closed Settlement row is unchanged and a second reversal of the same application is
    refused."""
    url = migrated_database_url
    case = reversal_case(url)
    customer, pet, line, charge = case["customer"], case["pet"], case["pet_line"], case["charge"]
    paid = case["charge_paid"]
    assert held(url, pet) == 20_000 - 1_000 - paid
    assert outstanding(url, line) == case["damage_due"] - 1_000
    assert charge_remaining(url, charge) == case["charge_due"] - paid
    settlement_before = settlement_row(url, case["settlement"])
    status_before, version_before = invoice_state(url, case["pet_invoice"])
    assert status_before == "PARTIALLY_PAID"
    with psycopg.connect(url) as connection:
        correction = begin(connection, case, case["draft"])
        line_reversal = reverse(connection, correction, case["line_application"], case["person"])
        charge_reversal = reverse(
            connection, correction, case["charge_application"], case["person"]
        )
    assert state(url, case["draft"]) == "CONFIRMED"
    assert held(url, pet) == 20_000
    assert one(url, "SELECT app.deposit_snapshot(%s)->'held_refundable_usd_cents'", pet) == (
        20_000,
    )
    assert one(url, "SELECT sum(amount) FROM app.deposit_balance_events(%s)", pet) == (20_000,)
    assert one(url, "SELECT app.deposit_has_active_application(%s)", pet) == (False,)
    assert outstanding(url, line) == case["damage_due"]
    # At commit the reversed line's Invoice gets its status and version refreshed (review round 1).
    status_after, version_after = invoice_state(url, case["pet_invoice"])
    assert (status_after, version_after > version_before) == ("UNPAID", True)
    assert charge_remaining(url, charge) == case["charge_due"]
    summary = one(url, "SELECT app.late_payment_charge_application_summary(%s)", charge)[0]
    assert (summary["deposit_total_usd_cents"], summary["items"]) == (0, [])
    # As of a time between the application and its reversal, the line was paid by the Deposit.
    assert one(
        url,
        "SELECT app.invoice_line_deposit_value_at(%s,"
        "reversal.occurred_at-interval '1 microsecond'),"
        "app.invoice_line_deposit_value_at(%s,'infinity') "
        "FROM app.deposit_application_reversals reversal WHERE reversal.id=%s",
        line,
        line,
        line_reversal,
    ) == (1_000, 0)
    # The reversal is the latest event of each target (allocation chronology).
    assert one(
        url,
        "SELECT app.allocation_target_latest_at('INVOICE',%s)=(SELECT occurred_at FROM "
        "app.deposit_application_reversals WHERE id=%s),"
        "app.allocation_target_latest_at('LATE_PAYMENT_CHARGE',%s)=(SELECT occurred_at FROM "
        "app.deposit_application_reversals WHERE id=%s)",
        case["pet_invoice"],
        line_reversal,
        charge,
        charge_reversal,
    ) == (True, True)
    with psycopg.connect(url) as connection:
        linked = connection.execute(
            "SELECT deposit_application_reversal_id FROM app.settlement_correction_effects "
            "WHERE settlement_correction_id=%s ORDER BY effect_sequence",
            (correction,),
        ).fetchall()
    assert [row[0] for row in linked] == [line_reversal, charge_reversal]
    # Both ledgers: the Deposit owner and the obligations' Customer are the same Customer here,
    # so each reversal has one header with both components and the opposite of DEPOSIT_APPLIED.
    with psycopg.connect(url) as connection:
        position = assert_reconciled(connection, customer)
        events = reversed_events(connection, customer)
    assert position.pet_deposit == 20_000
    assert [
        (
            event["event_id"],
            event["event_order"],
            event["source_table"],
            event["component_count"],
            event["pet_deposit_effect_usd_cents"],
            event["invoice_effect_usd_cents"],
            event["charge_effect_usd_cents"],
            cast(dict[str, Any], event["source_audit"])["application_id"],
        )
        for event in events
    ] == [
        (
            str(line_reversal),
            76,
            "deposit_application_reversals",
            2,
            1_000,
            1_000,
            0,
            str(case["line_application"]),
        ),
        (
            str(charge_reversal),
            76,
            "deposit_application_reversals",
            2,
            paid,
            0,
            paid,
            str(case["charge_application"]),
        ),
    ]
    # The runtime ledger read accepts the new kind as a history filter (review round 1).
    found = CustomerLedgerReadService(runtime_database_url()).get(
        customer,
        LedgerReadRequest(filters=LedgerFilter(event_kind="DEPOSIT_APPLICATION_REVERSED")),
        actor=actor(case["human"], case["prop"], LEDGER_CAPABILITY),
    )
    rows = cast(list[dict[str, Any]], cast(dict[str, Any], found["data"])["items"])
    assert sorted((row["event_id"], row["event_kind"]) for row in rows) == sorted(
        [
            (str(line_reversal), "DEPOSIT_APPLICATION_REVERSED"),
            (str(charge_reversal), "DEPOSIT_APPLICATION_REVERSED"),
        ]
    )
    # BR-SETTLE-009: the Deposit's own history shows each reversal.
    page = PostgresDepositResourceFlow(runtime_database_url()).ledger(pet, limit=50, cursor=None)
    assert sorted(
        (
            event.event_id,
            event.event_kind,
            event.amount_usd_cents,
            event.source_id,
            event.governing_source_kind,
            event.governing_source_id,
            event.actor_id,
            event.authorization_reference,
            event.reason,
        )
        for event in page.items
        if event.event_kind.startswith("APPLICATION_REVERSAL_")
    ) == sorted(
        [
            (
                line_reversal,
                "APPLICATION_REVERSAL_INVOICE_LINE",
                1_000,
                case["line_application"],
                "FINAL_SETTLEMENT",
                case["settlement"],
                case["person"],
                "financial.approve",
                REASON,
            ),
            (
                charge_reversal,
                "APPLICATION_REVERSAL_LATE_PAYMENT_CHARGE",
                paid,
                case["charge_application"],
                "FINAL_SETTLEMENT",
                case["settlement"],
                case["person"],
                "financial.approve",
                REASON,
            ),
        ]
    )
    with psycopg.connect(runtime_database_url()) as runtime:
        assert runtime.execute(
            f"SELECT count(*) FROM {HISTORY.split('(')[0]}(%s,%s)", (case["prop"], pet)
        ).fetchone() == (2,)
        assert runtime.execute(
            f"SELECT count(*) FROM {HISTORY.split('(')[0]}(%s,%s)", (uuid4(), pet)
        ).fetchone() == (0,)
    assert settlement_row(url, case["settlement"]) == settlement_before
    # One reversal per application: a later correction cannot reverse it again.
    again = correction_draft(url, case)
    with pytest.raises(psycopg.Error) as twice, psycopg.connect(url) as connection:
        reverse(
            connection, begin(connection, case, again), case["line_application"], case["person"]
        )
    assert twice.value.sqlstate == "23505"
    assert state(url, again) == "PENDING"


def test_a_deposit_application_is_reversed_only_inside_its_own_settlements_correction(
    migrated_database_url: str,
) -> None:
    """BR-SETTLE-013 and BR-AUTH-010: a reversal is refused when it is not linked to a correction,
    when it is linked to a correction of another Settlement, when another person or another
    authorization writes it, for an unknown application, with an invalid reason, and outside the
    time bounds: before the closure or the correction, not later than the latest event of its
    target (a Payment allocation after closure) or of its Deposit (another reversal), or later
    than the clock plus 5 seconds (review round 1). Every attempt rolls back and the draft stays
    pending. The table is append-only."""
    url = migrated_database_url
    case = reversal_case(url)
    application = case["line_application"]
    other = {**leaving_case(url), "person": case["person"]}
    close(url, other["human"], other["settlement"])
    other_draft = correction_draft(url, other)

    def refused(statement: str, *arguments: object) -> Any:
        with pytest.raises(psycopg.Error) as failure, psycopg.connect(url) as connection:
            correction = begin(connection, case, case["draft"])
            reversal = uuid4()
            connection.execute(LINK, (correction, "deposit_application_reversal_id", reversal))
            connection.execute(statement, (reversal, application, *arguments))
        return refusal(failure)

    with pytest.raises(psycopg.Error) as unlinked, psycopg.connect(url) as connection:
        reverse(
            connection,
            begin(connection, case, case["draft"]),
            application,
            case["person"],
            link=False,
        )
    assert refusal(unlinked) == ("23514", UNLINKED)
    with pytest.raises(psycopg.Error) as elsewhere, psycopg.connect(url) as connection:
        reverse(connection, begin(connection, other, other_draft), application, case["person"])
    assert refusal(elsewhere) == ("23514", UNLINKED)
    assert refused(REVERSE, REASON, case["human"]) == ("23514", INVALID)
    statement = (
        "INSERT INTO app.deposit_application_reversals(id,deposit_application_id,reason,"
        "occurred_at,actor_id,authorization_reference) VALUES (%s,%s,%s,{at},%s,%s)"
    )
    assert refused(
        statement.format(at="clock_timestamp()"), REASON, case["person"], "deposits.correct"
    ) == ("23514", INVALID)
    assert refused(
        statement.format(
            at="(SELECT closed_at FROM app.final_settlements WHERE id='"
            + str(case["settlement"])
            + "')-interval '1 second'"
        ),
        REASON,
        case["person"],
        "financial.approve",
    ) == ("23514", INVALID)
    assert refused(
        statement.format(at="clock_timestamp()+interval '1 minute'"),
        REASON,
        case["person"],
        "financial.approve",
    ) == ("23514", INVALID)
    assert refused(
        statement.format(at="clock_timestamp()"),
        "\u00a0Reversed for a wrong charge",
        case["person"],
        "financial.approve",
    ) == ("22023", "Deposit application reversal reason is invalid")
    with pytest.raises(psycopg.Error) as unknown, psycopg.connect(url) as connection:
        reverse(connection, begin(connection, case, case["draft"]), uuid4(), case["person"])
    assert refusal(unknown) == ("23503", "Deposit application was not found")
    # Not before the correction itself (the header is written after the closure).
    with pytest.raises(psycopg.Error) as early, psycopg.connect(url) as connection:
        correction = begin(connection, case, case["draft"])
        reversal = uuid4()
        connection.execute(LINK, (correction, "deposit_application_reversal_id", reversal))
        connection.execute(
            statement.format(
                at="(SELECT occurred_at FROM app.settlement_corrections WHERE id=%s)"
                "-interval '1 microsecond'"
            ),
            (
                reversal,
                case["charge_application"],
                REASON,
                correction,
                case["person"],
                "financial.approve",
            ),
        )
    assert refusal(early) == ("23514", INVALID)
    # Later than the Deposit's latest event: a second reversal dated before the first one.
    with pytest.raises(psycopg.Error) as behind_deposit, psycopg.connect(url) as connection:
        correction = begin(connection, case, case["draft"])
        first = reverse(connection, correction, case["charge_application"], case["person"])
        reversal = uuid4()
        connection.execute(LINK, (correction, "deposit_application_reversal_id", reversal))
        connection.execute(
            statement.format(
                at="(SELECT occurred_at FROM app.deposit_application_reversals WHERE id=%s)"
                "-interval '1 microsecond'"
            ),
            (reversal, application, REASON, first, case["person"], "financial.approve"),
        )
    assert refusal(behind_deposit) == ("23514", INVALID)
    # Later than the target's latest event: a Payment allocation on the line posted after the
    # correction began, so neither the closure nor the correction bound can refuse it (review
    # round 2); the reversal is dated at that allocation.
    with pytest.raises(psycopg.Error) as behind_target, psycopg.connect(url) as connection:
        correction = begin(connection, case, case["draft"])
        pay(
            url,
            case["prop"],
            case["human"],
            case["customer"],
            case["pet_invoice"],
            case["pet_line"],
            500,
        )
        reversal = uuid4()
        connection.execute(LINK, (correction, "deposit_application_reversal_id", reversal))
        assert connection.execute(
            "SELECT max(allocation.posted_at)>correction.occurred_at "
            "FROM app.payment_allocations allocation,app.settlement_corrections correction "
            "WHERE allocation.invoice_id=%s AND correction.id=%s "
            "GROUP BY correction.occurred_at",
            (case["pet_invoice"], correction),
        ).fetchone() == (True,)
        connection.execute(
            statement.format(
                at="(SELECT max(posted_at) FROM app.payment_allocations WHERE invoice_id=%s)"
            ),
            (
                reversal,
                application,
                REASON,
                case["pet_invoice"],
                case["person"],
                "financial.approve",
            ),
        )
    assert refusal(behind_target) == ("23514", INVALID)
    assert (state(url, case["draft"]), state(url, other_draft)) == ("PENDING", "PENDING")
    assert (
        count(
            url,
            "SELECT count(*) FROM app.deposit_application_reversals "
            "WHERE deposit_application_id=%s",
            application,
        )
        == 0
    )
    assert held(url, case["pet"]) == 20_000 - 1_000 - case["charge_paid"]
    # Append-only, also for the table owner.
    with psycopg.connect(url) as connection:
        reversal = reverse(
            connection, begin(connection, case, case["draft"]), application, case["person"]
        )
    for statement in (
        "UPDATE app.deposit_application_reversals SET reason='Changed' WHERE id=%s",
        "DELETE FROM app.deposit_application_reversals WHERE id=%s",
    ):
        with pytest.raises(psycopg.Error) as mutation, psycopg.connect(url) as connection:
            connection.execute(statement, (reversal,))
        assert refusal(mutation) == ("55000", "Deposit application reversals are append-only")
    # The correction link (DB-SETTLE-005) refers to the table, so PostgreSQL refuses TRUNCATE before
    # the no-truncate trigger runs (full run P1).
    with pytest.raises(psycopg.Error) as truncate, psycopg.connect(url) as connection:
        connection.execute("TRUNCATE app.deposit_application_reversals")
    assert refusal(truncate) == (
        "0A000",
        "cannot truncate a table referenced in a foreign key constraint",
    )


def test_a_deposit_paid_obligation_changes_inside_a_correction_only_once_reversed(
    migrated_database_url: str,
) -> None:
    """The 8a-1 refusal of a change to a Deposit-paid obligation is relaxed only for an obligation
    whose Deposit applications are all reversed: inside a correction, a linked credit Adjustment
    of the pet damage Invoice, and a linked Late-payment Charge correction (review round 1), are
    refused while their Deposit application is active and accepted once the same correction
    reversed it. The draft stays pending after each refusal."""
    url = migrated_database_url
    case = reversal_case(url)
    target = {**case, "other_line": case["pet_line"]}
    with pytest.raises(psycopg.Error) as active, psycopg.connect(url) as connection:
        correction = begin(connection, case, case["draft"])
        adjustment = uuid4()
        connection.execute(LINK, (correction, "invoice_adjustment_id", adjustment))
        credit_adjustment(connection, target, adjustment)
    assert refusal(active) == ("55000", DEPOSIT_PAID)
    assert state(url, case["draft"]) == "PENDING"
    with psycopg.connect(url) as connection:
        correction = begin(connection, case, case["draft"])
        reverse(connection, correction, case["line_application"], case["person"])
        adjustment = uuid4()
        connection.execute(LINK, (correction, "invoice_adjustment_id", adjustment))
        credit_adjustment(connection, target, adjustment)
    assert state(url, case["draft"]) == "CONFIRMED"
    assert outstanding(url, case["pet_line"]) == case["damage_due"] - 100
    assert held(url, case["pet"]) == 20_000 - case["charge_paid"]
    # The relaxation is safe because the 8e-1 refusal still stops an unlinked one-call change of
    # the now Deposit-free obligation after closure (review round 2).
    with pytest.raises(psycopg.Error) as unlinked, psycopg.connect(url) as connection:
        credit_adjustment(connection, target, uuid4())
    assert refusal(unlinked) == ("P5S01", CLOSED)
    # The Late-payment Charge branch of the same refusal (P4603, the Late-payment conflict).
    charge_draft = correction_draft(url, case)

    def charge_correction(connection: psycopg.Connection[Any], correction: UUID) -> None:
        corrected = uuid4()
        connection.execute(LINK, (correction, "late_payment_charge_correction_id", corrected))
        connection.execute(
            "SELECT app.correct_late_payment_charge(%s,%s,%s,%s,%s,'deposit-reversal',"
            "'REDUCTION',1,NULL,'Charged in error',%s,%s)",
            (case["prop"], case["charge"], case["human"], uuid4(), "a" * 64, corrected, uuid4()),
        )

    with pytest.raises(psycopg.Error) as charge_active, psycopg.connect(url) as connection:
        charge_correction(connection, begin(connection, case, charge_draft))
    assert refusal(charge_active) == ("P4603", DEPOSIT_PAID)
    assert state(url, charge_draft) == "PENDING"
    with psycopg.connect(url) as connection:
        correction = begin(connection, case, charge_draft)
        reverse(connection, correction, case["charge_application"], case["person"])
        charge_correction(connection, correction)
    assert state(url, charge_draft) == "CONFIRMED"
    assert charge_remaining(url, case["charge"]) == case["charge_due"] - 1
    assert held(url, case["pet"]) == 20_000


def test_deposit_application_reversals_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (HISTORY, *INTERNAL):
            definer, settings = cast(
                tuple[bool, list[str] | None],
                connection.execute(
                    "SELECT prosecdef,proconfig FROM pg_catalog.pg_proc "
                    "WHERE oid=CAST(%s AS regprocedure)",
                    (function,),
                ).fetchone(),
            )
            assert settings is not None and "search_path=pg_catalog" in settings, function
            # Only the append-only refusal runs with the caller's rights.
            assert definer is (function != INTERNAL[0]), function
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                allowed = role == "prm_runtime" and function == HISTORY
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (allowed,), (role, function)
            # BR-SETTLE-013, no time limit: the only interval bounds the clock.
            source = connection.execute(
                "SELECT prosrc FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure", (function,)
            ).fetchone()
            assert source is not None and "age(" not in str(source[0]), function
            assert set(re.findall(r"interval '([^']*)'", str(source[0]))) <= {"5 seconds"}
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
            assert connection.execute(
                "SELECT has_table_privilege(%s,'app.deposit_application_reversals',"
                "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')",
                (role,),
            ).fetchone() == (False,), role
        # The new link is deferrable, unique and inside the one-link check.
        assert connection.execute(
            "SELECT condeferrable,condeferred,confrelid::regclass::text "
            "FROM pg_catalog.pg_constraint "
            "WHERE conrelid='app.settlement_correction_effects'::regclass AND contype='f' "
            "AND conkey=ARRAY[(SELECT attnum FROM pg_catalog.pg_attribute WHERE "
            "attrelid='app.settlement_correction_effects'::regclass "
            "AND attname='deposit_application_reversal_id')]"
        ).fetchone() == (True, True, "app.deposit_application_reversals")
        assert connection.execute(
            "SELECT count(*) FROM pg_catalog.pg_constraint "
            "WHERE conrelid='app.settlement_correction_effects'::regclass AND contype='u' "
            "AND conkey=ARRAY[(SELECT attnum FROM pg_catalog.pg_attribute WHERE "
            "attrelid='app.settlement_correction_effects'::regclass "
            "AND attname='deposit_application_reversal_id')]"
        ).fetchone() == (1,)
        one_link = connection.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_catalog.pg_constraint "
            "WHERE conname='settlement_correction_effect_one_link'"
        ).fetchone()
        assert one_link is not None and "deposit_application_reversal_id" in str(one_link[0])
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261105_101")
    assert revision is not None and revision.down_revision == "20261104_100"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, object], dict[str, object], set[str]]:
        with psycopg.connect(database) as connection:
            functions = {
                str(row[0]): row[1]
                for row in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid) "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ).fetchall()
            }
            relations = {
                str(row[0]): row[1]
                for row in connection.execute(
                    "SELECT c.oid::regclass::text,CASE WHEN c.relkind='v' "
                    "THEN pg_catalog.pg_get_viewdef(c.oid) END FROM pg_catalog.pg_class c "
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

    with _temporary_migration_database("deposit_application_reversal") as temporary:
        alembic_command.upgrade(config, "20261104_100")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, "20261105_101")
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert set(after_relations) - set(before_relations) == {"app.deposit_application_reversals"}
    assert set(before_relations) <= set(after_relations)
    # Only the ledger projection view changes: it gains the reversal event.
    assert {
        name
        for name in before_relations
        if before_relations[name] is not None and after_relations[name] != before_relations[name]
    } == {"app.customer_ledger_effects"}
    assert "DEPOSIT_APPLICATION_REVERSED" in str(after_relations["app.customer_ledger_effects"])
    assert set(after_functions) - set(before_functions) == {HISTORY, *INTERNAL}
    assert after_triggers - before_triggers == {
        "app.deposit_application_reversals:deposit_application_reversals_complete",
        "app.deposit_application_reversals:deposit_application_reversals_immutable",
        "app.deposit_application_reversals:deposit_application_reversals_no_truncate",
        "app.deposit_application_reversals:deposit_application_reversals_validate",
    }
    assert before_triggers <= after_triggers
    # The readers gain "not reversed" and the link functions gain the new link; no other
    # earlier function changes.
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set(CHANGED)
    for name in CHANGED:
        assert "deposit_application_revers" in str(after_functions[name]).lower(), name
        assert "deposit_application_revers" not in str(before_functions[name]).lower(), name
