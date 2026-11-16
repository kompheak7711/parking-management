"""Join main's ABA QR migration (340) with the UI v81 migrations.

No database change. Main put 20270717_340 (DL-180: the ABA QR of each Invoice message and its
events) after 20270722_377; ui-v81 joined 377 with its own 360 to 368 in 20270722_369. This file
has 369 and 340 as parents, so there is one head again and a database on either side gets the
other side's migrations from a plain ``alembic upgrade head``. The two sides share no object:
340 adds the tables ``app.aba_qr_requests`` and ``app.aba_qr_events`` and new ``app.aba_*``
functions, which no migration from 360 to 369 touches. Forward-only.

The number 367 was kept for this join when 366 and 368 were made, so the file's date and number
are earlier than its parents'; only the two parents below decide the order.

Revision ID: 20270718_367
Revises: 20270722_369, 20270717_340
"""

from collections.abc import Sequence

revision: str = "20270718_367"
down_revision: str | Sequence[str] | None = ("20270722_369", "20270717_340")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to change: the two parents share no object."""


def downgrade() -> None:
    raise NotImplementedError("the join of 340 and 369 is forward-only")
