# ruff: noqa: E501
"""Telegram bots, step 4b: staff report a problem, the Technician closes a job, and the urgent alert (DL-175).

Owner rules (3 Nov 2026, staff forms mock-up v14 and Problem report Part B, approved 11:22):

1. Report a problem (walk-round): every linked staff member picks Unit Problem or Building
   problem, the Unit or the place (and floor), taps the problem type picture, takes at least one
   photo and writes what is wrong or sends a voice note. A Building problem shows the open
   reports at that place: "Same problem" joins it (DL-124). The report goes into the one Problem
   reports list with source STAFF_BOT. Safety, flooding and electric shock are always urgent. The
   tenant of the Unit is told only when the Manager plans a visit.
2. Close job: the Technician picks a planned repair, takes the after photo (required) and says
   the cost: No cost, or parts and paid outside workers in dollars with a receipt photo
   (required). Our own staff time is not added (it is in payroll). The repair is Done; the cost
   waits for the Manager's check (DL-130), which makes the Expense report.
3. The urgent alert: when an urgent report is saved (from any place), the caretaker on shift and
   the Authorizers (the Owner and the Manager on the Staff bot) hear it at once in the Staff bot.
   A report joined to an open one at once is not sent again; the person who sent it is not told.

Tables: ``staff_problem_report_sources`` (which Staff form made which report) and
``staff_job_closures`` (which Staff form closed which job), both append-only. The report photos
also take the stages DONE (after the repair) and RECEIPT. Technical choices by Claude under the
owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270621_332"
down_revision: str | None = "20270620_331"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = """
    ALTER TABLE app.problem_report_media DROP CONSTRAINT problem_report_media_stage_check;
    ALTER TABLE app.problem_report_media ADD CONSTRAINT problem_report_media_stage_check
        CHECK (stage IN ('REPORTED', 'DONE', 'RECEIPT'));

    CREATE TABLE app.staff_problem_report_sources (
        report_id uuid PRIMARY KEY REFERENCES app.problem_reports (id) ON DELETE RESTRICT,
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        inbound_event_id uuid NOT NULL UNIQUE
            REFERENCES app.telegram_inbound_events (id) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    COMMENT ON TABLE app.staff_problem_report_sources IS
        'Telegram bots step 4b (DL-175): the Staff bot form that made a Problem report.';

    CREATE TABLE app.staff_job_closures (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        report_id uuid NOT NULL REFERENCES app.problem_reports (id) ON DELETE RESTRICT,
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        inbound_event_id uuid NOT NULL UNIQUE
            REFERENCES app.telegram_inbound_events (id) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        cost_set_id uuid NOT NULL UNIQUE
            REFERENCES app.problem_report_cost_sets (id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX staff_job_closures_report_idx ON app.staff_job_closures (report_id);
    COMMENT ON TABLE app.staff_job_closures IS
        'Telegram bots step 4b (DL-175): a repair closed by the Technician in the Staff bot.';

    CREATE TRIGGER staff_problem_report_sources_append_only BEFORE UPDATE OR DELETE
        ON app.staff_problem_report_sources
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER staff_problem_report_sources_no_truncate BEFORE TRUNCATE
        ON app.staff_problem_report_sources
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER staff_job_closures_append_only BEFORE UPDATE OR DELETE
        ON app.staff_job_closures
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER staff_job_closures_no_truncate BEFORE TRUNCATE ON app.staff_job_closures
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
"""

FUNCTIONS = """
    -- The linked staff member who sent a form: the employee, their name and report roles.
    CREATE FUNCTION app.telegram_staff_sender(p_property uuid, p_user bigint)
    RETURNS TABLE (employee_id uuid, name text, roles text[]) ROWS 1
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT employee.id, left(COALESCE(NULLIF(employee.name_km, ''), employee.name_en), 120),
            array_agg(DISTINCT link.report_role ORDER BY link.report_role)
        FROM app.employee_telegram_links AS link
        JOIN app.employees AS employee ON employee.id = link.employee_id
        WHERE link.telegram_user_id = p_user AND employee.property_id = p_property
          AND app.hr_link_live(link.id, timezone(app.hr_zone(), statement_timestamp())::date)
        GROUP BY employee.id, employee.name_km, employee.name_en
        ORDER BY employee.id
        LIMIT 1
    $$;

    -- The open repairs a Technician can close (Repair planned), with what the form shows: the
    -- urgent ones first, then the oldest, at most 12 (the relay keeps 8 KB per person).
    CREATE FUNCTION app.telegram_staff_jobs(p_property uuid) RETURNS jsonb
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT COALESCE(jsonb_agg(job.body ORDER BY job.urgent DESC, job.created_at), '[]'::jsonb)
        FROM (
            SELECT report.urgent, report.created_at, jsonb_build_object('report_id', report.id,
                'report_number', report.report_number, 'kind', report.kind,
                'unit', unit.unit_number, 'place_km', place.name_kh, 'floor', report.floor_label,
                'type_km', kind.name_kh, 'icon', kind.icon, 'urgent', report.urgent,
                'description', left(report.description, 100)) AS body
            FROM app.problem_reports AS report
            JOIN app.problem_types AS kind ON kind.id = report.problem_type_id
            LEFT JOIN app.units AS unit ON unit.id = report.unit_id
            LEFT JOIN app.problem_places AS place ON place.id = report.problem_place_id
            WHERE report.property_id = p_property
              AND app.problem_report_state(report.id) = 'REPAIR_PLANNED'
            ORDER BY report.urgent DESC, report.created_at
            LIMIT 12
        ) AS job
    $$;

    -- Who may open the Staff forms and what they show (replaces step 4a's list): each linked
    -- person with their name, roles and shift, and for a Technician the open repairs; the
    -- choices add the Units for Report a problem.
    CREATE OR REPLACE FUNCTION app.telegram_staff_form_data(p_property uuid, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_today date;
        v_users jsonb;
        v_jobs jsonb;
        v_choices jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT timezone(property.timezone_name, statement_timestamp())::date INTO v_today
        FROM app.properties AS property WHERE property.id = p_property;
        v_jobs := app.telegram_staff_jobs(p_property);
        SELECT coalesce(jsonb_agg(jsonb_build_object('id', person.telegram_user_id,
                'role', 'STAFF', 'data', jsonb_build_object('name_km', person.name_km,
                    'name_en', person.name_en, 'roles', person.roles,
                    'shift_code', person.shift_code, 'shift_km', person.shift_km)
                    || CASE WHEN person.roles ? 'TECHNICIAN'
                        THEN jsonb_build_object('jobs', v_jobs) ELSE '{}'::jsonb END)
                ORDER BY person.telegram_user_id), '[]'::jsonb)
        INTO v_users
        FROM (
            SELECT link.telegram_user_id, employee.name_km, employee.name_en,
                jsonb_agg(DISTINCT link.report_role) AS roles, job.shift_code,
                (SELECT shift.name_km FROM app.work_shifts AS shift
                 WHERE shift.code = job.shift_code) AS shift_km
            FROM app.employee_telegram_links AS link
            JOIN app.employees AS employee ON employee.id = link.employee_id
            LEFT JOIN LATERAL app.hr_job_on(employee.id, v_today) AS job ON true
            WHERE employee.property_id = p_property AND app.hr_link_live(link.id, v_today)
            GROUP BY link.telegram_user_id, employee.id, employee.name_km, employee.name_en,
                job.shift_code
        ) AS person;
        -- Report a problem uses the same types, places and open Building problems as the Tenant
        -- bot, and any Unit of the Property (Unit numbers only).
        v_choices := (app.telegram_tenant_form_data(p_property, p_actor) -> 'choices')
            || jsonb_build_object('units', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'id', unit.id, 'number', unit.unit_number) ORDER BY unit.unit_number)
                FROM app.units AS unit WHERE unit.property_id = p_property), '[]'::jsonb));
        RETURN jsonb_build_object('users', v_users, 'choices', v_choices);
    END $$;

    -- A refused staff form: the bot answers in a fixed word, nothing is saved.
    CREATE FUNCTION app.staff_form_refused(p_reason text) RETURNS jsonb
    LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT jsonb_build_object('result', 'INVALID', 'reason', p_reason)
    $$;

    -- The files a form brought, checked: each a saved media file, in the order sent.
    CREATE FUNCTION app.staff_form_files(p_media jsonb) RETURNS SETOF app.media_files
    LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
    DECLARE
        v_media jsonb;
        v_file app.media_files%ROWTYPE;
    BEGIN
        IF p_media IS NULL OR jsonb_typeof(p_media) <> 'array' THEN
            RAISE EXCEPTION 'files' USING ERRCODE = '22023';
        END IF;
        FOR v_media IN SELECT value FROM jsonb_array_elements(p_media) WITH ORDINALITY ORDER BY ordinality LOOP
            BEGIN
                SELECT file.* INTO v_file FROM app.media_files AS file
                WHERE file.id = (v_media #>> '{}')::uuid;
            EXCEPTION WHEN data_exception THEN
                RAISE EXCEPTION 'files' USING ERRCODE = '22023';
            END;
            IF v_file.id IS NULL THEN
                RAISE EXCEPTION 'files' USING ERRCODE = '22023';
            END IF;
            RETURN NEXT v_file;
        END LOOP;
    END $$;

    -- Keep one file with a report at a stage, at the next free place (the same file once).
    CREATE FUNCTION app.staff_keep_report_file(p_report uuid, p_file app.media_files,
        p_stage text, p_actor uuid) RETURNS void
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    BEGIN
        IF EXISTS (SELECT 1 FROM app.problem_report_media AS kept
                   WHERE kept.report_id = p_report AND kept.media_file_id = p_file.id) THEN
            RETURN;
        END IF;
        INSERT INTO app.problem_report_media (report_id, media_file_id, kind, stage, position,
            added_by)
        SELECT p_report, p_file.id,
            CASE WHEN p_file.content_type LIKE 'audio/%' THEN 'VOICE'
                 WHEN p_file.content_type LIKE 'video/%' THEN 'VIDEO' ELSE 'PHOTO' END,
            p_stage, COALESCE(max(kept.position), 0) + 1, p_actor
        FROM app.problem_report_media AS kept
        WHERE kept.report_id = p_report AND kept.stage = p_stage;
    END $$;

    -- 1. Report a problem from the Staff forms (the pulled item ``p_inbound``). The same form
    -- twice gives the same report.
    CREATE FUNCTION app.telegram_staff_problem_report(p_property uuid, p_inbound uuid,
        p_form jsonb, p_media jsonb, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date;
        v_event app.telegram_inbound_events%ROWTYPE;
        v_user bigint;
        v_sender record;
        v_source app.staff_problem_report_sources%ROWTYPE;
        v_main app.problem_reports%ROWTYPE;
        v_kind text;
        v_type app.problem_types%ROWTYPE;
        v_unit uuid;
        v_place uuid;
        v_floor text;
        v_same uuid;
        v_text text;
        v_file app.media_files%ROWTYPE;
        v_files app.media_files[] := '{}';
        v_photos integer := 0;
        v_voice boolean := false;
        v_lease uuid;
        v_customer uuid;
        v_id uuid := gen_random_uuid();
        v_number text;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        v_day := app.gl_today(p_property);
        SELECT event.* INTO v_event FROM app.telegram_inbound_events AS event
        WHERE event.id = p_inbound AND event.property_id = p_property
          AND event.bot_code = 'STAFF' AND event.kind = 'form';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the form does not exist' USING ERRCODE = '22023';
        END IF;
        SELECT source.* INTO v_source FROM app.staff_problem_report_sources AS source
        WHERE source.inbound_event_id = p_inbound;
        IF FOUND THEN
            SELECT report.* INTO v_main FROM app.problem_reports AS report
            WHERE report.id = v_source.report_id;
            RETURN jsonb_build_object('result', 'ADDED', 'repeated', true,
                'report_number', v_main.report_number, 'kind', v_main.kind,
                'urgent', v_main.urgent);
        END IF;
        SELECT account.telegram_user_id INTO v_user FROM app.telegram_accounts AS account
        WHERE account.id = v_event.account_id;
        SELECT sender.* INTO v_sender FROM app.telegram_staff_sender(p_property, v_user) AS sender;
        IF v_user IS NULL OR v_sender.employee_id IS NULL THEN
            RETURN jsonb_build_object('result', 'NOT_LINKED');
        END IF;
        IF p_form IS NULL OR jsonb_typeof(p_form) <> 'object' THEN
            RETURN app.staff_form_refused('not_a_form');
        END IF;
        v_kind := p_form ->> 'kind';
        IF v_kind IS NULL OR v_kind NOT IN ('UNIT', 'BUILDING') THEN
            RETURN app.staff_form_refused('kind');
        END IF;
        BEGIN
            SELECT kind.* INTO v_type FROM app.problem_types AS kind
            WHERE kind.id = (p_form ->> 'problem_type_id')::uuid AND kind.active;
            v_unit := (p_form ->> 'unit_id')::uuid;
            v_place := (p_form ->> 'problem_place_id')::uuid;
            v_same := (p_form ->> 'same_as')::uuid;
        EXCEPTION WHEN data_exception THEN
            RETURN app.staff_form_refused('not_a_form');
        END;
        IF v_type.id IS NULL THEN
            RETURN app.staff_form_refused('problem_type');
        END IF;
        IF p_form ? 'description' AND jsonb_typeof(p_form -> 'description') NOT IN ('string', 'null') THEN
            RETURN app.staff_form_refused('description');
        END IF;
        v_text := NULLIF(btrim(p_form ->> 'description'), '');
        IF v_text IS NOT NULL AND length(v_text) > 1000 THEN
            RETURN app.staff_form_refused('description');
        END IF;
        -- At least one photo (up to 4) and at most one voice note of up to 1 minute.
        BEGIN
            FOR v_file IN SELECT * FROM app.staff_form_files(p_media) LOOP
                IF v_file.content_type LIKE 'audio/%' THEN
                    IF v_voice OR COALESCE(v_file.duration_seconds, 0) > 60 THEN
                        RETURN app.staff_form_refused('files');
                    END IF;
                    v_voice := true;
                ELSIF v_file.content_type LIKE 'image/%' THEN
                    v_photos := v_photos + 1;
                ELSE
                    RETURN app.staff_form_refused('files');
                END IF;
                v_files := v_files || v_file;
            END LOOP;
        EXCEPTION WHEN invalid_parameter_value THEN
            RETURN app.staff_form_refused('files');
        END;
        IF v_photos NOT BETWEEN 1 AND 4 THEN
            RETURN app.staff_form_refused('photo');
        END IF;
        IF v_text IS NULL AND NOT v_voice AND (v_kind = 'UNIT' OR v_same IS NULL) THEN
            RETURN app.staff_form_refused('say_what');
        END IF;
        IF v_kind = 'UNIT' THEN
            IF v_place IS NOT NULL OR v_same IS NOT NULL OR p_form ? 'floor'
                AND jsonb_typeof(p_form -> 'floor') <> 'null' THEN
                RETURN app.staff_form_refused('place');
            END IF;
            IF v_unit IS NULL OR NOT EXISTS (SELECT 1 FROM app.units AS unit
                    WHERE unit.id = v_unit AND unit.property_id = p_property) THEN
                RETURN app.staff_form_refused('unit');
            END IF;
            SELECT current.lease_id, current.customer_id INTO v_lease, v_customer
            FROM app.problem_unit_lease(v_unit, v_day) AS current;
        ELSE
            IF v_unit IS NOT NULL THEN
                RETURN app.staff_form_refused('place');
            END IF;
            IF v_place IS NULL OR NOT EXISTS (SELECT 1 FROM app.problem_places AS place
                    WHERE place.id = v_place AND place.active) THEN
                RETURN app.staff_form_refused('place');
            END IF;
            IF p_form ? 'floor' AND jsonb_typeof(p_form -> 'floor') NOT IN ('string', 'null') THEN
                RETURN app.staff_form_refused('floor');
            END IF;
            v_floor := NULLIF(btrim(p_form ->> 'floor'), '');
            IF v_floor IS NOT NULL AND length(v_floor) > 20 THEN
                RETURN app.staff_form_refused('floor');
            END IF;
            IF v_same IS NOT NULL THEN
                SELECT report.* INTO v_main FROM app.problem_reports AS report
                WHERE report.id = v_same AND report.property_id = p_property
                  AND report.kind = 'BUILDING' AND report.problem_place_id = v_place
                FOR UPDATE;
                -- Closed since the form opened: this one is a new report.
                IF v_main.id IS NULL OR app.problem_report_state(v_main.id)
                        IN ('DONE', 'CLOSED', 'NOT_ACCEPTED', 'JOINED') THEN
                    v_same := NULL;
                    v_main := NULL;
                    IF v_text IS NULL AND NOT v_voice THEN
                        RETURN app.staff_form_refused('say_what');
                    END IF;
                END IF;
            END IF;
        END IF;
        v_number := app.take_document_number(
            CASE v_kind WHEN 'UNIT' THEN 'UNIT_PROBLEM' ELSE 'BUILDING_PROBLEM' END,
            date_part('year', v_day)::integer);
        INSERT INTO app.problem_reports (id, property_id, report_number, kind, unit_id, lease_id,
            customer_id, problem_place_id, floor_label, problem_type_id, description, urgent,
            always_urgent, may_enter, best_time, source, reported_by, created_by)
        VALUES (v_id, p_property, v_number, v_kind, v_unit, v_lease, v_customer, v_place,
            v_floor, v_type.id, COALESCE(v_text, CASE WHEN v_voice THEN 'Voice note only'
                ELSE 'Same problem as ' || v_main.report_number END),
            v_type.always_urgent, v_type.always_urgent, false, 'ANY', 'STAFF_BOT',
            v_sender.name, p_actor);
        PERFORM app.problem_report_event(v_id, 'RECEIVED', NULL,
            jsonb_build_object('source', 'STAFF_BOT', 'photos', v_photos, 'voice', v_voice),
            p_actor);
        FOREACH v_file IN ARRAY v_files LOOP
            PERFORM app.staff_keep_report_file(v_id, v_file, 'REPORTED', p_actor);
        END LOOP;
        INSERT INTO app.staff_problem_report_sources (report_id, property_id, inbound_event_id,
            telegram_user_id, employee_id, created_by)
        VALUES (v_id, p_property, p_inbound, v_user, v_sender.employee_id, p_actor);
        IF v_same IS NOT NULL THEN
            PERFORM 1 FROM app.problem_reports AS report WHERE report.id = v_id FOR UPDATE;
            PERFORM app.problem_report_join_to(v_id, v_same,
                'Same problem (picked by staff in Telegram)', p_actor);
        END IF;
        PERFORM app.product_audit(p_property, p_actor, v_day, 'problem_report.added',
            'problem_report', v_id, 'Problem report from the Staff bot', 'telegram.operate',
            NULL, jsonb_build_object('report_number', v_number, 'kind', v_kind,
                'source', 'STAFF_BOT', 'same_as', v_same), NULL);
        RETURN jsonb_build_object('result', 'ADDED', 'repeated', false,
            'report_number', v_number, 'kind', v_kind, 'urgent', v_type.always_urgent,
            'joined_to', CASE WHEN v_same IS NOT NULL THEN v_main.report_number END);
    END $$;

    -- 2. Close job: the Technician's after photo and cost for a planned repair. The repair is
    -- Done; the cost waits for the Manager's check. The same form twice closes it once.
    CREATE FUNCTION app.telegram_staff_close_job(p_property uuid, p_inbound uuid,
        p_form jsonb, p_media jsonb, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date;
        v_event app.telegram_inbound_events%ROWTYPE;
        v_user bigint;
        v_sender record;
        v_closed app.staff_job_closures%ROWTYPE;
        v_report app.problem_reports%ROWTYPE;
        v_report_id uuid;
        v_after numeric;
        v_cost text;
        v_parts numeric;
        v_outside numeric;
        v_lines jsonb := '[]'::jsonb;
        v_file app.media_files%ROWTYPE;
        v_files app.media_files[] := '{}';
        v_count integer := 0;
        v_version integer;
        v_set uuid;
        v_note text;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        v_day := app.gl_today(p_property);
        SELECT event.* INTO v_event FROM app.telegram_inbound_events AS event
        WHERE event.id = p_inbound AND event.property_id = p_property
          AND event.bot_code = 'STAFF' AND event.kind = 'form';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the form does not exist' USING ERRCODE = '22023';
        END IF;
        SELECT closed.* INTO v_closed FROM app.staff_job_closures AS closed
        WHERE closed.inbound_event_id = p_inbound;
        IF FOUND THEN
            RETURN jsonb_build_object('result', 'DONE', 'repeated', true,
                'report_number', (SELECT report.report_number FROM app.problem_reports AS report
                                  WHERE report.id = v_closed.report_id));
        END IF;
        SELECT account.telegram_user_id INTO v_user FROM app.telegram_accounts AS account
        WHERE account.id = v_event.account_id;
        SELECT sender.* INTO v_sender FROM app.telegram_staff_sender(p_property, v_user) AS sender;
        IF v_user IS NULL OR v_sender.employee_id IS NULL THEN
            RETURN jsonb_build_object('result', 'NOT_LINKED');
        END IF;
        IF NOT 'TECHNICIAN' = ANY (v_sender.roles) THEN
            RETURN jsonb_build_object('result', 'NOT_TECHNICIAN');
        END IF;
        IF p_form IS NULL OR jsonb_typeof(p_form) <> 'object' THEN
            RETURN app.staff_form_refused('not_a_form');
        END IF;
        BEGIN
            v_report_id := (p_form ->> 'report_id')::uuid;
        EXCEPTION WHEN data_exception THEN
            RETURN app.staff_form_refused('not_a_form');
        END;
        IF jsonb_typeof(p_form -> 'after_photos') IS DISTINCT FROM 'number' THEN
            RETURN app.staff_form_refused('after_photo');
        END IF;
        v_after := (p_form ->> 'after_photos')::numeric;
        v_cost := p_form ->> 'cost';
        IF v_cost IS NULL OR v_cost NOT IN ('NONE', 'PAID') THEN
            RETURN app.staff_form_refused('cost');
        END IF;
        -- Dollars as whole cents: parts and paid outside workers, at least one above zero.
        IF v_cost = 'PAID' THEN
            IF jsonb_typeof(COALESCE(p_form -> 'parts_usd_cents', '0'::jsonb)) <> 'number'
                OR jsonb_typeof(COALESCE(p_form -> 'outside_usd_cents', '0'::jsonb)) <> 'number' THEN
                RETURN app.staff_form_refused('cost');
            END IF;
            v_parts := COALESCE((p_form ->> 'parts_usd_cents')::numeric, 0);
            v_outside := COALESCE((p_form ->> 'outside_usd_cents')::numeric, 0);
            IF v_parts <> trunc(v_parts) OR v_outside <> trunc(v_outside)
                OR v_parts NOT BETWEEN 0 AND 99999999 OR v_outside NOT BETWEEN 0 AND 99999999
                OR v_parts + v_outside = 0 THEN
                RETURN app.staff_form_refused('cost');
            END IF;
            IF v_parts > 0 THEN
                v_lines := v_lines || jsonb_build_object('kind', 'PARTS',
                    'description', 'Parts (Staff bot)', 'currency', 'USD',
                    'amount_minor', v_parts::bigint);
            END IF;
            IF v_outside > 0 THEN
                v_lines := v_lines || jsonb_build_object('kind', 'OUTSIDE_WORKER',
                    'description', 'Outside workers (Staff bot)', 'currency', 'USD',
                    'amount_minor', v_outside::bigint);
            END IF;
        ELSIF p_form ? 'parts_usd_cents' OR p_form ? 'outside_usd_cents' THEN
            RETURN app.staff_form_refused('cost');
        END IF;
        -- The after photos first (1 to 3), then the receipt photos (1 or 2 with a cost, none
        -- without).
        BEGIN
            FOR v_file IN SELECT * FROM app.staff_form_files(p_media) LOOP
                IF v_file.content_type NOT LIKE 'image/%' THEN
                    RETURN app.staff_form_refused('files');
                END IF;
                v_files := v_files || v_file;
            END LOOP;
        EXCEPTION WHEN invalid_parameter_value THEN
            RETURN app.staff_form_refused('files');
        END;
        IF v_after NOT BETWEEN 1 AND 3 OR v_after <> trunc(v_after)
            OR cardinality(v_files) < v_after THEN
            RETURN app.staff_form_refused('after_photo');
        END IF;
        IF (v_cost = 'PAID' AND cardinality(v_files) - v_after NOT BETWEEN 1 AND 2)
            OR (v_cost = 'NONE' AND cardinality(v_files) <> v_after) THEN
            RETURN app.staff_form_refused('receipt');
        END IF;
        SELECT report.* INTO v_report FROM app.problem_reports AS report
        WHERE report.id = v_report_id AND report.property_id = p_property FOR UPDATE;
        IF NOT FOUND THEN
            RETURN app.staff_form_refused('job');
        END IF;
        IF app.problem_report_state(v_report.id) <> 'REPAIR_PLANNED' THEN
            RETURN jsonb_build_object('result', 'NOT_OPEN', 'report_number', v_report.report_number);
        END IF;
        IF NOT app.problem_report_cost_open(v_report.id) THEN
            RETURN jsonb_build_object('result', 'COST_CHECKED', 'report_number', v_report.report_number);
        END IF;
        v_note := left('Closed in the Staff bot by ' || v_sender.name, 500);
        v_version := app.record_problem_report_cost(p_property, v_report.id, v_report.version,
            jsonb_build_object('no_cost', v_cost = 'NONE', 'lines', v_lines, 'note', v_note),
            p_actor, NULL);
        v_version := app.problem_report_step(p_property, v_report.id, v_version, 'DONE',
            jsonb_build_object('note', v_note), p_actor, NULL);
        SELECT cost_set.id INTO v_set FROM app.problem_report_cost_sets AS cost_set
        WHERE cost_set.report_id = v_report.id ORDER BY cost_set.set_no DESC LIMIT 1;
        FOREACH v_file IN ARRAY v_files LOOP
            v_count := v_count + 1;
            PERFORM app.staff_keep_report_file(v_report.id, v_file,
                CASE WHEN v_count <= v_after THEN 'DONE' ELSE 'RECEIPT' END, p_actor);
        END LOOP;
        INSERT INTO app.staff_job_closures (report_id, property_id, inbound_event_id,
            telegram_user_id, employee_id, cost_set_id, created_by)
        VALUES (v_report.id, p_property, p_inbound, v_user, v_sender.employee_id, v_set, p_actor);
        RETURN jsonb_build_object('result', 'DONE', 'repeated', false,
            'report_number', v_report.report_number, 'cost', v_cost,
            'total_usd_cents', COALESCE(v_parts, 0) + COALESCE(v_outside, 0));
    END $$;

    -- 3. The urgent alert to the caretaker on shift and the Authorizers, once the report is
    -- saved (at the end of the change, so a report joined at once is not sent again).
    CREATE FUNCTION app.telegram_staff_urgent_alert() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_report app.problem_reports%ROWTYPE;
        v_now timestamptz := statement_timestamp();
        v_today date := timezone(app.hr_zone(), statement_timestamp())::date;
        v_sender bigint;
        v_details jsonb;
    BEGIN
        SELECT report.* INTO v_report FROM app.problem_reports AS report WHERE report.id = NEW.id;
        IF NOT v_report.urgent OR v_report.status = 'JOINED' THEN
            RETURN NULL;
        END IF;
        SELECT source.telegram_user_id INTO v_sender FROM app.staff_problem_report_sources AS source
        WHERE source.report_id = v_report.id;
        SELECT jsonb_build_object('number', v_report.report_number,
                'type', kind.name_kh,
                'where', CASE WHEN v_report.kind = 'UNIT' THEN unit.unit_number
                    ELSE concat_ws(' · ', place.name_kh, v_report.floor_label) END)
        INTO v_details
        FROM app.problem_types AS kind
        LEFT JOIN app.units AS unit ON unit.id = v_report.unit_id
        LEFT JOIN app.problem_places AS place ON place.id = v_report.problem_place_id
        WHERE kind.id = v_report.problem_type_id;
        INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code, language,
            details, keyboard, created_by)
        SELECT v_report.property_id, 'STAFF', person.telegram_user_id, 'staff.urgent', 'km',
            v_details, NULL, v_report.created_by
        FROM (
            SELECT DISTINCT link.telegram_user_id
            FROM app.employee_telegram_links AS link
            JOIN app.employees AS employee ON employee.id = link.employee_id
            WHERE employee.property_id = v_report.property_id
              AND app.hr_link_live(link.id, v_today)
              AND link.telegram_user_id IS DISTINCT FROM v_sender
              AND (link.report_role = 'AUTHORIZER' OR (link.report_role = 'CARETAKER'
                  AND EXISTS (
                      SELECT 1 FROM (VALUES (v_today), (v_today - 1)) AS shift_day (work_date)
                      CROSS JOIN LATERAL app.hr_shift_on(employee.id, shift_day.work_date) AS shift
                      CROSS JOIN LATERAL app.hr_shift_times(shift.shift_code, shift_day.work_date) AS times
                      WHERE shift.shift_code IS NOT NULL
                        AND v_now >= times.starts_at AND v_now < times.ends_at)))
        ) AS person;
        RETURN NULL;
    END $$;

    CREATE CONSTRAINT TRIGGER telegram_staff_urgent_alert
        AFTER INSERT ON app.problem_reports DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION app.telegram_staff_urgent_alert();
"""

RUNTIME = (
    "app.telegram_staff_problem_report(uuid, uuid, jsonb, jsonb, uuid)",
    "app.telegram_staff_close_job(uuid, uuid, jsonb, jsonb, uuid)",
)
INTERNAL = (
    "app.telegram_staff_sender(uuid, bigint)",
    "app.telegram_staff_jobs(uuid)",
    "app.staff_form_refused(text)",
    "app.staff_form_files(jsonb)",
    "app.staff_keep_report_file(uuid, app.media_files, text, uuid)",
    "app.telegram_staff_urgent_alert()",
)
TABLE_NAMES = "app.staff_problem_report_sources, app.staff_job_closures"


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    op.execute(f"REVOKE ALL ON TABLE {TABLE_NAMES} FROM PUBLIC, prm_runtime, prm_bootstrap")
    for signature in RUNTIME + INTERNAL:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in RUNTIME:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("the Staff bot reports migration is forward-only")
