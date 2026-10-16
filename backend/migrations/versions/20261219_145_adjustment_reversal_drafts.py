# ruff: noqa: E501
"""The mistaken credit Adjustment reversal before closure (V1-056 sub-slice 10f-1).

BR-INV-044, BR-CREDIT-006, BR-CREDIT-008, BR-AUTH-010, BR-SETTLE-013; DB-INV-010, DB-CREDIT-002;
owner answer 7 to Q-2026-10-06-36 and the slice 10 entry of the plan (owner answer to the 8f
report):

- A mistaken credit Adjustment is reversed through a draft of the new kind ADJUSTMENT_REVERSAL: an
  invoices.adjust holder records it with a reason, and only a financial.approve holder confirms it.
  The draft lists the Adjustment's line and, for each release of paid value the Adjustment made
  (migration 20261003_67), its Credit, the Credit's available value, the part that goes back on the
  line and the part that stays as debt.
- In one transaction the confirm writes the decision and then the first writer of
  app.invoice_adjustment_reversals (DB-INV-010): the reversal row, the Invoice status and version,
  then the put-back. For each release in its written order, the part of its Credit still available
  is applied to the line again, never more than the release and the line's unpaid rest
  (BR-CREDIT-008: the Invoice Customer's own Credit; BR-CREDIT-006: the Rent-first proposal, which
  must put the whole amount on the Adjustment's line). The rest of the release stays as debt on the
  line. One audit event invoice.adjustment_reversed.
- Refused (55000): a debit Adjustment; a reversed one; one that a hand-back or unpaid-Initial
  resolution wrote (Q-2026-10-16-118 point 2); one linked to a post-settlement correction; one whose
  Lease's Final Settlement is closed (sub-slice 10f-2 reverses it through a correction); a second
  waiting draft of the same Adjustment; and, until the owner answers Q-2026-10-16-118 point 1, a
  put-back that the Rent-first order would put on another line.

Relaxing changes: the draft kind, preparer, kind-preparer and WITHDRAWN checks gain
ADJUSTMENT_REVERSAL and invoices.adjust; the two capability-scoped draft reads accept nine
capabilities. New functions otherwise; no table, column, trigger or other grant change.
"""

from alembic import op
from sqlalchemy import text

revision = "20261219_145"
down_revision = "20261218_144"
branch_labels = None
depends_on = None

