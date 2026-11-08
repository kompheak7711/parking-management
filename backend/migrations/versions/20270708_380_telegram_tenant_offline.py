# ruff: noqa: E501
"""Telegram bots: the Tenant bot answers while the app is closed (DL-210).

Owner (7 Nov 2026): "I want tenant report 24/7" and "I don't want to open application 24/7"; on the
card the owner chose "Bot answers by itself": the relay links a new tenant at night with the
scrambled check list, opens the Problem report form, answers a sent report at once, sends an
urgent report to the caretaker at once, and the app collects every report with its number when
it opens.

1. ``app.telegram_tenant_offline_data`` gives the pull job what the relay needs to answer while
   the office is away (``telegram.operate``): each person a Lease link may name today (the same
   people, phone format, name words and Unit key as ``app.telegram_tenant_link``), each Unit's
   number and places, the problem types and shared places by id, and who gets an urgent alert:
   the Authorizers, and each caretaker with the times of their shifts from yesterday to the day
   after tomorrow. The pull job turns names and phones into keyed hashes before anything leaves
   the office; the relay never gets a name or a phone number.
2. ``app.telegram_tenant_form_data`` also gives each linked tenant's Unit number, so an urgent
   alert sent by the relay says where.
3. The urgent alert (DL-175) is not queued again for a report the relay already alerted: the pull
   job saves such a report with ``prm.relay_alerted`` set for its transaction.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270708_380"
down_revision: str | None = "20270708_373"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTIONS = """
    -- The places of one Unit, as the Tenant bot form shows them (migration 20270521_283).
    CREATE FUNCTION app.tenant_unit_places(p_unit uuid) RETURNS jsonb
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT COALESCE((SELECT jsonb_agg(jsonb_build_object('item_id', item.id,
                'number', number, 'count', feature.feature_count,
                'name_en', item.name_en, 'name_kh', item.name_km)
                ORDER BY item.sort_order, item.name_en, number)
            FROM app.unit_features AS feature
            JOIN app.unit_setup_items AS item ON item.id = feature.item_id
            CROSS JOIN generate_series(1, feature.feature_count) AS number
            WHERE feature.unit_id = p_unit), '[]'::jsonb)
    $$;

    CREATE OR REPLACE FUNCTION app.telegram_tenant_form_data(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_choices jsonb;
        v_users jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        v_choices := jsonb_build_object(
            'types', COALESCE((SELECT jsonb_agg(jsonb_build_object('id', kind.id,
                    'code', kind.code, 'name_en', kind.name_en, 'name_kh', kind.name_kh,
                    'icon', kind.icon, 'always_urgent', kind.always_urgent)
                    ORDER BY kind.sort_order)
                FROM app.problem_types AS kind WHERE kind.active), '[]'::jsonb),
            'places', COALESCE((SELECT jsonb_agg(jsonb_build_object('id', place.id,
                    'code', place.code, 'name_en', place.name_en, 'name_kh', place.name_kh)
                    ORDER BY place.sort_order)
                FROM app.problem_places AS place WHERE place.active), '[]'::jsonb),
            'open_building', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'report_id', report.id, 'report_number', report.report_number,
                    'problem_place_id', report.problem_place_id,
                    'problem_type_id', report.problem_type_id, 'floor', report.floor_label)
                    ORDER BY report.created_at)
                FROM app.problem_reports AS report
                WHERE report.property_id = p_property AND report.kind = 'BUILDING'
                  AND app.problem_report_state(report.id)
                      NOT IN ('DONE', 'CLOSED', 'NOT_ACCEPTED', 'JOINED')), '[]'::jsonb));
        SELECT COALESCE(jsonb_agg(jsonb_build_object('id', person.telegram_user_id,
                'role', 'TENANT', 'data', jsonb_build_object('places', person.places,
                    'unit', person.unit_number))
                ORDER BY person.telegram_user_id), '[]'::jsonb)
        INTO v_users
        FROM (
            SELECT link.telegram_user_id, unit.unit_number,
                app.tenant_unit_places(link.unit_id) AS places
            FROM (
                SELECT DISTINCT ON (link.telegram_user_id) link.telegram_user_id, link.unit_id
                FROM app.tenant_telegram_links AS link
                JOIN app.leases AS lease ON lease.id = link.lease_id
                WHERE link.property_id = p_property
                  AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                                  WHERE ending.link_id = link.id)
                  AND lease.status = 'SIGNED' AND lease.end_date >= app.gl_today(p_property)
                ORDER BY link.telegram_user_id, link.linked_at DESC
            ) AS link
            JOIN app.units AS unit ON unit.id = link.unit_id
        ) AS person;
        RETURN jsonb_build_object('choices', v_choices, 'users', v_users);
    END $$;

    -- What the relay needs to answer the Tenant bot while the office is away (DL-210).
    CREATE FUNCTION app.telegram_tenant_offline_data(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date := app.gl_today(p_property);
        v_hr_day date := timezone(app.hr_zone(), statement_timestamp())::date;
        v_people jsonb;
        v_units jsonb;
        v_always jsonb;
        v_shifts jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        -- Each person a link may name, with the forms of the name app.tenant_names_match
        -- accepts: the words in any order, written together, and written together backwards.
        SELECT COALESCE(jsonb_agg(jsonb_build_object('unit_id', person.unit_id,
                'phones', person.phones, 'names', jsonb_build_array(
                    's:' || array_to_string(ARRAY(SELECT word FROM unnest(person.words) AS word
                        ORDER BY word), ' '),
                    'c:' || array_to_string(person.words, ''),
                    'c:' || array_to_string(ARRAY(SELECT word FROM unnest(person.words)
                        WITH ORDINALITY AS part(word, position) ORDER BY position DESC), '')))
                ORDER BY person.unit_id, person.customer_id), '[]'::jsonb)
        INTO v_people
        FROM (
            SELECT DISTINCT ON (link.unit_id, link.customer_id) link.unit_id, link.customer_id,
                app.tenant_name_words(link.legal_name) AS words,
                (SELECT COALESCE(jsonb_agg(DISTINCT app.phone_e164(part.number))
                        FILTER (WHERE app.phone_e164(part.number) IS NOT NULL), '[]'::jsonb)
                 FROM regexp_split_to_table(COALESCE(link.phone_number, ''), '[/,;]')
                     AS part(number)) AS phones
            FROM app.tenant_link_people(p_property, v_day) AS link
            ORDER BY link.unit_id, link.customer_id, link.start_date DESC
        ) AS person
        WHERE cardinality(person.words) > 0 AND jsonb_array_length(person.phones) > 0;
        SELECT COALESCE(jsonb_object_agg(unit.id, jsonb_build_object(
                'unit', unit.unit_number, 'unit_key', app.tenant_unit_key(unit.unit_number),
                'places', app.tenant_unit_places(unit.id))), '{}'::jsonb)
        INTO v_units
        FROM app.units AS unit
        WHERE unit.id IN (SELECT DISTINCT link.unit_id
                          FROM app.tenant_link_people(p_property, v_day) AS link);
        -- Who gets an urgent alert, as app.telegram_staff_urgent_alert picks them.
        SELECT COALESCE(jsonb_agg(DISTINCT link.telegram_user_id), '[]'::jsonb)
        INTO v_always
        FROM app.employee_telegram_links AS link
        JOIN app.employees AS employee ON employee.id = link.employee_id
        WHERE employee.property_id = p_property AND link.report_role = 'AUTHORIZER'
          AND app.hr_link_live(link.id, v_hr_day);
        SELECT COALESCE(jsonb_agg(jsonb_build_array(shift.telegram_user_id,
                extract(epoch FROM shift.starts_at)::bigint, extract(epoch FROM shift.ends_at)::bigint)
                ORDER BY shift.starts_at, shift.telegram_user_id), '[]'::jsonb)
        INTO v_shifts
        FROM (
            SELECT DISTINCT link.telegram_user_id, times.starts_at, times.ends_at
            FROM app.employee_telegram_links AS link
            JOIN app.employees AS employee ON employee.id = link.employee_id
            CROSS JOIN generate_series(v_hr_day - 1, v_hr_day + 2, interval '1 day') AS day (work_date)
            CROSS JOIN LATERAL app.hr_shift_on(employee.id, day.work_date::date) AS planned
            CROSS JOIN LATERAL app.hr_shift_times(planned.shift_code, day.work_date::date) AS times
            WHERE employee.property_id = p_property AND link.report_role = 'CARETAKER'
              AND planned.shift_code IS NOT NULL
              AND app.hr_link_live(link.id, day.work_date::date)
        ) AS shift;
        RETURN jsonb_build_object(
            'people', v_people,
            'units', v_units,
            'types', COALESCE((SELECT jsonb_object_agg(kind.id, jsonb_build_object(
                    'name_kh', kind.name_kh, 'always_urgent', kind.always_urgent))
                FROM app.problem_types AS kind WHERE kind.active), '{}'::jsonb),
            'places', COALESCE((SELECT jsonb_object_agg(place.id, place.name_kh)
                FROM app.problem_places AS place WHERE place.active), '{}'::jsonb),
            'alert', jsonb_build_object('always', v_always, 'shifts', v_shifts));
    END $$;

    -- The urgent alert (DL-175), not queued again when the relay already sent it (DL-210).
    CREATE OR REPLACE FUNCTION app.telegram_staff_urgent_alert() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_report app.problem_reports%ROWTYPE;
        v_now timestamptz := statement_timestamp();
        v_today date := timezone(app.hr_zone(), statement_timestamp())::date;
        v_sender bigint;
        v_details jsonb;
    BEGIN
        IF current_setting('prm.relay_alerted', true) = 'on' THEN
            RETURN NULL;
        END IF;
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
"""

RUNTIME = ("app.telegram_tenant_offline_data(uuid, uuid)",)
INTERNAL = ("app.tenant_unit_places(uuid)",)


def upgrade() -> None:
    op.execute(FUNCTIONS)
    for signature in RUNTIME + INTERNAL:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in RUNTIME:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("the Tenant bot offline migration is forward-only")
