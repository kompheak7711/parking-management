"""Alembic environment using only the separately supplied migration connection."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

migration_url = os.environ.get("MIGRATION_DATABASE_URL")
if migration_url is None:
    raise RuntimeError("MIGRATION_DATABASE_URL is required; runtime credentials are not accepted")
if migration_url.startswith("postgresql://"):
    migration_url = migration_url.replace("postgresql://", "postgresql+psycopg://", 1)
config.set_main_option("sqlalchemy.url", migration_url.replace("%", "%%"))


def run_migrations_online() -> None:
    """Run reviewed forward migrations in a transaction."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, transactional_ddl=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()