FUNCTION_SQL = r"""
    -- Sub-slice 10f-1: what an Adjustment reversal would restore and put back, and the refusal
    -- that applies (NULL when none). P0002 for an Adjustment that is not on the Property.
    CREATE FUNCTION app.adjustment_reversal_source(p_property uuid,p_adjustment uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_adjustment app.invoice_adjustments%ROWTYPE; v_invoice app.invoices%ROWTYPE;
        v_line app.invoice_lines%ROWTYPE; v_rest bigint; v_row record; v_available bigint;
        v_put bigint; v_used jsonb:='{}'::jsonb; v_releases jsonb:='[]'::jsonb;
        v_put_total bigint:=0; v_debt_total bigint:=0; v_refusal text;
    BEGIN
        SELECT * INTO v_adjustment FROM app.invoice_adjustments WHERE id=p_adjustment;
        IF NOT FOUND OR app.invoice_property_id(v_adjustment.invoice_id) IS DISTINCT FROM p_property
        THEN RAISE EXCEPTION 'Invoice Adjustment was not found' USING ERRCODE='P0002'; END IF;
        SELECT * INTO STRICT v_invoice FROM app.invoices WHERE id=v_adjustment.invoice_id;
        SELECT * INTO STRICT v_line FROM app.invoice_lines WHERE id=v_adjustment.invoice_line_id;
        -- The line's unpaid rest once the reversal restores the credit Adjustment's amount.
        v_rest:=app.invoice_line_outstanding(v_line.id)
            +CASE v_adjustment.adjustment_type WHEN 'CREDIT' THEN v_adjustment.amount_usd_cents ELSE 0 END;
        -- Each release in its written order: the part of its Credit still available goes back on
        -- the line (earlier put-backs from the same Credit counted); the rest stays as debt. A
        -- reversed Credit, a Payment no longer received or another Customer's Credit gives 0.
        FOR v_row IN
            SELECT release.id,release.source_kind,release.released_usd_cents,
                COALESCE(release.customer_credit_id,application.customer_credit_id) AS credit_id
            FROM app.invoice_credit_excess_releases release
            LEFT JOIN app.customer_credit_applications application
                ON application.id=release.reversed_credit_application_id
            WHERE release.invoice_adjustment_id=v_adjustment.id
            ORDER BY release.created_at,release.id
        LOOP
            SELECT CASE WHEN payment.status<>'RECEIVED'
                    OR credit.customer_id IS DISTINCT FROM v_invoice.customer_id THEN 0
                    ELSE GREATEST(app.credit_available_value(credit.id),0) END
            INTO STRICT v_available
            FROM app.customer_credits credit
            JOIN app.payments payment ON payment.id=credit.source_payment_id
            WHERE credit.id=v_row.credit_id;
            v_available:=GREATEST(v_available-COALESCE((v_used->>v_row.credit_id::text)::bigint,0),0);
            v_put:=LEAST(v_row.released_usd_cents,v_available,GREATEST(v_rest,0));
            v_rest:=v_rest-v_put;
            v_used:=v_used||jsonb_build_object(v_row.credit_id::text,
                COALESCE((v_used->>v_row.credit_id::text)::bigint,0)+v_put);
            v_put_total:=v_put_total+v_put;
            v_debt_total:=v_debt_total+v_row.released_usd_cents-v_put;
            v_releases:=v_releases||jsonb_build_array(jsonb_build_object(
                'invoice_credit_excess_release_id',v_row.id,'source_kind',v_row.source_kind,
                'customer_credit_id',v_row.credit_id,'released_usd_cents',v_row.released_usd_cents,
                'available_usd_cents',v_available,'credit_latest_at',app.credit_latest_at(v_row.credit_id),
                'put_back_usd_cents',v_put,'debt_usd_cents',v_row.released_usd_cents-v_put));
        END LOOP;
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
            WHEN EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                WHERE effect.invoice_adjustment_id=v_adjustment.id) THEN
                'An Adjustment of a post-settlement correction is not reversed by an Adjustment reversal draft'
            WHEN EXISTS(SELECT 1 FROM app.final_settlements settlement
                WHERE settlement.lease_id=v_invoice.lease_id AND settlement.closed_at IS NOT NULL) THEN
                'The Lease''s Final Settlement is closed; the Adjustment is reversed through a correction of that Final Settlement'
            -- Q-2026-10-16-118 point 1 (fail closed until the owner answers): the Rent-first order
            -- (Rent, then Service Charges, then other lines, by line sequence) must choose the
            -- Adjustment's line, so no line before it may still owe.
            WHEN v_put_total>0 AND EXISTS(SELECT 1 FROM app.invoice_lines other
                WHERE other.invoice_id=v_invoice.id AND other.id<>v_line.id
                  AND (CASE other.category WHEN 'RENT' THEN 0 WHEN 'SERVICE_CHARGES' THEN 1 ELSE 2 END,
                        other.line_sequence,other.id)
                    <(CASE v_line.category WHEN 'RENT' THEN 0 WHEN 'SERVICE_CHARGES' THEN 1 ELSE 2 END,
                        v_line.line_sequence,v_line.id)
                  AND app.invoice_line_outstanding(other.id)>0) THEN
                'The Credit put-back would go on another line by the Rent-first order; this waits for the owner'
        END;
        RETURN jsonb_build_object('invoice_adjustment_id',v_adjustment.id,
            'adjustment_type',v_adjustment.adjustment_type,'amount_usd_cents',v_adjustment.amount_usd_cents,
            'invoice_id',v_invoice.id,'invoice_line_id',v_line.id,'customer_id',v_invoice.customer_id,
            'lease_id',v_invoice.lease_id,'invoice_status',v_invoice.status,'invoice_version',v_invoice.version,
            'line_outstanding_usd_cents',app.invoice_line_outstanding(v_line.id),
            'releases',v_releases,'put_back_usd_cents',v_put_total,'debt_usd_cents',v_debt_total,
            'refusal',v_refusal);
    END $$;

    -- A time strictly later than every financial event of the Invoice: its allocations,
    -- Adjustments, Late-payment Decision, Credit applications and their reversals, and its last
    -- change (the order app.serialize_invoice_adjustment_source checks).
    CREATE FUNCTION app.adjustment_reversal_instant(p_invoice uuid)
    RETURNS timestamptz LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT GREATEST(clock_timestamp(),
            COALESCE(app.allocation_target_latest_at('INVOICE',p_invoice),'-infinity')
                +interval '1 microsecond',
            COALESCE((SELECT max(event_at) FROM (
                SELECT application.occurred_at AS event_at
                FROM app.customer_credit_applications application WHERE application.invoice_id=p_invoice
                UNION ALL SELECT reversal.occurred_at
                FROM app.customer_credit_application_reversals reversal
                JOIN app.customer_credit_applications application
                    ON application.id=reversal.credit_application_id
                WHERE application.invoice_id=p_invoice) events),'-infinity')+interval '1 microsecond',
            (SELECT updated_at FROM app.invoices WHERE id=p_invoice))
    $$;

    -- The result of a confirmed Adjustment reversal, read from the stored rows (a replay returns
    -- the same).
    CREATE FUNCTION app.adjustment_reversal_result(p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        SELECT jsonb_build_object('draft_id',draft.id,'invoice_adjustment_reversal_id',reversal.id,
            'invoice_adjustment_id',adjustment.id,'invoice_id',adjustment.invoice_id,
            'invoice_line_id',adjustment.invoice_line_id,'restored_usd_cents',adjustment.amount_usd_cents,
            'reason',reversal.reason,'occurred_at',reversal.occurred_at,'actor_id',reversal.actor_id,
            'authorization_reference',reversal.authorization_reference,
            'put_backs',COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'credit_application_id',application.id,
                    'customer_credit_id',application.customer_credit_id,
                    'invoice_credit_excess_release_id',entry.item->'invoice_credit_excess_release_id',
                    'amount_usd_cents',application.amount_usd_cents) ORDER BY entry.position)
                FROM jsonb_array_elements(decision.result->'put_backs') WITH ORDINALITY AS entry(item,position)
                JOIN app.customer_credit_applications application
                    ON application.id=(entry.item->>'credit_application_id')::uuid),'[]'::jsonb),
            'debt_usd_cents',(decision.result->>'debt_usd_cents')::bigint)
        FROM app.financial_drafts draft
        JOIN app.financial_draft_decisions decision
            ON decision.draft_id=draft.id AND decision.decision='CONFIRMED'
        JOIN app.invoice_adjustment_reversals reversal
            ON reversal.id=(decision.result->>'invoice_adjustment_reversal_id')::uuid
        JOIN app.invoice_adjustments adjustment ON adjustment.id=reversal.invoice_adjustment_id
        WHERE draft.id=p_draft AND draft.kind='ADJUSTMENT_REVERSAL'
    $$;

    -- Staff record an Adjustment reversal draft (invoices.adjust); it has no financial effect
    -- until a financial.approve holder confirms it.
    CREATE FUNCTION app.record_adjustment_reversal_draft(p_property uuid,p_actor uuid,p_draft uuid,
        p_adjustment uuid,p_reason text,p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_existing app.financial_drafts%ROWTYPE; v_input jsonb; v_source jsonb; v_payload jsonb;
    BEGIN
        PERFORM app.require_invoice_command_actor(p_property,p_actor);
        PERFORM app.assert_active_financial_actor(p_actor,p_property);
        IF p_authorization IS DISTINCT FROM 'invoices.adjust' THEN
            RAISE EXCEPTION 'Adjustment reversal draft authorization is invalid' USING ERRCODE='42501'; END IF;
        -- The one-draft-per-Adjustment lock and the source read rely on READ COMMITTED (as the
        -- Payment return recorder).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'An Adjustment reversal draft is recorded at READ COMMITTED' USING ERRCODE='55000'; END IF;
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_adjustment IS NULL
            OR app.lease_notice_text_valid(p_reason,1000) IS NOT TRUE
        THEN RAISE EXCEPTION 'Adjustment reversal draft input is invalid' USING ERRCODE='22023'; END IF;
        v_input:=jsonb_build_object('invoice_adjustment_id',p_adjustment);
        -- An exact repeat replays before any current-state check.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
        IF FOUND THEN
            IF v_existing.property_id=p_property AND v_existing.kind='ADJUSTMENT_REVERSAL'
                AND v_existing.prepared_by=p_actor AND v_existing.reason=p_reason
                AND (v_existing.payload-'source')=v_input
            -- No result or replay shows the decision's transaction id (sub-slice 10b).
            THEN RETURN app.financial_draft_json(v_existing) #- '{decision,result,transaction_id}'; END IF;
            RAISE EXCEPTION 'Adjustment reversal draft identity was reused' USING ERRCODE='P5205';
        END IF;
        -- Drafts of one Adjustment are serialized, so only one may wait.
        PERFORM pg_advisory_xact_lock(hashtextextended('adjustment-reversal:' || p_adjustment::text,0));
        v_source:=app.adjustment_reversal_source(p_property,p_adjustment);
        IF v_source->>'refusal' IS NOT NULL THEN
            RAISE EXCEPTION '%',v_source->>'refusal' USING ERRCODE='55000'; END IF;
        IF EXISTS(SELECT 1 FROM app.financial_drafts draft
            WHERE draft.property_id=p_property AND draft.kind='ADJUSTMENT_REVERSAL'
              AND draft.payload->>'invoice_adjustment_id'=p_adjustment::text
              AND NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                  WHERE decision.draft_id=draft.id))
        THEN RAISE EXCEPTION 'Another Adjustment reversal draft of this Adjustment is waiting'
            USING ERRCODE='55000'; END IF;
        v_payload:=v_input || jsonb_build_object('source',v_source);
        IF octet_length(v_payload::text)>16000 THEN
            RAISE EXCEPTION 'The Adjustment reversal draft exceeds the stored draft size of 16000 bytes'
                USING ERRCODE='22023'; END IF;
        RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'ADJUSTMENT_REVERSAL','invoices.adjust',
            v_payload,'adjustment-reversal:' || encode(sha256(convert_to(v_source::text,'UTF8')),'hex'),
            p_reason);
    END $$;

    -- A financial.approve holder confirms an Adjustment reversal draft: in one transaction the
    -- decision, the reversal, the Invoice status and version, and the put-back. Refusals: an
    -- unknown Property or draft P0002/P4501; an inactive or missing approver P4506 or 42501;
    -- business state 55000; a draft whose sources changed P5S02 (stale; it stays pending).
    -- Nothing is written unless everything succeeds.
    CREATE FUNCTION app.confirm_adjustment_reversal(p_property uuid,p_actor uuid,p_draft uuid,p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_timezone text; v_draft app.financial_drafts%ROWTYPE; v_adjustment app.invoice_adjustments%ROWTYPE;
        v_invoice app.invoices%ROWTYPE; v_line app.invoice_lines%ROWTYPE; v_source jsonb; v_row record;
        v_item jsonb; v_reversal uuid; v_at timestamptz; v_put_at timestamptz; v_before jsonb;
        v_plan jsonb; v_proposal jsonb; v_put bigint; v_result jsonb;
    BEGIN
        v_timezone:=app.require_invoice_command_actor(p_property,p_actor);
        -- BR-AUTH-010: a person confirms; an inactive approver is refused above (P4506).
        IF NOT EXISTS(SELECT 1 FROM app.actor_identities identity
            WHERE identity.actor_id=p_actor AND identity.identity_kind='HUMAN')
        THEN RAISE EXCEPTION 'An Adjustment reversal is confirmed only by a human approver'
            USING ERRCODE='42501'; END IF;
        IF p_authorization IS DISTINCT FROM 'financial.approve' THEN
            RAISE EXCEPTION 'Only financial.approve may confirm an Adjustment reversal' USING ERRCODE='42501'; END IF;
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' THEN
            RAISE EXCEPTION 'Adjustment reversal input is invalid' USING ERRCODE='22023'; END IF;
        -- The serialization of every decision on this draft, then the replay of an exact repeat.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        IF EXISTS(SELECT 1 FROM app.financial_drafts draft
            JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id
            WHERE draft.id=p_draft AND draft.property_id=p_property AND draft.kind='ADJUSTMENT_REVERSAL'
              AND decision.decision='CONFIRMED' AND decision.decided_by=p_actor)
        THEN RETURN app.adjustment_reversal_result(p_draft); END IF;
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
        IF NOT FOUND OR v_draft.kind<>'ADJUSTMENT_REVERSAL' OR v_draft.prepare_capability<>'invoices.adjust'
            OR v_draft.payload->>'invoice_adjustment_id' IS NULL
            OR v_draft.payload->>'invoice_adjustment_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        THEN RAISE EXCEPTION 'Adjustment reversal draft was not found' USING ERRCODE='P0002'; END IF;
        IF EXISTS(SELECT 1 FROM app.financial_draft_decisions WHERE draft_id=p_draft) THEN
            RAISE EXCEPTION 'Financial draft is already decided' USING ERRCODE='55000'; END IF;
        -- The checks below rely on READ COMMITTED: each statement sees the commits the locks waited
        -- for (as the Payment return confirm).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'An Adjustment reversal is confirmed at READ COMMITTED' USING ERRCODE='55000'; END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended(
            'adjustment-reversal:' || (v_draft.payload->>'invoice_adjustment_id'),0));
        SELECT * INTO v_adjustment FROM app.invoice_adjustments
        WHERE id=(v_draft.payload->>'invoice_adjustment_id')::uuid;
        IF NOT FOUND OR app.invoice_property_id(v_adjustment.invoice_id) IS DISTINCT FROM p_property THEN
            RAISE EXCEPTION 'Invoice Adjustment was not found' USING ERRCODE='P0002'; END IF;
        -- Lock order of app.post_credit_application, the writer of the same Credit applications:
        -- each released Credit's Payment (its serialization row, then the row) in id order, the
        -- Credits in id order, then the Invoice and its lines. app.adjust_invoice and the Final
        -- Settlement confirm lock the Invoice first; a deadlock with them is detected (40P01) and
        -- is a conflict, with nothing written.
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
        v_source:=app.adjustment_reversal_source(p_property,v_adjustment.id);
        IF 'adjustment-reversal:' || encode(sha256(convert_to(v_source::text,'UTF8')),'hex')
            IS DISTINCT FROM v_draft.source_revision
        THEN RAISE EXCEPTION 'The Adjustment reversal draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        IF v_source->>'refusal' IS NOT NULL THEN
            RAISE EXCEPTION '%',v_source->>'refusal' USING ERRCODE='55000'; END IF;
        SELECT * INTO STRICT v_line FROM app.invoice_lines WHERE id=v_adjustment.invoice_line_id;

        -- Every id is fresh; the decision names the reversal and each put-back before they are
        -- written, so the result is read from the stored rows.
        v_reversal:=gen_random_uuid();
        SELECT COALESCE(jsonb_agg(entry.item||jsonb_build_object('credit_application_id',gen_random_uuid())
                ORDER BY entry.position),'[]'::jsonb)
        INTO v_plan
        FROM jsonb_array_elements(v_source->'releases') WITH ORDINALITY AS entry(item,position)
        WHERE (entry.item->>'put_back_usd_cents')::bigint>0;
        -- The reversal advances the Invoice version once, and a put-back once more (the refresh).
        IF (v_invoice.version>2147483647-(CASE WHEN jsonb_array_length(v_plan)>0 THEN 2 ELSE 1 END)) THEN
            RAISE EXCEPTION 'Invoice version cannot advance' USING ERRCODE='55000'; END IF;
        PERFORM app.confirm_financial_draft_record(p_property,p_actor,p_draft,'ADJUSTMENT_REVERSAL',
            jsonb_build_object('invoice_adjustment_reversal_id',v_reversal,
                'invoice_adjustment_id',v_adjustment.id,
                'put_backs',(SELECT COALESCE(jsonb_agg(jsonb_build_object(
                        'credit_application_id',entry.item->'credit_application_id',
                        'invoice_credit_excess_release_id',entry.item->'invoice_credit_excess_release_id',
                        'customer_credit_id',entry.item->'customer_credit_id',
                        'amount_usd_cents',entry.item->'put_back_usd_cents') ORDER BY entry.position),
                        '[]'::jsonb)
                    FROM jsonb_array_elements(v_plan) WITH ORDINALITY AS entry(item,position)),
                'debt_usd_cents',(v_source->>'debt_usd_cents')::bigint,
                'transaction_id',pg_current_xact_id()::text),'financial.approve');
        v_before:=app.invoice_resource_snapshot(v_invoice.id);
        -- DB-INV-010: the reversal with the draft's reason and the approver, dated after every
        -- financial event of the Invoice; the Invoice status and version as app.adjust_invoice sets
        -- them.
        v_at:=app.adjustment_reversal_instant(v_invoice.id);
        INSERT INTO app.invoice_adjustment_reversals(id,invoice_adjustment_id,reason,occurred_at,actor_id,
            authorization_reference)
        VALUES (v_reversal,v_adjustment.id,v_draft.reason,v_at,p_actor,'financial.approve');
        UPDATE app.invoices SET status=app.invoice_application_status(v_invoice.id),version=version+1,
            updated_at=GREATEST(v_at,updated_at),updated_by=p_actor WHERE id=v_invoice.id;
        -- The put-back: each part of a release's Credit still available, on the Adjustment's line,
        -- with the Rent-first proposal for its amount (BR-CREDIT-006), which must put the whole
        -- amount on that line (Q-2026-10-16-118 point 1); the approver applies it as the Credit
        -- writers do (credits.apply), each dated after the one before.
        v_put_at:=v_at;
        FOR v_item IN SELECT entry.item FROM jsonb_array_elements(v_plan) WITH ORDINALITY AS entry(item,position)
            ORDER BY entry.position
        LOOP
            v_put:=(v_item->>'put_back_usd_cents')::bigint;
            v_put_at:=GREATEST(v_put_at+interval '1 microsecond',
                app.credit_excess_instant(v_invoice.id,(v_item->>'customer_credit_id')::uuid));
            v_proposal:=app.credit_application_proposal(p_property,(v_item->>'customer_credit_id')::uuid,
                v_invoice.id,v_put,v_put_at);
            IF (v_proposal->>'amount_usd_cents')::bigint IS DISTINCT FROM v_put
                OR jsonb_array_length(v_proposal->'details') IS DISTINCT FROM 1
                OR v_proposal->'details'->0->>'invoice_line_id' IS DISTINCT FROM v_line.id::text
            THEN RAISE EXCEPTION 'The Credit put-back would go on another line by the Rent-first order; this waits for the owner'
                USING ERRCODE='55000'; END IF;
            INSERT INTO app.customer_credit_applications(id,customer_credit_id,target_kind,invoice_id,
                late_payment_charge_id,final_settlement_id,amount_usd_cents,within_invoice_basis,
                customer_designation_reference,proposal_generated_at,proposal_trace,occurred_at,actor_id,
                authorization_reference)
            VALUES ((v_item->>'credit_application_id')::uuid,(v_item->>'customer_credit_id')::uuid,
                'INVOICE',v_invoice.id,NULL,NULL,v_put,'RENT_THEN_RECURRING_SERVICES_PROPOSAL',NULL,
                v_put_at,v_proposal,v_put_at,p_actor,'credits.apply');
            INSERT INTO app.customer_credit_application_details(id,customer_credit_application_id,
                invoice_line_id,late_payment_charge_id,obligation_kind,invoice_line_category_snapshot,
                proposed_amount_usd_cents,applied_amount_usd_cents,attribution_basis,detail_sequence,
                calculation_trace)
            VALUES (gen_random_uuid(),(v_item->>'credit_application_id')::uuid,v_line.id,NULL,
                'INVOICE_LINE',v_line.category,v_put,v_put,v_proposal->'details'->0->>'attribution_basis',1,
                jsonb_build_object('reason','Invoice Adjustment reversal put-back',
                    'invoice_adjustment_reversal_id',v_reversal,
                    'invoice_credit_excess_release_id',v_item->'invoice_credit_excess_release_id'));
        END LOOP;
        IF jsonb_array_length(v_plan)>0 THEN
            PERFORM app.refresh_allocated_invoice(v_invoice.id,p_actor,true);
        END IF;
        -- Every record is written: the deferred checks run now, inside this definer function (as
        -- the existing writers run them).
        SET CONSTRAINTS ALL IMMEDIATE;
        v_result:=app.adjustment_reversal_result(p_draft);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,linked_source_event_id,customer_id,lease_id)
        VALUES (gen_random_uuid(),v_at,timezone(v_timezone,v_at)::date,p_actor,'invoice.adjustment_reversed',
            'invoice',v_invoice.id,v_draft.reason,'financial.approve',p_property,v_before,
            app.invoice_resource_snapshot(v_invoice.id),p_draft,'API','SUCCEEDED',
            jsonb_build_object('capability','financial.approve','draft_id',p_draft,
                'prepare_capability','invoices.adjust','invoice_adjustment_id',v_adjustment.id,
                'invoice_adjustment_reversal_id',v_reversal,'invoice_line_id',v_line.id,
                'put_backs',v_result->'put_backs'),
            v_reversal,v_invoice.customer_id,v_invoice.lease_id);
        RETURN v_result;
    END $$;
"""

