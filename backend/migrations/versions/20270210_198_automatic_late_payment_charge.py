"""The automatic late-payment charge (V1-056 slice 11g-1; DL-076 answers 1 to 3).

At 00:00 Property time on the first day after an Invoice's Due Date, if any of it is unpaid, the
app adds one late-payment charge by itself: the Settings rate (DL-075; 10 percent until the
Settings rate is built) of the amount unpaid at that moment, rounded half-up to the cent. The
billing worker runs the pass with its Property's `billing.generate` service principal; no Manager
decision is needed. Every change to an existing object only accepts more rows:

1. `late_payment_decisions.default_rate_basis_points` takes a whole percent from 0 to 10 instead
   of exactly 10 percent (DB-INV-007, DL-075 answer 1).
2. A decision or a charge names its person (`finalized_by`, `created_by`, still a human account)
   or, new, its service (`finalized_by_service`, `created_by_service`, an actor identity): exactly
   one of the two. The person columns become nullable instead of moving their foreign keys, so
   this migration takes no lock on `app.user_accounts` (a whole-chain upgrade that holds the
   V1-042 validation gate cannot deadlock with a waiting writer; see 20270118_175).
3. The active-actor trigger reads the service column when the person column is empty and passes
   the Invoice's Property for a decision or a charge, so a Property's billing service principal
   is an accepted actor there.
4. The decision check: a row marked `late_payment.automatic_charge` is checked by the new rule
   of the automatic charge; any other row keeps today's check, at 10 percent, by a person. The
   charge check: a charge is made by the same actor as its decision.
5. The decision and charge snapshots and the charge position view show the service as the
   actor when there is no person.

New: the rate seam `app.late_payment_rate_basis_points`, the run table (one row per Property
and business day, so a day is done once and a missed day is caught up), the window, candidate,
record and run functions for prm_financial. Readings recorded under DL-076 and the owner card of
2026-10-25: an Invoice already late when the job first runs gets no charge (the window starts at
the first run day, and the record function and the decision check enforce it too); an Invoice
issued after its charge moment gets none; a closed Final Settlement's Invoice gets none
(BR-SETTLE-012); a zero amount writes nothing.
"""

from alembic import op
from sqlalchemy import text

revision = "20270210_198"
down_revision = "20270209_197"
branch_labels = None
depends_on = None

AUTOMATIC = "late_payment.automatic_charge"
REASON = "Automatic late-payment charge (DL-076)"

