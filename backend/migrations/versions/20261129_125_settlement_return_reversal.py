# ruff: noqa: E501
"""A return recorded by mistake after closure (V1-056 sub-slice 10e-3, `RETURN_REVERSAL`).

BR-SETTLE-013, BR-SETTLE-016, DL-032, BR-REFUND-015, BR-CREDIT-008, BR-AUTH-010; DB-REFUND-002,
DB-SETTLE-005; owner answer (a) to Q-2026-10-08-57 and the Q-2026-10-11-78 rule (the person who
received the refund money pays it back):

- A new variant `RETURN_REVERSAL` of the `SETTLEMENT_CORRECTION` draft kind names one return that an
  earlier `REFUND_RETURN` correction of the same closed Final Settlement recorded by mistake.
  `final_settlements.prepare` records it with a reason and evidence; only `financial.approve`
  confirms it.
- In one transaction, each record linked to the correction before it is written: the uses of the
  returned Refund's own source (its Credit, or its Deposit) by the earlier correction and by every
  `HELD_VALUE_REFUND` that names it are undone (their Credit applications and Deposit
  applications are reversed, newest first, so the debt comes back on its obligations and stays
  with their Customers, BR-SETTLE-016); each of their Refunds from that source that still has a
  net value is recovered by a charge of the exact net amount to the person who received it (the
  sub-slice 10e-1c writer: an `EXTRA_CHARGE` on this Lease when that person is its signed
  Customer, else a no-Lease charge); then the return itself is reversed (a `CORRECTION_REVERSAL`
  row). No DL-032 step.
- Refused (55000): a return already reversed; a Refund to recover that has its own return; a
  Refund to recover paid to someone other than the Deposit's own Customer (Q-2026-10-12-94, until
  the owner answers); uses to undo that are more than the returned amount (Q-2026-10-12-95, until
  the owner answers); a returned value no longer available because another path used it.

Relaxing changes only: the general Refund correction check accepts the linked reversal row (and
reads a Deposit Refund's source by `source_deposit_id` in its reversal branch, so an
over-reversal of any Deposit Refund is refused); the recovery check accepts a recovery linked to
the confirmed reversal; the recovery writer words its charge; the correction lock function gains
a branch; the left value of an earlier return-only correction counts a reversed return as 0 (a
state no path reached before this migration).
"""

from alembic import op
from sqlalchemy import text

revision = "20261129_125"
down_revision = "20261128_124"
branch_labels = None
depends_on = None

