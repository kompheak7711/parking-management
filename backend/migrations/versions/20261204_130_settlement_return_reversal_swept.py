# ruff: noqa: E501
"""A return's reversal undoes the money another correction paid out (V1-056 sub-slice 10e-3d-2a).

BR-SETTLE-008, BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-014, BR-REFUND-015, DL-032; DB-SETTLE-005,
DB-REFUND-002; owner answer (a) to Q-2026-10-13-100 point 1 (the person who received the money pays
it back, and any debt that money paid becomes owed again; together exactly the mistaken amount):

- The count of sub-slice 10e-3d-1 becomes one internal walk, `app.settlement_returned_value_walk`,
  which `app.settlement_returned_value_left` (same signature, settings and results) and the new
  `app.settlement_returned_value_takes` both read, so they cannot disagree. The walk also names
  what each correction drew and brought back, and where each take sits in the taker's draw.
- `app.settlement_returned_value_takes` returns, for an earlier return-only correction E, each
  record of another correction S (neither E nor one naming E) that paid out part of E's money.
  Inside S the money S brought back pays out first, then S's Refunds from the source, the oldest
  first, then S's applications from it, the newest first; E's part of S's draw falls on those
  records in that order. An S that also paid out through a reversal of the Credit, a reversed
  return, a Deposit receipt reversal or a forfeiture is not split (implementer's reading, fail
  closed): one row names that record and the whole part (sub-slices 10e-3d-2c and 10e-2d).
- The `RETURN_REVERSAL` source undoes those parts too: a Refund part is charged back to the person
  who received that Refund (a share, as sub-slice 10e-3b), an application part reverses the
  application whole and applies the rest again to the same obligation from the same source (as
  sub-slice 10e-3c, one part per such application). The own uses' threshold becomes the part of
  E's money they used (E's used less its swept part). New keys: `swept` (the parts undone),
  `swept_undone_usd_cents` and `swept_open` (the parts it cannot undo yet, each with its kind).
- The refusal of a positive `swept_usd_cents` ends: the parts must add up exactly and be listed
  exactly (fail closed), and each part it cannot undo yet is refused with its own message (a
  payment a later correction changed: sub-slice 10e-3d-2b; a Credit reversal or a Deposit receipt
  reversal: sub-slice 10e-3d-2c; a forfeiture: refused, owner answer (a) to Q-2026-10-13-103 point
  2; any other: "undo its other use first").
- Review round 1: the parts applied again are listed in the DL-032 stage order, then in the order
  their applications were first written (the Deposit application check refuses a lower stage
  after a higher one in one correction); a Credit part applied again without a Customer
  designation on a newer application of an Invoice with Rent or Service lines, while an older one
  of that Invoice is reversed too, is refused (the Rent-first proposal would refuse it at the
  confirm; Q-2026-10-13-104); and when two or more own corrections paid out from the source and
  one of them also took another return's money (the source's flag
  `shared_with_other_returns`), the reversal waits for sub-slice 10e-3d-2b, because the own uses
  are undone over all own corrections at once while the walk takes them per correction.
- Review round 2 (owner answer (a) to Q-2026-10-13-105): the flag `shared_with_other_returns`
  must be there as true or false, as the other new keys must; the confirm's loop over the parts
  applied again refuses any source kind other than a Credit or a Deposit (fail closed).
- The confirm writes every part applied again, in the source's order (a Credit step or a Deposit
  application each); the recovery scope accepts a Refund of another correction of the same
  Settlement that the draft's source names as a swept part. The lock function needs no change: it
  reads the source's lists, so it locks every listed application's target, and the returned
  Credit or the Lease's Deposits are locked as before.

A `RETURN_REVERSAL` draft recorded before this migration is stale at its confirm (P5S02, its
source gained keys); staff reject it and record it again.
"""

from alembic import op
from sqlalchemy import text

revision = "20261204_130"
down_revision = "20261203_129"
branch_labels = None
depends_on = None

