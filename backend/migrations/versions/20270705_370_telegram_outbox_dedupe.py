# ruff: noqa: E501
"""Database review fixes of 7 Nov 2026, DL-202 (B): a Telegram message with a dedupe key waits once.

The read-only review of 7 Nov 2026 found that nothing in the database stopped the same automatic
message from being queued twice when a job ran again. The owner's answer of 7 Nov 2026 13:58:
add the dedupe key, and the jobs set it.

1. ``telegram_outbox.dedupe_key`` (optional): a short word, 1 to 120 letters, digits, dots,
   colons, dashes and underscores. The unique index ``telegram_outbox_dedupe_idx`` keeps one
   message per bot, chat and key. A message without a key is queued as before.
2. ``telegram_queue_once`` (internal) is the one way into the outbox with a key: it inserts, or
   returns the id of the message already waiting with that key and says nothing new was queued.
   ``telegram_queue`` (8 arguments) and ``telegram_queue_message`` use it; the message JSON may
   carry ``dedupe_key`` (the pull job keys the ping answer ``ping:<inbound id>``).
3. ``telegram_bot_reply`` gets a 10th argument ``p_reply_to``: the inbound message a bot answers.
   With it each answer is keyed ``reply:<inbound>:<n>``, so one inbound message gets its answer
   once; the number returned counts the messages newly queued. The 9-argument version stays
   and passes NULL.
4. A message sent again after Gave up (``telegram_outbox_retry``) copies no key: the key names
   the first message only.

Forward-only and additive. Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270705_370"
down_revision: str | None = "20270612_321"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEY_PATTERN = "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$"

SCHEMA = f"""
    ALTER TABLE app.telegram_outbox ADD COLUMN dedupe_key text
        CHECK (dedupe_key ~ '{KEY_PATTERN}');
    CREATE UNIQUE INDEX telegram_outbox_dedupe_idx
        ON app.telegram_outbox (bot_code, chat_id, dedupe_key) WHERE dedupe_key IS NOT NULL;
