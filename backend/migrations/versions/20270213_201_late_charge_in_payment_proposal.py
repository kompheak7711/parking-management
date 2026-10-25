"""A late-payment charge right after its own Invoice in the payment proposal (V1-056 slice 11g-4;
DL-076 answer 5).

DL-076 answer 5 (owner): money pays oldest Due Date first, and a late-payment charge is paid
right after its own Invoice, before newer Invoices; staff change the order only when the
Customer names what to pay (BR-PAY-024). This replaces BR-PAY-040, where staff ticked the
charge by hand. A third-party payer's money pays only what the payer names (DL-029 stays).

1. `app.payment_allocation_proposal` also proposes each open late-payment charge of the payer
   right after its source Invoice, in the order Due Date, issue time, Invoice number, Invoice id,
   then the Invoice before its charge. Only a payer's own Payment with nothing named
   (`NORMAL_CUSTOMER`, no identified Invoice or charge) gets charge targets; a third-party or
   named Payment is proposed as before. A charge counts against the same bounds as an Invoice
   (100 targets, 500 details, the size limit). A charge target names `late_payment_charge_id`, its
   `source_invoice_id` and that Invoice's Due Date, issue time and number; it has no
   `invoice_id`, so the posting command takes it as a charge target. The policy name says so.
2. `app.post_payment_allocations` posts a proposed charge target as a direct charge allocation
   (no proposal batch fields: the table keeps proposal batches for Invoice targets only); its
   detail's trace names the proposal batch. The confirmed proposal itself is still compared
   whole under the locks and stays the trace of the batch's Invoice allocations. The audit
   event of a charge allocation names no proposal batch either; only the detail's trace links
   it to the batch.

A batch now often holds both charges and Invoices; the posting command locks each charge, then
the Invoices, as it already did for a designated batch with both, so two such posts at once can
end in a detected deadlock (no money moves; the service answers unavailable and the client
replays the same command with the same key).

Additive: a read function replaced with the same signature, settings and grants, and one writer
patched in place; no table or grant change.
"""

from alembic import op
from sqlalchemy import text

revision = "20270213_201"
down_revision = "20270212_200"
branch_labels = None
depends_on = None

