"""Daily and weekly rent: a daily guest changes to a Lease with $50 off the first month (315).

The desk links the guest's Lease draft on the booking page; Sign Lease then asks for the money
due less the $50, and the Initial Rent Invoice shows the $50 as a credit adjustment.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from payment_test_support import database_instant, seed_method
from property_rental.billing import month_end
from property_rental.lease_signing_api import PostgresLeaseSigningFlow, SignWithPaymentCommand
from test_invoice_migration import financial_database_url
from test_lease_migration import create_draft
from test_migrations import _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_short_stay_booking_migration import (
    BOOK,
    BookingDatabase,
    booking,
    refused,
    run,
    short_stay_database,
)
from test_short_stay_check_in_migration import (
    BILL,
    CHECK_IN,
    CHECK_OUT,
    DEPOSIT,
    TICKS,
    guest_with_id,
    pay,
    read,
)

REVISION = "20270605_315"
LINK = "SELECT app.link_short_stay_lease(%s, %s, %s::jsonb, %s, NULL)"
PLAN = "SELECT app.set_lease_planned_security_deposit(%s,%s,%s,%s,%s,%s,%s)"


@pytest.fixture(scope="module")
def stay_database(migrated_database_url: str) -> Iterator[BookingDatabase]:
    assert migrated_database_url
    with short_stay_database("prm_short_stay_lease") as database:
        yield database


def checked_in(db: BookingDatabase, guest: uuid.UUID, unit: uuid.UUID) -> tuple[Any, int]:
    made = run(
        db.runtime_url,
        BOOK,
        db.property_id,
        booking(db, unit, 0, 2, customer_id=str(guest)),
        db.staff,
    )
    run(db.runtime_url, DEPOSIT, db.property_id, made, json.dumps({"kind": "CASH"}), db.staff)
    billed = run(db.runtime_url, BILL, db.property_id, made, read(db, made)["version"], db.staff)
    pay(db, guest, billed["invoice"]["invoice_id"], billed["invoice"]["total_usd_cents"])
    inside = run(
        db.runtime_url, CHECK_IN, db.property_id, made, TICKS, read(db, made)["version"], db.staff
    )
    return made, int(inside["version"])


def draft(db: BookingDatabase, guest: uuid.UUID, unit: uuid.UUID) -> uuid.UUID:
    with psycopg.connect(db.owner_url) as connection:
        lease = create_draft(
            connection,
            actor_id=db.manager,
            unit_id=unit,
            primary_tenant_id=guest,
            start_date=db.today,
            end_date=month_end(db.today + timedelta(days=400)),
            signed=False,
        )
    with psycopg.connect(db.runtime_url) as connection:
        connection.execute(
            PLAN,
            (
                db.property_id,
                lease,
                uuid.uuid4(),
                db.manager,
                40_000,
                "Draft terms",
                "leases.draft",
            ),
        )
    return lease


def flow(db: BookingDatabase) -> PostgresLeaseSigningFlow:
    name = urlsplit(db.owner_url).path.lstrip("/")
    return PostgresLeaseSigningFlow(
        db.runtime_url, _url_with_database(financial_database_url(), name)
    )


def initial(db: BookingDatabase, lease: uuid.UUID) -> dict[str, Any]:
    return cast(dict[str, Any], flow(db).preview(db.property_id, lease)["initial"])


def sign(db: BookingDatabase, lease: uuid.UUID, amount: int) -> dict[str, Any]:
    with psycopg.connect(db.owner_url) as connection:
        at = database_instant(connection) - timedelta(seconds=1)
        method = seed_method(connection, db.manager)
        version = connection.execute(
            "SELECT version FROM app.leases WHERE id=%s", (lease,)
        ).fetchone()
        signers = connection.execute(
            "SELECT id FROM app.lease_signers WHERE lease_id=%s AND signed_at IS NULL ORDER BY id",
            (lease,),
        ).fetchall()
    assert version is not None
    command = SignWithPaymentCommand(
        idempotency_key=uuid.uuid4(),
        expected_version=int(version[0]),
        signer_ids=tuple(uuid.UUID(str(row[0])) for row in signers),
        reason="Every Signer signed the paper Lease",
        payment_method_id=method,
        received_amount_minor=amount,
        received_at=at,
        evidence_reference="Cash received, Cash",
        payer_intent_memo="Money received at signing the Lease",
    )
    return cast(
        dict[str, Any],
        flow(db).sign_with_payment(db.property_id, lease, command, db.manager, True),
    )


def test_migration_315_follows_step_4b() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270604_314"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_a_daily_guest_signs_a_lease_with_50_dollars_off(stay_database: BookingDatabase) -> None:
    db = stay_database
    guest = guest_with_id(db)
    made, version = checked_in(db, guest, db.studio)
    lease = draft(db, guest, db.one_bedroom)
    before = read(db, made)
    assert before["lease_off_usd_cents"] == 5000 and before["lease_offer"] is None
    assert [found["lease_id"] for found in before["lease_drafts"]] == [str(lease)]
    full = initial(db, lease)
    assert full["short_stay_off_usd_cents"] == 0

    linked = run(
        db.runtime_url, LINK, db.property_id, made, json.dumps({"lease_id": str(lease)}), db.staff
    )
    assert linked["lease_offer"]["off_usd_cents"] == 5000
    assert (linked["lease_offer"]["lease_status"], linked["lease_drafts"]) == ("DRAFTED", [])
    assert linked["history"][-1]["kind"] == "LEASE_LINKED"
    assert linked["version"] == version
    # Once per stay and once per Lease.
    assert "already" in refused(
        db.runtime_url,
        "55000",
        LINK,
        db.property_id,
        made,
        json.dumps({"lease_id": str(lease)}),
        db.staff,
    )

    off = initial(db, lease)
    assert off["short_stay_off_usd_cents"] == 5000
    assert off["total_usd_cents"] == full["total_usd_cents"] - 5000
    done = sign(db, lease, off["total_usd_cents"] + 40_000)
    assert done["rent_usd_cents"] == off["total_usd_cents"]
    with psycopg.connect(db.owner_url) as connection:
        invoice = connection.execute(
            "SELECT status FROM app.invoices WHERE id=%s", (done["invoice_id"],)
        ).fetchone()
        credit = connection.execute(
            "SELECT adjustment.adjustment_type, adjustment.amount_usd_cents, line.category "
            "FROM app.invoice_adjustments AS adjustment "
            "JOIN app.invoice_lines AS line ON line.id = adjustment.invoice_line_id "
            "WHERE adjustment.invoice_id=%s",
            (done["invoice_id"],),
        ).fetchall()
    assert invoice == ("PAID",)
    assert credit == [("CREDIT", 5000, "RENT")]
    assert read(db, made)["lease_offer"]["lease_status"] == "SIGNED"


def test_only_a_guest_in_or_after_the_stay_links_their_own_draft(
    stay_database: BookingDatabase,
) -> None:
    db = stay_database
    guest = guest_with_id(db)
    other = guest_with_id(db)
    booked = run(
        db.runtime_url,
        BOOK,
        db.property_id,
        booking(db, db.two_bedroom, 30, 2, customer_id=str(guest)),
        db.staff,
    )
    mine = draft(db, guest, db.no_rent)
    theirs = draft(db, other, db.leased)
    link = json.dumps({"lease_id": str(mine)})
    assert "while in or after" in refused(
        db.runtime_url, "55000", LINK, db.property_id, booked, link, db.staff
    )
    made, version = checked_in(db, guest, db.two_bedroom)
    assert "draft of this guest" in refused(
        db.runtime_url,
        "55000",
        LINK,
        db.property_id,
        made,
        json.dumps({"lease_id": str(theirs)}),
        db.staff,
    )
    refused(
        db.runtime_url,
        "22023",
        LINK,
        db.property_id,
        made,
        json.dumps({"lease_id": str(uuid.uuid4())}),
        db.staff,
    )
    refused(db.runtime_url, "22023", LINK, db.property_id, made, '{"lease_id": "x"}', db.staff)
    # After the check-out it still links.
    left = run(db.runtime_url, CHECK_OUT, db.property_id, made, version, db.staff)
    assert left["status"] == "CHECKED_OUT"
    linked = run(db.runtime_url, LINK, db.property_id, made, link, db.staff)
    assert linked["lease_offer"]["lease_id"] == str(mine)
    # A Lease without a link signs as before.
    assert initial(db, theirs)["short_stay_off_usd_cents"] == 0
