# ruff: noqa: E501
"""What an earlier return-only correction has left, counted over every correction (V1-056 sub-slice 10e-3d-1).

BR-SETTLE-008, BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-014, DL-032; DB-SETTLE-005; owner answer (a)
to Q-2026-10-12-97 and its detail of 2026-10-13:

- A new internal count, `app.settlement_returned_value_left`, walks a Settlement's corrections
  oldest first, each with what it did at its own time. A correction's own returns into a Credit
  or Deposit open its entry; what it drew from that Credit or Deposit (applications, Refunds and
  reversed returns, less the applications it reversed and the Refunds it recovered by a charge,
  so the money it released is paid out first) takes first from its own entry (its Refunds and
  step paid out its own returned money first, as the sub-slice 10e-3b and 10e-3c reversals
  charge back), then from the entry of the earlier correction it names (a `HELD_VALUE_REFUND`, or
  a `RETURN_REVERSAL`), then from the other entries, oldest return first. Review round 2: its own
  Deposit receipts and forfeiture reversals count as brought back, its receipt reversals and
  forfeitures as paid out, and its reversal of the Credit takes all the Credit still holds. So a
  sweep (the shared DL-032 step of a correction that does not name the earlier correction,
  BR-SETTLE-008) now lowers the earlier correction's left value; a part a `RETURN_REVERSAL` applies
  again is money the reversed correction already used. Only uses made by corrections of the
  Settlement count;
  ordinary Credit spending stays the known limit of owner answer 2 to Q-2026-10-09-63, and what
  the Credit or Deposit holds still caps every payout.
- `app.settlement_held_deposit_value` and `app.settlement_held_credit_value` return that count's
  left value (same signatures; their readers do not change).
- A reversal of an earlier return takes only that return's own left value: the `RETURN_REVERSAL`
  source names the part of the earlier correction's returned money that another correction paid
  out (`swept_usd_cents`), and the check refuses a positive one until the owner answers
  Q-2026-10-13-100 (sub-slice 10e-3d-2), and a missing one. Review round 2: the source also names
  the earlier correction's left value (`left_usd_cents`), and the check refuses a reversal that
  would take more than it from the source (the returned amount and the part applied again less the
  applications and recoveries it undoes), for example when a Refund of the uses came back through
  a later return.

A `HELD_VALUE_REFUND` or `RETURN_REVERSAL` draft recorded before this migration whose source now
reads differently is stale at its confirm (P5S02); staff reject it and record it again.
"""

from alembic import op
from sqlalchemy import text

revision = "20261203_129"
down_revision = "20261202_128"
branch_labels = None
depends_on = None

