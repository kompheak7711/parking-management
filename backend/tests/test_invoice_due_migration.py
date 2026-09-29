"""Synthetic PostgreSQL contract for the unpublished dated-attribution core.

These storage tests do not accept the still-pending command, replay or UI wiring.
"""

import os
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import Connection, sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from payment_test_support import seed_payment
from property_rental.invoice_due import DueSourceKind
from property_rental.invoice_due_history import (
    DueEffectKind,
    DueObligation,
    DueReduction,
    DueSourcePart,
    reconcile_line_due_history,
)
from test_invoice_migration import create_recurring_rent_invoice, setup_signed_lease
from test_migrations import _temporary_migration_database
from test_reservation_migration import migrated_database_url  # noqa: F401

DB = Connection[tuple[object, ...]]


@pytest.fixture
def due_connection(migrated_database_url: str) -> Iterator[DB]:  # noqa: F811
    with psycopg.connect(migrated_database_url) as connection:
        try:
            yield connection
        finally:
            connection.rollback()


def source(connection: DB) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    actor, prop, customer, lease = setup_signed_lease(connection)
    invoice, line = create_recurring_rent_invoice(
        connection, actor_id=actor, customer_id=customer, lease_id=lease
    )
    return actor, prop, customer, invoice, line


def adjustment(
    connection: DB,
    actor: UUID,
    prop: UUID,
    invoice: UUID,
    line: UUID,
    kind: str,
    amount: int,
    due: date | None = None,
    *,
    correction_parts: tuple[tuple[UUID | None, int, int], ...] | None = None,
) -> UUID:
    identifier = uuid4()
    selected: list[dict[str, object]] | None = None
    if correction_parts is not None:
        assert [part[2] for part in correction_parts] == list(range(1, len(correction_parts) + 1))
        selected = [
            {
                "source_kind": "ORIGINAL_LINE" if debit is None else "DEBIT_ADJUSTMENT",
                "source_id": str(line if debit is None else debit),
                "amount_usd_cents": value,
            }
            for debit, value, _ in correction_parts
        ]
    connection.execute(
        "SELECT app.adjust_invoice(%s,%s,%s,%s,%s,%s,"
        "(SELECT version FROM app.invoices WHERE id=%s),%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            prop,
            invoice,
            line,
            actor,
            uuid4(),
            "a" * 64,
            invoice,
            kind,
            amount,
            f"synthetic-approved-source:{identifier}",
            "Synthetic amount correction",
            identifier,
            uuid4(),
            due,
            "Synthetic approved governing document" if due is not None else None,
            Jsonb(selected) if selected is not None else None,
        ),
    )
    return identifier


def source_with_credit(
    connection: DB, amount: int
) -> tuple[tuple[UUID, UUID, UUID, UUID, UUID], UUID]:
    actor, prop, customer, lease = setup_signed_lease(connection)
    payment = seed_payment(
        connection, actor_id=actor, property_id=prop, customer_id=customer, amount=amount
    )
    recognized = connection.execute(
        "SELECT app.recognize_customer_credit(%s,%s,%s,%s,%s,%s,%s)",
        (
            prop,
            payment,
            actor,
            uuid4(),
            amount,
            "Synthetic Customer authorization",
            "Test recognition",
        ),
    ).fetchone()
    assert recognized is not None
    credit = UUID(cast(dict[str, Any], recognized[0])["credit"]["id"])

    invoice, line = create_recurring_rent_invoice(
        connection, actor_id=actor, customer_id=customer, lease_id=lease
    )
    return (actor, prop, customer, invoice, line), credit


