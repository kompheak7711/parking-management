# ruff: noqa: E501
"""A return reversal undoes another Lease's correction's Credit payment through a companion
correction of that Lease's Final Settlement (V1-056 sub-slice 10e-3d-2d-2a).

BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-006, BR-CREDIT-014, DL-032; DB-SETTLE-005; owner answers
(a) to Q-2026-10-13-100 point 2 ("when a reversal undoes a payment on that other Lease, that
Lease's history must show which correction undid it") and (a) to Q-2026-10-13-103 point 3 (a
companion correction of the other Lease's Settlement, recorded and confirmed together with the
reversal in one step). Since sub-slice 10e-3d-2d-1 a take of a return's money by a correction of
another Final Settlement B was one open part, and the return's reversal was refused.

- New internal `app.settlement_correction_companion_id(p_draft, p_settlement)` (the companion
  draft's id, derived from the reversal's draft and B) and
  `app.settlement_return_reversal_companion_source(p_source, p_settlement)` (B's slice of a
  reversal's stored source: its listed Credit applications and its parts applied again, in the
  source's order), and `app.settlement_credit_application_owner(p_application)` (the Final
  Settlement a Credit application belongs to: its own, or for an ordinary application such as the
  rest a REFUND correction writes again, the Final Settlement of its target's Lease; review round
  1). No grant.
- `app.settlement_returned_value_walk` (exact-text patches): a companion is part of its reversal.
  The corrections walked leave out companions, and every sum reads the effects of the correction
  and of its companions (worked out from the reversal draft's stored `companions`, with no scan of
  drafts), so the reversal's net draw is the money it really takes from the source.
- `app.settlement_returned_value_placed` (exact-text patch): the `OTHER_SETTLEMENT` part stays
  only for a take of another Settlement's correction that has a Refund from the source (its
  charge-back through the companion is sub-slice 10e-3d-2d-2b); otherwise that take is placed on
  its records as a take of this Settlement's. (A reversal taker is always opened by its return
  reversal record, so its companions' records need no merge here.)
- `app.settlement_returned_value_successor` and `app.settlement_returned_value_follow`
  (exact-text patches): only this Settlement's entries of a reversal's `reapply` are that
  correction's own put-backs, so the n-th of them is its n-th linked put-back.
- `app.settlement_return_reversal_source_state` (exact-text patch): the new key `companions` lists
  each other Final Settlement whose correction's Credit application is listed for undoing.
- `app.assert_settlement_return_reversal_allowed` (exact-text patch): exactly one companion entry
  per such Settlement, each closed and of this Settlement's Property ("The return reversal source is
  incomplete" otherwise).
- `app.confirm_settlement_return_reversal` (exact-text patches): the Settlement draft locks of this
  Settlement and every companion's in Settlement id order, then their invoice-lease locks and Lease
  rows in Lease id order, before the lock function; after the reversal's header one companion per
  entry (its draft through `app.insert_financial_draft` by the approver under
  `final_settlements.prepare` with the reversal's reason, then its decision and header through
  `app.begin_settlement_correction`); another Settlement's Credit application reversal is linked to
  that Settlement's companion; a part of it applied again goes back on its own line through
  `app.post_final_settlement_credit_application` with the companion's draft; an audit event per
  companion on its Lease, naming the reversal.
- `app.settlement_return_reversal_result` (exact-text patch): the new key `companions`.
- `app.post_final_settlement_credit_application`, `app.assert_settlement_correction_credit_application`
  and `app.settlement_correction_put_back_allowed` (exact-text patches): the put-back rules of a
  return reversal also hold for its companion (variant `RETURN_REVERSAL_COMPANION`), which reads its
  own draft's `source` and `plan`.

Beyond that ranking, the follow function still stops open (`CHANGED_APPLICATION`) at a payment of
the other Lease that one of its corrections, a companion included, changed, so a later reversal
of another return whose money sat in it is refused (fail closed). The successor function has had
no caller since migration 134 (the source function calls the follow function); its patch is
tested directly. No table, column, constraint, trigger or
grant change. A `RETURN_REVERSAL` draft recorded before this migration has no `companions` key in
its stored source, so it is stale at its confirm (P5S02); staff reject it and record it again.
"""

