# ruff: noqa: E501
"""Telegram bots, step 1: the shared base (owner OK of the bots plan 03/11/2026 08:36, coding 04/11).

The tech and database plan SeEVTsVcU6eF7wx7uKeSEG (phase 5, T1 to T5 all recommended) puts
three bots (Customer, Tenant, Staff) on one base:

1. ``telegram_bots`` names the three bots (no keys: those stay files under /run/secrets).
2. ``telegram_accounts``: each Telegram person who used a bot, by Telegram's own number, with
   the language they chose and the phone they shared.
3. ``telegram_inbound_events``: every item pulled from the relay, saved once by its relay id
   (and once by Telegram's update number), so an item pulled twice is saved once. The raw
   message is kept 90 days; then only the summary stays.
4. ``telegram_outbox`` and ``telegram_outbox_attempts``: every message a bot must send waits in
   the outbox first; each try is a row. A message is Sent after a good try, keeps being tried
   with growing waits, and gives up after 7 days. Failing for 12 hours shows on the health page.
5. ``media_files``: each photo, video or voice note once, by its SHA-256 fingerprint, stored on
   the office disk (inside the encrypted backups). Problem reports and the staff forms link to it.
6. ``relay_pull_runs``: each pull from the relay, for the health page.

Rights (group Administration): See Telegram health (telegram.read) and Run the Telegram jobs
(telegram.operate, the account the pull and send timers run as). The Owner and Manager bundles
hold both, like every bundle right; Staff hold neither.

The relay on Cloudflare never reads this database. The office jobs pull from it and call these
functions. Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270430_281"
down_revision: str | None = "20270611_351"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROVENANCE = "v1-1-telegram-base"
CAPABILITIES = (
    ("telegram.read", "See the Telegram bots health"),
    ("telegram.operate", "Run the Telegram pull and send jobs"),
)
PERMISSIONS = (
    (
        "TELEGRAM_HEALTH",
        "See the Telegram bots health",
        "មើលស្ថានភាព Telegram bot",
        ("telegram.read",),
    ),
    (
        "TELEGRAM_JOBS",
        "Run the Telegram bot jobs",
        "ដំណើរការការងារ Telegram bot",
        ("telegram.operate",),
    ),
)
REASON = "Owner 2026-11-04: Telegram bots shared base rights"


def _text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


TABLES = """
    CREATE TABLE app.telegram_bots (
        code text PRIMARY KEY CHECK (code IN ('CUSTOMER', 'TENANT', 'STAFF')),
        name_en text NOT NULL,
        sort_order smallint NOT NULL UNIQUE
    );
    INSERT INTO app.telegram_bots (code, name_en, sort_order) VALUES
        ('CUSTOMER', 'CHETANA Residence', 1),
        ('TENANT', 'CHETANA Residence support', 2),
        ('STAFF', 'CHETANA staff', 3);

    -- One row per Telegram person. Telegram's number never changes; language and phone are the
    -- latest the person gave (each change is also kept in telegram_inbound_events).
    CREATE TABLE app.telegram_accounts (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        telegram_user_id bigint NOT NULL UNIQUE CHECK (telegram_user_id > 0),
        language text CHECK (language IN ('km', 'en')),
        phone_e164 text CHECK (phone_e164 ~ '^\\+[1-9][0-9]{6,14}$'),
        first_seen_at timestamptz NOT NULL,
        last_seen_at timestamptz NOT NULL,
        CONSTRAINT telegram_accounts_seen CHECK (last_seen_at >= first_seen_at)
    );

    CREATE TABLE app.telegram_inbound_events (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        relay_item_id text NOT NULL UNIQUE CHECK (relay_item_id ~ '^[A-Za-z0-9_-]{8,64}$'),
        bot_code text NOT NULL REFERENCES app.telegram_bots (code) ON DELETE RESTRICT,
        kind text NOT NULL CHECK (kind ~ '^[a-z][a-z_.]{1,40}$'),
        telegram_update_id bigint CHECK (telegram_update_id >= 0),
        account_id uuid REFERENCES app.telegram_accounts (id) ON DELETE RESTRICT,
        chat_id bigint,
        received_at timestamptz NOT NULL,
        pulled_at timestamptz NOT NULL DEFAULT statement_timestamp(),
        summary jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(summary) = 'object'),
        payload jsonb CHECK (payload IS NULL OR jsonb_typeof(payload) = 'object'),
        payload_removed_at timestamptz,
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT telegram_inbound_events_update UNIQUE (bot_code, telegram_update_id),
        CONSTRAINT telegram_inbound_events_removed CHECK (
            payload_removed_at IS NULL OR payload IS NULL)
    );
    CREATE INDEX telegram_inbound_events_received_idx
        ON app.telegram_inbound_events (received_at) WHERE payload IS NOT NULL;
    CREATE INDEX telegram_inbound_events_account_idx
        ON app.telegram_inbound_events (account_id, received_at DESC);

    CREATE TABLE app.media_files (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        sha256 text NOT NULL UNIQUE CHECK (sha256 ~ '^[0-9a-f]{64}$'),
        content_type text NOT NULL CHECK (content_type IN ('image/jpeg', 'image/png',
            'image/webp', 'video/mp4', 'audio/ogg', 'audio/mpeg', 'audio/mp4')),
        size_bytes bigint NOT NULL CHECK (size_bytes BETWEEN 1 AND 20971520),
        storage_path text NOT NULL UNIQUE CHECK (storage_path ~ '^[0-9a-f]{2}/[0-9a-f]{64}$'),
        width integer CHECK (width BETWEEN 1 AND 10000),
        height integer CHECK (height BETWEEN 1 AND 10000),
        duration_seconds integer CHECK (duration_seconds BETWEEN 0 AND 600),
        source text NOT NULL CHECK (source IN ('TELEGRAM', 'APP')),
        telegram_file_unique_id text CHECK (telegram_file_unique_id ~ '^[A-Za-z0-9_-]{1,64}$'),
        inbound_event_id uuid REFERENCES app.telegram_inbound_events (id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT media_files_path CHECK (storage_path = substr(sha256, 1, 2) || '/' || sha256),
        CONSTRAINT media_files_size CHECK ((width IS NULL) = (height IS NULL))
    );
    CREATE INDEX media_files_inbound_idx ON app.media_files (inbound_event_id)
        WHERE inbound_event_id IS NOT NULL;

    CREATE TABLE app.telegram_outbox (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        bot_code text NOT NULL REFERENCES app.telegram_bots (code) ON DELETE RESTRICT,
        chat_id bigint NOT NULL CHECK (chat_id <> 0),
        text_code text NOT NULL CHECK (text_code ~ '^[a-z][a-z0-9_.]{1,60}$'),
        language text NOT NULL CHECK (language IN ('km', 'en')),
        details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
        buttons jsonb CHECK (buttons IS NULL OR jsonb_typeof(buttons) = 'array'),
        created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX telegram_outbox_created_idx ON app.telegram_outbox (property_id, created_at);

    CREATE TABLE app.telegram_outbox_attempts (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        outbox_id uuid NOT NULL REFERENCES app.telegram_outbox (id) ON DELETE RESTRICT,
        attempt_number integer NOT NULL CHECK (attempt_number BETWEEN 1 AND 10000),
        outcome text NOT NULL CHECK (outcome IN ('SENT', 'FAILED', 'GAVE_UP')),
        error_code text CHECK (error_code ~ '^[a-z][a-z0-9_]{1,40}$'),
        telegram_message_id bigint CHECK (telegram_message_id > 0),
        attempted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT telegram_outbox_attempts_number UNIQUE (outbox_id, attempt_number),
        CONSTRAINT telegram_outbox_attempts_sent CHECK (
            (outcome = 'SENT') = (telegram_message_id IS NOT NULL)
            AND (outcome = 'SENT') = (error_code IS NULL))
    );
    -- At most one final try (Sent or Gave up) per message.
    CREATE UNIQUE INDEX telegram_outbox_attempts_final_idx ON app.telegram_outbox_attempts (outbox_id)
        WHERE outcome IN ('SENT', 'GAVE_UP');

    CREATE TABLE app.relay_pull_runs (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        started_at timestamptz NOT NULL,
        finished_at timestamptz NOT NULL,
        outcome text NOT NULL CHECK (outcome IN ('OK', 'FAILED')),
        error_code text CHECK (error_code ~ '^[a-z][a-z0-9_]{1,40}$'),
        items_received integer NOT NULL DEFAULT 0 CHECK (items_received >= 0),
        items_saved integer NOT NULL DEFAULT 0 CHECK (items_saved >= 0),
        items_repeated integer NOT NULL DEFAULT 0 CHECK (items_repeated >= 0),
        items_refused integer NOT NULL DEFAULT 0 CHECK (items_refused >= 0),
        relay_waiting integer CHECK (relay_waiting >= 0),
        relay_oldest_at timestamptz,
        relay_dropped integer CHECK (relay_dropped >= 0),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT relay_pull_runs_times CHECK (finished_at >= started_at),
        CONSTRAINT relay_pull_runs_error CHECK ((outcome = 'FAILED') = (error_code IS NOT NULL))
    );
    CREATE INDEX relay_pull_runs_property_idx ON app.relay_pull_runs (property_id, started_at DESC);

    -- History is never changed or emptied.
    CREATE FUNCTION app.reject_telegram_change() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    BEGIN
        RAISE EXCEPTION 'Telegram history is never changed' USING ERRCODE = '55000';
    END $$;
    REVOKE ALL ON FUNCTION app.reject_telegram_change() FROM PUBLIC;
    CREATE TRIGGER telegram_bots_fixed BEFORE INSERT OR UPDATE OR DELETE ON app.telegram_bots
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER telegram_accounts_no_delete BEFORE DELETE ON app.telegram_accounts
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER media_files_append_only BEFORE UPDATE OR DELETE ON app.media_files
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER telegram_outbox_append_only BEFORE UPDATE OR DELETE ON app.telegram_outbox
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER telegram_outbox_attempts_append_only BEFORE UPDATE OR DELETE
        ON app.telegram_outbox_attempts
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER relay_pull_runs_append_only BEFORE UPDATE OR DELETE ON app.relay_pull_runs
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER telegram_inbound_events_no_delete BEFORE DELETE ON app.telegram_inbound_events
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER telegram_bots_no_truncate BEFORE TRUNCATE ON app.telegram_bots
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER telegram_accounts_no_truncate BEFORE TRUNCATE ON app.telegram_accounts
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER telegram_inbound_events_no_truncate BEFORE TRUNCATE ON app.telegram_inbound_events
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER media_files_no_truncate BEFORE TRUNCATE ON app.media_files
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER telegram_outbox_no_truncate BEFORE TRUNCATE ON app.telegram_outbox
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER telegram_outbox_attempts_no_truncate BEFORE TRUNCATE
        ON app.telegram_outbox_attempts
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER relay_pull_runs_no_truncate BEFORE TRUNCATE ON app.relay_pull_runs
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();

    -- An inbound event changes only once: its raw message is removed after 90 days.
    CREATE FUNCTION app.protect_telegram_inbound_event() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    BEGIN
        IF OLD.payload IS NOT NULL AND NEW.payload IS NULL AND NEW.payload_removed_at IS NOT NULL
            AND OLD.payload_removed_at IS NULL
            AND (to_jsonb(NEW) - 'payload' - 'payload_removed_at')
                = (to_jsonb(OLD) - 'payload' - 'payload_removed_at') THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'Telegram history is never changed' USING ERRCODE = '55000';
    END $$;
    REVOKE ALL ON FUNCTION app.protect_telegram_inbound_event() FROM PUBLIC;
    CREATE TRIGGER telegram_inbound_events_payload_only BEFORE UPDATE ON app.telegram_inbound_events
        FOR EACH ROW EXECUTE FUNCTION app.protect_telegram_inbound_event();

    -- An account keeps its number and first time; only language, phone and last seen move.
    CREATE FUNCTION app.protect_telegram_account() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    BEGIN
        IF NEW.id <> OLD.id OR NEW.telegram_user_id <> OLD.telegram_user_id
            OR NEW.first_seen_at <> OLD.first_seen_at OR NEW.last_seen_at < OLD.last_seen_at THEN
            RAISE EXCEPTION 'Telegram history is never changed' USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION app.protect_telegram_account() FROM PUBLIC;
    CREATE TRIGGER telegram_accounts_protect BEFORE UPDATE ON app.telegram_accounts
        FOR EACH ROW EXECUTE FUNCTION app.protect_telegram_account();
"""

FUNCTIONS = """
    -- The account the jobs run as must hold the right on this Property.
    CREATE FUNCTION app.require_telegram_right(p_actor uuid, p_capability text, p_property uuid)
    RETURNS void LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM app.properties AS property WHERE property.id = p_property) THEN
            RAISE EXCEPTION 'the Property does not exist' USING ERRCODE = '22023';
        END IF;
        IF p_actor IS NULL OR NOT EXISTS (
            SELECT 1 FROM app.actor_capability_grants(p_actor) AS held
            WHERE held.capability_id = p_capability AND held.property_id = p_property
        ) THEN
            RAISE EXCEPTION 'this account may not do this' USING ERRCODE = '42501';
        END IF;
    END $$;
    REVOKE ALL ON FUNCTION app.require_telegram_right(uuid, text, uuid) FROM PUBLIC;

    -- The account for one Telegram number, made on first sight; language and phone when given.
    CREATE FUNCTION app.telegram_account_seen(p_user bigint, p_seen timestamptz,
        p_language text, p_phone text) RETURNS uuid
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    DECLARE v_id uuid;
    BEGIN
        INSERT INTO app.telegram_accounts AS account (telegram_user_id, language, phone_e164,
            first_seen_at, last_seen_at)
        VALUES (p_user, p_language, p_phone, p_seen, p_seen)
        ON CONFLICT (telegram_user_id) DO UPDATE SET
            language = COALESCE(EXCLUDED.language, account.language),
            phone_e164 = COALESCE(EXCLUDED.phone_e164, account.phone_e164),
            last_seen_at = greatest(account.last_seen_at, EXCLUDED.last_seen_at)
        RETURNING account.id INTO v_id;
        RETURN v_id;
    END $$;
    REVOKE ALL ON FUNCTION app.telegram_account_seen(bigint, timestamptz, text, text) FROM PUBLIC;

    -- 1. One item pulled from the relay, saved once. Returns whether it was new.
    CREATE FUNCTION app.telegram_record_pulled_item(p_property uuid, p_item jsonb, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_id uuid;
        v_existing uuid;
        v_account uuid;
        v_user bigint;
        v_update bigint;
        v_received timestamptz;
        v_media jsonb;
        v_media_id uuid;
        v_media_ids jsonb := '[]'::jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        IF p_item IS NULL OR jsonb_typeof(p_item) <> 'object'
            OR jsonb_typeof(p_item -> 'relay_item_id') IS DISTINCT FROM 'string'
            OR jsonb_typeof(p_item -> 'bot') IS DISTINCT FROM 'string'
            OR jsonb_typeof(p_item -> 'kind') IS DISTINCT FROM 'string'
            OR jsonb_typeof(p_item -> 'received_at') IS DISTINCT FROM 'string' THEN
            RAISE EXCEPTION 'the relay item is not complete' USING ERRCODE = '22023';
        END IF;
        SELECT event.id INTO v_existing FROM app.telegram_inbound_events AS event
        WHERE event.relay_item_id = p_item ->> 'relay_item_id';
        IF FOUND THEN
            RETURN jsonb_build_object('saved', false, 'inbound_id', v_existing);
        END IF;
        v_received := (p_item ->> 'received_at')::timestamptz;
        IF jsonb_typeof(p_item -> 'update_id') = 'number' THEN
            v_update := (p_item ->> 'update_id')::bigint;
            SELECT event.id INTO v_existing FROM app.telegram_inbound_events AS event
            WHERE event.bot_code = p_item ->> 'bot' AND event.telegram_update_id = v_update;
            IF FOUND THEN
                RETURN jsonb_build_object('saved', false, 'inbound_id', v_existing);
            END IF;
        END IF;
        IF jsonb_typeof(p_item -> 'telegram_user_id') = 'number' THEN
            v_user := (p_item ->> 'telegram_user_id')::bigint;
            v_account := app.telegram_account_seen(v_user, v_received,
                p_item #>> '{account,language}', p_item #>> '{account,phone}');
        END IF;
        INSERT INTO app.telegram_inbound_events (property_id, relay_item_id, bot_code, kind,
            telegram_update_id, account_id, chat_id, received_at, summary, payload, created_by)
        VALUES (p_property, p_item ->> 'relay_item_id', p_item ->> 'bot', p_item ->> 'kind',
            v_update, v_account, (p_item ->> 'chat_id')::bigint, v_received,
            COALESCE(p_item -> 'summary', '{}'::jsonb), p_item -> 'payload', p_actor)
        RETURNING id INTO v_id;
        FOR v_media IN SELECT value FROM jsonb_array_elements(COALESCE(p_item -> 'media', '[]'::jsonb))
        LOOP
            INSERT INTO app.media_files (sha256, content_type, size_bytes, storage_path, width,
                height, duration_seconds, source, telegram_file_unique_id, inbound_event_id,
                created_by)
            VALUES (v_media ->> 'sha256', v_media ->> 'content_type',
                (v_media ->> 'size_bytes')::bigint, v_media ->> 'storage_path',
                (v_media ->> 'width')::integer, (v_media ->> 'height')::integer,
                (v_media ->> 'duration_seconds')::integer, 'TELEGRAM',
                v_media ->> 'telegram_file_unique_id', v_id, p_actor)
            ON CONFLICT (sha256) DO NOTHING
            RETURNING id INTO v_media_id;
            IF v_media_id IS NULL THEN
                SELECT media.id INTO v_media_id FROM app.media_files AS media
                WHERE media.sha256 = v_media ->> 'sha256';
            END IF;
            v_media_ids := v_media_ids || jsonb_build_array(v_media_id);
            v_media_id := NULL;
        END LOOP;
        RETURN jsonb_build_object('saved', true, 'inbound_id', v_id, 'account_id', v_account,
            'media_ids', v_media_ids);
    END $$;

    -- 2. One pull from the relay.
    CREATE FUNCTION app.telegram_record_pull_run(p_property uuid, p_run jsonb, p_actor uuid)
    RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_id uuid;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        INSERT INTO app.relay_pull_runs (property_id, started_at, finished_at, outcome, error_code,
            items_received, items_saved, items_repeated, items_refused, relay_waiting,
            relay_oldest_at, relay_dropped, created_by)
        VALUES (p_property, (p_run ->> 'started_at')::timestamptz,
            (p_run ->> 'finished_at')::timestamptz, p_run ->> 'outcome', p_run ->> 'error_code',
            COALESCE((p_run ->> 'items_received')::integer, 0),
            COALESCE((p_run ->> 'items_saved')::integer, 0),
            COALESCE((p_run ->> 'items_repeated')::integer, 0),
            COALESCE((p_run ->> 'items_refused')::integer, 0),
            (p_run ->> 'relay_waiting')::integer, (p_run ->> 'relay_oldest_at')::timestamptz,
            (p_run ->> 'relay_dropped')::integer, p_actor)
        RETURNING id INTO v_id;
        RETURN v_id;
    END $$;

    -- 3. A message for a bot to send. Later steps call it from their own functions.
    CREATE FUNCTION app.telegram_queue(p_property uuid, p_bot text, p_chat bigint, p_text_code text,
        p_language text, p_details jsonb, p_buttons jsonb, p_actor uuid) RETURNS uuid
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    DECLARE v_id uuid;
    BEGIN
        INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code, language,
            details, buttons, created_by)
        VALUES (p_property, p_bot, p_chat, p_text_code, COALESCE(p_language, 'km'),
            COALESCE(p_details, '{}'::jsonb), p_buttons, p_actor)
        RETURNING id INTO v_id;
        RETURN v_id;
    END $$;
    REVOKE ALL ON FUNCTION app.telegram_queue(uuid, text, bigint, text, text, jsonb, jsonb, uuid)
        FROM PUBLIC;

    CREATE FUNCTION app.telegram_queue_message(p_property uuid, p_message jsonb, p_actor uuid)
    RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        IF p_message IS NULL OR jsonb_typeof(p_message) <> 'object'
            OR jsonb_typeof(p_message -> 'chat_id') IS DISTINCT FROM 'number' THEN
            RAISE EXCEPTION 'the message is not complete' USING ERRCODE = '22023';
        END IF;
        RETURN app.telegram_queue(p_property, p_message ->> 'bot',
            (p_message ->> 'chat_id')::bigint, p_message ->> 'text_code',
            p_message ->> 'language', p_message -> 'details', p_message -> 'buttons', p_actor);
    END $$;

    -- 4. Messages to send now: not sent, not given up, and past the wait after the last
    -- failed try (1, 2, 4 ... minutes, at most 60).
    CREATE FUNCTION app.telegram_outbox_due(p_property uuid, p_limit integer, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_due jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT COALESCE(jsonb_agg(row_to_json(due)::jsonb ORDER BY due.created_at), '[]'::jsonb)
        INTO v_due
        FROM (
            SELECT message.id, message.bot_code AS bot, message.chat_id, message.text_code,
                message.language, message.details, message.buttons, message.created_at,
                COALESCE(tries.count, 0) AS tries
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

    -- 5. One try. A failure after 7 days of tries is recorded as Gave up.
    CREATE FUNCTION app.telegram_record_send_attempt(p_property uuid, p_outbox uuid, p_outcome text,
        p_error_code text, p_message_id bigint, p_actor uuid) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_message app.telegram_outbox%ROWTYPE;
        v_outcome text := p_outcome;
        v_number integer;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT * INTO v_message FROM app.telegram_outbox AS message
        WHERE message.id = p_outbox AND message.property_id = p_property FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the message does not exist' USING ERRCODE = '22023';
        END IF;
        IF p_outcome NOT IN ('SENT', 'FAILED') THEN
            RAISE EXCEPTION 'a try is Sent or Failed' USING ERRCODE = '22023';
        END IF;
        IF EXISTS (SELECT 1 FROM app.telegram_outbox_attempts AS attempt
                   WHERE attempt.outbox_id = p_outbox AND attempt.outcome IN ('SENT', 'GAVE_UP')) THEN
            RAISE EXCEPTION 'the message is already finished' USING ERRCODE = '55000';
        END IF;
        IF v_outcome = 'FAILED' AND v_message.created_at < clock_timestamp() - interval '7 days' THEN
            v_outcome := 'GAVE_UP';
        END IF;
        SELECT COALESCE(max(attempt.attempt_number), 0) + 1 INTO v_number
        FROM app.telegram_outbox_attempts AS attempt WHERE attempt.outbox_id = p_outbox;
        INSERT INTO app.telegram_outbox_attempts (outbox_id, attempt_number, outcome, error_code,
            telegram_message_id, created_by)
        VALUES (p_outbox, v_number, v_outcome,
            CASE WHEN v_outcome = 'SENT' THEN NULL ELSE COALESCE(p_error_code, 'send_failed') END,
            CASE WHEN v_outcome = 'SENT' THEN p_message_id END, p_actor);
        RETURN v_outcome;
    END $$;

    -- 6. Remove raw messages older than 90 days; the summary stays.
    CREATE FUNCTION app.telegram_remove_old_payloads(p_property uuid, p_actor uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_count integer;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        UPDATE app.telegram_inbound_events AS event
        SET payload = NULL, payload_removed_at = statement_timestamp()
        WHERE event.property_id = p_property AND event.payload IS NOT NULL
          AND event.received_at < statement_timestamp() - interval '90 days';
        GET DIAGNOSTICS v_count = ROW_COUNT;
        RETURN v_count;
    END $$;

    -- 7. The health page numbers.
    CREATE FUNCTION app.telegram_health(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_last app.relay_pull_runs%ROWTYPE;
        v_last_ok timestamptz;
        v_waiting integer;
        v_failing integer;
        v_gave_up integer;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.read', p_property);
        SELECT * INTO v_last FROM app.relay_pull_runs AS run
        WHERE run.property_id = p_property ORDER BY run.started_at DESC LIMIT 1;
        SELECT max(run.finished_at) INTO v_last_ok FROM app.relay_pull_runs AS run
        WHERE run.property_id = p_property AND run.outcome = 'OK';
        SELECT count(*) FILTER (WHERE tries.final IS NOT TRUE)::integer,
            count(*) FILTER (WHERE tries.final IS NOT TRUE
                AND tries.first_failed_at < clock_timestamp() - interval '12 hours')::integer
        INTO v_waiting, v_failing
        FROM app.telegram_outbox AS message
        LEFT JOIN LATERAL (
            SELECT bool_or(attempt.outcome IN ('SENT', 'GAVE_UP')) AS final,
                min(attempt.attempted_at) FILTER (WHERE attempt.outcome = 'FAILED') AS first_failed_at
            FROM app.telegram_outbox_attempts AS attempt WHERE attempt.outbox_id = message.id
        ) AS tries ON true
        WHERE message.property_id = p_property;
        SELECT count(*)::integer INTO v_gave_up
        FROM app.telegram_outbox_attempts AS attempt
        JOIN app.telegram_outbox AS message ON message.id = attempt.outbox_id
        WHERE message.property_id = p_property AND attempt.outcome = 'GAVE_UP'
          AND attempt.attempted_at > clock_timestamp() - interval '7 days';
        RETURN jsonb_build_object(
            'last_pull_at', v_last.started_at,
            'last_pull_outcome', v_last.outcome,
            'last_pull_error', v_last.error_code,
            'last_ok_pull_at', v_last_ok,
            'relay_waiting', v_last.relay_waiting,
            'relay_oldest_at', v_last.relay_oldest_at,
            'relay_dropped', COALESCE(v_last.relay_dropped, 0),
            'outbox_waiting', v_waiting,
            'outbox_failing_12h', v_failing,
            'outbox_gave_up_7d', v_gave_up);
    END $$;
"""

JOB_FUNCTIONS = (
    "app.telegram_record_pulled_item(uuid, jsonb, uuid)",
    "app.telegram_record_pull_run(uuid, jsonb, uuid)",
    "app.telegram_queue_message(uuid, jsonb, uuid)",
    "app.telegram_outbox_due(uuid, integer, uuid)",
    "app.telegram_record_send_attempt(uuid, uuid, text, text, bigint, uuid)",
    "app.telegram_remove_old_payloads(uuid, uuid)",
    "app.telegram_health(uuid, uuid)",
)
TABLE_NAMES = (
    "app.telegram_bots, app.telegram_accounts, app.telegram_inbound_events, app.media_files, "
    "app.telegram_outbox, app.telegram_outbox_attempts, app.relay_pull_runs"
)


def upgrade() -> None:
    capability_rows = ",\n            ".join(
        f"({_text(name)}, pg_catalog.split_part({_text(name)}, '.', 1), {_text(description)}, "
        f"'bundle', '{PROVENANCE}')"
        for name, description in CAPABILITIES
    )
    mapping_rows = ",\n            ".join(
        f"({_text(code)}, {_text(name)}, '{PROVENANCE}')"
        for code, _en, _kh, names in PERMISSIONS
        for name in names
    )
    op.execute(
        f"""
        INSERT INTO app.capabilities (capability_id, family, description, grant_path, provenance)
        VALUES
            {capability_rows};
        """
    )
    for code, en, kh, _names in PERMISSIONS:
        op.execute(
            "INSERT INTO app.permissions (permission_code, group_code, sort_order, name_en, "
            f"name_kh, provenance) VALUES ({_text(code)}, 'ADMIN', "
            "(SELECT max(sort_order) FROM app.permissions) + 1, "
            f"{_text(en)}, {_text(kh)}, '{PROVENANCE}')"
        )
    op.execute(
        f"""
        INSERT INTO app.permission_capabilities (permission_code, capability_id, provenance)
        VALUES
            {mapping_rows};
        """
    )
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    op.execute(
        f"""
        REVOKE ALL ON TABLE {TABLE_NAMES} FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE {TABLE_NAMES} TO prm_runtime;
        """
    )
    for signature in JOB_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")

    # The Owner and Manager bundles of every Property get both rights (new Properties get them
    # from the seed, which gives those two bundles every bundle right). Staff get neither.
    added = "ARRAY[" + ", ".join(_text(name) for name, _ in CAPABILITIES) + "]::text[]"
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
                  ON bundle.role_bundle_id IN (seeded.owner_bundle_id, seeded.manager_bundle_id)
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
                SELECT v_default.role_bundle_id, v_default.version + 1, added
                FROM pg_catalog.unnest({added}) AS added;
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
                            'capabilities_added', pg_catalog.to_jsonb({added})),
                        pg_catalog.gen_random_uuid(), 'ADMINISTRATIVE', 'SUCCEEDED'
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    raise RuntimeError("the Telegram shared base migration is forward-only")