FUNCTION_SQL = r"""
    -- Sub-slice 10e-3: the input of a RETURN_REVERSAL draft: the earlier correction and the
    -- evidence that the return never happened.
    CREATE FUNCTION app.settlement_return_reversal_input(p_input jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_earlier text;
    BEGIN
        IF p_input IS NULL OR jsonb_typeof(p_input) IS DISTINCT FROM 'object'
            -- The byte order, whatever the database collation.
            OR (SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(p_input) key)
                IS DISTINCT FROM ARRAY['evidence_reference','settlement_correction_id']
        THEN RAISE EXCEPTION 'Return reversal correction input is invalid' USING ERRCODE='22023'; END IF;
        v_earlier:=app.final_settlement_plan_id(p_input->'settlement_correction_id');
        IF v_earlier IS NULL
            OR jsonb_typeof(p_input->'evidence_reference') IS DISTINCT FROM 'string'
            OR app.lease_notice_text_valid(p_input->>'evidence_reference',500) IS NOT TRUE
        THEN RAISE EXCEPTION 'Return reversal correction input is invalid' USING ERRCODE='22023'; END IF;
        RETURN jsonb_build_object('settlement_correction_id',v_earlier,
            'evidence_reference',p_input->>'evidence_reference');
    END $$;

    -- Sub-slice 10e-3: the earlier correction and every confirmed HELD_VALUE_REFUND correction
    -- that names it (a correction header exists only once its draft is confirmed).
    CREATE FUNCTION app.settlement_return_reversal_users(p_earlier uuid)
    RETURNS uuid[] LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT array_agg(users.id ORDER BY users.id) FROM (
            SELECT p_earlier AS id
            UNION SELECT later.id FROM app.settlement_corrections later
            JOIN app.financial_drafts draft
                ON draft.id=later.correlation_id AND draft.kind='SETTLEMENT_CORRECTION'
            WHERE draft.payload->>'variant'='HELD_VALUE_REFUND'
              AND draft.payload->>'held_from_settlement_correction_id'=p_earlier::text) users
    $$;

    -- Sub-slice 10e-3: what a RETURN_REVERSAL of the earlier correction undoes, read from the
    -- current state: the earlier correction's return (the returned Refund, its own Credit or
    -- Deposit, the amount, whether it is reversed); the active Credit applications from that
    -- Credit and the active Deposit applications from that Deposit that the earlier correction or
    -- a HELD_VALUE_REFUND naming it wrote, newest first; their Refunds from that source with a net
    -- value (each charged back to the person who received it: this Lease when that person is its
    -- signed Customer, else no Lease); and the source's value now. Records they wrote from any
    -- other Credit or Deposit are real money paid to real debt and stay.
    CREATE FUNCTION app.settlement_return_reversal_source_state(p_settlement uuid, p_earlier uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET "TimeZone"='UTC' AS $$
        WITH settlement AS (
            SELECT settlement.* FROM app.final_settlements settlement WHERE settlement.id=p_settlement
        ), earlier AS (
            SELECT correction.id,correction.correlation_id AS draft_id,returned.id AS return_id,
                returned.refund_id,returned.source_balance_effect_usd_cents AS amount,
                refund.source_customer_credit_id AS credit_id,refund.source_deposit_id AS deposit_id,
                EXISTS(SELECT 1 FROM app.refund_corrections reversal
                    WHERE reversal.reverses_correction_id=returned.id) AS reversed
            FROM app.settlement_corrections correction
            JOIN app.financial_drafts draft ON draft.id=correction.correlation_id
                AND draft.kind='SETTLEMENT_CORRECTION' AND draft.payload->>'variant'='REFUND_RETURN'
            JOIN app.settlement_correction_effects effect ON effect.settlement_correction_id=correction.id
            JOIN app.refund_corrections returned
                ON returned.id=effect.refund_correction_id AND returned.correction_kind='VALUE_CORRECTION'
            JOIN app.refunds refund ON refund.id=returned.refund_id
            WHERE correction.id=p_earlier AND correction.final_settlement_id=p_settlement
        ), users AS (
            SELECT unnest(app.settlement_return_reversal_users(p_earlier)) AS id
            WHERE EXISTS(SELECT 1 FROM earlier)
        ), credit_applications AS (
            SELECT application.* FROM earlier
            JOIN users ON true
            JOIN app.settlement_correction_effects effect ON effect.settlement_correction_id=users.id
            JOIN app.customer_credit_applications application
                ON application.id=effect.customer_credit_application_id
            WHERE application.customer_credit_id=earlier.credit_id
              AND NOT EXISTS(SELECT 1 FROM app.customer_credit_application_reversals reversal
                  WHERE reversal.credit_application_id=application.id)
        ), deposit_applications AS (
            SELECT application.* FROM earlier
            JOIN users ON true
            JOIN app.settlement_correction_effects effect ON effect.settlement_correction_id=users.id
            JOIN app.deposit_applications application ON application.id=effect.deposit_application_id
            WHERE application.deposit_id=earlier.deposit_id
              AND NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal
                  WHERE reversal.deposit_application_id=application.id)
        ), paid AS (
            SELECT refund.*,app.refund_net_value_at(refund.id,'infinity') AS net,
                CASE WHEN refund.source_deposit_id IS NULL THEN 'CREDIT' ELSE 'DEPOSIT' END AS source_kind,
                COALESCE(refund.source_deposit_id,refund.source_customer_credit_id) AS source_id,
                -- Owner answers B and C to Q-2026-10-11-78: this Lease only when the person who
                -- received the money is its signed Customer.
                CASE WHEN EXISTS(SELECT 1 FROM app.lease_signers signer
                    WHERE signer.lease_id=(SELECT settlement.lease_id FROM settlement)
                      AND signer.customer_id=refund.recipient_customer_id
                      AND signer.signed_at IS NOT NULL)
                    THEN (SELECT settlement.lease_id FROM settlement) END AS lease_id,
                -- Q-2026-10-12-94: a Credit Refund always goes to the Credit's own Customer.
                refund.source_deposit_id IS NULL OR refund.recipient_customer_id=(SELECT deposit.customer_id
                    FROM app.deposits deposit WHERE deposit.id=refund.source_deposit_id) AS deposit_customer,
                (SELECT count(*) FROM app.refund_corrections returned
                    WHERE returned.refund_id=refund.id AND returned.correction_kind='VALUE_CORRECTION'
                      AND NOT EXISTS(SELECT 1 FROM app.refund_corrections reversal
                          WHERE reversal.reverses_correction_id=returned.id)) AS returns
            FROM earlier
            JOIN users ON true
            JOIN app.settlement_correction_effects effect ON effect.settlement_correction_id=users.id
            JOIN app.refunds refund ON refund.id=effect.refund_id
            WHERE refund.source_customer_credit_id=earlier.credit_id
               OR refund.source_deposit_id=earlier.deposit_id
        )
        SELECT jsonb_build_object(
            'settlement',(SELECT jsonb_build_object('id',settlement.id,'closed_at',settlement.closed_at,
                    'lease_id',settlement.lease_id) FROM settlement),
            'earlier',(SELECT jsonb_build_object('id',earlier.id,'draft_id',earlier.draft_id,
                    'return_id',earlier.return_id,'refund_id',earlier.refund_id,
                    'amount_usd_cents',earlier.amount,'customer_credit_id',earlier.credit_id,
                    'deposit_id',earlier.deposit_id,'reversed',earlier.reversed) FROM earlier),
            'linked',(SELECT COALESCE(jsonb_agg(users.id ORDER BY users.id),'[]'::jsonb) FROM users
                WHERE users.id<>p_earlier),
            'credit_applications',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',application.id,
                    'customer_credit_id',application.customer_credit_id,
                    'target_kind',application.target_kind,'invoice_id',application.invoice_id,
                    'late_payment_charge_id',application.late_payment_charge_id,
                    'amount_usd_cents',application.amount_usd_cents)
                    ORDER BY application.occurred_at DESC,application.id DESC),'[]'::jsonb)
                FROM credit_applications application),
            'deposit_applications',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',application.id,
                    'deposit_id',application.deposit_id,'target_kind',application.target_kind,
                    'invoice_id',application.invoice_id,'invoice_line_id',application.invoice_line_id,
                    'late_payment_charge_id',application.late_payment_charge_id,
                    'amount_usd_cents',application.amount_usd_cents)
                    ORDER BY application.occurred_at DESC,application.application_order DESC,
                        application.id DESC),'[]'::jsonb)
                FROM deposit_applications application),
            -- The sub-slice 10e-1c recovery entry, read by app.write_payment_return_recoveries.
            'recoveries',(SELECT COALESCE(jsonb_agg(jsonb_build_object('refund_id',paid.id,
                    'refund_number',paid.refund_number,'source_kind',paid.source_kind,
                    'source_id',paid.source_id,'recipient_customer_id',paid.recipient_customer_id,
                    'amount_usd_cents',paid.net,'lease_id',paid.lease_id,
                    'charge',CASE WHEN paid.lease_id IS NULL THEN 'NO_LEASE'
                        ELSE 'CLOSED_SETTLEMENT_LEASE' END,
                    'closed_final_settlement_id',CASE WHEN paid.lease_id IS NOT NULL THEN p_settlement END,
                    'reservation_outcome',false,'shared_deposit',false,
                    'deposit_customer',paid.deposit_customer,'returns',paid.returns)
                    ORDER BY paid.processed_at,paid.id),'[]'::jsonb)
                FROM paid WHERE paid.net>0),
            'source',(SELECT jsonb_build_object(
                    'value_usd_cents',CASE WHEN earlier.deposit_id IS NOT NULL
                        THEN app.deposit_held_value_at(earlier.deposit_id,'infinity')
                        ELSE app.credit_available_value(earlier.credit_id) END,
                    'latest_at',CASE WHEN earlier.deposit_id IS NOT NULL
                        THEN app.deposit_balance_latest_at(earlier.deposit_id)
                        ELSE app.credit_latest_at(earlier.credit_id) END) FROM earlier))
    $$;

    -- Sub-slice 10e-3: the refusals of a RETURN_REVERSAL, at record and again at confirm.
    CREATE FUNCTION app.assert_settlement_return_reversal_allowed(p_source jsonb)
    RETURNS void LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    BEGIN
        IF jsonb_typeof(p_source->'earlier') IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'The returned-Refund correction to reverse was not found' USING ERRCODE='P0002'; END IF;
        IF (p_source->'earlier'->>'reversed')::boolean THEN
            RAISE EXCEPTION 'The return of this correction is already reversed' USING ERRCODE='55000'; END IF;
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'recoveries') recovery
            WHERE (recovery->>'returns')::bigint>0)
        THEN RAISE EXCEPTION 'A Refund paid from the returned value has its own return; reverse that return first'
            USING ERRCODE='55000'; END IF;
        -- Q-2026-10-12-94: who pays back a Deposit Refund paid to an agreed Signer waits for the
        -- owner.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'recoveries') recovery
            WHERE NOT (recovery->>'deposit_customer')::boolean)
        THEN RAISE EXCEPTION 'Who pays back a Deposit Refund paid to an agreed Signer is not decided yet'
            USING ERRCODE='55000'; END IF;
        -- Q-2026-10-12-95: the uses to undo are more than the returned amount (a REFUND_RETURN
        -- with a new Refund also applied or refunded money its source already held), so who pays
        -- back the part the return did not bring back waits for the owner (review round 1).
        IF (SELECT COALESCE(sum((application->>'amount_usd_cents')::bigint),0)
                FROM jsonb_array_elements((p_source->'credit_applications')
                    ||(p_source->'deposit_applications')) application)
            +(SELECT COALESCE(sum((recovery->>'amount_usd_cents')::bigint),0)
                FROM jsonb_array_elements(p_source->'recoveries') recovery)
            >(p_source->'earlier'->>'amount_usd_cents')::bigint
        THEN RAISE EXCEPTION 'The correction to reverse also used money its return did not bring back; reversing it waits for the owner'
            USING ERRCODE='55000'; END IF;
        -- The source holds the returned amount again once the listed uses are undone; otherwise
        -- another path used the returned value, which this correction does not undo. A missing
        -- value is refused too (review round 1).
        IF NOT COALESCE((p_source->'source'->>'value_usd_cents')::bigint
            +(SELECT COALESCE(sum((application->>'amount_usd_cents')::bigint),0)
                FROM jsonb_array_elements((p_source->'credit_applications')
                    ||(p_source->'deposit_applications')) application)
            +(SELECT COALESCE(sum((recovery->>'amount_usd_cents')::bigint),0)
                FROM jsonb_array_elements(p_source->'recoveries') recovery)
            >=(p_source->'earlier'->>'amount_usd_cents')::bigint,false)
        THEN RAISE EXCEPTION 'The returned value is no longer available; undo its other use first'
            USING ERRCODE='55000'; END IF;
    END $$;

    -- Sub-slice 10e-3: the reversal of named Deposit applications inside a correction's confirm,
    -- newest first, each linked before it is written (the loop of
    -- app.write_correction_deposit_application_reversals, for named applications only).
    CREATE FUNCTION app.write_correction_named_deposit_application_reversals(p_correction uuid,
        p_approver uuid, p_reason text, p_applications uuid[], p_at timestamptz)
    RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET "TimeZone"='UTC' AS $$
    DECLARE v_at timestamptz; v_row record; v_new uuid;
    BEGIN
        v_at:=p_at;
        FOR v_row IN SELECT application.id,application.deposit_id,application.target_kind,
                COALESCE(application.invoice_id,application.late_payment_charge_id) AS target
            FROM app.deposit_applications application
            WHERE application.id=ANY(p_applications)
              AND NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal
                  WHERE reversal.deposit_application_id=application.id)
            ORDER BY application.occurred_at DESC,application.application_order DESC,application.id DESC
        LOOP
            v_at:=GREATEST(v_at+interval '1 microsecond',CASE v_row.target_kind
                    WHEN 'INVOICE_LINE' THEN app.credit_excess_instant(v_row.target,NULL)
                    ELSE app.settlement_late_charge_instant(v_row.target,NULL) END,
                COALESCE(app.deposit_balance_latest_at(v_row.deposit_id),'-infinity')
                    +interval '1 microsecond');
            v_new:=gen_random_uuid();
            PERFORM app.link_settlement_correction_effect(p_correction,'deposit_application_reversal_id',v_new);
            INSERT INTO app.deposit_application_reversals(id,deposit_application_id,reason,occurred_at,
                actor_id,authorization_reference)
            VALUES (v_new,v_row.id,p_reason,v_at,p_approver,'financial.approve');
        END LOOP;
        RETURN v_at;
    END $$;

    -- Sub-slice 10e-3: the reversal row of a RETURN_REVERSAL: a CORRECTION_REVERSAL under
    -- refunds.corrections.reverse of exactly the earlier correction's return, the whole amount,
    -- with the draft's reason and evidence, by the approver of a RETURN_REVERSAL correction of
    -- the Refund's own Final Settlement confirmed in this transaction that links the row.
    CREATE FUNCTION app.settlement_return_reversal_allowed(p_correction app.refund_corrections)
    RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE((SELECT (p_correction).correction_kind='CORRECTION_REVERSAL'
                AND (p_correction).authorization_reference='refunds.corrections.reverse'
                AND (p_correction).actor_id=correction.actor_id
                AND (p_correction).reverses_correction_id::text=draft.payload->'source'->'earlier'->>'return_id'
                AND (p_correction).refund_id::text=draft.payload->>'refund_id'
                AND (p_correction).source_balance_effect_usd_cents
                    =-(draft.payload->>'returned_amount_usd_cents')::bigint
                AND (p_correction).reason=draft.reason
                AND (p_correction).evidence_reference=draft.payload->'return_reversal'->>'evidence_reference'
                AND app.settlement_correction_linked(correction.final_settlement_id,'refund_corrections',
                    (p_correction).id)
                AND app.settlement_refund_return_settlement((p_correction).refund_id)
                    =correction.final_settlement_id
            FROM app.settlement_correction_effects effect
            JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
            JOIN app.financial_drafts draft
                ON draft.id=correction.correlation_id AND draft.kind='SETTLEMENT_CORRECTION'
            WHERE effect.refund_correction_id=(p_correction).id
              AND draft.payload->>'variant'='RETURN_REVERSAL'),false)
    $$;

    -- Sub-slice 10e-3: a Refund a RETURN_REVERSAL recovers: one that the reversed return's
    -- correction or a HELD_VALUE_REFUND naming it wrote from the returned Refund's own Credit or
    -- Deposit, and that the draft's recorded recoveries name with the Deposit's own Customer as
    -- recipient (review round 1, defence in depth).
    CREATE FUNCTION app.settlement_return_reversal_refund(p_draft uuid, p_refund uuid)
    RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE((SELECT EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                JOIN app.refunds refund ON refund.id=effect.refund_id
                WHERE effect.refund_id=p_refund
                  AND effect.settlement_correction_id=ANY(app.settlement_return_reversal_users(
                      app.final_settlement_plan_id(draft.payload->'held_from_settlement_correction_id')::uuid))
                  AND (refund.source_customer_credit_id::text=draft.payload->>'customer_credit_id'
                      OR refund.source_deposit_id::text=draft.payload->>'deposit_id')
                  AND EXISTS(SELECT 1 FROM jsonb_array_elements(draft.payload->'source'->'recoveries') item
                      WHERE item->>'refund_id'=p_refund::text
                        AND (item->>'deposit_customer')::boolean))
            FROM app.financial_drafts draft
            WHERE draft.id=p_draft AND draft.kind='SETTLEMENT_CORRECTION'
              AND draft.payload->>'variant'='RETURN_REVERSAL'),false)
    $$;

    -- Sub-slice 10e-3: the result of a confirmed RETURN_REVERSAL (no transaction id).
    CREATE FUNCTION app.settlement_return_reversal_result(p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET "TimeZone"='UTC' AS $$
        SELECT jsonb_build_object(
            'draft',app.financial_draft_json(draft) #- '{decision,result,transaction_id}',
            'settlement_correction',(SELECT jsonb_build_object('id',correction.id,
                    'final_settlement_id',correction.final_settlement_id,'reason',correction.reason,
                    'occurred_at',correction.occurred_at,'actor_id',correction.actor_id,
                    'authorization_reference',correction.authorization_reference)
                FROM app.settlement_corrections correction
                WHERE correction.id=app.settlement_correction_id(draft.id)),
            'return_reversal',(SELECT jsonb_build_object('id',reversal.id,'refund_id',reversal.refund_id,
                    'reverses_correction_id',reversal.reverses_correction_id,
                    'amount_usd_cents',-reversal.source_balance_effect_usd_cents,
                    'previous_net_refund_usd_cents',reversal.previous_net_refund_usd_cents,
                    'resulting_net_refund_usd_cents',reversal.resulting_net_refund_usd_cents,
                    'evidence_reference',reversal.evidence_reference,'occurred_at',reversal.occurred_at,
                    'actor_id',reversal.actor_id,'authorization_reference',reversal.authorization_reference)
                FROM app.settlement_correction_effects effect
                JOIN app.refund_corrections reversal ON reversal.id=effect.refund_correction_id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)
                  AND reversal.correction_kind='CORRECTION_REVERSAL'),
            'credit_application_reversals',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',reversal.id,
                    'credit_application_id',reversal.credit_application_id,
                    'customer_credit_id',application.customer_credit_id,
                    'invoice_id',application.invoice_id,
                    'late_payment_charge_id',application.late_payment_charge_id,
                    'amount_usd_cents',application.amount_usd_cents,'occurred_at',reversal.occurred_at)
                    ORDER BY effect.effect_sequence),'[]'::jsonb)
                FROM app.settlement_correction_effects effect
                JOIN app.customer_credit_application_reversals reversal
                    ON reversal.id=effect.credit_application_reversal_id
                JOIN app.customer_credit_applications application
                    ON application.id=reversal.credit_application_id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)),
            'deposit_application_reversals',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',reversal.id,
                    'deposit_application_id',reversal.deposit_application_id,
                    'deposit_id',application.deposit_id,'invoice_line_id',application.invoice_line_id,
                    'late_payment_charge_id',application.late_payment_charge_id,
                    'amount_usd_cents',application.amount_usd_cents,'occurred_at',reversal.occurred_at)
                    ORDER BY effect.effect_sequence),'[]'::jsonb)
                FROM app.settlement_correction_effects effect
                JOIN app.deposit_application_reversals reversal
                    ON reversal.id=effect.deposit_application_reversal_id
                JOIN app.deposit_applications application ON application.id=reversal.deposit_application_id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)),
            'recoveries',(SELECT COALESCE(jsonb_agg(app.refund_recovery_json(recovery.id)
                    ORDER BY effect.effect_sequence),'[]'::jsonb)
                FROM app.settlement_correction_effects effect
                JOIN app.refund_corrections recovery ON recovery.id=effect.refund_correction_id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)
                  AND recovery.correction_kind='RECOVERED_BY_CHARGE'))
        FROM app.financial_drafts draft WHERE draft.id=p_draft
    $$;

    -- Sub-slice 10e-3: the recorder (final_settlements.prepare). The draft names the earlier
    -- REFUND_RETURN correction and stores what the confirm will undo, so the approver sees each
    -- reversal and each charge (the person and the exact amount).
    CREATE FUNCTION app.record_settlement_return_reversal_draft(p_property uuid, p_actor uuid,
        p_draft uuid, p_settlement uuid, p_reversal jsonb, p_reason text, p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET "TimeZone"='UTC' AS $$
    DECLARE v_existing app.financial_drafts%ROWTYPE; v_input jsonb; v_settlement app.final_settlements%ROWTYPE;
        v_earlier uuid; v_source jsonb; v_payload jsonb;
    BEGIN
        PERFORM app.require_invoice_command_actor(p_property,p_actor);
        PERFORM app.assert_active_financial_actor(p_actor,p_property);
        IF p_authorization IS DISTINCT FROM 'final_settlements.prepare' THEN
            RAISE EXCEPTION 'Post-settlement correction draft authorization is invalid'
                USING ERRCODE='42501'; END IF;
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_settlement IS NULL
            OR app.lease_notice_text_valid(p_reason,500) IS NOT TRUE
        THEN RAISE EXCEPTION 'Return reversal correction input is invalid' USING ERRCODE='22023'; END IF;
        v_input:=app.settlement_return_reversal_input(p_reversal);
        -- The source checks rely on READ COMMITTED: each statement sees the commits the locks
        -- waited for (as the sub-slice 10e-1a recorder).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'A post-settlement correction draft is recorded at READ COMMITTED'
                USING ERRCODE='55000'; END IF;
        -- An exact repeat replays before any current-state check.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
        IF FOUND THEN
            IF v_existing.property_id=p_property AND v_existing.kind='SETTLEMENT_CORRECTION'
                AND v_existing.payload->>'variant'='RETURN_REVERSAL' AND v_existing.prepared_by=p_actor
                AND v_existing.reason=p_reason
                AND v_existing.payload->>'final_settlement_id'=p_settlement::text
                AND v_existing.payload->'return_reversal'=v_input
            -- The decision's transaction id never leaves the database (sub-slice 10b).
            THEN RETURN app.financial_draft_json(v_existing) #- '{decision,result,transaction_id}'; END IF;
            RAISE EXCEPTION 'Post-settlement correction draft identity was reused' USING ERRCODE='P5205';
        END IF;
        v_earlier:=(v_input->>'settlement_correction_id')::uuid;
        -- One draft of an earlier correction waits at a time.
        PERFORM pg_advisory_xact_lock(hashtextextended('return-reversal:' || v_earlier::text,0));
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=p_settlement AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        IF v_settlement.closed_at IS NULL THEN
            RAISE EXCEPTION 'A post-settlement correction needs a closed Final Settlement'
                USING ERRCODE='55000'; END IF;
        v_source:=app.settlement_return_reversal_source_state(p_settlement,v_earlier);
        PERFORM app.assert_settlement_return_reversal_allowed(v_source);
        IF EXISTS(SELECT 1 FROM app.financial_drafts draft
            WHERE draft.property_id=p_property AND draft.kind='SETTLEMENT_CORRECTION'
              AND draft.payload->>'variant'='RETURN_REVERSAL'
              AND draft.payload->>'held_from_settlement_correction_id'=v_earlier::text
              AND NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                  WHERE decision.draft_id=draft.id))
        THEN RAISE EXCEPTION 'A return reversal draft of this correction is already waiting'
            USING ERRCODE='55000'; END IF;
        v_payload:=jsonb_build_object('variant','RETURN_REVERSAL','final_settlement_id',p_settlement,
            'lease_id',v_settlement.lease_id,'held_from_settlement_correction_id',v_earlier,
            'refund_id',v_source->'earlier'->'refund_id',
            'customer_credit_id',v_source->'earlier'->'customer_credit_id',
            'deposit_id',v_source->'earlier'->'deposit_id',
            'returned_amount_usd_cents',v_source->'earlier'->'amount_usd_cents',
            'return_reversal',v_input,'source',v_source);
        IF octet_length(v_payload::text)>16000 THEN
            RAISE EXCEPTION 'The return reversal correction draft exceeds the stored draft size of 16000 bytes'
                USING ERRCODE='22023'; END IF;
        RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'SETTLEMENT_CORRECTION',
            'final_settlements.prepare',v_payload,
            'settlement-correction:' || encode(sha256(convert_to(v_source::text,'UTF8')),'hex'),p_reason);
    END $$;

    -- Sub-slice 10e-3: the confirm (financial.approve, a person, READ COMMITTED).
    CREATE FUNCTION app.confirm_settlement_return_reversal(p_property uuid, p_actor uuid, p_draft uuid,
        p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET "TimeZone"='UTC' AS $$
    DECLARE v_draft app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_timezone text; v_input jsonb; v_earlier uuid; v_source jsonb; v_correction uuid; v_unit uuid;
        v_evidence jsonb; v_result jsonb; v_at timestamptz; v_row record; v_new uuid;
        v_return app.refund_corrections%ROWTYPE; v_refund app.refunds%ROWTYPE; v_net bigint;
    BEGIN
        v_timezone:=app.require_invoice_command_actor(p_property,p_actor);
        -- BR-AUTH-010: a person confirms; an inactive approver is refused above (P4506).
        IF NOT EXISTS(SELECT 1 FROM app.actor_identities identity
            WHERE identity.actor_id=p_actor AND identity.identity_kind='HUMAN')
        THEN RAISE EXCEPTION 'A post-settlement correction is confirmed only by a human approver'
            USING ERRCODE='42501'; END IF;
        IF p_authorization IS DISTINCT FROM 'financial.approve' THEN
            RAISE EXCEPTION 'Only financial.approve may confirm a post-settlement correction'
                USING ERRCODE='42501'; END IF;
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' THEN
            RAISE EXCEPTION 'Post-settlement correction input is invalid' USING ERRCODE='22023'; END IF;
        -- The serialization of every decision on this draft, then the replay of an exact repeat.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        IF EXISTS(SELECT 1 FROM app.financial_drafts draft
            JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id
            WHERE draft.id=p_draft AND draft.property_id=p_property AND draft.kind='SETTLEMENT_CORRECTION'
              AND draft.payload->>'variant'='RETURN_REVERSAL' AND decision.decision='CONFIRMED'
              AND decision.decided_by=p_actor)
        THEN RETURN app.settlement_return_reversal_result(p_draft); END IF;
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
        IF NOT FOUND OR v_draft.kind<>'SETTLEMENT_CORRECTION'
            OR v_draft.prepare_capability<>'final_settlements.prepare'
            OR v_draft.payload->>'variant' IS DISTINCT FROM 'RETURN_REVERSAL'
        THEN RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        IF EXISTS(SELECT 1 FROM app.financial_draft_decisions WHERE draft_id=p_draft) THEN
            RAISE EXCEPTION 'Financial draft is already decided' USING ERRCODE='55000'; END IF;
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=app.final_settlement_plan_id(v_draft.payload->'final_settlement_id')::uuid
          AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        -- The checks below rely on READ COMMITTED (as the other correction confirms).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'A post-settlement correction is confirmed at READ COMMITTED'
                USING ERRCODE='55000'; END IF;
        -- The stored correction passes the recorder's shape check again.
        v_input:=app.settlement_return_reversal_input(v_draft.payload->'return_reversal');
        IF v_input IS DISTINCT FROM v_draft.payload->'return_reversal' THEN
            RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        v_earlier:=(v_input->>'settlement_correction_id')::uuid;
        -- Lock order: the draft lock (above); the return-reversal lock of the earlier correction
        -- (as the recorder); then the 8e-3 order: the Settlement's draft lock, the invoice-lease
        -- lock of the Lease (the recovery charges, as sub-slice 10e-2), the Lease row FOR UPDATE,
        -- then the correction lock function, whose RETURN_REVERSAL branch takes the returned
        -- Credit (and its Payment) in the id-ordered passes, the targets of the applications to
        -- undo FOR UPDATE in the Charge and Invoice passes, the Settlement row and every Deposit
        -- of the Lease (the returned Deposit among them). A detected deadlock (40P01) is a conflict.
        PERFORM pg_advisory_xact_lock(hashtextextended('return-reversal:' || v_earlier::text,0));
        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));
        PERFORM pg_advisory_xact_lock(hashtextextended('invoice-lease:' || v_settlement.lease_id::text,0));
        PERFORM 1 FROM app.leases WHERE id=v_settlement.lease_id FOR UPDATE;
        PERFORM app.lock_settlement_correction_plan(p_draft);
        -- Under the locks, the sources still have the digest the draft recorded; otherwise the
        -- draft is stale and stays pending. Then the recorder's refusals again.
        v_source:=app.settlement_return_reversal_source_state(v_settlement.id,v_earlier);
        IF 'settlement-correction:' || encode(sha256(convert_to(v_source::text,'UTF8')),'hex')
            IS DISTINCT FROM v_draft.source_revision
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        -- The stored draft names exactly what its source reads (review round 1, as the 10e-2
        -- confirm's shape check).
        IF v_draft.payload->'source' IS DISTINCT FROM v_source
            OR v_draft.payload->>'held_from_settlement_correction_id' IS DISTINCT FROM v_earlier::text
            OR v_draft.payload->'refund_id' IS DISTINCT FROM v_source->'earlier'->'refund_id'
            OR v_draft.payload->'customer_credit_id' IS DISTINCT FROM v_source->'earlier'->'customer_credit_id'
            OR v_draft.payload->'deposit_id' IS DISTINCT FROM v_source->'earlier'->'deposit_id'
            OR v_draft.payload->'returned_amount_usd_cents'
                IS DISTINCT FROM v_source->'earlier'->'amount_usd_cents'
        THEN RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        PERFORM app.assert_settlement_return_reversal_allowed(v_source);
        SELECT lease.unit_id INTO STRICT v_unit FROM app.leases lease WHERE lease.id=v_settlement.lease_id;

        -- The decision, then the header (sub-slice 10a). From here every record is linked before
        -- it is written, and every id is fresh, never derived from the draft (sub-slice 10b).
        v_correction:=app.begin_settlement_correction(p_property,p_actor,p_draft,'financial.approve');
        v_evidence:=jsonb_build_object('capability','financial.approve','draft_id',p_draft,
            'settlement_correction_id',v_correction,'final_settlement_id',v_settlement.id,
            'variant','RETURN_REVERSAL','held_from_settlement_correction_id',v_earlier);
        v_at:=clock_timestamp();
        -- The Credit applications paid from the returned Credit, newest first (as sub-slice
        -- 10e-1b): the debt comes back on its obligations and stays with their Customers.
        FOR v_row IN SELECT (item->>'id')::uuid AS id,item->>'target_kind' AS target_kind,
                COALESCE(item->>'invoice_id',item->>'late_payment_charge_id')::uuid AS target,
                (item->>'customer_credit_id')::uuid AS credit
            FROM jsonb_array_elements(v_source->'credit_applications') WITH ORDINALITY entry(item,position)
            ORDER BY entry.position
        LOOP
            v_at:=GREATEST(v_at+interval '1 microsecond',CASE v_row.target_kind
                WHEN 'INVOICE' THEN app.credit_excess_instant(v_row.target,v_row.credit)
                ELSE app.settlement_late_charge_instant(v_row.target,v_row.credit) END);
            v_new:=gen_random_uuid();
            PERFORM app.link_settlement_correction_effect(v_correction,'credit_application_reversal_id',v_new);
            INSERT INTO app.customer_credit_application_reversals(id,credit_application_id,reason,
                occurred_at,actor_id,authorization_reference)
            VALUES (v_new,v_row.id,v_draft.reason,v_at,p_actor,'credits.applications.reverse');
        END LOOP;
        -- The Deposit applications paid from the returned Deposit, newest first.
        v_at:=app.write_correction_named_deposit_application_reversals(v_correction,p_actor,v_draft.reason,
            ARRAY(SELECT (item->>'id')::uuid FROM jsonb_array_elements(v_source->'deposit_applications') item),
            v_at);
        -- Owner answers to Q-2026-10-11-78: the person who received a Refund paid from the returned
        -- value pays it back, the exact net amount (the sub-slice 10e-1c writer).
        v_at:=app.write_payment_return_recoveries(p_property,p_actor,p_draft,v_correction,NULL,
            v_source->'recoveries',v_draft.reason,v_input->>'evidence_reference',v_at,v_evidence);
        -- The reversal of the return: later than every record above, the Refund's corrections and
        -- the latest event of its Credit or Deposit.
        SELECT * INTO STRICT v_return FROM app.refund_corrections
        WHERE id=(v_source->'earlier'->>'return_id')::uuid;
        SELECT * INTO STRICT v_refund FROM app.refunds WHERE id=v_return.refund_id;
        v_net:=app.refund_net_value_at(v_refund.id,'infinity');
        v_at:=GREATEST(v_at+interval '1 microsecond',clock_timestamp(),
            (SELECT max(correction.occurred_at) FROM app.refund_corrections correction
                WHERE correction.refund_id=v_refund.id)+interval '1 microsecond',
            COALESCE(app.credit_latest_at(v_refund.source_customer_credit_id),'-infinity')
                +interval '1 microsecond',
            COALESCE(app.deposit_balance_latest_at(v_refund.source_deposit_id),'-infinity')
                +interval '1 microsecond');
        v_new:=gen_random_uuid();
        PERFORM app.link_settlement_correction_effect(v_correction,'refund_correction_id',v_new);
        INSERT INTO app.refund_corrections(id,refund_id,correction_kind,reverses_correction_id,
            source_balance_effect_usd_cents,source_balance_effect_original_minor,
            previous_net_refund_usd_cents,resulting_net_refund_usd_cents,reason,evidence_reference,
            occurred_at,actor_id,authorization_reference)
        VALUES (v_new,v_refund.id,'CORRECTION_REVERSAL',v_return.id,-v_return.source_balance_effect_usd_cents,
            -v_return.source_balance_effect_original_minor,v_net,v_net+v_return.source_balance_effect_usd_cents,
            v_draft.reason,v_input->>'evidence_reference',v_at,p_actor,'refunds.corrections.reverse');
        -- Every linked record is written: the deferred checks run now, inside this definer
        -- function, as the existing writers run them (sub-slice 10b plan note).
        SET CONSTRAINTS ALL IMMEDIATE;
        v_result:=app.settlement_return_reversal_result(p_draft);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
        VALUES (gen_random_uuid(),v_at,timezone(v_timezone,v_at)::date,p_actor,
            'final_settlement.correction.confirmed','settlement_correction',v_correction,v_draft.reason,
            'financial.approve',p_property,'{}'::jsonb,
            jsonb_build_object('settlement_correction_id',v_correction,
                'final_settlement_id',v_settlement.id,'variant','RETURN_REVERSAL',
                'held_from_settlement_correction_id',v_earlier,'refund_id',v_refund.id,
                'refund_correction_id',v_new,'reversed_refund_correction_id',v_return.id,
                'customer_credit_id',v_refund.source_customer_credit_id,
                'deposit_id',v_refund.source_deposit_id,
                'returned_amount_usd_cents',v_return.source_balance_effect_usd_cents,
                'credit_application_reversal_ids',(SELECT COALESCE(jsonb_agg(item->'id'),'[]'::jsonb)
                    FROM jsonb_array_elements(v_result->'credit_application_reversals') item),
                'deposit_application_reversal_ids',(SELECT COALESCE(jsonb_agg(item->'id'),'[]'::jsonb)
                    FROM jsonb_array_elements(v_result->'deposit_application_reversals') item),
                'recoveries',v_result->'recoveries'),
            v_correction,'API','SUCCEEDED',v_evidence,v_refund.recipient_customer_id,v_settlement.lease_id,
            v_unit);
        RETURN v_result;
    END $$;
"""

