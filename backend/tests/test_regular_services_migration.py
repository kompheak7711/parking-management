"""Migration 20270407_257 (V1.1 part 1, owner 2026-10-29, DL-115 (I)): Regular services and the
Services Invoice.

- Settings keeps Regular services with a set price; a repeat answers the same service, two never
  share a name, and one on an Invoice this year is removed only next year.
- A Services Invoice bills each Regular service at its Settings price times How many; a later
  price change never changes it, Edit items cannot change it, and a removed service is refused.
- Owner 2026-10-29 19:20 (decision card): its lines count in the "Rent and Services" report bar.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.invoice import (
    CreateServicesInvoiceDraftCommand,
    InvoiceInvalidError,
    InvoiceItem,
    InvoiceNotFoundError,
    IssueInvoiceCommand,
    ReplaceInvoiceDraftItemsCommand,
    ServiceInvoiceItem,
)
from property_rental.report_totals import INCOME_GROUPS
from property_rental.service_settings_api import (
    PostgresServiceSettingsFlow,
    RegularServiceChange,
    RegularServiceCreate,
    ServiceSettingsConflict,
    ServiceSettingsNotFound,
)
from test_final_settlement_migration import today
from test_invoice_migration import invoice_api_actor, runtime_database_url, setup_signed_lease
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_one_time_charges_migration import invoices
from test_report_month_facts_migration import facts


def _lease(url: str) -> tuple[UUID, UUID, UUID, UUID]:
    now = today(url)
    with psycopg.connect(url) as connection:
        return setup_signed_lease(
            connection,
            start_date=now.replace(year=now.year - 1, month=1, day=1),
            end_date=now.replace(year=now.year + 1, month=12, day=31),
            with_occupancy=False,
        )


def _service(prop: UUID, human: UUID, name: str, cents: int) -> dict[str, Any]:
    body = RegularServiceCreate(
        regular_service_id=uuid4(), name_en=name, name_km=None, price_usd_cents=cents
    )
    return PostgresServiceSettingsFlow(runtime_database_url()).save_regular_service(
        prop, human, body.regular_service_id, body
    )


def test_settings_keep_regular_services_with_a_set_price(migrated_database_url: str) -> None:
    human, prop, _, _ = _lease(migrated_database_url)
    flow = PostgresServiceSettingsFlow(runtime_database_url())
    body = RegularServiceCreate(
        regular_service_id=uuid4(), name_en="Extra cleaning", name_km=None, price_usd_cents=1_500
    )
    added = flow.save_regular_service(prop, human, body.regular_service_id, body)
    assert added == {
        "regular_service_id": str(body.regular_service_id),
        "name_en": "Extra cleaning",
        "name_km": None,
        "price_usd_cents": 1_500,
        "removed": False,
        "version": 1,
        "used_this_year": 0,
    }
    # The same form again after a lost answer answers the same service.
    assert flow.save_regular_service(prop, human, body.regular_service_id, body) == added
    with pytest.raises(ServiceSettingsConflict):
        _service(prop, human, "extra CLEANING", 900)
    changed = flow.save_regular_service(
        prop,
        human,
        body.regular_service_id,
        RegularServiceChange(
            name_en="Extra cleaning", name_km="សម្អាតបន្ថែម", price_usd_cents=1_800, version=1
        ),
    )
    assert (changed["price_usd_cents"], changed["version"]) == (1_800, 2)
    listed = flow.read_regular_services(prop)["regular_services"]
    assert [item["regular_service_id"] for item in cast(list[dict[str, Any]], listed)] == [
        str(body.regular_service_id)
    ]
    removed = flow.remove_regular_service(prop, human, body.regular_service_id, 2)
    assert removed["removed"] is True
    assert flow.read_regular_services(prop)["regular_services"] == []
    with pytest.raises(ServiceSettingsNotFound):
        flow.remove_regular_service(prop, human, body.regular_service_id, 3)


def test_a_services_invoice_takes_each_price_from_settings(migrated_database_url: str) -> None:
    human, prop, customer, lease = _lease(migrated_database_url)
    staff = invoice_api_actor(human, prop)
    laundry = _service(prop, human, "Laundry bag", 450)
    cleaning = _service(prop, human, "Deep cleaning", 2_000)
    laundry_id = UUID(laundry["regular_service_id"])
    cleaning_id = UUID(cleaning["regular_service_id"])
    items = (
        ServiceInvoiceItem(uuid4(), laundry_id, 3),
        ServiceInvoiceItem(uuid4(), cleaning_id, 1),
    )
    command = CreateServicesInvoiceDraftCommand(uuid4(), customer, lease, items)
    draft = invoices().create_services_draft(prop, command, actor=staff)
    assert (draft["status"], draft["category"]) == ("DRAFT", "MISCELLANEOUS_CHARGES")
    assert draft["original_total"] == {"currency": "USD", "minor_units": 3_350}
    lines = cast(list[dict[str, Any]], draft["lines"])
    assert [(line["description"], line["calculation_evidence"]["quantity"]) for line in lines] == [
        ("Laundry bag", 3),
        ("Deep cleaning", 1),
    ]
    # The same request again answers the same Draft, once.
    assert invoices().create_services_draft(prop, command, actor=staff) == draft

    flow = PostgresServiceSettingsFlow(runtime_database_url())
    flow.save_regular_service(
        prop,
        human,
        laundry_id,
        RegularServiceChange(name_en="Laundry bag", price_usd_cents=600, version=1),
    )
    again = invoices().get(UUID(str(draft["id"])), actor=staff)
    assert again["original_total"] == draft["original_total"]
    # Used on an Invoice this year, so it stays until next year.
    with pytest.raises(ServiceSettingsConflict):
        flow.remove_regular_service(prop, human, cleaning_id, 1)
    # Edit items would let a price be typed.
    with pytest.raises(InvoiceInvalidError):
        invoices().replace_draft_items(
            prop,
            UUID(str(draft["id"])),
            ReplaceInvoiceDraftItemsCommand(
                uuid4(),
                customer,
                lease,
                "Regular services from Settings",
                "Settings > Regular services price",
                "Cheaper",
                (InvoiceItem(uuid4(), "Laundry bag", 3, 100),),
                cast(int, draft["version"]),
            ),
            actor=staff,
        )
    with pytest.raises(InvoiceNotFoundError):
        invoices().create_services_draft(
            prop,
            CreateServicesInvoiceDraftCommand(
                uuid4(), customer, lease, (ServiceInvoiceItem(uuid4(), uuid4(), 1),)
            ),
            actor=staff,
        )

    invoices().issue(
        prop,
        UUID(str(draft["id"])),
        IssueInvoiceCommand(uuid4(), cast(int, draft["version"])),
        actor=staff,
    )
    kinds = {row[2] for row in facts("report_income_facts", human, prop)}
    assert "REGULAR_SERVICE_CHARGES" in kinds
    assert INCOME_GROUPS["REGULAR_SERVICE_CHARGES"] == INCOME_GROUPS["RENT"] == "rent"


def test_runtime_role_cannot_write_regular_services_directly(migrated_database_url: str) -> None:
    human, prop, _, _ = _lease(migrated_database_url)
    with (
        psycopg.connect(runtime_database_url()) as connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        connection.execute(
            "INSERT INTO app.regular_services(id,property_id,name_en,price_usd_cents,"
            "created_by,updated_by) VALUES (%s,%s,'Free',1,%s,%s)",
            (uuid4(), prop, human, human),
        )
