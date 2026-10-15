# ruff: noqa: E501
"""A return's money that left through a bounced Payment or a wrong receipt is charged to the person
who received the returned Refund (V1-056 sub-slice 10e-3d-2c).

BR-SETTLE-013, BR-SETTLE-016, BR-REFUND-015, BR-CREDIT-014, DL-032; DB-SETTLE-005, DB-REFUND-002;
owner answer (a) to Q-2026-10-13-103 point 1 ("charge the person who received that Refund"; the
Q-2026-10-11-78 rule). A `RETURNED_PAYMENT` correction (a bounced Payment) or a
`DEPOSIT_RECEIPT_CORRECTION` (a wrong receipt) C recovers every Refund paid from the money it takes
back, reverses the payments made from it and then reverses the source itself (the Credit reversal
takes all the Credit holds; the receipt reversal empties the Deposit). So money of an earlier
return-only correction E that was still in the source, or that C brought back into it from another
correction's payment or Refund, left with C's reversal of the source, while C charged E's returned
Refund R's recipient only R's net, which E had lowered. E's reversal now charges each such part to
the person who received R (a further `RECOVERED_BY_CHARGE` on R, linked to the reversal, on R's
charge Lease as the sub-slice 10e-1c charge, or with no Lease), and nothing else: the charges C made
to other Refunds' recipients and the debts C made owed again stay.

- `app.settlement_returned_value_placed` (exact-text patch): the take of such a C of this Settlement
  through its Credit reversal or receipt reversal is a part of E's returned Refund (new record kind
  `RETURNED_REFUND`, record id R) instead of an open take; any other open take stays open.
- `app.settlement_returned_value_follow` (exact-text patch): a stretch on a payment such a C of this
  Settlement reversed, where C also reversed the source, is a `RETURNED_REFUND` part (record id
  NULL; the caller names its own return's Refund); without C's reversal of the source it stops open.
- `app.settlement_return_reversal_source_state` (exact-text patches): the follow's
  `RETURNED_REFUND` rows name E's Refund; a Refund part more than its Refund's net, where such a C
  recovered at least that excess from the Refund by a charge and also reversed the source, splits
  into the Refund part (at most its net) and a `RETURNED_REFUND` part (the excess); the
  `RETURNED_REFUND` parts stay open (kind `RETURNED_REFUND`) when they add up to more than R's net
  after E's return is reversed (another active return of R does not refuse it: C charged only the
  net every return had lowered, so each return's reversal charges back only its own money;
  implementer's design change); the parts undone are summed into one recovery entry of R (its
  recipient, its net after the reversal). An own use's Refund from the source that such a correction recovered also takes the
  walk path, so its part is placed and charged back the same way.
- `app.assert_settlement_return_reversal_allowed` (exact-text patches): a `RETURNED_REFUND` part is
  E's returned Refund and is listed exactly (one recovery entry of R, its amount the sum of every
  such part, no more than its net); a part that cannot be followed keeps the
  refusal, reworded to "A Credit reversal or a Deposit receipt reversal paid out this return's
  money in a way this reversal cannot follow yet; reversing it waits for the owner".
- `app.settlement_return_reversal_refund` (exact-text patch, relaxing): the recovery scope also
  accepts R when the draft's source names a `RETURNED_REFUND` part of it and lists its recovery for
  its recipient.
- `app.confirm_settlement_return_reversal` (exact-text patches): R's recovery entry is written
  right after the `CORRECTION_REVERSAL` row (before it R's net is what C left, 0 when C recovered
  all of it; a recovery may never leave a negative net), dated at that row's time, the other
  entries before it as today.
- `app.validate_general_refund_correction` (exact-text patches, relaxing; implementer's design
  changes, for review round 1): (1) the reversal of E's return inside its own `RETURN_REVERSAL`
  counts the charge-back of R that the same correction's draft lists as available in the source
  (the charge-back brings that money back), and when it covers the whole reversal it also stands
  for a source Payment that is no longer received; (2) R's charge-back may take the same time as
  that reversal (never earlier, and no other row may tie), so the two make one point in the
  source's history: the deferred Credit and Deposit history checks group events by time, and a
  later charge-back would leave the source below zero between the two rows. New internal
  `app.settlement_return_reversal_charge_back(app.refund_corrections)` and
  `app.settlement_return_reversal_paired_charge_back(app.refund_corrections)`.
- `app.write_payment_return_recoveries` (exact-text patches): R's charge says it recovers value
  whose return was recorded by mistake, and R's recovery row takes the reversal's time the confirm
  passes in its evidence (`returned_refund_at`, honoured only inside a `RETURN_REVERSAL` for the
  Refund the evidence names); every other recovery is unchanged. R's recovery row is so dated a
  few microseconds before the charge Invoice it names (nothing reads that order; the history
  checks read the recovery's time).

No lock, grant, table, constraint or trigger change. A `RETURN_REVERSAL` draft recorded before this
migration whose source now differs is stale at its confirm (P5S02); staff reject it and record it
again.
"""

