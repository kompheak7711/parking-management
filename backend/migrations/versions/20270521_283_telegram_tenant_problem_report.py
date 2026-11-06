# ruff: noqa: E501
"""Telegram bots, step 2b: a linked tenant sends a Problem report from the Tenant bot (DL-127).

Owner rules (3 Nov 2026, tenant mock-up v15, Problem report Part B): a linked tenant taps
Problem report, then Unit Problem or Building problem, and fills one short form (a Telegram Mini
App). The tenant taps the problem type first. Safety, flooding and a risk of electric shock are
always urgent. The tenant writes what is wrong, sends a voice note (up to 1 minute), or both, and
may add up to 5 photos. A Unit Problem also asks if it is urgent, if staff may enter when the
tenant is out, and the best time. A Building problem asks where (and the floor), then shows the
open Building problems there: "Same problem" joins that report (DL-124), "Something else" makes
a new one. The report goes into the one Problem reports list with source TENANT_BOT.

1. ``problem_report_media``: the photos, videos and voice notes of a report (files kept once in
   ``media_files``, DL-125).
2. ``tenant_problem_report_sources``: which Telegram form made which report, so each form makes
   one report only and later steps can tell the tenant about their report.
3. ``media_files`` also takes ``audio/webm`` (voice notes recorded on Android phones).

The functions run as the account the Telegram jobs run as (``telegram.operate``). Technical
choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270521_283"
down_revision: str | None = "20270520_282"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = """
    ALTER TABLE app.media_files DROP CONSTRAINT media_files_content_type_check;
    ALTER TABLE app.media_files ADD CONSTRAINT media_files_content_type_check CHECK (
        content_type IN ('image/jpeg', 'image/png', 'image/webp', 'video/mp4', 'audio/ogg',
            'audio/mpeg', 'audio/mp4', 'audio/webm'));

    CREATE TABLE app.problem_report_media (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        report_id uuid NOT NULL REFERENCES app.problem_reports (id) ON DELETE RESTRICT,
        media_file_id uuid NOT NULL REFERENCES app.media_files (id) ON DELETE RESTRICT,
        kind text NOT NULL CHECK (kind IN ('PHOTO', 'VIDEO', 'VOICE')),
        stage text NOT NULL CHECK (stage IN ('REPORTED')),
        position smallint NOT NULL CHECK (position BETWEEN 1 AND 10),
        added_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        added_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT problem_report_media_position UNIQUE (report_id, stage, position),
        CONSTRAINT problem_report_media_once UNIQUE (report_id, media_file_id)
    );
    COMMENT ON TABLE app.problem_report_media IS
        'Telegram bots step 2b (DL-127): photos, videos and voice notes of a Problem report.';

    CREATE TABLE app.tenant_problem_report_sources (
        report_id uuid PRIMARY KEY REFERENCES app.problem_reports (id) ON DELETE RESTRICT,
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        inbound_event_id uuid NOT NULL UNIQUE
            REFERENCES app.telegram_inbound_events (id) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        link_id uuid NOT NULL REFERENCES app.tenant_telegram_links (id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX tenant_problem_report_sources_person_idx
        ON app.tenant_problem_report_sources (property_id, telegram_user_id, created_at DESC);

    CREATE TRIGGER problem_report_media_append_only BEFORE UPDATE OR DELETE
        ON app.problem_report_media
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER problem_report_media_no_truncate BEFORE TRUNCATE ON app.problem_report_media
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER tenant_problem_report_sources_append_only BEFORE UPDATE OR DELETE
        ON app.tenant_problem_report_sources
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER tenant_problem_report_sources_no_truncate BEFORE TRUNCATE
        ON app.tenant_problem_report_sources
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
"""

FUNCTIONS = """
    -- 1. What the Tenant bot form shows, for the relay: the problem types, the shared places and
    -- the open Building problems (number, place, type and floor only), and for each linked
    -- person the places in their Unit. No names, no phone numbers, no Unit numbers.
    CREATE FUNCTION app.telegram_tenant_form_data(p_property uuid, p_actor uuid)
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
                'role', 'TENANT', 'data', jsonb_build_object('places', person.places))
                ORDER BY person.telegram_user_id), '[]'::jsonb)
        INTO v_users
        FROM (
            SELECT link.telegram_user_id,
                COALESCE((SELECT jsonb_agg(jsonb_build_object('item_id', item.id,
                        'number', number, 'count', feature.feature_count,
                        'name_en', item.name_en, 'name_kh', item.name_km)
                        ORDER BY item.sort_order, item.name_en, number)
                    FROM app.unit_features AS feature
                    JOIN app.unit_setup_items AS item ON item.id = feature.item_id
                    CROSS JOIN generate_series(1, feature.feature_count) AS number
                    WHERE feature.unit_id = link.unit_id), '[]'::jsonb) AS places
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
        ) AS person;
        RETURN jsonb_build_object('choices', v_choices, 'users', v_users);
    END $$;

    -- A refused form: the bot tells the tenant in a fixed word, nothing is saved.
    CREATE FUNCTION app.tenant_form_refused(p_reason text) RETURNS jsonb
    LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT jsonb_build_object('result', 'INVALID', 'reason', p_reason)
    $$;

    -- 2. One Problem report from one Tenant bot form (the pulled item ``p_inbound``). The same
    -- form twice gives the same report.
    CREATE FUNCTION app.telegram_tenant_problem_report(p_property uuid, p_inbound uuid,
        p_form jsonb, p_media jsonb, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date;
        v_event app.telegram_inbound_events%ROWTYPE;
        v_user bigint;
        v_link app.tenant_telegram_links%ROWTYPE;
        v_source app.tenant_problem_report_sources%ROWTYPE;
        v_kind text;
        v_type app.problem_types%ROWTYPE;
        v_text text;
        v_voice boolean := false;
        v_photos integer := 0;
        v_urgent boolean;
        v_enter boolean := false;
        v_best text := 'ANY';
        v_item uuid;
        v_number integer;
        v_place uuid;
        v_floor text;
        v_same uuid;
        v_main app.problem_reports%ROWTYPE;
        v_lease uuid;
        v_customer uuid;
        v_by text;
        v_id uuid := gen_random_uuid();
        v_report_number text;
        v_media jsonb;
        v_file app.media_files%ROWTYPE;
        v_media_kind text;
        v_position integer := 0;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        v_day := app.gl_today(p_property);
        SELECT event.* INTO v_event FROM app.telegram_inbound_events AS event
        WHERE event.id = p_inbound AND event.property_id = p_property
          AND event.bot_code = 'TENANT' AND event.kind = 'form';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the form does not exist' USING ERRCODE = '22023';
        END IF;
        SELECT account.telegram_user_id INTO v_user FROM app.telegram_accounts AS account
        WHERE account.id = v_event.account_id;
        -- The same form again: the report it made.
        SELECT source.* INTO v_source FROM app.tenant_problem_report_sources AS source
        WHERE source.inbound_event_id = p_inbound;
        IF FOUND THEN
            SELECT report.* INTO v_main FROM app.problem_reports AS report
            WHERE report.id = v_source.report_id;
            RETURN jsonb_build_object('result', 'ADDED', 'repeated', true,
                'report_id', v_main.id, 'report_number', v_main.report_number,
                'kind', v_main.kind, 'urgent', v_main.urgent,
                'joined_to', (SELECT main.report_number FROM app.problem_reports AS main
                              WHERE main.id = v_main.joined_to_id));
        END IF;
        v_link := app.tenant_active_link(p_property, v_user);
        IF v_user IS NULL OR v_link.id IS NULL THEN
            RETURN jsonb_build_object('result', 'NOT_LINKED');
        END IF;
        IF p_form IS NULL OR jsonb_typeof(p_form) <> 'object' THEN
            RETURN app.tenant_form_refused('not_a_form');
        END IF;
        v_kind := p_form ->> 'kind';
        IF v_kind IS NULL OR v_kind NOT IN ('UNIT', 'BUILDING') THEN
            RETURN app.tenant_form_refused('kind');
        END IF;
        BEGIN
            SELECT kind.* INTO v_type FROM app.problem_types AS kind
            WHERE kind.id = (p_form ->> 'problem_type_id')::uuid AND kind.active;
            v_item := (p_form ->> 'place_item_id')::uuid;
            v_number := (p_form ->> 'place_number')::integer;
            v_place := (p_form ->> 'problem_place_id')::uuid;
            v_same := (p_form ->> 'same_as')::uuid;
        EXCEPTION WHEN data_exception THEN
            RETURN app.tenant_form_refused('not_a_form');
        END;
        IF v_type.id IS NULL THEN
            RETURN app.tenant_form_refused('problem_type');
        END IF;
        IF p_form ? 'description' AND jsonb_typeof(p_form -> 'description') NOT IN ('string', 'null') THEN
            RETURN app.tenant_form_refused('description');
        END IF;
        v_text := NULLIF(btrim(p_form ->> 'description'), '');
        IF v_text IS NOT NULL AND length(v_text) > 1000 THEN
            RETURN app.tenant_form_refused('description');
        END IF;
        -- The files: up to 5 photos or videos and one voice note. The pull job passes the files
        -- it saved with this form (a file sent before is the same file, kept once).
        IF p_media IS NULL OR jsonb_typeof(p_media) <> 'array' THEN
            RETURN app.tenant_form_refused('files');
        END IF;
        FOR v_media IN SELECT value FROM jsonb_array_elements(p_media) LOOP
            BEGIN
                SELECT file.* INTO v_file FROM app.media_files AS file
                WHERE file.id = (v_media #>> '{}')::uuid;
            EXCEPTION WHEN data_exception THEN
                RETURN app.tenant_form_refused('files');
            END;
            IF v_file.id IS NULL THEN
                RETURN app.tenant_form_refused('files');
            END IF;
            IF v_file.content_type LIKE 'audio/%' THEN
                IF v_voice OR COALESCE(v_file.duration_seconds, 0) > 60 THEN
                    RETURN app.tenant_form_refused('files');
                END IF;
                v_voice := true;
            ELSE
                v_photos := v_photos + 1;
            END IF;
        END LOOP;
        IF v_photos > 5 THEN
            RETURN app.tenant_form_refused('files');
        END IF;
        -- Write what is wrong, or send a voice note, or both (owner, 3 Nov 2026). "Same problem"
        -- as an open Building problem needs neither (tenant mock-up v15).
        IF v_text IS NULL AND NOT v_voice AND (v_kind = 'UNIT' OR v_same IS NULL) THEN
            RETURN app.tenant_form_refused('say_what');
        END IF;
        IF jsonb_typeof(p_form -> 'danger') NOT IN ('boolean', 'null') AND p_form ? 'danger' THEN
            RETURN app.tenant_form_refused('urgent');
        END IF;
        v_urgent := v_type.always_urgent OR COALESCE((p_form ->> 'danger')::boolean, false);
        IF v_kind = 'UNIT' THEN
            IF NOT v_urgent THEN
                IF jsonb_typeof(p_form -> 'urgent') IS DISTINCT FROM 'boolean' THEN
                    RETURN app.tenant_form_refused('urgent');
                END IF;
                v_urgent := (p_form ->> 'urgent')::boolean;
            END IF;
            IF jsonb_typeof(p_form -> 'may_enter') IS DISTINCT FROM 'boolean' THEN
                RETURN app.tenant_form_refused('may_enter');
            END IF;
            v_enter := (p_form ->> 'may_enter')::boolean;
            v_best := COALESCE(p_form ->> 'best_time', 'ANY');
            IF v_best NOT IN ('AM', 'PM', 'ANY') THEN
                RETURN app.tenant_form_refused('best_time');
            END IF;
            IF (v_item IS NULL) <> (v_number IS NULL) THEN
                RETURN app.tenant_form_refused('place');
            END IF;
            IF v_item IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM app.unit_features AS feature
                WHERE feature.unit_id = v_link.unit_id AND feature.item_id = v_item
                  AND v_number BETWEEN 1 AND feature.feature_count) THEN
                RETURN app.tenant_form_refused('place');
            END IF;
            IF v_place IS NOT NULL OR v_same IS NOT NULL THEN
                RETURN app.tenant_form_refused('place');
            END IF;
            SELECT current.lease_id, current.customer_id INTO v_lease, v_customer
            FROM app.problem_unit_lease(v_link.unit_id, v_day) AS current;
        ELSE
            IF v_item IS NOT NULL OR v_number IS NOT NULL THEN
                RETURN app.tenant_form_refused('place');
            END IF;
            IF v_place IS NULL OR NOT EXISTS (SELECT 1 FROM app.problem_places AS place
                    WHERE place.id = v_place AND place.active) THEN
                RETURN app.tenant_form_refused('place');
            END IF;
            IF p_form ? 'floor' AND jsonb_typeof(p_form -> 'floor') NOT IN ('string', 'null') THEN
                RETURN app.tenant_form_refused('floor');
            END IF;
            v_floor := NULLIF(btrim(p_form ->> 'floor'), '');
            IF v_floor IS NOT NULL AND length(v_floor) > 20 THEN
                RETURN app.tenant_form_refused('floor');
            END IF;
            IF v_same IS NOT NULL THEN
                SELECT report.* INTO v_main FROM app.problem_reports AS report
                WHERE report.id = v_same AND report.property_id = p_property
                  AND report.kind = 'BUILDING' AND report.problem_place_id = v_place
                FOR UPDATE;
                -- The report was closed since the form opened: this one is a new report.
                IF v_main.id IS NULL OR app.problem_report_state(v_main.id)
                        IN ('DONE', 'CLOSED', 'NOT_ACCEPTED', 'JOINED') THEN
                    v_same := NULL;
                END IF;
            END IF;
        END IF;
        SELECT left(customer.legal_name || ', Unit ' || unit.unit_number, 120) INTO v_by
        FROM app.customers AS customer, app.units AS unit
        WHERE customer.id = v_link.customer_id AND unit.id = v_link.unit_id;
        v_report_number := app.take_document_number(
            CASE v_kind WHEN 'UNIT' THEN 'UNIT_PROBLEM' ELSE 'BUILDING_PROBLEM' END,
            date_part('year', v_day)::integer);
        INSERT INTO app.problem_reports (id, property_id, report_number, kind, unit_id, lease_id,
            customer_id, place_item_id, place_number, problem_place_id, floor_label,
            problem_type_id, description, urgent, always_urgent, may_enter, best_time, source,
            reported_by, created_by)
        VALUES (v_id, p_property, v_report_number, v_kind,
            CASE WHEN v_kind = 'UNIT' THEN v_link.unit_id END, v_lease, v_customer, v_item,
            v_number, v_place, v_floor, v_type.id, COALESCE(v_text, CASE WHEN v_voice
                THEN 'Voice note only' ELSE 'Same problem as '
                    || COALESCE(v_main.report_number, 'an open report') END),
            v_urgent, v_type.always_urgent, v_enter, v_best, 'TENANT_BOT', v_by, p_actor);
        PERFORM app.problem_report_event(v_id, 'RECEIVED', NULL,
            jsonb_build_object('source', 'TENANT_BOT', 'photos', v_photos, 'voice', v_voice),
            p_actor);
        FOR v_media IN SELECT value FROM jsonb_array_elements(p_media) LOOP
            SELECT file.* INTO v_file FROM app.media_files AS file
            WHERE file.id = (v_media #>> '{}')::uuid;
            v_media_kind := CASE WHEN v_file.content_type LIKE 'audio/%' THEN 'VOICE'
                WHEN v_file.content_type LIKE 'video/%' THEN 'VIDEO' ELSE 'PHOTO' END;
            -- The same file twice in one form is kept once.
            IF NOT EXISTS (SELECT 1 FROM app.problem_report_media AS kept
                           WHERE kept.report_id = v_id AND kept.media_file_id = v_file.id) THEN
                v_position := v_position + 1;
                INSERT INTO app.problem_report_media (report_id, media_file_id, kind, stage,
                    position, added_by)
                VALUES (v_id, v_file.id, v_media_kind, 'REPORTED', v_position, p_actor);
            END IF;
        END LOOP;
        INSERT INTO app.tenant_problem_report_sources (report_id, property_id, inbound_event_id,
            telegram_user_id, link_id, created_by)
        VALUES (v_id, p_property, p_inbound, v_user, v_link.id, p_actor);
        -- "Same problem": saved with its own number and joined at once (DL-124).
        IF v_same IS NOT NULL THEN
            PERFORM 1 FROM app.problem_reports AS report WHERE report.id = v_id FOR UPDATE;
            PERFORM app.problem_report_join_to(v_id, v_same,
                'Same problem (picked by the tenant in Telegram)', p_actor);
        END IF;
        PERFORM app.product_audit(p_property, p_actor, v_day, 'problem_report.added',
            'problem_report', v_id, 'Problem report from the Tenant bot', 'telegram.operate',
            NULL, jsonb_build_object('report_number', v_report_number, 'kind', v_kind,
                'source', 'TENANT_BOT', 'same_as', v_same), NULL);
        RETURN jsonb_build_object('result', 'ADDED', 'repeated', false,
            'report_id', v_id, 'report_number', v_report_number, 'kind', v_kind,
            'urgent', v_urgent,
            'joined_to', CASE WHEN v_same IS NOT NULL THEN v_main.report_number END,
            'urgent_hours', COALESCE(app.business_rule_value('TR_URGENT_HOURS', v_day), 1),
            'plan_workdays', COALESCE(app.business_rule_value('TR_PLAN_WORKDAYS', v_day), 1));
    END $$;
"""

JOB_FUNCTIONS = (
    "app.telegram_tenant_form_data(uuid, uuid)",
    "app.telegram_tenant_problem_report(uuid, uuid, jsonb, jsonb, uuid)",
)
TABLE_NAMES = "app.problem_report_media, app.tenant_problem_report_sources"


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    op.execute(f"REVOKE ALL ON TABLE {TABLE_NAMES} FROM PUBLIC, prm_runtime, prm_bootstrap")
    op.execute("REVOKE ALL ON FUNCTION app.tenant_form_refused(text) FROM PUBLIC")
    for signature in JOB_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("the Tenant bot Problem report migration is forward-only")
