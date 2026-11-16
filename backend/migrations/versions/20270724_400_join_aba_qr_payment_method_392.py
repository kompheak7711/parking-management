"""Join main's ABA QR payment method migration (392) with the UI v81 migrations.

No database change. Main put 20270723_392 (DL-227: the Settings choice of the payment method
that records ABA QR payments) after 20270717_340; ui-v81 joined 340 with its own 360 to 369 in
20270718_367. This file has 367 and 392 as parents, so there is one head again and a database
on either side gets the other side's migrations from a plain ``alembic upgrade head``. The two
sides share no object: 392 adds the column ``app.payment_methods.aba_qr`` and changes
``app.aba_payment_method`` and ``app.replace_property_payment_methods``, which no migration
from 360 to 369 touches. Forward-only.

Revision ID: 20270724_400
Revises: 20270718_367, 20270723_392
"""

from collections.abc import Sequence

revision: str = "20270724_400"
down_revision: str | Sequence[str] | None = ("20270718_367", "20270723_392")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to change: the two parents share no object."""


def downgrade() -> None:
    raise NotImplementedError("the join of 392 and 367 is forward-only")