def reduction(
    connection: DB,
    context: tuple[UUID, UUID, UUID, UUID, UUID],
    kind: DueEffectKind,
    amount: int,
    *,
    preexisting_credit: UUID | None = None,
    source_parts: tuple[tuple[UUID | None, int, int], ...] | None = None,
) -> UUID:
    actor, prop, customer, invoice, line = context
    if kind is DueEffectKind.CREDIT_ADJUSTMENT:
        return adjustment(
            connection, actor, prop, invoice, line, "CREDIT", amount, correction_parts=source_parts
        )
    detail = {"invoice_line_id": str(line), "amount_usd_cents": amount}
    if kind is DueEffectKind.PAYMENT_ALLOCATION:
        payment = seed_payment(
            connection, actor_id=actor, property_id=prop, customer_id=customer, amount=amount
        )
        intent: dict[str, Any] = {
            "mode": "DESIGNATED",
            "designation_reference": "Synthetic Customer designation",
            "targets": [
                {"invoice_id": str(invoice), "amount_usd_cents": amount, "details": [detail]}
            ],
        }
        connection.execute(
            "SELECT app.post_payment_allocations(%s,%s,%s,%s,%s,%s)",
            (prop, payment, actor, uuid4(), "b" * 64, Jsonb(intent)),
        )
        row = connection.execute(
            "SELECT detail.id FROM app.payment_allocation_details detail "
            "JOIN app.payment_allocations allocation ON allocation.id=detail.payment_allocation_id "
            "WHERE allocation.payment_id=%s AND detail.invoice_line_id=%s",
            (payment, line),
        ).fetchone()
    else:
        if preexisting_credit is None:
            raise ValueError(
                "Credit fixture must recognize true excess before creating its Invoice"
            )
        credit = preexisting_credit
        intent = {
            "mode": "DESIGNATED",
            "designation_reference": "Synthetic Customer designation",
            "invoice_id": str(invoice),
            "amount_usd_cents": amount,
            "details": [detail],
        }
        connection.execute(
            "SELECT app.post_credit_application(%s,%s,%s,%s,%s)",
            (prop, credit, actor, uuid4(), Jsonb(intent)),
        )
        row = connection.execute(
            "SELECT detail.id FROM app.customer_credit_application_details detail "
            "JOIN app.customer_credit_applications application "
            "ON application.id=detail.customer_credit_application_id "
            "WHERE application.customer_credit_id=%s AND detail.invoice_line_id=%s",
            (credit, line),
        ).fetchone()
    assert row is not None and isinstance(row[0], UUID)
    return row[0]


def parts(
    connection: DB,
    line: UUID,
    kind: DueEffectKind,
    parent: UUID,
    values: tuple[tuple[UUID | None, int, int], ...],
) -> None:
    field = {
        DueEffectKind.PAYMENT_ALLOCATION: "payment_detail_id",
        DueEffectKind.CUSTOMER_CREDIT_APPLICATION: "credit_application_detail_id",
        DueEffectKind.CREDIT_ADJUSTMENT: "credit_adjustment_id",
    }[kind]
    connection.execute("SET CONSTRAINTS app.invoice_due_source_parts_complete DEFERRED")
    for debit, amount, sequence in values:
        connection.execute(
            sql.SQL(
                "INSERT INTO app.invoice_due_source_parts("
                "id,invoice_line_id,debit_adjustment_id,{},"
                "amount_usd_cents,part_sequence) VALUES(%s,%s,%s,%s,%s,%s)"
            ).format(sql.Identifier(field)),
            (uuid4(), line, debit, parent, amount, sequence),
        )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


def position(connection: DB, line: UUID, as_of: datetime | None = None) -> dict[str, Any]:
    row = connection.execute(
        "SELECT app.invoice_line_due_position_at(%s,COALESCE(%s,clock_timestamp()))", (line, as_of)
    ).fetchone()
    assert row is not None and isinstance(row[0], dict)
    return row[0]


def assert_python_parity(connection: DB, line: UUID, at: datetime) -> None:
    sources = tuple(
        DueObligation(
            cast(UUID, row[2]),
            DueSourceKind(str(row[0])),
            cast(UUID, row[1]),
            cast(date | None, row[3]),
            cast(datetime, row[4]),
            cast(int, row[5]),
            cast(datetime | None, row[6]),
        )
        for row in connection.execute(
            "SELECT * FROM app.invoice_due_source_history(%s)", (line,)
        ).fetchall()
    )
    saved = connection.execute(
        "SELECT * FROM app.invoice_due_recorded_parts(%s)", (line,)
    ).fetchall()
    effects = tuple(
        DueReduction(
            line,
            DueEffectKind(str(row[0])),
            cast(UUID, row[1]),
            cast(datetime, row[3]),
            cast(int, row[4]),
            tuple(
                DueSourcePart(DueSourceKind(str(part[2])), cast(UUID, part[3]), cast(int, part[4]))
                for part in saved
                if part[0] == row[0] and part[1] == row[1]
            )
            or None,
            cast(datetime | None, row[5]),
        )
        for row in connection.execute(
            "SELECT * FROM app.invoice_due_reduction_history(%s)", (line,)
        ).fetchall()
    )
    expected = reconcile_line_due_history(line, at, sources, effects)
    actual = position(connection, line, at)
    assert actual["aggregate_outstanding_usd_cents"] == expected.aggregate_outstanding_usd_cents
    assert actual["attribution_complete"] == expected.attribution_complete
    assert actual["blockers"] == [
        {"code": x.code.value, "record_kind": x.record_kind, "record_id": str(x.record_id)}
        for x in expected.blockers
    ]
    assert [
        (x["source_kind"], x["source_id"], x["approved_due_date"], x["remaining_usd_cents"])
        for x in actual["amounts"]
    ] == [
        (
            x.source_kind.value,
            str(x.source_id),
            x.approved_due_date.isoformat(),
            x.remaining_usd_cents,
        )
        for x in expected.amounts
    ]
    assert actual["proven_original_reductions"] == [
        {"effect_kind": x.effect_kind.value, "effect_id": str(x.effect_id)}
        for x in expected.proven_original_reductions
    ]


