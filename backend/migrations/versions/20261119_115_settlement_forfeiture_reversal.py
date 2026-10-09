# ruff: noqa: E501
"""Post-settlement correction: FORFEITURE_REVERSAL (V1-056 sub-slice 10d).

BR-SETTLE-013, BR-SETTLE-008, BR-DEP-019, BR-DEP-023, BR-DEP-026, DL-032, BR-REFUND-014,
BR-REFUND-015, BR-AUTH-010; owner answer 4 to Q-2026-10-06-36, answer 1 to Q-2026-10-06-37,
answers 1 and 3 to Q-2026-10-07-41, answers 1 to 3 to Q-2026-10-07-42, Q-2026-10-05-24 and
answer 2 to Q-2026-10-10-71:

- The reversal of a confirmed Lease Deposit forfeiture after the Lease's Final Settlement is
  closed runs inside a correction of that Settlement. Staff record it under
  final_settlements.prepare with a reason, the forfeiture, an evidence reference, the Refund
  method and reference note and the DL-032 plan; only a financial.approve holder confirms it.
- In one transaction the confirm writes the forfeiture reversal through the existing reversal
  function (every earlier reversal rule applies: the approver as actor, deposits.correct, the
  command record and the deposit.disposition.reversed audit), linked to the correction, so the
  Deposit holds the forfeited money again on the DL-032 path (Q-2026-10-05-24); then the shared
  DL-032 step: each Customer's Credit first pays that Customer's own open debt on the Lease, the
  Deposit pays the Lease's open debt in the DL-032 order and only the rest is refunded
  (BR-SETTLE-008), to the Primary Tenant or an agreed signed Signer (BR-REFUND-015).
- Owner answer 2 to Q-2026-10-10-71: a forfeiture is reversed this way only when no other
  forfeiture of the same Deposit stays active, because otherwise the Deposit stays kept and the
  step cannot use the money (Q-2026-10-09-61 decides that case before sub-slice 10h).

New functions only; no committed function, table or trigger changes.
"""

from alembic import op

revision = "20261119_115"
down_revision = "20261118_114"
branch_labels = None
depends_on = None