PROPOSAL = r"""
CREATE OR REPLACE FUNCTION app.payment_allocation_proposal(p_property_id uuid, p_payment_id uuid,
    p_generated_at timestamp with time zone, p_batch_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog'
AS $function$
        DECLARE v_payment app.payments%ROWTYPE; v_item record; v_line record;
        DECLARE v_available bigint; v_remaining bigint; v_amount bigint; v_total bigint;
        DECLARE v_targets jsonb:='[]'; v_details jsonb; v_sequence integer:=0;
        DECLARE v_detail_count integer:=0; v_has_more boolean:=false;
        DECLARE v_next_details jsonb; v_next_target jsonb; v_target jsonb;
        BEGIN
            SELECT * INTO v_payment FROM app.payments
                WHERE id=p_payment_id AND property_id=p_property_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Payment not found' USING ERRCODE='P4901'; END IF;
            IF v_payment.status<>'RECEIVED' OR p_generated_at IS NULL OR NOT isfinite(p_generated_at)
                OR p_generated_at<v_payment.confirmed_at OR p_generated_at>clock_timestamp()+interval '5 seconds'
                OR p_batch_id IS NULL OR p_batch_id='00000000-0000-0000-0000-000000000000'
            THEN RAISE EXCEPTION 'Payment proposal input is invalid' USING ERRCODE='P4902'; END IF;
            IF p_generated_at<app.payment_proposal_dependency_at(p_payment_id) THEN
                RAISE EXCEPTION 'Proposal predates current financial dependencies' USING ERRCODE='P4904';
            END IF;
            v_available:=app.payment_available_value(p_payment_id); v_remaining:=v_available;
            -- V1-056 slice 11g-4 (DL-076 answer 5): each open late-payment charge of a payer's own
            -- Payment with nothing named comes right after its source Invoice.
            FOR v_item IN SELECT * FROM (
                SELECT invoice.id AS invoice_id,NULL::uuid AS charge_id,invoice.customer_id,
                    invoice.due_date,invoice.issued_at,invoice.invoice_number,invoice.version,
                    0 AS rank,NULL::bigint AS charge_outstanding
                FROM app.invoices invoice
                WHERE invoice.status IN ('UNPAID','PARTIALLY_PAID')
                    AND app.invoice_property_id(invoice.id)=p_property_id
                    AND v_payment.identified_late_payment_charge_id IS NULL
                    AND (v_payment.identified_invoice_id IS NULL OR invoice.id=v_payment.identified_invoice_id)
                    AND ((v_payment.payment_scope_kind='NORMAL_CUSTOMER'
                            AND invoice.customer_id=v_payment.payer_customer_id)
                        OR (v_payment.payment_scope_kind='THIRD_PARTY_IDENTIFIED'
                            AND (v_payment.lease_id IS NULL OR invoice.lease_id=v_payment.lease_id)))
                UNION ALL
                SELECT invoice.id,charge.id,charge.customer_id,invoice.due_date,invoice.issued_at,
                    invoice.invoice_number,NULL::bigint,1,position.remaining_balance_usd_cents
                FROM app.late_payment_charges charge
                JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
                JOIN app.late_payment_charge_financial_position position
                    ON position.late_payment_charge_id=charge.id
                WHERE position.remaining_balance_usd_cents>0 AND invoice.status<>'VOID'
                    AND app.invoice_property_id(invoice.id)=p_property_id
                    AND v_payment.payment_scope_kind='NORMAL_CUSTOMER'
                    AND v_payment.identified_invoice_id IS NULL
                    AND v_payment.identified_late_payment_charge_id IS NULL
                    AND charge.customer_id=v_payment.payer_customer_id) item
                ORDER BY item.due_date,item.issued_at,item.invoice_number COLLATE "C",item.invoice_id,
                    item.rank,item.charge_id
            LOOP
                EXIT WHEN v_remaining=0;
                IF v_item.charge_id IS NOT NULL THEN
                    IF v_sequence>=100 OR v_detail_count>=500 THEN
                        v_has_more:=true; EXIT;
                    END IF;
                    v_amount:=LEAST(v_remaining,v_item.charge_outstanding);
                    v_next_target:=jsonb_build_object(
                        'late_payment_charge_id',v_item.charge_id,'target_customer_id',v_item.customer_id,
                        'source_invoice_id',v_item.invoice_id,'due_date',v_item.due_date,
                        'issued_at',v_item.issued_at,'invoice_number',v_item.invoice_number,
                        'sequence',v_sequence+1,'outstanding_usd_cents',v_item.charge_outstanding,
                        'amount_usd_cents',v_amount);
                    IF octet_length((v_targets||jsonb_build_array(v_next_target))::text)>200000 THEN
                        v_has_more:=true; EXIT;
                    END IF;
                    v_sequence:=v_sequence+1; v_detail_count:=v_detail_count+1;
                    v_targets:=v_targets||jsonb_build_array(v_next_target);
                    v_remaining:=v_remaining-v_amount;
                    CONTINUE;
                END IF;
                v_details:='[]'; v_total:=0; v_target:=NULL;
                FOR v_line IN SELECT line.*,app.invoice_line_outstanding(line.id) AS outstanding
                    FROM app.invoice_lines line WHERE line.invoice_id=v_item.invoice_id
                    ORDER BY CASE line.category WHEN 'RENT' THEN 0 WHEN 'SERVICE_CHARGES' THEN 1 ELSE 2 END,
                        line.line_sequence,line.id
                LOOP
                    EXIT WHEN v_remaining=0;
                    IF v_line.outstanding<=0 THEN CONTINUE; END IF;
                    IF v_sequence>=100 OR v_detail_count>=500 THEN
                        v_has_more:=true; EXIT;
                    END IF;
                    v_amount:=LEAST(v_remaining,v_line.outstanding);
                    v_next_details:=v_details||jsonb_build_array(jsonb_build_object(
                        'invoice_line_id',v_line.id,'category',v_line.category,
                        'outstanding_usd_cents',v_line.outstanding,'amount_usd_cents',v_amount,
                        'attribution_basis',CASE v_line.category WHEN 'RENT' THEN 'RENT_FIRST_PROPOSAL'
                            WHEN 'SERVICE_CHARGES' THEN 'SERVICE_PROPOSAL' ELSE 'OTHER_CONFIRMED' END));
                    v_next_target:=jsonb_build_object(
                        'invoice_id',v_item.invoice_id,'target_customer_id',v_item.customer_id,
                        'due_date',v_item.due_date,'issued_at',v_item.issued_at,
                        'invoice_number',v_item.invoice_number,'version',v_item.version,
                        'sequence',v_sequence+1,'amount_usd_cents',v_total+v_amount,'details',v_next_details);
                    -- Bound the producer below the command's 250KB UTF-8 envelope.
                    -- jsonb text includes spaces, so this is conservative versus compact JSON.
                    IF octet_length((v_targets||jsonb_build_array(v_next_target))::text)>200000 THEN
                        IF v_sequence=0 AND v_total=0 THEN
                            RAISE EXCEPTION 'Invoice cannot fit bounded proposal' USING ERRCODE='P4902';
                        END IF;
                        v_has_more:=true; EXIT;
                    END IF;
                    v_target:=v_next_target; v_details:=v_next_details;
                    v_detail_count:=v_detail_count+1;
                    v_total:=v_total+v_amount; v_remaining:=v_remaining-v_amount;
                END LOOP;
                IF v_total>0 THEN
                    v_sequence:=v_sequence+1;
                    v_targets:=v_targets||jsonb_build_array(v_target);
                END IF;
                EXIT WHEN v_has_more;
            END LOOP;
            RETURN jsonb_build_object('property_id',p_property_id,'payment_id',p_payment_id,
                'proposal_batch_id',p_batch_id,'generated_at',p_generated_at,
                'available_usd_cents',v_available,'unallocated_after_usd_cents',v_remaining,
                'continuation_status',CASE WHEN v_has_more THEN 'MORE_ELIGIBLE' ELSE 'COMPLETE' END,
                'continuation','CONFIRM_PAGE_THEN_REQUEST_FRESH_PROPOSAL',
                'targets',v_targets,
                'policy',CASE WHEN v_payment.payment_scope_kind='NORMAL_CUSTOMER'
                        AND v_payment.identified_invoice_id IS NULL
                        AND v_payment.identified_late_payment_charge_id IS NULL
                    THEN 'DUE_ISSUED_NUMBER_ID_CHARGE_AFTER_INVOICE/RENT_SERVICE_SOURCE_ORDER'
                    ELSE 'DUE_ISSUED_NUMBER_ID/RENT_SERVICE_SOURCE_ORDER' END,
                'payment_scope',v_payment.payment_scope_kind,
                'designation_reference',CASE WHEN v_payment.payment_scope_kind='THIRD_PARTY_IDENTIFIED'
                    OR v_payment.identified_invoice_id IS NOT NULL
                    THEN 'confirmed-payment:'||v_payment.id::text ELSE NULL END);
        END $function$
"""

