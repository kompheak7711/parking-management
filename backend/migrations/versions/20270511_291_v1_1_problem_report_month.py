# ruff: noqa: E501
"""Problem reports: the Home card and the Monthly report (DL-131).

Mock-up round 29 (Monthly report of Tenant requests) and round 32 (A7 cost in the Monthly
report, A10 Home card, "Home lists each cost still to check"), approved by the owner on
03/11/2026 with the Problem report design.

1. ``app.problem_report_summary`` (``problem_reports.read``): open reports, how many are urgent
   and late (the same Late rule as the list), and each cost still waiting for a Manager's check.
2. ``app.problem_report_month`` (``problem_reports.plan``, the Monthly report): for one month in
   the Property's time zone, the reports received (joined reports are counted apart, not
   again), urgent ones contacted on time, normal ones planned on time, done and the average days
   to fix, still open, opened again (Not fixed), who pays and the Damage charges, reports by
   type and by place, repeat problems, the reports late now, and the repair cost by Unit and by
   type (parts and outside workers, dollars and riel kept apart; the latest entry of each report
   done in the month).

Read only. Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270511_291"
down_revision: str | None = "20270510_290"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTIONS = """
    -- Late now, by the list's rule (problem_report_json): NULL, URGENT or NORMAL.
    CREATE FUNCTION app.problem_report_late(p_report uuid) RETURNS text
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT app.problem_report_json(p_report, false) ->> 'late'
    $$;
    REVOKE ALL ON FUNCTION app.problem_report_late(uuid) FROM PUBLIC;

    -- The total of each cost kind and currency in the latest entry of one report.
    CREATE FUNCTION app.problem_report_cost_parts(p_report uuid)
    RETURNS TABLE (parts_usd_cents bigint, outside_usd_cents bigint, parts_khr bigint,
        outside_khr bigint)
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT
            COALESCE(sum(line.amount_minor) FILTER (WHERE line.kind = 'PARTS' AND line.currency = 'USD'), 0)::bigint,
            COALESCE(sum(line.amount_minor) FILTER (WHERE line.kind = 'OUTSIDE_WORKER' AND line.currency = 'USD'), 0)::bigint,
            COALESCE(sum(line.amount_minor) FILTER (WHERE line.kind = 'PARTS' AND line.currency = 'KHR'), 0)::bigint,
            COALESCE(sum(line.amount_minor) FILTER (WHERE line.kind = 'OUTSIDE_WORKER' AND line.currency = 'KHR'), 0)::bigint
        FROM app.problem_report_cost_lines AS line
        WHERE line.set_id = (app.problem_report_cost_latest(p_report)).id
    $$;
    REVOKE ALL ON FUNCTION app.problem_report_cost_parts(uuid) FROM PUBLIC;

    -- 1. The Home card.
    CREATE FUNCTION app.problem_report_summary(p_property uuid, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        PERFORM app.require_product_right(p_actor, 'problem_reports.read', p_property);
        RETURN (
            WITH open AS (
                SELECT report.id, report.urgent, app.problem_report_late(report.id) AS late
                FROM app.problem_reports AS report
                WHERE report.property_id = p_property
                  AND report.status NOT IN ('DONE', 'CLOSED', 'NOT_ACCEPTED', 'JOINED')
            ), waiting AS (
                SELECT report.id, report.report_number, report.kind, unit.unit_number,
                    shared.name_en AS place_en, shared.name_kh AS place_kh, cost_set.entered_at,
                    cost_set.set_id
                FROM app.problem_reports AS report
                CROSS JOIN LATERAL (SELECT latest.id AS set_id, latest.entered_at, latest.no_cost
                    FROM app.problem_report_cost_latest(report.id) AS latest) AS cost_set
                LEFT JOIN app.units AS unit ON unit.id = report.unit_id
                LEFT JOIN app.problem_places AS shared ON shared.id = report.problem_place_id
                WHERE report.property_id = p_property AND cost_set.set_id IS NOT NULL
                  AND NOT cost_set.no_cost
                  AND NOT EXISTS (SELECT 1 FROM app.problem_report_cost_checks AS checked
                                  WHERE checked.set_id = cost_set.set_id)
            )
            SELECT jsonb_build_object(
                'open', (SELECT count(*) FROM open),
                'urgent', (SELECT count(*) FROM open WHERE open.urgent),
                'late', (SELECT count(*) FROM open WHERE open.late IS NOT NULL),
                'costs_to_check', COALESCE((
                    SELECT jsonb_agg(jsonb_build_object('report_id', waiting.id,
                            'report_number', waiting.report_number, 'kind', waiting.kind,
                            'unit_number', waiting.unit_number, 'place_en', waiting.place_en,
                            'place_kh', waiting.place_kh, 'entered_at', waiting.entered_at,
                            'totals', COALESCE((
                                SELECT jsonb_agg(jsonb_build_object('currency', total.currency,
                                        'amount_minor', total.amount_minor) ORDER BY total.currency DESC)
                                FROM (SELECT line.currency, sum(line.amount_minor)::bigint AS amount_minor
                                      FROM app.problem_report_cost_lines AS line
                                      WHERE line.set_id = waiting.set_id GROUP BY line.currency) AS total),
                                '[]'::jsonb))
                        ORDER BY waiting.entered_at)
                    FROM waiting), '[]'::jsonb))
        );
    END $$;

    -- 2. The Monthly report of one month (the first day of the month).
    CREATE FUNCTION app.problem_report_month(p_property uuid, p_actor uuid, p_month date)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.require_product_right(p_actor, 'problem_reports.plan', p_property);
        v_zone text;
        v_start timestamptz;
        v_end timestamptz;
        v_repeat_count integer;
        v_repeat_days integer;
    BEGIN
        IF p_month IS NULL OR extract(day FROM p_month) <> 1 OR p_month > v_day
            OR p_month < date '2026-01-01' THEN
            RAISE EXCEPTION 'Choose a month up to this month' USING ERRCODE = '22023';
        END IF;
        SELECT property.timezone_name INTO v_zone FROM app.properties AS property
        WHERE property.id = p_property;
        v_start := p_month::timestamp AT TIME ZONE v_zone;
        v_end := (p_month + interval '1 month')::timestamp AT TIME ZONE v_zone;
        v_repeat_count := COALESCE(app.business_rule_value('REPEAT_COUNT', v_day), 3)::integer;
        v_repeat_days := COALESCE(app.business_rule_value('REPEAT_DAYS', v_day), 90)::integer;
        RETURN (
            WITH received AS (
                SELECT report.*, app.problem_report_state(report.id) AS state
                FROM app.problem_reports AS report
                WHERE report.property_id = p_property
                  AND report.created_at >= v_start AND report.created_at < v_end
            ), counted AS (
                SELECT * FROM received WHERE received.status <> 'JOINED'
            ), done AS (
                SELECT report.*, cost.*
                FROM app.problem_reports AS report
                CROSS JOIN LATERAL app.problem_report_cost_parts(report.id) AS cost
                WHERE report.property_id = p_property
                  AND report.done_at >= v_start AND report.done_at < v_end
            ), urgent AS (
                SELECT counted.id, counted.contacted_at <= counted.created_at + make_interval(
                    hours => COALESCE(app.business_rule_value('TR_URGENT_HOURS', v_day), 1)::integer)
                    AS on_time
                FROM counted WHERE counted.urgent
            ), normal AS (
                SELECT counted.id, (
                    SELECT min(event.occurred_at) FROM app.problem_report_events AS event
                    WHERE event.report_id = counted.id
                      AND event.step IN ('PLANNED', 'REPAIR_JOB', 'CLEANING', 'NOT_ACCEPTED',
                          'CLOSED_NOTE')
                    ) <= (app.add_working_days(timezone(v_zone, counted.created_at)::date,
                            COALESCE(app.business_rule_value('TR_PLAN_WORKDAYS', v_day), 1)::integer)
                          + timezone(v_zone, counted.created_at)::time) AT TIME ZONE v_zone
                    AS on_time
                FROM counted WHERE NOT counted.urgent
            ), places AS (
                SELECT counted.kind, unit.unit_number, shared.code AS place_code,
                    shared.name_en AS place_en, shared.name_kh AS place_kh, count(*) AS reports
                FROM counted
                LEFT JOIN app.units AS unit ON unit.id = counted.unit_id
                LEFT JOIN app.problem_places AS shared ON shared.id = counted.problem_place_id
                GROUP BY counted.kind, unit.unit_number, shared.code, shared.name_en, shared.name_kh
            ), repeats AS (
                SELECT unit.unit_number, kind.code, kind.name_en, kind.name_kh, kind.icon,
                    count(*) AS reports,
                    jsonb_agg(jsonb_build_object('report_id', report.id,
                        'report_number', report.report_number) ORDER BY report.created_at) AS found
                FROM app.problem_reports AS report
                JOIN app.units AS unit ON unit.id = report.unit_id
                JOIN app.problem_types AS kind ON kind.id = report.problem_type_id
                WHERE report.property_id = p_property AND report.kind = 'UNIT'
                  AND report.status <> 'JOINED' AND report.created_at < v_end
                  AND report.created_at >= v_end - make_interval(days => v_repeat_days)
                GROUP BY unit.unit_number, kind.code, kind.name_en, kind.name_kh, kind.icon
                HAVING count(*) >= v_repeat_count
                   AND bool_or(report.created_at >= v_start)
            )
            SELECT jsonb_build_object(
                'month', p_month,
                'received', (SELECT count(*) FROM counted),
                'joined', (SELECT count(*) FROM received WHERE received.status = 'JOINED'),
                'unit_problems', (SELECT count(*) FROM counted WHERE counted.kind = 'UNIT'),
                'building_problems', (SELECT count(*) FROM counted WHERE counted.kind = 'BUILDING'),
                'urgent', (SELECT count(*) FROM urgent),
                'urgent_on_time', (SELECT count(*) FROM urgent WHERE urgent.on_time),
                'normal', (SELECT count(*) FROM normal),
                'normal_on_time', (SELECT count(*) FROM normal WHERE normal.on_time),
                'done', (SELECT count(*) FROM done WHERE done.status <> 'JOINED'),
                'average_days_to_fix', (SELECT round((avg(extract(epoch FROM done.done_at - done.created_at))
                        / 86400)::numeric, 1)
                    FROM done WHERE done.status <> 'JOINED'),
                'still_open', (SELECT count(*) FROM counted
                    WHERE counted.state NOT IN ('DONE', 'CLOSED', 'NOT_ACCEPTED')),
                'not_accepted', (SELECT count(*) FROM counted WHERE counted.state = 'NOT_ACCEPTED'),
                'opened_again', (SELECT count(*) FROM app.problem_report_events AS event
                    JOIN app.problem_reports AS report ON report.id = event.report_id
                    WHERE report.property_id = p_property AND event.step = 'NOT_FIXED'
                      AND event.occurred_at >= v_start AND event.occurred_at < v_end),
                'owner_pays', (SELECT count(*) FROM counted WHERE counted.pays = 'OWNER'),
                'tenant_pays', (SELECT count(*) FROM counted WHERE counted.pays = 'TENANT'),
                'damage_usd_cents', COALESCE((SELECT sum(charge.authorized_amount_usd_cents)
                    FROM app.authorized_nonrecurring_obligations AS charge
                    JOIN counted ON counted.id = charge.problem_report_id), 0),
                'by_type', COALESCE((
                    SELECT jsonb_agg(jsonb_build_object('code', kind.code, 'name_en', kind.name_en,
                            'name_kh', kind.name_kh, 'icon', kind.icon, 'reports', typed.reports)
                        ORDER BY typed.reports DESC, kind.sort_order)
                    FROM (SELECT counted.problem_type_id, count(*) AS reports FROM counted
                          GROUP BY counted.problem_type_id) AS typed
                    JOIN app.problem_types AS kind ON kind.id = typed.problem_type_id), '[]'::jsonb),
                'by_place', COALESCE((
                    SELECT jsonb_agg(jsonb_build_object('kind', places.kind,
                            'unit_number', places.unit_number, 'place_code', places.place_code,
                            'place_en', places.place_en, 'place_kh', places.place_kh,
                            'reports', places.reports)
                        ORDER BY places.reports DESC, places.kind DESC, places.unit_number,
                            places.place_code)
                    FROM places), '[]'::jsonb),
                'repeats', COALESCE((
                    SELECT jsonb_agg(jsonb_build_object('unit_number', repeats.unit_number,
                            'code', repeats.code, 'name_en', repeats.name_en,
                            'name_kh', repeats.name_kh, 'icon', repeats.icon,
                            'reports', repeats.reports, 'found', repeats.found)
                        ORDER BY repeats.reports DESC, repeats.unit_number)
                    FROM repeats), '[]'::jsonb),
                'late_now', COALESCE((
                    SELECT jsonb_agg(jsonb_build_object('report_id', late.id,
                            'report_number', late.report_number, 'late', late.late)
                        ORDER BY late.created_at)
                    FROM (SELECT report.id, report.report_number, report.created_at,
                              app.problem_report_late(report.id) AS late
                          FROM app.problem_reports AS report
                          WHERE report.property_id = p_property
                            AND report.status NOT IN ('DONE', 'CLOSED', 'NOT_ACCEPTED', 'JOINED'))
                        AS late
                    WHERE late.late IS NOT NULL), '[]'::jsonb),
                'cost_by_unit', COALESCE((
                    SELECT jsonb_agg(jsonb_build_object('unit_number', costs.unit_number,
                            'reports', costs.reports, 'parts_usd_cents', costs.parts_usd_cents,
                            'outside_usd_cents', costs.outside_usd_cents,
                            'parts_khr', costs.parts_khr, 'outside_khr', costs.outside_khr)
                        ORDER BY costs.unit_number NULLS LAST)
                    FROM (SELECT unit.unit_number, count(*) AS reports,
                              sum(done.parts_usd_cents)::bigint AS parts_usd_cents,
                              sum(done.outside_usd_cents)::bigint AS outside_usd_cents,
                              sum(done.parts_khr)::bigint AS parts_khr,
                              sum(done.outside_khr)::bigint AS outside_khr
                          FROM done LEFT JOIN app.units AS unit ON unit.id = done.unit_id
                          WHERE done.status <> 'JOINED'
                          GROUP BY unit.unit_number) AS costs), '[]'::jsonb),
                'cost_by_type', COALESCE((
                    SELECT jsonb_agg(jsonb_build_object('code', kind.code, 'name_en', kind.name_en,
                            'name_kh', kind.name_kh, 'icon', kind.icon, 'reports', costs.reports,
                            'parts_usd_cents', costs.parts_usd_cents,
                            'outside_usd_cents', costs.outside_usd_cents,
                            'parts_khr', costs.parts_khr, 'outside_khr', costs.outside_khr)
                        ORDER BY kind.sort_order)
                    FROM (SELECT done.problem_type_id, count(*) AS reports,
                              sum(done.parts_usd_cents)::bigint AS parts_usd_cents,
                              sum(done.outside_usd_cents)::bigint AS outside_usd_cents,
                              sum(done.parts_khr)::bigint AS parts_khr,
                              sum(done.outside_khr)::bigint AS outside_khr
                          FROM done WHERE done.status <> 'JOINED'
                          GROUP BY done.problem_type_id) AS costs
                    JOIN app.problem_types AS kind ON kind.id = costs.problem_type_id), '[]'::jsonb))
        );
    END $$;
"""

RUNTIME = (
    "app.problem_report_summary(uuid, uuid)",
    "app.problem_report_month(uuid, uuid, date)",
)


def upgrade() -> None:
    op.execute(FUNCTIONS)
    for signature in RUNTIME:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("The Problem report Monthly report migration is forward-only")
