# ruff: noqa: E501
"""Telegram bots, step 2a: the Tenant bot links a Telegram account to a tenant (DL-126).

Owner rules (2 Nov 2026 21:09 and 3 Nov 2026 05:14, bots plan T5): a tenant links by sharing
their own Telegram phone number, then typing their name and their Unit. All three must match one
person on an active Lease (the main tenant, a signer or someone living there). They are linked at
once, with no code. A wrong try says what to check and how many tries are left, never which part
was wrong; 5 wrong tries in 24 hours block linking for 24 hours. The name check ignores capitals,
spaces and the order of the words. A one-line privacy notice is shown when a tenant links.

1. ``telegram_language_choices``: the language a person chose in a bot (Khmer or English).
2. ``telegram_chat_steps``: where each person is in a bot conversation (the newest row counts).
3. ``tenant_link_attempts``: every link try with its result; removed after 90 days (bots plan:
   failed link tries are kept 90 days like other technical logs).
4. ``tenant_telegram_links`` and ``tenant_telegram_link_endings``: a link between a Telegram
   account and a Customer on a Lease, and when and why it ended (the Lease ended, staff removed
   it, or the person linked again).
5. ``telegram_outbox.keyboard``: the fixed keyboard a message shows (the buttons under the chat).

The functions run as the account the Telegram jobs run as (``telegram.operate``); the Linked
tenants list reads with ``telegram.read``. Technical choices by Claude under the owner's
2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270520_282"
down_revision: str | None = "20270430_281"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = """
    CREATE TABLE app.telegram_language_choices (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        bot_code text NOT NULL REFERENCES app.telegram_bots (code) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        language text NOT NULL CHECK (language IN ('km', 'en')),
        chosen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX telegram_language_choices_person_idx
        ON app.telegram_language_choices (bot_code, telegram_user_id, chosen_at DESC);

    CREATE TABLE app.telegram_chat_steps (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        bot_code text NOT NULL REFERENCES app.telegram_bots (code) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        step text NOT NULL CHECK (step ~ '^[a-z][a-z0-9_.]{1,40}$'),
        data jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(data) = 'object'
            AND pg_column_size(data) <= 4096),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX telegram_chat_steps_person_idx
        ON app.telegram_chat_steps (bot_code, telegram_user_id, created_at DESC);

    CREATE TABLE app.tenant_link_attempts (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        phone_e164 text CHECK (phone_e164 ~ '^\\+[1-9][0-9]{6,14}$'),
        typed_name text NOT NULL CHECK (length(typed_name) BETWEEN 1 AND 120),
        typed_unit text NOT NULL CHECK (length(typed_unit) BETWEEN 1 AND 20),
        result text NOT NULL CHECK (result IN ('LINKED', 'NO_MATCH', 'BLOCKED', 'NO_PHONE')),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX tenant_link_attempts_person_idx
        ON app.tenant_link_attempts (property_id, telegram_user_id, created_at DESC);
    CREATE INDEX tenant_link_attempts_created_idx ON app.tenant_link_attempts (created_at);

    CREATE TABLE app.tenant_telegram_links (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        customer_id uuid NOT NULL REFERENCES app.customers (id) ON DELETE RESTRICT,
        lease_id uuid NOT NULL REFERENCES app.leases (id) ON DELETE RESTRICT,
        unit_id uuid NOT NULL REFERENCES app.units (id) ON DELETE RESTRICT,
        linked_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX tenant_telegram_links_person_idx
        ON app.tenant_telegram_links (property_id, telegram_user_id, linked_at DESC);
    CREATE INDEX tenant_telegram_links_lease_idx ON app.tenant_telegram_links (lease_id);

    CREATE TABLE app.tenant_telegram_link_endings (
        link_id uuid PRIMARY KEY REFERENCES app.tenant_telegram_links (id) ON DELETE RESTRICT,
        reason text NOT NULL CHECK (reason IN ('LEASE_ENDED', 'REMOVED', 'NEW_LINK')),
        note text CHECK (note IS NULL OR (length(note) BETWEEN 1 AND 300 AND note = btrim(note))),
        ended_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        ended_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT tenant_telegram_link_endings_note CHECK ((reason = 'REMOVED') = (note IS NOT NULL))
    );

    ALTER TABLE app.telegram_outbox ADD COLUMN keyboard text
        CHECK (keyboard ~ '^[a-z][a-z0-9_.]{1,40}$');

    CREATE TRIGGER telegram_language_choices_append_only BEFORE UPDATE OR DELETE
        ON app.telegram_language_choices FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER telegram_chat_steps_append_only BEFORE UPDATE OR DELETE
        ON app.telegram_chat_steps FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER tenant_telegram_links_append_only BEFORE UPDATE OR DELETE
        ON app.tenant_telegram_links FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER tenant_telegram_link_endings_append_only BEFORE UPDATE OR DELETE
        ON app.tenant_telegram_link_endings FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER telegram_language_choices_no_truncate BEFORE TRUNCATE
        ON app.telegram_language_choices FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER telegram_chat_steps_no_truncate BEFORE TRUNCATE
        ON app.telegram_chat_steps FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER tenant_link_attempts_no_truncate BEFORE TRUNCATE
        ON app.tenant_link_attempts FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER tenant_telegram_links_no_truncate BEFORE TRUNCATE
        ON app.tenant_telegram_links FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER tenant_telegram_link_endings_no_truncate BEFORE TRUNCATE
        ON app.tenant_telegram_link_endings FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();

    -- A link try is never changed; it is removed only once it is more than 90 days old.
    CREATE FUNCTION app.protect_tenant_link_attempt() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    BEGIN
        IF TG_OP = 'DELETE' AND OLD.created_at < clock_timestamp() - interval '90 days' THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'Telegram history is never changed' USING ERRCODE = '55000';
    END $$;
    REVOKE ALL ON FUNCTION app.protect_tenant_link_attempt() FROM PUBLIC;
    CREATE TRIGGER tenant_link_attempts_protect BEFORE UPDATE OR DELETE ON app.tenant_link_attempts
        FOR EACH ROW EXECUTE FUNCTION app.protect_tenant_link_attempt();
"""

FUNCTIONS = """
    -- Phone numbers in one format, as in backend/src/property_rental/telegram_phone.py:
    -- "012 345 678", "+855 12 345 678" and "85512345678" are the same number.
    CREATE FUNCTION app.phone_e164(p_text text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog AS $$
    DECLARE
        v_text text := btrim(p_text);
        v_plus boolean;
        v_digits text;
        v_result text;
    BEGIN
        IF v_text IS NULL OR v_text = '' THEN
            RETURN NULL;
        END IF;
        v_plus := left(v_text, 1) = '+';
        v_digits := regexp_replace(CASE WHEN v_plus THEN substr(v_text, 2) ELSE v_text END,
            '[[:space:]().-]', '', 'g');
        IF v_digits !~ '^[0-9]+$' THEN
            RETURN NULL;
        END IF;
        IF v_plus THEN
            v_result := '+' || v_digits;
        ELSIF left(v_digits, 2) = '00' THEN
            v_result := '+' || substr(v_digits, 3);
        ELSIF left(v_digits, 1) = '0' THEN
            v_result := '+855' || substr(v_digits, 2);
        ELSE
            v_result := '+' || v_digits;
        END IF;
        IF left(v_result, 5) = '+8550' THEN
            v_result := '+855' || substr(v_result, 6);
        END IF;
        RETURN CASE WHEN v_result ~ '^\\+[1-9][0-9]{6,14}$' THEN v_result END;
    END $$;

    -- The words of a name, small letters, no marks or digits, in the order typed.
    CREATE FUNCTION app.tenant_name_words(p_name text) RETURNS text[]
    LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT COALESCE(array_agg(word ORDER BY position), '{}'::text[])
        FROM regexp_split_to_table(
            btrim(regexp_replace(lower(COALESCE(p_name, '')), '[[:punct:][:digit:][:space:]]+', ' ', 'g')),
            ' ') WITH ORDINALITY AS part(word, position)
        WHERE word <> ''
    $$;

    -- Owner rule: capitals, spaces and word order do not matter ("Kim Dara" is "Dara Kim", and
    -- "DaraKim" too).
    CREATE FUNCTION app.tenant_names_match(p_typed text, p_on_lease text) RETURNS boolean
    LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        WITH typed AS (SELECT app.tenant_name_words(p_typed) AS words),
            lease AS (SELECT app.tenant_name_words(p_on_lease) AS words)
        SELECT cardinality(typed.words) > 0 AND (
            (SELECT array_agg(word ORDER BY word) FROM unnest(typed.words) AS word)
                = (SELECT array_agg(word ORDER BY word) FROM unnest(lease.words) AS word)
            OR array_to_string(typed.words, '') = array_to_string(lease.words, '')
            OR array_to_string(typed.words, '') = (
                SELECT string_agg(word, '' ORDER BY position DESC)
                FROM unnest(lease.words) WITH ORDINALITY AS part(word, position)))
        FROM typed, lease
    $$;

    -- "Unit 305", "305" and "unit305" are the same Unit.
    CREATE FUNCTION app.tenant_unit_key(p_unit text) RETURNS text
    LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT regexp_replace(upper(regexp_replace(COALESCE(p_unit, ''), '[[:space:]]+', '', 'g')),
            '^(UNIT|ROOM|NO\\.?|#|បន្ទប់)', '')
    $$;

    -- The people a link may name: on a signed Lease that has not ended, the main tenant, each
    -- signer, and each person living there now.
    CREATE FUNCTION app.tenant_link_people(p_property uuid, p_day date)
    RETURNS TABLE (lease_id uuid, unit_id uuid, unit_number text, customer_id uuid,
        legal_name text, phone_number text, start_date date)
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT lease.id, unit.id, unit.unit_number, customer.id, customer.legal_name,
            customer.phone_number, lease.start_date
        FROM app.units AS unit
        JOIN app.leases AS lease ON lease.unit_id = unit.id
        JOIN LATERAL (
            SELECT lease.primary_tenant_id AS person
            UNION SELECT signer.customer_id FROM app.lease_signers AS signer
                WHERE signer.lease_id = lease.id
            UNION SELECT stay.customer_id FROM app.occupancies AS stay
                WHERE stay.lease_id = lease.id
                  AND (stay.move_out_date IS NULL OR stay.move_out_date >= p_day)
        ) AS people ON true
        JOIN app.customers AS customer ON customer.id = people.person
            AND customer.deactivated_at IS NULL
        WHERE unit.property_id = p_property AND lease.status = 'SIGNED' AND lease.end_date >= p_day
    $$;

    -- The link a Telegram account has now: not ended, and its Lease still signed and not over.
    CREATE FUNCTION app.tenant_active_link(p_property uuid, p_user bigint)
    RETURNS app.tenant_telegram_links
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT link.*
        FROM app.tenant_telegram_links AS link
        JOIN app.leases AS lease ON lease.id = link.lease_id
        WHERE link.property_id = p_property AND link.telegram_user_id = p_user
          AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                          WHERE ending.link_id = link.id)
          AND lease.status = 'SIGNED' AND lease.end_date >= app.gl_today(p_property)
        ORDER BY link.linked_at DESC
        LIMIT 1
    $$;

    -- When linking is blocked: 5 wrong tries in 24 hours block it until the 5th newest is a day old.
    CREATE FUNCTION app.tenant_link_blocked_until(p_property uuid, p_user bigint)
    RETURNS timestamptz LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT CASE WHEN count(*) >= 5 THEN min(attempt.created_at) + interval '24 hours' END
        FROM (
            SELECT tried.created_at FROM app.tenant_link_attempts AS tried
            WHERE tried.property_id = p_property AND tried.telegram_user_id = p_user
              AND tried.result = 'NO_MATCH'
              AND tried.created_at > clock_timestamp() - interval '24 hours'
            ORDER BY tried.created_at DESC
            LIMIT 5
        ) AS attempt
    $$;

    -- 1. Where a person is in a bot: language, step, link and block.
    CREATE FUNCTION app.telegram_bot_state(p_property uuid, p_bot text, p_user bigint, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_step app.telegram_chat_steps%ROWTYPE;
        v_link app.tenant_telegram_links%ROWTYPE;
        v_language text;
        v_account app.telegram_accounts%ROWTYPE;
        v_link_json jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        IF p_bot IS NULL OR p_bot NOT IN ('CUSTOMER', 'TENANT', 'STAFF') OR p_user IS NULL
            OR p_user <= 0 THEN
            RAISE EXCEPTION 'the bot or the person is not valid' USING ERRCODE = '22023';
        END IF;
        SELECT choice.language INTO v_language FROM app.telegram_language_choices AS choice
        WHERE choice.bot_code = p_bot AND choice.telegram_user_id = p_user
        ORDER BY choice.chosen_at DESC LIMIT 1;
        SELECT step.* INTO v_step FROM app.telegram_chat_steps AS step
        WHERE step.bot_code = p_bot AND step.telegram_user_id = p_user
        ORDER BY step.created_at DESC LIMIT 1;
        SELECT account.* INTO v_account FROM app.telegram_accounts AS account
        WHERE account.telegram_user_id = p_user;
        IF p_bot = 'TENANT' THEN
            v_link := app.tenant_active_link(p_property, p_user);
            IF v_link.id IS NOT NULL THEN
                SELECT jsonb_build_object('id', v_link.id, 'customer_id', v_link.customer_id,
                    'lease_id', v_link.lease_id, 'unit_id', v_link.unit_id,
                    'name', customer.legal_name, 'unit_number', unit.unit_number)
                INTO v_link_json
                FROM app.customers AS customer, app.units AS unit
                WHERE customer.id = v_link.customer_id AND unit.id = v_link.unit_id;
            END IF;
        END IF;
        RETURN jsonb_build_object(
            'language', v_language,
            'telegram_language', v_account.language,
            'has_phone', v_account.phone_e164 IS NOT NULL,
            'step', v_step.step,
            'data', COALESCE(v_step.data, '{}'::jsonb),
            'link', v_link_json,
            'blocked_until', CASE WHEN p_bot = 'TENANT'
                THEN app.tenant_link_blocked_until(p_property, p_user) END);
    END $$;

    -- 2. A bot's answer: the person's next step and the messages to send, in one go.
    CREATE FUNCTION app.telegram_bot_reply(p_property uuid, p_bot text, p_user bigint,
        p_chat bigint, p_step text, p_data jsonb, p_language text, p_messages jsonb, p_actor uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_message jsonb;
        v_count integer := 0;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        IF p_bot IS NULL OR p_bot NOT IN ('CUSTOMER', 'TENANT', 'STAFF') OR p_user IS NULL
            OR p_user <= 0 OR p_chat IS NULL OR p_chat = 0
            OR p_language IS DISTINCT FROM 'km' AND p_language IS DISTINCT FROM 'en'
            OR jsonb_typeof(p_messages) IS DISTINCT FROM 'array'
            OR jsonb_array_length(p_messages) > 5 THEN
            RAISE EXCEPTION 'the answer is not valid' USING ERRCODE = '22023';
        END IF;
        IF p_step IS NOT NULL THEN
            INSERT INTO app.telegram_chat_steps (bot_code, telegram_user_id, step, data, created_by)
            VALUES (p_bot, p_user, p_step, COALESCE(p_data, '{}'::jsonb), p_actor);
        END IF;
        FOR v_message IN SELECT value FROM jsonb_array_elements(p_messages) LOOP
            INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code, language,
                details, keyboard, created_by)
            VALUES (p_property, p_bot, p_chat, v_message ->> 'text_code', p_language,
                COALESCE(v_message -> 'details', '{}'::jsonb), v_message ->> 'keyboard', p_actor);
            v_count := v_count + 1;
        END LOOP;
        RETURN v_count;
    END $$;

    -- 3. The language a person chose (Khmer or English).
    CREATE FUNCTION app.telegram_choose_language(p_property uuid, p_bot text, p_user bigint,
        p_language text, p_actor uuid)
    RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        IF p_language IS NULL OR p_language NOT IN ('km', 'en') THEN
            RAISE EXCEPTION 'choose Khmer or English' USING ERRCODE = '22023';
        END IF;
        INSERT INTO app.telegram_language_choices (bot_code, telegram_user_id, language, created_by)
        VALUES (p_bot, p_user, p_language, p_actor);
    END $$;

    -- 4. One link try: the shared phone, the typed name and the typed Unit must all match one
    -- person on an active Lease.
    CREATE FUNCTION app.telegram_tenant_link(p_property uuid, p_user bigint, p_name text,
        p_unit text, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_name text := btrim(p_name);
        v_unit text := btrim(p_unit);
        v_phone text;
        v_blocked timestamptz;
        v_day date := app.gl_today(p_property);
        v_match record;
        v_current app.tenant_telegram_links%ROWTYPE;
        v_link uuid;
        v_fails integer;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        IF p_user IS NULL OR p_user <= 0 OR v_name IS NULL OR length(v_name) NOT BETWEEN 1 AND 120
            OR v_unit IS NULL OR length(v_unit) NOT BETWEEN 1 AND 20 THEN
            RAISE EXCEPTION 'type a name and a Unit' USING ERRCODE = '22023';
        END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended('tenant_link:' || p_user::text, 0));
        SELECT account.phone_e164 INTO v_phone FROM app.telegram_accounts AS account
        WHERE account.telegram_user_id = p_user;
        v_blocked := app.tenant_link_blocked_until(p_property, p_user);
        IF v_blocked IS NOT NULL THEN
            INSERT INTO app.tenant_link_attempts (property_id, telegram_user_id, phone_e164,
                typed_name, typed_unit, result, created_by)
            VALUES (p_property, p_user, v_phone, v_name, v_unit, 'BLOCKED', p_actor);
            RETURN jsonb_build_object('result', 'BLOCKED', 'tries_left', 0,
                'blocked_until', v_blocked);
        END IF;
        IF v_phone IS NULL THEN
            INSERT INTO app.tenant_link_attempts (property_id, telegram_user_id, phone_e164,
                typed_name, typed_unit, result, created_by)
            VALUES (p_property, p_user, NULL, v_name, v_unit, 'NO_PHONE', p_actor);
            RETURN jsonb_build_object('result', 'NO_PHONE');
        END IF;
        SELECT person.* INTO v_match
        FROM app.tenant_link_people(p_property, v_day) AS person
        WHERE app.tenant_unit_key(person.unit_number) = app.tenant_unit_key(v_unit)
          AND app.tenant_unit_key(v_unit) <> ''
          AND EXISTS (SELECT 1 FROM regexp_split_to_table(COALESCE(person.phone_number, ''),
                          '[/,;]') AS part(number)
                      WHERE app.phone_e164(part.number) = v_phone)
          AND app.tenant_names_match(v_name, person.legal_name)
        ORDER BY person.start_date DESC, person.lease_id
        LIMIT 1;
        IF v_match.lease_id IS NULL THEN
            INSERT INTO app.tenant_link_attempts (property_id, telegram_user_id, phone_e164,
                typed_name, typed_unit, result, created_by)
            VALUES (p_property, p_user, v_phone, v_name, v_unit, 'NO_MATCH', p_actor);
            SELECT count(*)::integer INTO v_fails FROM app.tenant_link_attempts AS tried
            WHERE tried.property_id = p_property AND tried.telegram_user_id = p_user
              AND tried.result = 'NO_MATCH'
              AND tried.created_at > clock_timestamp() - interval '24 hours';
            RETURN jsonb_build_object('result', 'NO_MATCH', 'tries_left', greatest(0, 5 - v_fails),
                'blocked_until', app.tenant_link_blocked_until(p_property, p_user));
        END IF;
        INSERT INTO app.tenant_link_attempts (property_id, telegram_user_id, phone_e164,
            typed_name, typed_unit, result, created_by)
        VALUES (p_property, p_user, v_phone, v_name, v_unit, 'LINKED', p_actor);
        v_current := app.tenant_active_link(p_property, p_user);
        IF v_current.id IS NOT NULL AND v_current.customer_id = v_match.customer_id
            AND v_current.lease_id = v_match.lease_id THEN
            v_link := v_current.id;
        ELSE
            IF v_current.id IS NOT NULL THEN
                INSERT INTO app.tenant_telegram_link_endings (link_id, reason, ended_by)
                VALUES (v_current.id, 'NEW_LINK', p_actor);
            END IF;
            INSERT INTO app.tenant_telegram_links (property_id, telegram_user_id, customer_id,
                lease_id, unit_id, created_by)
            VALUES (p_property, p_user, v_match.customer_id, v_match.lease_id, v_match.unit_id,
                p_actor)
            RETURNING id INTO v_link;
        END IF;
        RETURN jsonb_build_object('result', 'LINKED', 'link_id', v_link,
            'name', v_match.legal_name, 'unit_number', v_match.unit_number);
    END $$;

    -- 5. Links whose Lease ended or was not signed any more end by themselves (run by the pull job).
    CREATE FUNCTION app.telegram_tenant_end_finished_links(p_property uuid, p_actor uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_count integer;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        INSERT INTO app.tenant_telegram_link_endings (link_id, reason, ended_by)
        SELECT link.id, 'LEASE_ENDED', p_actor
        FROM app.tenant_telegram_links AS link
        JOIN app.leases AS lease ON lease.id = link.lease_id
        WHERE link.property_id = p_property
          AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                          WHERE ending.link_id = link.id)
          AND (lease.status <> 'SIGNED' OR lease.end_date < app.gl_today(p_property));
        GET DIAGNOSTICS v_count = ROW_COUNT;
        RETURN v_count;
    END $$;

    -- 6. Staff remove a link, with a reason (front desk: "Remove").
    CREATE FUNCTION app.telegram_tenant_link_remove(p_property uuid, p_link uuid, p_note text,
        p_actor uuid)
    RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_note text := btrim(p_note);
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        IF v_note IS NULL OR length(v_note) NOT BETWEEN 1 AND 300 THEN
            RAISE EXCEPTION 'Say why the link is removed, at most 300 letters' USING ERRCODE = '22023';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM app.tenant_telegram_links AS link
                       WHERE link.id = p_link AND link.property_id = p_property) THEN
            RAISE EXCEPTION 'the link was not found' USING ERRCODE = '22023';
        END IF;
        IF EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                   WHERE ending.link_id = p_link) THEN
            RAISE EXCEPTION 'the link has already ended' USING ERRCODE = '55000';
        END IF;
        INSERT INTO app.tenant_telegram_link_endings (link_id, reason, note, ended_by)
        VALUES (p_link, 'REMOVED', v_note, p_actor);
    END $$;

    -- 7. The Linked tenants list: links in force, newest first.
    CREATE FUNCTION app.telegram_tenant_links_read(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_rows jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.read', p_property);
        SELECT COALESCE(jsonb_agg(jsonb_build_object(
                'id', link.id, 'customer_id', link.customer_id, 'name', customer.legal_name,
                'lease_id', link.lease_id, 'unit_id', link.unit_id,
                'unit_number', unit.unit_number, 'linked_at', link.linked_at)
            ORDER BY link.linked_at DESC), '[]'::jsonb)
        INTO v_rows
        FROM app.tenant_telegram_links AS link
        JOIN app.customers AS customer ON customer.id = link.customer_id
        JOIN app.units AS unit ON unit.id = link.unit_id
        JOIN app.leases AS lease ON lease.id = link.lease_id
        WHERE link.property_id = p_property
          AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                          WHERE ending.link_id = link.id)
          AND lease.status = 'SIGNED' AND lease.end_date >= app.gl_today(p_property);
        RETURN v_rows;
    END $$;

    -- 8. Who may send Tenant bot forms, for the relay's access list.
    CREATE FUNCTION app.telegram_tenant_access_list(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_rows jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT COALESCE(jsonb_agg(jsonb_build_object('id', person.telegram_user_id,
                'role', 'TENANT') ORDER BY person.telegram_user_id), '[]'::jsonb)
        INTO v_rows
        FROM (
            SELECT DISTINCT link.telegram_user_id
            FROM app.tenant_telegram_links AS link
            JOIN app.leases AS lease ON lease.id = link.lease_id
            WHERE link.property_id = p_property
              AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                              WHERE ending.link_id = link.id)
              AND lease.status = 'SIGNED' AND lease.end_date >= app.gl_today(p_property)
        ) AS person;
        RETURN v_rows;
    END $$;

    -- 9. Link tries older than 90 days are removed.
    CREATE FUNCTION app.telegram_remove_old_link_attempts(p_property uuid, p_actor uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_count integer;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        DELETE FROM app.tenant_link_attempts AS tried
        WHERE tried.property_id = p_property
          AND tried.created_at < clock_timestamp() - interval '90 days';
        GET DIAGNOSTICS v_count = ROW_COUNT;
        RETURN v_count;
    END $$;

    -- The send job also needs the keyboard of each message.
    CREATE OR REPLACE FUNCTION app.telegram_outbox_due(p_property uuid, p_limit integer, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_due jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT COALESCE(jsonb_agg(row_to_json(due)::jsonb ORDER BY due.created_at), '[]'::jsonb)
        INTO v_due
        FROM (
            SELECT message.id, message.bot_code AS bot, message.chat_id, message.text_code,
                message.language, message.details, message.buttons, message.keyboard,
                message.created_at, COALESCE(tries.count, 0) AS tries
            FROM app.telegram_outbox AS message
            LEFT JOIN LATERAL (
                SELECT count(*)::integer AS count, max(attempt.attempted_at) AS last_at,
                    bool_or(attempt.outcome IN ('SENT', 'GAVE_UP')) AS final
                FROM app.telegram_outbox_attempts AS attempt WHERE attempt.outbox_id = message.id
            ) AS tries ON true
            WHERE message.property_id = p_property
              AND NOT COALESCE(tries.final, false)
              AND (tries.last_at IS NULL OR tries.last_at + make_interval(
                    mins => least(60, (2 ^ least(tries.count - 1, 6))::integer))
                  <= clock_timestamp())
            ORDER BY message.created_at
            LIMIT greatest(1, least(COALESCE(p_limit, 50), 200))
        ) AS due;
        RETURN v_due;
    END $$;
"""

HELPERS = (
    "app.tenant_link_people(uuid, date)",
    "app.tenant_active_link(uuid, bigint)",
    "app.tenant_link_blocked_until(uuid, bigint)",
)
JOB_FUNCTIONS = (
    "app.telegram_bot_state(uuid, text, bigint, uuid)",
    "app.telegram_bot_reply(uuid, text, bigint, bigint, text, jsonb, text, jsonb, uuid)",
    "app.telegram_choose_language(uuid, text, bigint, text, uuid)",
    "app.telegram_tenant_link(uuid, bigint, text, text, uuid)",
    "app.telegram_tenant_end_finished_links(uuid, uuid)",
    "app.telegram_tenant_link_remove(uuid, uuid, text, uuid)",
    "app.telegram_tenant_links_read(uuid, uuid)",
    "app.telegram_tenant_access_list(uuid, uuid)",
    "app.telegram_remove_old_link_attempts(uuid, uuid)",
)
# Typed names and phones stay behind the functions: the runtime login reads none of these tables.
TABLE_NAMES = (
    "app.telegram_language_choices, app.telegram_chat_steps, app.tenant_link_attempts, "
    "app.tenant_telegram_links, app.tenant_telegram_link_endings"
)


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    op.execute(f"REVOKE ALL ON TABLE {TABLE_NAMES} FROM PUBLIC, prm_runtime, prm_bootstrap")
    for signature in (
        "app.phone_e164(text)",
        "app.tenant_name_words(text)",
        "app.tenant_names_match(text, text)",
        "app.tenant_unit_key(text)",
        *HELPERS,
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in JOB_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("the Tenant bot link migration is forward-only")