FUNCTION_SQL = r"""
    -- Sub-slice 10e-3d-2a: the walk of sub-slice 10e-3d-1 over a Settlement's corrections, oldest
    -- first, leaving out p_except, each with what it did at its own time. Rows: ENTRY (a
    -- correction's own returns into the source open its entry: the amount returned); DRAW (what
    -- a correction drew from the source, with what it brought back as the offset); TAKE (a part
    -- of a correction's draw taken from an entry, at the offset within that draw; swept when the
    -- entry is neither the correction's own nor the one it names). As in sub-slice 10e-3d-1: what
    -- a correction paid out (applications, Refunds, reversed returns, and for a Deposit its
    -- receipt reversals and forfeitures) less what it brought back (its reversals of
    -- applications, its recoveries by a charge, and for a Deposit its receipts and forfeiture
    -- reversals), never below 0; a reversal of the Credit takes all the Credit still holds. Its
    -- own entry first, then the entry of the earlier correction it names (a HELD_VALUE_REFUND or
    -- a RETURN_REVERSAL), then the other entries, oldest return first. Only uses made by
    -- corrections count (owner answer 2 to Q-2026-10-09-63).
    CREATE FUNCTION app.settlement_returned_value_walk(p_settlement uuid,p_kind text,
        p_source uuid,p_except uuid)
    RETURNS TABLE(walk_position integer,walk_kind text,walk_correction_id uuid,walk_entry_id uuid,
        walk_amount_usd_cents bigint,walk_offset_usd_cents bigint,walk_swept boolean)
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE
        v_ids uuid[]:='{}'; v_left bigint[]:='{}'; v_correction record; v_return bigint;
        v_paid bigint; v_back bigint; v_use bigint; v_take bigint; v_own bigint;
        v_offset bigint; v_named integer; v_index integer; v_position integer:=0;
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
            -- Paid out: applications, Refunds and reversed returns; for a Deposit also its
            -- receipt reversals and forfeitures (all whole records).
            v_paid:=COALESCE((SELECT sum(application.amount_usd_cents)
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
                      AND disposition.deposit_id=p_source),0);
            -- Brought back: reversed applications and Refunds recovered by a charge; for a
            -- Deposit also its receipts and forfeiture reversals.
            v_back:=COALESCE((SELECT sum(application.amount_usd_cents)
                    FROM app.settlement_correction_effects effect
                    JOIN app.customer_credit_application_reversals reversal
                        ON reversal.id=effect.credit_application_reversal_id
                    JOIN app.customer_credit_applications application
                        ON application.id=reversal.credit_application_id
                    WHERE effect.settlement_correction_id=v_correction.id AND p_kind='CREDIT'
                      AND application.customer_credit_id=p_source),0)
                +COALESCE((SELECT sum(application.amount_usd_cents)
                    FROM app.settlement_correction_effects effect
                    JOIN app.deposit_application_reversals reversal
                        ON reversal.id=effect.deposit_application_reversal_id
                    JOIN app.deposit_applications application
                        ON application.id=reversal.deposit_application_id
                    WHERE effect.settlement_correction_id=v_correction.id AND p_kind='DEPOSIT'
                      AND application.deposit_id=p_source),0)
                +COALESCE((SELECT sum(recovery.source_balance_effect_usd_cents)
                    FROM app.settlement_correction_effects effect
                    JOIN app.refund_corrections recovery
                        ON recovery.id=effect.refund_correction_id
                        AND recovery.correction_kind='RECOVERED_BY_CHARGE'
                    JOIN app.refunds origin ON origin.id=recovery.refund_id
                    WHERE effect.settlement_correction_id=v_correction.id
                      AND (p_kind='CREDIT' AND origin.source_customer_credit_id=p_source
                          OR p_kind='DEPOSIT' AND origin.source_deposit_id=p_source)),0)
                +COALESCE((SELECT sum(receipt.amount_usd_cents)
                    FROM app.settlement_correction_effects effect
                    JOIN app.deposit_receipts receipt ON receipt.id=effect.deposit_receipt_id
                    WHERE effect.settlement_correction_id=v_correction.id AND p_kind='DEPOSIT'
                      AND receipt.deposit_id=p_source),0)
                +COALESCE((SELECT sum(disposition.amount_usd_cents)
                    FROM app.settlement_correction_effects effect
                    JOIN app.deposit_disposition_reversals reversal
                        ON reversal.id=effect.deposit_disposition_reversal_id
                    JOIN app.deposit_dispositions disposition
                        ON disposition.id=reversal.deposit_disposition_id
                    WHERE effect.settlement_correction_id=v_correction.id AND p_kind='DEPOSIT'
                      AND disposition.deposit_id=p_source),0);
            v_use:=GREATEST(v_paid-v_back,0);
            -- A reversal of the Credit takes all the Credit still holds.
            IF p_kind='CREDIT' AND EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                JOIN app.customer_credit_reversals reversal
                    ON reversal.id=effect.customer_credit_reversal_id
                WHERE effect.settlement_correction_id=v_correction.id
                  AND reversal.customer_credit_id=p_source) THEN
                v_use:=v_return+(SELECT COALESCE(sum(remaining),0)::bigint
                    FROM unnest(v_left) AS remaining);
            END IF;
            IF v_return>0 THEN
                v_position:=v_position+1;
                RETURN QUERY SELECT v_position,'ENTRY'::text,v_correction.id,v_correction.id,
                    v_return,0::bigint,false;
            END IF;
            IF v_use>0 THEN
                v_position:=v_position+1;
                RETURN QUERY SELECT v_position,'DRAW'::text,v_correction.id,NULL::uuid,v_use,
                    v_back,false;
            END IF;
            -- Its own returned money first.
            v_offset:=0;
            v_take:=LEAST(v_use,v_return);
            IF v_take>0 THEN
                v_position:=v_position+1;
                RETURN QUERY SELECT v_position,'TAKE'::text,v_correction.id,v_correction.id,
                    v_take,v_offset,false;
            END IF;
            v_use:=v_use-v_take; v_offset:=v_offset+v_take; v_own:=v_return-v_take;
            -- Then the earlier correction it names.
            v_named:=array_position(v_ids::text[],v_correction.named);
            IF v_named IS NOT NULL THEN
                v_take:=LEAST(v_use,v_left[v_named]);
                IF v_take>0 THEN
                    v_position:=v_position+1;
                    RETURN QUERY SELECT v_position,'TAKE'::text,v_correction.id,v_ids[v_named],
                        v_take,v_offset,false;
                END IF;
                v_left[v_named]:=v_left[v_named]-v_take; v_use:=v_use-v_take;
                v_offset:=v_offset+v_take;
            END IF;
            -- Then the other returns, oldest first: money another correction paid out.
            v_index:=1;
            WHILE v_use>0 AND v_index<=cardinality(v_ids) LOOP
                v_take:=LEAST(v_use,v_left[v_index]);
                IF v_take>0 THEN
                    v_position:=v_position+1;
                    RETURN QUERY SELECT v_position,'TAKE'::text,v_correction.id,v_ids[v_index],
                        v_take,v_offset,true;
                END IF;
                v_left[v_index]:=v_left[v_index]-v_take; v_use:=v_use-v_take;
                v_offset:=v_offset+v_take; v_index:=v_index+1;
            END LOOP;
            IF v_return>0 THEN
                v_ids:=v_ids||v_correction.id; v_left:=v_left||v_own;
            END IF;
        END LOOP;
    END $$;

    -- Sub-slice 10e-3d-2a: each record of another correction S (neither p_earlier nor one naming
    -- it) that paid out part of p_earlier's returned money, read from the walk (owner answer (a)
    -- to Q-2026-10-13-100 point 1). S's take from p_earlier's entry sits in S's draw after what S
    -- brought back, which pays out first; S's payouts are its Refunds from the source, the oldest
    -- first, then its applications from it, the newest first (the owner answers to
    -- Q-2026-10-10-76 and Q-2026-10-12-95: a new Refund pays the returned money first). A
    -- record's part is its overlap with the take; the parts add up to the take. An S that also
    -- paid out through a reversal of the Credit, a reversed return, a Deposit receipt reversal or
    -- a forfeiture is not split: one row names the first such record and the whole take.
    CREATE FUNCTION app.settlement_returned_value_takes(p_settlement uuid,p_kind text,
        p_source uuid,p_earlier uuid)
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
            WHERE take.walk_kind='TAKE' AND take.walk_swept AND take.walk_entry_id=p_earlier
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

    -- Sub-slice 10e-3d-2a: the count of sub-slice 10e-3d-1, unchanged in its results, read from
    -- the walk: for each correction with a return into the source, what it returned, what the
    -- corrections used of it, the part that corrections which neither are it nor name it paid
    -- out (swept), and what is left.
    CREATE OR REPLACE FUNCTION app.settlement_returned_value_left(p_settlement uuid,p_kind text,
        p_source uuid,p_except uuid)
    RETURNS TABLE(settlement_correction_id uuid,returned_usd_cents bigint,used_usd_cents bigint,
        swept_usd_cents bigint,left_usd_cents bigint)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        WITH walked AS MATERIALIZED (
            SELECT walk.* FROM app.settlement_returned_value_walk(p_settlement,p_kind,p_source,
                p_except) walk
        ), taken AS (
            SELECT take.walk_entry_id AS entry_id,sum(take.walk_amount_usd_cents) AS used,
                COALESCE(sum(take.walk_amount_usd_cents) FILTER (WHERE take.walk_swept),0) AS swept
            FROM walked take WHERE take.walk_kind='TAKE' GROUP BY take.walk_entry_id
        )
        SELECT entry.walk_correction_id,entry.walk_amount_usd_cents,
            COALESCE(taken.used,0)::bigint,COALESCE(taken.swept,0)::bigint,
            (entry.walk_amount_usd_cents-COALESCE(taken.used,0))::bigint
        FROM walked entry LEFT JOIN taken ON taken.entry_id=entry.walk_correction_id
        WHERE entry.walk_kind='ENTRY'
        ORDER BY entry.walk_position
    $$;
"""

