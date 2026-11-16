"""Join main's Draft Invoice change and delete migration (399, DL-239) with the UI v81 migrations.

No database change. Main put 20270802_399 (DL-239: a Draft Invoice is changed with no reason,
and a Draft made by a person can be deleted) after 20270801_398; ui-v81 has 398 through its join
20270801_409. This file has 409 and 399 as parents, so there is one head again. The two sides
share no object that either changes: 399 adds ``app.delete_invoice_draft`` and changes the
Invoice draft and history guards, which no ui-v81 migration redefines. Forward-only.

Revision ID: 20270802_416
Revises: 20270801_409, 20270802_399
"""

from collections.abc import Sequence

revision: str = "20270802_416"
down_revision: str | Sequence[str] | None = ("20270801_409", "20270802_399")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to change: the two parents share no object that either changes."""


def downgrade() -> None:
    raise NotImplementedError("the join of 409 and 399 is forward-only")
