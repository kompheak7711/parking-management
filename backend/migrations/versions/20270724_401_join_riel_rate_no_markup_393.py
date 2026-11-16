"""Join main's riel rate migration (393, no mark-up) with the UI v81 migrations.

No database change. Main put 20270724_393 (DL-228: the riel rate is ABA's Sell rate with no
0.5% mark-up) after 20270723_392; ui-v81 joined 392 with its own 360 to 369 in 20270724_400.
This file has 400 and 393 as parents, so there is one head again and a database on either side
gets the other side's migrations from a plain ``alembic upgrade head``. The two sides share no
object that either changes: 393 changes ``app.exchange_rate_records`` (its mark-up check),
``app.execute_exchange_rate``, ``app.confirm_khr_payment`` and the business rule
``RIEL_RATE_MARK_UP``; from 360 to 369 only 361 reads ``app.exchange_rate_records`` (the Home
page's latest rate), and it changes none of them. Forward-only.

Revision ID: 20270724_401
Revises: 20270724_400, 20270724_393
"""

from collections.abc import Sequence

revision: str = "20270724_401"
down_revision: str | Sequence[str] | None = ("20270724_400", "20270724_393")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to change: the two parents share no object that either changes."""


def downgrade() -> None:
    raise NotImplementedError("the join of 393 and 400 is forward-only")
