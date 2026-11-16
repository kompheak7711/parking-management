"""Join main's Late-payment Invoice migration (396, DL-233) with the UI v81 migrations.

No database change. Main put 20270730_396 (DL-233: the late-payment charge is an Invoice of the
type Late-payment) after 20270729_395; ui-v81 has 395 through its join 20270729_406. This file
has 406 and 396 as parents, so there is one head again. The two sides share no object that
either changes: no ui-v81 migration redefines a function 396 adds or changes (the late-payment
charge, Invoice void and adjustment checks, ``app.invoice_resource_snapshot``,
``app.report_income_facts``, ``app.gl_app_record_events`` and the Invoice type rules).
Forward-only.

Revision ID: 20270730_407
Revises: 20270729_406, 20270730_396
"""

from collections.abc import Sequence

revision: str = "20270730_407"
down_revision: str | Sequence[str] | None = ("20270729_406", "20270730_396")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to change: the two parents share no object that either changes."""


def downgrade() -> None:
    raise NotImplementedError("the join of 406 and 396 is forward-only")
