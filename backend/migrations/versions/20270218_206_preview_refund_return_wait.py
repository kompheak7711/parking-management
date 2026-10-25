# ruff: noqa: E501
"""The preview also lists another Settlement's waiting REFUND_RETURN correction draft (V1-056 slice 12d).

Owner answer (a) to Q-2026-10-20-149 (BR-SETTLE-002, BR-SETTLE-013, BR-CREDIT-008; DL-093): the
release part of the Q-2026-10-20-146 answer (sub-slice 10i-4c, migration `20270117_174`) also
covers a waiting `REFUND_RETURN` correction draft whose plan overlay gives value back to a Credit
held by a person of another Lease. That other Lease's Settlement waits until the draft is
confirmed, rejected or withdrawn; no amount rule changes, only the order. One exact-text
replacement of the filter (checked to match once); same signature, settings and privileges.
"""

from alembic import op
from sqlalchemy import text

revision = "20270218_206"
down_revision = "20270217_205"
branch_labels = None
depends_on = None

PREVIEW = "app.final_settlement_preview(uuid,uuid,uuid,text[])"

PREVIEW_REPLACEMENTS = (
    (
        "                          OR (draft.payload->>'variant'='REFUND' AND EXISTS(SELECT 1\n",
        "                          -- V1-056 slice 12d (owner answer (a) to Q-2026-10-20-149): a\n"
        "                          -- REFUND_RETURN draft gives value back to its Credit the same way.\n"
        "                          OR (draft.payload->>'variant' IN ('REFUND','REFUND_RETURN') AND EXISTS(SELECT 1\n",
    ),
)


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Settlement preview refund return wait contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    _patch(PREVIEW, PREVIEW_REPLACEMENTS)


def downgrade() -> None:
    raise RuntimeError("Settlement preview refund return wait migration is forward-only")
