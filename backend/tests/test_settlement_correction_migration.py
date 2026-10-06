"""Post-settlement correction record (V1-056 sub-slice 10a).

BR-SETTLE-012 and BR-SETTLE-013 (owner answers to Q-2026-10-06-36): a closed Final Settlement is
never reopened; a later fix is a new correction linked to it, with a reason, prepared as a
SETTLEMENT_CORRECTION draft and confirmed only by a financial.approve holder (BR-AUTH-010), with no
time limit. DB-SETTLE-003 is the correction header and DB-SETTLE-005 links each record the
correction writes. The closed Settlement refusals of sub-slices 8e-1 and 8e-2 let a record through
only when it is linked to a correction of the same Settlement confirmed in the same transaction.
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

from property_rental.invoice import (
    CorrectInvoiceDraftCommand,
    CreateInvoiceDraftCommand,
    InvoiceConflictError,
)
from test_final_settlement_closed_refusal_migration import (
    CLOSED,
    close,
    closed_refusal,
    no_lease_charge,
)
from test_final_settlement_credit_application_migration import (
    REVERSAL_REFUSED,
    decide,
    write,
)
from test_final_settlement_draft_migration import STAFF, leaving_case, normal_plan, record
from test_final_settlement_migration import one, outstanding
from test_final_settlement_preview_migration import key_card
from test_invoice_migration import setup_signed_lease
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_one_time_charges_migration import invoices
from test_one_time_charges_migration import staff as invoice_staff

BEGIN = "SELECT app.begin_settlement_correction(%s,%s,%s,%s)"
LINK = "SELECT app.link_settlement_correction_effect(%s,%s,%s)"
REASON = "The Damage charge was billed twice"
INTERNAL = (
    "app.reject_settlement_correction_mutation()",
    "app.validate_settlement_correction()",
    "app.assert_settlement_correction_confirmed()",
    "app.validate_settlement_correction_effect()",
    "app.settlement_correction_id(uuid)",
    "app.settlement_correction_linked(uuid,text,uuid)",
    "app.begin_settlement_correction(uuid,uuid,uuid,text)",
    "app.link_settlement_correction_effect(uuid,text,uuid)",
)
CLOSED_GUARD = "app.refuse_closed_final_settlement_change()"
CREDIT_REVERSAL_GUARD = "app.refuse_final_settlement_credit_application_reversal()"
NOT_CLOSED = "A post-settlement correction needs a closed Final Settlement"
NOT_CONFIRMED = "A post-settlement correction needs its draft confirmed by its approver"
NO_EFFECT = "A post-settlement correction needs at least one effect"
LATE_EFFECT = "A correction effect is written with its correction"


def approver(url: str) -> UUID:
    """Another active person, made by the signed-Lease fixture (the same person may also confirm
    with financial.approve, plan Q4)."""
    with psycopg.connect(url) as connection:
        return setup_signed_lease(connection)[0]


def correction_draft(url: str, case: dict[str, Any], settlement: UUID | None = None) -> UUID:
    """A SETTLEMENT_CORRECTION draft, as the variant recorders (later sub-slices) will write it."""
    draft = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.insert_financial_draft(%s,%s,%s,'SETTLEMENT_CORRECTION',"
            "'final_settlements.prepare',%s,NULL,%s)",
            (
                case["prop"],
                case["human"],
                draft,
                Jsonb({"final_settlement_id": str(settlement or case["settlement"])}),
                REASON,
            ),
        )
    return draft


def invoice_of(url: str, line: UUID) -> UUID:
    return UUID(str(one(url, "SELECT invoice_id FROM app.invoice_lines WHERE id=%s", line)[0]))


def credit_adjustment(
    connection: psycopg.Connection[Any], case: dict[str, Any], adjustment: UUID, amount: int = 100
) -> None:
    """A credit Adjustment on the Settlement's open line, through the existing writer."""
    invoice = connection.execute(
        "SELECT invoice_id FROM app.invoice_lines WHERE id=%s", (case["other_line"],)
    ).fetchone()
    assert invoice is not None
    version = connection.execute(
        "SELECT version FROM app.invoices WHERE id=%s", (invoice[0],)
    ).fetchone()
    assert version is not None
    connection.execute(
        "SELECT app.adjust_invoice(%s,%s,%s,%s,%s,%s,%s,'CREDIT',%s,%s,%s,%s,%s)",
        (
            case["prop"],
            invoice[0],
            case["other_line"],
            case["human"],
            uuid4(),
            "a" * 64,
            version[0],
            amount,
            f"correction/{uuid4()}",
            REASON,
            adjustment,
            uuid4(),
        ),
    )