INTERNAL = (
    "app.settlement_return_reversal_input(jsonb)",
    "app.settlement_return_reversal_users(uuid)",
    "app.settlement_return_reversal_source_state(uuid,uuid)",
    "app.assert_settlement_return_reversal_allowed(jsonb)",
    "app.write_correction_named_deposit_application_reversals(uuid,uuid,text,uuid[],timestamp with time zone)",
    "app.settlement_return_reversal_allowed(app.refund_corrections)",
    "app.settlement_return_reversal_refund(uuid,uuid)",
    "app.settlement_return_reversal_result(uuid)",
)
RECORD = "app.record_settlement_return_reversal_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_return_reversal(uuid,uuid,uuid,text)"

GENERAL = "app.validate_general_refund_correction()"
GENERAL_REPLACEMENTS = (
    (
        """                OR app.refund_recovery_allowed(NEW);""",
        """                OR app.refund_recovery_allowed(NEW)
                -- Sub-slice 10e-3: the reversal of a return recorded by mistake, inside its
                -- RETURN_REVERSAL correction.
                OR app.settlement_return_reversal_allowed(NEW);""",
    ),
    (
        """                v_available:=CASE WHEN v_refund.pet_refund_review_id IS NOT NULL THEN app.deposit_held_value_at(v_refund.source_deposit_id,'infinity')""",
        """                -- Sub-slice 10e-3 (the 10c-2b-2a note): every Deposit Refund's source is its
                -- Deposit, so an over-reversal of any Deposit Refund is refused.
                v_available:=CASE WHEN v_refund.source_deposit_id IS NOT NULL THEN app.deposit_held_value_at(v_refund.source_deposit_id,'infinity')""",
    ),
    (
        """                IF (v_refund.pet_refund_review_id IS NULL AND v_payment.status<>'RECEIVED')""",
        """                IF (v_refund.source_deposit_id IS NULL AND v_payment.status<>'RECEIVED')""",
    ),
)

