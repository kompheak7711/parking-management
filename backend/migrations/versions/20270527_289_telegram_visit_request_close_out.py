# ruff: noqa: E501
"""Telegram bots, step 3c: Make Reservation, Block, the 12-month removal and the month (DL-173).

Owner rules of 28 Oct 2026 (CRM users and flows) and the CRM mock-up:

* Make Reservation from a request: the Reservation is made the usual way (deposit first); the
  request then shows "Became Reservation" with the Reservation, and closes.
* A Manager can Block the Telegram account of a request (and Unblock it). A blocked account
  cannot send new inquiries or Contact office messages from the Customer bot.
* The name, phone, email, note and Telegram account of a request are removed when the request
  has had no activity for 12 months; the request, its number and its steps stay (the counts stay
  right). A Customer bot account that was not seen for 12 months loses its shared phone too
  (an account linked to a Lease keeps it).
* This month, the reasons and the sources are for Managers and the Owner.

1. ``visit_request_events`` gets RESERVED with the Reservation (one request per Reservation).
2. ``telegram_account_blocks`` (append-only): Block and Unblock, with who and why.
3. ``visit_requests`` keeps its rows; the only change allowed is the 12-month removal.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270527_289"
down_revision: str | None = "20270526_288"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATE = "app.visit_request_state(uuid)"
OPEN = "app.visit_request_open(uuid)"
ACT = "app.visit_request_act(uuid, uuid, text, jsonb, uuid)"
ROW = "app.visit_request_row(app.visit_requests)"
CARD = "app.visit_request_card(app.visit_requests, uuid)"
ADD = "app.telegram_visit_request_add(uuid, uuid, bigint, bigint, text, jsonb, uuid)"
CONTACT = "app.telegram_contact_add(uuid, uuid, text, bigint, bigint, text, text, text, uuid)"

TABLES = """
    ALTER TABLE app.visit_request_events
        DROP CONSTRAINT visit_request_events_kind_check,
        ADD CONSTRAINT visit_request_events_kind_check CHECK (kind IN ('TAKEN', 'GIVEN', 'CALL',
            'VISIT_BOOKED', 'VISITED', 'NO_SHOW', 'CLOSED', 'REOPENED', 'SPAM', 'SENT_BY_HAND',
            'REMINDER_DUE', 'RESERVED')),
        ADD COLUMN reservation_id uuid UNIQUE REFERENCES app.reservations (id) ON DELETE RESTRICT,
        ADD CONSTRAINT visit_request_events_reservation CHECK (
            (kind = 'RESERVED') = (reservation_id IS NOT NULL));

    CREATE TABLE app.telegram_account_blocks (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        blocked boolean NOT NULL,
        request_id uuid REFERENCES app.visit_requests (id) ON DELETE RESTRICT,
        note text CHECK (length(note) BETWEEN 1 AND 300 AND note = btrim(note)),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT telegram_account_blocks_why CHECK (NOT blocked OR note IS NOT NULL)
    );
    CREATE INDEX telegram_account_blocks_person_idx
        ON app.telegram_account_blocks (property_id, telegram_user_id, created_at);
    CREATE TRIGGER telegram_account_blocks_append_only BEFORE UPDATE OR DELETE
        ON app.telegram_account_blocks FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER telegram_account_blocks_no_truncate BEFORE TRUNCATE
        ON app.telegram_account_blocks FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    REVOKE ALL ON TABLE app.telegram_account_blocks FROM PUBLIC, prm_runtime, prm_bootstrap;

    -- The 12-month removal: the personal facts may be emptied once; nothing else changes.
    ALTER TABLE app.visit_requests
        ADD COLUMN removed_at timestamptz,
        ALTER COLUMN phone_e164 DROP NOT NULL,
        ALTER COLUMN customer_name DROP NOT NULL,
        DROP CONSTRAINT visit_requests_email,
        DROP CONSTRAINT visit_requests_telegram,
        ADD CONSTRAINT visit_requests_email CHECK (removed_at IS NOT NULL
            OR (contact_by = 'EMAIL') = (email IS NOT NULL)),
        ADD CONSTRAINT visit_requests_telegram CHECK (source <> 'TELEGRAM'
            OR (inbound_event_id IS NOT NULL AND (removed_at IS NOT NULL
                OR (telegram_user_id IS NOT NULL AND chat_id IS NOT NULL)))),
        ADD CONSTRAINT visit_requests_kept CHECK (removed_at IS NOT NULL
            OR (phone_e164 IS NOT NULL AND customer_name IS NOT NULL)),
        ADD CONSTRAINT visit_requests_removed CHECK (removed_at IS NULL OR (
            phone_e164 IS NULL AND customer_name IS NULL AND email IS NULL AND note IS NULL
            AND telegram_user_id IS NULL AND chat_id IS NULL));

    CREATE FUNCTION app.visit_requests_only_removal()
    RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    DECLARE
        v_personal text[] := ARRAY['removed_at', 'customer_name', 'phone_e164', 'email', 'note',
                                   'telegram_user_id', 'chat_id'];
    BEGIN
        IF TG_OP = 'UPDATE' AND OLD.removed_at IS NULL AND NEW.removed_at IS NOT NULL
           AND (to_jsonb(NEW) - v_personal) = (to_jsonb(OLD) - v_personal) THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'Visit requests are kept as they are' USING ERRCODE = '55000';
    END $$;
    DROP TRIGGER visit_requests_append_only ON app.visit_requests;
    CREATE TRIGGER visit_requests_append_only BEFORE UPDATE OR DELETE ON app.visit_requests
        FOR EACH ROW EXECUTE FUNCTION app.visit_requests_only_removal();
