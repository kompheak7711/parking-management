"""Join main's missed-amount migration (395, DL-232) with the UI v81 migrations.

No database change. Main put 20270729_395 (DL-232: an amount missed on a fully paid line keeps
the type of what was missed) after 20270728_394; ui-v81 has 394 through its join 20270728_405
and then the Leasing thread's 20270727_414 (short-stay guest notices). This file has 414 and 395
as parents, so there is one head again. The two sides share no object that either changes: 395
adds ``app.invoices.missed_on_invoice_line_id`` and ``app.create_missed_amount_invoice_draft``
and changes ``app.create_items_invoice_draft_of_type``, ``app.keep_invoice_type``,
``app.invoice_resource_snapshot``, ``app.report_income_facts`` and ``app.gl_app_record_events``;
no ui-v81 migration redefines any of them, and 414 changes only the short-stay notice objects.
Forward-only.

Revision ID: 20270729_406
Revises: 20270727_414, 20270729_395
"""

from collections.abc import Sequence

revision: str = "20270729_406"
down_revision: str | Sequence[str] | None = ("20270727_414", "20270729_395")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to change: the two parents share no object that either changes."""


def downgrade() -> None:
    raise NotImplementedError("the join of 414 and 395 is forward-only")
