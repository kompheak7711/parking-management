"""Fresh allocation proposals over isolated current-head PostgreSQL."""

import json
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from payment_test_support import seed_payment
from property_rental.allocation_read import AllocationHistoryPage, AllocationReadService
from property_rental.invoice import (
    CreateInvoiceDraftCommand,
    IssueInvoiceCommand,
    PostgresInvoiceService,
)
from property_rental.payment_allocation import (
    AllocationAuthorizationError,
    AllocationInvalidError,
    AllocationNotFoundError,
    PostAllocationsCommand,
    ReverseAllocationCommand,
)
from test_credit_migration import actor
from test_invoice_migration import (
    financial_database_url,
    invoice_api_actor,
    runtime_database_url,
    set_draft_correction_context,
    setup_invoice_api_source,
)
from test_payment_allocation_migration import service, source
from test_reservation_migration import migrated_database_url  # noqa: F401


def test_allocation_proposal_read_preserves_source_history_and_posts_only_when_confirmed(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, invoices = source(migrated_database_url)
    who = actor(human, prop, "payments.allocate")
    query = (
        "SELECT to_jsonb(p),to_jsonb(r),g.revision,"
        "(SELECT count(*) FROM app.payment_allocations WHERE payment_id=p.id) "
        "FROM app.payments p JOIN app.receipts r ON r.payment_id=p.id "
        "LEFT JOIN app.payment_serialization_guards g ON g.payment_id=p.id WHERE p.id=%s"
    )
    with psycopg.connect(migrated_database_url) as connection:
        before = connection.execute(query, (payment,)).fetchone()
        assert before is not None and before[3] == 0
    proposal = AllocationReadService(runtime_database_url()).proposal(prop, payment, actor=who)
    assert proposal["property_id"] == str(prop) and proposal["payment_id"] == str(payment)
    targets = proposal["targets"]
    assert isinstance(targets, list)
    assert [target["invoice_id"] for target in targets] == [str(invoices[1]), str(invoices[0])]
    assert [target["amount_usd_cents"] for target in targets] == [80_000, 20_000]
    assert proposal["available_usd_cents"] == 100_000
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(query, (payment,)).fetchone() == before
    # The proposal cannot post itself; the unchanged explicit command service
    # validates this exact snapshot and retains its original replay result.
    command = PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal})
    result = service().post(prop, payment, command, actor=who)
    assert result["available_usd_cents"] == 0
    assert service().post(prop, payment, command, actor=who) == result
    with psycopg.connect(migrated_database_url) as connection:
        after = connection.execute(query, (payment,)).fetchone()
        assert after is not None and after[:2] == before[:2] and after[3] == 2


def test_allocation_proposal_read_rejects_stale_disabled_actor_without_effects(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, _ = source(migrated_database_url)
    who = actor(human, prop, "payments.allocate")
    reader = AllocationReadService(runtime_database_url())
    assert reader.proposal(prop, payment, actor=who)["payment_id"] == str(payment)
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (human,)
        )
    with pytest.raises(AllocationAuthorizationError):
        reader.proposal(prop, payment, actor=who)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.payment_allocations WHERE payment_id=%s", (payment,)
        ).fetchone() == (0,)


