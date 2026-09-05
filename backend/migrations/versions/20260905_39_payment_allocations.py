# ruff: noqa: E501
"""Add explicit Payment allocation events and authoritative application projections."""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision = "20260905_39"
down_revision = "20260905_38"
branch_labels = None
depends_on = None


def replace_function(signature: str, replacements: Sequence[tuple[str, str]]) -> None:
    """Preserve the prior guard verbatim except for reviewed, asserted integration points."""
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in replacements:
        if before not in definition:
            raise RuntimeError(f"Allocation migration source contract changed: {signature}")
        definition = definition.replace(before, after)
    op.execute(definition)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.payment_allocations (
            id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
            payment_id uuid NOT NULL REFERENCES app.payments(id) ON DELETE RESTRICT,
            target_customer_id uuid NOT NULL REFERENCES app.customers(id) ON DELETE RESTRICT,
            proposal_batch_id uuid,
            between_invoice_sequence smallint CHECK(between_invoice_sequence>0),
            target_kind text NOT NULL CHECK(target_kind IN ('INVOICE','LATE_PAYMENT_CHARGE')),
            invoice_id uuid REFERENCES app.invoices(id) ON DELETE RESTRICT,
            late_payment_charge_id uuid REFERENCES app.late_payment_charges(id) ON DELETE RESTRICT,
            amount_usd_cents bigint NOT NULL CHECK(amount_usd_cents BETWEEN 1 AND 9000000000000000),
            between_invoice_basis text NOT NULL CHECK(between_invoice_basis IN (
                'FIFO_PROPOSAL','CUSTOMER_DESIGNATED','THIRD_PARTY_DESIGNATED',
                'DIRECT_LATE_PAYMENT_CHARGE')),
            within_invoice_basis text NOT NULL CHECK(within_invoice_basis IN (
                'RENT_THEN_RECURRING_SERVICES_PROPOSAL','CUSTOMER_DESIGNATED',
                'OTHER_APPLICABLE_OBLIGATION','NOT_APPLICABLE')),
            customer_designation_reference text CHECK(
                customer_designation_reference=btrim(customer_designation_reference)
                AND length(customer_designation_reference) BETWEEN 1 AND 500),
            selected_invoice_due_date date,
            selected_invoice_issued_at timestamptz,
            selected_invoice_number_snapshot text,
            proposal_generated_at timestamptz,
            proposal_trace jsonb,
            posted_at timestamptz NOT NULL CHECK(isfinite(posted_at)),
            posted_by uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL CHECK(authorization_reference='payments.allocate'),
            CONSTRAINT allocation_exact_target CHECK(
                (target_kind='INVOICE' AND invoice_id IS NOT NULL AND late_payment_charge_id IS NULL)
                OR (target_kind='LATE_PAYMENT_CHARGE' AND invoice_id IS NULL
                    AND late_payment_charge_id IS NOT NULL)),
            CONSTRAINT allocation_designation CHECK(
                (between_invoice_basis IN ('CUSTOMER_DESIGNATED','THIRD_PARTY_DESIGNATED'))
                = (customer_designation_reference IS NOT NULL)),
            CONSTRAINT allocation_proposal_shape CHECK(
                (proposal_batch_id IS NULL AND between_invoice_sequence IS NULL
                    AND selected_invoice_due_date IS NULL AND selected_invoice_issued_at IS NULL
                    AND selected_invoice_number_snapshot IS NULL AND proposal_generated_at IS NULL
                    AND proposal_trace IS NULL AND between_invoice_basis<>'FIFO_PROPOSAL'
                    AND within_invoice_basis<>'RENT_THEN_RECURRING_SERVICES_PROPOSAL')
                OR (proposal_batch_id IS NOT NULL AND between_invoice_sequence IS NOT NULL
                    AND target_kind='INVOICE' AND selected_invoice_due_date IS NOT NULL
                    AND selected_invoice_issued_at IS NOT NULL
                    AND selected_invoice_number_snapshot IS NOT NULL
                    AND proposal_generated_at IS NOT NULL AND isfinite(proposal_generated_at)
                    AND proposal_generated_at<=posted_at AND proposal_trace IS NOT NULL
                    AND jsonb_typeof(proposal_trace)='object'
                    AND between_invoice_basis<>'DIRECT_LATE_PAYMENT_CHARGE')),
            CONSTRAINT allocation_charge_basis CHECK(
                (target_kind='LATE_PAYMENT_CHARGE')=(within_invoice_basis='NOT_APPLICABLE'))
        );
        CREATE UNIQUE INDEX payment_allocation_proposal_sequence_idx
            ON app.payment_allocations(payment_id,proposal_batch_id,between_invoice_sequence)
            WHERE proposal_batch_id IS NOT NULL;
        CREATE INDEX payment_allocations_source_idx ON app.payment_allocations(payment_id,posted_at,id);
        CREATE INDEX payment_allocations_invoice_idx ON app.payment_allocations(invoice_id)
            WHERE invoice_id IS NOT NULL;
        CREATE INDEX payment_allocations_charge_idx ON app.payment_allocations(late_payment_charge_id)
            WHERE late_payment_charge_id IS NOT NULL;

        CREATE TABLE app.payment_allocation_details (
            id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
            payment_allocation_id uuid NOT NULL REFERENCES app.payment_allocations(id)
                ON DELETE RESTRICT,
            invoice_line_id uuid REFERENCES app.invoice_lines(id) ON DELETE RESTRICT,
            late_payment_charge_id uuid REFERENCES app.late_payment_charges(id) ON DELETE RESTRICT,
            obligation_kind text NOT NULL CHECK(obligation_kind IN ('INVOICE_LINE','LATE_PAYMENT_CHARGE')),
            invoice_line_category_snapshot text,
            proposed_amount_usd_cents bigint CHECK(proposed_amount_usd_cents BETWEEN 1 AND 9000000000000000),
            posted_amount_usd_cents bigint NOT NULL CHECK(posted_amount_usd_cents BETWEEN 1 AND 9000000000000000),
            attribution_basis text NOT NULL CHECK(attribution_basis IN (
                'RENT_FIRST_PROPOSAL','SERVICE_PROPOSAL','CUSTOMER_DESIGNATED',
                'THIRD_PARTY_DESIGNATED','OTHER_CONFIRMED','DIRECT_LATE_PAYMENT_CHARGE')),
            detail_sequence smallint NOT NULL CHECK(detail_sequence>0),
            calculation_trace jsonb NOT NULL CHECK(jsonb_typeof(calculation_trace)='object'),
            UNIQUE(payment_allocation_id,detail_sequence),
            UNIQUE(payment_allocation_id,invoice_line_id),
            UNIQUE(payment_allocation_id,late_payment_charge_id),
            CONSTRAINT allocation_detail_target CHECK(
                (obligation_kind='INVOICE_LINE' AND invoice_line_id IS NOT NULL
                    AND late_payment_charge_id IS NULL AND invoice_line_category_snapshot IS NOT NULL)
                OR (obligation_kind='LATE_PAYMENT_CHARGE' AND invoice_line_id IS NULL
                    AND late_payment_charge_id IS NOT NULL AND invoice_line_category_snapshot IS NULL))
        );
        CREATE INDEX payment_allocation_details_line_idx ON app.payment_allocation_details(invoice_line_id)
            WHERE invoice_line_id IS NOT NULL;
        CREATE INDEX payment_allocation_details_charge_idx ON app.payment_allocation_details(late_payment_charge_id)
            WHERE late_payment_charge_id IS NOT NULL;
        CREATE TABLE app.payment_allocation_reversals (
            id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
            payment_allocation_id uuid NOT NULL UNIQUE REFERENCES app.payment_allocations(id)
                ON DELETE RESTRICT,
            reason text NOT NULL CHECK(reason=btrim(reason) AND length(reason) BETWEEN 1 AND 1000),
            occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at)),
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL CHECK(authorization_reference='payments.allocate')
        );
        CREATE TABLE app.payment_allocation_commands (
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            action text NOT NULL CHECK(action IN ('POST','REVERSE_ALLOCATION','REVERSE_PAYMENT')),
            idempotency_key uuid NOT NULL CHECK(idempotency_key<>'00000000-0000-0000-0000-000000000000'),
            request_digest text NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$'),
            target_id uuid NOT NULL,
            response jsonb NOT NULL CHECK(jsonb_typeof(response)='object'),
            completed_at timestamptz NOT NULL CHECK(isfinite(completed_at)),
            PRIMARY KEY(property_id,actor_id,action,idempotency_key)
        );

        CREATE FUNCTION app.payment_allocated_value_at(p_payment_id uuid,p_as_of timestamptz)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT COALESCE(sum(allocation.amount_usd_cents),0)::bigint
            FROM app.payment_allocations allocation
            LEFT JOIN app.payment_allocation_reversals reversal
                ON reversal.payment_allocation_id=allocation.id
            WHERE allocation.payment_id=p_payment_id AND allocation.posted_at<=p_as_of
                AND (reversal.id IS NULL OR reversal.occurred_at>p_as_of)
        $$;
        CREATE FUNCTION app.invoice_line_payment_value_at(p_line_id uuid,p_as_of timestamptz)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT COALESCE(sum(detail.posted_amount_usd_cents),0)::bigint
            FROM app.payment_allocation_details detail
            JOIN app.payment_allocations allocation ON allocation.id=detail.payment_allocation_id
            LEFT JOIN app.payment_allocation_reversals reversal
                ON reversal.payment_allocation_id=allocation.id
            WHERE detail.invoice_line_id=p_line_id AND allocation.posted_at<=p_as_of
                AND (reversal.id IS NULL OR reversal.occurred_at>p_as_of)
        $$;
        CREATE FUNCTION app.invoice_line_outstanding_at(p_line_id uuid,p_as_of timestamptz)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT app.invoice_adjusted_line_obligation_at(p_line_id,p_as_of)
                - app.invoice_line_payment_value_at(p_line_id,p_as_of)
        $$;
        CREATE FUNCTION app.invoice_line_outstanding(p_line_id uuid)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT app.invoice_adjusted_line_obligation(p_line_id)
                - app.invoice_line_payment_value_at(p_line_id,'infinity'::timestamptz)
        $$;
        CREATE FUNCTION app.invoice_application_status(p_invoice_id uuid)
        RETURNS text LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT CASE WHEN COALESCE(sum(app.invoice_line_outstanding(line.id)),0)=0 THEN 'PAID'
                WHEN COALESCE(sum(app.invoice_line_payment_value_at(line.id,'infinity'::timestamptz)),0)>0
                    THEN 'PARTIALLY_PAID' ELSE 'UNPAID' END
            FROM app.invoice_lines line WHERE line.invoice_id=p_invoice_id
        $$;
        CREATE OR REPLACE FUNCTION app.payment_disposition_summary(p_payment_id uuid)
        RETURNS jsonb LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT jsonb_build_object(
                'allocation_usd_cents',app.payment_allocated_value_at(p_payment_id,'infinity'::timestamptz),
                'deposit_usd_cents',COALESCE((SELECT sum(receipt.amount_usd_cents)
                    FROM app.deposit_receipts receipt WHERE receipt.payment_id=p_payment_id
                    AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                        WHERE reversal.deposit_receipt_id=receipt.id)),0),
                'credit_usd_cents',0,'refund_usd_cents',0)
        $$;
        COMMENT ON FUNCTION app.payment_disposition_summary(uuid) IS
            'Authoritative active Allocation and Deposit receipt consumption; V1-051 must extend Credit/direct Refund terms without replacing current consumers.';
        CREATE FUNCTION app.payment_available_value(p_payment_id uuid)
        RETURNS bigint LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT CASE WHEN payment.status='REVERSED' THEN 0 ELSE
                payment.usd_accounting_value_cents-COALESCE((SELECT sum(value::numeric)
                FROM jsonb_each_text(app.payment_disposition_summary(payment.id))),0)::bigint END
            FROM app.payments payment WHERE payment.id=p_payment_id
        $$;
        CREATE VIEW app.payment_financial_position WITH(security_invoker=true) AS
            SELECT payment.id AS payment_id,payment.payer_customer_id,payment.property_id,
                payment.status,payment.usd_accounting_value_cents AS original_usd_cents,
                app.payment_allocated_value_at(payment.id,'infinity'::timestamptz) AS allocated_usd_cents,
                (app.payment_disposition_summary(payment.id)->>'deposit_usd_cents')::bigint
                    AS deposit_directed_usd_cents,
                app.payment_available_value(payment.id) AS available_usd_cents,
                CASE WHEN app.payment_allocated_value_at(payment.id,'infinity'::timestamptz)=0
                    THEN 'UNALLOCATED' WHEN app.payment_available_value(payment.id)=0
                    THEN 'FULLY_ALLOCATED' ELSE 'PARTIALLY_ALLOCATED' END AS allocation_condition
            FROM app.payments payment;

        CREATE OR REPLACE FUNCTION app.late_payment_charge_application_summary(p_charge_id uuid)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT CASE WHEN EXISTS(SELECT 1 FROM app.late_payment_charges WHERE id=p_charge_id)
            THEN jsonb_build_object(
                'active_total_usd_cents',COALESCE(sum(allocation.amount_usd_cents),0),
                'payment_total_usd_cents',COALESCE(sum(allocation.amount_usd_cents),0),
                'credit_total_usd_cents',0,
                'items',COALESCE(jsonb_agg(jsonb_build_object(
                    'kind','PAYMENT_ALLOCATION','id',allocation.id,
                    'payment_id',allocation.payment_id,'amount_usd_cents',allocation.amount_usd_cents,
                    'posted_at',allocation.posted_at) ORDER BY allocation.posted_at,allocation.id)
                    FILTER(WHERE allocation.id IS NOT NULL),'[]'::jsonb)) ELSE NULL END
            FROM app.payment_allocations allocation
            WHERE allocation.late_payment_charge_id=p_charge_id AND NOT EXISTS(
                SELECT 1 FROM app.payment_allocation_reversals reversal
                    WHERE reversal.payment_allocation_id=allocation.id)
        $$;

        CREATE FUNCTION app.lock_payment_allocation_target(p_kind text,p_target_id uuid)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_invoice_id uuid;
        BEGIN
            IF p_kind='INVOICE' THEN
                PERFORM 1 FROM app.invoices WHERE id=p_target_id FOR UPDATE;
                IF pg_trigger_depth()>0 THEN
                    PERFORM app.advance_invoice_serialization_guard('invoice-financial:'||p_target_id::text);
                END IF;
            ELSIF p_kind='LATE_PAYMENT_CHARGE' THEN
                SELECT source_invoice_id INTO v_invoice_id
                    FROM app.late_payment_charges WHERE id=p_target_id FOR UPDATE;
                PERFORM 1 FROM app.invoices WHERE id=v_invoice_id FOR UPDATE;
                IF pg_trigger_depth()>0 THEN
                    PERFORM app.advance_invoice_serialization_guard('invoice-financial:'||v_invoice_id::text);
                    PERFORM app.advance_invoice_serialization_guard('late-charge:'||p_target_id::text);
                END IF;
            ELSE RAISE EXCEPTION 'Allocation target kind is invalid' USING ERRCODE='23514'; END IF;
        END $$;

        CREATE FUNCTION app.allocation_target_latest_at(p_kind text,p_target_id uuid)
        RETURNS timestamptz LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT max(event_at) FROM (
                SELECT posted_at AS event_at FROM app.payment_allocations
                    WHERE (p_kind='INVOICE' AND invoice_id=p_target_id)
                        OR (p_kind='LATE_PAYMENT_CHARGE' AND late_payment_charge_id=p_target_id)
                UNION ALL SELECT reversal.occurred_at FROM app.payment_allocation_reversals reversal
                    JOIN app.payment_allocations allocation ON allocation.id=reversal.payment_allocation_id
                    WHERE (p_kind='INVOICE' AND allocation.invoice_id=p_target_id)
                        OR (p_kind='LATE_PAYMENT_CHARGE' AND allocation.late_payment_charge_id=p_target_id)
                UNION ALL SELECT occurred_at FROM app.invoice_adjustments
                    WHERE p_kind='INVOICE' AND invoice_id=p_target_id
                UNION ALL SELECT reversal.occurred_at FROM app.invoice_adjustment_reversals reversal
                    JOIN app.invoice_adjustments adjustment ON adjustment.id=reversal.invoice_adjustment_id
                    WHERE p_kind='INVOICE' AND adjustment.invoice_id=p_target_id
                UNION ALL SELECT finalized_at FROM app.late_payment_decisions
                    WHERE p_kind='INVOICE' AND source_invoice_id=p_target_id
                UNION ALL SELECT occurred_at FROM app.late_payment_charge_corrections
                    WHERE p_kind='LATE_PAYMENT_CHARGE' AND late_payment_charge_id=p_target_id
            ) events
        $$;

        CREATE FUNCTION app.validate_payment_allocation_source()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_payment app.payments%ROWTYPE; v_customer uuid; v_property uuid; v_lease uuid;
        DECLARE v_invoice app.invoices%ROWTYPE; v_target_invoice uuid; v_balance bigint;
        DECLARE v_source_at timestamptz;
        BEGIN
            PERFORM app.assert_active_financial_actor(NEW.posted_by,NULL);
            PERFORM app.serialize_payment_state(NEW.payment_id);
            SELECT * INTO STRICT v_payment FROM app.payments WHERE id=NEW.payment_id FOR UPDATE;
            PERFORM app.lock_payment_allocation_target(NEW.target_kind,
                COALESCE(NEW.invoice_id,NEW.late_payment_charge_id));
            IF NEW.target_kind='INVOICE' THEN
                SELECT * INTO STRICT v_invoice FROM app.invoices WHERE id=NEW.invoice_id;
                v_target_invoice:=v_invoice.id; v_customer:=v_invoice.customer_id;
                v_lease:=v_invoice.lease_id; v_property:=app.invoice_property_id(v_invoice.id);
                v_source_at:=GREATEST(v_invoice.issued_at,v_invoice.updated_at);
                SELECT COALESCE(sum(app.invoice_line_outstanding(id)),0)
                    INTO v_balance FROM app.invoice_lines WHERE invoice_id=v_invoice.id;
                IF v_invoice.status NOT IN ('UNPAID','PARTIALLY_PAID','PAID') THEN
                    RAISE EXCEPTION 'Allocation requires an issued non-VOID Invoice' USING ERRCODE='23514';
                END IF;
                IF NEW.proposal_batch_id IS NOT NULL AND (
                    NEW.selected_invoice_due_date IS DISTINCT FROM v_invoice.due_date
                    OR NEW.selected_invoice_issued_at IS DISTINCT FROM v_invoice.issued_at
                    OR NEW.selected_invoice_number_snapshot IS DISTINCT FROM v_invoice.invoice_number)
                THEN RAISE EXCEPTION 'Allocation proposal evidence is stale' USING ERRCODE='40001'; END IF;
            ELSE
                SELECT charge.customer_id,invoice.lease_id,invoice.id,
                    app.invoice_property_id(invoice.id),position.remaining_balance_usd_cents,
                    GREATEST(charge.created_at,charge.payable_at)
                INTO STRICT v_customer,v_lease,v_target_invoice,v_property,v_balance,v_source_at
                FROM app.late_payment_charges charge
                JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
                JOIN app.late_payment_charge_financial_position position
                    ON position.late_payment_charge_id=charge.id
                WHERE charge.id=NEW.late_payment_charge_id;
            END IF;
            IF v_payment.status<>'RECEIVED' OR v_property IS DISTINCT FROM v_payment.property_id
                OR NEW.target_customer_id IS DISTINCT FROM v_customer
                OR NEW.amount_usd_cents>app.payment_available_value(NEW.payment_id)
                OR NEW.amount_usd_cents>v_balance
                OR NEW.posted_at<v_payment.confirmed_at OR NEW.posted_at<v_source_at
                OR NEW.posted_at>clock_timestamp()+interval '5 seconds'
                OR NEW.posted_at<=app.allocation_target_latest_at(NEW.target_kind,
                    COALESCE(NEW.invoice_id,NEW.late_payment_charge_id))
            THEN RAISE EXCEPTION 'Allocation source, amount or chronology is invalid' USING ERRCODE='23514'; END IF;
            PERFORM app.assert_active_financial_actor(NEW.posted_by,v_property);
            IF v_payment.payment_scope_kind='NORMAL_CUSTOMER' THEN
                IF v_customer<>v_payment.payer_customer_id
                    OR NEW.between_invoice_basis='THIRD_PARTY_DESIGNATED'
                THEN RAISE EXCEPTION 'Normal allocation target must belong to payer' USING ERRCODE='23514'; END IF;
            ELSE
                IF NEW.between_invoice_basis<>'THIRD_PARTY_DESIGNATED'
                    OR (v_payment.lease_id IS NOT NULL AND v_lease IS DISTINCT FROM v_payment.lease_id)
                THEN RAISE EXCEPTION 'Third-party allocation is outside identified intent' USING ERRCODE='23514'; END IF;
            END IF;
            IF (v_payment.identified_invoice_id IS NOT NULL
                    AND v_target_invoice IS DISTINCT FROM v_payment.identified_invoice_id)
                OR (v_payment.identified_late_payment_charge_id IS NOT NULL
                    AND NEW.late_payment_charge_id IS DISTINCT FROM v_payment.identified_late_payment_charge_id)
            THEN RAISE EXCEPTION 'Allocation differs from confirmed target intent' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER payment_allocations_validate BEFORE INSERT ON app.payment_allocations
            FOR EACH ROW EXECUTE FUNCTION app.validate_payment_allocation_source();

        CREATE FUNCTION app.refresh_allocated_invoice(p_invoice_id uuid,p_actor_id uuid,p_force boolean)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_status text; v_desired text;
        BEGIN
            SELECT status INTO v_status FROM app.invoices WHERE id=p_invoice_id FOR UPDATE;
            IF v_status NOT IN ('UNPAID','PARTIALLY_PAID','PAID') THEN RETURN; END IF;
            v_desired:=app.invoice_application_status(p_invoice_id);
            IF p_force OR v_status<>v_desired THEN
                UPDATE app.invoices SET status=v_desired,version=version+1,
                    updated_at=clock_timestamp(),updated_by=p_actor_id WHERE id=p_invoice_id;
            END IF;
        END $$;

        CREATE FUNCTION app.validate_allocation_complete_state()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_id uuid; v_header app.payment_allocations%ROWTYPE; v_total numeric; v_count integer;
        BEGIN
            IF TG_TABLE_NAME='payment_allocations' THEN v_id:=NEW.id;
            ELSE v_id:=NEW.payment_allocation_id; END IF;
            SELECT * INTO STRICT v_header FROM app.payment_allocations WHERE id=v_id;
            SELECT sum(posted_amount_usd_cents),count(*) INTO v_total,v_count
                FROM app.payment_allocation_details WHERE payment_allocation_id=v_id;
            -- The immutable header's deferred event validates every detail and
            -- projection once. Positive append-only details cannot be added later
            -- without changing this sum, so detail events need only enforce the
            -- immutable total. Avoid re-projecting a large Invoice for every line.
            IF TG_TABLE_NAME='payment_allocation_details' THEN
                IF v_total IS DISTINCT FROM v_header.amount_usd_cents::numeric THEN
                    RAISE EXCEPTION 'Allocation header and detail totals must reconcile' USING ERRCODE='23514';
                END IF;
                RETURN NULL;
            END IF;
            IF v_total IS DISTINCT FROM v_header.amount_usd_cents::numeric OR v_count=0
                OR (v_header.target_kind='LATE_PAYMENT_CHARGE' AND v_count<>1)
                OR EXISTS(SELECT 1 FROM app.payment_allocation_details detail
                    LEFT JOIN app.invoice_lines line ON line.id=detail.invoice_line_id
                    WHERE detail.payment_allocation_id=v_id AND (
                        (v_header.target_kind='INVOICE' AND (
                            detail.obligation_kind<>'INVOICE_LINE'
                            OR line.invoice_id IS DISTINCT FROM v_header.invoice_id
                            OR line.category IS DISTINCT FROM detail.invoice_line_category_snapshot))
                        OR (v_header.target_kind='LATE_PAYMENT_CHARGE' AND (
                            detail.obligation_kind<>'LATE_PAYMENT_CHARGE'
                            OR detail.late_payment_charge_id IS DISTINCT FROM v_header.late_payment_charge_id))
                        OR ((v_header.proposal_batch_id IS NULL)
                            IS DISTINCT FROM (detail.proposed_amount_usd_cents IS NULL))
                        OR detail.posted_amount_usd_cents>detail.proposed_amount_usd_cents))
                OR app.payment_available_value(v_header.payment_id)<0
                OR EXISTS(SELECT 1 FROM app.payment_allocation_details detail
                    WHERE detail.payment_allocation_id=v_id AND detail.invoice_line_id IS NOT NULL
                        AND app.invoice_line_outstanding(detail.invoice_line_id)<0)
                OR EXISTS(SELECT 1 FROM app.late_payment_charge_financial_position position
                    WHERE position.late_payment_charge_id=v_header.late_payment_charge_id
                        AND position.remaining_balance_usd_cents<0)
            THEN RAISE EXCEPTION 'Allocation header, detail and financial position must reconcile' USING ERRCODE='23514'; END IF;
            IF v_header.invoice_id IS NOT NULL THEN
                PERFORM app.refresh_allocated_invoice(v_header.invoice_id,v_header.posted_by,false);
            END IF;
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER payment_allocations_complete AFTER INSERT ON app.payment_allocations
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_allocation_complete_state();
        CREATE CONSTRAINT TRIGGER payment_allocation_details_complete AFTER INSERT ON app.payment_allocation_details
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_allocation_complete_state();

        CREATE FUNCTION app.validate_payment_allocation_reversal()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_header app.payment_allocations%ROWTYPE;
        BEGIN
            SELECT * INTO STRICT v_header FROM app.payment_allocations WHERE id=NEW.payment_allocation_id;
            PERFORM app.assert_active_financial_actor(NEW.actor_id,NULL);
            PERFORM app.serialize_payment_state(v_header.payment_id);
            PERFORM 1 FROM app.payments WHERE id=v_header.payment_id FOR UPDATE;
            PERFORM app.lock_payment_allocation_target(v_header.target_kind,
                COALESCE(v_header.invoice_id,v_header.late_payment_charge_id));
            IF NEW.occurred_at<v_header.posted_at OR NEW.occurred_at>clock_timestamp()+interval '5 seconds'
                OR NEW.occurred_at<=app.allocation_target_latest_at(v_header.target_kind,
                    COALESCE(v_header.invoice_id,v_header.late_payment_charge_id))
            THEN RAISE EXCEPTION 'Allocation reversal chronology is invalid' USING ERRCODE='23514'; END IF;
            PERFORM app.assert_active_financial_actor(NEW.actor_id,
                (SELECT property_id FROM app.payments WHERE id=v_header.payment_id));
            RETURN NEW;
        END $$;
        CREATE TRIGGER payment_allocation_reversals_validate BEFORE INSERT ON app.payment_allocation_reversals
            FOR EACH ROW EXECUTE FUNCTION app.validate_payment_allocation_reversal();
        CREATE FUNCTION app.reconcile_payment_allocation_reversal()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_invoice uuid;
        BEGIN
            SELECT invoice_id INTO v_invoice FROM app.payment_allocations WHERE id=NEW.payment_allocation_id;
            IF v_invoice IS NOT NULL THEN
                PERFORM app.refresh_allocated_invoice(v_invoice,NEW.actor_id,true);
            END IF;
            RETURN NULL;
        END $$;
        CREATE TRIGGER payment_allocation_reversals_reconcile AFTER INSERT ON app.payment_allocation_reversals
            FOR EACH ROW EXECUTE FUNCTION app.reconcile_payment_allocation_reversal();
        """
    )
    integrate_existing_financial_guards()
    create_payment_history_budget_guard()
    create_allocation_services()
    for table in (
        "payment_allocations",
        "payment_allocation_details",
        "payment_allocation_reversals",
        "payment_allocation_commands",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.reject_invoice_append_only_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON app.{table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION app.reject_invoice_append_only_mutation()"
        )
        op.execute(
            f"REVOKE ALL ON TABLE app.{table} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
        op.execute(f"GRANT SELECT ON TABLE app.{table} TO prm_runtime,prm_financial")
    for function in (
        "payment_allocated_value_at(uuid,timestamptz)",
        "invoice_line_payment_value_at(uuid,timestamptz)",
        "invoice_line_outstanding_at(uuid,timestamptz)",
        "invoice_line_outstanding(uuid)",
        "invoice_application_status(uuid)",
        "payment_available_value(uuid)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION app.{function} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
        op.execute(f"GRANT EXECUTE ON FUNCTION app.{function} TO prm_runtime,prm_financial")
    op.execute("GRANT SELECT ON app.payment_financial_position TO prm_runtime,prm_financial")
    for function in (
        "lock_payment_allocation_target(text,uuid)",
        "allocation_target_latest_at(text,uuid)",
        "validate_payment_allocation_source()",
        "refresh_allocated_invoice(uuid,uuid,boolean)",
        "validate_allocation_complete_state()",
        "validate_payment_allocation_reversal()",
        "reconcile_payment_allocation_reversal()",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION app.{function} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )


def create_payment_history_budget_guard() -> None:
    """Validate every historical breakpoint, not just today's released source value."""
    op.execute("""
        CREATE FUNCTION app.validate_payment_history_budget()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_payment_id uuid; v_original bigint;
        BEGIN
            IF TG_TABLE_NAME IN ('payment_allocations','deposit_receipts') THEN
                v_payment_id:=NEW.payment_id;
            ELSIF TG_TABLE_NAME='payment_allocation_reversals' THEN
                SELECT payment_id INTO STRICT v_payment_id FROM app.payment_allocations
                    WHERE id=NEW.payment_allocation_id;
            ELSE
                SELECT payment_id INTO STRICT v_payment_id FROM app.deposit_receipts
                    WHERE id=NEW.deposit_receipt_id;
            END IF;
            SELECT usd_accounting_value_cents INTO STRICT v_original FROM app.payments
                WHERE id=v_payment_id;
            IF EXISTS (
                WITH events AS (
                    SELECT posted_at AS event_at,amount_usd_cents::numeric AS delta
                    FROM app.payment_allocations WHERE payment_id=v_payment_id
                    UNION ALL
                    SELECT reversal.occurred_at,-allocation.amount_usd_cents::numeric
                    FROM app.payment_allocation_reversals reversal
                    JOIN app.payment_allocations allocation ON allocation.id=reversal.payment_allocation_id
                    WHERE allocation.payment_id=v_payment_id
                    UNION ALL
                    SELECT occurred_at,amount_usd_cents::numeric FROM app.deposit_receipts
                    WHERE payment_id=v_payment_id
                    UNION ALL
                    SELECT reversal.occurred_at,-receipt.amount_usd_cents::numeric
                    FROM app.deposit_receipt_reversals reversal
                    JOIN app.deposit_receipts receipt ON receipt.id=reversal.deposit_receipt_id
                    WHERE receipt.payment_id=v_payment_id
                ), positions AS (
                    SELECT sum(sum(delta)) OVER (ORDER BY event_at) AS used
                    FROM events GROUP BY event_at
                ) SELECT 1 FROM positions WHERE used<0 OR used>v_original
            ) THEN
                RAISE EXCEPTION 'Payment historical availability exceeded' USING ERRCODE='23514';
            END IF;
            RETURN NULL;
        END $$;
        REVOKE ALL ON FUNCTION app.validate_payment_history_budget()
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        COMMENT ON FUNCTION app.validate_payment_history_budget() IS
            'V1-049 all historical Allocation/Deposit breakpoints; V1-051 must extend for Credit/Refund consumers.';
    """)
    for table in (
        "payment_allocations",
        "payment_allocation_reversals",
        "deposit_receipts",
        "deposit_receipt_reversals",
    ):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER {table}_payment_history_budget AFTER INSERT ON app.{table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
            "EXECUTE FUNCTION app.validate_payment_history_budget()"
        )


