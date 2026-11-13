"""The riel rate has no mark-up (migration 20270724_393, DL-228).

New rate records keep ABA's Sell rate rounded up to a whole riel (0 basis points). Records saved
before the change keep their 0.5% and still pass the formula check. The unused Settings rule
"Riel rate: ABA Sell rate plus" is gone."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from psycopg import Connection, Error
from psycopg.types.json import Jsonb

from test_configuration_migration import migrated_database_url as migrated_database_url

__all__ = ["migrated_database_url"]

INSERT = """
    INSERT INTO app.exchange_rate_records (
        id, reference_rate_khr_per_usd, markup_basis_points, system_rate_khr_per_usd,
        rate_source, applicable_at, calculation_trace
    ) VALUES (%s, %s, %s, %s, 'ABA_AUTOMATIC', statement_timestamp(), %s)
"""


@pytest.fixture
def owner(migrated_database_url: str) -> Iterator[Connection[tuple[object, ...]]]:
    with psycopg.connect(migrated_database_url) as connection:
        yield connection
        connection.rollback()


def refused(connection: Connection[tuple[object, ...]], *row: object) -> None:
    with connection.transaction():
        with pytest.raises(Error) as failure:
            with connection.transaction():
                connection.execute(INSERT, (uuid4(), *row, Jsonb({"test": "DL-228"})))
        assert failure.value.sqlstate == "23514"


def test_new_rate_records_have_no_markup_and_old_records_keep_theirs(
    owner: Connection[tuple[object, ...]],
) -> None:
    trace = Jsonb({"test": "DL-228"})
    # Today's ABA Sell rate is the app rate, rounded up to a whole riel.
    owner.execute(INSERT, (uuid4(), "4077.000000", 0, 4077, trace))
    owner.execute(INSERT, (uuid4(), "4076.250000", 0, 4077, trace))
    # A record saved before DL-228 keeps its 0.5%: 4,062 x 1.005 = 4,082.31, so 4,083.
    owner.execute(INSERT, (uuid4(), "4062.000000", 50, 4083, trace))
    owner.execute(INSERT, (uuid4(), "99999999999999.999999", 0, 100000000000000, trace))

    refused(owner, "4077.000000", 0, 4098)  # 0.5% added to a new record
    refused(owner, "4077.000000", 0, 4076)  # rounded down
    refused(owner, "4062.000000", 50, 4062)  # an old record without its 0.5%
    refused(owner, "4062.000000", 25, 4073)  # any other mark-up


def test_payment_functions_no_longer_add_markup_and_the_settings_rule_is_gone(
    owner: Connection[tuple[object, ...]],
) -> None:
    for signature in (
        "app.confirm_khr_payment(uuid,uuid,uuid,jsonb,jsonb)",
        "app.execute_exchange_rate(uuid,uuid,text,uuid,numeric,bigint,text,text,"
        "timestamp with time zone,uuid,jsonb)",
    ):
        row = owner.execute(
            "SELECT pg_catalog.pg_get_functiondef(CAST(%s AS regprocedure))", (signature,)
        ).fetchone()
        assert row is not None
        body = str(row[0])
        assert "1.005" not in body and ",50," not in body.replace(" ", ""), signature
    assert owner.execute(
        "SELECT count(*) FROM app.business_rule_names WHERE code = 'RIEL_RATE_MARK_UP'"
    ).fetchone() == (0,)
