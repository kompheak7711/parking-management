"""Join main's Lease draft fix (20270719_374, DL-223) with the UI v81 migrations (360 to 365).

No database change. Main put 374 after 20270715_387; ui-v81 put its own 360 to 365 after
20270716_391. This file has both as parents, so there is one head again and a database on
either side gets the other side's migrations from a plain ``alembic upgrade head``. The two
sides share no object: 374 replaces only ``app.guard_lease_short_stay_nights``, which no
migration from 390 to 365 touches. Forward-only.

Revision ID: 20270718_366
Revises: 20270714_365, 20270719_374
"""

from collections.abc import Sequence

revision: str = "20270718_366"
down_revision: str | Sequence[str] | None = ("20270714_365", "20270719_374")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to change: the two parents share no object."""


def downgrade() -> None:
    raise NotImplementedError("the join of 374 and 365 is forward-only")