from alembic import op
from sqlalchemy import text

revision = "20261212_138"
down_revision = "20261211_137"
branch_labels = None
depends_on = None

COMPANION_ID = "app.settlement_correction_companion_id(uuid,uuid)"
COMPANION_SOURCE = "app.settlement_return_reversal_companion_source(jsonb,uuid)"
OWNER = "app.settlement_credit_application_owner(uuid)"
INTERNAL = (OWNER, COMPANION_ID, COMPANION_SOURCE)

FUNCTION_SQL = """
    -- The Final Settlement a Credit application belongs to: its own Final Settlement, or, for
    -- an ordinary application (the rest a REFUND correction writes again has none), the Final
    -- Settlement of its target's Lease; NULL when it has neither (review round 1).
    CREATE FUNCTION app.settlement_credit_application_owner(p_application uuid)
    RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE(application.final_settlement_id,settlement.id)
        FROM app.customer_credit_applications application
        LEFT JOIN app.late_payment_charges charge ON charge.id=application.late_payment_charge_id
        LEFT JOIN app.invoices invoice
            ON invoice.id=COALESCE(application.invoice_id,charge.source_invoice_id)
        LEFT JOIN app.final_settlements settlement ON settlement.lease_id=invoice.lease_id
        WHERE application.id=p_application
    $$;

    -- The companion draft of a return reversal for another Final Settlement: its id is derived
    -- from the reversal's draft and that Settlement, so the reversal and its companion name each
    -- other without a stored link.
    CREATE FUNCTION app.settlement_correction_companion_id(p_draft uuid,p_settlement uuid)
    RETURNS uuid LANGUAGE sql IMMUTABLE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT md5('settlement-correction-companion:' || p_draft::text || ':'
            || p_settlement::text)::uuid
    $$;

    -- Another Final Settlement's slice of a return reversal's source: its listed Credit
    -- applications and its parts applied again, in the source's order (the n-th part applied
    -- again is the n-th step of the companion's plan).
    CREATE FUNCTION app.settlement_return_reversal_companion_source(p_source jsonb,p_settlement uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT jsonb_build_object(
            'credit_applications',(SELECT COALESCE(jsonb_agg(entry.item ORDER BY entry.position),
                    '[]'::jsonb)
                FROM jsonb_array_elements(CASE WHEN jsonb_typeof(p_source->'credit_applications')='array'
                    THEN p_source->'credit_applications' ELSE '[]'::jsonb END)
                    WITH ORDINALITY entry(item,position)
                WHERE app.settlement_credit_application_owner((entry.item->>'id')::uuid)
                    =p_settlement),
            'reapply',(SELECT COALESCE(jsonb_agg(entry.item ORDER BY entry.position),'[]'::jsonb)
                FROM jsonb_array_elements(CASE WHEN jsonb_typeof(p_source->'reapply')='array'
                    THEN p_source->'reapply' ELSE '[]'::jsonb END) WITH ORDINALITY entry(item,position)
                WHERE entry.item->>'source_kind'='CREDIT'
                  AND app.settlement_credit_application_owner((entry.item->>'application_id')::uuid)
                      =p_settlement))
    $$;
"""

# Review round 1 (speed): a return reversal's companion corrections, worked out from its stored
# source's `companions` (the confirm writes one companion per entry), with no scan of drafts.
COMPANIONS_OF_DRAFT = """ARRAY(SELECT app.settlement_correction_id(
                    app.settlement_correction_companion_id(draft.id,(item->>'final_settlement_id')::uuid))
                FROM jsonb_array_elements(CASE WHEN jsonb_typeof(draft.payload->'source'->'companions')='array'
                    THEN draft.payload->'source'->'companions' ELSE '[]'::jsonb END) item)"""

