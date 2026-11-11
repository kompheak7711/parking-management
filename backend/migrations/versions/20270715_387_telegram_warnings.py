# ruff: noqa: E501
"""Telegram bots: a warning goes to the tenants linked to its Lease when staff record it (DL-217).

Owner (11 Nov 2026): CHETANA Residence support sends "any notice or warning", warnings come after
Receipts and notices ("All three, in that order"), and on the card of 11 Nov 2026 the owner chose
"When staff record it": the day-20 and day-30 late Rent letters and Lease warnings go to the
tenant on Telegram as soon as staff record them. Paper stays the official copy.

1. ``app.telegram_warning_notices`` keeps what was queued: one row per warning and Telegram
   account, with its outbox message. It is never changed, and it stops a second message.
2. Staff record the warnings as before: a Lease warning (``app.lease_violation_warnings``) and the
   day-20 warning and day-30 serious nonpayment of a Rent case (``app.rent_nonpayment_events``).
   Cure and authorized follow-up events are not warnings and are not sent. The pull job (about
   once a minute) queues the warnings recorded in the last 3 days that someone linked to the
   Lease has not had yet, in the language each person chose. Guests have no Lease and get none.
   A person who links later gets the warnings of the day before the link too, never older ones.
3. The message says what the paper letter says: for Rent, the Invoice, its Due Date and the Rent
   still to pay when staff recorded it; for a Lease warning, its number, date, what happened and
   the Lease rule, as staff wrote them. Every message says the paper letter is the official copy.
   Nothing in it ends a Lease or adds a charge.
4. ``app.telegram_warnings_page`` (``telegram.read``) lists the warnings of the last 90 days with
   who got them, so staff see who still needs the letter by hand.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule; the sending rule is the
owner's card.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270715_387"
down_revision: str | None = "20270714_386"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PAGE_DAYS = 90
# Warnings newer than this are sent; a person gets those recorded from a day before the link.
RECENT_DAYS = 3
LINK_DAYS_BACK = 1

TABLES = """
    CREATE TABLE app.telegram_warning_notices (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        warning_kind text NOT NULL CHECK (warning_kind IN ('LEASE_WARNING', 'RENT_20', 'RENT_30')),
        lease_warning_id uuid REFERENCES app.lease_violation_warnings (id) ON DELETE RESTRICT,
        rent_event_id uuid REFERENCES app.rent_nonpayment_events (id) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        outbox_id uuid NOT NULL UNIQUE REFERENCES app.telegram_outbox (id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        CONSTRAINT telegram_warning_notices_source CHECK (
            (warning_kind = 'LEASE_WARNING' AND lease_warning_id IS NOT NULL AND rent_event_id IS NULL)
            OR (warning_kind IN ('RENT_20', 'RENT_30') AND rent_event_id IS NOT NULL
                AND lease_warning_id IS NULL)),
        CONSTRAINT telegram_warning_notices_lease_once UNIQUE (lease_warning_id, telegram_user_id),
        CONSTRAINT telegram_warning_notices_rent_once UNIQUE (rent_event_id, telegram_user_id)
    );
    CREATE INDEX telegram_warning_notices_property_idx
        ON app.telegram_warning_notices (property_id, created_at DESC);

    CREATE TRIGGER telegram_warning_notices_append_only BEFORE UPDATE OR DELETE
        ON app.telegram_warning_notices FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER telegram_warning_notices_no_truncate BEFORE TRUNCATE
        ON app.telegram_warning_notices FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    REVOKE ALL ON app.telegram_warning_notices FROM PUBLIC;
"""

FUNCTIONS = f"""
    -- The warnings of a Property recorded since p_since: Lease warnings and the day-20 and day-30
    -- Rent milestones.
    CREATE FUNCTION app.telegram_warnings_since(p_property uuid, p_since timestamptz)
    RETURNS TABLE (kind text, source_id uuid, lease_id uuid, occurred_at timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        SELECT 'LEASE_WARNING', warning.id, warning.lease_id, warning.occurred_at
        FROM app.lease_violation_warnings AS warning
        JOIN app.leases AS lease ON lease.id = warning.lease_id
        JOIN app.units AS unit ON unit.id = lease.unit_id
        WHERE unit.property_id = p_property AND warning.occurred_at >= p_since
        UNION ALL
        SELECT CASE event.event_kind WHEN 'TWENTY_DAY_WARNING' THEN 'RENT_20' ELSE 'RENT_30' END,
            event.id, rent_case.lease_id, event.occurred_at
        FROM app.rent_nonpayment_events AS event
        JOIN app.rent_nonpayment_cases AS rent_case ON rent_case.id = event.rent_nonpayment_case_id
        JOIN app.leases AS lease ON lease.id = rent_case.lease_id
        JOIN app.units AS unit ON unit.id = lease.unit_id
        WHERE unit.property_id = p_property AND event.occurred_at >= p_since
          AND event.event_kind IN ('TWENTY_DAY_WARNING', 'THIRTY_DAY_SERIOUS_DEFAULT')
    $$;

    -- The warning message's fields, with the dates as the tenant reads them.
    CREATE FUNCTION app.telegram_warning_details(p_kind text, p_source uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_details jsonb;
    BEGIN
        IF p_kind = 'LEASE_WARNING' THEN
            SELECT jsonb_build_object(
                    'sequence', warning.warning_sequence,
                    'unit', unit.unit_number,
                    'date', to_char(warning.warning_date, 'DD/MM/YYYY'),
                    'when', to_char(warning.violation_date, 'DD/MM/YYYY'),
                    'text', warning.violation_description,
                    'rule', warning.lease_provision)
            INTO v_details
            FROM app.lease_violation_warnings AS warning
            JOIN app.leases AS lease ON lease.id = warning.lease_id
            JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE warning.id = p_source;
        ELSE
            SELECT jsonb_build_object(
                    'unit', unit.unit_number,
                    'invoice', invoice.invoice_number,
                    'due', to_char(rent_case.due_date_snapshot, 'DD/MM/YYYY'),
                    'amount', app.telegram_usd(event.remaining_rent_usd_cents),
                    'date', to_char(event.event_date, 'DD/MM/YYYY'))
            INTO v_details
            FROM app.rent_nonpayment_events AS event
            JOIN app.rent_nonpayment_cases AS rent_case ON rent_case.id = event.rent_nonpayment_case_id
            JOIN app.invoices AS invoice ON invoice.id = rent_case.invoice_id
            JOIN app.leases AS lease ON lease.id = rent_case.lease_id
            JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE event.id = p_source;
        END IF;
        IF v_details IS NULL THEN
            RAISE EXCEPTION 'Unknown warning' USING ERRCODE = '22023';
        END IF;
        RETURN v_details;
    END $$;

    -- Run by the pull job: the warnings of the last {RECENT_DAYS} days not yet sent to a live link
    -- of their Lease.
    CREATE FUNCTION app.telegram_warnings_queue(p_property uuid, p_actor uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_warning record;
        v_person record;
        v_details jsonb;
        v_outbox uuid;
        v_count integer := 0;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        FOR v_warning IN
            SELECT * FROM app.telegram_warnings_since(p_property,
                statement_timestamp() - interval '{RECENT_DAYS} days') AS warning
            ORDER BY warning.occurred_at, warning.source_id
        LOOP
            v_details := NULL;
            FOR v_person IN
                SELECT DISTINCT ON (link.telegram_user_id) link.telegram_user_id,
                    COALESCE((SELECT choice.language FROM app.telegram_language_choices AS choice
                              WHERE choice.bot_code = 'TENANT'
                                AND choice.telegram_user_id = link.telegram_user_id
                              ORDER BY choice.chosen_at DESC LIMIT 1), 'km') AS language
                FROM app.tenant_telegram_links AS link
                WHERE link.property_id = p_property AND link.lease_id = v_warning.lease_id
                  AND link.linked_at - interval '{LINK_DAYS_BACK} day' <= v_warning.occurred_at
                  AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                                  WHERE ending.link_id = link.id)
                  AND app.tenant_link_stay_live(link.lease_id, link.booking_id,
                                                app.gl_today(p_property))
                  AND NOT EXISTS (SELECT 1 FROM app.telegram_warning_notices AS notice
                                  WHERE notice.telegram_user_id = link.telegram_user_id
                                    AND (notice.lease_warning_id = v_warning.source_id
                                         OR notice.rent_event_id = v_warning.source_id))
                ORDER BY link.telegram_user_id, link.linked_at DESC
            LOOP
                v_details := COALESCE(v_details,
                    app.telegram_warning_details(v_warning.kind, v_warning.source_id));
                INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code, language,
                    details, keyboard, created_by)
                VALUES (p_property, 'TENANT', v_person.telegram_user_id,
                    CASE v_warning.kind WHEN 'LEASE_WARNING' THEN 'tenant.lease_warning'
                         WHEN 'RENT_20' THEN 'tenant.rent_warning'
                         ELSE 'tenant.rent_default' END,
                    v_person.language, v_details, NULL, p_actor)
                RETURNING id INTO v_outbox;
                INSERT INTO app.telegram_warning_notices (property_id, warning_kind,
                    lease_warning_id, rent_event_id, telegram_user_id, outbox_id)
                VALUES (p_property, v_warning.kind,
                    CASE WHEN v_warning.kind = 'LEASE_WARNING' THEN v_warning.source_id END,
                    CASE WHEN v_warning.kind <> 'LEASE_WARNING' THEN v_warning.source_id END,
                    v_person.telegram_user_id, v_outbox);
                v_count := v_count + 1;
            END LOOP;
        END LOOP;
        RETURN v_count;
    END $$;

    -- The warnings of the last {PAGE_DAYS} days and who got them on Telegram.
    CREATE FUNCTION app.telegram_warnings_page(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_rows jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.read', p_property);
        SELECT COALESCE(jsonb_agg(jsonb_build_object(
                'id', warning.source_id, 'kind', warning.kind,
                'unit_number', unit.unit_number, 'customer', customer.legal_name,
                'recorded_at', warning.occurred_at,
                'sent', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                        'telegram_user_id', notice.telegram_user_id,
                        'queued_at', notice.created_at,
                        'state', COALESCE(final.outcome, 'WAITING'),
                        'sent_at', final.attempted_at) ORDER BY notice.created_at)
                    FROM app.telegram_warning_notices AS notice
                    LEFT JOIN app.telegram_outbox_attempts AS final
                      ON final.outbox_id = notice.outbox_id AND final.outcome IN ('SENT', 'GAVE_UP')
                    WHERE notice.lease_warning_id = warning.source_id
                       OR notice.rent_event_id = warning.source_id), '[]'::jsonb))
                ORDER BY warning.occurred_at DESC, warning.source_id), '[]'::jsonb)
        INTO v_rows
        FROM app.telegram_warnings_since(p_property,
                statement_timestamp() - interval '{PAGE_DAYS} days') AS warning
        JOIN app.leases AS lease ON lease.id = warning.lease_id
        JOIN app.units AS unit ON unit.id = lease.unit_id
        JOIN app.customers AS customer ON customer.id = lease.primary_tenant_id;
        RETURN jsonb_build_object('warnings', v_rows, 'rules', jsonb_build_object('days', {PAGE_DAYS}));
    END $$;
"""

RUNTIME = (
    "app.telegram_warnings_queue(uuid, uuid)",
    "app.telegram_warnings_page(uuid, uuid)",
)
INTERNAL = (
    "app.telegram_warnings_since(uuid, timestamptz)",
    "app.telegram_warning_details(text, uuid)",
)


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    for signature in RUNTIME + INTERNAL:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in RUNTIME:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("the Tenant bot warning migration is forward-only")