INTERNAL = (
    "app.settlement_returned_value_walk(uuid,text,uuid,uuid)",
    "app.settlement_returned_value_takes(uuid,text,uuid,uuid)",
)
REPLACED = "app.settlement_returned_value_left(uuid,text,uuid,uuid)"

SOURCE = "app.settlement_return_reversal_source_state(uuid,uuid)"
SOURCE_REPLACEMENTS = (
    (
        """               OR refund.source_deposit_id=earlier.deposit_id
        -- Sub-slice 10e-3b (owner answer (a) to Q-2026-10-12-95): the totals of the uses. When
""",
        """               OR refund.source_deposit_id=earlier.deposit_id
        -- Sub-slice 10e-3d-2a (owner answer (a) to Q-2026-10-13-100 point 1): the earlier
        -- correction's count, and each record of another correction that paid out part of its
        -- returned money (app.settlement_returned_value_takes). A Refund part is charged back to
        -- the person who received that Refund (a share, as sub-slice 10e-3b); an application
        -- part reverses the application whole and applies the rest again (as sub-slice 10e-3c).
        -- A part this reversal cannot undo yet is open, with its kind: a payment a later
        -- correction changed (an application reversed since, or a Refund part more than the
        -- Refund's net), or the take of a correction that also reversed the Credit, a return or
        -- a receipt, or forfeited.
        ), counted_entry AS (
            SELECT counted.* FROM earlier
            CROSS JOIN LATERAL app.settlement_returned_value_left(p_settlement,
                CASE WHEN earlier.deposit_id IS NOT NULL THEN 'DEPOSIT' ELSE 'CREDIT' END,
                COALESCE(earlier.deposit_id,earlier.credit_id),NULL) counted
            WHERE counted.settlement_correction_id=earlier.id
        ), swept_state AS (
            SELECT taken.*,CASE
                    WHEN taken.record_kind NOT IN ('REFUND','CREDIT_APPLICATION','DEPOSIT_APPLICATION')
                        THEN taken.record_kind
                    WHEN taken.record_kind='CREDIT_APPLICATION' AND EXISTS(SELECT 1
                        FROM app.customer_credit_application_reversals reversal
                        WHERE reversal.credit_application_id=taken.record_id)
                        THEN 'CHANGED_APPLICATION'
                    WHEN taken.record_kind='DEPOSIT_APPLICATION' AND EXISTS(SELECT 1
                        FROM app.deposit_application_reversals reversal
                        WHERE reversal.deposit_application_id=taken.record_id)
                        THEN 'CHANGED_APPLICATION'
                    WHEN taken.record_kind='REFUND' AND NOT COALESCE(taken.part_usd_cents
                        <=app.refund_net_value_at(taken.record_id,'infinity'),false)
                        THEN 'CHANGED_REFUND' END AS open_kind
            FROM earlier
            CROSS JOIN LATERAL app.settlement_returned_value_takes(p_settlement,
                CASE WHEN earlier.deposit_id IS NOT NULL THEN 'DEPOSIT' ELSE 'CREDIT' END,
                COALESCE(earlier.deposit_id,earlier.credit_id),earlier.id) taken
        ), swept_undone AS (
            SELECT swept_state.* FROM swept_state WHERE swept_state.open_kind IS NULL
        ), swept_paid AS (
            -- The recovery entry of a Refund part, as the own uses' entries below.
            SELECT refund.*,app.refund_net_value_at(refund.id,'infinity') AS net,
                CASE WHEN refund.source_deposit_id IS NULL THEN 'CREDIT' ELSE 'DEPOSIT' END AS source_kind,
                COALESCE(refund.source_deposit_id,refund.source_customer_credit_id) AS source_id,
                CASE WHEN EXISTS(SELECT 1 FROM app.lease_signers signer
                    WHERE signer.lease_id=(SELECT settlement.lease_id FROM settlement)
                      AND signer.customer_id=refund.recipient_customer_id
                      AND signer.signed_at IS NOT NULL)
                    THEN (SELECT settlement.lease_id FROM settlement) END AS lease_id,
                refund.source_deposit_id IS NULL OR refund.recipient_customer_id=(SELECT deposit.customer_id
                    FROM app.deposits deposit WHERE deposit.id=refund.source_deposit_id) AS deposit_customer,
                (SELECT count(*) FROM app.refund_corrections returned
                    WHERE returned.refund_id=refund.id AND returned.correction_kind='VALUE_CORRECTION'
                      AND NOT EXISTS(SELECT 1 FROM app.refund_corrections reversal
                          WHERE reversal.reverses_correction_id=returned.id)) AS returns,
                taken.part_usd_cents AS share
            FROM swept_undone taken JOIN app.refunds refund ON refund.id=taken.record_id
            WHERE taken.record_kind='REFUND'
        -- Sub-slice 10e-3b (owner answer (a) to Q-2026-10-12-95): the totals of the uses. When
""",
    ),
    (
        """            SELECT (SELECT earlier.amount FROM earlier) AS returned,
""",
        """            -- Sub-slice 10e-3d-2a: the part of the returned money the own uses used (the
            -- earlier correction's used less the part other corrections paid out).
            SELECT (SELECT counted_entry.used_usd_cents-counted_entry.swept_usd_cents
                FROM counted_entry) AS returned,
""",
    ),
    (
        """                FROM credit_applications application
                -- Sub-slice 10e-3b: the Refunds took the whole returned amount.
                WHERE NOT (SELECT covered.refunds_only FROM covered)
                  -- Sub-slice 10e-3c: the newest, up to the rest the debt took.
                  AND application.id IN (SELECT undone.id FROM undone)),""",
        """                FROM (SELECT own_use.* FROM credit_applications own_use
                    -- Sub-slice 10e-3b: the Refunds took the whole returned amount.
                    WHERE NOT (SELECT covered.refunds_only FROM covered)
                      -- Sub-slice 10e-3c: the newest, up to the rest the debt took.
                      AND own_use.id IN (SELECT undone.id FROM undone)
                    -- Sub-slice 10e-3d-2a: and each application of another correction that paid
                    -- out part of the returned money, reversed whole.
                    UNION ALL
                    SELECT swept_use.* FROM app.customer_credit_applications swept_use
                    WHERE swept_use.id IN (SELECT taken.record_id FROM swept_undone taken
                        WHERE taken.record_kind='CREDIT_APPLICATION')) application),""",
    ),
    (
        """                FROM deposit_applications application
                WHERE NOT (SELECT covered.refunds_only FROM covered)
                  AND application.id IN (SELECT undone.id FROM undone)),""",
        """                FROM (SELECT own_use.* FROM deposit_applications own_use
                    WHERE NOT (SELECT covered.refunds_only FROM covered)
                      AND own_use.id IN (SELECT undone.id FROM undone)
                    -- Sub-slice 10e-3d-2a: and each application of another correction that paid
                    -- out part of the returned money, reversed whole.
                    UNION ALL
                    SELECT swept_use.* FROM app.deposit_applications swept_use
                    WHERE swept_use.id IN (SELECT taken.record_id FROM swept_undone taken
                        WHERE taken.record_kind='DEPOSIT_APPLICATION')) application),""",
    ),
    (
        """                    'amount_usd_cents',shares.amount,'net_usd_cents',paid.net,""",
        """                    'amount_usd_cents',paid.share,'net_usd_cents',paid.net,""",
    ),
    (
        """                FROM paid JOIN shares ON shares.id=paid.id WHERE shares.amount>0),""",
        """                FROM (SELECT own_paid.*,shares.amount AS share FROM paid own_paid
                    JOIN shares ON shares.id=own_paid.id WHERE shares.amount>0
                    -- Sub-slice 10e-3d-2a: and each Refund part of another correction.
                    UNION ALL
                    SELECT swept_paid.* FROM swept_paid) paid),""",
    ),
    (
        """            WHERE partial.debt_paid AND undone.before_it+undone.amount_usd_cents>partial.rest
        )
        SELECT jsonb_build_object(""",
        """            WHERE partial.debt_paid AND undone.before_it+undone.amount_usd_cents>partial.rest
            -- Sub-slice 10e-3d-2a: the part of each application of another correction that was
            -- not the returned money, applied again.
            UNION ALL
            SELECT CASE taken.record_kind WHEN 'CREDIT_APPLICATION' THEN 'CREDIT' ELSE 'DEPOSIT' END,
                taken.record_id,taken.amount_usd_cents,
                (taken.amount_usd_cents-taken.part_usd_cents)::bigint
            FROM swept_undone taken
            WHERE taken.record_kind IN ('CREDIT_APPLICATION','DEPOSIT_APPLICATION')
              AND taken.part_usd_cents<taken.amount_usd_cents
        )
        SELECT jsonb_build_object(""",
    ),
    (
        """                WHERE counted.settlement_correction_id=earlier.id))
""",
        """                WHERE counted.settlement_correction_id=earlier.id),
            -- Sub-slice 10e-3d-2a: the parts of the returned money that other corrections paid
            -- out and this reversal undoes, their total, and the parts it cannot undo yet.
            'swept',(SELECT COALESCE(jsonb_agg(jsonb_build_object(
                    'settlement_correction_id',taken.settlement_correction_id,
                    'record_kind',taken.record_kind,'record_id',taken.record_id,
                    'amount_usd_cents',taken.amount_usd_cents,'part_usd_cents',taken.part_usd_cents)
                    ORDER BY taken.settlement_correction_id,taken.record_id),'[]'::jsonb)
                FROM swept_undone taken),
            'swept_undone_usd_cents',(SELECT COALESCE(sum(taken.part_usd_cents),0)
                FROM swept_undone taken),
            'swept_open',(SELECT COALESCE(jsonb_agg(jsonb_build_object(
                    'settlement_correction_id',taken.settlement_correction_id,
                    'kind',taken.open_kind,'record_kind',taken.record_kind,
                    'record_id',taken.record_id,'part_usd_cents',taken.part_usd_cents)
                    ORDER BY taken.settlement_correction_id,taken.record_id),'[]'::jsonb)
                FROM swept_state taken WHERE taken.open_kind IS NOT NULL),
            -- Review round 1: two or more own corrections paid out from the source and one of
            -- them also took another return's money.
            'shared_with_other_returns',(SELECT shared_own.mixed FROM shared_own))
""",
    ),
    (
        """            -- Sub-slice 10e-3c: the part applied again (at most one entry): the reversed""",
        """            -- Sub-slice 10e-3c: the part applied again (at most one entry of the own uses;
            -- since sub-slice 10e-3d-2a also one per application of another correction): the reversed""",
    ),
    (
        """                    ORDER BY restored.id,detail.id),'[]'::jsonb)""",
        """                    -- Sub-slice 10e-3d-2a (review round 1): in the DL-032 stage order, then
                    -- in the order the applications were first written, so the confirm writes
                    -- them as the Deposit application check and the Rent-first proposal expect.
                    ORDER BY CASE deposit_use.application_stage WHEN 'PET_RELATED_FIRST' THEN 1
                            WHEN 'SECURITY_EXPLICIT' THEN 2 WHEN 'PET_REMAINDER_EXPLICIT' THEN 3
                            ELSE 0 END,
                        COALESCE(credit_use.occurred_at,deposit_use.occurred_at),
                        deposit_use.application_order,restored.id,detail.id),'[]'::jsonb)""",
    ),
    (
        """        ), swept_undone AS (
            SELECT swept_state.* FROM swept_state WHERE swept_state.open_kind IS NULL""",
        """        -- Review round 1: the own uses are undone with all their Refunds first and then their
        -- applications, the newest first, over every own correction; the walk takes them per
        -- correction in time order. The two agree unless two or more own corrections paid out
        -- from the source and one of them also took another return's money; that case waits for
        -- sub-slice 10e-3d-2b (it then derives the own uses' parts from the walk too).
        ), shared_own AS (
            SELECT EXISTS(SELECT 1 FROM earlier
                    CROSS JOIN LATERAL app.settlement_returned_value_walk(p_settlement,
                        CASE WHEN earlier.deposit_id IS NOT NULL THEN 'DEPOSIT' ELSE 'CREDIT' END,
                        COALESCE(earlier.deposit_id,earlier.credit_id),NULL) walk
                    WHERE walk.walk_kind='TAKE' AND walk.walk_swept
                      AND walk.walk_correction_id IN (SELECT users.id FROM users))
                AND (SELECT count(DISTINCT effect.settlement_correction_id)
                    FROM app.settlement_correction_effects effect
                    WHERE effect.settlement_correction_id IN (SELECT users.id FROM users)
                      AND (effect.customer_credit_application_id IN (SELECT credit_use.id
                              FROM credit_applications credit_use)
                          OR effect.deposit_application_id IN (SELECT deposit_use.id
                              FROM deposit_applications deposit_use)
                          OR effect.refund_id IN (SELECT refund_use.id FROM paid refund_use
                              WHERE refund_use.net>0)))>=2 AS mixed
        ), swept_undone AS (
            SELECT swept_state.* FROM swept_state WHERE swept_state.open_kind IS NULL""",
    ),
)

