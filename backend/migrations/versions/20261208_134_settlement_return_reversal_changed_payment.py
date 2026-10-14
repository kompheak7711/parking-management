# ruff: noqa: E501
"""A return's money on a payment a later Refund correction or pet-damage reclassification changed
(V1-056 sub-slice 10e-3d-2b-2).

BR-SETTLE-008, BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-014, DL-032; DB-SETTLE-005; owner answer
(a) to Q-2026-10-13-107 (the money a changing correction took back out of a payment pays out first
on its Refunds, the oldest first, then on its payments, the newest first, and the mistaken money
keeps its place in that stream) and the owner's acceptance (2026-10-14) of the design reading that
a return reversal's put-back keeps each part's place, with the reversed return's money cut out:

- New internal `app.settlement_returned_value_placed(p_settlement, p_kind, p_source, p_earlier,
  p_swept)`: the rows of `app.settlement_returned_value_parts` with each part's offset in its
  record (0 for the open takes of a correction that also reversed the Credit, a return or a
  receipt, or forfeited). `app.settlement_returned_value_parts` becomes a call to it without the
  offset (same signature, settings and privileges), so the two cannot disagree.
- New internal `app.settlement_returned_value_follow(p_settlement, p_kind, p_source, p_record_kind,
  p_record, p_offset, p_part, p_until)`: the records that hold a stretch of a payment's money now.
  An active payment holds it itself (open when the stretch is not inside it). A payment a
  `RETURN_REVERSAL` R reversed and put back (the n-th entry of R's stored `reapply` is R's n-th
  linked payment, with the checks of `app.settlement_returned_value_successor`) passes the stretch
  to the put-back, its offset less the stretches of R's reversed return that lie before it; those
  stretches are R's reversed return's placed parts followed up to the payments R reversed
  (`p_until` R), they must add up to the payment less the put-back and must not overlap the
  stretch. A payment a `REFUND`
  correction or `PET_DAMAGE_RECLASSIFICATION` Q of the same Settlement reversed is laid over Q's
  stream: Q's reversals of payments from the source, in the order Q wrote them, are the money Q
  took back; Q's Refunds from the source (the oldest first), then its payments from it (the newest
  first), pay it out in that order; each Q Refund the stretch overlaps holds that part, each Q
  payment is followed again (at most 100 steps). Anything else stops open (`CHANGED_APPLICATION`)
  at the record where it stops: an unknown record, offset or part; a stretch not inside its
  payment; with `p_until`, a change by a correction not strictly earlier than `p_until` (so the
  recursion ends; review round 1); a reversal by no correction,
  by another Settlement's correction or by another correction kind; a put-back that does not check
  or whose reversed return's stretches do not add up; Q also brought back money from the source
  other than by reversing payments, also reversed the Credit, a return or a receipt, or forfeited;
  or the stretch reaches past what Q paid out.
- `app.settlement_return_reversal_source_state` (exact-text patch; the sub-slice 10e-3d-2b-1a and
  10e-3d-2b-1b `swept_state` replaced whole): the swept and own takes come from the placed function
  with their offsets, each payment part goes through the follow function, and the rows are summed
  per own flag, correction and record; a Refund part more than the Refund's net now is open
  (`CHANGED_REFUND`), as before.
- `app.settlement_return_reversal_refund` (exact-text patch, relaxing): a Refund the source names
  as an own use's part (a changing correction's Refund that now holds it) is in the reversal's
  recovery scope, as a Refund the source names as another correction's part.
- `app.assert_settlement_return_reversal_allowed` (exact-text patch): the message of a part that
  cannot be followed becomes "A later correction changed a payment made with this return's money
  in a way this reversal cannot follow yet; reversing it waits for the owner".

No writer, lock or grant changes. A `RETURN_REVERSAL` draft recorded before this migration whose
source now differs is stale at its confirm (P5S02); staff reject it and record it again.
"""

from alembic import op
from sqlalchemy import text

revision = "20261208_134"
down_revision = "20261207_133"
branch_labels = None
depends_on = None

