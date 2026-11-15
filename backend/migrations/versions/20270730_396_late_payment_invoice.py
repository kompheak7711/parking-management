"""The late-payment charge becomes an Invoice of the type Late-payment (L1, DL-233).

Owner (12 Nov 2026, DL-226, L1). Every amount a Customer owes is an Invoice. Before, the
late-payment charge was the one exception: a debt of its own kind with its own payment,
Credit, Deposit, correction and settlement code.

What changes (BR-LATE-001, BR-INV-016):

- The automatic pass writes the same decision as before. In the same step it now makes and
  issues an Invoice of the type Late-payment for the Customer and the Lease of the late
  Invoice, with one line. The Invoice is owed on the day it is made. No charge of the old kind
  is written any more.
- ``app.invoices.late_payment_decision_id`` names the decision. It is empty on every other
  Invoice, it never changes, and one decision has one Invoice. An Invoice has the type
  Late-payment if and only if it names its decision.
- The line of that Invoice has its source like every one-time charge: a row of
  ``app.authorized_nonrecurring_obligations``. For this one kind the row is written by the
  Property's billing service, not by a person, and names the decision.
- The type Late-payment is in use. Its late-payment switch is No and cannot be set to Yes, and
  the pass does not read such an Invoice: a Late-payment Invoice never gets a charge itself.
- The Invoice that was late cannot be made Void while its Late-payment Invoice stands, as
  with a charge before.
- The Invoice read names the Invoice that was late (``late_payment_of``), and the late-payment
  card of that Invoice names its Late-payment Invoice (``late_invoice``).
- The income report counts a Late-payment Invoice as late-payment income, and the General
  Ledger posts it to the late-payment income account (4050), as with a charge before. The debt
  itself is in the Invoice account (1100) like every Invoice.

A charge made before this migration stays as it was made, with its own payments and
corrections. No row is changed or deleted. This migration is forward-only.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule; the rule is the owner's.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270730_396"
down_revision: str | None = "20270729_395"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = r"""
ALTER TABLE app.invoices
    ADD COLUMN late_payment_decision_id uuid REFERENCES app.late_payment_decisions(id);
COMMENT ON COLUMN app.invoices.late_payment_decision_id IS
    'The late-payment decision this Late-payment Invoice was made from (L1, DL-233).';
CREATE UNIQUE INDEX invoices_late_payment_decision_key
    ON app.invoices (late_payment_decision_id) WHERE late_payment_decision_id IS NOT NULL;

ALTER TABLE app.authorized_nonrecurring_obligations
    ADD COLUMN late_payment_decision_id uuid REFERENCES app.late_payment_decisions(id),
    ADD COLUMN authorized_by_service uuid REFERENCES app.actor_identities(actor_id),
    ALTER COLUMN authorized_by DROP NOT NULL,
    ADD CONSTRAINT authorized_nonrecurring_late_payment_shape CHECK (
        (late_payment_decision_id IS NULL AND authorized_by IS NOT NULL
            AND authorized_by_service IS NULL)
        OR (late_payment_decision_id IS NOT NULL AND authorized_by IS NULL
            AND authorized_by_service IS NOT NULL AND category = 'MISCELLANEOUS_CHARGES'
            AND due_date_rule = 'GOVERNING_SOURCE'));
COMMENT ON COLUMN app.authorized_nonrecurring_obligations.late_payment_decision_id IS
    'Set only on the source of a Late-payment Invoice line: its decision (L1, DL-233).';
CREATE UNIQUE INDEX authorized_nonrecurring_late_payment_decision_key
    ON app.authorized_nonrecurring_obligations (late_payment_decision_id)
    WHERE late_payment_decision_id IS NOT NULL;