@pytest.mark.parametrize("kind", list(DueEffectKind))
def test_due_storage_preserves_typed_parts_and_matches_python(
    due_connection: DB, kind: DueEffectKind
) -> None:
    credit: UUID | None = None
    if kind is DueEffectKind.CUSTOMER_CREDIT_APPLICATION:
        context, credit = source_with_credit(due_connection, 50_000)
    else:
        context = source(due_connection)
    actor, prop, _, invoice, line = context
    debit = adjustment(
        due_connection, actor, prop, invoice, line, "DEBIT", 20_000, date(2027, 3, 10)
    )
    values = ((None, 40_000, 1), (debit, 10_000, 2))
    parent = reduction(
        due_connection,
        context,
        kind,
        50_000,
        preexisting_credit=credit,
        source_parts=values if kind is DueEffectKind.CREDIT_ADJUSTMENT else None,
    )
    if kind is not DueEffectKind.CREDIT_ADJUSTMENT:
        parts(due_connection, line, kind, parent, values)
    actual = position(due_connection, line)
    assert actual["aggregate_outstanding_usd_cents"] == 50_000
    assert {x["source_id"]: x["remaining_usd_cents"] for x in actual["amounts"]} == {
        str(line): 40_000,
        str(debit): 10_000,
    }
    assert due_connection.execute(
        "SELECT due_date,original_total_usd_cents FROM app.invoices WHERE id=%s", (invoice,)
    ).fetchone() == (date(2027, 2, 5), 80_000)
    row = due_connection.execute("SELECT clock_timestamp()").fetchone()
    assert row is not None
    assert_python_parity(due_connection, line, cast(datetime, row[0]))