from alembic import op
from sqlalchemy import text

revision = "20261210_136"
down_revision = "20261209_135"
branch_labels = None
depends_on = None

INTERNAL = (
    "app.settlement_return_reversal_charge_back(app.refund_corrections)",
    "app.settlement_return_reversal_paired_charge_back(app.refund_corrections)",
)

FUNCTION_SQL = r"""
    CREATE FUNCTION app.settlement_return_reversal_charge_back(p_correction app.refund_corrections)
    RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        -- Sub-slice 10e-3d-2c (owner answer (a) to Q-2026-10-13-103 point 1): the charge-back of
        -- the returned Refund that the RETURN_REVERSAL correction reversing this return lists in
        -- its draft's source, confirmed in this transaction by this row's actor; 0 for any other
        -- row.
        SELECT CASE WHEN app.settlement_return_reversal_allowed(p_correction) THEN COALESCE((
                SELECT sum((item->>'amount_usd_cents')::bigint)
                FROM app.settlement_correction_effects effect
                JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
                JOIN app.financial_drafts draft ON draft.id=correction.correlation_id
                    AND draft.kind='SETTLEMENT_CORRECTION' AND draft.payload->>'variant'='RETURN_REVERSAL'
                JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id
                    AND decision.decision='CONFIRMED' AND decision.decided_by=correction.actor_id
                CROSS JOIN LATERAL jsonb_array_elements(draft.payload->'source'->'recoveries') item
                WHERE effect.refund_correction_id=(p_correction).id
                  AND correction.actor_id=(p_correction).actor_id
                  AND decision.result->>'transaction_id'=pg_current_xact_id()::text
                  AND decision.decided_at>=transaction_timestamp()
                  AND (p_correction).refund_id::text=draft.payload->>'refund_id'
                  AND item->>'refund_id'=(p_correction).refund_id::text
                  AND EXISTS(SELECT 1 FROM jsonb_array_elements((draft.payload->'source'->'swept')
                          ||CASE WHEN jsonb_typeof(draft.payload->'source'->'own_parts')='array'
                              THEN draft.payload->'source'->'own_parts' ELSE '[]'::jsonb END) part
                      WHERE part->>'record_kind'='RETURNED_REFUND'
                        AND part->>'record_id'=(p_correction).refund_id::text)),0)
            ELSE 0 END::bigint
    $$;
    CREATE FUNCTION app.settlement_return_reversal_paired_charge_back(p_correction app.refund_corrections)
    RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        -- Sub-slice 10e-3d-2c: the returned Refund's charge-back that the RETURN_REVERSAL
        -- correction confirmed in this transaction by this row's actor lists in its draft's
        -- source, dated at the reversal of that return the same correction wrote on the Refund
        -- just before it, so the two make one point in the source's history (the reversal takes
        -- the money out of the source and the charge-back brings it back at the same time).
        SELECT COALESCE((SELECT bool_or(true)
            FROM app.settlement_correction_effects effect
            JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
            JOIN app.financial_drafts draft ON draft.id=correction.correlation_id
                AND draft.kind='SETTLEMENT_CORRECTION' AND draft.payload->>'variant'='RETURN_REVERSAL'
            JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id
                AND decision.decision='CONFIRMED' AND decision.decided_by=correction.actor_id
            WHERE effect.refund_correction_id=(p_correction).id
              AND (p_correction).correction_kind='RECOVERED_BY_CHARGE'
              AND correction.actor_id=(p_correction).actor_id
              AND decision.result->>'transaction_id'=pg_current_xact_id()::text
              AND decision.decided_at>=transaction_timestamp()
              AND (p_correction).refund_id::text=draft.payload->>'refund_id'
              AND EXISTS(SELECT 1 FROM jsonb_array_elements(draft.payload->'source'->'recoveries') item
                  WHERE item->>'refund_id'=(p_correction).refund_id::text)
              AND EXISTS(SELECT 1 FROM jsonb_array_elements((draft.payload->'source'->'swept')
                      ||CASE WHEN jsonb_typeof(draft.payload->'source'->'own_parts')='array'
                          THEN draft.payload->'source'->'own_parts' ELSE '[]'::jsonb END) part
                  WHERE part->>'record_kind'='RETURNED_REFUND'
                    AND part->>'record_id'=(p_correction).refund_id::text)
              AND EXISTS(SELECT 1 FROM app.settlement_correction_effects paired
                  JOIN app.refund_corrections reversal ON reversal.id=paired.refund_correction_id
                  WHERE paired.settlement_correction_id=correction.id
                    AND reversal.refund_id=(p_correction).refund_id
                    AND reversal.correction_kind='CORRECTION_REVERSAL'
                    AND reversal.reverses_correction_id::text
                        =draft.payload->'source'->'earlier'->>'return_id'
                    AND reversal.occurred_at=(p_correction).occurred_at)),false)
    $$;
"""

