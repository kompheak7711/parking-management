# ruff: noqa: E501
"""Post-settlement correction: CHARGE_REDUCTION of an unpaid Late-payment Charge (V1-056 sub-slice 10c-3a).

BR-SETTLE-013, BR-LATE-005, BR-AUTH-010; owner answer to Q-2026-10-07-38 (recommendation (a)):

- After the Lease's Final Settlement is closed, a wrong Late-payment Charge that is still unpaid is
  reduced by a CHARGE_REDUCTION correction: Staff record it under final_settlements.prepare with a
  reason, the Charge and the amount; only a financial.approve holder confirms it.
- The confirm links and writes one Late-payment Charge correction: REDUCTION of the amount, or
  CHARGE_REVERSAL when the amount is the whole current obligation. It never releases paid value:
  more than the unpaid rest is refused (a paid Charge is sub-slice 10c-3b), and a Charge a Deposit
  application paid is refused, as the Invoice-line form (8a-1).

New functions beside the Invoice-line ones (migration 20261103_99); the Invoice-line confirm is
patched so that it never takes a Late-payment Charge draft, and the new confirm never takes an
Invoice-line draft.
"""

from alembic import op
from sqlalchemy import text

revision = "20261115_111"
down_revision = "20261114_110"
branch_labels = None
depends_on = None

LINE_CONFIRM = "app.confirm_settlement_charge_reduction(uuid,uuid,uuid,text)"
LINE_CONFIRM_REPLACEMENTS = (
    (
        "              AND draft.payload->>'variant'='CHARGE_REDUCTION' AND decision.decision='CONFIRMED'\n",
        "              AND draft.payload->>'variant'='CHARGE_REDUCTION' AND decision.decision='CONFIRMED'\n"
        "              -- Sub-slice 10c-3a: a Late-payment Charge reduction has its own confirm.\n"
        "              AND draft.payload->'target_kind' IS NULL\n",
    ),
    (
        "            OR v_draft.payload->>'variant' IS DISTINCT FROM 'CHARGE_REDUCTION'\n",
        "            OR v_draft.payload->>'variant' IS DISTINCT FROM 'CHARGE_REDUCTION'\n"
        "            OR v_draft.payload->'target_kind' IS NOT NULL\n",
    ),
)