def correct(url: str, case: dict[str, Any], person: UUID) -> tuple[UUID, UUID, UUID]:
    """One correction of the closed Settlement: header, link, then the linked credit Adjustment,
    all in one transaction. Returns the draft, the correction and the Adjustment."""
    draft = correction_draft(url, case)
    adjustment = uuid4()
    with psycopg.connect(url) as connection:
        found = connection.execute(
            BEGIN, (case["prop"], person, draft, "financial.approve")
        ).fetchone()
        assert found is not None
        correction = UUID(str(found[0]))
        connection.execute(LINK, (correction, "invoice_adjustment_id", adjustment))
        credit_adjustment(connection, case, adjustment)
        assert connection.execute(
            "SELECT app.settlement_correction_linked(%s,'invoice_adjustments',%s)",
            (case["settlement"], adjustment),
        ).fetchone() == (True,)
    return draft, correction, adjustment


def refusal(url: str, *statements: tuple[str, tuple[object, ...]]) -> tuple[Any, Any]:
    """Run the statements in one transaction; the refusal rolls back everything."""
    with pytest.raises(psycopg.Error) as failure, psycopg.connect(url) as connection:
        for sql, parameters in statements:
            connection.execute(sql, parameters)
    return failure.value.sqlstate, failure.value.diag.message_primary


def count(url: str, sql: str, *parameters: object) -> int:
    return int(one(url, sql, *parameters)[0])


def settlement_row(url: str, settlement: UUID) -> Any:
    """The Settlement row and the number of its closure snapshot rows."""
    return one(
        url,
        "SELECT to_jsonb(s),(SELECT count(*) FROM app.settlement_invoice_items i "
        "WHERE i.final_settlement_id=s.id),(SELECT count(*) FROM "
        "app.settlement_late_payment_charge_items c WHERE c.final_settlement_id=s.id),"
        "(SELECT count(*) FROM app.settlement_invoice_line_items l "
        "JOIN app.settlement_invoice_items i ON i.id=l.settlement_invoice_item_id "
        "WHERE i.final_settlement_id=s.id) "
        "FROM app.final_settlements s WHERE s.id=%s",
        settlement,
    )


