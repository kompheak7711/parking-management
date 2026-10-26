# ruff: noqa: E501
"""Receive payment in one step (V1-058 R5c-1; DL-077; DESIGN.md "What this money pays for").

Owner rule 13/10/2026 (DL-077): money pays Invoices when it is received, not later. The Receive
payment screen saves the payment, its Receipt and what the money pays for in one database
transaction, so a payment is never left half-saved (AGENTS.md: database transactions for
multi-step financial operations). Pressing Receive payment is the staff confirmation (DL-029);
the payment and its allocations stay two separate records (BR-PAY-019).

1. `app.receive_payment_commands`: one append-only row per command (Property, actor, key) with
   the request digest, the Payment and the response, so a retry with the same key gets the same
   answer and a different request with the same key is refused.
2. `app.receive_payment_replay(...)`: the replay read, used before a KHR rate is chosen.
3. `app.receive_payment(...)`: confirms the Payment through the existing USD or KHR command
   (under a key derived from this command's key, so it never replays a plain confirmation),
   then, in the same transaction:
   - `OLDEST_FIRST`: builds the existing payment proposal (oldest Due Date first, a late-payment
     charge right after its own Invoice, DL-076 answer 5) and posts it only when its targets are
     exactly the ones the screen showed; otherwise nothing is saved (P4904) and the screen reads
     the Customer again. No targets on both sides means the money waits on the Receipt.
   - Only the payer's own money (`NORMAL_CUSTOMER`, nothing named on the Payment) is taken;
     more than one proposal page (over 100 items) is refused (P5R02).
   - `NAMED`: the Customer named what to pay (BR-PAY-024). Each named Invoice is paid line by
     line in the proposal's line order (Rent, then Services, then the rest); a named charge is
     paid directly. Money may not be left waiting while the payer still owes something the
     proposal would pay (P5R01), because there is no "keep it for later" while the Customer
     owes anything.
   The response is the confirmation response plus the allocations made (with the Invoice
   number each one pays, a charge naming its source Invoice) and the money left on the Receipt.
4. `app.receive_payment_payable(...)`: the read behind the screen's list, the Customer's unpaid
   Invoices and open late-payment charges in the proposal's order, each with what is owed.

Additive only: one new table and three new functions; no existing table, function or grant
changes.
"""

from alembic import op

revision = "20270311_230"
down_revision = "20270310_229"
branch_labels = None
depends_on = None

UUID_PATTERN = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