RECOVERY = "app.refund_recovery_allowed(app.refund_corrections)"
RECOVERY_REPLACEMENTS = (
    (
        """                              WHERE reversal.deposit_receipt_id=receipt.id)))
                AND EXISTS(SELECT 1 FROM app.authorized_nonrecurring_obligations obligation""",
        """                              WHERE reversal.deposit_receipt_id=receipt.id))
                    -- Sub-slice 10e-3: or inside a RETURN_REVERSAL confirmed by the same approver
                    -- in this transaction that links the row, for a Refund that the reversed
                    -- return's correction or a HELD_VALUE_REFUND naming it paid from the returned
                    -- Refund's own Credit or Deposit.
                    OR EXISTS(SELECT 1 FROM app.settlement_corrections settlement_correction
                        JOIN app.financial_drafts draft ON draft.id=settlement_correction.correlation_id
                            AND draft.kind='SETTLEMENT_CORRECTION'
                            AND draft.payload->>'variant'='RETURN_REVERSAL'
                        JOIN app.financial_draft_decisions decision
                            ON decision.draft_id=draft.id AND decision.decision='CONFIRMED'
                            AND decision.decided_by=settlement_correction.actor_id
                        JOIN app.settlement_correction_effects effect
                            ON effect.settlement_correction_id=settlement_correction.id
                            AND effect.refund_correction_id=(p_correction).id
                        WHERE settlement_correction.actor_id=(p_correction).actor_id
                          AND decision.result->>'transaction_id'=pg_current_xact_id()::text
                          AND decision.decided_at>=transaction_timestamp()
                          AND app.settlement_return_reversal_refund(draft.id,refund.id)))
                AND EXISTS(SELECT 1 FROM app.authorized_nonrecurring_obligations obligation""",
    ),
)