# The variants whose reversal of the source (a Credit reversal, or a receipt reversal) takes the
# money a return brought back: a bounced Payment's correction and a receipt correction.
RETURNED_VARIANTS = "('RETURNED_PAYMENT','DEPOSIT_RECEIPT_CORRECTION')"

PLACED = "app.settlement_returned_value_placed(uuid,text,uuid,uuid,boolean)"
PLACED_REPLACEMENTS = (
    (
        """        SELECT opened.taker,opened.kind,opened.id,taken.amount,taken.amount,0::bigint
        FROM opened JOIN taken ON taken.taker=opened.taker
""",
        """        -- Sub-slice 10e-3d-2c (owner answer (a) to Q-2026-10-13-103 point 1): the take of a
        -- bounced Payment's correction or a receipt correction of this Settlement through its
        -- Credit reversal or receipt reversal is a part of the earlier return's own returned
        -- Refund, charged back to the person who received it; any other open take stays open.
        SELECT opened.taker,CASE WHEN returned.refund_id IS NOT NULL THEN 'RETURNED_REFUND'
                ELSE opened.kind END,COALESCE(returned.refund_id,opened.id),
            taken.amount,taken.amount,0::bigint
        FROM opened JOIN taken ON taken.taker=opened.taker
        LEFT JOIN LATERAL (SELECT origin.id AS refund_id
            FROM app.settlement_corrections taker_correction
            JOIN app.financial_drafts draft ON draft.id=taker_correction.correlation_id
                AND draft.kind='SETTLEMENT_CORRECTION'
                AND draft.payload->>'variant' IN """
        + RETURNED_VARIANTS
        + """
            JOIN app.settlement_correction_effects effect ON effect.settlement_correction_id=p_earlier
            JOIN app.refund_corrections return_row ON return_row.id=effect.refund_correction_id
                AND return_row.correction_kind='VALUE_CORRECTION'
            JOIN app.refunds origin ON origin.id=return_row.refund_id
            WHERE taker_correction.id=opened.taker
              AND taker_correction.final_settlement_id=p_settlement
              AND opened.kind IN ('CREDIT_REVERSAL','RECEIPT_REVERSAL')
              AND (p_kind='CREDIT' AND origin.source_customer_credit_id=p_source
                  OR p_kind='DEPOSIT' AND origin.source_deposit_id=p_source)
            ORDER BY return_row.id LIMIT 1) returned ON true
""",
    ),
)

FOLLOW = "app.settlement_returned_value_follow(uuid,text,uuid,text,uuid,bigint,bigint,uuid)"
FOLLOW_REPLACEMENTS = (
    (
        """            -- A REFUND correction or a pet-damage reclassification Q (owner answer (a) to
""",
        """            -- Sub-slice 10e-3d-2c (owner answer (a) to Q-2026-10-13-103 point 1): a bounced
            -- Payment's correction or a receipt correction C reversed the payment, so the stretch
            -- went back into the source, and C's reversal of the source (its Credit reversal, or the
            -- reversal of a receipt into the Deposit) took it out: the stretch is a part of the
            -- caller's return's own returned Refund, which the caller names (record id NULL).
            -- Fail closed when C did not also reverse the source.
            IF v_variant IN """
        + RETURNED_VARIANTS
        + """ THEN
                IF EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                    WHERE effect.settlement_correction_id=v_changer
                      AND (EXISTS(SELECT 1 FROM app.customer_credit_reversals reversal
                              WHERE reversal.id=effect.customer_credit_reversal_id
                                AND p_kind='CREDIT' AND reversal.customer_credit_id=p_source)
                          OR EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                              JOIN app.deposit_receipts receipt ON receipt.id=reversal.deposit_receipt_id
                              WHERE reversal.id=effect.deposit_receipt_reversal_id
                                AND p_kind='DEPOSIT' AND receipt.deposit_id=p_source))) THEN
                    RETURN QUERY SELECT v_changer,'RETURNED_REFUND'::text,NULL::uuid,NULL::bigint,
                        0::bigint,v_part,NULL::text;
                ELSE
                    RETURN QUERY SELECT v_owner,v_kind,v_record,v_amount,v_offset,v_part,
                        'CHANGED_APPLICATION'::text;
                END IF;
                CONTINUE;
            END IF;
            -- A REFUND correction or a pet-damage reclassification Q (owner answer (a) to
""",
    ),
)

