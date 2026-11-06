# ruff: noqa: E501
"""Telegram bots, step 3a: the Customer bot and Visit requests from it (DL-171).

Owner-approved CRM mock-up (customer bot view, 28 Oct to 2 Nov 2026) and DESIGN rounds 9 and 10:
a new customer chooses Khmer or English, then Send an inquiry, FAQ or Contact office. Send an
inquiry asks how to contact them (Telegram, Email, Phone call or SMS, WhatsApp), their own phone
(Telegram's share button), the email when they chose Email, their name, the Unit Type, a visit
day (2 to 30 days ahead, Monday to Saturday, or none yet) with Morning or Afternoon, the move-in
month (or Later) and a note they can skip. The bot shows the request to check; "Send an inquiry"
saves it and answers with its number.

1. ``visit_requests`` (append-only): one row for each inquiry, numbered from the app's Numbers
   (VISIT_REQUEST, VRyy000n). A new inquiry from a person or phone that already has a request
   joins it and keeps the first one's place in the list (owner rule 28 Oct 2026: first come,
   first served; a repeat joins the old request). Statuses, Take, calls, visits and Close come
   in step 3b, and the 12-month removal of name, phone and account with them.
2. Rights (group Leasing): See Visit requests (``visit_requests.read``) for the Owner, the
   Manager and Staff (owner 28 Oct 2026: the front desk, Managers and the Owner work the list).
3. Contact office from the Customer bot: the office's Reply shows the Customer bot menu.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270525_287"
down_revision: str | None = "20270524_286"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROVENANCE = "v1-1-telegram-customer-bot"
CAPABILITY = ("visit_requests.read", "See the Visit requests new customers send")
PERMISSION = ("VISIT_REQUESTS", "See Visit requests", "មើលសំណើមកមើលបន្ទប់")
REASON = "Owner 2026-10-28: the front desk, Managers and the Owner work Visit requests"
SEED = "app.seed_default_role_bundles(uuid)"
STAFF_BEFORE = "'short_stays.housekeeping', 'telegram.contact']::text[]"
STAFF_AFTER = "'short_stays.housekeeping', 'telegram.contact', 'visit_requests.read']::text[]"
ANSWER = "app.telegram_contact_answer(uuid, uuid, text, text, uuid)"
ANSWER_BEFORE = "ELSE 'tenant.menu' END;"
ANSWER_AFTER = "ELSE 'tenant.menu' END;\n            ELSE\n                v_keyboard := 'customer.menu';"

TABLES = """
    CREATE TABLE app.visit_requests (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        request_number text NOT NULL UNIQUE CHECK (request_number ~ '^[A-Z]{2,5}[0-9]{6,}$'),
        source text NOT NULL CHECK (source IN ('TELEGRAM')),
        inbound_event_id uuid UNIQUE
            REFERENCES app.telegram_inbound_events (id) ON DELETE RESTRICT,
        telegram_user_id bigint CHECK (telegram_user_id > 0),
        chat_id bigint CHECK (chat_id <> 0),
        language text NOT NULL CHECK (language IN ('km', 'en')),
        contact_by text NOT NULL CHECK (contact_by IN ('TELEGRAM', 'EMAIL', 'PHONE', 'WHATSAPP')),
        phone_e164 text NOT NULL CHECK (phone_e164 ~ '^\\+[1-9][0-9]{6,14}$'),
        email text CHECK (length(email) BETWEEN 3 AND 120
            AND email ~ '^[^@ ]+@[^@ ]+[.][^@ ]+$'),
        customer_name text NOT NULL
            CHECK (length(customer_name) BETWEEN 1 AND 120 AND customer_name = btrim(customer_name)),
        unit_type text NOT NULL CHECK (unit_type ~ '^[A-Z0-9][A-Z0-9_]{0,39}$'),
        visit_on date,
        visit_part text CHECK (visit_part IN ('MORNING', 'AFTERNOON')),
        move_in_month date CHECK (extract(day FROM move_in_month) = 1),
        note text CHECK (length(note) BETWEEN 1 AND 500 AND note = btrim(note)),
        joined_to uuid REFERENCES app.visit_requests (id) ON DELETE RESTRICT,
        received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT visit_requests_email CHECK ((contact_by = 'EMAIL') = (email IS NOT NULL)),
        CONSTRAINT visit_requests_visit CHECK ((visit_on IS NULL) = (visit_part IS NULL)),
        CONSTRAINT visit_requests_telegram CHECK (source <> 'TELEGRAM' OR (
            inbound_event_id IS NOT NULL AND telegram_user_id IS NOT NULL AND chat_id IS NOT NULL))
    );
    CREATE INDEX visit_requests_list_idx ON app.visit_requests (property_id, received_at);
    CREATE INDEX visit_requests_person_idx ON app.visit_requests (property_id, telegram_user_id);
    CREATE INDEX visit_requests_phone_idx ON app.visit_requests (property_id, phone_e164);
    CREATE TRIGGER visit_requests_append_only BEFORE UPDATE OR DELETE ON app.visit_requests
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER visit_requests_no_truncate BEFORE TRUNCATE ON app.visit_requests
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    REVOKE ALL ON TABLE app.visit_requests FROM PUBLIC, prm_runtime, prm_bootstrap;
    COMMENT ON TABLE app.visit_requests IS
        'Telegram step 3a (DL-171): Visit requests new customers send from the Customer bot.';

    -- The request numbers (Settings > Business > Numbers), like the Problem report numbers.
    INSERT INTO app.number_rules (document_type, year, last_number, format)
    SELECT 'VISIT_REQUEST', years.year, 0, 'VRyy000n'
    FROM (SELECT DISTINCT date_part('year', timezone(property.timezone_name,
              statement_timestamp()))::smallint AS year
          FROM app.properties AS property
          UNION SELECT date_part('year', statement_timestamp())::smallint) AS years
    ON CONFLICT (document_type, year) DO NOTHING;