RECOVERY_WRITER = "app.write_payment_return_recoveries(uuid,uuid,uuid,uuid,uuid,jsonb,text,text,timestamp with time zone,jsonb)"
RECOVERY_WRITER_REPLACEMENTS = (
    (
        """            THEN 'a corrected Deposit receipt' ELSE 'a returned Payment' END;""",
        """            THEN 'a corrected Deposit receipt'
            -- Sub-slice 10e-3: a Refund paid from value that a mistaken return brought back.
            WHEN p_authorization_evidence->>'variant'='RETURN_REVERSAL'
            THEN 'value a mistaken Refund return brought back' ELSE 'a returned Payment' END;""",
    ),
)

LOCK = "app.lock_settlement_correction_plan(uuid)"
LOCK_REPLACEMENTS = (
    (
        """            AND jsonb_typeof(v_draft.payload->'plan') IS DISTINCT FROM 'object'
        THEN v_steps:='[]'::jsonb; END IF;""",
        """            AND jsonb_typeof(v_draft.payload->'plan') IS DISTINCT FROM 'object'
        THEN v_steps:='[]'::jsonb; END IF;
        -- Sub-slice 10e-3: nor has a RETURN_REVERSAL.
        IF v_draft.payload->>'variant'='RETURN_REVERSAL' THEN v_steps:='[]'::jsonb; END IF;""",
    ),
    (
        """        FOR v_id IN SELECT payment.id FROM (SELECT credit.source_payment_id AS id""",
        """        -- Sub-slice 10e-3: a RETURN_REVERSAL correction's returned Credit (and so its Payment)
        -- joins the id-ordered passes; the targets of the applications it undoes join the Charge
        -- and Invoice passes FOR UPDATE; its returned Deposit is a Deposit of the Lease, in the
        -- Deposit pass. They are read before the Payment pass; a change in between changes the
        -- confirm's source digest, so the draft is then stale.
        IF v_draft.payload->>'variant'='RETURN_REVERSAL' THEN
            SELECT v_credits||COALESCE(array_agg(refund.source_customer_credit_id),'{}') INTO v_credits
            FROM app.refunds refund
            WHERE refund.id=app.final_settlement_plan_id(v_draft.payload->'refund_id')::uuid
              AND refund.source_customer_credit_id IS NOT NULL;
            SELECT COALESCE(array_agg(DISTINCT target.charge) FILTER (WHERE target.charge IS NOT NULL),'{}'),
                v_target_invoices||COALESCE(array_agg(DISTINCT target.invoice)
                    FILTER (WHERE target.invoice IS NOT NULL),'{}')
            INTO v_return_charges,v_target_invoices FROM (
                SELECT app.final_settlement_plan_id(item->'late_payment_charge_id')::uuid AS charge,
                    app.final_settlement_plan_id(item->'invoice_id')::uuid AS invoice
                FROM jsonb_array_elements(COALESCE(app.settlement_return_reversal_source_state(v_settlement,
                        app.final_settlement_plan_id(v_draft.payload->'held_from_settlement_correction_id')::uuid)
                    ->'credit_applications','[]'::jsonb)
                    ||COALESCE(app.settlement_return_reversal_source_state(v_settlement,
                        app.final_settlement_plan_id(v_draft.payload->'held_from_settlement_correction_id')::uuid)
                    ->'deposit_applications','[]'::jsonb)) item) target;
            v_target_charges:=v_target_charges||v_return_charges;
            v_target_invoices:=v_target_invoices||COALESCE((SELECT array_agg(charge.source_invoice_id)
                FROM app.late_payment_charges charge WHERE charge.id=ANY(v_return_charges)),'{}');
        END IF;
        FOR v_id IN SELECT payment.id FROM (SELECT credit.source_payment_id AS id""",
    ),
)

