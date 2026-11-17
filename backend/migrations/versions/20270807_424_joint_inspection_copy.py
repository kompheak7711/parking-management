# ruff: noqa: E501
"""Joint Inspection (DL-243 answer 6, DL-244): the tenant gets a PDF copy by the Tenant bot.

Owner (16 Nov 2026, "Yes to all advice"): when a Joint Inspection is Done, the tenant gets its
PDF copy in the Tenant bot (CHETANA Residence support), and staff can print the same PDF.

1. ``app.telegram_joint_inspection_notices`` keeps what was queued: one row per Done Joint
   Inspection and Telegram account, with its outbox message. It is never changed, and it stops a
   second copy.
2. The pull job (about once a minute) runs ``app.telegram_joint_inspections_queue``: each Joint
   Inspection that became Done in the last 3 days goes to each live link of its Lease that has
   not had it, in the language the person chose. A link to the Lease made later than a day after
   the inspection gets nothing (the tenant can ask the office). A Replaced inspection that is
   still new is sent too: its replacement follows as its own copy.
3. The send job reads the inspection for the PDF with
   ``app.telegram_joint_inspection_for_outbox`` (``telegram.operate``), the same data the app
   shows, with where the two signatures are kept.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270807_424"
down_revision: str | None = "20270805_423"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Joint Inspections Done within this many days are sent.
RECENT_DAYS = 3
# A person who links up to this many days after the inspection still gets it.
LINK_DAYS_AFTER = 1

TABLES = """
    CREATE TABLE app.telegram_joint_inspection_notices (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        inspection_id uuid NOT NULL REFERENCES app.joint_inspections (id) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        outbox_id uuid NOT NULL UNIQUE REFERENCES app.telegram_outbox (id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        CONSTRAINT telegram_joint_inspection_notices_once UNIQUE (inspection_id, telegram_user_id)
    );
    CREATE INDEX telegram_joint_inspection_notices_property_idx
        ON app.telegram_joint_inspection_notices (property_id, created_at DESC);

    CREATE TRIGGER telegram_joint_inspection_notices_append_only BEFORE UPDATE OR DELETE
        ON app.telegram_joint_inspection_notices FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER telegram_joint_inspection_notices_no_truncate BEFORE TRUNCATE
        ON app.telegram_joint_inspection_notices FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    REVOKE ALL ON app.telegram_joint_inspection_notices FROM PUBLIC;
"""

FUNCTIONS = f"""
    -- Who gets the copy: each Telegram account with a link to the inspection's Lease that has
    -- not ended, with the language last chosen in the Tenant bot.
    CREATE FUNCTION app.telegram_joint_inspection_people(p_inspection uuid)
    RETURNS TABLE (property_id uuid, telegram_user_id bigint, language text, linked_at timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        SELECT person.property_id, person.telegram_user_id,
            COALESCE((SELECT choice.language FROM app.telegram_language_choices AS choice
                      WHERE choice.bot_code = 'TENANT'
                        AND choice.telegram_user_id = person.telegram_user_id
                      ORDER BY choice.chosen_at DESC LIMIT 1), 'km'),
            person.linked_at
        FROM (
            SELECT DISTINCT ON (link.telegram_user_id) link.property_id, link.telegram_user_id,
                link.linked_at
            FROM app.joint_inspections AS inspection
            JOIN app.tenant_telegram_links AS link
              ON link.lease_id = inspection.lease_id AND link.property_id = inspection.property_id
            WHERE inspection.id = p_inspection
              AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                              WHERE ending.link_id = link.id)
            ORDER BY link.telegram_user_id, link.linked_at DESC
        ) AS person
    $$;

    -- The message's fields, with the words in the person's language.
    CREATE FUNCTION app.telegram_joint_inspection_details(p_inspection uuid, p_language text)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        SELECT jsonb_build_object(
            'number', inspection.inspection_number,
            'unit', unit.unit_number,
            'kind', CASE
                WHEN inspection.kind = 'MOVE_IN' AND p_language = 'km' THEN 'ពេលចូលស្នាក់នៅ'
                WHEN inspection.kind = 'MOVE_IN' THEN 'move-in'
                WHEN p_language = 'km' THEN 'ពេលចាកចេញ'
                ELSE 'move-out' END,
            'date', to_char(inspection.inspection_date, 'DD/MM/YYYY'))
        FROM app.joint_inspections AS inspection
        JOIN app.units AS unit ON unit.id = inspection.unit_id
        WHERE inspection.id = p_inspection
    $$;

    -- Queue the copy for each person who has not had it yet.
    CREATE FUNCTION app.telegram_queue_joint_inspection(p_inspection uuid, p_actor uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_done timestamptz;
        v_person record;
        v_outbox uuid;
        v_count integer := 0;
    BEGIN
        SELECT inspection.done_at INTO v_done FROM app.joint_inspections AS inspection
        WHERE inspection.id = p_inspection AND inspection.status IN ('DONE', 'REPLACED');
        IF v_done IS NULL THEN
            RETURN 0;
        END IF;
        FOR v_person IN SELECT * FROM app.telegram_joint_inspection_people(p_inspection) AS person
            WHERE person.linked_at <= v_done + interval '{LINK_DAYS_AFTER} day'
              AND NOT EXISTS (SELECT 1 FROM app.telegram_joint_inspection_notices AS notice
                              WHERE notice.inspection_id = p_inspection
                                AND notice.telegram_user_id = person.telegram_user_id)
        LOOP
            INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code, language,
                details, keyboard, created_by)
            VALUES (v_person.property_id, 'TENANT', v_person.telegram_user_id,
                'tenant.joint_inspection', v_person.language,
                app.telegram_joint_inspection_details(p_inspection, v_person.language),
                NULL, p_actor)
            RETURNING id INTO v_outbox;
            INSERT INTO app.telegram_joint_inspection_notices (property_id, inspection_id,
                telegram_user_id, outbox_id)
            VALUES (v_person.property_id, p_inspection, v_person.telegram_user_id, v_outbox);
            v_count := v_count + 1;
        END LOOP;
        RETURN v_count;
    END $$;

    -- Run by the pull job: the Joint Inspections Done in the last {RECENT_DAYS} days.
    CREATE FUNCTION app.telegram_joint_inspections_queue(p_property uuid, p_actor uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_inspection uuid;
        v_count integer := 0;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        FOR v_inspection IN
            SELECT inspection.id FROM app.joint_inspections AS inspection
            WHERE inspection.property_id = p_property
              AND inspection.status IN ('DONE', 'REPLACED')
              AND inspection.done_at >= statement_timestamp() - interval '{RECENT_DAYS} days'
            ORDER BY inspection.done_at, inspection.id
        LOOP
            v_count := v_count + app.telegram_queue_joint_inspection(v_inspection, p_actor);
        END LOOP;
        RETURN v_count;
    END $$;

    -- The send job: the inspection of a copy message, as the app shows it, with where the two
    -- signatures are kept. NULL when the message is not a Joint Inspection copy.
    CREATE FUNCTION app.telegram_joint_inspection_for_outbox(p_property uuid, p_outbox uuid,
        p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_inspection uuid;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT notice.inspection_id INTO v_inspection
        FROM app.telegram_joint_inspection_notices AS notice
        WHERE notice.outbox_id = p_outbox AND notice.property_id = p_property;
        IF v_inspection IS NULL THEN
            RETURN NULL;
        END IF;
        RETURN jsonb_build_object(
            'inspection', app.joint_inspection_json(v_inspection),
            'files', COALESCE((SELECT jsonb_object_agg(file.id::text, jsonb_build_object(
                    'storage_key', file.storage_key, 'sha256', file.sha256,
                    'media_type', file.media_type))
                FROM app.joint_inspection_files AS file
                WHERE file.inspection_id = v_inspection AND file.removed_at IS NULL
                  AND file.role IN ('TENANT_SIGNATURE', 'STAFF_SIGNATURE')), '{{}}'::jsonb));
    END $$;
"""

RUNTIME = (
    "app.telegram_joint_inspections_queue(uuid, uuid)",
    "app.telegram_joint_inspection_for_outbox(uuid, uuid, uuid)",
)
INTERNAL = (
    "app.telegram_joint_inspection_people(uuid)",
    "app.telegram_joint_inspection_details(uuid, text)",
    "app.telegram_queue_joint_inspection(uuid, uuid)",
)


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    for signature in RUNTIME + INTERNAL:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in RUNTIME:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("the Joint Inspection copy migration is forward-only")