POST = "app.post_payment_allocations(uuid,uuid,uuid,uuid,text,jsonb)"
POST_REPLACEMENTS = (
    (
        "                VALUES(v_id,p_payment_id,v_customer,v_batch,\n"
        "                    CASE WHEN v_generated THEN (v_target->>'sequence')::smallint END,\n",
        "                -- V1-056 slice 11g-4: a proposed charge target is posted as a direct charge\n"
        "                -- allocation; proposal batch fields stay with Invoice targets.\n"
        "                VALUES(v_id,p_payment_id,v_customer,CASE WHEN v_charge IS NULL THEN v_batch END,\n"
        "                    CASE WHEN v_generated AND v_charge IS NULL\n"
        "                        THEN (v_target->>'sequence')::smallint END,\n",
    ),
    (
        "                    v_reference,CASE WHEN v_generated THEN (v_target->>'due_date')::date END,\n"
        "                    CASE WHEN v_generated THEN (v_target->>'issued_at')::timestamptz END,\n"
        "                    CASE WHEN v_generated THEN v_target->>'invoice_number' END,\n"
        "                    v_generated_at,CASE WHEN v_generated THEN v_proposal END,v_now,p_actor_id,'payments.allocate');\n",
        "                    v_reference,CASE WHEN v_generated AND v_charge IS NULL\n"
        "                        THEN (v_target->>'due_date')::date END,\n"
        "                    CASE WHEN v_generated AND v_charge IS NULL\n"
        "                        THEN (v_target->>'issued_at')::timestamptz END,\n"
        "                    CASE WHEN v_generated AND v_charge IS NULL THEN v_target->>'invoice_number' END,\n"
        "                    CASE WHEN v_charge IS NULL THEN v_generated_at END,\n"
        "                    CASE WHEN v_generated AND v_charge IS NULL THEN v_proposal END,\n"
        "                    v_now,p_actor_id,'payments.allocate');\n",
    ),
    (
        "                        jsonb_build_object('designation_reference',v_reference));\n",
        "                        jsonb_build_object('designation_reference',v_reference)\n"
        "                            ||CASE WHEN v_generated THEN jsonb_build_object('proposal_batch_id',v_batch,\n"
        "                                'proposal_sequence',(v_target->>'sequence')::integer)\n"
        "                                ELSE '{}'::jsonb END);\n",
    ),
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
            raise RuntimeError(f"Payment allocation contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(PROPOSAL)
    _patch(POST, POST_REPLACEMENTS)


def downgrade() -> None:
    raise RuntimeError("Late-payment charge proposal order migration is forward-only")