FUNCTION_SQL = r"""
    -- Sub-slice 10e-3d (owner answer (a) to Q-2026-10-12-97 and its detail of 2026-10-13): the
    -- returned money of each correction of a Settlement in one Credit or Deposit, and how much of
    -- it the corrections used. The Settlement's corrections are walked oldest first (the
    -- correction's time, then its id), leaving out p_except, each with what it did at its own
    -- time. A correction's own returns into the source (its linked VALUE_CORRECTION rows) open
    -- its entry. What it drew from the source is what it paid out (its linked applications from
    -- the source and Refunds from it, and the returns it reversed, its linked CORRECTION_REVERSAL
    -- rows) less what it brought back (its linked reversals of applications from the source and
    -- its linked RECOVERED_BY_CHARGE rows of Refunds from it), so a correction pays out the money
    -- it released first (review round 1: a released application's rest written again and the
    -- Refund of the released part are not new uses). What it drew takes first from its own
    -- entry (sub-slices 10e-3b and 10e-3c: its Refunds and step paid out its own returned money
    -- first), then from the entry of the earlier correction it names (a HELD_VALUE_REFUND, or a
    -- RETURN_REVERSAL, whose return reversal empties the named entry), then from the other
    -- entries, oldest return first; the rest is the source's other money and is not counted.
    -- What an entry gives in that last pass went to a correction that neither is it nor names
    -- it (swept). Only uses made by corrections count: ordinary Credit spending is the known
    -- limit of owner answer 2 to Q-2026-10-09-63, and what the source holds caps every payout.
    CREATE FUNCTION app.settlement_returned_value_left(p_settlement uuid,p_kind text,
        p_source uuid,p_except uuid)
    RETURNS TABLE(settlement_correction_id uuid,returned_usd_cents bigint,used_usd_cents bigint,
        swept_usd_cents bigint,left_usd_cents bigint)
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE
        v_ids uuid[]:='{}'; v_returned bigint[]:='{}'; v_left bigint[]:='{}';
        v_swept bigint[]:='{}'; v_correction record; v_return bigint; v_own bigint;
        v_use bigint; v_take bigint; v_named integer; v_index integer;
    BEGIN
        IF p_settlement IS NULL OR p_source IS NULL OR p_kind IS NULL
            OR p_kind NOT IN ('CREDIT','DEPOSIT') THEN
            RAISE EXCEPTION 'Returned value source is invalid' USING ERRCODE='22023'; END IF;
        FOR v_correction IN
            SELECT correction.id,
                CASE WHEN draft.payload->>'variant' IN ('HELD_VALUE_REFUND','RETURN_REVERSAL')
                    THEN draft.payload->>'held_from_settlement_correction_id' END AS named
            FROM app.settlement_corrections correction
            JOIN app.financial_drafts draft
                ON draft.id=correction.correlation_id AND draft.kind='SETTLEMENT_CORRECTION'
            WHERE correction.final_settlement_id=p_settlement
              AND correction.id IS DISTINCT FROM p_except
            ORDER BY correction.occurred_at,correction.id
        LOOP
            SELECT COALESCE(sum(returned.source_balance_effect_usd_cents),0) INTO v_return
            FROM app.settlement_correction_effects effect
            JOIN app.refund_corrections returned ON returned.id=effect.refund_correction_id
            JOIN app.refunds origin ON origin.id=returned.refund_id
            WHERE effect.settlement_correction_id=v_correction.id
              AND returned.correction_kind='VALUE_CORRECTION'
              AND (p_kind='CREDIT' AND origin.source_customer_credit_id=p_source
                  OR p_kind='DEPOSIT' AND origin.source_deposit_id=p_source);
            -- Paid out: applications, Refunds and reversed returns.
            v_use:=COALESCE((SELECT sum(application.amount_usd_cents)
                    FROM app.settlement_correction_effects effect
                    JOIN app.customer_credit_applications application
                        ON application.id=effect.customer_credit_application_id
                    WHERE effect.settlement_correction_id=v_correction.id AND p_kind='CREDIT'
                      AND application.customer_credit_id=p_source),0)
                +COALESCE((SELECT sum(application.amount_usd_cents)
                    FROM app.settlement_correction_effects effect
                    JOIN app.deposit_applications application
                        ON application.id=effect.deposit_application_id
                    WHERE effect.settlement_correction_id=v_correction.id AND p_kind='DEPOSIT'
                      AND application.deposit_id=p_source),0)
                +COALESCE((SELECT sum(refund.usd_accounting_value_cents)
                    FROM app.settlement_correction_effects effect
                    JOIN app.refunds refund ON refund.id=effect.refund_id
                    WHERE effect.settlement_correction_id=v_correction.id
                      AND (p_kind='CREDIT' AND refund.source_customer_credit_id=p_source
                          OR p_kind='DEPOSIT' AND refund.source_deposit_id=p_source)),0)
                -COALESCE((SELECT sum(reversed.source_balance_effect_usd_cents)
                    FROM app.settlement_correction_effects effect
                    JOIN app.refund_corrections reversed
                        ON reversed.id=effect.refund_correction_id
                        AND reversed.correction_kind='CORRECTION_REVERSAL'
                    JOIN app.refunds origin ON origin.id=reversed.refund_id
                    WHERE effect.settlement_correction_id=v_correction.id
                      AND (p_kind='CREDIT' AND origin.source_customer_credit_id=p_source
                          OR p_kind='DEPOSIT' AND origin.source_deposit_id=p_source)),0)
            -- Brought back: reversed applications and Refunds recovered by a charge.
                -COALESCE((SELECT sum(application.amount_usd_cents)
                    FROM app.settlement_correction_effects effect
                    JOIN app.customer_credit_application_reversals reversal
                        ON reversal.id=effect.credit_application_reversal_id
                    JOIN app.customer_credit_applications application
                        ON application.id=reversal.credit_application_id
                    WHERE effect.settlement_correction_id=v_correction.id AND p_kind='CREDIT'
                      AND application.customer_credit_id=p_source),0)
                -COALESCE((SELECT sum(application.amount_usd_cents)
                    FROM app.settlement_correction_effects effect
                    JOIN app.deposit_application_reversals reversal
                        ON reversal.id=effect.deposit_application_reversal_id
                    JOIN app.deposit_applications application
                        ON application.id=reversal.deposit_application_id
                    WHERE effect.settlement_correction_id=v_correction.id AND p_kind='DEPOSIT'
                      AND application.deposit_id=p_source),0)
                -COALESCE((SELECT sum(recovery.source_balance_effect_usd_cents)
                    FROM app.settlement_correction_effects effect
                    JOIN app.refund_corrections recovery
                        ON recovery.id=effect.refund_correction_id
                        AND recovery.correction_kind='RECOVERED_BY_CHARGE'
                    JOIN app.refunds origin ON origin.id=recovery.refund_id
                    WHERE effect.settlement_correction_id=v_correction.id
                      AND (p_kind='CREDIT' AND origin.source_customer_credit_id=p_source
                          OR p_kind='DEPOSIT' AND origin.source_deposit_id=p_source)),0)
            -- Review round 2: a Deposit's own receipts and forfeiture reversals are brought back,
            -- its receipt reversals and forfeitures are paid out (all whole records).
                -COALESCE((SELECT sum(receipt.amount_usd_cents)
                    FROM app.settlement_correction_effects effect
                    JOIN app.deposit_receipts receipt ON receipt.id=effect.deposit_receipt_id
                    WHERE effect.settlement_correction_id=v_correction.id AND p_kind='DEPOSIT'
                      AND receipt.deposit_id=p_source),0)
                +COALESCE((SELECT sum(receipt.amount_usd_cents)
                    FROM app.settlement_correction_effects effect
                    JOIN app.deposit_receipt_reversals reversal
                        ON reversal.id=effect.deposit_receipt_reversal_id
                    JOIN app.deposit_receipts receipt ON receipt.id=reversal.deposit_receipt_id
                    WHERE effect.settlement_correction_id=v_correction.id AND p_kind='DEPOSIT'
                      AND receipt.deposit_id=p_source),0)
                +COALESCE((SELECT sum(disposition.amount_usd_cents)
                    FROM app.settlement_correction_effects effect
                    JOIN app.deposit_dispositions disposition
                        ON disposition.id=effect.deposit_disposition_id
                    WHERE effect.settlement_correction_id=v_correction.id AND p_kind='DEPOSIT'
                      AND disposition.deposit_id=p_source),0)
                -COALESCE((SELECT sum(disposition.amount_usd_cents)
                    FROM app.settlement_correction_effects effect
                    JOIN app.deposit_disposition_reversals reversal
                        ON reversal.id=effect.deposit_disposition_reversal_id
                    JOIN app.deposit_dispositions disposition
                        ON disposition.id=reversal.deposit_disposition_id
                    WHERE effect.settlement_correction_id=v_correction.id AND p_kind='DEPOSIT'
                      AND disposition.deposit_id=p_source),0);
            v_use:=GREATEST(v_use,0);
            -- Review round 2: its reversal of the Credit takes all the Credit still holds.
            IF p_kind='CREDIT' AND EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                JOIN app.customer_credit_reversals reversal
                    ON reversal.id=effect.customer_credit_reversal_id
                WHERE effect.settlement_correction_id=v_correction.id
                  AND reversal.customer_credit_id=p_source) THEN
                v_use:=v_return+(SELECT COALESCE(sum(remaining),0)::bigint
                    FROM unnest(v_left) AS remaining);
            END IF;
            -- Its own returned money first.
            v_take:=LEAST(v_use,v_return); v_use:=v_use-v_take; v_own:=v_return-v_take;
            -- Then the earlier correction it names.
            v_named:=array_position(v_ids::text[],v_correction.named);
            IF v_named IS NOT NULL THEN
                v_take:=LEAST(v_use,v_left[v_named]);
                v_left[v_named]:=v_left[v_named]-v_take; v_use:=v_use-v_take;
            END IF;
            -- Then the other returns, oldest first: money another correction paid out.
            v_index:=1;
            WHILE v_use>0 AND v_index<=cardinality(v_ids) LOOP
                v_take:=LEAST(v_use,v_left[v_index]);
                v_left[v_index]:=v_left[v_index]-v_take;
                v_swept[v_index]:=v_swept[v_index]+v_take;
                v_use:=v_use-v_take; v_index:=v_index+1;
            END LOOP;
            IF v_return>0 THEN
                v_ids:=v_ids||v_correction.id; v_returned:=v_returned||v_return;
                v_left:=v_left||v_own; v_swept:=v_swept||0::bigint;
            END IF;
        END LOOP;
        RETURN QUERY SELECT entry.id,entry.amount,entry.amount-entry.remaining,entry.taken,
                entry.remaining
            FROM unnest(v_ids,v_returned,v_left,v_swept) AS entry(id,amount,remaining,taken);
    END $$;
"""

