# ruff: noqa: E501
"""Telegram bots, step 3b: working the Visit requests (DL-172).

Owner rules of 28 Oct 2026 (CRM users and flows, answers of 17:54 and 18:52) and DESIGN round 10:

* The list is oldest first (first come, first served). "Take" makes a request yours; a Manager
  can give it to another person. Late means more than 2 working hours with nobody taking it;
  working time is Monday to Saturday, 07:00 to 17:00.
* "Record a call" saves Answered or No answer. After no answer on 3 different days, the request
  can be closed as "Could not reach".
* Book a visit (date, time and who shows it) and move it. A Telegram customer gets the
  confirmation from the bot, and at 08:00 the day before, a reminder. Phone, WhatsApp (and, until
  the app sends email, email) customers are in "Send by hand today" with the words to send;
  staff tap Mark sent.
* Visited or No-show after the visit; Close as Not interested with a reason from the fixed list
  (Other needs a note) or as Customer cancelled; Reopen with a note. A Manager can mark Spam.
* A person who asks again after their request closed starts a new request (it no longer joins).

1. ``visit_request_events`` (append-only): every step of a request, with who did it.
2. Rights (group Leasing): Work Visit requests (``visit_requests.work``: Owner, Manager and Staff)
   and Manage Visit requests (``visit_requests.manage``: Give to another person, Spam; Owner and
   Manager).

Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270526_288"
down_revision: str | None = "20270525_287"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROVENANCE = "v1-1-telegram-visit-request-work"
CAPABILITIES = (
    ("visit_requests.work", "Take, call, book a visit for and close Visit requests"),
    ("visit_requests.manage", "Give Visit requests to another person and mark them Spam"),
)
PERMISSIONS = (
    ("VISIT_REQUESTS_WORK", "Work Visit requests", "ធ្វើការលើសំណើមកមើលបន្ទប់", "visit_requests.work"),
    ("VISIT_REQUESTS_MANAGE", "Manage Visit requests", "គ្រប់គ្រងសំណើមកមើលបន្ទប់", "visit_requests.manage"),
)
EVERY = ("visit_requests.work", "visit_requests.manage")
STAFF = ("visit_requests.work",)
REASON = "Owner 2026-10-28: Take, calls, visits and Close for Visit requests; a Manager gives and marks Spam"
SEED = "app.seed_default_role_bundles(uuid)"
STAFF_BEFORE = "'telegram.contact', 'visit_requests.read']::text[]"
STAFF_AFTER = "'telegram.contact', 'visit_requests.read', 'visit_requests.work']::text[]"
ADD = "app.telegram_visit_request_add(uuid, uuid, bigint, bigint, text, jsonb, uuid)"
ADD_BEFORE = "AND (main.telegram_user_id = p_user OR main.phone_e164 = v_phone)"
ADD_AFTER = ADD_BEFORE + "\n          AND app.visit_request_open(main.id)"
PAGE = "app.visit_requests_page(uuid, uuid)"

TABLES = """
    CREATE TABLE app.visit_request_events (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        request_id uuid NOT NULL REFERENCES app.visit_requests (id) ON DELETE RESTRICT,
        kind text NOT NULL CHECK (kind IN ('TAKEN', 'GIVEN', 'CALL', 'VISIT_BOOKED', 'VISITED',
            'NO_SHOW', 'CLOSED', 'REOPENED', 'SPAM', 'SENT_BY_HAND', 'REMINDER_DUE')),
        staff_id uuid REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        answered boolean,
        visit_at timestamptz,
        reason text CHECK (reason IN ('PRICE', 'TYPE_NOT_FREE', 'LOCATION', 'FOUND_OTHER',
            'MOVE_IN_FAR', 'NO_REACH', 'OTHER', 'CANCELLED')),
        what text CHECK (what IN ('CONFIRMATION', 'REMINDER')),
        note text CHECK (length(note) BETWEEN 1 AND 300 AND note = btrim(note)),
        outbox_id uuid UNIQUE REFERENCES app.telegram_outbox (id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT visit_request_events_staff CHECK (
            (kind IN ('TAKEN', 'GIVEN', 'VISIT_BOOKED')) = (staff_id IS NOT NULL)),
        CONSTRAINT visit_request_events_call CHECK ((kind = 'CALL') = (answered IS NOT NULL)),
        CONSTRAINT visit_request_events_visit CHECK ((kind = 'VISIT_BOOKED') = (visit_at IS NOT NULL)),
        CONSTRAINT visit_request_events_reason CHECK ((kind = 'CLOSED') = (reason IS NOT NULL)),
        CONSTRAINT visit_request_events_other CHECK (reason IS DISTINCT FROM 'OTHER' OR note IS NOT NULL),
        CONSTRAINT visit_request_events_what CHECK (
            (kind IN ('SENT_BY_HAND', 'REMINDER_DUE')) = (what IS NOT NULL)),
        CONSTRAINT visit_request_events_note CHECK (
            kind NOT IN ('REOPENED', 'SPAM') OR note IS NOT NULL)
    );
    CREATE INDEX visit_request_events_request_idx
        ON app.visit_request_events (request_id, created_at);
    CREATE TRIGGER visit_request_events_append_only BEFORE UPDATE OR DELETE
        ON app.visit_request_events FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER visit_request_events_no_truncate BEFORE TRUNCATE
        ON app.visit_request_events FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    REVOKE ALL ON TABLE app.visit_request_events FROM PUBLIC, prm_runtime, prm_bootstrap;
"""

FUNCTIONS = """
    -- Minutes of working time (Monday to Saturday, 07:00 to 17:00, the Property's time zone)
    -- between two moments; counting stops after 60 days.
    CREATE FUNCTION app.visit_working_minutes(p_from timestamptz, p_to timestamptz, p_zone text)
    RETURNS integer LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
    DECLARE
        v_from timestamp := timezone(p_zone, p_from);
        v_to timestamp := timezone(p_zone, p_to);
        v_day date;
        v_start timestamp;
        v_end timestamp;
        v_total numeric := 0;
    BEGIN
        IF v_to <= v_from THEN
            RETURN 0;
        END IF;
        v_day := v_from::date;
        WHILE v_day <= v_to::date AND v_day <= v_from::date + 60 LOOP
            IF extract(isodow FROM v_day) <> 7 THEN
                v_start := greatest(v_day + time '07:00', v_from);
                v_end := least(v_day + time '17:00', v_to);
                IF v_end > v_start THEN
                    v_total := v_total + extract(epoch FROM v_end - v_start) / 60;
                END IF;
            END IF;
            v_day := v_day + 1;
        END LOOP;
        RETURN floor(v_total)::integer;
    END $$;

    -- Where a request stands now, from its steps in order.
    CREATE FUNCTION app.visit_request_state(p_request uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
    DECLARE
        v_event app.visit_request_events%ROWTYPE;
        v_status text := 'NEW';
        v_answered boolean := false;
        v_staff uuid;
        v_visit_at timestamptz;
        v_visit_staff uuid;
        v_booking uuid;
        v_reason text;
        v_note text;
        v_zone text;
        v_no_answer integer;
    BEGIN
        FOR v_event IN SELECT event.* FROM app.visit_request_events AS event
            WHERE event.request_id = p_request ORDER BY event.created_at, event.id
        LOOP
            CASE v_event.kind
                WHEN 'TAKEN', 'GIVEN' THEN v_staff := v_event.staff_id;
                WHEN 'CALL' THEN
                    IF v_event.answered THEN
                        v_answered := true;
                        IF v_status = 'NEW' THEN v_status := 'CONTACTED'; END IF;
                    END IF;
                WHEN 'VISIT_BOOKED' THEN
                    v_status := 'VISIT_BOOKED';
                    v_visit_at := v_event.visit_at;
                    v_visit_staff := v_event.staff_id;
                    v_booking := v_event.id;
                WHEN 'VISITED' THEN v_status := 'VISITED';
                WHEN 'NO_SHOW' THEN v_status := 'NO_SHOW';
                WHEN 'CLOSED' THEN
                    v_status := 'CLOSED';
                    v_reason := v_event.reason;
                    v_note := v_event.note;
                WHEN 'SPAM' THEN
                    v_status := 'SPAM';
                    v_note := v_event.note;
                WHEN 'REOPENED' THEN
                    v_status := CASE WHEN v_answered THEN 'CONTACTED' ELSE 'NEW' END;
                    v_reason := NULL;
                    v_note := NULL;
                    v_visit_at := NULL;
                    v_visit_staff := NULL;
                    v_booking := NULL;
                ELSE NULL;
            END CASE;
        END LOOP;
        SELECT property.timezone_name INTO v_zone
        FROM app.visit_requests AS request
        JOIN app.properties AS property ON property.id = request.property_id
        WHERE request.id = p_request;
        SELECT count(DISTINCT timezone(v_zone, event.created_at)::date)::integer INTO v_no_answer
        FROM app.visit_request_events AS event
        WHERE event.request_id = p_request AND event.kind = 'CALL' AND NOT event.answered;
        RETURN jsonb_build_object('status', v_status, 'staff_id', v_staff,
            'visit_at', v_visit_at, 'visit_staff_id', v_visit_staff, 'booking_id', v_booking,
            'reason', v_reason, 'note', v_note, 'no_answer_days', v_no_answer,
            'answered', v_answered);
    END $$;

    CREATE FUNCTION app.visit_request_open(p_request uuid)
    RETURNS boolean LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT app.visit_request_state(p_request) ->> 'status' NOT IN ('CLOSED', 'SPAM')
    $$;

    CREATE FUNCTION app.visit_request_holds(p_actor uuid, p_capability text, p_property uuid)
    RETURNS boolean LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT EXISTS (SELECT 1 FROM app.actor_capability_grants(p_actor) AS held
                       WHERE held.capability_id = p_capability AND held.property_id = p_property)
    $$;

    -- The words of a visit in the customer's language: "Saturday 31/10/2026" and "09:00".
    CREATE FUNCTION app.visit_day_words(p_at timestamptz, p_zone text, p_language text)
    RETURNS jsonb LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT jsonb_build_object(
            'day', (CASE WHEN p_language = 'km'
                THEN (ARRAY['ថ្ងៃច័ន្ទ', 'ថ្ងៃអង្គារ', 'ថ្ងៃពុធ', 'ថ្ងៃព្រហស្បតិ៍', 'ថ្ងៃសុក្រ',
                            'ថ្ងៃសៅរ៍', 'ថ្ងៃអាទិត្យ'])
                ELSE (ARRAY['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday',
                            'Sunday']) END)[extract(isodow FROM timezone(p_zone, p_at))::integer]
                || ' ' || to_char(timezone(p_zone, p_at), 'DD/MM/YYYY'),
            'time', to_char(timezone(p_zone, p_at), 'HH24:MI'))
    $$;

    -- 1. One step on a request from the app.
    CREATE FUNCTION app.visit_request_act(p_property uuid, p_request uuid, p_action text,
        p_body jsonb, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_request app.visit_requests%ROWTYPE;
        v_state jsonb;
        v_status text;
        v_holder uuid;
        v_manager boolean;
        v_zone text;
        v_address text;
        v_note text := NULLIF(btrim(p_body ->> 'note'), '');
        v_staff uuid;
        v_at timestamptz;
        v_local timestamp;
        v_reason text;
        v_what text;
        v_outbox uuid;
        v_words jsonb;
        v_event uuid := gen_random_uuid();
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'visit_requests.work', p_property);
        IF jsonb_typeof(p_body) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'the step is not valid' USING ERRCODE = '22023';
        END IF;
        IF length(v_note) > 300 THEN
            RAISE EXCEPTION 'The note is at most 300 letters' USING ERRCODE = '22023';
        END IF;
        SELECT request.* INTO v_request FROM app.visit_requests AS request
        WHERE request.id = p_request AND request.property_id = p_property
          AND request.joined_to IS NULL
        FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the request does not exist' USING ERRCODE = '22023';
        END IF;
        SELECT property.timezone_name, COALESCE(property.address_text, property.name)
        INTO v_zone, v_address FROM app.properties AS property WHERE property.id = p_property;
        v_state := app.visit_request_state(p_request);
        v_status := v_state ->> 'status';
        v_holder := (v_state ->> 'staff_id')::uuid;
        v_manager := app.visit_request_holds(p_actor, 'visit_requests.manage', p_property);

        IF p_action = 'TAKE' THEN
            IF v_status IN ('CLOSED', 'SPAM') THEN
                RAISE EXCEPTION 'This request is closed' USING ERRCODE = '55000';
            END IF;
            IF v_holder IS NOT NULL THEN
                RAISE EXCEPTION 'Someone already took this request' USING ERRCODE = '55000';
            END IF;
            INSERT INTO app.visit_request_events (id, request_id, kind, staff_id, created_by)
            VALUES (v_event, p_request, 'TAKEN', p_actor, p_actor);
            RETURN jsonb_build_object('event_id', v_event);
        END IF;
        IF p_action = 'GIVE' THEN
            IF NOT v_manager THEN
                RAISE EXCEPTION 'Only a Manager gives a request to another person'
                    USING ERRCODE = '42501';
            END IF;
            v_staff := (p_body ->> 'staff_id')::uuid;
            IF v_staff IS NULL OR NOT app.visit_request_holds(v_staff, 'visit_requests.work', p_property) THEN
                RAISE EXCEPTION 'Choose a person who works Visit requests' USING ERRCODE = '22023';
            END IF;
            IF v_status IN ('CLOSED', 'SPAM') THEN
                RAISE EXCEPTION 'This request is closed' USING ERRCODE = '55000';
            END IF;
            INSERT INTO app.visit_request_events (id, request_id, kind, staff_id, note, created_by)
            VALUES (v_event, p_request, 'GIVEN', v_staff, v_note, p_actor);
            RETURN jsonb_build_object('event_id', v_event);
        END IF;
        IF p_action = 'SPAM' THEN
            IF NOT v_manager THEN
                RAISE EXCEPTION 'Only a Manager marks Spam' USING ERRCODE = '42501';
            END IF;
            IF v_status IN ('CLOSED', 'SPAM', 'VISIT_BOOKED') THEN
                RAISE EXCEPTION 'This request cannot be marked Spam now' USING ERRCODE = '55000';
            END IF;
            IF v_note IS NULL THEN
                RAISE EXCEPTION 'Write why' USING ERRCODE = '22023';
            END IF;
            INSERT INTO app.visit_request_events (id, request_id, kind, note, created_by)
            VALUES (v_event, p_request, 'SPAM', v_note, p_actor);
            RETURN jsonb_build_object('event_id', v_event);
        END IF;

        IF p_action = 'REOPEN' THEN
            IF v_status NOT IN ('CLOSED', 'SPAM') THEN
                RAISE EXCEPTION 'This request is open' USING ERRCODE = '55000';
            END IF;
            IF NOT v_manager AND (v_status = 'SPAM' OR v_holder IS DISTINCT FROM p_actor) THEN
                RAISE EXCEPTION 'Only the person who had this request or a Manager reopens it'
                    USING ERRCODE = '42501';
            END IF;
            IF v_note IS NULL THEN
                RAISE EXCEPTION 'Write why' USING ERRCODE = '22023';
            END IF;
            INSERT INTO app.visit_request_events (id, request_id, kind, note, created_by)
            VALUES (v_event, p_request, 'REOPENED', v_note, p_actor);
            RETURN jsonb_build_object('event_id', v_event);
        END IF;

        -- Every other step: the person who has the request, or a Manager.
        IF v_holder IS NULL THEN
            RAISE EXCEPTION 'Take the request first' USING ERRCODE = '55000';
        END IF;
        IF v_holder <> p_actor AND NOT v_manager THEN
            RAISE EXCEPTION 'Only the person who has this request or a Manager can do this'
                USING ERRCODE = '42501';
        END IF;
        IF v_status IN ('CLOSED', 'SPAM') THEN
            RAISE EXCEPTION 'This request is closed' USING ERRCODE = '55000';
        END IF;

        IF p_action = 'CALL' THEN
            IF jsonb_typeof(p_body -> 'answered') IS DISTINCT FROM 'boolean' THEN
                RAISE EXCEPTION 'Choose Answered or No answer' USING ERRCODE = '22023';
            END IF;
            INSERT INTO app.visit_request_events (id, request_id, kind, answered, note, created_by)
            VALUES (v_event, p_request, 'CALL', (p_body ->> 'answered')::boolean, v_note,
                p_actor);
        ELSIF p_action = 'BOOK' THEN
            IF v_status NOT IN ('CONTACTED', 'VISIT_BOOKED', 'NO_SHOW', 'VISITED') THEN
                RAISE EXCEPTION 'Talk to the customer first' USING ERRCODE = '55000';
            END IF;
            BEGIN
                v_local := (p_body ->> 'visit_at')::timestamp;
            EXCEPTION WHEN data_exception THEN
                RAISE EXCEPTION 'Choose the visit day and time' USING ERRCODE = '22023';
            END;
            v_at := v_local AT TIME ZONE v_zone;
            IF v_local IS NULL OR v_at < clock_timestamp()
                OR extract(isodow FROM v_local) = 7
                OR v_local::time NOT BETWEEN time '07:00' AND time '17:00' THEN
                RAISE EXCEPTION 'Choose a time from now, Monday to Saturday, 07:00 to 17:00'
                    USING ERRCODE = '22023';
            END IF;
            v_staff := COALESCE((p_body ->> 'staff_id')::uuid, p_actor);
            IF NOT app.visit_request_holds(v_staff, 'visit_requests.work', p_property) THEN
                RAISE EXCEPTION 'Choose a person who works Visit requests' USING ERRCODE = '22023';
            END IF;
            IF v_request.contact_by = 'TELEGRAM' THEN
                v_words := app.visit_day_words(v_at, v_zone, v_request.language);
                INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code,
                    language, details, keyboard, created_by)
                VALUES (p_property, 'CUSTOMER', v_request.chat_id,
                    CASE WHEN v_status = 'VISIT_BOOKED' THEN 'customer.visit_moved'
                         ELSE 'customer.visit_booked' END,
                    v_request.language,
                    v_words || jsonb_build_object('staff',
                        COALESCE(app.telegram_user_name(v_staff), ''),
                        'address', left(v_address, 300)),
                    'customer.menu', p_actor)
                RETURNING id INTO v_outbox;
            END IF;
            INSERT INTO app.visit_request_events (id, request_id, kind, staff_id, visit_at, note,
                outbox_id, created_by)
            VALUES (v_event, p_request, 'VISIT_BOOKED', v_staff, v_at, v_note, v_outbox, p_actor);
        ELSIF p_action IN ('VISITED', 'NO_SHOW') THEN
            IF v_status <> 'VISIT_BOOKED' OR timezone(v_zone, (v_state ->> 'visit_at')::timestamptz)::date
                > timezone(v_zone, clock_timestamp())::date THEN
                RAISE EXCEPTION 'Only on or after the visit day' USING ERRCODE = '55000';
            END IF;
            INSERT INTO app.visit_request_events (id, request_id, kind, note, created_by)
            VALUES (v_event, p_request, p_action, v_note, p_actor);
        ELSIF p_action = 'CLOSE' THEN
            v_reason := p_body ->> 'reason';
            IF v_reason IS NULL OR v_reason NOT IN ('PRICE', 'TYPE_NOT_FREE', 'LOCATION',
                    'FOUND_OTHER', 'MOVE_IN_FAR', 'NO_REACH', 'OTHER', 'CANCELLED') THEN
                RAISE EXCEPTION 'Choose why the request closes' USING ERRCODE = '22023';
            END IF;
            IF v_reason = 'OTHER' AND v_note IS NULL THEN
                RAISE EXCEPTION 'Write why' USING ERRCODE = '22023';
            END IF;
            IF v_reason = 'NO_REACH' AND (v_state ->> 'no_answer_days')::integer < 3 THEN
                RAISE EXCEPTION 'Could not reach needs no answer on 3 days' USING ERRCODE = '55000';
            END IF;
            INSERT INTO app.visit_request_events (id, request_id, kind, reason, note, created_by)
            VALUES (v_event, p_request, 'CLOSED', v_reason, v_note, p_actor);
        ELSIF p_action = 'SENT' THEN
            v_what := p_body ->> 'what';
            IF v_what IS NULL OR v_what NOT IN ('CONFIRMATION', 'REMINDER')
                OR v_status <> 'VISIT_BOOKED' THEN
                RAISE EXCEPTION 'Nothing to send by hand' USING ERRCODE = '55000';
            END IF;
            INSERT INTO app.visit_request_events (id, request_id, kind, what, created_by)
            VALUES (v_event, p_request, 'SENT_BY_HAND', v_what, p_actor);
        ELSE
            RAISE EXCEPTION 'the step is not valid' USING ERRCODE = '22023';
        END IF;
        RETURN jsonb_build_object('event_id', v_event, 'outbox_id', v_outbox);
    END $$;

    -- 2. The 08:00 reminder the day before a visit (the Telegram jobs, every minute).
    CREATE FUNCTION app.visit_request_reminders(p_property uuid, p_actor uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_zone text;
        v_now timestamp;
        v_due record;
        v_outbox uuid;
        v_count integer := 0;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT property.timezone_name INTO v_zone FROM app.properties AS property
        WHERE property.id = p_property;
        v_now := timezone(v_zone, clock_timestamp());
        IF v_now::time < time '08:00' THEN
            RETURN 0;
        END IF;
        FOR v_due IN
            SELECT request.*, state.state
            FROM app.visit_requests AS request
            CROSS JOIN LATERAL (SELECT app.visit_request_state(request.id) AS state) AS state
            WHERE request.property_id = p_property AND request.joined_to IS NULL
              AND EXISTS (SELECT 1 FROM app.visit_request_events AS event
                          WHERE event.request_id = request.id AND event.kind = 'VISIT_BOOKED')
        LOOP
            CONTINUE WHEN v_due.state ->> 'status' <> 'VISIT_BOOKED'
                OR timezone(v_zone, (v_due.state ->> 'visit_at')::timestamptz)::date
                    <> v_now::date + 1;
            CONTINUE WHEN EXISTS (
                SELECT 1 FROM app.visit_request_events AS reminder
                JOIN app.visit_request_events AS booking
                  ON booking.id = (v_due.state ->> 'booking_id')::uuid
                WHERE reminder.request_id = v_due.id AND reminder.kind = 'REMINDER_DUE'
                  AND reminder.created_at > booking.created_at);
            v_outbox := NULL;
            IF v_due.contact_by = 'TELEGRAM' THEN
                INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code,
                    language, details, keyboard, created_by)
                VALUES (p_property, 'CUSTOMER', v_due.chat_id, 'customer.visit_reminder',
                    v_due.language,
                    app.visit_day_words((v_due.state ->> 'visit_at')::timestamptz, v_zone,
                        v_due.language),
                    'customer.menu', p_actor)
                RETURNING id INTO v_outbox;
            END IF;
            INSERT INTO app.visit_request_events (request_id, kind, what, outbox_id, created_by)
            VALUES (v_due.id, 'REMINDER_DUE', 'REMINDER', v_outbox, p_actor);
            v_count := v_count + 1;
        END LOOP;
        RETURN v_count;
    END $$;

    -- 3. One request with its whole history.
    CREATE FUNCTION app.visit_request_detail(p_property uuid, p_request uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_request app.visit_requests%ROWTYPE;
        v_history jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'visit_requests.read', p_property);
        SELECT request.* INTO v_request FROM app.visit_requests AS request
        WHERE request.id = p_request AND request.property_id = p_property
          AND request.joined_to IS NULL;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the request does not exist' USING ERRCODE = '22023';
        END IF;
        SELECT COALESCE(jsonb_agg(jsonb_build_object('at', event.created_at, 'kind', event.kind,
                'by', app.telegram_user_name(event.created_by),
                'staff', app.telegram_user_name(event.staff_id), 'answered', event.answered,
                'visit_at', event.visit_at, 'reason', event.reason, 'what', event.what,
                'note', event.note, 'sent_by_bot', event.outbox_id IS NOT NULL)
            ORDER BY event.created_at, event.id), '[]'::jsonb)
        INTO v_history
        FROM app.visit_request_events AS event WHERE event.request_id = p_request;
        RETURN app.visit_request_card(v_request, p_actor)
            || jsonb_build_object('history', v_history);
    END $$;
"""

CARD = """
    -- One request as the list shows it: the facts, where it stands, Late and what to send.
    CREATE FUNCTION app.visit_request_card(p_request app.visit_requests, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
    DECLARE
        v_state jsonb := app.visit_request_state(p_request.id);
        v_zone text;
        v_waiting integer;
        v_status text := v_state ->> 'status';
        v_booking app.visit_request_events%ROWTYPE;
        v_send jsonb := '[]'::jsonb;
        v_hand boolean := p_request.contact_by <> 'TELEGRAM';
    BEGIN
        SELECT property.timezone_name INTO v_zone FROM app.properties AS property
        WHERE property.id = p_request.property_id;
        v_waiting := app.visit_working_minutes(p_request.received_at, clock_timestamp(), v_zone);
        IF v_status = 'VISIT_BOOKED' AND v_hand THEN
            SELECT event.* INTO v_booking FROM app.visit_request_events AS event
            WHERE event.id = (v_state ->> 'booking_id')::uuid;
            IF NOT EXISTS (SELECT 1 FROM app.visit_request_events AS sent
                    WHERE sent.request_id = p_request.id AND sent.kind = 'SENT_BY_HAND'
                      AND sent.what = 'CONFIRMATION' AND sent.created_at > v_booking.created_at) THEN
                v_send := v_send || jsonb_build_array('CONFIRMATION');
            END IF;
            IF EXISTS (SELECT 1 FROM app.visit_request_events AS due
                    WHERE due.request_id = p_request.id AND due.kind = 'REMINDER_DUE'
                      AND due.created_at > v_booking.created_at)
               AND NOT EXISTS (SELECT 1 FROM app.visit_request_events AS sent
                    WHERE sent.request_id = p_request.id AND sent.kind = 'SENT_BY_HAND'
                      AND sent.what = 'REMINDER' AND sent.created_at > v_booking.created_at) THEN
                v_send := v_send || jsonb_build_array('REMINDER');
            END IF;
        END IF;
        RETURN app.visit_request_row(p_request) || jsonb_build_object(
            'status', v_status,
            'staff_id', v_state -> 'staff_id',
            'staff', app.telegram_user_name((v_state ->> 'staff_id')::uuid),
            'mine', (v_state ->> 'staff_id')::uuid = p_actor,
            'waiting_minutes', v_waiting,
            'late', v_status = 'NEW' AND v_state ->> 'staff_id' IS NULL AND v_waiting > 120,
            'no_answer_days', v_state -> 'no_answer_days',
            'calls', (SELECT count(*) FROM app.visit_request_events AS event
                      WHERE event.request_id = p_request.id AND event.kind = 'CALL'),
            'visit_at', v_state -> 'visit_at',
            'visit_local', to_char(timezone(v_zone, (v_state ->> 'visit_at')::timestamptz),
                'YYYY-MM-DD"T"HH24:MI'),
            'visit_staff', app.telegram_user_name((v_state ->> 'visit_staff_id')::uuid),
            'reason', v_state -> 'reason', 'close_note', v_state -> 'note',
            'to_send', v_send,
            'joined', (SELECT COALESCE(jsonb_agg(app.visit_request_row(kid)
                           ORDER BY kid.received_at, kid.id), '[]'::jsonb)
                       FROM app.visit_requests AS kid WHERE kid.joined_to = p_request.id));
    END $$;

    -- The list (replaces step 3a's): oldest first; the people who work requests; who may manage.
    CREATE OR REPLACE FUNCTION app.visit_requests_page(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_list jsonb;
        v_workers jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'visit_requests.read', p_property);
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
            'can_manage', app.visit_request_holds(p_actor, 'visit_requests.manage', p_property));
    END $$;
"""

APP_FUNCTIONS = (
    "app.visit_request_act(uuid, uuid, text, jsonb, uuid)",
    "app.visit_request_reminders(uuid, uuid)",
    "app.visit_request_detail(uuid, uuid, uuid)",
)
INNER_FUNCTIONS = (
    "app.visit_working_minutes(timestamptz, timestamptz, text)",
    "app.visit_request_state(uuid)",
    "app.visit_request_open(uuid)",
    "app.visit_request_holds(uuid, text, uuid)",
    "app.visit_day_words(timestamptz, text, text)",
    "app.visit_request_card(app.visit_requests, uuid)",
)


def _text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _array(names: Sequence[str]) -> str:
    return "ARRAY[" + ", ".join(_text(name) for name in names) + "]::text[]"


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
    for name, description in CAPABILITIES:
        op.execute(
            "INSERT INTO app.capabilities (capability_id, family, description, grant_path, "
            f"provenance) VALUES ({_text(name)}, 'visit_requests', {_text(description)}, "
            f"'bundle', '{PROVENANCE}')"
        )
    for code, en, kh, name in PERMISSIONS:
        op.execute(
            "INSERT INTO app.permissions (permission_code, group_code, sort_order, name_en, "
            f"name_kh, provenance) VALUES ({_text(code)}, 'LEASING', "
            "(SELECT max(sort_order) FROM app.permissions) + 1, "
            f"{_text(en)}, {_text(kh)}, '{PROVENANCE}')"
        )
        op.execute(
            "INSERT INTO app.permission_capabilities (permission_code, capability_id, provenance) "
            f"VALUES ({_text(code)}, {_text(name)}, '{PROVENANCE}')"
        )
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    op.execute(CARD)
    for signature in INNER_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in APP_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")
    _patch(ADD, ADD_BEFORE, ADD_AFTER)

    _patch(SEED, STAFF_BEFORE, STAFF_AFTER)
    every = _array(EVERY)
    staff = _array(STAFF)
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
                SELECT seeded.property_id, bundle.role_bundle_id, bundle.version,
                    CASE bundle.role_bundle_id
                        WHEN seeded.staff_bundle_id THEN {staff}
                        ELSE {every}
                    END AS added
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
                SELECT v_default.role_bundle_id, v_default.version + 1, added
                FROM pg_catalog.unnest(v_default.added) AS added;
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
                            'capabilities_added', pg_catalog.to_jsonb(v_default.added)),
                        pg_catalog.gen_random_uuid(), 'ADMINISTRATIVE', 'SUCCEEDED'
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    raise RuntimeError("the Visit requests work migration is forward-only")
