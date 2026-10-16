# ruff: noqa: E501
"""The mistaken credit Adjustment reversal after closure (V1-056 sub-slice 10f-2).

BR-SETTLE-012, BR-SETTLE-013, BR-SETTLE-016, BR-INV-044, BR-CREDIT-006, BR-CREDIT-008,
BR-AUTH-010; DB-SETTLE-003, DB-SETTLE-005, DB-INV-010, DB-CREDIT-002; owner answer 7 to
Q-2026-10-06-36 (after closure a mistaken credit Adjustment is reversed only inside a correction
prepared under final_settlements.prepare and confirmed by financial.approve), owner answer (a) to
Q-2026-10-16-118 and owner answer (b) to Q-2026-10-16-119:

- A new variant ADJUSTMENT_REVERSAL of the SETTLEMENT_CORRECTION draft: a final_settlements.prepare
  holder records it with a reason, naming the closed Final Settlement and the credit Adjustment;
  only a financial.approve holder confirms it.
- Which Adjustments: a credit Adjustment, not reversed, on an issued Invoice of the Settlement's
  Lease, recorded before the closure, or written after it by a CHARGE_REDUCTION correction of that
  Settlement (Q-2026-10-16-119 (b): its reversal restores exactly the debt the reduction removed).
  Refused (55000): the Adjustment of any other correction, an Adjustment a resolution wrote
  (Q-2026-10-16-118 point 2), an open Settlement, another Lease's Adjustment and a second waiting
  draft of either Adjustment reversal kind.
- In one transaction the confirm writes the decision and the correction header, then the
  Adjustment reversal and the put-backs of sub-slice 10f-1b (the label put back by a correction, on
  the Adjustment's own line, at most the release, the Credit still available and the line's unpaid
  rest), each linked to the correction (DB-SETTLE-005). The rest of each release stays as debt on
  the Invoice Customer's ledger (BR-SETTLE-016); no DL-032 step runs, because an Adjustment never
  releases a Deposit application.

New internal functions: an overload of app.begin_settlement_correction that also writes the
variant's result keys into the decision; an overload of app.adjustment_reversal_source that names
the Settlement; app.settlement_adjustment_reversal_result. New writers:
app.record_settlement_adjustment_reversal_draft and app.confirm_settlement_adjustment_reversal
(EXECUTE to the financial role). Relaxing exact-text patches: app.adjustment_reversal_result,
app.validate_credit_application_put_back, app.validate_adjustment_reversal_put_back and
app.adjustment_reversal_put_back_allowed also accept the confirmed decision of such a correction
(the put-back must also be linked to that correction). No table, column, trigger or other grant
change.
"""

from alembic import op
from sqlalchemy import text

revision = "20261221_147"
down_revision = "20261220_146"
branch_labels = None
depends_on = None

