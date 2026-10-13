# ruff: noqa: E501
"""The own uses of a return placed by the walk (V1-056 sub-slice 10e-3d-2b-1b).

BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-014, DL-032; DB-SETTLE-005; owner answer (a) to
Q-2026-10-13-100 point 1 (the reversal of a mistaken return charges the paid-out part back to the
person who received it and makes the debt its money paid owed again):

- New internal `app.settlement_returned_value_parts(p_settlement, p_kind, p_source, p_earlier,
  p_swept)`: the record parts the walk places a return's money on, for the takes of other
  corrections (`p_swept` true, the sub-slice 10e-3d-2a takes) or for the takes of the return's own
  correction and of the corrections naming it (`p_swept` false). Its body is the body of
  `app.settlement_returned_value_takes` with that one condition; the takes function is replaced by a
  call to it with `p_swept` true (same signature, settings and privileges), so the two cannot
  disagree.
- `app.settlement_return_reversal_source_state` (exact-text patches): the own uses of the earlier
  correction E (E's own correction and the held-value Refunds naming E) take the walk path when two
  or more of them paid out from the source, when an own application from it was reversed since
  (round 2 note N3 of sub-slice 10e-3d-2a), or when an own correction's draw starts after money it
  brought back (round 1 note N2 of sub-slice 10e-3d-2b-1a; defensive: today no `REFUND_RETURN` or
  `HELD_VALUE_REFUND` writer links a record that brings money back). On that path each own
  correction's take of E's money sits on its Refunds (the oldest first) and then on its
  applications (the newest first), after what it brought back, each reversed application followed
  to its successor (a part with none, or more than it, stays open); the parts are
  listed, charged back and applied again exactly as the other corrections' parts, the pooled own
  lists stay empty, and the source names them in `own_parts` and `own_open` (the shapes of `swept`
  and `swept_open`). Otherwise the pooled own path of sub-slices 10e-3b and 10e-3c is unchanged and
  both keys are null.
- `app.assert_settlement_return_reversal_allowed` (exact-text patches): both keys must be null or
  lists together; on the walk path the own parts are held to the rules of the other corrections'
  parts (exact amounts, a Refund part no more than its net and without a return of its own, an
  application part listed and reversed whole with exactly its rest applied again, each above 0),
  their total is exactly the part of the returned money the own uses used, no record is a part
  twice, every listed application, recovery and part applied again belongs to a part, an own part
  that cannot be undone yet has the message of its kind, and the pooled-path checks (the Refund
  with its own return on the shared path, the one own part applied again, the flag of own
  corrections that also took another return's money) do not apply.

No writer, lock or grant changes. A `RETURN_REVERSAL` draft recorded before this migration has a
source without the two new keys, so it is stale at its confirm (P5S02); staff reject it and record
it again.
"""

from alembic import op
from sqlalchemy import text

revision = "20261206_132"
down_revision = "20261205_131"
branch_labels = None
depends_on = None

