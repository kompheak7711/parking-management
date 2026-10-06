# ruff: noqa: E501
"""Post-settlement correction: charge reduction (V1-056 sub-slice 10c-1a).

BR-SETTLE-013, BR-SETTLE-012, BR-INV-045, BR-AUTH-010; DB-SETTLE-003, DB-SETTLE-005; owner answer 1
to Q-2026-10-06-36 (a clear fix for a wrong charge that is still unpaid).

- A wrong charge that is still unpaid after closure is removed by a CHARGE_REDUCTION correction:
  Staff record a SETTLEMENT_CORRECTION draft under final_settlements.prepare with a reason
  (app.record_settlement_charge_reduction_draft); only a financial.approve holder confirms it
  (app.confirm_settlement_charge_reduction). The confirmation writes, linked to the correction, a
  credit Adjustment of the wrong Invoice line, which follows its Invoice's Customer (BR-INV-045).
- The amount is at most the line's unpaid rest under the locks. A reduction that would release paid
  value is a REFUND correction (sub-slice 10c-1b) and is refused here.
- An Invoice that a Deposit application paid takes no Adjustment (the 8a-1 refusal stays until
  sub-slice 10c-2).

Additive: new functions only; no table, trigger or earlier function changes. The 8e-1 refusal
already lets a linked Adjustment through (sub-slice 10a).
"""

from alembic import op

revision = "20261103_99"
down_revision = "20261102_98"
branch_labels = None
depends_on = None

RECORD = "app.record_settlement_charge_reduction_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_charge_reduction(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.settlement_charge_reduction_input(jsonb)",
    "app.settlement_charge_reduction_source_state(uuid,uuid,uuid)",
    "app.settlement_charge_reduction_plan(uuid,uuid,jsonb)",
    "app.settlement_charge_reduction_result(uuid)",
)