@pytest.mark.parametrize("kind", list(DueEffectKind))
def test_due_legacy_original_proof_and_later_ambiguity_are_distinct(
    legacy_due_connection: DB, kind: DueEffectKind
) -> None:
    connection = legacy_due_connection
    credit: UUID | None = None
    if kind is DueEffectKind.CUSTOMER_CREDIT_APPLICATION:
        context, credit = source_with_credit(connection, 5000)
    else:
        context = source(connection)
    actor, _, _, _, line = context
    original, parameters, response = legacy_adjustment(connection, context, "CREDIT", 10000)
    original_event = connection.execute(
        "SELECT occurred_at FROM app.invoice_adjustments WHERE id=%s", (original,)
    ).fetchone()
    assert original_event is not None and isinstance(original_event[0], datetime)
    debit, _, _ = legacy_adjustment(connection, context, "DEBIT", 20000)
    if kind is DueEffectKind.CREDIT_ADJUSTMENT:
        ambiguous, _, _ = legacy_adjustment(connection, context, "CREDIT", 5000)
    else:
        ambiguous = reduction(connection, context, kind, 5000, preexisting_credit=credit)
    # A real61reversal removes the debit balance, but cannot prove the later
    # reduction's intended source. Its ambiguous attribution must survive62.
    connection.execute(
        "INSERT INTO app.invoice_adjustment_reversals(id,invoice_adjustment_id,reason,"
        "occurred_at,actor_id,authorization_reference) "
        "VALUES(%s,%s,'Synthetic explicit legacy reversal',clock_timestamp(),%s,'invoices.adjust')",
        (uuid4(), debit, actor),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    before = upgrade_populated_due_history(connection)
    current = position(connection, line)
    assert current["aggregate_outstanding_usd_cents"] == 65000 and current["amounts"] == []
    assert current["blockers"] == [
        {
            "code": "AMBIGUOUS_LEGACY_ATTRIBUTION",
            "record_kind": kind.value,
            "record_id": str(ambiguous),
        }
    ]
    old_position = position(connection, line, original_event[0])
    assert old_position["attribution_complete"]
    assert old_position["aggregate_outstanding_usd_cents"] == 70000
    assert old_position["proven_original_reductions"] == [
        {"effect_kind": "CREDIT_ADJUSTMENT", "effect_id": str(original)}
    ]
    assert_python_parity(connection, line, original_event[0])
    assert_python_parity(connection, line, datetime.fromisoformat(current["as_of"]))
    assert_legacy_replay_and_new_post_blocked(connection, context, parameters, response, before)


def test_due_missing_legacy_date_is_not_imputed_from_original_invoice(
    legacy_due_connection: DB,
) -> None:
    connection = legacy_due_connection
    context = source(connection)
    *_, line = context
    debit, parameters, response = legacy_adjustment(connection, context, "DEBIT", 20000)
    before = upgrade_populated_due_history(connection)
    current = position(connection, line)
    assert current["aggregate_outstanding_usd_cents"] == 100000 and current["amounts"] == []
    assert current["blockers"] == [
        {
            "code": "MISSING_APPROVED_DUE_DATE",
            "record_kind": "DEBIT_ADJUSTMENT",
            "record_id": str(debit),
        }
    ]
    issued = connection.execute(
        "SELECT issued_at FROM app.invoices WHERE id=%s", (context[3],)
    ).fetchone()
    assert issued is not None and isinstance(issued[0], datetime)
    for at in (
        issued[0] - timedelta(microseconds=1),
        issued[0],
        datetime.fromisoformat(current["as_of"]),
    ):
        assert_python_parity(connection, line, at)
    assert_legacy_replay_and_new_post_blocked(connection, context, parameters, response, before)


@pytest.mark.parametrize(
    "invalid", ["incomplete_amount", "sequence_gap", "overapplied_source", "credit_as_debit"]
)
def test_due_parts_reject_invalid_source_conservation_and_sequence(
    due_connection: DB, invalid: str
) -> None:
    context = source(due_connection)
    actor, prop, _, invoice, line = context
    debit = adjustment(
        due_connection, actor, prop, invoice, line, "DEBIT", 20000, date(2027, 3, 10)
    )
    parent = uuid4()
    variants: dict[str, tuple[tuple[UUID | None, int, int], ...]] = {
        "incomplete_amount": ((None, 49999, 1),),
        "sequence_gap": ((None, 50000, 2),),
        "overapplied_source": ((debit, 50000, 1),),
        "credit_as_debit": ((parent, 50000, 1),),
    }
    # A direct writer must fail the complete atomic operation. No valid command
    # or committed parent may be manufactured without its required parts.
    with pytest.raises(psycopg.errors.CheckViolation), due_connection.transaction():
        due_connection.execute("SET CONSTRAINTS ALL DEFERRED")
        due_connection.execute(
            "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adjustment_type,"
            "amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
            "authorization_reference) "
            "VALUES(%s,%s,%s,'CREDIT',50000,%s,'Synthetic invalid parts test',"
            "clock_timestamp(),%s,'invoices.adjust')",
            (parent, invoice, line, f"synthetic-invalid:{parent}", actor),
        )
        parts(due_connection, line, DueEffectKind.CREDIT_ADJUSTMENT, parent, variants[invalid])
    assert due_connection.execute(
        "SELECT count(*) FROM app.invoice_due_source_parts WHERE credit_adjustment_id=%s", (parent,)
    ).fetchone() == (0,)
    assert due_connection.execute(
        "SELECT count(*) FROM app.invoice_adjustments WHERE id=%s", (parent,)
    ).fetchone() == (0,)


def test_due_debit_reversal_cannot_reassign_a_live_application(due_connection: DB) -> None:
    context = source(due_connection)
    actor, prop, _, invoice, line = context
    debit = adjustment(
        due_connection, actor, prop, invoice, line, "DEBIT", 20_000, date(2027, 3, 10)
    )
    parent = reduction(
        due_connection,
        context,
        DueEffectKind.CREDIT_ADJUSTMENT,
        10_000,
        source_parts=((debit, 10_000, 1),),
    )
    statement = (
        "INSERT INTO app.invoice_adjustment_reversals(id,invoice_adjustment_id,reason,"
        "occurred_at,actor_id,authorization_reference) "
        "VALUES(%s,%s,'Synthetic explicit reversal',clock_timestamp(),%s,'invoices.adjust')"
    )
    with pytest.raises(psycopg.errors.CheckViolation), due_connection.transaction():
        due_connection.execute(statement, (uuid4(), debit, actor))
        due_connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert position(due_connection, line)["aggregate_outstanding_usd_cents"] == 90_000
    due_connection.execute(statement, (uuid4(), parent, actor))
    due_connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    restored = position(due_connection, line)
    assert restored["aggregate_outstanding_usd_cents"] == 100_000
    due_connection.execute(statement, (uuid4(), debit, actor))
    due_connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert position(due_connection, line)["aggregate_outstanding_usd_cents"] == 80_000
    assert_python_parity(due_connection, line, datetime.fromisoformat(restored["as_of"]))


def test_due_evidence_is_immutable_and_core_has_no_runtime_write_access(due_connection: DB) -> None:
    actor, prop, _, invoice, line = source(due_connection)
    debit = adjustment(
        due_connection, actor, prop, invoice, line, "DEBIT", 20_000, date(2027, 3, 10)
    )
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState), due_connection.transaction():
        due_connection.execute(
            "UPDATE app.invoice_debit_due_sources SET approved_due_date=approved_due_date+1 "
            "WHERE invoice_adjustment_id=%s",
            (debit,),
        )
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState), due_connection.transaction():
        due_connection.execute(
            "DELETE FROM app.invoice_debit_due_sources WHERE invoice_adjustment_id=%s", (debit,)
        )
    for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
        for table in ("invoice_debit_due_sources", "invoice_due_source_parts"):
            assert due_connection.execute(
                "SELECT has_table_privilege(%s,%s,'INSERT,UPDATE,DELETE,TRUNCATE')",
                (role, "app." + table),
            ).fetchone() == (False,)
        assert due_connection.execute(
            "SELECT has_function_privilege(%s,"
            "'app.invoice_line_due_position_at(uuid,timestamptz)','EXECUTE')",
            (role,),
        ).fetchone() == (False,)
    assert position(due_connection, line)["attribution_complete"]