# What the Receive payment screen lists for a Customer: the same items, in the same order, that
# `app.payment_allocation_proposal` pays for the Customer's own Payment with nothing named.
PAYABLE = r"""
    CREATE FUNCTION app.receive_payment_payable(p_property_id uuid,p_customer_id uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_items jsonb;
    BEGIN
        IF p_property_id IS NULL OR p_customer_id IS NULL
        THEN RAISE EXCEPTION 'Payable read input is invalid' USING ERRCODE='P4902'; END IF;
        SELECT COALESCE(jsonb_agg(item.value ORDER BY item.due_date,item.issued_at,
                item.invoice_number COLLATE "C",item.invoice_id,item.rank,item.charge_id),'[]')
            INTO v_items FROM (
                SELECT invoice.id AS invoice_id,NULL::uuid AS charge_id,invoice.due_date,
                    invoice.issued_at,invoice.invoice_number,0 AS rank,
                    jsonb_build_object('kind','INVOICE','id',invoice.id,'invoice_id',invoice.id,
                        'invoice_number',invoice.invoice_number,'category',invoice.primary_category,
                        'due_date',invoice.due_date,'owed_usd_cents',
                        (SELECT COALESCE(sum(GREATEST(app.invoice_line_outstanding(line.id),0)),0)
                            FROM app.invoice_lines line WHERE line.invoice_id=invoice.id)) AS value
                FROM app.invoices invoice
                WHERE invoice.status IN ('UNPAID','PARTIALLY_PAID') AND invoice.customer_id=p_customer_id
                    AND app.invoice_property_id(invoice.id)=p_property_id
                UNION ALL
                SELECT invoice.id,charge.id,invoice.due_date,invoice.issued_at,invoice.invoice_number,1,
                    jsonb_build_object('kind','LATE_PAYMENT_CHARGE','id',charge.id,'invoice_id',invoice.id,
                        'invoice_number',invoice.invoice_number,'category',NULL,
                        'due_date',invoice.due_date,'owed_usd_cents',position.remaining_balance_usd_cents)
                FROM app.late_payment_charges charge
                JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
                JOIN app.late_payment_charge_financial_position position
                    ON position.late_payment_charge_id=charge.id
                WHERE position.remaining_balance_usd_cents>0 AND invoice.status<>'VOID'
                    AND app.invoice_property_id(invoice.id)=p_property_id
                    AND charge.customer_id=p_customer_id) item
            WHERE (item.value->>'owed_usd_cents')::bigint>0;
        RETURN jsonb_build_object('property_id',p_property_id,'customer_id',p_customer_id,
            'items',v_items);
    END $$;
    REVOKE ALL ON FUNCTION app.receive_payment_payable(uuid,uuid)
        FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
    GRANT EXECUTE ON FUNCTION app.receive_payment_payable(uuid,uuid) TO prm_runtime,prm_financial;
"""


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE app.receive_payment_commands (
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL CHECK(idempotency_key<>'00000000-0000-0000-0000-000000000000'),
            request_digest text NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$'),
            payment_id uuid NOT NULL UNIQUE REFERENCES app.payments(id) ON DELETE RESTRICT,
            response jsonb NOT NULL CHECK(jsonb_typeof(response)='object'),
            recorded_at timestamptz NOT NULL CHECK(isfinite(recorded_at)),
            PRIMARY KEY(property_id,actor_id,idempotency_key)
        );
        COMMENT ON TABLE app.receive_payment_commands IS
            'V1-058 R5c-1 (DL-077): one Receive payment command (payment, Receipt and allocations in one transaction) and its exact response.';
        CREATE TRIGGER receive_payment_commands_immutable
            BEFORE UPDATE OR DELETE ON app.receive_payment_commands
            FOR EACH ROW EXECUTE FUNCTION app.reject_invoice_append_only_mutation();
        CREATE TRIGGER receive_payment_commands_no_truncate
            BEFORE TRUNCATE ON app.receive_payment_commands
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_invoice_append_only_mutation();
        REVOKE ALL ON app.receive_payment_commands FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;

        CREATE FUNCTION app.receive_payment_replay(
            p_property_id uuid,p_actor_id uuid,p_key uuid,p_digest text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_command app.receive_payment_commands%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id,p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            IF p_key IS NULL OR p_key='00000000-0000-0000-0000-000000000000'
                OR p_digest IS NULL OR p_digest!~'^[0-9a-f]{64}$'
            THEN RAISE EXCEPTION 'Receive payment identity is invalid' USING ERRCODE='P5302'; END IF;
            -- Held until the Payment, its Receipt, its allocations and the response commit.
            PERFORM pg_advisory_xact_lock(hashtextextended('receive-payment:'
                ||p_property_id::text||':'||p_actor_id::text||':'||p_key::text,0));
            SELECT * INTO v_command FROM app.receive_payment_commands
                WHERE property_id=p_property_id AND actor_id=p_actor_id AND idempotency_key=p_key;
            IF FOUND THEN
                IF v_command.request_digest<>p_digest
                THEN RAISE EXCEPTION 'Receive payment key reused' USING ERRCODE='P5305'; END IF;
                RETURN v_command.response;
            END IF;
            RETURN NULL;
        END $$;


        CREATE FUNCTION app.receive_payment(
            p_property_id uuid,p_actor_id uuid,p_key uuid,p_digest text,
            p_request jsonb,p_selection jsonb,p_pays jsonb
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
          SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_result jsonb; v_confirm jsonb; v_payment app.payments%ROWTYPE; v_mode text;
        DECLARE v_proposal jsonb; v_found jsonb; v_targets jsonb:='[]'; v_target jsonb;
        DECLARE v_details jsonb; v_left bigint; v_take bigint; v_line record; v_invoice uuid;
        DECLARE v_post jsonb; v_allocations jsonb; v_seen uuid[]:='{}'; v_id uuid;
        DECLARE v_scope text:=p_property_id::text||':'||p_actor_id::text||':'||p_key::text;
        BEGIN
            v_result:=app.receive_payment_replay(p_property_id,p_actor_id,p_key,p_digest);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            v_mode:=p_pays->>'mode';
            IF p_pays IS NULL OR jsonb_typeof(p_pays)<>'object' OR v_mode IS NULL
                OR v_mode NOT IN ('OLDEST_FIRST','NAMED')
                OR p_pays-ARRAY['mode','targets']<>'{}'::jsonb
                OR jsonb_typeof(p_pays->'targets') IS DISTINCT FROM 'array'
                OR jsonb_array_length(p_pays->'targets')>100
                OR (v_mode='NAMED' AND jsonb_array_length(p_pays->'targets')=0)
            THEN RAISE EXCEPTION 'What the money pays is invalid' USING ERRCODE='P5302'; END IF;
            FOR v_target IN SELECT value FROM jsonb_array_elements(p_pays->'targets') LOOP
                IF jsonb_typeof(v_target)<>'object'
                    OR v_target-ARRAY['invoice_id','late_payment_charge_id','amount_usd_cents']<>'{}'::jsonb
                    OR (v_target ? 'invoice_id')=(v_target ? 'late_payment_charge_id')
                    OR jsonb_typeof(v_target->'amount_usd_cents') IS DISTINCT FROM 'number'
                    OR v_target->>'amount_usd_cents' !~ '^[1-9][0-9]{0,15}$'
                    OR jsonb_typeof(COALESCE(v_target->'invoice_id',v_target->'late_payment_charge_id'))
                        IS DISTINCT FROM 'string'
                    OR COALESCE(v_target->>'invoice_id',v_target->>'late_payment_charge_id') !~ '%(uuid)s'
                THEN RAISE EXCEPTION 'What the money pays is invalid' USING ERRCODE='P5302'; END IF;
                v_id:=COALESCE(v_target->>'invoice_id',v_target->>'late_payment_charge_id')::uuid;
                IF v_id=ANY(v_seen) OR (v_target->>'amount_usd_cents')::bigint>9000000000000000
                THEN RAISE EXCEPTION 'What the money pays is invalid' USING ERRCODE='P5302'; END IF;
                v_seen:=v_seen||v_id;
            END LOOP;
            -- Receive payment is for the payer's own money with nothing named on the Payment
            -- (review round 1): the proposal pays nothing for a Payment that names an Invoice
            -- or a charge, which would let money wait while the payer still owes.
            IF p_request->'payment_scope_kind' IS DISTINCT FROM '"NORMAL_CUSTOMER"'::jsonb
                OR p_request->'identified_invoice_id' IS DISTINCT FROM 'null'::jsonb
                OR p_request->'identified_late_payment_charge_id' IS DISTINCT FROM 'null'::jsonb
            THEN RAISE EXCEPTION 'Receive payment takes the payer''s own money' USING ERRCODE='P5302'; END IF;
            -- A key derived from this command's key: the confirmation can never replay a
            -- Payment confirmed earlier by another command.
            IF p_request->>'received_currency'='USD' AND p_selection IS NULL THEN
                v_confirm:=app.confirm_usd_payment(p_property_id,p_actor_id,
                    md5('receive-payment:confirm:'||v_scope)::uuid,p_request);
            ELSIF p_request->>'received_currency'='KHR' THEN
                v_confirm:=app.confirm_khr_payment(p_property_id,p_actor_id,
                    md5('receive-payment:confirm:'||v_scope)::uuid,p_request,p_selection);
            ELSE RAISE EXCEPTION 'Receive payment intent is invalid' USING ERRCODE='P5302'; END IF;
            SELECT * INTO STRICT v_payment FROM app.payments WHERE id=(v_confirm->'payment'->>'id')::uuid;
            -- Defensive: the derived key is new, so an older Payment can only mean key reuse.
            IF v_payment.confirmed_at<transaction_timestamp()
            THEN RAISE EXCEPTION 'Receive payment key reused' USING ERRCODE='P5305'; END IF;
            IF v_mode='OLDEST_FIRST' THEN
                v_proposal:=app.payment_allocation_proposal(p_property_id,v_payment.id,
                    clock_timestamp(),gen_random_uuid());
                SELECT COALESCE(jsonb_agg(CASE WHEN target ? 'invoice_id'
                        THEN jsonb_build_object('invoice_id',target->'invoice_id',
                            'amount_usd_cents',target->'amount_usd_cents')
                        ELSE jsonb_build_object('late_payment_charge_id',target->'late_payment_charge_id',
                            'amount_usd_cents',target->'amount_usd_cents') END ORDER BY position),'[]')
                    INTO v_found FROM jsonb_array_elements(v_proposal->'targets')
                    WITH ORDINALITY AS item(target,position);
                -- The screen showed these ticks; anything else means the Customer's Invoices
                -- changed meanwhile, so nothing is saved and the screen reads them again.
                IF v_found IS DISTINCT FROM p_pays->'targets'
                THEN RAISE EXCEPTION 'What the money pays changed; read it again' USING ERRCODE='P4904'; END IF;
                -- More than one proposal page (100 targets, 500 lines): money would wait while
                -- something is still owed, so this is refused with its own code.
                IF v_proposal->>'continuation_status'='MORE_ELIGIBLE'
                THEN RAISE EXCEPTION 'Too many unpaid items for one payment' USING ERRCODE='P5R02'; END IF;
                IF jsonb_array_length(v_found)>0 THEN
                    v_post:=app.post_payment_allocations(p_property_id,v_payment.id,p_actor_id,
                        md5('receive-payment:allocate:'||v_scope)::uuid,p_digest,
                        jsonb_build_object('mode','PROPOSAL','proposal',v_proposal));
                END IF;
            ELSE
                FOR v_target IN SELECT value FROM jsonb_array_elements(p_pays->'targets') LOOP
                    IF v_target ? 'late_payment_charge_id' THEN
                        v_targets:=v_targets||jsonb_build_array(v_target);
                        CONTINUE;
                    END IF;
                    SELECT id INTO v_invoice FROM app.invoices
                        WHERE id=(v_target->>'invoice_id')::uuid AND app.invoice_property_id(id)=p_property_id;
                    IF NOT FOUND THEN RAISE EXCEPTION 'Invoice not found' USING ERRCODE='P4901'; END IF;
                    v_left:=(v_target->>'amount_usd_cents')::bigint; v_details:='[]';
                    -- The proposal's line order: Rent, then Services, then the other lines.
                    FOR v_line IN SELECT line.id,app.invoice_line_outstanding(line.id) AS outstanding
                        FROM app.invoice_lines line WHERE line.invoice_id=v_invoice
                        ORDER BY CASE line.category WHEN 'RENT' THEN 0 WHEN 'SERVICE_CHARGES' THEN 1 ELSE 2 END,
                            line.line_sequence,line.id
                    LOOP
                        EXIT WHEN v_left=0;
                        CONTINUE WHEN v_line.outstanding<=0;
                        v_take:=LEAST(v_left,v_line.outstanding);
                        v_details:=v_details||jsonb_build_array(jsonb_build_object(
                            'invoice_line_id',v_line.id,'amount_usd_cents',v_take));
                        v_left:=v_left-v_take;
                    END LOOP;
                    -- The screen takes each amount from the list it read, so more than the
                    -- Invoice owes now means the list changed meanwhile.
                    IF v_left>0
                    THEN RAISE EXCEPTION 'More than the Invoice owes' USING ERRCODE='P4904'; END IF;
                    v_targets:=v_targets||jsonb_build_array(jsonb_build_object('invoice_id',v_invoice,
                        'amount_usd_cents',v_target->'amount_usd_cents','details',v_details));
                END LOOP;
                v_post:=app.post_payment_allocations(p_property_id,v_payment.id,p_actor_id,
                    md5('receive-payment:allocate:'||v_scope)::uuid,p_digest,
                    jsonb_build_object('mode','DESIGNATED','targets',v_targets,
                        'designation_reference','Named by the payer at Receive payment'));
                -- No "keep it for later" while the payer still owes something (DL-077).
                IF app.payment_available_value(v_payment.id)>0
                    AND jsonb_array_length(app.payment_allocation_proposal(p_property_id,v_payment.id,
                        clock_timestamp(),gen_random_uuid())->'targets')>0
                THEN RAISE EXCEPTION 'Money is left while other Invoices are unpaid' USING ERRCODE='P5R01'; END IF;
            END IF;
            SELECT COALESCE(jsonb_agg(jsonb_build_object('allocation_id',allocation.id,
                    'target_kind',allocation.target_kind,'invoice_id',allocation.invoice_id,
                    'late_payment_charge_id',allocation.late_payment_charge_id,
                    'invoice_number',invoice.invoice_number,
                    'amount_usd_cents',allocation.amount_usd_cents) ORDER BY item.position),'[]')
                INTO v_allocations
                FROM jsonb_array_elements_text(COALESCE(v_post->'allocation_ids','[]'))
                    WITH ORDINALITY AS item(id,position)
                JOIN app.payment_allocations allocation ON allocation.id=item.id::uuid
                LEFT JOIN app.late_payment_charges charge ON charge.id=allocation.late_payment_charge_id
                JOIN app.invoices invoice ON invoice.id=COALESCE(allocation.invoice_id,charge.source_invoice_id);
            v_result:=v_confirm||jsonb_build_object('pays_mode',v_mode,'allocations',v_allocations,
                'left_usd_cents',app.payment_available_value(v_payment.id));
            INSERT INTO app.receive_payment_commands
                VALUES(p_property_id,p_actor_id,p_key,p_digest,v_payment.id,v_result,clock_timestamp());
            RETURN v_result;
        END $$;
        REVOKE ALL ON FUNCTION app.receive_payment_replay(uuid,uuid,uuid,text),
            app.receive_payment(uuid,uuid,uuid,text,jsonb,jsonb,jsonb)
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        GRANT EXECUTE ON FUNCTION app.receive_payment_replay(uuid,uuid,uuid,text),
            app.receive_payment(uuid,uuid,uuid,text,jsonb,jsonb,jsonb) TO prm_financial;
    """.replace("%(uuid)s", UUID_PATTERN)
    )
    op.execute(PAYABLE)


def downgrade() -> None:
    raise RuntimeError("Receive payment history is forward-only; downgrade is not supported")