UPDATE app.invoice_types SET in_use = true, version = version + 1 WHERE code = 'LATE_PAYMENT';
"""

SOURCE = r"""
CREATE FUNCTION app.validate_late_payment_obligation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
BEGIN
    -- The source of a Late-payment Invoice line says what its decision says.
    IF NOT EXISTS (
        SELECT 1 FROM app.late_payment_decisions AS decision
        JOIN app.invoices AS late_invoice ON late_invoice.id = decision.source_invoice_id
        WHERE decision.id = NEW.late_payment_decision_id
          AND decision.authorization_reference = 'late_payment.automatic_charge'
          AND decision.finalized_by_service = NEW.authorized_by_service
          AND decision.customer_id = NEW.customer_id
          AND decision.approved_amount_usd_cents = NEW.authorized_amount_usd_cents
          AND decision.finalized_at = NEW.authorized_at
          AND late_invoice.lease_id IS NOT DISTINCT FROM NEW.lease_id
          AND NEW.source_reference = 'late_payment:' || late_invoice.id::text
    ) THEN
        RAISE EXCEPTION 'The Late-payment source does not fit its decision'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $function$;
REVOKE ALL ON FUNCTION app.validate_late_payment_obligation() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER authorized_nonrecurring_obligations_late_payment
    AFTER INSERT ON app.authorized_nonrecurring_obligations
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    WHEN (NEW.late_payment_decision_id IS NOT NULL)
    EXECUTE FUNCTION app.validate_late_payment_obligation();
"""

ACTOR = "app.enforce_active_human_financial_actor()"
ACTOR_SERVICE = (
    (
        "THEN (to_jsonb(NEW)->>'authorized_by')::uuid",
        "THEN COALESCE((to_jsonb(NEW)->>'authorized_by')::uuid,"
        "(to_jsonb(NEW)->>'authorized_by_service')::uuid)",
    ),
    (
        "(to_jsonb(NEW)->>'source_invoice_id')::uuid) END);",
        "(to_jsonb(NEW)->>'source_invoice_id')::uuid) "
        "WHEN TG_TABLE_NAME='authorized_nonrecurring_obligations' THEN ("
        "SELECT app.invoice_property_id(decision.source_invoice_id) "
        "FROM app.late_payment_decisions AS decision "
        "WHERE decision.id=(to_jsonb(NEW)->>'late_payment_decision_id')::uuid) END);",
    ),
)

KEEP = r"""
CREATE OR REPLACE FUNCTION app.keep_invoice_type() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
DECLARE v_missed_type text;
BEGIN
    IF NEW.missed_on_invoice_line_id IS NOT NULL THEN
        SELECT source.invoice_type INTO v_missed_type
        FROM app.invoice_lines AS line
        JOIN app.invoices AS source ON source.id = line.invoice_id
        WHERE line.id = NEW.missed_on_invoice_line_id;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF NEW.invoice_type IS DISTINCT FROM OLD.invoice_type THEN
            RAISE EXCEPTION 'The Invoice type is kept as it was made' USING ERRCODE = '55000';
        END IF;
        IF NEW.missed_on_invoice_line_id IS DISTINCT FROM OLD.missed_on_invoice_line_id THEN
            RAISE EXCEPTION 'The missed line is kept as it was made' USING ERRCODE = '55000';
        END IF;
        IF NEW.late_payment_decision_id IS DISTINCT FROM OLD.late_payment_decision_id THEN
            RAISE EXCEPTION 'The late-payment link is kept as it was made'
                USING ERRCODE = '55000';
        END IF;
        -- A Draft made from another charge may get another category. When it had the usual
        -- type of its category, it gets the usual type of the new one.
        IF NEW.primary_category IS DISTINCT FROM OLD.primary_category
            AND OLD.invoice_type
                = app.invoice_type_code(OLD.primary_category, OLD.rent_billing_kind)
        THEN
            NEW.invoice_type
                := app.invoice_type_code(NEW.primary_category, NEW.rent_billing_kind);
        END IF;
    ELSIF NEW.invoice_type IS NULL THEN
        NEW.invoice_type := CASE WHEN NEW.late_payment_decision_id IS NOT NULL
            THEN 'LATE_PAYMENT'
            ELSE coalesce(v_missed_type,
                app.invoice_type_code(NEW.primary_category, NEW.rent_billing_kind)) END;
    END IF;
    IF NEW.invoice_type IS NULL OR NOT (
        CASE WHEN NEW.late_payment_decision_id IS NOT NULL THEN
            -- L1 (DL-233): the Late-payment Invoice of one decision of the automatic pass.
            NEW.primary_category = 'MISCELLANEOUS_CHARGES'
            AND NEW.invoice_type = 'LATE_PAYMENT'
            AND NEW.missed_on_invoice_line_id IS NULL
        WHEN NEW.missed_on_invoice_line_id IS NOT NULL THEN
            -- D3 (DL-232): a missed amount is a one-time charge of the type of what was missed.
            NEW.primary_category = 'MISCELLANEOUS_CHARGES'
            AND NEW.invoice_type IS NOT DISTINCT FROM v_missed_type
            AND NEW.invoice_type <> 'LATE_PAYMENT'
        ELSE
            NEW.invoice_type = app.invoice_type_code(NEW.primary_category, NEW.rent_billing_kind)
            OR (NEW.primary_category = 'MISCELLANEOUS_CHARGES'
                AND NEW.invoice_type IN ('SHORT_STAY', 'PRODUCTS', 'DAMAGE'))
        END
    ) THEN
        RAISE EXCEPTION 'The Invoice type does not fit the Invoice category'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' AND NEW.late_payment_decision_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM app.late_payment_decisions AS decision
        JOIN app.invoices AS late_invoice ON late_invoice.id = decision.source_invoice_id
        WHERE decision.id = NEW.late_payment_decision_id
          AND decision.authorization_reference = 'late_payment.automatic_charge'
          AND decision.finalized_by_service = NEW.created_by
          AND decision.customer_id = NEW.customer_id
          AND decision.approved_amount_usd_cents = NEW.original_total_usd_cents
          AND late_invoice.lease_id IS NOT DISTINCT FROM NEW.lease_id
    ) THEN
        RAISE EXCEPTION 'The Late-payment Invoice does not fit its decision'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $function$;
