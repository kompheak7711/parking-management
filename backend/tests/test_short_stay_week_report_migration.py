"""Daily and weekly rent: the weekly report and tenant complaints (migration 318).

The report shows, for 7 days, each Unit's paid nights, its money, the booking-site share and the
cleaning cost, the occupancy against the 40% before the test, the guests who linked a Lease,
damage and the monthly tenants' complaints. Only the Owner and the Manager read it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_move_in_migration import migrated_database_url as migrated_database_url
from test_short_stay_booking_migration import (
    BOOK,
    BookingDatabase,
    booking,
    refused,
    run,
    short_stay_database,
)
from test_short_stay_check_in_migration import ON_SITE, read
from test_short_stay_guests_quotes_migration import QUOTE, stayed

REVISION = "20270608_318"
REPORT = "SELECT app.short_stay_week_report(%s, %s, %s)"
COMPLAINT = "SELECT app.record_short_stay_complaint(%s, %s::jsonb, %s, NULL)"


@pytest.fixture(scope="module")
def stay_database(migrated_database_url: str) -> Iterator[BookingDatabase]:
    assert migrated_database_url
    with short_stay_database("prm_short_stay_week_report") as database:
        yield database


def row(report: dict[str, Any], number: str) -> dict[str, Any]:
    return next(unit for unit in report["units"] if unit["unit_number"] == number)


def test_migration_318_follows_step_5b() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270607_317"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_the_week_counts_paid_nights_money_and_costs(stay_database: BookingDatabase) -> None:
    db = stay_database
    # A walk-in stayed 2 nights and checked out; an Agoda guest paid on the site.
    _, walk_in = stayed(db, db.studio)
    walk_total = read(db, walk_in)["total_usd_cents"]
    agoda = run(
        db.runtime_url,
        BOOK,
        db.property_id,
        booking(
            db,
            db.one_bedroom,
            3,
            2,
            source="BOOKING_SITE",
            site_name="Agoda",
            site_reference="AG-9",
        ),
        db.staff,
    )
    run(db.runtime_url, ON_SITE, db.property_id, agoda, read(db, agoda)["version"], db.staff)
    agoda_total = read(db, agoda)["total_usd_cents"]
    # Not paid yet: not counted.
    run(db.runtime_url, BOOK, db.property_id, booking(db, db.two_bedroom, 1, 2), db.staff)
    # A monthly tenant complains (the front desk records it).
    refused(db.runtime_url, "22023", COMPLAINT, db.property_id, json.dumps({"what": " "}), db.staff)
    complaint = run(
        db.runtime_url,
        COMPLAINT,
        db.property_id,
        json.dumps({"what": "Noise after midnight", "unit_id": str(db.studio)}),
        db.staff,
    )
    assert complaint["noted_on"] == str(db.today)

    # Only the Owner and the Manager read the report, for a week that has started.
    refused(db.runtime_url, "42501", REPORT, db.property_id, db.today, db.staff)
    refused(
        db.runtime_url, "22023", REPORT, db.property_id, db.today + timedelta(days=1), db.manager
    )
    report = run(db.runtime_url, REPORT, db.property_id, db.today, db.manager)
    assert (report["from"], report["to"]) == (str(db.today), str(db.today + timedelta(days=6)))
    assert report["base_occupancy_points"] == 4000
    studio = row(report, "U501")
    # The change-over after the walk-in: $5 cleaning + $2 linen.
    assert (studio["nights"], studio["income_usd_cents"], studio["site_fees_usd_cents"]) == (
        2,
        walk_total,
        0,
    )
    assert studio["cleaning_usd_cents"] == 700
    assert studio["net_usd_cents"] == walk_total - 700
    one = row(report, "U503")
    assert (one["nights"], one["income_usd_cents"]) == (2, agoda_total)
    # Site fees start at 0% until the owner sets them (owner 05/11).
    assert one["site_fees_usd_cents"] == 0
    assert row(report, "U505")["nights"] == 0
    totals = report["totals"]
    assert totals["nights"] == 4
    assert totals["unit_nights"] == totals["units"] * 7
    assert totals["occupancy_points"] == 4 * 10000 // (totals["units"] * 7)
    assert totals["net_usd_cents"] == sum(unit["net_usd_cents"] for unit in report["units"])
    sources = {(entry["source"], entry["site_name"]): entry["stays"] for entry in report["sources"]}
    assert sources == {("WALK_IN", None): 1, ("BOOKING_SITE", "Agoda"): 1}
    assert [entry["what"] for entry in report["complaints"]] == ["Noise after midnight"]
    assert report["complaints"][0]["unit_number"] == "U501"
    assert report["cancellations"] == {"count": 0, "kept_usd_cents": 0}
    assert report["leases"] == [] and report["damages"] == []
    # A week before: nothing yet.
    before = run(db.runtime_url, REPORT, db.property_id, db.today - timedelta(days=7), db.manager)
    assert before["totals"]["nights"] == 0 and before["complaints"] == []


def test_a_quote_shows_the_month_prices(stay_database: BookingDatabase) -> None:
    db = stay_database
    check_in = db.today + timedelta(days=60)
    quote = run(
        db.runtime_url,
        QUOTE,
        db.property_id,
        json.dumps(
            {
                "unit_id": str(db.studio),
                "guest_name": "Sok Chenda",
                "guest_count": 1,
                "check_in_on": str(check_in),
                "check_out_on": str(check_in + timedelta(days=2)),
            }
        ),
        db.staff,
    )
    assert (quote["month_only_usd_cents"], quote["monthly_rent_usd_cents"]) == (44900, 29900)