SQL = f"""
    -- DL-075 answer 1: the Settings rate is a whole percent from 0 to 10, default 10. The
    -- Settings screen comes with the screen rebuild; until then every Property uses 10 percent.
    -- The Settings build replaces this one function (CREATE OR REPLACE).
    CREATE FUNCTION app.late_payment_rate_basis_points(p_property_id uuid, p_charge_date date)
    RETURNS smallint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT 1000::smallint
    $$;

    -- The charge moment of a Due Date: 00:00 Property time on the next day.
    CREATE FUNCTION app.late_payment_charge_moment(p_due_date date, p_timezone text)
    RETURNS timestamptz LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
        SELECT (p_due_date+1)::timestamp AT TIME ZONE p_timezone
    $$;

    -- The balance unpaid at the charge moment and the rounded charge (BR-MONEY-012).
    CREATE FUNCTION app.late_payment_amount(p_rate smallint, p_balance bigint)
    RETURNS bigint LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
        SELECT floor((p_balance::numeric*p_rate+5000)/10000)::bigint
    $$;

    -- The amount unpaid at the charge moment cannot change once the charge is written: the pass
    -- holds the Invoice row, and a later allocation, Adjustment or reversal of the Invoice must be
    -- dated after the decision's finalized_at (app.allocation_target_latest_at), so one dated
    -- before midnight that is still being written is refused, not lost. The pass waits 10
    -- seconds after 00:00 so that such a payment, posted just before midnight, is counted.
    CREATE FUNCTION app.late_payment_settled_after(p_moment timestamptz)
    RETURNS timestamptz LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
        SELECT p_moment+interval '10 seconds'
    $$;

    CREATE FUNCTION app.validate_automatic_late_payment_decision(p_decision_id uuid)
    RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_decision app.late_payment_decisions%ROWTYPE;
        DECLARE v_invoice app.invoices%ROWTYPE; v_property uuid; v_timezone text;
        DECLARE v_moment timestamptz; v_balance bigint; v_rate smallint; v_amount bigint;
        BEGIN
            SELECT * INTO STRICT v_decision FROM app.late_payment_decisions WHERE id=p_decision_id;
            SELECT * INTO STRICT v_invoice FROM app.invoices
            WHERE id=v_decision.source_invoice_id FOR UPDATE;
            v_property:=app.invoice_property_id(v_invoice.id);
            SELECT timezone_name INTO v_timezone FROM app.properties WHERE id=v_property;
            v_moment:=app.late_payment_charge_moment(v_invoice.due_date,v_timezone);
            SELECT COALESCE(sum(app.invoice_line_outstanding_at(line.id,v_moment)),0)
            INTO v_balance FROM app.invoice_lines line WHERE line.invoice_id=v_invoice.id;
            v_rate:=app.late_payment_rate_basis_points(v_property,v_invoice.due_date+1);
            v_amount:=app.late_payment_amount(v_rate,v_balance);
            IF v_property IS NULL OR v_timezone IS NULL
                OR NOT EXISTS(SELECT 1 FROM app.billing_service_principals principal
                    WHERE principal.actor_id=v_decision.finalized_by_service
                      AND principal.property_id=v_property
                      AND principal.capability='billing.generate'
                      AND principal.lifecycle_state='active')
                OR v_decision.finalized_by IS NOT NULL
                OR v_decision.decision_outcome<>'CONFIRMED_DEFAULT'
                OR v_decision.reason<>'{REASON}'
                OR v_decision.customer_id<>v_invoice.customer_id
                OR v_decision.source_due_date<>v_invoice.due_date
                OR v_invoice.lease_id IS NULL
                OR NOT EXISTS(SELECT 1 FROM app.leases lease WHERE lease.id=v_invoice.lease_id
                    AND lease.status IN ('SIGNED','TERMINATED'))
                OR v_invoice.status NOT IN ('UNPAID','PARTIALLY_PAID','PAID')
                OR v_invoice.rent_billing_kind IS NOT DISTINCT FROM 'INITIAL'
                OR v_invoice.issued_at IS NULL OR v_invoice.issued_at>v_moment
                OR v_decision.assessed_at<>v_moment
                OR v_decision.finalized_at<app.late_payment_settled_after(v_moment)
                OR v_invoice.due_date+1<app.late_payment_first_charge_day(
                    v_property,v_decision.finalized_at,v_timezone)
                OR v_balance<=0 OR v_balance<>v_decision.overdue_balance_at_assessment_usd_cents
                OR v_decision.default_rate_basis_points<>v_rate
                OR v_amount<=0 OR v_amount<>v_decision.calculated_default_amount_usd_cents
                OR v_decision.approved_amount_usd_cents<>v_amount
                OR NOT EXISTS(SELECT 1 FROM app.late_payment_charges charge
                    WHERE charge.late_payment_decision_id=v_decision.id
                      AND charge.source_invoice_id=v_invoice.id
                      AND charge.customer_id=v_decision.customer_id
                      AND charge.original_amount_usd_cents=v_amount
                      AND charge.payable_at=v_decision.finalized_at
                      AND charge.created_by IS NULL
                      AND charge.created_by_service=v_decision.finalized_by_service)
            THEN RAISE EXCEPTION 'Automatic late-payment charge is invalid' USING ERRCODE='23514';
            END IF;
        END $$;

    -- One row per Property and business day: the day's pass is done once.
    -- (The table is created before the functions below that read it.)
    CREATE TABLE app.late_payment_charge_runs (
        property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
        business_date date NOT NULL,
        system_actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id)
            ON DELETE RESTRICT,
        recorded_at timestamptz NOT NULL,
        charged_count integer NOT NULL CHECK (charged_count>=0),
        no_amount_count integer NOT NULL CHECK (no_amount_count>=0),
        skipped_count integer NOT NULL CHECK (skipped_count>=0),
        PRIMARY KEY (property_id,business_date)
    );
    CREATE TRIGGER late_payment_charge_runs_append_only BEFORE UPDATE OR DELETE
        ON app.late_payment_charge_runs FOR EACH ROW
        EXECUTE FUNCTION app.reject_invoice_append_only_mutation();
    CREATE TRIGGER late_payment_charge_runs_reject_truncate BEFORE TRUNCATE
        ON app.late_payment_charge_runs FOR EACH STATEMENT
        EXECUTE FUNCTION app.reject_invoice_storage_truncate();

    -- The first charge day a pass may still cover (owner card of 2026-10-25, "No charge"): the
    -- day after the last finished pass, or the business day itself before the first pass, so an
    -- Invoice already late on the first day gets no charge.
    CREATE FUNCTION app.late_payment_first_charge_day(
        p_property_id uuid, p_at timestamptz, p_timezone text)
    RETURNS date LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE(max(run.business_date)+1,timezone(p_timezone,p_at)::date)
        FROM app.late_payment_charge_runs run WHERE run.property_id=p_property_id
    $$;

    -- The Property's billing service principal, and no one else, runs the pass.
    CREATE FUNCTION app.require_late_payment_charge_job(p_property_id uuid, p_actor_id uuid)
    RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_timezone text;
        BEGIN
            SELECT timezone_name INTO v_timezone FROM app.properties WHERE id=p_property_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Late-payment Property was not found'
                USING ERRCODE='P4601'; END IF;
            PERFORM 1 FROM app.billing_service_principals principal
            WHERE principal.actor_id=p_actor_id AND principal.property_id=p_property_id
              AND principal.capability='billing.generate' AND principal.lifecycle_state='active'
            FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'The automatic late-payment charge needs the Property''s billing service'
                    USING ERRCODE='42501'; END IF;
            RETURN v_timezone;
        END $$;

    -- The day's window: the business day of the instant (an instant later than the database
    -- clock counts as now), the first charge day it covers (the day after the last run, or the
    -- day itself before any run), whether the day's charge moment has settled and whether the
    -- day is already done.
    CREATE FUNCTION app.automatic_late_payment_charge_window(
        p_property_id uuid, p_actor_id uuid, p_as_of timestamptz)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_timezone text; v_day date; v_last date; v_as_of timestamptz;
        BEGIN
            v_timezone:=app.require_late_payment_charge_job(p_property_id,p_actor_id);
            -- An instant older than an hour would let a pass mark past days done or start the
            -- window in the past (review round 1, security).
            IF p_as_of IS NULL OR p_as_of<clock_timestamp()-interval '1 hour' THEN
                RAISE EXCEPTION 'The late-payment pass instant is invalid' USING ERRCODE='22023';
            END IF;
            v_as_of:=least(p_as_of,clock_timestamp());
            v_day:=timezone(v_timezone,v_as_of)::date;
            SELECT max(run.business_date) INTO v_last FROM app.late_payment_charge_runs run
            WHERE run.property_id=p_property_id;
            RETURN jsonb_build_object(
                'business_date',v_day,
                'from_date',app.late_payment_first_charge_day(p_property_id,v_as_of,v_timezone),
                'ready',v_as_of>=app.late_payment_settled_after(
                    app.late_payment_charge_moment(v_day-1,v_timezone)),
                'done',v_last IS NOT NULL AND v_last>=v_day);
        END $$;

    -- The Invoices the day's pass looks at: of the Property, with a Lease, issued, no decision,
    -- and a charge day in the window, by id after p_after (an Invoice with no charge stays a
    -- candidate, so the pass pages on). The record function checks each one again.
    CREATE FUNCTION app.automatic_late_payment_charge_candidates(
        p_property_id uuid, p_actor_id uuid, p_as_of timestamptz, p_after uuid, p_limit integer)
    RETURNS TABLE(invoice_id uuid) LANGUAGE plpgsql SECURITY DEFINER
    SET search_path=pg_catalog AS $$
        DECLARE v_window jsonb;
        BEGIN
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 1000 THEN
                RAISE EXCEPTION 'The late-payment pass limit is invalid' USING ERRCODE='22023';
            END IF;
            v_window:=app.automatic_late_payment_charge_window(p_property_id,p_actor_id,p_as_of);
            IF (v_window->>'done')::boolean OR NOT (v_window->>'ready')::boolean THEN
                RETURN; END IF;
            RETURN QUERY
            SELECT invoice.id FROM app.invoices invoice
            WHERE invoice.lease_id IS NOT NULL AND invoice.status NOT IN ('DRAFT','VOID')
              AND invoice.due_date BETWEEN (v_window->>'from_date')::date-1
                  AND (v_window->>'business_date')::date-1
              AND app.invoice_property_id(invoice.id)=p_property_id
              AND (p_after IS NULL OR invoice.id>p_after)
              AND NOT EXISTS(SELECT 1 FROM app.late_payment_decisions decision
                  WHERE decision.source_invoice_id=invoice.id)
            ORDER BY invoice.id
            LIMIT p_limit;
        END $$;

    -- Adds one Invoice's charge, or answers why it adds none. Written at READ COMMITTED (the
    -- closed Final Settlement guard); the Invoice row is locked before the Settlement row.
    CREATE FUNCTION app.record_automatic_late_payment_charge(
        p_property_id uuid, p_actor_id uuid, p_invoice_id uuid,
        p_decision_id uuid, p_charge_id uuid, p_audit_id uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_timezone text; v_invoice app.invoices%ROWTYPE; v_lease_status text;
        DECLARE v_now timestamptz; v_moment timestamptz; v_balance bigint; v_rate smallint;
        DECLARE v_amount bigint; v_closed timestamptz; v_result jsonb;
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
            v_now:=clock_timestamp();
            v_moment:=app.late_payment_charge_moment(v_invoice.due_date,v_timezone);
            IF v_now<app.late_payment_settled_after(v_moment) THEN
                RETURN jsonb_build_object('outcome','NOT_YET_DUE'); END IF;
            IF v_invoice.lease_id IS NULL THEN
                RETURN jsonb_build_object('outcome','NO_LEASE'); END IF;
            SELECT status INTO v_lease_status FROM app.leases WHERE id=v_invoice.lease_id;
            IF v_lease_status IS NULL OR v_lease_status NOT IN ('SIGNED','TERMINATED') THEN
                RETURN jsonb_build_object('outcome','LEASE_NOT_SIGNED_OR_TERMINATED'); END IF;
            IF v_invoice.rent_billing_kind IS NOT DISTINCT FROM 'INITIAL' THEN
                RETURN jsonb_build_object('outcome','INITIAL_RENT'); END IF;
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
                '{REASON}','{AUTOMATIC}',jsonb_build_object(
                    'formula','unpaid_balance_at_charge_moment_x_settings_rate',
                    'rule','DL-076','source_invoice_id',p_invoice_id,
                    'source_due_date',v_invoice.due_date,'charge_moment',v_moment,
                    'overdue_balance_usd_cents',v_balance,'rate_basis_points',v_rate,
                    'rounding','HALF_UP_TO_USD_CENT','calculated_amount_usd_cents',v_amount,
                    'property_timezone',v_timezone,'charge_date',v_invoice.due_date+1));
            INSERT INTO app.late_payment_charges(
                id,customer_id,source_invoice_id,late_payment_decision_id,
                original_amount_usd_cents,payable_at,created_at,created_by_service)
            VALUES (p_charge_id,v_invoice.customer_id,p_invoice_id,p_decision_id,
                v_amount,v_now,v_now,p_actor_id);
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.late_payment_charge_snapshot(p_charge_id);
            INSERT INTO app.audit_events(
                id,occurred_at,business_date,actor_id,action,entity_type,entity_id,reason,
                authorization_reference,property_id,previous_state,resulting_state,
                correlation_id,source,outcome,authorization_evidence,linked_source_event_id,
                customer_id,lease_id)
            VALUES (p_audit_id,v_now,timezone(v_timezone,v_now)::date,p_actor_id,
                'late_payment.charge_added','late_payment_charge',p_charge_id,'{REASON}',
                '{AUTOMATIC}',p_property_id,NULL,v_result,p_decision_id,'SCHEDULED','SUCCEEDED',
                jsonb_build_object('principal_capability','billing.generate','rule','DL-076',
                    'amount_usd_cents',v_amount,'rate_basis_points',v_rate),
                p_charge_id,v_invoice.customer_id,v_invoice.lease_id);
            RETURN jsonb_build_object('outcome','CHARGED','charge',v_result);
        END $$;

    -- Marks the day's pass done once every candidate was looked at.
    CREATE FUNCTION app.record_late_payment_charge_run(
        p_property_id uuid, p_actor_id uuid, p_as_of timestamptz,
        p_charged integer, p_no_amount integer, p_skipped integer)
    RETURNS date LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_window jsonb; v_day date;
        BEGIN
            v_window:=app.automatic_late_payment_charge_window(p_property_id,p_actor_id,p_as_of);
            v_day:=(v_window->>'business_date')::date;
            IF NOT (v_window->>'ready')::boolean THEN
                RAISE EXCEPTION 'The late-payment pass is not ready for this day'
                    USING ERRCODE='55000'; END IF;
            IF (v_window->>'done')::boolean THEN RETURN v_day; END IF;
            IF p_charged IS NULL OR p_no_amount IS NULL OR p_skipped IS NULL
                OR least(p_charged,p_no_amount,p_skipped)<0
            THEN RAISE EXCEPTION 'The late-payment pass counts are invalid' USING ERRCODE='22023';
            END IF;
            INSERT INTO app.late_payment_charge_runs(property_id,business_date,system_actor_id,
                recorded_at,charged_count,no_amount_count,skipped_count)
            VALUES (p_property_id,v_day,p_actor_id,clock_timestamp(),p_charged,p_no_amount,
                p_skipped)
            ON CONFLICT (property_id,business_date) DO NOTHING;
            RETURN v_day;
        END $$;
"""