def post_due_adjustment(
    connection: DB,
    context: tuple[UUID, UUID, UUID, UUID, UUID],
    kind: str,
    amount: int,
    *,
    due: date | None = None,
    reference: str | None = None,
    correction_parts: object = None,
    legacy: bool = False,
    key: UUID | None = None,
) -> tuple[UUID, UUID, UUID, dict[str, Any]]:
    actor, prop, _, invoice, line = context
    identifier, audit, command_key = uuid4(), uuid4(), key or uuid4()
    parameters: tuple[object, ...] = (
        prop,
        invoice,
        line,
        actor,
        command_key,
        "b" * 64,
        invoice,
        kind,
        amount,
        f"synthetic-approved-correction:{command_key}",
        "Approved synthetic correction",
        identifier,
        audit,
    )
    query = (
        "SELECT app.adjust_invoice(%s,%s,%s,%s,%s,%s,"
        "(SELECT version FROM app.invoices WHERE id=%s),%s,%s,%s,%s,%s,%s"
    )
    if not legacy:
        query += ",%s,%s,%s"
        parameters = (
            *parameters,
            due,
            reference,
            Jsonb(correction_parts) if correction_parts is not None else None,
        )
    row = connection.execute(query + ")", parameters).fetchone()
    assert row is not None
    return identifier, command_key, audit, cast(dict[str, Any], row[0])