"""

FUNCTIONS = """
    CREATE FUNCTION app.telegram_user_blocked(p_property uuid, p_user bigint)
    RETURNS boolean LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT COALESCE((SELECT block.blocked FROM app.telegram_account_blocks AS block
                         WHERE block.property_id = p_property AND block.telegram_user_id = p_user
                         ORDER BY block.created_at DESC, block.id DESC LIMIT 1), false)
    $$;

    -- The 12-month removal (the Telegram jobs, every run). Answers how many requests lost
    -- their personal facts.
    CREATE FUNCTION app.visit_requests_remove_old(p_property uuid, p_actor uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_cut timestamptz := clock_timestamp() - interval '12 months';
        v_count integer;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        WITH stale AS (
            SELECT main.id FROM app.visit_requests AS main
            WHERE main.property_id = p_property AND main.joined_to IS NULL
              AND main.removed_at IS NULL AND main.received_at < v_cut
              AND NOT EXISTS (SELECT 1 FROM app.visit_request_events AS event
                              WHERE event.request_id = main.id AND event.created_at >= v_cut)
              AND NOT EXISTS (SELECT 1 FROM app.visit_requests AS kid
                              WHERE kid.joined_to = main.id AND kid.received_at >= v_cut)
        ), cleared AS (
            UPDATE app.visit_requests AS request
            SET removed_at = clock_timestamp(), customer_name = NULL, phone_e164 = NULL,
                email = NULL, note = NULL, telegram_user_id = NULL, chat_id = NULL
            WHERE request.removed_at IS NULL
              AND (request.id IN (SELECT stale.id FROM stale)
                   OR request.joined_to IN (SELECT stale.id FROM stale))
            RETURNING request.joined_to
        )
        SELECT count(*) FILTER (WHERE cleared.joined_to IS NULL)::integer INTO v_count
        FROM cleared;
        UPDATE app.telegram_accounts AS account SET phone_e164 = NULL
        WHERE account.phone_e164 IS NOT NULL AND account.last_seen_at < v_cut
          AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_links AS link
                          WHERE link.telegram_user_id = account.telegram_user_id);
        RETURN v_count;
    END $$;

    -- This month for Managers and the Owner: the counts, why requests closed, where they came from.
    CREATE FUNCTION app.visit_requests_month(p_property uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
    DECLARE
        v_zone text;
        v_from timestamptz;
    BEGIN
        SELECT property.timezone_name INTO v_zone FROM app.properties AS property
        WHERE property.id = p_property;
        v_from := date_trunc('month', timezone(v_zone, clock_timestamp())) AT TIME ZONE v_zone;
        RETURN jsonb_build_object(
            'month', to_char(timezone(v_zone, clock_timestamp()), 'YYYY-MM'),
            'new', (SELECT count(*) FROM app.visit_requests AS request
                    WHERE request.property_id = p_property AND request.joined_to IS NULL
                      AND request.received_at >= v_from),
            'joined', (SELECT count(*) FROM app.visit_requests AS request
                       WHERE request.property_id = p_property AND request.joined_to IS NOT NULL
                         AND request.received_at >= v_from),
            'steps', (SELECT jsonb_object_agg(kinds.kind, kinds.n) FROM (
                SELECT kind.kind, (SELECT count(DISTINCT event.request_id)
                    FROM app.visit_request_events AS event
                    JOIN app.visit_requests AS request ON request.id = event.request_id
                    WHERE request.property_id = p_property AND event.kind = kind.kind
                      AND event.created_at >= v_from) AS n
                FROM unnest(ARRAY['VISIT_BOOKED', 'VISITED', 'NO_SHOW', 'RESERVED', 'CLOSED',
                                  'SPAM']) AS kind (kind)) AS kinds),
            'reasons', (SELECT COALESCE(jsonb_agg(jsonb_build_object('reason', counted.reason,
                            'count', counted.n) ORDER BY counted.n DESC, counted.reason), '[]'::jsonb)
                        FROM (SELECT event.reason, count(*) AS n
                              FROM app.visit_request_events AS event
                              JOIN app.visit_requests AS request ON request.id = event.request_id
                              WHERE request.property_id = p_property AND event.kind = 'CLOSED'
                                AND event.created_at >= v_from
                              GROUP BY event.reason) AS counted),
            'sources', (SELECT COALESCE(jsonb_agg(jsonb_build_object('source', counted.source,
                            'count', counted.n) ORDER BY counted.n DESC, counted.source), '[]'::jsonb)
                        FROM (SELECT request.source, count(*) AS n
                              FROM app.visit_requests AS request
                              WHERE request.property_id = p_property
                                AND request.joined_to IS NULL AND request.received_at >= v_from
                              GROUP BY request.source) AS counted));
    END $$;

    -- The list (replaces step 3b's): adds the month for Managers and the Owner.
    CREATE OR REPLACE FUNCTION app.visit_requests_page(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_list jsonb;
        v_workers jsonb;
        v_manage boolean;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'visit_requests.read', p_property);
        v_manage := app.visit_request_holds(p_actor, 'visit_requests.manage', p_property);
        SELECT COALESCE(jsonb_agg(app.visit_request_card(main, p_actor)
            ORDER BY main.received_at, main.id), '[]'::jsonb)
        INTO v_list
        FROM app.visit_requests AS main
        WHERE main.property_id = p_property AND main.joined_to IS NULL;
        SELECT COALESCE(jsonb_agg(jsonb_build_object('id', account.actor_id,
                'name', account.display_name) ORDER BY account.display_name), '[]'::jsonb)
        INTO v_workers
        FROM app.user_accounts AS account
        WHERE account.lifecycle_state = 'active'
          AND app.visit_request_holds(account.actor_id, 'visit_requests.work', p_property);
        RETURN jsonb_build_object('requests', v_list,
            'today', app.visit_request_today(p_property),
            'address', (SELECT COALESCE(property.address_text, property.name)
                        FROM app.properties AS property WHERE property.id = p_property),
            'workers', v_workers,
            'me', p_actor,
            'can_work', app.visit_request_holds(p_actor, 'visit_requests.work', p_property),
            'can_manage', v_manage,
            'month', CASE WHEN v_manage THEN app.visit_requests_month(p_property) END);
    END $$;
"""

ACT_DECLARE = "        v_event uuid := gen_random_uuid();\n    BEGIN"
ACT_DECLARE_AFTER = (
    "        v_event uuid := gen_random_uuid();\n        v_reservation uuid;\n    BEGIN"
)
ACT_BLOCK_BEFORE = "        IF p_action = 'REOPEN' THEN"
ACT_BLOCK = """        IF p_action IN ('BLOCK', 'UNBLOCK') THEN
            IF NOT v_manager THEN
                RAISE EXCEPTION 'Only a Manager blocks a Telegram account' USING ERRCODE = '42501';
            END IF;
            IF v_request.telegram_user_id IS NULL THEN
                RAISE EXCEPTION 'This request has no Telegram account now' USING ERRCODE = '55000';
            END IF;
            IF (p_action = 'BLOCK') = app.telegram_user_blocked(p_property, v_request.telegram_user_id) THEN
                RAISE EXCEPTION 'The account is already so' USING ERRCODE = '55000';
            END IF;
            IF p_action = 'BLOCK' AND v_note IS NULL THEN
                RAISE EXCEPTION 'Write why' USING ERRCODE = '22023';
            END IF;
            INSERT INTO app.telegram_account_blocks (id, property_id, telegram_user_id, blocked,
                request_id, note, created_by)
            VALUES (v_event, p_property, v_request.telegram_user_id, p_action = 'BLOCK', p_request,
                v_note, p_actor);
            RETURN jsonb_build_object('event_id', v_event);
        END IF;
"""
ACT_RESERVE_BEFORE = "        ELSIF p_action = 'SENT' THEN"
ACT_RESERVE = """        ELSIF p_action = 'RESERVE' THEN
            IF v_status NOT IN ('CONTACTED', 'VISIT_BOOKED', 'VISITED', 'NO_SHOW') THEN
                RAISE EXCEPTION 'Talk to the customer first' USING ERRCODE = '55000';
            END IF;
            BEGIN
                v_reservation := (p_body ->> 'reservation_id')::uuid;
            EXCEPTION WHEN data_exception THEN
                v_reservation := NULL;
            END;
            IF v_reservation IS NULL OR NOT EXISTS (
                    SELECT 1 FROM app.reservations AS reservation
                    JOIN app.units AS unit ON unit.id = reservation.unit_id
                    WHERE reservation.id = v_reservation AND unit.property_id = p_property) THEN
                RAISE EXCEPTION 'Choose the Reservation' USING ERRCODE = '22023';
            END IF;
            IF EXISTS (SELECT 1 FROM app.visit_request_events AS event
                       WHERE event.reservation_id = v_reservation) THEN
                RAISE EXCEPTION 'This Reservation already belongs to a request' USING ERRCODE = '55000';
            END IF;
            INSERT INTO app.visit_request_events (id, request_id, kind, reservation_id, created_by)
            VALUES (v_event, p_request, 'RESERVED', v_reservation, p_actor);
"""

CARD_BEFORE = "            'to_send', v_send,"
CARD_AFTER = """            'to_send', v_send,
            'reservation_id', (SELECT event.reservation_id FROM app.visit_request_events AS event
                               WHERE event.request_id = p_request.id AND event.kind = 'RESERVED'
                               ORDER BY event.created_at DESC LIMIT 1),
            'blocked', p_request.telegram_user_id IS NOT NULL
                AND app.telegram_user_blocked(p_request.property_id, p_request.telegram_user_id),
            'removed', p_request.removed_at IS NOT NULL,"""

BLOCKED_ANSWER = """        IF app.telegram_user_blocked(p_property, p_user) THEN
            RETURN jsonb_build_object('result', 'BLOCKED');
        END IF;
"""


def _patch(signature: str, before: str, after: str, *, every: bool = False) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    found = definition.count(before)
    if found == 0 or (found != 1 and not every):
        raise RuntimeError(f"{signature} does not have the expected text")
    op.execute(text(definition.replace(before, after)))


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    for signature in (
        "app.telegram_user_blocked(uuid, bigint)",
        "app.visit_requests_month(uuid)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION app.visit_requests_remove_old(uuid, uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.visit_requests_remove_old(uuid, uuid) TO prm_runtime")

    # Became Reservation: a status of its own, and no longer open.
    _patch(
        STATE,
        "                WHEN 'VISITED' THEN v_status := 'VISITED';",
        "                WHEN 'VISITED' THEN v_status := 'VISITED';\n"
        "                WHEN 'RESERVED' THEN v_status := 'RESERVED';",
    )
    _patch(OPEN, "NOT IN ('CLOSED', 'SPAM')", "NOT IN ('CLOSED', 'SPAM', 'RESERVED')")
    _patch(ACT, ACT_DECLARE, ACT_DECLARE_AFTER)
    _patch(
        ACT,
        "v_status IN ('CLOSED', 'SPAM') THEN",
        "v_status IN ('CLOSED', 'SPAM', 'RESERVED') THEN",
        every=True,
    )
    _patch(
        ACT,
        "IF v_status IN ('CLOSED', 'SPAM', 'VISIT_BOOKED') THEN",
        "IF v_status IN ('CLOSED', 'SPAM', 'VISIT_BOOKED', 'RESERVED') THEN",
    )
    _patch(ACT, ACT_BLOCK_BEFORE, ACT_BLOCK + ACT_BLOCK_BEFORE)
    _patch(ACT, ACT_RESERVE_BEFORE, ACT_RESERVE + ACT_RESERVE_BEFORE)
    _patch(CARD, CARD_BEFORE, CARD_AFTER)
    # A removed request shows no name or phone.
    _patch(
        ROW,
        "'name', p_request.customer_name, 'phone', p_request.phone_e164,",
        "'name', COALESCE(p_request.customer_name, ''),"
        " 'phone', COALESCE(p_request.phone_e164, ''),",
    )
    # A blocked account sends no inquiry and no Contact office message from the Customer bot.
    _patch(
        ADD,
        "        SELECT account.phone_e164 INTO v_phone",
        BLOCKED_ANSWER + "        SELECT account.phone_e164 INTO v_phone",
    )
    _patch(
        CONTACT,
        "        IF p_bot = 'TENANT' THEN",
        "        IF p_bot = 'CUSTOMER' AND app.telegram_user_blocked(p_property, p_user) THEN\n"
        "            RETURN jsonb_build_object('result', 'BLOCKED');\n"
        "        END IF;\n"
        "        IF p_bot = 'TENANT' THEN",
    )


def downgrade() -> None:
    raise RuntimeError("the Visit requests close-out migration is forward-only")