INTERNAL = (
    "app.late_payment_rate_basis_points(uuid,date)",
    "app.late_payment_charge_moment(date,text)",
    "app.late_payment_amount(smallint,bigint)",
    "app.late_payment_settled_after(timestamp with time zone)",
    "app.validate_automatic_late_payment_decision(uuid)",
    "app.require_late_payment_charge_job(uuid,uuid)",
    "app.late_payment_first_charge_day(uuid,timestamp with time zone,text)",
)
FINANCIAL = (
    "app.automatic_late_payment_charge_window(uuid,uuid,timestamp with time zone)",
    (
        "app.automatic_late_payment_charge_candidates("
        "uuid,uuid,timestamp with time zone,uuid,integer)"
    ),
    "app.record_automatic_late_payment_charge(uuid,uuid,uuid,uuid,uuid,uuid)",
    (
        "app.record_late_payment_charge_run("
        "uuid,uuid,timestamp with time zone,integer,integer,integer)"
    ),
)

PATCHES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "app.enforce_active_human_financial_actor()",
        (
            (
                "WHEN 'late_payment_decisions' THEN (to_jsonb(NEW)->>'finalized_by')::uuid\n",
                "WHEN 'late_payment_decisions' THEN COALESCE(\n"
                "                    (to_jsonb(NEW)->>'finalized_by')::uuid,\n"
                "                    (to_jsonb(NEW)->>'finalized_by_service')::uuid)\n",
            ),
            (
                "WHEN 'late_payment_charges' THEN (to_jsonb(NEW)->>'created_by')::uuid\n",
                "WHEN 'late_payment_charges' THEN COALESCE(\n"
                "                    (to_jsonb(NEW)->>'created_by')::uuid,\n"
                "                    (to_jsonb(NEW)->>'created_by_service')::uuid)\n",
            ),
            (
                "PERFORM app.assert_active_financial_actor(v_actor_id,NULL);",
                "-- V1-056 slice 11g-1 (DL-076): a decision or a charge names its\n"
                "            -- Invoice's Property, so that Property's billing service principal\n"
                "            -- is accepted.\n"
                "            PERFORM app.assert_active_financial_actor(v_actor_id,\n"
                "                CASE WHEN TG_TABLE_NAME IN\n"
                "                    ('late_payment_decisions','late_payment_charges')\n"
                "                    THEN app.invoice_property_id(\n"
                "                        (to_jsonb(NEW)->>'source_invoice_id')::uuid) END);",
            ),
        ),
    ),
    (
        "app.validate_late_payment_decision()",
        (
            (
                "DECLARE v_invoice app.invoices%ROWTYPE; v_balance bigint; v_default bigint;\n"
                "        BEGIN\n",
                "DECLARE v_invoice app.invoices%ROWTYPE; v_balance bigint; v_default bigint;\n"
                "        BEGIN\n"
                "            -- V1-056 slice 11g-1 (DL-076): the automatic charge has its own\n"
                "            -- rule; any other decision is a person's, checked as before.\n"
                f"            IF NEW.authorization_reference='{AUTOMATIC}' THEN\n"
                "                PERFORM app.validate_automatic_late_payment_decision(NEW.id);\n"
                "                RETURN NEW;\n"
                "            END IF;\n"
                "            -- A person's decision keeps the fixed 10 percent of the manual\n"
                "            -- path.\n"
                "            IF NEW.finalized_by IS NULL OR NEW.finalized_by_service IS NOT NULL\n"
                "            THEN RAISE EXCEPTION\n"
                "                'A person''s late-payment decision needs a person'\n"
                "                USING ERRCODE='23514'; END IF;\n"
                "            IF NEW.default_rate_basis_points<>1000\n"
                "            THEN RAISE EXCEPTION 'Late-payment assessment snapshot is invalid'\n"
                "                USING ERRCODE='23514'; END IF;\n",
            ),
        ),
    ),
    (
        "app.validate_late_payment_charge()",
        (
            (
                "                OR NEW.created_at<v_decision.finalized_at\n",
                "                OR NEW.created_at<v_decision.finalized_at\n"
                "                -- V1-056 slice 11g-1: made by the actor of its decision.\n"
                "                OR NEW.created_by IS DISTINCT FROM v_decision.finalized_by\n"
                "                OR NEW.created_by_service IS DISTINCT FROM\n"
                "                    v_decision.finalized_by_service\n",
            ),
        ),
    ),
    (
        "app.late_payment_decision_snapshot(uuid)",
        (
            (
                "'finalized_by',v_decision.finalized_by,",
                "'finalized_by',COALESCE(v_decision.finalized_by,\n"
                "                    v_decision.finalized_by_service),",
            ),
        ),
    ),
    (
        "app.late_payment_charge_snapshot(uuid)",
        (
            (
                "'created_by',v_charge.created_by",
                "'created_by',COALESCE(v_charge.created_by,v_charge.created_by_service)",
            ),
        ),
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
            raise RuntimeError(f"Late-payment charge contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def _constraint(table: str, definition: str) -> str:
    names = (
        op.get_bind()
        .execute(
            text(
                "SELECT conname FROM pg_catalog.pg_constraint "
                "WHERE conrelid=CAST(:table AS regclass) "
                "AND pg_catalog.pg_get_constraintdef(oid)=:definition"
            ),
            {"table": table, "definition": definition},
        )
        .scalars()
        .all()
    )
    if len(names) != 1:
        raise RuntimeError(f"Late-payment constraint changed: {table} {definition}")
    return str(names[0])


def _replace_position_view() -> None:
    """The charge position view shows the service as the creator when there is no person; same
    columns and types, so CREATE OR REPLACE keeps its privileges and security_invoker."""
    definition = str(
        op.get_bind()
        .execute(
            text(
                "SELECT pg_catalog.pg_get_viewdef("
                "'app.late_payment_charge_financial_position'::regclass)"
            )
        )
        .scalar_one()
    )
    before = "charge.created_by\n"
    if definition.count(before) != 1:
        raise RuntimeError("Late-payment charge position view changed")
    definition = definition.replace(
        before, "COALESCE(charge.created_by, charge.created_by_service) AS created_by\n"
    )
    op.execute(
        "CREATE OR REPLACE VIEW app.late_payment_charge_financial_position "
        f"WITH (security_invoker = true) AS {definition}"
    )


def upgrade() -> None:
    rate = _constraint("app.late_payment_decisions", "CHECK ((default_rate_basis_points = 1000))")
    op.execute(f'ALTER TABLE app.late_payment_decisions DROP CONSTRAINT "{rate}"')
    op.execute(
        "ALTER TABLE app.late_payment_decisions ADD CONSTRAINT "
        "late_payment_decisions_rate_whole_percent CHECK ("
        "default_rate_basis_points BETWEEN 0 AND 1000 AND default_rate_basis_points % 100 = 0)"
    )
    for table, person, service in (
        ("late_payment_decisions", "finalized_by", "finalized_by_service"),
        ("late_payment_charges", "created_by", "created_by_service"),
    ):
        op.execute(
            f"ALTER TABLE app.{table} ADD COLUMN {service} uuid "
            "REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT, "
            f"ALTER COLUMN {person} DROP NOT NULL, "
            f"ADD CONSTRAINT {table}_one_actor CHECK (({person} IS NULL) <> ({service} IS NULL))"
        )
    op.execute(SQL)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    _replace_position_view()
    # Read only through the definer functions above.
    op.execute(
        "REVOKE ALL ON TABLE app.late_payment_charge_runs "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    for function in (*INTERNAL, *FINANCIAL):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} "
            "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for function in FINANCIAL:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("The automatic late-payment charge migration is forward-only")