INTERNAL = ("app.settlement_returned_value_left(uuid,text,uuid,uuid)",)

DEPOSIT_VALUE = "app.settlement_held_deposit_value(uuid,uuid)"
DEPOSIT_VALUE_REPLACEMENTS = (
    (
        """        WITH linked AS (
            SELECT later.id FROM app.settlement_corrections later
            JOIN app.financial_drafts draft
                ON draft.id=later.correlation_id AND draft.kind='SETTLEMENT_CORRECTION'
            WHERE draft.payload->>'variant'='HELD_VALUE_REFUND'
              AND draft.payload->>'held_from_settlement_correction_id'=p_earlier::text)
        SELECT GREATEST(0,
            (SELECT COALESCE(sum(returned.source_balance_effect_usd_cents),0)
                FROM app.settlement_correction_effects effect
                JOIN app.refund_corrections returned ON returned.id=effect.refund_correction_id
                JOIN app.refunds origin ON origin.id=returned.refund_id
                WHERE effect.settlement_correction_id=p_earlier AND origin.source_deposit_id=p_deposit
                  -- Sub-slice 10e-3: a reversed return leaves nothing.
                  AND NOT EXISTS(SELECT 1 FROM app.refund_corrections reversal
                      WHERE reversal.reverses_correction_id=returned.id))
            -(SELECT COALESCE(sum(application.amount_usd_cents),0) FROM linked
                JOIN app.settlement_correction_effects effect ON effect.settlement_correction_id=linked.id
                JOIN app.deposit_applications application
                    ON application.id=effect.deposit_application_id
                WHERE application.deposit_id=p_deposit)
            -(SELECT COALESCE(sum(refund.usd_accounting_value_cents),0) FROM linked
                JOIN app.settlement_correction_effects effect ON effect.settlement_correction_id=linked.id
                JOIN app.refunds refund ON refund.id=effect.refund_id
                WHERE refund.source_deposit_id=p_deposit))
""",
        """        -- Sub-slice 10e-3d (owner answer (a) to Q-2026-10-12-97): what the earlier
        -- correction returned into the Deposit less every correction's use that the count takes
        -- from it (app.settlement_returned_value_left); a reversed return leaves nothing.
        SELECT COALESCE((SELECT counted.left_usd_cents
            FROM app.settlement_corrections correction
            CROSS JOIN LATERAL app.settlement_returned_value_left(correction.final_settlement_id,
                'DEPOSIT',p_deposit,NULL) counted
            WHERE correction.id=p_earlier AND counted.settlement_correction_id=p_earlier),0)
""",
    ),
)