WALK = "app.settlement_returned_value_walk(uuid,text,uuid,uuid)"
WALK_REPLACEMENTS = (
    (
        """
        v_offset bigint; v_named integer; v_index integer; v_position integer:=0;""",
        """
        v_offset bigint; v_named integer; v_index integer; v_position integer:=0;
        v_members uuid[];""",
        1,
    ),
    (
        """
              AND correction.id IS DISTINCT FROM p_except
            ORDER BY correction.occurred_at,correction.id""",
        """
              AND correction.id IS DISTINCT FROM p_except
              -- Sub-slice 10e-3d-2d-2a: a companion is part of its return reversal.
              AND draft.payload->>'variant' IS DISTINCT FROM 'RETURN_REVERSAL_COMPANION'
            ORDER BY correction.occurred_at,correction.id""",
        1,
    ),
    (
        """
                CASE WHEN draft.payload->>'variant' IN ('HELD_VALUE_REFUND','RETURN_REVERSAL')
                    THEN draft.payload->>'held_from_settlement_correction_id' END AS named""",
        """
                CASE WHEN draft.payload->>'variant' IN ('HELD_VALUE_REFUND','RETURN_REVERSAL')
                    THEN draft.payload->>'held_from_settlement_correction_id' END AS named,
                -- Sub-slice 10e-3d-2d-2a: a return reversal's companions.
                CASE WHEN draft.payload->>'variant'='RETURN_REVERSAL' THEN """
        + COMPANIONS_OF_DRAFT
        + """
                    ELSE '{}'::uuid[] END AS companions""",
        1,
    ),
    (
        """
        LOOP
            SELECT COALESCE(sum(returned.source_balance_effect_usd_cents),0) INTO v_return""",
        """
        LOOP
            -- Sub-slice 10e-3d-2d-2a (owner answer (a) to Q-2026-10-13-103 point 3): the records
            -- of a return reversal's companions on other Final Settlements are the reversal's, so
            -- its net draw is the money it really takes from the source.
            v_members:=ARRAY[v_correction.id]||v_correction.companions;
            SELECT COALESCE(sum(returned.source_balance_effect_usd_cents),0) INTO v_return""",
        1,
    ),
    (
        "effect.settlement_correction_id=v_correction.id",
        "effect.settlement_correction_id=ANY(v_members)",
        13,
    ),
)

PLACED = "app.settlement_returned_value_placed(uuid,text,uuid,uuid,boolean)"
PLACED_REPLACEMENTS = (
    (
        """
                WHERE taker_correction.final_settlement_id<>p_settlement
                UNION ALL""",
        """
                WHERE taker_correction.final_settlement_id<>p_settlement
                  -- Sub-slice 10e-3d-2d-2a: only while the take has a Refund from the source (its
                  -- charge-back through the companion is sub-slice 10e-3d-2d-2b); its Credit
                  -- applications are placed and undone through a companion correction.
                  AND (p_kind<>'CREDIT' OR EXISTS(SELECT 1 FROM effects
                      JOIN app.refunds refund ON refund.id=effects.refund_id
                      WHERE effects.taker=taken.taker
                        AND refund.source_customer_credit_id=p_source))
                UNION ALL""",
        1,
    ),
)

STATE = "app.settlement_return_reversal_source_state(uuid,uuid)"
STATE_REPLACEMENTS = (
    (
        """
            'linked',(SELECT COALESCE(jsonb_agg(users.id ORDER BY users.id),'[]'::jsonb) FROM users
                WHERE users.id<>p_earlier),""",
        """
            'linked',(SELECT COALESCE(jsonb_agg(users.id ORDER BY users.id),'[]'::jsonb) FROM users
                WHERE users.id<>p_earlier),
            -- Sub-slice 10e-3d-2d-2a (owner answer (a) to Q-2026-10-13-103 point 3): each other
            -- Final Settlement whose correction's Credit application this reversal undoes; the
            -- confirm writes one companion correction of it.
            'companions',(SELECT COALESCE(jsonb_agg(jsonb_build_object('final_settlement_id',other.id,
                    'lease_id',other.lease_id,'property_id',other.property_id,
                    'closed',other.closed_at IS NOT NULL) ORDER BY other.id),'[]'::jsonb)
                FROM app.final_settlements other
                WHERE other.id<>p_settlement AND other.id IN (SELECT
                        app.settlement_credit_application_owner(taken.record_id)
                    FROM swept_undone taken WHERE taken.record_kind='CREDIT_APPLICATION')),""",
        1,
    ),
)

