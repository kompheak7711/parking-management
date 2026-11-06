# ruff: noqa: E501
"""Telegram bots, step 4e: the Unit Check and the Maintenance check from the Staff bot (DL-178).

Owner rules (staff forms mock-up v14, 3 Nov 2026; Repair Checks and Unit Checks, DL-115):

1. Unit Check: the Technician (or an Authorizer) picks the Unit and the kind (regular, or after a
   repair), and marks each area Good, Broken or Missing: living room, bedroom, bathroom, kitchen,
   balcony, air conditioner, and keys, key cards and remotes. A Unit without an area leaves it
   out. Each Broken or Missing area needs what is wrong and at least one photo. Unit numbers only:
   no tenant name or phone. Each finding becomes a Unit Problem in the one Problem reports list
   (source STAFF_BOT), so the Manager plans it as usual. A Unit Check never makes a charge.
2. Maintenance check: the Technician (or an Authorizer) picks a planned visit (Visit planned),
   says how staff entered (urgent, the tenant agreed, or notice given first), what caused it
   (wear, the tenant caused it, or not sure yet), whether it was fixed at once (urgent only),
   takes the photos and writes a note. The report moves to Checked; the Manager then decides who
   pays in the app. "Tenant caused" only marks the cause: only a confirmed finding in the app can
   become a Damage charge (DL-115).

Tables: ``staff_unit_checks`` and ``staff_unit_check_findings`` (one row per Broken or Missing
area, with the Unit Problem it made) and ``staff_maintenance_checks`` (which Staff form checked
which visit), all append-only. The report photos also take the stage CHECK. The Staff forms get
the planned visits and the Unit Check areas in the shared choices (not in each person's data,
which the relay keeps to 8 KB). Technical choices by Claude under the owner's 2026-10-23 22:30
rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270624_335"
down_revision: str | None = "20270623_334"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The Unit Check areas (mock-up v14), in form order, with the problem type a finding gets.
AREAS: tuple[tuple[str, str, str, str], ...] = (
    ("LIVING", "Living room", "បន្ទប់ទទួលភ្ញៀវ", "OTHER"),
    ("BEDROOM", "Bedroom", "បន្ទប់គេង", "OTHER"),
    ("BATHROOM", "Bathroom", "បន្ទប់ទឹក", "OTHER"),
    ("KITCHEN", "Kitchen", "ផ្ទះបាយ", "OTHER"),
    ("BALCONY", "Balcony", "រានហាល", "OTHER"),
    ("AIR_CONDITIONER", "Air conditioner", "ម៉ាស៊ីនត្រជាក់", "AIR_CONDITIONER"),
    ("KEYS", "Keys, key cards and remotes", "សោ កាតសោ និងរីម៉ូត", "DOOR_LOCK"),
)
AREA_CODES = ", ".join(f"'{code}'" for code, *_ in AREAS)
AREA_ROWS = ",\n            ".join(
    f"('{code}', '{en}', '{km}', '{kind}', {index})"
    for index, (code, en, km, kind) in enumerate(AREAS, start=1)
)

TABLES = f"""
    ALTER TABLE app.problem_report_media DROP CONSTRAINT problem_report_media_stage_check;
    ALTER TABLE app.problem_report_media ADD CONSTRAINT problem_report_media_stage_check
        CHECK (stage IN ('REPORTED', 'CHECK', 'DONE', 'RECEIPT'));

    CREATE TABLE app.staff_unit_checks (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        unit_id uuid NOT NULL REFERENCES app.units (id) ON DELETE RESTRICT,
        inbound_event_id uuid NOT NULL UNIQUE
            REFERENCES app.telegram_inbound_events (id) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        check_date date NOT NULL,
        kind text NOT NULL CHECK (kind IN ('REGULAR', 'AFTER_REPAIR')),
        areas jsonb NOT NULL CHECK (jsonb_typeof(areas) = 'object' AND areas <> '{{}}'::jsonb),
        note text CHECK (note = btrim(note) AND length(note) BETWEEN 1 AND 500),
        findings smallint NOT NULL CHECK (findings BETWEEN 0 AND 7),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX staff_unit_checks_unit_idx ON app.staff_unit_checks (unit_id, check_date);
    COMMENT ON TABLE app.staff_unit_checks IS
        'Telegram bots step 4e (DL-178): a Unit Check sent from the Staff bot.';

    CREATE TABLE app.staff_unit_check_findings (
        check_id uuid NOT NULL REFERENCES app.staff_unit_checks (id) ON DELETE RESTRICT,
        area text NOT NULL CHECK (area IN ({AREA_CODES})),
        state text NOT NULL CHECK (state IN ('BROKEN', 'MISSING')),
        finding text NOT NULL CHECK (finding = btrim(finding) AND length(finding) BETWEEN 1 AND 300),
        photos smallint NOT NULL CHECK (photos BETWEEN 1 AND 5),
        report_id uuid NOT NULL UNIQUE REFERENCES app.problem_reports (id) ON DELETE RESTRICT,
        PRIMARY KEY (check_id, area)
    );
    COMMENT ON TABLE app.staff_unit_check_findings IS
        'Telegram bots step 4e (DL-178): a Broken or Missing area of a Unit Check and its Unit Problem.';

    CREATE TABLE app.staff_maintenance_checks (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        report_id uuid NOT NULL REFERENCES app.problem_reports (id) ON DELETE RESTRICT,
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        inbound_event_id uuid NOT NULL UNIQUE
            REFERENCES app.telegram_inbound_events (id) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        employee_id uuid NOT NULL REFERENCES app.employees (id) ON DELETE RESTRICT,
        entry text NOT NULL CHECK (entry IN ('URGENT', 'TENANT_OK', 'NOTICE')),
        cause text NOT NULL CHECK (cause IN ('WEAR', 'DAMAGE', 'UNSURE')),
        fixed boolean NOT NULL,
        note text CHECK (note = btrim(note) AND length(note) BETWEEN 1 AND 400),
        photos smallint NOT NULL CHECK (photos BETWEEN 1 AND 5),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX staff_maintenance_checks_report_idx ON app.staff_maintenance_checks (report_id);
    COMMENT ON TABLE app.staff_maintenance_checks IS
        'Telegram bots step 4e (DL-178): a planned visit checked by the Technician in the Staff bot.';

    CREATE TRIGGER staff_unit_checks_append_only BEFORE UPDATE OR DELETE ON app.staff_unit_checks
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER staff_unit_checks_no_truncate BEFORE TRUNCATE ON app.staff_unit_checks
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER staff_unit_check_findings_append_only BEFORE UPDATE OR DELETE
        ON app.staff_unit_check_findings
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER staff_unit_check_findings_no_truncate BEFORE TRUNCATE
        ON app.staff_unit_check_findings
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER staff_maintenance_checks_append_only BEFORE UPDATE OR DELETE
        ON app.staff_maintenance_checks
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER staff_maintenance_checks_no_truncate BEFORE TRUNCATE
        ON app.staff_maintenance_checks
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
"""

FUNCTIONS = """
    -- The Unit Check areas in form order: the code, the words and the problem type of a finding.
    CREATE FUNCTION app.staff_unit_areas()
    RETURNS TABLE (code text, name_en text, name_km text, problem_code text, sort_order integer)
    LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT * FROM (VALUES
            __AREA_ROWS__
        ) AS area (code, name_en, name_km, problem_code, sort_order)
    $$;

    -- The planned visits a Technician can check (Visit planned), with what the form shows: the
    -- urgent ones first, then the soonest visit, at most 12. They go in the shared choices.
    CREATE FUNCTION app.telegram_staff_visits(p_property uuid) RETURNS jsonb
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT COALESCE(jsonb_agg(visit.body ORDER BY visit.urgent DESC, visit.visit_on,
            visit.visit_at, visit.created_at), '[]'::jsonb)
        FROM (
            SELECT report.urgent, report.visit_on, report.visit_at, report.created_at,
                jsonb_build_object('report_id', report.id, 'report_number', report.report_number,
                'kind', report.kind, 'unit', unit.unit_number, 'place_km', place.name_kh,
                'floor', report.floor_label, 'type_km', kind.name_kh, 'icon', kind.icon,
                'urgent', report.urgent, 'visit_on', to_char(report.visit_on, 'DD/MM'),
                'visit_at', to_char(report.visit_at, 'HH24:MI'),
                'description', left(report.description, 100)) AS body
            FROM app.problem_reports AS report
            JOIN app.problem_types AS kind ON kind.id = report.problem_type_id
            LEFT JOIN app.units AS unit ON unit.id = report.unit_id
            LEFT JOIN app.problem_places AS place ON place.id = report.problem_place_id
            WHERE report.property_id = p_property
              AND app.problem_report_state(report.id) = 'PLANNED'
            ORDER BY report.urgent DESC, report.visit_on, report.visit_at, report.created_at
            LIMIT 12
        ) AS visit
    $$;

    -- Who may open the Staff forms and what they show (replaces step 4d's list): the same as
    -- before, and the choices add the planned visits and the Unit Check areas.
    CREATE OR REPLACE FUNCTION app.telegram_staff_form_data(p_property uuid, p_actor uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_now timestamptz := statement_timestamp();
        v_today date;
        v_users jsonb;
        v_jobs jsonb;
        v_choices jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT timezone(property.timezone_name, v_now)::date INTO v_today
        FROM app.properties AS property WHERE property.id = p_property;
        v_jobs := app.telegram_staff_jobs(p_property);
        SELECT coalesce(jsonb_agg(jsonb_build_object('id', person.telegram_user_id,
                'role', 'STAFF', 'data', jsonb_build_object('name_km', person.name_km,
                    'name_en', person.name_en, 'roles', person.roles,
                    'shift_code', person.shift_code, 'shift_km', person.shift_km)
                    || CASE WHEN person.roles ? 'TECHNICIAN'
                        THEN jsonb_build_object('jobs', v_jobs) ELSE '{}'::jsonb END
                    || app.telegram_staff_checklist_person(person.employee_id, person.roles, v_now))
                ORDER BY person.telegram_user_id), '[]'::jsonb)
        INTO v_users
        FROM (
            SELECT link.telegram_user_id, employee.id AS employee_id, employee.name_km,
                employee.name_en, jsonb_agg(DISTINCT link.report_role) AS roles, job.shift_code,
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
        -- uses the meters (Unit numbers and last readings only, no names). The checklists show
        -- the tasks due today. The Maintenance check shows the planned visits, and the Unit
        -- Check its areas.
        v_choices := (app.telegram_tenant_form_data(p_property, p_actor) -> 'choices')
            || jsonb_build_object('units', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'id', unit.id, 'number', unit.unit_number) ORDER BY unit.unit_number)
                FROM app.units AS unit WHERE unit.property_id = p_property), '[]'::jsonb),
                'meters', app.telegram_staff_meters(p_property, v_today),
                'checklists', app.telegram_staff_checklists(v_today),
                'visits', app.telegram_staff_visits(p_property),
                'unit_areas', (SELECT jsonb_agg(jsonb_build_object('code', area.code,
                        'km', area.name_km) ORDER BY area.sort_order)
                    FROM app.staff_unit_areas() AS area));
        RETURN jsonb_build_object('users', v_users, 'choices', v_choices);
    END $$;

    -- The photos a form brought: images only, in the order sent. NULL means a wrong file.
    CREATE FUNCTION app.staff_form_photos(p_media jsonb) RETURNS app.media_files[]
    LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
    DECLARE
        v_file app.media_files%ROWTYPE;
        v_files app.media_files[] := '{}';
    BEGIN
        BEGIN
            FOR v_file IN SELECT * FROM app.staff_form_files(p_media) LOOP
                IF v_file.content_type NOT LIKE 'image/%' THEN
                    RETURN NULL;
                END IF;
                v_files := v_files || v_file;
            END LOOP;
        EXCEPTION WHEN invalid_parameter_value THEN
            RETURN NULL;
        END;
        RETURN v_files;
    END $$;

    -- 1. A Unit Check (the pulled item ``p_inbound``): each Broken or Missing area becomes a
    -- Unit Problem with its photos. The same form twice saves it once.
    CREATE FUNCTION app.telegram_staff_unit_check(p_property uuid, p_inbound uuid,
        p_form jsonb, p_media jsonb, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date;
        v_sender record;
        v_done app.staff_unit_checks%ROWTYPE;
        v_unit uuid;
        v_kind text;
        v_areas jsonb;
        v_findings jsonb;
        v_finding jsonb;
        v_key text;
        v_state text;
        v_text text;
        v_count numeric;
        v_note text;
        v_plan jsonb := '[]'::jsonb;
        v_item jsonb;
        v_area record;
        v_files app.media_files[];
        v_file app.media_files%ROWTYPE;
        v_used integer := 0;
        v_photos integer;
        v_id uuid := gen_random_uuid();
        v_report uuid;
        v_number text;
        v_numbers text[] := '{}';
        v_type app.problem_types%ROWTYPE;
        v_lease uuid;
        v_customer uuid;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        v_day := app.gl_today(p_property);
        SELECT sender.* INTO v_sender FROM app.staff_form_sender(p_property, p_inbound) AS sender;
        SELECT done.* INTO v_done FROM app.staff_unit_checks AS done
        WHERE done.inbound_event_id = p_inbound;
        IF FOUND THEN
            RETURN jsonb_build_object('result', 'SENT', 'repeated', true,
                'findings', v_done.findings,
                'numbers', COALESCE((SELECT jsonb_agg(report.report_number ORDER BY area.sort_order)
                    FROM app.staff_unit_check_findings AS finding
                    JOIN app.problem_reports AS report ON report.id = finding.report_id
                    JOIN app.staff_unit_areas() AS area ON area.code = finding.area
                    WHERE finding.check_id = v_done.id), '[]'::jsonb));
        END IF;
        IF v_sender.employee_id IS NULL THEN
            RETURN jsonb_build_object('result', 'NOT_LINKED');
        END IF;
        IF NOT v_sender.roles && ARRAY['TECHNICIAN', 'AUTHORIZER'] THEN
            RETURN jsonb_build_object('result', 'NOT_ROLE');
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
        v_kind := p_form ->> 'kind';
        IF v_kind IS NULL OR v_kind NOT IN ('REGULAR', 'AFTER_REPAIR') THEN
            RETURN app.staff_form_refused('kind');
        END IF;
        -- Each area at most once, Good, Broken or Missing; at least one area.
        v_areas := p_form -> 'areas';
        IF v_areas IS NULL OR jsonb_typeof(v_areas) <> 'object' OR v_areas = '{}'::jsonb
            OR EXISTS (SELECT 1 FROM jsonb_each(v_areas) AS picked
                       WHERE picked.key NOT IN (SELECT area.code FROM app.staff_unit_areas() AS area)
                          OR jsonb_typeof(picked.value) <> 'string'
                          OR picked.value #>> '{}' NOT IN ('GOOD', 'BROKEN', 'MISSING')) THEN
            RETURN app.staff_form_refused('areas');
        END IF;
        -- What is wrong and how many photos, for exactly the Broken and Missing areas.
        v_findings := COALESCE(p_form -> 'findings', '{}'::jsonb);
        IF jsonb_typeof(v_findings) <> 'object' THEN
            RETURN app.staff_form_refused('findings');
        END IF;
        FOR v_area IN SELECT area.* FROM app.staff_unit_areas() AS area ORDER BY area.sort_order LOOP
            v_state := v_areas ->> v_area.code;
            v_finding := v_findings -> v_area.code;
            IF v_state IS NULL OR v_state = 'GOOD' THEN
                IF v_finding IS NOT NULL THEN
                    RETURN app.staff_form_refused('findings');
                END IF;
                CONTINUE;
            END IF;
            IF v_finding IS NULL OR jsonb_typeof(v_finding) <> 'object' THEN
                RETURN app.staff_form_refused('findings');
            END IF;
            BEGIN
                v_text := app.staff_form_text(v_finding -> 'text', 300);
            EXCEPTION WHEN SQLSTATE 'PRS01' THEN
                RETURN app.staff_form_refused('findings');
            END;
            IF v_text IS NULL THEN
                RETURN app.staff_form_refused('findings');
            END IF;
            IF jsonb_typeof(v_finding -> 'photos') IS DISTINCT FROM 'number' THEN
                RETURN app.staff_form_refused('photo');
            END IF;
            v_count := (v_finding ->> 'photos')::numeric;
            IF v_count <> trunc(v_count) OR v_count NOT BETWEEN 1 AND 5 THEN
                RETURN app.staff_form_refused('photo');
            END IF;
            v_plan := v_plan || jsonb_build_object('area', v_area.code, 'state', v_state,
                'text', v_text, 'photos', v_count::integer, 'name_en', v_area.name_en,
                'problem_code', v_area.problem_code);
        END LOOP;
        IF EXISTS (SELECT 1 FROM jsonb_object_keys(v_findings) AS picked (key)
                   WHERE NOT (v_areas ? picked.key)) THEN
            RETURN app.staff_form_refused('findings');
        END IF;
        BEGIN
            v_note := app.staff_form_text(p_form -> 'note', 500);
        EXCEPTION WHEN SQLSTATE 'PRS01' THEN
            RETURN app.staff_form_refused('note');
        END;
        -- The photos, area by area in form order, exactly as many as the findings say.
        v_files := app.staff_form_photos(p_media);
        IF v_files IS NULL THEN
            RETURN app.staff_form_refused('files');
        END IF;
        IF cardinality(v_files) <> COALESCE((SELECT sum((item ->> 'photos')::integer)
                FROM jsonb_array_elements(v_plan) AS item), 0) THEN
            RETURN app.staff_form_refused('photo');
        END IF;
        INSERT INTO app.staff_unit_checks (id, property_id, unit_id, inbound_event_id,
            telegram_user_id, employee_id, check_date, kind, areas, note, findings, created_by)
        VALUES (v_id, p_property, v_unit, p_inbound, v_sender.telegram_user_id,
            v_sender.employee_id, v_day, v_kind, v_areas, v_note, jsonb_array_length(v_plan),
            p_actor);
        IF jsonb_array_length(v_plan) > 0 THEN
            SELECT current.lease_id, current.customer_id INTO v_lease, v_customer
            FROM app.problem_unit_lease(v_unit, v_day) AS current;
        END IF;
        FOR v_item IN SELECT value FROM jsonb_array_elements(v_plan) WITH ORDINALITY ORDER BY ordinality LOOP
            v_type := NULL;
            SELECT kind.* INTO v_type FROM app.problem_types AS kind
            WHERE kind.code = v_item ->> 'problem_code' AND kind.active;
            IF v_type.id IS NULL THEN
                SELECT kind.* INTO v_type FROM app.problem_types AS kind WHERE kind.code = 'OTHER';
            END IF;
            v_report := gen_random_uuid();
            v_number := app.take_document_number('UNIT_PROBLEM', date_part('year', v_day)::integer);
            INSERT INTO app.problem_reports (id, property_id, report_number, kind, unit_id,
                lease_id, customer_id, problem_place_id, floor_label, problem_type_id, description,
                urgent, always_urgent, may_enter, best_time, source, reported_by, created_by)
            VALUES (v_report, p_property, v_number, 'UNIT', v_unit, v_lease, v_customer, NULL,
                NULL, v_type.id,
                CASE v_kind WHEN 'REGULAR' THEN 'Unit Check: ' ELSE 'Unit Check after a repair: ' END
                    || (v_item ->> 'name_en') || ', '
                    || CASE v_item ->> 'state' WHEN 'BROKEN' THEN 'broken' ELSE 'missing' END
                    || '. ' || (v_item ->> 'text'),
                v_type.always_urgent, v_type.always_urgent, false, 'ANY', 'STAFF_BOT',
                v_sender.name, p_actor);
            v_photos := (v_item ->> 'photos')::integer;
            PERFORM app.problem_report_event(v_report, 'RECEIVED', NULL,
                jsonb_build_object('source', 'STAFF_BOT', 'photos', v_photos, 'voice', false,
                    'unit_check', v_item ->> 'area'), p_actor);
            FOREACH v_file IN ARRAY v_files[v_used + 1 : v_used + v_photos] LOOP
                PERFORM app.staff_keep_report_file(v_report, v_file, 'REPORTED', p_actor);
            END LOOP;
            v_used := v_used + v_photos;
            INSERT INTO app.staff_unit_check_findings (check_id, area, state, finding, photos,
                report_id)
            VALUES (v_id, v_item ->> 'area', v_item ->> 'state', v_item ->> 'text', v_photos,
                v_report);
            PERFORM app.product_audit(p_property, p_actor, v_day, 'problem_report.added',
                'problem_report', v_report, 'Unit Check finding from the Staff bot',
                'telegram.operate', NULL, jsonb_build_object('report_number', v_number,
                    'kind', 'UNIT', 'source', 'STAFF_BOT', 'area', v_item ->> 'area'), NULL);
            v_numbers := v_numbers || v_number;
        END LOOP;
        PERFORM app.product_audit(p_property, p_actor, v_day, 'staff.unit_check.sent',
            'staff_unit_check', v_id, 'Unit Check from the Staff bot', 'telegram.operate',
            NULL, jsonb_build_object('kind', v_kind, 'findings', jsonb_array_length(v_plan),
                'reports', to_jsonb(v_numbers)), NULL);
        RETURN jsonb_build_object('result', 'SENT', 'repeated', false,
            'findings', jsonb_array_length(v_plan), 'numbers', to_jsonb(v_numbers));
    END $$;

    -- 2. A Maintenance check: the Technician's check of a planned visit (cause, how staff
    -- entered, fixed at once, photos). The report is Checked; who pays is decided in the app.
    -- The same form twice checks it once.
    CREATE FUNCTION app.telegram_staff_maintenance_check(p_property uuid, p_inbound uuid,
        p_form jsonb, p_media jsonb, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date;
        v_sender record;
        v_done app.staff_maintenance_checks%ROWTYPE;
        v_report app.problem_reports%ROWTYPE;
        v_report_id uuid;
        v_entry text;
        v_cause text;
        v_fixed boolean := false;
        v_note text;
        v_files app.media_files[];
        v_file app.media_files%ROWTYPE;
        v_id uuid := gen_random_uuid();
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        v_day := app.gl_today(p_property);
        SELECT sender.* INTO v_sender FROM app.staff_form_sender(p_property, p_inbound) AS sender;
        SELECT done.* INTO v_done FROM app.staff_maintenance_checks AS done
        WHERE done.inbound_event_id = p_inbound;
        IF FOUND THEN
            RETURN jsonb_build_object('result', 'CHECKED', 'repeated', true,
                'report_number', (SELECT report.report_number FROM app.problem_reports AS report
                                  WHERE report.id = v_done.report_id),
                'cause', v_done.cause, 'fixed', v_done.fixed);
        END IF;
        IF v_sender.employee_id IS NULL THEN
            RETURN jsonb_build_object('result', 'NOT_LINKED');
        END IF;
        IF NOT v_sender.roles && ARRAY['TECHNICIAN', 'AUTHORIZER'] THEN
            RETURN jsonb_build_object('result', 'NOT_ROLE');
        END IF;
        IF p_form IS NULL OR jsonb_typeof(p_form) <> 'object' THEN
            RETURN app.staff_form_refused('not_a_form');
        END IF;
        BEGIN
            v_report_id := (p_form ->> 'report_id')::uuid;
        EXCEPTION WHEN data_exception THEN
            RETURN app.staff_form_refused('visit');
        END;
        v_entry := p_form ->> 'entry';
        IF v_entry IS NULL OR v_entry NOT IN ('URGENT', 'TENANT_OK', 'NOTICE') THEN
            RETURN app.staff_form_refused('entry');
        END IF;
        v_cause := p_form ->> 'cause';
        IF v_cause IS NULL OR v_cause NOT IN ('WEAR', 'DAMAGE', 'UNSURE') THEN
            RETURN app.staff_form_refused('cause');
        END IF;
        IF p_form ? 'fixed' THEN
            IF jsonb_typeof(p_form -> 'fixed') <> 'boolean' THEN
                RETURN app.staff_form_refused('fixed');
            END IF;
            v_fixed := (p_form ->> 'fixed')::boolean;
        END IF;
        BEGIN
            v_note := app.staff_form_text(p_form -> 'note', 400);
        EXCEPTION WHEN SQLSTATE 'PRS01' THEN
            RETURN app.staff_form_refused('note');
        END;
        -- 1 to 5 photos of what was found.
        v_files := app.staff_form_photos(p_media);
        IF v_files IS NULL THEN
            RETURN app.staff_form_refused('files');
        END IF;
        IF cardinality(v_files) NOT BETWEEN 1 AND 5 THEN
            RETURN app.staff_form_refused('photo');
        END IF;
        SELECT report.* INTO v_report FROM app.problem_reports AS report
        WHERE report.id = v_report_id AND report.property_id = p_property FOR UPDATE;
        IF NOT FOUND THEN
            RETURN app.staff_form_refused('visit');
        END IF;
        IF app.problem_report_state(v_report.id) <> 'PLANNED' THEN
            RETURN jsonb_build_object('result', 'NOT_PLANNED', 'report_number', v_report.report_number);
        END IF;
        IF v_fixed AND NOT v_report.urgent THEN
            RETURN app.staff_form_refused('fixed');
        END IF;
        PERFORM app.problem_report_step(p_property, v_report.id, v_report.version, 'CHECKED',
            jsonb_build_object('cause', v_cause, 'fixed', v_fixed,
                'note', left(concat_ws(' ', 'Checked in the Staff bot by ' || v_sender.name || '.',
                    CASE v_entry WHEN 'URGENT' THEN 'Entered: urgent.'
                        WHEN 'TENANT_OK' THEN 'Entered: the tenant agreed.'
                        ELSE 'Entered: notice given first.' END,
                    v_note), 500)),
            p_actor, NULL);
        FOREACH v_file IN ARRAY v_files LOOP
            PERFORM app.staff_keep_report_file(v_report.id, v_file, 'CHECK', p_actor);
        END LOOP;
        INSERT INTO app.staff_maintenance_checks (id, report_id, property_id, inbound_event_id,
            telegram_user_id, employee_id, entry, cause, fixed, note, photos, created_by)
        VALUES (v_id, v_report.id, p_property, p_inbound, v_sender.telegram_user_id,
            v_sender.employee_id, v_entry, v_cause, v_fixed, v_note, cardinality(v_files), p_actor);
        PERFORM app.product_audit(p_property, p_actor, v_day, 'staff.maintenance_check.sent',
            'problem_report', v_report.id, 'Maintenance check from the Staff bot',
            'telegram.operate', NULL, jsonb_build_object('report_number', v_report.report_number,
                'entry', v_entry, 'cause', v_cause, 'fixed', v_fixed), NULL);
        RETURN jsonb_build_object('result', 'CHECKED', 'repeated', false,
            'report_number', v_report.report_number, 'cause', v_cause, 'fixed', v_fixed);
    END $$;
""".replace("__AREA_ROWS__", AREA_ROWS)

RUNTIME = (
    "app.telegram_staff_unit_check(uuid, uuid, jsonb, jsonb, uuid)",
    "app.telegram_staff_maintenance_check(uuid, uuid, jsonb, jsonb, uuid)",
)
INTERNAL = (
    "app.staff_unit_areas()",
    "app.telegram_staff_visits(uuid)",
    "app.staff_form_photos(jsonb)",
)
TABLE_NAMES = "app.staff_unit_checks, app.staff_unit_check_findings, app.staff_maintenance_checks"


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    op.execute(f"REVOKE ALL ON TABLE {TABLE_NAMES} FROM PUBLIC, prm_runtime, prm_bootstrap")
    for signature in RUNTIME + INTERNAL:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in RUNTIME:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("the Staff bot Unit Check migration is forward-only")