FUNCTION_SQL = r"""
    -- Sub-slice 10e-3d-2b-2: the parts of app.settlement_returned_value_parts with each part's
    -- offset in its record (0 for an open take of a correction that also reversed the Credit, a
    -- return or a receipt, or forfeited).
    CREATE FUNCTION app.settlement_returned_value_placed(p_settlement uuid,p_kind text,
            p_source uuid,p_earlier uuid,p_swept boolean)
        RETURNS TABLE(settlement_correction_id uuid,record_kind text,record_id uuid,
            amount_usd_cents bigint,part_usd_cents bigint,offset_usd_cents bigint)
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
                -GREATEST(placed.before_it,taken.start_at))::bigint,
            (GREATEST(placed.before_it,taken.start_at)-placed.before_it)::bigint
        FROM placed JOIN taken ON taken.taker=placed.taker
        WHERE placed.before_it+placed.amount>taken.start_at
          AND placed.before_it<taken.start_at+taken.amount
        UNION ALL
        SELECT opened.taker,opened.kind,opened.id,taken.amount,taken.amount,0::bigint
        FROM opened JOIN taken ON taken.taker=opened.taker
    $$;

    -- The sub-slice 10e-3d-2b-1b parts, from the placed function (same rows without the offset).
    CREATE OR REPLACE FUNCTION app.settlement_returned_value_parts(p_settlement uuid,p_kind text,
            p_source uuid,p_earlier uuid,p_swept boolean)
        RETURNS TABLE(settlement_correction_id uuid,record_kind text,record_id uuid,
            amount_usd_cents bigint,part_usd_cents bigint)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT placed.settlement_correction_id,placed.record_kind,placed.record_id,
            placed.amount_usd_cents,placed.part_usd_cents
        FROM app.settlement_returned_value_placed(p_settlement,p_kind,p_source,p_earlier,
            p_swept) placed
    $$;

    -- Sub-slice 10e-3d-2b-2 (owner answer (a) to Q-2026-10-13-107): the records that hold a
    -- stretch of a payment's money now (p_offset into p_record, p_part long). With p_until (a
    -- return reversal), a stretch stops at a payment that correction reversed: where its reversed
    -- return's own stretches were just before it (each step back reads only earlier corrections).
    CREATE FUNCTION app.settlement_returned_value_follow(p_settlement uuid,p_kind text,
            p_source uuid,p_record_kind text,p_record uuid,p_offset bigint,p_part bigint,
            p_until uuid DEFAULT NULL)
        RETURNS TABLE(follow_correction_id uuid,follow_record_kind text,follow_record_id uuid,
            follow_amount_usd_cents bigint,follow_offset_usd_cents bigint,
            follow_part_usd_cents bigint,follow_open_kind text)
        LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE
        v_queue jsonb; v_item jsonb; v_steps integer:=0; v_kind text; v_record uuid;
        v_offset bigint; v_part bigint; v_amount bigint; v_owner uuid; v_reversed boolean;
        v_changer uuid; v_variant text; v_source jsonb; v_earlier uuid; v_entry jsonb;
        v_position integer; v_next uuid; v_next_amount bigint; v_cut bigint; v_before bigint;
        v_overlap boolean; v_start bigint; v_total bigint; v_line uuid; v_next_line uuid;
        v_out record;
        v_credit app.customer_credit_applications%ROWTYPE;
        v_deposit app.deposit_applications%ROWTYPE;
    BEGIN
        v_queue:=jsonb_build_array(jsonb_build_object('record_kind',p_record_kind,
            'record_id',p_record,'offset',p_offset,'part',p_part));
        WHILE jsonb_array_length(v_queue)>0 LOOP
            v_item:=v_queue->0; v_queue:=v_queue-0; v_steps:=v_steps+1;
            v_kind:=v_item->>'record_kind'; v_record:=(v_item->>'record_id')::uuid;
            v_offset:=(v_item->>'offset')::bigint; v_part:=(v_item->>'part')::bigint;
            v_amount:=NULL; v_owner:=NULL; v_changer:=NULL; v_reversed:=NULL;
            -- The payment of this source and the correction that wrote it; whether it was
            -- reversed since, and by which correction.
            IF p_kind='CREDIT' AND v_kind='CREDIT_APPLICATION' THEN
                SELECT * INTO v_credit FROM app.customer_credit_applications application
                WHERE application.id=v_record AND application.customer_credit_id=p_source;
                IF FOUND THEN
                    v_amount:=v_credit.amount_usd_cents;
                    SELECT effect.settlement_correction_id INTO v_owner
                    FROM app.settlement_correction_effects effect
                    WHERE effect.customer_credit_application_id=v_record;
                    SELECT true,effect.settlement_correction_id INTO v_reversed,v_changer
                    FROM app.customer_credit_application_reversals reversal
                    LEFT JOIN app.settlement_correction_effects effect
                        ON effect.credit_application_reversal_id=reversal.id
                    WHERE reversal.credit_application_id=v_record;
                END IF;
            ELSIF p_kind='DEPOSIT' AND v_kind='DEPOSIT_APPLICATION' THEN
                SELECT * INTO v_deposit FROM app.deposit_applications application
                WHERE application.id=v_record AND application.deposit_id=p_source;
                IF FOUND THEN
                    v_amount:=v_deposit.amount_usd_cents;
                    SELECT effect.settlement_correction_id INTO v_owner
                    FROM app.settlement_correction_effects effect
                    WHERE effect.deposit_application_id=v_record;
                    SELECT true,effect.settlement_correction_id INTO v_reversed,v_changer
                    FROM app.deposit_application_reversals reversal
                    LEFT JOIN app.settlement_correction_effects effect
                        ON effect.deposit_application_reversal_id=reversal.id
                    WHERE reversal.deposit_application_id=v_record;
                END IF;
            END IF;
            v_reversed:=COALESCE(v_reversed,false);
            -- Fail closed: an unknown payment, offset or part, a stretch that is not inside the
            -- payment (review round 1), or too many steps.
            IF v_amount IS NULL OR v_owner IS NULL OR v_offset IS NULL OR v_part IS NULL
                OR v_offset<0 OR v_part<=0 OR v_offset+v_part>v_amount OR v_steps>100 THEN
                RETURN QUERY SELECT v_owner,v_kind,v_record,v_amount,v_offset,v_part,
                    'CHANGED_APPLICATION'::text;
                CONTINUE;
            END IF;
            -- A stretch that reaches a payment the correction p_until reversed stops there.
            IF v_reversed AND v_changer=p_until THEN
                RETURN QUERY SELECT v_owner,v_kind,v_record,v_amount,v_offset,v_part,NULL::text;
                CONTINUE;
            END IF;
            -- Review round 1: with p_until, a payment is followed only through changes by
            -- corrections strictly earlier than p_until, so each step back reads only earlier
            -- corrections and the recursion ends (fail closed otherwise).
            IF v_reversed AND p_until IS NOT NULL AND NOT EXISTS(SELECT 1
                FROM app.settlement_corrections changer
                JOIN app.settlement_corrections stop_at ON stop_at.id=p_until
                WHERE changer.id=v_changer
                  AND (changer.occurred_at,changer.id)<(stop_at.occurred_at,stop_at.id)) THEN
                RETURN QUERY SELECT v_owner,v_kind,v_record,v_amount,v_offset,v_part,
                    'CHANGED_APPLICATION'::text;
                CONTINUE;
            END IF;
            -- An active payment holds the stretch itself, when it is inside it.
            IF NOT v_reversed THEN
                RETURN QUERY SELECT v_owner,v_kind,v_record,v_amount,v_offset,v_part,
                    CASE WHEN v_offset+v_part<=v_amount THEN NULL ELSE 'CHANGED_APPLICATION' END::text;
                CONTINUE;
            END IF;
            -- The correction that reversed it, of this Settlement.
            v_variant:=NULL; v_source:=NULL; v_earlier:=NULL;
            SELECT draft.payload->>'variant',draft.payload->'source',
                CASE WHEN draft.payload->>'variant'='RETURN_REVERSAL'
                    THEN app.final_settlement_plan_id(draft.payload->'held_from_settlement_correction_id')::uuid END
                INTO v_variant,v_source,v_earlier
            FROM app.settlement_corrections correction
            JOIN app.financial_drafts draft ON draft.id=correction.correlation_id
                AND draft.kind='SETTLEMENT_CORRECTION'
            WHERE correction.id=v_changer AND correction.final_settlement_id=p_settlement;
            IF v_variant='RETURN_REVERSAL' THEN
                -- The return reversal's put-back for the payment: the n-th entry of its stored
                -- source's reapply is its n-th linked payment, checked as in
                -- app.settlement_returned_value_successor, except that the put-back must belong to
                -- this Settlement (the reversed payment may be the rest a Refund correction wrote
                -- again, which the successor function does not follow).
                v_entry:=NULL; v_position:=NULL; v_next:=NULL; v_next_amount:=NULL;
                IF (SELECT count(*) FROM jsonb_array_elements(CASE WHEN jsonb_typeof(v_source->'reapply')='array'
                        THEN v_source->'reapply' ELSE '[]'::jsonb END) item
                    WHERE item->>'application_id'=v_record::text)=1 THEN
                    SELECT entry.item,entry.position::integer INTO v_entry,v_position
                    FROM jsonb_array_elements(CASE WHEN jsonb_typeof(v_source->'reapply')='array'
                        THEN v_source->'reapply' ELSE '[]'::jsonb END) WITH ORDINALITY entry(item,position)
                    WHERE entry.item->>'application_id'=v_record::text AND entry.item->>'source_kind'=p_kind;
                END IF;
                IF v_entry IS NOT NULL THEN
                    SELECT COALESCE(linked.customer_credit_application_id,linked.deposit_application_id)
                        INTO v_next
                    FROM (SELECT effect.customer_credit_application_id,effect.deposit_application_id,
                            row_number() OVER (ORDER BY effect.effect_sequence) AS rank
                        FROM app.settlement_correction_effects effect
                        WHERE effect.settlement_correction_id=v_changer
                          AND (effect.customer_credit_application_id IS NOT NULL
                              OR effect.deposit_application_id IS NOT NULL)) linked
                    WHERE linked.rank=v_position;
                END IF;
                IF v_next IS NOT NULL AND p_kind='CREDIT' THEN
                    IF (SELECT count(*) FROM app.customer_credit_application_details detail
                            WHERE detail.customer_credit_application_id=v_record)=1
                        AND (SELECT count(*) FROM app.customer_credit_application_details detail
                            WHERE detail.customer_credit_application_id=v_next)=1 THEN
                        SELECT detail.invoice_line_id INTO v_line
                        FROM app.customer_credit_application_details detail
                        WHERE detail.customer_credit_application_id=v_record;
                        SELECT detail.invoice_line_id INTO v_next_line
                        FROM app.customer_credit_application_details detail
                        WHERE detail.customer_credit_application_id=v_next;
                        SELECT successor.amount_usd_cents INTO v_next_amount
                        FROM app.customer_credit_applications successor
                        WHERE successor.id=v_next AND v_next_line IS NOT DISTINCT FROM v_line
                          AND successor.final_settlement_id=p_settlement
                          AND successor.customer_credit_id=v_credit.customer_credit_id
                          AND successor.target_kind=v_credit.target_kind
                          AND successor.invoice_id IS NOT DISTINCT FROM v_credit.invoice_id
                          AND successor.late_payment_charge_id
                              IS NOT DISTINCT FROM v_credit.late_payment_charge_id
                          AND successor.amount_usd_cents::text=v_entry->>'amount_usd_cents'
                          AND successor.amount_usd_cents<v_credit.amount_usd_cents;
                    END IF;
                ELSIF v_next IS NOT NULL THEN
                    SELECT successor.amount_usd_cents INTO v_next_amount
                    FROM app.deposit_applications successor
                    WHERE successor.id=v_next AND successor.deposit_id=v_deposit.deposit_id
                      AND successor.final_settlement_id=p_settlement
                      AND successor.application_stage=v_deposit.application_stage
                      AND successor.target_kind=v_deposit.target_kind
                      AND successor.invoice_id IS NOT DISTINCT FROM v_deposit.invoice_id
                      AND successor.invoice_line_id IS NOT DISTINCT FROM v_deposit.invoice_line_id
                      AND successor.late_payment_charge_id
                          IS NOT DISTINCT FROM v_deposit.late_payment_charge_id
                      AND successor.amount_usd_cents::text=v_entry->>'amount_usd_cents'
                      AND successor.amount_usd_cents<v_deposit.amount_usd_cents;
                END IF;
                -- The put-back is the payment with exactly the reversed return's stretches cut
                -- out (owner, 2026-10-14): those stretches, followed to this payment, add up to
                -- the payment less the put-back and do not overlap this stretch, which keeps its
                -- place less the cut stretches before it.
                v_cut:=NULL; v_before:=NULL; v_overlap:=NULL;
                IF v_next_amount IS NOT NULL AND v_earlier IS NOT NULL THEN
                    SELECT COALESCE(sum(at_payment.follow_part_usd_cents),0),
                        COALESCE(sum(at_payment.follow_part_usd_cents) FILTER (WHERE
                            at_payment.follow_offset_usd_cents+at_payment.follow_part_usd_cents<=v_offset),0),
                        COALESCE(bool_or(at_payment.follow_offset_usd_cents<v_offset+v_part
                            AND at_payment.follow_offset_usd_cents+at_payment.follow_part_usd_cents>v_offset),false)
                        INTO v_cut,v_before,v_overlap
                    FROM (SELECT placed.* FROM app.settlement_returned_value_placed(p_settlement,p_kind,
                            p_source,v_earlier,true) placed
                        UNION ALL
                        SELECT placed.* FROM app.settlement_returned_value_placed(p_settlement,p_kind,
                            p_source,v_earlier,false) placed) cut
                    CROSS JOIN LATERAL app.settlement_returned_value_follow(p_settlement,p_kind,p_source,
                        cut.record_kind,cut.record_id,cut.offset_usd_cents,cut.part_usd_cents,v_changer) at_payment
                    WHERE cut.record_kind IN ('CREDIT_APPLICATION','DEPOSIT_APPLICATION')
                      AND at_payment.follow_record_id=v_record AND at_payment.follow_open_kind IS NULL;
                END IF;
                IF v_next_amount IS NULL OR v_cut IS NULL OR v_cut<>v_amount-v_next_amount
                    OR v_overlap THEN
                    RETURN QUERY SELECT v_owner,v_kind,v_record,v_amount,v_offset,v_part,
                        'CHANGED_APPLICATION'::text;
                    CONTINUE;
                END IF;
                v_queue:=v_queue||jsonb_build_array(jsonb_build_object('record_kind',v_kind,
                    'record_id',v_next,'offset',v_offset-v_before,'part',v_part));
                CONTINUE;
            END IF;
            -- A REFUND correction or a pet-damage reclassification Q (owner answer (a) to
            -- Q-2026-10-13-107). Fail closed when Q brought money back from the source other
            -- than by reversing payments, or also reversed the Credit, a return or a receipt, or
            -- forfeited from it.
            IF v_variant IS NULL OR v_variant NOT IN ('REFUND','PET_DAMAGE_RECLASSIFICATION')
                OR EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                    WHERE effect.settlement_correction_id=v_changer
                      AND (EXISTS(SELECT 1 FROM app.refund_corrections changed
                              JOIN app.refunds origin ON origin.id=changed.refund_id
                              WHERE changed.id=effect.refund_correction_id
                                AND (p_kind='CREDIT' AND origin.source_customer_credit_id=p_source
                                    OR p_kind='DEPOSIT' AND origin.source_deposit_id=p_source))
                          OR EXISTS(SELECT 1 FROM app.customer_credit_reversals reversal
                              WHERE reversal.id=effect.customer_credit_reversal_id
                                AND p_kind='CREDIT' AND reversal.customer_credit_id=p_source)
                          OR EXISTS(SELECT 1 FROM app.deposit_receipts receipt
                              WHERE receipt.id=effect.deposit_receipt_id
                                AND p_kind='DEPOSIT' AND receipt.deposit_id=p_source)
                          OR EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                              JOIN app.deposit_receipts receipt ON receipt.id=reversal.deposit_receipt_id
                              WHERE reversal.id=effect.deposit_receipt_reversal_id
                                AND p_kind='DEPOSIT' AND receipt.deposit_id=p_source)
                          OR EXISTS(SELECT 1 FROM app.deposit_dispositions disposition
                              WHERE disposition.id=effect.deposit_disposition_id
                                AND p_kind='DEPOSIT' AND disposition.deposit_id=p_source)
                          OR EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal
                              JOIN app.deposit_dispositions disposition
                                  ON disposition.id=reversal.deposit_disposition_id
                              WHERE reversal.id=effect.deposit_disposition_reversal_id
                                AND p_kind='DEPOSIT' AND disposition.deposit_id=p_source)))
            THEN
                RETURN QUERY SELECT v_owner,v_kind,v_record,v_amount,v_offset,v_part,
                    'CHANGED_APPLICATION'::text;
                CONTINUE;
            END IF;
            -- Where the stretch sits in what Q took back: Q's reversals of payments from the
            -- source, in the order Q wrote them.
            v_start:=NULL;
            SELECT taken_back.before_it+v_offset INTO v_start
            FROM (SELECT reversed.id,COALESCE(sum(reversed.amount_usd_cents) OVER (
                        ORDER BY reversed.effect_sequence
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0) AS before_it
                FROM (SELECT application.id,application.amount_usd_cents,effect.effect_sequence
                    FROM app.settlement_correction_effects effect
                    JOIN app.customer_credit_application_reversals reversal
                        ON reversal.id=effect.credit_application_reversal_id
                    JOIN app.customer_credit_applications application
                        ON application.id=reversal.credit_application_id
                    WHERE effect.settlement_correction_id=v_changer AND p_kind='CREDIT'
                      AND application.customer_credit_id=p_source
                    UNION ALL
                    SELECT application.id,application.amount_usd_cents,effect.effect_sequence
                    FROM app.settlement_correction_effects effect
                    JOIN app.deposit_application_reversals reversal
                        ON reversal.id=effect.deposit_application_reversal_id
                    JOIN app.deposit_applications application
                        ON application.id=reversal.deposit_application_id
                    WHERE effect.settlement_correction_id=v_changer AND p_kind='DEPOSIT'
                      AND application.deposit_id=p_source) reversed) taken_back
            WHERE taken_back.id=v_record;
            -- Q's payouts from the source: its Refunds, the oldest first, then its payments, the
            -- newest first; the stretch must lie within them (else Q left money in the source).
            SELECT COALESCE(sum(paid.amount),0) INTO v_total
            FROM (SELECT refund.usd_accounting_value_cents::bigint AS amount
                FROM app.settlement_correction_effects effect
                JOIN app.refunds refund ON refund.id=effect.refund_id
                WHERE effect.settlement_correction_id=v_changer
                  AND (p_kind='CREDIT' AND refund.source_customer_credit_id=p_source
                      OR p_kind='DEPOSIT' AND refund.source_deposit_id=p_source)
                UNION ALL
                SELECT application.amount_usd_cents
                FROM app.settlement_correction_effects effect
                JOIN app.customer_credit_applications application
                    ON application.id=effect.customer_credit_application_id
                WHERE effect.settlement_correction_id=v_changer AND p_kind='CREDIT'
                  AND application.customer_credit_id=p_source
                UNION ALL
                SELECT application.amount_usd_cents
                FROM app.settlement_correction_effects effect
                JOIN app.deposit_applications application
                    ON application.id=effect.deposit_application_id
                WHERE effect.settlement_correction_id=v_changer AND p_kind='DEPOSIT'
                  AND application.deposit_id=p_source) paid;
            IF v_start IS NULL OR v_start+v_part>v_total THEN
                RETURN QUERY SELECT v_owner,v_kind,v_record,v_amount,v_offset,v_part,
                    'CHANGED_APPLICATION'::text;
                CONTINUE;
            END IF;
            FOR v_out IN
                SELECT stream.kind,stream.id,stream.amount,
                    GREATEST(stream.before_it,v_start)-stream.before_it AS offset_in,
                    LEAST(stream.before_it+stream.amount,v_start+v_part)
                        -GREATEST(stream.before_it,v_start) AS part
                FROM (SELECT records.*,COALESCE(sum(records.amount) OVER (
                            ORDER BY records.record_group,records.record_order
                            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0) AS before_it
                    FROM (SELECT 'REFUND' AS kind,refund.id,
                            refund.usd_accounting_value_cents::bigint AS amount,1 AS record_group,
                            row_number() OVER (ORDER BY refund.processed_at,refund.id) AS record_order
                        FROM app.settlement_correction_effects effect
                        JOIN app.refunds refund ON refund.id=effect.refund_id
                        WHERE effect.settlement_correction_id=v_changer
                          AND (p_kind='CREDIT' AND refund.source_customer_credit_id=p_source
                              OR p_kind='DEPOSIT' AND refund.source_deposit_id=p_source)
                        UNION ALL
                        SELECT 'CREDIT_APPLICATION',application.id,application.amount_usd_cents,2,
                            row_number() OVER (ORDER BY application.occurred_at DESC,application.id DESC)
                        FROM app.settlement_correction_effects effect
                        JOIN app.customer_credit_applications application
                            ON application.id=effect.customer_credit_application_id
                        WHERE effect.settlement_correction_id=v_changer AND p_kind='CREDIT'
                          AND application.customer_credit_id=p_source
                        UNION ALL
                        SELECT 'DEPOSIT_APPLICATION',application.id,application.amount_usd_cents,2,
                            row_number() OVER (ORDER BY application.occurred_at DESC,
                                application.application_order DESC,application.id DESC)
                        FROM app.settlement_correction_effects effect
                        JOIN app.deposit_applications application
                            ON application.id=effect.deposit_application_id
                        WHERE effect.settlement_correction_id=v_changer AND p_kind='DEPOSIT'
                          AND application.deposit_id=p_source) records) stream
                WHERE stream.before_it+stream.amount>v_start AND stream.before_it<v_start+v_part
                ORDER BY stream.before_it
            LOOP
                IF v_out.kind='REFUND' THEN
                    -- A Refund of Q holds that part (charged back to the person who received it).
                    RETURN QUERY SELECT v_changer,'REFUND'::text,v_out.id,v_out.amount,
                        v_out.offset_in::bigint,v_out.part::bigint,NULL::text;
                ELSE
                    v_queue:=v_queue||jsonb_build_array(jsonb_build_object('record_kind',v_out.kind,
                        'record_id',v_out.id,'offset',v_out.offset_in,'part',v_out.part));
                END IF;
            END LOOP;
        END LOOP;
    END $$;
"""

