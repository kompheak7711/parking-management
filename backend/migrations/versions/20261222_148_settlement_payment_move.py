# ruff: noqa: E501
"""The wrong-Unit Payment move after closure (V1-056 sub-slice 10g).

BR-PAY-042, BR-SETTLE-012, BR-SETTLE-013, BR-SETTLE-016, BR-AUTH-010; DB-PAY-008, DB-SETTLE-003,
DB-SETTLE-005; owner answer 4 to Q-2026-10-06-36 and answers 1 and 5 to Q-2026-10-06-37:

- A new variant PAYMENT_MOVE of the SETTLEMENT_CORRECTION draft: a final_settlements.prepare holder
  records it with a reason and the acknowledgement text of both Customers (who, the date and how),
  naming the closed Final Settlement, the wrong Invoice allocation and the correct Invoice on a
  Lease of another Unit; only a financial.approve holder confirms it.
- Which allocations: an Invoice allocation, not reversed, on an Invoice of the Settlement's Lease,
  that this Settlement relied on (posted at or before the closure, or linked to a correction of
  this Settlement). Refused (55000): an open Settlement, another Lease's allocation, an allocation
  already reversed, an allocation that a correction of another Final Settlement wrote (owner answer
  5: only that Settlement's own correction may change it; open: Q-2026-10-17-120), an allocation
  made after the closure (the slice 7 move draft moves it) and a waiting move draft of either kind.
  The slice 7 rules of app.payment_move_source apply unchanged; the correct Invoice may belong to
  a Lease whose Final Settlement is closed (allocations to it stay open).
- In one transaction the confirm writes the decision and the correction header, then the slice 7
  move: the wrong allocation's reversal and the new allocation of the same Payment to the correct
  Invoice (each linked to the correction, DB-SETTLE-005), its details and the payment_moves row.
  The debt comes back on the Settlement obligation and stays on its Customer's ledger
  (BR-SETTLE-016); what the correct Invoice does not take stays unallocated on the Payment (plan
  Q16); no DL-032 step runs.

New internal functions: app.settlement_payment_move_source, app.settlement_payment_move_allowed and
app.settlement_payment_move_result. New writers: app.record_settlement_payment_move_draft and
app.confirm_settlement_payment_move (EXECUTE to the financial role). Relaxing exact-text patch:
app.validate_payment_move also accepts such a correction's move, written after its decision in the
same transaction, whose decision names the move, with the reversal and the new allocation linked
to it. No table, column, trigger
or other grant change.
"""

from alembic import op
from sqlalchemy import text

revision = "20261222_148"
down_revision = "20261221_147"
branch_labels = None
depends_on = None