FUNCTION_SQL = r"""
    CREATE FUNCTION app.settlement_returned_value_parts(p_settlement uuid,p_kind text,
            p_source uuid,p_earlier uuid,p_swept boolean)
        RETURNS TABLE(settlement_correction_id uuid,record_kind text,record_id uuid,
            amount_usd_cents bigint,part_usd_cents bigint)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        WITH walked AS MATERIALIZED (
            SELECT walk.* FROM app.settlement_returned_value_walk(p_settlement,p_kind,p_source,
                NULL) walk
        ), taken AS (
            SELECT take.walk_correction_id AS taker,take.walk_amount_usd_cents AS amount,
                draw.walk_offset_usd_cents+take.walk_offset_usd_cents AS start_at
            FROM walked take
            JOIN walked draw
                ON draw.walk_kind='DRAW' AND draw.walk_correction_id=take.walk_correction_id
            -- Sub-slice 10e-3d-2b-1b: the takes of other corrections (p_swept true) or of the
            -- return's own correction and the corrections naming it (p_swept false).
            WHERE take.walk_kind='TAKE' AND take.walk_swept=p_swept AND take.walk_entry_id=p_earlier
        ), effects AS (
            SELECT taken.taker,effect.* FROM taken
            JOIN app.settlement_correction_effects effect ON effect.settlement_correction_id=taken.taker
        ), opened AS (
            SELECT DISTINCT ON (found.taker) found.taker,found.kind,found.id FROM (
                SELECT effects.taker,'CREDIT_REVERSAL' AS kind,reversal.id,1 AS record_group
                FROM effects JOIN app.customer_credit_reversals reversal
                    ON reversal.id=effects.customer_credit_reversal_id
                WHERE p_kind='CREDIT' AND reversal.customer_credit_id=p_source
                UNION ALL
                SELECT effects.taker,'RETURN_REVERSAL',reversed.id,2
                FROM effects JOIN app.refund_corrections reversed
                    ON reversed.id=effects.refund_correction_id
                    AND reversed.correction_kind='CORRECTION_REVERSAL'
                JOIN app.refunds origin ON origin.id=reversed.refund_id
                WHERE p_kind='CREDIT' AND origin.source_customer_credit_id=p_source
                   OR p_kind='DEPOSIT' AND origin.source_deposit_id=p_source
                UNION ALL
                SELECT effects.taker,'RECEIPT_REVERSAL',reversal.id,3
                FROM effects JOIN app.deposit_receipt_reversals reversal
                    ON reversal.id=effects.deposit_receipt_reversal_id
                JOIN app.deposit_receipts receipt ON receipt.id=reversal.deposit_receipt_id
                WHERE p_kind='DEPOSIT' AND receipt.deposit_id=p_source
                UNION ALL
                SELECT effects.taker,'FORFEITURE',disposition.id,4
                FROM effects JOIN app.deposit_dispositions disposition
                    ON disposition.id=effects.deposit_disposition_id
                WHERE p_kind='DEPOSIT' AND disposition.deposit_id=p_source) found
            ORDER BY found.taker,found.record_group,found.id
        ), records AS (
            SELECT effects.taker,'REFUND' AS kind,refund.id,
                refund.usd_accounting_value_cents::bigint AS amount,1 AS record_group,
                row_number() OVER (PARTITION BY effects.taker
                    ORDER BY refund.processed_at,refund.id) AS record_order
            FROM effects JOIN app.refunds refund ON refund.id=effects.refund_id
            WHERE p_kind='CREDIT' AND refund.source_customer_credit_id=p_source
               OR p_kind='DEPOSIT' AND refund.source_deposit_id=p_source
            UNION ALL
            SELECT effects.taker,'CREDIT_APPLICATION',application.id,application.amount_usd_cents,2,
                row_number() OVER (PARTITION BY effects.taker
                    ORDER BY application.occurred_at DESC,application.id DESC)
            FROM effects JOIN app.customer_credit_applications application
                ON application.id=effects.customer_credit_application_id
            WHERE p_kind='CREDIT' AND application.customer_credit_id=p_source
            UNION ALL
            SELECT effects.taker,'DEPOSIT_APPLICATION',application.id,application.amount_usd_cents,2,
                row_number() OVER (PARTITION BY effects.taker
                    ORDER BY application.occurred_at DESC,application.application_order DESC,
                        application.id DESC)
            FROM effects JOIN app.deposit_applications application
                ON application.id=effects.deposit_application_id
            WHERE p_kind='DEPOSIT' AND application.deposit_id=p_source
        ), placed AS (
            SELECT records.*,COALESCE(sum(records.amount) OVER (PARTITION BY records.taker
                    ORDER BY records.record_group,records.record_order
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0) AS before_it
            FROM records WHERE NOT EXISTS(SELECT 1 FROM opened WHERE opened.taker=records.taker)
        )
        SELECT placed.taker,placed.kind,placed.id,placed.amount,
            (LEAST(placed.before_it+placed.amount,taken.start_at+taken.amount)
                -GREATEST(placed.before_it,taken.start_at))::bigint
        FROM placed JOIN taken ON taken.taker=placed.taker
        WHERE placed.before_it+placed.amount>taken.start_at
          AND placed.before_it<taken.start_at+taken.amount
        UNION ALL
        SELECT opened.taker,opened.kind,opened.id,taken.amount,taken.amount
        FROM opened JOIN taken ON taken.taker=opened.taker
    $$;

    -- The sub-slice 10e-3d-2a takes: the parts of other corrections, from the shared function.
    CREATE OR REPLACE FUNCTION app.settlement_returned_value_takes(p_settlement uuid,p_kind text,
            p_source uuid,p_earlier uuid)
        RETURNS TABLE(settlement_correction_id uuid,record_kind text,record_id uuid,
            amount_usd_cents bigint,part_usd_cents bigint)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT parts.settlement_correction_id,parts.record_kind,parts.record_id,
            parts.amount_usd_cents,parts.part_usd_cents
        FROM app.settlement_returned_value_parts(p_settlement,p_kind,p_source,p_earlier,true) parts
    $$;
"""

