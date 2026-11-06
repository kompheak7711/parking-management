# ruff: noqa: E501
"""Telegram bots, step 2c: the app pages Linked tenants and Telegram health (DL-128).

Owner-approved app screens (round 29, 3 Nov 2026 10:45, Office > Telegram): Linked tenants shows
the links in force, the link tries that did not match (with tries left or blocked until) and the
ended links; a link can be removed with a reason. Telegram health (Owner and Manager only) shows
the last relay pull, the messages waiting or failed with their last error and Retry, each bot's
last message in and out, and the last relay pulls. No bot keys are ever shown.

1. ``telegram_outbox_retries``: a message the send job gave up on, sent again from Telegram health
   (a new outbox message; each given-up message is retried once).

Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270522_284"
down_revision: str | None = "20270521_283"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = """
    CREATE TABLE app.telegram_outbox_retries (
        outbox_id uuid PRIMARY KEY REFERENCES app.telegram_outbox (id) ON DELETE RESTRICT,
        retry_outbox_id uuid NOT NULL UNIQUE REFERENCES app.telegram_outbox (id) ON DELETE RESTRICT,
        retried_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        retried_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT telegram_outbox_retries_other CHECK (outbox_id <> retry_outbox_id)
    );
    CREATE TRIGGER telegram_outbox_retries_append_only BEFORE UPDATE OR DELETE
        ON app.telegram_outbox_retries
        FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER telegram_outbox_retries_no_truncate BEFORE TRUNCATE ON app.telegram_outbox_retries
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
"""

FUNCTIONS = """
    -- Who a chat is, for the app: the linked tenant's name and Unit, else nothing.
    CREATE FUNCTION app.telegram_chat_person(p_property uuid, p_bot text, p_chat bigint)
    RETURNS jsonb LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT CASE WHEN p_bot = 'TENANT' THEN (
            SELECT jsonb_build_object('name', customer.legal_name, 'unit_number', unit.unit_number)
            FROM app.tenant_telegram_links AS link
            JOIN app.customers AS customer ON customer.id = link.customer_id
            JOIN app.units AS unit ON unit.id = link.unit_id
            WHERE link.property_id = p_property AND link.telegram_user_id = p_chat
            ORDER BY link.linked_at DESC LIMIT 1) END
    $$;

    -- 1. The Linked tenants page.
    CREATE FUNCTION app.telegram_links_page(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_day date;
        v_linked jsonb;
        v_tries jsonb;
        v_ended jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.read', p_property);
        v_day := app.gl_today(p_property);
        SELECT COALESCE(jsonb_agg(jsonb_build_object(
                'id', link.id, 'telegram_user_id', link.telegram_user_id,
                'phone', account.phone_e164, 'customer_id', link.customer_id,
                'name', customer.legal_name, 'unit_number', unit.unit_number,
                'lease_id', link.lease_id, 'lease_end_date', lease.end_date,
                'linked_at', link.linked_at)
            ORDER BY link.linked_at DESC), '[]'::jsonb)
        INTO v_linked
        FROM app.tenant_telegram_links AS link
        JOIN app.customers AS customer ON customer.id = link.customer_id
        JOIN app.units AS unit ON unit.id = link.unit_id
        JOIN app.leases AS lease ON lease.id = link.lease_id
        LEFT JOIN app.telegram_accounts AS account ON account.telegram_user_id = link.telegram_user_id
        WHERE link.property_id = p_property
          AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                          WHERE ending.link_id = link.id)
          AND lease.status = 'SIGNED' AND lease.end_date >= v_day;
        -- Accounts with wrong tries in the last 24 hours and no link now.
        SELECT COALESCE(jsonb_agg(person.row ORDER BY person.last_at DESC), '[]'::jsonb)
        INTO v_tries
        FROM (
            SELECT max(tried.created_at) AS last_at, jsonb_build_object(
                'telegram_user_id', tried.telegram_user_id,
                'phone', (array_agg(tried.phone_e164 ORDER BY tried.created_at DESC))[1],
                'typed_name', (array_agg(tried.typed_name ORDER BY tried.created_at DESC))[1],
                'typed_unit', (array_agg(tried.typed_unit ORDER BY tried.created_at DESC))[1],
                'tries', count(*),
                'tries_left', greatest(0, 5 - count(*)),
                'blocked_until', app.tenant_link_blocked_until(p_property, tried.telegram_user_id),
                'last_at', max(tried.created_at)) AS row
            FROM app.tenant_link_attempts AS tried
            WHERE tried.property_id = p_property AND tried.result = 'NO_MATCH'
              AND tried.created_at > clock_timestamp() - interval '24 hours'
              AND (app.tenant_active_link(p_property, tried.telegram_user_id)).id IS NULL
            GROUP BY tried.telegram_user_id
        ) AS person;
        SELECT COALESCE(jsonb_agg(jsonb_build_object(
                'id', link.id, 'telegram_user_id', link.telegram_user_id,
                'name', customer.legal_name, 'unit_number', unit.unit_number,
                'linked_at', link.linked_at, 'ended_at', ending.ended_at,
                'reason', ending.reason, 'note', ending.note)
            ORDER BY ending.ended_at DESC), '[]'::jsonb)
        INTO v_ended
        FROM app.tenant_telegram_link_endings AS ending
        JOIN app.tenant_telegram_links AS link ON link.id = ending.link_id
        JOIN app.customers AS customer ON customer.id = link.customer_id
        JOIN app.units AS unit ON unit.id = link.unit_id
        WHERE link.property_id = p_property
          AND ending.ended_at > clock_timestamp() - interval '90 days';
        RETURN jsonb_build_object('linked', v_linked, 'tries', v_tries, 'ended', v_ended,
            'rules', jsonb_build_object('tries', 5, 'block_hours', 24, 'keep_days', 90));
    END $$;

    -- 2. The Telegram health page (Owner and Manager).
    CREATE FUNCTION app.telegram_health_page(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_bots jsonb;
        v_outbox jsonb;
        v_pulls jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.read', p_property);
        SELECT jsonb_agg(jsonb_build_object('code', bot.code, 'name', bot.name_en,
                'last_in', (SELECT max(event.received_at) FROM app.telegram_inbound_events AS event
                            WHERE event.property_id = p_property AND event.bot_code = bot.code),
                'last_out', (SELECT max(attempt.attempted_at)
                             FROM app.telegram_outbox_attempts AS attempt
                             JOIN app.telegram_outbox AS message ON message.id = attempt.outbox_id
                             WHERE message.property_id = p_property AND message.bot_code = bot.code
                               AND attempt.outcome = 'SENT'),
                'failing', EXISTS (SELECT 1 FROM app.telegram_outbox AS message
                    JOIN app.telegram_outbox_attempts AS attempt ON attempt.outbox_id = message.id
                    WHERE message.property_id = p_property AND message.bot_code = bot.code
                      AND attempt.outcome IN ('FAILED', 'GAVE_UP')
                      AND attempt.attempted_at > clock_timestamp() - interval '12 hours'
                      AND NOT EXISTS (SELECT 1 FROM app.telegram_outbox_attempts AS later
                          WHERE later.outbox_id = message.id AND later.outcome = 'SENT')))
            ORDER BY bot.sort_order)
        INTO v_bots
        FROM app.telegram_bots AS bot;
        -- Messages not sent: still trying, or given up in the last 7 days and not sent again.
        SELECT COALESCE(jsonb_agg(pending.body ORDER BY pending.created_at), '[]'::jsonb)
        INTO v_outbox
        FROM (
            SELECT message.created_at, jsonb_build_object(
                'id', message.id, 'bot', message.bot_code, 'text_code', message.text_code,
                'created_at', message.created_at, 'tries', tries.count,
                'last_error', tries.last_error, 'last_try_at', tries.last_at,
                'status', CASE WHEN tries.gave_up THEN 'GAVE_UP' ELSE 'WAITING' END,
                'retried', EXISTS (SELECT 1 FROM app.telegram_outbox_retries AS retry
                                   WHERE retry.outbox_id = message.id),
                'to', app.telegram_chat_person(p_property, message.bot_code, message.chat_id))
                AS body
            FROM app.telegram_outbox AS message
            JOIN LATERAL (
                SELECT count(*)::integer AS count, max(attempt.attempted_at) AS last_at,
                    bool_or(attempt.outcome = 'SENT') AS sent,
                    bool_or(attempt.outcome = 'GAVE_UP') AS gave_up,
                    (array_agg(attempt.error_code ORDER BY attempt.attempt_number DESC))[1]
                        AS last_error
                FROM app.telegram_outbox_attempts AS attempt WHERE attempt.outbox_id = message.id
            ) AS tries ON true
            WHERE message.property_id = p_property AND tries.count > 0
              AND NOT COALESCE(tries.sent, false)
              AND (NOT COALESCE(tries.gave_up, false)
                   OR tries.last_at > clock_timestamp() - interval '7 days')
            ORDER BY message.created_at DESC
            LIMIT 50
        ) AS pending;
        SELECT COALESCE(jsonb_agg(jsonb_build_object('started_at', run.started_at,
                'outcome', run.outcome, 'error_code', run.error_code,
                'items_received', run.items_received, 'items_saved', run.items_saved,
                'items_refused', run.items_refused) ORDER BY run.started_at DESC), '[]'::jsonb)
        INTO v_pulls
        FROM (SELECT * FROM app.relay_pull_runs AS run WHERE run.property_id = p_property
              ORDER BY run.started_at DESC LIMIT 10) AS run;
        RETURN app.telegram_health(p_property, p_actor)
            || jsonb_build_object('bots', v_bots, 'outbox', v_outbox, 'pulls', v_pulls);
    END $$;

    -- Remove link from the app: a link of another Property "does not exist" (404 in the API).
    CREATE OR REPLACE FUNCTION app.telegram_tenant_link_remove(p_property uuid, p_link uuid,
        p_note text, p_actor uuid)
    RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_note text := btrim(p_note);
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        IF v_note IS NULL OR length(v_note) NOT BETWEEN 1 AND 300 THEN
            RAISE EXCEPTION 'Say why the link is removed, at most 300 letters' USING ERRCODE = '22023';
        END IF;
        PERFORM 1 FROM app.tenant_telegram_links AS link
        WHERE link.id = p_link AND link.property_id = p_property FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the link does not exist' USING ERRCODE = '22023';
        END IF;
        IF EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                   WHERE ending.link_id = p_link) THEN
            RAISE EXCEPTION 'The link has already ended' USING ERRCODE = '55000';
        END IF;
        INSERT INTO app.tenant_telegram_link_endings (link_id, reason, note, ended_by)
        VALUES (p_link, 'REMOVED', v_note, p_actor);
    END $$;

    -- 3. Retry a message the send job gave up on: a new message, once.
    CREATE FUNCTION app.telegram_outbox_retry(p_property uuid, p_outbox uuid, p_actor uuid)
    RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_message app.telegram_outbox%ROWTYPE;
        v_new uuid := gen_random_uuid();
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT message.* INTO v_message FROM app.telegram_outbox AS message
        WHERE message.id = p_outbox AND message.property_id = p_property FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the message does not exist' USING ERRCODE = '22023';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM app.telegram_outbox_attempts AS attempt
                       WHERE attempt.outbox_id = p_outbox AND attempt.outcome = 'GAVE_UP') THEN
            RAISE EXCEPTION 'Only a message the app gave up on can be sent again'
                USING ERRCODE = '55000';
        END IF;
        IF EXISTS (SELECT 1 FROM app.telegram_outbox_retries AS retry
                   WHERE retry.outbox_id = p_outbox) THEN
            RAISE EXCEPTION 'This message was already sent again' USING ERRCODE = '55000';
        END IF;
        INSERT INTO app.telegram_outbox (id, property_id, bot_code, chat_id, text_code, language,
            details, buttons, keyboard, created_by)
        VALUES (v_new, p_property, v_message.bot_code, v_message.chat_id, v_message.text_code,
            v_message.language, v_message.details, v_message.buttons, v_message.keyboard, p_actor);
        INSERT INTO app.telegram_outbox_retries (outbox_id, retry_outbox_id, retried_by)
        VALUES (p_outbox, v_new, p_actor);
        RETURN v_new;
    END $$;
"""

APP_FUNCTIONS = (
    "app.telegram_links_page(uuid, uuid)",
    "app.telegram_health_page(uuid, uuid)",
    "app.telegram_outbox_retry(uuid, uuid, uuid)",
)


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    op.execute(
        "REVOKE ALL ON TABLE app.telegram_outbox_retries FROM PUBLIC, prm_runtime, prm_bootstrap"
    )
    op.execute("REVOKE ALL ON FUNCTION app.telegram_chat_person(uuid, text, bigint) FROM PUBLIC")
    for signature in APP_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("the Telegram app pages migration is forward-only")
