"""Join main's Pet Deposit at signing migration (397, DL-234) with the UI v81 migrations.

No database change. Main put 20270731_397 (DL-234: the Pet Deposit for a pet kept from the start
is received at signing) after 20270730_396; ui-v81 has 396 through its join 20270730_407. This
file has 407 and 397 as parents, so there is one head again. The two sides share no object that
either changes: no ui-v81 migration redefines a function 397 adds or changes (the planned Pet
Deposit, ``app.lease_signing_preview``, ``app.sign_lease_with_payment`` and the Lease
append-only guards). Forward-only.

Revision ID: 20270731_408
Revises: 20270730_407, 20270731_397
"""

from collections.abc import Sequence

revision: str = "20270731_408"
down_revision: str | Sequence[str] | None = ("20270730_407", "20270731_397")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to change: the two parents share no object that either changes."""


def downgrade() -> None:
    raise NotImplementedError("the join of 407 and 397 is forward-only")
