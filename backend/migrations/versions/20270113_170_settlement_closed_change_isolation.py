# ruff: noqa: E501
"""The 8e-1 closed Final Settlement refusal at READ COMMITTED only (V1-056 sub-slice 10h-4b).

BR-SETTLE-012, BR-SETTLE-013, DL-032.

- Owner answer (a) to Q-2026-10-20-145 point 1, the same way as the answer (a) to
  Q-2026-10-19-143: app.refuse_closed_final_settlement_change, the a0_ BEFORE trigger of the eight
  tables a closed Final Settlement guards (Invoices, one-time charges, VOID events, Adjustments and
  their reversals, Late-payment decisions, Charges and Charge corrections), refuses (55000) a write
  at an isolation level other than READ COMMITTED, before any read. A snapshot older than a
  Settlement's start would not see the Settlement, so the check cannot wait until it finds one.
  No app path writes these tables at a stricter level.

Fail-closed refusal the owner approved: one exact-text replacement; signature, settings and
privileges are kept. No table, column, trigger, constraint or grant change.
"""

from alembic import op
from sqlalchemy import text

revision = "20270113_170"
down_revision = "20270112_169"
branch_labels = None
depends_on = None

GUARD = "app.refuse_closed_final_settlement_change()"

GUARD_REPLACEMENTS = (
    (
        "        BEGIN\n"
        "            -- Separate branches: each table's row has only its own columns. On app.invoices the\n",
        "        BEGIN\n"
        "            -- Sub-slice 10h-4b (owner answer (a) to Q-2026-10-20-145 point 1): a snapshot older\n"
        "            -- than a Final Settlement's start would not see it, so these tables are written only\n"
        "            -- at READ COMMITTED.\n"
        "            IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN\n"
        "                RAISE EXCEPTION 'An Invoice, Adjustment or Late-payment record is written at READ COMMITTED'\n"
        "                    USING ERRCODE='55000'; END IF;\n"
        "            -- Separate branches: each table's row has only its own columns. On app.invoices the\n",
    ),
)


def _definition(signature: str) -> str:
    return str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )


def _replaced(signature: str, replacements: tuple[tuple[str, str], ...]) -> str:
    definition = _definition(signature)
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Closed Settlement change isolation contract changed: {signature}")
        definition = definition.replace(before, after)
    return definition


def upgrade() -> None:
    # CREATE OR REPLACE keeps the function's identity, owner and privileges.
    op.execute(_replaced(GUARD, GUARD_REPLACEMENTS))


def downgrade() -> None:
    raise RuntimeError("Closed Settlement change isolation migration is forward-only")
