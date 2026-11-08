# ruff: noqa: E501
"""Database review fixes of 7 Nov 2026, DL-202 (C): a chat whose person blocked the bot gets nothing until the person writes again.

Owner rule of 7 Nov 2026 13:58: "stop sending when a chat blocks the bot. Set blocked
automatically when Telegram returns 'blocked', and clear it when the person writes again." The
review suggested a column on ``telegram_accounts``; that table is one row per Telegram person
across all bots, and a person blocks one bot at a time, so the block is kept per bot and chat in
its own append-only table (technical choice by Claude under the owner's 2026-10-23 22:30 rule).

1. ``app.telegram_bot_blocks``: one row each time a bot's chat is BLOCKED (Telegram answered 403,
   the send job records ``telegram_blocked_by_person``) or CLEARED (an inbound message from that
   chat was saved). Rows are never changed or deleted; the newest row says the state now.
   Nothing writes a row by hand: two triggers do it.
2. ``telegram_outbox_due`` leaves out the messages of a blocked chat, so the send job stops trying.
   The messages stay waiting and go out again once the chat is cleared.
3. ``telegram_health`` adds ``chats_blocked``, and ``outbox_failing_12h`` no longer counts the
   messages of a blocked chat (nothing is trying them).
4. Telegram also reports the block itself (``my_chat_member`` with status kicked or left); that
   inbound event does not clear the block.

Forward-only and additive.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270706_371"
down_revision: str | None = "20270705_370"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = """
    CREATE TABLE app.telegram_bot_blocks (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        seq bigint NOT NULL GENERATED ALWAYS AS IDENTITY UNIQUE,
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        bot_code text NOT NULL REFERENCES app.telegram_bots (code) ON DELETE RESTRICT,
        chat_id bigint NOT NULL CHECK (chat_id <> 0),
        kind text NOT NULL CHECK (kind IN ('BLOCKED', 'CLEARED')),
        outbox_id uuid REFERENCES app.telegram_outbox (id) ON DELETE RESTRICT,
        inbound_event_id uuid REFERENCES app.telegram_inbound_events (id) ON DELETE RESTRICT,
        noted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT telegram_bot_blocks_source CHECK (
            (kind = 'BLOCKED' AND inbound_event_id IS NULL)
            OR (kind = 'CLEARED' AND outbox_id IS NULL))
    );
    CREATE INDEX telegram_bot_blocks_chat_idx ON app.telegram_bot_blocks (bot_code, chat_id, seq DESC);
    CREATE INDEX telegram_bot_blocks_property_idx ON app.telegram_bot_blocks (property_id, seq DESC);
    CREATE TRIGGER telegram_bot_blocks_append_only BEFORE UPDATE OR DELETE ON app.telegram_bot_blocks
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER telegram_bot_blocks_no_truncate BEFORE TRUNCATE ON app.telegram_bot_blocks
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
"""

FUNCTIONS = """
    -- 1. Is this bot's chat blocked now? The newest row says.
    CREATE FUNCTION app.telegram_chat_blocked(p_bot text, p_chat bigint) RETURNS boolean
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT COALESCE((SELECT block.kind = 'BLOCKED' FROM app.telegram_bot_blocks AS block
            WHERE block.bot_code = p_bot AND block.chat_id = p_chat
            ORDER BY block.seq DESC LIMIT 1), false)
    $$;
    REVOKE ALL ON FUNCTION app.telegram_chat_blocked(text, bigint) FROM PUBLIC;

    -- 2. Telegram answered that the person blocked the bot: note the chat once.
    CREATE FUNCTION app.note_telegram_block() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_message app.telegram_outbox%ROWTYPE;
    BEGIN
        IF NEW.outcome IN ('FAILED', 'GAVE_UP') AND NEW.error_code = 'telegram_blocked_by_person' THEN
            SELECT * INTO v_message FROM app.telegram_outbox AS message
            WHERE message.id = NEW.outbox_id;
            PERFORM pg_advisory_xact_lock(hashtextextended(
                'telegram-block:' || v_message.bot_code || ':' || v_message.chat_id, 0));
            IF NOT app.telegram_chat_blocked(v_message.bot_code, v_message.chat_id) THEN
                INSERT INTO app.telegram_bot_blocks (property_id, bot_code, chat_id, kind, outbox_id,
                    created_by)
                VALUES (v_message.property_id, v_message.bot_code, v_message.chat_id, 'BLOCKED',
                    NEW.outbox_id, NEW.created_by);
            END IF;
        END IF;
        RETURN NULL;
    END $$;
    REVOKE ALL ON FUNCTION app.note_telegram_block() FROM PUBLIC;
    CREATE TRIGGER telegram_outbox_attempts_note_block AFTER INSERT ON app.telegram_outbox_attempts
        FOR EACH ROW EXECUTE FUNCTION app.note_telegram_block();

    -- 3. The person wrote again: the block is over. Telegram's own report of the block
    -- (my_chat_member with status kicked or left) is not the person writing.
    CREATE FUNCTION app.clear_telegram_block() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        IF NEW.chat_id IS NOT NULL
            AND COALESCE(NEW.payload #>> '{my_chat_member,new_chat_member,status}', '')
                NOT IN ('kicked', 'left') THEN
            PERFORM pg_advisory_xact_lock(hashtextextended(
                'telegram-block:' || NEW.bot_code || ':' || NEW.chat_id, 0));
            IF app.telegram_chat_blocked(NEW.bot_code, NEW.chat_id) THEN
                INSERT INTO app.telegram_bot_blocks (property_id, bot_code, chat_id, kind,
                    inbound_event_id, created_by)
                VALUES (NEW.property_id, NEW.bot_code, NEW.chat_id, 'CLEARED', NEW.id, NEW.created_by);
            END IF;
        END IF;
        RETURN NULL;
    END $$;
    REVOKE ALL ON FUNCTION app.clear_telegram_block() FROM PUBLIC;
    CREATE TRIGGER telegram_inbound_events_clear_block AFTER INSERT ON app.telegram_inbound_events
        FOR EACH ROW EXECUTE FUNCTION app.clear_telegram_block();

    -- 4. Messages to send now: as before (migration 20270520_282), without the blocked chats.
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
              AND NOT app.telegram_chat_blocked(message.bot_code, message.chat_id)
            ORDER BY message.created_at
            LIMIT greatest(1, least(COALESCE(p_limit, 50), 200))
        ) AS due;
        RETURN v_due;
    END $$;

    -- 5. The health page numbers (migration 20270430_281) plus the blocked chats.
    CREATE OR REPLACE FUNCTION app.telegram_health(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_last app.relay_pull_runs%ROWTYPE;
        v_last_ok timestamptz;
        v_waiting integer;
        v_failing integer;
        v_gave_up integer;
        v_blocked integer;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.read', p_property);
        SELECT * INTO v_last FROM app.relay_pull_runs AS run
        WHERE run.property_id = p_property ORDER BY run.started_at DESC LIMIT 1;
        SELECT max(run.finished_at) INTO v_last_ok FROM app.relay_pull_runs AS run
        WHERE run.property_id = p_property AND run.outcome = 'OK';
        SELECT count(*) FILTER (WHERE tries.final IS NOT TRUE)::integer,
            count(*) FILTER (WHERE tries.final IS NOT TRUE
                AND tries.first_failed_at < clock_timestamp() - interval '12 hours'
                AND NOT app.telegram_chat_blocked(message.bot_code, message.chat_id))::integer
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
        SELECT count(*)::integer INTO v_blocked
        FROM (
            SELECT DISTINCT ON (block.bot_code, block.chat_id) block.kind
            FROM app.telegram_bot_blocks AS block
            WHERE block.property_id = p_property
            ORDER BY block.bot_code, block.chat_id, block.seq DESC
        ) AS latest
        WHERE latest.kind = 'BLOCKED';
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
            'outbox_gave_up_7d', v_gave_up,
            'chats_blocked', v_blocked);
    END $$;
"""


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(
        "REVOKE ALL ON TABLE app.telegram_bot_blocks FROM PUBLIC, prm_runtime, prm_bootstrap; "
        "GRANT SELECT ON TABLE app.telegram_bot_blocks TO prm_runtime"
    )
    op.execute(FUNCTIONS)


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
