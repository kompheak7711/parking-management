"""One-time application-controlled Property initialization command."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from uuid import UUID

from property_rental.property import configure_postgres_property
from property_rental.settings import Settings


def main(arguments: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    """Initialize the single Property using the configured runtime database identity."""
    parser = argparse.ArgumentParser(description="Initialize this deployment's Property")
    parser.add_argument("--property-id", required=True, type=UUID)
    parser.add_argument("--name", required=True)
    parser.add_argument("--address")
    parser.add_argument("--actor-id", required=True, type=UUID)
    parsed = parser.parse_args(arguments)
    resolved = settings or Settings()
    if resolved.database_url is None:
        parser.error("APP_DATABASE_URL is required")
    configure_postgres_property(
        resolved.database_url.get_secret_value(),
        parsed.property_id,
        name=parsed.name,
        address_text=parsed.address,
        actor_id=parsed.actor_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