SQL = r"""
    -- The stored form of a forfeiture reversal correction: the forfeiture, the evidence reference
    -- (1 to 500 characters) and the Refund method and reference note of the correction (both
    -- required, BR-REFUND-014). 22023 otherwise.
    CREATE FUNCTION app.settlement_forfeiture_reversal_input(p_input jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_disposition text; v_method text;
    BEGIN
        IF p_input IS NULL OR jsonb_typeof(p_input) IS DISTINCT FROM 'object'
            -- The byte order, whatever the database collation.
            OR (SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(p_input) key)
                IS DISTINCT FROM ARRAY['deposit_disposition_id','evidence_reference','reference_note','refund_method_id']
            OR jsonb_typeof(p_input->'evidence_reference') IS DISTINCT FROM 'string'
            OR app.lease_notice_text_valid(p_input->>'evidence_reference',500) IS NOT TRUE
            OR jsonb_typeof(p_input->'reference_note') IS DISTINCT FROM 'string'
            OR app.lease_notice_text_valid(p_input->>'reference_note',500) IS NOT TRUE
        THEN RAISE EXCEPTION 'Forfeiture reversal correction input is invalid' USING ERRCODE='22023'; END IF;
        v_disposition:=app.final_settlement_plan_id(p_input->'deposit_disposition_id');
        v_method:=app.final_settlement_plan_id(p_input->'refund_method_id');
        IF v_disposition IS NULL OR v_method IS NULL THEN
            RAISE EXCEPTION 'Forfeiture reversal correction input is invalid' USING ERRCODE='22023'; END IF;
        RETURN jsonb_build_object('deposit_disposition_id',v_disposition,
            'evidence_reference',p_input->>'evidence_reference','refund_method_id',v_method,
            'reference_note',p_input->>'reference_note');
    END $$;

    -- What a forfeiture reversal correction depends on: the Settlement, the forfeiture and its
    -- reversal state, the Deposit (held value, latest balance event, path), the other forfeitures
    -- of the Deposit that stay active and the pending drafts of the Deposit (a correction draft,
    -- this one included, is serialized by the Settlement's draft lock and is left out).
    CREATE FUNCTION app.settlement_forfeiture_reversal_source_state(p_settlement uuid,p_disposition uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        SELECT jsonb_build_object(
            'settlement',(SELECT jsonb_build_object('id',settlement.id,'closed_at',settlement.closed_at,
                    'lease_id',settlement.lease_id)
                FROM app.final_settlements settlement WHERE settlement.id=p_settlement),
            'disposition',(SELECT jsonb_build_object('id',disposition.id,'deposit_id',disposition.deposit_id,
                    'amount_usd_cents',disposition.amount_usd_cents,
                    'governing_lease_id',disposition.governing_lease_id,
                    'reversal_ids',(SELECT COALESCE(jsonb_agg(reversal.id ORDER BY reversal.id),'[]'::jsonb)
                        FROM app.deposit_disposition_reversals reversal
                        WHERE reversal.deposit_disposition_id=disposition.id))
                FROM app.deposit_dispositions disposition WHERE disposition.id=p_disposition),
            'deposit',(SELECT jsonb_build_object('id',deposit.id,
                    'held_usd_cents',app.deposit_held_value_at(deposit.id,'infinity'),
                    'latest_at',app.deposit_balance_latest_at(deposit.id),
                    'path',app.lease_deposit_settlement_path(app.deposit_property_id(deposit.id),deposit.id)->>'path',
                    'other_active_forfeitures',(SELECT COALESCE(jsonb_agg(other.id ORDER BY other.id),'[]'::jsonb)
                        FROM app.deposit_dispositions other
                        WHERE other.deposit_id=deposit.id AND other.id<>p_disposition
                          AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal
                              WHERE reversal.deposit_disposition_id=other.id)),
                    'pending_drafts',(SELECT COALESCE(jsonb_agg(draft.id ORDER BY draft.id),'[]'::jsonb)
                        FROM app.financial_drafts draft
                        WHERE draft.property_id=app.deposit_property_id(deposit.id)
                          AND draft.kind<>'SETTLEMENT_CORRECTION'
                          AND draft.payload->>'deposit_id'=deposit.id::text
                          AND NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                              WHERE decision.draft_id=draft.id)))
                FROM app.deposit_dispositions disposition
                JOIN app.deposits deposit ON deposit.id=disposition.deposit_id
                WHERE disposition.id=p_disposition))
    $$;

    -- Checks a stored-form forfeiture reversal correction against the current state and returns
    -- what the draft records: the Lease, the Deposit and its owner, the forfeiture, the forfeited
    -- amount and the source revision. An unknown Settlement or a forfeiture that is not one of a
    -- Deposit of the Settlement's Lease P0002; a state the correction does not allow 55000.
    CREATE FUNCTION app.settlement_forfeiture_reversal_plan(p_property uuid,p_settlement uuid,p_input jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_settlement app.final_settlements%ROWTYPE; v_disposition app.deposit_dispositions%ROWTYPE;
        v_customer uuid;
    BEGIN
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=p_settlement AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        IF v_settlement.closed_at IS NULL THEN
            RAISE EXCEPTION 'A post-settlement correction needs a closed Final Settlement'
                USING ERRCODE='55000'; END IF;
        -- A Lease forfeiture of a Deposit of this Lease (a Reservation disposition has no
        -- governing Lease).
        SELECT disposition.* INTO v_disposition FROM app.deposit_dispositions disposition
        JOIN app.deposits deposit ON deposit.id=disposition.deposit_id
        WHERE disposition.id=(p_input->>'deposit_disposition_id')::uuid
          AND disposition.governing_lease_id=v_settlement.lease_id AND deposit.lease_id=v_settlement.lease_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Lease Deposit forfeiture was not found' USING ERRCODE='P0002'; END IF;
        IF EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal
            WHERE reversal.deposit_disposition_id=v_disposition.id)
        THEN RAISE EXCEPTION 'The forfeiture is already reversed' USING ERRCODE='55000'; END IF;
        -- Owner answer 2 to Q-2026-10-10-71: with another active forfeiture the Deposit stays kept
        -- after the reversal, and the DL-032 step cannot use the money.
        IF EXISTS(SELECT 1 FROM app.deposit_dispositions other
            WHERE other.deposit_id=v_disposition.deposit_id AND other.id<>v_disposition.id
              AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal
                  WHERE reversal.deposit_disposition_id=other.id))
        THEN RAISE EXCEPTION 'Another forfeiture of this Deposit stays active; the reversal would not put the Deposit on the DL-032 path'
            USING ERRCODE='55000'; END IF;
        -- BR-REFUND-014: an active Refund method for the correction's Deposit Refund.
        PERFORM 1 FROM app.refund_methods WHERE id=(p_input->>'refund_method_id')::uuid AND active;
        IF NOT FOUND THEN RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE='55000'; END IF;
        SELECT deposit.customer_id INTO STRICT v_customer FROM app.deposits deposit
        WHERE deposit.id=v_disposition.deposit_id;
        RETURN jsonb_build_object('lease_id',v_settlement.lease_id,'customer_id',v_customer,
            'deposit_id',v_disposition.deposit_id,'deposit_disposition_id',v_disposition.id,
            'amount_usd_cents',v_disposition.amount_usd_cents,
            'source_revision','settlement-correction:' || encode(sha256(convert_to(
                app.settlement_forfeiture_reversal_source_state(p_settlement,v_disposition.id)::text,'UTF8')),'hex'));
    END $$;

    -- The result of a confirmed forfeiture reversal correction: the shared correction result and
    -- the forfeiture reversal it linked.
    CREATE FUNCTION app.settlement_forfeiture_reversal_result(p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        SELECT app.settlement_refund_return_result(p_draft)||jsonb_build_object('forfeiture_reversal',
            (SELECT jsonb_build_object('id',reversal.id,'deposit_disposition_id',reversal.deposit_disposition_id,
                    'deposit_id',disposition.deposit_id,'amount_usd_cents',disposition.amount_usd_cents,
                    'reason',reversal.reason,'evidence_reference',reversal.evidence_reference,
                    'occurred_at',reversal.occurred_at,'actor_id',reversal.actor_id,
                    'authorization_reference',reversal.authorization_reference)
                FROM app.settlement_correction_effects effect
                JOIN app.deposit_disposition_reversals reversal
                    ON reversal.id=effect.deposit_disposition_reversal_id
                JOIN app.deposit_dispositions disposition ON disposition.id=reversal.deposit_disposition_id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(p_draft)))
    $$;

    -- Staff record a forfeiture reversal correction draft (final_settlements.prepare); it has no
    -- financial effect until a financial.approve holder confirms it.
    CREATE FUNCTION app.record_settlement_forfeiture_reversal_draft(p_property uuid,p_actor uuid,p_draft uuid,
        p_settlement uuid,p_reversal jsonb,p_reason text,p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_existing app.financial_drafts%ROWTYPE; v_input jsonb; v_plan jsonb; v_payload jsonb;
        v_steps jsonb; v_overlay jsonb; v_result jsonb; v_choice text;
    BEGIN
        PERFORM app.require_invoice_command_actor(p_property,p_actor);
        PERFORM app.assert_active_financial_actor(p_actor,p_property);
        IF p_authorization IS DISTINCT FROM 'final_settlements.prepare' THEN
            RAISE EXCEPTION 'Post-settlement correction draft authorization is invalid'
                USING ERRCODE='42501'; END IF;
        -- The reason is at most 500 characters, as every correction's and the reversal record's.
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_settlement IS NULL
            OR app.lease_notice_text_valid(p_reason,500) IS NOT TRUE
            OR p_reversal IS NULL OR jsonb_typeof(p_reversal) IS DISTINCT FROM 'object'
        THEN RAISE EXCEPTION 'Forfeiture reversal correction input is invalid' USING ERRCODE='22023'; END IF;
        v_input:=app.settlement_forfeiture_reversal_input(p_reversal-'plan');
        v_steps:=COALESCE(p_reversal->'plan',jsonb_build_object('steps','[]'::jsonb,'pet_remainder','null'::jsonb));
        IF jsonb_typeof(v_steps) IS DISTINCT FROM 'object' OR jsonb_typeof(v_steps->'steps') IS DISTINCT FROM 'array'
        THEN RAISE EXCEPTION 'Forfeiture reversal correction input is invalid' USING ERRCODE='22023'; END IF;
        -- An exact repeat replays before any current-state check.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
        IF FOUND THEN
            IF v_existing.property_id=p_property AND v_existing.kind='SETTLEMENT_CORRECTION'
                AND v_existing.payload->>'variant'='FORFEITURE_REVERSAL' AND v_existing.prepared_by=p_actor
                AND v_existing.reason=p_reason
                AND v_existing.payload->>'final_settlement_id'=p_settlement::text
                AND v_existing.payload->'forfeiture_reversal'=v_input AND v_existing.payload->'plan'=v_steps
            -- No correction result or replay shows the decision's transaction id (sub-slice 10b).
            THEN RETURN app.financial_draft_json(v_existing) #- '{decision,result,transaction_id}'; END IF;
            RAISE EXCEPTION 'Post-settlement correction draft identity was reused' USING ERRCODE='P5205';
        END IF;
        v_plan:=app.settlement_forfeiture_reversal_plan(p_property,p_settlement,v_input);
        -- One Refund method and reference note per correction: every Deposit Refund step uses the
        -- correction's.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(v_steps->'steps') step
            WHERE step->>'kind'='DEPOSIT_REFUNDS'
              AND (app.final_settlement_plan_id(step->'refund_method_id')
                      IS DISTINCT FROM v_input->>'refund_method_id'
                  OR step->'reference_note' IS DISTINCT FROM v_input->'reference_note'))
        THEN RAISE EXCEPTION 'A post-settlement correction has one Refund method, reference note, recipient and agreement'
            USING ERRCODE='22023'; END IF;
        -- Owner answer 3 to Q-2026-10-07-44: the remaining Pet Deposit is used by the Customer's
        -- choice given for this correction; neither the Final Settlement's nor an earlier
        -- confirmed correction's choice is reused (the recorded text is compared).
        IF v_steps->'pet_remainder'->>'basis'='CUSTOMER_CHOICE' THEN
            SELECT draft.payload->'pet_remainder'->>'customer_choice' INTO v_choice
            FROM app.financial_drafts draft
            JOIN app.financial_draft_decisions decision
                ON decision.draft_id=draft.id AND decision.decision='CONFIRMED'
            WHERE draft.kind='FINAL_SETTLEMENT' AND draft.payload->>'final_settlement_id'=p_settlement::text;
            IF v_choice IS NOT NULL AND v_choice=v_steps->'pet_remainder'->>'customer_choice' THEN
                RAISE EXCEPTION 'A correction needs the Customer''s choice for this correction; the Final Settlement''s choice is not reused'
                    USING ERRCODE='55000'; END IF;
            IF EXISTS(SELECT 1 FROM app.financial_drafts draft
                JOIN app.financial_draft_decisions decision
                    ON decision.draft_id=draft.id AND decision.decision='CONFIRMED'
                WHERE draft.kind='SETTLEMENT_CORRECTION'
                  AND draft.payload->>'final_settlement_id'=p_settlement::text
                  AND draft.payload->'plan'->'pet_remainder'->>'customer_choice'
                      =v_steps->'pet_remainder'->>'customer_choice')
            THEN RAISE EXCEPTION 'A correction needs the Customer''s choice for this correction; an earlier correction''s choice is not reused'
                USING ERRCODE='55000'; END IF;
        END IF;
        -- The shared step's check on the current state (sub-slice 10c-2a-2) with the forfeited
        -- amount back in the Deposit: each Customer's Credit first pays that Customer's own open
        -- debt, the Deposit pays the Lease's open debt in the DL-032 order and only the rest is
        -- refunded (owner answer 4 to Q-2026-10-06-36, BR-SETTLE-008). The check adds the overlay
        -- whatever the Deposit's path; at the confirm the reversal puts the Deposit on the DL-032
        -- path (Q-2026-10-05-24) before the step checks the real state.
        v_overlay:=jsonb_build_object('obligations','{}'::jsonb,'credits','{}'::jsonb,
            'deposits',jsonb_build_object(v_plan->>'deposit_id',v_plan->'amount_usd_cents'));
        v_result:=app.settlement_correction_plan_result(p_property,p_actor,p_settlement,v_steps,v_overlay)
            -'source_revision';
        v_payload:=jsonb_build_object('variant','FORFEITURE_REVERSAL','final_settlement_id',p_settlement,
            'lease_id',v_plan->'lease_id','customer_id',v_plan->'customer_id','deposit_id',v_plan->'deposit_id',
            'deposit_disposition_id',v_plan->'deposit_disposition_id',
            'amount_usd_cents',v_plan->'amount_usd_cents','forfeiture_reversal',v_input,
            'plan',v_steps,'plan_overlay',v_overlay,'plan_result',v_result);
        RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'SETTLEMENT_CORRECTION',
            'final_settlements.prepare',v_payload,v_plan->>'source_revision',p_reason);
    END $$;

    -- A financial.approve holder confirms a forfeiture reversal correction: in one transaction the
    -- decision and the header (sub-slice 10a), then, each linked before it is written, the
    -- forfeiture reversal and the shared DL-032 step. Refusals: an unknown Property, draft or
    -- Settlement P0002/P4501; an inactive or missing approver P4506 or 42501; business state
    -- 55000; a draft whose sources changed P5S02 (stale; it stays pending). Nothing is written
    -- unless everything succeeds.
    CREATE FUNCTION app.confirm_settlement_forfeiture_reversal(p_property uuid,p_actor uuid,p_draft uuid,
        p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_draft app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_timezone text; v_now timestamptz; v_business_date date; v_input jsonb; v_plan jsonb;
        v_correction uuid; v_unit uuid; v_evidence jsonb; v_result jsonb; v_step jsonb; v_method uuid;
        v_deposit uuid; v_customer uuid; v_disposition uuid; v_reversal uuid;
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
              AND draft.payload->>'variant'='FORFEITURE_REVERSAL' AND decision.decision='CONFIRMED'
              AND decision.decided_by=p_actor)
        THEN RETURN app.settlement_forfeiture_reversal_result(p_draft); END IF;
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
        IF NOT FOUND OR v_draft.kind<>'SETTLEMENT_CORRECTION'
            OR v_draft.prepare_capability<>'final_settlements.prepare'
            OR v_draft.payload->>'variant' IS DISTINCT FROM 'FORFEITURE_REVERSAL'
        THEN RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        IF EXISTS(SELECT 1 FROM app.financial_draft_decisions WHERE draft_id=p_draft) THEN
            RAISE EXCEPTION 'Financial draft is already decided' USING ERRCODE='55000'; END IF;
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=app.final_settlement_plan_id(v_draft.payload->'final_settlement_id')::uuid
          AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        -- The checks below rely on READ COMMITTED: each statement sees the commits the locks
        -- waited for (as the other correction confirms).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'A post-settlement correction is confirmed at READ COMMITTED'
                USING ERRCODE='55000'; END IF;
        -- The stored correction passes the recorder's shape check again.
        v_input:=app.settlement_forfeiture_reversal_input(v_draft.payload->'forfeiture_reversal');
        IF v_input IS DISTINCT FROM v_draft.payload->'forfeiture_reversal' THEN
            RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        v_disposition:=(v_input->>'deposit_disposition_id')::uuid;
        -- Lock order, the 8e-3 order (as the other correction confirms): the draft lock (above);
        -- the Settlement's draft lock; the Lease row FOR UPDATE; then the shared step's locks
        -- (app.lock_settlement_correction_plan), whose last pass takes every Deposit of the Lease
        -- with its lease-deposit-forfeiture lock and row; then the forfeiture row FOR UPDATE (the
        -- Deposit before the forfeiture, as the 6b confirm); after the stale checks the Refund
        -- methods FOR SHARE; app.begin_settlement_correction locks the draft row and the
        -- Settlement row. A detected deadlock (40P01) is a conflict.
        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));
        PERFORM 1 FROM app.leases WHERE id=v_settlement.lease_id FOR UPDATE;
        PERFORM app.lock_settlement_correction_plan(p_draft);
        PERFORM 1 FROM app.deposit_dispositions WHERE id=v_disposition FOR UPDATE;
        -- Under the locks, the sources still have the digest the draft recorded, and the check of
        -- the recorder still gives the same correction; otherwise the draft is stale and stays pending.
        IF 'settlement-correction:' || encode(sha256(convert_to(app.settlement_forfeiture_reversal_source_state(
                v_settlement.id,v_disposition)::text,'UTF8')),'hex')
            IS DISTINCT FROM v_draft.source_revision
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        v_plan:=app.settlement_forfeiture_reversal_plan(p_property,v_settlement.id,v_input);
        IF v_plan->>'source_revision' IS DISTINCT FROM v_draft.source_revision
            OR v_plan->'lease_id' IS DISTINCT FROM v_draft.payload->'lease_id'
            OR v_plan->'customer_id' IS DISTINCT FROM v_draft.payload->'customer_id'
            OR v_plan->'deposit_id' IS DISTINCT FROM v_draft.payload->'deposit_id'
            OR v_plan->'amount_usd_cents' IS DISTINCT FROM v_draft.payload->'amount_usd_cents'
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        v_deposit:=app.final_settlement_plan_id(v_plan->'deposit_id')::uuid;
        v_customer:=app.final_settlement_plan_id(v_plan->'customer_id')::uuid;
        -- BR-REFUND-014: each Refund method stays active until its Refunds are written.
        FOR v_method IN SELECT DISTINCT method.id FROM (
                SELECT app.final_settlement_plan_id(step->'refund_method_id')::uuid AS id
                FROM jsonb_array_elements(v_draft.payload->'plan'->'steps') step
                WHERE step->>'kind'='DEPOSIT_REFUNDS'
                UNION SELECT app.final_settlement_plan_id(v_input->'refund_method_id')::uuid) method
            WHERE method.id IS NOT NULL ORDER BY 1
        LOOP
            PERFORM 1 FROM app.refund_methods WHERE id=v_method AND active FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE='55000'; END IF;
        END LOOP;
        SELECT lease.unit_id INTO STRICT v_unit FROM app.leases lease WHERE lease.id=v_settlement.lease_id;

        -- The decision, then the header (sub-slice 10a). From here every record is linked before
        -- it is written, and every id is fresh, never derived from the draft (sub-slice 10b).
        v_correction:=app.begin_settlement_correction(p_property,p_actor,p_draft,'financial.approve');
        v_evidence:=jsonb_build_object('capability','financial.approve','draft_id',p_draft,
            'settlement_correction_id',v_correction,'final_settlement_id',v_settlement.id,
            'variant','FORFEITURE_REVERSAL','deposit_disposition_id',v_disposition);
        -- The forfeiture reversal through the existing reversal function (migration 27, as the 6b
        -- confirm writes it): the approver as actor, deposits.correct, the draft's reason and
        -- evidence reference, the command record keyed by this draft and the
        -- deposit.disposition.reversed audit. The Deposit then holds the forfeited money again on
        -- the DL-032 path (Q-2026-10-05-24).
        v_reversal:=gen_random_uuid();
        PERFORM app.link_settlement_correction_effect(v_correction,'deposit_disposition_reversal_id',v_reversal);
        PERFORM app.reverse_deposit_disposition_v2(p_property,p_actor,p_draft,
            encode(sha256(convert_to('settlement-forfeiture-reversal:' || p_draft::text,'UTF8')),'hex'),
            v_reversal,v_disposition,v_draft.reason,v_input->>'evidence_reference','deposits.correct');
        v_now:=GREATEST(clock_timestamp(),app.deposit_balance_latest_at(v_deposit)+interval '1 microsecond');
        v_business_date:=timezone(v_timezone,v_now)::date;
        -- The shared DL-032 step (sub-slice 10c-2a-2): under the same locks, the plan check again on
        -- the real state (stale P5S02 otherwise), then the Customer's Credit, the Deposit
        -- applications and the Deposit Refund of the plan.
        v_step:=app.post_settlement_correction_plan(p_property,p_actor,p_draft);
        -- Every linked record is written: the deferred checks run now, inside this definer
        -- function, as the existing writers run them (sub-slice 10b plan note).
        SET CONSTRAINTS ALL IMMEDIATE;
        v_result:=app.settlement_forfeiture_reversal_result(p_draft);
        -- The audit event names the recipient of the Deposit Refund the step wrote (one recipient
        -- per correction), or the Deposit's owner when nothing was refunded.
        v_customer:=COALESCE((SELECT refund.recipient_customer_id FROM app.refunds refund
            WHERE refund.id IN (SELECT listed::uuid
                FROM jsonb_array_elements_text(COALESCE(v_step->'refund_ids','[]'::jsonb)) listed)
            ORDER BY refund.id LIMIT 1),v_customer);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
        VALUES (gen_random_uuid(),v_now,v_business_date,p_actor,'final_settlement.correction.confirmed',
            'settlement_correction',v_correction,v_draft.reason,'financial.approve',p_property,
            '{}'::jsonb,
            jsonb_build_object('settlement_correction_id',v_correction,
                'final_settlement_id',v_settlement.id,'variant','FORFEITURE_REVERSAL',
                'deposit_disposition_id',v_disposition,'deposit_disposition_reversal_id',v_reversal,
                'deposit_id',v_deposit,'reversed_usd_cents',v_plan->'amount_usd_cents',
                'customer_id',v_customer,
                -- Every record the shared step wrote (sub-slice 10c-2a-3).
                'credit_application_ids',COALESCE(v_step->'credit_application_ids','[]'::jsonb),
                'deposit_application_ids',COALESCE(v_step->'deposit_application_ids','[]'::jsonb),
                'deposit_refund_ids',COALESCE(v_step->'refund_ids','[]'::jsonb)),
            v_correction,'API','SUCCEEDED',v_evidence,v_customer,v_settlement.lease_id,v_unit);
        RETURN v_result;
    END $$;
"""

INTERNAL = (
    "app.settlement_forfeiture_reversal_input(jsonb)",
    "app.settlement_forfeiture_reversal_source_state(uuid,uuid)",
    "app.settlement_forfeiture_reversal_plan(uuid,uuid,jsonb)",
    "app.settlement_forfeiture_reversal_result(uuid)",
)
RECORD = "app.record_settlement_forfeiture_reversal_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_forfeiture_reversal(uuid,uuid,uuid,text)"


def upgrade() -> None:
    op.execute(SQL)
    for function in (*INTERNAL, RECORD, CONFIRM):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for function in (RECORD, CONFIRM):
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Forfeiture reversal correction migration is forward-only")
