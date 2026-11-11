# ruff: noqa: E501
"""Telegram bots: a one-time QR links a tenant or a short-stay guest at once (DL-214).

Owner (11 Nov 2026, card "Add a Telegram QR at Lease signing and guest check-in?"): "Yes, QR for
tenants and guests". Staff open the Lease or the Booking, pick the person and show the QR; the
person scans it with the phone camera and taps Start in the Tenant bot, and is linked at once
with no name or Unit to type. A short-stay guest's link ends at check-out. Guests get no
Invoices on Telegram. Linking by typed name and Unit stays for Lease tenants.

1. ``app.telegram_link_codes``: one row per QR, with the SHA-256 of the code only (the code itself
   is shown once and never kept), the person, their Lease or Booking and Unit, who made it, and
   when it stops working (24 hours). ``app.telegram_link_code_uses`` records the one scan that
   used it. Both are never changed.
2. ``app.tenant_telegram_links`` can name a Booking instead of a Lease (exactly one of the two).
   A guest's link is live while the Booking is checked in, or booked with its check-in day come,
   up to its check-out day; it ends ("STAY_ENDED") when the stay is over. Every function that
   reads live links reads both kinds; the Invoice messages skip guest links.
3. ``app.telegram_bot_names``: each bot's Telegram user name as the send job last saw it, so the
   app can make the ``t.me`` link of the QR.
4. Functions: ``app.telegram_link_people`` (who on the Lease or Booking can get a QR: the
   ``leases.sign`` right for a Lease, ``short_stays.desk`` for a Booking),
   ``app.telegram_link_code_create`` (makes the code and its link), ``app.telegram_tenant_link_code``
   (the Tenant bot's Start with a code, ``telegram.operate``), ``app.telegram_link_codes_offline``
   (the codes' hashes and Units, so the relay links a scan while the office is away) and
   ``app.telegram_bot_name_set`` (the send job).

Technical choices by Claude under the owner's 2026-10-23 22:30 rule. Forward-only.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270712_384"
down_revision: str | None = "20270711_383"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CODE_HOURS = 24

TABLES = """
    ALTER TABLE app.tenant_telegram_links
        ADD COLUMN booking_id uuid REFERENCES app.short_stay_bookings (id) ON DELETE RESTRICT,
        ALTER COLUMN lease_id DROP NOT NULL,
        ADD CONSTRAINT tenant_telegram_links_one_stay CHECK (num_nonnulls(lease_id, booking_id) = 1);
    CREATE INDEX tenant_telegram_links_booking_idx ON app.tenant_telegram_links (booking_id)
        WHERE booking_id IS NOT NULL;
    ALTER TABLE app.tenant_telegram_link_endings
        DROP CONSTRAINT tenant_telegram_link_endings_reason_check,
        ADD CONSTRAINT tenant_telegram_link_endings_reason_check
            CHECK (reason IN ('LEASE_ENDED', 'REMOVED', 'NEW_LINK', 'STAY_ENDED'));

    CREATE TABLE app.telegram_link_codes (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        code_hash text NOT NULL UNIQUE CHECK (code_hash ~ '^[0-9a-f]{64}$'),
        customer_id uuid NOT NULL REFERENCES app.customers (id) ON DELETE RESTRICT,
        lease_id uuid REFERENCES app.leases (id) ON DELETE RESTRICT,
        booking_id uuid REFERENCES app.short_stay_bookings (id) ON DELETE RESTRICT,
        unit_id uuid NOT NULL REFERENCES app.units (id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        expires_at timestamptz NOT NULL,
        CONSTRAINT telegram_link_codes_one_stay CHECK (num_nonnulls(lease_id, booking_id) = 1),
        CONSTRAINT telegram_link_codes_expiry CHECK (expires_at > created_at)
    );
    CREATE INDEX telegram_link_codes_property_idx
        ON app.telegram_link_codes (property_id, expires_at DESC);

    CREATE TABLE app.telegram_link_code_uses (
        code_id uuid PRIMARY KEY REFERENCES app.telegram_link_codes (id) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        link_id uuid NOT NULL UNIQUE REFERENCES app.tenant_telegram_links (id) ON DELETE RESTRICT,
        used_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );

    CREATE TABLE app.telegram_bot_names (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        bot_code text NOT NULL REFERENCES app.telegram_bots (code) ON DELETE RESTRICT,
        username text NOT NULL CHECK (username ~ '^[A-Za-z][A-Za-z0-9_]{3,31}$'),
        seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX telegram_bot_names_bot_idx
        ON app.telegram_bot_names (property_id, bot_code, seen_at DESC);
"""

APPEND_ONLY = ("telegram_link_codes", "telegram_link_code_uses", "telegram_bot_names")

FUNCTIONS = f"""
    -- A Lease or a Booking a link may name on this day.
    CREATE FUNCTION app.tenant_link_stay_live(p_lease uuid, p_booking uuid, p_day date)
    RETURNS boolean LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT CASE
            WHEN p_lease IS NOT NULL THEN EXISTS (
                SELECT 1 FROM app.leases AS lease
                WHERE lease.id = p_lease AND lease.status = 'SIGNED' AND lease.end_date >= p_day)
            WHEN p_booking IS NOT NULL THEN EXISTS (
                SELECT 1 FROM app.short_stay_bookings AS booking
                WHERE booking.id = p_booking AND booking.check_out_on >= p_day
                  AND (booking.status = 'CHECKED_IN'
                       OR (booking.status = 'BOOKED' AND booking.check_in_on <= p_day)))
            ELSE false
        END
    $$;

    -- The link a Telegram account has now: not ended, and its Lease or stay not over.
    CREATE OR REPLACE FUNCTION app.tenant_active_link(p_property uuid, p_user bigint)
    RETURNS app.tenant_telegram_links
    LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT link.*
        FROM app.tenant_telegram_links AS link
        WHERE link.property_id = p_property AND link.telegram_user_id = p_user
          AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                          WHERE ending.link_id = link.id)
          AND app.tenant_link_stay_live(link.lease_id, link.booking_id, app.gl_today(p_property))
        ORDER BY link.linked_at DESC
        LIMIT 1
    $$;

    CREATE OR REPLACE FUNCTION app.telegram_tenant_end_finished_links(p_property uuid, p_actor uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_count integer;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        INSERT INTO app.tenant_telegram_link_endings (link_id, reason, ended_by)
        SELECT link.id, CASE WHEN link.booking_id IS NULL THEN 'LEASE_ENDED' ELSE 'STAY_ENDED' END,
            p_actor
        FROM app.tenant_telegram_links AS link
        WHERE link.property_id = p_property
          AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                          WHERE ending.link_id = link.id)
          AND NOT app.tenant_link_stay_live(link.lease_id, link.booking_id,
                                            app.gl_today(p_property));
        GET DIAGNOSTICS v_count = ROW_COUNT;
        RETURN v_count;
    END $$;

    CREATE OR REPLACE FUNCTION app.telegram_tenant_access_list(p_property uuid, p_actor uuid)
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
            WHERE link.property_id = p_property
              AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                              WHERE ending.link_id = link.id)
              AND app.tenant_link_stay_live(link.lease_id, link.booking_id,
                                            app.gl_today(p_property))
        ) AS person;
        RETURN v_rows;
    END $$;

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
                WHERE link.property_id = p_property
                  AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                                  WHERE ending.link_id = link.id)
                  AND app.tenant_link_stay_live(link.lease_id, link.booking_id,
                                                app.gl_today(p_property))
                ORDER BY link.telegram_user_id, link.linked_at DESC
            ) AS link
            JOIN app.units AS unit ON unit.id = link.unit_id
        ) AS person;
        RETURN jsonb_build_object('choices', v_choices, 'users', v_users);
    END $$;

    CREATE OR REPLACE FUNCTION app.telegram_tenant_links_read(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_rows jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.read', p_property);
        SELECT COALESCE(jsonb_agg(jsonb_build_object(
                'id', link.id, 'customer_id', link.customer_id, 'name', customer.legal_name,
                'lease_id', link.lease_id, 'booking_id', link.booking_id, 'unit_id', link.unit_id,
                'unit_number', unit.unit_number, 'linked_at', link.linked_at)
            ORDER BY link.linked_at DESC), '[]'::jsonb)
        INTO v_rows
        FROM app.tenant_telegram_links AS link
        JOIN app.customers AS customer ON customer.id = link.customer_id
        JOIN app.units AS unit ON unit.id = link.unit_id
        WHERE link.property_id = p_property
          AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                          WHERE ending.link_id = link.id)
          AND app.tenant_link_stay_live(link.lease_id, link.booking_id, app.gl_today(p_property));
        RETURN v_rows;
    END $$;

    CREATE OR REPLACE FUNCTION app.telegram_links_page(p_property uuid, p_actor uuid)
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
                'booking_id', link.booking_id, 'booking_number', booking.booking_number,
                'stay_end_date', booking.check_out_on,
                'linked_at', link.linked_at)
            ORDER BY link.linked_at DESC), '[]'::jsonb)
        INTO v_linked
        FROM app.tenant_telegram_links AS link
        JOIN app.customers AS customer ON customer.id = link.customer_id
        JOIN app.units AS unit ON unit.id = link.unit_id
        LEFT JOIN app.leases AS lease ON lease.id = link.lease_id
        LEFT JOIN app.short_stay_bookings AS booking ON booking.id = link.booking_id
        LEFT JOIN app.telegram_accounts AS account ON account.telegram_user_id = link.telegram_user_id
        WHERE link.property_id = p_property
          AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                          WHERE ending.link_id = link.id)
          AND app.tenant_link_stay_live(link.lease_id, link.booking_id, v_day);
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

    -- The bot's Telegram user name as the send job last saw it.
    CREATE FUNCTION app.telegram_bot_name(p_property uuid, p_bot text)
    RETURNS text LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT name.username FROM app.telegram_bot_names AS name
        WHERE name.property_id = p_property AND name.bot_code = p_bot
        ORDER BY name.seen_at DESC LIMIT 1
    $$;

    CREATE FUNCTION app.telegram_bot_name_set(p_property uuid, p_bot text, p_username text,
        p_actor uuid)
    RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        IF p_username IS NULL OR p_username !~ '^[A-Za-z][A-Za-z0-9_]{{3,31}}$' THEN
            RAISE EXCEPTION 'the bot name is not valid' USING ERRCODE = '22023';
        END IF;
        IF app.telegram_bot_name(p_property, p_bot) IS NOT DISTINCT FROM p_username THEN
            RETURN false;
        END IF;
        INSERT INTO app.telegram_bot_names (property_id, bot_code, username, created_by)
        VALUES (p_property, p_bot, p_username, p_actor);
        RETURN true;
    END $$;

    -- The people of a Lease or a Booking who can get a QR, and the Unit.
    CREATE FUNCTION app.telegram_link_stay(p_property uuid, p_lease uuid, p_booking uuid,
        p_actor uuid)
    RETURNS TABLE (customer_id uuid, legal_name text, unit_id uuid, unit_number text)
    LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
    DECLARE v_day date := app.gl_today(p_property);
    BEGIN
        IF num_nonnulls(p_lease, p_booking) <> 1 THEN
            RAISE EXCEPTION 'name one Lease or one Booking' USING ERRCODE = '22023';
        END IF;
        IF p_lease IS NOT NULL THEN
            PERFORM app.require_telegram_right(p_actor, 'leases.sign', p_property);
            RETURN QUERY
            SELECT DISTINCT ON (person.customer_id) person.customer_id, person.legal_name,
                person.unit_id, person.unit_number
            FROM app.tenant_link_people(p_property, v_day) AS person
            WHERE person.lease_id = p_lease
            ORDER BY person.customer_id;
        ELSE
            PERFORM app.require_telegram_right(p_actor, 'short_stays.desk', p_property);
            RETURN QUERY
            SELECT customer.id, customer.legal_name, unit.id, unit.unit_number
            FROM app.short_stay_bookings AS booking
            JOIN app.customers AS customer ON customer.id = booking.customer_id
            JOIN app.units AS unit ON unit.id = booking.unit_id
            WHERE booking.id = p_booking AND booking.property_id = p_property
              AND app.tenant_link_stay_live(NULL, booking.id, v_day);
        END IF;
    END $$;

    CREATE FUNCTION app.telegram_link_people(p_property uuid, p_lease uuid, p_booking uuid,
        p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_people jsonb;
    BEGIN
        SELECT COALESCE(jsonb_agg(jsonb_build_object('customer_id', person.customer_id,
                'name', person.legal_name, 'unit_number', person.unit_number)
                ORDER BY person.legal_name, person.customer_id), '[]'::jsonb)
        INTO v_people
        FROM app.telegram_link_stay(p_property, p_lease, p_booking, p_actor) AS person;
        RETURN jsonb_build_object('people', v_people,
            'bot_ready', app.telegram_bot_name(p_property, 'TENANT') IS NOT NULL,
            'hours', {CODE_HOURS});
    END $$;

    -- Make a one-time code and its t.me link. The code is returned once and only its hash kept.
    CREATE FUNCTION app.telegram_link_code_create(p_property uuid, p_lease uuid, p_booking uuid,
        p_customer uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_person record;
        v_bot text;
        v_code text := replace(gen_random_uuid()::text, '-', '')
            || substr(replace(gen_random_uuid()::text, '-', ''), 1, 8);
        v_expires timestamptz := clock_timestamp() + interval '{CODE_HOURS} hours';
    BEGIN
        SELECT person.* INTO v_person
        FROM app.telegram_link_stay(p_property, p_lease, p_booking, p_actor) AS person
        WHERE person.customer_id = p_customer;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'this person is not on a live Lease or stay' USING ERRCODE = '22023';
        END IF;
        v_bot := app.telegram_bot_name(p_property, 'TENANT');
        IF v_bot IS NULL THEN
            RAISE EXCEPTION 'the Tenant bot is not set up yet' USING ERRCODE = '55000';
        END IF;
        INSERT INTO app.telegram_link_codes (property_id, code_hash, customer_id, lease_id,
            booking_id, unit_id, created_by, expires_at)
        VALUES (p_property, encode(sha256(convert_to(v_code, 'UTF8')), 'hex'), p_customer,
            p_lease, p_booking, v_person.unit_id, p_actor, v_expires);
        RETURN jsonb_build_object('url', 'https://t.me/' || v_bot || '?start=' || v_code,
            'bot', v_bot, 'name', v_person.legal_name, 'unit_number', v_person.unit_number,
            'expires_at', v_expires);
    END $$;

    -- The Tenant bot's Start with a code: link at once, or say why not.
    CREATE FUNCTION app.telegram_tenant_link_code(p_property uuid, p_user bigint, p_code text,
        p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_code app.telegram_link_codes%ROWTYPE;
        v_used app.telegram_link_code_uses%ROWTYPE;
        v_current app.tenant_telegram_links%ROWTYPE;
        v_link uuid;
        v_name text;
        v_unit text;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        IF p_user IS NULL OR p_user <= 0 THEN
            RAISE EXCEPTION 'the Telegram account is not valid' USING ERRCODE = '22023';
        END IF;
        IF p_code IS NULL OR p_code !~ '^[0-9a-f]{{40}}$' THEN
            RETURN jsonb_build_object('result', 'NOT_FOUND');
        END IF;
        SELECT code.* INTO v_code FROM app.telegram_link_codes AS code
        WHERE code.property_id = p_property
          AND code.code_hash = encode(sha256(convert_to(p_code, 'UTF8')), 'hex')
        FOR UPDATE;
        IF NOT FOUND THEN
            RETURN jsonb_build_object('result', 'NOT_FOUND');
        END IF;
        SELECT customer.legal_name INTO v_name FROM app.customers AS customer
        WHERE customer.id = v_code.customer_id;
        SELECT unit.unit_number INTO v_unit FROM app.units AS unit WHERE unit.id = v_code.unit_id;
        SELECT used.* INTO v_used FROM app.telegram_link_code_uses AS used
        WHERE used.code_id = v_code.id;
        IF FOUND THEN
            -- The same person scanning again is told they are linked; anyone else is refused.
            IF v_used.telegram_user_id = p_user
                AND (app.tenant_active_link(p_property, p_user)).id = v_used.link_id THEN
                RETURN jsonb_build_object('result', 'LINKED', 'link_id', v_used.link_id,
                    'name', v_name, 'unit_number', v_unit, 'repeated', true);
            END IF;
            RETURN jsonb_build_object('result', 'USED');
        END IF;
        IF v_code.expires_at <= clock_timestamp() THEN
            RETURN jsonb_build_object('result', 'EXPIRED');
        END IF;
        IF NOT app.tenant_link_stay_live(v_code.lease_id, v_code.booking_id,
                                         app.gl_today(p_property)) THEN
            RETURN jsonb_build_object('result', 'ENDED');
        END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended('tenant_link:' || p_user::text, 0));
        v_current := app.tenant_active_link(p_property, p_user);
        IF v_current.id IS NOT NULL THEN
            INSERT INTO app.tenant_telegram_link_endings (link_id, reason, ended_by)
            VALUES (v_current.id, 'NEW_LINK', p_actor);
        END IF;
        INSERT INTO app.tenant_telegram_links (property_id, telegram_user_id, customer_id,
            lease_id, booking_id, unit_id, created_by)
        VALUES (p_property, p_user, v_code.customer_id, v_code.lease_id, v_code.booking_id,
            v_code.unit_id, p_actor)
        RETURNING id INTO v_link;
        INSERT INTO app.telegram_link_code_uses (code_id, telegram_user_id, link_id, created_by)
        VALUES (v_code.id, p_user, v_link, p_actor);
        RETURN jsonb_build_object('result', 'LINKED', 'link_id', v_link, 'name', v_name,
            'unit_number', v_unit, 'guest', v_code.booking_id IS NOT NULL);
    END $$;

    -- The codes the relay may use while the office is away: unused, not expired, stay live.
    CREATE FUNCTION app.telegram_link_codes_offline(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_rows jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT COALESCE(jsonb_agg(jsonb_build_object('code_hash', code.code_hash,
                'unit_id', code.unit_id, 'unit', unit.unit_number,
                'places', app.tenant_unit_places(unit.id),
                'expires_at', extract(epoch FROM code.expires_at)::bigint)
                ORDER BY code.created_at, code.id), '[]'::jsonb)
        INTO v_rows
        FROM app.telegram_link_codes AS code
        JOIN app.units AS unit ON unit.id = code.unit_id
        WHERE code.property_id = p_property AND code.expires_at > clock_timestamp()
          AND NOT EXISTS (SELECT 1 FROM app.telegram_link_code_uses AS used
                          WHERE used.code_id = code.id)
          AND app.tenant_link_stay_live(code.lease_id, code.booking_id, app.gl_today(p_property));
        RETURN v_rows;
    END $$;
"""

# Guests get no Invoices on Telegram (owner, 11 Nov 2026): an Invoice without a Lease goes only
# to the Customer's Lease links, never to a Booking link.
PATCHES = (
    (
        "app.telegram_invoice_people(uuid)",
        "OR (invoice.lease_id IS NULL AND link.customer_id = invoice.customer_id)",
        "OR (invoice.lease_id IS NULL AND link.booking_id IS NULL\n"
        "                   AND link.customer_id = invoice.customer_id)",
    ),
    (
        "app.telegram_invoice_reminders(uuid,uuid)",
        "OR (invoice.lease_id IS NULL AND invoice.customer_id = link.customer_id)",
        "OR (invoice.lease_id IS NULL AND link.booking_id IS NULL\n"
        "                   AND invoice.customer_id = link.customer_id)",
    ),
)

RUNTIME = (
    "app.telegram_bot_name_set(uuid, text, text, uuid)",
    "app.telegram_link_people(uuid, uuid, uuid, uuid)",
    "app.telegram_link_code_create(uuid, uuid, uuid, uuid, uuid)",
    "app.telegram_tenant_link_code(uuid, bigint, text, uuid)",
    "app.telegram_link_codes_offline(uuid, uuid)",
)
INTERNAL = (
    "app.tenant_link_stay_live(uuid, uuid, date)",
    "app.telegram_bot_name(uuid, text)",
    "app.telegram_link_stay(uuid, uuid, uuid, uuid)",
)


def _patch(signature: str, before: str, after: str) -> None:
    definition = (
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
    op.execute(TABLES)
    for table in APPEND_ONLY:
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON app.{table}
                FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
            CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON app.{table}
                FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
            REVOKE ALL ON TABLE app.{table} FROM PUBLIC, prm_runtime, prm_bootstrap;
            """
        )
    op.execute(FUNCTIONS)
    for signature, before, after in PATCHES:
        _patch(signature, before, after)
    for signature in RUNTIME + INTERNAL:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in RUNTIME:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("the Telegram link QR migration is forward-only")
