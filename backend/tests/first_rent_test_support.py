"""V1.1 part 2 (DL-118): the first Rent gets the late-payment charge by default (owner
01/11/2026). The V1 tests that check how a first Rent with no late charge settles switch the
FIRST_RENT Invoice type to No for the test and back to Yes after it."""

from collections.abc import Iterator

import psycopg
import pytest


@pytest.fixture
def first_rent_late_payment_off(migrated_database_url: str) -> Iterator[None]:
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.invoice_types SET late_payment = false, version = version + 1 "
            "WHERE code = 'FIRST_RENT' AND late_payment"
        )
    try:
        yield
    finally:
        with psycopg.connect(migrated_database_url) as connection:
            connection.execute(
                "UPDATE app.invoice_types SET late_payment = true, version = version + 1 "
                "WHERE code = 'FIRST_RENT' AND NOT late_payment"
            )
