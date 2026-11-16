"""Join main's late-payment cap (377) with the UI v81 migrations.

No database change. Main put 20270722_377 (DL-226: the late-payment charge in Settings is a
whole percent from 0 to 10) after 20270721_376; ui-v81 joined 376 with its own 360 to 366 in
20270722_368. This file has 368 and 377 as parents, so there is one head again and a database
on either side gets the other side's migrations from a plain ``alembic upgrade head``. The two
sides share no object: 377 changes only ``app.business_rules_program_range()`` and
``app.late_payment_rate_basis_points(uuid, date)``, which no migration from 360 to 368
touches. Forward-only.

Revision ID: 20270722_369
Revises: 20270722_368, 20270722_377
"""

from collections.abc import Sequence

revision: str = "20270722_369"
down_revision: str | Sequence[str] | None = ("20270722_368", "20270722_377")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to change: the two parents share no object."""


def downgrade() -> None:
    raise NotImplementedError("the join of 377 and 368 is forward-only")
