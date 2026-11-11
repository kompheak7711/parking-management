# ruff: noqa: E501
"""Telegram bots: the office sends a notice to linked tenants and guests (DL-216).

Owner (11 Nov 2026): CHETANA Residence support sends "any notice or warning", and notices come
after Receipts ("All three, in that order"). A notice is news from the office, such as a water or
power cut, building work or a holiday: it is not about money and is not a Lease letter (those are
the warnings, a later step with the owner's rules).

1. ``app.telegram_notices`` keeps each notice as sent: the words in English and/or Khmer, who it
   is for (everyone linked, some floors, or some Units), the person who sent it and when. It is
   never changed.
2. ``app.telegram_notice_deliveries`` keeps one row per notice and Telegram account with its
   outbox message, so nobody gets the same notice twice.
3. ``app.telegram_notice_send`` (``telegram.operate``: Owner and Managers) saves the notice and
   queues it at once for each live link (tenants and guests) of the chosen Units, in the
   language each person chose; a notice written in one language goes in that language to all.
4. ``app.telegram_notices_page`` (``telegram.read``) lists the notices of the last 90 days with
   how many people got each one.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule (no money or Lease rule).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270714_386"
down_revision: str | None = "20270713_385"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PAGE_DAYS = 90
MAX_WORDS = 1500

TABLES = f"""
    CREATE TABLE app.telegram_notices (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        text_en text CHECK (text_en IS NULL OR (text_en = btrim(text_en)
            AND length(text_en) BETWEEN 1 AND {MAX_WORDS})),
        text_km text CHECK (text_km IS NULL OR (text_km = btrim(text_km)
            AND length(text_km) BETWEEN 1 AND {MAX_WORDS})),
        audience text NOT NULL CHECK (audience IN ('ALL', 'FLOORS', 'UNITS')),
        floors text[] NOT NULL DEFAULT '{{}}',
        unit_ids uuid[] NOT NULL DEFAULT '{{}}',
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        CONSTRAINT telegram_notices_words CHECK (num_nonnulls(text_en, text_km) >= 1),
        CONSTRAINT telegram_notices_audience CHECK (
            (audience = 'ALL' AND cardinality(floors) = 0 AND cardinality(unit_ids) = 0)
            OR (audience = 'FLOORS' AND cardinality(floors) BETWEEN 1 AND 100 AND cardinality(unit_ids) = 0)
            OR (audience = 'UNITS' AND cardinality(unit_ids) BETWEEN 1 AND 500 AND cardinality(floors) = 0))
    );
    CREATE INDEX telegram_notices_property_idx ON app.telegram_notices (property_id, created_at DESC);

    CREATE TABLE app.telegram_notice_deliveries (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        notice_id uuid NOT NULL REFERENCES app.telegram_notices (id) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        outbox_id uuid NOT NULL UNIQUE REFERENCES app.telegram_outbox (id) ON DELETE RESTRICT,
        CONSTRAINT telegram_notice_deliveries_once UNIQUE (notice_id, telegram_user_id)
    );