ASSERT = "app.assert_settlement_return_reversal_allowed(jsonb)"
ASSERT_REPLACEMENTS = (
    (
        """
        THEN RAISE EXCEPTION 'A correction of another Lease''s Final Settlement used this return''s money; reversing it waits for sub-slice 10e-3d-2d-2'
            USING ERRCODE='55000'; END IF;""",
        """
        THEN RAISE EXCEPTION 'A correction of another Lease''s Final Settlement used this return''s money; reversing it waits for sub-slice 10e-3d-2d-2'
            USING ERRCODE='55000'; END IF;
        -- Sub-slice 10e-3d-2d-2a (owner answer (a) to Q-2026-10-13-103 point 3): exactly one
        -- companion entry per other Final Settlement whose Credit application is listed, each
        -- closed and of this Settlement's Property (fail closed).
        IF (p_source->'companions' IS NOT NULL
                AND jsonb_typeof(p_source->'companions') IS DISTINCT FROM 'array')
            OR EXISTS(SELECT 1 FROM jsonb_array_elements(CASE
                    WHEN jsonb_typeof(p_source->'companions')='array'
                    THEN p_source->'companions' ELSE '[]'::jsonb END) item
                WHERE NOT COALESCE((item->>'closed')::boolean,false)
                   OR item->>'final_settlement_id' IS NOT DISTINCT FROM p_source->'settlement'->>'id'
                   OR NOT EXISTS(SELECT 1 FROM app.final_settlements other
                       JOIN app.final_settlements settlement
                           ON settlement.id::text=p_source->'settlement'->>'id'
                       WHERE other.id::text=item->>'final_settlement_id'
                         AND other.closed_at IS NOT NULL
                         AND other.property_id=settlement.property_id
                         AND other.lease_id::text IS NOT DISTINCT FROM item->>'lease_id'
                         AND other.property_id::text IS NOT DISTINCT FROM item->>'property_id'))
            OR (SELECT COALESCE(array_agg(item->>'final_settlement_id'
                    ORDER BY item->>'final_settlement_id'),'{}'::text[])
                FROM jsonb_array_elements(CASE WHEN jsonb_typeof(p_source->'companions')='array'
                    THEN p_source->'companions' ELSE '[]'::jsonb END) item)
                IS DISTINCT FROM (SELECT COALESCE(array_agg(DISTINCT owned.owner
                        ORDER BY owned.owner),'{}'::text[])
                    FROM jsonb_array_elements(p_source->'credit_applications') item
                    JOIN app.customer_credit_applications application
                        ON application.id::text=item->>'id'
                    -- Review round 1: an ordinary application (no Final Settlement of its own)
                    -- belongs to the Final Settlement of its target's Lease; one with neither is
                    -- refused here.
                    CROSS JOIN LATERAL (SELECT
                        app.settlement_credit_application_owner(application.id)::text AS owner) owned
                    WHERE owned.owner IS DISTINCT FROM p_source->'settlement'->>'id')
        THEN RAISE EXCEPTION 'The return reversal source is incomplete' USING ERRCODE='55000'; END IF;""",
        1,
    ),
)

