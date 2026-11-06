# ruff: noqa: E501
"""Telegram bots, step 2d part 2: Contact office and the FAQ (DL-170).

Owner-approved app screens (round 29, 3 Nov 2026 10:45, Office > Telegram) and the tenant
mock-up v15:

* Contact office: a person taps Contact office in a bot and writes a message. The office sees
  the messages from both bots, Waiting (oldest first) and Answered. Each message is answered once:
  Reply (the bot sends the words to the person) or Answered by phone (a note; nothing is sent).
* FAQ: questions and answers in English and Khmer, for the Customer bot, the Tenant bot or both.
  Each change is a new version. A Manager's change waits for the Owner; the Owner's save is
  approved at once. The bots show only the newest approved version.

1. ``telegram_contact_messages`` and ``telegram_contact_answers`` (append-only).
2. ``telegram_faq_questions``, ``telegram_faq_versions`` and ``telegram_faq_approvals``
   (append-only; a question is never deleted, it can be set to "Hidden").
3. Rights (group Administration): Answer Contact office (``telegram.contact``: Owner, Manager and
   Staff) and Edit the FAQ (``telegram.faq``: Owner and Manager). Only the Owner approves.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270524_286"
down_revision: str | None = "20270523_285"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROVENANCE = "v1-1-telegram-contact-faq"
CAPABILITIES = (
    ("telegram.contact", "See and answer Contact office messages from the bots"),
    ("telegram.faq", "Edit the questions and answers the bots show"),
)
PERMISSIONS = (
    (
        "TELEGRAM_CONTACT",
        "Answer Contact office",
        "ឆ្លើយសារទាក់ទងការិយាល័យ",
        ("telegram.contact",),
    ),
    (
        "TELEGRAM_FAQ",
        "Edit the FAQ",
        "កែសំណួរញឹកញាប់",
        ("telegram.faq",),
    ),
)
OWNER = ("telegram.contact", "telegram.faq")
STAFF = ("telegram.contact",)
REASON = "Owner 2026-11-03 round 29: Contact office and FAQ rights"
SEED = "app.seed_default_role_bundles(uuid)"
# Main's daily and weekly rent (migration 20270531_310) now ends the Staff list.
STAFF_BEFORE = "'short_stays.housekeeping']::text[]"


def _text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _array(names: Sequence[str]) -> str:
    return "ARRAY[" + ", ".join(_text(name) for name in names) + "]::text[]"


TABLES = """
    -- 1. Contact office.
    CREATE TABLE app.telegram_contact_messages (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        inbound_event_id uuid NOT NULL UNIQUE
            REFERENCES app.telegram_inbound_events (id) ON DELETE RESTRICT,
        bot_code text NOT NULL REFERENCES app.telegram_bots (code) ON DELETE RESTRICT
            CHECK (bot_code IN ('CUSTOMER', 'TENANT')),
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        chat_id bigint NOT NULL CHECK (chat_id <> 0),
        language text NOT NULL CHECK (language IN ('km', 'en')),
        sender_name text CHECK (length(btrim(sender_name)) BETWEEN 1 AND 120),
        link_id uuid REFERENCES app.tenant_telegram_links (id) ON DELETE RESTRICT,
        message text NOT NULL CHECK (length(btrim(message)) BETWEEN 1 AND 1000),
        received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX telegram_contact_messages_property_idx
        ON app.telegram_contact_messages (property_id, received_at);

    CREATE TABLE app.telegram_contact_answers (
        message_id uuid PRIMARY KEY
            REFERENCES app.telegram_contact_messages (id) ON DELETE RESTRICT,
        how text NOT NULL CHECK (how IN ('TELEGRAM', 'PHONE')),
        answer text NOT NULL CHECK (length(btrim(answer)) BETWEEN 1 AND 600),
        outbox_id uuid UNIQUE REFERENCES app.telegram_outbox (id) ON DELETE RESTRICT,
        answered_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        answered_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT telegram_contact_answers_sent CHECK ((how = 'TELEGRAM') = (outbox_id IS NOT NULL))
    );

    -- 2. The FAQ: a question has numbered versions; the newest approved one is shown.
    CREATE TABLE app.telegram_faq_questions (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        question_number integer NOT NULL CHECK (question_number BETWEEN 1 AND 999),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT telegram_faq_questions_number UNIQUE (property_id, question_number)
    );

    CREATE TABLE app.telegram_faq_versions (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        question_id uuid NOT NULL REFERENCES app.telegram_faq_questions (id) ON DELETE RESTRICT,
        for_bots text NOT NULL CHECK (for_bots IN ('BOTH', 'CUSTOMER', 'TENANT', 'HIDDEN')),
        question_en text NOT NULL CHECK (length(btrim(question_en)) BETWEEN 1 AND 160),
        answer_en text NOT NULL CHECK (length(btrim(answer_en)) BETWEEN 1 AND 800),
        question_km text NOT NULL CHECK (length(btrim(question_km)) BETWEEN 1 AND 160),
        answer_km text NOT NULL CHECK (length(btrim(answer_km)) BETWEEN 1 AND 800),
        proposed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        proposed_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX telegram_faq_versions_question_idx
        ON app.telegram_faq_versions (question_id, proposed_at DESC);

    CREATE TABLE app.telegram_faq_approvals (
        version_id uuid PRIMARY KEY REFERENCES app.telegram_faq_versions (id) ON DELETE RESTRICT,
        question_id uuid NOT NULL REFERENCES app.telegram_faq_questions (id) ON DELETE RESTRICT,
        version_number integer NOT NULL CHECK (version_number > 0),
        approved_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        approved_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT,
        CONSTRAINT telegram_faq_approvals_number UNIQUE (question_id, version_number)
    );
"""

APPEND_ONLY = (
    "telegram_contact_messages",
    "telegram_contact_answers",
    "telegram_faq_questions",
    "telegram_faq_versions",
    "telegram_faq_approvals",
)

FUNCTIONS = """
    CREATE FUNCTION app.telegram_actor_is_owner(p_actor uuid)
    RETURNS boolean LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT EXISTS (
            SELECT 1 FROM app.user_accounts AS account
            JOIN app.user_account_classes AS classification
              ON classification.actor_id = account.actor_id
            WHERE account.actor_id = p_actor AND account.lifecycle_state = 'active'
              AND classification.account_class = 'owner')
    $$;

    CREATE FUNCTION app.telegram_user_name(p_actor uuid)
    RETURNS text LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
        SELECT account.display_name FROM app.user_accounts AS account
        WHERE account.actor_id = p_actor
    $$;

    -- 1. A bot saves a Contact office message (the Telegram jobs' account).
    CREATE FUNCTION app.telegram_contact_add(p_property uuid, p_inbound uuid, p_bot text,
        p_user bigint, p_chat bigint, p_language text, p_name text, p_message text,
        p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_id uuid;
        v_link uuid;
        v_message text := btrim(p_message);
        v_name text := NULLIF(btrim(left(COALESCE(p_name, ''), 120)), '');
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        IF p_bot IS NULL OR p_bot NOT IN ('CUSTOMER', 'TENANT') OR p_user IS NULL OR p_user <= 0
            OR p_chat IS NULL OR p_chat = 0 OR p_language IS NULL
            OR p_language NOT IN ('km', 'en') THEN
            RAISE EXCEPTION 'the message is not valid' USING ERRCODE = '22023';
        END IF;
        IF v_message IS NULL OR length(v_message) NOT BETWEEN 1 AND 1000 THEN
            RAISE EXCEPTION 'Write the message, at most 1000 letters' USING ERRCODE = '22023';
        END IF;
        PERFORM 1 FROM app.telegram_inbound_events AS event
        WHERE event.id = p_inbound AND event.property_id = p_property;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the message does not exist' USING ERRCODE = '22023';
        END IF;
        SELECT message.id INTO v_id FROM app.telegram_contact_messages AS message
        WHERE message.inbound_event_id = p_inbound;
        IF FOUND THEN
            RETURN jsonb_build_object('result', 'REPEATED', 'id', v_id);
        END IF;
        IF p_bot = 'TENANT' THEN
            v_link := (app.tenant_active_link(p_property, p_user)).id;
        END IF;
        INSERT INTO app.telegram_contact_messages (property_id, inbound_event_id, bot_code,
            telegram_user_id, chat_id, language, sender_name, link_id, message, created_by)
        VALUES (p_property, p_inbound, p_bot, p_user, p_chat, p_language, v_name, v_link,
            v_message, p_actor)
        RETURNING id INTO v_id;
        RETURN jsonb_build_object('result', 'SAVED', 'id', v_id);
    END $$;

    -- 2. The Contact office page: Waiting oldest first, Answered in the last 90 days newest first.
    CREATE FUNCTION app.telegram_contact_page(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_waiting jsonb;
        v_answered jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.contact', p_property);
        WITH shown AS (
            SELECT message.id, message.received_at, answer.answered_at, jsonb_build_object(
                'id', message.id, 'bot', message.bot_code,
                'name', COALESCE(customer.legal_name, message.sender_name),
                'unit_number', unit.unit_number,
                'phone', account.phone_e164,
                'language', message.language,
                'message', message.message, 'received_at', message.received_at,
                'answer', CASE WHEN answer.message_id IS NULL THEN NULL ELSE jsonb_build_object(
                    'how', answer.how, 'text', answer.answer, 'at', answer.answered_at,
                    'by', app.telegram_user_name(answer.answered_by)) END) AS body
            FROM app.telegram_contact_messages AS message
            LEFT JOIN app.telegram_contact_answers AS answer ON answer.message_id = message.id
            LEFT JOIN app.tenant_telegram_links AS link ON link.id = message.link_id
            LEFT JOIN app.customers AS customer ON customer.id = link.customer_id
            LEFT JOIN app.units AS unit ON unit.id = link.unit_id
            LEFT JOIN app.telegram_accounts AS account
              ON account.telegram_user_id = message.telegram_user_id
            WHERE message.property_id = p_property
              AND (answer.message_id IS NULL
                   OR answer.answered_at > clock_timestamp() - interval '90 days')
        )
        SELECT COALESCE(jsonb_agg(shown.body ORDER BY shown.received_at, shown.id)
                   FILTER (WHERE shown.answered_at IS NULL), '[]'::jsonb),
               COALESCE(jsonb_agg(shown.body ORDER BY shown.answered_at DESC, shown.id)
                   FILTER (WHERE shown.answered_at IS NOT NULL), '[]'::jsonb)
        INTO v_waiting, v_answered
        FROM shown;
        RETURN jsonb_build_object('waiting', v_waiting, 'answered', v_answered);
    END $$;

    -- 3. Answer a message once: Reply (the bot sends it) or Answered by phone (a note).
    CREATE FUNCTION app.telegram_contact_answer(p_property uuid, p_message uuid, p_how text,
        p_answer text, p_actor uuid)
    RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_message app.telegram_contact_messages%ROWTYPE;
        v_answer text := btrim(p_answer);
        v_outbox uuid;
        v_keyboard text;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.contact', p_property);
        IF p_how IS NULL OR p_how NOT IN ('TELEGRAM', 'PHONE') THEN
            RAISE EXCEPTION 'Choose Reply or Answered by phone' USING ERRCODE = '22023';
        END IF;
        IF v_answer IS NULL OR length(v_answer) NOT BETWEEN 1 AND 600 THEN
            RAISE EXCEPTION 'Write the answer, at most 600 letters' USING ERRCODE = '22023';
        END IF;
        SELECT message.* INTO v_message FROM app.telegram_contact_messages AS message
        WHERE message.id = p_message AND message.property_id = p_property FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the message does not exist' USING ERRCODE = '22023';
        END IF;
        IF EXISTS (SELECT 1 FROM app.telegram_contact_answers AS answer
                   WHERE answer.message_id = p_message) THEN
            RAISE EXCEPTION 'This message was already answered' USING ERRCODE = '55000';
        END IF;
        IF p_how = 'TELEGRAM' THEN
            IF v_message.bot_code = 'TENANT' THEN
                v_keyboard := CASE WHEN (app.tenant_active_link(p_property,
                    v_message.telegram_user_id)).id IS NULL THEN 'tenant.start' ELSE 'tenant.menu' END;
            END IF;
            INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code, language,
                details, keyboard, created_by)
            VALUES (p_property, v_message.bot_code, v_message.chat_id, 'contact.reply',
                v_message.language, jsonb_build_object('text', v_answer), v_keyboard, p_actor)
            RETURNING id INTO v_outbox;
        END IF;
        INSERT INTO app.telegram_contact_answers (message_id, how, answer, outbox_id, answered_by)
        VALUES (p_message, p_how, v_answer, v_outbox, p_actor);
    END $$;

    -- 4. The FAQ page: each question with its approved version and the one waiting for the Owner.
    CREATE FUNCTION app.telegram_faq_page(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_questions jsonb;
        v_edit boolean;
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM app.properties AS property WHERE property.id = p_property) THEN
            RAISE EXCEPTION 'the Property does not exist' USING ERRCODE = '22023';
        END IF;
        v_edit := p_actor IS NOT NULL AND EXISTS (
            SELECT 1 FROM app.actor_capability_grants(p_actor) AS held
            WHERE held.capability_id = 'telegram.faq' AND held.property_id = p_property);
        IF NOT v_edit THEN
            PERFORM app.require_telegram_right(p_actor, 'telegram.contact', p_property);
        END IF;
        SELECT COALESCE(jsonb_agg(jsonb_build_object(
                'id', question.id, 'number', question.question_number,
                'current', current_version.body, 'pending', pending.body)
            ORDER BY question.question_number), '[]'::jsonb)
        INTO v_questions
        FROM app.telegram_faq_questions AS question
        LEFT JOIN LATERAL (
            SELECT jsonb_build_object('version_id', version.id,
                'version_number', approval.version_number, 'for_bots', version.for_bots,
                'question_en', version.question_en, 'answer_en', version.answer_en,
                'question_km', version.question_km, 'answer_km', version.answer_km,
                'approved_by', app.telegram_user_name(approval.approved_by),
                'approved_at', approval.approved_at) AS body
            FROM app.telegram_faq_approvals AS approval
            JOIN app.telegram_faq_versions AS version ON version.id = approval.version_id
            WHERE approval.question_id = question.id
            ORDER BY approval.version_number DESC LIMIT 1
        ) AS current_version ON true
        LEFT JOIN LATERAL (
            SELECT jsonb_build_object('version_id', newest.id, 'for_bots', newest.for_bots,
                'question_en', newest.question_en, 'answer_en', newest.answer_en,
                'question_km', newest.question_km, 'answer_km', newest.answer_km,
                'proposed_by', app.telegram_user_name(newest.proposed_by),
                'proposed_at', newest.proposed_at) AS body
            FROM (SELECT version.* FROM app.telegram_faq_versions AS version
                  WHERE version.question_id = question.id
                  ORDER BY version.proposed_at DESC, version.id DESC LIMIT 1) AS newest
            WHERE NOT EXISTS (SELECT 1 FROM app.telegram_faq_approvals AS approval
                              WHERE approval.version_id = newest.id)
        ) AS pending ON true
        WHERE question.property_id = p_property;
        RETURN jsonb_build_object('questions', v_questions, 'can_edit', v_edit,
            'owner', app.telegram_actor_is_owner(p_actor));
    END $$;

    -- Approve one version: it gets the next version number.
    CREATE FUNCTION app.telegram_faq_approve_version(p_version uuid, p_actor uuid)
    RETURNS integer LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    DECLARE
        v_question uuid;
        v_number integer;
    BEGIN
        SELECT version.question_id INTO v_question FROM app.telegram_faq_versions AS version
        WHERE version.id = p_version;
        SELECT COALESCE(max(approval.version_number), 0) + 1 INTO v_number
        FROM app.telegram_faq_approvals AS approval WHERE approval.question_id = v_question;
        INSERT INTO app.telegram_faq_approvals (version_id, question_id, version_number, approved_by)
        VALUES (p_version, v_question, v_number, p_actor);
        RETURN v_number;
    END $$;

    -- 5. Save a question (new when p_question is NULL). The Owner's save is approved at once.
    CREATE FUNCTION app.telegram_faq_save(p_property uuid, p_question uuid, p_version jsonb,
        p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_question uuid := p_question;
        v_number integer;
        v_version uuid;
        v_owner boolean;
        v_for text := p_version ->> 'for_bots';
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.faq', p_property);
        IF jsonb_typeof(p_version) IS DISTINCT FROM 'object'
            OR v_for IS NULL OR v_for NOT IN ('BOTH', 'CUSTOMER', 'TENANT', 'HIDDEN') THEN
            RAISE EXCEPTION 'Choose which bots show the question' USING ERRCODE = '22023';
        END IF;
        IF length(btrim(COALESCE(p_version ->> 'question_en', ''))) NOT BETWEEN 1 AND 160
            OR length(btrim(COALESCE(p_version ->> 'question_km', ''))) NOT BETWEEN 1 AND 160
            OR length(btrim(COALESCE(p_version ->> 'answer_en', ''))) NOT BETWEEN 1 AND 800
            OR length(btrim(COALESCE(p_version ->> 'answer_km', ''))) NOT BETWEEN 1 AND 800 THEN
            RAISE EXCEPTION 'Write the question (at most 160 letters) and the answer (at most 800) in English and Khmer'
                USING ERRCODE = '22023';
        END IF;
        IF v_question IS NULL THEN
            -- One new question at a time for the Property, so numbers never clash.
            PERFORM 1 FROM app.properties AS property WHERE property.id = p_property FOR UPDATE;
            SELECT COALESCE(max(question.question_number), 0) + 1 INTO v_number
            FROM app.telegram_faq_questions AS question WHERE question.property_id = p_property;
            INSERT INTO app.telegram_faq_questions (property_id, question_number, created_by)
            VALUES (p_property, v_number, p_actor) RETURNING id INTO v_question;
        ELSE
            SELECT question.question_number INTO v_number FROM app.telegram_faq_questions AS question
            WHERE question.id = v_question AND question.property_id = p_property FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'the question does not exist' USING ERRCODE = '22023';
            END IF;
        END IF;
        INSERT INTO app.telegram_faq_versions (question_id, for_bots, question_en, answer_en,
            question_km, answer_km, proposed_by)
        VALUES (v_question, v_for, btrim(p_version ->> 'question_en'),
            btrim(p_version ->> 'answer_en'), btrim(p_version ->> 'question_km'),
            btrim(p_version ->> 'answer_km'), p_actor)
        RETURNING id INTO v_version;
        v_owner := app.telegram_actor_is_owner(p_actor);
        IF v_owner THEN
            PERFORM app.telegram_faq_approve_version(v_version, p_actor);
        END IF;
        RETURN jsonb_build_object('question_id', v_question, 'number', v_number,
            'version_id', v_version, 'approved', v_owner);
    END $$;

    -- 6. The Owner approves the version waiting: only the newest version, not yet approved.
    CREATE FUNCTION app.telegram_faq_approve(p_property uuid, p_version uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_question app.telegram_faq_questions%ROWTYPE;
        v_newest uuid;
        v_number integer;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.faq', p_property);
        IF NOT app.telegram_actor_is_owner(p_actor) THEN
            RAISE EXCEPTION 'Only the Owner approves a FAQ answer' USING ERRCODE = '42501';
        END IF;
        SELECT question.* INTO v_question
        FROM app.telegram_faq_versions AS version
        JOIN app.telegram_faq_questions AS question ON question.id = version.question_id
        WHERE version.id = p_version AND question.property_id = p_property
        FOR UPDATE OF question;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'the version does not exist' USING ERRCODE = '22023';
        END IF;
        SELECT version.id INTO v_newest FROM app.telegram_faq_versions AS version
        WHERE version.question_id = v_question.id
        ORDER BY version.proposed_at DESC, version.id DESC LIMIT 1;
        IF v_newest <> p_version OR EXISTS (SELECT 1 FROM app.telegram_faq_approvals AS approval
                                            WHERE approval.version_id = p_version) THEN
            RAISE EXCEPTION 'This version is no longer the one waiting; reload the page'
                USING ERRCODE = '55000';
        END IF;
        v_number := app.telegram_faq_approve_version(p_version, p_actor);
        RETURN jsonb_build_object('number', v_question.question_number, 'version_number', v_number);
    END $$;

    -- 7. What a bot shows: the newest approved version of each question for this bot.
    CREATE FUNCTION app.telegram_faq_for_bot(p_property uuid, p_bot text, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE v_list jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        IF p_bot IS NULL OR p_bot NOT IN ('CUSTOMER', 'TENANT') THEN
            RAISE EXCEPTION 'the bot is not valid' USING ERRCODE = '22023';
        END IF;
        SELECT COALESCE(jsonb_agg(jsonb_build_object('number', question.question_number,
                'question_en', shown.question_en, 'answer_en', shown.answer_en,
                'question_km', shown.question_km, 'answer_km', shown.answer_km)
            ORDER BY question.question_number), '[]'::jsonb)
        INTO v_list
        FROM app.telegram_faq_questions AS question
        JOIN LATERAL (
            SELECT version.* FROM app.telegram_faq_approvals AS approval
            JOIN app.telegram_faq_versions AS version ON version.id = approval.version_id
            WHERE approval.question_id = question.id
            ORDER BY approval.version_number DESC LIMIT 1
        ) AS shown ON true
        WHERE question.property_id = p_property AND shown.for_bots IN ('BOTH', p_bot);
        RETURN v_list;
    END $$;
"""

APP_FUNCTIONS = (
    "app.telegram_contact_page(uuid, uuid)",
    "app.telegram_contact_answer(uuid, uuid, text, text, uuid)",
    "app.telegram_faq_page(uuid, uuid)",
    "app.telegram_faq_save(uuid, uuid, jsonb, uuid)",
    "app.telegram_faq_approve(uuid, uuid, uuid)",
    "app.telegram_contact_add(uuid, uuid, text, bigint, bigint, text, text, text, uuid)",
    "app.telegram_faq_for_bot(uuid, text, uuid)",
)
INNER_FUNCTIONS = (
    "app.telegram_actor_is_owner(uuid)",
    "app.telegram_user_name(uuid)",
    "app.telegram_faq_approve_version(uuid, uuid)",
)


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
    for signature in INNER_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in APP_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")

    # New Properties: Staff answer Contact office; the Owner and Manager get every right.
    _patch(
        SEED,
        STAFF_BEFORE,
        "'short_stays.housekeeping', " + ", ".join(_text(name) for name in STAFF) + "]::text[]",
    )
    every = _array(OWNER)
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
    raise RuntimeError("the Telegram Contact office and FAQ migration is forward-only")