ASSERT = "app.assert_settlement_return_reversal_allowed(jsonb)"
ASSERT_REPLACEMENTS = (
    (
        """AS $function$
    BEGIN
""",
        """AS $function$
    DECLARE v_own bigint;
    BEGIN
""",
    ),
    (
        """        IF jsonb_typeof(p_source->'uses') IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'The return reversal source is incomplete' USING ERRCODE='55000'; END IF;
""",
        """        IF jsonb_typeof(p_source->'uses') IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'The return reversal source is incomplete' USING ERRCODE='55000'; END IF;
        -- Sub-slice 10e-3d-2a (owner answer (a) to Q-2026-10-13-100 point 1): the earlier
        -- correction's count and the parts of its money other corrections paid out, before every
        -- check that reads them. Fail closed: every key is there and of its type, each part is
        -- above 0, and the money other corrections paid out is exactly the parts this reversal
        -- undoes and the parts it cannot undo yet.
        IF jsonb_typeof(p_source->'swept_usd_cents') IS DISTINCT FROM 'number'
            OR jsonb_typeof(p_source->'left_usd_cents') IS DISTINCT FROM 'number'
            OR jsonb_typeof(p_source->'swept_undone_usd_cents') IS DISTINCT FROM 'number'
            OR jsonb_typeof(p_source->'swept') IS DISTINCT FROM 'array'
            OR jsonb_typeof(p_source->'swept_open') IS DISTINCT FROM 'array'
            -- Review round 2: the flag of own corrections that also took another return's money
            -- is there as true or false too.
            OR jsonb_typeof(p_source->'shared_with_other_returns') IS DISTINCT FROM 'boolean'
        THEN RAISE EXCEPTION 'The return reversal source is incomplete' USING ERRCODE='55000'; END IF;
        IF (p_source->>'swept_usd_cents')::bigint
                <>(p_source->>'swept_undone_usd_cents')::bigint
                    +(SELECT COALESCE(sum((item->>'part_usd_cents')::bigint),0)
                        FROM jsonb_array_elements(p_source->'swept_open') item)
            OR (p_source->>'swept_undone_usd_cents')::bigint
                <>(SELECT COALESCE(sum((item->>'part_usd_cents')::bigint),0)
                    FROM jsonb_array_elements(p_source->'swept') item)
            OR EXISTS(SELECT 1 FROM jsonb_array_elements((p_source->'swept')||(p_source->'swept_open')) item
                WHERE NOT COALESCE((item->>'part_usd_cents')::bigint>0,false))
        THEN RAISE EXCEPTION 'The return reversal source is incomplete' USING ERRCODE='55000'; END IF;
        -- What this reversal cannot undo yet, each with its own message: a payment a later
        -- correction changed (sub-slice 10e-3d-2b); a Credit reversal or a Deposit receipt
        -- reversal (sub-slice 10e-3d-2c, owner answer (a) to Q-2026-10-13-103 point 1); a
        -- forfeiture (owner answer (a) to point 2: refused, sub-slice 10e-2d should make it
        -- unreachable); anything else (a reversed return, a Refund part more than its net).
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'swept_open') item
            WHERE item->>'kind'='CHANGED_APPLICATION')
        THEN RAISE EXCEPTION 'A later correction changed a payment made with this return''s money; reversing it waits for sub-slice 10e-3d-2b'
            USING ERRCODE='55000'; END IF;
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'swept_open') item
            WHERE item->>'kind' IN ('CREDIT_REVERSAL','RECEIPT_REVERSAL'))
        THEN RAISE EXCEPTION 'A Credit reversal or a Deposit receipt reversal paid out this return''s money; reversing it waits for sub-slice 10e-3d-2c'
            USING ERRCODE='55000'; END IF;
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'swept_open') item
            WHERE item->>'kind'='FORFEITURE')
        THEN RAISE EXCEPTION 'A forfeiture kept this return''s money; the return cannot be reversed'
            USING ERRCODE='55000'; END IF;
        IF jsonb_array_length(p_source->'swept_open')>0 THEN
            RAISE EXCEPTION 'The returned value is no longer available; undo its other use first'
                USING ERRCODE='55000'; END IF;
        -- Review round 1: two or more own corrections paid out from the source and one of them
        -- also took another return's money (the source's flag), so the own uses' parts may not
        -- be this return's money; that case waits for sub-slice 10e-3d-2b.
        IF (p_source->>'shared_with_other_returns')::boolean THEN
            RAISE EXCEPTION 'This return''s own corrections also paid out another return''s money; reversing it waits for sub-slice 10e-3d-2b'
                USING ERRCODE='55000'; END IF;
        -- Each part this reversal undoes is listed exactly: a Refund part as the recovery of
        -- exactly that part, no more than the Refund's net; an application part as a listed
        -- application of its amount, reversed whole, with the rest of it, if any, applied again
        -- as exactly one entry.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'swept') taken
            WHERE NOT COALESCE(CASE taken->>'record_kind'
                WHEN 'REFUND' THEN (SELECT count(*)=1
                        AND bool_and((recovery->>'amount_usd_cents')::bigint
                                =(taken->>'part_usd_cents')::bigint
                            AND (recovery->>'amount_usd_cents')::bigint
                                <=(recovery->>'net_usd_cents')::bigint)
                    FROM jsonb_array_elements(p_source->'recoveries') recovery
                    WHERE recovery->>'refund_id'=taken->>'record_id')
                WHEN 'CREDIT_APPLICATION' THEN (SELECT count(*)=1
                        AND bool_and((application->>'amount_usd_cents')::bigint
                            =(taken->>'amount_usd_cents')::bigint)
                    FROM jsonb_array_elements(p_source->'credit_applications') application
                    WHERE application->>'id'=taken->>'record_id')
                WHEN 'DEPOSIT_APPLICATION' THEN (SELECT count(*)=1
                        AND bool_and((application->>'amount_usd_cents')::bigint
                            =(taken->>'amount_usd_cents')::bigint)
                    FROM jsonb_array_elements(p_source->'deposit_applications') application
                    WHERE application->>'id'=taken->>'record_id') END
                AND (taken->>'record_kind'='REFUND'
                    OR (taken->>'part_usd_cents')::bigint<=(taken->>'amount_usd_cents')::bigint
                        AND (SELECT COALESCE(array_agg((item->>'amount_usd_cents')::bigint),'{}')
                            FROM jsonb_array_elements(CASE WHEN jsonb_typeof(p_source->'reapply')='array'
                                THEN p_source->'reapply' ELSE '[]'::jsonb END) item
                            WHERE item->>'application_id'=taken->>'record_id')
                            =CASE WHEN (taken->>'part_usd_cents')::bigint<(taken->>'amount_usd_cents')::bigint
                                THEN ARRAY[(taken->>'amount_usd_cents')::bigint-(taken->>'part_usd_cents')::bigint]
                                ELSE '{}'::bigint[] END),false))
        THEN RAISE EXCEPTION 'The return reversal source is incomplete' USING ERRCODE='55000'; END IF;
        -- The part of the returned money the own uses used: the returned amount less what is
        -- left and less what other corrections paid out (their parts are undone above).
        v_own:=(p_source->'earlier'->>'amount_usd_cents')::bigint
            -(p_source->>'left_usd_cents')::bigint-(p_source->>'swept_usd_cents')::bigint;
""",
    ),
    (
        """                >(p_source->'earlier'->>'amount_usd_cents')::bigint
            AND (p_source->'uses'->>'returned_refunds')::bigint>0,true)""",
        """                -- Sub-slice 10e-3d-2a: against the part of the returned money the own uses used.
                >v_own
            AND (p_source->'uses'->>'returned_refunds')::bigint>0,true)""",
    ),
    (
        """            OR (CASE WHEN jsonb_typeof(p_source->'reapply')='array'
                THEN jsonb_array_length(p_source->'reapply')>1
                    OR (jsonb_array_length(p_source->'reapply')>0
                        AND NOT COALESCE((p_source->'uses'->>'applied_usd_cents')::bigint
                            +(p_source->'uses'->>'refunded_usd_cents')::bigint
                            >(p_source->'earlier'->>'amount_usd_cents')::bigint
                            AND (p_source->'uses'->>'refunded_usd_cents')::bigint
                                <(p_source->'earlier'->>'amount_usd_cents')::bigint,false))
                ELSE true END)""",
        """            -- Sub-slice 10e-3d-2a: at most one entry per application; of the own uses'
            -- applications at most one, and only when their Refunds paid out less than the part
            -- of the returned money the own uses used (the entries of other corrections'
            -- applications are checked above).
            OR (CASE WHEN jsonb_typeof(p_source->'reapply')='array'
                THEN (SELECT count(DISTINCT item->>'application_id')
                        FROM jsonb_array_elements(p_source->'reapply') item)
                        <>jsonb_array_length(p_source->'reapply')
                    OR (SELECT count(*) FROM jsonb_array_elements(p_source->'reapply') item
                        WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'swept') taken
                            WHERE taken->>'record_id'=item->>'application_id'))>1
                    OR ((SELECT count(*) FROM jsonb_array_elements(p_source->'reapply') item
                            WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'swept') taken
                                WHERE taken->>'record_id'=item->>'application_id'))>0
                        AND NOT COALESCE((p_source->'uses'->>'applied_usd_cents')::bigint
                            +(p_source->'uses'->>'refunded_usd_cents')::bigint>v_own
                            AND (p_source->'uses'->>'refunded_usd_cents')::bigint<v_own,false))
                ELSE true END)""",
    ),
    (
        """        IF NOT COALESCE((SELECT back.amount<=returned.amount
""",
        """        -- Sub-slice 10e-3d-2a (review round 1): a Credit part applied again without a
        -- Customer designation on an Invoice with Rent or Service lines follows the Rent-first
        -- proposal, which pays the line of the oldest reversed application of that Invoice
        -- first; a part on a newer one would be refused at the confirm, so it is refused here
        -- and waits for the owner (Q-2026-10-13-104). The listed applications are newest first.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'reapply') item
            JOIN jsonb_array_elements(p_source->'credit_applications')
                WITH ORDINALITY reapplied(application,position)
                ON reapplied.application->>'id'=item->>'application_id'
            WHERE item->>'source_kind'='CREDIT' AND item->>'target_kind'='INVOICE_LINE'
              AND jsonb_typeof(item->'customer_designation') IS DISTINCT FROM 'string'
              AND EXISTS(SELECT 1 FROM app.invoice_lines line
                  WHERE line.invoice_id::text=reapplied.application->>'invoice_id'
                    AND line.category IN ('RENT','SERVICE_CHARGES'))
              AND EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'credit_applications')
                      WITH ORDINALITY older(application,position)
                  WHERE older.application->>'invoice_id'=reapplied.application->>'invoice_id'
                    AND older.position>reapplied.position))
        THEN RAISE EXCEPTION 'A part applied again on an Invoice with Rent or Service lines would not follow the Rent-first order; reversing this return waits for the owner'
            USING ERRCODE='55000'; END IF;
        IF NOT COALESCE((SELECT back.amount<=returned.amount
""",
    ),
    (
        """                        FROM jsonb_array_elements(p_source->'recoveries') recovery) AS amount,""",
        """                        FROM jsonb_array_elements(p_source->'recoveries') recovery)
                    -- Sub-slice 10e-3d-2a: less the parts of other corrections' records (checked
                    -- above), so the own uses bring back the part of the returned money they used.
                    -(p_source->>'swept_undone_usd_cents')::bigint AS amount,""",
    ),
    (
        """            CROSS JOIN (SELECT (p_source->'earlier'->>'amount_usd_cents')::bigint AS amount) returned),false)""",
        """            CROSS JOIN (SELECT v_own AS amount) returned),false)""",
    ),
    (
        """        -- correction paid out is not undone here; that waits for the owner (Q-2026-10-13-100).
        -- A missing part is refused too.
        IF jsonb_typeof(p_source->'swept_usd_cents') IS DISTINCT FROM 'number' THEN
            RAISE EXCEPTION 'The return reversal source is incomplete' USING ERRCODE='55000'; END IF;
        IF (p_source->>'swept_usd_cents')::bigint<>0 THEN
            RAISE EXCEPTION 'Another correction paid out this return''s money; reversing it waits for the owner'
                USING ERRCODE='55000'; END IF;
""",
        """        -- correction paid out is undone with it since sub-slice 10e-3d-2a (owner answer (a) to
        -- Q-2026-10-13-100 point 1; its parts are checked above).
""",
    ),
)

