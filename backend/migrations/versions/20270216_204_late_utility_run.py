# ruff: noqa: E501
"""The scheduled worker bills a Utility period finalized after a run for its dates (V1-056 slice 12b).

DL-071 answer 18 (owner, 2026-10-20): a Utility period finalized after a SUCCEEDED Utility run
for the same dates (`LATE_AFTER_SUCCEEDED_RUN`, migration `20261008_73`) is billed by the next
scheduled pass by itself, once and never twice. `app.utility_unbilled_periods`, its route and the
staff catch-up command stay as a safety check; a `NOT_MOVED_IN` period is still billed only by the
catch-up command.

A late period is billed by a late Utility run: a successor of the last SUCCEEDED run of the same
dates, with a logical key that starts with `utilities-late/`, dated on the worker's business day.

1. `app.protect_billing_run_history` also accepts, as a successor, a scheduled late Utility run
   of a SUCCEEDED predecessor on the same or a later business day (a successor of a FAILED run
   is unchanged).
2. `app.snapshot_billing_run_eligible_sources` gives a late run, instead of a copy of the
   predecessor's snapshot, exactly the periods the candidate function lists: finalized periods of
   its dates with no Invoice line (a voided one included), that no run of those dates ever
   snapshotted, whose Lease is responsible (no Utility case). A period an earlier run skipped
   (for example `NOT_MOVED_IN`) is never tried again by the worker; a period billed meanwhile by
   the catch-up command is skipped by the existing item recorder.
3. `app.start_scheduled_billing_run` does not match a late run to the root run of its dates and
   links it to the last SUCCEEDED run of the chain (refused when the chain does not end in a
   SUCCEEDED run, 55000, and for an API call or a Rent run, 22023).
4. `app.scheduled_late_utility_candidates` (new, `prm_financial` only) lists the dates to bill:
   a RUNNING late run to finish, and the dates of each finalized period that the Lease is
   responsible for, that has no Invoice line, that no run of its dates ever snapshotted, and
   whose dates have a chain ending in a SUCCEEDED run and no RUNNING run; its key names the
   SUCCEEDED run it continues. A late run whose item
   ends in an error stays RUNNING and the same worker resumes it with its own key on the next
   pass; a period it skipped stays in the unbilled list for the catch-up command.
5. `app.record_scheduled_utility_item`: a late run's Invoice is due on the later of the on-time
   Due Date and its issue date plus the Property's configured days (decided by Claude under the
   owner's 2026-10-23 22:30 rule, DL-091).

Each existing function is patched by exact text; CREATE OR REPLACE keeps its owner, settings and
grants.
"""

from alembic import op
from sqlalchemy import text

revision = "20270216_204"
down_revision = "20270215_203"
branch_labels = None
depends_on = None

PROTECT = "app.protect_billing_run_history()"
SNAPSHOT = "app.snapshot_billing_run_eligible_sources()"
START = (
    "app.start_scheduled_billing_run(uuid,uuid,text,text,date,date,date,uuid,text,uuid,uuid,"
    "uuid,text)"
)
ITEM = "app.record_scheduled_utility_item(uuid,uuid,text,uuid,uuid,text,uuid,timestamptz)"
CANDIDATES = "app.scheduled_late_utility_candidates(uuid,uuid,timestamp with time zone,integer)"