INTERNAL = (
    "app.settlement_returned_value_placed(uuid,text,uuid,uuid,boolean)",
    "app.settlement_returned_value_follow(uuid,text,uuid,text,uuid,bigint,bigint,uuid)",
)
REPLACED = "app.settlement_returned_value_parts(uuid,text,uuid,uuid,boolean)"

KIND = "CASE WHEN earlier.deposit_id IS NOT NULL THEN 'DEPOSIT' ELSE 'CREDIT' END"
SOURCE_ID = "COALESCE(earlier.deposit_id,earlier.credit_id)"

SOURCE = "app.settlement_return_reversal_source_state(uuid,uuid)"
SOURCE_REPLACEMENTS = (
    (
        """        -- Sub-slice 10e-3d-2b-1a (owner answer (a) to Q-2026-10-13-100 point 1): an application
        -- part follows to the application now holding it (app.settlement_returned_value_successor:
        -- itself while active, else the put-back of the return reversal that changed it), with
        -- that application's correction and amount; it is open when there is none or the part is
        -- more than it.
        ), swept_state AS (
            SELECT taken.own,COALESCE(followed.correction_id,taken.settlement_correction_id)
                    AS settlement_correction_id,
                taken.record_kind,COALESCE(followed.id,taken.record_id) AS record_id,
                COALESCE(followed.amount,taken.amount_usd_cents)::bigint AS amount_usd_cents,
                taken.part_usd_cents,CASE
                    WHEN taken.record_kind NOT IN ('REFUND','CREDIT_APPLICATION','DEPOSIT_APPLICATION')
                        THEN taken.record_kind
                    WHEN taken.record_kind IN ('CREDIT_APPLICATION','DEPOSIT_APPLICATION')
                        AND NOT COALESCE(followed.amount>=taken.part_usd_cents,false)
                        THEN 'CHANGED_APPLICATION'
                    WHEN taken.record_kind='REFUND' AND NOT COALESCE(taken.part_usd_cents
                        <=app.refund_net_value_at(taken.record_id,'infinity'),false)
                        THEN 'CHANGED_REFUND' END AS open_kind
            FROM earlier
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
            LEFT JOIN LATERAL (
                SELECT successor.id,COALESCE(credit_now.amount_usd_cents,deposit_now.amount_usd_cents)
                        AS amount,
                    owner.settlement_correction_id AS correction_id
                FROM (SELECT app.settlement_returned_value_successor(CASE taken.record_kind
                        WHEN 'CREDIT_APPLICATION' THEN 'CREDIT' ELSE 'DEPOSIT' END,
                        taken.record_id) AS id) successor
                LEFT JOIN app.customer_credit_applications credit_now
                    ON taken.record_kind='CREDIT_APPLICATION' AND credit_now.id=successor.id
                LEFT JOIN app.deposit_applications deposit_now
                    ON taken.record_kind='DEPOSIT_APPLICATION' AND deposit_now.id=successor.id
                LEFT JOIN app.settlement_correction_effects owner
                    ON owner.customer_credit_application_id=successor.id
                    OR owner.deposit_application_id=successor.id
                WHERE taken.record_kind IN ('CREDIT_APPLICATION','DEPOSIT_APPLICATION')
                  AND successor.id IS NOT NULL) followed ON true
""",
        """        -- Sub-slice 10e-3d-2b-2 (owner answer (a) to Q-2026-10-13-107): each part keeps its
        -- place in its record (app.settlement_returned_value_placed); a payment part is followed
        -- to the records that hold it now (app.settlement_returned_value_follow: the payment
        -- itself while active; a return reversal's put-back, with that return's money cut out;
        -- the Refunds and payments of a REFUND correction or pet-damage reclassification that
        -- changed it, in the order that correction paid the money out again), and the rows are
        -- summed per own flag, correction and record. A part that cannot be followed is open
        -- with the record where it stops; a Refund part more than the Refund's net is open.
        ), swept_state AS (
            SELECT held.own,held.settlement_correction_id,held.record_kind,held.record_id,
                held.amount_usd_cents,held.part_usd_cents,CASE
                    WHEN held.open_kind IS NOT NULL THEN held.open_kind
                    WHEN held.record_kind='REFUND' AND NOT COALESCE(held.part_usd_cents
                        <=app.refund_net_value_at(held.record_id,'infinity'),false)
                        THEN 'CHANGED_REFUND' END AS open_kind
            FROM (SELECT taken.own AS own,holding.settlement_correction_id,holding.record_kind,
                    holding.record_id,max(holding.amount_usd_cents)::bigint AS amount_usd_cents,
                    sum(holding.part_usd_cents)::bigint AS part_usd_cents,
                    max(holding.open_kind) AS open_kind
                FROM earlier
                CROSS JOIN LATERAL (
                    SELECT false AS own,swept_take.* FROM app.settlement_returned_value_placed(p_settlement,
                        """
        + KIND
        + """,
                        """
        + SOURCE_ID
        + """,earlier.id,true) swept_take
                    UNION ALL
                    SELECT true,own_take.* FROM app.settlement_returned_value_placed(p_settlement,
                        """
        + KIND
        + """,
                        """
        + SOURCE_ID
        + """,earlier.id,false) own_take
                    WHERE (SELECT own_walk.walk FROM own_walk)) taken
                CROSS JOIN LATERAL (
                    SELECT taken.settlement_correction_id,taken.record_kind,taken.record_id,
                        taken.amount_usd_cents,taken.part_usd_cents,
                        CASE WHEN taken.record_kind<>'REFUND' THEN taken.record_kind END AS open_kind
                    WHERE taken.record_kind NOT IN ('CREDIT_APPLICATION','DEPOSIT_APPLICATION')
                    UNION ALL
                    SELECT follow.follow_correction_id,follow.follow_record_kind,follow.follow_record_id,
                        follow.follow_amount_usd_cents,follow.follow_part_usd_cents,
                        follow.follow_open_kind
                    FROM app.settlement_returned_value_follow(p_settlement,
                        """
        + KIND
        + """,
                        """
        + SOURCE_ID
        + """,taken.record_kind,taken.record_id,
                        taken.offset_usd_cents,taken.part_usd_cents) follow
                    WHERE taken.record_kind IN ('CREDIT_APPLICATION','DEPOSIT_APPLICATION')) holding
                GROUP BY taken.own,holding.settlement_correction_id,holding.record_kind,
                    holding.record_id) held
""",
    ),
)

