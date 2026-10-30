"""Actual runtime-role ledger reads, source preservation and coherent paging."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr

from deposit_receipt_reversal_test_support import reverse_receipt_as_owner
from payment_test_support import seed_payment
from property_rental.app import create_app
from property_rental.credit import ApplyCreditCommand, ReverseCreditApplicationCommand
from property_rental.customer_ledger import (
    LedgerCursor,
    LedgerEventKey,
    LedgerFilter,
    LedgerInvalidError,
    LedgerPosition,
    LedgerSnapshotChangedError,
)
from property_rental.customer_ledger_query import (
    LEDGER_CAPABILITY,
    LedgerDetailCursor,
    LedgerReadRequest,
)
from property_rental.customer_ledger_read import (
    CustomerLedgerReadService,
    LedgerAuthorizationError,
    LedgerNotFoundError,
    LedgerUnavailableError,
)
from property_rental.deposit import ReverseDepositReceiptCommand
from property_rental.invoice import (
    CreateInvoiceDraftCommand,
    IssueInvoiceCommand,
    PostgresInvoiceService,
)
from property_rental.late_payment import (
    DecisionOutcome,
    FinalizeLatePaymentDecisionCommand,
)
from property_rental.payment_allocation import ReverseAllocationCommand
from property_rental.settings import Settings
from refund_test_support import create_usd_refund
from test_credit_application_migration import application_id
from test_credit_application_migration import source as credit_source
from test_credit_migration import actor
from test_credit_migration import service as credits
from test_credit_migration import source as payment_source
from test_customer_ledger_migration import VIEWS, canonical_invoice
from test_invoice_migration import (
    financial_database_url,
    invoice_api_actor,
    register_billing_service_principal,
    runtime_database_url,
    setup_invoice_api_source,
)
from test_late_payment_migration import late_payment_actor
from test_late_payment_migration import service as late_service
from test_lease_migration import setup_sources
from test_migrations import _temporary_migration_database, _url_with_database
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated
from test_payment_allocation_migration import service as allocations
from test_payment_allocation_migration import source as allocation_source
from test_payment_migration import fx_payment
from test_payment_reversal_context_migration import deposit_source, snapshot
from test_refund_service_migration import create
from test_refund_service_migration import service as refunds
from test_reservation_migration import migrated_database_url  # noqa: F401


def get(
    human: UUID, prop: UUID, customer: UUID, query: LedgerReadRequest | None = None
) -> dict[str, object]:
    return CustomerLedgerReadService(runtime_database_url()).get(
        customer,
        query or LedgerReadRequest(),
        actor=actor(human, prop, LEDGER_CAPABILITY),
    )


def data(result: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], result["data"])


def items(result: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], data(result)["items"])


def pages(
    human: UUID, prop: UUID, customer: UUID, query: LedgerReadRequest
) -> list[dict[str, object]]:
    rows = []
    for _ in range(100):
        result = get(human, prop, customer, query)
        rows.extend(items(result))
        if result["next_cursor"] is None:
            return rows
        query = replace(
            query,
            cursor=str(result["next_cursor"]),
            revision=str(data(result)["source_revision"]),
        )
    raise AssertionError("Ledger pagination did not terminate")


def issued_invoice(url: str) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    with psycopg.connect(url) as connection:
        human, prop, customer, obligation = setup_invoice_api_source(connection)
    service = PostgresInvoiceService(runtime_database_url(), financial_database_url())
    who = invoice_api_actor(human, prop)
    draft = service.create_draft(prop, CreateInvoiceDraftCommand(uuid4(), obligation), actor=who)
    invoice = UUID(str(draft["id"]))
    service.issue(
        prop,
        invoice,
        IssueInvoiceCommand(uuid4(), int(str(draft["version"]))),
        actor=who,
    )
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", (invoice,)
        ).fetchone()
        assert row is not None
    return human, prop, customer, invoice, UUID(str(row[0]))


def test_ledger_runtime_canonical_composition_and_components_are_complete_and_read_only(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, invoice, rent, trash = canonical_invoice(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=customer,
            amount=30000,
        )
    allocations().post(
        prop,
        payment,
        designated(invoice, rent, 30000),
        actor=allocation_actor(human, prop),
    )
    before = snapshot(migrated_database_url)
    first = get(human, prop, customer, LedgerReadRequest(limit=1))
    assert data(first)["position"] == LedgerPosition(invoice=21000).as_wire()
    revision = str(data(first)["source_revision"])
    sources = pages(
        human,
        prop,
        customer,
        LedgerReadRequest(section="composition", limit=1, revision=revision),
    )
    assert {(r["invoice_line_id"], r["balance_usd_cents"]) for r in sources} == {
        (str(rent), "20000"),
        (str(trash), "1000"),
    }
    history = pages(human, prop, customer, LedgerReadRequest(limit=1, revision=revision))
    assert len(history) == data(first)["event_count"] == 3
    for event in history:
        components = pages(
            human,
            prop,
            customer,
            LedgerReadRequest(
                section="components",
                limit=1,
                event_kind=str(event["event_kind"]),
                event_id=UUID(str(event["event_id"])),
                revision=revision,
            ),
        )
        assert len(components) == event["component_count"]
        assert len({r["detail_key"] for r in components}) == len(components)
    assert snapshot(migrated_database_url) == before


def test_ledger_runtime_filters_follow_history_and_mixed_kind_timestamp_peers_survive_pages(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, invoice, _ = issued_invoice(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT issued_at FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
        assert row is not None
        at = cast(datetime, row[0])
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=customer,
            amount=3000,
            confirmed_at=at,
        )
    events = pages(human, prop, customer, LedgerReadRequest(limit=1))
    assert [(r["event_kind"], r["event_id"]) for r in events] == [
        ("INVOICE_ISSUED", str(invoice)),
        ("PAYMENT_RECEIVED", str(payment)),
    ]
    assert all(
        r["position_after_instant"] == LedgerPosition(invoice=10000, payment=3000).as_wire()
        for r in events
    )
    filtered = items(
        get(
            human,
            prop,
            customer,
            LedgerReadRequest(filters=LedgerFilter(at, at, "PAYMENT_RECEIVED")),
        )
    )
    assert (
        len(filtered) == 1
        and filtered[0]["position_after_instant"]
        == LedgerPosition(invoice=10000, payment=3000).as_wire()
    )


def test_ledger_runtime_new_commit_invalidates_history_composition_and_component_selections(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, invoice, _, _ = canonical_invoice(migrated_database_url)
    original = get(human, prop, customer)
    revision = str(data(original)["source_revision"])
    source = get(human, prop, customer, LedgerReadRequest(section="composition", limit=1))
    component = get(
        human,
        prop,
        customer,
        LedgerReadRequest(
            section="components", event_kind="INVOICE_ISSUED", event_id=invoice, limit=1
        ),
    )
    assert source["next_cursor"] is not None and component["next_cursor"] is not None
    with psycopg.connect(migrated_database_url) as connection:
        seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=customer,
            amount=123,
        )
    for query in [
        LedgerReadRequest(revision=revision),
        LedgerReadRequest(section="composition", cursor=str(source["next_cursor"])),
        LedgerReadRequest(
            section="components",
            event_kind="INVOICE_ISSUED",
            event_id=invoice,
            cursor=str(component["next_cursor"]),
        ),
    ]:
        with pytest.raises(LedgerSnapshotChangedError):
            get(human, prop, customer, query)
    assert data(get(human, prop, customer))["source_revision"] != revision


def test_ledger_runtime_forged_nonexistent_anchors_are_rejected_in_every_section(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, invoice, _, _ = canonical_invoice(migrated_database_url)
    revision = str(data(get(human, prop, customer))["source_revision"])
    for section in ["history", "composition", "components"]:
        query = LedgerReadRequest(
            section=section,
            event_kind="INVOICE_ISSUED" if section == "components" else None,
            event_id=invoice if section == "components" else None,
        )
        scope = query.fingerprint(prop, customer)
        token = (
            LedgerCursor(
                scope,
                revision,
                LedgerEventKey(datetime.now(UTC), "INVOICE_ISSUED", uuid4()),
            ).encode()
            if section == "history"
            else LedgerDetailCursor(
                scope,
                revision,
                "INVOICE:" + str(uuid4()) if section == "composition" else "f" * 64,
            ).encode()
        )
        with pytest.raises(LedgerInvalidError):
            get(human, prop, customer, replace(query, cursor=token))


def test_ledger_runtime_empty_and_large_exact_balances_do_not_net_or_round(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, customer, _ = setup_sources(connection)
    empty = get(human, prop, customer)
    assert items(empty) == [] and data(empty)["position"] == LedgerPosition().as_wire()
    with psycopg.connect(migrated_database_url) as connection:
        for _ in range(2):
            seed_payment(
                connection,
                actor_id=human,
                property_id=prop,
                customer_id=customer,
                amount=9000000000000000,
            )
    result = get(human, prop, customer)
    assert data(result)["position"] == LedgerPosition(payment=18000000000000000).as_wire()
    assert len(items(result)) == 2


def test_ledger_runtime_coherent_snapshot_survives_concurrent_refund_commit(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, payment = payment_source(migrated_database_url)
    before = get(human, prop, customer)

    class ConcurrentReader(CustomerLedgerReadService):
        @contextmanager
        def _read(self) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
            with super()._read() as connection:
                connection.execute(
                    "SELECT app.customer_ledger_snapshot(%s,%s,%s)",
                    (prop, customer, human),
                ).fetchone()
                create_usd_refund(
                    refunds(),
                    prop,
                    create(payment, 3000),
                    actor=actor(human, prop, "refunds.create"),
                )
                yield connection

    coherent = ConcurrentReader(runtime_database_url()).get(
        customer,
        LedgerReadRequest(revision=str(data(before)["source_revision"])),
        actor=actor(human, prop, LEDGER_CAPABILITY),
    )
    assert coherent == before
    after = get(human, prop, customer)
    assert data(after)["source_revision"] != data(before)["source_revision"]
    assert data(after)["position"] == LedgerPosition(payment=7000).as_wire()


def test_ledger_runtime_denies_other_property_missing_customer_and_wrong_expected_property(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, _ = payment_source(migrated_database_url)
    reader = CustomerLedgerReadService(runtime_database_url())
    before = snapshot(migrated_database_url)
    with pytest.raises(LedgerNotFoundError):
        reader.get(
            customer,
            LedgerReadRequest(),
            actor=actor(human, uuid4(), LEDGER_CAPABILITY),
        )
    with pytest.raises(LedgerNotFoundError):
        reader.get(uuid4(), LedgerReadRequest(), actor=actor(human, prop, LEDGER_CAPABILITY))
    with pytest.raises(LedgerNotFoundError):
        reader.get(
            customer,
            LedgerReadRequest(),
            actor=actor(human, prop, LEDGER_CAPABILITY),
            expected_property=uuid4(),
        )
    assert snapshot(migrated_database_url) == before


def test_ledger_runtime_denies_disabled_missing_and_nonhuman_actor_even_with_ledger_grant(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, _ = payment_source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        nonhuman = register_billing_service_principal(
            connection, property_id=prop, created_by=human
        )
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s",
            (human,),
        )
    for who in [human, nonhuman, uuid4()]:
        with pytest.raises(LedgerAuthorizationError):
            get(who, prop, customer)
        with pytest.raises(LedgerAuthorizationError):
            CustomerLedgerReadService(runtime_database_url()).customers(
                1, None, actor=actor(who, prop, LEDGER_CAPABILITY)
            )


def test_ledger_runtime_picker_exposes_only_names_and_identities_with_complete_uuid_pages(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, _ = payment_source(migrated_database_url)
    reader = CustomerLedgerReadService(runtime_database_url())
    after = None
    rows = []
    before = snapshot(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        count_row = connection.execute("SELECT count(*) FROM app.customers").fetchone()
        assert count_row is not None
        total = int(count_row[0])
    for _ in range(total // 100 + 1):
        page = reader.customers(100, after, actor=actor(human, prop, LEDGER_CAPABILITY))
        rows.extend(cast(list[dict[str, object]], page["items"]))
        if page["next_cursor"] is None:
            break
        after = UUID(str(page["next_cursor"]))
    else:
        raise AssertionError("Customer picker pagination did not terminate")
    assert any(r["id"] == str(customer) for r in rows)
    assert (
        all(set(r) == {"id", "legal_name"} for r in rows)
        and len({r["id"] for r in rows}) == len(rows) == total
    )
    assert snapshot(migrated_database_url) == before


def test_ledger_runtime_debit_adjustment_and_its_reversal_remain_distinct_events(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, invoice, line = issued_invoice(migrated_database_url)
    adjustment, reversal = uuid4(), uuid4()
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            (
                "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adju"
                "stment_type,amount_usd_cents,source_reference,reason,occurred_at,actor"
                "_id,authorization_reference) VALUES(%s,%s,%s,'DEBIT',500,'ledger-test'"
                ",'Approved debit correction',clock_timestamp(),%s,'invoices.adjust')"
            ),
            (adjustment, invoice, line, human),
        )
    adjusted = get(human, prop, customer)
    assert data(adjusted)["position"] == LedgerPosition(invoice=10500).as_wire()
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            (
                "INSERT INTO app.invoice_adjustment_reversals(id,invoice_adjustment_id,"
                "reason,occurred_at,actor_id,authorization_reference) VALUES(%s,%s,'Inc"
                "orrect debit',clock_timestamp(),%s,'invoices.adjust')"
            ),
            (reversal, adjustment, human),
        )
    result = get(human, prop, customer)
    assert data(result)["position"] == LedgerPosition(invoice=10000).as_wire()
    assert [(r["event_kind"], r["invoice_effect_usd_cents"]) for r in items(result)[1:]] == [
        ("INVOICE_ADJUSTED", "500"),
        ("INVOICE_ADJUSTMENT_REVERSED", "-500"),
    ]


def test_ledger_runtime_credit_to_charge_and_reversal_preserve_separate_invoice(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, credit, invoice, _, payment = credit_source(
        migrated_database_url, period_start=date(2026, 5, 1)
    )
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT payer_customer_id FROM app.payments WHERE id=%s", (payment,)
        ).fetchone()
        assert row is not None
        customer = UUID(str(row[0]))
    late_service().finalize_decision(
        prop,
        invoice,
        FinalizeLatePaymentDecisionCommand(
            uuid4(), DecisionOutcome.CONFIRMED_DEFAULT, 8000, "Approved charge"
        ),
        actor=late_payment_actor(human, prop),
    )
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT id FROM app.late_payment_charges WHERE source_invoice_id=%s",
            (invoice,),
        ).fetchone()
        assert row is not None
        charge = UUID(str(row[0]))
    result = credits().apply(
        prop,
        credit,
        ApplyCreditCommand(
            uuid4(),
            {
                "mode": "DIRECT_CHARGE",
                "late_payment_charge_id": str(charge),
                "amount_usd_cents": 4000,
            },
        ),
        actor=actor(human, prop, "credits.apply"),
    )
    applied = get(human, prop, customer)
    assert (
        data(applied)["position"]
        == LedgerPosition(invoice=80000, charge=4000, credit=96000).as_wire()
    )
    credits().reverse_application(
        prop,
        application_id(result),
        ReverseCreditApplicationCommand(uuid4(), "Correct application"),
        actor=actor(human, prop, "credits.applications.reverse"),
    )
    reversed = get(human, prop, customer)
    assert (
        data(reversed)["position"]
        == LedgerPosition(invoice=80000, charge=8000, credit=100000).as_wire()
    )
    effects = [
        r
        for r in items(reversed)
        if r["event_kind"] in {"CREDIT_APPLIED", "CREDIT_APPLICATION_REVERSED"}
    ]
    assert [
        (
            r["invoice_effect_usd_cents"],
            r["charge_effect_usd_cents"],
            r["credit_effect_usd_cents"],
        )
        for r in effects
    ] == [("0", "-4000", "-4000"), ("0", "4000", "4000")]


def test_ledger_runtime_deposit_receipt_reversal_keeps_held_liability_and_payment_separate(
    migrated_database_url: str,  # noqa: F811
) -> None:
    service, staff, _, deposit, _, receipts = deposit_source(migrated_database_url)
    human, prop = service.actor_id, service.property_id
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT customer_id FROM app.deposits WHERE id=%s", (deposit,)
        ).fetchone()
        assert row is not None
        customer = UUID(str(row[0]))
    before = get(human, prop, customer)
    assert data(before)["position"] == LedgerPosition(payment=10000, pet_deposit=20000).as_wire()
    reverse_receipt_as_owner(
        service,
        ReverseDepositReceiptCommand(uuid4(), uuid4(), receipts[0], "Incorrect receipt"),
        actor=staff,
    )
    after = get(human, prop, customer)
    assert data(after)["position"] == LedgerPosition(payment=20000, pet_deposit=10000).as_wire()
    assert any(r["event_kind"] == "DEPOSIT_RECEIPT_REVERSED" for r in items(after))


def test_ledger_runtime_original_khr_evidence_is_exact_without_repricing(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        payment = fx_payment(connection)
        row = connection.execute(
            (
                "SELECT confirmed_by,property_id,payer_customer_id,usd_accounting_value"
                "_cents FROM app.payments WHERE id=%s"
            ),
            (payment,),
        ).fetchone()
        assert row is not None
        human, prop, customer, usd = row
    before = snapshot(migrated_database_url)
    result = get(human, prop, customer)
    assert data(result)["position"] == LedgerPosition(payment=usd).as_wire()
    received = next(r for r in items(result) if r["event_kind"] == "PAYMENT_RECEIVED")
    audit = cast(dict[str, object], received["source_audit"])
    assert audit["received_currency"] == "KHR" and isinstance(audit["received_amount_minor"], str)
    assert snapshot(migrated_database_url) == before


def test_ledger_runtime_http_uses_only_application_credentials_and_denies_source_commands(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, _ = payment_source(migrated_database_url)
    settings = Settings(database_url=SecretStr(runtime_database_url()))
    before = snapshot(migrated_database_url)
    with TestClient(
        create_app(settings, actor_resolver=lambda _: actor(human, prop, LEDGER_CAPABILITY))
    ) as api:
        response = api.get(f"/api/v1/customers/{customer}/account-ledger")
        assert (
            response.status_code == 200
            and response.json()["data"]["position"] == LedgerPosition(payment=10000).as_wire()
        )
        assert response.headers["cache-control"] == "private, no-store"
        assert api.get(f"/api/v1/customers/{customer}").status_code == 404
        assert api.get(f"/api/v1/properties/{prop}/customers").status_code == 403
        assert api.post(f"/api/v1/customers/{customer}/account-ledger").status_code == 405
    assert snapshot(migrated_database_url) == before


def test_ledger_read_migration_is_forward_only_and_preserves_populated48_sources(
    migrated_database_url: str,  # noqa: F811
) -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["20270406_256"]
    revision = scripts.get_revision("20260909_49")
    assert revision is not None and revision.down_revision == "20260909_48"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database("ledger_reads") as temporary:
        cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", temporary)
        command.upgrade(cfg, "20260909_48")
        with psycopg.connect(temporary) as connection:
            human, prop, _, customer, _ = setup_sources(connection)
            payment = seed_payment(
                connection,
                actor_id=human,
                property_id=prop,
                customer_id=customer,
                amount=12345,
            )
        before = snapshot(temporary)
        command.upgrade(cfg, "20260909_49")
        assert snapshot(temporary) == before
        with psycopg.connect(temporary) as connection:
            row = connection.execute(
                "SELECT app.customer_ledger_snapshot(%s,%s,%s)", (prop, customer, human)
            ).fetchone()
            assert row is not None
            assert row[0]["position"]["payment"] == "12345"
            assert connection.execute(
                "SELECT usd_accounting_value_cents FROM app.payments WHERE id=%s",
                (payment,),
            ).fetchone() == (12345,)


@pytest.mark.parametrize("role_url", [runtime_database_url, financial_database_url])
def test_ledger_read_migration_does_not_grant_direct_projection_access(
    migrated_database_url: str,  # noqa: F811
    role_url: Callable[[], str],
) -> None:
    for view in VIEWS:
        with psycopg.connect(role_url()) as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT * FROM app." + view + " LIMIT 1")


def test_ledger_runtime_third_party_allocation_reversal_keeps_payer_and_beneficiary_separate(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, invoices = allocation_source(migrated_database_url)
    _, _, payer, _ = payment_source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            (
                "SELECT i.customer_id,l.id FROM app.invoices i JOIN app.invoice_lines l"
                " ON l.invoice_id=i.id WHERE i.id=%s"
            ),
            (invoices[0],),
        ).fetchone()
        assert row is not None
        beneficiary, line = UUID(str(row[0])), UUID(str(row[1]))
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=payer,
            amount=80000,
            scope="THIRD_PARTY_IDENTIFIED",
            invoice_id=invoices[0],
        )
    posted = allocations().post(
        prop,
        payment,
        designated(invoices[0], line, 80000),
        actor=allocation_actor(human, prop),
    )
    allocation = UUID(str(cast(list[object], posted["allocation_ids"])[0]))
    allocations().reverse_allocation(
        prop,
        allocation,
        ReverseAllocationCommand(uuid4(), "Incorrect third-party attribution"),
        actor=allocation_actor(human, prop),
    )
    payer_events = items(get(human, prop, payer))
    target_events = items(get(human, prop, beneficiary))
    payer_reversal = next(
        r
        for r in payer_events
        if r["event_kind"] == "PAYMENT_ALLOCATION_REVERSED" and r["payment_id"] == str(payment)
    )
    target_reversal = next(
        r
        for r in target_events
        if r["event_kind"] == "PAYMENT_ALLOCATION_REVERSED" and r["payment_id"] == str(payment)
    )
    assert (
        payer_reversal["payment_effect_usd_cents"],
        payer_reversal["invoice_effect_usd_cents"],
    ) == ("80000", "0")
    assert (
        target_reversal["payment_effect_usd_cents"],
        target_reversal["invoice_effect_usd_cents"],
    ) == ("0", "80000")
    assert data(get(human, prop, payer))["position"] == LedgerPosition(payment=90000).as_wire()


def test_ledger_read_functions_have_narrow_stable_privileges_and_use_read_only_repeatable_read(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, customer, _ = payment_source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        rows = connection.execute(
            "SELECT p.proname,p.provolatile,p.prosecdef,p.proconfig,has_function_pr"
            "ivilege('prm_runtime',p.oid,'EXECUTE'),has_function_privilege('prm_fin"
            "ancial',p.oid,'EXECUTE'),has_function_privilege('prm_bootstrap',p.oid,"
            "'EXECUTE'),EXISTS(SELECT 1 FROM aclexplode(COALESCE(p.proacl,acldefaul"
            "t('f',p.proowner))) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE'"
            ") FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.n"
            "spname='app' AND p.proname IN('customer_ledger_snapshot','customer_led"
            "ger_page','customer_ledger_customers')"
        ).fetchall()
        assert len(rows) == 3
        for row in rows:
            assert row[1:3] == ("s", True) and "search_path=pg_catalog" in row[3]
            assert row[4:] == (True, False, False, False)
    observations = []

    class ObservedReader(CustomerLedgerReadService):
        @contextmanager
        def _read(self) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
            with super()._read() as connection:
                observations.append(
                    connection.execute(
                        "SELECT current_setting('transaction_isolation'),current_setting('trans"
                        "action_read_only'),current_setting('statement_timeout'),current_settin"
                        "g('lock_timeout')"
                    ).fetchone()
                )
                yield connection

    ObservedReader(runtime_database_url()).get(
        customer, LedgerReadRequest(), actor=actor(human, prop, LEDGER_CAPABILITY)
    )
    assert observations == [("repeatable read", "on", "5s", "3s")]


def test_ledger_runtime_complete_pages_over_one_hundred_keep_revision_and_exact_totals(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, customer, _ = setup_sources(connection)
        payments = {
            str(
                seed_payment(
                    connection,
                    actor_id=human,
                    property_id=prop,
                    customer_id=customer,
                    amount=amount,
                )
            )
            for amount in range(1, 106)
        }
    before = snapshot(migrated_database_url)
    first = get(human, prop, customer, LedgerReadRequest(limit=100))
    revision = str(data(first)["source_revision"])
    assert len(items(first)) == 100 and first["next_cursor"] is not None
    second = get(
        human,
        prop,
        customer,
        LedgerReadRequest(limit=100, cursor=str(first["next_cursor"]), revision=revision),
    )
    assert len(items(second)) == 5 and second["next_cursor"] is None
    history = items(first) + items(second)
    assert {r["payment_id"] for r in history} == payments
    assert len({r["event_id"] for r in history}) == data(first)["event_count"] == 105
    assert (
        data(first)["position"]
        == data(second)["position"]
        == LedgerPosition(payment=sum(range(1, 106))).as_wire()
    )
    composition = pages(
        human,
        prop,
        customer,
        LedgerReadRequest(section="composition", limit=100, revision=revision),
    )
    assert len(composition) == 105
    assert {r["balance_source_id"] for r in composition} == payments
    assert sum(int(str(r["balance_usd_cents"])) for r in composition) == 5565
    assert snapshot(migrated_database_url) == before


def test_ledger_runtime_rejects_offsetting_source_errors_even_when_aggregate_still_matches(
    migrated_database_url: str,  # noqa: F811
) -> None:
    # Fault injection is confined to a separate disposable test database. Neither
    # the shared fixture nor published source/view definitions are modified.
    with _temporary_migration_database("ledger_source_fault") as temporary:
        cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", temporary)
        command.upgrade(cfg, "head")
        with psycopg.connect(temporary) as connection:
            human, prop, _, customer, _ = setup_sources(connection)
            ids = [
                seed_payment(
                    connection, actor_id=human, property_id=prop, customer_id=customer, amount=100
                )
                for _ in range(2)
            ]
        before = snapshot(temporary)
        reader = CustomerLedgerReadService(
            _url_with_database(runtime_database_url(), urlsplit(temporary).path.removeprefix("/"))
        )
        who = actor(human, prop, LEDGER_CAPABILITY)
        assert data(reader.get(customer, LedgerReadRequest(), actor=who))["position"] == (
            LedgerPosition(payment=200).as_wire()
        )
        with psycopg.connect(temporary) as connection:
            original = connection.execute(
                "SELECT pg_get_viewdef('app.customer_ledger_balance_sources'::regclass,true)"
            ).fetchone()
            assert original is not None
            definition = str(original[0]).strip().removesuffix(";")
            connection.execute(
                sql.SQL(
                    "CREATE OR REPLACE VIEW app.customer_ledger_balance_sources "
                    "WITH(security_invoker=true) AS SELECT property_id,customer_id,balance_kind,"
                    "balance_source_id,invoice_id,invoice_line_id,late_payment_charge_id,category,"
                    "description,balance_usd_cents+CASE balance_source_id WHEN {} THEN 1 "
                    "WHEN {} THEN -1 ELSE 0 END AS balance_usd_cents FROM ({}) s"
                ).format(sql.Literal(ids[0]), sql.Literal(ids[1]), sql.SQL(definition))
            )
            assert connection.execute(
                "SELECT sum(balance_usd_cents) FROM app.customer_ledger_balance_sources "
                "WHERE customer_id=%s",
                (customer,),
            ).fetchone() == (200,)
        with pytest.raises(LedgerUnavailableError):
            reader.get(customer, LedgerReadRequest(), actor=who)
        with psycopg.connect(temporary) as connection:
            with pytest.raises(psycopg.Error) as failure:
                connection.execute(
                    "SELECT app.customer_ledger_snapshot(%s,%s,%s)", (prop, customer, human)
                )
            assert failure.value.sqlstate == "P4902"
        assert snapshot(temporary) == before