def test_allocation_proposal_read_denies_cross_property_missing_payment_and_wrong_capability(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, _ = source(migrated_database_url)
    reader = AllocationReadService(runtime_database_url())
    for who in (actor(human, prop, "payments.read"), actor(human, uuid4(), "payments.allocate")):
        with pytest.raises(AllocationAuthorizationError):
            reader.proposal(prop, payment, actor=who)
    with pytest.raises(AllocationNotFoundError):
        reader.proposal(prop, uuid4(), actor=actor(human, prop, "payments.allocate"))
    missing = uuid4()
    with pytest.raises(AllocationNotFoundError):
        reader.proposal(missing, payment, actor=actor(human, missing, "payments.allocate"))


def test_allocation_history_pages_preserve_posted_facts_and_linked_reversals(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, _ = source(migrated_database_url)
    who = actor(human, prop, "payments.read", "payments.allocate", "payments.allocations.reverse")
    reader = AllocationReadService(runtime_database_url())
    assert reader.history(prop, payment, actor=who)["items"] == []
    proposal = reader.proposal(prop, payment, actor=who)
    posted = service().post(
        prop,
        payment,
        PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
        actor=who,
    )
    first = reader.history(prop, payment, AllocationHistoryPage(1), actor=who)
    cursor = cast(dict[str, object], first["next_cursor"])
    second = reader.history(
        prop, payment, AllocationHistoryPage(1, UUID(str(cursor["after_id"]))), actor=who
    )
    assert second["next_cursor"] is None
    items = cast(list[dict[str, object]], first["items"]) + cast(
        list[dict[str, object]], second["items"]
    )
    assert len(items) == 2 and {row["id"] for row in items} == set(
        cast(list[str], posted["allocation_ids"])
    )
    assert sum(cast(int, row["amount_usd_cents"]) for row in items) == 100_000
    assert all("proposal_trace" not in row and row["reversal"] is None for row in items)
    selected = UUID(str(items[0]["id"]))
    evidence = reader.history(prop, payment, actor=who, allocation_id=selected)
    original = cast(dict[str, object], evidence["allocation"])
    assert original["proposal_trace"] == proposal
    assert original["detail_count"] == len(cast(list[object], evidence["items"])) == 1
    reversal = service().reverse_allocation(
        prop, selected, ReverseAllocationCommand(uuid4(), "Correct target"), actor=who
    )
    changed = reader.history(prop, payment, actor=who, allocation_id=selected)
    after = cast(dict[str, object], changed["allocation"])
    assert {key: value for key, value in after.items() if key != "reversal"} == {
        key: value for key, value in original.items() if key != "reversal"
    }
    assert cast(dict[str, object], after["reversal"])["id"] == reversal["reversal_id"]
    assert changed["items"] == evidence["items"]


def test_allocation_history_scope_and_cursor_anchors_cannot_cross_resources(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, _ = source(migrated_database_url)
    other_human, other_prop, other_payment, _ = source(migrated_database_url)
    reader = AllocationReadService(runtime_database_url())
    other = actor(other_human, other_prop, "payments.allocate", "payments.read")
    posted = service().post(
        other_prop,
        other_payment,
        PostAllocationsCommand(
            uuid4(),
            {
                "mode": "PROPOSAL",
                "proposal": reader.proposal(other_prop, other_payment, actor=other),
            },
        ),
        actor=other,
    )
    foreign = UUID(cast(list[str], posted["allocation_ids"])[0])
    who = actor(human, prop, "payments.read")
    # The canonical database has one Property; separate Customers remain
    # readable within the same authorized Property. Test the actual boundary.
    assert prop == other_prop
    assert reader.history(prop, other_payment, actor=who)["payment_id"] == str(other_payment)
    missing_property = uuid4()
    with pytest.raises(AllocationNotFoundError):
        reader.history(
            missing_property,
            other_payment,
            actor=actor(human, missing_property, "payments.read"),
        )
    with pytest.raises(AllocationAuthorizationError):
        reader.history(prop, other_payment, actor=actor(human, uuid4(), "payments.read"))
    with pytest.raises(AllocationNotFoundError):
        reader.history(prop, payment, actor=who, allocation_id=foreign)
    with pytest.raises(AllocationInvalidError):
        reader.history(prop, payment, AllocationHistoryPage(1, foreign), actor=who)
    with pytest.raises(AllocationInvalidError):
        reader.history(
            other_prop,
            other_payment,
            AllocationHistoryPage(1, uuid4()),
            actor=other,
            allocation_id=foreign,
        )
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s",
            (other_human,),
        )
    for selected in (None, foreign):
        with pytest.raises(AllocationAuthorizationError):
            reader.history(other_prop, other_payment, actor=other, allocation_id=selected)


def large_history_source(
    database_url: str,
) -> tuple[UUID, UUID, UUID, dict[str, object]]:
    # Use only valid authorized obligations. The accepted producer's 500-detail
    # ceiling creates a large real proposal and forces several evidence pages.
    with psycopg.connect(database_url) as connection:
        human, prop, customer, first_source = setup_invoice_api_source(
            connection, amount_usd_cents=1, source_reference="history-bound"
        )
        sources = [uuid4() for _ in range(499)]
        for index, source_id in enumerate(sources):
            connection.execute(
                "INSERT INTO app.authorized_nonrecurring_obligations "
                "(id,customer_id,category,description,authorized_amount_usd_cents,"
                "governing_due_date,due_date_source,source_reference,authorized_at,authorized_by,"
                "authorization_reference) "
                "VALUES (%s,%s,'MISCELLANEOUS_CHARGES','History detail',1,"
                "current_date+14,'history-bound',%s,clock_timestamp(),%s,"
                "'invoice.nonrecurring.authorize')",
                (source_id, customer, f"history-bound/{index}", human),
            )
    invoices = PostgresInvoiceService(runtime_database_url(), financial_database_url())
    draft = invoices.create_draft(
        prop, CreateInvoiceDraftCommand(uuid4(), first_source), actor=invoice_api_actor(human, prop)
    )
    invoice = UUID(str(draft["id"]))
    with psycopg.connect(database_url) as connection:
        set_draft_correction_context(
            connection, actor_id=human, reason="Add authorized history test obligations"
        )
        connection.execute(
            "UPDATE app.invoices SET original_total_usd_cents=500,version=version+1,"
            "updated_at=clock_timestamp(),updated_by=%s WHERE id=%s",
            (human, invoice),
        )
        for index, source_id in enumerate(sources, 2):
            connection.execute(
                "INSERT INTO app.invoice_lines (id,invoice_id,line_sequence,category,description,"
                "amount_usd_cents,authorized_obligation_id,calculation_trace,created_by) "
                "VALUES (%s,%s,%s,'MISCELLANEOUS_CHARGES','History detail',1,%s,%s,%s)",
                (
                    uuid4(),
                    invoice,
                    index,
                    source_id,
                    Jsonb(
                        {
                            "formula": "authorized_source_exact_amount",
                            "authorized_obligation_id": str(source_id),
                            "authorized_amount_usd_cents": 1,
                        }
                    ),
                    human,
                ),
            )
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=500
        )
    invoices.issue(
        prop, invoice, IssueInvoiceCommand(uuid4(), 2), actor=invoice_api_actor(human, prop)
    )
    who = actor(human, prop, "payments.read", "payments.allocate")
    reader = AllocationReadService(runtime_database_url())
    proposal = reader.proposal(prop, payment, actor=who)
    return human, prop, payment, proposal


def test_allocation_history_full_size_proposal_and_all_details_are_accessible_without_mutation(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, proposal = large_history_source(migrated_database_url)
    who = actor(human, prop, "payments.read", "payments.allocate")
    reader = AllocationReadService(runtime_database_url())
    # The accepted maximum detail count is 500; its genuine proposal is
    # already larger than the Payment HTTP cap that this slice must not reuse.
    assert len(json.dumps(proposal).encode()) > 32_768
    targets = cast(list[dict[str, object]], proposal["targets"])
    assert len(cast(list[object], targets[0]["details"])) == 500
    posted = service().post(
        prop,
        payment,
        PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
        actor=who,
    )
    selected = UUID(cast(list[str], posted["allocation_ids"])[0])
    snapshot_sql = (
        "SELECT to_jsonb(payment),to_jsonb(receipt),guard.revision FROM app.payments payment "
        "JOIN app.receipts receipt ON receipt.payment_id=payment.id "
        "JOIN app.payment_serialization_guards guard ON guard.payment_id=payment.id "
        "WHERE payment.id=%s"
    )
    with psycopg.connect(migrated_database_url) as connection:
        before = connection.execute(snapshot_sql, (payment,)).fetchone()
        expected = connection.execute(
            "SELECT to_jsonb(detail) FROM app.payment_allocation_details detail "
            "WHERE payment_allocation_id=%s ORDER BY detail_sequence,id",
            (selected,),
        ).fetchall()
    summaries = reader.history(prop, payment, actor=who)
    assert len(json.dumps(summaries).encode()) < 5_000
    details: list[dict[str, object]] = []
    after_id = None
    for _ in range(5):
        page = reader.history(
            prop, payment, AllocationHistoryPage(100, after_id), actor=who, allocation_id=selected
        )
        assert cast(dict[str, object], page["allocation"])["proposal_trace"] == proposal
        assert len(json.dumps(page).encode()) < 1_048_576
        details.extend(cast(list[dict[str, object]], page["items"]))
        cursor = page["next_cursor"]
        after_id = UUID(str(cast(dict[str, object], cursor)["after_id"])) if cursor else None
    assert after_id is None and len(details) == 500
    assert details == [row[0] for row in expected]
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(snapshot_sql, (payment,)).fetchone() == before
