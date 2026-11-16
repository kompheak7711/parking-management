"""Join main's stored Invoice type migration (394, DL-231) with the UI v81 migrations.

No database change. Main put 20270728_394 (DL-231: the seven Invoice types are kept on the
Invoice) after 20270727_379; ui-v81 has 379 through its join 20270727_404. This file has 404 and
394 as parents, so there is one head again. The two sides share no object that either changes:
394 adds ``app.invoices.invoice_type`` and changes ``app.invoice_type_of``,
``app.create_items_invoice_draft``, ``app.short_stay_invoice``, ``app.sign_quotation``,
``app.decide_short_stay_charge`` and ``app.decide_short_stay_damage``. No ui-v81 migration
redefines any of them or adds Invoices; 364 only calls ``app.invoice_type_of``, whose signature
394 keeps. Forward-only.

Revision ID: 20270728_405
Revises: 20270727_404, 20270728_394
"""

from collections.abc import Sequence

revision: str = "20270728_405"
down_revision: str | Sequence[str] | None = ("20270727_404", "20270728_394")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to change: the two parents share no object that either changes."""


def downgrade() -> None:
    raise NotImplementedError("the join of 404 and 394 is forward-only")