CREDIT_VALUE = "app.settlement_held_credit_value(uuid,uuid,uuid)"
CREDIT_VALUE_REPLACEMENTS = (
    (
        """        WITH users AS (
            SELECT p_earlier AS id
            UNION ALL
            SELECT later.id FROM app.settlement_corrections later
            JOIN app.financial_drafts draft
                ON draft.id=later.correlation_id AND draft.kind='SETTLEMENT_CORRECTION'
            WHERE draft.payload->>'variant'='HELD_VALUE_REFUND'
              AND draft.payload->>'held_from_settlement_correction_id'=p_earlier::text
              AND later.id IS DISTINCT FROM p_except)
        SELECT GREATEST(0,
            (SELECT COALESCE(sum(returned.source_balance_effect_usd_cents),0)
                FROM app.settlement_correction_effects effect
                JOIN app.refund_corrections returned ON returned.id=effect.refund_correction_id
                JOIN app.refunds origin ON origin.id=returned.refund_id
                WHERE effect.settlement_correction_id=p_earlier AND origin.source_customer_credit_id=p_credit
                  -- Sub-slice 10e-3: a reversed return leaves nothing.
                  AND NOT EXISTS(SELECT 1 FROM app.refund_corrections reversal
                      WHERE reversal.reverses_correction_id=returned.id))
            -(SELECT COALESCE(sum(application.amount_usd_cents),0) FROM users
                JOIN app.settlement_correction_effects effect ON effect.settlement_correction_id=users.id
                JOIN app.customer_credit_applications application
                    ON application.id=effect.customer_credit_application_id
                WHERE application.customer_credit_id=p_credit)
            -(SELECT COALESCE(sum(refund.usd_accounting_value_cents),0) FROM users
                JOIN app.settlement_correction_effects effect ON effect.settlement_correction_id=users.id
                JOIN app.refunds refund ON refund.id=effect.refund_id
                WHERE refund.source_customer_credit_id=p_credit AND users.id<>p_earlier))
""",
        """        -- Sub-slice 10e-3d (owner answer (a) to Q-2026-10-12-97): what the earlier
        -- correction returned into the Credit less every correction's use that the count takes
        -- from it (app.settlement_returned_value_left), leaving out p_except (a confirm leaves
        -- out its own records, owner answer 2 to Q-2026-10-09-63); a reversed return leaves
        -- nothing.
        SELECT COALESCE((SELECT counted.left_usd_cents
            FROM app.settlement_corrections correction
            CROSS JOIN LATERAL app.settlement_returned_value_left(correction.final_settlement_id,
                'CREDIT',p_credit,p_except) counted
            WHERE correction.id=p_earlier AND counted.settlement_correction_id=p_earlier),0)
""",
    ),
)