INTERNAL = ("app.settlement_returned_value_parts(uuid,text,uuid,uuid,boolean)",)
REPLACED = "app.settlement_returned_value_takes(uuid,text,uuid,uuid)"

WALK_FLAG = "(SELECT own_walk.walk FROM own_walk)"

SOURCE = "app.settlement_return_reversal_source_state(uuid,uuid)"
SOURCE_REPLACEMENTS = (
    (
        """            WHERE counted.settlement_correction_id=earlier.id
        -- Sub-slice 10e-3d-2b-1a (owner answer (a) to Q-2026-10-13-100 point 1): an application
""",
        """            WHERE counted.settlement_correction_id=earlier.id
        -- Sub-slice 10e-3d-2b-1b (owner answer (a) to Q-2026-10-13-100 point 1): the own uses'
        -- parts come from the walk, as the other corrections' parts, when two or more own
        -- corrections paid out from the source, when an own application from it was reversed
        -- since, or when an own correction's draw starts after money it brought back (defensive:
        -- no own correction's writer links such a record today). Otherwise the
        -- pooled own path of sub-slices 10e-3b and 10e-3c below places the returned money on
        -- the same records.
        ), own_walk AS (
            SELECT (SELECT count(DISTINCT effect.settlement_correction_id)
                    FROM app.settlement_correction_effects effect
                    WHERE effect.settlement_correction_id IN (SELECT users.id FROM users)
                      AND (effect.customer_credit_application_id IN (SELECT credit_use.id
                              FROM credit_applications credit_use)
                          OR effect.deposit_application_id IN (SELECT deposit_use.id
                              FROM deposit_applications deposit_use)
                          OR effect.refund_id IN (SELECT refund_use.id FROM paid refund_use
                              WHERE refund_use.net>0)))>=2
                OR EXISTS(SELECT 1 FROM earlier
                    JOIN users ON true
                    JOIN app.settlement_correction_effects effect
                        ON effect.settlement_correction_id=users.id
                    WHERE EXISTS(SELECT 1 FROM app.customer_credit_applications credit_use
                            JOIN app.customer_credit_application_reversals reversal
                                ON reversal.credit_application_id=credit_use.id
                            WHERE credit_use.id=effect.customer_credit_application_id
                              AND credit_use.customer_credit_id=earlier.credit_id)
                       OR EXISTS(SELECT 1 FROM app.deposit_applications deposit_use
                            JOIN app.deposit_application_reversals reversal
                                ON reversal.deposit_application_id=deposit_use.id
                            WHERE deposit_use.id=effect.deposit_application_id
                              AND deposit_use.deposit_id=earlier.deposit_id))
                OR EXISTS(SELECT 1 FROM earlier
                    CROSS JOIN LATERAL app.settlement_returned_value_walk(p_settlement,
                        CASE WHEN earlier.deposit_id IS NOT NULL THEN 'DEPOSIT' ELSE 'CREDIT' END,
                        COALESCE(earlier.deposit_id,earlier.credit_id),NULL) walk
                    WHERE walk.walk_kind='DRAW' AND walk.walk_offset_usd_cents>0
                      AND walk.walk_correction_id IN (SELECT users.id FROM users)) AS walk
        -- Sub-slice 10e-3d-2b-1a (owner answer (a) to Q-2026-10-13-100 point 1): an application
""",
    ),
    (
        """        ), swept_state AS (
            SELECT COALESCE(followed.correction_id,taken.settlement_correction_id)
""",
        """        ), swept_state AS (
            SELECT taken.own,COALESCE(followed.correction_id,taken.settlement_correction_id)
""",
    ),
    (
        """            FROM earlier
            CROSS JOIN LATERAL app.settlement_returned_value_takes(p_settlement,
                CASE WHEN earlier.deposit_id IS NOT NULL THEN 'DEPOSIT' ELSE 'CREDIT' END,
                COALESCE(earlier.deposit_id,earlier.credit_id),earlier.id) taken
""",
        """            FROM earlier
            CROSS JOIN LATERAL (
                SELECT false AS own,swept_take.* FROM app.settlement_returned_value_takes(p_settlement,
                    CASE WHEN earlier.deposit_id IS NOT NULL THEN 'DEPOSIT' ELSE 'CREDIT' END,
                    COALESCE(earlier.deposit_id,earlier.credit_id),earlier.id) swept_take
                -- Sub-slice 10e-3d-2b-1b: on the walk path also the own uses' parts (own true).
                UNION ALL
                SELECT true,own_take.* FROM app.settlement_returned_value_parts(p_settlement,
                    CASE WHEN earlier.deposit_id IS NOT NULL THEN 'DEPOSIT' ELSE 'CREDIT' END,
                    COALESCE(earlier.deposit_id,earlier.credit_id),earlier.id,false) own_take
                WHERE (SELECT own_walk.walk FROM own_walk)) taken
""",
    ),
    (
        """        -- from the source and one of them also took another return's money; that case waits for
        -- sub-slice 10e-3d-2b (it then derives the own uses' parts from the walk too).
""",
        """        -- from the source and one of them also took another return's money; that case waits for
        -- sub-slice 10e-3d-2b (it then derives the own uses' parts from the walk too). Since
        -- sub-slice 10e-3d-2b-1b every source with two or more own corrections that paid out
        -- takes the walk path (own_walk above): also when one of them paid out source money no
        -- return brought back, where the two can differ too (review round 2). The flag stays,
        -- and the refusal function refuses it only on a pooled-path source.
""",
    ),
    (
        """        ), swept_undone AS (
            SELECT swept_state.* FROM swept_state WHERE swept_state.open_kind IS NULL
""",
        """        -- Sub-slice 10e-3d-2b-1b: with the own uses' parts of the walk path (own true), listed,
        -- charged back and applied again exactly as the other corrections' parts.
        ), swept_undone AS (
            SELECT swept_state.* FROM swept_state WHERE swept_state.open_kind IS NULL
""",
    ),
    (
        """                FROM (SELECT own_use.* FROM credit_applications own_use
                    -- Sub-slice 10e-3b: the Refunds took the whole returned amount.
                    WHERE NOT (SELECT covered.refunds_only FROM covered)
""",
        """                FROM (SELECT own_use.* FROM credit_applications own_use
                    -- Sub-slice 10e-3b: the Refunds took the whole returned amount.
                    WHERE NOT (SELECT covered.refunds_only FROM covered)
                      -- Sub-slice 10e-3d-2b-1b: the pooled own path only.
                      AND NOT """
        + WALK_FLAG
        + """
""",
    ),
    (
        """                FROM (SELECT own_use.* FROM deposit_applications own_use
                    WHERE NOT (SELECT covered.refunds_only FROM covered)
""",
        """                FROM (SELECT own_use.* FROM deposit_applications own_use
                    WHERE NOT (SELECT covered.refunds_only FROM covered)
                      AND NOT """
        + WALK_FLAG
        + """
""",
    ),
    (
        """                    JOIN shares ON shares.id=own_paid.id WHERE shares.amount>0
""",
        """                    JOIN shares ON shares.id=own_paid.id WHERE shares.amount>0
                        AND NOT """
        + WALK_FLAG
        + """
""",
    ),
    (
        """            WHERE partial.debt_paid AND undone.before_it+undone.amount_usd_cents>partial.rest
""",
        """            WHERE partial.debt_paid AND undone.before_it+undone.amount_usd_cents>partial.rest
              AND NOT """
        + WALK_FLAG
        + """
""",
    ),
    (
        """                    ORDER BY taken.settlement_correction_id,taken.record_id),'[]'::jsonb)
                FROM swept_undone taken),
            'swept_undone_usd_cents',(SELECT COALESCE(sum(taken.part_usd_cents),0)
                FROM swept_undone taken),
""",
        """                    ORDER BY taken.settlement_correction_id,taken.record_id),'[]'::jsonb)
                FROM swept_undone taken WHERE NOT taken.own),
            'swept_undone_usd_cents',(SELECT COALESCE(sum(taken.part_usd_cents),0)
                FROM swept_undone taken WHERE NOT taken.own),
""",
    ),
    (
        """                    SELECT swept_use.* FROM app.customer_credit_applications swept_use
""",
        """                    -- Sub-slice 10e-3d-2b-1b: on the walk path also each application of an own
                    -- use's part.
                    SELECT swept_use.* FROM app.customer_credit_applications swept_use
""",
    ),
    (
        """                    SELECT swept_use.* FROM app.deposit_applications swept_use
""",
        """                    -- Sub-slice 10e-3d-2b-1b: on the walk path also each application of an own
                    -- use's part.
                    SELECT swept_use.* FROM app.deposit_applications swept_use
""",
    ),
    (
        """            -- Sub-slice 10e-3c: the part applied again (at most one entry of the own uses;
""",
        """            -- Sub-slice 10e-3d-2b-1b: on the walk path one entry per own use's application
            -- part too, and none of the pooled own path below.
            -- Sub-slice 10e-3c: the part applied again (at most one entry of the own uses;
""",
    ),
    (
        """                FROM swept_state taken WHERE taken.open_kind IS NOT NULL),
""",
        """                FROM swept_state taken WHERE taken.open_kind IS NOT NULL AND NOT taken.own),
""",
    ),
    (
        """            'shared_with_other_returns',(SELECT shared_own.mixed FROM shared_own))
""",
        """            'shared_with_other_returns',(SELECT shared_own.mixed FROM shared_own),
            -- Sub-slice 10e-3d-2b-1b: on the walk path the own uses' parts this reversal undoes and
            -- those it cannot undo yet (the shapes of 'swept' and 'swept_open'); null on the
            -- pooled path.
            'own_parts',CASE WHEN """
        + WALK_FLAG
        + """ THEN (SELECT COALESCE(jsonb_agg(
                    jsonb_build_object('settlement_correction_id',taken.settlement_correction_id,
                        'record_kind',taken.record_kind,'record_id',taken.record_id,
                        'amount_usd_cents',taken.amount_usd_cents,'part_usd_cents',taken.part_usd_cents)
                    ORDER BY taken.settlement_correction_id,taken.record_id),'[]'::jsonb)
                FROM swept_undone taken WHERE taken.own) ELSE 'null'::jsonb END,
            'own_open',CASE WHEN """
        + WALK_FLAG
        + """ THEN (SELECT COALESCE(jsonb_agg(
                    jsonb_build_object('settlement_correction_id',taken.settlement_correction_id,
                        'kind',taken.open_kind,'record_kind',taken.record_kind,
                        'record_id',taken.record_id,'part_usd_cents',taken.part_usd_cents)
                    ORDER BY taken.settlement_correction_id,taken.record_id),'[]'::jsonb)
                FROM swept_state taken WHERE taken.open_kind IS NOT NULL AND taken.own)
                ELSE 'null'::jsonb END)
""",
    ),
)