"""

FUNCTIONS = """
    -- The Property's day today (its time zone).
    CREATE FUNCTION app.visit_request_today(p_property uuid)
    RETURNS date LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT timezone(property.timezone_name, statement_timestamp())::date
        FROM app.properties AS property WHERE property.id = p_property
    $$;

    -- 1. What the Customer bot offers one person: today, the Unit Types and their shared phone.
    CREATE FUNCTION app.telegram_customer_choices(p_property uuid, p_user bigint, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_types jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT COALESCE(jsonb_agg(jsonb_build_object('code', item.code,
                'name_en', item.name_en, 'name_km', COALESCE(item.name_km, item.name_en))
            ORDER BY item.sort_order, item.code), '[]'::jsonb)
        INTO v_types
        FROM app.unit_setup_items AS item
        WHERE item.property_id = p_property AND item.list_kind = 'UNIT_TYPE'
          AND item.removed_at IS NULL;
        RETURN jsonb_build_object(
            'today', app.visit_request_today(p_property),
            'unit_types', v_types,
            'phone', (SELECT account.phone_e164 FROM app.telegram_accounts AS account
                      WHERE account.telegram_user_id = p_user));
    END $$;

    -- 2. "Send an inquiry": save the request (the Telegram jobs' account).
    CREATE FUNCTION app.telegram_visit_request_add(p_property uuid, p_inbound uuid,
        p_user bigint, p_chat bigint, p_language text, p_request jsonb, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_found app.visit_requests%ROWTYPE;
        v_main app.visit_requests%ROWTYPE;
        v_phone text;
        v_how text;
        v_email text;
        v_name text;
        v_type text;
        v_day date;
        v_part text;
        v_move date;
        v_note text;
        v_today date;
        v_number text;
        v_id uuid := gen_random_uuid();
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        IF p_user IS NULL OR p_user <= 0 OR p_chat IS NULL OR p_chat = 0
            OR p_language IS NULL OR p_language NOT IN ('km', 'en')
            OR jsonb_typeof(p_request) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'the request is not valid' USING ERRCODE = '22023';
        END IF;
        PERFORM 1 FROM app.telegram_inbound_events AS event
        WHERE event.id = p_inbound AND event.property_id = p_property
          AND event.bot_code = 'CUSTOMER';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the message does not exist' USING ERRCODE = '22023';
        END IF;
        SELECT request.* INTO v_found FROM app.visit_requests AS request
        WHERE request.inbound_event_id = p_inbound;
        IF FOUND THEN
            RETURN jsonb_build_object('result', 'REPEATED', 'number', v_found.request_number,
                'main_number', (SELECT main.request_number FROM app.visit_requests AS main
                                WHERE main.id = v_found.joined_to));
        END IF;
        SELECT account.phone_e164 INTO v_phone FROM app.telegram_accounts AS account
        WHERE account.telegram_user_id = p_user;
        IF v_phone IS NULL THEN
            RETURN jsonb_build_object('result', 'NO_PHONE');
        END IF;

        v_how := p_request ->> 'contact_by';
        IF v_how IS NULL OR v_how NOT IN ('TELEGRAM', 'EMAIL', 'PHONE', 'WHATSAPP') THEN
            RAISE EXCEPTION 'Choose how we contact you' USING ERRCODE = '22023';
        END IF;
        IF v_how = 'EMAIL' THEN
            v_email := btrim(p_request ->> 'email');
            IF v_email IS NULL OR length(v_email) NOT BETWEEN 3 AND 120
                OR v_email !~ '^[^@ ]+@[^@ ]+[.][^@ ]+$' THEN
                RAISE EXCEPTION 'Type a good email address' USING ERRCODE = '22023';
            END IF;
        END IF;
        v_name := btrim(p_request ->> 'name');
        IF v_name IS NULL OR length(v_name) NOT BETWEEN 1 AND 120 THEN
            RAISE EXCEPTION 'Type the name, at most 120 letters' USING ERRCODE = '22023';
        END IF;
        v_type := p_request ->> 'unit_type';
        PERFORM 1 FROM app.unit_setup_items AS item
        WHERE item.property_id = p_property AND item.list_kind = 'UNIT_TYPE'
          AND item.code = v_type AND item.removed_at IS NULL;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Choose a Unit Type' USING ERRCODE = '22023';
        END IF;
        v_today := app.visit_request_today(p_property);
        IF p_request ->> 'visit_on' IS NOT NULL THEN
            BEGIN
                v_day := (p_request ->> 'visit_on')::date;
            EXCEPTION WHEN data_exception THEN
                RAISE EXCEPTION 'The visit day is not a date' USING ERRCODE = '22023';
            END;
            IF v_day NOT BETWEEN v_today + 2 AND v_today + 30
                OR extract(isodow FROM v_day) = 7 THEN
                RAISE EXCEPTION 'Choose a visit day 2 to 30 days ahead, Monday to Saturday'
                    USING ERRCODE = '22023';
            END IF;
            v_part := p_request ->> 'visit_part';
            IF v_part IS NULL OR v_part NOT IN ('MORNING', 'AFTERNOON') THEN
                RAISE EXCEPTION 'Choose Morning or Afternoon' USING ERRCODE = '22023';
            END IF;
        END IF;
        IF COALESCE(p_request ->> 'move_in', 'LATER') <> 'LATER' THEN
            IF (p_request ->> 'move_in') !~ '^[0-9]{4}-[0-9]{2}$' THEN
                RAISE EXCEPTION 'Choose the move-in month' USING ERRCODE = '22023';
            END IF;
            BEGIN
                v_move := ((p_request ->> 'move_in') || '-01')::date;
            EXCEPTION WHEN data_exception THEN
                RAISE EXCEPTION 'Choose the move-in month' USING ERRCODE = '22023';
            END;
            IF v_move < date_trunc('month', v_today)::date OR v_move > v_today + 730 THEN
                RAISE EXCEPTION 'Choose the move-in month' USING ERRCODE = '22023';
            END IF;
        END IF;
        v_note := NULLIF(btrim(p_request ->> 'note'), '');
        IF length(v_note) > 500 THEN
            RAISE EXCEPTION 'The note is at most 500 letters' USING ERRCODE = '22023';
        END IF;

        -- A request of the same person or phone is already in the list: this one joins it.
        SELECT main.* INTO v_main FROM app.visit_requests AS main
        WHERE main.property_id = p_property AND main.joined_to IS NULL
          AND (main.telegram_user_id = p_user OR main.phone_e164 = v_phone)
        ORDER BY main.received_at, main.id
        LIMIT 1;
        v_number := app.take_document_number('VISIT_REQUEST',
            date_part('year', v_today)::integer);
        INSERT INTO app.visit_requests (id, property_id, request_number, source,
            inbound_event_id, telegram_user_id, chat_id, language, contact_by, phone_e164, email,
            customer_name, unit_type, visit_on, visit_part, move_in_month, note, joined_to,
            created_by)
        VALUES (v_id, p_property, v_number, 'TELEGRAM', p_inbound, p_user, p_chat, p_language,
            v_how, v_phone, v_email, v_name, v_type, v_day, v_part, v_move, v_note, v_main.id,
            p_actor);
        RETURN jsonb_build_object(
            'result', CASE WHEN v_main.id IS NULL THEN 'ADDED' ELSE 'JOINED' END,
            'number', v_number, 'main_number', v_main.request_number);
    END $$;

    -- 3. The Visit requests list: oldest first, each with the inquiries that joined it.
    CREATE FUNCTION app.visit_request_row(p_request app.visit_requests)
    RETURNS jsonb LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT jsonb_build_object(
            'id', p_request.id, 'number', p_request.request_number,
            'source', p_request.source, 'received_at', p_request.received_at,
            'name', p_request.customer_name, 'phone', p_request.phone_e164,
            'contact_by', p_request.contact_by, 'email', p_request.email,
            'language', p_request.language, 'unit_type', p_request.unit_type,
            'unit_type_en', item.name_en, 'unit_type_km', COALESCE(item.name_km, item.name_en),
            'visit_on', p_request.visit_on, 'visit_part', p_request.visit_part,
            'move_in_month', to_char(p_request.move_in_month, 'YYYY-MM'),
            'note', p_request.note)
        FROM (SELECT 1) AS one
        LEFT JOIN app.unit_setup_items AS item
          ON item.property_id = p_request.property_id AND item.list_kind = 'UNIT_TYPE'
         AND item.code = p_request.unit_type
    $$;

    CREATE FUNCTION app.visit_requests_page(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_list jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'visit_requests.read', p_property);
        SELECT COALESCE(jsonb_agg(app.visit_request_row(main) || jsonb_build_object(
                'status', 'NEW',
                'joined', (SELECT COALESCE(jsonb_agg(app.visit_request_row(kid)
                               ORDER BY kid.received_at, kid.id), '[]'::jsonb)
                           FROM app.visit_requests AS kid WHERE kid.joined_to = main.id))
            ORDER BY main.received_at, main.id), '[]'::jsonb)
        INTO v_list
        FROM app.visit_requests AS main
        WHERE main.property_id = p_property AND main.joined_to IS NULL;
        RETURN jsonb_build_object('requests', v_list,
            'today', app.visit_request_today(p_property));
    END $$;
"""

APP_FUNCTIONS = (
    "app.telegram_customer_choices(uuid, bigint, uuid)",
    "app.telegram_visit_request_add(uuid, uuid, bigint, bigint, text, jsonb, uuid)",
    "app.visit_requests_page(uuid, uuid)",
)
INNER_FUNCTIONS = (
    "app.visit_request_today(uuid)",
    "app.visit_request_row(app.visit_requests)",
)


def _text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _patch(signature: str, before: str, after: str) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    if definition.count(before) != 1:
        raise RuntimeError(f"{signature} does not have the expected text")
    op.execute(text(definition.replace(before, after)))


def upgrade() -> None:
    name, description = CAPABILITY
    code, name_en, name_kh = PERMISSION
    op.execute(
        f"""
        INSERT INTO app.capabilities (capability_id, family, description, grant_path, provenance)
        VALUES ({_text(name)}, 'visit_requests', {_text(description)}, 'bundle',
            '{PROVENANCE}');
        INSERT INTO app.permissions (permission_code, group_code, sort_order, name_en, name_kh,
            provenance)
        VALUES ({_text(code)}, 'LEASING', (SELECT max(sort_order) FROM app.permissions) + 1,
            {_text(name_en)}, {_text(name_kh)}, '{PROVENANCE}');
        INSERT INTO app.permission_capabilities (permission_code, capability_id, provenance)
        VALUES ({_text(code)}, {_text(name)}, '{PROVENANCE}');
        """
    )
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    for signature in INNER_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in APP_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")
    _patch(ANSWER, ANSWER_BEFORE, ANSWER_AFTER)

    # New Properties: every default bundle sees Visit requests.
    _patch(SEED, STAFF_BEFORE, STAFF_AFTER)
    op.execute(
        f"""
        DO $$
        DECLARE
            v_default record;
            v_owner uuid;
            v_timezone text;
            v_at timestamptz := pg_catalog.statement_timestamp();
        BEGIN
            SELECT classification.actor_id INTO v_owner
            FROM app.user_account_classes AS classification
            WHERE classification.account_class = 'owner';
            FOR v_default IN
                SELECT seeded.property_id, bundle.role_bundle_id, bundle.version
                FROM app.default_role_bundles AS seeded
                JOIN app.role_bundles AS bundle
                  ON bundle.role_bundle_id IN (
                      seeded.owner_bundle_id, seeded.manager_bundle_id, seeded.staff_bundle_id)
                ORDER BY seeded.property_id, bundle.role_bundle_id
                FOR UPDATE OF bundle
            LOOP
                UPDATE app.role_bundles SET version = v_default.version + 1
                WHERE role_bundle_id = v_default.role_bundle_id;
                INSERT INTO app.role_bundle_capabilities (role_bundle_id, version, capability_id)
                SELECT v_default.role_bundle_id, v_default.version + 1, held.capability_id
                FROM app.role_bundle_capabilities AS held
                WHERE held.role_bundle_id = v_default.role_bundle_id
                  AND held.version = v_default.version
                UNION
                SELECT v_default.role_bundle_id, v_default.version + 1, {_text(name)};
                SELECT property.timezone_name INTO v_timezone
                FROM app.properties AS property WHERE property.id = v_default.property_id;
                IF v_owner IS NOT NULL THEN
                    INSERT INTO app.audit_events (
                        id, occurred_at, business_date, actor_id, action, entity_type, entity_id,
                        reason, authorization_reference, property_id, previous_state,
                        resulting_state, correlation_id, source, outcome
                    ) VALUES (
                        pg_catalog.gen_random_uuid(), v_at,
                        pg_catalog.timezone(v_timezone, v_at)::date, v_owner,
                        'identity.role_bundle.updated', 'role_bundle', v_default.role_bundle_id,
                        {_text(REASON)}, 'identity.manage_access', v_default.property_id,
                        pg_catalog.jsonb_build_object('version', v_default.version),
                        pg_catalog.jsonb_build_object(
                            'version', v_default.version + 1,
                            'capabilities_added', pg_catalog.jsonb_build_array({_text(name)})),
                        pg_catalog.gen_random_uuid(), 'ADMINISTRATIVE', 'SUCCEEDED'
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    raise RuntimeError("the Telegram Customer bot migration is forward-only")