SOURCE = "app.settlement_return_reversal_source_state(uuid,uuid)"
SOURCE_REPLACEMENTS = (
    (
        """                    WHERE walk.walk_kind='DRAW' AND walk.walk_offset_usd_cents>0
                      AND walk.walk_correction_id IN (SELECT users.id FROM users)) AS walk
""",
        """                    WHERE walk.walk_kind='DRAW' AND walk.walk_offset_usd_cents>0
                      AND walk.walk_correction_id IN (SELECT users.id FROM users))
                -- Sub-slice 10e-3d-2c: or an own use's Refund from the source that a bounced
                -- Payment's correction or a receipt correction recovered by a charge, so its part
                -- is placed and charged back as below.
                OR EXISTS(SELECT 1 FROM paid own_refund
                    JOIN app.refund_corrections recovery ON recovery.refund_id=own_refund.id
                        AND recovery.correction_kind='RECOVERED_BY_CHARGE'
                    JOIN app.settlement_correction_effects effect
                        ON effect.refund_correction_id=recovery.id
                    JOIN app.settlement_corrections recovery_owner
                        ON recovery_owner.id=effect.settlement_correction_id
                    JOIN app.financial_drafts draft ON draft.id=recovery_owner.correlation_id
                        AND draft.kind='SETTLEMENT_CORRECTION'
                        AND draft.payload->>'variant' IN """
        + RETURNED_VARIANTS
        + """) AS walk
""",
    ),
    (
        """        ), swept_state AS (
            SELECT held.own,held.settlement_correction_id,held.record_kind,held.record_id,
                held.amount_usd_cents,held.part_usd_cents,CASE
                    WHEN held.open_kind IS NOT NULL THEN held.open_kind
                    WHEN held.record_kind='REFUND' AND NOT COALESCE(held.part_usd_cents
                        <=app.refund_net_value_at(held.record_id,'infinity'),false)
                        THEN 'CHANGED_REFUND' END AS open_kind
            FROM (SELECT taken.own AS own,holding.settlement_correction_id,holding.record_kind,
""",
        """        ), swept_grouped AS (
            SELECT taken.own AS own,holding.settlement_correction_id,holding.record_kind,
""",
    ),
    (
        """                        CASE WHEN taken.record_kind<>'REFUND' THEN taken.record_kind END AS open_kind
""",
        """                        CASE WHEN taken.record_kind NOT IN ('REFUND','RETURNED_REFUND')
                            THEN taken.record_kind END AS open_kind
""",
    ),
    (
        """                    SELECT follow.follow_correction_id,follow.follow_record_kind,follow.follow_record_id,
""",
        """                    -- Sub-slice 10e-3d-2c: a part the follow function hands back as the
                    -- returned Refund is this return's own returned Refund.
                    SELECT follow.follow_correction_id,follow.follow_record_kind,
                        CASE WHEN follow.follow_record_kind='RETURNED_REFUND' THEN earlier.refund_id
                            ELSE follow.follow_record_id END,
""",
    ),
    (
        """                GROUP BY taken.own,holding.settlement_correction_id,holding.record_kind,
                    holding.record_id) held
""",
        """                GROUP BY taken.own,holding.settlement_correction_id,holding.record_kind,
                    holding.record_id
        -- Sub-slice 10e-3d-2c (owner answer (a) to Q-2026-10-13-103 point 1): a Refund part more
        -- than its Refund's net, where a bounced Payment's correction or a receipt correction C of
        -- this Settlement recovered at least that excess from the Refund by a charge and also
        -- reversed the source (its Credit reversal, or the reversal of a receipt into the
        -- Deposit), went back into the source with that recovery and out with C's reversal: the
        -- excess is a part of this return's own returned Refund, charged back to the person who
        -- received it, and the rest stays a part of the Refund. Without such a C the part stays
        -- open below.
        ), swept_cover AS (
            SELECT grouped.own,grouped.settlement_correction_id,grouped.record_id,cover.correction_id,
                (grouped.part_usd_cents
                    -GREATEST(app.refund_net_value_at(grouped.record_id,'infinity'),0))::bigint AS excess
            FROM swept_grouped grouped
            CROSS JOIN earlier
            CROSS JOIN LATERAL (SELECT recovery_owner.id AS correction_id
                FROM app.settlement_correction_effects effect
                JOIN app.refund_corrections recovery ON recovery.id=effect.refund_correction_id
                    AND recovery.correction_kind='RECOVERED_BY_CHARGE'
                    AND recovery.refund_id=grouped.record_id
                JOIN app.settlement_corrections recovery_owner
                    ON recovery_owner.id=effect.settlement_correction_id
                    AND recovery_owner.final_settlement_id=p_settlement
                JOIN app.financial_drafts draft ON draft.id=recovery_owner.correlation_id
                    AND draft.kind='SETTLEMENT_CORRECTION'
                    AND draft.payload->>'variant' IN """
        + RETURNED_VARIANTS
        + """
                WHERE recovery.source_balance_effect_usd_cents>=grouped.part_usd_cents
                        -GREATEST(app.refund_net_value_at(grouped.record_id,'infinity'),0)
                  AND EXISTS(SELECT 1 FROM app.settlement_correction_effects reversed
                    WHERE reversed.settlement_correction_id=recovery_owner.id
                      AND (EXISTS(SELECT 1 FROM app.customer_credit_reversals reversal
                              WHERE reversal.id=reversed.customer_credit_reversal_id
                                AND reversal.customer_credit_id=earlier.credit_id)
                          OR EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                              JOIN app.deposit_receipts receipt
                                  ON receipt.id=reversal.deposit_receipt_id
                              WHERE reversal.id=reversed.deposit_receipt_reversal_id
                                AND receipt.deposit_id=earlier.deposit_id)))
                ORDER BY recovery_owner.occurred_at,recovery_owner.id LIMIT 1) cover
            WHERE grouped.record_kind='REFUND' AND grouped.open_kind IS NULL
              AND grouped.part_usd_cents>app.refund_net_value_at(grouped.record_id,'infinity')
        ), swept_split AS (
            SELECT grouped.own,grouped.settlement_correction_id,grouped.record_kind,
                grouped.record_id,grouped.amount_usd_cents,
                (grouped.part_usd_cents-COALESCE(cover.excess,0))::bigint AS part_usd_cents,
                grouped.open_kind
            FROM swept_grouped grouped
            LEFT JOIN swept_cover cover ON grouped.record_kind='REFUND' AND cover.own=grouped.own
                AND cover.settlement_correction_id=grouped.settlement_correction_id
                AND cover.record_id=grouped.record_id
            UNION ALL
            SELECT cover.own,cover.correction_id,'RETURNED_REFUND',earlier.refund_id,NULL::bigint,
                cover.excess,NULL::text
            FROM swept_cover cover CROSS JOIN earlier
        -- The parts summed per own flag, correction and record again; a part of the returned
        -- Refund stays open when the parts of it add up to more than its net once this return is
        -- reversed (fail closed). Another active return of that Refund does not refuse it: the
        -- correction that took the money charged only the net that every return had lowered, so
        -- each return's reversal charges back only its own money (implementer's design change).
        ), swept_state AS (
            SELECT held.own,held.settlement_correction_id,held.record_kind,held.record_id,
                CASE WHEN held.record_kind='RETURNED_REFUND' THEN (SELECT
                        refund.usd_accounting_value_cents::bigint FROM app.refunds refund
                        WHERE refund.id=held.record_id)
                    ELSE held.amount_usd_cents END AS amount_usd_cents,
                held.part_usd_cents,CASE
                    WHEN held.open_kind IS NOT NULL THEN held.open_kind
                    WHEN held.record_kind='REFUND' AND NOT COALESCE(held.part_usd_cents
                        <=app.refund_net_value_at(held.record_id,'infinity'),false)
                        THEN 'CHANGED_REFUND'
                    WHEN held.record_kind='RETURNED_REFUND' AND NOT COALESCE(
                        held.record_id=earlier.refund_id
                        AND held.returned_total<=app.refund_net_value_at(earlier.refund_id,'infinity')
                            +earlier.amount,false)
                        THEN 'RETURNED_REFUND' END AS open_kind
            FROM (SELECT split.own,split.settlement_correction_id,split.record_kind,split.record_id,
                    max(split.amount_usd_cents)::bigint AS amount_usd_cents,
                    sum(split.part_usd_cents)::bigint AS part_usd_cents,
                    max(split.open_kind) AS open_kind,
                    (sum(sum(split.part_usd_cents) FILTER (WHERE split.record_kind='RETURNED_REFUND'))
                        OVER ())::bigint AS returned_total
                FROM swept_split split WHERE split.part_usd_cents>0
                GROUP BY split.own,split.settlement_correction_id,split.record_kind,
                    split.record_id) held
            CROSS JOIN earlier
""",
    ),
    (
        """            FROM swept_undone taken JOIN app.refunds refund ON refund.id=taken.record_id
            WHERE taken.record_kind='REFUND'
""",
        """            FROM swept_undone taken JOIN app.refunds refund ON refund.id=taken.record_id
            WHERE taken.record_kind='REFUND'
        -- Sub-slice 10e-3d-2c (owner answer (a) to Q-2026-10-13-103 point 1): one recovery entry
        -- of this return's own returned Refund for every part of it this reversal undoes: its
        -- recipient pays them back (the Q-2026-10-11-78 and Q-2026-10-12-94 recipient rule),
        -- against its net once this return is reversed (checked above).
        ), returned_paid AS (
            SELECT refund.*,(app.refund_net_value_at(refund.id,'infinity')+earlier.amount)::bigint AS net,
                CASE WHEN refund.source_deposit_id IS NULL THEN 'CREDIT' ELSE 'DEPOSIT' END AS source_kind,
                COALESCE(refund.source_deposit_id,refund.source_customer_credit_id) AS source_id,
                CASE WHEN EXISTS(SELECT 1 FROM app.lease_signers signer
                    WHERE signer.lease_id=(SELECT settlement.lease_id FROM settlement)
                      AND signer.customer_id=refund.recipient_customer_id
                      AND signer.signed_at IS NOT NULL)
                    THEN (SELECT settlement.lease_id FROM settlement) END AS lease_id,
                refund.source_deposit_id IS NULL OR refund.recipient_customer_id=(SELECT deposit.customer_id
                    FROM app.deposits deposit WHERE deposit.id=refund.source_deposit_id) AS deposit_customer,
                0::bigint AS returns,parts.total AS share
            FROM earlier
            JOIN app.refunds refund ON refund.id=earlier.refund_id
            CROSS JOIN (SELECT COALESCE(sum(taken.part_usd_cents),0)::bigint AS total
                FROM swept_undone taken WHERE taken.record_kind='RETURNED_REFUND') parts
            WHERE parts.total>0
""",
    ),
    (
        """                    -- Sub-slice 10e-3d-2a: and each Refund part of another correction.
                    UNION ALL
                    SELECT swept_paid.* FROM swept_paid) paid),
""",
        """                    -- Sub-slice 10e-3d-2a: and each Refund part of another correction.
                    UNION ALL
                    SELECT swept_paid.* FROM swept_paid
                    -- Sub-slice 10e-3d-2c: and the returned Refund's charge-back.
                    UNION ALL
                    SELECT returned_paid.* FROM returned_paid) paid),
""",
    ),
)