CONFIRM = "app.confirm_settlement_return_reversal(uuid,uuid,uuid,text)"
CONFIRM_REPLACEMENTS = (
    (
        """
        v_reapply jsonb; v_reapplied uuid; v_order integer; v_step integer;""",
        """
        v_reapply jsonb; v_reapplied uuid; v_order integer; v_step integer;
        v_companion jsonb; v_companions jsonb:='{}'::jsonb; v_other uuid; v_others uuid[];
        v_companion_step integer;""",
        1,
    ),
    (
        """
        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));
        PERFORM pg_advisory_xact_lock(hashtextextended('invoice-lease:' || v_settlement.lease_id::text,0));
        PERFORM 1 FROM app.leases WHERE id=v_settlement.lease_id FOR UPDATE;
        PERFORM app.lock_settlement_correction_plan(p_draft);""",
        """
        -- Sub-slice 10e-3d-2d-2a: with companions (the stored source names their Settlements),
        -- the Settlement draft locks of this Settlement and of each companion's in Settlement id
        -- order, then their invoice-lease locks and Lease rows in Lease id order, all before the
        -- lock function; every other writer on a companion's Lease takes its Settlement draft lock
        -- before the Credit, so no wait crosses. A changed set makes the source stale below.
        v_others:=ARRAY(SELECT other.id FROM app.final_settlements other
            WHERE other.id=v_settlement.id OR (other.property_id=p_property
                AND other.id::text IN (SELECT item->>'final_settlement_id'
                    FROM jsonb_array_elements(CASE
                        WHEN jsonb_typeof(v_draft.payload->'source'->'companions')='array'
                        THEN v_draft.payload->'source'->'companions' ELSE '[]'::jsonb END) item))
            ORDER BY other.id);
        FOREACH v_other IN ARRAY v_others LOOP
            PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_other::text,0));
        END LOOP;
        FOR v_other IN SELECT other.lease_id FROM app.final_settlements other
            WHERE other.id=ANY(v_others) ORDER BY other.lease_id
        LOOP
            PERFORM pg_advisory_xact_lock(hashtextextended('invoice-lease:' || v_other::text,0));
        END LOOP;
        FOR v_other IN SELECT other.lease_id FROM app.final_settlements other
            WHERE other.id=ANY(v_others) ORDER BY other.lease_id
        LOOP
            PERFORM 1 FROM app.leases WHERE id=v_other FOR UPDATE;
        END LOOP;
        PERFORM app.lock_settlement_correction_plan(p_draft);""",
        1,
    ),
    (
        """
            'variant','RETURN_REVERSAL','held_from_settlement_correction_id',v_earlier);
        v_at:=clock_timestamp();""",
        """
            'variant','RETURN_REVERSAL','held_from_settlement_correction_id',v_earlier);
        v_at:=clock_timestamp();
        -- Sub-slice 10e-3d-2d-2a (owner answer (a) to Q-2026-10-13-103 point 3): one companion
        -- correction of each other Final Settlement whose correction's Credit application this
        -- reversal undoes, recorded and confirmed here by the same approver, so that Lease's own
        -- correction list shows which correction undid it. Its draft carries its slice of the
        -- source and its put-back steps and names this reversal, which names it in its result.
        FOR v_companion IN SELECT item FROM jsonb_array_elements(v_source->'companions') item
            ORDER BY item->>'final_settlement_id'
        LOOP
            v_other:=(v_companion->>'final_settlement_id')::uuid;
            PERFORM app.insert_financial_draft(p_property,p_actor,
                app.settlement_correction_companion_id(p_draft,v_other),'SETTLEMENT_CORRECTION',
                'final_settlements.prepare',jsonb_build_object('variant','RETURN_REVERSAL_COMPANION',
                    'final_settlement_id',v_other,'lease_id',v_companion->'lease_id',
                    'return_reversal_draft_id',p_draft,'return_reversal_correction_id',v_correction,
                    'source',app.settlement_return_reversal_companion_source(v_source,v_other),
                    'plan',jsonb_build_object('steps',app.settlement_return_reversal_reapply_steps(
                        app.settlement_return_reversal_companion_source(v_source,v_other)))),
                NULL,v_draft.reason);
            v_companions:=v_companions||jsonb_build_object(v_other::text,
                app.begin_settlement_correction(p_property,p_actor,
                    app.settlement_correction_companion_id(p_draft,v_other),'financial.approve'));
            -- Review round 1: the records below are later than every companion header.
            v_at:=GREATEST(v_at,(SELECT correction.occurred_at FROM app.settlement_corrections correction
                WHERE correction.id=(v_companions->>v_other::text)::uuid));
        END LOOP;""",
        1,
    ),
    (
        """
            PERFORM app.link_settlement_correction_effect(v_correction,'credit_application_reversal_id',v_new);""",
        """
            -- Sub-slice 10e-3d-2d-2a: another Settlement's application is linked to its companion.
            PERFORM app.link_settlement_correction_effect(COALESCE((v_companions->>(
                    app.settlement_credit_application_owner(v_row.id)::text))::uuid,v_correction),
                'credit_application_reversal_id',v_new);""",
        1,
    ),
    (
        """
        IF v_reapply->>'source_kind'='CREDIT' THEN
            v_at:=GREATEST(v_at,(app.post_final_settlement_credit_application(p_property,p_actor,
                v_settlement.id,p_draft,v_step)->>'occurred_at')::timestamptz);""",
        """
        IF v_reapply->>'source_kind'='CREDIT' THEN
            -- Sub-slice 10e-3d-2d-2a: a part of another Settlement's application goes back on its
            -- own line through that Settlement's companion, as the n-th step of the companion's
            -- plan (its n-th part applied again).
            v_other:=app.settlement_credit_application_owner((v_reapply->>'application_id')::uuid);
            IF v_other IS DISTINCT FROM v_settlement.id THEN
                SELECT count(*) INTO v_companion_step
                FROM jsonb_array_elements(v_source->'reapply') WITH ORDINALITY entry(item,position)
                WHERE entry.position<=v_step AND entry.item->>'source_kind'='CREDIT'
                  AND app.settlement_credit_application_owner((entry.item->>'application_id')::uuid)
                      IS NOT DISTINCT FROM v_other;
                v_at:=GREATEST(v_at,(app.post_final_settlement_credit_application(p_property,p_actor,
                    v_other,app.settlement_correction_companion_id(p_draft,v_other),
                    v_companion_step)->>'occurred_at')::timestamptz);
            ELSE
            v_at:=GREATEST(v_at,(app.post_final_settlement_credit_application(p_property,p_actor,
                v_settlement.id,p_draft,v_step)->>'occurred_at')::timestamptz);
            END IF;""",
        1,
    ),
    (
        """
                -- Sub-slice 10e-3c: the part applied again.
                'reapplied',v_result->'reapplied'),""",
        """
                -- Sub-slice 10e-3c: the part applied again.
                'reapplied',v_result->'reapplied',
                -- Sub-slice 10e-3d-2d-2a: the companion corrections of other Settlements.
                'companions',(SELECT COALESCE(jsonb_agg(item->'settlement_correction_id'),'[]'::jsonb)
                    FROM jsonb_array_elements(v_result->'companions') item)),""",
        1,
    ),
    (
        """
            v_correction,'API','SUCCEEDED',v_evidence,v_refund.recipient_customer_id,v_settlement.lease_id,
            v_unit);
        RETURN v_result;""",
        """
            v_correction,'API','SUCCEEDED',v_evidence,v_refund.recipient_customer_id,v_settlement.lease_id,
            v_unit);
        -- Sub-slice 10e-3d-2d-2a: each companion's own audit event on its Lease, naming this
        -- reversal.
        FOR v_companion IN SELECT item FROM jsonb_array_elements(v_result->'companions') item
        LOOP
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
                entity_id,reason,authorization_reference,property_id,previous_state,resulting_state,
                correlation_id,source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
            VALUES (gen_random_uuid(),v_at,timezone(v_timezone,v_at)::date,p_actor,
                'final_settlement.correction.confirmed','settlement_correction',
                (v_companion->>'settlement_correction_id')::uuid,v_draft.reason,'financial.approve',
                p_property,'{}'::jsonb,
                jsonb_build_object('settlement_correction_id',v_companion->'settlement_correction_id',
                    'final_settlement_id',v_companion->'final_settlement_id',
                    'variant','RETURN_REVERSAL_COMPANION',
                    'return_reversal_settlement_correction_id',v_correction,
                    'credit_application_reversal_ids',(SELECT COALESCE(jsonb_agg(item->'id'),'[]'::jsonb)
                        FROM jsonb_array_elements(v_companion->'credit_application_reversals') item),
                    'reapplied',v_companion->'reapplied'),
                (v_companion->>'settlement_correction_id')::uuid,'API','SUCCEEDED',
                v_evidence||jsonb_build_object('settlement_correction_id',
                    v_companion->'settlement_correction_id','final_settlement_id',
                    v_companion->'final_settlement_id','variant','RETURN_REVERSAL_COMPANION',
                    'draft_id',v_companion->'draft_id','return_reversal_draft_id',p_draft),
                v_refund.recipient_customer_id,(v_companion->>'lease_id')::uuid,
                (SELECT lease.unit_id FROM app.leases lease
                    WHERE lease.id=(v_companion->>'lease_id')::uuid));
        END LOOP;
        RETURN v_result;""",
        1,
    ),
)

