"""Short stays: the room check reports problems; damage is charged with no approval (DL-222).

Migration 20270716_391. The owner (12 Nov 2026, "All recommended"): a short-stay check-out works
like a long-stay move-out. The housekeeper reports each problem as a Unit Problem report, with no
cost. The person who bills damage (`damage_charges.bill`) decides on the booking "Charge the
guest" (from the deposit first, the rest an Invoice) or "No charge". The deposit waits until then.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_move_in_migration import migrated_database_url as migrated_database_url
from test_role_bundle_migration import ADD_BUNDLE, ADD_CAPABILITY, ASSIGN, add_account
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
    CHARGE,
    CHECK_IN,
    CHECK_OUT,
    DECIDE,
    DEPOSIT,
    END_DEPOSIT,
    ROOM,
    TICKS,
    guest_with_id,
    pay,
    problem_type,
    read,
    unit_status,
)

REVISION = "20270716_391"
ADD_REPORT = "SELECT app.add_problem_report(%s, %s::jsonb, %s, NULL)"
REPORT = "SELECT app.problem_report_json(%s, false)"
DUE = "SELECT app.short_stay_damage_due(%s, %s)"


def due_of(db: BookingDatabase, booking_id: uuid.UUID) -> list[dict[str, object]]:
    return [
        entry
        for entry in run(db.runtime_url, DUE, db.property_id, db.manager)
        if entry["booking_id"] == str(booking_id)
    ]


@pytest.fixture(scope="module")
def stay_database(migrated_database_url: str) -> Iterator[BookingDatabase]:
    assert migrated_database_url
    with short_stay_database("prm_short_stay_room_problems") as database:
        yield database


def another_studio(db: BookingDatabase, number: str) -> uuid.UUID:
    """One more Studio with a monthly Rent, free today."""
    unit = uuid.uuid4()
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.units (id, property_id, unit_number, floor, unit_type, status, "
            "default_monthly_rent_usd_cents, created_by, updated_by) "
            "VALUES (%s, %s, %s, '6', 'STUDIO', 'VACANT', 29900, %s, %s)",
            (unit, db.property_id, number, db.manager, db.manager),
        )
    return unit


def checked_out(db: BookingDatabase, unit: uuid.UUID, start: int) -> tuple[uuid.UUID, uuid.UUID]:
    """A guest who paid, left a $50 cash deposit, stayed and checked out; room check to do."""
    guest = guest_with_id(db)
    made = run(
        db.runtime_url,
        BOOK,
        db.property_id,
        booking(db, unit, start, 1, customer_id=str(guest)),
        db.staff,
    )
    run(db.runtime_url, DEPOSIT, db.property_id, made, json.dumps({"kind": "CASH"}), db.staff)
    billed = run(db.runtime_url, BILL, db.property_id, made, read(db, made)["version"], db.staff)
    pay(db, guest, billed["invoice"]["invoice_id"], billed["invoice"]["due_usd_cents"])
    inside = run(
        db.runtime_url, CHECK_IN, db.property_id, made, TICKS, read(db, made)["version"], db.staff
    )
    run(db.runtime_url, CHECK_OUT, db.property_id, made, inside["version"], db.staff)
    return made, guest


def test_migration_391_follows_the_invoice_types() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270716_390"
    assert scripts.get_heads() == ["20270729_395"]
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_the_room_check_reports_problems_and_the_charge_needs_no_approval(
    stay_database: BookingDatabase,
) -> None:
    db = stay_database
    made, guest = checked_out(db, db.studio, 0)
    # A cost is refused: staff report problems, the charge is set on the booking.
    assert "damage charge is set on the booking" in refused(
        db.runtime_url,
        "22023",
        ROOM,
        db.property_id,
        made,
        json.dumps({"damage": "Broken lamp", "damage_usd_cents": 8000}),
        db.staff,
    )
    # A problem has only its type, what is wrong and Urgent.
    refused(
        db.runtime_url,
        "22023",
        ROOM,
        db.property_id,
        made,
        json.dumps({"problems": [{"problem_type_id": problem_type(db), "cost": 1}]}),
        db.staff,
    )
    lamp = {"problem_type_id": problem_type(db), "description": "Broken lamp"}
    leak = {
        "problem_type_id": problem_type(db, "WATER"),
        "description": "Shower leaks",
        "urgent": True,
    }
    checked = run(
        db.runtime_url,
        ROOM,
        db.property_id,
        made,
        json.dumps({"problems": [lamp, leak], "note": "Two things to fix"}),
        db.staff,
    )
    assert checked["room_check"]["status"] == "DONE"
    assert unit_status(db, db.studio) == "VACANT"
    problems = checked["problems"]
    assert [(p["description"], p["urgent"]) for p in problems] == [
        ("Broken lamp", False),
        ("Shower leaks", True),
    ]
    assert all(p["report_number"].startswith("UP") for p in problems)
    assert checked["damage_due"] is True and checked["damage_decision"] is None
    assert checked["history"][-1]["details"]["problems"][0]["description"] == "Broken lamp"
    # Each problem is a Unit Problem report of the stay's Unit, from the room check, with its stay.
    report = run(db.owner_url, REPORT, problems[0]["report_id"])
    assert (report["kind"], report["source"], report["unit_id"]) == (
        "UNIT",
        "ROOM_CHECK",
        str(db.studio),
    )
    assert report["stay"]["booking_id"] == str(made)
    assert report["stay"]["guest_name"] == "Meas Rina"
    # The room check is done once; a stay's problem is not reported after it.
    refused(db.runtime_url, "55000", ROOM, db.property_id, made, "{}", db.staff)
    room_report = {
        "kind": "UNIT",
        "unit_id": str(db.studio),
        "source": "ROOM_CHECK",
        "booking_id": str(made),
        "problem_type_id": problem_type(db),
        "description": "Later",
        "urgent": False,
    }
    assert "reported at its room check" in refused(
        db.runtime_url,
        "55000",
        ADD_REPORT,
        db.property_id,
        json.dumps(room_report),
        db.staff,
    )
    without = {key: value for key, value in room_report.items() if key != "booking_id"}
    refused(db.runtime_url, "22023", ADD_REPORT, db.property_id, json.dumps(without), db.staff)
    # The deposit waits for the decision.
    assert "not decided" in refused(
        db.runtime_url, "55000", END_DEPOSIT, db.property_id, made, db.staff
    )
    # The stay waits on the list of the person who bills damage; Staff do not see that list.
    assert due_of(db, made) == [
        {
            "booking_id": str(made),
            "booking_number": checked["booking_number"],
            "guest_name": "Meas Rina",
            "unit_number": checked["unit_number"],
            "problem_count": 2,
        }
    ]
    refused(db.runtime_url, "42501", DUE, db.property_id, db.staff)
    # Staff do not bill damage; a charge says what for and how much.
    charge = {"charge": True, "description": "Lamp and shower", "amount_usd_cents": 12000}
    refused(db.runtime_url, "42501", CHARGE, db.property_id, made, json.dumps(charge), db.staff)
    for wrong in (
        {"charge": True, "description": "Lamp"},
        {"charge": True, "amount_usd_cents": 12000},
        {"charge": True, "description": "Lamp", "amount_usd_cents": 0},
        {"charge": False, "amount_usd_cents": 100},
        {"charge": "yes"},
    ):
        refused(
            db.runtime_url, "22023", CHARGE, db.property_id, made, json.dumps(wrong), db.manager
        )
    charged = run(db.runtime_url, CHARGE, db.property_id, made, json.dumps(charge), db.manager)
    damage = charged["damages"][0]
    assert (damage["status"], damage["amount_usd_cents"], damage["from_deposit_usd_cents"]) == (
        "APPROVED",
        12000,
        5000,
    )
    assert charged["damage_due"] is False and due_of(db, made) == []
    assert charged["damage_decision"]["outcome"] == "CHARGE"
    assert charged["damage_decision"]["damage_id"] == damage["damage_id"]
    invoice = run(
        db.owner_url,
        "SELECT jsonb_build_object('total', original_total_usd_cents, 'customer', customer_id, "
        "'status', status) FROM app.invoices WHERE id = %s",
        damage["invoice_id"],
    )
    assert invoice == {"total": 7000, "customer": str(guest), "status": "UNPAID"}
    # One decision per stay.
    assert "already decided" in refused(
        db.runtime_url,
        "55000",
        CHARGE,
        db.property_id,
        made,
        json.dumps({"charge": False}),
        db.manager,
    )
    ended = run(db.runtime_url, END_DEPOSIT, db.property_id, made, db.staff)
    assert (ended["deposit"]["status"], ended["deposit"]["kept_usd_cents"]) == ("KEPT", 5000)
    assert [event["kind"] for event in ended["history"]][-3:] == [
        "ROOM_CHECKED",
        "DAMAGE_CHARGED",
        "DEPOSIT_KEPT",
    ]


def test_no_charge_gives_the_whole_deposit_back(stay_database: BookingDatabase) -> None:
    db = stay_database
    made, _guest = checked_out(db, db.one_bedroom, 0)
    # A booking with no problem has nothing to decide.
    clean, _ = checked_out(db, db.two_bedroom, 0)
    run(db.runtime_url, ROOM, db.property_id, clean, "{}", db.staff)
    assert read(db, clean)["damage_due"] is False
    assert "after the room check reports a problem" in refused(
        db.runtime_url,
        "55000",
        CHARGE,
        db.property_id,
        clean,
        json.dumps({"charge": False}),
        db.manager,
    )
    stain = {"problem_type_id": problem_type(db, "CLEANING"), "description": "Sofa stain"}
    run(db.runtime_url, ROOM, db.property_id, made, json.dumps({"problems": [stain]}), db.staff)
    decided = run(
        db.runtime_url,
        CHARGE,
        db.property_id,
        made,
        json.dumps({"charge": False, "note": "Normal wear"}),
        db.manager,
    )
    assert decided["damages"] == []
    assert (decided["damage_decision"]["outcome"], decided["damage_decision"]["note"]) == (
        "NO_CHARGE",
        "Normal wear",
    )
    ended = run(db.runtime_url, END_DEPOSIT, db.property_id, made, db.staff)
    assert (ended["deposit"]["status"], ended["deposit"]["kept_usd_cents"]) == ("RETURNED", 0)
    assert "NO_DAMAGE_CHARGE" in [event["kind"] for event in ended["history"]]


def test_a_housekeeper_without_the_report_right_reports_no_problem(
    stay_database: BookingDatabase,
) -> None:
    db = stay_database
    made, _guest = checked_out(db, another_studio(db, "U601"), 0)
    with psycopg.connect(db.owner_url) as connection:
        cleaner = add_account(connection, "staff")
        bundle = uuid.uuid4()
        connection.execute(ADD_BUNDLE, (bundle, db.property_id, "Room checks only", 1))
        connection.execute(ADD_CAPABILITY, (bundle, 1, "short_stays.housekeeping", "bundle"))
        connection.execute(ASSIGN, (uuid.uuid4(), cleaner, bundle, db.property_id))
    lamp = {"problem_type_id": problem_type(db), "description": "Broken lamp"}
    assert "add a Problem report" in refused(
        db.runtime_url,
        "42501",
        ROOM,
        db.property_id,
        made,
        json.dumps({"problems": [lamp]}),
        cleaner,
    )
    done = run(db.runtime_url, ROOM, db.property_id, made, "{}", cleaner)
    assert done["room_check"]["status"] == "DONE" and done["problems"] == []


def test_a_charge_that_waited_from_before_is_decided_by_the_billing_right(
    stay_database: BookingDatabase,
) -> None:
    db = stay_database
    decide = str(
        run(
            db.owner_url,
            "SELECT pg_catalog.pg_get_functiondef("
            "'app.decide_short_stay_damage(uuid, uuid, jsonb, uuid, uuid)'::regprocedure)",
        )
    )
    assert "'damage_charges.bill'" in decide and "short_stays.approve" not in decide
    made, _guest = checked_out(db, another_studio(db, "U602"), 0)
    run(db.runtime_url, ROOM, db.property_id, made, "{}", db.staff)
    # A damage row made by the room check before DL-222 still waits.
    with psycopg.connect(db.owner_url) as connection:
        row = connection.execute(
            "INSERT INTO app.short_stay_damages (booking_id, description, amount_usd_cents, "
            "asked_by) VALUES (%s, 'Old chair', 2000, %s) RETURNING id",
            (made, db.staff),
        ).fetchone()
    assert row is not None
    assert read(db, made)["damage_due"] is False
    refused(db.runtime_url, "55000", END_DEPOSIT, db.property_id, made, db.staff)
    approve = json.dumps({"approve": True})
    refused(db.runtime_url, "42501", DECIDE, db.property_id, row[0], approve, db.staff)
    decided = run(db.runtime_url, DECIDE, db.property_id, row[0], approve, db.manager)
    assert decided["damages"][0]["from_deposit_usd_cents"] == 2000
    ended = run(db.runtime_url, END_DEPOSIT, db.property_id, made, db.staff)
    assert ended["deposit"]["end_note"] == "Kept for the damage charge"


def test_the_links_and_decisions_are_never_changed(stay_database: BookingDatabase) -> None:
    db = stay_database
    for table in ("short_stay_problem_reports", "short_stay_damage_decisions"):
        assert run(db.runtime_url, f"SELECT count(*) FROM app.{table}") >= 1
        refused(db.owner_url, "55000", f"DELETE FROM app.{table}")
        refused(db.owner_url, "55000", f"TRUNCATE app.{table}")
        with psycopg.connect(db.runtime_url) as connection, pytest.raises(psycopg.Error) as caught:
            connection.execute(f"DELETE FROM app.{table}")
        assert caught.value.sqlstate == "42501"
    refused(
        db.owner_url,
        "55000",
        "UPDATE app.short_stay_damage_decisions SET note = 'Changed'",
    )