ASSERT = "app.assert_settlement_return_reversal_allowed(jsonb)"
ASSERT_REPLACEMENTS = (
    (
        """            WHERE item->>'kind' IN ('CREDIT_REVERSAL','RECEIPT_REVERSAL'))
        THEN RAISE EXCEPTION 'A Credit reversal or a Deposit receipt reversal paid out this return''s money; reversing it waits for sub-slice 10e-3d-2c'
""",
        """            -- Sub-slice 10e-3d-2c: such a take is charged to the person who received the
            -- returned Refund, unless it cannot be followed (fail closed).
            WHERE item->>'kind' IN ('CREDIT_REVERSAL','RECEIPT_REVERSAL','RETURNED_REFUND'))
        THEN RAISE EXCEPTION 'A Credit reversal or a Deposit receipt reversal paid out this return''s money in a way this reversal cannot follow yet; reversing it waits for the owner'
""",
    ),
    (
        """                    WHERE application->>'id'=taken->>'record_id') END
                AND (taken->>'record_kind'='REFUND'
""",
        """                    WHERE application->>'id'=taken->>'record_id')
                -- Sub-slice 10e-3d-2c: a part of this return's own returned Refund, charged back
                -- in its one recovery entry, whose amount is every such part, no more than its net,
                -- and whose return count is 0 (the entry counts no return).
                WHEN 'RETURNED_REFUND' THEN taken->>'record_id'=p_source->'earlier'->>'refund_id'
                    AND (SELECT count(*)=1
                        AND bool_and((recovery->>'amount_usd_cents')::bigint
                                =(SELECT sum((part->>'part_usd_cents')::bigint)
                                    FROM jsonb_array_elements((p_source->'swept')
                                        ||CASE WHEN v_walk THEN p_source->'own_parts' ELSE '[]'::jsonb END) part
                                    WHERE part->>'record_kind'='RETURNED_REFUND')
                            AND (recovery->>'amount_usd_cents')::bigint
                                <=(recovery->>'net_usd_cents')::bigint
                            AND (recovery->>'returns')::bigint=0)
                    FROM jsonb_array_elements(p_source->'recoveries') recovery
                    WHERE recovery->>'refund_id'=taken->>'record_id') END
                AND (taken->>'record_kind' IN ('REFUND','RETURNED_REFUND')
""",
    ),
    (
        """            OR (SELECT count(*)<>count(DISTINCT item->>'record_id')
                FROM jsonb_array_elements((p_source->'swept')||(p_source->'own_parts')) item)
""",
        """            OR (SELECT count(*)<>count(DISTINCT item->>'record_id')
                FROM jsonb_array_elements((p_source->'swept')||(p_source->'own_parts')) item
                -- Sub-slice 10e-3d-2c: the returned Refund's parts share its one recovery entry.
                WHERE item->>'record_kind'<>'RETURNED_REFUND')
""",
    ),
    (
        """                    WHERE item->>'record_kind'='REFUND' AND item->>'record_id'=recovery->>'refund_id'))
""",
        """                    WHERE item->>'record_kind' IN ('REFUND','RETURNED_REFUND')
                      AND item->>'record_id'=recovery->>'refund_id'))
""",
    ),
)