SOURCE = "app.settlement_return_reversal_source_state(uuid,uuid)"
SOURCE_REPLACEMENTS = (
    (
        """                        ELSE app.credit_latest_at(earlier.credit_id) END) FROM earlier))
""",
        """                        ELSE app.credit_latest_at(earlier.credit_id) END) FROM earlier),
            -- Sub-slice 10e-3d (owner detail of 2026-10-13 to Q-2026-10-12-97): the part of the
            -- earlier correction's returned money that a correction which neither is it nor names
            -- it paid out (app.settlement_returned_value_left).
            'swept_usd_cents',(SELECT counted.swept_usd_cents FROM earlier
                CROSS JOIN LATERAL app.settlement_returned_value_left(p_settlement,
                    CASE WHEN earlier.deposit_id IS NOT NULL THEN 'DEPOSIT' ELSE 'CREDIT' END,
                    COALESCE(earlier.deposit_id,earlier.credit_id),NULL) counted
                WHERE counted.settlement_correction_id=earlier.id),
            -- Review round 2: its left value; the reversal takes at most this from the source.
            'left_usd_cents',(SELECT counted.left_usd_cents FROM earlier
                CROSS JOIN LATERAL app.settlement_returned_value_left(p_settlement,
                    CASE WHEN earlier.deposit_id IS NOT NULL THEN 'DEPOSIT' ELSE 'CREDIT' END,
                    COALESCE(earlier.deposit_id,earlier.credit_id),NULL) counted
                WHERE counted.settlement_correction_id=earlier.id))
""",
    ),
)