def create_allocation_services() -> None:
    """Expose explicit commands, never table mutation, to the financial service role."""
    op.execute("""
        CREATE FUNCTION app.payment_allocation_proposal(
            p_property_id uuid,p_payment_id uuid,p_generated_at timestamptz,p_batch_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_payment app.payments%ROWTYPE; v_invoice record; v_line record;
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
            v_available:=app.payment_available_value(p_payment_id); v_remaining:=v_available;
            FOR v_invoice IN SELECT invoice.* FROM app.invoices invoice
                WHERE invoice.status IN ('UNPAID','PARTIALLY_PAID')
                    AND app.invoice_property_id(invoice.id)=p_property_id
                    AND v_payment.identified_late_payment_charge_id IS NULL
                    AND (v_payment.identified_invoice_id IS NULL OR invoice.id=v_payment.identified_invoice_id)
                    AND ((v_payment.payment_scope_kind='NORMAL_CUSTOMER'
                            AND invoice.customer_id=v_payment.payer_customer_id)
                        OR (v_payment.payment_scope_kind='THIRD_PARTY_IDENTIFIED'
                            AND (v_payment.lease_id IS NULL OR invoice.lease_id=v_payment.lease_id)))
                ORDER BY invoice.due_date,invoice.issued_at,invoice.invoice_number COLLATE "C",invoice.id
            LOOP
                EXIT WHEN v_remaining=0;
                v_details:='[]'; v_total:=0; v_target:=NULL;
                FOR v_line IN SELECT line.*,app.invoice_line_outstanding(line.id) AS outstanding
                    FROM app.invoice_lines line WHERE line.invoice_id=v_invoice.id
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
                        'invoice_id',v_invoice.id,'target_customer_id',v_invoice.customer_id,
                        'due_date',v_invoice.due_date,'issued_at',v_invoice.issued_at,
                        'invoice_number',v_invoice.invoice_number,'version',v_invoice.version,
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
                'targets',v_targets,'policy','DUE_ISSUED_NUMBER_ID/RENT_SERVICE_SOURCE_ORDER',
                'payment_scope',v_payment.payment_scope_kind,
                'designation_reference',CASE WHEN v_payment.payment_scope_kind='THIRD_PARTY_IDENTIFIED'
                    OR v_payment.identified_invoice_id IS NOT NULL
                    THEN 'confirmed-payment:'||v_payment.id::text ELSE NULL END);
        END $$;

        CREATE FUNCTION app.payment_allocation_replay(
            p_property_id uuid,p_actor_id uuid,p_action text,p_key uuid,p_digest text,p_target_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_receipt app.payment_allocation_commands%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id,p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            IF p_action IS NULL OR p_action NOT IN ('POST','REVERSE_ALLOCATION','REVERSE_PAYMENT')
                OR p_key IS NULL OR p_key='00000000-0000-0000-0000-000000000000'
                OR p_target_id IS NULL OR p_digest IS NULL OR p_digest!~'^[0-9a-f]{64}$'
            THEN RAISE EXCEPTION 'Allocation command identity is invalid' USING ERRCODE='P4902'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('allocation-command:'||p_property_id::text
                ||':'||p_actor_id::text||':'||p_action||':'||p_key::text,0));
            SELECT * INTO v_receipt FROM app.payment_allocation_commands WHERE property_id=p_property_id
                AND actor_id=p_actor_id AND action=p_action AND idempotency_key=p_key;
            IF FOUND THEN
                IF v_receipt.request_digest<>p_digest OR v_receipt.target_id<>p_target_id
                THEN RAISE EXCEPTION 'Allocation idempotency key reused' USING ERRCODE='P4905'; END IF;
                RETURN v_receipt.response;
            END IF;
            RETURN NULL;
        END $$;

        CREATE FUNCTION app.audit_payment_allocation_event()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_header app.payment_allocations%ROWTYPE; v_payment app.payments%ROWTYPE;
        DECLARE v_actor uuid; v_at timestamptz; v_reason text; v_action text;
        BEGIN
            IF TG_TABLE_NAME='payment_allocations' THEN
                v_header:=NEW; v_actor:=NEW.posted_by; v_at:=NEW.posted_at;
                v_reason:='Explicitly confirmed allocation'; v_action:='payment_allocation.posted';
            ELSE
                SELECT * INTO STRICT v_header FROM app.payment_allocations WHERE id=NEW.payment_allocation_id;
                v_actor:=NEW.actor_id; v_at:=NEW.occurred_at; v_reason:=NEW.reason;
                v_action:='payment_allocation.reversed';
            END IF;
            SELECT * INTO STRICT v_payment FROM app.payments WHERE id=v_header.payment_id;
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,
                entity_type,entity_id,reason,authorization_reference,property_id,
                resulting_state,correlation_id,source,outcome,customer_id,lease_id)
            VALUES(gen_random_uuid(),v_at,(v_at AT TIME ZONE 'Asia/Phnom_Penh')::date,v_actor,v_action,
                'payment_allocation',v_header.id,v_reason,'payments.allocate',v_payment.property_id,
                jsonb_build_object('allocation_id',v_header.id,'payment_id',v_header.payment_id,
                    'invoice_id',v_header.invoice_id,'late_payment_charge_id',v_header.late_payment_charge_id,
                    'amount_usd_cents',v_header.amount_usd_cents,'event',v_action,
                    'proposal_batch_id',v_header.proposal_batch_id),NEW.id,'API','SUCCESS',
                v_header.target_customer_id,v_payment.lease_id);
            RETURN NULL;
        END $$;
        CREATE TRIGGER payment_allocations_audit AFTER INSERT ON app.payment_allocations
            FOR EACH ROW EXECUTE FUNCTION app.audit_payment_allocation_event();
        CREATE TRIGGER payment_allocation_reversals_audit AFTER INSERT ON app.payment_allocation_reversals
            FOR EACH ROW EXECUTE FUNCTION app.audit_payment_allocation_event();

        CREATE FUNCTION app.post_payment_allocations(
            p_property_id uuid,p_payment_id uuid,p_actor_id uuid,p_key uuid,p_digest text,p_intent jsonb
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_replay jsonb; v_payment app.payments%ROWTYPE; v_proposal jsonb;
        DECLARE v_target jsonb; v_detail jsonb; v_targets jsonb; v_result jsonb;
        DECLARE v_invoice uuid; v_charge uuid; v_customer uuid; v_id uuid; v_line app.invoice_lines%ROWTYPE;
        DECLARE v_generated boolean; v_batch uuid; v_generated_at timestamptz; v_reference text;
        DECLARE v_now timestamptz; v_between text; v_amount bigint; v_sequence integer;
        DECLARE v_ids jsonb:='[]';
        BEGIN
            v_replay:=app.payment_allocation_replay(p_property_id,p_actor_id,'POST',p_key,p_digest,p_payment_id);
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            PERFORM app.serialize_payment_state(p_payment_id);
            SELECT * INTO v_payment FROM app.payments WHERE id=p_payment_id FOR UPDATE;
            IF NOT FOUND OR v_payment.property_id<>p_property_id
            THEN RAISE EXCEPTION 'Payment not found' USING ERRCODE='P4901'; END IF;
            IF p_intent IS NULL OR jsonb_typeof(p_intent)<>'object'
                OR p_intent->>'mode' IS NULL OR p_intent->>'mode' NOT IN ('PROPOSAL','DESIGNATED','DIRECT_CHARGE')
            THEN RAISE EXCEPTION 'Allocation intent is invalid' USING ERRCODE='P4902'; END IF;
            v_generated:=p_intent->>'mode'='PROPOSAL';
            IF v_generated THEN
                v_proposal:=p_intent->'proposal';
                v_targets:=v_proposal->'targets';
                v_batch:=(v_proposal->>'proposal_batch_id')::uuid;
                v_generated_at:=(v_proposal->>'generated_at')::timestamptz;
                v_reference:=v_proposal->>'designation_reference';
            ELSIF p_intent->>'mode'='DIRECT_CHARGE' THEN
                IF NOT (p_intent ? 'late_payment_charge_id') OR NOT (p_intent ? 'amount_usd_cents')
                    OR p_intent-ARRAY['mode','late_payment_charge_id','amount_usd_cents']<>'{}'::jsonb
                THEN RAISE EXCEPTION 'Direct Charge intent is invalid' USING ERRCODE='P4902'; END IF;
                v_targets:=jsonb_build_array(jsonb_build_object(
                    'late_payment_charge_id',p_intent->'late_payment_charge_id',
                    'amount_usd_cents',p_intent->'amount_usd_cents'));
                v_reference:=CASE WHEN v_payment.payment_scope_kind='THIRD_PARTY_IDENTIFIED'
                    THEN 'confirmed-payment:'||v_payment.id::text ELSE NULL END;
            ELSE
                v_targets:=p_intent->'targets'; v_reference:=p_intent->>'designation_reference';
                IF v_reference IS NULL OR v_reference<>btrim(v_reference)
                    OR length(v_reference) NOT BETWEEN 1 AND 500
                THEN RAISE EXCEPTION 'Explicit designation reference is required' USING ERRCODE='P4902'; END IF;
            END IF;
            IF v_targets IS NULL OR jsonb_typeof(v_targets)<>'array'
                OR jsonb_array_length(v_targets) NOT BETWEEN 1 AND 100
            THEN RAISE EXCEPTION 'Allocation targets are invalid' USING ERRCODE='P4902'; END IF;
            -- Every target is locked in stable order before any value moves. Existing
            -- Charge corrections use Charge then Invoice, so Charge targets go first.
            FOR v_target IN SELECT value FROM jsonb_array_elements(v_targets)
                ORDER BY (value->>'late_payment_charge_id') IS NULL,
                    COALESCE(value->>'late_payment_charge_id',value->>'invoice_id')
            LOOP
                v_invoice:=(v_target->>'invoice_id')::uuid;
                v_charge:=(v_target->>'late_payment_charge_id')::uuid;
                IF (v_invoice IS NULL)=(v_charge IS NULL)
                THEN RAISE EXCEPTION 'Exactly one allocation target is required' USING ERRCODE='P4902'; END IF;
                PERFORM app.lock_payment_allocation_target(
                    CASE WHEN v_invoice IS NOT NULL THEN 'INVOICE' ELSE 'LATE_PAYMENT_CHARGE' END,
                    COALESCE(v_invoice,v_charge));
                PERFORM 1 FROM app.invoice_lines WHERE invoice_id=v_invoice ORDER BY id FOR UPDATE;
            END LOOP;
            IF v_generated AND v_proposal IS DISTINCT FROM app.payment_allocation_proposal(
                p_property_id,p_payment_id,v_generated_at,v_batch)
            THEN RAISE EXCEPTION 'Allocation proposal changed; obtain a fresh proposal' USING ERRCODE='P4904'; END IF;
            SET CONSTRAINTS ALL DEFERRED;
            FOR v_target IN SELECT value FROM jsonb_array_elements(v_targets)
            LOOP
                v_invoice:=(v_target->>'invoice_id')::uuid; v_charge:=(v_target->>'late_payment_charge_id')::uuid;
                v_id:=gen_random_uuid(); v_now:=clock_timestamp(); v_sequence:=0;
                v_between:=CASE WHEN v_payment.payment_scope_kind='THIRD_PARTY_IDENTIFIED'
                    THEN 'THIRD_PARTY_DESIGNATED' WHEN v_reference IS NOT NULL THEN 'CUSTOMER_DESIGNATED'
                    WHEN v_charge IS NOT NULL THEN 'DIRECT_LATE_PAYMENT_CHARGE' ELSE 'FIFO_PROPOSAL' END;
                IF v_invoice IS NOT NULL THEN
                    SELECT customer_id INTO v_customer FROM app.invoices WHERE id=v_invoice;
                ELSE SELECT customer_id INTO v_customer FROM app.late_payment_charges WHERE id=v_charge; END IF;
                IF v_customer IS NULL THEN RAISE EXCEPTION 'Allocation target not found' USING ERRCODE='P4901'; END IF;
                v_amount:=(v_target->>'amount_usd_cents')::bigint;
                INSERT INTO app.payment_allocations(id,payment_id,target_customer_id,
                    proposal_batch_id,between_invoice_sequence,target_kind,invoice_id,late_payment_charge_id,
                    amount_usd_cents,between_invoice_basis,within_invoice_basis,customer_designation_reference,
                    selected_invoice_due_date,selected_invoice_issued_at,selected_invoice_number_snapshot,
                    proposal_generated_at,proposal_trace,posted_at,posted_by,authorization_reference)
                VALUES(v_id,p_payment_id,v_customer,v_batch,
                    CASE WHEN v_generated THEN (v_target->>'sequence')::smallint END,
                    CASE WHEN v_invoice IS NOT NULL THEN 'INVOICE' ELSE 'LATE_PAYMENT_CHARGE' END,
                    v_invoice,v_charge,v_amount,v_between,
                    CASE WHEN v_charge IS NOT NULL THEN 'NOT_APPLICABLE'
                        WHEN v_generated THEN 'RENT_THEN_RECURRING_SERVICES_PROPOSAL' ELSE 'CUSTOMER_DESIGNATED' END,
                    v_reference,CASE WHEN v_generated THEN (v_target->>'due_date')::date END,
                    CASE WHEN v_generated THEN (v_target->>'issued_at')::timestamptz END,
                    CASE WHEN v_generated THEN v_target->>'invoice_number' END,
                    v_generated_at,CASE WHEN v_generated THEN v_proposal END,v_now,p_actor_id,'payments.allocate');
                IF v_charge IS NOT NULL THEN
                    INSERT INTO app.payment_allocation_details(id,payment_allocation_id,late_payment_charge_id,
                        obligation_kind,posted_amount_usd_cents,attribution_basis,detail_sequence,calculation_trace)
                    VALUES(gen_random_uuid(),v_id,v_charge,'LATE_PAYMENT_CHARGE',v_amount,
                        CASE WHEN v_payment.payment_scope_kind='THIRD_PARTY_IDENTIFIED'
                            THEN 'THIRD_PARTY_DESIGNATED' ELSE 'DIRECT_LATE_PAYMENT_CHARGE' END,1,
                        jsonb_build_object('designation_reference',v_reference));
                ELSE
                    IF jsonb_typeof(v_target->'details') IS DISTINCT FROM 'array'
                        OR jsonb_array_length(v_target->'details') NOT BETWEEN 1 AND 500
                    THEN RAISE EXCEPTION 'Invoice allocation details required' USING ERRCODE='P4902'; END IF;
                    FOR v_detail IN SELECT value FROM jsonb_array_elements(v_target->'details')
                    LOOP
                        v_sequence:=v_sequence+1;
                        SELECT * INTO STRICT v_line FROM app.invoice_lines
                            WHERE id=(v_detail->>'invoice_line_id')::uuid AND invoice_id=v_invoice FOR UPDATE;
                        INSERT INTO app.payment_allocation_details(id,payment_allocation_id,invoice_line_id,
                            obligation_kind,invoice_line_category_snapshot,proposed_amount_usd_cents,
                            posted_amount_usd_cents,attribution_basis,detail_sequence,calculation_trace)
                        VALUES(gen_random_uuid(),v_id,v_line.id,'INVOICE_LINE',v_line.category,
                            CASE WHEN v_generated THEN (v_detail->>'amount_usd_cents')::bigint END,
                            (v_detail->>'amount_usd_cents')::bigint,
                            CASE WHEN v_generated THEN v_detail->>'attribution_basis'
                                WHEN v_payment.payment_scope_kind='THIRD_PARTY_IDENTIFIED'
                                    THEN 'THIRD_PARTY_DESIGNATED' ELSE 'CUSTOMER_DESIGNATED' END,
                            v_sequence::smallint,jsonb_build_object('confirmed_detail',v_detail,
                                'designation_reference',v_reference));
                    END LOOP;
                    PERFORM app.refresh_allocated_invoice(v_invoice,p_actor_id,true);
                END IF;
                v_ids:=v_ids||jsonb_build_array(v_id);
            END LOOP;
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=jsonb_build_object('payment_id',p_payment_id,'allocation_ids',v_ids,
                'available_usd_cents',app.payment_available_value(p_payment_id));
            INSERT INTO app.payment_allocation_commands VALUES(p_property_id,p_actor_id,'POST',p_key,
                p_digest,p_payment_id,v_result,clock_timestamp());
            RETURN v_result;
        END $$;

        CREATE FUNCTION app.reverse_payment_allocation_command(
            p_property_id uuid,p_allocation_id uuid,p_actor_id uuid,p_key uuid,p_digest text,p_reason text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_replay jsonb; v_header app.payment_allocations%ROWTYPE; v_id uuid:=gen_random_uuid();
        DECLARE v_result jsonb;
        BEGIN
            v_replay:=app.payment_allocation_replay(p_property_id,p_actor_id,'REVERSE_ALLOCATION',
                p_key,p_digest,p_allocation_id);
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            SELECT allocation.* INTO v_header FROM app.payment_allocations allocation
                JOIN app.payments payment ON payment.id=allocation.payment_id
                WHERE allocation.id=p_allocation_id AND payment.property_id=p_property_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Allocation not found' USING ERRCODE='P4901'; END IF;
            INSERT INTO app.payment_allocation_reversals VALUES(v_id,p_allocation_id,p_reason,
                clock_timestamp(),p_actor_id,'payments.allocate');
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=jsonb_build_object('allocation_id',p_allocation_id,'reversal_id',v_id,
                'payment_id',v_header.payment_id,'available_usd_cents',app.payment_available_value(v_header.payment_id));
            INSERT INTO app.payment_allocation_commands VALUES(p_property_id,p_actor_id,'REVERSE_ALLOCATION',
                p_key,p_digest,p_allocation_id,v_result,clock_timestamp());
            RETURN v_result;
        END $$;
        CREATE FUNCTION app.reverse_payment_command(
            p_property_id uuid,p_payment_id uuid,p_actor_id uuid,p_key uuid,p_digest text,
            p_expected_status text,p_reason text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_replay jsonb; v_payment app.payments%ROWTYPE; v_id uuid:=gen_random_uuid(); v_result jsonb;
        BEGIN
            v_replay:=app.payment_allocation_replay(p_property_id,p_actor_id,'REVERSE_PAYMENT',
                p_key,p_digest,p_payment_id);
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            PERFORM app.serialize_payment_state(p_payment_id);
            SELECT * INTO v_payment FROM app.payments WHERE id=p_payment_id FOR UPDATE;
            IF NOT FOUND OR v_payment.property_id<>p_property_id
            THEN RAISE EXCEPTION 'Payment not found' USING ERRCODE='P4901'; END IF;
            IF p_expected_status IS DISTINCT FROM 'RECEIVED' OR v_payment.status<>p_expected_status
            THEN RAISE EXCEPTION 'Payment state changed' USING ERRCODE='P4904'; END IF;
            -- Separate authorized downstream commands must resolve dependencies;
            -- the existing authoritative reversal guard rejects any unresolved use.
            INSERT INTO app.payment_reversals VALUES(v_id,p_payment_id,p_reason,clock_timestamp(),
                p_actor_id,'payments.reverse');
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=jsonb_build_object('payment_id',p_payment_id,'reversal_id',v_id,'status','REVERSED');
            INSERT INTO app.payment_allocation_commands VALUES(p_property_id,p_actor_id,'REVERSE_PAYMENT',
                p_key,p_digest,p_payment_id,v_result,clock_timestamp());
            RETURN v_result;
        END $$;
    """)
    for signature in (
        "payment_allocation_replay(uuid,uuid,text,uuid,text,uuid)",
        "audit_payment_allocation_event()",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION app.{signature} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    for signature in (
        "post_payment_allocations(uuid,uuid,uuid,uuid,text,jsonb)",
        "reverse_payment_allocation_command(uuid,uuid,uuid,uuid,text,text)",
        "reverse_payment_command(uuid,uuid,uuid,uuid,text,text,text)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION app.{signature} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
        op.execute(f"GRANT EXECUTE ON FUNCTION app.{signature} TO prm_financial")
    op.execute(
        "REVOKE ALL ON FUNCTION app.payment_allocation_proposal(uuid,uuid,timestamptz,uuid) FROM PUBLIC,prm_bootstrap"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.payment_allocation_proposal(uuid,uuid,timestamptz,uuid) TO prm_runtime,prm_financial"
    )


def integrate_existing_financial_guards() -> None:
    """Extend existing constraints without discarding their pre-allocation protections."""
    replace_function(
        "app.protect_invoice_header_history()",
        [
            (
                "AND NOT (OLD.status='UNPAID' AND NEW.status='PAID' AND v_adjusted_total=0)\n"
                "                AND NOT (OLD.status='PAID' AND NEW.status='UNPAID' AND v_adjusted_total>0)",
                "AND NOT (OLD.status IN ('UNPAID','PARTIALLY_PAID','PAID')\n"
                "                    AND NEW.status=app.invoice_application_status(NEW.id))",
            ),
            (
                "Payment-dependent Invoice status transition is unavailable before Payment persistence",
                "Invoice status must match its authoritative application position",
            ),
        ],
    )
    replace_function(
        "app.invoice_resource_snapshot(uuid)",
        [
            (
                "ELSE app.invoice_adjusted_line_obligation(line.id) END)",
                "ELSE app.invoice_line_outstanding(line.id) END)",
            ),
            (
                "'active_application_total',jsonb_build_object('currency','USD','minor_units',0)",
                "'active_application_total',jsonb_build_object('currency','USD','minor_units',\n"
                "                    (SELECT COALESCE(sum(app.invoice_line_payment_value_at(id,'infinity')),0)\n"
                "                     FROM app.invoice_lines WHERE invoice_id=p_invoice_id))",
            ),
            (
                "THEN 0 ELSE v_adjusted END)",
                "THEN 0 ELSE (SELECT COALESCE(sum(app.invoice_line_outstanding(id)),0)\n"
                "                        FROM app.invoice_lines WHERE invoice_id=p_invoice_id) END)",
            ),
        ],
    )
    replace_function(
        "app.validate_invoice_adjustment_effect()",
        [
            ("('UNPAID','PAID')", "('UNPAID','PARTIALLY_PAID','PAID')"),
            ("app.invoice_adjusted_line_obligation_at(", "app.invoice_line_outstanding_at("),
            ("app.invoice_adjusted_line_obligation(id)", "app.invoice_line_outstanding(id)"),
            (
                "OR (v_invoice_obligation=0 AND v_status<>'PAID')\n"
                "                OR (v_invoice_obligation>0 AND v_status<>'UNPAID')",
                "OR v_status<>app.invoice_application_status(v_invoice_id)",
            ),
        ],
    )
    replace_function(
        "app.adjust_invoice(uuid,uuid,uuid,uuid,uuid,text,integer,text,bigint,text,text,uuid,uuid)",
        [
            ("('UNPAID','PAID')", "('UNPAID','PARTIALLY_PAID','PAID')"),
            (
                "SELECT min(resulting),sum(resulting)",
                "SELECT min(resulting-app.invoice_line_payment_value_at(id,'infinity')),sum(resulting)",
            ),
            (
                "status=CASE WHEN v_resulting=0 THEN 'PAID' ELSE 'UNPAID' END",
                "status=app.invoice_application_status(p_invoice_id)",
            ),
        ],
    )
    invoice_events = """
                UNION ALL SELECT allocation.posted_at FROM app.payment_allocations allocation
                    WHERE allocation.invoice_id=v_invoice_id
                UNION ALL SELECT reversal.occurred_at FROM app.payment_allocation_reversals reversal
                    JOIN app.payment_allocations allocation ON allocation.id=reversal.payment_allocation_id
                    WHERE allocation.invoice_id=v_invoice_id
    """
    replace_function(
        "app.serialize_invoice_adjustment_source()",
        [
            (
                "            ) AS financial_events;",
                invoice_events + "            ) AS financial_events;",
            )
        ],
    )
    replace_function(
        "app.validate_invoice_void_event()",
        [
            (
                "IF v_status<>'VOID'",
                """IF v_status<>'VOID'
                OR EXISTS(SELECT 1 FROM app.payment_allocations allocation
                    LEFT JOIN app.payment_allocation_reversals reversal
                        ON reversal.payment_allocation_id=allocation.id
                    WHERE allocation.invoice_id=NEW.invoice_id AND (
                        reversal.id IS NULL OR reversal.occurred_at>=NEW.occurred_at
                        OR allocation.posted_at>=NEW.occurred_at))""",
            )
        ],
    )
    replace_function(
        "app.validate_late_payment_decision()",
        [
            ("app.invoice_adjusted_line_obligation_at(", "app.invoice_line_outstanding_at("),
            ("v_invoice.status<>'UNPAID'", "v_invoice.status NOT IN ('UNPAID','PARTIALLY_PAID')"),
            (
                "OR NEW.assessed_at<v_invoice.issued_at",
                """OR NEW.assessed_at<v_invoice.issued_at
                OR EXISTS(SELECT 1 FROM app.payment_allocations allocation
                    LEFT JOIN app.payment_allocation_reversals reversal
                        ON reversal.payment_allocation_id=allocation.id
                    WHERE allocation.invoice_id=NEW.source_invoice_id AND (
                        allocation.posted_at BETWEEN NEW.assessed_at AND NEW.finalized_at
                        OR reversal.occurred_at BETWEEN NEW.assessed_at AND NEW.finalized_at))""",
            ),
        ],
    )
    for signature in (
        "app.late_payment_review_snapshot(uuid)",
        "app.finalize_late_payment_decision(uuid,uuid,uuid,uuid,text,text,text,bigint,text,uuid,uuid,uuid)",
    ):
        replace_function(
            signature,
            [
                (
                    "app.invoice_adjusted_line_obligation(line.id)",
                    "app.invoice_line_outstanding(line.id)",
                ),
                (
                    "v_invoice.status<>'UNPAID'",
                    "v_invoice.status NOT IN ('UNPAID','PARTIALLY_PAID')",
                ),
            ],
        )
    replace_function(
        "app.validate_late_charge_correction()",
        [
            (
                "OR v_current<0 OR v_current>v_original",
                """OR v_current<0 OR v_current>v_original
                OR v_current<COALESCE((app.late_payment_charge_application_summary(
                    NEW.late_payment_charge_id)->>'active_total_usd_cents')::bigint,0)""",
            )
        ],
    )
    replace_function(
        "app.serialize_late_charge_correction()",
        [
            (
                "OR NEW.occurred_at<=COALESCE(v_latest_at,'-infinity'::timestamptz)",
                """OR NEW.occurred_at<=COALESCE(v_latest_at,'-infinity'::timestamptz)
                OR EXISTS(SELECT 1 FROM app.payment_allocations allocation
                    LEFT JOIN app.payment_allocation_reversals reversal
                        ON reversal.payment_allocation_id=allocation.id
                    WHERE allocation.late_payment_charge_id=NEW.late_payment_charge_id
                        AND (allocation.posted_at>=NEW.occurred_at
                            OR reversal.occurred_at>=NEW.occurred_at))""",
            )
        ],
    )
    replace_function(
        "app.validate_payment_reversal()",
        [
            (
                "            ) dependency_events;",
                """
                UNION ALL SELECT allocation.posted_at FROM app.payment_allocations allocation
                    WHERE allocation.payment_id=NEW.payment_id
                UNION ALL SELECT reversal.occurred_at FROM app.payment_allocation_reversals reversal
                    JOIN app.payment_allocations allocation ON allocation.id=reversal.payment_allocation_id
                    WHERE allocation.payment_id=NEW.payment_id
            ) dependency_events;""",
            )
        ],
    )


def downgrade() -> None:
    raise RuntimeError("Allocation history is forward-only; use an approved forward migration")