def test_a_correction_needs_a_closed_settlement_and_writes_its_header_and_links(
    migrated_database_url: str,
) -> None:
    """BR-SETTLE-013: an open Settlement takes no correction; a closed one takes a correction that
    records the approver's confirmation, a header with the draft's reason and one link per record,
    and the Settlement row and its closure snapshots stay exactly as they were (BR-SETTLE-012)."""
    url = migrated_database_url
    case = leaving_case(url)
    person = approver(url)
    draft = correction_draft(url, case)
    begin = (BEGIN, (case["prop"], person, draft, "financial.approve"))
    assert refusal(url, begin) == ("55000", NOT_CLOSED)
    assert (
        count(url, "SELECT count(*) FROM app.financial_draft_decisions WHERE draft_id=%s", draft)
        == 0
    )
    close(url, case["human"], case["settlement"])
    before = settlement_row(url, case["settlement"])
    # Only financial.approve confirms; the draft must be a SETTLEMENT_CORRECTION draft.
    assert refusal(url, (BEGIN, (case["prop"], person, draft, "final_settlements.prepare")))[0] == (
        "42501"
    )
    assert refusal(url, (BEGIN, (case["prop"], person, uuid4(), "financial.approve")))[0] == "P0002"
    malformed = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.insert_financial_draft(%s,%s,%s,'SETTLEMENT_CORRECTION',"
            "'final_settlements.prepare',%s,NULL,%s)",
            (case["prop"], case["human"], malformed, Jsonb({"final_settlement_id": "x"}), REASON),
        )
    assert refusal(url, (BEGIN, (case["prop"], person, malformed, "financial.approve"))) == (
        "P0002",
        "Final Settlement was not found",
    )
    # A header alone never commits: it needs at least one effect.
    assert refusal(url, begin) == ("23514", NO_EFFECT)
    assert (
        count(url, "SELECT count(*) FROM app.financial_draft_decisions WHERE draft_id=%s", draft)
        == 0
    )
    open_before = outstanding(url, case["other_line"])
    decided, correction, adjustment = correct(url, case, person)
    assert outstanding(url, case["other_line"]) == open_before - 100
    stored = one(
        url,
        "SELECT final_settlement_id,reason,actor_id,authorization_reference,"
        "app.settlement_correction_id(correlation_id)=id,occurred_at>=(SELECT closed_at FROM "
        "app.final_settlements WHERE id=final_settlement_id) FROM app.settlement_corrections "
        "WHERE id=%s",
        correction,
    )
    assert stored == (case["settlement"], REASON, person, "financial.approve", True, True)
    decision = one(
        url,
        "SELECT decision.decision,decision.decided_by,decision.result->>'settlement_correction_id',"
        "decision.result ? 'transaction_id' "
        "FROM app.financial_draft_decisions decision JOIN app.settlement_corrections correction "
        "ON correction.correlation_id=decision.draft_id WHERE correction.id=%s",
        correction,
    )
    assert decision == ("CONFIRMED", person, str(correction), True)
    assert one(
        url,
        "SELECT effect_sequence,invoice_adjustment_id,"
        "num_nonnulls(invoice_id,payment_allocation_id,refund_id,customer_credit_reversal_id) "
        "FROM app.settlement_correction_effects "
        "WHERE settlement_correction_id=%s",
        correction,
    ) == (1, adjustment, 0)
    assert settlement_row(url, case["settlement"]) == before
    # A decided draft is never confirmed again.
    assert refusal(url, (BEGIN, (case["prop"], person, decided, "financial.approve"))) == (
        "55000",
        "Financial draft is already decided",
    )


def test_a_correction_commits_only_with_its_draft_confirmed_by_its_approver(
    migrated_database_url: str,
) -> None:
    """The deferred check: a header written while its draft waits, or under another person's
    confirmation in the same transaction, is refused at commit, even when the table owner writes
    it. The header check needs a closed Settlement, that Settlement's draft, the draft's reason,
    and a time not before the closure and not later than the clock plus 5 seconds."""
    url = migrated_database_url
    case = leaving_case(url)
    person = approver(url)
    close(url, case["human"], case["settlement"])
    header = (
        "INSERT INTO app.settlement_corrections(id,final_settlement_id,reason,occurred_at,actor_id,"
        "authorization_reference,correlation_id) VALUES (%s,%s,%s,clock_timestamp(),%s,"
        "'financial.approve',%s)"
    )
    # While the draft waits: the header alone reaches commit and is refused there.
    draft = correction_draft(url, case)
    assert refusal(url, (header, (uuid4(), case["settlement"], REASON, person, draft))) == (
        "42501",
        NOT_CONFIRMED,
    )
    # Another person confirmed it in this transaction: the link is accepted, the commit is not.
    draft = correction_draft(url, case)
    correction = uuid4()
    assert refusal(
        url,
        (
            "SELECT app.confirm_financial_draft_record(%s,%s,%s,'SETTLEMENT_CORRECTION',"
            "jsonb_build_object('transaction_id',pg_current_xact_id()::text),'financial.approve')",
            (case["prop"], case["human"], draft),
        ),
        (header, (correction, case["settlement"], REASON, person, draft)),
        (LINK, (correction, "invoice_id", case["initial"])),
    ) == ("42501", NOT_CONFIRMED)
    # The header's own checks, at insert.
    other = leaving_case(url)
    close(url, other["human"], other["settlement"])
    still_open = leaving_case(url)
    open_draft = correction_draft(url, still_open)
    draft = correction_draft(url, case)
    at = (
        "INSERT INTO app.settlement_corrections(id,final_settlement_id,reason,occurred_at,actor_id,"
        "authorization_reference,correlation_id) SELECT %s,id,%s,{},%s,'financial.approve',%s "
        "FROM app.final_settlements WHERE id=%s"
    )
    for sql, values in (
        (header, (uuid4(), case["settlement"], "Another reason", person, draft)),
        # Another closed Settlement than the draft names.
        (header, (uuid4(), other["settlement"], REASON, person, draft)),
        # The Settlement the draft names is still open.
        (header, (uuid4(), still_open["settlement"], REASON, person, open_draft)),
        (
            at.format("closed_at-interval '1 second'"),
            (uuid4(), REASON, person, draft, case["settlement"]),
        ),
        (
            at.format("clock_timestamp()+interval '1 minute'"),
            (uuid4(), REASON, person, draft, case["settlement"]),
        ),
    ):
        assert refusal(url, (sql, values)) == (
            "23514",
            "A post-settlement correction needs its closed Final Settlement, its draft and valid "
            "chronology",
        )


