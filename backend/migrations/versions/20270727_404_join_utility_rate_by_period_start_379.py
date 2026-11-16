"""Join main's Utilities rate migration (379, DL-230) with the UI v81 migrations.

No database change. Main put 20270727_379 (DL-230: the Utilities rate is chosen by the first day
of the period of use) after 20270726_413; ui-v81 has 413 through its join 20270726_403. This file
has 403 and 379 as parents, so there is one head again. The two sides share no object that either
changes: 379 changes ``app.preview_utility_calculation`` and ``app.validate_invoice_line``, and no
ui-v81 migration redefines either. Forward-only.

Revision ID: 20270727_404
Revises: 20270726_403, 20270727_379
"""

from collections.abc import Sequence

revision: str = "20270727_404"
down_revision: str | Sequence[str] | None = ("20270726_403", "20270727_379")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to change: the two parents share no object that either changes."""


def downgrade() -> None:
    raise NotImplementedError("the join of 403 and 379 is forward-only")