PROTECT_BEFORE = (
    "                    IF v_predecessor.id IS NULL OR v_predecessor.status<>'FAILED'\n"
    "                        OR NEW.property_id<>v_predecessor.property_id\n"
    "                        OR NEW.run_kind<>v_predecessor.run_kind\n"
    "                        OR NEW.business_date<>v_predecessor.business_date\n"
)
PROTECT_AFTER = (
    "                    IF v_predecessor.id IS NULL\n"
    "                        OR NOT ((v_predecessor.status='FAILED'\n"
    "                                AND NEW.business_date=v_predecessor.business_date)\n"
    "                            -- V1-056 slice 12b: a late Utility run continues a SUCCEEDED one.\n"
    "                            OR (v_predecessor.status='SUCCEEDED' AND NEW.run_kind='UTILITIES'\n"
    "                                AND left(NEW.logical_run_key,15)='utilities-late/'\n"
    "                                AND NEW.invocation_source='SCHEDULED'\n"
    "                                AND NEW.business_date>=v_predecessor.business_date))\n"
    "                        OR NEW.property_id<>v_predecessor.property_id\n"
    "                        OR NEW.run_kind<>v_predecessor.run_kind\n"
)
SNAPSHOT_BEFORE = "            IF NEW.predecessor_run_id IS NOT NULL THEN\n"
SNAPSHOT_AFTER = (
    "            -- V1-056 slice 12b: a late Utility run (successor of a SUCCEEDED run) snapshots\n"
    "            -- only what app.scheduled_late_utility_candidates lists: finalized periods of its\n"
    "            -- dates with no Invoice line, that no run of those dates ever snapshotted, whose\n"
    "            -- Lease is responsible. A period an earlier run skipped is never tried again.\n"
    "            IF NEW.predecessor_run_id IS NOT NULL AND EXISTS (\n"
    "                SELECT 1 FROM app.billing_runs AS predecessor\n"
    "                WHERE predecessor.id=NEW.predecessor_run_id AND predecessor.status='SUCCEEDED'\n"
    "            ) THEN\n"
    "                INSERT INTO app.billing_run_eligible_sources(\n"
    "                    billing_run_id,source_kind,source_id,source_period_start,source_period_end,\n"
    "                    snapshotted_at,source_evidence\n"
    "                )\n"
    "                SELECT NEW.id,'UTILITY_PERIOD',period.id,period.start_date,period.end_date,\n"
    "                    statement_timestamp(),pg_catalog.jsonb_build_object(\n"
    "                        'unit_id',period.unit_id,'utility_type',period.utility_type,\n"
    "                        'calculation_kind',period.calculation_kind,\n"
    "                        'consumption_quantity',app.utility_consumption_effective_quantity(period.id),\n"
    "                        'finalized_at',period.finalized_at,'finalized_by',period.finalized_by,\n"
    "                        'calculation_trace',period.calculation_trace\n"
    "                    )\n"
    "                FROM app.utility_consumption_periods AS period\n"
    "                JOIN app.units AS unit ON unit.id=period.unit_id\n"
    "                WHERE NEW.run_kind='UTILITIES' AND unit.property_id=NEW.property_id\n"
    "                  AND period.start_date=NEW.period_start AND period.end_date=NEW.period_end\n"
    "                  AND period.finalized_at<=statement_timestamp()\n"
    "                  AND NOT EXISTS (SELECT 1 FROM app.invoice_lines AS line\n"
    "                      WHERE line.utility_consumption_period_id=period.id)\n"
    "                  AND EXISTS (SELECT 1 FROM app.utility_period_responsibility(\n"
    "                          period.unit_id,period.start_date,period.end_date) AS responsibility\n"
    "                      WHERE responsibility.outcome='RESPONSIBLE')\n"
    "                  AND NOT EXISTS (SELECT 1 FROM app.billing_runs AS seen\n"
    "                      JOIN app.billing_run_eligible_sources AS snapshot\n"
    "                        ON snapshot.billing_run_id=seen.id\n"
    "                      WHERE seen.property_id=NEW.property_id AND seen.run_kind='UTILITIES'\n"
    "                        AND seen.period_start=NEW.period_start\n"
    "                        AND seen.period_end=NEW.period_end AND seen.id<>NEW.id\n"
    "                        AND snapshot.source_kind='UTILITY_PERIOD'\n"
    "                        AND snapshot.source_id=period.id)\n"
    "                ORDER BY period.id;\n"
    "                RETURN NEW;\n"
    "            END IF;\n"
    "            IF NEW.predecessor_run_id IS NOT NULL THEN\n"
)
START_DECLARE_BEFORE = (
    "        DECLARE v_attempt_number integer; v_started_at timestamptz:=clock_timestamp();\n"
)
START_DECLARE_AFTER = (
    "        DECLARE v_attempt_number integer; v_started_at timestamptz:=clock_timestamp();\n"
    "        DECLARE v_late_predecessor uuid;\n"
)
START_MATCH_BEFORE = (
    "                OR (run.run_kind=p_run_kind AND run.period_start=p_period_start\n"
    "                    AND run.period_end=p_period_end AND run.predecessor_run_id IS NULL)\n"
)
START_MATCH_AFTER = (
    "                OR (run.run_kind=p_run_kind AND run.period_start=p_period_start\n"
    "                    AND run.period_end=p_period_end AND run.predecessor_run_id IS NULL\n"
    "                    AND left(p_logical_run_key,15)<>'utilities-late/')\n"
)
START_INSERT_BEFORE = (
    "            ELSE\n"
    "                INSERT INTO app.billing_runs(\n"
    "                    id,property_id,run_kind,logical_run_key,business_date,period_start,period_end,\n"
    "                    idempotency_key,request_digest,requester_actor_id,system_actor_id,correlation_id,\n"
    "                    invocation_source,status,started_at\n"
    "                ) VALUES (\n"
    "                    p_run_id,p_property_id,p_run_kind,p_logical_run_key,p_business_date,\n"
    "                    p_period_start,p_period_end,p_idempotency_key,p_request_digest,\n"
    "                    p_requester_actor_id,p_system_actor_id,\n"
    "                    p_correlation_id,p_invocation_source,'RUNNING',v_started_at\n"
    "                ) RETURNING * INTO v_run;\n"
)
START_INSERT_AFTER = (
    "            ELSE\n"
    "                -- V1-056 slice 12b: a late Utility run (scheduled worker only) continues the\n"
    "                -- last run of its dates, which must have SUCCEEDED (the advisory lock above\n"
    "                -- serializes the chain).\n"
    "                IF left(p_logical_run_key,15)='utilities-late/' THEN\n"
    "                    IF p_run_kind<>'UTILITIES' OR p_invocation_source<>'SCHEDULED' THEN\n"
    "                        RAISE EXCEPTION 'Scheduled Billing command evidence is invalid'\n"
    "                            USING ERRCODE='22023';\n"
    "                    END IF;\n"
    "                    SELECT run.id INTO v_late_predecessor FROM app.billing_runs AS run\n"
    "                    WHERE run.property_id=p_property_id AND run.run_kind='UTILITIES'\n"
    "                      AND run.period_start=p_period_start AND run.period_end=p_period_end\n"
    "                      AND run.status='SUCCEEDED'\n"
    "                      AND NOT EXISTS (SELECT 1 FROM app.billing_runs AS successor\n"
    "                          WHERE successor.predecessor_run_id=run.id)\n"
    "                    FOR UPDATE;\n"
    "                    IF v_late_predecessor IS NULL THEN\n"
    "                        RAISE EXCEPTION 'A late Utility run needs a succeeded run of its dates'\n"
    "                            USING ERRCODE='55000';\n"
    "                    END IF;\n"
    "                END IF;\n"
    "                INSERT INTO app.billing_runs(\n"
    "                    id,property_id,run_kind,logical_run_key,business_date,period_start,period_end,\n"
    "                    idempotency_key,request_digest,requester_actor_id,system_actor_id,correlation_id,\n"
    "                    invocation_source,status,started_at,predecessor_run_id\n"
    "                ) VALUES (\n"
    "                    p_run_id,p_property_id,p_run_kind,p_logical_run_key,p_business_date,\n"
    "                    p_period_start,p_period_end,p_idempotency_key,p_request_digest,\n"
    "                    p_requester_actor_id,p_system_actor_id,\n"
    "                    p_correlation_id,p_invocation_source,'RUNNING',v_started_at,\n"
    "                    v_late_predecessor\n"
    "                ) RETURNING * INTO v_run;\n"
)
ITEM_DUE_BEFORE = (
    "                v_due_date:=(date_trunc('month',v_period.end_date)::date\n"
    "                    + interval '1 month')::date+4;\n"
)
ITEM_DUE_AFTER = ITEM_DUE_BEFORE + (
    "                -- V1-056 slice 12b: a late Utility run's Invoice is due no earlier than the\n"
    "                -- on-time Due Date and no earlier than the Property's configured days\n"
    "                -- after it is issued (the catch-up command's rule, BR-UTIL-021), counted\n"
    "                -- from the Property's date now when a resumed run issues it later.\n"
    "                IF left(v_run.logical_run_key,15)='utilities-late/' THEN\n"
    "                    SELECT greatest(v_due_date,\n"
    "                            greatest(v_run.business_date,\n"
    "                                timezone(property.timezone_name,v_now)::date)\n"
    "                            +property.one_time_charge_due_days)\n"
    "                    INTO STRICT v_due_date FROM app.properties AS property\n"
    "                    WHERE property.id=v_run.property_id;\n"
    "                END IF;\n"
)
ITEM_RULE_BEFORE = (
    "                    v_amount,'GOVERNING_SOURCE','BR-UTIL-022',1,v_now,v_run.system_actor_id,\n"
)
ITEM_RULE_AFTER = (
    "                    v_amount,\n"
    "                    CASE WHEN v_due_date=(date_trunc('month',v_period.end_date)::date\n"
    "                        + interval '1 month')::date+4 THEN 'GOVERNING_SOURCE'\n"
    "                        ELSE 'ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS' END,\n"
    "                    CASE WHEN v_due_date=(date_trunc('month',v_period.end_date)::date\n"
    "                        + interval '1 month')::date+4 THEN 'BR-UTIL-022' ELSE 'BR-UTIL-021' END,\n"
    "                    1,v_now,v_run.system_actor_id,\n"
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
            raise RuntimeError(f"Billing run contract changed: {signature}")
        definition = definition.replace(before, after)
    op.execute(definition)


def upgrade() -> None:
    _patch(PROTECT, ((PROTECT_BEFORE, PROTECT_AFTER),))
    _patch(SNAPSHOT, ((SNAPSHOT_BEFORE, SNAPSHOT_AFTER),))
    _patch(ITEM, ((ITEM_DUE_BEFORE, ITEM_DUE_AFTER), (ITEM_RULE_BEFORE, ITEM_RULE_AFTER)))
    _patch(
        START,
        (
            (START_DECLARE_BEFORE, START_DECLARE_AFTER),
            (START_MATCH_BEFORE, START_MATCH_AFTER),
            (START_INSERT_BEFORE, START_INSERT_AFTER),
        ),
    )
    op.execute(
        """
        CREATE FUNCTION app.scheduled_late_utility_candidates(
            p_property_id uuid,p_actor_id uuid,p_as_of timestamptz,p_limit integer
        ) RETURNS TABLE(business_date date,period_start date,period_end date,logical_run_key text,
            idempotency_key uuid)
        LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_timezone text; v_current_date date;
        BEGIN
            IF p_as_of IS NULL OR p_limit IS NULL OR p_limit<1 OR p_limit>100 THEN
                RAISE EXCEPTION 'Worker candidate bounds are invalid' USING ERRCODE='22023';
            END IF;
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            SELECT property.timezone_name INTO STRICT v_timezone
            FROM app.properties AS property WHERE property.id=p_property_id;
            v_current_date:=timezone(v_timezone,p_as_of)::date;
            RETURN QUERY
            WITH unfinished AS (
                SELECT run.business_date AS run_date,run.period_start AS run_start,
                    run.period_end AS run_end,run.logical_run_key AS run_key,
                    run.idempotency_key AS run_idempotency_key
                FROM app.billing_runs AS run
                WHERE run.property_id=p_property_id AND run.run_kind='UTILITIES'
                  AND run.status='RUNNING' AND left(run.logical_run_key,15)='utilities-late/'
                  AND run.requester_actor_id=p_actor_id
            ), late AS (
                -- The key names the run it continues, so a second late period of the same
                -- dates on the same day gets a new run.
                SELECT DISTINCT v_current_date AS run_date,period.start_date AS run_start,
                    period.end_date AS run_end,
                    'utilities-late/'||to_char(period.start_date,'YYYY-MM-DD')||'/'
                        ||to_char(period.end_date,'YYYY-MM-DD')||'/'
                        ||to_char(v_current_date,'YYYY-MM-DD')||'/'||last_run.id::text AS run_key,
                    NULL::uuid AS run_idempotency_key
                FROM app.utility_consumption_periods AS period
                JOIN app.units AS unit ON unit.id=period.unit_id
                JOIN app.billing_runs AS last_run ON last_run.property_id=p_property_id
                  AND last_run.run_kind='UTILITIES' AND last_run.period_start=period.start_date
                  AND last_run.period_end=period.end_date AND last_run.status='SUCCEEDED'
                  AND last_run.business_date<=v_current_date
                  AND NOT EXISTS (SELECT 1 FROM app.billing_runs AS successor
                      WHERE successor.predecessor_run_id=last_run.id)
                WHERE unit.property_id=p_property_id
                  AND period.finalized_at<=p_as_of
                  AND greatest(period.end_date,timezone(v_timezone,period.finalized_at)::date)
                      <=v_current_date
                  AND NOT EXISTS (SELECT 1 FROM app.invoice_lines AS line
                      WHERE line.utility_consumption_period_id=period.id)
                  AND NOT EXISTS (SELECT 1 FROM app.billing_runs AS seen
                      JOIN app.billing_run_eligible_sources AS snapshot
                        ON snapshot.billing_run_id=seen.id
                      WHERE seen.property_id=p_property_id AND seen.run_kind='UTILITIES'
                        AND seen.period_start=period.start_date AND seen.period_end=period.end_date
                        AND snapshot.source_kind='UTILITY_PERIOD' AND snapshot.source_id=period.id)
                  AND NOT EXISTS (SELECT 1 FROM app.billing_runs AS running
                      WHERE running.property_id=p_property_id AND running.run_kind='UTILITIES'
                        AND running.period_start=period.start_date
                        AND running.period_end=period.end_date AND running.status='RUNNING')
                  AND EXISTS (SELECT 1 FROM app.utility_period_responsibility(
                          period.unit_id,period.start_date,period.end_date) AS responsibility
                      WHERE responsibility.outcome='RESPONSIBLE')
            )
            SELECT candidate.run_date,candidate.run_start,candidate.run_end,candidate.run_key,
                candidate.run_idempotency_key
            FROM (SELECT * FROM unfinished UNION SELECT * FROM late) AS candidate
            ORDER BY candidate.run_end,candidate.run_start,candidate.run_date,candidate.run_key
            LIMIT p_limit;
        END $$;
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {CANDIDATES} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap")
    op.execute(f"GRANT EXECUTE ON FUNCTION {CANDIDATES} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Late Utility run migration is forward-only")
