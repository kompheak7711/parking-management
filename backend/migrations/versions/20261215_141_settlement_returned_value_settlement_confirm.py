# ruff: noqa: E501
"""A Final Settlement's own confirm that used a returned Credit counts against the return, and a
return reversal undoes that use through the companion (V1-056 sub-slice 10e-3d-2d-2c).

BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-014, DL-032; DB-SETTLE-005; owner answer (a) to
Q-2026-10-15-113. A Final Settlement's own confirm writes its Credit applications with the
Settlement and no correction link, so until now the walk did not see them: when the Customer's
other Lease closed after a return and its confirm let the returned Credit pay its debt, the return
kept its money left while the Credit held nothing.

- `app.settlement_returned_value_walk` (exact-text patches): for a Credit, each Final Settlement
  whose own confirm applied it is a walker too, at the time of its first such application, in the
  one order by time and id with the corrections; its id is the Final Settlement's (there is no
  correction). Its draw is the sum of those applications and it takes the returns' money, the
  oldest first. It is a walker only while some return's money is left at its place in the order,
  so a confirm before every return gives no row and no committed result changes.
- `app.settlement_returned_value_placed` (exact-text patch): such a take is placed on that
  confirm's Credit applications from the source, the newest first.
- `app.settlement_returned_value_follow` (exact-text patch): the writer of a Credit application
  with no correction link and a Final Settlement is that Final Settlement (until now such a
  payment stopped open, because its writer must be known).

Nothing else changes: the source lists such an application for undoing and its Settlement as a
companion (`app.settlement_credit_application_owner`), and the confirm reverses it linked to that
companion and puts back any rest through the companion's step, as for another Settlement's
correction (sub-slice 10e-3d-2d-2a). No table, column, constraint, trigger, lock or grant change.
A `RETURN_REVERSAL` or held-value draft recorded before this migration whose source now differs is
stale at its confirm (P5S02) or refused; staff reject it and record it again.
"""

from alembic import op
from sqlalchemy import text

revision = "20261215_141"
down_revision = "20261214_140"
branch_labels = None
depends_on = None

WALK = "app.settlement_returned_value_walk(uuid,text,uuid,uuid)"
WALK_REPLACEMENTS = (
    (
        """
        FOR v_correction IN
            SELECT correction.id,
                CASE WHEN draft.payload->>'variant' IN ('HELD_VALUE_REFUND','RETURN_REVERSAL')""",
        """
        FOR v_correction IN
            SELECT walker.* FROM (SELECT correction.id,false AS confirm,
                correction.occurred_at AS walk_at,
                CASE WHEN draft.payload->>'variant' IN ('HELD_VALUE_REFUND','RETURN_REVERSAL')""",
        1,
    ),
    (
        """
              AND draft.payload->>'variant' IS DISTINCT FROM 'RETURN_REVERSAL_COMPANION'
            ORDER BY correction.occurred_at,correction.id
        LOOP""",
        """
              AND draft.payload->>'variant' IS DISTINCT FROM 'RETURN_REVERSAL_COMPANION'
            -- Sub-slice 10e-3d-2d-2c (owner answer (a) to Q-2026-10-15-113): for a Credit, also
            -- each Final Settlement whose own confirm applied it (its applications carry the
            -- Settlement and no correction link), at the time of its first such application.
            UNION ALL
            SELECT settlement.id,true,min(application.occurred_at),NULL::text,'{}'::uuid[]
            FROM app.final_settlements settlement
            JOIN app.customer_credit_applications application
                ON application.final_settlement_id=settlement.id
            WHERE p_kind='CREDIT' AND application.customer_credit_id=p_source
              AND NOT EXISTS(SELECT 1 FROM app.settlement_correction_effects linked
                  WHERE linked.customer_credit_application_id=application.id)
            GROUP BY settlement.id) walker
            ORDER BY walker.walk_at,walker.id
        LOOP""",
        1,
    ),
    (
        """
            v_use:=GREATEST(v_paid-v_back,0);""",
        """
            v_use:=GREATEST(v_paid-v_back,0);
            -- Sub-slice 10e-3d-2d-2c: a Final Settlement's own confirm draws its Credit
            -- applications from the source (it has no correction records, no return and names
            -- none); it is a walker only while some return's money is left, so a confirm before
            -- every return gives no row.
            IF v_correction.confirm THEN
                v_use:=CASE WHEN COALESCE((SELECT sum(remaining)
                        FROM unnest(v_left) AS remaining),0)>0
                    THEN (SELECT COALESCE(sum(application.amount_usd_cents),0)
                        FROM app.customer_credit_applications application
                        WHERE application.final_settlement_id=v_correction.id
                          AND application.customer_credit_id=p_source
                          AND NOT EXISTS(SELECT 1 FROM app.settlement_correction_effects linked
                              WHERE linked.customer_credit_application_id=application.id))
                    ELSE 0 END;
            END IF;""",
        1,
    ),
)

PLACED = "app.settlement_returned_value_placed(uuid,text,uuid,uuid,boolean)"
PLACED_REPLACEMENTS = (
    (
        """
        ), placed AS (""",
        """
            -- Sub-slice 10e-3d-2d-2c (owner answer (a) to Q-2026-10-15-113): a take by a Final
            -- Settlement's own confirm is placed on its Credit applications from the source, the
            -- newest first (no correction links them; the taker is the Final Settlement).
            UNION ALL
            SELECT confirm_taker.taker,'CREDIT_APPLICATION',application.id,
                application.amount_usd_cents,2,
                row_number() OVER (PARTITION BY confirm_taker.taker
                    ORDER BY application.occurred_at DESC,application.id DESC)
            FROM (SELECT DISTINCT taken.taker FROM taken) confirm_taker
            JOIN app.final_settlements settlement ON settlement.id=confirm_taker.taker
            JOIN app.customer_credit_applications application
                ON application.final_settlement_id=settlement.id
            WHERE p_kind='CREDIT' AND application.customer_credit_id=p_source
              AND NOT EXISTS(SELECT 1 FROM app.settlement_correction_effects linked
                  WHERE linked.customer_credit_application_id=application.id)
        ), placed AS (""",
        1,
    ),
)

FOLLOW = "app.settlement_returned_value_follow(uuid,text,uuid,text,uuid,bigint,bigint,uuid)"
FOLLOW_REPLACEMENTS = (
    (
        """
                    WHERE effect.customer_credit_application_id=v_record;""",
        """
                    WHERE effect.customer_credit_application_id=v_record;
                    -- Sub-slice 10e-3d-2d-2c (owner answer (a) to Q-2026-10-15-113): a Final
                    -- Settlement's own confirm wrote an application with no correction link.
                    IF v_owner IS NULL THEN v_owner:=v_credit.final_settlement_id; END IF;""",
        1,
    ),
)

PATCHES = (
    (WALK, WALK_REPLACEMENTS),
    (PLACED, PLACED_REPLACEMENTS),
    (FOLLOW, FOLLOW_REPLACEMENTS),
)


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
            raise RuntimeError(
                f"Returned value Settlement confirm contract changed: {signature}"
            )
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Returned value Settlement confirm migration is forward-only")
