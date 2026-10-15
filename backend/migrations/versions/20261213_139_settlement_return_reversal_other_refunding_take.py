# ruff: noqa: E501
"""A take by another Lease's correction that also paid a Refund from the returned Credit is undone
through the companion (V1-056 sub-slice 10e-3d-2d-2b-1).

BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-014; DB-SETTLE-005; owner answers (a) to Q-2026-10-13-100
point 2 and Q-2026-10-13-103 point 3. Since sub-slice 10e-3d-2d-2a a take of a return's money by a
correction of another Final Settlement B was placed on its records and undone through a companion
correction of B, but only when that correction paid no Refund from the source; otherwise the whole
take stayed one open `OTHER_SETTLEMENT` part. A correction's draw covers, in order, what it brought
back itself (the draw's offset), its own return, then the return it names, before any other
return's money, and its records are laid out Refunds first, then applications, the newest first.
Every Credit Refund writer caps its Refund by one of those three (a `REFUND` correction by what it
released, a `REFUND_RETURN` by its own return, a held-value Refund by its named return's left
value) or pays it from a Credit it creates itself, so another return's money starts after its
Refunds and sits on its applications, which the companion undoes (review round 1).

- `app.settlement_returned_value_placed` (exact-text patches): the `OTHER_SETTLEMENT` opened row is
  removed, so such a take is placed on its records as a take of this Settlement's; a part that falls
  on any record of a correction of another Final Settlement other than a Credit application (no
  real path through a take found; a Refund part's charge-back through the companion is not built)
  is one open `OTHER_SETTLEMENT` part named by that correction, as in sub-slice 10e-3d-2d-1, which
  the refusal function refuses with its existing message (an allow-list, security review round 1).
  For a Deposit source such a take stays refused (and is unreachable: a Deposit's walk reads only
  its own Settlement's corrections): each of its records is an open `OTHER_SETTLEMENT` part, and a
  stretch no record covers fails the source's sum check (security review round 3).

No other function, table, column, constraint, trigger, lock or grant change. A `RETURN_REVERSAL`
draft recorded before this migration whose source now differs is stale at its confirm (P5S02);
staff reject it and record it again.
"""

from alembic import op
from sqlalchemy import text

revision = "20261213_139"
down_revision = "20261212_138"
branch_labels = None
depends_on = None

PLACED = "app.settlement_returned_value_placed(uuid,text,uuid,uuid,boolean)"
PLACED_REPLACEMENTS = (
    (
        """
                -- Sub-slice 10e-3d-2d-1: a take by a correction of another Final Settlement is
                -- one open part (its undo on the other Lease is sub-slice 10e-3d-2d-2).
                SELECT taken.taker,'OTHER_SETTLEMENT' AS kind,taken.taker AS id,0 AS record_group
                FROM taken JOIN app.settlement_corrections taker_correction
                    ON taker_correction.id=taken.taker
                WHERE taker_correction.final_settlement_id<>p_settlement
                  -- Sub-slice 10e-3d-2d-2a: only while the take has a Refund from the source (its
                  -- charge-back through the companion is sub-slice 10e-3d-2d-2b); its Credit
                  -- applications are placed and undone through a companion correction.
                  AND (p_kind<>'CREDIT' OR EXISTS(SELECT 1 FROM effects
                      JOIN app.refunds refund ON refund.id=effects.refund_id
                      WHERE effects.taker=taken.taker
                        AND refund.source_customer_credit_id=p_source))
                UNION ALL
                SELECT effects.taker,'CREDIT_REVERSAL' AS kind,reversal.id,1 AS record_group""",
        """
                -- Sub-slice 10e-3d-2d-2b-1: a take by a correction of another Final Settlement is
                -- placed on its records as a take of this Settlement's, also when that correction
                -- paid a Refund from the source (a part on such a Refund stays open, below).
                SELECT effects.taker,'CREDIT_REVERSAL' AS kind,reversal.id,1 AS record_group""",
        1,
    ),
    (
        """
        SELECT placed.taker,placed.kind,placed.id,placed.amount,
            (LEAST(placed.before_it+placed.amount,taken.start_at+taken.amount)
                -GREATEST(placed.before_it,taken.start_at))::bigint,
            (GREATEST(placed.before_it,taken.start_at)-placed.before_it)::bigint
        FROM placed JOIN taken ON taken.taker=placed.taker""",
        """
        -- Sub-slice 10e-3d-2d-2b-1: a part on any record of a correction of another Final
        -- Settlement other than a Credit application (which its companion undoes), such as a
        -- Refund, is one open part named by that correction (a Refund part's charge-back through
        -- the companion is not built; no real path through a take found), as in sub-slice
        -- 10e-3d-2d-1.
        SELECT placed.taker,CASE WHEN placed.kind<>'CREDIT_APPLICATION' AND other_taker.id IS NOT NULL
                THEN 'OTHER_SETTLEMENT' ELSE placed.kind END,
            CASE WHEN placed.kind<>'CREDIT_APPLICATION' AND other_taker.id IS NOT NULL
                THEN placed.taker ELSE placed.id END,placed.amount,
            (LEAST(placed.before_it+placed.amount,taken.start_at+taken.amount)
                -GREATEST(placed.before_it,taken.start_at))::bigint,
            (GREATEST(placed.before_it,taken.start_at)-placed.before_it)::bigint
        FROM placed JOIN taken ON taken.taker=placed.taker
        LEFT JOIN app.settlement_corrections other_taker ON other_taker.id=placed.taker
            AND other_taker.final_settlement_id<>p_settlement""",
        1,
    ),
)

PATCHES = ((PLACED, PLACED_REPLACEMENTS),)


def _patch(signature: str, replacements: tuple[tuple[str, str, int], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after, count in replacements:
        if definition.count(before) != count:
            raise RuntimeError(f"Return reversal other refunding take contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Return reversal other refunding take migration is forward-only")