SQL = r"""
    -- The draft's Late-payment Charge reduction, checked for shape only and stored in one form:
    -- malformed input 22023.
    CREATE FUNCTION app.settlement_late_charge_reduction_input(p_reduction jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_charge text;
    BEGIN
        IF p_reduction IS NULL OR jsonb_typeof(p_reduction) IS DISTINCT FROM 'object'
            -- The byte order, whatever the database collation.
            OR (SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(p_reduction) key)
                IS DISTINCT FROM ARRAY['amount_usd_cents','late_payment_charge_id']
        THEN RAISE EXCEPTION 'Late-payment Charge reduction input is invalid' USING ERRCODE='22023'; END IF;
        v_charge:=app.final_settlement_plan_id(p_reduction->'late_payment_charge_id');
        IF v_charge IS NULL
            OR jsonb_typeof(p_reduction->'amount_usd_cents') IS DISTINCT FROM 'number'
            OR (p_reduction->>'amount_usd_cents') !~ '^[1-9][0-9]{0,15}$'
        THEN RAISE EXCEPTION 'Late-payment Charge reduction input is invalid' USING ERRCODE='22023'; END IF;
        -- The cap of the other money writers; a JSON number always casts.
        IF (p_reduction->>'amount_usd_cents')::numeric>9000000000000000 THEN
            RAISE EXCEPTION 'Late-payment Charge reduction input is invalid' USING ERRCODE='22023'; END IF;
        RETURN jsonb_build_object('late_payment_charge_id',v_charge,
            'amount_usd_cents',(p_reduction->>'amount_usd_cents')::bigint);
    END $$;

    -- A Late-payment Charge's current obligation: its original amount after every correction (as
    -- app.correct_late_payment_charge counts it).
    CREATE FUNCTION app.settlement_late_charge_obligation(p_charge uuid)
    RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT charge.original_amount_usd_cents+COALESCE((SELECT sum(CASE correction.correction_kind
                WHEN 'REDUCTION' THEN -correction.amount_usd_cents
                WHEN 'CHARGE_REVERSAL' THEN -correction.amount_usd_cents
                ELSE correction.amount_usd_cents END)
            FROM app.late_payment_charge_corrections correction
            WHERE correction.late_payment_charge_id=charge.id),0)
        FROM app.late_payment_charges charge WHERE charge.id=p_charge
    $$;

    -- The state a Late-payment Charge reduction depends on; its digest is the draft's source
    -- revision. A Payment, Credit or Deposit value on the Charge, or a correction of it, changes it.
    CREATE FUNCTION app.settlement_late_charge_reduction_source_state(p_settlement uuid,p_charge uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        SELECT jsonb_build_object(
            'settlement',(SELECT jsonb_build_object('id',settlement.id,'closed_at',settlement.closed_at,
                    'lease_id',settlement.lease_id)
                FROM app.final_settlements settlement WHERE settlement.id=p_settlement),
            'charge',(SELECT jsonb_build_object('id',charge.id,'customer_id',charge.customer_id,
                    'source_invoice_id',charge.source_invoice_id,'lease_id',invoice.lease_id,
                    'invoice_void',invoice.status='VOID',
                    'obligation_usd_cents',app.settlement_late_charge_obligation(charge.id),
                    'corrections',(SELECT jsonb_build_object('count',count(*),'latest_at',max(correction.occurred_at),
                            'reversed',COALESCE(bool_or(correction.correction_kind='CHARGE_REVERSAL'),false))
                        FROM app.late_payment_charge_corrections correction
                        WHERE correction.late_payment_charge_id=charge.id),
                    'applications',app.late_payment_charge_application_summary(charge.id))
                FROM app.late_payment_charges charge
                JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
                WHERE charge.id=p_charge))
    $$;

    -- Checks a stored-form reduction against the current state and returns what the draft records:
    -- the Lease, the Charge's Customer, the reduction and the source revision. An unknown
    -- Settlement or a Charge not of its Lease P0002; a state the correction does not allow 55000.
    CREATE FUNCTION app.settlement_late_charge_reduction_plan(p_property uuid,p_settlement uuid,
        p_reduction jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_settlement app.final_settlements%ROWTYPE; v_charge app.late_payment_charges%ROWTYPE;
        v_invoice app.invoices%ROWTYPE; v_summary jsonb;
    BEGIN
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=p_settlement AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        IF v_settlement.closed_at IS NULL THEN
            RAISE EXCEPTION 'A post-settlement correction needs a closed Final Settlement'
                USING ERRCODE='55000'; END IF;
        SELECT charge.* INTO v_charge FROM app.late_payment_charges charge
        JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
        WHERE charge.id=(p_reduction->>'late_payment_charge_id')::uuid
          AND invoice.lease_id=v_settlement.lease_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The reduced Late-payment Charge is not a Charge of this Final Settlement'
                USING ERRCODE='P0002'; END IF;
        SELECT * INTO STRICT v_invoice FROM app.invoices WHERE id=v_charge.source_invoice_id;
        IF v_invoice.status='VOID' OR EXISTS(SELECT 1 FROM app.late_payment_charge_corrections correction
            WHERE correction.late_payment_charge_id=v_charge.id AND correction.correction_kind='CHARGE_REVERSAL')
        THEN RAISE EXCEPTION 'The reduced Late-payment Charge is not an open obligation of this Final Settlement'
            USING ERRCODE='55000'; END IF;
        v_summary:=app.late_payment_charge_application_summary(v_charge.id);
        -- 8a-1: a Charge that a Deposit application paid takes no correction, as the Invoice-line
        -- form (the paid case is sub-slice 10c-3b).
        IF (v_summary->>'deposit_total_usd_cents')::bigint>0 THEN
            RAISE EXCEPTION 'A Deposit application paid this obligation at Final Settlement'
                USING ERRCODE='55000'; END IF;
        -- Design note: a reduction removes only the unpaid rest; releasing paid value is a REFUND.
        IF (p_reduction->>'amount_usd_cents')::bigint
            >app.settlement_late_charge_obligation(v_charge.id)-(v_summary->>'active_total_usd_cents')::bigint
        THEN RAISE EXCEPTION 'The charge reduction would release paid value' USING ERRCODE='55000'; END IF;
        RETURN jsonb_build_object('lease_id',v_settlement.lease_id,'customer_id',v_charge.customer_id,
            'reduction',p_reduction,
            'source_revision','settlement-correction:' || encode(sha256(convert_to(
                app.settlement_late_charge_reduction_source_state(p_settlement,v_charge.id)::text,
                'UTF8')),'hex'));
    END $$;

    -- Staff record a Late-payment Charge reduction correction draft (final_settlements.prepare); it
    -- has no financial effect until a financial.approve holder confirms it.
    CREATE FUNCTION app.record_settlement_late_charge_reduction_draft(p_property uuid,p_actor uuid,
        p_draft uuid,p_settlement uuid,p_reduction jsonb,p_reason text,p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_existing app.financial_drafts%ROWTYPE; v_input jsonb; v_plan jsonb; v_payload jsonb;
    BEGIN
        PERFORM app.require_invoice_command_actor(p_property,p_actor);
        PERFORM app.assert_active_financial_actor(p_actor,p_property);
        IF p_authorization IS DISTINCT FROM 'final_settlements.prepare' THEN
            RAISE EXCEPTION 'Post-settlement correction draft authorization is invalid'
                USING ERRCODE='42501'; END IF;
        -- The reason is at most 500 characters: the Charge correction keeps it (as
        -- app.correct_late_payment_charge).
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_settlement IS NULL
            OR app.lease_notice_text_valid(p_reason,500) IS NOT TRUE
        THEN RAISE EXCEPTION 'Late-payment Charge reduction input is invalid' USING ERRCODE='22023'; END IF;
        v_input:=app.settlement_late_charge_reduction_input(p_reduction);
        -- An exact repeat replays before any current-state check.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
        IF FOUND THEN
            IF v_existing.property_id=p_property AND v_existing.kind='SETTLEMENT_CORRECTION'
                AND v_existing.payload->>'variant'='CHARGE_REDUCTION'
                AND v_existing.payload->>'target_kind'='LATE_PAYMENT_CHARGE'
                AND v_existing.prepared_by=p_actor AND v_existing.reason=p_reason
                AND v_existing.payload->>'final_settlement_id'=p_settlement::text
                AND v_existing.payload->'reduction'=v_input
            -- The decision's transaction id never leaves the database (sub-slice 10b).
            THEN RETURN app.financial_draft_json(v_existing) #- '{decision,result,transaction_id}'; END IF;
            RAISE EXCEPTION 'Post-settlement correction draft identity was reused' USING ERRCODE='P5205';
        END IF;
        v_plan:=app.settlement_late_charge_reduction_plan(p_property,p_settlement,v_input);
        v_payload:=jsonb_build_object('variant','CHARGE_REDUCTION','target_kind','LATE_PAYMENT_CHARGE',
            'final_settlement_id',p_settlement,'lease_id',v_plan->'lease_id',
            'customer_id',v_plan->'customer_id','reduction',v_plan->'reduction');
        RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'SETTLEMENT_CORRECTION',
            'final_settlements.prepare',v_payload,v_plan->>'source_revision',p_reason);
    END $$;

    -- What the confirm returns, also for an exact repeat (rebuilt from the stored records): the
    -- draft without the decision's transaction id, the correction header, the linked Charge
    -- correction and the Charge.
    CREATE FUNCTION app.settlement_late_charge_reduction_result(p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT jsonb_build_object(
            'draft',app.financial_draft_json(draft) #- '{decision,result,transaction_id}',
            'settlement_correction',(SELECT jsonb_build_object('id',correction.id,
                    'final_settlement_id',correction.final_settlement_id,'reason',correction.reason,
                    'occurred_at',correction.occurred_at,'actor_id',correction.actor_id,
                    'authorization_reference',correction.authorization_reference)
                FROM app.settlement_corrections correction
                WHERE correction.id=app.settlement_correction_id(draft.id)),
            'late_payment_charge_correction',(SELECT jsonb_build_object('id',charge_correction.id,
                    'late_payment_charge_id',charge_correction.late_payment_charge_id,
                    'correction_kind',charge_correction.correction_kind,
                    'amount_usd_cents',charge_correction.amount_usd_cents,
                    'previous_obligation_usd_cents',charge_correction.previous_obligation_usd_cents,
                    'resulting_obligation_usd_cents',charge_correction.resulting_obligation_usd_cents,
                    'reason',charge_correction.reason,'occurred_at',charge_correction.occurred_at,
                    'actor_id',charge_correction.actor_id,
                    'authorization_reference',charge_correction.authorization_reference)
                FROM app.settlement_correction_effects effect
                JOIN app.late_payment_charge_corrections charge_correction
                    ON charge_correction.id=effect.late_payment_charge_correction_id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)),
            'late_payment_charge',app.late_payment_charge_snapshot((SELECT
                    charge_correction.late_payment_charge_id
                FROM app.settlement_correction_effects effect
                JOIN app.late_payment_charge_corrections charge_correction
                    ON charge_correction.id=effect.late_payment_charge_correction_id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id))))
        FROM app.financial_drafts draft WHERE draft.id=p_draft
    $$;

    -- A financial.approve holder confirms a Late-payment Charge reduction correction. Refusals: an
    -- unknown Property, draft or Settlement P0002/P4501; an inactive or missing approver P4506 or
    -- 42501; business state (a decided draft, an open Settlement) 55000; a draft whose sources
    -- changed since it was recorded P5S02 (stale; it stays pending). Nothing is written unless
    -- everything succeeds.
    CREATE FUNCTION app.confirm_settlement_late_charge_reduction(p_property uuid,p_actor uuid,p_draft uuid,
        p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_draft app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_charge app.late_payment_charges%ROWTYPE; v_timezone text; v_now timestamptz;
        v_business_date date; v_reduction jsonb; v_plan jsonb; v_correction uuid; v_row uuid;
        v_amount bigint; v_current bigint; v_kind text; v_lease uuid; v_unit uuid; v_before jsonb;
        v_after jsonb; v_evidence jsonb; v_result jsonb;
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
              AND draft.payload->>'variant'='CHARGE_REDUCTION'
              AND draft.payload->>'target_kind'='LATE_PAYMENT_CHARGE' AND decision.decision='CONFIRMED'
              AND decision.decided_by=p_actor)
        THEN RETURN app.settlement_late_charge_reduction_result(p_draft); END IF;
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
        IF NOT FOUND OR v_draft.kind<>'SETTLEMENT_CORRECTION'
            OR v_draft.prepare_capability<>'final_settlements.prepare'
            OR v_draft.payload->>'variant' IS DISTINCT FROM 'CHARGE_REDUCTION'
            OR v_draft.payload->>'target_kind' IS DISTINCT FROM 'LATE_PAYMENT_CHARGE'
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
        -- The stored reduction passes the recorder's shape check again.
        v_reduction:=app.settlement_late_charge_reduction_input(v_draft.payload->'reduction');
        IF v_reduction IS DISTINCT FROM v_draft.payload->'reduction' THEN
            RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        v_amount:=(v_reduction->>'amount_usd_cents')::bigint;
        -- Lock order, the 8e-3 order: the draft lock (above); the Settlement's draft lock; the
        -- Lease row FOR UPDATE; the Charge row and its Invoice FOR UPDATE (the order of
        -- app.lock_payment_allocation_target, so a Payment or Credit on the Charge commits before or
        -- waits); app.begin_settlement_correction locks the draft row and the Settlement row.
        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));
        PERFORM 1 FROM app.leases WHERE id=v_settlement.lease_id FOR UPDATE;
        SELECT * INTO v_charge FROM app.late_payment_charges
        WHERE id=(v_reduction->>'late_payment_charge_id')::uuid FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The reduced Late-payment Charge is not a Charge of this Final Settlement'
                USING ERRCODE='P0002'; END IF;
        PERFORM 1 FROM app.invoices WHERE id=v_charge.source_invoice_id FOR UPDATE;
        -- Under the locks, the sources still have the digest the draft recorded, and the check of
        -- the recorder still gives the same result; otherwise the draft is stale and stays pending.
        IF 'settlement-correction:' || encode(sha256(convert_to(app.settlement_late_charge_reduction_source_state(
                v_settlement.id,v_charge.id)::text,'UTF8')),'hex')
            IS DISTINCT FROM v_draft.source_revision
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        v_plan:=app.settlement_late_charge_reduction_plan(p_property,v_settlement.id,v_reduction);
        IF v_plan->>'source_revision' IS DISTINCT FROM v_draft.source_revision
            OR v_plan->'lease_id' IS DISTINCT FROM v_draft.payload->'lease_id'
            OR v_plan->'customer_id' IS DISTINCT FROM v_draft.payload->'customer_id'
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        SELECT invoice.lease_id,lease.unit_id INTO STRICT v_lease,v_unit FROM app.invoices invoice
        JOIN app.leases lease ON lease.id=invoice.lease_id WHERE invoice.id=v_charge.source_invoice_id;
        v_current:=app.settlement_late_charge_obligation(v_charge.id);
        -- BR-LATE-005 and the Charge correction row's rules: removing the whole current obligation
        -- is the Charge reversal (terminal); any smaller amount is a reduction.
        v_kind:=CASE WHEN v_amount=v_current THEN 'CHARGE_REVERSAL' ELSE 'REDUCTION' END;

        -- The decision, then the header (sub-slice 10a). From here every record is linked before
        -- it is written, and every id is fresh, never derived from the draft (sub-slice 10b).
        v_correction:=app.begin_settlement_correction(p_property,p_actor,p_draft,'financial.approve');
        -- Stamped after the approval and after the Charge's latest correction (its chronology).
        v_now:=GREATEST(clock_timestamp(),COALESCE((SELECT max(correction.occurred_at)
            FROM app.late_payment_charge_corrections correction
            WHERE correction.late_payment_charge_id=v_charge.id),'-infinity')+interval '1 microsecond');
        v_business_date:=timezone(v_timezone,v_now)::date;
        v_row:=gen_random_uuid();
        v_before:=app.late_payment_charge_snapshot(v_charge.id);
        v_evidence:=jsonb_build_object('capability','financial.approve','draft_id',p_draft,
            'settlement_correction_id',v_correction,'final_settlement_id',v_settlement.id,
            'variant','CHARGE_REDUCTION','target_kind','LATE_PAYMENT_CHARGE');
        PERFORM app.link_settlement_correction_effect(v_correction,'late_payment_charge_correction_id',v_row);
        INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,correction_kind,
            amount_usd_cents,reverses_correction_id,reason,previous_obligation_usd_cents,
            resulting_obligation_usd_cents,occurred_at,actor_id,authorization_reference,correlation_id)
        VALUES (v_row,v_charge.id,v_kind,v_amount,NULL,v_draft.reason,v_current,v_current-v_amount,
            v_now,p_actor,'financial.approve',v_correction);
        -- Every linked record is written: the deferred checks run now, inside this definer
        -- function, as the existing writers run them (sub-slice 10b plan note).
        SET CONSTRAINTS ALL IMMEDIATE;
        v_after:=app.late_payment_charge_snapshot(v_charge.id);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
            entity_id,reason,authorization_reference,property_id,previous_state,resulting_state,
            correlation_id,source,outcome,authorization_evidence,linked_source_event_id,customer_id,
            lease_id)
        VALUES (gen_random_uuid(),v_now,v_business_date,p_actor,'late_payment.charge_corrected',
            'late_payment_charge',v_charge.id,v_draft.reason,'financial.approve',p_property,v_before,
            v_after,v_correction,'API','SUCCEEDED',
            v_evidence || jsonb_build_object('kind',v_kind,'amount_usd_cents',v_amount),
            v_row,v_charge.customer_id,v_lease);
        v_result:=app.settlement_late_charge_reduction_result(p_draft);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
        VALUES (gen_random_uuid(),v_now,v_business_date,p_actor,'final_settlement.correction.confirmed',
            'settlement_correction',v_correction,v_draft.reason,'financial.approve',p_property,
            '{}'::jsonb,
            jsonb_build_object('settlement_correction_id',v_correction,
                'final_settlement_id',v_settlement.id,'variant','CHARGE_REDUCTION',
                'target_kind','LATE_PAYMENT_CHARGE','late_payment_charge_id',v_charge.id,
                'late_payment_charge_correction_id',v_row,'correction_kind',v_kind,
                'customer_id',v_charge.customer_id,'amount_usd_cents',v_amount),
            v_correction,'API','SUCCEEDED',v_evidence,v_charge.customer_id,v_lease,v_unit);
        RETURN v_result;
    END $$;
"""

INTERNAL = (
    "app.settlement_late_charge_reduction_input(jsonb)",
    "app.settlement_late_charge_obligation(uuid)",
    "app.settlement_late_charge_reduction_source_state(uuid,uuid)",
    "app.settlement_late_charge_reduction_plan(uuid,uuid,jsonb)",
    "app.settlement_late_charge_reduction_result(uuid)",
)
RECORD = "app.record_settlement_late_charge_reduction_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_late_charge_reduction(uuid,uuid,uuid,text)"


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
            raise RuntimeError(f"Late-payment Charge reduction source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(SQL)
    _patch(LINE_CONFIRM, LINE_CONFIRM_REPLACEMENTS)
    for function in (*INTERNAL, RECORD, CONFIRM):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for function in (RECORD, CONFIRM):
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Late-payment Charge reduction migration is forward-only")
