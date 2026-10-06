"""One-call reversal of a Credit released to another Customer (V1-056 sub-slice 8g).

BR-CREDIT-014 and BR-CREDIT-008; owner answer to Q-2026-10-06-35 (approved tightening): a Customer
Credit that a credit Adjustment released to a Customer who is not the payer of its source Payment
stays with that Customer. The one-call Credit reversal (credits.reverse) refuses it for every
writer, so its value never goes back onto the payer's Payment; the Credit can still be refunded to
its Customer through the CREDIT_CUSTOMER Refund draft of sub-slice 8f.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.credit import CreditConflictError, ReverseCreditCommand
from property_rental.identity import AuthenticatedActor
from refund_test_support import cash
from test_credit_adjustment_excess_migration import credit as credit_adjustment
from test_credit_customer_refund_migration import (
    approving,
    available,
    command,
    moved_credit,
    staff,
    third_party_credit,
)
from test_credit_customer_refund_migration import service as refunds
from test_credit_migration import credit_id, recognize
from test_credit_migration import service as credits
from test_credit_migration import source as credit_source
from test_migrations import _temporary_migration_database
from test_payment_move_migration import WrongAllocation, person, rows, value, wrong_allocation
from test_reservation_migration import migrated_database_url  # noqa: F401

REFUSAL = "app.validate_credit_customer_credit_reversal()"
TRIGGER = "customer_credit_reversals_other_customer"
REFUSED = (
    "A Credit released to a Customer other than the payer stays with that Customer; "
    "apply it to that Customer's obligations or refund it to that Customer"
)
MOVED_REFUSED = (
    "A Credit released from a moved Payment stays with its Customer; "
    "apply it to that Customer's Invoices"
)


def reverser(identity: UUID, prop: UUID) -> AuthenticatedActor:
    return person(identity, prop, "credits.reverse")


def reversals(url: str, credit: UUID) -> int:
    return int(
        value(
            url,
            "SELECT count(*) FROM app.customer_credit_reversals WHERE customer_credit_id=%s",
            credit,
        )
    )


def direct_reversal(url: str, credit: UUID, actor: UUID) -> psycopg.Error:
    """Even the database owner's direct reversal row is refused, at the BEFORE INSERT trigger."""
    with psycopg.connect(url) as connection:
        with pytest.raises(psycopg.Error) as refused:
            connection.execute(
                "INSERT INTO app.customer_credit_reversals(id,customer_credit_id,reason,"
                "occurred_at,actor_id,authorization_reference) "
                "VALUES (%s,%s,'Direct',clock_timestamp(),%s,'credits.reverse')",
                (uuid4(), credit, actor),
            )
        connection.rollback()
    return refused.value


def payer_adjustment_credit(url: str) -> tuple[WrongAllocation, UUID]:
    """A normal Customer Payment pays its payer's Invoice; a credit Adjustment of 5,000 releases
    5,000 as Credit of that Invoice Customer, who is the payer."""
    case = wrong_allocation(url)
    credit_adjustment(url, case.human, case.prop, case.invoice_wrong, case.line_wrong, 5_000)
    credit = UUID(
        str(
            value(
                url,
                "SELECT release.customer_credit_id FROM app.invoice_credit_excess_releases release "
                "JOIN app.customer_credits credit ON credit.id=release.customer_credit_id "
                "WHERE credit.source_payment_id=%s",
                case.payment,
            )
        )
    )
    return case, credit