SCOPE = "app.settlement_return_reversal_refund(uuid,uuid)"
SCOPE_REPLACEMENTS = (
    (
        """        SELECT COALESCE((SELECT EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
""",
        """        SELECT COALESCE((SELECT
                -- Sub-slice 10e-3d-2c (owner answer (a) to Q-2026-10-13-103 point 1): or the
                -- returned Refund itself, when the draft's source names a part of it charged back
                -- to its recipient and lists that recovery for its recipient.
                (p_refund::text=draft.payload->>'refund_id'
                    AND EXISTS(SELECT 1 FROM jsonb_array_elements((draft.payload->'source'->'swept')
                            ||CASE WHEN jsonb_typeof(draft.payload->'source'->'own_parts')='array'
                                THEN draft.payload->'source'->'own_parts' ELSE '[]'::jsonb END) taken
                        WHERE taken->>'record_kind'='RETURNED_REFUND'
                          AND taken->>'record_id'=p_refund::text)
                    AND EXISTS(SELECT 1 FROM app.refunds refund
                        JOIN jsonb_array_elements(draft.payload->'source'->'recoveries') item
                            ON item->>'refund_id'=refund.id::text
                        WHERE refund.id=p_refund
                          AND (refund.source_customer_credit_id::text=draft.payload->>'customer_credit_id'
                              OR refund.source_deposit_id::text=draft.payload->>'deposit_id')
                          AND item->>'recipient_customer_id'=refund.recipient_customer_id::text))
                OR EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
""",
    ),
)