OWN_PARTS = "CASE WHEN v_walk THEN p_source->'own_parts' ELSE '[]'::jsonb END"
OWN_OPEN = "CASE WHEN v_walk THEN p_source->'own_open' ELSE '[]'::jsonb END"

ASSERT = "app.assert_settlement_return_reversal_allowed(jsonb)"
ASSERT_REPLACEMENTS = (
    (
        """    DECLARE v_own bigint;
""",
        """    DECLARE v_own bigint; v_walk boolean;
""",
    ),
    (
        """            OR jsonb_typeof(p_source->'shared_with_other_returns') IS DISTINCT FROM 'boolean'
        THEN RAISE EXCEPTION 'The return reversal source is incomplete' USING ERRCODE='55000'; END IF;
""",
        """            OR jsonb_typeof(p_source->'shared_with_other_returns') IS DISTINCT FROM 'boolean'
        THEN RAISE EXCEPTION 'The return reversal source is incomplete' USING ERRCODE='55000'; END IF;
        -- Sub-slice 10e-3d-2b-1b: the own uses' parts and those not undone yet are null on the
        -- pooled path of sub-slices 10e-3b and 10e-3c and lists on the walk path, both alike.
        IF jsonb_typeof(p_source->'own_parts') IS NULL
            OR jsonb_typeof(p_source->'own_parts') NOT IN ('null','array')
            OR jsonb_typeof(p_source->'own_open') IS DISTINCT FROM jsonb_typeof(p_source->'own_parts')
        THEN RAISE EXCEPTION 'The return reversal source is incomplete' USING ERRCODE='55000'; END IF;
        v_walk:=jsonb_typeof(p_source->'own_parts')='array';
        -- Review round 1: the pooled-path checks of the totals are skipped on the walk path, so
        -- there the totals are checked to be there as numbers (fail closed, as the pooled path
        -- refuses missing totals).
        IF v_walk AND (jsonb_typeof(p_source->'uses'->'applied_usd_cents') IS DISTINCT FROM 'number'
            OR jsonb_typeof(p_source->'uses'->'refunded_usd_cents') IS DISTINCT FROM 'number'
            OR jsonb_typeof(p_source->'uses'->'returned_refunds') IS DISTINCT FROM 'number')
        THEN RAISE EXCEPTION 'The return reversal source is incomplete' USING ERRCODE='55000'; END IF;
""",
    ),
    (
        """            OR EXISTS(SELECT 1 FROM jsonb_array_elements((p_source->'swept')||(p_source->'swept_open')) item
""",
        """            -- Sub-slice 10e-3d-2b-1b: the own uses' parts too, on the walk path.
            OR EXISTS(SELECT 1 FROM jsonb_array_elements((p_source->'swept')||(p_source->'swept_open')
                ||"""
        + OWN_PARTS
        + "||"
        + OWN_OPEN
        + """) item
""",
    ),
    (
        """        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'swept_open') item
            WHERE item->>'kind'='CHANGED_APPLICATION')
""",
        """        -- Sub-slice 10e-3d-2b-1b: also an own use's part on the walk path.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements((p_source->'swept_open')||"""
        + OWN_OPEN
        + """) item
            WHERE item->>'kind'='CHANGED_APPLICATION')
""",
    ),
    (
        """        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'swept_open') item
            WHERE item->>'kind' IN ('CREDIT_REVERSAL','RECEIPT_REVERSAL'))
""",
        """        IF EXISTS(SELECT 1 FROM jsonb_array_elements((p_source->'swept_open')||"""
        + OWN_OPEN
        + """) item
            WHERE item->>'kind' IN ('CREDIT_REVERSAL','RECEIPT_REVERSAL'))
""",
    ),
    (
        """        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'swept_open') item
            WHERE item->>'kind'='FORFEITURE')
""",
        """        IF EXISTS(SELECT 1 FROM jsonb_array_elements((p_source->'swept_open')||"""
        + OWN_OPEN
        + """) item
            WHERE item->>'kind'='FORFEITURE')
""",
    ),
    (
        """        IF jsonb_array_length(p_source->'swept_open')>0 THEN
""",
        """        IF jsonb_array_length((p_source->'swept_open')||"""
        + OWN_OPEN
        + """)>0 THEN
""",
    ),
    (
        """        -- be this return's money; that case waits for sub-slice 10e-3d-2b.
        IF (p_source->>'shared_with_other_returns')::boolean THEN
""",
        """        -- be this return's money; that case waits for sub-slice 10e-3d-2b. Since sub-slice
        -- 10e-3d-2b-1b the source takes the walk path in that case, so the flag refuses only a
        -- pooled-path source (fail closed).
        IF (p_source->>'shared_with_other_returns')::boolean AND NOT v_walk THEN
""",
    ),
    (
        """        -- as exactly one entry.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'swept') taken
""",
        """        -- as exactly one entry. Sub-slice 10e-3d-2b-1b: the own uses' parts of the walk path too.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements((p_source->'swept')||"""
        + OWN_PARTS
        + """) taken
""",
    ),
    (
        """        v_own:=(p_source->'earlier'->>'amount_usd_cents')::bigint
            -(p_source->>'left_usd_cents')::bigint-(p_source->>'swept_usd_cents')::bigint;
""",
        """        v_own:=(p_source->'earlier'->>'amount_usd_cents')::bigint
            -(p_source->>'left_usd_cents')::bigint-(p_source->>'swept_usd_cents')::bigint;
        -- Sub-slice 10e-3d-2b-1b: on the walk path the own uses' parts are exactly that part of
        -- the returned money, no record is a part twice, and every listed application, recovery
        -- and part applied again belongs to a part (the pooled own lists are empty).
        -- Review round 1: a missing amount makes the comparison unknown, which is refused too.
        -- Review round 2: nested, so the own lists are read only on the walk path.
        IF v_walk THEN IF (COALESCE((SELECT COALESCE(sum((item->>'part_usd_cents')::bigint),0)
                    FROM jsonb_array_elements(p_source->'own_parts') item)<>v_own,true)
            OR (SELECT count(*)<>count(DISTINCT item->>'record_id')
                FROM jsonb_array_elements((p_source->'swept')||(p_source->'own_parts')) item)
            OR EXISTS(SELECT 1 FROM jsonb_array_elements((p_source->'credit_applications')
                    ||(p_source->'deposit_applications')) application
                WHERE NOT EXISTS(SELECT 1
                    FROM jsonb_array_elements((p_source->'swept')||(p_source->'own_parts')) item
                    WHERE item->>'record_kind' IN ('CREDIT_APPLICATION','DEPOSIT_APPLICATION')
                      AND item->>'record_id'=application->>'id'))
            OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'recoveries') recovery
                WHERE NOT EXISTS(SELECT 1
                    FROM jsonb_array_elements((p_source->'swept')||(p_source->'own_parts')) item
                    WHERE item->>'record_kind'='REFUND' AND item->>'record_id'=recovery->>'refund_id'))
            OR EXISTS(SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(p_source->'reapply')='array'
                    THEN p_source->'reapply' ELSE '[]'::jsonb END) entry
                WHERE NOT EXISTS(SELECT 1
                    FROM jsonb_array_elements((p_source->'swept')||(p_source->'own_parts')) item
                    WHERE item->>'record_kind' IN ('CREDIT_APPLICATION','DEPOSIT_APPLICATION')
                      AND item->>'record_id'=entry->>'application_id')))
        THEN RAISE EXCEPTION 'The return reversal source is incomplete' USING ERRCODE='55000'; END IF;
        END IF;
""",
    ),
    (
        """            AND (p_source->'uses'->>'returned_refunds')::bigint>0,true)
""",
        """            AND (p_source->'uses'->>'returned_refunds')::bigint>0
            -- Sub-slice 10e-3d-2b-1b: the pooled path only; on the walk path a Refund part with
            -- its own return is refused above.
            AND NOT v_walk,true)
""",
    ),
    (
        """                    OR (SELECT count(*) FROM jsonb_array_elements(p_source->'reapply') item
                        WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'swept') taken
                            WHERE taken->>'record_id'=item->>'application_id'))>1
                    OR ((SELECT count(*) FROM jsonb_array_elements(p_source->'reapply') item
                            WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'swept') taken
""",
        """                    -- Sub-slice 10e-3d-2b-1b: the entries of the own uses' parts of the walk path
                    -- are checked with the other parts.
                    OR (SELECT count(*) FROM jsonb_array_elements(p_source->'reapply') item
                        WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements((p_source->'swept')
                                ||"""
        + OWN_PARTS
        + """) taken
                            WHERE taken->>'record_id'=item->>'application_id'))>1
                    OR ((SELECT count(*) FROM jsonb_array_elements(p_source->'reapply') item
                            WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements((p_source->'swept')
                                    ||"""
        + OWN_PARTS
        + """) taken
""",
    ),
)

PATCHES = (
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
            raise RuntimeError(
                f"Settlement return reversal own parts contract changed: {signature}"
            )
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(FUNCTION_SQL)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    for function in (*INTERNAL, REPLACED):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Settlement return reversal own parts migration is forward-only")
