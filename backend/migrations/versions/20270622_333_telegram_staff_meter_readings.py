# ruff: noqa: E501
"""Telegram bots, step 4c: the meter reader's Utility reading form and the Meter check request (DL-176).

Owner rules (22 Oct 2026; staff forms mock-up v14, approved 3 Nov 2026; bots plan rev 29):

1. Utility reading: the meter reader (the Technician, or a stand-in caretaker) types each Unit's
   Electricity and Water reading in one table. No photo is needed. A reading lower than last
   month, or Electricity more than 300 kWh above it, shows "Look again" before sending.
2. The readings are not meter readings yet: they wait in Utilities until a Manager (anyone who
   may record readings) confirms them. A confirmed reading becomes a normal meter reading on the
   day it was read, so billing does not change. The Manager may instead ask the reader to read
   some Units again (the bot tells the reader) or not use a reading.
3. Meter check request: a flag beside a Unit's reading asks the Technical team to check a meter
   (broken, cannot read the number, number not sure, other), with an optional photo and note.
   It becomes a Unit Problem (Electricity or Water) in the one Problem reports list.

Tables: ``staff_meter_reading_runs`` (one sent form), ``staff_meter_reading_proposals`` (one
reading per meter) and ``staff_meter_reading_decisions`` (the Manager's answer), all
append-only. Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270622_333"
down_revision: str | None = "20270621_332"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = """
    CREATE TABLE app.staff_meter_reading_runs (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        inbound_event_id uuid NOT NULL UNIQUE
            REFERENCES app.telegram_inbound_events (id) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        reading_date date NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX staff_meter_reading_runs_property_idx
        ON app.staff_meter_reading_runs (property_id, created_at DESC);
    COMMENT ON TABLE app.staff_meter_reading_runs IS
        'Telegram bots step 4c (DL-176): one Utility reading form sent in the Staff bot.';

    CREATE TABLE app.staff_meter_reading_proposals (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        run_id uuid NOT NULL REFERENCES app.staff_meter_reading_runs (id) ON DELETE RESTRICT,
        meter_id uuid NOT NULL REFERENCES app.utility_meters (id) ON DELETE RESTRICT,
        unit_id uuid NOT NULL REFERENCES app.units (id) ON DELETE RESTRICT,
        utility_type text NOT NULL CHECK (utility_type IN ('ELECTRICITY', 'WATER')),
        reading_value numeric(20,6) NOT NULL CHECK (reading_value >= 0),
        last_value numeric(20,6) CHECK (last_value >= 0),
        last_date date,
        flag text CHECK (flag IN ('LOWER', 'HIGH')),
        CONSTRAINT staff_meter_reading_proposals_once UNIQUE (run_id, meter_id),
        CONSTRAINT staff_meter_reading_proposals_last CHECK ((last_value IS NULL) = (last_date IS NULL))
    );
    CREATE INDEX staff_meter_reading_proposals_meter_idx
        ON app.staff_meter_reading_proposals (meter_id);
    COMMENT ON TABLE app.staff_meter_reading_proposals IS
        'Telegram bots step 4c (DL-176): a reading typed by staff, waiting for a Manager.';

    CREATE TABLE app.staff_meter_reading_decisions (
        proposal_id uuid PRIMARY KEY
            REFERENCES app.staff_meter_reading_proposals (id) ON DELETE RESTRICT,
        decision text NOT NULL CHECK (decision IN ('CONFIRMED', 'ASK_AGAIN', 'NOT_USED')),
        reading_id uuid UNIQUE REFERENCES app.utility_readings (id) ON DELETE RESTRICT,
        decided_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        decided_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT staff_meter_reading_decisions_reading
            CHECK ((decision = 'CONFIRMED') = (reading_id IS NOT NULL))
    );
    COMMENT ON TABLE app.staff_meter_reading_decisions IS
        'Telegram bots step 4c (DL-176): the Manager confirmed a staff reading (it became a meter reading), asked to read again, or did not use it.';

    CREATE TRIGGER staff_meter_reading_runs_append_only BEFORE UPDATE OR DELETE
        ON app.staff_meter_reading_runs
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER staff_meter_reading_runs_no_truncate BEFORE TRUNCATE
        ON app.staff_meter_reading_runs
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER staff_meter_reading_proposals_append_only BEFORE UPDATE OR DELETE
        ON app.staff_meter_reading_proposals
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER staff_meter_reading_proposals_no_truncate BEFORE TRUNCATE
        ON app.staff_meter_reading_proposals
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER staff_meter_reading_decisions_append_only BEFORE UPDATE OR DELETE
        ON app.staff_meter_reading_decisions
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER staff_meter_reading_decisions_no_truncate BEFORE TRUNCATE
        ON app.staff_meter_reading_decisions
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
"""

FUNCTIONS = """
    -- The meter that can be read now for a Unit and a type: installed, not broken, not removed.
    CREATE FUNCTION app.staff_readable_meter(p_unit uuid, p_type text, p_day date) RETURNS uuid
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT meter.id FROM app.utility_meters AS meter
        WHERE meter.unit_id = p_unit AND meter.utility_type = p_type
          AND meter.installed_date <= p_day AND meter.failure_date IS NULL
          AND meter.deactivated_date IS NULL
        ORDER BY meter.installed_date DESC, meter.id
        LIMIT 1
    $$;

    -- The meter's last saved reading before a day (what "last month" shows).
    CREATE FUNCTION app.staff_last_reading(p_meter uuid, p_day date)
    RETURNS TABLE (reading_value numeric, reading_date date) ROWS 1
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT reading.reading_value, reading.reading_date FROM app.utility_readings AS reading
        WHERE reading.meter_id = p_meter AND reading.reading_date < p_day
        ORDER BY reading.reading_date DESC, reading.id
        LIMIT 1
    $$;

    -- What the Utility reading form shows: each Unit with a meter that can be read, with the
    -- last reading of each type ("e" Electricity, "w" Water; absent when the Unit has none).
    CREATE FUNCTION app.telegram_staff_meters(p_property uuid, p_day date) RETURNS jsonb
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT COALESCE(jsonb_agg(item.body ORDER BY item.unit_number), '[]'::jsonb)
        FROM (
            SELECT unit.unit_number, jsonb_strip_nulls(jsonb_build_object('id', unit.id,
                    'n', unit.unit_number,
                    'e', CASE WHEN electric.id IS NOT NULL THEN jsonb_build_object('last',
                        trim_scale((SELECT last.reading_value
                                    FROM app.staff_last_reading(electric.id, p_day + 1) AS last))) END,
                    'w', CASE WHEN water.id IS NOT NULL THEN jsonb_build_object('last',
                        trim_scale((SELECT last.reading_value
                                    FROM app.staff_last_reading(water.id, p_day + 1) AS last))) END)) AS body
            FROM app.units AS unit
            LEFT JOIN app.utility_meters AS electric
                ON electric.id = app.staff_readable_meter(unit.id, 'ELECTRICITY', p_day)
            LEFT JOIN app.utility_meters AS water
                ON water.id = app.staff_readable_meter(unit.id, 'WATER', p_day)
            WHERE unit.property_id = p_property AND (electric.id IS NOT NULL OR water.id IS NOT NULL)
        ) AS item
    $$;

    -- Who may open the Staff forms and what they show (replaces step 4b's list): the same
    -- people and choices, and the choices add the meters for the Utility reading form.
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
        -- bot, and any Unit of the Property (Unit numbers only). The Utility reading form
        -- uses the meters (Unit numbers and last readings only, no names).
        v_choices := (app.telegram_tenant_form_data(p_property, p_actor) -> 'choices')
            || jsonb_build_object('units', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'id', unit.id, 'number', unit.unit_number) ORDER BY unit.unit_number)
                FROM app.units AS unit WHERE unit.property_id = p_property), '[]'::jsonb),
                'meters', app.telegram_staff_meters(p_property, v_today));
        RETURN jsonb_build_object('users', v_users, 'choices', v_choices);
    END $$;

    -- The pulled Staff form ``p_inbound`` and who sent it, for the 4c forms.
    CREATE FUNCTION app.staff_form_sender(p_property uuid, p_inbound uuid)
    RETURNS TABLE (telegram_user_id bigint, employee_id uuid, name text, roles text[]) ROWS 1
    LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
    DECLARE
        v_user bigint;
    BEGIN
        SELECT account.telegram_user_id INTO v_user
        FROM app.telegram_inbound_events AS event
        JOIN app.telegram_accounts AS account ON account.id = event.account_id
        WHERE event.id = p_inbound AND event.property_id = p_property
          AND event.bot_code = 'STAFF' AND event.kind = 'form';
        IF NOT FOUND THEN
            IF NOT EXISTS (SELECT 1 FROM app.telegram_inbound_events AS event
                           WHERE event.id = p_inbound AND event.property_id = p_property
                             AND event.bot_code = 'STAFF' AND event.kind = 'form') THEN
                RAISE EXCEPTION 'the form does not exist' USING ERRCODE = '22023';
            END IF;
            RETURN;
        END IF;
        RETURN QUERY SELECT v_user, sender.employee_id, sender.name, sender.roles
        FROM app.telegram_staff_sender(p_property, v_user) AS sender;
    END $$;

    -- A typed meter reading: a JSON number from 0 to below one billion, at most 3 decimals.
    CREATE FUNCTION app.staff_reading_value(p_value jsonb) RETURNS numeric
    LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog AS $$
    DECLARE
        v_value numeric;
    BEGIN
        IF p_value IS NULL OR jsonb_typeof(p_value) = 'null' THEN
            RETURN NULL;
        END IF;
        IF jsonb_typeof(p_value) <> 'number' THEN
            RAISE EXCEPTION 'value' USING ERRCODE = '22023';
        END IF;
        v_value := (p_value #>> '{}')::numeric;
        IF v_value < 0 OR v_value >= 1000000000 OR v_value <> round(v_value, 3) THEN
            RAISE EXCEPTION 'value' USING ERRCODE = '22023';
        END IF;
        RETURN v_value;
    END $$;

    -- 1. The Utility reading form (the pulled item ``p_inbound``): the readings wait for a
    -- Manager. The same form twice is saved once.
    CREATE FUNCTION app.telegram_staff_meter_readings(p_property uuid, p_inbound uuid,
        p_form jsonb, p_media jsonb, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date;
        v_sender record;
        v_run app.staff_meter_reading_runs%ROWTYPE;
        v_run_id uuid := gen_random_uuid();
        v_row jsonb;
        v_unit uuid;
        v_units uuid[] := '{}';
        v_type text;
        v_key text;
        v_value numeric;
        v_meter uuid;
        v_last record;
        v_flag text;
        v_count integer := 0;
        v_flagged integer := 0;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        v_day := app.gl_today(p_property);
        SELECT sender.* INTO v_sender FROM app.staff_form_sender(p_property, p_inbound) AS sender;
        SELECT run.* INTO v_run FROM app.staff_meter_reading_runs AS run
        WHERE run.inbound_event_id = p_inbound;
        IF FOUND THEN
            RETURN jsonb_build_object('result', 'SENT', 'repeated', true,
                'count', (SELECT count(*) FROM app.staff_meter_reading_proposals AS proposal
                          WHERE proposal.run_id = v_run.id),
                'flagged', (SELECT count(*) FROM app.staff_meter_reading_proposals AS proposal
                            WHERE proposal.run_id = v_run.id AND proposal.flag IS NOT NULL),
                'reading_date', v_run.reading_date);
        END IF;
        IF v_sender.employee_id IS NULL THEN
            RETURN jsonb_build_object('result', 'NOT_LINKED');
        END IF;
        IF NOT v_sender.roles && ARRAY['METER_READER', 'AUTHORIZER'] THEN
            RETURN jsonb_build_object('result', 'NOT_METER_READER');
        END IF;
        -- No photo is needed (owner rule, 22 Oct 2026), so none is taken.
        IF p_media IS NULL OR p_media <> '[]'::jsonb THEN
            RETURN app.staff_form_refused('no_photo');
        END IF;
        IF p_form IS NULL OR jsonb_typeof(p_form) <> 'object'
            OR jsonb_typeof(p_form -> 'readings') IS DISTINCT FROM 'array'
            OR jsonb_array_length(p_form -> 'readings') NOT BETWEEN 1 AND 500 THEN
            RETURN app.staff_form_refused('not_a_form');
        END IF;
        INSERT INTO app.staff_meter_reading_runs (id, property_id, inbound_event_id,
            telegram_user_id, employee_id, reading_date, created_by)
        VALUES (v_run_id, p_property, p_inbound, v_sender.telegram_user_id,
            v_sender.employee_id, v_day, p_actor);
        FOR v_row IN SELECT value FROM jsonb_array_elements(p_form -> 'readings') LOOP
            IF jsonb_typeof(v_row) <> 'object' THEN
                RAISE EXCEPTION 'not_a_form' USING ERRCODE = 'PRS01';
            END IF;
            BEGIN
                v_unit := (v_row ->> 'unit_id')::uuid;
            EXCEPTION WHEN data_exception THEN
                RAISE EXCEPTION 'unit' USING ERRCODE = 'PRS01';
            END;
            IF v_unit IS NULL OR v_unit = ANY (v_units) OR NOT EXISTS (
                    SELECT 1 FROM app.units AS unit
                    WHERE unit.id = v_unit AND unit.property_id = p_property) THEN
                RAISE EXCEPTION 'unit' USING ERRCODE = 'PRS01';
            END IF;
            v_units := v_units || v_unit;
            FOREACH v_type IN ARRAY ARRAY['ELECTRICITY', 'WATER'] LOOP
                v_key := lower(v_type);
                BEGIN
                    v_value := app.staff_reading_value(v_row -> v_key);
                EXCEPTION WHEN invalid_parameter_value THEN
                    RAISE EXCEPTION 'value' USING ERRCODE = 'PRS01';
                END;
                CONTINUE WHEN v_value IS NULL;
                v_meter := app.staff_readable_meter(v_unit, v_type, v_day);
                IF v_meter IS NULL THEN
                    RAISE EXCEPTION 'meter' USING ERRCODE = 'PRS01';
                END IF;
                SELECT last.* INTO v_last FROM app.staff_last_reading(v_meter, v_day) AS last;
                -- "Look again" (mock-up v14): lower than last month, or Electricity more
                -- than 300 kWh above it.
                v_flag := CASE
                    WHEN v_last.reading_value IS NOT NULL AND v_value < v_last.reading_value THEN 'LOWER'
                    WHEN v_type = 'ELECTRICITY' AND v_last.reading_value IS NOT NULL
                        AND v_value - v_last.reading_value > 300 THEN 'HIGH' END;
                INSERT INTO app.staff_meter_reading_proposals (run_id, meter_id, unit_id,
                    utility_type, reading_value, last_value, last_date, flag)
                VALUES (v_run_id, v_meter, v_unit, v_type, v_value, v_last.reading_value,
                    v_last.reading_date, v_flag);
                v_count := v_count + 1;
                v_flagged := v_flagged + (v_flag IS NOT NULL)::integer;
            END LOOP;
        END LOOP;
        IF v_count = 0 THEN
            RAISE EXCEPTION 'empty' USING ERRCODE = 'PRS01';
        END IF;
        PERFORM app.product_audit(p_property, p_actor, v_day, 'utility.staff_readings.sent',
            'staff_meter_reading_run', v_run_id, 'Utility readings from the Staff bot',
            'telegram.operate', NULL, jsonb_build_object('readings', v_count,
                'flagged', v_flagged, 'reading_date', v_day), NULL);
        RETURN jsonb_build_object('result', 'SENT', 'repeated', false, 'count', v_count,
            'flagged', v_flagged, 'reading_date', v_day);
    EXCEPTION WHEN SQLSTATE 'PRS01' THEN
        -- A wrong row refuses the whole form; nothing of it is kept.
        RETURN app.staff_form_refused(SQLERRM);
    END $$;

    -- 2. Meter check request: a Unit Problem (Electricity or Water) for the Technical team, with
    -- up to 2 photos. The same form twice gives the same report.
    CREATE FUNCTION app.telegram_staff_meter_check(p_property uuid, p_inbound uuid,
        p_form jsonb, p_media jsonb, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date;
        v_sender record;
        v_source app.staff_problem_report_sources%ROWTYPE;
        v_unit uuid;
        v_meter text;
        v_problem text;
        v_note text;
        v_type app.problem_types%ROWTYPE;
        v_file app.media_files%ROWTYPE;
        v_files app.media_files[] := '{}';
        v_lease uuid;
        v_customer uuid;
        v_id uuid := gen_random_uuid();
        v_number text;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        v_day := app.gl_today(p_property);
        SELECT sender.* INTO v_sender FROM app.staff_form_sender(p_property, p_inbound) AS sender;
        SELECT source.* INTO v_source FROM app.staff_problem_report_sources AS source
        WHERE source.inbound_event_id = p_inbound;
        IF FOUND THEN
            RETURN jsonb_build_object('result', 'ADDED', 'repeated', true,
                'report_number', (SELECT report.report_number FROM app.problem_reports AS report
                                  WHERE report.id = v_source.report_id));
        END IF;
        IF v_sender.employee_id IS NULL THEN
            RETURN jsonb_build_object('result', 'NOT_LINKED');
        END IF;
        IF p_form IS NULL OR jsonb_typeof(p_form) <> 'object' THEN
            RETURN app.staff_form_refused('not_a_form');
        END IF;
        BEGIN
            v_unit := (p_form ->> 'unit_id')::uuid;
        EXCEPTION WHEN data_exception THEN
            RETURN app.staff_form_refused('unit');
        END;
        IF v_unit IS NULL OR NOT EXISTS (SELECT 1 FROM app.units AS unit
                WHERE unit.id = v_unit AND unit.property_id = p_property) THEN
            RETURN app.staff_form_refused('unit');
        END IF;
        v_meter := p_form ->> 'meter';
        v_problem := p_form ->> 'problem';
        IF v_meter IS NULL OR v_meter NOT IN ('ELECTRICITY', 'WATER') THEN
            RETURN app.staff_form_refused('meter');
        END IF;
        IF v_problem IS NULL OR v_problem NOT IN ('BROKEN', 'CANNOT_READ', 'NOT_SURE', 'OTHER') THEN
            RETURN app.staff_form_refused('problem');
        END IF;
        IF p_form ? 'note' AND jsonb_typeof(p_form -> 'note') NOT IN ('string', 'null') THEN
            RETURN app.staff_form_refused('note');
        END IF;
        v_note := NULLIF(btrim(p_form ->> 'note'), '');
        IF v_note IS NOT NULL AND length(v_note) > 300 THEN
            RETURN app.staff_form_refused('note');
        END IF;
        IF v_problem = 'OTHER' AND v_note IS NULL THEN
            RETURN app.staff_form_refused('say_what');
        END IF;
        -- A photo if possible: up to 2 photos, nothing else.
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
        IF cardinality(v_files) > 2 THEN
            RETURN app.staff_form_refused('photo');
        END IF;
        SELECT kind.* INTO v_type FROM app.problem_types AS kind WHERE kind.code = v_meter;
        SELECT current.lease_id, current.customer_id INTO v_lease, v_customer
        FROM app.problem_unit_lease(v_unit, v_day) AS current;
        v_number := app.take_document_number('UNIT_PROBLEM', date_part('year', v_day)::integer);
        INSERT INTO app.problem_reports (id, property_id, report_number, kind, unit_id, lease_id,
            customer_id, problem_place_id, floor_label, problem_type_id, description, urgent,
            always_urgent, may_enter, best_time, source, reported_by, created_by)
        VALUES (v_id, p_property, v_number, 'UNIT', v_unit, v_lease, v_customer, NULL, NULL,
            v_type.id, concat_ws(' ', 'Meter check request:',
                CASE v_meter WHEN 'ELECTRICITY' THEN 'Electricity meter' ELSE 'Water meter' END
                || ', ' || CASE v_problem WHEN 'BROKEN' THEN 'broken.'
                    WHEN 'CANNOT_READ' THEN 'cannot read the number.'
                    WHEN 'NOT_SURE' THEN 'number not sure.' ELSE 'other.' END,
                v_note),
            v_type.always_urgent, v_type.always_urgent, false, 'ANY', 'STAFF_BOT',
            v_sender.name, p_actor);
        PERFORM app.problem_report_event(v_id, 'RECEIVED', NULL,
            jsonb_build_object('source', 'STAFF_BOT', 'photos', cardinality(v_files),
                'voice', false, 'meter_check', v_meter), p_actor);
        FOREACH v_file IN ARRAY v_files LOOP
            PERFORM app.staff_keep_report_file(v_id, v_file, 'REPORTED', p_actor);
        END LOOP;
        INSERT INTO app.staff_problem_report_sources (report_id, property_id, inbound_event_id,
            telegram_user_id, employee_id, created_by)
        VALUES (v_id, p_property, p_inbound, v_sender.telegram_user_id, v_sender.employee_id,
            p_actor);
        PERFORM app.product_audit(p_property, p_actor, v_day, 'problem_report.added',
            'problem_report', v_id, 'Meter check request from the Staff bot', 'telegram.operate',
            NULL, jsonb_build_object('report_number', v_number, 'kind', 'UNIT',
                'source', 'STAFF_BOT', 'meter', v_meter, 'problem', v_problem), NULL);
        RETURN jsonb_build_object('result', 'ADDED', 'repeated', false,
            'report_number', v_number);
    END $$;

    -- 3. Utilities: the staff readings that wait for a Manager, newest form first (at most 20
    -- forms). "already" marks a meter that has a reading saved for that day.
    CREATE FUNCTION app.staff_meter_readings_waiting(p_property uuid, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'utility_readings.record', p_property);
        RETURN (
            SELECT COALESCE(jsonb_agg(run.body ORDER BY run.created_at DESC), '[]'::jsonb)
            FROM (
                SELECT run.created_at, jsonb_build_object('run_id', run.id,
                    'reading_date', run.reading_date, 'sent_at', run.created_at,
                    'sent_by', COALESCE(NULLIF(employee.name_en, ''), employee.name_km),
                    'readings', (
                        SELECT jsonb_agg(jsonb_build_object('proposal_id', proposal.id,
                                'unit_id', proposal.unit_id, 'unit', unit.unit_number,
                                'utility_type', proposal.utility_type,
                                'reading_value', trim_scale(proposal.reading_value)::text,
                                'last_value', trim_scale(proposal.last_value)::text,
                                'last_date', proposal.last_date, 'flag', proposal.flag,
                                'already', EXISTS (SELECT 1 FROM app.utility_readings AS saved
                                    WHERE saved.meter_id = proposal.meter_id
                                      AND saved.reading_date = run.reading_date))
                            ORDER BY unit.unit_number, proposal.utility_type)
                        FROM app.staff_meter_reading_proposals AS proposal
                        JOIN app.units AS unit ON unit.id = proposal.unit_id
                        WHERE proposal.run_id = run.id AND NOT EXISTS (
                            SELECT 1 FROM app.staff_meter_reading_decisions AS decided
                            WHERE decided.proposal_id = proposal.id))) AS body
                FROM app.staff_meter_reading_runs AS run
                JOIN app.employees AS employee ON employee.id = run.employee_id
                WHERE run.property_id = p_property AND EXISTS (
                    SELECT 1 FROM app.staff_meter_reading_proposals AS proposal
                    WHERE proposal.run_id = run.id AND NOT EXISTS (
                        SELECT 1 FROM app.staff_meter_reading_decisions AS decided
                        WHERE decided.proposal_id = proposal.id))
                ORDER BY run.created_at DESC
                LIMIT 20
            ) AS run
        );
    END $$;

    -- 4. Utilities: the Manager's answer for some waiting staff readings. CONFIRMED saves each
    -- as a normal meter reading on the day it was read (a meter that already has a reading that
    -- day is left waiting and named in "already"); ASK_AGAIN tells the reader in the Staff bot
    -- which Units to read again; NOT_USED closes them. An answered reading is skipped, so the
    -- same tap twice changes nothing.
    CREATE FUNCTION app.decide_staff_meter_readings(p_property uuid, p_proposals jsonb,
        p_decision text, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date;
        v_ids uuid[];
        v_row record;
        v_version integer;
        v_reading uuid;
        v_done integer := 0;
        v_already text[] := '{}';
        v_answered uuid[] := '{}';
        v_ask record;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'utility_readings.record', p_property);
        v_day := app.gl_today(p_property);
        IF p_decision IS NULL OR p_decision NOT IN ('CONFIRMED', 'ASK_AGAIN', 'NOT_USED') THEN
            RAISE EXCEPTION 'the answer is not known' USING ERRCODE = '22023';
        END IF;
        IF p_proposals IS NULL OR jsonb_typeof(p_proposals) <> 'array'
            OR jsonb_array_length(p_proposals) NOT BETWEEN 1 AND 500 THEN
            RAISE EXCEPTION 'pick the readings' USING ERRCODE = '22023';
        END IF;
        BEGIN
            SELECT array_agg(DISTINCT (value #>> '{}')::uuid) INTO v_ids
            FROM jsonb_array_elements(p_proposals);
        EXCEPTION WHEN data_exception THEN
            RAISE EXCEPTION 'pick the readings' USING ERRCODE = '22023';
        END;
        IF EXISTS (SELECT 1 FROM unnest(v_ids) AS picked (id)
                   WHERE NOT EXISTS (
                       SELECT 1 FROM app.staff_meter_reading_proposals AS proposal
                       JOIN app.staff_meter_reading_runs AS run ON run.id = proposal.run_id
                       WHERE proposal.id = picked.id AND run.property_id = p_property)) THEN
            RAISE EXCEPTION 'a staff reading does not exist' USING ERRCODE = '22023';
        END IF;
        FOR v_row IN
            SELECT proposal.*, run.reading_date, unit.unit_number
            FROM app.staff_meter_reading_proposals AS proposal
            JOIN app.staff_meter_reading_runs AS run ON run.id = proposal.run_id
            JOIN app.units AS unit ON unit.id = proposal.unit_id
            WHERE proposal.id = ANY (v_ids) AND NOT EXISTS (
                SELECT 1 FROM app.staff_meter_reading_decisions AS decided
                WHERE decided.proposal_id = proposal.id)
            ORDER BY unit.unit_number, proposal.utility_type
            FOR UPDATE OF proposal
        LOOP
            v_reading := NULL;
            IF p_decision = 'CONFIRMED' THEN
                IF EXISTS (SELECT 1 FROM app.utility_readings AS saved
                           WHERE saved.meter_id = v_row.meter_id
                             AND saved.reading_date = v_row.reading_date) THEN
                    v_already := v_already || v_row.unit_number;
                    CONTINUE;
                END IF;
                SELECT meter.version INTO v_version FROM app.utility_meters AS meter
                WHERE meter.id = v_row.meter_id;
                -- The same path as a reading typed in Utilities: the Manager is the one who
                -- records it; the staff form is the evidence.
                v_reading := app.record_utility_reading_api(v_row.meter_id, gen_random_uuid(),
                    v_version, v_row.reading_date, v_row.reading_value, 'MANUAL',
                    'Staff bot reading ' || v_row.run_id::text || ', confirmed in Utilities',
                    p_actor, v_row.id,
                    encode(sha256(convert_to(concat_ws('|', 'STAFF_READING', v_row.id,
                        v_row.meter_id, v_row.reading_date, v_row.reading_value), 'UTF8')), 'hex'));
            END IF;
            INSERT INTO app.staff_meter_reading_decisions (proposal_id, decision, reading_id,
                decided_by)
            VALUES (v_row.id, p_decision, v_reading, p_actor);
            v_answered := v_answered || v_row.id;
            v_done := v_done + 1;
        END LOOP;
        -- Read again: one message to each reader, with the Units and meters.
        IF p_decision = 'ASK_AGAIN' THEN
            FOR v_ask IN
                SELECT run.telegram_user_id, string_agg(unit.unit_number || ' '
                    || CASE proposal.utility_type WHEN 'ELECTRICITY' THEN 'ភ្លើង' ELSE 'ទឹក' END,
                    ', ' ORDER BY unit.unit_number, proposal.utility_type) AS units
                FROM app.staff_meter_reading_decisions AS decided
                JOIN app.staff_meter_reading_proposals AS proposal ON proposal.id = decided.proposal_id
                JOIN app.staff_meter_reading_runs AS run ON run.id = proposal.run_id
                JOIN app.units AS unit ON unit.id = proposal.unit_id
                WHERE decided.proposal_id = ANY (v_answered)
                GROUP BY run.telegram_user_id
            LOOP
                INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code,
                    language, details, keyboard, created_by)
                VALUES (p_property, 'STAFF', v_ask.telegram_user_id, 'staff.meter_again', 'km',
                    jsonb_build_object('units', v_ask.units), NULL, p_actor);
            END LOOP;
        END IF;
        -- One audit line for each sent form answered.
        FOR v_ask IN
            SELECT proposal.run_id, count(*) AS readings
            FROM app.staff_meter_reading_proposals AS proposal
            WHERE proposal.id = ANY (v_answered)
            GROUP BY proposal.run_id
            ORDER BY proposal.run_id
        LOOP
            PERFORM app.product_audit(p_property, p_actor, v_day,
                'utility.staff_readings.' || lower(p_decision), 'staff_meter_reading_run',
                v_ask.run_id, 'Staff bot readings answered in Utilities',
                'utility_readings.record', NULL,
                jsonb_build_object('readings', v_ask.readings, 'decision', p_decision), NULL);
        END LOOP;
        RETURN jsonb_build_object('decision', p_decision, 'done', v_done,
            'already', to_jsonb(v_already));
    END $$;
"""

RUNTIME = (
    "app.telegram_staff_meter_readings(uuid, uuid, jsonb, jsonb, uuid)",
    "app.telegram_staff_meter_check(uuid, uuid, jsonb, jsonb, uuid)",
    "app.staff_meter_readings_waiting(uuid, uuid)",
    "app.decide_staff_meter_readings(uuid, jsonb, text, uuid)",
)
INTERNAL = (
    "app.staff_readable_meter(uuid, text, date)",
    "app.staff_last_reading(uuid, date)",
    "app.telegram_staff_meters(uuid, date)",
    "app.staff_form_sender(uuid, uuid)",
    "app.staff_reading_value(jsonb)",
)
TABLE_NAMES = (
    "app.staff_meter_reading_runs, app.staff_meter_reading_proposals, "
    "app.staff_meter_reading_decisions"
)


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    op.execute(f"REVOKE ALL ON TABLE {TABLE_NAMES} FROM PUBLIC, prm_runtime, prm_bootstrap")
    for signature in RUNTIME + INTERNAL:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in RUNTIME:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("the Staff bot meter readings migration is forward-only")