"""

HEADER = "app.protect_invoice_header_history()"
HEADER_SERVICE = (
    (
        "AND identity.actor_id IN (NEW.created_by,NEW.updated_by)",
        "AND identity.actor_id IN (NEW.created_by,NEW.updated_by) "
        "AND NEW.late_payment_decision_id IS NULL",
    ),
    (
        "AND identity.actor_id IN (NEW.updated_by,NEW.issued_by)",
        "AND identity.actor_id IN (NEW.updated_by,NEW.issued_by) "
        "AND NEW.late_payment_decision_id IS NULL",
    ),
)

DECISION = "app.validate_automatic_late_payment_decision(uuid)"
DECISION_INVOICE = (
    (
        "OR NOT EXISTS(SELECT 1 FROM app.late_payment_charges charge",
        "OR NOT (EXISTS(SELECT 1 FROM app.invoices late "
        "WHERE late.late_payment_decision_id=v_decision.id "
        "AND late.customer_id=v_decision.customer_id "
        "AND late.lease_id IS NOT DISTINCT FROM v_invoice.lease_id "
        "AND late.invoice_type='LATE_PAYMENT' "
        "AND late.original_total_usd_cents=v_amount "
        "AND late.issued_at=v_decision.finalized_at "
        "AND late.issued_by=v_decision.finalized_by_service "
        "AND late.created_by=v_decision.finalized_by_service) "
        "OR EXISTS(SELECT 1 FROM app.late_payment_charges charge",
    ),
    (
        "AND charge.created_by_service=v_decision.finalized_by_service)",
        "AND charge.created_by_service=v_decision.finalized_by_service))",
    ),
)

TYPE_SWITCH = "app.set_invoice_type_late_payment(uuid,text,boolean,text,uuid,uuid)"
TYPE_SWITCH_FIXED = (
    (
        "IF v_type.late_payment = p_late_payment THEN",
        "IF p_code = 'LATE_PAYMENT' AND p_late_payment THEN "
        "RAISE EXCEPTION 'A Late-payment Invoice never gets a late-payment charge' "
        "USING ERRCODE = '55000'; END IF; "
        "IF v_type.late_payment = p_late_payment THEN",
    ),
)

# The charge only goes down (BR-LATE-001): a credit Adjustment lowers a Late-payment Invoice,
# a debit Adjustment is refused, whoever writes it.
RAISED = "app.validate_invoice_adjustment_effect()"
RAISED_NEVER = (
    (
        "v_line_id:=NEW.invoice_line_id;",
        "v_line_id:=NEW.invoice_line_id; "
        "IF NEW.adjustment_type='DEBIT' AND EXISTS (SELECT 1 FROM app.invoices AS late "
        "WHERE late.id=NEW.invoice_id AND late.late_payment_decision_id IS NOT NULL) THEN "
        "RAISE EXCEPTION 'A Late-payment Invoice is never raised' "
        "USING ERRCODE='23514'; END IF;",
    ),
)

CANDIDATES = (
    "app.automatic_late_payment_charge_candidates(uuid,uuid,timestamp with time zone,uuid,integer)"
)
CANDIDATES_NOT_LATE = (
    (
        "AND invoice.status NOT IN ('DRAFT','VOID')",
        "AND invoice.status NOT IN ('DRAFT','VOID') AND invoice.late_payment_decision_id IS NULL",
    ),
)

SNAPSHOT = "app.invoice_resource_snapshot(uuid)"
SNAPSHOT_LATE = (
    (
        "'invoice_type',app.invoice_type_of(v_invoice.id),",
        "'invoice_type',app.invoice_type_of(v_invoice.id),"
        "'late_payment_of',(SELECT jsonb_build_object('invoice_id',late_invoice.id,"
        "'invoice_number',late_invoice.invoice_number) "
        "FROM app.late_payment_decisions AS decision "
        "JOIN app.invoices AS late_invoice ON late_invoice.id=decision.source_invoice_id "
        "WHERE decision.id=v_invoice.late_payment_decision_id),",
    ),
)

VOID = "app.void_invoice(uuid,uuid,uuid,uuid,text,integer,text,uuid,uuid)"
VOID_LATE = (
    (
        "OR EXISTS (SELECT 1 FROM app.late_payment_charges AS charge",
        "OR EXISTS (SELECT 1 FROM app.invoices AS late "
        "JOIN app.late_payment_decisions AS decision "
        "ON decision.id=late.late_payment_decision_id "
        "WHERE decision.source_invoice_id=p_invoice_id AND late.status<>'VOID') "
        "OR EXISTS (SELECT 1 FROM app.late_payment_charges AS charge",
    ),
)

CARD_OF_INVOICE = r"""
CREATE FUNCTION app.late_payment_invoice_card(p_invoice_id uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog AS $function$
    -- The late-payment card of an Invoice whose charge is a Late-payment Invoice (L1).
    SELECT jsonb_build_object(
        'charge_id',NULL,
        'late_invoice',jsonb_build_object('invoice_id',late.id,
            'invoice_number',late.invoice_number,'status',late.status),
        'invoice_id',decision.source_invoice_id,
        'customer_id',late.customer_id,
        'payable_at',late.issued_at,
        'charged_at',decision.assessed_at,
        'decision_outcome',decision.decision_outcome,
        'calculated_default_usd_cents',decision.calculated_default_amount_usd_cents,
        'added_at',late.created_at,
        'by_app',true,
        'added_by',NULL,
        'unpaid_at_charge_usd_cents',decision.overdue_balance_at_assessment_usd_cents,
        'rate_basis_points',decision.default_rate_basis_points,
        'original_usd_cents',late.original_total_usd_cents,
        'now_usd_cents',amounts.now_cents,
        'still_owed_usd_cents',amounts.owed_cents,
        'paid_usd_cents',GREATEST(amounts.now_cents-amounts.owed_cents,0),
        'changes','[]'::jsonb,
        'paid_by','[]'::jsonb)
    FROM app.late_payment_decisions AS decision
    JOIN app.invoices AS late ON late.late_payment_decision_id=decision.id
    CROSS JOIN LATERAL (
        SELECT CASE WHEN late.status='VOID' THEN 0 ELSE COALESCE(
                sum(app.invoice_adjusted_line_obligation(line.id)),0)::bigint END AS now_cents,
            CASE WHEN late.status='VOID' THEN 0 ELSE COALESCE(
                sum(GREATEST(app.invoice_line_outstanding(line.id),0)),0)::bigint END
                AS owed_cents
        FROM app.invoice_lines AS line WHERE line.invoice_id=late.id) AS amounts
    WHERE decision.source_invoice_id=p_invoice_id
$function$;
REVOKE ALL ON FUNCTION app.late_payment_invoice_card(uuid) FROM PUBLIC;
"""

CARD = "app.invoice_late_charge_card(uuid,uuid,uuid)"
CARD_LATE = (
    (
        "RETURN (SELECT jsonb_build_object(",
        "IF EXISTS(SELECT 1 FROM app.late_payment_decisions AS decision "
        "JOIN app.invoices AS late ON late.late_payment_decision_id=decision.id "
        "WHERE decision.source_invoice_id=p_invoice_id) THEN "
        "RETURN app.late_payment_invoice_card(p_invoice_id); END IF; "
        "RETURN (SELECT jsonb_build_object(",
    ),
)

INCOME = "app.report_income_facts(uuid,uuid,uuid[])"
INCOME_LATE = (
    (
        "i.primary_category, i.missed_on_invoice_line_id,",
        "i.primary_category, i.missed_on_invoice_line_id, i.late_payment_decision_id,",
    ),
    (
        "CASE WHEN EXISTS(SELECT 1 FROM app.quotation_lines quoted",
        "CASE WHEN invoice.late_payment_decision_id IS NOT NULL THEN 'LATE_PAYMENT_CHARGES' "
        "WHEN EXISTS(SELECT 1 FROM app.quotation_lines quoted",
    ),
)

LEDGER = "app.gl_app_record_events(uuid,date,date)"
LEDGER_LATE = (
    (
        "coalesce(stay.code, missed_stay.code, CASE missed.category",
        "coalesce(CASE WHEN i.late_payment_decision_id IS NOT NULL THEN '4050' END, "
        "stay.code, missed_stay.code, CASE missed.category",
    ),
)

VOID_EVENT = "app.validate_invoice_void_event()"
VOID_EVENT_LATE = (
    (
        "THEN RAISE EXCEPTION 'Invoice VOID dependencies are not resolved'",
        "OR EXISTS (SELECT 1 FROM app.invoices AS late "
        "JOIN app.late_payment_decisions AS decision "
        "ON decision.id=late.late_payment_decision_id "
        "WHERE decision.source_invoice_id=NEW.invoice_id AND late.status<>'VOID') "
        "THEN RAISE EXCEPTION 'Invoice VOID dependencies are not resolved'",
    ),
)

RECORD = r"""
CREATE OR REPLACE FUNCTION app.record_automatic_late_payment_charge(
    p_property_id uuid, p_actor_id uuid, p_invoice_id uuid, p_decision_id uuid,
    p_charge_id uuid, p_audit_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $function$
DECLARE v_timezone text; v_invoice app.invoices%ROWTYPE; v_lease_status text;
DECLARE v_now timestamptz; v_moment timestamptz; v_balance bigint; v_rate smallint;
DECLARE v_amount bigint; v_closed timestamptz; v_result jsonb; v_draft jsonb;
DECLARE v_day date; v_text text; v_obligation uuid := gen_random_uuid();
DECLARE v_evidence jsonb;
BEGIN
    v_timezone:=app.require_late_payment_charge_job(p_property_id,p_actor_id);
    IF p_decision_id IS NULL OR p_decision_id='00000000-0000-0000-0000-000000000000'::uuid
        OR p_charge_id IS NULL OR p_charge_id='00000000-0000-0000-0000-000000000000'::uuid
        OR p_audit_id IS NULL OR p_audit_id='00000000-0000-0000-0000-000000000000'::uuid
    THEN RAISE EXCEPTION 'Late-payment record identity is invalid' USING ERRCODE='22023';
    END IF;
    SELECT * INTO v_invoice FROM app.invoices WHERE id=p_invoice_id FOR UPDATE;
    IF NOT FOUND OR app.invoice_property_id(p_invoice_id) IS DISTINCT FROM p_property_id
    THEN RAISE EXCEPTION 'Late-payment Invoice was not found' USING ERRCODE='P4601';
    END IF;
    IF EXISTS(SELECT 1 FROM app.late_payment_decisions WHERE source_invoice_id=p_invoice_id)
    THEN RETURN jsonb_build_object('outcome','ALREADY_ASSESSED'); END IF;
    -- L1 (DL-233): a Late-payment Invoice never gets a late-payment charge itself.
    IF v_invoice.late_payment_decision_id IS NOT NULL THEN
        RETURN jsonb_build_object('outcome','LATE_PAYMENT_OFF'); END IF;
    v_now:=clock_timestamp();
    v_moment:=app.late_payment_charge_moment(v_invoice.due_date,v_timezone);
    IF v_now<app.late_payment_settled_after(v_moment) THEN
        RETURN jsonb_build_object('outcome','NOT_YET_DUE'); END IF;
    IF v_invoice.lease_id IS NULL THEN
        RETURN jsonb_build_object('outcome','NO_LEASE'); END IF;
    SELECT status INTO v_lease_status FROM app.leases WHERE id=v_invoice.lease_id;
    IF v_lease_status IS NULL OR v_lease_status NOT IN ('SIGNED','TERMINATED') THEN
        RETURN jsonb_build_object('outcome','LEASE_NOT_SIGNED_OR_TERMINATED'); END IF;
    -- V1.1 (owner 01/11/2026): the Invoice type says whether a late charge is added.
    IF NOT app.invoice_type_late_payment(v_invoice.id) THEN
        RETURN jsonb_build_object('outcome','LATE_PAYMENT_OFF'); END IF;
    IF v_invoice.status NOT IN ('UNPAID','PARTIALLY_PAID','PAID') THEN
        RETURN jsonb_build_object('outcome','NOT_ISSUED_OR_VOID'); END IF;
    -- The window is checked here too, so no caller charges a day the pass may not cover.
    IF v_invoice.due_date+1
        <app.late_payment_first_charge_day(p_property_id,v_now,v_timezone) THEN
        RETURN jsonb_build_object('outcome','NOT_IN_WINDOW'); END IF;
    IF v_invoice.issued_at>v_moment THEN
        RETURN jsonb_build_object('outcome','ISSUED_AFTER_CHARGE_TIME'); END IF;
    SELECT settlement.closed_at INTO v_closed FROM app.final_settlements settlement
    WHERE settlement.lease_id=v_invoice.lease_id FOR SHARE;
    IF v_closed IS NOT NULL THEN
        RETURN jsonb_build_object('outcome','FINAL_SETTLEMENT_CLOSED'); END IF;
    SELECT COALESCE(sum(app.invoice_line_outstanding_at(line.id,v_moment)),0)
    INTO v_balance FROM app.invoice_lines line WHERE line.invoice_id=p_invoice_id;
    v_rate:=app.late_payment_rate_basis_points(p_property_id,v_invoice.due_date+1);
    v_amount:=CASE WHEN v_balance>0 THEN app.late_payment_amount(v_rate,v_balance)
        ELSE 0 END;
    IF v_amount<=0 THEN RETURN jsonb_build_object('outcome','NO_AMOUNT'); END IF;
    INSERT INTO app.late_payment_decisions(
        id,source_invoice_id,customer_id,source_due_date,
        overdue_balance_at_assessment_usd_cents,default_rate_basis_points,
        calculated_default_amount_usd_cents,decision_outcome,
        approved_amount_usd_cents,assessed_at,finalized_at,finalized_by_service,reason,
        authorization_reference,calculation_trace)
    VALUES (p_decision_id,p_invoice_id,v_invoice.customer_id,v_invoice.due_date,
        v_balance,v_rate,v_amount,'CONFIRMED_DEFAULT',v_amount,v_moment,v_now,p_actor_id,
        'Automatic late-payment charge (DL-076)','late_payment.automatic_charge',
        jsonb_build_object(
            'formula','unpaid_balance_at_charge_moment_x_settings_rate',
            'rule','DL-076','source_invoice_id',p_invoice_id,
            'source_due_date',v_invoice.due_date,'charge_moment',v_moment,
            'overdue_balance_usd_cents',v_balance,'rate_basis_points',v_rate,
            'rounding','HALF_UP_TO_USD_CENT','calculated_amount_usd_cents',v_amount,
            'property_timezone',v_timezone,'charge_date',v_invoice.due_date+1));
    -- L1 (DL-233): the charge is an Invoice of the type Late-payment, owed on the day it is
    -- made. Its line has its source like every one-time charge.
    v_day:=timezone(v_timezone,v_now)::date;
    v_text:='Late-payment charge of Invoice ' || v_invoice.invoice_number;
    v_evidence:=jsonb_build_object('principal_capability','billing.generate','rule','DL-233',
        'late_payment_decision_id',p_decision_id,'source_invoice_id',p_invoice_id,
        'amount_usd_cents',v_amount,'rate_basis_points',v_rate);
    INSERT INTO app.authorized_nonrecurring_obligations(id,customer_id,lease_id,category,
        description,authorized_amount_usd_cents,governing_due_date,due_date_source,
        source_reference,authorized_at,authorized_by,authorized_by_service,
        authorization_reference,due_date_rule,late_payment_decision_id)
    VALUES (v_obligation,v_invoice.customer_id,v_invoice.lease_id,'MISCELLANEOUS_CHARGES',
        v_text,v_amount,v_day,'BR-LATE-001','late_payment:' || p_invoice_id::text,v_now,NULL,
        p_actor_id,'late_payment.automatic_charge','GOVERNING_SOURCE',p_decision_id);
    INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,primary_category,status,
        invoice_date,due_date,original_total_usd_cents,due_date_rule,due_date_source,
        created_at,created_by,updated_at,updated_by,late_payment_decision_id)
    VALUES (p_charge_id,'INV-' || to_char(v_day,'YYYYMMDD') || '-'
            || upper(substr(replace(p_charge_id::text,'-',''),1,12)),
        v_invoice.customer_id,v_invoice.lease_id,'MISCELLANEOUS_CHARGES','DRAFT',v_day,v_day,
        v_amount,'GOVERNING_SOURCE','BR-LATE-001',v_now,p_actor_id,v_now,p_actor_id,
        p_decision_id);
    INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,
        amount_usd_cents,authorized_obligation_id,calculation_trace,created_at,
        last_changed_at,created_by,last_changed_by)
    VALUES (gen_random_uuid(),p_charge_id,1,'MISCELLANEOUS_CHARGES',v_text,v_amount,
        v_obligation,jsonb_build_object(
            'formula','unpaid_balance_at_charge_moment_x_settings_rate',
            'late_payment_decision_id',p_decision_id,'source_invoice_id',p_invoice_id,
            'overdue_balance_usd_cents',v_balance,'rate_basis_points',v_rate,
            'authorized_obligation_id',v_obligation,'authorized_amount_usd_cents',v_amount),
        v_now,v_now,p_actor_id,p_actor_id);
    v_draft:=app.invoice_resource_snapshot(p_charge_id);
    INSERT INTO app.audit_events(
        id,occurred_at,business_date,actor_id,action,entity_type,entity_id,reason,
        authorization_reference,property_id,previous_state,resulting_state,
        correlation_id,source,outcome,authorization_evidence,customer_id,lease_id)
    VALUES (gen_random_uuid(),v_now,v_day,p_actor_id,'invoice.created','invoice',p_charge_id,
        'Automatic late-payment charge (DL-076)','late_payment.automatic_charge',
        p_property_id,'{}'::jsonb,v_draft,p_decision_id,'SCHEDULED','SUCCEEDED',v_evidence,
        v_invoice.customer_id,v_invoice.lease_id);
    UPDATE app.invoices SET status='UNPAID',issued_at=v_now,issued_by=p_actor_id,
        version=version+1,updated_at=v_now,updated_by=p_actor_id
    WHERE id=p_charge_id;
    SET CONSTRAINTS ALL IMMEDIATE;
    v_result:=app.invoice_resource_snapshot(p_charge_id);
    INSERT INTO app.audit_events(
        id,occurred_at,business_date,actor_id,action,entity_type,entity_id,reason,
        authorization_reference,property_id,previous_state,resulting_state,
        correlation_id,source,outcome,authorization_evidence,linked_source_event_id,
        customer_id,lease_id)
    VALUES (p_audit_id,v_now,v_day,p_actor_id,'invoice.issued','invoice',p_charge_id,
        'Automatic late-payment charge (DL-076)','late_payment.automatic_charge',
        p_property_id,v_draft,v_result,p_decision_id,'SCHEDULED','SUCCEEDED',v_evidence,
        p_charge_id,v_invoice.customer_id,v_invoice.lease_id);
    RETURN jsonb_build_object('outcome','CHARGED','invoice',v_result);