RESULT = "app.settlement_return_reversal_result(uuid)"
RESULT_REPLACEMENTS = (
    (
        """
                  AND recovery.correction_kind='RECOVERED_BY_CHARGE'))
        FROM app.financial_drafts draft WHERE draft.id=p_draft""",
        """
                  AND recovery.correction_kind='RECOVERED_BY_CHARGE'),
            -- Sub-slice 10e-3d-2d-2a: the companion corrections of other Final Settlements, each
            -- with its Credit application reversals and parts applied again.
            'companions',(SELECT COALESCE(jsonb_agg(jsonb_build_object(
                    'settlement_correction_id',companion.id,'draft_id',companion.correlation_id,
                    'final_settlement_id',companion.final_settlement_id,'lease_id',other.lease_id,
                    'occurred_at',companion.occurred_at,
                    'credit_application_reversals',(SELECT COALESCE(jsonb_agg(jsonb_build_object(
                            'id',reversal.id,'credit_application_id',reversal.credit_application_id,
                            'customer_credit_id',application.customer_credit_id,
                            'invoice_id',application.invoice_id,
                            'late_payment_charge_id',application.late_payment_charge_id,
                            'amount_usd_cents',application.amount_usd_cents,
                            'occurred_at',reversal.occurred_at)
                            ORDER BY effect.effect_sequence),'[]'::jsonb)
                        FROM app.settlement_correction_effects effect
                        JOIN app.customer_credit_application_reversals reversal
                            ON reversal.id=effect.credit_application_reversal_id
                        JOIN app.customer_credit_applications application
                            ON application.id=reversal.credit_application_id
                        WHERE effect.settlement_correction_id=companion.id),
                    'reapplied',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',credit_use.id,
                            'source_kind','CREDIT','customer_credit_id',credit_use.customer_credit_id,
                            'invoice_id',credit_use.invoice_id,'invoice_line_id',detail.invoice_line_id,
                            'late_payment_charge_id',credit_use.late_payment_charge_id,
                            'amount_usd_cents',credit_use.amount_usd_cents,
                            'within_invoice_basis',credit_use.within_invoice_basis,
                            'occurred_at',credit_use.occurred_at)
                            ORDER BY effect.effect_sequence),'[]'::jsonb)
                        FROM app.settlement_correction_effects effect
                        JOIN app.customer_credit_applications credit_use
                            ON credit_use.id=effect.customer_credit_application_id
                        LEFT JOIN app.customer_credit_application_details detail
                            ON detail.customer_credit_application_id=credit_use.id
                        WHERE effect.settlement_correction_id=companion.id))
                    ORDER BY companion.final_settlement_id),'[]'::jsonb)
                FROM app.settlement_corrections companion
                JOIN app.financial_drafts companion_draft ON companion_draft.id=companion.correlation_id
                    AND companion_draft.kind='SETTLEMENT_CORRECTION'
                    AND companion_draft.payload->>'variant'='RETURN_REVERSAL_COMPANION'
                JOIN app.final_settlements other ON other.id=companion.final_settlement_id
                WHERE companion_draft.payload->>'return_reversal_correction_id'
                    =app.settlement_correction_id(draft.id)::text))
        FROM app.financial_drafts draft WHERE draft.id=p_draft""",
        1,
    ),
)

