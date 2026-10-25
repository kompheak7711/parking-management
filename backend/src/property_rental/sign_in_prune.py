"""Owner-run removal of wrong sign-in tries older than 30 days (V1-056 slice 12c; DL-092).

Owner answer (a) to Q-2026-10-23-175: the Owner removes wrong-try rows, their ended waits and
the clears older than 30 days with `app.prune_sign_in_wrong_tries`, which only the migration
owner may run, in batches of usernames until none is left. The database address is read from
`MIGRATION_DATABASE_URL` (as `make migrate` does) and is never printed; the command prints only
the three counts.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence
from typing import Final

import psycopg

PRUNE_SQL = (
    "SELECT wrong_tries,waits,clears,last_username_digest FROM app.prune_sign_in_wrong_tries(%s,%s)"
)
# Usernames per transaction: each takes one advisory lock until the batch commits.
BATCH: Final = 500
MAX_BATCHES: Final = 10_000


def prune(database_url: str, batch: int = BATCH) -> dict[str, int]:
    """Remove the rows older than 30 days, one committed batch of usernames at a time, and
    return the total counts."""
    totals = {"wrong_tries": 0, "waits": 0, "clears": 0}
    after: bytes | None = None
    with psycopg.connect(database_url) as connection:
        connection.isolation_level = psycopg.IsolationLevel.READ_COMMITTED
        for _ in range(MAX_BATCHES):
            with connection.transaction():
                row = connection.execute(PRUNE_SQL, (after, batch)).fetchone()
            if row is None:
                raise RuntimeError("the prune function returned no row")
            totals["wrong_tries"] += int(row[0])
            totals["waits"] += int(row[1])
            totals["clears"] += int(row[2])
            if row[3] is None:
                return totals
            after = bytes(row[3])
    raise RuntimeError("the prune did not finish within its batch bound")


def main(argv: Sequence[str] | None = None) -> int:
    if list(argv if argv is not None else sys.argv[1:]):
        print(json.dumps({"event": "sign_in_prune.usage", "detail": "takes no arguments"}))
        return 2
    database_url = os.environ.get("MIGRATION_DATABASE_URL", "")
    if not database_url:
        print(json.dumps({"event": "sign_in_prune.config_invalid", "detail": "no database"}))
        return 2
    try:
        counts = prune(database_url)
    except psycopg.Error as error:
        # The SQLSTATE only: a driver message may name the server.
        print(json.dumps({"event": "sign_in_prune.failed", "sqlstate": error.sqlstate}))
        return 1
    except RuntimeError:
        print(json.dumps({"event": "sign_in_prune.failed", "sqlstate": None}))
        return 1
    print(json.dumps({"event": "sign_in_prune.completed", **counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