"""

APPEND_ONLY = ("telegram_notices", "telegram_notice_deliveries")

FUNCTIONS = f"""
    CREATE FUNCTION app.telegram_notice_send(p_property uuid, p_body jsonb, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_en text := NULLIF(btrim(p_body->>'text_en'), '');
        v_km text := NULLIF(btrim(p_body->>'text_km'), '');
        v_audience text := p_body->>'audience';
        v_floors text[];
        v_units uuid[];
        v_notice uuid;
        v_person record;
        v_outbox uuid;
        v_count integer := 0;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        IF jsonb_typeof(p_body) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'A notice needs its words and who it is for' USING ERRCODE = '22023';
        END IF;
        IF v_en IS NULL AND v_km IS NULL THEN
            RAISE EXCEPTION 'A notice needs its words' USING ERRCODE = '22023';
        END IF;
        IF length(v_en) > {MAX_WORDS} OR length(v_km) > {MAX_WORDS} THEN
            RAISE EXCEPTION 'A notice is too long' USING ERRCODE = '22023';
        END IF;
        IF v_audience = 'FLOORS' THEN
            IF jsonb_typeof(p_body->'floors') IS DISTINCT FROM 'array' THEN
                RAISE EXCEPTION 'Choose the floors' USING ERRCODE = '22023';
            END IF;
            SELECT COALESCE(array_agg(DISTINCT btrim(floor)), '{{}}') INTO v_floors
            FROM jsonb_array_elements_text(p_body->'floors') AS floor WHERE btrim(floor) <> '';
            IF cardinality(v_floors) = 0 OR EXISTS (
                SELECT 1 FROM unnest(v_floors) AS wanted
                WHERE NOT EXISTS (SELECT 1 FROM app.units AS unit
                                  WHERE unit.property_id = p_property AND unit.floor = wanted)) THEN
                RAISE EXCEPTION 'Choose floors of this Property' USING ERRCODE = '22023';
            END IF;
        ELSIF v_audience = 'UNITS' THEN
            IF jsonb_typeof(p_body->'unit_ids') IS DISTINCT FROM 'array' THEN
                RAISE EXCEPTION 'Choose the Units' USING ERRCODE = '22023';
            END IF;
            BEGIN
                SELECT COALESCE(array_agg(DISTINCT unit_id::uuid), '{{}}') INTO v_units
                FROM jsonb_array_elements_text(p_body->'unit_ids') AS unit_id;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Choose Units of this Property' USING ERRCODE = '22023';
            END;
            IF cardinality(v_units) = 0 OR EXISTS (
                SELECT 1 FROM unnest(v_units) AS wanted
                WHERE NOT EXISTS (SELECT 1 FROM app.units AS unit
                                  WHERE unit.property_id = p_property AND unit.id = wanted)) THEN
                RAISE EXCEPTION 'Choose Units of this Property' USING ERRCODE = '22023';
            END IF;
        ELSIF v_audience IS DISTINCT FROM 'ALL' THEN
            RAISE EXCEPTION 'Choose who the notice is for' USING ERRCODE = '22023';
        END IF;
        INSERT INTO app.telegram_notices (property_id, text_en, text_km, audience, floors,
            unit_ids, created_by)
        VALUES (p_property, v_en, v_km, v_audience, COALESCE(v_floors, '{{}}'),
            COALESCE(v_units, '{{}}'), p_actor)
        RETURNING id INTO v_notice;
        FOR v_person IN
            SELECT DISTINCT ON (link.telegram_user_id) link.telegram_user_id,
                COALESCE((SELECT choice.language FROM app.telegram_language_choices AS choice
                          WHERE choice.bot_code = 'TENANT'
                            AND choice.telegram_user_id = link.telegram_user_id
                          ORDER BY choice.chosen_at DESC LIMIT 1), 'km') AS language
            FROM app.tenant_telegram_links AS link
            JOIN app.units AS unit ON unit.id = link.unit_id
            WHERE link.property_id = p_property
              AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                              WHERE ending.link_id = link.id)
              AND app.tenant_link_stay_live(link.lease_id, link.booking_id, app.gl_today(p_property))
              AND (v_audience = 'ALL'
                   OR (v_audience = 'FLOORS' AND unit.floor = ANY (v_floors))
                   OR (v_audience = 'UNITS' AND unit.id = ANY (v_units)))
            ORDER BY link.telegram_user_id, link.linked_at DESC
        LOOP
            INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code, language,
                details, keyboard, created_by)
            VALUES (p_property, 'TENANT', v_person.telegram_user_id, 'tenant.notice',
                v_person.language,
                jsonb_build_object('notice', CASE WHEN v_person.language = 'en'
                    THEN COALESCE(v_en, v_km) ELSE COALESCE(v_km, v_en) END),
                NULL, p_actor)
            RETURNING id INTO v_outbox;
            INSERT INTO app.telegram_notice_deliveries (notice_id, telegram_user_id, outbox_id)
            VALUES (v_notice, v_person.telegram_user_id, v_outbox);
            v_count := v_count + 1;
        END LOOP;
        RETURN jsonb_build_object('notice_id', v_notice, 'queued', v_count);
    END $$;

    -- The notices of the last {PAGE_DAYS} days, who they were for and how many people got them.
    CREATE FUNCTION app.telegram_notices_page(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_rows jsonb;
        v_floors jsonb;
        v_units jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.read', p_property);
        SELECT COALESCE(jsonb_agg(jsonb_build_object(
                'id', notice.id, 'text_en', notice.text_en, 'text_km', notice.text_km,
                'audience', notice.audience, 'floors', to_jsonb(notice.floors),
                'units', COALESCE((SELECT jsonb_agg(unit.unit_number ORDER BY unit.unit_number)
                    FROM app.units AS unit WHERE unit.id = ANY (notice.unit_ids)), '[]'::jsonb),
                'sent_by', COALESCE(account.display_name, ''),
                'created_at', notice.created_at,
                'people', (SELECT count(*) FROM app.telegram_notice_deliveries AS delivery
                           WHERE delivery.notice_id = notice.id),
                'sent', (SELECT count(*) FROM app.telegram_notice_deliveries AS delivery
                         JOIN app.telegram_outbox_attempts AS attempt
                           ON attempt.outbox_id = delivery.outbox_id AND attempt.outcome = 'SENT'
                         WHERE delivery.notice_id = notice.id),
                'failed', (SELECT count(*) FROM app.telegram_notice_deliveries AS delivery
                           JOIN app.telegram_outbox_attempts AS attempt
                             ON attempt.outbox_id = delivery.outbox_id AND attempt.outcome = 'GAVE_UP'
                           WHERE delivery.notice_id = notice.id))
                ORDER BY notice.created_at DESC), '[]'::jsonb)
        INTO v_rows
        FROM app.telegram_notices AS notice
        LEFT JOIN app.user_accounts AS account ON account.actor_id = notice.created_by
        WHERE notice.property_id = p_property
          AND notice.created_at >= statement_timestamp() - interval '{PAGE_DAYS} days';
        SELECT COALESCE(jsonb_agg(DISTINCT unit.floor ORDER BY unit.floor), '[]'::jsonb) INTO v_floors
        FROM app.units AS unit WHERE unit.property_id = p_property AND unit.floor IS NOT NULL;
        SELECT COALESCE(jsonb_agg(jsonb_build_object('id', unit.id, 'unit_number', unit.unit_number,
                'floor', unit.floor) ORDER BY unit.unit_number), '[]'::jsonb) INTO v_units
        FROM app.units AS unit WHERE unit.property_id = p_property;
        RETURN jsonb_build_object('notices', v_rows, 'floors', v_floors, 'units', v_units,
            'rules', jsonb_build_object('days', {PAGE_DAYS}, 'max', {MAX_WORDS}));
    END $$;
"""

RUNTIME = (
    "app.telegram_notice_send(uuid, jsonb, uuid)",
    "app.telegram_notices_page(uuid, uuid)",
)


def upgrade() -> None:
    op.execute(TABLES)
    for table in APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON app.{table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change()"
        )
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC")
    op.execute(FUNCTIONS)
    for signature in RUNTIME:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("the Tenant bot notice migration is forward-only")