FUNCTION_SQL = r"""
    -- What a PAYMENT_MOVE correction moves: an Invoice allocation this closed Settlement relied
    -- on, then the slice 7 source of the move itself.
    CREATE FUNCTION app.settlement_payment_move_source(p_property uuid,p_settlement uuid,
        p_allocation uuid,p_target_invoice uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_settlement app.final_settlements%ROWTYPE; v_allocation app.payment_allocations%ROWTYPE;
        v_lease uuid;
    BEGIN
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=p_settlement AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        SELECT allocation.* INTO v_allocation FROM app.payment_allocations allocation
        JOIN app.payments payment ON payment.id=allocation.payment_id
        WHERE allocation.id=p_allocation AND payment.property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Payment allocation was not found' USING ERRCODE='P0002'; END IF;
        IF v_settlement.closed_at IS NULL THEN
            RAISE EXCEPTION 'A post-settlement correction needs a closed Final Settlement'
                USING ERRCODE='55000'; END IF;
        -- BR-PAY-042 names Invoices: Late-payment Charge allocations do not move (as slice 7).
        IF v_allocation.target_kind<>'INVOICE' THEN
            RAISE EXCEPTION 'Only an Invoice allocation can move' USING ERRCODE='22023'; END IF;
        SELECT invoice.lease_id INTO v_lease FROM app.invoices invoice WHERE invoice.id=v_allocation.invoice_id;
        IF v_lease IS DISTINCT FROM v_settlement.lease_id THEN
            RAISE EXCEPTION 'The allocation does not pay an Invoice of this Final Settlement''s Lease'
                USING ERRCODE='55000'; END IF;
        IF EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal
            WHERE reversal.payment_allocation_id=p_allocation)
        THEN RAISE EXCEPTION 'The allocation is already reversed' USING ERRCODE='55000'; END IF;
        -- Owner answer 5 to Q-2026-10-06-37: a record that another Final Settlement relied on
        -- changes only through a confirmed correction of that Settlement. Such an allocation (the
        -- new allocation of another Settlement's PAYMENT_MOVE correction) is refused until the
        -- owner answers Q-2026-10-17-120.
        IF EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
            JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
            WHERE effect.payment_allocation_id=p_allocation
              AND correction.final_settlement_id<>v_settlement.id)
        THEN RAISE EXCEPTION 'A correction of another Final Settlement wrote this allocation; this correction cannot move it'
            USING ERRCODE='55000'; END IF;
        -- This Settlement relied on the allocation: its closure counted it, or one of its
        -- corrections wrote it. An allocation made after the closure moves through the slice 7
        -- move draft (the slice 10 design note).
        IF v_allocation.posted_at>v_settlement.closed_at
            AND NOT EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
                WHERE effect.payment_allocation_id=p_allocation
                  AND correction.final_settlement_id=v_settlement.id)
        THEN RAISE EXCEPTION 'An allocation made after the closure moves through the ordinary move draft'
            USING ERRCODE='55000'; END IF;
        RETURN app.payment_move_source(p_property,p_allocation,p_target_invoice)
            || jsonb_build_object('final_settlement_id',v_settlement.id,'lease_id',v_settlement.lease_id,
                'closed_at',v_settlement.closed_at);
    END $$;

    -- The move of a PAYMENT_MOVE correction: the approver's CONFIRMED financial.approve decision
    -- of this transaction that names this move, and the reversal and the new allocation linked to
    -- its correction.
    CREATE FUNCTION app.settlement_payment_move_allowed(p_draft uuid,p_approver uuid,p_move uuid,
        p_reversal uuid,p_allocation uuid)
    RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE((
            SELECT EXISTS(SELECT 1 FROM app.financial_drafts draft
                JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id
                JOIN app.settlement_corrections correction
                    ON correction.id=app.settlement_correction_id(draft.id)
                   AND correction.final_settlement_id::text=draft.payload->>'final_settlement_id'
                WHERE draft.id=p_draft AND draft.kind='SETTLEMENT_CORRECTION'
                  AND draft.payload->>'variant'='PAYMENT_MOVE'
                  AND decision.decision='CONFIRMED' AND decision.decided_by=p_approver
                  AND decision.authorization_reference='financial.approve'
                  AND decision.result->>'transaction_id'=pg_current_xact_id()::text
                  AND decision.decided_at>=transaction_timestamp()
                  AND decision.result->>'payment_move_id'=p_move::text
                  AND EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                      WHERE effect.settlement_correction_id=correction.id
                        AND effect.payment_allocation_reversal_id=p_reversal)
                  AND EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                      WHERE effect.settlement_correction_id=correction.id
                        AND effect.payment_allocation_id=p_allocation))),false)
    $$;

    -- The stored move of a PAYMENT_MOVE correction; no result or replay shows the decision's
    -- transaction id (sub-slice 10b).
    CREATE FUNCTION app.settlement_payment_move_result(p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        SELECT jsonb_build_object('draft',app.financial_draft_json(draft) #- '{decision,result,transaction_id}',
            'move',jsonb_build_object('payment_move_id',move.id,'payment_id',move.payment_id,
                'source_allocation_id',move.source_allocation_id,'source_reversal_id',move.source_reversal_id,
                'target_allocation_id',move.target_allocation_id,'source_invoice_id',move.source_invoice_id,
                'target_invoice_id',move.target_invoice_id,'moved_usd_cents',move.moved_usd_cents,
                'left_on_payment_usd_cents',(decision.result->>'left_on_payment_usd_cents')::bigint,
                'confirmed_at',move.confirmed_at,'confirmed_by',move.confirmed_by),
            'settlement_correction',jsonb_build_object('id',correction.id,
                'final_settlement_id',correction.final_settlement_id,'reason',correction.reason,
                'occurred_at',correction.occurred_at,'actor_id',correction.actor_id,
                'authorization_reference',correction.authorization_reference))
        FROM app.financial_drafts draft
        JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id
        JOIN app.payment_moves move ON move.draft_id=draft.id
        JOIN app.settlement_corrections correction ON correction.id=app.settlement_correction_id(draft.id)
        WHERE draft.id=p_draft
    $$;

    CREATE FUNCTION app.record_settlement_payment_move_draft(p_property uuid,p_actor uuid,p_draft uuid,
        p_settlement uuid,p_allocation uuid,p_target_invoice uuid,p_reason text,
        p_source_acknowledgement text,p_target_acknowledgement text,p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_existing app.financial_drafts%ROWTYPE; v_input jsonb; v_source jsonb; v_payload jsonb;
    BEGIN
        PERFORM app.require_invoice_command_actor(p_property,p_actor);
        PERFORM app.assert_active_financial_actor(p_actor,p_property);
        IF p_authorization IS DISTINCT FROM 'final_settlements.prepare' THEN
            RAISE EXCEPTION 'Post-settlement correction draft authorization is invalid'
                USING ERRCODE='42501'; END IF;
        -- The one-draft-per-allocation lock and the source read rely on READ COMMITTED (as the
        -- slice 7 recorder and the other correction recorders).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'A post-settlement correction draft is recorded at READ COMMITTED'
                USING ERRCODE='55000'; END IF;
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_settlement IS NULL
            OR p_allocation IS NULL OR p_target_invoice IS NULL
            OR app.lease_notice_text_valid(p_reason,1000) IS NOT TRUE
            OR app.lease_notice_text_valid(p_source_acknowledgement,2000) IS NOT TRUE
            OR app.lease_notice_text_valid(p_target_acknowledgement,2000) IS NOT TRUE
        THEN RAISE EXCEPTION 'Payment move correction input is invalid' USING ERRCODE='22023'; END IF;
        v_input:=jsonb_build_object('variant','PAYMENT_MOVE','final_settlement_id',p_settlement,
            'source_allocation_id',p_allocation,'target_invoice_id',p_target_invoice,
            'source_acknowledgement',p_source_acknowledgement,
            'target_acknowledgement',p_target_acknowledgement);
        -- An exact repeat replays before any current-state check.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
        IF FOUND THEN
            IF v_existing.property_id=p_property AND v_existing.kind='SETTLEMENT_CORRECTION'
                AND v_existing.prepared_by=p_actor AND v_existing.reason=p_reason
                AND (v_existing.payload-'source'-'lease_id')=v_input
            THEN RETURN app.financial_draft_json(v_existing) #- '{decision,result,transaction_id}'; END IF;
            RAISE EXCEPTION 'Post-settlement correction draft identity was reused' USING ERRCODE='P5205';
        END IF;
        -- The Property is checked before the lock; the move drafts of one allocation, of both
        -- kinds, are then serialized. This recorder refuses while a draft of either kind waits; the
        -- slice 7 recorder sees only its own kind until 10h refuses its drafts of the allocations a
        -- closed Settlement relied on.
        v_source:=app.settlement_payment_move_source(p_property,p_settlement,p_allocation,p_target_invoice);
        PERFORM pg_advisory_xact_lock(hashtextextended('payment-move:' || p_allocation::text,0));
        v_source:=app.settlement_payment_move_source(p_property,p_settlement,p_allocation,p_target_invoice);
        IF EXISTS(SELECT 1 FROM app.financial_drafts draft
            WHERE draft.property_id=p_property
              AND (draft.kind='PAYMENT_MOVE' OR (draft.kind='SETTLEMENT_CORRECTION'
                  AND draft.payload->>'variant'='PAYMENT_MOVE'))
              AND draft.payload->>'source_allocation_id'=p_allocation::text
              AND NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                  WHERE decision.draft_id=draft.id))
        THEN RAISE EXCEPTION 'A move draft for this allocation is already waiting' USING ERRCODE='55000'; END IF;
        v_payload:=v_input || jsonb_build_object('lease_id',v_source->'lease_id','source',v_source);
        IF octet_length(v_payload::text)>16000 THEN
            RAISE EXCEPTION 'The Payment move correction draft exceeds the stored draft size of 16000 bytes (acknowledgements and the line split of the correct Invoice)'
                USING ERRCODE='22023'; END IF;
        RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'SETTLEMENT_CORRECTION',
            'final_settlements.prepare',v_payload,
            'settlement-correction:' || encode(sha256(convert_to(v_source::text,'UTF8')),'hex'),p_reason);
    END $$;

    CREATE FUNCTION app.confirm_settlement_payment_move(p_property uuid,p_actor uuid,p_draft uuid,
        p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_timezone text; v_draft app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_source jsonb; v_invoice app.invoices%ROWTYPE; v_payment uuid; v_source_allocation uuid;
        v_source_invoice uuid; v_target_invoice uuid; v_reversal uuid:=gen_random_uuid();
        v_allocation uuid:=gen_random_uuid(); v_move uuid:=gen_random_uuid(); v_correction uuid;
        v_at timestamptz; v_detail jsonb; v_sequence integer:=0; v_moved bigint; v_left bigint;
        v_unit uuid; v_evidence jsonb; v_result jsonb;
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
              AND draft.payload->>'variant'='PAYMENT_MOVE' AND decision.decision='CONFIRMED'
              AND decision.decided_by=p_actor)
        THEN RETURN app.settlement_payment_move_result(p_draft); END IF;
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
        IF NOT FOUND OR v_draft.kind<>'SETTLEMENT_CORRECTION'
            OR v_draft.prepare_capability<>'final_settlements.prepare'
            OR v_draft.payload->>'variant' IS DISTINCT FROM 'PAYMENT_MOVE'
            OR v_draft.payload->>'source_allocation_id' IS NULL
            OR v_draft.payload->>'source_allocation_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            OR v_draft.payload->>'target_invoice_id' IS NULL
            OR v_draft.payload->>'target_invoice_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            OR v_draft.payload->>'final_settlement_id' IS NULL
            OR v_draft.payload->>'final_settlement_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        THEN RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        IF EXISTS(SELECT 1 FROM app.financial_draft_decisions WHERE draft_id=p_draft) THEN
            RAISE EXCEPTION 'Financial draft is already decided' USING ERRCODE='55000'; END IF;
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=(v_draft.payload->>'final_settlement_id')::uuid AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        -- The checks below rely on READ COMMITTED: each statement sees the commits the locks waited
        -- for (as the slice 7 confirm and the other correction confirms).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'A post-settlement correction is confirmed at READ COMMITTED'
                USING ERRCODE='55000'; END IF;
        v_source_allocation:=(v_draft.payload->>'source_allocation_id')::uuid;
        v_target_invoice:=(v_draft.payload->>'target_invoice_id')::uuid;
        v_payment:=(v_draft.payload->'source'->>'payment_id')::uuid;
        v_source_invoice:=(v_draft.payload->'source'->>'source_invoice_id')::uuid;
        -- Lock order: the draft lock (above); the allocation's move lock (shared with the slice 7
        -- drafts); the Settlement's draft lock (as app.begin_settlement_correction takes it); the
        -- Payment (its serialization row, then the row), both Invoices in id order and the correct
        -- Invoice's lines (the slice 7 order); the Settlement row last, in
        -- app.begin_settlement_correction.
        PERFORM pg_advisory_xact_lock(hashtextextended('payment-move:' || v_source_allocation::text,0));
        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));
        PERFORM app.serialize_payment_state(v_payment);
        PERFORM 1 FROM app.payments WHERE id=v_payment FOR UPDATE;
        PERFORM 1 FROM app.invoices WHERE id IN (v_source_invoice,v_target_invoice) ORDER BY id FOR UPDATE;
        PERFORM 1 FROM app.invoice_lines WHERE invoice_id=v_target_invoice ORDER BY id FOR UPDATE;
        -- Under the locks the source still has the digest the draft recorded; otherwise the draft
        -- is stale and stays pending. A refusal of the source refuses the confirm the same way.
        v_source:=app.settlement_payment_move_source(p_property,v_settlement.id,v_source_allocation,
            v_target_invoice);
        IF 'settlement-correction:' || encode(sha256(convert_to(v_source::text,'UTF8')),'hex')
            IS DISTINCT FROM v_draft.source_revision
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        v_moved:=(v_source->>'moved_usd_cents')::bigint;
        v_left:=(v_source->>'source_amount_usd_cents')::bigint-v_moved;
        -- The decision, then the header (sub-slice 10a). From here every record is linked before
        -- it is written.
        v_correction:=app.begin_settlement_correction(p_property,p_actor,p_draft,'financial.approve',
            jsonb_build_object('payment_move_id',v_move,'payment_id',v_payment,
                'source_allocation_id',v_source_allocation,'source_reversal_id',v_reversal,
                'target_allocation_id',v_allocation,'source_invoice_id',v_source_invoice,
                'target_invoice_id',v_target_invoice,'moved_usd_cents',v_moved,
                'left_on_payment_usd_cents',v_left));
        SET CONSTRAINTS ALL DEFERRED;
        -- The slice 7 move: one instant for the reversal and the new allocation, strictly later
        -- than every financial event of both Invoices, so the Payment is never over-used in between.
        v_at:=GREATEST(app.credit_excess_instant(v_source_invoice,NULL),
            app.credit_excess_instant(v_target_invoice,NULL));
        PERFORM app.link_settlement_correction_effect(v_correction,'payment_allocation_reversal_id',v_reversal);
        INSERT INTO app.payment_allocation_reversals(id,payment_allocation_id,reason,occurred_at,
            actor_id,authorization_reference)
        VALUES (v_reversal,v_source_allocation,v_draft.reason,v_at,p_actor,'payments.allocations.reverse');
        SELECT * INTO STRICT v_invoice FROM app.invoices WHERE id=v_target_invoice;
        PERFORM app.link_settlement_correction_effect(v_correction,'payment_allocation_id',v_allocation);
        INSERT INTO app.payment_allocations(id,payment_id,target_customer_id,proposal_batch_id,
            between_invoice_sequence,target_kind,invoice_id,late_payment_charge_id,amount_usd_cents,
            between_invoice_basis,within_invoice_basis,customer_designation_reference,
            selected_invoice_due_date,selected_invoice_issued_at,selected_invoice_number_snapshot,
            proposal_generated_at,proposal_trace,posted_at,posted_by,authorization_reference)
        VALUES (v_allocation,v_payment,v_invoice.customer_id,gen_random_uuid(),1,'INVOICE',
            v_target_invoice,NULL,v_moved,'WRONG_UNIT_MOVE','RENT_THEN_RECURRING_SERVICES_PROPOSAL',NULL,
            v_invoice.due_date,v_invoice.issued_at,v_invoice.invoice_number,v_at,
            jsonb_build_object('variant','WRONG_UNIT_MOVE','payment_move_draft_id',p_draft,
                'source_allocation_id',v_source_allocation,'source_reversal_id',v_reversal,
                'settlement_correction_id',v_correction,'final_settlement_id',v_settlement.id),
            v_at,p_actor,'payments.allocate');
        FOR v_detail IN SELECT value FROM jsonb_array_elements(v_source->'details') LOOP
            v_sequence:=v_sequence+1;
            INSERT INTO app.payment_allocation_details(id,payment_allocation_id,invoice_line_id,
                obligation_kind,invoice_line_category_snapshot,proposed_amount_usd_cents,
                posted_amount_usd_cents,attribution_basis,detail_sequence,calculation_trace)
            VALUES (gen_random_uuid(),v_allocation,(v_detail->>'invoice_line_id')::uuid,'INVOICE_LINE',
                v_detail->>'category',(v_detail->>'amount_usd_cents')::bigint,
                (v_detail->>'amount_usd_cents')::bigint,v_detail->>'attribution_basis',
                v_sequence::smallint,jsonb_build_object('payment_move_draft_id',p_draft,
                    'settlement_correction_id',v_correction,'confirmed_detail',v_detail));
        END LOOP;
        -- Advance the correct Invoice's version even when its status stays the same (as slice 7).
        PERFORM app.refresh_allocated_invoice(v_target_invoice,p_actor,true);
        INSERT INTO app.payment_moves(id,draft_id,property_id,payment_id,source_allocation_id,
            source_reversal_id,source_reversed_by_move,target_allocation_id,source_invoice_id,
            target_invoice_id,moved_usd_cents,source_acknowledgement,target_acknowledgement,
            confirmed_at,confirmed_by)
        VALUES (v_move,p_draft,p_property,v_payment,v_source_allocation,v_reversal,true,v_allocation,
            v_source_invoice,v_target_invoice,v_moved,v_draft.payload->>'source_acknowledgement',
            v_draft.payload->>'target_acknowledgement',clock_timestamp(),p_actor);
        -- Every linked record is written: the deferred checks run now, inside this definer
        -- function (as the other variants run them).
        SET CONSTRAINTS ALL IMMEDIATE;
        v_result:=app.settlement_payment_move_result(p_draft);
        SELECT lease.unit_id INTO STRICT v_unit FROM app.leases lease WHERE lease.id=v_settlement.lease_id;
        v_evidence:=jsonb_build_object('capability','financial.approve','draft_id',p_draft,
            'settlement_correction_id',v_correction,'final_settlement_id',v_settlement.id,
            'variant','PAYMENT_MOVE');
        -- One move audit event (as slice 7; its correlation id is the draft id) and the
        -- correction's own event.
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,resulting_state,correlation_id,source,outcome,
            authorization_evidence,customer_id,lease_id)
        VALUES (gen_random_uuid(),v_at,timezone(v_timezone,v_at)::date,p_actor,'payment_move.confirmed',
            'payment_move',v_move,v_draft.reason,'financial.approve',p_property,
            (v_result->'move') || jsonb_build_object('prepared_by_actor_id',v_draft.prepared_by,
                'source_customer_id',v_source->>'source_customer_id',
                'target_customer_id',v_source->>'target_customer_id'),
            p_draft,'API','SUCCEEDED',v_evidence,v_invoice.customer_id,v_invoice.lease_id);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
        VALUES (gen_random_uuid(),v_at,timezone(v_timezone,v_at)::date,p_actor,
            'final_settlement.correction.confirmed','settlement_correction',v_correction,v_draft.reason,
            'financial.approve',p_property,'{}'::jsonb,
            jsonb_build_object('settlement_correction_id',v_correction,
                'final_settlement_id',v_settlement.id,'variant','PAYMENT_MOVE',
                'payment_move_id',v_move,'payment_id',v_payment,
                'source_allocation_id',v_source_allocation,'source_reversal_id',v_reversal,
                'target_allocation_id',v_allocation,'source_invoice_id',v_source_invoice,
                'target_invoice_id',v_target_invoice,
                'source_customer_id',v_source->>'source_customer_id',
                'target_customer_id',v_source->>'target_customer_id',
                'moved_usd_cents',v_moved,'left_on_payment_usd_cents',v_left),
            v_correction,'API','SUCCEEDED',v_evidence,(v_source->>'source_customer_id')::uuid,
            v_settlement.lease_id,v_unit);
        RETURN v_result;
    END $$;
"""