def test_due_command_debit_preserves_original_date_and_atomic_governing_audit(
    due_connection: DB,
) -> None:
    context = source(due_connection)
    actor, _, _, invoice, line = context
    original = due_connection.execute(
        "SELECT due_date,version FROM app.invoices WHERE id=%s", (invoice,)
    ).fetchone()
    assert original is not None and isinstance(original[1], int)
    identifier, _, audit, result = post_due_adjustment(
        due_connection,
        context,
        "DEBIT",
        1000,
        due=date(2027, 3, 9),
        reference="approved/document/1",
    )
    row = due_connection.execute(
        "SELECT due.approved_due_date,due.governing_source_reference,"
        "due.actor_id=adjustment.actor_id,due.occurred_at=adjustment.occurred_at,"
        "due.authorization_reference=adjustment.authorization_reference "
        "FROM app.invoice_debit_due_sources due JOIN app.invoice_adjustments adjustment "
        "ON adjustment.id=due.invoice_adjustment_id WHERE adjustment.id=%s",
        (identifier,),
    ).fetchone()
    assert row == (date(2027, 3, 9), "approved/document/1", True, True, True)
    assert (
        original[:1]
        == due_connection.execute(
            "SELECT due_date FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
    )
    evidence = due_connection.execute(
        "SELECT actor_id,linked_source_event_id,authorization_evidence FROM app.audit_events "
        "WHERE id=%s",
        (audit,),
    ).fetchone()
    assert evidence is not None and evidence[:2] == (actor, identifier)
    assert cast(dict[str, Any], evidence[2])["approved_due_date"] == "2027-03-09"
    assert cast(dict[str, Any], evidence[2])["governing_source_reference"] == "approved/document/1"
    assert result["version"] == original[1] + 1
    assert position(due_connection, line)["attribution_complete"] is True
    at = due_connection.execute("SELECT clock_timestamp()").fetchone()
    assert at is not None
    assert_python_parity(due_connection, line, cast(datetime, at[0]))


@pytest.mark.parametrize("legacy", [False, True])
def test_due_command_rejects_new_undated_debit_but_preserves_recorded_exact_response(
    due_connection: DB,
    legacy: bool,
) -> None:
    context = source(due_connection)
    actor, prop, _, invoice, _ = context
    with pytest.raises(psycopg.Error, match="approved governing due date"):
        with due_connection.transaction():
            post_due_adjustment(due_connection, context, "DEBIT", 1000, legacy=legacy)
    key = uuid4()
    # An exact stored pre-extension response is replayed without interpreting it
    # as a new post; populated61-to62 migration acceptance remains a separate gate.
    prior = {"id": str(invoice), "version": 1, "historical_response": "preserve verbatim"}
    due_connection.execute(
        "SELECT app.record_invoice_command(%s,%s,'adjust',%s,%s,%s,"
        "200::smallint,%s,clock_timestamp())",
        (prop, actor, key, "b" * 64, invoice, Jsonb(prior)),
    )
    _, _, _, response = post_due_adjustment(
        due_connection, context, "DEBIT", 1000, legacy=legacy, key=key
    )
    assert response == prior
    assert due_connection.execute(
        "SELECT count(*) FROM app.invoice_adjustments WHERE invoice_id=%s", (invoice,)
    ).fetchone() == (0,)
    assert due_connection.execute(
        "SELECT count(*) FROM app.invoice_commands WHERE invoice_id=%s AND action='adjust'",
        (invoice,),
    ).fetchone() == (1,)


def test_due_command_credit_records_explicit_sources_and_replay_without_reposting(
    due_connection: DB,
) -> None:
    context = source(due_connection)
    *_, line = context
    debit, _, _, _ = post_due_adjustment(
        due_connection, context, "DEBIT", 1000, due=date(2027, 3, 9), reference="approved/1"
    )
    selected = [
        {"source_kind": "ORIGINAL_LINE", "source_id": str(line), "amount_usd_cents": 100},
        {"source_kind": "DEBIT_ADJUSTMENT", "source_id": str(debit), "amount_usd_cents": 400},
    ]
    credit, key, audit, result = post_due_adjustment(
        due_connection, context, "CREDIT", 500, correction_parts=selected
    )
    assert due_connection.execute(
        "SELECT debit_adjustment_id,amount_usd_cents,part_sequence "
        "FROM app.invoice_due_source_parts "
        "WHERE credit_adjustment_id=%s ORDER BY part_sequence",
        (credit,),
    ).fetchall() == [(None, 100, 1), (debit, 400, 2)]
    _, _, _, replay = post_due_adjustment(
        due_connection, context, "CREDIT", 500, correction_parts=selected, key=key
    )
    assert replay == result
    assert due_connection.execute(
        "SELECT count(*) FROM app.invoice_due_source_parts WHERE credit_adjustment_id=%s", (credit,)
    ).fetchone() == (2,)
    evidence = due_connection.execute(
        "SELECT authorization_evidence->'correction_parts' FROM app.audit_events WHERE id=%s",
        (audit,),
    ).fetchone()
    assert evidence == (selected,)
    at = due_connection.execute("SELECT clock_timestamp()").fetchone()
    assert at is not None
    assert_python_parity(due_connection, line, cast(datetime, at[0]))


def test_due_command_only_infers_credit_source_when_history_has_no_debit(
    due_connection: DB,
) -> None:
    context = source(due_connection)
    credit, _, _, _ = post_due_adjustment(due_connection, context, "CREDIT", 100, legacy=True)
    assert due_connection.execute(
        "SELECT debit_adjustment_id,amount_usd_cents FROM app.invoice_due_source_parts "
        "WHERE credit_adjustment_id=%s",
        (credit,),
    ).fetchall() == [(None, 100)]
    post_due_adjustment(
        due_connection, context, "DEBIT", 1000, due=date(2027, 3, 9), reference="approved/1"
    )
    with pytest.raises(psycopg.Error, match="explicit source parts"):
        with due_connection.transaction():
            post_due_adjustment(due_connection, context, "CREDIT", 100, legacy=True)


@pytest.mark.parametrize(
    "case",
    [
        "duplicate",
        "wrong_line",
        "over_source",
        "wrong_total",
        "bool_amount",
        "fraction_amount",
        "unknown_field",
        "empty",
    ],
)
def test_due_command_rejects_invalid_source_parts_atomically(due_connection: DB, case: str) -> None:
    context = source(due_connection)
    *_, line = context
    original: dict[str, object] = {
        "source_kind": "ORIGINAL_LINE",
        "source_id": str(line),
        "amount_usd_cents": 100,
    }
    choices: dict[str, object] = {
        "duplicate": [original, original],
        "wrong_line": [{**original, "source_id": str(uuid4())}],
        "over_source": [{**original, "amount_usd_cents": 80001}],
        "wrong_total": [{**original, "amount_usd_cents": 99}],
        "bool_amount": [{**original, "amount_usd_cents": True}],
        "fraction_amount": [{**original, "amount_usd_cents": 1.5}],
        "unknown_field": [{**original, "extra": "not allowed"}],
        "empty": [],
    }
    with pytest.raises(psycopg.Error):
        with due_connection.transaction():
            post_due_adjustment(
                due_connection, context, "CREDIT", 100, correction_parts=choices[case]
            )
    assert due_connection.execute(
        "SELECT count(*) FROM app.invoice_adjustments WHERE invoice_line_id=%s", (line,)
    ).fetchone() == (0,)
    assert due_connection.execute(
        "SELECT count(*) FROM app.invoice_due_source_parts WHERE invoice_line_id=%s", (line,)
    ).fetchone() == (0,)


@pytest.mark.parametrize("kind", ["DEBIT", "CREDIT"])
def test_due_command_direct_adjustment_writer_requires_atomic_evidence(
    due_connection: DB,
    kind: str,
) -> None:
    actor, _, _, invoice, line = source(due_connection)
    with pytest.raises(psycopg.errors.CheckViolation, match="atomic"):
        with due_connection.transaction():
            due_connection.execute(
                "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adjustment_type,"
                "amount_usd_cents,source_reference,reason,occurred_at,actor_id,"
                "authorization_reference) "
                "VALUES(%s,%s,%s,%s,100,'synthetic/1','Approved synthetic correction',"
                "clock_timestamp(),%s,'invoices.adjust')",
                (uuid4(), invoice, line, kind, actor),
            )
            due_connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_due_command_only_financial_role_can_call_new_signature(due_connection: DB) -> None:
    signature = (
        "app.adjust_invoice(uuid,uuid,uuid,uuid,uuid,text,integer,text,bigint,"
        "text,text,uuid,uuid,date,text,jsonb)"
    )
    for role, expected in (
        ("prm_runtime", False),
        ("prm_bootstrap", False),
        ("prm_financial", True),
    ):
        assert due_connection.execute(
            "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)
        ).fetchone() == (expected,)
    for role in ("prm_runtime", "prm_bootstrap", "prm_financial"):
        assert due_connection.execute(
            "SELECT has_function_privilege(%s,"
            "'app.invoice_credit_correction_parts(uuid,bigint,jsonb,timestamptz)',"
            "'EXECUTE')",
            (role,),
        ).fetchone() == (False,)


LEGACY_ADJUSTMENT_SQL = "SELECT app.adjust_invoice(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
LEGACY_FINANCIAL_TABLES = (
    "invoices",
    "invoice_lines",
    "invoice_adjustments",
    "invoice_adjustment_reversals",
    "invoice_commands",
    "payments",
    "receipts",
    "payment_allocations",
    "payment_allocation_details",
    "payment_allocation_reversals",
    "customer_credits",
    "customer_credit_applications",
    "customer_credit_application_details",
    "customer_credit_application_reversals",
    "audit_events",
)


@pytest.fixture
def legacy_due_connection() -> Iterator[DB]:
    """Populate a real61database, never retroactively disable the62constraints."""
    with _temporary_migration_database("prm_due_legacy") as temporary:
        command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "20260915_61")
        with psycopg.connect(temporary) as connection:
            try:
                assert_legacy_due_target(connection, "20260915_61")
                yield connection
            finally:
                connection.rollback()