def test_a_transaction_that_started_before_another_committed_cannot_use_its_correction(
    migrated_database_url: str,
) -> None:
    """Review round 2 (the round-1 blocker): two transactions start, a third commits a correction;
    neither earlier transaction may use that committed correction's link to pass the closed
    Settlement refusal, nor add an effect to it."""
    url = migrated_database_url
    case = leaving_case(url)
    person = approver(url)
    close(url, case["human"], case["settlement"])
    effect = (
        "INSERT INTO app.settlement_correction_effects(id,settlement_correction_id,effect_sequence,"
        "invoice_id) VALUES (%s,%s,2,%s)"
    )
    with psycopg.connect(url) as early, psycopg.connect(url) as other_early:
        early.execute("SELECT 1")
        other_early.execute("SELECT 1")
        _, correction, adjustment = correct(url, case, person)
        with pytest.raises(psycopg.Error) as reused:
            credit_adjustment(early, case, adjustment)
        assert (reused.value.sqlstate, reused.value.diag.message_primary) == ("P5S01", CLOSED)
        early.rollback()
        with pytest.raises(psycopg.Error) as appended:
            other_early.execute(effect, (uuid4(), correction, case["initial"]))
        assert (appended.value.sqlstate, appended.value.diag.message_primary) == (
            "23514",
            LATE_EFFECT,
        )
        other_early.rollback()
    assert (
        count(
            url,
            "SELECT count(*) FROM app.settlement_correction_effects "
            "WHERE settlement_correction_id=%s",
            correction,
        )
        == 1
    )


def test_each_effect_has_exactly_one_link_and_belongs_to_a_new_correction(
    migrated_database_url: str,
) -> None:
    """DB-SETTLE-005: exactly one typed link per row, a record is linked to at most one
    correction, an unknown link is refused, and no effect is added to a committed correction."""
    url = migrated_database_url
    case = leaving_case(url)
    person = approver(url)
    close(url, case["human"], case["settlement"])
    _, correction, adjustment = correct(url, case, person)
    effect = (
        "INSERT INTO app.settlement_correction_effects(id,settlement_correction_id,effect_sequence,"
        "invoice_id,refund_id) VALUES (%s,%s,%s,%s,%s)"
    )
    # The committed correction takes no further effect.
    assert refusal(url, (effect, (uuid4(), correction, 2, case["initial"], None))) == (
        "23514",
        LATE_EFFECT,
    )
    draft = correction_draft(url, case)
    begin = (BEGIN, (case["prop"], person, draft, "financial.approve"))
    derived = UUID(str(one(url, "SELECT app.settlement_correction_id(%s)", draft)[0]))
    # A new correction: no link, or two links, breaks the one-link check.
    for links in ((None, None), (case["initial"], uuid4())):
        sqlstate, message = refusal(url, begin, (effect, (uuid4(), derived, 1, *links)))
        assert sqlstate == "23514" and "settlement_correction_effect_one_link" in str(message)
    assert refusal(url, begin, (LINK, (derived, "invoice_adjustment_id", adjustment)))[0] == "23505"
    assert refusal(url, begin, (LINK, (derived, "payment_id", uuid4())))[0] == "22023"
    assert (
        count(
            url,
            "SELECT count(*) FROM app.settlement_correction_effects "
            "WHERE settlement_correction_id=%s",
            correction,
        )
        == 1
    )


