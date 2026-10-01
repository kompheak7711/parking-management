# ruff: noqa: E501
"""Reject a debit Adjustment once its Invoice line has no remaining balance (BR-INV-044)."""

from alembic import op
from sqlalchemy import text

revision = "20261003_66"
down_revision = "20261002_65"
branch_labels = None
depends_on = None

ADJUST = "app.adjust_invoice(uuid,uuid,uuid,uuid,uuid,text,integer,text,bigint,text,text,uuid,uuid)"
EFFECT = "app.validate_invoice_adjustment_effect()"

ADJUST_REPLACEMENTS = (
    (
        "            WITH line_balances AS (\n",
        """            IF p_adjustment_type='DEBIT' AND app.invoice_line_outstanding(p_line_id)<=0 THEN
                RAISE EXCEPTION 'Invoice line is fully paid; balance:%',
                    app.invoice_line_outstanding(p_line_id) USING ERRCODE='P4509';
            END IF;
            WITH line_balances AS (
""",
    ),
)

EFFECT_REPLACEMENTS = (
    (
        "THEN RAISE EXCEPTION 'Invoice Adjustment would violate the issued obligation'\n"
        "                USING ERRCODE='23514'; END IF;\n",
        """THEN RAISE EXCEPTION 'Invoice Adjustment would violate the issued obligation'
                USING ERRCODE='23514'; END IF;
            IF TG_TABLE_NAME='invoice_adjustments' THEN
                IF NEW.adjustment_type='DEBIT' AND v_line_obligation-NEW.amount_usd_cents<=0 THEN
                    RAISE EXCEPTION 'A debit Adjustment requires a positive line balance'
                        USING ERRCODE='23514'; END IF;
            END IF;
""",
    ),
)


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Debit Adjustment source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    _patch(ADJUST, ADJUST_REPLACEMENTS)
    _patch(EFFECT, EFFECT_REPLACEMENTS)


def downgrade() -> None:
    raise RuntimeError("Debit Adjustment line block is forward-only")
