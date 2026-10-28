"""Migration 20270328_247 (V1-060 B6, DL-103): many items on one Miscellaneous Invoice.

The owner asked on 2026-10-28 why two charges make two Invoices and chose "Yes, build it now"
with four rules: a whole quantity and a unit price in US cents, the amount exactly the quantity
times the unit price; a part payment pays the items from the top down; one reason and one approval
for the whole Invoice; at most 20 items on one Invoice.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from payment_test_support import seed_payment
from property_rental.invoice import (
    CreateInvoiceDraftCommand,
    CreateItemsInvoiceDraftCommand,
    InvoiceConflictError,
    InvoiceIdempotencyKeyReused,
    InvoiceInvalidError,
    InvoiceItem,
    InvoiceNotFoundError,
    InvoiceVersionConflict,
    IssueInvoiceCommand,
    RecordOneTimeChargeCommand,
    ReplaceInvoiceDraftItemsCommand,
)
from property_rental.payment_allocation import PaymentAllocationService, PostAllocationsCommand
from rent_month_test_support import bill_unbilled_rent_months
from test_final_settlement_migration import start, today
from test_final_settlement_preview_migration import preview
from test_invoice_migration import (
    financial_database_url,
    invoice_api_actor,
    runtime_database_url,
    setup_signed_lease,
)
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_one_time_charges_migration import invoices
from test_payment_allocation_migration import actor as payment_actor
from test_termination_deposit_migration import terminate

CREATE = (
    "app.create_items_invoice_draft(uuid,uuid,uuid,text,uuid,uuid,uuid,uuid,uuid,text,text,jsonb)"
)
REPLACE = (
    "app.replace_invoice_draft_items("
    "uuid,uuid,uuid,uuid,text,integer,uuid,uuid,text,text,text,jsonb,uuid)"
)
INTERNAL = (
    "app.invoice_items_input(jsonb)",
    "app.record_invoice_item_charge(uuid,uuid,text,timestamp with time zone,uuid,uuid,uuid,uuid,"
    "text,integer,bigint,text,text)",
    "app.insert_invoice_item_line(uuid,uuid,integer,uuid,timestamp with time zone)",
)
REASON = "Keys, lock and cleaning"
EVIDENCE = "Front desk log 31"
CHANGE = "Customer asked for one more key; the lock stays"
KEYS_LOCK_CLEANING = (("Key copy", 2, 1_500), ("Door lock", 1, 3_999), ("Cleaning hour", 3, 1_250))


def _lease(url: str) -> tuple[UUID, UUID, UUID, UUID]:
    """Human, Property, Primary Tenant and a signed Lease from last January to next December."""
    now = today(url)
    with psycopg.connect(url) as connection:
        return setup_signed_lease(
            connection,
            start_date=now.replace(year=now.year - 1, month=1, day=1),
            end_date=now.replace(year=now.year + 1, month=12, day=31),
            with_occupancy=False,
        )


def _items(*rows: tuple[str, int, int]) -> tuple[InvoiceItem, ...]:
    return tuple(InvoiceItem(uuid4(), name, quantity, price) for name, quantity, price in rows)


def _create(
    customer: UUID, lease: UUID | None, items: tuple[InvoiceItem, ...]
) -> CreateItemsInvoiceDraftCommand:
    return CreateItemsInvoiceDraftCommand(uuid4(), customer, lease, REASON, EVIDENCE, items)


def _change(
    customer: UUID, lease: UUID | None, items: tuple[InvoiceItem, ...], version: object
) -> ReplaceInvoiceDraftItemsCommand:
    return ReplaceInvoiceDraftItemsCommand(
        uuid4(), customer, lease, REASON, EVIDENCE, CHANGE, items, cast(int, version)
    )


def _rows(resource: dict[str, object]) -> list[tuple[object, ...]]:
    return [
        (
            line["sequence"],
            line["description"],
            line["original_amount"]["minor_units"],
            line["source"]["id"],
        )
        for line in cast(list[dict[str, Any]], resource["lines"])
    ]


def test_one_invoice_bills_every_item_at_exactly_quantity_times_unit_price(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, customer, lease = _lease(url)
    staff = invoice_api_actor(human, prop)
    key_copy, lock, cleaning = _items(*KEYS_LOCK_CLEANING)
    command = _create(customer, lease, (key_copy, lock, cleaning))
    draft = invoices().create_items_draft(prop, command, actor=staff)
    assert (draft["status"], draft["category"], draft["due_date"]) == (
        "DRAFT",
        "MISCELLANEOUS_CHARGES",
        None,
    )
    assert (draft["customer_id"], draft["lease_id"]) == (str(customer), str(lease))
    assert draft["original_total"] == {"currency": "USD", "minor_units": 10_749}
    assert _rows(draft) == [
        (1, "Key copy", 3_000, str(key_copy.charge_id)),
        (2, "Door lock", 3_999, str(lock.charge_id)),
        (3, "Cleaning hour", 3_750, str(cleaning.charge_id)),
    ]
    assert cast(list[dict[str, Any]], draft["lines"])[0]["calculation_evidence"] == {
        "formula": "authorized_source_quantity_times_unit_price",
        "authorized_obligation_id": str(key_copy.charge_id),
        "authorized_amount_usd_cents": 3_000,
        "quantity": 2,
        "unit_price_usd_cents": 1_500,
        "reason": REASON,
        "evidence_reference": EVIDENCE,
        "source_reference": f"one-time-charge:{key_copy.charge_id}",
    }
    # Each item is its own approved charge, all with the one reason and approval (owner rule 3).
    with psycopg.connect(url) as connection:
        charges = connection.execute(
            "SELECT id,quantity,unit_price_usd_cents,authorized_amount_usd_cents,reason,"
            "evidence_reference,authorization_reference,lease_id,customer_id "
            "FROM app.authorized_nonrecurring_obligations WHERE id=ANY(%s)",
            ([key_copy.charge_id, lock.charge_id, cleaning.charge_id],),
        ).fetchall()
        recorded = connection.execute(
            "SELECT count(*) FROM app.audit_events "
            "WHERE action='invoice.one_time_charge.recorded' AND entity_id=ANY(%s)",
            ([key_copy.charge_id, lock.charge_id, cleaning.charge_id],),
        ).fetchone()
        created = connection.execute(
            "SELECT reason,authorization_evidence->'authorized_obligation_ids' "
            "FROM app.audit_events WHERE action='invoice.created' AND entity_id=%s",
            (UUID(str(draft["id"])),),
        ).fetchall()
    same = (REASON, EVIDENCE, "invoices.create", lease, customer)
    assert sorted(charges, key=lambda row: str(row[0])) == sorted(
        [
            (key_copy.charge_id, 2, 1_500, 3_000, *same),
            (lock.charge_id, 1, 3_999, 3_999, *same),
            (cleaning.charge_id, 3, 1_250, 3_750, *same),
        ],
        key=lambda row: str(row[0]),
    )
    assert recorded == (3,)
    assert created == [
        (
            "Invoice DRAFT created from typed items",
            [str(key_copy.charge_id), str(lock.charge_id), str(cleaning.charge_id)],
        )
    ]
    # An exact replay returns the saved Draft; the key with other input is refused, and the same
    # charges under a new key would bill them twice.
    assert invoices().create_items_draft(prop, command, actor=staff) == draft
    with pytest.raises(InvoiceIdempotencyKeyReused):
        invoices().create_items_draft(prop, replace(command, reason="Other reason"), actor=staff)
    with pytest.raises(InvoiceConflictError):
        invoices().create_items_draft(prop, replace(command, idempotency_key=uuid4()), actor=staff)
    issued = invoices().issue(
        prop,
        UUID(str(draft["id"])),
        IssueInvoiceCommand(uuid4(), cast(int, draft["version"])),
        actor=staff,
    )
    assert issued["status"] == "UNPAID"
    assert issued["due_date"] == (today(url) + timedelta(days=7)).isoformat()
    assert _rows(issued) == _rows(draft)


def test_a_part_payment_pays_the_items_from_the_top_down(migrated_database_url: str) -> None:
    url = migrated_database_url
    human, prop, customer, lease = _lease(url)
    staff = invoice_api_actor(human, prop)
    draft = invoices().create_items_draft(
        prop, _create(customer, lease, _items(*KEYS_LOCK_CLEANING)), actor=staff
    )
    invoice = UUID(str(draft["id"]))
    invoices().issue(prop, invoice, IssueInvoiceCommand(uuid4(), 1), actor=staff)
    with psycopg.connect(url) as connection:
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=customer,
            amount=5_000,
            lease_id=lease,
            invoice_id=invoice,
        )
    payments = PaymentAllocationService(runtime_database_url(), financial_database_url())
    cashier = payment_actor(human, prop)
    proposal = payments.proposal(prop, payment, actor=cashier)
    targets = cast(list[dict[str, Any]], proposal["targets"])
    lines = cast(list[dict[str, Any]], draft["lines"])
    assert [target["invoice_id"] for target in targets] == [str(invoice)]
    assert [
        (detail["invoice_line_id"], detail["amount_usd_cents"]) for detail in targets[0]["details"]
    ] == [(lines[0]["id"], 3_000), (lines[1]["id"], 2_000)]
    payments.post(
        prop,
        payment,
        PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
        actor=cashier,
    )
    paid = invoices().get(invoice, actor=staff)
    assert paid["status"] == "PARTIALLY_PAID"
    assert [
        line["outstanding_balance"]["minor_units"]
        for line in cast(list[dict[str, Any]], paid["lines"])
    ] == [0, 1_999, 3_750]


def test_edit_items_keeps_the_same_items_and_withdraws_the_others_with_the_reason(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, customer, lease = _lease(url)
    staff = invoice_api_actor(human, prop)
    key_copy, lock, cleaning = _items(*KEYS_LOCK_CLEANING)
    draft = invoices().create_items_draft(
        prop, _create(customer, lease, (key_copy, lock, cleaning)), actor=staff
    )
    invoice = UUID(str(draft["id"]))
    cleaning_line = cast(list[dict[str, Any]], draft["lines"])[2]["id"]
    three_keys = InvoiceItem(uuid4(), "Key copy", 3, 1_500)
    bulbs = InvoiceItem(uuid4(), "Light bulb", 4, 250)
    change = _change(customer, lease, (cleaning, three_keys, bulbs), draft["version"])
    changed = invoices().replace_draft_items(prop, invoice, change, actor=staff)
    version = cast(int, draft["version"]) + 1
    assert changed["version"] == version
    assert changed["status"] == "DRAFT"
    assert changed["original_total"] == {"currency": "USD", "minor_units": 9_250}
    assert _rows(changed) == [
        (1, "Cleaning hour", 3_750, str(cleaning.charge_id)),
        (2, "Key copy", 4_500, str(three_keys.charge_id)),
        (3, "Light bulb", 1_000, str(bulbs.charge_id)),
    ]
    # The item that stayed keeps its line and its charge; the others are withdrawn with the
    # reason for the change, and the Draft history keeps them.
    assert cast(list[dict[str, Any]], changed["lines"])[0]["id"] == cleaning_line
    with psycopg.connect(url) as connection:
        withdrawn = connection.execute(
            "SELECT before_state->>'authorized_obligation_id',reason,changed_by "
            "FROM app.invoice_draft_revision_events "
            "WHERE invoice_id=%s AND entity_kind='LINE' AND operation='DELETE'",
            (invoice,),
        ).fetchall()
        audit = connection.execute(
            "SELECT reason,authorization_evidence->'authorized_obligation_ids' "
            "FROM app.audit_events WHERE action='invoice.draft_corrected' AND entity_id=%s",
            (invoice,),
        ).fetchall()
        charges = connection.execute(
            "SELECT count(*) FROM app.authorized_nonrecurring_obligations WHERE id=ANY(%s)",
            ([key_copy.charge_id, lock.charge_id],),
        ).fetchone()
    assert sorted(withdrawn) == sorted(
        [(str(key_copy.charge_id), CHANGE, human), (str(lock.charge_id), CHANGE, human)]
    )
    assert audit == [
        (CHANGE, [str(cleaning.charge_id), str(three_keys.charge_id), str(bulbs.charge_id)])
    ]
    # Approved charges are append-only: the withdrawn charges stay, on no Invoice line.
    assert charges == (2,)
    assert invoices().replace_draft_items(prop, invoice, change, actor=staff) == changed
    with pytest.raises(InvoiceVersionConflict):
        invoices().replace_draft_items(
            prop, invoice, replace(change, idempotency_key=uuid4()), actor=staff
        )
    # A kept item must keep its values, and a withdrawn charge cannot come back.
    for items in (
        (replace(cleaning, description="Cleaning hours"), three_keys, bulbs),
        (cleaning, three_keys, bulbs, lock),
    ):
        with pytest.raises(InvoiceConflictError):
            invoices().replace_draft_items(
                prop, invoice, _change(customer, lease, items, version), actor=staff
            )
    invoices().issue(prop, invoice, IssueInvoiceCommand(uuid4(), version), actor=staff)
    with pytest.raises(InvoiceInvalidError):
        invoices().replace_draft_items(
            prop, invoice, _change(customer, lease, (cleaning,), version + 1), actor=staff
        )


def test_only_a_draft_made_from_typed_items_can_be_edited(migrated_database_url: str) -> None:
    url = migrated_database_url
    human, prop, customer, lease = _lease(url)
    staff = invoice_api_actor(human, prop)
    single = RecordOneTimeChargeCommand(
        uuid4(),
        "MISCELLANEOUS_CHARGES",
        customer,
        lease,
        None,
        "Replacement key card",
        1_500,
        "Customer lost key card",
        "Front desk log 32",
    )
    invoices().record_one_time_charge(prop, single, actor=staff)
    old = invoices().create_draft(
        prop, CreateInvoiceDraftCommand(uuid4(), single.charge_id), actor=staff
    )
    with pytest.raises(InvoiceInvalidError):
        invoices().replace_draft_items(
            prop,
            UUID(str(old["id"])),
            _change(customer, lease, _items(("Key card", 1, 1_500)), old["version"]),
            actor=staff,
        )
    draft = invoices().create_items_draft(
        prop, _create(customer, lease, _items(("Key copy", 2, 1_500))), actor=staff
    )
    invoice = UUID(str(draft["id"]))
    items = _items(("Key copy", 1, 1_500))
    # The Customer must be the Lease's Primary Tenant, and a Customer without a Lease must exist.
    with pytest.raises(InvoiceInvalidError):
        invoices().replace_draft_items(
            prop, invoice, _change(uuid4(), lease, items, draft["version"]), actor=staff
        )
    with pytest.raises(InvoiceNotFoundError):
        invoices().replace_draft_items(
            prop, invoice, _change(uuid4(), None, items, draft["version"]), actor=staff
        )
    with pytest.raises(InvoiceNotFoundError):
        invoices().replace_draft_items(
            prop, uuid4(), _change(customer, lease, items, draft["version"]), actor=staff
        )
    with pytest.raises(InvoiceInvalidError):
        invoices().create_items_draft(prop, _create(uuid4(), lease, items), actor=staff)
    # Moving the Draft to no Lease gives every item a new charge.
    moved = invoices().replace_draft_items(
        prop, invoice, _change(customer, None, items, draft["version"]), actor=staff
    )
    assert moved["lease_id"] is None
    assert _rows(moved) == [(1, "Key copy", 1_500, str(items[0].charge_id))]


def test_items_taken_off_a_draft_do_not_block_the_final_settlement(
    migrated_database_url: str,
) -> None:
    """A charge Edit items took off was withdrawn with a reason, like a charge a draft
    correction replaced: the preview lists it as information, not as a blocking issue."""
    url = migrated_database_url
    now = today(url)
    human, prop, customer, lease = _lease(url)
    staff = invoice_api_actor(human, prop)
    key_copy, lock = _items(("Key copy", 2, 1_500), ("Door lock", 1, 3_999))
    draft = invoices().create_items_draft(
        prop, _create(customer, lease, (key_copy, lock)), actor=staff
    )
    # Staff take the lock off and move the key copy to no Lease (a new charge).
    invoices().replace_draft_items(
        prop,
        UUID(str(draft["id"])),
        _change(customer, None, _items(("Key copy", 2, 1_500)), draft["version"]),
        actor=staff,
    )
    terminate(url, human, prop, lease, now, voluntary=False)
    bill_unbilled_rent_months(url, human, prop, lease)
    view = preview(prop, human, start(prop, human, lease))
    information = sorted(view["information"], key=lambda item: item["authorized_obligation_id"])
    assert information == sorted(
        [
            {
                "code": "CHARGE_REPLACED_BY_DRAFT_CORRECTION",
                "authorized_obligation_id": str(item.charge_id),
                "customer_id": str(customer),
                "category": "MISCELLANEOUS_CHARGES",
                "amount_usd_cents": amount,
                "replacement_authorized_obligation_id": None,
                "replacement_lease_id": None,
            }
            for item, amount in ((key_copy, 3_000), (lock, 3_999))
        ],
        key=lambda item: str(item["authorized_obligation_id"]),
    )
    assert view["blocking_issues"] == [] and view["ready"] is True


def test_the_database_refuses_items_outside_the_owner_rules(migrated_database_url: str) -> None:
    human, prop, customer, lease = _lease(migrated_database_url)
    good: dict[str, object] = {
        "charge_id": str(uuid4()),
        "description": "Key copy",
        "quantity": 2,
        "unit_price_usd_cents": 1_500,
    }
    refused: list[object] = [
        [],
        [{**good, "charge_id": str(uuid4())} for _ in range(21)],
        [good, good],
        [{**good, "quantity": 1.5}],
        [{**good, "quantity": "2"}],
        [{**good, "quantity": 0}],
        [{**good, "quantity": 10_000}],
        [{**good, "unit_price_usd_cents": 0}],
        [{**good, "unit_price_usd_cents": 1_000_000_000}],
        [{**good, "unit_price_usd_cents": 12.5}],
        [{**good, "amount_usd_cents": 3_000}],
        [{key: value for key, value in good.items() if key != "quantity"}],
        [{**good, "description": " Key copy"}],
        [{**good, "description": ""}],
        [{**good, "charge_id": "not-an-id"}],
        [{**good, "charge_id": str(UUID(int=0))}],
        {"items": [good]},
        [[good]],
    ]
    with psycopg.connect(financial_database_url()) as connection:
        for items in refused:
            with pytest.raises(psycopg.Error) as error:
                with connection.transaction():
                    connection.execute(
                        "SELECT app.create_items_invoice_draft("
                        "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            prop,
                            human,
                            uuid4(),
                            hashlib.sha256(str(items).encode()).hexdigest(),
                            uuid4(),
                            uuid4(),
                            uuid4(),
                            customer,
                            lease,
                            REASON,
                            EVIDENCE,
                            Jsonb(items),
                        ),
                    )
            assert error.value.sqlstate == "22023", items


def test_item_commands_are_least_privilege_and_an_item_amount_is_quantity_times_price(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, _, customer, _ = _lease(url)
    with psycopg.connect(url) as connection:
        for function in (CREATE, REPLACE):
            assert connection.execute(
                "SELECT routine.prosecdef,routine.proconfig @> ARRAY['search_path=pg_catalog'] "
                "FROM pg_catalog.pg_proc AS routine WHERE routine.oid=%s::regprocedure",
                (function,),
            ).fetchone() == (True, True)
        for role in ("public", "prm_runtime", "prm_financial", "prm_bootstrap"):
            for function in (CREATE, REPLACE):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (role == "prm_financial",), (role, function)
            for function in INTERNAL:
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (role, function)
        insert = (
            "INSERT INTO app.authorized_nonrecurring_obligations("
            "id,customer_id,lease_id,category,description,authorized_amount_usd_cents,"
            "governing_due_date,due_date_source,source_reference,authorized_at,authorized_by,"
            "authorization_reference,quantity,unit_price_usd_cents) VALUES (%s,%s,NULL,%s,"
            "'Key copy',%s,current_date+14,%s,%s,clock_timestamp(),%s,"
            "'invoice.nonrecurring.authorize',%s,%s)"
        )
        for category, amount, quantity, price in (
            ("MISCELLANEOUS_CHARGES", 3_001, 2, 1_500),
            ("MISCELLANEOUS_CHARGES", 3_000, 2, None),
            ("MISCELLANEOUS_CHARGES", 1_500, None, 1_500),
            ("MISCELLANEOUS_CHARGES", 3_000_000_000_000, 10_000, 300_000_000),
        ):
            identity = uuid4()
            with pytest.raises(psycopg.errors.CheckViolation) as error:
                with connection.transaction():
                    connection.execute(
                        insert,
                        (
                            identity,
                            customer,
                            category,
                            amount,
                            f"approved-obligation/{identity}",
                            f"approved-obligation/{identity}",
                            human,
                            quantity,
                            price,
                        ),
                    )
            assert error.value.diag.constraint_name == "authorized_nonrecurring_item_price"
        # Only a Miscellaneous item has a quantity (a Damage charge is checked first against its
        # inspection finding, so the clause is read from the constraint).
        definition = connection.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_catalog.pg_constraint "
            "WHERE conname='authorized_nonrecurring_item_price'"
        ).fetchone()
        assert definition is not None
        assert "category = 'MISCELLANEOUS_CHARGES'::text" in str(definition[0])
        identity = uuid4()
        connection.execute(
            insert,
            (
                identity,
                customer,
                "MISCELLANEOUS_CHARGES",
                3_000,
                f"approved-obligation/{identity}",
                f"approved-obligation/{identity}",
                human,
                2,
                1_500,
            ),
        )
        connection.rollback()


def test_invoice_items_migration_follows_add_occupant_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_current_head() == "20270328_247"
    revision = scripts.get_revision("20270328_247")
    assert revision is not None and revision.down_revision == "20270327_246"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