CONFIRM = "app.confirm_settlement_return_reversal(uuid,uuid,uuid,text)"
CONFIRM_REPLACEMENTS = (
    (
        """        v_at:=app.write_payment_return_recoveries(p_property,p_actor,p_draft,v_correction,NULL,
            v_source->'recoveries',v_draft.reason,v_input->>'evidence_reference',v_at,v_evidence);
""",
        """        -- Sub-slice 10e-3d-2c: all but the returned Refund's own charge-back, written after
        -- its return is reversed (below).
        v_at:=app.write_payment_return_recoveries(p_property,p_actor,p_draft,v_correction,NULL,
            (SELECT COALESCE(jsonb_agg(entry.item ORDER BY entry.position),'[]'::jsonb)
                FROM jsonb_array_elements(v_source->'recoveries') WITH ORDINALITY entry(item,position)
                WHERE entry.item->>'refund_id' IS DISTINCT FROM v_source->'earlier'->>'refund_id'),
            v_draft.reason,v_input->>'evidence_reference',v_at,v_evidence);
""",
    ),
    (
        """            v_draft.reason,v_input->>'evidence_reference',v_at,p_actor,'refunds.corrections.reverse');
""",
        """            v_draft.reason,v_input->>'evidence_reference',v_at,p_actor,'refunds.corrections.reverse');
        -- Sub-slice 10e-3d-2c (owner answer (a) to Q-2026-10-13-103 point 1): the returned
        -- Refund's charge-back of the parts of this return's money that a bounced Payment's
        -- correction or a receipt correction took out of the source, now that its net again holds
        -- this return's amount; it brings that money back into the source, dated at this
        -- reversal (one point in the source's history, which the deferred history checks read).
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(v_source->'recoveries') item
            WHERE item->>'refund_id'=v_source->'earlier'->>'refund_id') THEN
            v_at:=app.write_payment_return_recoveries(p_property,p_actor,p_draft,v_correction,NULL,
                (SELECT jsonb_agg(item) FROM jsonb_array_elements(v_source->'recoveries') item
                    WHERE item->>'refund_id'=v_source->'earlier'->>'refund_id'),
                v_draft.reason,v_input->>'evidence_reference',v_at,
                v_evidence||jsonb_build_object('returned_refund_id',v_refund.id,
                    'returned_refund_at',v_at));
        END IF;
""",
    ),
)

