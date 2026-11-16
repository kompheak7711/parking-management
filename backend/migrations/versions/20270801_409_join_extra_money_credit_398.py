"""Join main's extra-money-to-Credit migration (398, DL-235) with the UI v81 migrations.

No database change. Main put 20270801_398 (DL-235: extra money at Receive payment becomes
Customer Credit at once) after 20270731_397; ui-v81 has 397 through its join 20270731_408. This
file has 408 and 398 as parents, so there is one head again. The two sides share no object that
either changes: 398 changes ``app.receive_payment``, which no ui-v81 migration redefines.
Forward-only.

Revision ID: 20270801_409
Revises: 20270731_408, 20270801_398
"""

from collections.abc import Sequence

revision: str = "20270801_409"
down_revision: str | Sequence[str] | None = ("20270731_408", "20270801_398")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to change: the two parents share no object that either changes."""


def downgrade() -> None:
    raise NotImplementedError("the join of 408 and 398 is forward-only")
