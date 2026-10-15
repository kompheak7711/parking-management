# ruff: noqa: E501
"""A returned Credit's count takes the corrections of every Final Settlement that use it
(V1-056 sub-slice 10e-3d-2d-1).

BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-014, DL-032; DB-SETTLE-005; owner answer (a) to
Q-2026-10-13-100 point 2 ("a correction on another Lease of the same Customer that uses the
returned Credit counts too"). A Customer Credit belongs to a Customer, not a Lease: a correction's
DL-032 step on another Lease of the same Customer applies it to that Customer's open debt there.
Until now the walk counted only the corrections of the returning correction's own Settlement, so
such a use left the return's left value too high (a held-value Refund naming the return could pay
out money a later return brought back, and its reversal could take that money).

- `app.settlement_returned_value_walk` (exact-text patch): for a Credit, the corrections walked
  are those of the given Settlement and, of every other Final Settlement, those with a linked
  record the walk reads for that Credit (a Credit application from it, a reversal of such an
  application, a Refund from it, a return, return reversal or recovery of such a Refund, a
  reversal of the Credit), all in one order by time and id. A Deposit belongs to one Lease, so its
  walk does not change. Corrections of the given Settlement with no such record give no walk rows,
  as before.
- `app.settlement_returned_value_placed` (exact-text patch): a take of the return's money by a
  correction of another Final Settlement is one open part of the new kind `OTHER_SETTLEMENT`
  (record id: that correction), before any other kind, so none of its records is listed for
  undoing.
- `app.assert_settlement_return_reversal_allowed` (exact-text patch): such a part is refused
  before any other open part (55000) until sub-slice 10e-3d-2d-2 builds the undo on the other
  Lease with a companion correction of its Settlement (owner answer (a) to Q-2026-10-13-103
  point 3).

Known limit kept: a use of the returned Credit by another Lease's own Final Settlement confirm
(not a correction) is not counted, as ordinary Credit spending outside a correction is not (owner
answer 2 to Q-2026-10-09-63); what the Credit holds still caps every payout. Counting in one time
order can move the attribution of a later sweep by this Settlement's own corrections to a later
return (oldest return first); this follows the owner's answer.

No lock, grant, table, constraint or trigger change. A `RETURN_REVERSAL` or `HELD_VALUE_REFUND`
draft recorded before this migration whose source now differs is stale at its confirm (P5S02);
staff reject it and record it again.
"""

from alembic import op
from sqlalchemy import text

revision = "20261211_137"
down_revision = "20261210_136"
branch_labels = None
depends_on = None

WALK = "app.settlement_returned_value_walk(uuid,text,uuid,uuid)"
WALK_REPLACEMENTS = (
    (
        """
            WHERE correction.final_settlement_id=p_settlement
              AND correction.id IS DISTINCT FROM p_except""",
        """
            WHERE (correction.final_settlement_id=p_settlement
                -- Sub-slice 10e-3d-2d-1 (owner answer (a) to Q-2026-10-13-100 point 2): a Credit
                -- belongs to a Customer, not a Lease, so its walk also takes the corrections of
                -- every other Final Settlement with a linked record this walk reads for it, in one
                -- time order; a Deposit belongs to one Lease, so its walk does not change.
                OR p_kind='CREDIT' AND correction.id IN (SELECT used.settlement_correction_id
                    FROM app.settlement_correction_effects used
                    LEFT JOIN app.customer_credit_applications application
                        ON application.id=used.customer_credit_application_id
                    LEFT JOIN app.customer_credit_application_reversals application_reversal
                        ON application_reversal.id=used.credit_application_reversal_id
                    LEFT JOIN app.customer_credit_applications reversed_application
                        ON reversed_application.id=application_reversal.credit_application_id
                    LEFT JOIN app.refunds refund ON refund.id=used.refund_id
                    LEFT JOIN app.refund_corrections refund_correction
                        ON refund_correction.id=used.refund_correction_id
                    LEFT JOIN app.refunds corrected_refund
                        ON corrected_refund.id=refund_correction.refund_id
                    LEFT JOIN app.customer_credit_reversals credit_reversal
                        ON credit_reversal.id=used.customer_credit_reversal_id
                    WHERE p_source IN (application.customer_credit_id,
                        reversed_application.customer_credit_id,refund.source_customer_credit_id,
                        corrected_refund.source_customer_credit_id,
                        credit_reversal.customer_credit_id)))
              AND correction.id IS DISTINCT FROM p_except""",
    ),
)

PLACED = "app.settlement_returned_value_placed(uuid,text,uuid,uuid,boolean)"
PLACED_REPLACEMENTS = (
    (
        """
                SELECT effects.taker,'CREDIT_REVERSAL' AS kind,reversal.id,1 AS record_group""",
        """
                -- Sub-slice 10e-3d-2d-1: a take by a correction of another Final Settlement is
                -- one open part (its undo on the other Lease is sub-slice 10e-3d-2d-2).
                SELECT taken.taker,'OTHER_SETTLEMENT' AS kind,taken.taker AS id,0 AS record_group
                FROM taken JOIN app.settlement_corrections taker_correction
                    ON taker_correction.id=taken.taker
                WHERE taker_correction.final_settlement_id<>p_settlement
                UNION ALL
                SELECT effects.taker,'CREDIT_REVERSAL' AS kind,reversal.id,1 AS record_group""",
    ),
)

ASSERT = "app.assert_settlement_return_reversal_allowed(jsonb)"
ASSERT_REPLACEMENTS = (
    (
        """
        -- What this reversal cannot undo yet, each with its own message: a payment a later""",
        """
        -- Sub-slice 10e-3d-2d-1 (owner answer (a) to Q-2026-10-13-100 point 2): a correction of
        -- another Final Settlement used this return's money; its undo on that Lease, with a
        -- companion correction of its Settlement (owner answer (a) to Q-2026-10-13-103 point 3),
        -- is sub-slice 10e-3d-2d-2.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements((p_source->'swept_open')||CASE WHEN v_walk THEN p_source->'own_open' ELSE '[]'::jsonb END) item
            WHERE item->>'kind'='OTHER_SETTLEMENT')
        THEN RAISE EXCEPTION 'A correction of another Lease''s Final Settlement used this return''s money; reversing it waits for sub-slice 10e-3d-2d-2'
            USING ERRCODE='55000'; END IF;
        -- What this reversal cannot undo yet, each with its own message: a payment a later""",
    ),
)

PATCHES = (
    (WALK, WALK_REPLACEMENTS),
    (PLACED, PLACED_REPLACEMENTS),
    (ASSERT, ASSERT_REPLACEMENTS),
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
            raise RuntimeError(f"Returned value other Settlements contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Returned value other Settlements migration is forward-only")