def test_the_closed_settlement_refusal_lets_through_only_a_record_linked_in_this_transaction(
    migrated_database_url: str,
) -> None:
    """Sub-slice 8e-1 stays the rule after closure: an unlinked Adjustment, an Adjustment linked to
    another Settlement's correction, an unlinked Adjustment reversal, and a VOID (which has no link,
    even inside a correction) are refused; an Adjustment reversal linked to a new correction of the
    same Settlement passes. A link committed earlier no longer counts."""
    url = migrated_database_url
    case = leaving_case(url)
    other = leaving_case(url)
    person = approver(url)
    for settled in (case, other):
        close(url, settled["human"], settled["settlement"])
    _, _, adjustment = correct(url, case, person)
    open_before = outstanding(url, case["other_line"])
    with psycopg.connect(url) as connection:
        assert connection.execute(
            "SELECT app.settlement_correction_linked(%s,'invoice_adjustments',%s)",
            (case["settlement"], adjustment),
        ).fetchone() == (False,)
    with pytest.raises(psycopg.Error) as unlinked, psycopg.connect(url) as connection:
        credit_adjustment(connection, case, uuid4())
    assert (unlinked.value.sqlstate, unlinked.value.diag.message_primary) == ("P5S01", CLOSED)
    elsewhere = correction_draft(url, other)
    other_correction = UUID(str(one(url, "SELECT app.settlement_correction_id(%s)", elsewhere)[0]))
    wrong = uuid4()
    with pytest.raises(psycopg.Error) as foreign, psycopg.connect(url) as connection:
        connection.execute(BEGIN, (other["prop"], person, elsewhere, "financial.approve"))
        connection.execute(LINK, (other_correction, "invoice_adjustment_id", wrong))
        credit_adjustment(connection, case, wrong)
    assert (foreign.value.sqlstate, foreign.value.diag.message_primary) == ("P5S01", CLOSED)
    reversal = (
        "INSERT INTO app.invoice_adjustment_reversals(id,invoice_adjustment_id,reason,occurred_at,"
        "actor_id,authorization_reference) VALUES (%s,%s,%s,clock_timestamp(),%s,'invoices.adjust')"
    )
    undo = uuid4()
    assert refusal(url, (reversal, (undo, adjustment, REASON, case["human"]))) == ("P5S01", CLOSED)
    void = (
        "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
        "authorization_reference) VALUES (%s,%s,%s,clock_timestamp(),%s,'invoices.void')"
    )
    draft = correction_draft(url, case)
    correction = UUID(str(one(url, "SELECT app.settlement_correction_id(%s)", draft)[0]))
    begin = (BEGIN, (case["prop"], person, draft, "financial.approve"))
    invoice = invoice_of(url, case["other_line"])
    assert refusal(
        url,
        begin,
        (LINK, (correction, "invoice_id", invoice)),
        (void, (uuid4(), invoice, REASON, case["human"])),
    ) == ("P5S01", CLOSED)
    with psycopg.connect(url) as connection:
        connection.execute(*begin)
        connection.execute(LINK, (correction, "invoice_adjustment_reversal_id", undo))
        connection.execute(reversal, (undo, adjustment, REASON, case["human"]))
    assert outstanding(url, case["other_line"]) == open_before + 100
    assert (
        count(url, "SELECT count(*) FROM app.invoice_void_events WHERE invoice_id=%s", invoice) == 0
    )