# Relaxing: the capability-scoped draft reads take the reader's preparer capabilities, which are
# now nine with invoices.adjust (the bound was eight since migration 20261120_116).
PATCHES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "app.financial_draft_resource_by_capability(uuid,uuid,uuid,text[])",
        (
            (
                "cardinality(p_capabilities) NOT BETWEEN 1 AND 8",
                "cardinality(p_capabilities) NOT BETWEEN 1 AND 9",
            ),
        ),
    ),
    (
        "app.list_financial_drafts_by_capability(uuid,uuid,text[],text,integer,timestamp with time zone,uuid)",
        (
            (
                "cardinality(p_capabilities) NOT BETWEEN 1 AND 8",
                "cardinality(p_capabilities) NOT BETWEEN 1 AND 9",
            ),
        ),
    ),
)

INTERNAL = (
    "app.adjustment_reversal_source(uuid,uuid)",
    "app.adjustment_reversal_instant(uuid)",
    "app.adjustment_reversal_result(uuid)",
)
RECORD = "app.record_adjustment_reversal_draft(uuid,uuid,uuid,uuid,text,text)"
CONFIRM = "app.confirm_adjustment_reversal(uuid,uuid,uuid,text)"

PREPARERS = (
    "'refunds.create','deposits.dispose','reservation_deposits.dispose',"
    "'reservation_deposits.refund','payments.allocations.reverse',"
    "'final_settlements.prepare','deposits.correct','payments.reverse','invoices.adjust'"
)