END $function$;
"""


def _definition(signature: str) -> str:
    return str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )


def _changed(signature: str, replacements: tuple[tuple[str, str], ...]) -> str:
    definition = _definition(signature)
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Late-payment source contract changed: {signature}: {before}")
        definition = definition.replace(before, after)
    return definition


def _run(sql: str) -> None:
    op.execute(text(sql.replace(":", "\\:")))


def upgrade() -> None:
    _run(COLUMNS)
    _run(SOURCE)
    _run(_changed(ACTOR, ACTOR_SERVICE))
    _run(KEEP)
    _run(_changed(HEADER, HEADER_SERVICE))
    _run(_changed(DECISION, DECISION_INVOICE))
    _run(_changed(TYPE_SWITCH, TYPE_SWITCH_FIXED))
    _run(_changed(RAISED, RAISED_NEVER))
    _run(_changed(CANDIDATES, CANDIDATES_NOT_LATE))
    _run(_changed(SNAPSHOT, SNAPSHOT_LATE))
    _run(_changed(VOID, VOID_LATE))
    _run(_changed(VOID_EVENT, VOID_EVENT_LATE))
    _run(RECORD)
    _run(CARD_OF_INVOICE)
    _run(_changed(CARD, CARD_LATE))
    _run(_changed(INCOME, INCOME_LATE))
    _run(_changed(LEDGER, LEDGER_LATE))


def downgrade() -> None:
    raise RuntimeError("the Late-payment Invoice migration is forward-only")