def test_an_invoice_draft_moves_onto_the_closed_lease_only_inside_its_own_correction(
    migrated_database_url: str,
) -> None:
    """Review round 1: the UPDATE path of the 8e-1 refusal. A draft with no Lease linked by a
    committed correction cannot be corrected onto a charge of the closed Lease in a later
    transaction; a draft linked by a correction confirmed in the same transaction can."""
    url = migrated_database_url
    case = leaving_case(url)
    human, prop, lease, customer = case["human"], case["prop"], case["lease"], case["customer"]
    person = approver(url)
    staff = invoice_staff(human, prop)
    charge = key_card(customer, lease)
    invoices().record_one_time_charge(prop, charge, actor=staff)
    drafts = []
    for _ in range(2):
        free = no_lease_charge(customer)
        invoices().record_one_time_charge(prop, free, actor=staff)
        drafts.append(
            invoices().create_draft(
                prop, CreateInvoiceDraftCommand(uuid4(), free.charge_id), actor=staff
            )
        )
    close(url, human, case["settlement"])
    committed, current = (UUID(str(draft["id"])) for draft in drafts)
    draft = correction_draft(url, case)
    correction = UUID(str(one(url, "SELECT app.settlement_correction_id(%s)", draft)[0]))
    with psycopg.connect(url) as connection:
        connection.execute(BEGIN, (prop, person, draft, "financial.approve"))
        connection.execute(LINK, (correction, "invoice_id", committed))
    closed_refusal(
        InvoiceConflictError,
        invoices().correct_draft,
        prop,
        committed,
        CorrectInvoiceDraftCommand(
            uuid4(), charge.charge_id, "Bill the key card", cast(int, drafts[0]["version"])
        ),
        actor=staff,
    )
    assert one(url, "SELECT lease_id FROM app.invoices WHERE id=%s", committed) == (None,)
    draft = correction_draft(url, case)
    correction = UUID(str(one(url, "SELECT app.settlement_correction_id(%s)", draft)[0]))
    with psycopg.connect(url) as connection:
        connection.execute(BEGIN, (prop, person, draft, "financial.approve"))
        connection.execute(LINK, (correction, "invoice_id", current))
        connection.execute(
            "SELECT app.correct_invoice_draft(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                prop,
                current,
                charge.charge_id,
                human,
                uuid4(),
                "b" * 64,
                drafts[1]["version"],
                "Bill the key card",
                uuid4(),
            ),
        )
    assert one(url, "SELECT lease_id,status FROM app.invoices WHERE id=%s", current) == (
        lease,
        "DRAFT",
    )


def test_a_settlement_credit_application_reversal_passes_only_inside_a_correction(
    migrated_database_url: str,
) -> None:
    """Sub-slice 8e-2 stays the rule after closure: a Credit application the Settlement made is
    reversed only when the reversal is linked to a correction of that Settlement confirmed in the
    same transaction; the Credit is then available again."""
    url = migrated_database_url
    case = leaving_case(url)
    person = approver(url)
    settlement_draft = record(case, normal_plan(case), pet_remainder=STAFF)["draft_id"]
    with psycopg.connect(url) as connection:
        decide(connection, case, settlement_draft)
        application = UUID(write(connection, case, settlement_draft, 1)["id"])
    close(url, case["human"], case["settlement"])
    credit = UUID(
        str(
            one(
                url,
                "SELECT customer_credit_id FROM app.customer_credit_applications WHERE id=%s",
                application,
            )[0]
        )
    )
    available = int(str(one(url, "SELECT app.credit_available_value(%s)", credit)[0]))
    amount = int(
        str(
            one(
                url,
                "SELECT amount_usd_cents FROM app.customer_credit_applications WHERE id=%s",
                application,
            )[0]
        )
    )
    reversal = (
        "INSERT INTO app.customer_credit_application_reversals(id,credit_application_id,reason,"
        "occurred_at,actor_id,authorization_reference) VALUES (%s,%s,%s,clock_timestamp(),%s,"
        "'credits.applications.reverse')"
    )
    undo = uuid4()
    assert refusal(url, (reversal, (undo, application, REASON, case["human"]))) == (
        "P5S01",
        REVERSAL_REFUSED,
    )
    # A correction of another closed Settlement does not let it through.
    other = leaving_case(url)
    close(url, other["human"], other["settlement"])
    elsewhere = correction_draft(url, other)
    other_correction = UUID(str(one(url, "SELECT app.settlement_correction_id(%s)", elsewhere)[0]))
    assert refusal(
        url,
        (BEGIN, (other["prop"], person, elsewhere, "financial.approve")),
        (LINK, (other_correction, "credit_application_reversal_id", undo)),
        (reversal, (undo, application, REASON, case["human"])),
    ) == ("P5S01", REVERSAL_REFUSED)
    draft = correction_draft(url, case)
    with psycopg.connect(url) as connection:
        found = connection.execute(
            BEGIN, (case["prop"], person, draft, "financial.approve")
        ).fetchone()
        assert found is not None
        connection.execute(LINK, (found[0], "credit_application_reversal_id", undo))
        connection.execute(reversal, (undo, application, REASON, case["human"]))
    assert int(str(one(url, "SELECT app.credit_available_value(%s)", credit)[0])) == (
        available + amount
    )


