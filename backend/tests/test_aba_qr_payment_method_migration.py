"""The Payment Method for ABA QR payments is chosen in Settings (migration 20270723_392, DL-227).

The Settings save marks one method that is on; the office jobs then record ABA QR payments with
it, before any code in the operations file."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from property_rental import aba_qr
from test_hr_employees_migration import HrDatabase, make_hr_database, refused
from test_move_in_migration import migrated_database_url as migrated_database_url

__all__ = ["migrated_database_url"]

BANK: dict[str, Any] = {"code": "DL227_BANK", "display_name": "Bank transfer", "accepted": True}
QR: dict[str, Any] = {
    "code": "DL227_QR",
    "display_name": "CHETANA Residence ABA QR code",
    "accepted": True,
}


@pytest.fixture(scope="module")
def method_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_aba_method")


def methods_now(db: HrDatabase) -> list[dict[str, Any]]:
    with psycopg.connect(db.owner_url) as owner:
        rows = owner.execute(
            "SELECT id, code, accepted, aba_qr FROM app.payment_methods ORDER BY code"
        ).fetchall()
    return [{"id": row[0], "code": row[1], "accepted": row[2], "aba_qr": row[3]} for row in rows]


def save(db: HrDatabase, *methods: dict[str, Any]) -> None:
    """The Settings save, with every method already saved that the call does not name."""
    known = {method["code"]: method["id"] for method in methods_now(db)}
    named = {method["code"] for method in methods}
    payload = [
        {"id": str(known.get(method["code"], uuid.uuid4())), **method} for method in methods
    ] + [
        {"id": str(row["id"]), "code": row["code"], "display_name": row["code"], "accepted": True}
        for row in methods_now(db)
        if row["code"] not in named and row["accepted"]
    ]
    with psycopg.connect(db.runtime_url) as runtime:
        version = runtime.execute(
            "SELECT version FROM app.property_configuration WHERE property_id = %s",
            (db.property_id,),
        ).fetchone()
        assert version is not None
        row = runtime.execute(
            "SELECT version FROM app.replace_property_payment_methods(%s, %s, %s, %s)",
            (db.property_id, Jsonb(payload), version[0], db.owner),
        ).fetchone()
    assert row is not None and row[0] == version[0] + 1


def marked(db: HrDatabase) -> list[str]:
    return [row["code"] for row in methods_now(db) if row["aba_qr"]]


def store(db: HrDatabase) -> aba_qr.PostgresAbaStore:
    return aba_qr.PostgresAbaStore(db.runtime_url, property_id=db.property_id, actor_id=db.manager)


def method_id(db: HrDatabase, code: str) -> uuid.UUID:
    return uuid.UUID(str(next(row["id"] for row in methods_now(db) if row["code"] == code)))


def test_settings_mark_one_method_for_aba_qr_and_the_jobs_use_it_first(
    method_database: HrDatabase,
) -> None:
    db = method_database
    office = store(db)
    save(db, BANK, QR)
    assert marked(db) == [], "no method is marked by the migration"
    # Before a method is marked the code from the operations file is still used.
    assert office.payment_method_id(BANK["code"]) == method_id(db, BANK["code"])
    assert office.payment_method_id(None) is None

    save(db, {**BANK, "aba_qr": False}, {**QR, "aba_qr": True})
    assert marked(db) == [QR["code"]]
    assert office.payment_method_id(None) == method_id(db, QR["code"])
    assert office.payment_method_id(BANK["code"]) == method_id(db, QR["code"]), "the mark wins"

    # A screen that does not send the mark keeps it.
    save(db, BANK, QR)
    assert marked(db) == [QR["code"]]
    # Moving the mark to another method takes it away from the first.
    save(db, {**BANK, "aba_qr": True}, QR)
    assert marked(db) == [BANK["code"]]
    save(db, BANK, {**QR, "aba_qr": True})
    assert marked(db) == [QR["code"]]

    # Turning the marked method off takes the mark away; the file's code is used again.
    save(db, BANK, {**QR, "accepted": False})
    assert marked(db) == []
    assert office.payment_method_id(None) is None
    assert office.payment_method_id(QR["code"]) is None, "a method that is off is never used"
    assert office.payment_method_id(BANK["code"]) == method_id(db, BANK["code"])

    # Clearing every mark on purpose.
    save(db, BANK, {**QR, "aba_qr": True})
    save(db, {**BANK, "aba_qr": False}, {**QR, "aba_qr": False})
    assert marked(db) == []


def test_a_wrong_mark_is_refused_and_the_table_keeps_at_most_one(
    method_database: HrDatabase,
) -> None:
    db = method_database
    save(db, BANK, {**QR, "aba_qr": True})
    with psycopg.connect(db.runtime_url) as runtime:
        version = runtime.execute(
            "SELECT version FROM app.property_configuration WHERE property_id = %s",
            (db.property_id,),
        ).fetchone()
    assert version is not None
    call = "SELECT version FROM app.replace_property_payment_methods(%s, %s, %s, %s)"
    ids = {row["code"]: str(row["id"]) for row in methods_now(db)}
    for wrong in (
        [{**BANK, "aba_qr": True}, {**QR, "aba_qr": True}],
        [BANK, {**QR, "accepted": False, "aba_qr": True}],
        [BANK, {**QR, "aba_qr": "yes"}],
    ):
        payload = [{"id": ids[method["code"]], **method} for method in wrong]
        refused(db.runtime_url, "22023", call, db.property_id, Jsonb(payload), version[0], db.owner)
    assert marked(db) == [QR["code"]], "nothing changed"

    with psycopg.connect(db.owner_url) as owner:
        with pytest.raises(psycopg.errors.UniqueViolation):
            owner.execute(
                "UPDATE app.payment_methods SET aba_qr = true WHERE code = %s", (BANK["code"],)
            )
    with psycopg.connect(db.owner_url) as owner:
        with pytest.raises(psycopg.errors.CheckViolation):
            owner.execute(
                "UPDATE app.payment_methods SET accepted = false WHERE code = %s", (QR["code"],)
            )
    with psycopg.connect(db.runtime_url) as runtime:
        assert runtime.execute(
            "SELECT has_table_privilege('prm_runtime', 'app.payment_methods', 'UPDATE')"
        ).fetchone() == (False,)