FUNCTION_SQL = r"""
    -- Sub-slice 10f-2: app.begin_settlement_correction with the variant's own result keys in the
    -- decision (the 10f-1b put-back checks read them); the framework keys always win.
    CREATE FUNCTION app.begin_settlement_correction(p_property uuid,p_approver uuid,p_draft uuid,
        p_authorization text,p_result jsonb)
    RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_draft app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_correction uuid;
    BEGIN
        PERFORM app.require_invoice_command_actor(p_property,p_approver);
        PERFORM app.assert_active_financial_actor(p_approver,p_property);
        IF p_authorization IS DISTINCT FROM 'financial.approve' THEN
            RAISE EXCEPTION 'Only financial.approve may confirm a post-settlement correction'
                USING ERRCODE='42501'; END IF;
        IF p_draft IS NULL OR jsonb_typeof(p_result) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'Post-settlement correction input is invalid' USING ERRCODE='22023'; END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
        IF NOT FOUND OR v_draft.kind<>'SETTLEMENT_CORRECTION' THEN
            RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        IF v_draft.payload->>'final_settlement_id' IS NULL
            OR v_draft.payload->>'final_settlement_id'
                !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=(v_draft.payload->>'final_settlement_id')::uuid AND property_id=p_property;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        -- The Settlement's draft lock first, as the Settlement recorder and confirm take it.
        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));
        v_draft:=app.lock_pending_financial_draft(p_property,p_draft);
        SELECT * INTO v_settlement FROM app.final_settlements WHERE id=v_settlement.id FOR SHARE;
        IF v_settlement.closed_at IS NULL THEN
            RAISE EXCEPTION 'A post-settlement correction needs a closed Final Settlement'
                USING ERRCODE='55000'; END IF;
        v_correction:=app.settlement_correction_id(p_draft);
        PERFORM app.confirm_financial_draft_record(p_property,p_approver,p_draft,'SETTLEMENT_CORRECTION',
            p_result || jsonb_build_object('settlement_correction_id',v_correction,
                'final_settlement_id',v_settlement.id,
                'transaction_id',pg_current_xact_id()::text),'financial.approve');
        INSERT INTO app.settlement_corrections(id,final_settlement_id,reason,occurred_at,actor_id,
            authorization_reference,correlation_id)
        VALUES (v_correction,v_settlement.id,v_draft.reason,clock_timestamp(),p_approver,
            'financial.approve',p_draft);
        RETURN v_correction;
    END $$;

    -- Sub-slice 10f-2: what an Adjustment reversal correction of a closed Final Settlement would
    -- restore and put back (the releases and amounts of sub-slice 10f-1), and the refusal that
    -- applies (NULL when none). P0002 for a Settlement or an Adjustment not on the Property.
    CREATE FUNCTION app.adjustment_reversal_source(p_property uuid,p_adjustment uuid,p_settlement uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_settlement app.final_settlements%ROWTYPE; v_adjustment app.invoice_adjustments%ROWTYPE;
        v_invoice app.invoices%ROWTYPE; v_source jsonb; v_reduction boolean; v_refusal text;
    BEGIN
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=p_settlement AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        -- The 10f-1 source gives the releases and amounts (P0002 for an Adjustment not on the
        -- Property); its refusal, written for the draft before closure, is replaced below.
        v_source:=app.adjustment_reversal_source(p_property,p_adjustment);
        SELECT * INTO STRICT v_adjustment FROM app.invoice_adjustments WHERE id=p_adjustment;
        SELECT * INTO STRICT v_invoice FROM app.invoices WHERE id=v_adjustment.invoice_id;
        -- Owner answer (b) to Q-2026-10-16-119: an Adjustment that a CHARGE_REDUCTION correction of
        -- this Settlement wrote (it released nothing).
        v_reduction:=EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
            JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
            JOIN app.financial_drafts draft ON draft.id=correction.correlation_id
            WHERE effect.invoice_adjustment_id=v_adjustment.id
              AND correction.final_settlement_id=v_settlement.id
              AND draft.kind='SETTLEMENT_CORRECTION' AND draft.payload->>'variant'='CHARGE_REDUCTION'
              AND draft.payload->'target_kind' IS NULL);
        v_refusal:=CASE
            WHEN v_adjustment.adjustment_type<>'CREDIT' THEN
                'Only a credit Adjustment is reversed by an Adjustment reversal draft'
            WHEN EXISTS(SELECT 1 FROM app.invoice_adjustment_reversals reversal
                WHERE reversal.invoice_adjustment_id=v_adjustment.id) THEN
                'The Adjustment is already reversed'
            WHEN v_invoice.status NOT IN ('UNPAID','PARTIALLY_PAID','PAID') THEN
                'The Adjustment''s Invoice is not an issued Invoice'
            -- Q-2026-10-16-118 point 2: a resolution's Adjustment stays with its resolution.
            WHEN EXISTS(SELECT 1 FROM app.hand_back_rent_resolutions resolution
                    WHERE v_adjustment.id=ANY(resolution.adjustment_ids))
                OR EXISTS(SELECT 1 FROM app.unpaid_initial_termination_resolutions resolution
                    WHERE resolution.adjustment_ids @> jsonb_build_array(v_adjustment.id::text)) THEN
                'An Adjustment that a resolution wrote is not reversed by an Adjustment reversal draft'
            WHEN v_invoice.lease_id IS DISTINCT FROM v_settlement.lease_id THEN
                'The Adjustment is not on an Invoice of this Final Settlement''s Lease'
            -- Q-2026-10-16-119 (b): of the Adjustments corrections wrote (after closure only a
            -- correction writes one on this Lease), only a CHARGE_REDUCTION's is reversed.
            WHEN NOT v_reduction AND (EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                    WHERE effect.invoice_adjustment_id=v_adjustment.id)
                OR v_adjustment.occurred_at>=v_settlement.closed_at) THEN
                'Of the Adjustments of post-settlement corrections, only a charge reduction''s is reversed by an Adjustment reversal correction'
            WHEN v_settlement.closed_at IS NULL THEN
                'A post-settlement correction needs a closed Final Settlement'
        END;
        RETURN (v_source-'refusal') || jsonb_build_object('final_settlement_id',v_settlement.id,
            'charge_reduction',v_reduction,'refusal',v_refusal);
    END $$;

    -- The result of a confirmed Adjustment reversal correction, read from the stored rows (a
    -- replay returns the same).
    CREATE FUNCTION app.settlement_adjustment_reversal_result(p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        SELECT app.adjustment_reversal_result(p_draft) || jsonb_build_object('settlement_correction',
            jsonb_build_object('id',correction.id,'final_settlement_id',correction.final_settlement_id,
                'reason',correction.reason,'occurred_at',correction.occurred_at,
                'actor_id',correction.actor_id,'authorization_reference',correction.authorization_reference))
        FROM app.settlement_corrections correction
        WHERE correction.id=app.settlement_correction_id(p_draft)
    $$;

    -- Staff record an Adjustment reversal correction of a closed Final Settlement
    -- (final_settlements.prepare); it has no financial effect until a financial.approve holder
    -- confirms it.
    CREATE FUNCTION app.record_settlement_adjustment_reversal_draft(p_property uuid,p_actor uuid,
        p_draft uuid,p_settlement uuid,p_adjustment uuid,p_reason text,p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_existing app.financial_drafts%ROWTYPE; v_source jsonb; v_payload jsonb;
    BEGIN
        PERFORM app.require_invoice_command_actor(p_property,p_actor);
        PERFORM app.assert_active_financial_actor(p_actor,p_property);
        IF p_authorization IS DISTINCT FROM 'final_settlements.prepare' THEN
            RAISE EXCEPTION 'Post-settlement correction draft authorization is invalid'
                USING ERRCODE='42501'; END IF;
        -- The one-draft-per-Adjustment lock and the source read rely on READ COMMITTED (as the
        -- 10f-1 recorder).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'A post-settlement correction draft is recorded at READ COMMITTED'
                USING ERRCODE='55000'; END IF;
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_settlement IS NULL
            OR p_adjustment IS NULL OR app.lease_notice_text_valid(p_reason,1000) IS NOT TRUE
        THEN RAISE EXCEPTION 'Adjustment reversal correction input is invalid' USING ERRCODE='22023'; END IF;
        -- An exact repeat replays before any current-state check.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
        IF FOUND THEN
            IF v_existing.property_id=p_property AND v_existing.kind='SETTLEMENT_CORRECTION'
                AND v_existing.payload->>'variant'='ADJUSTMENT_REVERSAL'
                AND v_existing.prepared_by=p_actor AND v_existing.reason=p_reason
                AND v_existing.payload->>'final_settlement_id'=p_settlement::text
                AND v_existing.payload->>'invoice_adjustment_id'=p_adjustment::text
            -- No result or replay shows the decision's transaction id (sub-slice 10b).
            THEN RETURN app.financial_draft_json(v_existing) #- '{decision,result,transaction_id}'; END IF;
            RAISE EXCEPTION 'Post-settlement correction draft identity was reused' USING ERRCODE='P5205';
        END IF;
        -- The drafts of one Adjustment, of both Adjustment reversal kinds, are serialized, so only
        -- one may wait.
        PERFORM pg_advisory_xact_lock(hashtextextended('adjustment-reversal:' || p_adjustment::text,0));
        v_source:=app.adjustment_reversal_source(p_property,p_adjustment,p_settlement);
        IF v_source->>'refusal' IS NOT NULL THEN
            RAISE EXCEPTION '%',v_source->>'refusal' USING ERRCODE='55000'; END IF;
        IF EXISTS(SELECT 1 FROM app.financial_drafts draft
            WHERE draft.property_id=p_property
              AND (draft.kind='ADJUSTMENT_REVERSAL' OR (draft.kind='SETTLEMENT_CORRECTION'
                  AND draft.payload->>'variant'='ADJUSTMENT_REVERSAL'))
              AND draft.payload->>'invoice_adjustment_id'=p_adjustment::text
              AND NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                  WHERE decision.draft_id=draft.id))
        THEN RAISE EXCEPTION 'Another Adjustment reversal draft of this Adjustment is waiting'
            USING ERRCODE='55000'; END IF;
        v_payload:=jsonb_build_object('variant','ADJUSTMENT_REVERSAL','final_settlement_id',p_settlement,
            'invoice_adjustment_id',p_adjustment,'lease_id',v_source->'lease_id',
            'customer_id',v_source->'customer_id','source',v_source);
        IF octet_length(v_payload::text)>16000 THEN
            RAISE EXCEPTION 'The Adjustment reversal correction draft exceeds the stored draft size of 16000 bytes'
                USING ERRCODE='22023'; END IF;
        RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'SETTLEMENT_CORRECTION',
            'final_settlements.prepare',v_payload,
            'settlement-correction:' || encode(sha256(convert_to(v_source::text,'UTF8')),'hex'),p_reason);
    END $$;

    -- A financial.approve holder confirms an Adjustment reversal correction: in one transaction
    -- the decision and the correction header, the reversal, the Invoice status and version, and
    -- the put-backs, each record linked to the correction. Refusals: an unknown Property, draft or
    -- Settlement P0002/P4501; an inactive or missing approver P4506 or 42501; business state
    -- 55000; a draft whose sources changed P5S02 (stale; it stays pending). Nothing is written
    -- unless everything succeeds.
    CREATE FUNCTION app.confirm_settlement_adjustment_reversal(p_property uuid,p_actor uuid,p_draft uuid,
        p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_timezone text; v_draft app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_adjustment app.invoice_adjustments%ROWTYPE; v_invoice app.invoices%ROWTYPE;
        v_line app.invoice_lines%ROWTYPE; v_source jsonb; v_row record; v_item jsonb; v_correction uuid;
        v_reversal uuid; v_at timestamptz; v_put_at timestamptz; v_before jsonb; v_plan jsonb;
        v_put bigint; v_unit uuid; v_evidence jsonb; v_result jsonb;
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
              AND draft.payload->>'variant'='ADJUSTMENT_REVERSAL' AND decision.decision='CONFIRMED'
              AND decision.decided_by=p_actor)
        THEN RETURN app.settlement_adjustment_reversal_result(p_draft); END IF;
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
        IF NOT FOUND OR v_draft.kind<>'SETTLEMENT_CORRECTION'
            OR v_draft.prepare_capability<>'final_settlements.prepare'
            OR v_draft.payload->>'variant' IS DISTINCT FROM 'ADJUSTMENT_REVERSAL'
            OR v_draft.payload->>'invoice_adjustment_id' IS NULL
            OR v_draft.payload->>'invoice_adjustment_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            OR v_draft.payload->>'final_settlement_id' IS NULL
            OR v_draft.payload->>'final_settlement_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        THEN RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        IF EXISTS(SELECT 1 FROM app.financial_draft_decisions WHERE draft_id=p_draft) THEN
            RAISE EXCEPTION 'Financial draft is already decided' USING ERRCODE='55000'; END IF;
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=(v_draft.payload->>'final_settlement_id')::uuid AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        -- The checks below rely on READ COMMITTED: each statement sees the commits the locks waited
        -- for (as the 10f-1 confirm and the charge reduction confirm).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'A post-settlement correction is confirmed at READ COMMITTED'
                USING ERRCODE='55000'; END IF;
        -- Lock order: the draft lock (above); the Adjustment's draft lock (shared with sub-slice
        -- 10f-1); the Settlement's draft lock (as app.begin_settlement_correction takes it); each
        -- released Credit's Payment (its serialization row, then the row) in id order, the Credits
        -- in id order, then the Invoice and its lines (the Credit writers' order, as 10f-1); the
        -- Settlement row last, in app.begin_settlement_correction, after the Invoice (the order of
        -- the 8e-1 refusal).
        PERFORM pg_advisory_xact_lock(hashtextextended(
            'adjustment-reversal:' || (v_draft.payload->>'invoice_adjustment_id'),0));
        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));
        SELECT * INTO v_adjustment FROM app.invoice_adjustments
        WHERE id=(v_draft.payload->>'invoice_adjustment_id')::uuid;
        IF NOT FOUND OR app.invoice_property_id(v_adjustment.invoice_id) IS DISTINCT FROM p_property THEN
            RAISE EXCEPTION 'Invoice Adjustment was not found' USING ERRCODE='P0002'; END IF;
        FOR v_row IN SELECT DISTINCT credit.source_payment_id AS payment_id
            FROM app.invoice_credit_excess_releases release
            LEFT JOIN app.customer_credit_applications application
                ON application.id=release.reversed_credit_application_id
            JOIN app.customer_credits credit
                ON credit.id=COALESCE(release.customer_credit_id,application.customer_credit_id)
            WHERE release.invoice_adjustment_id=v_adjustment.id ORDER BY 1
        LOOP
            PERFORM app.serialize_payment_state(v_row.payment_id);
            PERFORM 1 FROM app.payments WHERE id=v_row.payment_id FOR UPDATE;
        END LOOP;
        PERFORM 1 FROM app.customer_credits credit WHERE credit.id IN (
            SELECT COALESCE(release.customer_credit_id,application.customer_credit_id)
            FROM app.invoice_credit_excess_releases release
            LEFT JOIN app.customer_credit_applications application
                ON application.id=release.reversed_credit_application_id
            WHERE release.invoice_adjustment_id=v_adjustment.id)
        ORDER BY credit.id FOR UPDATE;
        PERFORM app.lock_payment_allocation_target('INVOICE',v_adjustment.invoice_id);
        SELECT * INTO STRICT v_invoice FROM app.invoices WHERE id=v_adjustment.invoice_id FOR UPDATE;
        PERFORM 1 FROM app.invoice_lines WHERE invoice_id=v_invoice.id ORDER BY id FOR UPDATE;
        -- Under the locks, the sources still have the digest the draft recorded; otherwise the
        -- draft is stale and stays pending. Then the recorder's refusals again.
        v_source:=app.adjustment_reversal_source(p_property,v_adjustment.id,v_settlement.id);
        IF 'settlement-correction:' || encode(sha256(convert_to(v_source::text,'UTF8')),'hex')
            IS DISTINCT FROM v_draft.source_revision
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        IF v_source->>'refusal' IS NOT NULL THEN
            RAISE EXCEPTION '%',v_source->>'refusal' USING ERRCODE='55000'; END IF;
        SELECT * INTO STRICT v_line FROM app.invoice_lines WHERE id=v_adjustment.invoice_line_id;
        SELECT lease.unit_id INTO STRICT v_unit FROM app.leases lease WHERE lease.id=v_invoice.lease_id;

        -- Every id is fresh; the decision names the reversal and each put-back before they are
        -- written (the 10f-1b put-back checks read them), so the result is read from the stored
        -- rows.
        v_reversal:=gen_random_uuid();
        SELECT COALESCE(jsonb_agg(entry.item||jsonb_build_object('credit_application_id',gen_random_uuid())
                ORDER BY entry.position),'[]'::jsonb)
        INTO v_plan
        FROM jsonb_array_elements(v_source->'releases') WITH ORDINALITY AS entry(item,position)
        WHERE (entry.item->>'put_back_usd_cents')::bigint>0;
        -- The reversal advances the Invoice version once, and a put-back once more (the refresh).
        IF (v_invoice.version>2147483647-(CASE WHEN jsonb_array_length(v_plan)>0 THEN 2 ELSE 1 END)) THEN
            RAISE EXCEPTION 'Invoice version cannot advance' USING ERRCODE='55000'; END IF;
        -- The decision, then the header (sub-slice 10a). From here every record is linked before
        -- it is written.
        v_correction:=app.begin_settlement_correction(p_property,p_actor,p_draft,'financial.approve',
            jsonb_build_object('invoice_adjustment_reversal_id',v_reversal,
                'invoice_adjustment_id',v_adjustment.id,
                'put_backs',(SELECT COALESCE(jsonb_agg(jsonb_build_object(
                        'credit_application_id',entry.item->'credit_application_id',
                        'invoice_credit_excess_release_id',entry.item->'invoice_credit_excess_release_id',
                        'customer_credit_id',entry.item->'customer_credit_id',
                        'amount_usd_cents',entry.item->'put_back_usd_cents') ORDER BY entry.position),
                        '[]'::jsonb)
                    FROM jsonb_array_elements(v_plan) WITH ORDINALITY AS entry(item,position)),
                'debt_usd_cents',(v_source->>'debt_usd_cents')::bigint));
        v_before:=app.invoice_resource_snapshot(v_invoice.id);
        -- DB-INV-010: the reversal with the draft's reason and the approver, dated after every
        -- financial event of the Invoice; the Invoice status and version as app.adjust_invoice sets
        -- them. The 8e-1 refusal lets it through because the correction links it.
        v_at:=app.adjustment_reversal_instant(v_invoice.id);
        PERFORM app.link_settlement_correction_effect(v_correction,'invoice_adjustment_reversal_id',v_reversal);
        INSERT INTO app.invoice_adjustment_reversals(id,invoice_adjustment_id,reason,occurred_at,actor_id,
            authorization_reference)
        VALUES (v_reversal,v_adjustment.id,v_draft.reason,v_at,p_actor,'financial.approve');
        UPDATE app.invoices SET status=app.invoice_application_status(v_invoice.id),version=version+1,
            updated_at=GREATEST(v_at,updated_at),updated_by=p_actor WHERE id=v_invoice.id;
        -- The put-backs of sub-slice 10f-1b (owner answer (a) to Q-2026-10-16-118 point 1): each
        -- part of a release's Credit still available goes back on the Adjustment's own line with
        -- the label put back by a correction and no Rent-first proposal; the approver applies it
        -- as the Credit writers do (credits.apply), each dated after the one before, each linked
        -- to the correction.
        v_put_at:=v_at;
        FOR v_item IN SELECT entry.item FROM jsonb_array_elements(v_plan) WITH ORDINALITY AS entry(item,position)
            ORDER BY entry.position
        LOOP
            v_put:=(v_item->>'put_back_usd_cents')::bigint;
            v_put_at:=GREATEST(v_put_at+interval '1 microsecond',
                app.credit_excess_instant(v_invoice.id,(v_item->>'customer_credit_id')::uuid));
            PERFORM app.link_settlement_correction_effect(v_correction,'customer_credit_application_id',
                (v_item->>'credit_application_id')::uuid);
            INSERT INTO app.customer_credit_applications(id,customer_credit_id,target_kind,invoice_id,
                late_payment_charge_id,final_settlement_id,amount_usd_cents,within_invoice_basis,
                customer_designation_reference,proposal_generated_at,proposal_trace,occurred_at,actor_id,
                authorization_reference)
            VALUES ((v_item->>'credit_application_id')::uuid,(v_item->>'customer_credit_id')::uuid,
                'INVOICE',v_invoice.id,NULL,NULL,v_put,'PUT_BACK_BY_CORRECTION',NULL,
                NULL,NULL,v_put_at,p_actor,'credits.apply');
            INSERT INTO app.customer_credit_application_details(id,customer_credit_application_id,
                invoice_line_id,late_payment_charge_id,obligation_kind,invoice_line_category_snapshot,
                proposed_amount_usd_cents,applied_amount_usd_cents,attribution_basis,detail_sequence,
                calculation_trace)
            VALUES (gen_random_uuid(),(v_item->>'credit_application_id')::uuid,v_line.id,NULL,
                'INVOICE_LINE',v_line.category,NULL,v_put,'PUT_BACK_BY_CORRECTION',1,
                jsonb_build_object('reason','Invoice Adjustment reversal put-back',
                    'invoice_adjustment_reversal_id',v_reversal,
                    'invoice_credit_excess_release_id',v_item->'invoice_credit_excess_release_id'));
        END LOOP;
        IF jsonb_array_length(v_plan)>0 THEN
            PERFORM app.refresh_allocated_invoice(v_invoice.id,p_actor,true);
        END IF;
        -- Every linked record is written: the deferred checks run now, inside this definer
        -- function (as the other variants run them).
        SET CONSTRAINTS ALL IMMEDIATE;
        v_result:=app.settlement_adjustment_reversal_result(p_draft);
        v_evidence:=jsonb_build_object('capability','financial.approve','draft_id',p_draft,
            'settlement_correction_id',v_correction,'final_settlement_id',v_settlement.id,
            'variant','ADJUSTMENT_REVERSAL');
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,linked_source_event_id,customer_id,lease_id)
        VALUES (gen_random_uuid(),v_at,timezone(v_timezone,v_at)::date,p_actor,'invoice.adjustment_reversed',
            'invoice',v_invoice.id,v_draft.reason,'financial.approve',p_property,v_before,
            app.invoice_resource_snapshot(v_invoice.id),p_draft,'API','SUCCEEDED',
            v_evidence || jsonb_build_object('prepare_capability','final_settlements.prepare',
                'invoice_adjustment_id',v_adjustment.id,'invoice_adjustment_reversal_id',v_reversal,
                'invoice_line_id',v_line.id,'put_backs',v_result->'put_backs'),
            v_reversal,v_invoice.customer_id,v_invoice.lease_id);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
        VALUES (gen_random_uuid(),v_at,timezone(v_timezone,v_at)::date,p_actor,
            'final_settlement.correction.confirmed','settlement_correction',v_correction,v_draft.reason,
            'financial.approve',p_property,'{}'::jsonb,
            jsonb_build_object('settlement_correction_id',v_correction,
                'final_settlement_id',v_settlement.id,'variant','ADJUSTMENT_REVERSAL',
                'invoice_adjustment_id',v_adjustment.id,'invoice_adjustment_reversal_id',v_reversal,
                'invoice_id',v_invoice.id,'invoice_line_id',v_line.id,'customer_id',v_invoice.customer_id,
                'restored_usd_cents',v_adjustment.amount_usd_cents,'put_backs',v_result->'put_backs',
                'debt_usd_cents',(v_source->>'debt_usd_cents')::bigint),
            v_correction,'API','SUCCEEDED',v_evidence,v_invoice.customer_id,v_invoice.lease_id,v_unit);
        RETURN v_result;
    END $$;
"""