VALIDATE = "app.validate_payment_move()"
DECISION_LINE = (
    "                OR EXISTS (SELECT 1 FROM app.financial_draft_decisions WHERE draft_id=NEW.draft_id)\n"
)
KIND_LINES = (
    "            IF v_draft.id IS NULL OR v_draft.kind<>'PAYMENT_MOVE' OR v_draft.property_id<>NEW.property_id\n"
    "                OR v_draft.payload->>'variant' IS DISTINCT FROM 'WRONG_UNIT_MOVE'\n"
)
PATCHES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        VALIDATE,
        (
            (DECISION_LINE, ""),
            (
                KIND_LINES,
                "            IF v_draft.id IS NULL OR v_draft.property_id<>NEW.property_id\n"
                "                -- A slice 7 move draft is still undecided; a PAYMENT_MOVE correction of a\n"
                "                -- closed Final Settlement (sub-slice 10g) writes the move after its decision,\n"
                "                -- in the same transaction, with the reversal and the new allocation linked.\n"
                "                OR NOT ((v_draft.kind='PAYMENT_MOVE'\n"
                "                        AND v_draft.payload->>'variant' IS NOT DISTINCT FROM 'WRONG_UNIT_MOVE'\n"
                "                        AND NOT EXISTS (SELECT 1 FROM app.financial_draft_decisions\n"
                "                            WHERE draft_id=NEW.draft_id))\n"
                "                    OR (v_draft.kind='SETTLEMENT_CORRECTION'\n"
                "                        AND v_draft.payload->>'variant' IS NOT DISTINCT FROM 'PAYMENT_MOVE'\n"
                "                        AND app.settlement_payment_move_allowed(NEW.draft_id,NEW.confirmed_by,\n"
                "                            NEW.id,NEW.source_reversal_id,NEW.target_allocation_id)))\n",
            ),
        ),
    ),
)

INTERNAL = (
    "app.settlement_payment_move_source(uuid,uuid,uuid,uuid)",
    "app.settlement_payment_move_allowed(uuid,uuid,uuid,uuid,uuid)",
    "app.settlement_payment_move_result(uuid)",
)
RECORD = (
    "app.record_settlement_payment_move_draft(uuid,uuid,uuid,uuid,uuid,uuid,text,text,text,text)"
)
CONFIRM = "app.confirm_settlement_payment_move(uuid,uuid,uuid,text)"


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
            raise RuntimeError(f"Settlement Payment move contract changed: {signature}")
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
    raise RuntimeError("Settlement Payment move migration is forward-only")
