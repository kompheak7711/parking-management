"""One-time application-controlled Property initialization command."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from uuid import UUID, uuid4

import psycopg

from property_rental.property import PropertyAlreadyConfiguredError, configure_postgres_property
from property_rental.settings import Settings


def owner_actor_id(database_url: str) -> UUID | None:
    """The one Owner-class account (V1-060: the local run has no other way to name it)."""
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            "SELECT actor_id FROM app.user_account_classes WHERE account_class = 'owner'"
        ).fetchone()
    return None if row is None else UUID(str(row[0]))


def main(arguments: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    """Initialize the single Property using the configured runtime database identity."""
    parser = argparse.ArgumentParser(description="Initialize this deployment's Property")
    # V1-060: both may be left out; a new identifier is made and the Owner sets the Property up.
    parser.add_argument("--property-id", type=UUID)
    parser.add_argument("--name", required=True)
    parser.add_argument("--address")
    parser.add_argument("--actor-id", type=UUID)
    parsed = parser.parse_args(arguments)
    resolved = settings or Settings()
    if resolved.database_url is None:
        parser.error("APP_DATABASE_URL is required")
    database_url = resolved.database_url.get_secret_value()
    actor_id = parsed.actor_id or owner_actor_id(database_url)
    if actor_id is None:
        parser.error("no Owner account yet: make the first Owner account first")
    try:
        configured = configure_postgres_property(
            database_url,
            parsed.property_id or uuid4(),
            name=parsed.name,
            address_text=parsed.address,
            actor_id=actor_id,
        )
    except PropertyAlreadyConfiguredError:
        print("The Property is already set up; nothing was changed.")
        return 0
    print(f"The Property {configured.name} is set up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