def assert_legacy_due_target(connection: DB, revision: str) -> None:
    target = conninfo_to_dict(os.environ["MIGRATION_DATABASE_URL"])
    name = connection.info.dbname
    suffix = name.removeprefix("prm_due_legacy_")
    assert name.startswith("prm_due_legacy_") and len(suffix) == 32
    assert UUID(hex=suffix).hex == suffix
    assert target["dbname"] == name
    assert connection.info.host == target["host"] == "127.0.0.1"
    port = target.get("port")
    assert isinstance(port, (str, int)) and not isinstance(port, bool)
    assert connection.info.port == int(port)
    assert connection.info.user == target["user"] == "prm_migrator"
    row = connection.execute(
        "SELECT current_database(),current_user,(SELECT version_num FROM alembic_version),"
        "to_regclass('app.invoices') IS NOT NULL,to_regclass('app.invoice_lines') IS NOT NULL,"
        "to_regclass('app.invoice_debit_due_sources') IS NOT NULL,"
        "to_regclass('app.invoice_due_source_parts') IS NOT NULL"
    ).fetchone()
    present = revision == "20260916_62"
    assert row == (name, "prm_migrator", revision, True, True, present, present)


def legacy_financial_snapshot(connection: DB) -> dict[str, list[tuple[object, ...]]]:
    return {
        table: connection.execute(
            sql.SQL("SELECT to_jsonb(row) FROM app.{} row ORDER BY to_jsonb(row)::text").format(
                sql.Identifier(table)
            )
        ).fetchall()
        for table in LEGACY_FINANCIAL_TABLES
    }


