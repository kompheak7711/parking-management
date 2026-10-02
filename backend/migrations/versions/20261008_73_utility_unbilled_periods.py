# ruff: noqa: E501
"""Let Utility runs of overlapping dates coexist, list unbilled periods and catch them up.

Relaxing and additive only. The Utility run bills only periods whose exact dates equal the run's
dates, and an Invoice line is UNIQUE per consumption period, so overlapping Utility run ranges
cannot double bill; only Rent runs keep the no-overlap rule. A period finalized after a successful
run for the same dates, or skipped as NOT_MOVED_IN, is never picked up again: staff see it in
app.utility_unbilled_periods and bill it with the explicit catch-up command.
"""

from alembic import op
from sqlalchemy import text

revision = "20261008_73"
down_revision = "20261007_72"
branch_labels = None
depends_on = None

CATCH_UP = "app.utility_catch_up_invoice_create(uuid,uuid,uuid,uuid,text,jsonb,text)"
ROWS = "app.utility_unbilled_period_rows(uuid)"
UNBILLED = "app.utility_unbilled_periods(uuid,uuid,integer,integer)"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE app.billing_runs DROP CONSTRAINT billing_runs_period_no_overlap;
        ALTER TABLE app.billing_runs ADD CONSTRAINT billing_runs_period_no_overlap
            EXCLUDE USING gist (
                property_id WITH =,run_kind WITH =,
                daterange(period_start,period_end,'[]') WITH &&
            ) WHERE (status<>'FAILED' AND run_kind='RENT');

        CREATE FUNCTION app.utility_unbilled_period_rows(p_property uuid)
        RETURNS TABLE(period_id uuid,unit_id uuid,utility_type text,start_date date,end_date date,
            quantity text,lease_id uuid,can_catch_up boolean,gap_reason text)
        LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
            SELECT period.id,period.unit_id,period.utility_type,period.start_date,period.end_date,
                period.consumption_quantity::text,resp.lease_id,resp.outcome='RESPONSIBLE',
                CASE WHEN EXISTS(SELECT 1 FROM app.billing_run_items AS item
                        WHERE item.outcome='SKIPPED' AND item.diagnostic_code='NOT_MOVED_IN'
                            AND ((item.source_kind='UTILITY_PERIOD' AND item.source_id=period.id)
                                OR (item.source_kind='UTILITY_CASE' AND item.source_id IN (
                                    SELECT estimate.estimation_case_id FROM app.broken_meter_estimates AS estimate
                                    WHERE estimate.consumption_period_id=period.id))))
                        THEN 'NOT_MOVED_IN'
                    ELSE 'LATE_AFTER_SUCCEEDED_RUN' END
            FROM app.utility_consumption_periods AS period
            JOIN app.units AS unit ON unit.id=period.unit_id AND unit.property_id=p_property
            CROSS JOIN LATERAL app.utility_period_responsibility(period.unit_id,period.start_date,period.end_date) AS resp
            WHERE resp.outcome IN ('RESPONSIBLE','NOT_MOVED_IN')
                AND NOT EXISTS(SELECT 1 FROM app.invoice_lines AS line WHERE line.utility_consumption_period_id=period.id)
                AND (EXISTS(SELECT 1 FROM app.billing_run_items AS item
                        WHERE item.outcome='SKIPPED' AND item.diagnostic_code='NOT_MOVED_IN'
                            AND ((item.source_kind='UTILITY_PERIOD' AND item.source_id=period.id)
                                OR (item.source_kind='UTILITY_CASE' AND item.source_id IN (
                                    SELECT estimate.estimation_case_id FROM app.broken_meter_estimates AS estimate
                                    WHERE estimate.consumption_period_id=period.id))))
                    OR EXISTS(SELECT 1 FROM app.billing_runs AS late_run
                        WHERE late_run.property_id=p_property AND late_run.run_kind='UTILITIES'
                            AND late_run.status='SUCCEEDED' AND late_run.period_start=period.start_date
                            AND late_run.period_end=period.end_date
                            AND NOT EXISTS(SELECT 1 FROM app.billing_run_eligible_sources AS snapshot
                                WHERE snapshot.billing_run_id=late_run.id AND snapshot.source_kind='UTILITY_PERIOD'
                                    AND snapshot.source_id=period.id)))
        $$;

        CREATE FUNCTION app.utility_unbilled_periods(p_property uuid,p_actor uuid,p_limit integer,p_offset integer)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_items jsonb; v_total integer;
        BEGIN
            IF NOT EXISTS(SELECT 1 FROM app.user_accounts WHERE actor_id=p_actor AND lifecycle_state='active')
            THEN RAISE EXCEPTION 'Utility period actor is not active' USING ERRCODE='P5406'; END IF;
            IF p_property IS NULL OR NOT EXISTS(SELECT 1 FROM app.properties WHERE id=p_property)
            THEN RAISE EXCEPTION 'Utility period Property was not found' USING ERRCODE='P5401'; END IF;
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 50 OR p_offset IS NULL OR p_offset NOT BETWEEN 0 AND 1000000
            THEN RAISE EXCEPTION 'Utility period page is invalid' USING ERRCODE='P5N02'; END IF;
            SELECT count(*) INTO v_total FROM app.utility_unbilled_period_rows(p_property);
            SELECT COALESCE(jsonb_agg(jsonb_build_object('period_id',page.period_id,'unit_id',page.unit_id,
                'utility_type',page.utility_type,'start_date',page.start_date,'end_date',page.end_date,
                'consumption_quantity',page.quantity,'lease_id',page.lease_id,'can_catch_up',page.can_catch_up,
                'gap_reason',page.gap_reason) ORDER BY page.end_date,page.start_date,page.period_id),'[]'::jsonb)
            INTO v_items FROM (SELECT * FROM app.utility_unbilled_period_rows(p_property)
                ORDER BY end_date,start_date,period_id LIMIT p_limit OFFSET p_offset) AS page;
            RETURN jsonb_build_object('items',v_items,'total',v_total,'limit',p_limit,'offset',p_offset,
                'creates_invoice',false);
        END $$;
    """)
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": CATCH_UP},
        )
        .scalar_one()
    )
    marker = "THEN RAISE EXCEPTION 'UTILITY_PERIOD_NOT_SKIPPED'"
    if definition.count(marker) != 1:
        raise RuntimeError("Utility catch-up evidence contract changed")
    late = """AND NOT EXISTS(SELECT 1 FROM app.billing_runs AS late_run
                    WHERE late_run.property_id=p_property AND late_run.run_kind='UTILITIES'
                        AND late_run.status='SUCCEEDED' AND late_run.period_start=v_p.start_date
                        AND late_run.period_end=v_p.end_date
                        AND NOT EXISTS(SELECT 1 FROM app.billing_run_eligible_sources AS snapshot
                            WHERE snapshot.billing_run_id=late_run.id AND snapshot.source_kind='UTILITY_PERIOD'
                                AND snapshot.source_id=v_period))
            """
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition.replace(marker, late + marker))
    for function in (ROWS, UNBILLED):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {UNBILLED} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("Utility unbilled period migration is forward-only")
