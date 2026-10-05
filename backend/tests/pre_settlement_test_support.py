"""A temporary database at the schema before V1-056 sub-slice 8a-1 (migration 20261021_86).

Earlier contract tests simulated a future ``app.deposit_applications`` table to prove that the
readers fail closed when one appears. Migration 86 creates the real table, so those tests run on
a database migrated only to revision 20261020_85; their assertions are unchanged.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from test_deposit_migration import financial_database_url, runtime_database_url
from test_migrations import _temporary_migration_database

PRE_SETTLEMENT_REVISION = "20261020_85"


@pytest.fixture
def pre_settlement_database(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[str]:
    """Yield the owner URL of a fresh database at revision 20261020_85; services follow it."""
    assert migrated_database_url
    with _temporary_migration_database("pre_settlement") as temporary:
        command.upgrade(
            Config(str(Path(__file__).parents[1] / "alembic.ini")), PRE_SETTLEMENT_REVISION
        )
        database = conninfo_to_dict(temporary)["dbname"]
        monkeypatch.setenv(
            "FINANCIAL_DATABASE_URL", make_conninfo(financial_database_url(), dbname=database)
        )
        monkeypatch.setenv(
            "APP_DATABASE_URL", make_conninfo(runtime_database_url(), dbname=database)
        )
        yield temporary