"""

FUNCTIONS = f"""
    -- 1. The one way into the outbox with a dedupe key (internal).
    CREATE FUNCTION app.telegram_queue_once(p_property uuid, p_bot text, p_chat bigint,
        p_text_code text, p_language text, p_details jsonb, p_buttons jsonb, p_keyboard text,
        p_dedupe_key text, p_actor uuid, OUT o_id uuid, OUT o_queued boolean)
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    BEGIN
        IF p_dedupe_key IS NOT NULL AND p_dedupe_key !~ '{KEY_PATTERN}' THEN
            RAISE EXCEPTION 'a dedupe key is 1 to 120 letters, digits, dots, colons, dashes or underscores'
                USING ERRCODE = '22023';
        END IF;
        INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code, language,
            details, buttons, keyboard, dedupe_key, created_by)
        VALUES (p_property, p_bot, p_chat, p_text_code, COALESCE(p_language, 'km'),
            COALESCE(p_details, '{{}}'::jsonb), p_buttons, p_keyboard, p_dedupe_key, p_actor)
        ON CONFLICT (bot_code, chat_id, dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING
        RETURNING id INTO o_id;
        o_queued := o_id IS NOT NULL;
        IF NOT o_queued THEN
            SELECT message.id INTO o_id FROM app.telegram_outbox AS message
            WHERE message.bot_code = p_bot AND message.chat_id = p_chat
              AND message.dedupe_key = p_dedupe_key;
        END IF;
    END $$;
    REVOKE ALL ON FUNCTION app.telegram_queue_once(uuid, text, bigint, text, text, jsonb, jsonb,
        text, text, uuid) FROM PUBLIC;

    -- 2. The old internal entry stays and queues without a key.
    CREATE OR REPLACE FUNCTION app.telegram_queue(p_property uuid, p_bot text, p_chat bigint,
        p_text_code text, p_language text, p_details jsonb, p_buttons jsonb, p_actor uuid)
    RETURNS uuid LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    DECLARE v_id uuid;
    BEGIN
        SELECT once.o_id INTO v_id
        FROM app.telegram_queue_once(p_property, p_bot, p_chat, p_text_code, p_language,
            p_details, p_buttons, NULL, NULL, p_actor) AS once;
        RETURN v_id;
    END $$;

    -- 3. A job's message may carry its key.
    CREATE OR REPLACE FUNCTION app.telegram_queue_message(p_property uuid, p_message jsonb,
        p_actor uuid)
    RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_id uuid;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        IF p_message IS NULL OR jsonb_typeof(p_message) <> 'object'
            OR jsonb_typeof(p_message -> 'chat_id') IS DISTINCT FROM 'number'
            OR jsonb_typeof(p_message -> 'dedupe_key') NOT IN ('string', 'null') THEN
            RAISE EXCEPTION 'the message is not complete' USING ERRCODE = '22023';
        END IF;
        SELECT once.o_id INTO v_id
        FROM app.telegram_queue_once(p_property, p_message ->> 'bot',
            (p_message ->> 'chat_id')::bigint, p_message ->> 'text_code',
            p_message ->> 'language', p_message -> 'details', p_message -> 'buttons', NULL,
            p_message ->> 'dedupe_key', p_actor) AS once;
        RETURN v_id;
    END $$;

    -- 4. A bot's answer names the inbound message it answers; each answer to it is queued once.
    CREATE FUNCTION app.telegram_bot_reply(p_property uuid, p_bot text, p_user bigint,
        p_chat bigint, p_step text, p_data jsonb, p_language text, p_messages jsonb,
        p_actor uuid, p_reply_to text)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_message record;
        v_queued boolean;
        v_count integer := 0;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        IF p_bot IS NULL OR p_bot NOT IN ('CUSTOMER', 'TENANT', 'STAFF') OR p_user IS NULL
            OR p_user <= 0 OR p_chat IS NULL OR p_chat = 0
            OR p_language IS DISTINCT FROM 'km' AND p_language IS DISTINCT FROM 'en'
            OR jsonb_typeof(p_messages) IS DISTINCT FROM 'array'
            OR jsonb_array_length(p_messages) > 5
            OR p_reply_to IS NOT NULL AND p_reply_to !~ '^[A-Za-z0-9][A-Za-z0-9_-]{{0,63}}$' THEN
            RAISE EXCEPTION 'the answer is not valid' USING ERRCODE = '22023';
        END IF;
        IF p_step IS NOT NULL THEN
            INSERT INTO app.telegram_chat_steps (bot_code, telegram_user_id, step, data, created_by)
            VALUES (p_bot, p_user, p_step, COALESCE(p_data, '{{}}'::jsonb), p_actor);
        END IF;
        FOR v_message IN
            SELECT element.value, element.ordinality
            FROM jsonb_array_elements(p_messages) WITH ORDINALITY AS element
        LOOP
            SELECT once.o_queued INTO v_queued
            FROM app.telegram_queue_once(p_property, p_bot, p_chat,
                v_message.value ->> 'text_code', p_language,
                COALESCE(v_message.value -> 'details', '{{}}'::jsonb), NULL,
                v_message.value ->> 'keyboard',
                CASE WHEN p_reply_to IS NOT NULL
                    THEN 'reply:' || p_reply_to || ':' || v_message.ordinality END,
                p_actor) AS once;
            IF v_queued THEN
                v_count := v_count + 1;
            END IF;
        END LOOP;
        RETURN v_count;
    END $$;

    -- The 9-argument answer stays for older callers and names no inbound message.
    CREATE OR REPLACE FUNCTION app.telegram_bot_reply(p_property uuid, p_bot text, p_user bigint,
        p_chat bigint, p_step text, p_data jsonb, p_language text, p_messages jsonb, p_actor uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        RETURN app.telegram_bot_reply(p_property, p_bot, p_user, p_chat, p_step, p_data,
            p_language, p_messages, p_actor, NULL::text);
    END $$;
"""

RUNTIME = (
    "app.telegram_bot_reply(uuid, text, bigint, bigint, text, jsonb, text, jsonb, uuid, text)",
)


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(FUNCTIONS)
    for signature in RUNTIME:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