SCOPE = "app.settlement_return_reversal_refund(uuid,uuid)"
SCOPE_REPLACEMENTS = (
    (
        """                      OR EXISTS(SELECT 1 FROM jsonb_array_elements(draft.payload->'source'->'swept') taken
""",
        """                      -- Sub-slice 10e-3d-2b-2: or one it names as an own use's part (a
                      -- changing correction's Refund that now holds the returned money).
                      OR EXISTS(SELECT 1 FROM jsonb_array_elements((draft.payload->'source'->'swept')
                              ||CASE WHEN jsonb_typeof(draft.payload->'source'->'own_parts')='array'
                                  THEN draft.payload->'source'->'own_parts' ELSE '[]'::jsonb END) taken
""",
    ),
)

ASSERT = "app.assert_settlement_return_reversal_allowed(jsonb)"
ASSERT_REPLACEMENTS = (
    (
        """        THEN RAISE EXCEPTION 'A later correction changed a payment made with this return''s money; reversing it waits for sub-slice 10e-3d-2b'
""",
        """        -- Sub-slice 10e-3d-2b-2: a change the follow function cannot follow (fail closed).
        THEN RAISE EXCEPTION 'A later correction changed a payment made with this return''s money in a way this reversal cannot follow yet; reversing it waits for the owner'
""",
    ),
)

PATCHES = (
    (SOURCE, SOURCE_REPLACEMENTS),
    (SCOPE, SCOPE_REPLACEMENTS),
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
                f"Settlement return reversal changed payment contract changed: {signature}"
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
    raise RuntimeError("Settlement return reversal changed payment migration is forward-only")