GENERAL = "app.validate_general_refund_correction()"
GENERAL_REPLACEMENTS = (
    (
        """                OR NOT isfinite(NEW.occurred_at) OR NEW.occurred_at<=v_latest
""",
        """                OR NOT isfinite(NEW.occurred_at)
                -- Sub-slice 10e-3d-2c: the returned Refund's charge-back takes the time of the
                -- reversal of its return that the same correction wrote just before it, so the two
                -- make one point in the source's history; never earlier, and nothing else ties.
                OR NEW.occurred_at<v_latest
                OR NEW.occurred_at=v_latest
                    AND NOT app.settlement_return_reversal_paired_charge_back(NEW)
""",
    ),
    (
        """                IF (v_refund.source_deposit_id IS NULL AND v_payment.status<>'RECEIVED')
                    OR v_available< -NEW.source_balance_effect_usd_cents
""",
        """                -- Sub-slice 10e-3d-2c (owner answer (a) to Q-2026-10-13-103 point 1): inside
                -- the RETURN_REVERSAL that reverses this return, the same correction charges the
                -- returned Refund back right after this row for the money a bounced Payment's
                -- correction or a receipt correction took out of the source; that charge-back
                -- counts as available, and when it covers the whole reversal it also stands for a
                -- Payment that is no longer received.
                IF (v_refund.source_deposit_id IS NULL AND v_payment.status<>'RECEIVED'
                        AND app.settlement_return_reversal_charge_back(NEW)
                            < -NEW.source_balance_effect_usd_cents)
                    OR v_available+app.settlement_return_reversal_charge_back(NEW)
                        < -NEW.source_balance_effect_usd_cents
""",
    ),
)

WRITER = "app.write_payment_return_recoveries(uuid,uuid,uuid,uuid,uuid,jsonb,text,text,timestamp with time zone,jsonb)"
WRITER_REPLACEMENTS = (
    (
        """                p_evidence,v_at,p_actor,'financial.approve',(v_charge->>'obligation_id')::uuid);
""",
        """                -- Sub-slice 10e-3d-2c: the returned Refund's charge-back is dated at the reversal
                -- of its return (one point in the source's history); every other recovery as above.
                -- Review round 1 (security): only inside a RETURN_REVERSAL and only for the
                -- returned Refund the evidence names.
                p_evidence,COALESCE(CASE WHEN p_authorization_evidence->>'variant'='RETURN_REVERSAL'
                        AND p_authorization_evidence->>'returned_refund_id'=v_refund.id::text
                    THEN (p_authorization_evidence->>'returned_refund_at')::timestamptz END,v_at),
                p_actor,'financial.approve',(v_charge->>'obligation_id')::uuid);
""",
    ),
    (
        """            WHEN p_authorization_evidence->>'variant'='RETURN_REVERSAL'
            THEN 'value a mistaken Refund return brought back' ELSE 'a returned Payment' END;
""",
        """            -- Sub-slice 10e-3d-2c: the returned Refund itself, for the part of it whose return
            -- was recorded by mistake.
            WHEN p_authorization_evidence->>'variant'='RETURN_REVERSAL'
                AND p_authorization_evidence->>'returned_refund_id' IS NOT NULL
            THEN 'value whose return was recorded by mistake'
            WHEN p_authorization_evidence->>'variant'='RETURN_REVERSAL'
            THEN 'value a mistaken Refund return brought back' ELSE 'a returned Payment' END;
""",
    ),
)

PATCHES = (
    (PLACED, PLACED_REPLACEMENTS),
    (FOLLOW, FOLLOW_REPLACEMENTS),
    (SOURCE, SOURCE_REPLACEMENTS),
    (ASSERT, ASSERT_REPLACEMENTS),
    (SCOPE, SCOPE_REPLACEMENTS),
    (CONFIRM, CONFIRM_REPLACEMENTS),
    (GENERAL, GENERAL_REPLACEMENTS),
    (WRITER, WRITER_REPLACEMENTS),
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
                f"Settlement return reversal returned Refund contract changed: {signature}"
            )
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
    raise RuntimeError("Settlement return reversal returned Refund migration is forward-only")