def upgrade_populated_due_history(connection: DB) -> dict[str, list[tuple[object, ...]]]:
    assert_legacy_due_target(connection, "20260915_61")
    before = legacy_financial_snapshot(connection)
    connection.commit()
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "20260916_62")
    assert_legacy_due_target(connection, "20260916_62")
    assert legacy_financial_snapshot(connection) == before
    assert connection.execute("SELECT count(*) FROM app.invoice_debit_due_sources").fetchone() == (
        0,
    )
    assert connection.execute("SELECT count(*) FROM app.invoice_due_source_parts").fetchone() == (
        0,
    )
    return before


def legacy_adjustment(
    connection: DB,
    context: tuple[UUID, UUID, UUID, UUID, UUID],
    kind: str,
    amount: int,
) -> tuple[UUID, tuple[object, ...], dict[str, Any]]:
    actor, prop, _, invoice, line = context
    version = connection.execute(
        "SELECT version FROM app.invoices WHERE id=%s", (invoice,)
    ).fetchone()
    assert version is not None
    identifier, key = uuid4(), uuid4()
    parameters: tuple[object, ...] = (
        prop,
        invoice,
        line,
        actor,
        key,
        "c" * 64,
        version[0],
        kind,
        amount,
        f"synthetic-approved-legacy:{key}",
        "Approved synthetic legacy correction",
        identifier,
        uuid4(),
    )
    row = connection.execute(LEGACY_ADJUSTMENT_SQL, parameters).fetchone()
    assert row is not None
    return identifier, parameters, cast(dict[str, Any], row[0])


def assert_legacy_replay_and_new_post_blocked(
    connection: DB,
    context: tuple[UUID, UUID, UUID, UUID, UUID],
    parameters: tuple[object, ...],
    response: dict[str, Any],
    before: dict[str, list[tuple[object, ...]]],
) -> None:
    assert connection.execute(LEGACY_ADJUSTMENT_SQL, parameters).fetchone() == (response,)
    assert legacy_financial_snapshot(connection) == before
    with pytest.raises(psycopg.Error, match="Dated amount evidence must be resolved"):
        with connection.transaction():
            post_due_adjustment(
                connection,
                context,
                "DEBIT",
                100,
                due=date(2027, 4, 9),
                reference="approved/new-source",
            )
    assert legacy_financial_snapshot(connection) == before
    assert connection.execute("SELECT count(*) FROM app.invoice_debit_due_sources").fetchone() == (
        0,
    )
    assert connection.execute("SELECT count(*) FROM app.invoice_due_source_parts").fetchone() == (
        0,
    )