def _single_check(pattern: str) -> str:
    names = (
        op.get_bind()
        .execute(
            text(
                "SELECT conname FROM pg_catalog.pg_constraint "
                "WHERE conrelid='app.financial_drafts'::regclass AND contype='c' "
                "AND pg_catalog.pg_get_constraintdef(oid) LIKE :pattern"
            ),
            {"pattern": pattern},
        )
        .scalars()
        .all()
    )
    if len(names) != 1:
        raise RuntimeError(f"Financial draft constraint is not unique: {pattern}")
    return str(names[0])


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
            raise RuntimeError(f"Adjustment reversal draft contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    kind = _single_check("CHECK ((kind = ANY (ARRAY['REFUND'%")
    capability = _single_check("CHECK ((prepare_capability = ANY%")
    kind_capability = _single_check("%kind = 'DEPOSIT_FORFEITURE'%")
    # Relaxing: the draft kind ADJUSTMENT_REVERSAL, prepared under invoices.adjust (owner answer 7
    # to Q-2026-10-06-36), and its withdrawal by that preparer.
    op.execute(f"""
        ALTER TABLE app.financial_drafts DROP CONSTRAINT {kind};
        ALTER TABLE app.financial_drafts ADD CONSTRAINT {kind} CHECK (kind IN (
            'REFUND','DEPOSIT_FORFEITURE','PAYMENT_MOVE','FINAL_SETTLEMENT','SETTLEMENT_CORRECTION',
            'PAYMENT_RETURN','ADJUSTMENT_REVERSAL'));
        ALTER TABLE app.financial_drafts DROP CONSTRAINT {capability};
        ALTER TABLE app.financial_drafts ADD CONSTRAINT {capability} CHECK (prepare_capability IN (
            {PREPARERS}));
        ALTER TABLE app.financial_drafts DROP CONSTRAINT {kind_capability};
        ALTER TABLE app.financial_drafts ADD CONSTRAINT {kind_capability} CHECK (
            (kind = 'REFUND' AND prepare_capability IN ('refunds.create','reservation_deposits.refund'))
            OR (kind = 'DEPOSIT_FORFEITURE'
                AND prepare_capability IN ('deposits.dispose','reservation_deposits.dispose','deposits.correct'))
            OR (kind = 'PAYMENT_MOVE' AND prepare_capability = 'payments.allocations.reverse')
            OR (kind IN ('FINAL_SETTLEMENT','SETTLEMENT_CORRECTION')
                AND prepare_capability = 'final_settlements.prepare')
            OR (kind = 'PAYMENT_RETURN' AND prepare_capability = 'payments.reverse')
            OR (kind = 'ADJUSTMENT_REVERSAL' AND prepare_capability = 'invoices.adjust'));
        ALTER TABLE app.financial_draft_decisions DROP CONSTRAINT financial_draft_decision_shape;
        ALTER TABLE app.financial_draft_decisions ADD CONSTRAINT financial_draft_decision_shape CHECK (
            (decision = 'CONFIRMED' AND authorization_reference = 'financial.approve'
                AND result IS NOT NULL)
            OR (decision = 'REJECTED' AND authorization_reference = 'financial.approve'
                AND reason IS NOT NULL AND result IS NULL)
            OR (decision = 'WITHDRAWN' AND reason IS NOT NULL AND result IS NULL
                AND authorization_reference IN ({PREPARERS}))
        );
    """)
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
    raise RuntimeError("Adjustment reversal draft migration is forward-only")