def test_a_third_party_adjustment_credit_is_not_reversed_back_onto_the_payers_payment(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """The one-call reversal of the Invoice Customer's Credit, released from a third-party
    Payment, is a conflict that writes nothing; the value stays the Customer's Credit and is
    refunded to that Customer only through the CREDIT_CUSTOMER draft."""
    url = migrated_database_url
    case, credit, payer = third_party_credit(url)
    assert (
        value(url, "SELECT customer_id FROM app.customer_credits WHERE id=%s", credit)
        == case.customer_wrong
        != payer
    )
    assert value(url, "SELECT app.credit_customer_refund_basis(%s) IS NOT NULL", credit) is True
    with pytest.raises(CreditConflictError) as refused:
        credits().reverse(
            case.prop,
            credit,
            ReverseCreditCommand(uuid4(), "Return the value to the payer"),
            actor=reverser(case.human, case.prop),
        )
    cause = refused.value.__cause__
    assert isinstance(cause, psycopg.Error)
    assert (cause.sqlstate, cause.diag.message_primary) == ("P4904", REFUSED)
    assert reversals(url, credit) == 0 and available(url, credit) == 5_000
    assert value(url, "SELECT app.payment_available_value(%s)", case.payment) == 0
    # The Credit stays with its Customer: the CREDIT_CUSTOMER Refund draft pays that Customer.
    choice = cash(refunds(), case.prop, staff(case))
    draft = refunds().record_credit_customer_draft(
        case.prop, command(credit, 5_000), choice, actor=staff(case)
    )
    confirmed = refunds().confirm_draft(
        case.prop, UUID(str(draft["draft_id"])), actor=approving(case)
    )
    header = cast(dict[str, object], cast(dict[str, object], confirmed["refund"])["refund"])
    assert header["recipient_customer_id"] == str(case.customer_wrong)
    assert available(url, credit) == 0 and reversals(url, credit) == 0
    assert value(url, "SELECT app.payment_available_value(%s)", case.payment) == 0


def test_the_payers_own_credits_are_still_reversed_with_one_call(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """Only Credits released to a Customer other than the payer are refused: the payer's
    recognized Credit and an adjustment Credit whose Customer is the payer of a normal Customer
    Payment are reversed as before."""
    url = migrated_database_url
    human, prop, _, payment = credit_source(url, 2_000)
    own = credit_id(recognize(prop, payment, human, 1_000))
    case, payer_credit = payer_adjustment_credit(url)
    for credit, prop_id, actor in (
        (own, prop, human),
        (payer_credit, case.prop, case.human),
    ):
        assert value(url, "SELECT app.credit_customer_refund_basis(%s)", credit) is None
        credits().reverse(
            prop_id,
            credit,
            ReverseCreditCommand(uuid4(), "Recorded by mistake"),
            actor=reverser(actor, prop_id),
        )
        assert reversals(url, credit) == 1
    assert value(url, "SELECT app.payment_available_value(%s)", case.payment) == 5_000


def test_every_writer_is_refused_and_the_slice_7_refusal_still_answers_first(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """The refusal sits on the table, so even the database owner's direct row is refused; a
    Credit released from a moved allocation to another Customer meets both refusals, and the
    slice 7 one answers first, as before."""
    url = migrated_database_url
    case, credit, _ = third_party_credit(url)
    refused = direct_reversal(url, credit, case.human)
    assert (refused.sqlstate, refused.diag.message_primary) == ("P4904", REFUSED)
    moved_case, moved = moved_credit(url)
    assert value(url, "SELECT app.credit_customer_refund_basis(%s) IS NOT NULL", moved) is True
    refused = direct_reversal(url, moved, moved_case.human)
    assert (refused.sqlstate, refused.diag.message_primary) == ("P4904", MOVED_REFUSED)
    assert reversals(url, credit) == 0 and reversals(url, moved) == 0


def test_credit_customer_credit_reversal_refusal_is_least_privilege_and_forward_only(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
            assert connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, REFUSAL)
            ).fetchone() == (False,), role
        assert connection.execute(
            "SELECT prosecdef,proconfig FROM pg_catalog.pg_proc WHERE oid=CAST(%s AS regprocedure)",
            (REFUSAL,),
        ).fetchone() == (True, ["search_path=pg_catalog"])
    # Row-level BEFORE INSERT triggers fire in name order: the slice 7 refusal, this refusal,
    # then the Credit reversal checks that lock the Payment and the Credit.
    assert rows(
        url,
        "SELECT trigger_name FROM information_schema.triggers "
        "WHERE event_object_schema='app' AND event_object_table='customer_credit_reversals' "
        "AND action_timing='BEFORE' AND event_manipulation='INSERT' AND action_orientation='ROW' "
        "ORDER BY trigger_name",
    ) == [
        ("customer_credit_reversals_moved_payment",),
        (TRIGGER,),
        ("customer_credit_reversals_validate",),
    ]
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261031_96")
    assert revision is not None and revision.down_revision == "20261030_95"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, object], set[str], set[str]]:
        with psycopg.connect(database) as connection:
            functions = {
                str(row[0]): row[1]
                for row in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid) "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ).fetchall()
            }
            tables = {
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
        return functions, tables, triggers

    with _temporary_migration_database("credit_customer_credit_reversal") as temporary:
        alembic_command.upgrade(config, "20261030_95")
        before_functions, before_tables, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, "20261031_96")
        after_functions, after_tables, after_triggers = catalog(temporary)
    assert after_tables == before_tables
    assert set(after_functions) - set(before_functions) == {REFUSAL}
    assert not {
        name for name in before_functions if after_functions[name] != before_functions[name]
    }
    assert after_triggers - before_triggers == {f"app.customer_credit_reversals:{TRIGGER}"}
    assert before_triggers <= after_triggers
