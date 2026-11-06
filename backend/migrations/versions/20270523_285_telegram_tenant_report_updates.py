# ruff: noqa: E501
"""Telegram bots, step 2d part 1: the tenant hears each step of a report, checks the repair, and
sees My requests (DL-129).

Owner-approved tenant mock-up v15 (3 Nov 2026, "T1 - T5: all recommended") and the Tenant
requests design (round 29: "the tenant gets a Telegram message at each step"):

1. Each step of a Problem report the tenant made (by phone, at the desk or in the Tenant bot)
   queues a Telegram message in the person's language to every linked tenant of that Lease (and
   to the person who sent a Building problem from the bot). A report joined to another follows
   the main report's steps.
2. When the repair is done the tenant taps Fixed or Not fixed. Fixed closes the report; Not fixed
   opens it again with the same number. With no answer it closes by itself after
   TR_AUTO_CLOSE_DAYS (already in ``problem_report_state``).
3. My requests: the person's open reports and those closed in the last 30 days (at most 10).

Not here yet: the tenant's Agree when the tenant pays (TENANT_PAYS) and the urgent alert to the
caretaker on shift (needs the Staff bot). Technical choices by Claude under the owner's
2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270523_285"
down_revision: str | None = "20270522_284"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTIONS = """
    -- The Tenant bot people who hear about a report: each tenant linked now to its Lease, and the
    -- person who sent it from the bot while still linked. Only reports the tenant made.
    CREATE FUNCTION app.tenant_report_people(p_report uuid)
    RETURNS TABLE (telegram_user_id bigint, language text)
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        WITH report AS (
            SELECT found.* FROM app.problem_reports AS found
            WHERE found.id = p_report AND found.source IN ('PHONE', 'WALKIN', 'TENANT_BOT')
        ), people AS (
            SELECT link.telegram_user_id
            FROM report
            JOIN app.tenant_telegram_links AS link
                ON link.lease_id = report.lease_id AND link.property_id = report.property_id
            WHERE (app.tenant_active_link(report.property_id, link.telegram_user_id)).lease_id
                = report.lease_id
            UNION
            SELECT source.telegram_user_id
            FROM report
            JOIN app.tenant_problem_report_sources AS source ON source.report_id = report.id
            WHERE (app.tenant_active_link(report.property_id, source.telegram_user_id)).id
                IS NOT NULL
        )
        SELECT people.telegram_user_id,
            COALESCE((SELECT choice.language FROM app.telegram_language_choices AS choice
                      WHERE choice.bot_code = 'TENANT'
                        AND choice.telegram_user_id = people.telegram_user_id
                      ORDER BY choice.chosen_at DESC LIMIT 1), 'km')
        FROM people
    $$;

    -- 1. Each step of a report queues the tenant's message. A step the tenant took in the bot
    -- (details.via = TELEGRAM) is answered by the bot itself.
    CREATE FUNCTION app.telegram_tenant_report_notice() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_report app.problem_reports%ROWTYPE;
        v_code text;
        v_keyboard text := 'tenant.menu';
        v_details jsonb;
        v_person record;
    BEGIN
        IF NEW.details ->> 'via' = 'TELEGRAM' THEN
            RETURN NULL;
        END IF;
        SELECT report.* INTO v_report FROM app.problem_reports AS report
        WHERE report.id = NEW.report_id;
        IF NOT FOUND OR v_report.source NOT IN ('PHONE', 'WALKIN', 'TENANT_BOT') THEN
            RETURN NULL;
        END IF;
        v_code := CASE NEW.step
            WHEN 'RECEIVED' THEN
                CASE WHEN v_report.source IN ('PHONE', 'WALKIN') THEN 'tenant.step_received' END
            WHEN 'CONTACTED' THEN
                CASE WHEN NEW.details ->> 'how' = 'VISIT' THEN 'tenant.step_on_way' END
            WHEN 'PLANNED' THEN 'tenant.step_planned'
            WHEN 'REPLANNED' THEN 'tenant.step_planned'
            WHEN 'CHECKED' THEN
                CASE WHEN NEW.details ->> 'fixed' = 'true' THEN 'tenant.step_checked_fixed'
                     ELSE 'tenant.step_checked' END
            WHEN 'OWNER_PAYS' THEN
                CASE WHEN v_report.status = 'DONE' THEN 'done' ELSE 'tenant.step_owner_pays' END
            WHEN 'WAITING_PARTS' THEN 'tenant.step_parts'
            WHEN 'PARTS_ARRIVED' THEN 'tenant.step_parts_arrived'
            WHEN 'DONE' THEN 'done'
            WHEN 'REPAIR_JOB' THEN 'tenant.step_repair_job'
            WHEN 'CLEANING' THEN 'tenant.step_cleaning'
            WHEN 'CLOSED_NOTE' THEN 'tenant.step_handled'
            WHEN 'NOT_ACCEPTED' THEN 'tenant.step_not_accepted'
            WHEN 'MANAGER_CLOSED' THEN 'tenant.step_closed'
            WHEN 'FIXED' THEN 'tenant.step_closed'
            WHEN 'NOT_FIXED' THEN 'tenant.step_reopened'
            -- "Same problem" picked in the bot is answered by the bot.
            WHEN 'JOINED' THEN
                CASE WHEN NEW.note IS DISTINCT FROM
                    'Same problem (picked by the tenant in Telegram)' THEN 'tenant.step_joined' END
        END;
        IF v_code IS NULL THEN
            RETURN NULL;
        END IF;
        v_details := jsonb_build_object('number', v_report.report_number,
            'technician', COALESCE(v_report.technician, ''),
            'day', COALESCE(to_char(v_report.visit_on, 'DD/MM/YYYY'), ''),
            'time', COALESCE(to_char(v_report.visit_at, 'HH24:MI'), ''),
            'main', COALESCE(NEW.details ->> 'main_number', ''));
        IF v_code = 'done' THEN
            IF v_report.kind = 'UNIT' AND v_report.customer_id IS NOT NULL THEN
                v_code := 'tenant.step_done_check';
                v_keyboard := 'tenant.check';
                v_details := v_details || jsonb_build_object('days', COALESCE(
                    app.business_rule_value('TR_AUTO_CLOSE_DAYS', app.gl_today(v_report.property_id)),
                    3)::integer);
            ELSE
                v_code := 'tenant.step_done';
            END IF;
        END IF;
        FOR v_person IN
            SELECT DISTINCT ON (people.telegram_user_id) people.telegram_user_id, people.language
            FROM (
                SELECT own.telegram_user_id, own.language
                FROM app.tenant_report_people(v_report.id) AS own
                UNION ALL
                -- Reports joined to this one follow its steps.
                SELECT kid_people.telegram_user_id, kid_people.language
                FROM app.problem_reports AS kid
                CROSS JOIN LATERAL app.tenant_report_people(kid.id) AS kid_people
                WHERE kid.joined_to_id = v_report.id AND kid.status = 'JOINED'
                  AND NEW.step NOT IN ('RECEIVED', 'JOINED')
            ) AS people
            ORDER BY people.telegram_user_id
        LOOP
            INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code, language,
                details, keyboard, created_by)
            VALUES (v_report.property_id, 'TENANT', v_person.telegram_user_id, v_code,
                v_person.language, v_details, v_keyboard, NEW.actor_id);
        END LOOP;
        RETURN NULL;
    END $$;

    CREATE TRIGGER problem_report_events_tenant_notice AFTER INSERT ON app.problem_report_events
        FOR EACH ROW EXECUTE FUNCTION app.telegram_tenant_report_notice();

    -- 2. The tenant taps Fixed or Not fixed: the newest done Unit Problem on the person's Lease.
    CREATE FUNCTION app.telegram_tenant_report_check(p_property uuid, p_user bigint,
        p_fixed boolean, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_link app.tenant_telegram_links%ROWTYPE;
        v_report app.problem_reports%ROWTYPE;
        v_note text;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        IF p_user IS NULL OR p_user <= 0 OR p_fixed IS NULL THEN
            RAISE EXCEPTION 'the answer is not valid' USING ERRCODE = '22023';
        END IF;
        v_link := app.tenant_active_link(p_property, p_user);
        IF v_link.id IS NULL THEN
            RETURN jsonb_build_object('result', 'NOT_LINKED');
        END IF;
        SELECT report.* INTO v_report FROM app.problem_reports AS report
        WHERE report.property_id = p_property AND report.lease_id = v_link.lease_id
          AND report.kind = 'UNIT' AND report.customer_id IS NOT NULL
          AND report.source IN ('PHONE', 'WALKIN', 'TENANT_BOT')
          AND app.problem_report_state(report.id) = 'DONE'
        ORDER BY report.done_at DESC
        LIMIT 1
        FOR UPDATE;
        IF NOT FOUND THEN
            RETURN jsonb_build_object('result', 'NOTHING');
        END IF;
        IF p_fixed THEN
            v_note := 'The tenant tapped Fixed in Telegram';
            UPDATE app.problem_reports SET status = 'CLOSED', closed_at = statement_timestamp(),
                version = version + 1 WHERE id = v_report.id;
        ELSE
            v_note := 'The tenant tapped Not fixed in Telegram';
            UPDATE app.problem_reports SET status = 'REPAIR_PLANNED', done_at = NULL,
                version = version + 1 WHERE id = v_report.id;
        END IF;
        PERFORM app.problem_report_event(v_report.id,
            CASE WHEN p_fixed THEN 'FIXED' ELSE 'NOT_FIXED' END, v_note,
            jsonb_build_object('via', 'TELEGRAM', 'telegram_user_id', p_user), p_actor);
        PERFORM app.product_audit(p_property, p_actor, app.gl_today(p_property),
            'problem_report.step', 'problem_report', v_report.id, v_note, 'telegram.operate',
            jsonb_build_object('status', 'DONE'),
            jsonb_build_object('step', CASE WHEN p_fixed THEN 'TENANT_FIXED'
                                            ELSE 'TENANT_NOT_FIXED' END),
            NULL);
        RETURN jsonb_build_object('result', CASE WHEN p_fixed THEN 'CLOSED' ELSE 'REOPENED' END,
            'report_number', v_report.report_number,
            'technician', COALESCE(v_report.technician, ''));
    END $$;

    -- 3. My requests: open reports, and those closed in the last 30 days (at most 10).
    CREATE FUNCTION app.telegram_tenant_my_reports(p_property uuid, p_user bigint, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_link app.tenant_telegram_links%ROWTYPE;
        v_day date;
        v_reports jsonb;
        v_unit text;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        v_link := app.tenant_active_link(p_property, p_user);
        IF v_link.id IS NULL THEN
            RETURN jsonb_build_object('result', 'NOT_LINKED');
        END IF;
        v_day := app.gl_today(p_property);
        SELECT unit.unit_number INTO v_unit FROM app.units AS unit WHERE unit.id = v_link.unit_id;
        SELECT COALESCE(jsonb_agg(mine.body ORDER BY mine.created_at DESC), '[]'::jsonb)
        INTO v_reports
        FROM (
            SELECT report.created_at, jsonb_build_object(
                'report_number', report.report_number, 'kind', report.kind,
                'state', listed.state, 'type_en', kind.name_en, 'type_kh', kind.name_kh,
                'main_number', main.report_number,
                'technician', CASE WHEN listed.state IN ('PLANNED', 'REPAIR_PLANNED')
                    AND report.visit_on >= v_day THEN report.technician END,
                'visit_on', CASE WHEN listed.state IN ('PLANNED', 'REPAIR_PLANNED')
                    AND report.visit_on >= v_day THEN to_char(report.visit_on, 'DD/MM/YYYY') END,
                'visit_at', CASE WHEN listed.state IN ('PLANNED', 'REPAIR_PLANNED')
                    AND report.visit_on >= v_day THEN to_char(report.visit_at, 'HH24:MI') END)
                AS body
            FROM app.problem_reports AS report
            CROSS JOIN LATERAL (SELECT app.problem_report_state(report.id) AS state) AS listed
            JOIN app.problem_types AS kind ON kind.id = report.problem_type_id
            LEFT JOIN app.problem_reports AS main ON main.id = report.joined_to_id
            WHERE report.property_id = p_property
              AND report.source IN ('PHONE', 'WALKIN', 'TENANT_BOT')
              AND (report.lease_id = v_link.lease_id
                   OR EXISTS (SELECT 1 FROM app.tenant_problem_report_sources AS source
                              WHERE source.report_id = report.id
                                AND source.telegram_user_id = p_user))
              AND (listed.state NOT IN ('CLOSED', 'NOT_ACCEPTED')
                   OR COALESCE(report.closed_at, report.done_at, report.created_at)
                       > statement_timestamp() - interval '30 days')
            ORDER BY report.created_at DESC
            LIMIT 10
        ) AS mine;
        RETURN jsonb_build_object('result', 'OK', 'unit_number', v_unit, 'reports', v_reports);
    END $$;
"""

JOB_FUNCTIONS = (
    "app.telegram_tenant_report_check(uuid, bigint, boolean, uuid)",
    "app.telegram_tenant_my_reports(uuid, bigint, uuid)",
)


def upgrade() -> None:
    op.execute(FUNCTIONS)
    op.execute("REVOKE ALL ON FUNCTION app.tenant_report_people(uuid) FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION app.telegram_tenant_report_notice() FROM PUBLIC")
    for signature in JOB_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("the Tenant bot report updates migration is forward-only")
