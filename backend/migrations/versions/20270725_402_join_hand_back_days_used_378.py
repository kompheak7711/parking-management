"""Join main's hand-back migration (378, DL-229) with the UI v81 migrations.

No database change. Main put 20270725_378 (DL-229: a hand-back before the 5th pays only the
days used) after 20270724_393; ui-v81 has 393 through 20270724_401 and then its own 411 and 412
(problem type names and order). This file has 412 and 378 as parents, so there is one head again
and a database on either side gets the other side's migrations from a plain
``alembic upgrade head``. The two sides share no object that either changes: 378 changes
``app.hand_back_rent_resolutions``, ``app.hand_back_rent_invoice_basis`` and adds
``app.resolve_hand_back_rent_invoice``; 411 and 412 change only ``app.problem_types`` rows, and
no ui-v81 migration redefines a function that 378 calls (361 and 362 only read Invoice lines).
Forward-only.

Revision ID: 20270725_402
Revises: 20270725_412, 20270725_378
"""

from collections.abc import Sequence

revision: str = "20270725_402"
down_revision: str | Sequence[str] | None = ("20270725_412", "20270725_378")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to change: the two parents share no object that either changes."""


def downgrade() -> None:
    raise NotImplementedError("the join of 378 and 412 is forward-only")