POST = (
    "app.post_final_settlement_credit_application(uuid,uuid,uuid,uuid,integer)"
)
POST_REPLACEMENTS = (
    (
        """
            IF v_draft.kind='SETTLEMENT_CORRECTION' AND v_draft.payload->>'variant'='RETURN_REVERSAL' THEN""",
        """
            -- Sub-slice 10e-3d-2d-2a: also its companion on another Final Settlement.
            IF v_draft.kind='SETTLEMENT_CORRECTION'
                AND v_draft.payload->>'variant' IN ('RETURN_REVERSAL','RETURN_REVERSAL_COMPANION') THEN""",
        1,
    ),
)

APPLICATION = "app.assert_settlement_correction_credit_application(app.customer_credit_applications)"
APPLICATION_REPLACEMENTS = (
    (
        """
                      WHEN v_variant='RETURN_REVERSAL' AND EXISTS(SELECT 1 FROM app.invoice_lines line""",
        """
                      -- Sub-slice 10e-3d-2d-2a: also its companion on another Final Settlement.
                      WHEN v_variant IN ('RETURN_REVERSAL','RETURN_REVERSAL_COMPANION')
                          AND EXISTS(SELECT 1 FROM app.invoice_lines line""",
        1,
    ),
)

PUT_BACK = (
    "app.settlement_correction_put_back_allowed(uuid,app.customer_credit_applications,"
    "app.customer_credit_application_details,integer)"
)
PUT_BACK_REPLACEMENTS = (
    (
        """
        SELECT COALESCE(CASE WHEN (SELECT payload->>'variant' FROM draft)
                IS DISTINCT FROM 'RETURN_REVERSAL'""",
        """
        -- Sub-slice 10e-3d-2d-2a: also a return reversal's companion, from its own draft.
        SELECT COALESCE(CASE WHEN COALESCE((SELECT payload->>'variant' FROM draft),'')
                NOT IN ('RETURN_REVERSAL','RETURN_REVERSAL_COMPANION')""",
        1,
    ),
)