CHARGE_REDUCTION_SQL = """
    -- The draft's reduction, checked for shape only and stored in one form: malformed input 22023.
    CREATE FUNCTION app.settlement_charge_reduction_input(p_reduction jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_invoice text; v_line text;
    BEGIN
        IF p_reduction IS NULL OR jsonb_typeof(p_reduction) IS DISTINCT FROM 'object'
            OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_reduction) key
                WHERE key NOT IN ('invoice_id','invoice_line_id','amount_usd_cents'))
        THEN RAISE EXCEPTION 'Charge reduction input is invalid' USING ERRCODE='22023'; END IF;
        v_invoice:=app.final_settlement_plan_id(p_reduction->'invoice_id');
        v_line:=app.final_settlement_plan_id(p_reduction->'invoice_line_id');
        IF v_invoice IS NULL OR v_line IS NULL
            OR jsonb_typeof(p_reduction->'amount_usd_cents') IS DISTINCT FROM 'number'
            OR (p_reduction->>'amount_usd_cents') !~ '^[1-9][0-9]{0,15}$'
        THEN RAISE EXCEPTION 'Charge reduction input is invalid' USING ERRCODE='22023'; END IF;
        -- The cap of the other money writers; a JSON number always casts.
        IF (p_reduction->>'amount_usd_cents')::numeric>9000000000000000 THEN
            RAISE EXCEPTION 'Charge reduction input is invalid' USING ERRCODE='22023'; END IF;
        RETURN jsonb_build_object('invoice_id',v_invoice,'invoice_line_id',v_line,
            'amount_usd_cents',(p_reduction->>'amount_usd_cents')::bigint);
    END $$;

    -- The state a charge reduction depends on; its digest is the draft's source revision. A
    -- Payment, Credit or Deposit value on the line, or an Adjustment of it, changes the digest.
    CREATE FUNCTION app.settlement_charge_reduction_source_state(p_settlement uuid,p_invoice uuid,
        p_line uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        SELECT jsonb_build_object(
            'settlement',(SELECT jsonb_build_object('id',settlement.id,'closed_at',settlement.closed_at,
                    'lease_id',settlement.lease_id)
                FROM app.final_settlements settlement WHERE settlement.id=p_settlement),
            'invoice',(SELECT jsonb_build_object('id',invoice.id,'lease_id',invoice.lease_id,
                    'customer_id',invoice.customer_id,
                    'issued',invoice.status IN ('UNPAID','PARTIALLY_PAID','PAID'),
                    'deposit_applications',(SELECT count(*) FROM app.deposit_applications application
                        WHERE application.invoice_id=invoice.id))
                FROM app.invoices invoice WHERE invoice.id=p_invoice),
            'line',(SELECT jsonb_build_object('id',line.id,'invoice_id',line.invoice_id,
                    'obligation_usd_cents',app.invoice_adjusted_line_obligation(line.id),
                    'paid_usd_cents',app.invoice_line_application_value_at(line.id,'infinity'))
                FROM app.invoice_lines line WHERE line.id=p_line))
    $$;

    -- Checks a stored-form reduction against the current state and returns what the draft records:
    -- the Lease, the Invoice's Customer, the reduction and the source revision. An unknown
    -- Settlement, Invoice or line P0002; a state the correction does not allow 55000.
    CREATE FUNCTION app.settlement_charge_reduction_plan(p_property uuid,p_settlement uuid,
        p_reduction jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_settlement app.final_settlements%ROWTYPE; v_invoice app.invoices%ROWTYPE; v_line uuid;
    BEGIN
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=p_settlement AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        IF v_settlement.closed_at IS NULL THEN
            RAISE EXCEPTION 'A post-settlement correction needs a closed Final Settlement'
                USING ERRCODE='55000'; END IF;
        SELECT * INTO v_invoice FROM app.invoices
        WHERE id=(p_reduction->>'invoice_id')::uuid AND lease_id=v_settlement.lease_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The reduced Invoice is not an Invoice of this Final Settlement'
                USING ERRCODE='P0002'; END IF;
        IF v_invoice.status NOT IN ('UNPAID','PARTIALLY_PAID','PAID') THEN
            RAISE EXCEPTION 'The reduced Invoice is not an issued obligation of this Final Settlement'
                USING ERRCODE='55000'; END IF;
        SELECT line.id INTO v_line FROM app.invoice_lines line
        WHERE line.id=(p_reduction->>'invoice_line_id')::uuid AND line.invoice_id=v_invoice.id;
        IF NOT FOUND THEN RAISE EXCEPTION 'Invoice line was not found' USING ERRCODE='P0002'; END IF;
        -- 8a-1: an Invoice that a Deposit application paid takes no Adjustment (until 10c-2).
        IF EXISTS(SELECT 1 FROM app.deposit_applications application
            WHERE application.invoice_id=v_invoice.id)
        THEN RAISE EXCEPTION 'A Deposit application paid this obligation at Final Settlement'
            USING ERRCODE='55000'; END IF;
        -- Design note: a reduction removes only the unpaid rest; releasing paid value is a REFUND.
        IF (p_reduction->>'amount_usd_cents')::bigint>app.invoice_line_outstanding(v_line) THEN
            RAISE EXCEPTION 'The charge reduction would release paid value'
                USING ERRCODE='55000'; END IF;
        RETURN jsonb_build_object('lease_id',v_settlement.lease_id,'customer_id',v_invoice.customer_id,
            'reduction',p_reduction,
            'source_revision','settlement-correction:' || encode(sha256(convert_to(
                app.settlement_charge_reduction_source_state(p_settlement,v_invoice.id,v_line)::text,
                'UTF8')),'hex'));
    END $$;

    -- Staff record a charge reduction correction draft (final_settlements.prepare); it has no
    -- financial effect until a financial.approve holder confirms it.
    CREATE FUNCTION app.record_settlement_charge_reduction_draft(p_property uuid,p_actor uuid,
        p_draft uuid,p_settlement uuid,p_reduction jsonb,p_reason text,p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_existing app.financial_drafts%ROWTYPE; v_input jsonb; v_plan jsonb; v_payload jsonb;
    BEGIN
        PERFORM app.require_invoice_command_actor(p_property,p_actor);
        PERFORM app.assert_active_financial_actor(p_actor,p_property);
        IF p_authorization IS DISTINCT FROM 'final_settlements.prepare' THEN
            RAISE EXCEPTION 'Post-settlement correction draft authorization is invalid'
                USING ERRCODE='42501'; END IF;
        -- The reason is at most 500 characters: the Adjustment keeps it (as app.adjust_invoice).
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_settlement IS NULL
            OR app.lease_notice_text_valid(p_reason,500) IS NOT TRUE
        THEN RAISE EXCEPTION 'Charge reduction input is invalid' USING ERRCODE='22023'; END IF;
        v_input:=app.settlement_charge_reduction_input(p_reduction);
        -- An exact repeat replays before any current-state check.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
        IF FOUND THEN
            IF v_existing.property_id=p_property AND v_existing.kind='SETTLEMENT_CORRECTION'
                AND v_existing.payload->>'variant'='CHARGE_REDUCTION' AND v_existing.prepared_by=p_actor
                AND v_existing.reason=p_reason
                AND v_existing.payload->>'final_settlement_id'=p_settlement::text
                AND v_existing.payload->'reduction'=v_input
            -- The decision's transaction id never leaves the database (sub-slice 10b).
            THEN RETURN app.financial_draft_json(v_existing) #- '{decision,result,transaction_id}'; END IF;
            RAISE EXCEPTION 'Post-settlement correction draft identity was reused' USING ERRCODE='P5205';
        END IF;
        v_plan:=app.settlement_charge_reduction_plan(p_property,p_settlement,v_input);
        v_payload:=jsonb_build_object('variant','CHARGE_REDUCTION','final_settlement_id',p_settlement,
            'lease_id',v_plan->'lease_id','customer_id',v_plan->'customer_id',
            'reduction',v_plan->'reduction');
        RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'SETTLEMENT_CORRECTION',
            'final_settlements.prepare',v_payload,v_plan->>'source_revision',p_reason);
    END $$;

    -- What the confirm returns, also for an exact repeat (rebuilt from the stored records): the
    -- draft without the decision's transaction id, the correction header, the linked Adjustment and
    -- its Invoice.
    CREATE FUNCTION app.settlement_charge_reduction_result(p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT jsonb_build_object(
            'draft',app.financial_draft_json(draft) #- '{decision,result,transaction_id}',
            'settlement_correction',(SELECT jsonb_build_object('id',correction.id,
                    'final_settlement_id',correction.final_settlement_id,'reason',correction.reason,
                    'occurred_at',correction.occurred_at,'actor_id',correction.actor_id,
                    'authorization_reference',correction.authorization_reference)
                FROM app.settlement_corrections correction
                WHERE correction.id=app.settlement_correction_id(draft.id)),
            'invoice_adjustment',(SELECT jsonb_build_object('id',adjustment.id,
                    'invoice_id',adjustment.invoice_id,'invoice_line_id',adjustment.invoice_line_id,
                    'adjustment_type',adjustment.adjustment_type,
                    'amount_usd_cents',adjustment.amount_usd_cents,
                    'source_reference',adjustment.source_reference,'reason',adjustment.reason,
                    'occurred_at',adjustment.occurred_at,'actor_id',adjustment.actor_id,
                    'authorization_reference',adjustment.authorization_reference)
                FROM app.settlement_correction_effects effect
                JOIN app.invoice_adjustments adjustment ON adjustment.id=effect.invoice_adjustment_id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)),
            'invoice',app.invoice_resource_snapshot((SELECT adjustment.invoice_id
                FROM app.settlement_correction_effects effect
                JOIN app.invoice_adjustments adjustment ON adjustment.id=effect.invoice_adjustment_id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id))))
        FROM app.financial_drafts draft WHERE draft.id=p_draft
    $$;

    -- A financial.approve holder confirms a charge reduction correction. Refusals: an unknown
    -- Property, draft or Settlement P0002/P4501; an inactive or missing approver P4506 or 42501;
    -- business state (a decided draft, an open Settlement) 55000; a draft whose sources changed
    -- since it was recorded P5S02 (stale; it stays pending). At the confirm a release of paid value
    -- or a new Deposit application always shows as a changed line, so it is P5S02, not the
    -- recorder's 55000 (review round 1). Nothing is written unless everything succeeds.
    CREATE FUNCTION app.confirm_settlement_charge_reduction(p_property uuid,p_actor uuid,p_draft uuid,
        p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_draft app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_invoice app.invoices%ROWTYPE; v_timezone text; v_now timestamptz; v_business_date date;
        v_reduction jsonb; v_plan jsonb; v_correction uuid; v_adjustment uuid; v_line uuid;
        v_amount bigint; v_reference text; v_unit uuid; v_before jsonb; v_after jsonb;
        v_evidence jsonb; v_result jsonb;
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
              AND draft.payload->>'variant'='CHARGE_REDUCTION' AND decision.decision='CONFIRMED'
              AND decision.decided_by=p_actor)
        THEN RETURN app.settlement_charge_reduction_result(p_draft); END IF;
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
        IF NOT FOUND OR v_draft.kind<>'SETTLEMENT_CORRECTION'
            OR v_draft.prepare_capability<>'final_settlements.prepare'
            OR v_draft.payload->>'variant' IS DISTINCT FROM 'CHARGE_REDUCTION'
        THEN RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        IF EXISTS(SELECT 1 FROM app.financial_draft_decisions WHERE draft_id=p_draft) THEN
            RAISE EXCEPTION 'Financial draft is already decided' USING ERRCODE='55000'; END IF;
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=app.final_settlement_plan_id(v_draft.payload->'final_settlement_id')::uuid
          AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        -- The checks below rely on READ COMMITTED: each statement sees the commits the locks
        -- waited for (as the Settlement confirm and the extra charge confirm).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'A post-settlement correction is confirmed at READ COMMITTED'
                USING ERRCODE='55000'; END IF;
        -- The stored reduction passes the recorder's shape check again, so a later recorder of
        -- another shape never reaches the writes below (as sub-slice 10b).
        v_reduction:=app.settlement_charge_reduction_input(v_draft.payload->'reduction');
        IF v_reduction IS DISTINCT FROM v_draft.payload->'reduction' THEN
            RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        v_line:=(v_reduction->>'invoice_line_id')::uuid;
        v_amount:=(v_reduction->>'amount_usd_cents')::bigint;
        -- Lock order: the draft lock (above); the Settlement's draft lock (as
        -- app.begin_settlement_correction takes it); the Invoice, before the Settlement row that
        -- app.begin_settlement_correction locks, in the order of the 8e-1 refusal (Invoice, then
        -- Settlement row), so a Payment or Credit on the line commits before or waits.
        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));
        SELECT * INTO v_invoice FROM app.invoices WHERE id=(v_reduction->>'invoice_id')::uuid FOR UPDATE;
        -- Under the locks, the sources still have the digest the draft recorded, and the check of
        -- the recorder still gives the same result; otherwise the draft is stale and stays pending.
        IF 'settlement-correction:' || encode(sha256(convert_to(app.settlement_charge_reduction_source_state(
                v_settlement.id,(v_reduction->>'invoice_id')::uuid,v_line)::text,'UTF8')),'hex')
            IS DISTINCT FROM v_draft.source_revision
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        v_plan:=app.settlement_charge_reduction_plan(p_property,v_settlement.id,v_reduction);
        IF v_plan->>'source_revision' IS DISTINCT FROM v_draft.source_revision
            OR v_plan->'lease_id' IS DISTINCT FROM v_draft.payload->'lease_id'
            OR v_plan->'customer_id' IS DISTINCT FROM v_draft.payload->'customer_id'
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        SELECT lease.unit_id INTO STRICT v_unit FROM app.leases lease WHERE lease.id=v_invoice.lease_id;

        -- The decision, then the header (sub-slice 10a). From here every record is linked before
        -- it is written.
        v_correction:=app.begin_settlement_correction(p_property,p_actor,p_draft,'financial.approve');
        -- Every record is stamped after the approval (as sub-slice 10b).
        v_now:=clock_timestamp();
        v_business_date:=timezone(v_timezone,v_now)::date;
        -- A fresh id, never derived from the draft (sub-slice 10b security review round 1).
        v_adjustment:=gen_random_uuid();
        v_reference:='settlement-correction:' || v_correction::text;
        v_before:=app.invoice_resource_snapshot(v_invoice.id);
        v_evidence:=jsonb_build_object('capability','financial.approve','draft_id',p_draft,
            'settlement_correction_id',v_correction,'final_settlement_id',v_settlement.id,
            'variant','CHARGE_REDUCTION');
        PERFORM app.link_settlement_correction_effect(v_correction,'invoice_adjustment_id',v_adjustment);
        INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adjustment_type,
            amount_usd_cents,source_reference,reason,occurred_at,actor_id,authorization_reference)
        VALUES (v_adjustment,v_invoice.id,v_line,'CREDIT',v_amount,v_reference,v_draft.reason,v_now,
            p_actor,'financial.approve');
        -- The Invoice status, version and time follow, as app.adjust_invoice refreshes them.
        UPDATE app.invoices SET status=app.invoice_application_status(v_invoice.id),
            version=version+1,updated_at=v_now,updated_by=p_actor
        WHERE id=v_invoice.id;
        -- Every linked record is written: the deferred checks run now, inside this definer
        -- function, as the existing Invoice writers run them (sub-slice 10b plan note).
        SET CONSTRAINTS ALL IMMEDIATE;
        v_after:=app.invoice_resource_snapshot(v_invoice.id);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
            entity_id,reason,authorization_reference,property_id,previous_state,resulting_state,
            correlation_id,source,outcome,authorization_evidence,linked_source_event_id,customer_id,
            lease_id)
        VALUES (gen_random_uuid(),v_now,v_business_date,p_actor,'invoice.adjusted','invoice',
            v_invoice.id,v_draft.reason,'financial.approve',p_property,v_before,v_after,v_correction,
            'API','SUCCEEDED',v_evidence || jsonb_build_object('source_reference',v_reference,
                'invoice_line_id',v_line),
            v_adjustment,v_invoice.customer_id,v_invoice.lease_id);
        v_result:=app.settlement_charge_reduction_result(p_draft);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
        VALUES (gen_random_uuid(),v_now,v_business_date,p_actor,'final_settlement.correction.confirmed',
            'settlement_correction',v_correction,v_draft.reason,'financial.approve',p_property,
            '{}'::jsonb,
            jsonb_build_object('settlement_correction_id',v_correction,
                'final_settlement_id',v_settlement.id,'variant','CHARGE_REDUCTION',
                'invoice_adjustment_id',v_adjustment,'invoice_id',v_invoice.id,'invoice_line_id',v_line,
                'customer_id',v_invoice.customer_id,'amount_usd_cents',v_amount),
            v_correction,'API','SUCCEEDED',v_evidence,v_invoice.customer_id,v_invoice.lease_id,v_unit);
        RETURN v_result;
    END $$;
"""


def upgrade() -> None:
    op.execute(CHARGE_REDUCTION_SQL)
    for function in (RECORD, CONFIRM, *INTERNAL):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {RECORD}, {CONFIRM} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Settlement charge reduction migration is forward-only")
