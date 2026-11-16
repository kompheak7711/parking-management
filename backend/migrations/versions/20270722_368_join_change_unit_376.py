"""Join main's Change Unit and Reserve Unit stop (375 and 376) with the UI v81 migrations.

No database change. Main put 20270720_375 (DL-224) and 20270721_376 (DL-225) after
20270719_374; ui-v81 joined 374 with its own 360 to 365 in 20270718_366. This file has 366 and
376 as parents, so there is one head again and a database on either side gets the other side's
migrations from a plain ``alembic upgrade head``. The two sides share no object: 375 and 376
add their own functions and triggers and replace only ``app.short_stay_refund_sources``, which
no migration from 390 to 366 touches. Forward-only.

Revision ID: 20270722_368
Revises: 20270718_366, 20270721_376
"""

from collections.abc import Sequence

revision: str = "20270722_368"
down_revision: str | Sequence[str] | None = ("20270718_366", "20270721_376")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to change: the two parents share no object."""


def downgrade() -> None:
    raise NotImplementedError("the join of 376 and 366 is forward-only")