# The decision filter of the 10f-1b put-back checks and of the 10f-1 result: an ADJUSTMENT_REVERSAL
# draft, or (sub-slice 10f-2) a SETTLEMENT_CORRECTION draft of the variant ADJUSTMENT_REVERSAL.
KIND = "draft.kind='ADJUSTMENT_REVERSAL' AND decision.decision='CONFIRMED'"
EITHER_KIND = (
    "(draft.kind='ADJUSTMENT_REVERSAL' OR (draft.kind='SETTLEMENT_CORRECTION'\n"
    "                    AND draft.payload->>'variant'='ADJUSTMENT_REVERSAL'))\n"
    "                  AND decision.decision='CONFIRMED'"
)

PATCHES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "app.adjustment_reversal_result(uuid)",
        (
            (
                "WHERE draft.id=p_draft AND draft.kind='ADJUSTMENT_REVERSAL'",
                "WHERE draft.id=p_draft AND (draft.kind='ADJUSTMENT_REVERSAL'\n"
                "            OR (draft.kind='SETTLEMENT_CORRECTION'"
                " AND draft.payload->>'variant'='ADJUSTMENT_REVERSAL'))",
            ),
        ),
    ),
    ("app.validate_credit_application_put_back()", ((KIND, EITHER_KIND),)),
    ("app.validate_adjustment_reversal_put_back()", ((KIND, EITHER_KIND),)),
    (
        "app.adjustment_reversal_put_back_allowed(app.customer_credit_applications,"
        "app.customer_credit_application_details)",
        (
            (KIND, EITHER_KIND),
            (
                "AND p_application.final_settlement_id IS NULL\n",
                "AND p_application.final_settlement_id IS NULL\n"
                "                -- Sub-slice 10f-2: a correction's put-back is also linked to it.\n"
                "                AND (draft.kind='ADJUSTMENT_REVERSAL'\n"
                "                    OR EXISTS(SELECT 1 FROM app.settlement_correction_effects effect\n"
                "                        WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)\n"
                "                          AND effect.customer_credit_application_id=p_application.id))\n",
            ),
        ),
    ),
)

INTERNAL = (
    "app.begin_settlement_correction(uuid,uuid,uuid,text,jsonb)",
    "app.adjustment_reversal_source(uuid,uuid,uuid)",
    "app.settlement_adjustment_reversal_result(uuid)",
)
RECORD = "app.record_settlement_adjustment_reversal_draft(uuid,uuid,uuid,uuid,uuid,text,text)"
CONFIRM = "app.confirm_settlement_adjustment_reversal(uuid,uuid,uuid,text)"


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
            raise RuntimeError(f"Settlement Adjustment reversal contract changed: {signature}")
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
    raise RuntimeError("Settlement Adjustment reversal migration is forward-only")