SCOPE = "app.settlement_return_reversal_refund(uuid,uuid)"
SCOPE_REPLACEMENTS = (
    (
        """                  AND effect.settlement_correction_id=ANY(app.settlement_return_reversal_users(
                      app.final_settlement_plan_id(draft.payload->'held_from_settlement_correction_id')::uuid))
""",
        """                  AND (effect.settlement_correction_id=ANY(app.settlement_return_reversal_users(
                      app.final_settlement_plan_id(draft.payload->'held_from_settlement_correction_id')::uuid))
                      -- Sub-slice 10e-3d-2a: or a Refund of another correction of the same
                      -- Settlement that the draft's source names as a part of the returned money
                      -- it paid out.
                      OR EXISTS(SELECT 1 FROM jsonb_array_elements(draft.payload->'source'->'swept') taken
                          JOIN app.settlement_corrections other
                              ON other.id::text=taken->>'settlement_correction_id'
                          WHERE taken->>'record_kind'='REFUND' AND taken->>'record_id'=p_refund::text
                            AND other.id=effect.settlement_correction_id
                            AND other.final_settlement_id::text=draft.payload->>'final_settlement_id'))
""",
    ),
)

CONFIRM = "app.confirm_settlement_return_reversal(uuid,uuid,uuid,text)"
CONFIRM_REPLACEMENTS = (
    (
        """            -- Sub-slice 10e-3c: the stored plan is the one-step plan of the part applied again,""",
        """            -- Sub-slice 10e-3c: the stored plan is the plan of the parts applied again (one
            -- step each since sub-slice 10e-3d-2a),""",
    ),
    (
        """        -- Sub-slice 10e-3c (owner answer (a) to Q-2026-10-12-96): the part of the last reversed
        -- application that was not returned money is applied again to the same obligation from""",
        """        -- Sub-slice 10e-3c (owner answer (a) to Q-2026-10-12-96): the part of the last reversed
        -- application that was not returned money (since sub-slice 10e-3d-2a also the part of
        -- each application of another correction) is applied again to the same obligation from""",
    ),
    (
        """        v_reapply jsonb; v_reapplied uuid; v_order integer;
""",
        """        v_reapply jsonb; v_reapplied uuid; v_order integer; v_step integer;
""",
    ),
    (
        """        v_reapply:=v_source->'reapply'->0;
        IF v_reapply->>'source_kind'='CREDIT' THEN
            v_at:=GREATEST(v_at,(app.post_final_settlement_credit_application(p_property,p_actor,
                v_settlement.id,p_draft,1)->>'occurred_at')::timestamptz);
        ELSIF v_reapply->>'source_kind'='DEPOSIT' THEN
            SELECT COALESCE(max(application.application_order),0)+1 INTO v_order
            FROM app.deposit_applications application
            WHERE application.final_settlement_id=v_settlement.id;
            v_reapplied:=gen_random_uuid();
            PERFORM app.link_settlement_correction_effect(v_correction,'deposit_application_id',v_reapplied);
            v_at:=GREATEST(v_at,(app.post_deposit_application(p_property,p_actor,v_settlement.id,
                v_reapplied,(v_reapply->>'deposit_id')::uuid,v_reapply->>'application_stage',
                v_reapply->>'target_kind',(v_reapply->>'target_id')::uuid,
                (v_reapply->>'amount_usd_cents')::bigint,v_order,v_draft.reason)->>'occurred_at')::timestamptz);
        END IF;
""",
        """        -- Sub-slice 10e-3d-2a: every part applied again, in the source's order; the n-th entry
        -- is the n-th step of the draft's plan.
        FOR v_reapply,v_step IN SELECT entry.item,entry.position::integer
            FROM jsonb_array_elements(v_source->'reapply') WITH ORDINALITY entry(item,position)
            ORDER BY entry.position
        LOOP
        IF v_reapply->>'source_kind'='CREDIT' THEN
            v_at:=GREATEST(v_at,(app.post_final_settlement_credit_application(p_property,p_actor,
                v_settlement.id,p_draft,v_step)->>'occurred_at')::timestamptz);
        ELSIF v_reapply->>'source_kind'='DEPOSIT' THEN
            SELECT COALESCE(max(application.application_order),0)+1 INTO v_order
            FROM app.deposit_applications application
            WHERE application.final_settlement_id=v_settlement.id;
            v_reapplied:=gen_random_uuid();
            PERFORM app.link_settlement_correction_effect(v_correction,'deposit_application_id',v_reapplied);
            v_at:=GREATEST(v_at,(app.post_deposit_application(p_property,p_actor,v_settlement.id,
                v_reapplied,(v_reapply->>'deposit_id')::uuid,v_reapply->>'application_stage',
                v_reapply->>'target_kind',(v_reapply->>'target_id')::uuid,
                (v_reapply->>'amount_usd_cents')::bigint,v_order,v_draft.reason)->>'occurred_at')::timestamptz);
        -- Review round 2: any other source kind is refused, so nothing is skipped silently.
        ELSE
            RAISE EXCEPTION 'The return reversal source is incomplete' USING ERRCODE='55000';
        END IF;
        END LOOP;
""",
    ),
)

PATCHES = (
    (SOURCE, SOURCE_REPLACEMENTS),
    (ASSERT, ASSERT_REPLACEMENTS),
    (SCOPE, SCOPE_REPLACEMENTS),
    (CONFIRM, CONFIRM_REPLACEMENTS),
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
            raise RuntimeError(f"Settlement return reversal swept contract changed: {signature}")
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
    raise RuntimeError("Settlement return reversal swept migration is forward-only")