def test_correction_records_are_append_only_and_have_no_time_limit(
    migrated_database_url: str,
) -> None:
    """No change or removal of a header or an effect; the only time checks are "not before the
    closure" and "not later than the clock plus 5 seconds" (owner: no time limit)."""
    url = migrated_database_url
    case = leaving_case(url)
    close(url, case["human"], case["settlement"])
    _, correction, _ = correct(url, case, approver(url))
    for statement in (
        "UPDATE app.settlement_corrections SET reason='Changed' WHERE id=%s",
        "DELETE FROM app.settlement_corrections WHERE id=%s",
        "UPDATE app.settlement_correction_effects SET effect_sequence=9 "
        "WHERE settlement_correction_id=%s",
        "DELETE FROM app.settlement_correction_effects WHERE settlement_correction_id=%s",
    ):
        assert refusal(url, (statement, (correction,)))[0] == "55000"
    sources = {
        function: str(
            one(
                url,
                "SELECT prosrc FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure",
                function,
            )[0]
        )
        for function in INTERNAL
    }
    validate = sources["app.validate_settlement_correction()"]
    assert "NEW.occurred_at<v_settlement.closed_at" in validate
    assert "clock_timestamp()+interval '5 seconds'" in validate
    # No other time bound in any correction function: no age, no deadline.
    assert sum(source.count("interval") for source in sources.values()) == 1
    assert not any("age(" in source for source in sources.values())


def test_settlement_correction_records_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
            for table in ("app.settlement_corrections", "app.settlement_correction_effects"):
                assert connection.execute(
                    "SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE')",
                    (role, table),
                ).fetchone() == (False,), (role, table)
            for function in (*INTERNAL, CLOSED_GUARD, CREDIT_REVERSAL_GUARD):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (role, function)
        for function in (*INTERNAL, CLOSED_GUARD, CREDIT_REVERSAL_GUARD):
            definer, settings = cast(
                tuple[bool, list[str]],
                connection.execute(
                    "SELECT prosecdef,proconfig FROM pg_catalog.pg_proc "
                    "WHERE oid=CAST(%s AS regprocedure)",
                    (function,),
                ).fetchone(),
            )
            assert definer and "search_path=pg_catalog" in settings, function
        assert connection.execute(
            "SELECT tgdeferrable,tginitdeferred FROM pg_catalog.pg_trigger "
            "WHERE tgrelid='app.settlement_corrections'::regclass "
            "AND tgname='settlement_corrections_confirmed'"
        ).fetchone() == (True, True)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261101_97")
    assert revision is not None and revision.down_revision == "20261031_96"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, object], set[str]]:
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
        return functions, tables

    with _temporary_migration_database("settlement_correction") as temporary:
        alembic_command.upgrade(config, "20261031_96")
        before_functions, before_tables = catalog(temporary)
        alembic_command.upgrade(config, "20261101_97")
        after_functions, after_tables = catalog(temporary)
    assert after_tables - before_tables == {
        "app.settlement_corrections",
        "app.settlement_correction_effects",
    }
    assert before_tables <= after_tables
    assert set(after_functions) - set(before_functions) == set(INTERNAL)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {CLOSED_GUARD, CREDIT_REVERSAL_GUARD}
