"""Actual action-only reversal context, complete pages and guarded financial reads."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from time import monotonic
from typing import Literal, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import sql

from deposit_disposition_test_support import disposition_context, terminate_for_disposition
from deposit_receipt_reversal_test_support import reverse_receipt_as_owner
from lease_deposit_forfeiture_test_support import (
    record_disposition_as_owner,
    reverse_disposition_as_owner,
)
from payment_test_support import seed_deposit_payment, seed_payment
from pre_settlement_test_support import pre_settlement_database  # noqa: F401
from property_rental.credit import ReverseCreditApplicationCommand, ReverseCreditCommand
from property_rental.deposit import (
    PostgresDepositService,
    RecordDepositDispositionCommand,
    ReverseDepositDispositionCommand,
    ReverseDepositReceiptCommand,
)
from property_rental.financial_reference import FinancialReferenceService
from property_rental.identity import AuthenticatedActor
from property_rental.late_payment import (
    CorrectionKind,
    CorrectLatePaymentChargeCommand,
    DecisionOutcome,
    FinalizeLatePaymentDecisionCommand,
)
from property_rental.payment_allocation import (
    PostAllocationsCommand,
    ReverseAllocationCommand,
    ReversePaymentCommand,
)
from property_rental.payment_read import (
    PaymentReadAuthorizationError,
    PaymentReadInvalidError,
    PaymentReadNotFoundError,
    PaymentReadService,
    PaymentReadUnavailableError,
)
from property_rental.payment_reversal_context import (
    PaymentReversalContextChanged,
    PaymentReversalContextService,
    ReversalContextPage,
)
from property_rental.refund import ReverseRefundCorrectionCommand
from refund_test_support import create_pet_refund, create_usd_refund
from test_credit_application_migration import application_id, designated
from test_credit_application_migration import source as application_source
from test_credit_migration import actor, credit_id, recognize, source
from test_credit_migration import service as credits
from test_deposit_migration import create_pet, setup_signed_pet_lease
from test_invoice_migration import register_billing_service_principal, runtime_database_url
from test_late_payment_migration import late_payment_actor, setup_invoice
from test_late_payment_migration import service as late_service
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated as allocate_line
from test_payment_allocation_migration import service as allocations
from test_payment_allocation_migration import source as allocation_source
from test_payment_migration import fx_payment
from test_pet_refund_migration import command as pet_refund
from test_pet_refund_migration import qualified
from test_refund_service_migration import corrections, create, refund_id, returned
from test_refund_service_migration import service as refunds
from test_reservation_migration import migrated_database_url  # noqa: F401


def reader() -> PaymentReversalContextService:
    return PaymentReversalContextService(runtime_database_url())


def get(
    human: UUID,
    prop: UUID,
    payment: UUID,
    view: Literal["impact", "result"] = "impact",
    limit: int = 100,
    cursor: str | None = None,
) -> dict[str, object]:
    return reader().get(
        prop,
        payment,
        ReversalContextPage(view, limit, cursor),
        actor=actor(human, prop, "payments.reverse"),
    )


def data(result: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], result["data"])


def items(result: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], data(result)["items"])


def payload(item: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], item["data"])


def snapshot(url: str) -> dict[str, object]:
    tables = (
        "payments",
        "receipts",
        "payment_reversals",
        "payment_allocations",
        "payment_allocation_details",
        "payment_allocation_reversals",
        "customer_credits",
        "customer_credit_reversals",
        "customer_credit_applications",
        "customer_credit_application_details",
        "customer_credit_application_reversals",
        "deposit_receipts",
        "deposit_receipt_reversals",
        "deposit_dispositions",
        "deposit_disposition_reversals",
        "refunds",
        "refund_corrections",
        "payment_serialization_guards",
        "deposit_serialization_guards",
        "invoice_serialization_guards",
        "audit_events",
    )
    with psycopg.connect(url) as connection:
        return {
            table: connection.execute(
                sql.SQL(
                    "SELECT count(*),md5(COALESCE(jsonb_agg(to_jsonb(t) "
                    "ORDER BY to_jsonb(t)::text)::text,'[]')) FROM app.{} t"
                ).format(sql.Identifier(table))
            ).fetchone()
            for table in tables
        }


def test_payment_reversal_context_database_action_only_original_fx_and_no_writes(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        payment = fx_payment(connection, channel=True, channel_rate=Decimal("4100.123456"))
        row = connection.execute(
            "SELECT confirmed_by,property_id FROM app.payments WHERE id=%s", (payment,)
        ).fetchone()
        assert row is not None
        human, prop = row
    before = snapshot(migrated_database_url)
    original = PaymentReadService(runtime_database_url()).get(
        prop, payment, actor=actor(human, prop, "payments.read")
    )
    for view in ("impact", "result"):
        result = get(human, prop, payment, view)
        assert data(result)["payment_resource"] == original
        assert items(result) == [] and result["next_cursor"] is None
        assert len(str(data(result)["revision"])) == 64
    assert snapshot(migrated_database_url) == before


def test_payment_reversal_context_database_allocation_impact_unwind_and_historical_results(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, invoices = allocation_source(migrated_database_url)
    staff = allocation_actor(human, prop)
    proposal = allocations().proposal(prop, payment, actor=staff)
    posted = allocations().post(
        prop,
        payment,
        PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
        actor=staff,
    )
    original = data(get(human, prop, payment))["payment_resource"]
    impact = items(get(human, prop, payment))
    assert [x["kind"] for x in impact] == ["ALLOCATION"] * 2 + ["ALLOCATION_LINE"] * 2
    assert {x["id"] for x in impact[:2]} == set(cast(list[str], posted["allocation_ids"]))
    assert sum(cast(int, payload(x)["amount_usd_cents"]) for x in impact[:2]) == 100000
    assert {payload(x)["source_id"] for x in impact[:2]} == {str(payment)}
    current = items(get(human, prop, payment, "result"))
    assert {x["id"]: payload(x)["outstanding_usd_cents"] for x in current} == {
        str(invoices[0]): 60000,
        str(invoices[1]): 0,
    }
    first = get(human, prop, payment, limit=1)
    for identity in cast(list[str], posted["allocation_ids"]):
        allocations().reverse_allocation(
            prop,
            UUID(identity),
            ReverseAllocationCommand(uuid4(), "Resolve original assignment"),
            actor=staff,
        )
    with pytest.raises(PaymentReversalContextChanged):
        get(human, prop, payment, limit=1, cursor=str(first["next_cursor"]))
    allocations().reverse_payment(
        prop, payment, ReversePaymentCommand(uuid4(), "Correct original receipt"), actor=staff
    )
    assert items(get(human, prop, payment)) == []
    after = get(human, prop, payment, "result")
    assert {x["id"]: payload(x)["outstanding_usd_cents"] for x in items(after)} == {
        str(i): 80000 for i in invoices
    }
    resource = cast(dict[str, object], data(after)["payment_resource"])
    assert cast(dict[str, object], resource["payment"])["status"] == "REVERSED"
    assert resource["receipt"] == cast(dict[str, object], original)["receipt"]


def test_payment_reversal_context_database_credit_application_dependencies_and_results(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, credit, invoice, line, payment = application_source(migrated_database_url)
    app = application_id(
        credits().apply(
            prop, credit, designated(invoice, line, 1000), actor=actor(human, prop, "credits.apply")
        )
    )
    current = get(human, prop, payment)
    assert [x["kind"] for x in items(current)] == [
        "CREDIT",
        "CREDIT_APPLICATION",
        "CREDIT_APPLICATION_LINE",
    ]
    assert payload(items(current)[1])["source_id"] == str(credit)
    assert payload(items(current)[2])["source_id"] == str(app)
    assert payload(items(current)[2])["target_id"] == str(line)
    first = get(human, prop, payment, limit=1)
    credits().reverse_application(
        prop,
        app,
        ReverseCreditApplicationCommand(uuid4(), "Correct application"),
        actor=actor(human, prop, "credits.applications.reverse"),
    )
    with pytest.raises(PaymentReversalContextChanged):
        get(human, prop, payment, limit=1, cursor=str(first["next_cursor"]))
    credits().reverse(
        prop,
        credit,
        ReverseCreditCommand(uuid4(), "Resolve original credit"),
        actor=actor(human, prop, "credits.reverse"),
    )
    assert items(get(human, prop, payment)) == []
    final = items(get(human, prop, payment, "result"))
    assert [x["kind"] for x in final] == ["INVOICE", "CREDIT"]
    assert final[0]["id"] == str(invoice) and payload(final[0])["outstanding_usd_cents"] == 80000
    assert payload(final[1]) == {
        "recognized_usd_cents": 100000,
        "applied_usd_cents": 0,
        "refunded_usd_cents": 0,
        "reversed_usd_cents": 100000,
        "available_usd_cents": 0,
    }


@pytest.mark.parametrize("kind", ["PAYMENT", "CREDIT"])
def test_payment_reversal_context_database_partial_full_refund_returns_and_correction_reversal(
    migrated_database_url: str,  # noqa: F811
    kind: str,
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    source_id = credit_id(recognize(prop, payment, human)) if kind == "CREDIT" else payment
    staff = actor(human, prop, "refunds.create", "refunds.correct", "refunds.corrections.reverse")
    result = create_usd_refund(refunds(), prop, create(source_id, kind=kind), actor=staff)
    refund = refund_id(result)

    def net() -> int | None:
        found = [x for x in items(get(human, prop, payment)) if x["kind"] == "REFUND"]
        if not found:
            return None
        assert len(found) == 1 and found[0]["id"] == str(refund)
        assert payload(found[0])["source_id"] == str(source_id)
        assert payload(found[0])["amount_usd_cents"] == 8000
        return cast(int, payload(found[0])["unreturned_usd_cents"])

    assert net() == 8000
    old_revision = data(get(human, prop, payment))["revision"]
    corrected = refunds().verify_usd_return(prop, refund, returned(), actor=staff)
    assert net() == 4000 and data(get(human, prop, payment))["revision"] != old_revision
    refunds().verify_usd_return(prop, refund, returned(), actor=staff)
    assert net() is None
    correction = UUID(str(corrections(corrected)[0]["id"]))
    refunds().reverse_correction(
        prop,
        refund,
        correction,
        ReverseRefundCorrectionCommand(uuid4(), "Reviewed evidence", "Correct return entry"),
        actor=staff,
    )
    assert net() == 4000


def test_payment_reversal_context_database_complete_large_pages_and_revision_change(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url, 20000)
    ids = {str(credit_id(recognize(prop, payment, human, 1))) for _ in range(105)}
    before = snapshot(migrated_database_url)
    first = get(human, prop, payment)
    assert len(items(first)) == 100 and first["next_cursor"] is not None
    last = get(human, prop, payment, cursor=str(first["next_cursor"]))
    assert len(items(last)) == 5 and last["next_cursor"] is None
    assert {x["id"] for x in items(first) + items(last)} == ids
    assert data(first)["revision"] == data(last)["revision"]
    assert snapshot(migrated_database_url) == before
    recognize(prop, payment, human, 1)
    with pytest.raises(PaymentReversalContextChanged):
        get(human, prop, payment, cursor=str(first["next_cursor"]))


def test_payment_reversal_context_database_other_payment_target_change_invalidates_result(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, credit, invoice, line, payment = application_source(migrated_database_url)
    credits().apply(
        prop, credit, designated(invoice, line, 1000), actor=actor(human, prop, "credits.apply")
    )
    before = get(human, prop, payment, "result", limit=1)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT payer_customer_id FROM app.payments WHERE id=%s", (payment,)
        ).fetchone()
        assert row is not None
        other = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=row[0], amount=1000
        )
    allocations().post(
        prop, other, allocate_line(invoice, line, 1000), actor=allocation_actor(human, prop)
    )
    with pytest.raises(PaymentReversalContextChanged):
        get(human, prop, payment, "result", limit=1, cursor=str(before["next_cursor"]))
    assert payload(items(get(human, prop, payment, "result"))[0])["outstanding_usd_cents"] == 78000


@pytest.mark.parametrize("kind", ["missing", "disabled", "service"])
def test_payment_reversal_context_database_fresh_actor_precedes_source(
    migrated_database_url: str,  # noqa: F811
    kind: str,
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        if kind == "disabled":
            connection.execute(
                "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s",
                (human,),
            )
        elif kind == "service":
            human = register_billing_service_principal(
                connection, property_id=prop, created_by=human
            )
        else:
            human = uuid4()
    before = snapshot(migrated_database_url)
    for identity in (payment, uuid4()):
        with pytest.raises(PaymentReadAuthorizationError):
            get(human, prop, identity)
    assert snapshot(migrated_database_url) == before


def test_payment_reversal_context_database_missing_property_source_and_cursor(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    with pytest.raises(PaymentReadNotFoundError):
        get(human, uuid4(), payment)
    with pytest.raises(PaymentReadNotFoundError):
        get(human, prop, uuid4())
    revision = data(get(human, prop, payment))["revision"]
    with pytest.raises(PaymentReadInvalidError):
        get(human, prop, payment, cursor=f"{revision}:1:{uuid4()}")


def test_payment_reversal_context_database_migration_privileges_and_readonly_transaction(
    migrated_database_url: str,  # noqa: F811
) -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    assert scripts.get_heads() == ["20270402_252"]
    revision = scripts.get_revision("20260908_46")
    assert revision is not None and revision.down_revision == "20260907_45"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    signature = "app.payment_reversal_context_page(uuid,uuid,uuid,text,integer,integer,uuid)"
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT prosecdef,provolatile,proconfig FROM pg_proc WHERE oid=%s::regprocedure",
            (signature,),
        ).fetchone()
        assert row is not None and row[:2] == (True, "s") and "search_path=pg_catalog" in row[2]
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
            assert connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)
            ).fetchone() == (role == "prm_runtime",)
        for table in (
            "customer_credits",
            "customer_credit_applications",
            "credit_commands",
            "refund_commands",
        ):
            assert connection.execute(
                "SELECT has_table_privilege('prm_runtime',%s,"
                "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')",
                (f"app.{table}",),
            ).fetchone() == (False,)
    human, prop, _, payment = source(migrated_database_url)
    with psycopg.connect(runtime_database_url()) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        row = connection.execute(
            "SELECT app.payment_reversal_context_page(%s,%s,%s,'impact',100,NULL,NULL)",
            (prop, payment, human),
        ).fetchone()
        assert row is not None and row[0]["items"] == []


def deposit_source(
    url: str,
) -> tuple[PostgresDepositService, AuthenticatedActor, UUID, UUID, UUID, list[UUID]]:
    service, staff, lease, approval, day = setup_signed_pet_lease(url)
    deposit, _ = create_pet(service, staff, lease, approval, day)
    with psycopg.connect(url) as connection:
        payment = seed_deposit_payment(
            connection, deposit_id=deposit, actor_id=service.actor_id, amount=20000
        )
        receipts = [uuid4(), uuid4()]
        for index, receipt in enumerate(receipts):
            receipt_payment = (
                payment
                if index == 0
                else seed_deposit_payment(
                    connection, deposit_id=deposit, actor_id=service.actor_id, amount=10000
                )
            )
            connection.execute(
                "INSERT INTO app.deposit_receipts(id,deposit_id,payment_"
                "id,amount_usd_cents,occurred_at,actor_id) VALUES (%s,%s"
                ",%s,10000,clock_timestamp(),%s)",
                (receipt, deposit, receipt_payment, service.actor_id),
            )
    return service, staff, lease, deposit, payment, receipts


def test_payment_reversal_context_database_shared_deposit_descendants_deduplicated_and_guarded(
    migrated_database_url: str,  # noqa: F811
) -> None:
    service, staff, lease, deposit, payment, receipts = deposit_source(migrated_database_url)
    human, prop = service.actor_id, service.property_id
    initial = get(human, prop, payment, limit=1)
    initial_cursor = f"{data(initial)['revision']}:6:{receipts[0]}"
    terminate_for_disposition(migrated_database_url, service, lease, date.today())
    disposition = RecordDepositDispositionCommand(
        uuid4(),
        uuid4(),
        deposit,
        lease,
        5000,
        date.today(),
        "Approved Lease outcome",
        context=disposition_context(migrated_database_url, deposit),
    )
    record_disposition_as_owner(service, disposition, actor=staff)
    with pytest.raises(PaymentReversalContextChanged):
        get(human, prop, payment, limit=1, cursor=initial_cursor)
    impact = items(get(human, prop, payment))
    assert [x["kind"] for x in impact] == [
        "DEPOSIT_RECEIPT",
        "DEPOSIT_DISPOSITION",
    ]
    assert impact[1]["id"] == str(disposition.disposition_id)
    position = items(get(human, prop, payment, "result"))
    assert len(position) == 1 and position[0]["id"] == str(deposit)
    assert payload(position[0])["held_usd_cents"] == 15000
    before = get(human, prop, payment, limit=1)
    reverse_disposition_as_owner(
        service,
        ReverseDepositDispositionCommand(
            uuid4(), uuid4(), disposition.disposition_id, "Correct evidence", "CASE-052"
        ),
        actor=staff,
    )
    with pytest.raises(PaymentReversalContextChanged):
        get(human, prop, payment, limit=1, cursor=str(before["next_cursor"]))
    before = get(human, prop, payment, limit=1)
    receipt_cursor = f"{data(before)['revision']}:6:{receipts[0]}"
    for receipt in receipts:
        reverse_receipt_as_owner(
            service,
            ReverseDepositReceiptCommand(uuid4(), uuid4(), receipt, "Correct source receipt"),
            actor=staff,
        )
    with pytest.raises(PaymentReversalContextChanged):
        get(human, prop, payment, limit=1, cursor=receipt_cursor)
    assert items(get(human, prop, payment)) == []
    final = items(get(human, prop, payment, "result"))
    assert len(final) == 1 and payload(final[0]) == {
        "deposit_type": "PET",
        "held_usd_cents": 0,
        "received_usd_cents": 0,
        "disposed_usd_cents": 0,
        "refunded_usd_cents": 0,
    }


def test_payment_reversal_context_database_pet_refund_and_return_use_deposit_revision(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, _, deposit, review = qualified(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT payment_id FROM app.deposit_receipts WHERE deposit_id=%s", (deposit,)
        ).fetchone()
        assert row is not None
        payment = row[0]
    staff = actor(human, prop, "refunds.create", "refunds.correct", "refunds.corrections.reverse")
    original = data(get(human, prop, payment))["revision"]
    result = create_pet_refund(refunds(), prop, pet_refund(deposit, review), actor=staff)
    assert data(get(human, prop, payment))["revision"] != original
    first = get(human, prop, payment, limit=1)
    children = items(get(human, prop, payment))
    assert [x["kind"] for x in children] == ["DEPOSIT_RECEIPT", "REFUND"]
    assert payload(children[1])["source_id"] == str(deposit)
    refund = refund_id(result)
    corrected = refunds().verify_usd_return(prop, refund, returned(15000), actor=staff)
    with pytest.raises(PaymentReversalContextChanged):
        get(human, prop, payment, limit=1, cursor=str(first["next_cursor"]))
    assert [x["kind"] for x in items(get(human, prop, payment))] == ["DEPOSIT_RECEIPT"]
    assert payload(items(get(human, prop, payment, "result"))[0])["held_usd_cents"] == 20000
    correction = UUID(str(corrections(corrected)[0]["id"]))
    refunds().reverse_correction(
        prop,
        refund,
        correction,
        ReverseRefundCorrectionCommand(uuid4(), "Reviewed evidence", "Correct return entry"),
        actor=staff,
    )
    assert payload(items(get(human, prop, payment))[-1])["unreturned_usd_cents"] == 15000
    assert payload(items(get(human, prop, payment, "result"))[0])["held_usd_cents"] == 5000


@pytest.mark.parametrize("historical", [False, True])
def test_payment_reversal_context_database_unsupported_future_application_is_explicit(
    pre_settlement_database: str,  # noqa: F811
    historical: bool,
) -> None:
    # V1-056 sub-slice 8a-1: migration 86 creates app.deposit_applications, so this contract test
    # of the forward check now runs on the schema before it (revision 20261020_85); every
    # assertion is unchanged. The head behavior is tested in test_final_settlement_migration.
    url = pre_settlement_database
    service, staff, _, deposit, payment, receipts = deposit_source(url)
    if historical:
        for receipt in receipts:
            reverse_receipt_as_owner(
                service,
                ReverseDepositReceiptCommand(uuid4(), uuid4(), receipt, "Resolve source"),
                actor=staff,
            )
    with psycopg.connect(url) as connection:
        assert connection.execute("SELECT to_regclass('app.deposit_applications')").fetchone() == (
            None,
        )
        connection.execute(
            "CREATE TABLE app.deposit_applications(id uuid PRIMARY KEY,deposit_id uuid NOT NULL)"
        )
        connection.execute(
            "INSERT INTO app.deposit_applications VALUES (%s,%s)", (uuid4(), deposit)
        )
        for view in ("impact", "result"):
            row = connection.execute(
                "SELECT app.payment_reversal_context_page(%s,%s,%s,%s,100,NULL,NULL)",
                (service.property_id, payment, service.actor_id, view),
            ).fetchone()
            assert row is not None and row[0]["unsupported_application"] is (
                view == "result" or not historical
            )
        # Future schema is synthetic and never committed, even if an assertion fails.
        connection.rollback()
        assert connection.execute("SELECT to_regclass('app.deposit_applications')").fetchone() == (
            None,
        )


def test_payment_reversal_context_database_charge_result_matches_authoritative_position(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, invoice, _ = setup_invoice(connection, period_start=date(2026, 5, 1))
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=10000
        )
    late_service().finalize_decision(
        prop,
        invoice,
        FinalizeLatePaymentDecisionCommand(
            uuid4(), DecisionOutcome.CONFIRMED_DEFAULT, 8000, "Confirm default late charge"
        ),
        actor=late_payment_actor(human, prop),
    )
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT id FROM app.late_payment_charges WHERE source_invoice_id=%s", (invoice,)
        ).fetchone()
        assert row is not None
        charge = row[0]
    posted = allocations().post(
        prop,
        payment,
        PostAllocationsCommand(
            uuid4(),
            {
                "mode": "DIRECT_CHARGE",
                "late_payment_charge_id": str(charge),
                "amount_usd_cents": 4000,
            },
        ),
        actor=allocation_actor(human, prop),
    )
    initial = data(get(human, prop, payment, "result"))["revision"]
    late_service().correct_charge(
        prop,
        charge,
        CorrectLatePaymentChargeCommand(
            uuid4(), CorrectionKind.REDUCTION, "Reduce eligible value", 1000
        ),
        actor=late_payment_actor(human, prop),
    )
    result = get(human, prop, payment, "result")
    assert data(result)["revision"] != initial
    assert len(items(result)) == 1 and items(result)[0]["kind"] == "LATE_PAYMENT_CHARGE"
    position = payload(items(result)[0])
    assert position["source_invoice_id"] == str(invoice) and position["original_usd_cents"] == 8000
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT adjusted_obligation_usd_cents,remaining_balance_"
            "usd_cents FROM app.late_payment_charge_financial_positi"
            "on WHERE late_payment_charge_id=%s",
            (charge,),
        ).fetchone()
        assert (
            row
            == (position["adjusted_obligation_usd_cents"], position["remaining_balance_usd_cents"])
            == (7000, 3000)
        )
        assert connection.execute(
            "SELECT status FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone() == ("UNPAID",)
    allocation = UUID(str(cast(list[str], posted["allocation_ids"])[0]))
    allocations().reverse_allocation(
        prop,
        allocation,
        ReverseAllocationCommand(uuid4(), "Resolve assignment"),
        actor=allocation_actor(human, prop),
    )
    late_service().correct_charge(
        prop,
        charge,
        CorrectLatePaymentChargeCommand(
            uuid4(), CorrectionKind.CHARGE_REVERSAL, "Reverse charge", None
        ),
        actor=late_payment_actor(human, prop),
    )
    final = payload(items(get(human, prop, payment, "result"))[0])
    assert final["reversed"] is True and final["remaining_balance_usd_cents"] == 0


def test_payment_reversal_context_database_coherent_snapshot_during_new_refund(
    migrated_database_url: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    original = get(human, prop, payment)
    read = FinancialReferenceService._read

    @contextmanager
    def interleaved(
        self: FinancialReferenceService, who: AuthenticatedActor, property_id: UUID | None = None
    ) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
        with read(self, who, property_id) as connection:
            create_usd_refund(
                refunds(), prop, create(payment, 1000), actor=actor(human, prop, "refunds.create")
            )
            yield connection

    with monkeypatch.context() as current:
        current.setattr(FinancialReferenceService, "_read", interleaved)
        assert get(human, prop, payment) == original
    changed = get(human, prop, payment)
    assert data(changed)["revision"] != data(original)["revision"] and len(items(changed)) == 1


def test_payment_reversal_context_database_statement_deadline_is_unavailable(
    migrated_database_url: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    monkeypatch.setattr(
        "property_rental.payment_reversal_context._DETAIL",
        "SELECT pg_sleep(6) WHERE %s::uuid IS NOT NULL AND %s::uuid IS NOT NULL",
    )
    started = monotonic()
    with pytest.raises(PaymentReadUnavailableError):
        get(human, prop, payment)
    assert 4.5 <= monotonic() - started < 8


def test_payment_reversal_context_database_void_invoice_has_zero_current_balance(
    migrated_database_url: str,  # noqa: F811
) -> None:
    from property_rental.invoice import PostgresInvoiceService, VoidInvoiceCommand
    from test_invoice_migration import financial_database_url, invoice_api_actor

    human, prop, credit, invoice, line, payment = application_source(migrated_database_url)
    application = application_id(
        credits().apply(
            prop,
            credit,
            designated(invoice, line, 1000),
            actor=actor(human, prop, "credits.apply"),
        )
    )
    credits().reverse_application(
        prop,
        application,
        ReverseCreditApplicationCommand(uuid4(), "Resolve attribution"),
        actor=actor(human, prop, "credits.applications.reverse"),
    )
    before = get(human, prop, payment, "result", limit=1)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT version FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
        assert row is not None
        version = row[0]
    authoritative = PostgresInvoiceService(runtime_database_url(), financial_database_url()).void(
        prop,
        invoice,
        VoidInvoiceCommand(uuid4(), "Correct original issued invoice", version),
        actor=invoice_api_actor(human, prop),
    )
    with pytest.raises(PaymentReversalContextChanged):
        get(human, prop, payment, "result", limit=1, cursor=str(before["next_cursor"]))
    result = payload(items(get(human, prop, payment, "result"))[0])
    assert result["status"] == authoritative["status"] == "VOID"
    assert (
        result["outstanding_usd_cents"]
        == cast(dict[str, object], authoritative["outstanding_balance"])["minor_units"]
        == 0
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT original_total_usd_cents FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone() == (80000,)