HELD_DEPOSIT = "app.settlement_held_deposit_value(uuid,uuid)"
HELD_DEPOSIT_REPLACEMENTS = (
    (
        """                WHERE effect.settlement_correction_id=p_earlier AND origin.source_deposit_id=p_deposit)""",
        """                WHERE effect.settlement_correction_id=p_earlier AND origin.source_deposit_id=p_deposit
                  -- Sub-slice 10e-3: a reversed return leaves nothing.
                  AND NOT EXISTS(SELECT 1 FROM app.refund_corrections reversal
                      WHERE reversal.reverses_correction_id=returned.id))""",
    ),
)

HELD_CREDIT = "app.settlement_held_credit_value(uuid,uuid,uuid)"
HELD_CREDIT_REPLACEMENTS = (
    (
        """                WHERE effect.settlement_correction_id=p_earlier AND origin.source_customer_credit_id=p_credit)""",
        """                WHERE effect.settlement_correction_id=p_earlier AND origin.source_customer_credit_id=p_credit
                  -- Sub-slice 10e-3: a reversed return leaves nothing.
                  AND NOT EXISTS(SELECT 1 FROM app.refund_corrections reversal
                      WHERE reversal.reverses_correction_id=returned.id))""",
    ),
)

PATCHES = (
    (GENERAL, GENERAL_REPLACEMENTS),
    (RECOVERY, RECOVERY_REPLACEMENTS),
    (RECOVERY_WRITER, RECOVERY_WRITER_REPLACEMENTS),
    (LOCK, LOCK_REPLACEMENTS),
    (HELD_DEPOSIT, HELD_DEPOSIT_REPLACEMENTS),
    (HELD_CREDIT, HELD_CREDIT_REPLACEMENTS),
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
            raise RuntimeError(f"Settlement return reversal contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(FUNCTION_SQL)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    for function in (*INTERNAL, RECORD, CONFIRM):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for function in (RECORD, CONFIRM):
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Settlement return reversal migration is forward-only")
