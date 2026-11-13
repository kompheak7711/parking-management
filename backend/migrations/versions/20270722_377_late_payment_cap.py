"""DL-226 (D2, owner 12 Nov 2026): the late-payment charge in Settings is at most 10%.

The owner decided that Settings refuse a late-payment charge above 10% (Lease Article 2.3).
Before this migration ``app.business_rules_program_range()`` took any value of
``LATE_PAYMENT_PERCENT`` up to 100% (DL-118 (B)). But the record of a late-payment charge
(``app.late_payment_decisions``, constraint ``late_payment_decisions_rate_whole_percent``,
DL-085) holds only a whole percent from 0 to 10. So a value such as 15% or 7.5% was saved in
Settings, but the charge record refuses it, and the automatic charge could then not be saved.

Two functions change:

1. ``app.business_rules_program_range()``: ``LATE_PAYMENT_PERCENT`` takes only what the charge
   record can hold, a whole percent from 0 to 10 (0 to 1000 in hundredths of a percent, in
   steps of 100). The refusal says so.
2. ``app.late_payment_rate_basis_points(property, date)``: a value saved before this migration
   stays in the history (the rows are append-only). It is read as at most 10%, cut down to a
   whole percent, so the charge is never more than the value saved and never more than 10%.

What stays as it was: the starting value of 10%; every other business rule and its range; the
late-payment decisions and charges already recorded.

No table, column, grant or data change. Forward-only.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270722_377"
down_revision: str | None = "20270721_376"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RANGE = "app.business_rules_program_range()"
RANGE_BEFORE = "IF (v_code = 'LATE_PAYMENT_PERCENT' AND NEW.value > 10000)"
RANGE_AFTER = (
    "IF v_code = 'LATE_PAYMENT_PERCENT'\n"
    "                AND (NEW.value NOT BETWEEN 0 AND 1000 OR mod(NEW.value, 100) <> 0) THEN\n"
    "                RAISE EXCEPTION 'The late-payment charge is a whole percent from 0 to 10'\n"
    "                    USING ERRCODE = '22023';\n"
    "            END IF;\n"
    "            IF (v_code = 'LATE_PAYMENT_PERCENT' AND NEW.value > 1000)"
)

RATE = "app.late_payment_rate_basis_points(uuid, date)"
RATE_BEFORE = (
    "SELECT coalesce(app.business_rule_value('LATE_PAYMENT_PERCENT', p_charge_date),\n"
    "                1000)::smallint"
)
RATE_AFTER = (
    "SELECT (least(coalesce(app.business_rule_value('LATE_PAYMENT_PERCENT', p_charge_date),\n"
    "                1000), 1000) / 100 * 100)::smallint"
)


def _patch(signature: str, before: str, after: str) -> None:
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    if definition.count(before) != 1:
        raise RuntimeError(f"Late-payment source contract changed: {signature}")
    op.execute(definition.replace(before, after))


def upgrade() -> None:
    _patch(RANGE, RANGE_BEFORE, RANGE_AFTER)
    _patch(RATE, RATE_BEFORE, RATE_AFTER)


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