ASSERT = "app.assert_settlement_return_reversal_allowed(jsonb)"
ASSERT_REPLACEMENTS = (
    (
        """        -- The source holds the returned amount again once the listed uses are undone; otherwise
        -- another path used the returned value, which this correction does not undo. A missing
        -- value is refused too (review round 1).
""",
        """        -- Sub-slice 10e-3d (owner detail of 2026-10-13 to Q-2026-10-12-97): a reversal of an
        -- earlier return takes only that return's own left value. Money of it that another
        -- correction paid out is not undone here; that waits for the owner (Q-2026-10-13-100).
        -- A missing part is refused too.
        IF jsonb_typeof(p_source->'swept_usd_cents') IS DISTINCT FROM 'number' THEN
            RAISE EXCEPTION 'The return reversal source is incomplete' USING ERRCODE='55000'; END IF;
        IF (p_source->>'swept_usd_cents')::bigint<>0 THEN
            RAISE EXCEPTION 'Another correction paid out this return''s money; reversing it waits for the owner'
                USING ERRCODE='55000'; END IF;
        -- Review round 2: the reversal takes from the source the returned amount and the part
        -- applied again less the applications and recoveries it undoes, and never more than the
        -- return's own left value (for example when a Refund of the uses came back through a
        -- later return: reverse that later return first).
        IF jsonb_typeof(p_source->'left_usd_cents') IS DISTINCT FROM 'number' THEN
            RAISE EXCEPTION 'The return reversal source is incomplete' USING ERRCODE='55000'; END IF;
        IF (p_source->'earlier'->>'amount_usd_cents')::bigint
            +(SELECT COALESCE(sum((item->>'amount_usd_cents')::bigint),0)
                FROM jsonb_array_elements(p_source->'reapply') item)
            -(SELECT COALESCE(sum((application->>'amount_usd_cents')::bigint),0)
                FROM jsonb_array_elements((p_source->'credit_applications')
                    ||(p_source->'deposit_applications')) application)
            -(SELECT COALESCE(sum((recovery->>'amount_usd_cents')::bigint),0)
                FROM jsonb_array_elements(p_source->'recoveries') recovery)
            >(p_source->>'left_usd_cents')::bigint THEN
            RAISE EXCEPTION 'The returned value is no longer available; undo its other use first'
                USING ERRCODE='55000'; END IF;
        -- The source holds the returned amount again once the listed uses are undone; otherwise
        -- another path used the returned value, which this correction does not undo. A missing
        -- value is refused too (review round 1).
""",
    ),
)

PATCHES = (
    (DEPOSIT_VALUE, DEPOSIT_VALUE_REPLACEMENTS),
    (CREDIT_VALUE, CREDIT_VALUE_REPLACEMENTS),
    (SOURCE, SOURCE_REPLACEMENTS),
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
            raise RuntimeError(f"Settlement returned value count contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(FUNCTION_SQL)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Settlement returned value count migration is forward-only")