# Review round 1: a return reversal's `reapply` also lists the entries of other Settlements'
# records, whose put-backs are linked to their companions, so the n-th entry of this Settlement is
# this correction's n-th linked put-back.
SUCCESSOR = "app.settlement_returned_value_successor(text,uuid)"
SUCCESSOR_REPLACEMENTS = (
    (
        """
            WHERE entry.item->>'application_id'=v_current::text AND entry.item->>'source_kind'=p_kind;
            IF v_entry IS NULL THEN RETURN NULL; END IF;""",
        """
            WHERE entry.item->>'application_id'=v_current::text AND entry.item->>'source_kind'=p_kind;
            IF v_entry IS NULL THEN RETURN NULL; END IF;
            -- Sub-slice 10e-3d-2d-2a: only this Settlement's entries are this correction's
            -- put-backs (another Settlement's go back through its companion).
            v_position:=(SELECT count(*) FROM jsonb_array_elements(v_source->'reapply')
                    WITH ORDINALITY entry(item,position)
                WHERE entry.position<=v_position AND (entry.item->>'source_kind'<>'CREDIT'
                    OR app.settlement_credit_application_owner((entry.item->>'application_id')::uuid)
                        IS NOT DISTINCT FROM (SELECT correction.final_settlement_id
                            FROM app.settlement_corrections correction
                            WHERE correction.id=v_correction)));""",
        1,
    ),
)

FOLLOW = "app.settlement_returned_value_follow(uuid,text,uuid,text,uuid,bigint,bigint,uuid)"
FOLLOW_REPLACEMENTS = (
    (
        """
                    WHERE entry.item->>'application_id'=v_record::text AND entry.item->>'source_kind'=p_kind;
                END IF;""",
        """
                    WHERE entry.item->>'application_id'=v_record::text AND entry.item->>'source_kind'=p_kind;
                END IF;
                -- Sub-slice 10e-3d-2d-2a: only this Settlement's entries are this correction's
                -- put-backs (another Settlement's go back through its companion).
                IF v_entry IS NOT NULL THEN
                    v_position:=(SELECT count(*) FROM jsonb_array_elements(v_source->'reapply')
                            WITH ORDINALITY entry(item,position)
                        WHERE entry.position<=v_position AND (entry.item->>'source_kind'<>'CREDIT'
                            OR app.settlement_credit_application_owner(
                                (entry.item->>'application_id')::uuid) IS NOT DISTINCT FROM p_settlement));
                END IF;""",
        1,
    ),
)

PATCHES = (
    (WALK, WALK_REPLACEMENTS),
    (SUCCESSOR, SUCCESSOR_REPLACEMENTS),
    (FOLLOW, FOLLOW_REPLACEMENTS),
    (PLACED, PLACED_REPLACEMENTS),
    (STATE, STATE_REPLACEMENTS),
    (ASSERT, ASSERT_REPLACEMENTS),
    (CONFIRM, CONFIRM_REPLACEMENTS),
    (RESULT, RESULT_REPLACEMENTS),
    (POST, POST_REPLACEMENTS),
    (APPLICATION, APPLICATION_REPLACEMENTS),
    (PUT_BACK, PUT_BACK_REPLACEMENTS),
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
            raise RuntimeError(f"Return reversal companion contract changed: {signature}")
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
    raise RuntimeError("Return reversal companion migration is forward-only")
