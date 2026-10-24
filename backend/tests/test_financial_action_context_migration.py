"""Selected financial facts on isolated PostgreSQL using existing action grants."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from time import monotonic
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from deposit_receipt_reversal_test_support import reverse_receipt_as_owner
from payment_test_support import seed_payment
from pre_settlement_test_support import pre_settlement_database  # noqa: F401
from property_rental.credit import (
    ApplyCreditCommand,
    ReverseCreditApplicationCommand,
    ReverseCreditCommand,
)
from property_rental.deposit import ReverseDepositReceiptCommand
from property_rental.financial_action_context import (
    ACTION_CAPABILITIES,
    FinancialActionContextChanged,
    FinancialActionContextRequest,
    FinancialActionContextService,
)
from property_rental.financial_reference import FinancialReferenceService
from property_rental.identity import AuthenticatedActor
from property_rental.invoice import (
    AdjustInvoiceCommand,
    AdjustmentType,
    CreateInvoiceDraftCommand,
    PostgresInvoiceService,
    VoidInvoiceCommand,
)
from property_rental.late_payment import (
    CorrectionKind,
    CorrectLatePaymentChargeCommand,
    DecisionOutcome,
    FinalizeLatePaymentDecisionCommand,
)
from property_rental.payment_allocation import PostAllocationsCommand, ReverseAllocationCommand
from property_rental.payment_read import (
    PaymentReadAuthorizationError,
    PaymentReadNotFoundError,
    PaymentReadService,
    PaymentReadUnavailableError,
)
from property_rental.refund import ReverseRefundCorrectionCommand
from refund_test_support import create_pet_refund, create_usd_refund
from reservation_deposit_test_support import correct_reservation_outcome
from test_allocation_read_migration import large_history_source
from test_credit_application_migration import application_id, designated
from test_credit_application_migration import source as application_source
from test_credit_migration import actor, credit_id, recognize, source
from test_credit_migration import service as credits
from test_invoice_migration import (
    financial_database_url,
    invoice_api_actor,
    register_billing_service_principal,
    runtime_database_url,
    set_draft_correction_context,
    setup_invoice_api_source,
)
from test_late_payment_migration import late_payment_actor
from test_late_payment_migration import service as late_service
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import service as allocations
from test_payment_allocation_migration import source as allocation_source
from test_payment_migration import fx_payment, reverse
from test_payment_reversal_context_migration import deposit_source, snapshot
from test_pet_refund_migration import command as pet_refund
from test_pet_refund_migration import qualified
from test_receipt_migration import source as receipt_source
from test_refund_service_migration import corrections, create, refund_id, returned
from test_refund_service_migration import service as refunds
from test_reservation_lifecycle_migration import active_reservation, cancel
from test_reservation_migration import migrated_database_url  # noqa: F401


def get(
    human: UUID,
    prop: UUID,
    purpose: str,
    source_id: UUID,
    *,
    target_kind: str | None = None,
    target_id: UUID | None = None,
    refund: UUID | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, object]:
    return FinancialActionContextService(runtime_database_url()).get(
        prop,
        FinancialActionContextRequest(
            purpose, source_id, target_kind, target_id, refund, limit, cursor
        ),
        actor=actor(human, prop, ACTION_CAPABILITIES[purpose]),
    )


def data(result: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], result["data"])


def context(result: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], data(result)["context"])


def test_financial_action_context_database_payment_receipt_fx_and_no_writes(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        payment = fx_payment(connection, channel=True, channel_rate=Decimal("4100.123456"))
        row = connection.execute(
            "SELECT confirmed_by,property_id FROM app.payments WHERE id=%s", (payment,)
        ).fetchone()
        assert row is not None
        human, prop = row
        receipt = connection.execute(
            "SELECT id FROM app.receipts WHERE payment_id=%s", (payment,)
        ).fetchone()
        assert receipt is not None
    before = snapshot(migrated_database_url)
    original = PaymentReadService(runtime_database_url()).get(
        prop, payment, actor=actor(human, prop, "payments.read")
    )
    for purpose, identity in (
        ("allocation", payment),
        ("credit_recognition", payment),
        ("receipt_reprint", receipt[0]),
    ):
        result = get(human, prop, purpose, identity)
        assert data(result)["payment_resource"] == original
        assert data(result)["items"] == [] and result["next_cursor"] is None
        if purpose == "receipt_reprint":
            assert cast(dict[str, object], context(result)["receipt"])["id"] == str(receipt[0])
    assert snapshot(migrated_database_url) == before


def test_financial_action_context_database_credit_recognition_and_reversal_position(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    assert (
        context(get(human, prop, "credit_recognition", payment))["applicable_obligations"] is False
    )
    identity = credit_id(recognize(prop, payment, human))
    before = snapshot(migrated_database_url)
    for purpose in ("credit_reversal", "credit_application"):
        result = get(human, prop, purpose, identity)
        credit = cast(dict[str, object], context(result)["credit"])
        assert cast(dict[str, object], credit["position"])["available_usd_cents"] == 8000
        assert cast(dict[str, object], credit["credit"])["source_payment_id"] == str(payment)
    assert snapshot(migrated_database_url) == before
    credits().reverse(
        prop,
        identity,
        ReverseCreditCommand(uuid4(), "Correct recognition"),
        actor=actor(human, prop, "credits.reverse"),
    )
    after = context(get(human, prop, "credit_reversal", identity))
    assert cast(dict[str, object], after["reversal"])["customer_credit_id"] == str(identity)
    assert (
        cast(dict[str, object], cast(dict[str, object], after["credit"])["position"])[
            "available_usd_cents"
        ]
        == 0
    )


def test_financial_action_context_database_allocation_original_and_current_target(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, invoices = allocation_source(migrated_database_url)
    assert (
        context(get(human, prop, "credit_recognition", payment))["applicable_obligations"] is True
    )
    before = snapshot(migrated_database_url)
    target = get(human, prop, "allocation", payment, target_kind="INVOICE", target_id=invoices[0])
    assert cast(dict[str, object], data(target)["target"])["outstanding_usd_cents"] == 80000
    assert cast(list[dict[str, object]], data(target)["items"])[0]["kind"] == "INVOICE_LINE"
    assert snapshot(migrated_database_url) == before
    staff = allocation_actor(human, prop)
    posted = allocations().post(
        prop,
        payment,
        PostAllocationsCommand(
            uuid4(),
            {"mode": "PROPOSAL", "proposal": allocations().proposal(prop, payment, actor=staff)},
        ),
        actor=staff,
    )
    identities = cast(list[str], posted["allocation_ids"])
    for value in identities:
        identity = UUID(value)
        original = get(human, prop, "allocation_reversal", identity)
        header = cast(dict[str, object], context(original)["allocation"])
        details = cast(list[dict[str, object]], data(original)["items"])
        assert (
            sum(
                cast(int, cast(dict[str, object], d["data"])["posted_amount_usd_cents"])
                for d in details
            )
            == header["amount_usd_cents"]
        )
        assert context(original)["reversal"] is None
        allocations().reverse_allocation(
            prop, identity, ReverseAllocationCommand(uuid4(), "Correct allocation"), actor=staff
        )
        after = get(human, prop, "allocation_reversal", identity)
        assert context(after)["allocation"] == header
        assert cast(dict[str, object], context(after)["reversal"])["payment_allocation_id"] == value
        assert cast(dict[str, object], data(after)["target"])["outstanding_usd_cents"] == 80000


def test_financial_action_context_database_credit_application_original_and_reversal(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, credit, invoice, line, payment = application_source(migrated_database_url)
    before = get(
        human, prop, "credit_application", credit, target_kind="INVOICE", target_id=invoice
    )
    assert cast(dict[str, object], data(before)["target"])["outstanding_usd_cents"] == 80000
    posted = credits().apply(
        prop, credit, designated(invoice, line, 30000), actor=actor(human, prop, "credits.apply")
    )
    identity = application_id(posted)
    original = get(human, prop, "credit_application_reversal", identity)
    header = context(original)["application"]
    assert cast(dict[str, object], data(original)["target"])["outstanding_usd_cents"] == 50000
    assert cast(
        dict[str, object], cast(dict[str, object], data(original)["payment_resource"])["payment"]
    )["id"] == str(payment)
    details = cast(list[dict[str, object]], data(original)["items"])
    assert cast(dict[str, object], details[0]["data"])["applied_amount_usd_cents"] == 30000
    assert cast(dict[str, object], details[0]["data"])["target_id"] == str(line)
    credits().reverse_application(
        prop,
        identity,
        ReverseCreditApplicationCommand(uuid4(), "Correct application"),
        actor=actor(human, prop, "credits.applications.reverse"),
    )
    after = get(human, prop, "credit_application_reversal", identity)
    assert context(after)["application"] == header
    assert cast(dict[str, object], context(after)["reversal"])["credit_application_id"] == str(
        identity
    )
    assert cast(dict[str, object], data(after)["target"])["outstanding_usd_cents"] == 80000


@pytest.mark.parametrize("kind", ["PAYMENT", "CREDIT"])
def test_financial_action_context_database_refund_original_return_and_exact_correction(
    migrated_database_url: str,  # noqa: F811
    kind: str,
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    source_id = credit_id(recognize(prop, payment, human)) if kind == "CREDIT" else payment
    posted = create_usd_refund(
        refunds(), prop, create(source_id, kind=kind), actor=actor(human, prop, "refunds.create")
    )
    identity = refund_id(posted)
    original = context(get(human, prop, "refund_return", identity))
    assert cast(dict[str, object], original["refund"])["refund"] == posted["refund"]
    correction_result = refunds().verify_usd_return(
        prop, identity, returned(), actor=actor(human, prop, "refunds.correct")
    )
    correction = corrections(correction_result)[0]
    correction_id = UUID(str(correction["id"]))
    before = snapshot(migrated_database_url)
    selected = context(
        get(human, prop, "refund_correction_reversal", correction_id, refund=identity)
    )
    assert selected["correction"] == correction and selected["reversal"] is None
    assert cast(dict[str, object], selected["refund"])["net_refund_usd_cents"] == 4000
    assert snapshot(migrated_database_url) == before
    with pytest.raises(PaymentReadNotFoundError):
        get(human, prop, "refund_correction_reversal", correction_id, refund=uuid4())
    refunds().reverse_correction(
        prop,
        identity,
        correction_id,
        ReverseRefundCorrectionCommand(uuid4(), "Reviewed evidence", "Correct return entry"),
        actor=actor(human, prop, "refunds.corrections.reverse"),
    )
    after = context(get(human, prop, "refund_correction_reversal", correction_id, refund=identity))
    assert after["correction"] == correction
    assert cast(dict[str, object], after["reversal"])["reverses_correction_id"] == str(
        correction_id
    )
    assert cast(dict[str, object], after["refund"])["net_refund_usd_cents"] == 8000


@pytest.mark.parametrize("purpose", ACTION_CAPABILITIES)
def test_financial_action_context_database_missing_sources_do_not_leak(
    migrated_database_url: str,  # noqa: F811
    purpose: str,
) -> None:
    human, prop, _, _ = source(migrated_database_url)
    with pytest.raises(PaymentReadNotFoundError):
        get(
            human,
            prop,
            purpose,
            uuid4(),
            refund=uuid4() if purpose == "refund_correction_reversal" else None,
        )


def test_financial_action_context_database_migration_privileges_and_forward_only(
    migrated_database_url: str,  # noqa: F811
) -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    assert scripts.get_heads() == ["20270207_195"]
    revision = scripts.get_revision("20260908_47")
    assert revision is not None and revision.down_revision == "20260908_46"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    signature = (
        "app.financial_action_context_page(uuid,uuid,text,uuid,uuid,text,uuid,integer,integer,uuid)"
    )
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT prosecdef,provolatile,proconfig FROM pg_proc WHERE oid=%s::regprocedure",
            (signature,),
        ).fetchone()
        assert (
            row is not None
            and row[:2] == (True, "s")
            and "search_path=pg_catalog" in row[2]
            and "TimeZone=UTC" in row[2]
        )
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
            assert connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)
            ).fetchone() == (role == "prm_runtime",)
        assert connection.execute(
            "SELECT NOT EXISTS(SELECT 1 FROM pg_proc p,aclexplode(p.proacl) acl "
            "WHERE p.oid=%s::regprocedure AND acl.grantee=0 "
            "AND acl.privilege_type='EXECUTE')",
            (signature,),
        ).fetchone() == (True,)


def walk_context(
    human: UUID,
    prop: UUID,
    purpose: str,
    source_id: UUID,
    *,
    target_kind: str | None = None,
    target_id: UUID | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    cursor = None
    revision = None
    for _ in range(1000):
        page = get(
            human,
            prop,
            purpose,
            source_id,
            target_kind=target_kind,
            target_id=target_id,
            limit=37,
            cursor=cursor,
        )
        current = data(page)
        assert revision is None or current["revision"] == revision
        revision = current["revision"]
        items = cast(list[dict[str, object]], current["items"])
        assert len(items) <= 37
        rows.extend(items)
        cursor = cast(str | None, page["next_cursor"])
        if cursor is None:
            break
    else:
        pytest.fail("Financial context did not finish its bounded continuation")
    assert len({item["id"] for item in rows}) == len(rows)
    assert [item["sequence"] for item in rows] == list(range(1, len(rows) + 1))
    return rows


def test_financial_action_context_database_complete_500_line_sources_and_stale_pages(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, proposal = large_history_source(migrated_database_url)
    invoice = UUID(str(cast(list[dict[str, object]], proposal["targets"])[0]["invoice_id"]))
    first = get(
        human, prop, "allocation", payment, target_kind="INVOICE", target_id=invoice, limit=37
    )
    before = snapshot(migrated_database_url)
    target_lines = walk_context(
        human, prop, "allocation", payment, target_kind="INVOICE", target_id=invoice
    )
    assert len(target_lines) == 500
    assert (
        sum(
            cast(int, cast(dict[str, object], item["data"])["outstanding_usd_cents"])
            for item in target_lines
        )
        == 500
    )
    assert snapshot(migrated_database_url) == before
    posted = allocations().post(
        prop,
        payment,
        PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
        actor=allocation_actor(human, prop),
    )
    identity = UUID(cast(list[str], posted["allocation_ids"])[0])
    with pytest.raises(FinancialActionContextChanged):
        get(
            human,
            prop,
            "allocation",
            payment,
            target_kind="INVOICE",
            target_id=invoice,
            limit=37,
            cursor=str(first["next_cursor"]),
        )
    allocation_lines = walk_context(human, prop, "allocation_reversal", identity)
    assert len(allocation_lines) == 500
    assert (
        sum(
            cast(int, cast(dict[str, object], item["data"])["posted_amount_usd_cents"])
            for item in allocation_lines
        )
        == 500
    )
    assert all(
        cast(dict[str, object], item["data"])["current_outstanding_usd_cents"] == 0
        for item in allocation_lines
    )
    # Recognition occurs while all applicable obligations are paid. It remains a
    # distinct source when the original Allocation is subsequently reversed.
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT payer_customer_id FROM app.payments WHERE id=%s", (payment,)
        ).fetchone()
        assert row is not None
        credit_payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=row[0], amount=500
        )
    credit = credit_id(recognize(prop, credit_payment, human, 500))
    allocations().reverse_allocation(
        prop,
        identity,
        ReverseAllocationCommand(uuid4(), "Correct allocation"),
        actor=allocation_actor(human, prop),
    )
    credit_target_lines = walk_context(
        human, prop, "credit_application", credit, target_kind="INVOICE", target_id=invoice
    )
    assert len(credit_target_lines) == 500
    credit_proposal = credits().application_proposal(
        prop, credit, invoice, 500, actor=actor(human, prop, "credits.apply")
    )
    applied = credits().apply(
        prop,
        credit,
        ApplyCreditCommand(uuid4(), {"mode": "PROPOSAL", "proposal": credit_proposal}),
        actor=actor(human, prop, "credits.apply"),
    )
    application = application_id(applied)
    app_first = get(human, prop, "credit_application_reversal", application, limit=37)
    app_lines = walk_context(human, prop, "credit_application_reversal", application)
    assert len(app_lines) == 500
    assert (
        sum(
            cast(int, cast(dict[str, object], item["data"])["applied_amount_usd_cents"])
            for item in app_lines
        )
        == 500
    )
    assert context(get(human, prop, "allocation_reversal", identity))["reversal"] is not None
    credits().reverse_application(
        prop,
        application,
        ReverseCreditApplicationCommand(uuid4(), "Correct application"),
        actor=actor(human, prop, "credits.applications.reverse"),
    )
    with pytest.raises(FinancialActionContextChanged):
        get(
            human,
            prop,
            "credit_application_reversal",
            application,
            limit=37,
            cursor=str(app_first["next_cursor"]),
        )


def test_financial_action_context_database_selected_correction_beyond_max_history_page(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    original = create_usd_refund(
        refunds(), prop, create(payment), actor=actor(human, prop, "refunds.create")
    )
    identity = refund_id(original)
    first = None
    for _ in range(101):
        result = refunds().verify_usd_return(
            prop, identity, returned(1), actor=actor(human, prop, "refunds.correct")
        )
        if first is None:
            first = corrections(result)[0]
    assert first is not None
    selected = context(
        get(human, prop, "refund_correction_reversal", UUID(str(first["id"])), refund=identity)
    )
    assert selected["correction"] == first
    assert cast(dict[str, object], selected["refund"])["net_refund_usd_cents"] == 7899
    assert selected["reversal"] is None


@pytest.mark.parametrize("kind", ["missing", "disabled", "service"])
def test_financial_action_context_database_fresh_human_before_source(
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
    for source_id in (payment, uuid4()):
        with pytest.raises(PaymentReadAuthorizationError):
            get(human, prop, "allocation", source_id)
    assert snapshot(migrated_database_url) == before


def test_financial_action_context_database_normal_credit_and_third_party_target_scope(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, payment, invoices = allocation_source(migrated_database_url)
    _, _, foreign_payment, foreign_invoices = allocation_source(migrated_database_url)
    with pytest.raises(PaymentReadNotFoundError):
        get(
            human, prop, "allocation", payment, target_kind="INVOICE", target_id=foreign_invoices[0]
        )
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT payer_customer_id FROM app.payments WHERE id=%s", (foreign_payment,)
        ).fetchone()
        assert row is not None
        third_party = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=row[0],
            amount=100000,
            scope="THIRD_PARTY_IDENTIFIED",
            invoice_id=invoices[0],
        )
    selected = get(
        human, prop, "allocation", third_party, target_kind="INVOICE", target_id=invoices[0]
    )
    assert cast(dict[str, object], data(selected)["target"])["id"] == str(invoices[0])
    assert (
        cast(
            dict[str, object],
            cast(dict[str, object], data(selected)["payment_resource"])["payment"],
        )["payer_customer_id"]
        != cast(dict[str, object], data(selected)["target"])["customer_id"]
    )
    with pytest.raises(PaymentReadNotFoundError):
        get(human, prop, "allocation", third_party, target_kind="INVOICE", target_id=invoices[1])
    credit_human, credit_prop, credit, _, _, _ = application_source(migrated_database_url)
    with pytest.raises(PaymentReadNotFoundError):
        get(
            credit_human,
            credit_prop,
            "credit_application",
            credit,
            target_kind="INVOICE",
            target_id=invoices[0],
        )


def test_financial_action_context_database_shared_deposit_guard_changes_source_context(
    migrated_database_url: str,  # noqa: F811
) -> None:
    service, staff, _, _, payment, receipts = deposit_source(migrated_database_url)
    human, prop = service.actor_id, service.property_id
    before = get(human, prop, "allocation", payment)
    with psycopg.connect(migrated_database_url) as connection:
        guard = connection.execute(
            "SELECT revision FROM app.payment_serialization_guards WHERE payment_id=%s", (payment,)
        ).fetchone()
    reverse_receipt_as_owner(
        service,
        ReverseDepositReceiptCommand(uuid4(), uuid4(), receipts[0], "Resolve original direction"),
        actor=staff,
    )
    with psycopg.connect(migrated_database_url) as connection:
        assert (
            connection.execute(
                "SELECT revision FROM app.payment_serialization_guards WHERE payment_id=%s",
                (payment,),
            ).fetchone()
            == guard
        )
    after = get(human, prop, "allocation", payment)
    assert data(after)["revision"] != data(before)["revision"]
    assert (
        cast(
            dict[str, object], cast(dict[str, object], data(after)["payment_resource"])["position"]
        )["available_usd_cents"]
        == 20000
    )


def test_financial_action_context_database_coherent_snapshot_during_new_refund(
    migrated_database_url: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    original = get(human, prop, "allocation", payment)
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
        assert get(human, prop, "allocation", payment) == original
    changed = get(human, prop, "allocation", payment)
    assert data(changed)["revision"] != data(original)["revision"]
    assert (
        cast(
            dict[str, object],
            cast(dict[str, object], data(changed)["payment_resource"])["position"],
        )["available_usd_cents"]
        == 9000
    )


def test_financial_action_context_database_statement_deadline_is_unavailable(
    migrated_database_url: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    monkeypatch.setattr(
        "property_rental.financial_action_context._DETAIL",
        "SELECT pg_sleep(6) WHERE %s::uuid IS NOT NULL AND %s::uuid IS NOT NULL",
    )
    started = monotonic()
    with pytest.raises(PaymentReadUnavailableError):
        get(human, prop, "allocation", payment)
    assert 4.5 <= monotonic() - started < 8


def test_financial_action_context_database_historical_void_target_is_zero(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, credit, invoice, line, _ = application_source(migrated_database_url)
    identity = application_id(
        credits().apply(
            prop, credit, designated(invoice, line, 1000), actor=actor(human, prop, "credits.apply")
        )
    )
    credits().reverse_application(
        prop,
        identity,
        ReverseCreditApplicationCommand(uuid4(), "Resolve attribution"),
        actor=actor(human, prop, "credits.applications.reverse"),
    )
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT version FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
        assert row is not None
    PostgresInvoiceService(runtime_database_url(), financial_database_url()).void(
        prop,
        invoice,
        VoidInvoiceCommand(uuid4(), "Correct original invoice", row[0]),
        actor=invoice_api_actor(human, prop),
    )
    result = get(human, prop, "credit_application_reversal", identity)
    assert cast(dict[str, object], data(result)["target"])["status"] == "VOID"
    declared = cast(dict[str, object], data(result)["target"])
    assert declared["line_count"] == 1
    assert declared["original_total_usd_cents"] == declared["adjusted_total_usd_cents"] == 80000
    assert cast(dict[str, object], data(result)["target"])["outstanding_usd_cents"] == 0
    assert (
        cast(dict[str, object], cast(list[dict[str, object]], data(result)["items"])[0]["data"])[
            "current_outstanding_usd_cents"
        ]
        == 0
    )


def test_financial_action_context_database_charge_remains_separate_from_invoice(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, credit, invoice, _, credit_payment = application_source(
        migrated_database_url, period_start=date(2026, 5, 1)
    )
    with psycopg.connect(migrated_database_url) as connection:
        customer = connection.execute(
            "SELECT payer_customer_id FROM app.payments WHERE id=%s", (credit_payment,)
        ).fetchone()
        assert customer is not None
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer[0], amount=10000
        )
    late_service().finalize_decision(
        prop,
        invoice,
        FinalizeLatePaymentDecisionCommand(
            uuid4(), DecisionOutcome.CONFIRMED_DEFAULT, 8000, "Confirm default charge"
        ),
        actor=late_payment_actor(human, prop),
    )
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT id FROM app.late_payment_charges WHERE source_invoice_id=%s", (invoice,)
        ).fetchone()
        assert row is not None
        charge = row[0]
    intent: dict[str, object] = {
        "mode": "DIRECT_CHARGE",
        "late_payment_charge_id": str(charge),
        "amount_usd_cents": 2000,
    }
    allocated = allocations().post(
        prop, payment, PostAllocationsCommand(uuid4(), intent), actor=allocation_actor(human, prop)
    )
    applied = credits().apply(
        prop,
        credit,
        ApplyCreditCommand(uuid4(), intent | {"amount_usd_cents": 3000}),
        actor=actor(human, prop, "credits.apply"),
    )
    late_service().correct_charge(
        prop,
        charge,
        CorrectLatePaymentChargeCommand(
            uuid4(), CorrectionKind.REDUCTION, "Correct charge value", 1000
        ),
        actor=late_payment_actor(human, prop),
    )
    allocation = UUID(cast(list[str], allocated["allocation_ids"])[0])
    application = application_id(applied)
    for purpose, source_id in (
        ("allocation", payment),
        ("credit_application", credit),
        ("allocation_reversal", allocation),
        ("credit_application_reversal", application),
    ):
        is_posting = purpose in {"allocation", "credit_application"}
        result = get(
            human,
            prop,
            purpose,
            source_id,
            target_kind="LATE_PAYMENT_CHARGE" if is_posting else None,
            target_id=charge if is_posting else None,
        )
        target = cast(dict[str, object], data(result)["target"])
        assert target["source_invoice_id"] == str(invoice)
        assert (
            target["original_usd_cents"],
            target["adjusted_obligation_usd_cents"],
            target["remaining_balance_usd_cents"],
        ) == (8000, 7000, 2000)
        details = cast(list[dict[str, object]], data(result)["items"])
        if is_posting:
            assert details == []
        else:
            assert (
                len(details) == 1
                and cast(dict[str, object], details[0]["data"])["current_outstanding_usd_cents"]
                == 2000
            )
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT status FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone() == ("UNPAID",)
        assert connection.execute(
            "SELECT sum(app.invoice_line_outstanding(id)) FROM app.invoice_lines "
            "WHERE invoice_id=%s",
            (invoice,),
        ).fetchone() == (80000,)
    allocations().reverse_allocation(
        prop,
        allocation,
        ReverseAllocationCommand(uuid4(), "Resolve charge allocation"),
        actor=allocation_actor(human, prop),
    )
    credits().reverse_application(
        prop,
        application,
        ReverseCreditApplicationCommand(uuid4(), "Resolve charge application"),
        actor=actor(human, prop, "credits.applications.reverse"),
    )
    late_service().correct_charge(
        prop,
        charge,
        CorrectLatePaymentChargeCommand(
            uuid4(), CorrectionKind.CHARGE_REVERSAL, "Reverse charge", None
        ),
        actor=late_payment_actor(human, prop),
    )
    final = cast(
        dict[str, object], data(get(human, prop, "allocation_reversal", allocation))["target"]
    )
    assert final["reversed"] is True and final["remaining_balance_usd_cents"] == 0


def test_financial_action_context_database_deposit_refund_return_and_correction_source(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, _, deposit, review = qualified(migrated_database_url)
    staff = actor(human, prop, "refunds.create", "refunds.correct", "refunds.corrections.reverse")
    created = create_pet_refund(refunds(), prop, pet_refund(deposit, review), actor=staff)
    identity = refund_id(created)
    before = snapshot(migrated_database_url)
    initial = get(human, prop, "refund_return", identity)
    assert data(initial)["payment_resource"] is None
    assert context(initial)["deposit_source"] == {
        "id": str(deposit),
        "deposit_type": "PET",
        "held_usd_cents": 5000,
    }
    assert cast(dict[str, object], context(initial)["refund"])["refund"] == created["refund"]
    assert snapshot(migrated_database_url) == before
    corrected = refunds().verify_usd_return(prop, identity, returned(), actor=staff)
    correction = UUID(str(corrections(corrected)[0]["id"]))
    selected = get(human, prop, "refund_correction_reversal", correction, refund=identity)
    assert data(selected)["payment_resource"] is None
    assert cast(dict[str, object], context(selected)["deposit_source"])["held_usd_cents"] == 9000
    assert cast(dict[str, object], context(selected)["refund"])["net_refund_usd_cents"] == 11000
    refunds().reverse_correction(
        prop,
        identity,
        correction,
        ReverseRefundCorrectionCommand(uuid4(), "Reviewed evidence", "Correct return entry"),
        actor=staff,
    )
    after = get(human, prop, "refund_correction_reversal", correction, refund=identity)
    assert cast(dict[str, object], context(after)["deposit_source"])["held_usd_cents"] == 5000
    assert cast(dict[str, object], context(after)["refund"])["net_refund_usd_cents"] == 15000


def test_financial_action_context_database_direct_sql_rejects_malformed_arguments(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    invalid: list[tuple[int, object]] = [
        (2, None),
        (2, "future_settlement"),
        (3, None),
        (3, UUID(int=0)),
        (4, uuid4()),
        (5, "INVOICE"),
        (6, uuid4()),
        (7, None),
        (7, 0),
        (7, 101),
        (8, 0),
        (8, 32768),
        (9, uuid4()),
    ]
    before = snapshot(migrated_database_url)
    with psycopg.connect(runtime_database_url()) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        for index, value in invalid:
            params: list[object] = [
                prop,
                human,
                "allocation",
                payment,
                None,
                None,
                None,
                50,
                None,
                None,
            ]
            params[index] = value
            with pytest.raises(psycopg.errors.InvalidParameterValue):
                with connection.transaction():
                    connection.execute(
                        "SELECT app.financial_action_context_page(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        params,
                    )
    assert snapshot(migrated_database_url) == before


@pytest.mark.parametrize("historical", [False, True])
def test_financial_action_context_database_future_deposit_application_is_explicit(
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
        row = connection.execute(
            "SELECT app.financial_action_context_page(%s,%s,'allocation',"
            "%s,NULL,NULL,NULL,50,NULL,NULL)",
            (service.property_id, service.actor_id, payment),
        ).fetchone()
        assert row is not None and row[0]["unsupported_application"] is True
        connection.rollback()
        assert connection.execute("SELECT to_regclass('app.deposit_applications')").fetchone() == (
            None,
        )


def test_financial_action_context_database_actual_utf8_projection_budget(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, _ = setup_invoice_api_source(connection)
        obligation = uuid4()
        description = "😀" * 260_000
        assert len(description) < 1_000_000 < len(description.encode("utf-8"))
        connection.execute(
            "INSERT INTO app.authorized_nonrecurring_obligations "
            "(id,customer_id,category,description,authorized_amount_usd_cents,"
            "governing_due_date,due_date_source,source_reference,authorized_at,authorized_by,"
            "authorization_reference) VALUES (%s,%s,'MISCELLANEOUS_CHARGES',%s,100,"
            "current_date+14,'synthetic-byte-bound',%s,clock_timestamp(),%s,"
            "'invoice.nonrecurring.authorize')",
            (obligation, customer, description, str(obligation), human),
        )
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=100
        )
    invoice_service = PostgresInvoiceService(runtime_database_url(), financial_database_url())
    draft = invoice_service.create_draft(
        prop, CreateInvoiceDraftCommand(uuid4(), obligation), actor=invoice_api_actor(human, prop)
    )
    invoice = UUID(str(draft["id"]))
    before = snapshot(migrated_database_url)
    assert data(get(human, prop, "allocation", payment))["target"] is None
    with psycopg.connect(runtime_database_url()) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        with pytest.raises(psycopg.errors.ProgramLimitExceeded) as error:
            connection.execute(
                "SELECT app.financial_action_context_page(%s,%s,'allocation',"
                "%s,NULL,'INVOICE',%s,50,NULL,NULL)",
                (prop, human, payment, invoice),
            )
        assert error.value.sqlstate == "54000"
    with pytest.raises(PaymentReadUnavailableError):
        get(human, prop, "allocation", payment, target_kind="INVOICE", target_id=invoice)
    assert snapshot(migrated_database_url) == before


def test_financial_action_context_database_invoice_debit_preserves_original_and_adjusted(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, credit, invoice, line, payment = application_source(migrated_database_url)
    service = PostgresInvoiceService(runtime_database_url(), financial_database_url())
    staff = invoice_api_actor(human, prop)
    current = service.get(invoice, actor=staff)
    service.adjust(
        prop,
        invoice,
        AdjustInvoiceCommand(
            uuid4(),
            line,
            AdjustmentType.DEBIT,
            100,
            "synthetic-debit",
            "Approved additional obligation",
            int(str(current["version"])),
        ),
        actor=staff,
    )
    before = snapshot(migrated_database_url)
    for purpose, identity in [("allocation", payment), ("credit_application", credit)]:
        row = data(get(human, prop, purpose, identity, target_kind="INVOICE", target_id=invoice))
        item = cast(dict[str, object], cast(list[dict[str, object]], row["items"])[0]["data"])
        assert item["original_amount_usd_cents"] == 80000
        assert item["adjusted_amount_usd_cents"] == item["outstanding_usd_cents"] == 80100
        assert cast(dict[str, object], row["target"])["outstanding_usd_cents"] == 80100
        declared = cast(dict[str, object], row["target"])
        assert row["item_count"] == declared["line_count"] == 1
        assert declared["original_total_usd_cents"] == 80000
        assert declared["adjusted_total_usd_cents"] == 80100
    assert snapshot(migrated_database_url) == before


@pytest.mark.parametrize("purpose", ["allocation", "credit_application"])
@pytest.mark.parametrize("changed_sequence", [1, 2])
def test_financial_action_context_database_draft_revision_invalidates_old_pages(
    migrated_database_url: str,  # noqa: F811
    purpose: str,
    changed_sequence: int,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, first_source = setup_invoice_api_source(
            connection, amount_usd_cents=100, source_reference="draft-context-source"
        )
        second_source, replacement = uuid4(), uuid4()
        for identity, description in [
            (second_source, "Second original line"),
            (replacement, "Corrected original description"),
        ]:
            connection.execute(
                "INSERT INTO app.authorized_nonrecurring_obligations "
                "(id,customer_id,category,description,authorized_amount_usd_cents,"
                "governing_due_date,due_date_source,source_reference,authorized_at,authorized_by,"
                "authorization_reference) SELECT %s,customer_id,category,%s,author"
                "ized_amount_usd_cents,"
                "governing_due_date,due_date_source,%s,clock_timestamp(),authorized_by,"
                "authorization_reference FROM app.authorized_nonrecurring_obligations WHERE id=%s",
                (identity, description, str(identity), first_source),
            )
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=1000
        )
    credit = credit_id(recognize(prop, payment, human, amount=100))
    invoice_service = PostgresInvoiceService(runtime_database_url(), financial_database_url())
    draft = invoice_service.create_draft(
        prop, CreateInvoiceDraftCommand(uuid4(), first_source), actor=invoice_api_actor(human, prop)
    )
    invoice = UUID(str(draft["id"]))
    with psycopg.connect(migrated_database_url) as connection:
        set_draft_correction_context(
            connection, actor_id=human, reason="Include second approved source"
        )
        connection.execute(
            "UPDATE app.invoices SET original_total_usd_cents=200,version=vers"
            "ion+1,updated_at=clock_timestamp(),updated_by=%s WHERE id=%s",
            (human, invoice),
        )
        connection.execute(
            "INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,categor"
            "y,description,amount_usd_cents,authorized_obligation_id,calculati"
            "on_trace,created_by) "
            "VALUES (%s,%s,2,'MISCELLANEOUS_CHARGES','Second original line',100,%s,%s,%s)",
            (
                uuid4(),
                invoice,
                second_source,
                Jsonb(
                    {
                        "formula": "authorized_source_exact_amount",
                        "authorized_obligation_id": str(second_source),
                        "authorized_amount_usd_cents": 100,
                    }
                ),
                human,
            ),
        )
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    identity = payment if purpose == "allocation" else credit
    first = get(human, prop, purpose, identity, target_kind="INVOICE", target_id=invoice, limit=1)
    cursor = str(first["next_cursor"])
    assert first["next_cursor"] is not None
    initial = get(
        human,
        prop,
        purpose,
        identity,
        target_kind="INVOICE",
        target_id=invoice,
        limit=1,
        cursor=cursor,
    )
    assert initial["next_cursor"] is None and data(initial)["revision"] == data(first)["revision"]
    assert cast(dict[str, object], data(first)["target"])["outstanding_usd_cents"] == 0
    declared = cast(dict[str, object], data(first)["target"])
    assert data(first)["item_count"] == data(initial)["item_count"] == declared["line_count"] == 2
    assert declared["original_total_usd_cents"] == declared["adjusted_total_usd_cents"] == 200
    guard_sql = (
        "SELECT COALESCE((SELECT revision FROM app.invoice_serialization_g"
        "uards WHERE guard_key=%s),0)"
    )
    with psycopg.connect(migrated_database_url) as connection:
        old_guard = connection.execute(guard_sql, (f"invoice-financial:{invoice}",)).fetchone()
        old_version = connection.execute(
            "SELECT version FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
        old_events = connection.execute(
            "SELECT count(*) FROM app.invoice_draft_revision_events WHERE invoice_id=%s", (invoice,)
        ).fetchone()
        set_draft_correction_context(
            connection, actor_id=human, reason="Correct authorized line source and description"
        )
        connection.execute(
            "UPDATE app.invoices SET version=version+1,updated_at=clock_timest"
            "amp(),updated_by=%s WHERE id=%s",
            (human, invoice),
        )
        connection.execute(
            "UPDATE app.invoice_lines SET description='Corrected original desc"
            "ription',authorized_obligation_id=%s,calculation_trace=%s,last_ch"
            "anged_by=%s WHERE invoice_id=%s AND line_sequence=%s",
            (
                replacement,
                Jsonb(
                    {
                        "formula": "authorized_source_exact_amount",
                        "authorized_obligation_id": str(replacement),
                        "authorized_amount_usd_cents": 100,
                    }
                ),
                human,
                invoice,
                changed_sequence,
            ),
        )
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert (
            connection.execute(guard_sql, (f"invoice-financial:{invoice}",)).fetchone() == old_guard
        )
        assert old_version is not None and old_events is not None
        assert connection.execute(
            "SELECT version FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone() == (old_version[0] + 1,)
        new_events = connection.execute(
            "SELECT count(*) FROM app.invoice_draft_revision_events WHERE invoice_id=%s", (invoice,)
        ).fetchone()
        assert new_events is not None and new_events[0] > old_events[0]
    after_correction = snapshot(migrated_database_url)
    with pytest.raises(FinancialActionContextChanged):
        get(
            human,
            prop,
            purpose,
            identity,
            target_kind="INVOICE",
            target_id=invoice,
            limit=1,
            cursor=cursor,
        )
    fresh = get(human, prop, purpose, identity, target_kind="INVOICE", target_id=invoice, limit=1)
    assert data(fresh)["revision"] != data(first)["revision"]
    assert snapshot(migrated_database_url) == after_correction


@pytest.mark.parametrize("channel_kind", ["none", "manual", "complete", "amount", "usd", "rate"])
def test_financial_action_context_database_khr_credit_preserves_exact_original_fx(
    migrated_database_url: str,  # noqa: F811
    channel_kind: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        payment = fx_payment(
            connection,
            manual=channel_kind == "manual",
            channel=channel_kind in {"complete", "amount", "usd", "rate"},
            channel_amount_only=channel_kind == "amount",
            channel_usd_only=channel_kind == "usd",
            channel_rate_only=channel_kind == "rate",
            channel_rate=Decimal("4100.123456") if channel_kind == "rate" else None,
            amount=4142 if channel_kind == "rate" else 4143,
        )
        payment_row = connection.execute(
            "SELECT confirmed_by,property_id FROM app.payments WHERE id=%s", (payment,)
        ).fetchone()
        assert payment_row is not None
        human, prop = payment_row
    identity = credit_id(recognize(prop, payment, human, 80))
    before = snapshot(migrated_database_url)
    result = get(human, prop, "credit_reversal", identity)
    resource = cast(dict[str, object], data(result)["payment_resource"])
    credit = cast(dict[str, object], context(result)["credit"])
    original_fx = cast(dict[str, object], resource["exchange_rate"])
    assert credit["exchange_rate"] == {k: v for k, v in original_fx.items() if k != "entered_by"}
    assert data(result)["item_count"] == 0 and data(result)["items"] == []
    assert cast(dict[str, object], credit["position"])["recognized_usd_cents"] == 80
    assert snapshot(migrated_database_url) == before


@pytest.mark.parametrize("zero_kind", ["paid", "adjusted"])
def test_financial_action_context_database_zero_balance_retains_invoice_cardinality_and_totals(
    migrated_database_url: str,  # noqa: F811
    zero_kind: str,
) -> None:
    human, prop, credit, invoice, line, payment = application_source(migrated_database_url)
    if zero_kind == "paid":
        credits().apply(
            prop,
            credit,
            designated(invoice, line, 80000),
            actor=actor(human, prop, "credits.apply"),
        )
    else:
        invoice_service = PostgresInvoiceService(runtime_database_url(), financial_database_url())
        staff = invoice_api_actor(human, prop)
        current = invoice_service.get(invoice, actor=staff)
        invoice_service.adjust(
            prop,
            invoice,
            AdjustInvoiceCommand(
                uuid4(),
                line,
                AdjustmentType.CREDIT,
                80000,
                "synthetic-zero",
                "Approved obligation reduction",
                int(str(current["version"])),
            ),
            actor=staff,
        )
    before = snapshot(migrated_database_url)
    for purpose, identity in [("allocation", payment), ("credit_application", credit)]:
        result = get(human, prop, purpose, identity, target_kind="INVOICE", target_id=invoice)
        row = data(result)
        target = cast(dict[str, object], row["target"])
        assert row["item_count"] == target["line_count"] == 1
        assert target["status"] == "PAID" and target["outstanding_usd_cents"] == 0
        assert target["original_total_usd_cents"] == 80000
        assert target["adjusted_total_usd_cents"] == (80000 if zero_kind == "paid" else 0)
        items = cast(list[dict[str, object]], row["items"])
        assert len(items) == 1 and result["next_cursor"] is None
        assert cast(dict[str, object], items[0]["data"])["outstanding_usd_cents"] == 0
    assert snapshot(migrated_database_url) == before


def test_financial_action_context_database_review_aa_multiple_applications(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, credit, invoice, line, _ = application_source(migrated_database_url)
    staff = actor(human, prop, "credits.apply", "credits.applications.reverse")
    first = application_id(
        credits().apply(prop, credit, designated(invoice, line, 30000), actor=staff)
    )
    credits().apply(prop, credit, designated(invoice, line, 20000), actor=staff)
    before = snapshot(migrated_database_url)
    selected = context(get(human, prop, "credit_application_reversal", first))
    assert cast(dict[str, object], selected["application"])["amount_usd_cents"] == 30000
    assert (
        cast(dict[str, object], cast(dict[str, object], selected["credit"])["position"])[
            "applied_usd_cents"
        ]
        == 50000
    )
    assert selected["reversal"] is None and snapshot(migrated_database_url) == before
    credits().reverse_application(
        prop,
        first,
        ReverseCreditApplicationCommand(uuid4(), "Correct selected application"),
        actor=staff,
    )
    before = snapshot(migrated_database_url)
    after = context(get(human, prop, "credit_application_reversal", first))
    assert after["application"] == selected["application"] and after["reversal"] is not None
    assert (
        cast(dict[str, object], cast(dict[str, object], after["credit"])["position"])[
            "applied_usd_cents"
        ]
        == 20000
    )
    assert snapshot(migrated_database_url) == before


@pytest.mark.parametrize("kind", ["PAYMENT", "CREDIT"])
def test_financial_action_context_database_review_aa_refund_multiple_and_parent_reversal(
    migrated_database_url: str,  # noqa: F811
    kind: str,
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    identity = credit_id(recognize(prop, payment, human)) if kind == "CREDIT" else payment
    staff = actor(human, prop, "refunds.create", "refunds.correct", "refunds.corrections.reverse")
    first = refund_id(create_usd_refund(refunds(), prop, create(identity, 3000, kind), actor=staff))
    second = refund_id(
        create_usd_refund(refunds(), prop, create(identity, 2000, kind), actor=staff)
    )
    before = snapshot(migrated_database_url)
    original = get(human, prop, "refund_return", first)
    assert cast(dict[str, object], context(original)["refund"])["net_refund_usd_cents"] == 3000
    if kind == "PAYMENT":
        position = cast(
            dict[str, object],
            cast(dict[str, object], data(original)["payment_resource"])["position"],
        )
        assert cast(dict[str, object], position["dispositions"])["refund_usd_cents"] == 5000
    else:
        position = cast(
            dict[str, object], cast(dict[str, object], context(original)["credit"])["position"]
        )
        assert position["refunded_usd_cents"] == 5000
    assert snapshot(migrated_database_url) == before
    returned_first = refunds().verify_usd_return(prop, first, returned(1000), actor=staff)
    selected_id = UUID(str(corrections(returned_first)[0]["id"]))
    refunds().verify_usd_return(prop, first, returned(1000), actor=staff)
    before = snapshot(migrated_database_url)
    selected = context(get(human, prop, "refund_correction_reversal", selected_id, refund=first))
    assert (
        cast(dict[str, object], selected["correction"])["source_balance_effect_usd_cents"] == 1000
    )
    assert cast(dict[str, object], selected["refund"])["net_refund_usd_cents"] == 1000
    assert selected["reversal"] is None and snapshot(migrated_database_url) == before
    refunds().reverse_correction(
        prop,
        first,
        selected_id,
        ReverseRefundCorrectionCommand(
            uuid4(), "Reviewed selected evidence", "Correct selected return"
        ),
        actor=staff,
    )
    before = snapshot(migrated_database_url)
    reversed_context = context(
        get(human, prop, "refund_correction_reversal", selected_id, refund=first)
    )
    assert reversed_context["reversal"] is not None
    assert cast(dict[str, object], reversed_context["refund"])["net_refund_usd_cents"] == 2000
    assert snapshot(migrated_database_url) == before
    refunds().verify_usd_return(prop, first, returned(2000), actor=staff)
    refunds().verify_usd_return(prop, second, returned(2000), actor=staff)
    if kind == "CREDIT":
        credits().reverse(
            prop,
            identity,
            ReverseCreditCommand(uuid4(), "Reverse fully restored Credit"),
            actor=actor(human, prop, "credits.reverse"),
        )
    with psycopg.connect(migrated_database_url) as connection:
        reverse(connection, payment, human)
    before = snapshot(migrated_database_url)
    for purpose, selected_source in [
        ("refund_return", first),
        ("refund_correction_reversal", selected_id),
    ]:
        final = get(
            human,
            prop,
            purpose,
            selected_source,
            refund=first if purpose == "refund_correction_reversal" else None,
        )
        assert cast(dict[str, object], context(final)["refund"])["net_refund_usd_cents"] == 0
        resource = cast(dict[str, object], data(final)["payment_resource"])
        assert cast(dict[str, object], resource["payment"])["status"] == "REVERSED"
        assert cast(dict[str, object], resource["position"])["available_usd_cents"] == 0
        assert (
            cast(dict[str, object], context(final)["refund"])["refund"]
            == cast(dict[str, object], context(original)["refund"])["refund"]
        )
    assert snapshot(migrated_database_url) == before


def test_financial_action_context_database_review_aa_historical_receipt_identity(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, payment, receipt = receipt_source(migrated_database_url)
    original = context(get(human, prop, "receipt_reprint", receipt))["receipt"]
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "SELECT * FROM app.update_customer(%s,'Changed synthetic name',"
            "'012345678',NULL,NULL,NULL,1,%s,%s)",
            (customer, human, uuid4()),
        )
        reverse(connection, payment, human)
    before = snapshot(migrated_database_url)
    final = get(human, prop, "receipt_reprint", receipt)
    assert context(final)["receipt"] == original
    assert (
        cast(dict[str, object], cast(dict[str, object], original)["identity_snapshot"])[
            "payer_legal_name"
        ]
        != "Changed synthetic name"
    )
    assert (
        cast(
            dict[str, object], cast(dict[str, object], data(final)["payment_resource"])["payment"]
        )["status"]
        == "REVERSED"
    )
    assert snapshot(migrated_database_url) == before


def test_financial_action_context_database_review_aa_legacy_reservation_null_evidence(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, _, reservation = active_reservation(connection)
    original, correction_id, replacement = uuid4(), uuid4(), uuid4()
    with psycopg.connect(financial_database_url()) as connection:
        cancel(
            connection,
            actor_id=human,
            property_id=prop,
            reservation_id=reservation,
            idempotency_key=uuid4(),
            event_id=uuid4(),
            outcome_id=original,
            responsibility="PROPERTY",
            property_could_provide_unit=False,
            coordination_reference="Synthetic reviewed case",
            refund_number="RF-" + str(original),
        )
    # V1-056 slice 3b: the correction is a draft confirmed under financial.approve.
    with psycopg.connect(financial_database_url()) as connection:
        corrected = correct_reservation_outcome(
            connection,
            actor_id=human,
            property_id=prop,
            reservation_id=reservation,
            idempotency_key=uuid4(),
            correction_id=correction_id,
            expected_outcome_id=original,
            replacement_outcome_id=replacement,
            replacement_refund_number="RF-" + str(replacement),
            reason="Correct synthetic processing reference",
            evidence_reference="Synthetic review evidence",
        )
        assert corrected is not None and corrected[12] == replacement
    before = snapshot(migrated_database_url)
    selected = context(
        get(human, prop, "refund_correction_reversal", correction_id, refund=original)
    )
    summary = cast(dict[str, object], selected["refund"])
    assert summary["net_refund_usd_cents"] == 0
    assert cast(dict[str, object], summary["refund"])["source_lifecycle_event_id"] is not None
    correction_row = cast(dict[str, object], selected["correction"])
    for field in [
        "source_balance_effect_original_minor",
        "verified_return_amount_minor",
        "verified_return_currency",
        "verified_returned_at",
        "return_method_reference",
    ]:
        assert correction_row[field] is None
    assert correction_row["authorization_reference"] == "reservation_deposits.correct"
    assert snapshot(migrated_database_url) == before
